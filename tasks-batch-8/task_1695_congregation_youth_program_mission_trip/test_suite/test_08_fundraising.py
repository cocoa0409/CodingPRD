"""Fundraising: channel fees, gross-vs-net dual basis, goal boundary, the
zero-credit gate, account-state gating of donations, and refund conservation."""
from test_helpers import (
    ApiErrorId,
    add_donation,
    create_approved_registration,
    create_participant,
    create_registration,
    get_account,
    get_account_for_registration,
    get_registration,
    make_director_headers,
    make_guardian_headers,
    make_treasurer_headers,
    setup_program_with_open_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()
TREASURER = make_treasurer_headers()


def _account_with_donations(api, goal_cents, donations):
    """Approved registration + account funded with [(amount, channel), ...]."""
    program, trip = setup_program_with_open_trip()
    _, registration, _ = create_approved_registration(
        trip["id"], "guardian-1",
        registration_overrides={"fundraising_goal_cents": goal_cents})
    account = get_account_for_registration(registration["id"])
    created = [add_donation(account["id"], amount, channel)
               for amount, channel in donations]
    return registration, account, created


class TestGrossProgressVsNetCredit:
    def test_channel_fees_and_gross_net_totals(self, api):
        """PRD §3.4: "The channel determines `fee_cents` at creation: cash
        carries no fee; a check carries a flat 25 cents; an online card gift
        carries its 2.9% percentage component rounded half up to the nearest
        cent first, then plus a flat 30 cents."
        PRD §3.4: "`raised_gross_cents` (total of `amount_cents`),
        `fee_total_cents` (total of `fee_cents`), `raised_net_cents` (gross
        minus fees), and `available_credit_cents` (net minus the
        `credit_applied_cents` already moved)".

        Design: Difficulty/dual_variant_calc/fundraising_gross_progress_vs_net_credit
        """
        _, account, donations = _account_with_donations(
            api, 30000, [(10000, "CARD_ONLINE"), (5000, "CASH"),
                         (20000, "CHECK")])

        card, cash, check = donations
        assert card["fee_cents"] == 320, (
            "round_half_up(0.029*10000)=290 rounded BEFORE the +30 flat")
        assert cash["fee_cents"] == 0
        assert check["fee_cents"] == 25

        data = get_account(account["id"])
        assert data["raised_gross_cents"] == 35000
        assert data["fee_total_cents"] == 345
        assert data["raised_net_cents"] == 34655

    def test_goal_progress_gross_but_creditable_net(self, api):
        """PRD §3.4: "This dual basis is deliberate: donor-facing progress and
        the scholarship fundraising bonus use the gross figure, while only
        fee-free net value may move onto the trip balance, so identical donation
        data yields less credit than progress." and "`goal_met` is a gross-basis
        comparison — true when `goal_cents` is positive and `raised_gross_cents`
        is at least `goal_cents`, with exact equality counting."

        Design: Difficulty/dual_variant_calc/fundraising_gross_progress_vs_net_credit
        """
        _, account, _ = _account_with_donations(
            api, 30000, [(10000, "CARD_ONLINE"), (5000, "CASH"),
                         (20000, "CHECK")])
        data = get_account(account["id"])
        assert data["goal_met"] is True, "35000 gross >= 30000 goal"
        assert data["available_credit_cents"] == 34655, (
            "the creditable balance is the NET basis — 345 of fees diverge")
        assert data["raised_gross_cents"] - data["available_credit_cents"] == 345


class TestGoalMetBoundary:
    def test_goal_met_equality_boundary(self, api):
        """PRD §3.4: "`goal_met` is a gross-basis comparison — true when
        `goal_cents` is positive and `raised_gross_cents` is at least
        `goal_cents`, with exact equality counting."

        Design: Corner/calculations/goal_met_equality_boundary
        """
        _, account, _ = _account_with_donations(
            api, 20000, [(10000, "CASH"), (9999, "CASH")])
        assert get_account(account["id"])["goal_met"] is False, (
            "gross 19999 < goal 20000")

        add_donation(account["id"], 1, "CASH")
        data = get_account(account["id"])
        assert data["raised_gross_cents"] == 20000
        assert data["goal_met"] is True, "equality satisfies the goal"


class TestApplyCreditZeroAvailable:
    def test_apply_credit_zero_available_rejected(self, api):
        """PRD §3.4: "Applying credit, a `Treasurer` action, requires the account
        `OPEN` (`ERR_ACCOUNT_CLOSED`), the registration in `APPROVED` or
        `CONFIRMED` (`ERR_REGISTRATION_STATE_FORBIDS_ACTION` ...), and
        `available_credit_cents` greater than zero (`ERR_NO_CREDIT_AVAILABLE`,
        HTTP 422)."

        Design: Corner/validations/apply_credit_zero_available_rejected
        """
        program, trip = setup_program_with_open_trip()
        _, registration, _ = create_approved_registration(trip["id"],
                                                          "guardian-1")
        account = get_account_for_registration(registration["id"])

        resp = api.apply_credit(account["id"], TREASURER)
        validate_error(resp, ApiErrorId.ERR_NO_CREDIT_AVAILABLE, 422)
        assert get_registration(registration["id"])[
            "fundraising_credit_applied_cents"] == 0


class TestDonationRequiresOpenAccount:
    def test_withdrawal_closes_the_fundraising_account(self, api):
        """PRD §3.7: "From `DRAFT`, `SUBMITTED`, or `WAITLISTED`, withdrawal
        simply closes the `OPEN` fundraising account and voids every non-`VOIDED`
        consent form."

        Design: Difficulty/cross_entity_state_dependency/donation_requires_fundraising_account_open
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1",
                                           fundraising_goal_cents=5000)
        account = get_account_for_registration(registration["id"])
        assert account["status"] == "OPEN"

        withdrawn = api.withdraw_registration(
            registration["id"], make_guardian_headers("guardian-1"),
            payload={"reason": "changed plans"})
        validate_success(withdrawn, 200)
        assert get_account(account["id"])["status"] == "CLOSED"

    def test_donation_against_closed_account_rejected(self, api):
        """PRD §3.4: "The fundraising side is deliberately independent of
        approval: donations may be recorded while the registration is still a
        draft, because the only state gate on the donation create is that the
        account be `OPEN` (`ERR_ACCOUNT_CLOSED` otherwise)."

        Design: Difficulty/cross_entity_state_dependency/donation_requires_fundraising_account_open
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1")
        account = get_account_for_registration(registration["id"])
        api.withdraw_registration(registration["id"],
                                  make_guardian_headers("guardian-1"))

        resp = api.create_donation(
            account["id"],
            {"donor_name": "D1", "amount_cents": 1000, "channel": "CASH"},
            TREASURER)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_CLOSED, 409)


class TestDonationRefundConservation:
    def test_donation_receive_then_refund_restores_account_sums(self, api):
        """PRD §3.4: "a successful refund removes it from all four account sums"
        — "refunded donations drop out of every sum".

        Design: Difficulty/compensating_invariant/donation_receive_refund_net_raised_conservation
        """
        _, account, _ = _account_with_donations(api, 0, [])
        donation = add_donation(account["id"], 10000, "CARD_ONLINE")

        mid = get_account(account["id"])
        assert mid["raised_gross_cents"] == 10000
        assert mid["fee_total_cents"] == 320
        assert mid["raised_net_cents"] == 9680
        assert mid["available_credit_cents"] == 9680

        refunded = api.refund_donation(donation["id"], TREASURER,
                                       payload={"reason": "donor bounced"})
        validate_success(refunded, 200)
        zeroed = get_account(account["id"])
        assert zeroed["raised_gross_cents"] == 0
        assert zeroed["fee_total_cents"] == 0
        assert zeroed["raised_net_cents"] == 0
        assert zeroed["available_credit_cents"] == 0, (
            "the receive+refund pair leaves every account sum at its pre-pair value")

    def test_refund_leaves_no_residue_for_later_donations(self, api):
        """PRD §3.4: "The account maintains four rollups over its donations in
        `RECEIVED` or `APPLIED` — refunded donations drop out of every sum".

        Design: Difficulty/compensating_invariant/donation_receive_refund_net_raised_conservation
        """
        _, account, _ = _account_with_donations(api, 0, [])
        donation = add_donation(account["id"], 10000, "CARD_ONLINE")
        api.refund_donation(donation["id"], TREASURER)

        add_donation(account["id"], 5000, "CASH")
        data = get_account(account["id"])
        assert data["raised_gross_cents"] == 5000
        assert data["available_credit_cents"] == 5000, (
            "no fee residue from the refunded pair contaminates later donations")
