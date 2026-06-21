"""Temperature excursion accumulation and the quarantine cascade (PRD 3.11).

Readings are processed strictly in chronological order by reading_utc, ties
broken by created_at (insertion sequence). Because a reading can arrive with an
earlier reading_utc than ones already stored, the unit's posture is recomputed
from the full ordered stream on every new reading.
"""
from db import db
from services.common import touch, parse_dt
from services.calculations import EXCURSION_LIMIT_MINUTES


def recompute_unit(unit):
    """Replay all temp logs for the unit in chronological order to derive
    compliance_status and excursion_minutes, then cascade quarantine to its
    ACTIVE assignments if the unit crosses the threshold.

    Quarantine, once reached by the replay, is sticky: only a ComplianceOfficer
    certify-compliant clears it. So if the unit is already QUARANTINED we do not
    auto-recover it here.
    """
    logs = [t for t in db.temp_logs.values() if t["storage_unit_id"] == unit["id"]]
    logs.sort(key=lambda t: (parse_dt(t["reading_utc"]), t["_seq"]))

    temp_min = unit["temp_min_c"]
    temp_max = unit["temp_max_c"]

    status = "COMPLIANT"
    excursion = 0
    prev_oor_dt = None
    quarantined = False

    for log in logs:
        in_range = temp_min <= log["reading_c"] <= temp_max
        log["in_range"] = in_range
        if quarantined:
            # Once quarantined during the replay it stays quarantined; later
            # readings still record in_range but do not auto-clear it.
            continue
        if in_range:
            excursion = 0
            prev_oor_dt = None
            if status == "EXCURSION":
                status = "COMPLIANT"
        else:
            cur_dt = parse_dt(log["reading_utc"])
            if status == "COMPLIANT":
                status = "EXCURSION"
                excursion = 0
            else:  # already EXCURSION
                gap = (cur_dt - prev_oor_dt).total_seconds() / 60.0
                excursion += int(round(gap))
            prev_oor_dt = cur_dt
            if excursion > EXCURSION_LIMIT_MINUTES:
                status = "QUARANTINED"
                quarantined = True

    # Preserve an existing QUARANTINED posture set on a prior call.
    if unit["compliance_status"] == "QUARANTINED" and not quarantined:
        return

    changed = (
        unit["compliance_status"] != status
        or unit["excursion_minutes"] != excursion
    )
    unit["compliance_status"] = status
    unit["excursion_minutes"] = excursion
    if changed:
        touch(unit)

    if status == "QUARANTINED":
        _cascade_quarantine(unit)


def _cascade_quarantine(unit):
    """Every ACTIVE storage assignment whose allocation_plan touches this unit
    is moved to QUARANTINED with its slots held (not freed)."""
    for asn in db.storage_assignments.values():
        if asn["status"] != "ACTIVE":
            continue
        touched = any(entry["storage_unit_id"] == unit["id"]
                      for entry in asn["allocation_plan"])
        if touched:
            asn["status"] = "QUARANTINED"
            touch(asn)
