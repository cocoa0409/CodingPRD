"""The ops checkpoint (§2.5) and the logical-clock test-driving endpoint.

Step order is pinned:
 1. month settlement      6. deliverable misses (+ disclosure MISSING sweep)
 2. strike expiry         7. perk expiry
 3. tax-form expiry       8. subscription renewal / lapse
 4. grant expiry          9. deal completion
 5. stream no-shows      10. moderation (TIMEOUT) expiry
"""

from datetime import timedelta

from flask import Blueprint

import db
import domain
from core import (auth, body, iso, month_label, ok_obj, parse_dt, req_str,
                  require_role, rhu)
from core import err_invalid_request
from routes.community import grant_cycle
from routes.deals import breach_deal

bp = Blueprint("ops", __name__)

NO_SHOW_GRACE_MINUTES = 30
DISCLOSURE_MISSING_HOURS = 72
PAST_DUE_GRACE_DAYS = 7


@bp.post("/api/_clock/set_current_utc")
def set_clock():
    uid, role = auth()
    b = body()
    to_iso8601 = b.get("to_iso8601")
    if to_iso8601 is None:
        raise err_invalid_request("Field 'to_iso8601' is required")
    target = parse_dt(to_iso8601, "to_iso8601")
    require_role(role, ("PlatformAdmin",))
    db.store.clock = target  # the clock never falls back to wall time
    return ok_obj({"current_utc": iso(db.store.clock)})


@bp.post("/api/ops/run")
def ops_run():
    uid, role = auth()
    body()
    require_role(role, ("PlatformAdmin",))
    now = db.now()
    counters = {
        "events_cleared": 0,
        "strikes_expired": 0,
        "tax_forms_expired": 0,
        "grants_expired": 0,
        "streams_no_show": 0,
        "deliverables_missed": 0,
        "perks_expired": 0,
        "subscriptions_renewed": 0,
        "subscriptions_expired": 0,
        "deals_completed": 0,
        "payouts_released": 0,
    }

    # -- Step 1: month settlement -------------------------------------------
    # PENDING events whose settlement month is strictly earlier than the
    # clock's current calendar month settle to CLEARED with final net.
    cur_month = month_label(now)
    eligible = [e for e in db.store.revenue_events.values()
                if e["recognition_status"] == "PENDING"
                and e["settlement_month"] < cur_month]
    groups = {}
    for e in eligible:
        groups.setdefault((e["channel_id"], e["settlement_month"]), []).append(e)
    for (ch_id, _month), events in groups.items():
        month_gross = sum(e["gross_cents"] for e in events if e["kind"] != "CHARGEBACK")
        rebate = domain.VOLUME_REBATE_BPS if month_gross >= domain.VOLUME_REBATE_THRESHOLD_CENTS else 0
        for e in sorted(events, key=lambda x: (x["created_at"], x["_seq"])):
            effective_fee = e["platform_fee_bps"] - rebate
            e["net_cents"] = rhu(e["gross_cents"] * (10000 - effective_fee), 10000)
            e["recognition_status"] = "CLEARED"
            counters["events_cleared"] += 1

    # -- Step 2: strike expiry ----------------------------------------------
    # ISSUED/UPHELD past expires_at -> EXPIRED; UNDER_APPEAL is exempt (a
    # pending appeal tolls the window). Posture recomputed after each expiry;
    # a return to STANDARD releases POSTURE-held payouts.
    for s in sorted(db.store.strikes.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if s["strike_status"] in ("ISSUED", "UPHELD") and s["expires_at"] <= now:
            ch = domain.get_channel(s["channel_id"])
            old_posture = domain.monetization_posture(ch)
            s["strike_status"] = "EXPIRED"
            db.touch(s)
            counters["strikes_expired"] += 1
            domain.posture_cascade(ch, old_posture, cause="POSTURE")
            if domain.monetization_posture(ch) == "STANDARD":
                counters["payouts_released"] += domain.release_held_payouts(ch["id"], "POSTURE")

    # -- Step 3: tax-form expiry --------------------------------------------
    # VERIFIED forms past expires_on -> EXPIRED; posture recompute + hold
    # cascade (STANDARD -> RESTRICTED stamps TAX_FORM holds).
    for f in sorted(db.store.tax_forms.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if f["tax_status"] == "VERIFIED" and f["expires_on"] is not None \
                and f["expires_on"] <= now:
            ch = domain.get_channel(f["channel_id"])
            old_posture = domain.monetization_posture(ch)
            f["tax_status"] = "EXPIRED"
            db.touch(f)
            counters["tax_forms_expired"] += 1
            domain.posture_cascade(ch, old_posture, cause="TAX_FORM")

    # -- Step 4: simulcast-grant expiry --------------------------------------
    for g in sorted(db.store.grants.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if g["grant_status"] == "APPROVED" and g["window_end"] <= now:
            g["grant_status"] = "EXPIRED"
            db.touch(g)
            counters["grants_expired"] += 1

    # -- Step 5: stream no-shows ---------------------------------------------
    for st in sorted(db.store.streams.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if st["stream_status"] == "SCHEDULED" \
                and now > st["scheduled_start"] + timedelta(minutes=NO_SHOW_GRACE_MINUTES):
            st["stream_status"] = "NO_SHOW"
            db.touch(st)
            counters["streams_no_show"] += 1

    # -- Step 6: deliverable misses (+ forced MISSING disclosures) -----------
    for dv in sorted(db.store.deliverables.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if dv["performance_status"] == "SCHEDULED" and now > dv["due_at"]:
            dv["performance_status"] = "MISSED"
            db.touch(dv)
            counters["deliverables_missed"] += 1
            deal = db.store.deals.get(dv["deal_id"])
            if deal is not None:
                deal["miss_count"] += 1
                db.touch(deal)
                if deal["miss_count"] >= 3 and deal["deal_status"] == "ACTIVE":
                    breach_deal(deal)  # BREACHED + clawback CHARGEBACK event
        elif dv["performance_status"] == "PERFORMED" \
                and dv["disclosure_status"] == "PENDING" \
                and dv["performed_at"] is not None \
                and now > dv["performed_at"] + timedelta(hours=DISCLOSURE_MISSING_HOURS):
            dv["disclosure_status"] = "MISSING"
            db.touch(dv)

    # -- Step 7: perk expiry ---------------------------------------------------
    for g in sorted(db.store.perk_grants.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if g["perk_status"] in ("PENDING", "FAILED") and now > g["due_at"]:
            g["perk_status"] = "EXPIRED"
            db.touch(g)
            counters["perks_expired"] += 1

    # -- Step 8: subscription renewal and lapse --------------------------------
    renewing = [s for s in db.store.subscriptions.values()
                if s["sub_status"] == "ACTIVE" and s["current_period_end"] <= now]
    renewing.sort(key=lambda s: (s["current_period_end"], s["created_at"], s["_seq"]))
    for s in renewing:
        tier = db.store.tiers.get(s["tier_id"])
        viewer = db.store.viewers.get(s["viewer_id"])
        ch = domain.get_channel(s["channel_id"])
        if tier is None or viewer is None or ch is None:
            continue
        s["cycles_paid"] += 1
        s["current_period_end"] = _add_month(s["current_period_end"])
        db.touch(s)
        grant_cycle(ch, viewer, tier, s)  # revenue event + MERCH grant + spend
        counters["subscriptions_renewed"] += 1
    for s in sorted(db.store.subscriptions.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if s["sub_status"] == "PAST_DUE" \
                and now >= s["current_period_end"] + timedelta(days=PAST_DUE_GRACE_DAYS):
            s["sub_status"] = "EXPIRED"
            db.touch(s)
            domain.void_open_perks(s)
            counters["subscriptions_expired"] += 1

    # -- Step 9: deal completion ------------------------------------------------
    for d in sorted(db.store.deals.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if d["deal_status"] == "ACTIVE" \
                and domain.deal_verified_count(d["id"]) >= d["required_deliverable_count"] \
                and now >= d["flight_end"] \
                and domain.deal_disclosure_compliant(d["id"]):
            d["deal_status"] = "COMPLETED"
            db.touch(d)
            counters["deals_completed"] += 1

    # -- Step 10: moderation expiry ---------------------------------------------
    for a in sorted(db.store.mod_actions.values(), key=lambda x: (x["created_at"], x["_seq"])):
        if a["action_status"] == "ACTIVE" and a["action_kind"] == "TIMEOUT" \
                and a["expires_at"] is not None and a["expires_at"] <= now:
            viewer = db.store.viewers.get(a["viewer_id"])
            before = domain.viewer_standing(viewer) if viewer is not None else None
            a["action_status"] = "EXPIRED"
            db.touch(a)
            if viewer is not None:
                domain.recompute_standing_and_cascade(viewer, before)

    db.store.ops_run_index += 1
    result = {"ops_run_index": db.store.ops_run_index}
    result.update(counters)
    return ok_obj(result)


def _add_month(dt):
    from core import add_months
    return add_months(dt, 1)
