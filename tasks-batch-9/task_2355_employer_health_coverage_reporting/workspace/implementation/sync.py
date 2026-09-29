"""Derived counters, the correction-count chain and the cascade side effects."""

from db import clock_iso, db, insert, rows, touch
import calc
import lookups as lk

VOIDED = "VOIDED"
FURNISHED = ("FURNISHED_PAPER", "FURNISHED_ELECTRONIC")
ATTACHED_STATES = (
    "ATTACHED",
    "PENDING_FILING",
    "FILED_ACCEPTED",
    "FILED_WITH_ERRORS",
    "CORRECTION_DRAFTED",
)
OPEN_TRANSMITTAL_STATES = (
    "DRAFT",
    "BUILT",
    "TRANSMITTED",
    "ACCEPTED_WITH_ERRORS",
    "PARTIALLY_ACCEPTED",
    "REJECTED",
    "CORRECTION_REQUIRED",
)
FILED_STATES = ("FILED_ACCEPTED", "FILED_WITH_ERRORS", "CORRECTION_DRAFTED")


def set_field(record, field, value):
    """Assign and version-bump only when the stored value actually changes."""
    if record.get(field) != value:
        record[field] = value
        touch(record)


def set_fields(record, values):
    for field, value in values.items():
        set_field(record, field, value)


# --------------------------------------------------------------------------- #
# derived counters
# --------------------------------------------------------------------------- #
def sync_member(member):
    forms = []
    for employee in rows("employees"):
        if employee["group_member_id"] == member["id"]:
            forms.extend(lk.forms_of_employee(employee))
    live = [f for f in forms if lk.is_live(f)]
    set_field(member, "generated_form_count", len(live))
    set_field(
        member,
        "unattached_form_count",
        sum(1 for f in live if f["filing_status"] == "NOT_FILED"),
    )
    set_field(
        member,
        "attached_form_count",
        sum(1 for f in live if f["filing_status"] in ATTACHED_STATES),
    )
    set_field(
        member,
        "furnishing_penalty_total_cents",
        sum(f.get("late_furnishing_penalty_cents") or 0 for f in forms),
    )
    open_ones = [
        t for t in lk.transmittals_of_member(member) if t["status"] in OPEN_TRANSMITTAL_STATES
    ]
    open_id = max(open_ones, key=lambda t: t["_seq"])["id"] if open_ones else None
    set_field(member, "open_transmittal_id", open_id)


def group_forms(group):
    forms = []
    for employee in lk.employees_of_group(group):
        forms.extend(lk.forms_of_employee(employee))
    return forms


def sync_group(group):
    count = sum(
        1
        for f in group_forms(group)
        if f["furnishing_status"] == "REDELIVERY_REQUIRED"
        or f["filing_status"] == "CORRECTION_DRAFTED"
    )
    set_field(group, "open_correction_count", count)
    if count > 0 and group["determination_state"] == "DETERMINED_ALE":
        set_field(group, "determination_state", "CORRECTION_OPEN")
    elif count == 0 and group["determination_state"] == "CORRECTION_OPEN":
        set_field(group, "determination_state", "DETERMINED_ALE")


def sync_season(season):
    count = sum(
        1
        for g in rows("controlled_groups")
        if g["filing_season_id"] == season["id"] and g["determination_state"] == "CORRECTION_OPEN"
    )
    set_field(season, "open_correction_count", count)


def sync_transmittal(transmittal):
    forms = [f for f in lk.forms_of_transmittal(transmittal) if f["filing_status"] != VOIDED]
    set_field(transmittal, "form_count", len(forms))
    errors = lk.errors_of_transmittal(transmittal)
    set_field(transmittal, "error_count", len(errors))
    set_field(
        transmittal,
        "open_error_count",
        sum(1 for e in errors if e["resolution_status"] == "OPEN"),
    )


def sync_notice(notice):
    set_field(notice, "evidence_count", len(lk.evidence_of_notice(notice)))


def sync_all():
    """Refresh every derived counter after a mutating request."""
    for member in rows("group_members"):
        sync_member(member)
    for transmittal in rows("transmittals"):
        sync_transmittal(transmittal)
    for group in rows("controlled_groups"):
        sync_group(group)
    for season in rows("filing_seasons"):
        sync_season(season)
    for notice in rows("penalty_notices"):
        sync_notice(notice)


# --------------------------------------------------------------------------- #
# form / line writing
# --------------------------------------------------------------------------- #
LINE_FIELDS = (
    "line14_code",
    "line15_amount_cents",
    "line16_code",
    "full_time_flag",
    "ft_source",
    "affordability_threshold_cents",
    "safe_harbor_applied",
    "special_situation",
    "assessable",
)


def write_lines(form, computed):
    """Create the twelve lines, or rewrite them in place when they exist."""
    existing = dict((l["month"], l) for l in lk.lines_of_form(form))
    for line in computed:
        row = existing.get(line["month"])
        if row is None:
            record = {"form_1095c_id": form["id"], "month": line["month"]}
            for field in LINE_FIELDS:
                record[field] = line[field]
            insert("monthly_coverage_lines", record)
        else:
            for field in LINE_FIELDS:
                row[field] = line[field]


def copy_lines(source_form, target_form):
    for line in lk.lines_of_form(source_form):
        record = {"form_1095c_id": target_form["id"], "month": line["month"]}
        for field in LINE_FIELDS:
            record[field] = line[field]
        insert("monthly_coverage_lines", record)


def apply_rollups(form, rollup):
    for field, value in rollup.items():
        set_field(form, field, value)


def refresh_rollups(form):
    apply_rollups(form, calc.rollup(lk.lines_of_form(form)))


def write_employee_full_time(employee, full_time, sources, average):
    months = [m for m in range(1, 13) if full_time[m - 1]]
    set_field(employee, "full_time_months", months)
    set_field(employee, "full_time_month_count", len(months))
    set_field(employee, "measured_average_hours", calc.as_number(average))
    set_field(employee, "ft_source_by_month", list(sources))
    set_field(employee, "last_recomputed_at", clock_iso())


def resolve_effective_method(employee):
    member = lk.member_of_employee(employee)
    method = employee.get("measurement_method_override") or (
        member["measurement_method"] if member else "LOOK_BACK"
    )
    set_field(employee, "effective_measurement_method", method)
    return method


def new_form_record(employee, plan_start_month, preference, user_id):
    return {
        "employee_id": employee["id"],
        "transmittal_id": None,
        "corrected_from_form_id": None,
        "form_type": "ORIGINAL",
        "plan_start_month": plan_start_month,
        "safe_harbor_preference": preference,
        "furnishing_status": "NOT_FURNISHED",
        "filing_status": "NOT_FILED",
        "all_12_months_code": None,
        "ft_month_count": 0,
        "offered_month_count": 0,
        "assessable_month_count": 0,
        "line15_total_cents": 0,
        "generated_by_user_id": user_id,
        "furnished_by_user_id": None,
        "furnished_at": None,
        "late_furnishing_penalty_cents": 0,
        "correction_reason": None,
    }


def draft_correction(source_form, employee, season, reason, user_id):
    """Create the CORRECTED successor of `source_form` with fresh lines."""
    record = new_form_record(
        employee,
        source_form["plan_start_month"],
        source_form["safe_harbor_preference"],
        user_id,
    )
    record["form_type"] = "CORRECTED"
    record["corrected_from_form_id"] = source_form["id"]
    record["correction_reason"] = reason
    correction = insert("forms_1095c", record)

    computed = None
    try:
        computed = calc.compute_lines(employee, season, source_form["safe_harbor_preference"])
    except Exception:
        computed = None
    if computed is None:
        copy_lines(source_form, correction)
        refresh_rollups(correction)
    else:
        lines, rollup, full_time, sources, average = computed
        write_lines(correction, lines)
        apply_rollups(correction, rollup)
        write_employee_full_time(employee, full_time, sources, average)
    return correction


# --------------------------------------------------------------------------- #
# cascades
# --------------------------------------------------------------------------- #
def open_correction_on_form(form):
    """LINK 3: move whichever dimensions have already left the building."""
    if form["furnishing_status"] in FURNISHED:
        set_field(form, "furnishing_status", "REDELIVERY_REQUIRED")
    if form["filing_status"] in ("FILED_ACCEPTED", "FILED_WITH_ERRORS"):
        set_field(form, "filing_status", "CORRECTION_DRAFTED")


def termination_cascade(employee, effective_date):
    """LINK 2 and LINK 3 of the termination chain (LINK 4/5 land in sync_all)."""
    form = lk.live_form(employee)
    if form is None:
        return
    season = lk.season_of_employee(employee)
    if season is None:
        return
    _, term_month = calc.year_pinned_months(employee, season["tax_year"])
    if term_month is None:
        return
    offers = lk.offers_of_employee(employee)
    for line in lk.lines_of_form(form):
        month = line["month"]
        if month > term_month:
            line["line14_code"] = "1H"
            line["line15_amount_cents"] = None
            line["line16_code"] = "2A"
            line["full_time_flag"] = False
            line["ft_source"] = "NOT_EMPLOYED"
            line["assessable"] = False
        elif month == term_month:
            line["special_situation"] = "TERMINATION"
            offer = calc.governing_offer(offers, month)
            if offer is not None and offer["offer_kind"] != "NO_OFFER":
                line["line16_code"] = "2B"
                line["assessable"] = False
    refresh_rollups(form)
    open_correction_on_form(form)


def leave_end_cascade(employee):
    form = lk.live_form(employee)
    if form is None:
        return
    excluded_months = set(
        row["month"] for row in lk.hours_of_employee(employee) if row["excluded_from_denominator"]
    )
    if not excluded_months:
        return
    for line in lk.lines_of_form(form):
        if line["month"] in excluded_months:
            line["special_situation"] = "LEAVE"


def transfer_cascade(employee, effective_date):
    form = lk.live_form(employee)
    if form is None:
        return
    month = int(effective_date[5:7])
    for line in lk.lines_of_form(form):
        if line["month"] == month:
            line["special_situation"] = "TRANSFER"


def consent_withdrawal_cascade(employee):
    for form in lk.forms_of_employee(employee):
        if form["furnishing_status"] == "FURNISHED_ELECTRONIC":
            set_field(form, "furnishing_status", "REDELIVERY_REQUIRED")


def refresh_lines_from_recompute(form, full_time, sources):
    """The employee recompute refreshes only these three per-month fields."""
    for line in lk.lines_of_form(form):
        index = line["month"] - 1
        line["full_time_flag"] = full_time[index]
        line["ft_source"] = sources[index]
        line["assessable"] = bool(full_time[index] and line["line16_code"] is None)
    refresh_rollups(form)


def zero_member_allocations(group):
    for member in lk.members_of_group(group, active_only=True):
        set_field(member, "allocated_penalty_cents", 0)


def invalidate_recomputation(notice, group):
    set_field(notice, "a_month_penalty_cents", None)
    set_field(notice, "b_month_penalty_cents", None)
    set_field(notice, "recalculated_amount_cents", None)
    set_field(notice, "recomputed_at", None)
    zero_member_allocations(group)
    set_field(notice, "allocated_total_cents", 0)
    set_field(notice, "unallocated_amount_cents", 0)
