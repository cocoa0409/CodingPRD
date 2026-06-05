"""Payload factories — one per entity, input fields only.

Every test starts against an empty database (the harness restarts the server
before each test), but a single test may register several debtors; debtor email
is unique across debtors, so create_debtor_payload mints a fresh email per call.
"""
import uuid

from .constants import TEST_DEFAULTS


def _unique_email() -> str:
    return f"debtor-{uuid.uuid4().hex[:12]}@example.com"


def create_debtor_payload(**overrides) -> dict:
    """Debtor input: full_name, email (unique), prior_discharge_within_8y? (default false)."""
    defaults = {
        "full_name": "Test Debtor",
        "email": _unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_creditor_payload(**overrides) -> dict:
    """Creditor input: name."""
    defaults = {"name": "Test Creditor"}
    defaults.update(overrides)
    return defaults


def create_trustee_payload(**overrides) -> dict:
    """Trustee input: name."""
    defaults = {"name": "Test Trustee"}
    defaults.update(overrides)
    return defaults


def create_case_payload(debtor_id: str, **overrides) -> dict:
    """Case input: debtor_id, filed_chapter, state_code, household_size."""
    defaults = {
        "debtor_id": debtor_id,
        "filed_chapter": "CHAPTER_13",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "household_size": TEST_DEFAULTS["HOUSEHOLD_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_means_test_payload(case_id: str, **overrides) -> dict:
    """MeansTest input: case_id, cmi_monthly_cents, monthly_expenses_cents,
    median_annual_income_cents."""
    defaults = {
        "case_id": case_id,
        "cmi_monthly_cents": 400_000,
        "monthly_expenses_cents": 300_000,
        "median_annual_income_cents": TEST_DEFAULTS["MEDIAN_ANNUAL_INCOME_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(case_id: str, schedule_letter: str, **overrides) -> dict:
    """Schedule input: case_id, schedule_letter, description,
    asset_value_cents? (default 0), claimed_exempt_value_cents? (default 0)."""
    defaults = {
        "case_id": case_id,
        "schedule_letter": schedule_letter,
        "description": "line item",
    }
    defaults.update(overrides)
    return defaults


def create_debt_payload(case_id: str, creditor_id: str, **overrides) -> dict:
    """Debt input: case_id, creditor_id, debt_class, scheduled_amount_cents."""
    defaults = {
        "case_id": case_id,
        "creditor_id": creditor_id,
        "debt_class": "UNSECURED",
        "scheduled_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(case_id: str, trustee_id: str, **overrides) -> dict:
    """Meeting341 input: case_id, trustee_id, room_code, scheduled_start, scheduled_end."""
    defaults = {
        "case_id": case_id,
        "trustee_id": trustee_id,
        "room_code": "ROOM-1",
        "scheduled_start": "2026-07-01T09:00:00Z",
        "scheduled_end": "2026-07-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(case_id: str, debt_id: str, filed_by_creditor_id: str,
                         **overrides) -> dict:
    """ClaimRecord input: case_id, debt_id, filed_by_creditor_id, claimed_amount_cents."""
    defaults = {
        "case_id": case_id,
        "debt_id": debt_id,
        "filed_by_creditor_id": filed_by_creditor_id,
        "claimed_amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(case_id: str, expected_case_version: int, **overrides) -> dict:
    """Plan input: case_id, monthly_payment_cents, plan_duration_months,
    expected_case_version."""
    defaults = {
        "case_id": case_id,
        "monthly_payment_cents": 50_000,
        "plan_duration_months": 36,
        "expected_case_version": expected_case_version,
    }
    defaults.update(overrides)
    return defaults


def create_plan_payment_payload(plan_id: str, **overrides) -> dict:
    """PlanPayment input: plan_id, amount_cents."""
    defaults = {
        "plan_id": plan_id,
        "amount_cents": 50_000,
    }
    defaults.update(overrides)
    return defaults


def create_stay_relief_motion_payload(case_id: str, movant_creditor_id: str,
                                      target_debt_id: str, **overrides) -> dict:
    """StayReliefMotion input: case_id, movant_creditor_id, target_debt_id."""
    defaults = {
        "case_id": case_id,
        "movant_creditor_id": movant_creditor_id,
        "target_debt_id": target_debt_id,
    }
    defaults.update(overrides)
    return defaults
