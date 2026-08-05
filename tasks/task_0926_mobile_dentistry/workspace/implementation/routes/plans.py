"""Treatment plans, the follow-up cadence and the referral loop."""

from flask import Blueprint

import calc
import clock
import gates
import serializers
import store
import validation as v
from constants import (
    ENUM_RESPONSE_OUTCOME,
    REFERRAL_MAX_ATTEMPTS,
    REFERRAL_NO_RESPONSE_DAYS,
)
from envelope import array_response, object_response
from errors import ApiError
from timefmt import add_days

bp = Blueprint("plans", __name__)


def _plan_site(plan):
    encounter = store.get("encounters", plan["encounter_id"])
    if encounter is None:
        return None
    visit = store.get("site_visits", encounter["site_visit_id"])
    if visit is None:
        return None
    return store.get("sites", visit["site_id"])


# --------------------------------------------------------------------------
# POST /mobile-dentistry/treatment-plans
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/treatment-plans", methods=["POST"])
def create_treatment_plan():
    v.authenticate(["FieldDentist", "FieldHygienist"])
    body = v.body()
    encounter = v.fk_row(body, "encounter_id", "encounters")
    patient = v.fk_row(body, "patient_id", "patients")
    author = v.fk_row(body, "authoring_staff_id", "staff_members")

    for field in ("encounter_id", "patient_id", "authoring_staff_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    planned_codes = v.req_string_array(body, "planned_procedure_codes", default=[])

    if patient["id"] != encounter["patient_id"]:
        raise ApiError("ERR_VALIDATION", "patient_id must equal the encounter's patient_id.")

    visit = store.get("site_visits", encounter["site_visit_id"])
    gates.period_gate(visit["program_period_id"])

    row = store.insert("treatment_plans", {
        "encounter_id": encounter["id"],
        "patient_id": patient["id"],
        "authoring_staff_id": author["id"],
        "plan_status": "DRAFT",
        "urgency_band": encounter["triage_band"],
        "planned_procedure_codes": planned_codes,
        "activated_on": None,
        "follow_up_due_date": None,
        "follow_up_status": "NOT_DUE",
        "last_contact_at": None,
        "contact_attempt_count": 0,
        "superseded_reason": None,
    })
    v.mark_minted(row)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.treatment_plan(row), 201)


@bp.route("/mobile-dentistry/treatment-plans", methods=["GET"])
def list_treatment_plans():
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "BillingSpecialist",
    ])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("treatment_plans"), {
        "encounter_id": "encounter_id",
        "patient_id": "patient_id",
        "authoring_staff_id": "authoring_staff_id",
        "plan_status": "plan_status",
    })
    follow_up_filter = None
    from flask import request
    raw = request.args.get("follow_up_status")
    if raw:
        follow_up_filter = raw
        rows = [r for r in rows if serializers.treatment_plan(r)["follow_up_status"] == follow_up_filter]
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.treatment_plan, page), limit, offset, total)


@bp.route("/mobile-dentistry/treatment-plans/<plan_id>", methods=["GET"])
def read_treatment_plan(plan_id):
    v.authenticate([
        "ProgramAdmin", "SiteCoordinator", "FieldDentist",
        "FieldHygienist", "BillingSpecialist",
    ])
    row = v.path_row("treatment_plans", plan_id)
    return object_response(serializers.treatment_plan(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/treatment-plans/{id}/activate
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/treatment-plans/<plan_id>/activate", methods=["POST"])
def activate_treatment_plan(plan_id):
    v.authenticate(["FieldDentist"])
    row = v.path_row("treatment_plans", plan_id)
    encounter = store.get("encounters", row["encounter_id"])
    visit = store.get("site_visits", encounter["site_visit_id"])

    gates.period_gate(visit["program_period_id"])

    if row["plan_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if encounter["clinical_status"] not in ("EXAMINED", "TREATED", "CLOSED"):
        raise ApiError("ERR_INVALID_STATE")

    row["plan_status"] = "ACTIVE"
    row["activated_on"] = clock.today()
    row["follow_up_due_date"] = calc.follow_up_due_date(row)
    row["follow_up_status"] = calc.follow_up_status(row)
    v.touch(row)
    gates.mark_period_reports_stale(visit["program_period_id"])
    return object_response(serializers.treatment_plan(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/treatment-plans/{id}/follow-up-contact
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/treatment-plans/<plan_id>/follow-up-contact", methods=["POST"])
def record_follow_up_contact(plan_id):
    v.authenticate(["SiteCoordinator", "FieldDentist", "FieldHygienist"])
    row = v.path_row("treatment_plans", plan_id)
    body = v.body()
    v.opt_string(body, "contact_note")

    if row["plan_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    row["last_contact_at"] = clock.now()
    row["contact_attempt_count"] += 1
    row["follow_up_due_date"] = calc.follow_up_due_date(row)
    row["follow_up_status"] = "CONTACTED"
    v.touch(row)
    return object_response(serializers.treatment_plan(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/referrals
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/referrals", methods=["POST"])
def create_referral():
    v.authenticate(["FieldDentist", "SiteCoordinator"])
    body = v.body()
    plan = v.fk_row(body, "treatment_plan_id", "treatment_plans")
    patient = v.fk_row(body, "patient_id", "patients")

    for field in ("treatment_plan_id", "patient_id"):
        v.need(body, field)
        if not isinstance(body.get(field), str):
            raise ApiError("ERR_VALIDATION", "Field '%s' must be a string." % field)
    dental_home_name = v.req_string(body, "dental_home_name")

    if patient["id"] != plan["patient_id"]:
        raise ApiError("ERR_VALIDATION", "patient_id must equal the plan's patient_id.")

    row = store.insert("referrals", {
        "treatment_plan_id": plan["id"],
        "patient_id": patient["id"],
        "dental_home_name": dental_home_name,
        "status": "OPEN",
        "attempt_count": 0,
        "due_at": None,
        "last_sent_at": None,
        "next_eligible_send_at": None,
        "abandoned_at": None,
        "abandon_reason": None,
        "case_management_opened_at": None,
    })
    v.mark_minted(row)
    return object_response(serializers.referral(row), 201)


@bp.route("/mobile-dentistry/referrals", methods=["GET"])
def list_referrals():
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "FieldDentist", "BillingSpecialist"])
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all_rows("referrals"), {
        "treatment_plan_id": "treatment_plan_id",
        "patient_id": "patient_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return array_response(serializers.many(serializers.referral, page), limit, offset, total)


@bp.route("/mobile-dentistry/referrals/<referral_id>", methods=["GET"])
def read_referral(referral_id):
    v.authenticate(["ProgramAdmin", "SiteCoordinator", "FieldDentist", "BillingSpecialist"])
    row = v.path_row("referrals", referral_id)
    return object_response(serializers.referral(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/referrals/{id}/send
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/referrals/<referral_id>/send", methods=["POST"])
def send_referral(referral_id):
    v.authenticate(["FieldDentist", "SiteCoordinator"])
    row = v.path_row("referrals", referral_id)
    body = v.body()
    dental_home_name = v.opt_string(body, "dental_home_name")

    plan = store.get("treatment_plans", row["treatment_plan_id"])

    # Rung 11 -- a send is declared only out of OPEN, NO_RESPONSE and DECLINED.
    if row["status"] not in ("OPEN", "NO_RESPONSE", "DECLINED"):
        raise ApiError("ERR_INVALID_STATE")
    if row["status"] == "OPEN" and plan["plan_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    # Rung 33 -- the re-send waiting period, NO_RESPONSE only.
    if row["status"] == "NO_RESPONSE":
        if row["next_eligible_send_at"] is not None and clock.now() < row["next_eligible_send_at"]:
            raise ApiError("ERR_REFERRAL_NOT_DUE")

    # Rung 34 -- the attempt cap, mutate-then-reject.
    if row["status"] in ("NO_RESPONSE", "DECLINED") and row["attempt_count"] >= REFERRAL_MAX_ATTEMPTS:
        now = clock.now()
        row["status"] = "ABANDONED"
        row["abandoned_at"] = now
        row["case_management_opened_at"] = now
        row["abandon_reason"] = "ATTEMPT_CAP_REACHED"
        v.touch(row)
        raise ApiError("ERR_REFERRAL_CAP_REACHED")

    now = clock.now()
    first_send = row["attempt_count"] == 0
    if dental_home_name is not None:
        row["dental_home_name"] = dental_home_name
    row["status"] = "SENT"
    row["attempt_count"] += 1
    row["last_sent_at"] = now
    row["next_eligible_send_at"] = add_days(now, REFERRAL_NO_RESPONSE_DAYS)
    if first_send:
        site = _plan_site(plan)
        site_type = site["site_type"] if site else "SCHOOL"
        row["due_at"] = calc.referral_due_at(now, plan["urgency_band"], site_type)
    v.touch(row)
    return object_response(serializers.referral(row), 200)


# --------------------------------------------------------------------------
# POST /mobile-dentistry/referrals/{id}/record-response
# --------------------------------------------------------------------------
@bp.route("/mobile-dentistry/referrals/<referral_id>/record-response", methods=["POST"])
def record_referral_response(referral_id):
    v.authenticate(["FieldDentist", "SiteCoordinator"])
    row = v.path_row("referrals", referral_id)
    body = v.body()
    v.enum_type_check(body, "outcome", required=True)
    outcome = v.check_enum(body, "outcome", ENUM_RESPONSE_OUTCOME)

    if outcome == "COMPLETED":
        if row["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if row["status"] != "SENT":
            raise ApiError("ERR_INVALID_STATE")

    row["status"] = outcome
    v.touch(row)

    if outcome == "COMPLETED":
        plan = store.get("treatment_plans", row["treatment_plan_id"])
        if plan is not None and plan["plan_status"] == "ACTIVE":
            plan["plan_status"] = "COMPLETED"
            plan["follow_up_due_date"] = None
            plan["follow_up_status"] = "CONTACTED"
            v.touch(plan)

    return object_response(serializers.referral(row), 200)
