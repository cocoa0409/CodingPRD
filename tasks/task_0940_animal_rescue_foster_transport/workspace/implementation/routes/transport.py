"""Transport: runs, legs, manifests and the relay chain."""

from decimal import Decimal

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import gates
import services
from errors import ApiError
from routing import listing, must, must_fk, query_filters
from store import DB, ordered, touch
from validation import Field, parse_body

bp = Blueprint("transport", __name__)


def _validation(msg):
    return ApiError("ERR_VALIDATION", msg)


def _run_org(run):
    return run.get("origin_organization_id") if run else None


def _partner_org_of_run(run):
    commitment = DB.get("PartnerCommitment", run.get("partner_commitment_id")) if run else None
    return commitment["organization_id"] if commitment else None


# =====================================================================
#  Runs
# =====================================================================

@bp.post("/rescue/transport-runs")
def create_run():
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    body = parse_body(request, [
        Field("origin_organization_id", "string", required=True),
        Field("run_type", "string", required=True, enum="run_type"),
        Field("origin_hub_code", "string", required=True),
        Field("destination_hub_code", "string", required=True),
        Field("purpose", "string", default="INTAKE_TRANSPORT", enum="purpose"),
        Field("partner_commitment_id", "string", default=None),
    ])
    if body["purpose"] == "TRANSFER_OUT" and not body["partner_commitment_id"]:
        raise _validation("partner_commitment_id is required when purpose is TRANSFER_OUT.")
    must("Organization", body["origin_organization_id"])
    must_fk("PartnerCommitment", body["partner_commitment_id"])
    gates.check_gate1(body["origin_organization_id"])
    run = DB.insert("TransportRun", {
        "origin_organization_id": body["origin_organization_id"],
        "partner_commitment_id": body["partner_commitment_id"],
        "run_type": body["run_type"],
        "purpose": body["purpose"],
        "origin_hub_code": body["origin_hub_code"],
        "destination_hub_code": body["destination_hub_code"],
        "status": "PLANNED",
        "slots_drawn": 0,
        "started_at": None,
        "aborted_at": None,
    })
    return envelope.created(derive.transport_run(run))


@bp.get("/rescue/transport-runs/<run_id>")
def read_run(run_id):
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver", "PartnerRescue"])
    run = DB.get("TransportRun", run_id)
    if run is not None:
        # PRD 2.1: a PartnerRescue reads its own commitments "together with the
        # runs drawing on it".
        auth.own_if(ctx, "PartnerRescue", _partner_org_of_run(run))
    return envelope.ok(derive.transport_run(must("TransportRun", run_id)))


@bp.get("/rescue/transport-runs")
def list_runs():
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "PartnerRescue"])
    rows = DB.all("TransportRun")
    if ctx.role == "PartnerRescue":
        rows = [r for r in rows if _partner_org_of_run(r) == ctx.user_id]
    return listing("TransportRun", rows,
                   query_filters(["origin_organization_id", "partner_commitment_id",
                                  "run_type", "purpose", "status"]))


def _distinct_manifested_animals(run):
    """The count of DISTINCT animals across all the run's legs whose manifest
    entries stand at ASSIGNED or LOADED -- an animal on two legs counts once."""
    seen = []
    for leg in ordered(DB.where("TransportLeg", transport_run_id=run["id"])):
        for entry in ordered(DB.where("ManifestEntry", transport_leg_id=leg["id"])):
            if entry["status"] in ("ASSIGNED", "LOADED") and entry["animal_id"] not in seen:
                seen.append(entry["animal_id"])
    return seen


@bp.post("/rescue/transport-runs/<run_id>/start")
def start_run(run_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    parse_body(request, [])
    run = must("TransportRun", run_id)
    gates.check_gate1(_run_org(run))

    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED run may be started.")
    if not DB.where("TransportLeg", transport_run_id=run["id"]):
        raise ApiError("ERR_INVALID_STATE", "At least one leg must exist on the run.")

    if run["purpose"] == "TRANSFER_OUT":
        commitment = DB.get("PartnerCommitment", run.get("partner_commitment_id"))
        animal_ids = _distinct_manifested_animals(run)
        needed = len(animal_ids)
        # Adjudication of friction 7: Reading A -- the GLOBAL LADDER decides.
        # The species check sits at rung 32, the commitment-expiry check at rung
        # 39, so a run whose commitment has expired AND whose animals are of the
        # wrong species reports ERR_PARTNER_SPECIES_MISMATCH.  PRD 2.5 is
        # emphatic that the observable error "must not depend on implementation
        # order" and that "the system therefore evaluates a single global ladder
        # of 45 rungs in a fixed sequence" -- the transition's own precondition
        # list is a local restatement, not a second arbiter.  Neither reading
        # strands anything (each code stays reachable on its own), so ladder
        # primacy settles it.
        if commitment is not None:
            for animal_id in animal_ids:                          # rung 32
                animal = DB.get("Animal", animal_id)
                if animal is not None and animal["species"] != commitment["species"]:
                    raise ApiError("ERR_PARTNER_SPECIES_MISMATCH",
                                   "A manifested animal is not of the commitment's species.")
            expired = (commitment["status"] == "EXPIRED"
                       or clock.now() > clock.parse(commitment["expires_at"]))
            if expired:                                           # rung 39
                raise ApiError("ERR_PARTNER_COMMITMENT_UNAVAILABLE",
                               "The partner commitment has expired.")
            if commitment["slots_open"] < needed:                 # rung 44
                raise ApiError("ERR_PARTNER_COMMITMENT_UNAVAILABLE",
                               "The partner commitment has too few open slots.")
            commitment["slots_drawn"] += needed
            commitment["slots_open"] = (commitment["slots_total"] - commitment["slots_drawn"]
                                        - commitment["slots_released"])
            if commitment["slots_drawn"] >= commitment["slots_total"]:
                commitment["status"] = "EXHAUSTED"
            elif commitment["slots_drawn"] > 0:
                commitment["status"] = "PARTIALLY_DRAWN"
            touch(commitment)
            run["slots_drawn"] = needed

    run["status"] = "IN_PROGRESS"
    run["started_at"] = clock.stamp()                  # (c) clock-derived
    touch(run)
    return envelope.ok(derive.transport_run(run))


@bp.post("/rescue/transport-runs/<run_id>/abort")
def abort_run(run_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    parse_body(request, [Field("reason", "string")])
    run = must("TransportRun", run_id)
    gates.check_gate1(_run_org(run))
    if run["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE", "Only a PLANNED or IN_PROGRESS run may be aborted.")
    services.abort_run(run)
    return envelope.ok(derive.transport_run(run))


# =====================================================================
#  Legs
# =====================================================================

@bp.post("/rescue/transport-runs/<run_id>/transport-legs")
def add_leg(run_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    body = parse_body(request, [
        Field("driver_person_id", "string", required=True),
        Field("sequence_no", "integer", required=True, fmt="gte1"),
        Field("origin_hub_code", "string", required=True),
        Field("destination_hub_code", "string", required=True),
        Field("scheduled_depart_at", "datetime", required=True),
        Field("scheduled_arrive_at", "datetime", required=True),
        Field("crate_capacity_units", "integer", required=True, fmt="gte1"),
        Field("weight_capacity_lb", "number", required=True, fmt="gt0"),
        Field("crosses_state_line", "boolean", default=False),
        Field("destination_state_code", "string", default=None, fmt="state"),
        Field("species_policy", "string", default="ANY", enum="species_policy"),
    ])
    if clock.parse(body["scheduled_arrive_at"]) <= clock.parse(body["scheduled_depart_at"]):
        raise _validation("scheduled_arrive_at must be strictly after scheduled_depart_at.")
    if body["crosses_state_line"] and not body["destination_state_code"]:
        raise _validation("destination_state_code is required when crosses_state_line is true.")

    run = must("TransportRun", run_id)
    driver = must("Person", body["driver_person_id"])
    gates.check_gate1(_run_org(run))

    # Rung 19: legs are added "while it is still PLANNED".
    if run["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE", "A leg may only be added to a PLANNED run.")
    if not driver.get("driver_license_number"):
        raise _validation("The named driver has no driver_license_number recorded.")
    for existing in DB.where("TransportLeg", transport_run_id=run["id"]):
        if existing["sequence_no"] == body["sequence_no"]:
            raise _validation("sequence_no must be unique within the run.")

    # Rung 37: exclusive driver occupancy with the asymmetric turnaround buffer.
    if calc.driver_interval_conflict(driver["id"], body["scheduled_depart_at"],
                                     body["scheduled_arrive_at"]):
        raise ApiError("ERR_DRIVER_LEG_OVERLAP", "The driver is already occupied in that interval.")

    leg = DB.insert("TransportLeg", {
        "transport_run_id": run["id"],
        "driver_person_id": driver["id"],
        "sequence_no": body["sequence_no"],
        "origin_hub_code": body["origin_hub_code"],
        "destination_hub_code": body["destination_hub_code"],
        "scheduled_depart_at": body["scheduled_depart_at"],   # (b) byte-verbatim
        "scheduled_arrive_at": body["scheduled_arrive_at"],   # (b) byte-verbatim
        "crate_capacity_units": body["crate_capacity_units"],
        "weight_capacity_lb": body["weight_capacity_lb"],
        "crosses_state_line": body["crosses_state_line"],
        "destination_state_code": body["destination_state_code"],
        "species_policy": body["species_policy"],
        "used_crate_units": 0,
        "used_weight_lb": 0,
        "status": "SCHEDULED",
        "departed_at": None,
        "arrived_at": None,
    })
    touch(run)
    return envelope.created(derive.transport_leg(leg))


@bp.get("/rescue/transport-legs/<leg_id>")
def read_leg(leg_id):
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver"])
    leg = DB.get("TransportLeg", leg_id)
    if leg is not None:
        auth.own_if(ctx, "Driver", leg["driver_person_id"])
    return envelope.ok(derive.transport_leg(must("TransportLeg", leg_id)))


@bp.get("/rescue/transport-legs")
def list_legs():
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver"])
    rows = DB.all("TransportLeg")
    if ctx.role == "Driver":
        rows = [l for l in rows if l["driver_person_id"] == ctx.user_id]
    return listing("TransportLeg", rows,
                   query_filters(["transport_run_id", "driver_person_id", "status"]))


def _manifested_animals(leg, statuses):
    out = []
    for entry in ordered(DB.where("ManifestEntry", transport_leg_id=leg["id"])):
        if entry["status"] in statuses:
            animal = DB.get("Animal", entry["animal_id"])
            if animal is not None:
                out.append((entry, animal))
    return out


@bp.post("/rescue/transport-legs/<leg_id>/depart")
def depart_leg(leg_id):
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver"])
    leg = DB.get("TransportLeg", leg_id)
    if leg is not None:
        auth.own_if(ctx, "Driver", leg["driver_person_id"])
    parse_body(request, [])
    leg = must("TransportLeg", leg_id)
    run = DB.get("TransportRun", leg["transport_run_id"])
    carried = _manifested_animals(leg, ("ASSIGNED",))

    # Gate 3 is evaluated PER MANIFESTED ANIMAL: one restrained animal blocks
    # the whole departure, and it pre-empts every rung below.
    gates.run_gates(_run_org(run), gate3=True, gate3_animals=[a for _, a in carried])

    if leg["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED leg may depart.")
    if run is None or run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "The parent run must be IN_PROGRESS.")

    if leg["crosses_state_line"]:
        for _entry, animal in carried:                          # rung 27
            if not calc.rabies_eligible(animal):
                raise ApiError("ERR_RABIES_AGE_NOT_MET",
                               "An animal is not rabies-eligible for an interstate departure.")
        for _entry, animal in carried:                          # rung 34
            if calc.governing_certificate(animal["id"], leg["destination_state_code"]) is None:
                raise ApiError("ERR_CVI_REQUIRED",
                               "An animal holds no certificate for the destination state.")
        for _entry, animal in carried:                          # rung 35
            cert = calc.governing_certificate(animal["id"], leg["destination_state_code"])
            derive.expire_certificate(cert)
            # The comparison is against the leg's SCHEDULED departure instant,
            # not against the clock at the moment of the call.
            if clock.parse(leg["scheduled_depart_at"]) > clock.parse(cert["expires_at"]):
                raise ApiError("ERR_CVI_EXPIRED",
                               "The governing certificate has expired for this departure.")

    # Rung 36: relay sequencing -- legs strictly cannot leapfrog one another.
    for other in DB.where("TransportLeg", transport_run_id=leg["transport_run_id"]):
        if other["sequence_no"] < leg["sequence_no"] and other["status"] != "ARRIVED":
            raise ApiError("ERR_LEG_SEQUENCE_VIOLATION",
                           "A lower-sequence leg has not yet arrived.")

    leg["status"] = "DEPARTED"
    leg["departed_at"] = clock.stamp()                 # (c) clock-derived
    touch(leg)
    for entry, animal in carried:
        entry["status"] = "LOADED"
        touch(entry)
        animal["lifecycle_status"] = "IN_TRANSIT"
        animal["current_hub_code"] = None
        touch(animal)
    calc.recompute_leg(leg)
    return envelope.ok(derive.transport_leg(leg))


@bp.post("/rescue/transport-legs/<leg_id>/arrive")
def arrive_leg(leg_id):
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver"])
    leg = DB.get("TransportLeg", leg_id)
    if leg is not None:
        auth.own_if(ctx, "Driver", leg["driver_person_id"])
    parse_body(request, [])
    leg = must("TransportLeg", leg_id)
    run = DB.get("TransportRun", leg["transport_run_id"])
    gates.check_gate1(_run_org(run))

    if leg["status"] != "DEPARTED":
        raise ApiError("ERR_INVALID_STATE", "Only a DEPARTED leg may arrive.")
    if run is None or run["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "The parent run must be IN_PROGRESS.")

    leg["status"] = "ARRIVED"
    leg["arrived_at"] = clock.stamp()                  # (c) clock-derived
    touch(leg)

    siblings = DB.where("TransportLeg", transport_run_id=run["id"])
    highest = max(s["sequence_no"] for s in siblings)
    if leg["sequence_no"] == highest:
        for entry, animal in _manifested_animals(leg, ("LOADED",)):
            entry["status"] = "DELIVERED"
            touch(entry)
            animal["lifecycle_status"] = "IN_CUSTODY"
            # Adjudication of friction 5: Reading A -- on an INTAKE_TRANSPORT
            # run the dispatching organization is the receiving one, so
            # current_organization_id is repointed to the run's
            # origin_organization_id.  Reading B (leave it unchanged) would
            # strand the declared side effect "sets Animal.current_organization_id
            # to the run's destination organization when purpose is
            # INTAKE_TRANSPORT" entirely -- it could never fire, on any input.
            if run["purpose"] == "INTAKE_TRANSPORT":
                animal["current_organization_id"] = run["origin_organization_id"]
            touch(animal)
        calc.recompute_leg(leg)
        if all(s["status"] == "ARRIVED" for s in siblings):
            run["status"] = "COMPLETED"
            touch(run)
    return envelope.ok(derive.transport_leg(leg))


@bp.post("/rescue/transport-legs/<leg_id>/abort")
def abort_leg(leg_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    parse_body(request, [Field("reason", "string")])
    leg = must("TransportLeg", leg_id)
    run = DB.get("TransportRun", leg["transport_run_id"])
    gates.check_gate1(_run_org(run))

    if leg["status"] == "SCHEDULED":
        # Nobody is stranded, because nobody was loaded.
        leg["status"] = "ABORTED"
        touch(leg)
        for entry in ordered(DB.where("ManifestEntry", transport_leg_id=leg["id"], status="ASSIGNED")):
            entry["status"] = "BUMPED"
            touch(entry)
        calc.recompute_leg(leg)
    elif leg["status"] == "DEPARTED":
        services.strand_cascade(leg)
    else:
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED or DEPARTED leg may be aborted.")
    return envelope.ok(derive.transport_leg(leg))


# =====================================================================
#  Manifest entries
# =====================================================================

@bp.post("/rescue/transport-legs/<leg_id>/manifest-entries")
def manifest_animal(leg_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    body = parse_body(request, [
        Field("animal_id", "string", required=True),
        Field("expected_leg_version", "integer", required=True, fmt="gte0"),
    ])
    leg = must("TransportLeg", leg_id)
    animal = must("Animal", body["animal_id"])
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True, gate3=True)

    # Rung 17: the OCC guard pins the remaining crate-and-weight view.
    if body["expected_leg_version"] != leg["version"]:
        raise ApiError("ERR_STALE_VERSION", "The leg has been modified since it was read.")
    if leg["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Animals may only be manifested onto a SCHEDULED leg.")

    if not calc.leg_species_compatible(leg, animal):                     # rung 26
        raise ApiError("ERR_SPECIES_INCOMPATIBLE_LEG",
                       "The leg's species and temperament policy rejects this animal.")

    litter = DB.get("Litter", animal["litter_id"]) if animal.get("litter_id") else None
    if litter is not None and litter["transport_basis"] == "GROUPED":     # rung 31
        for entry in DB.all("ManifestEntry"):
            if entry["status"] not in ("ASSIGNED", "LOADED"):
                continue
            if entry["transport_leg_id"] == leg["id"]:
                continue
            other = DB.get("Animal", entry["animal_id"])
            if other is not None and other.get("litter_id") == litter["id"]:
                raise ApiError("ERR_LITTER_SPLIT_NOT_APPROVED",
                               "A littermate already sits on a different leg.")

    crate_units, is_anchor = calc.litter_transport_units(animal, leg["id"])
    if leg["used_crate_units"] + crate_units > leg["crate_capacity_units"]:   # rung 40
        raise ApiError("ERR_LEG_CRATE_CAPACITY_EXCEEDED", "The leg's crate capacity is exhausted.")
    new_weight = Decimal(str(leg["used_weight_lb"])) + Decimal(str(animal["weight_lb"]))
    if calc.round_dp(new_weight, 2) > Decimal(str(leg["weight_capacity_lb"])):  # rung 41
        raise ApiError("ERR_LEG_WEIGHT_CAPACITY_EXCEEDED", "The leg's weight capacity is exhausted.")

    # Adjudication of friction 6: Reading B -- re-manifesting a stranded animal
    # LEAVES the original entry at STRANDED, with its stranded_at_hub_code
    # intact for audit, and creates a fresh entry in ASSIGNED on the replacement
    # leg.  Reading A (mutate the existing row and re-point it) contradicts two
    # declared behaviours: this endpoint answers 201 because "manifesting
    # returns the NEW manifest entry" (PRD 4), and the `status` filter on the
    # manifest-entry list could never surface the STRANDED audit row again.
    entry = DB.insert("ManifestEntry", {
        "transport_leg_id": leg["id"],
        "animal_id": animal["id"],
        "crate_units": crate_units,
        "is_litter_anchor": is_anchor,
        "status": "ASSIGNED",
        "stranded_at_hub_code": None,
    })
    calc.recompute_leg(leg)
    touch(leg)
    return envelope.created(derive.manifest_entry(entry))


def _leg_driver_of_entry(entry):
    leg = DB.get("TransportLeg", entry["transport_leg_id"])
    return leg["driver_person_id"] if leg else None


@bp.get("/rescue/manifest-entries/<entry_id>")
def read_manifest_entry(entry_id):
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver"])
    entry = DB.get("ManifestEntry", entry_id)
    if entry is not None:
        auth.own_if(ctx, "Driver", _leg_driver_of_entry(entry))
    return envelope.ok(derive.manifest_entry(must("ManifestEntry", entry_id)))


@bp.get("/rescue/manifest-entries")
def list_manifest_entries():
    ctx = auth.authenticate(["PlatformAdmin", "TransportDispatcher", "Driver"])
    rows = DB.all("ManifestEntry")
    if ctx.role == "Driver":
        rows = [e for e in rows if _leg_driver_of_entry(e) == ctx.user_id]
    return listing("ManifestEntry", rows,
                   query_filters(["transport_leg_id", "animal_id", "status"]))


@bp.delete("/rescue/manifest-entries/<entry_id>")
def bump_manifest_entry(entry_id):
    auth.authenticate(["PlatformAdmin", "TransportDispatcher"])
    entry = must("ManifestEntry", entry_id)
    leg = DB.get("TransportLeg", entry["transport_leg_id"])
    animal = DB.get("Animal", entry["animal_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))
    if entry["status"] != "ASSIGNED":
        raise ApiError("ERR_INVALID_STATE", "Only an ASSIGNED entry may be bumped.")
    entry["status"] = "BUMPED"
    touch(entry)
    if leg is not None:
        calc.recompute_leg(leg)
        touch(leg)
    # PRD 4: the bump answers 200 with the bumped manifest entry, not an empty body.
    return envelope.ok(derive.manifest_entry(entry))
