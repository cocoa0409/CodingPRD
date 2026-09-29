"""Bypass cases: scheduling, staffing, cancellation and closure."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import constants as C
import serialize
import svc
import valid as V
from auth import (ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, ROLE_SURGEON, endpoint)
from envelope import ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new, touch

D = Decimal
bp = Blueprint("cases", __name__)

CASE_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST, ROLE_SURGEON)


@bp.post("/bypass-cases")
@endpoint([ROLE_CHIEF, ROLE_CONTRACT_ADMIN])
def schedule_case(actor):
    body = V.payload()
    V.require(body, "contract_id", "surgeon_id", "procedure_type", "scheduled_start",
              "scheduled_end")
    row = {
        "contract_id": V.vstr(body, "contract_id", required=True),
        "surgeon_id": V.vstr(body, "surgeon_id", required=True),
        "assigned_perfusionist_id": None,
        "primary_device_id": None,
        "backup_device_id": None,
        "procedure_type": V.venum(body, "procedure_type", C.PROCEDURE_TYPES, required=True),
        "acuity": V.venum(body, "acuity", C.ACUITIES, default="ELECTIVE"),
        "scheduled_start": V.vdt(body, "scheduled_start", required=True),
        "scheduled_end": V.vdt(body, "scheduled_end", required=True),
        "bypass_status": "SCHEDULED",
        "billing_status": "UNBILLED",
        "bypass_started_at": None,
        "bypass_ended_at": None,
        "pump_time_minutes": None,
        "cross_clamp_minutes": None,
        "lowest_hematocrit_pct": None,
        "adverse_event_count": 0,
        "provisional_fee_cents": None,
        "final_fee_cents": None,
        "accrued_fee_cents": 0,
        "readiness_flag": "NONE",
        "setup_verified_at": None,
        "_covering_slot_id": None,
    }
    contract = svc.get_contract(row["contract_id"])
    surgeon = svc.get_surgeon(row["surgeon_id"])
    if row["procedure_type"] not in C.SPECIALTY_PROCEDURES[surgeon["specialty"]]:
        raise ApiError("ERR_PROCEDURE_SPECIALTY_MISMATCH")
    if surgeon["status"] != "ACTIVE":
        raise ApiError("ERR_SURGEON_NOT_ACTIVE")
    if row["scheduled_end"] <= row["scheduled_start"]:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    if row["scheduled_start"] < db.now():
        raise ApiError("ERR_CASE_START_IN_PAST")
    if row["acuity"] != "EMERGENT" and contract["coverage_posture"] == "UNCOVERED":
        raise ApiError("ERR_CONTRACT_COVERAGE_INSUFFICIENT")

    stamp_new(row)
    insert("bypass_cases", row)
    return ok(serialize.bypass_case(row), 201)


@bp.get("/bypass-cases/<cid>")
@endpoint(CASE_READ)
def read_case(actor, cid):
    return ok(serialize.bypass_case(svc.get_case(cid)))


@bp.get("/bypass-cases")
@endpoint(CASE_READ)
def list_cases(actor):
    limit, offset = V.pagination()
    rows = ordered("bypass_cases")
    for key in ("contract_id", "surgeon_id", "assigned_perfusionist_id", "bypass_status",
                "billing_status", "primary_device_id", "backup_device_id"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.bypass_case(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/bypass-cases/<cid>/assign-perfusionist")
@endpoint([ROLE_CHIEF])
def assign_perfusionist(actor, cid):
    body = V.payload()
    V.require(body, "perfusionist_id", "expected_case_version")
    perfusionist_id = V.vstr(body, "perfusionist_id", required=True)
    expected = V.vint(body, "expected_case_version", required=True)

    case = svc.get_case(cid)
    perf = svc.get_perfusionist(perfusionist_id)

    if expected != case["version"]:
        raise ApiError("ERR_STALE_CASE_VERSION")
    if case["bypass_status"] not in ("SCHEDULED", "STAFFED"):
        raise ApiError("ERR_CASE_NOT_ASSIGNABLE")

    cert = calc.ccp_certification(perfusionist_id)
    if cert is None or cert["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_CERTIFICATION_NOT_CURRENT")
    if perf["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PERFUSIONIST_NOT_ACTIVE")

    score = calc.perfusionist_readiness_score(perf, "ADMISSION")
    if score < C.READINESS_MIN_ADMISSION:
        raise ApiError("ERR_READINESS_BELOW_MINIMUM")

    slot = svc.covering_slot_for(case, perfusionist_id)
    if slot is None:
        raise ApiError("ERR_NO_COVERING_CALL_SLOT")

    prepared = 0
    on_bypass = 0
    for other in db.bypass_cases.values():
        if other["id"] == case["id"]:
            continue
        if other.get("assigned_perfusionist_id") != perfusionist_id:
            continue
        if not svc.intervals_overlap(case["scheduled_start"], case["scheduled_end"],
                                     other["scheduled_start"], other["scheduled_end"]):
            continue
        if other["bypass_status"] in C.CONCURRENT_STAFFED_STATUSES:
            prepared += 1
        elif other["bypass_status"] == "ON_BYPASS":
            on_bypass += 1
    if prepared >= C.MAX_CONCURRENT_STAFFED_CASES or on_bypass > 0:
        raise ApiError("ERR_PERFUSIONIST_CONCURRENT_CASE_LIMIT")

    contract = db.hospital_contracts[case["contract_id"]]
    takes_fresh_slot = case["billing_status"] != "PROVISIONAL_ACCRUED"
    if takes_fresh_slot and contract["accrued_case_count"] >= contract["monthly_case_cap"]:
        raise ApiError("ERR_CONTRACT_CASE_CAP_EXCEEDED")

    # Withdraw the outgoing accrual first so the contract ledger stays conserved.
    fee_delta = 0
    count_delta = 0
    if case["billing_status"] == "PROVISIONAL_ACCRUED":
        fee_delta -= int(case["accrued_fee_cents"])
    else:
        count_delta += 1

    card = calc.select_preference_card(case["surgeon_id"], case["procedure_type"])
    provisional = calc.case_fee_settlement(contract, case, "PROVISIONAL", card)

    case["assigned_perfusionist_id"] = perfusionist_id
    case["bypass_status"] = "STAFFED"
    case["provisional_fee_cents"] = provisional
    case["billing_status"] = "PROVISIONAL_ACCRUED"
    case["accrued_fee_cents"] = provisional
    case["_covering_slot_id"] = slot["id"]
    touch(case)

    fee_delta += provisional
    svc.post_contract_accrual(contract, fee_delta=fee_delta, count_delta=count_delta)

    perf["readiness_score"] = score
    perf["readiness_variant_last"] = "ADMISSION"
    touch(perf)

    return ok(serialize.bypass_case(case))


@bp.post("/bypass-cases/<cid>/cancel")
@endpoint([ROLE_CHIEF])
def cancel_case(actor, cid):
    body = V.payload()
    V.vstr(body, "reason", allow_empty=True)
    case = svc.get_case(cid)
    if case["bypass_status"] not in ("SCHEDULED", "STAFFED", "PACK_CONFIGURED", "SETUP_VERIFIED"):
        raise ApiError("ERR_CASE_NOT_CANCELLABLE")

    contract = db.hospital_contracts.get(case["contract_id"])
    held = []
    for key in ("primary_device_id", "backup_device_id"):
        did = case.get(key)
        if did and did not in held:
            held.append(did)

    case["bypass_status"] = "CANCELLED"
    released_fee = 0
    compensate = case["billing_status"] == "PROVISIONAL_ACCRUED"
    if compensate:
        released_fee = int(case["accrued_fee_cents"])
        case["billing_status"] = "UNBILLED"
        case["accrued_fee_cents"] = 0
    case["readiness_flag"] = "NONE"
    case["setup_verified_at"] = None
    touch(case)

    for did in held:
        device = db.perfusion_devices.get(did)
        if device is not None:
            svc.release_reserved_device(device)

    svc.invalidate_checklists(case["id"])

    if contract is not None:
        if compensate:
            svc.post_contract_accrual(contract, fee_delta=-released_fee, count_delta=-1)
        else:
            touch(contract)

    return ok(serialize.bypass_case(case))


@bp.post("/bypass-cases/<cid>/close")
@endpoint([ROLE_CHIEF])
def close_case(actor, cid):
    case = svc.get_case(cid)
    if case["bypass_status"] != "OFF_BYPASS":
        raise ApiError("ERR_CASE_NOT_OFF_BYPASS")
    pack = svc.case_latest_pack(cid)
    if pack is not None and pack["approval_status"] not in ("NOT_REQUIRED", "APPROVED"):
        raise ApiError("ERR_PACK_APPROVAL_PENDING")
    for rep in svc.case_incidents(cid):
        if rep["status"] in ("DRAFT", "SUBMITTED", "UNDER_REVIEW", "RETURNED_FOR_INFO"):
            raise ApiError("ERR_INCIDENT_CASE_NOT_COMPLETE")
    for run in svc.case_runs(cid):
        if run["status"] in ("RUNNING", "RELIEF_PENDING"):
            raise ApiError("ERR_INCIDENT_CASE_NOT_COMPLETE")

    contract = db.hospital_contracts[case["contract_id"]]
    final = calc.case_fee_settlement(contract, case, "FINAL")
    delta = final - int(case["accrued_fee_cents"])

    case["bypass_status"] = "CLOSED"
    case["final_fee_cents"] = final
    case["billing_status"] = "FINAL_ACCRUED"
    case["accrued_fee_cents"] = final
    touch(case)

    svc.post_contract_accrual(contract, fee_delta=delta, count_delta=0)

    perf = db.perfusionists.get(case.get("assigned_perfusionist_id"))
    if perf is not None:
        perf["career_case_count"] += 1
        svc.set_readiness(perf, "ADMISSION")

    return ok(serialize.bypass_case(case))
