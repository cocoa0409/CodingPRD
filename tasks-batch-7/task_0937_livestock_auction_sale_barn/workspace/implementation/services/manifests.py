"""Trailer totals, the haul charge and its proration (PRD 3.9)."""
import config
from money import D, q2
from store import db, touch


def manifest_lines(manifest_id):
    return sorted([l for l in db["load_lines"].values()
                   if l["load_manifest_id"] == manifest_id],
                  key=lambda l: (l["created_at"], l["_seq"]))


def haul_charge(manifest):
    if manifest["loaded_head"] == 0:
        return q2(0)
    if manifest["haul_basis"] == "PER_MILE":
        raw = q2(config.HAUL_RATE_PER_LOADED_MILE * D(manifest["loaded_miles"]))
        return raw if raw > config.MIN_HAUL_CHARGE else config.MIN_HAUL_CHARGE
    return q2(config.HAUL_RATE_PER_HEAD * D(manifest["loaded_head"]))


def recompute_manifest(manifest):
    """Totals, haul charge and every line's prorated share, with the rounding
    residual absorbed by the line with the EARLIEST created_at."""
    lines = manifest_lines(manifest["id"])
    manifest["loaded_head"] = sum(l["head"] for l in lines)
    manifest["loaded_weight_lb"] = q2(sum(D(l["weight_lb"]) for l in lines)) \
        if lines else D(0)
    manifest["haul_charge"] = haul_charge(manifest)
    prorate(manifest, lines)
    touch(manifest)
    return manifest


def prorate(manifest, lines):
    if not lines:
        return
    charge = D(manifest["haul_charge"])
    if manifest["proration_basis"] == "BY_WEIGHT":
        total = D(manifest["loaded_weight_lb"])
        basis = [D(l["weight_lb"]) for l in lines]
    else:
        total = D(manifest["loaded_head"])
        basis = [D(l["head"]) for l in lines]
    if total == 0:
        for line in lines:
            line["prorated_haul_amount"] = q2(0)
        return
    running = D(0)
    for line, share_basis in zip(lines, basis):
        share = q2(charge * share_basis / total)
        line["prorated_haul_amount"] = share
        running += share
    residual = q2(charge - running)
    if residual != 0:
        lines[0]["prorated_haul_amount"] = q2(
            D(lines[0]["prorated_haul_amount"]) + residual)
