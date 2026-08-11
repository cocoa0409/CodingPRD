"""Complaints and adjudication (state machine, quality scoring, segregation of
duties) plus the compliance reporting snapshot metrics."""
from test_helpers import (
    api_client,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    make_org_requester_headers,
    set_clock,
    create_org,
    create_submitted_request,
    create_submitted_vri_request,
    create_draft_request,
    submit_request,
    get_interpreter,
    setup_confirmed_assignment,
    setup_completed_encounter,
    file_complaint,
    begin_review,
    adjudicate,
    file_and_adjudicate,
    assert_report,
)

ADMIN = TEST_USERS["platform_admin_headers"]
REVIEWER = TEST_USERS["quality_reviewer_headers"]
CLERK = TEST_USERS["billing_clerk_headers"]


# ─── Difficulty: dual_variant_calc / quality score split ─────────────

def _setup_substantiated_major_plus_filed_critical():
    """Completed assignment; C1 (MAJOR) adjudicated SUBSTANTIATED; C2 (CRITICAL)
    filed and left FILED."""
    ctx = setup_completed_encounter()
    file_and_adjudicate(ctx, "SUBSTANTIATED", category="QUALITY", severity="MAJOR",
                        narrative="Sign errors throughout")
    file_complaint(ctx, category="PROFESSIONALISM", severity="CRITICAL",
                   narrative="Interpreter left mid-encounter")
    return ctx


def test_quality_score_final_variant_counts_substantiated_only():
    """PRD §3.9: "The final `quality_score` is 100 minus the summed `penalty_points`
    of the interpreter's `SUBSTANTIATED` complaints, floored at zero." with
    "`penalty_points` is set by severity — five for `MINOR`, fifteen for `MAJOR`,
    thirty for `CRITICAL`". (One SUBSTANTIATED MAJOR: 100 - 15 = 85; the FILED
    CRITICAL stays out of the final variant.)

    Design: Difficulty/dual_variant_calc/quality_score_provisional_vs_final_diverge_on_pending_complaint
    """
    ctx = _setup_substantiated_major_plus_filed_critical()
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["quality_score"] == 85, (
        f"final variant counts SUBSTANTIATED only, got {interp['quality_score']}"
    )


def test_quality_score_provisional_variant_assumes_worst_on_pending():
    """PRD §3.9: "The `quality_score_provisional` runs the same arithmetic but also
    counts complaints still `FILED` or `UNDER_REVIEW`, assuming the worst on
    everything pending — so a single pending `CRITICAL` complaint splits the two
    scores by thirty points." (100 - 15 - 30 = 55 while the final score is 85.)

    Design: Difficulty/dual_variant_calc/quality_score_provisional_vs_final_diverge_on_pending_complaint
    """
    ctx = _setup_substantiated_major_plus_filed_critical()
    interp = get_interpreter(ctx["interpreter"]["id"])
    assert interp["quality_score_provisional"] == 55, (
        f"provisional variant includes the FILED CRITICAL, got {interp['quality_score_provisional']}"
    )
    assert interp["quality_score"] != interp["quality_score_provisional"]


# ─── Corner: complaint state machine + segregation of duties ─────────

def test_complaint_reopen_cycle_runs_once():
    """PRD §3.9: "the filing `OrgRequester` may reopen it, returning it from
    `DISMISSED` to `UNDER_REVIEW`, provided `reopen_count` is still zero — a second
    reopen is rejected with `ERR_COMPLAINT_ALREADY_REOPENED`, and reopening from any
    state other than `DISMISSED` draws `ERR_COMPLAINT_INVALID_STATE`. Reopening
    increments `reopen_count` and, because the complaint is pending again,
    recomputes both quality scores."

    Design: Corner/state_machines/complaint_reopen_cycle_runs_once
    """
    ctx = setup_completed_encounter()
    complaint = file_complaint(ctx, category="LATENESS", severity="MINOR",
                               narrative="Arrived 5 minutes late")
    begin_review(complaint["id"])
    dismissed = adjudicate(complaint["id"], "DISMISSED")
    assert dismissed["status"] == "DISMISSED"

    org_headers = make_org_requester_headers(ctx["org"]["id"])
    reopened = get_success_data(api_client.reopen_complaint(complaint["id"], org_headers))
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["reopen_count"] == 1

    dismissed2 = adjudicate(complaint["id"], "DISMISSED")
    assert dismissed2["status"] == "DISMISSED"
    resp = api_client.reopen_complaint(complaint["id"], org_headers)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_ALREADY_REOPENED)


def test_begin_review_twice_returns_complaint_invalid_state():
    """PRD §3.9: "Beginning review moves a `FILED` complaint to `UNDER_REVIEW` (from
    any other state, `ERR_COMPLAINT_INVALID_STATE`)."

    Design: Corner/errors/begin_review_twice_returns_complaint_invalid_state
    """
    ctx = setup_completed_encounter()
    complaint = file_complaint(ctx, category="QUALITY", severity="MINOR",
                               narrative="n")
    begin_review(complaint["id"])
    resp = api_client.begin_review(complaint["id"], REVIEWER)
    validate_error(resp, ApiErrorId.ERR_COMPLAINT_INVALID_STATE)
    data = get_success_data(api_client.get_complaint(complaint["id"], ADMIN))
    assert data["status"] == "UNDER_REVIEW"


def test_org_requester_cannot_adjudicate_complaint():
    """PRD §3.9: "Adjudication belongs to the `QualityReviewer`."
    PRD §2.1: "A request whose role is valid but not permitted for the target
    endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)." and "an
    `OrgRequester` files requests, disputes, and complaints but cannot settle them".

    Design: Corner/rbac/org_requester_cannot_adjudicate_complaint
    """
    ctx = setup_completed_encounter()
    complaint = file_complaint(ctx, category="QUALITY", severity="MAJOR",
                               narrative="n")
    begin_review(complaint["id"])
    resp = api_client.adjudicate_complaint(
        complaint["id"], {"outcome": "SUBSTANTIATED"},
        make_org_requester_headers(ctx["org"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)
    data = get_success_data(api_client.get_complaint(complaint["id"], ADMIN))
    assert data["status"] == "UNDER_REVIEW", "the filing org cannot settle its own complaint"


def test_quality_reviewer_cannot_file_complaint():
    """PRD §2.1: "a `QualityReviewer` adjudicates complaints and issues credits but
    cannot file complaints or settle invoices".
    PRD §2.10: "Third, role permission (`ERR_UNAUTHORIZED_ROLE`). ... Fifth,
    existence of every path- and body-referenced identifier, left to right" — the
    role tier fires before any body-referenced id is resolved.

    Design: Corner/rbac/quality_reviewer_cannot_file_complaint
    """
    set_clock("2026-05-01T00:00:00Z")
    resp = api_client.create_complaint(
        {"org_id": NON_EXISTENT_UUID, "assignment_id": NON_EXISTENT_UUID,
         "category": "QUALITY", "severity": "MINOR", "narrative": "n"},
        REVIEWER)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


# ─── Corner: reporting snapshots ─────────────────────────────────────

def test_report_window_half_open_and_metric_set():
    """PRD §3.9: "A `PlatformAdmin` generates a snapshot over a half-open window —
    `window_start` inclusive, `window_end` exclusive and strictly later — optionally
    scoped to one `org_id`". "The snapshot's request metrics count requests whose
    `scheduled_start` falls inside the window: `total_requests` overall;
    `filled_count` in `CONFIRMED`, `IN_PROGRESS`, `COMPLETED`, or `CLOSED`;
    `unfilled_count` in `UNFILLED`; and `cancelled_count` in `CANCELLED`. The
    `fulfillment_rate` divides filled by the difference of total minus cancelled,
    rounded half-up to four decimal places, and is 0.0 when that denominator is
    zero." and "Finally, `ada_context_mix` breaks the included requests into
    per-context counts for `MEDICAL`, `LEGAL`, `EDUCATION`, and `GENERAL`."
    (A request scheduled exactly at window_end is excluded.)

    Design: Corner/calculations/report_window_half_open_and_metric_set
    """
    # R1: CONFIRMED (June 10). R2: CANCELLED from MATCHING (June 12).
    ctx = setup_confirmed_assignment()
    org = ctx["org"]
    req2 = create_submitted_request(
        org["id"], consumer_name="Kim Consumer",
        scheduled_start="2026-06-12T14:00:00Z", scheduled_end="2026-06-12T15:00:00Z",
        estimated_mileage=5)
    get_success_data(api_client.cancel_request(
        req2["id"], make_org_requester_headers(org["id"])))
    # R3: MATCHING, scheduled exactly at the window end -> excluded (half-open).
    create_submitted_request(
        org["id"], consumer_name="Bo UnDee", modality="VRI", ada_context="GENERAL",
        scheduled_start="2026-07-01T00:00:00Z", scheduled_end="2026-07-01T01:00:00Z",
        onsite_address=None, estimated_mileage=0)

    report = get_success_data(api_client.generate_report(
        {"org_id": org["id"], "window_start": "2026-06-01T00:00:00Z",
         "window_end": "2026-07-01T00:00:00Z"}, ADMIN))
    assert_report(report)
    assert report["total_requests"] == 2, "the window-end request is excluded"
    assert report["filled_count"] == 1
    assert report["unfilled_count"] == 0
    assert report["cancelled_count"] == 1
    assert report["fulfillment_rate"] == 1.0, "1 / (2 - 1)"
    assert report["no_show_count"] == 0
    assert report["total_billed_cents"] == 0
    assert report["complaint_count"] == 0
    assert report["substantiated_count"] == 0
    assert report["ada_context_mix"] == {
        "MEDICAL": 2, "LEGAL": 0, "EDUCATION": 0, "GENERAL": 0}
    assert report["avg_response_minutes"] == 0.0, (
        "the single acceptance happened at the same logical instant as its offer"
    )


def test_report_generate_platform_wide():
    """PRD §3.9: "optionally scoped to one `org_id`, where a null org produces a
    platform-wide snapshot" and "The `fulfillment_rate` divides filled by the
    difference of total minus cancelled, rounded half-up to four decimal places, and
    is 0.0 when that denominator is zero."
    (Two orgs each contribute one in-window MATCHING request: filled 0 / (2 - 0) =
    0.0; the mix splits MEDICAL 1 / GENERAL 1.)

    Design: Corner/endpoints/report_generate_platform_wide
    """
    set_clock("2026-05-01T00:00:00Z")
    org_a = create_org(name="Metro Hospital", org_type="MEDICAL")
    org_b = create_org(name="State Univ", org_type="EDUCATION")
    req_a = submit_request(create_draft_request(
        org_a["id"], consumer_name="Pat", modality="ASL_ONSITE", ada_context="MEDICAL",
        scheduled_start="2026-06-10T14:00:00Z", scheduled_end="2026-06-10T15:00:00Z",
        estimated_mileage=0))
    req_b = create_submitted_vri_request(
        org_b["id"], start="2026-06-11T14:00:00Z", end="2026-06-11T15:00:00Z",
        consumer_name="Stu")
    assert req_a["status"] == "MATCHING" and req_b["status"] == "MATCHING"

    report = get_success_data(api_client.generate_report(
        {"window_start": "2026-06-01T00:00:00Z", "window_end": "2026-07-01T00:00:00Z"},
        ADMIN))
    assert_report(report)
    assert report.get("org_id") is None, "omitted org_id means platform-wide"
    assert report["total_requests"] == 2
    assert report["ada_context_mix"] == {
        "MEDICAL": 1, "LEGAL": 0, "EDUCATION": 0, "GENERAL": 1}
    assert report["fulfillment_rate"] == 0.0
    assert report["filled_count"] == 0
