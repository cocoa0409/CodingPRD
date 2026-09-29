"""Ledger reads, the waitlist, refund exceptions, goodwill credit, the clock."""
from common import (ApiError, DB, Watch, clock, must_get, new_record, ok,
                    ok_list, parse_iso, public, rows, set_clock, to_iso)
from calc import (credit_guest_refund, entries_of_service, rescore,
                  restaurant_of_res, restaurant_of_service, return_seats,
                  service_of, sync_reservation, sync_service, ticket_class_of,
                  write_txn)
from guards import (auth, filtered, fk_exists, opt_str, own_guest,
                    own_reservation, own_restaurant, pagination, req_dt,
                    req_enum, req_int, req_str, window)

MONEY_READERS = ("PlatformAdmin", "RestaurantManager", "GuestServices", "Guest")
REASON_CODES = ("MEDICAL", "TRAVEL_DISRUPTION", "KITCHEN_ERROR", "WEATHER",
                "OTHER")
NOTE_CODES = ("POLICY_EXCEPTION", "PARTIAL_GOODWILL", "EVIDENCE_INSUFFICIENT",
              "OUT_OF_POLICY")
DECISIONS = ("APPROVED", "DENIED")
CREDIT_LIVE = ("ISSUED", "PARTIALLY_REDEEMED")


def own_credit(ctx, credit):
    """§2.1: a credit is scoped to one guest at one restaurant."""
    own_guest(ctx, credit["guest_id"])
    own_restaurant(ctx, credit["restaurant_id"])


def reservation_of(rec):
    return DB["reservations"][rec["reservation_id"]]


def redemptions_of(credit_id):
    return [t for t in rows("payment_transactions")
            if t["kind"] == "GOODWILL_REDEMPTION"
            and t["goodwill_credit_id"] == credit_id]


def sync_credit(credit, w=None):
    """§3.9: the four money figures, then the pinned status precedence."""
    if w is not None:
        w.add(credit)
    redeemed = sum(t["amount_cents"] for t in redemptions_of(credit["id"]))
    credit["redeemed_cents"] = redeemed
    credit["remaining_cents"] = (credit["issued_cents"] - redeemed
                                 - credit["revoked_cents"])
    if credit["revoked_cents"] > 0:
        credit["status"] = "REVOKED"
    elif credit["remaining_cents"] == 0:
        credit["status"] = "EXHAUSTED"
    elif 0 < redeemed < credit["issued_cents"]:
        credit["status"] = "PARTIALLY_REDEEMED"
    else:
        credit["status"] = "ISSUED"
    return credit


def register(app):

    # ------------------------------------------------------- the money ledger

    @app.get("/payment-transactions/<tid>")
    def read_transaction(tid):
        ctx = auth(*MONEY_READERS)
        txn = must_get("payment_transactions", tid)
        own_reservation(ctx, reservation_of(txn))
        return ok(public(txn))

    @app.get("/payment-transactions")
    def list_transactions():
        auth(*MONEY_READERS)
        pagination()
        items, limit, offset, total = window(filtered("payment_transactions", {
            "reservation_id": "reservation_id",
            "goodwill_credit_id": "goodwill_credit_id",
            "kind": "kind",
            "memo_code": "memo_code",
        }))
        return ok_list(items, limit, offset, total)

    # ------------------------------------------------------------- waitlist

    @app.post("/waitlist-entries")
    def join_waitlist():
        ctx = auth("Guest")
        body = ctx.body
        own_guest(ctx, body.get("guest_id"))
        service = fk_exists(body, "service_id", "services")
        guest = fk_exists(body, "guest_id", "guests")
        package = fk_exists(body, "requested_package_id", "packages")
        req_str(body, "service_id")
        req_str(body, "guest_id")
        party_size = req_int(body, "party_size", minimum=1, maximum=20)
        opt_str(body, "requested_package_id", None, allow_empty=False)
        if service["status"] != "PUBLISHED":
            raise ApiError("ERR_SERVICE_NOT_PUBLISHED",
                           "the service is not open for waitlisting")
        if package is not None:
            if not (package["min_party_size"] <= party_size
                    <= package["max_party_size"]):
                raise ApiError("ERR_PARTY_SIZE_OUT_OF_BAND",
                               "the party does not fit the requested package")
        restaurant = restaurant_of_service(service)
        for entry in entries_of_service(service["id"]):
            if entry["guest_id"] != guest["id"]:
                continue
            if entry["status"] in ("WAITING", "OFFERED"):
                raise ApiError("ERR_DUPLICATE_WAITLIST_ENTRY",
                               "this guest is already on this waitlist")
        for entry in entries_of_service(service["id"]):
            if entry["guest_id"] != guest["id"]:
                continue
            if entry["status"] == "EXPIRED" \
                    and entry["offer_round"] >= restaurant["max_offer_rounds"]:
                raise ApiError("ERR_OFFER_ROUNDS_EXHAUSTED",
                               "this guest has exhausted its offer rounds")
        entry = new_record("waitlist_entries", {
            "service_id": service["id"],
            "guest_id": guest["id"],
            "requested_package_id": package["id"] if package else None,
            "offered_reservation_id": None,
            "party_size": party_size,
            "status": "WAITING",
            "offer_round": 0,
            "offer_expires_at_utc": None,
            "priority_penalty_applied": bool(guest["refund_scrutiny_flag"]),
            "priority_score": 0,
        })
        rescore(entry)
        return ok(public(entry), 201)

    @app.get("/waitlist-entries/<eid>")
    def read_entry(eid):
        ctx = auth(*MONEY_READERS)
        entry = must_get("waitlist_entries", eid)
        own_guest(ctx, entry["guest_id"])
        own_restaurant(ctx, DB["services"][entry["service_id"]]["restaurant_id"])
        return ok(public(entry))

    @app.get("/waitlist-entries")
    def list_entries():
        auth(*MONEY_READERS)
        pagination()
        items, limit, offset, total = window(filtered("waitlist_entries", {
            "service_id": "service_id",
            "guest_id": "guest_id",
            "requested_package_id": "requested_package_id",
            "offered_reservation_id": "offered_reservation_id",
            "status": "status",
        }))
        return ok_list(items, limit, offset, total)

    @app.post("/waitlist-entries/<eid>/claim")
    def claim_offer(eid):
        ctx = auth("Guest")
        entry = must_get("waitlist_entries", eid)
        own_guest(ctx, entry["guest_id"])
        offered = None
        if entry["offered_reservation_id"]:
            offered = DB["reservations"].get(entry["offered_reservation_id"])
        if offered is not None:
            # Ladder 15: the class is sellable — "OPEN, RELEASED or SOLD_OUT for
            # a waitlist claim".
            tc = ticket_class_of(offered)
            if tc["status"] not in ("OPEN", "RELEASED", "SOLD_OUT"):
                raise ApiError("ERR_TICKET_CLASS_NOT_SELLABLE",
                               "the offered ticket class is not sellable")
            # Ladder 18 is qualified: "For a PENDING reservation, the logical
            # clock is strictly before hold_expires_at_utc".
            if offered["fulfillment_status"] == "PENDING" \
                    and offered["hold_expires_at_utc"] \
                    and clock() >= parse_iso(offered["hold_expires_at_utc"]):
                raise ApiError("ERR_HOLD_EXPIRED", "the offered hold has lapsed")
        # Ladder 22: the entry's own status. Ladder 17 does not list a waitlist
        # claim among the operations it guards, and §3.8 enumerates the claim's
        # preconditions with the entry's status first, so the entry-status check
        # precedes the offered reservation's own state check.
        if entry["status"] != "OFFERED":
            raise ApiError("ERR_WAITLIST_ENTRY_INVALID_STATE",
                           "only an OFFERED entry may be claimed")
        # Ladder 23.
        if entry["offer_expires_at_utc"] \
                and clock() >= parse_iso(entry["offer_expires_at_utc"]):
            raise ApiError("ERR_OFFER_EXPIRED", "this offer has lapsed")
        # §3.8: "the offered reservation to still be PENDING".
        if offered is not None and offered["fulfillment_status"] != "PENDING":
            raise ApiError("ERR_RESERVATION_INVALID_STATE",
                           "the offered hold is no longer PENDING")
        w = Watch()
        w.add(entry)
        entry["status"] = "CLAIMED"
        entry["offer_expires_at_utc"] = None
        w.commit()
        return ok(public(entry))

    @app.post("/waitlist-entries/<eid>/withdraw")
    def withdraw_entry(eid):
        ctx = auth("Guest")
        entry = must_get("waitlist_entries", eid)
        own_guest(ctx, entry["guest_id"])
        if entry["status"] not in ("WAITING", "OFFERED"):
            raise ApiError("ERR_WAITLIST_ENTRY_INVALID_STATE",
                           "this entry is no longer live")
        previous = entry["status"]
        w = Watch()
        w.add(entry)
        entry["status"] = "WITHDRAWN"
        if previous == "OFFERED":
            offered = None
            if entry["offered_reservation_id"]:
                offered = DB["reservations"].get(entry["offered_reservation_id"])
            if offered is not None and offered["fulfillment_status"] == "PENDING":
                tc = ticket_class_of(offered)
                w.add(offered, tc)
                offered["fulfillment_status"] = "CANCELLED"
                return_seats(tc, offered, w)
                sync_reservation(offered, w)
        w.commit()
        return ok(public(entry))

    # ----------------------------------------------------- refund exceptions

    @app.post("/refund-exceptions")
    def file_exception():
        ctx = auth("Guest", "GuestServices")
        body = ctx.body
        res = fk_exists(body, "reservation_id", "reservations")
        own_reservation(ctx, res)
        req_str(body, "reservation_id")
        reason_code = req_enum(body, "reason_code", REASON_CODES)
        requested = req_int(body, "requested_cents", minimum=1)
        headroom = res["amount_paid_cents"] - res["refunded_cents"]
        if requested > headroom:
            raise ApiError("ERR_REFUND_REQUEST_EXCEEDS_PAID",
                           "the request exceeds the money still held")
        exc = new_record("refund_exceptions", {
            "reservation_id": res["id"],
            "reason_code": reason_code,
            "requested_cents": requested,
            "status": "REQUESTED",
            "requested_by_user_id": ctx.user_id,
            "decided_by_user_id": None,
            "approved_cents": 0,
            "shortfall_cents": 0,
            "decision_note_code": None,
        })
        return ok(public(exc), 201)

    @app.get("/refund-exceptions/<xid>")
    def read_exception(xid):
        ctx = auth(*MONEY_READERS)
        exc = must_get("refund_exceptions", xid)
        own_reservation(ctx, reservation_of(exc))
        return ok(public(exc))

    @app.get("/refund-exceptions")
    def list_exceptions():
        auth(*MONEY_READERS)
        pagination()
        items, limit, offset, total = window(filtered("refund_exceptions", {
            "reservation_id": "reservation_id",
            "status": "status",
            "reason_code": "reason_code",
        }))
        return ok_list(items, limit, offset, total)

    @app.post("/refund-exceptions/<xid>/decide")
    def decide_exception(xid):
        ctx = auth("GuestServices")
        exc = must_get("refund_exceptions", xid)
        body = ctx.body
        decision = req_enum(body, "decision", DECISIONS)
        note_code = req_enum(body, "decision_note_code", NOTE_CODES)
        approved = 0
        if decision == "APPROVED":
            approved = req_int(body, "approved_cents", minimum=1)
        if ctx.user_id == exc["requested_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the filing operator may not decide the exception")
        if exc["status"] != "REQUESTED":
            raise ApiError("ERR_REFUND_EXCEPTION_ALREADY_DECIDED",
                           "this exception has already been decided")
        res = reservation_of(exc)
        if decision == "APPROVED":
            if approved > exc["requested_cents"]:
                raise ApiError("ERR_APPROVED_EXCEEDS_REQUESTED",
                               "more was approved than was asked for")
            if approved > res["forfeited_cents"]:
                raise ApiError("ERR_APPROVED_EXCEEDS_FORFEITED",
                               "more was approved than was ever forfeited")
        w = Watch()
        w.add(exc)
        exc["decided_by_user_id"] = ctx.user_id
        exc["decision_note_code"] = note_code
        if decision == "APPROVED":
            exc["status"] = "APPROVED"
            exc["approved_cents"] = approved
            exc["shortfall_cents"] = exc["requested_cents"] - approved
            w.add(res)
            write_txn(res, "FORFEITURE_REVERSAL", approved, "REFUND_EXCEPTION")
            write_txn(res, "REFUND", approved, "REFUND_EXCEPTION")
            sync_reservation(res, w)
            credit_guest_refund(res, approved, w)
            sync_service(service_of(res), w)
        else:
            exc["status"] = "DENIED"
            exc["approved_cents"] = 0
            exc["shortfall_cents"] = exc["requested_cents"]
        w.commit()
        return ok(public(exc))

    # ------------------------------------------------------ goodwill credits

    @app.post("/goodwill-credits")
    def issue_credit():
        ctx = auth("GuestServices")
        body = ctx.body
        exc = fk_exists(body, "refund_exception_id", "refund_exceptions")
        req_str(body, "refund_exception_id")
        issued = req_int(body, "issued_cents", minimum=1)
        expires = req_dt(body, "expires_at_utc")
        if expires <= clock():
            raise ApiError("ERR_VALIDATION",
                           "expires_at_utc must be after the logical clock")
        if ctx.user_id == exc["decided_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the deciding operator may not issue the credit")
        if exc["status"] != "APPROVED":
            raise ApiError("ERR_REFUND_EXCEPTION_NOT_APPROVED",
                           "a credit needs an APPROVED exception")
        res = reservation_of(exc)
        service = service_of(res)
        restaurant = restaurant_of_res(res)
        cap = min(restaurant["goodwill_credit_cap_cents"], exc["shortfall_cents"])
        if issued > cap:
            raise ApiError("ERR_GOODWILL_EXCEEDS_CAP",
                           "the credit exceeds the issuable ceiling")
        credit = new_record("goodwill_credits", {
            "refund_exception_id": exc["id"],
            "guest_id": res["guest_id"],
            "restaurant_id": service["restaurant_id"],
            "issued_cents": issued,
            "expires_at_utc": to_iso(expires),
            "redeemed_cents": 0,
            "revoked_cents": 0,
            "remaining_cents": issued,
            "status": "ISSUED",
            "issued_by_user_id": ctx.user_id,
        })
        return ok(public(credit), 201)

    @app.get("/goodwill-credits/<cid>")
    def read_credit(cid):
        ctx = auth(*MONEY_READERS)
        credit = must_get("goodwill_credits", cid)
        own_credit(ctx, credit)
        return ok(public(credit))

    @app.get("/goodwill-credits")
    def list_credits():
        auth(*MONEY_READERS)
        pagination()
        items, limit, offset, total = window(filtered("goodwill_credits", {
            "guest_id": "guest_id",
            "restaurant_id": "restaurant_id",
            "refund_exception_id": "refund_exception_id",
            "status": "status",
        }))
        return ok_list(items, limit, offset, total)

    @app.post("/goodwill-credits/<cid>/redemptions")
    def redeem_credit(cid):
        ctx = auth("Guest", "GuestServices")
        credit = must_get("goodwill_credits", cid)
        own_credit(ctx, credit)
        body = ctx.body
        res = fk_exists(body, "reservation_id", "reservations")
        req_str(body, "reservation_id")
        amount = req_int(body, "amount_cents", minimum=1)
        expected = req_int(body, "expected_goodwill_credit_version")
        if expected != credit["version"]:
            raise ApiError("ERR_STALE_GOODWILL_CREDIT_VERSION",
                           "the credit has moved on since it was read")
        if credit["status"] == "REVOKED":
            raise ApiError("ERR_GOODWILL_CREDIT_INVALID_STATE",
                           "a revoked credit cannot be redeemed")
        if credit["remaining_cents"] <= 0:
            raise ApiError("ERR_GOODWILL_CREDIT_EXHAUSTED",
                           "this credit has nothing left on it")
        if clock() >= parse_iso(credit["expires_at_utc"]):
            raise ApiError("ERR_GOODWILL_CREDIT_EXPIRED",
                           "this credit has expired")
        service = service_of(res)
        if res["guest_id"] != credit["guest_id"] \
                or service["restaurant_id"] != credit["restaurant_id"]:
            raise ApiError("ERR_GOODWILL_TARGET_MISMATCH",
                           "credit does not travel between guests or restaurants")
        if amount > credit["remaining_cents"]:
            raise ApiError("ERR_GOODWILL_REDEMPTION_EXCEEDS_REMAINING",
                           "the redemption exceeds what remains on the credit")
        if amount > res["balance_due_cents"]:
            raise ApiError("ERR_GOODWILL_EXCEEDS_BALANCE_DUE",
                           "credit may settle a bill but never overpay one")
        w = Watch()
        w.add(credit, res)
        txn = write_txn(res, "GOODWILL_REDEMPTION", amount, "CREDIT_APPLIED",
                        goodwill_credit_id=credit["id"])
        sync_credit(credit, w)
        sync_reservation(res, w)
        sync_service(service, w)
        w.commit()
        return ok(public(txn), 201)

    @app.post("/goodwill-credits/<cid>/revoke")
    def revoke_credit(cid):
        ctx = auth("GuestServices")
        credit = must_get("goodwill_credits", cid)
        opt_str(ctx.body, "reason_code", None, allow_empty=False)
        if ctx.user_id == credit["issued_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "the issuing operator may not revoke the credit")
        if credit["status"] not in CREDIT_LIVE:
            raise ApiError("ERR_GOODWILL_CREDIT_INVALID_STATE",
                           "this credit can no longer be revoked")
        w = Watch()
        w.add(credit)
        credit["revoked_cents"] = credit["remaining_cents"]
        sync_credit(credit, w)
        w.commit()
        return ok(public(credit))

    # --------------------------------------------------------- logical clock

    @app.post("/_clock/set_current_utc")
    def set_current_utc():
        ctx = auth("PlatformAdmin")
        moment = req_dt(ctx.body, "current_utc")
        set_clock(moment)
        return ok({})
