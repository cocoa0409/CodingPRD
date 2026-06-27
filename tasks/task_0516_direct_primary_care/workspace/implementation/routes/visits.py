"""Visit booking + clinical/billing lifecycle (PRD §3.5, §3.6, §3.7)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
import response
import serialize
import validate
from clock import clock
from middleware import authenticate, require_roles
from routes.helpers import get_or_404, require_member_owns, require_provider_owns
from services import domain

bp = Blueprint("visits", __name__)


@bp.route("/visits", methods=["POST"])
def book_visit():
    caller = authenticate()
    require_roles(caller, {"Member"})
    data = validate.body()

    member_id = validate.require(data, "member_id", str)
    slot_id = validate.require(data, "slot_id", str)
    visit_type = validate.require(data, "visit_type", str)
    expected_slot_version = validate.require(data, "expected_slot_version", int)
    validate.enum(visit_type, {"SAME_DAY", "VIRTUAL", "ANNUAL_PHYSICAL"}, "visit_type")

    # Existence (priority 3).
    member = get_or_404("member", member_id)
    slot = get_or_404("visit_slot", slot_id)

    # Ownership: Member books for itself.
    require_member_owns(caller, member_id)

    # OCC (priority 6): expected_slot_version must match live slot version.
    if expected_slot_version != slot["version"]:
        raise errors.stale_version("Slot version is stale.")

    # Business-temporal (priority 8): slot must not be exhausted; starts < ends.
    if slot["starts_at"] >= slot["ends_at"]:
        raise errors.slot_unavailable("Slot interval is invalid.")
    cap = domain.slot_effective_capacity(slot)
    if slot["booked_count"] >= cap:
        raise errors.slot_unavailable("Slot capacity is exhausted.")

    # Member double-booking (priority 9): overlapping BOOKED/CHECKED_IN visits.
    s_start = slot["starts_at"]
    s_end = slot["ends_at"]
    for v in db.visits.values():
        if v["member_id"] != member_id:
            continue
        if v["clinical_status"] not in ("BOOKED", "CHECKED_IN"):
            continue
        other_slot = db.visit_slots.get(v["slot_id"])
        if other_slot is None:
            continue
        # half-open overlap [start, end)
        if other_slot["starts_at"] < s_end and s_start < other_slot["ends_at"]:
            raise errors.member_double_booked("Member already has an overlapping visit.")

    # Annual-physical timing (priority 10).
    if visit_type == "ANNUAL_PHYSICAL":
        due = member.get("annual_physical_due_on")
        if due is not None and not (due <= clock.now()):
            raise errors.physical_not_due("Annual physical is not yet due.")

    # provider_id copied from member's assigned PCP.
    provider_id = member.get("assigned_provider_id")

    visit = dict(db.common_fields())
    visit["id"] = db.new_id()
    visit["_seq"] = db.next_seq()
    visit["member_id"] = member_id
    visit["provider_id"] = provider_id
    visit["slot_id"] = slot_id
    visit["visit_type"] = visit_type
    visit["clinical_status"] = "BOOKED"
    visit["billing_status"] = "NOT_BILLABLE"
    visit["service_lines"] = []
    visit["checked_in_at"] = None
    db.visits[visit["id"]] = visit

    # Increment slot booked_count, recompute slot_state, bump slot version.
    domain.recompute_slot(slot)  # recompute booked_count from visits, sets state + touches (version++)

    return response.object_response(serialize.visit(visit), 201)


@bp.route("/visits/<vid>", methods=["GET"])
def get_visit(vid):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    v = get_or_404("visit", vid)
    _read_ownership(caller, v)
    return response.object_response(serialize.visit(v), 200)


@bp.route("/visits", methods=["GET"])
def list_visits():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Provider", "Member"})
    limit, offset = validate.pagination()
    member_id = request.args.get("member_id")
    provider_id = request.args.get("provider_id")
    slot_id = request.args.get("slot_id")
    clinical_status = request.args.get("clinical_status")
    billing_status = request.args.get("billing_status")

    rows = list(db.visits.values())
    if caller.role == "Member":
        rows = [r for r in rows if r["member_id"] == caller.user_id]
    elif caller.role == "Provider":
        rows = [r for r in rows if r.get("provider_id") == caller.user_id]
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if provider_id is not None:
        rows = [r for r in rows if r.get("provider_id") == provider_id]
    if slot_id is not None:
        rows = [r for r in rows if r["slot_id"] == slot_id]
    if clinical_status is not None:
        rows = [r for r in rows if r["clinical_status"] == clinical_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]

    page, total = validate.paginate(rows, limit, offset)
    return response.array_response(
        [serialize.visit(r) for r in page], limit, offset, total, 200
    )


@bp.route("/visits/<vid>/check-in", methods=["POST"])
def check_in(vid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    v = get_or_404("visit", vid)
    require_provider_owns(caller, v.get("provider_id"))

    # State (priority 5).
    if v["clinical_status"] != "BOOKED":
        raise errors.invalid_state("Visit is not BOOKED.")
    # Cross-entity eligibility (priority 7): owner ACTIVE or PAST_DUE.
    member = db.members[v["member_id"]]
    if member["membership_status"] not in ("ACTIVE", "PAST_DUE"):
        raise errors.member_not_eligible("Member is not eligible to be seen.")

    v["clinical_status"] = "CHECKED_IN"
    v["checked_in_at"] = clock.now()
    db.touch(v)
    return response.object_response(serialize.visit(v), 200)


@bp.route("/visits/<vid>/complete", methods=["POST"])
def complete(vid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    v = get_or_404("visit", vid)
    require_provider_owns(caller, v.get("provider_id"))
    data = validate.body()

    service_lines = validate.require(data, "service_lines", list)
    _validate_service_lines(service_lines)

    # State (priority 5).
    if v["clinical_status"] != "CHECKED_IN":
        raise errors.invalid_state("Visit is not CHECKED_IN.")

    v["service_lines"] = [
        {
            "service_code": line["service_code"],
            "units": line["units"],
            "unit_charge_cents": line["unit_charge_cents"],
        }
        for line in service_lines
    ]
    v["clinical_status"] = "COMPLETED"
    if v["service_lines"]:
        v["billing_status"] = "BILLABLE"
    # else billing_status stays NOT_BILLABLE
    db.touch(v)

    # Annual physical advances Member.annual_physical_due_on +365d from clock now.
    if v["visit_type"] == "ANNUAL_PHYSICAL":
        member = db.members[v["member_id"]]
        member["annual_physical_due_on"] = clock.now() + timedelta(days=365)
        db.touch(member)

    return response.object_response(serialize.visit(v), 200)


@bp.route("/visits/<vid>/cancel", methods=["POST"])
def cancel_visit(vid):
    caller = authenticate()
    require_roles(caller, {"Member"})
    v = get_or_404("visit", vid)
    require_member_owns(caller, v["member_id"])

    if v["clinical_status"] != "BOOKED":
        raise errors.invalid_state("Visit is not BOOKED.")

    v["clinical_status"] = "CANCELLED"
    db.touch(v)
    slot = db.visit_slots.get(v["slot_id"])
    if slot is not None:
        domain.recompute_slot(slot)
    return response.object_response(serialize.visit(v), 200)


@bp.route("/visits/<vid>/no-show", methods=["POST"])
def no_show(vid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    v = get_or_404("visit", vid)
    require_provider_owns(caller, v.get("provider_id"))

    if v["clinical_status"] != "BOOKED":
        raise errors.invalid_state("Visit is not BOOKED.")
    slot = db.visit_slots.get(v["slot_id"])
    # Precondition: clock now >= slot.ends_at (PRD §3.6).
    if slot is not None and clock.now() < slot["ends_at"]:
        raise errors.invalid_state("Cannot mark NO_SHOW before slot end.")

    v["clinical_status"] = "NO_SHOW"
    db.touch(v)
    if slot is not None:
        domain.recompute_slot(slot)
    return response.object_response(serialize.visit(v), 200)


@bp.route("/visits/<vid>/invoice", methods=["POST"])
def invoice_visit(vid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    v = get_or_404("visit", vid)
    require_provider_owns(caller, v.get("provider_id"))

    # State (priority 5): billing BILLABLE and clinical COMPLETED.
    if v["billing_status"] != "BILLABLE":
        raise errors.invalid_state("Visit billing_status is not BILLABLE.")
    if v["clinical_status"] != "COMPLETED":
        raise errors.invalid_state("Visit clinical_status is not COMPLETED.")

    member = db.members[v["member_id"]]
    practice = db.practices[member["practice_id"]]
    split = domain.compute_invoice_split(member, practice, v["service_lines"])

    inv = dict(db.common_fields())
    inv["id"] = db.new_id()
    inv["_seq"] = db.next_seq()
    inv["member_id"] = v["member_id"]
    inv["visit_id"] = v["id"]
    inv["gross_charge_cents"] = split["gross_charge_cents"]
    inv["dpc_covered_cents"] = split["dpc_covered_cents"]
    inv["insurance_billed_cents"] = split["insurance_billed_cents"]
    inv["member_responsibility_cents"] = split["member_responsibility_cents"]
    inv["invoice_status"] = "ISSUED"
    db.invoices[inv["id"]] = inv

    v["billing_status"] = "INVOICED"
    db.touch(v)

    return response.object_response(serialize.invoice(inv), 201)


@bp.route("/visits/<vid>/write-off", methods=["POST"])
def write_off(vid):
    caller = authenticate()
    require_roles(caller, {"Provider"})
    v = get_or_404("visit", vid)
    require_provider_owns(caller, v.get("provider_id"))

    if v["billing_status"] != "BILLABLE":
        raise errors.invalid_state("Visit billing_status is not BILLABLE.")

    v["billing_status"] = "WRITTEN_OFF"
    db.touch(v)
    return response.object_response(serialize.visit(v), 200)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_ownership(caller, visit):
    if caller.role == "Member" and caller.user_id != visit["member_id"]:
        raise errors.forbidden("Member does not own this visit.")
    if caller.role == "Provider" and caller.user_id != visit.get("provider_id"):
        raise errors.forbidden("Provider does not own this visit.")


def _validate_service_lines(service_lines):
    for line in service_lines:
        if not isinstance(line, dict):
            raise errors.invalid_request("Each service line must be an object.")
        if not isinstance(line.get("service_code"), str):
            raise errors.invalid_request("service_code must be a string.")
        units = line.get("units")
        charge = line.get("unit_charge_cents")
        if not isinstance(units, int) or isinstance(units, bool):
            raise errors.invalid_request("units must be an integer.")
        if not isinstance(charge, int) or isinstance(charge, bool):
            raise errors.invalid_request("unit_charge_cents must be an integer.")
