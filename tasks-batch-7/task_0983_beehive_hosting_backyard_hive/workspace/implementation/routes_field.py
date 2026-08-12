"""Routes: inspections, treatments, harvests, honey allocations."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import services as svc
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
                    ERR_NOT_RESOURCE_OWNER, ERR_SEGREGATION_OF_DUTIES,
                    ERR_INSPECTION_NOT_SUBMITTED, ERR_HIVE_NOT_OPERABLE, ERR_HIVE_QUARANTINED,
                    ERR_WITHDRAWAL_WINDOW_ACTIVE, ERR_INSPECTION_STALE,
                    ERR_TREATMENT_WINDOW_OVERLAP, ERR_ALLOCATION_NOT_DISTRIBUTABLE)
from middleware import auth, body, ALL_AUTHENTICATED
from response import success, paginate
from util import new_base, touch, pub, req_int, req_num, req_bool, req_enum, req_dt, req_str
from routes_core import _get

bp = Blueprint("field", __name__)

TREATMENT_PRODUCTS = ("OXALIC_ACID", "APIVAR", "FORMIC_ACID")


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------

@bp.post("/api/inspections")
def create_inspection():
    uid, _ = auth(("Beekeeper",))
    b = body()
    hive_id = b.get("hive_id")
    if not isinstance(hive_id, str) or not hive_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'hive_id' is required")
    hive = db.hives.get(hive_id)
    if hive is None:
        raise_err(ERR_NOT_FOUND, "Hive %s not found" % hive_id)
    inspected_at = req_dt(b, "inspected_at")
    mites = req_int(b, "mites_counted", minv=0)
    bees = req_int(b, "bees_sampled", minv=1)
    disease = req_bool(b, "disease_flag")
    brood = req_int(b, "brood_score", minv=0, maxv=10)
    queen = req_bool(b, "queen_seen")
    stores = req_num(b, "stores_kg", minv=0)
    if hive["lifecycle_status"] in ("DEAD", "REMOVED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is DEAD or REMOVED")
    insp = new_base()
    insp.update({"hive_id": hive_id, "recorded_by_id": uid, "inspected_at": inspected_at,
                 "mites_counted": mites, "bees_sampled": bees,
                 "mite_load_per_100": svc.compute_mite_load(mites, bees),
                 "disease_flag": disease, "brood_score": brood, "queen_seen": queen,
                 "stores_kg": stores, "status": "DRAFT",
                 "return_reason": None, "verified_by_id": None})
    db.inspections[insp["id"]] = insp
    return success(pub(insp), 201)


@bp.get("/api/inspections/<iid>")
def get_inspection(iid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.inspections, iid)), 200)


@bp.get("/api/inspections")
def list_inspections():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.inspections)
    hive_id = request.args.get("hive_id")
    if hive_id is not None:
        items = [i for i in items if i["hive_id"] == hive_id]
    page, meta = paginate(items)
    return success([pub(i) for i in page], 200, meta)


@bp.post("/api/inspections/<iid>/submit")
def submit_inspection(iid):
    uid, _ = auth(("Beekeeper",))
    insp = _get(db.inspections, iid)
    if insp["recorded_by_id"] != uid:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Only the recording beekeeper may submit")
    if insp["status"] not in ("DRAFT", "RETURNED"):
        raise_err(ERR_INVALID_STATE, "Inspection is not DRAFT or RETURNED")
    insp["status"] = "SUBMITTED"
    touch(insp)
    return success(pub(insp), 200)


@bp.post("/api/inspections/<iid>/verify")
def verify_inspection(iid):
    uid, _ = auth(("ApiaryManager",))
    insp = _get(db.inspections, iid)
    if insp["status"] != "SUBMITTED":
        raise_err(ERR_INSPECTION_NOT_SUBMITTED, "Inspection is not SUBMITTED")
    hive = db.hives.get(insp["hive_id"])
    if hive is not None and hive["lifecycle_status"] in ("DEAD", "REMOVED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is DEAD or REMOVED")
    if insp["recorded_by_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Verifier must differ from recorder")
    insp["status"] = "VERIFIED"
    insp["verified_by_id"] = uid
    touch(insp)
    if hive is not None:
        svc.apply_verify_cascade(hive)
    return success(pub(insp), 200)


@bp.post("/api/inspections/<iid>/return")
def return_inspection(iid):
    uid, _ = auth(("ApiaryManager",))
    insp = _get(db.inspections, iid)
    b = body()
    reason = req_str(b, "return_reason")
    if insp["status"] != "SUBMITTED":
        raise_err(ERR_INSPECTION_NOT_SUBMITTED, "Inspection is not SUBMITTED")
    if insp["recorded_by_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Returner must differ from recorder")
    insp["status"] = "RETURNED"
    insp["return_reason"] = reason
    touch(insp)
    return success(pub(insp), 200)


# ---------------------------------------------------------------------------
# Treatments
# ---------------------------------------------------------------------------

@bp.post("/api/treatments")
def create_treatment():
    auth(("ApiaryManager",))
    b = body()
    hive_id = b.get("hive_id")
    if not isinstance(hive_id, str) or not hive_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'hive_id' is required")
    hive = db.hives.get(hive_id)
    if hive is None:
        raise_err(ERR_NOT_FOUND, "Hive %s not found" % hive_id)
    product = req_enum(b, "product", TREATMENT_PRODUCTS)
    start = req_dt(b, "start_date")
    end = req_dt(b, "end_date")
    if end <= start:
        raise_err(ERR_INVALID_REQUEST, "end_date must be after start_date")
    if hive["lifecycle_status"] in ("DEAD", "REMOVED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is DEAD or REMOVED")
    # Half-open window overlap: [start, end) vs existing [s, e).
    for t in db.treatments.values():
        if t["hive_id"] == hive_id and start < t["end_date"] and t["start_date"] < end:
            raise_err(ERR_TREATMENT_WINDOW_OVERLAP, "Treatment window overlaps an existing treatment")
    tr = new_base()
    tr.update({"hive_id": hive_id, "product": product, "start_date": start, "end_date": end,
               "status": "SCHEDULED", "withdrawal_end_date": end + timedelta(days=14),
               "started_at": None, "completed_at": None})
    db.treatments[tr["id"]] = tr
    return success(pub(tr), 201)


@bp.get("/api/treatments/<tid>")
def get_treatment(tid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.treatments, tid)), 200)


@bp.get("/api/treatments")
def list_treatments():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.treatments)
    hive_id = request.args.get("hive_id")
    if hive_id is not None:
        items = [t for t in items if t["hive_id"] == hive_id]
    page, meta = paginate(items)
    return success([pub(t) for t in page], 200, meta)


@bp.post("/api/treatments/<tid>/start")
def start_treatment(tid):
    auth(("Beekeeper",))
    tr = _get(db.treatments, tid)
    if tr["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Treatment is not SCHEDULED")
    hive = db.hives.get(tr["hive_id"])
    if hive is None or hive["lifecycle_status"] not in ("ACTIVE", "QUARANTINED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is not ACTIVE or QUARANTINED")
    tr["status"] = "IN_PROGRESS"
    tr["started_at"] = db.now()
    touch(tr)
    return success(pub(tr), 200)


@bp.post("/api/treatments/<tid>/complete")
def complete_treatment(tid):
    auth(("Beekeeper",))
    tr = _get(db.treatments, tid)
    if tr["status"] != "IN_PROGRESS":
        raise_err(ERR_INVALID_STATE, "Treatment is not IN_PROGRESS")
    tr["status"] = "COMPLETED"
    tr["completed_at"] = db.now()
    touch(tr)
    return success(pub(tr), 200)


# ---------------------------------------------------------------------------
# Harvests
# ---------------------------------------------------------------------------

def _allocation_for_harvest(hv):
    season_id = hv.get("_season_id")
    if season_id is not None:
        alloc = svc.find_allocation(season_id, hv["hive_id"])
        if alloc is not None:
            return alloc
    season = svc.open_season()
    if season is not None:
        return svc.find_allocation(season["id"], hv["hive_id"])
    return None


@bp.post("/api/harvests")
def create_harvest():
    uid, _ = auth(("Beekeeper",))
    b = body()
    hive_id = b.get("hive_id")
    if not isinstance(hive_id, str) or not hive_id:
        raise_err(ERR_INVALID_REQUEST, "Field 'hive_id' is required")
    hive = db.hives.get(hive_id)
    if hive is None:
        raise_err(ERR_NOT_FOUND, "Hive %s not found" % hive_id)
    collected_on = req_dt(b, "collected_on")
    gross = req_num(b, "gross_kg", max_dp=3)
    if gross <= 0:
        raise_err(ERR_INVALID_REQUEST, "gross_kg must be strictly above 0")
    moisture = req_num(b, "moisture_pct", minv=0, max_dp=2)
    if moisture > Decimal(100):
        raise_err(ERR_INVALID_REQUEST, "moisture_pct must be between 0 and 100")
    # State (step 6): operable hive.
    if hive["lifecycle_status"] in ("DEAD", "REMOVED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is DEAD or REMOVED")
    # Safety (step 7): quarantine, then withdrawal embargo.
    if hive["lifecycle_status"] == "QUARANTINED":
        raise_err(ERR_HIVE_QUARANTINED, "Quarantined hive may not be harvested")
    for t in db.treatments.values():
        if (t["hive_id"] == hive_id and t["status"] in ("IN_PROGRESS", "COMPLETED")
                and t["start_date"] <= collected_on < t["withdrawal_end_date"]):
            raise_err(ERR_WITHDRAWAL_WINDOW_ACTIVE,
                      "collected_on falls inside a treatment withdrawal window")
    # Temporal (step 10): fresh VERIFIED inspection within [collected_on - 30d, collected_on].
    window_start = collected_on - timedelta(days=30)
    fresh = any(i for i in db.inspections.values()
                if i["hive_id"] == hive_id and i["status"] == "VERIFIED"
                and window_start <= i["inspected_at"] <= collected_on)
    if not fresh:
        raise_err(ERR_INSPECTION_STALE, "No VERIFIED inspection within 30 days of collected_on")
    hv = new_base()
    hv.update({"hive_id": hive_id, "collected_on": collected_on, "gross_kg": gross,
               "moisture_pct": moisture, "net_kg": svc.compute_net_kg(gross, moisture),
               "status": "RECORDED", "recorded_by_id": uid, "approved_by_id": None,
               "_season_id": (svc.open_season() or {}).get("id") if svc.open_season() else None})
    db.harvests[hv["id"]] = hv
    # PRD §3.6: projected_pool_net_kg sums net_kg over harvests in RECORDED
    # or APPROVED status — refresh an existing PROJECTED allocation so the
    # reported field reflects the just-recorded harvest.
    if hv["_season_id"] is not None:
        alloc = svc.find_allocation(hv["_season_id"], hive_id)
        if alloc is not None and alloc["status"] == "PROJECTED":
            svc.recompute_allocation_projected(alloc)
    return success(pub(hv), 201)


@bp.get("/api/harvests/<hid>")
def get_harvest(hid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.harvests, hid)), 200)


@bp.get("/api/harvests")
def list_harvests():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.harvests)
    hive_id = request.args.get("hive_id")
    if hive_id is not None:
        items = [h for h in items if h["hive_id"] == hive_id]
    page, meta = paginate(items)
    return success([pub(h) for h in page], 200, meta)


@bp.post("/api/harvests/<hid>/approve")
def approve_harvest(hid):
    uid, _ = auth(("ApiaryManager",))
    hv = _get(db.harvests, hid)
    if hv["status"] != "RECORDED":
        raise_err(ERR_INVALID_STATE, "Harvest is not RECORDED")
    hive = db.hives.get(hv["hive_id"])
    if hive is None or hive["lifecycle_status"] not in ("ACTIVE", "QUARANTINED"):
        raise_err(ERR_HIVE_NOT_OPERABLE, "Hive is not ACTIVE or QUARANTINED")
    season = svc.open_season()
    alloc = svc.find_allocation(season["id"], hv["hive_id"]) if season is not None else None
    if alloc is not None and alloc["status"] in ("FINALIZED", "DISTRIBUTED"):
        raise_err(ERR_ALLOCATION_NOT_DISTRIBUTABLE, "Allocation is already finalized")
    if hv["recorded_by_id"] == uid:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Approver must differ from recorder")
    hv["status"] = "APPROVED"
    hv["approved_by_id"] = uid
    if season is not None:
        hv["_season_id"] = season["id"]
    touch(hv)
    if season is not None:
        if alloc is None:
            alloc = new_base()
            alloc.update({"season_id": season["id"], "hive_id": hv["hive_id"],
                          "status": "PROJECTED", "projected_pool_net_kg": Decimal("0"),
                          "projected_host_kg": Decimal("0"), "pool_net_kg": None,
                          "effective_bps": None, "host_kg": None, "reserve_kg": None,
                          "operator_kg": None, "edu_bonus_kg": None,
                          "finalized_at": None, "distributed_at": None})
            db.allocations[alloc["id"]] = alloc
        svc.recompute_allocation_projected(alloc)
    return success(pub(hv), 200)


@bp.post("/api/harvests/<hid>/void")
def void_harvest(hid):
    auth(("ApiaryManager",))
    hv = _get(db.harvests, hid)
    if hv["status"] not in ("RECORDED", "APPROVED"):
        raise_err(ERR_INVALID_STATE, "Harvest is not RECORDED or APPROVED")
    alloc = _allocation_for_harvest(hv)
    if alloc is not None and alloc["status"] in ("FINALIZED", "DISTRIBUTED"):
        raise_err(ERR_ALLOCATION_NOT_DISTRIBUTABLE, "Allocation is already finalized")
    hv["status"] = "VOIDED"
    touch(hv)
    if alloc is not None:
        svc.recompute_allocation_projected(alloc)
    return success(pub(hv), 200)


# ---------------------------------------------------------------------------
# Honey allocations
# ---------------------------------------------------------------------------

@bp.get("/api/allocations/<aid>")
def get_allocation(aid):
    auth(ALL_AUTHENTICATED)
    return success(pub(_get(db.allocations, aid)), 200)


@bp.get("/api/allocations")
def list_allocations():
    auth(ALL_AUTHENTICATED)
    items = svc.sorted_all(db.allocations)
    season_id = request.args.get("season_id")
    hive_id = request.args.get("hive_id")
    if season_id is not None:
        items = [a for a in items if a["season_id"] == season_id]
    if hive_id is not None:
        items = [a for a in items if a["hive_id"] == hive_id]
    page, meta = paginate(items)
    return success([pub(a) for a in page], 200, meta)


@bp.post("/api/allocations/<aid>/distribute")
def distribute_allocation(aid):
    auth(("PlatformOps",))
    alloc = _get(db.allocations, aid)
    if alloc["status"] != "FINALIZED":
        raise_err(ERR_ALLOCATION_NOT_DISTRIBUTABLE, "Allocation is not FINALIZED")
    hive = db.hives.get(alloc["hive_id"])
    site = db.sites.get(hive["site_id"]) if hive else None
    host = db.hosts.get(site["host_id"]) if site else None
    if host is not None:
        from decimal import Decimal as _D
        host["honey_credit_kg"] = _D(str(host["honey_credit_kg"])) + alloc["host_kg"]
        touch(host)
    for h in db.harvests.values():
        if (h["hive_id"] == alloc["hive_id"] and h.get("_season_id") == alloc["season_id"]
                and h["status"] == "APPROVED"):
            h["status"] = "SETTLED"
            touch(h)
    alloc["status"] = "DISTRIBUTED"
    alloc["distributed_at"] = db.now()
    touch(alloc)
    return success(pub(alloc), 200)
