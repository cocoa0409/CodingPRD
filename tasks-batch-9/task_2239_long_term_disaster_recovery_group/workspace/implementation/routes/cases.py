"""Survivors, recovery cases and everything hanging off a case (PRD 3.1-3.3, 3.9)."""

from flask import Blueprint

import db
import lookups
import middleware as mw
import response
from constants import (
    ASSESSMENT_VARIANTS,
    ASSISTANCE_SOURCE_TYPES,
    BUCKET_OF_CATEGORY,
    CASE_STATUSES,
    CATEGORY_CAP_CENTS,
    CONTACT_OUTCOMES,
    CONTACT_TYPES,
    DAMAGE_CATEGORIES,
    DOCUMENTATION_STATUSES,
    FUNDING_STATUSES,
    INCOME_BANDS,
    PURPOSE_CODES,
    RESIDENCE_STATUSES,
    ROLE_ADMIN,
    ROLE_CASE_MANAGER,
    ROLE_CHAIR,
    ROLE_CONSTRUCTION,
    ROLE_INTAKE,
    ROLE_OFFICER,
    VERIFICATION_OUTCOMES,
)
from errors import ApiError
from services import calculations as calc
from services import rollups

bp = Blueprint("cases", __name__)

ASSESSABLE_STATUSES = ("INTAKE", "ASSESSED", "PRESENTED", "ACTIVE_RECOVERY")


# ---------------------------------------------------------------------------
# Survivor
# ---------------------------------------------------------------------------
@bp.post("/survivors")
def create_survivor():
    mw.authorize((ROLE_INTAKE, ROLE_ADMIN))
    body = mw.get_body()
    record = db.base_record()
    record.update(
        {
            "household_name": mw.req_str(body, "household_name"),
            "primary_contact_phone": mw.req_str(body, "primary_contact_phone"),
            "household_size": mw.req_int(body, "household_size", minimum=1),
            "income_band": mw.req_enum(body, "income_band", INCOME_BANDS),
            "head_of_household_age": mw.req_int(
                body, "head_of_household_age", minimum=18
            ),
            "has_member_with_disability": mw.opt_bool(
                body, "has_member_with_disability", False
            ),
            "is_uninsured": mw.opt_bool(body, "is_uninsured", False),
            "consent_on_file": mw.opt_bool(body, "consent_on_file", False),
            "follow_up_opt_in": mw.opt_bool(body, "follow_up_opt_in", True),
            "priority_score": 0,
            "open_case_count": 0,
        }
    )
    record["priority_score"] = calc.survivor_priority_score(record)
    db.survivors[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/survivors/<sid>")
def get_survivor(sid):
    mw.authorize(
        (ROLE_INTAKE, ROLE_CASE_MANAGER, ROLE_CHAIR, ROLE_OFFICER, ROLE_ADMIN)
    )
    return response.object_response(lookups.survivor(sid))


# ---------------------------------------------------------------------------
# RecoveryCase
# ---------------------------------------------------------------------------
@bp.post("/recovery-cases")
def create_case():
    mw.authorize((ROLE_INTAKE, ROLE_ADMIN))
    body = mw.get_body()
    survivor_id = mw.req_id(body, "survivor_id")
    disaster_code = mw.req_str(body, "disaster_code")
    manager = mw.req_str(body, "assigned_case_manager_user_id")
    residence = mw.req_enum(body, "primary_residence_status", RESIDENCE_STATUSES)
    housing_need = mw.opt_int(body, "temporary_housing_need_cents", 0, minimum=0)

    survivor = lookups.survivor(survivor_id)

    record = db.base_record()
    record.update(
        {
            "survivor_id": survivor_id,
            "disaster_code": disaster_code,
            "assigned_case_manager_user_id": manager,
            "primary_residence_status": residence,
            "temporary_housing_need_cents": housing_need,
            "case_status": "INTAKE",
            "funding_status": "UNFUNDED",
            "verified_damage_total_cents": 0,
            "reference_unmet_cents": 0,
            "total_committed_cents": 0,
            "total_net_disbursed_cents": 0,
            "residual_unmet_cents": 0,
            "closure_waiver_reason": None,
            "reopen_count": 0,
            "withdrawn_reason": None,
        }
    )
    db.recovery_cases[record["id"]] = record
    rollups.recompute_survivor(survivor)
    return response.object_response(record, 201)


@bp.get("/recovery-cases/<cid>")
def get_case(cid):
    mw.authorize(
        (
            ROLE_INTAKE,
            ROLE_CASE_MANAGER,
            ROLE_CHAIR,
            ROLE_OFFICER,
            ROLE_CONSTRUCTION,
            ROLE_ADMIN,
        )
    )
    return response.object_response(lookups.case(cid))


@bp.get("/recovery-cases")
def list_cases():
    mw.authorize(
        (ROLE_INTAKE, ROLE_CASE_MANAGER, ROLE_CHAIR, ROLE_OFFICER, ROLE_ADMIN)
    )
    limit, offset = mw.pagination()
    survivor_id = mw.query_str("survivor_id")
    case_status = mw.query_enum("case_status", CASE_STATUSES)
    funding_status = mw.query_enum("funding_status", FUNDING_STATUSES)
    disaster_code = mw.query_str("disaster_code")

    rows = db.sorted_records(list(db.recovery_cases.values()))
    if survivor_id is not None:
        rows = [r for r in rows if r["survivor_id"] == survivor_id]
    if case_status is not None:
        rows = [r for r in rows if r["case_status"] == case_status]
    if funding_status is not None:
        rows = [r for r in rows if r["funding_status"] == funding_status]
    if disaster_code is not None:
        rows = [r for r in rows if r["disaster_code"] == disaster_code]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# DamageItem
# ---------------------------------------------------------------------------
@bp.post("/recovery-cases/<cid>/damage-items")
def create_damage_item(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    category = mw.req_enum(body, "category", DAMAGE_CATEGORIES)
    description = mw.req_str(body, "item_description")
    documented = mw.req_int(body, "documented_cost_cents", minimum=0)
    photo_count = mw.opt_int(body, "photo_count", 0, minimum=0)
    critical = mw.opt_bool(body, "is_habitability_critical", False)

    case = lookups.case(cid)
    if case["case_status"] not in ASSESSABLE_STATUSES:
        raise ApiError("ERR_CASE_NOT_ASSESSABLE")

    record = db.base_record()
    record.update(
        {
            "case_id": case["id"],
            "category": category,
            "item_description": description,
            "documented_cost_cents": documented,
            "photo_count": photo_count,
            "is_habitability_critical": critical,
            "verification_status": "UNVERIFIED",
            "verified_cost_cents": None,
            "capped_cost_cents": 0,
            "purpose_bucket": BUCKET_OF_CATEGORY[category],
            "verified_by_user_id": None,
        }
    )
    db.damage_items[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/recovery-cases/<cid>/damage-items")
def list_damage_items(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_CONSTRUCTION, ROLE_CHAIR, ROLE_ADMIN))
    limit, offset = mw.pagination()
    status = mw.query_enum("verification_status", ("UNVERIFIED", "VERIFIED", "REJECTED"))
    category = mw.query_enum("category", DAMAGE_CATEGORIES)

    case = lookups.case(cid)
    rows = db.sorted_records(
        [d for d in db.damage_items.values() if d["case_id"] == case["id"]]
    )
    if status is not None:
        rows = [r for r in rows if r["verification_status"] == status]
    if category is not None:
        rows = [r for r in rows if r["category"] == category]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/damage-items/<did>/verification")
def verify_damage_item(did):
    user_id, _role = mw.authorize((ROLE_CONSTRUCTION, ROLE_ADMIN))
    body = mw.get_body()
    outcome = mw.req_enum(body, "verification_status", VERIFICATION_OUTCOMES)
    verified_cost = mw.req_int(body, "verified_cost_cents", minimum=0)

    item = lookups.damage_item(did)
    if item["verification_status"] != "UNVERIFIED":
        raise ApiError("ERR_DAMAGE_ITEM_ALREADY_VERIFIED")

    db.set_field(item, "verification_status", outcome)
    db.set_field(item, "verified_cost_cents", verified_cost)
    db.set_field(item, "verified_by_user_id", user_id)
    if outcome == "VERIFIED":
        db.set_field(
            item,
            "capped_cost_cents",
            min(verified_cost, CATEGORY_CAP_CENTS[item["category"]]),
        )
    else:
        db.set_field(item, "capped_cost_cents", 0)

    case = db.recovery_cases.get(item["case_id"])
    if case is not None:
        rollups.recompute_case_damage_total(case)
        db.mark(case)
    return response.object_response(item)


# ---------------------------------------------------------------------------
# AssistanceRecord
# ---------------------------------------------------------------------------
@bp.post("/recovery-cases/<cid>/assistance-records")
def create_assistance_record(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    source_type = mw.req_enum(body, "source_type", ASSISTANCE_SOURCE_TYPES)
    purpose_code = mw.req_enum(body, "purpose_code", PURPOSE_CODES)
    awarded = mw.req_int(body, "awarded_cents", minimum=0)
    received_on = mw.req_date(body, "received_on")
    documentation = mw.opt_enum(
        body, "documentation_status", DOCUMENTATION_STATUSES, "UNDOCUMENTED"
    )

    case = lookups.case(cid)
    if case["case_status"] not in ASSESSABLE_STATUSES:
        raise ApiError("ERR_CASE_NOT_ASSESSABLE")

    record = db.base_record()
    record.update(
        {
            "case_id": case["id"],
            "source_type": source_type,
            "purpose_code": purpose_code,
            "awarded_cents": awarded,
            "received_on": received_on,
            "documentation_status": documentation,
            "is_excluded_from_dob": False,
            "exclusion_note": None,
        }
    )
    db.assistance_records[record["id"]] = record
    db.mark(case)
    return response.object_response(record, 201)


@bp.get("/recovery-cases/<cid>/assistance-records")
def list_assistance_records(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_OFFICER, ROLE_CHAIR, ROLE_ADMIN))
    limit, offset = mw.pagination()
    purpose_code = mw.query_enum("purpose_code", PURPOSE_CODES)
    documentation = mw.query_enum("documentation_status", DOCUMENTATION_STATUSES)

    case = lookups.case(cid)
    rows = db.sorted_records(
        [a for a in db.assistance_records.values() if a["case_id"] == case["id"]]
    )
    if purpose_code is not None:
        rows = [r for r in rows if r["purpose_code"] == purpose_code]
    if documentation is not None:
        rows = [r for r in rows if r["documentation_status"] == documentation]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# UnmetNeedAssessment
# ---------------------------------------------------------------------------
@bp.post("/recovery-cases/<cid>/assessments")
def create_assessment(cid):
    user_id, _role = mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    variant = mw.req_enum(body, "variant", ASSESSMENT_VARIANTS)

    case = lookups.case(cid)
    if case["case_status"] not in ASSESSABLE_STATUSES:
        raise ApiError("ERR_CASE_NOT_ASSESSABLE")
    has_verified = any(
        d["verification_status"] == "VERIFIED"
        for d in calc.case_damage_items(case["id"])
    )
    if not has_verified:
        raise ApiError("ERR_NO_VERIFIED_DAMAGE")

    figures = calc.unmet_need_determination(case, variant)
    record = db.base_record(with_version=False)
    record.update(
        {
            "case_id": case["id"],
            "variant": variant,
            "verified_damage_total_cents": figures["verified_damage_total_cents"],
            "total_documented_assistance_cents": figures[
                "total_documented_assistance_cents"
            ],
            "bucket_need_cents": figures["bucket_need_cents"],
            "bucket_offset_cents": figures["bucket_offset_cents"],
            "unmet_need_total_cents": figures["unmet_need_total_cents"],
            "prepared_by_user_id": user_id,
        }
    )
    db.assessments[record["id"]] = record

    if case["case_status"] == "INTAKE":
        db.set_field(case, "case_status", "ASSESSED")
    db.mark(case)
    return response.object_response(record, 201)


@bp.get("/recovery-cases/<cid>/assessments")
def list_assessments(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_CHAIR, ROLE_OFFICER, ROLE_ADMIN))
    limit, offset = mw.pagination()
    variant = mw.query_enum("variant", ASSESSMENT_VARIANTS)

    case = lookups.case(cid)
    rows = db.sorted_records(
        [a for a in db.assessments.values() if a["case_id"] == case["id"]]
    )
    if variant is not None:
        rows = [r for r in rows if r["variant"] == variant]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Duplication-of-benefits computed read
# ---------------------------------------------------------------------------
@bp.get("/recovery-cases/<cid>/dob-report")
def dob_report(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_OFFICER, ROLE_ADMIN))
    purpose_code = mw.query_req_enum("purpose_code", PURPOSE_CODES)
    requested = mw.query_int("requested_cents", 0, minimum=0)

    case = lookups.case(cid)
    figures = calc.dob_exposure_check(case, purpose_code, requested)
    payload = {
        "case_id": case["id"],
        "survivor_id": case["survivor_id"],
        "purpose_code": purpose_code,
        "dob_pool_cents": figures["dob_pool_cents"],
        "prior_disbursed_cents": figures["prior_disbursed_cents"],
        "bucket_need_cents": figures["bucket_need_cents"],
        "dob_exposure_cents": figures["dob_exposure_cents"],
        "sibling_case_ids": figures["sibling_case_ids"],
    }
    return response.object_response(payload)


# ---------------------------------------------------------------------------
# Closure, withdrawal, reopening
# ---------------------------------------------------------------------------
def _case_projects(case_id):
    return [p for p in db.projects.values() if p["case_id"] == case_id]


def _case_follow_ups(case_id):
    return [f for f in db.follow_ups.values() if f["case_id"] == case_id]


@bp.post("/recovery-cases/<cid>/closure-review")
def closure_review(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    mw.opt_str(body, "review_note")

    case = lookups.case(cid)
    if case["case_status"] != "ACTIVE_RECOVERY":
        raise ApiError("ERR_CASE_INVALID_STATE")
    if case["funding_status"] != "SATISFIED":
        raise ApiError("ERR_CLOSURE_CRITERIA_NOT_MET")
    for project in _case_projects(case["id"]):
        if project["status"] not in ("CLOSED_OUT", "CANCELLED"):
            raise ApiError("ERR_CLOSURE_CRITERIA_NOT_MET")
    if not _case_follow_ups(case["id"]):
        raise ApiError("ERR_CLOSURE_CRITERIA_NOT_MET")

    db.set_field(case, "case_status", "CLOSURE_PENDING")
    return response.object_response(case)


@bp.post("/recovery-cases/<cid>/close")
def close_case(cid):
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    waiver = mw.opt_str(body, "closure_waiver_reason", allow_empty=False)
    withdrawn = mw.opt_str(body, "withdrawn_reason", allow_empty=False)

    case = lookups.case(cid)

    if withdrawn is not None:
        if case["case_status"] not in ("INTAKE", "ASSESSED"):
            raise ApiError("ERR_CASE_INVALID_STATE")
        if case["case_status"] == "INTAKE":
            blocking = [
                p
                for p in db.presentations.values()
                if p["case_id"] == case["id"]
                and p["status"] in ("QUEUED", "PRESENTING", "DELIBERATING", "AWARDED")
            ]
            if blocking:
                raise ApiError("ERR_CASE_INVALID_STATE")
        db.set_field(case, "case_status", "INACTIVE")
        db.set_field(case, "withdrawn_reason", withdrawn)
        rollups.recompute_survivor(db.survivors.get(case["survivor_id"]))
        return response.object_response(case)

    if case["case_status"] != "CLOSURE_PENDING":
        raise ApiError("ERR_CASE_INVALID_STATE")
    if case["residual_unmet_cents"] != 0 and not waiver:
        raise ApiError("ERR_CLOSURE_CRITERIA_NOT_MET")
    has_review = any(
        f["contact_type"] == "CLOSURE_REVIEW" for f in _case_follow_ups(case["id"])
    )
    if not has_review:
        raise ApiError("ERR_CLOSURE_CRITERIA_NOT_MET")

    if waiver is not None:
        db.set_field(case, "closure_waiver_reason", waiver)
    db.set_field(case, "case_status", "CLOSED")
    rollups.recompute_survivor(db.survivors.get(case["survivor_id"]))
    return response.object_response(case)


@bp.post("/recovery-cases/<cid>/reopen")
def reopen_case(cid):
    mw.authorize((ROLE_ADMIN,))
    body = mw.get_body()
    mw.req_str(body, "reopen_reason")

    case = lookups.case(cid)
    if case["case_status"] != "CLOSED":
        raise ApiError("ERR_CASE_INVALID_STATE")

    db.set_field(case, "case_status", "ACTIVE_RECOVERY")
    db.set_field(case, "reopen_count", case["reopen_count"] + 1)
    rollups.recompute_survivor(db.survivors.get(case["survivor_id"]))
    return response.object_response(case)


# ---------------------------------------------------------------------------
# FollowUpContact
# ---------------------------------------------------------------------------
@bp.post("/recovery-cases/<cid>/follow-ups")
def create_follow_up(cid):
    user_id, _role = mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    body = mw.get_body()
    contact_type = mw.req_enum(body, "contact_type", CONTACT_TYPES)
    contacted_on = mw.req_date(body, "contacted_on")
    outcome = mw.req_enum(body, "outcome", CONTACT_OUTCOMES)
    notes = mw.req_str(body, "notes", allow_empty=True)

    case = lookups.case(cid)
    record = db.base_record(with_version=False)
    record.update(
        {
            "case_id": case["id"],
            "contact_type": contact_type,
            "contacted_on": contacted_on,
            "outcome": outcome,
            "notes": notes,
            "recorded_by_user_id": user_id,
        }
    )
    db.follow_ups[record["id"]] = record
    return response.object_response(record, 201)


@bp.get("/recovery-cases/<cid>/follow-ups")
def list_follow_ups(cid):
    mw.authorize((ROLE_CASE_MANAGER, ROLE_ADMIN))
    limit, offset = mw.pagination()
    contact_type = mw.query_enum("contact_type", CONTACT_TYPES)

    case = lookups.case(cid)
    rows = db.sorted_records(
        [f for f in db.follow_ups.values() if f["case_id"] == case["id"]]
    )
    if contact_type is not None:
        rows = [r for r in rows if r["contact_type"] == contact_type]

    page, total = response.paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)
