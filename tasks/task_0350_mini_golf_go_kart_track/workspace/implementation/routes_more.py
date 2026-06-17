"""Remaining routes: heats, tee-sessions, guests/waivers, wallets,
combo-passes, party-groups, bookings. Registered onto the app from app.py.
"""
from datetime import timedelta

from flask import request

from db import db
from errors import err
import errors as E
import response as R
from middleware import (
    authenticate, require_role, forbid,
    ROLE_OPS, ROLE_CASHIER, ROLE_GUEST,
)
import reqvalidate as V
from util import new_uuid, now_iso, parse_iso, parse_date, iso_format
import serializers as S
import services as SV
import calculations as C

ALL_ROLES = [ROLE_OPS, ROLE_CASHIER, ROLE_GUEST]


def register(app, helpers):
    base_entity_fields = helpers["base_entity_fields"]
    guest_owns = helpers["guest_owns"]
    list_response = helpers["list_response"]

    # =======================================================================
    # HEAT
    # =======================================================================

    @app.route("/heats", methods=["POST"])
    def create_heat():
        p = authenticate()
        require_role(p, [ROLE_OPS])
        body = V.get_json_body()
        venue_id = V.require_str(body, "venue_id")
        venue = SV.get_venue(venue_id)
        attraction_id = V.require_str(body, "attraction_id")
        attraction = SV.get_attraction(attraction_id)
        start_raw = V.require_str(body, "start_utc")
        end_raw = V.require_str(body, "end_utc")
        window = V.optional_enum(body, "window", {"OFF_PEAK", "PEAK"}, "OFF_PEAK")
        start = _parse_instant(start_raw, "start_utc")
        end = _parse_instant(end_raw, "end_utc")
        if end <= start:
            raise err(E.ERR_INVALID_REQUEST, "end_utc must be after start_utc")
        # attraction kind agreement (ERR_ATTRACTION_KIND_MISMATCH, 409)
        if attraction["kind"] != "GO_KART":
            raise err(E.ERR_ATTRACTION_KIND_MISMATCH, "Heat requires a GO_KART attraction")
        # overlap: half-open [start,end), non-terminal heats on same attraction
        _check_heat_overlap(attraction_id, start, end)
        h = base_entity_fields()
        h.update({
            "venue_id": venue_id,
            "attraction_id": attraction_id,
            "start_utc": iso_format(start),
            "end_utc": iso_format(end),
            "window": window,
            "lane_capacity": attraction["lane_count"],
            "status": "SCHEDULED",
        })
        db.heats[h["id"]] = h
        return R.success(S.heat_out(h), 201)

    @app.route("/heats", methods=["GET"])
    def list_heats():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.heats, None, S.heat_out, {
            "venue_id": request.args.get("venue_id"),
            "attraction_id": request.args.get("attraction_id"),
            "status": request.args.get("status"),
        })

    @app.route("/heats/<heat_id>", methods=["GET"])
    def get_heat_ep(heat_id):
        p = authenticate()
        require_role(p, ALL_ROLES)
        h = SV.get_heat(heat_id)
        return R.success(S.heat_out(h))

    @app.route("/heats/<heat_id>/open", methods=["POST"])
    def open_heat(heat_id):
        p = authenticate()
        require_role(p, [ROLE_OPS])
        h = SV.get_heat(heat_id)
        SV.open_slot(h, "HEAT")
        return R.success(S.heat_out(h))

    @app.route("/heats/<heat_id>/close", methods=["POST"])
    def close_heat(heat_id):
        p = authenticate()
        require_role(p, [ROLE_OPS])
        h = SV.get_heat(heat_id)
        SV.close_slot(h, "HEAT")
        return R.success(S.heat_out(h))

    @app.route("/heats/<heat_id>/cancel", methods=["POST"])
    def cancel_heat(heat_id):
        p = authenticate()
        require_role(p, [ROLE_OPS])
        h = SV.get_heat(heat_id)
        SV.cancel_slot(h, "HEAT")
        return R.success(S.heat_out(h))

    # =======================================================================
    # TEE SESSION
    # =======================================================================

    @app.route("/tee-sessions", methods=["POST"])
    def create_tee_session():
        p = authenticate()
        require_role(p, [ROLE_OPS])
        body = V.get_json_body()
        venue_id = V.require_str(body, "venue_id")
        venue = SV.get_venue(venue_id)
        attraction_id = V.require_str(body, "attraction_id")
        attraction = SV.get_attraction(attraction_id)
        start_raw = V.require_str(body, "start_utc")
        end_raw = V.require_str(body, "end_utc")
        capacity = V.require_int(body, "party_slot_capacity", minimum=0)
        window = V.optional_enum(body, "window", {"OFF_PEAK", "PEAK"}, "OFF_PEAK")
        start = _parse_instant(start_raw, "start_utc")
        end = _parse_instant(end_raw, "end_utc")
        if end < start:
            raise err(E.ERR_INVALID_REQUEST, "end_utc must be at or after start_utc")
        if attraction["kind"] != "MINI_GOLF":
            raise err(E.ERR_ATTRACTION_KIND_MISMATCH, "TeeSession requires a MINI_GOLF attraction")
        _check_tee_overlap(attraction_id, start, end)
        s = base_entity_fields()
        s.update({
            "venue_id": venue_id,
            "attraction_id": attraction_id,
            "start_utc": iso_format(start),
            "end_utc": iso_format(end),
            "window": window,
            "party_slot_capacity": capacity,
            "status": "SCHEDULED",
        })
        db.tee_sessions[s["id"]] = s
        return R.success(S.tee_session_out(s), 201)

    @app.route("/tee-sessions", methods=["GET"])
    def list_tee_sessions():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.tee_sessions, None, S.tee_session_out, {
            "venue_id": request.args.get("venue_id"),
            "attraction_id": request.args.get("attraction_id"),
            "status": request.args.get("status"),
        })

    @app.route("/tee-sessions/<tid>", methods=["GET"])
    def get_tee_session_ep(tid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        s = SV.get_tee_session(tid)
        return R.success(S.tee_session_out(s))

    @app.route("/tee-sessions/<tid>/open", methods=["POST"])
    def open_tee(tid):
        p = authenticate()
        require_role(p, [ROLE_OPS])
        s = SV.get_tee_session(tid)
        SV.open_slot(s, "TEE_SESSION")
        return R.success(S.tee_session_out(s))

    @app.route("/tee-sessions/<tid>/close", methods=["POST"])
    def close_tee(tid):
        p = authenticate()
        require_role(p, [ROLE_OPS])
        s = SV.get_tee_session(tid)
        SV.close_slot(s, "TEE_SESSION")
        return R.success(S.tee_session_out(s))

    @app.route("/tee-sessions/<tid>/cancel", methods=["POST"])
    def cancel_tee(tid):
        p = authenticate()
        require_role(p, [ROLE_OPS])
        s = SV.get_tee_session(tid)
        SV.cancel_slot(s, "TEE_SESSION")
        return R.success(S.tee_session_out(s))

    # =======================================================================
    # GUEST / WAIVER
    # =======================================================================

    @app.route("/guests", methods=["POST"])
    def create_guest():
        p = authenticate()
        require_role(p, ALL_ROLES)
        body = V.get_json_body()
        full_name = V.require_str(body, "full_name")
        height = V.require_int(body, "height_cm", minimum=0)
        birthdate = V.optional_str(body, "birthdate", None)
        if birthdate is not None:
            try:
                parse_date(birthdate)
            except Exception:
                raise err(E.ERR_INVALID_REQUEST, "birthdate must be an ISO date (YYYY-MM-DD)")
        g = base_entity_fields()
        g.update({
            "full_name": full_name,
            "height_cm": height,
            "birthdate": birthdate,
        })
        db.guests[g["id"]] = g
        # auto-create empty wallet
        w = base_entity_fields()
        w.update({
            "guest_id": g["id"],
            "arcade_card_balance_cents": 0,
            "total_loaded_cents": 0,
        })
        db.wallets[w["id"]] = w
        return R.success(S.guest_out(g), 201)

    @app.route("/guests", methods=["GET"])
    def list_guests():
        p = authenticate()
        require_role(p, ALL_ROLES)
        ws = request.args.get("waiver_status")
        items = list(db.guests.values())
        items.sort(key=lambda x: (x["created_at"], x["_seq"]))
        if ws is not None:
            items = [g for g in items if S.waiver_status(g["id"]) == ws]
        from pagination import get_pagination, paginate
        limit, offset = get_pagination()
        total = len(items)
        page = paginate(items, limit, offset)
        return R.success_list([S.guest_out(g) for g in page], limit, offset, total)

    @app.route("/guests/<guest_id>", methods=["GET"])
    def get_guest_ep(guest_id):
        p = authenticate()
        require_role(p, ALL_ROLES)
        g = SV.get_guest(guest_id)
        guest_owns(p, guest_id)
        return R.success(S.guest_out(g))

    @app.route("/waivers", methods=["POST"])
    def create_waiver():
        p = authenticate()
        require_role(p, ALL_ROLES)
        body = V.get_json_body()
        guest_id = V.require_str(body, "guest_id")
        guest = SV.get_guest(guest_id)
        guest_owns(p, guest_id)
        guardian_name = V.optional_str(body, "guardian_name", None)
        # determine venue clock for signed_at: a waiver is signed against "the
        # venue's current clock value at the moment of signing". Guests aren't
        # bound to a venue; use the representative latest venue clock, falling
        # back to wall time when no venue exists.
        clock = S.current_clock_for_waiver()
        if clock is None:
            signed_at_dt = parse_iso(now_iso())
        else:
            signed_at_dt = clock
        # minor check: age at signed_at < 18 requires guardian_name
        if guest.get("birthdate"):
            bd = parse_date(guest["birthdate"])
            age = _age_at(bd, signed_at_dt)
            if age < 18 and not guardian_name:
                raise err(E.ERR_WAIVER_REQUIRED, "Minor's waiver requires guardian_name")
        expires_dt = signed_at_dt + timedelta(days=365)
        w = {
            "id": new_uuid(),
            "guest_id": guest_id,
            "signed_at": iso_format(signed_at_dt),
            "expires_at": iso_format(expires_dt),
            "guardian_name": guardian_name,
            "created_at": now_iso(),
            "_seq": db.next_seq(),
        }
        db.waivers[w["id"]] = w
        # guest waiver_status is derived on read; touch guest to reflect mutation
        SV.touch(guest)
        return R.success(S.waiver_out(w), 201)

    @app.route("/waivers", methods=["GET"])
    def list_waivers():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.waivers, None, S.waiver_out, {
            "guest_id": request.args.get("guest_id"),
        })

    @app.route("/waivers/<waiver_id>", methods=["GET"])
    def get_waiver_ep(waiver_id):
        p = authenticate()
        require_role(p, ALL_ROLES)
        w = SV.get_waiver(waiver_id)
        guest_owns(p, w["guest_id"])
        return R.success(S.waiver_out(w))

    # =======================================================================
    # WALLET
    # =======================================================================

    @app.route("/wallets", methods=["GET"])
    def list_wallets():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.wallets, None, S.wallet_out, {
            "guest_id": request.args.get("guest_id"),
        })

    @app.route("/wallets/<wallet_id>", methods=["GET"])
    def get_wallet_ep(wallet_id):
        p = authenticate()
        require_role(p, ALL_ROLES)
        w = SV.get_wallet(wallet_id)
        guest_owns(p, w["guest_id"])
        return R.success(S.wallet_out(w))

    @app.route("/wallets/<wallet_id>/top-ups", methods=["POST"])
    def wallet_topup(wallet_id):
        p = authenticate()
        require_role(p, ALL_ROLES)
        w = SV.get_wallet(wallet_id)
        guest_owns(p, w["guest_id"])
        body = V.get_json_body()
        amount = V.require_int(body, "amount_cents", minimum=0)
        bonus = C.loyalty_bonus(w["total_loaded_cents"], amount)
        w["total_loaded_cents"] += amount
        w["arcade_card_balance_cents"] += amount + bonus
        SV.touch(w)
        return R.success(S.wallet_out(w))

    @app.route("/wallets/<wallet_id>/redemptions", methods=["POST"])
    def wallet_redeem(wallet_id):
        p = authenticate()
        require_role(p, [ROLE_CASHIER, ROLE_GUEST])
        w = SV.get_wallet(wallet_id)
        guest_owns(p, w["guest_id"])
        body = V.get_json_body()
        amount = V.require_int(body, "amount_cents", minimum=0)
        if amount > w["arcade_card_balance_cents"]:
            raise err(E.ERR_INSUFFICIENT_CARD_BALANCE, "Redemption exceeds card balance")
        w["arcade_card_balance_cents"] -= amount
        SV.touch(w)
        return R.success(S.wallet_out(w))

    # =======================================================================
    # COMBO PASS
    # =======================================================================

    @app.route("/combo-passes", methods=["POST"])
    def create_combo_pass():
        p = authenticate()
        require_role(p, ALL_ROLES)
        body = V.get_json_body()
        guest_id = V.require_str(body, "guest_id")
        guest = SV.get_guest(guest_id)
        guest_owns(p, guest_id)
        total = V.require_int(body, "total_credits", minimum=1)
        c = base_entity_fields()
        c.update({
            "guest_id": guest_id,
            "total_credits": total,
            "credits_redeemed": 0,
            "status": "ACTIVE",
        })
        db.combo_passes[c["id"]] = c
        return R.success(S.combo_pass_out(c), 201)

    @app.route("/combo-passes", methods=["GET"])
    def list_combo_passes():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.combo_passes, None, S.combo_pass_out, {
            "guest_id": request.args.get("guest_id"),
            "status": request.args.get("status"),
        })

    @app.route("/combo-passes/<cid>", methods=["GET"])
    def get_combo_pass_ep(cid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        c = SV.get_combo_pass(cid)
        guest_owns(p, c["guest_id"])
        return R.success(S.combo_pass_out(c))

    # =======================================================================
    # PARTY GROUP
    # =======================================================================

    @app.route("/party-groups", methods=["POST"])
    def create_party_group():
        p = authenticate()
        require_role(p, ALL_ROLES)
        body = V.get_json_body()
        venue_id = V.require_str(body, "venue_id")
        venue = SV.get_venue(venue_id)
        host_guest_id = V.require_str(body, "host_guest_id")
        host = SV.get_guest(host_guest_id)
        guest_owns(p, host_guest_id)
        package_name = V.require_str(body, "package_name")
        included = V.require_int(body, "included_unit_count", minimum=0)
        deposit = V.require_int(body, "deposit_cents", minimum=0)
        wallet = SV.wallet_for_guest(host_guest_id)
        if wallet is None or deposit > wallet["arcade_card_balance_cents"]:
            raise err(E.ERR_INSUFFICIENT_CARD_BALANCE, "Deposit exceeds host wallet balance")
        # debit deposit
        wallet["arcade_card_balance_cents"] -= deposit
        SV.touch(wallet)
        pg = base_entity_fields()
        pg.update({
            "venue_id": venue_id,
            "host_guest_id": host_guest_id,
            "package_name": package_name,
            "included_unit_count": included,
            "deposit_cents": deposit,
            "units_consumed": 0,
            "status": "DRAFT",
        })
        db.party_groups[pg["id"]] = pg
        return R.success(S.party_group_out(pg), 201)

    @app.route("/party-groups", methods=["GET"])
    def list_party_groups():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.party_groups, None, S.party_group_out, {
            "venue_id": request.args.get("venue_id"),
            "host_guest_id": request.args.get("host_guest_id"),
            "status": request.args.get("status"),
        })

    @app.route("/party-groups/<gid>", methods=["GET"])
    def get_party_group_ep(gid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        pg = SV.get_party_group(gid)
        guest_owns(p, pg["host_guest_id"])
        return R.success(S.party_group_out(pg))

    @app.route("/party-groups/<gid>/confirm", methods=["POST"])
    def confirm_party_group(gid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        pg = SV.get_party_group(gid)
        guest_owns(p, pg["host_guest_id"])
        body = V.get_json_body()
        venue = SV.get_venue(pg["venue_id"])
        # priority 4: OCC field present & well-formed (malformed body)
        expected_version = _read_group_occ_field(body)
        # priority 5: posture gate
        if venue["posture"] != "OPEN":
            raise err(E.ERR_VENUE_NOT_OPEN, "Venue is not OPEN")
        # priority 6: OCC version mismatch -> 412
        if expected_version != pg["version"]:
            raise err(E.ERR_STALE_GROUP_VERSION, "Group version is stale")
        # priority 7: state
        if pg["status"] != "DRAFT":
            raise err(E.ERR_INVALID_STATE, "Party group is not DRAFT")
        # priority 7.4: at least one member booking in HOLD or CONFIRMED
        members = [b for b in db.bookings.values() if b.get("group_id") == gid]
        if not any(b["status"] in ("HOLD", "CONFIRMED") for b in members):
            raise err(E.ERR_PARTY_GROUP_EMPTY, "Party group has no HOLD/CONFIRMED member booking")
        pg["status"] = "CONFIRMED"
        SV.touch(pg)
        return R.success(S.party_group_out(pg))

    @app.route("/party-groups/<gid>/check-in", methods=["POST"])
    def checkin_party_group(gid):
        p = authenticate()
        require_role(p, [ROLE_OPS, ROLE_CASHIER])
        pg = SV.get_party_group(gid)
        if pg["status"] != "CONFIRMED":
            raise err(E.ERR_INVALID_STATE, "Party group is not CONFIRMED")
        members = [b for b in db.bookings.values() if b.get("group_id") == gid]
        if not any(b["status"] == "CHECKED_IN" for b in members):
            raise err(E.ERR_INVALID_STATE, "No member booking is CHECKED_IN")
        pg["status"] = "CHECKED_IN"
        SV.touch(pg)
        return R.success(S.party_group_out(pg))

    @app.route("/party-groups/<gid>/cancel", methods=["POST"])
    def cancel_party_group(gid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        pg = SV.get_party_group(gid)
        guest_owns(p, pg["host_guest_id"])
        if pg["status"] not in ("DRAFT", "CONFIRMED"):
            raise err(E.ERR_INVALID_STATE, "Party group cannot be cancelled from its state")
        was_draft = pg["status"] == "DRAFT"
        pg["status"] = "CANCELLED"
        # cascade: non-terminal member bookings -> CANCELLED (with side effects)
        members = [b for b in db.bookings.values() if b.get("group_id") == gid]
        for b in members:
            if b["status"] in ("HOLD", "CONFIRMED", "WAITLISTED"):
                SV.cancel_booking_internal(b)
        # deposit refunded only if cancelled while DRAFT
        if was_draft:
            wallet = SV.wallet_for_guest(pg["host_guest_id"])
            if wallet is not None:
                wallet["arcade_card_balance_cents"] += pg["deposit_cents"]
                SV.touch(wallet)
        SV.touch(pg)
        return R.success(S.party_group_out(pg))

    # =======================================================================
    # BOOKING
    # =======================================================================

    @app.route("/bookings", methods=["POST"])
    def create_booking():
        p = authenticate()
        require_role(p, ALL_ROLES)
        body = V.get_json_body()
        # existence resolution left-to-right: venue, guest, slot, plan, group, pass
        venue_id = V.require_str(body, "venue_id")
        venue = SV.get_venue(venue_id)
        guest_id = V.require_str(body, "guest_id")
        guest = SV.get_guest(guest_id)
        guest_owns(p, guest_id)
        slot_kind = V.require_enum(body, "slot_kind", {"HEAT", "TEE_SESSION"})
        heat_id = V.optional_str(body, "heat_id", None)
        tee_session_id = V.optional_str(body, "tee_session_id", None)
        pricing_plan_id = V.require_str(body, "pricing_plan_id")
        group_id = V.optional_str(body, "group_id", None)
        combo_pass_id = V.optional_str(body, "combo_pass_id", None)
        origin = V.require_enum(body, "origin", {"RESERVATION", "WALK_IN"})
        party_size = V.require_int(body, "party_size", minimum=1)
        units = V.optional_int(body, "units", 1, minimum=1)

        # slot_kind must agree with which slot ref provided (ERR_INVALID_REQUEST)
        if slot_kind == "HEAT":
            if not heat_id or tee_session_id:
                raise err(E.ERR_INVALID_REQUEST, "slot_kind HEAT requires heat_id and no tee_session_id")
        else:
            if not tee_session_id or heat_id:
                raise err(E.ERR_INVALID_REQUEST, "slot_kind TEE_SESSION requires tee_session_id and no heat_id")

        # existence of slot and plan (left-to-right)
        if slot_kind == "HEAT":
            slot = SV.get_heat(heat_id)
        else:
            slot = SV.get_tee_session(tee_session_id)
        plan = SV.get_pricing_plan(pricing_plan_id)
        if group_id is not None:
            SV.get_party_group(group_id)
        combo = None
        if combo_pass_id is not None:
            combo = SV.get_combo_pass(combo_pass_id)

        # attraction-kind agreement: slot_kind must match owning attraction kind
        attraction = db.attractions.get(slot["attraction_id"])
        if slot_kind == "HEAT" and (attraction is None or attraction["kind"] != "GO_KART"):
            raise err(E.ERR_ATTRACTION_KIND_MISMATCH, "Heat booking requires GO_KART attraction")
        if slot_kind == "TEE_SESSION" and (attraction is None or attraction["kind"] != "MINI_GOLF"):
            raise err(E.ERR_ATTRACTION_KIND_MISMATCH, "TeeSession booking requires MINI_GOLF attraction")

        # wristband cap (ERR_WRISTBAND_CAP_EXCEEDED)
        if plan["mode"] == "WRISTBAND" and plan["wristband_unit_cap"] > 0 and units > plan["wristband_unit_cap"]:
            raise err(E.ERR_WRISTBAND_CAP_EXCEEDED, "units exceed wristband_unit_cap")

        # provisional pricing at create (HOLD)
        gross = C.booking_price(plan, slot["window"], units, party_size)

        b = base_entity_fields()
        b.update({
            "venue_id": venue_id,
            "guest_id": guest_id,
            "slot_kind": slot_kind,
            "heat_id": heat_id if slot_kind == "HEAT" else None,
            "tee_session_id": tee_session_id if slot_kind == "TEE_SESSION" else None,
            "pricing_plan_id": pricing_plan_id,
            "group_id": group_id,
            "combo_pass_id": combo_pass_id,
            "origin": origin,
            "party_size": party_size,
            "units": units,
            "gross_price_cents": gross,
            "credits_applied": 0,
            "cash_due_cents": gross,
            "status": "HOLD",
            "waitlist_seq": None,
        })
        db.bookings[b["id"]] = b
        return R.success(S.booking_out(b), 201)

    @app.route("/bookings", methods=["GET"])
    def list_bookings():
        p = authenticate()
        require_role(p, ALL_ROLES)
        return list_response(db.bookings, None, S.booking_out, {
            "venue_id": request.args.get("venue_id"),
            "guest_id": request.args.get("guest_id"),
            "heat_id": request.args.get("heat_id"),
            "tee_session_id": request.args.get("tee_session_id"),
            "group_id": request.args.get("group_id"),
            "combo_pass_id": request.args.get("combo_pass_id"),
            "pricing_plan_id": request.args.get("pricing_plan_id"),
            "status": request.args.get("status"),
        })

    @app.route("/bookings/<bid>", methods=["GET"])
    def get_booking_ep(bid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        b = SV.get_booking(bid)
        guest_owns(p, b["guest_id"])
        return R.success(S.booking_out(b))

    @app.route("/bookings/<bid>/confirm", methods=["POST"])
    def confirm_booking(bid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        b = SV.get_booking(bid)
        guest_owns(p, b["guest_id"])
        body = V.get_json_body()
        venue = SV.get_venue(b["venue_id"])
        slot, slot_kind = SV.slot_of_booking(b)
        if slot is None:
            raise err(E.ERR_NOT_FOUND, "Owning slot not found")

        # priority 4: OCC field must be present & well-formed (malformed body)
        expected_version = _read_slot_occ_field(body, slot_kind)

        # priority 5: posture gate
        if venue["posture"] != "OPEN":
            raise err(E.ERR_VENUE_NOT_OPEN, "Venue is not OPEN")

        # priority 6: OCC version mismatch -> 412
        if expected_version != slot["version"]:
            raise err(E.ERR_STALE_SLOT_VERSION, "Slot version is stale")

        # priority 7: state — booking must be HOLD; owning slot OPEN
        if b["status"] != "HOLD":
            raise err(E.ERR_INVALID_STATE, "Booking is not in HOLD")
        if slot["status"] != "OPEN":
            raise err(E.ERR_INVALID_STATE, "Owning slot is not OPEN")

        attraction = db.attractions.get(slot["attraction_id"])
        guest = db.guests.get(b["guest_id"])

        # priority 8: height gate
        if attraction is not None and guest["height_cm"] < attraction["min_height_cm"]:
            raise err(E.ERR_HEIGHT_REQUIREMENT, "Guest height below attraction minimum")

        # priority 9: waiver gate (against venue current_utc)
        clock = parse_iso(venue["current_utc"])
        if S.waiver_status_against(b["guest_id"], clock) != "SIGNED":
            raise err(E.ERR_WAIVER_REQUIRED, "Guest lacks a SIGNED unexpired waiver")

        # priority 12: combo pass validity
        combo = None
        if b["combo_pass_id"]:
            combo = db.combo_passes.get(b["combo_pass_id"])
            if combo is None or combo["guest_id"] != b["guest_id"] or \
                    combo["status"] != "ACTIVE" or \
                    max(0, combo["total_credits"] - combo["credits_redeemed"]) <= 0:
                raise err(E.ERR_COMBO_PASS_INVALID, "Combo pass invalid")

        # capacity examination
        plan = db.pricing_plans.get(b["pricing_plan_id"])
        avail = SV.slot_available(slot, slot_kind)
        gross = C.booking_price(plan, slot["window"], b["units"], b["party_size"])

        if avail >= b["party_size"]:
            # CONFIRMED path
            credits_applied, cash_due = C.combo_credit_application(
                plan, combo, gross, b["units"], b["party_size"]
            )
            b["gross_price_cents"] = gross
            b["credits_applied"] = credits_applied
            b["cash_due_cents"] = cash_due
            b["status"] = "CONFIRMED"
            b["waitlist_seq"] = None
            SV.touch(b)
            SV.touch(slot)  # committed recomputed on read; version +1
            if b["group_id"]:
                pg = db.party_groups.get(b["group_id"])
                if pg is not None:
                    SV.touch(pg)
        else:
            # WAITLISTED path
            existing = [x for x in db.bookings.values()
                        if x["status"] == "WAITLISTED" and (
                            (slot_kind == "HEAT" and x.get("heat_id") == slot["id"]) or
                            (slot_kind == "TEE_SESSION" and x.get("tee_session_id") == slot["id"]))]
            max_seq = max([x["waitlist_seq"] or 0 for x in existing], default=0)
            b["waitlist_seq"] = max_seq + 1
            b["status"] = "WAITLISTED"
            # provisional values retained; no capacity, slot version untouched
            SV.touch(b)
        return R.success(S.booking_out(b))

    @app.route("/bookings/<bid>/check-in", methods=["POST"])
    def checkin_booking(bid):
        p = authenticate()
        require_role(p, [ROLE_OPS, ROLE_CASHIER])
        b = SV.get_booking(bid)
        venue = SV.get_venue(b["venue_id"])
        slot, slot_kind = SV.slot_of_booking(b)
        if slot is None:
            raise err(E.ERR_NOT_FOUND, "Owning slot not found")
        # state: booking CONFIRMED, slot OPEN
        if b["status"] != "CONFIRMED":
            raise err(E.ERR_INVALID_STATE, "Booking is not CONFIRMED")
        if slot["status"] != "OPEN":
            raise err(E.ERR_INVALID_STATE, "Owning slot is not OPEN")
        # check-in window
        clock = parse_iso(venue["current_utc"])
        start = parse_iso(slot["start_utc"])
        end = parse_iso(slot["end_utc"])
        if slot_kind == "HEAT":
            in_window = (start <= clock < end)
        else:
            in_window = (start <= clock <= end)
        if not in_window:
            raise err(E.ERR_CHECK_IN_WINDOW, "Outside check-in window")
        b["status"] = "CHECKED_IN"
        # advance combo redemption
        if b["combo_pass_id"] and b["credits_applied"]:
            combo = db.combo_passes.get(b["combo_pass_id"])
            if combo is not None:
                combo["credits_redeemed"] += b["credits_applied"]
                if max(0, combo["total_credits"] - combo["credits_redeemed"]) == 0:
                    combo["status"] = "EXHAUSTED"
                SV.touch(combo)
        SV.touch(b)
        return R.success(S.booking_out(b))

    @app.route("/bookings/<bid>/cancel", methods=["POST"])
    def cancel_booking(bid):
        p = authenticate()
        require_role(p, ALL_ROLES)
        b = SV.get_booking(bid)
        guest_owns(p, b["guest_id"])
        if b["status"] not in ("HOLD", "CONFIRMED", "WAITLISTED"):
            raise err(E.ERR_INVALID_STATE, "Booking cannot be cancelled from its state")
        SV.cancel_booking_internal(b)
        return R.success(S.booking_out(b))

    @app.route("/bookings/<bid>/no-show", methods=["POST"])
    def no_show_booking(bid):
        p = authenticate()
        require_role(p, [ROLE_OPS, ROLE_CASHIER])
        b = SV.get_booking(bid)
        venue = SV.get_venue(b["venue_id"])
        slot, slot_kind = SV.slot_of_booking(b)
        if slot is None:
            raise err(E.ERR_NOT_FOUND, "Owning slot not found")
        if b["status"] != "CONFIRMED":
            raise err(E.ERR_INVALID_STATE, "Booking is not CONFIRMED")
        # no-show window: current_utc >= slot.end_utc
        clock = parse_iso(venue["current_utc"])
        end = parse_iso(slot["end_utc"])
        if clock < end:
            raise err(E.ERR_NO_SHOW_WINDOW, "Slot window has not passed")
        b["status"] = "NO_SHOW"
        SV.touch(b)
        SV.release_confirmed_capacity(b)
        SV.maybe_complete_group(b.get("group_id"))
        return R.success(S.booking_out(b))


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _parse_instant(raw, name):
    try:
        dt = parse_iso(raw)
    except Exception:
        raise err(E.ERR_INVALID_REQUEST, f"{name} must be a valid ISO 8601 instant")
    if dt is None:
        raise err(E.ERR_INVALID_REQUEST, f"{name} is required")
    return dt


def _age_at(birthdate, at_dt):
    at = at_dt.date()
    years = at.year - birthdate.year - ((at.month, at.day) < (birthdate.month, birthdate.day))
    return years


def _check_heat_overlap(attraction_id, start, end):
    for h in db.heats.values():
        if h["attraction_id"] != attraction_id:
            continue
        if h["status"] == "CANCELLED":
            continue
        s_start = parse_iso(h["start_utc"])
        s_end = parse_iso(h["end_utc"])
        # half-open [start,end): overlap iff candidate.start < s.end and s.start < candidate.end
        if start < s_end and s_start < end:
            raise err(E.ERR_SLOT_OVERLAP, "Heat overlaps an existing heat")


def _check_tee_overlap(attraction_id, start, end):
    from datetime import timedelta
    buffer = timedelta(minutes=10)
    for s in db.tee_sessions.values():
        if s["attraction_id"] != attraction_id:
            continue
        if s["status"] == "CANCELLED":
            continue
        s_start = parse_iso(s["start_utc"])
        s_end = parse_iso(s["end_utc"])
        if start >= s_end:
            gap = start - s_end
        elif s_start >= end:
            gap = s_start - end
        else:
            gap = timedelta(minutes=-1)  # interpenetrate
        if gap < buffer:
            raise err(E.ERR_SLOT_OVERLAP, "Tee session violates turnover buffer")


def _read_slot_occ_field(body, slot_kind):
    """Read & validate the required OCC field (priority-4 body wellformedness).

    Returns the integer expected version. Raises ERR_INVALID_REQUEST (422) when
    absent or non-integer; the mismatch (412) is checked by the caller after the
    posture gate.
    """
    field = "expected_heat_version" if slot_kind == "HEAT" else "expected_tee_session_version"
    if field not in body or body.get(field) is None:
        raise err(E.ERR_INVALID_REQUEST, f"{field} is required")
    ev = body.get(field)
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err(E.ERR_INVALID_REQUEST, f"{field} must be an integer")
    return ev


def _read_group_occ_field(body):
    if "expected_group_version" not in body or body.get("expected_group_version") is None:
        raise err(E.ERR_INVALID_REQUEST, "expected_group_version is required")
    ev = body.get("expected_group_version")
    if isinstance(ev, bool) or not isinstance(ev, int):
        raise err(E.ERR_INVALID_REQUEST, "expected_group_version must be an integer")
    return ev
