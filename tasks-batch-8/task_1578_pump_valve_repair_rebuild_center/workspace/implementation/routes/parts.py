from flask import Blueprint, request

from db import DB, stamp_new, touch
from errors import ERR_SUPERSEDES_NOT_ACTIVE, not_found, raise_err, invalid_state
from middleware import (
    as_bool,
    as_int,
    as_string,
    authenticate,
    get_json_body,
    require_roles,
)
from response import success_list, success_object
from routes.customers import parse_pagination

bp = Blueprint("parts", __name__)


@bp.route("/parts", methods=["POST"])
def create_part():
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["ServiceManager"])
    part_number = as_string(body, "part_number")
    description = as_string(body, "description")
    unit_price_cents = as_int(body, "unit_price_cents")
    aftermarket_allowed = as_bool(body, "aftermarket_allowed", default=False)

    part = stamp_new(
        {
            "part_number": part_number,
            "description": description,
            "unit_price_cents": unit_price_cents,
            "aftermarket_allowed": aftermarket_allowed,
            "status": "ACTIVE",
            "superseded_by_id": None,
        }
    )
    DB.parts[part["id"]] = part
    return success_object(part, status=201)


@bp.route("/parts", methods=["GET"])
def list_parts():
    authenticate()
    limit, offset = parse_pagination()
    status = request.args.get("status")
    superseded_by_id = request.args.get("superseded_by_id")
    items = sorted(DB.parts.values(), key=lambda p: (p["created_at"], p["id"]))
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if superseded_by_id is not None:
        items = [p for p in items if p.get("superseded_by_id") == superseded_by_id]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list(page, limit, offset, total)


@bp.route("/parts/<pid>", methods=["GET"])
def get_part(pid):
    authenticate()
    part = DB.parts.get(pid)
    if part is None:
        not_found("Part not found")
    return success_object(part)


@bp.route("/parts/<pid>/mark-obsolete", methods=["POST"])
def mark_obsolete(pid):
    caller = authenticate()
    body = get_json_body()
    require_roles(caller, ["ServiceManager"])
    part = DB.parts.get(pid)
    if part is None:
        not_found("Part not found")
    if part["status"] != "ACTIVE":
        invalid_state("Part is not ACTIVE")

    superseded_by_id = body.get("superseded_by_id")
    if superseded_by_id is not None:
        if not isinstance(superseded_by_id, str):
            raise_err(ERR_SUPERSEDES_NOT_ACTIVE, "superseded_by_id must be a string id")
        target = DB.parts.get(superseded_by_id)
        if target is None or target["status"] != "ACTIVE" or target["id"] == part["id"]:
            raise_err(
                ERR_SUPERSEDES_NOT_ACTIVE,
                "superseded_by_id must reference an existing ACTIVE part other than this part",
            )
        part["superseded_by_id"] = superseded_by_id

    part["status"] = "OBSOLETE"
    touch(part)

    # Cascade into open quoting work.
    for quote in DB.quotes.values():
        if quote["status"] not in ("DRAFT", "ISSUED", "REVISION_REQUESTED"):
            continue
        affected = False
        for line in quote.get("part_lines", []):
            if isinstance(line, dict) and line.get("part_id") == part["id"]:
                line["substitution_required"] = True
                affected = True
        if affected:
            if quote["status"] == "ISSUED":
                quote["status"] = "REVISION_REQUESTED"
                ro = DB.repair_orders.get(quote["repair_order_id"])
                if ro is not None:
                    if not ro.get("quote_attention_required"):
                        ro["quote_attention_required"] = True
                        touch(ro)
            touch(quote)

    return success_object(part)
