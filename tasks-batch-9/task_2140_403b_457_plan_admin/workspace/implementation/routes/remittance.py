"""Remittance batches and lost-earnings corrections."""
from flask import Blueprint, g, request

import auth
import calc
import derive
import envelope
import serialize
import store
import validate as V
from auth import endpoint
from errors import ApiError

bp = Blueprint("remittance", __name__)


def _parse_line_items(body):
    if "line_items" not in body or body["line_items"] is None:
        raise V.bad("Missing required field 'line_items'.")
    raw = body["line_items"]
    if not isinstance(raw, list) or len(raw) < 1:
        raise V.bad("Field 'line_items' must be a non-empty array.")
    items = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise V.bad("Each element of 'line_items' must be an object.")
        items.append({
            "vendor_account_id": V.req_str(entry, "vendor_account_id"),
            "elective_deferral_cents": V.req_int(entry, "elective_deferral_cents", minimum=0),
            "employer_contribution_cents": V.req_int(entry, "employer_contribution_cents",
                                                     minimum=0),
        })
    return items


@bp.post("/plan-admin/remittance-batches")
@endpoint(["PlanSponsorAdmin"])
def create_batch():
    body = V.body_of(request)
    plan_id = V.req_str(body, "plan_id")
    pay_period_start = V.req_date(body, "pay_period_start")
    pay_period_end = V.req_date(body, "pay_period_end")
    if pay_period_end <= pay_period_start:
        raise V.bad("pay_period_end must fall strictly after pay_period_start.")
    withholding_date = V.req_date(body, "withholding_date")
    total = V.req_int(body, "total_elective_deferral_cents", minimum=0)
    line_items = _parse_line_items(body)
    segregation = V.opt_date(body, "segregation_feasible_date")

    plan = auth.plan(plan_id)                                # rung 5
    for item in line_items:
        auth.vendor_account(item["vendor_account_id"])       # rung 5
    auth.own_plan(plan)                                      # rung 6
    if plan["status"] not in ("ACTIVE", "FROZEN"):           # rung 10
        raise ApiError("ERR_PLAN_NOT_ACTIVE", "The governing plan is %s." % plan["status"])
    if plan["status"] == "FROZEN":                           # rung 11
        raise ApiError("ERR_PLAN_FROZEN",
                       "No remittance batch may be created against a frozen plan.")
    if withholding_date > store.today():                     # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "withholding_date is in the future.")
    for other in store.rows(store.remittance_batches):       # rung 30
        if other["plan_id"] != plan_id or other["deposit_state"] == "REVERSED":
            continue
        other_start = calc.parse_iso_date(other["pay_period_start"])
        other_end = calc.parse_iso_date(other["pay_period_end"])
        if pay_period_start < other_end and other_start < pay_period_end:
            raise ApiError("ERR_REMITTANCE_PERIOD_OVERLAP",
                           "The pay period intersects an existing batch for this plan.")
    if total != sum(item["elective_deferral_cents"] for item in line_items):   # rung 33
        raise ApiError("ERR_REMITTANCE_TOTAL_MISMATCH",
                       "total_elective_deferral_cents does not equal the sum of the lines.")

    row = store.common_fields()
    row.update({
        "plan_id": plan_id,
        "pay_period_start": pay_period_start.isoformat(),
        "pay_period_end": pay_period_end.isoformat(),
        "withholding_date": withholding_date.isoformat(),
        "total_elective_deferral_cents": total,
        "line_items": line_items,
        "segregation_feasible_date": V.date_str(segregation),
        "deposit_state": "WITHHELD",
        "compliance_state": "UNDETERMINED",
        "deposit_date": None,
        "deadline_date": None,
        "calendar_days_late": 0,
        "business_days_late": 0,
    })
    store.remittance_batches[row["id"]] = row
    return envelope.created(serialize.batch(row))


@bp.get("/plan-admin/remittance-batches/<row_id>")
@endpoint(auth.ALL_ROLES)
def get_batch(row_id):
    return envelope.ok(serialize.batch(auth.batch(row_id)))


@bp.get("/plan-admin/remittance-batches")
@endpoint(auth.ALL_ROLES)
def list_batches():
    args = request.args
    limit, offset = V.pagination(args)
    plan_id = args.get("plan_id")
    deposit_state = V.query_enum(args, "deposit_state", calc.DEPOSIT_STATES)
    compliance_state = V.query_enum(args, "compliance_state", calc.COMPLIANCE_STATES)
    items = store.rows(store.remittance_batches)
    if plan_id:
        items = [b for b in items if b["plan_id"] == plan_id]
    if deposit_state:
        items = [b for b in items if b["deposit_state"] == deposit_state]
    if compliance_state:
        items = [b for b in items if b["compliance_state"] == compliance_state]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.batch(b) for b in page], limit, offset, total)


@bp.post("/plan-admin/remittance-batches/<row_id>/deposit")
@endpoint(["PlanSponsorAdmin"])
def deposit_batch(row_id):
    body = V.body_of(request)
    deposit_date = V.req_date(body, "deposit_date")
    batch = auth.batch(row_id)                               # rung 4
    plan = store.plans.get(batch["plan_id"])
    auth.own_plan(plan)                                      # rung 6
    if batch["deposit_state"] == "DEPOSITED":                # rung 13
        raise ApiError("ERR_REMITTANCE_ALREADY_DEPOSITED",
                       "The batch has already been deposited.")
    if deposit_date > store.today():                         # rung 29
        raise ApiError("ERR_DATE_IN_FUTURE", "deposit_date is in the future.")
    if batch["deposit_state"] == "WITHHELD":
        if deposit_date < calc.parse_iso_date(batch["withholding_date"]):
            raise V.bad("deposit_date must fall on or after withholding_date.")

    batch["deposit_state"] = "DEPOSITED"
    batch["deposit_date"] = deposit_date.isoformat()
    deadline = calc.remittance_deadline(batch, plan)
    batch["deadline_date"] = deadline.isoformat()

    participants = set()
    for item in batch["line_items"]:
        va = store.vendor_accounts.get(item["vendor_account_id"])
        if va is None:
            continue
        va["ytd_elective_deferrals_cents"] += item["elective_deferral_cents"]
        va["ytd_employer_contributions_cents"] += item["employer_contribution_cents"]
        store.touch(va)
        participants.add(va["participant_id"])

    timely = deposit_date <= deadline
    if timely:
        batch["compliance_state"] = "TIMELY"
        batch["calendar_days_late"] = 0
        batch["business_days_late"] = 0
    else:
        batch["compliance_state"] = "LATE"
        batch["calendar_days_late"] = (deposit_date - deadline).days
        batch["business_days_late"] = calc.count_business_days(deadline, deposit_date)
    store.touch(batch)

    if not timely:
        breakdown, lost_total = calc.lost_earnings_correction(batch)
        correction = store.common_fields()
        correction.update({
            "remittance_batch_id": batch["id"],
            "lost_earnings_total_cents": lost_total,
            "excise_tax_cents": calc.excise_tax_on_late_deposit(lost_total),
            "line_breakdown": breakdown,
            "state": "OPEN",
            "settlement_reference": None,
            "settled_at": None,
            "settled_by_user_id": None,
        })
        store.remittance_corrections[correction["id"]] = correction
        for line in breakdown:
            va = store.vendor_accounts.get(line["vendor_account_id"])
            if va is not None:
                va["pending_lost_earnings_cents"] += line["lost_earnings_cents"]
                store.touch(va)
                participants.add(va["participant_id"])
        batch["compliance_state"] = "CORRECTION_PENDING"
        store.touch(batch)
        derive.recompute_plan_corrections(plan)

    for pid in participants:
        participant = store.participants.get(pid)
        if participant:
            derive.recompute_participant(participant, bump=True)
    derive.recompute_plan_excess(plan)
    return envelope.ok(serialize.batch(batch))


@bp.post("/plan-admin/remittance-batches/<row_id>/reverse")
@endpoint(["PlanSponsorAdmin"])
def reverse_batch(row_id):
    body = V.body_of(request)
    V.req_str(body, "reason")
    batch = auth.batch(row_id)                               # rung 4
    plan = store.plans.get(batch["plan_id"])
    auth.own_plan(plan)                                      # rung 6
    if batch["deposit_state"] != "DEPOSITED":                # rung 9
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "Only a DEPOSITED batch may be reversed.")
    for corr in store.corrections_of(batch["id"]):
        if corr["state"] == "SETTLED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A batch with a settled correction cannot be reversed.")

    participants = set()
    for item in batch["line_items"]:
        va = store.vendor_accounts.get(item["vendor_account_id"])
        if va is None:
            continue
        va["ytd_elective_deferrals_cents"] -= item["elective_deferral_cents"]
        va["ytd_employer_contributions_cents"] -= item["employer_contribution_cents"]
        store.touch(va)
        participants.add(va["participant_id"])

    for corr in store.corrections_of(batch["id"]):
        if corr["state"] != "OPEN":
            continue
        for line in corr["line_breakdown"]:
            va = store.vendor_accounts.get(line["vendor_account_id"])
            if va is not None:
                va["pending_lost_earnings_cents"] -= line["lost_earnings_cents"]
                store.touch(va)
                participants.add(va["participant_id"])
        corr["state"] = "VOIDED"
        store.touch(corr)

    batch["deposit_state"] = "REVERSED"
    batch["compliance_state"] = "UNDETERMINED"
    batch["deposit_date"] = None
    batch["calendar_days_late"] = 0
    batch["business_days_late"] = 0
    store.touch(batch)

    derive.recompute_plan_corrections(plan)
    for pid in participants:
        participant = store.participants.get(pid)
        if participant:
            derive.recompute_participant(participant, bump=True)
    derive.recompute_plan_excess(plan)
    return envelope.ok(serialize.batch(batch))


@bp.get("/plan-admin/remittance-batches/<row_id>/corrections")
@endpoint(auth.ALL_ROLES)
def list_corrections(row_id):
    args = request.args
    limit, offset = V.pagination(args)
    state = V.query_enum(args, "state", calc.CORRECTION_STATES)
    auth.batch(row_id)
    items = store.corrections_of(row_id)
    if state:
        items = [c for c in items if c["state"] == state]
    page, total = envelope.paginate(items, limit, offset)
    return envelope.listing([serialize.correction(c) for c in page], limit, offset, total)


@bp.post("/plan-admin/remittance-batches/<row_id>/corrections/<correction_id>/settle")
@endpoint(["ComplianceOfficer"])
def settle_correction(row_id, correction_id):
    body = V.body_of(request)
    reference = V.req_str(body, "settlement_reference")
    batch = auth.batch(row_id)                               # rung 4 (left to right)
    correction = auth.correction(correction_id)
    if correction["remittance_batch_id"] != batch["id"]:
        raise ApiError("ERR_CORRECTION_NOT_FOUND",
                       "No correction with that id under the addressed batch.")
    if correction["state"] != "OPEN":                        # rung 14
        raise ApiError("ERR_CORRECTION_NOT_SETTLEABLE",
                       "Only an OPEN correction may be settled.")

    participants = set()
    for line in correction["line_breakdown"]:
        va = store.vendor_accounts.get(line["vendor_account_id"])
        if va is not None:
            va["pending_lost_earnings_cents"] -= line["lost_earnings_cents"]
            store.touch(va)
            participants.add(va["participant_id"])
    correction["state"] = "SETTLED"
    correction["settlement_reference"] = reference
    correction["settled_at"] = store.now_ts()
    correction["settled_by_user_id"] = g.user_id
    store.touch(correction)

    plan = store.plans.get(batch["plan_id"])
    if plan:
        derive.recompute_plan_corrections(plan)
    if batch["compliance_state"] == "CORRECTION_PENDING":
        if not any(c["state"] == "OPEN" for c in store.corrections_of(batch["id"])):
            batch["compliance_state"] = "CORRECTED"
            store.touch(batch)
            if plan:
                derive.recompute_plan_corrections(plan)
    for pid in participants:
        participant = store.participants.get(pid)
        if participant:
            derive.recompute_participant(participant)
    return envelope.ok(serialize.correction(correction))
