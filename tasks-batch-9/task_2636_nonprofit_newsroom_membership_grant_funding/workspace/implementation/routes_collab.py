"""Collaborative investigations and the conservation of shared cost (§3.8)."""

from flask import Blueprint

import calc
import derive
import guards
from core import (
    DB, ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER, ROLE_EDITORIAL_DIRECTOR,
    ROLE_FINANCE_CONTROLLER, apply_changes, authenticate, body, check_bps_range,
    check_date_order, fail, iso_ms, list_response, lookup, lookup_fk, new_row,
    now_clock, object_response, pagination, paginate, parse_date, parse_instant,
    public, q_enum, q_str, rows, touch, v_enum, v_instant, v_int, v_str,
)
from routes_fiscal import finalize_create

bp = Blueprint("collab", __name__)

COLLAB_READ_ROLES = (ROLE_EDITORIAL_DIRECTOR, ROLE_FINANCE_CONTROLLER,
                     ROLE_BOARD_OVERSIGHT, ROLE_DEVELOPMENT_OFFICER)


def get_collaboration(collaboration_id):
    return lookup("collaborations", collaboration_id, "ERR_COLLABORATION_NOT_FOUND")


def get_partner(partner_id):
    return lookup("collaboration_partners", partner_id, "ERR_PARTNER_NOT_FOUND")


def half_open_overlap(start_a, end_a, start_b, end_b):
    """Half-open windows: adjacency is expressly permitted."""
    if None in (start_a, end_a, start_b, end_b):
        return False
    return start_a < end_b and start_b < end_a


# ---------------------------------------------------------------------------
# Collaborations
# ---------------------------------------------------------------------------

@bp.post("/collaborations")
def create_collaboration():
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    data = body()
    area = lookup_fk("coverage_areas", data.get("coverage_area_id"),
                     "ERR_COVERAGE_AREA_NOT_FOUND")
    if area is None:
        fail("ERR_INVALID_REQUEST", "coverage_area_id is required")
    period = lookup_fk("fiscal_periods", data.get("fiscal_period_id"),
                       "ERR_FISCAL_PERIOD_NOT_FOUND")
    if period is None:
        fail("ERR_INVALID_REQUEST", "fiscal_period_id is required")
    title = v_str(data, "title", min_len=1)
    window_start = v_instant(data, "window_start")
    window_end = v_instant(data, "window_end")
    total_cost_cents = v_int(data, "total_cost_cents", minimum=1)
    lead_credit_bps = v_int(data, "lead_credit_bps")
    lead_cost_share_bps = v_int(data, "lead_cost_share_bps")
    check_bps_range("lead_credit_bps", lead_credit_bps)
    check_bps_range("lead_cost_share_bps", lead_cost_share_bps)
    check_date_order(window_start, window_end)

    period_start = parse_date(period["start_date"])
    period_end = parse_date(period["end_date"])
    if (period_start is not None and period_end is not None
            and (window_start.date() < period_start or window_end.date() > period_end)):
        fail("ERR_WINDOW_OUTSIDE_PERIOD",
             "the production window must lie inside the fiscal period")

    collaboration = new_row("collaborations", {
        "coverage_area_id": area["id"],
        "fiscal_period_id": period["id"],
        "title": title,
        "window_start": iso_ms(window_start),
        "window_end": iso_ms(window_end),
        "total_cost_cents": total_cost_cents,
        "lead_credit_bps": lead_credit_bps,
        "lead_cost_share_bps": lead_cost_share_bps,
        "status": "DRAFT",
        "partner_count": 0,
        "lead_cost_cents": 0,
        "allocated_cost_cents": 0,
        "syndication_revenue_cents": 0,
        "settled_at": None,
    })
    return object_response(public(collaboration), 201)


@bp.get("/collaborations/<collaboration_id>")
def read_collaboration(collaboration_id):
    authenticate(*COLLAB_READ_ROLES)
    return object_response(public(get_collaboration(collaboration_id)))


@bp.get("/collaborations")
def list_collaborations():
    authenticate(*COLLAB_READ_ROLES)
    area_id = q_str("coverage_area_id")
    period_id = q_str("fiscal_period_id")
    status = q_enum("status", calc.COLLABORATION_STATUSES)
    limit, offset = pagination()
    items = []
    for collaboration in rows("collaborations"):
        if area_id is not None and collaboration["coverage_area_id"] != area_id:
            continue
        if period_id is not None and collaboration["fiscal_period_id"] != period_id:
            continue
        if status is not None and collaboration["status"] != status:
            continue
        items.append(collaboration)
    items.sort(key=lambda c: (c["window_start"], c["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_response([public(c) for c in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Partners
# ---------------------------------------------------------------------------

@bp.post("/collaborations/<collaboration_id>/partners")
def add_collaboration_partner(collaboration_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    collaboration = get_collaboration(collaboration_id)
    data = body()
    partner_org_name = v_str(data, "partner_org_name", min_len=1)
    credit_share_bps = v_int(data, "credit_share_bps")
    cost_share_bps = v_int(data, "cost_share_bps")
    check_bps_range("credit_share_bps", credit_share_bps, minimum=1)
    check_bps_range("cost_share_bps", cost_share_bps, minimum=1)

    guards.require_not_terminal(collaboration["status"], calc.COLLABORATION_TERMINAL,
                                "collaboration")
    guards.require_state(collaboration["status"], ("DRAFT", "ACTIVE"),
                         "collaboration")
    for existing in derive.confirmed_partners(collaboration["id"]):
        if existing["partner_org_name"] == partner_org_name:
            fail("ERR_PARTNER_DUPLICATE",
                 "%s is already a confirmed partner" % partner_org_name)

    partner = new_row("collaboration_partners", {
        "collaboration_id": collaboration["id"],
        "partner_org_name": partner_org_name,
        "credit_share_bps": credit_share_bps,
        "cost_share_bps": cost_share_bps,
        "cost_owed_cents": 0,
        "remainder_rank": 0,
        "status": "CONFIRMED",
        "withdrawn_at": None,
    })
    if collaboration["status"] == "ACTIVE":
        derive.recompute_collaboration_split(collaboration)
    else:
        derive.recompute_collaboration_counts(collaboration)
    return object_response(public(finalize_create(partner)), 201)


@bp.get("/collaborations/<collaboration_id>/partners")
def list_collaboration_partners(collaboration_id):
    authenticate(*COLLAB_READ_ROLES)
    collaboration = get_collaboration(collaboration_id)
    status = q_enum("status", calc.PARTNER_STATUSES)
    limit, offset = pagination()
    items = [p for p in rows("collaboration_partners")
             if p["collaboration_id"] == collaboration["id"]
             and (status is None or p["status"] == status)]
    page, total = paginate(items, limit, offset)
    return list_response([public(p) for p in page], total, limit, offset)


@bp.get("/collaboration-partners/<partner_id>")
def read_collaboration_partner(partner_id):
    authenticate(*COLLAB_READ_ROLES)
    return object_response(public(get_partner(partner_id)))


@bp.post("/collaboration-partners/<partner_id>/withdraw")
def withdraw_collaboration_partner(partner_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    partner = get_partner(partner_id)
    data = body()
    v_str(data, "withdrawal_reason", required=False, default=None, min_len=0)
    collaboration = DB["collaborations"].get(partner["collaboration_id"])

    guards.require_not_terminal(partner["status"], calc.PARTNER_TERMINAL, "partner")
    if collaboration is None or collaboration["status"] not in ("DRAFT", "ACTIVE"):
        fail("ERR_INVALID_STATE",
             "the collaboration is not accepting partner changes")
    if (collaboration["status"] == "ACTIVE"
            and len(derive.confirmed_partners(collaboration["id"])) <= 1):
        fail("ERR_LAST_PARTNER_WITHDRAWAL",
             "an ACTIVE collaboration must retain at least one confirmed partner")

    apply_changes(partner, {
        "status": "WITHDRAWN",
        "withdrawn_at": iso_ms(now_clock()),
        "cost_owed_cents": 0,
        "remainder_rank": 0,
    }, force=True)
    # The folded shares and the re-run split are one single row mutation, so the
    # collaboration's version increments by exactly 1.
    collaboration["lead_credit_bps"] = (int(collaboration["lead_credit_bps"])
                                        + int(partner["credit_share_bps"]))
    collaboration["lead_cost_share_bps"] = (int(collaboration["lead_cost_share_bps"])
                                           + int(partner["cost_share_bps"]))
    before = int(collaboration["version"])
    derive.recompute_collaboration_split(collaboration)
    if int(collaboration["version"]) == before:
        touch(collaboration)
    return object_response(public(partner))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

COLLAB_SOURCES = {
    "ACTIVATE": ("DRAFT",),
    "SETTLE": ("ACTIVE",),
    "DISSOLVE": ("DRAFT", "ACTIVE"),
}


@bp.post("/collaborations/<collaboration_id>/status-actions")
def collaboration_status_actions(collaboration_id):
    authenticate(ROLE_EDITORIAL_DIRECTOR)
    collaboration = get_collaboration(collaboration_id)
    data = body()
    action = v_enum(data, "action", tuple(COLLAB_SOURCES))
    period = DB["fiscal_periods"].get(collaboration["fiscal_period_id"])

    guards.require_period_open(period)
    guards.require_not_terminal(collaboration["status"], calc.COLLABORATION_TERMINAL,
                                "collaboration")
    guards.require_state(collaboration["status"], COLLAB_SOURCES[action],
                         "collaboration")

    if action == "ACTIVATE":
        guards.require_publication_gate_open(collaboration["coverage_area_id"])
        start = parse_instant(collaboration["window_start"])
        end = parse_instant(collaboration["window_end"])
        for other in rows("collaborations"):
            if other["id"] == collaboration["id"]:
                continue
            if other["coverage_area_id"] != collaboration["coverage_area_id"]:
                continue
            if other["status"] != "ACTIVE":
                continue
            if half_open_overlap(start, end,
                                 parse_instant(other["window_start"]),
                                 parse_instant(other["window_end"])):
                fail("ERR_COLLABORATION_WINDOW_OVERLAP",
                     "another ACTIVE collaboration on this beat overlaps the window")
        partners = derive.confirmed_partners(collaboration["id"])
        credit_sum = int(collaboration["lead_credit_bps"]) + sum(
            int(p["credit_share_bps"]) for p in partners)
        if credit_sum != 10000:
            fail("ERR_CREDIT_SHARE_SUM_INVALID",
                 "credit shares sum to %s basis points" % credit_sum)
        cost_sum = int(collaboration["lead_cost_share_bps"]) + sum(
            int(p["cost_share_bps"]) for p in partners)
        if cost_sum != 10000:
            fail("ERR_COST_SHARE_SUM_INVALID",
                 "cost shares sum to %s basis points" % cost_sum)
        if not partners:
            fail("ERR_NO_CONFIRMED_PARTNER",
                 "at least one confirmed partner is required")
        derive.recompute_collaboration_split(collaboration,
                                             extra={"status": "ACTIVE"})
    elif action == "SETTLE":
        end = parse_instant(collaboration["window_end"])
        if end is not None and now_clock() < end:
            fail("ERR_COLLABORATION_WINDOW_OPEN",
                 "the production window has not closed")
        if int(collaboration["allocated_cost_cents"]) != int(collaboration["total_cost_cents"]):
            fail("ERR_INVALID_STATE",
                 "the allocated cost does not reconcile against the total cost")
        derive.recompute_collaboration_counts(collaboration, extra={
            "status": "SETTLED",
            "settled_at": iso_ms(now_clock()),
        })
    else:
        credit_folded = int(collaboration["lead_credit_bps"])
        cost_folded = int(collaboration["lead_cost_share_bps"])
        for partner in derive.confirmed_partners(collaboration["id"]):
            credit_folded += int(partner["credit_share_bps"])
            cost_folded += int(partner["cost_share_bps"])
            apply_changes(partner, {
                "status": "WITHDRAWN",
                "withdrawn_at": iso_ms(now_clock()),
                "cost_owed_cents": 0,
            }, force=True)
        collaboration["lead_credit_bps"] = credit_folded
        collaboration["lead_cost_share_bps"] = cost_folded
        derive.recompute_collaboration_split(collaboration,
                                            extra={"status": "DISSOLVED"})
    return object_response(public(collaboration))
