"""Removal gating (rental fiscal branch vs purchase cooling-off branch),
buyback variants, removal completion cascade, and compensating cancel."""
import pytest

from test_helpers import (
    api_client, TEST_USERS,
    validate_success, validate_error,
    ApiErrorId, MODEL_STRAIGHT,
    set_clock, create_catalog_model, setup_approved_assessment,
    create_agreement, get_agreement, get_equipment_unit, get_service_plan,
    get_warranty_claim, drive_agreement_to_active, attach_service_plan,
    activate_agreement, record_payment, schedule_removal,
    setup_active_agreement, setup_active_purchase_past_cooling_off,
    file_claim, review_claim, adjudicate_claim,
    create_removal_job_payload, fresh_crew,
)

COORD = TEST_USERS["install_coordinator_headers"]
FUNDING = TEST_USERS["funding_officer_headers"]


# ---------------------------------------------------------------------------
# Mode-dependent removal gates (branching fork)
# ---------------------------------------------------------------------------

def test_rental_removal_blocked_until_fully_paid(api):
    """PRD §3.7: "For a `RENTAL` agreement, removal is blocked until the rental
    is fully paid — `paid_to_date_cents` must have reached `list_price_cents`
    — otherwise `ERR_RENTAL_BALANCE_OUTSTANDING` (402)."
    PRD §3.4: "The agreement's `list_price_cents` is mode-dependent: for
    `PURCHASE` it is the quote's `issued_total_cents`; for `RENTAL` it is the
    model's `monthly_rental_rate_cents` multiplied by the
    `committed_rental_months` from the acceptance payload."

    Design: Difficulty/non_linear_state_machine/agreement_branching_rental_vs_purchase
    """
    # 7500 * 24 months = 180000 list; only 100000 is paid before the attempt.
    bag = setup_active_agreement(acquisition_mode="RENTAL",
                                 committed_rental_months=24, tier="BASIC")
    agreement = get_agreement(bag["agreement"]["id"])
    assert agreement["list_price_cents"] == 180000
    record_payment(bag["agreement"]["id"], 100000, bag["customer"]["id"])

    res = api.create_removal_job(
        bag["agreement"]["id"],
        create_removal_job_payload(fresh_crew("CREW-RL"),
                                   scheduled_start_utc="2026-07-01T09:00:00Z",
                                   scheduled_end_utc="2026-07-01T11:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_RENTAL_BALANCE_OUTSTANDING)


def test_purchase_removal_allowed_after_cooling_off(api):
    """PRD §3.7: "For a `PURCHASE` agreement, a cooling-off period applies: at
    least 30 days must have elapsed since the install completed, otherwise
    `ERR_REMOVAL_COOLING_OFF` (409)."
    PRD §3.7: "Creating the job moves the agreement from `ACTIVE` to
    `REMOVAL_REQUESTED` and computes the `buyback_offered_cents` on the job."
    PRD §3.7: "For a **purchase**, the market-adjusted variant applies: ... so
    the offer never quite reaches zero."

    Design: Difficulty/non_linear_state_machine/agreement_branching_rental_vs_purchase
    """
    # Installed 2026-06-10; clock at 2026-07-15 is past the 30-day window.
    bag = setup_active_purchase_past_cooling_off()
    job = schedule_removal(bag["agreement"]["id"], crew=fresh_crew("CREW-PU"),
                           start="2026-08-01T09:00:00Z",
                           end="2026-08-01T11:00:00Z")
    assert job["status"] == "SCHEDULED"
    # Market-adjusted decay never reaches zero for a purchase.
    assert isinstance(job["buyback_offered_cents"], int)
    assert job["buyback_offered_cents"] > 0
    agreement = get_agreement(bag["agreement"]["id"])
    assert agreement["status"] == "REMOVAL_REQUESTED"


def test_purchase_removal_cooling_off_violation(api):
    """PRD §3.7: "For a `PURCHASE` agreement, a cooling-off period applies: at
    least 30 days must have elapsed since the install completed, otherwise
    `ERR_REMOVAL_COOLING_OFF` (409)."

    Design: Corner/validations/purchase_removal_cooling_off_violation
    """
    # Installed 2026-06-10; clock advanced only to 2026-06-20 (10 days).
    bag = setup_active_agreement(tier="BASIC")
    set_clock("2026-06-20T00:00:00Z")
    res = api.create_removal_job(
        bag["agreement"]["id"],
        create_removal_job_payload(fresh_crew("CREW-CO"),
                                   scheduled_start_utc="2026-06-25T09:00:00Z",
                                   scheduled_end_utc="2026-06-25T11:00:00Z"),
        COORD)
    validate_error(res, ApiErrorId.ERR_REMOVAL_COOLING_OFF)


# ---------------------------------------------------------------------------
# Buyback straight-line variant reaches zero at end of useful life
# ---------------------------------------------------------------------------

def test_buyback_offer_straight_line_zero_at_useful_life(api):
    """PRD §3.7: "For a **rental**, the straight-line variant applies: the base
    is multiplied by the larger of zero and one minus the elapsed whole months
    of installation divided by a 120-month useful life, then multiplied by the
    condition factor for the grade recorded on the removal — 0.85 for
    `REFURB_A`, 0.65 for `REFURB_B`, 0.35 for `REFURB_C`, and 0.0 for `RETIRED`
    — so the offer can decay all the way to zero."

    Design: Corner/calculations/buyback_offer_straight_line_zero_at_useful_life
    """
    set_clock()
    create_catalog_model(model_code="SL-BB", base_purchase_price_cents=450000,
                         monthly_rental_rate_cents=8500, install_labor_hours=6)
    base = setup_approved_assessment("SL-BB")
    bag = create_agreement(base["customer"]["id"], base["assessment"]["id"],
                           "SL-BB", "RENTAL", committed_rental_months=6,
                           liability_waiver_signed=True)
    drive_agreement_to_active(bag["agreement"], bag["quote"], tier="BASIC",
                              funding="skip", rail_length=4.00, labor_hours=6)
    # Rental list is 8500 * 6 = 51000; pay it off in full to clear the gate.
    agreement = get_agreement(bag["agreement"]["id"])
    record_payment(bag["agreement"]["id"], agreement["list_price_cents"],
                   base["customer"]["id"])
    # Ten years later: whole months installed >= 120, so the straight-line
    # depreciation factor is floored at zero.
    set_clock("2036-06-15T00:00:00Z")
    job = schedule_removal(bag["agreement"]["id"], crew=fresh_crew("CREW-BB"),
                           start="2036-07-01T09:00:00Z",
                           end="2036-07-01T11:00:00Z")
    assert job["buyback_offered_cents"] == 0


# ---------------------------------------------------------------------------
# Removal completion: the four-hop cascade
# ---------------------------------------------------------------------------

def _setup_removal_cascade_scenario():
    """ACTIVE PURCHASE agreement past cooling-off, STANDARD plan, two claims
    (one UNDER_REVIEW, one APPROVED-but-unpaid), removal job SCHEDULED."""
    bag = setup_active_purchase_past_cooling_off(tier="STANDARD", region="EAST")
    plan = bag["service_plan"]
    wc1 = file_claim(bag["agreement"]["id"], plan["id"], "MECHANICAL", 10000)
    wc2 = file_claim(bag["agreement"]["id"], plan["id"], "ELECTRICAL", 5000)
    review_claim(wc1["id"])
    review_claim(wc2["id"])
    adjudicate_claim(wc2["id"], "APPROVED", approved_cents=5000)
    removal = schedule_removal(bag["agreement"]["id"], crew=fresh_crew("CREW-D"),
                               start="2026-07-20T09:00:00Z",
                               end="2026-07-20T11:00:00Z")
    return bag, plan, wc1, wc2, removal


def test_removal_complete_cascades_agreement_unit_and_plan(api):
    """PRD §3.7: "Completing the removal requires the assessor-graded
    `condition_grade_at_removal` (`REFURB_A`, `REFURB_B`, `REFURB_C`, or
    `RETIRED`) and triggers the largest cascade in the system: the agreement
    moves from `REMOVAL_REQUESTED` to `REMOVED`; the unit moves to `REMOVED`
    and takes on that graded condition; the service plan cascades to
    `CANCELLED`; and every warranty claim still in `SUBMITTED`, `UNDER_REVIEW`,
    or `APPROVED` is forcibly moved to `DENIED` with its `denial_reason` set to
    `AGREEMENT_REMOVED` — a compensating reversal even for claims already
    approved but not yet paid."

    Design: Difficulty/transitive_cascade/removal_complete_four_hop_cascade
    """
    bag, plan, wc1, wc2, removal = _setup_removal_cascade_scenario()
    completed = validate_success(
        api.complete_removal_job(removal["id"],
                                 {"condition_grade_at_removal": "REFURB_A"},
                                 COORD), 200)
    assert completed["status"] == "COMPLETED"

    agreement = get_agreement(bag["agreement"]["id"])
    assert agreement["status"] == "REMOVED"
    unit = get_equipment_unit(bag["unit"]["id"])
    assert unit["status"] == "REMOVED"
    assert unit["condition_grade"] == "REFURB_A"
    plan_after = get_service_plan(plan["id"])
    assert plan_after["status"] == "CANCELLED"


def test_removal_complete_denies_open_claims_with_agreement_removed(api):
    """PRD §3.7: "Completing the removal requires the assessor-graded
    `condition_grade_at_removal` (`REFURB_A`, `REFURB_B`, `REFURB_C`, or
    `RETIRED`) and triggers the largest cascade in the system: the agreement
    moves from `REMOVAL_REQUESTED` to `REMOVED`; the unit moves to `REMOVED`
    and takes on that graded condition; the service plan cascades to
    `CANCELLED`; and every warranty claim still in `SUBMITTED`, `UNDER_REVIEW`,
    or `APPROVED` is forcibly moved to `DENIED` with its `denial_reason` set to
    `AGREEMENT_REMOVED` — a compensating reversal even for claims already
    approved but not yet paid."

    Design: Difficulty/transitive_cascade/removal_complete_four_hop_cascade
    """
    bag, plan, wc1, wc2, removal = _setup_removal_cascade_scenario()
    validate_success(
        api.complete_removal_job(removal["id"],
                                 {"condition_grade_at_removal": "REFURB_A"},
                                 COORD), 200)

    wc1_after = get_warranty_claim(wc1["id"])
    assert wc1_after["status"] == "DENIED"
    assert wc1_after["denial_reason"] == "AGREEMENT_REMOVED"
    wc2_after = get_warranty_claim(wc2["id"])
    assert wc2_after["status"] == "DENIED"
    assert wc2_after["denial_reason"] == "AGREEMENT_REMOVED"


# ---------------------------------------------------------------------------
# Removal cancel: compensating revert
# ---------------------------------------------------------------------------

def test_cascading_side_effects_removaljob_cancel_reverts_agreement(api):
    """PRD §3.7: "A removal job still `SCHEDULED` may instead be cancelled,
    which is itself compensating: the agreement reverts from
    `REMOVAL_REQUESTED` back to `ACTIVE`."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_removaljob_cancel_reverts_agreement
    """
    bag = setup_active_purchase_past_cooling_off(tier="BASIC")
    removal = schedule_removal(bag["agreement"]["id"], crew=fresh_crew("CREW-RC"),
                               start="2026-08-01T09:00:00Z",
                               end="2026-08-01T11:00:00Z")
    assert get_agreement(bag["agreement"]["id"])["status"] == "REMOVAL_REQUESTED"

    cancelled = validate_success(api.cancel_removal_job(removal["id"], COORD), 200)
    assert cancelled["status"] == "CANCELLED"
    agreement = get_agreement(bag["agreement"]["id"])
    assert agreement["status"] == "ACTIVE"
