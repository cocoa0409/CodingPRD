"""Rate agreement endpoints (supersede pattern, OCC on Contributor.version)."""

from flask import request

from .auth import require, require_owner
from .blueprint import bp
from .envelope import ok_list, ok_obj
from .errors import ApiError, bad_request, invalid_state, not_found
from .serialize import ser_rate_agreement
from .store import STORE, new_entity, touch
from .util import (
    body,
    opt_dt,
    opt_int,
    paged,
    pagination_params,
    req_dt,
    req_enum,
    req_int,
    sort_created,
)

PRICING_MODES = ("PER_WORD", "FLAT")
RIGHTS_KINDS = ("FIRST", "ONE_TIME", "ALL")
IN_FLIGHT_STATUSES = ("OFFERED", "ACCEPTED", "IN_PROGRESS", "SUBMITTED", "UNDER_VERIFICATION")
READ_ROLES = ["DeskAdmin", "Editor", "FinanceUser", "Contributor"]


@bp.post("/freelance-desk/contributors/<cid>/rate-agreements")
def create_rate_agreement(cid):
    require(["DeskAdmin"])
    c = STORE.contributors.get(cid)
    if c is None:
        not_found("Contributor")
    # Priority 4: state precondition of the supersede transition
    if c["status"] != "ACTIVE":
        invalid_state("Rate agreements can only be created for an ACTIVE contributor")
    b = body()

    # Priority 15: field shape
    pricing_mode = req_enum(b, "pricing_mode", PRICING_MODES)
    per_word = opt_int(b, "per_word_rate_cents")
    flat = opt_int(b, "flat_fee_cents")
    if pricing_mode == "PER_WORD":
        if per_word is None or per_word < 1:
            bad_request("per_word_rate_cents must be >= 1 when pricing_mode is PER_WORD")
        if flat is not None:
            bad_request("flat_fee_cents must be null when pricing_mode is PER_WORD")
    else:
        if flat is None or flat < 1:
            bad_request("flat_fee_cents must be >= 1 when pricing_mode is FLAT")
        if per_word is not None:
            bad_request("per_word_rate_cents must be null when pricing_mode is FLAT")
    kill_fee_pct = req_int(b, "kill_fee_pct_num")
    if not (1 <= kill_fee_pct <= 100):
        bad_request("kill_fee_pct_num must be between 1 and 100")
    rights_default = req_enum(b, "rights_default", RIGHTS_KINDS)
    effective_from = req_dt(b, "effective_from")
    effective_to = opt_dt(b, "effective_to")
    if "expected_contributor_version" not in b or b["expected_contributor_version"] is None:
        bad_request("expected_contributor_version is required")
    expected_version = b["expected_contributor_version"]
    if not isinstance(expected_version, int) or isinstance(expected_version, bool):
        bad_request("expected_contributor_version must be an integer")

    # Priority 16: validity window
    prior_active = None
    for r in STORE.rate_agreements.values():
        if r["contributor_id"] == cid and r["status"] == "ACTIVE":
            prior_active = r
            break
    if effective_to is not None and not (effective_from < effective_to):
        raise ApiError(
            "ERR_INVALID_WINDOW", 422, "effective_to must be null or after effective_from"
        )
    if prior_active is not None and effective_from < prior_active["effective_from"]:
        raise ApiError(
            "ERR_INVALID_WINDOW",
            422,
            "effective_from must be at or after the prior ACTIVE agreement's effective_from",
        )

    # Priority 19: OCC on the contributor
    if expected_version != c["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_contributor_version does not match current version"
        )

    if prior_active is not None:
        prior_active["status"] = "SUPERSEDED"
        touch(prior_active)

    e = new_entity()
    e.update({
        "contributor_id": cid,
        "pricing_mode": pricing_mode,
        "per_word_rate_cents": per_word,
        "flat_fee_cents": flat,
        "kill_fee_pct_num": kill_fee_pct,
        "rights_default": rights_default,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
    })
    STORE.rate_agreements[e["id"]] = e
    touch(c)  # create-with-supersede bumps the parent contributor version
    return ok_obj(ser_rate_agreement(e), 201)


@bp.get("/freelance-desk/contributors/<cid>/rate-agreements")
def list_rate_agreements(cid):
    uid, role = require(READ_ROLES)
    c = STORE.contributors.get(cid)
    if c is None:
        not_found("Contributor")
    if role == "Contributor":
        require_owner(uid, cid)
    items = [r for r in STORE.rate_agreements.values() if r["contributor_id"] == cid]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r["status"] == status]
    items = sort_created(items)
    limit, offset = pagination_params()
    page, total = paged(items, limit, offset)
    return ok_list([ser_rate_agreement(r) for r in page], limit, offset, total)


@bp.get("/freelance-desk/rate-agreements/<rid>")
def get_rate_agreement(rid):
    uid, role = require(READ_ROLES)
    r = STORE.rate_agreements.get(rid)
    if r is None:
        not_found("RateAgreement")
    if role == "Contributor":
        require_owner(uid, r["contributor_id"])
    return ok_obj(ser_rate_agreement(r))


@bp.post("/freelance-desk/rate-agreements/<rid>/revoke")
def revoke_rate_agreement(rid):
    require(["DeskAdmin"])
    r = STORE.rate_agreements.get(rid)
    if r is None:
        not_found("RateAgreement")
    if r["status"] != "ACTIVE":
        invalid_state("Only an ACTIVE rate agreement can be revoked")
    for a in STORE.assignments.values():
        if a["rate_agreement_id"] == rid and a["editorial_status"] in IN_FLIGHT_STATUSES:
            invalid_state("Agreement is referenced by an in-flight assignment")
    r["status"] = "REVOKED"
    touch(r)
    return ok_obj(ser_rate_agreement(r))
