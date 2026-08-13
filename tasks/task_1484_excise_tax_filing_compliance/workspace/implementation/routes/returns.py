"""Tax returns (create, submit, withdraw, file, amend, summary) and deposits."""
from flask import Blueprint, request

import errors
from errors import raise_err
from store import DB
from auth import (
    require_roles, ALL_READ_ROLES, body_dict, req_str, req_int, req_str_list,
    new_entity, touch, get_or_404, public, paginate, user_id,
)
from response import success_object, success_list
from utiltime import fmt_dt, now_dt, valid_period_key
import services

bp = Blueprint("returns", __name__)

RETURN_FIELDS = ["registration_id", "jurisdiction_id", "period", "amendment_of_id",
                 "amendment_sequence", "prepared_by_user_id", "filed_by_user_id",
                 "due_date", "filed_at", "event_count", "gross_tax_cents",
                 "exempted_cents", "taxable_tax_cents", "credits_cents",
                 "deposits_applied_cents", "penalty_cents", "net_due_cents",
                 "pinned_rate_snapshot", "filing_status", "settlement_status"]
DEPOSIT_FIELDS = ["registration_id", "jurisdiction_id", "period", "window",
                  "scheduled_amount_cents", "due_date", "paid_amount_cents",
                  "paid_at", "penalty_cents", "applied_amount_cents",
                  "applied_return_id", "status"]


def ser_return(r):
    return public(r, RETURN_FIELDS)


def ser_deposit(d):
    return public(d, DEPOSIT_FIELDS)


# ------------------------------------------------------------------ returns
@bp.post("/returns")
def create_return():
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    registration_id = req_str(body, "registration_id")
    jurisdiction_id = req_str(body, "jurisdiction_id")
    period = req_str(body, "period")
    reg = get_or_404(DB.registrations, registration_id, "Registration")
    jurisdiction = get_or_404(DB.jurisdictions, jurisdiction_id, "Jurisdiction")
    if not valid_period_key(period, jurisdiction["return_frequency"]):
        raise_err(errors.ERR_INVALID_REQUEST,
                  "period must match the jurisdiction's period-key shape")
    if reg["status"] != "ACTIVE":
        raise_err(errors.ERR_REG_NOT_ACTIVE,
                  "Registration must be ACTIVE to create a return")
    for r in DB.returns.values():
        if (r["registration_id"] == registration_id
                and r["jurisdiction_id"] == jurisdiction_id
                and r["period"] == period
                and r["amendment_of_id"] is None
                and r["filing_status"] != "SUPERSEDED"):
            raise_err(errors.ERR_DUPLICATE_RETURN,
                      "A non-SUPERSEDED original return already exists for this period")
    ret = services.create_return_record(registration_id, jurisdiction_id, period)
    services.recompute_rollup(reg["registrant_id"])
    return success_object(ser_return(ret), 201)


@bp.get("/returns/<rid>")
def get_return(rid):
    require_roles(ALL_READ_ROLES)
    ret = get_or_404(DB.returns, rid, "TaxReturn")
    return success_object(ser_return(ret))


@bp.get("/returns")
def list_returns():
    require_roles(ALL_READ_ROLES)
    items = list(DB.returns.values())
    for param in ("registration_id", "jurisdiction_id", "period",
                  "filing_status", "settlement_status", "amendment_of_id"):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    data, limit, offset, total = paginate(items, ser_return)
    return success_list(data, limit, offset, total)


@bp.get("/returns/<rid>/summary")
def return_summary(rid):
    require_roles(ALL_READ_ROLES)
    ret = get_or_404(DB.returns, rid, "TaxReturn")
    return success_object({
        "return_id": ret["id"],
        "period": ret["period"],
        "event_count": ret["event_count"],
        "gross_tax_cents": ret["gross_tax_cents"],
        "exempted_cents": ret["exempted_cents"],
        "taxable_tax_cents": ret["taxable_tax_cents"],
        "credits_cents": ret["credits_cents"],
        "deposits_applied_cents": ret["deposits_applied_cents"],
        "penalty_cents": ret["penalty_cents"],
        "net_due_cents": ret["net_due_cents"],
        "filing_status": ret["filing_status"],
        "settlement_status": ret["settlement_status"],
    })


@bp.post("/returns/<rid>/submit")
def submit_return(rid):
    uid, _role = require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    ret = get_or_404(DB.returns, rid, "TaxReturn")
    if ret["filing_status"] != "DRAFT":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Return with filing_status {ret['filing_status']} cannot be submitted")
    ret["filing_status"] = "SUBMITTED"
    ret["prepared_by_user_id"] = uid
    touch(ret)
    services.recompute_rollup(DB.registrations[ret["registration_id"]]["registrant_id"])
    return success_object(ser_return(ret))


@bp.post("/returns/<rid>/withdraw")
def withdraw_return(rid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body_dict(require=False)
    ret = get_or_404(DB.returns, rid, "TaxReturn")
    if ret["filing_status"] != "SUBMITTED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Return with filing_status {ret['filing_status']} cannot be withdrawn")
    ret["filing_status"] = "DRAFT"
    ret["prepared_by_user_id"] = None
    touch(ret)
    services.recompute_rollup(DB.registrations[ret["registration_id"]]["registrant_id"])
    return success_object(ser_return(ret))


@bp.post("/returns/<rid>/file")
def file_return(rid):
    uid, _role = require_roles(["TaxReviewer", "ComplianceAdmin"])
    body = body_dict()
    expected_version = req_int(body, "expected_return_version")
    ret = get_or_404(DB.returns, rid, "TaxReturn")
    if ret["filing_status"] != "SUBMITTED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Return with filing_status {ret['filing_status']} cannot be filed")
    if expected_version != ret["version"]:
        raise_err(errors.ERR_STALE_VERSION,
                  "expected_return_version does not match the return's current version")
    if ret["prepared_by_user_id"] is not None and uid == ret["prepared_by_user_id"]:
        raise_err(errors.ERR_SOD,
                  "The filer must differ from the preparer (segregation of duties)")

    reg = DB.registrations[ret["registration_id"]]
    registrant = DB.registrants[reg["registrant_id"]]
    ret["filed_by_user_id"] = uid
    services.file_return_settlement(ret, registrant)
    services.pin_rate_snapshot(ret)

    # Included events RATED/ADJUSTED -> RETURNED.
    for e in DB.events.values():
        if e.get("return_id") == ret["id"] and e["status"] in ("RATED", "ADJUSTED"):
            e["status"] = "RETURNED"
            touch(e)

    # Amendment filing supersedes the parent; deposits_applied carried forward
    # (already folded into deposits_applied_cents by the settlement waterfall).
    if ret["amendment_of_id"] is not None:
        parent = DB.returns[ret["amendment_of_id"]]
        if parent["filing_status"] == "FILED":
            parent["filing_status"] = "SUPERSEDED"
            touch(parent)

    services.recompute_rollup(registrant["id"])
    services.recompute_bond_requirement(reg)
    services.refresh_deficiency(reg)
    services.check_registrant_recovery(registrant)
    services.check_registrant_cancellation(registrant)
    return success_object(ser_return(ret))


@bp.post("/returns/<rid>/amend")
def amend_return(rid):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    expected_version = req_int(body, "expected_return_version")
    add_event_ids = body.get("add_event_ids")
    if add_event_ids is not None:
        if not isinstance(add_event_ids, list) or any(not isinstance(x, str) for x in add_event_ids):
            raise_err(errors.ERR_INVALID_REQUEST,
                      "add_event_ids must be an array of TaxableEvent ids")
    parent = get_or_404(DB.returns, rid, "TaxReturn")
    add_events = []
    if add_event_ids:
        for eid in add_event_ids:
            add_events.append(get_or_404(DB.events, eid, "TaxableEvent"))
    if parent["filing_status"] != "FILED":
        raise_err(errors.ERR_INVALID_STATE,
                  f"Return with filing_status {parent['filing_status']} cannot be amended")
    if expected_version != parent["version"]:
        raise_err(errors.ERR_STALE_VERSION,
                  "expected_return_version does not match the return's current version")
    jurisdiction = DB.jurisdictions[parent["jurisdiction_id"]]
    if services.audit_hold_blocks(parent["registration_id"], parent["jurisdiction_id"],
                                  parent["period"], jurisdiction["return_frequency"]):
        raise_err(errors.ERR_AUDIT_HOLD,
                  "An audit records hold covers this period")
    if services.open_amendment_of(parent["id"]) is not None:
        raise_err(errors.ERR_AMENDMENT_ALREADY_OPEN,
                  "An open amendment already exists for this return")
    for e in add_events:
        if e["registration_id"] != parent["registration_id"]:
            raise_err(errors.ERR_CROSS_REGISTRANT,
                      "add_event_ids must reference events of the same registration")

    amendment = services.create_return_record(
        parent["registration_id"], parent["jurisdiction_id"], parent["period"],
        amendment_of=parent["id"], amendment_sequence=parent["amendment_sequence"] + 1)
    # The amendment contains the parent's RETURNED events plus add_event_ids.
    for e in DB.events.values():
        if e.get("return_id") == parent["id"] and e["status"] == "RETURNED":
            e["return_id"] = amendment["id"]
            touch(e)
    for e in add_events:
        e["return_id"] = amendment["id"]
        touch(e)
    services.recompute_return(amendment)
    touch(parent)  # opening an amendment increments the parent version by one
    services.recompute_rollup(DB.registrations[parent["registration_id"]]["registrant_id"])
    return success_object(ser_return(amendment), 201)


# ------------------------------------------------------------------ deposits
@bp.get("/deposits/<did>")
def get_deposit(did):
    require_roles(ALL_READ_ROLES)
    dep = get_or_404(DB.deposits, did, "Deposit")
    return success_object(ser_deposit(dep))


@bp.get("/deposits")
def list_deposits():
    require_roles(ALL_READ_ROLES)
    items = list(DB.deposits.values())
    for param in ("registration_id", "jurisdiction_id", "period", "status",
                  "applied_return_id"):
        v = request.args.get(param)
        if v is not None:
            items = [d for d in items if d.get(param) == v]
    data, limit, offset, total = paginate(
        items, ser_deposit,
        sort_key=lambda d: (d["due_date"], d["created_at"], d["_seq"]))
    return success_list(data, limit, offset, total)


@bp.post("/deposits/<did>/pay")
def pay_deposit(did):
    require_roles(["TaxAnalyst", "ComplianceAdmin"])
    body = body_dict()
    amount = req_int(body, "amount_cents", minimum=1)
    dep = get_or_404(DB.deposits, did, "Deposit")
    if dep["status"] not in ("SCHEDULED", "LATE"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Deposit in status {dep['status']} cannot be paid")
    dep["paid_amount_cents"] = amount
    dep["paid_at"] = fmt_dt(now_dt())
    dep["penalty_cents"] = services.late_deposit_penalty(
        dep["scheduled_amount_cents"], dep["_due_dt"], now_dt())
    dep["status"] = "PAID"
    touch(dep)
    return success_object(ser_deposit(dep))


@bp.post("/deposits/<did>/waive")
def waive_deposit(did):
    require_roles(["ComplianceAdmin"])
    body_dict(require=False)
    dep = get_or_404(DB.deposits, did, "Deposit")
    if dep["status"] not in ("SCHEDULED", "LATE"):
        raise_err(errors.ERR_INVALID_STATE,
                  f"Deposit in status {dep['status']} cannot be waived")
    dep["status"] = "WAIVED"
    touch(dep)
    return success_object(ser_deposit(dep))
