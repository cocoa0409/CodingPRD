"""Shape and domain-invariant assertions for every resource in the PRD.

Two layers live here:

* `assert_<resource>(data)` — structural checks: the declared fields are present,
  system fields have the right form, and the rounding scale of every numeric
  field matches the scale the PRD pins for it.
* domain invariant helpers — cross-field arithmetic that must hold on any
  correct implementation (component sums, credit arithmetic, quantity variants).
"""

import math

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import BAF, COMPLIANCE_SCORE, CREDIT_THRESHOLDS, SCALES

# Tolerances derived from the PRD's rounding scales (PRD §2.10).
MONEY_TOL = 0.005
TONNAGE_TOL = 0.0005
SULFUR_TOL = 0.0005
RATE_TOL = 0.00005


# ─── Generic helpers ──────────────────────────────────

def assert_fields_present(data, field_names):
    """Every named field must be present on the payload (value may be null)."""
    missing = [name for name in field_names if name not in data]
    assert not missing, f"missing fields on payload: {missing}; got keys {sorted(data)}"


def assert_decimal_scale(value, places, label):
    """The value must be representable at exactly the pinned decimal scale."""
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    scaled = value * (10 ** places)
    assert abs(scaled - round(scaled)) < 1e-6, (
        f"{label}={value!r} carries more than {places} decimal places"
    )


def assert_money(actual, expected, label="amount"):
    assert actual == pytest.approx(expected, abs=0.01), f"{label}: {actual} != {expected}"


def assert_tonnage(actual, expected, label="quantity"):
    assert actual == pytest.approx(expected, abs=0.001), f"{label}: {actual} != {expected}"


def assert_sulfur(actual, expected, label="sulfur_pct"):
    assert actual == pytest.approx(expected, abs=0.001), f"{label}: {actual} != {expected}"


def assert_rate(actual, expected, label="rate"):
    """For four-decimal rates: baf_pct and credit utilisation."""
    assert actual == pytest.approx(expected, abs=0.0001), f"{label}: {actual} != {expected}"


def assert_system_fields(data, versioned=True):
    """id and created_at on every resource; updated_at and version on all but
    the immutable index quote (PRD §2.5)."""
    assert is_valid_uuid(data["id"]), f"id is not a UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at is not ISO-8601: {data['created_at']!r}"
    )
    if versioned:
        assert is_iso8601_timestamp(data["updated_at"]), (
            f"updated_at is not ISO-8601: {data['updated_at']!r}"
        )
        assert isinstance(data["version"], int), f"version must be an integer: {data['version']!r}"
        assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


# ─── Reference data ───────────────────────────────────

PORT_FIELDS = [
    "id", "port_code", "name", "eca_zone", "eca_sulfur_limit_pct",
    "notice_lead_hours", "concurrent_ops_capacity", "spill_response_tier",
    "created_at", "updated_at", "version",
]


def assert_port(data):
    assert_fields_present(data, PORT_FIELDS)
    assert_system_fields(data)
    assert isinstance(data["eca_zone"], bool)
    assert isinstance(data["notice_lead_hours"], int)
    assert isinstance(data["concurrent_ops_capacity"], int)
    assert_decimal_scale(data["eca_sulfur_limit_pct"], SCALES["SULFUR"], "eca_sulfur_limit_pct")
    assert data["spill_response_tier"] in ("TIER_1", "TIER_2", "TIER_3")


FUEL_GRADE_FIELDS = [
    "id", "grade_code", "max_sulfur_pct", "eca_permitted", "test_tolerance_pct",
    "index_code", "base_barging_rate_usd_per_mt", "min_barging_fee_usd",
    "cross_contamination_group", "created_at", "updated_at", "version",
]


def assert_fuel_grade(data):
    assert_fields_present(data, FUEL_GRADE_FIELDS)
    assert_system_fields(data)
    assert isinstance(data["eca_permitted"], bool)
    assert_decimal_scale(data["max_sulfur_pct"], SCALES["SULFUR"], "max_sulfur_pct")
    assert_decimal_scale(data["test_tolerance_pct"], SCALES["SULFUR"], "test_tolerance_pct")
    assert_decimal_scale(data["min_barging_fee_usd"], SCALES["MONEY"], "min_barging_fee_usd")
    assert data["cross_contamination_group"] in ("DISTILLATE", "RESIDUAL", "BIOBLEND")


INDEX_QUOTE_FIELDS = [
    "id", "grade_id", "quote_date", "price_usd_per_mt", "source", "created_at",
]


def assert_index_quote(data):
    """An index quote is immutable: only id and created_at, no updated_at and no
    version (PRD §2.5)."""
    assert_fields_present(data, INDEX_QUOTE_FIELDS)
    assert_system_fields(data, versioned=False)
    assert is_valid_uuid(data["grade_id"])
    assert is_iso8601_timestamp(data["quote_date"])
    assert_decimal_scale(data["price_usd_per_mt"], SCALES["MONEY"], "price_usd_per_mt")
    assert data["source"] in ("PLATTS", "ARGUS")
    assert "updated_at" not in data, "an index quote must not carry updated_at"
    assert "version" not in data, "an index quote must not carry version"


CUSTOMER_FIELDS = [
    "id", "name", "credit_limit_usd", "payment_terms_days", "settlement_basis",
    "credit_status", "outstanding_balance_usd", "conservative_exposure_usd",
    "available_credit_usd", "open_commitment_count",
    "created_at", "updated_at", "version",
]


def assert_customer(data):
    assert_fields_present(data, CUSTOMER_FIELDS)
    assert_system_fields(data)
    assert isinstance(data["payment_terms_days"], int)
    assert isinstance(data["open_commitment_count"], int)
    assert data["settlement_basis"] in ("SUPPLIER_FIGURES", "JOINT_SURVEY_MANDATORY")
    assert data["credit_status"] in ("OK", "WATCH", "HOLD")
    for field in ("credit_limit_usd", "outstanding_balance_usd",
                  "conservative_exposure_usd", "available_credit_usd"):
        assert_decimal_scale(data[field], SCALES["MONEY"], field)


DELIVERY_ASSET_FIELDS = [
    "id", "name", "asset_type", "capacity_mt", "home_port_id", "boom_certified",
    "segregated_tanks", "turnaround_buffer_minutes", "last_grade_id", "status",
    "committed_quantity_mt", "compliance_score", "created_at", "updated_at", "version",
]


def assert_delivery_asset(data):
    assert_fields_present(data, DELIVERY_ASSET_FIELDS)
    assert_system_fields(data)
    assert data["asset_type"] in ("BARGE", "TRUCK")
    assert data["status"] in ("AVAILABLE", "QUARANTINED")
    assert isinstance(data["boom_certified"], bool)
    assert isinstance(data["segregated_tanks"], bool)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert_decimal_scale(data["capacity_mt"], SCALES["TONNAGE"], "capacity_mt")
    assert_decimal_scale(
        data["committed_quantity_mt"], SCALES["TONNAGE"], "committed_quantity_mt"
    )
    assert_compliance_score_in_range(data["compliance_score"])


def assert_compliance_score_in_range(score):
    """The score is clamped into the closed interval 0.00 to 100.00 (PRD §3.6)."""
    assert_decimal_scale(score, SCALES["MONEY"], "compliance_score")
    assert COMPLIANCE_SCORE["MIN"] <= score <= COMPLIANCE_SCORE["MAX"], (
        f"compliance_score {score} outside 0.00 to 100.00"
    )


# ─── Nominations and orders ───────────────────────────

NOMINATION_FIELDS = [
    "id", "customer_id", "port_id", "grade_id", "vessel_imo", "vessel_name",
    "scrubber_fitted", "nominated_quantity_mt", "declared_sulfur_pct",
    "delivery_mode", "window_start", "window_end", "eca_documentation_ref",
    "fulfillment_status", "compliance_status", "compliance_reviewer_user_id",
    "created_at", "updated_at", "version",
]

NOMINATION_COMPLIANCE_STATES = ("PENDING_REVIEW", "APPROVED", "REJECTED")
NOMINATION_FULFILLMENT_STATES = (
    "DRAFT", "CONFIRMED", "SCHEDULED", "AWAITING_SCHEDULE", "DELIVERED", "CLOSED",
)


def assert_nomination(data):
    assert_fields_present(data, NOMINATION_FIELDS)
    assert_system_fields(data)
    assert data["compliance_status"] in NOMINATION_COMPLIANCE_STATES
    assert data["fulfillment_status"] in NOMINATION_FULFILLMENT_STATES
    assert data["delivery_mode"] in ("BARGE", "TRUCK")
    assert isinstance(data["scrubber_fitted"], bool)
    assert_decimal_scale(
        data["nominated_quantity_mt"], SCALES["TONNAGE"], "nominated_quantity_mt"
    )
    assert_decimal_scale(data["declared_sulfur_pct"], SCALES["SULFUR"], "declared_sulfur_pct")
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])


def assert_nomination_state(data, compliance_status, fulfillment_status):
    """The two dimensions advance independently (PRD §2.6), so assert both."""
    assert data["compliance_status"] == compliance_status, (
        f"compliance_status {data['compliance_status']} != {compliance_status}"
    )
    assert data["fulfillment_status"] == fulfillment_status, (
        f"fulfillment_status {data['fulfillment_status']} != {fulfillment_status}"
    )


DELIVERY_ORDER_FIELDS = [
    "id", "nomination_id", "asset_id", "planned_quantity_mt", "slot_start",
    "slot_end", "logistics_status", "measurement_status", "port_clearance_ref",
    "cleared_at", "barge_sounding_mt", "vessel_sounding_mt", "meter_mt",
    "surveyed_mt", "agreed_quantity_mt", "measurement_basis", "shortfall_mt",
    "created_at", "updated_at", "version",
]

ORDER_LOGISTICS_STATES = (
    "SCHEDULED", "CLEARED", "PUMPING", "DELIVERED", "SUSPENDED", "CANCELLED",
)
ORDER_MEASUREMENT_STATES = (
    "NOT_STARTED", "FIGURES_RECORDED", "RESURVEYED", "AGREED", "DISPUTED",
)


def assert_delivery_order(data):
    assert_fields_present(data, DELIVERY_ORDER_FIELDS)
    assert_system_fields(data)
    assert data["logistics_status"] in ORDER_LOGISTICS_STATES
    assert data["measurement_status"] in ORDER_MEASUREMENT_STATES
    assert_decimal_scale(
        data["planned_quantity_mt"], SCALES["TONNAGE"], "planned_quantity_mt"
    )
    assert is_iso8601_timestamp(data["slot_start"])
    assert is_iso8601_timestamp(data["slot_end"])
    if data["measurement_basis"] is not None:
        assert data["measurement_basis"] in ("SUPPLIER_FIGURES", "JOINT_SURVEY")
    for field in ("barge_sounding_mt", "vessel_sounding_mt", "meter_mt",
                  "surveyed_mt", "agreed_quantity_mt", "shortfall_mt"):
        if data[field] is not None:
            assert_decimal_scale(data[field], SCALES["TONNAGE"], field)


def assert_order_state(data, logistics_status, measurement_status):
    """The logistics and measurement dimensions advance independently (PRD §2.6)."""
    assert data["logistics_status"] == logistics_status, (
        f"logistics_status {data['logistics_status']} != {logistics_status}"
    )
    assert data["measurement_status"] == measurement_status, (
        f"measurement_status {data['measurement_status']} != {measurement_status}"
    )


def assert_slot_end_from_quantity(order, planned_quantity_mt):
    """Auto-scheduled slot length: pumping time at 250 mt/hour rounded up to the
    whole minute plus a 60-minute hose allowance (PRD §3.4)."""
    expected_minutes = math.ceil(planned_quantity_mt / 250 * 60) + 60
    start = _parse_instant(order["slot_start"])
    end = _parse_instant(order["slot_end"])
    actual_minutes = round((end - start).total_seconds() / 60)
    assert actual_minutes == expected_minutes, (
        f"slot spans {actual_minutes} minutes, expected {expected_minutes}"
    )


def _parse_instant(text):
    from datetime import datetime
    return datetime.strptime(text.replace(".000Z", "Z"), "%Y-%m-%dT%H:%M:%SZ")


# ─── Delivery notes, claims and analyses ──────────────

BDN_FIELDS = [
    "id", "delivery_order_id", "bdn_number", "declared_sulfur_pct",
    "sample_seal_number", "delivered_quantity_mt", "status", "issued_by_user_id",
    "sample_retention_until", "sample_custody_status", "sample_released_at",
    "created_at", "updated_at", "version",
]


def assert_bunker_delivery_note(data):
    assert_fields_present(data, BDN_FIELDS)
    assert_system_fields(data)
    assert data["status"] in ("ISSUED", "SUPERSEDED")
    assert data["sample_custody_status"] in ("RETAINED", "RELEASED_TO_LAB", "EXPIRED")
    assert_decimal_scale(
        data["delivered_quantity_mt"], SCALES["TONNAGE"], "delivered_quantity_mt"
    )
    assert_decimal_scale(data["declared_sulfur_pct"], SCALES["SULFUR"], "declared_sulfur_pct")
    assert is_iso8601_timestamp(data["sample_retention_until"])


QUALITY_CLAIM_FIELDS = [
    "id", "bdn_id", "customer_id", "claimed_defect", "affected_quantity_mt",
    "quantity_basis_mt", "replacement_price_usd_per_mt", "status", "analysis_round",
    "credit_usd", "remediation_type", "proposed_by_user_id", "accepted_by_user_id",
    "created_at", "updated_at", "version",
]

CLAIM_STATES = (
    "SUBMITTED", "UNDER_ANALYSIS", "REMEDIATION_PROPOSED",
    "REMEDIATION_ACCEPTED", "REJECTED",
)


def assert_quality_claim(data):
    assert_fields_present(data, QUALITY_CLAIM_FIELDS)
    assert_system_fields(data)
    assert data["status"] in CLAIM_STATES
    assert data["claimed_defect"] in (
        "SULFUR_EXCEEDANCE", "WATER_CONTENT", "DENSITY_DEVIATION",
    )
    assert isinstance(data["analysis_round"], int)
    assert_decimal_scale(
        data["affected_quantity_mt"], SCALES["TONNAGE"], "affected_quantity_mt"
    )
    assert_decimal_scale(
        data["quantity_basis_mt"], SCALES["TONNAGE"], "quantity_basis_mt"
    )
    assert_decimal_scale(data["credit_usd"], SCALES["MONEY"], "credit_usd")
    if data["remediation_type"] is not None:
        assert data["remediation_type"] in ("PRICE_ALLOWANCE", "DEBUNKER")


LAB_ANALYSIS_FIELDS = [
    "id", "claim_id", "lab_ref", "measured_sulfur_pct", "retest_of_analysis_id",
    "round_index", "verdict", "exceedance_pct", "analyzed_by_user_id",
    "created_at", "updated_at", "version",
]


def assert_lab_analysis(data):
    assert_fields_present(data, LAB_ANALYSIS_FIELDS)
    assert_system_fields(data)
    assert data["verdict"] in ("ON_SPEC", "OFF_SPEC")
    assert isinstance(data["round_index"], int)
    assert_decimal_scale(data["measured_sulfur_pct"], SCALES["SULFUR"], "measured_sulfur_pct")
    assert_decimal_scale(data["exceedance_pct"], SCALES["SULFUR"], "exceedance_pct")
    assert data["exceedance_pct"] >= 0, "exceedance_pct is never negative"


# ─── Invoices ─────────────────────────────────────────

INVOICE_FIELDS = [
    "id", "delivery_order_id", "customer_id", "pricing_date", "quantity_basis_mt",
    "index_price_usd_per_mt", "baf_pct", "fuel_cost_usd", "baf_usd",
    "barging_fee_usd", "eca_surcharge_usd", "provisional_amount_usd",
    "claim_credit_usd", "final_amount_usd", "status", "issued_at", "due_date",
    "created_at", "updated_at", "version",
]

INVOICE_STATES = ("PROVISIONAL", "ISSUED", "CREDIT_APPLIED", "VOID")


def assert_invoice(data):
    assert_fields_present(data, INVOICE_FIELDS)
    assert_system_fields(data)
    assert data["status"] in INVOICE_STATES
    assert_decimal_scale(data["quantity_basis_mt"], SCALES["TONNAGE"], "quantity_basis_mt")
    assert_decimal_scale(data["baf_pct"], SCALES["BAF_PCT"], "baf_pct")
    for field in ("index_price_usd_per_mt", "fuel_cost_usd", "baf_usd",
                  "barging_fee_usd", "eca_surcharge_usd", "provisional_amount_usd",
                  "claim_credit_usd", "final_amount_usd"):
        assert_decimal_scale(data[field], SCALES["MONEY"], field)


def assert_baf_pct_within_band(baf_pct):
    """The composed factor is clamped into the band before it is rounded to four
    decimal places (PRD §3.9)."""
    assert BAF["FLOOR"] - 1e-9 <= baf_pct <= BAF["CEILING"] + 1e-9, (
        f"baf_pct {baf_pct} outside the 0.010 to 0.045 band"
    )


def assert_provisional_is_component_sum(invoice):
    """Each component is rounded to two decimal places first and the already
    rounded components are then added (PRD §2.10)."""
    total = (
        invoice["fuel_cost_usd"]
        + invoice["baf_usd"]
        + invoice["barging_fee_usd"]
        + invoice["eca_surcharge_usd"]
    )
    assert_money(
        invoice["provisional_amount_usd"], round(total, 2), "provisional_amount_usd"
    )


def assert_final_is_provisional_less_credit(invoice):
    """The final amount is the provisional amount less the booked claim credit
    (PRD §3.8, §3.9)."""
    assert_money(
        invoice["final_amount_usd"],
        round(invoice["provisional_amount_usd"] - invoice["claim_credit_usd"], 2),
        "final_amount_usd",
    )


# ─── Spill incidents ──────────────────────────────────

SPILL_FIELDS = [
    "id", "delivery_order_id", "asset_id", "port_id", "reported_at",
    "volume_liters", "boom_deployed", "severity", "penalty_points", "status",
    "containment_confirmed", "response_ref", "closed_at",
    "created_at", "updated_at", "version",
]


def assert_spill_incident(data):
    assert_fields_present(data, SPILL_FIELDS)
    assert_system_fields(data)
    assert data["severity"] in ("MINOR", "MAJOR")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["boom_deployed"], bool)
    assert isinstance(data["containment_confirmed"], bool)
    assert_decimal_scale(data["volume_liters"], SCALES["MONEY"], "volume_liters")
    assert_decimal_scale(data["penalty_points"], SCALES["MONEY"], "penalty_points")


# ─── Credit exposure read model ───────────────────────

# The credit-exposure endpoint is a computed read over the customer projection
# (PRD §3.2), so it carries the same five computed fields as the customer record.
CREDIT_EXPOSURE_FIELDS = CUSTOMER_FIELDS


def assert_credit_exposure(data):
    assert_customer(data)


def assert_conservative_is_settled_plus_open(exposure, open_commitments_usd):
    """The conservative figure is the settled receivables plus the open
    commitments (PRD §3.2)."""
    assert_money(
        exposure["conservative_exposure_usd"],
        round(exposure["outstanding_balance_usd"] + open_commitments_usd, 2),
        "conservative_exposure_usd",
    )


def assert_available_is_limit_less_conservative(exposure):
    """Available credit is the limit less the conservative exposure (PRD §3.2)."""
    assert_money(
        exposure["available_credit_usd"],
        round(exposure["credit_limit_usd"] - exposure["conservative_exposure_usd"], 2),
        "available_credit_usd",
    )


def assert_credit_status_from_settled(exposure):
    """Standing comes from the settled figure alone: utilisation to four decimal
    places, HOLD at or above 1.0000, WATCH at or above 0.8000, else OK
    (PRD §3.2)."""
    utilisation = round(
        exposure["outstanding_balance_usd"] / exposure["credit_limit_usd"], 4
    )
    if utilisation >= CREDIT_THRESHOLDS["HOLD_UTILISATION"]:
        expected = "HOLD"
    elif utilisation >= CREDIT_THRESHOLDS["WATCH_UTILISATION"]:
        expected = "WATCH"
    else:
        expected = "OK"
    assert exposure["credit_status"] == expected, (
        f"utilisation {utilisation} should give {expected}, got {exposure['credit_status']}"
    )


# ─── Envelope and ordering helpers ────────────────────

def assert_created_at_ascending(items):
    """The default ordering is by created_at ascending (PRD §2.3)."""
    stamps = [item["created_at"] for item in items]
    assert stamps == sorted(stamps), f"items are not in created_at ascending order: {stamps}"


def assert_quote_date_descending(items):
    """Index quotes under a grade come back newest quote_date first (PRD §2.3)."""
    stamps = [item["quote_date"] for item in items]
    assert stamps == sorted(stamps, reverse=True), (
        f"quotes are not in quote_date descending order: {stamps}"
    )


def assert_unchanged(before, after, fields):
    """None of the named fields moved — used to prove a rejected call had no
    partial effect."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} changed from {before[field]!r} to {after[field]!r}"
        )


def assert_version_unchanged(before, after):
    assert after["version"] == before["version"], (
        f"version moved from {before['version']} to {after['version']}"
    )


__all__ = [
    "MONEY_TOL",
    "TONNAGE_TOL",
    "SULFUR_TOL",
    "RATE_TOL",
    "assert_fields_present",
    "assert_decimal_scale",
    "assert_money",
    "assert_tonnage",
    "assert_sulfur",
    "assert_rate",
    "assert_system_fields",
    "assert_port",
    "assert_fuel_grade",
    "assert_index_quote",
    "assert_customer",
    "assert_delivery_asset",
    "assert_compliance_score_in_range",
    "assert_nomination",
    "assert_nomination_state",
    "assert_delivery_order",
    "assert_order_state",
    "assert_slot_end_from_quantity",
    "assert_bunker_delivery_note",
    "assert_quality_claim",
    "assert_lab_analysis",
    "assert_invoice",
    "assert_baf_pct_within_band",
    "assert_provisional_is_component_sum",
    "assert_final_is_provisional_less_credit",
    "assert_spill_incident",
    "assert_credit_exposure",
    "assert_conservative_is_settled_plus_open",
    "assert_available_is_limit_less_conservative",
    "assert_credit_status_from_settled",
    "assert_created_at_ascending",
    "assert_quote_date_descending",
    "assert_unchanged",
    "assert_version_unchanged",
    "PORT_FIELDS",
    "FUEL_GRADE_FIELDS",
    "INDEX_QUOTE_FIELDS",
    "CUSTOMER_FIELDS",
    "DELIVERY_ASSET_FIELDS",
    "NOMINATION_FIELDS",
    "DELIVERY_ORDER_FIELDS",
    "BDN_FIELDS",
    "QUALITY_CLAIM_FIELDS",
    "LAB_ANALYSIS_FIELDS",
    "INVOICE_FIELDS",
    "SPILL_FIELDS",
    "CREDIT_EXPOSURE_FIELDS",
]
