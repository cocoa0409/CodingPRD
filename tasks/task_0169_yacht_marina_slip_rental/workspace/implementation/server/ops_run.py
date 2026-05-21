"""Operations sweep (§2.7, §3.7) — runs four housekeeping cascades atomically.

Order, per PRD §2.7:
  1. ops_run_index += 1.
  2. Expire ACTIVE policies whose expiration_date is reached or passed.
  3. Expire APPROVED reservations whose check_in_date is a full day+ in the past
     and which never checked in (decrement liveaboard count if applicable).
  4. Expire OFFERED slip transfer requests past their offer_expires_at.
  5. Run slip-match selector on QUEUED waitlist entries in sequence_no order.
  6. Expire QUEUED waitlist entries whose requested_check_out is reached/passed.

All operations are performed under `store.lock`.
"""
from __future__ import annotations

from datetime import timedelta

from .clock import iso_format, parse_iso, real_now
from .common import bump, stamp_new
from .marina_helpers import (
    half_open_overlap,
    recompute_liveaboard_count,
)
from .pricing import forward_looking_total
from .store import store


def run_ops(marina: dict) -> None:
    """Execute the ops sweep for a single marina. Caller holds store.lock."""
    marina["ops_run_index"] = int(marina.get("ops_run_index", 0)) + 1
    bump(marina)

    current = parse_iso(marina["current_date"])

    # 2. Expire policies.
    for policy in store.policies.values():
        if policy.get("marina_id") != marina["id"]:
            continue
        if policy.get("status") != "ACTIVE":
            continue
        try:
            exp = parse_iso(policy["expiration_date"])
        except (KeyError, ValueError):
            continue
        if current >= exp:
            policy["status"] = "EXPIRED"
            bump(policy)

    # 3. Expire APPROVED reservations whose check_in_date was a full day+ in the past
    #    and which never checked in.
    for res in list(store.reservations.values()):
        if res.get("marina_id") != marina["id"]:
            continue
        if res.get("status") != "APPROVED":
            continue
        try:
            check_in = parse_iso(res["check_in_date"])
        except (KeyError, ValueError):
            continue
        if current >= check_in + timedelta(days=1):
            res["status"] = "EXPIRED"
            bump(res)
            if res.get("liveaboard"):
                recompute_liveaboard_count(marina)
                bump(marina)

    # 4. Expire OFFERED transfer requests.
    for tr in store.transfer_requests.values():
        if tr.get("marina_id") != marina["id"]:
            continue
        if tr.get("status") != "OFFERED":
            continue
        try:
            exp_at = parse_iso(tr["offer_expires_at"])
        except (KeyError, ValueError):
            continue
        if current >= exp_at:
            tr["status"] = "EXPIRED"
            bump(tr)

    # 5. Slip-match selector — promote QUEUED waitlist entries.
    queued = [
        w
        for w in store.waitlist.values()
        if w.get("marina_id") == marina["id"] and w.get("status") == "QUEUED"
    ]
    queued.sort(key=lambda w: (int(w["sequence_no"]), w["id"]))
    for entry in queued:
        vessel = store.vessels.get(entry.get("vessel_id"))
        if not vessel:
            continue
        try:
            req_in = parse_iso(entry["requested_check_in"])
            req_out = parse_iso(entry["requested_check_out"])
        except (KeyError, ValueError):
            continue

        candidates = []
        for slip in store.slips.values():
            if slip.get("marina_id") != marina["id"]:
                continue
            if slip.get("status") != "AVAILABLE":
                continue
            if slip["length_feet"] < vessel["loa_feet"]:
                continue
            if slip["beam_feet"] - 2.0 < vessel["beam_feet"]:
                continue
            if slip["depth_feet"] < vessel["draft_feet"]:
                continue
            if entry.get("liveaboard"):
                if not slip.get("liveaboard_allowed"):
                    continue
                if int(marina.get("liveaboard_active_count", 0)) >= int(
                    marina.get("liveaboard_quota", 0)
                ):
                    continue
            # Overlap check inline so we don't pull marina_helpers cyclically
            blocked = False
            for r in store.reservations.values():
                if r.get("slip_id") != slip["id"]:
                    continue
                if r.get("status") not in ("APPROVED", "CHECKED_IN"):
                    continue
                try:
                    r_in = parse_iso(r["check_in_date"])
                    r_out = parse_iso(r["check_out_date"])
                except (KeyError, ValueError):
                    continue
                if half_open_overlap(req_in, req_out, r_in, r_out):
                    blocked = True
                    break
            if blocked:
                continue
            candidates.append(slip)

        if not candidates:
            continue

        candidates.sort(
            key=lambda s: (
                round(float(s["length_feet"]) - float(vessel["loa_feet"]), 6),
                round(float(s["beam_feet"]) - float(vessel["beam_feet"]), 6),
                round(float(s["depth_feet"]) - float(vessel["draft_feet"]), 6),
                str(s["code"]),
            )
        )
        chosen = candidates[0]

        # Create the new APPROVED reservation
        new_res = {
            "marina_id": marina["id"],
            "boater_id": entry["boater_id"],
            "vessel_id": entry["vessel_id"],
            "slip_id": chosen["id"],
            "check_in_date": entry["requested_check_in"],
            "check_out_date": entry["requested_check_out"],
            "liveaboard": bool(entry.get("liveaboard", False)),
            "insurance_policy_id": None,  # promoted reservation has no explicit policy ref
            "status": "APPROVED",
            "estimated_total_cents": forward_looking_total(
                base_daily_rate_cents=int(marina["base_daily_rate_cents"]),
                loa_feet=vessel["loa_feet"],
                flat_daily_charge_cents=int(chosen["flat_daily_charge_cents"]),
                liveaboard=bool(entry.get("liveaboard", False)),
                check_in_date=req_in,
                check_out_date=req_out,
            ),
            "final_total_cents": None,
            "nights": (req_out - req_in).days,
        }
        stamp_new(new_res)
        store.reservations[new_res["id"]] = new_res

        entry["status"] = "PROMOTED"
        entry["promoted_reservation_id"] = new_res["id"]
        # Append-only entry has no version/updated_at to bump.

        if entry.get("liveaboard"):
            recompute_liveaboard_count(marina)
            bump(marina)

    # 6. Expire QUEUED waitlist entries past requested_check_out.
    for entry in store.waitlist.values():
        if entry.get("marina_id") != marina["id"]:
            continue
        if entry.get("status") != "QUEUED":
            continue
        try:
            req_out = parse_iso(entry["requested_check_out"])
        except (KeyError, ValueError):
            continue
        if current >= req_out:
            entry["status"] = "EXPIRED"
