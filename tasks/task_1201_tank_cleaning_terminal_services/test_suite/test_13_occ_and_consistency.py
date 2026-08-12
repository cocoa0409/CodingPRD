"""Optimistic concurrency rules (PRD §2.6) and immediate read-after-write."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_service_window_payload, create_inspection_payload,
    patch_cleaning_job_payload,
    new_ctx, create_job, schedule_job,
    setup_ctx_entry_in_progress,
    add_inspector, create_inspection,
    fresh_tank_version, fresh_inspector_version,
)

OPERATOR = TEST_USERS["operator_headers"]


class TestOptimisticConcurrency:
    def test_stale_tank_version_rejects_window_create(self, api):
        """PRD §2.6: "Booking a service window requires the request to carry `expected_tank_version` holding the tank `version` the client last observed. If the tank's current `version` has advanced since — for example because another writer has just booked a window on the same tank, an act that legitimately extends the tank's booked calendar and itself increments the tank's `version` by one — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from extending a calendar it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_window_create_returns_412
        """
        ctx = new_ctx()
        stale_version = ctx["tank"]["version"]
        validate_success(api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], stale_version,
                planned_start="2026-05-02T00:00:00Z",
                planned_end="2026-05-10T00:00:00Z"),
            OPERATOR), 201)  # advances the tank's version
        # The June interval overlaps nothing and respects the buffer — only
        # the stale version rejects this write.
        res = api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], stale_version,
                planned_start="2026-06-01T00:00:00Z",
                planned_end="2026-06-05T00:00:00Z"),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_job_version_rejects_patch(self, api):
        """PRD §3.4: "the patch must carry `expected_job_version` per §2.6 and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). Each accepted patch advances the job's `version` by one"
        PRD §2.6: "Patching a cleaning job requires `expected_job_version` matching the job's current `version`; a job whose version has advanced since the client's last read rejects the patch with `ERR_STALE_VERSION` (HTTP 412), because the client's edits were computed against a stale snapshot."

        Design: Corner/cross_cutting_layers/occ_stale_job_patch_returns_412
        """
        ctx = new_ctx()
        job = create_job(ctx, heel_volume_liters_sounding=100,
                         base_service_fee_cents=1000)
        stale_version = job["version"]
        patched = validate_success(api.patch_cleaning_job(
            job["id"],
            patch_cleaning_job_payload(stale_version,
                                       base_service_fee_cents=2000),
            OPERATOR), 200)
        assert patched["version"] == stale_version + 1
        assert patched["base_service_fee_cents"] == 2000

        res = api.patch_cleaning_job(
            job["id"],
            patch_cleaning_job_payload(stale_version,
                                       base_service_fee_cents=3000),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_inspector_version_rejects_inspection_create(self, api):
        """PRD §2.6: "Booking an inspection requires `expected_inspector_version` matching the inspector's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412). This rejection applies even when the new interval overlaps nothing on the inspector's calendar — the client's view of the calendar is stale regardless of whether the specific slot happens to be free."

        Design: Corner/cross_cutting_layers/occ_stale_inspection_create_returns_412
        """
        ctx = setup_ctx_entry_in_progress()
        add_inspector(ctx)
        inspector_id = ctx["inspector"]["id"]
        stale_version = fresh_inspector_version(inspector_id)
        create_inspection(ctx, "2026-05-03T00:00:00Z", "2026-05-03T08:00:00Z")
        # May-5 slot is free; only the stale inspector version rejects it.
        res = api.create_inspection(
            create_inspection_payload(
                ctx["job"]["id"], inspector_id, stale_version,
                scheduled_start="2026-05-05T00:00:00Z",
                scheduled_end="2026-05-05T08:00:00Z"),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION)


class TestImmediateConsistency:
    def test_schedule_visible_in_immediately_following_reads(self, api):
        """PRD §3.4: "On success the job moves `DRAFT` to `SCHEDULED`, the window's `job_id` is set to the job, and the job's `version` increments by one."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."

        Design: Corner/consistency_model/immediate_read_after_write_consistency
        """
        ctx = new_ctx()
        job = create_job(ctx, heel_volume_liters_sounding=100,
                         base_service_fee_cents=1000)
        schedule_job(ctx)
        # The next read reflects the mutation: job SCHEDULED, window linked.
        after = validate_success(api.get_cleaning_job(job["id"], OPERATOR), 200)
        assert after["status"] == "SCHEDULED"
        window = validate_success(
            api.get_service_window(ctx["window"]["id"], OPERATOR), 200)
        assert window["job_id"] == job["id"]
