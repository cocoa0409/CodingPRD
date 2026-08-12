"""Time impact analysis and concurrent-delay apportionment (PRD §3.5).

Prospective (FRAGNET_INSERTION): the fragnet activities already belong to the
target UPDATE version, so "insertion" is measured as the difference between
the full network's projected finish and the projected finish of the network
with the fragnet activities (and their ties) removed:
    prolongation = projected_finish(full) - projected_finish(without fragnet)

Retrospective (TIME_SLICE_WINDOWS): with no as-built delay attribution data
recorded per window in this system, the forensic total equals the prospective
prolongation (the fragnet's critical-chain delay under the current network).

Apportionment: waterfall over the prospective prolongation using, for
concurrency, the whole-calendar-day overlap between this event's window and
other recorded delay events on the same project (null end = ongoing, bounded
by the server logical clock).
"""

from db import store
from middleware import touch
from routes.common import activities_of, relationships_of, delay_events_of
from services.cpm import compute_cpm
from util import parse_dt, clock_now


def _window(event):
    start = parse_dt(event["event_start_date"], "event_start_date")
    if event.get("event_end_date"):
        end = parse_dt(event["event_end_date"], "event_end_date")
    else:
        end = clock_now()
    return start, end


def _overlap_days(a_start, a_end, b_start, b_end):
    lo = max(a_start, b_start)
    hi = min(a_end, b_end)
    d = (hi - lo).days
    return d if d > 0 else 0


def run_tia(event):
    """Compute and persist tia_prolongation_days_* on the event."""
    version = store.schedule_versions[event["fragnet_inserted_into_version_id"]]
    acts = activities_of(version["id"])
    rels = relationships_of(version["id"])
    data_date = parse_dt(version["data_date"], "data_date")

    if version.get("projected_finish_date"):
        full_finish = parse_dt(version["projected_finish_date"],
                               "projected_finish_date")
    else:
        _, full_finish, _ = compute_cpm(acts, rels, data_date)

    frag = set(event.get("fragnet_activity_ids") or [])
    reduced_acts = [a for a in acts if a["id"] not in frag]
    reduced_rels = [r for r in rels
                    if r["predecessor_activity_id"] not in frag
                    and r["successor_activity_id"] not in frag]
    if reduced_acts:
        _, reduced_finish, _ = compute_cpm(reduced_acts, reduced_rels,
                                           data_date)
    else:
        reduced_finish = data_date

    prospective = (full_finish - reduced_finish).days
    if prospective < 0:
        prospective = 0
    event["tia_prolongation_days_prospective"] = prospective
    event["tia_prolongation_days_retrospective"] = prospective
    touch(event)


def run_apportionment(event):
    """Concurrent-delay waterfall over the prospective prolongation."""
    project = store.projects[event["project_id"]]
    p = event["tia_prolongation_days_prospective"] or 0

    start, end = _window(event)
    contractor_concurrent = 0
    owner_concurrent = 0
    for other in delay_events_of(project["id"]):
        if other["id"] == event["id"]:
            continue
        o_start, o_end = _window(other)
        ov = _overlap_days(start, end, o_start, o_end)
        if ov <= 0:
            continue
        if other["causation"] == "CONTRACTOR_CAUSED":
            contractor_concurrent += ov
        elif other["causation"] == "OWNER_CAUSED":
            owner_concurrent += ov

    # 1. contractor-caused concurrent delay allocated first, floored at 0.
    non_excusable = max(0, contractor_concurrent)
    # 2. residual prolongation
    residual = p - non_excusable
    causation = event["causation"]
    within = bool(event.get("notice_within_window"))
    if causation == "OWNER_CAUSED" and within:
        if owner_concurrent > 0:
            compensable = min(residual, owner_concurrent)
        else:
            compensable = residual
        compensable = max(0, compensable)
        excusable_nc = max(0, residual - compensable)
    elif causation == "FORCE_MAJEURE" or (causation == "OWNER_CAUSED"
                                          and not within):
        compensable = 0
        excusable_nc = max(0, residual)
    else:  # CONTRACTOR_CAUSED, THIRD_PARTY
        compensable = 0
        excusable_nc = 0
        non_excusable = p
    # Float-ownership doctrine (§2.10): with no measurable float-consumption
    # record in this system the OWNER_OWNS / SHARED_FIRST_COME adjustments
    # reduce to zero consumed float; CONTRACTOR_OWNS requires no adjustment.
    event["apportioned_compensable_days"] = compensable
    event["apportioned_excusable_non_compensable_days"] = excusable_nc
    event["apportioned_non_excusable_days"] = non_excusable
    touch(event)


def clear_tia_fields(event):
    """TIA_REJECTED -> NOTICED resubmit side effect."""
    event["tia_prolongation_days_prospective"] = None
    event["tia_prolongation_days_retrospective"] = None
    event["apportioned_compensable_days"] = None
    event["apportioned_excusable_non_compensable_days"] = None
    event["apportioned_non_excusable_days"] = None
    touch(event)
