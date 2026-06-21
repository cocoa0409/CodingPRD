"""Serializers: turn stored dicts into response payloads.

Each serializer emits exactly the fields declared in SCAFFOLD §1.1 for that
entity, in a stable order, stripping internal bookkeeping keys (e.g. _seq).
Folio money fields and corporate outstanding balance are recomputed live
(PRD §2.9: computed fields recomputed synchronously, never deferred).
"""
import calc


def hotel_out(h):
    return {
        "id": h["id"],
        "name": h["name"],
        "timezone": h["timezone"],
        "current_business_date": h["current_business_date"],
        "overbooking_allowance_pct": h["overbooking_allowance_pct"],
        "audit_epoch": h["audit_epoch"],
        "posture": h["posture"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def room_type_out(rt):
    return {
        "id": rt["id"],
        "hotel_id": rt["hotel_id"],
        "code": rt["code"],
        "tier_rank": rt["tier_rank"],
        "physical_inventory": rt["physical_inventory"],
        "base_rate_cents": rt["base_rate_cents"],
        "created_at": rt["created_at"],
        "updated_at": rt["updated_at"],
        "version": rt["version"],
    }


def room_out(r):
    return {
        "id": r["id"],
        "hotel_id": r["hotel_id"],
        "room_type_id": r["room_type_id"],
        "room_number": r["room_number"],
        "housekeeping_status": r["housekeeping_status"],
        "assigned_reservation_id": r["assigned_reservation_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def rate_plan_out(rp):
    return {
        "id": rp["id"],
        "hotel_id": rp["hotel_id"],
        "code": rp["code"],
        "kind": rp["kind"],
        "corporate_account_id": rp["corporate_account_id"],
        "adjustment_mode": rp["adjustment_mode"],
        "adjustment_value": rp["adjustment_value"],
        "package_fee_cents": rp["package_fee_cents"],
        "no_show_policy": rp["no_show_policy"],
        "status": rp["status"],
        "created_at": rp["created_at"],
        "updated_at": rp["updated_at"],
        "version": rp["version"],
    }


def corporate_account_out(ca):
    return {
        "id": ca["id"],
        "hotel_id": ca["hotel_id"],
        "name": ca["name"],
        "credit_limit_cents": ca["credit_limit_cents"],
        "outstanding_balance_cents": calc.corporate_outstanding(ca["id"]),
        "status": ca["status"],
        "created_at": ca["created_at"],
        "updated_at": ca["updated_at"],
        "version": ca["version"],
    }


def guest_out(g):
    return {
        "id": g["id"],
        "hotel_id": g["hotel_id"],
        "full_name": g["full_name"],
        "email": g["email"],
        "loyalty_tier": g["loyalty_tier"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def group_block_out(gb):
    return {
        "id": gb["id"],
        "hotel_id": gb["hotel_id"],
        "room_type_id": gb["room_type_id"],
        "rate_plan_id": gb["rate_plan_id"],
        "block_name": gb["block_name"],
        "arrival_date": gb["arrival_date"],
        "departure_date": gb["departure_date"],
        "cutoff_date": gb["cutoff_date"],
        "blocked_rooms": gb["blocked_rooms"],
        "picked_up_rooms": calc.block_pickup(gb["id"]),
        "washed_rooms": gb["washed_rooms"],
        "status": gb["status"],
        "created_at": gb["created_at"],
        "updated_at": gb["updated_at"],
        "version": gb["version"],
    }


def reservation_out(rv):
    return {
        "id": rv["id"],
        "hotel_id": rv["hotel_id"],
        "guest_id": rv["guest_id"],
        "room_type_id": rv["room_type_id"],
        "rate_plan_id": rv["rate_plan_id"],
        "corporate_account_id": rv["corporate_account_id"],
        "group_block_id": rv["group_block_id"],
        "assigned_room_id": rv["assigned_room_id"],
        "effective_room_type_id": rv["effective_room_type_id"],
        "arrival_date": rv["arrival_date"],
        "departure_date": rv["departure_date"],
        "nights": rv["nights"],
        "is_upgraded": rv["is_upgraded"],
        "upgrade_is_comp": rv["upgrade_is_comp"],
        "status": rv["status"],
        "created_at": rv["created_at"],
        "updated_at": rv["updated_at"],
        "version": rv["version"],
    }


def folio_out(f):
    money = calc.folio_money(f["id"])
    return {
        "id": f["id"],
        "hotel_id": f["hotel_id"],
        "reservation_id": f["reservation_id"],
        "room_charges_cents": money["room_charges_cents"],
        "projected_charges_cents": f["projected_charges_cents"],
        "incidentals_cents": money["incidentals_cents"],
        "payments_cents": money["payments_cents"],
        "balance_cents": money["balance_cents"],
        "bill_to": f["bill_to"],
        "status": f["status"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def incidental_out(i):
    return {
        "id": i["id"],
        "hotel_id": i["hotel_id"],
        "folio_id": i["folio_id"],
        "kind": i["kind"],
        "description": i["description"],
        "amount_cents": i["amount_cents"],
        "posted_by_kind": i["posted_by_kind"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def night_audit_run_out(n):
    return {
        "id": n["id"],
        "hotel_id": n["hotel_id"],
        "business_date": n["business_date"],
        "epoch": n["epoch"],
        "no_show_count": n["no_show_count"],
        "room_postings_count": n["room_postings_count"],
        "washed_block_count": n["washed_block_count"],
        "status": n["status"],
        "created_at": n["created_at"],
        "updated_at": n["updated_at"],
        "version": n["version"],
    }


def availability_cell_out(c):
    # AvailabilityCell carries only id and created_at as system fields
    # (PRD §2.4: no updated_at, no version).
    return {
        "id": c["id"],
        "hotel_id": c["hotel_id"],
        "room_type_id": c["room_type_id"],
        "stay_date": c["stay_date"],
        "sold_count": c["sold_count"],
        "sellable_count": c["sellable_count"],
        "created_at": c["created_at"],
    }
