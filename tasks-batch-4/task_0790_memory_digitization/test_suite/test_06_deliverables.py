"""Deliverable generation and download: the CLOUD download limit, the stale
optimistic-concurrency guard, the non-CLOUD block, and expiry."""
from test_helpers import (
    ApiErrorId, validate_error, validate_success,
    download, set_clock, make_customer_headers,
    setup_generated_artifact,
)


# ===========================================================================
# boundary_precision_check / download_limit_boundary_at_three
# ===========================================================================
def test_fourth_download_rejected_at_limit(api):
    """PRD §3.6: "The download is also allowed only while `download_count` is
    below the limit of 3 downloads per artifact; a further attempt is refused
    with `ERR_DOWNLOAD_LIMIT_REACHED` (HTTP 409)."

    Three downloads succeed (download_count reaches 3); the fourth is refused.

    Design: Difficulty/boundary_precision_check/download_limit_boundary_at_three
    """
    art = setup_generated_artifact(api, output_type="CLOUD", customer_email="dl-lim1@x.com")
    for _ in range(3):
        download(api, art["artifact_id"], art["customer_id"])
    resp = api.download_artifact(art["artifact_id"], make_customer_headers(art["customer_id"]))
    validate_error(resp, ApiErrorId.ERR_DOWNLOAD_LIMIT_REACHED)
    got = validate_success(api.get_output_artifact(
        art["artifact_id"], make_customer_headers(art["customer_id"])))
    assert got["download_count"] == 3, got


def test_third_download_succeeds_at_boundary(api):
    """PRD §3.6: "A successful download increments the artifact's
    `download_count` by one and records an immutable `DownloadEvent` carrying its
    `output_artifact_id`, a `sequence_number` equal to the new download count
    (its 1-based ordinal against the artifact), and a `downloaded_at` set to the
    current logical clock instant."

    The third download (the last permitted one) succeeds, taking download_count
    to 3 and stamping sequence_number 3.

    Design: Difficulty/boundary_precision_check/download_limit_boundary_at_three
    """
    art = setup_generated_artifact(api, output_type="CLOUD", customer_email="dl-lim2@x.com")
    download(api, art["artifact_id"], art["customer_id"])
    download(api, art["artifact_id"], art["customer_id"])
    third = download(api, art["artifact_id"], art["customer_id"])
    assert third["sequence_number"] == 3, third
    got = validate_success(api.get_output_artifact(
        art["artifact_id"], make_customer_headers(art["customer_id"])))
    assert got["download_count"] == 3, got


# ===========================================================================
# cross_cutting_complexity_layers / occ_stale_order_version_conflict (corner)
# ===========================================================================
def test_second_generation_with_stale_version_rejected(api):
    """PRD §2.7: "If `expected_order_version` does not equal the order's current
    `version`, the request is rejected with `ERR_STALE_ORDER_VERSION` (HTTP
    412)."
    PRD §3.6: "Generating a new artifact for an order supersedes any prior
    deliverable: any existing `AVAILABLE` artifact of that order is moved to
    `REVOKED`."

    The first generation bumped the order version, so replaying the original
    (now stale) expected_order_version is refused.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_conflict
    """
    art = setup_generated_artifact(api, output_type="CLOUD", customer_email="occ@x.com")
    resp = api.create_output_artifact(
        art["order_id"],
        {"output_type": "CLOUD", "expected_order_version": art["stale_version"]},
        make_customer_headers(art["customer_id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION)


# ===========================================================================
# validations / download_non_cloud_returns_not_downloadable (corner)
# ===========================================================================
def test_download_non_cloud_artifact_rejected(api):
    """PRD §3.6: "A download is permitted only when the artifact's `output_type`
    is `CLOUD`; a download attempt on a `USB` or `DVD` artifact is rejected with
    `ERR_NOT_DOWNLOADABLE` (HTTP 409)."

    Design: Corner/validations/download_non_cloud_returns_not_downloadable
    """
    art = setup_generated_artifact(api, output_type="USB", customer_email="nd@x.com")
    resp = api.download_artifact(art["artifact_id"], make_customer_headers(art["customer_id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_DOWNLOADABLE)


# ===========================================================================
# validations / download_after_expiry_returns_download_expired (corner)
# ===========================================================================
def test_download_after_expiry_rejected(api):
    """PRD §3.6: "The download is allowed only while the logical clock is strictly
    before the artifact's `expires_at`; if the clock has reached or passed
    `expires_at`, the download is refused with `ERR_DOWNLOAD_EXPIRED` (HTTP 409)
    and the artifact is lazily moved from `AVAILABLE` to `EXPIRED` at that
    moment."
    PRD §3.6: "sets its `expires_at` to the artifact's `created_at` plus 30
    days."

    An artifact generated at the 2026-03-01 default clock expires 2026-03-31;
    downloading after the clock advances to 2026-05-01 is refused.

    Design: Corner/validations/download_after_expiry_returns_download_expired
    """
    art = setup_generated_artifact(api, output_type="CLOUD", customer_email="de@x.com")
    set_clock(api, "2026-05-01T00:00:00Z")
    resp = api.download_artifact(art["artifact_id"], make_customer_headers(art["customer_id"]))
    validate_error(resp, ApiErrorId.ERR_DOWNLOAD_EXPIRED)
