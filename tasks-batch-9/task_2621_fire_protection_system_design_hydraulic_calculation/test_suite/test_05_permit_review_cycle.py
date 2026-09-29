"""The permit review loop and the two downstream gates on lodging a package."""
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.assertions import assert_money, assert_posture, assert_sheet_counters
from test_helpers.factories import build_submittal_payload
from test_helpers.fixtures import (
    begin_review,
    complete_review,
    raise_comment,
    read_calculation,
    read_comment,
    read_project,
    read_shop_drawing,
    read_submittal,
    respond_to_comment,
    build_under_review_stage,
    build_qc_passed_stage,
    create_shop_drawing,
    open_clearance,
    record_clearance,
    seal,
)
from test_helpers.test_users import make_design_engineer_headers

MINOR_COMMENT = dict(
    code_section="NFPA 13 23.4.4.7",
    severity="MINOR",
    description="Label the hose allowance on the summary sheet",
)
RESPONSE_NOTE = "Hose allowance annotated on sheet FP-101"


def _commented(client):
    """One MINOR comment raised and the pass closed out, so the package is back
    with the designer."""
    ctx = build_under_review_stage(client)
    ctx["comment"] = raise_comment(
        client,
        ctx["submittal_id"],
        ctx["reviewer_id"],
        assigned_engineer_id=ctx["lead_id"],
        **MINOR_COMMENT,
    )
    ctx["submittal"] = complete_review(client, ctx["submittal_id"], ctx["reviewer_id"])
    return ctx


class TestOneReviewCycleAbsorbsACommentRound:
    def test_01_a_minor_comment_returns_the_package_to_the_designer(self, client):
        """With `open_comment_count` of 1 or more, the package moves
        `UNDER_REVIEW → COMMENTS_ISSUED` and returns to the designer for correction.

        Design: Difficulty/non_linear_state_machine/submittal_comment_response_review_cycle_keeps_cycle_number_at_one
        """
        ctx = _commented(client)
        submittal = ctx["submittal"]
        assert submittal["state"] == "COMMENTS_ISSUED"
        assert submittal["cycle_number"] == 1
        assert submittal["open_comment_count"] == 1
        assert submittal["major_comment_count"] == 0
        assert submittal["reviewed_by_ahj_reviewer_id"] == ctx["reviewer_id"]

        # A MINOR comment never gates the project, so the design stays writable.
        project = read_project(client, ctx["project_id"])
        assert project["status"] == "PERMIT_REVIEW"
        assert project["open_major_comment_count"] == 0
        assert_posture(project, "OPEN")

    def test_02_answering_bubbles_the_package_up_without_clearing_the_count(self, client):
        """When no comment of the package remains in `OPEN`, the package bubbles up
        `COMMENTS_ISSUED → RESPONSE_COMPLETE` and is ready for the authority to reopen
        review.

        Design: Difficulty/non_linear_state_machine/submittal_comment_response_review_cycle_keeps_cycle_number_at_one
        """
        ctx = _commented(client)
        answered = respond_to_comment(
            client, ctx["comment"]["id"], ctx["lead_id"], response_note=RESPONSE_NOTE
        )
        assert answered["state"] == "RESPONDED"
        assert answered["response_note"] == RESPONSE_NOTE
        assert answered["disposition"] is None

        submittal = read_submittal(client, ctx["submittal_id"])
        assert submittal["state"] == "RESPONSE_COMPLETE"
        assert submittal["cycle_number"] == 1
        # Answering does not reduce the count: a RESPONDED comment is still carried.
        assert submittal["open_comment_count"] == 1
        assert submittal["major_comment_count"] == 0

    def test_03_reopening_review_stays_on_cycle_one_and_mints_no_new_package(self, client):
        """Opening review moves the package `SUBMITTED → UNDER_REVIEW` on a first pass, or
        `RESPONSE_COMPLETE → UNDER_REVIEW` on any later pass, and records
        `reviewed_by_ahj_reviewer_id` from the acting examiner.

        Design: Difficulty/non_linear_state_machine/submittal_comment_response_review_cycle_keeps_cycle_number_at_one
        """
        ctx = _commented(client)
        respond_to_comment(
            client, ctx["comment"]["id"], ctx["lead_id"], response_note=RESPONSE_NOTE
        )
        reopened = begin_review(client, ctx["submittal_id"], ctx["reviewer_id"])
        assert reopened["state"] == "UNDER_REVIEW"
        assert reopened["cycle_number"] == 1
        assert_money(reopened["review_fee_usd"], 0.00)
        assert reopened["supersedes_submittal_id"] is None

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "PERMIT_REVIEW"
        assert project["submittal_cycle_count"] == 1
        assert_money(project["review_fee_balance_usd"], 0.00)
        assert project["open_major_comment_count"] == 0
        assert_posture(project, "OPEN")

        listed, meta = validate_paginated(
            client.list_submittals(
                make_design_engineer_headers(ctx["lead_id"]),
                params={"project_id": ctx["project_id"]},
            )
        )
        assert meta["total_count"] == 1, "the comment round must not mint a second package"
        assert [row["id"] for row in listed] == [ctx["submittal_id"]]

        # The sealed design and its coordinated sheet are untouched by the loop.
        assert read_calculation(client, ctx["calculation_id"])["state"] == "SEALED"
        assert read_comment(client, ctx["comment"]["id"])["state"] == "RESPONDED"
        assert_sheet_counters(read_shop_drawing(client, ctx["sheet_id"]), "COORDINATED", 3)
        assert read_project(client, ctx["project_id"])["sealed_calculation_count"] == 1


def _lodge(client, ctx, calculation_ids=None):
    """POST /submittals with a freshly read version pin, returning the raw response."""
    payload = build_submittal_payload(
        project_id=ctx["project_id"],
        included_calculation_ids=calculation_ids or [ctx["calculation_id"]],
        expected_project_version=read_project(client, ctx["project_id"])["version"],
    )
    return client.create_submittal(payload, make_design_engineer_headers(ctx["lead_id"]))


class TestSubmittalGateWalksTheDownstreamEntities:
    def test_04_with_no_sheet_at_all_the_unsealed_calculation_answers_first(self, client):
        """Every named calculation must belong to this project and be in state `SEALED`, or
        the lodgement is refused with `ERR_CALCULATION_NOT_SEALED`.

        Design: Difficulty/cross_entity_state_dependency/submittal_gate_walks_from_unsealed_calculation_to_uncoordinated_sheet_to_success
        """
        ctx = build_qc_passed_stage(client)
        assert read_calculation(client, ctx["calculation_id"])["state"] == "QC_PASSED"

        # With no sheet on the project the drawing rule is vacuous, so the seal rule
        # at the earlier priority has to answer this attempt.
        refused = _lodge(client, ctx)
        validate_error(refused, "ERR_CALCULATION_NOT_SEALED", expected_status=409)

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "DESIGN"
        assert project["submittal_cycle_count"] == 0
        assert project["sealed_calculation_count"] == 0

    def test_05_a_sheet_two_trades_of_three_cleared_answers_the_second_attempt(self, client):
        """every shop drawing whose `hydraulic_calculation_id` is one of those calculations
        must be in `COORDINATED` or `ISSUED`, or the lodgement is refused with
        `ERR_DRAWING_NOT_COORDINATED`.

        Design: Difficulty/cross_entity_state_dependency/submittal_gate_walks_from_unsealed_calculation_to_uncoordinated_sheet_to_success
        """
        ctx = build_qc_passed_stage(client)
        _lodge(client, ctx)
        seal(client, ctx["calculation_id"], ctx["lead_id"])

        sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])
        for trade in ("STRUCTURAL", "MECHANICAL"):
            item = open_clearance(client, sheet["id"], trade)
            record_clearance(client, item["id"], ctx["lead_id"])
        assert_sheet_counters(
            read_shop_drawing(client, sheet["id"]), "IN_COORDINATION", 2
        )

        refused = _lodge(client, ctx)
        validate_error(refused, "ERR_DRAWING_NOT_COORDINATED", expected_status=409)

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "DESIGN"
        assert project["submittal_cycle_count"] == 0
        assert project["sealed_calculation_count"] == 1

    def test_06_the_third_trade_clears_the_gate_and_the_identical_body_is_accepted(
        self, client
    ):
        """A clearance that raises `cleared_trade_count` to `required_trade_count` moves the
        sheet to `COORDINATED`.

        Design: Difficulty/cross_entity_state_dependency/submittal_gate_walks_from_unsealed_calculation_to_uncoordinated_sheet_to_success
        """
        ctx = build_qc_passed_stage(client)
        validate_error(_lodge(client, ctx), "ERR_CALCULATION_NOT_SEALED")
        seal(client, ctx["calculation_id"], ctx["lead_id"])

        sheet = create_shop_drawing(client, ctx["project_id"], ctx["calculation_id"])
        items = {
            trade: open_clearance(client, sheet["id"], trade)
            for trade in ("STRUCTURAL", "MECHANICAL", "LIGHTING")
        }
        for trade in ("STRUCTURAL", "MECHANICAL"):
            record_clearance(client, items[trade]["id"], ctx["lead_id"])
        validate_error(_lodge(client, ctx), "ERR_DRAWING_NOT_COORDINATED")

        record_clearance(client, items["LIGHTING"]["id"], ctx["lead_id"])
        assert_sheet_counters(read_shop_drawing(client, sheet["id"]), "COORDINATED", 3)

        submittal = validate_success(_lodge(client, ctx), expected_status=201)
        assert submittal["state"] == "SUBMITTED"
        assert submittal["cycle_number"] == 1
        assert_money(submittal["review_fee_usd"], 0.00)
        assert submittal["included_calculation_ids"] == [ctx["calculation_id"]]

        project = read_project(client, ctx["project_id"])
        assert project["status"] == "PERMIT_REVIEW"
        assert project["submittal_cycle_count"] == 1
