"""Swap marketplace: post/list/get/claim/approve/decline/execute/cancel (PRD §3.4).

Cross-level ordering follows PRD §2.11 (state 6 -> safety 8 -> temporal 9 ->
constraint 10 -> fiscal 11); within a level, endpoint narrative order.
"""
from decimal import Decimal

from flask import Blueprint

import db
import validation as V
from db import store
from errors import ApiError
from middleware import require_roles, ownership_violation
from response import ok, created, paginate
from services import domain as D
from routes.assignments import get_assignment_or_404
from routes.physicians import get_physician_or_404

bp = Blueprint("swaps", __name__)

ALL = ["SchedulerAdmin", "ChiefOfStaff", "Physician", "CredentialingOfficer"]


def get_swap_or_404(swap_id):
    swap = store.swaps.get(swap_id)
    if swap is None:
        raise ApiError("ERR_SWAP_NOT_FOUND", 404, "SwapRequest id does not exist")
    return swap


def _check_claimant_eligibility(swap, claimant):
    """Execute-time claimant eligibility re-check (scaffold order):
    unavailability, overlap, moonlight cap."""
    assignment = get_assignment_or_404(swap["assignment_id"])
    slot = D.slot_of(assignment)
    program = store.programs.get(swap["program_id"])
    if D.has_approved_window_covering(claimant["id"], slot["date"]):
        raise ApiError("ERR_UNAVAILABILITY_CONFLICT", 409,
                       "An APPROVED unavailability window covers the slot date")
    if D.has_overlapping_assignment(claimant["id"], slot):
        raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                       "Claimant holds an assignment whose half-open window overlaps")
    D.check_moonlight_cap(claimant, slot["date"])
    return assignment, slot, program


@bp.route("/api/swap-requests", methods=["POST"])
def create_swap():
    uid, role = require_roles(["Physician"])
    body = V.json_body()
    assignment_id = V.req_str(body, "assignment_id")
    assignment = get_assignment_or_404(assignment_id)
    # Ownership (priority 3): the offered assignment must belong to the caller.
    if assignment["physician_id"] != uid:
        ownership_violation("A Physician may offer only their own assignments for swap")
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED", 409,
                       "The offered assignment must be SCHEDULED")
    program = store.programs.get(assignment["program_id"])
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED", 409,
                       "Swap posting requires the program PUBLISHED")
    for sw in store.swaps.values():
        if sw["assignment_id"] == assignment["id"] \
                and sw["status"] in D.NON_TERMINAL_SWAP_STATUSES:
            raise ApiError("ERR_DUPLICATE_ACTIVE_SWAP", 409,
                           "The assignment already has a swap in POSTED, CLAIMED, or APPROVED")
    swap = db.new_common({
        "program_id": assignment["program_id"],
        "assignment_id": assignment["id"],
        "offerer_physician_id": assignment["physician_id"],
        "claimant_physician_id": None,
        "decline_reason": None,
        "status": "POSTED",
    })
    store.swaps[swap["id"]] = swap
    return created(swap)


@bp.route("/api/swap-requests", methods=["GET"])
def list_swaps():
    require_roles(ALL)
    rows = list(store.swaps.values())
    rows = paginate.filter(rows, "program_id")
    rows = paginate.filter(rows, "assignment_id")
    rows = paginate.filter(rows, "offerer_physician_id")
    rows = paginate.filter(rows, "claimant_physician_id")
    rows = paginate.filter(rows, "status")
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.route("/api/swap-requests/<swap_id>", methods=["GET"])
def get_swap(swap_id):
    require_roles(ALL)
    return ok(get_swap_or_404(swap_id))


@bp.route("/api/swap-requests/<swap_id>/claim", methods=["POST"])
def claim_swap(swap_id):
    uid, role = require_roles(["Physician"])
    V.json_body()
    swap = get_swap_or_404(swap_id)
    claimant = get_physician_or_404(uid)  # Physician role identity is entity-backed
    if swap["status"] != "POSTED":
        raise ApiError("ERR_SWAP_NOT_POSTED", 409, "claim requires the swap POSTED")
    assignment = get_assignment_or_404(swap["assignment_id"])
    slot = D.slot_of(assignment)
    program = store.programs.get(swap["program_id"])
    # Claimant guard order per PRD §3.4 narrative / scaffold preconditions:
    # STAFF, ACTIVE, != offerer, specialty, unavailability, overlap, cap, cutoff.
    if claimant["employment_type"] != "STAFF":
        raise ApiError("ERR_SWAP_CLAIMANT_INELIGIBLE", 409,
                       "Swap claimant is not a STAFF physician")
    if claimant["status"] != "ACTIVE":
        raise ApiError("ERR_PHYSICIAN_INACTIVE", 409,
                       "An INACTIVE physician cannot take a new commitment")
    if claimant["id"] == swap["offerer_physician_id"]:
        raise ApiError("ERR_SELF_SWAP", 409, "Claimant equals the offerer")
    if claimant["specialty"] != program["service_line"]:
        raise ApiError("ERR_SPECIALTY_MISMATCH", 409,
                       "Claimant specialty != program.service_line")
    if D.has_approved_window_covering(claimant["id"], slot["date"]):
        raise ApiError("ERR_UNAVAILABILITY_CONFLICT", 409,
                       "An APPROVED unavailability window covers the slot date")
    if D.has_overlapping_assignment(claimant["id"], slot):
        raise ApiError("ERR_ASSIGNMENT_OVERLAP", 409,
                       "Claimant holds an assignment whose half-open window overlaps")
    D.check_moonlight_cap(claimant, slot["date"])
    # window_start - now >= swap_cutoff_hours, equality allowed.
    cutoff = (slot["window_start"] - db.now_logical()).total_seconds()
    if cutoff < int(program["swap_cutoff_hours"]) * 3600:
        raise ApiError("ERR_SWAP_CUTOFF_VIOLATION", 409,
                       "Claim later than swap_cutoff_hours before slot.window_start")
    swap["claimant_physician_id"] = uid
    swap["status"] = "CLAIMED"
    db.touch(swap)
    return ok(swap)


@bp.route("/api/swap-requests/<swap_id>/approve", methods=["POST"])
def approve_swap(swap_id):
    require_roles(["ChiefOfStaff"])
    V.json_body()
    swap = get_swap_or_404(swap_id)
    if swap["status"] != "CLAIMED":
        raise ApiError("ERR_SWAP_NOT_CLAIMED", 409, "approve requires the swap CLAIMED")
    assignment = get_assignment_or_404(swap["assignment_id"])
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED", 409,
                       "The referenced assignment must still be SCHEDULED")
    program = store.programs.get(swap["program_id"])
    if program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED", 409,
                       "Swap approval requires the program PUBLISHED")
    _equity_check(swap, assignment, program)
    swap["status"] = "APPROVED"
    db.touch(swap)
    return ok(swap)


def _equity_check(swap, assignment, program):
    """Post-swap prospective points: claimant credited with the slot's points,
    offerer relieved. Breach when claimant_after > mean_after + equity_band_points
    (strictly greater; equality permitted). Population recomputed post-swap."""
    slot = D.slot_of(assignment)
    sp = D.slot_points(program, slot)
    claimant_id = swap["claimant_physician_id"]
    offerer_id = swap["offerer_physician_id"]
    totals = D.program_point_totals(program)
    # Post-swap qualifying-assignment counts (prospective status set).
    counts = {}
    for a in store.assignments.values():
        if a["program_id"] == program["id"] and a["status"] in D.PROSPECTIVE_STATUSES:
            counts[a["physician_id"]] = counts.get(a["physician_id"], 0) + 1
    counts[offerer_id] = counts.get(offerer_id, 0) - 1   # original leaves the set
    counts[claimant_id] = counts.get(claimant_id, 0) + 1  # replacement enters it
    claimant_after = totals.get(claimant_id, [Decimal("0")])[0] + sp
    total_after = sum((v[0] for v in totals.values()), Decimal("0"))  # points move; sum unchanged
    population_after = sum(1 for c in counts.values() if c >= 1)
    if population_after <= 0:
        return
    mean_after = D.two_dp(total_after / population_after)
    if claimant_after > mean_after + Decimal(program["equity_band_points"]):
        raise ApiError("ERR_SWAP_EQUITY_BREACH", 409,
                       "Approval would push the claimant beyond mean + equity_band_points")


@bp.route("/api/swap-requests/<swap_id>/decline", methods=["POST"])
def decline_swap(swap_id):
    require_roles(["ChiefOfStaff"])
    body = V.json_body()
    decline_reason = V.opt_str(body, "decline_reason", None)
    swap = get_swap_or_404(swap_id)
    if swap["status"] != "CLAIMED":
        raise ApiError("ERR_SWAP_NOT_CLAIMED", 409, "decline requires the swap CLAIMED")
    swap["status"] = "POSTED"
    swap["claimant_physician_id"] = None
    swap["decline_reason"] = decline_reason
    db.touch(swap)
    return ok(swap)


@bp.route("/api/swap-requests/<swap_id>/execute", methods=["POST"])
def execute_swap(swap_id):
    require_roles(["SchedulerAdmin"])
    V.json_body()
    swap = get_swap_or_404(swap_id)
    if swap["status"] != "APPROVED":
        raise ApiError("ERR_SWAP_NOT_APPROVED", 409, "execute requires the swap APPROVED")
    assignment = get_assignment_or_404(swap["assignment_id"])
    if assignment["status"] != "SCHEDULED":
        raise ApiError("ERR_SWAP_ASSIGNMENT_NOT_SCHEDULED", 409,
                       "The referenced assignment must still be SCHEDULED")
    claimant = get_physician_or_404(swap["claimant_physician_id"])
    slot = D.slot_of(assignment)
    program = store.programs.get(swap["program_id"])
    # Scaffold execute order: slot window_start strictly in the future, then the
    # claimant eligibility re-check (unavailability, overlap, moonlight cap).
    if not (slot["window_start"] > db.now_logical()):
        raise ApiError("ERR_SLOT_WINDOW_PASSED", 409,
                       "The slot window start is not in the future")
    _assignment, slot, program = _check_claimant_eligibility(swap, claimant)
    # Fiscal gate (priority 11) on the replacement's projected pay.
    projected = D.compute_projected_pay(program, slot, claimant)
    D.check_payroll_budget(program, projected)
    # Execute: original -> SWAPPED; replacement created for claimant (origin SWAP);
    # slot stays ASSIGNED; reserve adjusts; program version +1.
    assignment["status"] = "SWAPPED"
    db.touch(assignment)
    D.create_assignment(program, slot, claimant, "SWAP", source_swap_id=swap["id"])
    # Any other non-terminal swap referencing the (now swapped) assignment cancels.
    D.cancel_non_terminal_swaps_for_assignment(assignment["id"])
    swap["status"] = "EXECUTED"
    db.touch(swap)
    D.sync_program_totals(program)
    db.touch(program)
    return ok(swap)


@bp.route("/api/swap-requests/<swap_id>/cancel", methods=["POST"])
def cancel_swap(swap_id):
    uid, role = require_roles(["Physician"])
    V.json_body()
    swap = get_swap_or_404(swap_id)
    if swap["offerer_physician_id"] != uid:
        ownership_violation("Only the offerer may cancel the swap")
    if swap["status"] != "POSTED":
        raise ApiError("ERR_SWAP_NOT_POSTED", 409,
                       "cancel requires the swap POSTED; a CLAIMED swap must be declined first")
    swap["status"] = "CANCELLED"
    db.touch(swap)
    return ok(swap)
