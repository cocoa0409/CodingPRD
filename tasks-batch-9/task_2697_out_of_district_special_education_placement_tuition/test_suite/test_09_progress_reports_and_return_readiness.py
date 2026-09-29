"""
Quarterly progress reporting, the two readiness aggregations and the gate they feed.

Readiness is a mean of already-rounded per-report scores drawn only from ACCEPTED
reports; the two variants disagree about which quarters may contribute, and the
activation ladder puts plan completeness above readiness above money.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_DUPLICATE_PROGRESS_PERIOD,
    ERR_DUPLICATE_RESOURCE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_RETURN_READINESS_NOT_MET,
    ERR_TRANSITION_SERVICES_INCOMPLETE,
)
from test_helpers.assertions import assert_ledger, assert_score
from test_helpers.fixtures import (
    accept_progress_report,
    build_active_day_placement,
    build_readiness_world,
    list_rows,
    make_draft_plan,
    read_account,
    read_placement,
    read_plan,
    read_readiness,
    read_report,
    submit_progress_report,
)
from test_helpers.test_users import COORDINATOR_HEADERS, TEAM_CHAIR_HEADERS

AUTHORIZED_CENTS = 100000000
DAY_CONTRACT_ENCUMBRANCE_CENTS = 5760000
RESERVE_CENTS = 250000
ENCUMBERED_WITH_RESERVE_CENTS = 6010000
AVAILABLE_WITH_RESERVE_CENTS = 93990000
AVAILABLE_WITHOUT_RESERVE_CENTS = 94240000

# ─── The three-quarter climb: 46.10, 63.00, 80.30 ─────────────────────────────
CLIMB_Q1 = {
    "goals_total": 10,
    "goals_met": 4,
    "goals_regressed": 2,
    "benchmark_scaled_score": 55,
    "attendance_rate_pct": 88,
}
CLIMB_Q2 = {
    "goals_total": 10,
    "goals_met": 6,
    "goals_regressed": 1,
    "benchmark_scaled_score": 62,
    "attendance_rate_pct": 92,
}
CLIMB_Q3 = {
    "goals_total": 10,
    "goals_met": 8,
    "goals_regressed": 0,
    "benchmark_scaled_score": 71,
    "attendance_rate_pct": 95,
}
CLIMB_SCORES = (46.10, 63.00, 80.30)
TRAILING_SCORE = 71.65
RECENCY_SCORE = 67.12
VARIANT_GAP = 4.53
REPORTING_INSTANT = "2027-04-01T09:00:00Z"

# ─── The boundary pair: 62.00, 62.90 and then 62.10 ───────────────────────────
FLOOR_Q1 = {
    "goals_total": 10,
    "goals_met": 6,
    "goals_regressed": 1,
    "benchmark_scaled_score": 60,
    "attendance_rate_pct": 90,
}
FLOOR_Q2 = dict(FLOOR_Q1, attendance_rate_pct=94.5)
FLOOR_Q3 = dict(FLOOR_Q1, attendance_rate_pct=90.5)
FLOOR_Q1_SCORE = 62.00
FLOOR_Q2_SCORE = 62.90
FLOOR_Q3_SCORE = 62.10
BELOW_FLOOR_SCORE = 62.45
AT_FLOOR_SCORE = 62.50
RECENCY_ABOVE_FLOOR_SCORE = 62.53

# ─── The single strong quarter: 80.00 ─────────────────────────────────────────
STRONG_QUARTER = {
    "goals_total": 10,
    "goals_met": 8,
    "goals_regressed": 0,
    "benchmark_scaled_score": 70,
    "attendance_rate_pct": 95,
}
STRONG_SCORE = 80.00

TRANSITION_SERVICES = ["Transition IEP meeting", "Two-week reverse mainstream trial"]
SINGLE_SERVICE = ["Transition IEP meeting"]
BRIDGE_PLAN = {
    "target_return_date": "2027-05-01",
    "receiving_program": "Northvale Bridge Program",
}
READINESS_READ_INSTANT = "2027-01-15T09:00:00Z"


def _activate(api, plan_id, services, variant="trailing_two_quarter"):
    """The raw activation call, so both the 2xx and the refusals can be inspected."""
    return api.activate_transition_plan(
        plan_id,
        f.activate_plan_payload(
            transition_services=services, readiness_variant=variant
        ),
        TEAM_CHAIR_HEADERS,
    )


class TestReadinessVariantFork:
    """The two aggregations disagree about which quarters may contribute."""

    def test_the_trailing_variant_discards_the_oldest_quarter_outright(self, api):
        """
        Three accepted quarters climb 46.10, 63.00, 80.30, and the trailing mean
        takes only the two newest, so the weak first quarter cannot depress it.

        PRD: "Under the `trailing_two_quarter` variant, which is the default, only the first two rows of that ordering contribute, each with equal weight, and the readiness score is the plain arithmetic mean of their two `report_score` values, rounded half up to two decimal places."

        Design: Difficulty/dual_variant_calc/return_readiness_trailing_versus_recency_weighted
        """
        world = build_readiness_world(
            api,
            [dict(CLIMB_Q1), dict(CLIMB_Q2), dict(CLIMB_Q3)],
            plan_instant=REPORTING_INSTANT,
        )
        for report, expected in zip(world["reports"], CLIMB_SCORES):
            assert report["status"] == "ACCEPTED"
            assert_score(report["report_score"], expected)

        readiness = read_readiness(api, world["plan"]["id"], "trailing_two_quarter")
        assert readiness["variant"] == "trailing_two_quarter"
        assert_score(readiness["readiness_score"], TRAILING_SCORE)
        assert readiness["accepted_report_count"] == 3
        assert readiness["readiness_met"] is True
        assert len(readiness["report_scores"]) == 2
        assert_score(readiness["report_scores"][0], CLIMB_SCORES[2])
        assert_score(readiness["report_scores"][1], CLIMB_SCORES[1])

    def test_the_recency_weighted_variant_keeps_the_oldest_quarter_at_weight_049(
        self, api
    ):
        """
        The same three quarters score 4.53 points lower once every accepted report
        contributes under a decaying weight, and neither read touches the plan.

        PRD: "Under the `cumulative_recency_weighted` variant, **every** accepted report contributes, with a geometrically decaying weight: the newest row's weight is 0.7 raised to the power zero, that is 1; the next row's is 0.7; the next 0.49; and so on."

        Design: Difficulty/dual_variant_calc/return_readiness_trailing_versus_recency_weighted
        """
        world = build_readiness_world(
            api,
            [dict(CLIMB_Q1), dict(CLIMB_Q2), dict(CLIMB_Q3)],
            plan_instant=REPORTING_INSTANT,
        )
        plan_id = world["plan"]["id"]

        trailing = read_readiness(api, plan_id, "trailing_two_quarter")
        recency = read_readiness(api, plan_id, "cumulative_recency_weighted")

        assert recency["variant"] == "cumulative_recency_weighted"
        assert_score(recency["readiness_score"], RECENCY_SCORE)
        assert recency["accepted_report_count"] == 3
        assert recency["readiness_met"] is True
        assert [round(score, 2) for score in recency["report_scores"]] == [
            CLIMB_SCORES[2],
            CLIMB_SCORES[1],
            CLIMB_SCORES[0],
        ]
        assert_score(
            trailing["readiness_score"] - recency["readiness_score"], VARIANT_GAP
        )

        plan = read_plan(api, plan_id)
        assert plan["status"] == "DRAFT"
        assert plan["readiness_score_at_activation"] is None
        assert plan["reserve_cents"] == 0


class TestActivationLadderOrder:
    """Completeness at rung 11 answers before readiness at rung 12."""

    def test_the_empty_service_list_answers_before_the_missing_reports(self, api):
        """
        One call violates both gates — no services committed and no accepted
        reports at all — and the caller is told only about the completeness
        failure, with no reserve taken.

        PRD: "A plan can therefore be blocked for incompleteness while also being unready and unfunded, and the caller sees only the completeness error."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority_11_beats_constraint_priority_12_on_plan_activation
        """
        world = build_active_day_placement(api)
        plan = make_draft_plan(api, world["placement"]["id"])

        response = _activate(api, plan["id"], [])
        validate_error(response, ERR_TRANSITION_SERVICES_INCOMPLETE, 409)

        stored = read_plan(api, plan["id"])
        assert stored["status"] == "DRAFT"
        assert stored["reserve_cents"] == 0
        assert read_placement(api, world["placement"]["id"])[
            "transition_reserve_cents"
        ] == 0
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_WITHOUT_RESERVE_CENTS,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
        )

    def test_the_readiness_rung_is_reachable_once_the_services_are_supplied(self, api):
        """
        With a non-empty service list the same plan, still with no accepted
        reports, is refused one rung lower down.

        PRD: "At rung 12, the readiness gate: the placement must have at least two `ACCEPTED` progress reports **and** the readiness score under the requested variant must be at least 62.50; either failure is refused with `ERR_RETURN_READINESS_NOT_MET`."

        Design: Difficulty/priority_pair_validation_conflict/safety_priority_11_beats_constraint_priority_12_on_plan_activation
        """
        world = build_active_day_placement(api)
        plan = make_draft_plan(api, world["placement"]["id"])

        response = _activate(api, plan["id"], TRANSITION_SERVICES)
        validate_error(response, ERR_RETURN_READINESS_NOT_MET, 409)

        stored = read_plan(api, plan["id"])
        assert stored["status"] == "DRAFT"
        assert stored["reserve_cents"] == 0
        assert stored["transition_services"] == []
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_WITHOUT_RESERVE_CENTS,
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
        )


class TestReadinessFloorBoundary:
    """The 62.50 floor is inclusive against a score rounded half up to two places."""

    def test_a_trailing_mean_of_62_45_is_refused(self, api):
        """
        Quarters of 62.00 and 62.90 average five hundredths below the floor, and
        the readiness read reports the two contributing scores newest first.

        PRD: "Under either variant, readiness is met when the score is greater than or equal to 62.50."

        Design: Difficulty/boundary_precision_check/readiness_floor_inclusive_at_exactly_62_50_and_fails_at_62_45
        """
        world = build_readiness_world(api, [dict(FLOOR_Q1), dict(FLOOR_Q2)])
        assert_score(world["reports"][0]["report_score"], FLOOR_Q1_SCORE)
        assert_score(world["reports"][1]["report_score"], FLOOR_Q2_SCORE)

        readiness = read_readiness(api, world["plan"]["id"])
        assert_score(readiness["readiness_score"], BELOW_FLOOR_SCORE)
        assert readiness["accepted_report_count"] == 2
        assert readiness["readiness_met"] is False
        assert [round(score, 2) for score in readiness["report_scores"]] == [
            FLOOR_Q2_SCORE,
            FLOOR_Q1_SCORE,
        ]

        response = _activate(api, world["plan"]["id"], TRANSITION_SERVICES)
        validate_error(response, ERR_RETURN_READINESS_NOT_MET, 409)

        stored = read_plan(api, world["plan"]["id"])
        assert stored["status"] == "DRAFT"
        assert stored["reserve_cents"] == 0
        assert stored["transition_services"] == []

    def test_a_trailing_mean_of_exactly_62_50_activates_the_plan(self, api):
        """
        A third quarter scoring 62.10 replaces the oldest contributor and lands the
        mean exactly on the floor, which passes and reserves the transition money.

        PRD: "The comparison is inclusive, so a score of exactly 62.50 passes."

        Design: Difficulty/boundary_precision_check/readiness_floor_inclusive_at_exactly_62_50_and_fails_at_62_45
        """
        world = build_readiness_world(api, [dict(FLOOR_Q1), dict(FLOOR_Q2)])
        plan_id = world["plan"]["id"]
        placement_id = world["placement"]["id"]
        validate_error(
            _activate(api, plan_id, TRANSITION_SERVICES),
            ERR_RETURN_READINESS_NOT_MET,
            409,
        )

        third = submit_progress_report(api, placement_id, 3, **dict(FLOOR_Q3))
        accepted = accept_progress_report(api, third["id"])
        assert_score(accepted["report_score"], FLOOR_Q3_SCORE)

        activated = validate_success(_activate(api, plan_id, TRANSITION_SERVICES))
        assert activated["status"] == "ACTIVE"
        assert_score(activated["readiness_score_at_activation"], AT_FLOOR_SCORE)
        assert activated["reserve_cents"] == RESERVE_CENTS
        assert activated["transition_services"] == TRANSITION_SERVICES

        assert read_placement(api, placement_id)["transition_reserve_cents"] == (
            RESERVE_CENTS
        )
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_WITH_RESERVE_CENTS,
            encumbered=ENCUMBERED_WITH_RESERVE_CENTS,
            disbursed=0,
        )


class TestAcceptedReportCountFloor:
    """The readiness gate has two independent conditions; this is the count one."""

    def test_a_single_accepted_report_far_above_the_floor_still_blocks(self, api):
        """
        One quarter scoring 80.00 is miles above the threshold, but a second
        quarter left SUBMITTED does not count toward the two-report minimum.

        PRD: "At rung 12, the readiness gate: the placement must have at least two `ACCEPTED` progress reports **and** the readiness score under the requested variant must be at least 62.50; either failure is refused with `ERR_RETURN_READINESS_NOT_MET`."

        Design: Difficulty/boundary_precision_check/min_accepted_reports_count_boundary_at_one_versus_two
        """
        world = build_readiness_world(
            api,
            [dict(STRONG_QUARTER), dict(STRONG_QUARTER, leave_submitted=True)],
        )
        accepted, pending = world["reports"]
        assert accepted["status"] == "ACCEPTED"
        assert_score(accepted["report_score"], STRONG_SCORE)
        assert pending["status"] == "SUBMITTED"
        assert_score(pending["report_score"], STRONG_SCORE)

        readiness = read_readiness(api, world["plan"]["id"])
        assert readiness["accepted_report_count"] == 1
        assert readiness["readiness_met"] is False
        assert_score(readiness["readiness_score"], STRONG_SCORE)

        response = _activate(api, world["plan"]["id"], SINGLE_SERVICE)
        validate_error(response, ERR_RETURN_READINESS_NOT_MET, 409)

        stored = read_plan(api, world["plan"]["id"])
        assert stored["status"] == "DRAFT"
        assert stored["reserve_cents"] == 0

    def test_accepting_the_second_report_moves_the_count_from_one_to_two(self, api):
        """
        Nothing about the score changes; only the disposition of the second report
        does, and the identical activation then succeeds and stamps the frozen
        figure.

        PRD: "`status` becomes `ACTIVE`; `transition_services` is stored verbatim as supplied; `readiness_score_at_activation` is stamped with the score computed under the applied variant, freezing the figure the decision rested on even though later reports will move the live computation; `reserve_cents` is set to 250 000."

        Design: Difficulty/boundary_precision_check/min_accepted_reports_count_boundary_at_one_versus_two
        """
        world = build_readiness_world(
            api,
            [dict(STRONG_QUARTER), dict(STRONG_QUARTER, leave_submitted=True)],
        )
        plan_id = world["plan"]["id"]
        validate_error(
            _activate(api, plan_id, SINGLE_SERVICE), ERR_RETURN_READINESS_NOT_MET, 409
        )

        accept_progress_report(api, world["reports"][1]["id"])
        readiness = read_readiness(api, plan_id)
        assert readiness["accepted_report_count"] == 2
        assert readiness["readiness_met"] is True

        activated = validate_success(_activate(api, plan_id, SINGLE_SERVICE))
        assert activated["status"] == "ACTIVE"
        assert_score(activated["readiness_score_at_activation"], STRONG_SCORE)
        assert activated["reserve_cents"] == RESERVE_CENTS
        assert activated["transition_services"] == SINGLE_SERVICE
        assert_ledger(
            read_account(api, world["account"]["id"]),
            available=AVAILABLE_WITH_RESERVE_CENTS,
            encumbered=ENCUMBERED_WITH_RESERVE_CENTS,
            disbursed=0,
        )


class TestReadinessComputedRead:
    """A computed read compares the variants side by side and writes nothing."""

    def test_both_variants_are_readable_and_neither_touches_the_plan(self, api):
        """
        The same two quarters fail the floor under the default aggregation and pass
        it under the recency-weighted one, and the plan is untouched afterwards.

        PRD: "A computed read on a plan evaluates readiness under an optional `variant`, defaulting to `trailing_two_quarter`, and mutates nothing at all — in particular it never writes `readiness_score_at_activation`."

        Design: Corner/endpoints/readiness_computed_read_returns_both_variants_without_mutating_the_plan
        """
        world = build_readiness_world(
            api,
            [dict(FLOOR_Q1), dict(FLOOR_Q2)],
            plan_instant=READINESS_READ_INSTANT,
            plan_overrides=dict(BRIDGE_PLAN),
        )
        plan_id = world["plan"]["id"]

        default_read = validate_success(
            api.get_plan_readiness(plan_id, TEAM_CHAIR_HEADERS)
        )
        assert default_read["plan_id"] == plan_id
        assert default_read["variant"] == "trailing_two_quarter"
        assert_score(default_read["readiness_score"], BELOW_FLOOR_SCORE)
        assert default_read["accepted_report_count"] == 2
        assert default_read["readiness_met"] is False
        assert [round(score, 2) for score in default_read["report_scores"]] == [
            FLOOR_Q2_SCORE,
            FLOOR_Q1_SCORE,
        ]

        weighted_read = validate_success(
            api.get_plan_readiness(
                plan_id,
                TEAM_CHAIR_HEADERS,
                {"variant": "cumulative_recency_weighted"},
            )
        )
        assert weighted_read["variant"] == "cumulative_recency_weighted"
        assert_score(weighted_read["readiness_score"], RECENCY_ABOVE_FLOOR_SCORE)
        assert weighted_read["accepted_report_count"] == 2
        assert weighted_read["readiness_met"] is True

        plan = read_plan(api, plan_id)
        assert plan["status"] == "DRAFT"
        assert plan["readiness_score_at_activation"] is None
        assert plan["reserve_cents"] == 0
        assert plan["version"] == 1
        assert_ledger(
            read_account(api, world["account"]["id"]),
            encumbered=DAY_CONTRACT_ENCUMBRANCE_CENTS,
        )


class TestProgressReportDisposition:
    """One endpoint, two terminal outcomes chosen by the decision input."""

    def test_the_reject_branch_keeps_the_report_out_of_the_readiness_set(self, api):
        """
        A report strong enough to pass the floor on its own is rejected instead of
        accepted, so the readiness input set stays empty and the row is locked.

        PRD: "`REJECT` requires nothing of the placement's state, sets `status` to `REJECTED`, sets `report_score` to 0 — a rejected report never enters the readiness baseline, and zeroing its score makes that irreversible — and increments `version`."

        Design: Corner/endpoints/progress_report_reject_decision_takes_the_rejected_branch
        """
        world = build_active_day_placement(api)
        placement_id = world["placement"]["id"]
        report = submit_progress_report(api, placement_id, 1, **dict(STRONG_QUARTER))
        assert report["status"] == "SUBMITTED"
        assert_score(report["report_score"], STRONG_SCORE)
        plan = make_draft_plan(api, placement_id, **dict(BRIDGE_PLAN))

        rejected = validate_success(
            api.accept_progress_report(
                report["id"], f.accept_report_payload("REJECT"), COORDINATOR_HEADERS
            )
        )
        assert rejected["status"] == "REJECTED"
        assert_score(rejected["report_score"], 0)

        readiness = read_readiness(api, plan["id"])
        assert readiness["accepted_report_count"] == 0
        assert readiness["report_scores"] == []
        assert readiness["readiness_met"] is False

        replay = api.accept_progress_report(
            report["id"], f.accept_report_payload("ACCEPT"), COORDINATOR_HEADERS
        )
        validate_error(replay, ERR_INVALID_STATE_TRANSITION, 409)
        assert read_report(api, report["id"])["status"] == "REJECTED"


class TestPlanAndReportUniqueness:
    """Two different uniqueness scopes, each with its own code."""

    def test_a_second_non_terminal_plan_on_the_same_placement_is_refused(self, api):
        """
        The incumbent plan is DRAFT, which is non-terminal, so a second plan is
        refused even with a different date and receiving program.

        PRD: "Only one non-terminal plan — `DRAFT` or `ACTIVE` — may exist per placement, and a second is refused with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/errors/second_live_transition_plan_on_the_same_placement_rejected
        """
        world = build_active_day_placement(api)
        placement_id = world["placement"]["id"]
        make_draft_plan(api, placement_id, **dict(BRIDGE_PLAN))

        response = api.create_transition_plan(
            f.transition_plan_payload(
                placement_id,
                target_return_date="2027-06-01",
                receiving_program="Eastgate Resource Program",
            ),
            COORDINATOR_HEADERS,
        )
        validate_error(response, ERR_DUPLICATE_RESOURCE, 409)

        rows, meta = list_rows(
            api.list_transition_plans(
                COORDINATOR_HEADERS, {"placement_id": placement_id}
            )
        )
        assert meta["total_count"] == 1
        assert rows[0]["target_return_date"] == BRIDGE_PLAN["target_return_date"]
        assert rows[0]["receiving_program"] == BRIDGE_PLAN["receiving_program"]

    def test_a_second_report_for_the_same_quarter_is_refused_but_the_next_is_not(
        self, api
    ):
        """
        The uniqueness key is the placement, fiscal year and quarter together, so
        the same quarter collides while the following quarter is admitted.

        PRD: "Only one report may exist per `placement_id`, `fiscal_year` and `quarter` triple among reports in `SUBMITTED` or `ACCEPTED` status, and a duplicate — or a `quarter` outside 1 through 4 — is refused with `ERR_DUPLICATE_PROGRESS_PERIOD`."

        Design: Corner/errors/second_progress_report_for_the_same_quarter_rejected
        """
        world = build_active_day_placement(api)
        placement_id = world["placement"]["id"]
        first = submit_progress_report(api, placement_id, 2, **dict(FLOOR_Q1))
        accept_progress_report(api, first["id"])

        stronger = dict(
            goals_total=10,
            goals_met=9,
            goals_regressed=0,
            benchmark_scaled_score=80,
            attendance_rate_pct=99,
        )
        duplicate = api.create_progress_report(
            f.progress_report_payload(placement_id, 2, **stronger), COORDINATOR_HEADERS
        )
        validate_error(duplicate, ERR_DUPLICATE_PROGRESS_PERIOD, 409)

        third = validate_success(
            api.create_progress_report(
                f.progress_report_payload(placement_id, 3, **stronger),
                COORDINATOR_HEADERS,
            ),
            201,
        )
        assert third["quarter"] == 3
        assert third["status"] == "SUBMITTED"

        _, meta = list_rows(
            api.list_progress_reports(
                COORDINATOR_HEADERS, {"placement_id": placement_id}
            )
        )
        assert meta["total_count"] == 2
