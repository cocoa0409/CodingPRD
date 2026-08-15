"""Branch offices, inspection scheduling, and the inspection lifecycle.

Covers inspection creation defaults, the conditional close fork, terminal
lockdown, the 300-day scheduling gap, OCC on branch version, missing user
context, and the list-response envelope contract.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_finding,
    assert_branch_inspection,
    close_inspection_now,
    close_inspection_payload,
    create_branch_payload,
    create_finding_payload,
    create_inspection_payload,
    get_branch,
    make_branch,
    make_rep,
    schedule_inspection,
    set_clock,
    setup_branch_with_closed_inspection,
    setup_in_progress_inspection,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["analyst_headers"]
PRINCIPAL_A = TEST_USERS["principal_a_headers"]


# ─── inspection creation defaults ─────────────────────

def test_inspection_create_defaults_and_due_date(api, any_headers):
    """PRD §3.2: "A successful scheduling increments the branch's `version`
    by one." PRD §3.1: "its `next_inspection_due_date` is initialized to the
    branch's creation date plus the inspection cycle" — a branch created at
    the default clock 2026-08-01 with the default 12-month cycle is first due
    2027-08-01, and the fresh inspection starts SCHEDULED with zeroed counts
    and no started/completed stamps.

    Design: Corner/entities/inspection_create_defaults_and_computed
    """
    branch = make_branch(name="Init Branch", region="E")
    res = schedule_inspection(branch["id"], scheduled_date="2026-08-10")
    inspection = validate_success(res, 201)
    assert_branch_inspection(inspection)
    assert inspection["status"] == "SCHEDULED"
    assert inspection["open_findings_count"] == 0
    assert inspection["high_severity_open_count"] == 0
    assert inspection.get("started_at") is None
    assert inspection.get("completed_date") is None

    branch_after = get_branch(branch["id"])
    assert branch_after["version"] == branch["version"] + 1, (
        "scheduling must increment the branch version by exactly one"
    )
    assert branch_after["next_inspection_due_date"] == "2027-08-01"


def test_get_nonexistent_branch_returns_not_found(api, any_headers):
    """PRD §2.10: "Identifiers are validated left to right, and the first
    unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/get_nonexistent_branch_returns_not_found
    """
    res = api.get_branch("00000000-0000-4000-8000-000000000000", any_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


# ─── conditional close ────────────────────────────────

def test_zero_finding_close_goes_straight_to_closed(api, any_headers):
    """PRD §3.2: "From `IN_PROGRESS`, the close moves the inspection directly
    to `CLOSED` when the inspection's `open_findings_count` is zero — a
    zero-finding close — and to `AWAITING_REMEDIATION` when open findings
    remain". PRD §3.2: "Reaching `CLOSED` stamps `completed_date` with the
    current clock date".

    Design: Corner/state_machines/zero_finding_close_allowed
    """
    branch, inspection = setup_in_progress_inspection(region="W")
    res = close_inspection_now(inspection["id"])
    closed = validate_success(res, 200)
    assert closed["status"] == "CLOSED"
    assert closed["completed_date"] == "2026-08-01"


def test_close_with_open_findings_awaits_remediation_then_blocked(api, any_headers):
    """PRD §3.2: "From `AWAITING_REMEDIATION`, the close succeeds only when
    every finding of the inspection has reached `VERIFIED_CLOSED`; if any
    finding remains non-terminal, the close is rejected with
    `ERR_FINDINGS_STILL_OPEN`". The first close only forks the inspection, so
    the same expected_branch_version still satisfies the OCC guard.

    Design: Corner/state_machines/guard_close_with_open_findings
    """
    branch, inspection = setup_in_progress_inspection(region="S")
    add_finding(inspection["id"], severity="MEDIUM", description="gap")

    branch_v = get_branch(branch["id"])["version"]
    res = api.close_inspection(
        inspection["id"], close_inspection_payload(branch_v), PRINCIPAL_A,
    )
    mid = validate_success(res, 200)
    assert mid["status"] == "AWAITING_REMEDIATION"

    res2 = api.close_inspection(
        inspection["id"], close_inspection_payload(branch_v), PRINCIPAL_A,
    )
    validate_error(res2, ApiErrorId.ERR_FINDINGS_STILL_OPEN)


def test_close_from_closed_terminal_lockdown(api, any_headers):
    """PRD §3.2: "a close attempted from a state the transition does not
    allow — including a terminal `CLOSED` — is rejected with
    `ERR_INSPECTION_INVALID_STATE`". The OCC guard is satisfied with the
    current branch version, isolating the state lockdown as the cause.

    Design: Corner/state_machines/terminal_lockdown_closed_inspection
    """
    branch, inspection = setup_in_progress_inspection(region="N")
    closed = validate_success(close_inspection_now(inspection["id"]), 200)
    assert closed["status"] == "CLOSED"

    branch_v = get_branch(branch["id"])["version"]
    res = api.close_inspection(
        inspection["id"], close_inspection_payload(branch_v), PRINCIPAL_A,
    )
    validate_error(res, ApiErrorId.ERR_INSPECTION_INVALID_STATE)


# ─── finding creation guard ───────────────────────────

def test_finding_requires_in_progress_inspection(api, any_headers):
    """PRD §3.2: "While the inspection is `IN_PROGRESS`, analysts record
    findings against it" — against a SCHEDULED inspection the create is
    rejected with the inspection state error ("starting from any other state
    is rejected with `ERR_INSPECTION_INVALID_STATE`" gives the per-resource
    code), and after start the finding lands in OPEN and increments the
    inspection's open_findings_count.

    Design: Corner/state_machines/inspection_start_then_add_finding
    """
    branch = make_branch(region="E")
    res = schedule_inspection(branch["id"], scheduled_date="2026-08-10")
    inspection = validate_success(res, 201)
    assert inspection["status"] == "SCHEDULED"

    bad = api.create_finding(
        create_finding_payload(inspection["id"], severity="LOW"), ANALYST,
    )
    validate_error(bad, ApiErrorId.ERR_INSPECTION_INVALID_STATE)

    started = validate_success(api.start_inspection(inspection["id"], ANALYST), 200)
    assert started["status"] == "IN_PROGRESS"

    finding = validate_success(
        api.create_finding(
            create_finding_payload(inspection["id"], severity="LOW",
                                   description="on time"),
            ANALYST,
        ),
        201,
    )
    assert finding["status"] == "OPEN"
    after = validate_success(api.get_inspection(inspection["id"], any_headers), 200)
    assert after["open_findings_count"] == 1


# ─── single open inspection ───────────────────────────

def test_second_open_inspection_rejected_with_current_version(api, any_headers):
    """PRD §3.2: "a branch may have at most one inspection that is not yet
    `CLOSED` — that is, at most one inspection in `SCHEDULED`, `IN_PROGRESS`,
    or `AWAITING_REMEDIATION`; attempting to schedule a second is rejected
    with `ERR_INSPECTION_ALREADY_OPEN`". The request carries the branch's
    current version so the constraint check — not OCC — fires.

    Design: Corner/errors/inspection_already_open_rejected
    """
    branch = make_branch(region="E")
    first = validate_success(
        schedule_inspection(branch["id"], scheduled_date="2026-09-15"), 201
    )
    assert first["status"] == "SCHEDULED"
    res = schedule_inspection(branch["id"], scheduled_date="2026-09-16")
    validate_error(res, ApiErrorId.ERR_INSPECTION_ALREADY_OPEN)


# ─── 300-day gap boundary ─────────────────────────────

class TestInspectionMinGapBuffer:
    def test_gap_of_299_days_rejected(self, api, any_headers):
        """PRD §3.2: "the `scheduled_date` must fall at least 300 days after
        the `completed_date` of the branch's last `CLOSED` inspection; a
        shorter gap is rejected with `ERR_INSPECTION_GAP_VIOLATION`".
        2026-12-25 is 299 days after the 2026-03-01 completion.

        Design: Difficulty/resource_temporal_overlap/inspection_min_gap_buffer
        """
        branch, _closed = setup_branch_with_closed_inspection()
        set_clock("2026-09-01T09:00:00Z")
        res = schedule_inspection(branch["id"], scheduled_date="2026-12-25")
        validate_error(res, ApiErrorId.ERR_INSPECTION_GAP_VIOLATION)

    def test_gap_of_exactly_300_days_allowed(self, api, any_headers):
        """PRD §3.2: "the `scheduled_date` must fall at least 300 days after
        the `completed_date` of the branch's last `CLOSED` inspection; a
        shorter gap is rejected with `ERR_INSPECTION_GAP_VIOLATION`".
        2026-12-26 is exactly 300 days after 2026-03-01, so "at least 300
        days" is satisfied and the schedule succeeds.

        Design: Difficulty/resource_temporal_overlap/inspection_min_gap_buffer
        """
        branch, _closed = setup_branch_with_closed_inspection()
        set_clock("2026-09-01T09:00:00Z")
        res = schedule_inspection(branch["id"], scheduled_date="2026-12-26")
        inspection = validate_success(res, 201)
        assert inspection["status"] == "SCHEDULED"


# ─── OCC on branch version ────────────────────────────

class TestInspectionCreateOcc:
    def test_stale_branch_version_rejected(self, api, any_headers):
        """PRD §2.9: "a mismatch with the branch's current `version` is
        rejected with `ERR_STALE_BRANCH_VERSION` (HTTP 412), so that
        scheduling decisions are never made on stale cycle math, posture, or
        due-date state." The second create carries the version observed
        before the first scheduling advanced it.

        Design: Difficulty/cross_cutting/occ_inspection_create_stale_branch
        """
        branch = make_branch(region="W")
        stale_v = branch["version"]
        first = api.create_inspection(
            create_inspection_payload(
                branch["id"], expected_branch_version=stale_v,
                scheduled_date="2026-09-15",
            ),
            ANALYST,
        )
        validate_success(first, 201)

        res = api.create_inspection(
            create_inspection_payload(
                branch["id"], expected_branch_version=stale_v,
                scheduled_date="2026-09-16",
            ),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_STALE_BRANCH_VERSION)

    def test_stale_rejection_creates_no_inspection(self, api, any_headers):
        """PRD §2.9: "The OCC check runs after authentication, authorization,
        and existence checks, but before every business rule on the guarded
        endpoint." A create rejected at the OCC gate persists nothing: the
        branch still has exactly the one inspection from the accepted call.

        Design: Difficulty/cross_cutting/occ_inspection_create_stale_branch
        """
        branch = make_branch(region="W")
        stale_v = branch["version"]
        validate_success(
            api.create_inspection(
                create_inspection_payload(
                    branch["id"], expected_branch_version=stale_v,
                    scheduled_date="2026-09-15",
                ),
                ANALYST,
            ),
            201,
        )
        res = api.create_inspection(
            create_inspection_payload(
                branch["id"], expected_branch_version=stale_v,
                scheduled_date="2026-09-16",
            ),
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_STALE_BRANCH_VERSION)

        data, meta = validate_paginated(
            api.list_inspections(any_headers, params={"branch_id": branch["id"]})
        )
        assert len(data) == 1, f"stale create must not persist: {data}"


# ─── platform contract: auth + envelope ───────────────

def test_missing_user_context_header(api):
    """PRD §2.1: "If either header is missing, or the role value is not one
    of the recognized values, the request is rejected with
    `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

    Design: Corner/rbac/missing_user_context_header
    """
    res = api.create_branch(create_branch_payload(name="NoAuth", region="E"),
                            headers={})
    validate_error(res, ApiErrorId.ERR_MISSING_USER_CONTEXT)


def test_list_envelope_and_pagination(api, any_headers):
    """PRD §2.3: "The `meta` object of a list response carries the pagination
    fields `limit`, `offset`, `total_count`, and `has_more`." PRD §2.2:
    "The `response_type` is either "object" for a single resource or "array"
    for a list of resources." Two representatives paginate one per page:
    page 1 reports has_more true, page 2 reports has_more false.

    Design: Corner/endpoints/envelope_shape_and_pagination
    """
    branch = make_branch(name="PG Branch", region="E")
    make_rep(branch["id"], crd_number="940001", full_name="PG One")
    make_rep(branch["id"], crd_number="940002", full_name="PG Two")

    res1 = api.list_representatives(any_headers, params={"limit": 1, "offset": 0})
    page1, meta1 = validate_paginated(res1)
    body1 = res1.json()
    assert body1["response_type"] == "array"
    assert isinstance(body1["meta"]["api_request_id"], str)
    assert body1["meta"]["api_request_id"].startswith("req_")
    assert len(page1) == 1
    assert meta1["total_count"] == 2
    assert meta1["has_more"] is True

    res2 = api.list_representatives(any_headers, params={"limit": 1, "offset": 1})
    page2, meta2 = validate_paginated(res2)
    assert len(page2) == 1
    assert meta2["total_count"] == 2
    assert meta2["has_more"] is False
    assert page1[0]["id"] != page2[0]["id"]
