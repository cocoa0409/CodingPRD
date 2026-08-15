"""Queue A difficulty tests: priority-pair validation conflicts."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_provider_ops_headers,
    setup_auto_expired_case,
    setup_matched_ira,
    create_active_recordkeeper,
)

OPS = TEST_USERS["provider_ops_headers"]


class TestIraEstablishStateBeatsFiscal:
    def _setup_executed_cash_case(self):
        """Auto cash-out case fully executed: check ISSUED, case EXECUTED,
        force_out_path == CASH_OUT."""
        ctx = setup_auto_expired_case(balance=50000)
        get_success_data(api_client.create_check(
            {"distribution_case_id": ctx["case"]["id"]}, OPS))
        ctx["case"] = get_success_data(
            api_client.get_distribution_case(ctx["case"]["id"], OPS))
        assert ctx["case"]["case_status"] == "EXECUTED"
        assert ctx["case"]["force_out_path"] == "CASH_OUT"
        return ctx

    def test_state_error_outranks_fiscal(self):
        """PRD §2.9: "Every request is evaluated against eleven tiers of checks in a fixed
        order, and the first failing tier produces the response."
        PRD §3.6: "any other case state is `ERR_INVALID_STATE`"

        Design: Difficulty/priority_pair_validation_conflict/ira_establish_state_beats_fiscal
        """
        ctx = self._setup_executed_cash_case()
        # Case is EXECUTED (state violation, tier 6) AND its path is CASH_OUT
        # (fiscal violation, tier 11). The earlier tier must fire.
        res = api_client.create_safe_harbor_ira(
            {"distribution_case_id": ctx["case"]["id"]}, OPS)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_state_error_http_status(self):
        """PRD §2.9: "6. **State permits the transition** — the target entity's current
        state must allow the requested transition, including state guards such as an IRA
        not being `MATCHED` or a case not being `NOTIFIED`; failure is
        `ERR_INVALID_STATE` (409)."
        PRD §2.9: "11. **Money and threshold rules** — threshold configuration sanity on
        plan update, automatic execution only on the path the lock selected, a positive
        transfer amount, the match-score floor for manual confirm, and the SSN gate;
        failures are `ERR_THRESHOLD_CONFIG_INVALID`, `ERR_CASE_BALANCE_INELIGIBLE`,
        `ERR_INSUFFICIENT_IRA_BALANCE`, `ERR_MATCH_SCORE_BELOW_THRESHOLD`, and
        `ERR_SSN_GATE_FAILED` (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/ira_establish_state_beats_fiscal
        """
        ctx = self._setup_executed_cash_case()
        res = api_client.create_safe_harbor_ira(
            {"distribution_case_id": ctx["case"]["id"]}, OPS)
        err = validate_error(res, ApiErrorId.ERR_INVALID_STATE, 409)
        assert err["error_id"] == "ERR_INVALID_STATE"
        # Explicitly NOT the fiscal error even though the path also mismatches.
        assert err["error_id"] != "ERR_CASE_BALANCE_INELIGIBLE"


class TestTransferSafetyBeatsReferential:
    def _setup(self):
        """IRA MATCHED to plan Y at RK-B, NO prenotice sent, then RK-B SUSPENDED."""
        ctx = setup_matched_ira(balance=300000)
        # Suspend RK-B; a suspension does NOT expire the CONFIRMED match
        # (only exit does per PRD §2.8).
        get_success_data(api_client.suspend_recordkeeper(ctx["rk_b"]["id"], OPS))
        ctx["ira"] = get_success_data(
            api_client.get_safe_harbor_ira(ctx["ira"]["id"], OPS))
        assert ctx["ira"]["ira_status"] == "MATCHED"
        return ctx

    def test_safety_error_outranks_referential(self):
        """PRD §2.9: "Every request is evaluated against eleven tiers of checks in a fixed
        order, and the first failing tier produces the response."
        PRD §2.9: "7. **Compliance gates** — segregation of duties on review creation, fee
        disclosure before fee assessment, prenotice delivery before transfer, the
        escheat-warning lead time, and no unnoticed case at batch execute; failures are
        `ERR_SEGREGATION_OF_DUTIES`, `ERR_FEE_DISCLOSURE_NOT_DELIVERED`,
        `ERR_PRENOTICE_NOT_DELIVERED`, `ERR_ESCHEAT_WARNING_REQUIRED`, and
        `ERR_CASE_NOTICE_OUTSTANDING` (all 422)."
        PRD §2.9: "9. **Referenced-entity state** — the plan must be `ACTIVE` for case
        creation, the recordkeeper `ACTIVE` for matching and transfer, the match's
        plan-recordkeeper pair must agree, and a destination plan must be reachable;
        failures are `ERR_PLAN_NOT_ACTIVE`, `ERR_RECORDKEEPER_NOT_ACTIVE`,
        `ERR_RECORDKEEPER_PLAN_MISMATCH`, and `ERR_DESTINATION_PLAN_NOT_ACCEPTING`
        (all 422)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_safety_beats_referential
        """
        ctx = self._setup()
        # No DELIVERED prenotice (safety, tier 7) AND RK-B suspended (referential,
        # tier 9). The earlier tier must fire.
        res = api_client.create_transfer(
            ctx["ira"]["id"],
            {"expected_ira_version": ctx["ira"]["version"]},
            OPS,
        )
        validate_error(res, ApiErrorId.ERR_PRENOTICE_NOT_DELIVERED, 422)

    def test_safety_error_id_exact(self):
        """PRD §3.7: "an `AUTO_PORTABILITY_PRENOTICE` notice for the case must have reached
        `DELIVERED` (`ERR_PRENOTICE_NOT_DELIVERED`)"
        PRD §3.7: "The match's recordkeeper must still be `ACTIVE`
        (`ERR_RECORDKEEPER_NOT_ACTIVE`)."

        Design: Difficulty/priority_pair_validation_conflict/transfer_safety_beats_referential
        """
        ctx = self._setup()
        res = api_client.create_transfer(
            ctx["ira"]["id"],
            {"expected_ira_version": ctx["ira"]["version"]},
            OPS,
        )
        err = validate_error(res, ApiErrorId.ERR_PRENOTICE_NOT_DELIVERED)
        assert err["error_id"] == "ERR_PRENOTICE_NOT_DELIVERED"
        assert err["error_id"] != "ERR_RECORDKEEPER_NOT_ACTIVE"
