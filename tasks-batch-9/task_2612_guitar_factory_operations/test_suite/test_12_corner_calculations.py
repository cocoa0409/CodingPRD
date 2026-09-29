"""
Arithmetic at its ordinary settings: the per-cut kerf charge, the input set a
provisional quote is summed over, a playability score whose every term clamps to
zero, the minted serial, the first-tier customs fee and the standard warranty.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U

INSIDE_SPEC = {
    "action_mm_treble": 1.60,
    "action_mm_bass": 2.20,
    "relief_mm": 0.25,
    "intonation_cents_max": 4.0,
}


def a_serialized_standard_instrument(api, env):
    """
    The plain order at the inspection bench measured exactly at every ceiling,
    signed off by a second pair of eyes, and issued its serial number.
    """
    F.measure_inspection(api, env["insp1"], dict(INSIDE_SPEC), U.LUTHIER_HEADERS)
    F.sign_inspection(api, env["insp1"], U.INSPECTOR_HEADERS)
    return F.assign_serial(api, env["bo1"], U.COORDINATOR_HEADERS)


def test_a_single_cut_is_charged_the_per_cut_kerf_not_the_whole_lot_allowance(api, lot_released):
    """
    The three-percent sawdust charge on this one cut is an order of magnitude
    larger than the thirty-basis-point whole-lot allowance the receipt projection
    assumed, so the standing wood falls by the billet plus its own kerf.

    PRD: "`kerf_loss_board_feet` is the sawdust charged against the lot for this
    particular cut: multiply the billet's `board_feet` by 300 basis points, divide
    by 10000, and round half up to two decimal places — a three-percent per-cut
    allowance, an order of magnitude larger than the 30-basis-point whole-lot
    allowance the nominal projection assumes, which is exactly why the two yield
    figures diverge in practice."

    Design: Corner/calculations/billet_cut_charges_actual_kerf_per_cut_and_moves_the_ledger
    """
    billet = F.create_billet(api, lot_released["lot1"], lot_released["lot_v1"],
                             billet_code="BLT-001", board_feet=30.00, grade="AAA")
    assert billet["kerf_loss_board_feet"] == 0.90
    assert billet["status"] == "AVAILABLE"

    lot = validate_success(
        api.get_tonewood_lot(lot_released["lot1"], U.WOOD_BUYER_HEADERS))
    A.assert_lot_ledger(lot, available=69.10, unassigned=30.00, reserved=0.00,
                        consumed=0.00, scrapped=0.00, kerf_loss=0.90)
    assert lot["board_feet_cut"] == 30.00
    assert lot["status"] == "RELEASED"
    A.assert_wood_conserved(lot)


def test_the_two_yield_figures_stand_apart_after_the_first_cut(api, lot_released):
    """
    The realised figure is the wood actually sawn with no shrinkage deducted,
    because the lot now reads drier than target and the allowance clamps, while
    the receipt projection stays frozen on the wet reading taken at delivery.

    PRD: "Both lean on the same shrinkage helper: a lot's shrinkage allowance in
    basis points is the amount by which its moisture reading exceeds the 8.0
    percent target, clamped at zero so that wood drier than target is never
    credited with negative loss, multiplied by 45 basis points per percentage
    point of excess."

    Design: Corner/calculations/billet_cut_charges_actual_kerf_per_cut_and_moves_the_ledger
    """
    F.create_billet(api, lot_released["lot1"], lot_released["lot_v1"],
                    billet_code="BLT-001", board_feet=30.00, grade="AAA")

    lot = validate_success(
        api.get_tonewood_lot(lot_released["lot1"], U.WOOD_BUYER_HEADERS))
    assert lot["actual_yield_board_feet"] == 30.00
    assert lot["nominal_yield_board_feet"] == 97.90
    assert lot["moisture_content_pct"] == 7.0
    assert lot["moisture_at_receipt_pct"] == 12.0


def test_rejecting_a_line_drops_it_out_of_the_forward_looking_total(api, order_two_options):
    """
    Two unapproved options both price into the forward-looking total; refusing
    one drops that row out of the input set and the total falls by exactly that
    line, while the refused row keeps its own priced amount for the audit trail.

    PRD: "**`provisional_quote_total_cents`** is forward-looking: its input set is
    every selection on the order whose status is `PENDING_APPROVAL` or `SELECTED`,
    and it reads each option's unit upcharge live from the catalog row at
    evaluation time."

    Design: Corner/calculations/provisional_quote_excludes_a_rejected_option_selection
    """
    env = order_two_options
    before = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert before["provisional_quote_total_cents"] == 345910

    rejected = F.reject_selection(api, env["selG"],
                                  "customer dropped the gold hardware",
                                  U.COORDINATOR_HEADERS)
    assert rejected["status"] == "REJECTED"
    assert rejected["line_total_cents"] == 29705

    kept = validate_success(api.get_option_selection(env["selD"], U.COORDINATOR_HEADERS))
    assert kept["status"] == "PENDING_APPROVAL"
    assert kept["line_total_cents"] == 16205

    after = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    assert after["provisional_quote_total_cents"] == 316205
    assert after["binding_quote_total_cents"] is None


def test_a_measurement_exactly_at_every_ceiling_scores_nothing_at_all(api, order_at_inspection):
    """
    A guitar set up precisely on all four specification limits earns a score of
    zero rather than a small positive remainder, because every term is a
    one-sided excess and all four bounds are inclusive.

    PRD: "Because each clamp is one-sided, a measurement exactly at its
    specification limit contributes exactly zero, and a guitar set up tighter
    than specification on one dimension earns no credit against another dimension
    that is out of specification."

    Design: Corner/calculations/deviation_score_is_zero_when_every_measurement_is_inside_spec
    """
    env = order_at_inspection
    measured = F.measure_inspection(api, env["insp1"], dict(INSIDE_SPEC),
                                    U.LUTHIER_HEADERS)
    assert measured["deviation_score"] == 0.00
    A.assert_decimal_2dp(measured["deviation_score"], "deviation_score")

    signed = F.sign_inspection(api, env["insp1"], U.INSPECTOR_HEADERS)
    assert signed["status"] == "SIGNED"
    assert signed["verdict"] == "PASS"
    assert signed["inspector_user_id"] == U.INSPECTOR_HEADERS["X-User-ID"]

    order = validate_success(api.get_build_order(env["bo1"], U.COORDINATOR_HEADERS))
    A.assert_order_state(order, build_stage="INSPECTION",
                         commercial_status="OPTIONS_LOCKED")
    assert order["rework_round_count"] == 0


def test_the_serial_is_minted_from_the_model_the_logical_year_and_a_padded_sequence(api, order_at_inspection):
    """
    The first instrument of its model in this year takes sequence one, padded to
    five digits, with the year read off the logical clock the shop is running on
    rather than off wall-clock time.

    PRD: "For a `model_code` of `OM45` at 2026-08-22T09:00:00Z with no `OM45`
    serials issued in 2026, the serial is `OM45-2026-00001`; the next `OM45`
    serialized in 2026 is `OM45-2026-00002`, while the first `D28` of that year is
    `D28-2026-00001`."

    Design: Corner/calculations/serial_number_is_minted_per_model_and_year_and_applies_the_deposit
    """
    serialized = a_serialized_standard_instrument(api, order_at_inspection)

    assert serialized["serial_number"] == "OM45-2026-00001"
    A.assert_order_state(serialized, build_stage="SERIALIZED",
                         commercial_status="INVOICED")


def test_serialization_applies_the_held_deposit_against_the_binding_price(api, order_at_inspection):
    """
    The same request that mints the serial closes the fiscal loop, moving the
    smaller of the held balance and the binding price out of held and into
    applied, which leaves nothing held and the four buckets still adding up.

    PRD: "And the deposit is applied against the binding price:
    `deposit_applied_cents` rises by the smaller of `deposit_held_cents` and
    `binding_quote_total_cents`, and `deposit_held_cents` falls by that same
    amount."

    Design: Corner/calculations/serial_number_is_minted_per_model_and_year_and_applies_the_deposit
    """
    serialized = a_serialized_standard_instrument(api, order_at_inspection)

    assert serialized["binding_quote_total_cents"] == 300000
    A.assert_deposit_ledger(serialized, paid=100000, applied=100000, refunded=0,
                            forfeited=0, held=0)
    A.assert_money_conserved(serialized)


def test_a_three_hundred_thousand_cent_shipment_is_priced_at_the_first_tier_rate(api, order_at_inspection):
    """
    The goods value sits under the first ceiling, so the highest rate applies and
    lands well above the flat floor, which therefore does not bind; the insurance
    is then charged on the goods plus that fee.

    PRD: "**Step three** sets `doc_fee_cents` to the larger of the tier-rate fee —
    `goods_value_cents` multiplied by the tier's rate in basis points (150 for the
    first tier, 110 for the second, 80 for the third), divided by 10000 and rounded
    half up — and a floor of 3000 cents, and then adds 12500 cents when
    `cites_permit_required` is true."

    Design: Corner/calculations/export_fees_use_the_tier_1_rate_with_no_cites_endorsement
    """
    a_serialized_standard_instrument(api, order_at_inspection)

    shipment = F.create_shipment(api, order_at_inspection["bo1"], "JP")
    assert shipment["status"] == "DOCS_PENDING"
    assert shipment["cites_permit_required"] is False
    assert shipment["required_cites_appendix"] == "NONE"
    assert shipment["goods_value_cents"] == 300000
    assert shipment["doc_fee_cents"] == 4500
    assert shipment["insurance_cents"] == 2741
    assert shipment["declared_value_cents"] == 307241


def test_a_file_with_no_permit_number_is_accepted_when_no_listed_wood_contributed(api, order_at_inspection):
    """
    The only wood in this instrument is unlisted, so the shipment needs no
    endorsement and the customs file may be handed in with the permit field left
    out altogether.

    PRD: "When `cites_permit_required` is true the request must carry a non-empty
    `cites_permit_number` of 1 to 40 characters, otherwise
    `ERR_CITES_PERMIT_MISSING`; when the contributing lots include no CITES-listed
    wood at all, `cites_permit_required` is false and the permit number may be
    omitted entirely."

    Design: Corner/calculations/export_fees_use_the_tier_1_rate_with_no_cites_endorsement
    """
    a_serialized_standard_instrument(api, order_at_inspection)
    shipment = F.create_shipment(api, order_at_inspection["bo1"], "JP")

    attached = F.attach_docs(api, shipment["id"])
    assert attached["status"] == "DOCS_ATTACHED"
    assert attached["doc_fee_cents"] == 4500
    assert attached["insurance_cents"] == 2741
    assert attached["declared_value_cents"] == 307241


def test_a_standard_instrument_is_covered_for_twenty_four_calendar_months(api, order_at_inspection):
    """
    The window is read off the instrument rather than the shop: a build that is
    not custom shop takes the shorter term, and the end date is the purchase day
    two whole calendar years on rather than a day-count approximation.

    PRD: "`coverage_ends_at` is the `purchase_date` advanced by that many whole
    calendar months, expressed at `00:00:00Z` — calendar months, never thirty-day
    approximations — and clamped to the last valid day of the target month when the
    source day does not exist there."

    Design: Corner/calculations/standard_build_warranty_covers_twenty_four_calendar_months
    """
    serialized = a_serialized_standard_instrument(api, order_at_inspection)
    assert serialized["is_custom_shop"] is False

    shop = F.create_shop(api, F.shop_payload(shop_code="SHP-1",
                                             shop_name="Kanto Fret Works",
                                             country_code="JP"))
    F.authorize_shop(api, shop["id"], "FULL_SERVICE")

    registration = F.create_registration(api, order_at_inspection["bo1"], shop["id"],
                                         "OM45-2026-00001",
                                         purchase_date="2026-08-16T00:00:00Z")
    assert registration["status"] == "ACTIVE"
    assert registration["coverage_months"] == 24
    assert registration["coverage_ends_at"] == "2028-08-16T00:00:00Z"
    assert registration["serial_number"] == "OM45-2026-00001"


def test_registering_the_instrument_counts_against_the_registering_shop(api, order_at_inspection):
    """
    The tally on the shop is the number of live registrations it holds, so the
    first active row it books takes that count from nothing to one.

    PRD: "The registration opens in status `ACTIVE`, and the registering shop's
    `warranty_claim_count` reflects the count of its `ACTIVE` registrations."

    Design: Corner/calculations/standard_build_warranty_covers_twenty_four_calendar_months
    """
    a_serialized_standard_instrument(api, order_at_inspection)
    shop = F.create_shop(api, F.shop_payload(shop_code="SHP-1",
                                             shop_name="Kanto Fret Works",
                                             country_code="JP"))
    F.authorize_shop(api, shop["id"], "FULL_SERVICE")

    before = validate_success(api.get_repair_shop(shop["id"], U.SERVICE_MANAGER_HEADERS))
    assert before["warranty_claim_count"] == 0

    F.create_registration(api, order_at_inspection["bo1"], shop["id"],
                          "OM45-2026-00001", purchase_date="2026-08-16T00:00:00Z")

    after = validate_success(api.get_repair_shop(shop["id"], U.SERVICE_MANAGER_HEADERS))
    assert after["warranty_claim_count"] == 1
