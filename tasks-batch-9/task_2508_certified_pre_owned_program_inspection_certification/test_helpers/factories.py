"""Payload factories — one per write operation, input fields only.

Every factory accepts `**overrides` so a test controls exactly the field it is
exercising and inherits sane defaults for everything else. Passing
`field=None` removes the key from the payload, which is how an omission test is
written.

Only fields the PRD declares as inputs appear here; derived and system-managed
fields are never sent.
"""

from typing import List, Optional

DEFAULTS = {
    "DEALER_NAME": "Coast Motors",
    "FRANCHISE_CODE": "FR-1001",
    "REGION_CODE": "WEST",
    "PEER_DEALER_NAME": "Summit Auto",
    "PEER_FRANCHISE_CODE": "FR-2002",
    "PEER_REGION_CODE": "EAST",
    "TECHNICIAN_NAME": "Ada Tech",
    "CREDENTIAL_ID": "CR-1",
    "CREDENTIAL_EXPIRES_AT": "2027-01-01T00:00:00Z",
    "TEMPLATE_CODE": "MPI-172",
    "TEMPLATE_EFFECTIVE_FROM": "2026-01-01",
    "VIN": "1HGCM82633A000001",
    "MODEL_YEAR": 2022,
    "IN_SERVICE_DATE": "2022-02-01",
    "ODOMETER_MILES": 62000,
    "STARTED_AT": "2026-07-31T09:00:00Z",
    "LISTING_PRICE_CENTS": 2895000,
    "CUSTOMER_REFERENCE": "CUST-1",
    "COMPLAINT_DESCRIPTION": "brake noise two days after delivery",
}


def _clean(payload: dict) -> dict:
    """Drop keys explicitly set to None so omission is expressible as an override."""
    return {k: v for k, v in payload.items() if v is not None}


def vin_for(sequence: int) -> str:
    """A distinct 17-character VIN per sequence number, as §3.2 requires."""
    return f"1HGCM82633A{sequence:06d}"


# ───────────────────────────── logical clock ─────────────────────────────

def set_clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}


# ─────────────────────── programme configuration ─────────────────────────

def program_config_payload(**overrides) -> dict:
    """A retune carries any subset of the tunables; there are no defaults."""
    return _clean(dict(overrides))


# ────────────────────────────── dealers ──────────────────────────────────

def create_dealer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["DEALER_NAME"],
        "franchise_code": DEFAULTS["FRANCHISE_CODE"],
        "region_code": DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return _clean(payload)


def peer_dealer_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PEER_DEALER_NAME"],
        "franchise_code": DEFAULTS["PEER_FRANCHISE_CODE"],
        "region_code": DEFAULTS["PEER_REGION_CODE"],
    }
    payload.update(overrides)
    return _clean(payload)


def privilege_payload(privilege_status: str, privilege_reason: Optional[str] = None) -> dict:
    return _clean(
        {"privilege_status": privilege_status, "privilege_reason": privilege_reason}
    )


# ──────────────────────────── technicians ────────────────────────────────

def create_technician_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TECHNICIAN_NAME"],
        "credential_id": DEFAULTS["CREDENTIAL_ID"],
        "credential_expires_at": DEFAULTS["CREDENTIAL_EXPIRES_AT"],
        "credential_status": "ACTIVE",
    }
    payload.update(overrides)
    return _clean(payload)


# ──────────────────────── checklist catalogue ────────────────────────────

def create_template_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["TEMPLATE_CODE"],
        "effective_from": DEFAULTS["TEMPLATE_EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return _clean(payload)


def checklist_item_payload(**overrides) -> dict:
    payload = {
        "item_code": "P1",
        "category": "POWERTRAIN",
        "severity": "CRITICAL",
        "pass_criteria": "no engine or transmission fault codes",
    }
    payload.update(overrides)
    return _clean(payload)


def item_p1_payload(**overrides) -> dict:
    """`P1` — POWERTRAIN, CRITICAL, uncurable: a failure here ends the inspection."""
    payload = {
        "item_code": "P1",
        "category": "POWERTRAIN",
        "severity": "CRITICAL",
        "pass_criteria": "no engine or transmission fault codes",
        "reconditioning_allowed": False,
    }
    payload.update(overrides)
    return _clean(payload)


def item_s1_payload(**overrides) -> dict:
    """`S1` — SAFETY, CRITICAL, repairable with a 200000-cent per-item ceiling."""
    payload = {
        "item_code": "S1",
        "category": "SAFETY",
        "severity": "CRITICAL",
        "pass_criteria": "all airbag and restraint systems nominal",
        "reconditioning_allowed": True,
        "max_reconditioning_cost_cents": 200000,
    }
    payload.update(overrides)
    return _clean(payload)


def item_b1_payload(**overrides) -> dict:
    """`B1` — BRAKES, MAJOR, measured on the inclusive band 4.0 .. 12.0 mm."""
    payload = {
        "item_code": "B1",
        "category": "BRAKES",
        "severity": "MAJOR",
        "pass_criteria": "pad thickness within 4.0..12.0 mm",
        "min_measure": 4.0,
        "max_measure": 12.0,
        "reconditioning_allowed": True,
        "max_reconditioning_cost_cents": 100000,
    }
    payload.update(overrides)
    return _clean(payload)


def item_t1_payload(**overrides) -> dict:
    """`T1` — TIRES, MAJOR, repairable with a 200000-cent per-item ceiling."""
    payload = {
        "item_code": "T1",
        "category": "TIRES",
        "severity": "MAJOR",
        "pass_criteria": "tread depth above the wear bars on all four tires",
        "reconditioning_allowed": True,
        "max_reconditioning_cost_cents": 200000,
    }
    payload.update(overrides)
    return _clean(payload)


# ────────────────────────────── vehicles ─────────────────────────────────

def create_vehicle_payload(**overrides) -> dict:
    payload = {
        "vin": DEFAULTS["VIN"],
        "model_year": DEFAULTS["MODEL_YEAR"],
        "in_service_date": DEFAULTS["IN_SERVICE_DATE"],
        "odometer_miles": DEFAULTS["ODOMETER_MILES"],
        "title_brand": "CLEAN",
        "prior_use": "PERSONAL",
        "owner_count": 1,
    }
    payload.update(overrides)
    return _clean(payload)


def history_event_payload(event_type: str, **overrides) -> dict:
    payload = {"event_type": event_type}
    payload.update(overrides)
    return _clean(payload)


# ───────────────────────────── inspections ───────────────────────────────

def create_inspection_payload(
    vehicle_id: str,
    technician_id: str,
    template_id: str,
    **overrides,
) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "technician_id": technician_id,
        "template_id": template_id,
        "started_at": DEFAULTS["STARTED_AT"],
        "odometer_at_inspection": DEFAULTS["ODOMETER_MILES"],
    }
    payload.update(overrides)
    return _clean(payload)


def result_row(item_code: str, outcome: str, measured_value: Optional[float] = None) -> dict:
    """One recorded checklist outcome. `measured_value` is omitted when null."""
    return _clean(
        {
            "item_code": item_code,
            "outcome": outcome,
            "measured_value": measured_value,
        }
    )


def results_payload(rows: List[dict]) -> dict:
    return {"results": rows}


def clean_attempt_rows() -> List[dict]:
    """A whole-checklist PASS across the canonical P1 / S1 / B1 template."""
    return [
        result_row("P1", "PASS"),
        result_row("S1", "PASS"),
        result_row("B1", "PASS", measured_value=8.0),
    ]


def complete_reconditioning_payload(actual_cost_cents: Optional[int], **overrides) -> dict:
    payload = {"resolution": "COMPLETED", "actual_cost_cents": actual_cost_cents}
    payload.update(overrides)
    return _clean(payload)


def waive_reconditioning_payload(waiver_reason: Optional[str], **overrides) -> dict:
    payload = {"resolution": "WAIVED", "waiver_reason": waiver_reason}
    payload.update(overrides)
    return _clean(payload)


# ──────────────────────────── certifications ─────────────────────────────

def document(doc_type: str, reference: str) -> dict:
    return {"doc_type": doc_type, "reference": reference}


def documents_without_reconditioning(suffix: str = "1") -> List[dict]:
    """The three unconditionally required document types (§3.6)."""
    return [
        document("TITLE_HISTORY_REPORT", f"THR-{suffix}"),
        document("INSPECTION_WORKSHEET", f"IW-{suffix}"),
        document("CUSTOMER_DISCLOSURE", f"CD-{suffix}"),
    ]


def documents_with_reconditioning(suffix: str = "1") -> List[dict]:
    """All four types, for a backing inspection that generated repairs (§3.6)."""
    return documents_without_reconditioning(suffix) + [
        document("RECONDITIONING_INVOICE", f"RI-{suffix}")
    ]


def create_certification_payload(
    vehicle_id: str,
    inspection_id: str,
    expected_vehicle_version,
    documents: Optional[List[dict]] = None,
    **overrides,
) -> dict:
    payload = {
        "vehicle_id": vehicle_id,
        "inspection_id": inspection_id,
        "expected_vehicle_version": expected_vehicle_version,
        "documents": (
            documents_without_reconditioning() if documents is None else documents
        ),
    }
    payload.update(overrides)
    return _clean(payload)


def adjudication_payload(decision: str = "APPROVE", rejection_reason: Optional[str] = None) -> dict:
    return _clean({"decision": decision, "rejection_reason": rejection_reason})


def decertify_payload(decertification_reason: str = "ADMIN_ACTION") -> dict:
    return {"decertification_reason": decertification_reason}


# ────────────────────────────── listings ─────────────────────────────────

def create_listing_payload(certification_id: str, **overrides) -> dict:
    payload = {
        "certification_id": certification_id,
        "channel": "OEM_SITE",
        "price_cents": DEFAULTS["LISTING_PRICE_CENTS"],
        "disclosure_fields": [
            "CERTIFIED_BADGE",
            "WARRANTY_END_DATE",
            "INSPECTION_DATE",
            "CERTIFICATION_NUMBER",
        ],
    }
    payload.update(overrides)
    return _clean(payload)


def syndicate_payload(expected_certification_version) -> dict:
    return {"expected_certification_version": expected_certification_version}


# ─────────────────────────── warranty claims ─────────────────────────────

def create_claim_payload(certification_id: str, **overrides) -> dict:
    payload = {
        "certification_id": certification_id,
        "component_category": "BRAKES",
        "repair_date": "2026-08-15",
        "repair_odometer_miles": 63000,
        "claimed_amount_cents": 100000,
    }
    payload.update(overrides)
    return _clean(payload)


def claim_adjudication_payload(decision: str = "APPROVE", denial_reason: Optional[str] = None) -> dict:
    return _clean({"decision": decision, "denial_reason": denial_reason})


# ───────────────────────────── complaints ────────────────────────────────

def create_complaint_payload(certification_id: str, **overrides) -> dict:
    payload = {
        "certification_id": certification_id,
        "customer_reference": DEFAULTS["CUSTOMER_REFERENCE"],
        "category": "INSPECTION_ITEM_FAILURE",
        "description": DEFAULTS["COMPLAINT_DESCRIPTION"],
    }
    payload.update(overrides)
    return _clean(payload)


# ─────────────────────────── audit sampling ──────────────────────────────

def audit_finding_payload(finding: str, finding_code: Optional[str] = None) -> dict:
    return _clean({"finding": finding, "finding_code": finding_code})
