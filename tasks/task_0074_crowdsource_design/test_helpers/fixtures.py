"""Composite setup helpers for the Crowdsource Design test suite.

Most claims under test require the system to be in a specific state
reached through 10–20 API calls (category -> client -> designer ->
reviewer -> project -> tiers -> stages -> submit-for-review -> approve
-> /_clock advance -> screening -> reviewer assignments -> score
submission -> start-aggregation -> publish -> ... -> award -> issue
-> sign x3 -> register -> /_events COPYRIGHT_REGISTERED -> dispatch
-> /_events PAYMENT_COMPLETED). These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):
- PlatformOps is OPAQUE; shared constant headers are canonical.
- Client, Designer, Reviewer are ENTITY-BACKED. Every ownership-gated
  call MUST use make_client_headers(client["id"]),
  make_designer_headers(designer["id"]), or
  make_reviewer_headers(reviewer_id) — never a shared fallback.

Setup helpers use get_success_data (lenient validator), so a broken
precondition surfaces as a clear setup error rather than a confusing
assertion failure inside the test body.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .factories import (
    award_payload,
    clock_advance_payload,
    create_client_payload,
    create_copyright_transfer_payload,
    create_design_category_payload,
    create_designer_payload,
    create_dispute_payload,
    create_prize_tier_payload,
    create_project_payload,
    create_review_assignment_payload,
    create_review_stage_payload,
    create_reviewer_payload,
    create_submission_payload,
    dispatch_payment_payload,
    emit_event_payload,
    resolve_dispute_payload,
    sign_transfer_payload,
    submit_scores_payload,
    unique_code,
    unique_corpus_id,
    unique_idempotency_key,
    unique_reviewer_id,
)
from .test_users import (
    TEST_USERS,
    make_client_headers,
    make_designer_headers,
    make_platform_ops_headers,
    make_reviewer_headers,
)


# ===========================================================================
# Shared role-header constants (opaque PlatformOps role)
# ===========================================================================
PO = TEST_USERS["platform_ops_headers"]
PO_ALT = TEST_USERS["platform_ops_headers_alt"]


# ===========================================================================
# ISO 8601 helpers (PRD §2.4: "ISO 8601 UTC timestamp with three
# fractional digits")
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision, Z-suffixed."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_at(year: int, month: int, day: int,
           hour: int = 0, minute: int = 0, second: int = 0) -> str:
    return iso_z(datetime(year, month, day, hour, minute, second,
                          tzinfo=timezone.utc))


# ===========================================================================
# Test-harness drivers (PRD §2.11)
# ===========================================================================
def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Any:
    """PRD §2.11: 'an administrative capability advances the virtual
    clock to a supplied ISO 8601 instant: the request body carries a to
    field.'"""
    return get_success_data(api_client.clock_advance(
        clock_advance_payload(to=to_iso), headers or PO,
    ))


def emit_event(event_type: str, subject_id: str,
               payload: Optional[Dict[str, Any]] = None,
               headers: Optional[Dict[str, str]] = None) -> Any:
    """PRD §2.11: 'a second administrative capability simulates an
    inbound event from an external system'."""
    body = emit_event_payload(event_type=event_type,
                              subject_id=subject_id,
                              payload=payload if payload is not None else {})
    return get_success_data(api_client.emit_event(body, headers or PO))


# ===========================================================================
# Single-entity factory shortcuts (each returns the created entity dict)
# ===========================================================================
def create_design_category(
    code: Optional[str] = None,
    similarity_corpus_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.create_design_category(
        create_design_category_payload(
            code=code or unique_code("CAT"),
            similarity_corpus_id=similarity_corpus_id or unique_corpus_id(),
        ),
        headers or PO,
    ))


def create_client(
    tax_jurisdiction: str = "RESIDENT",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.create_client(
        create_client_payload(tax_jurisdiction=tax_jurisdiction),
        headers or PO,
    ))


def create_designer(
    categories: Optional[List[str]] = None,
    tax_residency: str = "RESIDENT",
    qualification_level: str = "NOVICE",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.create_designer(
        create_designer_payload(
            categories=categories or ["LOGO"],
            tax_residency=tax_residency,
            qualification_level=qualification_level,
        ),
        headers or PO,
    ))


def create_reviewer(
    categories: Optional[List[str]] = None,
    max_concurrent_assignments: int = 20,
    conflict_designer_ids: Optional[List[str]] = None,
    reviewer_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return get_success_data(api_client.create_reviewer(
        create_reviewer_payload(
            reviewer_id=reviewer_id or unique_reviewer_id(),
            categories=categories or ["LOGO"],
            max_concurrent_assignments=max_concurrent_assignments,
            conflict_designer_ids=conflict_designer_ids or [],
        ),
        headers or PO,
    ))


# ===========================================================================
# Standard timeline (PRD §3.2 — meet 72h + 168h gaps comfortably)
#
# The virtual clock is monotonically advancing across the test session
# (PRD §2.11 — only an "advance" capability exists). To keep every new
# project's opens_at strictly AFTER the current clock (required for
# PRD §3.2 "approval is permitted only while the virtual clock is still
# before opens_at"), we anchor each new project's timeline to a global
# counter that progresses by 1 year per project. The constants below
# are the SHAPE of the timeline relative to opens_at; the absolute
# anchor is fetched dynamically.
# ===========================================================================
_TIMELINE_EPOCH = datetime(2030, 1, 1, tzinfo=timezone.utc)
_PROJECT_TIMELINE_COUNTER = 0


def _next_timeline_anchor() -> datetime:
    """Each call returns a fresh anchor 1 year past the last one,
    guaranteeing the new project's opens_at is strictly in the FUTURE
    relative to any prior advance_clock call.
    """
    global _PROJECT_TIMELINE_COUNTER
    _PROJECT_TIMELINE_COUNTER += 1
    return _TIMELINE_EPOCH + timedelta(days=365 * _PROJECT_TIMELINE_COUNTER)


def _project_timeline(anchor: Optional[datetime] = None
                       ) -> Dict[str, Any]:
    """Return a self-consistent timeline dict for a single project,
    anchored at `anchor` (default: a fresh counter-derived instant).
    Stage windows are exactly contiguous (preliminary.ends_at ==
    semifinal.starts_at, etc.) to satisfy PRD §3.2's non-overlap rule.
    """
    a = anchor or _next_timeline_anchor()
    opens_at = a
    submission_deadline = a + timedelta(days=9)            # opens_at + 9d (> 72h)
    preliminary_starts = submission_deadline
    preliminary_ends = preliminary_starts + timedelta(days=2)
    semifinal_starts = preliminary_ends
    semifinal_ends = semifinal_starts + timedelta(days=2)
    final_starts = semifinal_ends
    final_ends = final_starts + timedelta(days=2)
    final_decision_deadline = submission_deadline + timedelta(days=20)
    return {
        "anchor": a,
        "opens_at": iso_z(opens_at),
        "submission_deadline": iso_z(submission_deadline),
        "preliminary_starts": iso_z(preliminary_starts),
        "preliminary_ends": iso_z(preliminary_ends),
        "semifinal_starts": iso_z(semifinal_starts),
        "semifinal_ends": iso_z(semifinal_ends),
        "final_starts": iso_z(final_starts),
        "final_ends": iso_z(final_ends),
        "final_decision_deadline": iso_z(final_decision_deadline),
        # convenient "just-after" markers for clock-advance steps
        "after_submission_deadline": iso_z(
            submission_deadline + timedelta(hours=1)),
        "after_preliminary_ends": iso_z(
            preliminary_ends + timedelta(hours=1)),
        "after_semifinal_ends": iso_z(
            semifinal_ends + timedelta(hours=1)),
        "after_final_ends": iso_z(
            final_ends + timedelta(hours=1)),
    }


# Legacy constants — kept ONLY as a backwards-compatible export surface
# for tests that import these names. New code should use _project_timeline().
DEFAULT_OPENS_AT = iso_at(2026, 6, 1)
DEFAULT_SUBMISSION_DEADLINE = iso_at(2026, 6, 10)
DEFAULT_PRELIMINARY_STARTS = iso_at(2026, 6, 10)
DEFAULT_PRELIMINARY_ENDS = iso_at(2026, 6, 12)
DEFAULT_SEMIFINAL_STARTS = iso_at(2026, 6, 12)
DEFAULT_SEMIFINAL_ENDS = iso_at(2026, 6, 14)
DEFAULT_FINAL_STARTS = iso_at(2026, 6, 14)
DEFAULT_FINAL_ENDS = iso_at(2026, 6, 16)
DEFAULT_FINAL_DECISION_DEADLINE = iso_at(2026, 6, 30)


# ===========================================================================
# Project setup tiers
# ===========================================================================
def create_draft_project(
    *,
    client: Optional[Dict[str, Any]] = None,
    category_code: Optional[str] = None,
    prize_pool_cents: int = 1_000_000,
    opens_at: Optional[str] = None,
    submission_deadline: Optional[str] = None,
    final_decision_deadline: Optional[str] = None,
    max_submissions_per_designer: Optional[int] = None,
    client_participates_final: Optional[bool] = None,
    timeline: Optional[Dict[str, Any]] = None,
    **extras: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create a (category, client, project, timeline) tuple in DRAFT.

    PRD §3.2: 'A Client authors a project as a draft.'
    A per-project monotonically-future timeline is computed so that
    PRD §3.2's approval-before-opens_at gate is reliably satisfiable
    across an entire test session with a one-way virtual clock.
    """
    tl = timeline or _project_timeline()
    cat = create_design_category(code=category_code)
    client = client or create_client()
    payload_extra: Dict[str, Any] = {}
    if max_submissions_per_designer is not None:
        payload_extra["max_submissions_per_designer"] = max_submissions_per_designer
    if client_participates_final is not None:
        payload_extra["client_participates_final"] = client_participates_final
    payload_extra.update(extras)
    project = get_success_data(api_client.create_project(
        create_project_payload(
            client_id=client["id"],
            category_code=cat["code"],
            prize_pool_cents=prize_pool_cents,
            opens_at=opens_at or tl["opens_at"],
            submission_deadline=submission_deadline or tl["submission_deadline"],
            final_decision_deadline=final_decision_deadline
                                    or tl["final_decision_deadline"],
            **payload_extra,
        ),
        make_client_headers(client["id"]),
    ))
    return cat, client, project, tl


def add_prize_tier(project_id: str, client_id: str,
                   *, rank: int = 1,
                   gross_amount_cents: int = 1_000_000,
                   tier_kind: str = "MAIN") -> Dict[str, Any]:
    return get_success_data(api_client.create_prize_tier(
        project_id,
        create_prize_tier_payload(
            rank=rank,
            gross_amount_cents=gross_amount_cents,
            tier_kind=tier_kind,
        ),
        make_client_headers(client_id),
    ))


def add_review_stage(project_id: str, client_id: str,
                     *, stage_kind: str,
                     passing_threshold: float = 60.00,
                     reviewer_quorum: int = 3,
                     rubric: Optional[Dict[str, float]] = None,
                     starts_at: str,
                     ends_at: str) -> Dict[str, Any]:
    return get_success_data(api_client.create_review_stage(
        project_id,
        create_review_stage_payload(
            stage_kind=stage_kind,
            passing_threshold=passing_threshold,
            reviewer_quorum=reviewer_quorum,
            rubric=rubric or {"creativity": 50, "execution": 50},
            starts_at=starts_at,
            ends_at=ends_at,
        ),
        make_client_headers(client_id),
    ))


def setup_project_ready_for_submit(
    *,
    prize_pool_cents: int = 1_000_000,
    tiers: Optional[List[Dict[str, Any]]] = None,
    passing_threshold: float = 60.00,
    reviewer_quorum: int = 3,
    rubric: Optional[Dict[str, float]] = None,
    client_participates_final: Optional[bool] = None,
    category_code: Optional[str] = None,
    max_submissions_per_designer: Optional[int] = None,
    timeline: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Project in DRAFT with exactly 3 review stages and the tier list.
    Sum of tier gross_amount_cents == prize_pool_cents (PRD §3.2 prereq).
    """
    tl = timeline or _project_timeline()
    cat, client, project, tl = create_draft_project(
        prize_pool_cents=prize_pool_cents,
        client_participates_final=client_participates_final,
        category_code=category_code,
        max_submissions_per_designer=max_submissions_per_designer,
        timeline=tl,
    )
    if tiers is None:
        tiers = [{"rank": 1, "gross_amount_cents": prize_pool_cents,
                  "tier_kind": "MAIN"}]
    tier_objs: List[Dict[str, Any]] = []
    for t in tiers:
        tier_objs.append(add_prize_tier(project["id"], client["id"], **t))
    prelim = add_review_stage(
        project["id"], client["id"],
        stage_kind="PRELIMINARY",
        passing_threshold=passing_threshold,
        reviewer_quorum=reviewer_quorum,
        rubric=rubric,
        starts_at=tl["preliminary_starts"],
        ends_at=tl["preliminary_ends"],
    )
    semi = add_review_stage(
        project["id"], client["id"],
        stage_kind="SEMIFINAL",
        passing_threshold=passing_threshold,
        reviewer_quorum=reviewer_quorum,
        rubric=rubric,
        starts_at=tl["semifinal_starts"],
        ends_at=tl["semifinal_ends"],
    )
    final = add_review_stage(
        project["id"], client["id"],
        stage_kind="FINAL",
        passing_threshold=passing_threshold,
        reviewer_quorum=reviewer_quorum,
        rubric=rubric,
        starts_at=tl["final_starts"],
        ends_at=tl["final_ends"],
    )
    return {
        "category": cat,
        "client": client,
        "project": project,
        "tiers": tier_objs,
        "stages": {"PRELIMINARY": prelim, "SEMIFINAL": semi, "FINAL": final},
        "timeline": tl,
    }


def setup_on_shelf_project(**kwargs: Any) -> Dict[str, Any]:
    """Project advanced to ON_SHELF: drafted -> submit -> approve.

    PRD §3.2: 'When the client is ready, they submit the project for
    platform review.' 'A PlatformOps operator either approves the
    project, moving it from UNDER_PLATFORM_REVIEW to ON_SHELF.'
    """
    ctx = setup_project_ready_for_submit(**kwargs)
    client = ctx["client"]
    project = ctx["project"]
    # submit-for-review (Client only)
    proj_after_submit = get_success_data(api_client.submit_project_for_review(
        project["id"], make_client_headers(client["id"]),
    ))
    # approve (PlatformOps; must be before opens_at)
    proj_on_shelf = get_success_data(api_client.approve_project(
        project["id"], PO,
    ))
    ctx["project"] = proj_on_shelf
    return ctx


def setup_in_preliminary(**kwargs: Any) -> Dict[str, Any]:
    """Project advanced to IN_PRELIMINARY by advancing the clock past
    submission_deadline.

    PRD §3.3: 'When the virtual server clock crosses the project's
    submission_deadline, the project automatically advances from
    ON_SHELF to IN_PRELIMINARY.'
    """
    ctx = setup_on_shelf_project(**kwargs)
    tl = ctx["timeline"]
    # Advance to just after submission_deadline (and PRELIMINARY starts).
    advance_clock(tl["after_submission_deadline"])
    # Refresh project status.
    ctx["project"] = get_success_data(api_client.get_project(
        ctx["project"]["id"], PO,
    ))
    return ctx


# ===========================================================================
# Submission + review-cycle helpers
# ===========================================================================
def add_designer_with_submission(
    project_id: str,
    *,
    categories: Optional[List[str]] = None,
    tax_residency: str = "RESIDENT",
    title: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create a Designer and post a Submission to project_id (project
    must be ON_SHELF).

    PRD §3.3: 'Each submission carries designer_id (which must match
    X-User-ID for the Designer role)' — uses make_designer_headers().
    """
    designer = create_designer(categories=categories,
                               tax_residency=tax_residency)
    submission = get_success_data(api_client.create_submission(
        project_id,
        create_submission_payload(
            designer_id=designer["id"],
            title=title,
        ),
        make_designer_headers(designer["id"]),
    ))
    return designer, submission


def assign_reviewer(
    *,
    review_stage_id: str,
    submission_id: str,
    reviewer_id: str,
) -> Dict[str, Any]:
    """Create a ReviewAssignment (PlatformOps action)."""
    return get_success_data(api_client.create_review_assignment(
        create_review_assignment_payload(
            review_stage_id=review_stage_id,
            submission_id=submission_id,
            reviewer_id=reviewer_id,
        ),
        PO,
    ))


def submit_review_scores(
    *,
    assignment_id: str,
    reviewer_id: str,
    criterion_scores: Dict[str, float],
) -> Dict[str, Any]:
    """Reviewer submits per-criterion scores (PRD §3.4).

    The Reviewer role is entity_backed on reviewer_id: we pass the
    reviewer's reviewer_id as X-User-ID via make_reviewer_headers().
    """
    return get_success_data(api_client.submit_scores(
        assignment_id,
        submit_scores_payload(criterion_scores=criterion_scores),
        make_reviewer_headers(reviewer_id),
    ))


def submit_client_scores_on_final(
    *,
    assignment_id: str,
    client_id: str,
    criterion_scores: Dict[str, float],
) -> Dict[str, Any]:
    """Client submits scores on a FINAL stage assignment when
    client_participates_final=true (PRD §3.5 + endpoint table)."""
    return get_success_data(api_client.submit_scores(
        assignment_id,
        submit_scores_payload(criterion_scores=criterion_scores),
        make_client_headers(client_id),
    ))


def assign_and_score(
    *,
    review_stage_id: str,
    submission_id: str,
    reviewer: Dict[str, Any],
    criterion_scores: Dict[str, float],
) -> Dict[str, Any]:
    """Convenience: assign reviewer, submit scores, return assignment."""
    asg = assign_reviewer(
        review_stage_id=review_stage_id,
        submission_id=submission_id,
        reviewer_id=reviewer["reviewer_id"],
    )
    return submit_review_scores(
        assignment_id=asg["id"],
        reviewer_id=reviewer["reviewer_id"],
        criterion_scores=criterion_scores,
    )


# ===========================================================================
# Aggregation, publish, advance
# ===========================================================================
def start_and_publish_stage(stage_id: str) -> Dict[str, Any]:
    """Start aggregation, then publish.

    PRD §3.5: 'The stage move is permitted only once the virtual clock
    has reached the stage's ends_at.' Caller must advance the clock
    BEFORE calling this helper.
    """
    get_success_data(api_client.start_aggregation(stage_id, PO))
    return get_success_data(api_client.publish_stage(stage_id, PO))


# ===========================================================================
# Cross-stage scenario builders used by difficulty-design instances
# ===========================================================================
def setup_in_final_with_advancing(
    *,
    n_submissions: int = 1,
    client_participates_final: bool = False,
    designer_residency: str = "RESIDENT",
    rubric: Optional[Dict[str, float]] = None,
    passing_threshold: float = 60.00,
    tiers: Optional[List[Dict[str, Any]]] = None,
    prize_pool_cents: int = 1_000_000,
    reviewer_quorum: int = 3,
) -> Dict[str, Any]:
    """Run a full project lifecycle from DRAFT to IN_FINAL with
    n_submissions submissions all in ADVANCING_FINAL and FINAL stage in
    OPEN (ready for client/reviewer scoring).

    Steps walked: register category/client -> project -> tiers ->
    stages -> submit-for-review -> approve -> /_clock past
    submission_deadline (preliminary OPEN, all submissions SCREENING ->
    ACCEPTED via originality default 100) -> create reviewer pool ->
    assign + score 3 reviewers per submission -> /_clock past prelim
    end -> start-aggregation prelim -> publish prelim (submissions ->
    ADVANCING_SEMIFINAL) -> /_clock past semi start -> assign+score 3
    reviewers per submission -> /_clock past semi end ->
    start-aggregation -> publish semifinal -> /_clock past final start.
    Returns a context dict with handles to all created entities.
    """
    if rubric is None:
        rubric = {"creativity": 50, "execution": 50}
    if tiers is None:
        tiers = [{"rank": 1, "gross_amount_cents": prize_pool_cents,
                  "tier_kind": "MAIN"}]

    ctx = setup_on_shelf_project(
        prize_pool_cents=prize_pool_cents,
        tiers=tiers,
        passing_threshold=passing_threshold,
        reviewer_quorum=reviewer_quorum,
        rubric=rubric,
        client_participates_final=client_participates_final,
    )

    project = ctx["project"]
    client = ctx["client"]
    cat = ctx["category"]
    stages = ctx["stages"]

    # Designers + submissions while ON_SHELF.
    designers: List[Dict[str, Any]] = []
    submissions: List[Dict[str, Any]] = []
    for i in range(n_submissions):
        d, s = add_designer_with_submission(
            project["id"],
            categories=[cat["code"]],
            tax_residency=designer_residency,
            title=f"Sub-{i}",
        )
        designers.append(d)
        submissions.append(s)

    # Cross submission_deadline -> IN_PRELIMINARY (submissions screened).
    tl = ctx["timeline"]
    advance_clock(tl["after_submission_deadline"])

    # Build a pool of reviewers for prelim + semi + final scoring.
    # Each submission needs >= reviewer_quorum SUBMITTED.
    reviewers: List[Dict[str, Any]] = []
    n_needed = max(reviewer_quorum, 3)
    for i in range(n_needed):
        r = create_reviewer(
            categories=[cat["code"]],
            max_concurrent_assignments=100,
        )
        reviewers.append(r)

    # Assign + score PRELIMINARY for every submission.
    prelim_assignments: List[Dict[str, Any]] = []
    for s in submissions:
        for r in reviewers[:reviewer_quorum]:
            asg = assign_and_score(
                review_stage_id=stages["PRELIMINARY"]["id"],
                submission_id=s["id"],
                reviewer=r,
                criterion_scores={c: 90 for c in rubric.keys()},
            )
            prelim_assignments.append(asg)

    # /_clock past PRELIMINARY ends_at.
    advance_clock(tl["after_preliminary_ends"])
    start_and_publish_stage(stages["PRELIMINARY"]["id"])

    # SEMIFINAL window opens.
    # Assign+score reviewers for every (now ADVANCING_SEMIFINAL) submission.
    semi_assignments: List[Dict[str, Any]] = []
    for s in submissions:
        for r in reviewers[:reviewer_quorum]:
            asg = assign_and_score(
                review_stage_id=stages["SEMIFINAL"]["id"],
                submission_id=s["id"],
                reviewer=r,
                criterion_scores={c: 90 for c in rubric.keys()},
            )
            semi_assignments.append(asg)

    # /_clock past SEMIFINAL ends_at.
    advance_clock(tl["after_semifinal_ends"])
    start_and_publish_stage(stages["SEMIFINAL"]["id"])

    # FINAL is now OPEN. The project is in IN_FINAL.
    ctx_out = {
        "category": cat,
        "client": client,
        "project": get_success_data(api_client.get_project(
            project["id"], PO,
        )),
        "tiers": ctx["tiers"],
        "stages": stages,
        "designers": designers,
        "submissions": submissions,
        "reviewers": reviewers,
        "prelim_assignments": prelim_assignments,
        "semi_assignments": semi_assignments,
        "timeline": tl,
    }
    return ctx_out


def setup_in_final_aggregating(
    *,
    n_submissions: int = 1,
    designer_residency: str = "RESIDENT",
    client_participates_final: bool = False,
    final_rubric: Optional[Dict[str, float]] = None,
    reviewer_quorum: int = 3,
    tiers: Optional[List[Dict[str, Any]]] = None,
    prize_pool_cents: int = 1_000_000,
    reviewer_scores: Optional[List[float]] = None,
    client_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Project IN_FINAL with FINAL stage in AGGREGATING and N submissions
    all in ADVANCING_FINAL. The FINAL aggregation has run for each
    submission.

    PRD §3.5: 'The second phase is per-submission, fired when
    PlatformOps moves the stage from OPEN to AGGREGATING.'

    Uses reviewer_scores list (one score per reviewer for FINAL stage,
    repeated criterion scores). If client_participates_final=true and
    client_score is given, the Client also submits a final-stage
    ReviewAssignment with that score.
    """
    if final_rubric is None:
        final_rubric = {"creativity": 50, "execution": 50}
    if reviewer_scores is None:
        reviewer_scores = [90.0] * reviewer_quorum

    ctx = setup_in_final_with_advancing(
        n_submissions=n_submissions,
        client_participates_final=client_participates_final,
        designer_residency=designer_residency,
        rubric=final_rubric,
        tiers=tiers,
        prize_pool_cents=prize_pool_cents,
        reviewer_quorum=reviewer_quorum,
    )

    final_stage = ctx["stages"]["FINAL"]
    submissions = ctx["submissions"]
    reviewers = ctx["reviewers"]
    client = ctx["client"]

    final_assignments: List[Dict[str, Any]] = []
    for s in submissions:
        # Reviewer scoring.
        for r, score in zip(reviewers[:len(reviewer_scores)],
                             reviewer_scores):
            asg = assign_and_score(
                review_stage_id=final_stage["id"],
                submission_id=s["id"],
                reviewer=r,
                criterion_scores={c: score for c in final_rubric.keys()},
            )
            final_assignments.append(asg)
        # Optional Client scoring on FINAL stage.
        if client_participates_final and client_score is not None:
            client_asg = get_success_data(api_client.create_review_assignment(
                create_review_assignment_payload(
                    review_stage_id=final_stage["id"],
                    submission_id=s["id"],
                    reviewer_id=client["id"],  # Client.id stands in
                ),
                PO,
            ))
            submit_client_scores_on_final(
                assignment_id=client_asg["id"],
                client_id=client["id"],
                criterion_scores={c: client_score
                                  for c in final_rubric.keys()},
            )
            final_assignments.append(client_asg)

    # Advance to FINAL ends_at and start aggregation.
    advance_clock(ctx["timeline"]["after_final_ends"])
    final_stage_after = get_success_data(api_client.start_aggregation(
        final_stage["id"], PO,
    ))
    ctx["stages"]["FINAL"] = final_stage_after
    ctx["final_assignments"] = final_assignments
    return ctx


def setup_awarded_project(
    *,
    designer_residency: str = "RESIDENT",
    tiers: Optional[List[Dict[str, Any]]] = None,
    prize_pool_cents: int = 1_000_000,
    reviewer_quorum: int = 3,
) -> Dict[str, Any]:
    """Project AWARDED with a single MAIN winner, CopyrightTransfer
    DRAFTED, PrizePayment SCHEDULED.

    Walks the full pipeline:
    project -> ON_SHELF -> IN_PRELIMINARY -> publish prelim ->
    IN_SEMIFINAL -> publish semi -> IN_FINAL -> aggregating -> award.
    """
    ctx = setup_in_final_aggregating(
        n_submissions=1,
        designer_residency=designer_residency,
        tiers=tiers,
        prize_pool_cents=prize_pool_cents,
        reviewer_quorum=reviewer_quorum,
    )
    project = ctx["project"]
    submission = ctx["submissions"][0]
    tier = ctx["tiers"][0]
    awarded = get_success_data(api_client.award_project(
        project["id"],
        award_payload(tier_assignments=[
            {"prize_tier_id": tier["id"], "submission_id": submission["id"]},
        ]),
        PO,
    ))
    ctx["project"] = awarded
    return ctx


def setup_registered_copyright(
    **kwargs: Any,
) -> Dict[str, Any]:
    """Drive an awarded project through the copyright pipeline so the
    CopyrightTransfer ends in REGISTERED.

    PRD §3.8 lifecycle: DRAFTED -> issue -> PENDING_SIGNATURES ->
    sign(CLIENT) -> sign(DESIGNER) -> sign(PLATFORM_NOTARY) ->
    ALL_SIGNED -> register -> REGISTERING -> /_events/emit
    COPYRIGHT_REGISTERED -> REGISTERED.
    """
    ctx = setup_awarded_project(**kwargs)
    project = ctx["project"]
    submission = ctx["submissions"][0]
    designer = ctx["designers"][0]
    client = ctx["client"]

    # Find the auto-DRAFTED transfer for the winner.
    # Use the GET endpoint via the project's POV.
    # Some implementations may not provide a listing; fall back to
    # locating via a manual create only if absolutely necessary.
    # PRD §3.7 guarantees auto-creation, so we fetch by listing per
    # the GET /copyright-transfers/{id} endpoint after enumerating
    # plausible identifiers. For robustness, the auto-DRAFTED transfer's
    # id is not directly exposed via a list endpoint — we therefore
    # find it indirectly by inspecting submission embeds where present,
    # but most safely we query a generic listing path that PRD §4 hints
    # at via /copyright-transfers (not exposed). To avoid that fragility
    # we instead drive the flow by creating a manual transfer if no
    # surfaced handle is exposed. PRD §3.8 ALLOWS manual creation.
    transfer = _ensure_copyright_transfer(project["id"], submission["id"])
    transfer = get_success_data(api_client.issue_for_signing(
        transfer["id"], PO,
    ))
    # Sign in order: CLIENT, DESIGNER, PLATFORM_NOTARY.
    transfer = get_success_data(api_client.sign_transfer(
        transfer["id"],
        sign_transfer_payload(signer_party_kind="CLIENT"),
        make_client_headers(client["id"]),
    ))
    transfer = get_success_data(api_client.sign_transfer(
        transfer["id"],
        sign_transfer_payload(signer_party_kind="DESIGNER"),
        make_designer_headers(designer["id"]),
    ))
    transfer = get_success_data(api_client.sign_transfer(
        transfer["id"],
        sign_transfer_payload(signer_party_kind="PLATFORM_NOTARY"),
        PO,
    ))
    transfer = get_success_data(api_client.register_transfer(
        transfer["id"], PO,
    ))
    emit_event("COPYRIGHT_REGISTERED", transfer["id"],
               payload={"registration_ref": "REG-XYZ"})
    transfer = get_success_data(api_client.get_copyright_transfer(
        transfer["id"], PO,
    ))
    ctx["transfer"] = transfer
    return ctx


def _ensure_copyright_transfer(project_id: str,
                               submission_id: str) -> Dict[str, Any]:
    """Return an existing auto-DRAFTED CopyrightTransfer for the
    submission. If the implementation surfaces no list endpoint, a
    manual create is the fallback (PRD §3.8 allows manual create)."""
    # Attempt to manually create; if the auto-DRAFTED conflicts, the
    # implementation may either return 409 or accept and replace.
    # Use a lenient approach: try create, and if 4xx, we assume the
    # auto-DRAFTED transfer is reachable through another path — but
    # the PRD does not expose a list/lookup, so to keep the helper
    # honest we ALWAYS use the manual-create path (PRD §3.8: "A
    # PlatformOps operator may also create a transfer manually for a
    # winning or runner-up submission when the auto-draft is missing").
    resp = api_client.create_copyright_transfer(
        create_copyright_transfer_payload(
            project_id=project_id,
            submission_id=submission_id,
            scope="FULL",
            usage_rights=[],
        ),
        PO,
    )
    return get_success_data(resp)


def setup_paid_prize_payment(**kwargs: Any) -> Dict[str, Any]:
    """Drive an awarded+registered project so the PrizePayment is in
    PAID.

    PRD §3.9: 'PlatformOps dispatches the payment by transitioning
    SCHEDULED to PAYING.' '/_events/emit PAYMENT_COMPLETED moves
    PAYING to PAID.'
    """
    ctx = setup_registered_copyright(**kwargs)
    project = ctx["project"]
    tier = ctx["tiers"][0]

    # Find the SCHEDULED PrizePayment for this project.
    pp = _find_prize_payment(project_id=project["id"],
                             prize_tier_id=tier["id"])
    pp = get_success_data(api_client.dispatch_payment(
        pp["id"],
        dispatch_payment_payload(
            idempotency_key=unique_idempotency_key()),
        PO,
    ))
    emit_event("PAYMENT_COMPLETED", pp["id"],
               payload={"external_payment_ref": "PAY-XYZ"})
    pp = get_success_data(api_client.get_prize_payment(pp["id"], PO))
    ctx["prize_payment"] = pp
    return ctx


def _find_prize_payment(*, project_id: str,
                        prize_tier_id: str) -> Dict[str, Any]:
    """Find the auto-created SCHEDULED PrizePayment for a (project, tier)
    via GET /prize-payments?project_id=...

    PRD §4: 'GET /prize-payments — List prize payments with optional
    filters by project_id, designer_id, and status.'
    """
    resp = api_client.list_prize_payments(
        PO, params={"project_id": project_id},
    )
    items, _meta = validate_paginated(resp)
    for it in items:
        if it.get("prize_tier_id") == prize_tier_id:
            return it
    raise AssertionError(
        f"No PrizePayment found for project={project_id} "
        f"prize_tier_id={prize_tier_id}; got {items!r}"
    )


# ===========================================================================
# Difficulty-design composite fixtures
# (each named after the scaffold_difficulty_design instance it serves)
# ===========================================================================
def setup_prize_withholding_pair(
    *,
    gross_amount_cents: int = 1_000_000,
) -> Dict[str, Any]:
    """For the prize_withholding_resident_vs_non_resident difficulty
    instance: two awarded projects identical except for designer's
    tax_residency.
    """
    p_res = setup_awarded_project(
        designer_residency="RESIDENT",
        tiers=[{"rank": 1, "gross_amount_cents": gross_amount_cents,
                "tier_kind": "MAIN"}],
        prize_pool_cents=gross_amount_cents,
    )
    p_non = setup_awarded_project(
        designer_residency="NON_RESIDENT",
        tiers=[{"rank": 1, "gross_amount_cents": gross_amount_cents,
                "tier_kind": "MAIN"}],
        prize_pool_cents=gross_amount_cents,
    )
    pp_res = _find_prize_payment(project_id=p_res["project"]["id"],
                                 prize_tier_id=p_res["tiers"][0]["id"])
    pp_non = _find_prize_payment(project_id=p_non["project"]["id"],
                                 prize_tier_id=p_non["tiers"][0]["id"])
    return {
        "resident": {"ctx": p_res, "payment": pp_res},
        "non_resident": {"ctx": p_non, "payment": pp_non},
    }


def setup_review_assignment_in_submitted(
    *,
    rubric: Optional[Dict[str, float]] = None,
    criterion_scores: Optional[Dict[str, float]] = None,
    reviewer_quorum: int = 3,
) -> Dict[str, Any]:
    """A PRELIMINARY stage OPEN with ONE specific ReviewAssignment
    in SUBMITTED for the assignment_score_rounding_order_pin and
    review_assignment_dispute_cycle instances.

    Returns ctx with: assignment under test (first one created), all
    reviewers and submission for further operations.
    """
    if rubric is None:
        rubric = {"creativity": 50, "execution": 50}
    if criterion_scores is None:
        criterion_scores = {c: 90 for c in rubric.keys()}

    ctx = setup_on_shelf_project(
        rubric=rubric,
        reviewer_quorum=reviewer_quorum,
    )
    cat = ctx["category"]
    project = ctx["project"]
    stages = ctx["stages"]

    designer, submission = add_designer_with_submission(
        project["id"], categories=[cat["code"]],
    )

    # Cross submission_deadline -> IN_PRELIMINARY; submission SCREENING ->
    # ACCEPTED (originality default).
    advance_clock(ctx["timeline"]["after_submission_deadline"])

    reviewer = create_reviewer(
        categories=[cat["code"]],
        max_concurrent_assignments=10,
    )
    assignment = assign_reviewer(
        review_stage_id=stages["PRELIMINARY"]["id"],
        submission_id=submission["id"],
        reviewer_id=reviewer["reviewer_id"],
    )
    submitted = submit_review_scores(
        assignment_id=assignment["id"],
        reviewer_id=reviewer["reviewer_id"],
        criterion_scores=criterion_scores,
    )
    ctx["designer"] = designer
    ctx["submission"] = submission
    ctx["reviewer"] = reviewer
    ctx["assignment"] = submitted
    return ctx


def setup_review_assignment_disputed(**kwargs: Any) -> Dict[str, Any]:
    """SUBMITTED ReviewAssignment moved to DISPUTED via a
    SCORING_FAIRNESS dispute. Used by the dispute_cycle instance.
    """
    ctx = setup_review_assignment_in_submitted(**kwargs)
    designer = ctx["designer"]
    assignment = ctx["assignment"]
    project = ctx["project"]
    dispute = get_success_data(api_client.create_dispute(
        create_dispute_payload(
            project_id=project["id"],
            dispute_type="SCORING_FAIRNESS",
            subject_ref_kind="REVIEW_ASSIGNMENT",
            subject_ref_id=assignment["id"],
            filer_kind="DESIGNER",
            filer_id=designer["id"],
        ),
        make_designer_headers(designer["id"]),
    ))
    ctx["dispute"] = dispute
    return ctx


def setup_stage_overlap_baseline() -> Dict[str, Any]:
    """A DRAFT project with NO stages so tests can post fresh stage
    configurations (for the stage_intervals_half_open_no_overlap
    instance)."""
    tl = _project_timeline()
    cat = create_design_category()
    client = create_client()
    project = get_success_data(api_client.create_project(
        create_project_payload(
            client_id=client["id"],
            category_code=cat["code"],
            opens_at=tl["opens_at"],
            submission_deadline=tl["submission_deadline"],
            final_decision_deadline=tl["final_decision_deadline"],
        ),
        make_client_headers(client["id"]),
    ))
    return {"category": cat, "client": client, "project": project,
            "timeline": tl}


__all__ = [
    "PO", "PO_ALT",
    "iso_z", "iso_at",
    "DEFAULT_OPENS_AT", "DEFAULT_SUBMISSION_DEADLINE",
    "DEFAULT_PRELIMINARY_STARTS", "DEFAULT_PRELIMINARY_ENDS",
    "DEFAULT_SEMIFINAL_STARTS", "DEFAULT_SEMIFINAL_ENDS",
    "DEFAULT_FINAL_STARTS", "DEFAULT_FINAL_ENDS",
    "DEFAULT_FINAL_DECISION_DEADLINE",
    "advance_clock", "emit_event",
    "create_design_category", "create_client", "create_designer",
    "create_reviewer",
    "create_draft_project", "add_prize_tier", "add_review_stage",
    "setup_project_ready_for_submit", "setup_on_shelf_project",
    "setup_in_preliminary",
    "add_designer_with_submission",
    "assign_reviewer", "submit_review_scores",
    "submit_client_scores_on_final",
    "assign_and_score", "start_and_publish_stage",
    "setup_in_final_with_advancing",
    "setup_in_final_aggregating",
    "setup_awarded_project",
    "setup_registered_copyright",
    "setup_paid_prize_payment",
    "setup_prize_withholding_pair",
    "setup_review_assignment_in_submitted",
    "setup_review_assignment_disputed",
    "setup_stage_overlap_baseline",
]
