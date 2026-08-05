"""Booking price snapshotting at creation and cancellation-refund dual variants."""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, fixtures,
)

PM = TEST_USERS["property_manager_headers"]


def _listed_with_guest(api, base=20000, cleaning=15000, tax=10):
    fixtures.set_clock(api, "2026-06-01T00:00:00Z")
    listed = fixtures.create_listed_property(api, base_nightly_rate_cents=base,
                                             cleaning_fee_cents=cleaning, occupancy_tax_pct=tax)
    guest = fixtures.create_guest(api)
    return listed["property"]["id"], guest["id"]


def test_booking_total_tax_computation_correct(api):
    """PRD §3.4: "locks the dynamic per-night rate into `quoted_per_night_cents` and the
    `nightly_subtotal_cents`, snapshots the property's cleaning fee into
    `quoted_cleaning_fee_cents`, computes `occupancy_tax_cents` as the taxable base (nightly
    subtotal plus cleaning fee) multiplied by the active permit's `occupancy_tax_pct` divided
    by one hundred and rounded half-up ..., and sets `total_cents` to the sum of nightly
    subtotal, cleaning fee, and occupancy tax."

    Design: Corner/calculations/booking_total_tax_computation_correct
    """
    pid, gid = _listed_with_guest(api)
    resp = api.create_booking(
        {"property_id": pid, "guest_id": gid, "check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"},
        PM)
    data = validate_success(resp, 201)
    assert data["nightly_subtotal_cents"] == 60000, f"got {data['nightly_subtotal_cents']}"
    assert data["occupancy_tax_cents"] == 7500, f"got {data['occupancy_tax_cents']}"
    assert data["total_cents"] == 82500, f"got {data['total_cents']}"


def test_booking_computed_fields_visible_same_request(api):
    """PRD §3.4: "On successful creation the server computes and snapshots the full price."
    PRD §3.4: "and sets `total_cents` to the sum of nightly subtotal, cleaning fee, and
    occupancy tax."

    Design: Corner/consistency_model/booking_create_computed_fields_visible_same_request
    """
    pid, gid = _listed_with_guest(api)
    resp = api.create_booking(
        {"property_id": pid, "guest_id": gid, "check_in": "2026-07-01T00:00:00Z", "check_out": "2026-07-04T00:00:00Z"},
        PM)
    data = validate_success(resp, 201)
    assert data["quoted_per_night_cents"] == 20000, f"got {data['quoted_per_night_cents']}"
    assert data["total_cents"] == 82500, f"got {data['total_cents']}"


def test_refund_flexible_full_refund_diverges(api):
    """PRD §3.5: "Under `FLEXIBLE`, a cancellation at least one day before check-in refunds
    the full one hundred percent, otherwise nothing."
    PRD §3.5: "The final `refund_cents` is the sum of the refundable nightly amount, the
    cleaning refund, and the tax refund."

    Design: Difficulty/dual_variant_calc/refund_flexible_vs_moderate_diverge
    """
    pid, gid = _listed_with_guest(api)
    b = fixtures.create_booking(api, pid, gid, "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z",
                                cancellation_policy="FLEXIBLE")
    fixtures.set_clock(api, "2026-06-02T00:00:00Z")  # 29 days before check-in
    data = get_success_data(api.cancel_booking(b["id"], PM))
    assert data["refund_cents"] == 82500, f"expected full 82500, got {data['refund_cents']}"
    assert data["stay_status"] == "CANCELLED"


def test_refund_moderate_half_refund_diverges(api):
    """PRD §3.5: "Under `MODERATE`, a cancellation at least thirty days out refunds fully,
    one at least seven days out (but fewer than thirty) refunds fifty percent, and anything
    under seven days refunds nothing — so for identical timing `MODERATE` can pay out far
    less than `FLEXIBLE`."

    Design: Difficulty/dual_variant_calc/refund_flexible_vs_moderate_diverge
    """
    pid, gid = _listed_with_guest(api)
    b = fixtures.create_booking(api, pid, gid, "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z",
                                cancellation_policy="MODERATE")
    fixtures.set_clock(api, "2026-08-03T00:00:00Z")  # 29 days before check-in => 50%
    data = get_success_data(api.cancel_booking(b["id"], PM))
    # nightly 30000 + cleaning 15000 + tax 3750 = 48750
    assert data["refund_cents"] == 48750, f"expected 48750, got {data['refund_cents']}"


def test_moderate_refund_at_30day_boundary_is_full(api):
    """PRD §3.5: "Under `MODERATE`, a cancellation at least thirty days out refunds fully".
    PRD §3.5: "The system computes days-to-check-in as the floored whole-day difference
    between `check_in` and the current logical clock, then selects a refund percentage with
    inclusive (at-or-greater-than) boundaries."

    Design: Difficulty/boundary_precision_check/moderate_refund_30day_inclusive_boundary
    """
    pid, gid = _listed_with_guest(api)
    b = fixtures.create_booking(api, pid, gid, "2026-07-01T00:00:00Z", "2026-07-04T00:00:00Z",
                                cancellation_policy="MODERATE")
    # clock stays 2026-06-01: exactly 30 days before check-in => full
    data = get_success_data(api.cancel_booking(b["id"], PM))
    assert data["refund_cents"] == 82500, f"expected full 82500 at 30-day boundary, got {data['refund_cents']}"


def test_moderate_refund_at_29days_is_half(api):
    """PRD §3.5: "one at least seven days out (but fewer than thirty) refunds fifty percent".
    PRD §3.5: "The refundable nightly portion is the `nightly_subtotal_cents` times the
    refund percentage, rounded half-up".

    Design: Difficulty/boundary_precision_check/moderate_refund_30day_inclusive_boundary
    """
    pid, gid = _listed_with_guest(api)
    b = fixtures.create_booking(api, pid, gid, "2026-09-01T00:00:00Z", "2026-09-04T00:00:00Z",
                                cancellation_policy="MODERATE")
    fixtures.set_clock(api, "2026-08-03T00:00:00Z")  # 29 days => 50%
    data = get_success_data(api.cancel_booking(b["id"], PM))
    assert data["refund_cents"] == 48750, f"expected 48750 at 29 days, got {data['refund_cents']}"
