"""AnnualSettlement lifecycle, settlement lines, payment/write-off."""
from flask import Blueprint

import errors
import helpers
import services
from db import store
from helpers import (authenticate, get_path, json_body, paginate, resolve_fk,
                     req_string, require_ownership, READ_ROLES, PAYMENT_OUTCOMES)
from response import success_object, success_list
from services import (ser_settlement, ser_settlement_line, touch, stamp, now_dt,
                      check_fy_open_guard, DISPUTE_WINDOW_DAYS, PAYMENT_DUE_DAYS)
from util import new_id, fmt_iso, days_later, rhu_div

bp = Blueprint("settlements", __name__)


def _get_settlement(settlement_id):
    return get_path(store.settlements, settlement_id, "AnnualSettlement")


def _get_line(line_id):
    return get_path(store.settlement_lines, line_id, "AirlineSettlementLine")


def _lines_of(settlement_id):
    return [l for l in store.settlement_lines.values()
            if l["annual_settlement_id"] == settlement_id]


@bp.get("/airport/settlements/<settlement_id>")
def get_settlement(settlement_id):
    authenticate(READ_ROLES)
    settlement = _get_settlement(settlement_id)
    return success_object(ser_settlement(settlement))


@bp.post("/airport/settlements/<settlement_id>/publish-review")
def publish_review(settlement_id):
    authenticate(("AirportFinance",))
    settlement = _get_settlement(settlement_id)
    if settlement["status"] != "COMPUTED":
        raise errors.invalid_state("Only a COMPUTED settlement can be published for review")
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)
    settlement["status"] = "AIRLINE_REVIEW"
    settlement["_published_review_dt"] = now_dt()
    touch(settlement)
    # cascade: each line goes PENDING with a 60-day payment due date
    due_dt = days_later(now_dt(), PAYMENT_DUE_DAYS)
    for line in _lines_of(settlement["id"]):
        line["payment_status"] = "PENDING"
        line["_due_dt"] = due_dt
        touch(line)
    return success_object(ser_settlement(settlement))


@bp.post("/airport/settlements/<settlement_id>/dispute")
def dispute(settlement_id):
    uid, _ = authenticate(("SignatoryAirline",))
    settlement = _get_settlement(settlement_id)
    body = json_body()
    airline = resolve_fk(body, "airline_id", store.airlines)  # priority 4
    airline_id = req_string(body, "airline_id")               # priority 5
    req_string(body, "reason")
    require_ownership(uid, airline_id)
    # priority 6: AIRLINE_REVIEW -> DISPUTED, or RESOLVED -> DISPUTED (cycle)
    if settlement["status"] not in ("AIRLINE_REVIEW", "RESOLVED"):
        raise errors.invalid_state(
            "Only a settlement in AIRLINE_REVIEW or RESOLVED can be disputed")
    # the caller must actually hold a line in this settlement
    if not any(l["airline_id"] == airline_id for l in _lines_of(settlement["id"])):
        raise errors.forbidden("Carrier holds no settlement line in this settlement")
    # priority 8: dispute window — 45 days from publish-review or last resolve
    if settlement["status"] == "AIRLINE_REVIEW":
        anchor = settlement["_published_review_dt"]
    else:
        anchor = settlement["_resolved_dt"]
    if anchor is None or now_dt() > days_later(anchor, DISPUTE_WINDOW_DAYS):
        raise errors.dispute_window_expired()
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)  # priority 9
    settlement["status"] = "DISPUTED"
    touch(settlement)
    return success_object(ser_settlement(settlement))


@bp.post("/airport/settlements/<settlement_id>/resolve")
def resolve(settlement_id):
    authenticate(("AirportDirector",))
    settlement = _get_settlement(settlement_id)
    body = json_body(required=False)
    if settlement["status"] != "DISPUTED":
        raise errors.invalid_state("Only a DISPUTED settlement can be resolved")
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)
    override = body.get("override_true_up_cents")
    if override is not None and not helpers._is_int(override):
        raise errors.invalid_request("Field 'override_true_up_cents' must be an integer")
    settlement["status"] = "RESOLVED"
    settlement["_resolved_dt"] = now_dt()
    if override is not None:
        _apply_override(settlement, override)
    touch(settlement)
    return success_object(ser_settlement(settlement))


def _apply_override(settlement, override_total):
    """Rewrite each line's true_up_cents following the allocation waterfall:
    pro-rata on the line's actual share basis, round-half-up, remainder to the
    largest share (ties by Airline.created_at ASC). Affected lines re-enter
    collection as PENDING."""
    lines = sorted(_lines_of(settlement["id"]),
                   key=lambda l: (l["_created_dt"], l["_seq"]))
    if not lines:
        settlement["total_true_up_cents"] = override_total
        return
    bases = [max(l["actual_airfield_share_cents"] + l["actual_terminal_share_cents"], 0)
             for l in lines]
    total_basis = sum(bases)
    allocated = []
    if total_basis > 0:
        for l, b in zip(lines, bases):
            allocated.append(rhu_div(override_total * b, total_basis))
    else:
        each = rhu_div(override_total, len(lines))
        allocated = [each] * len(lines)
    delta = override_total - sum(allocated)
    if delta != 0:
        # remainder to the largest share, ties by Airline.created_at ASC
        def share_key(idx):
            line = lines[idx]
            airline = store.airlines[line["airline_id"]]
            return airline["_created_dt"]
        max_basis = max(bases)
        candidates = [i for i, b in enumerate(bases) if b == max_basis]
        target_idx = min(candidates, key=share_key)
        allocated[target_idx] += delta
    for line, amount in zip(lines, allocated):
        line["true_up_cents"] = amount
        line["payment_status"] = "PENDING"
        touch(line)
    settlement["total_true_up_cents"] = override_total


@bp.post("/airport/settlements/<settlement_id>/recompute")
def recompute(settlement_id):
    authenticate(("AirportFinance",))
    settlement = _get_settlement(settlement_id)
    body = json_body()
    expected = body.get("expected_annual_settlement_version")
    if not helpers._is_int(expected):
        raise errors.invalid_request(
            "Field 'expected_annual_settlement_version' is required and must be an integer")
    if settlement["status"] == "FINALIZED":
        raise errors.invalid_state("A FINALIZED settlement cannot be recomputed")
    # priority 7: OCC on the settlement's version
    if expected != settlement["version"]:
        raise errors.stale_version(
            "expected_annual_settlement_version does not match the settlement's current version")
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)
    from .fy_routes import _apply_true_up
    _apply_true_up(settlement, fy, create_missing_only=True)
    touch(settlement)
    return success_object(ser_settlement(settlement))


@bp.post("/airport/settlements/<settlement_id>/finalize")
def finalize(settlement_id):
    authenticate(("AirportDirector",))
    settlement = _get_settlement(settlement_id)
    if settlement["status"] not in ("AIRLINE_REVIEW", "RESOLVED"):
        raise errors.invalid_state(
            "Only a settlement in AIRLINE_REVIEW or RESOLVED can be finalized")
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)
    # priority 16: every line settled
    if any(l["payment_status"] == "PENDING" for l in _lines_of(settlement["id"])):
        raise errors.unsettled_lines()
    settlement["status"] = "FINALIZED"
    touch(settlement)
    # cascade 1: parent fiscal year OPEN -> CLOSED
    if fy["status"] == "OPEN":
        fy["status"] = "CLOSED"
        touch(fy)
    # cascade 2: any schedule still DRAFT on this year -> EXPIRED
    for rs in store.rates_settings.values():
        if rs["fiscal_year_id"] == fy["id"] and rs["status"] == "DRAFT":
            rs["status"] = "EXPIRED"
            touch(rs)
    return success_object(ser_settlement(settlement))


@bp.get("/airport/settlements/<settlement_id>/lines")
def list_lines(settlement_id):
    authenticate(READ_ROLES)
    settlement = _get_settlement(settlement_id)
    items = _lines_of(settlement["id"])
    airline_id = helpers.request.args.get("airline_id")
    if airline_id is not None:
        items = [l for l in items if l["airline_id"] == airline_id]
    payment_status = helpers.request.args.get("payment_status")
    if payment_status is not None:
        items = [l for l in items if l["payment_status"] == payment_status]
    data, meta = paginate(items, ser_settlement_line)
    return success_list(data, meta)


# ---------------------------------------------------------------------------
# AirlineSettlementLine payment lifecycle
# ---------------------------------------------------------------------------
@bp.post("/airport/settlement_lines/<line_id>/record-payment")
def record_payment(line_id):
    authenticate(("AirportFinance",))
    line = _get_line(line_id)
    body = json_body()
    outcome = req_string(body, "outcome")
    if outcome not in PAYMENT_OUTCOMES:
        raise errors.invalid_request("Field 'outcome' must be one of ['PAID', 'CREDITED']")
    if line["payment_status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING line can record a payment")
    settlement = store.settlements[line["annual_settlement_id"]]
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)
    line["payment_status"] = outcome
    touch(line)
    # cascade: last PENDING line cleared -> DELINQUENT recovers to GOOD
    still_pending = any(
        l["payment_status"] == "PENDING"
        for l in store.settlement_lines.values()
        if l["airline_id"] == line["airline_id"]
        and store.settlements[l["annual_settlement_id"]]["fiscal_year_id"] == fy["id"])
    if not still_pending:
        ag = services.active_agreement(fy["id"], line["airline_id"])
        if ag is not None and ag["credit_standing"] == "DELINQUENT":
            ag["credit_standing"] = "GOOD"
            touch(ag)
    return success_object(ser_settlement_line(line))


@bp.post("/airport/settlement_lines/<line_id>/write-off")
def write_off(line_id):
    authenticate(("AirportDirector",))
    line = _get_line(line_id)
    if line["payment_status"] != "PENDING":
        raise errors.invalid_state("Only a PENDING line can be written off")
    settlement = store.settlements[line["annual_settlement_id"]]
    fy = store.fiscal_years[settlement["fiscal_year_id"]]
    check_fy_open_guard(fy)
    line["payment_status"] = "WRITTEN_OFF"
    touch(line)
    return success_object(ser_settlement_line(line))


@bp.get("/airport/settlement_lines/<line_id>")
def get_line(line_id):
    authenticate(READ_ROLES)
    line = _get_line(line_id)
    return success_object(ser_settlement_line(line))
