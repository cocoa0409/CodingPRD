"""Templates and CASCADE A — what a content edit destroys."""
from flask import Blueprint, request

import enums
import envelope
import serial
import services
import store
from ladder import Ctx
from model import new_row, touch
from store import db

bp = Blueprint("templates", __name__)

TEMPLATE_READ_ROLES = ["PlatformAdmin", "AccountOwner", "CampaignManager", "ProductionOperator"]


@bp.route("/mail/templates", methods=["POST"])
def create_template():
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager"])
    ctx.fk("account", "account_id")
    ctx.fk("handwriting_style", "handwriting_style_id")
    ctx.scope(lambda: ctx.get("account")["id"] if ctx.get("account") else None)
    ctx.fields(required=[("account_id", "str"), ("handwriting_style_id", "str"),
                         ("name", "str"), ("body_text", "str"),
                         ("character_count", "int")],
               optional=[("envelope_style", "str")])
    ctx.enums([("envelope_style", enums.ENVELOPE_STYLES)])
    ctx.ranges([("character_count", store.MIN_TEMPLATE_CHARACTER_COUNT,
                 store.MAX_TEMPLATE_CHARACTER_COUNT, False)])
    ctx.run()
    row = new_row({
        "account_id": ctx.body["account_id"],
        "handwriting_style_id": ctx.body["handwriting_style_id"],
        "name": ctx.body["name"],
        "body_text": ctx.body["body_text"],
        "character_count": ctx.body["character_count"],
        "version_no": 1,
        "envelope_style": ctx.body.get("envelope_style") or "STANDARD",
    })
    db.templates[row["id"]] = row
    return envelope.object_response(serial.template(row), 201)


@bp.route("/mail/templates/<template_id>", methods=["GET"])
def get_template(template_id):
    ctx = Ctx(TEMPLATE_READ_ROLES)
    ctx.path("template", template_id)
    ctx.scope(lambda: ctx.get("template")["account_id"])
    ctx.run()
    return envelope.object_response(serial.template(ctx.get("template")), 200)


@bp.route("/mail/templates", methods=["GET"])
def list_templates():
    ctx = Ctx(TEMPLATE_READ_ROLES)
    ctx.run()
    rows = list(db.templates.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    style_id = request.args.get("handwriting_style_id")
    if style_id is not None:
        rows = [r for r in rows if r["handwriting_style_id"] == style_id]
    rows = envelope.sort_rows(rows)
    page, limit, offset, total = envelope.paginate(rows, request.args)
    return envelope.list_response([serial.template(r) for r in page], limit, offset, total)


def _template_campaigns(template_id):
    """PRD 3.2: the edit "is an ordinary write against the campaigns behind
    those jobs, and is therefore subject to the write gate of 2.5"."""
    seen = []
    out = []
    for job in db.mail_jobs.values():
        if job["template_id"] != template_id:
            continue
        campaign = db.campaigns.get(job["campaign_id"])
        if campaign is not None and campaign["id"] not in seen:
            seen.append(campaign["id"])
            out.append(campaign)
    return out


@bp.route("/mail/templates/<template_id>", methods=["PATCH"])
def patch_template(template_id):
    ctx = Ctx(["PlatformAdmin", "AccountOwner", "CampaignManager"])
    ctx.path("template", template_id)
    ctx.scope(lambda: ctx.get("template")["account_id"])
    ctx.fields(optional=[("body_text", "str"), ("character_count", "int"),
                         ("envelope_style", "str")])
    ctx.enums([("envelope_style", enums.ENVELOPE_STYLES)])
    ctx.ranges([("character_count", store.MIN_TEMPLATE_CHARACTER_COUNT,
                 store.MAX_TEMPLATE_CHARACTER_COUNT, False)])
    ctx.gate(lambda: _template_campaigns(template_id))
    ctx.run()
    template = ctx.get("template")
    changed = False
    if "body_text" in ctx.body and ctx.body["body_text"] is not None:
        if ctx.body["body_text"] != template["body_text"]:
            changed = True
        template["body_text"] = ctx.body["body_text"]
    if "character_count" in ctx.body and ctx.body["character_count"] is not None:
        if ctx.body["character_count"] != template["character_count"]:
            changed = True
        template["character_count"] = ctx.body["character_count"]
    if "envelope_style" in ctx.body and ctx.body["envelope_style"] is not None:
        template["envelope_style"] = ctx.body["envelope_style"]
    if changed:
        services.cascade_a(template)
    touch(template)
    return envelope.object_response(serial.template(template), 200)
