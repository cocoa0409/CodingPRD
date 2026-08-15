"""Site endpoints."""

from flask import Blueprint
from db import db
from middleware import require_roles
from validate import (get_body, req_string, opt_string, opt_int, opt_enum,
                      parse_pagination)
from response import success_object, success_list
from errors import not_found, invalid_state, already_terminal

bp = Blueprint("sites", __name__)

SITE_TYPES = {"LIBRARY_BRANCH", "GARDEN"}


def site_view(s):
    return {k: v for k, v in s.items() if not k.startswith("_")}


def get_site_or_404(site_id):
    s = db.sites.get(site_id)
    if s is None:
        raise not_found("Site not found.")
    return s


@bp.post("/api/sites")
def create_site():
    require_roles("ProgramAdmin")
    body = get_body()
    name = req_string(body, "name")
    site_type = opt_enum(body, "site_type", SITE_TYPES)
    if site_type is None:
        from errors import invalid_request
        raise invalid_request("Missing required field: site_type")
    region_zone = req_string(body, "region_zone")
    label_stock_count = opt_int(body, "label_stock_count", min_v=0, default=0)
    site = {
        "name": name,
        "site_type": site_type,
        "region_zone": region_zone,
        "label_stock_count": label_stock_count,
        "status": "ACTIVE",
    }
    db.stamp_new(site)
    db.sites[site["id"]] = site
    return success_object(site_view(site), 201)


@bp.get("/api/sites")
def list_sites():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    status_f = None
    from flask import request
    from errors import invalid_enum
    status_f = request.args.get("status")
    if status_f is not None and status_f not in ("ACTIVE", "INACTIVE"):
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.sites.values(), key=lambda s: s["_seq"])
    if status_f:
        items = [s for s in items if s["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([site_view(s) for s in page], limit, offset, total)


@bp.get("/api/sites/<site_id>")
def get_site(site_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    s = get_site_or_404(site_id)
    return success_object(site_view(s))


@bp.patch("/api/sites/<site_id>")
def patch_site(site_id):
    require_roles("ProgramAdmin")
    s = get_site_or_404(site_id)
    body = get_body()
    name = opt_string(body, "name")
    region_zone = opt_string(body, "region_zone")
    label_stock_count = opt_int(body, "label_stock_count", min_v=0, default=None)
    new_status = opt_enum(body, "status", {"ACTIVE", "INACTIVE"}, default=None)

    if new_status is not None and new_status != s["status"]:
        if s["status"] == "ACTIVE" and new_status == "INACTIVE":
            # precondition: no non-terminal-ish swap event hosted here
            for ev in db.events.values():
                if ev["site_id"] == s["id"] and ev["status"] in (
                        "DRAFT", "SCHEDULED", "INTAKE_OPEN", "INTAKE_CLOSED"):
                    raise invalid_state(
                        "Site hosts a swap event that is not completed or cancelled.")
            s["status"] = "INACTIVE"
        elif s["status"] == "INACTIVE" and new_status == "ACTIVE":
            s["status"] = "ACTIVE"
    if name is not None:
        s["name"] = name
    if region_zone is not None:
        s["region_zone"] = region_zone
    if label_stock_count is not None:
        s["label_stock_count"] = label_stock_count
    db.touch(s)
    return success_object(site_view(s))
