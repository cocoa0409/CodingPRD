"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_NAME": "Test Plan 401k",
    "SPONSOR_EIN": "123456789",
    "PLAN_NUMBER": "001",
    "PROPOSED_TERMINATION_DATE": "2026-10-15T00:00:00Z",
    "FULL_NAME": "Test Participant",
    "SSN": "111223333",
    "MAILING_ADDRESS": "1 Main St",
    "ACCOUNT_BALANCE_CENTS": 250000,
    "VESTED_PCT": 100,
    "VENDOR_NAME": "Loc8",
    "OUTGOING_RECORDKEEPER": "OldRK",
    "INCOMING_RECORDKEEPER": "NewRK",
    "ELECTION_METHOD": "DIRECT_ROLLOVER_IRA",
    "AMOUNT_BASIS": "SUBMISSION_NET",
    "RATIONALE": (
        "Last-resort forfeiture after exhausted search; "
        "PBGC transfer declined for administrative cost reasons."
    ),
    "EXPENSE_METHOD": "PRO_RATA_BY_BALANCE",
    "TOTAL_EXPENSE_CENTS": 10000,
    "EXPENSE_DESCRIPTION": "Final recordkeeper invoice",
    "NARRATIVE": (
        "Exhausted commercial locator, public records, credit bureau, "
        "and certified mail steps with no result for this participant."
    ),
    "ENTRY_TYPE": "SEARCH_PROTOCOL_SUMMARY",
}


def create_termination_case_payload(**overrides) -> dict:
    defaults = {
        "plan_name": DEFAULTS["PLAN_NAME"],
        "sponsor_ein": DEFAULTS["SPONSOR_EIN"],
        "plan_number": DEFAULTS["PLAN_NUMBER"],
        "proposed_termination_date": DEFAULTS["PROPOSED_TERMINATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_participant_payload(**overrides) -> dict:
    defaults = {
        "termination_case_id": None,
        "full_name": DEFAULTS["FULL_NAME"],
        "ssn": DEFAULTS["SSN"],
        "mailing_address": DEFAULTS["MAILING_ADDRESS"],
        "account_balance_cents": DEFAULTS["ACCOUNT_BALANCE_CENTS"],
        "vested_pct": DEFAULTS["VESTED_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {
        "termination_case_id": None,
        "notice_type": "NOIT",
        "action_effective_date": DEFAULTS["PROPOSED_TERMINATION_DATE"],
        "expected_termination_case_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_period_payload(**overrides) -> dict:
    defaults = {
        "termination_case_id": None,
        "start_at": "2026-11-01T00:00:00Z",
        "end_at": "2026-11-05T00:00:00Z",
        "outgoing_recordkeeper": DEFAULTS["OUTGOING_RECORDKEEPER"],
        "incoming_recordkeeper": DEFAULTS["INCOMING_RECORDKEEPER"],
    }
    defaults.update(overrides)
    return defaults


def create_election_payload(**overrides) -> dict:
    defaults = {
        "participant_id": None,
        "election_method": DEFAULTS["ELECTION_METHOD"],
        "expected_participant_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_attempt_payload(**overrides) -> dict:
    defaults = {
        "method": "COMMERCIAL_LOCATOR",
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "attempted_at": "2026-08-01T00:00:00Z",
        "outcome": "NO_RESULT",
    }
    defaults.update(overrides)
    return defaults


def create_pbgc_transfer_payload(**overrides) -> dict:
    defaults = {
        "participant_id": None,
        "amount_basis": DEFAULTS["AMOUNT_BASIS"],
    }
    defaults.update(overrides)
    return defaults


def create_forfeiture_payload(**overrides) -> dict:
    defaults = {
        "participant_id": None,
        "rationale": DEFAULTS["RATIONALE"],
    }
    defaults.update(overrides)
    return defaults


def create_dlr_payload(**overrides) -> dict:
    defaults = {
        "termination_case_id": None,
        "intended_filing_date": "2026-08-25T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_fiduciary_log_entry_payload(**overrides) -> dict:
    defaults = {
        "termination_case_id": None,
        "entry_type": DEFAULTS["ENTRY_TYPE"],
        "narrative": DEFAULTS["NARRATIVE"],
    }
    defaults.update(overrides)
    return defaults


def create_expense_allocation_payload(**overrides) -> dict:
    defaults = {
        "termination_case_id": None,
        "method": DEFAULTS["EXPENSE_METHOD"],
        "total_expense_cents": DEFAULTS["TOTAL_EXPENSE_CENTS"],
        "description": DEFAULTS["EXPENSE_DESCRIPTION"],
    }
    defaults.update(overrides)
    return defaults
