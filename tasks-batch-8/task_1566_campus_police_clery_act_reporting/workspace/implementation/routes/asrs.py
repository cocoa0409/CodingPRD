"""Annual Security Reports and statistic line snapshots."""

from datetime import datetime, timezone

from flask import Blueprint, request

from core import (clock, db, enum_or_422, err, get_body, get_or_404, mint,
                  now_iso, now_iso_short, paginate, pub, req_int, req_str, require_roles,
                  success, touch)

bp = Blueprint("asrs", __name__)

REFERRAL_TYPES = {"LIQUOR_LAW_REFERRAL", "DRUG_LAW_REFERRAL",
                  "WEAPONS_LAW_REFERRAL"}

GEO_COLUMN_MAP = {
    "ON_CAMPUS": ("ON_CAMPUS",),
    "ON_CAMPUS_RESIDENTIAL": ("ON_CAMPUS", "ON_CAMPUS_RESIDENTIAL"),
    "NON_CAMPUS": ("NON_CAMPUS",),
    "PUBLIC_PROPERTY": ("PUBLIC_PROPERTY",),
}

VARIANTS = {"PROVISIONAL", "FINAL"}


def _deadline_for_year(report_year):
    return datetime(report_year + 1, 10, 1, 0, 0, 0, tzinfo=timezone.utc)


@bp.post("/annual-security-reports")
@require_roles("SystemAdmin")
def create_asr():
    data = get_body()
    report_year = req_int(data, "report_year")
    for a in db.asrs.values():
        if a["report_year"] == report_year:
            err("ERR_DUPLICATE_REPORT_YEAR", 409,
                "An ASR already exists for report_year %s" % report_year)
    asr = mint({"report_year": report_year,
                "statistics_version": 0,
                "compiled_at": None,
                "final_compile_done": False,
                "statistics_stale": False,
                "amendment_started_at": None,
                "published_at": None,
                "is_late": False,
                "status": "COLLECTING",
                "_compiled_dt": None,
                "_amendment_started_dt": None})
    db.asrs[asr["id"]] = asr
    return success(pub(asr), 201)


@bp.get("/annual-security-reports")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_asrs():
    items = list(db.asrs.values())
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    ry = request.args.get("report_year")
    if ry is not None:
        try:
            ry_i = int(ry)
            items = [a for a in items if a["report_year"] == ry_i]
        except ValueError:
            items = []
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.get("/annual-security-reports/<aid>")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def get_asr(aid):
    return success(pub(get_or_404(db.asrs, aid)), 200)


@bp.post("/annual-security-reports/<aid>/compile")
@require_roles("CleryCoordinator")
def compile_asr(aid):
    data = get_body()
    variant = req_str(data, "variant")
    expected_version = req_int(data, "expected_report_version")
    asr = get_or_404(db.asrs, aid)
    if asr["status"] not in ("COLLECTING", "UNDER_AMENDMENT"):
        err("ERR_INVALID_STATE", 409,
            "Compile allowed only in COLLECTING or UNDER_AMENDMENT")
    if expected_version != asr["version"]:
        err("ERR_STALE_VERSION", 412,
            "expected_report_version does not match current version")
    enum_or_422(variant, VARIANTS, "variant")
    # Step 1: freeze the incident set.
    include_statuses = ({"CLASSIFIED"} if variant == "FINAL"
                        else {"CLASSIFIED", "UNDER_RECLASSIFICATION"})
    incidents = [i for i in db.incidents.values()
                 if i["_occurred_dt"].year == asr["report_year"]
                 and i["status"] in include_statuses]
    # Steps 2-3: counted rows mapped into geography columns.
    cells = {}
    for inc in incidents:
        geo = db.geographies.get(inc["geography_id"])
        if geo is None:
            continue
        columns = GEO_COLUMN_MAP.get(geo["category"], ())
        for row in db.offense_counts.values():
            if row["incident_id"] != inc["id"] or row["status"] != "COUNTED":
                continue
            for col in columns:
                key = (row["offense_type"], col)
                cell = cells.setdefault(key, {"count": 0,
                                              "referred_persons_count": 0})
                cell["count"] += 1
                if row["offense_type"] in REFERRAL_TYPES:
                    cell["referred_persons_count"] += row["referred_persons"]
    # Step 4: supersede prior snapshot, bump version, emit rows.
    for line in db.statistic_lines.values():
        if line["report_id"] == aid and line["status"] == "CURRENT":
            line["status"] = "SUPERSEDED"
            touch(line)
    asr["statistics_version"] += 1
    for (offense_type, col), cell in sorted(cells.items()):
        if cell["count"] > 0 or cell["referred_persons_count"] > 0:
            line = mint({"report_id": aid,
                         "statistics_version": asr["statistics_version"],
                         "compilation_variant": variant,
                         "offense_type": offense_type,
                         "geography_column": col,
                         "count": cell["count"],
                         "referred_persons_count":
                             cell["referred_persons_count"],
                         "status": "CURRENT"})
            db.statistic_lines[line["id"]] = line
    asr["statistics_stale"] = False
    asr["compiled_at"] = now_iso_short()
    asr["_compiled_dt"] = clock.current
    if variant == "FINAL":
        asr["final_compile_done"] = True
    touch(asr)
    return success(pub(asr), 200)


@bp.get("/annual-security-reports/<aid>/statistic-lines")
@require_roles("SystemAdmin", "CleryCoordinator", "PoliceChief",
               "FederalReviewer")
def list_statistic_lines(aid):
    asr = get_or_404(db.asrs, aid)
    items = [l for l in db.statistic_lines.values() if l["report_id"] == aid]
    sv = request.args.get("statistics_version")
    if sv is not None:
        try:
            sv_i = int(sv)
            items = [l for l in items if l["statistics_version"] == sv_i]
        except ValueError:
            items = []
    else:
        items = [l for l in items
                 if l["statistics_version"] == asr["statistics_version"]]
    cv = request.args.get("compilation_variant")
    if cv is not None:
        items = [l for l in items if l["compilation_variant"] == cv]
    gc = request.args.get("geography_column")
    if gc is not None:
        items = [l for l in items if l["geography_column"] == gc]
    ot = request.args.get("offense_type")
    if ot is not None:
        items = [l for l in items if l["offense_type"] == ot]
    window, page = paginate(items)
    return success([pub(e) for e in window], 200, page)


@bp.post("/annual-security-reports/<aid>/submit-review")
@require_roles("CleryCoordinator")
def submit_review(aid):
    asr = get_or_404(db.asrs, aid)
    if asr["status"] != "COLLECTING":
        err("ERR_INVALID_STATE", 409,
            "Only a COLLECTING report may be submitted for review")
    if not asr["final_compile_done"]:
        err("ERR_FINAL_COMPILE_REQUIRED", 422,
            "A FINAL compile is required before submit-review")
    asr["status"] = "UNDER_REVIEW"
    touch(asr)
    return success(pub(asr), 200)


@bp.post("/annual-security-reports/<aid>/publish")
@require_roles("PoliceChief")
def publish_asr(aid):
    asr = get_or_404(db.asrs, aid)
    if asr["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_REVIEW report may be published")
    asr["published_at"] = now_iso_short()
    asr["is_late"] = clock.current > _deadline_for_year(asr["report_year"])
    asr["status"] = "PUBLISHED"
    touch(asr)
    return success(pub(asr), 200)


@bp.post("/annual-security-reports/<aid>/begin-amendment")
@require_roles("CleryCoordinator")
def begin_amendment(aid):
    asr = get_or_404(db.asrs, aid)
    if asr["status"] not in ("PUBLISHED", "REPUBLISHED"):
        err("ERR_INVALID_STATE", 409,
            "Only a PUBLISHED or REPUBLISHED report may be amended")
    asr["amendment_started_at"] = now_iso_short()
    asr["_amendment_started_dt"] = clock.current
    asr["status"] = "UNDER_AMENDMENT"
    touch(asr)
    return success(pub(asr), 200)


@bp.post("/annual-security-reports/<aid>/republish")
@require_roles("PoliceChief")
def republish_asr(aid):
    asr = get_or_404(db.asrs, aid)
    if asr["status"] != "UNDER_AMENDMENT":
        err("ERR_INVALID_STATE", 409,
            "Only an UNDER_AMENDMENT report may be republished")
    compiled_dt = asr.get("_compiled_dt")
    amended_dt = asr.get("_amendment_started_dt")
    if compiled_dt is None or amended_dt is None \
            or not compiled_dt > amended_dt:
        err("ERR_RECOMPILE_REQUIRED", 422,
            "A compile newer than amendment_started_at is required")
    asr["published_at"] = now_iso_short()
    asr["is_late"] = clock.current > _deadline_for_year(asr["report_year"])
    asr["status"] = "REPUBLISHED"
    touch(asr)
    return success(pub(asr), 200)
