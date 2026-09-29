"""Operating hour construction, classification and missing-data substitution
(PRD 3.5 / 3.6).
"""

from constants import METHOD_SYSTEM_TYPES
from db import base_record, db, touch
from lookup import systems_of_unit
from services import calc
from services.reports import (
    period_of_hour,
    recompute_report,
    recompute_unit_availability_for_periods,
)
from util import D, rhu


def _pick(systems):
    """A parameter slot holds at most one live system; a retired incumbent is
    only consulted when nothing live exists.
    """
    live = [s for s in systems if s["qa_status"] != "RETIRED"]
    pool = live if live else systems
    if not pool:
        return None
    pool = sorted(pool, key=lambda s: (s["created_at"], s["_seq"]))
    return pool[-1]


def so2_system_of_unit(unit_id):
    return _pick([s for s in systems_of_unit(unit_id) if s["parameter"] == "SO2"])


def appendix_d_system_of_unit(unit_id):
    return _pick([s for s in systems_of_unit(unit_id) if s["system_type"] == "EXCEPTED_APPENDIX_D"])


def governing_system(unit_id, heat_input_method):
    """The system whose health decides the hour's data quality."""
    if heat_input_method == "CEMS_FLOW_CO2":
        return so2_system_of_unit(unit_id)
    return appendix_d_system_of_unit(unit_id)


def unit_supports_method(unit_id, heat_input_method):
    wanted = METHOD_SYSTEM_TYPES[heat_input_method]
    return any(s["system_type"] in wanted for s in systems_of_unit(unit_id))


def bias_factor_for(unit_id, heat_input_method):
    """Only a CEMS SO2 mass carries the bias adjustment factor."""
    if heat_input_method != "CEMS_FLOW_CO2":
        return 1.0
    system = so2_system_of_unit(unit_id)
    if system is None:
        return 1.0
    return system.get("bias_adjustment_factor", 1.0)


def classify_hour(unit_id, heat_input_method, so2_conc_ppm):
    system = governing_system(unit_id, heat_input_method)
    if system is not None:
        if system["qa_status"] in ("OUT_OF_CONTROL", "RETIRED"):
            return "UNAVAILABLE"
        if system["cal_status"] in ("CAL_EXPIRED", "CAL_FAILED"):
            return "UNAVAILABLE"
    if heat_input_method == "CEMS_FLOW_CO2" and so2_conc_ppm is None:
        return "UNAVAILABLE"
    return "MEASURED"


def build_hour(unit, report, spec):
    """Create (but do not roll up) one operating hour.

    ``spec`` carries the validated inputs plus the resolved fuel sample.
    """
    method = spec["heat_input_method"]
    opf = spec["op_time_fraction"]
    if method == "CEMS_FLOW_CO2":
        heat_input, so2, nox, co2_tons = calc.cems_hour_values(
            spec["flow_scfh"],
            spec["co2_conc_pct"],
            spec["so2_conc_ppm"],
            spec.get("nox_rate_lb_mmbtu"),
            opf,
            bias_factor_for(unit["id"], method),
        )
    else:
        sample = spec["fuel_sample"]
        heat_input, so2, nox, co2_tons = calc.appendix_d_hour_values(
            spec["fuel_flow_lbs"],
            sample["gcv_btu_per_lb"],
            sample["sulfur_content_pct"],
            spec.get("nox_rate_lb_mmbtu"),
            opf,
        )

    data_quality = classify_hour(unit["id"], method, spec.get("so2_conc_ppm"))
    hour = base_record(versioned=False)
    hour.update(
        {
            "unit_id": unit["id"],
            "quarterly_report_id": report["id"],
            "fuel_sample_id": spec.get("fuel_sample_id"),
            "hour_begin_utc": spec["hour_begin_utc_raw"],
            "op_time_fraction": float(opf),
            "gross_load_mw": _as_float(spec.get("gross_load_mw")),
            "heat_input_method": method,
            "flow_scfh": _as_float(spec.get("flow_scfh")),
            "co2_conc_pct": _as_float(spec.get("co2_conc_pct")),
            "so2_conc_ppm": _as_float(spec.get("so2_conc_ppm")),
            "nox_rate_lb_mmbtu": _as_float(spec.get("nox_rate_lb_mmbtu")),
            "fuel_flow_lbs": _as_float(spec.get("fuel_flow_lbs")),
            "heat_input_mmbtu": heat_input,
            "so2_mass_lbs": None if data_quality == "UNAVAILABLE" else so2,
            "nox_mass_lbs": nox,
            "co2_mass_tons": co2_tons,
            "data_quality": data_quality,
            "substitution_method": "NONE",
            "substituted_so2_conc_ppm": None,
            "monitor_data_availability_pct_at_substitution": None,
            "quarterly_report_version_after": None,
            "_hour_begin": spec["hour_begin_utc"],
        }
    )
    db.operating_hours[hour["id"]] = hour
    return hour


def _as_float(value):
    if value is None:
        return None
    return float(value)


def finalize_append(unit, hours, reports):
    """One roll-up per touched report, then the unit's availability percentage.

    ``hours`` receive ``quarterly_report_version_after`` after every recompute so
    the value a client reads is the version the write left behind.
    """
    ordered_reports = sorted(reports, key=lambda r: (r["created_at"], r["_seq"]))
    for report in ordered_reports:
        recompute_report(report, revert_validated=True, bump=True)
    for hour in hours:
        report = db.quarterly_reports.get(hour["quarterly_report_id"])
        if report is not None:
            hour["quarterly_report_version_after"] = report["version"]
    recompute_unit_availability_for_periods(unit, [period_of_hour(h) for h in hours])


# ---------------------------------------------------------------------------
# missing-data substitution
# ---------------------------------------------------------------------------

def substitutable_targets(unit_id, start, end):
    """Half-open ``[from, to)`` window over the unit's UNAVAILABLE hours."""
    rows = [
        h for h in db.operating_hours.values()
        if h["unit_id"] == unit_id
        and h["data_quality"] == "UNAVAILABLE"
        and start <= h["_hour_begin"] < end
    ]
    rows.sort(key=lambda h: (h["_hour_begin"], h["created_at"], h["_seq"]))
    return rows


def run_substitutions(unit, targets):
    """Targets are filled one at a time in ascending hour order; each tier is
    frozen before the next target is considered, so a just-substituted hour never
    joins a later lookback but does join the availability denominator.
    """
    for hour in targets:
        hb = hour["_hour_begin"]
        year, quarter = period_of_hour(hour)
        availability = calc.availability_pct(unit["id"], year, quarter, before=hb)
        lookback = calc.lookback_values(unit["id"], hb)
        method, value = calc.substitution_tier(availability, lookback)
        # The substitute concentration is written as a whole number.
        concentration = int(rhu(value, 0))
        hour["substitution_method"] = method
        hour["substituted_so2_conc_ppm"] = concentration
        hour["monitor_data_availability_pct_at_substitution"] = availability
        hour["data_quality"] = "SUBSTITUTED"
        hour["so2_mass_lbs"] = calc.substituted_so2_mass(
            concentration, hour.get("flow_scfh"), hour["op_time_fraction"]
        )

    report_ids = []
    for hour in targets:
        rid = hour.get("quarterly_report_id")
        if rid and rid not in report_ids:
            report_ids.append(rid)
    reports = [db.quarterly_reports[rid] for rid in report_ids if rid in db.quarterly_reports]
    reports.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for report in reports:
        recompute_report(report, revert_validated=False, bump=True)
    recompute_unit_availability_for_periods(unit, [period_of_hour(h) for h in targets])
    return targets
