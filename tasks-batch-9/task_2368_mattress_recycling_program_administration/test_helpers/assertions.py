"""Entity assertions and domain invariant checkers for the recycling program API."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import AVG_UNIT_WEIGHT_KG


# ---------------------------------------------------------------------------
# Common shape helpers
# ---------------------------------------------------------------------------


def assert_common_fields(data: dict):
    """id, created_at, updated_at and version, as carried by every resource
    except the append-only load inspection."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601, got {data.get('created_at')}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601, got {data.get('updated_at')}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer starting at 1, got {data.get('version')}"
    )


def assert_state_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["enforcement_posture"] in ("NORMAL", "ELEVATED")
    for money_field in (
        "fee_collected_cents",
        "site_credit_paid_cents",
        "hauler_payment_paid_cents",
        "reserve_balance_cents",
        "receivable_cents",
        "recommended_rate_cents",
        "reserve_opening_cents",
    ):
        assert isinstance(
            data[money_field], int
        ), f"{money_field} must be whole cents (integer), got {data[money_field]!r}"
    assert isinstance(data["reserve_coverage_months"], (int, float))
    assert_program_ledger_invariants(data)


def assert_fee_rate_schedule(data: dict):
    assert_common_fields(data)
    assert data["unit_class"] in ("MATTRESS", "FOUNDATION")
    assert data["status"] in ("PROPOSED", "APPROVED", "ACTIVE", "SUPERSEDED")
    assert isinstance(data["fee_cents_per_unit"], int) and data["fee_cents_per_unit"] >= 1
    assert is_iso8601_timestamp(data["effective_from"])
    if data.get("effective_to") is not None:
        assert is_iso8601_timestamp(data["effective_to"])
    assert isinstance(data["recommended_rate_cents_at_proposal"], int)
    assert isinstance(data["band_low_cents"], int)
    assert isinstance(data["band_high_cents"], int)


def assert_registrant(data: dict):
    assert_common_fields(data)
    assert data["registrant_type"] in ("MANUFACTURER", "RETAILER", "BOTH")
    assert data["compliance_status"] in ("COMPLIANT", "DELINQUENT", "SUSPENDED")
    assert isinstance(data["delinquent_balance_cents"], int)
    assert isinstance(data["takeback_breach_count"], int)


def assert_sales_remittance(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "DRAFT",
        "FILED",
        "PAID",
        "UNDER_AUDIT",
        "AMENDMENT_REQUIRED",
        "AUDIT_CLOSED",
        "REFUNDED",
    )
    assert isinstance(data["period_code"], str) and len(data["period_code"]) == 6
    assert isinstance(data["units_sold_mattress"], int)
    assert isinstance(data["units_sold_foundation"], int)
    assert isinstance(data["amendment_round"], int) and 0 <= data["amendment_round"] <= 2
    assert isinstance(data["early_filing_qualified"], bool)
    for money_field in (
        "fee_self_assessed_cents",
        "fee_paid_cents",
        "fee_refunded_cents",
        "balance_due_cents",
    ):
        assert isinstance(
            data[money_field], int
        ), f"{money_field} must be whole cents (integer), got {data[money_field]!r}"


def assert_exemption_claim(data: dict):
    assert_common_fields(data)
    assert data["claim_type"] in ("EXEMPT_SALE", "OUT_OF_STATE_SHIPMENT")
    assert data["unit_class"] in ("MATTRESS", "FOUNDATION")
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert data["status"] in ("PENDING", "SUBSTANTIATED", "DISALLOWED")


def assert_collection_site(data: dict):
    assert_common_fields(data)
    assert data["site_type"] in (
        "COLLECTION_SITE",
        "TRANSFER_STATION",
        "PERMANENT_DROPOFF",
    )
    assert data["enrollment_status"] in ("APPLIED", "ENROLLED", "SUSPENDED")
    assert isinstance(data["contamination_strike_count"], int)
    for bucket in (
        "units_on_hand",
        "units_in_transit",
        "units_at_recycler_count",
        "units_recycled_count",
        "units_written_off_count",
        "units_reported_total",
    ):
        assert isinstance(data[bucket], int) and data[bucket] >= 0, (
            f"{bucket} must be a non-negative integer, got {data[bucket]!r}"
        )
    assert_custody_conservation(data)


def assert_volume_report(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("SUBMITTED", "ACCEPTED")
    assert isinstance(data["units_mattress"], int)
    assert isinstance(data["units_foundation"], int)
    assert isinstance(data["credited_units"], int)
    assert isinstance(data["credit_cents"], int)


def assert_hauler(data: dict):
    assert_common_fields(data)
    assert isinstance(data["service_regions"], list) and data["service_regions"]
    assert isinstance(data["per_unit_rate_cents"], int)
    assert isinstance(data["per_km_rate_cents"], int)
    assert isinstance(data["max_route_payment_cents"], int)
    assert isinstance(data["max_concurrent_routes"], int)
    assert isinstance(data["active_route_count"], int)
    assert isinstance(data["total_paid_cents"], int)


def assert_recycler(data: dict):
    assert_common_fields(data)
    assert data["certification_status"] in ("PROVISIONAL", "CERTIFIED", "SUSPENDED")
    assert isinstance(data["accepted_unit_classes"], list) and data["accepted_unit_classes"]
    for counter in (
        "units_received_count",
        "units_processed_count",
        "units_rejected_count",
    ):
        assert isinstance(data[counter], int)
    assert isinstance(data["verified_output_weight_kg"], (int, float))
    assert isinstance(data["diversion_rate_pct"], (int, float))


def assert_pickup_order(data: dict):
    assert_common_fields(data)
    assert data["fulfillment_status"] in (
        "SCHEDULED",
        "PICKED_UP",
        "DELIVERED",
        "CLOSED",
        "CANCELLED",
    )
    assert data["settlement_status"] in (
        "UNSETTLED",
        "ESTIMATED",
        "DISPUTED",
        "FINALIZED",
        "VOIDED",
    )
    assert isinstance(data["units_manifested"], int) and data["units_manifested"] >= 1
    assert isinstance(data["route_distance_km"], (int, float)) and data["route_distance_km"] > 0
    assert isinstance(data["hauler_auto_selected"], bool)
    for money_field in ("estimated_payment_cents", "final_payment_cents"):
        if data.get(money_field) is not None:
            assert isinstance(
                data[money_field], int
            ), f"{money_field} must be whole cents (integer), got {data[money_field]!r}"


def assert_load_inspection(data: dict):
    """An inspection is an append-only event record: it carries only id and
    created_at from the common properties."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "a load inspection must not carry updated_at"
    assert "version" not in data, "a load inspection must not carry version"
    assert data["disposition"] in ("PARTIAL_ACCEPT", "FULL_REJECT")
    assert data["infestation_finding"] in ("NONE", "BED_BUG", "MOLD")
    assert isinstance(data["contaminated_unit_count"], int)
    assert isinstance(data["contamination_pct"], (int, float))
    assert isinstance(data["units_accepted"], int)
    if data["disposition"] == "PARTIAL_ACCEPT":
        assert data["rejection_reason"] is None
    else:
        assert data["rejection_reason"] in ("INFESTATION", "CONTAMINATION_THRESHOLD")


def assert_commodity_output_record(data: dict):
    assert_common_fields(data)
    assert data["commodity"] in ("STEEL", "FOAM", "FIBER", "WOOD")
    assert data["record_status"] in ("SUBMITTED", "VERIFIED")
    assert isinstance(data["output_weight_kg"], (int, float)) and data["output_weight_kg"] > 0


def assert_take_back_delivery(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "SCHEDULED",
        "OBLIGATION_MET",
        "OBLIGATION_BREACHED",
        "WAIVED",
    )
    assert isinstance(data["units_delivered_new"], int) and data["units_delivered_new"] >= 1
    assert isinstance(data["units_takeback_offered"], int)
    assert isinstance(data["breach_units"], int)
    assert isinstance(data["breach_penalty_cents"], int)


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def assert_custody_conservation(site: dict):
    """After every request the site's lifetime total must equal the sum of the
    five custody buckets exactly."""
    buckets = (
        site["units_on_hand"]
        + site["units_in_transit"]
        + site["units_at_recycler_count"]
        + site["units_recycled_count"]
        + site["units_written_off_count"]
    )
    assert site["units_reported_total"] == buckets, (
        "units_reported_total must equal the five custody buckets: "
        f"{site['units_reported_total']} != {buckets} "
        f"(on_hand={site['units_on_hand']}, in_transit={site['units_in_transit']}, "
        f"at_recycler={site['units_at_recycler_count']}, "
        f"recycled={site['units_recycled_count']}, "
        f"written_off={site['units_written_off_count']})"
    )


def assert_custody_buckets(
    site: dict,
    on_hand: int,
    in_transit: int,
    at_recycler: int,
    recycled: int,
    written_off: int,
    reported_total: int = None,
):
    assert site["units_on_hand"] == on_hand, (
        f"units_on_hand expected {on_hand}, got {site['units_on_hand']}"
    )
    assert site["units_in_transit"] == in_transit, (
        f"units_in_transit expected {in_transit}, got {site['units_in_transit']}"
    )
    assert site["units_at_recycler_count"] == at_recycler, (
        f"units_at_recycler_count expected {at_recycler}, "
        f"got {site['units_at_recycler_count']}"
    )
    assert site["units_recycled_count"] == recycled, (
        f"units_recycled_count expected {recycled}, got {site['units_recycled_count']}"
    )
    assert site["units_written_off_count"] == written_off, (
        f"units_written_off_count expected {written_off}, "
        f"got {site['units_written_off_count']}"
    )
    if reported_total is not None:
        assert site["units_reported_total"] == reported_total, (
            f"units_reported_total expected {reported_total}, "
            f"got {site['units_reported_total']}"
        )
    assert_custody_conservation(site)


def assert_program_ledger_invariants(program: dict):
    """The reserve balance is the opening reserve plus fees collected, less site
    credits paid, less hauler payments paid."""
    expected = (
        program["reserve_opening_cents"]
        + program["fee_collected_cents"]
        - program["site_credit_paid_cents"]
        - program["hauler_payment_paid_cents"]
    )
    assert program["reserve_balance_cents"] == expected, (
        "reserve_balance_cents must reconcile from primary records: expected "
        f"{expected}, got {program['reserve_balance_cents']}"
    )


def assert_program_ledger(
    program: dict,
    fee_collected_cents: int = None,
    site_credit_paid_cents: int = None,
    hauler_payment_paid_cents: int = None,
    reserve_balance_cents: int = None,
    receivable_cents: int = None,
):
    if fee_collected_cents is not None:
        assert program["fee_collected_cents"] == fee_collected_cents, (
            f"fee_collected_cents expected {fee_collected_cents}, "
            f"got {program['fee_collected_cents']}"
        )
    if site_credit_paid_cents is not None:
        assert program["site_credit_paid_cents"] == site_credit_paid_cents, (
            f"site_credit_paid_cents expected {site_credit_paid_cents}, "
            f"got {program['site_credit_paid_cents']}"
        )
    if hauler_payment_paid_cents is not None:
        assert program["hauler_payment_paid_cents"] == hauler_payment_paid_cents, (
            f"hauler_payment_paid_cents expected {hauler_payment_paid_cents}, "
            f"got {program['hauler_payment_paid_cents']}"
        )
    if reserve_balance_cents is not None:
        assert program["reserve_balance_cents"] == reserve_balance_cents, (
            f"reserve_balance_cents expected {reserve_balance_cents}, "
            f"got {program['reserve_balance_cents']}"
        )
    if receivable_cents is not None:
        assert program["receivable_cents"] == receivable_cents, (
            f"receivable_cents expected {receivable_cents}, "
            f"got {program['receivable_cents']}"
        )
    assert_program_ledger_invariants(program)


def assert_two_decimals(value, expected, label="value"):
    """A quantity carried as a number with two decimal places."""
    assert round(float(value), 2) == round(float(expected), 2), (
        f"{label} expected {expected}, got {value}"
    )


def assert_diversion_basis(recycler: dict):
    """The diversion basis is the accepted units multiplied by 28.0 kilograms."""
    basis = recycler["units_processed_count"] * AVG_UNIT_WEIGHT_KG
    if basis == 0:
        assert_two_decimals(recycler["diversion_rate_pct"], 0.00, "diversion_rate_pct")
    else:
        expected = round(recycler["verified_output_weight_kg"] / basis * 100 + 1e-9, 2)
        assert_two_decimals(recycler["diversion_rate_pct"], expected, "diversion_rate_pct")
