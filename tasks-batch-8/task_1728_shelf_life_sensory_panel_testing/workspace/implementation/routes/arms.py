"""StudyArm registry (PRD §3.2)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STUDY_STATE,
    ERR_CONTROL_ARM_EXISTS, ERR_DUPLICATE_ARM_VARIANT,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import ser_arm, PACKAGING_VARIANTS
from util import body, opt_bool, paginate, req_enum, req_str, sort_created

bp = Blueprint("arms", __name__)


def get_arm(arm_id):
    a = db.store["arms"].get(arm_id)
    if a is None:
        raise_err(ERR_NOT_FOUND, f"StudyArm {arm_id} not found")
    return a


@bp.route("/study-arms", methods=["POST"])
@require_roles("SensoryScientist")
def create_arm():
    b = body()
    study_id = req_str(b, "study_id")
    packaging_variant = req_enum(b, "packaging_variant", PACKAGING_VARIANTS)
    is_control = opt_bool(b, "is_control", default=False)
    study = db.store["studies"].get(study_id)
    if study is None:
        raise_err(ERR_NOT_FOUND, f"Study {study_id} not found")
    if study["status"] != "DRAFT":
        raise_err(ERR_INVALID_STUDY_STATE,
                  "Arms may only be created while the study is DRAFT")
    for a in db.store["arms"].values():
        if a["study_id"] != study_id:
            continue
        if a["packaging_variant"] == packaging_variant:
            raise_err(ERR_DUPLICATE_ARM_VARIANT,
                      f"packaging_variant {packaging_variant} already used "
                      f"in this study")
    if is_control:
        for a in db.store["arms"].values():
            if a["study_id"] == study_id and a["is_control"]:
                raise_err(ERR_CONTROL_ARM_EXISTS,
                          "study already has a control arm")
    now = clock.now()
    arm = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "study_id": study_id,
        "packaging_variant": packaging_variant,
        "is_control": is_control,
        "computed_failure_day_equiv": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["arms"][arm["id"]] = arm
    return respond(ser_arm(arm), 201)


@bp.route("/study-arms", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_arms():
    items = sort_created(db.store["arms"].values())
    study_id = request.args.get("study_id")
    if study_id is not None:
        items = [a for a in items if a["study_id"] == study_id]
    page, pagination = paginate(items)
    return respond_list([ser_arm(a) for a in page], pagination)


@bp.route("/study-arms/<arm_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_arm(arm_id):
    return respond(ser_arm(get_arm(arm_id)), 200)
