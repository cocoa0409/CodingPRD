"""PatientAccount endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import now, sort_default, stamp_new, store, touch
from errors import (ERR_ACCOUNT_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, fail)
from middleware import ALL_ROLES, require_roles
from response import bool_param, ok_obj, paginate
from services.calc import dnfb_order_key
from services.core import (DISCHARGE_DISPOSITIONS, FINANCIAL_CLASSES,
                           PATIENT_CLASSES, chart_for_account, ser_account)
from validators import body, has, opt_enum, req_dt, req_enum, req_int, req_str

bp = Blueprint("accounts", __name__)


def get_account_or_404(account_id):
    a = store.accounts.get(account_id)
    if a is None:
        fail(404, ERR_ACCOUNT_NOT_FOUND, f"PatientAccount {account_id} does not exist")
    return a


@bp.route("/patient-accounts", methods=["POST"])
def create_account():
    require_roles("CodingManager")
    b = body()
    mrn = req_str(b, "mrn")
    admit_at = req_dt(b, "admit_at")
    patient_class = req_enum(b, "patient_class", PATIENT_CLASSES)
    financial_class = req_enum(b, "financial_class", FINANCIAL_CLASSES)
    total = req_int(b, "total_charges_cents")
    if total < 0:
        fail(400, ERR_INVALID_REQUEST, "total_charges_cents must be >= 0")
    if any(a["mrn"] == mrn for a in store.accounts.values()):
        fail(400, ERR_INVALID_REQUEST, "mrn must be unique across all accounts")
    account = stamp_new({
        "mrn": mrn,
        "admit_at": admit_at,
        "discharge_at": None,
        "patient_class": patient_class,
        "financial_class": financial_class,
        "discharge_disposition": None,
        "total_charges_cents": total,
        "status": "ADMITTED",
        "dnfb_flag": False,
        "dnfb_flagged_at": None,
    })
    store.accounts[account["id"]] = account
    return ok_obj(ser_account(account), 201)


@bp.route("/patient-accounts/<id>", methods=["GET"])
def get_account(id):
    require_roles(*ALL_ROLES)
    return ok_obj(ser_account(get_account_or_404(id)), 200)


@bp.route("/patient-accounts", methods=["GET"])
def list_accounts():
    require_roles(*ALL_ROLES)
    items = list(store.accounts.values())
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    dnfb_only = bool_param("dnfb_only")
    if dnfb_only:
        items = [a for a in items if a["dnfb_flag"]]
        as_of = now()
        items.sort(key=lambda a: dnfb_order_key(a, as_of))
    else:
        items = sort_default(items)
    return paginate([ser_account(a) for a in items])


@bp.route("/patient-accounts/<id>/discharge", methods=["POST"])
def discharge_account(id):
    require_roles("CodingManager")
    account = get_account_or_404(id)
    if account["status"] != "ADMITTED":
        fail(409, ERR_INVALID_STATE,
             f"Cannot discharge an account in state {account['status']}")
    b = body()
    discharge_at = req_dt(b, "discharge_at")
    disposition = req_enum(b, "discharge_disposition", DISCHARGE_DISPOSITIONS)
    if not discharge_at > account["admit_at"]:
        fail(400, ERR_INVALID_REQUEST, "discharge_at must be strictly later than admit_at")
    account["discharge_at"] = discharge_at
    account["discharge_disposition"] = disposition
    account["status"] = "DISCHARGED"
    touch(account)
    chart = chart_for_account(account["id"])
    if chart is not None and chart["status"] == "OPEN" and chart["open_deficiency_count"] == 0:
        chart["status"] = "READY_FOR_CODING"
        touch(chart)
    return ok_obj(ser_account(account), 200)
