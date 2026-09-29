"""Institutions, giving periods and the logical clock."""

from flask import Blueprint, request

import auth
import calc
import envelope
import resolve
import serializers
import shapes
import store
from auth import (CREDIT_ANALYST, INSTITUTION_REP, PLATFORM_ADMIN, READ_ALL)
from errors import ApiError

bp = Blueprint("institutions", __name__)

INSTITUTION_TYPES = ("CONGREGATION", "SCHOOL", "DENOMINATIONAL_AGENCY",
                     "NONPROFIT_MINISTRY")
PERIOD_SOURCES = ("AUDITED", "INTERNAL")

LIST_ROLES = (PLATFORM_ADMIN, auth.CREDIT_ANALYST, auth.COMMITTEE_MEMBER,
              auth.LOAN_SERVICER)


# ---------------------------------------------------------------------------
# institutions
# ---------------------------------------------------------------------------


@bp.route("/institutions", methods=["POST"])
def create_institution():
    auth.authenticate((PLATFORM_ADMIN,))
    b = shapes.body()
    row = store.base_record()
    row.update({
        "legal_name": shapes.req_str(b, "legal_name"),
        "institution_type": shapes.req_enum(b, "institution_type",
                                            INSTITUTION_TYPES),
        "denomination_code": shapes.req_str(b, "denomination_code"),
        "requires_denominational_approval": shapes.opt_bool(
            b, "requires_denominational_approval", False),
        "bylaws_borrowing_cap_cents": shapes.req_int(
            b, "bylaws_borrowing_cap_cents", exclusive_minimum=0),
        "bylaws_quorum_pct": shapes.req_ratio(b, "bylaws_quorum_pct", gt=0,
                                              le=1),
        "community_program_count": shapes.opt_int(b, "community_program_count",
                                                  0, minimum=0),
        "endowment_market_value_cents": shapes.opt_int(
            b, "endowment_market_value_cents", 0, minimum=0),
        "audited_period_count": 0,
        "period_count": 0,
        "unrestricted_giving_base_cents": 0,
        "net_available_for_debt_service_dollars": 0,
        "membership_trend_pct": None,
        "cumulative_forgiveness_cents": 0,
    })
    store.institutions[row["id"]] = row
    store.mark_created(row)
    return envelope.created(serializers.institution(row))


@bp.route("/institutions/<institution_id>", methods=["GET"])
def get_institution(institution_id):
    ctx = auth.authenticate(READ_ALL)
    auth.scope(ctx, institution_id)
    row = resolve.institution(institution_id)
    return envelope.ok(serializers.institution(row))


@bp.route("/institutions", methods=["GET"])
def list_institutions():
    auth.authenticate(LIST_ROLES)
    rows = envelope.filter_rows(list(store.institutions.values()), {
        "institution_type": "institution_type",
        "denomination_code": "denomination_code",
    })
    return envelope.listing(envelope.sort_created_desc(rows),
                            serializers.institution)


# ---------------------------------------------------------------------------
# giving periods
# ---------------------------------------------------------------------------


@bp.route("/giving-periods", methods=["POST"])
def create_giving_period():
    ctx = auth.authenticate((CREDIT_ANALYST, INSTITUTION_REP))
    b = shapes.body()
    auth.scope(ctx, b.get("institution_id"))
    institution = resolve.institution(b.get("institution_id"))
    if institution is None:
        shapes.req_id_field(b, "institution_id")

    label = shapes.req_str(b, "period_label")
    start_raw, start_dt = shapes.req_dt(b, "period_start")
    end_raw, end_dt = shapes.req_dt(b, "period_end")
    if end_dt <= start_dt:
        shapes.bad("period_end", "must be after period_start")
    source = shapes.req_enum(b, "source", PERIOD_SOURCES)
    total = shapes.req_int(b, "total_contributions_cents", minimum=0)
    restricted = shapes.req_int(b, "restricted_contributions_cents", minimum=0)
    draw = shapes.req_int(b, "donor_restricted_endowment_draw_cents", minimum=0)
    opex = shapes.req_int(b, "operating_expense_cents", minimum=0)
    households = shapes.req_int(b, "member_household_count", minimum=0)

    # ladder 36: closed intervals of the same institution may not touch
    for other in calc.institution_periods(institution["id"]):
        if start_dt <= other["_period_end_dt"] and \
                other["_period_start_dt"] <= end_dt:
            raise ApiError("ERR_GIVING_PERIOD_OVERLAP")

    # ladder 43
    if restricted + draw > total:
        raise ApiError("ERR_RESTRICTED_EXCEEDS_TOTAL")

    unrestricted = total - restricted - draw
    if unrestricted < 0:
        unrestricted = 0
    net = unrestricted - opex
    if net < 0:
        net = 0

    row = store.base_record()
    row.update({
        "institution_id": institution["id"],
        "period_label": label,
        "period_start": start_raw,
        "period_end": end_raw,
        "source": source,
        "total_contributions_cents": total,
        "restricted_contributions_cents": restricted,
        "donor_restricted_endowment_draw_cents": draw,
        "operating_expense_cents": opex,
        "member_household_count": households,
        "unrestricted_contributions_cents": unrestricted,
        "net_available_for_debt_service_cents": net,
        "_period_start_dt": start_dt,
        "_period_end_dt": end_dt,
    })
    store.giving_periods[row["id"]] = row
    store.mark_created(row)

    # the institution's four computed figures are reconciled synchronously
    institution.update(calc.institution_computed(institution))
    store.touch(institution)
    return envelope.created(serializers.giving_period(row))


@bp.route("/giving-periods/<giving_period_id>", methods=["GET"])
def get_giving_period(giving_period_id):
    ctx = auth.authenticate(READ_ALL)
    row = resolve.giving_period(giving_period_id)
    auth.scope(ctx, row.get("institution_id"))
    return envelope.ok(serializers.giving_period(row))


@bp.route("/giving-periods", methods=["GET"])
def list_giving_periods():
    auth.authenticate(READ_ALL)
    rows = envelope.filter_rows(list(store.giving_periods.values()), {
        "institution_id": "institution_id",
        "source": "source",
    })
    rows = sorted(rows, key=lambda r: r["_seq"])
    rows = sorted(rows, key=lambda r: r["_period_end_dt"], reverse=True)
    return envelope.listing(rows, serializers.giving_period)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth.authenticate((PLATFORM_ADMIN,))
    b = shapes.body()
    _raw, parsed = shapes.req_dt(b, "to_iso8601")
    current = store.clock_set(parsed)
    return envelope.ok({"current_utc": store.iso_ms(current)})
