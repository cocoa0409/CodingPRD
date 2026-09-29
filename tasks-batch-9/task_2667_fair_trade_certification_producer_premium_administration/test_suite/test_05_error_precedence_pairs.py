"""When one request breaks two rules at once, which refusal the caller sees."""

from test_helpers import (
    CHAIR,
    MISSING_USER_ID_HEADER,
    OFFICER,
    api_errors as E,
    assert_fund_partition,
    factories as f,
    make_producer_representative_headers,
    validate_error,
    validate_success,
)
from test_helpers.test_users import AUDITOR

NONEXISTENT_TRADE_ID = "00000000-0000-4000-8000-000000000000"


def _suspended_producer_with_a_funded_committee(api):
    """A suspended producer whose committee still sits over a 1200000 cent balance."""
    chain = f.build_certified_chain(api, harvest_kg=50000)
    committee = f.constitute_committee(
        api, chain["producer_id"], member_count=5,
        approved_use_categories=["EDUCATION", "INFRASTRUCTURE"],
    )
    chain["committee_id"] = committee["id"]
    f.record_settled_trade(api, chain, 15000, declared_unit_price_cents_per_kg=500)
    chain["fund_version"] = f.read_fund(api, chain["producer_id"])["version"]
    validate_success(
        api.suspend_holder(chain["producer_id"], f.reason_payload("MANUAL"), OFFICER), 200
    )
    return chain


def _water_point_proposal(chain, amount_cents):
    return f.proposal_payload(
        chain["committee_id"], chain["fund_version"], amount_cents,
        title="Village water point", use_category="INFRASTRUCTURE",
        use_period_start="2026-09-01", use_period_end="2026-10-01",
    )


class TestSuspensionOutranksFundBalance:
    """A suspended holder's premium spending is blocked before its arithmetic is examined."""

    def test_a_request_breaking_both_rules_is_refused_for_the_suspension(self, api, clock):
        """A 2000000 cent proposal against a suspended holder holding only 1200000 cents is
        refused for the suspension, and the rejected request writes nothing.

        Design: Difficulty/priority_pair_validation_conflict/premium_proposal_suspension_outranks_insufficient_fund_balance
        """
        chain = _suspended_producer_with_a_funded_committee(api)

        response = api.create_proposal(_water_point_proposal(chain, 2000000), CHAIR)

        validate_error(response, E.ERR_PREMIUM_USE_BLOCKED_BY_SUSPENSION, 409)
        fund = f.read_fund(api, chain["producer_id"])
        assert_fund_partition(fund, balance_cents=1200000)
        assert fund["pending_proposal_count"] == 0
        committee = f.read_committee(api, chain["committee_id"])
        assert committee["status"] == "ACTIVE"
        assert committee["open_proposal_count"] == 0

    def test_an_affordable_request_is_still_blocked_by_the_suspension(self, api, clock):
        """A 500000 cent proposal the fund could easily afford is refused for the same reason.

        Design: Difficulty/priority_pair_validation_conflict/premium_proposal_suspension_outranks_insufficient_fund_balance
        """
        chain = _suspended_producer_with_a_funded_committee(api)

        response = api.create_proposal(_water_point_proposal(chain, 500000), CHAIR)

        validate_error(response, E.ERR_PREMIUM_USE_BLOCKED_BY_SUSPENSION, 409)

    def test_after_reinstatement_the_same_request_hits_the_balance_ceiling(self, api, clock):
        """Reinstated, the identical 2000000 cent proposal is refused for the balance instead,
        showing the arithmetic rule was live all along and merely outranked.

        Design: Difficulty/priority_pair_validation_conflict/premium_proposal_suspension_outranks_insufficient_fund_balance
        """
        chain = _suspended_producer_with_a_funded_committee(api)
        validate_success(api.reinstate_holder(chain["producer_id"], OFFICER), 200)
        chain["fund_version"] = f.read_fund(api, chain["producer_id"])["version"]

        response = api.create_proposal(_water_point_proposal(chain, 2000000), CHAIR)

        validate_error(response, E.ERR_FUND_BALANCE_INSUFFICIENT, 402)


class TestRoleCheckOutranksExistence:
    """A caller who is not allowed to act never learns whether the target exists."""

    def test_a_wrong_role_on_a_missing_transaction_is_refused_for_the_role(self, api, clock):
        """A producer representative verifying a transaction that does not exist is refused as
        unauthorized, not told the transaction is missing.

        Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_transaction_returns_403
        """
        producer = f.build_certified_producer(api)

        response = api.verify_trade(
            NONEXISTENT_TRADE_ID, {"outcome": "VERIFIED"},
            make_producer_representative_headers(producer["holder_id"]),
        )

        error = validate_error(response, E.ERR_UNAUTHORIZED, 403)
        assert set(error.keys()) == {"error_id", "message"}, (
            f"the error payload should disclose nothing beyond error_id and message: {error}"
        )

    def test_a_missing_identity_header_outranks_the_role_check(self, api, clock):
        """With no acting identity at all the same call is refused as unauthenticated.

        Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_transaction_returns_403
        """
        f.build_certified_producer(api)

        response = api.verify_trade(
            NONEXISTENT_TRADE_ID, {"outcome": "VERIFIED"}, MISSING_USER_ID_HEADER
        )

        validate_error(response, E.ERR_UNAUTHENTICATED, 401)

    def test_the_permitted_role_does_get_the_not_found_answer(self, api, clock):
        """The auditor, who may verify, is told the transaction does not exist.

        Design: Difficulty/priority_pair_validation_conflict/unauthorized_role_outranks_missing_transaction_returns_403
        """
        f.build_certified_producer(api)

        response = api.verify_trade(NONEXISTENT_TRADE_ID, {"outcome": "VERIFIED"}, AUDITOR)

        validate_error(response, E.ERR_TRANSACTION_NOT_FOUND, 404)
