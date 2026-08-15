"""Composite setup helpers for multi-step test prerequisites.

Every helper builds preconditions from scratch via PRD-declared endpoints
(the harness restarts the server before every test, so each test starts
against an empty database with the logical clock at 2026-08-01T00:00:00Z).

Uses get_success_data() (lenient) so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Identity threading: RegisteredRep calls are ownership-gated, so any
rep-scoped call uses make_registered_rep_headers(rep["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    adjudicate_payload,
    close_inspection_payload,
    create_activity_payload,
    create_branch_payload,
    create_complaint_payload,
    create_correspondence_payload,
    create_disclosure_payload,
    create_finding_payload,
    create_inspection_payload,
    create_meeting_payload,
    create_plan_payload,
    create_representative_payload,
    remediate_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_registered_rep_headers

FIRM_ADMIN = TEST_USERS["firm_admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]
PRINCIPAL_B = TEST_USERS["principal_b_headers"]
ANY = TEST_USERS["any_headers"]


# ─── Tier 1: reference data ───────────────────────────

def make_branch(name="Test Branch", region="NE", **overrides):
    """Create a branch office. Returns the branch dict."""
    return get_success_data(
        api_client.create_branch(
            create_branch_payload(name=name, region=region, **overrides), FIRM_ADMIN
        )
    )


def make_rep(branch_id, crd_number="100001", full_name="Test Rep", **overrides):
    """Register a representative on a branch. Returns the rep dict."""
    return get_success_data(
        api_client.create_representative(
            create_representative_payload(
                branch_id, crd_number=crd_number, full_name=full_name, **overrides
            ),
            FIRM_ADMIN,
        )
    )


def make_branch_with_rep(region="NE", crd_number="100001", **rep_overrides):
    """Branch + one ACTIVE rep. Returns (branch, rep)."""
    branch = make_branch(region=region)
    rep = make_rep(branch["id"], crd_number=crd_number, **rep_overrides)
    return branch, rep


def get_branch(branch_id):
    return get_success_data(api_client.get_branch(branch_id, ANY))


def get_rep(rep_id):
    return get_success_data(api_client.get_representative(rep_id, ANY))


def set_clock(to_iso8601):
    """Move the logical clock (runs the PRD §2.5 sweeps). Returns current_utc body."""
    return get_success_data(
        api_client.set_clock(set_clock_payload(to_iso8601), FIRM_ADMIN)
    )


# ─── Tier 1/2: inspections and findings ───────────────

def schedule_inspection(branch_id, scheduled_date="2026-08-10"):
    """Schedule an inspection against the branch's CURRENT version (OCC).
    Returns the raw response so callers can assert success or failure."""
    branch = get_branch(branch_id)
    return api_client.create_inspection(
        create_inspection_payload(
            branch_id,
            expected_branch_version=branch["version"],
            scheduled_date=scheduled_date,
        ),
        ANALYST,
    )


def schedule_and_start_inspection(branch_id, scheduled_date="2026-08-10"):
    """Schedule + start. Returns the IN_PROGRESS inspection dict."""
    inspection = get_success_data(schedule_inspection(branch_id, scheduled_date))
    return get_success_data(api_client.start_inspection(inspection["id"], ANALYST))


def setup_in_progress_inspection(region="NE"):
    """Branch + IN_PROGRESS inspection. Returns (branch, inspection)."""
    branch = make_branch(region=region)
    inspection = schedule_and_start_inspection(branch["id"])
    return get_branch(branch["id"]), inspection


def add_finding(inspection_id, severity="LOW", due_date="2026-09-01",
                description="finding"):
    """Record a finding on an IN_PROGRESS inspection. Returns finding dict."""
    return get_success_data(
        api_client.create_finding(
            create_finding_payload(
                inspection_id,
                severity=severity,
                due_date=due_date,
                description=description,
            ),
            ANALYST,
        )
    )


def remediate_finding(finding_id, note="fixed"):
    return get_success_data(
        api_client.remediate_finding(
            finding_id, remediate_payload(remediation_note=note), ANALYST
        )
    )


def adjudicate_finding(finding_id, decision="VERIFY", **kwargs):
    return get_success_data(
        api_client.adjudicate_finding(
            finding_id, adjudicate_payload(decision, **kwargs), PRINCIPAL_A
        )
    )


def close_inspection_now(inspection_id):
    """Close an inspection carrying the branch's CURRENT version (OCC).
    Returns the raw response so callers can assert the fork outcome."""
    inspection = get_success_data(api_client.get_inspection(inspection_id, ANY))
    branch = get_branch(inspection["branch_id"])
    return api_client.close_inspection(
        inspection_id,
        close_inspection_payload(branch["version"]),
        PRINCIPAL_A,
    )


def setup_branch_with_closed_inspection(completed_clock="2026-03-01T09:00:00Z",
                                        scheduled_date="2026-03-01"):
    """Branch with one zero-finding CLOSED inspection completed at
    `completed_clock`. Returns (branch, inspection). Restores nothing —
    callers set whatever clock they need afterwards."""
    branch = make_branch(region="W")
    set_clock(completed_clock)
    inspection = schedule_and_start_inspection(branch["id"], scheduled_date)
    closed = get_success_data(close_inspection_now(inspection["id"]))
    assert closed["status"] == "CLOSED", f"Setup failed: {closed}"
    return get_branch(branch["id"]), closed


# ─── Tier 2: correspondence ───────────────────────────

def make_correspondence(rep_id, channel="EMAIL", lexicon_hits=0, subject="note"):
    """Capture a correspondence item. Returns the PENDING_REVIEW item dict."""
    return get_success_data(
        api_client.create_correspondence_item(
            create_correspondence_payload(
                rep_id, channel=channel, lexicon_hits=lexicon_hits, subject=subject
            ),
            ANALYST,
        )
    )


def review_item(item_id, decision, principal_headers=PRINCIPAL_A):
    return get_success_data(
        api_client.review_correspondence_item(
            item_id, {"decision": decision}, principal_headers
        )
    )


def make_escalated_correspondence(channel="EMAIL", lexicon_hits=0,
                                  escalated_by=PRINCIPAL_A):
    """Branch + rep + one item ESCALATED by `escalated_by`.
    Returns (rep, item)."""
    branch, rep = make_branch_with_rep(region="N")
    item = make_correspondence(rep["id"], channel=channel, lexicon_hits=lexicon_hits)
    item = review_item(item["id"], "ESCALATE", escalated_by)
    return rep, item


# ─── Tier 2: outside activities ───────────────────────

def make_activity(rep, **overrides):
    """Submit an OBA/PST as the owning rep (entity-backed identity).
    Returns the SUBMITTED request dict."""
    return get_success_data(
        api_client.create_outside_activity(
            create_activity_payload(**overrides),
            make_registered_rep_headers(rep["id"]),
        )
    )


def make_approved_activity(rep, decision="APPROVE", **overrides):
    """Submit + approve. Returns the APPROVED/APPROVED_WITH_CONDITIONS dict."""
    activity = make_activity(rep, **overrides)
    payload = {"decision": decision}
    if decision == "APPROVE_WITH_CONDITIONS":
        payload["conditions"] = overrides.get("conditions", ["STANDARD_CONDITION"])
    return get_success_data(
        api_client.decide_outside_activity(activity["id"], payload, PRINCIPAL_A)
    )


# ─── Tier 3: statutory disqualification chain ─────────

def make_sd_disclosure(rep_id, event_type="FELONY_CONVICTION",
                       event_date="2026-08-01", filed=True):
    """Draft (+ optionally file) a disclosure event. Returns the event dict."""
    event = get_success_data(
        api_client.create_disclosure_event(
            create_disclosure_payload(
                rep_id, event_type=event_type, event_date=event_date
            ),
            ANALYST,
        )
    )
    if filed:
        event = get_success_data(
            api_client.file_disclosure_event(event["id"], PRINCIPAL_A)
        )
    return event


def acknowledge_disclosure(event_id):
    return get_success_data(
        api_client.acknowledge_disclosure_event(event_id, PRINCIPAL_A)
    )


def make_sd_rep(branch=None, crd_number="200001", event_type="FELONY_CONVICTION",
                event_date="2026-08-01"):
    """Rep flagged statutorily disqualified via the acknowledge cascade.
    Returns (branch, refreshed rep, acknowledged disclosure)."""
    if branch is None:
        branch = make_branch(region="W")
    rep = make_rep(branch["id"], crd_number=crd_number)
    event = make_sd_disclosure(rep["id"], event_type=event_type,
                               event_date=event_date)
    event = acknowledge_disclosure(event["id"])
    return get_branch(branch["id"]), get_rep(rep["id"]), event


def create_plan_for_rep(rep_id, start_date="2026-08-03", end_date="2027-08-02",
                        conditions=("MONTHLY_REVIEW",)):
    """Create a DRAFT plan carrying the rep's CURRENT version (OCC).
    Returns the raw response so callers can assert success or failure."""
    rep = get_rep(rep_id)
    return api_client.create_supervision_plan(
        create_plan_payload(
            rep_id,
            expected_representative_version=rep["version"],
            start_date=start_date,
            end_date=end_date,
            conditions=list(conditions),
        ),
        PRINCIPAL_A,
    )


def make_active_plan(rep_id, start_date="2026-08-03", end_date="2027-08-02",
                     conditions=("MONTHLY_REVIEW",)):
    """Create + activate a heightened plan for an SD-flagged rep.
    Returns the ACTIVE plan dict."""
    plan = get_success_data(
        create_plan_for_rep(rep_id, start_date, end_date, conditions)
    )
    return get_success_data(api_client.activate_supervision_plan(plan["id"], PRINCIPAL_A))


def make_sd_rep_with_active_plan(branch=None, crd_number="200002",
                                 event_type="REGULATORY_BAR"):
    """SD-flagged rep with an ACTIVE heightened plan.
    Returns (branch, rep, plan)."""
    branch, rep, _event = make_sd_rep(
        branch=branch, crd_number=crd_number, event_type=event_type
    )
    plan = make_active_plan(rep["id"])
    return get_branch(branch["id"]), get_rep(rep["id"]), plan


def make_suspended_oba(crd_number="500001", event_type="SECURITIES_MISDEMEANOR",
                       activity_overrides=None):
    """Rep with a SUBMITTED OBA that the SD-ack cascade suspends.
    Returns (branch, rep, activity in SUSPENDED_REVIEW)."""
    branch, rep = make_branch_with_rep(region="N", crd_number=crd_number)
    activity = make_activity(rep, **(activity_overrides or {}))
    event = make_sd_disclosure(rep["id"], event_type=event_type,
                               event_date="2026-08-02")
    acknowledge_disclosure(event["id"])
    suspended = get_success_data(
        api_client.get_outside_activity(activity["id"], ANY)
    )
    assert suspended["status"] == "SUSPENDED_REVIEW", f"Setup failed: {suspended}"
    return get_branch(branch["id"]), get_rep(rep["id"]), suspended


# ─── Tier 3: meetings and attestations ────────────────

def make_meeting(year=2026, meeting_date="2026-12-15"):
    """Schedule the annual meeting (fans out PENDING attestations to all
    currently-ACTIVE reps). Returns the meeting dict."""
    return get_success_data(
        api_client.create_meeting(
            create_meeting_payload(year=year, meeting_date=meeting_date), PRINCIPAL_A
        )
    )


def attestation_map(meeting_id):
    """All attestations of a meeting keyed by rep_id."""
    data = get_success_data(
        api_client.list_attestations(ANY, params={"meeting_id": meeting_id})
    )
    assert isinstance(data, list), f"Setup failed: expected list, got {data!r}"
    return {a["rep_id"]: a for a in data}


def setup_held_meeting(num_reps=1, year=2026, meeting_date="2026-08-01",
                       hold_clock=None, region="E"):
    """Branch + `num_reps` ACTIVE reps + meeting HELD at `hold_clock`
    (defaults to noon on meeting_date). Returns (branch, reps, meeting,
    att_map keyed by rep_id)."""
    branch = make_branch(region=region)
    reps = [
        make_rep(branch["id"], crd_number=str(700000 + i), full_name=f"Rep {i}")
        for i in range(num_reps)
    ]
    meeting = make_meeting(year=year, meeting_date=meeting_date)
    if hold_clock is not None:
        set_clock(hold_clock)
    meeting = get_success_data(api_client.hold_meeting(meeting["id"], PRINCIPAL_A))
    assert meeting["status"] == "HELD", f"Setup failed: {meeting}"
    return branch, reps, meeting, attestation_map(meeting["id"])


def attest_as_owner(attestation_id, rep_id):
    return get_success_data(
        api_client.attest(attestation_id, make_registered_rep_headers(rep_id))
    )
