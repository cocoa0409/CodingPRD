"""Payload factories — one per entity, input fields only."""
import itertools

# Monotonic counters so each created entity gets a unique natural key when the
# test does not override it (state_account_number, program_code, ssn_last4).
_account_seq = itertools.count(1)
_program_seq = itertools.count(1)
_ssn_seq = itertools.count(1000)


def _next_account_number() -> str:
    return f"SAN-{next(_account_seq):06d}"


def _next_program_code() -> str:
    return f"PROG-{next(_program_seq):06d}"


def _next_ssn_last4() -> str:
    return f"{next(_ssn_seq) % 10000:04d}"


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Employer Co",
        "state_account_number": _next_account_number(),
        "experience_rate": 0.034,
        "reserve_opening_balance_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_claimant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Claimant",
        "ssn_last4": _next_ssn_last4(),
        "date_of_birth": "1990-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_wage_record_payload(claimant_id: str, employer_id: str,
                               calendar_quarter: str, gross_wages_cents: int,
                               **overrides) -> dict:
    defaults = {
        "claimant_id": claimant_id,
        "employer_id": employer_id,
        "calendar_quarter": calendar_quarter,
        "gross_wages_cents": gross_wages_cents,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(claimant_id: str, filed_date: str = "2026-04-05",
                         **overrides) -> dict:
    defaults = {
        "claimant_id": claimant_id,
        "filed_date": filed_date,
    }
    defaults.update(overrides)
    return defaults


def create_determination_payload(claim_id: str,
                                 determination_type: str = "MONETARY",
                                 **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "determination_type": determination_type,
    }
    defaults.update(overrides)
    return defaults


def create_weekly_certification_payload(claim_id: str,
                                        week_ending_date: str = "2026-04-11",
                                        **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "week_ending_date": week_ending_date,
    }
    defaults.update(overrides)
    return defaults


def create_work_search_contact_payload(contact_type: str = "EMPLOYER_APPLICATION",
                                       contact_date: str = "2026-04-08",
                                       **overrides) -> dict:
    defaults = {
        "contact_type": contact_type,
        "contact_date": contact_date,
    }
    defaults.update(overrides)
    return defaults


def create_overpayment_payload(claim_id: str, cause: str = "NONFRAUD",
                               principal_cents: int = 30000, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "cause": cause,
        "principal_cents": principal_cents,
    }
    defaults.update(overrides)
    return defaults


def create_recovery_payload(recovery_method: str, amount_cents: int,
                            expected_overpayment_version: int, **overrides) -> dict:
    defaults = {
        "recovery_method": recovery_method,
        "amount_cents": amount_cents,
        "expected_overpayment_version": expected_overpayment_version,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(determination_id: str, filed_by: str = "CLAIMANT",
                          filed_date: str = "2026-04-20", **overrides) -> dict:
    defaults = {
        "determination_id": determination_id,
        "filed_by": filed_by,
        "filed_date": filed_date,
    }
    defaults.update(overrides)
    return defaults


def create_extension_program_payload(extra_weeks: int = 13,
                                     trigger_start_date: str = "2026-01-01",
                                     trigger_end_date: str = "2026-12-31",
                                     **overrides) -> dict:
    defaults = {
        "program_code": _next_program_code(),
        "extra_weeks": extra_weeks,
        "trigger_start_date": trigger_start_date,
        "trigger_end_date": trigger_end_date,
    }
    defaults.update(overrides)
    return defaults
