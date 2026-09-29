"""Propagators, head licences and the suspension cycle."""

from flask import Blueprint

from calculations import COMPLIANCE_SUSPEND_THRESHOLD
from common import filtered, resolve, terminal, transition
from derive import (apply, children, close_quota_and_void_requests,
                    freeze_agreement_quotas, ordered_children,
                    recompute_active_sublicense_count, thaw_agreement_quotas)
from errors import ApiError
from middleware import ALL_ROLES, LICENSING_OFFICER, endpoint
from response import collection, created, ok
from store import new_id, parse_dt, store
from validation import ID, DateTime, Enum, Str, StrList, TERRITORY

bp = Blueprint("propagators", __name__)

PROPAGATOR_SCHEMA = [
    ("legal_name", Str(1, 80), True),
    ("home_territory_code", TERRITORY, True),
]

AGREEMENT_SCHEMA = [
    ("propagator_id", ID, True),
    ("quality_tier", Enum(["TIER_A", "TIER_B", "TIER_C"]), False),
    ("territory_codes", StrList(TERRITORY), True),
    ("term_start", DateTime(), True),
    ("term_end", DateTime(), True),
]


def norm(text):
    return (text or "").strip().casefold()


@endpoint(bp, "POST", "/propagators", [LICENSING_OFFICER], PROPAGATOR_SCHEMA)
def create_propagator(actor, body):
    for other in store.propagators.values():
        if norm(other["legal_name"]) == norm(body["legal_name"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "A propagator with this legal name already exists.")
    record = {
        "id": new_id(),
        "legal_name": body["legal_name"],
        "home_territory_code": body["home_territory_code"],
        "compliance_score": 100,
        "lifetime_compliance_score": 100,
        "royalty_payable_cents": 0,
        "royalty_settled_cents": 0,
        "damages_credit_cents": 0,
        "material_audit_finding_count": 0,
    }
    store.stamp_new(record)
    store.propagators[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/propagators", ALL_ROLES)
def list_propagators(actor):
    records, limit, offset, total = filtered("propagators", "home_territory_code")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/propagators/<propagator_id>", ALL_ROLES)
def get_propagator(actor, propagator_id):
    return ok(resolve("propagator_id", propagator_id))


# ---------------------------------------------------------------- agreements
@endpoint(bp, "POST", "/propagator-agreements", [LICENSING_OFFICER], AGREEMENT_SCHEMA)
def create_agreement(actor, body):
    propagator = resolve("propagator_id", body["propagator_id"])
    if parse_dt(body["term_end"]) <= parse_dt(body["term_start"]):
        raise ApiError("ERR_INVALID_INTERVAL")
    record = {
        "id": new_id(),
        "propagator_id": propagator["id"],
        "status": "PENDING_COUNTERSIGN",
        "quality_tier": body["quality_tier"] or "TIER_B",
        "territory_codes": list(body["territory_codes"]),
        "term_start": body["term_start"],
        "term_end": body["term_end"],
        "countersigned_by_user_id": None,
        "countersigned_at": None,
        "suspension_reason": None,
        "reinstatement_count": 0,
    }
    store.stamp_new(record)
    store.agreements[record["id"]] = record
    return created(record)


@endpoint(bp, "GET", "/propagator-agreements", ALL_ROLES)
def list_agreements(actor):
    records, limit, offset, total = filtered("agreements", "propagator_id", "status")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/propagator-agreements/<agreement_id>", ALL_ROLES)
def get_agreement(actor, agreement_id):
    return ok(resolve("agreement_id", agreement_id))


@endpoint(bp, "POST", "/propagator-agreements/<agreement_id>/countersign",
          [LICENSING_OFFICER], [])
def countersign(actor, body, agreement_id):
    agreement = resolve("agreement_id", agreement_id)
    terminal(agreement["status"] == "TERMINATED")
    transition(agreement["status"] == "PENDING_COUNTERSIGN")
    # Only available while the clock is strictly before term_end (PRD 3.5).
    transition(store.now < parse_dt(agreement["term_end"]))
    apply(agreement, {
        "status": "ACTIVE",
        "countersigned_by_user_id": actor.user_id,
        "countersigned_at": store.now_iso(),
    }, force=True)
    return ok(agreement)


@endpoint(bp, "POST", "/propagator-agreements/<agreement_id>/suspend",
          [LICENSING_OFFICER], [])
def suspend(actor, body, agreement_id):
    agreement = resolve("agreement_id", agreement_id)
    terminal(agreement["status"] == "TERMINATED")
    transition(agreement["status"] == "ACTIVE")
    apply(agreement, {"status": "SUSPENDED", "suspension_reason": "MANUAL"}, force=True)
    freeze_agreement_quotas(agreement)
    return ok(agreement)


@endpoint(bp, "POST", "/propagator-agreements/<agreement_id>/reinstate",
          [LICENSING_OFFICER], [])
def reinstate(actor, body, agreement_id):
    agreement = resolve("agreement_id", agreement_id)
    terminal(agreement["status"] == "TERMINATED")
    transition(agreement["status"] == "SUSPENDED")
    propagator = store.propagators[agreement["propagator_id"]]
    if int(propagator["compliance_score"]) < COMPLIANCE_SUSPEND_THRESHOLD:
        raise ApiError("ERR_COMPLIANCE_SCORE_TOO_LOW")
    if int(propagator["material_audit_finding_count"]) != 0:
        raise ApiError("ERR_MATERIAL_FINDING_UNRESOLVED")
    # The clock must still be strictly before term_end (PRD 3.5, uncoded gate).
    transition(store.now < parse_dt(agreement["term_end"]))
    apply(agreement, {
        "status": "ACTIVE",
        "suspension_reason": None,
        "reinstatement_count": int(agreement["reinstatement_count"]) + 1,
    }, force=True)
    thaw_agreement_quotas(agreement)
    return ok(agreement)


@endpoint(bp, "POST", "/propagator-agreements/<agreement_id>/terminate",
          [LICENSING_OFFICER], [])
def terminate(actor, body, agreement_id):
    agreement = resolve("agreement_id", agreement_id)
    terminal(agreement["status"] == "TERMINATED")
    transition(agreement["status"] in ("ACTIVE", "SUSPENDED"))
    for report in children("reports", "agreement_id", agreement["id"]):
        if (report["review_status"] == "ACCEPTED"
                and report["settlement_status"] == "UNSETTLED"):
            raise ApiError("ERR_UNSETTLED_ROYALTY_OUTSTANDING")
    apply(agreement, {"status": "TERMINATED"}, force=True)
    # Quota branch.
    quotas = ordered_children("quotas", "agreement_id", agreement["id"],
                              lambda q: q["season_code"])
    for quota in quotas:
        if quota["status"] in ("ACTIVE", "FROZEN"):
            close_quota_and_void_requests(quota)
    # Sublicensing branch.
    grants = ordered_children("grants", "agreement_id", agreement["id"],
                              lambda g: g["territory_code"],
                              lambda g: g["sublicensee_name"])
    touched_varieties = []
    for grant in grants:
        if grant["status"] in ("PROPOSED", "ACTIVE"):
            apply(grant, {
                "status": "REVOKED",
                "revocation_reason": "AGREEMENT_TERMINATED",
            })
            if grant["variety_id"] not in touched_varieties:
                touched_varieties.append(grant["variety_id"])
    for variety_id in touched_varieties:
        variety = store.varieties.get(variety_id)
        if variety is not None:
            recompute_active_sublicense_count(variety)
    return ok(agreement)
