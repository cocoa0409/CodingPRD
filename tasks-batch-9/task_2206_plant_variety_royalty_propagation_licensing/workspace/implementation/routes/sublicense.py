"""Sublicense grants: proposal, activation with the exclusivity buffer, revocation."""

from flask import Blueprint

from common import check_occ, filtered, require_agreement_active, resolve, terminal, transition
from derive import apply, children, recompute_active_sublicense_count
from errors import ApiError
from middleware import ALL_ROLES, LICENSING_OFFICER, endpoint
from response import collection, created, ok
from store import add_days, new_id, parse_dt, store
from validation import ID, DateTime, Enum, Int, Str, TERRITORY, UPPER_2_4

bp = Blueprint("sublicense", __name__)

GRANT_TERMINAL = ("REVOKED", "EXPIRED")
EXCLUSIVITY_BUFFER_DAYS = 30

GRANT_SCHEMA = [
    ("agreement_id", ID, True),
    ("variety_id", ID, True),
    ("sublicensee_name", Str(1, 80), True),
    ("territory_code", TERRITORY, True),
    ("jurisdiction_code", UPPER_2_4, True),
    ("exclusivity", Enum(["EXCLUSIVE", "NON_EXCLUSIVE"]), False),
    ("effective_date", DateTime(), True),
    ("expiry_date", DateTime(), True),
    ("expected_agreement_version", Int(0), True),
]


@endpoint(bp, "POST", "/sublicense-grants", [LICENSING_OFFICER], GRANT_SCHEMA)
def propose_grant(actor, body):
    agreement = resolve("agreement_id", body["agreement_id"])
    variety = resolve("variety_id", body["variety_id"])
    check_occ(body, "expected_agreement_version", agreement,
              "ERR_STALE_AGREEMENT_VERSION")
    if body["territory_code"] not in agreement["territory_codes"]:
        raise ApiError("ERR_TERRITORY_NOT_LICENSED")
    effective_date = parse_dt(body["effective_date"])
    expiry_date = parse_dt(body["expiry_date"])
    if expiry_date <= effective_date:
        raise ApiError("ERR_INVALID_INTERVAL")
    if (effective_date < parse_dt(agreement["term_start"])
            or expiry_date > parse_dt(agreement["term_end"])):
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM")
    record = {
        "id": new_id(),
        "agreement_id": agreement["id"],
        "variety_id": variety["id"],
        "sublicensee_name": body["sublicensee_name"],
        "territory_code": body["territory_code"],
        "jurisdiction_code": body["jurisdiction_code"],
        "exclusivity": body["exclusivity"] or "NON_EXCLUSIVE",
        "effective_date": body["effective_date"],
        "expiry_date": body["expiry_date"],
        "status": "PROPOSED",
        "activated_at": None,
        "revocation_reason": None,
    }
    store.stamp_new(record)
    store.grants[record["id"]] = record
    apply(agreement, None, force=True)
    return created(record)


@endpoint(bp, "GET", "/sublicense-grants", ALL_ROLES)
def list_grants(actor):
    records, limit, offset, total = filtered(
        "grants", "agreement_id", "variety_id", "territory_code", "status",
        "exclusivity")
    return collection(records, limit, offset, total)


@endpoint(bp, "GET", "/sublicense-grants/<grant_id>", ALL_ROLES)
def get_grant(actor, grant_id):
    return ok(resolve("grant_id", grant_id))


def exclusivity_conflict(candidate):
    """Buffer the incumbent by 30 days on both ends; never the applicant."""
    cand_start = parse_dt(candidate["effective_date"])
    cand_end = parse_dt(candidate["expiry_date"])
    for other in children("grants", "variety_id", candidate["variety_id"]):
        if other["id"] == candidate["id"] or other["status"] != "ACTIVE":
            continue
        if other["territory_code"] != candidate["territory_code"]:
            continue
        if (other["exclusivity"] != "EXCLUSIVE"
                and candidate["exclusivity"] != "EXCLUSIVE"):
            continue
        inc_start = add_days(parse_dt(other["effective_date"]),
                             -EXCLUSIVITY_BUFFER_DAYS)
        inc_end = add_days(parse_dt(other["expiry_date"]),
                           EXCLUSIVITY_BUFFER_DAYS)
        # Both intervals are closed, so touching endpoints do overlap.
        if inc_start <= cand_end and cand_start <= inc_end:
            return True
    return False


@endpoint(bp, "POST", "/sublicense-grants/<grant_id>/activate", [LICENSING_OFFICER], [])
def activate_grant(actor, body, grant_id):
    grant = resolve("grant_id", grant_id)
    terminal(grant["status"] in GRANT_TERMINAL)
    transition(grant["status"] == "PROPOSED")
    agreement = store.agreements[grant["agreement_id"]]
    require_agreement_active(agreement)
    variety = store.varieties[grant["variety_id"]]
    if grant["jurisdiction_code"] not in variety["protected_jurisdictions"]:
        raise ApiError("ERR_PROTECTION_NOT_IN_FORCE")
    if variety["lifecycle_state"] != "RELEASED":
        raise ApiError("ERR_VARIETY_NOT_RELEASED")
    # A window that has already closed cannot be activated.
    transition(store.now <= parse_dt(grant["expiry_date"]))
    if exclusivity_conflict(grant):
        raise ApiError("ERR_EXCLUSIVITY_CONFLICT")
    apply(grant, {"status": "ACTIVE", "activated_at": store.now_iso()}, force=True)
    recompute_active_sublicense_count(variety, force=True)
    return ok(grant)


@endpoint(bp, "POST", "/sublicense-grants/<grant_id>/revoke", [LICENSING_OFFICER], [])
def revoke_grant(actor, body, grant_id):
    grant = resolve("grant_id", grant_id)
    terminal(grant["status"] in GRANT_TERMINAL)
    transition(grant["status"] in ("PROPOSED", "ACTIVE"))
    was_active = grant["status"] == "ACTIVE"
    apply(grant, {"status": "REVOKED", "revocation_reason": "MANUAL"}, force=True)
    variety = store.varieties.get(grant["variety_id"])
    if variety is not None:
        # From PROPOSED the count never moved, so the variety only bumps when
        # the re-derivation actually changes it (PRD 3.8).
        recompute_active_sublicense_count(variety, force=was_active)
    return ok(grant)
