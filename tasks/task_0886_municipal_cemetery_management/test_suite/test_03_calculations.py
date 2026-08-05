"""Interment service fee composition, round-then-sum tax, marker foundation fee."""
from test_helpers import (
    validate_success, get_success_data,
    setup_scheduled_interment, setup_issued_deed, api_client,
    create_marker_permit_payload, TEST_USERS,
)

REG = TEST_USERS["registrar_headers"]
FIN = TEST_USERS["finance_officer_headers"]

# depth-2 GRAVE, scheduled 2026-05-02 (Sat) with clock at 2026-05-01 (Fri):
# base 90000 + depth 15000 + weekend 20000 + short-notice 25000 = 150000.
WEEKEND_SHORT_NOTICE = dict(
    depth_position=2, scheduled_date="2026-05-02",
    scheduled_start="2026-05-02T09:00:00Z", scheduled_end="2026-05-02T11:00:00Z",
    clock="2026-05-01T00:00:00Z",
)


# ── Difficulty: combinatorial_formula / interment_service_fee_tiered_composition ──

def test_service_fee_sums_all_four_components(api):
    """PRD §3.3: "The four components are summed to the final fee" — base 90,000 for
    GRAVE, depth surcharge 15,000 cents when it is exactly 2, a WEEKEND adds 20,000
    cents, and "The short-notice surcharge of 25,000 cents applies when the number of
    whole days from the current logical-clock date to the scheduled_date is strictly
    less than 3".

    Design: Difficulty/combinatorial_formula/interment_service_fee_tiered_composition
    """
    r = setup_scheduled_interment(**WEEKEND_SHORT_NOTICE)
    assert r["interment"]["service_fee_cents"] == 150000


def test_service_fee_day_type_weekend(api):
    """PRD §3.3: "The day surcharge derives from day_type, which is HOLIDAY when
    scheduled_date falls on one of the recognized holidays (2026-01-01, 2026-07-04,
    2026-11-26, 2026-12-25), WEEKEND when it falls on a Saturday or Sunday, and WEEKDAY
    otherwise"

    Design: Difficulty/combinatorial_formula/interment_service_fee_tiered_composition
    """
    r = setup_scheduled_interment(**WEEKEND_SHORT_NOTICE)
    assert r["interment"]["day_type"] == "WEEKEND"


# ── Difficulty: combinatorial_formula / invoice_tax_round_per_line_then_sum ──

def test_interment_invoice_tax_round_per_line_then_sum(api):
    """PRD §2.6: "for each taxable line, multiply its amount_cents by the tax rate of
    7.25% (0.0725) and round that product half-up to a whole cent, then sum those
    per-line rounded amounts". PRD §2.6: "An INTERMENT_SERVICE invoice has one taxable
    line per non-zero component of the service fee".

    Design: Difficulty/combinatorial_formula/invoice_tax_round_per_line_then_sum
    """
    r = setup_scheduled_interment(**WEEKEND_SHORT_NOTICE)
    invoice = validate_success(api.get_invoice(r["service_invoice_id"], FIN), 200)
    assert invoice["subtotal_cents"] == 150000
    assert invoice["tax_cents"] == 10876


def test_interment_invoice_total_reflects_per_line_rounding(api):
    """PRD §2.6: "The total_cents is subtotal_cents plus tax_cents. Because rounding
    happens per line before summing, an invoice composed of several small taxable
    lines can total a cent differently from one taxable line of the same subtotal —
    this is intentional and must be preserved."

    Design: Difficulty/combinatorial_formula/invoice_tax_round_per_line_then_sum
    """
    r = setup_scheduled_interment(**WEEKEND_SHORT_NOTICE)
    invoice = validate_success(api.get_invoice(r["service_invoice_id"], FIN), 200)
    assert invoice["total_cents"] == 160876


# ── Corner: calculations / interment_fee_weekday_base_only ──

def test_weekday_depth_one_future_fee_base_only(api):
    """PRD §3.3: "The depth surcharge is 0 when depth_position is 1"; a WEEKDAY adds
    no day surcharge and "The short-notice surcharge of 25,000 cents applies when the
    number of whole days from the current logical-clock date to the scheduled_date is
    strictly less than 3, and is otherwise 0."

    Design: Corner/calculations/interment_fee_weekday_base_only
    """
    r = setup_scheduled_interment(depth_position=1, scheduled_date="2026-06-01",
                                  scheduled_start="2026-06-01T09:00:00Z",
                                  scheduled_end="2026-06-01T11:00:00Z",
                                  clock="2026-05-01T00:00:00Z")
    assert r["interment"]["service_fee_cents"] == 90000
    assert r["interment"]["day_type"] == "WEEKDAY"


# ── Corner: calculations / marker_foundation_fee_flat_lookup ──

def test_flat_marker_foundation_fee_and_invoice_total(api):
    """PRD §3.5: "its foundation_fee_cents is computed from marker_type — 15,000 cents
    for FLAT, 30,000 for UPRIGHT, and 60,000 for MONUMENT". PRD §2.6: "A
    MARKER_FOUNDATION invoice has a single taxable foundation line for
    foundation_fee_cents."

    Design: Corner/calculations/marker_foundation_fee_flat_lookup
    """
    r = setup_issued_deed()
    permit = validate_success(api.create_marker_permit(
        create_marker_permit_payload(r["plot"]["id"], r["deed"]["id"], marker_type="FLAT"), REG), 201)
    assert permit["foundation_fee_cents"] == 15000
    invoice = validate_success(api.get_invoice(permit["foundation_invoice_id"], FIN), 200)
    assert invoice["total_cents"] == 16088
