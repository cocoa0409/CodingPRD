"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only PRD-declared endpoints.  Setup calls use
the lenient validator so a broken precondition reports as "Setup step failed"
rather than as a confusing assertion deep inside a test.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_checklist_item_payload,
    attach_credit_evidence_payload,
    create_certification_credit_payload,
    create_closeout_deliverable_payload,
    create_cx_plan_payload,
    create_cx_project_payload,
    create_deferred_test_payload,
    create_energy_baseline_payload,
    create_equipment_unit_payload,
    create_functional_test_payload,
    create_issue_payload,
    create_owner_requirement_payload,
    create_prefunctional_checklist_payload,
    create_submittal_payload,
    deliver_closeout_deliverable_payload,
    record_checklist_item_payload,
    record_post_period_payload,
    review_submittal_payload,
)
from .test_users import (
    ADMIN,
    CONTRACTOR,
    CXA,
    DESIGN,
    OWNER,
    make_contractor_headers,
    make_cx_authority_headers,
)

# --------------------------------------------------------------------------
# Tier 0 — single-call primitives
# --------------------------------------------------------------------------


def create_project(**overrides) -> dict:
    """Open a commissioning engagement."""
    return get_success_data(
        api_client.create_cx_project(create_cx_project_payload(**overrides), ADMIN)
    )


def get_project(project_id: str) -> dict:
    return get_success_data(api_client.get_cx_project(project_id, CXA))


def project_version(project_id: str) -> int:
    return get_project(project_id)["version"]


def get_readiness(project_id: str) -> dict:
    return get_success_data(api_client.get_readiness(project_id, CXA))


def set_logical_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


def create_requirement(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_owner_requirement(
            create_owner_requirement_payload(project_id, **overrides), OWNER
        )
    )


def create_approved_requirement(project_id: str, **overrides) -> dict:
    """Author an Owner Project Requirement line and move it DRAFT -> APPROVED."""
    requirement = create_requirement(project_id, **overrides)
    return get_success_data(
        api_client.approve_owner_requirement(requirement["id"], OWNER)
    )


def create_plan(project_id: str, title: str = "Commissioning Plan") -> dict:
    """Draft a commissioning plan, presenting the engagement's current version."""
    return get_success_data(
        api_client.create_cx_plan(
            create_cx_plan_payload(project_id, project_version(project_id), title=title),
            CXA,
        )
    )


def create_approved_plan(project_id: str, title: str = "Commissioning Plan") -> dict:
    plan = create_plan(project_id, title=title)
    return get_success_data(api_client.approve_cx_plan(plan["id"], OWNER))


def register_equipment(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_equipment_unit(
            create_equipment_unit_payload(project_id, **overrides), CXA
        )
    )


def set_install_status(equipment_id: str, install_status: str, user_id=None) -> dict:
    headers = make_contractor_headers(user_id) if user_id else CONTRACTOR
    return get_success_data(
        api_client.set_install_status(
            equipment_id, {"install_status": install_status}, headers
        )
    )


def get_equipment(equipment_id: str) -> dict:
    return get_success_data(api_client.get_equipment_unit(equipment_id, CXA))


def create_checklist(equipment_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_prefunctional_checklist(
            create_prefunctional_checklist_payload(equipment_id, **overrides), CXA
        )
    )


def add_item(checklist_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.add_checklist_item(
            checklist_id, add_checklist_item_payload(**overrides), CXA
        )
    )


def record_item(checklist_id: str, user_id: str = None, **overrides) -> dict:
    headers = make_contractor_headers(user_id) if user_id else CONTRACTOR
    return get_success_data(
        api_client.record_checklist_item(
            checklist_id, record_checklist_item_payload(**overrides), headers
        )
    )


def execute_checklist(checklist_id: str, user_id: str = None) -> dict:
    headers = make_contractor_headers(user_id) if user_id else CONTRACTOR
    return get_success_data(api_client.execute_checklist(checklist_id, headers))


def verify_checklist(checklist_id: str, user_id: str = None) -> dict:
    headers = make_cx_authority_headers(user_id) if user_id else CXA
    return get_success_data(api_client.verify_checklist(checklist_id, headers))


def get_checklist(checklist_id: str) -> dict:
    return get_success_data(api_client.get_prefunctional_checklist(checklist_id, CXA))


def create_issue(project_id: str, severity: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_issue(
            create_issue_payload(project_id, severity, **overrides), CXA
        )
    )


def get_issue(issue_id: str) -> dict:
    return get_success_data(api_client.get_issue(issue_id, CXA))


def propose_resolution(issue_id: str, text: str = "Corrective action proposed") -> dict:
    return get_success_data(
        api_client.propose_resolution(issue_id, {"proposed_resolution": text}, CONTRACTOR)
    )


def verify_closure(issue_id: str, closure_note: str = "Correction witnessed", **extra) -> dict:
    payload = {"closure_note": closure_note}
    payload.update(extra)
    return get_success_data(api_client.verify_closure(issue_id, payload, CXA))


def void_issue(issue_id: str, reason: str = "Raised in error") -> dict:
    return get_success_data(api_client.void_issue(issue_id, {"reason": reason}, CXA))


def create_submittal(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_submittal(create_submittal_payload(project_id, **overrides), DESIGN)
    )


def review_submittal(submittal_id: str, decision: str, comment: str = "Review comment") -> dict:
    return get_success_data(
        api_client.review_submittal(
            submittal_id, review_submittal_payload(decision, comment=comment), CXA
        )
    )


def resubmit_submittal(submittal_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.resubmit_submittal(submittal_id, DESIGN, overrides or {})
    )


def get_submittal(submittal_id: str) -> dict:
    return get_success_data(api_client.get_submittal(submittal_id, CXA))


def schedule_functional_test(
    equipment_id: str, requirement_id: str, scheduled_start: str, scheduled_end: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_functional_test(
            create_functional_test_payload(
                equipment_id, requirement_id, scheduled_start, scheduled_end, **overrides
            ),
            CXA,
        )
    )


def start_test(test_id: str) -> dict:
    return get_success_data(api_client.start_functional_test(test_id, CXA))


def record_test_result(test_id: str, measured_value, user_id: str = None) -> dict:
    headers = make_cx_authority_headers(user_id) if user_id else CXA
    return get_success_data(
        api_client.record_functional_test_result(
            test_id, {"measured_value": measured_value}, headers
        )
    )


def get_test(test_id: str) -> dict:
    return get_success_data(api_client.get_functional_test(test_id, CXA))


def run_functional_test(
    equipment_id: str,
    requirement_id: str,
    measured_value,
    scheduled_start: str,
    scheduled_end: str,
    witness_user_id: str = None,
    **overrides,
) -> dict:
    """Schedule -> start -> record-result in one shot. Returns the completed test."""
    test = schedule_functional_test(
        equipment_id, requirement_id, scheduled_start, scheduled_end, **overrides
    )
    start_test(test["id"])
    return record_test_result(test["id"], measured_value, user_id=witness_user_id)


def create_deferred_test(
    equipment_id: str, requirement_id: str, window_start: str, window_end: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_deferred_test(
            create_deferred_test_payload(
                equipment_id, requirement_id, window_start, window_end, **overrides
            ),
            CXA,
        )
    )


def get_deferred_test(deferred_test_id: str) -> dict:
    return get_success_data(api_client.get_deferred_test(deferred_test_id, CXA))


def plan_deliverable(project_id: str, deliverable_kind: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_closeout_deliverable(
            create_closeout_deliverable_payload(project_id, deliverable_kind, **overrides),
            CONTRACTOR,
        )
    )


def deliver_deliverable(deliverable_id: str, user_id: str = None, **overrides) -> dict:
    headers = make_contractor_headers(user_id) if user_id else CONTRACTOR
    return get_success_data(
        api_client.deliver_closeout_deliverable(
            deliverable_id, deliver_closeout_deliverable_payload(**overrides), headers
        )
    )


def accept_deliverable(deliverable_id: str, user_id: str = None) -> dict:
    headers = make_cx_authority_headers(user_id) if user_id else CXA
    return get_success_data(
        api_client.accept_closeout_deliverable(
            deliverable_id, {"attestation_note": "Reviewed and accepted"}, headers
        )
    )


def create_accepted_deliverable(project_id: str, deliverable_kind: str, **overrides) -> dict:
    """Plan -> deliver -> accept. Delivery uses the contractor, acceptance the CxA."""
    attendee_count = overrides.pop("attendee_count", 0)
    duration_minutes = overrides.pop("duration_minutes", 0)
    deliverable = plan_deliverable(project_id, deliverable_kind, **overrides)
    deliver_deliverable(
        deliverable["id"],
        attendee_count=attendee_count,
        duration_minutes=duration_minutes,
    )
    return accept_deliverable(deliverable["id"])


def get_deliverable(deliverable_id: str) -> dict:
    return get_success_data(api_client.get_closeout_deliverable(deliverable_id, CXA))


def create_credit(project_id: str, required_evidence_count: int, max_points: float, **overrides) -> dict:
    return get_success_data(
        api_client.create_certification_credit(
            create_certification_credit_payload(
                project_id, required_evidence_count, max_points, **overrides
            ),
            CXA,
        )
    )


def attach_evidence(credit_id: str, evidence_type: str, evidence_ref_id: str) -> dict:
    return get_success_data(
        api_client.attach_credit_evidence(
            credit_id, attach_credit_evidence_payload(evidence_type, evidence_ref_id), CXA
        )
    )


def get_credit(credit_id: str) -> dict:
    return get_success_data(api_client.get_certification_credit(credit_id, CXA))


def submit_credit(credit_id: str, expected_project_version: int) -> dict:
    return get_success_data(
        api_client.submit_certification_credit(
            credit_id, {"expected_project_version": expected_project_version}, CXA
        )
    )


def create_energy_baseline(project_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_energy_baseline(
            create_energy_baseline_payload(project_id, **overrides), CXA
        )
    )


def record_post_period(baseline_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.record_post_period(baseline_id, record_post_period_payload(**overrides), CXA)
    )


def get_baseline(baseline_id: str) -> dict:
    return get_success_data(api_client.get_energy_baseline(baseline_id, CXA))


def advance_phase(project_id: str, target_phase: str) -> dict:
    return get_success_data(
        api_client.advance_phase(project_id, {"target_phase": target_phase}, CXA)
    )


def list_issues(**params) -> tuple:
    """Returns (rows, meta) for the issue log."""
    response = api_client.list_issues(CXA, params=params)
    body = response.json()
    assert response.status_code == 200, f"issue list failed: {response.text}"
    return body["data"], body["meta"]


# --------------------------------------------------------------------------
# Tier 1 — state progression on one entity
# --------------------------------------------------------------------------


def create_verified_checklist(
    equipment_id: str,
    item_code: str = "PFC-01",
    description: str = "Filters installed and clean",
    is_safety_critical: bool = False,
    executor_user_id: str = None,
    verifier_user_id: str = None,
) -> dict:
    """Open a checklist, append one item, record it PASS, execute and verify.

    The executor and the verifier are deliberately distinct operator ids so the
    segregation-of-duties rule is satisfied.
    """
    checklist = create_checklist(equipment_id)
    add_item(
        checklist["id"],
        item_code=item_code,
        description=description,
        is_safety_critical=is_safety_critical,
    )
    record_item(checklist["id"], item_code=item_code, result="PASS", user_id=executor_user_id)
    execute_checklist(checklist["id"], user_id=executor_user_id)
    return verify_checklist(checklist["id"], user_id=verifier_user_id)


def create_executed_checklist(
    equipment_id: str,
    item_code: str = "PFC-01",
    is_safety_critical: bool = False,
    result: str = "PASS",
    executor_user_id: str = None,
) -> dict:
    """Open a checklist, append one item, record it and sign it off as EXECUTED."""
    checklist = create_checklist(equipment_id)
    add_item(checklist["id"], item_code=item_code, is_safety_critical=is_safety_critical)
    record_item(checklist["id"], item_code=item_code, result=result, user_id=executor_user_id)
    return execute_checklist(checklist["id"], user_id=executor_user_id)


# --------------------------------------------------------------------------
# Tier 2 — engagement + requirement + plan + equipment preambles
# --------------------------------------------------------------------------


def setup_project_with_approved_plan(
    project_overrides: dict = None, requirement_overrides: dict = None
) -> dict:
    """Engagement + one APPROVED requirement + an APPROVED plan pinning it.

    Returns {"project", "requirement", "plan"}.
    """
    project = create_project(**(project_overrides or {}))
    requirement = create_approved_requirement(
        project["id"], **(requirement_overrides or {})
    )
    plan = create_approved_plan(project["id"])
    return {"project": project, "requirement": requirement, "plan": plan}


def setup_prefunctional_verified_equipment(
    project_id: str, started_up: bool = True, **equipment_overrides
) -> dict:
    """Register equipment, install it, verify its checklist and optionally start it up.

    Returns {"equipment", "checklist"} with the equipment freshly re-read.
    """
    equipment = register_equipment(project_id, **equipment_overrides)
    set_install_status(equipment["id"], "INSTALLED")
    checklist = create_verified_checklist(equipment["id"])
    if started_up:
        set_install_status(equipment["id"], "STARTED_UP")
    return {"equipment": get_equipment(equipment["id"]), "checklist": checklist}


def setup_ready_equipment_on_pinned_plan(
    project_overrides: dict = None,
    requirement_overrides: dict = None,
    equipment_overrides: dict = None,
    started_up: bool = True,
) -> dict:
    """The most common preamble: approved pinned plan + one test-ready unit.

    Returns {"project", "requirement", "plan", "equipment", "checklist"}.
    """
    base = setup_project_with_approved_plan(project_overrides, requirement_overrides)
    unit = setup_prefunctional_verified_equipment(
        base["project"]["id"], started_up=started_up, **(equipment_overrides or {})
    )
    base.update(unit)
    return base


# --------------------------------------------------------------------------
# Tier 3 — full lifecycle shortcuts
# --------------------------------------------------------------------------


def setup_submittal_at_review_round_three(project_overrides: dict = None) -> dict:
    """Two full review/resubmit cycles leave the submittal RECEIVED at round 3.

    Returns {"project", "submittal"} where submittal is the row after the second
    resubmit.
    """
    project = create_project(**(project_overrides or {}))
    submittal = create_submittal(
        project["id"], title="AHU schedule", submittal_kind="DESIGN_DOCUMENT"
    )
    review_submittal(
        submittal["id"], "REVISE_AND_RESUBMIT", "Round 1 - coil capacity unsupported"
    )
    resubmit_submittal(submittal["id"])
    review_submittal(
        submittal["id"], "REVISE_AND_RESUBMIT", "Round 2 - still unsupported"
    )
    submittal = resubmit_submittal(submittal["id"])
    return {"project": project, "submittal": submittal}


def setup_gold_credit_on_verified_equipment(
    project_overrides: dict = None,
    requirement_overrides: dict = None,
    equipment_overrides: dict = None,
    required_evidence_count: int = 4,
    max_points: float = 6.0,
    credit_code: str = "EA-CX-ENHANCED",
    started_up: bool = True,
    accept_training: bool = True,
) -> dict:
    """Four fresh evidence rows on one credit: equipment, checklist, manual, training.

    With ``accept_training=False`` the training deliverable is left in
    ``DELIVERED`` — PRD 3.7 makes ``ACCEPTED`` terminal and reaches ``RETURNED``
    only from ``DELIVERED``, so a test that needs to return the deliverable must
    stop short of acceptance.  PRD 3.8 then makes that row's ``TRAINING``
    evidence stale on creation, leaving three fresh rows and one stale row.

    Returns {"project", "requirement", "plan", "equipment", "checklist",
    "manual_deliverable", "training_deliverable", "credit",
    "evidence_equipment", "evidence_checklist", "evidence_manual",
    "evidence_training"}.
    """
    base = setup_ready_equipment_on_pinned_plan(
        project_overrides, requirement_overrides, equipment_overrides, started_up=started_up
    )
    project_id = base["project"]["id"]
    equipment_id = base["equipment"]["id"]

    manual = plan_deliverable(
        project_id,
        "SYSTEMS_MANUAL_SECTION",
        title="Systems manual section",
        equipment_id=equipment_id,
    )
    deliver_deliverable(manual["id"], attendee_count=0, duration_minutes=0)
    manual = accept_deliverable(manual["id"])

    training = plan_deliverable(
        project_id,
        "TRAINING_SESSION",
        title="Operator training",
        equipment_id=equipment_id,
        required_attendee_count=5,
    )
    training = deliver_deliverable(
        training["id"], attendee_count=5, duration_minutes=120
    )
    if accept_training:
        training = accept_deliverable(training["id"])

    credit = create_credit(
        project_id, required_evidence_count, max_points, credit_code=credit_code
    )
    evidence_equipment = attach_evidence(
        credit["id"], "EQUIPMENT_VERIFICATION", equipment_id
    )
    evidence_checklist = attach_evidence(
        credit["id"], "CHECKLIST", base["checklist"]["id"]
    )
    evidence_manual = attach_evidence(credit["id"], "MANUAL_SECTION", manual["id"])
    evidence_training = attach_evidence(credit["id"], "TRAINING", training["id"])

    base.update(
        {
            "manual_deliverable": manual,
            "training_deliverable": training,
            "credit": get_credit(credit["id"]),
            "evidence_equipment": evidence_equipment,
            "evidence_checklist": evidence_checklist,
            "evidence_manual": evidence_manual,
            "evidence_training": evidence_training,
        }
    )
    return base


def setup_submitted_gold_credit_with_test_in_progress() -> dict:
    """A SUBMITTED GOLD credit on a LIFE_SAFETY unit whose test is IN_PROGRESS.

    Returns the dict from setup_gold_credit_on_verified_equipment plus
    {"test", "submitted_credit"}.
    """
    base = setup_gold_credit_on_verified_equipment(
        project_overrides={
            "name": "Summit Cx",
            "building_name": "Summit Tower",
            "certification_target": "STANDARD",
            "witness_capacity": 1,
        },
        requirement_overrides={
            "metric_key": "ALARM_AUDIBILITY_DBA",
            "criticality": "LIFE_SAFETY",
        },
        equipment_overrides={
            "tag": "FA-2",
            "system_type": "FIRE_ALARM",
            "criticality": "LIFE_SAFETY",
            "contract_value_cents": 1_000_005,
            "weight_units": 10,
        },
    )
    test = schedule_functional_test(
        base["equipment"]["id"],
        base["requirement"]["id"],
        "2026-09-10T09:00:00Z",
        "2026-09-10T11:00:00Z",
        script_code="FPT-FA-01",
    )
    start_test(test["id"])
    submitted = submit_credit(
        base["credit"]["id"], project_version(base["project"]["id"])
    )
    base.update({"test": get_test(test["id"]), "submitted_credit": submitted})
    return base


def setup_frozen_project_with_blocked_seasonal_test() -> dict:
    """An S1 deficiency freezes the engagement and blocks its planned seasonal test.

    Returns {"project", "requirement", "plan", "equipment", "checklist",
    "deferred_test", "issue", "frozen_project"}.
    """
    base = setup_ready_equipment_on_pinned_plan(
        project_overrides={"name": "Lakeside Cx", "building_name": "Lakeside Center"},
        requirement_overrides={"metric_key": "CHW_DELTA_T_F"},
        equipment_overrides={
            "tag": "CHW-2",
            "system_type": "CHILLER",
            "criticality": "CRITICAL",
        },
        started_up=False,
    )
    deferred = create_deferred_test(
        base["equipment"]["id"],
        base["requirement"]["id"],
        "2026-11-01T00:00:00Z",
        "2026-12-01T00:00:00Z",
        season="COOLING",
    )
    issue = create_issue(
        base["project"]["id"],
        "S1",
        origin="DESIGN_REVIEW",
        description="Condenser relief path missing",
        equipment_id=base["equipment"]["id"],
    )
    frozen = get_project(base["project"]["id"])
    propose_resolution(issue["id"], "Relief path added per detail 7/M501")
    base.update(
        {
            "deferred_test": get_deferred_test(deferred["id"]),
            "issue": issue,
            "frozen_project": frozen,
        }
    )
    return base


def setup_two_verified_checklists() -> dict:
    """Two installed units with VERIFIED checklists, weights 10 and 5.

    Returns {"project", "equipment_a", "checklist_a", "equipment_b",
    "checklist_b"}.
    """
    project = create_project(name="Vantage Cx", building_name="Vantage Point")
    unit_a = setup_prefunctional_verified_equipment(
        project["id"], started_up=False, tag="AHU-9", weight_units=10
    )
    unit_b = setup_prefunctional_verified_equipment(
        project["id"],
        started_up=False,
        tag="CHW-3",
        system_type="CHILLER",
        contract_value_cents=500_000,
        weight_units=5,
    )
    return {
        "project": project,
        "equipment_a": unit_a["equipment"],
        "checklist_a": unit_a["checklist"],
        "equipment_b": unit_b["equipment"],
        "checklist_b": unit_b["checklist"],
    }


def setup_two_ready_units_with_occupied_window(
    witness_capacity: int = 1,
    occupied_start: str = "2026-09-10T09:00:00Z",
    occupied_end: str = "2026-09-10T11:00:00Z",
) -> dict:
    """Two STARTED_UP, PREFUNCTIONAL_VERIFIED units; the first one holds a window.

    Returns {"project", "requirement", "plan", "equipment_a", "equipment_b",
    "occupying_test"}.
    """
    base = setup_project_with_approved_plan(
        project_overrides={
            "name": "Belmont Cx",
            "building_name": "Belmont Works",
            "witness_capacity": witness_capacity,
        }
    )
    project_id = base["project"]["id"]
    unit_a = setup_prefunctional_verified_equipment(project_id, tag="AHU-7")
    unit_b = setup_prefunctional_verified_equipment(project_id, tag="AHU-8")
    occupying = schedule_functional_test(
        unit_a["equipment"]["id"],
        base["requirement"]["id"],
        occupied_start,
        occupied_end,
        script_code="FPT-AHU-01",
    )
    base.update(
        {
            "equipment_a": unit_a["equipment"],
            "equipment_b": unit_b["equipment"],
            "occupying_test": occupying,
        }
    )
    return base


# --------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# --------------------------------------------------------------------------


def setup_three_holds_on_life_safety_unit() -> dict:
    """S3, S2 and S1 deficiencies on a 1000005-cent LIFE_SAFETY unit.

    The three frozen holds are 7500, 30000 and 75000 cents.
    Returns {"project", "equipment", "issue_s3", "issue_s2", "issue_s1"}.
    """
    project = create_project(name="Harbour Cx", building_name="Harbour House")
    equipment = register_equipment(
        project["id"],
        tag="FA-1",
        system_type="FIRE_ALARM",
        criticality="LIFE_SAFETY",
        contract_value_cents=1_000_005,
        weight_units=10,
    )
    issue_s3 = create_issue(
        project["id"],
        "S3",
        description="Annunciator legend incomplete",
        equipment_id=equipment["id"],
    )
    issue_s2 = create_issue(
        project["id"],
        "S2",
        description="Battery calculation not submitted",
        equipment_id=equipment["id"],
    )
    issue_s1 = create_issue(
        project["id"],
        "S1",
        description="Smoke detector spacing violates code",
        equipment_id=equipment["id"],
    )
    return {
        "project": project,
        "equipment": equipment,
        "issue_s3": issue_s3,
        "issue_s2": issue_s2,
        "issue_s1": issue_s1,
    }


def setup_project_at_severity_index_32() -> dict:
    """One S2 and one S3 deficiency put the index at 32.00 and the posture RESTRICTED.

    Returns {"project", "equipment", "issue_s2", "issue_s3", "after_s2", "after_s3"}.
    """
    project = create_project(name="Aster Cx", building_name="Aster Building")
    equipment = register_equipment(
        project["id"],
        tag="LTG-1",
        system_type="LIGHTING",
        criticality="CRITICAL",
        contract_value_cents=1_000_000,
        weight_units=10,
    )
    issue_s2 = create_issue(
        project["id"],
        "S2",
        description="Daylight sensor placement wrong",
        equipment_id=equipment["id"],
    )
    after_s2 = get_project(project["id"])
    issue_s3 = create_issue(
        project["id"],
        "S3",
        description="Zone schedule mislabelled",
        equipment_id=equipment["id"],
    )
    after_s3 = get_project(project["id"])
    return {
        "project": project,
        "equipment": equipment,
        "issue_s2": issue_s2,
        "issue_s3": issue_s3,
        "after_s2": after_s2,
        "after_s3": after_s3,
    }


def setup_frozen_project_with_incomplete_credit() -> dict:
    """A FROZEN engagement whose credit is also short of fresh evidence.

    Returns {"project", "requirement", "plan", "equipment", "checklist",
    "credit", "issue", "frozen_project"}.
    """
    base = setup_ready_equipment_on_pinned_plan(
        project_overrides={
            "name": "Foundry Cx",
            "building_name": "Foundry Block",
            "certification_target": "STANDARD",
        },
        requirement_overrides={"metric_key": "OA_FRACTION_PCT", "criticality": "STANDARD"},
        equipment_overrides={"tag": "AHU-3"},
        started_up=False,
    )
    credit = create_credit(
        base["project"]["id"], 4, 6.0, credit_code="EA-CX-ENHANCED"
    )
    attach_evidence(credit["id"], "CHECKLIST", base["checklist"]["id"])
    issue = create_issue(
        base["project"]["id"],
        "S1",
        description="Smoke control sequence not coordinated",
    )
    base.update(
        {
            "credit": get_credit(credit["id"]),
            "issue": issue,
            "frozen_project": get_project(base["project"]["id"]),
        }
    )
    return base


def setup_credit_with_stale_plan_pin() -> dict:
    """An evidence-sufficient credit on an engagement whose plan pin went stale.

    Returns {"project", "requirement", "plan", "equipment", "checklist",
    "credit", "revision", "approved_plan"}.
    """
    base = setup_ready_equipment_on_pinned_plan(
        project_overrides={
            "name": "Orchard Cx",
            "building_name": "Orchard House",
            "certification_target": "STANDARD",
        },
        equipment_overrides={
            "tag": "ELV-1",
            "system_type": "ELEVATOR",
        },
        started_up=False,
    )
    credit = create_credit(
        base["project"]["id"], 1, 2.0, credit_code="EA-CX-FUNDAMENTAL"
    )
    attach_evidence(credit["id"], "CHECKLIST", base["checklist"]["id"])
    revision = get_success_data(
        api_client.revise_owner_requirement(
            base["requirement"]["id"],
            {"target_value": 11_000, "tolerance_pct": 4, "criticality": "CRITICAL"},
            OWNER,
        )
    )
    base.update(
        {
            "credit": get_credit(credit["id"]),
            "revision": revision,
            "approved_plan": get_success_data(
                api_client.get_cx_plan(base["plan"]["id"], CXA)
            ),
        }
    )
    return base


def setup_dual_variant_completion_project() -> dict:
    """Two units whose PROVISIONAL and FINAL completion scores diverge (85.00 vs 60.00).

    Unit A (weight 10) carries a PASSED_WITH_EXCEPTIONS test and an ACCEPTED
    manual section; unit B (weight 5) carries only a PLANNED seasonal test.
    Returns {"project", "requirement", "plan", "equipment_a", "test_a",
    "deliverable_a", "equipment_b", "deferred_test_b"}.
    """
    base = setup_project_with_approved_plan(
        project_overrides={
            "name": "Northgate Cx",
            "building_name": "Northgate Tower",
            "certification_target": "STANDARD",
            "witness_capacity": 1,
        }
    )
    project_id = base["project"]["id"]

    unit_a = setup_prefunctional_verified_equipment(project_id, tag="AHU-1", weight_units=10)
    test_a = run_functional_test(
        unit_a["equipment"]["id"],
        base["requirement"]["id"],
        10_600,
        "2026-09-10T09:00:00Z",
        "2026-09-10T11:00:00Z",
    )
    deliverable_a = create_accepted_deliverable(
        project_id,
        "SYSTEMS_MANUAL_SECTION",
        title="AHU-1 systems manual section",
        equipment_id=unit_a["equipment"]["id"],
    )

    unit_b = setup_prefunctional_verified_equipment(
        project_id,
        started_up=False,
        tag="CHW-1",
        system_type="CHILLER",
        contract_value_cents=500_000,
        weight_units=5,
    )
    deferred_b = create_deferred_test(
        unit_b["equipment"]["id"],
        base["requirement"]["id"],
        "2026-11-01T00:00:00Z",
        "2026-12-01T00:00:00Z",
        season="COOLING",
    )

    base.update(
        {
            "equipment_a": get_equipment(unit_a["equipment"]["id"]),
            "checklist_a": unit_a["checklist"],
            "test_a": test_a,
            "deliverable_a": deliverable_a,
            "equipment_b": get_equipment(unit_b["equipment"]["id"]),
            "checklist_b": unit_b["checklist"],
            "deferred_test_b": deferred_b,
        }
    )
    return base


def setup_retro_project_with_post_period(
    certification_target: str = "STANDARD", post_kwh=410_000, post_hdd=2_880, **baseline_overrides
) -> dict:
    """A RETRO_COMMISSIONING measure with both savings variants computed.

    Returns {"project", "baseline"}.
    """
    project = create_project(
        name="Elmwood Retro-Cx",
        building_name="Elmwood Plaza",
        project_type="RETRO_COMMISSIONING",
        contract_value_cents=40_000_000,
        certification_target=certification_target,
    )
    baseline = create_energy_baseline(project["id"], **baseline_overrides)
    baseline = record_post_period(baseline["id"], post_kwh=post_kwh, post_hdd=post_hdd)
    return {"project": project, "baseline": baseline}


# --------------------------------------------------------------------------
# Tier 5 — terminal / acceptance-stage setups
# --------------------------------------------------------------------------


def setup_project_in_acceptance_phase(with_functional_and_closeout: bool = True) -> dict:
    """Walk an engagement PLANNING -> ... -> ACCEPTANCE with one equipment unit.

    When `with_functional_and_closeout` is true the unit also carries a PASSED
    functional test and an ACCEPTED closeout deliverable, so the FINAL variant of
    the completion score reads 100.00; otherwise only the pre-functional stage is
    complete and the FINAL variant reads 30.00.
    Returns {"project", "requirement", "plan", "equipment", "checklist", "test",
    "deliverable"}.
    """
    project = create_project(name="Acceptance Cx", building_name="Acceptance Block")
    requirement = create_approved_requirement(project["id"])
    advance_phase(project["id"], "DESIGN")
    plan = create_approved_plan(project["id"])
    advance_phase(project["id"], "CONSTRUCTION")

    equipment = register_equipment(project["id"], tag="AHU-LS")
    set_install_status(equipment["id"], "INSTALLED")
    checklist = create_verified_checklist(equipment["id"])
    advance_phase(project["id"], "FUNCTIONAL_TESTING")

    test = None
    deliverable = None
    if with_functional_and_closeout:
        set_install_status(equipment["id"], "STARTED_UP")
        test = run_functional_test(
            equipment["id"],
            requirement["id"],
            10_000,
            "2026-09-23T09:00:00Z",
            "2026-09-23T11:00:00Z",
        )
        deliverable = create_accepted_deliverable(
            project["id"],
            "SYSTEMS_MANUAL_SECTION",
            title="AHU manual section",
            equipment_id=equipment["id"],
        )
    advance_phase(project["id"], "ACCEPTANCE")

    return {
        "project": get_project(project["id"]),
        "requirement": requirement,
        "plan": plan,
        "equipment": get_equipment(equipment["id"]),
        "checklist": checklist,
        "test": test,
        "deliverable": deliverable,
    }


def setup_failed_life_safety_test_with_passing_peer() -> dict:
    """A FAILED LIFE_SAFETY test raising an S1 issue, plus a PASSED test on a peer unit.

    Returns {"project", "requirement", "plan", "equipment_a", "equipment_b",
    "failed_test", "passed_peer_test", "issue"}.
    """
    base = setup_project_with_approved_plan(
        project_overrides={
            "name": "Retest Cx",
            "building_name": "Retest Block",
            "witness_capacity": 1,
        },
        requirement_overrides={
            "metric_key": "ALARM_AUDIBILITY_DBA",
            "criticality": "LIFE_SAFETY",
        },
    )
    project_id = base["project"]["id"]
    unit_a = setup_prefunctional_verified_equipment(
        project_id,
        tag="FA-RT",
        system_type="FIRE_ALARM",
        criticality="LIFE_SAFETY",
    )
    unit_b = setup_prefunctional_verified_equipment(project_id, tag="AHU-RT")

    peer_test = run_functional_test(
        unit_b["equipment"]["id"],
        base["requirement"]["id"],
        10_000,
        "2026-09-19T09:00:00Z",
        "2026-09-19T11:00:00Z",
    )
    failed_test = run_functional_test(
        unit_a["equipment"]["id"],
        base["requirement"]["id"],
        8_000,
        "2026-09-18T09:00:00Z",
        "2026-09-18T11:00:00Z",
        script_code="FPT-FA-01",
    )
    rows, _ = list_issues(equipment_id=unit_a["equipment"]["id"], origin="FUNCTIONAL")
    assert len(rows) == 1, f"Setup expected exactly one FUNCTIONAL issue, got {rows}"
    issue = rows[0]
    propose_resolution(issue["id"], "Additional notification appliances added")

    base.update(
        {
            "equipment_a": get_equipment(unit_a["equipment"]["id"]),
            "equipment_b": get_equipment(unit_b["equipment"]["id"]),
            "failed_test": failed_test,
            "passed_peer_test": peer_test,
            "issue": get_issue(issue["id"]),
        }
    )
    return base


def setup_deferred_issue_with_seasonal_test(
    window_start: str = "2026-08-05T00:00:00Z",
    window_end: str = "2026-08-10T00:00:00Z",
) -> dict:
    """An S2 deficiency deferred against a PLANNED seasonal test on the same unit.

    Returns {"project", "requirement", "plan", "equipment", "issue",
    "deferred_test"}.
    """
    base = setup_project_with_approved_plan(
        project_overrides={"name": "Season Cx", "building_name": "Season Block"},
        requirement_overrides={"metric_key": "HEATING_CAPACITY_MBH"},
    )
    equipment = register_equipment(
        base["project"]["id"], tag="BLR-SE", system_type="BOILER"
    )
    set_install_status(equipment["id"], "INSTALLED")
    issue = create_issue(
        base["project"]["id"],
        "S2",
        origin="PREFUNCTIONAL",
        description="Heating capacity unproven",
        equipment_id=equipment["id"],
    )
    deferred = create_deferred_test(
        equipment["id"],
        base["requirement"]["id"],
        window_start,
        window_end,
        season="HEATING",
        issue_id=issue["id"],
    )
    issue = get_success_data(
        api_client.defer_issue(
            issue["id"], {"deferral_reason": "Deferred to the heating season window"}, OWNER
        )
    )
    base.update(
        {
            "equipment": get_equipment(equipment["id"]),
            "issue": issue,
            "deferred_test": get_deferred_test(deferred["id"]),
        }
    )
    return base
