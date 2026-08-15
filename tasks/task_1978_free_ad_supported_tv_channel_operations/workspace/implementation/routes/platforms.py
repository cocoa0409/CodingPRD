"""Distributor platforms and distribution agreements."""

from db import store, new_id, next_seq, now_str, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_REFERENCE_NOT_FOUND,
    ERR_AGREEMENT_WINDOW_OVERLAP,
    ERR_REV_SHARE_OUT_OF_RANGE,
)
from middleware import caller, require_roles, body, ROLE_PLATFORM_ADMIN
from response import created, ok, paginate
from serializers import ser_platform, ser_agreement
from services.core import get_or_404
from util import req_str, req_enum, req_int, opt_int, req_date
from flask import Blueprint, request

bp = Blueprint("platforms", __name__)

PA = [ROLE_PLATFORM_ADMIN]

PLATFORM_TRANSITIONS = {
    ("ONBOARDING", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ONBOARDING", "OFFBOARDED"),
    ("ACTIVE", "OFFBOARDED"),
    ("SUSPENDED", "OFFBOARDED"),
}

AGREEMENT_TRANSITIONS = {
    ("NEGOTIATION", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("NEGOTIATION", "TERMINATED"),
    ("ACTIVE", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}

RATE_FIELDS = (
    "rev_share_bps_below",
    "rev_share_bps_above",
    "tier_threshold_cents",
    "minimum_guarantee_cents",
)


def _create_record(fields):
    ts = now_str()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}
    rec.update(fields)
    return rec


# ---------------------------------------------------------------------------
# Platforms
# ---------------------------------------------------------------------------

@bp.route("/v1/distributor-platforms", methods=["POST"])
def create_platform():
    _, role = caller()
    b = body()
    name = req_str(b, "name")
    tier = req_enum(b, "reporting_tier", ("STANDARD", "PREMIUM"))
    require_roles(role, PA)
    rec = _create_record(
        {"name": name, "reporting_tier": tier, "platform_status": "ONBOARDING"}
    )
    store.distributor_platforms[rec["id"]] = rec
    return created(ser_platform(rec))


@bp.route("/v1/distributor-platforms", methods=["GET"])
def list_platforms():
    caller()
    recs = list(store.distributor_platforms.values())
    fs = request.args.get("platform_status")
    if fs is not None:
        recs = [r for r in recs if r["platform_status"] == fs]
    return paginate(recs, ser_platform)


@bp.route("/v1/distributor-platforms/<platform_id>", methods=["GET"])
def get_platform(platform_id):
    caller()
    rec = get_or_404(store.distributor_platforms, platform_id, "DistributorPlatform")
    return ok(ser_platform(rec))


@bp.route("/v1/distributor-platforms/<platform_id>", methods=["PATCH"])
def patch_platform(platform_id):
    _, role = caller()
    b = body()
    target = b.get("target_status")
    if not isinstance(target, str) or target not in ("ACTIVE", "SUSPENDED", "OFFBOARDED"):
        raise_err(ERR_INVALID_REQUEST, "target_status must be one of ACTIVE, SUSPENDED, OFFBOARDED")
    require_roles(role, PA)
    rec = get_or_404(store.distributor_platforms, platform_id, "DistributorPlatform")
    if (rec["platform_status"], target) not in PLATFORM_TRANSITIONS:
        raise_err(
            ERR_INVALID_STATE_TRANSITION,
            "Platform in %s cannot transition to %s" % (rec["platform_status"], target),
        )
    rec["platform_status"] = target
    touch(rec)
    if target == "OFFBOARDED":
        for agr in store.distribution_agreements.values():
            if agr["platform_id"] == rec["id"] and agr["agreement_status"] in (
                "NEGOTIATION",
                "ACTIVE",
                "SUSPENDED",
            ):
                agr["agreement_status"] = "TERMINATED"
                touch(agr)
    return ok(ser_platform(rec))


# ---------------------------------------------------------------------------
# Distribution agreements
# ---------------------------------------------------------------------------

def _validate_bps(value, field):
    if value < 0 or value > 6000:
        raise_err(ERR_REV_SHARE_OUT_OF_RANGE, "%s must be within 0..6000 basis points" % field)


@bp.route("/v1/distribution-agreements", methods=["POST"])
def create_agreement():
    _, role = caller()
    b = body()
    channel_id = req_str(b, "channel_id")
    platform_id = req_str(b, "platform_id")
    bps_below = req_int(b, "rev_share_bps_below")
    _validate_bps(bps_below, "rev_share_bps_below")
    bps_above = req_int(b, "rev_share_bps_above")
    _validate_bps(bps_above, "rev_share_bps_above")
    threshold = req_int(b, "tier_threshold_cents")
    if threshold < 0:
        raise_err(ERR_INVALID_REQUEST, "tier_threshold_cents must be >= 0")
    mg = opt_int(b, "minimum_guarantee_cents")
    if mg is None:
        mg = 0
    elif mg < 0:
        raise_err(ERR_INVALID_REQUEST, "minimum_guarantee_cents must be >= 0")
    eff_start = req_date(b, "effective_start_date")
    eff_end = req_date(b, "effective_end_date")
    if eff_end < eff_start:
        raise_err(ERR_INVALID_REQUEST, "effective_end_date must not precede effective_start_date")
    require_roles(role, PA)
    if channel_id not in store.channels:
        raise_err(ERR_REFERENCE_NOT_FOUND, "channel_id does not reference an existing channel")
    if platform_id not in store.distributor_platforms:
        raise_err(ERR_REFERENCE_NOT_FOUND, "platform_id does not reference an existing platform")
    # Closed-interval overlap per (channel, platform) among non-terminal
    # agreements; adjacency counts as overlap.
    for a in store.distribution_agreements.values():
        if (
            a["channel_id"] == channel_id
            and a["platform_id"] == platform_id
            and a["agreement_status"] in ("NEGOTIATION", "ACTIVE", "SUSPENDED")
            and eff_start <= a["_eff_end"]
            and a["_eff_start"] <= eff_end
        ):
            raise_err(
                ERR_AGREEMENT_WINDOW_OVERLAP,
                "Window overlaps a NEGOTIATION/ACTIVE/SUSPENDED agreement for the same (channel, platform)",
            )
    rec = _create_record(
        {
            "channel_id": channel_id,
            "platform_id": platform_id,
            "rev_share_bps_below": bps_below,
            "rev_share_bps_above": bps_above,
            "tier_threshold_cents": threshold,
            "minimum_guarantee_cents": mg,
            "effective_start_date": eff_start.isoformat(),
            "effective_end_date": eff_end.isoformat(),
            "agreement_status": "NEGOTIATION",
            "locked_rev_share_bps_below": None,
            "locked_rev_share_bps_above": None,
            "locked_tier_threshold_cents": None,
            "locked_minimum_guarantee_cents": None,
            "_eff_start": eff_start,
            "_eff_end": eff_end,
        }
    )
    store.distribution_agreements[rec["id"]] = rec
    return created(ser_agreement(rec))


@bp.route("/v1/distribution-agreements", methods=["GET"])
def list_agreements():
    caller()
    recs = list(store.distribution_agreements.values())
    fc = request.args.get("channel_id")
    fp = request.args.get("platform_id")
    fs = request.args.get("agreement_status")
    if fc is not None:
        recs = [r for r in recs if r["channel_id"] == fc]
    if fp is not None:
        recs = [r for r in recs if r["platform_id"] == fp]
    if fs is not None:
        recs = [r for r in recs if r["agreement_status"] == fs]
    return paginate(recs, ser_agreement)


@bp.route("/v1/distribution-agreements/<agreement_id>", methods=["GET"])
def get_agreement(agreement_id):
    caller()
    rec = get_or_404(store.distribution_agreements, agreement_id, "DistributionAgreement")
    return ok(ser_agreement(rec))


@bp.route("/v1/distribution-agreements/<agreement_id>", methods=["PATCH"])
def patch_agreement(agreement_id):
    _, role = caller()
    b = body()
    target = b.get("target_status")
    if target is not None and (
        not isinstance(target, str) or target not in ("ACTIVE", "SUSPENDED", "TERMINATED")
    ):
        raise_err(ERR_INVALID_REQUEST, "target_status must be one of ACTIVE, SUSPENDED, TERMINATED")
    rate_updates = {}
    for f in RATE_FIELDS:
        if f in b and b[f] is not None:
            v = b[f]
            if not isinstance(v, int) or isinstance(v, bool):
                raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % f)
            if f in ("rev_share_bps_below", "rev_share_bps_above"):
                _validate_bps(v, f)
            elif v < 0:
                raise_err(ERR_INVALID_REQUEST, "%s must be >= 0" % f)
            rate_updates[f] = v
    if target is None and not rate_updates:
        raise_err(ERR_INVALID_REQUEST, "Nothing to update")
    require_roles(role, PA)
    rec = get_or_404(store.distribution_agreements, agreement_id, "DistributionAgreement")
    # Rate fields are editable only while NEGOTIATION.
    if rate_updates:
        if rec["agreement_status"] != "NEGOTIATION":
            raise_err(
                ERR_INVALID_STATE_TRANSITION,
                "Rate fields are editable only while the agreement is NEGOTIATION",
            )
        for f, v in rate_updates.items():
            rec[f] = v
        touch(rec)
    if target is not None:
        current = rec["agreement_status"]
        if (current, target) not in AGREEMENT_TRANSITIONS:
            raise_err(
                ERR_INVALID_STATE_TRANSITION,
                "Agreement in %s cannot transition to %s" % (current, target),
            )
        if target == "ACTIVE":
            platform = store.distributor_platforms.get(rec["platform_id"])
            if platform is None or platform["platform_status"] != "ACTIVE":
                raise_err(ERR_INVALID_STATE_TRANSITION, "Platform must be ACTIVE to activate the agreement")
            channel = store.channels.get(rec["channel_id"])
            if channel is not None and channel["channel_status"] == "ARCHIVED":
                raise_err(ERR_INVALID_STATE_TRANSITION, "Channel is ARCHIVED")
            if current == "NEGOTIATION":
                # First activation pins the locked rate snapshot from the
                # current values; re-activation deliberately keeps the pinned
                # snapshot.
                rec["locked_rev_share_bps_below"] = rec["rev_share_bps_below"]
                rec["locked_rev_share_bps_above"] = rec["rev_share_bps_above"]
                rec["locked_tier_threshold_cents"] = rec["tier_threshold_cents"]
                rec["locked_minimum_guarantee_cents"] = rec["minimum_guarantee_cents"]
        rec["agreement_status"] = target
        touch(rec)
    return ok(ser_agreement(rec))
