"""Payload factories.

Each factory returns the minimum well-formed body for one create endpoint, with
keyword overrides for the field under test. Optional fields are omitted unless
supplied, so a factory call exercises the contract's declared defaults rather
than restating them.
"""

from typing import Any, Dict, List, Optional


def _prune(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value was left unspecified."""
    return {k: v for k, v in payload.items() if v is not None}


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


def client_payload(
    client_code: str = "CLBASE",
    name: str = "Baseline Statements Bank",
    status: Optional[str] = None,
    sla_turnaround_hours: Optional[int] = None,
    sla_penalty_rate_cents_per_hour: Optional[int] = None,
    sla_penalty_cap_cents: Optional[int] = None,
    control_total_tolerance_bp: Optional[int] = None,
    dr_readiness_required: Optional[bool] = False,
    **extra: Any,
) -> Dict[str, Any]:
    """A client registration body.

    ``dr_readiness_required`` defaults to ``False`` here so that a test which
    is not about disaster recovery need not stand up a DR site; pass ``True``
    explicitly to exercise the readiness gate.
    """
    payload = _prune(
        {
            "client_code": client_code,
            "name": name,
            "status": status,
            "sla_turnaround_hours": sla_turnaround_hours,
            "sla_penalty_rate_cents_per_hour": sla_penalty_rate_cents_per_hour,
            "sla_penalty_cap_cents": sla_penalty_cap_cents,
            "control_total_tolerance_bp": control_total_tolerance_bp,
        }
    )
    if dr_readiness_required is not None:
        payload["dr_readiness_required"] = dr_readiness_required
    payload.update(extra)
    return payload


def postage_deposit_payload(
    amount_cents: int = 100000, reference: str = "wire-base", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents, "reference": reference}
    payload.update(extra)
    return payload


def paperless_sync_payload(
    confirm_pending_account_refs: Optional[List[str]] = None, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "confirm_pending_account_refs": (
            confirm_pending_account_refs
            if confirm_pending_account_refs is not None
            else []
        )
    }
    payload.update(extra)
    return payload


def address_feedback_payload(
    note: str = "Address correction release", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"note": note}
    payload.update(extra)
    return payload


def enrollment_payload(
    client_id: str, account_ref: str = "ABC1001", channel: str = "EMAIL", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "account_ref": account_ref,
        "channel": channel,
    }
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Insert stock
# --------------------------------------------------------------------------


def insert_stock_payload(
    insert_code: str = "INS-BASE",
    description: str = "Regulatory disclosure",
    jurisdiction_code: str = "US",
    effective_from: str = "2026-01-01T00:00:00Z",
    effective_to: Optional[str] = None,
    sheets_per_insert: Optional[int] = None,
    received_count: int = 100,
    status: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "insert_code": insert_code,
            "description": description,
            "jurisdiction_code": jurisdiction_code,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "sheets_per_insert": sheets_per_insert,
            "received_count": received_count,
            "status": status,
        }
    )
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Composition template
# --------------------------------------------------------------------------


def template_payload(
    client_id: str,
    template_code: str = "T-BASE",
    version_no: int = 1,
    duplex_required: bool = False,
    sheets_per_document: int = 1,
    color_pages_per_document: int = 0,
    mail_class_preference: str = "FIRST_CLASS",
    required_insert_codes: Optional[List[str]] = None,
    variable_content_rules: Optional[List[Dict[str, Any]]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "template_code": template_code,
        "version_no": version_no,
        "duplex_required": duplex_required,
        "sheets_per_document": sheets_per_document,
        "color_pages_per_document": color_pages_per_document,
        "mail_class_preference": mail_class_preference,
        "required_insert_codes": (
            required_insert_codes if required_insert_codes is not None else []
        ),
        "variable_content_rules": (
            variable_content_rules if variable_content_rules is not None else []
        ),
    }
    payload.update(extra)
    return payload


def variable_content_rule(
    rule_code: str,
    threshold_amount_cents: int,
    add_sheets: int,
    required_insert_code: Optional[str] = None,
) -> Dict[str, Any]:
    """One variable content rule. ``required_insert_code`` is explicitly
    nullable, so it is always present in the rule object."""
    return {
        "rule_code": rule_code,
        "threshold_amount_cents": threshold_amount_cents,
        "add_sheets": add_sheets,
        "required_insert_code": required_insert_code,
    }


# --------------------------------------------------------------------------
# Data files and statement records
# --------------------------------------------------------------------------


def data_file_payload(
    client_id: str,
    file_name: str = "base.csv",
    format_spec_code: str = "DELIMITED",
    declared_record_count: int = 1,
    declared_control_total_cents: int = 5000,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "file_name": file_name,
        "format_spec_code": format_spec_code,
        "declared_record_count": declared_record_count,
        "declared_control_total_cents": declared_control_total_cents,
    }
    payload.update(extra)
    return payload


def statement_record_payload(
    data_file_id: str,
    account_ref: str = "ABC1001",
    sequence_no: int = 1,
    statement_amount_cents: int = 5000,
    address_line1: str = "100 Baseline Boulevard",
    city: str = "Atlanta",
    region_code: str = "GA",
    postal_code: str = "30301",
    postal_code_plus4: Optional[str] = "3001",
    address_line2: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "data_file_id": data_file_id,
            "account_ref": account_ref,
            "sequence_no": sequence_no,
            "statement_amount_cents": statement_amount_cents,
            "address_line1": address_line1,
            "address_line2": address_line2,
            "city": city,
            "region_code": region_code,
            "postal_code": postal_code,
            "postal_code_plus4": postal_code_plus4,
        }
    )
    payload.update(extra)
    return payload


def amend_control_totals_payload(
    declared_record_count: Optional[int] = None,
    declared_control_total_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "declared_record_count": declared_record_count,
            "declared_control_total_cents": declared_control_total_cents,
        }
    )
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Composition, presort, scheduling
# --------------------------------------------------------------------------


def composition_job_payload(
    data_file_id: str, template_id: str, rush_requested: bool = False, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "data_file_id": data_file_id,
        "template_id": template_id,
        "rush_requested": rush_requested,
    }
    payload.update(extra)
    return payload


def schedule_payload(
    window_start: str, press_line_id: Optional[str] = None, **extra: Any
) -> Dict[str, Any]:
    """A scheduling body. Omitting ``press_line_id`` runs the selector."""
    payload = _prune({"window_start": window_start, "press_line_id": press_line_id})
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Press floor
# --------------------------------------------------------------------------


def press_line_payload(
    line_code: str = "PL-BASE",
    capabilities: Optional[List[str]] = None,
    sheets_per_hour: int = 600,
    daily_sheet_capacity: int = 2000,
    changeover_buffer_minutes: Optional[int] = None,
    status: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "line_code": line_code,
            "sheets_per_hour": sheets_per_hour,
            "daily_sheet_capacity": daily_sheet_capacity,
            "changeover_buffer_minutes": changeover_buffer_minutes,
            "status": status,
        }
    )
    payload["capabilities"] = (
        capabilities if capabilities is not None else ["DUPLEX", "COLOR", "INSERT"]
    )
    payload.update(extra)
    return payload


# --------------------------------------------------------------------------
# Scanning, reprints, postage, returns, disaster recovery
# --------------------------------------------------------------------------


def abort_payload(abort_reason: Optional[str] = None, **extra: Any) -> Dict[str, Any]:
    """An abort body. Omitting the reason leaves the run on its default."""
    payload = _prune({"abort_reason": abort_reason})
    payload.update(extra)
    return payload


def scan_payload(
    stage: str, scanned_barcode: str, device_code: str = "SCN-BASE", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "stage": stage,
        "scanned_barcode": scanned_barcode,
        "device_code": device_code,
    }
    payload.update(extra)
    return payload


def reprint_payload(
    expected_composition_job_version: int,
    reprint_reason: str = "integrity failure",
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_composition_job_version": expected_composition_job_version,
        "reprint_reason": reprint_reason,
    }
    payload.update(extra)
    return payload


def entry_facility_payload(
    facility_code: str = "EF-BASE",
    facility_type: str = "SCF",
    tray_capacity_per_window: int = 10,
    discount_bp_first_class: int = 850,
    discount_bp_marketing: int = 400,
    status: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "facility_code": facility_code,
            "facility_type": facility_type,
            "tray_capacity_per_window": tray_capacity_per_window,
            "discount_bp_first_class": discount_bp_first_class,
            "discount_bp_marketing": discount_bp_marketing,
            "status": status,
        }
    )
    payload.update(extra)
    return payload


def seal_payload(expected_client_version: int, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_client_version": expected_client_version}
    payload.update(extra)
    return payload


def manifest_payload(
    entry_facility_id: str,
    induction_window_start: str,
    induction_window_end: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "entry_facility_id": entry_facility_id,
        "induction_window_start": induction_window_start,
        "induction_window_end": induction_window_end,
    }
    payload.update(extra)
    return payload


def return_payload(
    mail_piece_id: str, reason_code: str = "VACANT", **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mail_piece_id": mail_piece_id,
        "reason_code": reason_code,
    }
    payload.update(extra)
    return payload


def classify_payload(
    corrected_address_line1: Optional[str] = None,
    corrected_postal_code: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload = _prune(
        {
            "corrected_address_line1": corrected_address_line1,
            "corrected_postal_code": corrected_postal_code,
        }
    )
    payload.update(extra)
    return payload


def dr_site_payload(
    site_code: str = "DR-BASE", replication_lag_minutes: int = 5, **extra: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "site_code": site_code,
        "replication_lag_minutes": replication_lag_minutes,
    }
    payload.update(extra)
    return payload


def drill_payload(result: str = "PASS", **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"result": result}
    payload.update(extra)
    return payload
