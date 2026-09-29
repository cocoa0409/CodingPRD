"""The wine club: holds, releases and the run scheduler (PRD 3.8)."""
import clock
from store import db, touch, ordered
from services import derive, orders_svc, volume

MISSED_RUN_SUSPEND_THRESHOLD = 2
HOLD_BUFFER_DAYS = 3
_CADENCE_MONTHS = {"MONTHLY": 1, "QUARTERLY": 3}


def release_hold_fields(sub):
    """Copy hold_release_date into last_hold_release_date, then clear the hold."""
    sub["last_hold_release_date"] = sub.get("hold_release_date")
    sub["hold_start_date"] = None
    sub["hold_release_date"] = None
    sub["hold_reason"] = None
    sub["status"] = "ACTIVE"


def advance(date_value, cadence):
    months = _CADENCE_MONTHS.get(cadence, 1)
    return clock.add_months(date_value, months)


def candidates_for(winery_id, run_date):
    """(eligible, skipped_ids) -- the eligibility filter of PRD 3.8."""
    eligible = []
    skipped = []
    for sub in ordered(list(db.club_subscriptions.values())):
        if sub["winery_id"] != winery_id:
            continue
        if sub["status"] not in ("ACTIVE", "WEATHER_HELD"):
            continue
        raw_next = sub.get("next_run_date")
        if not raw_next:
            continue
        next_run = clock.parse_date(raw_next)
        if next_run is None or next_run > run_date:
            continue
        if derive.remaining_allotment(sub) < 1:
            # silently skipped; next_run_date is left exactly where it was
            skipped.append(sub["id"])
            continue
        if sub["status"] == "WEATHER_HELD":
            release_on = clock.parse_date(sub.get("hold_release_date"))
            if release_on is not None and release_on > run_date:
                skipped.append(sub["id"])
                sub["next_run_date"] = clock.date_iso(release_on)
                touch(sub)
                continue
            release_hold_fields(sub)
            touch(sub)
        eligible.append(sub)
    eligible.sort(key=lambda s: (clock.parse_date(s["next_run_date"]),
                                 -s["bottles_per_shipment"],
                                 s.get("created_at") or "",
                                 s.get("_seq") or 0))
    return eligible, skipped


def run(winery, run_date):
    eligible, skipped = candidates_for(winery["id"], run_date)
    generated = []
    for sub in eligible:
        consumer = db.consumers.get(sub["consumer_id"])
        if consumer is None:
            skipped.append(sub["id"])
            continue
        rule = volume.state_rule_for(consumer["state_code"])
        if rule is None:
            skipped.append(sub["id"])
            continue
        line_inputs = [{
            "sku": sub["sku"],
            "bottle_ml": sub["bottle_ml"],
            "bottles": sub["bottles_per_shipment"],
            "unit_price_cents": sub["unit_price_cents"],
        }]
        order = orders_svc.create_order(
            winery, consumer, rule, sub["id"], consumer["address_line"],
            consumer["state_code"], consumer["zip_code"], line_inputs)
        orders_svc.screen(order)
        generated.append(order["id"])
        if order["compliance_status"] == "REJECTED":
            sub["missed_run_count"] = sub["missed_run_count"] + 1
            if sub["missed_run_count"] >= MISSED_RUN_SUSPEND_THRESHOLD:
                sub["status"] = "SUSPENDED_COMPLIANCE"
                sub["next_run_date"] = None
                touch(sub)
                derive.bump_winery(winery)
            else:
                touch(sub)
        else:
            current = clock.parse_date(sub["next_run_date"])
            if current is not None:
                sub["next_run_date"] = clock.date_iso(advance(current, sub["cadence"]))
            touch(sub)
    return {
        "winery_id": winery["id"],
        "run_date": clock.date_iso(run_date),
        "generated_count": len(generated),
        "skipped_count": len(skipped),
        "generated_order_ids": generated,
        "skipped_subscription_ids": skipped,
    }
