"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_program_payload(**overrides) -> dict:
    """§3.1 Program create inputs."""
    defaults = {
        "name": "VS Fund",
        "fiscal_year": 2026,
        "total_budget_cents": 10000000,
        "overall_case_cap_cents": 5000000,
        "medical_cap_cents": 3000000,
        "lost_wage_cap_cents": 2000000,
        "funeral_cap_cents": 1000000,
        "mental_health_cap_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(program_id, **overrides) -> dict:
    """§3.2 VictimCase create inputs. cooperation_status omitted -> server default PENDING."""
    defaults = {
        "program_id": program_id,
        "victim_name": "Jane Roe",
        "incident_date": "2026-01-01",
        "crime_type": "ASSAULT",
        "reported_to_le": True,
        "cooperation_status": "COOPERATIVE",
        "filing_date": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(case_id, category="MEDICAL", **overrides) -> dict:
    """§3.3 Claim create inputs. Category-specific fields supplied via overrides."""
    defaults = {"case_id": case_id, "category": category}
    if category == "LOST_WAGE":
        defaults.update({
            "weekly_wage_cents": 100000,
            "num_weeks": 4,
            "disability_start_date": "2026-01-01",
            "disability_end_date": "2026-02-01",
        })
    else:
        defaults["claimed_amount_cents"] = 500000
    defaults.update(overrides)
    return defaults


def create_collateral_source_payload(claim_id, **overrides) -> dict:
    """§3.4 CollateralSource create inputs."""
    defaults = {
        "claim_id": claim_id,
        "source_type": "HEALTH_INSURANCE",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_award_payload(case_id, expected_program_version, **overrides) -> dict:
    """§3.6 Award create inputs (carries OCC token)."""
    defaults = {
        "case_id": case_id,
        "expected_program_version": expected_program_version,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(award_id, **overrides) -> dict:
    """§3.7 Disbursement create inputs."""
    defaults = {
        "award_id": award_id,
        "payee_type": "VICTIM",
        "amount_cents": 100000,
        "pay_run_date": "2026-05-10",
    }
    defaults.update(overrides)
    return defaults


def create_recovery_payload(case_id, **overrides) -> dict:
    """§3.8 RestitutionRecovery create inputs."""
    defaults = {
        "case_id": case_id,
        "offender_name": "John Doe",
        "ordered_amount_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_receipt_payload(**overrides) -> dict:
    """§3.8 RecoveryReceipt create inputs (recovery_id comes from path)."""
    defaults = {
        "amount_cents": 200000,
        "received_date": "2026-05-05",
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(case_id, **overrides) -> dict:
    """§3.9 Appeal create inputs."""
    defaults = {
        "case_id": case_id,
        "appeal_reason": "Reconsideration requested",
    }
    defaults.update(overrides)
    return defaults
