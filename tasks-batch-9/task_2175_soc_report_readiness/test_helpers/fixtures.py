"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because each test runs against an empty database.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import OBS_END, OBS_START
from .test_users import (
    ACCOUNT_EXECUTIVE_ID,
    AUDITOR_ID,
    COMPLIANCE_LEAD_ID,
    CONTROL_OWNER_ID,
    EVIDENCE_REVIEWER_ID,
    PLATFORM_ADMIN_ID,
    make_account_executive_headers,
    make_auditor_headers,
    make_compliance_lead_headers,
    make_control_owner_headers,
    make_evidence_reviewer_headers,
    make_platform_admin_headers,
)

CL = COMPLIANCE_LEAD_ID
AUD = AUDITOR_ID
OWN = CONTROL_OWNER_ID
REV = EVIDENCE_REVIEWER_ID
AE = ACCOUNT_EXECUTIVE_ID
PA = PLATFORM_ADMIN_ID

OBSERVATION_CLOCK = "2026-10-05T00:00:00.000Z"
POST_PERIOD_CLOCK = "2026-12-01T00:00:00.000Z"


# --------------------------------------------------------------------------
# Tier 0: single-call primitives
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str, user_id: str = PA) -> str:
    data = get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, make_platform_admin_headers(user_id))
    )
    return data["current_utc"]


def create_criterion(
    criterion_code: str = "CC1.1",
    category: str = "SECURITY",
    title: str = "Control environment",
    min_primary_controls: int = 1,
    applies_to_report_types=("SOC_2_TYPE_2",),
    user_id: str = PA,
) -> dict:
    payload = {
        "criterion_code": criterion_code,
        "category": category,
        "title": title,
        "min_primary_controls": min_primary_controls,
        "applies_to_report_types": list(applies_to_report_types),
    }
    return get_success_data(
        api_client.create_trust_criterion(payload, make_platform_admin_headers(user_id))
    )


def create_engagement(
    client_name: str = "Northwind",
    report_type: str = "SOC_2_TYPE_2",
    categories=("SECURITY",),
    observation_period_start: str = OBS_START,
    observation_period_end: str = OBS_END,
    max_distribution_recipients=None,
    user_id: str = CL,
) -> dict:
    payload = {
        "client_name": client_name,
        "report_type": report_type,
        "observation_period_start": observation_period_start,
        "observation_period_end": observation_period_end,
        "required_criteria_categories": list(categories),
    }
    if max_distribution_recipients is not None:
        payload["max_distribution_recipients"] = max_distribution_recipients
    return get_success_data(
        api_client.create_engagement(payload, make_compliance_lead_headers(user_id))
    )


def read_engagement(engagement_id: str, user_id: str = CL) -> dict:
    return get_success_data(
        api_client.get_engagement(engagement_id, make_compliance_lead_headers(user_id))
    )


def read_readiness_summary(engagement_id: str, user_id: str = CL) -> dict:
    return get_success_data(
        api_client.get_readiness_summary(engagement_id, make_compliance_lead_headers(user_id))
    )


def read_control(control_id: str, user_id: str = AUD) -> dict:
    return get_success_data(
        api_client.get_control(control_id, make_auditor_headers(user_id))
    )


def engagement_version(engagement_id: str) -> int:
    return read_engagement(engagement_id)["version"]


def control_version(control_id: str) -> int:
    return read_control(control_id)["version"]


def author_description(
    engagement_id: str,
    version_label: str = "v1",
    boundary_narrative: str = "The examined platform boundary.",
    expected_engagement_version=None,
    author_id: str = CL,
) -> dict:
    if expected_engagement_version is None:
        expected_engagement_version = engagement_version(engagement_id)
    payload = {
        "engagement_id": engagement_id,
        "version_label": version_label,
        "boundary_narrative": boundary_narrative,
        "expected_engagement_version": expected_engagement_version,
    }
    return get_success_data(
        api_client.create_system_description(payload, make_compliance_lead_headers(author_id))
    )


def add_component(
    system_description_id: str,
    component_type: str = "SOFTWARE",
    name: str = "Core API",
    scope_status=None,
    subservice_organization_id=None,
    exclusion_rationale=None,
    actor_id: str = CL,
) -> dict:
    payload = {
        "system_description_id": system_description_id,
        "component_type": component_type,
        "name": name,
    }
    if scope_status is not None:
        payload["scope_status"] = scope_status
    if subservice_organization_id is not None:
        payload["subservice_organization_id"] = subservice_organization_id
    if exclusion_rationale is not None:
        payload["exclusion_rationale"] = exclusion_rationale
    return get_success_data(
        api_client.create_boundary_component(payload, make_compliance_lead_headers(actor_id))
    )


def description_action(system_description_id: str, action: str, headers, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_system_description(system_description_id, body, headers)
    )


def submit_description_for_review(system_description_id: str, actor_id: str = CL) -> dict:
    return description_action(
        system_description_id, "SUBMIT_REVIEW", make_compliance_lead_headers(actor_id)
    )


def approve_description(system_description_id: str, auditor_id: str = AUD) -> dict:
    return description_action(
        system_description_id, "APPROVE", make_auditor_headers(auditor_id)
    )


def lock_boundary(system_description_id: str, actor_id: str = CL) -> dict:
    return get_success_data(
        api_client.lock_boundary(system_description_id, make_compliance_lead_headers(actor_id))
    )


def create_control(
    engagement_id: str,
    control_ref: str = "S-01",
    title: str = "Change approvals",
    frequency: str = "MONTHLY",
    automation=None,
    risk_rating=None,
    population_size=None,
    subservice_organization_id=None,
    actor_id: str = CL,
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "control_ref": control_ref,
        "title": title,
        "frequency": frequency,
    }
    if automation is not None:
        payload["automation"] = automation
    if risk_rating is not None:
        payload["risk_rating"] = risk_rating
    if population_size is not None:
        payload["population_size"] = population_size
    if subservice_organization_id is not None:
        payload["subservice_organization_id"] = subservice_organization_id
    return get_success_data(
        api_client.create_control(payload, make_compliance_lead_headers(actor_id))
    )


def map_control(
    control_id: str,
    trust_criterion_id: str,
    mapping_type: str = "PRIMARY",
    rationale=None,
    actor_id: str = CL,
) -> dict:
    payload = {
        "control_id": control_id,
        "trust_criterion_id": trust_criterion_id,
        "mapping_type": mapping_type,
    }
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(
        api_client.create_criteria_mapping(payload, make_compliance_lead_headers(actor_id))
    )


def assign_owner(control_id: str, owner_user_id: str = OWN, actor_id: str = CL) -> dict:
    return get_success_data(
        api_client.assign_control_owner(
            control_id, {"owner_user_id": owner_user_id}, make_compliance_lead_headers(actor_id)
        )
    )


def schedule_evidence(
    control_id: str,
    period_index: int = 0,
    period_start: str = OBS_START,
    period_end: str = OBS_END,
    actor_id: str = CL,
) -> dict:
    payload = {
        "control_id": control_id,
        "period_index": period_index,
        "period_start": period_start,
        "period_end": period_end,
    }
    return get_success_data(
        api_client.create_evidence_request(payload, make_compliance_lead_headers(actor_id))
    )


def generate_calendar(control_id: str, actor_id: str = CL) -> list:
    return get_success_data(
        api_client.generate_evidence_calendar(control_id, make_compliance_lead_headers(actor_id))
    )


def approve_control_design(control_id: str, auditor_id: str = AUD) -> dict:
    return get_success_data(
        api_client.transition_control(
            control_id, {"action": "APPROVE_DESIGN"}, make_auditor_headers(auditor_id)
        )
    )


def engagement_action(engagement_id: str, action: str, headers, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_engagement(engagement_id, body, headers)
    )


def lead_engagement_action(engagement_id: str, action: str, actor_id: str = CL, **payload) -> dict:
    return engagement_action(
        engagement_id, action, make_compliance_lead_headers(actor_id), **payload
    )


def auditor_engagement_action(engagement_id: str, action: str, actor_id: str = AUD, **payload) -> dict:
    return engagement_action(engagement_id, action, make_auditor_headers(actor_id), **payload)


def run_readiness_assessment(engagement_id: str, actor_id: str = CL) -> dict:
    return get_success_data(
        api_client.run_readiness_assessment(
            engagement_id, make_compliance_lead_headers(actor_id)
        )
    )


def run_calendar(engagement_id: str, actor_id: str = CL) -> dict:
    return get_success_data(
        api_client.run_calendar(engagement_id, make_compliance_lead_headers(actor_id))
    )


def submit_evidence(
    evidence_request_id: str, owner_user_id: str = OWN, artifact_ref: str = "art-1"
) -> dict:
    return get_success_data(
        api_client.submit_evidence(
            evidence_request_id,
            {"artifact_ref": artifact_ref},
            make_control_owner_headers(owner_user_id),
        )
    )


def review_evidence(
    evidence_request_id: str, action: str = "ACCEPT", reviewer_id: str = REV, **payload
) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.review_evidence(
            evidence_request_id, body, make_evidence_reviewer_headers(reviewer_id)
        )
    )


def settle_evidence(
    evidence_request_id: str,
    owner_user_id: str = OWN,
    reviewer_id: str = REV,
    artifact_ref: str = "art-1",
) -> dict:
    submit_evidence(evidence_request_id, owner_user_id, artifact_ref)
    return review_evidence(evidence_request_id, "ACCEPT", reviewer_id)


def create_manual_gap(
    engagement_id: str, severity: str = "MODERATE", description=None, actor_id: str = CL, **extra
) -> dict:
    payload = {"engagement_id": engagement_id, "severity": severity}
    if description is not None:
        payload["description"] = description
    payload.update(extra)
    return get_success_data(
        api_client.create_gap(payload, make_compliance_lead_headers(actor_id))
    )


def gap_action(gap_id: str, action: str, headers, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(api_client.transition_gap(gap_id, body, headers))


def plan_gap(gap_id: str, remediation_owner_user_id: str, remediation_due_date: str, actor_id: str = CL) -> dict:
    return gap_action(
        gap_id,
        "PLAN",
        make_compliance_lead_headers(actor_id),
        remediation_owner_user_id=remediation_owner_user_id,
        remediation_due_date=remediation_due_date,
    )


def remediate_gap(gap_id: str, actor_id: str = CL) -> dict:
    return gap_action(gap_id, "REMEDIATE", make_compliance_lead_headers(actor_id))


def verify_gap(gap_id: str, auditor_id: str = AUD) -> dict:
    return gap_action(gap_id, "VERIFY", make_auditor_headers(auditor_id))


def reopen_gap(gap_id: str, auditor_id: str = AUD, reason=None) -> dict:
    extra = {"reason": reason} if reason is not None else {}
    return gap_action(gap_id, "REOPEN", make_auditor_headers(auditor_id), **extra)


def create_subservice_org(
    engagement_id: str,
    name: str = "HostCo",
    services_provided: str = "Colocation",
    coverage_start: str = OBS_START,
    coverage_end: str = OBS_END,
    actor_id: str = CL,
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "name": name,
        "services_provided": services_provided,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
    }
    return get_success_data(
        api_client.create_subservice_organization(
            payload, make_compliance_lead_headers(actor_id)
        )
    )


def set_subservice_method(
    subservice_organization_id: str, method: str, csoc_narrative=None, actor_id: str = CL
) -> dict:
    payload = {"method": method}
    if csoc_narrative is not None:
        payload["csoc_narrative"] = csoc_narrative
    return get_success_data(
        api_client.set_subservice_method(
            subservice_organization_id, payload, make_compliance_lead_headers(actor_id)
        )
    )


def draw_sample(
    control_id: str,
    period_start: str = OBS_START,
    period_end: str = OBS_END,
    expected_control_version=None,
    auditor_id: str = AUD,
) -> dict:
    if expected_control_version is None:
        expected_control_version = control_version(control_id)
    payload = {
        "control_id": control_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_control_version": expected_control_version,
    }
    return get_success_data(
        api_client.draw_audit_sample(payload, make_auditor_headers(auditor_id))
    )


def record_items(sample_id: str, outcomes, auditor_id: str = AUD) -> dict:
    last = None
    for outcome in outcomes:
        if isinstance(outcome, tuple):
            body = {"outcome": outcome[0], "failure_reason": outcome[1]}
        else:
            body = {"outcome": outcome}
        last = get_success_data(
            api_client.record_sample_item(sample_id, body, make_auditor_headers(auditor_id))
        )
    return last


def conclude_sample(sample_id: str, auditor_id: str = AUD) -> dict:
    return get_success_data(
        api_client.conclude_audit_sample(sample_id, make_auditor_headers(auditor_id))
    )


def void_sample(sample_id: str, reason=None, auditor_id: str = AUD) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(
        api_client.void_audit_sample(sample_id, payload, make_auditor_headers(auditor_id))
    )


def list_exceptions(sample_id: str, auditor_id: str = AUD) -> list:
    return get_success_data(
        api_client.list_audit_exceptions(
            make_auditor_headers(auditor_id), params={"audit_sample_id": sample_id}
        )
    )


def evaluate_exception(
    exception_id: str, disposition: str, evaluation_note=None, auditor_id: str = AUD
) -> dict:
    payload = {"disposition": disposition}
    if evaluation_note is not None:
        payload["evaluation_note"] = evaluation_note
    return get_success_data(
        api_client.evaluate_audit_exception(
            exception_id, payload, make_auditor_headers(auditor_id)
        )
    )


def create_cuec(
    engagement_id: str,
    trust_criterion_id: str,
    statement: str = "User entities must review their own access reports quarterly.",
    deflection_topic: str = "user-access",
    actor_id: str = CL,
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "trust_criterion_id": trust_criterion_id,
        "statement": statement,
        "deflection_topic": deflection_topic,
    }
    return get_success_data(
        api_client.create_cuec(payload, make_compliance_lead_headers(actor_id))
    )


def articulate_cuec(cuec_id: str, action: str = "ARTICULATE", actor_id: str = CL) -> dict:
    return get_success_data(
        api_client.articulate_cuec(
            cuec_id, {"action": action}, make_compliance_lead_headers(actor_id)
        )
    )


def create_distribution(
    engagement_id: str,
    recipient_name: str = "Acme Corp",
    recipient_email: str = "soc@acme.example",
    actor_id: str = AE,
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "recipient_name": recipient_name,
        "recipient_email": recipient_email,
    }
    return get_success_data(
        api_client.create_report_distribution(payload, make_account_executive_headers(actor_id))
    )


def distribution_action(report_distribution_id: str, action: str, headers, **payload) -> dict:
    body = {"action": action}
    body.update(payload)
    return get_success_data(
        api_client.transition_report_distribution(report_distribution_id, body, headers)
    )


def create_bridge_letter(
    engagement_id: str,
    coverage_start: str,
    as_of_date: str,
    supersedes_bridge_letter_id=None,
    actor_id: str = AE,
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "coverage_start": coverage_start,
        "as_of_date": as_of_date,
    }
    if supersedes_bridge_letter_id is not None:
        payload["supersedes_bridge_letter_id"] = supersedes_bridge_letter_id
    return get_success_data(
        api_client.create_bridge_letter(payload, make_account_executive_headers(actor_id))
    )


def issue_bridge_letter(bridge_letter_id: str, actor_id: str = AE) -> dict:
    return get_success_data(
        api_client.issue_bridge_letter(bridge_letter_id, make_account_executive_headers(actor_id))
    )


def create_questionnaire(
    engagement_id: str,
    report_distribution_id: str,
    customer_name: str = "Acme Corp Security",
    criteria_item_count: int = 4,
    post_period_item_count: int = 3,
    cuec_item_count: int = 5,
    actor_id: str = AE,
) -> dict:
    payload = {
        "engagement_id": engagement_id,
        "report_distribution_id": report_distribution_id,
        "customer_name": customer_name,
        "criteria_item_count": criteria_item_count,
        "post_period_item_count": post_period_item_count,
        "cuec_item_count": cuec_item_count,
    }
    return get_success_data(
        api_client.create_customer_questionnaire(
            payload, make_account_executive_headers(actor_id)
        )
    )


def deflect_questionnaire(questionnaire_id: str, as_of_date: str, actor_id: str = AE) -> dict:
    return get_success_data(
        api_client.deflect_customer_questionnaire(
            questionnaire_id, {"as_of_date": as_of_date}, make_account_executive_headers(actor_id)
        )
    )


# --------------------------------------------------------------------------
# Tier 1: approved + locked narrative
# --------------------------------------------------------------------------
def setup_approved_locked_description(
    engagement_id: str,
    version_label: str = "v1",
    boundary_narrative: str = "The examined platform boundary.",
    component_type: str = "SOFTWARE",
    component_name: str = "Core API",
    lock: bool = True,
    author_id: str = CL,
    auditor_id: str = AUD,
) -> dict:
    """Author a description, give it one in-scope component, approve it, and
    (by default) lock its boundary. Returns the description as last read."""
    description = author_description(
        engagement_id,
        version_label=version_label,
        boundary_narrative=boundary_narrative,
        author_id=author_id,
    )
    add_component(
        description["id"], component_type=component_type, name=component_name, actor_id=author_id
    )
    submit_description_for_review(description["id"], actor_id=author_id)
    description = approve_description(description["id"], auditor_id=auditor_id)
    if lock:
        description = lock_boundary(description["id"], actor_id=author_id)
    return description


# --------------------------------------------------------------------------
# Tier 2 / 3: the whole readiness-to-fieldwork ladder
# --------------------------------------------------------------------------
DEFAULT_CONTROL_SPEC = {
    "control_ref": "S-01",
    "title": "Change approvals",
    "frequency": "QUARTERLY",
    "automation": "MANUAL",
    "risk_rating": "MODERATE",
    "population_size": 20,
    "map": (("CC1.1", "PRIMARY"),),
    "owner": OWN,
    "evidence": True,
    "approve_design": True,
    "evidence_period": None,
}


def setup_engagement_at(
    phase: str = "FIELDWORK",
    client_name: str = "Northwind",
    report_type: str = "SOC_2_TYPE_2",
    categories=("SECURITY",),
    criteria=None,
    controls=None,
    max_distribution_recipients=None,
    observation_period_start: str = OBS_START,
    observation_period_end: str = OBS_END,
    lock: bool = True,
    observation_clock: str = OBSERVATION_CLOCK,
    post_period_clock: str = POST_PERIOD_CLOCK,
) -> dict:
    """Walk an engagement up the phase ladder, wiring criteria, controls,
    mappings, owners and evidence along the way.

    phase is one of SCOPING, READINESS, OBSERVATION, FIELDWORK.
    criteria is a list of kwargs dicts for create_criterion.
    controls is a list of control spec dicts (see DEFAULT_CONTROL_SPEC).
    Returns {"engagement", "criteria", "system_description", "controls", "evidence"}.
    """
    if criteria is None:
        criteria = [
            {
                "criterion_code": "CC1.1",
                "category": "SECURITY",
                "title": "Control environment",
                "min_primary_controls": 1,
                "applies_to_report_types": (report_type,),
            }
        ]
    if controls is None:
        controls = [dict(DEFAULT_CONTROL_SPEC)]

    criterion_rows = {}
    for spec in criteria:
        row = create_criterion(**spec)
        criterion_rows[row["criterion_code"]] = row

    engagement = create_engagement(
        client_name=client_name,
        report_type=report_type,
        categories=categories,
        observation_period_start=observation_period_start,
        observation_period_end=observation_period_end,
        max_distribution_recipients=max_distribution_recipients,
    )
    description = setup_approved_locked_description(engagement["id"], lock=lock)

    control_rows = {}
    evidence_rows = {}
    for spec in controls:
        merged = dict(DEFAULT_CONTROL_SPEC)
        merged.update(spec)
        control = create_control(
            engagement["id"],
            control_ref=merged["control_ref"],
            title=merged["title"],
            frequency=merged["frequency"],
            automation=merged["automation"],
            risk_rating=merged["risk_rating"],
            population_size=merged["population_size"],
            subservice_organization_id=merged.get("subservice_organization_id"),
        )
        for code, mapping_type in merged["map"]:
            map_control(control["id"], criterion_rows[code]["id"], mapping_type=mapping_type)
        if merged.get("owner"):
            assign_owner(control["id"], merged["owner"])
        if merged.get("evidence"):
            window = merged.get("evidence_period") or (
                observation_period_start,
                observation_period_end,
            )
            evidence_rows[merged["control_ref"]] = schedule_evidence(
                control["id"],
                period_index=0,
                period_start=window[0],
                period_end=window[1],
            )
        control_rows[merged["control_ref"]] = control

    if phase != "SCOPING":
        lead_engagement_action(engagement["id"], "START_READINESS")
        for spec in controls:
            merged = dict(DEFAULT_CONTROL_SPEC)
            merged.update(spec)
            if merged.get("approve_design"):
                approve_control_design(control_rows[merged["control_ref"]]["id"])

    if phase in ("OBSERVATION", "FIELDWORK"):
        run_readiness_assessment(engagement["id"])
        lead_engagement_action(engagement["id"], "START_OBSERVATION")

    if phase == "FIELDWORK":
        set_clock(observation_clock)
        for spec in controls:
            merged = dict(DEFAULT_CONTROL_SPEC)
            merged.update(spec)
            if merged.get("evidence"):
                settle_evidence(
                    evidence_rows[merged["control_ref"]]["id"],
                    owner_user_id=merged["owner"],
                    artifact_ref="art-" + merged["control_ref"],
                )
        set_clock(post_period_clock)
        lead_engagement_action(engagement["id"], "START_FIELDWORK")

    return {
        "engagement": read_engagement(engagement["id"]),
        "engagement_id": engagement["id"],
        "criteria": criterion_rows,
        "system_description": description,
        "controls": {ref: read_control(row["id"]) for ref, row in control_rows.items()},
        "evidence": evidence_rows,
    }


def setup_fieldwork_single_control(**overrides) -> dict:
    """The most common preamble: one QUARTERLY / MANUAL / MODERATE control with
    population 20, design-approved, owned, its only evidence request accepted, and
    the engagement in FIELDWORK. sample_size for a draw on it is 4."""
    kwargs = {"phase": "FIELDWORK"}
    kwargs.update(overrides)
    return setup_engagement_at(**kwargs)


def setup_sample_in_testing(outcomes, **overrides) -> dict:
    """Fieldwork engagement plus one drawn sample with `outcomes` recorded on it."""
    scenario = setup_fieldwork_single_control(**overrides)
    control = scenario["controls"]["S-01"]
    sample = draw_sample(control["id"])
    if outcomes:
        record_items(sample["id"], outcomes)
    scenario["sample"] = sample
    scenario["control"] = control
    return scenario


# --------------------------------------------------------------------------
# Tier 4: issued report, delivered distribution, bridge letters
# --------------------------------------------------------------------------
def setup_issued_engagement(
    client_name: str = "Relecloud",
    report_type: str = "SOC_1_TYPE_2",
    articulated_cuec_count: int = 0,
) -> dict:
    """Full lifecycle through ISSUED using a zero-population ADHOC control, whose
    sample is minted directly into CONCLUDED_CLEAN so the attestation view reaches
    100.00. Returns the scenario dict plus the sample and any articulated CUECs."""
    scenario = setup_engagement_at(
        phase="FIELDWORK",
        client_name=client_name,
        report_type=report_type,
        controls=[
            {
                "control_ref": "X-01",
                "title": "Emergency change review",
                "frequency": "ADHOC",
                "automation": "MANUAL",
                "risk_rating": "LOW",
                "population_size": 0,
                "map": (("CC1.1", "PRIMARY"),),
            }
        ],
    )
    criterion = scenario["criteria"]["CC1.1"]
    cuecs = []
    for index in range(articulated_cuec_count):
        cuec = create_cuec(
            scenario["engagement_id"],
            criterion["id"],
            statement=f"User entities must perform complementary duty number {index + 1}.",
            deflection_topic=f"topic-{index + 1}",
        )
        articulate_cuec(cuec["id"])
        cuecs.append(cuec)

    sample = draw_sample(scenario["controls"]["X-01"]["id"])
    auditor_engagement_action(scenario["engagement_id"], "START_REPORTING")
    auditor_engagement_action(scenario["engagement_id"], "ISSUE")

    scenario["sample"] = sample
    scenario["cuecs"] = cuecs
    scenario["engagement"] = read_engagement(scenario["engagement_id"])
    return scenario


def deliver_distribution(
    engagement_id: str,
    recipient_name: str = "Acme Corp",
    recipient_email: str = "soc@acme.example",
    nda_reference: str = "NDA-2026-001",
) -> dict:
    """Request, NDA, approve and deliver one distribution. The engagement must
    already be ISSUED with an OPEN posture."""
    distribution = create_distribution(
        engagement_id, recipient_name=recipient_name, recipient_email=recipient_email
    )
    distribution_action(
        distribution["id"], "REQUEST_NDA", make_account_executive_headers(AE)
    )
    distribution_action(
        distribution["id"],
        "APPROVE",
        make_compliance_lead_headers(CL),
        nda_reference=nda_reference,
    )
    return distribution_action(
        distribution["id"], "DELIVER", make_account_executive_headers(AE)
    )


def setup_delivered_report(
    client_name: str = "Relecloud",
    report_type: str = "SOC_1_TYPE_2",
    articulated_cuec_count: int = 0,
) -> dict:
    """Issued engagement with one DELIVERED distribution - the precondition of
    bridge-letter issue and of questionnaire deflection."""
    scenario = setup_issued_engagement(
        client_name=client_name,
        report_type=report_type,
        articulated_cuec_count=articulated_cuec_count,
    )
    scenario["distribution"] = deliver_distribution(scenario["engagement_id"])
    scenario["engagement"] = read_engagement(scenario["engagement_id"])
    return scenario
