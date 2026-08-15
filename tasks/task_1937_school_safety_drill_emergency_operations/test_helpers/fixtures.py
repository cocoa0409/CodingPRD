"""Composite setup helpers for the School Safety Drills API tests.

Every helper builds preconditions from scratch using only PRD-declared
endpoints. Each test runs against a freshly restarted server: an empty
database and the logical clock at 2026-08-01T00:00:00Z.

Setup calls use get_success_data() so precondition failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_accommodation_plan_payload,
    create_aar_payload,
    create_compliance_report_payload,
    create_corrective_action_payload,
    create_drill_payload,
    create_eop_payload,
    create_release_payload,
    create_requirement_payload,
    create_roster_entry_payload,
    create_site_payload,
    create_site_plan_payload,
    create_walkthrough_completion_payload,
    create_walkthrough_payload,
)
from .test_users import (
    TEST_USERS,
    make_officer_headers,
    make_principal_headers,
)

COORD_HEADERS = TEST_USERS["coordinator_headers"]
OFFICER_HEADERS = TEST_USERS["officer_headers"]
PRINCIPAL_HEADERS = TEST_USERS["principal_headers"]
RESPONDER_HEADERS = TEST_USERS["responder_headers"]
AUDITOR_HEADERS = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str) -> None:
    """Advance the server logical clock (fires the system sweep)."""
    get_success_data(api_client.set_clock(to_iso8601, COORD_HEADERS), 200)


# ---------------------------------------------------------------------------
# Tier 1: single-entity creators
# ---------------------------------------------------------------------------

def create_site(name="Ridgeview Elementary",
                enrollment_count=500,
                academic_year_start=TEST_DEFAULTS["YEAR_START"],
                academic_year_end=TEST_DEFAULTS["YEAR_END"]) -> dict:
    resp = api_client.create_site(
        create_site_payload(name=name, enrollment_count=enrollment_count,
                            academic_year_start=academic_year_start,
                            academic_year_end=academic_year_end),
        COORD_HEADERS)
    return get_success_data(resp, 201)


def create_drill_requirement(site_id, drill_type="FIRE", required_per_year=2,
                             min_spacing_days=20, target_evac_seconds=300,
                             notes=None) -> dict:
    payload = create_requirement_payload(
        site_id=site_id, drill_type=drill_type,
        required_per_year=required_per_year, min_spacing_days=min_spacing_days,
        target_evac_seconds=target_evac_seconds)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_drill_requirement(payload, COORD_HEADERS), 201)


def publish_site_plan(site_id, document_title="Floor Plan 2026",
                      issued_on="2026-07-01", review_by_date="2027-01-15",
                      coverage_tags=("FLOOR_PLANS", "ACCESS_POINTS")) -> dict:
    resp = api_client.create_site_plan_document(
        create_site_plan_payload(site_id=site_id, document_title=document_title,
                                 issued_on=issued_on, review_by_date=review_by_date,
                                 coverage_tags=list(coverage_tags)),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def schedule_walkthrough(site_id, agency="FIRE", scheduled_date="2026-07-20") -> dict:
    resp = api_client.create_walkthrough(
        create_walkthrough_payload(site_id=site_id, agency=agency,
                                   scheduled_date=scheduled_date),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def complete_walkthrough(walkthrough_id, completed_date="2026-07-20",
                         findings_summary="Exits and assembly areas verified",
                         recommendations_count=0) -> dict:
    resp = api_client.complete_walkthrough(
        walkthrough_id,
        create_walkthrough_completion_payload(
            completed_date=completed_date, findings_summary=findings_summary,
            recommendations_count=recommendations_count),
        RESPONDER_HEADERS)
    return get_success_data(resp, 200)


def create_eop(site_id, title="EOP 2026", plan_version_label="v1",
               content_summary="Evacuation and lockdown procedures",
               review_due_date="2027-08-01") -> dict:
    resp = api_client.create_eop(
        create_eop_payload(site_id=site_id, title=title,
                           plan_version_label=plan_version_label,
                           content_summary=content_summary,
                           review_due_date=review_due_date),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def submit_eop(eop_id, headers=None) -> dict:
    return get_success_data(api_client.submit_eop(eop_id, headers or OFFICER_HEADERS), 200)


def decide_eop(eop_id, decision, return_reason=None) -> dict:
    payload = {"decision": decision}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return get_success_data(api_client.decide_eop(eop_id, payload, COORD_HEADERS), 200)


def activate_eop(eop_id) -> dict:
    return get_success_data(api_client.activate_eop(eop_id, COORD_HEADERS), 200)


# ---------------------------------------------------------------------------
# Tier 2: site hierarchy composites
# ---------------------------------------------------------------------------

def setup_site_with_requirement(site_name="Ridgeview Elementary",
                                enrollment_count=500,
                                requirement_overrides=None) -> dict:
    """Site + one FIRE drill requirement. Returns {"site", "requirement"}."""
    site = create_site(name=site_name, enrollment_count=enrollment_count)
    requirement = create_drill_requirement(site["id"], **(requirement_overrides or {}))
    return {"site": site, "requirement": requirement}


def setup_active_eop_site(site_name="Ridgeview Elementary", enrollment_count=500,
                          requirement_overrides=None, extra_requirements=None,
                          walkthrough_agency="FIRE",
                          walkthrough_scheduled_date="2026-07-20",
                          walkthrough_completed_date="2026-07-20",
                          site_plan_overrides=None, eop_overrides=None) -> dict:
    """Site + FIRE requirement (+ optional extra requirements) + CURRENT site
    plan + COMPLETED in-window walkthrough + EOP walked
    DRAFT -> SUBMITTED -> APPROVED -> ACTIVE.

    Returns {"site", "requirement", "requirements", "site_plan",
             "walkthrough", "eop"}.
    """
    site = create_site(name=site_name, enrollment_count=enrollment_count)
    requirement = create_drill_requirement(site["id"], **(requirement_overrides or {}))
    requirements = [requirement]
    for extra in (extra_requirements or []):
        requirements.append(create_drill_requirement(site["id"], **extra))
    site_plan = publish_site_plan(site["id"], **(site_plan_overrides or {}))
    walkthrough = schedule_walkthrough(site["id"], agency=walkthrough_agency,
                                       scheduled_date=walkthrough_scheduled_date)
    walkthrough = complete_walkthrough(walkthrough["id"],
                                       completed_date=walkthrough_completed_date)
    eop = create_eop(site["id"], **(eop_overrides or {}))
    submit_eop(eop["id"])
    decide_eop(eop["id"], "APPROVE")
    eop = activate_eop(eop["id"])
    return {"site": site, "requirement": requirement, "requirements": requirements,
            "site_plan": site_plan, "walkthrough": walkthrough, "eop": eop}


# ---------------------------------------------------------------------------
# Tier 3: drill lifecycle shortcuts
# ---------------------------------------------------------------------------

def schedule_drill(site_id, drill_type="FIRE", scheduled_date="2026-09-15",
                   scheduled_start_time="09:00", duration_minutes=30,
                   announcement_mode="ANNOUNCED") -> dict:
    resp = api_client.create_drill_event(
        create_drill_payload(site_id=site_id, drill_type=drill_type,
                             scheduled_date=scheduled_date,
                             scheduled_start_time=scheduled_start_time,
                             duration_minutes=duration_minutes,
                             announcement_mode=announcement_mode),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def start_drill_on(drill_id, date, at_time="09:00") -> dict:
    """Set the logical clock to dateTat_time:00Z, then start the drill."""
    set_clock(f"{date}T{at_time}:00Z")
    return get_success_data(api_client.start_drill(drill_id, OFFICER_HEADERS), 200)


def complete_drill_at(drill_id, date, at_time="09:04", completion_notes=None) -> dict:
    """Set the logical clock to dateTat_time:00Z, then complete the drill."""
    set_clock(f"{date}T{at_time}:00Z")
    payload = {}
    if completion_notes is not None:
        payload["completion_notes"] = completion_notes
    return get_success_data(api_client.complete_drill(drill_id, payload,
                                                      OFFICER_HEADERS), 200)


def run_completed_drill(site_id, drill_type="FIRE", scheduled_date="2026-09-15",
                        start_time="09:00", complete_time="09:04",
                        duration_minutes=30, announcement_mode="ANNOUNCED") -> dict:
    """Create a drill, start it on its scheduled date, complete it a few
    minutes later with an empty roster. Requires an ACTIVE plan at the site
    and a configured requirement for the drill type."""
    drill = schedule_drill(site_id, drill_type=drill_type,
                           scheduled_date=scheduled_date,
                           scheduled_start_time=start_time,
                           duration_minutes=duration_minutes,
                           announcement_mode=announcement_mode)
    start_drill_on(drill["id"], scheduled_date, start_time)
    return complete_drill_at(drill["id"], scheduled_date, complete_time)


def add_roster_entry(drill_id, student_ref="stu-1", accommodation_required=False) -> dict:
    resp = api_client.add_roster_entry(
        drill_id,
        create_roster_entry_payload(student_ref=student_ref,
                                    accommodation_required=accommodation_required),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def account_entry(entry_id) -> dict:
    return get_success_data(api_client.account_roster_entry(entry_id, OFFICER_HEADERS), 200)


def unaccount_entry(entry_id, reason=None) -> dict:
    payload = {}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api_client.unaccount_roster_entry(entry_id, payload,
                                                              OFFICER_HEADERS), 200)


def release_entry(entry_id, guardian_name="Jane Doe", released_to_verified=True) -> dict:
    return get_success_data(api_client.release_roster_entry(
        entry_id,
        create_release_payload(guardian_name=guardian_name,
                               released_to_verified=released_to_verified),
        OFFICER_HEADERS), 200)


# ---------------------------------------------------------------------------
# Tier 4: review / corrective-action lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_review(drill_id, findings_summary="Evacuation orderly",
                  overall_rating="MEETS", evacuation_assessment="MET_STANDARD") -> dict:
    resp = api_client.create_after_action_review(
        drill_id,
        create_aar_payload(findings_summary=findings_summary,
                           overall_rating=overall_rating,
                           evacuation_assessment=evacuation_assessment),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def submit_review(review_id, officer_user_id="officer-1") -> dict:
    return get_success_data(api_client.submit_after_action_review(
        review_id, make_officer_headers(officer_user_id)), 200)


def decide_review(review_id, decision, principal_user_id="principal-1",
                  return_reason=None) -> dict:
    payload = {"decision": decision}
    if return_reason is not None:
        payload["return_reason"] = return_reason
    return get_success_data(api_client.decide_after_action_review(
        review_id, payload, make_principal_headers(principal_user_id)), 200)


def create_accepted_review(drill_id, findings_summary="Evacuation orderly",
                           overall_rating="MEETS",
                           evacuation_assessment="MET_STANDARD",
                           officer_user_id="officer-1",
                           principal_user_id="principal-1") -> dict:
    """Create a review, submit it as the officer, ACCEPT it as the principal."""
    review = create_review(drill_id, findings_summary=findings_summary,
                           overall_rating=overall_rating,
                           evacuation_assessment=evacuation_assessment)
    submit_review(review["id"], officer_user_id)
    return decide_review(review["id"], "ACCEPT", principal_user_id)


def create_corrective_action(review_id, description="Replace gate signage",
                             priority="HIGH", due_date="2026-10-15",
                             assignee_name="Facilities Lead") -> dict:
    resp = api_client.create_corrective_action(
        review_id,
        create_corrective_action_payload(description=description,
                                         priority=priority, due_date=due_date,
                                         assignee_name=assignee_name),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def submit_ca_verification(action_id, evidence_note="Evidence attached") -> dict:
    return get_success_data(api_client.submit_ca_verification(
        action_id, {"evidence_note": evidence_note}, OFFICER_HEADERS), 200)


def verify_corrective_action(action_id, decision, note=None) -> dict:
    payload = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.verify_corrective_action(
        action_id, payload, COORD_HEADERS), 200)


def setup_accepted_review_scenario(site_name="Ridgeview Elementary",
                                   enrollment_count=500,
                                   drill_date="2026-09-15",
                                   review_overrides=None,
                                   officer_user_id="officer-1",
                                   principal_user_id="principal-1",
                                   ca_spec=None,
                                   **active_site_kwargs) -> dict:
    """ACTIVE-plan site + one COMPLETED FIRE drill (empty roster) + ACCEPTED
    review. When ca_spec is not None, also opens one corrective action
    ({} uses defaults). Returns the active-site context plus "drill",
    "review", and optionally "action".
    """
    ctx = setup_active_eop_site(site_name=site_name,
                                enrollment_count=enrollment_count,
                                **active_site_kwargs)
    drill = run_completed_drill(ctx["site"]["id"], scheduled_date=drill_date)
    review = create_accepted_review(drill["id"],
                                    officer_user_id=officer_user_id,
                                    principal_user_id=principal_user_id,
                                    **(review_overrides or {}))
    ctx["drill"] = drill
    ctx["review"] = review
    if ca_spec is not None:
        ctx["action"] = create_corrective_action(review["id"], **ca_spec)
    return ctx


def setup_pending_verification_action(evidence_note="Installed", **kwargs) -> dict:
    """Accepted-review scenario plus one corrective action moved
    OPEN -> PENDING_VERIFICATION."""
    ca_spec = kwargs.pop("ca_spec", None)
    ctx = setup_accepted_review_scenario(ca_spec=ca_spec if ca_spec is not None else {},
                                         **kwargs)
    ctx["action"] = submit_ca_verification(ctx["action"]["id"], evidence_note)
    return ctx


# ---------------------------------------------------------------------------
# Accommodation plans and compliance reports
# ---------------------------------------------------------------------------

def create_accommodation_plan(site_id, student_ref="stu-7", need_type="MOBILITY",
                              instructions="Staff-assisted evacuation via ramp route",
                              review_by_date="2027-01-15") -> dict:
    resp = api_client.create_accommodation_plan(
        create_accommodation_plan_payload(site_id=site_id, student_ref=student_ref,
                                          need_type=need_type,
                                          instructions=instructions,
                                          review_by_date=review_by_date),
        OFFICER_HEADERS)
    return get_success_data(resp, 201)


def create_compliance_report(site_id, period_start="2026-08-01",
                             period_end="2027-06-30") -> dict:
    resp = api_client.create_compliance_report(
        create_compliance_report_payload(site_id=site_id,
                                         period_start=period_start,
                                         period_end=period_end),
        COORD_HEADERS)
    return get_success_data(resp, 201)


# ---------------------------------------------------------------------------
# Fetch helpers (list-and-find for resources without a single-GET endpoint)
# ---------------------------------------------------------------------------

def _find_by_id(items, entity_id, what):
    for item in items:
        if item.get("id") == entity_id:
            return item
    raise AssertionError(f"{what} {entity_id} not found in list response")


def get_site(site_id) -> dict:
    return get_success_data(api_client.get_site(site_id, OFFICER_HEADERS), 200)


def get_drill(drill_id) -> dict:
    return get_success_data(api_client.get_drill_event(drill_id, OFFICER_HEADERS), 200)


def get_review(review_id) -> dict:
    return get_success_data(api_client.get_after_action_review(review_id,
                                                               OFFICER_HEADERS), 200)


def get_drill_requirement(site_id, requirement_id) -> dict:
    items = get_success_data(
        api_client.list_drill_requirements(site_id, OFFICER_HEADERS,
                                           params={"limit": 100}), 200)
    return _find_by_id(items, requirement_id, "DrillTypeRequirement")


def get_eop(site_id, eop_id) -> dict:
    items = get_success_data(
        api_client.list_eops(site_id, OFFICER_HEADERS, params={"limit": 100}), 200)
    return _find_by_id(items, eop_id, "EmergencyOperationsPlan")


def get_site_plan_document(site_id, document_id) -> dict:
    items = get_success_data(
        api_client.list_site_plan_documents(site_id, OFFICER_HEADERS,
                                            params={"limit": 100}), 200)
    return _find_by_id(items, document_id, "SitePlanDocument")


def get_walkthrough(site_id, walkthrough_id) -> dict:
    items = get_success_data(
        api_client.list_walkthroughs(site_id, OFFICER_HEADERS,
                                     params={"limit": 100}), 200)
    return _find_by_id(items, walkthrough_id, "FirstResponderWalkthrough")


def get_roster_entry(drill_id, entry_id) -> dict:
    items = get_success_data(
        api_client.list_roster_entries(drill_id, OFFICER_HEADERS,
                                       params={"limit": 100}), 200)
    return _find_by_id(items, entry_id, "RosterEntry")


def get_corrective_action(review_id, action_id) -> dict:
    items = get_success_data(
        api_client.list_corrective_actions(review_id, OFFICER_HEADERS,
                                           params={"limit": 100}), 200)
    return _find_by_id(items, action_id, "CorrectiveAction")


def get_accommodation_plan(site_id, plan_id) -> dict:
    items = get_success_data(
        api_client.list_accommodation_plans(site_id, OFFICER_HEADERS,
                                            params={"limit": 100}), 200)
    return _find_by_id(items, plan_id, "AccommodationPlan")


def get_compliance_report(site_id, report_id) -> dict:
    items = get_success_data(
        api_client.list_compliance_reports(site_id, OFFICER_HEADERS,
                                           params={"limit": 100}), 200)
    return _find_by_id(items, report_id, "ComplianceReport")


def get_type_attainment(report: dict, drill_type: str) -> dict:
    """Locate one drill type's attainment entry inside a report snapshot."""
    for entry in report.get("type_attainments", []):
        if entry.get("drill_type") == drill_type:
            return entry
    raise AssertionError(
        f"No type_attainments entry for {drill_type} in report {report.get('id')}")


__all__ = [
    "COORD_HEADERS", "OFFICER_HEADERS", "PRINCIPAL_HEADERS", "RESPONDER_HEADERS",
    "AUDITOR_HEADERS",
    "set_clock",
    "create_site", "create_drill_requirement", "publish_site_plan",
    "schedule_walkthrough", "complete_walkthrough", "create_eop", "submit_eop",
    "decide_eop", "activate_eop",
    "setup_site_with_requirement", "setup_active_eop_site",
    "schedule_drill", "start_drill_on", "complete_drill_at", "run_completed_drill",
    "add_roster_entry", "account_entry", "unaccount_entry", "release_entry",
    "create_review", "submit_review", "decide_review", "create_accepted_review",
    "create_corrective_action", "submit_ca_verification", "verify_corrective_action",
    "setup_accepted_review_scenario", "setup_pending_verification_action",
    "create_accommodation_plan", "create_compliance_report",
    "get_site", "get_drill", "get_review", "get_drill_requirement", "get_eop",
    "get_site_plan_document", "get_walkthrough", "get_roster_entry",
    "get_corrective_action", "get_accommodation_plan", "get_compliance_report",
    "get_type_attainment",
]
