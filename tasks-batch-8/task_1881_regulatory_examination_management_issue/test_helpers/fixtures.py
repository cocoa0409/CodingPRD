"""Composite setup helpers (PRD §3 workflows).

Every test starts against a freshly restarted server (empty database), so each
fixture builds its preconditions from scratch using only PRD-declared
endpoints. Setup calls use the lenient get_success_data() validator so a
broken precondition surfaces as a clear "Setup step failed" error.

Identity threading (PRD §2.1): RemediationOwner calls carry the acting
BankOfficer's id; ComplianceReviewer calls carry the acting
ComplianceReviewer's id.

Logical clock (PRD §2.5): the server starts at 2026-08-01T00:00:00Z. Scenarios
that must create several first-day items whose due dates sit before the
default clock first move the clock earlier (the capability accepts an
arbitrary target instant), because an already-overdue item flips the
examination posture at creation time (PRD §3.2 recomputes overdue_item_count
on every addition; §3.8 recomputes posture whenever that count changes; §2.9
step 13 then blocks further item creation under RESTRICTED/FROZEN).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_agency_payload,
    create_examination_payload,
    create_examiner_meeting_payload,
    create_first_day_item_payload,
    create_issue_payload,
    create_milestone_payload,
    create_officer_payload,
    create_remediation_plan_payload,
    create_reviewer_payload,
    create_submit_validation_payload,
    create_validation_evidence_payload,
)
from .test_users import (
    TEST_USERS,
    make_compliance_reviewer_headers,
    make_remediation_owner_headers,
)

ADMIN = TEST_USERS["platform_admin_headers"]
RAM = TEST_USERS["ram_headers"]
BOARD = TEST_USERS["board_reporter_headers"]


# ─── Tier 0: single-resource creators ───────────────────────────────────────

def create_agency(**overrides) -> dict:
    resp = api_client.create_agency(create_agency_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_officer(**overrides) -> dict:
    resp = api_client.create_officer(create_officer_payload(**overrides), ADMIN)
    return get_success_data(resp, 201)


def create_reviewer(certification_level: str = "L3", **overrides) -> dict:
    resp = api_client.create_reviewer(
        create_reviewer_payload(certification_level=certification_level, **overrides), ADMIN)
    return get_success_data(resp, 201)


def create_examination(agency_id: str, **overrides) -> dict:
    resp = api_client.create_examination(
        create_examination_payload(agency_id, **overrides), RAM)
    return get_success_data(resp, 201)


def set_logical_clock(to_iso8601: str) -> dict:
    resp = api_client.set_current_utc({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def get_exam(exam_id: str) -> dict:
    return get_success_data(api_client.get_examination(exam_id, RAM))


def get_issue(issue_id: str) -> dict:
    return get_success_data(api_client.get_issue(issue_id, RAM))


def get_plan(plan_id: str) -> dict:
    return get_success_data(api_client.get_remediation_plan(plan_id, RAM))


# ─── Tier 1: examination state progression ──────────────────────────────────

def create_first_day_item(exam_id: str, **overrides) -> dict:
    resp = api_client.create_first_day_item(
        exam_id, create_first_day_item_payload(**overrides), RAM)
    return get_success_data(resp, 201)


def issue_first_day_letter(exam_id: str) -> dict:
    return get_success_data(api_client.issue_first_day_letter(exam_id, RAM))


def waive_item(item_id: str, waived_reason: str = "Not applicable to this scope") -> dict:
    return get_success_data(
        api_client.waive_first_day_item(item_id, {"waived_reason": waived_reason}, RAM))


def begin_fieldwork(exam_id: str) -> dict:
    return get_success_data(api_client.begin_fieldwork(exam_id, RAM))


def create_meeting(exam_id: str, **overrides) -> dict:
    resp = api_client.create_examiner_meeting(
        create_examiner_meeting_payload(exam_id, **overrides), RAM)
    return get_success_data(resp, 201)


def finalize_meeting(meeting_id: str) -> dict:
    return get_success_data(api_client.finalize_examiner_meeting(meeting_id, RAM))


def deliver_findings(exam_id: str) -> dict:
    return get_success_data(api_client.deliver_findings(exam_id, RAM))


def file_issue(exam_id: str, **overrides) -> dict:
    """File an issue, threading a freshly observed examination version (PRD §2.7)."""
    if "expected_examination_version" not in overrides:
        overrides["expected_examination_version"] = get_exam(exam_id)["version"]
    resp = api_client.create_issue(exam_id, create_issue_payload(**overrides), RAM)
    return get_success_data(resp, 201)


def open_remediation(exam_id: str) -> dict:
    return get_success_data(api_client.open_remediation(exam_id, RAM))


# ─── Tier 2: entity hierarchy ───────────────────────────────────────────────

def setup_exam_with_items(
    num_items: int = 1,
    item_due_date: str = "2026-07-15T00:00:00Z",
    clock_start: str = None,
    agency_overrides: dict = None,
    exam_overrides: dict = None,
) -> dict:
    """Agency + examination + N first-day items (still PENDING).

    clock_start: when given, the logical clock is moved there BEFORE items are
    created so that past-due items do not flip the posture mid-roster.
    Returns {"agency", "exam", "items"}.
    """
    agency = create_agency(**(agency_overrides or {}))
    exam = create_examination(agency["id"], **(exam_overrides or {}))
    if clock_start is not None:
        set_logical_clock(clock_start)
    items = [
        create_first_day_item(exam["id"], due_date=item_due_date,
                              request_ref=f"FDL-{i + 1}")
        for i in range(num_items)
    ]
    return {"agency": agency, "exam": get_exam(exam["id"]), "items": items}


def setup_exam_first_day_issued(**kwargs) -> dict:
    ctx = setup_exam_with_items(**kwargs)
    ctx["exam"] = issue_first_day_letter(ctx["exam"]["id"])
    return ctx


def setup_exam_fieldwork(**kwargs) -> dict:
    """FIRST_DAY_ISSUED -> FIELDWORK: every item waived, then begin."""
    ctx = setup_exam_first_day_issued(**kwargs)
    for item in ctx["items"]:
        waive_item(item["id"])
    ctx["exam"] = begin_fieldwork(ctx["exam"]["id"])
    return ctx


def setup_exam_findings_delivered(**kwargs) -> dict:
    """FIELDWORK -> FINDINGS_DELIVERED via one finalized meeting."""
    ctx = setup_exam_fieldwork(**kwargs)
    meeting = create_meeting(ctx["exam"]["id"])
    ctx["meeting"] = finalize_meeting(meeting["id"])
    ctx["exam"] = deliver_findings(ctx["exam"]["id"])
    return ctx


# ─── Tier 3: issue / plan lifecycle shortcuts ───────────────────────────────

def setup_exam_remediation(
    issue_overrides: dict = None,
    reviewer_level: str = "L1",
    **kwargs,
) -> dict:
    """FINDINGS_DELIVERED -> REMEDIATION with one issue on the books.

    Adds "issue", "officer", "reviewer" to the context.
    """
    ctx = setup_exam_findings_delivered(**kwargs)
    ctx["issue"] = file_issue(ctx["exam"]["id"], **(issue_overrides or {}))
    ctx["exam"] = open_remediation(ctx["exam"]["id"])
    ctx["officer"] = create_officer()
    ctx["reviewer"] = create_reviewer(certification_level=reviewer_level)
    ctx["owner_headers"] = make_remediation_owner_headers(ctx["officer"]["id"])
    ctx["reviewer_headers"] = make_compliance_reviewer_headers(ctx["reviewer"]["id"])
    return ctx


def create_plan_with_milestone(
    issue_id: str,
    owner_headers: dict,
    plan_overrides: dict = None,
    milestone_overrides: dict = None,
) -> dict:
    """Create a DRAFT plan and give it its first milestone.

    A plan must hold at least one milestone before it can be submitted
    (PRD §3.6), so the milestone is added while the plan is still DRAFT.
    The plan's owner_user_id defaults to the acting officer's id — per
    PRD §2.1 the RemediationOwner's X-User-ID IS that BankOfficer's id.
    Returns {"plan", "milestone"}.
    """
    merged_plan_overrides = {"owner_user_id": owner_headers["X-User-ID"]}
    merged_plan_overrides.update(plan_overrides or {})
    plan_resp = api_client.create_remediation_plan(
        issue_id, create_remediation_plan_payload(**merged_plan_overrides),
        owner_headers)
    plan = get_success_data(plan_resp, 201)
    ms_payload = create_milestone_payload(
        expected_plan_version=get_plan(plan["id"])["version"],
        **(milestone_overrides or {}))
    milestone = get_success_data(
        api_client.create_remediation_milestone(plan["id"], ms_payload, owner_headers), 201)
    return {"plan": get_plan(plan["id"]), "milestone": milestone}


def drive_plan_to_status(plan_id: str, target: str, ctx: dict) -> dict:
    """Walk a plan with an existing milestone to DRAFT/SUBMITTED/APPROVED/ACTIVE."""
    plan = get_plan(plan_id)
    owner_headers = ctx["owner_headers"]
    reviewer_headers = ctx["reviewer_headers"]
    if target == "DRAFT":
        return plan
    plan = get_success_data(api_client.submit_remediation_plan(plan_id, owner_headers))
    if target == "SUBMITTED":
        return plan
    plan = get_success_data(api_client.approve_remediation_plan(plan_id, reviewer_headers))
    if target == "APPROVED":
        return plan
    if target == "ACTIVE":
        return get_success_data(api_client.activate_remediation_plan(plan_id, owner_headers))
    raise ValueError(f"unsupported target plan status: {target}")


def setup_active_plan_ctx(**kwargs) -> dict:
    """Exam in REMEDIATION + issue + APPROVED-then-ACTIVE plan with 1 milestone."""
    ctx = setup_exam_remediation(**kwargs)
    bundle = create_plan_with_milestone(ctx["issue"]["id"], ctx["owner_headers"])
    ctx["plan"] = drive_plan_to_status(bundle["plan"]["id"], "ACTIVE", ctx)
    ctx["milestone"] = bundle["milestone"]
    return ctx


def setup_issue_in_progress(**kwargs) -> dict:
    """Active plan whose first milestone has been started (issue IN_PROGRESS)."""
    ctx = setup_active_plan_ctx(**kwargs)
    ctx["milestone"] = get_success_data(
        api_client.start_remediation_milestone(
            ctx["milestone"]["id"], ctx["owner_headers"]))
    return ctx


def add_sufficient_evidence(ctx: dict, **overrides) -> dict:
    evidence = get_success_data(
        api_client.create_validation_evidence(
            ctx["issue"]["id"],
            create_validation_evidence_payload(
                submitted_by_user_id=ctx["officer"]["id"], **overrides),
            ctx["owner_headers"]),
        201)
    return get_success_data(
        api_client.mark_evidence_sufficient(evidence["id"], ctx["reviewer_headers"]))


def setup_plan_complete_ctx(**kwargs) -> dict:
    """Milestone completed so the ACTIVE plan has earned COMPLETE (PRD §3.6),
    and SUFFICIENT evidence is on hand for the issue."""
    ctx = setup_issue_in_progress(**kwargs)
    ctx["milestone"] = get_success_data(
        api_client.complete_remediation_milestone(
            ctx["milestone"]["id"], ctx["owner_headers"]))
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    ctx["evidence"] = add_sufficient_evidence(ctx)
    ctx["issue"] = get_issue(ctx["issue"]["id"])
    return ctx


def setup_validation_submitted(**kwargs) -> dict:
    """Issue driven IN_PROGRESS -> VALIDATION_SUBMITTED; closure request spawned.

    With a single issue on the examination this also auto-advances the
    examination REMEDIATION -> VALIDATION (PRD §3.7).
    """
    ctx = setup_plan_complete_ctx(**kwargs)
    closure = get_success_data(
        api_client.submit_issue_validation(
            ctx["issue"]["id"],
            create_submit_validation_payload(ctx["evidence"]["id"]),
            ctx["owner_headers"]),
        201)
    ctx["closure_request"] = closure
    ctx["issue"] = get_issue(ctx["issue"]["id"])
    ctx["exam"] = get_exam(ctx["exam"]["id"])
    return ctx


def setup_issue_closed(**kwargs) -> dict:
    """Full remediation arc: closure approved, issue CLOSED, exam VALIDATION."""
    ctx = setup_validation_submitted(**kwargs)
    issue_v = get_issue(ctx["issue"]["id"])["version"]
    ctx["closure_request"] = get_success_data(
        api_client.approve_closure_request(
            ctx["closure_request"]["id"],
            {"expected_issue_version": issue_v},
            ctx["reviewer_headers"]))
    ctx["issue"] = get_issue(ctx["issue"]["id"])
    ctx["exam"] = get_exam(ctx["exam"]["id"])
    return ctx


def setup_exam_closed(**kwargs) -> dict:
    """Entire lifecycle through examination CLOSED (VALIDATION -> CLOSED)."""
    ctx = setup_issue_closed(**kwargs)
    ctx["exam"] = get_success_data(api_client.close_examination(ctx["exam"]["id"], RAM))
    return ctx


# ─── Tier 4: threshold / accumulation targeting ─────────────────────────────

def setup_exam_with_overdue_items(
    num_items: int,
    item_due_date: str = "2026-07-20T00:00:00Z",
    clock_after: str = "2026-07-21T00:00:00Z",
    issue_letter: bool = True,
    **kwargs,
) -> dict:
    """Exam holding exactly num_items overdue PENDING first-day items.

    The clock is parked at 2026-07-01 while the roster is built (so creation
    order does not trip the posture gate), the letter is issued, and then the
    clock advances past the due date to trigger the overdue recompute.
    """
    ctx = setup_exam_with_items(
        num_items=num_items,
        item_due_date=item_due_date,
        clock_start="2026-07-01T00:00:00Z",
        **kwargs,
    )
    if issue_letter:
        ctx["exam"] = issue_first_day_letter(ctx["exam"]["id"])
    set_logical_clock(clock_after)
    ctx["exam"] = get_exam(ctx["exam"]["id"])
    return ctx


def setup_closed_issue_for_repeat_lineage(
    agency_id: str,
    issue_ref: str,
    officer_id: str,
    reviewer_id: str,
) -> dict:
    """A fully closed issue on a PRIOR examination of the given agency — the
    lineage anchor for repeat-finding detection (PRD §3.5).

    Uses a January examination window so it cannot overlap the primary exam's
    window, and reuses already-registered officer/reviewer identities.
    Returns the closed issue.
    """
    exam = create_examination(
        agency_id,
        scheduled_start_date="2026-01-05T00:00:00Z",
        scheduled_end_date="2026-01-10T00:00:00Z",
    )
    item = create_first_day_item(exam["id"], due_date="2026-01-12T00:00:00Z")
    issue_first_day_letter(exam["id"])
    waive_item(item["id"])
    begin_fieldwork(exam["id"])
    meeting = create_meeting(exam["id"], meeting_date="2026-01-07T10:00:00Z")
    finalize_meeting(meeting["id"])
    deliver_findings(exam["id"])
    issue = file_issue(exam["id"], issue_ref=issue_ref)
    open_remediation(exam["id"])

    owner_headers = make_remediation_owner_headers(officer_id)
    reviewer_headers = make_compliance_reviewer_headers(reviewer_id)
    bundle = create_plan_with_milestone(issue["id"], owner_headers)
    ctx = {"owner_headers": owner_headers, "reviewer_headers": reviewer_headers}
    drive_plan_to_status(bundle["plan"]["id"], "ACTIVE", ctx)
    get_success_data(api_client.start_remediation_milestone(
        bundle["milestone"]["id"], owner_headers))
    get_success_data(api_client.complete_remediation_milestone(
        bundle["milestone"]["id"], owner_headers))
    evidence = get_success_data(
        api_client.create_validation_evidence(
            issue["id"],
            create_validation_evidence_payload(submitted_by_user_id=officer_id),
            owner_headers),
        201)
    get_success_data(api_client.mark_evidence_sufficient(evidence["id"], reviewer_headers))
    closure = get_success_data(
        api_client.submit_issue_validation(
            issue["id"], create_submit_validation_payload(evidence["id"]), owner_headers),
        201)
    issue_v = get_issue(issue["id"])["version"]
    get_success_data(api_client.approve_closure_request(
        closure["id"], {"expected_issue_version": issue_v}, reviewer_headers))
    closed = get_issue(issue["id"])
    # PRD §3.5 requires the prior closure's closed_at to fall STRICTLY BEFORE
    # the new issue's created_at, and PRD §2.5 freezes the logical clock until
    # an operator advances it — so the lineage is only "prior" once the clock
    # moves past the closure instant.
    set_logical_clock("2026-08-02T00:00:00Z")
    return closed
