"""Surveys, re-baselining, the over-reservation sweep, and cull records."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    OWNER,
    advance_season_to,
    allocate_order,
    bucket_of,
    create_buyer,
    create_crop_lot,
    create_cull,
    create_draft_order,
    create_season,
    create_survey,
    get_success_data,
    list_buckets,
    list_order_allocations,
    post_ticket,
    set_clock,
    setup_booking_season,
    setup_harvest_with_crew,
    setup_season_with_block_and_lot,
    submit_order,
    validate_error,
    validate_paginated,
    api_client,
    make_buyer_headers,
    create_crew,
)


class TestBookVsSurveyStock:
    def _setup_shrink_scenario(self):
        """Lot H_6_7 baseline 300; order of 30 fully cut; cull of 10.
        Book stock before survey: 300 - 30 - 10 = 260. Survey reports 250."""
        ctx = setup_harvest_with_crew(quantity=30, unit_price_cents=400,
                                      H_6_7=300, crew_size=5)
        # Cut all 30 reserved trees.
        post_ticket(
            ctx["crew"], ctx["block"]["id"],
            [{"allocation_id": ctx["allocation"]["id"], "cut_count": 30}],
        )
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        create_cull(bucket["id"], 10, reason="DISEASE")
        return ctx

    def test_book_stock_drifts_from_physical_reality(self, api):
        """PRD §2.8: "The **book stock** is the ledger value exposed as
        `standing_count` on every read: the epoch baseline minus every recorded
        consumption event (cuts, culls, tag claims, consignment deliveries, net
        of reversals). The **survey stock** is the physical count a field crew
        reports. The two drift apart whenever unrecorded shrink occurs, and
        identical bucket data can therefore yield a different standing after a
        survey than before it."

        Design: Difficulty/dual_variant_calc/book_stock_vs_survey_stock_shrink
        """
        ctx = self._setup_shrink_scenario()
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 260, "book stock: 300 - 30 cut - 10 culled"
        assert bucket["cut_cumulative"] == 30
        assert bucket["culled_cumulative"] == 10
        assert bucket["last_shrink_delta"] is None, "null before first post"
        # The draft survey touches nothing until posted.
        survey = create_survey(ctx["lot"]["id"], H_6_7=250)
        assert survey["status"] == "DRAFT"
        bucket_after_draft = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_after_draft["standing_count"] == 260

    def test_post_adopts_survey_stock_and_records_shrink(self, api):
        """PRD §3.2: "On a successful post, each of the lot's six buckets is
        re-baselined: the bucket's `last_shrink_delta` records the surveyed
        count minus the book `standing_count` (negative meaning unrecorded
        loss), `baseline_count` becomes the surveyed count, `standing_count` is
        reset to that same physical count, and all four epoch counters —
        `cut_cumulative`, `culled_cumulative`, `ucut_sold_cumulative`,
        `consigned_cumulative` — reset to zero."

        Design: Difficulty/dual_variant_calc/book_stock_vs_survey_stock_shrink
        """
        ctx = self._setup_shrink_scenario()
        survey = create_survey(ctx["lot"]["id"], H_6_7=250)
        lot_now = get_success_data(api.get_crop_lot(ctx["lot"]["id"], FM))
        posted = get_success_data(
            api.post_survey(survey["id"], lot_now["version"], FM)
        )
        assert posted["status"] == "POSTED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["baseline_count"] == 250
        assert bucket["standing_count"] == 250
        assert bucket["last_shrink_delta"] == -10  # 250 - 260
        assert bucket["cut_cumulative"] == 0, "epoch counters reset"
        assert bucket["culled_cumulative"] == 0


class TestSurveySupersession:
    def _setup_two_surveys(self):
        ctx = setup_season_with_block_and_lot(H_6_7=300)
        lot_v1 = ctx["lot"]["version"]
        survey_a = create_survey(ctx["lot"]["id"], H_6_7=290)
        survey_b = create_survey(ctx["lot"]["id"], H_6_7=285)
        return ctx, lot_v1, survey_a, survey_b

    def test_first_post_increments_lot_version(self, api):
        """PRD §3.2: "The survey's `posted_at` stamps the logical-clock instant
        of posting, the previously `POSTED` survey of the same lot moves to
        `SUPERSEDED`, and the lot's `version` increments."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource, including mutations the
        server applies automatically as side effects of other operations."

        Design: Corner/state_machines/survey_supersedes_prior_posted
        """
        ctx, lot_v1, survey_a, _survey_b = self._setup_two_surveys()
        assert lot_v1 == 1
        posted = get_success_data(api.post_survey(survey_a["id"], lot_v1, FM))
        assert posted["status"] == "POSTED"
        lot_now = get_success_data(api.get_crop_lot(ctx["lot"]["id"], FM))
        assert lot_now["version"] == 2

    def test_second_post_supersedes_prior_and_rebaselines(self, api):
        """PRD §3.2: "The survey's `posted_at` stamps the logical-clock instant
        of posting, the previously `POSTED` survey of the same lot moves to
        `SUPERSEDED`, and the lot's `version` increments."
        PRD §3.1: "Crop lots can be listed and filtered by `block_id`; a lot's
        six buckets and its survey history are reachable as sub-resources of
        the lot, and every survey list is ordered by creation ascending."
        PRD §3.2: "the bucket's `last_shrink_delta` records the surveyed count
        minus the book `standing_count` (negative meaning unrecorded loss),
        `baseline_count` becomes the surveyed count, `standing_count` is reset
        to that same physical count".

        Design: Corner/state_machines/survey_supersedes_prior_posted
        """
        ctx, lot_v1, survey_a, survey_b = self._setup_two_surveys()
        get_success_data(api.post_survey(survey_a["id"], lot_v1, FM))
        lot_now = get_success_data(api.get_crop_lot(ctx["lot"]["id"], FM))
        get_success_data(api.post_survey(survey_b["id"], lot_now["version"], FM))
        data, meta = validate_paginated(api.list_lot_surveys(ctx["lot"]["id"], FM))
        assert meta["total_count"] == 2
        assert data[0]["id"] == survey_a["id"]
        assert data[0]["status"] == "SUPERSEDED"
        assert data[1]["id"] == survey_b["id"]
        assert data[1]["status"] == "POSTED"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["baseline_count"] == 285
        assert bucket["last_shrink_delta"] == -5  # 285 - 290


class TestSurveyPostOCC:
    def test_sequential_stale_post_rejected_412(self, api):
        """PRD §2.10: "Posting an inventory survey requires the request to
        carry `expected_crop_lot_version` equal to the target crop lot's
        current `version`; because posting a survey legitimately supersedes the
        previously posted survey, a second writer holding a stale lot version
        must lose with 412 rather than silently re-baselining buckets against
        counts the first writer already replaced."

        Design: Corner/complexity_layers/survey_post_stale_lot_version_occ
        """
        ctx = setup_season_with_block_and_lot(H_6_7=300)
        lot_v1 = ctx["lot"]["version"]
        survey_a = create_survey(ctx["lot"]["id"], H_6_7=295)
        survey_b = create_survey(ctx["lot"]["id"], H_6_7=290)
        posted = get_success_data(api.post_survey(survey_a["id"], lot_v1, FM))
        assert posted["status"] == "POSTED"
        resp = api.post_survey(survey_b["id"], lot_v1, FM)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_stale_post_leaves_lot_and_bucket_untouched(self, api):
        """PRD §2.10: "Posting an inventory survey requires the request to
        carry `expected_crop_lot_version` equal to the target crop lot's
        current `version`; because posting a survey legitimately supersedes the
        previously posted survey, a second writer holding a stale lot version
        must lose with 412 rather than silently re-baselining buckets against
        counts the first writer already replaced."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation of the resource, including mutations the
        server applies automatically as side effects of other operations."

        Design: Corner/complexity_layers/survey_post_stale_lot_version_occ
        """
        ctx = setup_season_with_block_and_lot(H_6_7=300)
        lot_v1 = ctx["lot"]["version"]
        survey_a = create_survey(ctx["lot"]["id"], H_6_7=295)
        survey_b = create_survey(ctx["lot"]["id"], H_6_7=290)
        get_success_data(api.post_survey(survey_a["id"], lot_v1, FM))
        api.post_survey(survey_b["id"], lot_v1, FM)
        lot_now = get_success_data(api.get_crop_lot(ctx["lot"]["id"], FM))
        assert lot_now["version"] == 2, "rejected post does not bump the lot"
        data, _ = validate_paginated(api.list_lot_surveys(ctx["lot"]["id"], FM))
        survey_b_now = [s for s in data if s["id"] == survey_b["id"]][0]
        assert survey_b_now["status"] == "DRAFT"
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["baseline_count"] == 295, "first post's baseline survives"


class TestOverReservationSweep:
    def _setup_over_reserved(self):
        """Bucket H_6_7 standing 300; order A (60) allocated first, order B
        (40) second; both ALLOCATED; reserved 100. A survey posting 50 strands
        the reservations."""
        ctx = setup_booking_season(H_6_7=300)
        buyer = create_buyer()
        order_a = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=60, unit_price_cents=400,
        )
        order_a = submit_order(order_a["id"], buyer["id"])
        allocate_order(order_a["id"], 60, order_a["version"])
        order_b = create_draft_order(
            ctx["season"]["id"], buyer["id"], quantity=40, unit_price_cents=400,
        )
        order_b = submit_order(order_b["id"], buyer["id"])
        allocate_order(order_b["id"], 40, order_b["version"])
        lot_v = get_success_data(api_client.get_crop_lot(ctx["lot"]["id"], FM))["version"]
        survey = create_survey(ctx["lot"]["id"], H_6_7=50)
        return ctx, order_a, order_b, survey, lot_v

    def test_sweep_releases_allocations_youngest_first(self, api):
        """PRD §3.2: "The sweep releases whole allocations against that bucket
        in youngest-first order (most recently created first), restoring each
        allocation's quantity to the bucket's `reserved_count` and deducting it
        from the serving order's `allocated_qty`, until reserved no longer
        exceeds standing or no allocations in `RESERVED` remain."
        PRD §3.2: "Only `RESERVED` allocations are ever swept — trees already
        `CUT` or `LOADED` are never touched — and each released allocation
        moves to `RELEASED`."

        Design: Difficulty/transitive_cascade/survey_post_overreservation_sweep_cascade
        """
        ctx, order_a, order_b, survey, lot_v = self._setup_over_reserved()
        get_success_data(api.post_survey(survey["id"], lot_v, FM))
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 50
        assert bucket["baseline_count"] == 50
        assert bucket["reserved_count"] == 0, (
            "sweep released B's 40 then A's 60 until reserved <= standing"
        )
        allocs_a = list_order_allocations(order_a["id"])
        allocs_b = list_order_allocations(order_b["id"])
        assert allocs_a[0]["status"] == "RELEASED"
        assert allocs_b[0]["status"] == "RELEASED"

    def test_swept_orders_regress_to_submitted(self, api):
        """PRD §3.2: "An order that drops below full allocation through the
        sweep regresses from `ALLOCATED` back to `SUBMITTED`."
        PRD §3.4: "Conversely, whenever a release or an over-reservation sweep
        leaves `allocated_qty` below `quantity`, an `ALLOCATED` order regresses
        to `SUBMITTED`."

        Design: Difficulty/transitive_cascade/survey_post_overreservation_sweep_cascade
        """
        _ctx, order_a, order_b, survey, lot_v = self._setup_over_reserved()
        get_success_data(api.post_survey(survey["id"], lot_v, FM))
        order_a_now = get_success_data(api.get_order(order_a["id"], FM))
        order_b_now = get_success_data(api.get_order(order_b["id"], FM))
        assert order_a_now["status"] == "SUBMITTED"
        assert order_a_now["allocated_qty"] == 0
        assert order_b_now["status"] == "SUBMITTED"
        assert order_b_now["allocated_qty"] == 0


class TestCullBoundaries:
    def test_cull_beyond_available_rejected(self, api):
        """PRD §3.2: "The count may not exceed the bucket's `available_count`,
        failing with `ERR_CULL_EXCEEDS_STANDING` (HTTP 422) when it does."

        Design: Corner/validations/cull_exceeding_available_returns_error
        """
        ctx = setup_season_with_block_and_lot(H_6_7=50)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        resp = api.create_cull_record(
            {"bucket_id": bucket["id"], "count": 51, "reason": "DISEASE"}, FM
        )
        validate_error(resp, ApiErrorId.ERR_CULL_EXCEEDS_STANDING)
        bucket_now = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_now["standing_count"] == 50, "rejected cull changes nothing"

    def test_cull_exactly_available_zeroes_bucket_and_depletes_lot(self, api):
        """PRD §3.2: "Recording a cull decrements the bucket's `standing_count`
        and accrues into `culled_cumulative`; it is permitted in any posture
        except `CLOSED`, and it can tip a fully consumed lot into `DEPLETED`."
        PRD §2.8: "When any consumption event leaves every bucket of a crop lot
        with zero standing, zero reserved, and zero active tags, the lot
        automatically transitions from `ACTIVE` to `DEPLETED`, incrementing the
        lot's `version` and refreshing its `updated_at`."

        Design: Corner/validations/cull_exceeding_available_returns_error
        """
        ctx = setup_season_with_block_and_lot(H_6_7=50)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        cull = create_cull(bucket["id"], 50, reason="DISEASE")
        assert cull["count"] == 50
        bucket_now = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_now["standing_count"] == 0
        assert bucket_now["culled_cumulative"] == 50
        lot_now = get_success_data(api.get_crop_lot(ctx["lot"]["id"], FM))
        assert lot_now["status"] == "DEPLETED"
