"""Payload factories — one per resource, input fields only.

Every factory accepts `**overrides` so a test can control exactly the field it is
exercising and inherit sensible values for everything else. Passing `None`
explicitly is honoured, so `create_nomination_payload(eca_documentation_ref=None)`
sends a null reference rather than dropping the key.
"""

# Canonical reference-data values reused across the suite.
PORT_CODE_ROTTERDAM = "NLRTM"
PORT_CODE_ANTWERP = "BEANR"
GRADE_CODE_MGO = "MGO-DMA"
GRADE_CODE_HSFO = "HSFO-380"
GRADE_CODE_VLSFO = "VLSFO-RME"


# ─── Logical clock ────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ─── Reference data ───────────────────────────────────

def create_port_payload(**overrides) -> dict:
    """An Emission Control Area port with a 24-hour notice period."""
    payload = {
        "port_code": PORT_CODE_ROTTERDAM,
        "name": "Rotterdam",
        "eca_zone": True,
        "eca_sulfur_limit_pct": 0.100,
        "notice_lead_hours": 24,
        "concurrent_ops_capacity": 2,
        "spill_response_tier": "TIER_1",
    }
    payload.update(overrides)
    return payload


def create_fuel_grade_payload(**overrides) -> dict:
    """A distillate marine gas oil permitted inside an Emission Control Area."""
    payload = {
        "grade_code": GRADE_CODE_MGO,
        "max_sulfur_pct": 0.100,
        "eca_permitted": True,
        "test_tolerance_pct": 0.010,
        "index_code": "MGO-ARA",
        "base_barging_rate_usd_per_mt": 9.50,
        "min_barging_fee_usd": 2000.00,
        "cross_contamination_group": "DISTILLATE",
    }
    payload.update(overrides)
    return payload


def create_index_quote_payload(grade_id: str, **overrides) -> dict:
    payload = {
        "grade_id": grade_id,
        "quote_date": "2026-08-03T00:00:00Z",
        "price_usd_per_mt": 705.00,
        "source": "PLATTS",
    }
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {
        "name": "Aegean Lines",
        "credit_limit_usd": 5000000.00,
        "payment_terms_days": 30,
        "settlement_basis": "SUPPLIER_FIGURES",
    }
    payload.update(overrides)
    return payload


def credit_review_payload(**overrides) -> dict:
    """Both fields are optional replacements; pass only what the test revises."""
    payload = {}
    payload.update(overrides)
    return payload


def create_delivery_asset_payload(home_port_id: str, **overrides) -> dict:
    payload = {
        "name": "Bunker Alpha",
        "asset_type": "BARGE",
        "capacity_mt": 3000.000,
        "home_port_id": home_port_id,
        "boom_certified": True,
        "segregated_tanks": False,
        "turnaround_buffer_minutes": 90,
    }
    payload.update(overrides)
    return payload


# ─── Nominations ──────────────────────────────────────

def create_nomination_payload(customer_id: str, port_id: str, grade_id: str, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "port_id": port_id,
        "grade_id": grade_id,
        "vessel_imo": "9123456",
        "vessel_name": "MV Anemos",
        "scrubber_fitted": False,
        "nominated_quantity_mt": 1200.000,
        "window_start": "2026-08-10T06:00:00Z",
        "window_end": "2026-08-11T06:00:00Z",
        "delivery_mode": "BARGE",
        "declared_sulfur_pct": 0.100,
        "eca_documentation_ref": "CHG-2026-0001",
    }
    payload.update(overrides)
    return payload


def compliance_review_payload(decision: str) -> dict:
    return {"decision": decision}


def auto_schedule_payload(requested_slot_start: str, expected_nomination_version: int) -> dict:
    return {
        "requested_slot_start": requested_slot_start,
        "expected_nomination_version": expected_nomination_version,
    }


# ─── Delivery orders ──────────────────────────────────

def create_delivery_order_payload(nomination_id: str, asset_id: str,
                                  expected_nomination_version: int, **overrides) -> dict:
    payload = {
        "nomination_id": nomination_id,
        "asset_id": asset_id,
        "planned_quantity_mt": 1200.000,
        "slot_start": "2026-08-10T06:00:00Z",
        "slot_end": "2026-08-10T12:00:00Z",
        "expected_nomination_version": expected_nomination_version,
    }
    payload.update(overrides)
    return payload


def clear_payload(port_clearance_ref: str = "PA-RTM-0001") -> dict:
    return {"port_clearance_ref": port_clearance_ref}


def complete_pumping_payload(**overrides) -> dict:
    """The canonical three figures: barge sounding, vessel sounding, meter."""
    payload = {
        "barge_sounding_mt": 1198.450,
        "vessel_sounding_mt": 1191.200,
        "meter_mt": 1197.800,
    }
    payload.update(overrides)
    return payload


def joint_survey_payload(surveyed_mt: float) -> dict:
    return {"surveyed_mt": surveyed_mt}


def quantity_decision_payload(decision: str) -> dict:
    return {"decision": decision}


# ─── Delivery notes ───────────────────────────────────

def create_bdn_payload(delivery_order_id: str, **overrides) -> dict:
    payload = {
        "delivery_order_id": delivery_order_id,
        "bdn_number": "BDN-2026-0001",
        "declared_sulfur_pct": 0.098,
        "sample_seal_number": "SEAL-0001",
    }
    payload.update(overrides)
    return payload


# ─── Quality claims, analyses and remediation ─────────

def create_quality_claim_payload(bdn_id: str, **overrides) -> dict:
    payload = {
        "bdn_id": bdn_id,
        "claimed_defect": "SULFUR_EXCEEDANCE",
        "affected_quantity_mt": 400.000,
    }
    payload.update(overrides)
    return payload


def create_lab_analysis_payload(claim_id: str, expected_claim_version: int, **overrides) -> dict:
    payload = {
        "claim_id": claim_id,
        "lab_ref": "LAB-0001",
        "measured_sulfur_pct": 0.135,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def claim_decision_payload(decision: str, **overrides) -> dict:
    payload = {"decision": decision}
    if decision == "PROPOSE":
        payload["remediation_type"] = "PRICE_ALLOWANCE"
    payload.update(overrides)
    return payload


# ─── Invoices ─────────────────────────────────────────

def create_invoice_payload(delivery_order_id: str, **overrides) -> dict:
    payload = {
        "delivery_order_id": delivery_order_id,
        "pricing_date": "2026-08-10T12:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── Spill incidents ──────────────────────────────────

def create_spill_incident_payload(delivery_order_id: str, **overrides) -> dict:
    payload = {
        "delivery_order_id": delivery_order_id,
        "reported_at": "2026-08-10T06:45:00Z",
        "volume_liters": 250.00,
        "boom_deployed": False,
    }
    payload.update(overrides)
    return payload


def confirm_containment_payload(response_ref: str = "RESP-RTM-0001") -> dict:
    return {"response_ref": response_ref}


__all__ = [
    "PORT_CODE_ROTTERDAM",
    "PORT_CODE_ANTWERP",
    "GRADE_CODE_MGO",
    "GRADE_CODE_HSFO",
    "GRADE_CODE_VLSFO",
    "set_clock_payload",
    "create_port_payload",
    "create_fuel_grade_payload",
    "create_index_quote_payload",
    "create_customer_payload",
    "credit_review_payload",
    "create_delivery_asset_payload",
    "create_nomination_payload",
    "compliance_review_payload",
    "auto_schedule_payload",
    "create_delivery_order_payload",
    "clear_payload",
    "complete_pumping_payload",
    "joint_survey_payload",
    "quantity_decision_payload",
    "create_bdn_payload",
    "create_quality_claim_payload",
    "create_lab_analysis_payload",
    "claim_decision_payload",
    "create_invoice_payload",
    "create_spill_incident_payload",
    "confirm_containment_payload",
]
