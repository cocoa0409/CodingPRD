"""/transfer-portal-entries endpoints."""

from datetime import timedelta
from flask import Blueprint, request, g

from core.auth import require_roles
from core.clock import CLOCK, iso_format, parse_iso
from core.envelope import success_object, success_array
from core.errors import raise_error
from core.models import make_entity, mark_mutated, serialize, serialize_list
from core.store import STORE, lock
from core.validation import (
    require_body,
    require_field,
    require_enum,
    parse_pagination,
    check_version,
)
from services.aggregates import recompute_program_aggregates
from services.calculations import (
    compute_immediate_eligibility,
    transfer_window_hours,
)
from services.cascades import cascade_enter_portal


bp = Blueprint("transfer_portal", __name__)


VALID_REASONS = {"PLAYING_TIME", "COACHING_CHANGE", "FAMILY", "ACADEMIC", "OTHER"}
VALID_STATUSES = {"ENTERED", "CONTACT_WINDOW", "COMMITTED", "WITHDRAWN", "EXPIRED"}


@bp.route("/transfer-portal-entries", methods=["POST"])
@require_roles("Athlete", "ComplianceOfficer")
def create_entry():
    body = require_body(request)
    athlete_id = require_field(body, "athlete_id", kind="string")
    reason = require_enum(body, "reason", VALID_REASONS)

    with lock():
        athlete = STORE.athletes.get(athlete_id)
        if athlete is None:
            raise_error("ERR_REFERENCE_NOT_FOUND", "Athlete not found")
        # Athlete role: must be self
        if g.user_role == "Athlete" and g.user_id != athlete_id:
            raise_error("ERR_FORBIDDEN", "Athlete may only enter portal for self")

        # State must be ENROLLED
        if athlete.get("status") != "ENROLLED":
            raise_error("ERR_INVALID_STATE", "Athlete must be ENROLLED to enter portal")

        # Priority 20: no active portal entry
        for e in STORE.transfer_portal_entries.values():
            if e.get("athlete_id") == athlete_id and e.get("status") in ("ENTERED", "CONTACT_WINDOW"):
                raise_error("ERR_DUPLICATE_PORTAL_ENTRY", "Athlete already has an active portal entry")

        # No UNDER_REVIEW NIL deal
        for d in STORE.nil_deals.values():
            if d.get("athlete_id") == athlete_id and d.get("status") == "UNDER_REVIEW":
                raise_error("ERR_PENDING_NIL_REVIEW", "Athlete has a NIL deal under review")

        # FORFEITED -> ineligible
        window_hours = transfer_window_hours(athlete.get("amateur_status", "AMATEUR"))
        if window_hours == 0:
            raise_error("ERR_PORTAL_INELIGIBLE", "Athlete amateur_status FORFEITED — cannot enter portal")

        # Build entry
        now = CLOCK.now()
        entered_at = now
        closes_at = entered_at + timedelta(hours=window_hours)
        origin_pid = athlete.get("current_program_id")
        entry = make_entity("TransferPortalEntry", {
            "athlete_id": athlete_id,
            "origin_program_id": origin_pid,
            "destination_program_id": None,
            "entered_at": iso_format(entered_at),
            "window_closes_at": iso_format(closes_at),
            "reason": reason,
            "status": "ENTERED",
            "immediate_eligibility": False,
        })
        STORE.transfer_portal_entries[entry["id"]] = entry

        # Cascade: release active slots; clear athlete current_program_id; athlete -> TRANSFER_PORTAL
        cascade_enter_portal(athlete)

        return success_object(serialize(entry), status=201)


@bp.route("/transfer-portal-entries/<entry_id>", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Athlete", "Auditor")
def get_entry(entry_id):
    with lock():
        e = STORE.transfer_portal_entries.get(entry_id)
        if not e:
            raise_error("ERR_NOT_FOUND", "TransferPortalEntry not found")
        if g.user_role == "Athlete" and e.get("athlete_id") != g.user_id:
            raise_error("ERR_FORBIDDEN", "Athlete may only read own entries")
        return success_object(serialize(e))


@bp.route("/transfer-portal-entries", methods=["GET"])
@require_roles("ComplianceOfficer", "Coach", "Auditor", "Athlete")
def list_entries():
    limit, offset = parse_pagination(request)
    status = request.args.get("status")
    athlete_id = request.args.get("athlete_id")
    origin_pid = request.args.get("origin_program_id")

    with lock():
        items = list(STORE.transfer_portal_entries.values())
        if g.user_role == "Athlete":
            items = [e for e in items if e.get("athlete_id") == g.user_id]
        if status:
            items = [e for e in items if e.get("status") == status]
        if athlete_id:
            items = [e for e in items if e.get("athlete_id") == athlete_id]
        if origin_pid:
            items = [e for e in items if e.get("origin_program_id") == origin_pid]
        items.sort(key=lambda e: (e["created_at"], e["_seq"]))
        total = len(items)
        page = items[offset:offset + limit]
        return success_array(serialize_list(page), limit, offset, total)


@bp.route("/transfer-portal-entries/<entry_id>/state", methods=["POST"])
@require_roles("ComplianceOfficer", "Athlete")
def transition_entry(entry_id):
    body = require_body(request)
    to_status = require_enum(body, "to_status", VALID_STATUSES)

    with lock():
        e = STORE.transfer_portal_entries.get(entry_id)
        if not e:
            raise_error("ERR_NOT_FOUND", "TransferPortalEntry not found")

        cur = e["status"]
        valid = {
            ("ENTERED", "WITHDRAWN"),
            ("CONTACT_WINDOW", "COMMITTED"),
            ("CONTACT_WINDOW", "WITHDRAWN"),
        }
        if (cur, to_status) not in valid:
            raise_error("ERR_INVALID_STATE", f"Invalid transition {cur} -> {to_status}")

        # Role-specific permissions
        # COMMITTED: ComplianceOfficer only
        # WITHDRAWN: Athlete (own) or ComplianceOfficer
        if to_status == "COMMITTED" and g.user_role != "ComplianceOfficer":
            raise_error("ERR_FORBIDDEN", "Only ComplianceOfficer can commit")
        if to_status == "WITHDRAWN":
            if g.user_role == "Athlete" and e.get("athlete_id") != g.user_id:
                raise_error("ERR_FORBIDDEN", "Athlete may only withdraw own entry")

        check_version(body, e["version"])

        athlete = STORE.athletes.get(e["athlete_id"])

        if (cur, to_status) == ("CONTACT_WINDOW", "COMMITTED"):
            # Required destination_program_id
            destination_pid = require_field(body, "destination_program_id", kind="string")
            prog = STORE.programs.get(destination_pid)
            if prog is None:
                raise_error("ERR_REFERENCE_NOT_FOUND", "Destination program not found")
            # Window check
            wc = parse_iso(e["window_closes_at"])
            if CLOCK.now() >= wc:
                raise_error("ERR_PORTAL_WINDOW_CLOSED", "Portal window has closed")
            # Recipient program must have SIGNED slot for this athlete
            matching_slot = None
            for s in STORE.scholarship_slots.values():
                if (
                    s.get("athlete_id") == e["athlete_id"]
                    and s.get("program_id") == destination_pid
                    and s.get("status") == "SIGNED"
                ):
                    matching_slot = s
                    break
            if matching_slot is None:
                raise_error("ERR_NO_SIGNED_SLOT", "Recipient program has no SIGNED slot for athlete")
            # Scholarship cap projection — slot is SIGNED already, so cap is satisfied since cap was checked at SIGNED.
            # But §2.8 lists priority 16 here as well; reaffirm.
            from services.money import round_two_dp
            current_used = float(prog.get("total_equivalencies_used", 0))
            cap = float(prog["scholarship_cap_equivalencies"])
            if current_used > cap:
                raise_error("ERR_SCHOLARSHIP_CAP_EXCEEDED", "Scholarship cap would be exceeded")
            # Roster cap projection
            current_count = sum(
                1 for a in STORE.athletes.values()
                if a.get("status") == "ENROLLED" and a.get("current_program_id") == destination_pid
            )
            if current_count + 1 > int(prog["roster_cap_count"]):
                raise_error("ERR_ROSTER_CAP_EXCEEDED", "Roster cap would be exceeded")

            # Commit
            e["status"] = "COMMITTED"
            e["destination_program_id"] = destination_pid
            mark_mutated(e)
            # Cascade: Athlete TRANSFER_PORTAL -> COMMITTED with current_program_id = destination
            # Then enroll the athlete because §3.4 says "cascades enrollment" — but reading PRD again:
            # "this in turn triggers the Athlete TRANSFER_PORTAL → COMMITTED transition", and the
            # roster-cap check that we just did "applies to the recipient program on portal
            # CONTACT_WINDOW → COMMITTED, which itself cascades enrollment". So we do cascade enrollment.
            athlete["status"] = "ENROLLED"  # cascade includes enrollment
            athlete["current_program_id"] = destination_pid
            mark_mutated(athlete)
            # Activate the SIGNED slot
            matching_slot["status"] = "ACTIVE"
            matching_slot["activated_at"] = CLOCK.now_iso()
            mark_mutated(matching_slot)
            recompute_program_aggregates(destination_pid)
            # Compute immediate_eligibility now that COMMITTED is final
            e["immediate_eligibility"] = compute_immediate_eligibility(
                e, athlete, list(STORE.transfer_portal_entries.values())
            )
            mark_mutated(e)
            return success_object(serialize(e))

        if (cur, to_status) == ("CONTACT_WINDOW", "WITHDRAWN"):
            wc = parse_iso(e["window_closes_at"])
            if CLOCK.now() >= wc:
                raise_error("ERR_PORTAL_WINDOW_CLOSED", "Portal window has closed")
            e["status"] = "WITHDRAWN"
            mark_mutated(e)
            # Rollback athlete: TRANSFER_PORTAL -> COMMITTED at origin
            if athlete is not None:
                athlete["status"] = "COMMITTED"
                athlete["current_program_id"] = e.get("origin_program_id")
                mark_mutated(athlete)
                # Recompute aggregates at origin (no slot is auto-recreated)
                if e.get("origin_program_id"):
                    recompute_program_aggregates(e["origin_program_id"])
            return success_object(serialize(e))

        if (cur, to_status) == ("ENTERED", "WITHDRAWN"):
            e["status"] = "WITHDRAWN"
            mark_mutated(e)
            # Rollback athlete: TRANSFER_PORTAL -> ENROLLED at origin
            if athlete is not None:
                athlete["status"] = "ENROLLED"
                athlete["current_program_id"] = e.get("origin_program_id")
                mark_mutated(athlete)
                if e.get("origin_program_id"):
                    recompute_program_aggregates(e["origin_program_id"])
            return success_object(serialize(e))
