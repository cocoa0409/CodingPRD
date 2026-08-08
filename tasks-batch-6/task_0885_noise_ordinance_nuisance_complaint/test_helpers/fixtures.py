"""Composite setup helpers.

These encapsulate the multi-step API sequences most test claims need to reach a
specific state (configure a policy, register a parcel, file/review/inspect/
substantiate complaints, contest citations, schedule and decide hearings, drive
chronic-nuisance posture to WATCH/DESIGNATED). Every helper builds its
preconditions from scratch against an empty database using only PRD endpoints,
and uses the lenient get_success_data() validator so setup problems surface as
clear "Setup failed" errors.

All helpers take the ApiClient as their first argument.
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    code_officer_headers,
    hearing_officer_headers,
    permit_clerk_headers,
    resident_headers,
    system_admin_headers,
)

# Day/night limits per zoning used consistently across setups.
POLICY_LIMITS = {
    "RESIDENTIAL": (55, 45),
    "COMMERCIAL": (65, 55),
    "INDUSTRIAL": (75, 65),
    "MIXED": (60, 50),
}
# A daytime decibel comfortably above each zoning's day limit.
OVER_LIMIT_DB = {
    "RESIDENTIAL": 70,
    "COMMERCIAL": 80,
    "INDUSTRIAL": 90,
    "MIXED": 80,
}

_ADDR_SEQ = [0]


def _next_address(prefix="Parcel"):
    _ADDR_SEQ[0] += 1
    return f"{_ADDR_SEQ[0]} {prefix} St"


# --------------------------------------------------------------------------- #
# Low-level building blocks
# --------------------------------------------------------------------------- #
def set_clock(api, iso: str):
    return get_success_data(api.set_clock({"to_iso8601": iso}, system_admin_headers()))


def config_policy(api, zoning, day_limit=None, night_limit=None,
                  day_start_hour=7, night_start_hour=22):
    if day_limit is None or night_limit is None:
        day_limit, night_limit = POLICY_LIMITS[zoning]
    return get_success_data(api.create_noise_policy({
        "zoning_type": zoning,
        "day_limit_db": day_limit,
        "night_limit_db": night_limit,
        "day_start_hour": day_start_hour,
        "night_start_hour": night_start_hour,
    }, system_admin_headers()))


def new_property(api, zoning="RESIDENTIAL", address=None):
    return get_success_data(api.create_property({
        "address": address or _next_address(),
        "zoning_type": zoning,
    }, code_officer_headers()))


def file_complaint(api, prop_id, reported_at, noise_type="MACHINERY", **overrides):
    payload = {"property_id": prop_id, "reported_at": reported_at, "noise_type": noise_type}
    payload.update(overrides)
    return get_success_data(api.create_complaint(payload, code_officer_headers()))


def review(api, complaint_id):
    return get_success_data(api.review_complaint(complaint_id, code_officer_headers()))


def inspect(api, complaint_id, measured_decibel, measured_at, officer_id="officer-1"):
    return get_success_data(api.create_inspection(complaint_id, {
        "measured_decibel": measured_decibel,
        "measured_at": measured_at,
    }, code_officer_headers(officer_id)))


def substantiate(api, complaint_id, officer_id="officer-1"):
    return get_success_data(api.substantiate_complaint(complaint_id, code_officer_headers(officer_id)))


def substantiate_once(api, prop_id, reported_at, measured_decibel,
                      noise_type="MACHINERY", officer_id="officer-1", measured_at=None):
    """File -> review -> inspect(over-limit) -> substantiate. Returns (complaint, enforcement)."""
    c = file_complaint(api, prop_id, reported_at, noise_type)
    review(api, c["id"])
    inspect(api, c["id"], measured_decibel, measured_at or reported_at, officer_id)
    enf = substantiate(api, c["id"], officer_id)
    return c, enf


def contest(api, enforcement_id):
    return get_success_data(api.contest_enforcement(enforcement_id, resident_headers()))


def schedule_hearing(api, enforcement_id, scheduled_at, hearing_officer_id="hof-9",
                     duration_minutes=None):
    payload = {"scheduled_at": scheduled_at, "hearing_officer_id": hearing_officer_id}
    if duration_minutes is not None:
        payload["duration_minutes"] = duration_minutes
    return get_success_data(api.create_hearing(enforcement_id, payload,
                                               hearing_officer_headers(hearing_officer_id)))


def decide(api, hearing_id, outcome, deciding_user_id="hof-9", reduction_pct=None):
    payload = {"outcome": outcome}
    if reduction_pct is not None:
        payload["reduction_pct"] = reduction_pct
    return get_success_data(api.decide_hearing(hearing_id, payload,
                                              hearing_officer_headers(deciding_user_id)))


def read_enforcement(api, enforcement_id):
    return get_success_data(api.get_enforcement(enforcement_id, code_officer_headers()))


def read_property(api, property_id):
    return get_success_data(api.get_property(property_id, code_officer_headers()))


# --------------------------------------------------------------------------- #
# Composite scenarios
# --------------------------------------------------------------------------- #
def setup_policy_and_property(api, zoning="COMMERCIAL", clock=None):
    """Configure a policy for `zoning` and register a fresh parcel of that zoning."""
    if clock:
        set_clock(api, clock)
    config_policy(api, zoning)
    prop = new_property(api, zoning)
    return prop


def setup_level1_citation(api, zoning="COMMERCIAL", clock=None,
                          first_reported="2026-05-10T12:00:00Z",
                          second_reported="2026-05-11T12:00:00Z"):
    """Two substantiations on one parcel: first -> WARNING (level 0), second -> level-1 CITATION.

    Returns dict with keys: property, prop_id, warning, enforcement, officer_id.
    For COMMERCIAL the level-1 CITATION assessed_fine_cents == 15000.
    """
    if clock:
        set_clock(api, clock)
    config_policy(api, zoning)
    prop = new_property(api, zoning)
    d = OVER_LIMIT_DB[zoning]
    _, warning = substantiate_once(api, prop["id"], first_reported, d)
    _, citation = substantiate_once(api, prop["id"], second_reported, d)
    return {
        "property": prop,
        "prop_id": prop["id"],
        "warning": warning,
        "enforcement": citation,
        "officer_id": "officer-1",
    }


def setup_contested_citation(api, zoning="COMMERCIAL", clock=None):
    """A level-1 CITATION moved to CONTESTED. Returns the same dict as setup_level1_citation
    with the enforcement now CONTESTED."""
    ctx = setup_level1_citation(api, zoning=zoning, clock=clock)
    contest(api, ctx["enforcement"]["id"])
    return ctx


def setup_scheduled_hearing(api, zoning="COMMERCIAL", clock=None,
                            scheduled_at="2026-05-20T10:00:00Z", hearing_officer_id="hof-9"):
    """A level-1 CITATION contested and its PENDING hearing scheduled by a different officer.

    Returns dict adding: hearing, hearing_id. The issuing officer is 'officer-1' and the
    hearing officer defaults to 'hof-9' so segregation of duties is satisfiable.
    """
    ctx = setup_contested_citation(api, zoning=zoning, clock=clock)
    hearing = schedule_hearing(api, ctx["enforcement"]["id"], scheduled_at, hearing_officer_id)
    ctx["hearing"] = hearing
    ctx["hearing_id"] = hearing["id"]
    return ctx


def setup_watch_property(api, zoning="RESIDENTIAL"):
    """A parcel driven to chronic_status WATCH via exactly 2 substantiations.

    Returns dict: property, prop_id, enforcements (list of 2).
    """
    config_policy(api, zoning)
    prop = new_property(api, zoning)
    d = OVER_LIMIT_DB[zoning]
    _, e1 = substantiate_once(api, prop["id"], "2026-05-10T12:00:00Z", d, noise_type="ANIMAL")
    _, e2 = substantiate_once(api, prop["id"], "2026-05-11T12:00:00Z", d, noise_type="ANIMAL")
    return {"property": prop, "prop_id": prop["id"], "enforcements": [e1, e2]}


def setup_designated_property(api, zoning="RESIDENTIAL", noise_type="VEHICLE"):
    """A parcel driven to chronic_status DESIGNATED via exactly 3 substantiations, which
    auto-creates one PENDING CHRONIC_DESIGNATION AbatementOrder (abatement_status
    UNDER_ABATEMENT).

    Returns dict: property, prop_id, enforcements (list of 3), abatement_order, abatement_id.
    """
    config_policy(api, zoning)
    prop = new_property(api, zoning)
    d = OVER_LIMIT_DB[zoning]
    _, e1 = substantiate_once(api, prop["id"], "2026-05-10T12:00:00Z", d, noise_type=noise_type)
    _, e2 = substantiate_once(api, prop["id"], "2026-05-11T12:00:00Z", d, noise_type=noise_type)
    _, e3 = substantiate_once(api, prop["id"], "2026-05-12T12:00:00Z", d, noise_type=noise_type)
    orders, _ = _list_abatement_orders(api, prop["id"])
    abatement = orders[0] if orders else None
    return {
        "property": prop,
        "prop_id": prop["id"],
        "enforcements": [e1, e2, e3],
        "abatement_order": abatement,
        "abatement_id": abatement["id"] if abatement else None,
    }


def _list_abatement_orders(api, property_id):
    from prd_bench_local_runner.testing import validate_paginated
    resp = api.list_abatement_orders(code_officer_headers(), params={"property_id": property_id})
    return validate_paginated(resp)
