"""Choose-and-cut tags: sale claims, redeem, expiry sweep, and block gates."""
from test_helpers import (
    ApiErrorId,
    CLOCK,
    FM,
    OWNER,
    advance_block_to,
    advance_season_to,
    bucket_of,
    create_block,
    create_crop_lot,
    create_season,
    create_ucut_tag,
    get_success_data,
    set_clock,
    setup_harvest_season,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)


class TestTagSaleAndRedeem:
    def test_tag_sale_claims_tree_and_sets_expiry(self, api):
        """PRD §3.7: "The tree is claimed the moment the tag is sold: the
        bucket's `standing_count` drops by one and its `tagged_active_count`
        rises by one."
        PRD §3.7: "Each tag carries an `expires_at` set exactly forty-eight
        hours after its creation on the logical clock, and the tag is born
        `ACTIVE`."

        Design: Corner/state_machines/tag_redeem_side_effects_on_bucket
        """
        ctx = setup_harvest_season(ucut=True, species="NORDMANN_FIR", H_6_7=10)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        tag = create_ucut_tag(ctx["block"]["id"], bucket["id"],
                              customer_name="Patron A", price_cents=6500)
        assert tag["status"] == "ACTIVE"
        # Created at the logical clock 2026-11-05T08:00:00Z; +48h exactly.
        assert tag["expires_at"] == "2026-11-07T08:00:00Z"
        bucket_now = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_now["standing_count"] == 9
        assert bucket_now["tagged_active_count"] == 1

    def test_redeem_converts_claim_to_sale(self, api):
        """PRD §3.7: "When the customer cuts their tree, redeeming the tag — a
        `HARVEST`-posture operation — moves it to terminal `REDEEMED`: the
        bucket's `tagged_active_count` drops by one and `ucut_sold_cumulative`
        rises by one, the tree now permanently gone from the field ledger."

        Design: Corner/state_machines/tag_redeem_side_effects_on_bucket
        """
        ctx = setup_harvest_season(ucut=True, species="NORDMANN_FIR", H_6_7=10)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        tag = create_ucut_tag(ctx["block"]["id"], bucket["id"],
                              customer_name="Patron A", price_cents=6500)
        redeemed = get_success_data(api.redeem_ucut_tag(tag["id"], FM))
        assert redeemed["status"] == "REDEEMED"
        bucket_now = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_now["tagged_active_count"] == 0
        assert bucket_now["ucut_sold_cumulative"] == 1
        assert bucket_now["standing_count"] == 9, "redeem does not return the tree"


class TestTagBlockDesignation:
    def _setup_two_blocks(self):
        season = create_season()
        blk_n = create_block(season["id"], block_code="B-N", acreage=5.0)
        lot_n = create_crop_lot(blk_n["id"], H_6_7=10)
        advance_block_to(blk_n["id"], "HARVESTABLE")
        blk_u = create_block(season["id"], block_code="B-U", acreage=5.0,
                             ucut_designated=True)
        lot_u = create_crop_lot(blk_u["id"], H_6_7=10)
        advance_block_to(blk_u["id"], "HARVESTABLE")
        set_clock(CLOCK["HARVEST_DAY"])
        advance_season_to(season["id"], "HARVEST")
        return season, blk_n, lot_n, blk_u, lot_u

    def test_tag_on_non_designated_block_rejected(self, api):
        """PRD §3.7: "The block must be `HARVESTABLE`
        (`ERR_BLOCK_NOT_HARVESTABLE`), must be flagged `ucut_designated`
        (`ERR_BLOCK_NOT_UCUT`, HTTP 422), must be the very block hosting the
        bucket's lot, and the bucket must have at least one tree standing
        (`ERR_BUCKET_EMPTY`, HTTP 422)."

        Design: Corner/validations/tag_on_non_ucut_block_rejected
        """
        _season, blk_n, lot_n, _blk_u, _lot_u = self._setup_two_blocks()
        bucket_n = bucket_of(lot_n["id"], "H_6_7")
        resp = api.create_ucut_tag(
            {"block_id": blk_n["id"], "bucket_id": bucket_n["id"],
             "customer_name": "Patron X", "price_cents": 6000},
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_BLOCK_NOT_UCUT)
        bucket_now = bucket_of(lot_n["id"], "H_6_7")
        assert bucket_now["standing_count"] == 10, "rejected tag claims nothing"

    def test_tag_on_designated_block_accepted(self, api):
        """PRD §3.7: "During `HARVEST` posture, a `FarmManager` sells a
        **UcutTag** naming the `block_id`, the `bucket_id` whose height class
        the customer wants, the `customer_name`, and the gate `price_cents`."
        PRD §3.1: "A block flagged `ucut_designated` (defaulting to false when
        omitted) is open to choose-and-cut retail customers once harvestable."

        Design: Corner/validations/tag_on_non_ucut_block_rejected
        """
        _season, _blk_n, _lot_n, blk_u, lot_u = self._setup_two_blocks()
        bucket_u = bucket_of(lot_u["id"], "H_6_7")
        tag = create_ucut_tag(blk_u["id"], bucket_u["id"],
                              customer_name="Patron Y", price_cents=6000)
        assert tag["status"] == "ACTIVE"


class TestTagOnEmptyBucket:
    def test_empty_bucket_rejects_tag_sale(self, api):
        """PRD §3.7: "The block must be `HARVESTABLE`
        (`ERR_BLOCK_NOT_HARVESTABLE`), must be flagged `ucut_designated`
        (`ERR_BLOCK_NOT_UCUT`, HTTP 422), must be the very block hosting the
        bucket's lot, and the bucket must have at least one tree standing
        (`ERR_BUCKET_EMPTY`, HTTP 422)."

        Design: Corner/validations/tag_on_empty_bucket_rejected
        """
        ctx = setup_harvest_season(ucut=True, species="NORDMANN_FIR",
                                   H_5_6=5, H_6_7=0)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket["standing_count"] == 0
        resp = api.create_ucut_tag(
            {"block_id": ctx["block"]["id"], "bucket_id": bucket["id"],
             "customer_name": "Patron Z", "price_cents": 6000},
            FM,
        )
        validate_error(resp, ApiErrorId.ERR_BUCKET_EMPTY)
        bucket_now = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_now["tagged_active_count"] == 0
        data, meta = validate_paginated(
            api.list_ucut_tags(FM, params={"bucket_id": bucket["id"]})
        )
        assert meta["total_count"] == 0


class TestTagExpirySweep:
    def test_tag_expiring_exactly_now_is_swept(self, api):
        """PRD §3.8: "First, every choose-and-cut tag of the season still
        `ACTIVE` whose `expires_at` is at or before the logical clock — a tag
        expiring exactly now expires — moves to `EXPIRED`, returning its tree
        to the bucket's standing pool."
        PRD §3.8: "Fourth, the season's `ops_run_index` increments by one,
        marking the checkpoint."

        Design: Corner/complexity_layers/ucut_tag_expiry_sweep_restores_tree
        """
        ctx = setup_harvest_season(ucut=True, species="NORDMANN_FIR", H_6_7=10)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        tag = create_ucut_tag(ctx["block"]["id"], bucket["id"],
                              customer_name="Patron E", price_cents=6000)
        set_clock("2026-11-07T08:00:00Z")  # exactly expires_at
        season = get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        assert season["ops_run_index"] == 1
        tag_now = get_success_data(api.get_ucut_tag(tag["id"], FM))
        assert tag_now["status"] == "EXPIRED", "<= boundary sweeps the tag"

    def test_expiry_returns_tree_without_a_sale(self, api):
        """PRD §3.7: "Finally, the ops-run checkpoint sweeps any active tag
        whose `expires_at` has been reached to terminal `EXPIRED` with the same
        return-to-pool effect."
        PRD §3.7: "Releasing a tag early, also a `HARVEST`-posture operation,
        moves it to terminal `RELEASED` and returns the tree to the pool:
        `tagged_active_count` drops by one and `standing_count` rises by one."

        Design: Corner/complexity_layers/ucut_tag_expiry_sweep_restores_tree
        """
        ctx = setup_harvest_season(ucut=True, species="NORDMANN_FIR", H_6_7=10)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        create_ucut_tag(ctx["block"]["id"], bucket["id"],
                        customer_name="Patron E", price_cents=6000)
        set_clock("2026-11-07T08:00:00Z")
        get_success_data(api.run_ops(ctx["season"]["id"], OWNER))
        bucket_now = bucket_of(ctx["lot"]["id"], "H_6_7")
        assert bucket_now["standing_count"] == 10, "tree returns to the pool"
        assert bucket_now["tagged_active_count"] == 0
        assert bucket_now["ucut_sold_cumulative"] == 0, "an expiry is not a sale"
