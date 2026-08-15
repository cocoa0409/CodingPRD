"""Validation precedence (PRD §2.10): state errors mask fiscal errors, and
the identity-header gate runs before everything else."""
from test_helpers import (
    ApiErrorId,
    get_fee,
    list_waiver_items,
    make_posted_fee_scenario,
    submit_waiver,
    validate_error,
)
from test_helpers.fixtures import TELLER_2


class TestWaiverCreateStateErrorBeatsFiscalError:
    def _setup(self):
        """Fee F1 (3500 POSTED) fully waived by a staff FULL request, leaving
        F1 WAIVED with zero outstanding."""
        ctx = make_posted_fee_scenario(
            program_overrides={"daily_fee_cap_cents": 100000,
                               "max_daily_fees_count": 10})
        account, fee = ctx["account"], ctx["fee"]
        first = submit_waiver(account["id"], [fee["id"]], kind="FULL",
                              reason_code="BANK_ERROR", headers=TELLER_2)
        assert first["status"] == "APPLIED"  # 3500 <= teller cap, staff
        assert get_fee(fee["id"])["status"] == "WAIVED"
        return account, fee, first

    def test_waived_fee_and_excess_amount_yields_fee_not_waivable(self, api):
        """PRD §2.10: "seventh, state-machine validity of the requested
        transition and waivability of listed fees (`ERR_INVALID_STATE_TRANSITION`,
        `ERR_FEE_NOT_WAIVABLE`)" and "twelfth, money rules covering waiver
        authority, waiver amount validity, and recovery caps".
        PRD §2.10: "Validation on any request executes in a fixed precedence
        order, and a failure at an earlier tier masks every later check."
        PRD §3.6: "a listed fee that is already `WAIVED` or `VOIDED`, or that
        belongs to another account, is rejected with `ERR_FEE_NOT_WAIVABLE`."

        Design: Difficulty/priority_pair_validation_conflict/waiver_create_state_error_beats_fiscal_error
        """
        account, fee, _ = self._setup()
        # The listed fee is WAIVED (state, tier 7) AND the FIXED_AMOUNT of
        # 999999 exceeds the listed outstanding (fiscal, tier 12).
        resp = api.create_fee_waiver_request(
            {"account_id": account["id"], "fee_ids": [fee["id"]],
             "kind": "FIXED_AMOUNT", "amount_cents": 999999,
             "reason_code": "GOODWILL"}, TELLER_2)
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_WAIVABLE)

    def test_rejected_dual_violation_writes_nothing(self, api):
        """PRD §3.6: "For every pending-born request, the system creates its
        **WaiverRequestItem** rows — each linking `waiver_request_id` to a
        `fee_id` — with `waived_cents` zero, because per-item amounts for
        pending requests are only computed when the request is applied."
        PRD §2.10: "a failure at an earlier tier masks every later check".

        Design: Difficulty/priority_pair_validation_conflict/waiver_create_state_error_beats_fiscal_error
        """
        account, fee, _ = self._setup()
        resp = api.create_fee_waiver_request(
            {"account_id": account["id"], "fee_ids": [fee["id"]],
             "kind": "FIXED_AMOUNT", "amount_cents": 999999,
             "reason_code": "GOODWILL"}, TELLER_2)
        validate_error(resp, ApiErrorId.ERR_FEE_NOT_WAIVABLE)

        assert get_fee(fee["id"])["status"] == "WAIVED"
        # Only the first (successful) request's allocation row exists.
        items = list_waiver_items(fee_id=fee["id"])
        assert len(items) == 1
        assert items[0]["waived_cents"] == 3500


class TestMissingAuthHeaders:
    def test_request_without_identity_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header, or carrying an empty
        value for either, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."
        PRD §2.10: "first, the presence and non-emptiness of the identity
        headers (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`)".

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_account(
            {"program_id": "11111111-2222-4333-8444-555555555555",
             "holder_name": "No Auth"}, headers=None)
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
