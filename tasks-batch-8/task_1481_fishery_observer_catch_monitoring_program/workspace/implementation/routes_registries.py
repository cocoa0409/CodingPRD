"""Registry routes: fisheries, vessel operators, vessels, observers,
debriefers, EM reviewers (PRD 3.1)."""

from flask import Blueprint

import store
from core import (
    ALL_ROLES, ApiError, body, err_forbidden, err_invalid, err_state,
    get_or_404, list_response, ok, opt_dt, opt_enum, opt_int, opt_num,
    opt_str, parse_dt, req_enum, req_num, req_str, require_roles,
)

bp = Blueprint("registries", __name__, url_prefix="/observer-program")

GEAR_TYPES = ("TRAWL", "LONGLINE", "POT", "GILLNET")
CERT_LEVELS = ("TRAINEE", "CERTIFIED", "LEAD")


def check_coverage_target(value):
    from core import dec
    pct = dec(value)
    if pct < dec("0.02") or pct > dec("1.00"):
        raise ApiError("ERR_COVERAGE_TARGET_OUT_OF_RANGE", 422,
                       "coverage_target_pct must be within [0.02, 1.00]")


def check_unique(collection, field, value):
    for e in store.db[collection].values():
        if e.get(field) == value:
            raise ApiError("ERR_UNIQUE_CONSTRAINT", 409,
                           "Duplicate %s: %s" % (field, value))


# ---------------------------------------------------------------------------
# Fishery
# ---------------------------------------------------------------------------


@bp.post("/fisheries")
def create_fishery():
    require_roles("ProgramAdmin")
    b = body()
    code = req_str(b, "code")
    name = req_str(b, "name")
    region = req_str(b, "region")
    target = req_num(b, "coverage_target_pct")
    gear = req_enum(b, "priority_gear", GEAR_TYPES)
    check_coverage_target(target)
    check_unique("fisheries", "code", code)
    f = store.new_entity({
        "code": code, "name": name, "region": region,
        "coverage_target_pct": target, "priority_gear": gear,
        "status": "ACTIVE",
    })
    store.db["fisheries"][f["id"]] = f
    return ok(f, status=201)


@bp.get("/fisheries")
def list_fisheries():
    require_roles(*ALL_ROLES)
    return list_response("fisheries", {"status": "status"})


@bp.get("/fisheries/<fid>")
def get_fishery(fid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("fisheries", fid, "Fishery"))


@bp.patch("/fisheries/<fid>")
def patch_fishery(fid):
    require_roles("ProgramAdmin")
    f = get_or_404("fisheries", fid, "Fishery")
    b = body()
    status = opt_enum(b, "status", ("ACTIVE", "SUSPENDED"))
    name = opt_str(b, "name")
    target = opt_num(b, "coverage_target_pct")
    gear = opt_enum(b, "priority_gear", GEAR_TYPES)
    if target is not None:
        check_coverage_target(target)
    if status is not None and status != f["status"]:
        # Only ACTIVE <-> SUSPENDED transitions exist.
        f["status"] = status
    if name is not None:
        f["name"] = name
    if target is not None:
        f["coverage_target_pct"] = target
    if gear is not None:
        f["priority_gear"] = gear
    store.touch(f)
    return ok(f)


# ---------------------------------------------------------------------------
# VesselOperator
# ---------------------------------------------------------------------------


@bp.post("/vessel-operators")
def create_operator():
    require_roles("ProgramAdmin")
    b = body()
    legal_name = req_str(b, "legal_name")
    license_number = req_str(b, "license_number")
    contact = req_str(b, "contact_person_ref")
    check_unique("operators", "license_number", license_number)
    op = store.new_entity({
        "legal_name": legal_name, "license_number": license_number,
        "contact_person_ref": contact,
        "payment_standing": "GOOD", "status": "ACTIVE",
    })
    store.db["operators"][op["id"]] = op
    return ok(op, status=201)


@bp.get("/vessel-operators")
def list_operators():
    require_roles(*ALL_ROLES)
    return list_response("operators", {"payment_standing": "payment_standing", "status": "status"})


@bp.get("/vessel-operators/<oid>")
def get_operator(oid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("operators", oid, "VesselOperator"))


# ---------------------------------------------------------------------------
# Vessel
# ---------------------------------------------------------------------------


@bp.post("/vessels")
def create_vessel():
    a = require_roles("VesselOperator")
    b = body()
    # Ownership (priority 2): operator_id must equal the caller's own id.
    if "operator_id" in b and b["operator_id"] != a["id"]:
        raise err_forbidden("operator_id must equal the acting operator's id")
    # Body FK existence (priority 3).
    fishery_id = b.get("fishery_id")
    if isinstance(fishery_id, str):
        get_or_404("fisheries", fishery_id, "Fishery")
    # Schema (priority 4).
    operator_id = req_str(b, "operator_id")
    fishery_id = req_str(b, "fishery_id")
    name = req_str(b, "vessel_name")
    permit = req_str(b, "permit_number")
    home_port = req_str(b, "home_port")
    length_ft = req_num(b, "length_ft")
    gear = req_enum(b, "gear_type", GEAR_TYPES)
    revenue = opt_int(b, "declared_annual_revenue_cents")
    prior_loed = opt_dt(b, "prior_last_observed_end_date")
    prior_points = opt_int(b, "prior_harassment_points")
    from core import dec
    if dec(length_ft) <= 0:
        raise err_invalid("length_ft must be > 0")
    if prior_points is None:
        prior_points = 0
    # Referential (priority 9): permit uniqueness.
    check_unique("vessels", "permit_number", permit)
    v = store.new_entity({
        "operator_id": operator_id, "fishery_id": fishery_id,
        "vessel_name": name, "permit_number": permit,
        "home_port": home_port, "length_ft": length_ft, "gear_type": gear,
        "declared_annual_revenue_cents": revenue,
        "monitoring_mode": "HUMAN_OBSERVER",
        "selection_penalty_points": prior_points,
        "substantiated_harassment_count": 0,
        "last_observed_end_date": prior_loed,
        "sea_days_observed_ytd": 0,
        "status": "REGISTERED",
    })
    store.db["vessels"][v["id"]] = v
    return ok(v, status=201)


@bp.get("/vessels")
def list_vessels():
    require_roles(*ALL_ROLES)
    return list_response("vessels", {
        "operator_id": "operator_id", "fishery_id": "fishery_id",
        "status": "status", "monitoring_mode": "monitoring_mode",
    })


@bp.get("/vessels/<vid>")
def get_vessel(vid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("vessels", vid, "Vessel"))


@bp.patch("/vessels/<vid>")
def patch_vessel(vid):
    require_roles("ProgramAdmin")
    v = get_or_404("vessels", vid, "Vessel")
    b = body()
    status = opt_enum(b, "status", ("REGISTERED", "ACTIVE", "SUSPENDED"))
    length_ft = opt_num(b, "length_ft")
    gear = opt_enum(b, "gear_type", GEAR_TYPES)
    home_port = opt_str(b, "home_port")
    revenue = opt_int(b, "declared_annual_revenue_cents")
    from core import dec
    if length_ft is not None and dec(length_ft) <= 0:
        raise err_invalid("length_ft must be > 0")
    if status is not None and status != v["status"]:
        current = v["status"]
        ok_transition = (current, status) in (
            ("REGISTERED", "ACTIVE"), ("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE"),
        )
        if not ok_transition:
            raise err_state("Vessel cannot transition %s -> %s" % (current, status))
        if status == "ACTIVE":
            op = store.db["operators"].get(v["operator_id"])
            if op is None or op["status"] != "ACTIVE":
                raise err_state("VesselOperator must be ACTIVE to activate the vessel")
        v["status"] = status
    if length_ft is not None:
        v["length_ft"] = length_ft
    if gear is not None:
        v["gear_type"] = gear
    if home_port is not None:
        v["home_port"] = home_port
    if revenue is not None:
        v["declared_annual_revenue_cents"] = revenue
    store.touch(v)
    return ok(v)


# ---------------------------------------------------------------------------
# Observer
# ---------------------------------------------------------------------------


@bp.post("/observers")
def create_observer():
    require_roles("ProgramAdmin")
    b = body()
    person_ref = req_str(b, "person_ref")
    full_name = req_str(b, "full_name")
    home_port = req_str(b, "home_port")
    level = req_enum(b, "certification_level", CERT_LEVELS)
    check_unique("observers", "person_ref", person_ref)
    import logic
    o = store.new_entity({
        "person_ref": person_ref, "full_name": full_name, "home_port": home_port,
        "certification_level": level,
        "max_consecutive_sea_days": logic.CERT_CAPS[level],
        "sea_days_used_ytd": 0,
        "status": "ACTIVE",
    })
    store.db["observers"][o["id"]] = o
    return ok(o, status=201)


@bp.get("/observers")
def list_observers():
    require_roles(*ALL_ROLES)
    return list_response("observers", {"status": "status", "certification_level": "certification_level"})


@bp.get("/observers/<oid>")
def get_observer(oid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("observers", oid, "Observer"))


@bp.patch("/observers/<oid>")
def patch_observer(oid):
    require_roles("ProgramAdmin")
    o = get_or_404("observers", oid, "Observer")
    b = body()
    status = opt_enum(b, "status", ("ACTIVE", "SUSPENDED", "DECERTIFIED"))
    home_port = opt_str(b, "home_port")
    level = opt_enum(b, "certification_level", CERT_LEVELS)
    if status is not None and status != o["status"]:
        current = o["status"]
        if current == "DECERTIFIED":
            raise err_state("A DECERTIFIED observer cannot change status")
        if status == "DECERTIFIED":
            import logic
            busy = any(
                d["observer_id"] == o["id"] and d["status"] in logic.ACTIVE_DEPLOYMENT_STATUSES
                for d in store.db["deployments"].values()
            )
            if busy:
                raise err_state("Observer holds open deployments and cannot be decertified")
        elif (current, status) not in (("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")):
            raise err_state("Observer cannot transition %s -> %s" % (current, status))
        o["status"] = status
    if home_port is not None:
        o["home_port"] = home_port
    if level is not None:
        import logic
        o["certification_level"] = level
        o["max_consecutive_sea_days"] = logic.CERT_CAPS[level]
    store.touch(o)
    return ok(o)


# ---------------------------------------------------------------------------
# Debriefer / EMReviewer (slim registries)
# ---------------------------------------------------------------------------


def _create_person(collection, label):
    require_roles("ProgramAdmin")
    b = body()
    person_ref = req_str(b, "person_ref")
    full_name = req_str(b, "full_name")
    check_unique(collection, "person_ref", person_ref)
    e = store.new_entity({
        "person_ref": person_ref, "full_name": full_name, "status": "ACTIVE",
    })
    store.db[collection][e["id"]] = e
    return ok(e, status=201)


def _patch_person(collection, pid, label):
    require_roles("ProgramAdmin")
    e = get_or_404(collection, pid, label)
    b = body()
    status = opt_enum(b, "status", ("ACTIVE", "SUSPENDED"))
    if status is not None:
        e["status"] = status
    store.touch(e)
    return ok(e)


@bp.post("/debriefers")
def create_debriefer():
    return _create_person("debriefers", "Debriefer")


@bp.get("/debriefers")
def list_debriefers():
    require_roles(*ALL_ROLES)
    return list_response("debriefers", {"status": "status"})


@bp.get("/debriefers/<pid>")
def get_debriefer(pid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("debriefers", pid, "Debriefer"))


@bp.patch("/debriefers/<pid>")
def patch_debriefer(pid):
    return _patch_person("debriefers", pid, "Debriefer")


@bp.post("/em-reviewers")
def create_em_reviewer():
    return _create_person("em_reviewers", "EMReviewer")


@bp.get("/em-reviewers")
def list_em_reviewers():
    require_roles(*ALL_ROLES)
    return list_response("em_reviewers", {"status": "status"})


@bp.get("/em-reviewers/<pid>")
def get_em_reviewer(pid):
    require_roles(*ALL_ROLES)
    return ok(get_or_404("em_reviewers", pid, "EMReviewer"))


@bp.patch("/em-reviewers/<pid>")
def patch_em_reviewer(pid):
    return _patch_person("em_reviewers", pid, "EMReviewer")
