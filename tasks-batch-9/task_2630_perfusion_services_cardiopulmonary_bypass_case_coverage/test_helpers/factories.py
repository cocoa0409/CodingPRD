"""Request-payload factories, one per creation or action endpoint.

Every factory returns the minimal valid body the PRD requires for that
operation, and accepts keyword overrides so a test can vary exactly the field
it is exercising.
"""
from typing import Any, Dict, List, Optional


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is None."""
    for key, value in overrides.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


# ─── Hospital contracts ───────────────────────────────
def build_hospital_contract(**overrides) -> Dict[str, Any]:
    """A contract carrying every commercial term explicitly."""
    return _merge(
        {
            "hospital_name": "St Aldate Cardiac Center",
            "staffing_model": "COVERAGE_PLUS_PER_CASE",
            "per_case_fee_cents": 400000,
            "ecmo_hourly_fee_cents": 90000,
            "monthly_case_cap": 5,
            "monthly_coverage_fee_cents": 1200000,
            "prolonged_surcharge_pct": 0.15,
            "prolonged_pump_threshold_minutes": 180,
            "disposable_markup_pct": 0.20,
            "disposable_discount_pct": 0.10,
        },
        overrides,
    )


def build_minimal_hospital_contract(**overrides) -> Dict[str, Any]:
    """A contract supplying only the fields with no declared default."""
    return _merge(
        {
            "hospital_name": "Minimal Terms Hospital",
            "staffing_model": "PER_CASE",
            "per_case_fee_cents": 400000,
            "ecmo_hourly_fee_cents": 90000,
            "monthly_case_cap": 5,
        },
        overrides,
    )


def build_contract_update(expected_contract_version: int, **overrides) -> Dict[str, Any]:
    """A commercial-terms update carrying the mandatory expected version."""
    return _merge({"expected_contract_version": expected_contract_version}, overrides)


def build_settlement_run(period: str = "2026-08", **overrides) -> Dict[str, Any]:
    """A monthly settlement request naming its YYYY-MM period."""
    return _merge({"period": period}, overrides)


# ─── Surgeons ─────────────────────────────────────────
def build_surgeon(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Dr Imani Cole",
            "npi_code": "NPI-3300110",
            "specialty": "ADULT_CARDIAC",
        },
        overrides,
    )


# ─── Preference cards ─────────────────────────────────
def build_pack_line_item(line_code: str, quantity: int, unit_cost_cents: int) -> Dict[str, Any]:
    """One line template: a line code, a quantity and a unit cost."""
    return {
        "line_code": line_code,
        "quantity": quantity,
        "unit_cost_cents": unit_cost_cents,
    }


DEFAULT_PACK_LINE_ITEMS: List[Dict[str, Any]] = [
    {"line_code": "A_OXYGENATOR", "quantity": 1, "unit_cost_cents": 1055},
    {"line_code": "B_TUBING_PACK", "quantity": 1, "unit_cost_cents": 1155},
    {"line_code": "C_CANNULA_SET", "quantity": 1, "unit_cost_cents": 1255},
]

DEFAULT_SAFETY_CHECK_CODES: List[str] = [
    "ACT_BASELINE",
    "CIRCUIT_INTEGRITY",
    "GAS_LINE",
]


def build_preference_card(surgeon_id: str, **overrides) -> Dict[str, Any]:
    """A complete card recipe for one procedure type."""
    return _merge(
        {
            "surgeon_id": surgeon_id,
            "procedure_type": "CABG",
            "standard_pump_minutes": 150,
            "prime_volume_ml": 1500,
            "pack_line_items": [dict(item) for item in DEFAULT_PACK_LINE_ITEMS],
            "required_safety_check_codes": list(DEFAULT_SAFETY_CHECK_CODES),
            "blood_management_protocol": "STANDARD",
            "min_hematocrit_pct": 22,
            "revision": 1,
        },
        overrides,
    )


# ─── Perfusionists, certifications and CE claims ──────
def build_perfusionist(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Rafe Mbeki",
            "employee_code": "EMP-1001",
            "ecmo_privileged": True,
            "career_case_count": 150,
        },
        overrides,
    )


def build_certification(**overrides) -> Dict[str, Any]:
    """A certification cycle whose expiry is strictly after its issue instant."""
    return _merge(
        {
            "cert_code": "CCP",
            "issued_on": "2026-01-01T00:00:00Z",
            "expires_on": "2026-12-31T00:00:00Z",
            "cycle_credit_requirement": 45,
        },
        overrides,
    )


def build_ce_activity(**overrides) -> Dict[str, Any]:
    return _merge(
        {
            "category": "CLINICAL",
            "credit_hours": 20,
            "activity_date": "2026-03-01T00:00:00Z",
            "accreditation_body": "ABCP",
        },
        overrides,
    )


def build_ce_decision(decision: str = "VERIFIED", **overrides) -> Dict[str, Any]:
    """A back-office adjudication of VERIFIED, REJECTED or REVOKED."""
    return _merge({"decision": decision}, overrides)


# ─── Devices and their events ─────────────────────────
def build_perfusion_device(contract_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "contract_id": contract_id,
            "asset_tag": "HLM-001",
            "device_class": "HEART_LUNG_MACHINE",
        },
        overrides,
    )


def build_device_event_log(event_code: str, **overrides) -> Dict[str, Any]:
    """A captured machine event naming its event code."""
    return _merge({"event_code": event_code}, overrides)


def build_service_completion(**overrides) -> Dict[str, Any]:
    """Preventive service takes no required input of its own."""
    return _merge({}, overrides)


# ─── Call rotation slots ──────────────────────────────
def build_call_rotation_slot(contract_id: str, perfusionist_id: str, **overrides) -> Dict[str, Any]:
    """An on-call window, half-open from window_start to window_end."""
    return _merge(
        {
            "contract_id": contract_id,
            "perfusionist_id": perfusionist_id,
            "slot_type": "PRIMARY_CALL",
            "window_start": "2026-08-01T00:00:00Z",
            "window_end": "2026-08-04T00:00:00Z",
        },
        overrides,
    )


# ─── Bypass cases and their operations ────────────────
def build_bypass_case(contract_id: str, surgeon_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "contract_id": contract_id,
            "surgeon_id": surgeon_id,
            "procedure_type": "CABG",
            "scheduled_start": "2026-08-02T06:00:00Z",
            "scheduled_end": "2026-08-02T12:00:00Z",
            "acuity": "ELECTIVE",
        },
        overrides,
    )


def build_assignment(perfusionist_id: str, expected_case_version: int, **overrides) -> Dict[str, Any]:
    """An assignment carrying the client's last observed case version."""
    return _merge(
        {
            "perfusionist_id": perfusionist_id,
            "expected_case_version": expected_case_version,
        },
        overrides,
    )


def build_substitution(
    line_code: str,
    replacement_code: str,
    replacement_unit_cost_cents: int,
    reason: str = "Preferred vendor out of stock",
) -> Dict[str, Any]:
    """One requested line replacement against the selected card."""
    return {
        "line_code": line_code,
        "replacement_code": replacement_code,
        "replacement_unit_cost_cents": replacement_unit_cost_cents,
        "reason": reason,
    }


def build_pack_configuration(primary_device_id: str, **overrides) -> Dict[str, Any]:
    """A pack configuration naming the primary machine."""
    return _merge({"primary_device_id": primary_device_id}, overrides)


def build_pack_decision(decision: str = "APPROVED", **overrides) -> Dict[str, Any]:
    """The owning surgeon's adjudication of a pending pack."""
    return _merge({"decision": decision}, overrides)


def build_check_result(check_code: str, passed: bool = True, note: str = "verified at setup") -> Dict[str, Any]:
    return {"check_code": check_code, "passed": passed, "note": note}


def build_pump_checklist(**overrides) -> Dict[str, Any]:
    """A checklist recording every safety check on the default card as passed."""
    return _merge(
        {
            "check_results": [build_check_result(code) for code in DEFAULT_SAFETY_CHECK_CODES],
            "blood_management_protocol": "STANDARD",
            "hematocrit_pct": 30,
        },
        overrides,
    )


def build_end_bypass(**overrides) -> Dict[str, Any]:
    """The clinical record written when the case comes off pump."""
    return _merge(
        {
            "pump_time_minutes": 150,
            "cross_clamp_minutes": 90,
            "lowest_hematocrit_pct": 24,
            "adverse_event_count": 0,
        },
        overrides,
    )


# ─── ECMO runs ────────────────────────────────────────
def build_ecmo_run(mode: str = "VA", **overrides) -> Dict[str, Any]:
    """The only field the caller supplies for a run is its support mode."""
    return _merge({"mode": mode}, overrides)


def build_ecmo_handoff(relief_slot_id: str, **overrides) -> Dict[str, Any]:
    return _merge({"relief_slot_id": relief_slot_id}, overrides)


# ─── Incident reports ─────────────────────────────────
def build_incident_report(case_id: str, involved_perfusionist_id: str, **overrides) -> Dict[str, Any]:
    return _merge(
        {
            "case_id": case_id,
            "involved_perfusionist_id": involved_perfusionist_id,
            "severity": "MINOR",
            "category": "CIRCUIT",
            "narrative": "Circuit pressure trended high during rewarming and was corrected.",
        },
        overrides,
    )


def build_incident_review(decision: str = "ACCEPT_FOR_REVIEW", **overrides) -> Dict[str, Any]:
    """A chief's review decision of ACCEPT_FOR_REVIEW or RETURN_FOR_INFO."""
    return _merge({"decision": decision}, overrides)


def build_incident_close(finding: str = "ISOLATED", **overrides) -> Dict[str, Any]:
    """A chief's closing finding of ISOLATED or SYSTEMIC."""
    return _merge({"finding": finding}, overrides)


# ─── Logical clock ────────────────────────────────────
def build_clock(current_utc: str, **overrides) -> Dict[str, Any]:
    """A target instant for the server's only time source."""
    return _merge({"current_utc": current_utc}, overrides)
