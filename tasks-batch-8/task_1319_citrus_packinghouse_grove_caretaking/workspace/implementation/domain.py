"""Domain constants, serializers, derived fields, and calculations."""
from datetime import timedelta
from decimal import Decimal

from core import (
    DB, D, rhu, cents, f2, iso_ms, now, touch, sort_asc, err,
)

# ---------------------------------------------------------------------------
# Constants (SCAFFOLD §1.3)
# ---------------------------------------------------------------------------
VARIETIES = {"HAMLIN", "VALENCIA", "RED_GRAPEFRUIT", "TANGERINE"}
VARIETY_MINIMUMS = {
    "HAMLIN": {"min_ratio": D("9.0"), "min_brix": D("8.5"), "min_juice": D("42.0")},
    "VALENCIA": {"min_ratio": D("9.0"), "min_brix": D("9.0"), "min_juice": D("45.0")},
    "RED_GRAPEFRUIT": {"min_ratio": D("7.0"), "min_brix": D("8.0"), "min_juice": D("38.0")},
    "TANGERINE": {"min_ratio": D("9.5"), "min_brix": D("9.0"), "min_juice": D("40.0")},
}
MATURITY_VALIDITY_HOURS = 120
GE_WEIGHTS = {"FANCY": D("1.15"), "CHOICE": D("1.0"), "STANDARD": D("0.9"), "JUICE": D("0.35")}
FRESH_COLOR_MIN = 6
FRESH_DEFECT_MAX = 20
FILL_ASSUMPTION = D("0.8")
TIER1_MAX = 10000
TIER2_MAX = 50000
CARETAKING_OFFSET_CAP_PCT = D("0.5")
ADVANCE_CAP_PCT = D("0.60")
COLD_TREATMENT_MIN_HOURS = 24
CERT_VALIDITY_DAYS = 14
CHEMICAL_MARKUP_PCT = D("0.12")
RATE_CENTS_PER_ACRE = {
    "SPRAY": {"SMALL": 4200, "MEDIUM": 3900, "LARGE": 3500},
    "FERTILIZE": {"SMALL": 3800, "MEDIUM": 3500, "LARGE": 3100},
    "PRUNE": {"SMALL": 5500, "MEDIUM": 5200, "LARGE": 4800},
    "MOW": {"SMALL": 1800, "MEDIUM": 1700, "LARGE": 1500},
}
GRADES = {"FANCY", "CHOICE", "STANDARD", "JUICE"}
REQUIRES_DEGREENING = {"RED_GRAPEFRUIT", "TANGERINE"}
PEST_TYPES = {"CANKER", "HLB_GREENING", "FRUIT_FLY", "BLACK_SPOT"}
CHANNEL_TYPES = {"EXPORT", "DOMESTIC_FRESH", "JUICE"}
DESTINATION_MARKETS = {"JAPAN", "EU", "KOREA", "DOMESTIC", "NONE"}
EXPORT_MARKETS = {"JAPAN", "EU", "KOREA"}
LOT_GRADES = {"FANCY", "CHOICE", "STANDARD"}
SERVICE_TYPES = {"SPRAY", "FERTILIZE", "PRUNE", "MOW"}
RECOUP_POLICIES = {"NEXT_SETTLEMENT_FULL", "PRO_RATA_THIRDS"}


# ---------------------------------------------------------------------------
# Derived: quarantine posture (PRD §2.10)
# ---------------------------------------------------------------------------
def order_covers_grove(order, grove):
    if order["status"] != "ACTIVE":
        return False
    if order["scope_type"] == "GROVE":
        return order["grove_id"] == grove["id"]
    return order["county_code"] == grove["county_code"]


def grove_posture(grove):
    for o in DB["quarantines"].values():
        if order_covers_grove(o, grove):
            return "QUARANTINED"
    return "CLEAR"


def active_fruit_fly_covers(grove):
    for o in DB["quarantines"].values():
        if o["pest_type"] == "FRUIT_FLY" and order_covers_grove(o, grove):
            return True
    return False


# ---------------------------------------------------------------------------
# Maturity helpers
# ---------------------------------------------------------------------------
def current_maturity_test(grove_id):
    cur = None
    for t in DB["maturity_tests"].values():
        if t["grove_id"] == grove_id and t["status"] == "CURRENT":
            if cur is None or (t["created_at"], t["_seq"]) > (cur["created_at"], cur["_seq"]):
                cur = t
    return cur


def maturity_gate(grove, ERR_REQUIRED, ERR_NOT_PASSING, ERR_EXPIRED):
    """Tiers 8 then 11: required -> not passing -> expired."""
    t = current_maturity_test(grove["id"])
    if t is None:
        err(ERR_REQUIRED, 422, "Grove has no CURRENT maturity test")
    if t["result"] != "PASS":
        err(ERR_NOT_PASSING, 422, "Grove's CURRENT maturity test did not pass")
    if now() >= t["expires_at"]:
        err(ERR_EXPIRED, 422, "Grove's CURRENT maturity test has expired")


# ---------------------------------------------------------------------------
# Pool helpers
# ---------------------------------------------------------------------------
def pool_covers_instant(pool, dt):
    start = pool["_week_start_date"]
    d = dt.date()
    return start <= d <= start + timedelta(days=6)


def find_open_pool(variety, dt):
    for p in sort_asc(DB["pools"].values()):
        if p["variety"] == variety and p["status"] == "OPEN" and pool_covers_instant(p, dt):
            return p
    return None


def find_pool_by_variety_week(variety, week_start_str):
    for p in sort_asc(DB["pools"].values()):
        if p["variety"] == variety and p["week_start"] == week_start_str:
            return p
    return None


def find_juice_channel(variety, week_start_str):
    for c in sort_asc(DB["channels"].values()):
        if (
            c["channel_type"] == "JUICE"
            and c["variety"] == variety
            and c["week_start"] == week_start_str
        ):
            return c
    return None


def recompute_provisional(pool):
    """pool_provisional_price (SCAFFOLD §1.3): forward-looking, juice excluded."""
    finite = [
        c
        for c in DB["channels"].values()
        if c["variety"] == pool["variety"]
        and c["week_start"] == pool["week_start"]
        and c["channel_type"] != "JUICE"
    ]
    rem_sum_boxes = sum(c["remaining_boxes"] for c in finite)
    rem_sum_value = sum(c["remaining_boxes"] * c["price_cents_per_box"] for c in finite)
    projected_proceeds = D(pool["posted_proceeds_cents"]) + FILL_ASSUMPTION * D(rem_sum_value)
    projected_ge = pool["posted_ge_boxes"] + FILL_ASSUMPTION * D(rem_sum_boxes)
    denom = projected_ge if projected_ge > 1 else D(1)
    pool["provisional_price_cents_per_ge_box"] = cents(projected_proceeds / denom)


def grower_posted_ge_in_pool(grower_id, pool_id):
    """Sum of ge_boxes over POSTED sort runs of the grower's groves in the pool."""
    grove_ids = {g["id"] for g in DB["groves"].values() if g["grower_id"] == grower_id}
    total = D(0)
    for r in DB["sort_runs"].values():
        if r["status"] != "POSTED":
            continue
        d = DB["deliveries"].get(r["delivery_id"])
        if d is None or d["pool_id"] != pool_id or d["grove_id"] not in grove_ids:
            continue
        total += D(str(r["ge_boxes"]))
    return total


# ---------------------------------------------------------------------------
# Channel posted-allocation (export-lot capacity, grade-scoped)
# ---------------------------------------------------------------------------
def channel_posted_boxes(channel_id, grade):
    total = 0
    for r in DB["sort_runs"].values():
        if r["status"] != "POSTED" or not r.get("allocation"):
            continue
        for line in r["allocation"]:
            if line["channel_id"] == channel_id and line["grade"] == grade:
                total += line["boxes"]
    return total


def channel_reserved_boxes(channel_id, grade, exclude_lot_id=None):
    """Boxes reserved by non-DIVERTED export lots on this channel+grade."""
    total = 0
    for lot in DB["export_lots"].values():
        if lot["id"] == exclude_lot_id:
            continue
        if lot["source_channel_id"] != channel_id or lot["grade"] != grade:
            continue
        if lot["status"] == "DIVERTED":
            continue
        total += lot["boxes"]
    return total


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _base(e):
    return {
        "id": e["id"],
        "created_at": iso_ms(e["created_at"]),
        "updated_at": iso_ms(e["updated_at"]),
        "version": e["version"],
    }


def ser_grower(g):
    out = _base(g)
    out.update(
        grower_code=g["grower_code"],
        display_name=g["display_name"],
        status=g["status"],
        advance_outstanding_cents=g["advance_outstanding_cents"],
        caretaking_balance_cents=g["caretaking_balance_cents"],
    )
    return out


def ser_grove(g):
    out = _base(g)
    out.update(
        grower_id=g["grower_id"],
        block_code=g["block_code"],
        variety=g["variety"],
        acreage=g["acreage"],
        county_code=g["county_code"],
        caretaking_enrolled=g["caretaking_enrolled"],
        lifecycle_status=g["lifecycle_status"],
        quarantine_posture=grove_posture(g),
    )
    return out


def ser_maturity_test(t):
    out = _base(t)
    out.update(
        grove_id=t["grove_id"],
        sampled_at=iso_ms(t["sampled_at"]),
        brix=t["brix"],
        acid_pct=t["acid_pct"],
        juice_pct=t["juice_pct"],
        ratio=f2(t["ratio"]),
        result=t["result"],
        status=t["status"],
        expires_at=iso_ms(t["expires_at"]),
    )
    return out


def ser_crew(c):
    out = _base(c)
    out.update(
        crew_code=c["crew_code"],
        daily_capacity_boxes=c["daily_capacity_boxes"],
        status=c["status"],
    )
    return out


def ser_assignment(a):
    out = _base(a)
    out.update(
        crew_id=a["crew_id"],
        grove_id=a["grove_id"],
        window_start=iso_ms(a["window_start"]),
        window_end=iso_ms(a["window_end"]),
        planned_boxes=a["planned_boxes"],
        actual_boxes=a["actual_boxes"],
        status=a["status"],
    )
    return out


def ser_delivery(d):
    out = _base(d)
    out.update(
        grove_id=d["grove_id"],
        assignment_id=d["assignment_id"],
        received_at=iso_ms(d["received_at"]),
        variety=d["variety"],
        gross_boxes=d["gross_boxes"],
        tare_boxes=d["tare_boxes"],
        net_boxes=d["net_boxes"],
        processing_status=d["processing_status"],
        regulatory_status=d["regulatory_status"],
        pool_id=d["pool_id"],
        requires_degreening=d["requires_degreening"],
    )
    return out


def ser_room(r):
    out = _base(r)
    out.update(
        room_code=r["room_code"],
        capacity_boxes=r["capacity_boxes"],
        min_hours=r["min_hours"],
        max_hours=r["max_hours"],
        status=r["status"],
    )
    return out


def ser_session(s):
    out = _base(s)
    out.update(
        room_id=s["room_id"],
        delivery_id=s["delivery_id"],
        boxes=s["boxes"],
        planned_hours=s["planned_hours"],
        color_add_applied=s["color_add_applied"],
        started_at=iso_ms(s["started_at"]),
        released_at=iso_ms(s["released_at"]) if s["released_at"] else None,
        duration_hours=(f2(s["duration_hours"]) if s["duration_hours"] is not None else None),
        status=s["status"],
    )
    return out


def ser_sort_run(r):
    out = _base(r)
    out.update(
        delivery_id=r["delivery_id"],
        fancy_boxes=r["fancy_boxes"],
        choice_boxes=r["choice_boxes"],
        standard_boxes=r["standard_boxes"],
        juice_boxes=r["juice_boxes"],
        cull_boxes=r["cull_boxes"],
        color_score=r["color_score"],
        defect_pct=r["defect_pct"],
        fresh_eligible=r["fresh_eligible"],
        ge_boxes=f2(r["ge_boxes"]),
        proceeds_cents=r["proceeds_cents"],
        allocation=r["allocation"],
        created_by=r["created_by"],
        verified_by=r["verified_by"],
        status=r["status"],
    )
    return out


def ser_channel(c):
    out = _base(c)
    out.update(
        channel_code=c["channel_code"],
        channel_type=c["channel_type"],
        destination_market=c["destination_market"],
        variety=c["variety"],
        week_start=c["week_start"],
        allocation_boxes=c["allocation_boxes"],
        price_cents_per_box=c["price_cents_per_box"],
        priority_rank=c["priority_rank"],
        accepts_grades=list(c["accepts_grades"]),
        remaining_boxes=c["remaining_boxes"],
    )
    return out


def ser_pool(p):
    out = _base(p)
    out.update(
        variety=p["variety"],
        week_start=p["week_start"],
        status=p["status"],
        posted_ge_boxes=f2(p["posted_ge_boxes"]),
        posted_proceeds_cents=p["posted_proceeds_cents"],
        sorted_field_boxes=p["sorted_field_boxes"],
        provisional_price_cents_per_ge_box=p["provisional_price_cents_per_ge_box"],
        final_price_cents_per_ge_box=p["final_price_cents_per_ge_box"],
    )
    return out


def ser_advance(a):
    out = _base(a)
    out.update(
        grower_id=a["grower_id"],
        pool_id=a["pool_id"],
        amount_cents=a["amount_cents"],
        recoup_policy=a["recoup_policy"],
        status=a["status"],
        issued_at=iso_ms(a["issued_at"]) if a["issued_at"] else None,
        recouped_cents=a["recouped_cents"],
        written_off_cents=a["written_off_cents"],
        outstanding_cents=a["outstanding_cents"],
    )
    return out


def ser_ct_order(o):
    out = _base(o)
    out.update(
        grove_id=o["grove_id"],
        service_type=o["service_type"],
        service_date=o["service_date"].isoformat(),
        acres_treated=o["acres_treated"],
        chemical_cost_cents=o["chemical_cost_cents"],
        rate_tier=o["rate_tier"],
        line_amount_cents=o["line_amount_cents"],
        invoice_id=o["invoice_id"],
        status=o["status"],
    )
    return out


def ser_ct_invoice(i):
    out = _base(i)
    out.update(
        grower_id=i["grower_id"],
        period_start=i["period_start"].isoformat(),
        period_end=i["period_end"].isoformat(),
        line_order_ids=list(i["line_order_ids"]),
        total_cents=i["total_cents"],
        paid_cents=i["paid_cents"],
        status=i["status"],
    )
    return out


def ser_quarantine(o):
    out = _base(o)
    out.update(
        scope_type=o["scope_type"],
        grove_id=o["grove_id"],
        county_code=o["county_code"],
        pest_type=o["pest_type"],
        status=o["status"],
        issued_at=iso_ms(o["issued_at"]),
        issued_by=o["issued_by"],
        released_at=iso_ms(o["released_at"]) if o["released_at"] else None,
        released_by=o["released_by"],
    )
    return out


def ser_export_lot(l):
    out = _base(l)
    out.update(
        destination_market=l["destination_market"],
        variety=l["variety"],
        grade=l["grade"],
        boxes=l["boxes"],
        source_channel_id=l["source_channel_id"],
        source_grove_id=l["source_grove_id"],
        cold_treatment_hours=l["cold_treatment_hours"],
        pool_id=l["pool_id"],
        inspection_requested_by=l["inspection_requested_by"],
        phyto_certificate_id=l["phyto_certificate_id"],
        diverted_to=l["diverted_to"],
        status=l["status"],
    )
    return out


def ser_cert(c):
    out = _base(c)
    out.update(
        export_lot_id=c["export_lot_id"],
        certificate_number=c["certificate_number"],
        inspection_result=c["inspection_result"],
        issued_at=iso_ms(c["issued_at"]),
        issued_by=c["issued_by"],
        expires_at=iso_ms(c["expires_at"]),
        status=c["status"],
    )
    return out
