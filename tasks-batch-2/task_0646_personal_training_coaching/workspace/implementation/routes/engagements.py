"""Engagement endpoints + lifecycle/end cascade (PRD §3.2, §3.3, §3.7)."""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from clock import clock, parse_iso8601, add_days, format_iso8601_ms
from helpers import (get_json_body, require_fields, require_enum,
                     pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import engagement_view
from services import domain
from services import calculations as calc

bp = Blueprint("engagements", __name__)

BILLING_MODELS = {"SESSION_PACK", "ONLINE_SUBSCRIPTION"}


@bp.route("/engagements", methods=["POST"])
@require_roles("Trainer")
def create_engagement():
    body = get_json_body()
    require_fields(body, "client_id", "billing_model", "expected_client_version")

    # Priority 4: FK existence.
    client = domain.get_client(body["client_id"])
    # Ownership: trainer must own the client.
    domain.assert_trainer_owns_client(client)

    # Priority 5: body well-formedness.
    billing_model = require_enum(body["billing_model"], BILLING_MODELS, "billing_model")
    expected_version = body["expected_client_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise errors.invalid_request("expected_client_version must be an integer")

    monthly_fee_cents = None
    cycle_start = None
    if billing_model == "ONLINE_SUBSCRIPTION":
        require_fields(body, "monthly_fee_cents", "cycle_start_utc")
        monthly_fee_cents = body["monthly_fee_cents"]
        if isinstance(monthly_fee_cents, bool) or not isinstance(monthly_fee_cents, int) or monthly_fee_cents <= 0:
            raise errors.invalid_request("monthly_fee_cents must be a positive integer")
        try:
            cycle_start = parse_iso8601(body["cycle_start_utc"])
        except Exception:
            raise errors.invalid_request("cycle_start_utc must be a valid ISO 8601 instant")

    # Priority 7: intake must be ASSESSED.
    if client["intake_status"] != "ASSESSED":
        raise errors.invalid_state(errors.ERR_INTAKE_NOT_ASSESSED, "Client intake is not ASSESSED")

    # Priority 13: OCC on client version.
    if expected_version != client["version"]:
        raise errors.stale_version("expected_client_version does not match client version")

    eid = new_id()
    ts = now_ts()
    engagement = {
        "id": eid,
        "client_id": client["id"],
        "trainer_id": client["trainer_id"],
        "billing_model": billing_model,
        "status": "ACTIVE",
        "wallet_credit_cents": 0,
        "pause_reason": "NONE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        # subscription cycle window (internal; not part of the public view)
        "monthly_fee_cents": monthly_fee_cents,
        "cycle_start_utc": format_iso8601_ms(cycle_start) if cycle_start else None,
        "cycle_end_utc": format_iso8601_ms(add_days(cycle_start, calc.MONTHLY_CYCLE_DAYS)) if cycle_start else None,
    }
    db.engagements[eid] = engagement

    # Side effect: increment client version by one.
    domain.touch(client)
    return success(engagement_view(engagement), 201)


@bp.route("/engagements/<engagement_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_engagement(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    return success(engagement_view(engagement), 200)


@bp.route("/engagements", methods=["GET"])
@require_roles("Trainer", "Client", "PlatformAdmin")
def list_engagements():
    limit, offset = pagination_params()
    client_filter = request.args.get("client_id")
    trainer_filter = request.args.get("trainer_id")

    items = list(db.engagements.values())
    if client_filter is not None:
        items = [e for e in items if e["client_id"] == client_filter]
    if trainer_filter is not None:
        items = [e for e in items if e["trainer_id"] == trainer_filter]
    if g.user_role == "Trainer":
        items = [e for e in items if e["trainer_id"] == g.user_id]
    elif g.user_role == "Client":
        items = [e for e in items if e["client_id"] == g.user_id]

    items.sort(key=lambda e: (e["created_at"], e["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([engagement_view(e) for e in page], limit, offset, total, 200)


@bp.route("/engagements/<engagement_id>/pause", methods=["POST"])
@require_roles("Trainer")
def pause_engagement(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    if engagement["status"] != "ACTIVE":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Engagement is not ACTIVE")
    engagement["status"] = "PAUSED"
    engagement["pause_reason"] = "MANUAL"
    domain.touch(engagement)
    return success(engagement_view(engagement), 200)


@bp.route("/engagements/<engagement_id>/resume", methods=["POST"])
@require_roles("Trainer")
def resume_engagement(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    if engagement["status"] != "PAUSED":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Engagement is not PAUSED")
    # Extra guard: if paused due to pack depletion, require an ACTIVE pack with a seat.
    if engagement["pause_reason"] == "PACK_DEPLETED":
        has_seat = any(
            p["engagement_id"] == engagement_id
            and p["status"] == "ACTIVE"
            and p["sessions_remaining"] > 0
            for p in db.session_packs.values()
        )
        if not has_seat:
            raise errors.invalid_state(errors.ERR_NO_SESSIONS_REMAINING,
                                       "No ACTIVE session pack with a remaining seat")
    engagement["status"] = "ACTIVE"
    engagement["pause_reason"] = "NONE"
    domain.touch(engagement)
    return success(engagement_view(engagement), 200)


@bp.route("/engagements/<engagement_id>/end", methods=["POST"])
@require_roles("Trainer")
def end_engagement(engagement_id):
    engagement = domain.get_engagement(engagement_id)
    domain.assert_owns_engagement(engagement)
    if engagement["status"] not in ("ACTIVE", "PAUSED"):
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Engagement is not ACTIVE or PAUSED")

    # 1. Cancel all BOOKED bookings (no fee), releasing their pack seats.
    for b in db.bookings.values():
        if b["engagement_id"] == engagement_id and b["status"] == "BOOKED":
            b["status"] = "CANCELLED"
            b["fee_charged_cents"] = 0
            domain.touch(b)

    # 2. SESSION_PACK: refund remaining (settled) seats, then mark REFUNDED.
    #    Settled view: only COMPLETED/NO_SHOW/LATE_CANCELLED are truly consumed;
    #    any still-BOOKED seat was just cancelled above so it no longer counts.
    if engagement["billing_model"] == "SESSION_PACK":
        for p in db.session_packs.values():
            if p["engagement_id"] != engagement_id or p["status"] != "ACTIVE":
                continue
            consumed = sum(
                1 for b in db.bookings.values()
                if b["session_pack_id"] == p["id"]
                and b["status"] in ("COMPLETED", "NO_SHOW", "LATE_CANCELLED")
            )
            unused = p["total_sessions"] - consumed
            if unused > 0:
                refund = unused * p["per_session_value_cents"]
                engagement["wallet_credit_cents"] += refund
            # recompute balance after cancellations, then settle to REFUNDED
            domain.recompute_pack_balance(p)
            p["status"] = "REFUNDED"
            domain.touch(p)

    # 3. ONLINE_SUBSCRIPTION: mid-cycle proration refund.
    if engagement["billing_model"] == "ONLINE_SUBSCRIPTION" and engagement.get("cycle_start_utc"):
        cycle_start = parse_iso8601(engagement["cycle_start_utc"])
        refund = calc.subscription_refund_cents(
            engagement["monthly_fee_cents"], cycle_start, clock.now())
        if refund > 0:
            engagement["wallet_credit_cents"] += refund

    if engagement["wallet_credit_cents"] < 0:
        engagement["wallet_credit_cents"] = 0

    # 4. PROVISIONAL macro plans -> LOCKED.
    for m in db.macro_plans.values():
        if m["engagement_id"] == engagement_id and m["status"] == "PROVISIONAL":
            m["status"] = "LOCKED"
            domain.touch(m)

    # 5. DRAFT/PUBLISHED programs -> ARCHIVED.
    for prog in db.program_assignments.values():
        if prog["engagement_id"] == engagement_id and prog["status"] in ("DRAFT", "PUBLISHED"):
            prog["status"] = "ARCHIVED"
            domain.touch(prog)

    # 6. Engagement -> ENDED.
    engagement["status"] = "ENDED"
    domain.touch(engagement)
    return success(engagement_view(engagement), 200)
