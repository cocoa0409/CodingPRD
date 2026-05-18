"""Damages endpoints (PRD §3.4)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import Blueprint

from config import DAMAGES_METHODS, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER, ROLE_PARALEGAL
from db import store
from errors import raise_error
from middleware import require_auth
from response import success
from routes._helpers import get_json_body
from services.calculations import calc_damages_total, sum_received_medical_bills
from services.case_engine import (
    assert_case_not_closed,
    check_version_match,
    get_case_or_404,
    now,
    touch,
)
from services.serializers import damages_to_dict
from utils import new_uuid


bp = Blueprint("damages", __name__)

RW_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY]
ALL_ROLES = [ROLE_PARALEGAL, ROLE_ATTORNEY, ROLE_MANAGING_PARTNER]


def _validate_method_inputs(method, multiplier_value, per_diem_rate, per_diem_days):
    """Cross-field validation per §3.4 / V_priority_52."""
    if method == "MULTIPLIER":
        # Default multiplier_value = 1.5 if missing.
        try:
            value = Decimal(str(multiplier_value)) if multiplier_value is not None else Decimal("1.5")
        except (InvalidOperation, TypeError):
            raise_error("ERR_DAMAGES_METHOD_INPUTS_INVALID", "multiplier_value must be numeric.")
        if value < Decimal("1.0") or value > Decimal("5.0"):
            raise_error(
                "ERR_DAMAGES_METHOD_INPUTS_INVALID",
                "multiplier_value must be in [1.0, 5.0].",
            )
        # Quantize to one decimal place.
        value = value.quantize(Decimal("0.1"))
        return value, 0, 0
    elif method == "PER_DIEM":
        if per_diem_rate is None or per_diem_days is None:
            raise_error(
                "ERR_DAMAGES_METHOD_INPUTS_INVALID",
                "per_diem_rate_cents and per_diem_days are required for PER_DIEM.",
            )
        if not isinstance(per_diem_rate, int) or isinstance(per_diem_rate, bool) or per_diem_rate <= 0:
            raise_error(
                "ERR_DAMAGES_METHOD_INPUTS_INVALID",
                "per_diem_rate_cents must be a positive integer.",
            )
        if not isinstance(per_diem_days, int) or isinstance(per_diem_days, bool) or per_diem_days <= 0:
            raise_error(
                "ERR_DAMAGES_METHOD_INPUTS_INVALID",
                "per_diem_days must be a positive integer.",
            )
        return None, int(per_diem_rate), int(per_diem_days)
    raise_error("ERR_VALIDATION", f"Unknown pain_suffering_method: {method}")


@bp.post("/pi-cases/<cid>/damages")
@require_auth(RW_ROLES)
def create_damages(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    lost_wages = body.get("lost_wages_cents", 0)
    property_damage = body.get("property_damage_cents", 0)
    if not isinstance(lost_wages, int) or isinstance(lost_wages, bool) or lost_wages < 0:
        raise_error("ERR_VALIDATION", "lost_wages_cents must be >= 0 integer.")
    if not isinstance(property_damage, int) or isinstance(property_damage, bool) or property_damage < 0:
        raise_error("ERR_VALIDATION", "property_damage_cents must be >= 0 integer.")

    method = body.get("pain_suffering_method", "MULTIPLIER")
    if method not in DAMAGES_METHODS:
        raise_error("ERR_VALIDATION", f"pain_suffering_method must be one of {sorted(DAMAGES_METHODS)}.")

    mult, per_rate, per_days = _validate_method_inputs(
        method,
        body.get("multiplier_value"),
        body.get("per_diem_rate_cents"),
        body.get("per_diem_days"),
    )

    with store.lock:
        if cid in store.damages_by_case:
            raise_error(
                "ERR_DAMAGES_ALREADY_EXISTS",
                "A Damages row already exists for this case.",
            )
        row = {
            "id": new_uuid(),
            "case_id": cid,
            "created_at": now(),
            "updated_at": now(),
            "version": 1,
            "medical_bills_cents": 0,
            "lost_wages_cents": int(lost_wages),
            "property_damage_cents": int(property_damage),
            "pain_suffering_method": method,
            "multiplier_value": float(mult) if mult is not None else None,
            "per_diem_rate_cents": per_rate,
            "per_diem_days": per_days,
            "pain_suffering_cents": 0,
            "total_damages_cents": 0,
        }
        # Recompute on creation against currently-received medical requests.
        received = sum_received_medical_bills(cid, store.medical_requests)
        calc_damages_total(row, received)
        store.damages[row["id"]] = row
        store.damages_by_case[cid] = row["id"]

    return success(damages_to_dict(row), 201)


@bp.patch("/pi-cases/<cid>/damages")
@require_auth(RW_ROLES)
def patch_damages(cid):
    body = get_json_body()
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)

    damages_id = store.damages_by_case.get(cid)
    if not damages_id:
        raise_error("ERR_NOT_FOUND", "Damages row not found.")
    row = store.damages[damages_id]

    check_version_match(row, body.get("version"))

    # Validate per-field updates.
    if "lost_wages_cents" in body:
        v = body["lost_wages_cents"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_error("ERR_VALIDATION", "lost_wages_cents must be >= 0 integer.")
        row["lost_wages_cents"] = int(v)
    if "property_damage_cents" in body:
        v = body["property_damage_cents"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_error("ERR_VALIDATION", "property_damage_cents must be >= 0 integer.")
        row["property_damage_cents"] = int(v)

    # Method-change branch.
    method = body.get("pain_suffering_method", row["pain_suffering_method"])
    if method not in DAMAGES_METHODS:
        raise_error("ERR_VALIDATION", f"pain_suffering_method must be one of {sorted(DAMAGES_METHODS)}.")

    multiplier_provided = body.get(
        "multiplier_value",
        row.get("multiplier_value") if method == "MULTIPLIER" else None,
    )
    rate_provided = body.get(
        "per_diem_rate_cents",
        row.get("per_diem_rate_cents") if method == "PER_DIEM" else None,
    )
    days_provided = body.get(
        "per_diem_days",
        row.get("per_diem_days") if method == "PER_DIEM" else None,
    )

    mult, per_rate, per_days = _validate_method_inputs(
        method, multiplier_provided, rate_provided, days_provided,
    )

    with store.lock:
        row["pain_suffering_method"] = method
        if method == "MULTIPLIER":
            row["multiplier_value"] = float(mult) if mult is not None else None
        else:
            row["per_diem_rate_cents"] = per_rate
            row["per_diem_days"] = per_days

        received = sum_received_medical_bills(cid, store.medical_requests)
        calc_damages_total(row, received)
        touch(row)

    return success(damages_to_dict(row), 200)


@bp.get("/pi-cases/<cid>/damages")
@require_auth(ALL_ROLES)
def fetch_damages(cid):
    get_case_or_404(cid)
    damages_id = store.damages_by_case.get(cid)
    if not damages_id:
        raise_error("ERR_NOT_FOUND", "Damages row not found.")
    return success(damages_to_dict(store.damages[damages_id]), 200)


@bp.post("/pi-cases/<cid>/damages/recompute")
@require_auth(RW_ROLES)
def recompute_damages(cid):
    case_row = get_case_or_404(cid)
    assert_case_not_closed(case_row)
    damages_id = store.damages_by_case.get(cid)
    if not damages_id:
        raise_error("ERR_NOT_FOUND", "Damages row not found.")
    row = store.damages[damages_id]

    with store.lock:
        received = sum_received_medical_bills(cid, store.medical_requests)
        calc_damages_total(row, received)
        touch(row)

    return success(damages_to_dict(row), 200)
