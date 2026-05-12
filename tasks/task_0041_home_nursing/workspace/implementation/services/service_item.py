"""ServiceItem catalog logic."""
import db
from errors import err
from services.constants import SPECIALTY_TAGS
from services.util import require_str, require_int, require_enum


def create_service_item(body: dict) -> dict:
    code = require_str(body, "code")
    name = require_str(body, "name")
    description = body.get("description", "")
    if description is not None and not isinstance(description, str):
        raise err("ERR_INVALID_REQUEST", "description must be a string")
    contraindications = body.get("contraindications", "")
    if contraindications is not None and not isinstance(contraindications, str):
        raise err("ERR_INVALID_REQUEST", "contraindications must be a string")
    required_skill = require_enum(body, "required_skill", SPECIALTY_TAGS)
    base_price = require_int(body, "base_price_cents")
    if base_price < 0:
        raise err("ERR_INVALID_REQUEST", "base_price_cents must be >= 0")
    duration = require_int(body, "duration_minutes")
    if duration <= 0:
        raise err("ERR_INVALID_REQUEST", "duration_minutes must be > 0")
    requires_doc = bool(body.get("requires_medical_doc", False))
    requires_review = bool(body.get("requires_eligibility_review", False))
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err("ERR_INVALID_REQUEST", "active must be a boolean")

    if code in db.service_items:
        raise err("ERR_INVALID_REQUEST", f"service item code {code} already exists")

    item = {
        "code": code,
        "name": name,
        "description": description or "",
        "contraindications": contraindications or "",
        "required_skill": required_skill,
        "requires_medical_doc": requires_doc,
        "requires_eligibility_review": requires_review,
        "base_price_cents": base_price,
        "duration_minutes": duration,
        "active": active,
    }
    db.stamp_create(item, common_fields=True)
    # id is a server-minted UUID per PRD §2.4; code is a separate
    # unique catalog identifier per PRD §3.2.
    db.service_items[code] = item
    return item


def list_service_items(limit: int, offset: int, active=None):
    rows = list(db.service_items.values())
    if active is not None:
        rows = [r for r in rows if r.get("active") == active]
    rows.sort(key=lambda r: r["_seq"])
    total = len(rows)
    return rows[offset: offset + limit], total


def get_service_item(code: str, *, allow_inactive: bool = True) -> dict:
    item = db.service_items.get(code)
    if item is None:
        raise err("ERR_SERVICE_ITEM_NOT_FOUND", f"service item {code} not found")
    return item
