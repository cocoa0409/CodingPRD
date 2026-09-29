"""Payload factories — one per entity, carrying only client-supplied input fields.

Every factory takes ``**overrides`` and returns a plain dict. Passing an override
whose value is ``None`` keeps the key present with a null value (useful for
testing explicit nulls); use ``drop_keys()`` to omit a key entirely.
"""
import itertools

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotone per-process suffix for uniqueness-constrained string fields."""
    return str(next(_counter))


def drop_keys(payload: dict, *keys) -> dict:
    """Return a copy of payload with the named keys removed."""
    return {k: v for k, v in payload.items() if k not in keys}


# --------------------------------------------------------------------------
# CatastropheEvent
# --------------------------------------------------------------------------
def create_event_payload(**overrides) -> dict:
    defaults = {
        "cat_code": f"CAT-2026-{100 + next(_counter)}",
        "peril_type": "HURRICANE",
        "jurisdiction_state": "FL",
        "event_start_utc": "2026-08-01T00:00:00.000Z",
        "exposure_count": 1000,
        "avg_insured_value": 250000,
        "expected_severity_index": 0.0400,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# RegulatoryBulletin
# --------------------------------------------------------------------------
def create_bulletin_payload(event_id=None, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "bulletin_number": f"BUL-{unique_suffix()}",
        "jurisdiction_state": "FL",
        "bulletin_type": "CANCELLATION_MORATORIUM",
        "effective_from": "2026-08-01T00:00:00.000Z",
        "effective_to": "2026-12-01T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Adjuster
# --------------------------------------------------------------------------
def create_adjuster_payload(**overrides) -> dict:
    defaults = {
        "full_name": f"Adjuster {unique_suffix()}",
        "employment_type": "STAFF",
        "home_state": "FL",
        "licensed_states": ["FL"],
        "license_expiry_utc": "2027-06-30T00:00:00.000Z",
        "max_open_claims": 10,
        "daily_rate": 900,
        "per_diem_rate": 150,
        "desk_certified": False,
        "aerial_certified": False,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# HousingBlock
# --------------------------------------------------------------------------
def create_housing_block_payload(event_id=None, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "hotel_name": f"Hotel {unique_suffix()}",
        "city": "Tampa",
        "rooms_total": 40,
        "nightly_rate": 200,
        "block_start_date": "2026-09-01T00:00:00.000Z",
        "block_end_date": "2026-09-15T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Deployment
# --------------------------------------------------------------------------
def create_deployment_payload(event_id=None, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "role_type": "FIELD",
        "window_start_utc": "2026-09-01T00:00:00.000Z",
        "window_end_utc": "2026-09-11T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Claim
# --------------------------------------------------------------------------
def coverage_line(
    coverage_code="DWELLING",
    limit_amount=400000,
    deductible_amount=5000,
    estimated_damage_amount=150000,
) -> dict:
    return {
        "coverage_code": coverage_code,
        "limit_amount": limit_amount,
        "deductible_amount": deductible_amount,
        "estimated_damage_amount": estimated_damage_amount,
    }


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "policy_number": f"POL-{unique_suffix()}",
        "loss_state": "FL",
        "loss_date_utc": "2026-07-30T00:00:00.000Z",
        "reported_loss_amount": 120000,
        "coverage_lines": [coverage_line()],
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# InspectionAssignment
# --------------------------------------------------------------------------
def create_inspection_assignment_payload(claim_id=None, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "mode": "FIELD",
        "window_start_utc": "2026-09-02T00:00:00.000Z",
        "window_end_utc": "2026-09-03T00:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(verified_damage_amount=100000, **overrides) -> dict:
    defaults = {"verified_damage_amount": verified_damage_amount}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# AdvancePayment
# --------------------------------------------------------------------------
def create_advance_payment_payload(claim_id=None, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "requested_amount": 10000,
        "basis": "STRUCTURE_PARTIAL",
    }
    defaults.update(overrides)
    return defaults


def void_advance_payload(void_reason="Issued in error", **overrides) -> dict:
    defaults = {"void_reason": void_reason}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# ReserveEntry (manual append on a claim)
# --------------------------------------------------------------------------
def create_reserve_entry_payload(expected_claim_version=None, **overrides) -> dict:
    defaults = {
        "expected_claim_version": expected_claim_version,
        "entry_type": "REVISION",
        "delta_case_reserve": 1000.00,
        "delta_paid": 0.00,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# VendorFirm / VendorAssignment
# --------------------------------------------------------------------------
def create_vendor_firm_payload(**overrides) -> dict:
    defaults = {
        "firm_name": f"Firm {unique_suffix()}",
        "vendor_type": "MITIGATION",
        "service_states": ["FL"],
        "max_concurrent_jobs": 5,
        "performance_score": 90.00,
    }
    defaults.update(overrides)
    return defaults


def activate_vendor_firm_payload(event_id=None, **overrides) -> dict:
    defaults = {"event_id": event_id}
    defaults.update(overrides)
    return defaults


def create_vendor_assignment_payload(claim_id=None, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "scope_amount": 5000,
        "required_vendor_type": "MITIGATION",
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# LossEstimateSnapshot
# --------------------------------------------------------------------------
def create_loss_estimate_payload(event_id=None, expected_event_version=None, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "method": "EXPOSURE_BASED",
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# FileTransferBatch
# --------------------------------------------------------------------------
def create_batch_payload(event_id=None, **overrides) -> dict:
    defaults = {"event_id": event_id, "target_unit": "PROPERTY-EAST"}
    defaults.update(overrides)
    return defaults


def add_claim_to_batch_payload(claim_id=None, **overrides) -> dict:
    defaults = {"claim_id": claim_id}
    defaults.update(overrides)
    return defaults


def reject_batch_payload(rejection_reason="Membership incorrect", **overrides) -> dict:
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Adjuster licence waiver
# --------------------------------------------------------------------------
def apply_license_waiver_payload(event_id=None, **overrides) -> dict:
    defaults = {"event_id": event_id}
    defaults.update(overrides)
    return defaults


# --------------------------------------------------------------------------
# Cat-code assignment
# --------------------------------------------------------------------------
def assign_cat_code_payload(event_id=None, **overrides) -> dict:
    defaults = {"event_id": event_id}
    defaults.update(overrides)
    return defaults
