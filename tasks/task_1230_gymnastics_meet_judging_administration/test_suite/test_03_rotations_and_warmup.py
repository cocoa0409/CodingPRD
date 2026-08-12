"""Rotations and warm-up blocks: temporal layout, changeover gaps, half-open
vs abutting interval semantics, and the waterfall window allocation."""
from datetime import datetime, timedelta, timezone

from test_helpers import (
    ApiErrorId,
    create_warmup_block_payload,
    parse_ts,
    setup_squads_for_layout,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["meet_director_headers"]

SESSION_START_DT = datetime(2026, 5, 2, 14, 0, tzinfo=timezone.utc)


def _durations_minutes(rotation):
    start = parse_ts(rotation["scheduled_start"])
    end = parse_ts(rotation["scheduled_end"])
    return (end - start).total_seconds() / 60.0


class TestRotationLayout:
    def test_generated_rotations_apply_five_minute_changeover_gap(
            self, api, meet_director_headers):
        """PRD §3.5: "The first rotation opens at the session's `scheduled_start`, and each
        subsequent rotation begins five minutes after its predecessor's `scheduled_end` — the
        changeover gap."

        Design: Corner/calculations/rotation_layout_changeover_gap_applied
        """
        ctx = setup_squads_for_layout(squad_sizes=(1,), max_athletes_per_squad=12)
        rotations = ctx["rotations"]
        assert len(rotations) == 4, f"expected 4 generated rotations, got {len(rotations)}"
        assert [r["rotation_number"] for r in rotations] == [1, 2, 3, 4]
        assert parse_ts(rotations[0]["scheduled_start"]) == SESSION_START_DT
        for prev, curr in zip(rotations, rotations[1:]):
            gap = (parse_ts(curr["scheduled_start"])
                   - parse_ts(prev["scheduled_end"])).total_seconds() / 60.0
            assert gap == 5.0, (
                f"rotation {curr['rotation_number']} must begin exactly five minutes after "
                f"rotation {prev['rotation_number']} ends, got a {gap}-minute gap")

    def test_generated_rotations_never_overlap_half_open(
            self, api, meet_director_headers):
        """PRD §3.5: "Rotation intervals are half-open, so adjacent rotations may share a
        boundary timestamp without overlapping; any true overlap of scheduled intervals
        within a session — whether the rotations are declared one at a time or generated as a
        set — is rejected with `ERR_ROTATION_OVERLAP` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/rotation_half_open_interval_no_overlap
        """
        ctx = setup_squads_for_layout(squad_sizes=(2,), max_athletes_per_squad=12)
        rotations = ctx["rotations"]
        assert len(rotations) == 4
        for prev, curr in zip(rotations, rotations[1:]):
            assert parse_ts(curr["scheduled_start"]) >= parse_ts(prev["scheduled_end"]), (
                f"rotations {prev['rotation_number']} and {curr['rotation_number']} overlap")
            gap = (parse_ts(curr["scheduled_start"])
                   - parse_ts(prev["scheduled_end"])).total_seconds() / 60.0
            assert gap >= 5.0, f"changeover gap must be at least 5 minutes, got {gap}"

    def test_rotation_durations_follow_per_athlete_pace(self, api, meet_director_headers):
        """PRD §3.5: "A rotation's duration derives from the field size — the total
        `athlete_count` across the session's squads — at a per-athlete pace of 30 seconds on
        `VAULT`, 90 seconds on `UNEVEN_BARS`, 120 seconds on `BALANCE_BEAM`, and 90 seconds on
        `FLOOR_EXERCISE`: the total headcount times the apparatus pace, divided by 60 and
        rounded up to a whole number of minutes."

        Design: Difficulty/resource_temporal_overlap/rotation_half_open_interval_no_overlap
        """
        # Four athletes: VAULT ceil(4*30/60)=2 min, UB ceil(4*90/60)=6,
        # BB ceil(4*120/60)=8, FX ceil(4*90/60)=6.
        ctx = setup_squads_for_layout(squad_sizes=(4,), max_athletes_per_squad=12)
        expected = {"VAULT": 2, "UNEVEN_BARS": 6, "BALANCE_BEAM": 8, "FLOOR_EXERCISE": 6}
        for rotation in ctx["rotations"]:
            assert _durations_minutes(rotation) == expected[rotation["apparatus"]], (
                f"{rotation['apparatus']} rotation must last "
                f"{expected[rotation['apparatus']]} minutes for 4 athletes, got "
                f"{_durations_minutes(rotation)}")


class TestWarmupWaterfall:
    def test_waterfall_remainder_flows_to_last_squad(self, api, meet_director_headers):
        """PRD §3.5: "Generating the blocks allocates the window squad by squad in ascending
        `rotation_index` order, ties broken by squad creation order: each squad's raw
        allotment is its `athlete_count` times two minutes, rounded up to a whole minute,
        then clamped to no less than eight minutes and no more than twenty. Allocation is a
        waterfall — if the remaining window cannot hold a squad's clamped allotment, that
        squad receives whatever minutes remain — and if minutes are still unallocated after
        every squad has been placed, the last squad's block absorbs the overflow."

        Design: Difficulty/combinatorial_formula/warmup_block_waterfall_remainder_allocation
        """
        # Three squads of four athletes: raw = ceil(4*2) = 8 min each; 24 min
        # allocated, so the remaining 36 min flow to the last squad's block.
        ctx = setup_squads_for_layout(squad_sizes=(4, 4, 4), max_athletes_per_squad=4)
        rotation = ctx["rotations"][0]
        blocks = validate_success(
            api.generate_warmup_blocks(rotation["id"], meet_director_headers), 201)
        assert len(blocks) == 3, f"expected one block per squad, got {len(blocks)}"
        blocks_by_squad = {b["squad_id"]: b for b in blocks}
        squad_a, squad_b, squad_c = (s["id"] for s in ctx["squads"])
        window_start = SESSION_START_DT - timedelta(minutes=60)

        assert parse_ts(blocks_by_squad[squad_a]["block_start"]) == window_start
        assert parse_ts(blocks_by_squad[squad_a]["block_end"]) == window_start + timedelta(minutes=8)
        assert parse_ts(blocks_by_squad[squad_b]["block_start"]) == window_start + timedelta(minutes=8)
        assert parse_ts(blocks_by_squad[squad_b]["block_end"]) == window_start + timedelta(minutes=16)
        # Last squad absorbs the overflow: 8 + 36 = 44 minutes, closing the window.
        assert parse_ts(blocks_by_squad[squad_c]["block_start"]) == window_start + timedelta(minutes=16)
        assert parse_ts(blocks_by_squad[squad_c]["block_end"]) == SESSION_START_DT

        total = sum((parse_ts(b["block_end"]) - parse_ts(b["block_start"])).total_seconds()
                    for b in blocks)
        assert total == 60 * 60, f"blocks must consume the full 60-minute window, got {total}s"

    def test_single_squad_block_absorbs_entire_window(self, api, meet_director_headers):
        """PRD §3.5: "if minutes are still unallocated after every squad has been placed,
        the last squad's block absorbs the overflow."
        PRD §3.5: "each squad's raw allotment is its `athlete_count` times two minutes,
        rounded up to a whole minute, then clamped to no less than eight minutes and no more
        than twenty."

        Design: Difficulty/combinatorial_formula/warmup_block_waterfall_remainder_allocation
        """
        # One squad of four athletes: raw 8 minutes, then the 52 unallocated
        # minutes overflow into the same (last) squad's block.
        ctx = setup_squads_for_layout(squad_sizes=(4,), max_athletes_per_squad=4)
        rotation = ctx["rotations"][0]
        blocks = validate_success(
            api.generate_warmup_blocks(rotation["id"], meet_director_headers), 201)
        assert len(blocks) == 1
        block = blocks[0]
        assert parse_ts(block["block_start"]) == SESSION_START_DT - timedelta(minutes=60)
        assert parse_ts(block["block_end"]) == SESSION_START_DT, (
            "the sole (last) squad's block must absorb the whole 60-minute window")


class TestWarmupBlockBoundaries:
    def test_generated_blocks_share_boundaries_without_overlap(
            self, api, meet_director_headers):
        """PRD §3.5: "Blocks may abut — one block's end coinciding with the next block's
        start is permitted — but any deeper overlap with another block on the same rotation
        is rejected with `ERR_WARMUP_BLOCK_OVERLAP` (HTTP 422), and this guard applies
        equally to a single hand-created block and to a generated set."

        Design: Difficulty/resource_temporal_overlap/warmup_block_closed_interval_shared_boundary
        """
        ctx = setup_squads_for_layout(squad_sizes=(4, 4), max_athletes_per_squad=4)
        rotation = ctx["rotations"][0]
        blocks = validate_success(
            api.generate_warmup_blocks(rotation["id"], meet_director_headers), 201)
        assert len(blocks) == 2
        ordered = sorted(blocks, key=lambda b: parse_ts(b["block_start"]))
        assert parse_ts(ordered[0]["block_end"]) == parse_ts(ordered[1]["block_start"]), (
            "consecutive generated blocks must share their boundary timestamp")
        # Together they cover the whole window with no gaps and no interior overlap.
        assert parse_ts(ordered[0]["block_start"]) == SESSION_START_DT - timedelta(minutes=60)
        assert parse_ts(ordered[1]["block_end"]) == SESSION_START_DT

    def test_manual_block_may_abut_but_not_overlap(self, api, meet_director_headers):
        """PRD §3.5: "Blocks may abut — one block's end coinciding with the next block's
        start is permitted — but any deeper overlap with another block on the same rotation
        is rejected with `ERR_WARMUP_BLOCK_OVERLAP` (HTTP 422), and this guard applies
        equally to a single hand-created block and to a generated set."

        Design: Difficulty/resource_temporal_overlap/warmup_block_closed_interval_shared_boundary
        """
        ctx = setup_squads_for_layout(squad_sizes=(4,), max_athletes_per_squad=4)
        rotation = ctx["rotations"][0]
        squad_id = ctx["squads"][0]["id"]
        first = api.create_warmup_block(rotation["id"], create_warmup_block_payload(
            squad_id, "VAULT", "2026-05-02T13:00:00Z", "2026-05-02T13:08:00Z"), DIRECTOR)
        validate_success(first, 201)
        # Abutting block (its start coincides with the first block's end): permitted.
        abutting = api.create_warmup_block(rotation["id"], create_warmup_block_payload(
            squad_id, "VAULT", "2026-05-02T13:08:00Z", "2026-05-02T13:20:00Z"), DIRECTOR)
        validate_success(abutting, 201)
        # Strict interior overlap with the first block: rejected.
        overlapping = api.create_warmup_block(rotation["id"], create_warmup_block_payload(
            squad_id, "VAULT", "2026-05-02T13:05:00Z", "2026-05-02T13:10:00Z"), DIRECTOR)
        validate_error(overlapping, ApiErrorId.ERR_WARMUP_BLOCK_OVERLAP)
