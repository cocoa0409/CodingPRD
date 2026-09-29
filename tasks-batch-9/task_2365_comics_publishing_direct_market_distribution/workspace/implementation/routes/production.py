"""Issues, the production board, printings and release windows
(PRD 3.2, 3.3, 3.7)."""

from flask import Blueprint

from core import (
    COLLECTED_BLACKOUT_DAYS,
    COMMERCIAL_STATUSES,
    COVER_KINDS,
    CRAFTS,
    DIGITAL_EMBARGO_DAYS,
    FOC_LEAD_DAYS,
    INCENTIVE_RATIOS,
    ON_SALE_CADENCE_DAYS,
    PRINT_BASES,
    PRINT_RUN_STATUSES,
    PRODUCTION_STATUSES,
    RELEASE_CHANNELS,
    REPRINT_COLLECTED_GUARD_DAYS,
    REVENUE_CHANNELS,
    BASIS_STATUSES,
    SOLICITATION_STATUSES,
    STAGE_STATUSES,
    ApiError,
    apply_fields,
    auth,
    bad,
    created_row,
    date_of,
    day_diff,
    db,
    fmt_dt,
    get_body,
    ok_list,
    ok_row,
    page,
    q_enum,
    q_month,
    shift_days,
    touch,
    v_datetime,
    v_enum,
    v_int,
    v_str,
)
from calc import (
    demand_forecast_quantity,
    order_driven_quantity,
    stage_slip_days,
    variant_incentive_allocation,
)
import services as svc

title_issues_bp = Blueprint("title_issues", __name__, url_prefix="/comics/titles")
issues_bp = Blueprint("issues", __name__, url_prefix="/comics/issues")
stages_bp = Blueprint("stages", __name__, url_prefix="/comics/production-stages")
print_runs_bp = Blueprint("print_runs", __name__, url_prefix="/comics/print-runs")

STAFFABLE_TITLE_STATUSES = ("GREENLIT", "IN_PRODUCTION", "PUBLISHING")


# ---------------------------------------------------------------------------
# Issue slate
# ---------------------------------------------------------------------------


@title_issues_bp.post("/<title_id>/issues")
def create_issue(title_id):
    auth(("ManagingEditor",))
    body = get_body()
    issue_number = v_int(body, "issue_number", required=True, minimum=1)
    page_count = v_int(body, "page_count", required=True, minimum=1, maximum=64)
    cover_price_cents = v_int(body, "cover_price_cents", required=True, minimum=1)
    target_on_sale_date = v_datetime(body, "target_on_sale_date", required=True)

    title = svc.get_title(title_id)
    if title["status"] not in STAFFABLE_TITLE_STATUSES:
        raise ApiError(
            "ERR_TITLE_NOT_GREENLIT",
            "A %s title cannot take new issues." % title["status"],
        )

    siblings = svc.title_issues(title["id"])
    for sibling in siblings:
        if sibling["commercial_status"] == "CANCELLED":
            continue
        gap = abs(day_diff(target_on_sale_date, sibling["target_on_sale_date"]))
        if gap < ON_SALE_CADENCE_DAYS:
            raise ApiError(
                "ERR_ON_SALE_CADENCE_CONFLICT",
                "The on-sale date must be at least %d calendar days from every sibling issue."
                % ON_SALE_CADENCE_DAYS,
            )
    if any(s["issue_number"] == issue_number for s in siblings):
        raise ApiError(
            "ERR_DUPLICATE_ISSUE_NUMBER",
            "Issue number %d already exists for this title." % issue_number,
        )

    row = db.new_row(
        title_id=title["id"],
        issue_number=issue_number,
        page_count=page_count,
        cover_price_cents=cover_price_cents,
        target_on_sale_date=fmt_dt(target_on_sale_date),
        foc_date=shift_days(target_on_sale_date, -FOC_LEAD_DAYS),
        production_status="PLANNED",
        commercial_status="UNSOLICITED",
        schedule_health="ON_TRACK",
        total_slip_days=0,
        total_ordered_units=0,
        printed_units=0,
        shipped_units=0,
        on_sale_date=None,
    )
    db.issues[row["id"]] = row
    svc.title_first_issue_created(title)
    return created_row(svc.issue_json, row)


@title_issues_bp.get("/<title_id>/issues")
def list_title_issues(title_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    commercial_status = q_enum("commercial_status", COMMERCIAL_STATUSES)
    production_status = q_enum("production_status", PRODUCTION_STATUSES)
    title = svc.get_title(title_id)
    rows = svc.title_issues(title["id"])
    if commercial_status is not None:
        rows = [r for r in rows if r["commercial_status"] == commercial_status]
    if production_status is not None:
        rows = [r for r in rows if r["production_status"] == production_status]
    window, meta = page(rows)
    return ok_list(svc.issue_json, window, meta)


@issues_bp.get("/<issue_id>")
def read_issue(issue_id):
    auth((
        "EditorInChief",
        "ManagingEditor",
        "SalesDirector",
        "RoyaltyAccountant",
        "Creator",
        "Retailer",
    ))
    return ok_row(svc.issue_json, svc.get_issue(issue_id))


# ---------------------------------------------------------------------------
# Production stages
# ---------------------------------------------------------------------------


@issues_bp.post("/<issue_id>/production-stages")
def book_stage(issue_id):
    auth(("ManagingEditor",))
    body = get_body()
    assignment_id = v_str(body, "assignment_id", required=True, min_len=1)
    craft = v_enum(body, "craft", CRAFTS, required=True)
    planned_start = v_datetime(body, "planned_start_date", required=True)
    planned_due = v_datetime(body, "planned_due_date", required=True)
    if planned_due < planned_start:
        bad("Field 'planned_due_date' must be on or after 'planned_start_date'.")

    issue = svc.get_issue(issue_id)
    assignment = svc.get_assignment(assignment_id)

    if issue["production_status"] == "CANCELLED":
        raise ApiError(
            "ERR_INVALID_STATE", "A cancelled issue cannot take new production stages."
        )
    if assignment["craft"] != craft:
        raise ApiError(
            "ERR_CRAFT_MISMATCH",
            "The stage craft %s differs from the assignment craft %s."
            % (craft, assignment["craft"]),
        )
    if assignment["title_id"] != issue["title_id"]:
        raise ApiError(
            "ERR_TITLE_SCOPE_MISMATCH",
            "The referenced assignment belongs to another title.",
        )

    row = db.new_row(
        issue_id=issue["id"],
        assignment_id=assignment["id"],
        craft=craft,
        planned_start_date=fmt_dt(planned_start),
        planned_due_date=fmt_dt(planned_due),
        actual_delivered_at=None,
        delivered_pages=None,
        slip_days=0,
        page_fee_cents=0,
        kickback_count=0,
        status="NOT_STARTED",
    )
    db.stages[row["id"]] = row
    svc.derive_production_status(issue)
    return created_row(svc.stage_json, row)


@issues_bp.get("/<issue_id>/production-stages")
def list_issue_stages(issue_id):
    auth(("EditorInChief", "ManagingEditor", "Creator"))
    craft = q_enum("craft", CRAFTS)
    status = q_enum("status", STAGE_STATUSES)
    issue = svc.get_issue(issue_id)
    rows = svc.issue_stages(issue["id"])
    if craft is not None:
        rows = [r for r in rows if r["craft"] == craft]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.stage_json, window, meta)


@stages_bp.get("/<stage_id>")
def read_stage(stage_id):
    auth(("EditorInChief", "ManagingEditor", "Creator"))
    return ok_row(svc.stage_json, svc.get_stage(stage_id))


def _own_stage(stage, user_id):
    assignment = svc.get_assignment(stage["assignment_id"])
    if assignment["creator_id"] != user_id:
        raise ApiError(
            "ERR_FORBIDDEN_RESOURCE",
            "This stage was booked against another creator's assignment.",
        )
    return assignment


@stages_bp.post("/<stage_id>/start")
def start_stage(stage_id):
    user_id, _role = auth(("Creator",))
    stage = svc.get_stage(stage_id)
    assignment = _own_stage(stage, user_id)
    if stage["status"] not in ("NOT_STARTED", "KICKED_BACK"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "A %s stage cannot be started." % stage["status"],
        )
    issue = svc.get_issue(stage["issue_id"])
    if issue["production_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "The issue's production has been cancelled.")

    if stage["status"] == "NOT_STARTED":
        allowed = ("ACCEPTED", "ACTIVE")
    else:
        allowed = ("ACTIVE",)
    if assignment["status"] not in allowed:
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ACCEPTED",
            "The referenced assignment is %s." % assignment["status"],
        )

    apply_fields(stage, status="IN_PROGRESS")
    if assignment["status"] == "ACCEPTED":
        apply_fields(assignment, status="ACTIVE")
    svc.derive_production_status(issue)
    return ok_row(svc.stage_json, stage)


@stages_bp.post("/<stage_id>/deliver")
def deliver_stage(stage_id):
    user_id, _role = auth(("Creator",))
    body = get_body()
    delivered_pages = v_int(body, "delivered_pages", required=True, minimum=1)
    stage = svc.get_stage(stage_id)
    issue = svc.get_issue(stage["issue_id"])
    if delivered_pages > issue["page_count"]:
        bad(
            "Field 'delivered_pages' may not exceed the issue's page count of %d."
            % issue["page_count"]
        )
    _own_stage(stage, user_id)
    if stage["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only an IN_PROGRESS stage may be delivered, not %s." % stage["status"],
        )

    delivered_at = db.now()
    apply_fields(
        stage,
        status="DELIVERED",
        actual_delivered_at=delivered_at,
        delivered_pages=delivered_pages,
        slip_days=stage_slip_days(delivered_at, stage["planned_due_date"]),
    )
    if svc.recompute_issue_slip(issue):
        svc.slip_cascade(issue)
    svc.derive_production_status(issue)
    return ok_row(svc.stage_json, stage)


@stages_bp.post("/<stage_id>/kick-back")
def kick_back_stage(stage_id):
    auth(("ManagingEditor",))
    body = get_body()
    v_str(body, "note", required=True, min_len=1, max_len=1000)
    stage = svc.get_stage(stage_id)
    if stage["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DELIVERED stage may be kicked back, not %s." % stage["status"],
        )
    apply_fields(
        stage, status="KICKED_BACK", kickback_count=stage["kickback_count"] + 1
    )
    svc.derive_production_status(svc.get_issue(stage["issue_id"]))
    return ok_row(svc.stage_json, stage)


@stages_bp.post("/<stage_id>/approve")
def approve_stage(stage_id):
    auth(("ManagingEditor",))
    stage = svc.get_stage(stage_id)
    if stage["status"] != "DELIVERED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a DELIVERED stage may be approved, not %s." % stage["status"],
        )
    assignment = svc.get_assignment(stage["assignment_id"])
    issue = svc.get_issue(stage["issue_id"])
    title = svc.get_title(issue["title_id"])

    apply_fields(
        stage,
        status="APPROVED",
        page_fee_cents=assignment["page_rate_cents"] * stage["delivered_pages"],
    )
    svc.recompute_title_production_cost(title)

    booked = [s for s in svc.assignment_stages(assignment["id"]) if s["status"] != "CANCELLED"]
    if assignment["status"] == "ACTIVE" and booked and all(
        s["status"] == "APPROVED" for s in booked
    ):
        apply_fields(assignment, status="COMPLETED")
        creator = db.creators.get(assignment["creator_id"])
        if creator is not None:
            svc.recompute_creator_active_count(creator)

    svc.derive_production_status(issue)
    return ok_row(svc.stage_json, stage)


# ---------------------------------------------------------------------------
# Variant covers
# ---------------------------------------------------------------------------


@issues_bp.post("/<issue_id>/variant-covers")
def create_variant_cover(issue_id):
    auth(("SalesDirector",))
    body = get_body()
    code = v_str(body, "code", required=True, min_len=1, max_len=8)
    kind = v_enum(body, "kind", COVER_KINDS, required=True)
    incentive_ratio = v_int(body, "incentive_ratio")
    cover_price_cents = v_int(body, "cover_price_cents", required=True, minimum=1)
    allocation_cap = v_int(body, "allocation_cap", minimum=1)

    issue = svc.get_issue(issue_id)
    if issue["commercial_status"] == "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", "A cancelled issue cannot take new covers.")

    if any(c["code"] == code for c in svc.issue_covers(issue["id"])):
        raise ApiError(
            "ERR_DUPLICATE_VARIANT_CODE",
            "Cover code '%s' already exists on this issue." % code,
        )

    if kind == "RATIO_INCENTIVE":
        if incentive_ratio not in INCENTIVE_RATIOS:
            raise ApiError(
                "ERR_VARIANT_RATIO_INVALID",
                "A RATIO_INCENTIVE cover requires an incentive_ratio of 10, 25, 50 or 100.",
            )
    elif incentive_ratio is not None:
        raise ApiError(
            "ERR_VARIANT_RATIO_INVALID",
            "Only a RATIO_INCENTIVE cover may carry an incentive_ratio.",
        )

    row = db.new_row(
        versioned=False,
        issue_id=issue["id"],
        code=code,
        kind=kind,
        incentive_ratio=incentive_ratio if kind == "RATIO_INCENTIVE" else None,
        cover_price_cents=cover_price_cents,
        allocation_cap=allocation_cap,
    )
    db.variant_covers[row["id"]] = row
    return created_row(svc.variant_cover_json, row)


@issues_bp.get("/<issue_id>/variant-covers")
def list_variant_covers(issue_id):
    auth(("EditorInChief", "SalesDirector", "Retailer"))
    kind = q_enum("kind", COVER_KINDS)
    issue = svc.get_issue(issue_id)
    rows = svc.issue_covers(issue["id"])
    if kind is not None:
        rows = [r for r in rows if r["kind"] == kind]
    window, meta = page(rows)
    return ok_list(svc.variant_cover_json, window, meta)


# ---------------------------------------------------------------------------
# Final order cut-off and release
# ---------------------------------------------------------------------------


@issues_bp.post("/<issue_id>/foc-lock")
def foc_lock(issue_id):
    auth(("SalesDirector",))
    issue = svc.get_issue(issue_id)
    if issue["commercial_status"] != "SOLICITED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "The final order cut-off may only be locked from SOLICITED, not %s."
            % issue["commercial_status"],
        )
    if date_of(db.now()) < date_of(issue["foc_date"]):
        raise ApiError(
            "ERR_FOC_NOT_REACHED",
            "The final order cut-off date has not been reached yet.",
        )
    submitted = [o for o in svc.issue_orders(issue["id"]) if o["status"] == "SUBMITTED"]
    if not submitted:
        raise ApiError(
            "ERR_NO_QUALIFYING_ORDERS", "The issue carries no submitted orders to lock."
        )

    covers = svc.issue_covers(issue["id"])
    # Eligibility for retailer-exclusive covers reads the units as they stand
    # BEFORE this lock adds any of the order units it is about to freeze.
    units_before = {
        r["id"]: r["cumulative_units_ytd"] for r in db.retailers.values()
    }

    affected_retailers = {}
    for order in submitted:
        retailer = db.retailers.get(order["retailer_id"])
        before = units_before.get(order["retailer_id"], 0)
        allocations, total_units = variant_incentive_allocation(order, covers, before)
        apply_fields(
            order,
            earned_variant_allocations=allocations,
            total_units=total_units,
            status="FOC_LOCKED",
        )
        if retailer is not None:
            affected_retailers[retailer["id"]] = retailer

    for retailer in affected_retailers.values():
        svc.recompute_retailer_units(retailer)
    svc.recompute_issue_order_units(issue)
    apply_fields(issue, commercial_status="FOC_LOCKED")
    return ok_row(svc.issue_json, issue)


@issues_bp.post("/<issue_id>/release")
def release_issue(issue_id):
    auth(("SalesDirector",))
    issue = svc.get_issue(issue_id)
    if issue["commercial_status"] != "PRINTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "An issue goes on sale from PRINTED, not %s." % issue["commercial_status"],
        )
    if issue["production_status"] != "CAMERA_READY":
        raise ApiError(
            "ERR_NOT_CAMERA_READY", "The issue's production dimension is not CAMERA_READY."
        )
    if date_of(db.now()) < date_of(issue["target_on_sale_date"]):
        raise ApiError(
            "ERR_ON_SALE_DATE_NOT_REACHED", "The target on-sale date has not arrived."
        )
    apply_fields(issue, commercial_status="ON_SALE", on_sale_date=db.now())
    svc.title_issue_went_on_sale(svc.get_title(issue["title_id"]))
    return ok_row(svc.issue_json, issue)


# ---------------------------------------------------------------------------
# Print runs
# ---------------------------------------------------------------------------


@issues_bp.post("/<issue_id>/print-runs")
def create_print_run(issue_id):
    auth(("ManagingEditor",))
    body = get_body()
    basis = v_enum(body, "basis", PRINT_BASES, required=True)
    expected_issue_version = v_int(body, "expected_issue_version", required=True)

    issue = svc.get_issue(issue_id)
    if expected_issue_version != issue["version"]:
        raise ApiError(
            "ERR_STALE_ISSUE_VERSION",
            "Expected issue version %s but the issue is at version %s."
            % (expected_issue_version, issue["version"]),
        )

    runs = svc.issue_print_runs(issue["id"])
    printed_runs = [r for r in runs if r["status"] == "PRINTED"]
    if basis == "ORDER_DRIVEN":
        if issue["commercial_status"] not in ("FOC_LOCKED", "PRINTED", "ON_SALE"):
            raise ApiError(
                "ERR_INVALID_STATE",
                "An ORDER_DRIVEN printing cannot be planned while the issue is %s."
                % issue["commercial_status"],
            )
    else:
        if issue["commercial_status"] not in ("PRINTED", "ON_SALE") or not printed_runs:
            raise ApiError(
                "ERR_INVALID_STATE",
                "A DEMAND_FORECAST printing requires a printed issue with an existing printing.",
            )
        for window in svc.issue_release_windows(issue["id"]):
            if window["channel"] != "COLLECTED":
                continue
            gap = day_diff(window["release_date"], db.now())
            if 0 <= gap <= REPRINT_COLLECTED_GUARD_DAYS:
                raise ApiError(
                    "ERR_COLLECTED_EDITION_CONFLICT",
                    "A collected edition is released within %d days, so no reprint may be planned."
                    % REPRINT_COLLECTED_GUARD_DAYS,
                )

    orders = svc.issue_orders(issue["id"])
    if basis == "ORDER_DRIVEN":
        order_base_units = sum(
            o["total_units"]
            for o in orders
            if o["status"] in svc.COMMITTED_ORDER_STATUSES
        )
        if order_base_units == 0:
            raise ApiError(
                "ERR_NO_QUALIFYING_ORDERS",
                "The locked order book is empty, so there is nothing to print.",
            )
    if not svc.has_required_craft_stages(issue["id"]):
        raise ApiError(
            "ERR_REQUIRED_CRAFT_STAGES_MISSING",
            "The issue is missing a production stage for one of the required crafts.",
        )

    if basis == "ORDER_DRIVEN":
        overprint_units, quantity = order_driven_quantity(order_base_units)
    else:
        prior_printed = sum(r["quantity"] for r in printed_runs)
        reorder_units = sum(
            o["standard_qty"]
            for o in orders
            if o["status"] == "SUBMITTED" and o["is_reorder"]
        )
        order_base_units, overprint_units, quantity = demand_forecast_quantity(
            prior_printed, reorder_units
        )

    highest = max(
        [r["printing_number"] for r in runs if r["status"] in ("PLANNED", "PRINTED")]
        or [0]
    )
    row = db.new_row(
        issue_id=issue["id"],
        printing_number=highest + 1,
        basis=basis,
        quantity=quantity,
        order_base_units=order_base_units,
        overprint_units=overprint_units,
        status="PLANNED",
        printed_at=None,
        cancel_reason=None,
    )
    db.print_runs[row["id"]] = row
    touch(issue)
    return created_row(svc.print_run_json, row)


@issues_bp.get("/<issue_id>/print-runs")
def list_issue_print_runs(issue_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    status = q_enum("status", PRINT_RUN_STATUSES)
    basis = q_enum("basis", PRINT_BASES)
    issue = svc.get_issue(issue_id)
    rows = svc.issue_print_runs(issue["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    window, meta = page(rows)
    return ok_list(svc.print_run_json, window, meta)


@print_runs_bp.get("/<run_id>")
def read_print_run(run_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    return ok_row(svc.print_run_json, svc.get_print_run(run_id))


@print_runs_bp.post("/<run_id>/complete")
def complete_print_run(run_id):
    auth(("ManagingEditor",))
    run = svc.get_print_run(run_id)
    if run["status"] != "PLANNED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PLANNED printing may be completed, not %s." % run["status"],
        )
    issue = svc.get_issue(run["issue_id"])
    if issue["production_status"] != "CAMERA_READY":
        raise ApiError(
            "ERR_NOT_CAMERA_READY", "A book that is not camera-ready cannot go to press."
        )
    if not svc.has_required_craft_stages(issue["id"]):
        raise ApiError(
            "ERR_REQUIRED_CRAFT_STAGES_MISSING",
            "The issue is missing a production stage for one of the required crafts.",
        )
    apply_fields(run, status="PRINTED", printed_at=db.now())
    svc.recompute_issue_printed_units(issue)
    if run["printing_number"] == 1 and issue["commercial_status"] == "FOC_LOCKED":
        apply_fields(issue, commercial_status="PRINTED")
    return ok_row(svc.print_run_json, run)


@print_runs_bp.post("/<run_id>/cancel")
def cancel_print_run(run_id):
    auth(("ManagingEditor",))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    run = svc.get_print_run(run_id)
    if run["status"] != "PLANNED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Only a PLANNED printing may be cancelled, not %s." % run["status"],
        )
    apply_fields(run, status="CANCELLED", cancel_reason=reason)
    svc.recompute_issue_printed_units(svc.get_issue(run["issue_id"]))
    return ok_row(svc.print_run_json, run)


# ---------------------------------------------------------------------------
# Release windows and issue-scoped reads
# ---------------------------------------------------------------------------


@issues_bp.post("/<issue_id>/release-windows")
def create_release_window(issue_id):
    auth(("SalesDirector",))
    body = get_body()
    channel = v_enum(body, "channel", RELEASE_CHANNELS, required=True)
    release_date = v_datetime(body, "release_date", required=True)
    expected_net = v_int(body, "expected_net_receipts_cents", minimum=0, default=0)

    issue = svc.get_issue(issue_id)
    if issue["commercial_status"] == "CANCELLED":
        raise ApiError(
            "ERR_INVALID_STATE", "A cancelled issue cannot take release windows."
        )

    if channel == "DIGITAL":
        earliest = shift_days(issue["target_on_sale_date"], DIGITAL_EMBARGO_DAYS)
        if date_of(release_date) < date_of(earliest):
            raise ApiError(
                "ERR_DIGITAL_EMBARGO_VIOLATION",
                "A digital window may not land earlier than %d days after the on-sale date."
                % DIGITAL_EMBARGO_DAYS,
            )
    else:
        latest = None
        for sibling in svc.title_issues(issue["title_id"]):
            if sibling["commercial_status"] == "CANCELLED":
                continue
            if latest is None or sibling["target_on_sale_date"] > latest:
                latest = sibling["target_on_sale_date"]
        if latest is not None:
            blackout_end = shift_days(latest, COLLECTED_BLACKOUT_DAYS)
            if date_of(release_date) <= date_of(blackout_end):
                raise ApiError(
                    "ERR_CANNIBALIZATION_WINDOW_CONFLICT",
                    "A collected window must fall strictly after the %d-day blackout."
                    % COLLECTED_BLACKOUT_DAYS,
                )

    row = db.new_row(
        versioned=False,
        issue_id=issue["id"],
        channel=channel,
        release_date=fmt_dt(release_date),
        expected_net_receipts_cents=expected_net,
    )
    db.release_windows[row["id"]] = row
    return created_row(svc.release_window_json, row)


@issues_bp.get("/<issue_id>/release-windows")
def list_release_windows(issue_id):
    auth(("EditorInChief", "SalesDirector", "RoyaltyAccountant"))
    channel = q_enum("channel", RELEASE_CHANNELS)
    issue = svc.get_issue(issue_id)
    rows = svc.issue_release_windows(issue["id"])
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    window, meta = page(rows)
    return ok_list(svc.release_window_json, window, meta)


@issues_bp.get("/<issue_id>/revenue-events")
def list_issue_revenue_events(issue_id):
    auth(("SalesDirector", "RoyaltyAccountant", "EditorInChief"))
    channel = q_enum("channel", REVENUE_CHANNELS)
    basis_status = q_enum("basis_status", BASIS_STATUSES)
    period = q_month("period")
    issue = svc.get_issue(issue_id)
    rows = svc.issue_revenue_events(issue["id"])
    if channel is not None:
        rows = [r for r in rows if r["channel"] == channel]
    if basis_status is not None:
        rows = [r for r in rows if r["basis_status"] == basis_status]
    if period is not None:
        rows = [r for r in rows if r["period"] == period]
    window, meta = page(rows)
    return ok_list(svc.revenue_event_json, window, meta)


@issues_bp.get("/<issue_id>/solicitations")
def list_issue_solicitations(issue_id):
    auth(("EditorInChief", "ManagingEditor", "SalesDirector"))
    status = q_enum("status", SOLICITATION_STATUSES)
    issue = svc.get_issue(issue_id)
    rows = svc.issue_solicitations(issue["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.solicitation_json, window, meta)
