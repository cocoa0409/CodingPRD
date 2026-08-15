"""Routes: program versions (create-with-release, OCC on Panel.version)."""

from flask import Blueprint, request

from core import (
    bump,
    envelope_object,
    err_duplicate,
    err_invalid_request,
    err_invalid_state,
    err_stale,
    get_body,
    now_dt,
    now_iso,
    opt_bool,
    paginate,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_panel, get_program_version
from serializers import ser_program_version
from store import db

bp = Blueprint("programs", __name__)


@bp.route("/panel-shop/panels/<panel_id>/program-versions", methods=["POST"])
def create_program_version(panel_id):
    require_roles("ControlsEngineer")
    p = get_panel(panel_id)
    body = get_body()
    # OCC (priority 7): expected_panel_version is a non-optional integer
    expected = body.get("expected_panel_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_panel_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_panel_version must be an integer.")
    if expected != p["version"]:
        raise err_stale("expected_panel_version does not match the panel's current version.")
    version_tag = req_str(body, "version_tag")
    content_hash = req_str(body, "content_hash")
    site_backup_taken = opt_bool(body, "site_backup_taken", False)
    # priority 16: version_tag and content_hash unique per panel
    for v in db.program_versions.values():
        if v["panel_id"] == panel_id and v["version_tag"] == version_tag:
            raise err_duplicate("version_tag already exists for this panel.")
        if v["panel_id"] == panel_id and v["content_hash"] == content_hash:
            raise err_duplicate("content_hash already exists for this panel.")
    # supersede-on-release: prior RELEASED versions become SUPERSEDED
    for v in db.program_versions.values():
        if v["panel_id"] == panel_id and v["status"] == "RELEASED":
            v["status"] = "SUPERSEDED"
    v = stamp_new(
        {
            "panel_id": panel_id,
            "version_tag": version_tag,
            "status": "RELEASED",
            "content_hash": content_hash,
            "site_backup_taken": site_backup_taken,
            "released_at": now_iso(),
        },
        with_version=False,
    )
    db.program_versions[v["id"]] = v
    # the panel aggregate owns the OCC anchor for the release operation
    bump(p)
    return envelope_object(ser_program_version(v), 201)


@bp.route("/panel-shop/program-versions/<pv_id>", methods=["GET"])
def fetch_program_version(pv_id):
    require_roles("ProjectManager", "QAManager", "ControlsEngineer", "FieldEngineer", "DesignEngineer")
    return envelope_object(ser_program_version(get_program_version(pv_id)))


@bp.route("/panel-shop/panels/<panel_id>/program-versions", methods=["GET"])
def list_program_versions(panel_id):
    require_roles("ProjectManager", "QAManager", "ControlsEngineer", "FieldEngineer", "DesignEngineer")
    get_panel(panel_id)
    versions = [v for v in db.program_versions.values() if v["panel_id"] == panel_id]
    if "status" in request.args:
        versions = [v for v in versions if v["status"] == request.args.get("status")]
    return paginate(sorted_by_created(versions), ser_program_version)


@bp.route("/panel-shop/program-versions/<pv_id>/archive", methods=["POST"])
def archive_program_version(pv_id):
    require_roles("ControlsEngineer")
    v = get_program_version(pv_id)
    if v["status"] not in ("DRAFT", "SUPERSEDED"):
        raise err_invalid_state("Only a DRAFT or SUPERSEDED version may be archived.")
    v["status"] = "ARCHIVED"
    return envelope_object(ser_program_version(v))


@bp.route("/panel-shop/program-versions/<pv_id>/mark-site-backup", methods=["POST"])
def mark_site_backup(pv_id):
    require_roles("FieldEngineer")
    v = get_program_version(pv_id)
    if v["status"] != "RELEASED":
        raise err_invalid_state("Only a RELEASED version may carry site backup evidence.")
    v["site_backup_taken"] = True
    return envelope_object(ser_program_version(v))
