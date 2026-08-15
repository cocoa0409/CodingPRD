"""Reference data: counterparties, users, contract types — defaults and retire guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_user_payload, create_counterparty_payload, create_contract_type_payload,
    assert_counterparty, assert_user, assert_contract_type,
    setup_user_directory, headers_by_id,
    setup_negotiation_ctx,
)

OPS = TEST_USERS["ops_admin_headers"]


class TestCounterpartyDefaults:
    def test_counterparty_risk_tier_defaults_to_standard(self, api):
        """Omitting risk_tier on counterparty creation applies STANDARD.

        PRD §3.2: "the optional `risk_tier` accepts `LOW`, `STANDARD`, `HIGH_RISK`,
        or `SANCTIONED` and defaults to `STANDARD` when omitted."

        Design: Corner/entities/counterparty_risk_tier_default_standard
        """
        payload = {"legal_name": "DefaultCo", "jurisdiction": "US-CA"}
        resp = api.create_counterparty(payload, OPS)
        data = validate_success(resp, expected_status=201)
        assert_counterparty(data)
        assert data["risk_tier"] == "STANDARD", (
            f"default risk_tier must be STANDARD, got {data['risk_tier']}")


class TestUserDefaults:
    def test_user_signing_authority_defaults_to_zero(self, api):
        """Omitting can_sign_above_cents yields 0 — the user can sign nothing.

        PRD §3.2: "and it defaults to 0, which, because the authority comparison is
        strict, means the user cannot sign anything at all."

        Design: Corner/entities/user_can_sign_above_cents_default_zero
        """
        resp = api.create_user(
            create_user_payload("nosign@example.com", "No Sign", "SIGNATORY"), OPS)
        data = validate_success(resp, expected_status=201)
        assert_user(data)
        assert data["can_sign_above_cents"] == 0, (
            f"default signing ceiling must be 0, got {data['can_sign_above_cents']}")


class TestContractTypeThresholds:
    def test_contract_type_non_monotonic_thresholds_rejected(self, api):
        """mid == low violates the strictly-ascending ladder.

        PRD §3.2: "The three must be strictly ascending — the mid threshold strictly
        greater than the low, the high strictly greater than the mid — and a creation
        that violates this ordering is rejected with `ERR_THRESHOLDS_NOT_MONOTONIC`
        (HTTP 422)."

        Design: Corner/validations/contract_type_thresholds_not_monotonic_returns_422
        """
        users = setup_user_directory()
        payload = create_contract_type_payload(
            users["bo"]["id"], users["lc"]["id"], code="BADLADDER",
            low_value_threshold_cents=500_000, mid_value_threshold_cents=500_000,
            high_value_threshold_cents=2_000_000)
        resp = api.create_contract_type(payload, OPS)
        validate_error(resp, ApiErrorId.ERR_THRESHOLDS_NOT_MONOTONIC)
        assert resp.status_code == 422


class TestContractTypeRetireCrossEntityGuard:
    def test_contract_type_retire_blocked_by_active_negotiation(self, api):
        """A contract type referenced by a non-terminal negotiation cannot retire.

        PRD §3.2: "an `OpsAdmin` may retire it — `ACTIVE → RETIRED` — only while no
        negotiation referencing it remains outside `EXECUTED` or `ABORTED`, otherwise
        `ERR_CONTRACT_TYPE_IN_USE`, and `RETIRED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/contract_type_retire_blocked_by_active_negotiation
        """
        ctx = setup_negotiation_ctx(ct_code="MSA")
        assert ctx.negotiation["draft_status"] == "OPEN"

        resp = api.retire_contract_type(ctx.contract_type["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_TYPE_IN_USE)
        assert resp.status_code == 409

        ct = get_success_data(api.get_contract_type(ctx.contract_type["id"], OPS))
        assert ct["status"] == "ACTIVE", "contract type must remain ACTIVE after refused retire"

    def test_contract_type_retire_succeeds_after_negotiation_aborted(self, api):
        """Aborting the referencing negotiation frees the contract type to retire.

        PRD §3.2: "an `OpsAdmin` may retire it — `ACTIVE → RETIRED` — only while no
        negotiation referencing it remains outside `EXECUTED` or `ABORTED`, otherwise
        `ERR_CONTRACT_TYPE_IN_USE`, and `RETIRED` is terminal."

        Design: Difficulty/cross_entity_state_dependency/contract_type_retire_blocked_by_active_negotiation
        """
        ctx = setup_negotiation_ctx(ct_code="MSA")

        resp = api.abort_negotiation(
            ctx.negotiation["id"], ctx.headers[ctx.users["ca"]["id"]])
        aborted = validate_success(resp, expected_status=200)
        assert aborted["draft_status"] == "ABORTED"

        resp = api.retire_contract_type(ctx.contract_type["id"], OPS)
        ct = validate_success(resp, expected_status=200)
        assert ct["status"] == "RETIRED"
