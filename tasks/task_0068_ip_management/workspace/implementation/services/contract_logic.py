"""Contract + RoyaltySchedule logic."""
from decimal import Decimal

import db
from errors import (APIError, ERR_REFERENCED_ENTITY_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_CONTRACT_STATE,
                    ERR_TEMPLATE_TYPE_MISMATCH, ERR_CONTRACT_FIELDS_FOR_TYPE, ERR_MIN_GUARANTEE_NOT_ALLOWED,
                    ERR_INSUFFICIENT_PARTIES, ERR_IP_NOT_REGISTERED, ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP,
                    ERR_BAD_REQUEST)
from services import audit
from services.common import make_versioned, touch
from utils import round_half_up_cents


VALID_CONTRACT_TYPES = ("TRANSFER", "EXCLUSIVE_LICENSE", "NON_EXCLUSIVE_LICENSE")


def draft_contract(body, actor_role, actor_id):
    from utils import get_str, get_enum, get_int
    ip_right_id = get_str(body, "ip_right_id")
    template_id = get_str(body, "template_id")
    contract_type = get_enum(body, "contract_type", VALID_CONTRACT_TYPES)
    parties = body.get("parties")
    royalty_rate = body.get("royalty_rate")
    min_guarantee = body.get("min_guarantee_cents")
    business_unit_id = get_str(body, "business_unit_id")

    # Priority 4: body-FK existence
    if ip_right_id not in db.ip_rights:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "ip_right_id does not resolve")
    if template_id not in db.contract_templates:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "template_id does not resolve")
    if business_unit_id not in db.business_units:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "business_unit_id does not resolve")

    # Priority 9: template type match
    template = db.contract_templates[template_id]
    if template["contract_type"] != contract_type:
        raise APIError(ERR_TEMPLATE_TYPE_MISMATCH, 422,
                       "template.contract_type does not match contract.contract_type")

    # Priority 10: fields-for-type
    if contract_type in ("EXCLUSIVE_LICENSE", "NON_EXCLUSIVE_LICENSE"):
        if royalty_rate is None:
            raise APIError(ERR_CONTRACT_FIELDS_FOR_TYPE, 422,
                           "royalty_rate required for license types")
    elif contract_type == "TRANSFER":
        if royalty_rate is not None:
            raise APIError(ERR_CONTRACT_FIELDS_FOR_TYPE, 422,
                           "royalty_rate must be null for TRANSFER")
        if min_guarantee is not None:
            raise APIError(ERR_CONTRACT_FIELDS_FOR_TYPE, 422,
                           "min_guarantee_cents must be null for TRANSFER")

    if royalty_rate is not None:
        if not isinstance(royalty_rate, (int, float)) or isinstance(royalty_rate, bool):
            raise APIError(ERR_BAD_REQUEST, 422, "royalty_rate must be numeric")
        if not (0 <= royalty_rate <= 1):
            raise APIError(ERR_BAD_REQUEST, 422, "royalty_rate must be between 0 and 1")

    # Priority 11: min_guarantee_cents only on EXCLUSIVE_LICENSE
    if min_guarantee is not None and contract_type != "EXCLUSIVE_LICENSE":
        raise APIError(ERR_MIN_GUARANTEE_NOT_ALLOWED, 422,
                       "min_guarantee_cents only allowed on EXCLUSIVE_LICENSE")

    # Priority 17: parties — ≥1 entry signature_required=true AND ≥2 unique party_id
    if not isinstance(parties, list) or len(parties) == 0:
        raise APIError(ERR_INSUFFICIENT_PARTIES, 422, "parties must be a non-empty list")
    party_ids = []
    has_required_signer = False
    normalized_parties = []
    for p in parties:
        if not isinstance(p, dict):
            raise APIError(ERR_INSUFFICIENT_PARTIES, 422, "party entries must be objects")
        pid = p.get("party_id")
        if not pid:
            raise APIError(ERR_INSUFFICIENT_PARTIES, 422, "party_id missing")
        sig_required = bool(p.get("signature_required"))
        if sig_required:
            has_required_signer = True
        party_ids.append(pid)
        normalized_parties.append({
            "party_id": pid,
            "role": p.get("role"),
            "signature_required": sig_required,
            "signed_at": p.get("signed_at"),
        })
    if not has_required_signer or len(set(party_ids)) < 2:
        raise APIError(ERR_INSUFFICIENT_PARTIES, 422,
                       "parties needs ≥1 required signer and ≥2 unique party_ids")

    contract = make_versioned({
        "ip_right_id": ip_right_id,
        "template_id": template_id,
        "contract_type": contract_type,
        "parties": normalized_parties,
        "royalty_rate": royalty_rate,
        "min_guarantee_cents": min_guarantee,
        "filed_with_authority": False,
        "status": "DRAFT",
        "business_unit_id": business_unit_id,
    })
    db.contracts[contract["id"]] = contract
    audit.emit("Contract", contract["id"], actor_role, actor_id,
               "CONTRACT_RECORD", from_state=None, to_state="DRAFT",
               payload={"contract_type": contract_type})
    return contract


def start_signing(contract, actor_role, actor_id):
    if contract["status"] != "DRAFT":
        raise APIError(ERR_INVALID_CONTRACT_STATE, 409, "Contract not in DRAFT")
    # all parties signed_at must be null
    for p in contract["parties"]:
        if p.get("signed_at") is not None:
            raise APIError(ERR_INVALID_CONTRACT_STATE, 409, "Some parties already have signatures")
    # template type still valid
    template = db.contract_templates.get(contract["template_id"])
    if not template or template["contract_type"] != contract["contract_type"]:
        raise APIError(ERR_TEMPLATE_TYPE_MISMATCH, 422,
                       "template.contract_type does not match")
    prior = contract["status"]
    contract["status"] = "SIGNING"
    touch(contract)
    audit.emit("Contract", contract["id"], actor_role, actor_id,
               "CONTRACT_RECORD", from_state=prior, to_state="SIGNING")
    return contract


def sign_contract(contract, party_id, actor_role, actor_id):
    if contract["status"] != "SIGNING":
        raise APIError(ERR_INVALID_CONTRACT_STATE, 409, "Contract not in SIGNING")
    match = None
    for p in contract["parties"]:
        if p["party_id"] == party_id:
            match = p
            break
    if match is None:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "party_id does not match contract parties")
    if match["signed_at"] is None:
        match["signed_at"] = db.now_iso()
    # Check if all required signers have signed
    all_signed = all(p["signed_at"] is not None
                     for p in contract["parties"] if p["signature_required"])
    prior = contract["status"]
    if all_signed:
        contract["status"] = "SIGNED"
    touch(contract)
    audit.emit("Contract", contract["id"], actor_role, actor_id,
               "CONTRACT_RECORD", from_state=prior, to_state=contract["status"],
               payload={"party_id": party_id})
    return contract


def file_with_authority(contract, actor_role, actor_id):
    if contract["status"] not in ("SIGNED", "AMENDED"):
        raise APIError(ERR_INVALID_CONTRACT_STATE, 409,
                       f"Contract in {contract['status']} cannot be filed")
    right = db.ip_rights.get(contract["ip_right_id"])
    if not right or right["status"] != "REGISTERED":
        # If TRANSFER and right is TRANSFERRED already, still not REGISTERED → fail
        raise APIError(ERR_IP_NOT_REGISTERED, 422,
                       "Linked IPRight must be REGISTERED to file the contract")
    prior = contract["status"]
    contract["status"] = "FILED"
    contract["filed_with_authority"] = True
    touch(contract)
    audit.emit("Contract", contract["id"], actor_role, actor_id,
               "CONTRACT_RECORD", from_state=prior, to_state="FILED")
    # For TRANSFER, flip the IPRight to TRANSFERRED
    if contract["contract_type"] == "TRANSFER":
        if right["status"] != "TRANSFERRED":
            p = right["status"]
            right["status"] = "TRANSFERRED"
            touch(right)
            audit.emit("IPRight", right["id"], actor_role, actor_id,
                       "STATUS_CHANGE", from_state=p, to_state="TRANSFERRED")
    return contract


def amend_contract(contract, actor_role, actor_id):
    if contract["status"] != "FILED":
        raise APIError(ERR_INVALID_CONTRACT_STATE, 409, "Contract not in FILED")
    snapshot = {
        "contract_type": contract["contract_type"],
        "royalty_rate": contract.get("royalty_rate"),
        "min_guarantee_cents": contract.get("min_guarantee_cents"),
        "parties": [dict(p) for p in contract["parties"]],
        "business_unit_id": contract["business_unit_id"],
        "template_id": contract["template_id"],
    }
    prior = contract["status"]
    contract["status"] = "AMENDED"
    touch(contract)
    audit.emit("Contract", contract["id"], actor_role, actor_id,
               "CONTRACT_RECORD", from_state=prior, to_state="AMENDED",
               payload={"prior": snapshot})
    return contract


def terminate_contract(contract, actor_role, actor_id):
    if contract["status"] not in ("FILED", "AMENDED"):
        raise APIError(ERR_INVALID_CONTRACT_STATE, 409,
                       "Contract not in FILED or AMENDED")
    now = db.now()
    for rs in db.royalty_schedules.values():
        if rs["contract_id"] != contract["id"]:
            continue
        if rs["status"] != "FORECAST":
            continue
        period_end = db.parse_iso(rs["period_end"])
        if period_end and period_end > now:
            raise APIError(ERR_INVALID_CONTRACT_STATE, 409,
                           "Future-period FORECAST royalty schedule blocks termination")
    prior = contract["status"]
    contract["status"] = "TERMINATED"
    touch(contract)
    audit.emit("Contract", contract["id"], actor_role, actor_id,
               "CONTRACT_RECORD", from_state=prior, to_state="TERMINATED")
    return contract


# -------------------- Royalty schedule logic --------------------

def create_royalty_schedule(contract, body, actor_role, actor_id):
    from utils import get_int, get_str
    period_index = get_int(body, "period_index", required=True, min_value=1)
    period_start_str = get_str(body, "period_start")
    period_end_str = get_str(body, "period_end")
    forecast_revenue = get_int(body, "forecast_revenue_cents", required=True, min_value=0)

    period_start = db.parse_iso(period_start_str)
    period_end = db.parse_iso(period_end_str)
    if not period_start or not period_end:
        raise APIError(ERR_BAD_REQUEST, 422, "Invalid period_start/period_end")
    if not (period_end > period_start):
        raise APIError(ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP, 422,
                       "period_end must be > period_start")

    # Check contiguity & no-overlap against existing schedules
    existing = sorted([rs for rs in db.royalty_schedules.values() if rs["contract_id"] == contract["id"]],
                      key=lambda r: r["period_index"])
    for rs in existing:
        s = db.parse_iso(rs["period_start"])
        e = db.parse_iso(rs["period_end"])
        # overlap check
        if not (period_end <= s or period_start >= e):
            raise APIError(ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP, 422,
                           "Royalty periods overlap")
    # Contiguity: new period_index must equal max(existing.period_index)+1 (or 1 if none)
    if existing:
        max_idx = max(rs["period_index"] for rs in existing)
        if period_index != max_idx + 1:
            raise APIError(ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP, 422,
                           "period_index must be monotonically increasing")
        # previous period_end must equal this period_start
        prev = next((rs for rs in existing if rs["period_index"] == max_idx), None)
        if prev:
            prev_end = db.parse_iso(prev["period_end"])
            if prev_end != period_start:
                raise APIError(ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP, 422,
                               "Royalty periods must be contiguous (no gap)")
    else:
        if period_index != 1:
            raise APIError(ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP, 422,
                           "First period_index must be 1")

    rate = contract.get("royalty_rate")
    provisional = 0
    if rate is not None:
        provisional = round_half_up_cents(Decimal(forecast_revenue) * Decimal(str(rate)))

    rs = make_versioned({
        "contract_id": contract["id"],
        "period_index": period_index,
        "period_start": db.to_iso(period_start),
        "period_end": db.to_iso(period_end),
        "forecast_revenue_cents": forecast_revenue,
        "actual_revenue_cents": 0,
        "provisional_royalty_cents": provisional,
        "final_royalty_cents": 0,
        "status": "FORECAST",
    })
    db.royalty_schedules[rs["id"]] = rs
    return rs


def settle_royalty_schedule(rs, body, actor_role, actor_id):
    from utils import get_int
    if rs["status"] != "FORECAST":
        raise APIError(ERR_INVALID_STATE, 409, "RoyaltySchedule already settled")
    actual = get_int(body, "actual_revenue_cents", required=True, min_value=0)
    contract = db.contracts.get(rs["contract_id"])
    if not contract:
        raise APIError(ERR_REFERENCED_ENTITY_NOT_FOUND, 422, "Parent contract missing")
    rate = contract.get("royalty_rate")
    raw = 0
    if rate is not None:
        raw = round_half_up_cents(Decimal(actual) * Decimal(str(rate)))
    if contract["contract_type"] == "EXCLUSIVE_LICENSE" and contract.get("min_guarantee_cents") is not None:
        final = max(raw, contract["min_guarantee_cents"])
    else:
        final = raw
    rs["actual_revenue_cents"] = actual
    rs["final_royalty_cents"] = final
    rs["status"] = "SETTLED"
    touch(rs)
    audit.emit("RoyaltySchedule", rs["id"], actor_role, actor_id,
               "STATUS_CHANGE", from_state="FORECAST", to_state="SETTLED",
               payload={"actual_revenue_cents": actual, "final_royalty_cents": final})
    return rs
