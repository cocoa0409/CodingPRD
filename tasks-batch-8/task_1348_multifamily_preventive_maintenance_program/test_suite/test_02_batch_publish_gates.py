"""Batch lifecycle gates: empty batch, window-in-past, OCC on publish,
archival lockdown, and locked-target reschedule refusal."""
from test_helpers import (
    TEST_USERS, NON_EXISTENT_UUID,
    validate_success, validate_error,
    ApiErrorId,
    api_client,
    create_property, create_building, create_unit, create_asset,
    create_template, create_plan, create_batch, add_visit, get_batch,
    publish_batch, set_clock, lock_batch, no_access_visit,
    setup_published_visit, setup_property_scaffold,
    create_batch_payload, create_template_payload,
    make_technician_headers,
)

TEST_PM = TEST_USERS["property_manager_headers"]


class TestEmptyBatchPublishRejected:
    def test_publish_batch_with_zero_visits_rejected(self, api):
        """PRD §3.3: "Publishing a batch with zero non-`CANCELLED` visits fails
        with `ERR_EMPTY_BATCH`".

        Design: Corner/errors/empty_batch_publish_rejected
        """
        prop = create_property()
        batch = create_batch(
            prop["id"], window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T18:00:00Z"
        )
        resp = api.publish_batch(batch["id"], {"expected_batch_version": batch["version"]}, TEST_PM)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH)


class TestWindowInPastPublishRejected:
    def test_publish_with_window_start_not_in_future_rejected(self, api):
        """PRD §3.3: "a batch whose `window_start` is no longer in the future
        fails with `ERR_WINDOW_IN_PAST`". The batch is non-empty so the empty-batch
        rule cannot mask the window check; at the default clock
        2026-08-01T00:00:00Z a window starting 2026-08-01T00:00:00Z is no longer
        in the future.

        Design: Corner/errors/window_in_past_publish_rejected
        """
        ctx = setup_property_scaffold()
        batch = create_batch(
            ctx["property"]["id"],
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        )
        add_visit(
            batch["id"], ctx["unit"]["id"], ctx["template"]["id"], ctx["asset"]["id"],
            ctx["plan"]["id"], scheduled_start="2026-08-01T01:00:00Z",
        )
        current = get_batch(batch["id"])
        resp = api.publish_batch(batch["id"], {"expected_batch_version": current["version"]}, TEST_PM)
        validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


class TestOccStaleVersionOnBatchPublish:
    def test_publish_with_stale_expected_batch_version_rejected(self, api):
        """PRD §2.9: "Publishing an entry batch requires the request to carry
        `expected_batch_version` holding the client-last-observed `version` of the
        batch; because every visit creation bumps the batch's `version`, a
        publisher working from a roster read before another manager added a visit
        is likewise rejected with `ERR_STALE_VERSION` (HTTP 412), and must re-read
        the batch before re-attempting."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_batch_publish
        """
        ctx = setup_property_scaffold()
        batch = create_batch(
            ctx["property"]["id"], window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T18:00:00Z"
        )
        stale_version = batch["version"]  # captured before the roster changed
        add_visit(
            batch["id"], ctx["unit"]["id"], ctx["template"]["id"], ctx["asset"]["id"],
            ctx["plan"]["id"], scheduled_start="2026-08-10T09:00:00Z",
        )
        resp = api.publish_batch(batch["id"], {"expected_batch_version": stale_version}, TEST_PM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestArchivedPropertyBlocksMutations:
    def test_child_template_create_rejected_after_archive(self, api):
        """PRD §2.10: "once a `PropertyManager` archives it, its `status` becomes
        `ARCHIVED` and every mutation of the property or of any descendant is
        rejected with `ERR_PROPERTY_ARCHIVED` (HTTP 409) — a check performed
        before any state or business rule, immediately after existence."

        Design: Corner/cross_cutting_layers/archived_property_blocks_all_child_mutation
        """
        prop = create_property()
        validate_success(api.archive_property(prop["id"], TEST_PM))
        resp = api.create_template(create_template_payload(prop["id"]), TEST_PM)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_ARCHIVED)

    def test_reads_of_archived_property_remain_available(self, api):
        """PRD §2.10: "Reads of an archived property and its descendants remain
        available to all roles."

        Design: Corner/cross_cutting_layers/archived_property_blocks_all_child_mutation
        """
        prop = create_property()
        validate_success(api.archive_property(prop["id"], TEST_PM))
        data = validate_success(api.get_property(prop["id"], TEST_PM))
        assert data["status"] == "ARCHIVED"


class TestBatchPublishGatedByPropertyActive:
    def _setup_draft_batch_with_visit(self):
        ctx = setup_property_scaffold()
        batch = create_batch(
            ctx["property"]["id"], window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T18:00:00Z"
        )
        add_visit(
            batch["id"], ctx["unit"]["id"], ctx["template"]["id"], ctx["asset"]["id"],
            ctx["plan"]["id"], scheduled_start="2026-08-10T09:00:00Z",
        )
        return ctx, batch

    def test_publish_under_archived_property_rejected(self, api):
        """PRD §2.10: "once a `PropertyManager` archives it, its `status` becomes
        `ARCHIVED` and every mutation of the property or of any descendant is
        rejected with `ERR_PROPERTY_ARCHIVED` (HTTP 409) — a check performed
        before any state or business rule, immediately after existence."

        Design: Difficulty/cross_entity_state_dependency/batch_publish_gated_by_property_active_and_window_future
        """
        ctx, batch = self._setup_draft_batch_with_visit()
        validate_success(api.archive_property(ctx["property"]["id"], TEST_PM))
        current = get_batch(batch["id"])
        resp = api.publish_batch(batch["id"], {"expected_batch_version": current["version"]}, TEST_PM)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_ARCHIVED)

    def test_batch_cancel_under_archived_property_rejected(self, api):
        """PRD §2.10: "every mutation of the property or of any descendant is
        rejected with `ERR_PROPERTY_ARCHIVED` (HTTP 409)". Batch cancel is a
        mutation of a descendant of the archived property.

        Design: Difficulty/cross_entity_state_dependency/batch_publish_gated_by_property_active_and_window_future
        """
        ctx, batch = self._setup_draft_batch_with_visit()
        validate_success(api.archive_property(ctx["property"]["id"], TEST_PM))
        resp = api.cancel_batch(batch["id"], TEST_PM)
        validate_error(resp, ApiErrorId.ERR_PROPERTY_ARCHIVED)


class TestRescheduleIntoLockedBatchRejected:
    def test_reschedule_into_locked_target_batch_rejected(self, api):
        """PRD §3.4: "the target batch must be `DRAFT` or `PUBLISHED` — `LOCKED`,
        `EXECUTED`, and `CANCELLED` targets fail with `ERR_BATCH_NOT_MUTABLE`".

        Design: Corner/endpoints/reschedule_rejected_when_target_batch_locked
        """
        # Source batch b1 published with one visit; the technician records a failed entry.
        ctx = setup_published_visit(
            occupancy="VACANT",
            window_start="2026-08-03T08:00:00Z",
            window_end="2026-08-03T18:00:00Z",
            scheduled_start="2026-08-03T09:00:00Z",
        )
        set_clock("2026-08-03T09:00:00Z")
        no_access_visit(ctx["visit"]["id"], technician_id="tech-1")

        # Target batch b2 must be PUBLISHED before it can be locked; publish
        # requires a non-empty roster, so b2 carries its own visit on unit 102.
        unit2 = create_unit(ctx["building"]["id"], unit_number="102", occupancy_status="VACANT")
        asset2 = create_asset(unit2["id"])
        batch2 = create_batch(
            ctx["property"]["id"], batch_label="b2",
            window_start="2026-08-10T08:00:00Z", window_end="2026-08-10T18:00:00Z",
        )
        add_visit(
            batch2["id"], unit2["id"], ctx["template"]["id"], asset2["id"],
            ctx["plan"]["id"], scheduled_start="2026-08-10T09:00:00Z",
        )
        publish_batch(batch2["id"])
        # Locking is legal once the clock has reached one hour before window_start.
        set_clock("2026-08-10T07:00:00Z")
        lock_batch(batch2["id"])

        resp = api.reschedule_visit(
            ctx["visit"]["id"],
            {"target_batch_id": batch2["id"], "new_scheduled_start": "2026-08-10T09:00:00Z"},
            TEST_PM,
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_NOT_MUTABLE)
