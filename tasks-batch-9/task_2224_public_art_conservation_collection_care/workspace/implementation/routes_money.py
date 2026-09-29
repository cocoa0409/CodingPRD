"""Funding pools, allocations and damage/insurance recovery (PRD 3.10, 3.11)."""

from flask import Blueprint

import calc
import services as svc
from db import create_record, db, fmt_instant, now, ordered, parse_date, touch
from errors import ApiError
from middleware import ANY_ROLE, FUNDING_ROLES, endpoint
from response import created, listing, ok
from validate import (
    ALLOCATION_PURPOSES,
    CLAIM_BASES,
    CLAIM_OUTCOMES,
    INCIDENT_TYPES,
    POOL_TYPES,
    TRIAGE_CHOICES,
    apply_filters,
    field,
    paging,
    parse_input,
)

bp = Blueprint("money", __name__)


# ---------------------------------------------------------------------------
# FundingPool
# ---------------------------------------------------------------------------

@bp.post("/public-art/funding-pools")
@endpoint(("FinanceOfficer",))
def create_pool():
    body = parse_input({
        "pool_code": field("string", required=True),
        "pool_type": field("enum", required=True, enum=POOL_TYPES),
        "fiscal_year": field("int", required=True, minimum=2000, maximum=2100),
        "principal_cents": field("int", default=0, minimum=0),
        "draw_rate_bps": field("int", default=0, minimum=0, maximum=2000),
        "set_aside_cents": field("int", default=0, minimum=0),
    })
    for existing in db.pools.values():
        if existing["pool_code"] == body["pool_code"]:
            raise ApiError("ERR_DUPLICATE_CODE", "pool_code is already in use.")

    draft = {
        "pool_code": body["pool_code"],
        "pool_type": body["pool_type"],
        "fiscal_year": body["fiscal_year"],
        "principal_cents": body["principal_cents"],
        "draw_rate_bps": body["draw_rate_bps"],
        "set_aside_cents": body["set_aside_cents"],
        "recovery_credits_cents": 0,
    }
    authorized, admin_fee = calc.pool_draw(draft)
    draft["draw_authorized_cents"] = authorized
    draft["admin_fee_cents"] = admin_fee
    draft["available_cents"] = authorized
    return created(create_record(db.pools, draft))


@bp.get("/public-art/funding-pools/<pool_id>")
@endpoint(FUNDING_ROLES)
def read_pool(pool_id):
    return ok(svc.pool_or_404(pool_id))


@bp.get("/public-art/funding-pools")
@endpoint(FUNDING_ROLES)
def list_pools():
    limit, offset = paging()
    rows = apply_filters(db.pools.values(), (
        ("pool_type", "pool_type", "string"),
        ("fiscal_year", "fiscal_year", "int"),
    ))
    return listing(ordered(rows), limit, offset)


# ---------------------------------------------------------------------------
# FundingAllocation
# ---------------------------------------------------------------------------

@bp.post("/public-art/funding-allocations")
@endpoint(("FinanceOfficer",))
def create_allocation():
    body = parse_input({
        "pool_id": field("id", required=True),
        "purpose": field("enum", required=True, enum=ALLOCATION_PURPOSES),
        "amount_cents": field("int", required=True, minimum=1),
        "expected_pool_version": field("int", required=True),
        "proposal_id": field("id"),
        "visit_id": field("id"),
    })
    pool = svc.pool_or_404(body["pool_id"])
    proposal = svc.proposal_or_404(body["proposal_id"]) if body["proposal_id"] else None
    visit = svc.visit_or_404(body["visit_id"]) if body["visit_id"] else None

    # PRD 2.11: optimistic concurrency on the pool balance
    if int(body["expected_pool_version"]) != int(pool["version"]):
        raise ApiError("ERR_STALE_POOL_VERSION")

    if body["purpose"] == "TREATMENT":
        if proposal is None or visit is not None:
            raise ApiError("ERR_ALLOCATION_LINK_MISMATCH")
    else:
        if visit is None or proposal is not None:
            raise ApiError("ERR_ALLOCATION_LINK_MISMATCH")

    if int(body["amount_cents"]) > int(pool["available_cents"]):
        raise ApiError("ERR_POOL_FUNDS_INSUFFICIENT")

    record = create_record(db.allocations, {
        "pool_id": pool["id"],
        "proposal_id": proposal["id"] if proposal else None,
        "visit_id": visit["id"] if visit else None,
        "purpose": body["purpose"],
        "amount_cents": body["amount_cents"],
        "status": "RESERVED",
        "release_reason": "NONE",
        "released_at": None,
    })
    svc.recompute_pool(pool)
    return created(record)


@bp.get("/public-art/funding-allocations/<allocation_id>")
@endpoint(FUNDING_ROLES)
def read_allocation(allocation_id):
    return ok(svc.allocation_or_404(allocation_id))


@bp.get("/public-art/funding-allocations")
@endpoint(FUNDING_ROLES)
def list_allocations():
    limit, offset = paging()
    rows = apply_filters(db.allocations.values(), (
        ("pool_id", "pool_id", "string"),
        ("proposal_id", "proposal_id", "string"),
        ("visit_id", "visit_id", "string"),
        ("purpose", "purpose", "string"),
        ("status", "status", "string"),
        ("release_reason", "release_reason", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/funding-allocations/<allocation_id>/release")
@endpoint(("FinanceOfficer",))
def release_allocation_endpoint(allocation_id):
    allocation = svc.allocation_or_404(allocation_id)
    parse_input({"release_note": field("string")})
    # a manual release is restricted to RESERVED; cascades may also release COMMITTED
    svc.require_state(allocation["status"], ("RESERVED",), "ERR_ALLOCATION_INVALID_STATE")
    svc.release_allocation(allocation, "MANUAL_RELEASE")
    return ok(allocation)


# ---------------------------------------------------------------------------
# DamageIncident
# ---------------------------------------------------------------------------

@bp.post("/public-art/damage-incidents")
@endpoint(("CollectionsRegistrar", "PublicArtManager", "MaintenanceCrew"))
def create_incident():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "incident_type": field("enum", required=True, enum=INCIDENT_TYPES),
        "damage_extent_pct": field("number", required=True, minimum=0, maximum=1),
        "narrative": field("string", required=True),
        "linked_proposal_id": field("id"),
        "credited_pool_id": field("id"),
    })
    artwork = svc.artwork_or_404(body["artwork_id"])
    proposal = svc.proposal_or_404(body["linked_proposal_id"]) if body["linked_proposal_id"] else None
    pool = svc.pool_or_404(body["credited_pool_id"]) if body["credited_pool_id"] else None
    # PRD 2.8 step 12 -- guards every write that references an artwork.
    svc.require_in_collection(artwork)

    record = create_record(db.incidents, {
        "artwork_id": artwork["id"],
        "incident_type": body["incident_type"],
        "damage_extent_pct": body["damage_extent_pct"],
        "narrative": body["narrative"],
        "linked_proposal_id": proposal["id"] if proposal else None,
        "reported_at": fmt_instant(now()),
        "damage_status": "REPORTED",
        "triage_class": "NONE",
        "claim_status": "NONE",
        "claim_basis": "NONE",
        "claimed_gross_cents": 0,
        "settlement_cents": 0,
        "credited_pool_id": pool["id"] if pool else None,
    })
    return created(record)


@bp.get("/public-art/damage-incidents/<incident_id>")
@endpoint(ANY_ROLE)
def read_incident(incident_id):
    return ok(svc.incident_or_404(incident_id))


@bp.get("/public-art/damage-incidents")
@endpoint(ANY_ROLE)
def list_incidents():
    limit, offset = paging()
    rows = apply_filters(db.incidents.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("incident_type", "incident_type", "string"),
        ("damage_status", "damage_status", "string"),
        ("claim_status", "claim_status", "string"),
        ("triage_class", "triage_class", "string"),
        ("claim_basis", "claim_basis", "string"),
        ("linked_proposal_id", "linked_proposal_id", "string"),
        ("credited_pool_id", "credited_pool_id", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/damage-incidents/<incident_id>/triage")
@endpoint(("ChiefConservator",))
def triage_incident(incident_id):
    incident = svc.incident_or_404(incident_id)
    body = parse_input({
        "triage_class": field("enum", required=True, enum=TRIAGE_CHOICES),
        "triage_note": field("string"),
    })
    svc.require_state(incident["damage_status"], ("REPORTED",), "ERR_INCIDENT_INVALID_STATE")
    incident["damage_status"] = "TRIAGED"
    incident["triage_class"] = body["triage_class"]
    touch(incident)
    return ok(incident)


@bp.post("/public-art/damage-incidents/<incident_id>/file-claim")
@endpoint(("FinanceOfficer",))
def file_claim(incident_id):
    incident = svc.incident_or_404(incident_id)
    body = parse_input({
        "claim_basis": field("enum", required=True, enum=CLAIM_BASES),
        "credited_pool_id": field("id"),
        "policy_note": field("string"),
    })
    pool = svc.pool_or_404(body["credited_pool_id"]) if body["credited_pool_id"] else None

    svc.require_state(incident["claim_status"], ("NONE",), "ERR_CLAIM_INVALID_STATE")
    svc.require_state(incident["damage_status"], ("TRIAGED",), "ERR_INCIDENT_INVALID_STATE")

    artwork = svc.artwork_or_404(incident["artwork_id"])
    if body["claim_basis"] == "RESTORATION":
        linked = db.proposals.get(incident.get("linked_proposal_id") or "")
        if (
            linked is None
            or linked["status"] not in ("APPROVED", "IN_EXECUTION", "COMPLETED")
            or linked.get("pinned_estimate_total_cents") is None
        ):
            raise ApiError("ERR_CLAIM_BASIS_UNSUPPORTED")
        gross = int(linked["pinned_estimate_total_cents"])
    else:
        elapsed_days = (now().date() - parse_date(artwork["acquisition_date"])).days
        gross = calc.acv_claim_gross(
            artwork["insured_value_cents"], elapsed_days, incident["damage_extent_pct"]
        )

    if pool is not None:
        incident["credited_pool_id"] = pool["id"]
    incident["claim_basis"] = body["claim_basis"]
    incident["claimed_gross_cents"] = gross
    incident["settlement_cents"] = calc.settlement_from_gross(gross)
    incident["claim_status"] = "FILED"
    touch(incident)
    return ok(incident)


@bp.post("/public-art/damage-incidents/<incident_id>/resolve-claim")
@endpoint(("FinanceOfficer",))
def resolve_claim(incident_id):
    incident = svc.incident_or_404(incident_id)
    body = parse_input({
        "outcome": field("enum", required=True, enum=CLAIM_OUTCOMES),
        "resolution_note": field("string"),
    })
    svc.require_state(incident["claim_status"], ("FILED",), "ERR_CLAIM_INVALID_STATE")

    if body["outcome"] == "DENY":
        incident["claim_status"] = "DENIED"
        incident["settlement_cents"] = 0
        touch(incident)
        return ok(incident)

    if not incident.get("credited_pool_id"):
        raise ApiError("ERR_CREDIT_POOL_REQUIRED")
    if int(incident["settlement_cents"]) <= 0:
        raise ApiError("ERR_NO_SETTLEMENT_PAYABLE")
    pool = svc.pool_or_404(incident["credited_pool_id"])

    incident["claim_status"] = "SETTLED"
    touch(incident)
    pool["recovery_credits_cents"] = (
        int(pool["recovery_credits_cents"]) + int(incident["settlement_cents"])
    )
    touch(pool)
    svc.recompute_pool(pool)
    return ok(incident)
