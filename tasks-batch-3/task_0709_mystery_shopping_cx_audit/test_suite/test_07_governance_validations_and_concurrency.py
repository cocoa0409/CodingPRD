"""Governance gates, publish/submit validations, RBAC, pagination, optimistic
concurrency, derived-counter reconciliation, and the remaining error-catalogue
violations.

Covers the corner validations, endpoints, rbac, cross_cutting_complexity_layers,
state_machines (sweep), and errors instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, fixtures,
)
from test_helpers.test_users import (
    make_anonymous_headers,
    make_platform_admin_headers,
    make_qa_validator_headers,
    make_finance_officer_headers,
    make_client_manager_headers,
    make_shopper_headers,
)
from test_helpers import factories


# ---------------------------------------------------------------------------
# validations / weights_not_normalized_publish_rejected
# ---------------------------------------------------------------------------
def test_publish_script_with_weights_not_summing_to_one_rejected(api):
    """PRD 3.3: "A script moves DRAFT -> PUBLISHED only when it is currently DRAFT,
    its owning client is ACTIVE, and its weights satisfy that sum-to-1.00 rule; a
    publish attempt whose weights are negative anywhere or do not sum to 1.00 (round
    half up, two decimal places) is rejected with ERR_WEIGHTS_NOT_NORMALIZED."

    Design: Corner/validations/weights_not_normalized_publish_rejected
    """
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cm = make_client_manager_headers(client["id"])
    payload = factories.create_script_payload(
        weights_json={"greeting": 0.5, "cleanliness": 0.4}, receipt_required=False,
    )
    script = validate_success(api.create_script(client["id"], payload, cm), expected_status=201)
    resp = api.publish_script(script["id"], cm)
    validate_error(resp, ApiErrorId.ERR_WEIGHTS_NOT_NORMALIZED.value)
    fetched = validate_success(api.list_scripts(client["id"], cm))
    item = fetched[0] if isinstance(fetched, list) else fetched
    assert item["status"] == "DRAFT", "script must stay DRAFT after a rejected publish"


# ---------------------------------------------------------------------------
# validations / scorecard_section_keys_mismatch_rejected
# ---------------------------------------------------------------------------
def test_scorecard_section_keys_mismatch_rejected(api):
    """PRD 3.5: "The keys of section_scores_json must be exactly the keys of the
    script's weights_json, no missing keys and no extra keys; a mismatch is rejected
    with ERR_SECTION_KEYS_MISMATCH."

    Design: Corner/validations/scorecard_section_keys_mismatch_rejected
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0, weights_json={"greeting": 1.0},
    )
    asg = fixtures.create_in_field_assignment(
        cat["client"]["id"], cat["wave"]["id"], cat["shopper"]["id"],
        cat["location"]["id"], cat["script"]["id"], "2026-06-20T00:00:00Z",
    )
    resp = api.create_scorecard(asg["id"], {"section_scores_json": {"greeting": 80, "extra": 50}},
                                make_shopper_headers(cat["shopper"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SECTION_KEYS_MISMATCH.value)


# ---------------------------------------------------------------------------
# validations / invalid_window_create_wave_rejected
# ---------------------------------------------------------------------------
def test_create_wave_with_inverted_window_rejected(api):
    """PRD 3.3: "The field_window_end must be strictly after field_window_start; a
    window that violates this -- whether at wave creation or at publish -- is
    rejected with ERR_INVALID_WINDOW."

    Design: Corner/validations/invalid_window_create_wave_rejected
    """
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cm = make_client_manager_headers(client["id"])
    payload = factories.create_wave_payload(
        field_window_start="2026-06-30T00:00:00Z", field_window_end="2026-06-01T00:00:00Z",
    )
    resp = api.create_wave(client["id"], payload, cm)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW.value)


# ---------------------------------------------------------------------------
# validations / revision_limit_reached_after_two_submissions
# ---------------------------------------------------------------------------
def test_request_revision_after_limit_reached_rejected(api):
    """PRD 3.6: "Requesting a revision moves the assignment SUBMITTED ->
    REVISION_REQUESTED. It is permitted only while the assignment is SUBMITTED and
    its submission_count is at most 2; a request-revision when submission_count
    exceeds 2 is rejected with ERR_REVISION_LIMIT_REACHED."

    Design: Corner/validations/revision_limit_reached_after_two_submissions
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0, weights_json={"greeting": 1.0},
    )
    sid = cat["shopper"]["id"]
    sh, qa = make_shopper_headers(sid), make_qa_validator_headers()
    asg = fixtures.create_in_field_assignment(
        cat["client"]["id"], cat["wave"]["id"], sid, cat["location"]["id"],
        cat["script"]["id"], "2026-06-28T00:00:00Z",
    )
    aid = asg["id"]
    photo_id = fixtures.add_approved_photo(aid, sid)
    fixtures.create_scorecard(aid, sid, {"greeting": 88})
    # Submit #1 (submission_count -> 1).
    validate_success(api.submit_assignment(aid, sh))
    # Revision round 1: request-revision, resume, re-approve, submit #2 (-> 2).
    validate_success(api.request_revision(aid, qa))
    validate_success(api.resume_assignment(aid, sh))
    validate_success(api.review_evidence(photo_id, {"decision": "APPROVE"}, qa))
    validate_success(api.submit_assignment(aid, sh))
    # Revision round 2: request-revision, resume, re-approve, submit #3 (-> 3).
    validate_success(api.request_revision(aid, qa))
    validate_success(api.resume_assignment(aid, sh))
    validate_success(api.review_evidence(photo_id, {"decision": "APPROVE"}, qa))
    submitted3 = validate_success(api.submit_assignment(aid, sh))
    assert submitted3["submission_count"] == 3, (
        f"submission_count expected 3 before the trigger, got {submitted3['submission_count']}"
    )
    # Third request-revision is rejected (submission_count 3 > 2).
    resp = api.request_revision(aid, qa)
    validate_error(resp, ApiErrorId.ERR_REVISION_LIMIT_REACHED.value)


# ---------------------------------------------------------------------------
# state_machines / sweep_deadline_expires_overdue_assigned_and_penalizes
# ---------------------------------------------------------------------------
def test_sweep_deadline_expires_overdue_assignment_and_penalizes(api):
    """PRD 3.7: "When the logical clock has advanced past an assignment's due_at and
    the assignment is still in ASSIGNED, IN_FIELD, or REVISION_REQUESTED, the sweep
    moves it to EXPIRED, decrements the shopper's reliability_score by 20 (floored
    at 0), and -- when the assignment had been IN_FIELD or REVISION_REQUESTED --
    decrements the shopper's open_assignment_count by 1."

    Design: Corner/state_machines/sweep_deadline_expires_overdue_assigned_and_penalizes
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
    )
    sid = cat["shopper"]["id"]
    asg = fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], sid, cat["location"]["id"],
        cat["script"]["id"], "2026-06-05T00:00:00Z",
    )
    fixtures.set_clock("2026-06-06T00:00:00Z")  # advance past due_at
    swept = validate_success(api.sweep_deadline(asg["id"], make_platform_admin_headers()))
    assert swept["status"] == "EXPIRED", f"expected EXPIRED after sweep, got {swept['status']}"
    shopper = validate_success(api.get_shopper(sid, make_platform_admin_headers()))
    assert shopper["reliability_score"] == 80, (
        f"reliability_score expected 80 (100 - 20), got {shopper['reliability_score']}"
    )


# ---------------------------------------------------------------------------
# endpoints / list_locations_paginated_envelope
# ---------------------------------------------------------------------------
def test_list_locations_paginated_envelope(api):
    """PRD 2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/list_locations_paginated_envelope
    """
    client = fixtures.register_client(fee_per_completed_shop_cents=15000)
    cid = client["id"]
    fixtures.create_location(cid, scenario_family="RETAIL", lat=40.0, lng=-74.0, label="L1")
    fixtures.create_location(cid, scenario_family="DINING", lat=41.0, lng=-75.0, label="L2")
    cm = make_client_manager_headers(cid)
    resp = api.list_locations(cid, cm, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2, f"total_count expected 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"has_more expected True with limit 1, got {meta['has_more']}"


# ---------------------------------------------------------------------------
# rbac / shopper_cannot_validate_assignment_forbidden_role
# ---------------------------------------------------------------------------
def test_shopper_cannot_validate_assignment(api):
    """PRD 2.1: "When a request carries a role that is recognized but not permitted
    to invoke the targeted operation under the access-control matrix in Section 4,
    the request is rejected with ERR_FORBIDDEN_ROLE."

    The validate endpoint authorizes only QaValidator (Section 4 endpoint table).

    Design: Corner/rbac/shopper_cannot_validate_assignment_forbidden_role
    """
    cat = fixtures.setup_submitted_assignment(
        due_at="2026-06-20T00:00:00Z", section_scores_json={"greeting": 88},
    )
    aid, sid = cat["assignment"]["id"], cat["shopper"]["id"]
    resp = api.validate_assignment(aid, make_shopper_headers(sid))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
    asg = validate_success(api.get_assignment(aid, make_qa_validator_headers()))
    assert asg["status"] == "SUBMITTED", "assignment must stay SUBMITTED after a forbidden validate"


# ---------------------------------------------------------------------------
# rbac / missing_auth_headers_unauthenticated
# ---------------------------------------------------------------------------
def test_missing_auth_headers_unauthenticated(api):
    """PRD 2.1: "A request that omits either header, or supplies a malformed value,
    is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    shopper = fixtures.register_shopper(tax_id_on_file=False, home_lat=40.0, home_lng=-74.0)
    # No X-User-ID / X-User-Role headers at all.
    resp = api._request("GET", f"/shoppers/{shopper['id']}", headers={})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ---------------------------------------------------------------------------
# rbac / finance_officer_segregation_blocks_self_validated_batch
# ---------------------------------------------------------------------------
def test_segregation_of_duties_blocks_self_validated_batch(api):
    """PRD 2.8: "When a FinanceOfficer later batches or pays the reimbursement that
    flows from that assignment, the platform compares the officer's X-User-ID
    against the assignment's validated_by_user_id; if they are equal, the request is
    rejected with ERR_SEGREGATION_OF_DUTIES. This check applies both when collecting
    reimbursements into a batch and when paying a batch."

    Design: Corner/rbac/finance_officer_segregation_blocks_self_validated_batch
    """
    # The same opaque user id "dual-op-1" both validates (as QaValidator) and
    # batches (as FinanceOfficer).
    cat = fixtures.setup_validated_assignment(
        due_at="2026-06-20T00:00:00Z", loc_lat=40.0, loc_lng=-74.0, qa_user_id="dual-op-1",
    )
    reimb = fixtures.get_assignment_reimbursement(cat["assignment"]["id"])
    resp = api.create_payout_batch(
        {"shopper_id": cat["shopper"]["id"], "reimbursement_ids": [reimb["id"]]},
        make_finance_officer_headers("dual-op-1"),
    )
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


# ---------------------------------------------------------------------------
# cross_cutting / occ_stale_assignment_version_on_cancel_rejected
# ---------------------------------------------------------------------------
def test_cancel_with_stale_version_rejected_then_current_succeeds(api):
    """PRD 2.7: "If expected_assignment_version does not equal the assignment's
    current version at the moment the server processes the cancel, the request is
    rejected with ERR_STALE_ASSIGNMENT_VERSION (HTTP 412)."
    PRD 3.7: "A successful cancel sets the assignment to CANCELLED, increments the
    assignment's version by 1, and -- when the assignment had been IN_FIELD or
    REVISION_REQUESTED -- decrements the shopper's open_assignment_count by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_assignment_version_on_cancel_rejected
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
    )
    sid = cat["shopper"]["id"]
    asg = fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], sid, cat["location"]["id"],
        cat["script"]["id"], "2026-06-20T00:00:00Z",
    )
    v0 = asg["version"]
    accepted = validate_success(api.accept_assignment(asg["id"], make_shopper_headers(sid)))
    v1 = accepted["version"]
    assert v1 != v0, "accept must advance the assignment version"
    cm = make_client_manager_headers(cat["client"]["id"])
    # Stale version v0 is rejected.
    stale = api.cancel_assignment(asg["id"], {"expected_assignment_version": v0}, cm)
    validate_error(stale, ApiErrorId.ERR_STALE_ASSIGNMENT_VERSION.value)
    # Current version v1 succeeds.
    cancelled = validate_success(api.cancel_assignment(asg["id"], {"expected_assignment_version": v1}, cm))
    assert cancelled["status"] == "CANCELLED", f"expected CANCELLED, got {cancelled['status']}"


# ---------------------------------------------------------------------------
# cross_cutting / derived_open_assignment_count_reconciles_on_accept_and_cancel
# ---------------------------------------------------------------------------
def test_open_assignment_count_reconciles_on_accept_and_cancel(api):
    """PRD 3.5: "Accepting increments the shopper's open_assignment_count by 1."
    PRD 3.7: "A successful cancel sets the assignment to CANCELLED, increments the
    assignment's version by 1, and -- when the assignment had been IN_FIELD or
    REVISION_REQUESTED -- decrements the shopper's open_assignment_count by 1."

    Design: Corner/cross_cutting_complexity_layers/derived_open_assignment_count_reconciles_on_accept_and_cancel
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
    )
    sid = cat["shopper"]["id"]
    asg = fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], sid, cat["location"]["id"],
        cat["script"]["id"], "2026-06-20T00:00:00Z",
    )
    accepted = validate_success(api.accept_assignment(asg["id"], make_shopper_headers(sid)))
    after_accept = validate_success(api.get_shopper(sid, make_platform_admin_headers()))
    assert after_accept["open_assignment_count"] == 1, (
        f"open_assignment_count expected 1 after accept, got {after_accept['open_assignment_count']}"
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    validate_success(api.cancel_assignment(
        asg["id"], {"expected_assignment_version": accepted["version"]}, cm))
    after_cancel = validate_success(api.get_shopper(sid, make_platform_admin_headers()))
    assert after_cancel["open_assignment_count"] == 0, (
        f"open_assignment_count expected 0 after cancel, got {after_cancel['open_assignment_count']}"
    )


# ---------------------------------------------------------------------------
# errors / error_shopper_has_open_assignments_on_suspend
# ---------------------------------------------------------------------------
def test_suspend_shopper_with_open_assignments_rejected(api):
    """PRD 3.2: "A PlatformAdmin may suspend a shopper, moving them CERTIFIED ->
    SUSPENDED, but only when the shopper is currently CERTIFIED and their
    open_assignment_count is exactly 0; a suspend attempt on a shopper with one or
    more open assignments is rejected with ERR_SHOPPER_HAS_OPEN_ASSIGNMENTS."

    Design: Corner/errors/error_shopper_has_open_assignments_on_suspend
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
    )
    sid = cat["shopper"]["id"]
    asg = fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], sid, cat["location"]["id"],
        cat["script"]["id"], "2026-06-20T00:00:00Z",
    )
    validate_success(api.accept_assignment(asg["id"], make_shopper_headers(sid)))  # open_assignment_count -> 1
    resp = api.suspend_shopper(sid, make_platform_admin_headers())
    validate_error(resp, ApiErrorId.ERR_SHOPPER_HAS_OPEN_ASSIGNMENTS.value)


# ---------------------------------------------------------------------------
# errors / error_wave_not_drained_on_close
# ---------------------------------------------------------------------------
def test_close_wave_with_live_assignment_rejected(api):
    """PRD 3.3: "A PUBLISHED wave may be closed, moving it PUBLISHED -> CLOSED, but
    only when no assignment in the wave is still in ASSIGNED, IN_FIELD, SUBMITTED, or
    REVISION_REQUESTED... a close attempt while any assignment is still live is
    rejected with ERR_WAVE_NOT_DRAINED."

    Design: Corner/errors/error_wave_not_drained_on_close
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
    )
    fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], cat["shopper"]["id"],
        cat["location"]["id"], cat["script"]["id"], "2026-06-20T00:00:00Z",
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    resp = api.close_wave(cat["wave"]["id"], cm)
    validate_error(resp, ApiErrorId.ERR_WAVE_NOT_DRAINED.value)


# ---------------------------------------------------------------------------
# errors / error_script_in_use_on_archive
# ---------------------------------------------------------------------------
def test_archive_script_referenced_by_live_assignment_rejected(api):
    """PRD 3.3: "A PUBLISHED script may be archived, moving it PUBLISHED ->
    ARCHIVED, but only when no assignment referencing the script is in a
    non-terminal state -- that is, every referencing assignment must be VALIDATED,
    REJECTED, CANCELLED, or EXPIRED; otherwise the archive is rejected with
    ERR_SCRIPT_IN_USE."

    Design: Corner/errors/error_script_in_use_on_archive
    """
    cat = fixtures.setup_catalog_with_shopper(
        scenario_family="RETAIL", loc_lat=40.0, loc_lng=-74.0,
    )
    fixtures.create_assignment(
        cat["client"]["id"], cat["wave"]["id"], cat["shopper"]["id"],
        cat["location"]["id"], cat["script"]["id"], "2026-06-20T00:00:00Z",
    )
    cm = make_client_manager_headers(cat["client"]["id"])
    resp = api.archive_script(cat["script"]["id"], cm)
    validate_error(resp, ApiErrorId.ERR_SCRIPT_IN_USE.value)


# ---------------------------------------------------------------------------
# errors / error_reimbursement_not_accrued_on_double_batch
# ---------------------------------------------------------------------------
def test_batching_already_batched_reimbursement_rejected(api):
    """PRD 3.9: "Each collected reimbursement must currently be ACCRUED; attempting
    to batch one that is not ACCRUED is rejected with ERR_REIMBURSEMENT_NOT_ACCRUED."

    Design: Corner/errors/error_reimbursement_not_accrued_on_double_batch
    """
    cat = fixtures.setup_batched_reimbursement(due_at="2026-06-20T00:00:00Z")
    reimb_id = cat["reimbursement"]["id"]
    resp = api.create_payout_batch(
        {"shopper_id": cat["shopper"]["id"], "reimbursement_ids": [reimb_id]},
        make_finance_officer_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_REIMBURSEMENT_NOT_ACCRUED.value)
