"""Composite setup helpers for the plan-termination lifecycle.

The server starts empty for every test, so each helper builds its preconditions
from scratch through the public API. All helpers use the lenient
get_success_data() validator: a failing setup step raises a clear
"Setup step failed" error instead of a confusing assertion deep in a test.

Identity threading: the search-exhauster identity defaults to admin-1
(TEST_USERS["admin_headers"]); disposition approvals default to fid-1
(TEST_USERS["fiduciary_headers"]) so the segregation-of-duties gate passes.
Tests that exercise the violation arm pass explicit headers built with
make_fiduciary_headers()/make_admin_headers().
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DATES
from .factories import (
    create_attempt_payload,
    create_dlr_payload,
    create_election_payload,
    create_fiduciary_log_entry_payload,
    create_forfeiture_payload,
    create_notice_payload,
    create_participant_payload,
    create_pbgc_transfer_payload,
    create_termination_case_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]          # X-User-ID: admin-1 (PlanAdministrator)
ADMIN2 = TEST_USERS["admin2_headers"]        # X-User-ID: admin-2 (PlanAdministrator)
FIDUCIARY = TEST_USERS["fiduciary_headers"]  # X-User-ID: fid-1 (IndependentFiduciary)
RECORDKEEPER = TEST_USERS["recordkeeper_headers"]  # X-User-ID: rk-1

# Pinned timeline shared by the lifecycle fixtures. The startup clock
# (2026-08-01) is 75 days before the pinned termination date, inside the
# NOIT issuance window; the distribution notice effective date pins the
# default-treatment date 30 days later.
T_TERMINATION = DATES["PROPOSED_TERMINATION_DATE"]       # 2026-10-15T00:00:00Z
DISTRIBUTION_DATE = DATES["DISTRIBUTION_EFFECTIVE_DATE"]  # 2026-10-20T00:00:00Z
DEFAULT_TREATMENT_DATE = DATES["DEFAULT_TREATMENT_DATE"]  # 2026-11-19T00:00:00Z
AFTER_DEFAULT_TREATMENT = DATES["AFTER_DEFAULT_TREATMENT"]  # 2026-11-20T00:00:00Z
CLOCK_STARTUP = DATES["CLOCK_STARTUP_DEFAULT"]            # 2026-08-01T00:00:00Z

# Fiduciary narratives (>= 50 characters as the PRD requires).
SEARCH_PROTOCOL_NARRATIVE = (
    "Exhausted commercial locator, public records, credit bureau, "
    "and certified mail steps with no result for this participant."
)
CLOSURE_SIGNOFF_NARRATIVE = (
    "All participants resolved, residual zero, notices and searches "
    "documented; case is ready for closure review."
)
FORFEITURE_RATIONALE_TEXT = (
    "Last-resort forfeiture after exhausted search; "
    "funds held for possible restoration."
)

# The four search steps in protocol order.
_SEARCH_STEPS = (
    "COMMERCIAL_LOCATOR",
    "PUBLIC_RECORDS",
    "CREDIT_BUREAU",
    "CERTIFIED_MAIL",
)

# Default attempt dates for the exhaustion walk: one per day so the attempts
# stay chronological and never future-dated (the clock is advanced to each
# attempt's date before recording it). Exhaustion runs at 2026-11-19, exactly
# 15 days after the certified-mail attempt (inclusive boundary).
DEFAULT_ATTEMPT_DATES = (
    "2026-11-01T00:00:00Z",
    "2026-11-02T00:00:00Z",
    "2026-11-03T00:00:00Z",
    "2026-11-04T00:00:00Z",
)
DEFAULT_EXHAUST_CLOCK = "2026-11-19T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: primitive wrappers (clock, CRUD reads)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601, headers=None):
    """Move the server logical clock; returns the resulting current_utc."""
    data = get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, headers or ADMIN)
    )
    return data


def get_case(case_id, headers=None):
    return get_success_data(api_client.get_termination_case(case_id, headers or ADMIN))


def get_participant(participant_id, headers=None):
    return get_success_data(api_client.get_participant(participant_id, headers or ADMIN))


def get_search_case(search_case_id, headers=None):
    return get_success_data(api_client.get_search_case(search_case_id, headers or ADMIN))


def get_election(election_id, headers=None):
    return get_success_data(api_client.get_election(election_id, headers or ADMIN))


def get_notice(notice_id, headers=None):
    return get_success_data(api_client.get_notice(notice_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Tier 1: case lifecycle (DRAFT -> NOTICE_OF_INTENT_ISSUED -> TERMINATION_EFFECTIVE
#         -> DISTRIBUTION_IN_PROGRESS)
# ---------------------------------------------------------------------------

def create_case(plan_name="Test Plan 401k", plan_number="001",
                restoration_policy=None, proposed_termination_date=T_TERMINATION,
                headers=None):
    """Create a termination case (DRAFT). restoration_policy omitted unless given."""
    payload = create_termination_case_payload(
        plan_name=plan_name,
        plan_number=plan_number,
        proposed_termination_date=proposed_termination_date,
    )
    if restoration_policy is not None:
        payload["restoration_policy"] = restoration_policy
    return get_success_data(api_client.create_termination_case(payload, headers or ADMIN))


def add_participant(case_id, balance_cents, vested_pct=100,
                    full_name="Test Participant", ssn="111223333",
                    mailing_address="1 Main St", headers=None):
    """Add a participant to the census; returns the created Participant."""
    payload = create_participant_payload(
        termination_case_id=case_id,
        full_name=full_name,
        ssn=ssn,
        mailing_address=mailing_address,
        account_balance_cents=balance_cents,
        vested_pct=vested_pct,
    )
    return get_success_data(api_client.create_participant(payload, headers or ADMIN))


def issue_notice(case_id, notice_type, action_effective_date, headers=None):
    """Issue a notice, threading the current case version for the OCC guard."""
    case = get_case(case_id)
    payload = create_notice_payload(
        termination_case_id=case_id,
        notice_type=notice_type,
        action_effective_date=action_effective_date,
        expected_termination_case_version=case["version"],
    )
    return get_success_data(api_client.create_notice(payload, headers or ADMIN))


def issue_noit(case_id, termination_date=T_TERMINATION, headers=None):
    """Issue the notice of intent to terminate.

    Moves the clock back to the startup instant first so the issuance always
    lands inside the statutory window for the pinned termination date
    (non-monotonic clock moves are permitted).
    """
    set_clock(CLOCK_STARTUP)
    return issue_notice(case_id, "NOIT", termination_date, headers)


def effectuate_termination(case_id, termination_date=T_TERMINATION, headers=None):
    """Advance the clock to the termination date and effectuate."""
    set_clock(termination_date)
    return get_success_data(api_client.effectuate_termination(case_id, headers or ADMIN))


def begin_distributions(case_id, distribution_date=DISTRIBUTION_DATE, headers=None):
    """Issue the DISTRIBUTION notice and begin distributions."""
    issue_notice(case_id, "DISTRIBUTION", distribution_date, headers)
    return get_success_data(api_client.begin_distributions(case_id, headers or ADMIN))


def setup_case_through_effectuation(participants=(), plan_name="Effectuate Co 401k",
                                    plan_number="301", restoration_policy=None,
                                    termination_date=T_TERMINATION):
    """Case + participants + NOIT + effectuation.

    participants: iterable of balance_cents ints, or (balance, vested_pct) pairs.
    Returns (case, [participant, ...]); the clock is left at the termination date.
    """
    case = create_case(plan_name=plan_name, plan_number=plan_number,
                       restoration_policy=restoration_policy,
                       proposed_termination_date=termination_date)
    plist = []
    for index, spec in enumerate(participants):
        if isinstance(spec, (tuple, list)):
            balance, vested = spec
        else:
            balance, vested = spec, 100
        plist.append(add_participant(
            case["id"], balance, vested,
            full_name=f"Participant {index + 1}", ssn=f"1212{index:05d}",
        ))
    issue_noit(case["id"], termination_date)
    case = effectuate_termination(case["id"], termination_date)
    return case, plist


def setup_case_in_distribution(participants=((250000, 100),),
                               plan_name="Distribution Co 401k", plan_number="302",
                               restoration_policy=None,
                               termination_date=T_TERMINATION,
                               distribution_date=DISTRIBUTION_DATE):
    """Full chain: case + participants + NOIT + effectuate + DISTRIBUTION notice
    + begin-distributions. Returns (case, [participant, ...]).

    The clock is left at the termination date (before the distribution date).
    """
    case, plist = setup_case_through_effectuation(
        participants, plan_name, plan_number, restoration_policy, termination_date)
    begin_distributions(case["id"], distribution_date)
    return get_case(case["id"]), plist


# ---------------------------------------------------------------------------
# Tier 2: contact flags and the missing/locate lifecycle
# ---------------------------------------------------------------------------

def flag_participant(participant_id, flag_type="UNDELIVERABLE_MAIL",
                     evidence_note=None, headers=None):
    payload = {"flag_type": flag_type}
    if evidence_note is not None:
        payload["evidence_note"] = evidence_note
    return get_success_data(
        api_client.flag_contact(participant_id, payload, headers or RECORDKEEPER))


def declare_participant_missing(participant_id, headers=None):
    """Declare a flagged participant missing; returns the updated Participant."""
    return get_success_data(api_client.declare_missing(participant_id, headers or ADMIN))


def locate_participant(participant_id, verified_address=None, headers=None):
    payload = {}
    if verified_address is not None:
        payload["verified_address"] = verified_address
    return get_success_data(api_client.locate_participant(participant_id, payload, headers or ADMIN))


def setup_missing_participant(participant_id, flag_type="UNDELIVERABLE_MAIL",
                              flag_clock="2026-11-01T00:00:00Z", admin_headers=None):
    """Flag + declare-missing. Returns (participant, open MissingSearchCase)."""
    if flag_clock is not None:
        set_clock(flag_clock)
    flag_participant(participant_id, flag_type)
    participant = declare_participant_missing(participant_id, admin_headers or ADMIN)
    search_case = get_search_case(participant["active_search_case_id"])
    return participant, search_case


# ---------------------------------------------------------------------------
# Tier 3: the four-step search protocol
# ---------------------------------------------------------------------------

def record_search_attempt(search_case_id, method, attempted_at, outcome="NO_RESULT",
                          vendor_name="Loc8", headers=None):
    payload = create_attempt_payload(
        method=method, vendor_name=vendor_name,
        attempted_at=attempted_at, outcome=outcome,
    )
    return get_success_data(
        api_client.record_attempt(search_case_id, payload, headers or ADMIN))


def escalate_search(search_case_id, headers=None):
    return get_success_data(api_client.escalate_search_case(search_case_id, headers or ADMIN))


def exhaust_search_protocol(search_case_id, attempt_dates=DEFAULT_ATTEMPT_DATES,
                            exhaust_clock=DEFAULT_EXHAUST_CLOCK, admin_headers=None):
    """Drive an open search case STEP1 -> STEP2 -> STEP3 -> STEP4 -> EXHAUSTED.

    The clock is advanced to each attempt's date before recording it so no
    attempt is ever future-dated, and the final escalation runs at
    exhaust_clock (>= last certified-mail attempt + 15 days).
    Returns the EXHAUSTED search case.
    """
    admin = admin_headers or ADMIN
    dates = tuple(attempt_dates)
    for method, day in zip(_SEARCH_STEPS[:3], dates[:3]):
        set_clock(day)
        record_search_attempt(search_case_id, method, day, headers=admin)
        escalate_search(search_case_id, admin)
    set_clock(dates[3])
    record_search_attempt(search_case_id, _SEARCH_STEPS[3], dates[3], headers=admin)
    set_clock(exhaust_clock)
    return escalate_search(search_case_id, admin)


def create_search_protocol_summary(case_id, search_case_id, headers=None):
    payload = create_fiduciary_log_entry_payload(
        termination_case_id=case_id,
        entry_type="SEARCH_PROTOCOL_SUMMARY",
        narrative=SEARCH_PROTOCOL_NARRATIVE,
        related_entity_id=search_case_id,
    )
    return get_success_data(api_client.create_fiduciary_log_entry(payload, headers or ADMIN))


def setup_exhausted_search(case_id, participant_id, document=True,
                           flag_type="UNDELIVERABLE_MAIL",
                           flag_clock="2026-11-01T00:00:00Z",
                           attempt_dates=DEFAULT_ATTEMPT_DATES,
                           exhaust_clock=DEFAULT_EXHAUST_CLOCK,
                           admin_headers=None):
    """Flag -> declare-missing -> four-step exhaustion -> optional
    SEARCH_PROTOCOL_SUMMARY log entry. Returns the EXHAUSTED MissingSearchCase."""
    admin = admin_headers or ADMIN
    _, search_case = setup_missing_participant(
        participant_id, flag_type=flag_type, flag_clock=flag_clock,
        admin_headers=admin)
    search_case = exhaust_search_protocol(
        search_case["id"], attempt_dates, exhaust_clock, admin)
    if document:
        create_search_protocol_summary(case_id, search_case["id"], admin)
    return search_case


# ---------------------------------------------------------------------------
# Tier 4: elections and payouts
# ---------------------------------------------------------------------------

def submit_election(participant_id, election_method="DIRECT_ROLLOVER_IRA",
                    destination_detail="IRA at Custodian X", headers=None):
    """Submit an election, threading the current participant version (OCC)."""
    participant = get_participant(participant_id)
    payload = create_election_payload(
        participant_id=participant_id,
        election_method=election_method,
        expected_participant_version=participant["version"],
    )
    if destination_detail is not None:
        payload["destination_detail"] = destination_detail
    else:
        payload.pop("destination_detail", None)
    return get_success_data(api_client.create_election(payload, headers or ADMIN))


def accept_election(election_id, headers=None):
    return get_success_data(api_client.accept_election(election_id, headers or ADMIN))


def election_payout(election_id, headers=None):
    """Return the single payout spawned by an accepted election."""
    data = get_success_data(api_client.list_election_payouts(election_id, headers or ADMIN))
    assert isinstance(data, list) and len(data) == 1, (
        f"expected exactly one payout for election {election_id}, got {data!r}")
    return data[0]


def create_accepted_payout(participant_id, election_method="DIRECT_ROLLOVER_IRA",
                           destination_detail="IRA at Custodian X", headers=None):
    """Submit + accept an election. Returns (election, payout)."""
    election = submit_election(participant_id, election_method, destination_detail, headers)
    accept_election(election["id"], headers)
    return election, election_payout(election["id"], headers)


def create_cleared_rollover(participant_id, headers=None):
    """Rollover election accepted and its payout cleared.

    Returns (election, payout). The participant lands in AUTO_ROLLED_OVER.
    """
    election, payout = create_accepted_payout(
        participant_id, "DIRECT_ROLLOVER_IRA", "IRA at Custodian X", headers)
    payout = get_success_data(
        api_client.mark_payout_cleared(payout["id"], headers or RECORDKEEPER))
    return election, payout


# ---------------------------------------------------------------------------
# Tier 5: dispositions (PBGC transfer / forfeiture) and fiduciary record
# ---------------------------------------------------------------------------

def create_submitted_pbgc_transfer(participant_id, amount_basis="SUBMISSION_NET",
                                   headers=None):
    payload = create_pbgc_transfer_payload(
        participant_id=participant_id, amount_basis=amount_basis)
    return get_success_data(api_client.create_pbgc_transfer(payload, headers or FIDUCIARY))


def create_recorded_forfeiture(participant_id, rationale=FORFEITURE_RATIONALE_TEXT,
                               headers=None):
    payload = create_forfeiture_payload(
        participant_id=participant_id, rationale=rationale)
    return get_success_data(api_client.create_forfeiture(payload, headers or FIDUCIARY))


def create_closure_signoff(case_id, headers=None):
    payload = create_fiduciary_log_entry_payload(
        termination_case_id=case_id,
        entry_type="CLOSURE_SIGNOFF",
        narrative=CLOSURE_SIGNOFF_NARRATIVE,
    )
    return get_success_data(api_client.create_fiduciary_log_entry(payload, headers or ADMIN))


def list_participant_payouts(participant_id, headers=None):
    return get_success_data(
        api_client.list_participant_payouts(participant_id, headers or ADMIN))


def list_participant_transfers(participant_id, headers=None):
    return get_success_data(
        api_client.list_participant_pbgc_transfers(participant_id, headers or ADMIN))


def list_participant_forfeitures(participant_id, headers=None):
    return get_success_data(
        api_client.list_participant_forfeitures(participant_id, headers or ADMIN))


def list_attempts(search_case_id, headers=None):
    return get_success_data(api_client.list_attempts(search_case_id, headers or ADMIN))


# ---------------------------------------------------------------------------
# Tier 6: determination letter and closure
# ---------------------------------------------------------------------------

DEFAULT_FILING_DATE = "2026-08-25T00:00:00Z"  # exactly 24 days after the startup clock


def create_dlr_with_covering_notice(case_id, filing_date=DEFAULT_FILING_DATE,
                                    headers=None):
    """Issue the INTERESTED_PARTY notice at the current clock and create the DLR.

    The caller must ensure the clock sits inside the covering window
    ([filing date - 24 days, filing date - 10 days]); at the startup clock the
    default filing date is exactly 24 days out (inclusive bound).
    Returns the DRAFT DeterminationLetterRequest.
    """
    issue_notice(case_id, "INTERESTED_PARTY", filing_date, headers)
    payload = create_dlr_payload(
        termination_case_id=case_id, intended_filing_date=filing_date)
    return get_success_data(api_client.create_dlr(payload, headers or ADMIN))


def file_dlr_on(dlr_id, file_date=DEFAULT_FILING_DATE, headers=None):
    """Move the clock to file_date and file the DLR (window re-checked)."""
    set_clock(file_date)
    return get_success_data(api_client.file_dlr(dlr_id, headers or ADMIN))


def setup_fully_resolved_case(balance=200000, plan_name="Resolved Co 401k",
                              plan_number="303", restoration_policy=None):
    """Case in FINAL_RECONCILIATION: one participant paid out via a cleared
    rollover, advanced to reconciliation, CLOSURE_SIGNOFF recorded.
    Returns (case, participant, payout).
    """
    case, plist = setup_case_in_distribution(
        participants=((balance, 100),), plan_name=plan_name,
        plan_number=plan_number, restoration_policy=restoration_policy)
    participant = plist[0]
    _, payout = create_cleared_rollover(participant["id"])
    case = get_success_data(api_client.advance_to_reconciliation(case["id"], ADMIN))
    create_closure_signoff(case["id"])
    return case, participant, payout


# ---------------------------------------------------------------------------
# Tier 7: blackout helpers
# ---------------------------------------------------------------------------

def create_blackout(case_id, start_at="2026-11-01T00:00:00Z",
                    end_at="2026-11-05T00:00:00Z", headers=None):
    payload = {
        "termination_case_id": case_id,
        "start_at": start_at,
        "end_at": end_at,
        "outgoing_recordkeeper": "OldRK",
        "incoming_recordkeeper": "NewRK",
    }
    return get_success_data(api_client.create_blackout_period(payload, headers or ADMIN))


def create_blackout_with_advisory(case_id, start_at="2026-11-01T00:00:00Z",
                                  end_at="2026-11-05T00:00:00Z",
                                  advisory_clock="2026-10-01T00:00:00Z"):
    """Schedule a blackout and issue its covering BLACKOUT_ADVISORY notice.

    The advisory is issued at advisory_clock (31 days before the default start,
    inside the 30-to-60-day window). Returns the SCHEDULED BlackoutPeriod.
    """
    blackout = create_blackout(case_id, start_at, end_at)
    set_clock(advisory_clock)
    issue_notice(case_id, "BLACKOUT_ADVISORY", start_at)
    return blackout


def activate_blackout(blackout_id, activation_clock, headers=None):
    """Move the clock inside the window and activate (Recordkeeper act)."""
    set_clock(activation_clock)
    return get_success_data(api_client.activate_blackout(blackout_id, headers or RECORDKEEPER))


def complete_blackout(blackout_id, completion_clock, headers=None):
    """Move the clock to/after end_at and complete (Recordkeeper act)."""
    set_clock(completion_clock)
    return get_success_data(api_client.complete_blackout(blackout_id, headers or RECORDKEEPER))
