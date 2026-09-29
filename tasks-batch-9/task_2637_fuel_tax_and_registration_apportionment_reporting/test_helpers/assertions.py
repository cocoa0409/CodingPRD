"""Domain assertion helpers.

Numeric helpers pin each quantity at the number of decimal places the contract
states for it, so a two-decimal money field is never compared with the slack
appropriate to a six-decimal percentage.
"""
import re
from typing import Any, Dict, List, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import LIGHT_ENTITY_FORBIDDEN_FIELDS


# --------------------------------------------------------------------------
# Numeric precision
# --------------------------------------------------------------------------

def assert_money(actual: Any, expected: float, label: str = "amount") -> None:
    """A 2-decimal currency amount."""
    assert actual is not None, f"{label} is null"
    assert actual == pytest.approx(expected, abs=0.01), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_gallons(actual: Any, expected: float, label: str = "gallons") -> None:
    """A 3-decimal gallons quantity."""
    assert actual is not None, f"{label} is null"
    assert actual == pytest.approx(expected, abs=0.001), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_miles(actual: Any, expected: float, label: str = "miles") -> None:
    """A 1-decimal mileage quantity."""
    assert actual is not None, f"{label} is null"
    assert actual == pytest.approx(expected, abs=0.05), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_ratio(actual: Any, expected: float, label: str = "ratio") -> None:
    """A 4-decimal ratio."""
    assert actual is not None, f"{label} is null"
    assert actual == pytest.approx(expected, abs=0.00005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_mpg(actual: Any, expected: float, label: str = "fleet_mpg") -> None:
    """A 2-decimal miles-per-gallon figure."""
    assert actual is not None, f"{label} is null"
    assert actual == pytest.approx(expected, abs=0.005), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_apportion_percent(
    actual: Any, expected: float, label: str = "apportion_percent"
) -> None:
    """A 6-decimal apportionment share."""
    assert actual is not None, f"{label} is null"
    assert actual == pytest.approx(expected, abs=0.0000005), (
        f"{label}: expected {expected}, got {actual}"
    )


# --------------------------------------------------------------------------
# Envelope shape
# --------------------------------------------------------------------------

def assert_success_meta(response) -> Dict[str, Any]:
    """The success envelope's ``meta`` block."""
    body = response.json()
    assert "meta" in body, f"no meta block in {body}"
    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str)
    assert meta["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {meta['api_request_id']!r}"
    )
    assert is_iso8601_timestamp(meta.get("api_request_timestamp")), (
        f"bad api_request_timestamp: {meta.get('api_request_timestamp')!r}"
    )
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$",
        str(meta["api_request_timestamp"]),
    ), (
        "api_request_timestamp must carry exactly three fractional digits, got "
        f"{meta['api_request_timestamp']!r}"
    )
    return meta


def assert_error_envelope(response, expected_error_id: str) -> Dict[str, Any]:
    """The error envelope: ``response_type`` ``error``, and a meta block
    carrying only the request id and the request timestamp."""
    body = response.json()
    assert body.get("response_type") == "error", (
        f"expected response_type 'error', got {body.get('response_type')!r}"
    )
    data = body.get("data") or {}
    assert data.get("error_id") == expected_error_id, (
        f"expected error_id {expected_error_id}, got {data.get('error_id')!r}"
    )
    assert isinstance(data.get("message"), str) and data["message"], (
        "error payload must carry a human-readable message"
    )
    meta = assert_success_meta(response)
    assert set(meta.keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta must carry only the request id and timestamp, got {sorted(meta)}"
    )
    return data


def assert_object_envelope(response) -> Dict[str, Any]:
    body = response.json()
    assert body.get("response_type") == "object", (
        f"expected response_type 'object', got {body.get('response_type')!r}"
    )
    assert_success_meta(response)
    return body["data"]


def assert_array_envelope(response) -> List[Dict[str, Any]]:
    body = response.json()
    assert body.get("response_type") == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body.get("data"), list)
    return body["data"]


# --------------------------------------------------------------------------
# Identity and common properties
# --------------------------------------------------------------------------

def assert_versioned_entity(data: Dict[str, Any]) -> None:
    """An entity that carries the full common property set."""
    assert is_valid_uuid(data.get("id")), f"id is not a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at"))
    assert is_iso8601_timestamp(data.get("updated_at"))
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_reference_entity(data: Dict[str, Any]) -> None:
    """A reference row: an identifier and a creation stamp, and neither an
    ``updated_at`` nor a ``version``."""
    assert is_valid_uuid(data.get("id")), f"id is not a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at"))
    for field in LIGHT_ENTITY_FORBIDDEN_FIELDS:
        assert field not in data, f"{field} must not appear on this row: {sorted(data)}"


def assert_version_is(data: Dict[str, Any], expected: int, label: str = "version") -> None:
    assert data.get("version") == expected, (
        f"{label}: expected {expected}, got {data.get('version')!r}"
    )


# --------------------------------------------------------------------------
# Collection helpers
# --------------------------------------------------------------------------

def by_code(rows: List[Dict[str, Any]], code: str) -> Dict[str, Any]:
    """The single row whose ``jurisdiction_code`` is ``code``."""
    matches = [r for r in rows if r.get("jurisdiction_code") == code]
    assert len(matches) == 1, (
        f"expected exactly one row for {code}, got {len(matches)}: "
        f"{[r.get('jurisdiction_code') for r in rows]}"
    )
    return matches[0]


def codes_of(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["jurisdiction_code"] for r in rows]


def active_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("line_status") == "ACTIVE"]


def voided_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("line_status") == "VOIDED"]


def active_legs(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("leg_status") == "ACTIVE"]


def voided_legs(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if r.get("leg_status") == "VOIDED"]


def credential_of_type(
    rows: List[Dict[str, Any]], credential_type: str
) -> Dict[str, Any]:
    matches = [r for r in rows if r.get("credential_type") == credential_type]
    assert len(matches) == 1, (
        f"expected exactly one {credential_type} credential, got {len(matches)}"
    )
    return matches[0]


# --------------------------------------------------------------------------
# Composite domain assertions
# --------------------------------------------------------------------------

def assert_trip_state(
    trip: Dict[str, Any],
    trip_status: Optional[str] = None,
    mileage_source: Optional[str] = None,
    accepted_leg_miles_total: Optional[float] = None,
    gap_miles_from_previous: Optional[float] = None,
    odometer_delta_miles: Optional[float] = None,
    supporting_document_reference: Any = ...,
    reconstructed_by_user_id: Any = ...,
) -> None:
    if trip_status is not None:
        assert trip["trip_status"] == trip_status, (
            f"trip_status: expected {trip_status}, got {trip['trip_status']}"
        )
    if mileage_source is not None:
        assert trip["mileage_source"] == mileage_source, (
            f"mileage_source: expected {mileage_source}, got {trip['mileage_source']}"
        )
    if accepted_leg_miles_total is not None:
        assert_miles(
            trip["accepted_leg_miles_total"],
            accepted_leg_miles_total,
            "accepted_leg_miles_total",
        )
    if gap_miles_from_previous is not None:
        assert_miles(
            trip["gap_miles_from_previous"],
            gap_miles_from_previous,
            "gap_miles_from_previous",
        )
    if odometer_delta_miles is not None:
        assert_miles(
            trip["odometer_delta_miles"], odometer_delta_miles, "odometer_delta_miles"
        )
    if supporting_document_reference is not ...:
        assert trip["supporting_document_reference"] == supporting_document_reference, (
            "supporting_document_reference: expected "
            f"{supporting_document_reference!r}, got "
            f"{trip['supporting_document_reference']!r}"
        )
    if reconstructed_by_user_id is not ...:
        assert trip["reconstructed_by_user_id"] == reconstructed_by_user_id, (
            f"reconstructed_by_user_id: expected {reconstructed_by_user_id!r}, got "
            f"{trip['reconstructed_by_user_id']!r}"
        )


def assert_carrier_compliance(
    carrier: Dict[str, Any],
    ifta_license_status: Optional[str] = None,
    irp_account_status: Optional[str] = None,
    unsubstantiated_mileage_ratio: Optional[float] = None,
    audit_flag: Optional[bool] = None,
    tax_paid_gallons_ytd: Optional[float] = None,
    suspension_count: Optional[int] = None,
    latest_prepared_fleet_mpg: Any = ...,
) -> None:
    if ifta_license_status is not None:
        assert carrier["ifta_license_status"] == ifta_license_status, (
            f"ifta_license_status: expected {ifta_license_status}, got "
            f"{carrier['ifta_license_status']}"
        )
    if irp_account_status is not None:
        assert carrier["irp_account_status"] == irp_account_status, (
            f"irp_account_status: expected {irp_account_status}, got "
            f"{carrier['irp_account_status']}"
        )
    if unsubstantiated_mileage_ratio is not None:
        assert_ratio(
            carrier["unsubstantiated_mileage_ratio"],
            unsubstantiated_mileage_ratio,
            "unsubstantiated_mileage_ratio",
        )
    if audit_flag is not None:
        assert carrier["audit_flag"] is audit_flag, (
            f"audit_flag: expected {audit_flag}, got {carrier['audit_flag']!r}"
        )
    if tax_paid_gallons_ytd is not None:
        assert_gallons(
            carrier["tax_paid_gallons_ytd"], tax_paid_gallons_ytd, "tax_paid_gallons_ytd"
        )
    if suspension_count is not None:
        assert carrier["suspension_count"] == suspension_count, (
            f"suspension_count: expected {suspension_count}, got "
            f"{carrier['suspension_count']}"
        )
    if latest_prepared_fleet_mpg is not ...:
        if latest_prepared_fleet_mpg is None:
            assert carrier["latest_prepared_fleet_mpg"] is None, (
                "latest_prepared_fleet_mpg should be null, got "
                f"{carrier['latest_prepared_fleet_mpg']!r}"
            )
        else:
            assert_mpg(
                carrier["latest_prepared_fleet_mpg"],
                latest_prepared_fleet_mpg,
                "latest_prepared_fleet_mpg",
            )


def assert_vehicle_dimensions(
    vehicle: Dict[str, Any],
    vehicle_status: Optional[str] = None,
    credential_status: Optional[str] = None,
    activated_on_date: Any = ...,
    replaced_vehicle_id: Any = ...,
) -> None:
    if vehicle_status is not None:
        assert vehicle["vehicle_status"] == vehicle_status, (
            f"vehicle_status: expected {vehicle_status}, got {vehicle['vehicle_status']}"
        )
    if credential_status is not None:
        assert vehicle["credential_status"] == credential_status, (
            f"credential_status: expected {credential_status}, got "
            f"{vehicle['credential_status']}"
        )
    if activated_on_date is not ...:
        assert vehicle["activated_on_date"] == activated_on_date, (
            f"activated_on_date: expected {activated_on_date!r}, got "
            f"{vehicle['activated_on_date']!r}"
        )
    if replaced_vehicle_id is not ...:
        assert vehicle["replaced_vehicle_id"] == replaced_vehicle_id, (
            f"replaced_vehicle_id: expected {replaced_vehicle_id!r}, got "
            f"{vehicle['replaced_vehicle_id']!r}"
        )


def assert_return_settlement(
    tax_return: Dict[str, Any],
    return_status: Optional[str] = None,
    settlement_basis: Optional[str] = None,
    total_fleet_miles: Optional[float] = None,
    total_tax_paid_gallons: Optional[float] = None,
    fleet_mpg: Any = ...,
    reconstructed_mileage_ratio: Optional[float] = None,
    total_net_tax_due: Optional[float] = None,
    reconstruction_penalty_amount: Optional[float] = None,
    total_amount_due: Optional[float] = None,
    audit_assessment_delta: Optional[float] = None,
) -> None:
    if return_status is not None:
        assert tax_return["return_status"] == return_status, (
            f"return_status: expected {return_status}, got {tax_return['return_status']}"
        )
    if settlement_basis is not None:
        assert tax_return["settlement_basis"] == settlement_basis, (
            f"settlement_basis: expected {settlement_basis}, got "
            f"{tax_return['settlement_basis']}"
        )
    if total_fleet_miles is not None:
        assert_miles(
            tax_return["total_fleet_miles"], total_fleet_miles, "total_fleet_miles"
        )
    if total_tax_paid_gallons is not None:
        assert_gallons(
            tax_return["total_tax_paid_gallons"],
            total_tax_paid_gallons,
            "total_tax_paid_gallons",
        )
    if fleet_mpg is not ...:
        if fleet_mpg is None:
            assert tax_return["fleet_mpg"] is None, (
                f"fleet_mpg should be null, got {tax_return['fleet_mpg']!r}"
            )
        else:
            assert_mpg(tax_return["fleet_mpg"], fleet_mpg)
    if reconstructed_mileage_ratio is not None:
        assert_ratio(
            tax_return["reconstructed_mileage_ratio"],
            reconstructed_mileage_ratio,
            "reconstructed_mileage_ratio",
        )
    if total_net_tax_due is not None:
        assert_money(
            tax_return["total_net_tax_due"], total_net_tax_due, "total_net_tax_due"
        )
    if reconstruction_penalty_amount is not None:
        assert_money(
            tax_return["reconstruction_penalty_amount"],
            reconstruction_penalty_amount,
            "reconstruction_penalty_amount",
        )
    if total_amount_due is not None:
        assert_money(tax_return["total_amount_due"], total_amount_due, "total_amount_due")
    if audit_assessment_delta is not None:
        assert_money(
            tax_return["audit_assessment_delta"],
            audit_assessment_delta,
            "audit_assessment_delta",
        )


def assert_jurisdiction_line(
    line: Dict[str, Any],
    taxable_miles: Optional[float] = None,
    taxable_gallons: Optional[float] = None,
    tax_paid_gallons: Optional[float] = None,
    net_taxable_gallons: Optional[float] = None,
    base_tax_amount: Optional[float] = None,
    surcharge_amount: Optional[float] = None,
    net_tax_amount: Optional[float] = None,
) -> None:
    code = line.get("jurisdiction_code")
    if taxable_miles is not None:
        assert_miles(line["taxable_miles"], taxable_miles, f"{code} taxable_miles")
    if taxable_gallons is not None:
        assert_gallons(line["taxable_gallons"], taxable_gallons, f"{code} taxable_gallons")
    if tax_paid_gallons is not None:
        assert_gallons(
            line["tax_paid_gallons"], tax_paid_gallons, f"{code} tax_paid_gallons"
        )
    if net_taxable_gallons is not None:
        assert_gallons(
            line["net_taxable_gallons"], net_taxable_gallons, f"{code} net_taxable_gallons"
        )
    if base_tax_amount is not None:
        assert_money(line["base_tax_amount"], base_tax_amount, f"{code} base_tax_amount")
    if surcharge_amount is not None:
        assert_money(line["surcharge_amount"], surcharge_amount, f"{code} surcharge_amount")
    if net_tax_amount is not None:
        assert_money(line["net_tax_amount"], net_tax_amount, f"{code} net_tax_amount")


def assert_application_totals(
    application: Dict[str, Any],
    application_status: Optional[str] = None,
    apportioned_vehicle_count: Optional[int] = None,
    fleet_total_distance_miles: Optional[float] = None,
    base_fee_total: Optional[float] = None,
    total_apportioned_fee: Optional[float] = None,
) -> None:
    if application_status is not None:
        assert application["application_status"] == application_status, (
            f"application_status: expected {application_status}, got "
            f"{application['application_status']}"
        )
    if apportioned_vehicle_count is not None:
        assert application["apportioned_vehicle_count"] == apportioned_vehicle_count, (
            f"apportioned_vehicle_count: expected {apportioned_vehicle_count}, got "
            f"{application['apportioned_vehicle_count']}"
        )
    if fleet_total_distance_miles is not None:
        assert_miles(
            application["fleet_total_distance_miles"],
            fleet_total_distance_miles,
            "fleet_total_distance_miles",
        )
    if base_fee_total is not None:
        assert_money(application["base_fee_total"], base_fee_total, "base_fee_total")
    if total_apportioned_fee is not None:
        assert_money(
            application["total_apportioned_fee"],
            total_apportioned_fee,
            "total_apportioned_fee",
        )


def assert_audit_selection(
    selection: Dict[str, Any],
    risk_score: Optional[int] = None,
    selection_status: Optional[str] = None,
    post_review_risk_score: Any = ...,
    retention_deficiency_ratio: Any = ...,
    expected_records_count: Any = ...,
    records_missing_count: Any = ...,
    reviewed_by_user_id: Any = ...,
) -> None:
    if risk_score is not None:
        assert selection["risk_score"] == risk_score, (
            f"risk_score: expected {risk_score}, got {selection['risk_score']}"
        )
    if selection_status is not None:
        assert selection["selection_status"] == selection_status, (
            f"selection_status: expected {selection_status}, got "
            f"{selection['selection_status']}"
        )
    if post_review_risk_score is not ...:
        assert selection["post_review_risk_score"] == post_review_risk_score, (
            f"post_review_risk_score: expected {post_review_risk_score!r}, got "
            f"{selection['post_review_risk_score']!r}"
        )
    if retention_deficiency_ratio is not ...:
        if retention_deficiency_ratio is None:
            assert selection["retention_deficiency_ratio"] is None
        else:
            assert_ratio(
                selection["retention_deficiency_ratio"],
                retention_deficiency_ratio,
                "retention_deficiency_ratio",
            )
    if expected_records_count is not ...:
        assert selection["expected_records_count"] == expected_records_count
    if records_missing_count is not ...:
        assert selection["records_missing_count"] == records_missing_count
    if reviewed_by_user_id is not ...:
        assert selection["reviewed_by_user_id"] == reviewed_by_user_id


def assert_credential_state(
    credential: Dict[str, Any],
    credential_status: Optional[str] = None,
    credential_type: Optional[str] = None,
    distributed_to_driver_id: Any = ...,
    voided_reason_code: Any = ...,
    distributed_at: Any = ...,
    valid_from_date: Optional[str] = None,
    valid_to_date: Optional[str] = None,
) -> None:
    if credential_status is not None:
        assert credential["credential_status"] == credential_status, (
            f"credential_status: expected {credential_status}, got "
            f"{credential['credential_status']}"
        )
    if credential_type is not None:
        assert credential["credential_type"] == credential_type
    if distributed_to_driver_id is not ...:
        assert credential["distributed_to_driver_id"] == distributed_to_driver_id, (
            f"distributed_to_driver_id: expected {distributed_to_driver_id!r}, got "
            f"{credential['distributed_to_driver_id']!r}"
        )
    if voided_reason_code is not ...:
        assert credential["voided_reason_code"] == voided_reason_code, (
            f"voided_reason_code: expected {voided_reason_code!r}, got "
            f"{credential['voided_reason_code']!r}"
        )
    if distributed_at is not ...:
        if distributed_at is None:
            assert credential["distributed_at"] is None
        else:
            assert credential["distributed_at"] == distributed_at
    if valid_from_date is not None:
        assert credential["valid_from_date"] == valid_from_date
    if valid_to_date is not None:
        assert credential["valid_to_date"] == valid_to_date


def assert_change_request(
    change: Dict[str, Any],
    change_status: Optional[str] = None,
    prorate_months: Optional[int] = None,
    fee_delta: Optional[float] = None,
    reversal_reason_code: Any = ...,
    decided_by_user_id: Any = ...,
    requested_by_user_id: Any = ...,
) -> None:
    if change_status is not None:
        assert change["change_status"] == change_status, (
            f"change_status: expected {change_status}, got {change['change_status']}"
        )
    if prorate_months is not None:
        assert change["prorate_months"] == prorate_months, (
            f"prorate_months: expected {prorate_months}, got {change['prorate_months']}"
        )
    if fee_delta is not None:
        assert_money(change["fee_delta"], fee_delta, "fee_delta")
    if reversal_reason_code is not ...:
        assert change["reversal_reason_code"] == reversal_reason_code
    if decided_by_user_id is not ...:
        assert change["decided_by_user_id"] == decided_by_user_id
    if requested_by_user_id is not ...:
        assert change["requested_by_user_id"] == requested_by_user_id
