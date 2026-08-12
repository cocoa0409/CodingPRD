"""The foster pipeline: homes, applications, home checks and placements."""

from flask import Blueprint, request

import auth
import calc
import clock
import derive
import envelope
import gates
import services
from errors import ApiError
from routing import listing, must, must_fk, query_filters, latch_all
from store import DB, ordered, touch
from validation import Field, parse_body

bp = Blueprint("foster", __name__)


def _validation(msg):
    return ApiError("ERR_VALIDATION", msg)


# =====================================================================
#  Foster homes
# =====================================================================

@bp.post("/rescue/foster-homes")
def create_foster_home():
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    body = parse_body(request, [
        Field("person_id", "string", required=True),
        Field("label", "string", required=True),
        Field("max_headcount", "integer", required=True, fmt="gte1"),
        Field("dog_slot_capacity", "integer", default=0, fmt="gte0"),
        Field("cat_slot_capacity", "integer", default=0, fmt="gte0"),
        Field("accepts_cats", "boolean", default=True),
        Field("min_child_age_years", "integer", default=99, fmt="gte0"),
        Field("has_fenced_yard", "boolean", default=False),
    ])
    must("Person", body["person_id"])
    # Gate 1: a FosterHome carries no organization-bearing field, so it is ungated.
    home = DB.insert("FosterHome", {
        "person_id": body["person_id"],
        "label": body["label"],
        "dog_slot_capacity": body["dog_slot_capacity"],
        "cat_slot_capacity": body["cat_slot_capacity"],
        "max_headcount": body["max_headcount"],
        "accepts_cats": body["accepts_cats"],
        "min_child_age_years": body["min_child_age_years"],
        "has_fenced_yard": body["has_fenced_yard"],
        "consumed_dog_slots": 0,
        "consumed_cat_slots": 0,
        "consumed_headcount": 0,
        "capacity_status": "OPEN",
    })
    return envelope.created(derive.foster_home(home))


@bp.get("/rescue/foster-homes/<home_id>")
def read_foster_home(home_id):
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator", "FosterParent"])
    home = DB.get("FosterHome", home_id)
    if home is not None:
        auth.own_if(ctx, "FosterParent", home["person_id"])
    return envelope.ok(derive.foster_home(must("FosterHome", home_id)))


@bp.get("/rescue/foster-homes")
def list_foster_homes():
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    return listing("FosterHome", DB.all("FosterHome"),
                   query_filters(["person_id", "capacity_status"]))


# =====================================================================
#  Foster applications -- two entirely independent axes
# =====================================================================

@bp.post("/rescue/foster-applications")
def create_foster_application():
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator", "FosterParent"])
    body = parse_body(request, [
        Field("person_id", "string", required=True),
        Field("foster_home_id", "string", required=True),
        Field("species_requested", "string", required=True, enum="species"),
    ])
    auth.own_if(ctx, "FosterParent", body["person_id"])
    must("Person", body["person_id"])
    must("FosterHome", body["foster_home_id"])
    app = DB.insert("FosterApplication", {
        "person_id": body["person_id"],
        "foster_home_id": body["foster_home_id"],
        "species_requested": body["species_requested"],
        "application_status": "SUBMITTED",
        "home_check_status": "NOT_SCHEDULED",
        "home_check_passed_at": None,
        "home_check_expires_at": None,
        "decided_by_user_id": None,
    })
    return envelope.created(derive.foster_application(app))


@bp.get("/rescue/foster-applications/<app_id>")
def read_foster_application(app_id):
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator", "FosterParent"])
    app = DB.get("FosterApplication", app_id)
    if app is not None:
        auth.own_if(ctx, "FosterParent", app["person_id"])
    return envelope.ok(derive.foster_application(must("FosterApplication", app_id)))


@bp.get("/rescue/foster-applications")
def list_foster_applications():
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    rows = latch_all("FosterApplication")
    return listing("FosterApplication", rows,
                   query_filters(["person_id", "foster_home_id", "application_status",
                                  "home_check_status"]))


@bp.post("/rescue/foster-applications/<app_id>/decision")
def decide_foster_application(app_id):
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    body = parse_body(request, [Field("decision", "string", required=True, enum="decision")])
    app = must("FosterApplication", app_id)
    if app["application_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED application may be decided.")
    app["application_status"] = "APPROVED" if body["decision"] == "APPROVE" else "DECLINED"
    app["decided_by_user_id"] = ctx.user_id
    touch(app)
    return envelope.ok(derive.foster_application(app))


@bp.post("/rescue/foster-applications/<app_id>/home-check")
def record_home_check(app_id):
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    body = parse_body(request, [
        Field("result", "string", required=True, enum="result"),
        Field("checked_at", "datetime", required=True),
    ])
    app = must("FosterApplication", app_id)
    derive.lapse_home_check(app)
    current = app["home_check_status"]
    if body["result"] == "PASS":
        # Accepted from NOT_SCHEDULED, FAILED and LAPSED -- not from PASSED.
        if current not in ("NOT_SCHEDULED", "FAILED", "LAPSED"):
            raise ApiError("ERR_INVALID_STATE", "No PASS transition is declared out of PASSED.")
        checked_raw = body["checked_at"]
        app["home_check_status"] = "PASSED"
        app["home_check_passed_at"] = checked_raw          # (b) byte-verbatim
        # (c) derived instant, rendered in the style of checked_at
        app["home_check_expires_at"] = clock.derive(
            clock.plus_days(clock.parse(checked_raw), calc.HOME_CHECK_VALID_DAYS), checked_raw)
    else:
        # Accepted from NOT_SCHEDULED, PASSED and LAPSED -- not from FAILED.
        if current not in ("NOT_SCHEDULED", "PASSED", "LAPSED"):
            raise ApiError("ERR_INVALID_STATE", "No FAIL transition is declared out of FAILED.")
        app["home_check_status"] = "FAILED"
        app["home_check_passed_at"] = None
        app["home_check_expires_at"] = None
    touch(app)
    return envelope.ok(derive.foster_application(app))


@bp.post("/rescue/foster-applications/<app_id>/status-change")
def change_foster_application_status(app_id):
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator", "FosterParent"])
    body = parse_body(request, [Field("action", "string", required=True, enum="action")])
    app = DB.get("FosterApplication", app_id)
    if app is not None:
        auth.own_if(ctx, "FosterParent", app["person_id"])
    app = must("FosterApplication", app_id)
    action = body["action"]
    current = app["application_status"]
    if action == "SUSPEND":
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Only an APPROVED application may be suspended.")
        app["application_status"] = "SUSPENDED"
    elif action == "RESUME":
        if current != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "Only a SUSPENDED application may be resumed.")
        app["application_status"] = "APPROVED"
    else:  # WITHDRAW -- reserved to the applicant themself (PRD 3.4)
        if ctx.role not in ("FosterParent", "PlatformAdmin"):
            raise ApiError("ERR_UNAUTHORIZED", "Withdrawal is reserved to the applicant.")
        if current != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Only an APPROVED application may be withdrawn.")
        app["application_status"] = "WITHDRAWN"
    touch(app)
    return envelope.ok(derive.foster_application(app))


# =====================================================================
#  Placements
# =====================================================================

def _check_application_state(app, animal):
    """Rung 20 -- guards proposing, activating AND transferring."""
    derive.lapse_home_check(app)
    if app["application_status"] != "APPROVED" or app["species_requested"] != animal["species"]:
        raise ApiError("ERR_INVALID_STATE",
                       "The linked foster application must be APPROVED for this species.")


def _check_foster_restriction(animal, home):
    """Rung 25 -- guards proposing and transferring ONLY.  Activation does not
    re-run it, because the receiving home was already vetted at proposal.
    Criteria are tested in a pinned order with the first failure reported."""
    if animal["species"] == "CAT" and not home["accepts_cats"]:
        raise ApiError("ERR_FOSTER_RESTRICTION_VIOLATION", "The home does not accept cats.")
    if home["min_child_age_years"] < animal["restriction_no_children_under_years"]:
        raise ApiError("ERR_FOSTER_RESTRICTION_VIOLATION",
                       "The home's youngest child is below the animal's restriction age.")
    if animal["restriction_requires_fenced_yard"] and not home["has_fenced_yard"]:
        raise ApiError("ERR_FOSTER_RESTRICTION_VIOLATION", "The home has no fenced yard.")


def _check_home_check_current(app):
    """Rung 29 -- guards all three operations, which matters because a check can
    lapse between proposal and activation."""
    derive.lapse_home_check(app)
    if app["home_check_status"] != "PASSED":
        raise ApiError("ERR_HOME_CHECK_NOT_CURRENT", "The home check is not current.")
    if app["home_check_expires_at"] and clock.now() > clock.parse(app["home_check_expires_at"]):
        raise ApiError("ERR_HOME_CHECK_NOT_CURRENT", "The home check is not current.")


def _check_capacity(home, animal, slot_consumption, headcount_consumption):
    """Rungs 42 and 43 -- species slots first, head count second, both inclusive."""
    bucket = calc.species_bucket(animal["species"])
    consumed = home["consumed_dog_slots"] if bucket == "dog" else home["consumed_cat_slots"]
    capacity = home["dog_slot_capacity"] if bucket == "dog" else home["cat_slot_capacity"]
    if consumed + slot_consumption > capacity:
        raise ApiError("ERR_FOSTER_CAPACITY_EXCEEDED", "The species slot capacity is exhausted.")
    if home["consumed_headcount"] + headcount_consumption > home["max_headcount"]:
        raise ApiError("ERR_FOSTER_HEADCOUNT_EXCEEDED", "The head count is exhausted.")


@bp.post("/rescue/foster-placements")
def propose_placement():
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    body = parse_body(request, [
        Field("animal_id", "string", required=True),
        Field("foster_home_id", "string", required=True),
        Field("foster_application_id", "string", required=True),
        Field("expected_foster_home_version", "integer", required=True, fmt="gte0"),
        Field("count_basis", "string", default="INDIVIDUAL", enum="count_basis"),
        Field("litter_id", "string", default=None),
    ])
    if body["count_basis"] == "NURSING_UNIT" and not body["litter_id"]:
        raise _validation("litter_id is required when count_basis is NURSING_UNIT.")
    animal = must("Animal", body["animal_id"])
    home = must("FosterHome", body["foster_home_id"])
    app = must("FosterApplication", body["foster_application_id"])
    must_fk("Litter", body["litter_id"])

    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate2=True)

    # Rung 17: the OCC guard pins the free-slot view the request was computed on.
    if body["expected_foster_home_version"] != home["version"]:
        raise ApiError("ERR_STALE_VERSION", "The foster home has been modified since it was read.")

    _check_application_state(app, animal)
    _check_foster_restriction(animal, home)
    _check_home_check_current(app)
    slot = calc.foster_slot_consumption(body["count_basis"])
    heads = calc.foster_headcount_consumption(body["count_basis"], body["litter_id"])
    _check_capacity(home, animal, slot, heads)

    placement = DB.insert("FosterPlacement", {
        "animal_id": animal["id"],
        "foster_home_id": home["id"],
        "foster_application_id": app["id"],
        "litter_id": body["litter_id"],
        "predecessor_placement_id": None,
        "count_basis": body["count_basis"],
        "slot_consumption": slot,
        "headcount_consumption": heads,
        "status": "PROPOSED",
        "started_at": None,
        "ended_at": None,
        "end_reason": None,
    })
    touch(home)      # PRD 3.4: proposing "increments the receiving home's version by one"
    return envelope.created(derive.foster_placement(placement))


@bp.get("/rescue/foster-placements/<placement_id>")
def read_placement(placement_id):
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator", "FosterParent"])
    placement = DB.get("FosterPlacement", placement_id)
    if placement is not None and ctx.role == "FosterParent":
        home = DB.get("FosterHome", placement["foster_home_id"])
        auth.own_if(ctx, "FosterParent", home["person_id"] if home else None)
    return envelope.ok(derive.foster_placement(must("FosterPlacement", placement_id)))


@bp.get("/rescue/foster-placements")
def list_placements():
    ctx = auth.authenticate(["PlatformAdmin", "FosterCoordinator", "FosterParent"])
    rows = DB.all("FosterPlacement")
    if ctx.role == "FosterParent":
        owned = set(h["id"] for h in DB.where("FosterHome", person_id=ctx.user_id))
        rows = [p for p in rows if p["foster_home_id"] in owned]
    return listing("FosterPlacement", rows,
                   query_filters(["animal_id", "foster_home_id", "foster_application_id",
                                  "litter_id", "predecessor_placement_id", "status"]))


@bp.post("/rescue/foster-placements/<placement_id>/activate")
def activate_placement(placement_id):
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    parse_body(request, [])
    placement = must("FosterPlacement", placement_id)
    animal = DB.get("Animal", placement["animal_id"])
    home = DB.get("FosterHome", placement["foster_home_id"])
    app = DB.get("FosterApplication", placement["foster_application_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))

    if placement["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a PROPOSED placement may be activated.")
    _check_application_state(app, animal)
    # Rung 25 is deliberately NOT re-run here.
    _check_home_check_current(app)
    _check_capacity(home, animal, placement["slot_consumption"], placement["headcount_consumption"])

    placement["status"] = "ACTIVE"
    placement["started_at"] = clock.stamp()            # (c) clock-derived
    touch(placement)
    animal["current_foster_home_id"] = home["id"]
    touch(animal)
    calc.recompute_home(home)
    touch(home)
    return envelope.ok(derive.foster_placement(placement))


@bp.post("/rescue/foster-placements/<placement_id>/end")
def end_placement(placement_id):
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    body = parse_body(request, [
        Field("reason", "string", required=True, enum="placement_end_reason"),
    ])
    placement = must("FosterPlacement", placement_id)
    animal = DB.get("Animal", placement["animal_id"])
    home = DB.get("FosterHome", placement["foster_home_id"])
    gates.check_gate1(gates.gate1_org_id(animal=animal))

    reason = body["reason"]
    if reason == "CANCELLED_BEFORE_START":
        if placement["status"] != "PROPOSED":
            raise ApiError("ERR_INVALID_STATE",
                           "CANCELLED_BEFORE_START is declared only out of PROPOSED.")
        placement["status"] = "CANCELLED"
    else:  # RETURNED_TO_SHELTER
        if placement["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE",
                           "RETURNED_TO_SHELTER is declared only out of ACTIVE.")
        placement["status"] = "ENDED"
        if animal is not None:
            animal["current_foster_home_id"] = None
            touch(animal)
    placement["ended_at"] = clock.stamp()              # (c) clock-derived
    placement["end_reason"] = reason
    touch(placement)
    services.recompute_home_and_version(home)
    return envelope.ok(derive.foster_placement(placement))


@bp.post("/rescue/foster-placements/<placement_id>/transfer")
def transfer_placement(placement_id):
    auth.authenticate(["PlatformAdmin", "FosterCoordinator"])
    body = parse_body(request, [
        Field("destination_foster_home_id", "string", required=True),
        Field("destination_foster_application_id", "string", required=True),
    ])
    placement = must("FosterPlacement", placement_id)
    dest_home = must("FosterHome", body["destination_foster_home_id"])
    dest_app = must("FosterApplication", body["destination_foster_application_id"])
    animal = DB.get("Animal", placement["animal_id"])
    source_home = DB.get("FosterHome", placement["foster_home_id"])

    # A foster transfer is the one placement operation an active MEDICAL hold
    # blocks; a LEGAL hold blocks it too, a BEHAVIOURAL hold never does.  It is
    # outside gate 2's scope.
    gates.run_gates(gates.gate1_org_id(animal=animal), animal=animal, gate3=True, gate4=True)

    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE placement may be transferred.")
    _check_application_state(dest_app, animal)
    _check_foster_restriction(animal, dest_home)
    _check_home_check_current(dest_app)
    _check_capacity(dest_home, animal, placement["slot_consumption"],
                    placement["headcount_consumption"])

    placement["status"] = "TRANSFERRED"
    placement["ended_at"] = clock.stamp()              # (c) clock-derived
    placement["end_reason"] = "TRANSFERRED_OUT"
    touch(placement)

    successor = DB.insert("FosterPlacement", {
        "animal_id": placement["animal_id"],
        "foster_home_id": dest_home["id"],
        "foster_application_id": dest_app["id"],
        "litter_id": placement["litter_id"],
        "predecessor_placement_id": placement["id"],
        "count_basis": placement["count_basis"],
        "slot_consumption": placement["slot_consumption"],
        "headcount_consumption": placement["headcount_consumption"],
        "status": "ACTIVE",
        "started_at": clock.stamp(),                   # (c) clock-derived
        "ended_at": None,
        "end_reason": None,
    })
    if animal is not None:
        animal["current_foster_home_id"] = dest_home["id"]
        touch(animal)
    services.recompute_home_and_version(source_home)
    services.recompute_home_and_version(dest_home)
    return envelope.created(derive.foster_placement(successor))
