"""Adult trap surveillance chain of custody and the arbovirus laboratory."""
from flask import Blueprint

import calc
import domain
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, authenticate, authorize, created,
    get_body, logical_now, logical_today, ok, ok_list, opt_decimal, opt_enum,
    opt_string, pagination, paginate, parse_date, query_enum, query_str,
    req_enum, req_int, req_present, validation,
)

bp = Blueprint("lab", __name__)

SPECIES = ("CULEX_PIPIENS", "CULEX_TARSALIS", "AEDES_AEGYPTI",
           "AEDES_ALBOPICTUS", "OTHER")
COLLECTION_STATUSES = ("LOGGED", "SUBMITTED", "POOLED", "VOIDED")
POOL_STATUSES = ("CREATED", "IN_TESTING", "RESULT_POSITIVE", "RESULT_NEGATIVE",
                 "INVALID", "DISCARDED")
ASSAYS = ("RT_PCR", "VECTEST")
RESULTS = ("POSITIVE", "NEGATIVE", "INVALID")

COLLECTION_ACTORS = {"SUBMIT": "FieldTech", "VOID": "AbatementManager"}
POOL_ACTORS = {"START_TEST": "LabAnalyst", "RESULT": "LabAnalyst",
               "DISCARD": "LabAnalyst"}


# --------------------------------------------------------------------------
# Trap collections
# --------------------------------------------------------------------------


@bp.post("/trap-sites/<trap_site_id>/collections")
def create_collection(trap_site_id):
    actor = authorize(authenticate(), ("FieldTech",))
    site = store.fetch("TrapSite", trap_site_id)
    body = get_body()
    collection_date = parse_date(req_present(body, "collection_date"), "collection_date")
    trap_nights = req_int(body, "trap_nights", minimum=1)
    female_count = req_int(body, "female_count", minimum=0)
    species = req_enum(body, "species", SPECIES)

    for existing in store.TRAP_COLLECTIONS.values():
        if existing["trap_site_id"] != site["id"]:
            continue
        if existing["collection_date"] != collection_date:
            continue
        if existing["status"] != "VOIDED":
            raise ApiError("ERR_DUPLICATE_RESOURCE", 409,
                           "A live collection already exists for that trap-site day.")

    record = store.new_record()
    record.update({
        "trap_site_id": site["id"],
        "recorded_by_applicator_id": actor.user_id,
        "collection_date": collection_date,
        "trap_nights": trap_nights,
        "female_count": female_count,
        "species": species,
        "status": "LOGGED",
        "pooled_mosquito_count": 0,
        "positive_pool_count": 0,
        "wnv_detected": False,
        "void_reason": None,
    })
    store.TRAP_COLLECTIONS[record["id"]] = record
    return created(views.trap_collection_view(record))


@bp.get("/trap-collections")
def list_collections():
    authorize(authenticate(), ALL_DISTRICT_READERS)
    limit, offset = pagination()
    trap_site_id = query_str("trap_site_id")
    recorded_by = query_str("recorded_by_applicator_id")
    status = query_enum("status", COLLECTION_STATUSES)
    rows = [c for c in store.TRAP_COLLECTIONS.values()
            if (trap_site_id is None or c["trap_site_id"] == trap_site_id)
            and (recorded_by is None or c["recorded_by_applicator_id"] == recorded_by)
            and (status is None or c["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.trap_collection_view(r) for r in page], limit, offset, total)


@bp.get("/trap-collections/<collection_id>")
def get_collection(collection_id):
    authorize(authenticate(), ALL_DISTRICT_READERS)
    collection = store.fetch("TrapCollection", collection_id)
    return ok(views.trap_collection_view(collection))


@bp.post("/trap-collections/<collection_id>/transitions")
def transition_collection(collection_id):
    actor = authorize(authenticate(), ("FieldTech", "AbatementManager"))
    body = get_body()
    action, known = domain.read_action(body, COLLECTION_ACTORS)
    domain.enforce_actor(action, known, COLLECTION_ACTORS, actor)

    collection = store.fetch("TrapCollection", collection_id)

    if known and action == "SUBMIT":
        if actor.user_id != collection["recorded_by_applicator_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Only the logging technician may submit this collection.")

    domain.require_action_supplied(action)
    void_reason = opt_string(body, "void_reason", 1, 1000) if known and action == "VOID" else None
    domain.require_known_action(action, known)

    area = domain.area_of_collection(collection)

    if action == "SUBMIT":
        if collection["status"] != "LOGGED":
            raise domain.invalid_transition("SUBMIT requires a LOGGED collection.")
        age_days = (logical_today() - collection["collection_date"]).days
        if age_days > calc.TRAP_COLLECTION_MAX_AGE_DAYS:
            raise ApiError("ERR_COLLECTION_WINDOW_EXPIRED", 422,
                           "The collection is older than the submission window.")
        collection["status"] = "SUBMITTED"
        store.touch(collection)
        if area is not None:
            domain.mark_open_assessments_stale(area["id"], "NEW_COLLECTION")
    else:  # VOID
        # VOID is available from LOGGED unconditionally and from a collection
        # already in the chain of custody only while no laboratory pool was
        # ever built from it (PRD §3.3). Because the first pool advances a
        # SUBMITTED collection to POOLED, a POOLED collection always carries
        # laboratory work and is therefore refused with ERR_COLLECTION_HAS_POOLS
        # rather than a bare transition error.
        if collection["status"] not in ("LOGGED", "SUBMITTED", "POOLED"):
            raise domain.invalid_transition("VOID requires a non-terminal collection.")
        was_submitted = collection["status"] in ("SUBMITTED", "POOLED")
        if was_submitted:
            if calc.pools_of_collection(collection["id"]):
                raise ApiError("ERR_COLLECTION_HAS_POOLS", 409,
                               "The collection already has laboratory pools.")
        collection["status"] = "VOIDED"
        collection["void_reason"] = void_reason
        store.touch(collection)
        if was_submitted and area is not None:
            domain.mark_open_assessments_stale(area["id"], "NEW_COLLECTION")

    return ok(views.trap_collection_view(collection))


# --------------------------------------------------------------------------
# Lab pools
# --------------------------------------------------------------------------


@bp.post("/trap-collections/<collection_id>/lab-pools")
def create_lab_pool(collection_id):
    authorize(authenticate(), ("LabAnalyst",))
    collection = store.fetch("TrapCollection", collection_id)
    body = get_body()
    pool_size = req_int(body, "pool_size", minimum=1, maximum=calc.POOL_MAX_MOSQUITOES)
    assay = opt_enum(body, "assay", ASSAYS, default="RT_PCR")

    if collection["status"] not in ("SUBMITTED", "POOLED"):
        raise ApiError("ERR_COLLECTION_NOT_SUBMITTED", 409,
                       "The parent collection is not SUBMITTED or POOLED.")

    record = store.new_record()
    record.update({
        "trap_collection_id": collection["id"],
        "pool_size": pool_size,
        "assay": assay,
        "status": "CREATED",
        "retest_count": 0,
        "ct_value": None,
        "result_recorded_at": None,
    })
    store.LAB_POOLS[record["id"]] = record

    collection["pooled_mosquito_count"] = collection["pooled_mosquito_count"] + pool_size
    if collection["status"] == "SUBMITTED":
        collection["status"] = "POOLED"
    store.touch(collection)

    return created(views.lab_pool_view(record))


@bp.get("/lab-pools")
def list_lab_pools():
    authorize(authenticate(), ALL_DISTRICT_READERS)
    limit, offset = pagination()
    collection_id = query_str("trap_collection_id")
    status = query_enum("status", POOL_STATUSES)
    rows = [p for p in store.LAB_POOLS.values()
            if (collection_id is None or p["trap_collection_id"] == collection_id)
            and (status is None or p["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.lab_pool_view(r) for r in page], limit, offset, total)


@bp.get("/lab-pools/<pool_id>")
def get_lab_pool(pool_id):
    authorize(authenticate(), ALL_DISTRICT_READERS)
    pool = store.fetch("LabPool", pool_id)
    return ok(views.lab_pool_view(pool))


@bp.post("/lab-pools/<pool_id>/transitions")
def transition_lab_pool(pool_id):
    actor = authorize(authenticate(), ("LabAnalyst",))
    body = get_body()
    action, known = domain.read_action(body, POOL_ACTORS)
    domain.enforce_actor(action, known, POOL_ACTORS, actor)

    pool = store.fetch("LabPool", pool_id)

    domain.require_action_supplied(action)
    result = None
    ct_value = None
    if known and action == "RESULT":
        result = req_enum(body, "result", RESULTS)
        ct_value = opt_decimal(body, "ct_value", default=None)
    domain.require_known_action(action, known)

    collection = store.TRAP_COLLECTIONS.get(pool["trap_collection_id"])
    area = domain.area_of_pool(pool)

    if action == "START_TEST":
        if pool["status"] not in ("CREATED", "INVALID"):
            raise domain.invalid_transition("START_TEST requires a CREATED or INVALID pool.")
        if collection is not None and collection["status"] not in ("SUBMITTED", "POOLED"):
            raise ApiError("ERR_COLLECTION_NOT_SUBMITTED", 409,
                           "The parent collection is not SUBMITTED or POOLED.")
        if pool["status"] == "INVALID":
            if pool["retest_count"] >= calc.MAX_POOL_RETESTS:
                raise ApiError("ERR_RETEST_LIMIT_EXCEEDED", 409,
                               "The pool has exhausted its retests.")
            pool["retest_count"] = pool["retest_count"] + 1
        pool["status"] = "IN_TESTING"
        store.touch(pool)

    elif action == "RESULT":
        if pool["status"] != "IN_TESTING":
            raise domain.invalid_transition("RESULT requires an IN_TESTING pool.")
        pool["result_recorded_at"] = logical_now()
        if result == "POSITIVE":
            pool["status"] = "RESULT_POSITIVE"
            if ct_value is not None:
                pool["ct_value"] = ct_value
            store.touch(pool)
            _positive_cascade(pool, collection, area)
        elif result == "NEGATIVE":
            pool["status"] = "RESULT_NEGATIVE"
            store.touch(pool)
            if area is not None:
                domain.mark_open_assessments_stale(area["id"], "LAB_RESULT")
        else:
            pool["status"] = "INVALID"
            store.touch(pool)
            if area is not None:
                domain.mark_open_assessments_stale(area["id"], "LAB_RESULT")

    else:  # DISCARD
        if pool["status"] != "INVALID":
            raise domain.invalid_transition("DISCARD requires an INVALID pool.")
        pool["status"] = "DISCARDED"
        store.touch(pool)
        if collection is not None:
            collection["pooled_mosquito_count"] = (
                collection["pooled_mosquito_count"] - pool["pool_size"])
            store.touch(collection)
        if area is not None:
            domain.mark_open_assessments_stale(area["id"], "LAB_RESULT")

    return ok(views.lab_pool_view(pool))


def _positive_cascade(pool, collection, area):
    """The five-hop positive-detection cascade of PRD §3.4."""
    now = logical_now()
    # Hop 1 — parent collection
    if collection is not None:
        collection["positive_pool_count"] = collection["positive_pool_count"] + 1
        collection["wnv_detected"] = collection["positive_pool_count"] >= 1
        store.touch(collection)
        # Hop 2 — trap site
        site = store.TRAP_SITES.get(collection["trap_site_id"])
        if site is not None:
            site["season_positive_count"] = site["season_positive_count"] + 1
            site["last_positive_at"] = now
            store.touch(site)
    # Hop 3 — open assessments of the area go stale
    if area is not None:
        domain.mark_open_assessments_stale(area["id"], "LAB_RESULT")
        # Hops 4 & 5 — posture recomputation and complaint escalation
        domain.recompute_posture(area)
