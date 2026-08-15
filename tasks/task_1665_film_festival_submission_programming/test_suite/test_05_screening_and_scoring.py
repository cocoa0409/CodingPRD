"""Screening phase: assignments, scores, recusal selector, and the
NEEDS_INFO revision loop (PRD §3.3, §3.4)."""
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    create_score_payload,
    fx_screening,
    make_filmmaker_headers, make_programmer_headers,
    set_clock,
    st_advance, st_assign, st_edition, st_film, st_programmer, st_rule,
    st_score, st_submitter,
    validate_error, validate_success,
    TEST_USERS,
)

CHAIR = TEST_USERS["chair_headers"]


def _screening_ctx():
    """Edition in SCREENING with one paid IN_SCREENING film."""
    ctx = st_edition()
    st_advance(ctx, "INTAKE_OPEN")
    submitter = st_submitter({"email": "ann@example.com"})
    film = st_film(ctx, submitter, {"title": "Screened"})
    st_rule(ctx, film["id"], "ELIGIBLE")
    st_advance(ctx, "INTAKE_CLOSED")
    st_advance(ctx, "SCREENING")
    return ctx, submitter, film


class TestAssignmentGuards:
    def test_coi_and_body_fk_guards_on_assignment(self, api):
        """PRD §3.4: "when the film's `production_company` appears in the
        programmer's `coi_production_companies`, the assignment is rejected
        with `ERR_COI_RECUSAL_REQUIRED`"; §2.9: "body-referenced entities are
        checked for existence and same-edition membership
        (`ERR_REFERENTIAL_INTEGRITY`, HTTP 422)."

        Design: Corner/validations/coi_and_body_fk_guards_on_assignment
        """
        ctx, _submitter, film = _screening_ctx()
        # Recreate the film with the conflicted production company.
        conflicted = st_programmer({
            "display_name": "Conflicted",
            "coi_production_companies": [film["production_company"]],
        })
        coi = api.create_screener_assignment(
            {"submission_id": film["id"], "programmer_id": conflicted["id"],
             "due_at": "2026-11-01T00:00:00Z"},
            CHAIR,
        )
        validate_error(coi, ApiErrorId.ERR_COI_RECUSAL_REQUIRED.value)

        ghost = api.create_screener_assignment(
            {"submission_id": film["id"], "programmer_id": NON_EXISTENT_UUID,
             "due_at": "2026-11-01T00:00:00Z"},
            CHAIR,
        )
        validate_error(ghost, ApiErrorId.ERR_REFERENTIAL_INTEGRITY.value)

    def test_assignment_cap_and_duplicate_guards(self, api, chair_headers):
        """PRD §3.4: "A programmer already holding `max_active_assignments`
        open assignments cannot take another, rejected with
        `ERR_ASSIGNMENT_CAP`, and a duplicate open assignment for the same
        submission–programmer pair is rejected with
        `ERR_DUPLICATE_ASSIGNMENT`."

        Design: Corner/validations/assignment_cap_and_duplicate_guards
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        film_a = st_film(ctx, submitter, {"title": "Cap A"})
        film_b = st_film(ctx, submitter, {"title": "Cap B"})
        st_rule(ctx, film_a["id"], "ELIGIBLE")
        st_rule(ctx, film_b["id"], "ELIGIBLE")
        st_advance(ctx, "INTAKE_CLOSED")
        st_advance(ctx, "SCREENING")

        capped = st_programmer({"display_name": "Capped",
                                "max_active_assignments": 1})
        free = st_programmer({"display_name": "Free"})
        st_assign(film_a["id"], capped["id"])
        st_assign(film_a["id"], free["id"])

        over_cap = api.create_screener_assignment(
            {"submission_id": film_b["id"], "programmer_id": capped["id"],
             "due_at": "2026-11-01T00:00:00Z"},
            chair_headers,
        )
        validate_error(over_cap, ApiErrorId.ERR_ASSIGNMENT_CAP.value)

        duplicate = api.create_screener_assignment(
            {"submission_id": film_a["id"], "programmer_id": free["id"],
             "due_at": "2026-11-01T00:00:00Z"},
            chair_headers,
        )
        validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_ASSIGNMENT.value)


class TestScoreGuards:
    def test_score_exists_and_range_guards(self, api):
        """PRD §3.4: "Each assignment accepts exactly one score, its
        `assignment_id` unique; a second score against the same assignment is
        rejected with `ERR_SCORE_EXISTS`" and rubric axes are "each an integer
        from 1 to 10, with out-of-range values rejected as `ERR_VALIDATION`."

        Design: Corner/validations/score_exists_and_range_guards
        """
        ctx, _submitter, film = _screening_ctx()
        p1 = st_programmer({"display_name": "S1"})
        p2 = st_programmer({"display_name": "S2"})
        a1 = st_assign(film["id"], p1["id"])
        a2 = st_assign(film["id"], p2["id"])
        st_score(a1["id"], p1["id"], 8)

        second = api.create_score(
            a1["id"], create_score_payload(overall=9),
            make_programmer_headers(p1["id"]),
        )
        validate_error(second, ApiErrorId.ERR_SCORE_EXISTS.value)

        out_of_range = api.create_score(
            a2["id"], create_score_payload(overall=11),
            make_programmer_headers(p2["id"]),
        )
        validate_error(out_of_range, ApiErrorId.ERR_VALIDATION.value)

    def test_scores_locked_after_deliberation(self, api, admin_headers):
        """PRD §3.4: "While the edition remains in `SCREENING`, the scoring
        programmer may revise a score's `originality`, `craft`, `story`,
        `overall`, or `recommendation`, and the film's aggregates recompute on
        each edit; once the edition advances to `DELIBERATION` the score's
        `locked` flag is true and edits are rejected with
        `ERR_SCORES_LOCKED`."

        Design: Corner/validations/scores_locked_after_deliberation
        """
        ctx, _submitter, film = _screening_ctx()
        p1 = st_programmer({"display_name": "S1"})
        p2 = st_programmer({"display_name": "S2"})
        a1 = st_assign(film["id"], p1["id"])
        a2 = st_assign(film["id"], p2["id"])
        score1 = st_score(a1["id"], p1["id"], 8)
        st_score(a2["id"], p2["id"], 9)

        patched = validate_success(api.update_score(
            score1["id"], {"overall": 9}, make_programmer_headers(p1["id"]),
        ))
        assert patched["overall"] == 9

        st_advance(ctx, "DELIBERATION")
        locked = api.update_score(
            score1["id"], {"overall": 3}, make_programmer_headers(p1["id"]),
        )
        validate_error(locked, ApiErrorId.ERR_SCORES_LOCKED.value)

        stored = validate_success(api.get_score(score1["id"], admin_headers))
        assert stored["overall"] == 9
        assert stored["locked"] is True


class TestScoreAggregates:
    def test_provisional_and_composite_from_same_scores(self, api, admin_headers):
        """PRD §3.4: "The `provisional_score` is the simple mean of `overall`
        across the film's `SCORED` assignments, rounded half up to three
        decimal places ... The `composite_score` is the seniority-weighted
        mean of the same inputs — `STAFF` scores weigh 1.0, `SENIOR` 1.5, and
        `LEAD` 2.0 — ... A worked example: scores of 8 from a `LEAD`, 7 from a
        `SENIOR`, and 9 from a `STAFF` give a weighted sum of 35.5 against a
        total weight of 4.5, a quotient of 7.8888… that rounds to 7.889,
        while the provisional mean is 8.000."

        Design: Difficulty/dual_variant_calc/score_provisional_vs_weighted_official
        """
        ctx = fx_screening(
            films=[{
                "title": "Cold Harbor",
                "scores": [("LEAD", 8), ("SENIOR", 7), ("STAFF", 9)],
                "submission_over": {"runtime_minutes": 95,
                                    "production_company": "Acme Films"},
            }],
            category="NARRATIVE_FEATURE",
            config_over={
                "min_runtime_minutes": 70, "max_runtime_minutes": 120,
                "premiere_requirement": "US_REQUIRED",
                "early_fee_cents": 9000, "regular_fee_cents": 12000,
                "late_fee_cents": 15000, "screener_count_required": 3,
            },
        )
        film_id = ctx["films"][0]["film"]["id"]
        film = validate_success(api.get_submission(film_id, admin_headers))
        assert film["provisional_score"] == pytest.approx(8.0, abs=1e-9)
        assert film["composite_score"] == pytest.approx(7.889, abs=1e-9)

    def test_provisional_differs_from_composite_on_identical_inputs(self, api, admin_headers):
        """PRD §3.4: the same worked example pins the divergence — "a quotient
        of 7.8888… that rounds to 7.889, while the provisional mean is
        8.000" — so on identical SCORED rows the unweighted and
        seniority-weighted aggregates legitimately differ.

        Design: Difficulty/dual_variant_calc/score_provisional_vs_weighted_official
        """
        ctx = fx_screening(
            films=[{
                "title": "Cold Harbor",
                "scores": [("LEAD", 8), ("SENIOR", 7), ("STAFF", 9)],
                "submission_over": {"runtime_minutes": 95,
                                    "production_company": "Acme Films"},
            }],
            category="NARRATIVE_FEATURE",
            config_over={
                "min_runtime_minutes": 70, "max_runtime_minutes": 120,
                "premiere_requirement": "US_REQUIRED",
                "early_fee_cents": 9000, "regular_fee_cents": 12000,
                "late_fee_cents": 15000, "screener_count_required": 3,
            },
        )
        film_id = ctx["films"][0]["film"]["id"]
        film = validate_success(api.get_submission(film_id, admin_headers))
        assert film["provisional_score"] != film["composite_score"], (
            "unweighted mean (8.000) and seniority-weighted mean (7.889) must "
            "diverge on the same three scores"
        )

    def test_composite_null_until_required_score_count(self, api, admin_headers):
        """PRD §3.4: the composite "remains null until the count of `SCORED`
        assignments reaches the category's `screener_count_required`", while
        the provisional "is the simple mean of `overall` across the film's
        `SCORED` assignments ... and is null while no score exists."

        Design: Corner/calculations/composite_null_until_required_score_count
        """
        ctx, _submitter, film = _screening_ctx()
        p1 = st_programmer({"display_name": "S1"})
        a1 = st_assign(film["id"], p1["id"])
        st_score(a1["id"], p1["id"], 8)  # 1 SCORED of the required 2

        read = validate_success(api.get_submission(film["id"], admin_headers))
        assert read["provisional_score"] == pytest.approx(8.0, abs=1e-9)
        assert read["composite_score"] is None


class TestNeedsInfoCycle:
    def _needs_info_ctx(self, api):
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter({"email": "nora@example.com"})
        film = st_film(ctx, submitter, {"title": "Loop Study",
                                        "premiere_status": "NONE",
                                        "production_company": "Loop Films",
                                        "format": "PRORES_4444",
                                        "runtime_minutes": 12})
        st_rule(ctx, film["id"], "NEEDS_INFO", reason="runtime credit sheet missing")
        return ctx, submitter, film

    def test_resubmit_rejected_until_flag_set(self, api):
        """PRD §3.3: "A ruling of `NEEDS_INFO` returns the film to the
        filmmaker with `needs_info_resolved` cleared to false; after amending
        the record — which sets the flag true — the filmmaker resubmits, and a
        resubmission attempted while the flag is still false is rejected with
        `ERR_UNRESOLVED_INFO_REQUEST`."

        Design: Difficulty/non_linear_state_machine/submission_needs_info_revision_cycle
        """
        _ctx, submitter, film = self._needs_info_ctx(api)
        headers = make_filmmaker_headers(submitter["id"])

        early = api.resubmit_submission(film["id"], headers)
        validate_error(early, ApiErrorId.ERR_UNRESOLVED_INFO_REQUEST.value)

        amended = validate_success(api.update_submission(
            film["id"], {"production_company": "Loop Films LLC"}, headers,
        ))
        assert amended["needs_info_resolved"] is True
        assert amended["status"] == "NEEDS_INFO"

        resubmitted = validate_success(api.resubmit_submission(film["id"], headers))
        assert resubmitted["status"] == "SUBMITTED"

    def test_cycle_completes_with_payment_dimension_untouched(self, api, admin_headers):
        """PRD §3.3: "The `SUBMITTED` → `NEEDS_INFO` → `SUBMITTED` revision
        cycle may repeat as often as needed", and §3.2: payment success moves
        "`payment_status` `UNPAID` → `PAID`" with no ruling step ever touching
        it.

        Design: Difficulty/non_linear_state_machine/submission_needs_info_revision_cycle
        """
        ctx, submitter, film = self._needs_info_ctx(api)
        headers = make_filmmaker_headers(submitter["id"])
        validate_success(api.update_submission(
            film["id"], {"production_company": "Loop Films LLC"}, headers,
        ))
        validate_success(api.resubmit_submission(film["id"], headers))

        ruled = st_rule(ctx, film["id"], "ELIGIBLE")
        assert ruled["status"] == "ELIGIBLE"

        final = validate_success(api.get_submission(film["id"], admin_headers))
        assert final["payment_status"] == "PAID", (
            "the payment dimension never cycled with the program pipeline"
        )


class TestReplacementSelector:
    def test_clock_sweep_expires_assignment_and_reassigns(self, api, chair_headers):
        """PRD §2.4: "When the clock moves past a screener assignment's
        `due_at`, a non-terminal assignment expires and the replacement
        selector runs"; §3.4: the pool admits only programmers "who have never
        held an assignment for this submission in any status", and "the
        retired assignment's `replaced_by_assignment_id` points at that new
        row".

        Design: Corner/state_machines/clock_sweep_expires_assignment_and_reassigns
        """
        ctx, _submitter, film = _screening_ctx()
        p1 = st_programmer({"display_name": "S1", "email": "s1@example.com"})
        set_clock("2026-08-02T00:00:00Z")
        p2 = st_programmer({"display_name": "S2", "email": "s2@example.com"})
        a1 = st_assign(film["id"], p1["id"], due_at="2026-10-01T00:00:00Z")

        set_clock("2026-10-02T00:00:00Z")  # past due_at: sweep fires
        expired = validate_success(
            api.get_screener_assignment(a1["id"], chair_headers)
        )
        assert expired["status"] == "EXPIRED"

        open_rows = validate_success(api.list_screener_assignments(
            chair_headers,
            params={"submission_id": film["id"], "status": "ASSIGNED"},
        ))
        assert len(open_rows) == 1
        replacement = open_rows[0]
        assert replacement["programmer_id"] == p2["id"], (
            "p1 is excluded (it has held an assignment for this submission); "
            "p2 is the next-ranked eligible programmer"
        )
        assert expired["replaced_by_assignment_id"] == replacement["id"]

    def test_recuse_replacement_selector_and_empty_pool(self, api, chair_headers):
        """PRD §3.4: "The pool is ranked by `active_assignment_count`
        ascending, ties broken by the programmer's `created_at` ascending, and
        the first-ranked programmer receives a fresh `ASSIGNED` assignment ...
        When the pool is empty no replacement is created and
        `replaced_by_assignment_id` stays null."

        Design: Corner/state_machines/recuse_replacement_selector_and_empty_pool
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        film_x = st_film(ctx, submitter, {"title": "Recuse X"})
        film_y = st_film(ctx, submitter, {"title": "Recuse Y"})
        st_rule(ctx, film_x["id"], "ELIGIBLE")
        st_rule(ctx, film_y["id"], "ELIGIBLE")
        st_advance(ctx, "INTAKE_CLOSED")
        st_advance(ctx, "SCREENING")

        p1 = st_programmer({"display_name": "S1", "email": "s1@example.com"})
        set_clock("2026-08-02T00:00:00Z")
        p2 = st_programmer({"display_name": "S2", "email": "s2@example.com"})
        set_clock("2026-08-03T00:00:00Z")
        p3 = st_programmer({"display_name": "S3", "email": "s3@example.com"})

        a_x = st_assign(film_x["id"], p1["id"])
        a_y = st_assign(film_y["id"], p2["id"])
        a_y3 = st_assign(film_y["id"], p3["id"])

        # Film X: p1 recuses; p2 and p3 tie on count (1 each) -> p2 created
        # earlier (2026-08-02) wins.
        recused_x = validate_success(api.recuse_assignment(
            a_x["id"], make_programmer_headers(p1["id"]),
        ))
        assert recused_x["status"] == "RECUSED"
        open_x = validate_success(api.list_screener_assignments(
            chair_headers,
            params={"submission_id": film_x["id"], "status": "ASSIGNED"},
        ))
        assert len(open_x) == 1
        assert open_x[0]["programmer_id"] == p2["id"]

        # Film Y: p2 recuses; p1 (count 0 after its recusal) beats p3 (count 1)
        # on count-ascending before created_at is consulted.
        validate_success(api.recuse_assignment(
            a_y["id"], make_programmer_headers(p2["id"]),
        ))
        open_y = validate_success(api.list_screener_assignments(
            chair_headers,
            params={"submission_id": film_y["id"], "status": "ASSIGNED"},
        ))
        assert {row["programmer_id"] for row in open_y} == {p1["id"], p3["id"]}

        # Film Y: p3 recuses; every programmer has held a row for Y, so the
        # pool is empty and no replacement is created.
        recused_y3 = validate_success(api.recuse_assignment(
            a_y3["id"], make_programmer_headers(p3["id"]),
        ))
        assert recused_y3["status"] == "RECUSED"
        assert recused_y3["replaced_by_assignment_id"] is None

        final_y = validate_success(api.list_screener_assignments(
            chair_headers,
            params={"submission_id": film_y["id"], "status": "ASSIGNED"},
        ))
        assert len(final_y) == 1
        assert final_y[0]["programmer_id"] == p1["id"]

    def test_programmer_deactivation_reassigns_open_assignments(self, api, admin_headers, chair_headers):
        """PRD §3.1: "flipping `active` from true to false recuses every
        assignment the programmer currently holds and runs the replacement
        selector of §3.4 for each"; §3.4: the pool is "ranked by
        `active_assignment_count` ascending".

        Design: Corner/cross_cutting_layers/programmer_deactivation_reassigns_open_assignments
        """
        ctx = st_edition()
        st_advance(ctx, "INTAKE_OPEN")
        submitter = st_submitter()
        film_x = st_film(ctx, submitter, {"title": "Deact X"})
        film_y = st_film(ctx, submitter, {"title": "Deact Y"})
        st_rule(ctx, film_x["id"], "ELIGIBLE")
        st_rule(ctx, film_y["id"], "ELIGIBLE")
        st_advance(ctx, "INTAKE_CLOSED")
        st_advance(ctx, "SCREENING")

        p1 = st_programmer({"display_name": "S1"})
        p2 = st_programmer({"display_name": "S2"})
        a_x = st_assign(film_x["id"], p1["id"])
        a_y = st_assign(film_y["id"], p1["id"])

        patched = validate_success(api.update_programmer(
            p1["id"], {"active": False}, admin_headers,
        ))
        assert patched["active"] is False
        assert patched["active_assignment_count"] == 0

        for old, film in ((a_x, film_x), (a_y, film_y)):
            stale = validate_success(
                api.get_screener_assignment(old["id"], chair_headers)
            )
            assert stale["status"] == "RECUSED"
            open_rows = validate_success(api.list_screener_assignments(
                chair_headers,
                params={"submission_id": film["id"], "status": "ASSIGNED"},
            ))
            assert len(open_rows) == 1
            assert open_rows[0]["programmer_id"] == p2["id"], (
                "the idle eligible p2 is selected as the replacement"
            )
            assert stale["replaced_by_assignment_id"] == open_rows[0]["id"]
