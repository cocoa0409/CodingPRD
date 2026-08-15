"""Cages, animals, litters, and census routes (PRD §3.4-3.6)."""
import uuid
from datetime import timedelta

from flask import Blueprint

from db import STORE, new_rec, now
from domain import (
    animal_counts_toward_capacity,
    animals_used_count,
    close_placement,
    effective_occupancy,
    open_placement,
    productivity,
    ser_animal,
    ser_cage,
    ser_census_record,
    ser_litter,
    recompute_cage,
)
from envelope import get_body, list_response, ok_obj
from errors import (
    ApiError,
    ERR_ANIMAL_CAP_EXCEEDED,
    ERR_CAGE_MISMATCH,
    ERR_CAGE_OVER_CAPACITY,
    ERR_DUPLICATE,
    ERR_LITTER_TOO_YOUNG,
    ERR_PROTOCOL_NOT_APPROVED,
    invalid_request,
    invalid_state,
    not_found,
)
from routes_admin import fetch
from validation import (
    authenticate,
    opt_dt,
    opt_str,
    require_role,
    req_dt,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("vivarium", __name__)

SPECIES = {"MOUSE", "RAT", "RABBIT", "ZEBRAFISH"}
CAGE_KINDS = {"STANDARD", "BREEDING"}
SEXES = {"M", "F"}


# ---------------------------------------------------------------------------
# Cages
# ---------------------------------------------------------------------------

@bp.post("/iacuc/cages")
def create_cage():
    uid, role = authenticate()
    require_role(role, "FacilityManager")
    body = get_body()
    cage_barcode = req_str(body, "cage_barcode")
    room_code = req_str(body, "room_code")
    species = req_enum(body, "species", SPECIES)
    cage_kind = req_enum(body, "cage_kind", CAGE_KINDS)
    capacity_adults = req_int(body, "capacity_adults", minimum=1)
    protocol_id = req_str(body, "protocol_id")
    fetch("protocols", protocol_id)
    if any(c.cage_barcode == cage_barcode for c in STORE["cages"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "cage_barcode already registered")
    r = new_rec(
        "cages",
        cage_barcode=cage_barcode,
        room_code=room_code,
        species=species,
        cage_kind=cage_kind,
        capacity_adults=capacity_adults,
        status="EMPTY",
        protocol_id=protocol_id,
        occupied_since=None,
    )
    return ok_obj(ser_cage(r), 201)


@bp.get("/iacuc/cages/<rid>")
def get_cage(rid):
    uid, role = authenticate()
    require_role(
        role, "FacilityManager", "AnimalCareStaff", "BillingCoordinator",
        "IacucAdministrator",
    )
    return ok_obj(ser_cage(fetch("cages", rid)))


@bp.post("/iacuc/cages/<rid>/decommission")
def decommission_cage(rid):
    uid, role = authenticate()
    require_role(role, "FacilityManager")
    c = fetch("cages", rid)
    if c.status != "EMPTY":
        raise invalid_state("Only an EMPTY cage may be decommissioned")
    c.status = "DECOMMISSIONED"
    c.touch()
    return ok_obj(ser_cage(c))


@bp.get("/iacuc/cages/<rid>/productivity")
def cage_productivity(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "FacilityManager")
    c = fetch("cages", rid)
    return ok_obj(productivity(c))


# ---------------------------------------------------------------------------
# Animals
# ---------------------------------------------------------------------------

def _check_cage_consistency(cage, species, protocol_id):
    if (
        cage.species != species
        or cage.protocol_id != protocol_id
        or cage.status == "DECOMMISSIONED"
    ):
        raise ApiError(
            ERR_CAGE_MISMATCH, 422,
            "Species/protocol mismatch between animal and cage, or cage "
            "decommissioned",
        )


def _check_capacity(cage, extra_slots):
    """Prospective effective occupancy after adding extra_slots animals."""
    proto = STORE["protocols"].get(cage.protocol_id)
    if proto is not None and proto.status == "SUSPENDED":
        raise ApiError(
            ERR_CAGE_OVER_CAPACITY, 422,
            "Cage is frozen: its protocol is SUSPENDED",
        )
    if effective_occupancy(cage.id) + extra_slots > cage.capacity_adults:
        raise ApiError(
            ERR_CAGE_OVER_CAPACITY, 422,
            "Placement would exceed cage capacity_adults",
        )


@bp.post("/iacuc/animals")
def create_animal():
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    body = get_body()
    animal_tag = req_str(body, "animal_tag")
    cage_id = req_str(body, "cage_id")
    protocol_id = req_str(body, "protocol_id")
    species = req_enum(body, "species", SPECIES)
    date_of_birth = req_dt(body, "date_of_birth")
    sex = req_enum(body, "sex", SEXES)
    litter_id = opt_str(body, "litter_id")

    cage = fetch("cages", cage_id)
    protocol = fetch("protocols", protocol_id)
    if litter_id is not None:
        fetch("litters", litter_id)

    # Priority 10: protocol animal ceiling (inclusive boundary).
    if animals_used_count(protocol) >= protocol.max_animals_justified:
        raise ApiError(
            ERR_ANIMAL_CAP_EXCEEDED, 422,
            "Protocol has reached its justified animal ceiling",
        )
    # Priority 11: protocol-approved gate.
    if protocol.status != "APPROVED":
        raise ApiError(
            ERR_PROTOCOL_NOT_APPROVED, 409,
            "Protocol must be APPROVED to add animals",
        )
    # Priority 13: species/protocol consistency.
    _check_cage_consistency(cage, species, protocol_id)
    # Priority 14: capacity (pups <= 21 days exempt).
    tmp = type("A", (), {"litter_id": litter_id, "date_of_birth": date_of_birth})
    extra = 1 if animal_counts_toward_capacity(tmp) else 0
    _check_capacity(cage, extra)
    # Priority 24: uniqueness.
    if any(a.animal_tag == animal_tag for a in STORE["animals"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "animal_tag already registered")

    r = new_rec(
        "animals",
        animal_tag=animal_tag,
        cage_id=cage_id,
        protocol_id=protocol_id,
        species=species,
        date_of_birth=date_of_birth,
        sex=sex,
        status="ALIVE",
        litter_id=litter_id,
        status_changed_at=None,
        placements=[],
    )
    open_placement(r, cage_id)
    recompute_cage(cage)
    return ok_obj(ser_animal(r), 201)


@bp.get("/iacuc/animals/<rid>")
def get_animal(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian", "IacucAdministrator")
    return ok_obj(ser_animal(fetch("animals", rid)))


@bp.get("/iacuc/cages/<rid>/animals")
def list_cage_animals(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian", "IacucAdministrator")
    fetch("cages", rid)
    rows = [a for a in STORE["animals"].values() if a.cage_id == rid]
    return list_response(rows, ser_animal)


@bp.get("/iacuc/protocols/<rid>/animals")
def list_protocol_animals(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "IacucAdministrator", "Investigator")
    fetch("protocols", rid)
    rows = [a for a in STORE["animals"].values() if a.protocol_id == rid]
    return list_response(rows, ser_animal)


@bp.post("/iacuc/animals/<rid>/transfer")
def transfer_animal(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    body = get_body()
    target_cage_id = req_str(body, "target_cage_id")
    a = fetch("animals", rid)
    target = fetch("cages", target_cage_id)
    if a.status != "ALIVE":
        raise invalid_state("Only an ALIVE animal may be transferred")
    _check_cage_consistency(target, a.species, a.protocol_id)
    extra = 1 if animal_counts_toward_capacity(a) else 0
    if target.id != a.cage_id:
        _check_capacity(target, extra)
    source = STORE["cages"].get(a.cage_id)
    close_placement(a)
    a.cage_id = target.id
    open_placement(a, target.id)
    a.touch()
    if source is not None:
        recompute_cage(source)
    if target.id != (source.id if source else None):
        recompute_cage(target)
    return ok_obj(ser_animal(a))


@bp.post("/iacuc/animals/<rid>/retire")
def retire_animal(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    a = fetch("animals", rid)
    if a.status != "ALIVE":
        raise invalid_state("Only an ALIVE animal may be retired")
    a.status = "RETIRED"
    a.status_changed_at = now()
    a.touch()
    cage = STORE["cages"].get(a.cage_id)
    if cage is not None:
        recompute_cage(cage)
    return ok_obj(ser_animal(a))


@bp.post("/iacuc/animals/<rid>/transfer-out")
def transfer_out_animal(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    a = fetch("animals", rid)
    if a.status != "ALIVE":
        raise invalid_state("Only an ALIVE animal may be transferred out")
    a.status = "TRANSFERRED_OUT"
    a.status_changed_at = now()
    close_placement(a)
    a.touch()
    cage = STORE["cages"].get(a.cage_id)
    if cage is not None:
        recompute_cage(cage)
    return ok_obj(ser_animal(a))


@bp.post("/iacuc/animals/<rid>/euthanize")
def euthanize_animal(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian")
    a = fetch("animals", rid)
    if a.status not in ("ALIVE", "RETIRED"):
        raise invalid_state("Only an ALIVE or RETIRED animal may be euthanized")
    if a.status == "ALIVE":
        a.status_changed_at = now()
    a.status = "EUTHANIZED"
    a.touch()
    cage = STORE["cages"].get(a.cage_id)
    if cage is not None:
        recompute_cage(cage)
    return ok_obj(ser_animal(a))


# ---------------------------------------------------------------------------
# Litters
# ---------------------------------------------------------------------------

@bp.post("/iacuc/litters")
def create_litter():
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    body = get_body()
    cage_id = req_str(body, "cage_id")
    protocol_id = req_str(body, "protocol_id")
    born_on = req_dt(body, "born_on")
    pup_count = req_int(body, "pup_count", minimum=1)
    cage = fetch("cages", cage_id)
    fetch("protocols", protocol_id)
    litter = new_rec(
        "litters",
        cage_id=cage_id,
        protocol_id=protocol_id,
        born_on=born_on,
        pup_count=pup_count,
        weaned_count=0,
        state="NURSING",
        closed_at=None,
    )
    for i in range(pup_count):
        pup = new_rec(
            "animals",
            animal_tag=f"PUP-{uuid.uuid4().hex[:12]}",
            cage_id=cage_id,
            protocol_id=protocol_id,
            species=cage.species,
            date_of_birth=born_on,
            sex="M" if i % 2 == 0 else "F",
            status="ALIVE",
            litter_id=litter.id,
            status_changed_at=None,
            placements=[],
        )
        open_placement(pup, cage_id)
    recompute_cage(cage)
    return ok_obj(ser_litter(litter), 201)


@bp.get("/iacuc/cages/<rid>/litters")
def list_cage_litters(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "FacilityManager")
    fetch("cages", rid)
    rows = [l for l in STORE["litters"].values() if l.cage_id == rid]
    return list_response(rows, ser_litter)


@bp.get("/iacuc/litters/<rid>")
def get_litter(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "FacilityManager")
    return ok_obj(ser_litter(fetch("litters", rid)))


@bp.get("/iacuc/litters/<rid>/animals")
def list_litter_animals(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    fetch("litters", rid)
    rows = [a for a in STORE["animals"].values() if a.litter_id == rid]
    return list_response(rows, ser_animal)


@bp.get("/iacuc/protocols/<rid>/litters")
def list_protocol_litters(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "IacucAdministrator")
    fetch("protocols", rid)
    rows = [l for l in STORE["litters"].values() if l.protocol_id == rid]
    return list_response(rows, ser_litter)


@bp.post("/iacuc/litters/<rid>/wean")
def wean_litter(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    body = get_body()
    target_ids = body.get("target_cage_ids")
    if not isinstance(target_ids, list) or not target_ids:
        raise invalid_request("'target_cage_ids' must be a non-empty list")
    for t in target_ids:
        if not isinstance(t, str):
            raise invalid_request("'target_cage_ids' must be a list of strings")
    litter = fetch("litters", rid)
    targets = []
    for t in target_ids:
        targets.append(fetch("cages", t))
    if litter.state != "NURSING":
        raise invalid_state("Litter is not NURSING")
    # Priority 14 (capacity) precedes priority 18 (weaning age) per §2.8.
    pups = [
        a for a in STORE["animals"].values()
        if a.litter_id == litter.id and a.status == "ALIVE"
    ]
    assignment = {t.id: [] for t in targets}
    for i, pup in enumerate(pups):
        assignment[targets[i % len(targets)].id].append(pup)
    for t in targets:
        extra = sum(1 for p in assignment[t.id] if animal_counts_toward_capacity(p))
        _check_capacity(t, extra)
    if now() < litter.born_on + timedelta(days=21):
        raise ApiError(
            ERR_LITTER_TOO_YOUNG, 422,
            "Litter may not be weaned before born_on + 21 days",
        )
    source = STORE["cages"].get(litter.cage_id)
    for t in targets:
        for pup in assignment[t.id]:
            close_placement(pup)
            pup.cage_id = t.id
            open_placement(pup, t.id)
            pup.touch()
    litter.weaned_count = litter.pup_count
    litter.state = "WEANED"
    litter.touch()
    if source is not None:
        recompute_cage(source)
    for t in targets:
        if source is None or t.id != source.id:
            recompute_cage(t)
    return ok_obj(ser_litter(litter))


@bp.post("/iacuc/litters/<rid>/close")
def close_litter(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    litter = fetch("litters", rid)
    if litter.state != "WEANED":
        raise invalid_state("Only a WEANED litter may be closed")
    litter.state = "CLOSED"
    litter.closed_at = now()
    litter.touch()
    return ok_obj(ser_litter(litter))


# ---------------------------------------------------------------------------
# Census
# ---------------------------------------------------------------------------

@bp.post("/iacuc/census-records")
def create_census_record():
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff")
    body = get_body()
    cage_id = req_str(body, "cage_id")
    census_date = req_dt(body, "census_date")
    physical_count = req_int(body, "physical_count", minimum=0)
    cage = fetch("cages", cage_id)
    if cage.status == "DECOMMISSIONED":
        raise invalid_state("Cage is DECOMMISSIONED and excluded from census")
    system_count = sum(
        1
        for a in STORE["animals"].values()
        if a.cage_id == cage_id and a.status == "ALIVE"
    )
    r = new_rec(
        "census_records",
        cage_id=cage_id,
        census_date=census_date,
        physical_count=physical_count,
        system_count=system_count,
        discrepancy=physical_count - system_count,
    )
    return ok_obj(ser_census_record(r), 201)


@bp.get("/iacuc/cages/<rid>/census-records")
def list_cage_census_records(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "BillingCoordinator")
    fetch("cages", rid)
    rows = [c for c in STORE["census_records"].values() if c.cage_id == rid]
    return list_response(rows, ser_census_record)
