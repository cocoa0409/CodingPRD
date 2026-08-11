"""Hydrographic surveys, the kind gate, begin-dredging gates, the deficiency
loop, supersede chains, and survey-level segregation/OCC (PRD §2.7, §2.8,
§2.9, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, SURVEYOR_ID,
    create_survey_payload,
    set_clock, create_project, add_reach,
    submit_survey, accept_survey, reject_survey, get_reach,
    setup_active_project, setup_pre_surveyed_reach, setup_dredging_reach,
    make_owner_headers,
)


class TestSurveyKindGate:
    def test_survey_post_dredge_on_pending_reach_rejected(self, api,
                                                          surveyor_headers):
        """PRD §3.4: "A `PRE_DREDGE` survey is accepted only for a reach in
        `PENDING` or `PRE_SURVEYED`; a `POST_DREDGE` survey only for a reach in
        `DREDGING`. Any other pairing fails at creation with
        `ERR_SURVEY_KIND_MISMATCH` (HTTP 409)."

        Design: Corner/validations/survey_post_dredge_on_pending_reach_rejected
        """
        project = create_project(name="P-SKM")
        reach = add_reach(project["id"])
        res = api.create_survey(
            create_survey_payload(reach["id"], kind="POST_DREDGE",
                                  measured_volume_cy=39000,
                                  min_sounding_depth_ft=25.0),
            surveyor_headers,
        )
        validate_error(res, ApiErrorId.ERR_SURVEY_KIND_MISMATCH,
                       expected_status=409)


class TestBeginDredgingGates:
    def test_begin_dredging_from_pending_rejected(self, api, contractor_headers):
        """PRD §3.4: "beginning dredging moves a reach from `PRE_SURVEYED` to
        `DREDGING`"; PRD §2.9: "the target must be in a valid from-state for the
        requested transition, with terminal states locked down:
        `ERR_INVALID_STATE`, `ERR_PROJECT_NOT_ACTIVE`, `ERR_REACH_NOT_DREDGABLE`,
        `ERR_EVENT_NOT_COMPLETED`, `ERR_FINAL_ACCEPTANCE_INCOMPLETE`, and
        `ERR_SURVEY_KIND_MISMATCH` (all HTTP 409)."

        Design: Corner/state_machines/begin_dredging_from_pending_rejected
        """
        # ACTIVE project with reach still PENDING (no survey accepted).
        ctx = setup_active_project()
        res = api.begin_dredging(ctx["reach"]["id"], contractor_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        reach_after = get_reach(ctx["reach"]["id"])
        assert reach_after["status"] == "PENDING"

    def test_begin_dredging_on_planned_project_rejected(self, api,
                                                        contractor_headers):
        """PRD §3.4: "beginning dredging moves a reach from `PRE_SURVEYED` to
        `DREDGING` and is gated on the project being `ACTIVE` — else
        `ERR_PROJECT_NOT_ACTIVE` (HTTP 409) — and on an `APPROVED` plan existing
        for the project, else `ERR_PLAN_NOT_APPROVED` (HTTP 409)."

        Design: Corner/state_machines/begin_dredging_on_planned_project_rejected
        """
        # PLANNED project, plan APPROVED, reach PRE_SURVEYED.
        ctx = setup_pre_surveyed_reach(activate=False)
        res = api.begin_dredging(ctx["reach"]["id"], contractor_headers)
        validate_error(res, ApiErrorId.ERR_PROJECT_NOT_ACTIVE,
                       expected_status=409)
        reach_after = get_reach(ctx["reach"]["id"])
        assert reach_after["status"] == "PRE_SURVEYED"


class TestReachDeficiencyLoop:
    def _two_deficient_accepts(self):
        """Reach DREDGING; two POST_DREDGE surveys that fall short of the 25.0 ft
        requirement are accepted and loop the reach back to DREDGING."""
        ctx = setup_dredging_reach()
        s1 = submit_survey(ctx["reach"]["id"], "POST_DREDGE", 39500, 24.0)
        accept_survey(ctx["reach"]["id"], s1["id"])
        reach_after_1 = get_reach(ctx["reach"]["id"])
        s2 = submit_survey(ctx["reach"]["id"], "POST_DREDGE", 39200, 24.5,
                           supersedes_survey_id=s1["id"])
        accept_survey(ctx["reach"]["id"], s2["id"])
        reach_after_2 = get_reach(ctx["reach"]["id"])
        return ctx, s1, s2, reach_after_1, reach_after_2

    def test_reach_deficiency_loops_back_to_dredging(self, api):
        """PRD §3.4: "For a post-dredge acceptance, the depth test decides: when
        the survey's `min_sounding_depth_ft` is at least the reach's
        `required_depth_ft` — equality passes — the reach transitions to
        `ACCEPTED`, its terminal state; when the sounding falls short, the reach
        returns to `DREDGING`, the deficiency loop that lets the contractor
        re-dredge and the survey party submit a fresh post-dredge survey."

        Design: Difficulty/non_linear_state_machine/reach_deficiency_cycle_twice_then_accepted
        """
        ctx, s1, s2, reach_after_1, reach_after_2 = self._two_deficient_accepts()
        # 24.0 < 25.0 and 24.5 < 25.0: each deficient acceptance loops back.
        assert reach_after_1["status"] == "DREDGING"
        assert reach_after_2["status"] == "DREDGING"

    def test_reach_depth_equality_acceptance_and_removed_quantity(self, api,
                                                                  owner_headers):
        """PRD §3.4: "when the survey's `min_sounding_depth_ft` is at least the
        reach's `required_depth_ft` — equality passes — the reach transitions to
        `ACCEPTED`, its terminal state".
        PRD §3.4: "it equals the latest accepted pre-dredge volume minus the
        latest accepted post-dredge volume, floored at zero, where "latest" of
        each kind follows acceptance order (`created_at` ascending) and
        superseded surveys are excluded."

        Design: Difficulty/non_linear_state_machine/reach_deficiency_cycle_twice_then_accepted
        """
        ctx, s1, s2, _, _ = self._two_deficient_accepts()
        # Third survey at exactly the required 25.0 ft passes the depth gate.
        s3 = submit_survey(ctx["reach"]["id"], "POST_DREDGE", 39000, 25.0,
                           supersedes_survey_id=s2["id"])
        accept_survey(ctx["reach"]["id"], s3["id"])
        reach_after_3 = get_reach(ctx["reach"]["id"])
        assert reach_after_3["status"] == "ACCEPTED"
        # max(0, 40000 - 39000) = 1000.00
        assert reach_after_3["removed_in_place_cy"] == pytest.approx(1000.00,
                                                                     abs=1e-4)
        s1_after = validate_success(api.get_survey(s1["id"], owner_headers))
        s2_after = validate_success(api.get_survey(s2["id"], owner_headers))
        assert s1_after["status"] == "SUPERSEDED"
        assert s2_after["status"] == "SUPERSEDED"


class TestSurveyAcceptanceControls:
    def test_occ_stale_reach_version_on_survey_accept(self, api, owner_headers):
        """PRD §2.7: "the request must carry `expected_reach_version` matching
        the Reach's current `version`, and a mismatch is rejected with
        `ERR_STALE_REACH_VERSION` (HTTP 412)."
        PRD §3.4: "For a pre-dredge acceptance on a reach already `PRE_SURVEYED`,
        the previously accepted pre-dredge survey becomes `SUPERSEDED` while the
        reach stays `PRE_SURVEYED`."

        Design: Corner/complexity_layers/occ_stale_reach_version_on_survey_accept
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-OCC2")
        reach = add_reach(project["id"])
        s1 = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
        stale_version = get_reach(reach["id"])["version"]
        accept_survey(reach["id"], s1["id"])  # bumps Reach.version
        s2 = submit_survey(reach["id"], "PRE_DREDGE", 40500, 18.5,
                           supersedes_survey_id=s1["id"])
        res = api.accept_survey(
            s2["id"], {"expected_reach_version": stale_version}, owner_headers
        )
        validate_error(res, ApiErrorId.ERR_STALE_REACH_VERSION,
                       expected_status=412)
        # Retry with the fresh version: supersede cascade fires.
        fresh_version = get_reach(reach["id"])["version"]
        accepted = validate_success(
            api.accept_survey(s2["id"],
                              {"expected_reach_version": fresh_version},
                              owner_headers),
            200,
        )
        assert accepted["status"] == "ACCEPTED"
        s1_after = validate_success(api.get_survey(s1["id"], owner_headers))
        assert s1_after["status"] == "SUPERSEDED"
        reach_after = get_reach(reach["id"])
        assert reach_after["status"] == "PRE_SURVEYED"
        assert reach_after["removed_in_place_cy"] == pytest.approx(0, abs=1e-4)

    def test_segregation_survey_acceptor_is_submitter_rejected(
        self, api, owner_headers
    ):
        """PRD §2.8: "Survey acceptance and survey rejection compare against the
        survey's `submitted_by_user_id`." — an exact match "is rejected with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)".

        Design: Corner/endpoints/segregation_survey_acceptor_is_submitter_rejected
        """
        project = create_project(name="P-SOD1")
        reach = add_reach(project["id"])
        survey = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
        reach_version = get_reach(reach["id"])["version"]
        # OwnerEngineer role, but carrying the submitter's id (surv-1).
        res = api.accept_survey(
            survey["id"], {"expected_reach_version": reach_version},
            make_owner_headers(SURVEYOR_ID),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
                       expected_status=403)
        survey_after = validate_success(api.get_survey(survey["id"],
                                                       owner_headers))
        assert survey_after["status"] == "SUBMITTED"

    def test_state_beats_segregation_on_survey_accept(self, api):
        """PRD §2.9: "When several checks could reject the same request, the
        server evaluates them in the following fixed class order, and the first
        failing class produces the response — earlier failures mask later ones
        rather than accumulating"; the state-gate class ("6. **State gates** —
        the target must be in a valid from-state for the requested transition,
        with terminal states locked down: `ERR_INVALID_STATE`") precedes
        "8. **Segregation of duties** — `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)
        per §2.8."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_survey_accept
        """
        project = create_project(name="P-P1")
        reach = add_reach(project["id"])
        survey = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
        reject_survey(survey["id"])  # survey now REJECTED (terminal)
        reach_version = get_reach(reach["id"])["version"]
        # Both fail: wrong from-state (class 6) AND acceptor == submitter
        # (class 8). The state gate must be reported.
        res = api.accept_survey(
            survey["id"], {"expected_reach_version": reach_version},
            make_owner_headers(SURVEYOR_ID),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rejected_survey_remains_terminal_after_masked_accept(self, api,
                                                                  owner_headers):
        """PRD §3.4: "Both `REJECTED` and `SUPERSEDED` are terminal, as is
        `ACCEPTED`."; PRD §2.9: "the target must be in a valid from-state for
        the requested transition, with terminal states locked down:
        `ERR_INVALID_STATE`"; PRD §2.9: "the first failing class produces the
        response — earlier failures mask later ones rather than accumulating".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_segregation_on_survey_accept
        """
        project = create_project(name="P-P1B")
        reach = add_reach(project["id"])
        survey = submit_survey(reach["id"], "PRE_DREDGE", 40000, 18.5)
        reject_survey(survey["id"])
        reach_version = get_reach(reach["id"])["version"]
        res = api.accept_survey(
            survey["id"], {"expected_reach_version": reach_version},
            make_owner_headers(SURVEYOR_ID),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        # The masked request changed nothing: survey stays REJECTED, reach
        # stays PENDING.
        survey_after = validate_success(api.get_survey(survey["id"],
                                                       owner_headers))
        assert survey_after["status"] == "REJECTED"
        reach_after = get_reach(reach["id"])
        assert reach_after["status"] == "PENDING"
