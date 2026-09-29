"""Claim settlement, bounded negotiation and independent dispute resolution."""

from flask import Blueprint

import constants as C
from db import base_row, db, touch
from domain import (
    append_ledger,
    claim_view,
    contract_idr_eligible,
    contract_status,
    dispute_view,
    get_claim,
    get_contract,
    get_dispute,
    get_encounter,
    rows_of,
    select_protection_variant,
    settle_claim,
)
from errors import ApiError
from response import created, ok, ok_list, paginate
from validate import (
    auth,
    body,
    pagination,
    query_enum,
    query_str,
    req_int,
    req_str,
)

bp = Blueprint("claims", __name__)

CLAIM_READ_ROLES = (
    "ComplianceOfficer",
    "PayerRepresentative",
    "FacilityAdministrator",
    "IDREntity",
)
DISPUTE_READ_ROLES = (
    "ComplianceOfficer",
    "PayerRepresentative",
    "IDREntity",
    "FacilityAdministrator",
)


def _facility_of_claim(claim):
    encounter = db.encounters[claim["encounter_id"]]
    return db.facilities[encounter["facility_id"]]


# --- claims ---------------------------------------------------------------


@bp.post("/encounters/<eid>/claims")
def create_claim(eid):
    auth("ComplianceOfficer")
    data = body()
    contract_id = req_str(data, "payer_contract_id", 1, 64)

    encounter = get_encounter(eid)
    facility = db.facilities[encounter["facility_id"]]

    contract = get_contract(contract_id)
    if contract["facility_id"] != facility["id"]:
        raise ApiError("ERR_PAYER_CONTRACT_NOT_FOUND")

    if encounter["clinical_state"] not in C.TERMINAL_CLINICAL_STATES:
        raise ApiError("ERR_INVALID_ENCOUNTER_STATE")
    if contract_status(contract) != "ACTIVE":
        raise ApiError("ERR_PAYER_CONTRACT_NOT_ACTIVE")
    for existing in db.claims.values():
        if existing["encounter_id"] == encounter["id"]:
            raise ApiError("ERR_CLAIM_ALREADY_EXISTS")

    template = db.templates[encounter["pinned_disclosure_template_id"]]
    facility_fee = template["facility_fee_cents"]
    ancillary_total = sum(
        order["line_total_cents"]
        for order in db.ancillary_orders.values()
        if order["encounter_id"] == encounter["id"] and order["status"] == "RESULTED"
    )

    claim = base_row()
    claim.update(
        {
            "encounter_id": encounter["id"],
            "payer_contract_id": contract["id"],
            "billed_facility_fee_cents": facility_fee,
            "billed_ancillary_cents": ancillary_total,
            "billed_total_cents": facility_fee + ancillary_total,
            "protection_variant": select_protection_variant(contract, encounter),
            "allowed_amount_cents": None,
            "plan_paid_cents": None,
            "patient_responsibility_cents": None,
            "balance_bill_amount_cents": None,
            "written_off_cents": None,
            "pre_award_allowed_cents": None,
            "pre_award_plan_paid_cents": None,
            "pre_award_patient_responsibility_cents": None,
            "pre_award_written_off_cents": None,
            "negotiation_rounds_used": 0,
            "status": "DRAFT",
        }
    )
    db.claims[claim["id"]] = claim
    return created(claim_view(claim))


@bp.get("/claims")
def list_claims():
    auth(*CLAIM_READ_ROLES)
    encounter_id = query_str("encounter_id")
    contract_id = query_str("payer_contract_id")
    status = query_enum("status", C.CLAIM_STATUSES)
    limit, offset = pagination()

    rows = rows_of(db.claims)
    if encounter_id is not None:
        rows = [r for r in rows if r["encounter_id"] == encounter_id]
    if contract_id is not None:
        rows = [r for r in rows if r["payer_contract_id"] == contract_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return ok_list([claim_view(r) for r in page], limit, offset, len(rows))


@bp.get("/claims/<cid>")
def read_claim(cid):
    auth(*CLAIM_READ_ROLES)
    return ok(claim_view(get_claim(cid)))


@bp.post("/claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    auth("PayerRepresentative")
    data = body()
    req_str(data, "adjudication_note", 1, 1000, required=False)

    claim = get_claim(cid)
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    contract = db.contracts[claim["payer_contract_id"]]
    if contract_status(contract) != "ACTIVE":
        raise ApiError("ERR_PAYER_CONTRACT_NOT_ACTIVE")

    settle_claim(claim, contract)
    claim["status"] = "ADJUDICATED"
    touch(claim)

    if claim["balance_bill_amount_cents"] > 0:
        append_ledger(
            _facility_of_claim(claim),
            "BALANCE_BILL_ISSUED",
            "MINOR",
            "CLAIM",
            claim["id"],
            "Adjudication left a permitted balance bill for the patient.",
            defect_counted=False,
        )
    return ok(claim_view(claim))


# --- dispute cases --------------------------------------------------------


@bp.post("/claims/<cid>/dispute-cases")
def open_dispute_case(cid):
    user_id, _ = auth("ComplianceOfficer")
    data = body()
    req_str(data, "dispute_note", 1, 1000, required=False)

    claim = get_claim(cid)
    if claim["status"] != "ADJUDICATED":
        raise ApiError("ERR_INVALID_CLAIM_STATE")
    contract = db.contracts[claim["payer_contract_id"]]
    if not contract_idr_eligible(contract):
        raise ApiError("ERR_IDR_NOT_ELIGIBLE")

    dispute = base_row()
    dispute.update(
        {
            "claim_id": claim["id"],
            "initiated_by_user_id": user_id,
            "round_index": 0,
            "last_offer_cents": None,
            "last_counteroffer_cents": None,
            "last_offer_by_user_id": None,
            "idr_award_cents": None,
            "awarded_at": None,
            "status": "OPEN_NEGOTIATION",
        }
    )
    db.disputes[dispute["id"]] = dispute

    claim["status"] = "NEGOTIATION"
    claim["negotiation_rounds_used"] = 0
    touch(claim)
    return created(dispute_view(dispute))


@bp.get("/claims/<cid>/dispute-cases")
def list_dispute_cases(cid):
    auth(*DISPUTE_READ_ROLES)
    status = query_enum("status", C.DISPUTE_STATUSES)
    limit, offset = pagination()

    claim = get_claim(cid)
    rows = rows_of(db.disputes, claim_id=claim["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page = paginate(rows, limit, offset)
    return ok_list([dispute_view(r) for r in page], limit, offset, len(rows))


@bp.get("/dispute-cases/<did>")
def read_dispute_case(did):
    auth(*DISPUTE_READ_ROLES)
    return ok(dispute_view(get_dispute(did)))


@bp.post("/dispute-cases/<did>/offers")
def submit_offer(did):
    user_id, role = auth("ComplianceOfficer", "PayerRepresentative")
    data = body()
    offer_cents = req_int(data, "offer_cents", minimum=0)
    req_str(data, "offer_note", 1, 1000, required=False)

    dispute = get_dispute(did)
    claim = db.claims[dispute["claim_id"]]

    if role == "ComplianceOfficer":
        if dispute["status"] != "OPEN_NEGOTIATION":
            raise ApiError("ERR_INVALID_DISPUTE_STATE")
        if dispute["round_index"] >= C.NEGOTIATION_MAX_ROUNDS:
            raise ApiError("ERR_NEGOTIATION_ROUNDS_EXHAUSTED")
        dispute["last_offer_cents"] = offer_cents
        dispute["last_offer_by_user_id"] = user_id
        dispute["status"] = "OFFER_PENDING"
        touch(dispute)
    else:
        if dispute["status"] != "OFFER_PENDING":
            raise ApiError("ERR_INVALID_DISPUTE_STATE")
        dispute["last_counteroffer_cents"] = offer_cents
        dispute["last_offer_by_user_id"] = user_id
        dispute["round_index"] += 1
        dispute["status"] = "OPEN_NEGOTIATION"
        touch(dispute)
        claim["negotiation_rounds_used"] = dispute["round_index"]
        touch(claim)
    return ok(dispute_view(dispute))


@bp.post("/dispute-cases/<did>/initiate-idr")
def initiate_idr(did):
    auth("ComplianceOfficer")
    data = body()
    entity_name = req_str(data, "certified_entity_name", 1, 200)

    dispute = get_dispute(did)
    claim = db.claims[dispute["claim_id"]]
    contract = db.contracts[claim["payer_contract_id"]]

    if dispute["status"] != "OPEN_NEGOTIATION":
        raise ApiError("ERR_INVALID_DISPUTE_STATE")
    if not contract_idr_eligible(contract):
        raise ApiError("ERR_IDR_NOT_ELIGIBLE")
    if dispute["round_index"] < C.NEGOTIATION_MAX_ROUNDS:
        raise ApiError("ERR_NEGOTIATION_NOT_EXHAUSTED")

    dispute["status"] = "IDR_INITIATED"
    touch(dispute)

    claim["status"] = "IDR_PENDING"
    claim["negotiation_rounds_used"] = dispute["round_index"]
    touch(claim)

    append_ledger(
        _facility_of_claim(claim),
        "IDR_INITIATED",
        "INFO",
        "CLAIM",
        claim["id"],
        "Negotiation escalated to certified entity %s." % entity_name,
        defect_counted=False,
    )
    return ok(dispute_view(dispute))


@bp.post("/dispute-cases/<did>/award")
def enter_award(did):
    auth("IDREntity")
    data = body()
    award_cents = req_int(data, "award_cents", minimum=0)
    req_str(data, "award_rationale", 1, 1000, required=False)

    dispute = get_dispute(did)
    claim = db.claims[dispute["claim_id"]]
    contract = db.contracts[claim["payer_contract_id"]]

    if dispute["status"] != "IDR_INITIATED":
        raise ApiError("ERR_INVALID_DISPUTE_STATE")

    offer = dispute["last_offer_cents"]
    counter = dispute["last_counteroffer_cents"]
    if offer is None or counter is None:
        raise ApiError("ERR_AWARD_OUT_OF_RANGE")
    low, high = min(offer, counter), max(offer, counter)
    if award_cents < low or award_cents > high:
        raise ApiError("ERR_AWARD_OUT_OF_RANGE")

    dispute["status"] = "AWARDED"
    dispute["idr_award_cents"] = award_cents
    dispute["awarded_at"] = db.clock
    touch(dispute)

    claim["pre_award_allowed_cents"] = claim["allowed_amount_cents"]
    claim["pre_award_plan_paid_cents"] = claim["plan_paid_cents"]
    claim["pre_award_patient_responsibility_cents"] = claim["patient_responsibility_cents"]
    claim["pre_award_written_off_cents"] = claim["written_off_cents"]
    settle_claim(claim, contract, allowed_total=award_cents)
    claim["status"] = "RESOLVED"
    touch(claim)

    append_ledger(
        _facility_of_claim(claim),
        "IDR_AWARDED",
        "INFO",
        "CLAIM",
        claim["id"],
        "Certified entity awarded an allowed amount of %d cents." % award_cents,
        defect_counted=False,
    )
    return ok(dispute_view(dispute))


@bp.post("/dispute-cases/<did>/withdraw")
def withdraw_award(did):
    auth("IDREntity")
    data = body()
    req_str(data, "withdrawal_reason", 1, 500)

    dispute = get_dispute(did)
    claim = db.claims[dispute["claim_id"]]

    if dispute["status"] != "AWARDED":
        raise ApiError("ERR_INVALID_DISPUTE_STATE")

    dispute["status"] = "WITHDRAWN"
    dispute["idr_award_cents"] = None
    dispute["awarded_at"] = None
    touch(dispute)

    # Strict compensating restore: no recomputation, therefore no rounding drift.
    claim["allowed_amount_cents"] = claim["pre_award_allowed_cents"]
    claim["plan_paid_cents"] = claim["pre_award_plan_paid_cents"]
    claim["patient_responsibility_cents"] = claim["pre_award_patient_responsibility_cents"]
    claim["written_off_cents"] = claim["pre_award_written_off_cents"]
    if claim["protection_variant"] == "UNPROTECTED":
        claim["balance_bill_amount_cents"] = (
            claim["billed_total_cents"] - claim["allowed_amount_cents"]
        )
    else:
        claim["balance_bill_amount_cents"] = 0
    claim["pre_award_allowed_cents"] = None
    claim["pre_award_plan_paid_cents"] = None
    claim["pre_award_patient_responsibility_cents"] = None
    claim["pre_award_written_off_cents"] = None
    claim["status"] = "IDR_PENDING"
    touch(claim)

    append_ledger(
        _facility_of_claim(claim),
        "IDR_AWARD_WITHDRAWN",
        "MINOR",
        "CLAIM",
        claim["id"],
        "Entered award vacated; the claim was compensated back to its pre-award settlement.",
        defect_counted=False,
    )
    return ok(dispute_view(dispute))
