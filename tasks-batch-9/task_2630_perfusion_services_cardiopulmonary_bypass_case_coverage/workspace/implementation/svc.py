"""Shared side-effect helpers: ledgers, recomputations and cascades."""

from datetime import timedelta
from decimal import Decimal

import calc
import constants as C
from errors import ApiError
from store import db, insert, stamp_log, touch

D = Decimal


# -------------------------------------------------------------- lookups

def get_contract(cid):
    row = db.hospital_contracts.get(cid)
    if row is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND")
    return row


def get_surgeon(sid):
    row = db.surgeons.get(sid)
    if row is None:
        raise ApiError("ERR_SURGEON_NOT_FOUND")
    return row


def get_card(cid):
    row = db.preference_cards.get(cid)
    if row is None:
        raise ApiError("ERR_PREFERENCE_CARD_NOT_FOUND")
    return row


def get_perfusionist(pid):
    row = db.perfusionists.get(pid)
    if row is None:
        raise ApiError("ERR_PERFUSIONIST_NOT_FOUND")
    return row


def get_ce_activity(aid):
    row = db.ce_activities.get(aid)
    if row is None:
        raise ApiError("ERR_CE_ACTIVITY_NOT_FOUND")
    return row


def get_device(did):
    row = db.perfusion_devices.get(did)
    if row is None:
        raise ApiError("ERR_DEVICE_NOT_FOUND")
    return row


def get_slot(sid):
    row = db.call_rotation_slots.get(sid)
    if row is None:
        raise ApiError("ERR_ROTATION_SLOT_NOT_FOUND")
    return row


def get_case(cid):
    row = db.bypass_cases.get(cid)
    if row is None:
        raise ApiError("ERR_CASE_NOT_FOUND")
    return row


def get_pack(pid):
    row = db.disposable_packs.get(pid)
    if row is None:
        raise ApiError("ERR_PACK_NOT_FOUND")
    return row


def get_checklist(cid):
    row = db.pump_checklists.get(cid)
    if row is None:
        raise ApiError("ERR_CHECKLIST_NOT_FOUND")
    return row


def get_run(rid):
    row = db.ecmo_runs.get(rid)
    if row is None:
        raise ApiError("ERR_ECMO_RUN_NOT_FOUND")
    return row


def get_incident(iid):
    row = db.incident_reports.get(iid)
    if row is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND")
    return row


# --------------------------------------------------------- child lookups

def case_latest_pack(case_id):
    packs = [p for p in db.disposable_packs.values() if p["case_id"] == case_id]
    if not packs:
        return None
    packs.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return packs[-1]


def case_checklists(case_id):
    rows = [c for c in db.pump_checklists.values() if c["case_id"] == case_id]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    return rows


def case_runs(case_id):
    rows = [r for r in db.ecmo_runs.values() if r["case_id"] == case_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def case_incidents(case_id):
    rows = [i for i in db.incident_reports.values() if i["case_id"] == case_id]
    rows.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return rows


# ---------------------------------------------------------- ledgers

def post_contract_accrual(contract, fee_delta=0, count_delta=0):
    contract["accrued_case_fee_cents"] += int(fee_delta)
    contract["accrued_case_count"] += int(count_delta)
    touch(contract)


def refresh_ce_ledger(perf):
    verified, pending = calc.ce_ledger(perf["id"])
    perf["ce_credits_verified"] = verified
    perf["ce_credits_pending"] = pending
    touch(perf)


def set_readiness(perf, variant, record_variant=False):
    score = calc.perfusionist_readiness_score(perf, variant)
    perf["readiness_score"] = score
    if record_variant:
        perf["readiness_variant_last"] = variant
    touch(perf)
    return score


def recompute_coverage_posture(contract):
    contract["coverage_posture"] = calc.contract_coverage_posture(contract["id"])
    touch(contract)
    return contract["coverage_posture"]


# ------------------------------------------------------ device helpers

def append_event_log(device_id, event_code, recorded_by, detail=None, runtime_hours_delta=0):
    row = stamp_log({
        "device_id": device_id,
        "event_code": event_code,
        "runtime_hours_delta": runtime_hours_delta,
        "recorded_by_user_id": recorded_by,
        "detail": detail,
    })
    return insert("device_event_logs", row)


def release_reserved_device(device):
    """RESERVED -> AVAILABLE when the recomputed reservation count falls to 0."""
    if device["status"] != "RESERVED":
        return False
    if calc.device_open_reservation_count(device["id"]) == 0:
        device["status"] = "AVAILABLE"
        touch(device)
        return True
    return False


def cases_holding_device(device_id, role, statuses):
    out = []
    for case in db.bypass_cases.values():
        if case["bypass_status"] not in statuses:
            continue
        if role == "primary" and case.get("primary_device_id") == device_id:
            out.append(case)
        elif role == "backup" and case.get("backup_device_id") == device_id:
            out.append(case)
        elif role == "either" and (case.get("primary_device_id") == device_id
                                  or case.get("backup_device_id") == device_id):
            out.append(case)
    out.sort(key=lambda c: (c["scheduled_start"], c["created_at"], c["_seq"]))
    return out


def invalidate_checklists(case_id):
    for cl in case_checklists(case_id):
        if cl["status"] in ("DRAFT", "VERIFIED"):
            cl["status"] = "INVALIDATED"
            cl["blood_mgmt_signoff"] = False
            cl["verified_at"] = None
            touch(cl)


# ------------------------------------------------- critical alarm cascade

def critical_alarm_cascade(device):
    """PRD 3.7: four ordered links plus the gentler standby-side variant."""
    affected_statuses = ("PACK_CONFIGURED", "SETUP_VERIFIED")
    primary_cases = cases_holding_device(device["id"], "primary", affected_statuses)
    backup_cases = cases_holding_device(device["id"], "backup", affected_statuses)

    touched_devices = {device["id"]: device}
    touched_contracts = {}

    # Link 2 -- primary-side fallback.
    for case in primary_cases:
        standby_id = case.get("backup_device_id")
        case["bypass_status"] = "STAFFED"
        case["setup_verified_at"] = None
        case["readiness_flag"] = "DEVICE_FALLBACK_REQUIRED"
        case["primary_device_id"] = None
        case["backup_device_id"] = None
        touch(case)
        if standby_id:
            standby = db.perfusion_devices.get(standby_id)
            if standby is not None:
                touched_devices[standby_id] = standby
                if standby["status"] == "RESERVED":
                    standby["status"] = "AVAILABLE"
                    touch(standby)
        # Link 3 -- paperwork.
        invalidate_checklists(case["id"])
        # Link 4 -- money.
        if case["billing_status"] == "PROVISIONAL_ACCRUED":
            amount = case["accrued_fee_cents"]
            case["billing_status"] = "UNBILLED"
            case["accrued_fee_cents"] = 0
            touch(case)
            contract = db.hospital_contracts.get(case["contract_id"])
            if contract is not None:
                post_contract_accrual(contract, fee_delta=-amount, count_delta=-1)
                touched_contracts[contract["id"]] = contract

    # Parallel variant -- standby-side, deliberately gentler.
    for case in backup_cases:
        case["backup_device_id"] = None
        case["readiness_flag"] = "DEVICE_FALLBACK_REQUIRED"
        touch(case)

    return touched_devices, touched_contracts


# ------------------------------------------------- systemic finding cascade

def systemic_cascade(report):
    """PRD 3.9 links 2 through 4."""
    perf_id = report["involved_perfusionist_id"]

    # Link 2 -- credentialing.
    cert = calc.ccp_certification(perf_id)
    if cert is not None and cert["status"] in ("ACTIVE", "PROBATION"):
        if cert["probation_count"] >= 2:
            cert["status"] = "REVOKED"
            touch(cert)
        else:
            cert["status"] = "PROBATION"
            cert["remediation_credits_required"] = C.REMEDIATION_CREDIT_HOURS
            cert["probation_credits_banked"] = D("0.0")
            cert["probation_count"] += 1
            touch(cert)

    # Link 3 -- future primary call is stripped.
    slots = [
        s for s in db.call_rotation_slots.values()
        if s["perfusionist_id"] == perf_id
        and s["slot_type"] == "PRIMARY_CALL"
        and s["status"] == "SCHEDULED"
        and s["window_start"] > db.now()
    ]
    slots.sort(key=lambda s: (s["window_start"], s["created_at"], s["_seq"]))
    contract_ids = []
    for slot in slots:
        slot["status"] = "RELEASED"
        touch(slot)
        if slot["contract_id"] not in contract_ids:
            contract_ids.append(slot["contract_id"])

    # Link 4 -- coverage posture of every contract that lost a slot.
    for cid in contract_ids:
        contract = db.hospital_contracts.get(cid)
        if contract is not None:
            recompute_coverage_posture(contract)


# ------------------------------------------------------- clock advance

def advance_clock(target):
    db.clock = target

    lapsed = 0
    certs = list(db.certifications.values())
    certs.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for cert in certs:
        if cert["status"] in ("ACTIVE", "PROBATION") and cert["expires_on"] <= target:
            cert["status"] = "LAPSED"
            cert["remediation_credits_required"] = D("0.0")
            touch(cert)
            lapsed += 1

    relief = 0
    runs = list(db.ecmo_runs.values())
    runs.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for run in runs:
        if run["status"] == "RUNNING":
            if calc.run_uninterrupted_minutes(run) >= D(C.ECMO_RELIEF_WARN_MINUTES):
                run["status"] = "RELIEF_PENDING"
                touch(run)
                relief += 1

    contracts = list(db.hospital_contracts.values())
    contracts.sort(key=lambda c: (c["created_at"], c["_seq"]))
    for contract in contracts:
        recompute_coverage_posture(contract)

    return lapsed, relief, len(contracts)


# --------------------------------------------------------- misc helpers

def intervals_overlap(a_start, a_end, b_start, b_end):
    """Half-open intersection (PRD 2.5)."""
    return a_start < b_end and b_start < a_end


def turnaround_collides(new_start, new_end, other_start, other_end):
    """Non-strict comparisons against a buffered incumbent (PRD 3.5)."""
    buffer = timedelta(minutes=C.DEVICE_TURNAROUND_MINUTES)
    return new_start <= other_end + buffer and other_start <= new_end + buffer


def covering_slot_for(case, perfusionist_id):
    candidates = [
        s for s in db.call_rotation_slots.values()
        if s["perfusionist_id"] == perfusionist_id
        and s["contract_id"] == case["contract_id"]
        and s["slot_type"] in ("PRIMARY_CALL", "BACKUP_CALL")
        and s["status"] in C.LIVE_SLOT_STATUSES
        and s["window_start"] <= case["scheduled_start"]
        and case["scheduled_end"] <= s["window_end"]
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda s: (s["window_start"], s["created_at"], s["_seq"]))
    return candidates[0]


def perfusionist_has_breached_run(perfusionist_id, exclude_run_id=None):
    for run in db.ecmo_runs.values():
        if run["id"] == exclude_run_id:
            continue
        if run.get("primary_perfusionist_id") != perfusionist_id:
            continue
        if run["status"] not in ("RUNNING", "RELIEF_PENDING"):
            continue
        if calc.run_staffing_breach(run):
            return True
    return False
