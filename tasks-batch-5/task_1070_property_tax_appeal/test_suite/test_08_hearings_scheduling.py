"""Hearing scheduling overlap rules: pairwise representative buffer and aggregate room capacity."""
from test_helpers import validate_success, validate_error, ApiErrorId, make_analyst_headers
from test_helpers import fixtures as fx

_COMP = {"comp_address": "x", "sale_price_cents": 27000000,
         "comp_assessed_value_cents": 27000000, "adjustment_pct": 0.00}


def _two_filed_appeals(api, jurisdiction_overrides, num_reps=1):
    """Analyst 'an' owns two filed appeals in one shared jurisdiction; plus num_reps representatives."""
    an = fx.new_analyst(api)
    reps = [fx.new_analyst(api) for _ in range(num_reps)]
    client = fx.new_client(api)
    jur = fx.new_jurisdiction(api, **jurisdiction_overrides)
    fee = fx.new_fee_agreement(api, client["id"])
    appeals = []
    for _ in range(2):
        parcel = fx.new_parcel(api, an["id"], client["id"], jur["id"])
        assessment = fx.new_assessment(api, an["id"], parcel["id"])
        appeal = fx.new_appeal(api, an["id"], assessment["id"], fee["id"], "SALES_COMPARISON")
        fx.add_evidence(api, an["id"], appeal["id"], **_COMP)
        fx.do_file_appeal(api, an["id"], appeal["id"])
        appeals.append(appeal["id"])
    return {"an_id": an["id"], "rep_ids": [r["id"] for r in reps],
            "appeal1_id": appeals[0], "appeal2_id": appeals[1]}


class TestRepresentativeBuffer:
    """Same representative, gap < buffer(60) -> reject; gap == buffer -> allow.
    Design: Difficulty/resource_temporal_overlap/rt_representative_buffer_conflict
    """

    def test_gap_below_buffer_rejected(self, api):
        """PRD §3.5: "if the proposed interval falls closer than the jurisdiction's
        `rep_travel_buffer_minutes` to any other `SCHEDULED` hearing of the same representative in that
        jurisdiction, the request is rejected with `ERR_REPRESENTATIVE_UNAVAILABLE`". Gap 30 < 60.

        Design: Difficulty/resource_temporal_overlap/rt_representative_buffer_conflict
        """
        ctx = _two_filed_appeals(api, {"rep_travel_buffer_minutes": 60, "hearing_room_capacity": 3})
        rep = ctx["rep_ids"][0]
        fx.schedule_hearing(api, ctx["an_id"], ctx["appeal1_id"], rep,
                            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z", docket_room="R1")
        resp = api.schedule_hearing(
            ctx["appeal2_id"],
            {"representative_id": rep, "docket_room": "R2",
             "scheduled_start": "2026-08-01T11:30:00Z", "scheduled_end": "2026-08-01T12:30:00Z"},
            make_analyst_headers(ctx["an_id"]))
        validate_error(resp, ApiErrorId.ERR_REPRESENTATIVE_UNAVAILABLE.value)

    def test_gap_exactly_buffer_allowed(self, api):
        """PRD §3.5: "a gap exactly equal to the buffer is allowed." Gap 11:00->12:00 == 60.

        Design: Difficulty/resource_temporal_overlap/rt_representative_buffer_conflict
        """
        ctx = _two_filed_appeals(api, {"rep_travel_buffer_minutes": 60, "hearing_room_capacity": 3})
        rep = ctx["rep_ids"][0]
        fx.schedule_hearing(api, ctx["an_id"], ctx["appeal1_id"], rep,
                            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z", docket_room="R1")
        resp = api.schedule_hearing(
            ctx["appeal2_id"],
            {"representative_id": rep, "docket_room": "R2",
             "scheduled_start": "2026-08-01T12:00:00Z", "scheduled_end": "2026-08-01T13:00:00Z"},
            make_analyst_headers(ctx["an_id"]))
        hearing = validate_success(resp, expected_status=201)
        assert hearing["status"] == "SCHEDULED"


class TestDocketRoomCapacity:
    """Aggregate room capacity: overlap count at capacity -> reject; non-overlapping -> allow.
    Design: Difficulty/resource_temporal_overlap/rt_docket_room_capacity_full
    """

    def test_overlap_at_capacity_rejected(self, api):
        """PRD §3.5: "if the number of already-`SCHEDULED` hearings overlapping the proposed interval in
        the same jurisdiction-and-`docket_room` combination is already at or above the jurisdiction's
        `hearing_room_capacity`, the request is rejected with `ERR_DOCKET_ROOM_FULL`." capacity 1, overlap.

        Design: Difficulty/resource_temporal_overlap/rt_docket_room_capacity_full
        """
        ctx = _two_filed_appeals(api, {"hearing_room_capacity": 1, "rep_travel_buffer_minutes": 0}, num_reps=2)
        rep_a, rep_b = ctx["rep_ids"]
        fx.schedule_hearing(api, ctx["an_id"], ctx["appeal1_id"], rep_a,
                            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z", docket_room="R1")
        resp = api.schedule_hearing(
            ctx["appeal2_id"],
            {"representative_id": rep_b, "docket_room": "R1",
             "scheduled_start": "2026-08-01T10:30:00Z", "scheduled_end": "2026-08-01T11:30:00Z"},
            make_analyst_headers(ctx["an_id"]))
        validate_error(resp, ApiErrorId.ERR_DOCKET_ROOM_FULL.value)

    def test_non_overlapping_in_full_room_allowed(self, api):
        """PRD §3.5: "The hearing occupies the half-open interval running from `scheduled_start` up to
        but not including `scheduled_end`". A hearing beginning exactly when the prior one ends does not
        overlap, so at capacity 1 the count of overlapping SCHEDULED hearings is 0 and scheduling succeeds.

        Design: Difficulty/resource_temporal_overlap/rt_docket_room_capacity_full
        """
        ctx = _two_filed_appeals(api, {"hearing_room_capacity": 1, "rep_travel_buffer_minutes": 0}, num_reps=2)
        rep_a, rep_b = ctx["rep_ids"]
        fx.schedule_hearing(api, ctx["an_id"], ctx["appeal1_id"], rep_a,
                            "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z", docket_room="R1")
        resp = api.schedule_hearing(
            ctx["appeal2_id"],
            {"representative_id": rep_b, "docket_room": "R1",
             "scheduled_start": "2026-08-01T11:00:00Z", "scheduled_end": "2026-08-01T12:00:00Z"},
            make_analyst_headers(ctx["an_id"]))
        hearing = validate_success(resp, expected_status=201)
        assert hearing["status"] == "SCHEDULED"
