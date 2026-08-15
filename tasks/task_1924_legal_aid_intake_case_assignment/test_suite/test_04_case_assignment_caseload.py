"""Attorney assignment, caseload accounting (raw vs weighted), capacity
boundaries, OCC on assign, hold/resume posture, and close lockdown."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_paralegal,
    create_client,
    create_openable_application,
    open_case_from_application,
    setup_assigned_case,
    setup_closed_advice_case,
    make_supervising_attorney_headers,
    make_program_director_headers,
)


def _assign(api, case, attorney_id, sup_id, paralegal_id=None, version=None):
    payload = {"attorney_id": attorney_id,
               "expected_case_version": version if version is not None else case["version"]}
    if paralegal_id is not None:
        payload["paralegal_id"] = paralegal_id
    return api.assign_case(case["id"], payload, make_supervising_attorney_headers(sup_id))


class TestRawCountVsWeightedLoad:
    def test_caseload_raw_count_vs_weighted_load(self, api):
        """PRD §2.10: "The member's `open_case_count` counts that same case
        set by heads rather than by weight: one `EXTENDED` case plus three
        `ADVICE_ONLY` cases yields an `open_case_count` of 4 but
        `weighted_open_units` of 11 — identical data, two different numbers,
        each with its own audience. A member's `available_units` is their
        `max_units` minus their `weighted_open_units`."

        Design: Difficulty/dual_variant_calc/caseload_raw_count_vs_weighted_load
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist()
        sup = create_supervisor(max_units=4)
        att = create_attorney(full_name="Att One", max_units=40,
                              practice_areas=["EVICTION_DEFENSE", "BENEFITS_APPEAL",
                                              "CONSUMER_DEBT"])
        headers_sup = make_supervising_attorney_headers(sup["id"])
        client = create_client(intake["id"], full_name="Cli Load")
        plans = [("EVICTION_DEFENSE", "EXTENDED", "Landlord LLC"),
                 ("BENEFITS_APPEAL", "ADVICE_ONLY", "Benefits Agency"),
                 ("CONSUMER_DEBT", "ADVICE_ONLY", "Collector Inc")]
        for case_type, level, opposing in plans:
            app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                              opposing_party_name=opposing)
            case = open_case_from_application(app["id"], sup["id"], service_level=level)
            validate_success(_assign(api, case, att["id"], sup["id"]))

        caseload = validate_success(api.get_caseload(att["id"], headers_sup))
        assert caseload["open_case_count"] == 3
        assert caseload["weighted_open_units"] == 9  # 5 + 2 + 2 for the same case set
        assert caseload["available_units"] == 31  # 40 - 9

    def test_open_case_count_heads_vs_weights_second_reader(self, api):
        """PRD §2.10: "A member's `weighted_open_units` is the sum of
        `case_weight` over exactly those cases assigned to the member as
        attorney whose status is `OPEN` — `PENDING_ASSIGNMENT` and `ON_HOLD`
        cases contribute nothing, and paralegal assignments never add load to
        anyone."

        Design: Difficulty/dual_variant_calc/caseload_raw_count_vs_weighted_load
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att = create_attorney(full_name="Att Solo", practice_areas=["CONSUMER_DEBT"],
                              max_units=40)
        client = create_client(intake["id"], full_name="Cli V2")
        app1 = create_openable_application(intake["id"], client["id"],
                                           case_type="CONSUMER_DEBT",
                                           opposing_party_name="X1")
        case1 = open_case_from_application(app1["id"], sup["id"], service_level="ADVICE_ONLY")
        validate_success(_assign(api, case1, att["id"], sup["id"]))
        # a second case that stays PENDING_ASSIGNMENT contributes nothing
        # (distinct client: PRD forbids a second open case for the same
        # client and case type while the first is OPEN)
        client2 = create_client(intake["id"], full_name="Cli V2b")
        app2 = create_openable_application(intake["id"], client2["id"],
                                           case_type="CONSUMER_DEBT",
                                           opposing_party_name="X2")
        open_case_from_application(app2["id"], sup["id"], service_level="ADVICE_ONLY")

        caseload = validate_success(
            api.get_caseload(att["id"], make_supervising_attorney_headers(sup["id"])))
        assert caseload["open_case_count"] == 1
        assert caseload["weighted_open_units"] == 2


class TestCapacityBoundary:
    def test_caseload_capacity_equality_boundary(self, api):
        """PRD §3.6: "and the attorney's `weighted_open_units` plus the case's
        `case_weight` must not exceed their `max_units`, with an exactly-full
        load permitted, otherwise `ERR_CASELOAD_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/caseload_capacity_equality_boundary
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist()
        sup = create_supervisor(max_units=4)
        att = create_attorney(full_name="Att Edge", max_units=10,
                              practice_areas=["EVICTION_DEFENSE", "FAMILY_DV"])
        headers_sup = make_supervising_attorney_headers(sup["id"])

        def make_case(client_name, case_type, level, opposing, vulns=None):
            overrides = {"full_name": client_name}
            if vulns:
                overrides["vulnerability_factors"] = vulns
            client = create_client(intake["id"], **overrides)
            app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                              opposing_party_name=opposing)
            return open_case_from_application(app["id"], sup["id"], service_level=level)

        # case A loads the attorney to 5 of 10 (available exactly 5)
        case_a = make_case("Cli A", "FAMILY_DV", "EXTENDED", "X", ["DV_SURVIVOR"])
        validate_success(_assign(api, case_a, att["id"], sup["id"]))
        # case B at weight 5 lands exactly at max_units 10 (equality permitted)
        case_b = make_case("Cli B", "EVICTION_DEFENSE", "EXTENDED", "Y")
        ok = _assign(api, case_b, att["id"], sup["id"])
        assert validate_success(ok)["status"] == "OPEN"
        caseload = validate_success(api.get_caseload(att["id"], headers_sup))
        assert caseload["weighted_open_units"] == 10
        assert caseload["available_units"] == 0
        # case C at weight 2 exceeds available 0
        case_c = make_case("Cli C", "EVICTION_DEFENSE", "ADVICE_ONLY", "Z")
        bad = _assign(api, case_c, att["id"], sup["id"])
        validate_error(bad, ApiErrorId.ERR_CASELOAD_CAPACITY_EXCEEDED)

    def test_caseload_capacity_one_unit_over_rejected(self, api):
        """PRD §3.6: "and the attorney's `weighted_open_units` plus the case's
        `case_weight` must not exceed their `max_units`, with an exactly-full
        load permitted, otherwise `ERR_CASELOAD_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/caseload_capacity_equality_boundary
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT", "FAMILY_DV"])
        att = create_attorney(full_name="Att Nine", max_units=9,
                              practice_areas=["CONSUMER_DEBT", "FAMILY_DV"])
        headers_sup = make_supervising_attorney_headers(sup["id"])

        c1 = create_client(intake["id"], full_name="Cli N1", household_size=2,
                           vulnerability_factors=["DV_SURVIVOR"])
        app1 = create_openable_application(intake["id"], c1["id"], case_type="FAMILY_DV",
                                           opposing_party_name="X")
        case1 = open_case_from_application(app1["id"], sup["id"], service_level="EXTENDED")
        validate_success(_assign(api, case1, att["id"], sup["id"]))  # load 5 of 9
        # EXTENDED weight 5: 5 + 5 = 10 > 9 -> rejected
        c2 = create_client(intake["id"], full_name="Cli N2", household_size=2,
                           vulnerability_factors=["DV_SURVIVOR"])
        app2 = create_openable_application(intake["id"], c2["id"], case_type="FAMILY_DV",
                                           opposing_party_name="Y")
        case2 = open_case_from_application(app2["id"], sup["id"], service_level="EXTENDED")
        bad = _assign(api, case2, att["id"], sup["id"])
        validate_error(bad, ApiErrorId.ERR_CASELOAD_CAPACITY_EXCEEDED)
        # ADVICE_ONLY weight 2: 5 + 2 = 7 <= 9 -> permitted
        c3 = create_client(intake["id"], full_name="Cli N3")
        app3 = create_openable_application(intake["id"], c3["id"], case_type="CONSUMER_DEBT",
                                           opposing_party_name="Z")
        case3 = open_case_from_application(app3["id"], sup["id"], service_level="ADVICE_ONLY")
        ok = _assign(api, case3, att["id"], sup["id"])
        assert validate_success(ok)["status"] == "OPEN"
        caseload = validate_success(api.get_caseload(att["id"], headers_sup))
        assert caseload["weighted_open_units"] == 7

    def test_caseload_units_conserved_assign_then_close(self, api):
        """PRD §3.6: "A successful assignment writes `assigned_attorney_id`
        and, when provided, `assigned_paralegal_id`; it raises the attorney's
        `weighted_open_units` by the case's `case_weight` and their
        `open_case_count` by one, while paralegal load never changes."
        PRD §3.8: "Closing from `OPEN` releases the assigned attorney's
        `weighted_open_units` by the case's `case_weight` and decrements their
        `open_case_count`; closing from `ON_HOLD` changes no load, because the
        weight was already released at hold time; closing from
        `PENDING_ASSIGNMENT` changes no load, because none was ever added."

        Design: Difficulty/compensating_invariant/caseload_units_conserved_assign_then_close
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        sup = create_supervisor(practice_areas=["FAMILY_DV"], max_units=4)
        att = create_attorney(full_name="Att One", practice_areas=["FAMILY_DV"], max_units=40)
        headers_sup = make_supervising_attorney_headers(sup["id"])
        client = create_client(intake["id"], full_name="Cli Inv", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        case = open_case_from_application(app["id"], sup["id"], service_level="EXTENDED")

        before = validate_success(api.get_caseload(att["id"], headers_sup))
        assert before["weighted_open_units"] == 0
        validate_success(_assign(api, case, att["id"], sup["id"]))
        mid = validate_success(api.get_caseload(att["id"], headers_sup))
        assert mid["weighted_open_units"] == 5
        assert mid["open_case_count"] == 1
        validate_success(api.close_case(case["id"], {"outcome_code": "SETTLEMENT",
                                                     "closure_reason": "settled"},
                                        headers_sup))
        end = validate_success(api.get_caseload(att["id"], headers_sup))
        assert end["weighted_open_units"] == 0
        assert end["open_case_count"] == 0

    def test_place_hold_releases_load_and_resume_restores(self, api):
        """PRD §3.6: "Placing a hold moves a case from `OPEN` to `ON_HOLD` —
        the request may carry an optional `hold_reason` — and releases the
        assigned attorney's `weighted_open_units` by the case's `case_weight`,
        since only `OPEN` cases count toward load. Resuming moves a case from
        `ON_HOLD` back to `OPEN`, but only after re-checking that the assigned
        attorney, if any, is still `ACTIVE` — else `ERR_STAFF_NOT_ACTIVE` —
        and still has room, with the same equality-permitted ceiling, else
        `ERR_CASELOAD_CAPACITY_EXCEEDED`; a successful resume adds the weight
        back."

        Design: Difficulty/compensating_invariant/caseload_units_conserved_assign_then_close
        """
        case, app, intake, sup, att, client = setup_assigned_case()
        headers_sup = make_supervising_attorney_headers(sup["id"])
        mid = validate_success(api.get_caseload(att["id"], headers_sup))
        assert mid["weighted_open_units"] == 2
        validate_success(api.place_hold(case["id"], {}, headers_sup))
        held = validate_success(api.get_caseload(att["id"], headers_sup))
        assert held["weighted_open_units"] == 0
        validate_success(api.resume_case(case["id"], headers_sup))
        back = validate_success(api.get_caseload(att["id"], headers_sup))
        assert back["weighted_open_units"] == 2


class TestAssignRejections:
    def test_assign_staff_rejections_bundle(self, api):
        """PRD §3.6: "the designated attorney must exist as a resolvable
        reference, hold `staff_type` `ATTORNEY`, and be `ACTIVE`, otherwise
        `ERR_STAFF_NOT_ACTIVE` (HTTP 409); the attorney's `practice_areas`
        must contain the application's `case_type` and their
        `admitted_counties` must contain the `incident_county`, otherwise
        `ERR_STAFF_COVERAGE_MISMATCH` (HTTP 422); a supplied paralegal must be
        a `PARALEGAL`, be `ACTIVE`, and be supervised by the attorney being
        assigned — `supervising_attorney_id` pointing at that attorney —
        otherwise `ERR_PARALEGAL_SUPERVISION_MISMATCH` (HTTP 422);"

        Design: Corner/validations/assign_staff_rejections_bundle
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        wrong = create_attorney(full_name="Att WrongArea", practice_areas=["FAMILY_DV"])
        right = create_attorney(full_name="Att Right", practice_areas=["CONSUMER_DEBT"])
        other = create_attorney(full_name="Att Other", practice_areas=["CONSUMER_DEBT"])
        para = create_paralegal(other["id"], full_name="Para One",
                                practice_areas=["CONSUMER_DEBT"])
        tired = create_attorney(full_name="Att Tired", practice_areas=["CONSUMER_DEBT"])
        validate_success(api.update_staff_member(tired["id"], {"status": "ON_LEAVE"},
                                                 make_program_director_headers()))
        cases = []
        for i in (1, 2, 3):
            client = create_client(intake["id"], full_name=f"Cli B{i}")
            app = create_openable_application(intake["id"], client["id"],
                                              case_type="CONSUMER_DEBT",
                                              opposing_party_name=f"C{i}")
            cases.append(open_case_from_application(app["id"], sup["id"]))

        r1 = _assign(api, cases[0], wrong["id"], sup["id"])
        validate_error(r1, ApiErrorId.ERR_STAFF_COVERAGE_MISMATCH)
        r2 = _assign(api, cases[1], right["id"], sup["id"], paralegal_id=para["id"])
        validate_error(r2, ApiErrorId.ERR_PARALEGAL_SUPERVISION_MISMATCH)
        r3 = _assign(api, cases[2], tired["id"], sup["id"])
        validate_error(r3, ApiErrorId.ERR_STAFF_NOT_ACTIVE)
        for case in cases:
            after = validate_success(api.get_case(
                case["id"], make_supervising_attorney_headers(sup["id"])))
            assert after["status"] == "PENDING_ASSIGNMENT"

    def test_assign_on_closed_case_state_beats_stale_version(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed cascade of
        checks, and the first failing check determines the rejection — later
        checks are not consulted."
        PRD §2.7: "State-machine legality: the target entity must currently be
        in a from-state of the requested transition, else the request fails
        with the entity's invalid-state error — `ERR_INVALID_APPLICATION_STATE`,
        `ERR_INVALID_CASE_STATE`, `ERR_INVALID_REFERRAL_STATE`,
        `ERR_INVALID_GRANT_STATE`, or `ERR_INVALID_REPORT_STATE`."
        PRD §2.7: "Optimistic concurrency per §2.8, producing
        `ERR_STALE_VERSION`."

        Design: Corner/validations/assign_on_closed_case_state_beats_stale_version
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att2 = create_attorney(full_name="Att Two", practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli Ord2")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])
        headers_sup = make_supervising_attorney_headers(sup["id"])
        closed = validate_success(api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN"},
                                                 headers_sup))
        resp = api.assign_case(case["id"],
                               {"attorney_id": att2["id"],
                                "expected_case_version": closed["version"] - 1},
                               headers_sup)
        validate_error(resp, ApiErrorId.ERR_INVALID_CASE_STATE)

    def test_occ_stale_version_on_second_assign(self, api):
        """PRD §2.8: "Assigning (or reassigning) an attorney to a case
        requires the request to carry `expected_case_version`, the client's
        last observed `version` of that case. Because assignment from `OPEN`
        legitimately supersedes a prior assignment, a second sequential
        request carrying the pre-supersede version would otherwise observe a
        valid state and succeed; the version check is what condemns it. If
        `expected_case_version` does not match the case's current `version`,
        the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
        preventing the client from overwriting an assignment it has not
        observed."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_second_assign
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att_a = create_attorney(full_name="Att A", practice_areas=["CONSUMER_DEBT"])
        att_b = create_attorney(full_name="Att B", practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli OCC")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])

        first = validate_success(_assign(api, case, att_a["id"], sup["id"]))
        assert first["version"] == case["version"] + 1
        stale = _assign(api, case, att_b["id"], sup["id"])  # still version observed pre-assign
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_case(
            case["id"], make_supervising_attorney_headers(sup["id"])))
        assert after["assigned_attorney_id"] == att_a["id"]


class TestReassignmentReconciliation:
    def test_derived_load_reconciliation_on_reassignment(self, api):
        """PRD §3.6: "On reassignment, the outgoing attorney — if any, and if
        different — first sheds the case's weight and count before the
        incoming attorney picks them up."
        PRD §3.6: "Every assignment or reassignment increments the case's
        `version` by one."

        Design: Corner/cross_cutting_complexity_layers/derived_load_reconciliation_on_reassignment
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        att_a = create_attorney(full_name="Att A", practice_areas=["FAMILY_DV"])
        att_b = create_attorney(full_name="Att B", practice_areas=["FAMILY_DV"])
        client = create_client(intake["id"], full_name="Cli Re2", household_size=2,
                               vulnerability_factors=["DV_SURVIVOR"])
        app = create_openable_application(intake["id"], client["id"], case_type="FAMILY_DV",
                                          opposing_party_name="Abuser")
        case = open_case_from_application(app["id"], att_a["id"], service_level="EXTENDED")
        v2 = validate_success(_assign(api, case, att_a["id"], att_a["id"]))["version"]
        v3 = validate_success(_assign(api, case, att_b["id"], att_a["id"], version=v2))["version"]
        assert v3 == v2 + 1

        pd_headers = make_program_director_headers()
        a = validate_success(api.get_caseload(att_a["id"], pd_headers))
        b = validate_success(api.get_caseload(att_b["id"], pd_headers))
        assert a["weighted_open_units"] == 0 and a["open_case_count"] == 0
        assert b["weighted_open_units"] == 5 and b["open_case_count"] == 1
        after = validate_success(api.get_case(case["id"], pd_headers))
        assert after["assigned_attorney_id"] == att_b["id"]


class TestCloseLockdown:
    def test_closed_case_terminal_lockdown_rejects_further_transitions(self, api):
        """PRD §3.6: "Case actions attempted from a posture that does not
        permit them fail with `ERR_INVALID_CASE_STATE` (HTTP 409)."
        PRD §3.8: "`CLOSED` is terminal."

        Design: Corner/state_machines/closed_case_terminal_lockdown_rejects_further_transitions
        """
        case, intake, sup = setup_closed_advice_case()
        headers_sup = make_supervising_attorney_headers(sup["id"])
        r1 = api.place_hold(case["id"], {}, headers_sup)
        validate_error(r1, ApiErrorId.ERR_INVALID_CASE_STATE)
        r2 = api.close_case(case["id"], {"outcome_code": "ADMINISTRATIVE"}, headers_sup)
        validate_error(r2, ApiErrorId.ERR_INVALID_CASE_STATE)
