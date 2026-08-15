"""Minor-servicing exceptions: window schema, tiered duration caps,
segregated determination, and closed-interval window exclusivity."""
from test_helpers import (
    ApiErrorId,
    assert_minor_servicing_exception,
    bootstrap_manager,
    create_exception,
    create_machine,
    create_minor_servicing_exception_payload,
    get_exception,
    make_authorized_employee_headers,
    make_ehs_manager_headers,
    register_employee,
    validate_error,
    validate_success,
)


class TestExceptionCreation:
    def test_window_start_after_end_returns_400(self, api):
        """PRD §3.9: "An `AuthorizedEmployee` requests a determination by
        supplying the `machine_id`, a non-empty `task_description`, three boolean
        criteria — `routine_repetitive`, `integral_to_production`, and
        `alternative_measures_effective` — an `estimated_duration_min` of at
        least 1 minute, and an inclusive validity window whose `valid_from` is
        strictly before its `valid_until`."
        PRD §2.8: "Request-body schema — required fields present, enum members
        valid, arrays honoring their minimum lengths, integer ranges honored
        (`severity` between 1 and 5 inclusive, `estimated_duration_min` at least
        1), and window starts strictly before window ends — otherwise
        `ERR_VALIDATION`."

        Design: Corner/validations/exception_bad_window_returns_invalid_request
        """
        mgr = bootstrap_manager("E-MGR-BW", "Mgr BW")
        requester = register_employee(mgr, "E-W1-BW", "W1 BW")
        machine = create_machine(mgr, asset_tag="A-BW-1", name="Lathe",
                                 area="Bay 37")
        resp = api.create_minor_servicing_exception(
            create_minor_servicing_exception_payload(
                machine["id"], task_description="Bad window",
                estimated_duration_min=15,
                valid_from="2026-09-05T00:00:00Z",
                valid_until="2026-09-01T00:00:00Z"),
            make_authorized_employee_headers(requester["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestTieredDurationCap:
    def _setup_low_machine(self, api, suffix):
        mgr = bootstrap_manager(f"E-MGR-MS{suffix}", "Mgr MS")
        requester = register_employee(mgr, f"E-W1-MS{suffix}", "W1 MS")
        machine = create_machine(mgr, asset_tag=f"A-MS{suffix}-100",
                                 name="Lathe M", area="Line 2")
        assert machine["risk_tier"] == "LOW"
        return mgr, requester, machine

    def test_duration_equal_to_low_cap_is_eligible(self, api):
        """PRD §3.9: "The determination reads the machine's `risk_tier` once, at
        determination time, and applies a duration cap by tier: 480 minutes —
        eight hours — on a `LOW` machine, 120 minutes — two hours — on a `MEDIUM`
        machine, and zero minutes on a `HIGH` machine."
        PRD §3.9: "If any of the three boolean criteria is false, the outcome
        recorded in `determination` is `NOT_ELIGIBLE`. Otherwise, if
        `estimated_duration_min` exceeds the cap, the outcome is `NOT_ELIGIBLE`;
        a duration exactly equal to the cap remains eligible. Otherwise the
        outcome is `ELIGIBLE`."
        PRD §3.9: "The manager's identity is recorded as
        `determined_by_employee_id`, and the exception moves to `DETERMINED`."

        Design: Difficulty/combinatorial_formula/minor_servicing_tiered_cap_boundary
        """
        mgr, requester, machine = self._setup_low_machine(api, "A")
        exception = create_exception(
            requester, machine["id"], task_description="Clear jam at infeed",
            estimated_duration_min=480,
            valid_from="2026-09-01T00:00:00Z", valid_until="2026-09-05T00:00:00Z")

        determined = validate_success(api.determine_minor_servicing_exception(
            exception["id"], make_ehs_manager_headers(mgr["id"])))
        assert_minor_servicing_exception(determined)
        assert determined["determination"] == "ELIGIBLE", \
            "duration 480 equals the LOW cap — the boundary is inclusive"
        assert determined["status"] == "DETERMINED"
        assert determined["determined_by_employee_id"] == mgr["id"]

    def test_duration_one_minute_over_low_cap_is_not_eligible(self, api):
        """PRD §3.9: "The determination reads the machine's `risk_tier` once, at
        determination time, and applies a duration cap by tier: 480 minutes —
        eight hours — on a `LOW` machine, 120 minutes — two hours — on a `MEDIUM`
        machine, and zero minutes on a `HIGH` machine."
        PRD §3.9: "If any of the three boolean criteria is false, the outcome
        recorded in `determination` is `NOT_ELIGIBLE`. Otherwise, if
        `estimated_duration_min` exceeds the cap, the outcome is `NOT_ELIGIBLE`;
        a duration exactly equal to the cap remains eligible. Otherwise the
        outcome is `ELIGIBLE`."

        Design: Difficulty/combinatorial_formula/minor_servicing_tiered_cap_boundary
        """
        mgr, requester, machine = self._setup_low_machine(api, "B")
        exception = create_exception(
            requester, machine["id"], task_description="Clear jam at outfeed",
            estimated_duration_min=481,
            valid_from="2026-09-10T00:00:00Z", valid_until="2026-09-12T00:00:00Z")

        determined = validate_success(api.determine_minor_servicing_exception(
            exception["id"], make_ehs_manager_headers(mgr["id"])))
        assert determined["determination"] == "NOT_ELIGIBLE", \
            "481 minutes exceeds the LOW cap of 480"
        assert determined["status"] == "DETERMINED"


class TestDeterminationSegregation:
    def test_requester_cannot_determine_own_exception(self, api):
        """PRD §3.9: "Determination is segregated: an `EHSManager` runs it, and
        the manager must not be the requester (`ERR_SELF_APPROVAL_FORBIDDEN`)."
        PRD §3.9: "The requester is stamped as `requested_by_employee_id`, the
        `determination` stays null until decided, and the exception starts in
        `PENDING`."

        Design: Corner/validations/requester_cannot_determine_own_exception
        """
        mgr = bootstrap_manager("E-MGR-SD2", "Mgr SD2")
        requester = register_employee(mgr, "E-W1-SD2", "W1 SD2")
        machine = create_machine(mgr, asset_tag="A-SD2-1", name="Lathe",
                                 area="Bay 22")
        exception = create_exception(
            requester, machine["id"], task_description="Clear jam",
            estimated_duration_min=30,
            valid_from="2026-09-01T00:00:00Z", valid_until="2026-09-02T00:00:00Z")

        resp = api.determine_minor_servicing_exception(
            exception["id"], make_ehs_manager_headers(requester["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_APPROVAL_FORBIDDEN)
        after = get_exception(mgr, exception["id"])
        assert after["status"] == "PENDING"
        assert after["determination"] is None


class TestExceptionWindowExclusivity:
    def test_touching_eligible_window_conflicts_disjoint_does_not(self, api):
        """PRD §3.9: "Eligibility is exclusive per machine. When the computed
        outcome is `ELIGIBLE`, the determination is rejected with
        `ERR_EXCEPTION_WINDOW_CONFLICT` if another exception for the same machine
        already sits in `DETERMINED` with an `ELIGIBLE` outcome and a validity
        window overlapping the new one — closed intervals again, so windows that
        merely touch still conflict."

        Design: Corner/validations/exception_window_touch_conflicts
        """
        mgr = bootstrap_manager("E-MGR-EW", "Mgr EW")
        requester = register_employee(mgr, "E-W1-EW", "W1 EW")
        machine = create_machine(mgr, asset_tag="A-EW-1", name="Lathe",
                                 area="Bay 38")
        manager_headers = make_ehs_manager_headers(mgr["id"])

        e1 = create_exception(
            requester, machine["id"], task_description="E1",
            estimated_duration_min=60,
            valid_from="2026-09-01T00:00:00Z", valid_until="2026-09-05T00:00:00Z")
        e2 = create_exception(
            requester, machine["id"], task_description="E2 touching",
            estimated_duration_min=30,
            valid_from="2026-09-05T00:00:00Z", valid_until="2026-09-08T00:00:00Z")
        e3 = create_exception(
            requester, machine["id"], task_description="E3 disjoint",
            estimated_duration_min=30,
            valid_from="2026-09-06T00:00:00Z", valid_until="2026-09-08T00:00:00Z")

        determined_e1 = validate_success(
            api.determine_minor_servicing_exception(e1["id"], manager_headers))
        assert determined_e1["determination"] == "ELIGIBLE"

        resp = api.determine_minor_servicing_exception(e2["id"], manager_headers)
        validate_error(resp, ApiErrorId.ERR_EXCEPTION_WINDOW_CONFLICT)
        assert get_exception(mgr, e2["id"])["status"] == "PENDING", \
            "E2 starts exactly when E1's closed window ends — touching conflicts"

        determined_e3 = validate_success(
            api.determine_minor_servicing_exception(e3["id"], manager_headers))
        assert determined_e3["determination"] == "ELIGIBLE", \
            "E3 is disjoint from E1, and E2 never became ELIGIBLE"
