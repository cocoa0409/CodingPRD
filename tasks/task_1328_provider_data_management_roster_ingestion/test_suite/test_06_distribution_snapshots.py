"""Distribution targets, batches, snapshot selection and change classification,
batch lifecycle, and append-only items (PRD §3.9, §2.5)."""
from test_helpers import (
    FRESH_PROVIDER_SCORE,
    TEST_USERS,
    ApiErrorId,
    assert_distribution_item,
    create_batch,
    create_provider,
    create_target,
    list_batch_items,
    publish_batch,
    set_clock,
    setup_acked_baseline_batch,
    validate_error,
    validate_success,
)

TEST_STEWARD = TEST_USERS["data_steward_headers"]


class TestQualityFloorBoundary:
    def test_provider_at_exact_floor_included(self, api, distribution_operator_headers):
        """PRD §3.9: "A provider is eligible when its `lifecycle_status` is `ACTIVE` at
        the cutoff and its score meets the target's `required_quality_floor` — the plain
        `current_quality_score` for `CLAIMS` and `NETWORK` targets". A score exactly
        equal to the floor meets it (inclusive boundary).

        Design: Difficulty/boundary_precision_check/distribution_floor_exactly_at_threshold
        """
        set_clock()
        floor = FRESH_PROVIDER_SCORE["total_score"]  # 30
        provider = create_provider()
        target = create_target(target_code="CLAIMS", required_quality_floor=floor)
        batch = create_batch(target["id"])
        published = publish_batch(batch["id"])
        assert published["provider_count"] == 1, (
            f"Provider at score == floor must be included, provider_count={published['provider_count']}"
        )
        items = list_batch_items(batch["id"])
        assert len(items) == 1
        assert items[0]["provider_id"] == provider["id"]
        assert items[0]["change_kind"] == "ADD", (
            "Absent from any ACKED baseline, the provider appears as ADD (PRD §3.9); "
            f"got {items[0]['change_kind']}"
        )

    def test_provider_one_below_floor_excluded(self, api, distribution_operator_headers):
        """PRD §3.9: "A provider is eligible when its `lifecycle_status` is `ACTIVE` at
        the cutoff and its score meets the target's `required_quality_floor`". One point
        below the floor does not meet it.

        Design: Difficulty/boundary_precision_check/distribution_floor_exactly_at_threshold
        """
        set_clock()
        floor = FRESH_PROVIDER_SCORE["total_score"]  # 30
        create_provider()  # score 30
        target = create_target(target_code="CLAIMS", required_quality_floor=floor + 1)
        batch = create_batch(target["id"])
        published = publish_batch(batch["id"])
        assert published["provider_count"] == 0, (
            f"Provider one point below the floor must be excluded, "
            f"provider_count={published['provider_count']}"
        )
        assert list_batch_items(batch["id"]) == []


class TestChangeKindClassification:
    def test_term_and_add_against_baseline(self, api, distribution_operator_headers):
        """PRD §3.9: "Each provider's change is classified against the target's most
        recent `ACKED` batch, the baseline: a provider absent from the baseline appears
        as `ADD`; one present whose `payload_hash` has changed appears as `UPDATE`; one
        present who has since become `TERMINATED` or `MERGED` appears as `TERM`; and one
        present whose score has dropped below the floor appears as
        `QUALITY_DROP_EXCLUDED`." and "the batch's `provider_count` records how many
        items were materialized."

        Design: Corner/calculations/distribution_snapshot_change_kind_classification
        """
        set_clock()
        provider_a = create_provider()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        setup_acked_baseline_batch(target["id"])
        # Terminate A after the baseline; create newcomer B.
        validate_success(api.terminate_provider(provider_a["id"], TEST_STEWARD))
        provider_b = create_provider(npi="1234567894", location_key="LOC2")
        batch = create_batch(target["id"])
        published = publish_batch(batch["id"])
        assert published["provider_count"] == 2, (
            f"Baseline TERM plus newcomer ADD must yield 2 items, got {published['provider_count']}"
        )
        items = list_batch_items(batch["id"])
        by_provider = {i["provider_id"]: i["change_kind"] for i in items}
        assert by_provider.get(provider_a["id"]) == "TERM", (
            f"Terminated baseline provider must appear as TERM, got {by_provider.get(provider_a['id'])}"
        )
        assert by_provider.get(provider_b["id"]) == "ADD", (
            f"New provider must appear as ADD, got {by_provider.get(provider_b['id'])}"
        )


class TestBatchLifecycle:
    def test_second_publish_while_inflight_rejected(self, api, distribution_operator_headers):
        """PRD §3.9: "Two guards apply, evaluated in this order after state legality: no
        other batch for the same target may stand in `BUILDING` or `PUBLISHED`, failing
        as `ERR_BATCH_INFLIGHT` (HTTP 409); and the target must be `ACTIVE`, failing as
        `ERR_TARGET_DISABLED` (HTTP 409)."

        Design: Corner/validations/batch_inflight_blocks_second_publish
        """
        set_clock()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        batch1 = create_batch(target["id"])
        publish_batch(batch1["id"])
        batch2 = create_batch(target["id"])
        res = api.publish_batch(batch2["id"], distribution_operator_headers)
        validate_error(res, ApiErrorId.ERR_BATCH_INFLIGHT)

    def test_publish_against_disabled_target_rejected(self, api, distribution_operator_headers):
        """PRD §3.9: "and the target must be `ACTIVE`, failing as `ERR_TARGET_DISABLED`
        (HTTP 409)."

        Design: Corner/errors/error_target_disabled_on_publish
        """
        set_clock()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        batch = create_batch(target["id"])
        validate_success(api.disable_distribution_target(target["id"], distribution_operator_headers))
        res = api.publish_batch(batch["id"], distribution_operator_headers)
        validate_error(res, ApiErrorId.ERR_TARGET_DISABLED)

    def test_acked_batch_is_terminal(self, api, distribution_operator_headers):
        """PRD §3.9: "A published batch awaits its downstream fate. Acknowledgement
        moves it `PUBLISHED` → `ACKED`, making it the new baseline for future snapshots.
        Failure moves it `PUBLISHED` → `FAILED` and requires a `failure_reason` in the
        request. A batch still `BUILDING` may be discarded, moving to `SUPERSEDED`;
        `ACKED` and `SUPERSEDED` are the terminal batch states."
        PRD §2.6: "a request that names a legal resource in an illegal state is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/distribution_batch_terminal_acked_lockdown
        """
        set_clock()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        batch = setup_acked_baseline_batch(target["id"])
        res = api.fail_batch(
            batch["id"], {"failure_reason": "late"}, distribution_operator_headers
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(
            api.get_distribution_batch(batch["id"], distribution_operator_headers)
        )
        assert after["status"] == "ACKED"

    def test_retry_supersedes_failed_batch(self, api, distribution_operator_headers):
        """PRD §3.9: "Optionally the creation names a `retry_of_batch_id`: when it names
        a `FAILED` batch, that failed batch moves to `SUPERSEDED` as the new batch
        opens, making the new batch its manual retry."

        Design: Corner/endpoints/batch_retry_supersedes_failed
        """
        set_clock()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        batch1 = create_batch(target["id"])
        publish_batch(batch1["id"])
        validate_success(
            api.fail_batch(
                batch1["id"], {"failure_reason": "downstream 500"},
                distribution_operator_headers,
            )
        )
        res = api.create_distribution_batch(
            {"distribution_target_id": target["id"], "retry_of_batch_id": batch1["id"]},
            distribution_operator_headers,
        )
        batch2 = validate_success(res, 201)
        assert batch2["status"] == "BUILDING"
        assert batch2["retry_of_batch_id"] == batch1["id"]
        old = validate_success(
            api.get_distribution_batch(batch1["id"], distribution_operator_headers)
        )
        assert old["status"] == "SUPERSEDED", (
            f"Retried-from FAILED batch must move to SUPERSEDED, got {old['status']}"
        )


class TestDistributionItemsAppendOnly:
    def test_items_carry_only_id_and_created_at(self, api, distribution_operator_headers):
        """PRD §2.5: "Three record types are append-only ledger entries and carry only
        `id` and `created_at`: a distribution item, a data quality score row, and a
        provider merge record. For these three, both `updated_at` and `version` are
        absent — they are never mutated after creation."

        Design: Corner/entities/distribution_item_immutable_no_update_endpoint
        """
        set_clock()
        provider = create_provider()
        target = create_target(target_code="CLAIMS", required_quality_floor=0)
        batch = create_batch(target["id"])
        publish_batch(batch["id"])
        items = list_batch_items(batch["id"])
        assert len(items) >= 1, "Setup: expected at least one snapshot item"
        for item in items:
            assert_distribution_item(item)
            assert item["provider_id"] == provider["id"]
            assert item["change_kind"] == "ADD"
