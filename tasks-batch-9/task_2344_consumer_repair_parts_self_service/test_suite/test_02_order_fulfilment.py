"""Fulfilment: the core-return settlement, cancellation compensation and the two
independent per-line service dimensions.
"""
import pytest

from test_helpers import (
    ADMIN,
    CUSTOMER,
    api_client,
    assert_core_ledger_aggregates,
    assert_core_ledger_balanced,
    fixtures,
    get_success_data,
)


def _read_line(line_id):
    return get_success_data(api_client.get_order_line(line_id, ADMIN))


# --------------------------------------------------------------------------- #
# A core-bearing order delivered and then settled eight days late
# --------------------------------------------------------------------------- #
def _delivered_core_order():
    """Two units of a core-required part, delivered, with the clock eight days past due."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-1000",
        product_family="CRX",
        market_release_date="2025-01-15T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(
        sku="SKU-BATT-CORE",
        list_price_cents=8000,
        core_return_required=True,
        core_credit_cents=2500,
    )
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=30
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-BATT-CORE"], safety_warning_count=4
    )
    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line = fixtures.append_line(order["id"], part["id"], 2, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    order = fixtures.confirm_order(order["id"], CUSTOMER)
    fixtures.deliver_order(order["id"])
    fixtures.move_clock("2026-09-08T00:00:00Z")
    return {"part": part, "order": order, "line": line}


def test_confirmation_holds_the_ungraded_core_face_value():
    """PRD §3.6: "On the core dimension, when any line's part has
    `core_return_required` true, `core_return_status` moves from `NOT_REQUIRED` to
    `PENDING_CORE`, `core_return_due_at` is set to `confirmed_at` plus thirty days,
    and `core_credit_provisional_cents` is stamped with the full core face value of
    the order — the sum, across core-required lines, of the part's
    `core_credit_cents` multiplied by the line's `quantity` — ungraded, with no
    condition grading and no lateness decay."

    Design: Difficulty/dual_variant_calc/core_credit_provisional_hold_vs_final_settlement_diverge
    """
    bundle = _delivered_core_order()
    order = fixtures.read_order(bundle["order"]["id"])

    assert order["parts_subtotal_cents"] == 16000, (
        f"Expected 2 x 8000 == 16000, got {order['parts_subtotal_cents']}"
    )
    assert order["documentation_fee_cents"] == 980, (
        f"Expected 500 + 120 x 4 warnings == 980, got {order['documentation_fee_cents']}"
    )
    assert order["core_deposit_cents"] == 5000, (
        f"Expected 2 x 2500 == 5000, got {order['core_deposit_cents']}"
    )
    assert order["total_due_cents"] == 21980, (
        f"Expected 16000 + 980 + 5000 == 21980, got {order['total_due_cents']}"
    )
    assert order["core_credit_provisional_cents"] == 5000, (
        f"Expected the ungraded face value 5000, got "
        f"{order['core_credit_provisional_cents']}"
    )
    assert order["core_return_due_at"].startswith("2026-08-31T00:00:00"), (
        f"Expected confirmation plus thirty days, got {order['core_return_due_at']}"
    )


def test_late_damaged_core_settles_below_the_provisional_hold():
    """PRD §3.7: "First, `core_days_late` is the number of whole days from the
    order's `core_return_due_at` to the recorded `received_at`, floored at zero."
    PRD §3.7: "Otherwise `core_credit_final_cents` is the face value multiplied by
    the condition multiplier and then by the lateness decay, rounded half up to
    whole cents, and the dimension continues from `CORE_RECEIVED` to
    `CORE_CREDIT_ISSUED`."

    Design: Difficulty/dual_variant_calc/core_credit_provisional_hold_vs_final_settlement_diverge
    """
    bundle = _delivered_core_order()
    order = fixtures.book_core_return(
        bundle["order"]["id"], "2026-09-08T00:00:00Z", "DAMAGED_SHELL"
    )

    assert order["core_days_late"] == 8, (
        f"Expected 8 whole days from 2026-08-31 to 2026-09-08, got {order['core_days_late']}"
    )
    assert order["core_credit_final_cents"] == 2100, (
        f"Expected 5000 x 0.70 x 0.60 == 2100, got {order['core_credit_final_cents']}"
    )
    assert order["core_credit_provisional_cents"] == 5000, (
        "the provisional hold is the audit record and never regrades, got "
        f"{order['core_credit_provisional_cents']}"
    )
    assert (
        order["core_credit_provisional_cents"] - order["core_credit_final_cents"] == 2900
    ), "the two variants must diverge by 2900 cents"
    assert order["core_return_status"] == "CORE_CREDIT_ISSUED", order["core_return_status"]
    assert order["fulfillment_status"] == "CLOSED", (
        f"a settled core dimension rolls the order up to CLOSED, got "
        f"{order['fulfillment_status']}"
    )


def test_core_settlement_splits_the_ledger_between_settled_and_forfeited():
    """PRD §3.7: "On a credit issue, each part's
    `core_liability_outstanding_cents` decreases by its face value while
    `core_credit_settled_cents` increases by the credited share and
    `core_credit_forfeited_cents` increases by the unpaid remainder."
    PRD §2.10: "For every `PartCatalogItem`, the sum of
    `core_liability_outstanding_cents`, `core_credit_settled_cents`, and
    `core_credit_forfeited_cents` must equal `core_face_value_committed_cents` at
    all times."

    Design: Difficulty/dual_variant_calc/core_credit_provisional_hold_vs_final_settlement_diverge
    """
    bundle = _delivered_core_order()
    fixtures.book_core_return(
        bundle["order"]["id"], "2026-09-08T00:00:00Z", "DAMAGED_SHELL"
    )

    part = fixtures.read_part(bundle["part"]["id"])
    assert_core_ledger_aggregates(
        part, committed=5000, outstanding=0, settled=2100, forfeited=2900
    )


# --------------------------------------------------------------------------- #
# Cancelling a confirmed core-bearing order
# --------------------------------------------------------------------------- #
def _confirmed_core_order():
    """Two units of a core-required part, confirmed and not yet delivered."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9700",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(
        sku="SKU-CORE-MOD",
        list_price_cents=8000,
        core_return_required=True,
        core_credit_cents=2500,
    )
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=40
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-CORE-MOD"], safety_warning_count=2
    )
    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line = fixtures.append_line(order["id"], part["id"], 2, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    order = fixtures.confirm_order(order["id"], CUSTOMER)
    return {"assessment": assessment, "part": part, "order": order, "line": line}


def test_cancellation_releases_the_core_dimension():
    """PRD §3.6: "Cancellation stores the reason and compensates fully: where
    `core_return_status` was `PENDING_CORE` it moves to `CORE_RELEASED`,
    `core_credit_provisional_cents` is reset to zero and `core_return_due_at` to
    null, and for every core-required line both that part's
    `core_liability_outstanding_cents` and its `core_face_value_committed_cents`
    decrease by the same face value, which is what keeps the conservation identity
    of §2.10 balanced."

    Design: Difficulty/compensating_invariant/order_cancellation_restores_the_core_liability_ledger_identity
    """
    bundle = _confirmed_core_order()
    assert bundle["order"]["total_due_cents"] == 21740, (
        f"Expected 16000 + 740 + 5000 == 21740 before the cancel, got "
        f"{bundle['order']['total_due_cents']}"
    )

    order = fixtures.cancel_order(bundle["order"]["id"], CUSTOMER)

    assert order["core_return_status"] == "CORE_RELEASED", order["core_return_status"]
    assert order["fulfillment_status"] == "CANCELLED", order["fulfillment_status"]
    assert order["core_credit_provisional_cents"] == 0, (
        f"Expected the provisional hold reset to zero, got "
        f"{order['core_credit_provisional_cents']}"
    )
    assert order["core_return_due_at"] is None, (
        f"Expected core_return_due_at cleared, got {order['core_return_due_at']}"
    )


def test_cancellation_moves_both_sides_of_the_core_ledger():
    """PRD §2.10: "Cancelling an order lowers *both* of those totals by the same
    amount — the compensation moves both sides, which is why a cancellation is not
    a settlement."
    PRD §3.6: "The pinned assessment stays `CONSUMED` — a cancellation never
    resurrects eligibility."

    Design: Difficulty/compensating_invariant/order_cancellation_restores_the_core_liability_ledger_identity
    """
    bundle = _confirmed_core_order()
    fixtures.cancel_order(bundle["order"]["id"], CUSTOMER)

    part = fixtures.read_part(bundle["part"]["id"])
    assert_core_ledger_aggregates(
        part, committed=0, outstanding=0, settled=0, forfeited=0
    )
    assert_core_ledger_balanced(part)

    assessment = fixtures.read_assessment(bundle["assessment"]["id"])
    assert assessment["status"] == "CONSUMED", (
        f"Expected the assessment to stay CONSUMED, got {assessment['status']}"
    )


# --------------------------------------------------------------------------- #
# Authentication and calibration advance independently on one line
# --------------------------------------------------------------------------- #
def _delivered_paired_and_calibrated_line():
    """A delivered line whose part needs both authentication and calibration."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-6000",
        product_family="CRX",
        market_release_date="2025-04-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(
        sku="SKU-PAIRED-CAM",
        list_price_cents=3000,
        requires_authentication=True,
        requires_calibration=True,
    )
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-05-01T00:00:00Z", install_minutes=35
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-PAIRED-CAM"], safety_warning_count=2
    )
    fixtures.publish_calibration_procedure(
        model["id"], ["SKU-PAIRED-CAM"], safety_warning_count=1
    )
    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line = fixtures.append_line(order["id"], part["id"], 1, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    fixtures.confirm_order(order["id"], CUSTOMER)
    order = fixtures.deliver_order(order["id"])
    lines = fixtures.list_lines(order["id"])
    return {"order": order, "line": line, "pairing_token": lines[0]["pairing_token"]}


def test_authentication_does_not_move_the_calibration_dimension():
    """PRD §3.7: "When the submitted token equals the token minted on the line at
    delivery, `authentication_status` becomes `AUTHENTIC`; when the part also
    requires calibration, the calibration dimension stays at
    `CALIBRATION_REQUIRED` and a successful authentication is simply what unblocks
    it."

    Design: Difficulty/non_linear_state_machine/order_line_authentication_and_calibration_dimensions_advance_independently
    """
    bundle = _delivered_paired_and_calibrated_line()
    line = fixtures.authenticate_line(
        bundle["order"]["id"],
        bundle["line"]["id"],
        bundle["pairing_token"],
        CUSTOMER,
    )

    assert line["authentication_status"] == "AUTHENTIC", line["authentication_status"]
    assert line["calibration_status"] == "CALIBRATION_REQUIRED", (
        "the calibration dimension must not move when authentication does, got "
        f"{line['calibration_status']}"
    )
    assert line["calibration_attempt_count"] == 0, (
        f"Expected no calibration attempt yet, got {line['calibration_attempt_count']}"
    )


def test_calibration_does_not_move_the_authentication_dimension():
    """PRD §3.7: "Either way `calibration_attempt_count` increments by one and
    `last_measured_offset_ppm` is stored, and the tolerance branch is then
    evaluated inside the same request."
    PRD §3.7: "An order rolls up from `DELIVERED` to the terminal `CLOSED` on its
    own, with no client request, as soon as two conditions hold together: every
    line has `authentication_status` in `NOT_REQUIRED` or `AUTHENTIC` and
    `calibration_status` in `NOT_REQUIRED` or `CALIBRATION_PASSED`, and the core
    dimension sits in `NOT_REQUIRED`, `CORE_CREDIT_ISSUED`, or `CORE_FORFEITED`."

    Design: Difficulty/non_linear_state_machine/order_line_authentication_and_calibration_dimensions_advance_independently
    """
    bundle = _delivered_paired_and_calibrated_line()
    fixtures.authenticate_line(
        bundle["order"]["id"],
        bundle["line"]["id"],
        bundle["pairing_token"],
        CUSTOMER,
    )
    line = fixtures.calibrate_line(
        bundle["order"]["id"], bundle["line"]["id"], 120, CUSTOMER
    )

    assert line["authentication_status"] == "AUTHENTIC", (
        f"the calibrate call must leave authentication alone, got "
        f"{line['authentication_status']}"
    )
    assert line["calibration_status"] == "CALIBRATION_PASSED", line["calibration_status"]
    assert line["calibration_attempt_count"] == 1, line["calibration_attempt_count"]
    assert line["last_measured_offset_ppm"] == 120, line["last_measured_offset_ppm"]

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["fulfillment_status"] == "CLOSED", order["fulfillment_status"]
    assert order["total_due_cents"] == 3740, (
        f"Expected 3000 + 740 == 3740, got {order['total_due_cents']}"
    )


# --------------------------------------------------------------------------- #
# The 150 ppm calibration tolerance boundary
# --------------------------------------------------------------------------- #
def _delivered_calibration_only_line():
    """A delivered line whose part needs calibration but no authentication."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-9000",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(
        sku="SKU-TORQUE-CELL", list_price_cents=2000, requires_calibration=True
    )
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=20
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-TORQUE-CELL"], safety_warning_count=2
    )
    fixtures.publish_calibration_procedure(
        model["id"], ["SKU-TORQUE-CELL"], safety_warning_count=1
    )
    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    line = fixtures.append_line(order["id"], part["id"], 1, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    fixtures.confirm_order(order["id"], CUSTOMER)
    order = fixtures.deliver_order(order["id"])
    return {"order": order, "line": line}


def test_calibration_passes_at_exactly_one_hundred_fifty_ppm():
    """PRD §3.7: "When the absolute value of the measured offset is at most 150
    parts per million — 150 exactly passes — the dimension continues to
    `CALIBRATION_PASSED`."

    Design: Difficulty/boundary_precision_check/calibration_tolerance_boundary_passes_at_exactly_150_ppm
    """
    bundle = _delivered_calibration_only_line()
    line = fixtures.calibrate_line(
        bundle["order"]["id"], bundle["line"]["id"], 150, CUSTOMER
    )

    assert line["calibration_status"] == "CALIBRATION_PASSED", (
        f"150 ppm sits on the inclusive tolerance bound, got {line['calibration_status']}"
    )
    assert line["calibration_attempt_count"] == 1, line["calibration_attempt_count"]
    assert line["last_measured_offset_ppm"] == 150, line["last_measured_offset_ppm"]


def test_calibration_only_line_closes_the_order_at_the_tolerance_bound():
    """PRD §3.6: "A successful append captures the part's authentication and
    calibration requirements onto the line — `authentication_status` and
    `calibration_status` both start at `NOT_REQUIRED` and stay there for a part
    that needs neither step — and re-runs the whole order's pricing."
    PRD §3.7: "An order rolls up from `DELIVERED` to the terminal `CLOSED` on its
    own, with no client request, as soon as two conditions hold together: every
    line has `authentication_status` in `NOT_REQUIRED` or `AUTHENTIC` and
    `calibration_status` in `NOT_REQUIRED` or `CALIBRATION_PASSED`, and the core
    dimension sits in `NOT_REQUIRED`, `CORE_CREDIT_ISSUED`, or `CORE_FORFEITED`."

    Design: Difficulty/boundary_precision_check/calibration_tolerance_boundary_passes_at_exactly_150_ppm
    """
    bundle = _delivered_calibration_only_line()
    fixtures.calibrate_line(bundle["order"]["id"], bundle["line"]["id"], 150, CUSTOMER)

    line = _read_line(bundle["line"]["id"])
    assert line["authentication_status"] == "NOT_REQUIRED", (
        f"the part does not require authentication, got {line['authentication_status']}"
    )

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["fulfillment_status"] == "CLOSED", order["fulfillment_status"]
    assert order["total_due_cents"] == 2740, (
        f"Expected 2000 + 740 == 2740, got {order['total_due_cents']}"
    )
