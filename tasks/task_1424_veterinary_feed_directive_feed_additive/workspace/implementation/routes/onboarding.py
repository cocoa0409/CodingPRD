"""Onboarding routes: clinics, veterinarians, producers, animal groups, drugs, feed mills."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles
from response import success_object, success_list
from services import core

bp = Blueprint("onboarding", __name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _paginate(items):
    """Sorted by created_at ascending; limit/offset per PRD 2.3."""
    items = sorted(items, key=lambda e: (e["created_at"], e["id"]))
    total = len(items)
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        raise errors.invalid_request("limit must be an integer")
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        raise errors.invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise errors.invalid_request("limit must be between 1 and 100")
    if offset < 0:
        raise errors.invalid_request("offset must be >= 0")
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Clinics
# ---------------------------------------------------------------------------

@bp.post("/vfd/clinics")
def create_clinic():
    require_roles("Inspector")
    body = util.get_json_body()
    name = util.require_field(body, "name")
    license_number = util.require_field(body, "license_number")
    state_code = util.require_field(body, "state_code")
    for c in store.clinics.values():
        if c.get("license_number") == license_number:
            raise errors.ApiError(errors.ERR_DUPLICATE_CLINIC_LICENSE,
                                  "VeterinaryClinic.license_number already exists", 409)
    clinic = util.new_entity({
        "name": name,
        "license_number": license_number,
        "state_code": state_code,
        "compliance_score": 1000,
        "audit_ready": True,
    })
    store.clinics[clinic["id"]] = clinic
    return success_object(clinic, 201)


@bp.get("/vfd/clinics/<cid>")
def get_clinic(cid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_clinic(cid))


@bp.get("/vfd/clinics")
def list_clinics():
    require_roles("Inspector", "FeedMillOperator")
    items = list(store.clinics.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [c for c in items if c.get("state_code") == state_code]
    return _paginate(items)


# ---------------------------------------------------------------------------
# Veterinarians
# ---------------------------------------------------------------------------

@bp.post("/vfd/clinics/<cid>/veterinarians")
def create_veterinarian(cid):
    require_roles("Inspector")
    clinic = core.get_clinic(cid)
    body = util.get_json_body()
    full_name = util.require_field(body, "full_name")
    license_number = util.require_field(body, "license_number")
    state_code = util.require_field(body, "state_code")
    vet = util.new_entity({
        "clinic_id": clinic["id"],
        "full_name": full_name,
        "license_number": license_number,
        "state_code": state_code,
        "status": "ACTIVE",
    })
    store.veterinarians[vet["id"]] = vet
    return success_object(vet, 201)


@bp.get("/vfd/veterinarians/<vid>")
def get_veterinarian(vid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_vet(vid))


@bp.get("/vfd/clinics/<cid>/veterinarians")
def list_veterinarians(cid):
    require_roles("Inspector", "FeedMillOperator")
    core.get_clinic(cid)
    items = [v for v in store.veterinarians.values() if v.get("clinic_id") == cid]
    return _paginate(items)


@bp.post("/vfd/veterinarians/<vid>/suspend")
def suspend_veterinarian(vid):
    require_roles("Inspector")
    vet = core.get_vet(vid)
    if vet["status"] != "ACTIVE":
        raise errors.invalid_state("Veterinarian must be ACTIVE to suspend")
    vet["status"] = "SUSPENDED"
    util.touch(vet)
    core.expire_vfds_for_vet(vet["id"])
    return success_object(vet)


@bp.post("/vfd/veterinarians/<vid>/reinstate")
def reinstate_veterinarian(vid):
    require_roles("Inspector")
    vet = core.get_vet(vid)
    if vet["status"] != "SUSPENDED":
        raise errors.invalid_state("Veterinarian must be SUSPENDED to reinstate")
    vet["status"] = "ACTIVE"
    util.touch(vet)
    return success_object(vet)


@bp.post("/vfd/veterinarians/<vid>/revoke")
def revoke_veterinarian(vid):
    require_roles("Inspector")
    vet = core.get_vet(vid)
    if vet["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Veterinarian must be ACTIVE or SUSPENDED to revoke")
    vet["status"] = "REVOKED"
    util.touch(vet)
    core.expire_vfds_for_vet(vet["id"])
    return success_object(vet)


# ---------------------------------------------------------------------------
# Producers
# ---------------------------------------------------------------------------

@bp.post("/vfd/producers")
def create_producer():
    require_roles("Inspector")
    body = util.get_json_body()
    legal_name = util.require_field(body, "legal_name")
    premise_id = util.require_field(body, "premise_id")
    state_code = util.require_field(body, "state_code")
    for p in store.producers.values():
        if p.get("premise_id") == premise_id:
            raise errors.ApiError(errors.ERR_DUPLICATE_PREMISE,
                                  "Producer.premise_id already exists", 409)
    producer = util.new_entity({
        "legal_name": legal_name,
        "premise_id": premise_id,
        "state_code": state_code,
        "status": "ACTIVE",
    })
    store.producers[producer["id"]] = producer
    return success_object(producer, 201)


@bp.get("/vfd/producers/<pid>")
def get_producer(pid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_producer(pid))


@bp.get("/vfd/producers")
def list_producers():
    require_roles("Inspector", "FeedMillOperator")
    items = list(store.producers.values())
    state_code = request.args.get("state_code")
    if state_code is not None:
        items = [p for p in items if p.get("state_code") == state_code]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    return _paginate(items)


# ---------------------------------------------------------------------------
# Animal Groups
# ---------------------------------------------------------------------------

SPECIES = ("CATTLE", "SWINE", "POULTRY", "SHEEP", "GOAT")
PRODUCTION_CLASSES = ("BEEF", "DAIRY", "LAYER", "BROILER", "BREEDING")


@bp.post("/vfd/producers/<pid>/animal-groups")
def create_animal_group(pid):
    require_roles("Producer", "Inspector")
    producer = core.get_producer(pid)
    body = util.get_json_body()
    species = util.require_enum(body, "species", SPECIES)
    production_class = util.require_enum(body, "production_class", PRODUCTION_CLASSES)
    head_count = util.require_int(body, "head_count")
    average_weight_lbs = util.require_int(body, "average_weight_lbs")
    earliest_market_date = util.require_field(body, "earliest_market_date")
    # validate parseable
    util.parse_iso(earliest_market_date, "earliest_market_date")
    group = util.new_entity({
        "producer_id": producer["id"],
        "species": species,
        "production_class": production_class,
        "head_count": head_count,
        "average_weight_lbs": average_weight_lbs,
        "earliest_market_date": earliest_market_date,
    })
    store.animal_groups[group["id"]] = group
    return success_object(group, 201)


@bp.get("/vfd/animal-groups/<gid>")
def get_animal_group(gid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_animal_group(gid))


@bp.get("/vfd/producers/<pid>/animal-groups")
def list_animal_groups(pid):
    require_roles("Inspector", "Veterinarian", "Producer")
    core.get_producer(pid)
    items = [g for g in store.animal_groups.values() if g.get("producer_id") == pid]
    return _paginate(items)


# ---------------------------------------------------------------------------
# VFD Drugs
# ---------------------------------------------------------------------------

@bp.post("/vfd/drugs")
def create_drug():
    require_roles("Inspector")
    body = util.get_json_body()
    drug_code = util.require_field(body, "drug_code")
    label_name = util.require_field(body, "label_name")
    withdrawal_hours = util.require_int(body, "withdrawal_hours")
    allowed_species_classes = util.require_field(body, "allowed_species_classes")
    if not isinstance(allowed_species_classes, list):
        raise errors.invalid_request("allowed_species_classes must be an array")
    max_duration_days = util.require_int(body, "max_duration_days")
    for d in store.drugs.values():
        if d.get("drug_code") == drug_code:
            raise errors.ApiError(errors.ERR_DUPLICATE_DRUG_CODE,
                                  "VfdDrug.drug_code already exists", 409)
    drug = util.new_entity({
        "drug_code": drug_code,
        "label_name": label_name,
        "withdrawal_hours": withdrawal_hours,
        "allowed_species_classes": allowed_species_classes,
        "max_duration_days": max_duration_days,
        "prohibited_extra_label": True,
    })
    store.drugs[drug["id"]] = drug
    return success_object(drug, 201)


@bp.get("/vfd/drugs/<did>")
def get_drug(did):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_drug(did))


@bp.get("/vfd/drugs")
def list_drugs():
    require_roles("Inspector", "FeedMillOperator")
    return _paginate(list(store.drugs.values()))


# ---------------------------------------------------------------------------
# Feed Mills
# ---------------------------------------------------------------------------

@bp.post("/vfd/feed-mills")
def create_feed_mill():
    require_roles("Inspector")
    body = util.get_json_body()
    name = util.require_field(body, "name")
    fda_registration = util.require_field(body, "fda_registration")
    state_code = util.require_field(body, "state_code")
    for m in store.feed_mills.values():
        if m.get("fda_registration") == fda_registration:
            raise errors.ApiError(errors.ERR_DUPLICATE_FDA_REG,
                                  "FeedMill.fda_registration already exists", 409)
    mill = util.new_entity({
        "name": name,
        "fda_registration": fda_registration,
        "state_code": state_code,
        "pending_order_count": 0,
    })
    store.feed_mills[mill["id"]] = mill
    return success_object(mill, 201)


@bp.get("/vfd/feed-mills/<mid>")
def get_feed_mill(mid):
    require_roles("Inspector", "Veterinarian", "FeedMillOperator", "Producer")
    return success_object(core.get_feed_mill(mid))
