"""Daily ops-run checkpoint (PRD §2.4): six steps in pinned processing order."""
from datetime import timedelta

from db import STORE, today, touch, new_record
from services.domain import (
    HOUSE_CLEANING_DAYS,
    HOUSE_RESTING_DAYS,
    w1_window,
    w2_window,
    _env_collected_in_window,
    recompute_posture,
    flock_age_weeks,
)


def run_daily_ops():
    today_d = today()
    lots_expired = 0
    contracts_expired = 0
    flocks_advanced = 0
    houses_advanced = 0
    tests_auto_scheduled = 0

    # (1) Expire lots past sell-by: pack_date ASC, created_at ASC.
    expiring = [
        l for l in STORE["lots"].values()
        if l["lifecycle_status"] in ("FRESH", "RELEASED", "ALLOCATED")
        and today_d > l["sell_by_date"]
    ]
    expiring.sort(key=lambda l: (l["pack_date"], l["created_at"], l["_seq"]))
    for lot in expiring:
        was_allocated = lot["lifecycle_status"] == "ALLOCATED"
        lot["lifecycle_status"] = "EXPIRED"
        touch(lot)
        if was_allocated and lot.get("contract_id"):
            contract = STORE["contracts"].get(lot["contract_id"])
            lot["contract_id"] = None
            if contract is not None:
                touch(contract)
        lots_expired += 1

    # (2) Expire contracts at/past effective_end: effective_end ASC.
    expiring_c = [
        c for c in STORE["contracts"].values()
        if c["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")
        and today_d >= c["effective_end"]
    ]
    expiring_c.sort(key=lambda c: (c["effective_end"], c["created_at"], c["_seq"]))
    from services.domain import void_draft_settlements
    for contract in expiring_c:
        was_live = contract["status"] in ("ACTIVE", "SUSPENDED")
        contract["status"] = "EXPIRED"
        touch(contract)
        if was_live:
            void_draft_settlements(contract)
        contracts_expired += 1

    # (3) Flock age transitions PLACED->GROWING->LAYING: placement_date ASC.
    aging = [
        f for f in STORE["flocks"].values() if f["status"] in ("PLACED", "GROWING")
    ]
    aging.sort(key=lambda f: (f["placement_date"], f["created_at"], f["_seq"]))
    for flock in aging:
        advanced = False
        while True:
            age = flock_age_weeks(flock)
            if flock["status"] == "PLACED" and age >= 1:
                flock["status"] = "GROWING"
                touch(flock)
                advanced = True
            elif flock["status"] == "GROWING" and age >= 18:
                flock["status"] = "LAYING"
                touch(flock)
                advanced = True
            else:
                break
        if advanced:
            flocks_advanced += 1

    # (4) House turnaround CLEANING->RESTING (+7d), RESTING->EMPTY (+14d):
    #     status_changed_date ASC.
    turning = [
        h for h in STORE["houses"].values() if h["status"] in ("CLEANING", "RESTING")
    ]
    turning.sort(key=lambda h: (h["status_changed_date"], h["created_at"], h["_seq"]))
    for house in turning:
        scd = house["status_changed_date"]
        if house["status"] == "CLEANING" and today_d >= scd + timedelta(days=HOUSE_CLEANING_DAYS):
            house["status"] = "RESTING"
            house["status_changed_date"] = today_d
            touch(house)
            houses_advanced += 1
        elif house["status"] == "RESTING" and today_d >= scd + timedelta(days=HOUSE_RESTING_DAYS):
            house["status"] = "EMPTY"
            house["status_changed_date"] = today_d
            touch(house)
            houses_advanced += 1

    # (5) Auto-schedule due ENVIRONMENTAL sampling windows: flock placement_date ASC.
    candidates = [
        f for f in STORE["flocks"].values()
        if f["status"] == "LAYING" and f["quarantine_status"] == "CLEAR"
    ]
    candidates.sort(key=lambda f: (f["placement_date"], f["created_at"], f["_seq"]))
    for flock in candidates:
        age = flock_age_weeks(flock)
        due = False
        scheduled_date = None
        if 40 <= age <= 45:
            w1s, w1e = w1_window(flock)
            if not _env_collected_in_window(flock, w1s, w1e):
                due = True
                scheduled_date = w1e  # placement_date + 321 days
        if not due and flock.get("molt_count", 0) >= 1 and flock.get("molt_started_date"):
            weeks_since_molt = (today_d - flock["molt_started_date"]).days // 7
            if 4 <= weeks_since_molt <= 6:
                w2s, w2e = w2_window(flock)
                if not _env_collected_in_window(flock, w2s, w2e):
                    due = True
                    scheduled_date = w2e  # molt_started_date + 48 days
        if not due:
            continue
        has_scheduled = any(
            t["flock_id"] == flock["id"] and t["status"] == "SCHEDULED"
            for t in STORE["salmonella_tests"].values()
        )
        if has_scheduled:
            continue
        rec = new_record()
        rec.update({
            "flock_id": flock["id"],
            "test_type": "ENVIRONMENTAL",
            "scheduled_date": scheduled_date,
            "status": "SCHEDULED",
            "collected_date": None,
            "collected_by": None,
            "result": None,
            "resulted_by": None,
        })
        STORE["salmonella_tests"][rec["id"]] = rec
        tests_auto_scheduled += 1

    # (6) Recompute every farm's compliance posture.
    for farm in STORE["farms"].values():
        recompute_posture(farm)

    return {
        "lots_expired": lots_expired,
        "contracts_expired": contracts_expired,
        "flocks_advanced": flocks_advanced,
        "houses_advanced": houses_advanced,
        "tests_auto_scheduled": tests_auto_scheduled,
    }
