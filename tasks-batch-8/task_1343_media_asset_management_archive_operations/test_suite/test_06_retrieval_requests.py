"""Retrieval workflow: return loop, tier fork, fee quoting, expiry sweep, purpose and
deadline gates, and cancel ownership."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_asset, create_cataloged_asset, create_rights_grant, create_staff_member,
    create_legal_hold,
    create_retrieval_request, create_under_review_request, create_staged_request,
    create_migration_job, run_migration, get_asset, set_clock,
    create_retrieval_request_payload,
    make_requester_headers, make_access_officer_headers,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
OFFICER = TEST_USERS["access_officer_headers"]
LAB = TEST_USERS["lab_technician_headers"]


def _cleared_cataloged_asset(**overrides):
    asset = create_cataloged_asset(**overrides)
    create_rights_grant(asset["id"])
    return asset


# ─── return loop + tier fork (Difficulty x2) ──────────

def test_return_loop_then_approve_stages_with_fee(api):
    """PRD §3.6: "Returning moves `UNDER_REVIEW` back to `SUBMITTED`, increments
    `return_count` by one, and records the supplied `note` in `review_note`."
    PRD §3.6: "If the asset's `storage_tier` is anything other than `DEEP_ARCHIVE`,
    approval moves the request straight to `STAGED` and stamps `staged_at` with the
    current logical time."
    PRD §3.6: "a base of 0 cents for `ONLINE`, 500 cents for `NEARLINE`, or 1,500 cents
    for `DEEP_ARCHIVE`, plus 10 cents for each whole gigabyte of `size_gb` rounded up".

    Design: Difficulty/non_linear_state_machine/retrieval_request_return_loop_and_tier_fork
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset(size_gb=5)
    request = create_under_review_request(asset["id"], staff["id"])
    validate_success(api.return_retrieval_request(
        request["id"], {"note": "need air date"}, OFFICER), 200)
    validate_success(api.start_review(request["id"], OFFICER), 200)

    approved = validate_success(api.approve_retrieval_request(request["id"], OFFICER), 200)
    assert approved["status"] == "STAGED", "ONLINE asset takes the STAGED fork"
    assert approved["return_count"] == 1
    assert approved["quoted_fee_cents"] == 50, "0 base + ceil(5 GB) x 10"
    assert approved["staged_at"] is not None


def test_return_records_note_and_increments_count(api):
    """PRD §3.6: "Returning moves `UNDER_REVIEW` back to `SUBMITTED`, increments
    `return_count` by one, and records the supplied `note` in `review_note`."

    Design: Difficulty/non_linear_state_machine/retrieval_request_return_loop_and_tier_fork
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset()
    request = create_under_review_request(asset["id"], staff["id"])

    returned = validate_success(api.return_retrieval_request(
        request["id"], {"note": "need air date"}, OFFICER), 200)
    assert returned["status"] == "SUBMITTED"
    assert returned["return_count"] == 1
    assert returned["review_note"] == "need air date"


# ─── deep-archive fork / expiry sweep / auto-staging ──

def test_deep_archive_fork_recalling_then_stage_complete(api):
    """PRD §3.6: "If the asset sits in `DEEP_ARCHIVE`, approval instead moves the
    request to `RECALLING` — the tape must be physically recalled before staging."
    PRD §3.6: "a base of 0 cents for `ONLINE`, 500 cents for `NEARLINE`, or 1,500 cents
    for `DEEP_ARCHIVE`, plus 10 cents for each whole gigabyte of `size_gb` rounded up".
    PRD §3.6: "A `LabTechnician` marking the recall complete moves the request from
    `RECALLING` to `STAGED` — from any other state, `ERR_REQUEST_NOT_RECALLING`
    (HTTP 409) — and stamps `staged_at` with the current logical time."

    Design: Corner/state_machines/retrieval_deep_archive_fork_recalling_then_stage_complete
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset(size_gb=40)
    run_migration(asset["id"], "DEEP_ARCHIVE")
    assert get_asset(asset["id"])["storage_tier"] == "DEEP_ARCHIVE"

    request = create_under_review_request(asset["id"], staff["id"])
    approved = validate_success(api.approve_retrieval_request(request["id"], OFFICER), 200)
    assert approved["status"] == "RECALLING", "DEEP_ARCHIVE asset takes the RECALLING fork"
    assert approved["quoted_fee_cents"] == 1900, "1500 base + ceil(40) x 10"

    staged = validate_success(api.stage_complete_retrieval_request(request["id"], LAB), 200)
    assert staged["status"] == "STAGED"
    assert staged["staged_at"] is not None

    delivered = validate_success(api.deliver_retrieval_request(request["id"], OFFICER), 200)
    assert delivered["status"] == "DELIVERED"
    assert delivered["delivered_at"] is not None


def test_deliver_at_72h_boundary_then_expiry_sweep(api):
    """PRD §2.4: "Setting the clock triggers a time-based sweep: every retrieval request
    sitting in `STAGED` whose `staged_at` lies more than 72 hours in the past relative
    to the new clock value transitions to `EXPIRED`."
    PRD §3.6: "a request whose stage hold has lapsed has already been moved to the
    terminal `EXPIRED` state by the clock sweep of §2.4, so a late deliver attempt meets
    `ERR_REQUEST_NOT_STAGED` rather than a live request."

    Design: Corner/state_machines/retrieval_deliver_after_expiry_sweep_rejected
    """
    staff = create_staff_member()
    r1 = create_staged_request(_cleared_cataloged_asset(title="A")["id"], staff["id"])
    r2 = create_staged_request(_cleared_cataloged_asset(title="B")["id"], staff["id"])
    assert r1["staged_at"].startswith("2026-08-01T00:00:00")

    # Exactly staged_at + 72h: not "more than 72 hours", so both survive the sweep.
    set_clock("2026-08-04T00:00:00Z")
    delivered = validate_success(api.deliver_retrieval_request(r1["id"], OFFICER), 200)
    assert delivered["status"] == "DELIVERED"

    # One second past: the sweep expires the second request.
    set_clock("2026-08-04T00:00:01Z")
    late = api.deliver_retrieval_request(r2["id"], OFFICER)
    validate_error(late, ApiErrorId.ERR_REQUEST_NOT_STAGED)
    expired = validate_success(api.get_retrieval_request(r2["id"], OFFICER), 200)
    assert expired["status"] == "EXPIRED"


def test_migration_complete_auto_stages_recalling_request(api):
    """PRD §3.6: "The system provides a second, automatic path: when a migration job for
    the asset completes into any tier other than `DEEP_ARCHIVE` (§3.8), every request of
    that asset sitting in `RECALLING` moves to `STAGED` with `staged_at` set to the
    migration's completion time."

    Design: Corner/state_machines/migration_complete_auto_stages_recalling_request
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset(size_gb=40)
    run_migration(asset["id"], "DEEP_ARCHIVE")
    request = create_under_review_request(asset["id"], staff["id"])
    approved = validate_success(api.approve_retrieval_request(request["id"], OFFICER), 200)
    assert approved["status"] == "RECALLING"

    run_migration(asset["id"], "ONLINE")
    assert get_asset(asset["id"])["storage_tier"] == "ONLINE"
    staged = validate_success(api.get_retrieval_request(request["id"], OFFICER), 200)
    assert staged["status"] == "STAGED", "migration completion must stage the recall"
    assert staged["staged_at"] is not None


# ─── create-time gates ────────────────────────────────

def test_retrieval_on_draft_asset_not_retrievable(api):
    """PRD §3.6: "The asset must be retrievable: a `DISPOSED` asset is rejected with
    `ERR_ASSET_DISPOSED` (HTTP 409), and any catalog status other than `CATALOGED` or
    `ARCHIVED` is rejected with `ERR_ASSET_NOT_RETRIEVABLE` (HTTP 409)."

    Design: Corner/errors/retrieval_on_draft_asset_not_retrievable
    """
    staff = create_staff_member()
    asset = create_asset()  # METADATA_DRAFT
    res = api.create_retrieval_request(
        create_retrieval_request_payload(
            asset["id"], staff["id"], purpose="INTERNAL_REVIEW"),
        make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_ASSET_NOT_RETRIEVABLE)


def test_broadcast_purpose_blocked_when_restricted(api):
    """PRD §3.6: "The purpose gate checks the asset's current `rights_posture`: a
    `BROADCAST` purpose requires `CLEARED`; `INTERNAL_REVIEW` and `EXHIBITION` accept
    either `CLEARED` or `RESTRICTED`; an `EXPIRED` posture rejects every purpose — any
    failure is `ERR_RIGHTS_EXPIRED_FOR_PURPOSE` (HTTP 422)."

    Design: Corner/errors/broadcast_purpose_blocked_when_restricted
    """
    staff = create_staff_member()
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"], restriction_flags=["EDITORIAL_ONLY"])
    assert get_asset(asset["id"])["rights_posture"] == "RESTRICTED"

    res = api.create_retrieval_request(
        create_retrieval_request_payload(asset["id"], staff["id"], purpose="BROADCAST"),
        make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_RIGHTS_EXPIRED_FOR_PURPOSE)

    ok = validate_success(api.create_retrieval_request(
        create_retrieval_request_payload(
            asset["id"], staff["id"], purpose="INTERNAL_REVIEW"),
        make_requester_headers(staff["id"])), 201)
    assert ok["status"] == "SUBMITTED"


# ─── delivery deadline vs rights window (Difficulty x2) ──

def test_delivery_deadline_at_rights_window_end_rejected(api):
    """PRD §3.6: "for `BROADCAST` requests it must also fall strictly before the
    `window_end` of every effective rights grant the delivery would rely on — a deadline
    exactly equal to a grant's window end is already beyond the window, since windows
    are end-exclusive, and is rejected with `ERR_DELIVERY_BEYOND_RIGHTS_WINDOW`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/delivery_deadline_at_rights_window_end
    """
    staff = create_staff_member()
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"], window_start="2026-01-01T00:00:00Z",
                        window_end="2026-09-01T00:00:00Z")
    res = api.create_retrieval_request(
        create_retrieval_request_payload(
            asset["id"], staff["id"], purpose="BROADCAST",
            requested_delivery_by="2026-09-01T00:00:00Z"),
        make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_DELIVERY_BEYOND_RIGHTS_WINDOW)


def test_delivery_deadline_one_second_before_window_end_allowed(api):
    """PRD §3.6: "for `BROADCAST` requests it must also fall strictly before the
    `window_end` of every effective rights grant the delivery would rely on — a deadline
    exactly equal to a grant's window end is already beyond the window, since windows
    are end-exclusive, and is rejected with `ERR_DELIVERY_BEYOND_RIGHTS_WINDOW`
    (HTTP 422)."
    PRD §3.6: "A successfully created request is `SUBMITTED` with `return_count` zero
    and no quoted fee."

    Design: Difficulty/boundary_precision_check/delivery_deadline_at_rights_window_end
    """
    staff = create_staff_member()
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"], window_start="2026-01-01T00:00:00Z",
                        window_end="2026-09-01T00:00:00Z")
    created = validate_success(api.create_retrieval_request(
        create_retrieval_request_payload(
            asset["id"], staff["id"], purpose="BROADCAST",
            requested_delivery_by="2026-08-31T23:59:59Z"),
        make_requester_headers(staff["id"])), 201)
    assert created["status"] == "SUBMITTED"


# ─── validation priority pair (Difficulty x2) ─────────

def test_retrieval_create_hold_gate_beats_deadline_gate(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed order and returns the first failure encountered." (safety
    and segregation are step 6; temporal rules are step 7.)
    PRD §3.6: "Creation is gated in §2.6 order."
    PRD §3.6: "The asset must be clear of legal holds (`ERR_ASSET_UNDER_LEGAL_HOLD`,
    HTTP 409)."
    PRD §3.6: "The deadline must lie strictly in the future (otherwise
    `ERR_DELIVERY_DEADLINE_PAST`, HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/retrieval_create_hold_safety_beats_deadline_temporal
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset()
    create_legal_hold(asset["id"], user_id="lc-1")

    res = api.create_retrieval_request(
        create_retrieval_request_payload(
            asset["id"], staff["id"], purpose="BROADCAST",
            requested_delivery_by="2026-07-01T00:00:00Z"),  # past the default clock
        make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_ASSET_UNDER_LEGAL_HOLD)


def test_retrieval_create_past_deadline_rejected(api):
    """PRD §3.6: "The deadline must lie strictly in the future (otherwise
    `ERR_DELIVERY_DEADLINE_PAST`, HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/retrieval_create_hold_safety_beats_deadline_temporal
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset()
    res = api.create_retrieval_request(
        create_retrieval_request_payload(
            asset["id"], staff["id"], purpose="BROADCAST",
            requested_delivery_by="2026-07-01T00:00:00Z"),
        make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_DELIVERY_DEADLINE_PAST)


# ─── expedite fee and cancel ownership ────────────────

def test_expedite_delivery_fee_doubles(api):
    """PRD §3.6: "a base of 0 cents for `ONLINE`, 500 cents for `NEARLINE`, or 1,500
    cents for `DEEP_ARCHIVE`, plus 10 cents for each whole gigabyte of `size_gb` rounded
    up; an `EXPEDITE` delivery tier then doubles the quoted figure."

    Design: Corner/endpoints/retrieval_expedite_fee_doubles
    """
    staff = create_staff_member()
    asset = _cleared_cataloged_asset(size_gb=40)
    run_migration(asset["id"], "NEARLINE")

    request = create_under_review_request(
        asset["id"], staff["id"], delivery_tier="EXPEDITE")
    approved = validate_success(api.approve_retrieval_request(request["id"], OFFICER), 200)
    assert approved["quoted_fee_cents"] == 1800, "(500 + ceil(40) x 10) x 2"
    assert approved["status"] == "STAGED", "NEARLINE is not DEEP_ARCHIVE"


def test_requester_cannot_cancel_others_request(api):
    """PRD §2.8: "A `Requester` may cancel only their own retrieval requests — the
    request's `requester_id` must equal `X-User-ID` — while an `AccessOfficer` may
    cancel any non-terminal request."
    PRD §2.8: "Each ownership violation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
    (HTTP 403)."

    Design: Corner/rbac/requester_cannot_cancel_others_request
    """
    staff_a = create_staff_member(full_name="A")
    staff_b = create_staff_member(full_name="B")
    asset = _cleared_cataloged_asset()
    request = create_retrieval_request(asset["id"], staff_a["id"])

    res = api.cancel_retrieval_request(request["id"], make_requester_headers(staff_b["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    cancelled = validate_success(api.cancel_retrieval_request(request["id"], OFFICER), 200)
    assert cancelled["status"] == "CANCELLED"
