"""Security (RBAC, identity binding), validation priority, posture gates, and
case version increment behavior."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_case_payload, create_objection_payload,
    make_creditor_headers, create_creditor, create_case, create_asset,
    file_claim, get_case, get_case_version, review_claim, object_to_claim,
    set_clock, setup_case_in_claims_administration, setup_case_in_liquidation,
)

TRUSTEE = TEST_USERS["trustee_headers"]
CLERK = TEST_USERS["clerk_headers"]
COURT = TEST_USERS["court_headers"]


class TestAuthHeaders:
    def test_missing_auth_header_rejected(self, api):
        """PRD §2.1: "All interactions with the API must be authenticated
        through two mandatory HTTP headers: `X-User-ID` identifies the acting
        user, and `X-User-Role` specifies their operational capacity."
        PRD §2.1: "A request that is missing either header, or that presents a
        malformed value, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_rejected
        """
        case = create_case(case_number="26-20020")
        resp = api.get_case(case["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRolePermissions:
    def test_forbidden_role_rejected(self, api):
        """PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §4: `POST /trustee/cases` is authorized for the `Clerk` role only.

        Design: Corner/validations/forbidden_role_rejected
        """
        cred = create_creditor(creditor_ref="CR-RB-1")
        resp = api.create_case(create_case_payload(case_number="26-20021"),
                               make_creditor_headers(cred["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_clerk_cannot_object_to_claims(self, api):
        """PRD §3.3: "Objection is the trustee's attack on the claim."
        PRD §4: `POST /trustee/claims/{id}/objections` is authorized for the
        `Trustee` role only.
        PRD §2.1: "A request whose role is not permitted for the target
        endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/clerk_cannot_object_to_claims
        """
        ctx = setup_case_in_claims_administration(case_number="26-20052")
        claim = file_claim(ctx["case"]["id"], ctx["creditor"]["id"])
        review_claim(claim["id"])
        resp = api.create_objection(claim["id"], create_objection_payload(), CLERK)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_creditor_cannot_withdraw_another_creditors_claim(self, api):
        """PRD §2.1: "When `X-User-Role` is `Creditor`, `X-User-ID` is the `id`
        of the acting `Creditor`; ownership checks on any resource that
        references a `Creditor` compare the resource's foreign-key field to
        `X-User-ID` — concretely, a creditor may withdraw only a claim whose
        `creditor_id` equals the presented `X-User-ID`, and a mismatch is
        rejected with `ERR_NOT_ASSIGNED_TRUSTEE` (HTTP 403)."

        Design: Corner/rbac/creditor_cannot_withdraw_another_creditors_claim
        """
        cred_a = create_creditor(legal_name="A", creditor_ref="CR-RA-1")
        cred_b = create_creditor(legal_name="B", creditor_ref="CR-RB-2")
        ctx = setup_case_in_claims_administration(case_number="26-20051")
        claim = file_claim(ctx["case"]["id"], cred_a["id"])
        resp = api.withdraw_claim(claim["id"], make_creditor_headers(cred_b["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_TRUSTEE)


class TestBarDateValidation:
    def test_invalid_bar_date_rejected(self, api):
        """PRD §3.2: "The supplied `bar_date` must be strictly after the case's
        `filed_on`; a bar date on or before the petition date is rejected with
        `ERR_INVALID_BAR_DATE` (HTTP 422)."

        Design: Corner/validations/invalid_bar_date_rejected
        """
        case = create_case(case_number="26-20022")
        create_asset(case["id"])
        get_success_data(api_client.begin_investigation(case["id"], TRUSTEE))
        resp = api.set_bar_date(case["id"], "2026-01-15T00:00:00Z", CLERK)
        validate_error(resp, ApiErrorId.ERR_INVALID_BAR_DATE)


class TestValidationPriority:
    def test_state_violation_outranks_temporal_on_begin_liquidation(self, api):
        """PRD §2.11: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order, and the earliest
        failing tier determines the error surfaced:"
        PRD §2.11: "5. From-state validity for the requested transition —
        `ERR_INVALID_STATE`."
        PRD §2.11: "7. Temporal gates: the liquidation gate requires the
        logical clock to be strictly past the bar date
        (`ERR_BAR_DATE_NOT_PASSED`), sale consummation requires the clock to be
        at or past `effective_on` (`ERR_OBJECTION_WINDOW_OPEN`), and fee
        payment requires the clock to be at or past `effective_on`
        (`ERR_FEE_NOT_YET_EFFECTIVE`)."

        The case is OPEN (state violation) and no bar date exists, so the
        temporal gate could never be satisfied either; the state tier fires.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_begin_liquidation
        """
        case = create_case(case_number="26-10009")
        resp = api.begin_liquidation(case["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_temporal_gate_fires_when_state_is_valid(self, api):
        """PRD §3.4: "Beginning liquidation moves the case from
        `CLAIMS_ADMINISTRATION` to `LIQUIDATION` and requires the logical clock
        to be strictly past `claim_bar_date` (else `ERR_BAR_DATE_NOT_PASSED`)
        and every claim — timely or late — to have moved at least to
        `UNDER_REVIEW`, with any claim still `FILED` rejected as
        `ERR_CLAIMS_UNREVIEWED`."

        With the case in CLAIMS_ADMINISTRATION, no claims at all, and the
        clock exactly at the bar date (not strictly past), only the temporal
        gate can fail.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_temporal_on_begin_liquidation
        """
        ctx = setup_case_in_claims_administration(case_number="26-10009")
        set_clock("2026-06-01T00:00:00Z")  # exactly at the bar date
        resp = api.begin_liquidation(ctx["case"]["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_BAR_DATE_NOT_PASSED)


class TestCasePostureDependency:
    def _case_with_objected_claim(self):
        ctx = setup_case_in_claims_administration(case_number="26-10013")
        case_id = ctx["case"]["id"]
        claim = file_claim(case_id, ctx["creditor"]["id"])
        review_claim(claim["id"])
        obj = object_to_claim(claim["id"], grounds="INSUFFICIENT_DOCUMENTATION",
                              proposed_allowed_amount_cents=0)
        set_clock("2026-06-02T00:00:00Z")
        get_success_data(api_client.begin_liquidation(case_id, TRUSTEE))
        return ctx, claim, obj

    def test_begin_distribution_blocked_by_objected_claim(self, api):
        """PRD §3.4: "Beginning distribution moves the case from `LIQUIDATION`
        to `DISTRIBUTION` and requires no asset still in `MARKED_FOR_SALE` or
        `IN_AUCTION` (else `ERR_ASSETS_PENDING_SALE`), no claim still
        `OBJECTED` (else `ERR_OBJECTIONS_PENDING`), and a strictly positive
        `estate_cash_on_hand_cents` (else `ERR_NO_FUNDS_TO_DISTRIBUTE`)."

        Design: Difficulty/cross_entity_state_dependency/plan_confirm_gated_by_case_posture
        """
        ctx, claim, obj = self._case_with_objected_claim()
        resp = api.begin_distribution(ctx["case"]["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_OBJECTIONS_PENDING)

    def test_begin_distribution_gate_releases_after_objection_resolved(self, api):
        """PRD §3.3: "The objection becomes `SUSTAINED`, the claim becomes
        `DISALLOWED` with `allowed_amount_cents` zeroed, and the claim's
        `objection_id` clears to null."
        PRD §3.4: "Beginning distribution moves the case from `LIQUIDATION` to
        `DISTRIBUTION` and requires no asset still in `MARKED_FOR_SALE` or
        `IN_AUCTION` (else `ERR_ASSETS_PENDING_SALE`), no claim still
        `OBJECTED` (else `ERR_OBJECTIONS_PENDING`), and a strictly positive
        `estate_cash_on_hand_cents` (else `ERR_NO_FUNDS_TO_DISTRIBUTE`)."

        After the objection is sustained the register gate releases; with zero
        estate cash only the fiscal gate still blocks.

        Design: Difficulty/cross_entity_state_dependency/plan_confirm_gated_by_case_posture
        """
        ctx, claim, obj = self._case_with_objected_claim()
        validate_success(api.sustain_objection(obj["id"], COURT))
        resp = api.begin_distribution(ctx["case"]["id"], TRUSTEE)
        validate_error(resp, ApiErrorId.ERR_NO_FUNDS_TO_DISTRIBUTE)


class TestVersionIncrements:
    def test_version_increments_on_every_case_mutation(self, api):
        """PRD §3.1: "Filing sets `no_asset_report_filed` to true and closes
        the case; each of these case-level posture changes increments the
        case's `version`."
        PRD §3.2: "When the bar date is accepted, four things happen
        atomically: `claim_bar_date` is recorded on the case,
        `bar_date_noticed` flips to true (the §341/bar-date notice to scheduled
        creditors has issued), the case advances from `ASSET_INVESTIGATION` to
        `CLAIMS_ADMINISTRATION`, and every asset still `SCHEDULED` is swept to
        `UNDER_INVESTIGATION`. The case's `version` increments."
        PRD §3.3: "an `UNDER_REVIEW` claim becomes `ALLOWED`, its
        `allowed_amount_cents` is set equal to its `filed_amount_cents`, and
        the case's `allowed_claims_total_cents` increases by that amount, with
        the case `version` bumping accordingly."

        Each observed version advances by exactly one per case mutation.

        Design: Corner/cross_cutting_layers/version_increments_on_every_case_mutation
        """
        cred = create_creditor(creditor_ref="CR-VI-1")
        case = create_case(case_number="26-20061")
        v0 = case["version"]
        create_asset(case["id"])
        after_inv = validate_success(api.begin_investigation(case["id"], TRUSTEE))
        assert after_inv["version"] == v0 + 1
        after_bar = validate_success(
            api.set_bar_date(case["id"], "2026-06-01T00:00:00Z", CLERK))
        assert after_bar["version"] == after_inv["version"] + 1
        claim = file_claim(case["id"], cred["id"])
        review_claim(claim["id"])
        get_success_data(api.allow_claim(claim["id"], TRUSTEE))
        after_allow = get_case(case["id"])
        assert after_allow["version"] == after_bar["version"] + 1, \
            "claim allowance cascades a case version increment"
