from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import get_or_404, parse_pagination, paginate
from response import success, success_list
from errors import err, ERR_FORBIDDEN
from routes.essays import serialize_version

bp = Blueprint("essay_versions", __name__)


@bp.route("/essay-versions/<version_id>", methods=["GET"])
def get_version(version_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        v = get_or_404(store.essay_versions, version_id)
        _assert_access(caller, v)
        return success(serialize_version(v))


@bp.route("/essay-versions", methods=["GET"])
def list_versions():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_essay = request.args.get("essay_id")
    with store.lock:
        rows = [r for r in store.essay_versions.values() if _visible(caller, r)]
        if filt_essay is not None:
            rows = [r for r in rows if r.get("essay_id") == filt_essay]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize_version(r) for r in page], limit, offset, total)


def _visible(caller, v):
    essay = store.essays.get(v.get("essay_id"))
    if essay is None:
        return False
    student = store.students.get(essay.get("student_id"))
    if student is None:
        return False
    if caller.is_counselor:
        return student.get("counselor_id") == caller.user_id
    if caller.is_student:
        return student["id"] == caller.user_id
    return False


def _assert_access(caller, v):
    if not _visible(caller, v):
        raise err(ERR_FORBIDDEN, "Not permitted on this version")
