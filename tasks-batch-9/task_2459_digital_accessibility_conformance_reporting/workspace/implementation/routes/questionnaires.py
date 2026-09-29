"""Procurement questionnaires: accuracy obligations and disclosure debt (PRD 3.10)."""
from decimal import Decimal

from flask import Blueprint

from calc import UPDATE_CADENCE_DAYS
from db import db, dt_plus_days, iso_plus_days, new_row, now_iso, sort_key, touch
from derive import recompute_product, refresh_questionnaire
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from response import list_response, obj_response
from serialize import questionnaire_out
from validate import (
    ACCURACY_STATUSES,
    QUESTIONNAIRE_KINDS,
    REVIEW_STATUSES,
    body,
    fk_product,
    fk_report,
    pagination,
    paginate,
    path_questionnaire,
    q_enum,
    q_str,
    v_enum,
    v_str,
)

bp = Blueprint("questionnaires", __name__)


@bp.post("/questionnaire-responses")
@endpoint(["CustomerLiaison"])
def create_questionnaire():
    data = body()
    product = fk_product(data.get("product_id"))     # step 5
    report = fk_report(data.get("report_id"))        # step 5

    v_str(data, "product_id", required=True, min_len=1)
    v_str(data, "report_id", required=True, min_len=1)
    customer_name = v_str(data, "customer_name", required=True, min_len=1, max_len=160)
    kind = v_enum(data, "questionnaire_kind", QUESTIONNAIRE_KINDS, required=True)
    answers = v_str(data, "answers_summary", required=True, min_len=10, max_len=4000)

    # step 33: the cited report must belong to the named product
    if report["product_id"] != product["id"]:
        raise ApiError("ERR_CROSS_PRODUCT_REFERENCE",
                       "Report %s does not belong to product %s"
                       % (report["id"], product["id"]))

    row = new_row({
        "product_id": product["id"],
        "report_id": report["id"],
        "customer_name": customer_name,
        "questionnaire_kind": kind,
        "answers_summary": answers,
        "review_status": "DRAFT",
        "accuracy_status": "CURRENT",
        "disclosure_debt": Decimal("0.00"),
        "disclosure_tier": "STANDARD",
        "submitted_at": None,
        "last_attested_at": None,
        "update_due_at": None,
        "correction_due_at": None,
        "revision_count": 0,
    })
    row["_last_attested_dt"] = None
    row["_update_due_dt"] = None
    db.questionnaires[row["id"]] = row
    return obj_response(questionnaire_out(row), 201)


@bp.get("/questionnaire-responses/<questionnaire_id>")
@endpoint(ALL_ROLES)
def get_questionnaire(questionnaire_id):
    return obj_response(questionnaire_out(path_questionnaire(questionnaire_id)))


@bp.get("/questionnaire-responses")
@endpoint(ALL_ROLES)
def list_questionnaires():
    product_id = q_str("product_id")
    report_id = q_str("report_id")
    review_status = q_enum("review_status", REVIEW_STATUSES)
    accuracy_status = q_enum("accuracy_status", ACCURACY_STATUSES)
    limit, offset = pagination()
    rows = list(db.questionnaires.values())
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if report_id is not None:
        rows = [r for r in rows if r["report_id"] == report_id]
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    if accuracy_status is not None:
        rows = [r for r in rows if r["accuracy_status"] == accuracy_status]
    rows.sort(key=sort_key)
    page, total = paginate(rows, limit, offset)
    return list_response([questionnaire_out(r) for r in page], limit, offset, total)


@bp.post("/questionnaire-responses/<questionnaire_id>/submit")
@endpoint(["CustomerLiaison"])
def submit_questionnaire(questionnaire_id):
    questionnaire = path_questionnaire(questionnaire_id)
    body()

    # step 12: from-state
    if questionnaire["review_status"] != "DRAFT":
        raise ApiError("ERR_QUESTIONNAIRE_NOT_DRAFT",
                       "Questionnaire response %s is %s"
                       % (questionnaire["id"], questionnaire["review_status"]))

    questionnaire["review_status"] = "SUBMITTED"
    questionnaire["submitted_at"] = now_iso()
    refresh_questionnaire(questionnaire)
    touch(questionnaire)
    return obj_response(questionnaire_out(questionnaire))


@bp.post("/questionnaire-responses/<questionnaire_id>/attest")
@endpoint(["AccessibilityLead"])
def attest_questionnaire(questionnaire_id):
    questionnaire = path_questionnaire(questionnaire_id)
    data = body()
    v_str(data, "accuracy_attestation", required=True, min_len=1, max_len=2000)

    product = db.products[questionnaire["product_id"]]
    report = db.reports[questionnaire["report_id"]]

    # step 12: from-state
    if questionnaire["review_status"] != "SUBMITTED":
        raise ApiError("ERR_QUESTIONNAIRE_NOT_SUBMITTED",
                       "Questionnaire response %s is %s"
                       % (questionnaire["id"], questionnaire["review_status"]))
    # step 15: posture must not be FROZEN
    if product["publication_posture"] == "FROZEN":
        raise ApiError("ERR_PRODUCT_POSTURE_FROZEN",
                       "Product %s is FROZEN" % product["id"])
    # step 17: posture must be exactly OPEN
    if product["publication_posture"] != "OPEN":
        raise ApiError("ERR_PRODUCT_POSTURE_NOT_OPEN",
                       "Product %s is %s" % (product["id"],
                                             product["publication_posture"]))
    # step 30: the cited report must be published
    if report["state"] != "PUBLISHED":
        raise ApiError("ERR_REPORT_NOT_PUBLISHED",
                       "Report %s is %s" % (report["id"], report["state"]))

    questionnaire["review_status"] = "ATTESTED"
    questionnaire["last_attested_at"] = now_iso()
    questionnaire["_last_attested_dt"] = db.clock
    questionnaire["accuracy_status"] = "CURRENT"
    questionnaire["correction_due_at"] = None
    questionnaire["update_due_at"] = iso_plus_days(UPDATE_CADENCE_DAYS)
    questionnaire["_update_due_dt"] = dt_plus_days(UPDATE_CADENCE_DAYS)
    refresh_questionnaire(questionnaire)
    touch(questionnaire)

    recompute_product(product)
    return obj_response(questionnaire_out(questionnaire))


@bp.post("/questionnaire-responses/<questionnaire_id>/revise")
@endpoint(["CustomerLiaison"])
def revise_questionnaire(questionnaire_id):
    questionnaire = path_questionnaire(questionnaire_id)
    data = body()
    answers = v_str(data, "answers_summary", required=True, min_len=10, max_len=4000)

    # step 12: from-state
    if questionnaire["review_status"] not in ("SUBMITTED", "ATTESTED"):
        raise ApiError("ERR_QUESTIONNAIRE_NOT_REVISABLE",
                       "Questionnaire response %s is %s"
                       % (questionnaire["id"], questionnaire["review_status"]))

    questionnaire["answers_summary"] = answers
    questionnaire["review_status"] = "SUBMITTED"
    questionnaire["revision_count"] += 1
    questionnaire["submitted_at"] = now_iso()
    questionnaire["accuracy_status"] = "CURRENT"
    questionnaire["update_due_at"] = None
    questionnaire["_update_due_dt"] = None
    questionnaire["correction_due_at"] = None
    refresh_questionnaire(questionnaire)
    touch(questionnaire)

    product = db.products[questionnaire["product_id"]]
    recompute_product(product)
    return obj_response(questionnaire_out(questionnaire))
