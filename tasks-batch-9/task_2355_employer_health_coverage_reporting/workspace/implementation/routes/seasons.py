"""Filing seasons, controlled groups, group members, headcounts, logical clock."""

from flask import Blueprint

import calc
import lookups as lk
import sync
from auth import READ_ROLES, OPERATOR_ROLES, require_roles
from db import clock_iso, db, insert, rows, touch
from envelope import collection, created, created_collection, filtered, ok, ok_raw
from errors import fail
from guards import listing, require_group_unlocked, require_season_open, single_read
from shapes import (
    body,
    date_field,
    digits_field,
    enum_field,
    int_field,
    month_list_field,
    number_field,
    parse_iso8601,
    string_field,
)

bp = Blueprint("seasons", __name__)

COUNT_YEARS = ("PRIOR_YEAR", "REPORTING_YEAR")
DETERMINATION_STATES = (
    "NOT_DETERMINED",
    "DETERMINED_ALE",
    "DETERMINED_NON_ALE",
    "REOPENED",
    "CORRECTION_OPEN",
    "LOCKED",
)
SENT_TO_AGENCY = ("TRANSMITTED", "ACCEPTED", "ACCEPTED_WITH_ERRORS", "PARTIALLY_ACCEPTED")
SETTLED = ("ACCEPTED", "SUPERSEDED")


# --------------------------------------------------------------------------- #
# FilingSeason
# --------------------------------------------------------------------------- #
@bp.post("/filing-seasons")
def create_season():
    require_roles("ComplianceOfficer")
    data = body()
    tax_year = int_field(data, "tax_year", minimum=2020, maximum=2035)
    furnishing_deadline_date = date_field(data, "furnishing_deadline_date")
    filing_deadline_date = date_field(data, "filing_deadline_date")
    tier2_cutoff_date = date_field(data, "tier2_cutoff_date")
    affordability_pct = number_field(
        data, "affordability_pct", required=False, default=0.0902, gt=0, lt=1
    )
    fpl = int_field(data, "mainland_fpl_annual_cents", required=False, default=1560000, minimum=0)
    penalty_a = int_field(data, "penalty_a_annual_cents", required=False, default=296400, minimum=0)
    penalty_b = int_field(data, "penalty_b_annual_cents", required=False, default=444000, minimum=0)
    threshold = int_field(
        data, "electronic_filing_threshold", required=False, default=10, minimum=0
    )

    for season in rows("filing_seasons"):
        if season["tax_year"] == tax_year:
            fail("ERR_DUPLICATE_RESOURCE", "A filing season already exists for that tax year.")

    record = insert(
        "filing_seasons",
        {
            "tax_year": tax_year,
            "status": "OPEN",
            "affordability_pct": affordability_pct,
            "mainland_fpl_annual_cents": fpl,
            "penalty_a_annual_cents": penalty_a,
            "penalty_b_annual_cents": penalty_b,
            "electronic_filing_threshold": threshold,
            "furnishing_deadline_date": furnishing_deadline_date,
            "filing_deadline_date": filing_deadline_date,
            "tier2_cutoff_date": tier2_cutoff_date,
            "open_correction_count": 0,
            "locked_at": None,
        },
    )
    return created(record)


@bp.get("/filing-seasons")
def list_seasons():
    return listing(
        "filing_seasons",
        {"status": ("status", "str"), "tax_year": ("tax_year", "int")},
        READ_ROLES,
    )


@bp.get("/filing-seasons/<identifier>")
def read_season(identifier):
    return single_read("filing_seasons", identifier, READ_ROLES)


@bp.post("/filing-seasons/<season_id>/lock")
def lock_season(season_id):
    require_roles("ComplianceOfficer")
    body()
    season = lk.find("filing_seasons", season_id)
    require_season_open(season)

    if season["open_correction_count"] != 0:
        fail("ERR_SEASON_NOT_LOCKABLE", "A correction of this season is still open.")
    groups = [g for g in rows("controlled_groups") if g["filing_season_id"] == season["id"]]
    for group in groups:
        for member in lk.members_of_group(group, active_only=True):
            for transmittal in lk.transmittals_of_member(member):
                if transmittal["status"] not in SETTLED:
                    fail("ERR_SEASON_NOT_LOCKABLE", "A transmittal of this season has not settled.")

    sync.set_field(season, "status", "LOCKED")
    sync.set_field(season, "locked_at", clock_iso())
    for group in groups:
        if group["determination_state"] in ("DETERMINED_ALE", "DETERMINED_NON_ALE"):
            sync.set_field(group, "determination_state", "LOCKED")
    return ok(season)


# --------------------------------------------------------------------------- #
# ControlledGroup
# --------------------------------------------------------------------------- #
@bp.post("/controlled-groups")
def create_group():
    require_roles("ComplianceOfficer")
    data = body()
    filing_season_id = string_field(data, "filing_season_id")
    name = string_field(data, "name")
    lk.find("filing_seasons", filing_season_id)
    record = insert(
        "controlled_groups",
        {
            "filing_season_id": filing_season_id,
            "name": name,
            "determination_state": "NOT_DETERMINED",
            "determination_basis": None,
            "single_member_id": None,
            "monthly_group_fte": [],
            "annual_average_fte_raw": None,
            "annual_average_fte": None,
            "ale_reason": None,
            "seasonal_exception_applied": False,
            "open_correction_count": 0,
            "determined_at": None,
            "last_determination_user_id": None,
        },
    )
    return created(record)


@bp.get("/controlled-groups")
def list_groups():
    return listing(
        "controlled_groups",
        {
            "filing_season_id": ("filing_season_id", "str"),
            "determination_state": ("determination_state", "str"),
        },
        READ_ROLES,
    )


@bp.get("/controlled-groups/<identifier>")
def read_group(identifier):
    return single_read("controlled_groups", identifier, READ_ROLES)


@bp.post("/controlled-groups/<group_id>/ale-determination")
def ale_determination(group_id):
    user_id, _role = require_roles("ComplianceOfficer")
    data = body()
    basis = enum_field(data, "basis", ("AGGREGATED", "SINGLE_MEMBER"))
    expected = int_field(data, "expected_controlled_group_version", minimum=0)
    single_member_id = string_field(
        data, "single_member_id", required=(basis == "SINGLE_MEMBER")
    )

    group = lk.find("controlled_groups", group_id)
    member = None
    if basis == "SINGLE_MEMBER":
        member = lk.find("group_members", single_member_id)
        if member["controlled_group_id"] != group["id"]:
            fail("ERR_SCOPE_MISMATCH", "That member does not belong to this controlled group.")

    season = lk.season_of_group(group)
    require_season_open(season)
    require_group_unlocked(group)
    if expected != group["version"]:
        fail("ERR_STALE_GROUP_VERSION", "The controlled group has changed since it was read.")

    counted = [member] if member is not None else lk.members_of_group(group, active_only=True)
    for one in counted:
        months = set(
            row["month"] for row in lk.headcounts_of_member(one, "PRIOR_YEAR") if 1 <= row["month"] <= 12
        )
        if len(months) < 12:
            fail("ERR_HEADCOUNT_INCOMPLETE", "Twelve prior-year headcount months are required.")

    result = calc.aggregate_fte_and_status(counted)
    sync.set_field(group, "monthly_group_fte", result["monthly_group_fte"])
    sync.set_field(group, "annual_average_fte_raw", result["annual_average_fte_raw"])
    sync.set_field(group, "annual_average_fte", result["annual_average_fte"])
    sync.set_field(group, "determination_basis", basis)
    sync.set_field(group, "single_member_id", single_member_id if member is not None else None)
    sync.set_field(group, "ale_reason", result["ale_reason"])
    sync.set_field(group, "seasonal_exception_applied", result["seasonal_exception_applied"])
    sync.set_field(group, "determination_state", result["determination_state"])
    sync.set_field(group, "determined_at", clock_iso())
    sync.set_field(group, "last_determination_user_id", user_id)
    touch(group)

    if result["determination_state"] == "DETERMINED_ALE":
        for one in lk.members_of_group(group, active_only=True):
            sync.set_field(one, "reporting_year_ft_months", calc.reporting_year_ft_months(one))
    return ok(group)


@bp.post("/controlled-groups/<group_id>/reopen")
def reopen_group(group_id):
    require_roles("ComplianceOfficer")
    data = body()
    string_field(data, "reason", required=False)

    group = lk.find("controlled_groups", group_id)
    season = lk.season_of_group(group)
    require_season_open(season)
    require_group_unlocked(group)
    if group["determination_state"] not in ("DETERMINED_ALE", "DETERMINED_NON_ALE"):
        fail("ERR_GROUP_NOT_DETERMINED_ALE", "Only a determined group can be reopened.")
    if group["determination_state"] == "DETERMINED_ALE":
        for member in lk.members_of_group(group):
            for transmittal in lk.transmittals_of_member(member):
                if transmittal["status"] in SENT_TO_AGENCY:
                    fail(
                        "ERR_TRANSMITTAL_STATE_INVALID",
                        "A submission of this group has already gone to the agency.",
                    )

    sync.set_field(group, "determination_state", "REOPENED")
    sync.set_field(group, "determination_basis", None)
    sync.set_field(group, "ale_reason", None)
    sync.set_field(group, "annual_average_fte", None)
    sync.set_field(group, "annual_average_fte_raw", None)
    sync.set_field(group, "monthly_group_fte", [])
    sync.set_field(group, "determined_at", None)
    touch(group)
    return ok(group)


# --------------------------------------------------------------------------- #
# GroupMember
# --------------------------------------------------------------------------- #
@bp.post("/group-members")
def create_member():
    require_roles("ComplianceOfficer")
    data = body()
    controlled_group_id = string_field(data, "controlled_group_id")
    ein = digits_field(data, "ein", 9)
    legal_name = string_field(data, "legal_name")
    ownership_pct = number_field(data, "ownership_pct", gt=0, lte=100)
    method = enum_field(
        data, "measurement_method", ("LOOK_BACK", "MONTHLY"), required=False, default="LOOK_BACK"
    )

    group = lk.find("controlled_groups", controlled_group_id)
    require_group_unlocked(group)
    for existing in lk.members_of_group(group):
        if existing["ein"] == ein:
            fail("ERR_DUPLICATE_RESOURCE", "That EIN is already registered in this group.")

    record = insert(
        "group_members",
        {
            "controlled_group_id": controlled_group_id,
            "ein": ein,
            "legal_name": legal_name,
            "ownership_pct": ownership_pct,
            "measurement_method": method,
            "member_status": "ACTIVE",
            "generated_form_count": 0,
            "unattached_form_count": 0,
            "attached_form_count": 0,
            "reporting_year_ft_months": 0,
            "allocated_exclusion_employees": 0,
            "allocated_penalty_cents": 0,
            "furnishing_penalty_total_cents": 0,
            "open_transmittal_id": None,
        },
    )
    return created(record)


@bp.get("/group-members")
def list_members():
    return listing(
        "group_members",
        {
            "controlled_group_id": ("controlled_group_id", "str"),
            "member_status": ("member_status", "str"),
        },
        READ_ROLES,
    )


@bp.get("/group-members/<identifier>")
def read_member(identifier):
    return single_read("group_members", identifier, READ_ROLES)


@bp.patch("/group-members/<member_id>")
def update_member(member_id):
    require_roles("ComplianceOfficer")
    data = body()
    method = enum_field(data, "measurement_method", ("LOOK_BACK", "MONTHLY"), required=False)
    status = enum_field(data, "member_status", ("ACTIVE", "INACTIVE"), required=False)

    member = lk.find("group_members", member_id)
    require_group_unlocked(lk.group_of_member(member))
    if method is not None:
        member["measurement_method"] = method
    if status is not None:
        member["member_status"] = status
    touch(member)
    return ok(member)


# --------------------------------------------------------------------------- #
# MonthlyHeadcount
# --------------------------------------------------------------------------- #
@bp.post("/monthly-headcounts")
def create_headcounts():
    require_roles("ComplianceOfficer", "BenefitsAdmin")
    data = body()
    group_member_id = string_field(data, "group_member_id")
    count_year = enum_field(data, "count_year", COUNT_YEARS)
    months = month_list_field(data, "months")
    full_time_employee_count = int_field(data, "full_time_employee_count", minimum=0)
    part_time_hours_total = int_field(data, "part_time_hours_total", minimum=0)
    total_employee_count = int_field(data, "total_employee_count", minimum=0)
    seasonal_excess_count = int_field(
        data, "seasonal_excess_count", required=False, default=0, minimum=0
    )

    member = lk.find("group_members", group_member_id)

    taken = set(
        row["month"] for row in lk.headcounts_of_member(member, count_year)
    )
    seen = set()
    for month in months:
        if month in taken or month in seen:
            fail(
                "ERR_DUPLICATE_HEADCOUNT_MONTH",
                "A headcount row already exists for month %d." % month,
            )
        seen.add(month)

    created_rows = []
    for month in sorted(months):
        member_fte = calc.as_number(
            calc.dec(full_time_employee_count)
            + calc.round_half_up(calc.dec(part_time_hours_total) / calc.FTE_HOURS_DIVISOR, 2)
        )
        created_rows.append(
            insert(
                "monthly_headcounts",
                {
                    "group_member_id": group_member_id,
                    "count_year": count_year,
                    "month": month,
                    "full_time_employee_count": full_time_employee_count,
                    "part_time_hours_total": part_time_hours_total,
                    "total_employee_count": total_employee_count,
                    "seasonal_excess_count": seasonal_excess_count,
                    "member_fte": member_fte,
                },
            )
        )
    return created_collection(created_rows)


@bp.get("/monthly-headcounts")
def list_headcounts():
    return listing(
        "monthly_headcounts",
        {
            "group_member_id": ("group_member_id", "str"),
            "count_year": ("count_year", "str"),
            "month": ("month", "int"),
        },
        READ_ROLES,
    )


@bp.get("/monthly-headcounts/<identifier>")
def read_headcount(identifier):
    return single_read("monthly_headcounts", identifier, READ_ROLES)


# --------------------------------------------------------------------------- #
# logical clock
# --------------------------------------------------------------------------- #
@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(*OPERATOR_ROLES)
    data = body()
    raw = data.get("to_iso8601")
    if raw is None:
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required.")
    parsed = parse_iso8601(raw, "to_iso8601")
    db.clock = parsed
    from db import fmt_dt

    return ok_raw({"current_utc": fmt_dt(parsed)})
