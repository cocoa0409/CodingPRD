"""Cascading state transitions.

The recruitment platform has several multi-level cascade chains:

  Company EXPIRED      -> JobPosting LIVE -> OFF_SHELF -> ...
  Company BLACKLISTED  -> JobPosting {DRAFT,UNDER_REVIEW,LIVE} -> OFF_SHELF
                       -> HeadhunterContract ACTIVE -> TERMINATED
  JobPosting OFF_SHELF/EXPIRED -> Application {SUBMITTED,READ,FORWARDED} -> CLOSED
  Application CLOSED/REJECTED -> InterviewRound non-terminal -> CANCELLED

Every cascaded transition bumps version, refreshes updated_at, and writes an
AuditEvent with actor_role=system and actor_user_id=system.
"""
from __future__ import annotations

from typing import Any, Dict, List

from clock import iso_now
from store import append_audit, bump, store


SYSTEM_ACTOR_ROLE = "system"
SYSTEM_ACTOR_USER_ID = "system"


def _audit_state(entity: str, row: Dict[str, Any], from_state: str, to_state: str,
                 actor_role: str = SYSTEM_ACTOR_ROLE,
                 actor_user_id: str = SYSTEM_ACTOR_USER_ID) -> None:
    append_audit(
        subject_entity=entity,
        subject_id=row["id"],
        event_kind="STATE_TRANSITION",
        from_state=from_state,
        to_state=to_state,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )


# ---------------------------------------------------------------------------
# InterviewRound cancellation cascade
# ---------------------------------------------------------------------------
NON_TERMINAL_ROUND_STATUSES = {"DRAFT", "AWAITING_CANDIDATE", "SCHEDULED", "FEEDBACK_PENDING"}


def cancel_rounds_for_application(application_id: str,
                                  actor_role: str = SYSTEM_ACTOR_ROLE,
                                  actor_user_id: str = SYSTEM_ACTOR_USER_ID) -> None:
    for r in list(store.interview_rounds.values()):
        if r.get("application_id") != application_id:
            continue
        old_status = r.get("round_status")
        if old_status in NON_TERMINAL_ROUND_STATUSES:
            r["round_status"] = "CANCELLED"
            bump(r)
            _audit_state("InterviewRound", r, old_status, "CANCELLED",
                         actor_role=actor_role, actor_user_id=actor_user_id)


# ---------------------------------------------------------------------------
# Application close cascade from a JobPosting going OFF_SHELF/EXPIRED
# ---------------------------------------------------------------------------
APPS_CLOSEABLE = {"SUBMITTED", "READ", "FORWARDED"}


def close_applications_for_posting(job_posting_id: str,
                                   actor_role: str = SYSTEM_ACTOR_ROLE,
                                   actor_user_id: str = SYSTEM_ACTOR_USER_ID) -> None:
    for app in list(store.applications.values()):
        if app.get("job_posting_id") != job_posting_id:
            continue
        old = app.get("application_status")
        if old in APPS_CLOSEABLE:
            app["application_status"] = "CLOSED"
            bump(app)
            _audit_state("Application", app, old, "CLOSED",
                         actor_role=actor_role, actor_user_id=actor_user_id)
            # FORWARDED→CLOSED additionally cancels any non-terminal interview rounds.
            # The spec also says any non-terminal round on a closed application is
            # cancelled. We do this for any closing application defensively.
            cancel_rounds_for_application(app["id"], actor_role=actor_role,
                                          actor_user_id=actor_user_id)


# ---------------------------------------------------------------------------
# JobPosting off-shelf side-effects (decrement count + close applications)
# ---------------------------------------------------------------------------
def take_posting_off_shelf(
    posting: Dict[str, Any],
    *,
    to_state: str = "OFF_SHELF",
    actor_role: str = SYSTEM_ACTOR_ROLE,
    actor_user_id: str = SYSTEM_ACTOR_USER_ID,
) -> None:
    """Transition a LIVE posting to OFF_SHELF or EXPIRED, run its cascade.

    The decrement of the owning Company.active_job_posting_count is applied
    only when the source state is LIVE (i.e., the count was previously
    incremented). For DRAFT/UNDER_REVIEW postings moving to OFF_SHELF
    (via blacklist cascade), no decrement happens.
    """
    old = posting.get("posting_status")
    if old not in {"DRAFT", "UNDER_REVIEW", "LIVE"}:
        return
    was_live = (old == "LIVE")
    posting["posting_status"] = to_state
    posting["off_shelf_at"] = iso_now()
    bump(posting)
    if was_live:
        company = store.companies.get(posting.get("company_id"))
        if company is not None:
            company["active_job_posting_count"] = max(
                0, int(company.get("active_job_posting_count", 0)) - 1
            )
            bump(company)
    _audit_state("JobPosting", posting, old, to_state,
                 actor_role=actor_role, actor_user_id=actor_user_id)
    close_applications_for_posting(posting["id"], actor_role=actor_role,
                                   actor_user_id=actor_user_id)


# ---------------------------------------------------------------------------
# Company cascades
# ---------------------------------------------------------------------------
def cascade_company_expired(company: Dict[str, Any],
                            actor_role: str = SYSTEM_ACTOR_ROLE,
                            actor_user_id: str = SYSTEM_ACTOR_USER_ID) -> None:
    """All LIVE postings owned by this Company → OFF_SHELF."""
    for p in list(store.job_postings.values()):
        if p.get("company_id") != company["id"]:
            continue
        if p.get("posting_status") == "LIVE":
            take_posting_off_shelf(p, to_state="OFF_SHELF",
                                   actor_role=actor_role, actor_user_id=actor_user_id)


def cascade_company_blacklisted(company: Dict[str, Any],
                                actor_role: str,
                                actor_user_id: str) -> None:
    """All postings in {DRAFT,UNDER_REVIEW,LIVE} → OFF_SHELF; all ACTIVE contracts → TERMINATED."""
    for p in list(store.job_postings.values()):
        if p.get("company_id") != company["id"]:
            continue
        if p.get("posting_status") in {"DRAFT", "UNDER_REVIEW", "LIVE"}:
            take_posting_off_shelf(p, to_state="OFF_SHELF",
                                   actor_role=actor_role, actor_user_id=actor_user_id)
    for c in list(store.headhunter_contracts.values()):
        if c.get("company_id") != company["id"]:
            continue
        if c.get("contract_status") == "ACTIVE":
            old = c["contract_status"]
            c["contract_status"] = "TERMINATED"
            bump(c)
            _audit_state("HeadhunterContract", c, old, "TERMINATED",
                         actor_role=actor_role, actor_user_id=actor_user_id)
