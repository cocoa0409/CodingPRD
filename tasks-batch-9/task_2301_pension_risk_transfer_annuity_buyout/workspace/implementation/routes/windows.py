"""Lump-sum windows, notice fan-out, elections, cap waterfall and disbursement."""

from flask import Blueprint, request

from db import days, db, make_entity, now, ordered, public, touch
from errors import api_error
from middleware import (
    authenticate,
    body,
    filter_arg,
    get_datetime,
    get_enum,
    get_int,
    get_string,
    lookup,
    pagination,
    require_range,
    slice_page,
)
from response import list_response, object_response
from services import calculations as calc
from services import domain as dom

bp = Blueprint("windows", __name__)

WINDOW_LIST_ROLES = ["PlanSponsor", "PlanFiduciary", "PlanAdministrator", "Actuary", "Regulator"]
ELECTION_READ_ROLES = [
    "PlanSponsor",
    "PlanFiduciary",
    "PlanAdministrator",
    "Actuary",
    "Regulator",
    "Participant",
]


# --------------------------------------------------------------------------
# windows
# --------------------------------------------------------------------------


@bp.post("/prt/plans/<plan_id>/lump-sum-windows")
def create_window(plan_id):
    authenticate(["PlanAdministrator"])
    plan = lookup("plans", plan_id)
    payload = body()
    label = get_string(payload, "window_name")
    if len(label) < 1 or len(label) > 120:
        raise api_error("ERR_INVALID_REQUEST", "window_name has an invalid length.")
    opens_at = get_datetime(payload, "opens_at")
    closes_at = get_datetime(payload, "closes_at")
    cap = get_int(payload, "lump_sum_cap_cents")
    eligibility_max = get_int(payload, "eligibility_max_lump_sum_cents")
    require_range(cap, "lump_sum_cap_cents", 1, None)
    require_range(eligibility_max, "eligibility_max_lump_sum_cents", 1, None)
    if not opens_at < closes_at:
        raise api_error("ERR_INVALID_INTERVAL", "closes_at must be strictly after opens_at.")

    for other in dom.plan_windows(plan["id"]):
        if other["window_status"] == "VOIDED":
            continue
        overlaps = opens_at < other["closes_at"] and other["opens_at"] < closes_at
        quiet_clear = opens_at >= other["closes_at"] + days(calc.QUIET_PERIOD_DAYS)
        if overlaps or not quiet_clear:
            raise api_error("ERR_WINDOW_QUIET_PERIOD_CONFLICT")

    window = make_entity()
    window["plan_id"] = plan["id"]
    window["window_label"] = label
    window["opens_at"] = opens_at
    window["closes_at"] = closes_at
    window["eligibility_max_lump_sum_cents"] = eligibility_max
    window["lump_sum_cap_cents"] = cap
    window["window_status"] = "PLANNED"
    window["notice_count"] = 0
    window["approved_lump_sum_total_cents"] = 0
    window["paid_lump_sum_total_cents"] = 0
    window["opened_at"] = None
    window["closed_at"] = None
    window["settled_at"] = None
    db.windows[window["id"]] = window
    return object_response(public(window), 201)


@bp.get("/prt/plans/<plan_id>/lump-sum-windows")
def list_windows(plan_id):
    authenticate(WINDOW_LIST_ROLES)
    plan = lookup("plans", plan_id)
    status = request.args.get("window_status")
    limit, offset = pagination()
    records = dom.plan_windows(plan["id"])
    if status is not None:
        records = [w for w in records if w["window_status"] == status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(w) for w in page], limit, offset, total)


@bp.post("/prt/lump-sum-windows/<window_id>/opening")
def open_window(window_id):
    authenticate(["PlanAdministrator"])
    window = lookup("windows", window_id)
    body()
    clock = now()

    # Priority 9 — notice period.
    if window["closes_at"] - clock < days(calc.NOTICE_PERIOD_DAYS):
        raise api_error("ERR_NOTICE_PERIOD_TOO_SHORT")
    # Priority 11 — the window's own state.
    if window["window_status"] != "PLANNED":
        raise api_error("ERR_WINDOW_STATE_INVALID")
    if not (window["opens_at"] <= clock < window["closes_at"]):
        raise api_error("ERR_WINDOW_STATE_INVALID")
    # Priority 13 — the plan's authorization.
    plan = db.plans[window["plan_id"]]
    if plan["plan_status"] != "SETTLEMENT_AUTHORIZED" or plan["amendment_scope"] not in (
        "LUMP_SUM_ONLY",
        "BOTH",
    ):
        raise api_error("ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED")

    window["window_status"] = "OPEN"
    window["opened_at"] = clock
    count = 0
    for participant in dom.plan_participants(plan["id"]):
        if participant["participant_status"] != "IN_PLAN":
            continue
        if participant["mortality_status"] != "ALIVE_CONFIRMED":
            continue
        if participant["address_status"] != "CONFIRMED":
            continue
        pricing = calc.lump_sum_present_value(participant)
        if pricing["raw_pv_cents"] > window["eligibility_max_lump_sum_cents"]:
            continue
        election = make_entity()
        election["window_id"] = window["id"]
        election["participant_id"] = participant["id"]
        election["election_status"] = "NOTICE_SENT"
        election["notice_sent_at"] = clock
        election["notice_estimated_lump_sum_cents"] = pricing["raw_pv_cents"]
        election["election_choice"] = None
        election["elected_at"] = None
        election["raw_pv_cents"] = None
        election["admin_fee_bp"] = None
        election["admin_fee_cents"] = None
        election["net_lump_sum_cents"] = None
        election["revocation_count"] = 0
        election["paid_at"] = None
        election["paid_amount_cents"] = None
        db.elections[election["id"]] = election
        count += 1
    window["notice_count"] = count
    touch(window)
    return object_response(public(window))


def _waterfall_key(election):
    participant = db.participants.get(election["participant_id"])
    participant_created = participant["created_at"] if participant else election["created_at"]
    return (
        election["elected_at"],
        participant_created,
        election["created_at"],
        election["_seq"],
    )


@bp.post("/prt/lump-sum-windows/<window_id>/closing")
def close_window(window_id):
    authenticate(["PlanAdministrator"])
    window = lookup("windows", window_id)
    body()
    clock = now()
    if window["window_status"] != "OPEN":
        raise api_error("ERR_WINDOW_STATE_INVALID")
    if clock < window["closes_at"]:
        raise api_error("ERR_WINDOW_STATE_INVALID")

    elections = dom.window_elections(window["id"])
    for election in elections:
        if election["election_status"] == "NOTICE_SENT":
            election["election_status"] = "DEFAULTED_NO_RESPONSE"
            touch(election)

    candidates = sorted(
        [e for e in elections if e["election_status"] == "ELECTED_LUMP_SUM"],
        key=_waterfall_key,
    )
    running = 0
    cap = window["lump_sum_cap_cents"]
    for election in candidates:
        candidate_total = running + (election["net_lump_sum_cents"] or 0)
        if candidate_total <= cap:
            running = candidate_total
        else:
            election["election_status"] = "CAP_DEFERRED"
            touch(election)
    window["approved_lump_sum_total_cents"] = running
    window["window_status"] = "CLOSED"
    window["closed_at"] = clock
    touch(window)
    return object_response(public(window))


@bp.post("/prt/lump-sum-windows/<window_id>/settlement")
def settle_window(window_id):
    authenticate(["PlanSponsor"])
    window = lookup("windows", window_id)
    body()
    if window["window_status"] != "CLOSED":
        raise api_error("ERR_WINDOW_STATE_INVALID")

    plan = db.plans[window["plan_id"]]
    honoured = [
        e
        for e in dom.window_elections(window["id"])
        if e["election_status"] == "ELECTED_LUMP_SUM"
    ]

    # Priority 31 — re-price from each participant's current audited benefit.
    repriced_total = 0
    for election in honoured:
        participant = db.participants[election["participant_id"]]
        repriced_total += calc.lump_sum_present_value(participant)["net_lump_sum_cents"]
    if repriced_total > window["lump_sum_cap_cents"]:
        raise api_error("ERR_WINDOW_CAP_EXCEEDED")

    # Priority 34 — plan asset sufficiency.
    if plan["plan_assets_cents"] < window["approved_lump_sum_total_cents"]:
        raise api_error("ERR_PLAN_ASSETS_INSUFFICIENT")

    clock = now()
    paid_total = 0
    pbo_settled = 0
    for election in honoured:
        election["election_status"] = "PAID"
        election["paid_at"] = clock
        election["paid_amount_cents"] = election["net_lump_sum_cents"]
        paid_total += election["paid_amount_cents"] or 0
        touch(election)
        participant = db.participants[election["participant_id"]]
        pbo_settled += participant["accounting_liability_cents"] or 0
        participant["participant_status"] = "SETTLED_LUMP_SUM"
        participant["tranche_id"] = None
        touch(participant)

    dom.append_settlement_entry(
        plan,
        "LUMP_SUM_RECOGNITION",
        paid_total - pbo_settled,
        0,
        paid_total - pbo_settled,
        pbo_settled,
        "LumpSumWindow CLOSED -> SETTLED",
        window_id=window["id"],
    )

    plan["total_liability_cents"] = plan["total_liability_cents"] - pbo_settled
    plan["plan_assets_cents"] = plan["plan_assets_cents"] - paid_total
    dom.recompute_plan_participant_liability(plan)
    dom.recompute_plan_accounting_funded_status(plan)

    window["window_status"] = "SETTLED"
    window["paid_lump_sum_total_cents"] = paid_total
    window["settled_at"] = clock
    touch(window)

    dom.maybe_transition_to_residual(plan)
    return object_response(public(window))


# --------------------------------------------------------------------------
# elections
# --------------------------------------------------------------------------


@bp.get("/prt/elections")
def list_elections():
    authenticate(ELECTION_READ_ROLES)
    window_id = filter_arg("windows", "window_id")
    participant_id = filter_arg("participants", "participant_id")
    election_status = request.args.get("election_status")
    limit, offset = pagination()
    records = ordered(list(db.elections.values()))
    if window_id is not None:
        records = [e for e in records if e["window_id"] == window_id]
    if participant_id is not None:
        records = [e for e in records if e["participant_id"] == participant_id]
    if election_status is not None:
        records = [e for e in records if e["election_status"] == election_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(e) for e in page], limit, offset, total)


@bp.get("/prt/elections/<election_id>")
def get_election(election_id):
    authenticate(ELECTION_READ_ROLES)
    election = lookup("elections", election_id)
    return object_response(public(election))


@bp.post("/prt/elections/<election_id>/election")
def make_election(election_id):
    user_id, _role = authenticate(["Participant"])
    election = lookup("elections", election_id)
    if user_id != election["participant_id"]:
        raise api_error("ERR_IDENTITY_MISMATCH")
    payload = body()
    choice = get_enum(payload, "election_choice", ("LUMP_SUM", "ANNUITY"))

    if election["election_status"] != "NOTICE_SENT":
        raise api_error("ERR_ELECTION_STATE_INVALID")
    window = db.windows[election["window_id"]]
    clock = now()
    if window["window_status"] != "OPEN" or clock >= window["closes_at"]:
        raise api_error("ERR_WINDOW_NOT_OPEN")
    participant = db.participants[election["participant_id"]]
    if participant["benefit_audit_status"] not in ("PASSED_CLOSED", "CORRECTED"):
        raise api_error("ERR_PARTICIPANT_DATA_NOT_CLEAN")
    if participant["mortality_status"] != "ALIVE_CONFIRMED":
        raise api_error("ERR_MORTALITY_NOT_CONFIRMED")
    pricing = calc.lump_sum_present_value(participant)
    if pricing["raw_pv_cents"] > window["eligibility_max_lump_sum_cents"]:
        raise api_error("ERR_LUMP_SUM_NOT_ELIGIBLE")

    election["election_choice"] = choice
    election["elected_at"] = clock
    if choice == "LUMP_SUM":
        election["election_status"] = "ELECTED_LUMP_SUM"
        election["raw_pv_cents"] = pricing["raw_pv_cents"]
        election["admin_fee_bp"] = pricing["admin_fee_bp"]
        election["admin_fee_cents"] = pricing["admin_fee_cents"]
        election["net_lump_sum_cents"] = pricing["net_lump_sum_cents"]
    else:
        election["election_status"] = "ELECTED_ANNUITY"
    touch(election)
    return object_response(public(election))


@bp.post("/prt/elections/<election_id>/revocation")
def revoke_election(election_id):
    user_id, _role = authenticate(["Participant"])
    election = lookup("elections", election_id)
    if user_id != election["participant_id"]:
        raise api_error("ERR_IDENTITY_MISMATCH")
    body()

    if election["election_status"] not in ("ELECTED_LUMP_SUM", "ELECTED_ANNUITY"):
        raise api_error("ERR_ELECTION_STATE_INVALID")
    if election["revocation_count"] >= calc.REVOCATION_MAX:
        raise api_error("ERR_ELECTION_STATE_INVALID")
    window = db.windows[election["window_id"]]
    if window["window_status"] != "OPEN":
        raise api_error("ERR_WINDOW_NOT_OPEN")
    clock = now()
    deadline = election["elected_at"] + days(calc.REVOCATION_PERIOD_DAYS)
    if clock > deadline or clock >= window["closes_at"]:
        raise api_error("ERR_REVOCATION_PERIOD_ELAPSED")

    election["election_status"] = "NOTICE_SENT"
    election["elected_at"] = None
    election["election_choice"] = None
    election["raw_pv_cents"] = None
    election["admin_fee_bp"] = None
    election["admin_fee_cents"] = None
    election["net_lump_sum_cents"] = None
    election["revocation_count"] = election["revocation_count"] + 1
    touch(election)
    return object_response(public(election))
