"""The two transitive cascades: the depth-5 form-publication staleness cascade
(PRD 3.2) and the depth-4 withdrawal cascade (PRD 3.11 / 3.12)."""
import store
from services import lookup, slots


def publish_cascade(published):
    """HOP 1..5. Each hop is caused by the hop before it, not by the request."""
    prior = None
    for row in store.all_rows("agency_forms"):
        if (row["form_code"] == published["form_code"]
                and row["id"] != published["id"]
                and row["status"] == "ACTIVE"):
            prior = row
            break
    if prior is None:
        return

    # HOP 1
    prior["status"] = "SUPERSEDED"
    store.touch(prior)

    # HOP 2
    stale_applicant_ids = set()
    for form in store.all_rows("prepared_forms"):
        if form["agency_form_id"] != prior["id"]:
            continue
        if form["prep_status"] not in ("PREPARED", "SIGNED"):
            continue
        if form["prep_status"] == "SIGNED":
            form["signed_at"] = None
            form["signed_by_user_id"] = None
        form["prep_status"] = "STALE"
        store.touch(form)
        stale_applicant_ids.add(form["applicant_id"])

    # HOP 3
    regressed_order_ids = set()
    for applicant_id in stale_applicant_ids:
        applicant = store.get("applicants", applicant_id)
        if applicant is None or applicant["readiness_status"] != "COMPLETE":
            continue
        applicant["readiness_status"] = "PENDING"
        store.touch(applicant)
        regressed_order_ids.add(applicant["order_id"])

    # HOP 4
    for order_id in regressed_order_ids:
        order = store.get("orders", order_id)
        if order is None or order["workflow_status"] != "READY_FOR_SUBMISSION":
            continue
        order["workflow_status"] = "INTAKE"
        order["feasibility_status"] = "UNKNOWN"
        order["acknowledged_by_user_id"] = None
        store.touch(order)
        # HOP 5
        for leg in lookup.legs_of(order):
            if leg["leg_status"] == "CREATED":
                leg["leg_status"] = "CANCELLED"
                store.touch(leg)


def withdraw_applicants(order):
    """Hop 1 -> 2 -> 3: applicant WITHDRAWN, BOOKED appointments CANCELLED,
    slot capacity released and slot status re-derived."""
    for applicant in lookup.applicants_of(order):
        if applicant["readiness_status"] not in ("PENDING", "COMPLETE"):
            continue
        applicant["readiness_status"] = "WITHDRAWN"
        store.touch(applicant)
        for appointment in lookup.appointments_of(applicant):
            if appointment["booking_status"] != "BOOKED":
                continue
            appointment["booking_status"] = "CANCELLED"
            store.touch(appointment)
            slot = store.get("slots", appointment["slot_id"])
            if slot is not None:
                slots.release_seat(slot)


def cancel_outstanding_legs(order):
    """Adjudication of friction 2: a cancellation kills hops in CREATED or
    FAILED (the two from-states the leg axis declares for CANCELLED); the
    DISPATCHED reading would leave FAILED -> CANCELLED unreachable and would
    introduce an undeclared transition."""
    for leg in lookup.legs_of(order):
        if leg["leg_status"] in ("CREATED", "FAILED"):
            leg["leg_status"] = "CANCELLED"
            store.touch(leg)
