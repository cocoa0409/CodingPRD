"""SeedLot endpoints + GerminationTest endpoints + pack (packets)."""

from flask import Blueprint, request
from db import db
from middleware import require_roles
from validate import (get_body, req_string, opt_string, req_int, req_number,
                      opt_enum, parse_pagination)
from response import success_object, success_list
from errors import (not_found, invalid_state, already_terminal, invalid_enum,
                    invalid_request, ApiError)
from services.core import (lot_view, compute_viable_seed_count,
                           check_lot_depleted, VIABILITY_PASS_PCT,
                           LOT_MAX_PACKETS, round_half_up)

bp = Blueprint("lots", __name__)

LOT_STATUSES = {"DRAFT", "QUARANTINE", "ACTIVE", "DEPLETED", "REJECTED", "RETIRED"}
LOT_TERMINAL = {"DEPLETED", "REJECTED", "RETIRED"}
TEST_STATUSES = {"RECORDED", "CERTIFIED", "VOIDED"}


def get_lot_or_404(lot_id):
    lot = db.lots.get(lot_id)
    if lot is None:
        raise not_found("Seed lot not found.")
    return lot


def test_view(t):
    out = {k: v for k, v in t.items() if not k.startswith("_")}
    out["result_pct"] = float(round_half_up(t["result_pct"], 2))
    return out


# ---------------- SeedLot CRUD ----------------

@bp.post("/api/seed-lots")
def create_lot():
    require_roles("ProgramAdmin")
    body = get_body()
    variety_id = req_string(body, "variety_id")
    home_site_id = req_string(body, "home_site_id")
    lot_code = req_string(body, "lot_code")
    harvest_year = req_int(body, "harvest_year", min_v=2000, max_v=2100)
    seeds_received = req_int(body, "seeds_received", min_v=1)
    provisional = req_number(body, "provisional_viability_pct", min_v=0, max_v=100)
    provisional = float(round_half_up(provisional, 2))
    # band 5: FK existence
    variety = db.varieties.get(variety_id)
    if variety is None:
        raise not_found("variety_id does not resolve to an existing variety.")
    if home_site_id not in db.sites:
        raise not_found("home_site_id does not resolve to an existing site.")
    # band 6: RETIRED variety blocks new lots
    if variety["status"] == "RETIRED":
        raise invalid_state("Variety is RETIRED; new lots are blocked.")
    # band 8: uniqueness (variety_id, harvest_year, lot_code)
    for lot in db.lots.values():
        if (lot["variety_id"] == variety_id
                and lot["harvest_year"] == harvest_year
                and lot["lot_code"] == lot_code):
            raise ApiError("ERR_DUPLICATE_LOT_CODE", 409,
                           "A lot with this (variety_id, harvest_year, lot_code) exists.")
    lot = {
        "variety_id": variety_id,
        "home_site_id": home_site_id,
        "lot_code": lot_code,
        "harvest_year": harvest_year,
        "seeds_received": seeds_received,
        "provisional_viability_pct": provisional,
        "status": "DRAFT",
        "final_viability_pct": None,
        "seeds_remaining": seeds_received,
        "seeds_in_packets": 0,
        "seeds_discarded": 0,
        "packets_created_total": 0,
    }
    db.stamp_new(lot)
    db.lots[lot["id"]] = lot
    return success_object(lot_view(lot), 201)


@bp.get("/api/seed-lots")
def list_lots():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    variety_id = request.args.get("variety_id")
    home_site_id = request.args.get("home_site_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in LOT_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.lots.values(), key=lambda l: l["_seq"])
    if variety_id:
        items = [l for l in items if l["variety_id"] == variety_id]
    if home_site_id:
        items = [l for l in items if l["home_site_id"] == home_site_id]
    if status_f:
        items = [l for l in items if l["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([lot_view(l) for l in page], limit, offset, total)


@bp.get("/api/seed-lots/<lot_id>")
def get_lot(lot_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    lot = get_lot_or_404(lot_id)
    return success_object(lot_view(lot))


@bp.patch("/api/seed-lots/<lot_id>")
def patch_lot(lot_id):
    require_roles("ProgramAdmin")
    lot = get_lot_or_404(lot_id)
    body = get_body()
    new_status = opt_enum(body, "status", LOT_STATUSES, default=None)
    # band 14: terminal lockdown on any mutation trigger
    if lot["status"] in LOT_TERMINAL:
        raise already_terminal("Seed lot is in a terminal state.")
    if new_status is None or new_status == lot["status"]:
        # no-op metadata patch (only status is patchable per endpoint table)
        db.touch(lot)
        return success_object(lot_view(lot))
    if lot["status"] == "ACTIVE" and new_status == "RETIRED":
        # precondition: no CHECKED_OUT packet of this lot
        for p in db.packets.values():
            if p["lot_id"] == lot["id"] and p["status"] == "CHECKED_OUT":
                raise invalid_state("Lot has CHECKED_OUT packets; cannot retire.")
        # discard AVAILABLE packets; seeds move in_packets -> discarded
        for p in db.packets.values():
            if p["lot_id"] == lot["id"] and p["status"] == "AVAILABLE":
                p["status"] = "DISCARDED"
                db.touch(p)
                lot["seeds_in_packets"] -= p["seeds_count"]
                lot["seeds_discarded"] += p["seeds_count"]
        lot["status"] = "RETIRED"
        db.touch(lot)
        return success_object(lot_view(lot))
    raise invalid_state("Unsupported lot status transition.")


@bp.post("/api/seed-lots/<lot_id>/submit-for-review")
def submit_for_review(lot_id):
    require_roles("ProgramAdmin")
    lot = get_lot_or_404(lot_id)
    if lot["status"] in LOT_TERMINAL:
        raise already_terminal("Seed lot is in a terminal state.")
    if lot["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT lot can be submitted for review.")
    if lot["seeds_remaining"] <= 0:
        raise invalid_state("Lot has no remaining seeds; cannot enter quarantine.")
    lot["status"] = "QUARANTINE"
    db.touch(lot)
    return success_object(lot_view(lot))


@bp.post("/api/seed-lots/<lot_id>/recheck")
def recheck(lot_id):
    require_roles("ProgramAdmin")
    lot = get_lot_or_404(lot_id)
    if lot["status"] in LOT_TERMINAL:
        raise already_terminal("Seed lot is in a terminal state.")
    if lot["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE lot can be sent to recheck.")
    lot["status"] = "QUARANTINE"
    db.touch(lot)
    return success_object(lot_view(lot))


# ---------------- GerminationTest ----------------

@bp.post("/api/seed-lots/<lot_id>/germination-tests")
def record_test(lot_id):
    user_id, role = require_roles("Volunteer")
    # band 3: path id first
    lot = get_lot_or_404(lot_id)
    body = get_body()
    seeds_tested = req_int(body, "seeds_tested", min_v=1)
    sprouted_count = req_int(body, "sprouted_count", min_v=0)
    if sprouted_count > seeds_tested:
        raise invalid_request("sprouted_count must be <= seeds_tested.")
    # band 5: recording volunteer FK (the X-User-ID) must exist
    vol = db.volunteers.get(user_id)
    if vol is None:
        raise not_found("Recording volunteer not found.")
    # band 6: volunteer must be ACTIVE; lot must be QUARANTINE
    if vol["status"] != "ACTIVE":
        raise invalid_state("Only ACTIVE volunteers may record tests.")
    if lot["status"] in LOT_TERMINAL:
        raise already_terminal("Seed lot is in a terminal state.")
    if lot["status"] != "QUARANTINE":
        raise invalid_state("Tests may only be recorded while lot is QUARANTINE.")
    from decimal import Decimal, ROUND_HALF_UP
    result_pct = (Decimal(sprouted_count) / Decimal(seeds_tested) * Decimal(100)
                  ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    test = {
        "lot_id": lot["id"],
        "recorded_by_volunteer_id": user_id,
        "seeds_tested": seeds_tested,
        "sprouted_count": sprouted_count,
        "result_pct": float(result_pct),
        "status": "RECORDED",
    }
    db.stamp_new(test)
    db.tests[test["id"]] = test
    return success_object(test_view(test), 201)


@bp.get("/api/germination-tests")
def list_tests():
    require_roles("ProgramAdmin", "Member", "Volunteer")
    limit, offset = parse_pagination()
    lot_id = request.args.get("lot_id")
    vol_id = request.args.get("recorded_by_volunteer_id")
    status_f = request.args.get("status")
    if status_f is not None and status_f not in TEST_STATUSES:
        raise invalid_enum("status filter not in declared set.")
    items = sorted(db.tests.values(), key=lambda t: t["_seq"])
    if lot_id:
        items = [t for t in items if t["lot_id"] == lot_id]
    if vol_id:
        items = [t for t in items if t["recorded_by_volunteer_id"] == vol_id]
    if status_f:
        items = [t for t in items if t["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([test_view(t) for t in page], limit, offset, total)


@bp.get("/api/germination-tests/<test_id>")
def get_test(test_id):
    require_roles("ProgramAdmin", "Member", "Volunteer")
    t = db.tests.get(test_id)
    if t is None:
        raise not_found("Germination test not found.")
    return success_object(test_view(t))


@bp.post("/api/germination-tests/<test_id>/certify")
def certify_test(test_id):
    require_roles("ProgramAdmin")
    t = db.tests.get(test_id)
    if t is None:
        raise not_found("Germination test not found.")
    body = get_body()
    outcome = opt_enum(body, "outcome", {"PASS", "FAIL"})
    if outcome is None:
        raise invalid_request("Missing required field: outcome")
    # terminal lockdown (band 14) beats state (band 6) per catalog note:
    # "certifying one already CERTIFIED or VOIDED falls under terminal lockdown"
    if t["status"] in ("CERTIFIED", "VOIDED"):
        raise already_terminal("Germination test is in a terminal state.")
    if t["status"] != "RECORDED":
        raise ApiError("ERR_TEST_NOT_RECORDED", 409,
                       "Test is not in RECORDED state.")
    # band 10: outcome agreement with measured band
    from decimal import Decimal
    rp = Decimal(str(t["result_pct"]))
    if outcome == "PASS" and rp < VIABILITY_PASS_PCT:
        raise ApiError("ERR_VIABILITY_OUTCOME_MISMATCH", 422,
                       "PASS requires result_pct >= 70.00.")
    if outcome == "FAIL" and rp >= VIABILITY_PASS_PCT:
        raise ApiError("ERR_VIABILITY_OUTCOME_MISMATCH", 422,
                       "FAIL requires result_pct < 70.00.")
    # certify
    t["status"] = "CERTIFIED"
    db.touch(t)
    lot = db.lots.get(t["lot_id"])
    if lot is not None:
        if lot["status"] == "QUARANTINE":
            if outcome == "PASS":
                lot["final_viability_pct"] = t["result_pct"]
                lot["status"] = "ACTIVE"
                db.touch(lot)
            else:
                # FAIL
                if lot["packets_created_total"] == 0:
                    lot["status"] = "REJECTED"
                    db.touch(lot)
                else:
                    # recall cascade
                    _run_recall_cascade(lot)
                    lot["status"] = "QUARANTINE"
                    db.touch(lot)
    return success_object(test_view(t))


def _run_recall_cascade(lot):
    """Certify-FAIL recall cascade hops 1-2."""
    # hop 1: packets AVAILABLE/CHECKED_OUT/RETURNED -> RECALLED
    recalled_packet_ids = set()
    for p in db.packets.values():
        if p["lot_id"] == lot["id"] and p["status"] in (
                "AVAILABLE", "CHECKED_OUT", "RETURNED"):
            p["status"] = "RECALLED"
            db.touch(p)
            recalled_packet_ids.add(p["id"])
    # hop 2: checkouts with recalled packets, status ACTIVE/OVERDUE -> recall_required
    for c in db.checkouts.values():
        if c["packet_id"] in recalled_packet_ids and c["status"] in ("ACTIVE", "OVERDUE"):
            c["recall_required"] = True
            db.touch(c)
    # hop 3: no immediate member mutation (sweep handles suspension)


@bp.post("/api/germination-tests/<test_id>/void")
def void_test(test_id):
    require_roles("ProgramAdmin")
    t = db.tests.get(test_id)
    if t is None:
        raise not_found("Germination test not found.")
    if t["status"] in ("CERTIFIED", "VOIDED"):
        raise already_terminal("Germination test is in a terminal state.")
    if t["status"] != "RECORDED":
        raise ApiError("ERR_TEST_NOT_RECORDED", 409,
                       "Test is not in RECORDED state.")
    t["status"] = "VOIDED"
    db.touch(t)
    return success_object(test_view(t))


# ---------------- Pack ----------------

@bp.post("/api/seed-lots/<lot_id>/pack")
def pack_lot(lot_id):
    user_id, role = require_roles("Volunteer")
    lot = get_lot_or_404(lot_id)
    body = get_body()
    packet_count = req_int(body, "packet_count")
    seeds_per_packet = req_int(body, "seeds_per_packet", min_v=1)
    # band 5: packing volunteer must exist
    vol = db.volunteers.get(user_id)
    if vol is None:
        raise not_found("Packing volunteer not found.")
    # band 6: lot ACTIVE (ERR_LOT_NOT_ACTIVE); volunteer ACTIVE
    if vol["status"] != "ACTIVE":
        raise invalid_state("Only ACTIVE volunteers may pack.")
    if lot["status"] != "ACTIVE":
        raise ApiError("ERR_LOT_NOT_ACTIVE", 409,
                       "Pack attempted against a lot that is not ACTIVE.")
    site = db.sites.get(lot["home_site_id"])
    # band 11.1: pack allocation
    viable = compute_viable_seed_count(lot)
    by_seeds = viable // seeds_per_packet
    by_labels = site["label_stock_count"] if site else 0
    by_lot_cap = LOT_MAX_PACKETS - lot["packets_created_total"]
    allocatable = min(by_seeds, by_labels, by_lot_cap)
    if packet_count < 1 or packet_count > allocatable:
        raise ApiError("ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE", 422,
                       "packet_count outside 1..allocatable.")
    # create packets
    moved = packet_count * seeds_per_packet
    packet_ids = []
    for i in range(packet_count):
        seq = lot["packets_created_total"] + 1 + i
        packet = {
            "lot_id": lot["id"],
            "packet_code": f"{lot['lot_code']}-{lot['harvest_year']}-{seq:03d}",
            "seeds_count": seeds_per_packet,
            "status": "AVAILABLE",
        }
        db.stamp_new(packet)
        db.packets[packet["id"]] = packet
        packet_ids.append(packet["id"])
    lot["seeds_remaining"] -= moved
    lot["seeds_in_packets"] += moved
    lot["packets_created_total"] += packet_count
    db.touch(lot)
    if site is not None:
        site["label_stock_count"] -= packet_count
        db.touch(site)
    check_lot_depleted(lot)
    return success_object({
        "created_count": packet_count,
        "lot_id": lot["id"],
        "packet_ids": packet_ids,
    }, 201)
