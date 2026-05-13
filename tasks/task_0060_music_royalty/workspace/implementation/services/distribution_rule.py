"""DistributionRuleVersion service."""

from decimal import Decimal

from db import store
from errors import raise_err
from util import (
    get_str, get_enum, get_int, get_number, parse_iso8601,
)

CHANNELS = {"STREAMING", "RADIO", "TV", "PUBLIC_VENUE", "LIVE", "SYNC", "MECHANICAL_LICENSE"}
MODES = {"PER_PLAY", "PER_DURATION", "HYBRID"}
PLAYBACK_TYPES = {"FULL_PLAY", "SKIP", "BACKGROUND", "FOREGROUND"}


def serialize(r: dict) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "version_tag": r["version_tag"],
        "channel": r["channel"],
        "distribution_mode": r["distribution_mode"],
        "per_play_weight": float(r["per_play_weight"]) if r.get("per_play_weight") is not None else None,
        "per_duration_weight": float(r["per_duration_weight"]) if r.get("per_duration_weight") is not None else None,
        "playback_type_weights": r["playback_type_weights"],
        "minimum_payout_cents": r["minimum_payout_cents"],
        "micro_accumulation_cap_cents": r["micro_accumulation_cap_cents"],
        "effective_from": r["effective_from"],
    }


def create_rule(body: dict) -> dict:
    version_tag = get_str(body, "version_tag", min_len=1, max_len=32)
    channel = get_enum(body, "channel", CHANNELS)
    mode = get_enum(body, "distribution_mode", MODES)
    ppw = body.get("per_play_weight")
    pdw = body.get("per_duration_weight")
    if mode in ("PER_PLAY", "HYBRID"):
        if ppw is None:
            raise_err("ERR_VALIDATION", "per_play_weight required")
        if not (0.0 <= float(ppw) <= 1.0):
            raise_err("ERR_VALIDATION", "per_play_weight out of range")
    else:
        ppw = None
    if mode in ("PER_DURATION", "HYBRID"):
        if pdw is None:
            raise_err("ERR_VALIDATION", "per_duration_weight required")
        if not (0.0 <= float(pdw) <= 1.0):
            raise_err("ERR_VALIDATION", "per_duration_weight out of range")
    else:
        pdw = None

    if mode == "HYBRID":
        s = Decimal(str(ppw)) + Decimal(str(pdw))
        if s != Decimal("1") and s != Decimal("1.00"):
            if abs(float(s) - 1.0) > 1e-9:
                raise_err("ERR_RULE_WEIGHTS_INVALID", "per_play_weight + per_duration_weight must equal 1.00")

    ptw = body.get("playback_type_weights")
    if not isinstance(ptw, dict):
        raise_err("ERR_VALIDATION", "playback_type_weights must be object")
    for k in PLAYBACK_TYPES:
        if k not in ptw:
            raise_err("ERR_VALIDATION", f"playback_type_weights missing key {k}")
        v = ptw[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0.0 <= float(v) <= 2.0):
            raise_err("ERR_VALIDATION", f"playback_type_weights[{k}] out of range")

    minimum_payout_cents = get_int(body, "minimum_payout_cents", lo=0)
    micro_cap = get_int(body, "micro_accumulation_cap_cents", lo=0)
    if micro_cap < minimum_payout_cents:
        raise_err("ERR_VALIDATION", "micro_accumulation_cap_cents must be >= minimum_payout_cents")
    effective_from_str = get_str(body, "effective_from")
    parse_iso8601(effective_from_str)

    with store.lock:
        # Uniqueness on version_tag
        for r in store.distribution_rule_versions.values():
            if r["version_tag"] == version_tag:
                raise_err("ERR_VALIDATION", "Duplicate version_tag")
        row = store.lean_fields()
        row.update({
            "version_tag": version_tag,
            "channel": channel,
            "distribution_mode": mode,
            "per_play_weight": float(ppw) if ppw is not None else None,
            "per_duration_weight": float(pdw) if pdw is not None else None,
            "playback_type_weights": ptw,
            "minimum_payout_cents": minimum_payout_cents,
            "micro_accumulation_cap_cents": micro_cap,
            "effective_from": effective_from_str,
        })
        store.distribution_rule_versions[row["id"]] = row
    return serialize(row)


def list_rules(args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    channel = args.get("channel")
    with store.lock:
        rows = list(store.distribution_rule_versions.values())
    if channel:
        rows = [r for r in rows if r["channel"] == channel]
    rows.sort(key=lambda r: r["created_at"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serialize(r) for r in page], total, limit, offset
