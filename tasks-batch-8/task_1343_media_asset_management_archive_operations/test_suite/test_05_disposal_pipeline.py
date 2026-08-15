"""Disposal pipeline: retention gates, OCC pinning, approval safeguards, execution
cascades, withdrawal compensation, and BLOCKED resubmission."""
from test_helpers import (
    api_client,
    validate_success, validate_error, ApiErrorId,
    create_asset, create_archived_asset, create_rights_grant, create_ready_proxy,
    create_cataloged_asset, create_legal_hold, release_hold, create_migration_job,
    create_digitization_ticket, create_disposal_order, create_retention_policy,
    create_staff_member, create_under_review_request, get_asset, set_clock,
    create_disposal_order_payload,
    make_archivist_lead_headers,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
CATALOGER = TEST_USERS["metadata_cataloger_headers"]
ADMIN = TEST_USERS["system_admin_headers"]


def _archive_asset(media_type="VIDEO", archivist="arch-1", **overrides):
    return create_archived_asset(archivist=archivist, media_type=media_type, **overrides)


# ─── execution cascade (Difficulty x2) ────────────────

def test_disposal_execution_disposes_asset_and_cancels_request(api):
    """PRD §3.5: "Execution is allowed only once the logical clock has reached the
    order's `scheduled_execution_date` — earlier execution is rejected with
    `ERR_DISPOSAL_NOT_YET_DUE` (HTTP 422)".
    PRD §3.5: "Executing moves the order to the terminal `EXECUTED` state and the asset
    from `DISPOSAL_SCHEDULED` to `DISPOSED`, and the disposal cascades outward: every
    retrieval request for the asset in `SUBMITTED`, `UNDER_REVIEW`, `RECALLING`, or
    `STAGED` is cancelled to `CANCELLED`".

    Design: Difficulty/transitive_cascade/disposal_execution_depth2_cascade
    """
    create_retention_policy("VIDEO", 0)
    staff = create_staff_member()
    asset = _archive_asset()
    request = create_under_review_request(asset["id"], staff["id"])
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    validate_success(api.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)

    set_clock("2026-08-02T00:00:00Z")  # exactly the scheduled date: allowed
    executed = validate_success(api.execute_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    assert executed["status"] == "EXECUTED"

    asset_after = get_asset(asset["id"])
    assert asset_after["catalog_status"] == "DISPOSED", "link 1: asset disposed"
    request_after = validate_success(api.get_retrieval_request(request["id"], ARCHIVIST), 200)
    assert request_after["status"] == "CANCELLED", (
        "link 2: the in-flight request must be cancelled by the disposal")


def test_disposal_execution_cancels_migrations_and_tickets(api):
    """PRD §3.5: "Executing moves the order to the terminal `EXECUTED` state and the
    asset from `DISPOSAL_SCHEDULED` to `DISPOSED`, and the disposal cascades outward:
    every retrieval request for the asset in `SUBMITTED`, `UNDER_REVIEW`, `RECALLING`,
    or `STAGED` is cancelled to `CANCELLED`; every migration job for the asset in
    `QUEUED` or `HOLD_PAUSED` is cancelled to `CANCELLED`; and every digitization ticket
    for the asset in `QUEUED` or `ASSIGNED` is cancelled to `CANCELLED`."

    Design: Difficulty/transitive_cascade/disposal_execution_depth2_cascade
    """
    create_retention_policy("VIDEO", 0)
    staff = create_staff_member()
    asset = _archive_asset(format_class="BETACAM_SP")
    job = create_migration_job(asset["id"], "NEARLINE")
    ticket = create_digitization_ticket(
        asset["id"], scheduled_start="2026-08-10T00:00:00Z",
        scheduled_end="2026-08-10T02:00:00Z")
    request = create_under_review_request(asset["id"], staff["id"])

    v_now = get_asset(asset["id"])["version"]
    order = create_disposal_order(asset["id"], expected_asset_version=v_now,
                                  user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    validate_success(api.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)

    set_clock("2026-08-02T00:00:00Z")
    executed = validate_success(api.execute_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    assert executed["status"] == "EXECUTED"

    assert get_asset(asset["id"])["catalog_status"] == "DISPOSED"
    job_after = validate_success(api.get_migration_job(job["id"], ARCHIVIST), 200)
    assert job_after["status"] == "CANCELLED", "QUEUED migration must be cancelled"
    ticket_after = validate_success(api.get_digitization_ticket(ticket["id"], ARCHIVIST), 200)
    assert ticket_after["status"] == "CANCELLED", "QUEUED ticket must be cancelled"
    request_after = validate_success(api.get_retrieval_request(request["id"], ARCHIVIST), 200)
    assert request_after["status"] == "CANCELLED"


# ─── approve/withdraw compensation (Difficulty x2) ────

def test_approve_then_withdraw_conserves_catalog_status(api):
    """PRD §3.5: "A successful approval records `approved_by_user_id` and moves the
    asset's `catalog_status` from `ARCHIVED` to `DISPOSAL_SCHEDULED`".
    PRD §3.5: "Withdrawing a `DRAFT` order leaves the asset untouched; withdrawing an
    `APPROVED` order reverts the asset from `DISPOSAL_SCHEDULED` back to `ARCHIVED`.
    `WITHDRAWN` is terminal in both cases."

    Design: Difficulty/compensating_invariant/disposal_approve_withdraw_conserves_catalog_status
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    validate_success(api.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)
    assert get_asset(asset["id"])["catalog_status"] == "DISPOSAL_SCHEDULED"

    withdrawn = validate_success(api.withdraw_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    assert withdrawn["status"] == "WITHDRAWN"

    asset_after = get_asset(asset["id"])
    assert asset_after["catalog_status"] == "ARCHIVED", (
        "invariant: the approve+withdraw pair must leave zero catalog drift")
    assert asset_after["hold_status"] == "CLEAR"


def test_withdraw_draft_requires_creator_and_leaves_asset_untouched(api):
    """PRD §3.5: "Only the `ArchivistLead` whose `X-User-ID` equals the order's
    `created_by_user_id` may withdraw (otherwise `ERR_INSUFFICIENT_PERMISSIONS`,
    HTTP 403), and only from `DRAFT` or `APPROVED` (otherwise
    `ERR_DISPOSAL_ORDER_NOT_WITHDRAWABLE`, HTTP 409). Withdrawing a `DRAFT` order leaves
    the asset untouched".

    Design: Difficulty/compensating_invariant/disposal_approve_withdraw_conserves_catalog_status
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")

    res = api.withdraw_disposal_order(order["id"], make_archivist_lead_headers("arch-2"))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    withdrawn = validate_success(api.withdraw_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_asset(asset["id"])["catalog_status"] == "ARCHIVED", (
        "withdrawing a DRAFT order must leave the asset untouched")


# ─── validation priority pair (Difficulty x2) ─────────

def test_disposal_approve_state_gate_beats_hold_gate_draft(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed order and returns the first failure encountered." (state
    preconditions are step 4; safety and segregation are step 6.)
    PRD §3.5: "The order must be in `PENDING_APPROVAL` (otherwise
    `ERR_DISPOSAL_ORDER_NOT_PENDING`, HTTP 409); the asset's `hold_status` must be
    `CLEAR` (otherwise `ERR_LEGAL_HOLD_ACTIVE`)".

    Design: Difficulty/priority_pair_validation_conflict/disposal_approve_state_beats_hold_safety
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")  # stays DRAFT
    create_legal_hold(asset["id"], user_id="lc-1")

    res = api.approve_disposal_order(order["id"], make_archivist_lead_headers("arch-2"))
    validate_error(res, ApiErrorId.ERR_DISPOSAL_ORDER_NOT_PENDING)


def test_disposal_approve_state_gate_beats_hold_gate_rejected(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed order and returns the first failure encountered."
    PRD §3.5: "Rejection is the sibling exit from `PENDING_APPROVAL`: it records the
    supplied `reason` in `reject_reason`, moves the order to the terminal `REJECTED`
    state, and leaves the asset untouched."

    Design: Difficulty/priority_pair_validation_conflict/disposal_approve_state_beats_hold_safety
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    rejected = validate_success(api.reject_disposal_order(
        order["id"], {"reason": "no"}, make_archivist_lead_headers("arch-2")), 200)
    assert rejected["status"] == "REJECTED"
    create_legal_hold(asset["id"], user_id="lc-1")

    res = api.approve_disposal_order(order["id"], make_archivist_lead_headers("arch-2"))
    validate_error(res, ApiErrorId.ERR_DISPOSAL_ORDER_NOT_PENDING)


# ─── version pinning and OCC ──────────────────────────

def test_disposal_version_drift_on_approve(api):
    """PRD §3.5: "the asset's current `version` must still equal the order's
    `pinned_asset_version` — any drift, such as a metadata edit or a migration
    completion since the order was created, is rejected with
    `ERR_ASSET_VERSION_DRIFT` (HTTP 409)".
    PRD §2.5: "The `version` is an integer that increments by exactly one on every
    mutation of the resource".

    Design: Corner/validations/disposal_version_drift_on_approve
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    # recatalog mutates the asset (ARCHIVED -> IN_REVIEW), bumping its version
    validate_success(api.recatalog_asset(asset["id"], ARCHIVIST), 200)

    res = api.approve_disposal_order(order["id"], make_archivist_lead_headers("arch-2"))
    validate_error(res, ApiErrorId.ERR_ASSET_VERSION_DRIFT)


def test_occ_disposal_create_stale_version_rejected(api):
    """PRD §2.7: "If the asset's current `version` no longer equals the supplied value —
    because another writer edited the asset's metadata, placed a hold on it, or created
    another pinned write against it in the meantime — the request is rejected with
    `ERR_STALE_ASSET_VERSION` (HTTP 412)."
    PRD §2.5: "The `version` is an integer that increments by exactly one on every
    mutation of the resource".

    Design: Corner/cross_cutting_layers/occ_disposal_create_stale_version_rejected
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    v_arch = asset["version"]
    # Advance the asset version via recatalog -> approve -> archive
    validate_success(api.recatalog_asset(asset["id"], ARCHIVIST), 200)
    validate_success(api.metadata_approve(
        asset["id"], TEST_USERS["metadata_librarian_headers"]), 200)
    validate_success(api.archive_asset(asset["id"], ARCHIVIST), 200)

    stale = api.create_disposal_order(
        create_disposal_order_payload(asset["id"], v_arch),
        make_archivist_lead_headers("arch-1"))
    validate_error(stale, ApiErrorId.ERR_STALE_ASSET_VERSION)

    v_fresh = get_asset(asset["id"])["version"]
    assert v_fresh > v_arch
    order = validate_success(api.create_disposal_order(
        create_disposal_order_payload(asset["id"], v_fresh),
        make_archivist_lead_headers("arch-1")), 201)
    assert order["status"] == "DRAFT"


def test_disposal_resubmit_repins_version_after_hold_release(api):
    """PRD §3.5: "resubmission requires the order to be in `BLOCKED` (otherwise
    `ERR_DISPOSAL_ORDER_NOT_BLOCKED`, HTTP 409) and the asset's `hold_status` to be
    `CLEAR` (otherwise `ERR_LEGAL_HOLD_ACTIVE`), returns the order to
    `PENDING_APPROVAL`, and re-pins `pinned_asset_version` to the asset's current
    `version`, discarding the stale pin."
    PRD §3.4: "Disposal orders sitting in `BLOCKED` are deliberately not resurrected by
    release — they stay `BLOCKED` until an archivist manually resubmits them".

    Design: Corner/endpoints/disposal_resubmit_repins_version_after_hold_release
    """
    create_retention_policy("VIDEO", 0)
    asset = _archive_asset()
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    validate_success(api.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)

    hold = create_legal_hold(asset["id"], user_id="lc-1")
    blocked = validate_success(api.get_disposal_order(order["id"], ARCHIVIST), 200)
    assert blocked["status"] == "BLOCKED"
    release_hold(hold["id"], user_id="lc-2")

    resubmitted = validate_success(api.resubmit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    assert resubmitted["status"] == "PENDING_APPROVAL"
    assert resubmitted["pinned_asset_version"] == get_asset(asset["id"])["version"], (
        "resubmit must re-pin to the current asset version")

    approved = validate_success(api.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)
    assert approved["status"] == "APPROVED", "the re-pinned version must pass the drift check"


# ─── retention gates ──────────────────────────────────

def test_retention_default_seven_year_boundary(api):
    """PRD §3.5: "when no policy row exists for an asset's media type, a default of 7
    years applies."
    PRD §2.10: "Retention years are always 365-day years."
    PRD §3.5: "Eligibility is inclusive at the boundary: an asset whose eligibility
    instant equals now is eligible. Creating a disposal order before that instant is
    rejected with `ERR_RETENTION_NOT_ELAPSED` (HTTP 422)".

    Boundary arithmetic per the PRD formula (created_at + 7 x 365 days):
    an AUDIO asset created at the default clock 2026-08-01T00:00:00Z becomes eligible
    at exactly 2033-07-30T00:00:00Z (2033-07-29 is before; the boundary is inclusive).

    Design: Corner/calculations/retention_default_seven_year_boundary
    """
    asset = _archive_asset(media_type="AUDIO", format_class="DIGITAL_FILE")
    assert asset["created_at"].startswith("2026-08-01T00:00:00")

    set_clock("2033-07-29T00:00:00Z")  # one day before created_at + 7*365 days
    v_early = get_asset(asset["id"])["version"]
    early = api.create_disposal_order(
        create_disposal_order_payload(
            asset["id"], v_early, scheduled_execution_date="2033-08-05T00:00:00Z"),
        make_archivist_lead_headers("arch-1"))
    validate_error(early, ApiErrorId.ERR_RETENTION_NOT_ELAPSED)

    set_clock("2033-07-30T00:00:00Z")  # exactly created_at + 7*365 days: eligible (>=)
    order = validate_success(api.create_disposal_order(
        create_disposal_order_payload(
            asset["id"], v_early, scheduled_execution_date="2033-08-05T00:00:00Z"),
        make_archivist_lead_headers("arch-1")), 201)
    assert order["status"] == "DRAFT"


def test_disposal_override_bypasses_retention_with_reason(api):
    """PRD §3.5: "Creating a disposal order before that instant is rejected with
    `ERR_RETENTION_NOT_ELAPSED` (HTTP 422) unless the caller sets `retention_override`
    to true, which skips the elapsed check entirely; an override without a justification
    is a malformed request, so `override_reason` — null by default — is required
    whenever `retention_override` is true, and its absence is rejected with
    `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/endpoints/disposal_override_bypasses_retention_with_reason
    """
    # No VIDEO retention policy: the 7-year default applies and has not elapsed.
    asset = _archive_asset()
    v_arch = asset["version"]

    no_reason = api.create_disposal_order(
        create_disposal_order_payload(asset["id"], v_arch, retention_override=True),
        make_archivist_lead_headers("arch-1"))
    validate_error(no_reason, ApiErrorId.ERR_INVALID_REQUEST)

    order = validate_success(api.create_disposal_order(
        create_disposal_order_payload(
            asset["id"], v_arch, retention_override=True, override_reason="court order"),
        make_archivist_lead_headers("arch-1")), 201)
    assert order["status"] == "DRAFT"
    assert order["retention_override"] is True
