"""Club treasury invariant and validation priority on reimbursement approval."""
from test_helpers import (
    create_club,
    create_cleared_volunteer,
    get_club_balance,
    make_volunteer_headers,
    post_dues,
    post_reimbursement,
    validate_error,
    validate_success,
)


class TestTreasuryNetInvariant:
    def test_dues_minus_approved_reimbursement(self, api):
        """PRD §3.1: "At all times, `treasury_balance_cents` equals the sum of
        POSTED dues payments minus the sum of APPROVED reimbursements for that
        club." PRD §3.1: "An expense reimbursement is POSTED on entry but does
        not touch the balance until a volunteer approves it; approval moves the
        transaction from POSTED to APPROVED and debits the treasury, and an
        approval that would drive `treasury_balance_cents` negative is rejected
        with `ERR_INSUFFICIENT_TREASURY` (HTTP 422)."

        1000-cent dues posted, 400-cent reimbursement approved -> 600.

        Design: Difficulty/compensating_invariant/treasury_net_invariant
        """
        club = create_club()
        vol = create_cleared_volunteer(club["id"])
        post_dues(club["id"], vol["id"], 1000)
        assert get_club_balance(club["id"], vol["id"]) == 1000

        reimbursement = post_reimbursement(club["id"], vol["id"], 400)
        assert get_club_balance(club["id"], vol["id"]) == 1000, (
            "a POSTED reimbursement must not touch the balance before approval"
        )
        approved = validate_success(
            api.approve_treasury_transaction(
                reimbursement["id"], make_volunteer_headers(vol["id"])
            ),
            200,
        )
        assert approved["txn_status"] == "APPROVED"
        assert get_club_balance(club["id"], vol["id"]) == 600, (
            "balance must equal 1000 dues - 400 approved reimbursement"
        )

    def test_void_dues_payment_reverses_credit(self, api):
        """PRD §3.1: "A transaction still in POSTED status may be voided by a
        volunteer, moving it to VOIDED; voiding a dues payment reverses the
        credit it applied, debiting the treasury by the same amount."

        Design: Difficulty/compensating_invariant/treasury_net_invariant
        """
        club = create_club()
        vol = create_cleared_volunteer(club["id"])
        dues = post_dues(club["id"], vol["id"], 1000)
        assert get_club_balance(club["id"], vol["id"]) == 1000

        voided = validate_success(
            api.void_treasury_transaction(dues["id"], make_volunteer_headers(vol["id"])), 200
        )
        assert voided["txn_status"] == "VOIDED"
        assert get_club_balance(club["id"], vol["id"]) == 0, (
            "voiding the dues payment must reverse its credit exactly"
        )


class TestTreasuryApprovalPriority:
    def test_reapprove_already_approved_reports_state_not_fiscal(self, api):
        """PRD §2.9: "Every request passes through a fixed validation pipeline,
        and the first failing check determines the error returned." PRD §2.9:
        "the target resource is in a valid from-state for
        the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409).
        Applies to all action endpoints, so a transition attempted from the
        wrong state always fails here before any business check runs."

        The second approval of an already-APPROVED 800-cent reimbursement would
        also overdraw the 200-cent balance; the from-state violation is
        reported, not the solvency violation.

        Design: Difficulty/priority_pair_validation_conflict/temporal_before_fiscal_on_treasury_approve
        """
        club = create_club()
        vol = create_cleared_volunteer(club["id"])
        post_dues(club["id"], vol["id"], 1000)
        reimbursement = post_reimbursement(club["id"], vol["id"], 800)
        vol_headers = make_volunteer_headers(vol["id"])
        validate_success(api.approve_treasury_transaction(reimbursement["id"], vol_headers), 200)
        assert get_club_balance(club["id"], vol["id"]) == 200

        res = api.approve_treasury_transaction(reimbursement["id"], vol_headers)
        validate_error(res, "ERR_INVALID_STATE")
        assert get_club_balance(club["id"], vol["id"]) == 200, (
            "the rejected re-approval must not debit the treasury again"
        )

    def test_approve_voided_reimbursement_reports_state_not_fiscal(self, api):
        """PRD §3.1: "A transaction still in POSTED status may be voided by a
        volunteer, moving it to VOIDED". PRD §2.9: "the
        target resource is in a valid from-state for the requested transition;
        otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to all action
        endpoints, so a transition attempted from the wrong state always fails
        here before any business check runs."

        Approving a VOIDED 800-cent reimbursement against a 100-cent balance
        violates both the from-state rule and solvency; the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/temporal_before_fiscal_on_treasury_approve
        """
        club = create_club()
        vol = create_cleared_volunteer(club["id"])
        post_dues(club["id"], vol["id"], 100)
        reimbursement = post_reimbursement(club["id"], vol["id"], 800)
        vol_headers = make_volunteer_headers(vol["id"])
        validate_success(api.void_treasury_transaction(reimbursement["id"], vol_headers), 200)

        res = api.approve_treasury_transaction(reimbursement["id"], vol_headers)
        validate_error(res, "ERR_INVALID_STATE")
