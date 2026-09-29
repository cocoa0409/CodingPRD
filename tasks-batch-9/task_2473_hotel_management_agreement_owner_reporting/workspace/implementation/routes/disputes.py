"""Brand standard cost disputes with the franchisor."""

from flask import Blueprint

import validate as v
from auth import READ_ROLES, authenticate
from db import by_seq, new_row, serialize, store, touch
from errors import ApiError
from response import ok
from routes.common import paged
from services import core
from timeutil import add_days_iso, cmp_iso

bp = Blueprint("disputes", __name__)

ROUND_ACTIONS = (
    "MANAGER_RESPONSE",
    "OWNER_COUNTER",
    "ESCALATE_TO_FRANCHISOR",
    "RESOLVE_OWNER_FUNDS",
    "RESOLVE_WAIVED",
    "RESCIND_RESOLUTION",
)
ACTION_ROLES = {
    "MANAGER_RESPONSE": ("HotelManagerOps",),
    "OWNER_COUNTER": ("AssetManager", "OwnerRep"),
    "ESCALATE_TO_FRANCHISOR": ("HotelManagerOps",),
    "RESOLVE_OWNER_FUNDS": ("OwnerRep",),
    "RESOLVE_WAIVED": ("OwnerRep",),
    "RESCIND_RESOLUTION": ("OwnerRep",),
}
ACTION_ORIGINS = {
    "MANAGER_RESPONSE": ("OPENED", "OWNER_COUNTERED"),
    "OWNER_COUNTER": ("MANAGER_RESPONDED",),
    "ESCALATE_TO_FRANCHISOR": ("OWNER_COUNTERED",),
    "RESOLVE_OWNER_FUNDS": ("MANAGER_RESPONDED", "OWNER_COUNTERED"),
    "RESOLVE_WAIVED": ("MANAGER_RESPONDED", "OWNER_COUNTERED"),
    "RESCIND_RESOLUTION": ("RESOLVED_OWNER_FUNDS",),
}
FUNDING_SOURCES = ("FFE_RESERVE", "OWNER_CONTRIBUTION")
ESTIMATE_ACTIONS = ("MANAGER_RESPONSE", "OWNER_COUNTER")


def _overlaps(start_a, end_a, start_b, end_b):
    """Both windows are half-open: overlap iff a < d and c < b."""
    if None in (start_a, end_a, start_b, end_b):
        return False
    return cmp_iso(start_a, end_b) < 0 and cmp_iso(start_b, end_a) < 0


# ---------------------------------------------------------------------------
# POST /hotel-management/agreements/{id}/brand-disputes
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/agreements/<agreement_id>/brand-disputes")
def open_dispute(agreement_id):
    authenticate(["AssetManager"])
    body = v.body()
    requirement_ref = v.req_str(body, "franchise_requirement_ref")
    estimated_cost_cents = v.req_int(body, "estimated_cost_cents", gt=0)
    start = v.req_datetime(body, "remediation_start_utc")
    deadline = v.req_datetime(body, "remediation_deadline_utc")
    if cmp_iso(deadline, start) <= 0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "remediation_deadline_utc must be strictly after remediation_start_utc.",
        )

    agreement = core.find_agreement(agreement_id)
    core.require_active(agreement)

    # rule 35 -- only a live franchisor standstill on the same requirement conflicts
    for other in by_seq(
        [d for d in store.brand_disputes.values() if d["agreement_id"] == agreement["id"]]
    ):
        if other["status"] != "ESCALATED_TO_FRANCHISOR":
            continue
        if other["franchise_requirement_ref"] != requirement_ref:
            continue
        if _overlaps(start, deadline, other["standstill_start_utc"], other["standstill_end_utc"]):
            raise ApiError("ERR_DISPUTE_WINDOW_CONFLICT")

    dispute = new_row(
        {
            "agreement_id": agreement["id"],
            "franchise_requirement_ref": requirement_ref,
            "estimated_cost_cents": estimated_cost_cents,
            "remediation_start_utc": start,
            "remediation_deadline_utc": deadline,
            "status": "OPENED",
            "round": 0,
            "current_cost_estimate_cents": estimated_cost_cents,
            "standstill_start_utc": None,
            "standstill_end_utc": None,
            "funding_source": None,
            "funded_amount_cents": 0,
        }
    )
    store.brand_disputes[dispute["id"]] = dispute
    return ok(serialize(dispute), 201)


@bp.get("/hotel-management/agreements/<agreement_id>/brand-disputes")
def list_disputes(agreement_id):
    authenticate(READ_ROLES)
    agreement = core.find_agreement(agreement_id)
    rows = by_seq(
        [d for d in store.brand_disputes.values() if d["agreement_id"] == agreement["id"]]
    )
    status = v.query_str("status")
    requirement_ref = v.query_str("franchise_requirement_ref")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if requirement_ref is not None:
        rows = [r for r in rows if r["franchise_requirement_ref"] == requirement_ref]
    return paged(rows)


# ---------------------------------------------------------------------------
# POST /hotel-management/brand-disputes/{id}/rounds
# ---------------------------------------------------------------------------

@bp.post("/hotel-management/brand-disputes/<dispute_id>/rounds")
def post_round(dispute_id):
    _user_id, role = authenticate(["HotelManagerOps", "AssetManager", "OwnerRep"])
    body = v.body()
    action = v.req_str(body, "action")
    if action in ESTIMATE_ACTIONS:
        v.req_int(body, "cost_estimate_cents", gt=0)
    if action == "RESOLVE_OWNER_FUNDS":
        funding_source = v.req_str(body, "funding_source")
    else:
        funding_source = None
    v.opt_str(body, "note")
    v.check_enum(action, ROUND_ACTIONS, "action")
    if funding_source is not None:
        v.check_enum(funding_source, FUNDING_SOURCES, "funding_source")

    dispute = core.find_dispute(dispute_id)
    agreement = core.find_agreement(dispute["agreement_id"])

    if dispute["status"] not in ACTION_ORIGINS[action]:
        raise ApiError("ERR_INVALID_DISPUTE_STATE")
    if action == "ESCALATE_TO_FRANCHISOR" and dispute["round"] < agreement["max_dispute_rounds"]:
        raise ApiError(
            "ERR_INVALID_DISPUTE_STATE",
            "Escalation requires round to have reached the agreement's max_dispute_rounds.",
        )
    if role not in ACTION_ROLES[action]:
        raise ApiError("ERR_ACTION_ROLE_MISMATCH")

    if action == "MANAGER_RESPONSE":
        dispute["current_cost_estimate_cents"] = body["cost_estimate_cents"]
        dispute["status"] = "MANAGER_RESPONDED"
        touch(dispute)
        return ok(serialize(dispute))

    if action == "OWNER_COUNTER":
        dispute["current_cost_estimate_cents"] = body["cost_estimate_cents"]
        dispute["round"] = dispute["round"] + 1
        dispute["status"] = "OWNER_COUNTERED"
        touch(dispute)
        return ok(serialize(dispute))

    if action == "ESCALATE_TO_FRANCHISOR":
        dispute["status"] = "ESCALATED_TO_FRANCHISOR"
        dispute["standstill_start_utc"] = store.now_iso
        dispute["standstill_end_utc"] = add_days_iso(
            store.now_iso, agreement["dispute_standstill_days"]
        )
        touch(dispute)
        return ok(serialize(dispute))

    if action == "RESOLVE_WAIVED":
        dispute["status"] = "RESOLVED_WAIVED"
        touch(dispute)
        return ok(serialize(dispute))

    if action == "RESOLVE_OWNER_FUNDS":
        amount = dispute["current_cost_estimate_cents"]
        if funding_source == "FFE_RESERVE":
            if agreement["ffe_reserve_balance_cents"] < amount:
                raise ApiError("ERR_INSUFFICIENT_RESERVE_BALANCE")
            dispute["status"] = "RESOLVED_OWNER_FUNDS"
            dispute["funding_source"] = funding_source
            dispute["funded_amount_cents"] = amount
            touch(dispute)
            core.append_reserve_entry(
                agreement,
                "DISBURSEMENT",
                -amount,
                "BRAND_DISPUTE_FUNDING",
                "brand standard dispute %s funded from the reserve" % dispute["id"],
            )
        else:
            dispute["status"] = "RESOLVED_OWNER_FUNDS"
            dispute["funding_source"] = funding_source
            dispute["funded_amount_cents"] = amount
            touch(dispute)
            core.create_working_capital_call(
                agreement, amount, "FLOOR_RESTORATION", True
            )
        return ok(serialize(dispute))

    # RESCIND_RESOLUTION
    funded = dispute["funded_amount_cents"]
    drew_on_reserve = dispute["funding_source"] == "FFE_RESERVE"
    dispute["status"] = "OWNER_COUNTERED"
    dispute["funded_amount_cents"] = 0
    dispute["funding_source"] = None
    touch(dispute)
    if drew_on_reserve:
        core.append_reserve_entry(
            agreement,
            "DISBURSEMENT_REVERSAL",
            funded,
            "BRAND_DISPUTE_RESCISSION",
            "rescission of brand standard dispute %s" % dispute["id"],
        )
    return ok(serialize(dispute))
