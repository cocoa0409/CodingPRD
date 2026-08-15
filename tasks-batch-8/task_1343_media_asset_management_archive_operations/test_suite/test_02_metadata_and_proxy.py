"""Metadata submission gates, terminal-state lockdown, and the proxy retry budget."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_asset_payload, create_proxy_rendition_payload,
    create_open_batch, create_asset, create_cataloged_asset, create_disposed_asset,
    create_rights_grant, submit_metadata,
    TEST_USERS,
)

ARCHIVIST = TEST_USERS["archivist_lead_headers"]
CATALOGER = TEST_USERS["metadata_cataloger_headers"]
LIBRARIAN = TEST_USERS["metadata_librarian_headers"]
LAB = TEST_USERS["lab_technician_headers"]
INGEST = TEST_USERS["ingest_coordinator_headers"]


def test_submit_metadata_incomplete_then_complete(api):
    """PRD §3.1: "The submission is completeness-gated: `description` must be
    non-empty, `keywords` must contain at least one entry, and `content_rating` must be
    something other than `NR` (one of `G`, `PG`, `PG13`, `R`); a shortfall on any of the
    three is rejected with `ERR_METADATA_INCOMPLETE` (HTTP 422)."
    PRD §3.1: "a `MetadataCataloger` may patch `title`, `description`, `keywords`,
    `content_rating`, and `rights_holder`, and each successful edit increments the
    asset's `version`".

    Design: Corner/validations/metadata_incomplete_submit_rejected
    """
    batch = create_open_batch()
    asset = create_asset(batch["id"], keywords=[], content_rating="NR")
    res = api.submit_metadata(asset["id"], CATALOGER)
    validate_error(res, ApiErrorId.ERR_METADATA_INCOMPLETE)

    validate_success(api.patch_asset(
        asset["id"], {"keywords": ["k"], "content_rating": "PG"}, CATALOGER), 200)
    submitted = validate_success(api.submit_metadata(asset["id"], CATALOGER), 200)
    assert submitted["catalog_status"] == "IN_REVIEW"


def test_disposed_asset_rejects_submit_metadata(api):
    """PRD §3.1: "Submitting metadata for review moves the asset from `METADATA_DRAFT`
    to `IN_REVIEW` ... Attempting it from any other state is rejected with
    `ERR_INVALID_CATALOG_TRANSITION` (HTTP 409)."
    PRD §3.1: "A freshly ingested asset has `catalog_status` `METADATA_DRAFT`".

    Design: Corner/state_machines/asset_initial_state_and_terminal_lockdown
    """
    fresh = create_asset()
    assert fresh["catalog_status"] == "METADATA_DRAFT"

    disposed = create_disposed_asset()
    assert disposed["catalog_status"] == "DISPOSED"
    res = api.submit_metadata(disposed["id"], CATALOGER)
    validate_error(res, ApiErrorId.ERR_INVALID_CATALOG_TRANSITION)


def test_proxy_retry_budget_exhausted_at_cap(api):
    """PRD §3.2: "The retry budget is capped at 3 — attempting a retry when
    `retry_count` has already reached the cap is rejected with
    `ERR_RETRY_BUDGET_EXHAUSTED` (HTTP 409), and attempting it from any state other than
    `FAILED` is rejected with `ERR_PROXY_NOT_FAILED` (HTTP 409)."

    Design: Corner/state_machines/proxy_retry_budget_exhausted_at_cap
    """
    asset = create_asset()
    rendition = validate_success(api.create_proxy_rendition(
        create_proxy_rendition_payload(asset["id"]), LAB), 201)
    rid = rendition["id"]
    for round_no in (1, 2, 3):
        validate_success(api.claim_proxy(rid, LAB), 200)
        failed = validate_success(api.fail_proxy(rid, {"reason": f"f{round_no}"}, LAB), 200)
        assert failed["status"] == "FAILED"
        retried = validate_success(api.retry_proxy(rid, LAB), 200)
        assert retried["status"] == "QUEUED"
        assert retried["retry_count"] == round_no
    validate_success(api.claim_proxy(rid, LAB), 200)
    validate_success(api.fail_proxy(rid, {"reason": "f4"}, LAB), 200)

    res = api.retry_proxy(rid, LAB)
    validate_error(res, ApiErrorId.ERR_RETRY_BUDGET_EXHAUSTED)

    final = validate_success(api.get_proxy_rendition(rid, LAB), 200)
    assert final["retry_count"] == 3
    assert final["status"] == "FAILED"


def test_archive_rejected_while_proxy_queued(api):
    """PRD §3.1: "Two readiness gates guard it: at least one proxy rendition for the
    asset must be in `READY` (otherwise `ERR_PROXY_NOT_READY`, HTTP 409), and at least
    one rights-grant row must exist for the asset in any status, active or revoked
    (otherwise `ERR_NO_RIGHTS_GRANT_ON_RECORD`, HTTP 409)."
    PRD §3.2: "the technician either completes the rendition — which mints a
    system-generated `proxy_url`, stamps `indexed_at` with the current logical time, and
    moves it to the terminal `READY` state".

    Design: Difficulty/cross_entity_state_dependency/archive_gated_by_proxy_ready
    """
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"])
    rendition = validate_success(api.create_proxy_rendition(
        create_proxy_rendition_payload(asset["id"]), LAB), 201)

    res = api.archive_asset(asset["id"], ARCHIVIST)
    validate_error(res, ApiErrorId.ERR_PROXY_NOT_READY)

    validate_success(api.claim_proxy(rendition["id"], LAB), 200)
    ready = validate_success(api.complete_proxy(rendition["id"], LAB), 200)
    assert ready["status"] == "READY"
    assert ready["proxy_url"], "completed rendition must carry a system-generated proxy_url"

    archived = validate_success(api.archive_asset(asset["id"], ARCHIVIST), 200)
    assert archived["catalog_status"] == "ARCHIVED"


def test_archive_rejected_while_proxy_rendering(api):
    """PRD §3.1: "Two readiness gates guard it: at least one proxy rendition for the
    asset must be in `READY` (otherwise `ERR_PROXY_NOT_READY`, HTTP 409)".
    PRD §3.2: "Claiming moves a rendition from `QUEUED` to `RENDERING`".

    Design: Difficulty/cross_entity_state_dependency/archive_gated_by_proxy_ready
    """
    asset = create_cataloged_asset()
    create_rights_grant(asset["id"])
    rendition = validate_success(api.create_proxy_rendition(
        create_proxy_rendition_payload(asset["id"]), LAB), 201)
    claimed = validate_success(api.claim_proxy(rendition["id"], LAB), 200)
    assert claimed["status"] == "RENDERING"

    res = api.archive_asset(asset["id"], ARCHIVIST)
    validate_error(res, ApiErrorId.ERR_PROXY_NOT_READY)

    validate_success(api.complete_proxy(rendition["id"], LAB), 200)
    archived = validate_success(api.archive_asset(asset["id"], ARCHIVIST), 200)
    assert archived["catalog_status"] == "ARCHIVED"
