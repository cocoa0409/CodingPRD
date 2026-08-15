"""CurriculumFramework endpoints (PRD §3.1)."""

from flask import Blueprint

import serializers
from db import new_id, stamp_new, store
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, opt_enum,
                        req_enum, req_int, req_str, require_roles)
from response import paginate, sort_created, success_object

bp = Blueprint("frameworks", __name__)

SUBJECT_AREAS = ("MATHEMATICS", "ENGLISH_LANGUAGE_ARTS", "SCIENCE",
                 "SOCIAL_STUDIES", "WORLD_LANGUAGES")
GRADE_BANDS = ("K_5", "GRADES_6_8", "GRADES_9_12")
FRAMEWORK_STATUSES = ("ACTIVE", "RETIRED")


@bp.route("/frameworks", methods=["POST"])
def create_framework():
    auth = auth_context()
    require_roles(auth[1], ("DistrictAdmin",))
    body = get_body()
    framework = {
        "id": new_id(),
        "code": req_str(body, "code"),
        "subject_area": req_enum(body, "subject_area", SUBJECT_AREAS),
        "grade_band": req_enum(body, "grade_band", GRADE_BANDS),
        "standards_required_count": req_int(body, "standards_required_count", minimum=1),
        "effective_year": req_int(body, "effective_year"),
        "status": opt_enum(body, "status", FRAMEWORK_STATUSES, default="ACTIVE"),
    }
    stamp_new(framework)
    store.frameworks[framework["id"]] = framework
    return success_object(serializers.framework(framework), status=201)


@bp.route("/frameworks", methods=["GET"])
def list_frameworks():
    auth = auth_context()
    require_roles(auth[1], ALL_ROLES)
    items = list(store.frameworks.values())
    from flask import request
    subject_area = request.args.get("subject_area")
    status = request.args.get("status")
    if subject_area is not None:
        items = [f for f in items if f["subject_area"] == subject_area]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return paginate(sort_created(items), serializers.framework)


@bp.route("/frameworks/<frameworkId>", methods=["GET"])
def get_framework(frameworkId):
    auth = auth_context()
    require_roles(auth[1], ALL_ROLES)
    framework = get_or_404(store.frameworks, frameworkId, "CurriculumFramework")
    return success_object(serializers.framework(framework))
