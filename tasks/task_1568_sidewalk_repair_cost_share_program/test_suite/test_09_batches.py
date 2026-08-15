"""Bid batch lifecycle: pooling, sealing, award cascade, start-work, cancel."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    issue_notice,
    make_batch,
    make_defect,
    make_draft_notice,
    make_owner,
    make_parcel,
    make_segment,
    make_work_item,
    set_clock,
    setup_bid,
    setup_delinquent_notice,
    setup_sealed_batch,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
INSP2 = TEST_USERS["inspector2_headers"]


class TestBatchAwardCascade:
    def _setup_two_notice_batch(self):
        """Two parcels, each with one defect and a swept DELINQUENT notice,
        pooled into one sealed batch with a single 1000c bid."""
        owners, notices, segments = [], [], []
        for idx, (name, pnum, addr) in enumerate(
                [("Kim Kat", "P-1001", "11 Kat St"),
                 ("Lee Lark", "P-1002", "12 Lark St")]):
            owner = make_owner(name, addr)
            parcel = make_parcel(owner["id"], pnum, addr, "LOCAL")
            segment = make_segment(parcel["id"], f"S-100{idx + 1}-1")
            defect = make_defect(segment["id"], "SPALLING",
                                 50 if idx == 0 else 80)
            notice = issue_notice(
                make_draft_notice(parcel["id"], [defect["id"]])["id"])
            owners.append(owner)
            notices.append(notice)
            segments.append(segment)

        set_clock("2026-09-20T00:00:00Z")
        sweep = validate_success(api_client.run_delinquency_sweep(COORD))
        assert sweep["swept_notice_count"] == 2

        batch = make_batch("NB-3", "2026-09-25", "2026-10-15",
                           "2026-09-22T00:00:00Z")
        item1 = make_work_item(batch["id"], notices[0]["id"], 50, 1300)
        item2 = make_work_item(batch["id"], notices[1]["id"], 80, 1300)
        sealed = validate_success(api_client.seal_bid_batch(batch["id"], COORD))

        bundle = {"batch": sealed, "batch_version": sealed["version"]}
        setup_bid(bundle, unit_rate_cents=1000)
        set_clock("2026-09-23T00:00:00Z")
        return {"notices": notices, "segments": segments,
                "items": [item1, item2], "batch": bundle["batch"],
                "bid": bundle["bid"], "contractor": bundle["contractor"]}

    def test_award_marks_bid_and_items(self, api):
        """PRD §3.7: "The winning bid moves from `SUBMITTED` to `AWARDED` with
        its `evaluated_total_cents` frozen into the batch's `awarded_total_cents`
        and its `id` recorded as `awarded_bid_id`; every other `SUBMITTED` bid
        becomes `NOT_AWARDED`. The cascade continues downward: each `POOLED`
        work item becomes `SCHEDULED`"

        Design: Difficulty/transitive_cascade/batch_award_cascade
        """
        ctx = self._setup_two_notice_batch()
        batch = validate_success(api.award_bid_batch(ctx["batch"]["id"], COORD))
        assert batch["status"] == "AWARDED"
        assert batch["awarded_bid_id"] == ctx["bid"]["id"]
        assert batch["awarded_total_cents"] == 130000, \
            "1000 cents/sqft x 130 pooled sqft"

        bid = validate_success(api.get_bid(ctx["bid"]["id"], COORD))
        assert bid["status"] == "AWARDED", "link 1: winning bid"
        for item in ctx["items"]:
            refreshed = validate_success(api.get_work_item(item["id"], COORD))
            assert refreshed["status"] == "SCHEDULED", "link 2: items scheduled"

    def test_award_cascades_to_notices_and_segments(self, api):
        """PRD §3.7: "each pooled notice moves from `DELINQUENT` to
        `CITY_REPAIR_SCHEDULED`; and the segments of the referenced defects move
        to `REPAIR_IN_PROGRESS`."

        Design: Difficulty/transitive_cascade/batch_award_cascade
        """
        ctx = self._setup_two_notice_batch()
        validate_success(api.award_bid_batch(ctx["batch"]["id"], COORD))

        for notice in ctx["notices"]:
            refreshed = validate_success(
                api.get_repair_notice(notice["id"], COORD))
            assert refreshed["status"] == "CITY_REPAIR_SCHEDULED", \
                "link 3: notices scheduled"
        segment = validate_success(api.get_segment(ctx["segments"][0]["id"],
                                                   COORD))
        assert segment["status"] == "REPAIR_IN_PROGRESS", \
            "segment fan-out of the award cascade"


class TestWorkItemAndBatchStates:
    def test_verify_pooled_item_rejected(self, api):
        """PRD §3.7: "an `Inspector` verifies each completed item —
        `WORK_COMPLETED → VERIFIED`"
        PRD §2.7: "The target resource must be in the state the requested
        transition requires, else the transition's specific state error (HTTP
        409)"

        Design: Corner/state_machines/verify_pooled_work_item_rejected
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-S7",
            segment_code="S-S7-1", owner_name="Fay Fir",
            street_address="57 Fir St")
        batch = make_batch("NB-S7")
        item = make_work_item(batch["id"], bundle["notice"]["id"], 50, 1300)
        assert item["status"] == "POOLED"

        resp = api.verify_work_item(item["id"], INSP2)
        validate_error(resp, ApiErrorId.ERR_INVALID_WORK_ITEM_STATE)

    def test_seal_empty_batch_rejected(self, api):
        """PRD §3.7: "Sealing the batch — `OPEN_FOR_ITEMS → SEALED_FOR_BIDDING`
        — requires at least one `POOLED` item (else `ERR_EMPTY_BATCH`)"

        Design: Corner/errors/seal_empty_batch_rejected
        """
        batch = make_batch("NB-T8")
        assert batch["status"] == "OPEN_FOR_ITEMS"
        assert batch["estimated_total_cents"] == 0
        resp = api.seal_bid_batch(batch["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH)

    def test_batch_cancel_cascades_and_locks_terminal(self, api):
        """PRD §3.7: "Cancelling a batch in `OPEN_FOR_ITEMS` or
        `SEALED_FOR_BIDDING` — anything later fails with
        `ERR_INVALID_BATCH_STATE` — moves every `POOLED` item to `REMOVED` while
        leaving the referenced notices `DELINQUENT`; cancelling a sealed batch
        additionally moves every `SUBMITTED` bid to `NOT_AWARDED`."

        Design: Corner/state_machines/batch_cancel_cascades_and_locks_terminal
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-S10",
            segment_code="S-S10-1", owner_name="Ivy Iron",
            street_address="60 Iron St")
        setup_sealed_batch(bundle, "NB-S10")
        setup_bid(bundle, unit_rate_cents=1000)

        batch = validate_success(api.cancel_bid_batch(bundle["batch"]["id"],
                                                      COORD))
        assert batch["status"] == "CANCELLED"

        item = validate_success(api.get_work_item(bundle["item"]["id"], COORD))
        assert item["status"] == "REMOVED"
        bid = validate_success(api.get_bid(bundle["bid"]["id"], COORD))
        assert bid["status"] == "NOT_AWARDED"
        notice = validate_success(
            api.get_repair_notice(bundle["notice"]["id"], COORD))
        assert notice["status"] == "DELINQUENT", \
            "cancel does not touch the referenced notice"

        resp = api.award_bid_batch(batch["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_BATCH_STATE)

    def test_notice_already_pooled_rejected(self, api):
        """PRD §3.7: "The referenced notice must be `DELINQUENT` — pooling is
        the city-repair path — and must not already have a work item in
        `POOLED`, `SCHEDULED`, `WORK_COMPLETED`, or `VERIFIED` status in any
        batch (else `ERR_NOTICE_ALREADY_POOLED`)."

        Design: Corner/errors/notice_already_pooled_rejected
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-R6",
            segment_code="S-R6-1", owner_name="Lou Larch",
            street_address="90 Larch St")
        batch_a = make_batch("NB-R6A")
        make_work_item(batch_a["id"], bundle["notice"]["id"], 50, 1300)
        batch_b = make_batch("NB-R6B")

        resp = api.create_work_item(
            {"batch_id": batch_b["id"], "notice_id": bundle["notice"]["id"],
             "scope_sqft": 50, "engineer_unit_rate_cents": 1300}, COORD)
        validate_error(resp, ApiErrorId.ERR_NOTICE_ALREADY_POOLED)


class TestBatchEstimateAggregation:
    def test_estimate_recomputes_on_add_remove(self, api):
        """PRD §3.7: "The batch's `estimated_total_cents` is recomputed on
        every item addition and removal as the sum, over the batch's pooled
        items, of each item's `scope_sqft` multiplied by its
        `engineer_unit_rate_cents` and rounded half-up per item before summing;
        removed items drop out of the figure"

        Design: Corner/calculations/batch_estimate_recomputes_on_add_remove
        """
        owners, notices = [], []
        for idx, (name, pnum, addr) in enumerate(
                [("Uma Upas", "P-C6A", "71 Upas St"),
                 ("Val Vetch", "P-C6B", "72 Vetch St")]):
            owner = make_owner(name, addr)
            parcel = make_parcel(owner["id"], pnum, addr, "LOCAL")
            segment = make_segment(parcel["id"], f"S-C6{chr(65 + idx)}-1")
            defect = make_defect(segment["id"], "SPALLING",
                                 50 if idx == 0 else 80)
            notice = issue_notice(
                make_draft_notice(parcel["id"], [defect["id"]])["id"])
            owners.append(owner)
            notices.append(notice)

        set_clock("2026-09-16T00:00:00Z")
        validate_success(api.run_delinquency_sweep(COORD))

        batch = make_batch("NB-C6")
        assert batch["estimated_total_cents"] == 0

        item1 = make_work_item(batch["id"], notices[0]["id"], 50, 1300)
        batch = validate_success(api.get_bid_batch(batch["id"], COORD))
        assert batch["estimated_total_cents"] == 65000

        make_work_item(batch["id"], notices[1]["id"], 80, 1300)
        batch = validate_success(api.get_bid_batch(batch["id"], COORD))
        assert batch["estimated_total_cents"] == 169000

        removed = validate_success(api.remove_work_item(item1["id"], COORD))
        assert removed["status"] == "REMOVED"
        batch = validate_success(api.get_bid_batch(batch["id"], COORD))
        assert batch["estimated_total_cents"] == 104000


class TestAwardAndStartWorkWindows:
    def test_award_at_bid_deadline_rejected(self, api):
        """PRD §3.7: "The logical clock must be strictly past the
        `bid_deadline` (else `ERR_BID_WINDOW_STILL_OPEN`)."

        Design: Corner/errors/award_before_bid_deadline_rejected
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-T2",
            segment_code="S-T2-1", owner_name="Rae Ramie",
            street_address="99 Ramie St")
        setup_sealed_batch(bundle, "NB-T2")
        set_clock("2026-09-22T00:00:00Z")

        resp = api.award_bid_batch(bundle["batch"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_BID_WINDOW_STILL_OPEN)

    def test_start_work_window_boundary(self, api):
        """PRD §3.7: "Work may begin — `AWARDED → WORK_IN_PROGRESS` — once the
        logical clock reaches `work_window_start`, with the first day itself
        eligible and anything earlier failing as
        `ERR_WORK_WINDOW_NOT_REACHED`."

        Design: Corner/errors/start_work_before_window_rejected
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-T3",
            segment_code="S-T3-1", owner_name="Sal Sorrel",
            street_address="100 Sorrel St")
        setup_sealed_batch(bundle, "NB-T3")
        setup_bid(bundle, unit_rate_cents=1000)
        set_clock("2026-09-23T00:00:00Z")
        batch = validate_success(api.award_bid_batch(bundle["batch"]["id"],
                                                     COORD))
        assert batch["status"] == "AWARDED"

        resp = api.start_batch_work(batch["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_WORK_WINDOW_NOT_REACHED)

        set_clock("2026-09-25T00:00:00Z")
        batch = validate_success(api.start_batch_work(batch["id"], COORD))
        assert batch["status"] == "WORK_IN_PROGRESS", \
            "the first window day itself is eligible (>= inclusive)"
