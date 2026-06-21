"""Corner section: errors — the buyer-wire-not-locked path on terminate,
the stale-title-search-version OCC path, and the insufficient-escrow-funds
fiscal check at close.
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_actors,
    setup_active_agreement,
    setup_cleared_to_close,
    create_deposit,
    create_title_search,
    complete_title_search,
    resolve_title_search,
    create_title_insurance_policy_payload,
    terminate_purchase_agreement_payload,
    queue_disbursement,
    setup_locked_wire,
    api_client,
)


class TestBuyerWireNotLockedOnTerminate:
    def test_terminate_without_locked_buyer_wire_returns_409_err_buyer_wire_not_locked(self, api):
        """PRD §3.6: "If no ``BUYER`` wire instruction for this agreement is currently in ``LOCKED``, the termination is rejected with ``ERR_BUYER_WIRE_NOT_LOCKED`` (HTTP 409). The buyer's verified destination must exist before the system will route any refund — this is the same wire-fraud principle that gates the close, applied to the refund path."

        Design: Corner/errors/error_buyer_wire_not_locked_on_terminate
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(
            actors=actors, earnest_money_required_cents=1_000_000
        )
        # A PENDING EMD exists (would need refund routing) but no BUYER wire.
        create_deposit(actors, base["escrow"]["id"], amount_cents=500_000)
        res = api.terminate_purchase_agreement(
            base["agreement"]["id"],
            terminate_purchase_agreement_payload(
                terminated_reason="no BUYER wire LOCKED yet"
            ),
            actors["eo"],
        )
        validate_error(res, "ERR_BUYER_WIRE_NOT_LOCKED", expected_status=409)


class TestStaleTitleSearchVersionOnPolicyIssue:
    def test_policy_issue_with_stale_expected_title_search_version_returns_412(self, api):
        """PRD §2.7: "Issuing a ``TitleInsurancePolicy`` requires the request body to carry ``expected_title_search_version``, an integer the client last observed on the target ``TitleSearch``. If that value does not equal the title search's current ``version``, the request is rejected with ``ERR_STALE_TITLE_SEARCH_VERSION`` (HTTP 412)."

        Design: Corner/errors/error_stale_title_search_version_on_policy_issue
        """
        actors = setup_actors(initial_iso8601="2026-06-01T00:00:00Z")
        base = setup_active_agreement(actors=actors)
        search = create_title_search(actors, base["agreement"]["id"])
        complete_title_search(actors, search["id"], defects=[])
        resolved = resolve_title_search(actors, search["id"])
        current_version = resolved["version"]
        # Pass current_version - 1 as the expected value (a known-stale token).
        res = api.create_title_insurance_policy(
            create_title_insurance_policy_payload(
                title_search_id=search["id"],
                expected_title_search_version=current_version - 1,
            ),
            actors["ta"],
        )
        validate_error(res, "ERR_STALE_TITLE_SEARCH_VERSION", expected_status=412)


class TestInsufficientEscrowFundsOnClose:
    def test_close_with_insufficient_escrow_balance_returns_409_err_insufficient_escrow_funds(self, api):
        """PRD §3.5: "Closing the agreement advances it from ``CLEARED_TO_CLOSE`` to ``CLOSED`` and runs the disbursement waterfall. The fiscal-sufficiency check fires first: the escrow account's ``balance_cents`` must be at least the sum of ``amount_cents`` across every ``QUEUED`` disbursement on that escrow; if not, the close is rejected with ``ERR_INSUFFICIENT_ESCROW_FUNDS`` and nothing changes."

        Design: Corner/errors/error_insufficient_escrow_funds
        """
        ready = setup_cleared_to_close(
            purchase_price_cents=50_000_000,
            earnest_money_required_cents=1_000_000,
        )
        # Queue a disbursement far in excess of escrow balance (1_000_000).
        queue_disbursement(
            ready["actors"], ready["escrow_id"], ready["seller_wire_id"],
            purpose="SELLER_PROCEEDS", amount_cents=100_000_000,
        )
        res = api.close_purchase_agreement(
            ready["agreement_id"], ready["actors"]["eo"]
        )
        validate_error(res, "ERR_INSUFFICIENT_ESCROW_FUNDS", expected_status=409)
