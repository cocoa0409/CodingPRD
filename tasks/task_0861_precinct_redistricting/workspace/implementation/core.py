"""In-memory store, logical clock, calculations, and serializers.

All state is process-local and wiped on every fresh boot (start.sh re-invokes
the server before every test). No file/db persistence.
"""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4
import hashlib
import itertools

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

VALID_ROLES = {"Cartographer", "Demographer", "CommissionChair",
               "ElectionClerk", "PublicParticipant"}
ALL_ROLES = ["Cartographer", "Demographer", "CommissionChair",
             "ElectionClerk", "PublicParticipant"]

MAX_ABS_DEVIATION_PCT = Decimal("5.0")
REGISTRATION_RATE = Decimal("0.85")
SETUP_BUFFER_MINUTES = 60


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO-8601 UTC instant into a naive UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def render_ts(dt):
    """Render a naive UTC datetime as ISO-8601 with exactly 3 fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def rhu(value, places):
    """Round-half-up to `places` decimals; return a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal(1) if places == 0 else Decimal("1").scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def num(dec):
    """Convert a Decimal to a JSON-friendly float."""
    return float(dec)


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.jurisdictions = {}
        self.census_blocks = {}
        self.plans = {}
        self.districts = {}
        self.block_assignments = {}
        self.precincts = {}
        self.polling_places = {}
        self.polling_assignments = {}
        self.venues = {}
        self.hearings = {}
        self.comments = {}
        self.compliance_checks = {}
        self.gis_exports = {}
        self.clock = parse_iso(DEFAULT_CLOCK)
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def new_base():
    now = db.clock
    return {
        "id": str(uuid4()),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(rec):
    rec["updated_at"] = db.clock
    rec["version"] += 1


def common(rec):
    return {
        "id": rec["id"],
        "created_at": render_ts(rec["created_at"]),
        "updated_at": render_ts(rec["updated_at"]),
        "version": rec["version"],
    }


# ---------------------------------------------------------------------------
# Aggregation / calculation helpers
# ---------------------------------------------------------------------------
def juris_blocks(jid):
    return [b for b in db.census_blocks.values() if b["jurisdiction_id"] == jid]


def juris_totals(j):
    blocks = juris_blocks(j["id"])
    total = sum(b["population"] for b in blocks)
    vap = sum(b["voting_age_population"] for b in blocks)
    tc = j["target_district_count"]
    if tc:
        ideal = rhu(Decimal(total) / Decimal(tc), 4)
    else:
        ideal = Decimal("0")
    return total, vap, ideal


def active_district_bas(district_id):
    return [ba for ba in db.block_assignments.values()
            if ba["district_id"] == district_id and ba["status"] == "ACTIVE"]


def district_metrics(d):
    plan = db.plans[d["plan_id"]]
    j = db.jurisdictions[plan["jurisdiction_id"]]
    _, _, ideal = juris_totals(j)
    bas = active_district_bas(d["id"])
    blocks = [db.census_blocks[ba["census_block_id"]] for ba in bas]
    assigned = sum(b["population"] for b in blocks)
    target = ideal  # Decimal, 4dp
    deviation = int(rhu(Decimal(assigned) - target, 0))
    if target == 0:
        dev_pct = Decimal("0.00")
    else:
        dev_pct = rhu((Decimal(assigned) - target) / target * 100, 2)
    sum_min = sum(b["minority_vap"] for b in blocks)
    sum_vap = sum(b["voting_age_population"] for b in blocks)
    if sum_vap == 0:
        mvp = Decimal("0.00")
    else:
        mvp = rhu(Decimal(sum_min) / Decimal(sum_vap) * 100, 2)
    is_mm = mvp > Decimal("50.0")
    retained = False
    geoid = d.get("incumbent_home_geoid")
    if geoid:
        for b in blocks:
            if b["geoid"] == geoid:
                retained = True
                break
    return {
        "assigned_population": assigned,
        "target_population": target,
        "deviation": deviation,
        "deviation_pct": dev_pct,
        "minority_vap_pct": mvp,
        "is_majority_minority": is_mm,
        "incumbent_retained": retained,
    }


def plan_districts(plan_id):
    return [d for d in db.districts.values() if d["plan_id"] == plan_id]


def plan_metrics(p):
    ds = plan_districts(p["id"])
    metrics = [district_metrics(d) for d in ds]
    dps = [m["deviation_pct"] for m in metrics]
    if not dps:
        max_abs = Decimal("0.00")
        rng = Decimal("0.00")
    else:
        max_abs = max(abs(x) for x in dps)
        rng = max(dps) - min(dps)
    mm_count = sum(1 for m in metrics if m["is_majority_minority"])
    return {
        "max_abs_deviation_pct": max_abs,
        "overall_deviation_range_pct": rng,
        "majority_minority_district_count": mm_count,
    }


def full_partition(plan):
    blocks = juris_blocks(plan["jurisdiction_id"])
    for b in blocks:
        cnt = sum(1 for ba in db.block_assignments.values()
                  if ba["plan_id"] == plan["id"]
                  and ba["census_block_id"] == b["id"]
                  and ba["status"] == "ACTIVE")
        if cnt != 1:
            return False
    return True


def plan_is_compliant(p):
    m = plan_metrics(p)
    j = db.jurisdictions[p["jurisdiction_id"]]
    ds = plan_districts(p["id"])
    within = m["max_abs_deviation_pct"] <= MAX_ABS_DEVIATION_PCT
    vra = m["majority_minority_district_count"] >= j["required_majority_minority_districts"]
    contig = all(d["is_contiguous"] for d in ds)
    part = full_partition(p)
    return bool(within and vra and contig and part)


def precinct_blocks(precinct_id):
    return [b for b in db.census_blocks.values() if b.get("precinct_id") == precinct_id]


def precinct_registered_voters(p):
    if p["status"] in ("SPLIT", "MERGED"):
        return 0
    blocks = precinct_blocks(p["id"])
    if p["voter_count_basis"] == "PROVISIONAL":
        total_vap = sum(b["voting_age_population"] for b in blocks)
        return int(rhu(Decimal(total_vap) * REGISTRATION_RATE, 0))
    else:  # CERTIFIED
        return sum(b["registered_voters"] for b in blocks)


def active_place_assignments(place_id):
    return [pa for pa in db.polling_assignments.values()
            if pa["polling_place_id"] == place_id and pa["status"] == "ACTIVE"]


def place_assigned_voters(place):
    total = 0
    for pa in active_place_assignments(place["id"]):
        pr = db.precincts.get(pa["precinct_id"])
        if pr:
            total += precinct_registered_voters(pr)
    return total


def gis_checksum(plan):
    pairs = []
    for ba in db.block_assignments.values():
        if ba["plan_id"] == plan["id"] and ba["status"] == "ACTIVE":
            d = db.districts[ba["district_id"]]
            cb = db.census_blocks[ba["census_block_id"]]
            pairs.append((d["district_number"], cb["geoid"]))
    pairs.sort(key=lambda x: (x[0], x[1]))
    s = "|".join("%s:%s" % (n, g) for n, g in pairs)
    return hashlib.sha256(s.encode("utf-8")).hexdigest(), len(pairs)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_jurisdiction(j):
    total, vap, ideal = juris_totals(j)
    out = common(j)
    out.update({
        "name": j["name"],
        "state_code": j["state_code"],
        "target_district_count": j["target_district_count"],
        "required_majority_minority_districts": j["required_majority_minority_districts"],
        "total_population": total,
        "voting_age_population_total": vap,
        "ideal_district_population": num(ideal),
    })
    return out


def ser_census_block(b):
    out = common(b)
    out.update({
        "jurisdiction_id": b["jurisdiction_id"],
        "geoid": b["geoid"],
        "population": b["population"],
        "voting_age_population": b["voting_age_population"],
        "minority_vap": b["minority_vap"],
        "registered_voters": b["registered_voters"],
        "precinct_id": b.get("precinct_id"),
    })
    return out


def ser_plan(p):
    m = plan_metrics(p)
    out = common(p)
    out.update({
        "jurisdiction_id": p["jurisdiction_id"],
        "name": p["name"],
        "parent_plan_id": p.get("parent_plan_id"),
        "created_by_user_id": p["created_by_user_id"],
        "status": p["status"],
        "max_abs_deviation_pct": num(m["max_abs_deviation_pct"]),
        "overall_deviation_range_pct": num(m["overall_deviation_range_pct"]),
        "majority_minority_district_count": m["majority_minority_district_count"],
        "is_compliant": plan_is_compliant(p),
        "comment_opened_at": render_ts(p.get("comment_opened_at")),
        "adopted_at": render_ts(p.get("adopted_at")),
    })
    return out


def ser_district(d):
    m = district_metrics(d)
    out = common(d)
    out.update({
        "plan_id": d["plan_id"],
        "district_number": d["district_number"],
        "name": d.get("name"),
        "is_contiguous": d["is_contiguous"],
        "incumbent_name": d.get("incumbent_name"),
        "incumbent_home_geoid": d.get("incumbent_home_geoid"),
        "target_population": num(m["target_population"]),
        "assigned_population": m["assigned_population"],
        "deviation": m["deviation"],
        "deviation_pct": num(m["deviation_pct"]),
        "minority_vap_pct": num(m["minority_vap_pct"]),
        "is_majority_minority": m["is_majority_minority"],
        "incumbent_retained": m["incumbent_retained"],
    })
    return out


def ser_block_assignment(ba):
    out = common(ba)
    out.update({
        "plan_id": ba["plan_id"],
        "district_id": ba["district_id"],
        "census_block_id": ba["census_block_id"],
        "status": ba["status"],
    })
    return out


def ser_precinct(p):
    out = common(p)
    out.update({
        "jurisdiction_id": p["jurisdiction_id"],
        "name": p["name"],
        "parent_precinct_id": p.get("parent_precinct_id"),
        "status": p["status"],
        "voter_count_basis": p["voter_count_basis"],
        "registered_voters": precinct_registered_voters(p),
    })
    return out


def ser_polling_place(pp):
    assigned = place_assigned_voters(pp)
    cap = pp["capacity"]
    util = rhu(Decimal(assigned) / Decimal(cap) * 100, 2) if cap else Decimal("0.00")
    out = common(pp)
    out.update({
        "jurisdiction_id": pp["jurisdiction_id"],
        "name": pp["name"],
        "address": pp["address"],
        "capacity": pp["capacity"],
        "status": pp["status"],
        "assigned_registered_voters": assigned,
        "utilization_pct": num(util),
        "is_over_capacity": assigned > cap,
    })
    return out


def ser_polling_assignment(pa):
    out = common(pa)
    out.update({
        "precinct_id": pa["precinct_id"],
        "polling_place_id": pa["polling_place_id"],
        "ev_start_date": pa["ev_start_date"],
        "ev_end_date": pa["ev_end_date"],
        "status": pa["status"],
    })
    return out


def ser_venue(v):
    out = common(v)
    out.update({
        "jurisdiction_id": v["jurisdiction_id"],
        "name": v["name"],
        "capacity": v["capacity"],
    })
    return out


def ser_hearing(h):
    out = common(h)
    out.update({
        "plan_id": h["plan_id"],
        "venue_id": h["venue_id"],
        "scheduled_start": h["scheduled_start"],
        "scheduled_end": h["scheduled_end"],
        "status": h["status"],
    })
    return out


def ser_comment(c):
    out = common(c)
    out.update({
        "plan_id": c["plan_id"],
        "commenter_name": c["commenter_name"],
        "comment_text": c["comment_text"],
        "disposition": c["disposition"],
    })
    return out


def ser_compliance_check(cc):
    return {
        "id": cc["id"],
        "created_at": render_ts(cc["created_at"]),
        "plan_id": cc["plan_id"],
        "check_type": cc["check_type"],
        "result_status": cc["result_status"],
        "max_abs_deviation_pct": num(cc["max_abs_deviation_pct"]),
        "overall_deviation_range_pct": num(cc["overall_deviation_range_pct"]),
        "majority_minority_district_count": cc["majority_minority_district_count"],
        "detail": cc["detail"],
    }


def ser_gis_export(g):
    out = common(g)
    out.update({
        "plan_id": g["plan_id"],
        "export_format": g["export_format"],
        "status": g["status"],
        "block_count": g["block_count"],
        "district_count": g["district_count"],
        "checksum": g["checksum"],
    })
    return out
