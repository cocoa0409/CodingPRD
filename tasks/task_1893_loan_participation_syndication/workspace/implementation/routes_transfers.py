"""Participation transfers and buyback demands."""
from datetime import timedelta

from flask import Blueprint

import errors
from auth import require_roles, body, req_int, req_enum, req_date, is_int
from domain import get_or_404, paginate, apply_filters, exit_participant
from responses import ok, ok_list
from store import db, new_entity, touch, now_ts, today, parse_date
from calc import (
    facility_participants,
    recompute_shares,
    recompute_committed,
    materialize_facility,
    BUYBACK_PENALTY_BPS,
)
from store import clock_dt

bp = Blueprint("transfers", __name__, url_prefix="/api")

READ_ROLES = ("AgentBank", "Borrower", "ParticipantLender")
BREACH_TYPES = ("MISREPRESENTATION", "SERVICING_BREACH", "DOCUMENTATION_DEFECT")


def pub(ent):
    return {k: v for k, v in ent.items() if not k.startswith("_")}


def _facility_transfer_posture(fac):
    if fac["status"] in ("IN_DEFAULT", "ACCELERATED"):
        raise errors.facility_in_default()
    if fac["status"] in ("CLOSED", "TERMINATED"):
        raise errors.invalid_state("Facility is wound down")


# ---------------------------------------------------------------------------
# participation transfers
# ---------------------------------------------------------------------------

@bp.post("/transfers")
@require_roles("ParticipantLender")
def transfer_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    # request shape: exactly one transferee designator
    t_participant = data.get("transferee_participant_id")
    t_name = data.get("transferee_name")
    if (t_participant is None) == (t_name is None):
        raise errors.transfer_target_ambiguous()
    if t_participant is not None:
        if not isinstance(t_participant, str) or not t_participant.strip():
            raise errors.invalid_request("transferee_participant_id must be a string")
        if db["participants"].get(t_participant) is None:
            raise errors.not_found("transferee_participant_id does not resolve")
    if t_name is not None and (not isinstance(t_name, str) or not t_name.strip()):
        raise errors.invalid_request("transferee_name must be a non-empty string")
    amount = req_int(data, "transfer_amount_cents", minimum=1)
    settle_raw, settle_d = req_date(data, "settlement_date")
    # cross-entity posture (priority 7)
    _facility_transfer_posture(fac)
    # uniqueness (priority 10): no self-transfer
    if t_participant is not None and t_participant == uid:
        raise errors.self_transfer()
    # eligibility (priority 11): transferor COMMITTED/FUNDED on this facility
    transferor = db["participants"].get(uid)
    if (
        transferor is None
        or transferor["facility_id"] != fac["id"]
        or transferor["status"] not in ("COMMITTED", "FUNDED")
    ):
        raise errors.participant_not_eligible("Transferor must be COMMITTED or FUNDED")
    # temporal (priority 12): payment blackout windows, closed [vd-2d, vd+2d]
    for pay in db["payments"].values():
        if pay["facility_id"] != fac["id"] or pay["status"] == "REVERSED":
            continue
        vd = parse_date(pay["value_date"])
        if vd - timedelta(days=2) <= settle_d <= vd + timedelta(days=2):
            raise errors.settlement_in_blackout()
    # fiscal (priority 13): minimum, headroom, stub
    if amount < fac["min_transfer_cents"]:
        raise errors.transfer_below_minimum()
    if amount > transferor["commitment_cents"]:
        raise errors.transfer_exceeds_commitment()
    stub = transferor["commitment_cents"] - amount
    if 0 < stub < fac["min_transfer_cents"]:
        raise errors.transfer_stub_below_minimum()
    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "from_participant_id": uid,
            "transferee_participant_id": t_participant,
            "transferee_name": t_name,
            "transferee_resolved_participant_id": None,
            "transfer_amount_cents": amount,
            "settlement_date": settle_raw,
            "status": "PROPOSED",
            "proposed_at": now_ts(),
            "settled_at": None,
        }
    )
    db["transfers"][ent["id"]] = ent
    return ok(pub(ent), 201)


@bp.get("/transfers/<transferId>")
@require_roles(*READ_ROLES)
def transfer_get(uid, role, transferId):
    return ok(pub(get_or_404("transfers", transferId)))


@bp.get("/transfers")
@require_roles(*READ_ROLES)
def transfer_list(uid, role):
    items = apply_filters(
        list(db["transfers"].values()),
        [
            ("facility_id", "facility_id"),
            ("from_participant_id", "from_participant_id"),
            ("transferee_participant_id", "transferee_participant_id"),
            ("transferee_resolved_participant_id", "transferee_resolved_participant_id"),
            ("status", "status"),
        ],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/transfers/<transferId>/approve")
@require_roles("AgentBank")
def transfer_approve(uid, role, transferId):
    t = get_or_404("transfers", transferId)
    if t["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED transfer can be approved")
    fac = db["facilities"][t["facility_id"]]
    _facility_transfer_posture(fac)
    t["status"] = "AGENT_APPROVED"
    touch(t)
    return ok(pub(t))


@bp.post("/transfers/<transferId>/reject")
@require_roles("AgentBank")
def transfer_reject(uid, role, transferId):
    t = get_or_404("transfers", transferId)
    if t["status"] != "PROPOSED":
        raise errors.invalid_state("Only a PROPOSED transfer can be rejected")
    t["status"] = "REJECTED"
    touch(t)
    return ok(pub(t))


@bp.post("/transfers/<transferId>/settle")
@require_roles("AgentBank")
def transfer_settle(uid, role, transferId):
    t = get_or_404("transfers", transferId)
    data = body()
    if "expected_from_participant_version" not in data or not is_int(
        data.get("expected_from_participant_version")
    ):
        raise errors.invalid_request("expected_from_participant_version is required")
    expected = data["expected_from_participant_version"]
    if t["status"] != "AGENT_APPROVED":
        raise errors.invalid_state("Only an AGENT_APPROVED transfer can be settled")
    fac = db["facilities"][t["facility_id"]]
    _facility_transfer_posture(fac)
    transferor = db["participants"].get(t["from_participant_id"])
    if transferor is None:
        raise errors.not_found("Transferor no longer exists")
    # OCC (priority 8)
    if expected != transferor["version"]:
        raise errors.stale_version()
    # re-validated at settle
    if transferor["status"] not in ("COMMITTED", "FUNDED") or t["transfer_amount_cents"] > transferor["commitment_cents"]:
        raise errors.transfer_exceeds_commitment()

    amount = t["transfer_amount_cents"]
    prior_status = transferor["status"]
    transferor["commitment_cents"] -= amount
    touch(transferor)  # OCC anchor: exactly one version increment

    # transferee side
    if t["transferee_participant_id"] is not None:
        target = db["participants"][t["transferee_participant_id"]]
        target["commitment_cents"] += amount
        touch(target)
    else:
        target = new_entity()
        target.update(
            {
                "facility_id": fac["id"],
                "participant_name": t["transferee_name"],
                "commitment_cents": amount,
                "status": prior_status,
                "share_bps": 0,
                "funded_cents": 0,
                "cumulative_interest_cents": 0,
                "cumulative_principal_cents": 0,
            }
        )
        db["participants"][target["id"]] = target
    t["transferee_resolved_participant_id"] = target["id"]

    full_exit = transferor["commitment_cents"] == 0
    if full_exit:
        # transfer conservation: the transferee absorbed the commitment, so
        # the exit removes nothing from the voting bases
        exit_participant(transferor, fac, base_reduction=0)
    else:
        recompute_committed(fac)
        recompute_shares(fac)
    t["status"] = "SETTLED"
    t["settled_at"] = now_ts()
    touch(t)
    return ok(pub(t))


@bp.post("/transfers/<transferId>/cancel")
@require_roles("ParticipantLender")
def transfer_cancel(uid, role, transferId):
    t = get_or_404("transfers", transferId)
    if t["from_participant_id"] != uid:
        raise errors.not_owner("Only the transferor may cancel")
    if t["status"] not in ("PROPOSED", "AGENT_APPROVED"):
        raise errors.invalid_state("Transfer cannot be cancelled from its state")
    t["status"] = "CANCELLED"
    touch(t)
    return ok(pub(t))


# ---------------------------------------------------------------------------
# buyback demands
# ---------------------------------------------------------------------------

@bp.post("/buyback_demands")
@require_roles("ParticipantLender")
def buyback_create(uid, role):
    data = body()
    facility_id = data.get("facility_id")
    if not isinstance(facility_id, str) or not facility_id.strip():
        raise errors.invalid_request("facility_id is required")
    fac = db["facilities"].get(facility_id)
    if fac is None:
        raise errors.not_found("facility_id does not resolve")
    breach = req_enum(data, "breach_type", BREACH_TYPES)
    desc = data.get("breach_description")
    if desc is not None and not isinstance(desc, str):
        raise errors.invalid_request("breach_description must be a string")
    # posture (priority 7)
    if fac["status"] not in ("FUNDING", "ACTIVE", "IN_DEFAULT", "ACCELERATED"):
        raise errors.invalid_state("Facility posture does not permit buyback demands")
    # uniqueness (priority 10)
    for d in db["buybacks"].values():
        if (
            d["facility_id"] == fac["id"]
            and d["participant_id"] == uid
            and d["status"] in ("DEMANDED", "ACKNOWLEDGED", "DISPUTED")
        ):
            raise errors.buyback_already_pending()
    # eligibility (priority 11)
    p = db["participants"].get(uid)
    if p is None or p["facility_id"] != fac["id"] or p["status"] != "FUNDED":
        raise errors.buyback_not_funded()
    ent = new_entity()
    ent.update(
        {
            "facility_id": fac["id"],
            "participant_id": uid,
            "breach_type": breach,
            "breach_description": desc,
            "demanded_at": now_ts(),
            "status": "DEMANDED",
            "outstanding_share_cents": None,
            "accrued_share_cents": None,
            "penalty_cents": None,
            "repurchase_price_cents": None,
            "settled_at": None,
        }
    )
    db["buybacks"][ent["id"]] = ent
    return ok(pub(ent), 201)


@bp.get("/buyback_demands/<demandId>")
@require_roles(*READ_ROLES)
def buyback_get(uid, role, demandId):
    return ok(pub(get_or_404("buybacks", demandId)))


@bp.get("/buyback_demands")
@require_roles(*READ_ROLES)
def buyback_list(uid, role):
    items = apply_filters(
        list(db["buybacks"].values()),
        [("facility_id", "facility_id"), ("participant_id", "participant_id"), ("status", "status")],
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub(e) for e in page], limit, offset, total)


@bp.post("/buyback_demands/<demandId>/acknowledge")
@require_roles("AgentBank")
def buyback_acknowledge(uid, role, demandId):
    d = get_or_404("buybacks", demandId)
    if d["status"] not in ("DEMANDED", "DISPUTED"):
        raise errors.invalid_state("Demand cannot be acknowledged from its state")
    d["status"] = "ACKNOWLEDGED"
    touch(d)
    return ok(pub(d))


@bp.post("/buyback_demands/<demandId>/dispute")
@require_roles("AgentBank")
def buyback_dispute(uid, role, demandId):
    d = get_or_404("buybacks", demandId)
    if d["status"] != "DEMANDED":
        raise errors.invalid_state("Only a DEMANDED demand can be disputed")
    d["status"] = "DISPUTED"
    touch(d)
    return ok(pub(d))


@bp.post("/buyback_demands/<demandId>/settle")
@require_roles("AgentBank")
def buyback_settle(uid, role, demandId):
    d = get_or_404("buybacks", demandId)
    if d["status"] != "ACKNOWLEDGED":
        raise errors.invalid_state("Only an ACKNOWLEDGED demand can be settled")
    p = db["participants"].get(d["participant_id"])
    if p is None:
        raise errors.not_found("Participant no longer exists")
    if p["status"] != "FUNDED":
        raise errors.invalid_state("Participant must still be FUNDED at settle")
    fac = db["facilities"][d["facility_id"]]

    # hop 1: materialize accrual to the settle date, then price
    materialize_facility(fac, clock_dt().date())
    outstanding_share = p["funded_cents"] - p["cumulative_principal_cents"]
    accrued_share = (p["share_bps"] * fac["accrued_interest_cents"]) // 10000
    penalty = (
        (outstanding_share * BUYBACK_PENALTY_BPS) // 10000
        if d["breach_type"] == "SERVICING_BREACH"
        else 0
    )
    d["outstanding_share_cents"] = outstanding_share
    d["accrued_share_cents"] = accrued_share
    d["penalty_cents"] = penalty
    d["repurchase_price_cents"] = outstanding_share + accrued_share + penalty
    d["status"] = "SETTLED"
    d["settled_at"] = now_ts()
    touch(d)

    # hop 2+3: exit the participant; the commitment leaves the facility
    # totals (agent retains the position on its own book)
    exit_participant(p, fac, base_reduction=p["commitment_cents"])
    return ok(pub(d))


@bp.post("/buyback_demands/<demandId>/rescind")
@require_roles("ParticipantLender")
def buyback_rescind(uid, role, demandId):
    d = get_or_404("buybacks", demandId)
    if d["participant_id"] != uid:
        raise errors.not_owner("Only the demanding participant may rescind")
    if d["status"] not in ("DEMANDED", "DISPUTED"):
        raise errors.invalid_state("Demand cannot be rescinded from its state")
    d["status"] = "RESCINDED"
    touch(d)
    return ok(pub(d))
