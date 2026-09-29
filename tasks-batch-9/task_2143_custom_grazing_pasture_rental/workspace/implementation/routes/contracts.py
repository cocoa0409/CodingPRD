"""Grazing contracts: drafting, submission, signature and early removal."""
from flask import Blueprint, request

from common import (authenticate, body_of, opt_int, opt_num, req_dt_str,
                    req_enum, req_int, req_str, whole_days)
from derive import (grazing_window_conflicts, lots_of_contract,
                    pasture_of_contract, recompute_pasture, sorted_records)
from envelope import created, listing, ok, pagination, public, public_list
from errors import ApiError
from store import db, new_record, touch

bp = Blueprint("contracts", __name__)

ALL_ROLES = ("Grazier", "CattleOwner", "RangeConsultant", "PlatformAdmin")

BILLING_MODES = ("PER_HEAD_PER_DAY", "PER_POUND_OF_GAIN")
RESPONSIBILITIES = ("GRAZIER", "OWNER", "SHARED")
DEATH_LOSS_TERMS = ("OWNER_BEARS_ALL", "GRAZIER_SHARE_ABOVE_THRESHOLD")
EARLY_REMOVAL_REASONS = ("DROUGHT", "OWNER_ELECTED", "GRAZIER_ELECTED")


def get_contract(contract_id):
    contract = db.contracts.get(contract_id)
    if contract is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract does not exist.")
    return contract


@bp.post("/grazing/contracts")
def create_contract():
    actor = authenticate(("Grazier",))
    body = body_of()

    # priority 5 — body identifiers resolve
    owner_id = body.get("cattle_owner_id")
    if owner_id is not None and (not isinstance(owner_id, str) or owner_id not in db.cattle_owners):
        raise ApiError("ERR_PARTY_NOT_FOUND", "cattle_owner_id does not resolve.")
    pasture_id = body.get("pasture_id")
    if pasture_id is not None and (not isinstance(pasture_id, str) or pasture_id not in db.pastures):
        raise ApiError("ERR_PASTURE_NOT_FOUND", "pasture_id does not resolve.")

    # priority 7 — body validation
    cattle_owner_id = req_str(body, "cattle_owner_id")
    pasture_id = req_str(body, "pasture_id")
    billing_mode = req_enum(body, "billing_mode", BILLING_MODES)
    rate_cents = req_int(body, "rate_cents", gt=0)
    shrink_pct = opt_num(body, "shrink_pct", 0, minv=0, maxv=10)
    out_shrink_pct = opt_num(body, "out_shrink_pct", 0, minv=0, maxv=10)
    head_count_committed = req_int(body, "head_count_committed", gt=0)
    head_value_cents = req_int(body, "head_value_cents", gt=0)
    start_date = req_dt_str(body, "start_date")
    end_date = req_dt_str(body, "end_date")
    min_days = opt_int(body, "min_days", 60, minv=0)
    treatment_cost_split_pct = opt_int(body, "treatment_cost_split_pct", 0, minv=0, maxv=100)
    water_responsibility = req_enum(body, "water_responsibility", RESPONSIBILITIES)
    fence_responsibility = req_enum(body, "fence_responsibility", RESPONSIBILITIES)
    infrastructure_owner_cap_cents = opt_int(body, "infrastructure_owner_cap_cents", 100000, minv=0)
    death_loss_terms = req_enum(body, "death_loss_terms", DEATH_LOSS_TERMS)
    death_loss_threshold_pct = opt_num(body, "death_loss_threshold_pct", 2.0, minv=0, maxv=100)

    # priority 8 — the acting grazier must own the pasture the contract books
    pasture = db.pastures[pasture_id]
    if pasture["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "The pasture belongs to another grazier.")

    window_days = whole_days(end_date, start_date)

    rec = new_record()
    rec.update({
        "grazier_id": actor.user_id,
        "cattle_owner_id": cattle_owner_id,
        "pasture_id": pasture_id,
        "billing_mode": billing_mode,
        "rate_cents": rate_cents,
        "shrink_pct": shrink_pct,
        "out_shrink_pct": out_shrink_pct,
        "head_count_committed": head_count_committed,
        "head_value_cents": head_value_cents,
        "start_date": start_date,
        "end_date": end_date,
        "min_days": min_days,
        "treatment_cost_split_pct": treatment_cost_split_pct,
        "water_responsibility": water_responsibility,
        "fence_responsibility": fence_responsibility,
        "infrastructure_owner_cap_cents": infrastructure_owner_cap_cents,
        "death_loss_terms": death_loss_terms,
        "death_loss_threshold_pct": death_loss_threshold_pct,
        "signature_ref": None,
        "committed_head_days": head_count_committed * window_days,
        "lifecycle_status": "DRAFT",
        "billing_status": "UNBILLED",
        "early_removal_reason": None,
        "early_removal_effective_date": None,
    })
    db.contracts[rec["id"]] = rec
    return created(public(rec))


@bp.get("/grazing/contracts/<contract_id>")
def read_contract(contract_id):
    authenticate(ALL_ROLES)
    return ok(public(get_contract(contract_id)))


@bp.get("/grazing/contracts")
def list_contracts():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    rows = sorted_records(db.contracts.values())
    for field in ("grazier_id", "cattle_owner_id", "pasture_id", "lifecycle_status", "billing_status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(public_list(rows), limit, offset)


@bp.post("/grazing/contracts/<contract_id>/submit")
def submit_contract(contract_id):
    actor = authenticate(("Grazier",))
    contract = get_contract(contract_id)

    if contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may submit it.")

    if contract["lifecycle_status"] != "DRAFT":
        raise ApiError("ERR_CONTRACT_INVALID_STATE",
                       "Only a DRAFT contract may be submitted.")

    pasture = pasture_of_contract(contract)
    if pasture["operational_status"] != "AVAILABLE":
        raise ApiError("ERR_PASTURE_NOT_AVAILABLE", "The contract's pasture is not AVAILABLE.")

    if pasture["committed_head_days"] + contract["committed_head_days"] > pasture["rated_head_days"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED",
                       "The contract would push the pasture past its rated carrying budget.")

    contract["lifecycle_status"] = "PENDING_SIGNATURE"
    touch(contract)
    recompute_pasture(pasture)
    return ok(public(contract))


@bp.post("/grazing/contracts/<contract_id>/sign")
def sign_contract(contract_id):
    actor = authenticate(("CattleOwner",))
    contract = get_contract(contract_id)
    body = body_of()
    signature_ref = req_str(body, "signature_ref")

    if contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the named cattle owner may sign.")

    if contract["lifecycle_status"] != "PENDING_SIGNATURE":
        raise ApiError("ERR_CONTRACT_INVALID_STATE",
                       "Only a PENDING_SIGNATURE contract may be signed.")

    if grazing_window_conflicts(contract):
        raise ApiError("ERR_GRAZING_WINDOW_OVERLAP",
                       "The grazing window conflicts with a live contract on the pasture.")

    owner = db.cattle_owners[contract["cattle_owner_id"]]
    if owner["credit_status"] != "GOOD_STANDING":
        raise ApiError("ERR_OWNER_DELINQUENT", "The cattle owner is not in good credit standing.")

    contract["signature_ref"] = signature_ref
    contract["lifecycle_status"] = "ACTIVE"
    touch(contract)
    recompute_pasture(pasture_of_contract(contract))
    return ok(public(contract))


@bp.post("/grazing/contracts/<contract_id>/early-removal")
def early_removal(contract_id):
    actor = authenticate(("Grazier", "CattleOwner"))
    contract = get_contract(contract_id)
    body = body_of()
    reason = req_enum(body, "reason", EARLY_REMOVAL_REASONS)
    effective_date = req_dt_str(body, "effective_date")

    if actor.is_grazier and contract["grazier_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's grazier may act here.")
    if actor.is_owner and contract["cattle_owner_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Only the contract's cattle owner may act here.")

    if contract["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_CONTRACT_INVALID_STATE",
                       "Early removal is only declared from ACTIVE.")

    lots = lots_of_contract(contract["id"])

    # priority 19 — the owner-elected minimum stay
    if reason == "OWNER_ELECTED":
        for lot in lots:
            if not lot.get("in_date"):
                continue
            if whole_days(effective_date, lot["in_date"]) < contract["min_days"]:
                raise ApiError("ERR_MIN_DAYS_NOT_MET",
                               "The removal falls short of the contract's minimum days on feed.")

    # priority 20 — the reason must match the acting role
    if actor.is_owner and reason != "OWNER_ELECTED":
        raise ApiError("ERR_EARLY_REMOVAL_NOT_PERMITTED",
                       "A CattleOwner may only elect OWNER_ELECTED.")
    if actor.is_grazier and reason != "GRAZIER_ELECTED":
        raise ApiError("ERR_EARLY_REMOVAL_NOT_PERMITTED",
                       "A Grazier may only elect GRAZIER_ELECTED.")

    on_ground = [l for l in lots if l["status"] in ("ON_FEED", "REMOVAL_SCHEDULED")]
    any_settleable = [l for l in lots if l["status"] in ("ON_FEED", "REMOVAL_SCHEDULED", "WEIGHED_OUT")]

    if on_ground:
        contract["lifecycle_status"] = "EARLY_REMOVAL_PENDING"
        contract["early_removal_reason"] = reason
        contract["early_removal_effective_date"] = effective_date
        touch(contract)
        for lot in lots:
            if lot["status"] == "ON_FEED":
                lot["status"] = "REMOVAL_SCHEDULED"
                lot["scheduled_removal_date"] = effective_date
                touch(lot)
        recompute_pasture(pasture_of_contract(contract))
    elif not any_settleable:
        contract["lifecycle_status"] = "TERMINATED"
        contract["early_removal_reason"] = reason
        contract["early_removal_effective_date"] = effective_date
        touch(contract)
        recompute_pasture(pasture_of_contract(contract))
    else:
        raise ApiError("ERR_CONTRACT_INVALID_STATE",
                       "The contract's lots do not permit an early removal.")

    return ok(public(contract))
