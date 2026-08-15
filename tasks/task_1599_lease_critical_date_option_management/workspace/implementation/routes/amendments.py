"""Amendment negotiation endpoints (§3.7): cyclic negotiation, SoD, execution cascades."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_STATE, ERR_FK_SCOPE_VIOLATION, ERR_TEMPORAL_ORDER,
    ERR_NEGOTIATION_ALREADY_OPEN, ERR_STALE_VERSION, ERR_SOD_VIOLATION,
    ERR_LADDER_BREACH, ERR_NOT_IN_HOLDOVER,
)
from middleware import authorized, READ_ROLES
from response import success_object
from services.core import (
    new_record, touch, public, lease_amendments, compute_ladder,
    compute_holdover_accrual, post_ledger, supersede_nonterminal_options,
    OPEN_NEGOTIATION_STATES,
)
from routes.helpers import resolve_lease, resolve_amendment, sorted_items, paged
from util import CLOCK, fmt_dt, fmt_date_midnight, parse_date_value
from validate import get_body, req_int, req_enum, req_dateish, opt_int, opt_dateish, opt_bool

bp = Blueprint("amendments", __name__)

KINDS = ["RENEWAL_TERM", "EXPANSION_TERM", "CONTRACTION", "HOLDOVER_SETTLEMENT"]


@bp.post("/portfolios/<pid>/leases/<lid>/amendments")
def create_amendment(pid, lid):
    authorized(["AssetManager"])
    _p, lease = resolve_lease(pid, lid)
    body = get_body()
    supersedes = body.get("supersedes_amendment_id")
    if supersedes is not None and not isinstance(supersedes, str):
        raise_error(ERR_FK_SCOPE_VIOLATION, "supersedes_amendment_id must be a string id")
    kind = req_enum(body, "kind", KINDS)
    new_exp = req_dateish(body, "new_expiration_date")
    new_rent = req_int(body, "new_base_rent_cents_per_rsf_year", positive=True)
    # priority 4: body FK scope — supersedes must name an amendment of THIS lease
    if supersedes is not None:
        ref = db["amendments"].get(supersedes)
        if ref is None or ref["lease_id"] != lid:
            raise_error(ERR_FK_SCOPE_VIOLATION,
                        "supersedes_amendment_id must reference an amendment of the same lease")
    # priority 10: strictly after the lease's current expiration_date
    if new_exp <= parse_date_value(lease["expiration_date"]):
        raise_error(ERR_TEMPORAL_ORDER,
                    "new_expiration_date must be strictly after the current expiration_date")
    a = new_record("amendments", {
        "lease_id": lid,
        "supersedes_amendment_id": supersedes,
        "kind": kind,
        "new_expiration_date": fmt_date_midnight(new_exp),
        "new_base_rent_cents_per_rsf_year": new_rent,
        "status": "DRAFT",
        "negotiation_opened_at": None,
        "executed_at": None,
        "_last_proposer_user_id": None,
        "_agreed_by_user_id": None,
    })
    return success_object(public(a), 201)


@bp.get("/portfolios/<pid>/leases/<lid>/amendments")
def list_amendments(pid, lid):
    authorized(READ_ROLES)
    resolve_lease(pid, lid)
    items = sorted_items("amendments", {
        "lease_id": lid,
        "status": request.args.get("status"),
        "kind": request.args.get("kind"),
    })
    return paged(items, public)


@bp.get("/portfolios/<pid>/leases/<lid>/amendments/<aid>")
def get_amendment(pid, lid, aid):
    authorized(READ_ROLES)
    _p, _l, a = resolve_amendment(pid, lid, aid)
    return success_object(public(a))


@bp.post("/portfolios/<pid>/leases/<lid>/amendments/<aid>/propose")
def propose_amendment(pid, lid, aid):
    caller = authorized(["AssetManager"])
    _p, lease, a = resolve_amendment(pid, lid, aid)
    body = get_body()
    expected = req_int(body, "expected_lease_version")
    # priority 5: state (amendment DRAFT; lease ACTIVE/EXPIRING/HOLDOVER)
    if a["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT amendment can be proposed")
    if lease["status"] not in ("ACTIVE", "EXPIRING", "HOLDOVER"):
        raise_error(ERR_INVALID_STATE,
                    "proposal requires the lease to be ACTIVE, EXPIRING, or HOLDOVER")
    # priority 8: one open negotiation per lease
    for sib in lease_amendments(lid):
        if sib["id"] != aid and sib["status"] in OPEN_NEGOTIATION_STATES:
            raise_error(ERR_NEGOTIATION_ALREADY_OPEN,
                        "another amendment on this lease is already in open negotiation")
    # priority 14: OCC on Lease.version
    if expected != lease["version"]:
        raise_error(ERR_STALE_VERSION, "expected_lease_version does not match the lease version")
    a["status"] = "PROPOSED"
    a["negotiation_opened_at"] = fmt_dt(CLOCK.now())  # first proposal stamps it
    a["_last_proposer_user_id"] = caller.user_id
    touch(a)
    touch(lease)
    return success_object(public(a))


@bp.post("/portfolios/<pid>/leases/<lid>/amendments/<aid>/counter")
def counter_amendment(pid, lid, aid):
    authorized(["LandlordCounsel"])
    _p, _l, a = resolve_amendment(pid, lid, aid)
    body = get_body()
    new_rent = req_int(body, "new_base_rent_cents_per_rsf_year", positive=True)
    if a["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "only a PROPOSED amendment can be countered")
    a["new_base_rent_cents_per_rsf_year"] = new_rent
    a["status"] = "COUNTERED"
    touch(a)
    return success_object(public(a))


@bp.post("/portfolios/<pid>/leases/<lid>/amendments/<aid>/repropose")
def repropose_amendment(pid, lid, aid):
    caller = authorized(["AssetManager"])
    _p, _l, a = resolve_amendment(pid, lid, aid)
    body = get_body()
    new_rent = opt_int(body, "new_base_rent_cents_per_rsf_year", None, positive=True)
    new_exp = opt_dateish(body, "new_expiration_date", None)
    if a["status"] != "COUNTERED":
        raise_error(ERR_INVALID_STATE, "only a COUNTERED amendment can be re-proposed")
    if new_rent is not None:
        a["new_base_rent_cents_per_rsf_year"] = new_rent
    if new_exp is not None:
        a["new_expiration_date"] = fmt_date_midnight(new_exp)
    a["status"] = "PROPOSED"
    a["_last_proposer_user_id"] = caller.user_id  # most recent mover to PROPOSED
    touch(a)
    return success_object(public(a))


@bp.post("/portfolios/<pid>/leases/<lid>/amendments/<aid>/agree")
def agree_amendment(pid, lid, aid):
    caller = authorized(["LandlordCounsel"])
    _p, _l, a = resolve_amendment(pid, lid, aid)
    get_body()
    if a["status"] not in ("PROPOSED", "COUNTERED"):
        raise_error(ERR_INVALID_STATE, "only a PROPOSED or COUNTERED amendment can be agreed")
    # priority 9 — SoD: agreer != the user who most recently moved it to PROPOSED
    if a.get("_last_proposer_user_id") is not None and caller.user_id == a["_last_proposer_user_id"]:
        raise_error(ERR_SOD_VIOLATION,
                    "the agreeing counsel must differ from the most recent proposer")
    a["status"] = "AGREED"
    a["_agreed_by_user_id"] = caller.user_id
    touch(a)
    return success_object(public(a))


@bp.post("/portfolios/<pid>/leases/<lid>/amendments/<aid>/execute")
def execute_amendment(pid, lid, aid):
    caller = authorized(["AssetManager"])
    _p, lease, a = resolve_amendment(pid, lid, aid)
    body = get_body()
    expected = req_int(body, "expected_lease_version")
    enforce_ladder = opt_bool(body, "enforce_ladder", False)
    # priority 5: state admissibility
    if a["status"] != "AGREED":
        raise_error(ERR_INVALID_STATE, "only an AGREED amendment can be executed")
    # priority 9 — SoD: executor != agreer (precedes the stale-version check)
    if a.get("_agreed_by_user_id") is not None and caller.user_id == a["_agreed_by_user_id"]:
        raise_error(ERR_SOD_VIOLATION,
                    "the executing asset manager must differ from the agreeing counsel")
    # priority 14: OCC on Lease.version
    if expected != lease["version"]:
        raise_error(ERR_STALE_VERSION, "expected_lease_version does not match the lease version")
    # priority 15: advisory ladder guard against the post-execution view
    if enforce_ladder:
        post_status = lease["status"]
        if a["kind"] in ("RENEWAL_TERM", "EXPANSION_TERM"):
            post_status = "RENEWED"
        elif a["kind"] == "HOLDOVER_SETTLEMENT":
            post_status = "ACTIVE"
        lad = compute_ladder(pid, overrides={lid: {
            "status": post_status,
            "expiration_date": parse_date_value(a["new_expiration_date"]),
        }})
        if lad["posture"] == "LADDER_STRESSED":
            raise_error(ERR_LADDER_BREACH, "execution would push the portfolio into LADDER_STRESSED")
    # priority 16: settlement completeness
    if a["kind"] == "HOLDOVER_SETTLEMENT" and lease["status"] != "HOLDOVER":
        raise_error(ERR_NOT_IN_HOLDOVER,
                    "a HOLDOVER_SETTLEMENT amendment may only execute while the lease is in HOLDOVER")

    now = CLOCK.now()
    a["status"] = "EXECUTED"
    a["executed_at"] = fmt_dt(now)
    touch(a)

    # HOLDOVER_SETTLEMENT: the final accrual is priced on the then-current
    # (pre-execution) base rent — capture it before applying the new terms
    final_accrual = None
    if a["kind"] == "HOLDOVER_SETTLEMENT":
        final_accrual = compute_holdover_accrual(lease, now.date())

    # apply commercial terms; record as the lease's active amendment
    lease["expiration_date"] = a["new_expiration_date"]
    lease["base_rent_cents_per_rsf_year"] = a["new_base_rent_cents_per_rsf_year"]
    lease["active_amendment_id"] = aid

    if a["kind"] in ("RENEWAL_TERM", "EXPANSION_TERM"):
        # lease -> RENEWED per the lease machine (amendment-driven: no successor
        # lease row — the auto-create rule derives from an exercised option)
        lease["status"] = "RENEWED"
        touch(lease)
        supersede_nonterminal_options(lid)
    elif a["kind"] == "HOLDOVER_SETTLEMENT":
        # HOLDOVER -> ACTIVE: settle the final accrual, reset the counter
        post_ledger(lid, "AMENDMENT_SETTLEMENT", final_accrual, now.date())
        lease["accrued_holdover_rent_cents"] = 0
        lease["holdover_entered_at"] = None
        lease["status"] = "ACTIVE"
        touch(lease)
    else:  # CONTRACTION — new terms applied, lifecycle state unchanged
        touch(lease)
    return success_object(public(a))


@bp.post("/portfolios/<pid>/leases/<lid>/amendments/<aid>/abandon")
def abandon_amendment(pid, lid, aid):
    authorized(["AssetManager"])
    _p, lease, a = resolve_amendment(pid, lid, aid)
    get_body()
    if a["status"] not in ("DRAFT", "PROPOSED", "COUNTERED", "AGREED"):
        raise_error(ERR_INVALID_STATE, "an executed or abandoned amendment cannot be abandoned")
    a["status"] = "ABANDONED"
    touch(a)
    touch(lease)
    return success_object(public(a))
