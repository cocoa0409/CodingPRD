"""The group-block review release and the nine-step operations sweep (PRD 3.3, 3.9)."""

import calcs
import cascade
import store


def review_block(block, sailing):
    """Run the review-date release policy. Returns the number of cabins released."""
    cascade.recompute_block(block, bump=False)
    released = calcs.attrition_release(
        block["cabins_held"], block["picked_up_cabins"], block["release_policy"])

    if released <= 0:
        # Zero-release self-loop: legal, and no cabins move.
        block["review_count"] = block["review_count"] + 1
        block["review_date"] = store.iso(store.add_days(
            store.parse_iso(block["review_date"]), calcs.REVIEW_EXTENSION_DAYS))
        store.touch(block)
        return 0

    new_held = block["cabins_held"] - released
    block["cabins_held"] = new_held
    block["released_cabins_total"] = block["released_cabins_total"] + released
    block["review_count"] = block["review_count"] + 1
    block["status"] = "RELEASED" if new_held == 0 else "PARTIALLY_RELEASED"
    store.touch(block)

    inv = cascade.inventory_for(block["sailing_id"], block["cabin_category_id"])
    if inv is not None:
        inv["released_cabins_total"] = inv["released_cabins_total"] + released
        cascade.recompute_inventory(inv, bump=False)
        store.touch(inv)
        # The freed cabins are offered to the waitlist queue immediately.
        cascade.promote_waitlist(sailing, inv)
    return released


def _days_to_sail(sailing):
    return store.days_to_sail(store.parse_iso(sailing["embark_date"]), store.now_dt())


def run_sweep(sailing):
    """The nine steps, in the fixed order, against the current logical clock."""
    now = store.now_dt()
    sailing_id = sailing["id"]

    # ---- 1. expire promotions whose ends_on now lies before the current instant
    for promotion in cascade.promotions_of(sailing_id):
        if promotion["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        ends_on = store.parse_iso(promotion["ends_on"])
        if ends_on is not None and ends_on < now:
            store.apply_changes(promotion, {"status": "EXPIRED"}, bump=True)

    # ---- 2. activate SCHEDULED promotions whose window contains the current instant
    for promotion in cascade.promotions_of(sailing_id):
        if promotion["status"] != "SCHEDULED":
            continue
        starts_on = store.parse_iso(promotion["starts_on"])
        ends_on = store.parse_iso(promotion["ends_on"])
        if starts_on is not None and ends_on is not None and starts_on <= now <= ends_on:
            store.apply_changes(promotion, {"status": "ACTIVE"}, bump=True)

    # ---- 3. review every group block whose review_date has been reached
    for block in cascade.blocks_of(sailing_id):
        if block["status"] not in ("TENTATIVE", "PARTIALLY_RELEASED"):
            continue
        review_date = store.parse_iso(block["review_date"])
        if review_date is not None and review_date <= now:
            review_block(block, sailing)

    # ---- 4. promote waitlisted bookings into whatever is now free
    for inv in cascade.inventories_of(sailing_id):
        cascade.promote_waitlist(sailing, inv)

    # ---- 5. mark overdue bookings DELINQUENT
    for booking in cascade.bookings_of_sailing(sailing_id):
        if booking["booking_status"] not in ("OPTION", "CONFIRMED"):
            continue
        status = booking["payment_status"]
        due = None
        if status == "AWAITING_DEPOSIT":
            due = store.parse_iso(booking["deposit_due_date"])
        elif status == "DEPOSIT_PAID":
            due = store.parse_iso(booking["final_payment_due_date"])
        if due is not None and due < now:
            booking["payment_status"] = "DELINQUENT"
            booking["delinquent_since"] = store.now_iso()
            store.touch(booking)

    # ---- 6. auto-cancel bookings whose seven-day grace period has elapsed
    for booking in cascade.bookings_of_sailing(sailing_id):
        if booking["booking_status"] not in ("OPTION", "CONFIRMED"):
            continue
        if booking["payment_status"] != "DELINQUENT":
            continue
        since = store.parse_iso(booking["delinquent_since"])
        if since is None:
            continue
        if now >= store.add_days(since, calcs.DELINQUENCY_GRACE_DAYS):
            final = calcs.penalty_cents(
                booking["net_ticket_cents"], booking["upgrade_charge_cents"],
                _days_to_sail(sailing))
            cascade.cancel_booking(
                booking, sailing, "AUTO_DELINQUENT",
                provisional_cents=final, final_cents=final, assess_payment=True)

    # ---- 7. expire upgrade bids that have fallen out of the bid window
    days = _days_to_sail(sailing)
    if days < calcs.BID_WINDOW_MIN_DAYS:
        booking_ids = {b["id"] for b in cascade.bookings_of_sailing(sailing_id)}
        for bid in store.upgrade_bids.values():
            if bid["booking_id"] in booking_ids and bid["status"] in ("SUBMITTED", "COUNTERED"):
                store.apply_changes(bid, {"status": "EXPIRED"}, bump=True)

    # ---- 8. departure
    embark = store.parse_iso(sailing["embark_date"])
    if (embark is not None and now >= embark
            and sailing["status"] in ("OPEN_FOR_SALE", "SALES_SUSPENDED", "INVENTORY_CLOSED")):
        sailing["status"] = "SAILED"
        for booking in cascade.bookings_of_sailing(sailing_id):
            if booking["booking_status"] == "CONFIRMED":
                booking["booking_status"] = "SAILED"
                store.touch(booking)
                guest = store.guests.get(booking["guest_id"])
                if guest is not None:
                    guest["prior_sailings_count"] = guest["prior_sailings_count"] + 1
                    cascade.apply_loyalty(guest, bump=False)
                    store.touch(guest)
            elif booking["booking_status"] in ("OPTION", "WAITLISTED"):
                was_waitlisted = booking["booking_status"] == "WAITLISTED"
                provisional = 0 if was_waitlisted else calcs.penalty_cents(
                    booking["net_ticket_cents"], booking["upgrade_charge_cents"],
                    _days_to_sail(sailing))
                cascade.cancel_booking(
                    booking, sailing, "SAILED_UNCONFIRMED",
                    provisional_cents=provisional, assess_payment=True)

    # ---- 9. recompute posture and RALBD last, so they observe every movement
    cascade.recompute_inventories_of(sailing_id, bump=True)
    cascade.recompute_sailing(sailing, bump=False)
    store.touch(sailing)
    return sailing
