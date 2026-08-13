"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient 2xx validator) so setup failures surface as
clear errors. Ownership-gated calls thread the real StaffMember.id through
make_requester_headers; segregation-gated calls use distinct opaque operator
ids via the make_* builders.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_staff_member_payload, create_ingest_batch_payload, create_asset_payload,
    create_proxy_rendition_payload, create_rights_grant_payload,
    create_legal_hold_payload, create_retention_policy_payload,
    create_disposal_order_payload, create_retrieval_request_payload,
    create_usage_event_payload, create_royalty_statement_payload,
    create_migration_job_payload, create_digitization_ticket_payload,
    create_workstation_payload,
)
from .test_users import (
    TEST_USERS, make_requester_headers, make_metadata_cataloger_headers,
    make_metadata_librarian_headers, make_archivist_lead_headers,
    make_legal_counsel_headers, make_access_officer_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
INGEST = TEST_USERS["ingest_coordinator_headers"]
LIBRARIAN = TEST_USERS["metadata_librarian_headers"]
ARCHIVIST = TEST_USERS["archivist_lead_headers"]
RIGHTS = TEST_USERS["rights_manager_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]
OFFICER = TEST_USERS["access_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
LAB = TEST_USERS["lab_technician_headers"]

DEFAULT_GRANT_WINDOW = ("2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")


# ─── Clock ─────────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Set the logical clock (SystemAdmin). Returns {current_utc}."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: simple creators ───────────────────────────

def create_staff_member(email: str = None, **overrides) -> dict:
    payload = create_staff_member_payload(**overrides)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_staff_member(payload, ADMIN))


def create_open_batch(**overrides) -> dict:
    return get_success_data(api_client.create_ingest_batch(
        create_ingest_batch_payload(**overrides), INGEST))


def create_asset(batch_id: str = None, **overrides) -> dict:
    """Create an asset (METADATA_DRAFT, ONLINE) in an OPEN batch.

    Creates its own batch when batch_id is omitted.
    """
    if batch_id is None:
        batch_id = create_open_batch()["id"]
    return get_success_data(api_client.create_asset(
        create_asset_payload(batch_id, **overrides), INGEST))


def get_asset(asset_id: str) -> dict:
    return get_success_data(api_client.get_asset(asset_id, ARCHIVIST))


def create_workstation(supported_formats=("BETACAM_SP",), **overrides) -> dict:
    payload = create_workstation_payload(**overrides)
    payload["supported_formats"] = list(supported_formats)
    return get_success_data(api_client.create_workstation(payload, ADMIN))


def create_retention_policy(media_type: str = "VIDEO", min_retention_years: int = 0) -> dict:
    return get_success_data(api_client.create_retention_policy(
        create_retention_policy_payload(
            media_type=media_type, min_retention_years=min_retention_years),
        ADMIN))


# ─── Tier 2: catalog pipeline progression ──────────────

def submit_metadata(asset_id: str, user_id: str = "cat-1") -> dict:
    return get_success_data(api_client.submit_metadata(
        asset_id, make_metadata_cataloger_headers(user_id)))


def approve_metadata(asset_id: str, user_id: str = "lib-1") -> dict:
    return get_success_data(api_client.metadata_approve(
        asset_id, make_metadata_librarian_headers(user_id)))


def create_cataloged_asset(submitter: str = "cat-1", approver: str = "lib-1",
                           **asset_overrides) -> dict:
    """Asset walked METADATA_DRAFT -> IN_REVIEW -> CATALOGED."""
    asset = create_asset(**asset_overrides)
    submit_metadata(asset["id"], user_id=submitter)
    return approve_metadata(asset["id"], user_id=approver)


def create_ready_proxy(asset_id: str, **overrides) -> dict:
    """Proxy rendition walked QUEUED -> RENDERING -> READY."""
    rendition = get_success_data(api_client.create_proxy_rendition(
        create_proxy_rendition_payload(asset_id, **overrides), LAB))
    get_success_data(api_client.claim_proxy(rendition["id"], LAB))
    return get_success_data(api_client.complete_proxy(rendition["id"], LAB))


def create_rights_grant(asset_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_rights_grant(
        create_rights_grant_payload(asset_id, **overrides), RIGHTS))


def create_archived_asset(archivist: str = "arch-1", **asset_overrides) -> dict:
    """Asset CATALOGED + READY proxy + one rights grant, then ARCHIVED.

    Returns the archive-response asset (its version is the post-archive one).
    """
    asset = create_cataloged_asset(**asset_overrides)
    create_ready_proxy(asset["id"])
    create_rights_grant(asset["id"])
    return get_success_data(api_client.archive_asset(
        asset["id"], make_archivist_lead_headers(archivist)))


# ─── Tier 3: legal holds ───────────────────────────────

def create_legal_hold(asset_id: str, user_id: str = "lc-1", **overrides) -> dict:
    return get_success_data(api_client.create_legal_hold(
        create_legal_hold_payload(asset_id, **overrides),
        make_legal_counsel_headers(user_id)))


def release_hold(hold_id: str, user_id: str = "lc-2") -> dict:
    return get_success_data(api_client.release_legal_hold(
        hold_id, make_legal_counsel_headers(user_id)))


# ─── Tier 4: migration jobs ────────────────────────────

def create_migration_job(asset_id: str, target_tier: str = "NEARLINE",
                         expected_asset_version: int = None, user_id: str = "arch-1",
                         **overrides) -> dict:
    if expected_asset_version is None:
        expected_asset_version = get_asset(asset_id)["version"]
    return get_success_data(api_client.create_migration_job(
        create_migration_job_payload(
            asset_id, expected_asset_version, target_tier=target_tier, **overrides),
        make_archivist_lead_headers(user_id)))


def run_migration(asset_id: str, target_tier: str, checksum: str = "ok",
                  complete_at: str = None) -> dict:
    """Create -> start -> (optionally move clock) -> complete. Returns job."""
    job = create_migration_job(asset_id, target_tier)
    get_success_data(api_client.start_migration_job(job["id"], LAB))
    if complete_at is not None:
        set_clock(complete_at)
    return get_success_data(api_client.complete_migration_job(
        job["id"], {"checksum_sha256": checksum}, LAB))


# ─── Tier 5: disposal pipeline ─────────────────────────

def create_disposal_order(asset_id: str, expected_asset_version: int = None,
                          scheduled_execution_date: str = "2026-08-02T00:00:00Z",
                          user_id: str = "arch-1", **overrides) -> dict:
    """Create a DRAFT disposal order. Reads the asset version when not given."""
    if expected_asset_version is None:
        expected_asset_version = get_asset(asset_id)["version"]
    return get_success_data(api_client.create_disposal_order(
        create_disposal_order_payload(
            asset_id, expected_asset_version,
            scheduled_execution_date=scheduled_execution_date, **overrides),
        make_archivist_lead_headers(user_id)))


def create_approved_disposal(archived_asset: dict = None, creator: str = "arch-1",
                             approver: str = "arch-2",
                             scheduled_execution_date: str = "2026-08-02T00:00:00Z",
                             media_type: str = "VIDEO",
                             **asset_overrides):
    """Asset ARCHIVED (with a 0-year retention policy for its media type) and a
    DisposalOrder walked DRAFT -> PENDING_APPROVAL -> APPROVED.

    Returns (asset_after_approve, order).
    """
    create_retention_policy(media_type, 0)
    if archived_asset is None:
        archived_asset = create_archived_asset(
            archivist=creator, media_type=media_type, **asset_overrides)
    order = create_disposal_order(
        archived_asset["id"],
        expected_asset_version=archived_asset["version"],
        scheduled_execution_date=scheduled_execution_date,
        user_id=creator)
    get_success_data(api_client.submit_disposal_order(
        order["id"], make_archivist_lead_headers(creator)))
    approved = get_success_data(api_client.approve_disposal_order(
        order["id"], make_archivist_lead_headers(approver)))
    return get_asset(archived_asset["id"]), approved


def create_disposed_asset(creator: str = "arch-1", approver: str = "arch-2",
                          **asset_overrides) -> dict:
    """Full lifecycle through DISPOSED (clock moved to the scheduled date)."""
    asset, order = create_approved_disposal(
        creator=creator, approver=approver, **asset_overrides)
    set_clock("2026-08-02T00:00:00Z")
    get_success_data(api_client.execute_disposal_order(
        order["id"], make_archivist_lead_headers(creator)))
    return get_asset(asset["id"])


# ─── Tier 6: retrieval requests ────────────────────────

def create_retrieval_request(asset_id: str, staff_id: str, **overrides) -> dict:
    """Create a SUBMITTED retrieval request as the owning Requester."""
    return get_success_data(api_client.create_retrieval_request(
        create_retrieval_request_payload(asset_id, staff_id, **overrides),
        make_requester_headers(staff_id)))


def create_under_review_request(asset_id: str, staff_id: str, **overrides) -> dict:
    request = create_retrieval_request(asset_id, staff_id, **overrides)
    return get_success_data(api_client.start_review(request["id"], OFFICER))


def create_staged_request(asset_id: str, staff_id: str,
                          approver: str = "ao-1", **overrides) -> dict:
    """SUBMITTED -> UNDER_REVIEW -> STAGED (non-DEEP_ARCHIVE asset)."""
    request = create_under_review_request(asset_id, staff_id, **overrides)
    return get_success_data(api_client.approve_retrieval_request(
        request["id"], make_access_officer_headers(approver)))


# ─── Tier 7: usage events & royalty statements ─────────

def create_usage_event(asset_id: str, staff_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_usage_event(
        create_usage_event_payload(asset_id, staff_id, **overrides),
        make_requester_headers(staff_id)))


def create_verified_usage_event(asset_id: str, staff_id: str, **overrides) -> dict:
    event = create_usage_event(asset_id, staff_id, **overrides)
    return get_success_data(api_client.verify_usage_event(event["id"], FINANCE))


def create_royalty_statement(rights_holder: str = "ACME",
                             period_start: str = "2026-07-01T00:00:00Z",
                             period_end: str = "2026-08-01T00:00:00Z",
                             **overrides) -> dict:
    return get_success_data(api_client.create_royalty_statement(
        create_royalty_statement_payload(
            rights_holder=rights_holder, period_start=period_start,
            period_end=period_end, **overrides),
        FINANCE))


# ─── Tier 8: digitization lab ──────────────────────────

def create_digitization_ticket(asset_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_digitization_ticket(
        create_digitization_ticket_payload(asset_id, **overrides), ARCHIVIST))


def drive_ticket_to_qc(ticket_id: str, workstation_id: str) -> dict:
    """Assign -> start -> submit-qc. Returns the QC_REVIEW ticket."""
    get_success_data(api_client.assign_digitization_ticket(
        ticket_id, {"workstation_id": workstation_id}, LAB))
    get_success_data(api_client.start_digitization_ticket(ticket_id, LAB))
    return get_success_data(api_client.submit_qc_digitization_ticket(ticket_id, LAB))
