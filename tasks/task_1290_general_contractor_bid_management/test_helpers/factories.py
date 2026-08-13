"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_bid_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Structural Steel — Tower A",
        "trade_code": "051200",
        "bid_due_at": TEST_DEFAULTS["BID_DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_subcontractor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Sub LLC",
        "contact_email": "sub@x.com",
        "license_number": "LIC-0001",
    }
    defaults.update(overrides)
    return defaults


def create_prequal_application_payload(subcontractor_id, **overrides) -> dict:
    defaults = {
        "subcontractor_id": subcontractor_id,
        "declared_annual_revenue_cents": TEST_DEFAULTS["DECLARED_REVENUE_CENTS"],
        "declared_emr": TEST_DEFAULTS["DECLARED_EMR"],
        "declared_bonding_capacity_cents": TEST_DEFAULTS["DECLARED_BONDING_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def prequal_decision_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def approve_decision_payload(**overrides) -> dict:
    defaults = {
        "decision": "APPROVED",
        "verified_annual_revenue_cents": TEST_DEFAULTS["VERIFIED_REVENUE_CENTS"],
        "verified_emr": TEST_DEFAULTS["VERIFIED_EMR"],
        "verified_bonding_capacity_cents": TEST_DEFAULTS["VERIFIED_BONDING_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def prequal_resubmit_payload(**overrides) -> dict:
    defaults = {
        "declared_annual_revenue_cents": TEST_DEFAULTS["DECLARED_REVENUE_CENTS"],
        "declared_emr": TEST_DEFAULTS["DECLARED_EMR"],
        "declared_bonding_capacity_cents": TEST_DEFAULTS["DECLARED_BONDING_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_invitation_payload(bid_package_id, subcontractor_id) -> dict:
    return {"bid_package_id": bid_package_id, "subcontractor_id": subcontractor_id}


def respond_invitation_payload(intent) -> dict:
    return {"intent": intent}


def create_addendum_payload(bid_package_id, **overrides) -> dict:
    defaults = {"bid_package_id": bid_package_id, "summary": "Addendum: scope change"}
    defaults.update(overrides)
    return defaults


def waive_addendum_payload(subcontractor_id, **overrides) -> dict:
    defaults = {"subcontractor_id": subcontractor_id}
    defaults.update(overrides)
    return defaults


def create_bid_payload(bid_package_id, **overrides) -> dict:
    base = overrides.pop("base_bid_cents", TEST_DEFAULTS["BASE_BID_CENTS"])
    defaults = {
        "bid_package_id": bid_package_id,
        "base_bid_cents": base,
        # Default bond covers exactly the default 5% requirement.
        "bond_amount_cents": overrides.pop("bond_amount_cents", int(base * 0.05)),
    }
    defaults.update(overrides)
    return defaults


def create_bid_revision_payload(new_base_bid_cents, expected_bid_version,
                                **overrides) -> dict:
    defaults = {
        "new_base_bid_cents": new_base_bid_cents,
        "expected_bid_version": expected_bid_version,
    }
    defaults.update(overrides)
    return defaults


def create_leveling_adjustment_payload(bid_id, **overrides) -> dict:
    defaults = {
        "bid_id": bid_id,
        "description": "scope line being leveled",
        "treatment": "GC_ALLOWANCE",
        "amount_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_post_bid_interview_payload(bid_id, **overrides) -> dict:
    defaults = {
        "bid_id": bid_id,
        "interview_room": "ROOM-1",
        "scheduled_start": "2026-08-15T10:00:00Z",
        "scheduled_end": "2026-08-15T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_interview_payload(**overrides) -> dict:
    defaults = {"outcome_notes": "scope confirmed"}
    defaults.update(overrides)
    return defaults


def create_award_recommendation_payload(bid_package_id, recommended_bid_id,
                                        expected_bid_package_version,
                                        **overrides) -> dict:
    defaults = {
        "bid_package_id": bid_package_id,
        "recommended_bid_id": recommended_bid_id,
        "rationale": "scope coverage, leveling outcome, interview result",
        "expected_bid_package_version": expected_bid_package_version,
    }
    defaults.update(overrides)
    return defaults


def decide_recommendation_payload(decision, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def send_feedback_payload(**overrides) -> dict:
    return dict(overrides)


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
