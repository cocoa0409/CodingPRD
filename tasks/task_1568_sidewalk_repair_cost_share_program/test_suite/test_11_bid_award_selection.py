"""Bid award selection: evaluated totals, tie-breaks, eligibility filters, and
the half-open work-window conflict rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    get_batch_version,
    make_batch,
    make_bid,
    make_contractor,
    make_contractor_headers,
    make_work_item,
    set_clock,
    setup_delinquent_notice,
    setup_sealed_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


def _swept_notice(parcel_number, segment_code, owner_name, street_address,
                  area=50, corner=False):
    bundle = setup_delinquent_notice(
        sweep_clock="2026-09-16T00:00:00Z", parcel_number=parcel_number,
        segment_code=segment_code, owner_name=owner_name,
        street_address=street_address, defect_type="SPALLING", area_sqft=area,
        is_corner_lot=True if corner else None,
        is_corner_segment=True if corner else None,
        has_existing_curb_ramp=False if corner else None)
    return bundle


class TestHalfOpenWindowOverlap:
    def _setup_three_batches(self):
        """Contractor C1 holds awarded batch A [10-01, 11-01); B [10-15, 11-15)
        has bids from C1 (lowest) and C2; C [11-01, 12-01) has a bid from C1."""
        ctx = {}
        for idx, (name, pnum, addr) in enumerate(
                [("O1", "P-2001", "31 A St"), ("O2", "P-2002", "32 B St"),
                 ("O3", "P-2003", "33 C St")]):
            b = _swept_notice(pnum, f"S-200{idx + 1}-1", name, addr)
            ctx[f"notice{idx + 1}"] = b["notice"]

        c1 = make_contractor("C1 Construction", "L-101", "2027-12-31")
        c2 = make_contractor("C2 Construction", "L-102", "2027-12-31")
        ctx["c1"], ctx["c2"] = c1, c2

        # Batch A awarded to C1.
        batch_a = make_batch("NB-A", "2026-10-01", "2026-11-01",
                             "2026-09-20T00:00:00Z")
        make_work_item(batch_a["id"], ctx["notice1"]["id"], 50, 1300)
        sealed = validate_success(api_client.seal_bid_batch(batch_a["id"], COORD))
        ctx["bidA"] = make_bid(batch_a["id"], c1["id"], sealed["version"], 1000)
        set_clock("2026-09-21T00:00:00Z")
        batch_a = validate_success(api_client.award_bid_batch(batch_a["id"],
                                                              COORD))
        assert batch_a["awarded_bid_id"] == ctx["bidA"]["id"]
        ctx["batchA"] = batch_a

        # Batch B: overlapping window; bids from C1 (900) and C2 (1000).
        batch_b = make_batch("NB-B", "2026-10-15", "2026-11-15",
                             "2026-09-25T00:00:00Z")
        make_work_item(batch_b["id"], ctx["notice2"]["id"], 50, 1300)
        sealed = validate_success(api_client.seal_bid_batch(batch_b["id"], COORD))
        ctx["bidB1"] = make_bid(batch_b["id"], c1["id"], sealed["version"], 900)
        ctx["bidB2"] = make_bid(batch_b["id"], c2["id"],
                                get_batch_version(batch_b["id"]), 1000)
        ctx["batchB"] = batch_b

        # Batch C: adjacent window starting exactly at A's end; bid from C1.
        batch_c = make_batch("NB-C", "2026-11-01", "2026-12-01",
                             "2026-09-25T00:00:00Z")
        make_work_item(batch_c["id"], ctx["notice3"]["id"], 50, 1300)
        sealed = validate_success(api_client.seal_bid_batch(batch_c["id"], COORD))
        ctx["bidC1"] = make_bid(batch_c["id"], c1["id"], sealed["version"], 900)
        ctx["batchC"] = batch_c

        set_clock("2026-09-26T00:00:00Z")
        return ctx

    def test_overlapping_window_excludes_holder(self, api):
        """PRD §3.7: "A bid is eligible only when all four conditions hold: its
        status is `SUBMITTED`; its contractor is not suspended; the contractor's
        `insurance_valid_until` reaches at least `work_window_end`; and the
        contractor holds no conflicting window — for every other batch that
        contractor has in `AWARDED` or `WORK_IN_PROGRESS`, the half-open windows
        must not intersect, where an existing window ending exactly at this
        batch's start does not conflict."

        Design: Difficulty/resource_temporal_overlap/contractor_half_open_window_overlap_exclusion
        """
        ctx = self._setup_three_batches()
        batch_b = validate_success(
            api.award_bid_batch(ctx["batchB"]["id"], COORD))
        assert batch_b["awarded_bid_id"] == ctx["bidB2"]["id"], \
            "C1's lower bid is excluded by the overlap with awarded batch A"
        assert batch_b["awarded_total_cents"] == 50000

        bid_b1 = validate_success(api.get_bid(ctx["bidB1"]["id"], COORD))
        assert bid_b1["status"] == "NOT_AWARDED"

    def test_adjacent_window_is_not_a_conflict(self, api):
        """PRD §3.7: "the half-open windows must not intersect, where an
        existing window ending exactly at this batch's start does not conflict."

        Design: Difficulty/resource_temporal_overlap/contractor_half_open_window_overlap_exclusion
        """
        ctx = self._setup_three_batches()
        validate_success(api.award_bid_batch(ctx["batchB"]["id"], COORD))

        batch_c = validate_success(
            api.award_bid_batch(ctx["batchC"]["id"], COORD))
        assert batch_c["awarded_bid_id"] == ctx["bidC1"]["id"], \
            "C [11-01, 12-01) starts exactly at A's end: adjacency is eligible"
        assert batch_c["awarded_total_cents"] == 45000


class TestEvaluatedTotalAndTieBreaks:
    def test_evaluated_total_includes_ramp_fee(self, api):
        """PRD §3.7: "The selector recomputes each bid's
        `evaluated_total_cents` as its `unit_rate_cents` multiplied by the
        batch's total pooled scope in square feet, plus its `ramp_flat_fee_cents`
        multiplied by the count of pooled items flagged for ramp upgrade — the
        same formula snapshotted at submission."
        PRD §3.7: "The server stamps `contractor_id` from the bidder's
        `X-User-ID` and `submitted_at` from the logical clock, snapshots
        `evaluated_total_cents`, and increments the batch's `version`."

        Design: Corner/calculations/bid_evaluated_total_includes_ramp_fee
        """
        bundle_a = _swept_notice("P-C7A", "S-C7A-1", "Wyn Wahoo",
                                 "73 Wahoo St", area=50, corner=True)
        bundle_b = _swept_notice("P-C7B", "S-C7B-1", "Xan Xantho",
                                 "74 Xantho St", area=80)

        batch = make_batch("NB-C7")
        item1 = make_work_item(batch["id"], bundle_a["notice"]["id"], 50, 1300)
        assert item1["includes_ramp_upgrade"] is True, \
            "corner segment without an existing ramp"
        item2 = make_work_item(batch["id"], bundle_b["notice"]["id"], 80, 1300)
        assert item2["includes_ramp_upgrade"] is False

        sealed = validate_success(api.seal_bid_batch(batch["id"], COORD))
        contractor = make_contractor("Acme Paving", "L-701", "2026-12-31")
        bid = validate_success(api.create_bid(
            {"batch_id": batch["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 200000,
             "expected_batch_version": sealed["version"]},
            make_contractor_headers(contractor["id"])), 201)
        assert bid["evaluated_total_cents"] == 330000, \
            "1000 x 130 total scope + 200000 x 1 ramp item"
        assert bid["submitted_at"] == "2026-09-16T00:00:00Z"
        assert bid["status"] == "SUBMITTED"

    def test_tiebreak_falls_to_license_ascending(self, api):
        """PRD §3.7: "Eligible bids rank by `evaluated_total_cents` ascending,
        ties broken by earlier `submitted_at`, further ties by ascending
        contractor `license_number`; an empty eligible pool fails the award with
        `ERR_NO_ELIGIBLE_BIDS`."

        Design: Corner/calculations/bid_award_tiebreak_license_ascending
        """
        bundle = _swept_notice("P-C8", "S-C8-1", "Yvo Yucca", "75 Yucca St")
        batch = make_batch("NB-C8")
        make_work_item(batch["id"], bundle["notice"]["id"], 50, 1300)
        sealed = validate_success(api.seal_bid_batch(batch["id"], COORD))

        c_l2 = make_contractor("Second Builders", "L-002", "2027-12-31")
        c_l1 = make_contractor("First Builders", "L-001", "2027-12-31")
        bid_l2 = validate_success(api.create_bid(
            {"batch_id": batch["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": sealed["version"]},
            make_contractor_headers(c_l2["id"])), 201)
        bid_l1 = validate_success(api.create_bid(
            {"batch_id": batch["id"], "unit_rate_cents": 1000,
             "ramp_flat_fee_cents": 0,
             "expected_batch_version": get_batch_version(batch["id"])},
            make_contractor_headers(c_l1["id"])), 201)
        assert bid_l2["evaluated_total_cents"] == 50000
        assert bid_l1["evaluated_total_cents"] == 50000
        assert bid_l2["submitted_at"] == bid_l1["submitted_at"], \
            "same logical clock -> tie falls through to license_number"

        set_clock("2026-09-23T00:00:00Z")
        batch = validate_success(api.award_bid_batch(batch["id"], COORD))
        assert batch["awarded_bid_id"] == bid_l1["id"], \
            "license_number ASC: L-001 beats L-002"
        assert batch["awarded_total_cents"] == 50000

        bid_l2_after = validate_success(api.get_bid(bid_l2["id"], COORD))
        assert bid_l2_after["status"] == "NOT_AWARDED"
        rows, _ = validate_paginated(
            api.list_bids(COORD, params={"batch_id": batch["id"]}))
        assert len(rows) == 2

    def test_award_with_no_bids_rejected(self, api):
        """PRD §3.7: "an empty eligible pool fails the award with
        `ERR_NO_ELIGIBLE_BIDS`."

        Design: Corner/errors/award_with_no_bids_rejected
        """
        bundle = setup_delinquent_notice(
            sweep_clock="2026-09-16T00:00:00Z", parcel_number="P-T13",
            segment_code="S-T13-1", owner_name="Bea Betony",
            street_address="109 Betony St")
        setup_sealed_batch(bundle, "NB-T13")
        set_clock("2026-09-23T00:00:00Z")

        resp = api.award_bid_batch(bundle["batch"]["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_BIDS)
