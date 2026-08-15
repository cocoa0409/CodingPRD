"""Failure reports and the replant queue: frozen priority scores, queue ordering,
selector fallback, and lifecycle guards (PRD §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error, validate_paginated,
    create_crop_with_active_recipe, create_loop_rack,
    create_batch, seed_batch, germination_check, set_clock, create_contract,
    setup_queued_replant,
)

FM = TEST_USERS["farm_manager_headers"]
GR = TEST_USERS["grower_headers"]


def _frozen_score_scenario(api):
    """HB healthy (45.00 lb projected into week of 2026-08-24); FB failed with harvest
    3d21h out (urgency 2.0); FB2 failed with harvest 21d out (urgency 1.0). Contract
    commitment 500 lb/wk. Returns (rack1_towers, rr1, rr2)."""
    crop, _ = create_crop_with_active_recipe()
    _, rack1, towers_r1 = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=8)
    _, _, towers_r2 = create_loop_rack(loop_code="WL-B", rack_code="R-02", tower_count=8)
    create_contract(crop["id"], start_date="2026-08-03", end_date="2026-09-28")

    set_clock("2026-08-03T06:00:00Z")
    hb = create_batch(crop["id"], [t["id"] for t in towers_r1[0:4]])
    seed_batch(hb["id"])
    germination_check(hb["id"], 88.0)  # factor 0.90 -> 45.00 lb projected
    fb = create_batch(crop["id"], [t["id"] for t in towers_r1[4:8]])
    seed_batch(fb["id"])
    germination_check(fb["id"], 96.0)

    set_clock("2026-08-20T09:00:00Z")
    validate_success(api.fail_batch(fb["id"], {"cause_category": "PATHOGEN"}, GR))
    fr1 = validate_paginated(api.list_batch_failure_reports(fb["id"], GR))[0][0]
    validate_success(api.triage_failure_report(
        fr1["id"], {"cause_category": "PATHOGEN", "lost_lb_estimate": 50.0}, GR))
    rr1 = validate_success(api.request_replant(fr1["id"], GR), expected_status=201)

    set_clock("2026-08-20T09:30:00Z")
    fb2 = create_batch(crop["id"], [t["id"] for t in towers_r2[0:4]])
    seed_batch(fb2["id"])
    germination_check(fb2["id"], 96.0)
    validate_success(api.fail_batch(fb2["id"], {"cause_category": "NUTRIENT"}, GR))
    fr2 = validate_paginated(api.list_batch_failure_reports(fb2["id"], GR))[0][0]
    validate_success(api.triage_failure_report(
        fr2["id"], {"cause_category": "NUTRIENT", "lost_lb_estimate": 50.0}, GR))
    rr2 = validate_success(api.request_replant(fr2["id"], GR), expected_status=201)
    return towers_r1, rr1, rr2


class TestReplantPriorityScore:
    def test_priority_scores_computed_at_queue_time(self, api):
        """PRD §3.6: "the `priority_score` is the shortfall pounds times the crop's
        `margin_cents_per_lb` times the urgency factor, rounded half-up to two
        decimals" where "urgency doubles the score — a factor of 2.0 — when the failed
        batch's projected harvest lies no more than 14 days after the failure report's
        `created_at`, and is 1.0 otherwise" and "the shortfall is commitment minus
        supply, floored at zero."

        Design: Difficulty/combinatorial_formula/replant_priority_frozen_evaluation_order
        """
        _, rr1, rr2 = _frozen_score_scenario(api)
        # RR1: shortfall 455 (500 - 45.00 supply in week of 2026-08-24) x 300 x 2.0
        assert rr1["priority_score"] == pytest.approx(273000.00)
        # RR2: week of 2026-09-10 has zero qualifying supply: 500 x 300 x 1.0
        assert rr2["priority_score"] == pytest.approx(150000.00)
        assert rr1["replant_status"] == "QUEUED"

    def test_score_frozen_after_sibling_approval_and_best_fit_selection(self, api):
        """PRD §3.6: "a `priority_score` computed once at queue time and never
        recomputed afterward, no matter how supply later shifts" and "Candidate racks
        rank by spare room after use — idle count minus `towers_needed` ascending, so
        the fullest rack after placement wins ... within the chosen rack, towers are
        taken in `tower_index` ascending order."

        Design: Difficulty/combinatorial_formula/replant_priority_frozen_evaluation_order
        """
        towers_r1, rr1, rr2 = _frozen_score_scenario(api)
        approved = validate_success(api.approve_replant_request(rr1["id"], FM))
        assert approved["replant_status"] == "CONVERTED"

        spawned, meta = validate_paginated(api.list_replant_batches(rr1["id"], FM))
        assert meta["total_count"] == 1, "approval creates exactly one replacement batch"
        # Best fit: R-01 has exactly 4 free towers (slack 0) vs R-02 (slack 4).
        t5 = validate_success(api.get_tower(towers_r1[4]["id"], FM))
        assert t5["tower_status"] == "ALLOCATED"

        rr2_after = validate_success(api.get_replant_request(rr2["id"], FM))
        assert rr2_after["priority_score"] == pytest.approx(150000.00), \
            "the frozen score never recomputes even after supply changes"


class TestReplantQueueOrdering:
    def test_queue_orders_score_desc_then_failure_created_at(self, api):
        """PRD §3.6: "The queued listing follows the same ordering: `priority_score`
        descending, ties broken by the linked failure report's `created_at` ascending,
        never by identifier."

        Design: Corner/calculations/replant_queue_ordering_score_desc_then_created_at
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=2)
        create_contract(crop["id"], start_date="2026-08-03", end_date="2026-09-28")

        set_clock("2026-08-03T06:00:00Z")
        b1 = create_batch(crop["id"], [towers[0]["id"]])
        seed_batch(b1["id"])
        germination_check(b1["id"], 96.0)
        b2 = create_batch(crop["id"], [towers[1]["id"]])
        seed_batch(b2["id"])
        germination_check(b2["id"], 96.0)

        set_clock("2026-08-20T09:00:00Z")
        validate_success(api.fail_batch(b1["id"], {"cause_category": "PATHOGEN"}, GR))
        set_clock("2026-08-20T09:01:00Z")
        validate_success(api.fail_batch(b2["id"], {"cause_category": "PATHOGEN"}, GR))

        rr_ids = []
        for b in (b1, b2):
            fr = validate_paginated(api.list_batch_failure_reports(b["id"], GR))[0][0]
            validate_success(api.triage_failure_report(
                fr["id"], {"cause_category": "PATHOGEN", "lost_lb_estimate": 12.5}, GR))
            rr = validate_success(api.request_replant(fr["id"], GR), expected_status=201)
            # supply collapsed to zero before either request: both scores equal
            assert rr["priority_score"] == pytest.approx(300000.00)
            rr_ids.append(rr["id"])

        queued, meta = validate_paginated(
            api.list_replant_requests(FM, params={"replant_status": "QUEUED"}))
        assert meta["total_count"] == 2
        assert [q["id"] for q in queued] == rr_ids, \
            "equal scores tie-break on the failure report's created_at ascending"


class TestFailureReplantLifecycle:
    def test_failure_close_blocked_while_replant_queued(self, api):
        """PRD §3.6: "a report whose replant request is still `QUEUED` refuses to close
        with `ERR_REPLANT_STILL_QUEUED`."

        Design: Corner/state_machines/failure_close_blocked_while_replant_queued
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        _, failure, replant = setup_queued_replant(crop["id"], [towers[0]["id"]])

        resp = api.close_failure_report(failure["id"], GR)
        validate_error(resp, ApiErrorId.ERR_REPLANT_STILL_QUEUED)

        validate_success(api.drop_replant_request(replant["id"], FM))
        closed = validate_success(api.close_failure_report(failure["id"], GR))
        assert closed["report_status"] == "CLOSED"

    def test_replant_drop_is_terminal(self, api):
        """PRD §3.6: "A `FarmManager` may instead drop a queued request, ending it at
        `DROPPED`" — approval is defined only for "a queued request", so approving a
        dropped one is an invalid lifecycle transition (PRD §2.10 tier 5).

        Design: Corner/state_machines/replant_drop_is_terminal
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        _, _, replant = setup_queued_replant(crop["id"], [towers[0]["id"]])
        validate_success(api.drop_replant_request(replant["id"], FM))

        resp = api.approve_replant_request(replant["id"], FM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        batches, meta = validate_paginated(api.list_replant_batches(replant["id"], FM))
        assert meta["total_count"] == 0, "a dropped request never spawns a batch"


class TestReplantApprovalGates:
    def test_replant_no_towers_empty_pool_rejected(self, api):
        """PRD §3.6: "An empty candidate pool rejects the approval outright with
        `ERR_REPLANT_NO_TOWERS`; the selector never allocates partially."

        Design: Corner/errors/replant_no_towers_empty_pool_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        _, rack, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        _, _, replant = setup_queued_replant(crop["id"], [towers[0]["id"]])
        # The failure released the tower, so the rack can leave service; with the only
        # rack OUT_OF_SERVICE the selector pool is empty.
        validate_success(api.set_rack_out_of_service(rack["id"], FM))

        resp = api.approve_replant_request(replant["id"], FM)
        validate_error(resp, ApiErrorId.ERR_REPLANT_NO_TOWERS)
        after = validate_success(api.get_replant_request(replant["id"], FM))
        assert after["replant_status"] == "QUEUED"

    def test_replant_already_queued_rejected(self, api):
        """PRD §3.6: "provided no `QUEUED` **ReplantRequest** already exists for that
        failure — a duplicate is `ERR_REPLANT_ALREADY_QUEUED`, while an earlier
        `DROPPED` request does not block a fresh one."

        Design: Corner/errors/replant_already_queued_rejected
        """
        crop, _ = create_crop_with_active_recipe()
        _, _, towers = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=1)
        _, failure, replant = setup_queued_replant(crop["id"], [towers[0]["id"]])

        resp = api.request_replant(failure["id"], GR)
        validate_error(resp, ApiErrorId.ERR_REPLANT_ALREADY_QUEUED)

        validate_success(api.drop_replant_request(replant["id"], FM))
        fresh = validate_success(api.request_replant(failure["id"], GR), expected_status=201)
        assert fresh["id"] != replant["id"], "a fresh request creates a new replant row"
        assert fresh["replant_status"] == "QUEUED"
