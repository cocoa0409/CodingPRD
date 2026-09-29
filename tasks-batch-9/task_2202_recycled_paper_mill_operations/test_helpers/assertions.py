"""Entity assertions and domain invariant checkers."""
from datetime import datetime

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """Every resource carries id and created_at; most also carry updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


def assert_versioned_fields(data: dict):
    assert_common_fields(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be an integer >= 1, got {data.get('version')!r}"


def assert_reference_only_fields(data: dict):
    """Reference and append-only rows carry only id and created_at."""
    assert_common_fields(data)
    assert "updated_at" not in data, "updated_at must be absent from this resource kind"
    assert "version" not in data, "version must be absent from this resource kind"


def assert_customer(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["allocation_priority_tier"] in ("P1", "P2", "P3")
    assert 800 <= data["max_roll_diameter_mm"] <= 1800
    assert 400 <= data["max_roll_width_mm"] <= 2800
    assert data["wrap_spec"] in ("KRAFT_ONLY", "POLY_COATED", "STRETCH_HOOD")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_supplier(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["freight_per_ton"] >= 0
    assert isinstance(data["contamination_strike_count"], int)
    assert data["qualification_status"] in ("QUALIFIED", "PROBATION", "SUSPENDED")


def assert_fiber_grade(data: dict):
    assert_reference_only_fields(data)
    assert data["index_symbol"] in ("PPI_OCC", "PPI_DLK", "PPI_SOP", "PPI_ONP")
    assert 0 <= data["max_contamination_pct"] <= 25
    assert 0 <= data["max_moisture_pct"] <= 20
    assert 40 <= data["nominal_yield_pct"] <= 95
    assert isinstance(data["deink_required"], bool)
    assert 1 <= data["rank_order"] <= 99


def assert_market_index_quote(data: dict):
    assert_reference_only_fields(data)
    assert data["published_price_per_ton"] > 0
    assert isinstance(data["superseded"], bool)


def assert_paper_grade_spec(data: dict):
    assert_reference_only_fields(data)
    assert data["family"] in ("CONTAINERBOARD", "TISSUE")
    assert 12 <= data["basis_weight_gsm"] <= 400
    assert 2 <= data["target_moisture_pct"] <= 12
    assert 0.1 <= data["moisture_tolerance_pct"] <= 3
    assert data["min_sct_kn_m"] >= 0
    assert isinstance(data["requires_deink_pulp"], bool)
    assert 1 <= data["rank_order"] <= 99


def assert_paper_machine(data: dict):
    assert_versioned_fields(data)
    assert 1000 <= data["wire_width_mm"] <= 8000
    assert data["max_tons_per_hour"] > 0
    assert 0 <= data["changeover_buffer_minutes"] <= 240
    assert data["steam_tph_per_ton"] > 0
    assert data["status"] in ("RUNNABLE", "DOWN")


def assert_purchase_order(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("DRAFT", "PRICED", "CONFIRMED", "PARTIALLY_RECEIVED",
                             "CLOSED", "CANCELLED")
    assert 0 < data["contracted_tons"] <= 5000
    assert data["index_basis"] in ("PRIOR_MONTH", "CURRENT_MONTH")
    assert isinstance(data["pricing_revision_count"], int)
    assert data["received_net_tons"] >= 0


def assert_receipt(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("SAMPLED", "ACCEPTED", "DOWNGRADED", "REJECTED")
    assert isinstance(data["sublots"], list) and 1 <= len(data["sublots"]) <= 12
    assert data["net_tons"] >= 0
    assert data["weighted_moisture_pct"] >= 0
    assert data["weighted_contamination_pct"] >= 0


def assert_inventory_lot(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("AVAILABLE", "DEPLETED", "QUARANTINED")
    assert data["tons_received"] >= 0
    assert data["tons_consumed"] >= 0
    assert data["tons_available"] >= 0, "tons_available is never negative"


def assert_pulp_batch(data: dict):
    assert_versioned_fields(data)
    assert data["pulper_line"] in ("OCC_LINE", "DIP_LINE")
    assert data["status"] in ("QUEUED", "PULPING", "SCREENED", "CLEANED", "DEINKING",
                             "DEINK_HOLD", "APPROVED", "DIVERTED", "CANCELLED")
    assert isinstance(data["furnish_lines"], list) and 1 <= len(data["furnish_lines"]) <= 6
    assert isinstance(data["deink_pass_count"], int) and 0 <= data["deink_pass_count"] <= 3


def assert_production_run(data: dict):
    assert_versioned_fields(data)
    assert data["run_status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")
    assert data["quality_status"] in ("PENDING", "PROVISIONAL", "HELD", "REWORK",
                                     "CERTIFIED", "CONDEMNED")
    assert data["pulp_draw_tons"] > 0


def assert_grade_change(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("PLANNED", "EXECUTED", "VOIDED")


def assert_roll_set(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("WOUND", "WRAPPED", "QUARANTINED", "REWOUND",
                             "ALLOCATED", "SHIPPED", "SCRAPPED")
    assert 400 <= data["slit_width_mm"] <= 2800
    assert 800 <= data["diameter_mm"] <= 1800
    assert 1 <= data["roll_count"] <= 40
    assert data["net_tons"] > 0
    assert isinstance(data["rewind_count"], int)


def assert_customer_order(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("SUBMITTED", "SCHEDULED", "IN_PRODUCTION",
                             "PARTIALLY_ALLOCATED", "ALLOCATED", "SHIPPED",
                             "SHORT_CLOSED", "CANCELLED")
    assert 0 < data["ordered_tons"] <= 2000
    assert data["allocated_tons"] >= 0
    assert data["shipped_tons"] >= 0
    assert data["shortfall_tons"] >= 0


def assert_effluent_permit(data: dict):
    assert_versioned_fields(data)
    assert data["compliance_posture"] in ("COMPLIANT", "WATCH", "EXCEEDANCE")
    assert 7 <= data["rolling_window_days"] <= 30
    assert data["rolling_bod_kg_per_day"] >= 0
    assert data["rolling_tss_kg_per_day"] >= 0
    assert isinstance(data["exceedance_day_count"], int)


def assert_effluent_reading(data: dict):
    assert_versioned_fields(data)
    assert isinstance(data["voided"], bool)
    assert data["flow_m3"] >= 0 and data["bod_kg"] >= 0 and data["tss_kg"] >= 0


def assert_sludge_manifest(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("DRAFT", "SIGNED", "VOIDED")
    assert data["destination"] in ("LANDFILL", "LAND_APPLICATION", "FUEL")
    assert isinstance(data["reject_stream_ids"], list)
    assert 1 <= len(data["reject_stream_ids"]) <= 20


def assert_reject_stream(data: dict):
    assert_reference_only_fields(data)
    assert data["source_kind"] in ("PULP_REJECT", "DEINK_SLUDGE", "MACHINE_BROKE",
                                  "TRANSITION_WASTE")
    assert data["dry_solids_tons"] >= 0
    assert data["disposition"] in ("PENDING", "MANIFESTED", "REPULPED")


def assert_steam_allocation(data: dict):
    assert_versioned_fields(data)
    assert data["status"] in ("REQUESTED", "GRANTED", "CURTAILED", "RELEASED")
    assert 0 < data["demand_tph"] <= 200
    assert 1 <= data["priority_rank"] <= 3


# ------------------------------------------------------------- invariants -----

def assert_fiber_balance_conserved(balance: dict):
    """The mill fiber balance imbalance must read exactly zero whenever observed."""
    assert balance["imbalance_tons"] == 0 or abs(balance["imbalance_tons"]) < 1e-9, \
        f"imbalance_tons must be exactly zero, got {balance['imbalance_tons']}"
    expected = round(balance["total_received_tons"] - balance["total_consumed_tons"]
                     - balance["total_available_tons"], 3)
    assert abs(expected) < 1e-9, \
        f"received - consumed - available must be zero, got {expected}"


def assert_solids_ledger_invariant(summary: dict):
    """net_solids_tons equals manifested + unmanifested, to three decimal places."""
    assert round(summary["net_solids_tons"], 3) == round(
        summary["gross_solids_tons"] - summary["reversed_solids_tons"], 3), \
        "net_solids_tons must equal gross minus reversed"
    split = round(summary["manifested_dry_solids_tons"]
                  + summary["unmanifested_dry_solids_tons"], 3)
    assert round(summary["net_solids_tons"], 3) == split, \
        f"net_solids_tons {summary['net_solids_tons']} must equal manifested+unmanifested {split}"


def assert_version_bumped(before: dict, after: dict, by: int = 1):
    assert after["version"] == before["version"] + by, \
        f"version must advance by {by}: {before['version']} -> {after['version']}"


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two ISO 8601 UTC strings as instants.

    PRD §2.4 pins the rendering of server-minted timestamps to three fractional
    digits but says nothing about how a client-supplied instant is echoed back,
    so window instants are compared by value rather than by literal string.
    """
    def _parse(value):
        assert isinstance(value, str), f"{label} must be a string, got {value!r}"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert _parse(actual) == _parse(expected_iso), \
        f"{label} must be the instant {expected_iso}, got {actual}"
