from datetime import timedelta

from flask import Blueprint

import db
from db import LOCK, STORE
from errors import ApiError
from middleware import auth, require_owner
from response import ok_list, ok_object
from services import calc, serialize as ser
from services.resolution import (
    accepted_package_for_case,
    get_case,
    get_judgment,
    jurisdiction_of_case,
    judgment_for_case,
)
from utils import body_json, is_int, pagination, v_bool, v_date, v_enum, v_int

bp = Blueprint("judgments", __name__)


@bp.post("/api/cases/<cid>/judgment")
@auth({"CourtClerk"})
def enter_judgment(cid, _uid, _role):
    with LOCK:
        case = get_case(cid)
        b = body_json()
        possession = v_bool(b, "possession_granted")
        rent = v_int(b, "rent_awarded_cents", min_inclusive=0)
        damages = v_int(b, "damages_cents", min_inclusive=0)
        late_fee = v_int(b, "late_fee_cents", min_inclusive=0)
        court_costs = v_int(b, "court_costs_cents", min_inclusive=0)
        oldest_due = v_date(b, "oldest_unpaid_due_date")
        # state gate
        if case["status"] != "HEARING_CONCLUDED":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Case status does not permit judgment entry"
            )
        # segregation of duties: entering clerk must differ from fee-accepting clerk
        pkg = accepted_package_for_case(cid)
        if pkg is not None and _uid == pkg["accepted_by_clerk_id"]:
            raise ApiError(
                "ERR_SOD_FEE_JUDGMENT",
                409,
                "Judgment-entering clerk equals the fee-accepting clerk",
            )
        # judgment uniqueness
        if judgment_for_case(cid) is not None:
            raise ApiError(
                "ERR_JUDGMENT_EXISTS", 409, "Case already has a Judgment"
            )
        jurisdiction = jurisdiction_of_case(case)
        entered_at = db.now()
        principal = rent + damages
        days_overdue = max(0, (entered_at.date() - oldest_due).days)
        interest = calc.judgment_interest(jurisdiction, principal, days_overdue)
        total = rent + damages + late_fee + court_costs + interest
        appeal_deadline = entered_at + timedelta(days=calc.APPEAL_DAYS[jurisdiction])
        j = db.new_record(
            {
                "case_id": cid,
                "possession_granted": possession,
                "rent_awarded_cents": rent,
                "damages_cents": damages,
                "late_fee_cents": late_fee,
                "court_costs_cents": court_costs,
                "oldest_unpaid_due_date": oldest_due.isoformat(),
                "interest_cents": interest,
                "total_awarded_cents": total,
                "outstanding_balance_cents": total,
                "status": "ENTERED",
                "entered_by_clerk_id": _uid,
                "entered_at": entered_at,
                "appeal_deadline": appeal_deadline,
                "satisfied_at": None,
            }
        )
        # internal waterfall bucket remainders
        j["_remaining"] = {
            "court_costs": court_costs,
            "late_fees": late_fee,
            "damages": damages,
            "interest": interest,
            "rent": rent,
        }
        STORE.judgments[j["id"]] = j
        case["status"] = "JUDGMENT_ENTERED"
        db.bump(case)
        return ok_object(ser.judgment(j), 201)


@bp.get("/api/judgments/<jid>")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def read_judgment(jid, _uid, _role):
    with LOCK:
        return ok_object(ser.judgment(get_judgment(jid)))


@bp.get("/api/cases/<cid>/judgment")
@auth({"Landlord", "CourtClerk", "SheriffDeputy", "PlatformAdmin"})
def read_case_judgment(cid, _uid, _role):
    with LOCK:
        get_case(cid)
        limit, offset = pagination()
        j = judgment_for_case(cid)
        items = [j] if j is not None else []
        page = items[offset : offset + limit]
        return ok_list([ser.judgment(r) for r in page], len(items), limit, offset)


ZERO_ALLOCATION = {"court_costs": 0, "late_fees": 0, "damages": 0, "interest": 0, "rent": 0}


@bp.post("/api/judgments/<jid>/collection-entries")
@auth({"Landlord"})
def create_collection_entry(jid, _uid, _role):
    with LOCK:
        j = get_judgment(jid)
        case = STORE.cases[j["case_id"]]
        require_owner(_uid, case["landlord_id"])
        b = body_json()
        entry_type = v_enum(b, "entry_type", {"PAYMENT", "REVERSAL", "WRITE_OFF"})
        amount = v_int(b, "amount_cents", min_exclusive=0)
        reversal_of_id = b.get("reversal_of_id")
        if entry_type == "REVERSAL":
            if not isinstance(reversal_of_id, str) or reversal_of_id == "":
                raise ApiError(
                    "ERR_VALIDATION", 400, "reversal_of_id is required for REVERSAL"
                )
        else:
            if reversal_of_id is not None:
                raise ApiError(
                    "ERR_VALIDATION",
                    400,
                    "reversal_of_id is only allowed for REVERSAL",
                )
        # referential: reversal target
        target = None
        if entry_type == "REVERSAL":
            target = STORE.collection_entries.get(reversal_of_id)
            if (
                target is None
                or target["judgment_id"] != jid
                or target["entry_type"] != "PAYMENT"
                or target["reversed_by_id"] is not None
            ):
                raise ApiError(
                    "ERR_REVERSAL_TARGET_INVALID",
                    422,
                    "Reversal target missing, not a PAYMENT, cross-judgment, or already reversed",
                )
        # fiscal: outstanding limits / reversal amount equality
        if entry_type in ("PAYMENT", "WRITE_OFF") and amount > j["outstanding_balance_cents"]:
            raise ApiError(
                "ERR_PAYMENT_EXCEEDS_OUTSTANDING",
                422,
                "Amount exceeds outstanding balance",
            )
        if entry_type == "REVERSAL" and amount != target["amount_cents"]:
            raise ApiError(
                "ERR_PAYMENT_EXCEEDS_OUTSTANDING",
                422,
                "REVERSAL amount must equal target payment amount",
            )
        allocation = dict(ZERO_ALLOCATION)
        rem = j["_remaining"]
        if entry_type == "PAYMENT":
            left = amount
            for bucket in calc.WATERFALL_ORDER:
                applied = min(rem[bucket], left)
                rem[bucket] -= applied
                allocation[bucket] = applied
                left -= applied
            j["outstanding_balance_cents"] -= amount
        elif entry_type == "REVERSAL":
            awarded = {
                "court_costs": j["court_costs_cents"],
                "late_fees": j["late_fee_cents"],
                "damages": j["damages_cents"],
                "interest": j["interest_cents"],
                "rent": j["rent_awarded_cents"],
            }
            left = amount
            for bucket in reversed(calc.WATERFALL_ORDER):  # rent first .. court_costs last
                room = awarded[bucket] - rem[bucket]
                credited = min(room, left)
                rem[bucket] += credited
                left -= credited
            j["outstanding_balance_cents"] += amount
        else:  # WRITE_OFF
            j["outstanding_balance_cents"] -= amount
        entry = db.new_ledger(
            {
                "judgment_id": jid,
                "entry_type": entry_type,
                "amount_cents": amount,
                "reversal_of_id": reversal_of_id if entry_type == "REVERSAL" else None,
                "allocation": allocation,
                "resulting_outstanding_cents": j["outstanding_balance_cents"],
                "reversed_by_id": None,
                "recorded_by": _uid,
            }
        )
        STORE.collection_entries[entry["id"]] = entry
        if target is not None:
            target["reversed_by_id"] = entry["id"]
        if j["outstanding_balance_cents"] == 0 and j["status"] in ("ENTERED", "FINAL"):
            j["status"] = "SATISFIED"
            j["satisfied_at"] = db.now()
        db.bump(j)
        return ok_object(ser.collection_entry(entry), 201)


@bp.get("/api/judgments/<jid>/collection-entries")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_collection_entries(jid, _uid, _role):
    with LOCK:
        get_judgment(jid)
        limit, offset = pagination()
        items = [
            e for e in db.sorted_items(STORE.collection_entries) if e["judgment_id"] == jid
        ]
        page = items[offset : offset + limit]
        return ok_list([ser.collection_entry(r) for r in page], len(items), limit, offset)


@bp.get("/api/collection-entries/<eid>")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def read_collection_entry(eid, _uid, _role):
    with LOCK:
        from services.resolution import get_collection_entry

        return ok_object(ser.collection_entry(get_collection_entry(eid)))


@bp.get("/api/collection-entries/<eid>/reversals")
@auth({"Landlord", "CourtClerk", "PlatformAdmin"})
def list_entry_reversals(eid, _uid, _role):
    with LOCK:
        from services.resolution import get_collection_entry

        get_collection_entry(eid)
        limit, offset = pagination()
        items = [
            e
            for e in db.sorted_items(STORE.collection_entries)
            if e["reversal_of_id"] == eid
        ]
        page = items[offset : offset + limit]
        return ok_list([ser.collection_entry(r) for r in page], len(items), limit, offset)


# keep is_int import used (shape checks elsewhere); silence lint
_ = is_int
