"""Optimistic concurrency on reclassification, dispute listing/pagination,
and immediate read-after-write consistency."""
from test_helpers import (
    CLOCK,
    ApiErrorId,
    classify_case,
    grant_credit,
    make_cardholder_headers,
    make_investigator_headers,
    reclassify_payload,
    set_clock,
    setup_account_with_dispute,
    setup_classified_case_with_credit,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, get_account


class TestReclassifyOptimisticConcurrency:
    def _classified_fraud_case(self, api):
        """Case at version 1 (intake) then classified (version 2)."""
        account, txn, case = setup_account_with_dispute(
            balance=50000, amount=15000, txn_type="POS_PIN",
            error_type="UNAUTHORIZED", claim=15000, claimed_delay=1,
            classify=False,
        )
        v1 = case["version"]
        classified = classify_case(case["id"], is_fraud=True, verified_delay=1)
        return case["id"], v1, classified["version"]

    def test_reclassify_stale_version_rejected(self, api):
        """PRD §2.7: "A reclassification request must carry
        `expected_dispute_version`, holding the `version` of the Dispute Case
        the client last observed. If that value does not match the case's
        current `version`, the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/reclassify_stale_version_rejected
        """
        case_id, v1, _v2 = self._classified_fraud_case(api)
        resp = api.reclassify_dispute(
            case_id,
            reclassify_payload(v1, is_fraud_claim=False,
                               verified_report_delay_days=1),
            TEST_USERS["investigator_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_reclassify_current_version_succeeds_and_bumps(self, api):
        """PRD §2.7: "A reclassification request must carry
        `expected_dispute_version`, holding the `version` of the Dispute Case
        the client last observed."
        PRD §3.3: "A successful reclassification recomputes the fraud flag, the
        verified delay, the investigation window and its deadline, and the
        provisional holdback, and it increments the case's `version` by one."

        Design: Corner/cross_cutting_layers/reclassify_stale_version_rejected
        """
        case_id, _v1, v2 = self._classified_fraud_case(api)
        resp = api.reclassify_dispute(
            case_id,
            reclassify_payload(v2, is_fraud_claim=False,
                               verified_report_delay_days=1),
            TEST_USERS["investigator_headers"],
        )
        data = validate_success(resp)
        assert data["version"] == v2 + 1, (
            f"reclassification must increment the version by one, "
            f"got {data['version']} (was {v2})"
        )
        assert data["is_fraud_claim"] is False


class TestDisputeListing:
    def test_list_disputes_filtered_by_status_paginated(self, api):
        """PRD §3.8: "the case collection can be listed with `card_account_id`,
        `card_transaction_id`, and `status` filters."
        PRD §2.3: "Paginated list responses include the following fields in the
        `meta` object of the response envelope: `limit`, `offset`,
        `total_count`, and `has_more`."

        Design: Corner/endpoints/list_disputes_filtered_by_status_paginated
        """
        set_clock(CLOCK["ACCOUNT_OPEN"])
        from test_helpers import (
            create_account,
            create_transaction,
            file_dispute,
        )
        account = create_account(balance=50000, name="List")
        txn1 = create_transaction(account["id"], amount=4000)
        txn2 = create_transaction(account["id"], amount=4000)
        case1 = file_dispute(txn1["id"], account["id"], 4000, claimed_delay=5)
        file_dispute(txn2["id"], account["id"], 4000, claimed_delay=5)
        classify_case(case1["id"], is_fraud=False, verified_delay=5)
        data, meta = validate_paginated(api.list_disputes(
            TEST_USERS["investigator_headers"],
            params={"card_account_id": account["id"], "status": "CLASSIFIED"},
        ))
        assert meta["total_count"] == 1, (
            f"exactly one CLASSIFIED case must match, got {meta['total_count']}"
        )
        assert meta["has_more"] is False
        assert len(data) == 1
        assert data[0]["id"] == case1["id"]


class TestImmediateConsistency:
    def test_immediate_read_after_write_consistency(self, api):
        """PRD §3.1: "the response exposes the ledger `balance_cents` and the
        derived `provisional_outstanding_cents`, which is the sum of
        `amount_cents` over that account's Provisional Credits currently in
        `GRANTED` or `REINSTATED`."
        PRD §3.4: "The grant credits the account's `balance_cents` by the
        granted amount, raises `provisional_outstanding_cents` by the same
        amount".

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        account, _txn, case, credit = setup_classified_case_with_credit(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        # The very next reads reflect the mutation with no lag.
        after = get_account(account["id"])
        assert after["balance_cents"] == 58000
        assert after["provisional_outstanding_cents"] == 8000
        from test_helpers import get_success_data
        credits = get_success_data(api.list_case_provisional_credits(
            case["id"], TEST_USERS["intake_agent_headers"],
        ))
        assert credits[0]["status"] == "GRANTED"
