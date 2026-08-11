"""Composite setup helpers for multi-step test prerequisites.

Each helper builds its preconditions from scratch through the public API
(every test runs against a freshly booted server). Setup calls use
get_success_data() so a setup failure surfaces as a clear "Setup failed"
error rather than a confusing assertion failure.

Identity threading: after an Attorney record is created, every
ownership-gated call uses make_attorney_headers(attorney["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .assertions import parse_ts, iso_utc
from .factories import (
    create_court_payload,
    create_attorney_payload,
    create_case_payload,
    create_event_payload,
    create_transcript_order_payload,
    deliver_transcript_payload,
    create_brief_payload,
    create_citation_payload,
    create_extension_motion_payload,
    grant_motion_payload,
    create_filing_payload,
    create_oral_argument_payload,
    create_decision_payload,
    create_petition_payload,
)
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_attorney_headers

ADMIN = TEST_USERS["court_admin_headers"]
CLERK = TEST_USERS["court_clerk_headers"]
PARALEGAL = TEST_USERS["paralegal_headers"]


def _setup_failed(step: str, res) -> RuntimeError:
    try:
        body = res.json()
    except Exception:
        body = res.text
    return RuntimeError(f"Setup failed at step '{step}': HTTP {res.status_code} {body}")


def _ok(step: str, res) -> dict:
    data = get_success_data(res)
    if res.status_code >= 400:
        raise _setup_failed(step, res)
    return data


# ---------------------------------------------------------------------------
# Tier 0: clock + primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Drive the logical clock (PRD §2.5)."""
    _ok("set_clock", api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def read_clock() -> str:
    return _ok("read_clock", api_client.get_clock(ADMIN))["current_utc"]


def reset_clock() -> None:
    """Pin the logical clock at the deterministic boot default."""
    set_clock(TEST_DEFAULTS["BOOT_CLOCK"])


def create_court(**overrides):
    return _ok("create_court", api_client.create_court(create_court_payload(**overrides), ADMIN))


def create_attorney(admitted_court_ids=(), **overrides) -> dict:
    payload = create_attorney_payload(admitted_court_ids=list(admitted_court_ids), **overrides)
    return _ok("create_attorney", api_client.create_attorney(payload, ADMIN))


def create_case(court: dict, lead_attorney: dict, **overrides) -> dict:
    payload = create_case_payload(court["id"], lead_attorney["id"], **overrides)
    return _ok(
        "create_case",
        api_client.create_case(payload, make_attorney_headers(lead_attorney["id"])),
    )


def attorney_headers(attorney: dict) -> dict:
    return make_attorney_headers(attorney["id"])


# ---------------------------------------------------------------------------
# Tier 1: notice of appeal -> RECORD_PENDING
# ---------------------------------------------------------------------------

def file_and_accept_notice(case: dict, attorney: dict) -> dict:
    """Submit + clerk-accept a NOTICE_OF_APPEAL filing. Posture -> RECORD_PENDING."""
    filing = _ok(
        "create notice-of-appeal filing",
        api_client.create_filing(
            case["id"],
            create_filing_payload("NOTICE_OF_APPEAL"),
            attorney_headers(attorney),
        ),
    )
    _ok("accept notice-of-appeal filing", api_client.accept_filing(filing["id"], CLERK))
    return filing


def get_case_record(case_id: str, headers) -> dict:
    """Fetch the 1:1 record row of a case (list envelope)."""
    data = _ok("get case record", api_client.get_case_record(case_id, headers))
    rows = data if isinstance(data, list) else [data]
    assert rows, f"Setup failed: case {case_id} has no record row"
    return rows[0]


def get_case_schedule(case_id: str, headers, status: str = None) -> dict:
    """Fetch the case's briefing schedule (list envelope). When several exist
    (e.g. after a rehearing-driven reopen), pick by status if given."""
    data = _ok("get case schedule", api_client.get_case_schedule(case_id, headers))
    rows = data if isinstance(data, list) else [data]
    assert rows, f"Setup failed: case {case_id} has no briefing schedule"
    if status is not None:
        matches = [r for r in rows if r.get("status") == status]
        assert matches, f"Setup failed: no schedule with status {status} on case {case_id}"
        return matches[0]
    return rows[0]


def setup_record_pending_case(court_overrides=None, **case_overrides) -> dict:
    """Court + lead attorney (admitted) + case + accepted notice of appeal.

    Returns ctx with keys: court, attorney (lead), case, record, schedule.
    Case posture is RECORD_PENDING; record is PENDING_DESIGNATION; schedule
    is PENDING.
    """
    reset_clock()
    court = create_court(**(court_overrides or {}))
    attorney = create_attorney(admitted_court_ids=[court["id"]])
    case = create_case(court, attorney, **case_overrides)
    notice_filing = file_and_accept_notice(case, attorney)
    record = get_case_record(case["id"], attorney_headers(attorney))
    schedule = get_case_schedule(case["id"], attorney_headers(attorney))
    return {
        "court": court,
        "attorney": attorney,
        "case": case,
        "notice_filing": notice_filing,
        "record": record,
        "schedule": schedule,
    }


# ---------------------------------------------------------------------------
# Tier 2: record completion -> BRIEFING
# ---------------------------------------------------------------------------

def order_transcript(record_id: str, attorney: dict, **overrides) -> dict:
    return _ok(
        "order transcript",
        api_client.create_transcript_order(
            record_id,
            create_transcript_order_payload(**overrides),
            attorney_headers(attorney),
        ),
    )


def complete_record(record: dict, attorney: dict, complete_clock: str = None) -> dict:
    """Designate -> order one transcript -> begin preparation -> deliver.

    If complete_clock is given, the logical clock is pinned there just before
    delivery so the record's completion instant (the schedule anchor) is exact.
    Returns the final record row (status COMPLETE).
    """
    rec_id = record["id"]
    _ok("designate record", api_client.designate_record(rec_id, attorney_headers(attorney)))
    transcript = order_transcript(rec_id, attorney)
    _ok("begin preparation", api_client.begin_preparation(transcript["id"], CLERK))
    if complete_clock is not None:
        set_clock(complete_clock)
    _ok(
        "deliver transcript",
        api_client.deliver_transcript(transcript["id"], deliver_transcript_payload(), CLERK),
    )
    final = _ok("fetch completed record", api_client.get_record(rec_id, attorney_headers(attorney)))
    if final.get("status") != "COMPLETE":
        raise RuntimeError(f"Setup failed: record {rec_id} status is {final.get('status')}, expected COMPLETE")
    return final


def setup_briefing_case(court_overrides=None, complete_clock: str = None, add_reviewer: bool = True, **case_overrides) -> dict:
    """Full drive to BRIEFING: notice accepted, record COMPLETE, schedule ACTIVE.

    Returns ctx: court, attorney (lead/author), reviewer, case, record, schedule.
    """
    ctx = setup_record_pending_case(court_overrides=court_overrides, **case_overrides)
    reviewer = None
    if add_reviewer:
        reviewer = create_attorney(admitted_court_ids=[ctx["court"]["id"]])
        ctx["reviewer"] = reviewer
    record = complete_record(ctx["record"], ctx["attorney"], complete_clock=complete_clock)
    schedule = get_case_schedule(ctx["case"]["id"], attorney_headers(ctx["attorney"]))
    if schedule.get("status") != "ACTIVE":
        raise RuntimeError(f"Setup failed: schedule status is {schedule.get('status')}, expected ACTIVE")
    ctx["record"] = record
    ctx["schedule"] = schedule
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: brief lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_brief(ctx: dict, brief_type: str = "OPENING", author: dict = None, **overrides) -> dict:
    author = author or ctx["attorney"]
    payload = create_brief_payload(
        ctx["schedule"]["id"], author["id"], brief_type=brief_type, **overrides
    )
    return _ok(
        "create brief",
        api_client.create_brief(ctx["case"]["id"], payload, attorney_headers(author)),
    )


def submit_brief(brief: dict, author: dict) -> dict:
    return _ok("submit-review", api_client.submit_review(brief["id"], attorney_headers(author)))


def approve_brief(brief: dict, reviewer: dict) -> dict:
    return _ok("approve brief", api_client.approve_brief(brief["id"], attorney_headers(reviewer)))


def efile_brief(brief: dict, attorney: dict, served_party_emails=None) -> dict:
    """E-file a READY brief; returns the created Filing row."""
    payload = {"served_party_emails": list(served_party_emails or TEST_DEFAULTS["SERVED_EMAILS"])}
    return _ok("efile brief", api_client.efile_brief(brief["id"], payload, attorney_headers(attorney)))


def walk_brief_to_ready(ctx: dict, brief: dict, reviewer: dict = None) -> dict:
    reviewer = reviewer or ctx.get("reviewer")
    submit_brief(brief, ctx["attorney"])
    return approve_brief(brief, reviewer)


def walk_brief_to_efiled(ctx: dict, brief: dict, reviewer: dict = None) -> dict:
    walk_brief_to_ready(ctx, brief, reviewer=reviewer)
    return efile_brief(brief, ctx["attorney"])


def walk_brief_to_accepted(ctx: dict, brief: dict, reviewer: dict = None) -> dict:
    """DRAFT -> IN_REVIEW -> READY -> EFILED -> ACCEPTED. Returns the filing."""
    filing = walk_brief_to_efiled(ctx, brief, reviewer=reviewer)
    _ok("accept brief filing", api_client.accept_filing(filing["id"], CLERK))
    return filing


# ---------------------------------------------------------------------------
# Tier 4: full lifecycle — ARGUMENT_PENDING and DECIDED
# ---------------------------------------------------------------------------

def setup_argument_pending_case(court: dict = None, attorneys: tuple = None, **case_overrides) -> dict:
    """Drive a case all the way to ARGUMENT_PENDING.

    Both an OPENING and a RESPONSE brief are taken to ACCEPTED; the clock is
    then advanced past reply_due_at so the schedule completes (PRD §3.4) and
    the posture becomes ARGUMENT_PENDING with an oral argument REQUESTED.

    Returns ctx (from setup_briefing_case) plus "oral_argument".
    """
    if court is not None and attorneys is not None:
        attorney, reviewer = attorneys
        reset_clock()
        case = create_case(court, attorney, **case_overrides)
        file_and_accept_notice(case, attorney)
        record = get_case_record(case["id"], attorney_headers(attorney))
        record = complete_record(record, attorney)
        schedule = get_case_schedule(case["id"], attorney_headers(attorney))
        if schedule.get("status") != "ACTIVE":
            raise RuntimeError(f"Setup failed: schedule status {schedule.get('status')}, expected ACTIVE")
        ctx = {
            "court": court, "attorney": attorney, "reviewer": reviewer,
            "case": case, "record": record, "schedule": schedule,
        }
    else:
        ctx = setup_briefing_case(**case_overrides)

    opening = create_brief(ctx, "OPENING")
    response = create_brief(ctx, "RESPONSE")
    walk_brief_to_accepted(ctx, opening)
    walk_brief_to_accepted(ctx, response)

    # Advance the clock past the reply window so the schedule completes.
    reply_due = parse_ts(ctx["schedule"]["reply_due_at"])
    from datetime import timedelta
    set_clock(iso_utc(reply_due + timedelta(days=1)))

    case_now = _ok("fetch case", api_client.get_case(ctx["case"]["id"], attorney_headers(ctx["attorney"])))
    if case_now.get("posture") != "ARGUMENT_PENDING":
        raise RuntimeError(f"Setup failed: posture is {case_now.get('posture')}, expected ARGUMENT_PENDING")
    args = _ok(
        "list oral arguments",
        api_client.list_case_oral_arguments(ctx["case"]["id"], attorney_headers(ctx["attorney"])),
    )
    args = args if isinstance(args, list) else [args]
    requested = [a for a in args if a.get("status") == "REQUESTED"]
    if not requested:
        raise RuntimeError("Setup failed: no oral argument auto-created in REQUESTED")
    ctx["case"] = case_now
    ctx["oral_argument"] = requested[0]
    return ctx


def waive_argument(ctx: dict) -> dict:
    """Lead attorney waives the REQUESTED argument (PRD §3.7)."""
    return _ok(
        "waive argument",
        api_client.waive_argument(ctx["oral_argument"]["id"], attorney_headers(ctx["attorney"])),
    )


def enter_decision(ctx: dict, outcome: str = "AFFIRMED", issued_at: str = None) -> dict:
    """Enter a decision; requires the case's argument to stand HELD or WAIVED."""
    if issued_at is None:
        issued_at = read_clock()
    return _ok(
        "enter decision",
        api_client.create_decision(
            ctx["case"]["id"],
            create_decision_payload(outcome=outcome, issued_at=issued_at),
            CLERK,
        ),
    )


def setup_decided_case(outcome: str = "AFFIRMED", issued_at: str = None, **case_overrides) -> dict:
    """Full lifecycle through DECIDED. Returns ctx plus "decision"."""
    ctx = setup_argument_pending_case(**case_overrides)
    waive_argument(ctx)
    decision = enter_decision(ctx, outcome=outcome, issued_at=issued_at)
    case_now = _ok("fetch decided case", api_client.get_case(ctx["case"]["id"], attorney_headers(ctx["attorney"])))
    if case_now.get("posture") != "DECIDED":
        raise RuntimeError(f"Setup failed: posture is {case_now.get('posture')}, expected DECIDED")
    ctx["case"] = case_now
    ctx["decision"] = decision
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: motions
# ---------------------------------------------------------------------------

def create_motion(ctx: dict, target: str = "OPENING", requested_days: int = 7,
                  attorney: dict = None, **overrides) -> dict:
    attorney = attorney or ctx["attorney"]
    payload = create_extension_motion_payload(
        ctx["schedule"]["id"], target=target, requested_days=requested_days, **overrides
    )
    return _ok(
        "create extension motion",
        api_client.create_extension_motion(ctx["case"]["id"], payload, attorney_headers(attorney)),
    )


def grant_motion(motion: dict, granted_days: int, expected_schedule_version: int):
    """Raw grant call (no validation) so tests can assert on the response."""
    return api_client.grant_motion(
        motion["id"],
        grant_motion_payload(granted_days, expected_schedule_version),
        CLERK,
    )


def get_schedule_version(ctx: dict) -> int:
    sched = _ok("fetch schedule", api_client.get_schedule(ctx["schedule"]["id"], attorney_headers(ctx["attorney"])))
    ctx["schedule"] = sched
    return sched["version"]


def get_case_version(ctx: dict) -> int:
    case = _ok("fetch case", api_client.get_case(ctx["case"]["id"], attorney_headers(ctx["attorney"])))
    ctx["case"] = case
    return case["version"]


def list_case_deadlines(ctx: dict, kind: str = None) -> list:
    data = _ok(
        "list deadlines",
        api_client.list_case_deadlines(ctx["case"]["id"], attorney_headers(ctx["attorney"])),
    )
    rows = data if isinstance(data, list) else [data]
    if kind is not None:
        rows = [d for d in rows if d.get("kind") == kind]
    return rows
