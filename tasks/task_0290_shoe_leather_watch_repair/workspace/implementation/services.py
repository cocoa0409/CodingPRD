"""Business-logic services: state transitions, cascades, derived recomputation.

These functions assume existence / role / state preconditions have already been
checked by the route layer where appropriate, but several preconditions specific
to a transition are enforced here.
"""
import clock
import db
import calculations as calc
from errors import ApiError


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def ticket_lines(tid):
    return [sl for sl in db.service_lines.values() if sl["ticket_id"] == tid]


def ticket_parts(tid):
    return [po for po in db.parts_orders.values() if po["ticket_id"] == tid]


def ticket_estimates(tid):
    return [e for e in db.estimates.values() if e["ticket_id"] == tid]


def recompute_amount_paid(ticket):
    ticket["amount_paid_cents"] = calc.amount_paid(ticket["id"])


def is_redo_ticket(tid):
    """True when the ticket is referenced by some WarrantyClaim.redo_ticket_id."""
    return any(c.get("redo_ticket_id") == tid for c in db.warranty_claims.values())


# ---------------------------------------------------------------------------
# Estimate present
# ---------------------------------------------------------------------------
def present_estimate(estimate, ticket):
    """Present a DRAFT estimate. Caller has checked role + OCC version.

    State preconditions (priority 8) and ERR_NO_SERVICE_LINES /
    ERR_BAD_REVISION_CHAIN are enforced here.
    """
    if estimate["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ESTIMATE_STATE", "Estimate is not DRAFT")
    if ticket["repair_status"] not in ("INTAKE", "REVISION_REQUESTED"):
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not in INTAKE or REVISION_REQUESTED")

    # at least one non-VOIDED service line
    non_voided = [sl for sl in ticket_lines(ticket["id"]) if sl["status"] != "VOIDED"]
    if not non_voided:
        raise ApiError("ERR_NO_SERVICE_LINES", "Ticket has no non-VOIDED service lines")

    # revision-chain check
    if ticket["repair_status"] == "REVISION_REQUESTED":
        most_recent_rejected = _most_recent_rejected_estimate(ticket["id"])
        supersedes = estimate.get("supersedes_estimate_id")
        if most_recent_rejected is None or supersedes != most_recent_rejected["id"]:
            raise ApiError("ERR_BAD_REVISION_CHAIN",
                           "Revision must supersede the most recent REJECTED estimate")
        # supersede the prior rejected estimate
        most_recent_rejected["status"] = "SUPERSEDED"
        db.touch(most_recent_rejected)
        estimate["revision_number"] = most_recent_rejected["revision_number"] + 1

    # transition
    estimate["status"] = "PRESENTED"
    totals = calc.estimate_total(ticket["id"], ticket["priority"], "PROVISIONAL")
    estimate.update(totals)
    db.touch(estimate)

    ticket["repair_status"] = "AWAITING_APPROVAL"
    db.touch(ticket)

    _append_notification(ticket, "ESTIMATE_PRESENTED",
                         "Estimate %s presented" % estimate["id"])


def _most_recent_rejected_estimate(tid):
    rejected = [e for e in ticket_estimates(tid) if e["status"] == "REJECTED"]
    if not rejected:
        return None
    return max(rejected, key=lambda e: e.get("_seq", 0))


# ---------------------------------------------------------------------------
# Estimate approve / reject
# ---------------------------------------------------------------------------
def approve_estimate(estimate, ticket):
    if ticket["repair_status"] != "AWAITING_APPROVAL":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not AWAITING_APPROVAL")
    if estimate["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_ESTIMATE_STATE", "Estimate not PRESENTED")

    estimate["status"] = "APPROVED"
    db.touch(estimate)

    ticket["approved_estimate_id"] = estimate["id"]
    # compute ready_by once, here
    ticket["ready_by"] = calc.ready_by_sla(ticket)

    # outstanding parts -> AWAITING_PARTS, else APPROVED
    outstanding = [po for po in ticket_parts(ticket["id"])
                   if po["status"] in ("REQUESTED", "ORDERED")]
    if outstanding:
        ticket["repair_status"] = "AWAITING_PARTS"
    else:
        ticket["repair_status"] = "APPROVED"
    db.touch(ticket)


def reject_estimate(estimate, ticket):
    if ticket["repair_status"] != "AWAITING_APPROVAL":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not AWAITING_APPROVAL")
    if estimate["status"] != "PRESENTED":
        raise ApiError("ERR_INVALID_ESTIMATE_STATE", "Estimate not PRESENTED")

    estimate["status"] = "REJECTED"
    db.touch(estimate)

    ticket["repair_status"] = "REVISION_REQUESTED"
    db.touch(ticket)


# ---------------------------------------------------------------------------
# Parts order pipeline
# ---------------------------------------------------------------------------
def order_part(part, ticket):
    if part["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_PARTS_STATE", "PartsOrder not REQUESTED")
    if ticket["repair_status"] not in (
            "AWAITING_APPROVAL", "REVISION_REQUESTED", "APPROVED", "AWAITING_PARTS"):
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not in an orderable state")
    part["status"] = "ORDERED"
    db.touch(part)
    db.touch(ticket)


def receive_part(part, ticket):
    if part["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_PARTS_STATE", "PartsOrder not ORDERED")
    part["status"] = "RECEIVED"
    db.touch(part)
    db.touch(ticket)


def cancel_part(part, ticket):
    """Direct technician cancel: owning line is NOT auto-voided."""
    if part["status"] not in ("REQUESTED", "ORDERED"):
        raise ApiError("ERR_INVALID_PARTS_STATE", "PartsOrder not in REQUESTED/ORDERED")
    part["status"] = "CANCELLED"
    db.touch(part)
    db.touch(ticket)


# ---------------------------------------------------------------------------
# Ticket start-repair / mark-ready
# ---------------------------------------------------------------------------
def start_repair(ticket):
    status = ticket["repair_status"]
    if status not in ("APPROVED", "AWAITING_PARTS"):
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not APPROVED or AWAITING_PARTS")

    if status == "AWAITING_PARTS":
        for po in ticket_parts(ticket["id"]):
            if po["status"] not in ("RECEIVED", "CANCELLED"):
                raise ApiError("ERR_PARTS_NOT_READY",
                               "All parts must be RECEIVED or CANCELLED")

    tech_id = ticket.get("assigned_technician_id")
    tech = db.technicians.get(tech_id) if tech_id else None
    if tech is None or not tech.get("active", False):
        raise ApiError("ERR_NO_TECHNICIAN", "Ticket needs an assigned active technician")

    ticket["repair_status"] = "IN_REPAIR"
    db.touch(ticket)


def mark_ready(ticket):
    if ticket["repair_status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not IN_REPAIR")

    non_voided = [sl for sl in ticket_lines(ticket["id"]) if sl["status"] != "VOIDED"]
    for sl in non_voided:
        if sl["status"] != "COMPLETED":
            raise ApiError("ERR_LINES_NOT_COMPLETED",
                           "Every non-VOIDED service line must be COMPLETED")

    ticket["repair_status"] = "READY_FOR_PICKUP"
    ticket["ready_at"] = clock.now()
    totals = calc.estimate_total(ticket["id"], ticket["priority"], "FINAL")
    ticket["final_charge_cents"] = totals["estimate_total_cents"]
    ready_by = ticket.get("ready_by")
    ticket["sla_breached"] = bool(ready_by is not None and ticket["ready_at"] > ready_by)
    db.touch(ticket)


# ---------------------------------------------------------------------------
# notify-ready
# ---------------------------------------------------------------------------
def notify_ready(ticket):
    # notify_status is a parallel dimension; spec moves NONE -> READY_NOTIFIED.
    ticket["notify_status"] = "READY_NOTIFIED"
    db.touch(ticket)
    _append_notification(ticket, "READY_FOR_PICKUP", "Your item is ready for pickup")


# ---------------------------------------------------------------------------
# pickup
# ---------------------------------------------------------------------------
def pickup(ticket):
    if ticket["repair_status"] not in ("READY_FOR_PICKUP", "UNCLAIMED"):
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not READY_FOR_PICKUP or UNCLAIMED")

    recompute_amount_paid(ticket)
    final_charge = ticket.get("final_charge_cents") or 0
    if ticket["amount_paid_cents"] < final_charge:
        raise ApiError("ERR_BALANCE_DUE", "Outstanding balance due before pickup")

    ticket["picked_up_at"] = clock.now()
    ticket["warranty_expires_at"] = calc.warranty_window(ticket)
    ticket["repair_status"] = "PICKED_UP"
    db.touch(ticket)


# ---------------------------------------------------------------------------
# flag-unclaimed / dispose
# ---------------------------------------------------------------------------
def flag_unclaimed(ticket):
    from datetime import timedelta
    if ticket["repair_status"] != "READY_FOR_PICKUP":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not READY_FOR_PICKUP")
    ready_at = ticket.get("ready_at")
    threshold = ready_at + timedelta(days=calc.UNCLAIMED_GRACE_DAYS)
    if clock.now() < threshold:
        raise ApiError("ERR_UNCLAIMED_TOO_EARLY", "Unclaimed grace window not elapsed")

    ticket["repair_status"] = "UNCLAIMED"
    ticket["notify_status"] = "UNCLAIMED_WARNED"
    db.touch(ticket)
    _append_notification(ticket, "UNCLAIMED_WARNING", "Your item is unclaimed")


def dispose(ticket):
    from datetime import timedelta
    if ticket["repair_status"] != "UNCLAIMED":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not UNCLAIMED")
    if ticket["notify_status"] != "UNCLAIMED_WARNED":
        raise ApiError("ERR_UNCLAIMED_NOT_WARNED", "Ticket was never warned")
    ready_at = ticket.get("ready_at")
    threshold = ready_at + timedelta(days=calc.DISPOSAL_DAYS)
    if clock.now() < threshold:
        raise ApiError("ERR_DISPOSAL_TOO_EARLY", "Disposal window not elapsed")

    for sl in ticket_lines(ticket["id"]):
        if sl["status"] != "VOIDED":
            sl["status"] = "VOIDED"
            db.touch(sl)

    ticket["repair_status"] = "DISPOSED"
    db.touch(ticket)


# ---------------------------------------------------------------------------
# cancel (three-hop transitive cascade + mop-up)
# ---------------------------------------------------------------------------
def cancel_ticket(ticket):
    if ticket["repair_status"] not in (
            "INTAKE", "AWAITING_APPROVAL", "REVISION_REQUESTED", "APPROVED", "AWAITING_PARTS"):
        raise ApiError("ERR_NOT_CANCELLABLE", "Ticket not in a cancellable state")

    tid = ticket["id"]

    # hop 1: every non-RECEIVED PartsOrder -> CANCELLED
    for po in ticket_parts(tid):
        if po["status"] != "RECEIVED" and po["status"] != "CANCELLED":
            po["status"] = "CANCELLED"
            db.touch(po)
            db.touch(ticket)
            # hop 2: owning service line QUOTED/COMPLETED -> VOIDED
            line = db.service_lines.get(po.get("service_line_id"))
            if line is not None and line["status"] in ("QUOTED", "COMPLETED"):
                _void_line_with_cascade(line, ticket)

    # mop-up: any remaining non-VOIDED line is voided as well
    for sl in ticket_lines(tid):
        if sl["status"] != "VOIDED":
            _void_line_with_cascade(sl, ticket)

    # mop-up: any still-open estimate is rejected
    _reject_open_estimate(tid)

    ticket["repair_status"] = "CANCELLED"
    db.touch(ticket)


def _void_line_with_cascade(line, ticket):
    """Void a line and (hop 3) reject the ticket's open estimate."""
    line["status"] = "VOIDED"
    db.touch(line)
    _reject_open_estimate(ticket["id"])


def _reject_open_estimate(tid):
    for e in ticket_estimates(tid):
        if e["status"] in ("DRAFT", "PRESENTED"):
            e["status"] = "REJECTED"
            db.touch(e)


# ---------------------------------------------------------------------------
# service-line PATCH (adjust price / complete)
# ---------------------------------------------------------------------------
def complete_line(line, ticket):
    if line["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Service line not QUOTED")
    if ticket["repair_status"] != "IN_REPAIR":
        raise ApiError("ERR_INVALID_TICKET_STATE", "Ticket not IN_REPAIR")
    line["status"] = "COMPLETED"
    db.touch(line)
    db.touch(ticket)


# ---------------------------------------------------------------------------
# payment refund
# ---------------------------------------------------------------------------
def refund_payment(payment, ticket):
    if payment["state"] != "CAPTURED":
        raise ApiError("ERR_PAYMENT_NOT_REFUNDABLE", "Payment not CAPTURED")
    payment["state"] = "REFUNDED"
    if ticket is not None:
        recompute_amount_paid(ticket)
        db.touch(ticket)


# ---------------------------------------------------------------------------
# warranty claim adjudication
# ---------------------------------------------------------------------------
def _approved_estimate_author(ticket):
    eid = ticket.get("approved_estimate_id")
    if not eid:
        return None
    est = db.estimates.get(eid)
    if est is None:
        return None
    return est.get("authored_by_technician_id")


def approve_claim(claim, ruled_by_technician_id):
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Claim not FILED")
    ticket = db.repair_tickets.get(claim["ticket_id"])
    author = _approved_estimate_author(ticket) if ticket else None
    if author is not None and ruled_by_technician_id == author:
        raise ApiError("ERR_SEGREGATION_VIOLATION",
                       "Ruling technician must differ from the estimate author")

    claim["ruled_by_technician_id"] = ruled_by_technician_id
    claim["status"] = "APPROVED"

    # hop 1: spawn a no-charge redo RepairTicket
    redo = {
        "id": db.new_id(),
        "customer_id": ticket["customer_id"],
        "drop_off_at": clock.now(),
        "priority": "RUSH",
        "repair_status": "APPROVED",
        "notify_status": "NONE",
        "ready_by": None,
        "ready_at": None,
        "sla_breached": False,
        "approved_estimate_id": None,
        "final_charge_cents": 0,
        "amount_paid_cents": 0,
        "warranty_expires_at": None,
        "picked_up_at": None,
        "assigned_technician_id": None,
    }
    db.stamp_create(redo)
    db.repair_tickets[redo["id"]] = redo
    claim["redo_ticket_id"] = redo["id"]

    # hop 2: copy the failed service line onto the redo ticket as a no-charge QUOTED line
    failed_line = db.service_lines.get(claim["service_line_id"])
    if failed_line is not None:
        redo_line = {
            "id": db.new_id(),
            "ticket_id": redo["id"],
            "ticket_item_id": failed_line.get("ticket_item_id"),
            "service_type_id": failed_line.get("service_type_id"),
            "quoted_price_cents": 0,
            "adjusted_price_cents": None,
            "status": "QUOTED",
        }
        db.stamp_create(redo_line)
        db.service_lines[redo_line["id"]] = redo_line

    db.touch(claim)


def deny_claim(claim, ruled_by_technician_id):
    if claim["status"] != "FILED":
        raise ApiError("ERR_INVALID_CLAIM_STATE", "Claim not FILED")
    ticket = db.repair_tickets.get(claim["ticket_id"])
    author = _approved_estimate_author(ticket) if ticket else None
    if author is not None and ruled_by_technician_id == author:
        raise ApiError("ERR_SEGREGATION_VIOLATION",
                       "Ruling technician must differ from the estimate author")

    claim["ruled_by_technician_id"] = ruled_by_technician_id
    claim["status"] = "DENIED"
    db.touch(claim)


# ---------------------------------------------------------------------------
# notification append
# ---------------------------------------------------------------------------
def _append_notification(ticket, kind, body):
    customer = db.customers.get(ticket["customer_id"])
    channel = customer["notify_channel"] if customer else "EMAIL"
    notif = {
        "id": db.new_id(),
        "ticket_id": ticket["id"],
        "kind": kind,
        "channel": channel,
        "body": body,
    }
    db.stamp_audit_create(notif)
    db.notifications[notif["id"]] = notif
    return notif
