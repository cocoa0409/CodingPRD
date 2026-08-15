"""Incident reports: intake, classification, hierarchy, unfound cascades."""

from flask import Blueprint, g, request

from core import (business_days_between, clock, db, enum_or_422, err,
                  get_body, get_or_404, mint, now_iso, now_iso_short, opt_dt, opt_int,
                  opt_str, paginate, parse_dt, pub, req_dt, req_int, req_list,
                  req_str, require_roles, success, touch, _MISSING)

bp = Blueprint("incidents", __name__)

OFFENSE_TYPES = {"CRIMINAL_HOMICIDE", "SEX_OFFENSE", "ROBBERY",
                 "AGGRAVATED_ASSAULT", "BURGLARY", "MOTOR_VEHICLE_THEFT",
                 "ARSON", "DOMESTIC_VIOLENCE", "DATING_VIOLENCE", "STALKING",
                 "HATE_CRIME", "LIQUOR_LAW_REFERRAL", "DRUG_LAW_REFERRAL",
                 "WEAPONS_LAW_REFERRAL", "NON_CLERY"}

BIAS_MOTIVATIONS = {"NONE", "RACE", "RELIGION", "SEXUAL_ORIENTATION", "GENDER",
                    "GENDER_IDENTITY", "ETHNICITY", "NATIONAL_ORIGIN",
                    "DISABILITY"}

RANK = {"CRIMINAL_HOMICIDE": 10, "SEX_OFFENSE": 20, "ROBBERY": 30,
        "AGGRAVATED_ASSAULT": 40, "BURGLARY": 50, "MOTOR_VEHICLE_THEFT": 60,
        "ARSON": 70, "DOMESTIC_VIOLENCE": 80, "DATING_VIOLENCE": 81,
        "STALKING": 82, "HATE_CRIME": 90, "LIQUOR_LAW_REFERRAL": 100,
        "DRUG_LAW_REFERRAL": 101, "WEAPONS_LAW_REFERRAL": 102,
        "NON_CLERY": 999}

EXEMPT = {"ARSON", "DOMESTIC_VIOLENCE", "DATING_VIOLENCE", "STALKING",
          "HATE_CRIME", "LIQUOR_LAW_REFERRAL", "DRUG_LAW_REFERRAL",
          "WEAPONS_LAW_REFERRAL"}

SOURCES = {"POLICE_DIRECT", "CSA_REFERRAL", "ANONYMOUS"}
TERMINAL = {"UNFOUNDED", "WITHDRAWN"}


def _year_of(dt):
    return dt.year


def _log_entry_for(incident_id):
    for e in db.log_entries.values():
        if e["incident_id"] == incident_id:
            return e
    return None


def _asr_for_year(year):
    for a in db.asrs.values():
        if a["report_year"] == year:
            return a
    return None


def _check_not_terminal(inc):
    if inc["status"] in TERMINAL:
        err("ERR_INCIDENT_TERMINAL", 409,
            "Incident is in a terminal state: %s" % inc["status"])


@bp.post("/incident-reports")
@require_roles("CleryCoordinator", "PoliceChief")
def create_incident():
    data = get_body()
    reported_raw, reported_dt = req_dt(data, "reported_at")
    occurred_raw, occurred_dt = req_dt(data, "occurred_at")
    geography_id = req_str(data, "geography_id")
    source = req_str(data, "source")
    narrative = req_str(data, "narrative")
    end_raw, end_dt = opt_dt(data, "occurred_end_at")
    referral_id = opt_str(data, "referral_id")
    # Body foreign keys resolve (priority 5).
    geo = db.geographies.get(geography_id)
    if geo is None:
        err("ERR_REFERENCE_NOT_FOUND", 404, "geography_id does not resolve")
    referral = None
    if referral_id is not None:
        referral = db.referrals.get(referral_id)
        if referral is None:
            err("ERR_REFERENCE_NOT_FOUND", 404, "referral_id does not resolve")
    # Referential business rules (priority 10): retired geography, then
    # referral linkage state.
    if geo["status"] != "ACTIVE":
        err("ERR_GEOGRAPHY_RETIRED", 422, "Geography is RETIRED")
    if source == "CSA_REFERRAL":
        if referral_id is None:
            err("ERR_INVALID_STATE", 409,
                "referral_id is required when source is CSA_REFERRAL")
        if referral["status"] != "FORWARDED":
            err("ERR_INVALID_STATE", 409,
                "Referenced referral must be in FORWARDED status")
    else:
        if referral_id is not None:
            err("ERR_INVALID_STATE", 409,
                "referral_id must be absent unless source is CSA_REFERRAL")
    # Field-level constraints (priority 11).
    enum_or_422(source, SOURCES, "source")
    if end_dt is not None and end_dt < occurred_dt:
        err("ERR_VALIDATION_FAILED", 422,
            "occurred_end_at must be >= occurred_at")
    db.incident_seq += 1
    inc = mint({"report_number": "IR-%d-%06d" % (reported_dt.year,
                                                 db.incident_seq),
                "reported_at": reported_raw,
                "occurred_at": occurred_raw,
                "occurred_end_at": end_raw,
                "geography_id": geography_id,
                "source": source,
                "referral_id": referral_id,
                "narrative": narrative,
                "is_clery_reportable": False,
                "classified_at": None,
                "status": "DRAFT",
                "_reported_dt": reported_dt,
                "_occurred_dt": occurred_dt})
    db.incidents[inc["id"]] = inc
    if referral is not None:
        referral["status"] = "LINKED"
        touch(referral)
    return success(pub(inc), 201)


@bp.get("/incident-reports")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_incidents():
    items = list(db.incidents.values())
    st = request.args.get("status")
    if st is not None:
        items = [e for e in items if e["status"] == st]
    geo = request.args.get("geography_id")
    if geo is not None:
        items = [e for e in items if e["geography_id"] == geo]
    rid = request.args.get("referral_id")
    if rid is not None:
        items = [e for e in items if e.get("referral_id") == rid]
    ry = request.args.get("report_year")
    if ry is not None:
        try:
            ry_i = int(ry)
            items = [e for e in items if e["_occurred_dt"].year == ry_i]
        except ValueError:
            items = []
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/incident-reports/<iid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def get_incident(iid):
    return success(pub(get_or_404(db.incidents, iid)), 200)


@bp.post("/incident-reports/<iid>/submit")
@require_roles("CleryCoordinator", "PoliceChief")
def submit_incident(iid):
    inc = get_or_404(db.incidents, iid)
    _check_not_terminal(inc)
    if inc["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Only a DRAFT incident may be submitted")
    inc["status"] = "SUBMITTED"
    touch(inc)
    # Side effect: exactly one daily crime log entry per incident.
    db.log_entry_seq += 1
    entry = mint({"entry_number": "CL-%06d" % db.log_entry_seq,
                  "incident_id": inc["id"],
                  "nature": "Unclassified",
                  "date_reported": inc["reported_at"],
                  "date_occurred": inc["occurred_at"],
                  "general_location": None,
                  "disposition": "OPEN",
                  "last_disposition_change_at": None,
                  "entry_overdue": business_days_between(
                      inc["_reported_dt"], clock.current) > 2,
                  "disposition_update_overdue": False,
                  "is_public": True,
                  "_date_occurred_dt": inc["_occurred_dt"],
                  "_date_reported_dt": inc["_reported_dt"]})
    db.log_entries[entry["id"]] = entry
    return success(pub(inc), 200)


@bp.post("/incident-reports/<iid>/begin-classification")
@require_roles("CleryCoordinator")
def begin_classification(iid):
    inc = get_or_404(db.incidents, iid)
    _check_not_terminal(inc)
    if inc["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409,
            "Only a SUBMITTED incident may begin classification")
    inc["status"] = "UNDER_CLASSIFICATION"
    touch(inc)
    return success(pub(inc), 200)


def _resolve_hierarchy(offense_specs, incident):
    """Replace the incident's offense rows; return the primary label."""
    old = [r for r in db.offense_counts.values()
           if r["incident_id"] == incident["id"]]
    for r in old:
        del db.offense_counts[r["id"]]
    rows = []
    for idx, spec in enumerate(offense_specs):
        t = spec["offense_type"]
        exempt = t in EXEMPT
        row = mint({"incident_id": incident["id"],
                    "offense_type": t,
                    "victim_count": spec["victim_count"],
                    "referred_persons": spec["referred_persons"],
                    "bias_motivation": spec["bias_motivation"],
                    "hierarchy_rank": RANK[t],
                    "is_exempt_from_hierarchy": exempt,
                    "status": None,
                    "_order": idx})
        rows.append(row)
    non_exempt = [r for r in rows
                  if not r["is_exempt_from_hierarchy"]
                  and r["offense_type"] != "NON_CLERY"]
    primary = None
    if non_exempt:
        primary = min(non_exempt,
                      key=lambda r: (r["hierarchy_rank"], r["_order"]))
    for r in rows:
        if r["offense_type"] == "NON_CLERY":
            r["status"] = "EXCLUDED_BY_HIERARCHY"
        elif r["is_exempt_from_hierarchy"]:
            r["status"] = "COUNTED"
        elif primary is not None and r["id"] == primary["id"]:
            r["status"] = "COUNTED"
        else:
            r["status"] = "EXCLUDED_BY_HIERARCHY"
    for r in rows:
        db.offense_counts[r["id"]] = r
    if primary is not None:
        return primary["offense_type"]
    counted = [r for r in rows if r["status"] == "COUNTED"]
    if counted:
        return min(counted,
                   key=lambda r: (r["hierarchy_rank"], r["_order"]))[
                       "offense_type"]
    return None


@bp.post("/incident-reports/<iid>/classify")
@require_roles("CleryCoordinator")
def classify_incident(iid):
    data = get_body()
    geography_id = req_str(data, "geography_id")
    offense_counts = req_list(data, "offense_counts")
    expected_version = req_int(data, "expected_incident_version")
    # Shape of each element (priority 3).
    specs = []
    for el in offense_counts:
        if not isinstance(el, dict):
            err("ERR_INVALID_REQUEST", 400,
                "offense_counts elements must be objects")
        ot = el.get("offense_type", _MISSING)
        if ot is _MISSING or not isinstance(ot, str):
            err("ERR_INVALID_REQUEST", 400,
                "offense_counts.offense_type must be a string")
        vc = el.get("victim_count", 1)
        if isinstance(vc, bool) or not isinstance(vc, int):
            err("ERR_INVALID_REQUEST", 400,
                "offense_counts.victim_count must be an integer")
        rp = el.get("referred_persons", 0)
        if isinstance(rp, bool) or not isinstance(rp, int):
            err("ERR_INVALID_REQUEST", 400,
                "offense_counts.referred_persons must be an integer")
        bm = el.get("bias_motivation", "NONE")
        if not isinstance(bm, str):
            err("ERR_INVALID_REQUEST", 400,
                "offense_counts.bias_motivation must be a string")
        specs.append({"offense_type": ot, "victim_count": vc,
                      "referred_persons": rp, "bias_motivation": bm})
    inc = get_or_404(db.incidents, iid)
    geo = db.geographies.get(geography_id)
    if geo is None:
        err("ERR_REFERENCE_NOT_FOUND", 404, "geography_id does not resolve")
    # State legality (priority 6).
    _check_not_terminal(inc)
    reclass = inc["status"] == "UNDER_RECLASSIFICATION"
    if inc["status"] not in ("UNDER_CLASSIFICATION", "UNDER_RECLASSIFICATION"):
        err("ERR_INVALID_STATE", 409,
            "Incident must be UNDER_CLASSIFICATION or UNDER_RECLASSIFICATION")
    if expected_version != inc["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_incident_version does not match current version")
    # Business safety (priority 7).
    if not specs or all(s["offense_type"] == "NON_CLERY" for s in specs):
        err("ERR_CLASSIFICATION_INCOMPLETE", 422,
            "offense_counts must be non-empty and contain a Clery offense")
    # Referential (priority 10).
    if geo["status"] != "ACTIVE":
        err("ERR_GEOGRAPHY_RETIRED", 422, "Geography is RETIRED")
    # Field-level constraints (priority 11).
    for s in specs:
        enum_or_422(s["offense_type"], OFFENSE_TYPES, "offense_type")
        enum_or_422(s["bias_motivation"], BIAS_MOTIVATIONS, "bias_motivation")
        if s["victim_count"] < 1:
            err("ERR_VALIDATION_FAILED", 422, "victim_count must be >= 1")
        if s["referred_persons"] < 0:
            err("ERR_VALIDATION_FAILED", 422, "referred_persons must be >= 0")
    primary_label = _resolve_hierarchy(specs, inc)
    inc["geography_id"] = geography_id
    inc["classified_at"] = now_iso_short()
    inc["is_clery_reportable"] = any(
        r["status"] == "COUNTED" for r in db.offense_counts.values()
        if r["incident_id"] == inc["id"])
    inc["status"] = "CLASSIFIED"
    touch(inc)
    # Log entry cascade.
    entry = _log_entry_for(inc["id"])
    if entry is not None:
        entry["nature"] = primary_label if primary_label else "Unclassified"
        entry["general_location"] = geo["name"]
        touch(entry)
    # Reclassification staleness cascade.
    if reclass:
        asr = _asr_for_year(inc["_occurred_dt"].year)
        if (asr is not None and asr["status"] in ("COLLECTING",
                                                  "UNDER_AMENDMENT")
                and asr["statistics_version"] > 0):
            asr["statistics_stale"] = True
            touch(asr)
            for line in db.statistic_lines.values():
                if line["report_id"] == asr["id"] and line["status"] == "CURRENT":
                    line["status"] = "SUPERSEDED"
                    touch(line)
    return success(pub(inc), 200)


@bp.post("/incident-reports/<iid>/begin-reclassification")
@require_roles("CleryCoordinator")
def begin_reclassification(iid):
    inc = get_or_404(db.incidents, iid)
    _check_not_terminal(inc)
    if inc["status"] != "CLASSIFIED":
        err("ERR_INVALID_STATE", 409,
            "Only a CLASSIFIED incident may begin reclassification")
    asr = _asr_for_year(inc["_occurred_dt"].year)
    if asr is not None and asr["status"] in ("PUBLISHED", "REPUBLISHED"):
        err("ERR_REPORT_LOCKED", 409,
            "The year's Annual Security Report is published")
    inc["status"] = "UNDER_RECLASSIFICATION"
    touch(inc)
    return success(pub(inc), 200)


@bp.post("/incident-reports/<iid>/unfound")
@require_roles("PoliceChief")
def unfound_incident(iid):
    data = get_body()
    justification = data.get("justification", _MISSING)
    if justification is _MISSING or not isinstance(justification, str):
        err("ERR_INVALID_REQUEST", 400, "Field justification must be a string")
    inc = get_or_404(db.incidents, iid)
    _check_not_terminal(inc)
    if inc["status"] not in ("UNDER_CLASSIFICATION", "UNDER_RECLASSIFICATION",
                             "CLASSIFIED"):
        err("ERR_INVALID_STATE", 409,
            "Incident cannot be unfounded from status %s" % inc["status"])
    if not justification.strip():
        err("ERR_UNFOUNDED_JUSTIFICATION_REQUIRED", 422,
            "unfound requires a non-empty justification")
    # Cascade link 1: log entry.
    entry = _log_entry_for(inc["id"])
    if entry is not None:
        entry["disposition"] = "UNFOUNDED"
        entry["is_public"] = False
        entry["last_disposition_change_at"] = now_iso_short()
        entry["disposition_update_overdue"] = (
            business_days_between(clock.current, clock.current) > 2)
        touch(entry)
    # Cascade link 2+3: ASR staleness and statistic-line supersession.
    asr = _asr_for_year(inc["_occurred_dt"].year)
    if asr is not None and asr["statistics_version"] > 0:
        asr["statistics_stale"] = True
        touch(asr)
        for line in db.statistic_lines.values():
            if line["report_id"] == asr["id"] and line["status"] == "CURRENT":
                line["status"] = "SUPERSEDED"
                touch(line)
    for r in db.offense_counts.values():
        if r["incident_id"] == inc["id"]:
            r["status"] = "EXCLUDED_UNFOUNDED"
            touch(r)
    inc["is_clery_reportable"] = False
    inc["status"] = "UNFOUNDED"
    touch(inc)
    return success(pub(inc), 200)


@bp.post("/incident-reports/<iid>/withdraw")
@require_roles("CleryCoordinator")
def withdraw_incident(iid):
    inc = get_or_404(db.incidents, iid)
    _check_not_terminal(inc)
    if inc["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Only a DRAFT incident may be withdrawn")
    inc["status"] = "WITHDRAWN"
    touch(inc)
    return success(pub(inc), 200)


@bp.get("/incident-reports/<iid>/offense-counts")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_offense_counts(iid):
    get_or_404(db.incidents, iid)
    items = [r for r in db.offense_counts.values() if r["incident_id"] == iid]
    items.sort(key=lambda r: r.get("_order", 0))
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)
