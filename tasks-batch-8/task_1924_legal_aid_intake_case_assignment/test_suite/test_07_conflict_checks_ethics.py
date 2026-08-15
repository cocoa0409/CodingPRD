"""Conflict clearance: SoD recusal, waiver path, expiry through the sweep,
and the open-case gate after expiry."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_client,
    create_application,
    create_eligible_application,
    create_openable_application,
    conflict_check,
    set_clock,
    run_sweep,
    make_supervising_attorney_headers,
    make_ethics_officer_headers,
    make_intake_specialist_headers,
)


class TestEthicsRecusal:
    def test_ethics_recusal_sod_rejected(self, api):
        """PRD §3.3: "Ethics segregation of duties binds here: the resolving
        officer's `X-User-ID` must differ from the check's
        `checked_by_staff_id`, and a self-resolution attempt is rejected with
        `ERR_ETHICS_RECUSAL` (HTTP 403)."

        Design: Corner/validations/ethics_recusal_sod_rejected
        """
        create_venue_rule()
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli SoD")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Former Client")
        cc = conflict_check(app["id"], intake["id"], result="POTENTIAL_CONFLICT",
                            notes="prior representation")
        # same X-User-ID under the EthicsOfficer role is the SoD violation
        resp = api.resolve_conflict_check(
            cc["id"], {"resolution": "WAIVED", "waiver_reason": "waived"},
            make_ethics_officer_headers(intake["id"]))
        validate_error(resp, ApiErrorId.ERR_ETHICS_RECUSAL)
        after = validate_success(api.get_conflict_check(
            cc["id"], make_ethics_officer_headers(intake["id"])))
        assert after["result"] == "POTENTIAL_CONFLICT"

    def test_ethics_recusal_rejected_on_confirmed_conflict_path(self, api):
        """PRD §3.3: "Ethics segregation of duties binds here: the resolving
        officer's `X-User-ID` must differ from the check's
        `checked_by_staff_id`, and a self-resolution attempt is rejected with
        `ERR_ETHICS_RECUSAL` (HTTP 403)."

        Design: Corner/validations/ethics_recusal_sod_rejected
        """
        create_venue_rule()
        intake = create_intake_specialist()
        client = create_client(intake["id"], full_name="Cli SoD2")
        app = create_application(intake["id"], client["id"], case_type="EVICTION_DEFENSE",
                                 opposing_party_name="Former Client")
        cc = conflict_check(app["id"], intake["id"], result="POTENTIAL_CONFLICT")
        resp = api.resolve_conflict_check(
            cc["id"], {"resolution": "CONFIRMED_CONFLICT"},
            make_ethics_officer_headers(intake["id"]))
        validate_error(resp, ApiErrorId.ERR_ETHICS_RECUSAL)


class TestWaiverUnlock:
    def test_conflict_waiver_unlocks_open_case(self, api):
        """PRD §3.5: "Conflict resolution: the application's latest conflict
        check — the one with the greatest `created_at` — must exist and hold
        a `result` of `CLEAR` or `WAIVED`. A missing check, a
        `POTENTIAL_CONFLICT`, or a `CONFIRMED_CONFLICT` is rejected with
        `ERR_CONFLICT_UNRESOLVED` (HTTP 409)."
        PRD §3.3: "Choosing `WAIVED` additionally requires a non-empty
        `waiver_reason`; its absence is rejected with `ERR_INVALID_REQUEST`.
        Either resolution stamps `resolved_by_staff_id` and `resolved_at` from
        the acting officer and the clock."

        Design: Corner/state_machines/conflict_waiver_unlocks_open_case
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        ethics = create_attorney(full_name="Ethics Eve", max_units=10)
        client = create_client(intake["id"], full_name="Cli Waiv")
        app = create_eligible_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE",
                                          opposing_party_name="Former Client LLC")
        cc = conflict_check(app["id"], intake["id"], result="POTENTIAL_CONFLICT",
                            notes="adverse party is former client")
        resolved = validate_success(api.resolve_conflict_check(
            cc["id"], {"resolution": "WAIVED",
                       "waiver_reason": "no substantial relationship"},
            make_ethics_officer_headers(ethics["id"])))
        assert resolved["result"] == "WAIVED"
        assert resolved["resolved_by_staff_id"] == ethics["id"]

        case = validate_success(api.open_case(
            app["id"], {"service_level": "ADVICE_ONLY"},
            make_supervising_attorney_headers(sup["id"])), expected_status=201)
        assert case["application_id"] == app["id"]


class TestSweepExpiry:
    def test_conflict_check_expires_via_sweep_then_unresolved(self, api):
        """PRD §3.3: "During the daily sweep, every check in `CLEAR` or
        `WAIVED` whose `valid_until` lies strictly before the current logical
        clock transitions to `EXPIRED`, which is also terminal."
        PRD §3.5: "Conflict resolution: the application's latest conflict
        check — the one with the greatest `created_at` — must exist and hold
        a `result` of `CLEAR` or `WAIVED`. A missing check, a
        `POTENTIAL_CONFLICT`, or a `CONFIRMED_CONFLICT` is rejected with
        `ERR_CONFLICT_UNRESOLVED` (HTTP 409)."

        Design: Corner/state_machines/conflict_check_expires_via_sweep_then_unresolved
        """
        create_venue_rule()
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Exp")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE",
                                          opposing_party_name="Landlord")
        # CLEAR check born at default clock 2026-08-01 -> valid_until 2026-09-15
        checks, _meta = validate_paginated(
            api.list_conflict_checks(app["id"], make_intake_specialist_headers(intake["id"])))
        cc_id = checks[0]["id"]

        set_clock("2026-09-16T00:00:00Z")
        sweep = run_sweep()
        assert sweep["expired_conflict_checks"] == 1
        after = validate_success(api.get_conflict_check(
            cc_id, make_ethics_officer_headers(sup["id"])))
        assert after["result"] == "EXPIRED"
        # latest check is EXPIRED -> not in {CLEAR, WAIVED} -> resolution gate fails
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_CONFLICT_UNRESOLVED)
