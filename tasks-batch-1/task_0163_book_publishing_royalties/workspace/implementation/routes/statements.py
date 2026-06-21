"""Author statements, statement lines, reserves, and the finalize/pay
reconciliation cascades (PRD §3.5, §3.6, §3.8, §3.9)."""
from flask import Blueprint, request

import db
import errors
from middleware import get_principal, require_publisher, serialize
from response import object_response, array_response
from services import validate
from services.access import can_read_contract
from services.listing import paginate
from services import statement as svc
from services.money import mul_round

bp = Blueprint("statements", __name__)

# Computed monetary fields that live on an AuthorStatement record.
_STATEMENT_MONEY_FIELDS = [
    "gross_royalty_cents", "reserve_held_cents", "royalty_credited_cents",
    "reserve_released_cents", "subsidiary_income_cents", "period_earnings_cents",
    "advance_recouped_cents", "payable_before_commission_cents",
    "agent_commission_cents", "net_to_author_cents",
]


def _read_statement_or_403(sid):
    role, user_id = get_principal()
    stmt = db.author_statements.get(sid)
    if stmt is None:
        raise errors.not_found("Statement not found.")
    contract = db.contracts.get(stmt["contract_id"])
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return stmt


def _read_contract_or_403(cid):
    role, user_id = get_principal()
    contract = db.contracts.get(cid)
    if contract is None:
        raise errors.not_found("Contract not found.")
    if not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return contract


def _read_period_or_403(pid):
    role, user_id = get_principal()
    period = db.sales_periods.get(pid)
    if period is None:
        raise errors.not_found("Sales period not found.")
    contract = db.contracts.get(period["contract_id"])
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return period


# ---------------------------------------------------------------------------
# Generate (DRAFT)
# ---------------------------------------------------------------------------

@bp.route("/sales-periods/<pid>/generate-statement", methods=["POST"])
def generate_statement(pid):
    role, _ = get_principal()
    require_publisher(role)
    period = db.sales_periods.get(pid)
    if period is None:
        raise errors.not_found("Sales period not found.")
    contract = db.contracts.get(period["contract_id"])
    # State: period must be CLOSED.
    if period["status"] != "CLOSED":
        raise errors.invalid_state("Statement may only be generated for a CLOSED period.")
    # At most one statement per period (priority 12).
    for s in db.author_statements.values():
        if s["period_id"] == pid:
            raise errors.statement_exists()

    snap = svc.compute_snapshot(contract, period, committed=False)
    rec = db.make_common({
        "contract_id": contract["id"],
        "period_id": pid,
        "tax_withheld_cents": 0,
        "status": "DRAFT",
    })
    for f in _STATEMENT_MONEY_FIELDS:
        rec[f] = snap[f]
    db.author_statements[rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/statements/<sid>", methods=["GET"])
def get_statement(sid):
    stmt = _read_statement_or_403(sid)
    return object_response(serialize(stmt))


@bp.route("/sales-periods/<pid>/statement", methods=["GET"])
def get_period_statement(pid):
    period = _read_period_or_403(pid)
    records = [s for s in db.author_statements.values() if s["period_id"] == period["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/contracts/<cid>/statements", methods=["GET"])
def list_contract_statements(cid):
    contract = _read_contract_or_403(cid)
    status = request.args.get("status")
    records = [s for s in db.author_statements.values() if s["contract_id"] == contract["id"]]
    if status is not None:
        records = [s for s in records if s["status"] == status]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# StatementLine emission
# ---------------------------------------------------------------------------

def _emit_line(statement_id, line_type, amount_cents, memo):
    rec = db.make_light({
        "statement_id": statement_id,
        "line_type": line_type,
        "amount_cents": amount_cents,
        "memo": memo,
    })
    db.statement_lines[rec["id"]] = rec
    return rec


# ---------------------------------------------------------------------------
# Finalize (DRAFT -> FINALIZED) — the reconciliation heart
# ---------------------------------------------------------------------------

@bp.route("/statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    role, _ = get_principal()
    require_publisher(role)
    stmt = db.author_statements.get(sid)
    if stmt is None:
        raise errors.not_found("Statement not found.")
    contract = db.contracts.get(stmt["contract_id"])
    period = db.sales_periods.get(stmt["period_id"])

    # Well-formedness: expected_contract_version mandatory (priority 4).
    body = validate.get_body()
    expected = validate.req_int(body, "expected_contract_version")

    # State conflicts surface ahead of OCC (PRD §2.10).
    if stmt["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT statement may be finalized.")
    if period is None or period["status"] != "CLOSED":
        raise errors.invalid_state("Owning sales period must be CLOSED to finalize.")

    # OCC (priority 15).
    if expected != contract["version"]:
        raise errors.stale_contract_version()

    # Recompute committed snapshot against live state.
    snap = svc.compute_snapshot(contract, period, committed=True)

    # ---- Apply cascades atomically (all in-memory; no failure points after
    # this line, so this is effectively atomic) ----
    for f in _STATEMENT_MONEY_FIELDS:
        stmt[f] = snap[f]

    # debit unrecouped advance
    contract["unrecouped_advance_cents"] -= snap["advance_recouped_cents"]
    # increment lifetime_net_units by this period's net units
    contract["lifetime_net_units"] += snap["_period_net_units"]

    # liquidate eligible reserves; their released_cents already summed into snap
    for rv, consumed, released in snap["_reserve_plan"]:
        rv["consumed_cents"] = consumed
        rv["released_cents"] = released
        rv["status"] = "LIQUIDATED"
        db.touch(rv)

    # statement the credited subsidiary rights
    for sr in snap["_credited_rights"]:
        sr["status"] = "STATEMENTED"
        sr["statement_id"] = stmt["id"]
        db.touch(sr)

    # create a new HELD reserve sized at this period's reserve_held_cents
    reserve_pct = contract["reserve_pct"]
    period_net = snap["_period_net_units"]
    reserve_units = mul_round(period_net, reserve_pct)
    reserve_held = snap["reserve_held_cents"]
    if reserve_units > 0:
        unit_value = float(reserve_held) / float(reserve_units)
    else:
        unit_value = 0
    eligible_seq = period["sequence"] + contract["reserve_hold_periods"]
    new_reserve = db.make_common({
        "contract_id": contract["id"],
        "origin_statement_id": stmt["id"],
        "reserve_units": reserve_units,
        "reserve_held_cents": reserve_held,
        "reserve_unit_value_cents": unit_value,
        "eligible_sequence": eligible_seq,
        "released_cents": 0,
        "consumed_cents": 0,
        "status": "HELD",
    })
    db.returns_reserves[new_reserve["id"]] = new_reserve

    # transition owning period CLOSED -> STATEMENTED
    period["status"] = "STATEMENTED"
    db.touch(period)

    # statement itself transitions to FINALIZED
    stmt["status"] = "FINALIZED"
    db.touch(stmt)

    # emit immutable StatementLine rows (one per non-zero finalize component)
    lines = [
        ("ROYALTY", snap["gross_royalty_cents"], "Tiered royalty earned this period"),
        ("RESERVE_WITHHELD", -snap["reserve_held_cents"], "Returns reserve withheld this period"),
        ("RESERVE_RELEASED", snap["reserve_released_cents"], "Reserves liquidated into this statement"),
        ("SUBSIDIARY", snap["subsidiary_income_cents"], "Subsidiary rights income credited"),
        ("ADVANCE_RECOUP", -snap["advance_recouped_cents"], "Advance recouped this period"),
        ("AGENT_COMMISSION", -snap["agent_commission_cents"], "Agent commission on net payable"),
    ]
    for line_type, amount, memo in lines:
        if amount != 0:
            _emit_line(stmt["id"], line_type, amount, memo)

    # bump contract version (aggregate root)
    db.touch(contract)

    return object_response(serialize(stmt))


# ---------------------------------------------------------------------------
# Pay (FINALIZED -> PAID) — tax applied here only
# ---------------------------------------------------------------------------

@bp.route("/statements/<sid>/pay", methods=["POST"])
def pay_statement(sid):
    role, _ = get_principal()
    require_publisher(role)
    stmt = db.author_statements.get(sid)
    if stmt is None:
        raise errors.not_found("Statement not found.")
    contract = db.contracts.get(stmt["contract_id"])

    body = validate.get_body()
    expected = validate.req_int(body, "expected_contract_version")

    if stmt["status"] != "FINALIZED":
        raise errors.invalid_state("Only a FINALIZED statement may be paid.")

    if expected != contract["version"]:
        raise errors.stale_contract_version()

    author = db.authors.get(contract["author_id"])
    tax_pct = author["tax_withholding_pct"] if author else 0

    payable_before = stmt["payable_before_commission_cents"]
    agent_commission = stmt["agent_commission_cents"]
    author_facing = payable_before - agent_commission
    tax_withheld = mul_round(author_facing, tax_pct)
    net = payable_before - agent_commission - tax_withheld

    stmt["tax_withheld_cents"] = tax_withheld
    stmt["net_to_author_cents"] = net
    stmt["status"] = "PAID"
    db.touch(stmt)

    # emit TAX_WITHHELD (non-zero) and final NET_PAYABLE line
    if tax_withheld != 0:
        _emit_line(stmt["id"], "TAX_WITHHELD", -tax_withheld, "Tax withheld at payment")
    _emit_line(stmt["id"], "NET_PAYABLE", net, "Net amount payable to author")

    db.touch(contract)

    return object_response(serialize(stmt))


@bp.route("/statements/<sid>/lines", methods=["GET"])
def list_lines(sid):
    stmt = _read_statement_or_403(sid)
    line_type = request.args.get("line_type")
    records = [l for l in db.statement_lines.values() if l["statement_id"] == stmt["id"]]
    if line_type is not None:
        records = [l for l in records if l["line_type"] == line_type]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Reserves
# ---------------------------------------------------------------------------

@bp.route("/contracts/<cid>/reserves", methods=["GET"])
def list_contract_reserves(cid):
    contract = _read_contract_or_403(cid)
    status = request.args.get("status")
    records = [r for r in db.returns_reserves.values() if r["contract_id"] == contract["id"]]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/reserves/<rid>", methods=["GET"])
def get_reserve(rid):
    role, user_id = get_principal()
    reserve = db.returns_reserves.get(rid)
    if reserve is None:
        raise errors.not_found("Returns reserve not found.")
    contract = db.contracts.get(reserve["contract_id"])
    if contract is None or not can_read_contract(role, user_id, contract):
        raise errors.unauthorized()
    return object_response(serialize(reserve))


@bp.route("/statements/<sid>/reserves", methods=["GET"])
def list_statement_reserves(sid):
    stmt = _read_statement_or_403(sid)
    records = [r for r in db.returns_reserves.values() if r["origin_statement_id"] == stmt["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)


@bp.route("/statements/<sid>/subsidiary-rights", methods=["GET"])
def list_statement_rights(sid):
    stmt = _read_statement_or_403(sid)
    records = [r for r in db.subsidiary_rights.values() if r["statement_id"] == stmt["id"]]
    limit, offset = validate.pagination()
    page, total = paginate(records, limit, offset)
    return array_response(page, limit, offset, total)
