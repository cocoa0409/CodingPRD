"""Business lines, referral partners, referrals and participants
(PRD sections 3.1, 3.2, 3.3 and the funder outcome summary of 3.9)."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import derive
import shapes
from auth import must_exist_filter, must_get, require, require_owner
from errors import fail
from response import created, ok, ok_list, paginate, read_pagination
from serialize import dump, dump_many, jsonable
from store import all_records, create_record, days, set_fields, store

bp = Blueprint("intake", __name__)

READ_PROGRAM_ROLES = ("ProgramDirector", "IntakeSpecialist", "JobCoach", "CaseManager", "FunderAnalyst")


# =========================================================================== #
# BusinessLine
# =========================================================================== #

@bp.route("/business-lines", methods=["POST"])
def create_business_line():
    require(("ProgramDirector",))
    payload = shapes.body()
    name = shapes.req_string(payload, "name", 1, 120)
    market = shapes.req_int(payload, "market_viability_score", 0, 100)
    training = shapes.req_int(payload, "training_relevance_score", 0, 100)
    mission = shapes.req_int(payload, "mission_alignment_score", 0, 100)
    slots = shapes.req_int(payload, "training_slots_total", 1)
    capacity = shapes.req_int(payload, "supervisor_capacity", 1)
    margin = shapes.req_number(payload, "target_gross_margin_pct", 0, Decimal("0.9000"), places=4)
    cap = shapes.req_int(payload, "subsidy_cap_cents", 0)
    line = create_record("business_lines", {
        "name": name,
        "market_viability_score": market,
        "training_relevance_score": training,
        "mission_alignment_score": mission,
        "composite_viability_score": calc.composite_viability_score(market, training, mission),
        "status": "DRAFT",
        "intake_posture": "CLOSED",
        "training_slots_total": slots,
        "training_slots_filled": 0,
        "supervisor_capacity": capacity,
        "target_gross_margin_pct": margin,
        "subsidy_cap_cents": cap,
        "cumulative_subsidy_cents": 0,
        "quality_incident_count": 0,
        "rejection_reason": None,
        "launched_at": None,
    })
    return created(dump(line))


@bp.route("/business-lines/<business_line_id>", methods=["GET"])
def read_business_line(business_line_id):
    require(READ_PROGRAM_ROLES)
    return ok(dump(must_get("business_lines", business_line_id)))


@bp.route("/business-lines/<business_line_id>/review", methods=["POST"])
def review_business_line(business_line_id):
    require(("ProgramDirector",))
    line = must_get("business_lines", business_line_id)
    payload = shapes.body()
    decision = shapes.req_enum(payload, "decision", C.REVIEW_DECISIONS)
    reason = None
    if decision == "REJECTED":
        reason = shapes.req_string(payload, "rejection_reason", 1)
    if line["status"] != "DRAFT":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT business line may be reviewed.")
    if decision == "APPROVED":
        if not calc.viability_gate_met(line):
            fail("ERR_VIABILITY_GATE_NOT_MET",
                 "composite_viability_score must be at least 70.00 and every dimension score at least 50.")
        set_fields(line, status="APPROVED")
    else:
        set_fields(line, status="REJECTED", rejection_reason=reason)
    derive.recompute_line_posture(line)
    return ok(dump(line))


@bp.route("/business-lines/<business_line_id>/launch", methods=["POST"])
def launch_business_line(business_line_id):
    require(("ProgramDirector",))
    line = must_get("business_lines", business_line_id)
    shapes.body()
    if (line["status"] != "APPROVED"
            or line["training_slots_total"] < 1
            or line["supervisor_capacity"] < 1):
        fail("ERR_INVALID_STATE_TRANSITION", "Only an APPROVED business line may be launched.")
    set_fields(line, status="LAUNCHED", launched_at=store.now)
    derive.recompute_line_posture(line)
    return ok(dump(line))


@bp.route("/business-lines/<business_line_id>/outcome-summary", methods=["GET"])
def outcome_summary(business_line_id):
    require(("ProgramDirector", "CaseManager", "FunderAnalyst"))
    line = must_get("business_lines", business_line_id)
    measure = shapes.query_enum("retention_measure", C.RETENTION_MEASURES, "COHORT_BASED")
    default_start = line["launched_at"] or line["created_at"]
    period_start = shapes.query_datetime("period_start", default_start)
    period_end = shapes.query_datetime("period_end", store.now)

    cohort = [p for p in derive.participants_of_line(line["id"])
              if period_start <= p["enrolled_at"] <= period_end]
    cohort_ids = set(p["id"] for p in cohort)
    enrolled_count = len(cohort)
    placed_count = len([p for p in cohort if p["status"] in ("PLACED", "ALUMNI_RETAINED")])
    placement_rate = calc.ratio_or_none(placed_count, enrolled_count, 4)

    window_placements = [p for p in all_records("placements")
                         if p["participant_id"] in cohort_ids
                         and period_start <= p["hire_date"] <= period_end]

    if measure == "POINT_IN_TIME":
        denominator_rows = window_placements
        numerator_rows = [p for p in denominator_rows if p["employment_status"] == "ACTIVE"]
    else:
        denominator_rows = [p for p in window_placements
                            if p["hire_date"] + days(C.LATE_SEPARATION_DAYS) <= period_end]
        numerator_rows = [p for p in denominator_rows if p["retention_outcome"] == "RETAINED_180"]
    retention_denominator = len(denominator_rows)
    retention_numerator = len(numerator_rows)

    verified = [p for p in window_placements if p["wage_verification_status"] == "VERIFIED"]
    average_progression = None
    if verified:
        total = Decimal("0")
        for placement in verified:
            if placement["wage_progression_pct"] is not None:
                total += calc.dec(placement["wage_progression_pct"])
        average_progression = calc.rhu(total / calc.dec(len(verified)), 4)

    return ok(jsonable({
        "business_line_id": line["id"],
        "period_start": period_start,
        "period_end": period_end,
        "retention_measure": measure,
        "enrolled_count": enrolled_count,
        "placed_count": placed_count,
        "placement_rate": placement_rate,
        "retention_denominator": retention_denominator,
        "retention_numerator": retention_numerator,
        "retention_rate": calc.ratio_or_none(retention_numerator, retention_denominator, 4),
        "verified_placement_count": len(verified),
        "average_wage_progression_pct": average_progression,
    }))


# =========================================================================== #
# ReferralPartner
# =========================================================================== #

@bp.route("/referral-partners", methods=["POST"])
def create_referral_partner():
    require(("ProgramDirector",))
    payload = shapes.body()
    name = shapes.req_string(payload, "organization_name", 1, 120)
    tier = shapes.req_enum(payload, "mou_tier", C.MOU_TIERS)
    quota = shapes.req_int(payload, "referral_quota_per_period", 1)
    status = shapes.opt_enum(payload, "mou_status", C.MOU_STATUSES, "ACTIVE")
    partner = create_record("referral_partners", {
        "organization_name": name,
        "mou_tier": tier,
        "mou_status": status,
        "referral_quota_per_period": quota,
        "referrals_submitted_count": 0,
        "enrolled_referral_count": 0,
        "conversion_rate": None,
    })
    return created(dump(partner))


@bp.route("/referral-partners/<referral_partner_id>", methods=["GET"])
def read_referral_partner(referral_partner_id):
    require(("ProgramDirector", "IntakeSpecialist", "CaseManager", "FunderAnalyst", "ReferralPartner"))
    return ok(dump(must_get("referral_partners", referral_partner_id)))


# =========================================================================== #
# Referral
# =========================================================================== #

@bp.route("/referrals", methods=["POST"])
def submit_referral():
    user_id, _role = require(("ReferralPartner",))
    payload = shapes.body()
    partner = must_get("referral_partners", payload.get("referral_partner_id"))
    require_owner(partner["id"], user_id)
    reference = shapes.req_string(payload, "candidate_reference", 1, 64)
    declared = shapes.req_enum_list(payload, "declared_barrier_codes", C.BARRIER_CODES, 0, 7)
    income = shapes.req_int(payload, "household_income_cents", 0)
    size = shapes.req_int(payload, "household_size", 1)
    hours = shapes.req_int(payload, "hours_available_per_week", 0, 40)
    if partner["mou_status"] != "ACTIVE":
        fail("ERR_PARTNER_MOU_LAPSED", "The referring partner's MOU is not ACTIVE.")
    existing = derive.referrals_of_partner(partner["id"])
    if any(row["candidate_reference"] == reference for row in existing):
        fail("ERR_DUPLICATE_CANDIDATE_REFERENCE",
             "This partner has already submitted that candidate_reference.")
    window_start = store.now - days(C.REFERRAL_QUOTA_WINDOW_DAYS)
    recent = len([row for row in existing if row["created_at"] > window_start])
    if recent >= partner["referral_quota_per_period"]:
        fail("ERR_PARTNER_QUOTA_EXCEEDED",
             "The partner has reached its referral quota for the trailing 30 days.")
    referral = create_record("referrals", {
        "referral_partner_id": partner["id"],
        "candidate_reference": reference,
        "status": "SUBMITTED",
        "declared_barrier_codes": declared,
        "verified_barrier_codes": [],
        "household_income_cents": income,
        "household_size": size,
        "hours_available_per_week": hours,
        "fpl_ratio": None,
        "eligibility_score": None,
        "priority_band": None,
        "screened_at": None,
        "decided_by_user_id": None,
    })
    derive.recompute_partner(partner)
    return created(dump(referral))


@bp.route("/referrals/<referral_id>", methods=["GET"])
def read_referral(referral_id):
    user_id, role = require(("ProgramDirector", "IntakeSpecialist", "CaseManager",
                             "FunderAnalyst", "ReferralPartner"))
    referral = must_get("referrals", referral_id)
    if role == "ReferralPartner":
        require_owner(referral["referral_partner_id"], user_id)
    return ok(dump(referral))


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    require(("ProgramDirector", "IntakeSpecialist", "CaseManager", "FunderAnalyst"))
    partner = must_exist_filter("referral_partners", shapes.query_id("referral_partner_id"))
    status = shapes.query_enum("status", C.REFERRAL_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("referrals")
    if partner is not None:
        rows = [row for row in rows if row["referral_partner_id"] == partner["id"]]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/referrals/<referral_id>/screen", methods=["POST"])
def screen_referral(referral_id):
    user_id, _role = require(("IntakeSpecialist",))
    referral = must_get("referrals", referral_id)
    payload = shapes.body()
    decision = shapes.req_enum(payload, "decision", C.SCREEN_DECISIONS)
    codes = shapes.req_enum_list(payload, "verified_barrier_codes", C.BARRIER_CODES, 0, 7)
    income = shapes.req_int(payload, "verified_household_income_cents", 0)
    size = shapes.req_int(payload, "verified_household_size", 1)
    hours = shapes.req_int(payload, "verified_hours_available_per_week", 0, 40)
    if referral["status"] not in ("SUBMITTED", "WAITLISTED"):
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a SUBMITTED or WAITLISTED referral may be screened.")
    partner = store.referral_partners[referral["referral_partner_id"]]
    ratio, score = calc.eligibility_score(codes, income, size, hours, partner["mou_tier"])
    if decision == "ELIGIBLE":
        if (len(set(codes)) < 1
                or hours < C.MIN_WEEKLY_AVAILABILITY_HOURS
                or score < C.ELIGIBILITY_SCORE_FLOOR):
            fail("ERR_ELIGIBILITY_SCORE_BELOW_FLOOR",
                 "An ELIGIBLE decision requires at least one verified barrier, 20 available hours "
                 "and an eligibility_score of at least 50.00.")
    if partner["mou_status"] != "ACTIVE":
        fail("ERR_PARTNER_MOU_LAPSED", "The referring partner's MOU is not ACTIVE.")
    set_fields(referral,
               verified_barrier_codes=codes,
               household_income_cents=income,
               household_size=size,
               hours_available_per_week=hours,
               fpl_ratio=ratio,
               eligibility_score=score,
               priority_band=calc.priority_band(score),
               screened_at=store.now,
               decided_by_user_id=user_id,
               status=decision)
    return ok(dump(referral))


# =========================================================================== #
# Participant
# =========================================================================== #

@bp.route("/participants", methods=["POST"])
def enroll_participant():
    require(("IntakeSpecialist",))
    payload = shapes.body()
    referral = must_get("referrals", payload.get("referral_id"))
    line = must_get("business_lines", payload.get("business_line_id"))
    wage = shapes.req_int(payload, "wage_cents_per_hour")
    expected_version = shapes.req_int(payload, "expected_business_line_version")
    weeks = shapes.opt_int(payload, "max_transitional_weeks",
                           C.MIN_MAX_TRANSITIONAL_WEEKS, C.MAX_MAX_TRANSITIONAL_WEEKS,
                           C.DEFAULT_MAX_TRANSITIONAL_WEEKS)
    consumed = any(row["referral_id"] == referral["id"] for row in all_records("participants"))
    if referral["status"] != "ELIGIBLE" and not consumed:
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ELIGIBLE referral may be enrolled.")
    if line["version"] != expected_version:
        fail("ERR_STALE_BUSINESS_LINE_VERSION",
             "expected_business_line_version does not match the business line's current version.")
    if line["status"] != "LAUNCHED" or line["intake_posture"] != "OPEN":
        fail("ERR_INTAKE_CLOSED", "The business line is not accepting new enrollments.")
    if consumed:
        fail("ERR_REFERRAL_ALREADY_ENROLLED", "A participant already references this referral.")
    if wage < C.PROGRAM_MIN_TRAINEE_WAGE_CENTS or wage > C.PROGRAM_MAX_TRAINEE_WAGE_CENTS:
        fail("ERR_TRAINEE_WAGE_OUT_OF_RANGE",
             "wage_cents_per_hour must be between 1500 and 2200.")
    participant = create_record("participants", {
        "referral_id": referral["id"],
        "business_line_id": line["id"],
        "status": "TRANSITIONAL_EMPLOYED",
        "wage_cents_per_hour": wage,
        "max_transitional_weeks": weeks,
        "enrolled_at": store.now,
        "transitional_hours_worked": Decimal("0.000"),
        "scheduled_hours_current_week": Decimal("0.000"),
        "support_activity_minutes": 0,
        "delivered_coaching_count": 0,
        "readiness_certified_by_user_id": None,
        "readiness_certified_at": None,
        "graduated_at": None,
        "graduation_wage_cents_per_hour": None,
        "re_entry_count": 0,
        "eligible_re_entry_at": None,
    })
    set_fields(referral, status="ENROLLED")
    derive.recompute_partner(store.referral_partners[referral["referral_partner_id"]])
    derive.recompute_line_posture(line)
    return created(dump(participant))


@bp.route("/participants/<participant_id>", methods=["GET"])
def read_participant(participant_id):
    require(READ_PROGRAM_ROLES)
    return ok(dump(must_get("participants", participant_id)))


@bp.route("/participants", methods=["GET"])
def list_participants():
    require(READ_PROGRAM_ROLES)
    line = must_exist_filter("business_lines", shapes.query_id("business_line_id"))
    referral = must_exist_filter("referrals", shapes.query_id("referral_id"))
    status = shapes.query_enum("status", C.PARTICIPANT_STATUSES)
    limit, offset = read_pagination(request.args)
    rows = all_records("participants")
    if line is not None:
        rows = [row for row in rows if row["business_line_id"] == line["id"]]
    if referral is not None:
        rows = [row for row in rows if row["referral_id"] == referral["id"]]
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return ok_list(dump_many(paginate(rows, limit, offset)), limit, offset, len(rows))


@bp.route("/participants/<participant_id>/certify-readiness", methods=["POST"])
def certify_readiness(participant_id):
    user_id, _role = require(("JobCoach",))
    participant = must_get("participants", participant_id)
    shapes.body()
    if participant["status"] != "TRANSITIONAL_EMPLOYED":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a TRANSITIONAL_EMPLOYED participant may be certified.")
    if (calc.dec(participant["transitional_hours_worked"]) < C.MIN_TRANSITIONAL_HOURS
            or participant["support_activity_minutes"] < C.MIN_SUPPORT_MINUTES
            or participant["delivered_coaching_count"] < C.MIN_COACHING_SESSIONS):
        fail("ERR_GRADUATION_CRITERIA_NOT_MET",
             "Readiness requires 24.000 hours worked, 180 support minutes and 2 delivered coaching sessions.")
    set_fields(participant,
               status="READY_FOR_GRADUATION",
               readiness_certified_by_user_id=user_id,
               readiness_certified_at=store.now)
    derive.recompute_line_posture(store.business_lines[participant["business_line_id"]])
    return ok(dump(participant))


@bp.route("/participants/<participant_id>/graduate", methods=["POST"])
def graduate_participant(participant_id):
    user_id, _role = require(("CaseManager",))
    participant = must_get("participants", participant_id)
    shapes.body()
    holds_seat = any(row["status"] == "ASSIGNED"
                     for row in derive.assignments_of_participant(participant["id"]))
    if participant["status"] != "READY_FOR_GRADUATION" or holds_seat:
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a READY_FOR_GRADUATION participant holding no ASSIGNED seat may graduate.")
    if user_id == participant["readiness_certified_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The graduating case manager may not be the user who certified readiness.")
    set_fields(participant,
               status="GRADUATED",
               graduated_at=store.now,
               graduation_wage_cents_per_hour=participant["wage_cents_per_hour"])
    derive.recompute_line_posture(store.business_lines[participant["business_line_id"]])
    return ok(dump(participant))


@bp.route("/participants/<participant_id>/re-enter", methods=["POST"])
def re_enter_participant(participant_id):
    require(("IntakeSpecialist",))
    participant = must_get("participants", participant_id)
    payload = shapes.body()
    wage = shapes.req_int(payload, "wage_cents_per_hour")
    line = store.business_lines[participant["business_line_id"]]
    if participant["status"] != "RE_ENTRY_ELIGIBLE":
        fail("ERR_INVALID_STATE_TRANSITION",
             "Only a RE_ENTRY_ELIGIBLE participant may re-enter.")
    if line["status"] != "LAUNCHED" or line["intake_posture"] != "OPEN":
        fail("ERR_INTAKE_CLOSED", "The business line is not accepting new enrollments.")
    if participant["re_entry_count"] >= C.RE_ENTRY_LIMIT:
        fail("ERR_RE_ENTRY_LIMIT_REACHED", "The participant has reached the re-entry limit of two.")
    if wage < C.PROGRAM_MIN_TRAINEE_WAGE_CENTS or wage > C.PROGRAM_MAX_TRAINEE_WAGE_CENTS:
        fail("ERR_TRAINEE_WAGE_OUT_OF_RANGE",
             "wage_cents_per_hour must be between 1500 and 2200.")
    set_fields(participant,
               status="TRANSITIONAL_EMPLOYED",
               re_entry_count=participant["re_entry_count"] + 1,
               enrolled_at=store.now,
               wage_cents_per_hour=wage,
               readiness_certified_by_user_id=None,
               readiness_certified_at=None,
               graduated_at=None,
               graduation_wage_cents_per_hour=None,
               eligible_re_entry_at=None)
    derive.recompute_line_posture(line)
    return ok(dump(participant))
