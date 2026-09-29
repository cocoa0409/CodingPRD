"""Draw-request cascades: the waiver axis, auto-funding, and compensation."""
from store import db, now, bump
from services.ledger import (
    draw_lien_waivers, draw_cost_entries, recompute_project,
)


def recompute_waiver_compliance(draw):
    """The waiver axis moves independently of the funding axis (PRD 3.7).
    verified_waiver_count is refreshed first in every case."""
    waivers = draw_lien_waivers(draw["id"])
    verified = len([w for w in waivers if w["status"] == "VERIFIED"])
    required = draw.get("required_waiver_count") or 0

    changed = draw.get("verified_waiver_count") != verified
    draw["verified_waiver_count"] = verified

    if verified == required:
        compliance = "COMPLETE"
    elif verified > 0:
        compliance = "PARTIAL"
    else:
        compliance = "PENDING"

    if draw.get("waiver_compliance") != compliance:
        draw["waiver_compliance"] = compliance
        changed = True
    if changed:
        bump(draw)

    if compliance == "COMPLETE" and draw["status"] == "CONDITIONALLY_APPROVED":
        fund_draw(draw)
    return draw


def fund_draw(draw):
    """CONDITIONALLY_APPROVED -> FUNDED (system auto-transition)."""
    draw["status"] = "FUNDED"
    draw["funded_at"] = now()
    bump(draw)

    for entry in draw_cost_entries(draw["id"]):
        if entry["status"] == "INCLUDED_IN_DRAW":
            entry["status"] = "PAID"
            entry["paid_at"] = now()
            bump(entry)

    project = db.projects.get(draw["project_id"])
    if project is not None:
        recompute_project(project)
    return draw


def release_draw_holdings(draw):
    """Compensation shared by the lender RETURN edge and the controller void edge:
    included cost entries go back to APPROVED and outstanding waivers are voided."""
    for entry in draw_cost_entries(draw["id"]):
        if entry["status"] == "INCLUDED_IN_DRAW":
            entry["status"] = "APPROVED"
            entry["draw_request_id"] = None
            bump(entry)

    for waiver in draw_lien_waivers(draw["id"]):
        if waiver["status"] in ("REQUESTED", "RECEIVED", "REJECTED"):
            waiver["status"] = "VOIDED"
            waiver["voided_at"] = now()
            bump(waiver)

    project = db.projects.get(draw["project_id"])
    if project is not None:
        recompute_project(project)
