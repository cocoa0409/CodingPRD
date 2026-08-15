"""Visit creation cross-entity gates, check-in pipeline ordering, and the
post-visit rest block."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instants_equal,
    check_in_visit_ok,
    check_out_visit_ok,
    complete_orientation,
    get_animal,
    get_certification,
    run_sweeps,
    schedule_visit_ok,
    set_clock,
    setup_active_facility,
    setup_certified_team,
    setup_certified_team_at_facility,
    setup_renewable_certification,
    sign_waiver,
    get_team_version,
    create_visit_payload,
    make_facility_coordinator_headers,
    make_handler_headers,
    validate_error,
    validate_success,
    TEST_USERS,
)

ADMIN = TEST_USERS["program_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


class TestVisitCreateRequiresCertificationActive:
    def test_expired_certification_blocks_visit_creation(self):
        """PRD §3.7: "Referential: the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); an `ACTIVE` agreement must cover the facility on the scheduled date (`ERR_NO_ACTIVE_AGREEMENT`); orientation for the team at this facility must be `COMPLETED` and unexpired (`ERR_ORIENTATION_NOT_COMPLETED`); and a `SIGNED` waiver matching the facility's `required_waiver_version` must be on file (`ERR_WAIVER_NOT_ON_FILE`)."
        PRD §3.3: "A sweep moves an `ACTIVE` certification to `RENEWAL_DUE` once today enters the window from sixty days before `expires_on` through `expires_on` itself; once today passes `expires_on`, both `ACTIVE` and `RENEWAL_DUE` certifications move to `EXPIRED`."
        PRD §3.3: "A `ProgramAdmin` renews from `RENEWAL_DUE` or `EXPIRED` (otherwise `ERR_CERT_NOT_RENEWABLE`), but a lapsed certification may only be renewed while today is within ninety days past `expires_on` inclusive — beyond that the window is closed (`ERR_RENEWAL_WINDOW_CLOSED`)."

        Design: Difficulty/cross_entity_state_dependency/visit_create_requires_certification_active
        """
        # The certification gate (pipeline category 9) is only reachable with the
        # team still ACTIVE, so the certification must lapse by EXPIRY (no team
        # cascade) rather than by suspension (which drops the team in step).
        ctx = setup_renewable_certification(
            rabies_until="2031-12-31", policy_until="2031-12-31",
            facility_kwargs={"agreement_end": "2031-06-30"},
        )
        cert_id = ctx["certification"]["id"]
        # Activated 2026-08-02 -> expires_on 2028-08-01; sweep past it. The
        # certification goes EXPIRED while the team stays ACTIVE.
        set_clock("2028-08-02T00:00:00Z")
        run_sweeps()
        assert get_certification(cert_id)["status"] == "EXPIRED"
        blocked = api_client.create_visit(
            create_visit_payload(
                ctx["team"]["id"], ctx["facility"]["id"],
                "2028-08-03T10:00:00Z", "2028-08-03T10:30:00Z",
                get_team_version(ctx["team"]["id"]),
            ),
            ADMIN,
        )
        validate_error(blocked, ApiErrorId.ERR_CERT_NOT_ACTIVE)

        # Renewal (inside the ninety-day grace, six verified visits in the term)
        # restores the certification to ACTIVE, and a fresh orientation cycle
        # covers the new visit date.
        validate_success(api_client.renew_certification(cert_id, ADMIN))
        facility_headers = make_facility_coordinator_headers(ctx["facility"]["id"])
        reassigned = validate_success(
            api_client.reassign_orientation_record(ctx["orientation"]["id"], facility_headers)
        )
        validate_success(
            api_client.complete_orientation_record(
                reassigned["id"], {"attended_on": "2028-08-02"}, facility_headers
            )
        )
        ok = api_client.create_visit(
            create_visit_payload(
                ctx["team"]["id"], ctx["facility"]["id"],
                "2028-08-03T10:00:00Z", "2028-08-03T10:30:00Z",
                get_team_version(ctx["team"]["id"]),
            ),
            ADMIN,
        )
        assert validate_success(ok, 201)["lifecycle_status"] == "SCHEDULED", (
            "The identical payload must succeed once the certification is renewed"
        )

    def test_renewal_due_certification_still_authorizes_visits(self):
        """PRD §3.7: "Referential: the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); an `ACTIVE` agreement must cover the facility on the scheduled date (`ERR_NO_ACTIVE_AGREEMENT`); orientation for the team at this facility must be `COMPLETED` and unexpired (`ERR_ORIENTATION_NOT_COMPLETED`); and a `SIGNED` waiver matching the facility's `required_waiver_version` must be on file (`ERR_WAIVER_NOT_ON_FILE`)."
        PRD §3.3: "A sweep moves an `ACTIVE` certification to `RENEWAL_DUE` once today enters the window from sixty days before `expires_on` through `expires_on` itself; once today passes `expires_on`, both `ACTIVE` and `RENEWAL_DUE` certifications move to `EXPIRED`."

        Design: Difficulty/cross_entity_state_dependency/visit_create_requires_certification_active
        """
        team_ctx = setup_certified_team(handler_name="H X1b", team_name="TX1b")
        fac_ctx = setup_active_facility(name="School Ob", agreement_end="2029-06-30")
        # Orient and sign late enough that both still cover the visit date.
        set_clock("2027-08-01T00:00:00Z")
        complete_orientation(team_ctx["team"]["id"], fac_ctx["facility"]["id"],
                             attended_on="2027-08-01")
        sign_waiver(team_ctx["handler"]["id"], team_ctx["team"]["id"],
                    fac_ctx["facility"]["id"], signed_on="2027-08-01")
        # Activated 2026-08-02 -> expires_on 2028-08-01; 2028-07-02 is inside the
        # renewal window (60 days before expiry).
        set_clock("2028-07-02T00:00:00Z")
        run_sweeps()
        cert = get_certification(team_ctx["certification"]["id"])
        assert cert["status"] == "RENEWAL_DUE"
        visit = schedule_visit_ok(team_ctx["team"]["id"], fac_ctx["facility"]["id"],
                                  "2028-07-03T10:00:00Z", "2028-07-03T10:30:00Z")
        assert visit["lifecycle_status"] == "SCHEDULED", (
            "RENEWAL_DUE is an authorized certification state for visit scheduling"
        )


class TestReferentialBeatsTemporal:
    def _setup_voided_waiver(self):
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H U", "team_name": "TU"},
            facility_kwargs={"name": "School L"},
        )
        first = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        validate_success(
            api_client.void_liability_waiver(
                ctx["waiver"]["id"], {"reason": "superseded terms"}, COMPLIANCE
            )
        )
        return ctx, first

    def test_voided_waiver_masks_team_scheduling_conflict(self):
        """PRD §2.7: "Every request is evaluated against a fixed pipeline of check categories, in the order below, and the first category that fails determines the rejection. The ordering is load-bearing: an authentication failure masks everything downstream; a stale-version rejection surfaces before any state-machine precondition is examined; a segregation-of-duties violation is reported only after every other check has passed."
        PRD §2.7: "9. **Cross-entity referential integrity.** The team's certification is `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`), an `ACTIVE` agreement covers the facility and the scheduled date (`ERR_NO_ACTIVE_AGREEMENT`), orientation is `COMPLETED` and unexpired (`ERR_ORIENTATION_NOT_COMPLETED`), and a `SIGNED` waiver matches the facility's `required_waiver_version` (`ERR_WAIVER_NOT_ON_FILE`) — all HTTP 409. Applies to visit scheduling, offer acceptance, visit check-in (certification only), and facility reinstatement (agreement only)."
        PRD §3.4: "A `ComplianceOfficer` may void a `SIGNED` waiver (otherwise `ERR_WAIVER_NOT_SIGNED`) with a `reason`, moving it to `VOIDED`; voiding is purely prospective — existing `SCHEDULED` visits are unaffected."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_visit_create
        """
        ctx, _first = self._setup_voided_waiver()
        # 10:30-11:30 also strictly overlaps the existing 10:00-11:00 visit
        # (temporal, category 10); the referential waiver failure (category 9)
        # must surface first.
        resp = api_client.create_visit(
            create_visit_payload(
                ctx["team"]["id"], ctx["facility"]["id"],
                "2026-08-03T10:30:00Z", "2026-08-03T11:30:00Z",
                get_team_version(ctx["team"]["id"]),
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ON_FILE)

    def test_voided_waiver_alone_blocks_non_overlapping_visit(self):
        """PRD §3.7: "Referential: the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); an `ACTIVE` agreement must cover the facility on the scheduled date (`ERR_NO_ACTIVE_AGREEMENT`); orientation for the team at this facility must be `COMPLETED` and unexpired (`ERR_ORIENTATION_NOT_COMPLETED`); and a `SIGNED` waiver matching the facility's `required_waiver_version` must be on file (`ERR_WAIVER_NOT_ON_FILE`)."
        PRD §3.4: "A waiver authorizes visits only while `SIGNED` and only while its `waiver_version` equals the facility's current `required_waiver_version`; visit creation without a matching waiver fails with `ERR_WAIVER_NOT_ON_FILE`."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_visit_create
        """
        ctx, _first = self._setup_voided_waiver()
        # Non-overlapping slot: only the referential waiver gate can fail.
        resp = api_client.create_visit(
            create_visit_payload(
                ctx["team"]["id"], ctx["facility"]["id"],
                "2026-08-03T11:30:00Z", "2026-08-03T12:00:00Z",
                get_team_version(ctx["team"]["id"]),
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ON_FILE)


class TestCheckinPipelineOrder:
    def _setup_held_and_optionally_cancelled(self, cancel: bool):
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H S", "team_name": "TS"},
            facility_kwargs={"name": "School K"},
        )
        visit = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                                  "2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")
        validate_success(
            api_client.place_welfare_hold(
                ctx["animal"]["id"],
                {"hold_until": "2026-08-20T00:00:00Z", "reason": "observed stress"},
                COMPLIANCE,
            )
        )
        if cancel:
            validate_success(
                api_client.cancel_visit(visit["id"], {"reason": "schedule change"}, ADMIN)
            )
        return ctx, visit

    def test_state_beats_safety_on_checkin(self):
        """PRD §2.7: "Every request is evaluated against a fixed pipeline of check categories, in the order below, and the first category that fails determines the rejection. The ordering is load-bearing: an authentication failure masks everything downstream; a stale-version rejection surfaces before any state-machine precondition is examined; a segregation-of-duties violation is reported only after every other check has passed."
        PRD §3.7: "Check-in belongs to the handler who owns the visit's team (otherwise `ERR_OWNERSHIP_MISMATCH`) and requires the visit still `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`). Three gates guard the moment: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); and the clock must sit within the check-in window — no earlier than fifteen minutes before `scheduled_start` (earlier fails `ERR_CHECKIN_TOO_EARLY`) and no later than `scheduled_end` (later fails `ERR_CHECKIN_WINDOW_PASSED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_checkin
        """
        ctx, visit = self._setup_held_and_optionally_cancelled(cancel=True)
        set_clock("2026-08-03T10:00:00Z")
        resp = api_client.check_in_visit(visit["id"], make_handler_headers(ctx["handler"]["id"]))
        # State (category 7, visit CANCELLED) masks the welfare-hold safety
        # failure (category 8).
        validate_error(resp, ApiErrorId.ERR_VISIT_NOT_SCHEDULED)

    def test_welfare_hold_blocks_checkin_when_state_is_fine(self):
        """PRD §3.7: "Check-in belongs to the handler who owns the visit's team (otherwise `ERR_OWNERSHIP_MISMATCH`) and requires the visit still `SCHEDULED` (otherwise `ERR_VISIT_NOT_SCHEDULED`). Three gates guard the moment: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the team's certification must stand `ACTIVE` or `RENEWAL_DUE` (`ERR_CERT_NOT_ACTIVE`); and the clock must sit within the check-in window — no earlier than fifteen minutes before `scheduled_start` (earlier fails `ERR_CHECKIN_TOO_EARLY`) and no later than `scheduled_end` (later fails `ERR_CHECKIN_WINDOW_PASSED`)."
        PRD §3.9: "Welfare holds pull an animal off the schedule without touching its credentials. A `ComplianceOfficer` places an `ACTIVE` animal on hold (otherwise `ERR_ANIMAL_NOT_ACTIVE`) by supplying the `hold_until` instant and a `reason`; the animal moves to `WELFARE_HOLD` with `welfare_hold_until` set from the payload and `welfare_hold_reason` recorded as `MANUAL`."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_checkin
        """
        ctx, visit = self._setup_held_and_optionally_cancelled(cancel=False)
        set_clock("2026-08-03T10:00:00Z")
        resp = api_client.check_in_visit(visit["id"], make_handler_headers(ctx["handler"]["id"]))
        # Visit is SCHEDULED (state passes); the safety hold gate fires.
        validate_error(resp, ApiErrorId.ERR_ANIMAL_WELFARE_HOLD)


class TestRestBlock:
    def test_rest_tier_boundaries_and_block_equality(self):
        """PRD §3.7: "Animal welfare bookkeeping lands at the same moment: the visit's rest requirement is sixty minutes when the visit ran thirty minutes or less, one hundred twenty minutes when it ran thirty-one to sixty, and two hundred forty minutes when it ran sixty-one or more, and the animal's `welfare_blocked_until` is set to `actual_end` plus that rest requirement; both workload figures are recomputed."
        PRD §3.7: "Safety: the animal must not stand in `WELFARE_HOLD` (`ERR_ANIMAL_WELFARE_HOLD`); the animal's rest block must be satisfied — `scheduled_start` at or after `welfare_blocked_until`, with an earlier start failing `ERR_ANIMAL_REST_PERIOD`; the forward workload gate must hold — the animal's existing forward-looking workload plus the new visit's scheduled minutes may not exceed two hundred forty minutes, with a total of exactly two hundred forty allowed and anything beyond rejected `ERR_WORKLOAD_LIMIT_EXCEEDED`; the daily limit must hold — an animal already standing on two visits in `SCHEDULED`, `IN_PROGRESS`, or `COMPLETED` on that UTC calendar day rejects a third with `ERR_DAILY_VISIT_LIMIT_EXCEEDED`; the animal's `species` must appear in the facility's `allowed_species` (`ERR_SPECIES_NOT_PERMITTED`); and a valid rabies vaccination must cover the scheduled date (`ERR_VACCINATION_MISSING` / `ERR_VACCINATION_EXPIRED`)."

        Design: Corner/calculations/rest_tier_boundaries_and_block_equality
        """
        ctx = setup_certified_team_at_facility(
            team_kwargs={"handler_name": "H RB", "team_name": "TRB"},
            facility_kwargs={"name": "School X", "visits_per_week_cap": 6},
        )
        v1 = schedule_visit_ok(ctx["team"]["id"], ctx["facility"]["id"],
                               "2026-08-03T10:00:00Z", "2026-08-03T10:30:00Z")
        check_in_visit_ok(v1["id"], ctx["handler"]["id"], "2026-08-03T10:00:00Z")
        # Check out exactly 30 minutes in -> tier 1 rest (60 minutes).
        completed = check_out_visit_ok(v1["id"], ctx["handler"]["id"], "2026-08-03T10:30:00Z")
        assert completed["actual_minutes"] == 30
        animal = get_animal(ctx["animal"]["id"])
        assert_instants_equal(animal["welfare_blocked_until"], "2026-08-03T11:30:00Z")

        # One minute before the block expires -> rejected.
        early = api_client.create_visit(
            create_visit_payload(
                ctx["team"]["id"], ctx["facility"]["id"],
                "2026-08-03T11:29:00Z", "2026-08-03T11:59:00Z",
                get_team_version(ctx["team"]["id"]),
            ),
            ADMIN,
        )
        validate_error(early, ApiErrorId.ERR_ANIMAL_REST_PERIOD)
        # Exactly at welfare_blocked_until -> equality satisfies the rest gate.
        ok = api_client.create_visit(
            create_visit_payload(
                ctx["team"]["id"], ctx["facility"]["id"],
                "2026-08-03T11:30:00Z", "2026-08-03T12:00:00Z",
                get_team_version(ctx["team"]["id"]),
            ),
            ADMIN,
        )
        assert validate_success(ok, 201)["lifecycle_status"] == "SCHEDULED"
