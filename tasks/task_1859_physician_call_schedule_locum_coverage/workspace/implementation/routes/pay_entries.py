"""Pay entries — read-only; created at mark-served (PRD §3.6)."""
from flask import Blueprint

from db import store
from errors import ApiError
from middleware import require_roles
from response import ok, paginate

bp = Blueprint("pay_entries", __name__)

ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_pay_entry_or_404(entry_id):
    entry = store.pay_entries.get(entry_id)
    if entry is None:
        raise ApiError("ERR_PAY_ENTRY_NOT_FOUND", 404, "PayEntry id does not exist")
    return entry


@bp.route("/api/pay-entries", methods=["GET"])
def list_pay_entries():
    require_roles(ALL)
    rows = list(store.pay_entries.values())
    rows = paginate.filter(rows, "program_id")
    rows = paginate.filter(rows, "assignment_id")
    rows = paginate.filter(rows, "physician_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/pay-entries/<entry_id>", methods=["GET"])
def get_pay_entry(entry_id):
    require_roles(ALL)
    return ok(get_pay_entry_or_404(entry_id))
