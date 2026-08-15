"""Routes: as-built documentation packages."""

from flask import Blueprint

from calc import recompute_asbuilt, reevaluate_job_posture
from core import (
    bump,
    envelope_object,
    err_invalid_state,
    err_sod,
    get_body,
    opt_bool,
    paginate,
    require_roles,
)
from lookups import asbuilt_of_panel, get_asbuilt, get_panel, job_of_panel
from serializers import ser_asbuilt
from store import db

bp = Blueprint("asbuilt", __name__)

FLAG_FIELDS = ("has_wiring_diagram", "has_program_archive", "has_test_report", "has_ul_label_photo")


@bp.route("/panel-shop/as-built-packages/<pkg_id>", methods=["GET"])
def fetch_asbuilt(pkg_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "Customer")
    return envelope_object(ser_asbuilt(get_asbuilt(pkg_id)))


@bp.route("/panel-shop/panels/<panel_id>/as-built-packages", methods=["GET"])
def fetch_panel_asbuilt(panel_id):
    require_roles("ProjectManager", "QAManager", "DesignEngineer", "Customer")
    get_panel(panel_id)
    pkg = asbuilt_of_panel(panel_id)
    # 1:1 reverse reachability returns an array of 0-1
    limit = 10
    offset = 0
    items = [pkg] if pkg is not None else []
    from core import envelope_list

    return envelope_list([ser_asbuilt(q) for q in items], limit, offset, len(items))


@bp.route("/panel-shop/as-built-packages/<pkg_id>", methods=["PATCH"])
def update_asbuilt(pkg_id):
    require_roles("DesignEngineer")
    pkg = get_asbuilt(pkg_id)
    body = get_body()
    for f in FLAG_FIELDS:
        if f in body:
            pkg[f] = opt_bool(body, f)
    bump(pkg)  # the PATCH itself
    recompute_asbuilt(pkg)  # may fire the auto-advance / regress transition
    panel = db.panels[pkg["panel_id"]]
    reevaluate_job_posture(job_of_panel(panel))
    return envelope_object(ser_asbuilt(pkg))


@bp.route("/panel-shop/as-built-packages/<pkg_id>/approve", methods=["POST"])
def approve_asbuilt(pkg_id):
    user_id, _ = require_roles("QAManager")
    pkg = get_asbuilt(pkg_id)
    if pkg["status"] != "PENDING_REVIEW":
        raise err_invalid_state("AsBuiltPackage is not PENDING_REVIEW.")
    panel = db.panels[pkg["panel_id"]]
    if user_id == panel["design_engineer_id"]:
        raise err_sod("QAManager may not approve the as-built of their own design.")
    pkg["status"] = "APPROVED"
    bump(pkg)
    return envelope_object(ser_asbuilt(pkg))


@bp.route("/panel-shop/as-built-packages/<pkg_id>/return-for-rework", methods=["POST"])
def return_asbuilt(pkg_id):
    require_roles("QAManager")
    pkg = get_asbuilt(pkg_id)
    if pkg["status"] != "PENDING_REVIEW":
        raise err_invalid_state("AsBuiltPackage is not PENDING_REVIEW.")
    pkg["status"] = "INCOMPLETE"
    bump(pkg)
    return envelope_object(ser_asbuilt(pkg))


@bp.route("/panel-shop/as-built-packages/<pkg_id>/release", methods=["POST"])
def release_asbuilt(pkg_id):
    require_roles("ProjectManager")
    pkg = get_asbuilt(pkg_id)
    if pkg["status"] != "APPROVED":
        raise err_invalid_state("AsBuiltPackage is not APPROVED.")
    panel = db.panels[pkg["panel_id"]]
    if panel["status"] not in ("TEST_PASSED", "READY_FOR_LABEL", "LABELED"):
        raise err_invalid_state("Owning panel is not in a releasable state.")
    pkg["status"] = "RELEASED"
    bump(pkg)
    reevaluate_job_posture(job_of_panel(panel))
    return envelope_object(ser_asbuilt(pkg))
