"""Pro bono referrals: offer gates, half-open service-window overlap,
respond/withdraw transitions, expiry via sweep, and panel-member gates."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_client,
    create_openable_application,
    open_case_from_application,
    create_panel_member_payload,
    create_referral_accept_payload,
    set_clock,
    run_sweep,
    make_supervising_attorney_headers,
    make_program_director_headers,
)


def _create_panel(api, **overrides):
    resp = api.create_panel_member(create_panel_member_payload(**overrides),
                                   make_program_director_headers())
    return validate_success(resp, expected_status=201)


def _setup_case_with_offer(api, panel_overrides=None, case_type="CONSUMER_DEBT"):
    """ADVICE_ONLY PENDING_ASSIGNMENT case + panel member + OFFERED referral.
    Returns (case, referral, member, intake, sup)."""
    create_venue_rule(county="CountyA", case_type=case_type, venue="MUNICIPAL_COURT",
                      priority_base_weight=30, extended_eligible=False)
    intake = create_intake_specialist(practice_areas=[case_type])
    sup = create_supervisor(practice_areas=[case_type])
    member = _create_panel(api, **(panel_overrides or {"practice_areas": [case_type]}))
    client = create_client(intake["id"], full_name="Cli Ref")
    app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                      opposing_party_name="Collector")
    case = open_case_from_application(app["id"], sup["id"], service_level="ADVICE_ONLY")
    ref = validate_success(api.create_referral(
        case["id"], {"panel_member_id": member["id"]},
        make_supervising_attorney_headers(sup["id"])), expected_status=201)
    return case, ref, member, intake, sup


class TestOfferGates:
    def test_panel_rejections_bundle(self, api):
        """PRD §3.7: "The panel member must be `ACTIVE` at offer time, else
        `ERR_PANEL_MEMBER_NOT_ACTIVE` (HTTP 409); their `practice_areas` and
        `counties` must cover the case's `case_type` and `incident_county`,
        else `ERR_PANEL_COVERAGE_MISMATCH` (HTTP 422); and their
        `active_referral_count` must be strictly below
        `max_active_referrals`, else `ERR_PANEL_CAPACITY_REACHED` (HTTP 409)."
        PRD §3.7: "A panel member cannot be retired to `INACTIVE` while their
        `active_referral_count` is above zero — the attempt fails with
        `ERR_PANEL_HAS_ACTIVE_PLACEMENTS` (HTTP 409) — and the referral
        register filters by `case_id`, `panel_member_id`, or `status`."

        Design: Corner/validations/panel_rejections_bundle
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        headers_sup = make_supervising_attorney_headers(sup["id"])
        nocover = _create_panel(api, full_name="No Cover",
                                practice_areas=["CONSUMER_DEBT"], counties=["CountyB"])
        busy = _create_panel(api, full_name="Busy", practice_areas=["CONSUMER_DEBT"],
                             counties=["CountyA"], max_active_referrals=1)
        sleeper = _create_panel(api, full_name="Sleeper", practice_areas=["CONSUMER_DEBT"],
                                counties=["CountyA"], max_active_referrals=3)
        validate_success(api.update_panel_member(sleeper["id"], {"status": "SUSPENDED"},
                                                 make_program_director_headers()))

        def make_case(name, opposing):
            client = create_client(intake["id"], full_name=name)
            app = create_openable_application(intake["id"], client["id"],
                                              case_type="CONSUMER_DEBT",
                                              opposing_party_name=opposing)
            return open_case_from_application(app["id"], sup["id"],
                                              service_level="ADVICE_ONLY")

        case1 = make_case("Cli P1", "C1")
        case2 = make_case("Cli P2", "C2")
        # give Busy its one ACCEPTED placement from case2
        ref_busy = validate_success(api.create_referral(
            case2["id"], {"panel_member_id": busy["id"]}, headers_sup), expected_status=201)
        validate_success(api.respond_referral(ref_busy["id"], create_referral_accept_payload(),
                                              headers_sup))

        r1 = api.create_referral(case1["id"], {"panel_member_id": nocover["id"]}, headers_sup)
        validate_error(r1, ApiErrorId.ERR_PANEL_COVERAGE_MISMATCH)
        r2 = api.create_referral(case1["id"], {"panel_member_id": sleeper["id"]}, headers_sup)
        validate_error(r2, ApiErrorId.ERR_PANEL_MEMBER_NOT_ACTIVE)
        r3 = api.create_referral(case1["id"], {"panel_member_id": busy["id"]}, headers_sup)
        validate_error(r3, ApiErrorId.ERR_PANEL_CAPACITY_REACHED)
        r4 = api.update_panel_member(busy["id"], {"status": "INACTIVE"},
                                     make_program_director_headers())
        validate_error(r4, ApiErrorId.ERR_PANEL_HAS_ACTIVE_PLACEMENTS)

    def test_referral_on_pro_bono_case_rejected(self, api):
        """PRD §3.7: "The target case must be `INTERNAL` in `placement` and in
        `PENDING_ASSIGNMENT` or `OPEN` status, else `ERR_CASE_PLACEMENT_CONFLICT`
        (HTTP 409)."

        Design: Corner/validations/referral_on_pro_bono_case_rejected
        """
        case, ref, member, intake, sup = _setup_case_with_offer(api)
        headers_sup = make_supervising_attorney_headers(sup["id"])
        validate_success(api.respond_referral(ref["id"], create_referral_accept_payload(),
                                              headers_sup))
        resp = api.create_referral(case["id"], {"panel_member_id": member["id"]}, headers_sup)
        validate_error(resp, ApiErrorId.ERR_CASE_PLACEMENT_CONFLICT)


class TestRespondAndWindows:
    def test_referral_accept_requires_active_panel_member(self, api):
        """PRD §3.7: "it re-verifies that the panel member is still `ACTIVE`
        and still under capacity, with the same `ERR_PANEL_MEMBER_NOT_ACTIVE`
        and `ERR_PANEL_CAPACITY_REACHED` rejections;"

        Design: Difficulty/cross_entity_state_dependency/referral_accept_requires_active_panel_member
        """
        case, ref, member, intake, sup = _setup_case_with_offer(
            api, {"full_name": "Panel Pat", "practice_areas": ["EVICTION_DEFENSE"],
                  "counties": ["CountyA"], "max_active_referrals": 2},
            case_type="EVICTION_DEFENSE")
        validate_success(api.update_panel_member(member["id"], {"status": "SUSPENDED"},
                                                 make_program_director_headers()))
        resp = api.respond_referral(ref["id"], create_referral_accept_payload(),
                                    make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_PANEL_MEMBER_NOT_ACTIVE)
        after = validate_success(api.get_referral(
            ref["id"], make_supervising_attorney_headers(sup["id"])))
        assert after["status"] == "OFFERED"
        m = validate_success(api.get_panel_member(member["id"],
                                                  make_program_director_headers()))
        assert m["active_referral_count"] == 0

    def test_referral_accept_flips_case_to_pro_bono(self, api):
        """PRD §3.7: "Acceptance stamps `responded_at`, flips the case's
        `placement` to `PRO_BONO`, and — when the case was still
        `PENDING_ASSIGNMENT` — moves it to `OPEN` with `opened_at` stamped,
        since a pro bono placement satisfies assignment without consuming any
        attorney load; the case's `assigned_attorney_id` remains null while it
        is pro bono–placed; if that case is `ADVICE_ONLY` and has no
        `advice_deadline` yet, the deadline is set to 30 days after
        `opened_at`. The panel member's `active_referral_count` rises by one."

        Design: Difficulty/cross_entity_state_dependency/referral_accept_requires_active_panel_member
        """
        case, ref, member, intake, sup = _setup_case_with_offer(api)
        headers_sup = make_supervising_attorney_headers(sup["id"])
        accepted = validate_success(api.respond_referral(
            ref["id"], create_referral_accept_payload(), headers_sup))
        assert accepted["status"] == "ACCEPTED"
        c = validate_success(api.get_case(case["id"], headers_sup))
        assert c["placement"] == "PRO_BONO"
        assert c["status"] == "OPEN"
        assert c["assigned_attorney_id"] is None
        m = validate_success(api.get_panel_member(member["id"],
                                                  make_program_director_headers()))
        assert m["active_referral_count"] == 1

    def test_referral_service_window_halfopen_adjacency(self, api):
        """PRD §3.7: "it enforces window exclusivity — no other `ACCEPTED`
        referral for the same panel member may have a half-open service window
        from `service_start_date` up to but not including `service_end_date`
        that overlaps the requested window, where two windows that merely
        touch, one's end equal to the other's start, do not overlap. A
        violating acceptance is rejected with `ERR_PANEL_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/referral_service_window_halfopen_adjacency
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="FAMILY_DV", venue="FAMILY_COURT",
                          priority_base_weight=60, extended_eligible=True)
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        intake = create_intake_specialist()
        sup = create_supervisor()
        headers_sup = make_supervising_attorney_headers(sup["id"])
        member = _create_panel(api, full_name="Panel Pat",
                               practice_areas=["EVICTION_DEFENSE", "FAMILY_DV",
                                               "BENEFITS_APPEAL"],
                               counties=["CountyA"], max_active_referrals=5)

        def make_offered(name, case_type, opposing):
            client = create_client(intake["id"], full_name=name)
            app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                              opposing_party_name=opposing)
            case = open_case_from_application(app["id"], sup["id"],
                                              service_level="ADVICE_ONLY")
            return validate_success(api.create_referral(
                case["id"], {"panel_member_id": member["id"]}, headers_sup),
                expected_status=201)

        ref1 = make_offered("Cli A", "EVICTION_DEFENSE", "LA")
        validate_success(api.respond_referral(
            ref1["id"], create_referral_accept_payload(service_start_date="2026-09-01",
                                                       service_end_date="2026-10-01"),
            headers_sup))
        ref2 = make_offered("Cli B", "FAMILY_DV", "XB")
        ref3 = make_offered("Cli C", "BENEFITS_APPEAL", "Agency")

        # adjacency: start == R1's end is NOT overlap under half-open semantics
        r2 = api.respond_referral(ref2["id"], create_referral_accept_payload(
            service_start_date="2026-10-01", service_end_date="2026-11-01"), headers_sup)
        assert validate_success(r2)["status"] == "ACCEPTED"
        # strict intersection with R1 [2026-09-01, 2026-10-01)
        r3 = api.respond_referral(ref3["id"], create_referral_accept_payload(
            service_start_date="2026-09-15", service_end_date="2026-10-15"), headers_sup)
        validate_error(r3, ApiErrorId.ERR_PANEL_WINDOW_OVERLAP)
        m = validate_success(api.get_panel_member(member["id"],
                                                  make_program_director_headers()))
        assert m["active_referral_count"] == 2

    def test_referral_service_window_contained_window_rejected(self, api):
        """PRD §3.7: "it enforces window exclusivity — no other `ACCEPTED`
        referral for the same panel member may have a half-open service window
        from `service_start_date` up to but not including `service_end_date`
        that overlaps the requested window, where two windows that merely
        touch, one's end equal to the other's start, do not overlap. A
        violating acceptance is rejected with `ERR_PANEL_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/referral_service_window_halfopen_adjacency
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="EXPUNGEMENT",
                          venue="SUPERIOR_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        headers_sup = make_supervising_attorney_headers(sup["id"])
        member = _create_panel(api, full_name="Panel Win",
                               practice_areas=["CONSUMER_DEBT", "EXPUNGEMENT"],
                               counties=["CountyA"], max_active_referrals=5)

        def make_offered(name, case_type, opposing):
            client = create_client(intake["id"], full_name=name)
            app = create_openable_application(intake["id"], client["id"], case_type=case_type,
                                              opposing_party_name=opposing)
            case = open_case_from_application(app["id"], sup["id"],
                                              service_level="ADVICE_ONLY")
            return validate_success(api.create_referral(
                case["id"], {"panel_member_id": member["id"]}, headers_sup),
                expected_status=201)

        ref1 = make_offered("Cli W1", "CONSUMER_DEBT", "C1")
        validate_success(api.respond_referral(
            ref1["id"], create_referral_accept_payload(service_start_date="2026-09-01",
                                                       service_end_date="2026-10-01"),
            headers_sup))
        # strictly contained window [09-10, 09-20) overlaps [09-01, 10-01)
        ref2 = make_offered("Cli W2", "EXPUNGEMENT", "State")
        r2 = api.respond_referral(ref2["id"], create_referral_accept_payload(
            service_start_date="2026-09-10", service_end_date="2026-09-20"), headers_sup)
        validate_error(r2, ApiErrorId.ERR_PANEL_WINDOW_OVERLAP)
        # window fully before R1's start does not overlap
        ref3 = make_offered("Cli W3", "EXPUNGEMENT", "State 2")
        r3 = api.respond_referral(ref3["id"], create_referral_accept_payload(
            service_start_date="2026-08-01", service_end_date="2026-09-01"), headers_sup)
        assert validate_success(r3)["status"] == "ACCEPTED"

    def test_referral_window_inverted_rejected(self, api):
        """PRD §3.7: "A `decision` of `ACCEPT` requires both
        `service_start_date` and `service_end_date`, with the end strictly
        after the start, else `ERR_INVALID_REQUEST`;"

        Design: Corner/validations/referral_window_inverted_rejected
        """
        case, ref, member, intake, sup = _setup_case_with_offer(api)
        resp = api.respond_referral(
            ref["id"],
            {"decision": "ACCEPT", "service_start_date": "2026-10-01",
             "service_end_date": "2026-09-01"},
            make_supervising_attorney_headers(sup["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        after = validate_success(api.get_referral(
            ref["id"], make_supervising_attorney_headers(sup["id"])))
        assert after["status"] == "OFFERED"

    def test_referral_second_respond_rejected(self, api):
        """PRD §3.7: "`DECLINED`, `EXPIRED`, `WITHDRAWN`, and `COMPLETED` are
        terminal, and referral actions from impermissible states fail with
        `ERR_INVALID_REFERRAL_STATE` (HTTP 409)."

        Design: Corner/state_machines/referral_second_respond_rejected
        """
        case, ref, member, intake, sup = _setup_case_with_offer(
            api, {"full_name": "Panel Pat", "practice_areas": ["CONSUMER_DEBT"],
                  "counties": ["CountyA"], "max_active_referrals": 3})
        pd = make_program_director_headers()
        validate_success(api.respond_referral(
            ref["id"], {"decision": "DECLINE", "decline_reason": "too busy"}, pd))
        resp = api.respond_referral(ref["id"], create_referral_accept_payload(), pd)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERRAL_STATE)
        after = validate_success(api.get_referral(ref["id"], pd))
        assert after["status"] == "DECLINED"
        m = validate_success(api.get_panel_member(member["id"], pd))
        assert m["active_referral_count"] == 0


class TestReferralExpiry:
    def test_referral_offer_expires_via_sweep(self, api):
        """PRD §3.7: "the daily sweep expires any `OFFERED` referral whose
        `response_deadline` lies strictly before the clock, moving it to
        `EXPIRED`;"
        PRD §3.7: "`DECLINED`, `EXPIRED`, `WITHDRAWN`, and `COMPLETED` are
        terminal, and referral actions from impermissible states fail with
        `ERR_INVALID_REFERRAL_STATE` (HTTP 409)."

        Design: Corner/state_machines/referral_offer_expires_via_sweep
        """
        case, ref, member, intake, sup = _setup_case_with_offer(api)
        # offered at default clock 2026-08-01 -> response_deadline 2026-08-11
        set_clock("2026-08-12T00:00:00Z")
        sweep = run_sweep()
        assert sweep["expired_referrals"] == 1
        after = validate_success(api.get_referral(ref["id"], make_program_director_headers()))
        assert after["status"] == "EXPIRED"
        resp = api.respond_referral(ref["id"], create_referral_accept_payload(),
                                    make_program_director_headers())
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERRAL_STATE)
