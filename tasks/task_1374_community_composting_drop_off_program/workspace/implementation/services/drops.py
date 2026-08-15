"""DropEvent business logic: credits, rejection, batch reconciliation."""

import math
from decimal import Decimal, ROUND_HALF_UP

import db
from services import credits
from services.programs import touch, site_posture_touch
from services import posture as posture_svc


def serialize_drop(d):
    return {
        "id": d["id"],
        "site_id": d["site_id"],
        "participant_id": d["participant_id"],
        "access_grant_id": d["access_grant_id"],
        "material_category_id": d["material_category_id"],
        "gross_weight_kg": d["gross_weight_kg"],
        "contamination_kg": d["contamination_kg"],
        "provisional_net_kg": d["provisional_net_kg"],
        "final_net_kg": d["final_net_kg"],
        "credit_state": d["credit_state"],
        "verification_state": d["verification_state"],
        "processing_batch_id": d["processing_batch_id"],
        "occurred_at": db.fmt_ts(d["occurred_at"]),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def grant_provisional_credits(drop):
    """Grant provisional credits per PENDING_AUDIT -> ACCEPTED transition."""
    site = db.sites[drop["site_id"]]
    program = db.programs[site["program_id"]]
    rate = Decimal(str(program["diversion_credit_rate"]))
    amount = int(
        (Decimal(str(drop["provisional_net_kg"])) * rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    credits.record_grant(
        drop["participant_id"],
        amount,
        drop["occurred_at"],
        db.parse_dt(drop["created_at"]),
        drop["id"],
    )
    drop["credit_state"] = "PROVISIONALLY_CREDITED"


def accept_drop(drop):
    """Move a PENDING_AUDIT or FLAGGED_CONTAMINATED drop to ACCEPTED with
    credit side effects."""
    drop["verification_state"] = "ACCEPTED"
    if drop["credit_state"] == "UNCREDITED":
        grant_provisional_credits(drop)
    touch(drop)


def reject_drop(drop):
    """Move a drop to REJECTED: subtract provisional mass from site, revoke
    credit state, reverse any granted credits."""
    site = db.sites[drop["site_id"]]
    drop["verification_state"] = "REJECTED"
    # If credits were provisionally granted, reverse them
    if drop["credit_state"] in ("PROVISIONALLY_CREDITED", "FINALLY_CREDITED"):
        program = db.programs[site["program_id"]]
        rate = Decimal(str(program["diversion_credit_rate"]))
        amount = int(
            (Decimal(str(drop["provisional_net_kg"])) * rate).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
        if amount:
            credits.record_grant(
                drop["participant_id"],
                -amount,
                drop["occurred_at"],
                db.parse_dt(drop["created_at"]),
                drop["id"],
            )
    drop["credit_state"] = "REVOKED"
    site["stored_kg"] = db.round_kg(float(site["stored_kg"]) - float(drop["provisional_net_kg"]))
    touch(drop)
    site_posture_touch(site)


def reconcile_batch_accepted(batch):
    """On CLOSED_ACCEPTED: distribute measured_net_kg across ACCEPTED drops
    whose site was served by a COLLECTED stop on the batch's route
    (largest-remainder rounding at 0.01 kg)."""
    route = db.routes.get(batch["route_id"])
    if not route:
        return
    collected_site_ids = {
        s["site_id"]
        for s in db.stops.values()
        if s["route_id"] == route["id"] and s["status"] == "COLLECTED"
    }
    drops = [
        d
        for d in db.drops.values()
        if d["site_id"] in collected_site_ids
        and d["verification_state"] == "ACCEPTED"
        and d.get("processing_batch_id") is None
    ]
    measured_net = Decimal(str(batch["measured_net_kg"]))

    weights = [Decimal(str(d["provisional_net_kg"])) for d in drops]
    total_w = sum(weights)

    if not drops:
        return

    if total_w == 0:
        for d in drops:
            d["final_net_kg"] = 0.0
            _finalize_drop_credit(d, batch)
        return

    raws = [measured_net * w / total_w for w in weights]
    floors = [(r * 100).to_integral_value(rounding="ROUND_FLOOR") / 100 for r in raws]
    measured_units = int((measured_net * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    floor_units_sum = sum(int(f * 100) for f in floors)
    remainder_units = measured_units - floor_units_sum

    order = sorted(
        range(len(drops)),
        key=lambda i: (
            -(raws[i] - floors[i]),
            drops[i]["occurred_at"],
            drops[i]["created_at"],
        ),
    )
    finals = list(floors)
    idx = 0
    remaining = remainder_units
    while remaining > 0 and order:
        i = order[idx % len(order)]
        finals[i] = finals[i] + Decimal("0.01")
        remaining -= 1
        idx += 1

    for d, f in zip(drops, finals):
        d["final_net_kg"] = float(f.quantize(Decimal("0.01")))
        _finalize_drop_credit(d, batch)

    # Update site stored_kg: provisional mass was counted; now replace with
    # final mass for these drops.
    for d in drops:
        site = db.sites[d["site_id"]]
        delta = float(d["final_net_kg"]) - float(d["provisional_net_kg"])
        if delta != 0:
            site["stored_kg"] = db.round_kg(float(site["stored_kg"]) + delta)
            site_posture_touch(site)


def _finalize_drop_credit(drop, batch):
    """Apply credit delta (final vs provisional roundings) and set fields."""
    site = db.sites[drop["site_id"]]
    program = db.programs[site["program_id"]]
    rate = Decimal(str(program["diversion_credit_rate"]))
    final_credits = int(
        (Decimal(str(drop["final_net_kg"])) * rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    prov_credits = int(
        (Decimal(str(drop["provisional_net_kg"])) * rate).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    delta = final_credits - prov_credits
    if delta != 0:
        credits.record_grant(
            drop["participant_id"],
            delta,
            drop["occurred_at"],
            db.parse_dt(drop["created_at"]),
            drop["id"],
        )
    drop["credit_state"] = "FINALLY_CREDITED"
    drop["processing_batch_id"] = batch["id"]
    touch(drop)


def reconcile_batch_rejected(batch):
    """On CLOSED_REJECTED: flag every drop linked to stops on this route with
    an auto-created OPEN MAJOR ContaminationReport; reverse provisional
    credits."""
    route = db.routes.get(batch["route_id"])
    if not route:
        return
    collected_site_ids = {
        s["site_id"]
        for s in db.stops.values()
        if s["route_id"] == route["id"] and s["status"] == "COLLECTED"
    }
    drops = [
        d
        for d in db.drops.values()
        if d["site_id"] in collected_site_ids
        and d["verification_state"] in ("ACCEPTED", "PENDING_AUDIT", "FLAGGED_CONTAMINATED")
        and d.get("processing_batch_id") is None
    ]
    for d in drops:
        # Reverse provisional credits if granted
        if d["credit_state"] == "PROVISIONALLY_CREDITED":
            site = db.sites[d["site_id"]]
            program = db.programs[site["program_id"]]
            rate = Decimal(str(program["diversion_credit_rate"]))
            amount = int(
                (Decimal(str(d["provisional_net_kg"])) * rate).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            if amount:
                credits.record_grant(
                    d["participant_id"],
                    -amount,
                    d["occurred_at"],
                    db.parse_dt(d["created_at"]),
                    d["id"],
                )
        d["credit_state"] = "UNCREDITED"
        d["verification_state"] = "FLAGGED_CONTAMINATED"
        d["processing_batch_id"] = batch["id"]
        touch(d)
        report = {
            "id": db.new_id(),
            "site_id": d["site_id"],
            "drop_event_id": d["id"],
            "auditor_id": "system",
            "severity": "MAJOR",
            "finding_note": "Auto-opened: processing batch rejected for contamination",
            "feedback_sent_at": None,
            "status": "OPEN",
            "created_at": db.iso_now(),
            "updated_at": db.iso_now(),
            "version": 1,
        }
        db.contamination_reports[report["id"]] = report
        site = db.sites[d["site_id"]]
        site_posture_touch(site)
