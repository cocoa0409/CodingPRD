"""GrowerContract lifecycle: create, activate, upgrade, renewal, termination."""
from flask import Blueprint

import db
import utils
from errors import ApiError
from helpers import check_unique, get_or_404, need_date, need_int, need_str
from middleware import body, grower_owns_or_403, require_roles
from response import ok
from services import domain

bp = Blueprint("contracts", __name__)

ADMIN = "IntegratorAdmin"
GROWER = "Grower"
ANALYST = "SettlementAnalyst"


@bp.route("/api/contracts", methods=["POST"])
@require_roles(ADMIN)
def create_contract():
    b = body()
    # Priority 4: body FK existence.
    grower_id = b.get("grower_id")
    if not isinstance(grower_id, str) or not grower_id:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "Field 'grower_id' is required.", 422
        )
    if grower_id not in db.growers:
        raise ApiError(
            "ERR_REFERENCE_NOT_FOUND",
            "grower_id %s does not resolve." % grower_id,
            404,
        )
    # Priority 11: quantity sanity.
    contract_no = need_str(b, "contract_no")
    base_pay = need_int(b, "base_pay_cents_per_lb")
    if base_pay <= 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "base_pay_cents_per_lb must be positive.", 422
        )
    committed = need_int(b, "committed_house_count")
    if committed < 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "committed_house_count must be >= 0.", 422
        )
    term_start = need_date(b, "term_start_date")
    term_end = need_date(b, "term_end_date")
    # Priority 12: uniqueness.
    check_unique(db.contracts.values(), "contract_no", contract_no, "contract_no")
    rec = utils.make_record(
        {
            "grower_id": grower_id,
            "contract_no": contract_no,
            "base_pay_cents_per_lb": base_pay,
            "committed_house_count": committed,
            "term_start_date": term_start,
            "term_end_date": term_end,
            "status": "DRAFT",
            "upgrade_required": False,
        }
    )
    db.contracts[rec["id"]] = rec
    return ok(utils.pub(rec), 201)


@bp.route("/api/contracts/<cid>", methods=["GET"])
@require_roles(ADMIN, GROWER, ANALYST)
def get_contract(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    grower_owns_or_403(rec["grower_id"])
    return ok(utils.pub(rec))


@bp.route("/api/contracts/<cid>/activate", methods=["POST"])
@require_roles(ADMIN)
def activate_contract(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    if rec["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DRAFT contract can be activated (current: %s)." % rec["status"],
            409,
        )
    grower = db.growers.get(rec["grower_id"])
    if grower is None or grower["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Contract activation requires an ACTIVE grower.",
            409,
        )
    eligible = domain.eligible_house_count(rec["grower_id"])
    if eligible < rec["committed_house_count"]:
        raise ApiError(
            "ERR_INVALID_STATE",
            "Grower has %d eligible houses, fewer than committed_house_count %d."
            % (eligible, rec["committed_house_count"]),
            409,
        )
    rec["status"] = "ACTIVE"
    domain.bump(rec)
    return ok(utils.pub(rec))


@bp.route("/api/contracts/<cid>/impose-upgrade", methods=["POST"])
@require_roles(ADMIN)
def impose_upgrade(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    if not rec["upgrade_required"]:
        rec["upgrade_required"] = True
        domain.bump(rec)
    return ok(utils.pub(rec))


@bp.route("/api/contracts/<cid>/request-renewal", methods=["POST"])
@require_roles(GROWER)
def request_renewal(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    grower_owns_or_403(rec["grower_id"])
    if rec["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE contract can request renewal (current: %s)." % rec["status"],
            409,
        )
    if utils.logical_after(rec["term_end_date"]):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Renewal may only be requested on or before term_end_date %s."
            % rec["term_end_date"],
            409,
        )
    rec["status"] = "RENEWAL_PENDING"
    domain.bump(rec)
    return ok(utils.pub(rec))


@bp.route("/api/contracts/<cid>/renew", methods=["POST"])
@require_roles(ADMIN)
def renew_contract(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    if rec["status"] != "RENEWAL_PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a RENEWAL_PENDING contract can be renewed (current: %s)." % rec["status"],
            409,
        )
    b = body()
    new_term_end = need_date(b, "new_term_end_date")
    new_committed = need_int(b, "new_committed_house_count")
    if new_committed < 0:
        raise ApiError(
            "ERR_QUANTITY_INVALID", "new_committed_house_count must be >= 0.", 422
        )
    # Priority 13: renewal preconditions.
    if rec["upgrade_required"]:
        financed = any(
            l["grower_id"] == rec["grower_id"]
            and l["purpose"] == "CAPITAL_UPGRADE"
            and l["status"] in ("ISSUED", "REPAID")
            for l in db.loans.values()
        )
        if not financed:
            raise ApiError(
                "ERR_RENEWAL_BLOCKED",
                "Renewal blocked: upgrade_required is set and no CAPITAL_UPGRADE loan "
                "in ISSUED or REPAID status satisfies it.",
                422,
            )
    eligible = domain.eligible_house_count(rec["grower_id"])
    if eligible < new_committed:
        raise ApiError(
            "ERR_RENEWAL_BLOCKED",
            "Renewal blocked: %d eligible houses, fewer than new_committed_house_count %d."
            % (eligible, new_committed),
            422,
        )
    rec["status"] = "RENEWED"
    rec["term_end_date"] = new_term_end
    rec["committed_house_count"] = new_committed
    domain.bump(rec)
    grower = db.growers.get(rec["grower_id"])
    if grower is not None and domain.recompute_house_count(grower):
        domain.bump(grower)
    return ok(utils.pub(rec))


@bp.route("/api/contracts/<cid>/reject-renewal", methods=["POST"])
@require_roles(ADMIN)
def reject_renewal(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    if rec["status"] != "RENEWAL_PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a RENEWAL_PENDING contract can be rejected (current: %s)." % rec["status"],
            409,
        )
    rec["status"] = "ACTIVE"
    domain.bump(rec)
    return ok(utils.pub(rec))


@bp.route("/api/contracts/<cid>/terminate", methods=["POST"])
@require_roles(ADMIN)
def terminate_contract(cid):
    rec = get_or_404(db.contracts, cid, "GrowerContract")
    if rec["status"] != "ACTIVE":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an ACTIVE contract can be terminated (current: %s)." % rec["status"],
            409,
        )
    in_flight = sum(
        1
        for f in db.flocks.values()
        if f["contract_id"] == cid and f["status"] in domain.IN_FLIGHT_FLOCK_STATUSES
    )
    if in_flight:
        raise ApiError(
            "ERR_FLOCKS_IN_FLIGHT",
            "Termination blocked: %d flock(s) under this contract are non-terminal." % in_flight,
            409,
        )
    rec["status"] = "TERMINATED"
    domain.bump(rec)
    return ok(utils.pub(rec))
