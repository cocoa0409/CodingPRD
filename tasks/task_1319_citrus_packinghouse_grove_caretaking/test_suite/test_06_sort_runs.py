"""Sort runs: segregation of duties at verify, one-live-run constraint with
create-with-supersede after void, grade-sum exactness, the juice-channel
requirement at post, the packout waterfall arithmetic, and immediate
consistency of the post."""
from test_helpers import (
    ApiErrorId,
    allocation_boxes_per_channel,
    assert_sort_run,
    create_sort_run_for_delivery,
    dom_fresh_spec,
    get_delivery,
    get_pool,
    get_sort_run,
    juice_spec,
    set_clock,
    setup_delivery_received,
    setup_posted_scenario,
    sort_run_lifecycle,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    TEST_USERS,
    build_user_headers,
    make_inspector_headers,
    make_operator_headers,
)

ADMIN = TEST_USERS["admin_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestVerifySegregationOfDuties:
    def test_sort_run_verify_segregation_of_duties(self, api):
        """PRD §2.9: "A sort run's verifier must differ from its creator: the
        `X-User-ID` recorded as `verified_by` may not equal the run's
        `created_by`." and "Every violation of these pairings is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/state_machines/sort_run_verify_segregation_of_duties
        """
        scenario = setup_delivery_received("SM5", gross_boxes=10, planned_boxes=50)
        run = create_sort_run_for_delivery(
            scenario["delivery"]["id"], 10, 0, 0, 0, 0, 8, 5,
            operator_id="shared-1")
        assert run["created_by"] == "shared-1"
        assert run["status"] == "OPEN"
        # The same X-User-ID cannot verify its own run, even with the
        # QualityInspector role.
        resp = api_client.verify_sort_run(
            run["id"], build_user_headers("shared-1", "QualityInspector"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        # A different inspector verifies.
        verified = validate_success(api_client.verify_sort_run(
            run["id"], make_inspector_headers("qi-other")))
        assert verified["status"] == "VERIFIED"
        assert verified["verified_by"] == "qi-other"


class TestOneLiveRunPerDelivery:
    def test_sort_run_second_active_rejected_then_recreate(self, api):
        """PRD §3.5: "At most one non-`VOIDED` run may exist per delivery — a
        second live run is refused with `ERR_SORT_RUN_ALREADY_ACTIVE`". PRD
        §3.5: "A `LineOperator` may void a run while it is `OPEN` or
        `VERIFIED`, moving it to the terminal `VOIDED`".

        Design: Corner/state_machines/sort_run_second_active_rejected_then_recreate
        """
        scenario = setup_delivery_received("SM6", gross_boxes=10, planned_boxes=50)
        delivery_id = scenario["delivery"]["id"]
        first = create_sort_run_for_delivery(delivery_id, 9, 0, 0, 1, 0, 8, 5,
                                             operator_id="op-sm6")
        assert first["status"] == "OPEN"
        current_version = get_delivery(delivery_id)["version"]
        resp = api_client.create_sort_run(
            {"delivery_id": delivery_id, "fancy_boxes": 10, "choice_boxes": 0,
             "standard_boxes": 0, "juice_boxes": 0, "cull_boxes": 0,
             "color_score": 8, "defect_pct": 5,
             "expected_delivery_version": current_version},
            make_operator_headers("op-sm6"))
        validate_error(resp, ApiErrorId.ERR_SORT_RUN_ALREADY_ACTIVE)
        # After voiding, a fresh create with the current version succeeds.
        validate_success(api_client.void_sort_run(
            first["id"], make_operator_headers("op-sm6")))
        second = validate_success(api_client.create_sort_run(
            {"delivery_id": delivery_id, "fancy_boxes": 10, "choice_boxes": 0,
             "standard_boxes": 0, "juice_boxes": 0, "cull_boxes": 0,
             "color_score": 8, "defect_pct": 5,
             "expected_delivery_version": get_delivery(delivery_id)["version"]},
            make_operator_headers("op-sm6")), expected_status=201)
        assert second["status"] == "OPEN"


class TestSortBoxSum:
    def test_sort_box_mismatch_exact_equality(self, api):
        """PRD §3.5: "The five grade counts must sum exactly to the delivery's
        `net_boxes`; any mismatch fails with `ERR_SORT_BOX_MISMATCH`."

        Design: Corner/validations/sort_box_mismatch_exact_equality
        """
        scenario = setup_delivery_received("V4", gross_boxes=100, planned_boxes=100)
        delivery = scenario["delivery"]
        base = {"delivery_id": delivery["id"], "color_score": 7, "defect_pct": 10,
                "expected_delivery_version": delivery["version"]}
        # One box under (99 of 100).
        resp = api_client.create_sort_run(
            {**base, "fancy_boxes": 40, "choice_boxes": 30, "standard_boxes": 20,
             "juice_boxes": 8, "cull_boxes": 1},
            make_operator_headers("op-v4"))
        validate_error(resp, ApiErrorId.ERR_SORT_BOX_MISMATCH)
        # One box over (101 of 100).
        resp = api_client.create_sort_run(
            {**base, "fancy_boxes": 41, "choice_boxes": 30, "standard_boxes": 20,
             "juice_boxes": 8, "cull_boxes": 2},
            make_operator_headers("op-v4"))
        validate_error(resp, ApiErrorId.ERR_SORT_BOX_MISMATCH)
        # Neither attempt persists a run or mutates the delivery.
        assert get_delivery(delivery["id"])["version"] == delivery["version"]
        assert get_delivery(delivery["id"])["processing_status"] == "RECEIVED"


class TestJuiceChannelRequirement:
    def test_post_requires_juice_channel(self, api):
        """PRD §3.5: "the juice channel for the variety and week — which must
        exist, or the post fails with `ERR_NO_JUICE_CHANNEL`".

        Design: Corner/validations/post_requires_juice_channel
        """
        scenario = setup_delivery_received(
            "V7", gross_boxes=10, planned_boxes=50,
            channel_specs=[dom_fresh_spec("DOM-V7", "HAMLIN", boxes=50, rank=1)])
        delivery_id = scenario["delivery"]["id"]
        run = sort_run_lifecycle(delivery_id, 10, 0, 0, 0, 0, 8, 5,
                                 operator_id="op-v7", inspector_id="qi-v7",
                                 stop_at="verified")
        resp = api_client.post_sort_run(run["id"], make_operator_headers("op-v7"))
        validate_error(resp, ApiErrorId.ERR_NO_JUICE_CHANNEL)
        # Nothing moved: the run stays VERIFIED, the delivery READY_TO_SORT,
        # and the pool totals remain zero.
        assert get_sort_run(run["id"])["status"] == "VERIFIED"
        assert get_delivery(delivery_id)["processing_status"] == "READY_TO_SORT"
        pool = get_pool(scenario["pool"]["id"])
        assert pool["posted_ge_boxes"] == 0
        assert pool["posted_proceeds_cents"] == 0
        assert pool["sorted_field_boxes"] == 0


class TestPackoutWaterfall:
    def test_packout_allocation_waterfall_lines_and_money(self, api):
        """PRD §3.5: "the non-juice channels are walked in `priority_rank`
        ascending with ties broken by `created_at` ascending; within each
        channel, grades are filled in the fixed order `FANCY`, then `CHOICE`,
        then `STANDARD`" and "the run places the lesser of that grade's
        unplaced boxes and the channel's remaining capacity — an exact fit is
        allowed". PRD §3.5: "Whatever fresh fruit no channel could take
        overflows to juice." PRD §3.5: "The run's `proceeds_cents` is the sum
        over the allocation lines of each line's boxes multiplied by its
        channel's `price_cents_per_box`." PRD §3.5: "The `ge_boxes` value —
        grade-equivalent boxes — is `fancy_boxes` times 1.15, plus
        `choice_boxes` times 1.0, plus `standard_boxes` times 0.9, plus
        `juice_boxes` times 0.35, with the sum rounded half-up to 2 decimal
        places".

        Design: Difficulty/combinatorial_formula/packout_allocation_waterfall
        """
        scenario = setup_posted_scenario("PA1")
        run = scenario["sort_run"]
        assert_sort_run(run)
        assert run["status"] == "POSTED"
        assert run["fresh_eligible"] is True
        channels = scenario["channels"]
        totals = allocation_boxes_per_channel(run["allocation"])
        # JP (rank 1) fills its 25 FANCY; DOM (rank 2) takes the 15 FANCY
        # remainder plus 25 CHOICE; the 5 CHOICE + 20 STANDARD overflow and
        # the 8 measured juice boxes (33 total) go to the juice channel.
        assert totals.get(channels["JP-PA1"]["id"]) == 25
        assert totals.get(channels["DOM-PA1"]["id"]) == 40
        assert totals.get(channels["JU-PA1"]["id"]) == 33
        assert run["proceeds_cents"] == 25 * 900 + 15 * 500 + 25 * 500 + 33 * 220
        assert run["proceeds_cents"] == 49760
        assert run["ge_boxes"] == 96.8, "40*1.15 + 30*1.0 + 20*0.9 + 8*0.35"

    def test_packout_allocation_waterfall_side_effects(self, api):
        """PRD §3.5: a successful post "moves the delivery `READY_TO_SORT` →
        `SORTED` with a version bump, decrements `remaining_boxes` on every
        channel the waterfall touched, and increases the pool's
        `posted_ge_boxes`, `posted_proceeds_cents`, and `sorted_field_boxes`".
        PRD §3.5: "A channel's `remaining_boxes` is its `allocation_boxes`
        minus the boxes already allocated to `POSTED` runs".

        Design: Difficulty/combinatorial_formula/packout_allocation_waterfall
        """
        scenario = setup_posted_scenario("PA1B")
        channels = scenario["channels"]
        assert channels["JP-PA1B"]["remaining_boxes"] == 0
        assert channels["DOM-PA1B"]["remaining_boxes"] == 0
        assert channels["JU-PA1B"]["remaining_boxes"] is None, \
            "juice channels are uncapped and report null"
        assert scenario["delivery"]["processing_status"] == "SORTED"
        pool = scenario["pool"]
        assert pool["posted_ge_boxes"] == 96.8
        assert pool["posted_proceeds_cents"] == 49760
        assert pool["sorted_field_boxes"] == 100


class TestImmediateConsistency:
    def test_immediate_consistency_on_post(self, api):
        """PRD §1: "caretaking charges offset settlement proceeds — all within
        a single atomic request boundary, so that no reader ever observes a
        half-applied cascade." PRD §3.5: a successful post "stores the
        resulting `allocation` — an array of lines, each naming a channel, a
        grade, and a box count — together with `ge_boxes` and `proceeds_cents`
        on the run, moves the delivery `READY_TO_SORT` → `SORTED` with a
        version bump, decrements `remaining_boxes` on every channel the
        waterfall touched, and increases the pool's `posted_ge_boxes`,
        `posted_proceeds_cents`, and `sorted_field_boxes`, recomputes the
        pool's provisional price, and bumps the pool's `version`".

        Design: Corner/consistency_model/immediate_consistency_on_post
        """
        scenario = setup_posted_scenario(
            "CM1", variety="VALENCIA", gross_boxes=10,
            fancy_boxes=10, choice_boxes=0, standard_boxes=0,
            juice_boxes=0, cull_boxes=0, color_score=8, defect_pct=5,
            planned_boxes=50,
            channel_specs=[
                dom_fresh_spec("DOM-CM1", "VALENCIA", boxes=10, price=600, rank=1,
                               grades=("FANCY",)),
                juice_spec("JU-CM1", "VALENCIA"),
            ])
        run = scenario["sort_run"]
        # The post response itself carries the computed results.
        totals = allocation_boxes_per_channel(run["allocation"])
        assert totals.get(scenario["channels"]["DOM-CM1"]["id"]) == 10
        assert run["proceeds_cents"] == 6000
        assert run["ge_boxes"] == 11.5
        # Reads in the same logical instant show every derived field updated:
        # projected proceeds 6000 + 0.8*0, projected ge 11.5 + 0.8*0.
        pool = scenario["pool"]
        assert pool["posted_ge_boxes"] == 11.5
        assert pool["posted_proceeds_cents"] == 6000
        assert pool["sorted_field_boxes"] == 10
        assert pool["provisional_price_cents_per_ge_box"] == 522, \
            "6000 / 11.5 rounds half-up to 522"
        assert scenario["channels"]["DOM-CM1"]["remaining_boxes"] == 0
        assert scenario["delivery"]["processing_status"] == "SORTED"


class TestSortRunCreateOcc:
    def test_occ_sort_run_recreate_stale_delivery_version(self, api):
        """PRD §2.8: "Creating a sort run requires `expected_delivery_version`
        matching the delivery's current `version`. After a prior run is
        voided, a new run legitimately replaces it, and the create bumps the
        delivery's `version`; a create carrying a stale
        `expected_delivery_version` is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_sort_run_recreate_stale_delivery_version
        """
        set_clock("2026-08-01T00:00:00Z")
        scenario = setup_delivery_received("OC2", gross_boxes=10, planned_boxes=50)
        delivery_id = scenario["delivery"]["id"]
        pre_create_version = scenario["delivery"]["version"]
        first = create_sort_run_for_delivery(delivery_id, 10, 0, 0, 0, 0, 8, 5,
                                             operator_id="op-oc2")
        validate_success(api_client.void_sort_run(
            first["id"], make_operator_headers("op-oc2")))
        # The voided run no longer blocks, but the pre-create version is stale.
        resp = api_client.create_sort_run(
            {"delivery_id": delivery_id, "fancy_boxes": 10, "choice_boxes": 0,
             "standard_boxes": 0, "juice_boxes": 0, "cull_boxes": 0,
             "color_score": 8, "defect_pct": 5,
             "expected_delivery_version": pre_create_version},
            make_operator_headers("op-oc2"))
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        # Recreate with the current version succeeds.
        second = create_sort_run_for_delivery(delivery_id, 10, 0, 0, 0, 0, 8, 5,
                                              operator_id="op-oc2")
        assert second["status"] == "OPEN"
