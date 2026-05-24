"""Payload factories — one per entity, input fields only.

Each factory builds a minimal valid payload with sensible defaults that can be
overridden via keyword arguments. Default values steer toward easy successful
creation (e.g., DIRECT_UNSUBSIDIZED loan at 5.33% over $20,000).
"""
import uuid


# ─── Default values used across factories ───────────────


def _unique_email(prefix: str = "test") -> str:
    """Generate a unique email per test run to avoid ERR_EMAIL_DUPLICATE clashes."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def _unique_ssn4() -> str:
    """Generate a 4-digit numeric string."""
    return f"{uuid.uuid4().int % 10000:04d}"


def _unique_ein() -> str:
    """Generate a 9-digit numeric EIN."""
    return f"{uuid.uuid4().int % 1_000_000_000:09d}"


# ─── Borrower ─────────────────────────────────────────


def create_borrower_payload(**overrides) -> dict:
    """Build a Borrower create payload. military_status defaults to NONE per §3.1."""
    defaults = {
        "ssn_last4": _unique_ssn4(),
        "full_name": "Test Borrower",
        "date_of_birth": "1990-01-01",
        "email": _unique_email("brw"),
        "military_status": "NONE",
    }
    defaults.update(overrides)
    return defaults


# ─── Loan ─────────────────────────────────────────────


def create_loan_payload(borrower_id: str, **overrides) -> dict:
    """Build a Loan originate payload. Defaults to a $20,000 DIRECT_UNSUBSIDIZED loan @ 5.33%."""
    defaults = {
        "borrower_id": borrower_id,
        "loan_type": "DIRECT_UNSUBSIDIZED",
        "original_principal_cents": 2_000_000,
        "interest_rate_bps": 533,
        "disbursement_date": "2025-06-01",
    }
    defaults.update(overrides)
    return defaults


# ─── ServicingEvent ───────────────────────────────────


def create_servicing_event_payload(event_type: str, effective_on: str,
                                    reason_code: str = "OTHER", **overrides) -> dict:
    defaults = {
        "event_type": event_type,
        "effective_on": effective_on,
        "reason_code": reason_code,
    }
    defaults.update(overrides)
    return defaults


# ─── RepaymentPlan ────────────────────────────────────


def create_standard_10yr_plan_payload(loan_id: str, expected_loan_version: int,
                                       state_of_residence: str = "CONTIGUOUS",
                                       **overrides) -> dict:
    """STANDARD_10YR plan: agi_cents and family_size MUST be null per §3.3."""
    defaults = {
        "loan_id": loan_id,
        "plan_type": "STANDARD_10YR",
        "state_of_residence": state_of_residence,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_idr_plan_payload(loan_id: str, plan_type: str, agi_cents: int,
                             family_size: int, expected_loan_version: int,
                             state_of_residence: str = "CONTIGUOUS",
                             **overrides) -> dict:
    """IBR/PAYE/SAVE plan: agi_cents and family_size REQUIRED per §3.3."""
    defaults = {
        "loan_id": loan_id,
        "plan_type": plan_type,
        "agi_cents": agi_cents,
        "family_size": family_size,
        "state_of_residence": state_of_residence,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_recertify_payload(agi_cents: int, family_size: int, **overrides) -> dict:
    defaults = {
        "agi_cents": agi_cents,
        "family_size": family_size,
    }
    defaults.update(overrides)
    return defaults


# ─── Payment ──────────────────────────────────────────


def create_payment_payload(loan_id: str, amount_cents: int, posted_on: str,
                            source: str = "ACH", **overrides) -> dict:
    defaults = {
        "loan_id": loan_id,
        "amount_cents": amount_cents,
        "posted_on": posted_on,
        "source": source,
    }
    defaults.update(overrides)
    return defaults


# ─── EmploymentCertification ─────────────────────────


def create_employment_certification_payload(borrower_id: str,
                                              employer_type: str = "GOVERNMENT_FEDERAL",
                                              period_start_on: str = "2026-01-01",
                                              period_end_on: str = "2099-12-31",
                                              weekly_hours: float = 40,
                                              **overrides) -> dict:
    """Defaults produce an employer that qualifies for PSLF."""
    defaults = {
        "borrower_id": borrower_id,
        "employer_ein": _unique_ein(),
        "employer_type": employer_type,
        "period_start_on": period_start_on,
        "period_end_on": period_end_on,
        "weekly_hours": weekly_hours,
    }
    defaults.update(overrides)
    return defaults


# ─── PSLFTracker ──────────────────────────────────────


def create_pslf_tracker_payload(borrower_id: str, **overrides) -> dict:
    defaults = {"borrower_id": borrower_id}
    defaults.update(overrides)
    return defaults


def force_pslf_tracker_state_payload(qualifying_payment_count: int,
                                       status: str = "ELIGIBLE_FOR_FORGIVENESS",
                                       **overrides) -> dict:
    defaults = {
        "qualifying_payment_count": qualifying_payment_count,
        "status": status,
    }
    defaults.update(overrides)
    return defaults


# ─── DischargeApplication ────────────────────────────


def create_discharge_application_payload(borrower_id: str, discharge_type: str,
                                          filed_on: str,
                                          va_certification_doc_id=None,
                                          **overrides) -> dict:
    defaults = {
        "borrower_id": borrower_id,
        "discharge_type": discharge_type,
        "filed_on": filed_on,
    }
    if va_certification_doc_id is not None:
        defaults["va_certification_doc_id"] = va_certification_doc_id
    defaults.update(overrides)
    return defaults


def approve_discharge_payload(expected_loan_version_by_loan_id: dict) -> dict:
    """Body for POST /discharge-applications/{id}/approve per PRD §2.5."""
    return {"expected_loan_version_by_loan_id": expected_loan_version_by_loan_id}


# ─── Clock ────────────────────────────────────────────


def advance_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


# ─── Borrower military_status patch ───────────────────


def patch_military_status_payload(military_status: str) -> dict:
    return {"military_status": military_status}
