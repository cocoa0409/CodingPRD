"""Asset catalog lifecycle: parallel state dimensions and the recatalog rework cycle."""
from test_helpers import (
    validate_success,
    create_archived_asset, run_migration, get_asset,
    make_metadata_librarian_headers,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]


def _archived_then_migrated_to_nearline():
    """Asset ARCHIVED (grant + READY proxy on record), then migrated ONLINE->NEARLINE."""
    asset = create_archived_asset()
    run_migration(asset["id"], "NEARLINE")
    return asset


def test_recatalog_cycle_leaves_storage_tier_untouched(api):
    """PRD §3.1: "recataloging moves `ARCHIVED` back to `IN_REVIEW` and clears
    `metadata_submitted_by_user_id` so that the fresh review round starts without a
    pinned submitter."
    PRD §3.8: "The catalog lifecycle of §3.1 never changes the tier, and tier migration
    never changes `catalog_status`; the only writer of `storage_tier` is a completed
    migration job."
    PRD §3.1: "Approving moves `IN_REVIEW` to `CATALOGED`".

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_and_recatalog_cycle
    """
    asset = _archived_then_migrated_to_nearline()
    assert get_asset(asset["id"])["storage_tier"] == "NEARLINE"

    reopened = validate_success(api.recatalog_asset(asset["id"], ARCHIVIST), 200)
    assert reopened["catalog_status"] == "IN_REVIEW"

    # Fresh review round: recatalog lands in IN_REVIEW with the submitter cleared,
    # so the approve step completes the rework cycle (submit is only legal from
    # METADATA_DRAFT per PRD §3.1).
    cataloged = validate_success(api.metadata_approve(
        asset["id"], make_metadata_librarian_headers("lib-1")), 200)
    assert cataloged["catalog_status"] == "CATALOGED"
    assert cataloged["storage_tier"] == "NEARLINE", (
        "the tier dimension must be unaffected by the catalog rework cycle")


def test_recatalog_clears_pinned_submitter(api):
    """PRD §3.1: "recataloging moves `ARCHIVED` back to `IN_REVIEW` and clears
    `metadata_submitted_by_user_id` so that the fresh review round starts without a
    pinned submitter."
    PRD §3.8: "The catalog lifecycle of §3.1 never changes the tier".

    Design: Difficulty/non_linear_state_machine/asset_parallel_dimensions_and_recatalog_cycle
    """
    asset = _archived_then_migrated_to_nearline()

    reopened = validate_success(api.recatalog_asset(asset["id"], ARCHIVIST), 200)
    assert reopened["catalog_status"] == "IN_REVIEW"
    assert reopened["metadata_submitted_by_user_id"] is None, (
        "recatalog must clear the pinned submitter for the fresh review round")
    assert reopened["storage_tier"] == "NEARLINE"
