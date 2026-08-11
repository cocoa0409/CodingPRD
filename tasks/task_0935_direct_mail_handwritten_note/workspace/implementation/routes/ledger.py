"""Postage ledger reads."""
from flask import Blueprint, request

import envelope
import serial
from ladder import Ctx
from store import db

bp = Blueprint("ledger", __name__)

LEDGER_ROLES = ["PlatformAdmin", "AccountOwner", "CampaignManager", "ComplianceOfficer"]


@bp.route("/mail/postage-ledger-entries/<postage_ledger_entry_id>", methods=["GET"])
def get_entry(postage_ledger_entry_id):
    ctx = Ctx(LEDGER_ROLES)
    ctx.path("ledger_entry", postage_ledger_entry_id)
    ctx.scope(lambda: ctx.get("ledger_entry")["account_id"])
    ctx.run()
    return envelope.object_response(serial.ledger_entry(ctx.get("ledger_entry")), 200)


@bp.route("/mail/postage-ledger-entries", methods=["GET"])
def list_entries():
    ctx = Ctx(LEDGER_ROLES)
    ctx.run()
    rows = list(db.ledger_entries.values())
    for field in ("account_id", "campaign_id", "mail_job_id", "entry_type"):
        wanted = request.args.get(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.ledger_entry(r) for r in page], limit, offset, total)
