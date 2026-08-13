"""Facility partnership: agreements handshake, orientation cycle, waivers,
and the agreement-loss cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_active_handler,
    create_forming_team,
    create_request_ok,
    get_facility,
    get_orientation_record,
    get_visit,
    get_visit_request,
    offer_request_ok,
    accept_request_ok,
    register_animal,
    run_sweeps,
    schedule_visit_ok,
    set_clock,
    setup_active_facility,
    setup_certified_team_at_facility,
    sign_waiver,
    complete_orientation,
    make_facility_coordinator_headers,
    make_handler_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestAgreementUniqueness:
    def test_second_agreement_for_facility_rejected(self):
        """PRD §3.4: "The partnership agreement is a two-signature handshake. A `ProgramAdmin` drafts it with the `facility_id`, the coverage span `start_on` through `end_on` — the start strictly before the end, both inclusive as coverage dates — the contract caps `agreed_max_visit_minutes` and `insurance_minimum_cents`, and a `terms_version` label; a facility may carry only one agreement in `DRAFT`, `PENDING_FACILITY_SIGNATURE`, `PENDING_PROGRAM_SIGNATURE`, or `ACTIVE` at a time (a second fails with `ERR_ACTIVE_AGREEMENT_EXISTS`)."

        Design: Corner/errors/second_agreement_for_facility_rejected
        """
        fac_ctx = setup_active_facility(name="Fac AG")
        resp = api_client.create_facility_agreement(
            {
                "facility_id": fac_ctx["facility"]["id"],
                "start_on": "2026-08-01", "end_on": "2028-07-31",
                "agreed_max_visit_minutes": 60, "insurance_minimum_cents": 100_000_000,
                "terms_version": "t2",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_ACTIVE_AGREEMENT_EXISTS)


class TestFacilityReinstatement:
    def test_facility_reinstate_requires_active_agreement(self):
        """PRD §3.4: "Reinstatement by a `ComplianceOfficer` requires `SUSPENDED` (otherwise `ERR_FACILITY_NOT_SUSPENDED`) and, critically, an `ACTIVE` agreement already in place (otherwise `ERR_NO_ACTIVE_AGREEMENT`)."
        PRD §3.4: "The same cascade fires when a sweep expires an `ACTIVE` agreement once today passes `end_on`."

        Design: Corner/errors/facility_reinstate_requires_active_agreement
        """
        fac_ctx = setup_active_facility(name="Fac RA", agreement_end="2026-08-10")
        set_clock("2026-08-11T00:00:00Z")
        sweep = run_sweeps()
        assert sweep["agreements_expired"] == 1, (
            "The agreement must be swept to EXPIRED once today passes end_on"
        )
        facility = get_facility(fac_ctx["facility"]["id"])
        assert facility["status"] == "SUSPENDED", (
            "Agreement expiry must cascade the facility to SUSPENDED"
        )
        resp = api_client.reinstate_facility(fac_ctx["facility"]["id"], COMPLIANCE)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AGREEMENT)


class TestOrientationCycle:
    def test_orientation_expiry_reassign_cycle(self):
        """PRD §3.4: "Completion — by a coordinator of the same facility (`ERR_OWNERSHIP_MISMATCH`) on an `ASSIGNED` record (otherwise `ERR_ORIENTATION_NOT_ASSIGNED`) — records the `attended_on` date, which may not lie in the future (`ERR_ORIENTATION_DATE_FUTURE`), and sets `expires_on` to `attended_on` plus three hundred sixty-five days. A sweep expires a `COMPLETED` record once today passes `expires_on`, and a coordinator may re-assign an `EXPIRED` record (otherwise `ERR_ORIENTATION_NOT_EXPIRED`), which clears `attended_on` and `expires_on` and returns it to `ASSIGNED` — the cycle begins again."

        Design: Corner/state_machines/orientation_expiry_reassign_cycle
        """
        handler = create_active_handler(full_name="H OR")
        animal = register_animal(handler["id"], name="D")
        team = create_forming_team(handler["id"], animal["id"], "TOR")
        facility = validate_success(api_client.create_facility(
            {
                "name": "Fac O", "facility_type": "SCHOOL", "region_code": "WA",
                "max_visit_minutes": 60, "allowed_species": ["DOG"],
                "min_liability_coverage_cents": 100_000_000,
                "max_overlapping_teams": 2, "visits_per_week_cap": 5,
            }, ADMIN,
        ), 201)
        set_clock("2026-08-02T00:00:00Z")
        orientation = complete_orientation(team["id"], facility["id"], attended_on="2026-08-02")
        assert orientation["status"] == "COMPLETED"
        assert orientation["expires_on"] == "2027-08-02", (
            "expires_on must be attended_on + 365 days"
        )

        set_clock("2027-08-03T00:00:00Z")  # past expires_on 2027-08-02
        sweep = run_sweeps()
        assert sweep["orientations_expired"] == 1
        expired = get_orientation_record(orientation["id"])
        assert expired["status"] == "EXPIRED"

        reassigned = validate_success(
            api_client.reassign_orientation_record(
                orientation["id"], make_facility_coordinator_headers(facility["id"])
            )
        )
        assert reassigned["status"] == "ASSIGNED", "The cycle must reuse the same row"
        assert reassigned["attended_on"] is None, "attended_on must be cleared"
        assert reassigned["expires_on"] is None, "expires_on must be cleared"


class TestWaiverUniqueness:
    def test_duplicate_waiver_rejected(self):
        """PRD §3.4: "The liability waiver is the team's signature on the facility's terms. A handler signs one for an owned team by supplying the `team_id`, `facility_id`, `waiver_version`, and `signed_on` date; the record starts `SIGNED`, and only one `SIGNED` waiver may exist for a given team–facility–version triple (a duplicate fails with `ERR_WAIVER_ALREADY_EXISTS`)."

        Design: Corner/errors/duplicate_waiver_rejected
        """
        handler = create_active_handler(full_name="H DW")
        animal = register_animal(handler["id"], name="D")
        team = create_forming_team(handler["id"], animal["id"], "TDW")
        facility = validate_success(api_client.create_facility(
            {
                "name": "Fac W", "facility_type": "SCHOOL", "region_code": "WA",
                "max_visit_minutes": 60, "allowed_species": ["DOG"],
                "min_liability_coverage_cents": 100_000_000,
                "max_overlapping_teams": 2, "visits_per_week_cap": 5,
            }, ADMIN,
        ), 201)
        sign_waiver(handler["id"], team["id"], facility["id"], signed_on="2026-08-01")
        resp = api_client.create_liability_waiver(
            {
                "team_id": team["id"], "facility_id": facility["id"],
                "waiver_version": "v1", "signed_on": "2026-08-01",
            },
            make_handler_headers(handler["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_ALREADY_EXISTS)


class TestAgreementTerminationCascade:
    def _setup_agreement_loss_scenario(self):
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H K", "team_name": "TK"},
            facility_kwargs={"name": "School J", "visits_per_week_cap": 8},
        )
        accepted = self._accept(ctx, "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z",
                                visit_program="GENERAL", priority="ROUTINE")
        r2 = create_request_ok(ctx["facility"]["id"], "2026-08-12T14:00:00Z",
                               "2026-08-12T15:00:00Z", visit_program="READING",
                               priority="HIGH")
        v_dir = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-11T10:00:00Z", "2026-08-11T10:30:00Z")
        return ctx, accepted["request"], accepted["visit"], r2, v_dir

    @staticmethod
    def _accept(ctx, start, end, **kwargs):
        request = create_request_ok(ctx["facility"]["id"], start, end, **kwargs)
        offer_request_ok(request["id"], ctx["team"]["id"])
        visit = accept_request_ok(request["id"], ctx["handler"]["id"])
        return {"request": request, "visit": visit}

    def test_agreement_termination_suspends_facility(self):
        """PRD §3.4: "Agreement loss is a full teardown. Terminating an `ACTIVE` agreement — available to a `ProgramAdmin` or to the facility's own coordinator, otherwise `ERR_AGREEMENT_NOT_ACTIVE` or `ERR_OWNERSHIP_MISMATCH` — moves the agreement to `TERMINATED`, records the supplied `reason` in `terminated_reason`, and cascades: the facility drops `ACTIVE → SUSPENDED`; every `SCHEDULED` visit at the facility is cancelled with `cancel_reason` `AGREEMENT_ENDED` and the animals' `forward_workload_minutes` decremented; request-backed cancelled visits return their requests to `OPEN`; and every visit request of the facility still `OPEN` or `OFFERED` moves to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/agreement_termination_cascade
        """
        ctx, _r1, _v_req, _r2, _v_dir = self._setup_agreement_loss_scenario()
        terminated = validate_success(
            api_client.terminate_facility_agreement(
                ctx["agreement"]["id"], {"reason": "facility closure"}, ADMIN
            )
        )
        assert terminated["status"] == "TERMINATED"
        assert terminated["terminated_reason"] == "facility closure"
        facility = get_facility(ctx["facility"]["id"])
        assert facility["status"] == "SUSPENDED", (
            "Hop 1: the facility must drop ACTIVE -> SUSPENDED on agreement loss"
        )

    def test_agreement_termination_cancels_visits_and_withdraws_requests(self):
        """PRD §3.4: "Agreement loss is a full teardown. Terminating an `ACTIVE` agreement — available to a `ProgramAdmin` or to the facility's own coordinator, otherwise `ERR_AGREEMENT_NOT_ACTIVE` or `ERR_OWNERSHIP_MISMATCH` — moves the agreement to `TERMINATED`, records the supplied `reason` in `terminated_reason`, and cascades: the facility drops `ACTIVE → SUSPENDED`; every `SCHEDULED` visit at the facility is cancelled with `cancel_reason` `AGREEMENT_ENDED` and the animals' `forward_workload_minutes` decremented; request-backed cancelled visits return their requests to `OPEN`; and every visit request of the facility still `OPEN` or `OFFERED` moves to `WITHDRAWN`."

        Design: Difficulty/transitive_cascade/agreement_termination_cascade
        """
        ctx, r1, v_req, r2, v_dir = self._setup_agreement_loss_scenario()
        validate_success(
            api_client.terminate_facility_agreement(
                ctx["agreement"]["id"], {"reason": "facility closure"}, ADMIN
            )
        )
        direct = get_visit(v_dir["id"])
        assert direct["lifecycle_status"] == "CANCELLED"
        assert direct["cancel_reason"] == "AGREEMENT_ENDED", (
            "Hop 2: SCHEDULED visits cancel with cancel_reason AGREEMENT_ENDED"
        )
        backed = get_visit(v_req["id"])
        assert backed["lifecycle_status"] == "CANCELLED"
        assert backed["cancel_reason"] == "AGREEMENT_ENDED"
        r1_after = get_visit_request(r1["id"])
        r2_after = get_visit_request(r2["id"])
        # Hop 3: the backed request first reopens to OPEN, then the withdrawal
        # sweep of the same cascade takes every OPEN/OFFERED request to WITHDRAWN.
        assert r1_after["status"] == "WITHDRAWN"
        assert r2_after["status"] == "WITHDRAWN"
