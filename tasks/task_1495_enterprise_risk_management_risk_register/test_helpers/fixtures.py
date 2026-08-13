"""Composite setup helpers — multi-step preconditions for the ERM register.

The recurring shape: every interesting assertion requires (at minimum) a
category, a risk, an INHERENT assessment, and very often a control + ACTIVE
mapping + RESIDUAL assessment + appetite statement + treatment plan. These
helpers centralize the plumbing so tests stay focused on assertions.

All helpers use get_success_data() (lenient) so setup failures produce clear
"Setup step failed" errors, not downstream assertion noise.

Ownership threading: every helper that creates a Risk records owner_user_id
and uses matching headers for downstream owner-only calls. Every helper that
creates a TreatmentPlan (proposer_user_id) ensures plan approval happens as a
different X-User-ID than the proposer (segregation of duties, PRD §2.10).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_category_payload,
    create_risk_payload,
    create_assessment_payload,
    create_control_payload,
    create_mapping_payload,
    create_appetite_payload,
    create_treatment_plan_payload,
    create_treatment_action_payload,
    create_kri_payload,
    create_kri_observation_payload,
    create_report_payload,
    create_emerging_risk_payload,
)
from .test_users import (
    USER_RISK_OWNER,
    USER_RISK_MANAGER,
    USER_RISK_MANAGER_2,
    USER_CONTROL_OWNER,
    USER_BOARD_REPORTER,
    USER_INTERNAL_AUDITOR,
    make_risk_owner_headers,
    make_risk_manager_headers,
    make_control_owner_headers,
    make_board_reporter_headers,
    make_internal_auditor_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: Entity + state progression
# ---------------------------------------------------------------------------

def create_category(name="TestCategory", weight_factor=None, parent_category_id=None):
    """Create a TaxonomyCategory as RiskManager. Returns the created entity."""
    payload = create_category_payload(name=name)
    if weight_factor is not None:
        payload["weight_factor"] = weight_factor
    if parent_category_id is not None:
        payload["parent_category_id"] = parent_category_id
    res = api_client.create_category(payload, make_risk_manager_headers(USER_RISK_MANAGER))
    return get_success_data(res)


def create_risk(category_id, owner_user_id=USER_RISK_OWNER,
                treatment_budget_cents=None, title="Test Risk"):
    """Create a Risk (DRAFT) as the given owner. Returns the created entity."""
    payload = create_risk_payload(category_id, title=title, owner_user_id=owner_user_id)
    if treatment_budget_cents is not None:
        payload["treatment_budget_cents"] = treatment_budget_cents
    res = api_client.create_risk(payload, make_risk_owner_headers(owner_user_id))
    return get_success_data(res)


def submit_risk(risk_id, owner_user_id=USER_RISK_OWNER):
    """DRAFT -> IDENTIFIED."""
    res = api_client.submit_risk(risk_id, make_risk_owner_headers(owner_user_id))
    return get_success_data(res)


def get_risk(risk_id, role="risk_manager"):
    """Read the live Risk. Role determines which X-User-Role header is sent."""
    if role == "risk_manager":
        headers = make_risk_manager_headers(USER_RISK_MANAGER)
    elif role == "risk_owner":
        headers = make_risk_owner_headers(USER_RISK_OWNER)
    elif role == "control_owner":
        headers = make_control_owner_headers(USER_CONTROL_OWNER)
    elif role == "board_reporter":
        headers = make_board_reporter_headers(USER_BOARD_REPORTER)
    else:
        headers = make_internal_auditor_headers(USER_INTERNAL_AUDITOR)
    res = api_client.get_risk(risk_id, headers)
    return get_success_data(res)


def get_risk_version(risk_id):
    """Cheap helper: read the risk and return its current version."""
    return get_risk(risk_id)["version"]


def create_inherent_assessment(risk_id, likelihood, impact,
                                owner_user_id=USER_RISK_OWNER):
    """Post an INHERENT assessment against the risk's current version."""
    version = get_risk_version(risk_id)
    payload = create_assessment_payload(
        "INHERENT", expected_risk_version=version,
        likelihood=likelihood, impact=impact,
    )
    res = api_client.create_assessment(
        risk_id, payload, make_risk_owner_headers(owner_user_id),
    )
    return get_success_data(res)


def create_residual_assessment(risk_id, owner_user_id=USER_RISK_OWNER):
    """Post a RESIDUAL assessment against the risk's current version."""
    version = get_risk_version(risk_id)
    payload = create_assessment_payload("RESIDUAL", expected_risk_version=version)
    res = api_client.create_assessment(
        risk_id, payload, make_risk_owner_headers(owner_user_id),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: Composite — risk in a particular state
# ---------------------------------------------------------------------------

def create_identified_risk(category_id=None, owner_user_id=USER_RISK_OWNER, **risk_kwargs):
    """Category (if not given) + risk in IDENTIFIED."""
    if category_id is None:
        category_id = create_category()["id"]
    risk = create_risk(category_id, owner_user_id=owner_user_id, **risk_kwargs)
    submit_risk(risk["id"], owner_user_id=owner_user_id)
    return get_risk(risk["id"])


def create_assessed_risk(category_id=None, likelihood=3, impact=3,
                          owner_user_id=USER_RISK_OWNER, **risk_kwargs):
    """Risk with an INHERENT assessment posted (status ASSESSED)."""
    risk = create_identified_risk(category_id=category_id,
                                   owner_user_id=owner_user_id, **risk_kwargs)
    create_inherent_assessment(risk["id"], likelihood, impact,
                                owner_user_id=owner_user_id)
    return get_risk(risk["id"])


def create_residual_assessed_risk(category_id=None, likelihood=3, impact=3,
                                    owner_user_id=USER_RISK_OWNER, **risk_kwargs):
    """Risk with INHERENT + RESIDUAL assessments posted (still ASSESSED)."""
    risk = create_assessed_risk(category_id=category_id, likelihood=likelihood,
                                 impact=impact, owner_user_id=owner_user_id,
                                 **risk_kwargs)
    create_residual_assessment(risk["id"], owner_user_id=owner_user_id)
    return get_risk(risk["id"])


# ---------------------------------------------------------------------------
# Tier 2: Controls and mappings
# ---------------------------------------------------------------------------

def create_control(name="Test Control", effectiveness_pct=0.5,
                   max_mapped_risks=None, owner_user_id=USER_CONTROL_OWNER):
    """Create a Control (PROPOSED). Returns the created entity."""
    payload = create_control_payload(name=name, effectiveness_pct=effectiveness_pct)
    if max_mapped_risks is not None:
        payload["max_mapped_risks"] = max_mapped_risks
    res = api_client.create_control(payload, make_control_owner_headers(owner_user_id))
    return get_success_data(res)


def create_active_control(name="Test Control", effectiveness_pct=0.5,
                           max_mapped_risks=None, owner_user_id=USER_CONTROL_OWNER):
    """Create + activate a Control (ACTIVE)."""
    ctl = create_control(name=name, effectiveness_pct=effectiveness_pct,
                          max_mapped_risks=max_mapped_risks,
                          owner_user_id=owner_user_id)
    res = api_client.activate_control(ctl["id"], make_control_owner_headers(owner_user_id))
    return get_success_data(res)


def create_proposed_mapping(risk_id, control_id, coverage_weight=0.5,
                              owner_user_id=USER_RISK_OWNER):
    """Propose a RiskControlMapping (PROPOSED)."""
    payload = create_mapping_payload(control_id, coverage_weight=coverage_weight)
    res = api_client.create_control_mapping(
        risk_id, payload, make_risk_owner_headers(owner_user_id),
    )
    return get_success_data(res)


def approve_mapping(mapping_id, manager_user_id=USER_RISK_MANAGER):
    """PROPOSED -> ACTIVE."""
    res = api_client.approve_mapping(
        mapping_id, make_risk_manager_headers(manager_user_id),
    )
    return get_success_data(res)


def retire_mapping(mapping_id, manager_user_id=USER_RISK_MANAGER):
    """ACTIVE -> RETIRED."""
    res = api_client.retire_mapping(
        mapping_id, make_risk_manager_headers(manager_user_id),
    )
    return get_success_data(res)


def create_active_mapping(risk_id, control_id, coverage_weight=0.5,
                            owner_user_id=USER_RISK_OWNER,
                            manager_user_id=USER_RISK_MANAGER):
    """Propose + approve. Returns the ACTIVE mapping."""
    m = create_proposed_mapping(risk_id, control_id,
                                  coverage_weight=coverage_weight,
                                  owner_user_id=owner_user_id)
    return approve_mapping(m["id"], manager_user_id=manager_user_id)


# ---------------------------------------------------------------------------
# Tier 2: Appetite
# ---------------------------------------------------------------------------

def create_appetite(category_id, tolerance_score=10, acceptance_cap_score=20,
                     effective_from="2026-01-01T00:00:00Z",
                     effective_to="2027-01-01T00:00:00Z",
                     creator_user_id=USER_RISK_MANAGER):
    """Create an AppetiteStatement (DRAFT). creator_user_id is recorded as created_by."""
    payload = create_appetite_payload(
        category_id,
        tolerance_score=tolerance_score,
        acceptance_cap_score=acceptance_cap_score,
        effective_from=effective_from,
        effective_to=effective_to,
    )
    res = api_client.create_appetite_statement(
        payload, make_risk_manager_headers(creator_user_id),
    )
    return get_success_data(res)


def approve_appetite(statement_id, approver_user_id=USER_RISK_MANAGER_2):
    """DRAFT -> APPROVED. Approver must differ from creator (SoD)."""
    res = api_client.approve_appetite_statement(
        statement_id, make_risk_manager_headers(approver_user_id),
    )
    return get_success_data(res)


def create_approved_appetite(category_id, tolerance_score=10,
                               acceptance_cap_score=20,
                               effective_from="2026-01-01T00:00:00Z",
                               effective_to="2027-01-01T00:00:00Z",
                               creator_user_id=USER_RISK_MANAGER,
                               approver_user_id=USER_RISK_MANAGER_2):
    """Create + approve (different manager for SoD). Returns APPROVED statement."""
    stmt = create_appetite(category_id, tolerance_score, acceptance_cap_score,
                             effective_from, effective_to,
                             creator_user_id=creator_user_id)
    return approve_appetite(stmt["id"], approver_user_id=approver_user_id)


# ---------------------------------------------------------------------------
# Tier 3: Treatment plans
# ---------------------------------------------------------------------------

def create_proposed_plan(risk_id, budget_cents=100_000, owner_user_id=USER_RISK_OWNER,
                           title="Plan", due_date="2026-12-31T00:00:00Z"):
    """Propose a TreatmentPlan under the risk. Creator's X-User-ID becomes proposer."""
    version = get_risk_version(risk_id)
    payload = create_treatment_plan_payload(
        expected_risk_version=version,
        title=title, budget_cents=budget_cents,
        due_date=due_date, owner_user_id=owner_user_id,
    )
    res = api_client.create_treatment_plan(
        risk_id, payload, make_risk_owner_headers(owner_user_id),
    )
    return get_success_data(res)


def approve_plan(plan_id, approver_user_id=USER_RISK_MANAGER):
    """PROPOSED -> APPROVED. Approver must differ from proposer_user_id (SoD)."""
    res = api_client.approve_treatment_plan(
        plan_id, make_risk_manager_headers(approver_user_id),
    )
    return get_success_data(res)


def create_approved_plan(risk_id, budget_cents=100_000,
                          owner_user_id=USER_RISK_OWNER,
                          approver_user_id=USER_RISK_MANAGER,
                          title="Plan", due_date="2026-12-31T00:00:00Z"):
    """Propose + approve. Returns APPROVED plan."""
    plan = create_proposed_plan(risk_id, budget_cents=budget_cents,
                                  owner_user_id=owner_user_id,
                                  title=title, due_date=due_date)
    return approve_plan(plan["id"], approver_user_id=approver_user_id)


def start_plan(plan_id, owner_user_id=USER_RISK_OWNER):
    """APPROVED -> IN_PROGRESS (owner only)."""
    res = api_client.start_treatment_plan(
        plan_id, make_risk_owner_headers(owner_user_id),
    )
    return get_success_data(res)


def cancel_plan(plan_id, owner_user_id=USER_RISK_OWNER, reason=None):
    """APPROVED/IN_PROGRESS/OVERDUE -> CANCELLED (owner only)."""
    payload = {"reason": reason} if reason is not None else {}
    res = api_client.cancel_treatment_plan(
        plan_id, make_risk_owner_headers(owner_user_id), payload=payload,
    )
    return get_success_data(res)


def create_in_progress_plan(risk_id, budget_cents=100_000,
                              owner_user_id=USER_RISK_OWNER,
                              approver_user_id=USER_RISK_MANAGER,
                              title="Plan", due_date="2026-12-31T00:00:00Z"):
    """APPROVED + started -> IN_PROGRESS plan."""
    plan = create_approved_plan(risk_id, budget_cents=budget_cents,
                                  owner_user_id=owner_user_id,
                                  approver_user_id=approver_user_id,
                                  title=title, due_date=due_date)
    return start_plan(plan["id"], owner_user_id=owner_user_id)


def add_action(plan_id, title, owner_user_id=USER_RISK_OWNER):
    """Add a TreatmentAction to a plan (must be APPROVED or IN_PROGRESS)."""
    payload = create_treatment_action_payload(title=title)
    res = api_client.create_treatment_action(
        plan_id, payload, make_risk_owner_headers(owner_user_id),
    )
    return get_success_data(res)


def done_action(action_id, owner_user_id=USER_RISK_OWNER):
    """PENDING -> DONE (parent plan must be IN_PROGRESS)."""
    res = api_client.mark_action_done(action_id, make_risk_owner_headers(owner_user_id))
    return get_success_data(res)


def get_plan(plan_id):
    """Read the live TreatmentPlan."""
    res = api_client.get_treatment_plan(
        plan_id, make_risk_manager_headers(USER_RISK_MANAGER),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3: KRIs
# ---------------------------------------------------------------------------

def create_kri(category_id, name="K", direction="ABOVE",
                amber_threshold=50, red_threshold=75,
                min_observation_interval_days=None,
                manager_user_id=USER_RISK_MANAGER):
    """Create a KRI (DRAFT). Returns the created entity."""
    payload = create_kri_payload(
        category_id, name=name, direction=direction,
        amber_threshold=amber_threshold, red_threshold=red_threshold,
    )
    if min_observation_interval_days is not None:
        payload["min_observation_interval_days"] = min_observation_interval_days
    res = api_client.create_kri(payload, make_risk_manager_headers(manager_user_id))
    return get_success_data(res)


def activate_kri(kri_id, manager_user_id=USER_RISK_MANAGER):
    """DRAFT -> ACTIVE."""
    res = api_client.activate_kri(kri_id, make_risk_manager_headers(manager_user_id))
    return get_success_data(res)


def create_active_kri(category_id, name="K", direction="ABOVE",
                        amber_threshold=50, red_threshold=75,
                        min_observation_interval_days=None,
                        manager_user_id=USER_RISK_MANAGER):
    """Create + activate a KRI."""
    kri = create_kri(category_id, name=name, direction=direction,
                      amber_threshold=amber_threshold, red_threshold=red_threshold,
                      min_observation_interval_days=min_observation_interval_days,
                      manager_user_id=manager_user_id)
    return activate_kri(kri["id"], manager_user_id=manager_user_id)


def observe_kri(kri_id, observed_value, observed_at,
                 manager_user_id=USER_RISK_MANAGER):
    """POST /kris/{id}/observations."""
    payload = create_kri_observation_payload(observed_value, observed_at)
    res = api_client.create_kri_observation(
        kri_id, payload, make_risk_manager_headers(manager_user_id),
    )
    return get_success_data(res)


def get_kri(kri_id, manager_user_id=USER_RISK_MANAGER):
    res = api_client.get_kri(kri_id, make_risk_manager_headers(manager_user_id))
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3: Reports
# ---------------------------------------------------------------------------

def create_report(period_start="2026-08-01T00:00:00Z",
                    period_end="2026-08-31T00:00:00Z",
                    variant="FINAL",
                    reporter_user_id=USER_BOARD_REPORTER):
    """Create a RiskReport (DRAFT)."""
    payload = create_report_payload(period_start=period_start,
                                      period_end=period_end, variant=variant)
    res = api_client.create_report(
        payload, make_board_reporter_headers(reporter_user_id),
    )
    return get_success_data(res)


def finalize_report(report_id, reporter_user_id=USER_BOARD_REPORTER):
    """DRAFT -> FINALIZED."""
    res = api_client.finalize_report(
        report_id, make_board_reporter_headers(reporter_user_id),
    )
    return get_success_data(res)


def get_report(report_id, reporter_user_id=USER_BOARD_REPORTER):
    res = api_client.get_report(
        report_id, make_board_reporter_headers(reporter_user_id),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 3: Emerging risks
# ---------------------------------------------------------------------------

def create_emerging_risk(category_id, title="E",
                           scenario_severity=4, scenario_probability=3,
                           stress_factor=None, creator_role="RiskManager",
                           creator_user_id=USER_RISK_MANAGER):
    """Create an EmergingRisk (DRAFT). Creator may be RiskManager or RiskOwner."""
    payload = create_emerging_risk_payload(
        category_id, title=title,
        scenario_severity=scenario_severity,
        scenario_probability=scenario_probability,
    )
    if stress_factor is not None:
        payload["stress_factor"] = stress_factor
    if creator_role == "RiskManager":
        headers = make_risk_manager_headers(creator_user_id)
    else:
        headers = make_risk_owner_headers(creator_user_id)
    res = api_client.create_emerging_risk(payload, headers)
    return get_success_data(res)


def validate_emerging_risk(emerging_id, manager_user_id=USER_RISK_MANAGER):
    res = api_client.validate_emerging_risk(
        emerging_id, make_risk_manager_headers(manager_user_id),
    )
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 4: Full-domain composite fixtures (used by difficulty tests)
# ---------------------------------------------------------------------------

def setup_assessed_risk_with_two_active_mappings(
        likelihood=4, impact=5,
        k1_effectiveness=0.8, k1_coverage=0.5,
        k2_effectiveness=0.6, k2_coverage=0.5,
        category_name="Cat", **risk_kwargs):
    """Composite: category + risk ASSESSED with INHERENT, two controls each with
    an ACTIVE mapping. Returns dict of named handles.

    Default parameterization produces the canonical residual = 9 scenario:
      contributions = 0.40, 0.30 (sorted desc)
      discount      = 0.40 + 0.30*(1-0.40) = 0.58
      residual      = ceil(20 * 0.42) = 9
    """
    cat = create_category(name=category_name)
    risk = create_assessed_risk(category_id=cat["id"],
                                  likelihood=likelihood, impact=impact,
                                  **risk_kwargs)
    k1 = create_active_control(name="K1", effectiveness_pct=k1_effectiveness)
    k2 = create_active_control(name="K2", effectiveness_pct=k2_effectiveness)
    m1 = create_active_mapping(risk["id"], k1["id"], coverage_weight=k1_coverage)
    m2 = create_active_mapping(risk["id"], k2["id"], coverage_weight=k2_coverage)
    return {
        "category": cat,
        "risk": get_risk(risk["id"]),
        "k1": k1, "k2": k2,
        "m1": m1, "m2": m2,
    }


def setup_risk_in_treatment_with_plan(
        likelihood=3, impact=3,
        treatment_budget_cents=500_000,
        plan_budget_cents=100_000,
        plan_due_date="2026-12-31T00:00:00Z",
        category_name="Cat",
        owner_user_id=USER_RISK_OWNER,
        with_residual=True):
    """Composite: risk ASSESSED (+ RESIDUAL) -> plan APPROVED -> risk TREATMENT.
    Returns dict with category, risk, plan."""
    cat = create_category(name=category_name)
    if with_residual:
        risk = create_residual_assessed_risk(
            category_id=cat["id"], likelihood=likelihood, impact=impact,
            owner_user_id=owner_user_id,
            treatment_budget_cents=treatment_budget_cents,
        )
    else:
        risk = create_assessed_risk(
            category_id=cat["id"], likelihood=likelihood, impact=impact,
            owner_user_id=owner_user_id,
            treatment_budget_cents=treatment_budget_cents,
        )
    plan = create_approved_plan(
        risk["id"], budget_cents=plan_budget_cents,
        owner_user_id=owner_user_id, due_date=plan_due_date,
    )
    res = api_client.enter_treatment(
        risk["id"], make_risk_owner_headers(owner_user_id),
    )
    get_success_data(res)
    return {
        "category": cat,
        "risk": get_risk(risk["id"]),
        "plan": get_plan(plan["id"]),
    }


def setup_risk_in_monitoring(likelihood=3, impact=3,
                               treatment_budget_cents=500_000,
                               plan_budget_cents=100_000,
                               category_name="Cat",
                               owner_user_id=USER_RISK_OWNER):
    """Composite: risk TREATMENT -> plan cancelled -> risk MONITORING.

    Walks the only PRD path to MONITORING: enter-treatment requires an APPROVED
    plan, then we cancel it (so no plan is non-terminal) before monitor.
    """
    cat = create_category(name=category_name)
    risk = create_residual_assessed_risk(
        category_id=cat["id"], likelihood=likelihood, impact=impact,
        owner_user_id=owner_user_id,
        treatment_budget_cents=treatment_budget_cents,
    )
    plan = create_approved_plan(
        risk["id"], budget_cents=plan_budget_cents,
        owner_user_id=owner_user_id,
    )
    api_client.enter_treatment(risk["id"], make_risk_owner_headers(owner_user_id))
    cancel_plan(plan["id"], owner_user_id=owner_user_id)
    res = api_client.monitor_risk(risk["id"], make_risk_owner_headers(owner_user_id))
    get_success_data(res)
    return {
        "category": cat,
        "risk": get_risk(risk["id"]),
        "plan": get_plan(plan["id"]),
    }


def setup_category_with_approved_appetite(
        tolerance_score=10, acceptance_cap_score=20,
        effective_from="2026-01-01T00:00:00Z",
        effective_to="2027-01-01T00:00:00Z",
        category_name="Cat",
        creator_user_id=USER_RISK_MANAGER,
        approver_user_id=USER_RISK_MANAGER_2):
    """Category + APPROVED appetite statement covering the default clock."""
    cat = create_category(name=category_name)
    stmt = create_approved_appetite(
        cat["id"], tolerance_score, acceptance_cap_score,
        effective_from, effective_to,
        creator_user_id=creator_user_id,
        approver_user_id=approver_user_id,
    )
    return {"category": cat, "appetite": stmt}


# ---------------------------------------------------------------------------
# Tier 4: Breach generation
# ---------------------------------------------------------------------------

def create_breach_via_residual(risk_id, owner_user_id=USER_RISK_OWNER):
    """Trigger appetite breach evaluation by posting a RESIDUAL assessment and
    return the (now-open) ToleranceBreach, or None if the evaluation did not
    breach. Assumes an APPROVED appetite covering the current clock is in place
    and the risk's residual_score will exceed tolerance."""
    create_residual_assessment(risk_id, owner_user_id=owner_user_id)
    res = api_client.list_risk_tolerance_breaches(
        risk_id, make_risk_manager_headers(USER_RISK_MANAGER),
    )
    body = get_success_data(res)
    items = body if isinstance(body, list) else body.get("data", [])
    return items[0] if items else None


def get_risk_breaches(risk_id):
    res = api_client.list_risk_tolerance_breaches(
        risk_id, make_risk_manager_headers(USER_RISK_MANAGER),
    )
    body = get_success_data(res)
    return body if isinstance(body, list) else body.get("data", [])


# ---------------------------------------------------------------------------
# Tier 5: Clock / sweeps
# ---------------------------------------------------------------------------

def advance_clock(to_iso8601, manager_user_id=USER_RISK_MANAGER):
    """POST /_clock/set_current_utc — sweeps overdue plans and lapsed ACCEPTED
    breaches (PRD §2.4). Returns the response data (contains current_utc)."""
    res = api_client.set_clock(to_iso8601, make_risk_manager_headers(manager_user_id))
    return get_success_data(res)
