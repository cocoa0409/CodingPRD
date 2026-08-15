"""Grower roster, suspension, loans, and grower-scoped lists."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from helpers import check_unique, get_or_404, need_int, need_str, need_enum
from middleware import body, grower_owns_or_403, list_response, require_roles
from response import ok
from services import domain

bp = Blueprint("growers", __name__)

ADMIN = "IntegratorAdmin"
GROWER = "Grower"
ANALYST = "SettlementAnalyst"
TECH = "ServiceTech"
HAUL = "LivehaulScheduler"


def _grower_path_guard(gid):
    """Priority 2 ownership before priority 3 existence for grower-self routes:
    a Grower naming any grower id but their own is rejected 403 outright."""
    grower_owns_or_403(gid)
    return get_or_404(db.growers, gid, "Grower")


@bp.route("/api/growers", methods=["POST"])
@require_roles(ADMIN)
def create_grower():
    b = body()
    grower_code = need_str(b, "grower_code")
    full_name = need_str(b, "full_name")
    check_unique(db.growers.values(), "grower_code", grower_code, "grower_code")
    rec = utils.make_record(
        {
            "grower_code": grower_code,
            "full_name": full_name,
            "status": "ACTIVE",
            "performance_rating": None,
            "loan_outstanding_cents": 0,
            "house_count": 0,
        }
    )
    db.growers[rec["id"]] = rec
    return ok(utils.pub(rec), 201)


@bp.route("/api/growers/<gid>", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST, TECH, HAUL)
def get_grower(gid):
    rec = _grower_path_guard(gid)
    return ok(utils.pub(rec))


@bp.route("/api/growers", methods=["GET"])
@require_roles(ADMIN, ANALYST)
def list_growers():
    from flask import request

    return list_response(
        db.growers.values(), {"status": request.args.get("status")}
    )


@bp.route("/api/growers/<gid>/suspend", methods=["POST"])
@require_roles(ADMIN)
def suspend_grower(gid):
    rec = get_or_404(db.growers, gid, "Grower")
    if rec["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE grower can be suspended (current: %s)." % rec["status"],
            409,
        )
    rec["status"] = "SUSPENDED"
    domain.bump(rec)
    return ok(utils.pub(rec))


@bp.route("/api/growers/<gid>/loans", methods=["POST"])
@require_roles(ADMIN)
def issue_loan(gid):
    grower = get_or_404(db.growers, gid, "Grower")
    b = body()
    # Priority 6: OCC on Grower.version (skipped when the field is omitted).
    if "expected_grower_version" in b and b.get("expected_grower_version") is not None:
        if b.get("expected_grower_version") != grower["version"]:
            raise ApiError(
                "ERR_STALE_GROWER_VERSION",
                "expected_grower_version %r does not match current Grower.version %d; re-read and retry."
                % (b.get("expected_grower_version"), grower["version"]),
                412,
            )
    # Priority 16: loan terms.
    principal = need_int(b, "principal_cents", "ERR_LOAN_TERMS_INVALID")
    recovery_pct = need_int(b, "recovery_pct", "ERR_LOAN_TERMS_INVALID")
    purpose = need_enum(
        b, "purpose", domain.LOAN_PURPOSES, "ERR_LOAN_TERMS_INVALID"
    )
    if principal <= 0:
        raise ApiError(
            "ERR_LOAN_TERMS_INVALID", "principal_cents must be positive.", 422
        )
    if recovery_pct < 1 or recovery_pct > 50:
        raise ApiError(
            "ERR_LOAN_TERMS_INVALID", "recovery_pct must be within 1..50.", 422
        )
    rec = utils.make_record(
        {
            "grower_id": gid,
            "principal_cents": principal,
            "recovery_pct": recovery_pct,
            "outstanding_cents": principal,
            "status": "ISSUED",
            "purpose": purpose,
        }
    )
    db.loans[rec["id"]] = rec
    if domain.recompute_loan_outstanding(grower):
        domain.bump(grower)
    return ok(utils.pub(rec), 201)


@bp.route("/api/growers/<gid>/loans", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST)
def list_loans(gid):
    _grower_path_guard(gid)
    rows = [l for l in db.loans.values() if l["grower_id"] == gid]
    return list_response(rows)


@bp.route("/api/growers/<gid>/houses", methods=["GET"])
@require_roles(ADMIN, GROWER, TECH)
def list_grower_houses(gid):
    from flask import request

    _grower_path_guard(gid)
    rows = [h for h in db.houses.values() if h["grower_id"] == gid]
    return list_response(rows, {"house_status": request.args.get("house_status")})


@bp.route("/api/growers/<gid>/contracts", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST)
def list_grower_contracts(gid):
    _grower_path_guard(gid)
    rows = [c for c in db.contracts.values() if c["grower_id"] == gid]
    return list_response(rows)
