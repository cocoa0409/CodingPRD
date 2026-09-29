"""Read-your-write: the response of a write, and the read that follows it in the same test."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers import (
    MODERATOR_B_USER_ID,
    assert_instant,
    campaign_manager_headers,
    fulfillment_ops_headers,
    moderator_b_headers,
)
from test_helpers.fixtures import KitSpec


CANONICAL_TEN_UNIT_KIT = (
    KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),
    KitSpec("ACC-2", "ACCESSORY", 388, 2, 0.85, 10),
    KitSpec("INS-3", "INSERT_CARD", 554, 1, 0.9, 10),
)
SINGLE_HERO_KIT = (KitSpec("HERO-1", "HERO_PRODUCT", 1417, 1, 0.8, 10),)
NORTH_CENTER = {"name": "North Pick Center", "zone_code": "Z-NORTH"}
EPOCH = "2026-08-01T00:00:00Z"
REVIEW_DUE_AT = "2026-08-22T00:00:00Z"
MODERATOR_NOTE = "Clear disclosure and enough detail."


class TestAllocationSnapshotIsVisibleAtOnce:
    """The 201 body carries the snapshot, and the cost read behind it already agrees."""

    def test_the_response_and_the_following_cost_read_both_show_the_allocation(self, api):
        """PRD §4: "An operation that brings a new resource into existence answers
        with HTTP 201 and returns the created resource; an operation that modifies
        or transitions an existing resource answers with HTTP 200 and returns the
        updated resource; every read answers with HTTP 200."

        PRD §3.6: "The candidates are ordered by `created_at` ascending with
        `component_sku` ascending as the tie-break, and each contributes its own
        `quantity_per_kit` units — one kit needs one line's worth of every active
        component."

        PRD §3.6: "On success the per-line debits are recorded on the shipment as
        `reserved_line_units`, a mapping from kit line to units taken, and their sum
        is recorded as `kit_unit_total` — the figure both capacity ceilings were
        tested against."

        PRD §3.6: "The shipment's `committed_cost_cents` is the campaign's current
        `kit_assembly_unit_cost_cents` plus the `freight_cents_per_kit` of the
        center that owns the shipment's wave. That amount moves out of the
        campaign's `budget_available_cents` and into its `budget_committed_cents`."

        PRD §3.6: "A dedicated cost read exposes both figures side by side together
        with the budget triple, returning `campaign_id`,
        `kit_assembly_unit_cost_cents`, `cost_per_sample_provisional_cents`,
        `cost_per_sample_final_cents`, `budget_total_cents`,
        `budget_committed_cents`, `budget_available_cents`,
        `allocated_sample_count`, `delivered_sample_count` and
        `write_off_cost_cents`, so that the budget conservation identity of §2.7 can
        be checked directly against the cost figures derived from it."

        Design: Corner/consistency_model/allocation_response_carries_every_derived_field_immediately
        """
        world = fx.sampling_active_campaign(
            api,
            panelist_count=1,
            kit_specs=CANONICAL_TEN_UNIT_KIT,
            center_overrides=dict(NORTH_CENTER),
            name="Immediate Alloc",
        )
        enrollment_version = fx.get_enrollment(api, world.enrollment_id(0))["version"]

        shipment = validate_success(
            api.create_sample_shipment(
                fulfillment_ops_headers(),
                enrollment_id=world.enrollment_id(0),
                fulfillment_wave_id=world.wave_id,
                expected_enrollment_version=enrollment_version,
            ),
            201,
        )

        assert shipment["kit_unit_total"] == 4
        assert shipment["committed_cost_cents"] == 754
        assert shipment["reserved_line_units"] == {
            world.kit_line_id(0): 1,
            world.kit_line_id(1): 2,
            world.kit_line_id(2): 1,
        }

        summary = validate_success(
            api.get_campaign_cost_summary(campaign_manager_headers(), world.campaign_id)
        )
        assert summary["kit_assembly_unit_cost_cents"] == 454
        assert summary["cost_per_sample_provisional_cents"] == 754
        assert summary["cost_per_sample_final_cents"] == 0
        assert summary["budget_total_cents"] == 1000000
        assert summary["budget_committed_cents"] == 754
        assert summary["budget_available_cents"] == 999246
        assert summary["allocated_sample_count"] == 1
        assert summary["delivered_sample_count"] == 0
        assert summary["write_off_cost_cents"] == 0

        expected_available = {0: 9, 1: 8, 2: 9}
        for index, available in expected_available.items():
            line = fx.get_kit_line(api, world.kit_line_id(index))
            assert line["units_available"] == available

        assert fx.get_wave(api, world.wave_id)["planned_unit_count"] == 4


class TestApprovalCountersAreVisibleAtOnce:
    """One moderation call, and the two rows it moved read back already moved."""

    def test_the_approve_response_and_the_reads_behind_it_all_agree(self, api):
        """PRD §4: "An operation that brings a new resource into existence answers
        with HTTP 201 and returns the created resource; an operation that modifies
        or transitions an existing resource answers with HTTP 200 and returns the
        updated resource; every read answers with HTTP 200."

        PRD §3.7: "`APPROVE` moves the review `SUBMITTED → APPROVED`, records
        `approved_by_user_id` from the acting moderator's `X-User-ID`, increases the
        campaign's `approved_review_count` by 1, and advances the enrollment's
        obligation axis `REVIEW_DUE → REVIEW_FULFILLED`, discharging the panelist's
        obligation."

        PRD §3.7: "All three branches require the review to be `SUBMITTED` and all
        three record the note, but their side effects are deliberately disjoint."

        PRD §3.7: "Note the asymmetry: approval moves an obligation axis and a
        counter but never the posture, rejection moves a counter and the posture but
        no obligation axis, and requesting changes moves neither."

        PRD §3.7: "A first submission stamps `first_submitted_at` with the logical
        clock's current instant, and only a first submission does so — every later
        submission of the same review leaves that timestamp exactly as it was, which
        is what makes it a stable anchor for the audit variant's review-velocity
        window in §3.3."

        PRD §3.6: "Confirming delivery moves the shipment `SHIPPED → DELIVERED`,
        stamps `delivered_at` from the logical clock, increases the campaign's
        `delivered_sample_count` by 1, refreshes `cost_per_sample_final_cents`,
        re-evaluates `compliance_posture`, and advances the enrollment's obligation
        axis `SAMPLE_SENT → REVIEW_DUE` while stamping `review_due_at` as the
        delivery instant plus the campaign's `review_due_days` days."

        PRD §3.6: "Its numerator population is the campaign's shipments whose
        `status` is `DELIVERED` or `LOST`; the numerator sums, per shipment, the
        campaign's `kit_assembly_unit_cost_cents` plus that shipment's freight plus
        that shipment's `surcharge_cents`, and then adds the campaign's whole
        `write_off_cost_cents` once."

        Design: Corner/consistency_model/approval_counters_are_visible_in_the_same_request_cycle
        """
        bundle = fx.submitted_review_world(
            api,
            panelist_count=1,
            kit_specs=SINGLE_HERO_KIT,
            center_overrides=dict(NORTH_CENTER),
            objective_type="REVIEW_ACQUISITION",
            min_review_word_count=10,
            name="Immediate Approve",
        )
        world = bundle["world"]

        approved = validate_success(
            api.moderate_review(
                moderator_b_headers(),
                bundle["review"]["id"],
                decision="APPROVE",
                moderator_note=MODERATOR_NOTE,
            )
        )

        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == MODERATOR_B_USER_ID
        assert approved["moderator_note"] == MODERATOR_NOTE
        assert approved["changes_requested_by_user_id"] is None
        assert approved["revision_count"] == 0
        assert_instant(approved["first_submitted_at"], EPOCH, "first_submitted_at")

        campaign = fx.get_campaign(api, world.campaign_id)
        assert campaign["approved_review_count"] == 1
        assert campaign["delivered_sample_count"] == 1
        assert campaign["disclosure_rejected_review_count"] == 0
        assert campaign["syndicated_review_count"] == 0
        assert campaign["compliance_posture"] == "OPEN"
        assert campaign["cost_per_sample_final_cents"] == 583
        assert campaign["cost_per_sample_provisional_cents"] == 583

        enrollment = fx.get_enrollment(api, world.enrollment_id(0))
        assert enrollment["obligation_status"] == "REVIEW_FULFILLED"
        assert enrollment["screening_status"] == "SCREEN_PASSED"
        assert_instant(enrollment["review_due_at"], REVIEW_DUE_AT, "review_due_at")
