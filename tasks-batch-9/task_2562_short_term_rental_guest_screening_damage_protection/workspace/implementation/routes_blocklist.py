"""Blocklist entries and the adjudication sweep (PRD 3.9 / 3.10)."""

from flask import Blueprint, g

import calc
import views
from core import (ALL_ROLES, ROLE_ADJUDICATOR, ROLE_ADMIN, ROLE_COMPLIANCE,
                  ROLE_GUEST, ROLE_HOST, body_json, db, fail, hours, new_row,
                  now, object_response, opt_string, paginate, qs, req_enum,
                  req_int, req_string, require_auth, require_owner, sort_rows,
                  touch)

bp = Blueprint("blocklist", __name__)

SCOPES = ("PROPERTY", "HOST", "PLATFORM")
SCOPE_BREADTH = {"PROPERTY": 1, "HOST": 2, "PLATFORM": 3}
REASON_CODES = ("SUBSTANTIATED_INCIDENT", "APPROVED_CLAIM",
                "RISK_TIER_CRITICAL", "LAW_ENFORCEMENT_ESCALATION")
STATEMENT_CODES = ("NOT_THE_GUEST", "FACTS_DISPUTED", "REMEDIED")
DISPUTE_REASONS = ("GROUNDS_CONFIRMED", "GROUNDS_WITHDRAWN", "IDENTITY_ERROR")


def grounds_met(guest_row, reason_code):
    if reason_code == "SUBSTANTIATED_INCIDENT":
        return calc.substantiated_incident_count(guest_row) >= 1
    if reason_code == "APPROVED_CLAIM":
        return guest_row["approved_claim_count"] >= 1
    if reason_code == "RISK_TIER_CRITICAL":
        return calc.risk_tier(guest_row) == "CRITICAL"
    return calc.escalated_incident_count(guest_row) >= 1


@bp.route("/rentals/blocklist-entries", methods=["POST"])
def create_blocklist_entry():
    user_id, role = require_auth(ROLE_HOST, ROLE_COMPLIANCE)
    body = body_json()
    guest_id = req_string(body, "guest_id")
    scope = req_enum(body, "scope", SCOPES)
    property_id = opt_string(body, "property_id")
    host_id = opt_string(body, "host_id")
    supersedes_entry_id = opt_string(body, "supersedes_entry_id")
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    expected_guest_version = req_int(body, "expected_guest_version")

    # Only a ComplianceOfficer may write PLATFORM breadth.
    if scope == "PLATFORM" and role != ROLE_COMPLIANCE:
        fail("ERR_UNAUTHORIZED",
             "Only a ComplianceOfficer may write a PLATFORM-scope ban")

    # Body reference existence in entity field declaration order.
    guest_row = db.guests.get(guest_id)
    if guest_row is None:
        fail("ERR_GUEST_NOT_FOUND", "Guest not found")
    if property_id is not None and property_id not in db.properties:
        fail("ERR_PROPERTY_NOT_FOUND", "Property not found")
    if host_id is not None and host_id not in db.hosts:
        fail("ERR_HOST_NOT_FOUND", "Host not found")
    superseded = None
    if supersedes_entry_id is not None:
        superseded = db.blocklist_entries.get(supersedes_entry_id)
        if superseded is None:
            fail("ERR_BLOCKLIST_ENTRY_NOT_FOUND", "Blocklist entry not found")
    if expected_guest_version != guest_row["version"]:
        fail("ERR_GUEST_VERSION_STALE",
             "expected_guest_version does not match the guest")

    # 1. Scope and target must agree.
    if scope == "PROPERTY" and (property_id is None or host_id is not None):
        fail("ERR_SCOPE_TARGET_MISMATCH",
             "A PROPERTY ban needs a property_id and a null host_id")
    if scope == "HOST" and (host_id is None or property_id is not None):
        fail("ERR_SCOPE_TARGET_MISMATCH",
             "A HOST ban needs a host_id and a null property_id")
    if scope == "PLATFORM" and (property_id is not None
                                or host_id is not None):
        fail("ERR_SCOPE_TARGET_MISMATCH",
             "A PLATFORM ban leaves both property_id and host_id null")

    # 2. No standing ban at the same breadth or wider.
    breadth = SCOPE_BREADTH[scope]
    for entry in calc.guest_blocklist_entries(guest_id):
        if entry["entry_state"] not in calc.ENFORCING_STATES:
            continue
        if SCOPE_BREADTH[entry["scope"]] >= breadth:
            fail("ERR_BLOCKLIST_DUPLICATE_SCOPE",
                 "This guest is already banned at the same breadth or wider")

    # 3. Supersession must widen.
    if superseded is not None:
        if superseded["guest_id"] != guest_id \
                or superseded["entry_state"] != "ACTIVE" \
                or SCOPE_BREADTH[superseded["scope"]] >= breadth:
            fail("ERR_SUPERSEDE_NOT_BROADER",
                 "The superseded entry must be an ACTIVE, strictly narrower "
                 "entry of the same guest")

    # 4. The grounds must be evidenced.
    if not grounds_met(guest_row, reason_code):
        fail("ERR_BLOCKLIST_GROUNDS_NOT_MET",
             "The declared reason_code is not evidenced by this guest")

    row = calc.create_blocklist_row(
        guest_row, scope, reason_code, role, user_id,
        property_id=property_id, host_id=host_id, auto_generated=False)
    if superseded is not None:
        row["supersedes_entry_id"] = supersedes_entry_id
        superseded["entry_state"] = "LIFTED"
        touch(superseded)
    if scope == "PLATFORM":
        calc.cancel_future_dated_reservations(guest_row)
    touch(guest_row)
    return object_response(views.blocklist_view(row)), 201


@bp.route("/rentals/blocklist-entries/<bid>", methods=["GET"])
def get_blocklist_entry(bid):
    require_auth(*ALL_ROLES)
    row = db.blocklist_entries.get(bid)
    if row is None:
        fail("ERR_BLOCKLIST_ENTRY_NOT_FOUND", "Blocklist entry not found")
    return object_response(views.blocklist_view(row)), 200


@bp.route("/rentals/blocklist-entries", methods=["GET"])
def list_blocklist_entries():
    require_auth(*ALL_ROLES)
    rows = list(db.blocklist_entries.values())
    for param in ("guest_id", "property_id", "host_id", "supersedes_entry_id",
                  "scope", "entry_state", "dispute_window_state"):
        value = qs(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return paginate(rows, views.blocklist_view), 200


def _entry_or_404(bid):
    row = db.blocklist_entries.get(bid)
    if row is None:
        fail("ERR_BLOCKLIST_ENTRY_NOT_FOUND", "Blocklist entry not found")
    return row


@bp.route("/rentals/blocklist-entries/<bid>/dispute", methods=["POST"])
def dispute_entry(bid):
    require_auth(ROLE_GUEST)
    body = body_json()
    statement = req_enum(body, "dispute_statement_code", STATEMENT_CODES)
    b = _entry_or_404(bid)
    require_owner(b["guest_id"])
    # PRD 3.9 names exactly two gates for this action, both reported as
    # ERR_DISPUTE_WINDOW_CLOSED -- and says so explicitly for the terminal
    # EXPIRED / RESOLVED window states, so the window dimension answers first.
    if b["dispute_window_state"] != "OPEN":
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The dispute window is not OPEN")
    if now() > b["created_at"] + hours(336):
        fail("ERR_DISPUTE_WINDOW_CLOSED", "The dispute window has lapsed")
    if b["entry_state"] == "LIFTED":
        fail("ERR_ALREADY_TERMINAL", "This entry has already been lifted")
    if b["entry_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE entry can be disputed")
    b["dispute_statement_code"] = statement
    b["entry_state"] = "DISPUTED"
    b["dispute_window_state"] = "DISPUTED"
    touch(b)
    return object_response(views.blocklist_view(b)), 200


@bp.route("/rentals/blocklist-entries/<bid>/dispute-decision",
          methods=["POST"])
def decide_dispute(bid):
    require_auth(ROLE_COMPLIANCE)
    body = body_json()
    reason = req_enum(body, "dispute_reason_code", DISPUTE_REASONS)
    b = _entry_or_404(bid)
    if b["created_by_user_id"] == g.user_id:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The officer who created the entry may not rule on its dispute")
    if b["entry_state"] == "LIFTED":
        fail("ERR_ALREADY_TERMINAL", "This entry has already been lifted")
    if b["entry_state"] != "DISPUTED":
        fail("ERR_INVALID_STATE", "Only a DISPUTED entry has a dispute to rule")
    b["dispute_reason_code"] = reason
    b["dispute_decided_by_user_id"] = g.user_id
    b["dispute_window_state"] = "RESOLVED"
    if reason == "GROUNDS_CONFIRMED":
        b["entry_state"] = "ACTIVE"
        touch(b)
    else:
        b["entry_state"] = "LIFTED"
        touch(b)
        guest_row = db.guests.get(b["guest_id"])
        if guest_row is not None:
            touch(guest_row)
    return object_response(views.blocklist_view(b)), 200


@bp.route("/rentals/blocklist-entries/<bid>/lift", methods=["POST"])
def lift_entry(bid):
    require_auth(ROLE_COMPLIANCE)
    body_json()
    b = _entry_or_404(bid)
    if b["entry_state"] == "LIFTED":
        fail("ERR_ALREADY_TERMINAL", "This entry has already been lifted")
    if b["entry_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Only an ACTIVE entry can be lifted outright")
    b["entry_state"] = "LIFTED"
    touch(b)
    guest_row = db.guests.get(b["guest_id"])
    if guest_row is not None:
        touch(guest_row)
    return object_response(views.blocklist_view(b)), 200


# ---------------------------------------------------------------------------
# The adjudication sweep (PRD 3.10) -- seven phases in a pinned order against
# a single logical-clock reading.  Every deadline comparison is strict.
# ---------------------------------------------------------------------------

@bp.route("/rentals/ops/adjudication-sweep", methods=["POST"])
def adjudication_sweep():
    require_auth(ROLE_ADMIN)
    body_json()
    swept_at = now()

    report = {
        "swept_at": swept_at,
        "documents_expired": 0,
        "incidents_sla_breached": 0,
        "claims_denied_sla": 0,
        "claims_settled": 0,
        "claims_closed_denied": 0,
        "deposits_released": 0,
        "dispute_windows_expired": 0,
    }

    # Phase 1 -- identity document expiry, then the verification / risk cascade.
    for d in sort_rows(list(db.identity_documents.values())):
        if d["review_state"] not in ("PENDING", "ACCEPTED"):
            continue
        if not (d["expires_on"] < swept_at):
            continue
        d["review_state"] = "EXPIRED"
        touch(d)
        report["documents_expired"] += 1
        guest_row = db.guests.get(d["guest_id"])
        if guest_row is not None:
            touch(guest_row)
            calc.apply_risk_cascade(guest_row)

    # Phase 2 -- neighbourhood-complaint response service level.
    for i in sort_rows(list(db.incidents.values())):
        if i["incident_state"] != "OPEN":
            continue
        due = i["response_due_at"]
        if due is None or not (due < swept_at):
            continue
        if i["response_sla_breached"]:
            continue
        i["response_sla_breached"] = True
        touch(i)
        report["incidents_sla_breached"] += 1

    # Phase 3 -- adjudication service level.
    for c in sort_rows(list(db.damage_claims.values())):
        if c["claim_state"] != "UNDER_REVIEW":
            continue
        submitted = c["submitted_for_review_at"]
        if submitted is None:
            continue
        if not (submitted + hours(120) < swept_at):
            continue
        c["claim_state"] = "DENIED"
        c["sla_lapsed"] = True
        c["decision_reason_code"] = "SLA_LAPSED"
        c["decided_by_user_id"] = "system"
        c["decided_at"] = swept_at
        touch(c)
        report["claims_denied_sla"] += 1

    # Phase 4 -- settlement of decisions whose appeal window has closed.
    for c in sort_rows(list(db.damage_claims.values())):
        if c["claim_state"] not in ("APPROVED", "DENIED"):
            continue
        decided = c["decided_at"]
        if decided is None or not (decided + hours(168) < swept_at):
            continue
        if c["claim_state"] == "APPROVED":
            c["claim_state"] = "SETTLED"
            touch(c)
            report["claims_settled"] += 1
            r = db.reservations.get(c["reservation_id"])
            if r is not None and r["deposit_state"] == "APPLIED":
                r["deposit_state"] = "RELEASED"
                r["deposit_refunded_cents"] = (r["deposit_hold_cents"]
                                               - r["deposit_applied_cents"])
                touch(r)
        else:
            c["claim_state"] = "CLOSED_DENIED"
            touch(c)
            report["claims_closed_denied"] += 1

    # Phase 5 -- deposit release once the claim window has closed.
    for r in sort_rows(list(db.reservations.values())):
        if r["deposit_state"] != "HELD":
            continue
        if not (r["claim_window_ends_at"] < swept_at):
            continue
        blocked = False
        for c in db.damage_claims.values():
            if c["reservation_id"] == r["id"] and c["claim_state"] in (
                    "AWAITING_EVIDENCE", "UNDER_REVIEW", "APPEALED",
                    "APPROVED"):
                blocked = True
                break
        if blocked:
            continue
        r["deposit_state"] = "RELEASED"
        r["deposit_refunded_cents"] = r["deposit_hold_cents"]
        touch(r)
        report["deposits_released"] += 1
        guest_row = db.guests.get(r["guest_id"])
        if guest_row is not None:
            touch(guest_row)

    # Phase 6 -- blocklist dispute windows.  entry_state is untouched.
    for b in sort_rows(list(db.blocklist_entries.values())):
        if b["dispute_window_state"] != "OPEN":
            continue
        if not (b["created_at"] + hours(336) < swept_at):
            continue
        b["dispute_window_state"] = "EXPIRED"
        touch(b)
        report["dispute_windows_expired"] += 1

    # Phase 7 -- posture recomputation.  sensor_compliance_state and
    # coverage_posture are derived at read time, so they are already current;
    # this phase never reactivates a SUSPENDED listing.
    for p in db.properties.values():
        calc.sensor_compliance_state(p)
        calc.coverage_posture(p)

    return object_response(report), 200
