"""Reservations: holds, prepayment, add-on lines, dietary notes, floor ops."""
from common import (ApiError, DB, Watch, clock, must_get, new_record, ok,
                    ok_list, parse_iso, public, rows, to_iso)
from calc import (apply_settlement, entries_of_service, lines_of,
                  mint_reservation, minutes, notes_of, prep_minutes_total,
                  promote_after_restore, reservations_of_service,
                  rescore_guest_entries, restaurant_of_res, return_seats,
                  service_of, sync_class, sync_reservation, sync_service,
                  ticket_class_of, write_txn, SEVERITY_PREP_MINUTES)
from guards import (auth, filtered, opt_enum, opt_str, own_guest,
                    own_reservation, own_restaurant, pagination, req_dt,
                    req_enum, req_int, req_str, window)
from routes_catalog import CATALOG_READERS

PAYABLE_STATES = ("PENDING", "CONFIRMED", "SEATED")
RESTRICTIONS = ("GLUTEN", "DAIRY", "SHELLFISH", "NUT", "SOY", "VEGAN",
                "PESCATARIAN", "OTHER")
SEVERITIES = ("INFO", "ALLERGY", "ANAPHYLAXIS")
REJECT_REASONS = ("CROSS_CONTAMINATION_RISK", "INGREDIENT_UNAVAILABLE",
                  "DETAIL_INSUFFICIENT")


def require_state(res, allowed, message):
    if res["fulfillment_status"] not in allowed:
        raise ApiError("ERR_RESERVATION_INVALID_STATE", message)


def require_live_hold(res):
    """Priority 18: a PENDING hold must not have lapsed."""
    if res["fulfillment_status"] == "PENDING" and res["hold_expires_at_utc"]:
        if clock() >= parse_iso(res["hold_expires_at_utc"]):
            raise ApiError("ERR_HOLD_EXPIRED", "this hold has already lapsed")


def safety_gates(res):
    """Priorities 30 and 31, evaluated on table assignment and on seating."""
    notes = notes_of(res["id"])
    for note in notes:
        if note["severity"] == "ANAPHYLAXIS" and note["ack_status"] != "ACKED":
            raise ApiError("ERR_DIETARY_ACK_REQUIRED",
                           "an anaphylaxis note is still unacknowledged")
    for note in notes:
        if note["ack_status"] == "PREP_REJECTED":
            raise ApiError("ERR_DIETARY_NOTE_PREP_REJECTED",
                           "a dietary note is in PREP_REJECTED")


def withdraw_linked_entry(res, w):
    for entry in entries_of_service(res["service_id"]):
        if entry["status"] == "OFFERED" \
                and entry["offered_reservation_id"] == res["id"]:
            w.add(entry)
            entry["status"] = "WITHDRAWN"


def register(app):

    # ---------------------------------------------------------- reservations

    @app.post("/reservations")
    def create_reservation():
        ctx = auth("Guest")
        body = ctx.body
        raw_guest = body.get("guest_id")
        if isinstance(raw_guest, str) and raw_guest.strip() != "":
            own_guest(ctx, raw_guest)
        tc = None
        raw_class = body.get("ticket_class_id")
        if isinstance(raw_class, str) and raw_class.strip() != "":
            tc = must_get("ticket_classes", raw_class)
        guest = None
        if isinstance(raw_guest, str) and raw_guest.strip() != "":
            guest = must_get("guests", raw_guest)
        req_str(body, "ticket_class_id")
        req_str(body, "guest_id")
        party_size = req_int(body, "party_size", 1, None)
        primary_guest_name = req_str(body, "primary_guest_name", max_len=120)
        expected = req_int(body, "expected_ticket_class_version")
        if expected != tc["version"]:
            raise ApiError("ERR_STALE_TICKET_CLASS_VERSION",
                           "the ticket class has moved on since it was read")
        service = DB["services"][tc["service_id"]]
        if service["status"] != "PUBLISHED":
            raise ApiError("ERR_SERVICE_NOT_PUBLISHED",
                           "reservations require a PUBLISHED service")
        if tc["status"] not in ("OPEN", "RELEASED"):
            raise ApiError("ERR_TICKET_CLASS_NOT_SELLABLE",
                           "this ticket class is not sellable")
        if not (tc["min_party_size"] <= party_size <= tc["max_party_size"]):
            raise ApiError("ERR_PARTY_SIZE_OUT_OF_BAND",
                           "the party size sits outside the class band")
        for other in reservations_of_service(service["id"]):
            if other["guest_id"] == guest["id"] \
                    and other["fulfillment_status"] in ("PENDING", "CONFIRMED",
                                                        "SEATED"):
                raise ApiError("ERR_DUPLICATE_ACTIVE_RESERVATION",
                               "this guest already holds a live reservation")
        if tc["seats_available"] < party_size:
            raise ApiError("ERR_INSUFFICIENT_SEATS",
                           "not enough seats remain in the drawing pool")
        w = Watch()
        res = mint_reservation(tc, guest, party_size, primary_guest_name, False, w)
        w.commit()
        return ok(public(res), 201)

    @app.get("/reservations/<rid>")
    def read_reservation(rid):
        ctx = auth(*CATALOG_READERS)
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        return ok(public(res))

    @app.get("/reservations")
    def list_reservations():
        auth(*CATALOG_READERS)
        pagination()
        items, limit, offset, total = window(filtered("reservations", {
            "ticket_class_id": "ticket_class_id",
            "service_id": "service_id",
            "guest_id": "guest_id",
            "assigned_table_id": "assigned_table_id",
            "transferred_from_reservation_id": "transferred_from_reservation_id",
            "fulfillment_status": "fulfillment_status",
            "payment_status": "payment_status",
        }))
        return ok_list(items, limit, offset, total)

    @app.get("/reservations/<rid>/dietary-notes")
    def list_reservation_notes(rid):
        ctx = auth(*CATALOG_READERS)
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        pagination()
        items, limit, offset, total = window(filtered(
            "dietary_notes", {"ack_status": "ack_status"},
            extra=lambda n: n["reservation_id"] == rid))
        return ok_list(items, limit, offset, total)

    # --------------------------------------------------------------- payments

    @app.post("/reservations/<rid>/payments")
    def take_payment(rid):
        ctx = auth("Guest", "GuestServices")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        amount = req_int(ctx.body, "amount_cents", 1, None)
        require_state(res, PAYABLE_STATES,
                      "payments are refused in this seating state")
        require_live_hold(res)
        if amount > res["balance_due_cents"]:
            raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                           "the payment exceeds the outstanding balance")
        paid_before = res["amount_paid_cents"]
        if paid_before == 0 and amount < res["deposit_due_cents"]:
            raise ApiError("ERR_PAYMENT_BELOW_DEPOSIT",
                           "the first payment must settle at least the deposit")
        w = Watch()
        w.add(res)
        if paid_before == 0:
            write_txn(res, "DEPOSIT_CHARGE", amount, "GUEST_PREPAY")
            res["deposit_frozen"] = True
        else:
            write_txn(res, "BALANCE_CHARGE", amount, "GUEST_BALANCE")
        sync_reservation(res, w)
        sync_service(service_of(res), w)
        w.commit()
        return ok(public(res), 201)

    @app.post("/reservations/<rid>/confirm")
    def confirm_reservation(rid):
        ctx = auth("Guest")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        require_state(res, ("PENDING",),
                      "only a PENDING reservation may be confirmed")
        require_live_hold(res)
        if res["payment_status"] not in ("DEPOSIT_PAID", "FULLY_PAID"):
            raise ApiError("ERR_DEPOSIT_NOT_SETTLED",
                           "the deposit has not been settled")
        tc = ticket_class_of(res)
        if tc["status"] == "CLOSED":
            raise ApiError("ERR_TICKET_CLASS_NOT_SELLABLE",
                           "the ticket class is CLOSED")
        w = Watch()
        w.add(res, tc)
        res["fulfillment_status"] = "CONFIRMED"
        res["hold_expires_at_utc"] = None
        res["deposit_frozen"] = True
        tc["seats_held"] -= res["party_size"]
        tc["seats_sold"] += res["party_size"]
        sync_class(tc, w)
        sync_reservation(res, w)
        sync_service(service_of(res), w)
        w.commit()
        return ok(public(res))

    # ------------------------------------------------------- add-on lines

    @app.post("/reservations/<rid>/add-ons")
    def append_add_on(rid):
        ctx = auth("Guest")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        body = ctx.body
        add_on = None
        raw_add_on = body.get("add_on_id")
        if isinstance(raw_add_on, str) and raw_add_on.strip() != "":
            add_on = must_get("add_ons", raw_add_on)
        req_str(body, "add_on_id")
        qty = req_int(body, "qty")
        expected = req_int(body, "expected_reservation_version")
        if expected != res["version"]:
            raise ApiError("ERR_STALE_RESERVATION_VERSION",
                           "the reservation has moved on since it was read")
        require_state(res, PAYABLE_STATES,
                      "add-on lines are refused in this seating state")
        service = service_of(res)
        if add_on["restaurant_id"] != service["restaurant_id"]:
            raise ApiError("ERR_ADDON_RESTAURANT_MISMATCH",
                           "the add-on belongs to another restaurant")
        cutoff = (parse_iso(service["seating_start_utc"])
                  - minutes(add_on["order_cutoff_minutes"]))
        if clock() > cutoff:
            raise ApiError("ERR_ADDON_ORDER_CUTOFF_PASSED",
                           "the add-on order cutoff has passed")
        already = sum(l["qty"] for l in lines_of(res["id"])
                      if l["add_on_id"] == add_on["id"])
        ceiling = add_on["max_qty_per_cover"] * res["party_size"]
        if qty < 1 or already + qty > ceiling:
            raise ApiError("ERR_ADDON_QTY_INVALID",
                           "the quantity breaches the per-cover ceiling")
        w = Watch()
        w.add(res)
        line = new_record("reservation_add_ons", {
            "reservation_id": res["id"],
            "add_on_id": add_on["id"],
            "qty": qty,
            "unit_price_cents_locked": add_on["price_cents"],
            "line_subtotal_cents": add_on["price_cents"] * qty,
            "line_service_charge_cents": 0,
            "line_prep_minutes": add_on["prep_minutes_per_unit"] * qty,
            "ack_required": add_on["requires_kitchen_ack"],
        })
        sync_reservation(res, w)
        w.commit()
        return ok(public(line), 201)

    @app.get("/reservation-add-ons/<lid>")
    def read_line(lid):
        ctx = auth(*CATALOG_READERS)
        line = must_get("reservation_add_ons", lid)
        own_reservation(ctx, DB["reservations"][line["reservation_id"]])
        return ok(public(line))

    @app.get("/reservation-add-ons")
    def list_lines():
        auth(*CATALOG_READERS)
        pagination()
        items, limit, offset, total = window(filtered("reservation_add_ons", {
            "reservation_id": "reservation_id",
            "add_on_id": "add_on_id",
        }))
        return ok_list(items, limit, offset, total)

    # ------------------------------------------------------- dietary notes

    @app.post("/reservations/<rid>/dietary-notes")
    def capture_note(rid):
        ctx = auth("Guest")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        body = ctx.body
        guest_index = req_int(body, "guest_index")
        restriction = req_enum(body, "restriction_code", RESTRICTIONS)
        severity = req_enum(body, "severity", SEVERITIES)
        note_text = opt_str(body, "note_text", "", max_len=500)
        require_state(res, PAYABLE_STATES,
                      "dietary notes are refused in this seating state")
        if guest_index < 1 or guest_index > res["party_size"]:
            raise ApiError("ERR_GUEST_INDEX_OUT_OF_RANGE",
                           "guest_index falls outside the party")
        w = Watch()
        w.add(res)
        note = new_record("dietary_notes", {
            "reservation_id": res["id"],
            "guest_index": guest_index,
            "restriction_code": restriction,
            "severity": severity,
            "note_text": note_text,
            "prep_minutes": SEVERITY_PREP_MINUTES[severity],
            "ack_status": "PENDING",
            "reject_reason_code": None,
            "amend_count": 0,
            "acked_by_user_id": None,
        })
        sync_reservation(res, w)
        w.commit()
        return ok(public(note), 201)

    @app.get("/dietary-notes/<nid>")
    def read_note(nid):
        ctx = auth(*CATALOG_READERS)
        note = must_get("dietary_notes", nid)
        own_reservation(ctx, DB["reservations"][note["reservation_id"]])
        return ok(public(note))

    @app.post("/dietary-notes/<nid>/ack")
    def ack_note(nid):
        ctx = auth("KitchenLead")
        note = must_get("dietary_notes", nid)
        res = DB["reservations"][note["reservation_id"]]
        own_restaurant(ctx, service_of(res)["restaurant_id"])
        decision = req_enum(ctx.body, "decision", ("ACCEPT", "REJECT"))
        reason = opt_enum(ctx.body, "reject_reason_code", REJECT_REASONS)
        if decision == "REJECT" and reason is None:
            raise ApiError("ERR_VALIDATION",
                           "reject_reason_code is required when rejecting")
        if note["ack_status"] != "PENDING":
            raise ApiError("ERR_DIETARY_NOTE_INVALID_STATE",
                           "only a PENDING note may be decided")
        w = Watch()
        w.add(note)
        if decision == "ACCEPT":
            if res["fulfillment_status"] != "CONFIRMED":
                raise ApiError("ERR_RESERVATION_INVALID_STATE",
                               "the reservation must be CONFIRMED")
            if clock() >= parse_iso(service_of(res)["seating_start_utc"]):
                raise ApiError("ERR_DIETARY_NOTE_INVALID_STATE",
                               "the service has already started seating")
            note["ack_status"] = "ACKED"
            note["acked_by_user_id"] = ctx.user_id
        else:
            note["ack_status"] = "PREP_REJECTED"
            note["reject_reason_code"] = reason
        sync_reservation(res, w)
        w.commit()
        return ok(public(note))

    @app.post("/dietary-notes/<nid>/amend")
    def amend_note(nid):
        ctx = auth("Guest")
        note = must_get("dietary_notes", nid)
        res = DB["reservations"][note["reservation_id"]]
        own_reservation(ctx, res)
        body = ctx.body
        restriction = opt_enum(body, "restriction_code", RESTRICTIONS)
        severity = opt_enum(body, "severity", SEVERITIES)
        note_text = opt_str(body, "note_text", None, max_len=500)
        if note["ack_status"] != "PREP_REJECTED":
            raise ApiError("ERR_DIETARY_NOTE_INVALID_STATE",
                           "only a PREP_REJECTED note may be amended")
        if note["amend_count"] >= 3:
            raise ApiError("ERR_DIETARY_AMEND_LIMIT",
                           "this note has been amended three times already")
        w = Watch()
        w.add(note)
        if restriction is not None:
            note["restriction_code"] = restriction
        if severity is not None:
            note["severity"] = severity
        if note_text is not None:
            note["note_text"] = note_text
        note["ack_status"] = "PENDING"
        note["amend_count"] += 1
        note["reject_reason_code"] = None
        note["acked_by_user_id"] = None
        note["prep_minutes"] = SEVERITY_PREP_MINUTES[note["severity"]]
        sync_reservation(res, w)
        w.commit()
        return ok(public(note))

    # ---------------------------------------------------------- working the floor

    @app.post("/reservations/<rid>/assign-table")
    def assign_table(rid):
        ctx = auth("RestaurantManager")
        res = must_get("reservations", rid)
        service = service_of(res)
        own_restaurant(ctx, service["restaurant_id"])
        body = ctx.body
        table = None
        raw_table = body.get("table_id")
        if isinstance(raw_table, str) and raw_table.strip() != "":
            table = must_get("tables", raw_table)
        req_str(body, "table_id")
        seat_from = req_dt(body, "seat_from_utc")
        require_state(res, ("CONFIRMED",),
                      "only a CONFIRMED reservation may be assigned a table")
        safety_gates(res)
        restaurant = restaurant_of_res(res)
        cand_from = seat_from
        cand_to = (cand_from + minutes(service["turn_time_minutes"])
                   + minutes(table["turn_buffer_minutes"]))
        for other in rows("reservations"):
            if other["id"] == res["id"]:
                continue
            if other["assigned_table_id"] != table["id"]:
                continue
            if other["fulfillment_status"] not in ("CONFIRMED", "SEATED"):
                continue
            if not other["seat_from_utc"]:
                continue
            other_from = parse_iso(other["seat_from_utc"])
            other_to = (other_from
                        + minutes(service_of(other)["turn_time_minutes"])
                        + minutes(table["turn_buffer_minutes"]))
            if cand_from < other_to and other_from < cand_to:
                raise ApiError("ERR_TABLE_TURN_CONFLICT",
                               "the table is already occupied in that turn")
        if table["restaurant_id"] != service["restaurant_id"]:
            raise ApiError("ERR_TABLE_RESTAURANT_MISMATCH",
                           "the table belongs to another restaurant")
        if not (table["seats_min"] <= res["party_size"] <= table["seats_max"]):
            raise ApiError("ERR_TABLE_PARTY_SIZE_MISMATCH",
                           "the party does not fit the table's seat band")
        cand_lo = cand_from - minutes(restaurant["prep_lead_minutes"])
        cand_hi = cand_from
        load = prep_minutes_total(res)
        for other in reservations_of_service(service["id"]):
            if other["id"] == res["id"]:
                continue
            if not other["assigned_table_id"] or not other["seat_from_utc"]:
                continue
            if other["fulfillment_status"] not in ("CONFIRMED", "SEATED"):
                continue
            other_hi = parse_iso(other["seat_from_utc"])
            other_lo = other_hi - minutes(restaurant["prep_lead_minutes"])
            if cand_lo <= other_hi and other_lo <= cand_hi:
                load += other["prep_minutes_total"]
        if load > service["kitchen_prep_capacity_minutes"]:
            raise ApiError("ERR_KITCHEN_PREP_OVERSUBSCRIBED",
                           "the kitchen prep window is oversubscribed")
        w = Watch()
        w.add(res)
        res["assigned_table_id"] = table["id"]
        res["seat_from_utc"] = to_iso(seat_from)
        sync_reservation(res, w)
        w.commit()
        return ok(public(res))

    @app.post("/reservations/<rid>/seat")
    def seat_reservation(rid):
        ctx = auth("RestaurantManager")
        res = must_get("reservations", rid)
        service = service_of(res)
        own_restaurant(ctx, service["restaurant_id"])
        require_state(res, ("CONFIRMED",),
                      "only a CONFIRMED reservation may be seated")
        if not res["assigned_table_id"] or not res["seat_from_utc"]:
            raise ApiError("ERR_RESERVATION_INVALID_STATE",
                           "no table has been assigned yet")
        safety_gates(res)
        seat_from = parse_iso(res["seat_from_utc"])
        if clock() < seat_from:
            raise ApiError("ERR_SEATING_TOO_EARLY",
                           "the seating instant has not been reached")
        w = Watch()
        w.add(res)
        res["fulfillment_status"] = "SEATED"
        res["seat_to_utc"] = to_iso(seat_from
                                    + minutes(service["turn_time_minutes"]))
        sync_reservation(res, w)
        w.commit()
        return ok(public(res))

    @app.post("/reservations/<rid>/complete")
    def complete_reservation(rid):
        ctx = auth("RestaurantManager")
        res = must_get("reservations", rid)
        service = service_of(res)
        own_restaurant(ctx, service["restaurant_id"])
        require_state(res, ("SEATED",),
                      "only a SEATED reservation may be completed")
        if res["payment_status"] != "FULLY_PAID":
            raise ApiError("ERR_BALANCE_OUTSTANDING",
                           "the balance is still outstanding")
        w = Watch()
        w.add(res)
        res["fulfillment_status"] = "COMPLETED"
        guest = DB["guests"][res["guest_id"]]
        w.add(guest)
        guest["completed_reservations_count"] += 1
        rescore_guest_entries(guest, w)
        sync_reservation(res, w)
        sync_service(service, w)
        w.commit()
        return ok(public(res))

    @app.post("/reservations/<rid>/no-show")
    def declare_no_show(rid):
        ctx = auth("RestaurantManager")
        res = must_get("reservations", rid)
        service = service_of(res)
        own_restaurant(ctx, service["restaurant_id"])
        restaurant = restaurant_of_res(res)
        require_state(res, ("CONFIRMED",),
                      "only a CONFIRMED reservation may be declared a no-show")
        if not res["seat_from_utc"]:
            raise ApiError("ERR_NO_SHOW_TOO_EARLY",
                           "no seating instant has been set")
        threshold = (parse_iso(res["seat_from_utc"])
                     + minutes(restaurant["no_show_grace_minutes"]))
        if clock() < threshold:
            raise ApiError("ERR_NO_SHOW_TOO_EARLY",
                           "the no-show grace period has not elapsed")
        tc = ticket_class_of(res)
        w = Watch()
        w.add(res, tc)
        res["fulfillment_status"] = "NO_SHOW"
        apply_settlement(res, "NO_SHOW", "NO_SHOW", w)
        guest = DB["guests"][res["guest_id"]]
        w.add(guest)
        guest["no_show_strikes"] += 1
        rescore_guest_entries(guest, w)
        previous_status = tc["status"]
        tc["seats_sold"] -= res["party_size"]
        tc["seats_available"] += res["party_size"]
        sync_class(tc, w)
        promote_after_restore(tc, previous_status, w)
        sync_reservation(res, w)
        sync_service(service, w)
        w.commit()
        return ok(public(res))

    # ------------------------------------------------- cancel, rename, transfer

    @app.post("/reservations/<rid>/cancel")
    def cancel_reservation(rid):
        ctx = auth("Guest", "GuestServices")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        require_state(res, ("PENDING", "CONFIRMED"),
                      "this reservation can no longer be cancelled")
        if res["fulfillment_status"] == "CONFIRMED" and res["seat_from_utc"]:
            if clock() >= parse_iso(res["seat_from_utc"]):
                raise ApiError("ERR_CANCEL_WINDOW_CLOSED",
                               "the cancellation window has closed")
        tc = ticket_class_of(res)
        service = service_of(res)
        w = Watch()
        w.add(res, tc)
        previous = res["fulfillment_status"]
        previous_class_status = tc["status"]
        apply_settlement(res, "GUEST_CANCEL", "GUEST_CANCEL", w)
        res["fulfillment_status"] = "CANCELLED"
        if previous == "PENDING":
            return_seats(tc, res, w)
            withdraw_linked_entry(res, w)
        else:
            tc["seats_sold"] -= res["party_size"]
            tc["seats_available"] += res["party_size"]
            sync_class(tc, w)
        promote_after_restore(tc, previous_class_status, w)
        sync_reservation(res, w)
        sync_service(service, w)
        w.commit()
        return ok(public(res))

    @app.post("/reservations/<rid>/name-change")
    def change_name(rid):
        ctx = auth("Guest")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        new_name = req_str(ctx.body, "primary_guest_name", max_len=120)
        require_state(res, ("PENDING", "CONFIRMED"),
                      "this reservation can no longer be renamed")
        service = service_of(res)
        restaurant = restaurant_of_res(res)
        cutoff = (parse_iso(service["seating_start_utc"])
                  - minutes(restaurant["name_change_cutoff_minutes"]))
        if clock() > cutoff:
            raise ApiError("ERR_NAME_CHANGE_CUTOFF_PASSED",
                           "the name-change cutoff has passed")
        if res["name_change_count"] >= restaurant["max_name_changes"]:
            raise ApiError("ERR_NAME_CHANGE_LIMIT_REACHED",
                           "no name changes remain on this reservation")
        w = Watch()
        w.add(res)
        res["primary_guest_name"] = new_name
        res["name_change_count"] += 1
        w.commit()
        return ok(public(res))

    @app.post("/reservations/<rid>/transfer")
    def transfer_reservation(rid):
        ctx = auth("Guest")
        res = must_get("reservations", rid)
        own_reservation(ctx, res)
        body = ctx.body
        recipient = None
        raw_recipient = body.get("recipient_guest_id")
        if isinstance(raw_recipient, str) and raw_recipient.strip() != "":
            recipient = must_get("guests", raw_recipient)
        req_str(body, "recipient_guest_id")
        recipient_name = opt_str(body, "recipient_guest_name", None, max_len=120,
                                allow_empty=False)
        service = service_of(res)
        restaurant = restaurant_of_res(res)
        require_state(res, ("CONFIRMED",),
                      "only a CONFIRMED reservation may be transferred")
        if res["payment_status"] != "FULLY_PAID":
            raise ApiError("ERR_TRANSFER_REQUIRES_FULL_PAYMENT",
                           "a partly paid ticket cannot be handed on")
        cutoff = (parse_iso(service["seating_start_utc"])
                  - minutes(restaurant["transfer_cutoff_minutes"]))
        if clock() > cutoff:
            raise ApiError("ERR_TRANSFER_CUTOFF_PASSED",
                           "the transfer cutoff has passed")
        if recipient["is_broker_flagged"]:
            raise ApiError("ERR_RESALE_SUSPECTED",
                           "the recipient is flagged as a broker")
        if res["transferred_from_reservation_id"] is not None:
            raise ApiError("ERR_ONWARD_TRANSFER_FORBIDDEN",
                           "a transferred ticket may not be transferred again")
        initiator = DB["guests"][res["guest_id"]]
        if initiator["transfers_initiated_count"] >= restaurant["max_transfers_per_guest"]:
            raise ApiError("ERR_TRANSFER_LIMIT_REACHED",
                           "this guest has no transfers left")
        if recipient["id"] == res["guest_id"]:
            raise ApiError("ERR_TRANSFER_TO_SELF",
                           "the recipient must differ from the current holder")
        w = Watch()
        w.add(res, initiator)
        paid = res["amount_paid_cents"]
        successor = new_record("reservations", {
            "service_id": res["service_id"],
            "ticket_class_id": res["ticket_class_id"],
            "guest_id": recipient["id"],
            "assigned_table_id": None,
            "transferred_from_reservation_id": res["id"],
            "party_size": res["party_size"],
            "primary_guest_name": recipient_name or recipient["display_name"],
            "fulfillment_status": "CONFIRMED",
            "payment_status": "FULLY_PAID",
            "is_release_priced": res["is_release_priced"],
            "price_locked_per_cover_cents": res["price_locked_per_cover_cents"],
            "ticket_subtotal_cents": res["ticket_subtotal_cents"],
            "add_on_total_cents": res["add_on_total_cents"],
            "service_charge_cents": res["service_charge_cents"],
            "grand_total_cents": res["grand_total_cents"],
            "deposit_due_cents": res["deposit_due_cents"],
            "deposit_frozen": True,
            "balance_due_cents": 0,
            "amount_paid_cents": 0,
            "goodwill_applied_cents": 0,
            "refunded_cents": 0,
            "forfeited_cents": 0,
            "hold_expires_at_utc": None,
            "seat_from_utc": None,
            "seat_to_utc": None,
            "prep_minutes_total": 0,
            "name_change_count": 0,
            "cancel_settlement_basis": None,
        })
        for line in lines_of(res["id"]):
            new_record("reservation_add_ons", {
                "reservation_id": successor["id"],
                "add_on_id": line["add_on_id"],
                "qty": line["qty"],
                "unit_price_cents_locked": line["unit_price_cents_locked"],
                "line_subtotal_cents": line["line_subtotal_cents"],
                "line_service_charge_cents": line["line_service_charge_cents"],
                "line_prep_minutes": line["line_prep_minutes"],
                "ack_required": line["ack_required"],
            })
        for note in notes_of(res["id"]):
            new_record("dietary_notes", {
                "reservation_id": successor["id"],
                "guest_index": note["guest_index"],
                "restriction_code": note["restriction_code"],
                "severity": note["severity"],
                "note_text": note["note_text"],
                "prep_minutes": note["prep_minutes"],
                "ack_status": "PENDING",
                "reject_reason_code": None,
                "amend_count": note["amend_count"],
                "acked_by_user_id": None,
            })
        if paid > 0:
            write_txn(res, "TRANSFER_OUT", paid, "TRANSFER_MOVE")
            write_txn(successor, "TRANSFER_IN", paid, "TRANSFER_MOVE")
        res["fulfillment_status"] = "TRANSFERRED_OUT"
        initiator["transfers_initiated_count"] += 1
        rescore_guest_entries(initiator, w)
        sync_reservation(res, w)
        sync_reservation(successor)
        sync_service(service, w)
        w.commit()
        return ok(public(successor), 201)
