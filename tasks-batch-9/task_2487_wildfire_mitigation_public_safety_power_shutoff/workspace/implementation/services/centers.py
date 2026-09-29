"""Community resource centre activation (C10)."""

from datetime import timedelta

import clock
import db
from errors import ApiError
from services import calc, events


def scoped_districts(event):
    districts = set()
    for scope in events.confirmed_scopes(event):
        circuit = db.circuits.get(scope["circuit_id"])
        if circuit is not None:
            districts.add(circuit["district_code"])
    return districts


def buffer_conflict(center, event):
    last = center.get("last_served_all_clear_at")
    if last is None:
        return False
    edge = last + timedelta(minutes=calc.CRC_RESET_BUFFER_MINUTES)
    return event["forecast_onset_at"] < edge


def activate(event, requested_ids):
    districts = scoped_districts(event)
    required = int(event["crc_capacity_required"])

    if requested_ids is not None:
        named = [db.resource_centers[center_id] for center_id in requested_ids]
        # The §2.8 priority order decides between competing breaches:
        # own state (8) before interval occupation (16) before ceilings (17).
        for center in named:
            if center["status"] == "ACTIVATED":
                raise ApiError(
                    "ERR_RESOURCE_CENTER_ALREADY_ACTIVE",
                    "Resource center %s is already activated." % center["resource_center_code"],
                )
        for center in named:
            if buffer_conflict(center, event):
                raise ApiError(
                    "ERR_RESOURCE_CENTER_BUFFER_CONFLICT",
                    "Resource center %s is still inside its reset buffer."
                    % center["resource_center_code"],
                )
        for center in named:
            if center["district_code"] not in districts:
                raise ApiError(
                    "ERR_RESOURCE_CENTER_DISTRICT_MISMATCH",
                    "Resource center %s is outside the scoped districts."
                    % center["resource_center_code"],
                )
        chosen = list(enumerate(named, start=1))
    else:
        candidates = [
            c
            for c in db.resource_centers.values()
            if c["status"] in ("STANDBY", "DEMOBILIZED")
            and c["district_code"] in districts
            and not buffer_conflict(c, event)
        ]
        candidates.sort(
            key=lambda c: (
                0 if c["accessibility_certified"] else 1,
                -int(c["site_capacity"]),
                c["created_at"],
                c["_seq"],
            )
        )
        if not candidates and required > 0:
            raise ApiError(
                "ERR_NO_ELIGIBLE_RESOURCE_CENTER",
                "No eligible community resource center is available for this event.",
            )
        chosen = []
        cumulative = 0
        position = 0
        for center in candidates:
            if cumulative >= required:
                break
            position += 1
            chosen.append((position, center))
            cumulative += int(center["site_capacity"])

    activated_capacity = 0
    activated_ids = []
    stamp = clock.now()
    for position, center in chosen:
        if center["id"] in activated_ids:
            continue
        center["status"] = "ACTIVATED"
        center["psps_event_id"] = event["id"]
        db.set_dt(center, "activated_at", stamp)
        center["activation_order"] = position
        db.set_dt(
            center,
            "last_served_all_clear_at",
            event["forecast_all_clear_at"],
            event.get("_raw", {}).get("forecast_all_clear_at"),
        )
        db.touch(center)
        activated_capacity += int(center["site_capacity"])
        activated_ids.append(center["id"])

    events.recompute_crc_capacity_served(event)
    events.recompute_net_benefit(event)
    db.touch(event)

    unmet = max(0, required - int(event["crc_capacity_served"]))
    return {
        "activated_count": len(activated_ids),
        "activated_capacity": activated_capacity,
        "unmet_capacity": unmet,
        "activated_resource_center_ids": activated_ids,
    }
