"""Shrink valuation, cook-and-sell recovery (PRD 3.9) and violation remediation."""

from decimal import Decimal

import calc
import serializers
import services
from auth import counter_scope
from common import dec, rhu, touch
from envelope import obj_result
from errors import fail
from store import db
from validators import opt_id, opt_number, req_enum, req_number, req_str
from web import listing, route

SHRINK_ROLES = ("ChainAdmin", "SeafoodManager", "ComplianceOfficer")
SHRINK_REASONS = ("UNSOLD_FRESH", "MISLABEL_DESTRUCTION", "COLD_CHAIN_DISPOSAL")
ZERO3 = Decimal("0.000")


def resolve_event(event_id):
    """SeafoodManager scope reaches a shrink event through its lot's counter."""
    event = db.shrink_events.get(event_id)
    if event is not None:
        lot = db.lots.get(event["lot_id"])
        if lot is not None:
            counter_scope(lot["counter_id"])
    else:
        fail("ERR_SHRINK_EVENT_NOT_FOUND")
    return event


def resolve_violation(violation_id):
    violation = db.violations.get(violation_id)
    if violation is not None:
        counter_scope(violation["counter_id"])
    else:
        fail("ERR_VIOLATION_NOT_FOUND")
    return violation


# --------------------------------------------------------------------------
# shrink events
# --------------------------------------------------------------------------

@route("/shrink-events", methods=["POST"], roles=("SeafoodManager",))
def write_shrink(body):
    raw_lot = opt_id(body, "lot_id")
    lot = None
    if raw_lot is not None:
        lot = db.lots.get(raw_lot)
        if lot is not None:
            counter_scope(lot["counter_id"])
        else:
            fail("ERR_LOT_NOT_FOUND")

    req_str(body, "lot_id")
    reason = req_enum(body, "reason", SHRINK_REASONS)
    shrink_weight_kg = req_number(body, "shrink_weight_kg", 3, exclusive_min=0)
    conversion_requested_kg = opt_number(body, "conversion_requested_kg", 3, minimum=0)
    if conversion_requested_kg is None:
        conversion_requested_kg = ZERO3

    if lot["intake_status"] not in ("RECEIVED", "CASED", "HELD"):
        fail("ERR_LOT_STATE_INVALID")
    counter = services.lot_counter(lot)
    if counter is not None and counter["posture"] == "SUSPENDED":
        fail("ERR_COUNTER_SUSPENDED")
    if shrink_weight_kg > dec(lot["remaining_weight_kg"]):
        fail("ERR_SHRINK_EXCEEDS_REMAINING")

    record = services.create_shrink_event(
        lot, reason, shrink_weight_kg, conversion_requested_kg
    )
    return obj_result(serializers.shrink_event, record, 201)


@route("/shrink-events/<event_id>", methods=["GET"], roles=SHRINK_ROLES)
def get_shrink(body, event_id):
    return obj_result(serializers.shrink_event, resolve_event(event_id))


@route("/shrink-events", methods=["GET"], roles=SHRINK_ROLES)
def list_shrink(body):
    return listing(
        serializers.shrink_event,
        list(db.shrink_events.values()),
        string_fields=("lot_id", "reason", "status"),
    )


@route("/shrink-events/<event_id>/approve-conversion", methods=["POST"], roles=("SeafoodManager",))
def approve_conversion(body, event_id):
    event = resolve_event(event_id)

    if event["status"] != "VALUED":
        fail("ERR_SHRINK_STATE_INVALID")

    lot = db.lots.get(event["lot_id"])
    allowance = calc.conversion_allowance_kg(lot, event["shrink_weight_kg"])
    requested = dec(event["conversion_requested_kg"])

    # PRD 2.9 evaluates the allowance ceiling (item 52) ahead of the
    # permission gate (item 53).
    if requested > allowance:
        fail("ERR_CONVERSION_ALLOWANCE_EXCEEDED")
    if (
        event["reason"] != "UNSOLD_FRESH"
        or requested <= ZERO3
        or lot["previously_frozen"]
    ):
        fail("ERR_CONVERSION_NOT_PERMITTED")

    event["allowance_kg"] = allowance
    event["approved_conversion_kg"] = calc.approved_conversion_kg(requested, allowance)
    event["status"] = "CONVERSION_APPROVED"
    touch(event)
    return obj_result(serializers.shrink_event, event)


@route("/shrink-events/<event_id>/convert", methods=["POST"], roles=("SeafoodManager",))
def convert_shrink(body, event_id):
    event = resolve_event(event_id)

    if event["status"] != "CONVERSION_APPROVED":
        fail("ERR_SHRINK_STATE_INVALID")

    lot = db.lots.get(event["lot_id"])
    yield_kg = calc.cook_yield_kg(lot, event["approved_conversion_kg"])
    credit = calc.recovery_credit_cents(
        lot,
        event["approved_conversion_kg"],
        yield_kg,
        event["provisional_value_cents"],
    )
    event["cook_yield_kg"] = yield_kg
    event["recovery_credit_cents"] = credit
    event["final_value_cents"] = event["provisional_value_cents"] - credit
    event["status"] = "CONVERTED"
    touch(event)
    return obj_result(serializers.shrink_event, event)


@route("/shrink-events/<event_id>/post", methods=["POST"], roles=("SeafoodManager",))
def post_shrink(body, event_id):
    event = resolve_event(event_id)

    if event["status"] not in ("VALUED", "CONVERTED"):
        fail("ERR_SHRINK_STATE_INVALID")

    if event["status"] == "VALUED":
        event["final_value_cents"] = event["provisional_value_cents"]
        event["recovery_credit_cents"] = 0

    lot = db.lots.get(event["lot_id"])
    weight = dec(event["shrink_weight_kg"])
    remaining = dec(lot["remaining_weight_kg"])
    full_destruction = event["reason"] == "MISLABEL_DESTRUCTION" and weight == remaining

    lot["remaining_weight_kg"] = rhu(remaining - weight, 3)
    touch(lot)

    counter = services.lot_counter(lot)
    if counter is not None:
        counter["shrink_gross_cents"] += event["provisional_value_cents"]
        counter["shrink_net_cents"] += event["final_value_cents"]
        counter["recovered_conversion_cents"] += event["recovery_credit_cents"]
        touch(counter)

    event["posted_at"] = db.clock
    event["status"] = "POSTED"
    touch(event)

    if full_destruction and lot["intake_status"] == "CASED":
        services.vacate_lot(lot, "DISPOSED")
    return obj_result(serializers.shrink_event, event)


@route("/shrink-events/<event_id>/reverse", methods=["POST"], roles=("ComplianceOfficer",))
def reverse_shrink(body, event_id):
    event = db.shrink_events.get(event_id)
    if event is None:
        fail("ERR_SHRINK_EVENT_NOT_FOUND")
    reversal_note = req_str(body, "reversal_note")

    if event["status"] != "POSTED":
        fail("ERR_SHRINK_STATE_INVALID")

    lot = db.lots.get(event["lot_id"])
    if lot is not None:
        lot["remaining_weight_kg"] = rhu(
            dec(lot["remaining_weight_kg"]) + dec(event["shrink_weight_kg"]), 3
        )
        touch(lot)
        counter = services.lot_counter(lot)
        if counter is not None:
            counter["shrink_gross_cents"] -= event["provisional_value_cents"]
            counter["shrink_net_cents"] -= event["final_value_cents"]
            counter["recovered_conversion_cents"] -= event["recovery_credit_cents"]
            touch(counter)

    event["reversed_at"] = db.clock
    event["reversal_note"] = reversal_note
    event["status"] = "REVERSED"
    touch(event)
    return obj_result(serializers.shrink_event, event)


# --------------------------------------------------------------------------
# compliance violations
# --------------------------------------------------------------------------

@route("/violations/<violation_id>", methods=["GET"], roles=SHRINK_ROLES)
def get_violation(body, violation_id):
    return obj_result(serializers.violation, resolve_violation(violation_id))


@route("/violations", methods=["GET"], roles=SHRINK_ROLES)
def list_violations(body):
    return listing(
        serializers.violation,
        list(db.violations.values()),
        string_fields=("counter_id", "lot_id", "category", "status"),
    )


@route("/violations/<violation_id>/cure", methods=["POST"], roles=("SeafoodManager",))
def cure_violation(body, violation_id):
    violation = resolve_violation(violation_id)
    cure_note = req_str(body, "cure_note")

    if violation["status"] != "OPEN":
        fail("ERR_VIOLATION_STATE_INVALID")

    violation["status"] = "CURED"
    violation["cure_note"] = cure_note
    violation["cured_at"] = db.clock
    touch(violation)
    services.derive_posture(db.counters.get(violation["counter_id"]))
    return obj_result(serializers.violation, violation)


@route("/violations/<violation_id>/expunge", methods=["POST"], roles=("ComplianceOfficer",))
def expunge_violation(body, violation_id):
    violation = db.violations.get(violation_id)
    if violation is None:
        fail("ERR_VIOLATION_NOT_FOUND")
    expunge_note = req_str(body, "expunge_note")

    if violation["status"] not in ("OPEN", "CURED"):
        fail("ERR_VIOLATION_STATE_INVALID")

    violation["status"] = "EXPUNGED"
    violation["expunge_note"] = expunge_note
    violation["expunged_at"] = db.clock
    touch(violation)
    services.derive_posture(db.counters.get(violation["counter_id"]))
    return obj_result(serializers.violation, violation)
