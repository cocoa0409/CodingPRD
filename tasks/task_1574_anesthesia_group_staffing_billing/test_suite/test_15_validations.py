"""Validation-layer claims: auth headers, schema, existence, duplicates,
interval/date overlap guards, credential boundary, TEFRA completeness, fiscal
gate (PRD §2.4, §2.6, §2.7, §2.8, §3.3, §3.5, §3.7)."""
from test_helpers import (
    ADMIN,
    BILLING,
    SCHED,
    ApiErrorId,
    NON_EXISTENT_UUID,
    all_tefra_steps_true,
    build_user_headers,
    create_case,
    create_crna,
    create_fee_schedule,
    create_physician,
    create_published_roster,
    create_provider,
    create_roster,
    create_site,
    create_stipend_agreement,
    get_success_data,
    make_physician_headers,
    propose_and_confirm,
    setup_case_with_confirmed_primary,
    setup_completed_solo_case,
    setup_site_fee_roster,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestAuthHeaderValidation:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        value that is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.get_site(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400, "auth layer precedes existence (not 404)"

    def test_undeclared_role_value_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        value that is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request
        whose role is valid but not permitted for the target endpoint is
        rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/validations/invalid_role_header_rejected
        """
        resp = api.list_providers(headers=build_user_headers("x", "SuperUser"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
        assert resp.status_code == 400, (
            f"an undeclared role value is a 400 header error, not 403; got "
            f"{resp.status_code}")


class TestExistenceChecks:
    def test_unknown_procedure_code_rejected(self, api):
        """PRD §3.2: "The `procedure_code` is a lookup key, not an identifier:
        it must match an existing fee-schedule row's `procedure_code`, and an
        unknown code is rejected with `ERR_UNKNOWN_PROCEDURE_CODE`."

        Design: Corner/validations/unknown_procedure_code_rejected
        """
        site = create_site()
        roster = create_published_roster(site["id"])
        resp = api.create_case(
            {"roster_id": roster["id"], "procedure_code": "NOPE",
             "physical_status": "P1", "scheduled_start_minute": 540,
             "scheduled_end_minute": 600}, SCHED)
        validate_error(resp, ApiErrorId.ERR_UNKNOWN_PROCEDURE_CODE)
        cases = get_success_data(
            api.list_cases(SCHED, params={"roster_id": roster["id"]}))
        rows = cases if isinstance(cases, list) else cases["data"]
        assert len(rows) == 0

    def test_body_fk_roster_not_found_on_case_create(self, api):
        """PRD §2.8: "**Existence** — path identifiers are validated left to
        right, then body foreign keys in declared input order (`site_id`, then
        `roster_id`, then `provider_id`, then `case_id`, then `physician_id`)."

        Design: Corner/validations/body_fk_roster_not_found_on_case_create
        """
        create_fee_schedule("P100", 5)
        resp = api.create_case(
            {"roster_id": NON_EXISTENT_UUID, "procedure_code": "P100",
             "physical_status": "P1", "scheduled_start_minute": 540,
             "scheduled_end_minute": 600}, SCHED)
        validate_error(resp, ApiErrorId.ERR_ROSTER_NOT_FOUND)

    def test_body_fk_provider_not_found_on_assignment_create(self, api):
        """PRD §2.8: "**Existence** — path identifiers are validated left to
        right, then body foreign keys in declared input order (`site_id`, then
        `roster_id`, then `provider_id`, then `case_id`, then
        `physician_id`)."

        Design: Corner/validations/body_fk_provider_not_found_on_assignment_create
        """
        site, fee, roster = setup_site_fee_roster()
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": NON_EXISTENT_UUID,
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": case["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_FOUND)
        assignments = get_success_data(
            api.list_assignments(SCHED, params={"case_id": case["id"]}))
        rows = assignments if isinstance(assignments, list) else assignments["data"]
        assert len(rows) == 0


class TestTimeWindowValidation:
    def test_case_with_start_equal_end_rejected(self, api):
        """PRD §2.8: "**3b. Minute-window sanity** — on case creation, case
        rescheduling, and call-window creation, the start/end minute pair must
        satisfy the §2.4 bounds (start at least 0, end strictly after start,
        end at most 1439); violations yield `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/validations/inverted_time_windows_rejected
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        resp = api.create_case(
            {"roster_id": roster["id"], "procedure_code": "P100",
             "physical_status": "P1", "scheduled_start_minute": 540,
             "scheduled_end_minute": 540}, SCHED)
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

    def test_call_window_with_start_equal_end_rejected(self, api):
        """PRD §2.8: "**3b. Minute-window sanity** — on case creation, case
        rescheduling, and call-window creation, the start/end minute pair must
        satisfy the §2.4 bounds (start at least 0, end strictly after start,
        end at most 1439); violations yield `ERR_INVALID_TIME_WINDOW`."

        Design: Corner/validations/inverted_time_windows_rejected
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        provider = create_crna("Crna One")
        resp = api.create_call_assignment(
            {"roster_id": roster["id"], "provider_id": provider["id"],
             "window_start_minute": 600, "window_end_minute": 600}, SCHED)
        err = validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)
        assert err["error_id"] != "ERR_INVALID_REQUEST"


class TestDuplicateGuards:
    def test_duplicate_roster_per_site_date_rejected(self, api):
        """PRD §3.1: "One roster may exist per site per calendar date; a
        second roster for the same `site_id` and `service_date` is rejected
        with `ERR_DUPLICATE_ROSTER`."

        Design: Corner/validations/duplicate_roster_per_site_date_rejected
        """
        s1 = create_site("General Hospital")
        s2 = create_site("Surgery Center")
        create_roster(s1["id"], service_date="2026-08-10")
        resp = api.create_roster(
            {"site_id": s1["id"], "service_date": "2026-08-10",
             "required_primary_slots": 2, "scheduled_day_end_minute": 1080},
            SCHED)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ROSTER)
        # Same date on a different site is allowed.
        ok = api.create_roster(
            {"site_id": s2["id"], "service_date": "2026-08-10",
             "required_primary_slots": 1, "scheduled_day_end_minute": 1020},
            SCHED)
        validate_success(ok, expected_status=201)

    def test_duplicate_provider_npi_rejected(self, api):
        """PRD §2.7: "a National Provider Identifier in `npi` (unique across
        providers — re-registering an existing identifier is rejected with
        `ERR_DUPLICATE_PROVIDER_NPI`)".

        Design: Corner/validations/duplicate_provider_npi_rejected
        """
        create_provider("CRNA", "Crna One")
        npi_holder = get_success_data(api.list_providers(ADMIN))
        existing = (npi_holder if isinstance(npi_holder, list)
                    else npi_holder["data"])[0]
        resp = api.create_provider(
            {"full_name": "Crna Duplicate", "provider_type": "CRNA",
             "npi": existing["npi"], "credential_expires_on": "2027-06-30",
             "dea_expires_on": "2027-06-30"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROVIDER_NPI)
        _, meta = validate_paginated(api.list_providers(ADMIN))
        assert meta["total_count"] == 1

    def test_duplicate_procedure_code_rejected(self, api):
        """PRD §3.2: "the lookup `procedure_code` (globally unique — a repeat
        is `ERR_DUPLICATE_PROCEDURE_CODE`)".

        Design: Corner/validations/duplicate_procedure_code_rejected
        """
        create_fee_schedule("P100", 5)
        resp = api.create_fee_schedule(
            {"procedure_code": "P100", "base_units": 9,
             "contracted_max_cents": 2000000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PROCEDURE_CODE)

    def test_duplicate_attestation_per_case_physician_rejected(self, api):
        """PRD §3.5: "only one attestation may exist per pair — a duplicate is
        rejected with `ERR_DUPLICATE_ATTESTATION`."

        Design: Corner/validations/duplicate_attestation_per_case_physician_rejected
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        peer = create_physician("Dr. Peer")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        resp = api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ATTESTATION)
        # A different physician on the same case is allowed.
        ok = api.create_attestation(
            {"case_id": case["id"], "physician_id": peer["id"]}, SCHED)
        validate_success(ok, expected_status=201)


class TestAgreementWindowOverlap:
    def test_shared_boundary_date_conflicts(self, api):
        """PRD §2.6: "Stipend-agreement windows (`effective_from`,
        `effective_to`) are **closed date intervals** scoped to one site: the
        end date must not precede the start date, both boundary dates are
        covered, and two agreements for the same site may not share even a
        single calendar date."

        Design: Corner/validations/agreement_window_overlap_closed_date_interval
        """
        site = create_site()
        create_stipend_agreement(site["id"], effective_from="2026-08-10",
                                 effective_to="2026-08-14")
        resp = api.create_stipend_agreement(
            {"site_id": site["id"], "effective_from": "2026-08-14",
             "effective_to": "2026-08-20", "call_stipend_cents": 12000,
             "late_stay_rate_cents_per_minute": 50, "standby_full_cents": 30000,
             "standby_partial_cents": 15000}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)

    def test_disjoint_window_allowed(self, api):
        """PRD §2.6: "two agreements for the same site may not share even a
        single calendar date."

        Design: Corner/validations/agreement_window_overlap_closed_date_interval
        """
        site = create_site()
        create_stipend_agreement(site["id"], effective_from="2026-08-10",
                                 effective_to="2026-08-14")
        resp = api.create_stipend_agreement(
            {"site_id": site["id"], "effective_from": "2026-08-15",
             "effective_to": "2026-08-20", "call_stipend_cents": 12000,
             "late_stay_rate_cents_per_minute": 50, "standby_full_cents": 30000,
             "standby_partial_cents": 15000}, ADMIN)
        validate_success(resp, expected_status=201)


class TestCredentialExpiryBoundary:
    def test_service_on_expiry_date_allowed(self, api):
        """PRD §2.7: "Both expiry dates are valid *through* the named date: a
        provider may serve on the expiry date itself, and only a service date
        strictly later than an expiry violates currency."

        Design: Corner/validations/credential_expired_service_date_boundary
        """
        site, fee, roster = setup_site_fee_roster(
            service_date="2026-08-10", scheduled_day_end_minute=1200)
        provider = create_crna("Crna One", expiry="2026-08-10")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": provider["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": case["version"]}, SCHED)
        validate_success(resp, expected_status=201)

    def test_service_one_day_past_expiry_rejected(self, api):
        """PRD §2.7: "only a service date strictly later than an expiry
        violates currency."
        PRD §3.3: "the roster's `service_date` must not be strictly later than
        either `credential_expires_on` or `dea_expires_on` — else the proposal
        is rejected with `ERR_CREDENTIAL_EXPIRED`."

        Design: Corner/validations/credential_expired_service_date_boundary
        """
        site = create_site()
        create_fee_schedule("P100", 5)
        roster = create_published_roster(site["id"], service_date="2026-08-11",
                                         scheduled_day_end_minute=1200)
        provider = create_crna("Crna One", expiry="2026-08-10")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        resp = api.create_case_assignment(
            case["id"], {"provider_id": provider["id"],
                         "assignment_role": "CASE_PRIMARY",
                         "expected_case_version": case["version"]}, SCHED)
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_EXPIRED)


class TestTefraCompleteness:
    def test_six_true_one_false_rejected(self, api):
        """PRD §3.5: "All seven step flags supplied in the request must be
        true; an incomplete set is rejected with `ERR_TEFRA_STEPS_INCOMPLETE`
        (HTTP 422)".

        Design: Corner/validations/tefra_incomplete_steps_rejected
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        steps = all_tefra_steps_true()
        steps["step_post_anesthesia_care"] = False
        resp = api.submit_attestation(att["id"], steps,
                                      make_physician_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_TEFRA_STEPS_INCOMPLETE)
        after = get_success_data(api.get_attestation(att["id"], SCHED))
        assert after["status"] == "IN_PROGRESS"
        assert after["submitted_count"] == 0


class TestFiscalGate:
    def test_charge_exceeds_contracted_max_rejected(self, api):
        """PRD §3.7: "then that `charge_cents` does not exceed the procedure's
        `contracted_max_cents` (violations are `ERR_CHARGE_EXCEEDS_MAX`, HTTP
        402)".

        Design: Corner/validations/charge_exceeds_max_on_mark_ready_rejected
        """
        # P100 base 5, contracted max 50000; completed 60-min case yields
        # 9.0 units x 8000 = 72000 > 50000.
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST",
                                        contracted_max_cents=50000)
        claim_id = ctx["claims"][0]["id"]
        assert ctx["claims"][0]["charge_cents"] == 72000
        resp = api.mark_claim_ready(claim_id, BILLING)
        validate_error(resp, ApiErrorId.ERR_CHARGE_EXCEEDS_MAX)
        after = get_success_data(api.get_claim(claim_id, BILLING))
        assert after["status"] == "DRAFT"


class TestManualClaimGate:
    def test_manual_claim_without_completed_assignment_rejected(self, api):
        """PRD §3.7: "manual creation requires the case to be `COMPLETED` and
        the provider to hold a `COMPLETED` assignment on it, else
        `ERR_NO_COMPLETED_ASSIGNMENT`".

        Design: Corner/validations/manual_claim_without_completed_assignment_rejected
        """
        ctx = setup_completed_solo_case(provider_type="ANESTHESIOLOGIST")
        stranger = create_crna("Crna Two")
        resp = api.create_claim({"case_id": ctx["case"]["id"],
                                 "provider_id": stranger["id"]}, BILLING)
        validate_error(resp, ApiErrorId.ERR_NO_COMPLETED_ASSIGNMENT)


class TestSelfReviewForbidden:
    def test_verify_own_attestation_forbidden(self, api):
        """PRD §3.5: "verification and rejection both require the caller to be
        an `AttendingAnesthesiologist` whose `X-User-ID` differs from the
        attestation's `physician_id`, and a self-review is rejected with
        `ERR_SELF_REVIEW_FORBIDDEN`."

        Design: Corner/validations/self_review_forbidden_on_verify_and_reject
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        resp = api.verify_attestation(att["id"],
                                      make_physician_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN)

    def test_reject_own_attestation_forbidden(self, api):
        """PRD §3.5: "verification and rejection both require the caller to be
        an `AttendingAnesthesiologist` whose `X-User-ID` differs from the
        attestation's `physician_id`, and a self-review is rejected with
        `ERR_SELF_REVIEW_FORBIDDEN`."

        Design: Corner/validations/self_review_forbidden_on_verify_and_reject
        """
        site, fee, roster = setup_site_fee_roster(required_primary_slots=0,
                                                  scheduled_day_end_minute=1020)
        director = create_physician("Dr. Direct")
        case = create_case(roster["id"], scheduled_start_minute=540,
                           scheduled_end_minute=600)
        att = get_success_data(api.create_attestation(
            {"case_id": case["id"], "physician_id": director["id"]}, SCHED))
        get_success_data(api.submit_attestation(
            att["id"], all_tefra_steps_true(),
            make_physician_headers(director["id"])))
        resp = api.reject_attestation(att["id"],
                                      {"rejection_reason": "SELF_REVIEW"},
                                      make_physician_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_SELF_REVIEW_FORBIDDEN)
        after = get_success_data(api.get_attestation(att["id"], SCHED))
        assert after["status"] == "SUBMITTED"
