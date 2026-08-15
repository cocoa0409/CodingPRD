"""Draws and funding settlements."""
from datetime import timedelta

from flask import Blueprint

import errors
from auth import require_roles, body, req_int, req_date, is_int
from domain import get_or_404, paginate, apply_filters
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, today
from calc import (
    facility_participants,
    facility_draws,
    split_pool,
    late_funding_penalty,
    FUNDING_WINDOW_DAYS,
    sync_facility_aggregates,
)
from store import parse_date, date_of_ts

bp = Blueprint("funding", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# draws
# ---------------------------------------------------------------------------

@bp.post("/draws")
@require_roles("AgentBank")
def draw_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    # request shape (priority 5)
    amount = req_int(data, "draw_amount_cents", minimum=1)
    start_raw, start_d = req_date(data, "accrual_start_date")
    end_raw, end_d = req_date(data, "accrual_end_date")
    if end_d <= start_d:
        raise errors.invalid_request("accrual_end_date must be after accrual_start_date")
    if "expected_facility_version" not in data or not is_int(data.get("expected_facility_version")):
        raise errors.invalid_request("expected_facility_version is required")
    expected = data["expected_facility_version"]
    # cross-entity posture (priority 7)
    if fac["status"] == "ACCELERATED":
        raise errors.invalid_state("Draws are rejected on an accelerated facility")
    if fac["status"] != "COMMITTED":
        raise errors.facility_not_committed()
    # OCC (priority 8)
    if expected != fac["version"]:
        raise errors.stale_version()
    # overlap (priority 10): half-open windows
    for d in facility_draws(fac["id"]):
        if d["status"] == "CANCELLED":
            continue
        ex_start = parse_date(d["accrual_start_date"])
        ex_end = parse_date(d["accrual_end_date"])
        if start_d < ex_end and ex_start < end_d:
            raise errors.draw_window_overlap()
    # headroom (priority 13)
    used = sum(
        d["draw_amount_cents"] for d in facility_draws(fac["id"]) if d["status"] != "CANCELLED"
    )
    if used + amount > fac["total_commitment_cents"]:
        raise errors.draw_exceeds_commitment()

    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "draw_amount_cents": amount,
            "accrual_start_date": start_raw,
            "accrual_end_date": end_raw,
            "status": "FUNDING",
            "outstanding_cents": 0,
            "accrued_unpaid_interest_cents": 0,
            "accrual_as_of_date": start_raw,
            "settled_at": None,
            "_ledger": [],
            "_net_distributed": 0,
        }
    )
    db["draws"][ent["id"]] = ent

    # one FundingSettlement per COMMITTED participant, dues split by share_bps
    committed = [p for p in facility_participants(fac["id"]) if p["status"] == "COMMITTED"]
    dues = split_pool(amount, committed)
    due_date = (today() + timedelta(days=FUNDING_WINDOW_DAYS)).isoformat()
    for p in committed:
        st = new_entity()
        st.update(
            {
                "draw_id": ent["id"],
                "participant_id": p["id"],
                "facility_id": fac["id"],
                "due_cents": dues[p["id"]],
                "received_cents": 0,
                "funding_due_date": due_date,
                "wired_at": None,
                "status": "PENDING",
                "penalty_interest_cents": 0,
            }
        )
        db["settlements"][st["id"]] = st

    # facility bubble: COMMITTED -> FUNDING (first draw) + version increment
    fac["status"] = "FUNDING"
    touch(fac)
    return ok(pub(ent), 201)


@bp.get("/draws")
@require_roles(*READ_ROLES)
def draw_list(uid, role):
    items = apply_filters(list(db["draws"].values()), [("facility_id", "facility_id"), ("status", "status")])
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.get("/draws/<drawId>")
@require_roles(*READ_ROLES)
def draw_get(uid, role, drawId):
    return ok(pub(get_or_404("draws", drawId)))


@bp.post("/draws/<drawId>/cancel")
@require_roles("AgentBank")
def draw_cancel(uid, role, drawId):
    d = get_or_404("draws", drawId)
    if d["status"] != "FUNDING":
        raise errors.invalid_state("Only a FUNDING draw can be cancelled")
    siblings = [s for s in db["settlements"].values() if s["draw_id"] == d["id"]]
    if any(s["status"] in ("CONFIRMED", "LATE_CONFIRMED") for s in siblings):
        raise errors.draw_has_confirmed_funds()
    for s in siblings:
        if s["status"] in ("PENDING", "WIRED", "DEFAULTED"):
            s["status"] = "VOID"
            touch(s)
    d["status"] = "CANCELLED"
    touch(d)
    fac = db["facilities"][d["facility_id"]]
    live = [x for x in facility_draws(fac["id"]) if x["status"] != "CANCELLED"]
    if not live and fac["status"] == "FUNDING":
        fac["status"] = "COMMITTED"
        touch(fac)
    return ok(pub(d))


# ---------------------------------------------------------------------------
# funding settlements
# ---------------------------------------------------------------------------

@bp.get("/funding_settlements/<settlementId>")
@require_roles(*READ_ROLES)
def settlement_get(uid, role, settlementId):
    return ok(pub(get_or_404("settlements", settlementId)))


@bp.get("/funding_settlements")
@require_roles(*READ_ROLES)
def settlement_list(uid, role):
    items = apply_filters(
        list(db["settlements"].values()),
        [
            ("draw_id", "draw_id"),
            ("participant_id", "participant_id"),
            ("facility_id", "facility_id"),
            ("status", "status"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/funding_settlements/<settlementId>/report_wire")
@require_roles("ParticipantLender")
def settlement_report_wire(uid, role, settlementId):
    s = get_or_404("settlements", settlementId)
    if s["participant_id"] != uid:
        raise errors.not_owner("A participant may only report its own wire")
    data = body()
    amount = req_int(data, "amount_cents", minimum=1)
    if s["status"] not in ("PENDING", "DEFAULTED"):
        raise errors.invalid_state("Settlement cannot be wired from its state")
    s["received_cents"] = amount
    s["wired_at"] = now_ts()
    s["status"] = "WIRED"
    touch(s)
    return ok(pub(s))


@bp.post("/funding_settlements/<settlementId>/confirm")
@require_roles("AgentBank")
def settlement_confirm(uid, role, settlementId):
    s = get_or_404("settlements", settlementId)
    if s["status"] != "WIRED":
        raise errors.invalid_state("Only a WIRED settlement can be confirmed")
    data = body()
    wired_date = date_of_ts(s["wired_at"])
    due_date = parse_date(s["funding_due_date"])
    late = wired_date > due_date
    # pinned order: amount equality first, then penalty equality
    if s["received_cents"] != s["due_cents"]:
        raise errors.funding_amount_mismatch()
    if late:
        days_late = (wired_date - due_date).days
        penalty = late_funding_penalty(s["due_cents"], days_late)
        if data.get("penalty_received_cents") != penalty:
            raise errors.penalty_amount_mismatch()
        s["penalty_interest_cents"] = penalty
        s["status"] = "LATE_CONFIRMED"
    else:
        s["status"] = "CONFIRMED"
    touch(s)

    p = db["participants"][s["participant_id"]]
    p["funded_cents"] += s["due_cents"]
    if p["status"] == "COMMITTED":
        p["status"] = "FUNDED"
    touch(p)

    # draw bubble: settles when every sibling settlement is confirmed
    d = db["draws"][s["draw_id"]]
    siblings = [x for x in db["settlements"].values() if x["draw_id"] == d["id"]]
    if d["status"] == "FUNDING" and all(
        x["status"] in ("CONFIRMED", "LATE_CONFIRMED") for x in siblings
    ):
        d["status"] = "SETTLED"
        d["outstanding_cents"] = d["draw_amount_cents"]
        d["settled_at"] = now_ts()
        touch(d)
        fac = db["facilities"][d["facility_id"]]
        sync_facility_aggregates(fac)
        if fac["status"] == "FUNDING":
            fac["status"] = "ACTIVE"
            touch(fac)
    return ok(pub(s))


@bp.post("/funding_settlements/<settlementId>/mark_defaulted")
@require_roles("AgentBank")
def settlement_mark_defaulted(uid, role, settlementId):
    s = get_or_404("settlements", settlementId)
    if s["status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING settlement can be marked defaulted")
    if today() <= parse_date(s["funding_due_date"]):
        raise errors.funding_not_yet_due()
    s["status"] = "DEFAULTED"
    touch(s)
    return ok(pub(s))
