"""Derived-field maintenance, the allocation waterfall and the event cascades.

Convention used throughout (PRD 2.4 / 2.9):
  * the record the caller named is written field by field and then `touch`ed
    exactly once, so one request is one version increment on that record;
  * every record reached by a cascade hop goes through `update_record`, which
    increments its version when the hop actually changed something.
"""
import calc
from store import (
    apply_silent,
    create_record,
    db,
    logical_now,
    touch,
    update_record,
)
from util import fmt_ts, plus_days


# --- derived aggregates -----------------------------------------------------


def recompute_event_risk(event, silent=False):
    values = calc.event_risk_values(event)
    if silent:
        return apply_silent(event, values)
    return update_record(event, values)


def recompute_client(client):
    return update_record(client, calc.client_exposure_values(client))


def recompute_host(host):
    count = 0
    for assignment in calc.assignments_of_host(host["id"]):
        if assignment["assignment_state"] == "ASSIGNED":
            count += 1
    return update_record(host, {"active_assignment_count": count})


def host_names_for(booking):
    names = []
    for assignment in calc.assignments_of_booking(booking["id"]):
        if assignment["assignment_state"] != "ASSIGNED":
            continue
        host = db.on_site_hosts.get(assignment["on_site_host_id"])
        if host is not None:
            names.append(host["full_name"])
    return names


def build_itinerary(booking, package, event):
    return {
        "event_name": event["name"],
        "event_date": fmt_ts(event["event_date"]),
        "venue_name": event["venue_name"],
        "hotel_nights": package["hotel_nights"],
        "transport_included": package["transport_included"],
        "credential_count": booking["credentials_issued_count"],
        "host_names": host_names_for(booking),
    }


def refresh_itinerary(booking):
    """Keep the frozen itinerary's host list current (PRD 3.7)."""
    itinerary = booking.get("itinerary")
    if not itinerary:
        return False
    names = host_names_for(booking)
    if itinerary.get("host_names") == names:
        return False
    fresh = dict(itinerary)
    fresh["host_names"] = names
    return update_record(booking, {"itinerary": fresh})


def booking_paid_cents(booking):
    total = 0
    for installment in calc.installments_of_booking(booking["id"]):
        total += installment["paid_amount_cents"]
    return total - booking["refund_cents"]


def has_open_schedule_line(booking):
    for installment in calc.installments_of_booking(booking["id"]):
        if (
            installment["installment_kind"] == "SCHEDULE"
            and installment["installment_state"] in calc.OPEN_INSTALLMENT_STATES
        ):
            return True
    return False


# --- rights deal state and the channel waterfall ----------------------------


def run_waterfall_pass(deal, released_units, suppress_block=None):
    """Distribution pass then revert pass; returns the undistributed remainder."""
    blocks = calc.blocks_of_deal(deal["id"])
    recalled_units = 0
    for block in blocks:
        if block["block_state"] == "RECALLED":
            recalled_units += block["allocated_units"]
    remaining = released_units - recalled_units
    if remaining < 0:
        remaining = 0

    candidates = calc.waterfall_candidates(deal)
    pending = {}
    for block in candidates:
        give = block["target_units"] if block["target_units"] < remaining else remaining
        if give < 0:
            give = 0
        pending[block["id"]] = {"allocated_units": give}
        remaining -= give

    for block in candidates:
        changes = pending[block["id"]]
        allocated = changes["allocated_units"]
        committed = block["committed_units"]
        released_back = block["released_back_units"]
        over = committed - allocated
        if over > 0:
            sold = [
                b
                for b in calc.bookings_of_block(block["id"])
                if b["fulfillment_status"] == "ALLOCATED"
            ]
            sold.sort(key=lambda b: (b["created_at"], b["_seq"]), reverse=True)
            for booking in sold:
                if over <= 0:
                    break
                consumed = calc.consumed_units(booking)
                booking["fulfillment_status"] = "RESERVED"
                booking["allocation_block_id"] = None
                touch(booking)
                committed -= consumed
                released_back += consumed
                over -= consumed
            changes["committed_units"] = committed
            changes["released_back_units"] = released_back
        changes["block_state"] = (
            "EXHAUSTED" if allocated >= block["target_units"] else "OPEN"
        )

    for block_id, changes in pending.items():
        block = db.allocation_blocks[block_id]
        if suppress_block is not None and block_id == suppress_block:
            apply_silent(block, changes)
        else:
            update_record(block, changes)
    return remaining


def apply_deal_state(deal, with_status=True, force=False, waterfall=True, suppress_block=None):
    """Recompute a deal's derived figures (and optionally its status) in one write."""
    values = calc.deal_liability_values(deal)
    if with_status:
        status = calc.deal_status_for(deal)
        values["deal_status"] = status
        if status == "FULLY_RELEASED":
            values["shortfall_units"] = 0
    released = values["released_units"]
    if waterfall:
        values["unallocated_units"] = run_waterfall_pass(
            deal, released, suppress_block=suppress_block
        )
    else:
        held = 0
        for block in calc.blocks_of_deal(deal["id"]):
            held += block["allocated_units"]
        values["unallocated_units"] = released - held
    return update_record(deal, values, force=force)


def reopen_shortfall_deal(deal):
    """PRD 3.2: a fresh promise can lift a deal out of SHORTFALL_DECLARED."""
    if deal["deal_status"] != "SHORTFALL_DECLARED":
        return None
    released = calc.deal_released_units(deal)
    pending = calc.deal_pending_units(deal)
    if released + pending < deal["guaranteed_minimum_units"]:
        return None
    return "PARTIALLY_RELEASED" if released > 0 else "COMMITTED"


# --- payment schedules ------------------------------------------------------


def next_sequence_no(booking_id):
    highest = 0
    for installment in calc.installments_of_booking(booking_id):
        if installment["sequence_no"] > highest:
            highest = installment["sequence_no"]
    return highest + 1


def generate_schedule(booking, event):
    """Issue the booking's SCHEDULE lines (PRD 3.6). Never called directly by a client."""
    sequence = next_sequence_no(booking["id"])
    created = []
    for amount, due_at in calc.schedule_lines(booking, event):
        created.append(
            create_record(
                db.payment_installments,
                {
                    "booking_id": booking["id"],
                    "sequence_no": sequence,
                    "amount_cents": amount,
                    "due_at": due_at,
                    "installment_kind": "SCHEDULE",
                    "installment_state": "SCHEDULED",
                    "paid_amount_cents": 0,
                    "paid_at": None,
                },
            )
        )
        sequence += 1
    return created


def create_settlement_installment(booking, amount_cents):
    return create_record(
        db.payment_installments,
        {
            "booking_id": booking["id"],
            "sequence_no": next_sequence_no(booking["id"]),
            "amount_cents": amount_cents,
            "due_at": plus_days(logical_now(), calc.SETTLEMENT_DUE_DAYS),
            "installment_kind": "SETTLEMENT",
            "installment_state": "SCHEDULED",
            "paid_amount_cents": 0,
            "paid_at": None,
        },
    )


def void_open_installments(booking, reset_overdue=True):
    voided = 0
    for installment in calc.installments_of_booking(booking["id"]):
        if installment["installment_state"] in calc.OPEN_INSTALLMENT_STATES:
            update_record(installment, {"installment_state": "VOIDED"})
            voided += 1
    return voided


# --- inventory return and host stand-down ----------------------------------


def return_units_to_block(booking, block_id):
    """Give a booking's committed units back to its block (block_state untouched)."""
    if block_id is None:
        return None
    block = db.allocation_blocks.get(block_id)
    if block is None:
        return None
    consumed = calc.consumed_units(booking)
    update_record(
        block,
        {
            "committed_units": block["committed_units"] - consumed,
            "released_back_units": block["released_back_units"] + consumed,
        },
    )
    return block


def void_assignments_of_booking(booking):
    hosts = []
    for assignment in calc.assignments_of_booking(booking["id"]):
        if assignment["assignment_state"] != "ASSIGNED":
            continue
        update_record(
            assignment,
            {"assignment_state": "VOIDED", "released_at": logical_now()},
        )
        host = db.on_site_hosts.get(assignment["on_site_host_id"])
        if host is not None and host not in hosts:
            hosts.append(host)
    for host in hosts:
        recompute_host(host)
    return hosts


def release_assignments_of_booking(booking):
    hosts = []
    for assignment in calc.assignments_of_booking(booking["id"]):
        if assignment["assignment_state"] != "ASSIGNED":
            continue
        update_record(
            assignment,
            {"assignment_state": "RELEASED", "released_at": logical_now()},
        )
        host = db.on_site_hosts.get(assignment["on_site_host_id"])
        if host is not None and host not in hosts:
            hosts.append(host)
    for host in hosts:
        recompute_host(host)
    return hosts


def close_packages_of_event(event):
    for package in calc.packages_of_event(event["id"]):
        if package["package_status"] != "CLOSED":
            update_record(package, {"package_status": "CLOSED"})


def _remember(collection, record):
    if record is not None and record not in collection:
        collection.append(record)


# --- event cascades ---------------------------------------------------------


def postpone_freeze_cascade(event):
    """Hops two through four of PRD 3.8: freeze the sold book onto the new window."""
    clients = []
    for booking in calc.bookings_of_event(event["id"]):
        if booking["fulfillment_status"] not in ("RESERVED", "ALLOCATED", "CREDENTIALED"):
            continue
        was_credentialed = booking["fulfillment_status"] == "CREDENTIALED"
        block_id = booking["allocation_block_id"]

        changes = {"fulfillment_status": "REBOOK_PENDING", "allocation_block_id": None}
        if was_credentialed:
            changes["credentials_issued_count"] = 0
        if block_id is not None:
            return_units_to_block(booking, block_id)
        update_record(booking, changes)

        for installment in calc.installments_of_booking(booking["id"]):
            if installment["installment_state"] in calc.OPEN_INSTALLMENT_STATES:
                update_record(
                    installment,
                    {
                        "due_at": event["rebook_deadline_at"],
                        "installment_state": "SCHEDULED",
                    },
                )
        if was_credentialed:
            void_assignments_of_booking(booking)
        _remember(clients, db.clients.get(booking["client_id"]))

    for client in clients:
        recompute_client(client)
    return clients


def cancel_event_cascade(event):
    """The widest cascade in the system (PRD 3.9)."""
    now = logical_now()
    for deal in calc.deals_of_event(event["id"]):
        if deal["deal_status"] in ("SETTLED", "TERMINATED"):
            continue
        update_record(deal, {"deal_status": "TERMINATED"})
        for tranche in calc.tranches_of_deal(deal["id"]):
            if tranche["tranche_state"] == "PENDING":
                update_record(
                    tranche, {"tranche_state": "LAPSED", "lapsed_at": now}
                )
        for block in calc.blocks_of_deal(deal["id"]):
            if block["block_state"] in calc.LIVE_BLOCK_STATES:
                update_record(block, {"block_state": "RECALLED", "recalled_at": now})

    close_packages_of_event(event)

    clients = []
    for booking in calc.bookings_of_event(event["id"]):
        if booking["fulfillment_status"] in ("CANCELLED", "DELIVERED"):
            continue
        pre_paid = booking["paid_cents"]
        was_credentialed = booking["fulfillment_status"] == "CREDENTIALED"
        changes = {
            "fulfillment_status": "CANCELLED",
            "allocation_block_id": None,
            "settlement_variant": "TIER_SCHEDULE",
            "cancellation_fee_cents": 0,
            "refund_cents": pre_paid,
            "balance_due_cents": 0,
            "payment_status": "REFUNDED",
            "paid_cents": pre_paid - pre_paid,
        }
        if was_credentialed:
            changes["credentials_issued_count"] = 0
        update_record(booking, changes)
        void_open_installments(booking)
        void_assignments_of_booking(booking)
        _remember(clients, db.clients.get(booking["client_id"]))

    for build in calc.builds_of_event(event["id"]):
        if build["build_state"] in ("PLANNED", "APPROVED"):
            update_record(build, {"build_state": "CANCELLED"})
        elif build["build_state"] == "READY":
            update_record(build, {"build_state": "CLOSED"})

    for client in clients:
        recompute_client(client)
    return clients


def complete_event_cascade(event):
    """PRD 3.9: deliver the sold book and stand the venue down."""
    for booking in calc.bookings_of_event(event["id"]):
        if booking["fulfillment_status"] in ("ALLOCATED", "CREDENTIALED"):
            update_record(booking, {"fulfillment_status": "DELIVERED"})
        release_assignments_of_booking(booking)

    close_packages_of_event(event)

    for build in calc.builds_of_event(event["id"]):
        if build["build_state"] == "READY":
            update_record(build, {"build_state": "CLOSED"})
        elif build["build_state"] in ("PLANNED", "APPROVED"):
            update_record(build, {"build_state": "CANCELLED"})
