"""release_risk_eval: per-order projection, release projection, risk level,
and DelayNotice emission on worsening."""

from datetime import date, timedelta

import db
from .constants import (
    STAGE_LEAD, TP_REVISION_DELAY_DAYS, REPRESS_DELAY_DAYS,
    PRINT_TRANSIT_DAYS, BUFFER_DAYS, RISK_ORDER,
)

TERMINAL_ORDER_STATES = {"COMPLETED", "CANCELLED"}


def _parse(d):
    if isinstance(d, date):
        return d
    return date.fromisoformat(d)


def order_projected_completion(order):
    """Projected completion date for one order, or None if terminal."""
    if order["production_status"] in TERMINAL_ORDER_STATES:
        return None

    today = db.today_logical()
    status = order["production_status"]

    if status in ("SCHEDULED", "PRESSING", "QC_REVIEW") and _has_slots(order):
        # SCHEDULED or later: max(slot.date) + 1 day
        slot_dates = [
            _parse(s["date"])
            for s in db.press_slots.values()
            if s.get("press_order_id") == order["id"]
            and s["slot_kind"] == "PRODUCTION"
            and not s.get("freed", False)
        ]
        if slot_dates:
            press_projection = max(slot_dates) + timedelta(days=1)
        else:
            press_projection = today + timedelta(days=STAGE_LEAD.get(status, 21))
    elif status == "QUEUED":
        lead = STAGE_LEAD["QUEUED"]
        if order.get("repress_round", 0) >= 1:
            lead += REPRESS_DELAY_DAYS
        press_projection = today + timedelta(days=lead)
    elif status == "TOOLING":
        # TP revision rounds drive additional delay; tp_round counts produced
        # TPs, and revision rounds = number of revision loops entered.
        revision_count = order.get("_tp_revision_count", 0)
        press_projection = today + timedelta(
            days=STAGE_LEAD["TOOLING"] + TP_REVISION_DELAY_DAYS * revision_count
        )
    elif status in STAGE_LEAD:
        press_projection = today + timedelta(days=STAGE_LEAD[status])
    else:
        # DRAFT / QUOTED: no stage lead defined; treat as no projection
        return None

    # Print gate: max over non-CANCELLED print jobs of due_date + transit
    print_dates = []
    for pj in db.print_jobs.values():
        if pj["press_order_id"] == order["id"] and pj["status"] != "CANCELLED":
            print_dates.append(_parse(pj["due_date"]) + timedelta(days=PRINT_TRANSIT_DAYS))
    if print_dates:
        press_projection = max(press_projection, max(print_dates))

    return press_projection


def _has_slots(order):
    return any(
        s.get("press_order_id") == order["id"]
        and s["slot_kind"] == "PRODUCTION"
        and not s.get("freed", False)
        for s in db.press_slots.values()
    )


def compute_release_risk(release):
    """Compute (projected_completion_date, slack_days, risk_level) for a release."""
    today = db.today_logical()
    release_date = _parse(release["release_date"])

    projections = []
    for order in db.press_orders.values():
        if order["release_id"] == release["id"]:
            proj = order_projected_completion(order)
            if proj is not None:
                projections.append(proj)

    if not projections:
        projected = None
        slack = None
        level = "ON_TRACK"
    else:
        projected = max(projections)
        slack = (release_date - projected).days
        if slack >= BUFFER_DAYS:
            level = "ON_TRACK"
        elif slack >= 0:
            level = "AT_RISK"
        else:
            level = "LATE"

    return projected, slack, level


def recompute_release_risk(release, cause, triggering_order_id):
    """Recompute risk; append a DelayNotice iff the level strictly worsens.

    cause in {TP_REVISION, REPRESS, SCHEDULE, DATE_REVISION}.
    Mutates the release row (updated_at/version bump happens in caller context
    only when the release's own fields change; risk fields are computed views
    stored on the row)."""
    prior_level = release["risk_level"]
    projected, slack, level = compute_release_risk(release)

    release["projected_completion_date"] = projected.isoformat() if projected else None
    release["slack_days"] = slack
    release["risk_level"] = level

    if RISK_ORDER[level] > RISK_ORDER[prior_level]:
        notice = {
            "id": db.new_id(),
            "created_at": db.timestamp_now(),
            "release_id": release["id"],
            "press_order_id": triggering_order_id,
            "cause": cause,
            "prior_level": prior_level,
            "new_level": level,
            "message": (
                f"Release {release['id']} risk worsened from {prior_level} to "
                f"{level} (cause {cause}); projected completion "
                f"{release['projected_completion_date']} vs street date "
                f"{release['release_date']}."
            ),
        }
        db.delay_notices[notice["id"]] = notice
    return level
