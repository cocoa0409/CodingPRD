"""Restitution: allocation variants, rounding order, payment cascades, conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_restitution_payment,
    assert_settlement,
    assert_settlement_conservation,
    assert_iso_instant,
    drive_to_executed_settlement,
    get_business,
    get_complaint,
    get_payment,
    get_settlement,
    mark_received,
    pledge_payment,
    register_business,
    register_case_parties,
    register_consumer,
    register_mediation_room,
    register_mediator,
    setup_settled_case,
    set_clock,
    validate_error,
    validate_success,
)

OFFICER_1 = TEST_USERS["intake_officer_headers"]


def _two_executed_settlements(consumer, business, mediator, room, amounts,
                              day="2026-08-10", second_day=None):
    """Two complaints on one business, each with an EXECUTED settlement at full
    outstanding; filing order gives the first complaint filing_seq 1."""
    (amount_a, amount_b) = amounts
    ctx_a = drive_to_executed_settlement(
        consumer, business, mediator, room,
        incident_date="2026-07-01", description="obligation a", restitution_cents=amount_a,
        session_starts_at=f"{day}T10:00:00Z", session_ends_at=f"{day}T11:00:00Z",
    )
    day_b = second_day or day
    ctx_b = drive_to_executed_settlement(
        consumer, business, mediator, room,
        incident_date="2026-07-02", description="obligation b", restitution_cents=amount_b,
        session_starts_at=f"{day_b}T12:00:00Z", session_ends_at=f"{day_b}T13:00:00Z",
    )
    return ctx_a, ctx_b


def _setup_dual_allocation(api):
    """Identical obligation shapes on two businesses: 6000 (filing_seq 1) and
    5000 (filing_seq 2), both EXECUTED; a 10000 payment on each — CHRONOLOGICAL
    on the first, PRO_RATA on the second (PRD §3.7)."""
    conx = register_consumer(full_name="C X", email="cx@x.com", state_code="OR")
    cony = register_consumer(full_name="C Y", email="cy@x.com", state_code="OR")
    bizx = register_business(legal_name="RateX", home_state="OR", operates_in_states=["OR"])
    bizy = register_business(legal_name="RateY", home_state="OR", operates_in_states=["OR"])
    med = register_mediator(full_name="Med Two", employee_ref="EMP-2")
    room = register_mediation_room(room_name="Room B", capacity=8, location="Salem")
    set_clock("2026-08-01T00:00:00Z")

    ax, bx = _two_executed_settlements(conx, bizx, med, room, (6000, 5000), day="2026-08-10")
    ay, by = _two_executed_settlements(cony, bizy, med, room, (6000, 5000), day="2026-08-11")

    payx = pledge_payment(bizx, 10000)  # CHRONOLOGICAL by default
    payy = pledge_payment(bizy, 10000, allocation_method="PRO_RATA")
    mark_received(payx["id"])
    mark_received(payy["id"])
    return {
        "conx": conx, "cony": cony, "bizx": bizx, "bizy": bizy,
        "ax": ax, "bx": bx, "ay": ay, "by": by, "payx": payx, "payy": payy,
    }


class TestAllocationMethodVariants:
    def test_chronological_allocation_fills_earliest_filing_first(self, api):
        """PRD §3.7: "Under `CHRONOLOGICAL`, the payment fills each obligation completely, in filing order, before moving to the next, and the final obligation touched may receive only a partial fill."
        PRD §3.7: "a payment of 10,000 cents against obligations of 6,000 cents (the earlier filing) and 5,000 cents allocates 6,000 and 4,000 chronologically, but 5,455 and 4,545 pro rata"

        Design: Difficulty/dual_variant_calc/d_allocation_chronological_vs_prorata
        """
        env = _setup_dual_allocation(api)
        setax = get_settlement(env["ax"]["settlement"]["id"])
        setbx = get_settlement(env["bx"]["settlement"]["id"])
        assert setax["fulfilled_cents"] == 6000 and setax["outstanding_cents"] == 0
        assert setax["settlement_status"] == "FULFILLED"
        assert setbx["fulfilled_cents"] == 4000 and setbx["outstanding_cents"] == 1000
        assert_settlement_conservation(setax)
        assert_settlement_conservation(setbx)
        assert get_complaint(env["ax"]["complaint"]["id"])["case_status"] == "SETTLED", (
            "the fully filled earlier filing settles"
        )
        assert get_complaint(env["bx"]["complaint"]["id"])["case_status"] == "SETTLEMENT_PENDING"

    def test_prorata_allocation_splits_by_outstanding_share(self, api):
        """PRD §3.7: "Under `PRO_RATA`, each obligation's provisional share is the payment amount multiplied by that obligation's outstanding balance and divided by the total outstanding across all eligible obligations, with every line rounded half-up to whole cents first"
        PRD §3.7: "a payment of 10,000 cents against obligations of 6,000 cents (the earlier filing) and 5,000 cents allocates 6,000 and 4,000 chronologically, but 5,455 and 4,545 pro rata"

        Design: Difficulty/dual_variant_calc/d_allocation_chronological_vs_prorata
        """
        env = _setup_dual_allocation(api)
        setay = get_settlement(env["ay"]["settlement"]["id"])
        setby = get_settlement(env["by"]["settlement"]["id"])
        assert setay["fulfilled_cents"] == 5455, "round_half_up(10000*6000/11000)"
        assert setay["outstanding_cents"] == 545
        assert setby["fulfilled_cents"] == 4545
        assert setby["outstanding_cents"] == 455
        assert setay["settlement_status"] == "EXECUTED", "partial fill leaves the settlement open"
        assert get_complaint(env["ay"]["complaint"]["id"])["case_status"] == "SETTLEMENT_PENDING"
        # Divergence over the identical obligation shape and amount.
        setax = get_settlement(env["ax"]["settlement"]["id"])
        assert setax["fulfilled_cents"] != setay["fulfilled_cents"]


class TestProRataRoundingOrder:
    def _setup_rounding_case(self, api):
        parties = register_case_parties(
            consumer_overrides={"full_name": "C R", "email": "cr@x.com"},
            business_overrides={"legal_name": "RoundCo"},
        )
        set_clock("2026-08-01T00:00:00Z")
        a, b = _two_executed_settlements(
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
            (100, 100),
        )
        payment = pledge_payment(parties["business"], 99, allocation_method="PRO_RATA")
        mark_received(payment["id"])
        return a, b, payment

    def test_prorata_overshoot_cent_removed_from_latest_filing(self, api):
        """PRD §3.7: "with every line rounded half-up to whole cents first; the lines are then reconciled cent by cent — if the shares fall short of the payment, one cent at a time is added to lines in ascending filing order, cycling through them, until the payment is fully distributed, and if the shares overshoot, one cent at a time is removed from lines in descending filing order until the books balance"

        Design: Difficulty/combinatorial_formula/d_prorata_rounding_order
        """
        a, b, _ = self._setup_rounding_case(api)
        seta = get_settlement(a["settlement"]["id"])
        setb = get_settlement(b["settlement"]["id"])
        # Per-line round_half_up(99*100/200) = 50 each (sum 100 > 99); the overshoot
        # cent comes off the LARGEST filing_seq.
        assert seta["fulfilled_cents"] == 50 and seta["outstanding_cents"] == 50
        assert setb["fulfilled_cents"] == 49 and setb["outstanding_cents"] == 51

    def test_prorata_reconciliation_conserves_payment_cents(self, api):
        """PRD §3.7: "The target settlement's `fulfilled_cents` grows and its `outstanding_cents` shrinks by the allocated amount."
        PRD §3.7: "A settlement whose outstanding reaches exactly zero becomes `FULFILLED`, with `fulfilled_at` stamped."

        Design: Difficulty/combinatorial_formula/d_prorata_rounding_order
        """
        a, b, payment = self._setup_rounding_case(api)
        seta = get_settlement(a["settlement"]["id"])
        setb = get_settlement(b["settlement"]["id"])
        assert seta["fulfilled_cents"] + setb["fulfilled_cents"] == 99, "payment conserved exactly"
        assert seta["settlement_status"] == "EXECUTED"
        assert setb["settlement_status"] == "EXECUTED", "no fulfillment at partial allocation"
        allocated = get_payment(payment["id"])
        assert_restitution_payment(allocated)
        assert allocated["payment_status"] == "ALLOCATED"
        assert sum(line["allocated_cents"] for line in allocated["allocations"]) == 99


class TestPaymentCascade:
    def test_mark_received_cascades_allocation_to_fulfillment(self, api):
        """PRD §3.7: "Marking received stamps `received_at`, moves the payment to `ALLOCATED`, and records the computed breakdown in `allocations` as entries of `settlement_id`, `complaint_id`, `filing_seq`, and `allocated_cents`."
        PRD §3.7: "A settlement whose outstanding reaches exactly zero becomes `FULFILLED`, with `fulfilled_at` stamped."

        Design: Difficulty/transitive_cascade/d_cascade_payment_to_embargo
        """
        ctx = setup_settled_case(restitution_cents=5000)
        payment = ctx["payment"]
        assert payment["payment_status"] == "ALLOCATED"
        assert len(payment["allocations"]) == 1
        line = payment["allocations"][0]
        assert line["settlement_id"] == ctx["settlement"]["id"]
        assert line["complaint_id"] == ctx["complaint"]["id"]
        assert line["filing_seq"] == 1
        line_amount = line["allocated_cents"]
        assert line_amount == 5000

        settlement = ctx["settlement"]
        assert settlement["fulfilled_cents"] == 5000
        assert settlement["outstanding_cents"] == 0
        assert settlement["settlement_status"] == "FULFILLED"
        assert_iso_instant(settlement["fulfilled_at"], "2026-08-04T00:00:00Z", "fulfilled_at")

    def test_fulfilled_settlement_settles_complaint_and_embargoes(self, api):
        """PRD §3.7: "the complaint behind a freshly fulfilled settlement moves from `SETTLEMENT_PENDING` to `SETTLED`, with the closure ritual of §3.8 — `closed_at`, embargo or suppression, pattern recomputation — firing in full"
        PRD §2.10: "When a case reaches `SETTLED`, `CLOSED_UNRESOLVED`, or `REFERRED_ENFORCEMENT`, a complaint filed with `publication_consent` moves from `UNPUBLISHED` to `EMBARGOED`"
        PRD §3.8: "Each eligible complaint contributes a weight by outcome — 10 for `SETTLED`, 15 for `CLOSED_UNRESOLVED`, 25 for `REFERRED_ENFORCEMENT`"

        Design: Difficulty/transitive_cascade/d_cascade_payment_to_embargo
        """
        ctx = setup_settled_case(restitution_cents=5000)
        complaint = ctx["complaint"]
        assert complaint["case_status"] == "SETTLED"
        assert complaint["publication_status"] == "EMBARGOED"
        assert_iso_instant(complaint["closed_at"], "2026-08-04T00:00:00Z", "closed_at")

        business = ctx["business"]
        assert business["pattern_score"] == 10, "SETTLED weight 10 at SMALL x1.0"


class TestRestitutionConservationInvariant:
    def _setup_partially_allocated(self, api):
        parties = register_case_parties(
            consumer_overrides={"full_name": "C V", "email": "cv@x.com"},
            business_overrides={"legal_name": "InvCo"},
        )
        set_clock("2026-08-01T00:00:00Z")
        ctx = drive_to_executed_settlement(
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
            incident_date="2026-07-01", description="inv", restitution_cents=5000,
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        payment = pledge_payment(parties["business"], 3000)
        mark_received(payment["id"])
        return parties, ctx, payment

    def test_payment_return_restores_settlement_balances(self, api):
        """PRD §3.7: "A valid return moves the payment to `RETURNED` and reverses everything: each settlement's `fulfilled_cents` is decremented and its `outstanding_cents` restored, any settlement that had become `FULFILLED` reverts to `EXECUTED` with `fulfilled_at` cleared to null, the `allocations` list is emptied"

        Design: Difficulty/compensating_invariant/d_invariant_restitution_conservation
        """
        parties, ctx, payment = self._setup_partially_allocated(api)
        mid = get_settlement(ctx["settlement"]["id"])
        assert mid["fulfilled_cents"] == 3000 and mid["outstanding_cents"] == 2000
        assert_settlement_conservation(mid)

        returned = validate_success(api.mark_payment_returned(payment["id"], OFFICER_1))
        assert returned["payment_status"] == "RETURNED"
        assert returned["allocations"] == [], "allocations emptied on return"

        after = get_settlement(ctx["settlement"]["id"])
        assert after["fulfilled_cents"] == 0
        assert after["outstanding_cents"] == 5000

    def test_conservation_invariant_holds_across_allocate_and_return(self, api):
        """PRD §3.6: "While a settlement stands in `DRAFT`, `EXECUTED`, `FULFILLED`, or `BREACHED`, its `outstanding_cents` is its restitution minus its `fulfilled_cents`."
        PRD §3.7: "A valid return moves the payment to `RETURNED` and reverses everything"

        Design: Difficulty/compensating_invariant/d_invariant_restitution_conservation
        """
        parties, ctx, payment = self._setup_partially_allocated(api)
        allocated = get_settlement(ctx["settlement"]["id"])
        assert_settlement_conservation(allocated)

        validate_success(api.mark_payment_returned(payment["id"], OFFICER_1))
        restored = get_settlement(ctx["settlement"]["id"])
        assert_settlement_conservation(restored), "zero drift after the compensating return"
        assert restored["settlement_status"] == "EXECUTED", (
            "settlement never left the open set; no FULFILLED flip to revert"
        )
        complaint = get_complaint(ctx["complaint"]["id"])
        assert complaint["case_status"] == "SETTLEMENT_PENDING", (
            "complaint unchanged by the reversed allocation"
        )


class TestValidationPriorityStateBeatsFiscal:
    def _setup_settled_with_returned_payment(self, api):
        """Settlement 5000 EXECUTED; pay1 3000 ALLOCATED then RETURNED; pay2 5000
        ALLOCATED, fulfilling the settlement and settling the complaint; total open
        outstanding is now 0."""
        parties = register_case_parties(
            consumer_overrides={"full_name": "C E", "email": "ce@x.com"},
            business_overrides={"legal_name": "PrioCo"},
        )
        set_clock("2026-08-01T00:00:00Z")
        ctx = drive_to_executed_settlement(
            parties["consumer"], parties["business"], parties["mediator"], parties["room"],
            incident_date="2026-07-01", description="prio", restitution_cents=5000,
            session_starts_at="2026-08-10T10:00:00Z", session_ends_at="2026-08-10T11:00:00Z",
        )
        pay1 = pledge_payment(parties["business"], 3000)
        mark_received(pay1["id"])
        validate_success(api.mark_payment_returned(pay1["id"], OFFICER_1))
        pay2 = pledge_payment(parties["business"], 5000)
        mark_received(pay2["id"])
        assert get_complaint(ctx["complaint"]["id"])["case_status"] == "SETTLED"
        return parties, ctx, pay1

    def test_returned_payment_receipt_fails_state_before_fiscal_gate(self, api):
        """PRD §2.12: "Checks on any request run in a fixed order, and a failure at an earlier step masks every later one"
        PRD §2.12: "6. State: the target entity sits in a valid from-state for the requested transition, else `ERR_INVALID_STATE`."
        PRD §2.12: "11. The fiscal gate: a payment being marked received may not exceed the business's total open outstanding, else `ERR_RESTITUTION_EXCEEDS_OUTSTANDING`."

        Design: Difficulty/priority_pair_validation_conflict/d_priority_state_beats_fiscal
        """
        parties, ctx, pay1 = self._setup_settled_with_returned_payment(api)
        # pay1 is RETURNED (state gate) and its 3000 exceeds open outstanding 0
        # (fiscal gate); the earlier state check masks the fiscal one.
        resp = api.mark_payment_received(pay1["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_re_receipt_leaves_payment_and_closure_untouched(self, api):
        """PRD §2.12: "Checks on any request run in a fixed order, and a failure at an earlier step masks every later one"
        PRD §3.7: "A valid return moves the payment to `RETURNED`"

        Design: Difficulty/priority_pair_validation_conflict/d_priority_state_beats_fiscal
        """
        parties, ctx, pay1 = self._setup_settled_with_returned_payment(api)
        resp = api.mark_payment_received(pay1["id"], OFFICER_1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        payment = get_payment(pay1["id"])
        assert payment["payment_status"] == "RETURNED", "payment unchanged by the rejected receipt"
        complaint = get_complaint(ctx["complaint"]["id"])
        assert complaint["case_status"] == "SETTLED", (
            "the second payment's allocation had fulfilled the settlement"
        )
