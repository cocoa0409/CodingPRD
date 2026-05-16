"""System endpoints: /_clock and /_clock/advance."""

from datetime import timedelta
from flask import Blueprint, request, g

from core.auth import require_roles
from core.clock import CLOCK, iso_format, parse_iso
from core.envelope import success_object
from core.errors import raise_error
from core.models import mark_mutated
from core.store import STORE, lock
from core.validation import require_body, require_field
from services.calculations import compute_penalty_points
from services.cascades import cascade_violation_sustained


bp = Blueprint("system", __name__)


@bp.route("/_clock", methods=["GET"])
def get_clock():
    return success_object({"now": CLOCK.now_iso()})


@bp.route("/_clock/advance", methods=["POST"])
@require_roles("ComplianceOfficer", "Auditor")
def advance_clock():
    body = require_body(request)
    to_ts = require_field(body, "to_timestamp", kind="string")
    try:
        target = parse_iso(to_ts)
    except ValueError:
        raise_error("ERR_VALIDATION_FAILED", "to_timestamp must be ISO 8601")

    with lock():
        auto_transitions = []
        # If target is not after current, do nothing other than refresh now.
        moved = CLOCK.advance_to(target)
        if not moved:
            return success_object({"now": CLOCK.now_iso(), "auto_transitions": []})

        now = CLOCK.now()

        # (1) TransferPortalEntry ENTERED -> CONTACT_WINDOW (entered_at + 24h elapsed)
        entries_to_open = []
        for e in STORE.transfer_portal_entries.values():
            if e.get("status") != "ENTERED":
                continue
            entered_at = parse_iso(e["entered_at"])
            if now >= entered_at + timedelta(hours=24):
                entries_to_open.append(e)
        entries_to_open.sort(key=lambda x: (x["entered_at"], x["_seq"]))
        for e in entries_to_open:
            e["status"] = "CONTACT_WINDOW"
            mark_mutated(e)
            auto_transitions.append({
                "entity": "TransferPortalEntry",
                "id": e["id"],
                "from": "ENTERED",
                "to": "CONTACT_WINDOW",
            })

        # (2) ComplianceViolation SUBSTANTIATED -> SUSTAINED (auto-expire after 14d)
        v_to_sustain = []
        for v in STORE.compliance_violations.values():
            if v.get("status") != "SUBSTANTIATED":
                continue
            sub_at = STORE.substantiated_at.get(v["id"])
            if sub_at is None:
                continue
            if now - sub_at >= timedelta(days=14):
                v_to_sustain.append((v, sub_at))
        v_to_sustain.sort(key=lambda x: (x[1], x[0]["_seq"]))
        for v, _sub_at in v_to_sustain:
            v["status"] = "SUSTAINED"
            # Compute penalty points & cascade.
            v["penalty_points"] = compute_penalty_points(
                v, list(STORE.compliance_violations.values())
            )
            cascade_violation_sustained(v)
            auto_transitions.append({
                "entity": "ComplianceViolation",
                "id": v["id"],
                "from": "SUBSTANTIATED",
                "to": "SUSTAINED",
            })

        # (3) TransferPortalEntry CONTACT_WINDOW -> EXPIRED (window_closes_at crossed)
        entries_to_expire = []
        for e in STORE.transfer_portal_entries.values():
            if e.get("status") != "CONTACT_WINDOW":
                continue
            wc = parse_iso(e["window_closes_at"])
            if now >= wc:
                entries_to_expire.append(e)
        entries_to_expire.sort(key=lambda x: (x["window_closes_at"], x["_seq"]))
        for e in entries_to_expire:
            e["status"] = "EXPIRED"
            mark_mutated(e)
            auto_transitions.append({
                "entity": "TransferPortalEntry",
                "id": e["id"],
                "from": "CONTACT_WINDOW",
                "to": "EXPIRED",
            })

        return success_object({
            "now": CLOCK.now_iso(),
            "auto_transitions": auto_transitions,
        })
