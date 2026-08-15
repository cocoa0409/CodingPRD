"""Legal holds: placement cascades, release reconciliation, and hold gates."""
from test_helpers import (
    api_client,
    validate_success, validate_error, ApiErrorId,
    create_asset, create_cataloged_asset, create_archived_asset, create_rights_grant,
    create_legal_hold, release_hold, create_migration_job, get_asset,
    create_retention_policy, create_disposal_order, create_staff_member,
    create_under_review_request,
    create_retrieval_request_payload, create_migration_job_payload,
    make_archivist_lead_headers, make_requester_headers,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
OFFICER = TEST_USERS["access_officer_headers"]


def _walk_order_to_approved(asset):
    """Walk an ARCHIVED asset's disposal order to APPROVED (creator arch-1, approver arch-2)."""
    order = create_disposal_order(asset["id"], expected_asset_version=asset["version"],
                                  user_id="arch-1")
    validate_success(api_client.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    return validate_success(api_client.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)


def test_legal_hold_activation_depth3_cascade(api):
    """PRD §3.4: "Placing a hold cascades across the archive in the same transaction.
    The asset's `hold_status` becomes `HELD` and the asset's `version` increments by
    one. Any disposal order for the asset sitting in `PENDING_APPROVAL` or `APPROVED` is
    forced to `BLOCKED`, and if the blocked order was `APPROVED` — meaning it had
    already scheduled the asset — the asset's `catalog_status` reverts from
    `DISPOSAL_SCHEDULED` back to `ARCHIVED`."

    Design: Difficulty/transitive_cascade/legal_hold_activation_depth3_cascade
    """
    create_retention_policy("VIDEO", 0)
    asset = create_archived_asset()
    order = _walk_order_to_approved(asset)
    assert order["status"] == "APPROVED"
    assert get_asset(asset["id"])["catalog_status"] == "DISPOSAL_SCHEDULED"

    create_legal_hold(asset["id"], user_id="lc-1")

    asset_after = get_asset(asset["id"])
    assert asset_after["hold_status"] == "HELD"
    assert asset_after["catalog_status"] == "ARCHIVED", (
        "link 3: the order leaving APPROVED must revert the asset to ARCHIVED")
    order_after = validate_success(api.get_disposal_order(order["id"], ARCHIVIST), 200)
    assert order_after["status"] == "BLOCKED", (
        "link 2: the APPROVED order must be forced to BLOCKED by the hold")


def test_legal_hold_pauses_queued_migration(api):
    """PRD §3.4: "Any migration job for the asset sitting in `QUEUED` is paused to
    `HOLD_PAUSED`."
    PRD §3.4: "Placing a hold cascades across the archive in the same transaction. The
    asset's `hold_status` becomes `HELD`".

    Design: Difficulty/transitive_cascade/legal_hold_activation_depth3_cascade
    """
    create_retention_policy("VIDEO", 0)
    asset = create_archived_asset()
    job = create_migration_job(asset["id"], "NEARLINE")
    assert job["status"] == "QUEUED"
    order = create_disposal_order(asset["id"], user_id="arch-1")
    validate_success(api.submit_disposal_order(
        order["id"], make_archivist_lead_headers("arch-1")), 200)
    validate_success(api.approve_disposal_order(
        order["id"], make_archivist_lead_headers("arch-2")), 200)

    create_legal_hold(asset["id"], user_id="lc-1")

    job_after = validate_success(api.get_migration_job(job["id"], ARCHIVIST), 200)
    assert job_after["status"] == "HOLD_PAUSED"
    order_after = validate_success(api.get_disposal_order(order["id"], ARCHIVIST), 200)
    assert order_after["status"] == "BLOCKED"
    assert get_asset(asset["id"])["hold_status"] == "HELD"


def test_retrieval_approve_blocked_under_hold_then_unblocked(api):
    """PRD §3.4: "retrieval-request creation and approval are rejected with
    `ERR_ASSET_UNDER_LEGAL_HOLD` (HTTP 409)".
    PRD §3.4: "When the released hold was the last `ACTIVE` hold on the asset, two
    further cascades fire: the asset's `hold_status` returns to `CLEAR`".

    Design: Difficulty/cross_entity_state_dependency/retrieval_approve_gated_by_asset_hold
    """
    staff = create_staff_member()
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"])
    request = create_under_review_request(asset["id"], staff["id"])

    hold = create_legal_hold(asset["id"], user_id="lc-1")
    res = api.approve_retrieval_request(request["id"], OFFICER)
    validate_error(res, ApiErrorId.ERR_ASSET_UNDER_LEGAL_HOLD)

    release_hold(hold["id"], user_id="lc-2")
    approved = validate_success(
        api.approve_retrieval_request(request["id"], OFFICER), 200)
    assert approved["status"] == "STAGED"


def test_retrieval_create_blocked_under_hold(api):
    """PRD §3.4: "An active hold gates five operations elsewhere in this document:
    disposal-order approve, execute, and resubmit, and migration-job creation are
    rejected with `ERR_LEGAL_HOLD_ACTIVE` (HTTP 409) while the asset is `HELD`;
    retrieval-request creation and approval are rejected with
    `ERR_ASSET_UNDER_LEGAL_HOLD` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/retrieval_approve_gated_by_asset_hold
    """
    staff = create_staff_member()
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"])
    create_legal_hold(asset["id"], user_id="lc-1")

    res = api.create_retrieval_request(
        create_retrieval_request_payload(asset["id"], staff["id"]),
        make_requester_headers(staff["id"]))
    validate_error(res, ApiErrorId.ERR_ASSET_UNDER_LEGAL_HOLD)


def test_hold_release_unpauses_queued_migration(api):
    """PRD §3.4: "When the released hold was the last `ACTIVE` hold on the asset, two
    further cascades fire: the asset's `hold_status` returns to `CLEAR`, and every
    migration job paused in `HOLD_PAUSED` for that asset resumes to `QUEUED`."

    Design: Corner/cross_cutting_layers/hold_release_unpauses_queued_migration
    """
    asset = create_asset()
    job = create_migration_job(asset["id"], "NEARLINE")
    h1 = create_legal_hold(asset["id"], user_id="lc-1", matter_reference="M1")
    create_legal_hold(asset["id"], user_id="lc-2", matter_reference="M2")

    mid_job = validate_success(api.get_migration_job(job["id"], ARCHIVIST), 200)
    assert mid_job["status"] == "HOLD_PAUSED"

    release_hold(h1["id"], user_id="lc-3")
    mid = validate_success(api.get_migration_job(job["id"], ARCHIVIST), 200)
    assert mid["status"] == "HOLD_PAUSED", "a second ACTIVE hold must keep the job paused"
    assert get_asset(asset["id"])["hold_status"] == "HELD"

    holds = validate_success(api.list_legal_holds(
        ARCHIVIST, params={"asset_id": asset["id"], "status": "ACTIVE"}), 200)
    assert len(holds) == 1
    release_hold(holds[0]["id"], user_id="lc-4")

    end = validate_success(api.get_migration_job(job["id"], ARCHIVIST), 200)
    assert end["status"] == "QUEUED", "releasing the last hold must resume the job"
    assert get_asset(asset["id"])["hold_status"] == "CLEAR"


def test_migration_create_on_held_asset_rejected(api):
    """PRD §3.8: "The asset must not be `DISPOSED` (`ERR_ASSET_DISPOSED`, HTTP 409),
    must be clear of legal holds (`ERR_LEGAL_HOLD_ACTIVE`, HTTP 409), and must not
    already have another migration job `IN_PROGRESS` (`ERR_JOB_IN_PROGRESS_EXISTS`,
    HTTP 409)."

    Design: Corner/errors/migration_create_on_held_asset_rejected
    """
    asset = create_asset()
    create_legal_hold(asset["id"], user_id="lc-1")
    v_now = get_asset(asset["id"])["version"]
    res = api.create_migration_job(
        create_migration_job_payload(asset["id"], v_now, target_tier="NEARLINE"),
        ARCHIVIST)
    validate_error(res, ApiErrorId.ERR_LEGAL_HOLD_ACTIVE)
