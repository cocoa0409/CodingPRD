"""Warranty reserve, claim adjudication and remediation (PRD 3.9)."""

from flask import Blueprint

from db import db, insert, logical_date, touch
from errors import ApiError
from middleware import (ALL_ROLES, MILL_ADMIN, MILL_SUPERVISOR,
                        WARRANTY_ADJUDICATOR, acting_user_id, authorize)
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import calc, lookup, mill
from services.calc import D
from validation import (body_json, opt_ref, opt_str, pagination, query_enum,
                        query_str, req_date, req_decimal, req_enum, req_ref, req_str)

bp = Blueprint("warranty", __name__)

CLAIM_TYPES = ("CUPPING", "GAPPING")
ADJUDICATION_STATUSES = ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "REVERSED")
REMEDIATION_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
DECISIONS = ("APPROVED", "DENIED")
OPEN_ADJUDICATION_STATUSES = ("SUBMITTED", "INFO_REQUESTED")


def _reference_moisture(claim, line):
    """The moisture the mill judges the installation against (PRD 3.9)."""
    species = db.species_profiles[line["species_profile_id"]]
    lot_id = claim.get("flooring_lot_id")
    if lot_id:
        lot = db.flooring_lots.get(lot_id)
        if lot is not None:
            charge = db.kiln_charges.get(lot["kiln_charge_id"])
            if charge is not None and charge.get("average_moisture_pct") is not None:
                return charge["average_moisture_pct"]
    return species["target_moisture_pct"]


@bp.post("/mill/warranty-claims")
@authorize(WARRANTY_ADJUDICATOR, MILL_ADMIN)
def create_warranty_claim():
    body = body_json()
    product_line_id = req_ref(body, "product_line_id")
    flooring_lot_id = opt_ref(body, "flooring_lot_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    affected_square_feet = req_decimal(body, "affected_square_feet")
    installation_date = req_date(body, "installation_date")
    subfloor_moisture_pct_at_install = req_decimal(body, "subfloor_moisture_pct_at_install")
    ambient_rh_pct_at_install = req_decimal(body, "ambient_rh_pct_at_install")

    line = lookup.product_line(product_line_id)
    if flooring_lot_id is not None:
        lookup.flooring_lot(flooring_lot_id)

    today = logical_date()
    if installation_date > today:
        raise ApiError("ERR_INSTALL_DATE_IN_FUTURE")
    if calc.whole_months_between(installation_date, today) > calc.WARRANTY_MONTHS:
        raise ApiError("ERR_WARRANTY_PERIOD_EXPIRED")

    open_claims = [c for c in db.warranty_claims.values()
                   if c["product_line_id"] == line["id"]
                   and c["adjudication_status"] in OPEN_ADJUDICATION_STATUSES]
    if len(open_claims) >= calc.MAX_OPEN_CLAIMS:
        raise ApiError("ERR_TOO_MANY_OPEN_CLAIMS")

    record = insert(db.warranty_claims, {
        "product_line_id": product_line_id,
        "flooring_lot_id": flooring_lot_id,
        "claim_type": claim_type,
        "affected_square_feet": affected_square_feet,
        "installation_date": installation_date,
        "subfloor_moisture_pct_at_install": subfloor_moisture_pct_at_install,
        "ambient_rh_pct_at_install": ambient_rh_pct_at_install,
        "estimated_liability_cents": calc.estimated_liability(
            affected_square_feet, line["material_value_cents_per_sf"]),
        "adjudicated_affected_sf": None,
        "adjudicated_subfloor_moisture_pct": None,
        "adjudicated_ambient_rh_pct": None,
        "installer_share_pct": None,
        "mill_share_pct": None,
        "service_months": None,
        "depreciation_pct": None,
        "adjudicated_liability_cents": None,
        "submitted_by_user_id": acting_user_id(),
        "adjudicated_by_user_id": None,
        "info_request_note": None,
        "denial_reason": None,
        "reversal_reason": None,
        "adjudication_status": "SUBMITTED",
        "remediation_status": "NOT_STARTED",
    })
    return object_response(serialize("warranty_claim", record), 201)


@bp.get("/mill/warranty-claims/<warranty_claim_id>")
@authorize(*ALL_ROLES)
def get_warranty_claim(warranty_claim_id):
    return object_response(serialize("warranty_claim", lookup.warranty_claim(warranty_claim_id)))


@bp.get("/mill/warranty-claims")
@authorize(*ALL_ROLES)
def list_warranty_claims():
    limit, offset = pagination()
    rows = lookup.filtered(db.warranty_claims, [
        ("product_line_id", query_str("product_line_id")),
        ("flooring_lot_id", query_str("flooring_lot_id")),
        ("adjudication_status", query_enum("adjudication_status", ADJUDICATION_STATUSES)),
        ("remediation_status", query_enum("remediation_status", REMEDIATION_STATUSES)),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("warranty_claim", page), limit, offset, total)


@bp.post("/mill/warranty-claims/<warranty_claim_id>/request_info")
@authorize(WARRANTY_ADJUDICATOR)
def request_info(warranty_claim_id):
    body = body_json()
    info_request_note = req_str(body, "info_request_note")
    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["adjudication_status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    claim["info_request_note"] = info_request_note
    claim["adjudication_status"] = "INFO_REQUESTED"
    touch(claim)
    return object_response(serialize("warranty_claim", claim))


@bp.post("/mill/warranty-claims/<warranty_claim_id>/resubmit")
@authorize(WARRANTY_ADJUDICATOR, MILL_ADMIN)
def resubmit_claim(warranty_claim_id):
    body = body_json()
    affected_square_feet = req_decimal(body, "affected_square_feet")
    subfloor_moisture_pct_at_install = req_decimal(body, "subfloor_moisture_pct_at_install")
    ambient_rh_pct_at_install = req_decimal(body, "ambient_rh_pct_at_install")

    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["adjudication_status"] != "INFO_REQUESTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    line = db.product_lines[claim["product_line_id"]]
    claim["affected_square_feet"] = affected_square_feet
    claim["subfloor_moisture_pct_at_install"] = subfloor_moisture_pct_at_install
    claim["ambient_rh_pct_at_install"] = ambient_rh_pct_at_install
    claim["estimated_liability_cents"] = calc.estimated_liability(
        affected_square_feet, line["material_value_cents_per_sf"])
    claim["info_request_note"] = None
    claim["adjudication_status"] = "SUBMITTED"
    touch(claim)
    return object_response(serialize("warranty_claim", claim))


@bp.post("/mill/warranty-claims/<warranty_claim_id>/adjudicate")
@authorize(WARRANTY_ADJUDICATOR)
def adjudicate_claim(warranty_claim_id):
    body = body_json()
    decision = req_enum(body, "decision", DECISIONS)
    adjudicated_affected_sf = req_decimal(body, "adjudicated_affected_sf")
    adjudicated_subfloor_moisture_pct = req_decimal(body, "adjudicated_subfloor_moisture_pct")
    adjudicated_ambient_rh_pct = req_decimal(body, "adjudicated_ambient_rh_pct")
    denial_reason = opt_str(body, "denial_reason")

    claim = lookup.warranty_claim(warranty_claim_id)

    actor = acting_user_id()
    if actor is not None and claim.get("submitted_by_user_id") == actor:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if claim["adjudication_status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    if adjudicated_affected_sf > D(claim["affected_square_feet"]):
        raise ApiError("ERR_ADJUDICATED_SF_EXCEEDS_CLAIM")

    line = db.product_lines[claim["product_line_id"]]

    if decision == "DENIED":
        claim["adjudicated_affected_sf"] = adjudicated_affected_sf
        claim["adjudicated_subfloor_moisture_pct"] = adjudicated_subfloor_moisture_pct
        claim["adjudicated_ambient_rh_pct"] = adjudicated_ambient_rh_pct
        claim["adjudicated_by_user_id"] = actor
        claim["denial_reason"] = denial_reason
        claim["adjudication_status"] = "DENIED"
        touch(claim)
        return object_response(serialize("warranty_claim", claim))

    reference_mc = _reference_moisture(claim, line)
    _delta, installer_share, mill_share = calc.responsibility_split(
        adjudicated_subfloor_moisture_pct, reference_mc, adjudicated_ambient_rh_pct)

    service_months = calc.whole_months_between(claim["installation_date"], logical_date())
    depreciation_pct, liability_cents = calc.adjudicated_liability(
        adjudicated_affected_sf, line["material_value_cents_per_sf"],
        service_months, mill_share)

    if liability_cents > int(line["warranty_balance_cents"]):
        raise ApiError("ERR_WARRANTY_RESERVE_INSUFFICIENT")

    claim["adjudicated_affected_sf"] = adjudicated_affected_sf
    claim["adjudicated_subfloor_moisture_pct"] = adjudicated_subfloor_moisture_pct
    claim["adjudicated_ambient_rh_pct"] = adjudicated_ambient_rh_pct
    claim["adjudicated_by_user_id"] = actor
    claim["installer_share_pct"] = int(installer_share)
    claim["mill_share_pct"] = int(mill_share)
    claim["service_months"] = service_months
    claim["depreciation_pct"] = depreciation_pct
    claim["adjudicated_liability_cents"] = liability_cents
    claim["adjudication_status"] = "APPROVED"
    touch(claim)

    line["warranty_committed_cents"] = int(line["warranty_committed_cents"]) + liability_cents
    posture = mill.recompute_posture(line)
    touch(line)
    if posture in ("RESTRICTED", "FROZEN"):
        mill.hold_scheduled_prefinish_runs(
            line, "Warranty exposure on claim %s left the product line %s."
            % (claim["id"], posture))

    return object_response(serialize("warranty_claim", claim))


@bp.post("/mill/warranty-claims/<warranty_claim_id>/reverse")
@authorize(WARRANTY_ADJUDICATOR, MILL_ADMIN)
def reverse_claim(warranty_claim_id):
    body = body_json()
    reversal_reason = req_str(body, "reversal_reason")

    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["adjudication_status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if claim["remediation_status"] == "COMPLETED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    line = db.product_lines[claim["product_line_id"]]
    line["warranty_committed_cents"] = int(line["warranty_committed_cents"]) - \
        int(claim["adjudicated_liability_cents"])
    mill.recompute_posture(line)
    touch(line)

    claim["reversal_reason"] = reversal_reason
    claim["adjudication_status"] = "REVERSED"
    if claim["remediation_status"] in ("NOT_STARTED", "IN_PROGRESS"):
        claim["remediation_status"] = "CANCELLED"
    touch(claim)
    return object_response(serialize("warranty_claim", claim))


@bp.post("/mill/warranty-claims/<warranty_claim_id>/start_remediation")
@authorize(WARRANTY_ADJUDICATOR, MILL_SUPERVISOR)
def start_remediation(warranty_claim_id):
    body_json()
    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["adjudication_status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if claim["remediation_status"] != "NOT_STARTED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    claim["remediation_status"] = "IN_PROGRESS"
    touch(claim)
    return object_response(serialize("warranty_claim", claim))


@bp.post("/mill/warranty-claims/<warranty_claim_id>/complete_remediation")
@authorize(WARRANTY_ADJUDICATOR, MILL_SUPERVISOR)
def complete_remediation(warranty_claim_id):
    body_json()
    claim = lookup.warranty_claim(warranty_claim_id)
    if claim["adjudication_status"] != "APPROVED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if claim["remediation_status"] != "IN_PROGRESS":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    claim["remediation_status"] = "COMPLETED"
    touch(claim)
    return object_response(serialize("warranty_claim", claim))
