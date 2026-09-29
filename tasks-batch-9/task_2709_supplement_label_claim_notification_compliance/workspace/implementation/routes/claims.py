"""Claim development, review submission, approval, withdrawal and notification."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("claims", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_REVIEWER,
    auth.ROLE_APPROVAL,
    auth.ROLE_QA,
    auth.ROLE_AUDITOR,
)

REWORDABLE_STATES = ("DRAFT", "REVISION_REQUESTED")


def _duplicate_text(product_id, text, exclude_id=None):
    for claim in db.all_rows("claims"):
        if claim["product_id"] != product_id:
            continue
        if claim["substantiation_status"] == "WITHDRAWN":
            continue
        if exclude_id is not None and claim["id"] == exclude_id:
            continue
        if claim["claim_text"] == text:
            return True
    return False


@bp.route(PREFIX + "/claims", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_claim():
    body = validate.body()
    product_id = validate.req_str(body, "product_id")
    ingredient_id = validate.req_str(body, "ingredient_id")
    claim_text = validate.req_str(body, "claim_text")
    claim_type = validate.req_enum(body, "claim_type", calc.CLAIM_TYPES)

    fk_row("products", product_id, errors.ERR_PRODUCT_NOT_FOUND)
    fk_row("ingredients", ingredient_id, errors.ERR_INGREDIENT_NOT_FOUND)

    if _duplicate_text(product_id, claim_text):
        fail(
            errors.ERR_DUPLICATE_CLAIM_TEXT,
            "This claim text is already in use on the product.",
        )

    row = db.base_fields()
    row.update(
        {
            "product_id": product_id,
            "ingredient_id": ingredient_id,
            "claim_text": claim_text,
            "claim_type": claim_type,
            "substantiation_status": "DRAFT",
            "notification_status": "NOT_DUE",
            "authored_by_user_id": auth.user_id(),
            "approved_by_user_id": None,
            "approved_at": None,
            "notification_due_date": None,
            "notification_due_basis": None,
            "notified_at": None,
            "submission_reference": None,
            "revision_round": 0,
            "requires_recheck": False,
            "withdrawal_reason": None,
        }
    )
    db.insert("claims", row)
    return response.object_response(serialize.claim(row), 201)


@bp.route(PREFIX + "/claims/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_claim(row_id):
    row = path_row("claims", row_id, errors.ERR_CLAIM_NOT_FOUND)
    return response.object_response(serialize.claim(row))


@bp.route(PREFIX + "/claims", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_claims():
    return listing(
        "claims",
        serialize.claim,
        filters=("product_id", "ingredient_id", "substantiation_status", "notification_status"),
    )


@bp.route(PREFIX + "/claims/<row_id>", methods=["PATCH"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def reword_claim(row_id):
    row = path_row("claims", row_id, errors.ERR_CLAIM_NOT_FOUND)
    body = validate.body()

    sentinel = object()
    claim_text = validate.opt_str(body, "claim_text", default=sentinel, allow_null=False)
    claim_type = validate.opt_enum(
        body, "claim_type", calc.CLAIM_TYPES, default=sentinel, allow_null=False
    )

    if row["substantiation_status"] not in REWORDABLE_STATES:
        fail(
            errors.ERR_CLAIM_STATE_INVALID,
            "Only a DRAFT or REVISION_REQUESTED claim may be reworded.",
        )
    if claim_text is not sentinel and _duplicate_text(
        row["product_id"], claim_text, exclude_id=row["id"]
    ):
        fail(
            errors.ERR_DUPLICATE_CLAIM_TEXT,
            "This claim text is already in use on the product.",
        )

    if claim_text is not sentinel:
        row["claim_text"] = claim_text
    if claim_type is not sentinel:
        row["claim_type"] = claim_type
    db.touch(row)
    return response.object_response(serialize.claim(row))


@bp.route(PREFIX + "/claims/<row_id>/submit-for-review", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def submit_for_review(row_id):
    row = path_row("claims", row_id, errors.ERR_CLAIM_NOT_FOUND)
    if row["substantiation_status"] not in REWORDABLE_STATES:
        fail(
            errors.ERR_CLAIM_STATE_INVALID,
            "Only a DRAFT or REVISION_REQUESTED claim may be submitted for review.",
        )

    product = db.get("products", row["product_id"])
    if product is not None and product["label_posture"] == "FROZEN":
        fail(
            errors.ERR_PRODUCT_LABEL_FROZEN,
            "A FROZEN product may not have a claim submitted for review.",
        )

    ingredient = db.get("ingredients", row["ingredient_id"])
    if ingredient is None or ingredient["eligibility_status"] not in calc.LABEL_CLEARED_STATES:
        fail(
            errors.ERR_INGREDIENT_NOT_ELIGIBLE,
            "The claim's ingredient must be GRANDFATHERED or NDI_ACKNOWLEDGED.",
        )

    drafts = [d for d in cascade.dossiers_of(row["id"]) if d["dossier_status"] == "DRAFT"]
    if len(drafts) != 1 or drafts[0]["study_count"] < 1:
        fail(
            errors.ERR_DOSSIER_NOT_READY,
            "The claim needs exactly one DRAFT dossier carrying at least one study.",
        )

    resubmission = row["substantiation_status"] == "REVISION_REQUESTED"
    if resubmission and row["revision_round"] >= calc.MAX_REVISION_ROUNDS:
        fail(
            errors.ERR_REVISION_LIMIT_EXCEEDED,
            "The three permitted revision rounds have been consumed.",
        )

    dossier = drafts[0]
    dossier["dossier_status"] = "UNDER_REVIEW"
    # The competent-and-reliable score is computed once here and frozen forever.
    dossier["final_score"] = calc.final_score(dossier["evidence_studies"])
    db.touch(dossier)

    row["substantiation_status"] = "UNDER_SUBSTANTIATION_REVIEW"
    if resubmission:
        row["revision_round"] += 1
    db.touch(row)
    return response.object_response(serialize.claim(row))


@bp.route(PREFIX + "/claims/<row_id>/approve", methods=["POST"])
@auth.endpoint([auth.ROLE_APPROVAL])
def approve_claim(row_id):
    row = path_row("claims", row_id, errors.ERR_CLAIM_NOT_FOUND)
    if row["substantiation_status"] != "UNDER_SUBSTANTIATION_REVIEW":
        fail(
            errors.ERR_CLAIM_STATE_INVALID,
            "Only a claim under substantiation review may be approved.",
        )

    product = db.get("products", row["product_id"])
    if product is not None and product["label_posture"] == "FROZEN":
        fail(errors.ERR_PRODUCT_LABEL_FROZEN, "A FROZEN product may not have a claim approved.")

    accepted = [d for d in cascade.dossiers_of(row["id"]) if d["dossier_status"] == "ACCEPTED"]
    if len(accepted) != 1:
        fail(
            errors.ERR_DOSSIER_NOT_ACCEPTED,
            "The claim needs exactly one ACCEPTED substantiation dossier.",
        )
    if accepted[0]["reviewed_by_user_id"] == auth.user_id():
        fail(
            errors.ERR_SEGREGATION_OF_DUTIES,
            "The reviewer who cleared the evidence may not approve the claim.",
        )

    now = db.now()
    row["substantiation_status"] = "APPROVED"
    row["approved_by_user_id"] = auth.user_id()
    row["approved_at"] = now
    row["requires_recheck"] = False

    if product is not None:
        product["active_claim_count"] += 1
        db.touch(product)
        if product["lifecycle_status"] == "MARKETED":
            row["notification_status"] = "DUE"
            row["notification_due_basis"] = "CLAIM_ACTIVATION_BASIS"
            row["notification_due_date"] = calc.add_days(
                now.date(), calc.NOTIFICATION_WINDOW_DAYS
            )
    db.touch(row)
    return response.object_response(serialize.claim(row))


@bp.route(PREFIX + "/claims/<row_id>/withdraw", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST, auth.ROLE_APPROVAL])
def withdraw_claim(row_id):
    row = path_row("claims", row_id, errors.ERR_CLAIM_NOT_FOUND)
    body = validate.body()
    reason = validate.req_str(body, "withdrawal_reason")

    if row["substantiation_status"] != "APPROVED":
        fail(errors.ERR_CLAIM_STATE_INVALID, "Only an APPROVED claim may be withdrawn.")

    row["substantiation_status"] = "WITHDRAWN"
    row["withdrawal_reason"] = reason
    db.touch(row)

    product = db.get("products", row["product_id"])
    if product is not None:
        product["active_claim_count"] -= 1
        product["withdrawn_claim_count"] += 1
        db.touch(product)
        cascade.recompute_risk_index(product)

    return response.object_response(serialize.claim(row))


@bp.route(PREFIX + "/claims/<row_id>/notify-fda", methods=["POST"])
@auth.endpoint([auth.ROLE_APPROVAL])
def notify_fda(row_id):
    row = path_row("claims", row_id, errors.ERR_CLAIM_NOT_FOUND)
    body = validate.body()
    reference = validate.req_str(body, "submission_reference")

    if row["substantiation_status"] != "APPROVED":
        fail(
            errors.ERR_CLAIM_STATE_INVALID,
            "Only an APPROVED claim may be notified to the agency.",
        )
    if row["notification_status"] != "DUE":
        fail(
            errors.ERR_CLAIM_NOTIFICATION_NOT_DUE,
            "The claim's notification dimension must be exactly DUE.",
        )

    now = db.now()
    late = now.date() > row["notification_due_date"]
    row["notification_status"] = "SUBMITTED_LATE" if late else "SUBMITTED_TIMELY"
    row["notified_at"] = now
    row["submission_reference"] = reference
    db.touch(row)

    if late:
        product = db.get("products", row["product_id"])
        if product is not None:
            product["late_notification_count"] += 1
            db.touch(product)
            cascade.recompute_risk_index(product)

    return response.object_response(serialize.claim(row))
