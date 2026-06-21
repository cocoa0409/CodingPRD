"""Invoice routes: create draft, get, list, issue, pay, void. PRD §3.8, §2.10."""
from flask import Blueprint, request

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import invoice_out
from services import calc
from services.helpers import get_json_body, require_fields, paginate_and_respond
from services.lookups import (get_invoice, get_project, get_client, jobs_of_project)

bp = Blueprint("invoices", __name__)


@bp.route("/projects/<pid>/invoices", methods=["POST"])
def create_invoice(pid):
    _uid, role = get_user_context()
    require_role(role, {"AccountsReceivable"})
    p = get_project(pid)
    i = common_fields()
    i.update({
        "project_id": pid,
        "client_id": p["client_id"],
        "translation_subtotal_cents": None,
        "volume_discount_cents": None,
        "rush_surcharge_cents": None,
        "revision_surcharge_cents": None,
        "certification_cents": None,
        "total_cents": None,
        "expected_project_version": None,
        "status": "DRAFT",
    })
    db.invoices[i["id"]] = i
    return success_object(invoice_out(i), 201)


@bp.route("/invoices/<iid>", methods=["GET"])
def get_invoice_route(iid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Client"})
    i = get_invoice(iid)
    if role == "Client" and uid != i["client_id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Client may only read its own invoice")
    return success_object(invoice_out(i), 200)


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable"})
    items = list(db.invoices.values())
    client_f = request.args.get("client_id")
    project_f = request.args.get("project_id")
    status_f = request.args.get("status")
    if client_f is not None:
        items = [i for i in items if i["client_id"] == client_f]
    if project_f is not None:
        items = [i for i in items if i["project_id"] == project_f]
    if status_f is not None:
        items = [i for i in items if i["status"] == status_f]
    return paginate_and_respond(items, invoice_out)


# ---------------------------------------------------------------------------
# Issue (DRAFT -> ISSUED) PRD §3.8
# ---------------------------------------------------------------------------
@bp.route("/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    _uid, role = get_user_context()
    require_role(role, {"AccountsReceivable"})
    i = get_invoice(iid)
    body = get_json_body()
    require_fields(body, ["expected_project_version"])
    expected = body["expected_project_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err("ERR_INVALID_REQUEST", "expected_project_version must be an integer")

    if i["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Invoice must be DRAFT to issue")

    project = db.projects.get(i["project_id"])
    client = db.clients.get(i["client_id"])

    # priority 10: OCC stale project version
    if expected != project["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match project version")

    # priority 11: project must be DELIVERED
    if project["status"] != "DELIVERED":
        raise err("ERR_PROJECT_NOT_DELIVERED", "Project must be DELIVERED to issue an invoice")

    # client must be ACTIVE
    if client["status"] != "ACTIVE":
        raise err("ERR_CLIENT_SUSPENDED", "Cannot issue an invoice for a suspended client")

    delivered_jobs = [j for j in jobs_of_project(project["id"]) if j["status"] == "DELIVERED"]
    amounts = calc.final_invoice(
        delivered_jobs, project["pinned_base_rate_cents_per_word"],
        project["rush_tier"], project["certification_mode"])

    i["translation_subtotal_cents"] = amounts["translation_subtotal_cents"]
    i["volume_discount_cents"] = amounts["volume_discount_cents"]
    i["rush_surcharge_cents"] = amounts["rush_surcharge_cents"]
    i["revision_surcharge_cents"] = amounts["revision_surcharge_cents"]
    i["certification_cents"] = amounts["certification_cents"]
    i["total_cents"] = amounts["total_cents"]
    i["expected_project_version"] = expected
    i["status"] = "ISSUED"
    touch(i)

    # ar balance + project version bump + bubble
    client["ar_balance_cents"] = client["ar_balance_cents"] + amounts["total_cents"]
    touch(client)
    touch(project)  # increments Project.version by 1
    project["status"] = "INVOICED"
    touch(project)

    return success_object(invoice_out(i), 200)


# ---------------------------------------------------------------------------
# Pay (ISSUED -> PAID) PRD §3.8
# ---------------------------------------------------------------------------
@bp.route("/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    _uid, role = get_user_context()
    require_role(role, {"AccountsReceivable"})
    i = get_invoice(iid)
    if i["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE", "Invoice must be ISSUED to pay")
    i["status"] = "PAID"
    touch(i)
    client = db.clients.get(i["client_id"])
    if client is not None:
        client["ar_balance_cents"] = client["ar_balance_cents"] - i["total_cents"]
        touch(client)
    return success_object(invoice_out(i), 200)


# ---------------------------------------------------------------------------
# Void PRD §3.8
# ---------------------------------------------------------------------------
@bp.route("/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    _uid, role = get_user_context()
    require_role(role, {"AccountsReceivable"})
    i = get_invoice(iid)
    if i["status"] not in ("DRAFT", "ISSUED"):
        raise err("ERR_INVALID_STATE", "Invoice must be DRAFT or ISSUED to void")
    was_issued = (i["status"] == "ISSUED")
    i["status"] = "VOIDED"
    touch(i)
    if was_issued:
        client = db.clients.get(i["client_id"])
        if client is not None:
            client["ar_balance_cents"] = client["ar_balance_cents"] - i["total_cents"]
            touch(client)
        project = db.projects.get(i["project_id"])
        if project is not None and project["status"] == "INVOICED":
            project["status"] = "DELIVERED"
            touch(project)
    return success_object(invoice_out(i), 200)
