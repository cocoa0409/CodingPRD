"""Shared claim helpers: remedy recommendation, settlement waterfall, denial."""
import calc
import cascade
from common import ApiError, D, db, now, touch

TERMINAL = "CLOSED"
REMEDY_STRENGTH = {"SOFTWARE_REMEDIATION": 1, "MODULE_REPLACEMENT": 2, "PACK_REPLACEMENT": 3}
SETTLEMENT_FIELDS = ("settlement_variant", "proration_factor", "owner_share_cents",
                     "oem_share_cents", "admin_fee_cents", "oem_total_cents")


def assessment_of(claim):
    return db.assessments[claim["assessment_id"]]


def pack_of(claim):
    return db.packs[assessment_of(claim)["pack_id"]]


def vehicle_of(claim):
    return db.vehicles[claim["vehicle_id"]]


def center_of(claim):
    return db.centers[claim["service_center_id"]]


def program_of(claim):
    return db.programs[vehicle_of(claim)["warranty_program_id"]]


def guard_terminal(claim):
    if claim["adjudication_status"] == TERMINAL:
        raise ApiError("ERR_CLAIM_TERMINAL", 409, "The claim is closed and terminal.")


def recompute_recommendation(claim):
    assessment = assessment_of(claim)
    pack = db.packs[assessment["pack_id"]]
    program = program_of(claim)
    remedy, basis = calc.remedy_decision(program, pack, assessment)
    claim["recommended_remedy"] = remedy
    claim["recommendation_basis"] = basis
    return remedy, basis


def compute_settlement(claim, remedy, replacement_pack):
    """Returns the eight settlement values for a remedy without writing them."""
    assessment = assessment_of(claim)
    pack = db.packs[assessment["pack_id"]]
    program = program_of(claim)
    center = center_of(claim)
    cost = calc.remedy_cost_cents(program, center, pack, remedy, replacement_pack)
    fields = calc.settlement(program, assessment, cost)
    fields["remedy_cost_cents"] = cost
    return fields


def write_settlement(claim, fields):
    claim["remedy_cost_cents"] = fields["remedy_cost_cents"]
    for name in SETTLEMENT_FIELDS:
        claim[name] = fields[name]


def zero_money(claim, include_admin_fee=True, reset_proration=True):
    claim["remedy_cost_cents"] = 0
    claim["owner_share_cents"] = 0
    claim["oem_share_cents"] = 0
    claim["oem_total_cents"] = 0
    if include_admin_fee:
        claim["admin_fee_cents"] = 0
    if reset_proration:
        claim["proration_factor"] = D("0.0000")


def release_reserved_pack(claim):
    """Return a claim's reserved replacement pack to STOCK."""
    pack_id = claim.get("replacement_pack_id")
    if not pack_id:
        return
    pack = db.packs.get(pack_id)
    if pack is None:
        return
    if pack["status"] == "RESERVED":
        pack["status"] = "STOCK"
        touch(pack)
        cascade.refresh_reman_stock()


def reserve_pack(pack, vehicle_id=None):
    pack["status"] = "RESERVED"
    touch(pack)
    cascade.refresh_reman_stock()
