"""Cross-cutting surface: authentication/role gates, error envelope shape,
entity creation defaults, staff supervision rules, venue-rule uniqueness,
listing/filtering, and pagination."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_venue_rule,
    create_intake_specialist,
    create_supervisor,
    create_attorney,
    create_paralegal,
    create_client,
    create_openable_application,
    open_case_from_application,
    create_client_payload,
    create_grant_program,
    make_intake_specialist_headers,
    make_supervising_attorney_headers,
    make_paralegal_headers,
    make_ethics_officer_headers,
    make_grants_manager_headers,
    make_program_director_headers,
)


class TestAuthAndEnvelope:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, declaring the capacity
        in which they act. The system recognizes exactly seven roles:
        `IntakeSpecialist`, `SupervisingAttorney`, `StaffAttorney`,
        `Paralegal`, `EthicsOfficer`, `GrantsManager`, and `ProgramDirector`.
        A request with a missing header, or whose `X-User-Role` is not one of
        these seven declared roles, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/errors/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_client(
            {"full_name": "No Auth", "residence_county": "CountyA", "household_size": 1,
             "annual_gross_income_cents": 100, "annual_countable_income_cents": 100,
             "receives_means_tested_benefits": False},
            headers={"Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_error_envelope_shape_on_404(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/errors/error_envelope_shape_on_404
        """
        resp = api.get_case(NON_EXISTENT_UUID, make_program_director_headers())
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and len(body["data"]["message"]) > 0
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

    def test_get_client_by_unknown_id_returns_not_found(self, api):
        """PRD §2.6: "Requests that target nested resources resolve their path
        identifiers in strict left-to-right order. The request is rejected
        with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not
        resolve to an existing resource — an application identifier is
        validated before a conflict-check identifier beneath it, a case
        identifier before a time entry beneath it, and so on."

        Design: Corner/entities/get_client_by_unknown_id_returns_not_found
        """
        resp = api.get_client(NON_EXISTENT_UUID, make_program_director_headers())
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestEntityCreation:
    def test_client_create_returns_201_with_system_fields(self, api):
        """PRD §3.1: "The registration may also list `vulnerability_factors`
        — zero or more of `ELDERLY`, `DISABLED`, `DV_SURVIVOR`,
        `LIMITED_ENGLISH`, `HOMELESS`, and `VETERAN`; when omitted, the list
        defaults to empty. A new client's `status` is `ACTIVE`."
        PRD §2.5: "`id` (string): a unique, server-minted UUID with no type
        prefix."
        PRD §2.5: "`version` (integer): a system-managed integer that starts
        at 1 and increments by one on every mutation; it anchors optimistic
        concurrency control (§2.8)."

        Design: Corner/entities/client_create_returns_201_with_system_fields
        """
        intake = create_intake_specialist()
        resp = api.create_client(
            {"full_name": "Cli New", "residence_county": "CountyA", "household_size": 2,
             "annual_gross_income_cents": 1_000_000,
             "annual_countable_income_cents": 900_000,
             "receives_means_tested_benefits": False},
            make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["version"] == 1
        assert data["status"] == "ACTIVE"
        assert data["vulnerability_factors"] == []
        assert data["id"] and data["created_at"] and data["updated_at"]

    def test_staff_create_omitting_max_units_applies_default_40(self, api):
        """PRD §3.6: "Capacity is set through `max_units`, an integer of at
        least 1 that defaults to 40 when omitted."
        PRD §3.6: "New members start `ACTIVE` with zeroed load fields."

        Design: Corner/entities/staff_create_omitting_max_units_applies_default_40
        """
        resp = api.create_staff_member(
            {"full_name": "Att Default", "staff_type": "ATTORNEY",
             "admitted_counties": ["CountyA"], "practice_areas": ["EVICTION_DEFENSE"]},
            make_program_director_headers())
        data = validate_success(resp, expected_status=201)
        assert data["max_units"] == 40
        assert data["status"] == "ACTIVE"
        assert data["weighted_open_units"] == 0
        assert data["open_case_count"] == 0

    def test_create_client_with_unknown_field_returns_invalid_request(self, api):
        """PRD §2.7: "Request shape: missing required fields, unknown fields,
        bad enum values, or range violations — a satisfaction `score` outside
        1–5, `hours` outside 0.25–24.00, an end date not after its start date,
        a `household_size` below 1, negative cent amounts — produce
        `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_client_with_unknown_field_returns_invalid_request
        """
        intake = create_intake_specialist()
        payload = create_client_payload(full_name="Cli Bad")
        payload["priority_score"] = 99  # undeclared field
        resp = api.create_client(payload, make_intake_specialist_headers(intake["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_shape_error_precedes_fk_existence(self, api):
        """PRD §2.7: "Every request is evaluated against a fixed cascade of
        checks, and the first failing check determines the rejection — later
        checks are not consulted."
        PRD §2.7: "Request shape: missing required fields, unknown fields,
        bad enum values, or range violations — a satisfaction `score` outside
        1–5, `hours` outside 0.25–24.00, an end date not after its start date,
        a `household_size` below 1, negative cent amounts — produce
        `ERR_INVALID_REQUEST`."
        PRD §2.7: "Body foreign-key existence, producing `ERR_NOT_FOUND` as
        in §2.6."

        Design: Corner/validations/shape_error_precedes_fk_existence
        """
        intake = create_intake_specialist()
        resp = api.create_application(
            {"client_id": NON_EXISTENT_UUID, "case_type": "NOT_A_TYPE",
             "opposing_party_name": "X", "incident_county": "CountyA"},
            make_intake_specialist_headers(intake["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestStaffSupervision:
    def test_staff_supervision_self_reference_filter(self, api):
        """PRD §3.6: "A paralegal must be supervised: when `staff_type` is
        `PARALEGAL`, `supervising_attorney_id` is required and must reference
        a member whose `staff_type` is `ATTORNEY`, and the supervision chain
        must remain acyclic; a missing supervisor, a non-attorney supervisor,
        or a cycle is rejected with `ERR_INVALID_SUPERVISOR` (HTTP 422), both
        at onboarding and on any later staff update."
        PRD §3.6: "The staff register supports filtering by
        `supervising_attorney_id`, `staff_type`, `status`, a single
        `practice_area`, or a single `county`."

        Design: Corner/entities/staff_supervision_self_reference_filter
        """
        att = create_attorney(full_name="Att Sup", practice_areas=["FAMILY_DV"])
        para = create_paralegal(att["id"], full_name="Para One",
                                practice_areas=["FAMILY_DV"])
        assert para["supervising_attorney_id"] == att["id"]
        members, meta = validate_paginated(api.list_staff_members(
            make_program_director_headers(),
            params={"supervising_attorney_id": att["id"]}))
        assert meta["total_count"] == 1
        assert members[0]["id"] == para["id"]

    def test_invalid_supervisor_rejected(self, api):
        """PRD §3.6: "A paralegal must be supervised: when `staff_type` is
        `PARALEGAL`, `supervising_attorney_id` is required and must reference
        a member whose `staff_type` is `ATTORNEY`, and the supervision chain
        must remain acyclic; a missing supervisor, a non-attorney supervisor,
        or a cycle is rejected with `ERR_INVALID_SUPERVISOR` (HTTP 422), both
        at onboarding and on any later staff update."

        Design: Corner/validations/invalid_supervisor_rejected
        """
        att = create_attorney(full_name="Att Real", practice_areas=["FAMILY_DV"])
        para = create_paralegal(att["id"], full_name="Para Base",
                                practice_areas=["FAMILY_DV"])
        pd = make_program_director_headers()
        r1 = api.create_staff_member(
            {"full_name": "Para Bad", "staff_type": "PARALEGAL",
             "admitted_counties": ["CountyA"], "practice_areas": ["FAMILY_DV"],
             "supervising_attorney_id": para["id"]}, pd)
        validate_error(r1, ApiErrorId.ERR_INVALID_SUPERVISOR)
        r2 = api.create_staff_member(
            {"full_name": "Para None", "staff_type": "PARALEGAL",
             "admitted_counties": ["CountyA"], "practice_areas": ["FAMILY_DV"]}, pd)
        validate_error(r2, ApiErrorId.ERR_INVALID_SUPERVISOR)

    def test_staff_separation_with_open_cases_rejected(self, api):
        """PRD §3.6: "Staff status itself is guarded: a member cannot be moved
        to `SEPARATED` while any case in `OPEN` or `ON_HOLD` remains assigned
        to them, an attempt failing with `ERR_STAFF_HAS_OPEN_CASES`
        (HTTP 409)."

        Design: Corner/validations/staff_separation_with_open_cases_rejected
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli Sep")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])
        headers_sup = make_supervising_attorney_headers(sup["id"])
        validate_success(api.assign_case(
            case["id"], {"attorney_id": sup["id"],
                         "expected_case_version": case["version"]}, headers_sup))
        pd = make_program_director_headers()
        bad = api.update_staff_member(sup["id"], {"status": "SEPARATED"}, pd)
        validate_error(bad, ApiErrorId.ERR_STAFF_HAS_OPEN_CASES)
        validate_success(api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN"},
                                        headers_sup))
        good = api.update_staff_member(sup["id"], {"status": "SEPARATED"}, pd)
        assert validate_success(good)["status"] == "SEPARATED"


class TestVenueRules:
    def test_venue_rule_duplicate_rejected(self, api):
        """PRD §3.9: "The pair of `county` and `case_type` is unique across
        rules; a duplicate creation is rejected with `ERR_VENUE_RULE_CONFLICT`
        (HTTP 409)."

        Design: Corner/validations/venue_rule_duplicate_rejected
        """
        create_venue_rule()
        pd = make_program_director_headers()
        bad = api.create_venue_rule(
            {"county": "CountyA", "case_type": "EVICTION_DEFENSE",
             "venue": "SUPERIOR_COURT", "priority_base_weight": 70,
             "extended_eligible": False}, pd)
        validate_error(bad, ApiErrorId.ERR_VENUE_RULE_CONFLICT)
        ok = api.create_venue_rule(
            {"county": "CountyA", "case_type": "FAMILY_DV", "venue": "FAMILY_COURT",
             "priority_base_weight": 60, "extended_eligible": True}, pd)
        validate_success(ok, expected_status=201)

    def test_venue_copied_from_rule_to_case(self, api):
        """PRD §3.2: "The application's `venue` is copied from the matching
        rule, one of `SUPERIOR_COURT`, `HOUSING_COURT`, `FAMILY_COURT`,
        `MUNICIPAL_COURT`, `ADMIN_TRIBUNAL`, or `FEDERAL_TRIBUNAL`."
        PRD §3.5: "Its `application_id` ties it to the originating
        application, `venue` is copied from the application, `placement`
        starts as `INTERNAL`, `status` starts as `PENDING_ASSIGNMENT`, and
        both `assigned_attorney_id` and `assigned_paralegal_id` start null."

        Design: Corner/calculations/venue_copied_from_rule_to_case
        """
        create_venue_rule()  # HOUSING_COURT for (CountyA, EVICTION_DEFENSE)
        intake = create_intake_specialist()
        sup = create_supervisor()
        client = create_client(intake["id"], full_name="Cli Venue")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="EVICTION_DEFENSE",
                                          opposing_party_name="Landlord")
        screened = validate_success(api.get_application(
            app["id"], make_intake_specialist_headers(intake["id"])))
        # create_openable_application walked through screen; venue came from the rule
        case = open_case_from_application(app["id"], sup["id"], service_level="ADVICE_ONLY")
        assert case["venue"] == "HOUSING_COURT"
        assert screened["venue"] == "HOUSING_COURT"


class TestRoleDenials:
    def test_intake_specialist_cannot_open_case(self, api):
        """PRD §2.1: "A request whose role is declared but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.5: "Only a `SupervisingAttorney` may open a case, and only
        from an application in `ELIGIBLE`."

        Design: Corner/rbac/intake_specialist_cannot_open_case
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli RB")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        resp = api.open_case(app["id"], {"service_level": "ADVICE_ONLY"},
                             make_intake_specialist_headers(intake["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_grants_manager_cannot_create_grant_program(self, api):
        """PRD §2.1: "A request whose role is declared but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "A `GrantsManager` generates, submits, and revises grant
        reports but administers no grant programs; their read access covers
        the general list and detail views except the conflict-check and
        waitlist views, whose tables list only the roles explicitly permitted
        there."

        Design: Corner/rbac/grants_manager_cannot_create_grant_program
        """
        resp = api.create_grant_program(
            {"name": "Sneaky", "funder": "LSC", "period_start": "2026-01-01",
             "period_end": "2026-12-31", "allowed_case_types": ["CONSUMER_DEBT"],
             "allowed_counties": ["CountyA"], "income_cap_percentage": 150.00,
             "per_case_rate_cents": 33_333, "total_budget_cents": 100_000},
            make_grants_manager_headers())
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_ethics_officer_cannot_run_conflict_check(self, api):
        """PRD §2.1: "A request whose role is declared but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.3: "An `IntakeSpecialist` runs a conflict check against an
        application — naming its `result` as `CLEAR` or `POTENTIAL_CONFLICT`
        and optionally attaching `notes` — and the system stamps the check
        with `checked_by_staff_id` from the acting specialist's `X-User-ID`
        and `checked_at` from the logical clock."

        Design: Corner/rbac/ethics_officer_cannot_run_conflict_check
        """
        intake = create_intake_specialist()
        ethics = create_attorney(full_name="Ethics Eve", max_units=10)
        client = create_client(intake["id"], full_name="Cli EO")
        app = validate_success(api.create_application(
            {"client_id": client["id"], "case_type": "EVICTION_DEFENSE",
             "opposing_party_name": "Landlord", "incident_county": "CountyA"},
            make_intake_specialist_headers(intake["id"])), expected_status=201)
        resp = api.create_conflict_check(app["id"], {"result": "CLEAR"},
                                         make_ethics_officer_headers(ethics["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_paralegal_cannot_close_case(self, api):
        """PRD §2.1: "A request whose role is declared but not listed among
        the roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §3.8: "A `StaffAttorney` may close only their own case — the
        case's `assigned_attorney_id` must equal their `X-User-ID`, else
        `ERR_CASE_NOT_ASSIGNED_TO_YOU` (HTTP 403) — while a
        `SupervisingAttorney` may close any case."

        Design: Corner/rbac/paralegal_cannot_close_case
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att = create_attorney(full_name="Att A", practice_areas=["CONSUMER_DEBT"])
        para = create_paralegal(att["id"], full_name="Para One",
                                practice_areas=["CONSUMER_DEBT"])
        client = create_client(intake["id"], full_name="Cli PC")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])
        validate_success(api.assign_case(
            case["id"], {"attorney_id": att["id"], "paralegal_id": para["id"],
                         "expected_case_version": case["version"]},
            make_supervising_attorney_headers(sup["id"])))
        resp = api.close_case(case["id"], {"outcome_code": "ADVICE_GIVEN"},
                              make_paralegal_headers(para["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_grants_manager_cannot_accept_report_but_director_can(self, api):
        """PRD §3.9: "The report lifecycle walks `DRAFT` to `SUBMITTED` by
        the grants manager, then to terminal `ACCEPTED` by the
        `ProgramDirector`, or back to `RETURNED` when the director supplies a
        non-empty `return_reason` — its absence fails with
        `ERR_INVALID_REQUEST` — and a returned report is revised by the
        grants manager back to `DRAFT`, recomputing every aggregate at that
        moment."
        PRD §2.1: "A request whose role is declared but not listed among the
        roles permitted for the target endpoint is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/grants_manager_cannot_accept_report_but_director_can
        """
        grant = create_grant_program(name="Rep Fund")
        gm = make_grants_manager_headers()
        report = validate_success(
            api.create_grant_report(grant["id"], {"period_label": "2026-Q3"}, gm),
            expected_status=201)
        validate_success(api.submit_grant_report(report["id"], gm))
        bad = api.accept_grant_report(report["id"], gm)
        validate_error(bad, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
        good = api.accept_grant_report(report["id"], make_program_director_headers())
        assert validate_success(good)["status"] == "ACCEPTED"


class TestListingAndPagination:
    def test_cases_filtered_by_attorney_and_status(self, api):
        """PRD §3.6: "The staff register supports filtering by
        `supervising_attorney_id`, `staff_type`, `status`, a single
        `practice_area`, or a single `county`."
        PRD §4 (GET /cases): "List cases" with optional filters.

        Design: Corner/entities/cases_filtered_by_attorney_and_status
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        att_a = create_attorney(full_name="Att A", practice_areas=["CONSUMER_DEBT"])
        att_b = create_attorney(full_name="Att B", practice_areas=["CONSUMER_DEBT"])
        headers_sup = make_supervising_attorney_headers(sup["id"])

        def make_case(name, opposing, attorney):
            client = create_client(intake["id"], full_name=name)
            app = create_openable_application(intake["id"], client["id"],
                                              case_type="CONSUMER_DEBT",
                                              opposing_party_name=opposing)
            case = open_case_from_application(app["id"], sup["id"],
                                              service_level="ADVICE_ONLY")
            validate_success(api.assign_case(
                case["id"], {"attorney_id": attorney["id"],
                             "expected_case_version": case["version"]}, headers_sup))
            return case

        ca1 = make_case("Cli F1", "X1", att_a)
        ca2 = make_case("Cli F2", "X2", att_a)
        validate_success(api.place_hold(ca2["id"], {}, headers_sup))
        ca3 = make_case("Cli F3", "X3", att_b)

        cases, meta = validate_paginated(api.list_cases(
            headers_sup, params={"assigned_attorney_id": att_a["id"], "status": "OPEN"}))
        assert meta["total_count"] == 1
        ids = [c["id"] for c in cases]
        assert ids == [ca1["id"]]
        assert ca2["id"] not in ids and ca3["id"] not in ids

    def test_reverse_reachability_subresource_and_filter(self, api):
        """PRD §3.3: "the checks for an application can be listed through the
        application's sub-resource view."
        PRD §3.8: "surveys are immutable once recorded, and a case's survey
        list therefore returns zero or one record."
        PRD §3.4: "The waitlist listing presents entries in this same ranking
        order and can be filtered by `application_id`."

        Design: Corner/entities/reverse_reachability_subresource_and_filter
        """
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["CONSUMER_DEBT"])
        sup = create_supervisor(practice_areas=["CONSUMER_DEBT"])
        headers_in = make_intake_specialist_headers(intake["id"])
        client = create_client(intake["id"], full_name="Cli RR")
        app = create_openable_application(intake["id"], client["id"],
                                          case_type="CONSUMER_DEBT",
                                          opposing_party_name="Collector")
        case = open_case_from_application(app["id"], sup["id"])

        checks, meta_cc = validate_paginated(api.list_conflict_checks(app["id"], headers_in))
        assert meta_cc["total_count"] == 1
        surveys, meta_sv = validate_paginated(api.list_surveys(case["id"], headers_in))
        assert meta_sv["total_count"] == 0
        entries, meta_wl = validate_paginated(
            api.list_waitlist_entries(headers_in, params={"application_id": app["id"]}))
        assert meta_wl["total_count"] == 0

    def test_list_pagination_defaults_and_has_more(self, api):
        """PRD §2.3: "List endpoints accept two query parameters. The `limit`
        parameter caps the number of items returned; it defaults to 10, with
        a minimum of 1 and a maximum of 100. The `offset` parameter skips a
        number of items from the front of the result set and defaults to 0.
        Paginated list responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/cross_cutting_complexity_layers/list_pagination_defaults_and_has_more
        """
        intake = create_intake_specialist()
        headers = make_intake_specialist_headers(intake["id"])
        for i in range(1, 13):
            create_client(intake["id"], full_name=f"C{i:02d}",
                          annual_gross_income_cents=100,
                          annual_countable_income_cents=100)

        page1, meta1 = validate_paginated(api.list_clients(headers))
        assert len(page1) == 10
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(api.list_clients(headers, params={"offset": 10}))
        assert len(page2) == 2
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
        # envelope meta is carried on every response
        raw = api.list_clients(headers).json()
        assert "api_request_id" in raw["meta"]
        assert "api_request_timestamp" in raw["meta"]
