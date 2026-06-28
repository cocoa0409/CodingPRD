"""Entity -> response-dict serializers.

Computed fields (source: computed) are derived at read time where they depend on
clock position (is_traceable, is_accreditation_current, traceability_depth) or on
child rows (counts). System/input/stored fields are passed through.
"""
from calculations import MAX_DEPTH
from db import db


# ---------------------------------------------------------------------------
# CalibrationStandard
# ---------------------------------------------------------------------------
def _standard_chain(standard):
    """Return the list of standards from leaf up to anchor, or raise on cycle.

    Used for traceability_depth and is_traceable. Returns (chain, cyclic_bool).
    """
    chain = []
    seen = set()
    cur = standard
    while cur is not None:
        if cur["id"] in seen:
            return chain, True
        seen.add(cur["id"])
        chain.append(cur)
        parent_id = cur.get("parent_standard_id")
        if not parent_id:
            break
        cur = db.calibration_standards.get(parent_id)
        if cur is None:
            # Broken link; treat as end of resolvable chain.
            break
    return chain, False


def standard_traceability_depth(standard):
    chain, cyclic = _standard_chain(standard)
    if cyclic:
        return None
    # depth = number of hops to the anchor = len(chain) - 1
    return len(chain) - 1


def standard_is_traceable(standard):
    chain, cyclic = _standard_chain(standard)
    if cyclic:
        return False
    current_epoch = db.clock["current_epoch"]
    # The anchor (last in chain) must have null parent to be a real anchor.
    last = chain[-1]
    if last.get("parent_standard_id"):
        # Chain ends because of a broken parent link, not a real anchor.
        return False
    for s in chain:
        if s["status"] != "ACTIVE":
            return False
        if s["certified_through_epoch"] < current_epoch:
            return False
    return True


def serialize_standard(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "name": s["name"],
        "nist_test_number": s["nist_test_number"],
        "parent_standard_id": s.get("parent_standard_id"),
        "nominal_value": s["nominal_value"],
        "standard_unit": s["standard_unit"],
        "uncertainty": s["uncertainty"],
        "certified_through_epoch": s["certified_through_epoch"],
        "traceability_depth": standard_traceability_depth(s),
        "is_traceable": standard_is_traceable(s),
        "status": s["status"],
    }


# ---------------------------------------------------------------------------
# CalibrationVendor
# ---------------------------------------------------------------------------
def vendor_is_accreditation_current(v):
    if v["accreditation_body"] == "NONE":
        return False
    return v["accredited_through_epoch"] >= db.clock["current_epoch"]


def serialize_vendor(v):
    return {
        "id": v["id"],
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
        "name": v["name"],
        "accreditation_body": v["accreditation_body"],
        "accreditation_number": v.get("accreditation_number"),
        "accredited_through_epoch": v["accredited_through_epoch"],
        "is_accreditation_current": vendor_is_accreditation_current(v),
        "status": v["status"],
    }


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------
def instrument_open_oot_count(inst):
    return sum(
        1 for i in db.impacts.values()
        if i["instrument_id"] == inst["id"]
        and i["status"] not in ("DISPOSITIONED", "CANCELLED")
    )


def serialize_instrument(inst):
    return {
        "id": inst["id"],
        "created_at": inst["created_at"],
        "updated_at": inst["updated_at"],
        "version": inst["version"],
        "asset_tag": inst["asset_tag"],
        "description": inst["description"],
        "nominal_value": inst["nominal_value"],
        "tolerance_plus": inst["tolerance_plus"],
        "tolerance_minus": inst["tolerance_minus"],
        "measurement_unit": inst["measurement_unit"],
        "calibration_interval_epochs": inst["calibration_interval_epochs"],
        "criticality": inst["criticality"],
        "last_calibration_epoch": inst.get("last_calibration_epoch"),
        "next_due_epoch": inst.get("next_due_epoch"),
        "lifecycle_status": inst["lifecycle_status"],
        "calibration_status": inst["calibration_status"],
        "open_oot_count": inst.get("open_oot_count", 0),
    }


# ---------------------------------------------------------------------------
# CalibrationEvent
# ---------------------------------------------------------------------------
def serialize_event(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
        "instrument_id": e["instrument_id"],
        "standard_id": e["standard_id"],
        "vendor_id": e.get("vendor_id"),
        "performed_by_user_id": e["performed_by_user_id"],
        "scheduled_epoch": e["scheduled_epoch"],
        "result": e.get("result"),
        "as_found_in_tolerance": e.get("as_found_in_tolerance"),
        "as_left_in_tolerance": e.get("as_left_in_tolerance"),
        "max_abs_deviation": e.get("max_abs_deviation"),
        "tur": e.get("tur"),
        "status": e["status"],
    }


# ---------------------------------------------------------------------------
# MeasurementPoint
# ---------------------------------------------------------------------------
def serialize_point(p):
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "calibration_event_id": p["calibration_event_id"],
        "point_label": p["point_label"],
        "nominal": p["nominal"],
        "tol_plus": p["tol_plus"],
        "tol_minus": p["tol_minus"],
        "as_found_value": p["as_found_value"],
        "as_left_value": p["as_left_value"],
        "as_found_pass": p["as_found_pass"],
        "as_left_pass": p["as_left_pass"],
    }


# ---------------------------------------------------------------------------
# CalibrationCertificate
# ---------------------------------------------------------------------------
def serialize_certificate(c):
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "calibration_event_id": c["calibration_event_id"],
        "vendor_id": c["vendor_id"],
        "certificate_number": c["certificate_number"],
        "issued_epoch": c["issued_epoch"],
        "status": c["status"],
    }


# ---------------------------------------------------------------------------
# OutOfToleranceImpact
# ---------------------------------------------------------------------------
def impact_affected_product_count(impact):
    return sum(1 for ap in db.affected_products.values()
               if ap["impact_id"] == impact["id"])


def impact_recalled_product_count(impact):
    return sum(1 for ap in db.affected_products.values()
               if ap["impact_id"] == impact["id"] and ap["status"] == "RECALLED")


def serialize_impact(i):
    return {
        "id": i["id"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
        "instrument_id": i["instrument_id"],
        "triggering_event_id": i["triggering_event_id"],
        "prior_calibration_epoch": i.get("prior_calibration_epoch"),
        "suspect_window_start_epoch": i["suspect_window_start_epoch"],
        "suspect_window_end_epoch": i["suspect_window_end_epoch"],
        "dispositioned_by_user_id": i.get("dispositioned_by_user_id"),
        "disposition": i.get("disposition"),
        "affected_product_count": impact_affected_product_count(i),
        "recalled_product_count": impact_recalled_product_count(i),
        "status": i["status"],
    }


# ---------------------------------------------------------------------------
# AffectedProduct
# ---------------------------------------------------------------------------
def serialize_affected_product(ap):
    return {
        "id": ap["id"],
        "created_at": ap["created_at"],
        "updated_at": ap["updated_at"],
        "version": ap["version"],
        "impact_id": ap["impact_id"],
        "product_serial": ap["product_serial"],
        "measured_epoch": ap["measured_epoch"],
        "in_suspect_window": ap["in_suspect_window"],
        "status": ap["status"],
    }


# ---------------------------------------------------------------------------
# GageRRStudy
# ---------------------------------------------------------------------------
def serialize_study(s):
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "instrument_id": s["instrument_id"],
        "operator_count": s["operator_count"],
        "part_count": s["part_count"],
        "trial_count": s["trial_count"],
        "process_tolerance": s["process_tolerance"],
        "ev_repeatability": s.get("ev_repeatability"),
        "av_reproducibility": s.get("av_reproducibility"),
        "grr": s.get("grr"),
        "pct_grr": s.get("pct_grr"),
        "acceptability": s.get("acceptability"),
        "status": s["status"],
    }


# ---------------------------------------------------------------------------
# GageRRTrial
# ---------------------------------------------------------------------------
def serialize_trial(t):
    return {
        "id": t["id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
        "study_id": t["study_id"],
        "operator_index": t["operator_index"],
        "part_index": t["part_index"],
        "trial_index": t["trial_index"],
        "measured_value": t["measured_value"],
    }


# ---------------------------------------------------------------------------
# ClockState
# ---------------------------------------------------------------------------
def serialize_clock():
    return {
        "id": db.clock["id"],
        "created_at": db.clock["created_at"],
        "current_epoch": db.clock["current_epoch"],
    }


MAX_TRACE_DEPTH = MAX_DEPTH
