"""Delivery acceptance (over_quota_split + pool tagging + provisional advance)
and void compensation. Each tagged pool's totals move by that pool's portion;
every pool/quota mutation bumps that resource's version."""
from decimal import Decimal

from db import store, touch
from errors import ApiError
from services import quota as quota_service
from validation import round2, to_decimal

ZERO = Decimal("0")


def find_open_pool(season_id, code):
    for p in store.pools.values():
        if p["season_id"] == season_id and p["code"] == code and p["status"] == "OPEN":
            return p
    return None


def accept_delivery(delivery):
    season = store.seasons.get(delivery["season_id"])
    if season is None or season["status"] != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", 409, "Season is not OPEN")

    main_pool = find_open_pool(delivery["season_id"], "MAIN")
    if main_pool is None:
        raise ApiError("ERR_POOL_NOT_OPEN", 409, "The season's MAIN pool is not OPEN")

    quota = quota_service.find_quota(delivery["member_id"], delivery["season_id"])
    if quota is not None:
        base = to_decimal(quota["base_quota_barrels"])
        delivered = to_decimal(quota["delivered_barrels"])
    else:
        base = ZERO
        delivered = ZERO

    # over_quota_split: boundary is inclusive — landing exactly on the quota
    # leaves over_quota_barrels == 0 (>= semantics, not >).
    net = to_decimal(delivery["net_barrels"])
    remaining = max(ZERO, base - delivered)
    quota_applied = min(net, remaining)
    over = net - quota_applied

    over_pool = None
    if over > ZERO:
        over_pool = find_open_pool(delivery["season_id"], "OVER_QUOTA")
        if over_pool is None:
            raise ApiError("ERR_OVER_QUOTA_POOL_UNAVAILABLE", 409,
                           "No OPEN OVER_QUOTA pool exists for the season")

    # Weighted portions split pro-rata by barrels; the remainder belongs to
    # the over-quota portion so the two shares always sum to weighted_barrels.
    weighted = to_decimal(delivery["weighted_barrels"])
    if over > ZERO and net > ZERO:
        main_weighted = round2(weighted * quota_applied / net)
        over_weighted = weighted - main_weighted
    else:
        main_weighted = weighted
        over_weighted = ZERO

    # Provisional advance: two independently rounded terms at each pool's rate.
    main_advance = round2(main_weighted * to_decimal(main_pool["provisional_advance_rate_per_barrel"]))
    if over_pool is not None:
        over_advance = round2(over_weighted * to_decimal(over_pool["provisional_advance_rate_per_barrel"]))
    else:
        over_advance = ZERO

    delivery["quota_applied_barrels"] = quota_applied
    delivery["over_quota_barrels"] = over
    delivery["main_pool_id"] = main_pool["id"]
    delivery["over_quota_pool_id"] = over_pool["id"] if over_pool is not None else None
    delivery["advance_amount"] = main_advance + over_advance
    # Recorded per-pool contributions (used by void compensation and settlement).
    delivery["_main_net"] = quota_applied
    delivery["_main_weighted"] = main_weighted
    delivery["_main_advance"] = main_advance
    delivery["_over_net"] = over if over_pool is not None else ZERO
    delivery["_over_weighted"] = over_weighted
    delivery["_over_advance"] = over_advance

    if quota is not None:
        quota["delivered_barrels"] = delivered + quota_applied
        quota["over_quota_barrels"] = to_decimal(quota["over_quota_barrels"]) + over
        quota["posture"] = quota_service.posture_of(quota)
        touch(quota)

    main_pool["accepted_net_barrels"] = to_decimal(main_pool["accepted_net_barrels"]) + quota_applied
    main_pool["weighted_barrels_total"] = to_decimal(main_pool["weighted_barrels_total"]) + main_weighted
    main_pool["advances_outstanding"] = to_decimal(main_pool["advances_outstanding"]) + main_advance
    touch(main_pool)

    if over_pool is not None:
        over_pool["accepted_net_barrels"] = to_decimal(over_pool["accepted_net_barrels"]) + over
        over_pool["weighted_barrels_total"] = to_decimal(over_pool["weighted_barrels_total"]) + over_weighted
        over_pool["advances_outstanding"] = to_decimal(over_pool["advances_outstanding"]) + over_advance
        touch(over_pool)

    delivery["status"] = "ACCEPTED"
    touch(delivery)


def void_delivery(delivery):
    """Exact mirror of acceptance: subtract precisely the recorded contributions."""
    tagged = [p for p in (delivery.get("main_pool_id"), delivery.get("over_quota_pool_id")) if p]
    pools = []
    for pid in tagged:
        pool = store.pools.get(pid)
        if pool is not None:
            pools.append(pool)
    # Check ALL preconditions before committing ANY change.
    for pool in pools:
        if pool["status"] != "OPEN":
            raise ApiError("ERR_POOL_NOT_OPEN", 409, "A tagged pool is not OPEN")

    quota = quota_service.find_quota(delivery["member_id"], delivery["season_id"])
    if quota is not None:
        quota["delivered_barrels"] = (to_decimal(quota["delivered_barrels"])
                                      - to_decimal(delivery["quota_applied_barrels"]))
        quota["over_quota_barrels"] = (to_decimal(quota["over_quota_barrels"])
                                       - to_decimal(delivery["over_quota_barrels"]))
        quota["posture"] = quota_service.posture_of(quota)
        touch(quota)

    main_pool = store.pools.get(delivery.get("main_pool_id") or "")
    if main_pool is not None:
        main_pool["accepted_net_barrels"] = (to_decimal(main_pool["accepted_net_barrels"])
                                             - to_decimal(delivery.get("_main_net", ZERO)))
        main_pool["weighted_barrels_total"] = (to_decimal(main_pool["weighted_barrels_total"])
                                               - to_decimal(delivery.get("_main_weighted", ZERO)))
        main_pool["advances_outstanding"] = (to_decimal(main_pool["advances_outstanding"])
                                             - to_decimal(delivery.get("_main_advance", ZERO)))
        touch(main_pool)

    if delivery.get("over_quota_pool_id"):
        over_pool = store.pools.get(delivery["over_quota_pool_id"])
        if over_pool is not None:
            over_pool["accepted_net_barrels"] = (to_decimal(over_pool["accepted_net_barrels"])
                                                 - to_decimal(delivery.get("_over_net", ZERO)))
            over_pool["weighted_barrels_total"] = (to_decimal(over_pool["weighted_barrels_total"])
                                                   - to_decimal(delivery.get("_over_weighted", ZERO)))
            over_pool["advances_outstanding"] = (to_decimal(over_pool["advances_outstanding"])
                                                 - to_decimal(delivery.get("_over_advance", ZERO)))
            touch(over_pool)

    delivery["status"] = "VOIDED"
    touch(delivery)
