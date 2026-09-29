"""Risk pool accounting, reserving and settlement (PRD 3.7, 3.8)."""

from flask import Blueprint

import calc
import db
import derive
import middleware
import resolve
import response
import serialize
import validate
from errors import fail

bp = Blueprint("pools", __name__)

POOL_TYPES = ("PROFESSIONAL", "INSTITUTIONAL")
POOL_STATES = ("ACCUMULATING", "CLOSED_FOR_INCURRAL", "RESERVED",
               "SETTLEMENT_PROPOSED", "SETTLED")
POOL_READ_ROLES = ("IpaAdmin", "NetworkManager", "ClaimsExaminer",
                   "ReinsuranceUnderwriter", "PayerRepresentative")
PARTICIPATING_CREDENTIALS = ("ACTIVE", "NOTICE_GIVEN")


@bp.post("/ipa/delegation-agreements/<agreement_id>/risk-pools")
def create_pool(agreement_id):
    middleware.require("IpaAdmin")
    body = validate.body()
    pool_type = validate.req_enum(body, "pool_type", POOL_TYPES)
    pool_year_start = validate.req_instant(body, "pool_year_start")
    pool_year_end = validate.req_instant(body, "pool_year_end")

    agreement = resolve.agreement(agreement_id)

    # check 8
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")
    # check 19 — closed-interval overlap for pools of the same type
    for existing in db.pools_of_agreement(agreement["id"]):
        if existing["pool_type"] != pool_type:
            continue
        if (pool_year_start.dt <= existing["pool_year_end"].dt
                and existing["pool_year_start"].dt <= pool_year_end.dt):
            fail("ERR_POOL_PERIOD_OVERLAP")

    pool = db.create(
        db.pools,
        agreement_id=agreement["id"],
        pool_type=pool_type,
        pool_year_start=pool_year_start,
        pool_year_end=pool_year_end,
        status="ACCUMULATING",
        settlement_due_date=db.add_days(pool_year_end,
                                        calc.SETTLEMENT_LAG_DAYS[pool_type]),
        funded_cents=0,
        member_months_bps=0,
        paid_claims_cents=0,
        ibnr_reserve_cents=0,
        ibnr_method_used=None,
        stop_loss_recovery_cents=0,
        stop_loss_eligible_enrollee_count=0,
        loss_ratio_bps=0,
        deficit_flag=False,
        surplus_tier=None,
        raw_surplus_cents=0,
        admin_fee_cents=0,
        distributable_surplus_cents=0,
        shared_savings_pool_cents=0,
        _remittance_ids=[],
    )
    return response.ok(serialize.pool(pool), 201)


@bp.get("/ipa/delegation-agreements/<agreement_id>/risk-pools")
def list_agreement_pools(agreement_id):
    user_id, role = middleware.require(*POOL_READ_ROLES)
    pool_type = validate.query_enum("pool_type", POOL_TYPES)
    status = validate.query_enum("status", POOL_STATES)
    limit, offset = validate.pagination()
    agreement = resolve.agreement(agreement_id)
    middleware.check_ownership(role, user_id, agreement=agreement)

    items = db.pools_of_agreement(agreement["id"])
    if pool_type is not None:
        items = [p for p in items if p["pool_type"] == pool_type]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.pool(p) for p in window], limit, offset,
                            len(items))


@bp.get("/ipa/risk-pools/<pool_id>")
def read_pool(pool_id):
    user_id, role = middleware.require(*POOL_READ_ROLES)
    pool = resolve.pool(pool_id)
    middleware.check_ownership(role, user_id, agreement=db.agreement_of_pool(pool))
    return response.ok(serialize.pool(pool))


@bp.get("/ipa/risk-pools/<pool_id>/settlement-preview")
def settlement_preview(pool_id):
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    override = validate.query_enum("ibnr_method_override", calc.IBNR_METHODS)
    pool = resolve.pool(pool_id)
    agreement = db.agreement_of_pool(pool)
    middleware.check_ownership(role, user_id, agreement=agreement)

    if override is not None:
        reserve = calc.ibnr_reserve_estimate(agreement, pool, override)
    else:
        reserve = pool["ibnr_reserve_cents"]
    return response.ok(calc.pool_settlement_waterfall(pool, reserve))


# ------------------------------------------------------------ state machine
def _participants(pool, agreement):
    """Physicians eligible for a distribution, ordered created_at then npi."""
    period = "%04d" % pool["pool_year_start"].dt.year
    eligible = []
    for physician in db.physicians_of_agreement(agreement["id"]):
        if physician["credential_status"] not in PARTICIPATING_CREDENTIALS:
            continue
        scorecard = None
        for candidate in db.scorecards_of_physician(physician["id"]):
            if (candidate["measurement_period"] == period
                    and candidate["status"] == "FINAL"):
                scorecard = candidate
        if scorecard is None:
            return None, period
        eligible.append((physician, scorecard))
    eligible.sort(key=lambda pair: (pair[0]["_seq"], pair[0]["npi"]))
    return eligible, period


def _reserve(pool, agreement, override):
    method = override or agreement["ibnr_method"]
    pool["ibnr_method_used"] = method
    pool["ibnr_reserve_cents"] = calc.ibnr_reserve_estimate(agreement, pool, method)


def _propose_settlement(pool, agreement, participants):
    waterfall = calc.pool_settlement_waterfall(pool, pool["ibnr_reserve_cents"])
    pool["raw_surplus_cents"] = waterfall["raw_surplus_cents"]
    pool["surplus_tier"] = waterfall["surplus_tier"]
    pool["admin_fee_cents"] = waterfall["admin_fee_cents"]
    pool["distributable_surplus_cents"] = waterfall["distributable_surplus_cents"]
    pool["shared_savings_pool_cents"] = waterfall["shared_savings_pool_cents"]

    if not participants:
        return
    withhold_weights = []
    savings_weights = []
    member_months = []
    for physician, scorecard in participants:
        panel_mm = derive.panel_member_months_bps(pool, physician["id"])
        member_months.append(panel_mm)
        withhold_weights.append(panel_mm)
        savings_weights.append(panel_mm * scorecard["composite_score_bps"])

    withhold_shares = calc.largest_remainder_allocate(
        agreement["withheld_balance_cents"], withhold_weights)
    savings_shares = calc.largest_remainder_allocate(
        pool["shared_savings_pool_cents"], savings_weights)

    for index, (physician, scorecard) in enumerate(participants):
        release_bps = scorecard["withhold_release_bps"] or 0
        withhold_share = withhold_shares[index]
        release = calc.round_half_up(withhold_share * release_bps, 10000)
        savings = savings_shares[index]
        db.create(
            db.distributions,
            pool_id=pool["id"],
            physician_id=physician["id"],
            composite_score_bps_snapshot=scorecard["composite_score_bps"],
            withhold_release_bps_snapshot=release_bps,
            panel_member_months_bps=member_months[index],
            withhold_share_cents=withhold_share,
            withhold_release_cents=release,
            shared_savings_cents=savings,
            net_distribution_cents=release + savings,
            status="PROPOSED",
        )


def _void_settlement(pool, dispute_reason):
    for distribution in db.distributions_of_pool(pool["id"]):
        if distribution["status"] == "PROPOSED":
            distribution["status"] = "VOIDED"
            db.touch(distribution)
    pool["raw_surplus_cents"] = 0
    pool["surplus_tier"] = None
    pool["admin_fee_cents"] = 0
    pool["distributable_surplus_cents"] = 0
    pool["shared_savings_pool_cents"] = 0
    pool["_dispute_reason"] = dispute_reason


def _settle(pool, agreement):
    withhold_total = 0
    forfeited_total = 0
    for distribution in db.distributions_of_pool(pool["id"]):
        if distribution["status"] != "PROPOSED":
            continue
        distribution["status"] = "PAID"
        db.touch(distribution)
        withhold_total += distribution["withhold_share_cents"]
        forfeited_total += (distribution["withhold_share_cents"]
                            - distribution["withhold_release_cents"])
    agreement["withheld_balance_cents"] -= withhold_total
    agreement["forfeited_withhold_cents"] += forfeited_total
    db.touch(agreement)


@bp.post("/ipa/risk-pools/<pool_id>/state")
def pool_state(pool_id):
    user_id, role = middleware.require("IpaAdmin", "PayerRepresentative")
    body = validate.body()
    to_state = validate.req_enum(body, "to_state", POOL_STATES)
    override = validate.opt_enum(body, "ibnr_method_override", calc.IBNR_METHODS)
    dispute_reason = validate.opt_str(body, "dispute_reason")

    pool = resolve.pool(pool_id)
    current = pool["status"]

    # transition-level authorisation: only the payer disputes a proposal
    if to_state == "RESERVED" and current == "SETTLEMENT_PROPOSED":
        allowed = ("PayerRepresentative",)
    else:
        allowed = ("IpaAdmin",)
    middleware.require_transition_role(role, allowed)

    agreement = db.agreement_of_pool(pool)
    middleware.check_ownership(role, user_id, agreement=agreement)

    if to_state == "CLOSED_FOR_INCURRAL":
        if current != "ACCUMULATING" or db.clock().dt < pool["pool_year_end"].dt:
            fail("ERR_INVALID_STATE_TRANSITION")
        pool["status"] = "CLOSED_FOR_INCURRAL"
        db.touch(pool)

    elif to_state == "RESERVED":
        if current in ("CLOSED_FOR_INCURRAL", "RESERVED"):
            _reserve(pool, agreement, override)
            pool["status"] = "RESERVED"
            db.touch(pool)
        elif current == "SETTLEMENT_PROPOSED":
            _void_settlement(pool, dispute_reason)
            pool["status"] = "RESERVED"
            db.touch(pool)
        else:
            fail("ERR_INVALID_STATE_TRANSITION")

    elif to_state == "SETTLEMENT_PROPOSED":
        if current != "RESERVED":
            fail("ERR_INVALID_STATE_TRANSITION")
        participants, _period = _participants(pool, agreement)
        # check 23
        if participants is None:
            fail("ERR_SCORECARD_NOT_FINAL")
        _propose_settlement(pool, agreement, participants)
        pool["status"] = "SETTLEMENT_PROPOSED"
        db.touch(pool)

    elif to_state == "SETTLED":
        if current != "SETTLEMENT_PROPOSED":
            fail("ERR_INVALID_STATE_TRANSITION")
        # check 17
        if db.clock().dt < pool["settlement_due_date"].dt:
            fail("ERR_SETTLEMENT_WINDOW_NOT_OPEN")
        _settle(pool, agreement)
        pool["status"] = "SETTLED"
        db.touch(pool)

    else:  # pragma: no cover
        fail("ERR_INVALID_STATE_TRANSITION")

    return response.ok(serialize.pool(pool))


# --------------------------------------------------------- pool distributions
DISTRIBUTION_READ_ROLES = ("IpaAdmin", "NetworkManager", "PayerRepresentative",
                           "PhysicianUser")
DISTRIBUTION_STATES = ("PROPOSED", "VOIDED", "PAID")


@bp.get("/ipa/pool-distributions")
def list_distributions():
    middleware.require(*DISTRIBUTION_READ_ROLES)
    pool_id = validate.query_str("pool_id")
    physician_id = validate.query_str("physician_id")
    status = validate.query_enum("status", DISTRIBUTION_STATES)
    limit, offset = validate.pagination()

    items = db.ordered(db.distributions.values())
    if pool_id is not None:
        items = [d for d in items if d["pool_id"] == pool_id]
    if physician_id is not None:
        items = [d for d in items if d["physician_id"] == physician_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    window = validate.paginate(items, limit, offset)
    return response.ok_list([serialize.distribution(d) for d in window], limit, offset,
                            len(items))


@bp.get("/ipa/pool-distributions/<distribution_id>")
def read_distribution(distribution_id):
    user_id, role = middleware.require(*DISTRIBUTION_READ_ROLES)
    distribution = resolve.distribution(distribution_id)
    middleware.check_ownership(role, user_id,
                              physician_ids=[distribution["physician_id"]],
                              agreement=db.agreement_of_distribution(distribution))
    return response.ok(serialize.distribution(distribution))
