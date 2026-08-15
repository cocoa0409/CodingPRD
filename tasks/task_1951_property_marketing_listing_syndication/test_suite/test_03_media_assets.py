"""Media asset curation: auto-primary, atomic primary swap, set-primary
validations, minimum photo resolution, and archive state gating (PRD §3.2)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_media_asset,
    create_media_asset_payload,
    create_agent, owner_headers, create_draft_listing, upload_photo,
    upload_and_ready_photo,
    TEST_USERS,
    ApiErrorId,
)

MC = TEST_USERS["marketing_coordinator_headers"]


def _ready_photos(api, listing_id):
    data = get_success_data(
        api.list_media_assets(listing_id, MC, params={"kind": "PHOTO", "status": "READY"}), 200)
    return data


class TestSinglePrimaryPhotoInvariant:
    def test_first_ready_photo_becomes_primary_automatically(self, api):
        """PRD §3.2: "When a `PHOTO` becomes ready and no other `READY` photo of the
        listing currently holds `is_primary` true, the system sets `is_primary` true
        on the newly ready asset — an automatic primary assignment."

        Design: Difficulty/compensating_invariant/single_primary_photo_swap_invariant
        """
        agent = create_agent()
        listing = create_draft_listing(agent)
        photo_a = upload_and_ready_photo(listing, agent, file_url="https://cdn/a.jpg")
        assert photo_a["is_primary"] is True, "first READY PHOTO is auto-assigned primary"

        photo_b = upload_and_ready_photo(listing, agent, file_url="https://cdn/b.jpg")
        assert photo_b["is_primary"] is False, (
            "second READY PHOTO does not displace the existing primary"
        )

        primaries = [p for p in _ready_photos(api, listing["id"]) if p["is_primary"]]
        assert len(primaries) == 1 and primaries[0]["id"] == photo_a["id"]

    def test_set_primary_swap_keeps_exactly_one_primary(self, api):
        """PRD §3.2: "Exactly one `READY` photo per listing may be primary at a time."
        PRD §3.2: "The swap is atomic: the previous primary's `is_primary` flips to
        false as the new one flips to true, and `MEDIA_UPDATE` jobs are queued
        exactly as in the mark-ready flow."

        Design: Difficulty/compensating_invariant/single_primary_photo_swap_invariant
        """
        agent = create_agent()
        listing = create_draft_listing(agent)
        photo_a = upload_and_ready_photo(listing, agent, file_url="https://cdn/a.jpg")
        photo_b = upload_and_ready_photo(listing, agent, file_url="https://cdn/b.jpg")

        swapped = validate_success(
            api.set_primary_media(photo_b["id"], owner_headers(agent)), 200)
        assert swapped["is_primary"] is True
        assert swapped["id"] == photo_b["id"]

        photos = _ready_photos(api, listing["id"])
        primaries = [p for p in photos if p["is_primary"]]
        assert len(primaries) == 1, "exactly one primary before and after the swap"
        assert primaries[0]["id"] == photo_b["id"]
        by_id = {p["id"]: p for p in photos}
        assert by_id[photo_a["id"]]["is_primary"] is False


def test_set_primary_validation_trio(api):
    """PRD §3.2: "the designation enforces three checks in order — the asset's `kind`
    must be `PHOTO`, else `ERR_PRIMARY_REQUIRES_PHOTO`; its `status` must be `READY`,
    else `ERR_MEDIA_NOT_READY`; and it must not already be the primary, else
    `ERR_ALREADY_PRIMARY`."

    Design: Corner/validations/set_primary_validation_trio
    """
    agent = create_agent()
    listing = create_draft_listing(agent)

    video = validate_success(api.create_media_asset(
        listing["id"],
        create_media_asset_payload(kind="VIDEO", file_url="https://cdn/v.mp4", file_bytes=999999),
        owner_headers(agent)), 201)
    validate_success(api.mark_media_ready(video["id"], owner_headers(agent)), 200)

    uploaded_photo = upload_photo(listing, agent, file_url="https://cdn/u.jpg")
    ready_photo = upload_and_ready_photo(listing, agent, file_url="https://cdn/p.jpg")
    assert ready_photo["is_primary"] is True, "first READY PHOTO is auto-primary"

    res1 = api.set_primary_media(video["id"], owner_headers(agent))
    validate_error(res1, ApiErrorId.ERR_PRIMARY_REQUIRES_PHOTO, expected_status=422)

    res2 = api.set_primary_media(uploaded_photo["id"], owner_headers(agent))
    validate_error(res2, ApiErrorId.ERR_MEDIA_NOT_READY, expected_status=409)

    res3 = api.set_primary_media(ready_photo["id"], owner_headers(agent))
    validate_error(res3, ApiErrorId.ERR_ALREADY_PRIMARY, expected_status=409)

    primaries = [p for p in _ready_photos(api, listing["id"]) if p["is_primary"]]
    assert len(primaries) == 1 and primaries[0]["id"] == ready_photo["id"]


def test_mark_ready_small_photo_returns_media_too_small(api):
    """PRD §3.2: "a `PHOTO` must be at least 1024 pixels wide and at least 768 pixels
    tall, failing with `ERR_MEDIA_TOO_SMALL` when either dimension falls short."

    Design: Corner/validations/mark_ready_small_photo_returns_media_too_small
    """
    agent = create_agent()
    listing = create_draft_listing(agent)
    small = upload_photo(listing, agent, file_url="https://cdn/s.jpg",
                         width_px=800, height_px=600)
    res = api.mark_media_ready(small["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_MEDIA_TOO_SMALL, expected_status=422)

    assets = get_success_data(api.list_media_assets(listing["id"], MC), 200)
    assert assets[0]["status"] == "UPLOADED", "rejected mark-ready leaves the asset UPLOADED"


def test_media_archive_from_uploaded_rejected(api):
    """PRD §3.2: "Archiving retires an asset from `READY` to `ARCHIVED`, or from
    `REJECTED` to `ARCHIVED`."
    PRD §2.9: "Lifecycle and entity state — the current state permits the operation,
    else `ERR_INVALID_STATE`"

    Design: Corner/state_machines/media_archive_from_uploaded_rejected
    """
    agent = create_agent()
    listing = create_draft_listing(agent)
    video = validate_success(api.create_media_asset(
        listing["id"],
        create_media_asset_payload(kind="VIDEO", file_url="https://cdn/v.mp4", file_bytes=999999),
        owner_headers(agent)), 201)
    assert video["status"] == "UPLOADED"

    res = api.archive_media_asset(video["id"], owner_headers(agent))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    assets = get_success_data(api.list_media_assets(listing["id"], MC), 200)
    assert assets[0]["status"] == "UPLOADED"
