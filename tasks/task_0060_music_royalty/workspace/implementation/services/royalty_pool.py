"""RoyaltyPool service: open, patch, close (calculations), finalize, distribution listing, forfeit."""

from decimal import Decimal

from db import store
from errors import raise_err
from clock import clock
from util import (
    get_str, get_enum, get_int, get_number, parse_iso8601, round_half_up_cents,
    COUNTRY_RE,
)

REVENUE_SOURCES = {"STREAMING", "RADIO", "TV", "PUBLIC_VENUE", "LIVE", "SYNC", "MECHANICAL_LICENSE"}
CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY"}

# Channels (for distribution rule) -> compatible revenue_source values
# In our scaffold the two enums are aligned; a rule's channel must equal pool.revenue_source.


def serialize_pool(p: dict) -> dict:
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "period_start": p["period_start"],
        "period_end": p["period_end"],
        "revenue_source": p["revenue_source"],
        "region": p["region"],
        "gross_revenue_cents": p["gross_revenue_cents"],
        "platform_share_percent": float(p["platform_share_percent"]),
        "pool_currency": p["pool_currency"],
        "mechanical_split_percent": float(p["mechanical_split_percent"]),
        "net_distributable_cents": p.get("net_distributable_cents", 0),
        "mechanical_take_cents": p.get("mechanical_take_cents", 0),
        "performance_take_cents": p.get("performance_take_cents", 0),
        "platform_take_cents": p.get("platform_take_cents", 0),
        "admin_fee_cents": p.get("admin_fee_cents", 0),
        "status": p["status"],
        "distribution_rule_version_id": p.get("distribution_rule_version_id"),
        "closed_at": p.get("closed_at"),
    }


def serialize_distribution(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "royalty_pool_id": d["royalty_pool_id"],
        "work_id": d["work_id"],
        "rights_holder_id": d["rights_holder_id"],
        "rights_share_id": d["rights_share_id"],
        "sub_pool": d["sub_pool"],
        "gross_amount_cents": d["gross_amount_cents"],
        "commission_cents": d["commission_cents"],
        "net_after_commission_cents": d["net_after_commission_cents"],
        "status": d["status"],
    }


def create_pool(body: dict) -> dict:
    ps_str = get_str(body, "period_start")
    pe_str = get_str(body, "period_end")
    period_start = parse_iso8601(ps_str)
    period_end = parse_iso8601(pe_str)
    if period_end <= period_start:
        raise_err("ERR_VALIDATION", "period_end must be > period_start")
    revenue_source = get_enum(body, "revenue_source", REVENUE_SOURCES)
    region = get_str(body, "region", min_len=2, max_len=2)
    if region != "WW" and not COUNTRY_RE.match(region):
        raise_err("ERR_VALIDATION", "region must be 2 uppercase letters or WW")
    gross = get_int(body, "gross_revenue_cents", lo=0)
    platform_share = get_number(body, "platform_share_percent", lo=0.0, hi=40.0)
    pool_currency = get_enum(body, "pool_currency", CURRENCIES)
    mech_split = get_number(body, "mechanical_split_percent", lo=0.0, hi=100.0)
    drv_id = body.get("distribution_rule_version_id")

    with store.lock:
        if drv_id is not None and drv_id not in store.distribution_rule_versions:
            raise_err("ERR_NOT_FOUND", "DistributionRuleVersion not found")
        row = store.common_fields()
        row.update({
            "period_start": ps_str,
            "period_end": pe_str,
            "revenue_source": revenue_source,
            "region": region,
            "gross_revenue_cents": gross,
            "platform_share_percent": float(platform_share),
            "pool_currency": pool_currency,
            "mechanical_split_percent": float(mech_split),
            "net_distributable_cents": 0,
            "mechanical_take_cents": 0,
            "performance_take_cents": 0,
            "platform_take_cents": 0,
            "admin_fee_cents": 0,
            "status": "OPEN",
            "distribution_rule_version_id": drv_id,
            "closed_at": None,
        })
        store.royalty_pools[row["id"]] = row
    return serialize_pool(row)


def patch_pool(pool_id: str, body) -> dict:
    if not isinstance(body, dict):
        raise_err("ERR_VALIDATION", "body required")
    with store.lock:
        p = store.royalty_pools.get(pool_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Pool not found")
        if p["status"] != "OPEN":
            raise_err("ERR_INVALID_STATE", "Pool must be OPEN to patch")
        version_in = body.get("version")
        if version_in is not None and version_in != p["version"]:
            raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        if "gross_revenue_cents" in body and body["gross_revenue_cents"] is not None:
            g = body["gross_revenue_cents"]
            if isinstance(g, bool) or not isinstance(g, int) or g < 0:
                raise_err("ERR_VALIDATION", "gross_revenue_cents invalid")
            p["gross_revenue_cents"] = g
        if "distribution_rule_version_id" in body:
            drv_id = body["distribution_rule_version_id"]
            if drv_id is not None and drv_id not in store.distribution_rule_versions:
                raise_err("ERR_NOT_FOUND", "DistributionRuleVersion not found")
            p["distribution_rule_version_id"] = drv_id
        store.touch(p)
        return serialize_pool(p)


def _compute_admin_fee(gross_cents: int) -> int:
    # Tiers (half-open) on gross_revenue_cents:
    #   [0, 10_000_000) : 5.00% (TIER1)
    #   [10_000_000, 100_000_000) : 4.00% (TIER2) on portion above tier1 cap (10_000_000)
    #   [100_000_000, +inf) : 3.00% (TIER3) on portion above tier2 cap (100_000_000)
    # Round per-tier-slice FIRST (round_half_up), then sum.
    tier1_cap = 10_000_000
    tier2_cap = 100_000_000
    tier1_rate = Decimal("0.05")
    tier2_rate = Decimal("0.04")
    tier3_rate = Decimal("0.03")

    g = Decimal(gross_cents)
    if gross_cents < tier1_cap:
        slice1 = g
        slice2 = Decimal(0)
        slice3 = Decimal(0)
    elif gross_cents < tier2_cap:
        slice1 = Decimal(tier1_cap)
        slice2 = g - Decimal(tier1_cap)
        slice3 = Decimal(0)
    else:
        slice1 = Decimal(tier1_cap)
        slice2 = Decimal(tier2_cap) - Decimal(tier1_cap)
        slice3 = g - Decimal(tier2_cap)

    fee1 = round_half_up_cents(slice1 * tier1_rate)
    fee2 = round_half_up_cents(slice2 * tier2_rate)
    fee3 = round_half_up_cents(slice3 * tier3_rate)
    return fee1 + fee2 + fee3


def _classify_event(play_duration_seconds, work_duration, override_type=None):
    if override_type:
        return override_type
    if work_duration <= 0:
        return "FOREGROUND"
    ratio = float(play_duration_seconds) / float(work_duration)
    if ratio >= 0.95:
        return "FULL_PLAY"
    elif ratio < 0.30:
        return "SKIP"
    return "FOREGROUND"


def close_pool(pool_id: str, body) -> dict:
    """Close an OPEN pool. Computes net_distributable, admin fee, and creates Distribution rows.

    Pinned order:
      1. compute platform_take from gross
      2. compute admin_fee from gross
      3. net_distributable = gross - platform_take - admin_fee
      4. split into mechanical / performance (round mechanical FIRST)
      5. cascade Distribution creation
    """
    with store.lock:
        p = store.royalty_pools.get(pool_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Pool not found")

        # State: must be OPEN AND now >= period_end (validation #8).
        if p["status"] != "OPEN":
            raise_err("ERR_INVALID_STATE", "Pool not OPEN")
        now = clock.now()
        period_end = parse_iso8601(p["period_end"])
        if now < period_end:
            raise_err("ERR_INVALID_STATE", "now() < period_end")

        # OCC
        if isinstance(body, dict) and body.get("version") is not None:
            if body["version"] != p["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")

        # Rule version required.
        drv_id = p.get("distribution_rule_version_id")
        if not drv_id:
            raise_err("ERR_INVALID_STATE", "distribution_rule_version_id required")
        drv = store.distribution_rule_versions.get(drv_id)
        if not drv:
            raise_err("ERR_NOT_FOUND", "DistributionRuleVersion not found")
        if drv["channel"] != p["revenue_source"]:
            raise_err("ERR_INVALID_STATE", "Rule channel != pool revenue_source")
        # validation #18: drv.effective_from < pool.period_end (strict)
        if parse_iso8601(drv["effective_from"]) >= period_end:
            raise_err("ERR_RULE_NOT_EFFECTIVE", "Rule effective_from must be strictly < period_end")

        gross = p["gross_revenue_cents"]
        platform_share = Decimal(str(p["platform_share_percent"])) / Decimal("100")
        platform_take = round_half_up_cents(Decimal(gross) * platform_share)
        admin_fee = _compute_admin_fee(gross)
        net_distributable = gross - platform_take - admin_fee
        if net_distributable < 0:
            net_distributable = 0
        mech_split = Decimal(str(p["mechanical_split_percent"])) / Decimal("100")
        mechanical_take = round_half_up_cents(Decimal(net_distributable) * mech_split)
        performance_take = net_distributable - mechanical_take

        # Persist pool state.
        p["platform_take_cents"] = platform_take
        p["admin_fee_cents"] = admin_fee
        p["net_distributable_cents"] = net_distributable
        p["mechanical_take_cents"] = mechanical_take
        p["performance_take_cents"] = performance_take
        p["status"] = "CLOSED"
        p["closed_at"] = store.now_iso()
        store.touch(p)

        # Eligibility filter and per-work weighted unit computation.
        # Collect eligible events.
        period_start = parse_iso8601(p["period_start"])
        period_end_dt = period_end
        pool_region = p["region"]
        pool_channel = p["revenue_source"]

        # Map work_id -> list of (event_weight_score) for PER_PLAY, plus duration sums for PER_DURATION.
        from collections import defaultdict
        work_units = defaultdict(lambda: Decimal("0"))  # final units score
        # We compute by mode below.
        mode = drv["distribution_mode"]
        ptw_map = drv["playback_type_weights"]
        per_play_w = Decimal(str(drv["per_play_weight"])) if drv.get("per_play_weight") is not None else Decimal("0")
        per_dur_w = Decimal(str(drv["per_duration_weight"])) if drv.get("per_duration_weight") is not None else Decimal("0")

        # Per-work aggregations
        work_event_weights = defaultdict(list)  # per event playback_type_weight
        work_duration_weighted = defaultdict(lambda: Decimal("0"))  # sum(duration * weight)
        work_event_count = defaultdict(int)

        # Build the playback-source-channel map (for "PlaybackEvent's source channel" filter).
        # The batch carries the channel; we map event -> batch -> channel.
        for ev in store.playback_events.values():
            if ev["status"] not in ("ACCEPTED", "SUPPLEMENTED"):
                continue
            batch = store.playback_batches.get(ev["playback_batch_id"])
            if not batch or batch["validity_status"] != "VALID":
                continue
            if batch["channel"] != pool_channel:
                continue
            # Region match
            if pool_region != "WW" and ev["region"] != pool_region:
                continue
            played_at = parse_iso8601(ev["played_at"]) if ev.get("played_at") else None
            if played_at is None:
                continue
            if not (period_start <= played_at < period_end_dt):
                continue
            w = store.works.get(ev.get("work_id"))
            if not w or w["registration_status"] != "APPROVED":
                continue
            # Compute event type weight
            ptype = ev.get("playback_type")
            if not ptype:
                ptype = _classify_event(ev["play_duration_seconds"], w["duration_seconds"])
            weight = Decimal(str(ptw_map.get(ptype, 1.0)))
            work_event_weights[w["id"]].append(weight)
            work_duration_weighted[w["id"]] += Decimal(ev["play_duration_seconds"]) * weight
            work_event_count[w["id"]] += 1

        # Compute units(work) per mode.
        eligible_work_ids = list(work_event_weights.keys())
        for wid in eligible_work_ids:
            weights_list = work_event_weights[wid]
            n = len(weights_list)
            avg_weight = sum(weights_list, Decimal("0")) / Decimal(n) if n else Decimal("0")
            count_weighted = sum(weights_list, Decimal("0"))  # sum of per-event weights
            dur_weighted = work_duration_weighted[wid]
            if mode == "PER_PLAY":
                work_units[wid] = Decimal(n) * avg_weight  # equivalent to sum of weights
            elif mode == "PER_DURATION":
                work_units[wid] = dur_weighted
            else:  # HYBRID
                work_units[wid] = per_play_w * count_weighted + per_dur_w * dur_weighted

        # Split eligible works into sub-pools by rights_type.
        mech_works = []
        perf_works = []
        for wid in eligible_work_ids:
            w = store.works.get(wid)
            if not w:
                continue
            if w["rights_type"] in ("COMPOSITION", "LYRICS"):
                mech_works.append(wid)
            else:
                perf_works.append(wid)

        def _allocate_subpool(work_ids, sub_pool_amount):
            """Return dict work_id -> allocated cents, summing to sub_pool_amount."""
            if not work_ids or sub_pool_amount <= 0:
                return {wid: 0 for wid in work_ids}
            total_units = sum((work_units[wid] for wid in work_ids), Decimal("0"))
            if total_units == 0:
                return {wid: 0 for wid in work_ids}
            allocs = {}
            for wid in work_ids:
                u = work_units[wid]
                alloc = round_half_up_cents(Decimal(sub_pool_amount) * u / total_units)
                allocs[wid] = alloc
            # Residual lodged with highest-units work; ties broken by lowest lexicographic Work.id.
            residual = sub_pool_amount - sum(allocs.values())
            if residual != 0:
                # Determine highest-units work
                sorted_works = sorted(work_ids, key=lambda x: (-work_units[x], x))
                target = sorted_works[0]
                allocs[target] += residual
            return allocs

        mech_allocs = _allocate_subpool(mech_works, mechanical_take)
        perf_allocs = _allocate_subpool(perf_works, performance_take)

        # Per-share allocation per work
        def _allocate_per_share(work_id, work_cents):
            shares = [s for s in store.rights_shares.values()
                      if s["work_id"] == work_id and s["share_status"] == "ACTIVE"]
            if not shares:
                return []
            allocs = []
            for s in shares:
                alloc = round_half_up_cents(Decimal(work_cents) * Decimal(str(s["share_percent"])) / Decimal("100"))
                allocs.append((s, alloc))
            total = sum(a for _, a in allocs)
            residual = work_cents - total
            if residual != 0:
                # Residual lodged with the share whose share_percent is highest; ties => lowest share id.
                allocs.sort(key=lambda x: (-Decimal(str(x[0]["share_percent"])), x[0]["id"]))
                first_share, first_alloc = allocs[0]
                allocs[0] = (first_share, first_alloc + residual)
            return allocs

        # Create Distribution rows.
        for wid in eligible_work_ids:
            w = store.works.get(wid)
            sub_pool = "MECHANICAL" if w["rights_type"] in ("COMPOSITION", "LYRICS") else "PERFORMANCE"
            work_cents = mech_allocs.get(wid, 0) if sub_pool == "MECHANICAL" else perf_allocs.get(wid, 0)
            share_allocs = _allocate_per_share(wid, work_cents)
            for share, gross_amount in share_allocs:
                # Commission
                commission = 0
                binding_id = share.get("agency_binding_id")
                if binding_id:
                    binding = store.agency_bindings.get(binding_id)
                    if binding and binding["status"] == "ACTIVE":
                        from services.agency_binding import binding_active_at
                        if binding_active_at(binding, now):
                            # Also enforce territory rule (WW or pool.region)
                            if binding["territory"] == "WW" or binding["territory"] == pool_region:
                                cp = Decimal(str(binding["commission_percent"]))
                                commission = round_half_up_cents(Decimal(gross_amount) * cp / Decimal("100"))
                net_after = gross_amount - commission

                # Initial status PENDING; if work dispute_posture == FROZEN, immediately FROZEN.
                init_status = "FROZEN" if w.get("dispute_posture") == "FROZEN" else "PENDING"
                d = store.common_fields()
                d.update({
                    "royalty_pool_id": pool_id,
                    "work_id": wid,
                    "rights_holder_id": share["rights_holder_id"],
                    "rights_share_id": share["id"],
                    "sub_pool": sub_pool,
                    "gross_amount_cents": gross_amount,
                    "commission_cents": commission,
                    "net_after_commission_cents": net_after,
                    "status": init_status,
                })
                store.distributions[d["id"]] = d

        return serialize_pool(p)


def finalize_pool(pool_id: str, body) -> dict:
    with store.lock:
        p = store.royalty_pools.get(pool_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Pool not found")
        if p["status"] != "CLOSED":
            raise_err("ERR_INVALID_STATE", "Pool must be CLOSED")
        # No FROZEN distributions allowed.
        for d in store.distributions.values():
            if d["royalty_pool_id"] == pool_id and d["status"] == "FROZEN":
                raise_err("ERR_POOL_HAS_FROZEN_DISTRIBUTIONS", "Frozen distributions exist")
        if isinstance(body, dict) and body.get("version") is not None:
            if body["version"] != p["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        # Flip all PENDING distributions to RELEASED.
        for d in store.distributions.values():
            if d["royalty_pool_id"] == pool_id and d["status"] == "PENDING":
                d["status"] = "RELEASED"
                store.touch(d)
        p["status"] = "DISTRIBUTED"
        store.touch(p)
        return serialize_pool(p)


def get_pool(pool_id: str) -> dict:
    with store.lock:
        p = store.royalty_pools.get(pool_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Pool not found")
        return serialize_pool(p)


def list_distributions(pool_id: str, args):
    from util import parse_pagination
    limit, offset = parse_pagination(args)
    status = args.get("status")
    work_id = args.get("work_id")
    rights_holder_id = args.get("rights_holder_id")
    with store.lock:
        p = store.royalty_pools.get(pool_id)
        if not p:
            raise_err("ERR_NOT_FOUND", "Pool not found")
        rows = [d for d in store.distributions.values() if d["royalty_pool_id"] == pool_id]
        if status:
            rows = [d for d in rows if d["status"] == status]
        if work_id:
            rows = [d for d in rows if d["work_id"] == work_id]
        if rights_holder_id:
            rows = [d for d in rows if d["rights_holder_id"] == rights_holder_id]
        # RightsHolder caller may only see their own distributions.
        from middleware import current_role, current_user_id
        if current_role() == "RightsHolder":
            rows = [d for d in rows if d["rights_holder_id"] == current_user_id()]
        rows.sort(key=lambda r: r["created_at"])
        total = len(rows)
        page = rows[offset:offset + limit]
        return [serialize_distribution(d) for d in page], total, limit, offset


def forfeit_distribution(distribution_id: str, body) -> dict:
    with store.lock:
        d = store.distributions.get(distribution_id)
        if not d:
            raise_err("ERR_NOT_FOUND", "Distribution not found")
        if d["status"] != "RELEASED":
            raise_err("ERR_INVALID_STATE", "Distribution must be RELEASED to forfeit")
        # Gating: holder must have payment FAILED/ABANDONED or token revoked.
        holder = store.rights_holders.get(d["rights_holder_id"])
        token_revoked = holder.get("bank_account_revoked", False) if holder else False
        has_failed_payment = any(
            pay["rights_holder_id"] == d["rights_holder_id"]
            and pay["status"] in ("FAILED", "ABANDONED")
            for pay in store.payments.values()
        )
        if not (token_revoked or has_failed_payment):
            raise_err("ERR_DISTRIBUTION_NOT_FORFEITABLE", "Forfeit gating failed")
        if isinstance(body, dict) and body.get("version") is not None:
            if body["version"] != d["version"]:
                raise_err("ERR_VERSION_CONFLICT", "Version conflict")
        d["status"] = "FORFEITED"
        store.touch(d)
        # Reabsorb into parent pool's net_distributable_cents.
        p = store.royalty_pools.get(d["royalty_pool_id"])
        if p:
            p["net_distributable_cents"] = p.get("net_distributable_cents", 0) + d["gross_amount_cents"]
            store.touch(p)
        return serialize_distribution(d)
