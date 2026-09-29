"""State-machine side effects: the allowance gate, cascades and bubble-ups."""

import calc
import derive
from errors import ApiError
from store import clock_now, db, iso, new_row, parse_instant, touch


# --------------------------------------------------------------------------
# The not-to-exceed allowance gate (PRD 2.8) -- always evaluated LAST.
# --------------------------------------------------------------------------
def enforce_allowance(project, added_provisional_cents):
    allowance = calc.commitment_allowance_cents(project)
    projected = derive.provisional_cost_cents(project) + int(added_provisional_cents)
    if projected > allowance:
        raise ApiError(
            "ERR_BUDGET_CEILING_EXCEEDED",
            "Projected provisional cost %d exceeds the allowance of %d cents."
            % (projected, allowance),
        )


class LedgerWatch(object):
    """Bump the project row when a child write actually moves a ledger figure."""

    def __init__(self, project):
        self.project = project
        self.before = derive.ledger_snapshot(project)

    def finish(self):
        if self.project is None:
            return
        if derive.ledger_snapshot(self.project) != self.before:
            touch(self.project)


# --------------------------------------------------------------------------
# Change orders (PRD 3.9)
# --------------------------------------------------------------------------
def create_change_order(deliverable, trigger_reason, additional_rounds_granted,
                        requested_by_user_id):
    air_date = parse_instant(deliverable["air_date"])
    money = calc.change_order_amount(
        trigger_reason, additional_rounds_granted, air_date, clock_now()
    )
    row = new_row(
        deliverable_id=deliverable["id"],
        trigger_reason=trigger_reason,
        additional_rounds_granted=int(additional_rounds_granted),
        labor_cents=money["labor_cents"],
        rush_pct=money["rush_pct"],
        rush_cents=money["rush_cents"],
        subtotal_cents=money["subtotal_cents"],
        producer_fee_pct=money["producer_fee_pct"],
        producer_fee_cents=money["producer_fee_cents"],
        amount_cents=money["amount_cents"],
        requested_by_user_id=requested_by_user_id,
        approved_by_user_id=None,
        status="PENDING_APPROVAL",
        _decision_note=None,
    )
    db["change_orders"][row["id"]] = row
    return row


# --------------------------------------------------------------------------
# Project bubble-ups (PRD 2.9, 3.7, 3.8)
# --------------------------------------------------------------------------
def bubble_project_into_post(project):
    """The disappearance of the last non-terminal shoot day moves IN_PRODUCTION -> IN_POST."""
    if project is None or project["status"] != "IN_PRODUCTION":
        return
    days = derive.project_shoot_days(project["id"])
    if not days:
        return
    if any(day["status"] in ("PLANNED", "CONFIRMED") for day in days):
        return
    project["status"] = "IN_POST"
    touch(project)


def bubble_project_into_delivered(project):
    """The last outstanding deliverable's approval moves IN_POST -> DELIVERED."""
    if project is None or project["status"] != "IN_POST":
        return
    deliverables = derive.project_deliverables(project["id"])
    if not deliverables:
        return
    if any(row["status"] != "APPROVED" for row in deliverables):
        return
    project["status"] = "DELIVERED"
    touch(project)
    # cascade cross-entity: every CONFIRMED engagement completes, ledger-neutral
    for engagement in derive.project_engagements(project["id"]):
        if engagement["status"] == "CONFIRMED":
            engagement["status"] = "COMPLETED"
            touch(engagement)


# --------------------------------------------------------------------------
# Shoot-day cascades (PRD 3.7)
# --------------------------------------------------------------------------
def cascade_shoot_day_cancel(shoot_day):
    for booking in derive.shoot_day_bookings(shoot_day["id"]):
        if booking["status"] in ("HELD", "CONFIRMED"):
            booking["status"] = "RELEASED"
            touch(booking)
    for reservation in derive.shoot_day_reservations(shoot_day["id"]):
        if reservation["status"] == "RESERVED":
            reservation["status"] = "RELEASED"
            touch(reservation)


def cascade_shoot_day_wrap(shoot_day):
    for booking in derive.shoot_day_bookings(shoot_day["id"]):
        if booking["status"] == "CONFIRMED":
            booking["status"] = "COMPLETED"
            touch(booking)
        elif booking["status"] == "HELD":
            booking["status"] = "RELEASED"
            touch(booking)
    for reservation in derive.shoot_day_reservations(shoot_day["id"]):
        if reservation["status"] == "RESERVED":
            reservation["status"] = "RETURNED"
            touch(reservation)


# --------------------------------------------------------------------------
# Talent compensation basis selection (PRD 3.3)
# --------------------------------------------------------------------------
def price_engagement(engagement, project, basis):
    if basis == "PROVISIONAL":
        channel_basis_count = len(set(project["channel_scope"]))
        term_basis_months = project["usage_term_months"]
    else:
        deliverables = derive.project_deliverables(project["id"])
        channel_basis_count = len({row["channel"] for row in deliverables})
        term_basis_months = max(row["usage_rights_months"] for row in deliverables)
    money = calc.talent_compensation(
        engagement["compensation_model"],
        engagement["session_fee_cents"],
        engagement["session_days"],
        channel_basis_count,
        term_basis_months,
    )
    engagement.update(money)
    engagement["comp_basis"] = basis
    return money


# --------------------------------------------------------------------------
# Handover (PRD 3.10)
# --------------------------------------------------------------------------
def perform_handover(project, handover_recipient):
    now = clock_now()
    project["handover_at"] = iso(now)
    project["handover_recipient"] = handover_recipient
    project["status"] = "ARCHIVED"
    touch(project)
    for deliverable in derive.project_deliverables(project["id"]):
        if deliverable["status"] == "APPROVED":
            deliverable["status"] = "HANDED_OVER"
            touch(deliverable)
