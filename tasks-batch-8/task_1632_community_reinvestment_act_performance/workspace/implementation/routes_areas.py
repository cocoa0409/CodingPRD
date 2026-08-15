"""Assessment areas, demographic profiles, access analysis, and area-scoped lists."""

from datetime import timedelta
from decimal import Decimal

from core import (
    ACTIVITY_STATUSES,
    ACTIVITY_TYPES,
    ALL_ROLES,
    APPLICATION_STATUSES,
    APPLICATION_TYPES,
    BRANCH_STATUSES,
    LOAN_STATUSES,
    LOAN_TYPES,
    PROFILE_STATUSES,
    STORE,
    TRACT_INCOME_LEVELS,
    activity_out,
    api_err,
    application_out,
    area_out,
    authenticate,
    branch_out,
    cascade_public_file_stale,
    check_tract_exclusivity,
    clock_today,
    fmt_date,
    get_area_or_404,
    json_body,
    list_response,
    loan_out,
    new_entity,
    ok,
    optional,
    parse_date_str,
    profile_out,
    q_enum,
    q_int,
    ratio4,
    require,
    round2,
    touch,
    v_int,
    v_str,
    v_str_list,
    app,
)

AREA_ROLES = ("CRAOfficer",)


@app.route("/cra/assessment-areas", methods=["POST"])
def create_assessment_area():
    authenticate(AREA_ROLES)
    b = json_body()
    area_code = v_str(require(b, "area_code"), "area_code")
    name = v_str(require(b, "name"), "name")
    msa_code = v_str(require(b, "msa_code"), "msa_code")
    state_code = v_str(require(b, "state_code"), "state_code")
    tracts = v_str_list(require(b, "census_tracts"), "census_tracts")
    start = require(b, "effective_start_date")
    if parse_date_str(start) is None:
        api_err("ERR_VALIDATION", "Field effective_start_date must be an ISO date (YYYY-MM-DD).", 400)
    budget = v_int(require(b, "annual_cd_budget_cents"), "annual_cd_budget_cents", minimum=0)

    # Business constraint (tier 6): area_code unique.
    for other in STORE["assessment_areas"].values():
        if other["area_code"] == area_code:
            api_err("ERR_DUPLICATE_AREA_CODE", "area_code already exists.", 409)

    # Business constraint (tier 6): half-open [start, end) period overlap per msa_code.
    new_start = parse_date_str(start)
    for other in STORE["assessment_areas"].values():
        if other["msa_code"] != msa_code:
            continue
        other_end = (
            parse_date_str(other["effective_end_date"]) if other["effective_end_date"] else None
        )
        # New areas are open-ended; overlap iff other's end is open or after new start.
        if other_end is None or new_start < other_end:
            api_err(
                "ERR_AREA_PERIOD_OVERLAP",
                "Effective window overlaps another area in the same msa_code.",
                409,
            )

    a = new_entity()
    a.update(
        {
            "area_code": area_code,
            "name": name,
            "msa_code": msa_code,
            "state_code": state_code,
            "census_tracts": tracts,
            "effective_start_date": start,
            "effective_end_date": None,
            "annual_cd_budget_cents": budget,
            "confirmed_loan_count": 0,
            "qualified_cd_total_cents": 0,
            "status": "DRAFT",
        }
    )
    STORE["assessment_areas"][a["id"]] = a
    return ok(area_out(a), status=201)


@app.route("/cra/assessment-areas/<area_id>", methods=["GET"])
def get_assessment_area(area_id):
    authenticate(ALL_ROLES)
    return ok(area_out(get_area_or_404(area_id)))


@app.route("/cra/assessment-areas/<area_id>", methods=["PATCH"])
def patch_assessment_area(area_id):
    authenticate(AREA_ROLES)
    area = get_area_or_404(area_id)
    b = json_body()
    expected = v_int(
        require(b, "expected_assessment_area_version"), "expected_assessment_area_version"
    )
    new_name = optional(b, "name")
    if new_name is not None:
        new_name = v_str(new_name, "name")
    new_tracts = optional(b, "census_tracts")
    if new_tracts is not None:
        new_tracts = v_str_list(new_tracts, "census_tracts")

    if area["status"] not in ("DRAFT", "UNDER_REVIEW"):
        api_err("ERR_INVALID_STATE", "Assessment area may be edited only while DRAFT or UNDER_REVIEW.", 409)
    if expected != area["version"]:
        api_err("ERR_STALE_VERSION", "expected_assessment_area_version does not match the current version.", 412)
    if new_tracts is not None and area["status"] == "UNDER_REVIEW":
        check_tract_exclusivity(area, new_tracts)

    if new_name is not None:
        area["name"] = new_name
    if new_tracts is not None:
        area["census_tracts"] = new_tracts
    touch(area)
    return ok(area_out(area))


def _area_transition(area_id, from_state, to_state, cascade=False):
    authenticate(AREA_ROLES)
    area = get_area_or_404(area_id)
    if area["status"] != from_state:
        api_err(
            "ERR_INVALID_STATE",
            "Cannot perform this action while the assessment area is %s." % area["status"],
            409,
        )
    if to_state == "ACTIVE":
        # Activation / review completion share the two delineation checks.
        if not area["census_tracts"]:
            api_err("ERR_VALIDATION", "census_tracts must be non-empty at activation.", 400)
        check_tract_exclusivity(area, area["census_tracts"])
    area["status"] = to_state
    if to_state == "RETIRED":
        area["effective_end_date"] = fmt_date(clock_today())
    touch(area)
    if cascade:
        cascade_public_file_stale("aa_list_current")
    return ok(area_out(area))


@app.route("/cra/assessment-areas/<area_id>/activate", methods=["POST"])
def activate_area(area_id):
    return _area_transition(area_id, "DRAFT", "ACTIVE", cascade=True)


@app.route("/cra/assessment-areas/<area_id>/begin-review", methods=["POST"])
def begin_review_area(area_id):
    return _area_transition(area_id, "ACTIVE", "UNDER_REVIEW")


@app.route("/cra/assessment-areas/<area_id>/complete-review", methods=["POST"])
def complete_review_area(area_id):
    return _area_transition(area_id, "UNDER_REVIEW", "ACTIVE", cascade=True)


@app.route("/cra/assessment-areas/<area_id>/retire", methods=["POST"])
def retire_area(area_id):
    return _area_transition(area_id, "ACTIVE", "RETIRED", cascade=True)


# ---------------------------------------------------------------------------
# Demographic profiles
# ---------------------------------------------------------------------------
@app.route("/cra/assessment-areas/<area_id>/demographic-profiles", methods=["POST"])
def create_demographic_profile(area_id):
    authenticate(AREA_ROLES)
    area = get_area_or_404(area_id)
    b = json_body()
    expected = v_int(
        require(b, "expected_assessment_area_version"), "expected_assessment_area_version"
    )
    data_year = v_int(require(b, "data_year"), "data_year")
    total_tracts = v_int(require(b, "total_tracts"), "total_tracts", minimum=0)
    low_income = v_int(require(b, "low_income_tracts"), "low_income_tracts", minimum=0)
    moderate_income = v_int(
        require(b, "moderate_income_tracts"), "moderate_income_tracts", minimum=0
    )
    total_population = v_int(require(b, "total_population"), "total_population", minimum=0)
    lmi_population = v_int(require(b, "lmi_population"), "lmi_population", minimum=0)
    median_income = v_int(require(b, "median_family_income"), "median_family_income", minimum=0)
    if lmi_population > total_population:
        api_err("ERR_VALIDATION", "lmi_population may not exceed total_population.", 400)

    # OCC guard on the parent area.
    if expected != area["version"]:
        api_err("ERR_STALE_VERSION", "expected_assessment_area_version does not match the current version.", 412)

    # Same (area, data_year) vintage supersedes the prior CURRENT profile.
    for p in STORE["demographic_profiles"].values():
        if (
            p["assessment_area_id"] == area["id"]
            and p["data_year"] == data_year
            and p["status"] == "CURRENT"
        ):
            p["status"] = "SUPERSEDED"
            touch(p)

    p = new_entity()
    p.update(
        {
            "assessment_area_id": area["id"],
            "data_year": data_year,
            "total_tracts": total_tracts,
            "low_income_tracts": low_income,
            "moderate_income_tracts": moderate_income,
            "total_population": total_population,
            "lmi_population": lmi_population,
            "median_family_income": median_income,
            "lmi_population_pct": float(ratio4(lmi_population, total_population)),
            "lmi_tract_pct": float(ratio4(low_income + moderate_income, total_tracts)),
            "status": "CURRENT",
        }
    )
    STORE["demographic_profiles"][p["id"]] = p

    # Profile creation mutates the parent area.
    touch(area)
    return ok(profile_out(p), status=201)


@app.route("/cra/assessment-areas/<area_id>/demographic-profiles", methods=["GET"])
def list_demographic_profiles(area_id):
    authenticate(ALL_ROLES)
    area = get_area_or_404(area_id)
    status_f = q_enum("status", PROFILE_STATUSES)
    year_f = q_int("data_year")
    records = [
        p
        for p in STORE["demographic_profiles"].values()
        if p["assessment_area_id"] == area["id"]
        and (status_f is None or p["status"] == status_f)
        and (year_f is None or p["data_year"] == year_f)
    ]
    return list_response(records, profile_out)


# ---------------------------------------------------------------------------
# Access analysis (computed read)
# ---------------------------------------------------------------------------
@app.route("/cra/assessment-areas/<area_id>/access-analysis", methods=["GET"])
def access_analysis(area_id):
    authenticate(ALL_ROLES)
    area = get_area_or_404(area_id)

    open_branches = [
        b
        for b in STORE["branches"].values()
        if b["assessment_area_id"] == area["id"] and b["status"] == "OPEN"
    ]
    open_count = len(open_branches)

    # Benchmark: lmi_tract_pct of the CURRENT profile with the max data_year (0 if none).
    current_profiles = [
        p
        for p in STORE["demographic_profiles"].values()
        if p["assessment_area_id"] == area["id"] and p["status"] == "CURRENT"
    ]
    benchmark = Decimal("0")
    if current_profiles:
        latest = max(current_profiles, key=lambda p: (p["data_year"], p["created_at"], p["_seq"]))
        benchmark = Decimal(str(latest["lmi_tract_pct"]))

    # Trailing 365-day LMI closure count: closed_date in (today-365, today].
    today = clock_today()
    window_start = today - timedelta(days=365)
    closures = 0
    for b in STORE["branches"].values():
        if (
            b["assessment_area_id"] == area["id"]
            and b["status"] == "CLOSED"
            and b["tract_income_level"] in ("LOW", "MODERATE")
            and b["closed_date"]
        ):
            closed = parse_date_str(b["closed_date"])
            if closed is not None and window_start < closed <= today:
                closures += 1

    if open_count == 0:
        lmi_branch_pct = Decimal("0")
        score = Decimal("0")
    else:
        lmi_open = sum(
            1 for b in open_branches if b["tract_income_level"] in ("LOW", "MODERATE")
        )
        lmi_branch_pct = ratio4(lmi_open, open_count)
        raw = Decimal(50) + Decimal(100) * (lmi_branch_pct - benchmark) - Decimal(5) * closures
        score = round2(raw)
        if score < 0:
            score = Decimal("0")
        elif score > 100:
            score = Decimal("100")

    return ok(
        {
            "open_branch_count": open_count,
            "lmi_branch_pct": float(lmi_branch_pct),
            "benchmark_lmi_tract_pct": float(benchmark),
            "lmi_closures_12m": closures,
            "access_score": float(score),
        }
    )


# ---------------------------------------------------------------------------
# Area-scoped lists
# ---------------------------------------------------------------------------
@app.route("/cra/assessment-areas/<area_id>/loan-records", methods=["GET"])
def list_area_loans(area_id):
    authenticate(ALL_ROLES)
    area = get_area_or_404(area_id)
    status_f = q_enum("status", LOAN_STATUSES)
    year_f = q_int("reporting_year")
    type_f = q_enum("loan_type", LOAN_TYPES)
    records = [
        ln
        for ln in STORE["loan_records"].values()
        if ln["assessment_area_id"] == area["id"]
        and (status_f is None or ln["status"] == status_f)
        and (year_f is None or ln["reporting_year"] == year_f)
        and (type_f is None or ln["loan_type"] == type_f)
    ]
    return list_response(records, loan_out)


@app.route("/cra/assessment-areas/<area_id>/community-development-activities", methods=["GET"])
def list_area_activities(area_id):
    authenticate(ALL_ROLES)
    area = get_area_or_404(area_id)
    status_f = q_enum("status", ACTIVITY_STATUSES)
    type_f = q_enum("activity_type", ACTIVITY_TYPES)
    records = [
        a
        for a in STORE["cd_activities"].values()
        if a["assessment_area_id"] == area["id"]
        and (status_f is None or a["status"] == status_f)
        and (type_f is None or a["activity_type"] == type_f)
    ]
    return list_response(records, activity_out)


@app.route("/cra/assessment-areas/<area_id>/branches", methods=["GET"])
def list_area_branches(area_id):
    authenticate(ALL_ROLES)
    area = get_area_or_404(area_id)
    status_f = q_enum("status", BRANCH_STATUSES)
    level_f = q_enum("tract_income_level", TRACT_INCOME_LEVELS)
    records = [
        b
        for b in STORE["branches"].values()
        if b["assessment_area_id"] == area["id"]
        and (status_f is None or b["status"] == status_f)
        and (level_f is None or b["tract_income_level"] == level_f)
    ]
    return list_response(records, branch_out)


@app.route("/cra/assessment-areas/<area_id>/expansion-applications", methods=["GET"])
def list_area_applications(area_id):
    authenticate(ALL_ROLES)
    area = get_area_or_404(area_id)
    status_f = q_enum("status", APPLICATION_STATUSES)
    type_f = q_enum("application_type", APPLICATION_TYPES)
    records = [
        a
        for a in STORE["expansion_applications"].values()
        if a["target_assessment_area_id"] == area["id"]
        and (status_f is None or a["status"] == status_f)
        and (type_f is None or a["application_type"] == type_f)
    ]
    return list_response(records, application_out)
