"""Revenue events, royalty statements and the logical clock (PRD 2.4, 3.8)."""

from flask import Blueprint

from core import (
    BASIS_STATUSES,
    REVENUE_CHANNELS,
    STATEMENT_BASES,
    STATEMENT_STATUSES,
    ApiError,
    apply_fields,
    auth,
    bad,
    created_row,
    db,
    get_body,
    ok_data,
    ok_list,
    ok_row,
    ordered,
    page,
    q_enum,
    q_month,
    q_str,
    v_datetime,
    v_enum,
    v_int,
    v_month,
    v_str,
)
from calc import royalty_accrual
import services as svc

clock_bp = Blueprint("clock", __name__)
revenue_bp = Blueprint("revenue", __name__, url_prefix="/comics/revenue-events")
statements_bp = Blueprint("statements", __name__, url_prefix="/comics/royalty-statements")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


@clock_bp.post("/_clock/set_current_utc")
def set_clock():
    auth((
        "EditorInChief",
        "ManagingEditor",
        "SalesDirector",
        "RoyaltyAccountant",
        "Creator",
        "Retailer",
    ))
    body = get_body()
    moment = v_datetime(body, "to_iso8601", required=True)
    db.set_clock(moment)
    return ok_data({"to_iso8601": db.now(), "current_utc": db.now()})


# ---------------------------------------------------------------------------
# Revenue events
# ---------------------------------------------------------------------------


@revenue_bp.post("")
def post_revenue_event():
    auth(("RoyaltyAccountant",))
    body = get_body()
    issue_id = v_str(body, "issue_id", required=True, min_len=1)
    channel = v_enum(body, "channel", REVENUE_CHANNELS, required=True)
    basis_status = v_enum(body, "basis_status", BASIS_STATUSES, required=True)
    gross = v_int(body, "gross_receipts_cents", required=True, minimum=0)
    net = v_int(body, "net_receipts_cents", required=True, minimum=0)
    units = v_int(body, "units", minimum=0, default=0)
    period = v_month(body, "period", required=True)
    if net > gross:
        bad("Field 'net_receipts_cents' may not exceed 'gross_receipts_cents'.")

    issue = svc.get_issue(issue_id)
    row = db.new_row(
        versioned=False,
        issue_id=issue["id"],
        channel=channel,
        basis_status=basis_status,
        gross_receipts_cents=gross,
        net_receipts_cents=net,
        units=units,
        period=period,
        source="MANUAL",
    )
    db.revenue_events[row["id"]] = row
    return created_row(svc.revenue_event_json, row)


# ---------------------------------------------------------------------------
# Royalty statements
# ---------------------------------------------------------------------------


@statements_bp.post("")
def create_statement():
    auth(("RoyaltyAccountant",))
    body = get_body()
    title_id = v_str(body, "title_id", required=True, min_len=1)
    creator_id = v_str(body, "creator_id", required=True, min_len=1)
    period = v_month(body, "period", required=True)
    basis = v_enum(body, "basis", STATEMENT_BASES, required=True)

    title = svc.get_title(title_id)
    creator = svc.get_creator(creator_id)

    for other in svc.title_statements(title["id"]):
        if (
            other["creator_id"] == creator["id"]
            and other["period"] == period
            and other["basis"] == basis
            and other["status"] in ("DRAFT", "ISSUED", "PAID")
        ):
            raise ApiError(
                "ERR_DUPLICATE_STATEMENT_PERIOD",
                "A %s statement for this creator and period already exists." % basis,
            )

    participants = [
        a
        for a in svc.title_assignments(title["id"])
        if a["status"] in svc.PARTICIPATING_ASSIGNMENT_STATUSES
    ]
    own = [a for a in participants if a["creator_id"] == creator["id"]]
    if not own:
        raise ApiError(
            "ERR_NO_ASSIGNMENT_FOR_CREATOR",
            "The creator holds no accepted assignment on this title.",
        )
    assignment = own[0]

    issue_ids = set(i["id"] for i in svc.title_issues(title["id"]))
    allowed_basis = ("ESTIMATED", "ACTUAL") if basis == "ESTIMATED" else ("ACTUAL",)
    events = [
        e
        for e in ordered(db.revenue_events)
        if e["issue_id"] in issue_ids
        and e["period"] == period
        and e["basis_status"] in allowed_basis
    ]

    lines, gross = royalty_accrual(basis, events, title, participants, assignment["id"])
    recoupment = min(assignment["unrecouped_advance_cents"], gross)
    if recoupment < 0:
        recoupment = 0

    row = db.new_row(
        title_id=title["id"],
        creator_id=creator["id"],
        period=period,
        basis=basis,
        lines=lines,
        gross_royalty_cents=gross,
        recoupment_applied_cents=recoupment,
        payable_cents=gross - recoupment,
        status="DRAFT",
        issued_by_user_id=None,
        paid_by_user_id=None,
        payment_reference=None,
        reversal_reason=None,
        _assignment_id=assignment["id"],
    )
    db.statements[row["id"]] = row
    return created_row(svc.statement_json, row)


@statements_bp.get("")
def list_statements():
    auth(("EditorInChief", "RoyaltyAccountant", "Creator"))
    title_id = q_str("title_id")
    creator_id = q_str("creator_id")
    period = q_month("period")
    basis = q_enum("basis", STATEMENT_BASES)
    status = q_enum("status", STATEMENT_STATUSES)
    rows = ordered(db.statements)
    if title_id is not None:
        rows = [r for r in rows if r["title_id"] == title_id]
    if creator_id is not None:
        rows = [r for r in rows if r["creator_id"] == creator_id]
    if period is not None:
        rows = [r for r in rows if r["period"] == period]
    if basis is not None:
        rows = [r for r in rows if r["basis"] == basis]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    window, meta = page(rows)
    return ok_list(svc.statement_json, window, meta)


@statements_bp.get("/<statement_id>")
def read_statement(statement_id):
    auth(("EditorInChief", "RoyaltyAccountant", "Creator"))
    return ok_row(svc.statement_json, svc.get_statement(statement_id))


def _post_to_ledgers(statement):
    title = db.titles.get(statement["title_id"])
    if title is not None:
        svc.recompute_title_royalty_accrued(title)
    svc.recompute_unrecouped_advances(statement["title_id"], statement["creator_id"])


@statements_bp.post("/<statement_id>/issue")
def issue_statement(statement_id):
    user_id, _role = auth(("RoyaltyAccountant",))
    statement = svc.get_statement(statement_id)
    if statement["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A statement issues from DRAFT, not %s." % statement["status"],
        )
    apply_fields(statement, status="ISSUED", issued_by_user_id=user_id)
    _post_to_ledgers(statement)
    return ok_row(svc.statement_json, statement)


@statements_bp.post("/<statement_id>/pay")
def pay_statement(statement_id):
    user_id, _role = auth(("EditorInChief", "RoyaltyAccountant"))
    body = get_body()
    payment_reference = v_str(
        body, "payment_reference", required=True, min_len=1, max_len=120
    )
    statement = svc.get_statement(statement_id)
    if statement["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A statement is paid from ISSUED, not %s." % statement["status"],
        )
    if statement["issued_by_user_id"] == user_id:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The operator who issued a statement may not also pay it.",
        )
    if statement["payable_cents"] <= 0:
        raise ApiError(
            "ERR_ZERO_PAYABLE_STATEMENT",
            "A statement with nothing payable cannot be paid.",
        )
    apply_fields(
        statement,
        status="PAID",
        paid_by_user_id=user_id,
        payment_reference=payment_reference,
    )
    return ok_row(svc.statement_json, statement)


@statements_bp.post("/<statement_id>/reverse")
def reverse_statement(statement_id):
    auth(("RoyaltyAccountant",))
    body = get_body()
    reason = v_str(body, "reason", required=True, min_len=1, max_len=500)
    statement = svc.get_statement(statement_id)
    if statement["status"] == "PAID":
        raise ApiError(
            "ERR_STATEMENT_ALREADY_PAID", "A paid statement cannot be reversed."
        )
    if statement["status"] != "ISSUED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "A statement reverses from ISSUED, not %s." % statement["status"],
        )
    apply_fields(statement, status="REVERSED", reversal_reason=reason)
    _post_to_ledgers(statement)
    return ok_row(svc.statement_json, statement)
