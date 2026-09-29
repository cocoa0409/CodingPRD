"""Pinned arithmetic on the distribution side of the contract.

Chargeback tiers read from the pre-event diversion score, the two
diversion-exposure attribution theories and their rounding order, the chargeback
ledger's treatment of reversed and upheld rows, the reseller review predicate and
the product open-exception counter.  Every figure is re-derived from an
independent oracle and compared against the pinned literal.
"""
from prd_bench_local_runner.testing import validate_success

from test_helpers import COUNSEL_HEADERS, api_client
from test_helpers.assertions import (
    round_half_up,
    score_delta,
    standing_for_score,
    tier_rate_for_score,
)
from test_helpers.constants import EVIDENCE_HASH_1, EVIDENCE_HASH_3
from test_helpers.factories import (
    chargeback_dispute_decision_payload,
    chargeback_dispute_payload,
    exception_decision_payload,
)
from test_helpers.fixtures import (
    approve_exception,
    assess_chargeback,
    capture_observation,
    capture_purchase_serial,
    confirm_unauthorized,
    create_authorized_reseller,
    create_distributor,
    create_product,
    create_published_policy,
    create_serial_unit,
    order_test_purchase,
    pin_clock,
    read_chargeback,
    read_distributor,
    read_exception,
    read_exposure,
    read_product,
    read_reseller,
    read_serial_unit,
    request_exception,
    ship_unit_downstream,
)
from test_helpers.test_users import make_distributor_headers

CLOCK_AUG_01 = "2026-08-01T00:00:00Z"
CLOCK_AUG_20 = "2026-08-20T00:00:00Z"
OBSERVED_AUG_18 = "2026-08-18T00:00:00Z"
OBSERVED_AUG_19 = "2026-08-19T00:00:00Z"

STANDARD_FLOOR = 15000
MSRP = 20000
SKU_AUDIO = "SKU-AUDIO-1"

WINDOW_STARTS = "2026-08-10T00:00:00Z"
ADJACENT_SPLIT = "2026-08-20T00:00:00Z"
ADJACENT_ENDS = "2026-08-30T00:00:00Z"
MARKETING_PLAN = "BRAND_MARKETING_PLAN"

CAP_CENTS = 500000


# --------------------------------------------------------------------------- #
# Shared setup
# --------------------------------------------------------------------------- #
def _setup_catalogue():
    """One published policy effective 2026-08-01 and one 15000-floor product."""
    pin_clock(CLOCK_AUG_01)
    policy = create_published_policy(CLOCK_AUG_01)
    product = create_product(
        policy["id"],
        sku=SKU_AUDIO,
        name="Studio Headphones",
        msrp_cents=MSRP,
        standard_map_floor_cents=STANDARD_FLOOR,
    )
    return {"policy": policy, "product": product}


def _setup_authorized_channel():
    """The catalogue plus Acme Retail AUTHORIZED on an ACTIVE marketplace agreement."""
    world = _setup_catalogue()
    reseller, agreement = create_authorized_reseller(
        world["policy"]["id"],
        reseller_overrides={
            "legal_name": "Acme Retail LLC",
            "contact_email": "ops@acme.example",
            "primary_channel": "MARKETPLACE",
        },
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    world["reseller"] = reseller
    world["agreement"] = agreement
    pin_clock(CLOCK_AUG_20)
    return world


def _setup_traced_unit(extra_units=(), serial_number="SN-0001"):
    """Register LOT-A units to Northwind, then trace one through a grey listing.

    ``extra_units`` is a sequence of ``(serial_number, distributor_key)`` pairs
    registered alongside the traced unit.
    """
    world = _setup_catalogue()
    world["distributor"] = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=CAP_CENTS
    )
    world["units"] = {
        serial_number: create_serial_unit(
            world["product"]["id"],
            world["distributor"]["id"],
            serial_number=serial_number,
            lot_code="LOT-A",
        )
    }
    for extra_serial, distributor_key in extra_units:
        if distributor_key == "second" and "second_distributor" not in world:
            world["second_distributor"] = create_distributor(
                legal_name="Southpaw Supply Co", annual_chargeback_cap_cents=CAP_CENTS
            )
        owner = world["distributor"] if distributor_key == "first" else world["second_distributor"]
        world["units"][extra_serial] = create_serial_unit(
            world["product"]["id"],
            owner["id"],
            serial_number=extra_serial,
            lot_code="LOT-A",
        )

    pin_clock(CLOCK_AUG_20)
    world["grey_observation"] = capture_observation(
        world["product"]["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    purchase = order_test_purchase(
        world["grey_observation"]["id"],
        ordered_at=OBSERVED_AUG_19,
        purchase_price_cents=9000,
    )
    capture_purchase_serial(purchase["id"], serial_number)
    world["purchase"] = confirm_unauthorized(
        purchase["id"], outcome_reason="Seller has no agreement on file"
    )
    return world


# --------------------------------------------------------------------------- #
# Chargeback assessment
# --------------------------------------------------------------------------- #
def test_the_first_chargeback_prices_at_the_tier_the_score_had_before_it():
    """Four units bill at 2500 even though the resulting 10.0 score is one tier up.

    PRD: "Take the distributor's `diversion_score` as it stands *before* this event.
    The `tier_rate_cents_per_unit` is 2500 cents when that pre-event score is
    strictly below 10.0, 4000 cents when it is at or above 10.0 but strictly below
    25.0, and 6000 cents when it is at or above 25.0 — twenty-five, forty and sixty
    dollars a unit, with both tier boundaries inclusive at the lower bound."

    Design: Corner/calculations/chargeback_first_assessment_uses_the_pre_increment_tier
    """
    world = _setup_traced_unit()
    chargeback = assess_chargeback(
        world["distributor"]["id"], world["purchase"]["id"], diverted_units=4
    )

    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(0.0) == 2500
    assert chargeback["amount_cents"] == 2500 * 4 == 10000
    assert chargeback["score_delta_applied"] == score_delta(4) == 10.0

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 10000
    assert distributor["diversion_score"] == 10.0
    assert distributor["standing"] == standing_for_score(10.0) == "PROBATION"


def test_the_second_chargeback_reads_the_higher_tier_at_the_inclusive_bound():
    """A pre-event score of exactly 10.0 prices six units at 4000 each.

    PRD: "The `tier_rate_cents_per_unit` is 2500 cents when that pre-event score is
    strictly below 10.0, 4000 cents when it is at or above 10.0 but strictly below
    25.0, and 6000 cents when it is at or above 25.0 — twenty-five, forty and sixty
    dollars a unit, with both tier boundaries inclusive at the lower bound."

    Design: Corner/calculations/chargeback_second_assessment_moves_up_a_tier
    """
    world = _setup_traced_unit()
    assess_chargeback(world["distributor"]["id"], world["purchase"]["id"], diverted_units=4)

    second_unit = create_serial_unit(
        world["product"]["id"],
        world["distributor"]["id"],
        serial_number="SN-0003",
        lot_code="LOT-A",
    )
    second_observation = capture_observation(
        world["product"]["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals Two",
        listing_url="https://mkt.example/l/10",
        listed_price_cents=9500,
        observed_at=OBSERVED_AUG_19,
        evidence_hash=EVIDENCE_HASH_3,
    )
    second_purchase = order_test_purchase(
        second_observation["id"], ordered_at=OBSERVED_AUG_19, purchase_price_cents=9500
    )
    capture_purchase_serial(second_purchase["id"], second_unit["serial_number"])
    confirm_unauthorized(
        second_purchase["id"], outcome_reason="Second grey storefront confirmed"
    )

    chargeback = assess_chargeback(
        world["distributor"]["id"], second_purchase["id"], diverted_units=6
    )
    assert chargeback["tier_rate_cents_per_unit"] == tier_rate_for_score(10.0) == 4000
    assert chargeback["amount_cents"] == 4000 * 6 == 24000
    assert chargeback["score_delta_applied"] == score_delta(6) == 15.0

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 34000
    assert distributor["diversion_score"] == 25.0
    assert distributor["standing"] == standing_for_score(25.0) == "SUSPENDED"


def test_the_score_delta_is_two_and_a_half_points_for_a_single_unit():
    """One diverted unit costs 2500 cents and 2.5 score points, leaving GOOD standing.

    PRD: "The `score_delta_applied` is two and a half score points per diverted
    unit."

    Design: Corner/calculations/chargeback_score_delta_is_two_and_a_half_per_unit
    """
    world = _setup_traced_unit()
    chargeback = assess_chargeback(
        world["distributor"]["id"], world["purchase"]["id"], diverted_units=1
    )

    assert chargeback["amount_cents"] == 2500 * 1 == 2500
    assert chargeback["score_delta_applied"] == score_delta(1) == 2.5

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["diversion_score"] == 2.5
    assert distributor["standing"] == standing_for_score(2.5) == "GOOD"


# --------------------------------------------------------------------------- #
# Diversion exposure
# --------------------------------------------------------------------------- #
def test_the_two_attribution_theories_diverge_on_a_lot_split_across_distributors():
    """Full attribution charges the whole unit; proration charges three fifths of it.

    PRD: "Otherwise count all units of that lot in any custody state, and count the
    units of that lot whose `shipped_distributor_id` is this distributor in any
    custody state, and add to the running tally the lot's traced count multiplied by
    this distributor's shipped count, divided by the lot's total shipped count,
    rounded half up to two decimal places."

    Design: Corner/calculations/diversion_exposure_variants_diverge_on_a_shared_lot
    """
    world = _setup_traced_unit(
        extra_units=(
            ("SN-0003", "first"),
            ("SN-0004", "first"),
            ("SN-0005", "second"),
            ("SN-0006", "second"),
        )
    )

    attributed = read_exposure(world["distributor"]["id"], "TRACE_ATTRIBUTED")
    assert attributed["traced_unit_count"] == 1
    assert attributed["units_counted"] == 1
    assert attributed["tier_rate_cents_per_unit"] == tier_rate_for_score(0.0) == 2500
    assert attributed["exposure_cents"] == 2500 * 1 == 2500

    prorated = read_exposure(world["distributor"]["id"], "LOT_PRORATED")
    assert prorated["units_counted"] == round_half_up(1 * 3 / 5, 2) == 0.60
    assert prorated["tier_rate_cents_per_unit"] == 2500
    assert prorated["exposure_cents"] == round_half_up(2500 * 0.60) == 1500


def test_the_two_theories_reconcile_when_one_distributor_owns_the_whole_lot():
    """A proration factor of three thirds collapses onto full attribution.

    PRD: "A distributor that received six of a lot's ten units therefore carries six
    tenths of that lot's traced units."

    Design: Corner/calculations/diversion_exposure_variants_reconcile_on_a_single_distributor_lot
    """
    world = _setup_traced_unit(
        extra_units=(("SN-0003", "first"), ("SN-0004", "first"))
    )

    attributed = read_exposure(world["distributor"]["id"], "TRACE_ATTRIBUTED")
    assert attributed["units_counted"] == 1
    assert attributed["exposure_cents"] == 2500

    prorated = read_exposure(world["distributor"]["id"], "LOT_PRORATED")
    assert prorated["units_counted"] == round_half_up(1 * 3 / 3, 2) == 1.00
    assert prorated["exposure_cents"] == round_half_up(2500 * 1.00) == 2500


def test_a_lot_with_nothing_traced_is_skipped_before_any_division():
    """Registered but untraced units yield zeros on every reported figure.

    PRD: "For each lot, count the units of that lot in state `TRACED_UNAUTHORIZED`
    across *all* distributors; if that count is zero, skip the lot without performing
    any division."

    Design: Corner/calculations/diversion_exposure_empty_pool_returns_zero_without_dividing
    """
    world = _setup_catalogue()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=CAP_CENTS
    )
    create_serial_unit(
        world["product"]["id"], distributor["id"], serial_number="SN-0001", lot_code="LOT-A"
    )

    exposure = read_exposure(distributor["id"], "LOT_PRORATED")
    assert exposure["traced_unit_count"] == 0
    assert exposure["units_counted"] == 0
    assert exposure["exposure_cents"] == 0
    assert exposure["diversion_score"] == 0
    assert exposure["tier_rate_cents_per_unit"] == tier_rate_for_score(0.0) == 2500


def test_the_per_lot_share_is_rounded_to_two_decimals_before_the_tier_applies():
    """Two thirds becomes 0.67 units, so the exposure is 1675 rather than 1667.

    PRD: "Once every lot is folded in, the exposure is the per-unit rate multiplied
    by the accumulated tally, rounded half up once to whole cents at the very end."

    Design: Corner/calculations/diversion_exposure_lot_proration_rounds_to_two_decimals
    """
    world = _setup_traced_unit(
        extra_units=(("SN-0003", "first"), ("SN-0005", "second"))
    )

    exposure = read_exposure(world["distributor"]["id"], "LOT_PRORATED")
    assert exposure["traced_unit_count"] == 1
    assert exposure["units_counted"] == round_half_up(1 * 2 / 3, 2) == 0.67
    assert exposure["exposure_cents"] == round_half_up(2500 * 0.67) == 1675


# --------------------------------------------------------------------------- #
# The distributor chargeback ledger
# --------------------------------------------------------------------------- #
def _dispute(world, chargeback_id):
    return validate_success(
        api_client.dispute_chargeback(
            chargeback_id,
            chargeback_dispute_payload(),
            make_distributor_headers(world["distributor"]["id"]),
        )
    )


def test_a_reversed_chargeback_leaves_both_ledgers_but_keeps_its_own_figures():
    """The row still reports 10000 and 10.0 while the distributor is back to zero.

    PRD: "A `REVERSED` chargeback keeps its historical `amount_cents` and
    `score_delta_applied` on the row for audit but contributes to neither sum."

    Design: Corner/calculations/chargeback_ledger_excludes_reversed_rows_but_keeps_their_history
    """
    world = _setup_traced_unit()
    chargeback = assess_chargeback(
        world["distributor"]["id"], world["purchase"]["id"], diverted_units=4
    )
    _dispute(world, chargeback["id"])
    validate_success(
        api_client.decide_chargeback_dispute(
            chargeback["id"],
            chargeback_dispute_decision_payload(
                "REVERSE", decision_reason="Theft substantiated"
            ),
            COUNSEL_HEADERS,
        )
    )

    row = read_chargeback(chargeback["id"])
    assert row["status"] == "REVERSED"
    assert row["amount_cents"] == 10000
    assert row["score_delta_applied"] == 10.0

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 0
    assert distributor["diversion_score"] == 0
    assert distributor["standing"] == standing_for_score(0.0) == "GOOD"


def test_an_upheld_chargeback_stays_inside_the_balance_and_the_score():
    """Surviving a dispute changes the status and nothing in either sum.

    PRD: "A `decision` of `UPHOLD` moves it `DISPUTED → UPHELD`: `dispute_rounds` is
    increased by one, `decision_reason` is recorded, the chargeback's `version` is
    advanced, and both ledgers are left exactly as they are — the `amount_cents`
    stays in the distributor's balance and the `score_delta_applied` stays in its
    diversion score."

    Design: Corner/calculations/chargeback_ledger_keeps_upheld_rows_inside_the_balance
    """
    world = _setup_traced_unit()
    chargeback = assess_chargeback(
        world["distributor"]["id"], world["purchase"]["id"], diverted_units=4
    )
    _dispute(world, chargeback["id"])
    validate_success(
        api_client.decide_chargeback_dispute(
            chargeback["id"],
            chargeback_dispute_decision_payload(
                "UPHOLD",
                decision_reason="Chain-of-custody records contradict the transit claim",
            ),
            COUNSEL_HEADERS,
        )
    )

    assert read_chargeback(chargeback["id"])["status"] == "UPHELD"

    distributor = read_distributor(world["distributor"]["id"])
    assert distributor["chargeback_balance_cents"] == 10000
    assert distributor["diversion_score"] == 10.0
    assert distributor["standing"] == standing_for_score(10.0) == "PROBATION"


# --------------------------------------------------------------------------- #
# The reseller review predicate
# --------------------------------------------------------------------------- #
def test_a_traced_downstream_unit_alone_raises_the_review_flag():
    """The second disjunct fires even with no sourcing distributor declared.

    PRD: "A reseller's `review_required` flag is a predicate rather than a sum: it is
    true when either the reseller declares a sourcing distributor whose `standing` is
    `PROBATION` or `SUSPENDED`, or at least one serialized unit whose
    `downstream_reseller_id` is this reseller has been traced to an unauthorized
    seller."

    Design: Corner/calculations/review_required_true_from_a_traced_downstream_unit_alone
    """
    world = _setup_authorized_channel()
    pin_clock(CLOCK_AUG_01)
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=CAP_CENTS
    )
    unit = create_serial_unit(
        world["product"]["id"], distributor["id"], serial_number="SN-0002", lot_code="LOT-A"
    )
    ship_unit_downstream(unit["id"], distributor["id"], world["reseller"]["id"])

    pin_clock(CLOCK_AUG_20)
    observation = capture_observation(
        world["product"]["id"],
        channel="MARKETPLACE",
        seller_display_name="GreyBox Deals",
        listing_url="https://mkt.example/l/9",
        listed_price_cents=9000,
        observed_at=OBSERVED_AUG_18,
        evidence_hash=EVIDENCE_HASH_1,
    )
    purchase = order_test_purchase(
        observation["id"], ordered_at=OBSERVED_AUG_19, purchase_price_cents=9000
    )
    capture_purchase_serial(purchase["id"], "SN-0002")
    confirm_unauthorized(
        purchase["id"], outcome_reason="Storefront is not an authorized reseller"
    )

    reseller = read_reseller(world["reseller"]["id"])
    assert reseller["sourcing_distributor_id"] is None
    assert reseller["review_required"] is True
    assert read_serial_unit(unit["id"])["status"] == "TRACED_UNAUTHORIZED"
    assert read_distributor(distributor["id"])["standing"] == "GOOD"


def test_neither_disjunct_holds_for_a_good_distributor_and_an_untraced_unit():
    """Declaring a sourcing distributor is not by itself a reason for review.

    PRD: "Only the reseller's own declared sourcing distributor is consulted for the
    first clause; units shipped by any other distributor can only matter through the
    second clause."

    Design: Corner/calculations/review_required_stays_false_when_neither_disjunct_holds
    """
    world = _setup_catalogue()
    distributor = create_distributor(
        legal_name="Northwind Distribution", annual_chargeback_cap_cents=CAP_CENTS
    )
    reseller, _agreement = create_authorized_reseller(
        world["policy"]["id"],
        reseller_overrides={
            "legal_name": "Acme Retail LLC",
            "contact_email": "ops@acme.example",
            "primary_channel": "MARKETPLACE",
            "sourcing_distributor_id": distributor["id"],
        },
        agreement_overrides={"permitted_channels": ["MARKETPLACE", "OWN_WEBSITE"]},
    )
    unit = create_serial_unit(
        world["product"]["id"], distributor["id"], serial_number="SN-0002", lot_code="LOT-A"
    )
    shipped = ship_unit_downstream(unit["id"], distributor["id"], reseller["id"])

    assert shipped["status"] == "SHIPPED_TO_RESELLER"
    stored = read_reseller(reseller["id"])
    assert stored["review_required"] is False
    assert stored["sourcing_distributor_id"] == distributor["id"]
    assert read_distributor(distributor["id"])["standing"] == "GOOD"


# --------------------------------------------------------------------------- #
# The product open-exception counter
# --------------------------------------------------------------------------- #
def test_only_approved_exceptions_are_counted_as_open_on_the_product():
    """A rejected leg and a fresh request both stay outside the counter.

    PRD: "A product's `open_exception_count` equals the count of that product's
    pricing exceptions in status `APPROVED`. Exceptions in `REQUESTED`, `REJECTED`,
    `EXPIRED` or `VOIDED` are excluded, and the count is recomputed on every
    approval, expiry and voiding."

    Design: Corner/calculations/open_exception_count_counts_approved_exceptions_only
    """
    world = _setup_catalogue()
    approved_leg = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=WINDOW_STARTS,
        ends_at=ADJACENT_SPLIT,
        channel_scope="PHYSICAL_RETAIL",
        requested_override_floor_cents=13000,
        dealer_input_source=MARKETING_PLAN,
    )
    approve_exception(approved_leg["id"], decision_reason="First promo leg approved")

    rejected_leg = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at=ADJACENT_SPLIT,
        ends_at=ADJACENT_ENDS,
        channel_scope="PHYSICAL_RETAIL",
        requested_override_floor_cents=14000,
        dealer_input_source=MARKETING_PLAN,
    )
    validate_success(
        api_client.decide_exception(
            rejected_leg["id"],
            exception_decision_payload("REJECT", decision_reason="Second leg not funded"),
            COUNSEL_HEADERS,
        )
    )

    fresh = request_exception(
        world["product"]["id"],
        exception_type="PROMOTIONAL_EVENT",
        starts_at="2026-09-01T00:00:00Z",
        ends_at="2026-09-10T00:00:00Z",
        channel_scope="MARKETPLACE",
        requested_override_floor_cents=13500,
        dealer_input_source=MARKETING_PLAN,
    )

    assert read_exception(approved_leg["id"])["status"] == "APPROVED"
    assert read_exception(rejected_leg["id"])["status"] == "REJECTED"
    assert read_exception(fresh["id"])["status"] == "REQUESTED"
    assert read_product(world["product"]["id"])["open_exception_count"] == 1
