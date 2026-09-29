"""Order-side services: rental occupancy, core settlement ledger, closure rollup."""
from fractions import Fraction

import db
from db import setf, touch
from services.pricing import core_face_value_by_part, core_face_value_cents, order_lines
from util import days, round_half_up, whole_days_between

RENTAL_OCCUPANCY_STATES = ("PENDING_DISCLOSURE", "CONFIRMED", "DELIVERED")
RENTAL_BUFFER_DAYS = 2

CONDITION_MULTIPLIER = {
    "INTACT": Fraction(1),
    "DAMAGED_SHELL": Fraction(70, 100),
    "INCOMPLETE": Fraction(40, 100),
    "NON_RETURNABLE": Fraction(0),
}

LATE_FORFEIT_DAYS = 20

TERMINAL_AUTH = ("NOT_REQUIRED", "AUTHENTIC")
TERMINAL_CALIBRATION = ("NOT_REQUIRED", "CALIBRATION_PASSED")
SETTLED_CORE = ("NOT_REQUIRED", "CORE_CREDIT_ISSUED", "CORE_FORFEITED", "CORE_RELEASED")


# --------------------------------------------------------------------------
# rental_capacity_occupancy
# --------------------------------------------------------------------------

def rental_occupancy(part_id, order, window_start, window_end):
    """Units already committed on other orders whose buffered window collides."""
    occupied_units = 0
    for line in db.ordered(db.db.lines.all()):
        if line["part_id"] != part_id or line["order_id"] == order["id"]:
            continue
        other = db.db.orders.get(line["order_id"])
        if other is None or other["fulfillment_status"] not in RENTAL_OCCUPANCY_STATES:
            continue
        start = other.get("rental_window_start")
        end = other.get("rental_window_end")
        if start is None or end is None:
            continue
        occupied_end = end + days(RENTAL_BUFFER_DAYS)
        if window_start <= occupied_end and start <= window_end:
            occupied_units += line["quantity"]
    return occupied_units


# --------------------------------------------------------------------------
# core_return_credit_settlement
# --------------------------------------------------------------------------

def commit_core_liability(order):
    """PROVISIONAL_HOLD: face value moves onto every core part's ledger."""
    face_total = core_face_value_cents(order["id"])
    for part_id, amount in core_face_value_by_part(order["id"]).items():
        part = db.db.parts[part_id]
        part["core_face_value_committed_cents"] = (
            part.get("core_face_value_committed_cents", 0) + amount
        )
        part["core_liability_outstanding_cents"] = (
            part.get("core_liability_outstanding_cents", 0) + amount
        )
        touch(part)
    setf(order, "core_credit_provisional_cents", face_total)
    return face_total


def _allocate(total_credit, per_part):
    """Split an integer credit across parts by face value, largest remainder first."""
    face_total = sum(per_part.values())
    if face_total <= 0:
        return dict((k, 0) for k in per_part)
    allocation = {}
    remainders = []
    running = 0
    for part_id, face in per_part.items():
        exact = Fraction(total_credit * face, face_total)
        floor_value = exact.numerator // exact.denominator
        allocation[part_id] = floor_value
        remainders.append((exact - floor_value, part_id))
        running += floor_value
    leftover = total_credit - running
    remainders.sort(key=lambda pair: (-pair[0], pair[1]))
    index = 0
    while leftover > 0 and remainders:
        allocation[remainders[index % len(remainders)][1]] += 1
        leftover -= 1
        index += 1
    return allocation


def settle_core(order, condition, received_at):
    """FINAL_SETTLEMENT: compute lateness, condition decay, and move the ledger."""
    per_part = core_face_value_by_part(order["id"])
    face_total = sum(per_part.values())

    due = order.get("core_return_due_at")
    late_days = whole_days_between(due, received_at) if due is not None else 0

    condition_multiplier = CONDITION_MULTIPLIER[condition]
    decay = Fraction(1) - Fraction(5, 100) * late_days
    if decay < 0:
        decay = Fraction(0)

    if late_days >= LATE_FORFEIT_DAYS or condition == "NON_RETURNABLE":
        credited = 0
    else:
        credited = round_half_up(Fraction(face_total) * condition_multiplier * decay)

    allocation = _allocate(credited, per_part)
    for part_id, face in per_part.items():
        part = db.db.parts[part_id]
        share = allocation.get(part_id, 0)
        part["core_liability_outstanding_cents"] = (
            part.get("core_liability_outstanding_cents", 0) - face
        )
        part["core_credit_settled_cents"] = part.get("core_credit_settled_cents", 0) + share
        part["core_credit_forfeited_cents"] = (
            part.get("core_credit_forfeited_cents", 0) + (face - share)
        )
        touch(part)

    setf(order, "core_days_late", late_days)
    setf(order, "core_credit_final_cents", credited)
    setf(order, "core_return_status",
         "CORE_FORFEITED" if credited == 0 else "CORE_CREDIT_ISSUED")
    return credited, late_days


def release_core_liability(order):
    """Compensating release used when a CONFIRMED order is cancelled."""
    per_part = core_face_value_by_part(order["id"])
    for part_id, face in per_part.items():
        part = db.db.parts[part_id]
        part["core_liability_outstanding_cents"] = (
            part.get("core_liability_outstanding_cents", 0) - face
        )
        part["core_face_value_committed_cents"] = (
            part.get("core_face_value_committed_cents", 0) - face
        )
        touch(part)
    setf(order, "core_credit_provisional_cents", 0)
    setf(order, "core_return_status", "CORE_RELEASED")


# --------------------------------------------------------------------------
# DELIVERED -> CLOSED rollup
# --------------------------------------------------------------------------

def rollup_closure(order):
    if order["fulfillment_status"] != "DELIVERED":
        return
    for line in order_lines(order["id"]):
        if line["authentication_status"] not in TERMINAL_AUTH:
            return
        if line["calibration_status"] not in TERMINAL_CALIBRATION:
            return
    if order["core_return_status"] not in SETTLED_CORE:
        return
    setf(order, "fulfillment_status", "CLOSED")


# --------------------------------------------------------------------------
# defective_return_credit
# --------------------------------------------------------------------------

ROOT_CAUSE_FACTOR = {
    "MANUFACTURING_DEFECT": Fraction(1),
    "PART_AUTHENTICATION_FAILURE": Fraction(1),
    "UNDETERMINED": Fraction(50, 100),
    "PROVIDER_INSTALL_ERROR": Fraction(0),
    "CUSTOMER_MISUSE": Fraction(0),
}

# PRD 3.9: only CUSTOMER_MISUSE may never be credited.
NO_CREDIT_ROOT_CAUSES = ("CUSTOMER_MISUSE",)


def pro_rata_cents(case, line):
    return round_half_up(
        Fraction(line["line_total_cents"] * case["quantity"], line["quantity"])
    )


def goodwill_provisional(case, line):
    return round_half_up(Fraction(pro_rata_cents(case, line)) * Fraction(50, 100))


def analysis_final(case, line):
    if line["authentication_status"] == "COUNTERFEIT_SUSPECT":
        return 0
    factor = ROOT_CAUSE_FACTOR.get(case.get("root_cause_code"), Fraction(0))
    if case.get("defect_confirmed") is False:
        factor = min(factor, Fraction(25, 100))
    return round_half_up(Fraction(pro_rata_cents(case, line)) * factor)
