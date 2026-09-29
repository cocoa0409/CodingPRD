"""Payload factories — one per write endpoint, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """Monotonic suffix for fields the board requires to be unique."""
    return f"{next(_counter):04d}"


# ─── Standing registry ────────────────────────────────────────────────────────

def create_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Livestock Ranch",
        "mailing_state": TEST_DEFAULTS["MAILING_STATE"],
        "contact_email": "owner@example.test",
    }
    defaults.update(overrides)
    return defaults


def create_territory_payload(**overrides) -> dict:
    defaults = {
        "territory_code": f"T-{unique_suffix()}",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "travel_surcharge_cents": TEST_DEFAULTS["TRAVEL_SURCHARGE_CENTS"],
        "impound_capacity_head": TEST_DEFAULTS["IMPOUND_CAPACITY_HEAD"],
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(home_territory_id: str, **overrides) -> dict:
    defaults = {
        "badge_number": f"B-{unique_suffix()}",
        "home_territory_id": home_territory_id,
        "certification_expires_on": TEST_DEFAULTS["CERTIFICATION_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def set_inspector_status_payload(status: str) -> dict:
    return {"status": status}


# ─── Brand filings ────────────────────────────────────────────────────────────

def create_brand_application_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "application_type": "NEW",
        "brand_symbol": "7X",
        "position_code": "LEFT_RIB",
        "species_class": "CATTLE",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_renewal_application_payload(
    owner_id: str, expected_registration_version: int, **overrides
) -> dict:
    defaults = {
        "owner_id": owner_id,
        "expected_registration_version": expected_registration_version,
    }
    defaults.update(overrides)
    return defaults


def resubmit_application_payload(**overrides) -> dict:
    return dict(overrides)


def reject_application_payload(rejection_reason: str = "Not supported by the record") -> dict:
    return {"rejection_reason": rejection_reason}


# ─── Conflict claims ──────────────────────────────────────────────────────────

def create_conflict_claim_payload(
    claimant_owner_id: str, respondent_registration_id: str, **overrides
) -> dict:
    defaults = {
        "claimant_owner_id": claimant_owner_id,
        "respondent_registration_id": respondent_registration_id,
        "grounds": "PRIOR_USE",
    }
    defaults.update(overrides)
    return defaults


def decide_claim_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


# ─── Ownership instruments ────────────────────────────────────────────────────

def create_bill_of_sale_payload(
    seller_owner_id: str, buyer_owner_id: str, **overrides
) -> dict:
    defaults = {
        "seller_owner_id": seller_owner_id,
        "buyer_owner_id": buyer_owner_id,
        "document_number": f"BOS-{unique_suffix()}",
        "sale_date": "2026-08-01T00:00:00Z",
        "head_count": 10,
        "species_class": "CATTLE",
    }
    defaults.update(overrides)
    return defaults


# ─── Inspection work ──────────────────────────────────────────────────────────

def create_inspection_order_payload(
    owner_id: str, territory_id: str, **overrides
) -> dict:
    defaults = {
        "owner_id": owner_id,
        "territory_id": territory_id,
        "inspection_purpose": "SALE",
        "requested_window_start_at": "2026-08-10T08:00:00Z",
        "requested_window_end_at": "2026-08-10T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def schedule_order_payload(
    inspector_id: str,
    expected_inspector_version: int,
    scheduled_start_at: str = "2026-08-10T09:00:00Z",
    scheduled_end_at: str = "2026-08-10T11:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "inspector_id": inspector_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
        "expected_inspector_version": expected_inspector_version,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(head_count: int, **overrides) -> dict:
    defaults = {
        "species_class": "CATTLE",
        "head_count": head_count,
    }
    defaults.update(overrides)
    return defaults


def record_finding_payload(finding: str, **overrides) -> dict:
    defaults = {"finding": finding}
    defaults.update(overrides)
    return defaults


# ─── Estray disposition ───────────────────────────────────────────────────────

def estray_claim_decision_payload(decision: str) -> dict:
    return {"decision": decision}


def schedule_auction_payload(estimated_gross_cents: int) -> dict:
    return {"estimated_gross_cents": estimated_gross_cents}


def record_sale_payload(gross_proceeds_cents: int) -> dict:
    return {"gross_proceeds_cents": gross_proceeds_cents}


# ─── Theft caseload ───────────────────────────────────────────────────────────

def refer_investigation_payload(referral_agency: str = "MT Department of Livestock") -> dict:
    return {"referral_agency": referral_agency}


def close_investigation_payload(outcome: str) -> dict:
    return {"outcome": outcome}


# ─── Fees ─────────────────────────────────────────────────────────────────────

def create_fee_remittance_payload(
    owner_id: str, amount_cents: int, covered_order_ids: list, **overrides
) -> dict:
    defaults = {
        "owner_id": owner_id,
        "amount_cents": amount_cents,
        "covered_order_ids": covered_order_ids,
    }
    defaults.update(overrides)
    return defaults


def top_up_remittance_payload(additional_cents: int) -> dict:
    return {"additional_cents": additional_cents}


# ─── Logical clock ────────────────────────────────────────────────────────────

def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
