"""Corner: endpoints — response envelope shape, FK reverse-reachability."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    ApiErrorId,
    create_category, create_risk,
    create_assessed_risk, create_residual_assessed_risk,
    create_residual_assessment,
    create_active_control, create_active_mapping,
    create_active_kri, observe_kri,
    create_in_progress_plan, add_action,
    make_risk_manager_headers, make_internal_auditor_headers,
    USER_RISK_MANAGER, USER_INTERNAL_AUDITOR,
)


class TestErrorEnvelopeShape:
    def test_error_envelope_carries_required_fields(self):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type: "error"`, `data.error_id`,
        `data.message`, and `meta.api_request_id` / `meta.api_request_timestamp`.
        PRD §2.8 #3: "required fields present, types valid...
        (`ERR_INVALID_REQUEST`)".

        Design: Corner/endpoints/response_envelope_error_shape
        """
        res = api_client.create_category(
            {}, make_risk_manager_headers(USER_RISK_MANAGER),
        )
        assert res.status_code == 400
        body = res.json()
        assert body.get("response_type") == "error"
        assert "meta" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert isinstance(body["meta"].get("api_request_timestamp"), str)
        assert "data" in body
        assert body["data"].get("error_id") == "ERR_INVALID_REQUEST"
        assert isinstance(body["data"].get("message"), str)
        assert len(body["data"]["message"].strip()) > 0


class TestFkReverseReachability:
    """Corner: fk_reverse_reachability_nested_lists — children discoverable
    under each parent endpoint."""

    def _build_full(self):
        """category; risk ASSESSED (INHERENT+RESIDUAL); control ACTIVE with
        one ACTIVE mapping; KRI ACTIVE with one observation; plan IN_PROGRESS
        with one action."""
        cat = create_category(name="FK")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=2, impact=2,
            treatment_budget_cents=100_000,
        )
        ctl = create_active_control(name="C", effectiveness_pct=0.5)
        m = create_active_mapping(risk["id"], ctl["id"], coverage_weight=0.5)
        kri = create_active_kri(
            cat["id"], name="K", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        observe_kri(kri["id"], 10, "2026-08-01T00:00:00Z")
        create_residual_assessment(risk["id"])
        plan = create_in_progress_plan(risk["id"], budget_cents=50_000)
        a1 = add_action(plan["id"], "a1")
        return {
            "cat": cat, "risk": risk, "ctl": ctl, "m": m,
            "kri": kri, "plan": plan, "a1": a1,
        }

    def test_children_discoverable_under_each_parent(self):
        """PRD §3.2: "A risk's treatment plans, control mappings, and
        tolerance breaches can each be listed as collections of the risk."
        PRD §3.3: "The mappings referencing a control can be listed from the
        control side as well."
        PRD §3.5: "A plan's action list can be browsed independently."
        PRD §3.6: "the indicator's observations are listed chronologically by
        `observed_at`."

        Design: Corner/endpoints/fk_reverse_reachability_nested_lists
        """
        ctx = self._build_full()
        auditor = make_internal_auditor_headers(USER_INTERNAL_AUDITOR)
        # Assessments under risk: INHERENT + RESIDUAL = 2
        assessments = validate_success(
            api_client.list_assessments(ctx["risk"]["id"], auditor), 200,
        )
        assert len(assessments) == 2
        assert {a["kind"] for a in assessments} == {"INHERENT", "RESIDUAL"}
        # Mappings under risk: 1
        rm_mappings = validate_success(
            api_client.list_risk_control_mappings(ctx["risk"]["id"], auditor), 200,
        )
        assert len(rm_mappings) == 1
        assert rm_mappings[0]["id"] == ctx["m"]["id"]
        # Mappings under control: 1, same id
        cm_mappings = validate_success(
            api_client.list_control_mappings(ctx["ctl"]["id"], auditor), 200,
        )
        assert len(cm_mappings) == 1
        assert cm_mappings[0]["id"] == ctx["m"]["id"]
        # Observations under KRI: 1
        observations = validate_success(
            api_client.list_kri_observations(ctx["kri"]["id"], auditor), 200,
        )
        assert len(observations) == 1
        # Actions under plan: 1
        actions = validate_success(
            api_client.list_treatment_actions(ctx["plan"]["id"], auditor), 200,
        )
        assert len(actions) == 1
        assert actions[0]["id"] == ctx["a1"]["id"]
        # Risks under category
        risks = validate_success(
            api_client.list_category_risks(ctx["cat"]["id"], auditor), 200,
        )
        assert any(r["id"] == ctx["risk"]["id"] for r in risks)
