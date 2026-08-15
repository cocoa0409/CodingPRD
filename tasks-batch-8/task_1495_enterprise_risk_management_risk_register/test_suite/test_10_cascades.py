"""Difficulty: transitive_cascade (KRI red → risk kri_alert → plan URGENT;
mapping retire → residual recompute → breach OPEN). Cross-cutting: OCC stale
version, attest reconciliation, alert ratchet asymmetry, immediate visibility."""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_category, create_risk, create_identified_risk,
    create_assessed_risk, create_residual_assessed_risk,
    create_active_control, create_active_mapping, create_proposed_mapping,
    approve_mapping, retire_mapping,
    create_approved_appetite,
    create_proposed_plan, approve_plan, create_approved_plan,
    create_active_kri, observe_kri, get_kri, advance_clock,
    create_inherent_assessment, create_residual_assessment,
    create_in_progress_plan, add_action, done_action,
    get_risk, get_risk_version, get_plan,
    make_risk_owner_headers, make_risk_manager_headers,
    make_control_owner_headers, make_internal_auditor_headers,
    USER_RISK_OWNER, USER_RISK_MANAGER, USER_RISK_MANAGER_2,
    USER_CONTROL_OWNER, USER_INTERNAL_AUDITOR,
)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / kri_red_observation_alert_priority_chain
# ---------------------------------------------------------------------------

class TestKriRedCascade:
    """Depth-3 cascade: observation → KRI RED_BREACH → risk.kri_alert=true →
    plans ratchet to URGENT."""

    def _build(self):
        """Category CC; risk TREATMENT with APPROVED plan; KRI ACTIVE in same
        category."""
        cat = create_category(name="CC")
        risk = create_residual_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
            treatment_budget_cents=500_000,
        )
        plan = create_approved_plan(risk["id"], budget_cents=100_000)
        api_client.enter_treatment(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        kri = create_active_kri(
            cat["id"], name="Counterparty exposure",
            direction="ABOVE", amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        # The observation below is timestamped after the default logical
        # clock (2026-08-01T00:00:00Z); advance it first so the observation
        # is not rejected as lying in the future (PRD §3.6).
        advance_clock("2026-08-02T00:00:00Z")
        return {"category": cat, "risk": risk, "plan": plan, "kri": kri}

    def test_red_observation_flips_kri_breach_dimension(self):
        """PRD §3.6: "For an `ABOVE` indicator, the result is `RED_BREACH`
        when the observed value is strictly greater than the red threshold".

        Design: Difficulty/transitive_cascade/kri_red_observation_alert_priority_chain
        """
        ctx = self._build()
        observe_kri(ctx["kri"]["id"], 76, "2026-08-01T01:00:00Z")
        kri_after = get_kri(ctx["kri"]["id"])
        assert kri_after["current_breach_status"] == "RED_BREACH"

    def test_red_observation_cascades_to_risk_and_plan(self):
        """PRD §3.6: "A red result fires the alert cascade: every risk in the
        indicator's category whose status is `ASSESSED`, `TREATMENT`,
        `MONITORING`, or `REASSESSMENT` has its `kri_alert` raised to true
        and its `version` incremented by 1, and every treatment plan of those
        risks in `APPROVED`, `IN_PROGRESS`, or `OVERDUE` ratchets its
        `priority` to `URGENT` with its `version` incremented by 1."

        Design: Difficulty/transitive_cascade/kri_red_observation_alert_priority_chain
        """
        ctx = self._build()
        observe_kri(ctx["kri"]["id"], 76, "2026-08-01T01:00:00Z")
        risk_after = get_risk(ctx["risk"]["id"])
        assert risk_after["kri_alert"] is True
        plan_after = get_plan(ctx["plan"]["id"])
        assert plan_after["priority"] == "URGENT"


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / mapping_retire_residual_recompute_breach_chain
# ---------------------------------------------------------------------------

class TestMappingRetireCascade:
    """Mapping retire → risk residual recompute → breach OPEN (depth-2)."""

    def _build(self):
        """Category CT with APPROVED appetite tolerance 10 cap 20.
        Risk inherent 20; mappings M1 (eff 0.8, w 0.5 → 0.40) and
        M2 (eff 0.6, w 0.5 → 0.30) ACTIVE; residual 9 (< 10, no breach)."""
        cat = create_category(name="CT")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
        )
        k1 = create_active_control(name="KC1", effectiveness_pct=0.8)
        k2 = create_active_control(name="KC2", effectiveness_pct=0.6)
        m1 = create_active_mapping(risk["id"], k1["id"], coverage_weight=0.5)
        m2 = create_active_mapping(risk["id"], k2["id"], coverage_weight=0.5)
        # Approve the appetite only after both mappings are ACTIVE: each
        # mapping approval recomputes the residual and runs breach
        # evaluation (PRD §3.3), and with tolerance 10 in place the
        # intermediate residual 12 (M1 alone) would already have opened a
        # breach, defeating this scenario's premise. With no APPROVED
        # statement, "no breach is possible" (PRD §3.4) during approvals.
        create_approved_appetite(
            cat["id"], tolerance_score=10, acceptance_cap_score=20,
            effective_from="2026-01-01T00:00:00Z",
            effective_to="2027-01-01T00:00:00Z",
        )
        create_residual_assessment(risk["id"])
        return {"category": cat, "risk": risk, "m1": m1, "m2": m2}

    def test_no_breach_before_retire(self):
        """PRD §3.4: "the risk breaches appetite the moment its
        `residual_score` is greater than or equal to the statement's
        `tolerance_score`". Residual 9 < tolerance 10 → no breach.

        Design: Difficulty/transitive_cascade/mapping_retire_residual_recompute_breach_chain
        """
        ctx = self._build()
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                ctx["risk"]["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        assert breaches == []

    def test_retire_triggers_recompute_and_breach_open(self):
        """PRD §3.3: "Retiring a mapping, likewise a `RiskManager` decision,
        moves `ACTIVE` → `RETIRED`, decrements `mapped_active_count` by 1,
        increments the control's `version`, and runs the same residual
        recomputation and appetite evaluation on the risk, which may open a
        tolerance breach in `OPEN` status".
        PRD §3.4: "Provided no tolerance breach for the risk already exists
        in `OPEN`, `ACKNOWLEDGED`, or `ACCEPTED` status, the system then
        creates a ToleranceBreach in `OPEN` status... and records the
        offending score in `residual_at_breach`."

        Design: Difficulty/transitive_cascade/mapping_retire_residual_recompute_breach_chain
        """
        ctx = self._build()
        retire_mapping(ctx["m1"]["id"])
        risk_after = get_risk(ctx["risk"]["id"])
        # Only M2 (contribution 0.30) remains: discount 0.30 → ceil(20*0.70) = 14
        assert risk_after["residual_score"] == 14
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                ctx["risk"]["id"], make_risk_manager_headers(USER_RISK_MANAGER),
            ), 200,
        )
        assert len(breaches) == 1
        assert breaches[0]["status"] == "OPEN"
        assert breaches[0]["residual_at_breach"] == 14


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers — OCC
# ---------------------------------------------------------------------------

class TestOccStaleAssessmentVersion:
    def test_stale_assessment_version_rejected(self):
        """PRD §2.7: "If the risk's current `version` differs from
        `expected_risk_version`, the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412); the client must re-read the risk and
        retry against the fresh version."

        Design: Corner/cross_cutting_layers/occ_stale_assessment_version_rejected
        """
        cat = create_category(name="OCC1")
        risk = create_risk(cat["id"])
        api_client.submit_risk(risk["id"], make_risk_owner_headers(USER_RISK_OWNER))
        v_obs = get_risk_version(risk["id"])
        # First INHERENT assessment consumes v_obs and bumps version
        api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 3, "impact": 3,
             "expected_risk_version": v_obs},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        # Second assessment carries the now-stale v_obs
        res = api_client.create_assessment(
            risk["id"],
            {"kind": "RESIDUAL", "expected_risk_version": v_obs},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION.value)


class TestOccStalePlanCreateVersion:
    def test_stale_plan_create_rejected(self):
        """PRD §2.7: "A treatment-plan proposal reads the risk's available
        treatment budget, and a stale observed version may double-allocate
        budget already reserved by a plan created after the client's last
        read."
        PRD §2.7: "If the risk's current `version` differs from
        `expected_risk_version`, the write is rejected with
        `ERR_STALE_VERSION` (HTTP 412)".

        Design: Corner/cross_cutting_layers/occ_stale_plan_create_version_rejected
        """
        cat = create_category(name="OCC2")
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=2, impact=2,
            treatment_budget_cents=500_000,
        )
        v_obs = get_risk_version(risk["id"])
        # First plan create at v_obs succeeds
        res1 = api_client.create_treatment_plan(
            risk["id"],
            {"title": "PA", "budget_cents": 10_000,
             "due_date": "2026-12-31T00:00:00Z",
             "owner_user_id": USER_RISK_OWNER,
             "expected_risk_version": v_obs},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        pa = validate_success(res1, 201)
        assert pa["status"] == "PROPOSED"
        # Second create with the same (now stale) v_obs fails
        res2 = api_client.create_treatment_plan(
            risk["id"],
            {"title": "PB", "budget_cents": 10_000,
             "due_date": "2026-12-31T00:00:00Z",
             "owner_user_id": USER_RISK_OWNER,
             "expected_risk_version": v_obs},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        validate_error(res2, ApiErrorId.ERR_STALE_VERSION.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers — attest reconciliation
# ---------------------------------------------------------------------------

class TestAttestReconcilesResidualAndBreach:
    """Corner: attest_effectiveness_reconciles_residual_and_breach."""

    def _build(self):
        """Category with APPROVED appetite tolerance 10 cap 20.
        Risk inherent 20; control eff 0.8 mapped w 1.0 ACTIVE → contribution
        0.80 → discount 0.80 → residual ceil(20*0.20) = 4 (no breach)."""
        cat = create_category(name="ATR")
        create_approved_appetite(
            cat["id"], tolerance_score=10, acceptance_cap_score=20,
        )
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=4, impact=5,
        )
        ctl = create_active_control(name="C", effectiveness_pct=0.8)
        create_active_mapping(risk["id"], ctl["id"], coverage_weight=1.0)
        create_residual_assessment(risk["id"])
        # Move control to UNDER_REVIEW so attest is the next transition
        api_client.review_control(
            ctl["id"], make_control_owner_headers(USER_CONTROL_OWNER),
        )
        return risk, ctl

    def test_lower_attestation_recomputes_residual_up(self):
        """PRD §3.3: "On attestation, for every `ACTIVE` mapping referencing
        the control whose risk already has an inherent score, the risk's
        residual score is recomputed and appetite-breach evaluation runs".

        Design: Corner/cross_cutting_layers/attest_effectiveness_reconciles_residual_and_breach
        """
        risk, ctl = self._build()
        # Re-attest with lower effectiveness 0.4 → contribution 0.40
        # discount 0.40 → residual ceil(20*0.60) = 12
        api_client.attest_control(
            ctl["id"], {"effectiveness_pct": 0.4},
            make_control_owner_headers(USER_CONTROL_OWNER),
        )
        risk_after = get_risk(risk["id"])
        assert risk_after["residual_score"] == 12

    def test_lower_attestation_opens_breach(self):
        """PRD §3.3: "On attestation... the risk's residual score is
        recomputed and appetite-breach evaluation runs — which may open a
        tolerance breach in `OPEN` status".

        Design: Corner/cross_cutting_layers/attest_effectiveness_reconciles_residual_and_breach
        """
        risk, ctl = self._build()
        api_client.attest_control(
            ctl["id"], {"effectiveness_pct": 0.4},
            make_control_owner_headers(USER_CONTROL_OWNER),
        )
        breaches = validate_success(
            api_client.list_risk_tolerance_breaches(
                risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
            ), 200,
        )
        assert len(breaches) == 1
        assert breaches[0]["status"] == "OPEN"
        assert breaches[0]["residual_at_breach"] == 12


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers — ratchet asymmetry
# ---------------------------------------------------------------------------

class TestKriAlertRatchetAsymmetry:
    """Corner: kri_normal_observation_clears_alert_but_priority_ratchet_stays."""

    def _build(self):
        """Category; risk TREATMENT with APPROVED plan; ACTIVE KRI ABOVE 50/75
        min 0; RED observation applied."""
        cat = create_category(name="RAT")
        risk = create_residual_assessed_risk(
            category_id=cat["id"], likelihood=3, impact=3,
            treatment_budget_cents=500_000,
        )
        plan = create_approved_plan(risk["id"], budget_cents=100_000)
        api_client.enter_treatment(
            risk["id"], make_risk_owner_headers(USER_RISK_OWNER),
        )
        kri = create_active_kri(
            cat["id"], name="K", direction="ABOVE",
            amber_threshold=50, red_threshold=75,
            min_observation_interval_days=0,
        )
        # The observations are timestamped after the default logical clock
        # (2026-08-01T00:00:00Z); advance it first so they are not rejected
        # as lying in the future (PRD §3.6 ERR_OBSERVATION_IN_FUTURE).
        advance_clock("2026-08-02T00:00:00Z")
        # RED first
        observe_kri(kri["id"], 76, "2026-08-01T01:00:00Z")
        return risk, plan, kri

    def test_normal_observation_clears_kri_alert(self):
        """PRD §3.6: "A normal result clears `kri_alert` to false on those
        same risks".

        Design: Corner/cross_cutting_layers/kri_normal_observation_clears_alert_but_priority_ratchet_stays
        """
        risk, _, kri = self._build()
        observe_kri(kri["id"], 10, "2026-08-01T02:00:00Z")
        risk_after = get_risk(risk["id"])
        assert risk_after["kri_alert"] is False

    def test_plan_priority_ratchet_not_lowered(self):
        """PRD §3.6: "but plan priorities are never lowered: the `URGENT`
        ratchet is one-way."

        Design: Corner/cross_cutting_layers/kri_normal_observation_clears_alert_but_priority_ratchet_stays
        """
        _, plan, kri = self._build()
        observe_kri(kri["id"], 10, "2026-08-01T02:00:00Z")
        plan_after = get_plan(plan["id"])
        assert plan_after["priority"] == "URGENT"


# ---------------------------------------------------------------------------
# Corner: consistency_model — immediate visibility
# ---------------------------------------------------------------------------

class TestImmediateConsistency:
    """Corner: immediate_visibility_of_computed_fields."""

    def test_inherent_assessment_response_carries_computed_score(self):
        """PRD §3.2: "From `IDENTIFIED`, the assessment moves the risk to
        `ASSESSED` and sets `likelihood`, `impact`, `inherent_score`, and
        `inherent_band` on the risk."
        PRD §3.2: "Assessment records are append-only. Each record carries
        the `risk_id` it belongs to, its `kind`, and snapshots of the
        register after the event: `inherent_score` is captured for both
        kinds".

        Design: Corner/consistency_model/immediate_visibility_of_computed_fields
        """
        cat = create_category(name="IC")
        risk = create_identified_risk(category_id=cat["id"])
        v = risk["version"]
        res = api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 4, "impact": 3,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        assessment = validate_success(res, 201)
        # The snapshot is computed in the same request
        assert assessment["inherent_score"] == 12

    def test_get_risk_reflects_updated_score_and_version_immediately(self):
        """PRD §2.11: "Scores on the register are living values, and the
        system propagates every scoring-relevant change immediately."

        Design: Corner/consistency_model/immediate_visibility_of_computed_fields
        """
        cat = create_category(name="IC")
        risk = create_identified_risk(category_id=cat["id"])
        v = risk["version"]
        api_client.create_assessment(
            risk["id"],
            {"kind": "INHERENT", "likelihood": 4, "impact": 3,
             "expected_risk_version": v},
            make_risk_owner_headers(USER_RISK_OWNER),
        )
        after = validate_success(
            api_client.get_risk(
                risk["id"], make_internal_auditor_headers(USER_INTERNAL_AUDITOR),
            ), 200,
        )
        assert after["inherent_score"] == 12
        assert after["status"] == "ASSESSED"
        assert after["version"] == v + 1
