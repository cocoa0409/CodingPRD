"""PriceComparisonTool endpoints (PRD 3.3)."""

from flask import Blueprint

import calc
import clock
import db
import domain
import guards
import response

bp = Blueprint("tools", __name__)

READ_ROLES = ("PlanSponsorAdmin", "ComplianceOfficer", "ExternalAuditor")


@bp.route("/compliance/price-comparison-tools", methods=["POST"])
def create_tool():
    guards.authorize("PlanSponsorAdmin")
    body = guards.read_body()
    plan_year_id = guards.field(body, "plan_year_id", "string")
    tool_name = guards.field(body, "tool_name", "string")
    covered_items = guards.field(body, "covered_items_count", "integer")
    target = guards.field(
        body, "sla_target_uptime_pct", "number", required=False, default=99.00
    )
    guards.require(
        covered_items >= 0,
        "ERR_INVALID_REQUEST",
        "covered_items_count must be at least 0.",
    )
    plan_year = guards.fetch("plan_year", plan_year_id)
    guards.not_frozen(plan_year)
    record = db.common_fields()
    record.update({
        "plan_year_id": plan_year_id,
        "tool_name": tool_name,
        "covered_items_count": covered_items,
        "sla_target_uptime_pct": float(target),
        "status": "PENDING_LAUNCH",
        "launched_at": None,
        "outage_windows": [],
        "last_evaluated_month": None,
        "last_uptime_pct": None,
        "last_downtime_minutes": None,
        "sla_breach_open": False,
        "breach_onset_date": None,
    })
    db.tools[record["id"]] = record
    return response.created_response(response.public(record))


@bp.route("/compliance/price-comparison-tools/<row_id>", methods=["GET"])
def get_tool(row_id):
    guards.authorize(*READ_ROLES)
    return response.object_response(response.public(guards.fetch("tool", row_id)))


@bp.route("/compliance/price-comparison-tools", methods=["GET"])
def list_tools():
    guards.authorize(*READ_ROLES)
    limit, offset = guards.pagination()
    guards.filter_fk("plan_year", "plan_year_id")
    rows = guards.apply_filters(db.ordered(db.tools), [
        ("plan_year_id", "plan_year_id", None),
        ("status", "status", None),
        ("sla_breach_open", "sla_breach_open", guards.as_bool),
    ])
    page, total = guards.paginate(rows, limit, offset)
    return response.array_response(
        [response.public(r) for r in page], limit, offset, total
    )


@bp.route("/compliance/price-comparison-tools/<row_id>/launch", methods=["POST"])
def launch_tool(row_id):
    guards.authorize("PlanSponsorAdmin")
    tool = guards.fetch("tool", row_id)
    guards.read_body()
    plan_year = db.plan_years.get(tool["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(tool["status"], "PENDING_LAUNCH")
    guards.require(
        plan_year is not None and plan_year["lifecycle_status"] == "ACTIVE",
        "ERR_INVALID_STATE_TRANSITION",
        "The plan year must be ACTIVE to launch a price comparison tool.",
    )
    # Ladder step 30 — the tool must price enough covered items.
    guards.require(
        tool["covered_items_count"] >= calc.REQUIRED_COVERED_ITEMS,
        "ERR_COVERED_ITEMS_INSUFFICIENT",
        "covered_items_count must be at least %d." % calc.REQUIRED_COVERED_ITEMS,
    )
    with db.txn(tool):
        tool["status"] = "LIVE"
        tool["launched_at"] = clock.now_iso()
    return response.object_response(response.public(tool))


@bp.route(
    "/compliance/price-comparison-tools/<row_id>/outage-windows", methods=["POST"]
)
def add_outage_window(row_id):
    guards.authorize("PlanSponsorAdmin", "PlatformOperator")
    tool = guards.fetch("tool", row_id)
    body = guards.read_body()
    window_start = guards.field(body, "window_start", "datetime")
    window_end = guards.field(body, "window_end", "datetime")
    cause = guards.field(body, "cause", "string")
    plan_year = db.plan_years.get(tool["plan_year_id"])
    guards.not_frozen(plan_year)
    start = clock.parse_datetime(window_start)
    end = clock.parse_datetime(window_end)
    # Ladder step 19 — window shape first.
    guards.require(
        end > start,
        "ERR_INVALID_INTERVAL",
        "window_end must be strictly after window_start.",
    )
    # Ladder step 21 — half-open overlap with an existing window.
    for existing in tool["outage_windows"]:
        other_start = clock.parse_datetime(existing["window_start"])
        other_end = clock.parse_datetime(existing["window_end"])
        if start < other_end and other_start < end:
            guards.require(
                False,
                "ERR_OUTAGE_WINDOW_OVERLAP",
                "The window overlaps an existing outage window (%s..%s)."
                % (existing["window_start"], existing["window_end"]),
            )
    # Ladder step 22 — the window must be elapsed and after launch.
    launched = clock.parse_datetime(tool["launched_at"]) if tool["launched_at"] else None
    guards.require(
        end <= clock.now() and launched is not None and start >= launched,
        "ERR_OUTAGE_WINDOW_OUT_OF_RANGE",
        "The window must end at or before the logical clock and start at or after "
        "the tool's launched_at.",
    )
    with db.txn(tool):
        tool["outage_windows"] = tool["outage_windows"] + [{
            "window_start": window_start,
            "window_end": window_end,
            "cause": cause,
        }]
    return response.object_response(response.public(tool))


@bp.route("/compliance/price-comparison-tools/<row_id>/evaluations", methods=["POST"])
def evaluate_tool(row_id):
    user_id, _role = guards.authorize("ComplianceOfficer", "PlatformOperator")
    tool = guards.fetch("tool", row_id)
    body = guards.read_body()
    evaluation_month = guards.field(body, "evaluation_month", "month")
    plan_year = db.plan_years.get(tool["plan_year_id"])
    guards.not_frozen(plan_year)
    guards.state_is(tool["status"], "LIVE")
    # Ladder step 23 — the month must be fully elapsed and at or after launch.
    launch_month = clock.month_of(tool["launched_at"]) if tool["launched_at"] else None
    guards.require(
        evaluation_month < clock.month_of(clock.today_iso())
        and (launch_month is None or evaluation_month >= launch_month),
        "ERR_EVALUATION_MONTH_NOT_ELAPSED",
        "evaluation_month must be strictly before the current month and not precede "
        "the tool's launch month.",
    )
    scored = calc.monthly_uptime(
        evaluation_month, tool["outage_windows"], tool["sla_target_uptime_pct"]
    )
    was_open = tool["sla_breach_open"] is True
    opens = scored["breached"] and not was_open
    onset = clock.next_month_first_day(evaluation_month)
    with db.txn(tool):
        tool["last_evaluated_month"] = evaluation_month
        tool["last_uptime_pct"] = scored["last_uptime_pct"]
        tool["last_downtime_minutes"] = scored["last_downtime_minutes"]
        tool["sla_breach_open"] = bool(scored["breached"])
        if scored["breached"]:
            if opens:
                tool["breach_onset_date"] = onset
        else:
            tool["breach_onset_date"] = None
    if plan_year is not None:
        with db.txn(plan_year):
            if opens:
                domain.post_accrual(
                    plan_year,
                    "TOOL_SLA",
                    onset,
                    "Price comparison tool %s breached its uptime SLA in %s."
                    % (tool["id"], evaluation_month),
                    user_id,
                )
                domain.recompute_exposure(plan_year)
            domain.recompute_posture(plan_year)
    return response.object_response(response.public(tool))
