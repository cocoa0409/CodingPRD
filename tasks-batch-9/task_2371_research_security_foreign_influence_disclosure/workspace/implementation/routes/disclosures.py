"""The disclosure cycle: drafting, review, certification and plans."""

from decimal import Decimal

from flask import Blueprint

import db
import response
import util
import validate
from errors import ApiError
from middleware import CRO, INVESTIGATOR, RSO, require, require_any
from routes.common import must_exist, render_list
from services import cascade, derive, enums as E, present

bp = Blueprint("disclosures", __name__)

LIVE_REVIEW_STATES = ("DRAFT", "SUBMITTED", "UNDER_REVIEW",
                      "RETURNED_FOR_REVISION")


def _owner_guard(role, user_id, investigator_id):
    if role == INVESTIGATOR and user_id != investigator_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "The acting investigator does not own this resource.")


@bp.post("/disclosures")
def create_disclosure():
    user_id, role = require(INVESTIGATOR, RSO)
    data = validate.body()

    # step 3 — ownership for Investigator-role callers
    raw_investigator = data.get("investigator_id")
    if role == INVESTIGATOR and isinstance(raw_investigator, str):
        _owner_guard(role, user_id, raw_investigator)

    # step 5 — body foreign keys
    investigator = must_exist("investigator", raw_investigator)

    cycle_label = validate.req_string(data, "cycle_label")
    disclosure_type = validate.req_enum(data, "disclosure_type",
                                        E.DISCLOSURE_TYPES)
    expected = data.get("expected_investigator_version")
    if expected is None:
        validate.bad("Field 'expected_investigator_version' is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        validate.bad("Field 'expected_investigator_version' must be an integer.")

    # step 8 — parent version match
    if expected != investigator["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "Investigator version is %d." % investigator["version"])

    # step 15 — uniqueness of the live disclosure for this cycle
    siblings = [d for d in derive.investigator_disclosures(investigator["id"])
                if d["cycle_label"] == cycle_label]
    if any(d["review_status"] in ("CERTIFIED", "REJECTED") for d in siblings):
        raise ApiError("ERR_DUPLICATE_DISCLOSURE_CYCLE",
                       "A terminal disclosure already exists for cycle '%s'."
                       % cycle_label)

    record = db.base_record()
    record.update({
        "investigator_id": investigator["id"],
        "cycle_label": cycle_label,
        "disclosure_type": disclosure_type,
        "review_status": "DRAFT",
        "plan_status": "NOT_REQUIRED",
        "revision_round": 0,
        "item_count": 0,
        "late_item_count": 0,
        "undisclosed_item_count": 0,
        "completeness_score": 100,
        "completeness_tier": "A",
        "submitted_at": None,
        "certified_at": None,
        "reviewer_user_id": None,
        "plan_effort_cap_pct": None,
        "plan_required_actions": [],
        "plan_effective_from": None,
        "plan_expires_on": None,
        "plan_approver_user_id": None,
        "plan_acknowledged_at": None,
    })
    db.disclosures[record["id"]] = record

    for sibling in siblings:
        if sibling["review_status"] in LIVE_REVIEW_STATES:
            sibling["review_status"] = "SUPERSEDED"
            db.touch(sibling)

    cascade.recompute_investigator(investigator)
    return response.object_response(present.disclosure(record), 201)


@bp.get("/disclosures/<disclosure_id>")
def read_disclosure(disclosure_id):
    require_any()
    record = must_exist("disclosure", disclosure_id)
    return response.object_response(present.disclosure(record))


@bp.get("/disclosures")
def list_disclosures():
    require_any()
    investigator_id = validate.filter_value("investigator_id")
    review_status = validate.filter_enum("review_status", E.REVIEW_STATUSES)
    plan_status = validate.filter_enum("plan_status", E.PLAN_STATUSES)

    rows = []
    for record in db.ordered(db.disclosures.values()):
        if investigator_id and record["investigator_id"] != investigator_id:
            continue
        if review_status and record["review_status"] != review_status:
            continue
        if plan_status and record["plan_status"] != plan_status:
            continue
        rows.append(record)
    return render_list(rows, present.disclosure)


# ------------------------------------------------------------------- submit

@bp.post("/disclosures/<disclosure_id>/submit")
def submit_disclosure(disclosure_id):
    user_id, role = require(INVESTIGATOR)
    record = must_exist("disclosure", disclosure_id)
    _owner_guard(role, user_id, record["investigator_id"])

    if record["review_status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                       "A %s disclosure cannot be submitted."
                       % record["review_status"])

    investigator = db.investigators.get(record["investigator_id"])
    if investigator is not None and derive.posture_of(investigator) == "SUSPENDED":
        raise ApiError("ERR_INVESTIGATOR_SUSPENDED",
                       "A SUSPENDED investigator cannot submit a disclosure.")
    if derive.has_disputed_items(record["id"]):
        raise ApiError("ERR_DISPUTED_ITEMS_OPEN",
                       "Disputed items remain on this disclosure.")

    record["review_status"] = "SUBMITTED"
    record["submitted_at"] = db.clock_str()
    cascade.recompute_disclosure(record)
    cascade.recompute_investigator(investigator)
    return response.object_response(present.disclosure(record))


# ------------------------------------------------------------------- review

@bp.post("/disclosures/<disclosure_id>/review")
def review_disclosure(disclosure_id):
    user_id, _role = require(RSO, CRO)
    data = validate.body()
    record = must_exist("disclosure", disclosure_id)

    action = validate.req_enum(data, "action", E.REVIEW_ACTIONS)
    validate.opt_string(data, "review_note")

    status = record["review_status"]

    def assigned_reviewer_guard():
        if record["reviewer_user_id"] is not None and \
                record["reviewer_user_id"] != user_id:
            raise ApiError("ERR_NOT_ASSIGNED_REVIEWER",
                           "Only the assigned reviewer may act on this disclosure.")

    if action == "BEGIN_REVIEW":
        if status != "SUBMITTED":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "BEGIN_REVIEW requires a SUBMITTED disclosure.")
        assigned_reviewer_guard()
        record["review_status"] = "UNDER_REVIEW"
        if record["reviewer_user_id"] is None:
            record["reviewer_user_id"] = user_id
        db.touch(record)

    elif action == "RETURN_FOR_REVISION":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "RETURN_FOR_REVISION requires an UNDER_REVIEW disclosure.")
        assigned_reviewer_guard()
        record["review_status"] = "RETURNED_FOR_REVISION"
        record["revision_round"] = record["revision_round"] + 1
        cascade.recompute_disclosure(record)

    elif action == "REQUIRE_PLAN":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "REQUIRE_PLAN requires an UNDER_REVIEW disclosure.")
        if record["plan_status"] != "NOT_REQUIRED":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "The plan dimension is already at %s."
                           % record["plan_status"])
        assigned_reviewer_guard()
        investigator = db.investigators.get(record["investigator_id"])
        if investigator is not None:
            derive.compute_investigator(investigator)
        warranted = False
        if investigator is not None:
            if util.dec(investigator["total_commitment_pct"]) > Decimal("100"):
                warranted = True
            if investigator["risk_score"] >= 30:
                warranted = True
        for item in derive.disclosure_items(record["id"]):
            if item["item_type"] == "TALENT_PROGRAM" and \
                    item["status"] in ("DECLARED", "VERIFIED"):
                warranted = True
                break
        if not warranted:
            raise ApiError("ERR_PLAN_NOT_WARRANTED",
                           "No conflict-of-commitment trigger is present.")
        record["plan_status"] = "PLAN_REQUIRED"
        db.touch(record)
        cascade.recompute_investigator(investigator)

    elif action == "CERTIFY":
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "CERTIFY requires an UNDER_REVIEW disclosure.")
        assigned_reviewer_guard()
        derive.compute_disclosure(record)
        if record["completeness_score"] < E.MIN_CERTIFY_SCORE:
            raise ApiError("ERR_COMPLETENESS_TOO_LOW",
                           "completeness_score %d is below %d."
                           % (record["completeness_score"], E.MIN_CERTIFY_SCORE))
        if record["plan_status"] not in ("NOT_REQUIRED", "PLAN_WAIVED",
                                        "PLAN_ACKNOWLEDGED"):
            raise ApiError("ERR_PLAN_NOT_RESOLVED",
                           "The management plan is not resolved (%s)."
                           % record["plan_status"])
        if derive.has_disputed_items(record["id"]):
            raise ApiError("ERR_DISPUTED_ITEMS_OPEN",
                           "Disputed items remain on this disclosure.")
        record["review_status"] = "CERTIFIED"
        record["certified_at"] = db.clock_str()
        db.touch(record)
        for item in derive.disclosure_items(record["id"]):
            if item["status"] == "DECLARED":
                item["status"] = "VERIFIED"
                derive.compute_item(item)
                db.touch(item)
        cascade.recompute_disclosure(record)
        investigator = db.investigators.get(record["investigator_id"])
        cascade.recompute_investigator(investigator)
        cascade.recompute_projects_for_investigator(record["investigator_id"])

    else:  # REJECT
        if status != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "REJECT requires an UNDER_REVIEW disclosure.")
        assigned_reviewer_guard()
        if record["revision_round"] < 2:
            raise ApiError("ERR_REJECT_TOO_EARLY",
                           "At least two revision rounds are required.")
        record["review_status"] = "REJECTED"
        db.touch(record)
        for item in derive.disclosure_items(record["id"]):
            if item["status"] in ("DECLARED", "DISPUTED"):
                item["status"] = "WITHDRAWN"
                db.touch(item)
        cascade.recompute_disclosure(record)
        cascade.recompute_investigator(
            db.investigators.get(record["investigator_id"]))

    return response.object_response(present.disclosure(record))


# --------------------------------------------------------------------- plan

@bp.post("/disclosures/<disclosure_id>/plan")
def plan_disclosure(disclosure_id):
    user_id, role = require(CRO, INVESTIGATOR)
    data = validate.body()
    record = must_exist("disclosure", disclosure_id)

    action = validate.req_enum(data, "action", E.PLAN_ACTIONS)
    if action == "ACKNOWLEDGE":
        if role != INVESTIGATOR:
            raise ApiError("ERR_UNAUTHORIZED",
                           "Only the subject investigator may acknowledge a plan.")
        _owner_guard(role, user_id, record["investigator_id"])
    elif role != CRO:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Only a ConflictReviewOfficial may %s a plan." % action)

    plan_status = record["plan_status"]
    investigator = db.investigators.get(record["investigator_id"])

    if action == "ISSUE":
        # step 6 — shape before the transition and SoD checks
        cap = validate.req_decimal(data, "plan_effort_cap_pct", minimum=0)
        actions = data.get("plan_required_actions")
        if actions is None:
            validate.bad("Field 'plan_required_actions' is required.")
        actions = validate.opt_enum_list(data, "plan_required_actions",
                                         E.PLAN_REQUIRED_ACTIONS, default=[])
        effective_from = validate.req_instant(data, "plan_effective_from")
        expires_on = validate.req_instant(data, "plan_expires_on")

        if plan_status != "PLAN_REQUIRED":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "ISSUE requires plan_status PLAN_REQUIRED.")
        if record["reviewer_user_id"] is not None and \
                record["reviewer_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The reviewing officer may not issue the plan.")
        if util.parse_dt(expires_on) <= util.parse_dt(effective_from):
            raise ApiError("ERR_INVALID_PLAN_WINDOW",
                           "plan_expires_on must be strictly after "
                           "plan_effective_from.")

        record["plan_status"] = "PLAN_ISSUED"
        record["plan_effort_cap_pct"] = cap
        record["plan_required_actions"] = actions
        record["plan_effective_from"] = effective_from
        record["plan_expires_on"] = expires_on
        record["plan_approver_user_id"] = user_id
        db.touch(record)

    elif action == "ACKNOWLEDGE":
        if plan_status != "PLAN_ISSUED":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "ACKNOWLEDGE requires plan_status PLAN_ISSUED.")
        record["plan_status"] = "PLAN_ACKNOWLEDGED"
        record["plan_acknowledged_at"] = db.clock_str()
        db.touch(record)
        cascade.recompute_investigator(investigator)

    elif action == "WAIVE":
        if plan_status != "PLAN_REQUIRED":
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "WAIVE requires plan_status PLAN_REQUIRED.")
        if record["reviewer_user_id"] is not None and \
                record["reviewer_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The reviewing officer may not waive the plan.")
        if investigator is not None:
            derive.compute_investigator(investigator)
            if util.dec(investigator["total_commitment_pct"]) > Decimal("100"):
                raise ApiError("ERR_PLAN_NOT_WARRANTED",
                               "The investigator is still over-committed.")
        for item in derive.disclosure_items(record["id"]):
            if item["item_type"] == "TALENT_PROGRAM" and \
                    item["status"] in ("DECLARED", "VERIFIED"):
                raise ApiError("ERR_PLAN_NOT_WARRANTED",
                               "A talent-programme relationship is still live.")
        record["plan_status"] = "PLAN_WAIVED"
        db.touch(record)
        cascade.recompute_investigator(investigator)

    else:  # TERMINATE
        if plan_status not in ("PLAN_ISSUED", "PLAN_ACKNOWLEDGED"):
            raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                           "TERMINATE requires an issued or acknowledged plan.")
        record["plan_status"] = "PLAN_TERMINATED"
        db.touch(record)
        cascade.recompute_investigator(investigator)

    return response.object_response(present.disclosure(record))


# -------------------------------------------------------------------- items

@bp.post("/disclosures/<disclosure_id>/items")
def create_item(disclosure_id):
    user_id, role = require(INVESTIGATOR, RSO)
    data = validate.body()
    disclosure = must_exist("disclosure", disclosure_id)
    _owner_guard(role, user_id, disclosure["investigator_id"])

    # step 5 — body foreign keys resolve before the shape checks
    organization = must_exist("organization", data.get("foreign_organization_id"))

    item_type = validate.req_enum(data, "item_type", E.ITEM_TYPES)
    start_date = validate.req_instant(data, "start_date")
    annual_effort_hours = validate.opt_decimal(data, "annual_effort_hours",
                                              minimum=0, maximum=2080,
                                              default=Decimal("0"))
    compensation = validate.opt_int(data, "compensation_usd_cents", minimum=0,
                                    default=0)
    in_kind = validate.opt_int(data, "in_kind_value_cents", minimum=0, default=0)
    end_date = validate.opt_instant(data, "end_date")
    is_paid = validate.opt_bool(data, "is_paid", default=False)
    source = validate.opt_enum(data, "source", E.ITEM_SOURCES,
                               default="SELF_REPORTED")

    if disclosure["review_status"] not in ("DRAFT", "RETURNED_FOR_REVISION"):
        raise ApiError("ERR_INVALID_DISCLOSURE_TRANSITION",
                       "Items may only be added to a DRAFT or "
                       "RETURNED_FOR_REVISION disclosure.")

    record = db.base_record()
    record.update({
        "disclosure_id": disclosure["id"],
        "item_type": item_type,
        "foreign_organization_id": organization["id"],
        "annual_effort_hours": annual_effort_hours,
        "compensation_usd_cents": compensation,
        "in_kind_value_cents": in_kind,
        "start_date": start_date,
        "end_date": end_date,
        "is_paid": is_paid,
        "item_risk_points": 0,
        "status": "DECLARED",
        "source": source,
        "_late_at_create": disclosure["revision_round"] >= 1,
    })
    derive.compute_item(record)
    db.items[record["id"]] = record
    cascade.recompute_disclosure(disclosure)
    return response.object_response(present.item(record), 201)
