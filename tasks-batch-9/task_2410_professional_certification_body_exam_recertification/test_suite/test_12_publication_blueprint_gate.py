"""Publication is decided by an item's statistics, an entity the call never names."""

import pytest

from test_helpers import ApiErrorId
from test_helpers import assertions as ax
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success

PRETEST_BATCH = {"is_pretest": True, "response_count": 40, "correct_count": 24,
                 "upper_n": 10, "upper_correct": 9, "lower_n": 10, "lower_correct": 3}
FLAGGING_BATCH = {"is_pretest": False, "response_count": 60, "correct_count": 30,
                  "upper_n": 20, "upper_correct": 5, "lower_n": 20, "lower_correct": 15}
REDEEMING_BATCH = {"is_pretest": False, "response_count": 60, "correct_count": 30,
                   "upper_n": 30, "upper_correct": 30, "lower_n": 30, "lower_correct": 0}
PUBLISH_NOTE = {"publication_note": "publish the adopted form"}


def _adopted_form_over_a_complete_blueprint(api):
    """A single-position form with its cut score adopted, over a programme whose one
    domain is covered by one operational item.
    """
    program = fx.active_program(api)
    item = fx.operational_item(api, program["id"], batch=f.response_batch_payload(**PRETEST_BATCH))
    form = fx.assembled_form(api, program["id"], [item["id"]], form_code="CPX-F1")
    rated = fx.submit_ratings(api, form["id"], [0.6])
    adopted = fx.cut_score_form(api, form["id"], rated["version"])
    return program, item, adopted


class TestPublicationGateFollowsTheBlueprint:
    """One item's discrimination opens and closes the publication gate."""

    def test_operational_batch_flags_the_item_on_pooled_totals(self, api):
        """The programme pools pretest with operational evidence, so the second batch
        drags discrimination below the threshold and the item is flagged.

        PRD §3.3: "Under the `POOLED` basis, each working total is the sum of the
        corresponding pretest and operational accumulators".

        PRD §3.3: "Otherwise, if `discrimination_index` is strictly less than the
        program's `min_discrimination`, `flag_reason` becomes `LOW_DISCRIMINATION`."

        Design: Difficulty/cross_entity_state_dependency/form_publication_gated_on_program_blueprint_posture_toggled_by_item_flagging
        """
        program, item, _form = _adopted_form_over_a_complete_blueprint(api)
        assert program["psychometric_stat_basis"] == "POOLED"
        assert item["status"] == "OPERATIONAL"

        flagged = fx.ingest_batch(api, item["id"], **FLAGGING_BATCH)

        assert float(flagged["p_value"]) == pytest.approx(0.5400, abs=1e-4)
        assert float(flagged["discrimination_index"]) == pytest.approx(-0.1333, abs=1e-4)
        assert flagged["flag_reason"] == "LOW_DISCRIMINATION"
        assert flagged["status"] == "FLAGGED"
        ax.assert_item_stat_precision(flagged["p_value"])
        ax.assert_item_stat_precision(flagged["discrimination_index"])

    def test_flagging_strips_the_programme_of_its_only_covered_domain(self, api):
        """The item leaving the operational pool decrements the count and recomputes the
        posture, with no request naming the programme at all.

        PRD §3.3: "An `OPERATIONAL → FLAGGED` move decreases `operational_item_count`
        by 1 and recomputes the same two fields, which can flip the program `COMPLETE
        → DEFICIENT`".

        Design: Difficulty/cross_entity_state_dependency/form_publication_gated_on_program_blueprint_posture_toggled_by_item_flagging
        """
        program, item, _form = _adopted_form_over_a_complete_blueprint(api)
        before = fx.read_program(api, program["id"])
        assert before["operational_item_count"] == 1
        assert before["deficient_domain_codes"] == []
        assert before["blueprint_posture"] == "COMPLETE"

        fx.ingest_batch(api, item["id"], **FLAGGING_BATCH)

        after = fx.read_program(api, program["id"])
        assert after["operational_item_count"] == 0
        assert after["deficient_domain_codes"] == ["D1"]
        assert after["blueprint_posture"] == "DEFICIENT"
        ax.assert_blueprint_posture_agrees_with_counts(after)

    def test_publication_is_refused_while_the_blueprint_is_deficient(self, api):
        """The form is in the right state and its cut score is adopted, and it is still
        refused because of the programme's posture.

        PRD §3.5: "The program's `blueprint_posture` must be `COMPLETE`, or
        `ERR_BLUEPRINT_DEFICIENT`."

        Design: Difficulty/cross_entity_state_dependency/form_publication_gated_on_program_blueprint_posture_toggled_by_item_flagging
        """
        _program, item, form = _adopted_form_over_a_complete_blueprint(api)
        assert form["status"] == "CUT_SCORE_SET"
        fx.ingest_batch(api, item["id"], **FLAGGING_BATCH)

        refused = api.publish_form(form["id"], f.publish_form_payload(**PUBLISH_NOTE),
                                   fx.PROGRAM_ADMIN)

        validate_error(refused, ApiErrorId.ERR_BLUEPRINT_DEFICIENT.value, 422)
        assert fx.read_form(api, form["id"])["status"] == "CUT_SCORE_SET"

    def test_a_redeeming_batch_unflags_the_item_and_restores_the_posture(self, api):
        """A third batch lifts pooled discrimination back over the threshold, which
        returns the item to the operational pool and the programme to COMPLETE.

        PRD §3.3: "Once operational, the item enters the monitoring cycle: a later
        ingest yielding a non-null `flag_reason` with sufficient data moves it
        `OPERATIONAL → FLAGGED`, and a further ingest yielding a null `flag_reason`
        with sufficient data moves it back `FLAGGED → OPERATIONAL`."

        PRD §3.3: "A `PRETEST → OPERATIONAL` or `FLAGGED → OPERATIONAL` move increases
        the program's `operational_item_count` by 1 and then recomputes
        `deficient_domain_codes` and `blueprint_posture`, which can flip the program
        `DEFICIENT → COMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/form_publication_gated_on_program_blueprint_posture_toggled_by_item_flagging
        """
        program, item, _form = _adopted_form_over_a_complete_blueprint(api)
        fx.ingest_batch(api, item["id"], **FLAGGING_BATCH)

        restored = fx.ingest_batch(api, item["id"], **REDEEMING_BATCH)

        assert float(restored["p_value"]) == pytest.approx(0.5250, abs=1e-4)
        assert float(restored["discrimination_index"]) == pytest.approx(0.4333, abs=1e-4)
        assert restored["flag_reason"] is None
        assert restored["status"] == "OPERATIONAL"
        assert restored["retirement_reason"] is None

        after = fx.read_program(api, program["id"])
        assert after["operational_item_count"] == 1
        assert after["blueprint_posture"] == "COMPLETE"

    def test_the_identical_publish_call_succeeds_once_the_posture_returns(self, api):
        """The same body that was refused now publishes, and publication leaves the
        adopted cut score exactly as the panel set it.

        PRD §3.5: "Publication is the `ProgramAdmin`'s gate, optionally annotated with
        a `publication_note`, and it moves the form `CUT_SCORE_SET → PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/form_publication_gated_on_program_blueprint_posture_toggled_by_item_flagging
        """
        _program, item, form = _adopted_form_over_a_complete_blueprint(api)
        assert form["raw_cut_score"] == 0
        body = f.publish_form_payload(**PUBLISH_NOTE)
        fx.ingest_batch(api, item["id"], **FLAGGING_BATCH)
        validate_error(api.publish_form(form["id"], body, fx.PROGRAM_ADMIN),
                       ApiErrorId.ERR_BLUEPRINT_DEFICIENT.value, 422)
        fx.ingest_batch(api, item["id"], **REDEEMING_BATCH)

        published = validate_success(api.publish_form(form["id"], body, fx.PROGRAM_ADMIN), 200)

        assert published["status"] == "PUBLISHED"
        assert published["raw_cut_score"] == 0
        ax.assert_exam_form(published)
