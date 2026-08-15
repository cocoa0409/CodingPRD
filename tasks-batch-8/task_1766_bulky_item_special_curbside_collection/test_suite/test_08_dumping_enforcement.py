"""Dumping reports: determination consistency, illegal-dumping cascade,
fine escalation, household suspension/reinstatement cycle, and RBAC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_item,
    create_draft_request,
    create_dumping_report_payload,
    create_household,
    create_route_day,
    determine_payload,
    find_assessment,
    get_household_assessments,
    get_request,
    get_route_day,
    get_success_data,
    make_resident_headers,
    set_clock,
    setup_scheduled_request,
    setup_submitted_request,
    submit_request,
    suspend_household_via_illegal_dumping,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
DRIVER = TEST_USERS["driver_headers"]


def _get_household(api, household_id):
    return get_success_data(api.get_household(household_id, INSPECTOR))


class TestIllegalDumpingCascade:
    def _setup(self, api):
        set_clock("2026-08-05T00:00:00Z")
        rd = create_route_day(service_zone="ZONE_NORTH", route_date="2026-08-10")
        hh, req, _ = setup_submitted_request(
            street_address="5 Walnut Way", service_zone="ZONE_NORTH",
            annual_allowance_items=4,
            items=((1, "STANDARD_FURNITURE", False, True),),
        )
        report = get_success_data(api.create_dumping_report(
            create_dumping_report_payload(hh["id"]), INSPECTOR
        ))
        return hh, req, rd, report

    def test_illegal_determination_creates_fine_and_suspends(self, api):
        """PRD §3.6: "An illegal determination fires the deepest cascade in
        the system. It creates a `PENDING` FeeAssessment of `kind`
        `ILLEGAL_DUMPING_FINE` owned by the report's household: when the
        report links a request, the fine's `pickup_request_id` carries it;
        otherwise the fine stands unlinked against the household alone."
        PRD §3.6: "no priors yields 25000 cents, one prior 50000, two priors
        100000, and three or more priors 200000 cents. Transitively, the
        household's `status` flips to `SUSPENDED` with `suspension_reason`
        set, bumping the Household's `version`"

        Design: Difficulty/transitive_cascade/illegal_dumping_cascade_depth3
        """
        hh, req, rd, report = self._setup(api)
        det = get_success_data(api.determine_dumping_report(
            report["id"],
            determine_payload("ILLEGAL_DUMPING",
                              determination_notes="unclaimed set-out"),
            INSPECTOR,
        ))
        assert det["status"] == "DETERMINED_ILLEGAL"

        fine = find_assessment(
            get_household_assessments(hh["id"]), "ILLEGAL_DUMPING_FINE"
        )
        assert fine["amount_cents"] == 25000
        assert fine["household_id"] == hh["id"]
        assert fine["pickup_request_id"] is None
        assert fine["status"] == "PENDING"

        hh_after = _get_household(api, hh["id"])
        assert hh_after["status"] == "SUSPENDED"
        assert hh_after["suspension_reason"] == "ILLEGAL_DUMPING"

    def test_suspension_gates_subsequent_schedule(self, api):
        """PRD §3.6: "and from then on the standing gate of §3.1 rejects that
        household's request creation, submission, and scheduling attempts."
        PRD §3.1: "creating a new pickup request, submitting one, or
        scheduling one are all rejected with `ERR_HOUSEHOLD_SUSPENDED`."

        Design: Difficulty/transitive_cascade/illegal_dumping_cascade_depth3
        """
        hh, req, rd, report = self._setup(api)
        get_success_data(api.determine_dumping_report(
            report["id"],
            determine_payload("ILLEGAL_DUMPING",
                              determination_notes="unclaimed set-out"),
            INSPECTOR,
        ))
        resp = api.schedule_pickup_request(
            req["id"],
            {"route_day_id": rd["id"],
             "expected_route_day_version": rd["version"]},
            make_resident_headers(hh["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_SUSPENDED)
        assert resp.status_code == 409


class TestSuspensionReinstatementCycle:
    def test_household_suspended_between_determination_and_reinstatement(self, api):
        """PRD §3.1: "Reinstatement is Inspector-only and is gated on fiscal
        settlement: every `ILLEGAL_DUMPING_FINE` assessment owned by that
        household — whether linked to a pickup request or unlinked — must have
        reached `SETTLED` or `WAIVED` before the reinstatement clears
        `suspension_reason` and returns the household to `ACTIVE`, bumping its
        `version`."

        Design: Difficulty/non_linear_state_machine/household_suspension_reinstatement_cycle
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("44 Maple Dr", "ZONE_EAST", annual_allowance_items=4)
        report, fine = suspend_household_via_illegal_dumping(
            hh["id"], notes="no scheduled pickup on file"
        )

        mid = _get_household(api, hh["id"])
        assert mid["status"] == "SUSPENDED"
        assert fine["amount_cents"] == 25000
        assert fine["pickup_request_id"] is None
        assert fine["household_id"] == hh["id"]

        get_success_data(api.waive_fee_assessment(fine["id"], DISPATCHER))
        reinstated = get_success_data(
            api.reinstate_household(hh["id"], INSPECTOR)
        )
        assert reinstated["status"] == "ACTIVE"

    def test_reinstatement_clears_suspension_reason(self, api):
        """PRD §3.1: "every `ILLEGAL_DUMPING_FINE` assessment owned by that
        household — whether linked to a pickup request or unlinked — must have
        reached `SETTLED` or `WAIVED` before the reinstatement clears
        `suspension_reason` and returns the household to `ACTIVE`, bumping its
        `version`."

        Design: Difficulty/non_linear_state_machine/household_suspension_reinstatement_cycle
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("46 Maple Dr", "ZONE_EAST", annual_allowance_items=4)
        _, fine = suspend_household_via_illegal_dumping(hh["id"])
        get_success_data(api.waive_fee_assessment(fine["id"], DISPATCHER))
        reinstated = get_success_data(
            api.reinstate_household(hh["id"], INSPECTOR)
        )
        assert reinstated["status"] == "ACTIVE"
        assert reinstated["suspension_reason"] is None


class TestFineEscalation:
    def test_illegal_dumping_fine_escalates_with_priors(self, api):
        """PRD §3.6: "The system counts the household's prior confirmed
        violations — dumping reports already `DETERMINED_ILLEGAL` with a
        `reported_at` strictly earlier than this report's `reported_at`, ties
        broken by `created_at` ascending — and the fine is the 25000-cent base
        fine doubled once per prior violation, capped at three doublings: no
        priors yields 25000 cents, one prior 50000, two priors 100000, and
        three or more priors 200000 cents."

        Design: Corner/calculations/illegal_dumping_fine_escalates_with_priors
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("51 Fine St", "ZONE_WEST")

        # First offense.
        _, fine1 = suspend_household_via_illegal_dumping(hh["id"])
        assert fine1["amount_cents"] == 25000

        # Restore standing, then file a second (later) report.
        get_success_data(api.waive_fee_assessment(fine1["id"], DISPATCHER))
        get_success_data(api.reinstate_household(hh["id"], INSPECTOR))
        set_clock("2026-08-06T00:00:00Z")
        report2 = get_success_data(api.create_dumping_report(
            create_dumping_report_payload(hh["id"]), INSPECTOR
        ))
        get_success_data(api.determine_dumping_report(
            report2["id"], determine_payload("ILLEGAL_DUMPING"), INSPECTOR
        ))

        fines = [
            a for a in get_household_assessments(hh["id"])
            if a["kind"] == "ILLEGAL_DUMPING_FINE"
        ]
        amounts = sorted(a["amount_cents"] for a in fines)
        assert amounts == [25000, 50000]


class TestDeterminationConsistency:
    def _setup(self, api):
        set_clock("2026-08-05T00:00:00Z")
        hh, req, _, rd = setup_scheduled_request(
            street_address="81 Determination Dr", service_zone="ZONE_NORTH",
            route_date="2026-08-10",
        )
        set_clock("2026-08-10T12:00:00Z")
        linked = get_success_data(api.create_dumping_report(
            create_dumping_report_payload(hh["id"], pickup_request_id=req["id"]),
            INSPECTOR,
        ))
        unlinked = get_success_data(api.create_dumping_report(
            create_dumping_report_payload(hh["id"]), INSPECTOR
        ))
        return hh, req, linked, unlinked

    def test_authorized_without_linked_schedule_rejected(self, api):
        """PRD §3.6: "The determination value `AUTHORIZED_SETOUT` — the
        material was placed within one day of a genuinely scheduled pickup for
        that household — requires that the report links a request, that the
        linked request is currently `SCHEDULED`, and that its `scheduled_date`
        falls within the inclusive window from one day before to one day after
        the `reported_at` date"
        PRD §3.6: "Issuing a determination inconsistent with the linked
        evidence — authorized without the qualifying link, or illegal while
        the qualifying link exists — fails with
        `ERR_DETERMINATION_INCONSISTENT`."

        Design: Corner/validations/determination_authorized_requires_linked_schedule
        """
        hh, req, linked, unlinked = self._setup(api)
        resp = api.determine_dumping_report(
            unlinked["id"], determine_payload("AUTHORIZED_SETOUT"), INSPECTOR
        )
        validate_error(resp, ApiErrorId.ERR_DETERMINATION_INCONSISTENT)
        assert resp.status_code == 422

    def test_authorized_with_linked_schedule_succeeds(self, api):
        """PRD §3.6: "The determination value `AUTHORIZED_SETOUT` — the
        material was placed within one day of a genuinely scheduled pickup for
        that household — requires that the report links a request, that the
        linked request is currently `SCHEDULED`, and that its `scheduled_date`
        falls within the inclusive window from one day before to one day after
        the `reported_at` date; it moves the report to `DETERMINED_AUTHORIZED`"

        Design: Corner/validations/determination_authorized_requires_linked_schedule
        """
        hh, req, linked, unlinked = self._setup(api)
        det = get_success_data(api.determine_dumping_report(
            linked["id"],
            determine_payload("AUTHORIZED_SETOUT",
                              determination_notes="matches scheduled pickup"),
            INSPECTOR,
        ))
        assert det["status"] == "DETERMINED_AUTHORIZED"


class TestDumpingRbac:
    def test_driver_cannot_determine_dumping_report(self, api):
        """PRD §2.1: "Only an `Inspector` may determine a dumping report or
        reinstate a suspended household."
        PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/driver_cannot_determine_dumping_report
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("107 Duty Dr", "ZONE_NORTH")
        report = get_success_data(api.create_dumping_report(
            create_dumping_report_payload(hh["id"]), DRIVER
        ))
        resp = api.determine_dumping_report(
            report["id"], determine_payload("DISMISSED"), DRIVER
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403
        after = get_success_data(api.get_dumping_report(report["id"], INSPECTOR))
        assert after["status"] == "OPEN"

    def test_resident_cannot_waive_own_fine(self, api):
        """PRD §3.5: "A `Dispatcher` may instead waive any `PENDING`
        assessment, moving it to `WAIVED` with the same timestamp and version
        semantics — note the segregation of duties: waiver is Dispatcher-only,
        while dumping determinations and reinstatements are Inspector-only."

        Design: Corner/rbac/resident_cannot_waive_own_fine
        """
        set_clock("2026-08-05T00:00:00Z")
        hh = create_household("109 Waiver Way", "ZONE_EAST")
        _, fine = suspend_household_via_illegal_dumping(hh["id"])
        resp = api.waive_fee_assessment(fine["id"], make_resident_headers(hh["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert resp.status_code == 403
        after = get_success_data(api.get_fee_assessment(fine["id"], INSPECTOR))
        assert after["status"] == "PENDING"
