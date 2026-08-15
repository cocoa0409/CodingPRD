"""Global specifications: auth headers, role-based access, response envelope,
reference data (state rules, employers), and claim intake validation."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_claim,
    assert_employer,
    create_employer,
    create_separation,
    create_state_rule,
    get_success_data,
    set_clock,
    setup_statement_with_line,
    create_claim_payload,
    create_employer_payload,
    create_model,
    create_separation_payload,
    create_state_rule_payload,
    setup_under_adjudication_claim,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["claims_analyst_headers"]
TPA_AGENT = TEST_USERS["tpa_agent_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]
AUDITOR = TEST_USERS["charge_auditor_headers"]
RATER = TEST_USERS["rating_analyst_headers"]


class TestAuthHeaders:
    def test_missing_auth_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an
        unrecognized role, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_headers_rejected
        """
        resp = api.list_claims(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400)


class TestReferenceData:
    def test_state_rule_invalid_enum_rejected(self, api):
        """PRD §2.8: "required fields must be present, types must match, and
        enum values must lie in their declared domains; violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "its `response_window_days` with a `window_basis` of
        `CALENDAR` or `BUSINESS`"

        Design: Corner/entities/state_rule_invalid_enum_rejected
        """
        payload = create_state_rule_payload("YY", window_basis="LUNAR")
        resp = api.create_state_rule(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_separation_missing_required_field_rejected(self, api):
        """PRD §2.8: "required fields must be present, types must match, and
        enum values must lie in their declared domains; violations yield
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.2: "A `ClaimsAnalyst` records a `ClaimantSeparation` with the
        separating `employer_id`, the `claimant_name`, the claimant's
        `ssn_last4` (a 4-digit string), the `last_day_worked`, and the
        `separation_reason`"

        Design: Corner/entities/separation_missing_required_field_rejected
        """
        employer = create_employer()
        payload = create_separation_payload(employer["id"])
        del payload["separation_reason"]
        resp = api.create_separation(payload, ANALYST)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)

    def test_employer_creation_defaults_applied(self, api):
        """PRD §3.1: "The account may optionally seed `reserve_balance_cents`,
        which starts at zero when omitted. A new account begins with
        `compliance_posture` `CLEAR`, zero `late_response_strikes`, zero
        `protest_credits_cents`, and a `current_tax_rate_bps` computed at
        creation — 270 basis points until the experience-rating projection of
        §3.7 recomputes it."

        Design: Corner/entities/employer_creation_defaults_applied
        """
        payload = create_employer_payload(legal_name="DefCo")
        data = validate_success(api.create_employer(payload, ADMIN), 201)
        assert_employer(data)
        assert data["reserve_balance_cents"] == 0
        assert data["compliance_posture"] == "CLEAR"
        assert data["late_response_strikes"] == 0
        assert data["protest_credits_cents"] == 0
        assert data["current_tax_rate_bps"] == 270

    def test_rating_summary_computed_read(self, api):
        """PRD §3.7: "A computed read, the employer's rating summary, exposes
        the current standing in one place: `current_tax_rate_bps`,
        `compliance_posture`, `late_response_strikes`, and
        `protest_credits_cents`."
        PRD §3.1: "A new account begins with `compliance_posture` `CLEAR`, zero
        `late_response_strikes`, zero `protest_credits_cents`, and a
        `current_tax_rate_bps` computed at creation — 270 basis points until
        the experience-rating projection of §3.7 recomputes it."

        Design: Corner/endpoints/rating_summary_computed_read
        """
        employer = create_employer(legal_name="SumCo")
        data = validate_success(api.get_rating_summary(employer["id"], RATER), 200)
        assert data["current_tax_rate_bps"] == 270
        assert data["compliance_posture"] == "CLEAR"
        assert data["late_response_strikes"] == 0
        assert data["protest_credits_cents"] == 0


class TestClaimIntake:
    def test_get_claim_not_found_returns_404(self, api):
        """PRD §2.8: "the request is rejected with `ERR_NOT_FOUND` (HTTP 404)
        at the *first* identifier that does not exist; later identifiers are
        not examined."

        Design: Corner/entities/get_claim_not_found_returns_404
        """
        resp = api.get_claim(NON_EXISTENT_UUID, ANALYST)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND, 404)

    def test_claims_list_pagination_envelope(self, api):
        """PRD §2.3: "If not provided, it defaults to 10, with a minimum of 1
        and a maximum of 100."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/claims_list_pagination_envelope
        """
        set_clock()
        create_state_rule("XX")
        employer = create_employer(legal_name="PageCo")
        separation = create_separation(employer["id"])
        api.create_claim(create_claim_payload(employer["id"], separation["id"]),
                         ANALYST)
        resp = api.list_claims(ANALYST)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"].get("api_request_id"), str)
        data, meta = validate_paginated(resp)
        assert len(data) == 1
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert_claim(data[0])

    def test_claim_system_fields_ignore_client_input(self, api):
        """PRD §3.3: "The claim's `status` opens at `NOTICE_RECEIVED`, its
        `charged_amount_cents` at zero, and its `response_channel` stays null
        until a response is actually submitted, when it becomes `SELF` or
        `TPA`."

        Design: Corner/entities/claim_system_fields_ignore_client_input
        """
        set_clock()
        create_state_rule("XX")
        employer = create_employer(legal_name="SysCo")
        separation = create_separation(employer["id"])
        data = validate_success(
            api.create_claim(
                create_claim_payload(employer["id"], separation["id"]), ANALYST),
            201)
        assert_claim(data)
        assert data["status"] == "NOTICE_RECEIVED"
        assert data["charged_amount_cents"] == 0
        assert data["response_channel"] is None
        # Ten calendar days remain until the computed deadline.
        assert data["adjudication_posture"] == "STANDARD"

    def test_claim_reference_to_other_employers_separation_rejected(self, api):
        """PRD §2.8: "a claim's separation must belong to the same employer as
        the claim itself. A reference that resolves but belongs to a different
        parent yields `ERR_CROSS_PARENT_REFERENCE` (HTTP 422)."

        Design: Corner/entities/claim_reference_to_other_employers_separation_rejected
        """
        set_clock()
        create_state_rule("XX")
        employer_a = create_employer(legal_name="Own1")
        employer_b = create_employer(legal_name="Own2")
        separation = create_separation(employer_b["id"])
        resp = api.create_claim(
            create_claim_payload(employer_a["id"], separation["id"]), ANALYST)
        validate_error(resp, ApiErrorId.ERR_CROSS_PARENT_REFERENCE, 422)

    def test_reverse_reachability_employer_claims(self, api):
        """PRD §3.3: "Claims can be listed with optional filters —
        `employer_id`, `state_code`, `status`, and `separation_id` — and each
        claim exposes its responses, evidence, determinations, hearings, and
        charge line items for reverse reachability."
        PRD §4: "`/ui/employers/{id}/claims` | Claims for an employer"

        Design: Corner/entities/reverse_reachability_employer_claims
        """
        set_clock()
        create_state_rule("XX")
        employer_a = create_employer(legal_name="RevA")
        employer_b = create_employer(legal_name="RevB")
        sep_a = create_separation(employer_a["id"], claimant_name="Gus",
                                  ssn_last4="1005")
        sep_b = create_separation(employer_b["id"], claimant_name="Hank",
                                  ssn_last4="1006")
        claim_a = get_success_data(api.create_claim(
            create_claim_payload(employer_a["id"], sep_a["id"]), ANALYST))
        api.create_claim(create_claim_payload(employer_b["id"], sep_b["id"]), ANALYST)

        data, meta = validate_paginated(api.list_employer_claims(employer_a["id"], ANALYST))
        assert meta["total_count"] == 1
        assert len(data) == 1
        assert data[0]["id"] == claim_a["id"]
        assert data[0]["employer_id"] == employer_a["id"]
        assert data[0]["state_claim_number"] == claim_a["state_claim_number"]


class TestRbacSegregationOfDuties:
    def test_charge_auditor_cannot_record_determination(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "`/ui/claims/{id}/determinations` | Record agency determination
        | AgencyLiaison"

        Design: Corner/rbac/charge_auditor_cannot_record_determination
        """
        set_clock()
        create_state_rule("XX")
        ctx = setup_under_adjudication_claim()
        resp = api.create_determination(
            ctx["claim"]["id"],
            {"outcome": "ALLOWED", "mailed_at": "2026-08-05T09:00:00Z"},
            AUDITOR)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_tpa_agent_cannot_file_protest(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "`/ui/charge-line-items/{id}/protests` | File charge protest
        (OCC on statement) | ChargeAuditor"

        Design: Corner/rbac/tpa_agent_cannot_file_protest
        """
        set_clock()
        create_state_rule("XX")
        ctx = setup_statement_with_line(amount_cents=100_000, erroneous_reason=None)
        version = ctx["statement"]["version"]
        resp = api.file_protest(ctx["line"]["id"], "DUPLICATE_LINE", version,
                                TPA_AGENT)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)

    def test_claims_analyst_cannot_finalize_model(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §4: "`/ui/employers/{id}/experience-rating-models/{mid}/finalize` |
        Finalize model (OCC on employer; supersedes prior official) |
        RatingAnalyst"

        Design: Corner/rbac/claims_analyst_cannot_finalize_model
        """
        set_clock()
        employer = create_employer(legal_name="Rbac3")
        model = create_model(employer["id"])
        version = get_success_data(api.get_employer(employer["id"], ADMIN))["version"]
        resp = api.finalize_model(employer["id"], model["id"], version, ANALYST)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
