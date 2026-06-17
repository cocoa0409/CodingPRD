"""Gallery publish content boundary: photo_count == 0 vs photo_count >= 1."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, create_completed_booking,
)

OPS = TEST_USERS["operations_manager_headers"]


class TestGalleryEmptyBoundary:
    """Difficulty Rule 6: empty-collection boundary on publish — photo_count 0 rejects,
    photo_count >= 1 publishes."""

    def test_publish_empty_gallery_rejected(self, api):
        """PRD §3.9: "An attempt to publish a gallery whose `photo_count` is zero is
        rejected with `ERR_GALLERY_EMPTY`."

        Design: Difficulty/boundary_precision_check/gallery_publish_empty_zero_photo_boundary
        """
        built = create_completed_booking()
        gid = built["gallery"]["id"]
        # Gallery freshly created at completion has photo_count 0.
        assert built["gallery"]["photo_count"] == 0
        res = api.publish_gallery(gid, OPS)
        validate_error(res, ApiErrorId.ERR_GALLERY_EMPTY.value)
        after = get_success_data(api.get_gallery(gid, OPS))
        assert after["status"] == "DRAFT"

    def test_publish_with_one_photo_succeeds(self, api):
        """PRD §3.9: "Publishing from `DRAFT` to `PUBLISHED` requires that the gallery is
        in `DRAFT`, that its `photo_count` is at least 1, that the parent booking's
        `schedule_status` is `COMPLETED`, and that the parent booking's `payment_status`
        is `PAID_IN_FULL`; on success the system mints a fresh six-digit `access_pin` and
        increments the gallery's `version`."

        Design: Difficulty/boundary_precision_check/gallery_publish_empty_zero_photo_boundary
        """
        built = create_completed_booking()
        gid = built["gallery"]["id"]
        api.upload_gallery_photos(gid, {"count": 1}, OPS)
        published = validate_success(api.publish_gallery(gid, OPS), 200)
        assert published["status"] == "PUBLISHED"
        assert published["access_pin"] is not None
