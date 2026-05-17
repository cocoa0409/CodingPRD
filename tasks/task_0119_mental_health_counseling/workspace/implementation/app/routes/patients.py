"""Patient routes."""
from __future__ import annotations

from typing import Any

from flask import Blueprint

from ..auth import require_roles
from ..clock import now
from ..errors import (
    err_invalid_amount,
    err_not_found,
    err_reference_not_found,
    err_validation,
)
from ..helpers import (
    assert_integer,
    assert_string,
    new_uuid,
    occ_check,
    require_json_object,
)
from ..responses import created, ok
from ..services.calculations import sliding_fee_tier_pct
from ..services.cascades import bump
from ..services.serialize import serialize_patient
from ..store import store

bp = Blueprint("patients", __name__, url_prefix="/practice/patients")


@bp.post("")
@require_roles("PracticeAdmin", "Therapist")
def create_patient(**_):
    body = require_json_object()
    full_name = assert_string(body.get("full_name"), "full_name")
    state_of_residence = assert_string(body.get("state_of_residence"), "state_of_residence", pattern=r"^[A-Z]{2}$")
    # household_income_cents: presence/type → ERR_VALIDATION; value (< 0) → ERR_INVALID_AMOUNT.
    income = body.get("household_income_cents")
    if income is None:
        raise err_validation("household_income_cents is required")
    if isinstance(income, bool) or not isinstance(income, int):
        raise err_validation("household_income_cents must be an integer")
    if income < 0:
        raise err_invalid_amount("household_income_cents must be >= 0")
    size = assert_integer(body.get("household_size"), "household_size", minimum=1)
    insurance_plan_id = body.get("insurance_plan_id", None)
    if insurance_plan_id is not None and not isinstance(insurance_plan_id, str):
        raise err_validation("insurance_plan_id must be a string")

    s = store()
    with s.lock:
        if insurance_plan_id is not None and insurance_plan_id not in s.insurance_plans:
            raise err_reference_not_found("insurance_plan_id does not resolve")
        pid = new_uuid()
        ts = now()
        row: dict[str, Any] = {
            "id": pid,
            "full_name": full_name,
            "state_of_residence": state_of_residence,
            "household_income_cents": income,
            "household_size": size,
            "sliding_fee_tier_pct": sliding_fee_tier_pct(income, size),
            "insurance_plan_id": insurance_plan_id,
            "deductible_remaining_cents": 0,
            "latest_crisis_level": None,
            "safety_plan_required": False,
            "created_at": ts,
            "updated_at": ts,
            "version": 1,
        }
        s.patients[pid] = row
        return created(serialize_patient(row))


@bp.get("/<pid>")
@require_roles("PracticeAdmin", "Therapist", "BillingClerk")
def get_patient(pid: str, **_):
    s = store()
    row = s.patients.get(pid)
    if row is None:
        raise err_not_found("Patient not found")
    return ok(serialize_patient(row))


@bp.patch("/<pid>")
@require_roles("PracticeAdmin", "BillingClerk")
def update_patient(pid: str, **_):
    body = require_json_object()
    s = store()
    with s.lock:
        row = s.patients.get(pid)
        if row is None:
            raise err_not_found("Patient not found")
        occ_check(body.get("version"), row["version"])

        recompute_tier = False
        if "state_of_residence" in body:
            row["state_of_residence"] = assert_string(
                body["state_of_residence"], "state_of_residence", pattern=r"^[A-Z]{2}$"
            )
        if "household_income_cents" in body:
            v = body["household_income_cents"]
            if isinstance(v, bool) or not isinstance(v, int):
                raise err_validation("household_income_cents must be an integer")
            if v < 0:
                raise err_invalid_amount("household_income_cents must be >= 0")
            row["household_income_cents"] = v
            recompute_tier = True
        if "household_size" in body:
            v = assert_integer(body["household_size"], "household_size", minimum=1)
            row["household_size"] = v
            recompute_tier = True
        if "insurance_plan_id" in body:
            v = body["insurance_plan_id"]
            if v is not None and not isinstance(v, str):
                raise err_validation("insurance_plan_id must be a string or null")
            if v is not None and v not in s.insurance_plans:
                raise err_reference_not_found("insurance_plan_id does not resolve")
            row["insurance_plan_id"] = v
        if "deductible_remaining_cents" in body:
            v = body["deductible_remaining_cents"]
            if isinstance(v, bool) or not isinstance(v, int):
                raise err_validation("deductible_remaining_cents must be an integer")
            if v < 0:
                raise err_invalid_amount("deductible_remaining_cents must be >= 0")
            row["deductible_remaining_cents"] = v

        if recompute_tier:
            row["sliding_fee_tier_pct"] = sliding_fee_tier_pct(
                row["household_income_cents"], row["household_size"]
            )
        bump(row)
        return ok(serialize_patient(row))
