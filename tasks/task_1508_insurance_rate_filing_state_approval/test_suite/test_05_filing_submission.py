"""Submission gates, validation-pipeline ordering, and submit side effects
(PRD §2.8, §3.3, §3.5)."""
from test_helpers import (
    ApiErrorId,
    assert_instant_equals,
    get_success_data,
    list_calendar_entries,
    setup_draft_filing,
    setup_ready_filing,
    setup_released_wave,
    setup_submitted_filing,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx


def test_submit_from_draft_reports_state_over_temporal(api):
    """PRD §2.8: "sixth, whether the target resource is in a state from which
    the requested transition exists, rejected otherwise as `ERR_INVALID_STATE`
    (HTTP 409); seventh, segregation of duties; eighth, the usability of
    referenced regulatory configuration; ninth, temporal rules such as lead
    times, windows, and notice deadlines".

    Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_temporal
    """
    # Proposed 2026-08-10 also violates the 45-day lead (2026-08-01 + 45d =
    # 2026-09-15), but the filing is DRAFT: the state failure must surface.
    scenario = setup_draft_filing(proposed_effective_date="2026-08-10")
    res = api.submit_filing(scenario["filing"]["id"], fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    filing = get_success_data(api.get_filing(scenario["filing"]["id"], fx.OFFICER))
    assert filing["status"] == "DRAFT"


def test_complete_renewal_from_rated_reports_state_over_temporal(api):
    """PRD §2.8: "sixth, whether the target resource is in a state from which
    the requested transition exists, rejected otherwise as `ERR_INVALID_STATE`
    (HTTP 409)".
    PRD §2.8: "ninth, temporal rules such as lead times, windows, and notice
    deadlines".

    Design: Difficulty/priority_pair_validation_conflict/submit_state_beats_temporal
    """
    # RATED policy with the clock before its renewal date: complete-renewal
    # fails both the state check (not NOTICE_SENT) and the temporal check.
    scenario = setup_released_wave(
        policies=[("CA-1001", 100_000, 1.0, "2026-11-20")]
    )
    policy = scenario["policies"][0]
    res = api.complete_policy_renewal(policy["id"], fx.LEAD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    assert fx.refresh_policy(policy["id"])["status"] == "RATED"


def test_effective_lead_violation_at_submit(api):
    """PRD §3.3: "the effective-date lead rule must hold — under
    `PRIOR_APPROVAL` the `proposed_effective_date` must fall at least
    `min_effective_lead_days` after the submission date, while under
    `FILE_AND_USE` or `USE_AND_FILE` it must simply be on or after the
    submission date, with violations rejected as `ERR_EFFECTIVE_LEAD_VIOLATION`
    (HTTP 422)".

    Design: Corner/validations/effective_lead_violation_at_submit
    """
    # Submitted at the 2026-08-01 default clock; 2026-09-01 < 2026-09-15.
    scenario = setup_ready_filing(proposed_effective_date="2026-09-01")
    res = api.submit_filing(scenario["filing"]["id"], fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_EFFECTIVE_LEAD_VIOLATION)
    filing = get_success_data(api.get_filing(scenario["filing"]["id"], fx.OFFICER))
    assert filing["status"] == "READY"


def test_double_submit_rejected(api):
    """PRD §3.3: "Submission itself belongs to the `ComplianceOfficer` and
    moves the filing from `READY` to `SUBMITTED`."
    PRD §2.8: "sixth, whether the target resource is in a state from which the
    requested transition exists, rejected otherwise as `ERR_INVALID_STATE`
    (HTTP 409)".

    Design: Corner/state_machines/double_submit_returns_invalid_state
    """
    scenario = setup_submitted_filing()
    res = api.submit_filing(scenario["filing"]["id"], fx.OFFICER)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    filing = get_success_data(api.get_filing(scenario["filing"]["id"], fx.OFFICER))
    assert filing["status"] == "SUBMITTED"


def test_withdrawn_filing_is_terminal(api):
    """PRD §3.6: "In every case the filing ends in the terminal `WITHDRAWN`
    state."
    PRD §2.8: "sixth, whether the target resource is in a state from which the
    requested transition exists, rejected otherwise as `ERR_INVALID_STATE`
    (HTTP 409)".

    Design: Corner/state_machines/withdrawn_filing_terminal_lockdown
    """
    scenario = setup_draft_filing()
    withdrawn = validate_success(
        api.withdraw_filing(scenario["filing"]["id"], fx.ANALYST), 200
    )
    assert withdrawn["status"] == "WITHDRAWN"

    res = api.mark_filing_ready(scenario["filing"]["id"], fx.ANALYST)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    filing = get_success_data(api.get_filing(scenario["filing"]["id"], fx.ANALYST))
    assert filing["status"] == "WITHDRAWN"


def test_submit_response_carries_side_effects(api):
    """PRD §3.3: "A successful submission stamps `submitted_at` with the
    current logical time, assigns the `filing_number` — the literal prefix FIL,
    a hyphen, the state code, another hyphen, and a six-digit zero-padded
    sequence number maintained per state, so the first filing submitted to
    California is numbered FIL-CA-000001 — computes the `deemer_date` (§3.5)".
    PRD §3.5: "When the profile's `deemer_days` is greater than zero, submission
    computes `deemer_date` as the calendar date of `submitted_at` plus
    `deemer_days`".

    Design: Corner/endpoints/submit_side_effects_visible_in_response
    """
    scenario = setup_ready_filing()
    submitted = validate_success(
        api.submit_filing(scenario["filing"]["id"], fx.OFFICER), 200
    )
    assert submitted["status"] == "SUBMITTED"
    assert_instant_equals(submitted["submitted_at"], "2026-08-01T00:00:00Z")
    assert submitted["filing_number"] == "FIL-CA-000001"
    assert submitted["deemer_date"] == "2026-09-30"  # 2026-08-01 + 60 days


def test_file_and_use_submit_has_null_deemer(api):
    """PRD §3.5: "When the profile's `deemer_days` is greater than zero,
    submission computes `deemer_date` as the calendar date of `submitted_at`
    plus `deemer_days`; otherwise `deemer_date` stays null and no deemer
    machinery applies."
    PRD §3.3: "a `DEEMER_DATE` entry is created `PENDING` whenever the deemer
    applies, and an `EFFECTIVE_DATE` entry is created `PENDING` with its
    `due_date` set to the proposed effective date."

    Design: Corner/calculations/file_and_use_has_null_deemer
    """
    scenario = setup_submitted_filing(
        state_code="NV",
        profile_overrides={"filing_method": "FILE_AND_USE", "deemer_days": 0},
    )
    filing = scenario["filing"]
    assert filing["status"] == "SUBMITTED"
    assert filing["deemer_date"] is None

    entries = list_calendar_entries(filing_id=filing["id"])
    assert len(entries) == 1
    assert entries[0]["entry_type"] == "EFFECTIVE_DATE"
    assert entries[0]["status"] == "PENDING"
