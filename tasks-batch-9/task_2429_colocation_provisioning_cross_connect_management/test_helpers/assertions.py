"""Shape, precision and invariant assertions for the colocation API.

The response-envelope and error-envelope checks live in the framework
(`validate_success`, `validate_error`, `validate_paginated`); everything here is
domain-specific: the field roster each entity must return, the decimal precision the
PRD pins per unit, and the cross-entity roll-up identities the PRD states.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .constants import KW_DECIMALS, USD_DECIMALS, UNIT_RATE_DECIMALS

# --- numeric helpers -------------------------------------------------------


def round_half_up(value: Any, decimals: int) -> Decimal:
    """Half-up rounding to `decimals` places, the tie-breaking rule the PRD names."""
    quantum = Decimal(1).scaleb(-decimals)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _assert_scale(value: Any, decimals: int, label: str) -> None:
    assert value is not None, f"{label} must be present"
    assert isinstance(value, (int, float, str)), f"{label} must be numeric, got {value!r}"
    as_decimal = Decimal(str(value))
    assert -as_decimal.as_tuple().exponent <= decimals, (
        f"{label} carries more than {decimals} decimal places: {value!r}"
    )
    assert as_decimal == round_half_up(value, decimals), (
        f"{label} is not settled to {decimals} decimal places: {value!r}"
    )


def assert_kw_precision(value: Any, label: str = "power value") -> None:
    """Power quantities are carried to three decimals."""
    _assert_scale(value, KW_DECIMALS, label)


def assert_usd_precision(value: Any, label: str = "money value") -> None:
    """Money is carried to two decimals."""
    _assert_scale(value, USD_DECIMALS, label)


def assert_unit_rate_precision(value: Any, label: str = "unit rate") -> None:
    """Per-unit rates are carried to four decimals."""
    _assert_scale(value, UNIT_RATE_DECIMALS, label)


def assert_amount_equals(actual: Any, expected: Any, label: str = "amount") -> None:
    """Compare money without being tripped up by float representation."""
    assert round_half_up(actual, USD_DECIMALS) == round_half_up(expected, USD_DECIMALS), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_kw_equals(actual: Any, expected: Any, label: str = "power value") -> None:
    assert round_half_up(actual, KW_DECIMALS) == round_half_up(expected, KW_DECIMALS), (
        f"{label}: expected {expected}, got {actual}"
    )


# --- common fields ---------------------------------------------------------


def assert_common_fields(data: Dict[str, Any], label: str = "entity") -> None:
    """`id`, `created_at`, `updated_at`, `version` as every versioned record carries them."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and not isinstance(version, bool), (
        f"{label}.version must be an integer, got {version!r}"
    )
    assert version >= 1, f"{label}.version starts at 1, got {version}"


def assert_ledger_common_fields(data: Dict[str, Any], label: str = "invoice line") -> None:
    """An immutable ledger row carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id")), f"{label}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, f"{label} must not carry updated_at"
    assert "version" not in data, f"{label} must not carry version"


def assert_fields_present(data: Dict[str, Any], fields: Iterable[str], label: str) -> None:
    missing = [f for f in fields if f not in data]
    assert not missing, f"{label} is missing declared fields: {missing}"


# --- per-entity shape ------------------------------------------------------

CUSTOMER_FIELDS = ("legal_name", "account_code", "account_status")

CONTRACT_FIELDS = (
    "customer_id",
    "contract_number",
    "status",
    "billing_mode",
    "committed_cabinet_count",
    "committed_cage_sqft",
    "power_commit_kw",
    "redundancy_requirement",
    "committed_bandwidth_mbps",
    "cross_connect_allowance",
    "cross_connect_cap",
    "remote_hands_included_minutes",
    "remote_hands_remaining_minutes",
    "credit_hold",
    "term_start_date",
    "term_end_date",
    "provisioned_power_kw",
    "stranded_commit_kw",
    "commit_utilization_pct",
    "active_cross_connect_count",
    "billed_total_usd",
    "cross_connect_billed_usd",
    "last_closed_period_end",
)

ROW_FIELDS = (
    "hall_code",
    "row_code",
    "cabinet_slot_count",
    "design_density_kw_per_cabinet",
    "max_row_power_kw",
    "cooling_capacity_kw",
    "escort_slot_count",
    "decommission_flag",
    "row_status",
    "occupied_slot_count",
    "density_ceiling_kw",
    "effective_ceiling_kw",
    "allocated_power_kw",
    "cooling_load_kw",
    "energized_cabinet_count",
    "stranded_nameplate_kw",
    "stranded_measured_kw",
    "measured_peak_kw",
)

CABINET_FIELDS = (
    "row_id",
    "cabinet_code",
    "contract_id",
    "rated_power_kw",
    "footprint_type",
    "u_height",
    "status",
    "allocated_power_kw",
    "cooling_load_kw",
    "energized_primary_circuit_count",
)

CIRCUIT_FIELDS = (
    "cabinet_id",
    "circuit_code",
    "feed_side",
    "redundancy_role",
    "breaker_amps",
    "volts",
    "phase",
    "derated_kw",
    "allocated_kw",
    "cooling_contribution_kw",
    "status",
    "energized_at",
    "meter_intervals",
)

PORT_FIELDS = (
    "row_id",
    "panel_code",
    "port_number",
    "media_type",
    "status",
    "assigned_order_id",
    "quarantine_until",
)

CROSS_CONNECT_ORDER_FIELDS = (
    "contract_id",
    "requested_by_contact_id",
    "a_end_cabinet_id",
    "z_end_cabinet_id",
    "parent_order_id",
    "cable_type",
    "status",
    "a_end_port_id",
    "z_end_port_id",
    "path_hops",
    "revision_count",
    "mrc_usd",
    "proposed_by_user_id",
    "approved_by_user_id",
    "activated_at",
)

CONTACT_FIELDS = (
    "customer_id",
    "full_name",
    "authorization_scopes",
    "access_level",
    "biometric_state",
    "enrolled_at",
)

VISIT_FIELDS = (
    "contract_id",
    "contact_id",
    "cabinet_id",
    "purpose",
    "window_start",
    "window_end",
    "status",
    "escort_required",
    "escort_officer_user_id",
    "checked_in_at",
    "checked_out_at",
)

TICKET_FIELDS = (
    "contract_id",
    "requested_by_contact_id",
    "target_cabinet_id",
    "authorizing_contact_id",
    "severity",
    "description",
    "authorization_state",
    "execution_state",
    "authorized_at",
    "response_deadline_at",
    "dispatched_at",
    "completed_at",
    "sla_breached",
    "work_segments",
    "billable_increments",
    "billed_minutes",
    "included_increments_applied",
    "labor_charge_usd",
)

DECOMMISSION_ORDER_FIELDS = (
    "contract_id",
    "cabinet_id",
    "requested_by_contact_id",
    "status",
    "equipment_removed_at",
    "equipment_removed_by_user_id",
    "cables_reclaimed_at",
    "cables_reclaimed_by_user_id",
    "released_port_count",
    "released_power_kw",
)

INVOICE_LINE_FIELDS = (
    "contract_id",
    "line_type",
    "period_start",
    "period_end",
    "quantity",
    "unit_rate_usd",
    "amount_usd",
    "source_ref_id",
    "included_minutes_consumed",
    "reversed",
)


def assert_customer(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "customer")
    assert_fields_present(data, CUSTOMER_FIELDS, "customer")


def assert_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "contract")
    assert_fields_present(data, CONTRACT_FIELDS, "contract")
    assert_kw_precision(data["provisioned_power_kw"], "contract.provisioned_power_kw")
    assert_kw_precision(data["stranded_commit_kw"], "contract.stranded_commit_kw")
    assert_usd_precision(data["billed_total_usd"], "contract.billed_total_usd")


def assert_floor_row(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "row")
    assert_fields_present(data, ROW_FIELDS, "row")
    assert_kw_precision(data["allocated_power_kw"], "row.allocated_power_kw")
    assert_kw_precision(data["cooling_load_kw"], "row.cooling_load_kw")
    assert_kw_precision(data["density_ceiling_kw"], "row.density_ceiling_kw")
    assert_kw_precision(data["effective_ceiling_kw"], "row.effective_ceiling_kw")


def assert_cabinet(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "cabinet")
    assert_fields_present(data, CABINET_FIELDS, "cabinet")
    assert_kw_precision(data["allocated_power_kw"], "cabinet.allocated_power_kw")
    assert_kw_precision(data["cooling_load_kw"], "cabinet.cooling_load_kw")


def assert_power_circuit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "power circuit")
    assert_fields_present(data, CIRCUIT_FIELDS, "power circuit")
    assert_kw_precision(data["derated_kw"], "circuit.derated_kw")
    assert_kw_precision(data["allocated_kw"], "circuit.allocated_kw")
    assert_kw_precision(data["cooling_contribution_kw"], "circuit.cooling_contribution_kw")


def assert_patch_panel_port(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "port")
    assert_fields_present(data, PORT_FIELDS, "port")


def assert_cross_connect_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "cross-connect order")
    assert_fields_present(data, CROSS_CONNECT_ORDER_FIELDS, "cross-connect order")


def assert_authorized_contact(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "contact")
    assert_fields_present(data, CONTACT_FIELDS, "contact")


def assert_access_visit(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "access visit")
    assert_fields_present(data, VISIT_FIELDS, "access visit")


def assert_remote_hands_ticket(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "ticket")
    assert_fields_present(data, TICKET_FIELDS, "ticket")
    assert_usd_precision(data["labor_charge_usd"], "ticket.labor_charge_usd")


def assert_decommission_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data, "decommission order")
    assert_fields_present(data, DECOMMISSION_ORDER_FIELDS, "decommission order")


def assert_invoice_line(data: Dict[str, Any]) -> None:
    assert_ledger_common_fields(data)
    assert_fields_present(data, INVOICE_LINE_FIELDS, "invoice line")
    assert_usd_precision(data["amount_usd"], "invoice line.amount_usd")


# --- roll-up identities ----------------------------------------------------


def assert_row_capacity_view(
    row: Dict[str, Any],
    *,
    occupied_slot_count: Optional[int] = None,
    density_ceiling_kw: Optional[Any] = None,
    effective_ceiling_kw: Optional[Any] = None,
    allocated_power_kw: Optional[Any] = None,
    cooling_load_kw: Optional[Any] = None,
    energized_cabinet_count: Optional[int] = None,
    stranded_nameplate_kw: Optional[Any] = None,
    stranded_measured_kw: Optional[Any] = None,
    row_status: Optional[str] = None,
) -> None:
    """Assert the row's derived capacity view field by field, skipping unnamed ones."""
    if occupied_slot_count is not None:
        assert row["occupied_slot_count"] == occupied_slot_count, (
            f"row.occupied_slot_count: expected {occupied_slot_count}, got {row['occupied_slot_count']}"
        )
    if density_ceiling_kw is not None:
        assert_kw_equals(row["density_ceiling_kw"], density_ceiling_kw, "row.density_ceiling_kw")
    if effective_ceiling_kw is not None:
        assert_kw_equals(row["effective_ceiling_kw"], effective_ceiling_kw, "row.effective_ceiling_kw")
    if allocated_power_kw is not None:
        assert_kw_equals(row["allocated_power_kw"], allocated_power_kw, "row.allocated_power_kw")
    if cooling_load_kw is not None:
        assert_kw_equals(row["cooling_load_kw"], cooling_load_kw, "row.cooling_load_kw")
    if energized_cabinet_count is not None:
        assert row["energized_cabinet_count"] == energized_cabinet_count, (
            f"row.energized_cabinet_count: expected {energized_cabinet_count}, "
            f"got {row['energized_cabinet_count']}"
        )
    if stranded_nameplate_kw is not None:
        assert_kw_equals(row["stranded_nameplate_kw"], stranded_nameplate_kw, "row.stranded_nameplate_kw")
    if stranded_measured_kw is not None:
        assert_kw_equals(row["stranded_measured_kw"], stranded_measured_kw, "row.stranded_measured_kw")
    if row_status is not None:
        assert row["row_status"] == row_status, (
            f"row.row_status: expected {row_status}, got {row['row_status']}"
        )


def assert_contract_power_rollup(
    contract: Dict[str, Any],
    *,
    provisioned_power_kw: Optional[Any] = None,
    stranded_commit_kw: Optional[Any] = None,
    commit_utilization_pct: Optional[Any] = None,
) -> None:
    if provisioned_power_kw is not None:
        assert_kw_equals(
            contract["provisioned_power_kw"], provisioned_power_kw, "contract.provisioned_power_kw"
        )
    if stranded_commit_kw is not None:
        assert_kw_equals(
            contract["stranded_commit_kw"], stranded_commit_kw, "contract.stranded_commit_kw"
        )
    if commit_utilization_pct is not None:
        assert round_half_up(contract["commit_utilization_pct"], 1) == round_half_up(
            commit_utilization_pct, 1
        ), (
            f"contract.commit_utilization_pct: expected {commit_utilization_pct}, "
            f"got {contract['commit_utilization_pct']}"
        )


def assert_contract_billing_rollup(
    contract: Dict[str, Any],
    *,
    billed_total_usd: Optional[Any] = None,
    cross_connect_billed_usd: Optional[Any] = None,
    remote_hands_remaining_minutes: Optional[int] = None,
    active_cross_connect_count: Optional[int] = None,
) -> None:
    if billed_total_usd is not None:
        assert_amount_equals(contract["billed_total_usd"], billed_total_usd, "contract.billed_total_usd")
    if cross_connect_billed_usd is not None:
        assert_amount_equals(
            contract["cross_connect_billed_usd"],
            cross_connect_billed_usd,
            "contract.cross_connect_billed_usd",
        )
    if remote_hands_remaining_minutes is not None:
        assert contract["remote_hands_remaining_minutes"] == remote_hands_remaining_minutes, (
            f"contract.remote_hands_remaining_minutes: expected {remote_hands_remaining_minutes}, "
            f"got {contract['remote_hands_remaining_minutes']}"
        )
    if active_cross_connect_count is not None:
        assert contract["active_cross_connect_count"] == active_cross_connect_count, (
            f"contract.active_cross_connect_count: expected {active_cross_connect_count}, "
            f"got {contract['active_cross_connect_count']}"
        )


def assert_circuit_power(
    circuit: Dict[str, Any],
    *,
    status: Optional[str] = None,
    allocated_kw: Optional[Any] = None,
    cooling_contribution_kw: Optional[Any] = None,
    derated_kw: Optional[Any] = None,
) -> None:
    if status is not None:
        assert circuit["status"] == status, (
            f"circuit.status: expected {status}, got {circuit['status']}"
        )
    if allocated_kw is not None:
        assert_kw_equals(circuit["allocated_kw"], allocated_kw, "circuit.allocated_kw")
    if cooling_contribution_kw is not None:
        assert_kw_equals(
            circuit["cooling_contribution_kw"], cooling_contribution_kw, "circuit.cooling_contribution_kw"
        )
    if derated_kw is not None:
        assert_kw_equals(circuit["derated_kw"], derated_kw, "circuit.derated_kw")


def assert_cabinet_power(
    cabinet: Dict[str, Any],
    *,
    status: Optional[str] = None,
    allocated_power_kw: Optional[Any] = None,
    cooling_load_kw: Optional[Any] = None,
    energized_primary_circuit_count: Optional[int] = None,
) -> None:
    if status is not None:
        assert cabinet["status"] == status, (
            f"cabinet.status: expected {status}, got {cabinet['status']}"
        )
    if allocated_power_kw is not None:
        assert_kw_equals(cabinet["allocated_power_kw"], allocated_power_kw, "cabinet.allocated_power_kw")
    if cooling_load_kw is not None:
        assert_kw_equals(cabinet["cooling_load_kw"], cooling_load_kw, "cabinet.cooling_load_kw")
    if energized_primary_circuit_count is not None:
        assert cabinet["energized_primary_circuit_count"] == energized_primary_circuit_count, (
            f"cabinet.energized_primary_circuit_count: expected "
            f"{energized_primary_circuit_count}, got {cabinet['energized_primary_circuit_count']}"
        )


def assert_invoice_line_values(
    line: Dict[str, Any],
    *,
    line_type: Optional[str] = None,
    amount_usd: Optional[Any] = None,
    quantity: Optional[Any] = None,
    unit_rate_usd: Optional[Any] = None,
    source_ref_id: Optional[str] = None,
    included_minutes_consumed: Optional[int] = None,
    reversed_flag: Optional[bool] = None,
) -> None:
    if line_type is not None:
        assert line["line_type"] == line_type, (
            f"invoice line.line_type: expected {line_type}, got {line['line_type']}"
        )
    if amount_usd is not None:
        assert_amount_equals(line["amount_usd"], amount_usd, "invoice line.amount_usd")
    if quantity is not None:
        assert round_half_up(line["quantity"], KW_DECIMALS) == round_half_up(quantity, KW_DECIMALS), (
            f"invoice line.quantity: expected {quantity}, got {line['quantity']}"
        )
    if unit_rate_usd is not None:
        assert round_half_up(line["unit_rate_usd"], UNIT_RATE_DECIMALS) == round_half_up(
            unit_rate_usd, UNIT_RATE_DECIMALS
        ), f"invoice line.unit_rate_usd: expected {unit_rate_usd}, got {line['unit_rate_usd']}"
    if source_ref_id is not None:
        assert line["source_ref_id"] == source_ref_id, (
            f"invoice line.source_ref_id: expected {source_ref_id}, got {line['source_ref_id']}"
        )
    if included_minutes_consumed is not None:
        assert line["included_minutes_consumed"] == included_minutes_consumed, (
            f"invoice line.included_minutes_consumed: expected {included_minutes_consumed}, "
            f"got {line['included_minutes_consumed']}"
        )
    if reversed_flag is not None:
        assert line["reversed"] is reversed_flag, (
            f"invoice line.reversed: expected {reversed_flag}, got {line['reversed']}"
        )


def find_lines(lines: Iterable[Dict[str, Any]], line_type: str) -> list:
    return [line for line in lines if line.get("line_type") == line_type]


def one_line(lines: Iterable[Dict[str, Any]], line_type: str) -> Dict[str, Any]:
    """The single ledger row of a given type, asserting there is exactly one."""
    matches = find_lines(lines, line_type)
    assert len(matches) == 1, (
        f"expected exactly one {line_type} line, got {len(matches)}: "
        f"{[m.get('amount_usd') for m in matches]}"
    )
    return matches[0]


def assert_ticket_labor(
    ticket: Dict[str, Any],
    *,
    billable_increments: Optional[int] = None,
    billed_minutes: Optional[int] = None,
    included_increments_applied: Optional[int] = None,
    labor_charge_usd: Optional[Any] = None,
    sla_breached: Optional[bool] = None,
) -> None:
    if billable_increments is not None:
        assert ticket["billable_increments"] == billable_increments, (
            f"ticket.billable_increments: expected {billable_increments}, "
            f"got {ticket['billable_increments']}"
        )
    if billed_minutes is not None:
        assert ticket["billed_minutes"] == billed_minutes, (
            f"ticket.billed_minutes: expected {billed_minutes}, got {ticket['billed_minutes']}"
        )
    if included_increments_applied is not None:
        assert ticket["included_increments_applied"] == included_increments_applied, (
            f"ticket.included_increments_applied: expected {included_increments_applied}, "
            f"got {ticket['included_increments_applied']}"
        )
    if labor_charge_usd is not None:
        assert_amount_equals(ticket["labor_charge_usd"], labor_charge_usd, "ticket.labor_charge_usd")
    if sla_breached is not None:
        assert ticket["sla_breached"] is sla_breached, (
            f"ticket.sla_breached: expected {sla_breached}, got {ticket['sla_breached']}"
        )


def assert_version_is(data: Dict[str, Any], expected: int, label: str = "entity") -> None:
    assert data["version"] == expected, (
        f"{label}.version: expected {expected}, got {data['version']}"
    )


def assert_timestamps_unchanged(before: Dict[str, Any], after: Dict[str, Any], label: str) -> None:
    """A refused call must leave the record untouched."""
    assert before["updated_at"] == after["updated_at"], f"{label}.updated_at moved on a refusal"
    assert before["version"] == after["version"], f"{label}.version moved on a refusal"
