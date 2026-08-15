"""State-machine cascade side effects and the run_ops checkpoint (pinned
order per scaffold 1.3 run_ops_checkpoint).
"""
import clock
import db
from services import calc, posture
from services.core import touch


def vendor_of_assignment(assignment):
    if not assignment:
        return None
    app = db.STORES["applications"].get(assignment.get("application_id"))
    if app is None:
        return None
    return db.STORES["vendors"].get(app["vendor_id"])


def release_booth(booth):
    if booth is not None and booth["status"] != "AVAILABLE":
        booth["status"] = "AVAILABLE"
        booth["_reserved_for_assignment_id"] = None
        touch(booth)


def recompute_vendor_score(vendor):
    old = vendor["renewal_score"]
    calc.recompute_renewal_score(vendor)
    return vendor["renewal_score"] != old


def forfeit_assignment(assignment, strike=False, recompute=False):
    """Shared FORFEITED transition (manual forfeit, permit cascade, run_ops,
    market cancel). Returns the booth to AVAILABLE."""
    assignment["status"] = "FORFEITED"
    touch(assignment)
    release_booth(db.STORES["booths"].get(assignment["booth_id"]))
    if strike:
        vendor = vendor_of_assignment(assignment)
        if vendor is not None:
            vendor["no_show_strikes"] += 1
            if recompute:
                calc.recompute_renewal_score(vendor)
            touch(vendor)


def fire_weather_alert(market):
    """OPEN -> WEATHER_ALERT cascade (PRD 3.7)."""
    market["_weather_alert_flag"] = True
    touch(market)
    mid = market["id"]
    for dev in db.STORES["pos_devices"].values():
        if dev["market_id"] == mid and dev["status"] == "ACTIVE":
            dev["status"] = "SUSPENDED"
            touch(dev)
    for slot in db.STORES["programming"].values():
        if slot["market_id"] != mid:
            continue
        if slot["status"] == "LIVE":
            slot["status"] = "CANCELLED"
            touch(slot)
        elif slot["status"] == "SCHEDULED" and slot["slot_kind"] == "PARADE":
            slot["status"] = "CANCELLED"
            touch(slot)


def clear_weather_alert(market):
    """WEATHER_ALERT -> OPEN cascade (PRD 3.7)."""
    market["_weather_alert_flag"] = False
    touch(market)
    mid = market["id"]
    for dev in db.STORES["pos_devices"].values():
        if dev["market_id"] == mid and dev["status"] == "SUSPENDED":
            dev["status"] = "ACTIVE"
            touch(dev)


def cancel_market(market):
    market["_cancelled_flag"] = True
    touch(market)
    mid = market["id"]
    for app in db.STORES["applications"].values():
        if app["market_id"] == mid and app["status"] in (
            "DRAFT",
            "SUBMITTED",
            "UNDER_JURY",
            "WAITLISTED",
        ):
            app["status"] = "WITHDRAWN"
            touch(app)
    for a in db.STORES["assignments"].values():
        if a["market_id"] == mid and a["status"] in ("PENDING_PAYMENT", "ACTIVE"):
            forfeit_assignment(a, strike=False, recompute=False)


def close_season(market):
    """OPEN -> CLOSED_SEASON cascade (PRD 3.8); runs during run_ops."""
    mid = market["id"]
    for a in db.STORES["assignments"].values():
        if a["market_id"] == mid and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            touch(a)
            release_booth(db.STORES["booths"].get(a["booth_id"]))
    for dev in db.STORES["pos_devices"].values():
        if dev["market_id"] == mid and dev["status"] == "ACTIVE":
            dev["status"] = "RETURNED"
            touch(dev)
    for s in db.STORES["settlements"].values():
        if s["market_id"] == mid and s["status"] == "SUBMITTED":
            s["status"] = "RECONCILED"
            touch(s)
            vendor = vendor_of_assignment(
                db.STORES["assignments"].get(s["assignment_id"])
            )
            if vendor is not None:
                if recompute_vendor_score(vendor):
                    touch(vendor)
    market["_season_close_cascaded"] = True
    touch(market)


def run_ops(market):
    """Ops checkpoint; steps execute in pinned order (scaffold 1.3)."""
    market["run_ops_index"] += 1
    touch(market)
    mid = market["id"]
    now = clock.now()

    # 1. PENDING_PAYMENT assignments older than 3 ops runs -> FORFEITED
    for a in list(db.STORES["assignments"].values()):
        if (
            a["market_id"] == mid
            and a["status"] == "PENDING_PAYMENT"
            and market["run_ops_index"] - a["_ops_index_at_creation"] >= 3
        ):
            forfeit_assignment(a, strike=True, recompute=False)

    # 2. expire ACTIVE permits at/past expires_at (TEMP_STRUCTURE cascades)
    for p in list(db.STORES["permits"].values()):
        if p["market_id"] == mid and p["status"] == "ACTIVE" and p["expires_at"] <= now:
            p["status"] = "EXPIRED"
            touch(p)
            if p["permit_type"] == "TEMP_STRUCTURE":
                a = db.STORES["assignments"].get(p["assignment_id"])
                if a is not None and a["status"] in ("PENDING_PAYMENT", "ACTIVE"):
                    forfeit_assignment(a, strike=False, recompute=False)

    # 3. expire EXTENDED renewal offers at/past offer_expires_at
    for r in list(db.STORES["renewal_offers"].values()):
        if (
            r["market_id"] == mid
            and r["status"] == "EXTENDED"
            and r["offer_expires_at"] <= now
        ):
            r["status"] = "EXPIRED"
            touch(r)

    # 4. RESERVED load slots past ends_at -> NO_SHOW (strike + score recompute)
    for slot in list(db.STORES["load_slots"].values()):
        if slot["market_id"] == mid and slot["status"] == "RESERVED" and slot["ends_at"] < now:
            slot["status"] = "NO_SHOW"
            touch(slot)
            vendor = vendor_of_assignment(db.STORES["assignments"].get(slot["assignment_id"]))
            if vendor is not None:
                vendor["no_show_strikes"] += 1
                calc.recompute_renewal_score(vendor)
                touch(vendor)

    # 5. OPEN -> CLOSED_SEASON once closes_at has passed
    if (
        market["_opened_flag"]
        and not market["_cancelled_flag"]
        and not market["_season_close_cascaded"]
        and now >= market["closes_at"]
    ):
        close_season(market)


def sync_programming():
    """Lazy SCHEDULED -> LIVE -> COMPLETED evaluation on programming reads
    (system-automatic when the clock reaches the boundary and posture is OPEN)."""
    now = clock.now()
    for slot in db.STORES["programming"].values():
        market = db.STORES["markets"].get(slot["market_id"])
        if market is None:
            continue
        if posture.derive_posture(market) != "OPEN":
            continue
        if slot["status"] == "SCHEDULED" and now >= slot["starts_at"]:
            slot["status"] = "LIVE"
            touch(slot)
        if slot["status"] == "LIVE" and now >= slot["ends_at"]:
            slot["status"] = "COMPLETED"
            touch(slot)
