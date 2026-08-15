"""Location changes: owner-scoped submission, pending guards, termination guard,
deferred effectuation, the effectuation cascade, and OCC on the change version."""
from test_helpers import (
    ApiErrorId,
    approve_location_change,
    create_employee,
    create_location_change_payload,
    create_work_location,
    get_employer,
    get_success_data,
    make_employee_headers,
    open_nexus_case,
    recompute_nexus_case,
    set_clock,
    setup_employee_or_to_nj,
    submit_location_change,
    validate_error,
    validate_success,
)


class TestLocationChangeSubmission:
    def test_employee_submit_own_location_change_positive(self, api):
        """PRD §3.6: "Submission is `Employee`-only and owner-scoped: the payload
        carries `employee_id`, the destination `to_work_location_id`, the
        `effective_date` of the move (which may lie in the past for retroactive
        corrections), and a free-text `reason`. The new LocationChange starts
        `PENDING_REVIEW`; a `from_location_snapshot` captures the employee's current
        `work_location_id`, `state_code`, and `label` at creation, and
        `submitted_by_user_id` records the submitter."

        Design: Corner/rbac/employee_submit_own_location_change_positive
        """
        scenario = setup_employee_or_to_nj(employee_ref="E-6002")
        employee = scenario["employee"]
        res = submit_location_change(
            employee, scenario["nj_location"]["id"],
            effective_date="2026-09-01T00:00:00Z", reason="Moving home",
        )
        change = validate_success(res, 201)
        assert change["status"] == "PENDING_REVIEW"
        assert change["submitted_by_user_id"] == employee["id"]
        snapshot = change["from_location_snapshot"]
        assert snapshot["state_code"] == "OR"
        assert snapshot["work_location_id"] == scenario["or_location"]["id"]
        assert snapshot["label"] == scenario["or_location"]["label"]

    def test_location_change_pending_blocks_second_change(self, api):
        """PRD §3.6: "Only one open change per employee is permitted — an existing
        change in `PENDING_REVIEW` or `APPROVED` blocks a new one with
        `ERR_LOCATION_CHANGE_PENDING`"

        Design: Corner/validations/location_change_pending_blocks_second_change
        """
        scenario = setup_employee_or_to_nj(employee_ref="E-4107")
        employee = scenario["employee"]
        first = submit_location_change(
            employee, scenario["nj_location"]["id"],
            effective_date="2026-09-01T00:00:00Z", reason="First move",
        )
        validate_success(first, 201)
        second = submit_location_change(
            employee, scenario["or_location"]["id"],
            effective_date="2026-10-01T00:00:00Z",
            reason="Second move while first open",
        )
        validate_error(second, ApiErrorId.ERR_LOCATION_CHANGE_PENDING)

    def test_terminated_employee_location_change_rejected(self, api, nexus_analyst_headers):
        """PRD §3.6: "a change for a `TERMINATED` employee is rejected with
        `ERR_EMPLOYEE_NOT_ACTIVE`"
        PRD §3.2: "`TERMINATED` is terminal."

        Design: Corner/validations/terminated_employee_location_change_rejected
        """
        location = create_work_location("OR")
        employee = create_employee(location["id"], employee_ref="E-4111",
                                   full_name="BB One", resident_state_code="OR")
        terminated = validate_success(
            api.terminate_employee(
                employee["id"], {"termination_date": "2026-08-15T00:00:00Z"},
                nexus_analyst_headers,
            ),
            200,
        )
        assert terminated["status"] == "TERMINATED"
        res = api.create_location_change(
            create_location_change_payload(
                employee["id"], location["id"],
                effective_date="2026-09-01T00:00:00Z",
                reason="Move after termination",
            ),
            make_employee_headers(employee["id"]),
        )
        validate_error(res, ApiErrorId.ERR_EMPLOYEE_NOT_ACTIVE)


class TestLocationChangeEffectuationTiming:
    def _setup_approved_future_change(self):
        scenario = setup_employee_or_to_nj(employee_ref="E-2105")
        employee = scenario["employee"]
        change = validate_success(
            submit_location_change(
                employee, scenario["nj_location"]["id"],
                effective_date="2026-09-01T00:00:00Z", reason="Fall relocation",
            ),
            201,
        )
        approve_location_change(change["id"], user_id="na-1")
        return scenario, change

    def test_approved_change_holds_before_effective_date(self, api, tax_director_headers):
        """PRD §3.6: "Effectuation happens on the sweep. Once the clock reaches
        `effective_date`, an `APPROVED` change becomes `EFFECTIVE`"

        Design: Corner/state_machines/location_change_holds_approved_before_effective_date
        """
        _scenario, change = self._setup_approved_future_change()
        set_clock("2026-08-25T00:00:00Z")
        mid = get_success_data(api.get_location_change(change["id"], tax_director_headers))
        assert mid["status"] == "APPROVED", (
            "effective_date 2026-09-01 not yet reached at clock 2026-08-25"
        )

    def test_approved_change_effectuates_at_effective_date(self, api, tax_director_headers):
        """PRD §3.6: "Once the clock reaches `effective_date`, an `APPROVED` change
        becomes `EFFECTIVE` — provided the employee is still `ACTIVE` at sweep time"

        Design: Corner/state_machines/location_change_holds_approved_before_effective_date
        """
        _scenario, change = self._setup_approved_future_change()
        set_clock("2026-08-25T00:00:00Z")
        mid = get_success_data(api.get_location_change(change["id"], tax_director_headers))
        assert mid["status"] == "APPROVED"
        set_clock("2026-09-01T00:00:00Z")
        final = get_success_data(
            api.get_location_change(change["id"], tax_director_headers)
        )
        assert final["status"] == "EFFECTIVE"


class TestLocationChangeEffectuationCascade:
    def _setup_cascade_scenario(self):
        """OR employee (hired 2026-08-01), OR case THRESHOLD_MET at 2026-08-20
        (posture WATCH), NJ case WATCH, APPROVED OR->NJ change effective 2026-08-20."""
        out = setup_employee_or_to_nj(employee_ref="E-701", with_employer=True)
        employee = out["employee"]
        or_case = open_nexus_case("OR")
        nj_case = open_nexus_case("NJ")
        set_clock("2026-08-20T00:00:00Z")
        recompute_nexus_case(or_case["id"])
        employer = get_employer(out["employer"]["id"])
        assert employer["compliance_posture"] == "WATCH", (
            "setup expects WATCH while the OR case is THRESHOLD_MET"
        )
        change = validate_success(
            submit_location_change(
                employee, out["nj_location"]["id"],
                effective_date="2026-08-20T00:00:00Z", reason="Relocating",
            ),
            201,
        )
        approve_location_change(change["id"], user_id="na-1")
        out.update(or_case=or_case, nj_case=nj_case, change=change)
        return out

    def test_effectuation_moves_employee_and_recomputes_nexus(self, api, tax_director_headers):
        """PRD §3.6: "Effectuation is a multi-entity cascade: the employee's
        `current_work_location_id` becomes `to_work_location_id` and the employee's
        `version` increments; the employee's `CURRENT` LocalAssignment is truncated at
        `effective_date` (a zero-length remainder is `SUPERSEDED`) and a new segment is
        created by automatic resolution (`AUTO_GEOCODE`) covering from `effective_date`;
        nexus recompute cascades fire for both the old and the new state, and the
        `WATCH`-to-`THRESHOLD_MET` auto-transitions may fire in either direction"

        Design: Difficulty/transitive_cascade/location_change_effectuation_cascade
        """
        scenario = self._setup_cascade_scenario()
        set_clock("2026-08-20T00:00:00Z")  # sweep effectuates the APPROVED change
        employee = get_success_data(
            api.get_employee(scenario["employee"]["id"], tax_director_headers)
        )
        assert employee["current_work_location_id"] == scenario["nj_location"]["id"]
        or_case = get_success_data(
            api.get_nexus_case(scenario["or_case"]["id"], tax_director_headers)
        )
        assert or_case["employee_days_ytd"] == 19
        assert or_case["status"] == "WATCH", (
            "the cascade recompute auto-transitioned THRESHOLD_MET back to WATCH"
        )
        nj_case = get_success_data(
            api.get_nexus_case(scenario["nj_case"]["id"], tax_director_headers)
        )
        assert nj_case["employee_days_ytd"] == 1, "Aug 20 now attributes to NJ"

    def test_effectuation_posture_returns_to_good_standing(self, api, tax_director_headers):
        """PRD §3.6: "and the Employer's posture recomputes."
        PRD §2.7: "Otherwise it is `WATCH` when any open notice exists, or any
        FilingObligation is `LATE`, or any NexusCase is `THRESHOLD_MET`. Otherwise it
        is `GOOD_STANDING`."

        Design: Difficulty/transitive_cascade/location_change_effectuation_cascade
        """
        scenario = self._setup_cascade_scenario()
        set_clock("2026-08-20T00:00:00Z")
        employer = get_employer(scenario["employer"]["id"])
        assert employer["compliance_posture"] == "GOOD_STANDING", (
            "no open notices, no LATE obligations, no THRESHOLD_MET case remains"
        )


class TestLocationChangePatchOcc:
    def test_occ_location_change_patch_stale_version(self, api, nexus_analyst_headers):
        """PRD §2.8: "Editing a pending LocationChange
        (`PATCH /etax/location-changes/{id}`) requires
        `expected_location_change_version` matching the LocationChange's current
        `version`."
        PRD §2.8: "if that value does not match the parent entity's current `version`,
        the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_location_change_patch_stale_version
        """
        scenario = setup_employee_or_to_nj(employee_ref="E-7004")
        employee = scenario["employee"]
        change = validate_success(
            submit_location_change(
                employee, scenario["nj_location"]["id"],
                effective_date="2026-09-01T00:00:00Z", reason="Move",
            ),
            201,
        )
        observed_version = change["version"]
        first = api.patch_location_change(
            change["id"],
            {
                "effective_date": "2026-09-15T00:00:00Z",
                "expected_location_change_version": observed_version,
            },
            nexus_analyst_headers,
        )
        patched = validate_success(first, 200)
        assert patched["version"] == observed_version + 1, (
            "PRD §3.6: 'each edit increments the change's `version`'"
        )
        assert patched["effective_date"] == "2026-09-15T00:00:00Z"
        stale = api.patch_location_change(
            change["id"],
            {
                "reason": "Changed mind on timing",
                "expected_location_change_version": observed_version,
            },
            nexus_analyst_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
