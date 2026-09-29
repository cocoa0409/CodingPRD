"""Referral placements, the conversion/settlement/reversal saga and the
immutable revenue-share ledger."""

from datetime import timedelta

from flask import Blueprint

import db
import response
import validators as v
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    FEED_INTEGRATOR,
    MOVE_OPS_AGENT,
    PARTNER_AGENT,
    authenticate,
)
from services import derive, enums, gates, revenue
from services.lookup import (
    ledger_entry_or_404,
    move_or_404,
    placement_or_404,
    placements_of_move,
    ref_partner,
)

bp = Blueprint("placements", __name__)


def _partner(placement):
    return db.db.partners[placement["partner_id"]]


def _feed_source(move):
    return db.db.feed_sources[move["feed_source_id"]]


@bp.post("/moves/<move_id>/referral-placements")
def create_placement(move_id):
    authenticate(MOVE_OPS_AGENT)
    move = move_or_404(move_id)
    body = v.body()

    # rung 4 then rung 6.
    partner = ref_partner(v.id_field(body, "partner_id", required=False))
    if partner is None:
        v.bad("Field 'partner_id' is required.")
    expected = v.int_field(body, "expected_move_version")

    gates.require_move_state(
        move, ("VERIFIED", "SCHEDULING", "ATTENTION_REQUIRED", "IN_SERVICE")
    )
    gates.check_move_version(move, expected)
    gates.require_consent(move, "PARTNER_MARKETING")

    resident = db.db.residents[move["resident_id"]]
    gates.require_no_marketing_opt_out(resident)
    gates.require_duplicate_resolved(move)

    # rung 41: one live placement per (move, vertical).
    for other in placements_of_move(move["id"]):
        if other["vertical"] != partner["vertical"]:
            continue
        if other["placement_status"] in ("PLACED", "ACCEPTED", "CONVERTED", "SETTLED"):
            raise ApiError(
                "ERR_DUPLICATE_VERTICAL_PLACEMENT",
                "This move already has a live placement in that vertical.",
            )

    # rung 48 then rung 49.
    if partner["partner_status"] != "ACTIVE":
        raise ApiError(
            "ERR_PARTNER_PAUSED", "The referral partner is not ACTIVE."
        )
    now = db.now()
    month_count = 0
    for other in db.db.placements.values():
        if other["partner_id"] != partner["id"]:
            continue
        placed_at = db.parse_ts(other["placed_at"])
        if placed_at is None:
            continue
        if (placed_at.year, placed_at.month) == (now.year, now.month):
            month_count += 1
    if month_count >= partner["monthly_placement_cap"]:
        raise ApiError(
            "ERR_PARTNER_CAP_REACHED",
            "The partner has reached its monthly placement cap.",
        )

    rec = db.base_record()
    rec.update(
        {
            "move_id": move["id"],
            "partner_id": partner["id"],
            "vertical": partner["vertical"],
            "placement_status": "PLACED",
            "placed_at": db.now_iso(),
            "accepted_at": None,
            "converted_at": None,
            "gross_revenue_cents": 0,
            "settled_gross_revenue_cents": 0,
            "attributed_share_cents": 0,
            "feed_source_share_cents": 0,
            "decline_reason": None,
            "reversal_reason": None,
        }
    )
    db.db.placements[rec["id"]] = rec

    snap = derive.snapshot(move)
    derive.recompute(move)
    derive.commit(move, snap, force=True)
    return response.created(db.public(rec))


@bp.get("/referral-placements/<placement_id>")
def read_placement(placement_id):
    caller = authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, PARTNER_AGENT)
    rec = placement_or_404(placement_id)
    caller.own_if(PARTNER_AGENT, rec["partner_id"])
    return response.ok(db.public(rec))


@bp.get("/referral-placements")
def list_placements():
    authenticate(MOVE_OPS_AGENT, COMPLIANCE_OFFICER, PARTNER_AGENT)
    rows = response.match_filters(
        db.db.placements.values(),
        {
            "move_id": "move_id",
            "partner_id": "partner_id",
            "placement_status": "placement_status",
            "vertical": "vertical",
        },
    )
    return response.paginated(rows)


# ----------------------------------------------------------------- acceptance
@bp.post("/referral-placements/<placement_id>/acceptance")
def accept_placement(placement_id):
    caller = authenticate(PARTNER_AGENT)
    rec = placement_or_404(placement_id)
    caller.own_if(PARTNER_AGENT, rec["partner_id"])
    v.body()

    gates.require_placement_state(rec, ("PLACED",))
    move = move_or_404(rec["move_id"])
    gates.require_gate_open(move)

    rec["placement_status"] = "ACCEPTED"
    rec["accepted_at"] = db.now_iso()
    db.touch(rec)
    return response.ok(db.public(rec))


# -------------------------------------------------------------------- decline
@bp.post("/referral-placements/<placement_id>/decline")
def decline_placement(placement_id):
    caller = authenticate(PARTNER_AGENT)
    rec = placement_or_404(placement_id)
    caller.own_if(PARTNER_AGENT, rec["partner_id"])
    body = v.body()
    reason = v.str_field(body, "decline_reason", min_len=1, max_len=500)

    gates.require_placement_state(rec, ("ACCEPTED",))

    rec["placement_status"] = "DECLINED"
    rec["decline_reason"] = reason
    db.touch(rec)
    return response.ok(db.public(rec))


# ----------------------------------------------------------------- conversion
@bp.post("/referral-placements/<placement_id>/conversions")
def convert_placement(placement_id):
    caller = authenticate(PARTNER_AGENT)
    rec = placement_or_404(placement_id)
    caller.own_if(PARTNER_AGENT, rec["partner_id"])
    body = v.body()
    gross = v.int_field(body, "gross_revenue_cents", minimum=1)

    gates.require_placement_state(rec, ("ACCEPTED",))
    move = move_or_404(rec["move_id"])
    gates.require_gate_open(move)
    gates.require_no_marketing_opt_out(db.db.residents[move["resident_id"]])

    # rung 36: the attribution window, inclusive of the boundary instant.
    partner = _partner(rec)
    if partner["attribution_basis"] == "PLACEMENT_ACCEPTANCE":
        anchor = db.parse_ts(rec["accepted_at"])
    else:
        anchor = db.parse_ts(rec["placed_at"])
    if anchor is not None:
        deadline = anchor + timedelta(days=partner["attribution_window_days"])
        if db.now() > deadline:
            raise ApiError(
                "ERR_ATTRIBUTION_WINDOW_EXPIRED",
                "The partner's attribution window has closed.",
            )

    feed_source = _feed_source(move)
    commission = revenue.commission_provisional(partner, gross)
    feed_share = revenue.feed_source_share(commission, feed_source)

    rec["placement_status"] = "CONVERTED"
    rec["converted_at"] = db.now_iso()
    rec["gross_revenue_cents"] = gross
    rec["attributed_share_cents"] = commission
    rec["feed_source_share_cents"] = feed_share
    db.touch(rec)

    revenue.post_entry(rec, move, "ACCRUAL", commission)
    revenue.post_entry(rec, move, "FEED_SOURCE_SHARE", -feed_share)
    revenue.recompute_feed_accrual(feed_source)
    return response.ok(db.public(rec))


# ----------------------------------------------------------------- settlement
@bp.post("/referral-placements/<placement_id>/settlement")
def settle_placement(placement_id):
    authenticate()
    rec = placement_or_404(placement_id)
    body = v.body()
    settled_gross = v.int_field(body, "settled_gross_revenue_cents", minimum=0)

    gates.require_placement_state(rec, ("CONVERTED",))

    # rung 50: at least one cent and at most twice the reported gross.
    if settled_gross < 1 or settled_gross > 2 * rec["gross_revenue_cents"]:
        raise ApiError(
            "ERR_SETTLEMENT_AMOUNT_INVALID",
            "settled_gross_revenue_cents must be >= 1 and at most twice the"
            " reported gross revenue.",
        )

    move = move_or_404(rec["move_id"])
    feed_source = _feed_source(move)
    partner = _partner(rec)

    prior_commission = rec["attributed_share_cents"]
    prior_feed_share = rec["feed_source_share_cents"]
    commission = revenue.commission_settled(partner, settled_gross)
    feed_share = revenue.feed_source_share(commission, feed_source)

    rec["placement_status"] = "SETTLED"
    rec["settled_gross_revenue_cents"] = settled_gross
    rec["attributed_share_cents"] = commission
    rec["feed_source_share_cents"] = feed_share
    db.touch(rec)

    revenue.post_entry(rec, move, "ADJUSTMENT", commission - prior_commission)
    revenue.post_entry(
        rec, move, "FEED_SOURCE_SHARE_ADJUSTMENT", -(feed_share - prior_feed_share)
    )
    revenue.recompute_feed_accrual(feed_source)
    return response.ok(db.public(rec))


# ------------------------------------------------------------------- reversal
@bp.post("/referral-placements/<placement_id>/reversal")
def reverse_placement(placement_id):
    caller = authenticate(PARTNER_AGENT)
    rec = placement_or_404(placement_id)
    caller.own_if(PARTNER_AGENT, rec["partner_id"])
    body = v.body()
    reason = v.str_field(body, "reversal_reason", min_len=1, max_len=500)

    gates.require_placement_state(rec, ("CONVERTED",))

    move = move_or_404(rec["move_id"])
    feed_source = _feed_source(move)
    commission = rec["attributed_share_cents"]
    feed_share = rec["feed_source_share_cents"]

    rec["placement_status"] = "REVERSED"
    rec["reversal_reason"] = reason
    rec["attributed_share_cents"] = 0
    rec["feed_source_share_cents"] = 0
    db.touch(rec)

    revenue.post_entry(rec, move, "REVERSAL", -commission)
    revenue.post_entry(rec, move, "FEED_SOURCE_SHARE_REVERSAL", feed_share)
    revenue.recompute_feed_accrual(feed_source)
    return response.ok(db.public(rec))


# --------------------------------------------------------------------- ledger
@bp.get("/revenue-share-ledger-entries/<entry_id>")
def read_ledger_entry(entry_id):
    authenticate(COMPLIANCE_OFFICER)
    return response.ok(db.public(ledger_entry_or_404(entry_id)))


@bp.get("/revenue-share-ledger-entries")
def list_ledger_entries():
    authenticate(COMPLIANCE_OFFICER, FEED_INTEGRATOR, PARTNER_AGENT)
    rows = response.match_filters(
        db.db.ledger.values(),
        {
            "placement_id": "placement_id",
            "move_id": "move_id",
            "feed_source_id": "feed_source_id",
            "entry_type": "entry_type",
        },
    )
    return response.paginated(rows)
