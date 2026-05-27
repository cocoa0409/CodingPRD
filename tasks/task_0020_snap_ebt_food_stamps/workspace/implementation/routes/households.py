"""Household routes."""

import re
from flask import Blueprint, request

from db import db
from errors import raise_api
from middleware import require_roles
from response import success, list_success
from services.household_ops import bump_household
from util import (
    get_json_body, require_nonempty_str, optional_str, optional_bool,
    parse_pagination, paginate, new_id,
)


bp = Blueprint("households", __name__)

VALID_STATES = {"CA", "TX", "NY", "FL", "IL", "PA", "OH", "GA", "NC", "MI"}
CASE_NUMBER_RE = re.compile(r"^[A-Z]{2}-[0-9]{6}$")


def _hh_view(hh: dict) -> dict:
    return {
        "id": hh["id"],
        "case_number": hh["case_number"],
        "state_code": hh["state_code"],
        "address_line": hh["address_line"],
        "size": hh.get("size", 0),
        "gross_income_cents": hh.get("gross_income_cents", 0),
        "net_income_cents": hh.get("net_income_cents", 0),
        "status": hh["status"],
        "certification_end_date": hh.get("certification_end_date"),
        "heap_recipient": hh.get("heap_recipient", False),
        "created_at": hh["created_at"],
        "updated_at": hh["updated_at"],
        "version": hh["version"],
    }


@bp.route("/snap/households", methods=["POST"])
@require_roles("Caseworker")
def create_household(**_):
    body = get_json_body()
    case_number = require_nonempty_str(body, "case_number")
    state_code = require_nonempty_str(body, "state_code")
    address_line = require_nonempty_str(body, "address_line")
    heap_recipient = optional_bool(body, "heap_recipient", default=False)

    if not CASE_NUMBER_RE.match(case_number):
        raise_api("ERR_INVALID_REQUEST", "case_number must match ^[A-Z]{2}-[0-9]{6}$")
    if state_code not in VALID_STATES:
        raise_api("ERR_INVALID_REQUEST", "state_code not in allowed enum")

    for existing in db.households.values():
        if existing["case_number"] == case_number:
            raise_api("ERR_DUPLICATE_CASE_NUMBER", f"case_number {case_number} already exists")

    now = db.current_utc_iso()
    hh = {
        "id": new_id(),
        "case_number": case_number,
        "state_code": state_code,
        "address_line": address_line,
        "heap_recipient": heap_recipient,
        "size": 0,
        "gross_income_cents": 0,
        "net_income_cents": 0,
        "status": "PENDING",
        "certification_end_date": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.households[hh["id"]] = hh
    return success(_hh_view(hh), 201)


@bp.route("/snap/households/<hh_id>", methods=["GET"])
@require_roles("Caseworker", "Applicant", "FraudInvestigator", "BenefitIssuer")
def get_household(hh_id, _user_id, _role, **_):
    hh = db.households.get(hh_id)
    if hh is None:
        raise_api("ERR_NOT_FOUND", "Household not found")
    # Applicant: must own this household
    if _role == "Applicant" and _user_id != hh["id"]:
        raise_api("ERR_FORBIDDEN", "Applicant may only view own household")
    return success(_hh_view(hh))


@bp.route("/snap/households", methods=["GET"])
@require_roles("Caseworker", "FraudInvestigator", "BenefitIssuer")
def list_households(**_):
    limit, offset = parse_pagination()
    case_number = request.args.get("case_number")
    status = request.args.get("status")
    state_code = request.args.get("state_code")

    rows = list(db.households.values())
    if case_number is not None:
        rows = [r for r in rows if r["case_number"] == case_number]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]

    page, total = paginate(rows, limit, offset)
    return list_success([_hh_view(r) for r in page], limit, offset, total)


@bp.route("/snap/households/<hh_id>", methods=["PATCH"])
@require_roles("Caseworker")
def update_household(hh_id, **_):
    hh = db.households.get(hh_id)
    if hh is None:
        raise_api("ERR_NOT_FOUND", "Household not found")

    body = get_json_body()
    changed = False
    heap_changed = False

    if "address_line" in body:
        new_addr = body["address_line"]
        if not isinstance(new_addr, str) or not new_addr:
            raise_api("ERR_INVALID_REQUEST", "address_line must be a non-empty string")
        if hh["address_line"] != new_addr:
            hh["address_line"] = new_addr
            changed = True

    if "heap_recipient" in body:
        new_heap = body["heap_recipient"]
        if not isinstance(new_heap, bool):
            raise_api("ERR_INVALID_REQUEST", "heap_recipient must be a boolean")
        if hh["heap_recipient"] != new_heap:
            hh["heap_recipient"] = new_heap
            heap_changed = True
            changed = True

    if changed:
        if heap_changed:
            # Recompute net income (BENEFIT_CALC variant)
            from services.household_ops import recompute_household_totals
            recompute_household_totals(hh)
        bump_household(hh)

    return success(_hh_view(hh))


@bp.route("/snap/households/<hh_id>/suspend", methods=["POST"])
@require_roles("Caseworker")
def suspend_household(hh_id, **_):
    hh = db.households.get(hh_id)
    if hh is None:
        raise_api("ERR_NOT_FOUND", "Household not found")
    if hh["status"] != "ACTIVE":
        raise_api("ERR_INVALID_STATE", "Household must be ACTIVE to suspend")
    # Require at least one SUBSTANTIATED fraud flag
    has_substantiated = any(
        f["household_id"] == hh_id and f["status"] == "SUBSTANTIATED"
        for f in db.fraud_flags.values()
    )
    if not has_substantiated:
        raise_api(
            "ERR_INVALID_STATE",
            "Household suspension requires at least one SUBSTANTIATED FraudFlag",
        )

    hh["status"] = "SUSPENDED"

    # Cascade: ACTIVE EBT cards -> SUSPENDED
    for card in db.ebt_cards.values():
        if card["household_id"] == hh_id and card["status"] == "ACTIVE":
            card["status"] = "SUSPENDED"
            card["updated_at"] = db.current_utc_iso()
            card["version"] = int(card.get("version", 1)) + 1
            # Cascade further: AUTHORIZED purchase txs on this card -> REVERSED
            for tx in db.purchase_transactions.values():
                if tx["ebt_card_id"] == card["id"] and tx["status"] == "AUTHORIZED":
                    tx["status"] = "REVERSED"
                    tx["updated_at"] = db.current_utc_iso()
                    tx["version"] = int(tx.get("version", 1)) + 1

    # Cascade: DRAFT MonthlyAllotment for this household with benefit_month == current month -> EXPUNGED
    current_month = db.current_utc_iso()[:7]  # YYYY-MM
    for ma in db.monthly_allotments.values():
        if (ma["household_id"] == hh_id
                and ma["status"] == "DRAFT"
                and ma["benefit_month"] == current_month):
            ma["status"] = "EXPUNGED"
            ma["updated_at"] = db.current_utc_iso()
            ma["version"] = int(ma.get("version", 1)) + 1

    bump_household(hh)
    return success(_hh_view(hh))


@bp.route("/snap/households/<hh_id>/reinstate", methods=["POST"])
@require_roles("Caseworker")
def reinstate_household(hh_id, **_):
    hh = db.households.get(hh_id)
    if hh is None:
        raise_api("ERR_NOT_FOUND", "Household not found")
    if hh["status"] != "SUSPENDED":
        raise_api("ERR_INVALID_STATE", "Household must be SUSPENDED to reinstate")

    hh["status"] = "ACTIVE"

    # Cascade: SUSPENDED EBT cards -> ACTIVE
    for card in db.ebt_cards.values():
        if card["household_id"] == hh_id and card["status"] == "SUSPENDED":
            card["status"] = "ACTIVE"
            card["updated_at"] = db.current_utc_iso()
            card["version"] = int(card.get("version", 1)) + 1

    bump_household(hh)
    return success(_hh_view(hh))


@bp.route("/snap/households/<hh_id>/terminate", methods=["POST"])
@require_roles("Caseworker")
def terminate_household(hh_id, **_):
    hh = db.households.get(hh_id)
    if hh is None:
        raise_api("ERR_NOT_FOUND", "Household not found")
    if hh["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_api("ERR_INVALID_STATE", "Household must be ACTIVE or SUSPENDED to terminate")

    body = get_json_body()
    decision_reason = require_nonempty_str(body, "decision_reason")
    _ = decision_reason  # recorded only implicitly via the action

    hh["status"] = "TERMINATED"

    # Cascade: every EBT card -> CANCELLED (from PENDING_ISSUE/ACTIVE/SUSPENDED)
    for card in db.ebt_cards.values():
        if card["household_id"] == hh_id and card["status"] in (
            "PENDING_ISSUE", "ACTIVE", "SUSPENDED",
        ):
            card["status"] = "CANCELLED"
            card["updated_at"] = db.current_utc_iso()
            card["version"] = int(card.get("version", 1)) + 1

    # Cascade: future MonthlyAllotments (benefit_month > current month) -> EXPUNGED
    current_month = db.current_utc_iso()[:7]
    for ma in db.monthly_allotments.values():
        if ma["household_id"] == hh_id and ma["benefit_month"] > current_month:
            if ma["status"] in ("DRAFT", "ISSUED", "ADJUSTED"):
                ma["status"] = "EXPUNGED"
                ma["updated_at"] = db.current_utc_iso()
                ma["version"] = int(ma.get("version", 1)) + 1

    bump_household(hh)
    return success(_hh_view(hh))
