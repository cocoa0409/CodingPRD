"""Family recipients, the disclosure wall and monthly report generation."""

from flask import Blueprint

from core import constants as K
from core import serialize
from core.aggregates import accounts_of_client, period_for_month
from core.audit import set_client, set_subject
from core.clock import month_of_date_string
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.gates import (
    gate_authorization,
    gate_client_active,
    gate_scope_family_recipient,
)
from core.pipeline import (
    audited,
    authorize,
    resolve,
    resolve_body_client,
    resolve_body_ref,
)
from core.store import bump, db, new_row

bp = Blueprint("family", __name__)

LIST_ROLES = ("FiduciaryManager", "ComplianceOfficer", "PlatformAdmin")
READ_ROLES = ("FiduciaryManager", "ComplianceOfficer", "PlatformAdmin", "FamilyRecipient")


@bp.post("/dmm/family-recipients")
@audited("FamilyRecipient")
def enrol_recipient():
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    auth = resolve_body_ref(ctx, "authorization_id", "authorizations")
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("authorization_id", str, True),
        ("full_name", str, True),
        ("contact_email", str, True),
        ("relationship", str, True),
    ])
    ctx.check_enum("relationship", K.RELATIONSHIP)             # rung 5

    gate_authorization(auth)                                   # rung 7
    gate_scope_family_recipient(auth)                          # rung 8
    gate_client_active(client_row)                             # rung 11

    row = new_row("family_recipients", {
        "client_id": client_row["id"],
        "authorization_id": auth["id"],
        "full_name": ctx.body["full_name"],
        "contact_email": ctx.body["contact_email"],
        "relationship": ctx.body["relationship"],
        "permitted_categories": [],
        "subscription_status": "PENDING",
        "consent_recorded_by_role": None,
        "consent_recorded_at": None,
        "report_count": 0,
    })
    set_subject(row["id"])
    return object_response(serialize.family_recipient(row), 201)


@bp.post("/dmm/family-recipients/<rid>/consent")
@audited("FamilyRecipient", path_param="rid")
def record_consent(rid):
    ctx = authorize("Client", "FiduciaryManager")              # rungs 1-2
    recipient = resolve("family_recipients", rid)              # rung 3
    set_client(recipient["client_id"])
    ctx.check_shape([("permitted_categories", list, True)])    # rung 4
    ctx.check_enum_list("permitted_categories", K.DISCLOSURE_CATEGORY_ORDER)   # rung 5

    auth = db.authorizations.get(recipient["authorization_id"])
    gate_authorization(auth)                                   # rung 7
    client_row = db.clients.get(recipient["client_id"])
    gate_client_active(client_row)                             # rung 11

    if recipient["subscription_status"] not in ("PENDING", "ACTIVE"):   # rung 12
        fail("ERR_INVALID_STATE", "This subscription cannot record consent.")

    if ctx.role == "Client":                                   # rung 31
        if client_row["capacity_determination"] != "RETAINS_CAPACITY":
            fail("ERR_CAPACITY_REQUIRED", "The client does not retain decisional capacity.")
        if ctx.user_id != client_row["id"]:                    # rung 32
            fail("ERR_DISCLOSURE_DENIED", "A client may act only on their own file.")

    supplied = ctx.body["permitted_categories"]
    recipient["permitted_categories"] = [
        c for c in K.DISCLOSURE_CATEGORY_ORDER if c in supplied
    ]
    recipient["subscription_status"] = "ACTIVE"
    recipient["consent_recorded_by_role"] = ctx.role
    recipient["consent_recorded_at"] = db.now
    bump(recipient)
    return object_response(serialize.family_recipient(recipient), 200)


@bp.post("/dmm/family-reports")
@audited("FamilyReport")
def generate_report():
    ctx = authorize("FamilyRecipient", "FiduciaryManager")     # rungs 1-2
    recipient = resolve_body_ref(ctx, "recipient_id", "family_recipients")   # rung 3
    if recipient is not None:
        set_client(recipient["client_id"])
    ctx.check_shape([                                          # rung 4
        ("recipient_id", str, True),
        ("report_month", str, True),
        ("expected_recipient_version", int, True),
        ("requested_categories", list, False),
    ])
    ctx.check_enum_list("requested_categories", K.DISCLOSURE_CATEGORY_ORDER)   # rung 5

    auth = db.authorizations.get(recipient["authorization_id"])
    gate_authorization(auth)                                   # rung 7
    gate_client_active(db.clients.get(recipient["client_id"]))  # rung 11

    if ctx.role == "FamilyRecipient" and ctx.user_id != recipient["id"]:   # rung 32
        fail("ERR_DISCLOSURE_DENIED", "A recipient may generate only their own report.")

    if ctx.body["expected_recipient_version"] != recipient["version"]:      # rung 34
        fail("ERR_STALE_VERSION", "The recipient version has moved on.")

    report_month = ctx.body["report_month"]
    supplied = ctx.body.get("requested_categories")
    requested = [
        c for c in K.DISCLOSURE_CATEGORY_ORDER
        if supplied is None or c in supplied
    ]
    permitted = recipient.get("permitted_categories") or []
    included = [c for c in K.DISCLOSURE_CATEGORY_ORDER
                if c in requested and c in permitted]
    withheld = [c for c in K.DISCLOSURE_CATEGORY_ORDER
                if c in requested and c not in included]

    accounts = accounts_of_client(recipient["client_id"])
    is_provisional = True
    if accounts:
        is_provisional = False
        for account in accounts:
            period = period_for_month(account["id"], report_month)
            if period is None or period["status"] not in ("CLOSED", "LOCKED"):
                is_provisional = True
                break

    total_disbursed = 0
    if "BILL_PAY" in included:
        account_ids = {a["id"] for a in accounts}
        for payment in db.ordered("payments"):
            if payment["account_id"] not in account_ids:
                continue
            if payment["settlement_status"] != "SETTLED":
                continue
            if month_of_date_string(payment.get("settled_on")) != report_month:
                continue
            total_disbursed += payment["amount_cents"]

    closing_available = 0
    if "BALANCES" in included:
        closing_available = sum(a["available_balance_cents"] for a in accounts)

    row = new_row("family_reports", {
        "recipient_id": recipient["id"],
        "report_month": report_month,
        "requested_categories": requested,
        "included_categories": included,
        "withheld_categories": withheld,
        "is_provisional": is_provisional,
        "total_disbursed_cents": total_disbursed,
        "closing_available_balance_cents": closing_available,
        "generated_at": db.now,
    }, versioned=False)

    recipient["report_count"] += 1
    bump(recipient)
    set_subject(row["id"])
    return object_response(serialize.family_report(row), 201)


@bp.get("/dmm/family-recipients")
def list_recipients():
    authorize(*LIST_ROLES)
    rows = db.ordered("family_recipients")
    for field in ("client_id", "authorization_id", "subscription_status"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.family_recipient)


@bp.get("/dmm/family-recipients/<rid>")
def read_recipient(rid):
    authorize(*READ_ROLES)
    return object_response(
        serialize.family_recipient(resolve("family_recipients", rid)), 200
    )


@bp.get("/dmm/family-reports")
def list_reports():
    authorize(*READ_ROLES)
    rows = db.ordered("family_reports")
    for field in ("recipient_id", "report_month"):
        rows = filter_exact(rows, field)
    return paginate(rows, serialize.family_report)


@bp.get("/dmm/family-reports/<fid>")
def read_report(fid):
    ctx = authorize(*READ_ROLES)
    row = resolve("family_reports", fid)
    # PRD 2.1 - reading a report for any other recipient is refused.
    if ctx.role == "FamilyRecipient" and ctx.user_id != row["recipient_id"]:
        fail("ERR_DISCLOSURE_DENIED", "A recipient may read only their own reports.")
    return object_response(serialize.family_report(row), 200)
