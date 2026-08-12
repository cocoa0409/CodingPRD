"""Block rotation cycle and the replant-plan workflow (incl. SoD)."""
from test_helpers import (
    ApiErrorId,
    FM,
    OWNER,
    OWNER_ALT_USER_ID,
    advance_block_to,
    bucket_of,
    create_block,
    create_crop_lot,
    create_cull,
    create_replant_plan,
    create_season,
    get_success_data,
    list_buckets,
    setup_harvested_block_bare,
    setup_season_with_block_and_lot,
    validate_error,
    validate_paginated,
    api_client,
    make_farm_manager_headers,
    make_owner_headers,
)

PROPOSER_ID = "fm-carol"


class TestBlockRotationCycle:
    def _setup_depleted_block(self):
        ctx = setup_season_with_block_and_lot(H_6_7=300)
        bucket = bucket_of(ctx["lot"]["id"], "H_6_7")
        return ctx, bucket

    def test_rotation_walks_forward_through_harvested(self, api):
        """PRD §3.1: "Blocks live a cyclic rotation: `RESTING` → `PLANTED` →
        `GROWING` → `HARVESTABLE` → `HARVESTED` → `RESTING`, with each forward
        step beyond the first driven by an explicit rotation advance from a
        `FarmManager`."
        PRD §3.1: "Moving `HARVESTED` → `RESTING` requires that every crop lot
        of the block has reached `DEPLETED`."

        Design: Difficulty/non_linear_state_machine/block_rotation_full_cycle_replant
        """
        ctx, bucket = self._setup_depleted_block()
        b1 = get_success_data(api.advance_rotation(ctx["block"]["id"], FM))
        assert b1["rotation_state"] == "GROWING"
        b2 = get_success_data(api.advance_rotation(ctx["block"]["id"], FM))
        assert b2["rotation_state"] == "HARVESTABLE"
        create_cull(bucket["id"], 300, reason="GRADING")
        lot_now = get_success_data(api.get_crop_lot(ctx["lot"]["id"], FM))
        assert lot_now["status"] == "DEPLETED", (
            "culling every tree auto-depletes the lot"
        )
        b3 = get_success_data(api.advance_rotation(ctx["block"]["id"], FM))
        assert b3["rotation_state"] == "HARVESTED"
        b4 = get_success_data(api.advance_rotation(ctx["block"]["id"], FM))
        assert b4["rotation_state"] == "RESTING", "the cycle closes"

    def test_rested_block_accepts_successor_lot(self, api):
        """PRD §3.1: "A `FarmManager` may plant a new **CropLot** directly on a
        `RESTING` block by naming the `block_id`, the `species`, the
        `planted_year` of the cohort, and `initial_counts` — an object carrying
        an integer count of at least zero for every one of the six height-class
        keys."
        PRD §3.1: "A successful planting creates the lot in `ACTIVE` status,
        creates all six stand buckets with each bucket's `baseline_count` and
        `standing_count` initialized from the supplied counts, and moves the
        block from `RESTING` to `PLANTED`."

        Design: Difficulty/non_linear_state_machine/block_rotation_full_cycle_replant
        """
        ctx, bucket = self._setup_depleted_block()
        advance_block_to(ctx["block"]["id"], "HARVESTABLE")
        create_cull(bucket["id"], 300, reason="GRADING")
        advance_block_to(ctx["block"]["id"], "RESTING")
        lot2 = create_crop_lot(
            ctx["block"]["id"], species="GRAND_FIR", planted_year=2027,
            H_4_5=400,
        )
        assert lot2["status"] == "ACTIVE", "cycle restart: second planting"
        block_now = get_success_data(api.get_block(ctx["block"]["id"], FM))
        assert block_now["rotation_state"] == "PLANTED"
        bucket2 = bucket_of(lot2["id"], "H_4_5")
        assert bucket2["baseline_count"] == 400
        assert bucket2["standing_count"] == 400


class TestReplantProposalGuards:
    def test_propose_on_resting_block_rejected(self, api):
        """PRD §3.1: "When a block reaches `HARVESTED`, a `FarmManager` may
        propose a **ReplantPlan** by naming the `block_id`, the successor
        `species`, and the `planned_count` of seedlings (at least one);
        proposing against a block that is not `HARVESTED` fails with
        `ERR_BLOCK_OCCUPIED`."

        Design: Corner/validations/replant_propose_on_resting_block_rejected
        """
        season = create_season()
        block = create_block(season["id"])
        resp = api.create_replant_plan(
            {"block_id": block["id"], "species": "NOBLE_FIR",
             "planned_count": 400},
            make_farm_manager_headers(PROPOSER_ID),
        )
        validate_error(resp, ApiErrorId.ERR_BLOCK_OCCUPIED)

    def test_rejected_proposal_persists_nothing(self, api):
        """PRD §3.1: "proposing against a block that is not `HARVESTED` fails
        with `ERR_BLOCK_OCCUPIED`."
        PRD §3.1: "Replant plans can be listed filtered by `block_id`."

        Design: Corner/validations/replant_propose_on_resting_block_rejected
        """
        season = create_season()
        block = create_block(season["id"])
        api.create_replant_plan(
            {"block_id": block["id"], "species": "NOBLE_FIR",
             "planned_count": 400},
            make_farm_manager_headers(PROPOSER_ID),
        )
        data, meta = validate_paginated(
            api.list_replant_plans(FM, params={"block_id": block["id"]})
        )
        assert meta["total_count"] == 0


class TestReplantSegregationOfDuties:
    def test_self_approval_rejected(self, api):
        """PRD §3.1: "Both decisions enforce segregation of duties — the
        deciding `X-User-ID` must differ from `proposed_by_user_id`, else
        `ERR_SOD_VIOLATION`."
        PRD §2.1: "A further segregation-of-duties rule governs replant
        approvals: the operator who approves or rejects a replant plan must not
        be the operator who proposed it. A violation is rejected with
        `ERR_SOD_VIOLATION` (HTTP 403)."

        Design: Corner/rbac/replant_approver_must_differ_from_proposer_sod
        """
        ctx = setup_harvested_block_bare(tree_count=50)
        plan = create_replant_plan(ctx["block"]["id"], PROPOSER_ID,
                                   species="DOUGLAS_FIR", planned_count=400)
        assert plan["proposed_by_user_id"] == PROPOSER_ID
        resp = api.approve_replant_plan(
            plan["id"], make_owner_headers(PROPOSER_ID)
        )
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
        plan_now = get_success_data(api.get_replant_plan(plan["id"], FM))
        assert plan_now["status"] == "PROPOSED"

    def test_independent_approval_and_execute_create_successor(self, api):
        """PRD §3.1: "An `Owner` then decides: approval moves the plan to
        `APPROVED` and stamps `approved_by_user_id` — null until this point —
        with the approver's identity, while rejection moves it to `REJECTED`."
        PRD §3.1: "Execution of an `APPROVED` plan by a `FarmManager` re-checks
        that the block is still `HARVESTED` (a block re-occupied in the
        meantime yields `ERR_BLOCK_OCCUPIED`), then creates the successor crop
        lot on the block with the plan's species, a `planted_year` equal to the
        block's season `year`, and six stand buckets whose baselines place the
        entire `planned_count` on `H_4_5` and zero on every other class. The
        block moves `HARVESTED` → `PLANTED`, the plan's `created_crop_lot_id`
        records the server-minted lot identifier, and the plan reaches
        `EXECUTED`."

        Design: Corner/rbac/replant_approver_must_differ_from_proposer_sod
        """
        ctx = setup_harvested_block_bare(tree_count=50)
        assert ctx["block"]["rotation_state"] == "HARVESTED"
        plan = create_replant_plan(ctx["block"]["id"], PROPOSER_ID,
                                   species="DOUGLAS_FIR", planned_count=400)
        approved = get_success_data(
            api.approve_replant_plan(
                plan["id"], make_owner_headers(OWNER_ALT_USER_ID)
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == OWNER_ALT_USER_ID
        executed = get_success_data(
            api.execute_replant_plan(
                plan["id"], make_farm_manager_headers(PROPOSER_ID)
            )
        )
        assert executed["status"] == "EXECUTED"
        new_lot_id = executed["created_crop_lot_id"]
        assert new_lot_id, "server-minted successor lot id recorded"
        block_now = get_success_data(api.get_block(ctx["block"]["id"], FM))
        assert block_now["rotation_state"] == "PLANTED"
        new_buckets = list_buckets(new_lot_id)
        assert new_buckets[0]["height_class"] == "H_4_5"
        assert new_buckets[0]["baseline_count"] == 400
        for b in new_buckets[1:]:
            assert b["baseline_count"] == 0
