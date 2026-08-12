"""Block packing arithmetic, turnover constants, padded surgeon overlap."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_case_posting,
    make_block,
    make_case,
    make_coverage,
    make_line,
    make_room,
    make_surgeon,
    make_surgeon_headers,
    schedule_case_in_block,
    setup_surgeon_with_completions,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestTurnoverConstants:
    def test_hybrid_room_turnover_adds_ten_minutes(self, api):
        """PRD §3.3: "Every case also carries a `turnover_minutes` value, resolved at
        scheduling: a base gap by procedure class — 15 minutes for `MINOR`, 25 for
        `STANDARD`, 40 for `COMPLEX` — plus 10 additional minutes when the room
        `is_hybrid`. In any packed sequence, a case's turnover gap is charged before
        it whenever it is not the first case."

        Design: Corner/calculations/hybrid_room_turnover_adds_ten_minutes
        """
        line = make_line()
        surgeon = make_surgeon(line["id"], full_name="Dr. H")
        room = make_room(room_name="OR-HYB", is_hybrid=True)
        make_coverage(room["id"], "2026-05-04", 420, 1200)
        block = make_block(line["id"], room["id"], date="2026-05-04",
                           start_minute=480, end_minute=960, activate=True)

        c1 = schedule_case_in_block(
            make_case(surgeon["id"], procedure_class="MINOR")["id"],
            block["id"], surgeon["id"],
        )
        c2 = schedule_case_in_block(
            make_case(surgeon["id"], procedure_class="MINOR")["id"],
            block["id"], surgeon["id"],
        )

        assert c1["scheduled_start_minute"] == 480
        assert c1["scheduled_end_minute"] == 525
        assert c2["turnover_minutes"] == 25  # 15 base + 10 hybrid
        assert c2["scheduled_start_minute"] == 550  # 525 + 25
        assert c2["scheduled_end_minute"] == 595

        block_after = validate_success(api.get_block(block["id"], ADMIN), 200)
        assert block_after["occupied_minutes"] == 115  # 45 + 45 + 25


class TestPerCaseRoundingFitBoundary:
    def _setup_bias_1037(self):
        """Five COMPLEX completions of 186/186/187/187/187 minutes yield mean
        ratio 933/900 = 1.0366... -> 1.037 after the pinned rounding order."""
        return setup_surgeon_with_completions(
            line_name="PLAS", block_start=300, block_end=1440,
            coverage_start=300, coverage_end=1440,
            procedure_class="COMPLEX",
            actual_durations=[186, 186, 187, 187, 187],
        )

    def test_per_case_rounding_governs_fit(self, api):
        """PRD §3.3: "This rounding order is pinned: averaging happens on unrounded
        values, rounding to three decimals and clamping happen next, and the
        per-case multiplication with its own half-up rounding happens last, at
        posting."
        PRD §3.4: "If the end of the last packed case would exceed the block's
        `end_minute`, scheduling is rejected with `ERR_CASE_DOES_NOT_FIT` — and the
        fit always uses each case's individually rounded
        `predicted_duration_minutes`, never an unrounded sum."

        Design: Difficulty/combinatorial_formula/per_case_rounding_governs_block_fit_boundary
        """
        env = self._setup_bias_1037()
        surgeon = validate_success(api.get_surgeon(env["surgeon"]["id"], ADMIN), 200)
        assert surgeon["duration_bias_factor"] == 1.037

        make_coverage(env["room"]["id"], "2026-05-05", 420, 1440, provider_ref="AN2")
        block2 = make_block(env["line"]["id"], env["room"]["id"], date="2026-05-05",
                            start_minute=420, end_minute=528, activate=True)

        # round_half_up(45 * 1.037) = round_half_up(46.665) = 47 per case.
        m1 = make_case(env["surgeon"]["id"], procedure_class="MINOR")
        assert m1["predicted_duration_minutes"] == 47
        m1 = schedule_case_in_block(m1["id"], block2["id"], env["surgeon"]["id"])
        assert m1["scheduled_start_minute"] == 420

        # Packed second case: start 420+47+15 = 482, end 529 > block end 528.
        m2 = make_case(env["surgeon"]["id"], procedure_class="MINOR")
        res = api.schedule_case(
            m2["id"], {"block_id": block2["id"]},
            make_surgeon_headers(env["surgeon"]["id"]),
        )
        validate_error(res, ApiErrorId.ERR_CASE_DOES_NOT_FIT)
        assert res.status_code == 409
        reread = validate_success(api.get_case(m2["id"], ADMIN), 200)
        assert reread["status"] == "POSTED"

    def test_rejected_fit_leaves_block_and_case_untouched(self, api):
        """PRD §3.2: "While `ACTIVE`, the block's `reserved_minutes` counts the
        block-controlled span from `start_minute` through the scheduled end of its
        last `SCHEDULED` case (zero when no case is scheduled), and
        `occupied_minutes` sums the predicted durations of its `SCHEDULED` cases
        plus the turnover gap charged before every case that is not first in the
        packed sequence."
        PRD §3.3: "New cases are born `POSTED`, with `block_id`, `or_id`, `date`,
        `scheduled_start_minute`, and `scheduled_end_minute` all null until
        scheduling assigns them."

        Design: Difficulty/combinatorial_formula/per_case_rounding_governs_block_fit_boundary
        """
        env = self._setup_bias_1037()
        make_coverage(env["room"]["id"], "2026-05-05", 420, 1440, provider_ref="AN2")
        block2 = make_block(env["line"]["id"], env["room"]["id"], date="2026-05-05",
                            start_minute=420, end_minute=528, activate=True)
        m1 = schedule_case_in_block(
            make_case(env["surgeon"]["id"], procedure_class="MINOR")["id"],
            block2["id"], env["surgeon"]["id"],
        )
        m2 = make_case(env["surgeon"]["id"], procedure_class="MINOR")
        validate_error(
            api.schedule_case(
                m2["id"], {"block_id": block2["id"]},
                make_surgeon_headers(env["surgeon"]["id"]),
            ),
            ApiErrorId.ERR_CASE_DOES_NOT_FIT,
        )

        block_after = validate_success(api.get_block(block2["id"], ADMIN), 200)
        assert block_after["occupied_minutes"] == 47      # only m1
        assert block_after["reserved_minutes"] == 47      # 467 - 420
        m2_after = validate_success(api.get_case(m2["id"], ADMIN), 200)
        assert_case_posting(m2_after)
        assert m2_after["status"] == "POSTED"
        assert m2_after["scheduled_start_minute"] is None
        assert m2_after["block_id"] is None


class TestSurgeonPaddedOverlap:
    def _setup_two_rooms(self, line_name="SCTS"):
        line = make_line(name=line_name)
        surgeon = make_surgeon(line["id"], full_name="Dr. S")
        room1 = make_room("OR1")
        room2 = make_room("OR2")
        make_coverage(room1["id"], "2026-05-04", 420, 1200)
        make_coverage(room2["id"], "2026-05-04", 420, 1200)
        return line, surgeon, room1, room2

    def test_padded_overlap_across_rooms(self, api):
        """PRD §3.4: "Then the padded double-booking rule: for the case's surgeon on
        that date across all rooms, every existing `SCHEDULED` case occupies a
        padded interval running from its scheduled start through its scheduled end
        plus its own turnover gap, and the incoming case likewise occupies its start
        through its end plus its turnover; if two padded intervals intersect — the
        padded end treated as exclusive — the placement is rejected with
        `ERR_SURGEON_DOUBLE_BOOKED`, while touching exactly at a padded boundary is
        permitted."

        Design: Difficulty/resource_temporal_overlap/surgeon_padded_overlap_across_rooms
        """
        line, surgeon, room1, room2 = self._setup_two_rooms()
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=720, activate=True)
        c1 = schedule_case_in_block(
            make_case(surgeon["id"], procedure_class="STANDARD")["id"],
            block1["id"], surgeon["id"],
        )
        assert c1["scheduled_start_minute"] == 420  # padded to [420, 535)

        block2 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=520, end_minute=700, activate=True)
        c2 = make_case(surgeon["id"], procedure_class="STANDARD")
        res = api.schedule_case(
            c2["id"], {"block_id": block2["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res, ApiErrorId.ERR_SURGEON_DOUBLE_BOOKED)
        assert res.status_code == 409
        assert validate_success(api.get_case(c2["id"], ADMIN), 200)["status"] == "POSTED"

        cancelled = validate_success(api.cancel_block(block2["id"], ADMIN), 200)
        assert cancelled["status"] == "CANCELLED"

        # 535 touches the padded boundary exactly and is allowed.
        block3 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=535, end_minute=960, activate=True)
        placed = validate_success(
            api.schedule_case(
                c2["id"], {"block_id": block3["id"]},
                make_surgeon_headers(surgeon["id"]),
            ),
            200,
        )
        assert placed["status"] == "SCHEDULED"
        assert placed["scheduled_start_minute"] == 535

    def test_padded_boundary_with_complex_turnover(self, api):
        """PRD §3.4: "if two padded intervals intersect — the padded end treated as
        exclusive — the placement is rejected with `ERR_SURGEON_DOUBLE_BOOKED`,
        while touching exactly at a padded boundary is permitted."
        PRD §3.3: "a base gap by procedure class — 15 minutes for `MINOR`, 25 for
        `STANDARD`, 40 for `COMPLEX`".

        Design: Difficulty/resource_temporal_overlap/surgeon_padded_overlap_across_rooms
        """
        line, surgeon, room1, room2 = self._setup_two_rooms()
        block1 = make_block(line["id"], room1["id"], date="2026-05-04",
                            start_minute=420, end_minute=720, activate=True)
        c1 = schedule_case_in_block(
            make_case(surgeon["id"], procedure_class="COMPLEX")["id"],
            block1["id"], surgeon["id"],
        )
        assert c1["scheduled_end_minute"] == 600  # padded to [420, 640)

        # 639 intrudes one minute into the padded tail [600, 640).
        block2 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=639, end_minute=759, activate=True)
        c2 = make_case(surgeon["id"], procedure_class="MINOR")
        res = api.schedule_case(
            c2["id"], {"block_id": block2["id"]}, make_surgeon_headers(surgeon["id"])
        )
        validate_error(res, ApiErrorId.ERR_SURGEON_DOUBLE_BOOKED)

        validate_success(api.cancel_block(block2["id"], ADMIN), 200)
        block3 = make_block(line["id"], room2["id"], date="2026-05-04",
                            start_minute=640, end_minute=760, activate=True)
        placed = validate_success(
            api.schedule_case(
                c2["id"], {"block_id": block3["id"]},
                make_surgeon_headers(surgeon["id"]),
            ),
            200,
        )
        assert placed["scheduled_start_minute"] == 640
