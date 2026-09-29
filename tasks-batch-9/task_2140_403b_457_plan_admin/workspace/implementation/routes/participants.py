"""Participants, universal availability notices and eligibility determinations."""
from flask import Blueprint, g, request

import auth
import calc
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("participants", __name__)


@bp.post("/plan-admin/participants")
@endpoint(["PlanSponsorAdmin"])
def create_participant():
    body = V.body_of(request)
    employer_id = V.req_str(body, "employer_id")
    full_name = V.req_str(body, "full_name")
    date_of_birth = V.req_date(body, "date_of_birth")
    hire_date = V.req_date(body, "hire_date")
    scheduled_hours_per_week = V.req_num(body, "scheduled_hours_per_week", minimum=0)
    prior_year_hours_worked = V.req_int(body, "prior_year_hours_worked", minimum=0)
    includible_compensation_cents = V.req_int(body, "includible_compensation_cents", minimum=0)
    years_of_service = V.req_num(body, "years_of_service", minimum=0)
    employment_status = V.opt_enum(body, "employment_status", calc.EMPLOYMENT_STATUSES, "ACTIVE")
    termination_date = V.opt_date(body, "termination_date")
    is_student = V.opt_bool(body, "is_student_performing_services", False)
    is_nra = V.opt_bool(body, "is_nonresident_alien_no_us_income", False)
    is_hce = V.opt_bool(body, "is_select_management_or_hce", False)
    prior_employer = V.opt_int(body, "prior_employer_elective_deferrals_cents", 0, minimum=0)
    underutilized = V.opt_int(body, "underutilized_prior_limit_cents", 0, minimum=0)
    cumulative = V.opt_int(body, "cumulative_special_catchup_used_cents", 0, minimum=0)

    auth.employer(employer_id)                      # rung 5
    auth.require(employer_id == g.user_id)          # rung 6

    row = store.common_fields()
    row.update({
        "employer_id": employer_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth.isoformat(),
        "hire_date": hire_date.isoformat(),
        "employment_status": employment_status,
        "termination_date": V.date_str(termination_date),
        "scheduled_hours_per_week": scheduled_hours_per_week,
        "prior_year_hours_worked": prior_year_hours_worked,
        "is_student_performing_services": is_student,
        "is_nonresident_alien_no_us_income": is_nra,
        "is_select_management_or_hce": is_hce,
        "includible_compensation_cents": includible_compensation_cents,
        "years_of_service": years_of_service,
        "prior_employer_elective_deferrals_cents": prior_employer,
        "underutilized_prior_limit_cents": underutilized,
        "cumulative_special_catchup_used_cents": cumulative,
        "lifetime_elective_deferrals_cents": prior_employer,
        "ytd_elective_deferrals_all_vendors_cents": 0,
        "total_accumulated_benefit_cents": 0,
        "total_vested_balance_cents": 0,
        "total_outstanding_loan_balance_cents": 0,
        "highest_outstanding_loan_12mo_cents": 0,
        "loan_eligibility_flag": "AVAILABLE",
        "projected_annual_deferral_cents": 0,
    })
    store.participants[row["id"]] = row
    return envelope.created(serialize.participant(row))


@bp.get("/plan-admin/participants/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_participant(row_id):
    return envelope.ok(serialize.participant(auth.participant(row_id)))


@bp.get("/plan-admin/participants")
@endpoint(auth.ALL_ROLES)
def list_participants():
    args = request.args
    limit, offset = V.pagination(args)
    employer_id = args.get("employer_id")
    employment_status = V.query_enum(args, "employment_status", calc.EMPLOYMENT_STATUSES)
    items = store.rows(store.participants)
    if employer_id:
        items = [p for p in items if p["employer_id"] == employer_id]
    if employment_status:
        items = [p for p in items if p["employment_status"] == employment_status]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.participant(p) for p in page], limit, offset, total)


@bp.patch("/plan-admin/participants/<row_id>")
@endpoint(["PlanSponsorAdmin"])
def patch_participant(row_id):
    body = V.body_of(request)
    scheduled = V.opt_num(body, "scheduled_hours_per_week", minimum=0)
    prior_hours = V.opt_int(body, "prior_year_hours_worked", minimum=0)
    employment_status = V.opt_enum(body, "employment_status", calc.EMPLOYMENT_STATUSES)
    has_termination_date = "termination_date" in body
    termination_date = V.opt_date(body, "termination_date")
    comp = V.opt_int(body, "includible_compensation_cents", minimum=0)
    years = V.opt_num(body, "years_of_service", minimum=0)
    is_hce = V.opt_bool(body, "is_select_management_or_hce")
    is_student = V.opt_bool(body, "is_student_performing_services")
    is_nra = V.opt_bool(body, "is_nonresident_alien_no_us_income")

    participant = auth.participant(row_id)
    auth.own_participant(participant)

    if scheduled is not None:
        participant["scheduled_hours_per_week"] = scheduled
    if prior_hours is not None:
        participant["prior_year_hours_worked"] = prior_hours
    if employment_status is not None:
        participant["employment_status"] = employment_status
    if has_termination_date:
        participant["termination_date"] = V.date_str(termination_date)
    if comp is not None:
        participant["includible_compensation_cents"] = comp
    if years is not None:
        participant["years_of_service"] = years
    if is_hce is not None:
        participant["is_select_management_or_hce"] = is_hce
    if is_student is not None:
        participant["is_student_performing_services"] = is_student
    if is_nra is not None:
        participant["is_nonresident_alien_no_us_income"] = is_nra
    store.touch(participant)
    return envelope.ok(serialize.participant(participant))


# ---------------------------------------------- universal availability notices
@bp.post("/plan-admin/plans/<plan_id>/universal-availability-notices")
@endpoint(["PlanSponsorAdmin"])
def create_notice(plan_id):
    body = V.body_of(request)
    plan_year = V.req_int(body, "plan_year", minimum=2000, maximum=2100)
    issued_date = V.req_date(body, "issued_date")
    delivery_method = V.req_enum(body, "delivery_method", calc.DELIVERY_METHODS)
    recipient_count = V.req_int(body, "recipient_count", minimum=0)
    describes = V.req_bool(body, "describes_effective_opportunity")

    plan = auth.plan(plan_id)                        # rung 4
    auth.own_plan(plan)                              # rung 6
    if plan["status"] not in ("ACTIVE", "FROZEN"):   # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    if issued_date > store.today():                  # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "issued_date is in the future.")
    for existing in store.notices_of(plan_id):       # rung 34
        if existing["plan_year"] == plan_year:
            raise ApiError("ERR_DUPLICATE_UA_NOTICE",
                           "A notice already exists for this plan and plan year.")

    row = store.bare_fields()
    row.update({
        "plan_id": plan_id,
        "plan_year": plan_year,
        "issued_date": issued_date.isoformat(),
        "delivery_method": delivery_method,
        "recipient_count": recipient_count,
        "describes_effective_opportunity": describes,
    })
    row["is_valid"] = calc.notice_is_valid(row, plan)
    store.ua_notices[row["id"]] = row
    return envelope.created(serialize.notice(row))


@bp.get("/plan-admin/plans/<plan_id>/universal-availability-notices")
@endpoint(auth.ALL_ROLES)
def list_notices(plan_id):
    args = request.args
    limit, offset = V.pagination(args)
    plan_year = V.query_int(args, "plan_year")
    auth.plan(plan_id)
    items = store.notices_of(plan_id)
    if plan_year is not None:
        items = [n for n in items if n["plan_year"] == plan_year]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.notice(n) for n in page], limit, offset, total)


# ------------------------------------------------- eligibility determinations
@bp.post("/plan-admin/eligibility-determinations")
@endpoint(["ComplianceOfficer"])
def create_determination():
    body = V.body_of(request)
    plan_id = V.req_str(body, "plan_id")
    participant_id = V.req_str(body, "participant_id")
    asserted = V.opt_enum(body, "asserted_exclusion", calc.ASSERTED_EXCLUSIONS, "NONE")

    plan = auth.plan(plan_id)                        # rung 5
    participant = auth.participant(participant_id)   # rung 5

    status = calc.eligibility_status(plan, participant)
    if asserted != "NONE" and calc.ASSERTION_TO_STATUS[asserted] != status:   # rung 17
        raise ApiError("ERR_UA_EXCLUSION_NOT_PERMITTED",
                       "The participant's facts do not support the asserted exclusion.")
    notice_status, ua_applies = calc.notice_status_for(plan)

    for earlier in store.rows(store.eligibility_determinations):
        if earlier["plan_id"] == plan_id and earlier["participant_id"] == participant_id:
            if not earlier["superseded"]:
                earlier["superseded"] = True
                store.touch(earlier)

    row = store.common_fields()
    row.update({
        "plan_id": plan_id,
        "participant_id": participant_id,
        "asserted_exclusion": asserted,
        "determined_at": store.now_ts(),
        "determined_by_user_id": g.user_id,
        "status": status,
        "exclusion_basis": calc.EXCLUSION_BASIS.get(status),
        "notice_status": notice_status,
        "universal_availability_applies": ua_applies,
        "superseded": False,
    })
    store.eligibility_determinations[row["id"]] = row
    return envelope.created(serialize.determination(row))


@bp.get("/plan-admin/eligibility-determinations/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_determination(row_id):
    return envelope.ok(serialize.determination(auth.determination(row_id)))


@bp.get("/plan-admin/eligibility-determinations")
@endpoint(auth.ALL_ROLES)
def list_determinations():
    args = request.args
    limit, offset = V.pagination(args)
    plan_id = args.get("plan_id")
    participant_id = args.get("participant_id")
    status = V.query_enum(args, "status", calc.DETERMINATION_STATUSES)
    superseded = V.query_bool(args, "superseded")
    items = store.rows(store.eligibility_determinations)
    if plan_id:
        items = [d for d in items if d["plan_id"] == plan_id]
    if participant_id:
        items = [d for d in items if d["participant_id"] == participant_id]
    if status:
        items = [d for d in items if d["status"] == status]
    if superseded is not None:
        items = [d for d in items if d["superseded"] == superseded]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.determination(d) for d in page], limit, offset, total)


# --------------------------------------------------------- computed reads
@bp.get("/plan-admin/participants/<row_id>/contribution-limit-summary")
@endpoint(auth.ALL_ROLES)
def contribution_limit_summary(row_id):
    args = request.args
    plan_id = args.get("plan_id")
    if not plan_id:
        raise V.bad("Query parameter 'plan_id' is required.")
    plan_year = V.query_int(args, "plan_year")
    participant = auth.participant(row_id)
    plan = auth.plan(plan_id)
    employer = store.employers.get(plan["employer_id"])
    agg = calc.deferral_limit_aggregate_402g(plan, participant, employer)
    annual_additions, annual_limit = calc.annual_additions_415c(plan, participant)
    data = {
        "participant_id": participant["id"],
        "plan_id": plan["id"],
        "plan_year": plan_year if plan_year is not None else plan["plan_year"],
        "bucket_plan_type": agg["bucket"],
        "basic_limit_cents": calc.BASIC_ELECTIVE_DEFERRAL_LIMIT_CENTS,
        "service_15yr_catchup_capacity_cents": agg["service_15yr"],
        "age50_catchup_capacity_cents": agg["age_50"],
        "final_3yr_catchup_capacity_cents": agg["final_3yr"],
        "usable_catchup_capacity_cents": agg["usable_catchup"],
        "total_limit_cents": agg["total_limit"],
        "ytd_gross_cents": agg["ytd_gross"],
        "ytd_verified_cents": agg["ytd_verified"],
        "room_gross_cents": agg["room_gross"],
        "room_verified_cents": agg["room_verified"],
        "lifetime_elective_deferrals_cents": participant["lifetime_elective_deferrals_cents"],
        "annual_additions_cents": annual_additions,
        "annual_additions_limit_cents": annual_limit,
        "included_vendor_account_ids": [va["id"] for va in agg["accounts_all"]],
        "verified_vendor_account_ids": [va["id"] for va in agg["accounts_verified"]],
    }
    return envelope.ok(data)


@bp.get("/plan-admin/participants/<row_id>/loan-capacity")
@endpoint(auth.ALL_ROLES)
def loan_capacity(row_id):
    args = request.args
    plan_id = args.get("plan_id")
    if not plan_id:
        raise V.bad("Query parameter 'plan_id' is required.")
    participant = auth.participant(row_id)
    plan = auth.plan(plan_id)
    result = calc.loan_maximum_available(participant, plan)
    data = {
        "participant_id": participant["id"],
        "plan_id": plan["id"],
        "vested_total_cents": result["vested_total_cents"],
        "outstanding_total_cents": result["outstanding_total_cents"],
        "highest_outstanding_12mo_cents": result["highest_outstanding_12mo_cents"],
        "cap_statutory_cents": result["cap_statutory_cents"],
        "cap_vested_cents": result["cap_vested_cents"],
        "maximum_loan_cents": result["maximum_loan_cents"],
        "loan_eligibility_flag": participant["loan_eligibility_flag"],
        "included_vendor_account_ids": result["included_vendor_account_ids"],
        "unverified_vendor_account_ids": result["unverified_vendor_account_ids"],
    }
    return envelope.ok(data)
