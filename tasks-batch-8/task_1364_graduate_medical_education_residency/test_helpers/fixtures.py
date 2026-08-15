"""Composite setup helpers.

The harness restarts the server before every test, so every fixture builds its
preconditions from scratch against an empty database using only PRD-declared
endpoints. All helpers use the lenient get_success_data() so a setup failure
surfaces as a clear "Setup failed" message rather than a confusing assertion.

Ownership threading (PRD §2.1): after a Resident row exists, every
Resident-role call on its own records uses make_resident_headers(resident.id).
"""
import itertools
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_BUDGET_CENTS, DEFAULT_POSITIONS, DEFAULT_STIPEND_CENTS,
)
from .factories import (
    create_assignment_payload, create_case_log_payload,
    create_case_requirement_payload, create_citation_payload,
    create_ccc_review_payload, create_complement_payload, create_duty_log_payload,
    create_evaluation_payload, create_moonlighting_payload,
    create_probation_payload, create_program_payload, create_remediation_payload,
    create_resident_payload, create_rotation_payload, create_survey_payload,
    create_year_payload, finalize_ccc_payload, six_ratings,
)
from .test_users import (
    TEST_USERS, make_ccc_chair_headers, make_faculty_headers,
    make_pd_headers, make_resident_headers,
)

DIO = TEST_USERS["dio_headers"]
PD = TEST_USERS["pd_headers"]
PC = TEST_USERS["pc_headers"]
FAC = TEST_USERS["faculty_headers"]
CHAIR = TEST_USERS["ccc_chair_headers"]


def _ok(resp, what):
    data = get_success_data(resp)
    assert isinstance(data, dict) and data.get("id"), \
        f"Setup failed: {what}: {resp.status_code} {resp.text}"
    return data


def _list(resp, what):
    try:
        data, meta = validate_paginated(resp)
    except Exception as exc:  # pragma: no cover - setup clarity
        raise AssertionError(f"Setup failed: {what}: {resp.status_code} {resp.text}") from exc
    return data, meta


# --- Clock -------------------------------------------------------------------

def set_clock(to_iso8601, headers=None):
    resp = api_client.set_clock(to_iso8601, headers or PC)
    assert resp.status_code == 200, f"Setup failed: set_clock: {resp.text}"
    return get_success_data(resp)


# --- Tier 1/2: program, year, blocks, complement, resident --------------------

def make_program(**overrides):
    return _ok(api_client.create_program(create_program_payload(**overrides), DIO),
               "create program")


def make_year(program_id, activate=False, **overrides):
    year = _ok(api_client.create_academic_year(
        create_year_payload(program_id, **overrides), PC), "create year")
    if activate:
        year = _ok(api_client.activate_academic_year(year["id"], PC), "activate year")
    return year


def make_active_year(program_id, **overrides):
    return make_year(program_id, activate=True, **overrides)


def list_blocks(year_id, status=None):
    params = {"academic_year_id": year_id, "limit": 100}
    if status:
        params["status"] = status
    data, meta = _list(api_client.list_schedule_blocks(PC, params=params),
                       "list schedule blocks")
    return data


def get_block(year_id, index):
    """The block with block_index == index (1-based); the list is sorted by
    block_index ascending (PRD §2.3)."""
    blocks = list_blocks(year_id)
    assert len(blocks) >= index, f"expected at least {index} blocks, got {len(blocks)}"
    return blocks[index - 1]


def make_complement(program_id, year_id, pgy_level=1,
                    approved_positions=DEFAULT_POSITIONS,
                    annual_funding_budget_cents=DEFAULT_BUDGET_CENTS,
                    blended_stipend_cents=DEFAULT_STIPEND_CENTS,
                    approve=True):
    comp = _ok(api_client.create_complement(create_complement_payload(
        program_id, year_id, pgy_level=pgy_level,
        approved_positions=approved_positions,
        annual_funding_budget_cents=annual_funding_budget_cents,
        blended_stipend_cents=blended_stipend_cents), PD), "create complement")
    if approve:
        comp = _ok(api_client.submit_complement(comp["id"], PD), "submit complement")
        comp = _ok(api_client.approve_complement(comp["id"], DIO), "approve complement")
    return comp


def make_resident(program_id, year_id, pgy_level=1, activate=False, **overrides):
    res = _ok(api_client.create_resident(create_resident_payload(
        program_id, year_id, pgy_level=pgy_level, **overrides), PC), "create resident")
    if activate:
        res = _ok(api_client.activate_resident(res["id"], PC), "activate resident")
    return res


def make_active_resident(program_id, year_id, pgy_level=1, **overrides):
    return make_resident(program_id, year_id, pgy_level=pgy_level, activate=True, **overrides)


def setup_program_with_active_resident(approved_positions=DEFAULT_POSITIONS,
                                       annual_funding_budget_cents=DEFAULT_BUDGET_CENTS,
                                       blended_stipend_cents=DEFAULT_STIPEND_CENTS,
                                       pgy_level=1, activate_year=True):
    """Program + ACTIVE year + APPROVED complement + one ACTIVE resident.

    Returns dict(program, year, complement, resident).
    """
    program = make_program()
    year = make_year(program["id"], activate=activate_year)
    comp = make_complement(program["id"], year["id"], pgy_level=pgy_level,
                           approved_positions=approved_positions,
                           annual_funding_budget_cents=annual_funding_budget_cents,
                           blended_stipend_cents=blended_stipend_cents)
    resident = make_resident(program["id"], year["id"], pgy_level=pgy_level,
                             activate=True)
    return {"program": program, "year": year, "complement": comp, "resident": resident}


# --- Rotations / assignments --------------------------------------------------

def make_rotation(program_id, name=None, min_pgy_level=1, max_residents_per_block=2,
                  is_night_float=None):
    overrides = {"min_pgy_level": min_pgy_level,
                 "max_residents_per_block": max_residents_per_block}
    if name is not None:
        overrides["name"] = name
    if is_night_float is not None:
        overrides["is_night_float"] = is_night_float
    return _ok(api_client.create_rotation(
        create_rotation_payload(program_id, **overrides), PC), "create rotation")


def make_assignment(resident_id, schedule_block_id, rotation_id):
    return _ok(api_client.create_assignment(
        create_assignment_payload(resident_id, schedule_block_id, rotation_id), PC),
        "create assignment")


# --- Duty-hour logs -----------------------------------------------------------

def resident_headers(resident):
    return make_resident_headers(resident["id"])


def make_duty_log(resident, started_at, ended_at):
    return _ok(api_client.create_duty_log(
        create_duty_log_payload(resident["id"], started_at, ended_at),
        resident_headers(resident)), "create duty log")


def attest_log(log_id, resident):
    return _ok(api_client.attest_duty_log(log_id, resident_headers(resident)),
               "attest duty log")


def make_attested_log(resident, started_at, ended_at):
    log = make_duty_log(resident, started_at, ended_at)
    return attest_log(log["id"], resident)


def make_attested_logs(resident, specs):
    """Create + attest one log per (started_at, ended_at) pair, in order."""
    return [make_attested_log(resident, start, end) for start, end in specs]


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def weekly_shift_specs(week_monday, hours=20.0, offsets_hours=(0.0, 32.0, 64.0, 96.0)):
    """Four duty shifts inside the ISO week whose Monday is `week_monday`
    (YYYY-MM-DD): Mon +0h, Tue +8h, Wed +16h, Fri +0h by default — consecutive
    rest gaps stay >= 12h so no REST_8H violation fires (PRD §3.5)."""
    mon = datetime.strptime(week_monday, "%Y-%m-%d")
    specs = []
    for off in offsets_hours:
        start = mon + timedelta(hours=off)
        specs.append((_iso(start), _iso(start + timedelta(hours=hours))))
    return specs


def make_rolling_window_logs(resident, hours=20.0,
                             weeks=("2026-08-03", "2026-08-10", "2026-08-17",
                                    "2026-08-24"),
                             offsets_hours=(0.0, 32.0, 64.0, 96.0)):
    """Attest 4 shifts per week across the given ISO weeks — the canonical
    rolling-4-week-window roster (PRD §3.5)."""
    logs = []
    for week in weeks:
        logs.extend(make_attested_logs(
            resident, weekly_shift_specs(week, hours, offsets_hours)))
    return logs


def make_daily_logs(resident, start_date="2026-08-03", days=24, start_hour=2,
                    hours=2):
    """Attest one short log per calendar day for `days` consecutive days
    (DAY_OFF_4_IN_28 targeting; 22h rest gaps, no REST_8H)."""
    day0 = datetime.strptime(start_date, "%Y-%m-%d")
    logs = []
    for i in range(days):
        start = day0 + timedelta(days=i, hours=start_hour)
        logs.append(make_attested_log(resident, _iso(start),
                                      _iso(start + timedelta(hours=hours))))
    return logs


def setup_rest_violation(resident):
    """Two attested logs 4.00h apart on 2026-08-03 -> exactly one REST_8H
    violation (gap 4.00 < 8.00, PRD §3.5). Returns the violation row."""
    make_attested_log(resident, "2026-08-03T00:00:00Z", "2026-08-03T08:00:00Z")
    make_attested_log(resident, "2026-08-03T12:00:00Z", "2026-08-03T20:00:00Z")
    data, meta = list_violations(resident_id=resident["id"])
    assert meta["total_count"] == 1, \
        f"Setup failed: expected 1 REST_8H violation, got {meta['total_count']}"
    return data[0]


def list_violations(resident_id=None, duty_hour_log_id=None, status=None):
    params = {"limit": 100}
    if resident_id:
        params["resident_id"] = resident_id
    if duty_hour_log_id:
        params["duty_hour_log_id"] = duty_hour_log_id
    if status:
        params["status"] = status
    return _list(api_client.list_violations(PD, params=params), "list violations")


def get_duty_summary(resident_id, week_start):
    return _ok_plain(api_client.get_duty_hour_summary(resident_id, week_start, PD),
                     "duty-hour summary")


def _ok_plain(resp, what):
    data = get_success_data(resp)
    assert isinstance(data, dict), \
        f"Setup failed: {what}: {resp.status_code} {resp.text}"
    return data


# --- Moonlighting --------------------------------------------------------------

def make_moonlighting(resident, start_date="2026-09-01", end_date="2026-10-01",
                      hours_per_week=4.00, type="EXTERNAL", site_name=None,
                      submit=False, approve=False):
    overrides = {"type": type, "start_date": start_date, "end_date": end_date,
                 "hours_per_week": hours_per_week}
    if site_name is not None:
        overrides["site_name"] = site_name
    req = _ok(api_client.create_moonlighting(
        create_moonlighting_payload(resident["id"], **overrides),
        resident_headers(resident)), "create moonlighting request")
    if submit or approve:
        req = _ok(api_client.submit_moonlighting(req["id"], resident_headers(resident)),
                  "submit moonlighting")
    if approve:
        req = _ok(api_client.approve_moonlighting(req["id"], PD),
                  "approve moonlighting")
    return req


# --- Milestone evaluations / CCC ----------------------------------------------

_eval_counter = itertools.count(1000)


def make_evaluation(resident, year, reporting_period="H1", user_id=None,
                    role="FacultyEvaluator", level=3, patient_care=None):
    """Submit one immutable evaluation; evaluator_id/role stamp from headers
    (PRD §3.7)."""
    uid = user_id or f"ev-auto-{next(_eval_counter)}"
    headers = (make_pd_headers(uid) if role == "ProgramDirector"
               else make_faculty_headers(uid))
    return _ok(api_client.create_evaluation(
        create_evaluation_payload(
            resident["id"], year["id"], reporting_period=reporting_period,
            competency_ratings=six_ratings(level, patient_care=patient_care)),
        headers), "create milestone evaluation")


def make_evaluations(resident, year, count=3, reporting_period="H1", level=3,
                     evaluator_ids=None):
    ids = evaluator_ids or [f"ev-{i + 1}" for i in range(count)]
    assert len(ids) >= count
    return [make_evaluation(resident, year, reporting_period=reporting_period,
                            user_id=ids[i], level=level)
            for i in range(count)]


def make_ccc_review(resident, year, reporting_period="H1", chair_id="chair-1"):
    return _ok(api_client.create_ccc_review(
        create_ccc_review_payload(resident["id"], year["id"],
                                  reporting_period=reporting_period),
        make_ccc_chair_headers(chair_id)), "create CCC review")


def setup_ccc_in_deliberation(resident, year, num_evals=3, reporting_period="H1",
                              chair_id="chair-1", level=3, evaluator_ids=None):
    """`num_evals` evaluations + CCC review walked OPEN -> IN_DELIBERATION."""
    make_evaluations(resident, year, count=num_evals,
                     reporting_period=reporting_period, level=level,
                     evaluator_ids=evaluator_ids)
    review = make_ccc_review(resident, year, reporting_period=reporting_period,
                             chair_id=chair_id)
    return _ok(api_client.begin_deliberation(review["id"],
                                             make_ccc_chair_headers(chair_id)),
               "begin deliberation")


def setup_finalized_ccc(resident, year, outcome="SATISFACTORY",
                        reporting_period="H1", chair_id="chair-1", level=3):
    """3 evaluations + review -> IN_DELIBERATION -> FINALIZED with the outcome."""
    review = setup_ccc_in_deliberation(resident, year, num_evals=3,
                                       reporting_period=reporting_period,
                                       chair_id=chair_id, level=level)
    return _ok(api_client.finalize_ccc_review(
        review["id"], finalize_ccc_payload(outcome, level=level),
        make_ccc_chair_headers(chair_id)), "finalize CCC review")


# --- Procedure case logs / requirements ----------------------------------------

def make_case_requirement(program_id, procedure_category="MAJOR_SURGERY",
                          required_count=2, required_primary_count=1):
    return _ok(api_client.create_case_requirement(create_case_requirement_payload(
        program_id, procedure_category=procedure_category,
        required_count=required_count,
        required_primary_count=required_primary_count), PD),
        "create case requirement")


def make_case_log(resident, rotation, procedure_category="MAJOR_SURGERY",
                  performed_date="2026-08-03", role="SURGEON"):
    return _ok(api_client.create_case_log(create_case_log_payload(
        resident["id"], rotation["id"], procedure_category=procedure_category,
        performed_date=performed_date, role=role), resident_headers(resident)),
        "create case log")


def verify_case_log(log_id, evaluator_id="ev-1"):
    return _ok(api_client.verify_case_log(log_id, make_faculty_headers(evaluator_id)),
               "verify case log")


def make_verified_case_log(resident, rotation, procedure_category="MAJOR_SURGERY",
                           performed_date="2026-08-03", role="SURGEON",
                           evaluator_id="ev-1"):
    log = make_case_log(resident, rotation, procedure_category=procedure_category,
                        performed_date=performed_date, role=role)
    return verify_case_log(log["id"], evaluator_id)


def get_case_progress(resident_id):
    return _ok_plain(api_client.get_case_progress(resident_id, PD), "case progress")


# --- Remediation / probation ----------------------------------------------------

def make_remediation_plan(resident_id, goals="Improve sign-out documentation",
                          start_date="2026-08-01", end_date="2026-10-30"):
    return _ok(api_client.create_remediation_plan(create_remediation_payload(
        resident_id, goals=goals, start_date=start_date, end_date=end_date), PD),
        "create remediation plan")


def complete_remediation_plan(plan_id, outcome):
    return _ok(api_client.complete_remediation_plan(plan_id, {"outcome": outcome}, PD),
               "complete remediation plan")


def make_probation_case(resident_id, reason="Unprofessional conduct", user_id="pd-1"):
    return _ok(api_client.create_probation_case(
        create_probation_payload(resident_id, reason=reason),
        make_pd_headers(user_id)), "create probation case")


def list_probation_cases(resident_id=None, remediation_plan_id=None, status=None):
    params = {"limit": 100}
    if resident_id:
        params["resident_id"] = resident_id
    if remediation_plan_id:
        params["remediation_plan_id"] = remediation_plan_id
    if status:
        params["status"] = status
    return _list(api_client.list_probation_cases(PD, params=params),
                 "list probation cases")


def list_remediation_plans(resident_id=None, ccc_review_id=None, status=None):
    params = {"limit": 100}
    if resident_id:
        params["resident_id"] = resident_id
    if ccc_review_id:
        params["ccc_review_id"] = ccc_review_id
    if status:
        params["status"] = status
    return _list(api_client.list_remediation_plans(PD, params=params),
                 "list remediation plans")


# --- Citations / surveys --------------------------------------------------------

def make_citation(program_id, citation_code="IV.A.2", severity="SERIOUS",
                  area_code="DUTY_HOURS", due_date="2026-12-01"):
    return _ok(api_client.create_citation(create_citation_payload(
        program_id, citation_code=citation_code, severity=severity,
        area_code=area_code, due_date=due_date), DIO), "create citation")


def respond_and_resolve_citation(citation_id):
    """Walk OPEN -> RESPONSE_DRAFTED -> RESPONSE_SUBMITTED -> RESOLVED."""
    _ok(api_client.draft_citation_response(citation_id,
                                           {"response_text": "Plan revised."}, PD),
        "draft citation response")
    _ok(api_client.submit_citation_response(citation_id, PD),
        "submit citation response")
    return _ok(api_client.resolve_citation(citation_id,
                                           {"resolution_note": "Accepted"}, DIO),
               "resolve citation")


def list_citations(program_id=None, annual_survey_id=None, status=None,
                   severity=None):
    params = {"limit": 100}
    if program_id:
        params["program_id"] = program_id
    if annual_survey_id:
        params["annual_survey_id"] = annual_survey_id
    if status:
        params["status"] = status
    if severity:
        params["severity"] = severity
    return _list(api_client.list_citations(DIO, params=params), "list citations")


def make_survey(program_id, year_id):
    return _ok(api_client.create_survey(create_survey_payload(program_id, year_id), PC),
               "create survey")


def get_program(program_id):
    return _ok_plain(api_client.get_program(program_id, DIO), "get program")


# --- Tier 3/5: graduation path --------------------------------------------------

def setup_graduation_ready(rotation_name="General Surgery", required_count=1,
                           required_primary_count=0, surgeon_logs=1):
    """Program + ACTIVE year + APPROVED complement + ACTIVE resident +
    CaseRequirement satisfied by VERIFIED SURGEON logs + FINALIZED CCC review
    (SATISFACTORY). Returns dict with the whole scenario."""
    s = setup_program_with_active_resident(approved_positions=4)
    program, year, resident = s["program"], s["year"], s["resident"]
    rotation = make_rotation(program["id"], name=rotation_name,
                             max_residents_per_block=5)
    requirement = make_case_requirement(
        program["id"], required_count=required_count,
        required_primary_count=required_primary_count)
    day = datetime(2026, 8, 3)
    for i in range(surgeon_logs):
        make_verified_case_log(resident, rotation,
                               performed_date=(day + timedelta(days=i)).strftime("%Y-%m-%d"),
                               role="SURGEON")
    review = setup_finalized_ccc(resident, year, outcome="SATISFACTORY")
    s.update({"rotation": rotation, "requirement": requirement, "ccc_review": review})
    return s


def setup_graduated_resident():
    """Full lifecycle through GRADUATED (PRD §3.3 four graduation gates)."""
    s = setup_graduation_ready()
    resident = _ok(api_client.graduate_resident(s["resident"]["id"], PD),
                   "graduate resident")
    s["resident"] = resident
    return s
