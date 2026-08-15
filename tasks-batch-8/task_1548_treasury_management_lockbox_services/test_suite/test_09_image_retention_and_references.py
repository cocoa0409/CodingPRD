"""Image retrieval retention window and referential-vs-temporal validation
ordering."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    accept_item,
    assert_image_request,
    begin_capture,
    capture_item,
    create_batch,
    create_image_request,
    set_clock,
    setup_live_lockbox,
    validate_error,
    validate_success,
)


def _setup_accepted_item_at(clock_at="2026-08-01T10:00:00Z"):
    """LIVE workspace with one ACCEPTED item captured at `clock_at`."""
    set_clock(clock_at)
    ws = setup_live_lockbox()
    batch = create_batch(ws, batch_reference="B1", received_at=clock_at,
                         declared_item_count=1, declared_total_cents=1000)
    begin_capture(ws, batch["id"])
    item = capture_item(ws, batch["id"], check_number="1", amount_cents=1000)
    accept_item(ws, batch["id"], item["id"])
    return ws, item


class TestRetentionWindow:
    def test_request_after_retention_expiry_is_created_denied(self, api):
        """PRD §3.5: "At creation the request computes `retention_expires_at`
        — seven years from the item's capture timestamp — and `sla_due_at`, one
        business hour after the request is made; if the retention window has
        already lapsed, the request is created directly in `DENIED`."

        Design: Difficulty/resource_temporal_overlap/image_retention_window_vs_request_time
        """
        ws, item = _setup_accepted_item_at()
        # Jump more than seven years past the item's capture timestamp.
        set_clock("2033-08-02T10:00:00Z")
        resp = create_image_request(ws, item["id"])
        request = validate_success(resp, 201)
        assert request["status"] == "DENIED", (
            "A request filed beyond the retention window is created directly "
            "in DENIED"
        )

    def test_request_within_retention_window_is_created_requested(self, api):
        """PRD §3.5: "At creation the request computes `retention_expires_at`
        — seven years from the item's capture timestamp — and `sla_due_at`, one
        business hour after the request is made; if the retention window has
        already lapsed, the request is created directly in `DENIED`."

        Design: Difficulty/resource_temporal_overlap/image_retention_window_vs_request_time
        """
        ws, item = _setup_accepted_item_at()
        resp = create_image_request(ws, item["id"])
        request = validate_success(resp, 201)
        assert_image_request(request)
        assert request["status"] == "REQUESTED"
        assert request["retention_expires_at"], (
            "retention_expires_at is computed at creation"
        )


class TestReferentialBeforeTemporal:
    def test_referential_failure_beats_retention_failure(self, api):
        """PRD §2.9: "Incoming requests are checked against the following rules
        in the order listed — a request that fails an earlier check is rejected
        immediately and never reaches a later one."
        PRD §2.9: "8. Referential integrity of body-supplied references within
        the bank (`ERR_INVALID_REFERENCE`, 409)." (listed ahead of "11. Image
        retention window")

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_on_image_request
        """
        ws = setup_live_lockbox()
        # Eight years out, any real item would be past retention — but the
        # referenced item does not exist at all, so the referential check
        # (earlier in the order) is the one that must fire.
        set_clock("2034-08-01T00:00:00Z")
        resp = create_image_request(ws, NON_EXISTENT_UUID)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)

    def test_unresolvable_item_reference_rejected(self, api):
        """PRD §2.6: "References supplied in request bodies — an image
        request's `item_id`, an error credit's `cycle_id`, an incident's
        `reference_batch_id` or `reference_request_id`, a format's
        `supersedes_format_id` — must likewise resolve to an entity inside the
        same bank and customer scope, or the request fails with
        `ERR_INVALID_REFERENCE` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_on_image_request
        """
        ws = setup_live_lockbox()
        resp = create_image_request(ws, NON_EXISTENT_UUID)
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)
