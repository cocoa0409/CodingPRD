"""The five ordered write gates (PRD 2.6), rungs 28-33.

They run in a fixed order and the first failure decides the error; no later
gate and no domain rule below them is consulted.
"""

from core.constants import PREPAY_DEPOSIT_MIN_CENTS
from core.errors import ApiError
from core.store import db
from core.timeutil import clock, parse_iso_date

from .rollups import lines_of, prescription_covers, prescription_is_live


def gate1_farrier(farrier):
    """Gate 1 -- two rungs in sequence: status first, then the certificate."""
    if farrier is None:
        return
    if farrier["status"] != "ACTIVE":
        raise ApiError("ERR_FARRIER_INACTIVE")
    expires = parse_iso_date(farrier["cert_expires_on"])
    if expires is None or expires < clock.today:
        raise ApiError("ERR_FARRIER_CERT_EXPIRED")


def gate2_route_open(route):
    if route is None:
        return
    if route["status"] not in ("DRAFT", "PLANNED"):
        raise ApiError("ERR_ROUTE_NOT_OPEN")


def gate3_client(client):
    if client is None:
        return
    standing = client["billing_standing"]
    if standing == "ACTIVE":
        return
    if (
        standing == "PREPAY_REQUIRED"
        and client["deposit_balance_cents"] >= PREPAY_DEPOSIT_MIN_CENTS
    ):
        return
    raise ApiError("ERR_CLIENT_PREPAY_REQUIRED")


def gate4_horse_hold(horse, appointment=None, on_creation=False):
    """Gate 4 -- the horse is not on hold, or every line already on the visit is
    corrective under a live prescription covering its limb.

    # Adjudication of friction 1: creating an appointment for a horse whose
    # hold_status is HOLD is REFUSED with ERR_HORSE_ON_HOLD -- the empty
    # service-line set of a brand-new visit does not satisfy the escape clause
    # vacuously.  Section 4.1 declares ERR_HORSE_ON_HOLD as a reachable refusal
    # of POST /appointments, and only this reading keeps it reachable there.
    # It strands nothing: a visit created before the hold stays UNROUTED
    # through the lameness chain, can still take corrective lines under a live
    # prescription and can still be attached, so the whole
    # corrective-work-under-hold path remains reachable.
    #
    # Gate 4's guard list (section 2.6) names appointment creation, attachment,
    # service-line addition and appointment start -- warranty-revisit creation
    # is guarded by gate 3 only, and section 4.1 lists no ERR_HORSE_ON_HOLD for
    # it, so the hold is not consulted there.
    """
    if horse is None or horse["hold_status"] == "CLEAR":
        return
    if on_creation or appointment is None:
        raise ApiError("ERR_HORSE_ON_HOLD")
    existing = lines_of(appointment)
    for line in existing:
        if line["service_type"] != "CORRECTIVE":
            raise ApiError("ERR_HORSE_ON_HOLD")
        prescription = db.get("vet_prescriptions", line.get("prescription_id"))
        if not prescription_is_live(prescription, appointment["scheduled_date"]):
            raise ApiError("ERR_HORSE_ON_HOLD")
        if not prescription_covers(prescription, line["limb"]):
            raise ApiError("ERR_HORSE_ON_HOLD")


def gate5_appointment(appointment, eligible):
    if appointment["status"] not in eligible:
        raise ApiError("ERR_APPOINTMENT_NOT_ELIGIBLE")


# Eligible sets declared per operation (PRD 2.6).
ELIGIBLE = {
    # Adjudication of friction 7: line ADDITION takes the same eligible set as
    # line removal -- {UNROUTED, SCHEDULED, CONFIRMED} -- exactly as section 2.6
    # states it ("service-line addition and service-line removal accept
    # UNROUTED, SCHEDULED and CONFIRMED").  Admitting IN_PROGRESS would
    # contradict the only literal statement of the set and strands nothing.
    "service_line_add": ("UNROUTED", "SCHEDULED", "CONFIRMED"),
    "service_line_remove": ("UNROUTED", "SCHEDULED", "CONFIRMED"),
    "attach": ("UNROUTED",),
    "detach": ("SCHEDULED", "CONFIRMED"),
    "start": ("SCHEDULED", "CONFIRMED"),
    "complete": ("IN_PROGRESS",),
    "cancel": ("UNROUTED", "SCHEDULED", "CONFIRMED"),
    "no_show": ("SCHEDULED", "CONFIRMED"),
    "warranty_revisit": ("COMPLETED",),
    "reminder_send": ("SCHEDULED", "CONFIRMED"),
    # Adjudication of friction 2: reminder acknowledgement accepts SCHEDULED
    # AND CONFIRMED.  Section 3.8 conditions the appointment transition on the
    # appointment being SCHEDULED ("when the reminder's appointment is
    # SCHEDULED it moves to CONFIRMED"); under a SCHEDULED-only gate that
    # condition could never be false and the declared "move only the reminder"
    # behaviour would be unreachable.  Admitting CONFIRMED strands nothing --
    # ERR_APPOINTMENT_NOT_ELIGIBLE is still reachable on acknowledgement via a
    # BLOCKED, UNROUTED or cancelled appointment.
    "reminder_acknowledge": ("SCHEDULED", "CONFIRMED"),
}
