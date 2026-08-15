"""Urban forestry: defect routing loop, review lifecycle, award gate, and the
7-day cure buffer at seal."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_forestry_review_id,
    issue_notice,
    make_batch,
    make_bid,
    make_contractor,
    make_draft_notice,
    make_work_item,
    set_clock,
    setup_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
FORESTRY = TEST_USERS["forestry_headers"]


def _city_tree_inventory(parcel_number, segment_code, owner_name,
                         street_address):
    return setup_inventory(
        parcel_number=parcel_number, segment_code=segment_code,
        owner_name=owner_name, street_address=street_address,
        defect_type="TREE_ROOT_UPHEAVAL", measured_offset_inches=0.75,
        area_sqft=30, city_tree_involved=True)


class TestDefectForestryLoop:
    def test_creation_routes_to_forestry(self, api):
        """PRD §3.8: "When an inspector records a `TREE_ROOT_UPHEAVAL` defect
        with `city_tree_involved` set, the defect lands directly in
        `AWAITING_FORESTRY` rather than `OPEN` — `OPEN` is the initial state
        only for non-forestry defects — and a `ForestryReview` is auto-created
        against that `defect_id` in `PENDING` status."

        Design: Difficulty/non_linear_state_machine/defect_forestry_loop_cycle
        """
        bundle = _city_tree_inventory("P-800", "S-800-1", "Ivy Ivy",
                                      "9 Ivy St")
        defect = bundle["defect"]
        assert defect["status"] == "AWAITING_FORESTRY"
        assert defect["severity_class"] == "TRIP_HAZARD", \
            "offset 0.75 >= 0.50"

        rows, _ = validate_paginated(
            api.list_defect_forestry_reviews(defect["id"], FORESTRY))
        assert len(rows) == 1
        assert rows[0]["status"] == "PENDING", \
            "review auto-created by the defect-creation cascade"

    def test_no_conflict_clears_and_reopens_defect(self, api):
        """PRD §3.8: "A `decision` of `NO_CITY_CONFLICT` instead clears the
        review immediately, `PENDING → CLEARED`, with `work_completed_at`
        staying null."
        PRD §3.8: "Either way, clearing frees the linked defect: it moves from
        `AWAITING_FORESTRY` to `UNDER_REPAIR` when a non-terminal notice already
        references it — its repair was noticed while root work was pending —
        and back to `OPEN` otherwise, ready to be drafted onto a future notice."

        Design: Difficulty/non_linear_state_machine/defect_forestry_loop_cycle
        """
        bundle = _city_tree_inventory("P-800", "S-800-1", "Ivy Ivy",
                                      "9 Ivy St")
        defect_id = bundle["defect"]["id"]
        review_id = get_forestry_review_id(defect_id)

        review = validate_success(api.decide_forestry_review(
            review_id, {"decision": "NO_CITY_CONFLICT"}, FORESTRY))
        assert review["status"] == "CLEARED"

        defect = validate_success(api.get_defect(defect_id, COORD))
        assert defect["status"] == "OPEN", \
            "loop closed: OPEN -> AWAITING_FORESTRY -> OPEN"


class TestClearFromPendingRejected:
    def test_clear_requires_decided(self, api):
        """PRD §3.8: "Decisions or clears attempted on a review not in the
        required source state fail with `ERR_INVALID_FORESTRY_STATE`."

        Design: Corner/state_machines/forestry_clear_from_pending_rejected
        """
        bundle = _city_tree_inventory("P-S5", "S-S5-1", "Dee Elm", "55 Elm St")
        review_id = get_forestry_review_id(bundle["defect"]["id"])
        resp = api.clear_forestry_review(review_id, FORESTRY)
        validate_error(resp, ApiErrorId.ERR_INVALID_FORESTRY_STATE)


class TestAwardForestryGate:
    def _setup_gated_batch(self):
        """City-tree defect noticed while AWAITING_FORESTRY, swept DELINQUENT,
        pooled, sealed; one eligible bid; clock past bid_deadline."""
        bundle = _city_tree_inventory("P-1800", "S-1800-1", "Uma Ulmus",
                                      "21 Elm St")
        review_id = get_forestry_review_id(bundle["defect"]["id"])
        notice = issue_notice(make_draft_notice(
            bundle["parcel"]["id"], [bundle["defect"]["id"]])["id"])
        set_clock("2026-09-20T00:00:00Z")
        validate_success(api_client.run_delinquency_sweep(COORD))

        batch = make_batch("NB-7")
        make_work_item(batch["id"], notice["id"], 30, 1300)
        sealed = validate_success(api_client.seal_bid_batch(batch["id"], COORD))
        contractor = make_contractor("Acme Paving", "L-001", "2026-12-31")
        make_bid(batch["id"], contractor["id"], sealed["version"], 1000)
        set_clock("2026-09-23T00:00:00Z")
        return {"batch": sealed, "review_id": review_id}

    def test_pending_and_decided_reviews_block_award(self, api):
        """PRD §3.7: "The forestry gate then requires every review on every
        pooled item's notice defects to be `CLEARED` (else
        `ERR_FORESTRY_NOT_CLEARED`)."

        Design: Difficulty/cross_entity_state_dependency/award_blocked_until_forestry_cleared
        """
        ctx = self._setup_gated_batch()
        resp = api.award_bid_batch(ctx["batch"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FORESTRY_NOT_CLEARED)

        validate_success(api.decide_forestry_review(
            ctx["review_id"], {"decision": "PRUNE_APPROVED"}, FORESTRY))
        resp = api.award_bid_batch(ctx["batch"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FORESTRY_NOT_CLEARED)
        # DECIDED alone does not unblock; the explicit clear is required.

    def test_cleared_review_unblocks_award(self, api):
        """PRD §3.7: "The forestry gate then requires every review on every
        pooled item's notice defects to be `CLEARED` (else
        `ERR_FORESTRY_NOT_CLEARED`)."

        Design: Difficulty/cross_entity_state_dependency/award_blocked_until_forestry_cleared
        """
        ctx = self._setup_gated_batch()
        resp = api.award_bid_batch(ctx["batch"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_FORESTRY_NOT_CLEARED)

        validate_success(api.decide_forestry_review(
            ctx["review_id"], {"decision": "PRUNE_APPROVED"}, FORESTRY))
        cleared = validate_success(
            api.clear_forestry_review(ctx["review_id"], FORESTRY))
        assert cleared["status"] == "CLEARED"

        batch = validate_success(api.award_bid_batch(ctx["batch"]["id"], COORD))
        assert batch["status"] == "AWARDED"


class TestCureBufferBoundary:
    def _setup_cleared_review(self):
        """City-tree defect noticed, swept DELINQUENT; review PRUNE_APPROVED
        then CLEARED at clock 2026-09-20 (work_completed_at 2026-09-20)."""
        bundle = _city_tree_inventory("P-2100", "S-2100-1", "Will Wren",
                                      "34 Wren St")
        review_id = get_forestry_review_id(bundle["defect"]["id"])
        notice = issue_notice(make_draft_notice(
            bundle["parcel"]["id"], [bundle["defect"]["id"]])["id"])
        set_clock("2026-09-16T00:00:00Z")
        validate_success(api_client.run_delinquency_sweep(COORD))
        decide = validate_success(api_client.decide_forestry_review(
            review_id, {"decision": "PRUNE_APPROVED"}, FORESTRY))
        assert decide["status"] == "DECIDED"
        set_clock("2026-09-20T00:00:00Z")
        cleared = validate_success(api_client.clear_forestry_review(review_id,
                                                                    FORESTRY))
        assert cleared["status"] == "CLEARED"
        assert cleared["work_completed_at"] == "2026-09-20T00:00:00Z"
        return notice

    def test_six_day_gap_violates_cure_buffer(self, api):
        """PRD §3.7: "for every pooled item, every forestry review covering
        that item's notice defects that has reached `CLEARED` with a recorded
        `work_completed_at` must have finished root work at least 7 days before
        `work_window_start`; a tighter gap fails the seal with
        `ERR_CURE_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/forestry_cure_buffer_boundary
        """
        notice = self._setup_cleared_review()
        batch = make_batch("NB-D", "2026-09-26", "2026-10-10",
                           "2026-09-24T00:00:00Z")
        item = make_work_item(batch["id"], notice["id"], 30, 1300)

        resp = api.seal_bid_batch(batch["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_CURE_WINDOW_VIOLATION)
        # Window start is 6 days after the clearing: tighter than the buffer.

        # Clean up: the failed seal leaves the item pooled; remove it so later
        # tests in this class can pool the same notice again.
        validate_success(api.remove_work_item(item["id"], COORD))

    def test_exactly_seven_days_satisfies_buffer(self, api):
        """PRD §3.7: "for every pooled item, every forestry review covering
        that item's notice defects that has reached `CLEARED` with a recorded
        `work_completed_at` must have finished root work at least 7 days before
        `work_window_start`; a tighter gap fails the seal with
        `ERR_CURE_WINDOW_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/forestry_cure_buffer_boundary
        """
        notice = self._setup_cleared_review()
        batch = make_batch("NB-E", "2026-09-27", "2026-10-10",
                           "2026-09-24T00:00:00Z")
        make_work_item(batch["id"], notice["id"], 30, 1300)

        sealed = validate_success(api.seal_bid_batch(batch["id"], COORD))
        assert sealed["status"] == "SEALED_FOR_BIDDING", \
            "window start exactly D+7 satisfies the >= 7-day buffer"
