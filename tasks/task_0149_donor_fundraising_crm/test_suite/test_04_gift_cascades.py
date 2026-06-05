"""Cascading ledger effects of gift acknowledgement and refund: pledge
fulfilment and reversion, installment allocation, the delinquency cycle, the
match-claim fork, and the cross-entity refund-denies-match cascade.

Difficulty queue: transitive_cascade, non_linear_state_machine,
resource_temporal_overlap (pledge due window). Corner queue: cross-entity refund.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    api_client, TEST_USERS, ApiErrorId,
    create_open_campaign, create_donor, create_employer,
    create_acknowledged_gift, record_gift, acknowledge_gift,
    setup_open_campaign_with_donor, create_pledge, get_installments_sorted,
    setup_delinquent_pledge, open_match_claim, approve_match_claim,
    pay_match_claim, set_clock, rows_of,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


# ---------------------------------------------------------------------------
# Difficulty Rule 4 — transitive cascade depth-three
# ---------------------------------------------------------------------------
class TestAcknowledgeCascade:
    def test_acknowledge_drives_pledge_to_fulfilled_and_waives(self, api):
        """PRD §3.5: "If that allocation drives the pledge's `balance_cents` to zero,
        the pledge advances to `FULFILLED` and any installments still `DUE` are marked
        `WAIVED`." PRD §3.5: "moving that installment from `DUE` to `PAID` and stamping
        its `paid_by_gift_id` with the allocating gift's id."

        Design: Difficulty/transitive_cascade/acknowledge_cascade_depth_three_gift_pledge_installment
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        gift = record_gift(camp["id"], donor["id"], amount_cents=10000, pledge_id=pledge["id"])
        acknowledge_gift(gift["id"])

        p = validate_success(api.get_pledge(pledge["id"], GA))
        assert p["balance_cents"] == 0, "10000 against a 10000 pledge zeroes the balance"
        assert p["status"] == "FULFILLED", "balance 0 drives ACTIVE -> FULFILLED"

        insts = get_installments_sorted(pledge["id"])
        earliest = insts[0]
        assert earliest["status"] == "PAID", "earliest-due installment allocated to the gift"
        assert earliest["paid_by_gift_id"] == gift["id"], "paid_by_gift_id stamped with allocating gift"
        assert insts[1]["status"] == "WAIVED", "remaining DUE installment waived on FULFILLED"

    def test_acknowledge_allocates_earliest_due_installment(self, api):
        """PRD §3.5: "then allocates the gift to the single earliest due installment
        of that pledge — earliest by `due_on` ascending, breaking ties by
        `sequence_no` ascending — moving that installment from `DUE` to `PAID`".

        A partial payment of one installment leaves the pledge ACTIVE with the second
        still DUE.

        Design: Difficulty/transitive_cascade/acknowledge_cascade_depth_three_gift_pledge_installment
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        gift = record_gift(camp["id"], donor["id"], amount_cents=5000, pledge_id=pledge["id"])
        acknowledge_gift(gift["id"])

        p = validate_success(api.get_pledge(pledge["id"], GA))
        assert p["paid_cents"] == 5000
        assert p["balance_cents"] == 5000
        assert p["status"] == "ACTIVE", "a partial payment leaves the pledge ACTIVE"
        insts = get_installments_sorted(pledge["id"])
        assert insts[0]["status"] == "PAID"
        assert insts[1]["status"] == "DUE", "the later installment remains DUE"

    def test_refund_reverts_fulfilled_pledge_and_installment(self, api):
        """PRD §3.9: "if a `pledge_id` is present it recomputes the pledge's
        `paid_cents` and `balance_cents`, returns the installment whose
        `paid_by_gift_id` equals this gift to `DUE` and clears that `paid_by_gift_id`,
        and reverts a `FULFILLED` pledge to `ACTIVE` when the reversal lifts its
        balance above zero".

        Design: Difficulty/transitive_cascade/refund_cascade_depth_three_gift_pledge_installment_revert
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        gift = record_gift(camp["id"], donor["id"], amount_cents=10000, pledge_id=pledge["id"])
        acked = acknowledge_gift(gift["id"])  # pledge -> FULFILLED

        refunded = validate_success(
            api.refund_gift(gift["id"], {"expected_gift_version": acked["version"]}, GA)
        )
        assert refunded["status"] == "REFUNDED"

        p = validate_success(api.get_pledge(pledge["id"], GA))
        assert p["balance_cents"] == 10000, "refund lifts balance back to the full total"
        assert p["status"] == "ACTIVE", "FULFILLED reverts to ACTIVE when balance rises above 0"
        insts = get_installments_sorted(pledge["id"])
        prev_paid = [i for i in insts if i["paid_by_gift_id"] == gift["id"]]
        assert prev_paid == [], "no installment should still point at the refunded gift"
        # the installment that had been PAID by this gift is back to DUE
        assert any(i["status"] == "DUE" for i in insts), "the previously PAID installment returns to DUE"

    def test_refund_clears_paid_by_gift_id(self, api):
        """PRD §3.5: "It returns `PAID → DUE` when the allocating gift is refunded —
        matched by the installment whose `paid_by_gift_id` equals the refunded gift's
        id — clearing `paid_by_gift_id`."

        Design: Difficulty/transitive_cascade/refund_cascade_depth_three_gift_pledge_installment_revert
        """
        camp, donor = setup_open_campaign_with_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY")
        gift = record_gift(camp["id"], donor["id"], amount_cents=10000, pledge_id=pledge["id"])
        acked = acknowledge_gift(gift["id"])
        validate_success(api.refund_gift(gift["id"], {"expected_gift_version": acked["version"]}, GA))

        insts = get_installments_sorted(pledge["id"])
        reverted = [i for i in insts if i["status"] == "DUE"]
        assert reverted, "at least one installment is DUE again after refund"
        for i in reverted:
            assert i["paid_by_gift_id"] is None, "paid_by_gift_id cleared on revert to DUE"


# ---------------------------------------------------------------------------
# Difficulty Rule 3 — non-linear pledge cycle ACTIVE -> DELINQUENT -> (still DELINQUENT)
# ---------------------------------------------------------------------------
class TestPledgeDelinquencyCycle:
    def test_active_to_delinquent_then_partial_payment_stays_delinquent(self, api):
        """PRD §3.5: "if the pledge is `ACTIVE` and at least one installment is overdue
        (its `installments_due_count` is 1 or more), the pledge moves `ACTIVE →
        DELINQUENT`." PRD §3.5: "when a gift acknowledgement allocates payment such
        that, afterward, no installment with a `due_on` at or before the current clock
        remains `DUE`, a `DELINQUENT` pledge moves back to `ACTIVE`."

        With two overdue installments, paying one leaves an overdue installment, so the
        pledge stays DELINQUENT.

        Design: Difficulty/non_linear_state_machine/pledge_active_delinquent_active_cycle
        """
        camp, donor, pledge = setup_delinquent_pledge(
            total_amount_cents=10000, installment_count=2,
            start_clock="2026-01-01T00:00:00Z", overdue_clock="2026-02-15T00:00:00Z",
        )
        assert pledge["status"] == "DELINQUENT", "two overdue installments drive DELINQUENT"

        gift = record_gift(camp["id"], donor["id"], amount_cents=5000, pledge_id=pledge["id"])
        acknowledge_gift(gift["id"])
        p = validate_success(api.get_pledge(pledge["id"], GA))
        assert p["status"] == "DELINQUENT", "one overdue installment remains -> still DELINQUENT"
        assert p["installments_due_count"] == 1, "one installment still overdue and DUE"

    def test_delinquent_returns_to_active_when_all_overdue_cleared(self, api):
        """PRD §3.5: "when a gift acknowledgement allocates payment such that, afterward,
        no installment with a `due_on` at or before the current clock remains `DUE`, a
        `DELINQUENT` pledge moves back to `ACTIVE`."

        Only installment 1 is overdue (clock between the two due dates); paying it clears
        all overdue installments and returns the pledge to ACTIVE.

        Design: Difficulty/non_linear_state_machine/pledge_active_delinquent_active_cycle
        """
        # Clock at 2026-01-15: installment 1 (due 2026-01-01) overdue, installment 2
        # (due 2026-02-01) not yet due.
        camp, donor, pledge = setup_delinquent_pledge(
            total_amount_cents=10000, installment_count=2,
            start_clock="2026-01-01T00:00:00Z", overdue_clock="2026-01-15T00:00:00Z",
        )
        assert pledge["status"] == "DELINQUENT"
        assert pledge["installments_due_count"] == 1, "only installment 1 is overdue at 2026-01-15"

        gift = record_gift(camp["id"], donor["id"], amount_cents=5000, pledge_id=pledge["id"])
        acknowledge_gift(gift["id"])
        p = validate_success(api.get_pledge(pledge["id"], GA))
        assert p["status"] == "ACTIVE", "no overdue installment remains -> DELINQUENT returns to ACTIVE"
        assert p["installments_due_count"] == 0


# ---------------------------------------------------------------------------
# Difficulty Rule 3 — match-claim branching fork (APPROVED -> DENIED leaves totals)
# ---------------------------------------------------------------------------
class TestMatchClaimFork:
    def test_approved_then_denied_leaves_with_match_untouched(self, api):
        """PRD §3.6: "An approved claim may then be paid (`APPROVED → PAID`, ...) or
        denied (`APPROVED → DENIED`). Denial carries no ledger side effect." PRD §3.6:
        "The claim's `matched_amount_cents` is zero until the claim is paid."

        Design: Difficulty/non_linear_state_machine/matchclaim_branching_fork_paid_vs_denied
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0)
        donor = create_donor(employer_id=emp["id"])
        _, g = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        claim = open_match_claim(g)
        approve_match_claim(claim["id"])

        denied = validate_success(api.deny_match_claim(claim["id"], GA))
        assert denied["status"] == "DENIED"
        assert denied["matched_amount_cents"] == 0, "denial pins no matched amount"

        camp_data = validate_success(api.get_campaign(camp["id"], CM))
        assert camp_data["raised_with_match_cents"] == 100000, \
            "DENIED branch leaves raised_with_match at the hard-credit value only"

    def test_approved_then_paid_adds_to_with_match(self, api):
        """PRD §3.6: "Paying is the divergent branch: it pins the claim's
        `matched_amount_cents` and adds it to the gift's campaign's
        `raised_with_match_cents`".

        Design: Difficulty/non_linear_state_machine/matchclaim_branching_fork_paid_vs_denied
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0)
        donor = create_donor(employer_id=emp["id"])
        _, g = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        claim = open_match_claim(g)
        approve_match_claim(claim["id"])
        paid = validate_success(api.pay_match_claim(claim["id"], GA))
        assert paid["status"] == "PAID"
        assert paid["matched_amount_cents"] == 100000

        camp_data = validate_success(api.get_campaign(camp["id"], CM))
        assert camp_data["raised_with_match_cents"] == 200000, \
            "PAID branch adds the 100000 match on top of 100000 hard credit"


# ---------------------------------------------------------------------------
# Difficulty Rule 8 — resource temporal overlap: pledge due-window inclusive boundary
# ---------------------------------------------------------------------------
class TestPledgeDueWindowBoundary:
    def test_due_on_equal_to_clock_counts_as_overdue(self, api):
        """PRD §3.5: "Its `installments_due_count` is the number of this pledge's
        installments whose `due_on` is at or before the current clock and whose
        `status` is still `DUE`".

        Clock exactly equal to installment 1's due_on counts it as overdue (inclusive),
        driving DELINQUENT.

        Design: Difficulty/resource_temporal_overlap/pledge_due_window_overdue_inclusive_boundary
        """
        set_clock("2026-01-01T00:00:00Z")
        camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
        donor = create_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        # Clock left exactly at the due instant (installment 1 due_on == created_at == clock).
        p = validate_success(api.evaluate_pledge_delinquency(pledge["id"], GA))
        assert p["status"] == "DELINQUENT", "due_on == clock is inclusive overdue"
        assert p["installments_due_count"] == 1

    def test_due_on_after_clock_is_not_overdue(self, api):
        """PRD §3.5: "Its `installments_due_count` is the number of this pledge's
        installments whose `due_on` is at or before the current clock and whose `status`
        is still `DUE`". PRD §3.5: "if the pledge is `ACTIVE` and at least one installment
        is overdue ... the pledge moves `ACTIVE → DELINQUENT`."

        When the clock is strictly before every installment's due_on, no installment is
        overdue and the pledge stays ACTIVE (the open side of the inclusive boundary).

        Design: Difficulty/resource_temporal_overlap/pledge_due_window_overdue_inclusive_boundary
        """
        # Create the pledge with due_on == 2026-02-01, then rewind the clock to before it.
        set_clock("2026-02-01T00:00:00Z")
        camp = create_open_campaign(starts_on="2025-12-01T00:00:00Z", ends_on="2026-12-31T00:00:00Z")
        donor = create_donor()
        pledge = create_pledge(camp["id"], donor["id"], total_amount_cents=10000,
                               installment_count=2, frequency="MONTHLY",
                               schedule_basis="FRONT_LOADED")
        # Installment 1 due 2026-02-01; rewind clock to one day earlier so it is not yet due.
        set_clock("2026-01-31T00:00:00Z")
        p = validate_success(api.evaluate_pledge_delinquency(pledge["id"], GA))
        assert p["status"] == "ACTIVE", "no installment is at-or-before the clock -> stays ACTIVE"
        assert p["installments_due_count"] == 0


# ---------------------------------------------------------------------------
# Corner — cross-entity refund denies an unpaid match claim
# ---------------------------------------------------------------------------
class TestRefundDeniesUnpaidMatch:
    def test_refund_cascades_submitted_match_to_denied(self, api):
        """PRD §3.9: "if any matching claim against this gift is in `SUBMITTED` or
        `APPROVED`, that claim is cascaded to `DENIED`."

        Design: Corner/state_machines/gift_refund_denies_unpaid_match_cross_entity
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0)
        donor = create_donor(employer_id=emp["id"])
        acked, gift_id = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        claim = open_match_claim(gift_id)  # SUBMITTED

        refunded = validate_success(
            api.refund_gift(gift_id, {"expected_gift_version": acked["version"]}, GA)
        )
        assert refunded["status"] == "REFUNDED"
        claim_data = validate_success(api.get_match_claim(claim["id"], GA))
        assert claim_data["status"] == "DENIED", "refund denies the SUBMITTED claim (cross-entity)"
