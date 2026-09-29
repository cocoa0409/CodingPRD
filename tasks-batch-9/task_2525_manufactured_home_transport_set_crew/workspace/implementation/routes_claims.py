"""Damage-in-transit claims and the chargeback ledger (PRD 3.9)."""
from flask import Blueprint

import calc
import domain
from envelope import object_response
from errors import fail
from guards import (
    ANY_ROLE,
    actor_id,
    actor_role,
    apply_filters,
    filters,
    lookup,
    lookup_ref,
    roles,
    validate,
)
from routes_partners import list_response
from store import base_row, db, mark

bp = Blueprint("claims", __name__)

STAGES = ["PLANT_QC", "IN_TRANSIT", "AT_SET", "FINAL_INSPECTION", "UNKNOWN"]
HOLDABLE_SECTION_STATES = ("IN_TRANSIT", "DELIVERED")


def _points(claim):
    return {
        "PLANT": int(claim["plant_evidence_points"]),
        "HAULER": int(claim["hauler_evidence_points"]),
        "INSTALLER": int(claim["installer_evidence_points"]),
    }


@bp.post("/installations/damage-claims")
@roles("PlantDispatcher", "TransportManager", "SetCrewLead", "ClaimsAdjuster")
def create_claim():
    body = validate(
        [
            {"name": "order_id", "type": "string", "required": True},
            {"name": "section_id", "type": "string", "required": True},
            {"name": "hauler_id", "type": "string", "required": True},
            {"name": "set_crew_id", "type": "string", "required": True},
            {
                "name": "discovered_stage",
                "type": "enum",
                "required": True,
                "values": STAGES,
            },
            {
                "name": "claimed_amount_cents",
                "type": "integer",
                "required": True,
                "min": 1,
            },
            {"name": "blocks_set", "type": "boolean", "required": False},
            {
                "name": "plant_evidence_points",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 10,
            },
            {
                "name": "hauler_evidence_points",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 10,
            },
            {
                "name": "installer_evidence_points",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 10,
            },
        ]
    )
    # Priority 5: references resolve left to right in declaration order.
    order = lookup_ref("orders", body["order_id"], "ERR_ORDER_NOT_FOUND")
    section = lookup_ref("sections", body["section_id"], "ERR_SECTION_NOT_FOUND")
    # PRD 2.7: the floor named by section_id must belong to order_id; a floor of
    # another order is not a floor of this claim's order, hence the same 404.
    if section["order_id"] != order["id"]:
        fail("ERR_SECTION_NOT_FOUND")
    hauler = lookup_ref("haulers", body["hauler_id"], "ERR_HAULER_NOT_FOUND")
    crew = lookup_ref("set_crews", body["set_crew_id"], "ERR_SET_CREW_NOT_FOUND")

    # Priority 30: single-claim exposure ceiling.
    if int(body["claimed_amount_cents"]) > calc.CLAIM_CAP_CENTS:
        fail("ERR_CLAIM_AMOUNT_EXCEEDS_CAP")

    row = base_row()
    row.update(
        {
            "order_id": order["id"],
            "section_id": section["id"],
            "hauler_id": hauler["id"],
            "set_crew_id": crew["id"],
            "discovered_stage": body["discovered_stage"],
            "claimed_amount_cents": int(body["claimed_amount_cents"]),
            "blocks_set": bool(body.get("blocks_set", False)),
            "plant_evidence_points": int(body.get("plant_evidence_points", 0) or 0),
            "hauler_evidence_points": int(body.get("hauler_evidence_points", 0) or 0),
            "installer_evidence_points": int(
                body.get("installer_evidence_points", 0) or 0
            ),
            "allocation_basis": None,
            "approved_amount_cents": None,
            "plant_charge_cents": 0,
            "hauler_charge_cents": 0,
            "installer_charge_cents": 0,
            "dispute_round": 0,
            "status": "SUBMITTED",
        }
    )
    db.claims[row["id"]] = row

    # PRD 3.9: a blocking claim holds the floor and freezes downstream set work.
    if row["blocks_set"] and section["transit_status"] in HOLDABLE_SECTION_STATES:
        section["transit_status"] = "DAMAGED_HOLD"
        mark(section)
        mark(order)
        domain.recompute_posture(order)

    return object_response(domain.pub_claim(row), 201)


@bp.get("/installations/damage-claims/<row_id>")
@roles(*ANY_ROLE)
def read_claim(row_id):
    row = lookup("claims", row_id, "ERR_CLAIM_NOT_FOUND")
    return object_response(domain.pub_claim(row))


@bp.get("/installations/damage-claims")
@roles(*ANY_ROLE)
def list_claims():
    active = filters(
        {
            "order_id": None,
            "section_id": None,
            "hauler_id": None,
            "set_crew_id": None,
            "status": [
                "SUBMITTED",
                "UNDER_REVIEW",
                "DISPUTED",
                "ADJUDICATED",
                "REVERSED",
            ],
        }
    )
    rows = apply_filters(list(db.claims.values()), active)
    return list_response(rows, domain.pub_claim)


@bp.post("/installations/damage-claims/<row_id>/review")
@roles("ClaimsAdjuster")
def review_claim(row_id):
    validate([{"name": "notes", "type": "string", "required": True}])
    claim = lookup("claims", row_id, "ERR_CLAIM_NOT_FOUND")
    # SUBMITTED -> UNDER_REVIEW, and DISPUTED -> UNDER_REVIEW closes the cycle.
    if claim["status"] not in ("SUBMITTED", "DISPUTED"):
        fail("ERR_INVALID_STATE")
    claim["status"] = "UNDER_REVIEW"
    mark(claim)
    return object_response(domain.pub_claim(claim))


@bp.post("/installations/damage-claims/<row_id>/dispute")
@roles("PlantDispatcher", "TransportManager", "SetCrewLead")
def dispute_claim(row_id):
    body = validate(
        [
            {"name": "reason_code", "type": "string", "required": True},
            {
                "name": "plant_evidence_points",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 10,
            },
            {
                "name": "hauler_evidence_points",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 10,
            },
            {
                "name": "installer_evidence_points",
                "type": "integer",
                "required": False,
                "min": 0,
                "max": 10,
            },
        ]
    )
    claim = lookup("claims", row_id, "ERR_CLAIM_NOT_FOUND")
    # PRD 3.9: only a named party may push back -- the plant reached through the
    # order, the named hauler, or the named installer.
    role = actor_role()
    who = actor_id()
    if role == "PlantDispatcher":
        order = db.orders.get(claim["order_id"])
        owner = None if order is None else order["plant_id"]
    elif role == "TransportManager":
        owner = claim["hauler_id"]
    else:
        owner = claim["set_crew_id"]
    if who != owner:
        fail("ERR_NOT_RESOURCE_OWNER")

    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE")

    for field in (
        "plant_evidence_points",
        "hauler_evidence_points",
        "installer_evidence_points",
    ):
        if field in body:
            claim[field] = int(body[field])
    claim["status"] = "DISPUTED"
    claim["dispute_round"] = int(claim["dispute_round"]) + 1
    mark(claim)
    return object_response(domain.pub_claim(claim))


@bp.post("/installations/damage-claims/<row_id>/adjudicate")
@roles("ClaimsAdjuster")
def adjudicate_claim(row_id):
    body = validate(
        [
            {
                "name": "allocation_basis",
                "type": "enum",
                "required": True,
                "values": ["STAGE", "EVIDENCE"],
            }
        ]
    )
    claim = lookup("claims", row_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "UNDER_REVIEW":
        fail("ERR_INVALID_STATE")

    basis = body["allocation_basis"]
    approved = calc.approved_amount(claim["claimed_amount_cents"])

    # Priority 28: allocation-basis preconditions.
    if basis == "EVIDENCE":
        points = _points(claim)
        if sum(points.values()) < 1:
            fail("ERR_CLAIM_EVIDENCE_MISSING")
        charges = calc.evidence_allocation(points, approved)
    else:
        charges = calc.stage_allocation(claim["discovered_stage"], approved)
        if charges is None:
            fail("ERR_CLAIM_STAGE_MISMATCH")

    # Cascade level 1: the allocation is written and the claim settles.
    claim["allocation_basis"] = basis
    claim["approved_amount_cents"] = approved
    claim["plant_charge_cents"] = charges["PLANT"]
    claim["hauler_charge_cents"] = charges["HAULER"]
    claim["installer_charge_cents"] = charges["INSTALLER"]
    claim["status"] = "ADJUDICATED"
    mark(claim)

    # Levels 2-5: full ledger recompute, status refresh, leg holds, postures.
    affected = domain.refresh_chargebacks()
    for order in affected.values():
        domain.recompute_posture(order)

    # Separately: the held floor is released once no blocking claim remains.
    section = db.sections.get(claim["section_id"])
    if claim["blocks_set"] and domain.release_damaged_section(section):
        order = db.orders.get(claim["order_id"])
        if order is not None:
            domain.recompute_posture(order)

    return object_response(domain.pub_claim(claim))


@bp.post("/installations/damage-claims/<row_id>/reverse")
@roles("ClaimsAdjuster")
def reverse_claim(row_id):
    validate([{"name": "reason_code", "type": "string", "required": True}])
    claim = lookup("claims", row_id, "ERR_CLAIM_NOT_FOUND")
    if claim["status"] != "ADJUDICATED":
        fail("ERR_INVALID_STATE")

    claim["status"] = "REVERSED"
    claim["plant_charge_cents"] = 0
    claim["hauler_charge_cents"] = 0
    claim["installer_charge_cents"] = 0
    claim["allocation_basis"] = None
    claim["approved_amount_cents"] = None
    mark(claim)

    # PRD 3.9: unwind with no residue -- balances recomputed in full from the
    # surviving adjudicated rows, statuses refreshed, held legs restored.
    affected = domain.refresh_chargebacks()
    for order in affected.values():
        domain.recompute_posture(order)

    section = db.sections.get(claim["section_id"])
    if claim["blocks_set"] and domain.release_damaged_section(section):
        order = db.orders.get(claim["order_id"])
        if order is not None:
            domain.recompute_posture(order)

    return object_response(domain.pub_claim(claim))
