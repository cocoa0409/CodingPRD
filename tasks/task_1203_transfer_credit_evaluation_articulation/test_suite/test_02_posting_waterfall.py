"""Credit-cap waterfall: slot needs, FREE_ELECTIVE spill, global 60.0 cap,
and immediate consistency of posting effects."""
import pytest

from test_helpers import (
    get_success_data,
    api_client,
    TEST_USERS,
    create_transcript_course_payload,
    fixtures,
)

EVALUATOR = TEST_USERS["evaluator_headers"]
EVAL_A = fixtures.EVAL_A
EVAL_B = fixtures.EVAL_B


def _build_twelve_line_evaluation():
    """SEMESTER partner; 12 equivalencies feeding one transcript.

    5x MATH (6.0h each -> CMAT cap 6.0), 2x ENGL GENED_COMMS (5.0h -> CENG cap 6.0),
    5x HIST (5.0h -> CHIST cap 6.0); all grade A; student major MATH.
    Returns (student, evaluation, lines) with evaluation EVALUATED.
    """
    partner = fixtures.create_partner(credit_system="SEMESTER")
    c_math = fixtures.create_course(code="MATH-150", credit_hours=6.0, department="MATH")
    c_eng = fixtures.create_course(code="ENG-110", title="Composition", credit_hours=6.0,
                                   department="ENGL", gened_tags=["GENED_COMMS"])
    c_hist = fixtures.create_course(code="HIST-100", title="World History", credit_hours=6.0,
                                    department="HIST")
    agreement = fixtures.create_agreement(partner["id"])
    fixtures.activate_agreement(agreement["id"])
    external = (
        [("M-10%d" % i, c_math["id"], 6.0) for i in range(1, 6)]
        + [("E-201", c_eng["id"], 5.0), ("E-202", c_eng["id"], 5.0)]
        + [("H-30%d" % i, c_hist["id"], 5.0) for i in range(1, 6)]
    )
    for code, course_id, hours in external:
        fixtures.add_equivalency(agreement["id"], course_id, code, external_credit_hours=hours)
    student = fixtures.create_student(major="MATH")
    transcript = fixtures.create_verified_transcript(
        student["id"], partner["id"],
        courses=[
            create_transcript_course_payload(external_course_code=code, title=code,
                                             credit_hours=hours, grade="A")
            for code, _, hours in external
        ],
    )
    evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
    lines = fixtures.get_evaluation_lines(evaluation["id"])
    get_success_data(api_client.start_evaluation_review(evaluation["id"], EVALUATOR))
    fixtures.adopt_all_lines(evaluation["id"], lines)
    fixtures.finalize_evaluation(evaluation["id"], EVAL_A)
    return student, evaluation, lines


class TestWaterfallSlotNeedSpillWithCapTruncation:
    def test_slot_needs_spill_and_global_cap(self):
        """PRD §3.6: "The waterfall maintains per-slot need and fill: `MAJOR_CORE`
        admits 30.0 credits, `MAJOR_ELECTIVE` 12.0, each general-education slot
        (`GENED_COMMS`, `GENED_MATH`, `GENED_SCIENCE`, `GENED_HUMANITIES`,
        `GENED_SOCIAL`) admits 6.0, and `FREE_ELECTIVE` admits 24.0; a global purse
        caps all transfer credit at 60.0."
        PRD §3.6: "any leftover then spills into `FREE_ELECTIVE` — unless the
        natural slot already is `FREE_ELECTIVE` — again bounded by the leftover,
        that slot's remaining need, and the remaining global purse."

        Design: Difficulty/combinatorial_formula/waterfall_slot_need_spill_with_cap_truncation
        """
        student, evaluation, lines = _build_twelve_line_evaluation()
        fixtures.post_evaluation(evaluation["id"], EVAL_B)

        posted = get_success_data(api_client.get_evaluation(evaluation["id"], EVALUATOR))
        assert posted["applied_credits_total"] == pytest.approx(60.0, abs=1e-9)

        by_code = {}
        for line in lines:
            refreshed = get_success_data(api_client.get_line_item(line["id"], EVALUATOR))
            by_code[refreshed["external_course_code"]] = refreshed

        # MAJOR_CORE need 30.0 filled exactly by the five 6.0 MATH lines.
        for code in ("M-101", "M-102", "M-103", "M-104", "M-105"):
            assert by_code[code]["applied_credits"] == pytest.approx(6.0, abs=1e-9), code

        # E-201: 5.0 all into GENED_COMMS (need 6.0).
        assert by_code["E-201"]["applied_credits"] == pytest.approx(5.0, abs=1e-9)
        # E-202: 1.0 GENED_COMMS + 4.0 spill to FREE_ELECTIVE (two rows).
        e2_rows = get_success_data(api_client.list_requirement_applications(
            EVALUATOR, params={"line_item_id": by_code["E-202"]["id"]}
        ))
        row_set = {(r["slot"], r["applied_credits"]) for r in e2_rows}
        assert row_set == {("GENED_COMMS", 1.0), ("FREE_ELECTIVE", 4.0)}, row_set
        assert by_code["E-202"]["applied_credits"] == pytest.approx(5.0, abs=1e-9)

        # H-301..H-304 each 5.0 to FREE_ELECTIVE (4.0 spill + 20.0 = 24.0 full).
        for code in ("H-301", "H-302", "H-303", "H-304"):
            assert by_code[code]["applied_credits"] == pytest.approx(5.0, abs=1e-9), code

        # H-305: global cap reached exactly; line gets nothing but still yields a row.
        h5_rows = get_success_data(api_client.list_requirement_applications(
            EVALUATOR, params={"line_item_id": by_code["H-305"]["id"]}
        ))
        assert by_code["H-305"]["applied_credits"] == pytest.approx(0.0, abs=1e-9)
        assert len(h5_rows) == 1
        assert h5_rows[0]["applied_credits"] == pytest.approx(0.0, abs=1e-9)
        assert h5_rows[0]["status"] == "UNAPPLIED"

        refreshed_student = get_success_data(api_client.get_student(student["id"], EVALUATOR))
        assert refreshed_student["total_posted_transfer_credits"] == pytest.approx(60.0, abs=1e-9)

    def test_requirement_application_row_status_stamps(self):
        """PRD §3.6: "each row carries its `student_id`, the `line_item_id` it came
        from, its `slot`, its `applied_credits`, and a `status` stamped from the
        line's outcome: `APPLIED` when the full award was placed, `PARTIAL` when
        some but not all was, `UNAPPLIED` when nothing was."

        Design: Difficulty/combinatorial_formula/waterfall_slot_need_spill_with_cap_truncation
        """
        student, evaluation, lines = _build_twelve_line_evaluation()
        fixtures.post_evaluation(evaluation["id"], EVAL_B)

        rows = get_success_data(api_client.list_requirement_applications(
            EVALUATOR, params={"student_id": student["id"]}
        ))
        assert rows, "posting must create RequirementApplication rows"
        by_line = {}
        for r in rows:
            by_line.setdefault(r["line_item_id"], []).append(r)

        code_by_line_id = {}
        for line in lines:
            refreshed = get_success_data(api_client.get_line_item(line["id"], EVALUATOR))
            code_by_line_id[line["id"]] = refreshed["external_course_code"]

        for line_id, line_rows in by_line.items():
            code = code_by_line_id[line_id]
            if code == "H-305":
                assert all(r["status"] == "UNAPPLIED" for r in line_rows)
            else:
                # Every other line placed its full award (natural + spill).
                assert all(r["status"] == "APPLIED" for r in line_rows), (code, line_rows)
            # One row per line per bucket the line was placed into.
            for r in line_rows:
                assert r["student_id"] == student["id"]


class TestPostEffectsImmediatelyVisible:
    def test_post_response_and_reads_consistent(self):
        """PRD §3.6: "Posting then moves every adopted line to `POSTED`, adds the
        sum of the newly posted `applied_credits` onto the student's
        `total_posted_transfer_credits`, and records `applied_credits_total`,
        `posted_by_id`, and `posted_at` on the evaluation."

        Design: Corner/consistency_model/post_effects_immediately_visible
        """
        ctx = fixtures.setup_evaluation_in_review(
            course_kwargs={"code": "MATH-150", "credit_hours": 4.0, "department": "MATH"},
            equivalency_kwargs={"external_course_code": "M-101", "external_credit_hours": 4.0},
            transcript_courses=[create_transcript_course_payload(
                external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A")],
        )
        fixtures.adopt_all_lines(ctx["evaluation"]["id"], ctx["lines"])
        fixtures.finalize_evaluation(ctx["evaluation"]["id"], EVAL_A)

        post_resp = api_client.post_evaluation(ctx["evaluation"]["id"], EVAL_B)
        posted = get_success_data(post_resp)
        assert posted["status"] == "POSTED", "post response itself reflects committed state"
        assert posted["applied_credits_total"] == pytest.approx(4.0, abs=1e-9)
        assert posted["posted_by_id"] == "eval-b"
        assert posted["posted_at"] is not None

        student = get_success_data(api_client.get_student(ctx["student"]["id"], EVALUATOR))
        assert student["total_posted_transfer_credits"] == pytest.approx(4.0, abs=1e-9)

        rows = get_success_data(api_client.list_requirement_applications(
            EVALUATOR, params={"student_id": ctx["student"]["id"]}
        ))
        assert len(rows) == 1
        assert rows[0]["slot"] == "MAJOR_CORE"
        assert rows[0]["applied_credits"] == pytest.approx(4.0, abs=1e-9)
        assert rows[0]["status"] == "APPLIED"
