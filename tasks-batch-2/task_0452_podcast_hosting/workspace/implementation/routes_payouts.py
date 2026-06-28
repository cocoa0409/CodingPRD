"""PayoutStatement endpoints, revenue share, and settlement (PRD §3.8)."""

from flask import request

import calc
import common
import db
import errors
import ownership
import serialize
from common import new_common, touch
from response import success, list_success
from routehelpers import auth_and_role, body
from timeutil import parse_iso


def register(app):
    @app.route("/payout-statements", methods=["POST"])
    def create_payout():
        auth_and_role(["PlatformAdmin"])
        data = body()
        publisher_id = common.require_str(data, "publisher_id")
        period_start = common.require_str(data, "period_start")
        period_end = common.require_str(data, "period_end")
        try:
            start_dt = parse_iso(period_start)
            end_dt = parse_iso(period_end)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "period_start/period_end must be ISO 8601 timestamps")
        publisher = ownership.get_publisher(publisher_id)
        figures = _compute_figures(publisher, start_dt, end_dt)
        rec = new_common()
        rec.update({
            "publisher_id": publisher_id,
            "period_start": period_start,
            "period_end": period_end,
            "status": "DRAFT",
            "gross_revenue_cents": figures["gross"],
            "platform_fee_cents": figures["platform_fee"],
            "net_payable_cents": figures["net"],
            "settled_revenue_cents": figures["settled"],
        })
        db.db.payout_statements[rec["id"]] = rec
        return success(serialize.payout_statement(rec), status=201)

    @app.route("/payout-statements", methods=["GET"])
    def list_payouts():
        auth_and_role(["PlatformAdmin", "Publisher"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.payout_statements.values())
        publisher_id = request.args.get("publisher_id")
        if publisher_id:
            items = [s for s in items if s["publisher_id"] == publisher_id]
        status = request.args.get("status")
        if status:
            items = [s for s in items if s["status"] == status]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.payout_statement(s) for s in page], limit, offset, total)

    @app.route("/payout-statements/<sid>", methods=["GET"])
    def get_payout(sid):
        auth_and_role(["PlatformAdmin", "Publisher"])
        s = ownership.get_payout(sid)
        return success(serialize.payout_statement(s), status=200)

    @app.route("/payout-statements/<sid>/finalize", methods=["POST"])
    def finalize_payout(sid):
        auth_and_role(["PlatformAdmin"])
        s = ownership.get_payout(sid)
        if s["status"] != "DRAFT":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a DRAFT statement may be finalized")
        # Figures were computed at creation and are persisted -> already frozen.
        s["status"] = "FINALIZED"
        touch(s)
        return success(serialize.payout_statement(s), status=200)

    @app.route("/payout-statements/<sid>/pay", methods=["POST"])
    def pay_payout(sid):
        auth_and_role(["PlatformAdmin"])
        s = ownership.get_payout(sid)
        if s["status"] != "FINALIZED":
            raise errors.err(errors.ERR_INVALID_STATE, "Only a FINALIZED statement may be paid")
        if s["net_payable_cents"] <= 0:
            raise errors.err(errors.ERR_NOTHING_TO_PAY, "net_payable_cents is zero")
        s["status"] = "PAID"
        touch(s)
        return success(serialize.payout_statement(s), status=200)

    @app.route("/payout-statements/<sid>/void", methods=["POST"])
    def void_payout(sid):
        auth_and_role(["PlatformAdmin"])
        s = ownership.get_payout(sid)
        # DRAFT or FINALIZED (not yet PAID) -> VOID.
        if s["status"] not in ("DRAFT", "FINALIZED"):
            raise errors.err(errors.ERR_INVALID_STATE, "Statement cannot be voided from its current state")
        s["status"] = "VOID"
        touch(s)
        return success(serialize.payout_statement(s), status=200)


def _compute_figures(publisher, start_dt, end_dt):
    """gross / net / platform_fee / settled over the half-open window (PRD §3.8)."""
    # Select DELIVERED placements on this publisher's shows whose created_at is in
    # [period_start, period_end), ordered by created_at ASC for determinism.
    selected = []
    for p in db.db.ad_placements.values():
        if p["status"] != "DELIVERED":
            continue
        episode = db.db.episodes.get(p["episode_id"])
        if episode is None:
            continue
        show = db.db.shows.get(episode["show_id"])
        if show is None or show["publisher_id"] != publisher["id"]:
            continue
        created = parse_iso(p["created_at"])
        if start_dt <= created < end_dt:
            selected.append(p)
    selected.sort(key=lambda p: (p["created_at"], p["id"]))

    # gross = sum of already-rounded per-placement final_cost_cents.
    gross = sum(p["final_cost_cents"] for p in selected)
    # net = round_half_up(gross * share) once, after the product; fee = residual.
    net = calc.payout_net_from_gross(gross, publisher["revenue_share_pct"])
    platform_fee = gross - net
    # settled variant: only placements whose campaign is COMPLETED.
    settled_gross = 0
    for p in selected:
        campaign = db.db.ad_campaigns.get(p["campaign_id"])
        if campaign is not None and campaign["status"] == "COMPLETED":
            settled_gross += p["final_cost_cents"]
    settled = calc.payout_net_from_gross(settled_gross, publisher["revenue_share_pct"])
    return {"gross": gross, "net": net, "platform_fee": platform_fee, "settled": settled}
