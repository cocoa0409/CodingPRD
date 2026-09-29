"""Logical clock and jurisdiction reference data (PRD §2.4, §3.1)."""

import re

from flask import Blueprint

from db import base_row, db, fmt_ts, serialize
from errors import ApiError
from middleware import authorize
from response import created, ok
from validators import bad, get_body, v_bool, v_dt, v_enum, v_int, v_str

bp = Blueprint("system", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize("PlatformAdmin")
    body = get_body()
    _, parsed = v_dt(body, "to_iso8601", required=True)
    db.clock = parsed
    return ok({"current_utc": fmt_ts(db.clock)})


@bp.post("/jurisdictions")
def create_jurisdiction():
    authorize("PlatformAdmin")
    body = get_body()
    state_code = v_str(body, "state_code")
    if not STATE_CODE_RE.match(state_code):
        bad("state_code must be exactly two uppercase letters")
    name = v_str(body, "name")
    min_net_worth_cents = v_int(body, "min_net_worth_cents", minimum=0)
    base_bond_cents = v_int(body, "base_bond_cents", minimum=0)
    per_delegate_bond_cents = v_int(body, "per_delegate_bond_cents", minimum=0)
    bond_cap_cents = v_int(body, "bond_cap_cents", minimum=0)
    if bond_cap_cents < base_bond_cents:
        bad("bond_cap_cents must not be below base_bond_cents")
    response_window_days = v_int(body, "response_window_days", minimum=1)
    renewal_fee_cents = v_int(body, "renewal_fee_cents", minimum=0)
    assessment_rate_bps = v_int(body, "assessment_rate_bps", minimum=0)
    call_report_frequency = v_enum(body, "call_report_frequency", ("QUARTERLY", "ANNUAL"))
    participates = v_bool(body, "participates_in_multistate", required=False, default=True)

    for existing in db.jurisdictions.values():
        if existing["state_code"] == state_code:
            raise ApiError(
                "ERR_DUPLICATE_STATE_CODE",
                "Jurisdiction %s is already configured" % state_code,
            )

    row = base_row(with_common_fields=False)
    row.update(
        {
            "state_code": state_code,
            "name": name,
            "min_net_worth_cents": min_net_worth_cents,
            "base_bond_cents": base_bond_cents,
            "per_delegate_bond_cents": per_delegate_bond_cents,
            "bond_cap_cents": bond_cap_cents,
            "response_window_days": response_window_days,
            "renewal_fee_cents": renewal_fee_cents,
            "assessment_rate_bps": assessment_rate_bps,
            "participates_in_multistate": participates,
            "call_report_frequency": call_report_frequency,
        }
    )
    db.jurisdictions[row["id"]] = row
    return created(serialize(row))
