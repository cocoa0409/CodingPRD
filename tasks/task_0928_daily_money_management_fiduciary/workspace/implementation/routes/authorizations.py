"""The authorization instrument: drafting, execution, revocation."""

from flask import Blueprint

from core import constants as K
from core import serialize
from core.aggregates import revoke_authorization
from core.audit import set_client, set_subject
from core.clock import parse_date
from core.envelope import object_response
from core.errors import fail
from core.pipeline import audited, authorize, resolve, resolve_body_client
from core.store import bump, db, new_row

bp = Blueprint("authorizations", __name__)


@bp.post("/dmm/authorizations")
@audited("Authorization")
def draft_authorization():
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    client_row = resolve_body_client(ctx)                      # rung 3
    if client_row is not None:
        set_client(client_row["id"])
    ctx.check_shape([                                          # rung 4
        ("client_id", str, True),
        ("scope_tier", str, True),
        ("instrument_reference", str, True),
        ("effective_date", str, True),
        ("expiry_date", str, True),
    ])
    ctx.check_enum("scope_tier", K.SCOPE_TIER)                 # rung 5

    _check_date_span(                                        # rung 17
        ctx.body["effective_date"], ctx.body["expiry_date"],
        K.AUTHORIZATION_MAX_TERM_DAYS,
    )

    row = new_row("authorizations", {
        "client_id": client_row["id"],
        "scope_tier": ctx.body["scope_tier"],
        "instrument_reference": ctx.body["instrument_reference"],
        "effective_date": ctx.body["effective_date"],
        "expiry_date": ctx.body["expiry_date"],
        "status": "DRAFT",
        "executed_at": None,
        "revoked_at": None,
        "revocation_reason": None,
        "cascaded_payments_cancelled": 0,
        "cascaded_recipients_terminated": 0,
        "cascaded_applications_withdrawn": 0,
    })
    set_subject(row["id"])
    return object_response(serialize.authorization(row), 201)


def _check_date_span(effective_date, expiry_date, max_days=None):
    start = parse_date(effective_date)
    end = parse_date(expiry_date)
    if start is None or end is None:
        fail("ERR_VALIDATION", "Dates must be plain YYYY-MM-DD calendar dates.")
    if not end > start:
        fail("ERR_VALIDATION", "expiry_date must be strictly after effective_date.")
    if max_days is not None and (end - start).days > max_days:
        fail("ERR_VALIDATION", "The term exceeds the permitted maximum.")


@bp.post("/dmm/authorizations/<aid>/status")
@audited("Authorization", path_param="aid")
def drive_authorization_status(aid):
    ctx = authorize("FiduciaryManager")                        # rungs 1-2
    auth = resolve("authorizations", aid)                      # rung 3
    set_client(auth["client_id"])
    ctx.check_shape([                                          # rung 4
        ("to_status", str, True),
        ("revocation_reason", str, False),
    ])
    if ctx.body.get("to_status") == "REVOKED":
        ctx.require_conditional("revocation_reason")
    ctx.check_enum("to_status", K.AUTHORIZATION_STATUS)        # rung 5

    to_status = ctx.body["to_status"]

    # rung 12 - the state gate.
    if to_status == "ACTIVE":
        if auth["status"] != "DRAFT":
            fail("ERR_INVALID_STATE", "Only a DRAFT instrument may be executed.")
        client_row = db.clients.get(auth["client_id"])
        if client_row is None or client_row["status"] not in ("ACTIVE", "INTAKE"):
            fail("ERR_INVALID_STATE", "The client cannot have an instrument executed.")
    elif to_status == "REVOKED":
        if auth["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "Only an ACTIVE instrument may be revoked.")
    else:
        fail("ERR_INVALID_STATE", "No transition leads to that status.")

    if to_status == "REVOKED":                                 # rung 15
        if ctx.body["revocation_reason"].strip() == "":
            fail("ERR_VALIDATION", "revocation_reason must not be empty.")

    if to_status == "ACTIVE":
        auth["status"] = "ACTIVE"
        auth["executed_at"] = db.now
        for other in db.ordered("authorizations"):
            if other["id"] == auth["id"]:
                continue
            if other["client_id"] != auth["client_id"]:
                continue
            if other["status"] != "ACTIVE":
                continue
            other["status"] = "SUPERSEDED"
            bump(other)
        bump(auth)
    else:
        revoke_authorization(auth, ctx.body["revocation_reason"])

    return object_response(serialize.authorization(auth), 200)


@bp.get("/dmm/authorizations/<aid>")
def read_authorization(aid):
    authorize("FiduciaryManager", "BillPaySpecialist", "ComplianceOfficer",
              "PlatformAdmin")
    return object_response(serialize.authorization(resolve("authorizations", aid)), 200)
