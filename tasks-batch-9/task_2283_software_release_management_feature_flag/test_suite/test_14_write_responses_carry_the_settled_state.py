"""Nothing converges later: the writing response already carries the settled row."""

from test_helpers import (
    ChangeState,
    ReleasePhase,
    RiskClass,
    assert_envelope_shape,
    validate_success,
)
from test_helpers.fixtures import (
    read_change,
    read_release,
    read_train,
    scenario_release_ready_to_cut_with_deferrable_change,
)
from test_helpers.test_users import RELEASE_MANAGER


class TestCutResponseIsAlreadyFinal:
    """The cut recomputes, defers and pins before it answers."""

    def test_the_cut_body_reports_the_deferral_pinned_score_and_ledger(self, api):
        """"every change request on the release whose ``state`` is ``DRAFT``,
        ``RISK_CLASSIFIED`` or ``CAB_REVIEW`` moves to ``state`` ``DEFERRED``", a
        deferral that "is pinned to run *before* the attested score is computed, so
        those changes are counted in their post-deferral state", after which
        "``readiness_score_attested`` is computed and pinned; it is never recomputed
        for the remainder of the release's life".

        Design: Corner/consistency_model/cut_response_body_carries_the_recomputed_release_fields
        """
        built = scenario_release_ready_to_cut_with_deferrable_change(api)
        release_id = built["release"]["id"]
        assert built["change_medium"]["risk_score_preliminary"] == 33
        assert built["change_medium"]["risk_class"] == RiskClass.MEDIUM

        response = api.cut_release(release_id, {}, RELEASE_MANAGER)
        cut = validate_success(response, 200)
        read_back = read_release(api, release_id)

        assert_envelope_shape(response.json(), "object")
        assert cut["phase"] == ReleasePhase.CUT
        # One in-flight change is deferred by the cut, costing six points.
        assert cut["readiness_score_attested"] == 94
        assert cut["committed_change_count"] == 1
        assert cut["risk_budget_consumed_points"] == 9
        assert read_change(api, built["change_medium"]["id"])["state"] == (
            ChangeState.DEFERRED
        )
        assert read_change(api, built["change_low"]["id"])["state"] == ChangeState.MERGED
        assert read_back["phase"] == cut["phase"]
        assert read_back["readiness_score_attested"] == cut["readiness_score_attested"]
        assert read_back["readiness_score_projected"] == cut["readiness_score_projected"]
        assert read_back["version"] == cut["version"]
        assert read_train(api, built["train"]["id"])["open_release_count"] == 0
