"""Assignment creation and acceptance: qualification, segregation, work-window
collision, daily-throughput capacity, optimistic concurrency, cross-entity state
preconditions, and the provisional payout commitment.

Covers difficulty rules `cross_entity_state_dependency` (assignment->project),
`priority_pair_validation_conflict`, `resource_temporal_overlap`, plus corner
`validations`, `endpoints`, and `cross_cutting_complexity_layers` instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    create_client, create_rate_card, create_linguist, create_project, add_job,
    setup_foundations, quote_and_approve, assign, accept_as_translator,
    current_job_version, make_client_headers, make_translator_headers,
    create_assignment_payload,
)

PM = TEST_USERS["pm_headers"]
AR = TEST_USERS["ar_headers"]


# ─── cross_entity_state_dependency: accept requires project APPROVED ────────
def test_accept_assignment_while_project_quoted_rejected(api):
    """PRD §3.5: "Acceptance carries three further preconditions: ... the parent project
    must be `APPROVED` or `IN_PRODUCTION`, otherwise `ERR_PROJECT_NOT_APPROVED`".

    Design: Difficulty/cross_entity_state_dependency/cesd_assignment_accept_requires_project_approved
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    get_success_data(api.quote_project(project["id"], PM))  # QUOTED, not approved
    jv = current_job_version(job["id"])
    ta = assign(job["id"], translator["id"], "TRANSLATOR", expected_job_version=jv)
    resp = api.accept_assignment(ta["id"], make_translator_headers(translator["id"]))
    validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_APPROVED.value, 409)


def test_accept_assignment_quoted_project_no_state_change(api):
    """PRD §3.5: "the parent project must be `APPROVED` or `IN_PRODUCTION`, otherwise
    `ERR_PROJECT_NOT_APPROVED`".
    PRD §3.5: "A newly created assignment's `status` is `OFFERED`".

    Second probe: the rejected accept leaves the assignment in OFFERED (no transition
    to ACCEPTED occurred).

    Design: Difficulty/cross_entity_state_dependency/cesd_assignment_accept_requires_project_approved
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    get_success_data(api.quote_project(project["id"], PM))
    jv = current_job_version(job["id"])
    ta = assign(job["id"], translator["id"], "TRANSLATOR", expected_job_version=jv)
    api.accept_assignment(ta["id"], make_translator_headers(translator["id"]))
    after = validate_success(api.get_assignment(ta["id"], PM), 200)
    assert after["status"] == "OFFERED", f"expected OFFERED, got {after['status']}"


# ─── priority_pair_validation_conflict: segregation before throughput ───────
def test_reviewer_naming_active_translator_rejected_segregation(api):
    """PRD §3.5: "When the new assignment's role is `REVIEWER`, the named linguist must
    differ from the job's active translator linguist — the reviewer's `linguist_id` may
    not equal the `linguist_id` of the job's non-terminal `TRANSLATOR` assignment — and
    a same-person reviewer assignment is rejected with `ERR_SEGREGATION_VIOLATION`."

    Design: Difficulty/priority_pair_validation_conflict/ppvc_segregation_before_throughput
    """
    client = create_client()
    rate_card = create_rate_card()
    # One linguist who can both translate and review; named as the job's translator
    # and then named again as a same-person reviewer.
    linguist = create_linguist(full_name="Trans One", can_review=True)
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], linguist["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], linguist["id"])
    jv = current_job_version(job["id"])
    resp = api.create_assignment(
        create_assignment_payload(job["id"], linguist["id"], "REVIEWER", jv), PM)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value, 409)


def test_segregation_violation_isolated_from_throughput_check(api):
    """PRD §3.5: "a same-person reviewer assignment is rejected with
    `ERR_SEGREGATION_VIOLATION`."
    PRD §2.6: "(6) reviewer segregation of duties, failing with
    `ERR_SEGREGATION_VIOLATION`; ... (9) the linguist daily-throughput capacity check,
    failing with `ERR_THROUGHPUT_EXCEEDED`".

    Second probe: segregation (priority 6) is checked at assignment-create time, before
    the throughput check (priority 9) which only runs at accept — so a same-person
    reviewer create is rejected with the segregation error, and no reviewer assignment
    is created.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_segregation_before_throughput
    """
    client = create_client()
    rate_card = create_rate_card()
    linguist = create_linguist(full_name="Trans One", can_review=True)
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], linguist["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], linguist["id"])
    jv = current_job_version(job["id"])
    resp = api.create_assignment(
        create_assignment_payload(job["id"], linguist["id"], "REVIEWER", jv), PM)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_VIOLATION.value, 409)
    reviewers, _ = validate_paginated(
        api.list_job_assignments(job["id"], PM, params={"role": "REVIEWER"}))
    assert reviewers == [], "no REVIEWER assignment should have been created"


# ─── priority_pair_validation_conflict: throughput before fiscal/invoice ────
def test_accept_over_throughput_cap_rejected(api):
    """PRD §3.5: "accepting must not push any shared UTC calendar day's committed weighted
    words over the linguist's `daily_throughput_words` cap. ... if adding this
    assignment's weighted words would exceed the daily cap on any shared day, acceptance
    is rejected with `ERR_THROUGHPUT_EXCEEDED`."

    A single accept whose 1775 weighted words exceed a 1000-word cap is rejected.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_throughput_before_fiscal_invoice
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(full_name="Trans Slow", daily_throughput_words=1000)
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    jv = current_job_version(job["id"])
    ta = get_success_data(api.create_assignment(
        create_assignment_payload(job["id"], translator["id"], "TRANSLATOR", jv,
                                  window_start="2026-06-01T00:00:00.000Z",
                                  window_end="2026-06-01T12:00:00.000Z"), PM))
    resp = api.accept_assignment(ta["id"], make_translator_headers(translator["id"]))
    validate_error(resp, ApiErrorId.ERR_THROUGHPUT_EXCEEDED.value, 409)


def test_throughput_rejection_leaves_assignment_offered(api):
    """PRD §3.5: "acceptance is rejected with `ERR_THROUGHPUT_EXCEEDED`."
    PRD §3.5: "A newly created assignment's `status` is `OFFERED`".

    Second probe: the throughput-blocked accept does not transition the assignment; it
    remains OFFERED.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_throughput_before_fiscal_invoice
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(full_name="Trans Slow", daily_throughput_words=1000)
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    jv = current_job_version(job["id"])
    ta = get_success_data(api.create_assignment(
        create_assignment_payload(job["id"], translator["id"], "TRANSLATOR", jv,
                                  window_start="2026-06-01T00:00:00.000Z",
                                  window_end="2026-06-01T12:00:00.000Z"), PM))
    api.accept_assignment(ta["id"], make_translator_headers(translator["id"]))
    after = validate_success(api.get_assignment(ta["id"], PM), 200)
    assert after["status"] == "OFFERED", f"expected OFFERED, got {after['status']}"


# ─── resource_temporal_overlap: per-day aggregate throughput capacity ───────
def _two_jobs_one_accepted(throughput, win_a, win_b):
    """Helper: linguist with `throughput`, two approved single-job projects; the first
    translator assignment (window win_a) accepted; the second created (window win_b)
    and returned not-yet-accepted. Returns (translator, second_assignment)."""
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(daily_throughput_words=throughput)
    proj_a = create_project(client["id"], rate_card["id"], name="P-A")
    job_a = add_job(proj_a["id"])
    quote_and_approve({"project": proj_a, "client": client})
    ta_a = assign(job_a["id"], translator["id"], "TRANSLATOR",
                  window_start=win_a[0], window_end=win_a[1])
    accept_as_translator(ta_a["id"], translator["id"])
    proj_b = create_project(client["id"], rate_card["id"], name="P-B")
    job_b = add_job(proj_b["id"])
    quote_and_approve({"project": proj_b, "client": client})
    ta_b = assign(job_b["id"], translator["id"], "TRANSLATOR",
                  window_start=win_b[0], window_end=win_b[1])
    return translator, ta_b


def test_same_day_throughput_capacity_exceeded(api):
    """PRD §3.5: "The throughput check sums the weighted source words the linguist is
    already committed to across all overlapping `ACCEPTED` and `IN_PROGRESS` windows that
    share a UTC day with the new window, and if adding this assignment's weighted words
    would exceed the daily cap on any shared day, acceptance is rejected with
    `ERR_THROUGHPUT_EXCEEDED`."

    Two windows share 2026-06-01; 1775 + 1775 = 3550 exceeds the 2500 cap.

    Design: Difficulty/resource_temporal_overlap/rto_linguist_same_day_throughput_capacity
    """
    translator, ta_b = _two_jobs_one_accepted(
        2500,
        ("2026-06-01T00:00:00.000Z", "2026-06-01T18:00:00.000Z"),
        ("2026-06-01T06:00:00.000Z", "2026-06-01T23:00:00.000Z"))
    resp = api.accept_assignment(ta_b["id"], make_translator_headers(translator["id"]))
    validate_error(resp, ApiErrorId.ERR_THROUGHPUT_EXCEEDED.value, 409)


def test_same_day_throughput_capacity_does_not_double_commit(api):
    """PRD §3.5: "if adding this assignment's weighted words would exceed the daily cap on
    any shared day, acceptance is rejected with `ERR_THROUGHPUT_EXCEEDED`."
    PRD §3.5: "When acceptance succeeds ... the linguist's `committed_payout_cents` is
    increased by that amount."

    Second probe of the per-day aggregate rule: because the over-cap second accept is
    rejected, the linguist's committed payout stays at the single accepted assignment's
    15975 (the second 1775-word window is not committed onto the shared day).

    Design: Difficulty/resource_temporal_overlap/rto_linguist_same_day_throughput_capacity
    """
    translator, ta_b = _two_jobs_one_accepted(
        2500,
        ("2026-06-01T00:00:00.000Z", "2026-06-01T18:00:00.000Z"),
        ("2026-06-01T06:00:00.000Z", "2026-06-01T23:00:00.000Z"))
    api.accept_assignment(ta_b["id"], make_translator_headers(translator["id"]))
    ling = validate_success(api.get_linguist(translator["id"], PM), 200)
    assert ling["committed_payout_cents"] == 15975, \
        f"expected only the first 15975 committed, got {ling['committed_payout_cents']}"


def test_disjoint_day_throughput_accept_succeeds(api):
    """PRD §3.5: "The throughput check sums the weighted source words the linguist is
    already committed to across all overlapping `ACCEPTED` and `IN_PROGRESS` windows that
    share a UTC day with the new window".

    Negative side of the per-day rule: two windows on disjoint days (06-01 and 06-03),
    each 1775 <= 2500, so the second accept succeeds and the committed payout sums to
    15975 + 15975 = 31950.

    Design: Corner/cross_cutting_complexity_layers/throughput_disjoint_days_accept_succeeds
    """
    translator, ta_b = _two_jobs_one_accepted(
        2500,
        ("2026-06-01T00:00:00.000Z", "2026-06-01T18:00:00.000Z"),
        ("2026-06-03T00:00:00.000Z", "2026-06-03T18:00:00.000Z"))
    accepted = validate_success(
        api.accept_assignment(ta_b["id"], make_translator_headers(translator["id"])), 200)
    # PRD §3.5: "Once accepted, an assignment becomes IN_PROGRESS automatically as the
    # job moves into active work." A translator accept drives the job into TRANSLATING,
    # so the assignment is IN_PROGRESS by the end of the accept call.
    assert accepted["status"] == "IN_PROGRESS", f"got {accepted['status']}"
    ling = validate_success(api.get_linguist(translator["id"], PM), 200)
    assert ling["committed_payout_cents"] == 31950, \
        f"expected 31950, got {ling['committed_payout_cents']}"


# ─── resource_temporal_overlap: half-open reviewer/translator window overlap ─
def _job_translating_with_translator_window(win):
    """Approved project, one job, translator accepted on window `win` (job TRANSLATING).
    Returns (job, reviewer_linguist)."""
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist(full_name="Trans One")
    reviewer = create_linguist(full_name="Rev One", can_review=True)
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR",
                window_start=win[0], window_end=win[1])
    accept_as_translator(ta["id"], translator["id"])
    return job, reviewer


def test_reviewer_window_interior_overlap_rejected(api):
    """PRD §3.5: "the new half-open window must not overlap the job's active (non-terminal)
    translator window: because the intervals are half-open, a reviewer window whose
    `window_start` exactly equals the translator window's `window_end` does **not** overlap
    and is allowed, while any interior intersection of the two intervals does overlap and
    is rejected with `ERR_WINDOW_OVERLAP`."

    Reviewer window [06-01T12:00, 06-02T12:00) interior-intersects translator
    [06-01T00:00, 06-02T00:00).

    Design: Difficulty/resource_temporal_overlap/rto_job_reviewer_window_overlaps_translator_window
    """
    job, reviewer = _job_translating_with_translator_window(
        ("2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z"))
    jv = current_job_version(job["id"])
    resp = api.create_assignment(
        create_assignment_payload(job["id"], reviewer["id"], "REVIEWER", jv,
                                  window_start="2026-06-01T12:00:00.000Z",
                                  window_end="2026-06-02T12:00:00.000Z"), PM)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value, 409)


def test_reviewer_window_overlap_creates_no_reviewer_assignment(api):
    """PRD §3.5: "any interior intersection of the two intervals does overlap and is
    rejected with `ERR_WINDOW_OVERLAP`."
    PRD §3.5: "As a matter of structure, creating an assignment supersedes any prior
    non-terminal assignment of the same role on the same job".

    Second probe of the per-job interval-collision rule: because the overlapping reviewer
    create is rejected, no REVIEWER assignment exists on the job (and the active translator
    assignment is untouched).

    Design: Difficulty/resource_temporal_overlap/rto_job_reviewer_window_overlaps_translator_window
    """
    job, reviewer = _job_translating_with_translator_window(
        ("2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z"))
    jv = current_job_version(job["id"])
    api.create_assignment(
        create_assignment_payload(job["id"], reviewer["id"], "REVIEWER", jv,
                                  window_start="2026-06-01T12:00:00.000Z",
                                  window_end="2026-06-02T12:00:00.000Z"), PM)
    reviewers, _ = validate_paginated(
        api.list_job_assignments(job["id"], PM, params={"role": "REVIEWER"}))
    assert reviewers == [], "an overlapping reviewer create must not persist an assignment"


def test_reviewer_window_touching_translator_end_allowed(api):
    """PRD §3.5: "a reviewer window whose `window_start` exactly equals the translator
    window's `window_end` does **not** overlap and is allowed".

    Half-open boundary (negative side of ERR_WINDOW_OVERLAP): reviewer window
    [06-02T00:00, 06-03T00:00) touches but does not overlap translator
    [06-01T00:00, 06-02T00:00); the reviewer assignment-create succeeds (status OFFERED).

    Design: Corner/cross_cutting_complexity_layers/reviewer_window_touching_translator_end_no_overlap
    """
    job, reviewer = _job_translating_with_translator_window(
        ("2026-06-01T00:00:00.000Z", "2026-06-02T00:00:00.000Z"))
    jv = current_job_version(job["id"])
    created = validate_success(api.create_assignment(
        create_assignment_payload(job["id"], reviewer["id"], "REVIEWER", jv,
                                  window_start="2026-06-02T00:00:00.000Z",
                                  window_end="2026-06-03T00:00:00.000Z"), PM), 201)
    assert created["status"] == "OFFERED", f"got {created['status']}"


# ─── corner validations: qualification, inactive, bad window, priority ──────
def test_assign_unqualified_linguist_returns_not_qualified(api):
    """PRD §3.5: "The assigned linguist must be qualified for the project's source-and-
    target locale pair and must be `ACTIVE`; a linguist who does not list the pair in
    `qualified_pairs`, or who is inactive, is rejected with `ERR_LINGUIST_NOT_QUALIFIED`."

    Design: Corner/validations/assign_unqualified_linguist_returns_not_qualified
    """
    client = create_client()
    rate_card = create_rate_card()  # en-US -> de-DE
    linguist = create_linguist(full_name="Wrong Pair",
                               qualified_pairs=[{"source_locale": "fr-FR",
                                                 "target_locale": "de-DE"}])
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"], bands={"quoted_no_match_words": 1000})
    quote_and_approve({"project": project, "client": client})
    jv = current_job_version(job["id"])
    resp = api.create_assignment(
        create_assignment_payload(job["id"], linguist["id"], "TRANSLATOR", jv), PM)
    validate_error(resp, ApiErrorId.ERR_LINGUIST_NOT_QUALIFIED.value, 409)


def test_accept_assignment_by_inactive_linguist_returns_inactive(api):
    """PRD §3.5: "Acceptance carries three further preconditions: the accepting linguist's
    `status` must be `ACTIVE`, otherwise `ERR_LINGUIST_INACTIVE`".

    Design: Corner/validations/accept_assignment_by_inactive_linguist_returns_inactive
    """
    client = create_client()
    rate_card = create_rate_card()
    linguist = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"], bands={"quoted_no_match_words": 1000})
    quote_and_approve({"project": project, "client": client})
    jv = current_job_version(job["id"])
    ta = assign(job["id"], linguist["id"], "TRANSLATOR", expected_job_version=jv)
    get_success_data(api.deactivate_linguist(linguist["id"], PM))
    resp = api.accept_assignment(ta["id"], make_translator_headers(linguist["id"]))
    validate_error(resp, ApiErrorId.ERR_LINGUIST_INACTIVE.value, 409)


def test_create_assignment_window_end_before_start_returns_invalid_request(api):
    """PRD §3.5: "The work window is half-open: `window_end` must be strictly later than
    `window_start`, and a body that violates this is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/create_assignment_window_end_before_start_returns_invalid_request
    """
    client = create_client()
    rate_card = create_rate_card()
    linguist = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"], bands={"quoted_no_match_words": 1000})
    quote_and_approve({"project": project, "client": client})
    jv = current_job_version(job["id"])
    resp = api.create_assignment(
        create_assignment_payload(job["id"], linguist["id"], "TRANSLATOR", jv,
                                  window_start="2026-06-02T00:00:00.000Z",
                                  window_end="2026-06-01T00:00:00.000Z"), PM)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_priority_existence_before_state(api):
    """PRD §2.6: "(3) the existence sweep over path and foreign-key resources, which fails
    with `ERR_NOT_FOUND`; ... (5) the state check that the target resource is in a state
    from which the requested transition is allowed, which fails with `ERR_INVALID_STATE`".

    A non-existent project id is rejected with ERR_NOT_FOUND (existence precedes state).

    Design: Corner/validations/priority_existence_before_state
    """
    client = create_client()
    resp = api.approve_project(NON_EXISTENT_UUID, make_client_headers(client["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)


# ─── corner cross_cutting: OCC + derived field ─────────────────────────────
def test_occ_assignment_create_stale_job_version_returns_412(api):
    """PRD §2.8: "The server compares it against the target job's current `version`; if
    another writer has advanced that version since the client read it — most commonly
    because a replacement assignment of the same role was already created on the job,
    which legitimately supersedes the prior one and increments the job's `version` — the
    create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_assignment_create_stale_job_version_returns_412
    """
    client = create_client()
    rate_card = create_rate_card()
    la = create_linguist(full_name="A")
    lb = create_linguist(full_name="B")
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"], bands={"quoted_no_match_words": 1000})
    quote_and_approve({"project": project, "client": client})
    jv1 = current_job_version(job["id"])
    # First create bumps the job version (and supersedes nothing yet).
    assign(job["id"], la["id"], "TRANSLATOR", expected_job_version=jv1)
    # Second create reuses the now-stale jv1.
    resp = api.create_assignment(
        create_assignment_payload(job["id"], lb["id"], "TRANSLATOR", jv1), PM)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_committed_payout_reconciled_after_accept(api):
    """PRD §3.5: "When acceptance succeeds, the assignment's `payout_cents` is set to the
    provisional linguist payout computed over the job's quoted bands (see §3.9), a
    `COMMIT` ledger entry of that amount is appended, and the linguist's
    `committed_payout_cents` is increased by that amount."

    Design: Corner/cross_cutting_complexity_layers/derived_field_reconciliation_committed_payout_after_accept
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"])  # default bands -> weighted 1775; 1775*9 = 15975
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR")
    accept_as_translator(ta["id"], translator["id"])
    ling = validate_success(api.get_linguist(translator["id"], PM), 200)
    assert ling["committed_payout_cents"] == 15975, \
        f"expected 15975, got {ling['committed_payout_cents']}"


def test_list_job_assignments_returns_array(api):
    """PRD §3.12: "a job's assignments ... are all listable from their parent".
    PRD §3.12: "a job's assignment list also accepts a `role` filter".

    Design: Corner/endpoints/list_job_assignments_filtered_by_role
    """
    client = create_client()
    rate_card = create_rate_card()
    translator = create_linguist()
    project = create_project(client["id"], rate_card["id"])
    job = add_job(project["id"], bands={"quoted_no_match_words": 1000})
    quote_and_approve({"project": project, "client": client})
    ta = assign(job["id"], translator["id"], "TRANSLATOR")
    data, _ = validate_paginated(
        api.list_job_assignments(job["id"], PM, params={"role": "TRANSLATOR"}))
    assert len(data) == 1, f"expected 1 translator assignment, got {len(data)}"
    assert data[0]["id"] == ta["id"]
