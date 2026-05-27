"""Entity construction + serialization helpers.

Every primary resource carries id/created_at/updated_at/version. VestingEvent
is the single exception (immutable, append-only) — it carries only id and
created_at per PRD §2.4.
"""

from __future__ import annotations

from typing import Any

import db
from services.calculations import vested_employer_balance
from services.clock_and_age import years_of_service


# -----------------------------------------------------------------------------
# Common-field helpers
# -----------------------------------------------------------------------------


def stamp_create(entity: dict[str, Any], *, immutable: bool = False) -> dict[str, Any]:
    """Stamp id/created_at/(updated_at/version) on a new record."""
    now = db.iso_ms(db.utc_now())
    entity["id"] = db.new_id()
    entity["created_at"] = now
    if not immutable:
        entity["updated_at"] = now
        entity["version"] = 1
    return entity


def stamp_update(entity: dict[str, Any]) -> None:
    """Bump updated_at + version on every mutation, per PRD §2.4 + §2.6."""
    entity["updated_at"] = db.iso_ms(db.utc_now())
    entity["version"] = int(entity.get("version", 0)) + 1


# -----------------------------------------------------------------------------
# Derived-field reconciliation for a Participant.
# -----------------------------------------------------------------------------


def _plan_vesting_schedule(plan_id: str) -> str:
    plan = db.plans.get(plan_id)
    if not plan:
        # Defensive — caller should have validated. Default to GRADED_6.
        return "GRADED_6"
    return plan.get("vesting_schedule", "GRADED_6")


def recompute_yos(p: dict[str, Any]) -> None:
    """Recompute years_of_service from the system clock and hire_date."""
    p["years_of_service"] = years_of_service(p["hire_date"])


def recompute_vested_balance(p: dict[str, Any]) -> None:
    """Recompute vested_employer_balance_cents from the participant's current
    employer_balance_cents and years_of_service under the plan's schedule."""
    recompute_yos(p)
    schedule = _plan_vesting_schedule(p["plan_id"])
    p["vested_employer_balance_cents"] = vested_employer_balance(
        employer_balance_cents=p["employer_balance_cents"],
        years_of_service=p["years_of_service"],
        vesting_schedule=schedule,
    )


def recompute_outstanding_loan_principal(p: dict[str, Any]) -> None:
    """Sum outstanding_principal_cents over the participant's DISBURSED loans."""
    pid = p["id"]
    total = 0
    for loan in db.loans.values():
        if loan["participant_id"] == pid and loan["status"] == "DISBURSED":
            total += loan["outstanding_principal_cents"]
    p["outstanding_loan_principal_cents"] = total


# -----------------------------------------------------------------------------
# Serialization (output shape).
# -----------------------------------------------------------------------------


def serialize_plan(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "plan_year": p["plan_year"],
        "match_formula": p["match_formula"],
        "vesting_schedule": p["vesting_schedule"],
        "annual_compensation_limit_cents": p["annual_compensation_limit_cents"],
        "annual_deferral_limit_cents": p["annual_deferral_limit_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_participant(p: dict) -> dict:
    # Refresh lazily-derived fields on every read per PRD §2.9.
    recompute_yos(p)
    # Note: do NOT recompute vested_employer_balance on every read — it must be
    # reconciled strictly by triggering events (contribution close, loan default,
    # hardship pay, RMD pay, YEAR_TICK). Doing it on read would silently change
    # state outside those triggers.
    return {
        "id": p["id"],
        "plan_id": p["plan_id"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "hire_date": p["hire_date"],
        "annual_compensation_cents": p["annual_compensation_cents"],
        "deferral_rate_bps": p["deferral_rate_bps"],
        "enrollment_status": p["enrollment_status"],
        "employee_balance_cents": p["employee_balance_cents"],
        "employer_balance_cents": p["employer_balance_cents"],
        "years_of_service": p["years_of_service"],
        "vested_employer_balance_cents": p["vested_employer_balance_cents"],
        "outstanding_loan_principal_cents": p["outstanding_loan_principal_cents"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_contribution_period(cp: dict) -> dict:
    return {
        "id": cp["id"],
        "participant_id": cp["participant_id"],
        "period_end_date": cp["period_end_date"],
        "gross_compensation_cents": cp["gross_compensation_cents"],
        "employee_contribution_cents": cp["employee_contribution_cents"],
        "employer_match_cents": cp["employer_match_cents"],
        "status": cp["status"],
        "created_at": cp["created_at"],
        "updated_at": cp["updated_at"],
        "version": cp["version"],
    }


def serialize_loan(l: dict) -> dict:
    return {
        "id": l["id"],
        "participant_id": l["participant_id"],
        "principal_cents": l["principal_cents"],
        "term_months": l["term_months"],
        "annual_interest_rate_bps": l["annual_interest_rate_bps"],
        "monthly_payment_cents": l["monthly_payment_cents"],
        "outstanding_principal_cents": l["outstanding_principal_cents"],
        "status": l["status"],
        "created_at": l["created_at"],
        "updated_at": l["updated_at"],
        "version": l["version"],
    }


def serialize_hardship(h: dict) -> dict:
    return {
        "id": h["id"],
        "participant_id": h["participant_id"],
        "requested_amount_cents": h["requested_amount_cents"],
        "hardship_category": h["hardship_category"],
        "approved_amount_cents": h["approved_amount_cents"],
        "ten_percent_penalty_cents": h["ten_percent_penalty_cents"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def serialize_rmd(r: dict) -> dict:
    return {
        "id": r["id"],
        "participant_id": r["participant_id"],
        "distribution_year": r["distribution_year"],
        "prior_year_end_balance_cents": r["prior_year_end_balance_cents"],
        "rmd_variant": r["rmd_variant"],
        "spouse_date_of_birth": r.get("spouse_date_of_birth"),
        "required_amount_cents": r["required_amount_cents"],
        "distributed_amount_cents": r["distributed_amount_cents"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_vesting_event(v: dict) -> dict:
    # VestingEvent is immutable + append-only — no updated_at/version per PRD §2.4.
    return {
        "id": v["id"],
        "participant_id": v["participant_id"],
        "as_of_date": v["as_of_date"],
        "years_of_service_after": v["years_of_service_after"],
        "vested_pct_bps_after": v["vested_pct_bps_after"],
        "created_at": v["created_at"],
    }
