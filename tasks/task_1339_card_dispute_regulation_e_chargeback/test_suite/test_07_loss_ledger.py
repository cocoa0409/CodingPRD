"""Loss ledger: outstanding-loss conservation, manual entry bounds, and the
duplicate-dispute point-occupancy rule."""
from test_helpers import (
    ApiErrorId,
    create_dispute_payload,
    create_loss_recovery_payload,
    get_case,
    make_cardholder_headers,
    setup_account_with_dispute,
    setup_representment_accepted_case,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, get_success_data


class TestLossRecoveryConservation:
    def _resolved_case_with_auto_loss(self, api):
        """Case RESOLVED_MERCHANT_FAVOR via representment ACCEPT; the auto
        LOSS_RECOGNIZED entry is the 2500 filing fee."""
        return setup_representment_accepted_case(balance=50000, amount=12000)

    def test_loss_recovery_outstanding_conservation(self, api):
        """PRD §3.8: "its `outstanding_loss_cents` is the running balance: the
        sum of all `LOSS_RECOGNIZED` entry amounts minus the sum of all
        `RECOVERY_RECEIVED` entry amounts."
        PRD §3.8: "an amount exactly equal to the outstanding balance is
        permitted, but anything larger is rejected with
        `ERR_LOSS_EXCEEDS_OUTSTANDING`."

        Design: Difficulty/compensating_invariant/loss_recovery_outstanding_conservation
        """
        _account, _txn, case, _cb = self._resolved_case_with_auto_loss(api)
        fin = TEST_USERS["finance_officer_headers"]
        # +5000 manual loss -> outstanding 7500
        validate_success(api.create_loss_recovery(
            case["id"],
            create_loss_recovery_payload("LOSS_RECOGNIZED", 5000, memo="fee true-up"),
            fin,
        ), expected_status=201)
        # -7500 recovery equal to outstanding -> permitted, outstanding 0
        validate_success(api.create_loss_recovery(
            case["id"],
            create_loss_recovery_payload("RECOVERY_RECEIVED", 7500,
                                         memo="merchant repayment"),
            fin,
        ), expected_status=201)
        resolved = get_case(case["id"])
        assert resolved["outstanding_loss_cents"] == 0, (
            f"2500 auto + 5000 manual - 7500 recovery must net to 0, "
            f"got {resolved['outstanding_loss_cents']}"
        )

    def test_recovery_one_cent_beyond_outstanding_rejected(self, api):
        """PRD §3.8: "an amount exactly equal to the outstanding balance is
        permitted, but anything larger is rejected with
        `ERR_LOSS_EXCEEDS_OUTSTANDING`."

        Design: Difficulty/compensating_invariant/loss_recovery_outstanding_conservation
        """
        _account, _txn, case, _cb = self._resolved_case_with_auto_loss(api)
        fin = TEST_USERS["finance_officer_headers"]
        validate_success(api.create_loss_recovery(
            case["id"], create_loss_recovery_payload("LOSS_RECOGNIZED", 5000), fin,
        ), expected_status=201)
        validate_success(api.create_loss_recovery(
            case["id"], create_loss_recovery_payload("RECOVERY_RECEIVED", 7500), fin,
        ), expected_status=201)
        # Outstanding is now 0; even 1 cent more is over the bound.
        resp = api.create_loss_recovery(
            case["id"], create_loss_recovery_payload("RECOVERY_RECEIVED", 1), fin,
        )
        validate_error(resp, ApiErrorId.ERR_LOSS_EXCEEDS_OUTSTANDING)


class TestDuplicateDisputePointOccupancy:
    def test_duplicate_dispute_point_occupancy(self, api):
        """PRD §3.2: "A transaction may carry at most one open dispute: if any
        earlier case for it still sits in `RECEIVED`, `CLASSIFIED`,
        `CHARGEBACK_FILED`, `REPRESENTMENT_REVIEW`, or `REVERSAL_PENDING`,
        intake is refused with `ERR_DUPLICATE_ACTIVE_DISPUTE`".

        Design: Difficulty/resource_temporal_overlap/duplicate_dispute_point_occupancy
        """
        account, txn, _case = setup_account_with_dispute(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        resp = api.create_dispute(
            create_dispute_payload(
                txn["id"], 4000,
                error_type="DUPLICATE_CHARGE", claimed_report_delay_days=5,
            ),
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE)

    def test_duplicate_dispute_occupancy_holds_for_partial_claim(self, api):
        """PRD §3.2: "A transaction may carry at most one open dispute: if any
        earlier case for it still sits in `RECEIVED`, `CLASSIFIED`,
        `CHARGEBACK_FILED`, `REPRESENTMENT_REVIEW`, or `REVERSAL_PENDING`,
        intake is refused with `ERR_DUPLICATE_ACTIVE_DISPUTE`".

        Design: Difficulty/resource_temporal_overlap/duplicate_dispute_point_occupancy
        """
        account, txn, _case = setup_account_with_dispute(
            balance=50000, amount=8000, claim=8000, claimed_delay=5,
        )
        # A smaller, otherwise-valid claim is still refused: occupancy is total.
        resp = api.create_dispute(
            create_dispute_payload(
                txn["id"], 1, error_type="INCORRECT_AMOUNT",
                claimed_report_delay_days=2,
            ),
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_DISPUTE)
        disputes = get_success_data(api.list_disputes(
            make_cardholder_headers(account["id"]),
            params={"card_transaction_id": txn["id"]},
        ))
        assert len(disputes) == 1, (
            "the refused second intake must not create a case"
        )
