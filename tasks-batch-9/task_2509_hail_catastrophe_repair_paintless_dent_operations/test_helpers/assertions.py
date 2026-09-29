"""Shape and invariant assertions for the resources described by PRD §2.5–§2.8.

Each ``assert_<resource>_shape`` checks the fields the PRD says the resource
carries, the universal audit fields it says every resource carries, and the
three-resource exception that omits ``updated_at`` and ``version``.  The
invariant helpers below encode relationships the PRD states in prose (posture
selection, staging counters, the money chain, the pay cascade).
"""

from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import (
    OCCUPANCY_RATIO_DECIMALS,
    WARRANTY_COUNTER_WIDTH,
    WARRANTY_PREFIX,
)
from .types import NON_TERMINAL_REPAIR_STATES

# ─── Universal audit fields (PRD §2.5) ────────────────────────────────────────


def assert_identity_fields(row: Dict[str, Any]) -> None:
    """`id` is a UUID and `created_at` is an ISO-8601 UTC timestamp."""
    assert is_valid_uuid(row["id"]), f"id is not a UUID: {row['id']!r}"
    assert is_iso8601_timestamp(
        row["created_at"]
    ), f"created_at is not ISO-8601 UTC: {row['created_at']!r}"


def assert_versioned_audit_fields(row: Dict[str, Any]) -> None:
    """A resource that carries the full audit quartet."""
    assert_identity_fields(row)
    assert is_iso8601_timestamp(
        row["updated_at"]
    ), f"updated_at is not ISO-8601 UTC: {row['updated_at']!r}"
    assert isinstance(row["version"], int), f"version is not an integer: {row['version']!r}"
    assert row["version"] >= 1, f"version must start at 1, saw {row['version']!r}"


def assert_no_version_or_updated_at(row: Dict[str, Any]) -> None:
    """Permit, DamageLine and QualityInspection carry only `id` and `created_at`."""
    assert_identity_fields(row)
    assert "updated_at" not in row, "this resource must have no updated_at field at all"
    assert "version" not in row, "this resource must have no version field at all"


def assert_fields_present(row: Dict[str, Any], field_names: Sequence[str]) -> None:
    missing = [name for name in field_names if name not in row]
    assert not missing, f"missing fields {missing} in {sorted(row)}"


def assert_fields_equal(row: Dict[str, Any], **expected) -> None:
    """Compare named fields one at a time so failures name the offending field."""
    for field, value in expected.items():
        assert field in row, f"response has no {field} field"
        if isinstance(value, float):
            assert abs(row[field] - value) < 1e-9, (
                f"expected {field} {value}, saw {row[field]}"
            )
        else:
            assert row[field] == value, f"expected {field} {value!r}, saw {row[field]!r}"


# ─── Storm events (PRD §3.1) ──────────────────────────────────────────────────

STORM_EVENT_INPUT_FIELDS = [
    "name",
    "region_state_code",
    "max_hail_size_mm",
    "swath_area_km2",
    "swath_confidence",
    "vehicle_population_estimate",
    "competitor_shop_count",
    "first_hail_at",
]


def assert_storm_event_shape(event: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(event)
    assert_fields_present(
        event, STORM_EVENT_INPUT_FIELDS + ["status", "targeting_score", "demobilized_at"]
    )
    assert isinstance(event["targeting_score"], int), "targeting_score must be an integer"
    assert 0 <= event["targeting_score"] <= 100, (
        f"targeting_score must be clamped into 0..100, saw {event['targeting_score']}"
    )


# ─── Facilities (PRD §2.6, §3.2) ──────────────────────────────────────────────


def assert_facility_shape(facility: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(facility)
    assert_fields_present(
        facility,
        [
            "storm_event_id",
            "name",
            "state_code",
            "address",
            "staging_slot_count",
            "pay_model",
            "status",
            "posture",
            "warranty_counter",
            "commissioned_at",
            "staging_slots_occupied",
            "staging_slots_free",
            "staging_occupancy_ratio",
            "billable_accrued_cents",
            "absorbed_rental_cents",
        ],
    )
    assert is_valid_uuid(facility["storm_event_id"])
    assert_staging_counters(facility)


def assert_staging_counters(facility: Dict[str, Any]) -> None:
    """Occupied plus free equals the slot count, and the ratio matches them."""
    slot_count = facility["staging_slot_count"]
    occupied = facility["staging_slots_occupied"]
    free = facility["staging_slots_free"]
    assert occupied >= 0, f"staging_slots_occupied must not go negative: {occupied}"
    assert free >= 0, f"staging_slots_free must not go negative: {free}"
    assert occupied + free == slot_count, (
        f"occupied ({occupied}) + free ({free}) must equal "
        f"staging_slot_count ({slot_count})"
    )
    expected_ratio = round(occupied / slot_count, OCCUPANCY_RATIO_DECIMALS)
    assert abs(facility["staging_occupancy_ratio"] - expected_ratio) < 1e-9, (
        f"staging_occupancy_ratio {facility['staging_occupancy_ratio']} does not match "
        f"{occupied}/{slot_count} rounded to {OCCUPANCY_RATIO_DECIMALS} places"
    )


def assert_facility_state(
    facility: Dict[str, Any], status: str, posture: str
) -> None:
    assert facility["status"] == status, (
        f"expected facility status {status}, saw {facility['status']}"
    )
    assert facility["posture"] == posture, (
        f"expected facility posture {posture}, saw {facility['posture']}"
    )


def assert_commissioned_at_unchanged(
    facility: Dict[str, Any], expected_commissioned_at: str
) -> None:
    """The original commissioning instant survives a suspension and a return."""
    assert facility["commissioned_at"] == expected_commissioned_at, (
        f"commissioned_at was rewritten: expected {expected_commissioned_at}, "
        f"saw {facility['commissioned_at']}"
    )


# ─── Permits (PRD §2.5, §3.2) ─────────────────────────────────────────────────


def assert_permit_shape(permit: Dict[str, Any]) -> None:
    assert_no_version_or_updated_at(permit)
    assert_fields_present(
        permit,
        [
            "facility_id",
            "permit_type",
            "issuing_jurisdiction",
            "status",
            "valid_from",
            "valid_to",
            "decided_at",
        ],
    )
    assert is_valid_uuid(permit["facility_id"])


def assert_permit_decision(
    permit: Dict[str, Any],
    status: str,
    valid_from: Optional[str],
    valid_to: Optional[str],
    decided_at: Optional[str] = None,
) -> None:
    assert permit["status"] == status, (
        f"expected permit status {status}, saw {permit['status']}"
    )
    assert permit["valid_from"] == valid_from, (
        f"expected valid_from {valid_from!r}, saw {permit['valid_from']!r}"
    )
    assert permit["valid_to"] == valid_to, (
        f"expected valid_to {valid_to!r}, saw {permit['valid_to']!r}"
    )
    if decided_at is not None:
        assert permit["decided_at"] == decided_at, (
            f"expected decided_at {decided_at}, saw {permit['decided_at']}"
        )


# ─── Technicians (PRD §2.8, §3.3) ─────────────────────────────────────────────


def assert_technician_shape(technician: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(technician)
    assert_fields_present(
        technician,
        [
            "full_name",
            "home_state_code",
            "license_state_code",
            "license_expires_at",
            "skill_tier",
            "flat_split_pct",
            "deployment_state",
            "accrued_pay_cents",
            "approved_ticket_count",
        ],
    )
    assert technician["accrued_pay_cents"] >= 0
    assert technician["approved_ticket_count"] >= 0


def assert_technician_pay(
    technician: Dict[str, Any],
    accrued_pay_cents: int,
    approved_ticket_count: Optional[int] = None,
    deployment_state: Optional[str] = None,
) -> None:
    assert technician["accrued_pay_cents"] == accrued_pay_cents, (
        f"expected accrued_pay_cents {accrued_pay_cents}, "
        f"saw {technician['accrued_pay_cents']}"
    )
    if approved_ticket_count is not None:
        assert technician["approved_ticket_count"] == approved_ticket_count, (
            f"expected approved_ticket_count {approved_ticket_count}, "
            f"saw {technician['approved_ticket_count']}"
        )
    if deployment_state is not None:
        assert technician["deployment_state"] == deployment_state, (
            f"expected deployment_state {deployment_state}, "
            f"saw {technician['deployment_state']}"
        )


# ─── Housing units and crew deployments (PRD §3.3) ────────────────────────────


def assert_housing_unit_shape(unit: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(unit)
    assert_fields_present(
        unit,
        [
            "facility_id",
            "label",
            "bed_count",
            "nightly_rate_cents",
            "occupied_beds",
            "bed_nights_committed",
        ],
    )
    assert 0 <= unit["occupied_beds"] <= unit["bed_count"], (
        f"occupied_beds {unit['occupied_beds']} outside 0..{unit['bed_count']}"
    )
    assert unit["bed_nights_committed"] >= 0


def assert_housing_occupancy(
    unit: Dict[str, Any], occupied_beds: int, bed_nights_committed: int
) -> None:
    assert unit["occupied_beds"] == occupied_beds, (
        f"expected occupied_beds {occupied_beds}, saw {unit['occupied_beds']}"
    )
    assert unit["bed_nights_committed"] == bed_nights_committed, (
        f"expected bed_nights_committed {bed_nights_committed}, "
        f"saw {unit['bed_nights_committed']}"
    )


def assert_crew_deployment_shape(deployment: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(deployment)
    assert_fields_present(
        deployment,
        [
            "technician_id",
            "facility_id",
            "housing_unit_id",
            "start_date",
            "end_date",
            "status",
            "actual_end_date",
            "effective_end_date",
            "pay_split_pct_snapshot",
        ],
    )
    assert is_valid_uuid(deployment["technician_id"])
    assert is_valid_uuid(deployment["facility_id"])


# ─── Insurers and rate agreements (PRD §2.8, §3.4) ────────────────────────────


def assert_insurer_shape(insurer: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(insurer)
    assert_fields_present(
        insurer,
        [
            "name",
            "naic_code",
            "direct_bill_enabled",
            "active_rate_agreement_count",
            "outstanding_direct_bill_cents",
            "settled_cents",
        ],
    )
    assert insurer["active_rate_agreement_count"] >= 0


def assert_insurer_ledger(
    insurer: Dict[str, Any],
    outstanding_direct_bill_cents: int,
    settled_cents: Optional[int] = None,
    active_rate_agreement_count: Optional[int] = None,
) -> None:
    assert insurer["outstanding_direct_bill_cents"] == outstanding_direct_bill_cents, (
        f"expected outstanding_direct_bill_cents {outstanding_direct_bill_cents}, "
        f"saw {insurer['outstanding_direct_bill_cents']}"
    )
    if settled_cents is not None:
        assert insurer["settled_cents"] == settled_cents, (
            f"expected settled_cents {settled_cents}, saw {insurer['settled_cents']}"
        )
    if active_rate_agreement_count is not None:
        assert insurer["active_rate_agreement_count"] == active_rate_agreement_count, (
            f"expected active_rate_agreement_count {active_rate_agreement_count}, "
            f"saw {insurer['active_rate_agreement_count']}"
        )


RATE_AGREEMENT_SHEET_FIELDS = [
    "effective_from",
    "matrix_rate_dime_cents",
    "matrix_rate_nickel_cents",
    "matrix_rate_quarter_cents",
    "matrix_rate_half_dollar_cents",
    "labor_rate_cents_per_hour",
    "panel_cap_cents",
    "admin_fee_pct",
    "admin_fee_cap_cents",
    "supplement_auto_approve_pct",
    "rental_cap_days",
    "rental_daily_rate_cents",
]


def assert_rate_agreement_shape(agreement: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(agreement)
    assert_fields_present(
        agreement,
        ["insurer_id", "storm_event_id", "status"] + RATE_AGREEMENT_SHEET_FIELDS,
    )


# ─── Vehicles (PRD §2.7, §3.5–§3.9) ───────────────────────────────────────────


def assert_vehicle_shape(vehicle: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(vehicle)
    assert_fields_present(
        vehicle,
        [
            "facility_id",
            "insurer_id",
            "vin",
            "model_year",
            "make",
            "model",
            "acv_cents",
            "owner_name",
            "rental_required",
            "repair_status",
            "billing_status",
            "pinned_rate_agreement_id",
            "matrix_variant_total_cents",
            "conventional_variant_total_cents",
            "pdr_feasible",
            "triage_disposition",
            "approved_repair_cents",
            "approved_supplement_cents",
            "admin_fee_cents",
            "gross_billable_cents",
            "discount_cents",
            "net_billable_cents",
            "rework_count",
            "rental_days_billed",
            "shop_absorbed_rental_cents",
            "rental_opened_at",
            "rental_closed_at",
            "released_at",
            "warranty_number",
            "warranty_expires_at",
        ],
    )
    assert is_valid_uuid(vehicle["facility_id"])
    assert is_valid_uuid(vehicle["insurer_id"])
    assert len(vehicle["vin"]) == 17, f"vin must be 17 characters: {vehicle['vin']!r}"


def assert_vehicle_variants(
    vehicle: Dict[str, Any],
    matrix_variant_total_cents: int,
    conventional_variant_total_cents: int,
    pdr_feasible: Optional[bool] = None,
) -> None:
    assert vehicle["matrix_variant_total_cents"] == matrix_variant_total_cents, (
        f"expected matrix_variant_total_cents {matrix_variant_total_cents}, "
        f"saw {vehicle['matrix_variant_total_cents']}"
    )
    assert (
        vehicle["conventional_variant_total_cents"] == conventional_variant_total_cents
    ), (
        f"expected conventional_variant_total_cents "
        f"{conventional_variant_total_cents}, "
        f"saw {vehicle['conventional_variant_total_cents']}"
    )
    if pdr_feasible is not None:
        assert vehicle["pdr_feasible"] is pdr_feasible, (
            f"expected pdr_feasible {pdr_feasible}, saw {vehicle['pdr_feasible']}"
        )


def assert_triage_outcome(
    vehicle: Dict[str, Any],
    triage_disposition: str,
    approved_repair_cents: int,
    repair_status: Optional[str] = None,
) -> None:
    assert vehicle["triage_disposition"] == triage_disposition, (
        f"expected triage_disposition {triage_disposition}, "
        f"saw {vehicle['triage_disposition']}"
    )
    assert vehicle["approved_repair_cents"] == approved_repair_cents, (
        f"expected approved_repair_cents {approved_repair_cents}, "
        f"saw {vehicle['approved_repair_cents']}"
    )
    if repair_status is not None:
        assert vehicle["repair_status"] == repair_status, (
            f"expected repair_status {repair_status}, saw {vehicle['repair_status']}"
        )


def assert_money_chain(
    vehicle: Dict[str, Any],
    admin_fee_cents: int,
    gross_billable_cents: int,
    discount_cents: int,
    net_billable_cents: int,
) -> None:
    """The four derived money fields of the billable waterfall, together."""
    assert vehicle["admin_fee_cents"] == admin_fee_cents, (
        f"expected admin_fee_cents {admin_fee_cents}, saw {vehicle['admin_fee_cents']}"
    )
    assert vehicle["gross_billable_cents"] == gross_billable_cents, (
        f"expected gross_billable_cents {gross_billable_cents}, "
        f"saw {vehicle['gross_billable_cents']}"
    )
    assert vehicle["discount_cents"] == discount_cents, (
        f"expected discount_cents {discount_cents}, saw {vehicle['discount_cents']}"
    )
    assert vehicle["net_billable_cents"] == net_billable_cents, (
        f"expected net_billable_cents {net_billable_cents}, "
        f"saw {vehicle['net_billable_cents']}"
    )


def assert_vehicle_states(
    vehicle: Dict[str, Any],
    repair_status: Optional[str] = None,
    billing_status: Optional[str] = None,
) -> None:
    if repair_status is not None:
        assert vehicle["repair_status"] == repair_status, (
            f"expected repair_status {repair_status}, saw {vehicle['repair_status']}"
        )
    if billing_status is not None:
        assert vehicle["billing_status"] == billing_status, (
            f"expected billing_status {billing_status}, saw {vehicle['billing_status']}"
        )


def assert_occupies_staging_slot(vehicle: Dict[str, Any]) -> None:
    assert vehicle["repair_status"] in NON_TERMINAL_REPAIR_STATES, (
        f"repair_status {vehicle['repair_status']} is terminal, so this vehicle "
        "no longer occupies a staging slot"
    )


def assert_warranty_minted(
    vehicle: Dict[str, Any], warranty_number: str, warranty_expires_at: str
) -> None:
    """A released repair mints a prefixed, zero-padded number and a 90-day expiry."""
    assert vehicle["warranty_number"] == warranty_number, (
        f"expected warranty_number {warranty_number}, saw {vehicle['warranty_number']}"
    )
    assert vehicle["warranty_number"].startswith(WARRANTY_PREFIX)
    counter = vehicle["warranty_number"][len(WARRANTY_PREFIX) :]
    assert len(counter) == WARRANTY_COUNTER_WIDTH and counter.isdigit(), (
        f"the counter must be {WARRANTY_COUNTER_WIDTH} digits, saw {counter!r}"
    )
    assert vehicle["warranty_expires_at"] == warranty_expires_at, (
        f"expected warranty_expires_at {warranty_expires_at}, "
        f"saw {vehicle['warranty_expires_at']}"
    )


def assert_no_warranty_minted(vehicle: Dict[str, Any]) -> None:
    assert vehicle["warranty_number"] is None, (
        f"a towed-out total loss mints nothing, saw {vehicle['warranty_number']!r}"
    )


def assert_rental_exposure(
    vehicle: Dict[str, Any], rental_days_billed: int, shop_absorbed_rental_cents: int
) -> None:
    assert vehicle["rental_days_billed"] == rental_days_billed, (
        f"expected rental_days_billed {rental_days_billed}, "
        f"saw {vehicle['rental_days_billed']}"
    )
    assert vehicle["shop_absorbed_rental_cents"] == shop_absorbed_rental_cents, (
        f"expected shop_absorbed_rental_cents {shop_absorbed_rental_cents}, "
        f"saw {vehicle['shop_absorbed_rental_cents']}"
    )


# ─── Damage lines (PRD §2.5, §3.5) ────────────────────────────────────────────


def assert_damage_line_shape(line: Dict[str, Any]) -> None:
    assert_no_version_or_updated_at(line)
    assert_fields_present(
        line,
        [
            "vehicle_id",
            "panel_code",
            "dent_count",
            "dent_size_class",
            "aluminum",
            "r_and_i_hours",
            "oversize_dent_count",
            "conventional_labor_hours",
            "conventional_paint_materials_cents",
            "pdr_line_cents",
            "conventional_line_cents",
            "capped",
            "routed_to",
        ],
    )
    assert is_valid_uuid(line["vehicle_id"])


def assert_damage_line_pricing(
    line: Dict[str, Any],
    pdr_line_cents: int,
    conventional_line_cents: int,
    capped: Optional[bool] = None,
    routed_to: Optional[str] = None,
) -> None:
    assert line["pdr_line_cents"] == pdr_line_cents, (
        f"expected pdr_line_cents {pdr_line_cents} on panel {line['panel_code']}, "
        f"saw {line['pdr_line_cents']}"
    )
    assert line["conventional_line_cents"] == conventional_line_cents, (
        f"expected conventional_line_cents {conventional_line_cents} on panel "
        f"{line['panel_code']}, saw {line['conventional_line_cents']}"
    )
    if capped is not None:
        assert line["capped"] is capped, (
            f"expected capped {capped} on panel {line['panel_code']}, "
            f"saw {line['capped']}"
        )
    if routed_to is not None:
        assert line["routed_to"] == routed_to, (
            f"expected routed_to {routed_to} on panel {line['panel_code']}, "
            f"saw {line['routed_to']}"
        )


def line_by_panel(lines: List[Dict[str, Any]], panel_code: str) -> Dict[str, Any]:
    matches = [line for line in lines if line["panel_code"] == panel_code]
    assert len(matches) == 1, (
        f"expected exactly one {panel_code} damage line, saw {len(matches)}"
    )
    return matches[0]


# ─── Work tickets (PRD §3.7) ──────────────────────────────────────────────────


def assert_work_ticket_shape(ticket: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(ticket)
    assert_fields_present(
        ticket,
        [
            "vehicle_id",
            "technician_id",
            "labor_units",
            "dents_repaired",
            "panels_worked",
            "status",
            "payable_flat_cents",
            "payable_pooled_cents",
            "payable_cents",
            "pay_model_applied",
        ],
    )
    assert is_valid_uuid(ticket["vehicle_id"])
    assert is_valid_uuid(ticket["technician_id"])


def assert_ticket_pay(
    ticket: Dict[str, Any],
    payable_flat_cents: int,
    payable_pooled_cents: int,
    payable_cents: Optional[int] = None,
    pay_model_applied: Optional[str] = None,
    status: Optional[str] = None,
) -> None:
    """Both variants are always computed and stored; one of them is payable."""
    assert ticket["payable_flat_cents"] == payable_flat_cents, (
        f"expected payable_flat_cents {payable_flat_cents}, "
        f"saw {ticket['payable_flat_cents']}"
    )
    assert ticket["payable_pooled_cents"] == payable_pooled_cents, (
        f"expected payable_pooled_cents {payable_pooled_cents}, "
        f"saw {ticket['payable_pooled_cents']}"
    )
    if payable_cents is not None:
        assert ticket["payable_cents"] == payable_cents, (
            f"expected payable_cents {payable_cents}, saw {ticket['payable_cents']}"
        )
    if pay_model_applied is not None:
        assert ticket["pay_model_applied"] == pay_model_applied, (
            f"expected pay_model_applied {pay_model_applied}, "
            f"saw {ticket['pay_model_applied']}"
        )
    if status is not None:
        assert ticket["status"] == status, (
            f"expected ticket status {status}, saw {ticket['status']}"
        )


def ticket_by_technician(
    tickets: List[Dict[str, Any]], technician_id: str
) -> Dict[str, Any]:
    matches = [t for t in tickets if t["technician_id"] == technician_id]
    assert len(matches) == 1, (
        f"expected exactly one ticket for technician {technician_id}, "
        f"saw {len(matches)}"
    )
    return matches[0]


# ─── Supplements (PRD §3.8) ───────────────────────────────────────────────────


def assert_supplement_shape(supplement: Dict[str, Any]) -> None:
    assert_versioned_audit_fields(supplement)
    assert_fields_present(
        supplement,
        [
            "vehicle_id",
            "reason_code",
            "requested_amount_cents",
            "status",
            "round_index",
            "approved_amount_cents",
            "counter_amount_cents",
            "decided_at",
        ],
    )
    assert is_valid_uuid(supplement["vehicle_id"])
    assert supplement["round_index"] >= 1


def assert_supplement_state(
    supplement: Dict[str, Any],
    status: str,
    round_index: Optional[int] = None,
    approved_amount_cents: Optional[int] = None,
    requested_amount_cents: Optional[int] = None,
    counter_amount_cents: Optional[int] = None,
) -> None:
    assert supplement["status"] == status, (
        f"expected supplement status {status}, saw {supplement['status']}"
    )
    if round_index is not None:
        assert supplement["round_index"] == round_index, (
            f"expected round_index {round_index}, saw {supplement['round_index']}"
        )
    if approved_amount_cents is not None:
        assert supplement["approved_amount_cents"] == approved_amount_cents, (
            f"expected approved_amount_cents {approved_amount_cents}, "
            f"saw {supplement['approved_amount_cents']}"
        )
    if requested_amount_cents is not None:
        assert supplement["requested_amount_cents"] == requested_amount_cents, (
            f"expected requested_amount_cents {requested_amount_cents}, "
            f"saw {supplement['requested_amount_cents']}"
        )
    if counter_amount_cents is not None:
        assert supplement["counter_amount_cents"] == counter_amount_cents, (
            f"expected counter_amount_cents {counter_amount_cents}, "
            f"saw {supplement['counter_amount_cents']}"
        )


# ─── Quality inspections (PRD §2.5, §3.7) ─────────────────────────────────────


def assert_quality_inspection_shape(inspection: Dict[str, Any]) -> None:
    assert_no_version_or_updated_at(inspection)
    assert_fields_present(
        inspection,
        [
            "vehicle_id",
            "inspector_technician_id",
            "result",
            "defect_panel_codes",
            "rework_index",
            "inspected_at",
        ],
    )
    assert is_valid_uuid(inspection["vehicle_id"])
    assert is_valid_uuid(inspection["inspector_technician_id"])


# ─── Throughput summary (PRD §3.2) ────────────────────────────────────────────

THROUGHPUT_SUMMARY_FIELDS = [
    "staging_slot_count",
    "staging_slots_occupied",
    "staging_slots_free",
    "staging_occupancy_ratio",
    "posture",
    "open_vehicle_count",
    "vehicles_in_repair",
    "vehicles_ready",
    "released_count",
    "on_site_technician_count",
    "projected_days_to_clear",
    "billable_accrued_cents",
    "absorbed_rental_cents",
]


def assert_throughput_summary_shape(summary: Dict[str, Any]) -> None:
    assert_fields_present(summary, THROUGHPUT_SUMMARY_FIELDS)


def assert_throughput_values(summary: Dict[str, Any], **expected) -> None:
    assert_fields_equal(summary, **expected)


# ─── Listing helpers ──────────────────────────────────────────────────────────


def assert_created_at_ascending(rows: List[Dict[str, Any]]) -> None:
    stamps = [row["created_at"] for row in rows]
    assert stamps == sorted(stamps), (
        f"rows are not sorted by created_at ascending: {stamps}"
    )


def ids_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]
