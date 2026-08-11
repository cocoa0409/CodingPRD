"""Client intake, capacity, lifecycle and the per-client read surface."""

from flask import Blueprint, request

from core import constants as K
from core import serialize
from core.aggregates import accounts_of_client, revoke_authorization
from core.audit import set_client, set_subject
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import audited, authorize, resolve_client
from core.store import bump, db, new_row

bp = Blueprint("clients", __name__)

READ_ROLES = (
    "FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer",
    "CareCoordinator", "PlatformAdmin", "Client",
)
LIST_ROLES = ("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer", "PlatformAdmin")


@bp.post("/dmm/clients")
@audited("Client")
def create_client():
    ctx = authorize("FiduciaryManager")                       # rungs 1-2
    ctx.check_shape([                                          # rung 4
        ("full_name", str, True),
        ("date_of_birth", str, True),
        ("intake_reference", str, True),
    ])
    row = new_row("clients", {
        "full_name": ctx.body["full_name"],
        "date_of_birth": ctx.body["date_of_birth"],
        "intake_reference": ctx.body["intake_reference"],
        "status": "INTAKE",
        "capacity_determination": "NOT_DETERMINED",
        "capacity_determined_on": None,
        "activated_on": None,
        "closed_on": None,
    })
    set_subject(row["id"])
    set_client(row["id"])
    return object_response(serialize.client(row), 201)


@bp.post("/dmm/clients/<cid>/capacity-determination")
@audited("Client", path_param="cid")
def record_capacity(cid):
    ctx = authorize("FiduciaryManager")                       # rungs 1-2
    row = resolve_client(cid)                                  # rung 3
    set_client(row["id"])
    ctx.check_shape([                                          # rung 4
        ("determination", str, True),
        ("determined_on", str, True),
    ])
    ctx.check_enum("determination", K.CAPACITY_DETERMINATION)  # rung 5
    row["capacity_determination"] = ctx.body["determination"]
    # capacity_determined_on holds, byte-for-byte, the caller's determined_on.
    row["capacity_determined_on"] = ctx.body["determined_on"]
    bump(row)
    return object_response(serialize.client(row), 200)


@bp.post("/dmm/clients/<cid>/status-change")
@audited("Client", path_param="cid")
def change_client_status(cid):
    ctx = authorize("FiduciaryManager")                       # rungs 1-2
    row = resolve_client(cid)                                  # rung 3
    set_client(row["id"])
    ctx.check_shape([                                          # rung 4
        ("to_status", str, True),
        ("note", str, False),
    ])
    ctx.check_enum("to_status", K.CLIENT_STATUS)              # rung 5

    to_status = ctx.body["to_status"]
    current = row["status"]

    # rung 12 - the state gate, terminal states included.
    if to_status == "ACTIVE":
        if current == "INTAKE":
            if row["capacity_determination"] == "NOT_DETERMINED":
                fail("ERR_INVALID_STATE", "A capacity determination must be on file.")
        elif current != "SUSPENDED":
            fail("ERR_INVALID_STATE", "The client cannot move to ACTIVE from here.")
    elif to_status == "SUSPENDED":
        if current != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE client may be suspended.")
    elif to_status == "CLOSED":
        if current not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_INVALID_STATE", "The client cannot be closed from here.")
        if _has_money_in_transit(row["id"]):
            fail("ERR_INVALID_STATE", "A payment is still scheduled or in flight.")
    else:
        fail("ERR_INVALID_STATE", "No transition leads to that status.")

    if to_status == "ACTIVE" and current == "INTAKE":
        row["status"] = "ACTIVE"
        row["activated_on"] = db.today_str()
    elif to_status == "ACTIVE":
        row["status"] = "ACTIVE"
        for recipient in db.ordered("family_recipients"):
            if recipient["client_id"] != row["id"]:
                continue
            if recipient["subscription_status"] == "SUSPENDED":
                recipient["subscription_status"] = "ACTIVE"
                bump(recipient)
    elif to_status == "SUSPENDED":
        row["status"] = "SUSPENDED"
        for recipient in db.ordered("family_recipients"):
            if recipient["client_id"] != row["id"]:
                continue
            if recipient["subscription_status"] == "ACTIVE":
                recipient["subscription_status"] = "SUSPENDED"
                bump(recipient)
    else:
        row["status"] = "CLOSED"
        row["closed_on"] = db.today_str()
        for auth in db.ordered("authorizations"):
            if auth["client_id"] != row["id"] or auth["status"] != "ACTIVE":
                continue
            revoke_authorization(auth, "CLIENT_CLOSED")

    bump(row)
    return object_response(serialize.client(row), 200)


def _has_money_in_transit(client_id):
    account_ids = {a["id"] for a in accounts_of_client(client_id)}
    for payment in db.ordered("payments"):
        if payment["account_id"] in account_ids and payment["settlement_status"] in (
            "SCHEDULED", "IN_FLIGHT"
        ):
            return True
    return False


# ---------------------------------------------------------------- reads

@bp.get("/dmm/clients/<cid>")
def read_client(cid):
    authorize(*READ_ROLES)
    row = resolve_client(cid)
    return object_response(serialize.client(row), 200)


@bp.get("/dmm/clients/<cid>/authorizations")
def list_client_authorizations(cid):
    authorize(*LIST_ROLES)
    resolve_client(cid)
    rows = [a for a in db.ordered("authorizations") if a["client_id"] == cid]
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize.authorization)


@bp.get("/dmm/clients/<cid>/accounts")
def list_client_accounts(cid):
    authorize(*LIST_ROLES)
    resolve_client(cid)
    rows = [a for a in db.ordered("accounts") if a["client_id"] == cid]
    return paginate(rows, serialize.account)


@bp.get("/dmm/clients/<cid>/payees")
def list_client_payees(cid):
    authorize(*LIST_ROLES)
    resolve_client(cid)
    rows = [p for p in db.ordered("payees") if p["client_id"] == cid]
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize.payee)


@bp.get("/dmm/clients/<cid>/budget-categories")
def list_client_budget_categories(cid):
    authorize(*LIST_ROLES)
    resolve_client(cid)
    rows = [b for b in db.ordered("budget_categories") if b["client_id"] == cid]
    rows = filter_exact(rows, "budget_month")
    return paginate(rows, serialize.budget_category)


@bp.get("/dmm/clients/<cid>/coordination-requests")
def list_client_coordination_requests(cid):
    authorize("FiduciaryManager", "CareCoordinator", "ComplianceOfficer", "PlatformAdmin")
    resolve_client(cid)
    rows = [c for c in db.ordered("coordination_requests") if c["client_id"] == cid]
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize.coordination_request)


@bp.get("/dmm/clients/<cid>/audit-entries")
def export_client_audit(cid):
    ctx = authorize("FiduciaryManager", "ComplianceOfficer", "PlatformAdmin",
                    "FamilyRecipient")
    resolve_client(cid)                                        # rung 3
    rows = [e for e in db.ordered("audit_entries") if e["client_id"] == cid]

    if ctx.role == "FamilyRecipient":                          # rung 32
        recipient = db.family_recipients.get(ctx.user_id)
        if recipient is None or recipient["client_id"] != cid:
            fail("ERR_DISCLOSURE_DENIED", "This recipient may not read that file.")
        permitted = recipient.get("permitted_categories") or []
        rows = [e for e in rows if e["disclosure_category"] in permitted]

    rows = filter_exact(rows, "subject_entity")
    rows = filter_exact(rows, "outcome")
    return paginate(rows, serialize.audit_entry)
