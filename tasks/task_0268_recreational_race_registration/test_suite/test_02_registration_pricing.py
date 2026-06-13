"""Registration creation, the pinned pricing sequence, refunds, and deferral credit.

Covers difficulty rules dual_variant_calc, combinatorial_formula, and corner
instances under sections entities and calculations.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    make_participant_headers, assert_registration,
)
from test_helpers import fixtures as fx
from test_helpers.constants import CLOCK_REGULAR, CLOCK_LATE

RD = TEST_USERS["race_director_headers"]


# ---------------------------------------------------------------------------
# Required fields / defaults / computed fields (corner: entities)
# ---------------------------------------------------------------------------
def test_create_registration_missing_participant_id_rejected(api):
    """PRD §2.10: "then well-formedness of the request body — required fields
    present and well-typed, enum values within their declared sets, `party_size` at
    least 1, and amounts at least 1 where required (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/create_registration_missing_required_field_rejected
    """
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    resp = api.create_registration(
        {"event_id": event["id"], "distance_id": distance["id"], "wave_id": wave["id"]},
        headers)  # participant_id omitted
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_registration_entry_type_defaults_to_standard(api):
    """PRD §3.2: "The optional `entry_type` is `STANDARD` or `CHARITY`, defaulting to
    `STANDARD`."
    PRD §3.2: "For a charity entry, the system at creation copies the distance's
    `charity_fundraising_minimum_cents` into the registration's
    `fundraising_minimum_cents`; for a standard entry that minimum is 0."

    Design: Corner/entities/registration_entry_type_defaults_to_standard
    """
    event, distance, wave = fx.setup_open_event(
        capacity_total=50, charity_fundraising_minimum_cents=25000)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant)  # no entry_type
    assert reg["entry_type"] == "STANDARD", f"expected STANDARD, got {reg['entry_type']}"
    assert reg["fundraising_minimum_cents"] == 0, \
        f"standard entry minimum must be 0, got {reg['fundraising_minimum_cents']}"


def test_registration_amount_due_is_server_computed(api):
    """PRD §3.2: "At creation the system computes a provisional charge and stores it
    in `amount_due_cents`, using the registration's `created_at` as the reference
    clock."
    PRD §2.7: "All monetary amounts in the system are expressed as integer cents".

    Design: Corner/entities/registration_amount_due_ignores_client_supplied_computed_field
    """
    # REGULAR base 5500, party 1, no promo -> discount 0, fee ceil(5500*0.029)=160,
    # amount 5660.
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant)
    assert_registration(reg)
    assert reg["amount_due_cents"] == 5660, \
        f"expected amount_due_cents 5660, got {reg['amount_due_cents']}"


# ---------------------------------------------------------------------------
# No active pricing tier (corner: calculations)
# ---------------------------------------------------------------------------
def test_no_active_pricing_tier_before_earliest_effective_from(api):
    """PRD §3.2: "the base fee is the active pricing tier's `base_price_cents` for the
    distance at the reference clock; if no tier is active because the reference clock
    precedes the earliest `effective_from_utc`, the request is rejected with
    `ERR_NO_ACTIVE_PRICING_TIER`."

    Design: Corner/calculations/no_active_pricing_tier_before_earliest_effective_from
    """
    # Only tier starts 2026-05-01; open the event at 2026-02-01.
    event, distance, wave = fx.setup_open_event(capacity_total=50, open_clock="2026-02-01T00:00:00Z")
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    from test_helpers.factories import registration_payload
    resp = api.create_registration(
        registration_payload(event["id"], distance["id"], wave["id"], participant["id"]),
        headers)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_PRICING_TIER.value)


# ---------------------------------------------------------------------------
# Charity entry: base price waived (corner: calculations)
# ---------------------------------------------------------------------------
def test_charity_entry_zero_base_price(api):
    """PRD §3.2: "For a charity entry the base fee is instead 0 — the entry fee is
    waived."
    PRD §3.2: "For a charity entry, the system at creation copies the distance's
    `charity_fundraising_minimum_cents` into the registration's
    `fundraising_minimum_cents`".

    Design: Corner/calculations/charity_entry_zero_base_price
    """
    event, distance, wave = fx.setup_open_event(
        capacity_total=50, charity_capacity=10, charity_fundraising_minimum_cents=25000)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant, entry_type="CHARITY")
    assert reg["amount_due_cents"] == 0, \
        f"charity base waived -> amount_due_cents 0, got {reg['amount_due_cents']}"
    assert reg["fundraising_minimum_cents"] == 25000, \
        f"charity minimum copied from distance, got {reg['fundraising_minimum_cents']}"


# ---------------------------------------------------------------------------
# Combinatorial pricing: nested group+promo discount under cap
# (difficulty: combinatorial_formula)
# ---------------------------------------------------------------------------
def test_amount_due_group_and_promo_discount_combined(api):
    """PRD §3.2: "a party of at least 4 earns 0.10, a party of at least 2 but fewer
    than 4 earns 0.05, and a solo registrant earns 0.00."
    PRD §3.2: "`SPRING10` is worth 0.10 and `WELCOME05` is worth 0.05; any other or
    absent code is worth 0.00."
    PRD §3.2: "the group and promo percentages are added together and then capped at
    the maximum total discount of 0.20."
    PRD §3.2: "the discount in cents is the base multiplied by that capped
    percentage, rounded half-up to a whole cent ... the processing fee in cents is
    the discounted base multiplied by the processing fee rate of 0.029, rounded up
    to the next whole cent."

    Design: Difficulty/combinatorial_formula/amount_due_nested_min_group_and_promo_discount_cap
    """
    # MARATHON REGULAR base 5500, party 2 (group 0.05) + SPRING10 (promo 0.10) = 0.15.
    # discount = round_half_up(5500*0.15)=825; discounted=4675; fee=ceil(4675*0.029)=136;
    # amount = 4811.
    event, distance, wave = fx.setup_open_event(
        capacity_total=50, distance_label="MARATHON", distance_km=42.195)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant,
                                 party_size=2, promo_code="SPRING10")
    assert reg["amount_due_cents"] == 4811, \
        f"expected amount_due_cents 4811, got {reg['amount_due_cents']}"
    # PRD §3.2: "no charge is captured at creation, `amount_paid_cents` and
    # `processing_fee_cents` remain 0" — the 136 fee is embedded in amount_due_cents
    # but the stored processing_fee_cents field stays 0 until payment confirmation.
    assert reg["processing_fee_cents"] == 0, \
        f"no charge captured at creation, processing_fee_cents must be 0, got {reg['processing_fee_cents']}"


def test_amount_due_solo_no_promo_baseline(api):
    """PRD §3.2: "a solo registrant earns 0.00."
    PRD §3.2: "the processing fee in cents is the discounted base multiplied by the
    processing fee rate of 0.029, rounded up to the next whole cent. Finally, the
    amount is the discounted base plus the processing fee."

    Design: Difficulty/combinatorial_formula/amount_due_nested_min_group_and_promo_discount_cap
    """
    # Solo, no promo: discount 0; fee ceil(5500*0.029)=160; amount 5660.
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant)
    assert reg["amount_due_cents"] == 5660, \
        f"expected amount_due_cents 5660, got {reg['amount_due_cents']}"
    assert reg["processing_fee_cents"] == 0, \
        f"no charge captured at creation, processing_fee_cents must be 0, got {reg['processing_fee_cents']}"


# ---------------------------------------------------------------------------
# Dual-variant: provisional vs final pricing diverge across a tier flip
# (difficulty: dual_variant_calc)
# ---------------------------------------------------------------------------
def test_amount_due_provisional_vs_final_diverge_on_tier_flip(api):
    """PRD §3.3: "the system captures the final charge into `amount_paid_cents`,
    recording the `processing_fee_cents` component, computed with the very same
    pinned pricing sequence as the provisional estimate but now using the
    confirm-time clock as the reference. If the active tier changed between creation
    and confirmation, this final figure legitimately diverges from
    `amount_due_cents`."

    Design: Difficulty/dual_variant_calc/amount_due_provisional_vs_final_diverges_on_tier_flip
    """
    # Create under REGULAR (5500 -> due 5660); confirm under LATE (7000 -> paid 7203).
    event, distance, wave = fx.setup_open_event(
        capacity_total=50, distance_label="MARATHON", distance_km=42.195,
        tiers=fx.standard_tiers(), open_clock="2026-06-01T00:00:00Z")
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    fx.set_clock(CLOCK_REGULAR)  # 2026-06-09 -> REGULAR active
    reg = fx.create_registration(event, distance, wave, participant)
    assert reg["amount_due_cents"] == 5660, \
        f"provisional under REGULAR expected 5660, got {reg['amount_due_cents']}"

    fx.set_clock(CLOCK_LATE)  # 2026-06-16 -> LATE active
    dv = fx.distance_version(distance["id"], headers)
    resp = api.confirm_payment(reg["id"], {"expected_distance_version": dv}, headers)
    confirmed = validate_success(resp)
    assert confirmed["amount_paid_cents"] == 7203, \
        f"final under LATE expected 7203, got {confirmed['amount_paid_cents']}"
    assert confirmed["amount_paid_cents"] != confirmed["amount_due_cents"], \
        "final amount_paid must diverge from provisional amount_due across a tier flip"


def test_amount_paid_matches_amount_due_when_tier_unchanged(api):
    """PRD §3.3: "the system captures the final charge into `amount_paid_cents`,
    recording the `processing_fee_cents` component, computed with the very same
    pinned pricing sequence as the provisional estimate but now using the
    confirm-time clock as the reference."

    Design: Difficulty/dual_variant_calc/amount_due_provisional_vs_final_diverges_on_tier_flip
    """
    # Same tier (REGULAR) at create and confirm: final equals provisional 5660.
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    reg = fx.create_registration(event, distance, wave, participant)
    confirmed = fx.confirm_registration(reg, distance, participant)
    assert confirmed["amount_paid_cents"] == 5660, \
        f"final under same tier expected 5660, got {confirmed['amount_paid_cents']}"
    assert confirmed["amount_paid_cents"] == confirmed["amount_due_cents"], \
        "with no tier flip, final amount_paid equals provisional amount_due"


# ---------------------------------------------------------------------------
# Refund pinned rounding order (difficulty: combinatorial_formula)
# ---------------------------------------------------------------------------
def test_refund_rounds_fee_component_before_subtracting(api):
    """PRD §3.4: "the net base is `amount_paid_cents` minus `processing_fee_cents`
    (the processing fee is never refunded), the cancellation fee is that net
    multiplied by the cancellation fee rate of 0.15 rounded half-up to a whole cent,
    and the refund is the net minus that independently-rounded fee."
    PRD §3.4: "The fee component is rounded first and then subtracted — the system
    does not subtract a fractional fee and round the whole refund afterward."

    Design: Difficulty/combinatorial_formula/refund_pinned_rounding_order_fee_component_first
    """
    # CONFIRMED with paid 4811, fee 136 (party2 + SPRING10 at REGULAR on MARATHON):
    # net=4675; fee=round_half_up(4675*0.15)=701; refund=3974.
    event, distance, wave = fx.setup_open_event(
        capacity_total=50, distance_label="MARATHON", distance_km=42.195)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant,
                                 party_size=2, promo_code="SPRING10")
    reg = fx.confirm_registration(reg, distance, participant)
    resp = api.cancel_registration(reg["id"], headers)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_cents"] == 3974, \
        f"expected refund_cents 3974, got {cancelled['refund_cents']}"


def test_refund_zero_for_pending_payment_cancel(api):
    """PRD §3.4: "if the registration was in `PENDING_PAYMENT` or `WAITLISTED` nothing
    was ever captured, so the refund is 0".

    Design: Difficulty/combinatorial_formula/refund_pinned_rounding_order_fee_component_first
    """
    event, distance, wave = fx.setup_open_event(capacity_total=50)
    participant = fx.create_participant()
    headers = make_participant_headers(participant["id"])
    reg = fx.create_registration(event, distance, wave, participant)  # PENDING_PAYMENT
    resp = api.cancel_registration(reg["id"], headers)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_cents"] == 0, \
        f"PENDING_PAYMENT cancel refund must be 0, got {cancelled['refund_cents']}"
