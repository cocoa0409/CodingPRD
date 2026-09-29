"""Treatment proposals: drafting, costing, approval gates and execution (PRD 3.4, 3.5)."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import services as svc
from db import create_record, db, fmt_instant, now, ordered, parse_date, parse_instant, touch
from errors import ApiError
from middleware import ANY_ROLE, endpoint, require_owner
from response import created, listing, ok
from validate import (
    TREATMENT_SCOPES,
    apply_filters,
    bad,
    field,
    paging,
    parse_input,
)

bp = Blueprint("treatment", __name__)


@bp.post("/public-art/treatment-proposals")
@endpoint(("ChiefConservator",))
def create_proposal():
    body = parse_input({
        "artwork_id": field("id", required=True),
        "conservator_id": field("id", required=True),
        "assessment_id": field("id", required=True),
        "treatment_scope": field("enum", required=True, enum=TREATMENT_SCOPES),
        "engagement_start": field("datetime", required=True),
        "engagement_end": field("datetime", required=True),
        "expected_artwork_version": field("int", required=True),
        "alters_appearance": field("bool", default=False),
    })
    if parse_instant(body["engagement_end"]) <= parse_instant(body["engagement_start"]):
        bad("engagement_end must be strictly after engagement_start.")

    artwork = svc.artwork_or_404(body["artwork_id"])
    conservator = svc.conservator_or_404(body["conservator_id"])
    assessment = svc.assessment_or_404(body["assessment_id"])

    # PRD 2.8 step 6: optimistic concurrency on the parent artwork
    if int(body["expected_artwork_version"]) != int(artwork["version"]):
        raise ApiError("ERR_STALE_ARTWORK_VERSION")

    svc.require_in_collection(artwork)

    for other in db.proposals.values():
        if (
            other["assessment_id"] == assessment["id"]
            and other["status"] in svc.LIVE_PROPOSAL_STATUSES
        ):
            raise ApiError("ERR_DUPLICATE_ACTIVE_PROPOSAL")

    if assessment["status"] != "FINALIZED" or assessment["artwork_id"] != artwork["id"]:
        raise ApiError("ERR_ASSESSMENT_NOT_FINALIZED")

    record = create_record(db.proposals, {
        "artwork_id": artwork["id"],
        "conservator_id": conservator["id"],
        "assessment_id": assessment["id"],
        "treatment_scope": body["treatment_scope"],
        "alters_appearance": body["alters_appearance"],
        "engagement_start": body["engagement_start"],
        "engagement_end": body["engagement_end"],
        "line_items": [],
        "subtotal_cents": 0,
        "overhead_cents": 0,
        "contingency_cents": 0,
        "mobilization_cents": 0,
        "estimate_total_cents": 0,
        "pinned_estimate_total_cents": None,
        "status": "DRAFT",
        "revision_rounds": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "withdraw_reason": "NONE",
    })
    # drafting is itself an artwork mutation, which is what makes the OCC field bite
    touch(artwork)
    return created(record)


@bp.get("/public-art/treatment-proposals/<proposal_id>")
@endpoint(ANY_ROLE)
def read_proposal(proposal_id):
    return ok(svc.proposal_or_404(proposal_id))


@bp.get("/public-art/treatment-proposals")
@endpoint(ANY_ROLE)
def list_proposals():
    limit, offset = paging()
    rows = apply_filters(db.proposals.values(), (
        ("artwork_id", "artwork_id", "string"),
        ("conservator_id", "conservator_id", "string"),
        ("assessment_id", "assessment_id", "string"),
        ("status", "status", "string"),
        ("withdraw_reason", "withdraw_reason", "string"),
    ))
    return listing(ordered(rows), limit, offset)


@bp.post("/public-art/treatment-proposals/<proposal_id>/line-items")
@endpoint(("ChiefConservator",))
def append_line_item(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    body = parse_input({
        "labor_hours": field("number", required=True, minimum=0),
        "complexity_class": field("enum", required=True, enum=TREATMENT_SCOPES),
        "materials_cents": field("int", required=True, minimum=0),
        "description": field("string"),
    })
    svc.require_state(
        proposal["status"], ("DRAFT", "REVISION_REQUESTED"), "ERR_PROPOSAL_INVALID_STATE"
    )
    conservator = db.conservators.get(proposal["conservator_id"])
    rate = int(conservator["hourly_rate_cents"]) if conservator else 0
    labor_cents = calc.line_labor_cents(body["labor_hours"], rate, body["complexity_class"])
    line = {
        "labor_hours": body["labor_hours"],
        "complexity_class": body["complexity_class"],
        "materials_cents": body["materials_cents"],
        "labor_cents": labor_cents,
        "line_total_cents": labor_cents + int(body["materials_cents"]),
    }
    proposal["line_items"].append(line)
    proposal.update(calc.estimate_breakdown(proposal["line_items"]))
    touch(proposal)
    return ok(proposal)


@bp.post("/public-art/treatment-proposals/<proposal_id>/submit")
@endpoint(("ChiefConservator",))
def submit_proposal(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    parse_input({"submitter_note": field("string")})
    svc.require_state(
        proposal["status"], ("DRAFT", "REVISION_REQUESTED"), "ERR_PROPOSAL_INVALID_STATE"
    )
    if not proposal["line_items"]:
        raise ApiError(
            "ERR_PROPOSAL_INVALID_STATE", "A proposal cannot be submitted with no cost lines."
        )
    if proposal["status"] == "DRAFT":
        svc.require_in_collection(svc.artwork_or_404(proposal["artwork_id"]))
    proposal["status"] = "SUBMITTED"
    proposal["submitted_by_user_id"] = g.user_id
    touch(proposal)
    return ok(proposal)


@bp.post("/public-art/treatment-proposals/<proposal_id>/request-revision")
@endpoint(("PublicArtManager",))
def request_proposal_revision(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    parse_input({"reviewer_note": field("string", required=True)})
    svc.require_state(proposal["status"], ("SUBMITTED",), "ERR_PROPOSAL_INVALID_STATE")
    if int(proposal["revision_rounds"]) >= calc.MAX_REVISION_ROUNDS:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")
    proposal["status"] = "REVISION_REQUESTED"
    proposal["revision_rounds"] = int(proposal["revision_rounds"]) + 1
    touch(proposal)
    return ok(proposal)


def _consent_gate(proposal, artwork):
    """PRD 3.5 first gate, in the graduated order of PRD 2.8 steps 15-17."""
    if not proposal.get("alters_appearance"):
        return
    if artwork["moral_rights_status"] != "ACTIVE":
        return
    linked = [
        c for c in ordered(db.consultations.values()) if c.get("proposal_id") == proposal["id"]
    ]
    if not linked:
        raise ApiError("ERR_ARTIST_CONSULTATION_REQUIRED")
    statuses = [c["status"] for c in linked]
    if "CONCURRED" in statuses or "LAPSED" in statuses:
        if "OBJECTED" in statuses:
            raise ApiError("ERR_ARTIST_OBJECTION_UNRESOLVED")
        return
    if "PENDING" in statuses:
        raise ApiError("ERR_ARTIST_CONSULTATION_PENDING")
    if "OBJECTED" in statuses:
        raise ApiError("ERR_ARTIST_OBJECTION_UNRESOLVED")


def _eligibility_gate(proposal, artwork, conservator):
    if conservator is None or conservator["status"] != "ACTIVE":
        raise ApiError("ERR_CONSERVATOR_NOT_ELIGIBLE")
    if parse_date(conservator["insurance_expires_on"]) < parse_date(proposal["engagement_end"]):
        raise ApiError("ERR_CONSERVATOR_NOT_ELIGIBLE")
    if artwork["material_class"] not in (conservator.get("material_specialties") or []):
        raise ApiError("ERR_CONSERVATOR_NOT_ELIGIBLE")


def _exclusivity_gate(proposal):
    """Conservator windows are HALF-OPEN and padded by 48 hours on both sides."""
    buffer = timedelta(hours=calc.CONSERVATOR_BUFFER_HOURS)
    start = parse_instant(proposal["engagement_start"])
    end = parse_instant(proposal["engagement_end"])
    for other in db.proposals.values():
        if other["id"] == proposal["id"]:
            continue
        if other["conservator_id"] != proposal["conservator_id"]:
            continue
        if other["status"] not in svc.ENGAGED_STATUSES:
            continue
        other_start = parse_instant(other["engagement_start"])
        other_end = parse_instant(other["engagement_end"])
        if start < other_end + buffer and other_start < end + buffer:
            raise ApiError("ERR_CONSERVATOR_WINDOW_CONFLICT")


def _funding_gate(proposal):
    for alloc in db.allocations.values():
        if (
            alloc.get("proposal_id") == proposal["id"]
            and alloc["status"] == "RESERVED"
            and int(alloc["amount_cents"]) >= int(proposal["estimate_total_cents"])
        ):
            return alloc
    raise ApiError("ERR_FUNDING_NOT_RESERVED")


@bp.post("/public-art/treatment-proposals/<proposal_id>/approve")
@endpoint(("PublicArtManager",))
def approve_proposal(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    parse_input({"approval_note": field("string")})
    svc.require_state(proposal["status"], ("SUBMITTED",), "ERR_PROPOSAL_INVALID_STATE")
    artwork = svc.artwork_or_404(proposal["artwork_id"])
    svc.require_in_collection(artwork)
    _consent_gate(proposal, artwork)
    conservator = db.conservators.get(proposal["conservator_id"])
    _eligibility_gate(proposal, artwork, conservator)
    _exclusivity_gate(proposal)
    _funding_gate(proposal)

    proposal["status"] = "APPROVED"
    proposal["pinned_estimate_total_cents"] = int(proposal["estimate_total_cents"])
    proposal["approved_by_user_id"] = g.user_id
    touch(proposal)
    svc.recompute_engagement_count(conservator)
    svc.cascade_c(proposal, artwork)
    return ok(proposal)


@bp.post("/public-art/treatment-proposals/<proposal_id>/reject")
@endpoint(("PublicArtManager",))
def reject_proposal(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    parse_input({"rejection_reason": field("string", required=True)})
    svc.require_state(proposal["status"], ("SUBMITTED",), "ERR_PROPOSAL_INVALID_STATE")
    proposal["status"] = "REJECTED"
    touch(proposal)
    for alloc in svc.allocations_for_proposal(proposal["id"]):
        svc.release_allocation(alloc, "PROPOSAL_REJECTED")
    return ok(proposal)


@bp.post("/public-art/treatment-proposals/<proposal_id>/start-execution")
@endpoint(("ConservatorVendor",))
def start_execution(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    parse_input({"mobilization_note": field("string")})
    require_owner(proposal["conservator_id"])
    svc.require_state(proposal["status"], ("APPROVED",), "ERR_PROPOSAL_INVALID_STATE")
    artwork = svc.artwork_or_404(proposal["artwork_id"])
    svc.require_in_collection(artwork)
    if artwork["custody_status"] not in ("ON_VIEW", "IN_STORAGE"):
        raise ApiError("ERR_ARTWORK_CUSTODY_INVALID")
    for visit in db.visits.values():
        if visit["artwork_id"] == artwork["id"] and visit["status"] == "IN_PROGRESS":
            raise ApiError(
                "ERR_ARTWORK_CUSTODY_INVALID",
                "A maintenance visit on this work is currently in progress.",
            )

    proposal["status"] = "IN_EXECUTION"
    touch(proposal)
    artwork["custody_status"] = "IN_TREATMENT"
    if artwork["conservation_status"] == "TREATMENT_REQUIRED":
        artwork["conservation_status"] = "TREATMENT_IN_PROGRESS"
    touch(artwork)
    svc.recompute_site_units(svc.site_of(artwork))
    svc.recompute_ranks()
    svc.advance_allocations(
        svc.allocations_for_proposal(proposal["id"]), "RESERVED", "COMMITTED"
    )
    return ok(proposal)


@bp.post("/public-art/treatment-proposals/<proposal_id>/complete")
@endpoint(("ConservatorVendor",))
def complete_execution(proposal_id):
    proposal = svc.proposal_or_404(proposal_id)
    parse_input({"completion_report_ref": field("string", required=True)})
    require_owner(proposal["conservator_id"])
    svc.require_state(proposal["status"], ("IN_EXECUTION",), "ERR_PROPOSAL_INVALID_STATE")
    artwork = svc.artwork_or_404(proposal["artwork_id"])
    svc.require_in_collection(artwork)

    proposal["status"] = "COMPLETED"
    touch(proposal)

    artwork["custody_status"] = "ON_VIEW"
    artwork["conservation_status"] = "STABILIZED"
    artwork["treatment_priority_score"] = None
    artwork["treatment_priority_rank"] = None
    artwork["priority_basis"] = "NONE"
    touch(artwork)
    svc.recompute_site_units(svc.site_of(artwork))
    svc.recompute_ranks()

    svc.advance_allocations(
        svc.allocations_for_proposal(proposal["id"]), "COMMITTED", "DISBURSED"
    )
    svc.recompute_engagement_count(db.conservators.get(proposal["conservator_id"]))

    for incident in ordered(db.incidents.values()):
        if (
            incident.get("linked_proposal_id") == proposal["id"]
            and incident["damage_status"] == "TRIAGED"
        ):
            incident["damage_status"] = "RESOLVED"
            touch(incident)

    return ok(proposal)
