"""Fill decisions: decision runs, mark-aired, reconcile, manual voids."""

from db import store, now_str, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_BREAK_VERSION,
)
from middleware import (
    caller,
    require_roles,
    body,
    ROLE_CHANNEL_PROGRAMMER,
    ROLE_AD_OPS,
)
from response import ok, ok_array, paginate
from serializers import ser_decision, ser_break
from services.core import (
    get_or_404,
    break_decisions,
    recompute_break_fill,
    void_decision,
    ensure_posture_not_frozen,
    ensure_loop_ops_allowed,
    maybe_exhaust_campaign,
    maybe_revive_campaign,
)
from services.selector import run_selector
from util import rhu_div, is_int
from flask import Blueprint, request

bp = Blueprint("decisions", __name__)


@bp.route("/v1/ad-breaks/<break_id>/decision-runs", methods=["POST"])
def decision_run(break_id):
    _, role = caller()
    b = body()
    expected_version = b.get("expected_break_version")
    if not is_int(expected_version):
        raise_err(ERR_INVALID_REQUEST, "expected_break_version is required and must be an integer")
    require_roles(role, [ROLE_AD_OPS])
    br = get_or_404(store.ad_breaks, break_id, "AdBreak")
    loop = store.playlist_loops[br["loop_id"]]
    channel = store.channels[loop["channel_id"]]
    # Tier 7: state guards.
    ensure_posture_not_frozen(channel)
    ensure_loop_ops_allowed(channel)
    if loop["loop_status"] not in ("VALIDATED", "LOCKED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Decision runs require the parent loop to be VALIDATED or LOCKED",
        )
    if br["break_status"] not in ("MARKED", "DECIDED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Decision runs are not permitted on a %s break" % br["break_status"],
        )
    # Tier 8: OCC on the break.
    if expected_version != br["version"]:
        raise_err(ERR_STALE_BREAK_VERSION, "expected_break_version does not match the break's current version")
    # Re-decision compensation: void existing PROVISIONAL decisions first
    # (break bump suppressed — the run as a whole bumps the break once).
    for d in break_decisions(br["id"]):
        if d["decision_status"] == "PROVISIONAL":
            void_decision(d, touch_break=False)
    placed = run_selector(br)
    br["break_status"] = "DECIDED"
    recompute_break_fill(br, touch_break=False, collapse=False)
    touch(br)
    return ok_array([ser_decision(d) for d in placed], status=201)


@bp.route("/v1/ad-breaks/<break_id>/mark-aired", methods=["POST"])
def mark_aired(break_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_CHANNEL_PROGRAMMER])
    br = get_or_404(store.ad_breaks, break_id, "AdBreak")
    loop = store.playlist_loops[br["loop_id"]]
    if br["break_status"] != "DECIDED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only a DECIDED break can be marked aired")
    if loop["loop_status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Mark-aired requires the parent loop to be PUBLISHED")
    br["break_status"] = "AIRED"
    touch(br)
    return ok(ser_break(br))


@bp.route("/v1/ad-breaks/<break_id>/reconcile", methods=["POST"])
def reconcile(break_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_AD_OPS])
    br = get_or_404(store.ad_breaks, break_id, "AdBreak")
    if br["break_status"] != "AIRED":
        raise_err(ERR_INVALID_STATE_TRANSITION, "Only an AIRED break can be reconciled")
    for d in break_decisions(br["id"]):
        if d["decision_status"] != "COMMITTED":
            continue
        actual = sum(
            e["quantity"]
            for e in store.viewership_events.values()
            if e["event_type"] == "AD_IMPRESSION" and e["decision_id"] == d["id"]
        )
        d["actual_impressions"] = actual
        if d["fill_type"] == "DIRECT":
            campaign = store.ad_campaigns.get(d["campaign_id"])
            cpm = campaign["cpm_cents"] if campaign is not None else 0
            reconciled_cost = rhu_div(cpm * actual, 1000)
            d["reconciled_cost_cents"] = reconciled_cost
            d["decision_status"] = "RECONCILED"
            touch(d)
            if campaign is not None:
                campaign["spent_cents"] = max(
                    0, campaign["spent_cents"] + (reconciled_cost - d["committed_cost_cents"])
                )
                touch(campaign)
                maybe_exhaust_campaign(campaign)
                maybe_revive_campaign(campaign)
        else:
            d["reconciled_cost_cents"] = 0
            d["decision_status"] = "RECONCILED"
            touch(d)
    br["break_status"] = "RECONCILED"
    touch(br)
    recompute_break_fill(br)
    return ok(ser_break(br))


@bp.route("/v1/fill-decisions", methods=["GET"])
def list_decisions():
    caller()
    recs = list(store.fill_decisions.values())
    fb = request.args.get("break_id")
    fc = request.args.get("campaign_id")
    fcr = request.args.get("creative_id")
    fh = request.args.get("house_ad_id")
    fs = request.args.get("decision_status")
    ft = request.args.get("fill_type")
    if fb is not None:
        recs = [r for r in recs if r["break_id"] == fb]
    if fc is not None:
        recs = [r for r in recs if r["campaign_id"] == fc]
    if fcr is not None:
        recs = [r for r in recs if r["creative_id"] == fcr]
    if fh is not None:
        recs = [r for r in recs if r["house_ad_id"] == fh]
    if fs is not None:
        recs = [r for r in recs if r["decision_status"] == fs]
    if ft is not None:
        recs = [r for r in recs if r["fill_type"] == ft]
    return paginate(recs, ser_decision)


@bp.route("/v1/fill-decisions/<decision_id>", methods=["GET"])
def get_decision(decision_id):
    caller()
    rec = get_or_404(store.fill_decisions, decision_id, "FillDecision")
    return ok(ser_decision(rec))


@bp.route("/v1/fill-decisions/<decision_id>/void", methods=["POST"])
def void(decision_id):
    _, role = caller()
    body()
    require_roles(role, [ROLE_AD_OPS])
    rec = get_or_404(store.fill_decisions, decision_id, "FillDecision")
    if rec["decision_status"] not in ("PROVISIONAL", "COMMITTED"):
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Only a PROVISIONAL or COMMITTED decision can be voided",
        )
    void_decision(rec)
    return ok(ser_decision(rec))
