"""PesticideRegistry service."""

from common import (
    FERTILIZER_REGNO_RE,
    PESTICIDE_REGNO_RE,
    get_json_body,
    parse_iso_datetime,
    paginate,
    parse_pagination,
    require_field,
    sort_by_created_at,
    stamp_create_immutable,
)
from db import db
from errors import ERR_VALIDATION, raise_error
from services.audit import record_audit


def _serialize(reg: dict) -> dict:
    return {
        "id": reg["id"],
        "created_at": reg["created_at"],
        "registration_no": reg["registration_no"],
        "product_name": reg["product_name"],
        "category": reg["category"],
        "withdrawal_period_days": reg["withdrawal_period_days"],
        "max_dosage_per_hectare_g": reg["max_dosage_per_hectare_g"],
        "prohibited": reg.get("prohibited", False),
        "prohibited_since": reg.get("prohibited_since"),
    }


def create_registry(body):
    registration_no = require_field(body, "registration_no", str)
    product_name = require_field(body, "product_name", str)
    category = require_field(body, "category", str)
    withdrawal_period_days = require_field(body, "withdrawal_period_days", int)
    max_dosage = body.get("max_dosage_per_hectare_g")
    if max_dosage is None:
        raise_error(ERR_VALIDATION, "missing required field max_dosage_per_hectare_g")

    if category not in {"PESTICIDE", "FERTILIZER"}:
        raise_error(ERR_VALIDATION, "category must be PESTICIDE or FERTILIZER")
    if category == "PESTICIDE" and not PESTICIDE_REGNO_RE.match(registration_no):
        raise_error(ERR_VALIDATION, "registration_no must match ^PD-[0-9]{6}$ for PESTICIDE")
    if category == "FERTILIZER" and not FERTILIZER_REGNO_RE.match(registration_no):
        raise_error(ERR_VALIDATION, "registration_no must match ^FT-[0-9]{6}$ for FERTILIZER")
    if withdrawal_period_days < 0:
        raise_error(ERR_VALIDATION, "withdrawal_period_days must be >= 0")
    try:
        max_dosage_f = float(max_dosage)
    except Exception:
        raise_error(ERR_VALIDATION, "max_dosage_per_hectare_g must be numeric")

    with db.lock:
        if registration_no in db.pesticide_registry:
            raise_error(ERR_VALIDATION, "registration_no already registered")

        prohibited = bool(body.get("prohibited", False))
        prohibited_since = body.get("prohibited_since")
        if prohibited and prohibited_since is None:
            raise_error(ERR_VALIDATION, "prohibited_since required when prohibited=true")
        if prohibited_since is not None:
            # validate by parsing
            parse_iso_datetime(prohibited_since, "prohibited_since")

        reg = {
            "id": db.new_id(),
            "registration_no": registration_no,
            "product_name": product_name,
            "category": category,
            "withdrawal_period_days": withdrawal_period_days,
            "max_dosage_per_hectare_g": max_dosage_f,
            "prohibited": prohibited,
            "prohibited_since": prohibited_since,
        }
        stamp_create_immutable(reg)
        db.pesticide_registry[registration_no] = reg
        record_audit(
            "PesticideRegistry", reg["id"], "CREATE", "REGISTERED",
            before_state=None,
            change_summary={"registration_no": registration_no},
        )
    return _serialize(reg)


def list_registry(args):
    limit, offset = parse_pagination()
    prohibited = args.get("prohibited")
    category = args.get("category")
    items = list(db.pesticide_registry.values())
    if prohibited is not None:
        flag = str(prohibited).lower() == "true"
        items = [r for r in items if bool(r.get("prohibited", False)) == flag]
    if category is not None:
        items = [r for r in items if r.get("category") == category]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return [_serialize(r) for r in page], limit, offset, total


def prohibit_registry(registration_no):
    body = get_json_body()
    prohibited_since = require_field(body, "prohibited_since", str)
    parse_iso_datetime(prohibited_since, "prohibited_since")
    with db.lock:
        reg = db.pesticide_registry.get(registration_no)
        if reg is None:
            from errors import ERR_NOT_FOUND
            raise_error(ERR_NOT_FOUND, f"pesticide registry {registration_no} not found")
        before = "prohibited" if reg.get("prohibited") else "active"
        reg["prohibited"] = True
        reg["prohibited_since"] = prohibited_since
        record_audit(
            "PesticideRegistry", reg["id"], "UPDATE", "prohibited",
            before_state=before,
            change_summary={"prohibited_since": prohibited_since},
        )
    return _serialize(reg)
