"""Payload factories — one per client-creatable entity, input fields only.

Disbursements are never created directly by a client (PRD §3.9: "Disbursements are
never created directly by a client; they are emitted by the settle, rental-approval,
and subrogation-resolution cascades"), so there is no disbursement factory.
"""

# A wide default coverage window so claims dated in mid-2026 fall inside it.
DEFAULT_EFFECTIVE = "2026-01-01T00:00:00.000Z"
DEFAULT_EXPIRATION = "2026-12-31T00:00:00.000Z"
DEFAULT_LOSS_DATETIME = "2026-06-01T00:00:00.000Z"


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "policyholder_name": "Test Policyholder",
        "policy_number": "POL-TEST-1",
        "effective_date": DEFAULT_EFFECTIVE,
        "expiration_date": DEFAULT_EXPIRATION,
        "comparative_fault_rule": "PURE",
    }
    defaults.update(overrides)
    return defaults


def create_coverage_payload(**overrides) -> dict:
    defaults = {
        "coverage_type": "COLLISION",
        "limit_cents": 1_000_000,
        "deductible_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_rental_coverage_payload(**overrides) -> dict:
    defaults = {
        "coverage_type": "RENTAL",
        "limit_cents": 100_000,
        "rental_daily_cap_cents": 5_000,
        "rental_max_days": 10,
    }
    defaults.update(overrides)
    return defaults


def create_adjuster_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Adjuster",
        "license_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "loss_datetime": DEFAULT_LOSS_DATETIME,
        "loss_type": "COLLISION",
        "vehicle_acv_cents": 800_000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_party_payload(claim_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "party_role": "THIRD_PARTY",
        "display_name": "Other Driver",
    }
    defaults.update(overrides)
    return defaults


def create_repair_estimate_payload(claim_id: str, lines=None, **overrides) -> dict:
    if lines is None:
        lines = [{"description": "body", "labor_cents": 400_000, "parts_cents": 200_000}]
    defaults = {
        "claim_id": claim_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_total_loss_evaluation_payload(claim_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
    }
    defaults.update(overrides)
    return defaults


def create_rental_reimbursement_payload(claim_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "rental_start_date": "2026-06-01T00:00:00.000Z",
        "rental_end_date": "2026-06-08T00:00:00.000Z",
        "daily_rate_cents": 6_000,
    }
    defaults.update(overrides)
    return defaults


def create_subrogation_case_payload(claim_id: str, target_party_id: str, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "target_party_id": target_party_id,
        "demand_cents": 400_000,
    }
    defaults.update(overrides)
    return defaults


def estimate_lines(repair_total_cents: int) -> list:
    """Build a single-line estimate whose repair_total_cents equals the requested total.

    PRD §3.4: repair_total_cents is the sum over lines of labor_cents + parts_cents.
    """
    return [{"description": "repair", "labor_cents": repair_total_cents, "parts_cents": 0}]
