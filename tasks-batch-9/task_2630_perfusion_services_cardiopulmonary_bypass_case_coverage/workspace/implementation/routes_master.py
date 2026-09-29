"""Hospital contracts, settlement runs, surgeons and preference cards."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import (ROLE_BIOMED, ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST,
                  ROLE_SURGEON, endpoint)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("master", __name__)

READ_ALL = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST, ROLE_SURGEON)


# ----------------------------------------------------- hospital contracts

def _contract_terms(body, existing=None):
    out = {}
    if existing is None or "hospital_name" in body:
        out["hospital_name"] = V.vstr(body, "hospital_name", max_len=160,
                                      required=existing is None)
    if existing is None or "staffing_model" in body:
        out["staffing_model"] = V.venum(body, "staffing_model", C.STAFFING_MODELS,
                                        required=existing is None)
    if existing is None or "per_case_fee_cents" in body:
        out["per_case_fee_cents"] = V.vint(body, "per_case_fee_cents", minimum=1,
                                           required=existing is None)
    if existing is None or "ecmo_hourly_fee_cents" in body:
        out["ecmo_hourly_fee_cents"] = V.vint(body, "ecmo_hourly_fee_cents", minimum=1,
                                              required=existing is None)
    if existing is None or "monthly_case_cap" in body:
        out["monthly_case_cap"] = V.vint(body, "monthly_case_cap", minimum=1,
                                         required=existing is None)
    if existing is None or "monthly_coverage_fee_cents" in body:
        out["monthly_coverage_fee_cents"] = V.vint(body, "monthly_coverage_fee_cents",
                                                   minimum=0, default=0)
    if existing is None or "prolonged_surcharge_pct" in body:
        out["prolonged_surcharge_pct"] = V.vnum(body, "prolonged_surcharge_pct", minimum=0,
                                                maximum=1, max_dp=4, default=D("0.15"))
    if existing is None or "prolonged_pump_threshold_minutes" in body:
        out["prolonged_pump_threshold_minutes"] = V.vint(
            body, "prolonged_pump_threshold_minutes", minimum=30, default=180)
    if existing is None or "disposable_markup_pct" in body:
        out["disposable_markup_pct"] = V.vnum(body, "disposable_markup_pct", minimum=0,
                                              maximum=1, default=D("0.20"))
    if existing is None or "disposable_discount_pct" in body:
        out["disposable_discount_pct"] = V.vnum(body, "disposable_discount_pct", minimum=0,
                                                exclusive_max=1, default=D("0.0"))
    return out


@bp.post("/hospital-contracts")
@endpoint([ROLE_CONTRACT_ADMIN])
def create_contract(actor):
    body = V.payload()
    V.require(body, "hospital_name", "staffing_model", "per_case_fee_cents",
              "ecmo_hourly_fee_cents", "monthly_case_cap")
    row = _contract_terms(body)
    row.update({
        "accrued_case_fee_cents": 0,
        "accrued_case_count": 0,
        "coverage_posture": "UNCOVERED",
        "last_settlement_period": None,
    })
    stamp_new(row)
    insert("hospital_contracts", row)
    return ok(serialize.contract(row), 201)


@bp.get("/hospital-contracts/<cid>")
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_CHIEF])
def read_contract(actor, cid):
    return ok(serialize.contract(svc.get_contract(cid)))


@bp.put("/hospital-contracts/<cid>")
@endpoint([ROLE_CONTRACT_ADMIN])
def update_contract(actor, cid):
    body = V.payload()
    V.require(body, "expected_contract_version")
    expected = V.vint(body, "expected_contract_version")
    contract = db.hospital_contracts.get(cid)
    terms = _contract_terms(body, existing=True)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    if expected != contract["version"]:
        raise ApiError("ERR_STALE_CONTRACT_VERSION")
    contract.update(terms)
    touch(contract)
    return ok(serialize.contract(contract))


def _period_bounds(period):
    year = int(period[0:4])
    month = int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


@bp.post("/hospital-contracts/<cid>/settlement-runs")
@endpoint([ROLE_CONTRACT_ADMIN])
def settlement_run(actor, cid):
    body = V.payload()
    V.require(body, "period")
    period = V.vstr(body, "period")
    contract = svc.get_contract(cid)

    if not V.PERIOD_RE.match(period.strip()):
        raise ApiError("ERR_SETTLEMENT_PERIOD_INVALID")
    period = period.strip()
    start, end = _period_bounds(period)
    if start > db.now():
        raise ApiError("ERR_SETTLEMENT_PERIOD_INVALID")
    last = contract.get("last_settlement_period")
    if last is not None and period <= last:
        raise ApiError("ERR_SETTLEMENT_PERIOD_INVALID")

    cases = [c for c in db.bypass_cases.values() if c["contract_id"] == cid]
    settled = [
        c for c in cases
        if c["billing_status"] == "FINAL_ACCRUED"
        and c.get("bypass_ended_at") is not None
        and start <= c["bypass_ended_at"] < end
    ]
    settled.sort(key=lambda c: (c["created_at"], c["_seq"]))
    case_fee_gross = sum(int(c.get("final_fee_cents") or 0) for c in settled)

    case_ids = set(c["id"] for c in cases)
    ecmo_gross = 0
    for run in db.ecmo_runs.values():
        if run["case_id"] not in case_ids:
            continue
        if run["status"] != "DECANNULATED":
            continue
        closed = run.get("decannulated_at")
        if closed is None or not (start <= closed < end):
            continue
        ecmo_gross += int(run.get("ecmo_fee_cents") or 0)

    if contract["staffing_model"] in ("COVERAGE_PLUS_PER_CASE", "FULL_COVERAGE"):
        coverage_fee = int(contract["monthly_coverage_fee_cents"])
    else:
        coverage_fee = 0

    pre_credit = case_fee_gross + ecmo_gross + coverage_fee
    pct = calc.volume_credit_pct(pre_credit)
    volume_credit = calc.cents(D(pre_credit) * pct)

    systemic = 0
    for rep in db.incident_reports.values():
        if rep["case_id"] not in case_ids:
            continue
        if rep["finding"] != "SYSTEMIC":
            continue
        if start <= rep["updated_at"] < end:
            systemic += 1
    quality_credit = C.QUALITY_CREDIT_PER_SYSTEMIC_CENTS * systemic

    net = pre_credit - volume_credit - quality_credit
    if net < 0:
        net = 0

    for case in settled:
        case["billing_status"] = "INVOICED"
        touch(case)

    contract["last_settlement_period"] = period
    touch(contract)

    return ok({
        "period": period,
        "case_count": len(settled),
        "case_fee_gross_cents": case_fee_gross,
        "ecmo_gross_cents": ecmo_gross,
        "coverage_fee_cents": coverage_fee,
        "pre_credit_gross_cents": pre_credit,
        "volume_credit_pct": calc.num(pct),
        "volume_credit_cents": volume_credit,
        "quality_credit_cents": quality_credit,
        "net_settlement_cents": net,
        "contract_version": contract["version"],
    })


# ------------------------------------------------------------- surgeons

@bp.post("/surgeons")
@endpoint([ROLE_CONTRACT_ADMIN])
def create_surgeon(actor):
    body = V.payload()
    V.require(body, "full_name", "npi_code", "specialty")
    row = {
        "full_name": V.vstr(body, "full_name", max_len=120, required=True),
        "npi_code": V.vstr(body, "npi_code", required=True),
        "specialty": V.venum(body, "specialty", C.SPECIALTIES, required=True),
        "status": V.venum(body, "status", C.SURGEON_STATUSES, default="ACTIVE"),
    }
    for other in db.surgeons.values():
        if other["npi_code"] == row["npi_code"]:
            raise ApiError("ERR_DUPLICATE_CODE")
    stamp_new(row)
    insert("surgeons", row)
    return ok(serialize.surgeon(row), 201)


@bp.get("/surgeons/<sid>")
@endpoint(READ_ALL)
def read_surgeon(actor, sid):
    return ok(serialize.surgeon(svc.get_surgeon(sid)))


# ------------------------------------------------------ preference cards

def _validate_line_items(body):
    items = V.varray(body, "pack_line_items", min_len=1, max_len=12, required=True)
    seen = set()
    out = []
    for entry in items:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_FIELD_VALUE", "pack_line_items entries must be objects.")
        code = V.vstr(entry, "line_code", required=False)
        if code is None:
            raise ApiError("ERR_INVALID_FIELD_VALUE", "pack_line_items entries require line_code.")
        quantity = V.vint(entry, "quantity", minimum=1)
        unit = V.vint(entry, "unit_cost_cents", minimum=1)
        if quantity is None or unit is None:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "pack_line_items entries require quantity and unit_cost_cents.")
        if code in seen:
            raise ApiError("ERR_INVALID_FIELD_VALUE", "pack_line_items line_code values must be unique.")
        seen.add(code)
        out.append({"line_code": code, "quantity": quantity, "unit_cost_cents": unit})
    return out


def _validate_check_codes(body):
    codes = V.varray(body, "required_safety_check_codes", min_len=1, max_len=12, required=True)
    seen = set()
    out = []
    for code in codes:
        if not isinstance(code, str) or code.strip() == "":
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "required_safety_check_codes entries must be non-empty strings.")
        if code in seen:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "required_safety_check_codes entries must be unique.")
        seen.add(code)
        out.append(code)
    return out


@bp.post("/preference-cards")
@endpoint([ROLE_SURGEON, ROLE_CHIEF])
def create_preference_card(actor):
    body = V.payload()
    V.require(body, "surgeon_id", "procedure_type", "standard_pump_minutes", "prime_volume_ml",
              "pack_line_items", "required_safety_check_codes", "blood_management_protocol",
              "min_hematocrit_pct")
    row = {
        "surgeon_id": V.vstr(body, "surgeon_id", required=True),
        "procedure_type": V.venum(body, "procedure_type", C.PROCEDURE_TYPES, required=True),
        "revision": V.vint(body, "revision", minimum=1, default=1),
        "status": "ACTIVE",
        "standard_pump_minutes": V.vint(body, "standard_pump_minutes", minimum=30, required=True),
        "prime_volume_ml": V.vint(body, "prime_volume_ml", minimum=100, required=True),
        "pack_line_items": _validate_line_items(body),
        "required_safety_check_codes": _validate_check_codes(body),
        "blood_management_protocol": V.venum(body, "blood_management_protocol",
                                             C.BLOOD_PROTOCOLS, required=True),
        "min_hematocrit_pct": V.vnum(body, "min_hematocrit_pct", minimum=5, maximum=45,
                                     required=True),
    }
    surgeon = svc.get_surgeon(row["surgeon_id"])
    if actor.role == ROLE_SURGEON and actor.user_id != row["surgeon_id"]:
        raise ApiError("ERR_NOT_CARD_OWNER")
    if row["procedure_type"] not in C.SPECIALTY_PROCEDURES[surgeon["specialty"]]:
        raise ApiError("ERR_PROCEDURE_SPECIALTY_MISMATCH")

    stamp_new(row)
    insert("preference_cards", row)

    superseded = [
        c for c in db.preference_cards.values()
        if c["id"] != row["id"]
        and c["surgeon_id"] == row["surgeon_id"]
        and c["procedure_type"] == row["procedure_type"]
        and c["status"] == "ACTIVE"
        and c["revision"] <= row["revision"]
    ]
    superseded.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for card in superseded:
        card["status"] = "SUPERSEDED"
        touch(card)
    return ok(serialize.preference_card(row), 201)


@bp.get("/preference-cards/<pid>")
@endpoint(READ_ALL)
def read_preference_card(actor, pid):
    return ok(serialize.preference_card(svc.get_card(pid)))


@bp.get("/preference-cards")
@endpoint(READ_ALL)
def list_preference_cards(actor):
    limit, offset = V.pagination()
    rows = ordered("preference_cards")
    surgeon_id = request.args.get("surgeon_id")
    procedure_type = request.args.get("procedure_type")
    status = request.args.get("status")
    if surgeon_id is not None:
        rows = [r for r in rows if r["surgeon_id"] == surgeon_id]
    if procedure_type is not None:
        rows = [r for r in rows if r["procedure_type"] == procedure_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list([serialize.preference_card(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))
