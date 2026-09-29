"""Buyout tranches, carrier registry, quotes, selection, lock, funding, experts."""

from flask import Blueprint, request

from db import days, db, make_entity, now, ordered, public, touch
from errors import api_error
from middleware import (
    authenticate,
    body,
    filter_arg,
    get_bool,
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

bp = Blueprint("buyout", __name__)

TRANCHE_READ_ROLES = [
    "PlanSponsor",
    "PlanFiduciary",
    "Actuary",
    "PlanAdministrator",
    "Regulator",
    "InsurerRep",
]
QUOTE_READ_ROLES = ["PlanSponsor", "PlanFiduciary", "Actuary", "Regulator", "InsurerRep"]
INSURER_READ_ROLES = QUOTE_READ_ROLES
TRANSFER_READ_ROLES = ["PlanSponsor", "PlanFiduciary", "Regulator", "InsurerRep"]
EXPERT_READ_ROLES = ["PlanSponsor", "PlanFiduciary", "Regulator", "IndependentExpertUser"]

COHORTS = ("RETIREE_IN_PAY", "DEFERRED_VESTED")
RATING_GRADES = ("AAA", "AA_PLUS", "AA", "AA_MINUS", "A_PLUS", "A", "BBB")
INSURER_STATUSES = ("ACTIVE", "UNDER_REVIEW", "WITHDRAWN")
SELECTION_BASES = ("SAFETY_WEIGHTED", "PRICE_WEIGHTED")
LIVE_QUOTE_STATUSES = ("REQUESTED", "SUBMITTED", "SHORTLISTED", "LOCKED", "BOUND")
ABANDONABLE = ("DRAFT", "QUOTING", "INSURER_SELECTED", "PRICING_LOCKED")
OPINIONS = ("AFFIRMATIVE", "QUALIFIED", "ADVERSE")


def _rating_points(grade):
    return calc.RATING_POINTS.get(grade, 0)


def _meets_floor(grade):
    return _rating_points(grade) >= calc.SAFEST_AVAILABLE_MIN_RATING_POINTS


def _bounded_string(payload, name, low, high, required=True):
    value = get_string(payload, name, required=required)
    if value is None:
        return None
    if len(value) < low or len(value) > high:
        raise api_error("ERR_INVALID_REQUEST", "Field '%s' has an invalid length." % name)
    return value


# --------------------------------------------------------------------------
# tranches
# --------------------------------------------------------------------------


@bp.post("/prt/plans/<plan_id>/tranches")
def create_tranche(plan_id):
    authenticate(["PlanFiduciary"])
    plan = lookup("plans", plan_id)
    payload = body()
    label = _bounded_string(payload, "tranche_name", 1, 120)
    target_cohort = get_enum(payload, "target_cohort", COHORTS)

    tranche = make_entity()
    tranche["plan_id"] = plan["id"]
    tranche["tranche_label"] = label
    tranche["target_cohort"] = target_cohort
    tranche["tranche_status"] = "DRAFT"
    tranche["assigned_participant_count"] = 0
    tranche["accounting_liability_cents"] = 0
    tranche["settlement_liability_cents"] = 0
    tranche["data_readiness_flag"] = "BLOCKED"
    tranche["selection_basis"] = None
    tranche["selected_quote_id"] = None
    tranche["selected_insurer_id"] = None
    tranche["selection_score_bp"] = None
    tranche["locked_premium_cents"] = None
    tranche["lock_start_at"] = None
    tranche["lock_expires_at"] = None
    tranche["transfer_expense_cents"] = 0
    tranche["settlement_gain_loss_cents"] = None
    tranche["settled_at"] = None
    tranche["abandoned_at"] = None
    tranche["abandonment_reason"] = None
    db.tranches[tranche["id"]] = tranche
    return object_response(public(tranche), 201)


@bp.get("/prt/tranches")
def list_tranches():
    authenticate(TRANCHE_READ_ROLES)
    plan_id = filter_arg("plans", "plan_id")
    selected_quote_id = filter_arg("quotes", "selected_quote_id")
    selected_insurer_id = filter_arg("insurers", "selected_insurer_id")
    tranche_status = request.args.get("tranche_status")
    limit, offset = pagination()
    records = ordered(list(db.tranches.values()))
    if plan_id is not None:
        records = [t for t in records if t["plan_id"] == plan_id]
    if selected_quote_id is not None:
        records = [t for t in records if t["selected_quote_id"] == selected_quote_id]
    if selected_insurer_id is not None:
        records = [t for t in records if t["selected_insurer_id"] == selected_insurer_id]
    if tranche_status is not None:
        records = [t for t in records if t["tranche_status"] == tranche_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(t) for t in page], limit, offset, total)


@bp.get("/prt/tranches/<tranche_id>")
def get_tranche(tranche_id):
    authenticate(TRANCHE_READ_ROLES)
    tranche = lookup("tranches", tranche_id)
    return object_response(public(tranche))


@bp.post("/prt/tranches/<tranche_id>/participant-assignments")
def assign_participant(tranche_id):
    authenticate(["PlanAdministrator"])
    tranche = lookup("tranches", tranche_id)
    payload = body()
    participant_id = get_string(payload, "participant_id")
    participant = lookup("participants", participant_id)

    if tranche["tranche_status"] != "DRAFT":
        raise api_error("ERR_TRANCHE_STATE_INVALID")
    if participant["plan_id"] != tranche["plan_id"]:
        raise api_error("ERR_PARTICIPANT_PLAN_MISMATCH")
    if participant["cohort"] != tranche["target_cohort"]:
        raise api_error("ERR_PARTICIPANT_PLAN_MISMATCH")
    if participant["participant_status"] != "IN_PLAN":
        raise api_error("ERR_PARTICIPANT_ALREADY_ASSIGNED")

    participant["participant_status"] = "ASSIGNED"
    participant["tranche_id"] = tranche["id"]
    touch(participant)
    dom.recompute_tranche(tranche)
    return object_response(public(tranche))


@bp.post("/prt/tranches/<tranche_id>/quoting")
def open_quoting(tranche_id):
    authenticate(["PlanFiduciary"])
    tranche = lookup("tranches", tranche_id)
    body()
    if tranche["tranche_status"] != "DRAFT":
        raise api_error("ERR_TRANCHE_STATE_INVALID")
    plan = db.plans[tranche["plan_id"]]
    if plan["plan_status"] != "SETTLEMENT_AUTHORIZED" or plan["amendment_scope"] not in (
        "BUYOUT_ONLY",
        "BOTH",
    ):
        raise api_error("ERR_PLAN_NOT_SETTLEMENT_AUTHORIZED")

    assigned = dom.tranche_assigned_participants(tranche)
    for participant in assigned:
        if participant["data_status"] != "CLEAN":
            raise api_error("ERR_PARTICIPANT_DATA_NOT_CLEAN")
    for participant in assigned:
        if participant["mortality_status"] != "ALIVE_CONFIRMED":
            raise api_error("ERR_MORTALITY_NOT_CONFIRMED")
    if not assigned:
        raise api_error("ERR_TRANCHE_EMPTY")
    engaged = [
        e
        for e in dom.plan_experts(plan["id"])
        if e["expert_status"] in ("ENGAGED", "OPINION_ISSUED")
    ]
    if not engaged:
        raise api_error("ERR_EXPERT_STATE_INVALID")

    tranche["tranche_status"] = "QUOTING"
    dom.recompute_tranche(tranche, readiness="READY", count=False)
    return object_response(public(tranche))


@bp.post("/prt/tranches/<tranche_id>/abandonment")
def abandon_tranche(tranche_id):
    authenticate(["PlanFiduciary"])
    tranche = lookup("tranches", tranche_id)
    payload = body()
    reason = get_string(payload, "abandonment_reason")
    if tranche["tranche_status"] not in ABANDONABLE:
        raise api_error("ERR_TRANCHE_STATE_INVALID")

    insurer_id = tranche["selected_insurer_id"]
    selected_quote_id = tranche["selected_quote_id"]
    was_locked = tranche["locked_premium_cents"] is not None
    prior_lock_start = tranche["lock_start_at"]
    prior_lock_end = tranche["lock_expires_at"]

    tranche["tranche_status"] = "ABANDONED"
    tranche["abandoned_at"] = now()
    tranche["abandonment_reason"] = reason

    if was_locked and selected_quote_id:
        quote = db.quotes.get(selected_quote_id)
        if quote is not None and quote["quote_status"] == "LOCKED":
            quote["quote_status"] = "EXPIRED"
            touch(quote)
    for quote in dom.tranche_quotes(tranche["id"]):
        if quote["quote_status"] in ("REQUESTED", "SUBMITTED", "SHORTLISTED"):
            quote["quote_status"] = "EXPIRED"
            touch(quote)
    for participant in dom.tranche_assigned_participants(tranche):
        participant["participant_status"] = "IN_PLAN"
        participant["tranche_id"] = None
        touch(participant)

    tranche["selected_quote_id"] = None
    tranche["selected_insurer_id"] = None
    tranche["selection_score_bp"] = None
    tranche["locked_premium_cents"] = None
    tranche["lock_start_at"] = None
    tranche["lock_expires_at"] = None
    tranche["assigned_participant_count"] = dom.tranche_member_count(tranche)
    dom.recompute_tranche_liabilities(tranche)
    touch(tranche)

    if was_locked and insurer_id:
        insurer = db.insurers.get(insurer_id)
        if insurer is not None:
            dom.recompute_insurer_capacity(
                insurer, window_start=prior_lock_start, window_end=prior_lock_end
            )
    plan = db.plans.get(tranche["plan_id"])
    if plan is not None:
        dom.recompute_plan_participant_liability(plan)
    return object_response(public(tranche))


# --------------------------------------------------------------------------
# carrier registry
# --------------------------------------------------------------------------


@bp.post("/prt/insurers")
def create_insurer():
    authenticate(["Regulator"])
    payload = body()
    name = _bounded_string(payload, "insurer_name", 1, 200)
    rating_grade = get_enum(payload, "rating_grade", RATING_GRADES)
    capital_ratio_bp = get_int(payload, "capital_ratio_bp")
    capacity = get_int(payload, "capacity_cents")
    guaranty = get_int(payload, "state_guaranty_coverage_cents", required=False, default=0)
    require_range(capital_ratio_bp, "capital_ratio_bp", 0, 20000)
    require_range(capacity, "capacity_cents", 1, None)
    require_range(guaranty, "state_guaranty_coverage_cents", 0, None)
    for existing in db.insurers.values():
        if existing["insurer_name"] == name:
            raise api_error("ERR_INVALID_REQUEST", "insurer_name is already registered.")

    insurer = make_entity()
    insurer["insurer_name"] = name
    insurer["rating_grade"] = rating_grade
    insurer["capital_ratio_bp"] = capital_ratio_bp
    insurer["state_guaranty_coverage_cents"] = guaranty
    insurer["capacity_cents"] = capacity
    insurer["committed_capacity_cents"] = 0
    insurer["available_capacity_cents"] = capacity
    insurer["insurer_status"] = "ACTIVE"
    insurer["rating_changed_at"] = None
    db.insurers[insurer["id"]] = insurer
    return object_response(public(insurer), 201)


@bp.get("/prt/insurers/<insurer_id>")
def get_insurer(insurer_id):
    authenticate(INSURER_READ_ROLES)
    insurer = lookup("insurers", insurer_id)
    return object_response(public(insurer))


@bp.post("/prt/insurers/<insurer_id>/rating-changes")
def rating_change(insurer_id):
    authenticate(["Regulator"])
    insurer = lookup("insurers", insurer_id)
    payload = body()
    rating_grade = get_enum(payload, "rating_grade", RATING_GRADES)
    capital_ratio_bp = get_int(payload, "capital_ratio_bp", required=False)
    insurer_status = get_enum(payload, "insurer_status", INSURER_STATUSES, required=False)
    require_range(capital_ratio_bp, "capital_ratio_bp", 0, 20000)

    insurer["rating_grade"] = rating_grade
    if capital_ratio_bp is not None:
        insurer["capital_ratio_bp"] = capital_ratio_bp
    if insurer_status is not None:
        insurer["insurer_status"] = insurer_status
    insurer["rating_changed_at"] = now()
    touch(insurer)

    if not _meets_floor(rating_grade):
        for quote in ordered([q for q in db.quotes.values() if q["insurer_id"] == insurer["id"]]):
            if quote["quote_status"] not in ("SUBMITTED", "SHORTLISTED"):
                continue
            was_shortlisted = quote["quote_status"] == "SHORTLISTED"
            quote["quote_status"] = "INELIGIBLE"
            touch(quote)
            if not was_shortlisted:
                continue
            tranche = db.tranches.get(quote["tranche_id"])
            if tranche is None:
                continue
            if tranche["selected_quote_id"] != quote["id"]:
                continue
            if tranche["tranche_status"] != "INSURER_SELECTED":
                continue
            tranche["tranche_status"] = "QUOTING"
            tranche["selected_quote_id"] = None
            tranche["selected_insurer_id"] = None
            tranche["selection_score_bp"] = None
            tranche["selection_basis"] = None
            dom.recompute_tranche(tranche, readiness="BLOCKED", count=False, liabilities=False)
    return object_response(public(insurer))


# --------------------------------------------------------------------------
# independent experts
# --------------------------------------------------------------------------


@bp.post("/prt/plans/<plan_id>/independent-experts")
def propose_expert(plan_id):
    user_id, _role = authenticate(["PlanSponsor"])
    plan = lookup("plans", plan_id)
    payload = body()
    firm_name = _bounded_string(payload, "expert_firm_name", 1, 200)
    scope = get_string(payload, "engagement_scope")
    conflict = get_bool(payload, "conflict_disclosed", required=False, default=False)

    expert = make_entity()
    expert["plan_id"] = plan["id"]
    expert["expert_firm_name"] = firm_name
    expert["engagement_scope"] = scope
    expert["conflict_disclosed"] = bool(conflict)
    expert["expert_status"] = "INDEPENDENCE_REVIEW"
    expert["proposed_by_user_id"] = user_id
    expert["reviewed_by_user_id"] = None
    expert["safest_available_opinion"] = None
    expert["opinion_issued_at"] = None
    db.experts[expert["id"]] = expert
    return object_response(public(expert), 201)


@bp.get("/prt/plans/<plan_id>/independent-experts")
def list_experts(plan_id):
    authenticate(EXPERT_READ_ROLES)
    plan = lookup("plans", plan_id)
    expert_status = request.args.get("expert_status")
    limit, offset = pagination()
    records = dom.plan_experts(plan["id"])
    if expert_status is not None:
        records = [e for e in records if e["expert_status"] == expert_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(e) for e in page], limit, offset, total)


@bp.get("/prt/independent-experts/<expert_id>")
def get_expert(expert_id):
    authenticate(EXPERT_READ_ROLES)
    expert = lookup("experts", expert_id)
    return object_response(public(expert))


@bp.post("/prt/independent-experts/<expert_id>/independence-review")
def independence_review(expert_id):
    user_id, _role = authenticate(["PlanFiduciary"])
    expert = lookup("experts", expert_id)
    payload = body()
    decision = get_enum(payload, "review_decision", ("ENGAGE", "DISQUALIFY"))
    if expert["expert_status"] != "INDEPENDENCE_REVIEW":
        raise api_error("ERR_EXPERT_STATE_INVALID")
    if expert["proposed_by_user_id"] is not None and user_id == expert["proposed_by_user_id"]:
        raise api_error("ERR_SEGREGATION_OF_DUTIES")
    if decision == "ENGAGE" and expert["conflict_disclosed"]:
        raise api_error("ERR_EXPERT_CONFLICT_DISCLOSED")

    expert["expert_status"] = "ENGAGED" if decision == "ENGAGE" else "DISQUALIFIED"
    expert["reviewed_by_user_id"] = user_id
    touch(expert)
    return object_response(public(expert))


@bp.post("/prt/independent-experts/<expert_id>/opinion")
def issue_opinion(expert_id):
    user_id, _role = authenticate(["IndependentExpertUser"])
    if user_id != expert_id:
        raise api_error("ERR_IDENTITY_MISMATCH")
    expert = lookup("experts", expert_id)
    payload = body()
    opinion = get_enum(payload, "safest_available_opinion", OPINIONS)
    if expert["expert_status"] != "ENGAGED":
        raise api_error("ERR_EXPERT_NOT_ENGAGED")

    expert["expert_status"] = "OPINION_ISSUED"
    expert["safest_available_opinion"] = opinion
    expert["opinion_issued_at"] = now()
    touch(expert)
    return object_response(public(expert))


# --------------------------------------------------------------------------
# quotes
# --------------------------------------------------------------------------


@bp.post("/prt/tranches/<tranche_id>/quotes")
def request_quote(tranche_id):
    authenticate(["PlanFiduciary"])
    tranche = lookup("tranches", tranche_id)
    payload = body()
    insurer_id = get_string(payload, "insurer_id")
    insurer = lookup("insurers", insurer_id)

    if tranche["tranche_status"] != "QUOTING":
        raise api_error("ERR_TRANCHE_STATE_INVALID")
    if not _meets_floor(insurer["rating_grade"]) or insurer["insurer_status"] != "ACTIVE":
        raise api_error("ERR_INSURER_RATING_BELOW_FLOOR")
    for existing in dom.tranche_quotes(tranche["id"]):
        if existing["insurer_id"] == insurer["id"] and existing["quote_status"] in (
            LIVE_QUOTE_STATUSES
        ):
            raise api_error("ERR_DUPLICATE_QUOTE_REQUEST")

    quote = make_entity()
    quote["tranche_id"] = tranche["id"]
    quote["insurer_id"] = insurer["id"]
    quote["quote_status"] = "REQUESTED"
    quote["requested_at"] = now()
    quote["premium_cents"] = None
    quote["lock_days"] = None
    quote["quote_valid_days"] = None
    quote["submitted_at"] = None
    quote["expires_at"] = None
    quote["rating_at_submission"] = None
    quote["composite_score_bp"] = None
    quote["decline_reason"] = None
    db.quotes[quote["id"]] = quote
    touch(tranche)
    return object_response(public(quote), 201)


@bp.get("/prt/quotes")
def list_quotes():
    authenticate(QUOTE_READ_ROLES)
    tranche_id = filter_arg("tranches", "tranche_id")
    insurer_id = filter_arg("insurers", "insurer_id")
    quote_status = request.args.get("quote_status")
    limit, offset = pagination()
    records = ordered(list(db.quotes.values()))
    if tranche_id is not None:
        records = [q for q in records if q["tranche_id"] == tranche_id]
    if insurer_id is not None:
        records = [q for q in records if q["insurer_id"] == insurer_id]
    if quote_status is not None:
        records = [q for q in records if q["quote_status"] == quote_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(q) for q in page], limit, offset, total)


@bp.get("/prt/quotes/<quote_id>")
def get_quote(quote_id):
    authenticate(QUOTE_READ_ROLES)
    quote = lookup("quotes", quote_id)
    return object_response(public(quote))


@bp.post("/prt/quotes/<quote_id>/submission")
def quote_submission(quote_id):
    user_id, _role = authenticate(["InsurerRep"])
    quote = lookup("quotes", quote_id)
    if user_id != quote["insurer_id"]:
        raise api_error("ERR_IDENTITY_MISMATCH")
    payload = body()
    decision = get_enum(payload, "submission_decision", ("SUBMIT", "DECLINE"))
    premium = None
    lock_days = None
    valid_days = None
    decline_reason = None
    if decision == "SUBMIT":
        premium = get_int(payload, "premium_cents")
        lock_days = get_int(payload, "lock_days")
        valid_days = get_int(payload, "quote_valid_days")
        require_range(premium, "premium_cents", 1, None)
        require_range(lock_days, "lock_days", 1, 180)
        require_range(valid_days, "quote_valid_days", 1, 90)
    else:
        decline_reason = get_string(payload, "decline_reason")

    if quote["quote_status"] != "REQUESTED":
        if quote["quote_status"] in ("SUBMITTED", "SHORTLISTED", "LOCKED"):
            raise api_error("ERR_QUOTE_NOT_REQUESTED")
        raise api_error("ERR_QUOTE_STATE_INVALID")

    if decision == "DECLINE":
        quote["quote_status"] = "DECLINED"
        quote["decline_reason"] = decline_reason
        touch(quote)
        return object_response(public(quote))

    insurer = db.insurers.get(quote["insurer_id"])
    stamp = now()
    quote["quote_status"] = "SUBMITTED"
    quote["premium_cents"] = premium
    quote["lock_days"] = lock_days
    quote["quote_valid_days"] = valid_days
    quote["submitted_at"] = stamp
    quote["expires_at"] = stamp + days(valid_days)
    quote["rating_at_submission"] = insurer["rating_grade"] if insurer else None
    touch(quote)
    return object_response(public(quote))


# --------------------------------------------------------------------------
# selection and pricing lock
# --------------------------------------------------------------------------


@bp.post("/prt/tranches/<tranche_id>/insurer-selection")
def select_insurer(tranche_id):
    authenticate(["PlanFiduciary"])
    tranche = lookup("tranches", tranche_id)
    payload = body()
    basis = get_enum(payload, "selection_basis", SELECTION_BASES)

    if tranche["tranche_status"] != "QUOTING":
        raise api_error("ERR_TRANCHE_STATE_INVALID")
    affirmative = [
        e
        for e in dom.plan_experts(tranche["plan_id"])
        if e["expert_status"] == "OPINION_ISSUED"
        and e["safest_available_opinion"] == "AFFIRMATIVE"
    ]
    if not affirmative:
        raise api_error("ERR_EXPERT_OPINION_REQUIRED")
    assigned = dom.tranche_assigned_participants(tranche)
    for participant in assigned:
        if participant["benefit_audit_status"] not in dom.AUDIT_CLEAN_STATUSES:
            raise api_error("ERR_PARTICIPANT_DATA_NOT_CLEAN")

    clock = now()
    quotes = dom.tranche_quotes(tranche["id"])
    candidates = []
    for quote in quotes:
        if quote["quote_status"] != "SUBMITTED":
            continue
        if quote["expires_at"] is None or quote["expires_at"] <= clock:
            continue
        if not _meets_floor(quote["rating_at_submission"]):
            continue
        insurer = db.insurers.get(quote["insurer_id"])
        if insurer is None or insurer["insurer_status"] != "ACTIVE":
            continue
        candidates.append(quote)
    if not candidates:
        raise api_error("ERR_NO_ELIGIBLE_QUOTE")

    min_premium = min(q["premium_cents"] for q in candidates)
    scored = []
    for quote in candidates:
        insurer = db.insurers[quote["insurer_id"]]
        rating_points = _rating_points(quote["rating_at_submission"])
        score = calc.composite_score(
            rating_points,
            insurer["capital_ratio_bp"],
            min_premium,
            quote["premium_cents"],
            basis,
        )
        quote["composite_score_bp"] = score
        scored.append((quote, score, rating_points))

    scored.sort(
        key=lambda item: (
            -item[1],
            item[0]["premium_cents"],
            -item[2],
            item[0]["submitted_at"],
            item[0]["created_at"],
            item[0]["_seq"],
        )
    )
    winner, winning_score, _points = scored[0]

    for quote in quotes:
        if quote["id"] == winner["id"]:
            quote["quote_status"] = "SHORTLISTED"
            touch(quote)
        elif quote["quote_status"] == "SUBMITTED":
            quote["quote_status"] = "DECLINED"
            touch(quote)

    tranche["tranche_status"] = "INSURER_SELECTED"
    tranche["selection_basis"] = basis
    tranche["selected_quote_id"] = winner["id"]
    tranche["selected_insurer_id"] = winner["insurer_id"]
    tranche["selection_score_bp"] = winning_score
    touch(tranche)
    return object_response(public(tranche))


@bp.post("/prt/tranches/<tranche_id>/pricing-lock")
def pricing_lock(tranche_id):
    authenticate(["PlanFiduciary"])
    tranche = lookup("tranches", tranche_id)
    body()
    if tranche["tranche_status"] != "INSURER_SELECTED":
        raise api_error("ERR_TRANCHE_NOT_SELECTED")
    quote = db.quotes.get(tranche["selected_quote_id"])
    insurer = db.insurers.get(tranche["selected_insurer_id"])
    if quote is None or insurer is None:
        raise api_error("ERR_TRANCHE_NOT_SELECTED")

    if not _meets_floor(insurer["rating_grade"]):
        raise api_error("ERR_INSURER_RATING_BELOW_FLOOR")
    clock = now()
    if quote["expires_at"] is None or quote["expires_at"] <= clock:
        raise api_error("ERR_QUOTE_EXPIRED")

    candidate_start = clock
    candidate_end = clock + days(quote["lock_days"])
    committed = dom.committed_capacity(
        insurer["id"],
        exclude_tranche_id=tranche["id"],
        window_start=candidate_start,
        window_end=candidate_end,
    )
    available = insurer["capacity_cents"] - committed
    if quote["premium_cents"] > available:
        raise api_error("ERR_INSURER_CAPACITY_EXCEEDED")

    tranche["tranche_status"] = "PRICING_LOCKED"
    tranche["locked_premium_cents"] = quote["premium_cents"]
    tranche["lock_start_at"] = candidate_start
    tranche["lock_expires_at"] = candidate_end
    touch(tranche)
    quote["quote_status"] = "LOCKED"
    touch(quote)
    dom.recompute_insurer_capacity(
        insurer, window_start=candidate_start, window_end=candidate_end
    )
    return object_response(public(tranche))


# --------------------------------------------------------------------------
# asset transfers
# --------------------------------------------------------------------------


@bp.post("/prt/tranches/<tranche_id>/asset-transfers")
def initiate_transfer(tranche_id):
    authenticate(["PlanSponsor"])
    tranche = lookup("tranches", tranche_id)
    payload = body()
    expected = get_int(payload, "expected_tranche_version")
    mode = get_enum(payload, "transfer_mode", ("IN_KIND", "CASH"))
    gross = get_int(payload, "gross_value_cents")
    lot_count = get_int(payload, "security_lot_count", required=(mode == "IN_KIND"))
    if gross < 1:
        raise api_error("ERR_INVALID_REQUEST", "gross_value_cents must be at least 1.")
    if mode == "IN_KIND" and (lot_count < 1 or lot_count > 500):
        raise api_error("ERR_INVALID_REQUEST", "security_lot_count must be between 1 and 500.")
    if expected != tranche["version"]:
        raise api_error("ERR_STALE_TRANCHE_VERSION")
    if tranche["tranche_status"] != "PRICING_LOCKED":
        raise api_error("ERR_TRANCHE_STATE_INVALID")

    effective_lots = lot_count if mode == "IN_KIND" else 0
    expense = calc.transfer_expense(mode, gross, effective_lots)
    credited = gross - expense
    shortfall = tranche["locked_premium_cents"] - credited
    if shortfall > 0:
        raise api_error("ERR_TRANSFER_VALUE_SHORTFALL")

    for existing in dom.tranche_transfers(tranche["id"]):
        if existing["transfer_status"] == "INITIATED":
            existing["transfer_status"] = "SUPERSEDED"
            touch(existing)

    transfer = make_entity()
    transfer["tranche_id"] = tranche["id"]
    transfer["transfer_mode"] = mode
    transfer["in_kind_market_value_cents"] = gross if mode == "IN_KIND" else None
    transfer["in_kind_lot_count"] = effective_lots
    transfer["cash_amount_cents"] = gross if mode == "CASH" else None
    transfer["gross_value_cents"] = gross
    transfer["credited_value_cents"] = credited
    transfer["transfer_expense_cents"] = expense
    transfer["shortfall_cents"] = 0
    transfer["transfer_status"] = "INITIATED"
    transfer["insurer_decision"] = None
    transfer["rejection_reason"] = None
    transfer["settled_at"] = None
    db.transfers[transfer["id"]] = transfer
    touch(tranche)
    return object_response(public(transfer), 201)


@bp.get("/prt/tranches/<tranche_id>/asset-transfers")
def list_transfers(tranche_id):
    authenticate(TRANSFER_READ_ROLES)
    tranche = lookup("tranches", tranche_id)
    transfer_status = request.args.get("transfer_status")
    limit, offset = pagination()
    records = dom.tranche_transfers(tranche["id"])
    if transfer_status is not None:
        records = [t for t in records if t["transfer_status"] == transfer_status]
    page, total = slice_page(records, limit, offset)
    return list_response([public(t) for t in page], limit, offset, total)


@bp.post("/prt/asset-transfers/<transfer_id>/insurer-review")
def review_transfer(transfer_id):
    user_id, _role = authenticate(["InsurerRep"])
    transfer = lookup("transfers", transfer_id)
    tranche = db.tranches.get(transfer["tranche_id"])
    if tranche is None or user_id != tranche.get("selected_insurer_id"):
        raise api_error("ERR_IDENTITY_MISMATCH")
    payload = body()
    decision = get_enum(payload, "insurer_decision", ("ACCEPT", "REJECT"))
    rejection_reason = None
    if decision == "REJECT":
        rejection_reason = get_string(payload, "rejection_reason")

    if transfer["transfer_status"] != "INITIATED":
        if transfer["transfer_status"] == "SUPERSEDED":
            raise api_error("ERR_TRANSFER_STATE_INVALID")
        raise api_error("ERR_TRANSFER_NOT_INITIATED")

    if decision == "REJECT":
        transfer["transfer_status"] = "REJECTED"
        transfer["insurer_decision"] = decision
        transfer["rejection_reason"] = rejection_reason
        touch(transfer)
        return object_response(public(transfer))

    clock = now()
    if tranche["lock_expires_at"] is None or clock > tranche["lock_expires_at"]:
        raise api_error("ERR_QUOTE_EXPIRED")

    transfer["transfer_status"] = "SETTLED"
    transfer["insurer_decision"] = decision
    transfer["settled_at"] = clock
    touch(transfer)
    tranche["tranche_status"] = "ASSETS_TRANSFERRED"
    tranche["transfer_expense_cents"] = transfer["transfer_expense_cents"]
    touch(tranche)
    return object_response(public(transfer))


# --------------------------------------------------------------------------
# buyout settlement
# --------------------------------------------------------------------------


@bp.post("/prt/tranches/<tranche_id>/settlement")
def settle_tranche(tranche_id):
    authenticate(["PlanSponsor"])
    tranche = lookup("tranches", tranche_id)
    body()
    if tranche["tranche_status"] != "ASSETS_TRANSFERRED":
        raise api_error("ERR_TRANCHE_NOT_TRANSFERRED")

    plan = db.plans[tranche["plan_id"]]
    settled = [
        t for t in dom.tranche_transfers(tranche["id"]) if t["transfer_status"] == "SETTLED"
    ]
    delivery = settled[-1] if settled else None
    transfer_expense = delivery["transfer_expense_cents"] if delivery else 0
    gross_delivered = delivery["gross_value_cents"] if delivery else 0

    assigned = dom.tranche_assigned_participants(tranche)
    pbo_settled = sum(p["accounting_liability_cents"] or 0 for p in assigned)
    result = calc.settlement_recognition(
        tranche["locked_premium_cents"] or 0,
        transfer_expense,
        pbo_settled,
        plan["service_cost_cents"],
        plan["interest_cost_cents"],
        plan["unrecognized_actuarial_loss_cents"],
        plan["total_liability_cents"],
    )

    dom.append_settlement_entry(
        plan,
        "BUYOUT_RECOGNITION",
        result["recognized_cents"],
        result["deferred_cents"],
        result["gain_loss_cents"],
        pbo_settled,
        "BuyoutTranche ASSETS_TRANSFERRED -> SETTLED",
        tranche_id=tranche["id"],
    )

    for participant in assigned:
        participant["participant_status"] = "TRANSFERRED_TO_INSURER"
        touch(participant)

    plan["total_liability_cents"] = plan["total_liability_cents"] - pbo_settled
    plan["plan_assets_cents"] = plan["plan_assets_cents"] - gross_delivered
    dom.recompute_plan_participant_liability(plan)
    dom.recompute_plan_accounting_funded_status(plan)

    quote = db.quotes.get(tranche["selected_quote_id"])
    if quote is not None and quote["quote_status"] == "LOCKED":
        quote["quote_status"] = "BOUND"
        touch(quote)

    tranche["tranche_status"] = "SETTLED"
    tranche["settlement_gain_loss_cents"] = result["gain_loss_cents"]
    tranche["settled_at"] = now()
    touch(tranche)

    dom.maybe_transition_to_residual(plan)
    return object_response(public(tranche))
