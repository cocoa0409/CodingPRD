"""Pledges, pledge installments, and pledge write-offs."""

from flask import Blueprint, request

from core import (
    authenticate, authorize, body_json, check_unknown_fields, req_str, opt_str,
    req_money, req_int, req_enum, parse_dt, now, new_entity, touch,
    success_object, success_list, paginate, ALL_ROLES,
)
from db import store
from errors import (
    fail, ERR_AGREEMENT_NOT_FOUND, ERR_CAMPAIGN_NOT_FOUND, ERR_PLEDGE_NOT_FOUND,
    ERR_RESOURCE_NOT_FOUND, ERR_AGREEMENT_INVALID_STATE, ERR_CAMPAIGN_INVALID_STATE,
    ERR_PLEDGE_TYPE_REQUIRED, ERR_PLEDGE_ALREADY_EXISTS, ERR_OUTSIDE_COUNTING_WINDOW,
    ERR_INSTALLMENT_NOT_REMINDABLE, ERR_REMINDER_LIMIT_EXCEEDED,
    ERR_PLEDGE_NOT_ACTIVE, ERR_WRITE_OFF_EXCEEDS_OUTSTANDING,
    ERR_WRITE_OFF_NOT_PENDING, ERR_SEGREGATION_OF_DUTIES,
)
from services import (
    ser_pledge, ser_installment, ser_write_off, require_prospect_owner,
    generate_installments, pledge_outstanding_cents, open_installments,
    reevaluate_pledge_status, recompute_campaign_totals,
    refresh_prospect_recognition, MAX_REMINDERS,
)

bp = Blueprint("pledges", __name__)


def _get_pledge(pid):
    pledge = store["pledges"].get(pid)
    if pledge is None:
        fail(ERR_PLEDGE_NOT_FOUND, "Pledge not found")
    return pledge


@bp.post("/advancement/pledges")
def create_pledge():
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer"])
    body = body_json()
    check_unknown_fields(body, {"agreement_id", "total_amount_cents", "installment_count",
                                "frequency", "first_due_date", "campaign_id"})
    agreement_id = req_str(body, "agreement_id")
    total_amount_cents = req_money(body, "total_amount_cents")
    installment_count = req_int(body, "installment_count", minimum=1, maximum=120)
    frequency = req_enum(body, "frequency", {"MONTHLY", "QUARTERLY", "ANNUAL"})
    first_due_date = parse_dt(body.get("first_due_date"), "first_due_date")
    campaign_id = opt_str(body, "campaign_id")
    # existence (priority 4)
    agreement = store["agreements"].get(agreement_id)
    if agreement is None:
        fail(ERR_AGREEMENT_NOT_FOUND, "Agreement not found")
    campaign = None
    if campaign_id is not None:
        campaign = store["campaigns"].get(campaign_id)
        if campaign is None:
            fail(ERR_CAMPAIGN_NOT_FOUND, "Campaign not found")
    # ownership (priority 5)
    require_prospect_owner(user_id, agreement["prospect_id"])
    # state (priority 8)
    if agreement["signature_status"] != "EXECUTED":
        fail(ERR_AGREEMENT_INVALID_STATE, "Pledge requires an EXECUTED agreement")
    if campaign is not None and campaign["status"] != "ACTIVE":
        fail(ERR_CAMPAIGN_INVALID_STATE, "Campaign must be ACTIVE for booking")
    # business constraints (priority 11)
    proposal = store["proposals"].get(agreement["proposal_id"])
    if proposal is None or proposal["proposal_type"] != "PLEDGE":
        fail(ERR_PLEDGE_TYPE_REQUIRED, "Pledge requires an agreement whose proposal_type is PLEDGE")
    if any(p["agreement_id"] == agreement_id for p in store["pledges"].values()):
        fail(ERR_PLEDGE_ALREADY_EXISTS, "An agreement supports exactly one pledge")
    # temporal window (priority 12): booking moment inside the inclusive window
    if campaign is not None and not (campaign["counting_start"] <= now() <= campaign["counting_end"]):
        fail(ERR_OUTSIDE_COUNTING_WINDOW, "Pledge booking falls outside the campaign counting window")
    entity = new_entity()
    entity.update({
        "agreement_id": agreement_id,
        "prospect_id": agreement["prospect_id"],
        "fund_id": _fund_id_for_agreement(agreement_id),
        "campaign_id": campaign_id,
        "total_amount_cents": total_amount_cents,
        "installment_count": installment_count,
        "frequency": frequency,
        "first_due_date": first_due_date,
        "status": "ACTIVE",
    })
    store["pledges"][entity["id"]] = entity
    # installment schedule: front-loaded remainder, calendar-pinned due dates
    for row in generate_installments(entity):
        inst = new_entity()
        inst.update(row)
        store["installments"][inst["id"]] = inst
    # campaign face-value total picks up the booking
    if campaign is not None:
        recompute_campaign_totals(campaign)
    prospect = store["prospects"].get(entity["prospect_id"])
    if prospect is not None:
        refresh_prospect_recognition(prospect)
        touch(prospect)
    return success_object(ser_pledge(entity), 201)


def _fund_id_for_agreement(agreement_id):
    fund = next((f for f in store["funds"].values() if f["agreement_id"] == agreement_id), None)
    return fund["id"] if fund is not None else None


@bp.get("/advancement/pledges/<pid>")
def get_pledge(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    return success_object(ser_pledge(_get_pledge(pid)))


@bp.get("/advancement/pledges")
def list_pledges():
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    items = list(store["pledges"].values())
    for param in ("agreement_id", "fund_id", "campaign_id", "prospect_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    page, limit, offset, total = paginate(items)
    return success_list([ser_pledge(p) for p in page], limit, offset, total)


@bp.get("/advancement/pledges/<pid>/installments")
def list_installments(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_pledge(pid)
    items = [i for i in store["installments"].values() if i["pledge_id"] == pid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    page, limit, offset, total = paginate(items, sort_key=lambda i: (i["sequence_number"], i["id"]))
    return success_list([ser_installment(i) for i in page], limit, offset, total)


@bp.post("/advancement/installments/<iid>/remind")
def remind_installment(iid):
    user_id, role = authenticate()
    authorize(role, ["DonorRelationsOfficer"])
    body_json()  # no documented inputs
    inst = store["installments"].get(iid)
    if inst is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Installment not found")
    if inst["status"] not in ("SCHEDULED", "REMINDED", "OVERDUE"):
        fail(ERR_INSTALLMENT_NOT_REMINDABLE, f"Installment in {inst['status']} cannot be reminded")
    if inst["reminder_count"] >= MAX_REMINDERS:
        fail(ERR_REMINDER_LIMIT_EXCEEDED, "Reminder limit reached for this installment")
    inst["reminder_count"] += 1
    inst["status"] = "REMINDED"
    touch(inst)
    return success_object(ser_installment(inst))


@bp.post("/advancement/pledges/<pid>/write-offs")
def create_write_off(pid):
    user_id, role = authenticate()
    authorize(role, ["GiftOfficer", "FinanceSteward"])
    body = body_json()
    check_unknown_fields(body, {"amount_cents", "reason"})
    amount_cents = req_money(body, "amount_cents")
    reason = req_enum(body, "reason", {"UNCOLLECTIBLE", "DONOR_HARDSHIP", "DUPLICATE", "OTHER"})
    pledge = _get_pledge(pid)
    # ownership check applies to the GiftOfficer caller only
    if role == "GiftOfficer":
        require_prospect_owner(user_id, pledge["prospect_id"])
    if pledge["status"] != "ACTIVE":
        fail(ERR_PLEDGE_NOT_ACTIVE, "Write-off requires an ACTIVE pledge")
    if amount_cents > pledge_outstanding_cents(pledge):
        fail(ERR_WRITE_OFF_EXCEEDS_OUTSTANDING, "Write-off amount exceeds the pledge's outstanding balance")
    entity = new_entity()
    entity.update({
        "pledge_id": pid,
        "amount_cents": amount_cents,
        "reason": reason,
        "requested_by": user_id,
        "decided_by": None,
        "status": "PENDING",
    })
    store["write_offs"][entity["id"]] = entity
    return success_object(ser_write_off(entity), 201)


@bp.get("/advancement/pledges/<pid>/write-offs")
def list_write_offs(pid):
    user_id, role = authenticate()
    authorize(role, ALL_ROLES)
    _get_pledge(pid)
    items = [w for w in store["write_offs"].values() if w["pledge_id"] == pid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [w for w in items if w["status"] == status_filter]
    page, limit, offset, total = paginate(items)
    return success_list([ser_write_off(w) for w in page], limit, offset, total)


@bp.post("/advancement/write-offs/<wid>/review")
def review_write_off(wid):
    user_id, role = authenticate()
    authorize(role, ["AdvancementDirector"])
    body = body_json()
    check_unknown_fields(body, {"decision", "review_rationale"})
    decision = req_enum(body, "decision", {"APPROVE", "REJECT"})
    opt_str(body, "review_rationale")
    write_off = store["write_offs"].get(wid)
    if write_off is None:
        fail(ERR_RESOURCE_NOT_FOUND, "Write-off not found")
    # segregation of duties (priority 6) precedes the state precondition (8)
    if user_id == write_off["requested_by"]:
        fail(ERR_SEGREGATION_OF_DUTIES, "Reviewer must differ from the write-off requester")
    if write_off["status"] != "PENDING":
        fail(ERR_WRITE_OFF_NOT_PENDING, "Write-off is not PENDING")
    write_off["decided_by"] = user_id
    if decision == "REJECT":
        write_off["status"] = "REJECTED"
        touch(write_off)
        return success_object(ser_write_off(write_off))
    # APPROVE: allocate latest-first (due_date DESC, sequence_number DESC)
    write_off["status"] = "APPROVED"
    touch(write_off)
    pledge = store["pledges"].get(write_off["pledge_id"])
    remaining = write_off["amount_cents"]
    targets = sorted(
        open_installments(pledge),
        key=lambda i: (i["due_date"], i["sequence_number"]),
        reverse=True,
    )
    for inst in targets:
        if remaining <= 0:
            break
        open_cents = inst["amount_cents"] - inst["paid_cents"] - inst["written_off_cents"]
        applied = min(remaining, open_cents)
        inst["written_off_cents"] += applied
        remaining -= applied
        covered = inst["paid_cents"] + inst["written_off_cents"]
        if covered >= inst["amount_cents"]:
            inst["status"] = "WRITTEN_OFF" if inst["paid_cents"] == 0 else "PAID"
        touch(inst)
    reevaluate_pledge_status(pledge)
    touch(pledge)
    if pledge["campaign_id"] is not None:
        campaign = store["campaigns"].get(pledge["campaign_id"])
        if campaign is not None:
            recompute_campaign_totals(campaign)
    prospect = store["prospects"].get(pledge["prospect_id"])
    if prospect is not None:
        refresh_prospect_recognition(prospect)
        touch(prospect)
    return success_object(ser_write_off(write_off))
