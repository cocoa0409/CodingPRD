"""HTTP route registration.

Each handler runs the PRD section 2.8 pipeline prefix:
  stage 1  user context headers (middleware.user_context)
  stage 2  request body shape (per-endpoint shape validator)
  stage 3  role authorization (middleware.require_role)
then delegates to services for ownership/existence/OCC/state/business checks.
"""
from flask import request

from errors import ApiError
from middleware import (
    user_context, require_role, ANY_ROLE, DIO, PD, PC, RESIDENT, FACULTY,
    CCC_CHAIR,
)
from response import ok, ok_list
import services
import services2
from util import (
    body, pagination_args, parse_dt, req_present, as_str, as_int, as_num,
    as_bool, as_enum, as_list, as_dt, as_version, invalid_request,
)

ALL = ANY_ROLE


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def handle(op, roles=None, shape=None, status=200):
    user_id, role = user_context()
    data = body()
    if shape is not None:
        shape(data)
    if roles is not None:
        require_role(role, roles)
    return ok(op(user_id, role, data), status)


def handle_get_one(view):
    user_context()
    return ok(view())


def handle_list(fetch):
    user_context()
    limit, offset = pagination_args()
    items = fetch(request.args)
    total = len(items)
    return ok_list(items[offset:offset + limit], total, limit, offset)


# ---------------------------------------------------------------------------
# Shape validators (pipeline stage 2: required fields, types, declared enums)
# ---------------------------------------------------------------------------

def _shape_program(data):
    as_str(req_present(data, "name"), "name")
    as_enum(req_present(data, "specialty"), "specialty", services.SPECIALTIES)
    as_str(req_present(data, "acgme_program_code"), "acgme_program_code")


def _shape_year(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_str(req_present(data, "year_label"), "year_label")
    as_dt(req_present(data, "start_date"), "start_date")
    as_dt(req_present(data, "end_date"), "end_date")


def _shape_regenerate(data):
    data["expected_academic_year_version"] = as_version(
        req_present(data, "expected_academic_year_version"),
        "expected_academic_year_version")


def _shape_complement_create(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_str(req_present(data, "academic_year_id"), "academic_year_id")
    pgy = as_int(req_present(data, "pgy_level"), "pgy_level")
    if not 1 <= pgy <= 7:
        raise invalid_request("pgy_level must be an integer from 1 through 7")
    positions = as_int(req_present(data, "approved_positions"), "approved_positions")
    if positions < 0:
        raise invalid_request("approved_positions must be >= 0")
    budget = as_int(req_present(data, "annual_funding_budget_cents"),
                    "annual_funding_budget_cents")
    if budget < 0:
        raise invalid_request("annual_funding_budget_cents must be >= 0")
    stipend = as_int(req_present(data, "blended_stipend_cents"), "blended_stipend_cents")
    if stipend < 1:
        raise invalid_request("blended_stipend_cents must be >= 1")


def _shape_complement_update(data):
    if "approved_positions" in data and data["approved_positions"] is not None:
        if as_int(data["approved_positions"], "approved_positions") < 0:
            raise invalid_request("approved_positions must be >= 0")
    if "annual_funding_budget_cents" in data and data["annual_funding_budget_cents"] is not None:
        if as_int(data["annual_funding_budget_cents"], "annual_funding_budget_cents") < 0:
            raise invalid_request("annual_funding_budget_cents must be >= 0")
    if "blended_stipend_cents" in data and data["blended_stipend_cents"] is not None:
        if as_int(data["blended_stipend_cents"], "blended_stipend_cents") < 1:
            raise invalid_request("blended_stipend_cents must be >= 1")
    as_version(req_present(data, "expected_complement_approval_version"),
               "expected_complement_approval_version")
    data["expected_complement_approval_version"] = as_version(
        data["expected_complement_approval_version"],
        "expected_complement_approval_version")


def _shape_resident(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_str(req_present(data, "entry_academic_year_id"), "entry_academic_year_id")
    pgy = as_int(req_present(data, "pgy_level"), "pgy_level")
    if not 1 <= pgy <= 7:
        raise invalid_request("pgy_level must be an integer from 1 through 7")
    as_str(req_present(data, "full_name"), "full_name")
    as_str(req_present(data, "email"), "email")
    as_dt(req_present(data, "hire_date"), "hire_date")
    as_dt(req_present(data, "expected_graduation_date"), "expected_graduation_date")


def _shape_rotation_create(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_str(req_present(data, "name"), "name")
    min_pgy = as_int(req_present(data, "min_pgy_level"), "min_pgy_level")
    if not 1 <= min_pgy <= 7:
        raise invalid_request("min_pgy_level must be an integer from 1 through 7")
    cap = as_int(req_present(data, "max_residents_per_block"), "max_residents_per_block")
    if cap < 1:
        raise invalid_request("max_residents_per_block must be >= 1")
    if "is_night_float" in data and data["is_night_float"] is not None:
        as_bool(data["is_night_float"], "is_night_float")


def _shape_rotation_update(data):
    if "name" in data and data["name"] is not None:
        as_str(data["name"], "name")
    if "min_pgy_level" in data and data["min_pgy_level"] is not None:
        if not 1 <= as_int(data["min_pgy_level"], "min_pgy_level") <= 7:
            raise invalid_request("min_pgy_level must be an integer from 1 through 7")
    if "max_residents_per_block" in data and data["max_residents_per_block"] is not None:
        if as_int(data["max_residents_per_block"], "max_residents_per_block") < 1:
            raise invalid_request("max_residents_per_block must be >= 1")
    if "is_night_float" in data and data["is_night_float"] is not None:
        as_bool(data["is_night_float"], "is_night_float")
    as_version(req_present(data, "expected_rotation_version"), "expected_rotation_version")
    data["expected_rotation_version"] = as_version(
        data["expected_rotation_version"], "expected_rotation_version")


def _shape_assignment(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_str(req_present(data, "schedule_block_id"), "schedule_block_id")
    as_str(req_present(data, "rotation_id"), "rotation_id")


def _shape_duty_log(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_dt(req_present(data, "started_at"), "started_at")
    as_dt(req_present(data, "ended_at"), "ended_at")


def _shape_void(data):
    as_str(req_present(data, "void_reason"), "void_reason")


def _shape_resolve(data):
    as_str(req_present(data, "resolution_note"), "resolution_note")


def _shape_dismiss(data):
    as_str(req_present(data, "justification"), "justification")


def _shape_moonlighting(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_enum(req_present(data, "type"), "type", services2.MOONLIGHTING_TYPES)
    as_str(req_present(data, "site_name"), "site_name")
    as_dt(req_present(data, "start_date"), "start_date")
    as_dt(req_present(data, "end_date"), "end_date")
    hpw = as_num(req_present(data, "hours_per_week"), "hours_per_week")
    if not 1.0 <= float(hpw) <= 24.0:
        raise invalid_request("hours_per_week must lie between 1.00 and 24.00")


def _shape_deny(data):
    as_str(req_present(data, "denial_reason"), "denial_reason")


def _shape_revoke(data):
    as_str(req_present(data, "revocation_reason"), "revocation_reason")


def _shape_evaluation(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_str(req_present(data, "academic_year_id"), "academic_year_id")
    as_enum(req_present(data, "reporting_period"), "reporting_period",
            services2.REPORTING_PERIODS)
    as_list(req_present(data, "competency_ratings"), "competency_ratings")


def _shape_ccc_create(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_str(req_present(data, "academic_year_id"), "academic_year_id")
    as_enum(req_present(data, "reporting_period"), "reporting_period",
            services2.REPORTING_PERIODS)


def _shape_ccc_finalize(data):
    # outcome enum membership is judged later as ERR_INVALID_OUTCOME (422);
    # here only presence and type. Same for milestone_levels contents
    # (ERR_INCOMPLETE_RATINGS at the CCC gate).
    as_str(req_present(data, "outcome"), "outcome")
    as_list(req_present(data, "milestone_levels"), "milestone_levels")


def _shape_case_log(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_str(req_present(data, "rotation_id"), "rotation_id")
    as_enum(req_present(data, "procedure_category"), "procedure_category",
            services2.PROCEDURE_CATEGORIES)
    as_dt(req_present(data, "performed_date"), "performed_date")
    as_enum(req_present(data, "role"), "role", services2.CASE_ROLES)


def _shape_reject(data):
    as_str(req_present(data, "rejection_reason"), "rejection_reason")


def _shape_requirement(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_enum(req_present(data, "procedure_category"), "procedure_category",
            services2.PROCEDURE_CATEGORIES)
    count = as_int(req_present(data, "required_count"), "required_count")
    if count < 1:
        raise invalid_request("required_count must be >= 1")
    primary = as_int(req_present(data, "required_primary_count"), "required_primary_count")
    if primary < 0 or primary > count:
        raise invalid_request("required_primary_count must be >= 0 and <= required_count")


def _shape_plan(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_str(req_present(data, "goals"), "goals")
    as_dt(req_present(data, "start_date"), "start_date")
    as_dt(req_present(data, "end_date"), "end_date")


def _shape_plan_complete(data):
    # outcome enum membership is judged later as ERR_INVALID_OUTCOME (422).
    as_str(req_present(data, "outcome"), "outcome")


def _shape_plan_cancel(data):
    as_str(req_present(data, "cancel_reason"), "cancel_reason")


def _shape_probation(data):
    as_str(req_present(data, "resident_id"), "resident_id")
    as_str(req_present(data, "reason"), "reason")


def _shape_citation(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_str(req_present(data, "citation_code"), "citation_code")
    as_enum(req_present(data, "severity"), "severity", services2.SEVERITIES)
    as_enum(req_present(data, "area_code"), "area_code", services2.AREA_CODES)
    as_dt(req_present(data, "due_date"), "due_date")


def _shape_draft_response(data):
    as_str(req_present(data, "response_text"), "response_text")


def _shape_citation_resolve(data):
    as_str(req_present(data, "resolution_note"), "resolution_note")


def _shape_escalate(data):
    as_str(req_present(data, "escalation_reason"), "escalation_reason")


def _shape_survey_create(data):
    as_str(req_present(data, "program_id"), "program_id")
    as_str(req_present(data, "academic_year_id"), "academic_year_id")


def _shape_survey_close(data):
    as_num(req_present(data, "resident_response_rate"), "resident_response_rate")
    as_num(req_present(data, "faculty_response_rate"), "faculty_response_rate")
    areas = as_list(req_present(data, "area_results"), "area_results")
    for entry in areas:
        if not isinstance(entry, dict):
            raise invalid_request("area_results entries must be objects")
        as_enum(req_present(entry, "area_code"), "area_code", services2.AREA_CODES)
        as_num(req_present(entry, "compliance_pct"), "compliance_pct")


def _shape_clock(data):
    as_dt(req_present(data, "to_iso8601"), "to_iso8601")


def _summary_args():
    raw = request.args.get("week_start")
    if raw is None:
        raise invalid_request("Missing required query parameter: week_start")
    try:
        parse_dt(raw)
    except Exception:
        raise invalid_request("week_start must be an ISO 8601 timestamp")
    return raw


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------

def register_routes(app):
    app.url_map.strict_slashes = False

    # --- logical clock ---
    @app.post("/_clock/set_current_utc")
    def clock_set():
        return handle(lambda u, r, d: services2.set_clock(d),
                      roles=[PC, PD, DIO], shape=_shape_clock)

    # --- ResidencyProgram ---
    @app.post("/residency-programs")
    def program_create():
        return handle(lambda u, r, d: services.create_program(d),
                      roles=[DIO], shape=_shape_program, status=201)

    @app.get("/residency-programs")
    def program_list():
        return handle_list(services.list_programs)

    @app.get("/residency-programs/<pid>")
    def program_get(pid):
        return handle_get_one(lambda: services.get_program_view(pid))

    # --- AcademicYear ---
    @app.post("/residency-programs/academic-years")
    def year_create():
        return handle(lambda u, r, d: services.create_year(d),
                      roles=[PC], shape=_shape_year, status=201)

    @app.get("/residency-programs/academic-years")
    def year_list():
        return handle_list(services.list_years)

    @app.get("/residency-programs/academic-years/<yid>")
    def year_get(yid):
        return handle_get_one(lambda: services.get_year_view(yid))

    @app.post("/residency-programs/academic-years/<yid>/activate")
    def year_activate(yid):
        return handle(lambda u, r, d: services.activate_year(yid), roles=[PC])

    @app.post("/residency-programs/academic-years/<yid>/close")
    def year_close(yid):
        return handle(lambda u, r, d: services.close_year(yid), roles=[PC])

    @app.post("/residency-programs/academic-years/<yid>/regenerate-blocks")
    def year_regenerate(yid):
        return handle(lambda u, r, d: services.regenerate_blocks(yid, d),
                      roles=[PC], shape=_shape_regenerate)

    # --- ScheduleBlock ---
    @app.get("/residency-programs/schedule-blocks")
    def block_list():
        return handle_list(services.list_blocks)

    @app.get("/residency-programs/schedule-blocks/<bid>")
    def block_get(bid):
        return handle_get_one(lambda: services.get_block_view(bid))

    # --- ComplementApproval ---
    @app.post("/residency-programs/complement-approvals")
    def complement_create():
        return handle(lambda u, r, d: services.create_complement(d),
                      roles=[PD], shape=_shape_complement_create, status=201)

    @app.get("/residency-programs/complement-approvals")
    def complement_list():
        return handle_list(services.list_complements)

    @app.get("/residency-programs/complement-approvals/<cid>")
    def complement_get(cid):
        return handle_get_one(lambda: services.get_complement_view(cid))

    @app.put("/residency-programs/complement-approvals/<cid>")
    def complement_update(cid):
        return handle(lambda u, r, d: services.update_complement(cid, d),
                      roles=[PD], shape=_shape_complement_update)

    @app.post("/residency-programs/complement-approvals/<cid>/submit")
    def complement_submit(cid):
        return handle(lambda u, r, d: services.submit_complement(cid), roles=[PD])

    @app.post("/residency-programs/complement-approvals/<cid>/approve")
    def complement_approve(cid):
        return handle(lambda u, r, d: services.approve_complement(cid), roles=[DIO])

    @app.post("/residency-programs/complement-approvals/<cid>/reject")
    def complement_reject(cid):
        return handle(lambda u, r, d: services.reject_complement(cid), roles=[DIO])

    @app.post("/residency-programs/complement-approvals/<cid>/lock")
    def complement_lock(cid):
        return handle(lambda u, r, d: services.lock_complement(cid), roles=[DIO])

    # --- Resident ---
    @app.post("/residency-programs/residents")
    def resident_create():
        return handle(lambda u, r, d: services.create_resident(d),
                      roles=[PC], shape=_shape_resident, status=201)

    @app.get("/residency-programs/residents")
    def resident_list():
        return handle_list(services.list_residents)

    @app.get("/residency-programs/residents/<rid>")
    def resident_get(rid):
        return handle_get_one(lambda: services.get_resident_view(rid))

    @app.post("/residency-programs/residents/<rid>/activate")
    def resident_activate(rid):
        return handle(lambda u, r, d: services.activate_resident(rid), roles=[PC])

    @app.post("/residency-programs/residents/<rid>/place-on-leave")
    def resident_place_on_leave(rid):
        return handle(lambda u, r, d: services.place_on_leave(rid), roles=[PD])

    @app.post("/residency-programs/residents/<rid>/return-from-leave")
    def resident_return_from_leave(rid):
        return handle(lambda u, r, d: services.return_from_leave(rid), roles=[PD])

    @app.post("/residency-programs/residents/<rid>/graduate")
    def resident_graduate(rid):
        return handle(lambda u, r, d: services.graduate_resident(rid), roles=[PD])

    @app.post("/residency-programs/residents/<rid>/transfer")
    def resident_transfer(rid):
        return handle(lambda u, r, d: services.transfer_resident(rid), roles=[PD])

    @app.get("/residency-programs/residents/<rid>/duty-hour-summary")
    def resident_duty_hour_summary(rid):
        user_context()
        week_start = _summary_args()
        return ok(services.duty_hour_summary_view(rid, week_start))

    @app.get("/residency-programs/residents/<rid>/case-progress")
    def resident_case_progress(rid):
        return handle_get_one(lambda: services.case_progress_view(rid))

    # --- Rotation ---
    @app.post("/residency-programs/rotations")
    def rotation_create():
        return handle(lambda u, r, d: services.create_rotation(d),
                      roles=[PC], shape=_shape_rotation_create, status=201)

    @app.get("/residency-programs/rotations")
    def rotation_list():
        return handle_list(services.list_rotations)

    @app.get("/residency-programs/rotations/<rid>")
    def rotation_get(rid):
        return handle_get_one(lambda: services.get_rotation_view(rid))

    @app.put("/residency-programs/rotations/<rid>")
    def rotation_update(rid):
        return handle(lambda u, r, d: services.update_rotation(rid, d),
                      roles=[PC], shape=_shape_rotation_update)

    @app.post("/residency-programs/rotations/<rid>/retire")
    def rotation_retire(rid):
        return handle(lambda u, r, d: services.retire_rotation(rid), roles=[PC])

    # --- RotationAssignment ---
    @app.post("/residency-programs/rotation-assignments")
    def assignment_create():
        return handle(lambda u, r, d: services.create_assignment(d),
                      roles=[PC], shape=_shape_assignment, status=201)

    @app.get("/residency-programs/rotation-assignments")
    def assignment_list():
        return handle_list(services.list_assignments)

    @app.get("/residency-programs/rotation-assignments/<aid>")
    def assignment_get(aid):
        return handle_get_one(lambda: services.get_assignment_view(aid))

    @app.post("/residency-programs/rotation-assignments/<aid>/confirm")
    def assignment_confirm(aid):
        return handle(lambda u, r, d: services.confirm_assignment(aid), roles=[PC])

    @app.post("/residency-programs/rotation-assignments/<aid>/complete")
    def assignment_complete(aid):
        return handle(lambda u, r, d: services.complete_assignment(aid), roles=[PC])

    @app.post("/residency-programs/rotation-assignments/<aid>/cancel")
    def assignment_cancel(aid):
        return handle(lambda u, r, d: services.cancel_assignment(aid), roles=[PC])

    # --- DutyHourLog ---
    @app.post("/residency-programs/duty-hour-logs")
    def duty_log_create():
        return handle(lambda u, r, d: services2.create_duty_log(d, u, r),
                      roles=[RESIDENT], shape=_shape_duty_log, status=201)

    @app.get("/residency-programs/duty-hour-logs")
    def duty_log_list():
        return handle_list(services2.list_duty_logs)

    @app.get("/residency-programs/duty-hour-logs/<lid>")
    def duty_log_get(lid):
        return handle_get_one(lambda: services2.get_duty_log_view(lid))

    @app.post("/residency-programs/duty-hour-logs/<lid>/attest")
    def duty_log_attest(lid):
        return handle(lambda u, r, d: services2.attest_duty_log(lid, u, r),
                      roles=[RESIDENT])

    @app.post("/residency-programs/duty-hour-logs/<lid>/void")
    def duty_log_void(lid):
        return handle(lambda u, r, d: services2.void_duty_log(lid, d, u, r),
                      roles=[RESIDENT, PD], shape=_shape_void)

    # --- DutyHourViolation ---
    @app.get("/residency-programs/duty-hour-violations")
    def violation_list():
        return handle_list(services2.list_violations)

    @app.get("/residency-programs/duty-hour-violations/<vid>")
    def violation_get(vid):
        return handle_get_one(lambda: services2.get_violation_view(vid))

    @app.post("/residency-programs/duty-hour-violations/<vid>/acknowledge")
    def violation_acknowledge(vid):
        return handle(lambda u, r, d: services2.acknowledge_violation(vid), roles=[PC])

    @app.post("/residency-programs/duty-hour-violations/<vid>/resolve")
    def violation_resolve(vid):
        return handle(lambda u, r, d: services2.resolve_violation(vid, d),
                      roles=[PD], shape=_shape_resolve)

    @app.post("/residency-programs/duty-hour-violations/<vid>/dismiss")
    def violation_dismiss(vid):
        return handle(lambda u, r, d: services2.dismiss_violation(vid, d),
                      roles=[PD], shape=_shape_dismiss)

    # --- MoonlightingRequest ---
    @app.post("/residency-programs/moonlighting-requests")
    def moonlighting_create():
        return handle(lambda u, r, d: services2.create_moonlighting(d, u, r),
                      roles=[RESIDENT], shape=_shape_moonlighting, status=201)

    @app.get("/residency-programs/moonlighting-requests")
    def moonlighting_list():
        return handle_list(services2.list_moonlighting)

    @app.get("/residency-programs/moonlighting-requests/<mid>")
    def moonlighting_get(mid):
        return handle_get_one(lambda: services2.get_moonlighting_view(mid))

    @app.post("/residency-programs/moonlighting-requests/<mid>/submit")
    def moonlighting_submit(mid):
        return handle(lambda u, r, d: services2.submit_moonlighting(mid, u, r),
                      roles=[RESIDENT])

    @app.post("/residency-programs/moonlighting-requests/<mid>/approve")
    def moonlighting_approve(mid):
        return handle(lambda u, r, d: services2.approve_moonlighting(mid), roles=[PD])

    @app.post("/residency-programs/moonlighting-requests/<mid>/deny")
    def moonlighting_deny(mid):
        return handle(lambda u, r, d: services2.deny_moonlighting(mid, d),
                      roles=[PD], shape=_shape_deny)

    @app.post("/residency-programs/moonlighting-requests/<mid>/withdraw")
    def moonlighting_withdraw(mid):
        return handle(lambda u, r, d: services2.withdraw_moonlighting(mid, u, r),
                      roles=[RESIDENT])

    @app.post("/residency-programs/moonlighting-requests/<mid>/revoke")
    def moonlighting_revoke(mid):
        return handle(lambda u, r, d: services2.revoke_moonlighting(mid, d),
                      roles=[PD], shape=_shape_revoke)

    # --- MilestoneEvaluation ---
    @app.post("/residency-programs/milestone-evaluations")
    def evaluation_create():
        return handle(lambda u, r, d: services2.create_evaluation(d, u, r),
                      roles=[FACULTY, PD], shape=_shape_evaluation, status=201)

    @app.get("/residency-programs/milestone-evaluations")
    def evaluation_list():
        return handle_list(services2.list_evaluations)

    @app.get("/residency-programs/milestone-evaluations/<eid>")
    def evaluation_get(eid):
        return handle_get_one(lambda: services2.get_evaluation_view(eid))

    # --- CCCReview ---
    @app.post("/residency-programs/ccc-reviews")
    def ccc_create():
        return handle(lambda u, r, d: services2.create_ccc_review(d),
                      roles=[CCC_CHAIR], shape=_shape_ccc_create, status=201)

    @app.get("/residency-programs/ccc-reviews")
    def ccc_list():
        return handle_list(services2.list_ccc_reviews)

    @app.get("/residency-programs/ccc-reviews/<cid>")
    def ccc_get(cid):
        return handle_get_one(lambda: services2.get_ccc_review_view(cid))

    @app.post("/residency-programs/ccc-reviews/<cid>/begin-deliberation")
    def ccc_begin(cid):
        return handle(lambda u, r, d: services2.begin_deliberation(cid), roles=[CCC_CHAIR])

    @app.post("/residency-programs/ccc-reviews/<cid>/finalize")
    def ccc_finalize(cid):
        return handle(lambda u, r, d: services2.finalize_ccc_review(cid, d, u),
                      roles=[CCC_CHAIR], shape=_shape_ccc_finalize)

    @app.post("/residency-programs/ccc-reviews/<cid>/reopen")
    def ccc_reopen(cid):
        return handle(lambda u, r, d: services2.reopen_ccc_review(cid), roles=[CCC_CHAIR])

    # --- ProcedureCaseLog ---
    @app.post("/residency-programs/procedure-case-logs")
    def case_log_create():
        return handle(lambda u, r, d: services2.create_case_log(d, u, r),
                      roles=[RESIDENT], shape=_shape_case_log, status=201)

    @app.get("/residency-programs/procedure-case-logs")
    def case_log_list():
        return handle_list(services2.list_case_logs)

    @app.get("/residency-programs/procedure-case-logs/<lid>")
    def case_log_get(lid):
        return handle_get_one(lambda: services2.get_case_log_view(lid))

    @app.post("/residency-programs/procedure-case-logs/<lid>/verify")
    def case_log_verify(lid):
        return handle(lambda u, r, d: services2.verify_case_log(lid), roles=[FACULTY])

    @app.post("/residency-programs/procedure-case-logs/<lid>/reject")
    def case_log_reject(lid):
        return handle(lambda u, r, d: services2.reject_case_log(lid, d),
                      roles=[FACULTY], shape=_shape_reject)

    @app.post("/residency-programs/procedure-case-logs/<lid>/resubmit")
    def case_log_resubmit(lid):
        return handle(lambda u, r, d: services2.resubmit_case_log(lid, u, r),
                      roles=[RESIDENT])

    @app.post("/residency-programs/procedure-case-logs/<lid>/void")
    def case_log_void(lid):
        return handle(lambda u, r, d: services2.void_case_log(lid, d),
                      roles=[PD], shape=_shape_void)

    # --- CaseRequirement ---
    @app.post("/residency-programs/case-requirements")
    def requirement_create():
        return handle(lambda u, r, d: services2.create_requirement(d),
                      roles=[PD], shape=_shape_requirement, status=201)

    @app.get("/residency-programs/case-requirements")
    def requirement_list():
        return handle_list(services2.list_requirements)

    @app.get("/residency-programs/case-requirements/<qid>")
    def requirement_get(qid):
        return handle_get_one(lambda: services2.get_requirement_view(qid))

    # --- RemediationPlan ---
    @app.post("/residency-programs/remediation-plans")
    def plan_create():
        return handle(lambda u, r, d: services2.create_plan(d),
                      roles=[PD], shape=_shape_plan, status=201)

    @app.get("/residency-programs/remediation-plans")
    def plan_list():
        return handle_list(services2.list_plans)

    @app.get("/residency-programs/remediation-plans/<pid>")
    def plan_get(pid):
        return handle_get_one(lambda: services2.get_plan_view(pid))

    @app.post("/residency-programs/remediation-plans/<pid>/complete")
    def plan_complete(pid):
        return handle(lambda u, r, d: services2.complete_plan(pid, d),
                      roles=[PD], shape=_shape_plan_complete)

    @app.post("/residency-programs/remediation-plans/<pid>/cancel")
    def plan_cancel(pid):
        return handle(lambda u, r, d: services2.cancel_plan(pid, d),
                      roles=[PD], shape=_shape_plan_cancel)

    # --- ProbationCase ---
    @app.post("/residency-programs/probation-cases")
    def probation_create():
        return handle(lambda u, r, d: services2.create_probation(d),
                      roles=[PD], shape=_shape_probation, status=201)

    @app.get("/residency-programs/probation-cases")
    def probation_list():
        return handle_list(services2.list_probation)

    @app.get("/residency-programs/probation-cases/<pid>")
    def probation_get(pid):
        return handle_get_one(lambda: services2.get_probation_view(pid))

    @app.post("/residency-programs/probation-cases/<pid>/lift")
    def probation_lift(pid):
        return handle(lambda u, r, d: services2.lift_probation(pid), roles=[PD])

    @app.post("/residency-programs/probation-cases/<pid>/recommend-dismissal")
    def probation_recommend(pid):
        return handle(lambda u, r, d: services2.recommend_dismissal(pid, u), roles=[PD])

    @app.post("/residency-programs/probation-cases/<pid>/confirm-dismissal")
    def probation_confirm(pid):
        return handle(lambda u, r, d: services2.confirm_dismissal(pid, u), roles=[DIO])

    # --- AccreditationCitation ---
    @app.post("/residency-programs/accreditation-citations")
    def citation_create():
        return handle(lambda u, r, d: services2.create_citation(d),
                      roles=[DIO], shape=_shape_citation, status=201)

    @app.get("/residency-programs/accreditation-citations")
    def citation_list():
        return handle_list(services2.list_citations)

    @app.get("/residency-programs/accreditation-citations/<cid>")
    def citation_get(cid):
        return handle_get_one(lambda: services2.get_citation_view(cid))

    @app.post("/residency-programs/accreditation-citations/<cid>/draft-response")
    def citation_draft(cid):
        return handle(lambda u, r, d: services2.draft_citation_response(cid, d),
                      roles=[PD], shape=_shape_draft_response)

    @app.post("/residency-programs/accreditation-citations/<cid>/submit-response")
    def citation_submit(cid):
        return handle(lambda u, r, d: services2.submit_citation_response(cid), roles=[PD])

    @app.post("/residency-programs/accreditation-citations/<cid>/resolve")
    def citation_resolve(cid):
        return handle(lambda u, r, d: services2.resolve_citation(cid, d),
                      roles=[DIO], shape=_shape_citation_resolve)

    @app.post("/residency-programs/accreditation-citations/<cid>/escalate")
    def citation_escalate(cid):
        return handle(lambda u, r, d: services2.escalate_citation(cid, d),
                      roles=[DIO], shape=_shape_escalate)

    # --- AnnualSurvey ---
    @app.post("/residency-programs/annual-surveys")
    def survey_create():
        return handle(lambda u, r, d: services2.create_survey(d),
                      roles=[PC], shape=_shape_survey_create, status=201)

    @app.get("/residency-programs/annual-surveys")
    def survey_list():
        return handle_list(services2.list_surveys)

    @app.get("/residency-programs/annual-surveys/<sid>")
    def survey_get(sid):
        return handle_get_one(lambda: services2.get_survey_view(sid))

    @app.post("/residency-programs/annual-surveys/<sid>/close")
    def survey_close(sid):
        return handle(lambda u, r, d: services2.close_survey(sid, d),
                      roles=[DIO], shape=_shape_survey_close)
