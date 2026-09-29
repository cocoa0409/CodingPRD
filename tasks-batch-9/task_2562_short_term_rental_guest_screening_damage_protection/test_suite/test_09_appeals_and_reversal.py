"""Appeals: what an overturn gives back to the cent, and what an upheld one keeps."""

from test_helpers import (
    assertions,
    fixtures,
    validate_success,
)
from test_helpers.test_users import COMPLIANCE_OFFICER, SECOND_ADJUDICATOR


def _exhausting_approval(api):
    """A waiver listing whose single rung is spent by one fully approved claim."""
    cast = fixtures.setup_waiver_listing(
        api, guest_name="Alma Ferreira", guest_email="alma@guest.test"
    )
    layer = fixtures.add_coverage_layer(
        api, "DAMAGE_WAIVER", 10, 100000, 0, 1.0, "PROPERTY",
        property_id=cast.property_id,
    )
    before = validate_success(
        api.get_coverage_summary(cast.property_id, COMPLIANCE_OFFICER)
    )
    reservation = fixtures.complete_three_night_stay(api, cast)
    claim = fixtures.claim_under_review(api, cast, reservation["id"], 100000)
    approved = fixtures.approve_claim(api, claim["id"], 100000)
    return cast, layer, reservation, approved, before


def _appealed_by_guest(api, cast, claim_id, note):
    """The charged guest files the one admissible appeal against an approval."""
    appealed = validate_success(
        api.appeal_damage_claim(claim_id, cast.guest_headers, note=note)
    )
    assertions.assert_fields(
        appealed,
        "damage_claim",
        claim_state="APPEALED",
        appeal_round=1,
        appealed_by_role="Guest",
    )
    assertions.assert_fields(
        fixtures.read_host(api, cast), "host", payout_hold=True
    )
    return appealed


def test_an_overturned_appeal_hands_back_the_capacity_it_took_to_the_cent(api):
    """The 100000 the approval consumed comes back by voiding, not by deleting.

    Insurance capacity is the conserved quantity: the listing's only rung holds
    100000, the approval spends all of it and exhausts the layer, and the overturn
    restores exactly 100000 — while the allocation row survives with its own numbers
    intact under a voided flag, and the suspended listing deliberately stays down.

    PRD: "Every allocation line of this claim has its `voided` flag set to true, so each charged layer's `consumed_cents` falls back to its pre-approval value and any layer that had flipped to `EXHAUSTED` returns to `AVAILABLE`."
    PRD: "A layer returning to `AVAILABLE` restores `coverage_posture` on the listings it is visible to, but a listing that was suspended by that exhaustion cascade stays `SUSPENDED` until its host reactivates it."
    PRD: "On the claim, `approved_amount_cents`, `recovered_cents`, `uncovered_cents`, `host_absorbed_cents` and `deposit_applied_cents` are all reset to 0."
    PRD: "The guest's `approved_claim_count` falls by 1, which re-runs the risk score and removes the 7-point claim penalty."
    PRD: "Every branch sets `appeal_decision` and records `appeal_decided_by_user_id` as the acting adjudicator's `X-User-ID`, and every branch increases the claim's `version` by 1."

    Design: Difficulty/compensating_invariant/appeal_overturn_restores_coverage_layer_capacity_exactly
    """
    cast, layer, _reservation, approved, before = _exhausting_approval(api)
    assertions.assert_fields(
        before, "coverage_summary",
        remaining_capacity_cents=100000,
        coverage_posture="FULL",
    )
    assertions.assert_money_split(
        approved,
        approved_amount_cents=100000,
        deposit_applied_cents=0,
        recovered_cents=100000,
        uncovered_cents=0,
        host_absorbed_cents=0,
    )
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=100000,
        layer_state="EXHAUSTED",
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        listing_state="SUSPENDED",
        suspension_reason="COVERAGE_EXHAUSTED",
    )
    _appealed_by_guest(
        api, cast, approved["id"], "The pane was cracked before check-in."
    )

    reversed_claim = validate_success(
        api.decide_appeal(
            approved["id"],
            SECOND_ADJUDICATOR,
            decision="OVERTURNED",
            decision_reason_code="EVIDENCE_INSUFFICIENT",
        )
    )
    assertions.assert_fields(
        reversed_claim,
        "damage_claim",
        claim_state="DENIED",
        appeal_decision="OVERTURNED",
        appeal_decided_by_user_id="adj-2",
        decided_by_user_id="adj-1",
        approved_amount_cents=0,
        recovered_cents=0,
        uncovered_cents=0,
        host_absorbed_cents=0,
        deposit_applied_cents=0,
    )

    lines, _meta = assertions.assert_page(
        api.list_settlement_allocations(SECOND_ADJUDICATOR, claim_id=approved["id"]),
        total_count=1,
    )
    assertions.assert_allocation_line(
        lines[0],
        coverage_layer_id=layer["id"],
        gross_cents=100000,
        allocated_cents=100000,
        voided=True,
    )
    assertions.assert_page(
        api.list_settlement_allocations(
            SECOND_ADJUDICATOR, claim_id=approved["id"], voided=False
        ),
        total_count=0,
    )
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=0,
        layer_state="AVAILABLE",
    )

    after = validate_success(
        api.get_coverage_summary(cast.property_id, COMPLIANCE_OFFICER)
    )
    assertions.assert_fields(
        after,
        "coverage_summary",
        coverage_posture="FULL",
        visible_layer_count=1,
        available_layer_count=1,
        remaining_capacity_cents=100000,
    )
    assert after["remaining_capacity_cents"] == before["remaining_capacity_cents"], (
        "the restored capacity must equal the pre-approval capacity exactly"
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        listing_state="SUSPENDED",
        suspension_reason="COVERAGE_EXHAUSTED",
    )
    assertions.assert_fields(
        fixtures.read_host(api, cast), "host", payout_hold=False
    )
    guest = fixtures.read_guest(api, cast)
    assertions.assert_fields(guest, "guest", approved_claim_count=0)
    assertions.assert_guest_risk(guest, 31, "ELEVATED")


def test_an_upheld_appeal_gives_nothing_back_and_only_lifts_the_hold(api):
    """The same spent rung stays spent when the appeal fails.

    The compensating reversal is the property of the overturn alone. On identical
    facts an upheld appeal leaves the allocation unvoided, the layer at 100000
    consumed, the posture UNPROTECTED and the guest's claim penalty in place — the
    single thing it changes is the payout hold the filing had imposed.

    PRD: "Every monetary field and every allocation line is left exactly as the first-instance approval wrote it — no line is voided, no layer capacity is restored, the deposit stays `APPLIED`, and the guest's `approved_claim_count` and `risk_score` are unchanged."
    PRD: "The host's `payout_hold` is cleared back to false, because the appeal that justified the hold has been resolved."
    PRD: "`claim_state` returns from `APPEALED` to `APPROVED` and `appeal_decision` is set to `UPHELD`."
    PRD: "When the guest appeals an approval, the host's `payout_hold` is set to true and the host's `version` increases by 1, which bars that host from filing any further damage claim while the appeal is pending."

    Design: Difficulty/compensating_invariant/appeal_overturn_restores_coverage_layer_capacity_exactly
    """
    cast, layer, _reservation, approved, _before = _exhausting_approval(api)
    _appealed_by_guest(api, cast, approved["id"], "The pane was already cracked.")

    sustained = validate_success(
        api.decide_appeal(
            approved["id"],
            SECOND_ADJUDICATOR,
            decision="UPHELD",
            decision_reason_code="DAMAGE_CONFIRMED",
        )
    )
    assertions.assert_fields(
        sustained,
        "damage_claim",
        claim_state="APPROVED",
        appeal_decision="UPHELD",
        appeal_decided_by_user_id="adj-2",
    )
    assertions.assert_money_split(
        sustained,
        approved_amount_cents=100000,
        deposit_applied_cents=0,
        recovered_cents=100000,
        uncovered_cents=0,
        host_absorbed_cents=0,
    )

    lines, _meta = assertions.assert_page(
        api.list_settlement_allocations(SECOND_ADJUDICATOR, claim_id=approved["id"]),
        total_count=1,
    )
    assertions.assert_allocation_line(
        lines[0], allocated_cents=100000, voided=False
    )
    assertions.assert_page(
        api.list_settlement_allocations(
            SECOND_ADJUDICATOR, claim_id=approved["id"], voided=True
        ),
        total_count=0,
    )
    assertions.assert_layer_capacity(
        validate_success(api.get_coverage_layer(layer["id"], COMPLIANCE_OFFICER)),
        consumed_cents=100000,
        layer_state="EXHAUSTED",
    )
    assertions.assert_fields(
        validate_success(api.get_coverage_summary(cast.property_id, COMPLIANCE_OFFICER)),
        "coverage_summary",
        coverage_posture="UNPROTECTED",
        visible_layer_count=1,
        available_layer_count=0,
        remaining_capacity_cents=0,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        listing_state="SUSPENDED",
        suspension_reason="COVERAGE_EXHAUSTED",
    )
    assertions.assert_fields(
        fixtures.read_host(api, cast), "host", payout_hold=False
    )
    guest = fixtures.read_guest(api, cast)
    assertions.assert_fields(guest, "guest", approved_claim_count=1)
    assertions.assert_guest_risk(guest, 38, "ELEVATED")


def _deposit_approval(api):
    """A deposit listing with no coverage at all, whose 50000 hold is spent by a claim."""
    cast = fixtures.setup_deposit_listing(
        api, guest_name="Bo Nakamura", guest_email="bo@guest.test"
    )
    reservation = fixtures.complete_two_night_stay(api, cast)
    assertions.assert_fields(
        reservation,
        "reservation",
        deposit_state="HELD",
        deposit_hold_cents=50000,
        deposit_applied_cents=0,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", deposit_held_cents=50000
    )
    claim = fixtures.claim_under_review(api, cast, reservation["id"], 60000)
    approved = fixtures.approve_claim(api, claim["id"], 60000)
    return cast, reservation, approved


def test_an_overturned_appeal_puts_the_deposit_escrow_back_untouched(api):
    """50000 returns to escrow — not the 60000 approved and not a partial refund.

    Here the conserved quantity is the guest's escrow rather than any insurance
    capacity, and it is restored by a deposit transition rather than by voiding: the
    listing carries no coverage layer, so the approval spends the whole hold, leaves
    10000 uncovered, and the overturn hands back exactly the 50000 that was held.

    PRD: "When the reservation's `deposit_state` reads `APPLIED` it returns to `HELD` and the guest's `deposit_held_cents` is restored exactly to its pre-approval value."
    PRD: "On the claim, `approved_amount_cents`, `recovered_cents`, `uncovered_cents`, `host_absorbed_cents` and `deposit_applied_cents` are all reset to 0."
    PRD: "In parallel, when the deposit slice is non-zero the reservation's `deposit_state` moves from `HELD` to `APPLIED`, the guest's `deposit_held_cents` falls by the reservation's `deposit_hold_cents`, and both the reservation's `version` and the guest's `version` increase by 1."
    PRD: "`uncovered_cents` is whatever gross loss remains unabsorbed after the walk."

    Design: Difficulty/compensating_invariant/overturned_approval_restores_deposit_hold_exactly
    """
    cast, reservation, approved = _deposit_approval(api)
    assertions.assert_money_split(
        approved,
        approved_amount_cents=60000,
        deposit_applied_cents=50000,
        recovered_cents=50000,
        uncovered_cents=10000,
        host_absorbed_cents=10000,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        deposit_state="APPLIED",
        deposit_applied_cents=50000,
    )
    assertions.assert_fields(
        fixtures.read_guest(api, cast), "guest", deposit_held_cents=0
    )
    _appealed_by_guest(
        api, cast, approved["id"], "The countertop damage predates my stay."
    )

    reversed_claim = validate_success(
        api.decide_appeal(
            approved["id"],
            SECOND_ADJUDICATOR,
            decision="OVERTURNED",
            decision_reason_code="NORMAL_WEAR",
        )
    )
    assertions.assert_fields(
        reversed_claim,
        "damage_claim",
        claim_state="DENIED",
        appeal_decision="OVERTURNED",
        approved_amount_cents=0,
        deposit_applied_cents=0,
        recovered_cents=0,
        uncovered_cents=0,
        host_absorbed_cents=0,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        deposit_state="HELD",
        deposit_applied_cents=0,
        deposit_hold_cents=50000,
    )
    restored = fixtures.read_guest(api, cast)
    assertions.assert_fields(
        restored, "guest", deposit_held_cents=50000, approved_claim_count=0
    )
    assert restored["deposit_held_cents"] not in (40000, 60000), (
        "the escrow returns to the amount held, not to the approved or the net figure"
    )
    assertions.assert_guest_risk(restored, 31, "ELEVATED")
    assertions.assert_page(
        api.list_settlement_allocations(SECOND_ADJUDICATOR, claim_id=approved["id"]),
        total_count=0,
    )
    assertions.assert_fields(
        fixtures.read_property(api, cast),
        "property",
        listing_state="ACTIVE",
        suspension_reason=None,
    )
    assertions.assert_fields(
        fixtures.read_host(api, cast), "host", payout_hold=False
    )


def test_an_upheld_appeal_leaves_the_spent_deposit_spent(api):
    """The escrow stays consumed when the appeal fails, on identical facts.

    The restoration belongs to the overturn branch alone: with the appeal upheld the
    deposit stays APPLIED, the guest's escrow stays at zero, the 10000 uncovered tail
    and the host's 10000 absorption survive, and the seven-point claim penalty stays
    on the guest's score. Only the payout hold lifts.

    PRD: "Every monetary field and every allocation line is left exactly as the first-instance approval wrote it — no line is voided, no layer capacity is restored, the deposit stays `APPLIED`, and the guest's `approved_claim_count` and `risk_score` are unchanged."
    PRD: "The host's `payout_hold` is cleared back to false, because the appeal that justified the hold has been resolved."
    PRD: "After any appeal decision the claim sits again in `APPROVED` or `DENIED`, waiting for the sweep to settle or close it once `appeal_due_at` has passed."

    Design: Difficulty/compensating_invariant/overturned_approval_restores_deposit_hold_exactly
    """
    cast, reservation, approved = _deposit_approval(api)
    _appealed_by_guest(api, cast, approved["id"], "The damage predates my stay.")

    sustained = validate_success(
        api.decide_appeal(
            approved["id"],
            SECOND_ADJUDICATOR,
            decision="UPHELD",
            decision_reason_code="DAMAGE_CONFIRMED",
        )
    )
    assertions.assert_fields(
        sustained, "damage_claim", claim_state="APPROVED", appeal_decision="UPHELD"
    )
    assertions.assert_money_split(
        sustained,
        approved_amount_cents=60000,
        deposit_applied_cents=50000,
        recovered_cents=50000,
        uncovered_cents=10000,
        host_absorbed_cents=10000,
    )
    assertions.assert_fields(
        validate_success(api.get_reservation(reservation["id"], cast.host_headers)),
        "reservation",
        deposit_state="APPLIED",
        deposit_applied_cents=50000,
        deposit_hold_cents=50000,
    )
    spent = fixtures.read_guest(api, cast)
    assertions.assert_fields(
        spent, "guest", deposit_held_cents=0, approved_claim_count=1
    )
    assertions.assert_guest_risk(spent, 38, "ELEVATED")
    assertions.assert_page(
        api.list_settlement_allocations(SECOND_ADJUDICATOR, claim_id=approved["id"]),
        total_count=0,
    )
    assertions.assert_fields(
        fixtures.read_host(api, cast), "host", payout_hold=False
    )
