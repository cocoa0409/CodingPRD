"""LicenseBoard + CreditRequirement endpoints (PRD §3.1)."""

from flask import Blueprint

import errors
import serialize
from common import (
    get_json_body,
    require_string,
    require_number,
    require_field,
    enum_field,
    optional_field,
    parse_pagination,
    paginate,
)
from db import db
from middleware import require_roles
from models import new_full_record
from response import success_object, success_list
from util import round_half_up_1, as_decimal

bp = Blueprint("license_boards", __name__)

CREDIT_UNITS = {"CEU", "CME", "CLE"}
CATEGORIES = {"ETHICS", "SUBSTANCE", "GENERAL"}


def get_board_or_404(board_id):
    board = db.license_boards.get(board_id)
    if board is None:
        raise errors.not_found(f"LicenseBoard '{board_id}' not found.")
    return board


@bp.route("/license-boards", methods=["POST"])
@require_roles("BoardAdmin")
def create_license_board():
    body = get_json_body()
    name = require_string(body, "name")
    jurisdiction_code = require_string(body, "jurisdiction_code")
    credit_unit = enum_field(body, "credit_unit", CREDIT_UNITS)

    cycle_length_months = require_number(body, "cycle_length_months")
    total_required_hours = require_number(body, "total_required_hours")

    # cycle_length_months must be an integer >= 1.
    if isinstance(cycle_length_months, float) and not cycle_length_months.is_integer():
        raise errors.invalid_request("cycle_length_months must be an integer.")
    cycle_length_months = int(cycle_length_months)
    if cycle_length_months < 1:
        raise errors.validation_range("cycle_length_months must be >= 1.")

    if total_required_hours < 0:
        raise errors.validation_range("total_required_hours must be >= 0.")

    carryover_cap_hours = optional_field(body, "carryover_cap_hours", default=10.0, types=(int, float))
    audit_cooldown_days = optional_field(body, "audit_cooldown_days", default=365, types=int)
    reminder_lead_days = optional_field(body, "reminder_lead_days", default=60, types=int)

    if carryover_cap_hours is None:
        carryover_cap_hours = 10.0
    if isinstance(carryover_cap_hours, bool) or not isinstance(carryover_cap_hours, (int, float)):
        raise errors.invalid_request("carryover_cap_hours must be a number.")
    if carryover_cap_hours < 0:
        raise errors.validation_range("carryover_cap_hours must be >= 0.")

    if isinstance(audit_cooldown_days, bool) or not isinstance(audit_cooldown_days, int):
        raise errors.invalid_request("audit_cooldown_days must be an integer.")
    if audit_cooldown_days < 0:
        raise errors.validation_range("audit_cooldown_days must be >= 0.")

    if isinstance(reminder_lead_days, bool) or not isinstance(reminder_lead_days, int):
        raise errors.invalid_request("reminder_lead_days must be an integer.")
    if reminder_lead_days < 0:
        raise errors.validation_range("reminder_lead_days must be >= 0.")

    # jurisdiction_code: uppercase, length 2; unique with credit_unit.
    if not (isinstance(jurisdiction_code, str) and len(jurisdiction_code) == 2
            and jurisdiction_code.isupper()):
        raise errors.invalid_request("jurisdiction_code must be 2 uppercase letters.")

    with db.lock:
        for b in db.license_boards.values():
            if (b["jurisdiction_code"] == jurisdiction_code
                    and b["credit_unit"] == credit_unit):
                raise errors.validation_range(
                    "(jurisdiction_code, credit_unit) must be unique across boards."
                )

        rec = new_full_record()
        rec.update({
            "name": name,
            "jurisdiction_code": jurisdiction_code,
            "credit_unit": credit_unit,
            "cycle_length_months": cycle_length_months,
            "total_required_hours": round_half_up_1(total_required_hours),
            "carryover_cap_hours": round_half_up_1(carryover_cap_hours),
            "audit_cooldown_days": audit_cooldown_days,
            "reminder_lead_days": reminder_lead_days,
        })
        db.license_boards[rec["id"]] = rec

    return success_object(serialize.license_board(rec), status=201)


@bp.route("/license-boards/<board_id>", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def get_license_board(board_id):
    board = get_board_or_404(board_id)
    return success_object(serialize.license_board(board), status=200)


@bp.route("/license-boards/<board_id>/requirements", methods=["POST"])
@require_roles("BoardAdmin")
def add_requirement(board_id):
    board = get_board_or_404(board_id)
    body = get_json_body()
    category = enum_field(body, "category", CATEGORIES)
    min_hours = require_number(body, "min_hours")
    if min_hours < 0:
        raise errors.validation_range("min_hours must be >= 0.")
    min_hours = round_half_up_1(min_hours)

    with db.lock:
        # (board_id, category) unique.
        for r in db.credit_requirements.values():
            if r["board_id"] == board_id and r["category"] == category:
                raise errors.validation_range(
                    "(board_id, category) must be unique."
                )

        # Sum of non-GENERAL min_hours must not exceed board.total_required_hours.
        if category != "GENERAL":
            existing_sum = as_decimal(0)
            for r in db.credit_requirements.values():
                if r["board_id"] == board_id and r["category"] != "GENERAL":
                    existing_sum += as_decimal(r["min_hours"])
            new_sum = existing_sum + as_decimal(min_hours)
            if new_sum > as_decimal(board["total_required_hours"]):
                raise errors.validation_range(
                    "Sum of non-GENERAL min_hours exceeds board.total_required_hours."
                )

        rec = new_full_record()
        rec.update({
            "board_id": board_id,
            "category": category,
            "min_hours": min_hours,
        })
        db.credit_requirements[rec["id"]] = rec

    return success_object(serialize.credit_requirement(rec), status=201)


@bp.route("/license-boards/<board_id>/requirements", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def list_requirements(board_id):
    get_board_or_404(board_id)
    limit, offset = parse_pagination()
    items = [
        r for r in db.credit_requirements.values() if r["board_id"] == board_id
    ]
    items.sort(key=lambda r: r["created_at"])
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list(
        [serialize.credit_requirement(r) for r in page],
        limit, offset, total, status=200,
    )


@bp.route("/credit-requirements/<req_id>", methods=["GET"])
@require_roles("BoardAdmin", "Provider", "Licensee", "Auditor")
def get_requirement(req_id):
    rec = db.credit_requirements.get(req_id)
    if rec is None:
        raise errors.not_found(f"CreditRequirement '{req_id}' not found.")
    return success_object(serialize.credit_requirement(rec), status=200)
