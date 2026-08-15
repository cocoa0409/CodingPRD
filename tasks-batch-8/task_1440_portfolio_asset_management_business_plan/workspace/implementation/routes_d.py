"""Routes: loans, covenants, covenant tests, valuations, performance scorecards,
reforecasts, disposition decisions, lender reports, and their list endpoints."""
from datetime import date, timedelta
from flask import Blueprint

from core import (
    store, ALL_ROLES, COVENANT_TYPES, TEST_FREQS, VALUATION_METHODS, TRIGGER_TYPES,
    NON_CAPITAL_CATS, ApiError,
    auth_user, require_role, body, req_str, req_int, req_pos_int, req_nonneg_int,
    req_enum, req_date, req_period,
    get_or_404, new_record, touch,
    success_object, list_response,
    bad_request, forbidden, conflict, unprocessable, stale,
    clock_now, clock_date, now_iso,
    loans_of_asset, covenants_of_loan, tests_of_covenant, reforecasts_of_plan,
    lines_of_plan, reports_of_loan, scorecards_of_asset,
    annualized_noi, annual_debt_service, latest_confirmed_valuation, active_loan,
    months_between, fiscal_month, quarter_end_for, parse_period, prev_quarter,
    waive_loan_covenants, maybe_cure_loan, rhu_div, tick, parse_iso8601,
    ser_loan, ser_covenant, ser_covenant_test, ser_valuation, ser_scorecard,
    ser_reforecast, ser_decision, ser_lender_report,
)

bp = Blueprint("routes_d", __name__)


# ---------------------------------------------------------------------------
# Loans
# ---------------------------------------------------------------------------

@bp.route("/api/loans", methods=["POST"])
def d_create_loan():
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    b = body()
    aid = req_str(b, "asset_id")
    get_or_404(store.assets, aid, "asset")
    lender = req_str(b, "lender_name")
    principal = req_pos_int(b, "principal_balance_cents")
    rate = req_pos_int(b, "annual_interest_rate_bps")
    orig = req_date(b, "origination_date")
    mat = req_date(b, "maturity_date")
    if mat <= orig:
        raise bad_request("maturity_date must be strictly after origination_date")
    if any(l["status"] in ("CURRENT", "WATCH", "DEFAULT") for l in loans_of_asset(aid)):
        raise conflict("ERR_LOAN_EXISTS",
                       "The asset already has a loan in CURRENT, WATCH, or DEFAULT")
    rec = new_record()
    rec.update({"asset_id": aid, "lender_name": lender,
                "principal_balance_cents": principal, "annual_interest_rate_bps": rate,
                "origination_date": orig.isoformat(), "maturity_date": mat.isoformat(),
                "status": "CURRENT"})
    store.loans[rec["id"]] = rec
    return success_object(ser_loan(rec), 201)


@bp.route("/api/loans/<string:rid>", methods=["GET"])
def d_get_loan(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_loan(get_or_404(store.loans, rid, "loan")))


@bp.route("/api/loans/<string:rid>/covenants", methods=["GET"])
def d_loan_covenants(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    loan = get_or_404(store.loans, rid, "loan")
    return list_response(covenants_of_loan(loan["id"]), ser_covenant)


@bp.route("/api/loans/<string:rid>/lender-reports", methods=["GET"])
def d_loan_reports(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    loan = get_or_404(store.loans, rid, "loan")
    return list_response(reports_of_loan(loan["id"]), ser_lender_report)


# ---------------------------------------------------------------------------
# Covenants and covenant tests
# ---------------------------------------------------------------------------

@bp.route("/api/covenants", methods=["POST"])
def d_create_covenant():
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    b = body()
    lid = req_str(b, "loan_id")
    get_or_404(store.loans, lid, "loan")
    ctype = req_enum(b, "covenant_type", COVENANT_TYPES)
    threshold = req_pos_int(b, "threshold_bps")
    freq = req_enum(b, "test_frequency", TEST_FREQS)
    cure = b.get("cure_period_days", 30)
    if not isinstance(cure, int) or isinstance(cure, bool) or cure <= 0:
        raise bad_request("cure_period_days must be a positive integer")
    rec = new_record()
    rec.update({"loan_id": lid, "covenant_type": ctype, "threshold_bps": threshold,
                "test_frequency": freq, "cure_period_days": cure,
                "status": "ACTIVE", "last_breach_at": None})
    store.covenants[rec["id"]] = rec
    return success_object(ser_covenant(rec), 201)


@bp.route("/api/covenants/<string:rid>", methods=["GET"])
def d_get_covenant(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    return success_object(ser_covenant(get_or_404(store.covenants, rid, "covenant")))


@bp.route("/api/covenants/<string:rid>/waive", methods=["POST"])
def d_waive_covenant(rid):
    _, role = auth_user()
    require_role(role, ["Lender"])
    cov = get_or_404(store.covenants, rid, "covenant")
    if cov["status"] != "IN_BREACH":
        raise conflict("ERR_COVENANT_NOT_WAIVABLE", "Only an IN_BREACH covenant may be waived")
    cov["status"] = "WAIVED"
    cov["last_breach_at"] = None
    touch(cov)
    loan = store.loans.get(cov["loan_id"])
    if loan is not None:
        maybe_cure_loan(loan)
    return success_object(ser_covenant(cov))


@bp.route("/api/covenants/<string:rid>/covenant-tests", methods=["GET"])
def d_covenant_tests(rid):
    _, role = auth_user()
    require_role(role, ALL_ROLES)
    cov = get_or_404(store.covenants, rid, "covenant")
    return list_response(tests_of_covenant(cov["id"]), ser_covenant_test)


@bp.route("/api/covenant-tests", methods=["POST"])
def d_create_covenant_test():
    _, role = auth_user()
    require_role(role, ["Analyst"])
    b = body()
    cid = req_str(b, "covenant_id")
    cov = get_or_404(store.covenants, cid, "covenant")
    loan = store.loans.get(cov["loan_id"])
    if cov["status"] == "WAIVED" or loan is None or \
            loan["status"] in ("DEFAULT", "REFINANCED", "PAID_OFF"):
        raise conflict("ERR_COVENANT_NOT_TESTABLE",
                       "The covenant is WAIVED or its loan is in a terminal state")
    period = req_period(b, "period_label")
    if any(t["period_label"] == period for t in tests_of_covenant(cid)):
        raise conflict("ERR_DUPLICATE_COVENANT_TEST",
                       "A test already exists for (covenant_id, period_label)")
    asset = store.assets.get(loan["asset_id"])
    noi_used = None
    if cov["covenant_type"] in ("MIN_DSCR", "MIN_DEBT_YIELD"):
        noi = annualized_noi(asset)
        if noi is None:
            raise conflict("ERR_NO_NOI_EVIDENCE",
                           "No accepted actuals exist to compute annualized NOI")
        noi_used = noi
        if cov["covenant_type"] == "MIN_DSCR":
            measured = rhu_div(noi * 10000, annual_debt_service(loan))
        else:
            measured = rhu_div(noi * 10000, loan["principal_balance_cents"])
        result = "PASS" if measured >= cov["threshold_bps"] else "FAIL"
    else:  # MAX_LTV
        v = latest_confirmed_valuation(asset["id"])
        if v is None:
            raise conflict("ERR_STALE_VALUATION", "No CONFIRMED valuation exists for the asset")
        eff = date.fromisoformat(v["effective_date"])
        if (clock_date() - eff).days > 270:
            raise conflict("ERR_STALE_VALUATION",
                           "The latest CONFIRMED valuation is more than 270 days old")
        measured = rhu_div(loan["principal_balance_cents"] * 10000, v["implied_value_cents"])
        result = "PASS" if measured <= cov["threshold_bps"] else "FAIL"
    import uuid as _uuid
    rec = {"id": str(_uuid.uuid4()), "created_at": now_iso(), "_seq": next(store.seq),
           "covenant_id": cid, "period_label": period,
           "measured_value_bps": measured, "annualized_noi_cents_used": noi_used,
           "result": result}
    store.covenant_tests[rec["id"]] = rec
    if result == "FAIL":
        if cov["status"] == "ACTIVE":
            cov["status"] = "IN_BREACH"
            cov["last_breach_at"] = now_iso()
            touch(cov)
            if loan["status"] == "CURRENT":
                loan["status"] = "WATCH"
                touch(loan)
        elif cov["status"] == "IN_BREACH":
            breach_at = parse_iso8601(cov["last_breach_at"])
            if breach_at is not None and \
                    clock_now() > breach_at + timedelta(days=cov["cure_period_days"]) and \
                    loan["status"] == "WATCH":
                loan["status"] = "DEFAULT"
                touch(loan)
    else:  # PASS cures an active breach episode
        if cov["status"] == "IN_BREACH":
            cov["status"] = "ACTIVE"
            cov["last_breach_at"] = None
            touch(cov)
            maybe_cure_loan(loan)
    return success_object(ser_covenant_test(rec), 201)


# ---------------------------------------------------------------------------
# Valuations
# ---------------------------------------------------------------------------

@bp.route("/api/valuations", methods=["POST"])
def d_create_valuation():
    _, role = auth_user()
    require_role(role, ["Analyst"])
    b = body()
    aid = req_str(b, "asset_id")
    asset = get_or_404(store.assets, aid, "asset")
    method = req_enum(b, "method", VALUATION_METHODS)
    eff = req_date(b, "effective_date")
    if method == "EXTERNAL_APPRAISAL":
        if b.get("cap_rate_bps") is not None:
            raise bad_request("cap_rate_bps is forbidden when method is EXTERNAL_APPRAISAL")
        appraised = req_pos_int(b, "appraised_value_cents")
        cap = None
    else:
        if b.get("appraised_value_cents") is not None:
            raise bad_request("appraised_value_cents is forbidden when method is INTERNAL_CAP")
        cap = req_pos_int(b, "cap_rate_bps")
        appraised = None
    if eff > clock_date():
        raise unprocessable("ERR_FUTURE_PERIOD",
                            "effective_date must not be after the current clock date")
    if method == "INTERNAL_CAP":
        noi = annualized_noi(asset)
        if noi is None:
            raise conflict("ERR_VALUATION_NO_NOI_EVIDENCE",
                           "INTERNAL_CAP requires trailing-actuals annualized NOI evidence")
        noi_used = noi
        implied = rhu_div(noi * 10000, cap)
    else:
        noi_used = None
        implied = appraised
    rec = new_record()
    rec.update({"asset_id": aid, "effective_date": eff.isoformat(), "method": method,
                "appraised_value_cents": appraised, "cap_rate_bps": cap,
                "noi_used_cents": noi_used, "implied_value_cents": implied,
                "status": "DRAFT"})
    store.valuations[rec["id"]] = rec
    return success_object(ser_valuation(rec), 201)


@bp.route("/api/valuations/<string:rid>/confirm", methods=["POST"])
def d_confirm_valuation(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    v = get_or_404(store.valuations, rid, "valuation")
    b = body()
    expected = req_int(b, "expected_asset_version")
    asset = store.assets.get(v["asset_id"])
    if asset is None:
        raise unprocessable("ERR_REFERENTIAL_INTEGRITY", "valuation asset does not exist")
    if expected != asset["version"]:
        raise stale("ERR_STALE_ASSET_VERSION",
                    "expected_asset_version does not match the asset's current version")
    if v["status"] != "DRAFT":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT valuation may be confirmed")
    cur = latest_confirmed_valuation(asset["id"])
    if cur is not None and not (date.fromisoformat(v["effective_date"])
                                > date.fromisoformat(cur["effective_date"])):
        raise conflict("ERR_VALUATION_REGRESSIVE",
                       "effective_date must be strictly after the current CONFIRMED valuation's")
    if cur is not None:
        cur["status"] = "SUPERSEDED"
        touch(cur)
    v["status"] = "CONFIRMED"
    touch(v)
    asset["current_value_cents"] = v["implied_value_cents"]
    touch(asset)
    return success_object(ser_valuation(v))


# ---------------------------------------------------------------------------
# Performance scorecards
# ---------------------------------------------------------------------------

@bp.route("/api/performance-scorecards", methods=["POST"])
def d_create_scorecard():
    uid, role = auth_user()
    require_role(role, ["PropertyManager"])
    b = body()
    aid = req_str(b, "asset_id")
    asset = get_or_404(store.assets, aid, "asset")
    if asset["property_manager_id"] != uid:
        raise forbidden("A property manager may only submit scorecards for assets it manages")
    period = req_period(b, "period_label")
    occ = req_int(b, "occupancy_pct")
    coll = req_int(b, "collections_pct")
    ren = req_int(b, "renewal_rate_pct")
    for name, val in (("occupancy_pct", occ), ("collections_pct", coll),
                      ("renewal_rate_pct", ren)):
        if val < 0 or val > 100:
            raise bad_request(f"{name} must be in 0..100")
    exp_bps = req_int(b, "expense_variance_bps")
    if any(s["period_label"] == period for s in scorecards_of_asset(aid)):
        raise conflict("ERR_DUPLICATE_SCORECARD",
                       "A scorecard already exists for (asset_id, period_label)")
    exp_score = max(0, 100 - abs(exp_bps) // 50)
    comp = rhu_div(30 * occ + 30 * coll + 25 * exp_score + 15 * ren, 100)
    if comp >= 85:
        rating = "EXCELLENT"
    elif comp >= 70:
        rating = "SATISFACTORY"
    elif comp >= 55:
        rating = "WATCH"
    else:
        rating = "PROBATION"
    rec = new_record()
    rec.update({"asset_id": aid, "property_manager_id": asset["property_manager_id"],
                "period_label": period, "occupancy_pct": occ, "collections_pct": coll,
                "renewal_rate_pct": ren, "expense_variance_bps": exp_bps,
                "composite_score": comp, "rating": rating, "status": "SUBMITTED"})
    store.scorecards[rec["id"]] = rec
    return success_object(ser_scorecard(rec), 201)


@bp.route("/api/performance-scorecards/<string:rid>/review", methods=["POST"])
def d_review_scorecard(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    sc = get_or_404(store.scorecards, rid, "performance scorecard")
    if sc["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED scorecard may be reviewed")
    sc["status"] = "REVIEWED"
    touch(sc)
    return success_object(ser_scorecard(sc))


@bp.route("/api/performance-scorecards/<string:rid>/finalize", methods=["POST"])
def d_finalize_scorecard(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    sc = get_or_404(store.scorecards, rid, "performance scorecard")
    if sc["status"] != "REVIEWED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a REVIEWED scorecard may be finalized")
    sc["status"] = "FINALIZED"
    sc["_finalized_tick"] = tick()
    touch(sc)
    m = store.managers.get(sc["property_manager_id"])
    if m is not None:
        before = (m["probation_streak"], m["status"])
        if sc["rating"] == "PROBATION":
            m["probation_streak"] += 1
        else:
            m["probation_streak"] = 0
        if m["probation_streak"] >= 2 and m["status"] == "ACTIVE":
            m["status"] = "SUSPENDED"
        if (m["probation_streak"], m["status"]) != before:
            touch(m)
    return success_object(ser_scorecard(sc))


# ---------------------------------------------------------------------------
# Reforecasts
# ---------------------------------------------------------------------------

@bp.route("/api/reforecasts", methods=["POST"])
def d_create_reforecast():
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    pid = req_str(b, "plan_id")
    plan = get_or_404(store.plans, pid, "business plan")
    if plan["status"] != "APPROVED":
        raise conflict("ERR_PLAN_NOT_APPROVED", "Reforecasts require an APPROVED plan")
    raw = b.get("lines")
    if not isinstance(raw, list) or len(raw) == 0:
        raise bad_request("lines must be a non-empty array")
    entries = []
    seen = set()
    for e in raw:
        if not isinstance(e, dict):
            raise bad_request("each entry of lines must be an object")
        cat = req_str(e, "category")
        if cat == "CAPITAL":
            raise unprocessable("ERR_REFORECAST_CATEGORIES_INCOMPLETE",
                                "CAPITAL is forbidden in a reforecast")
        if cat not in NON_CAPITAL_CATS:
            raise bad_request(f"category must be one of {NON_CAPITAL_CATS}")
        amt = req_nonneg_int(e, "revised_annual_amount_cents")
        if cat in seen:
            raise unprocessable("ERR_REFORECAST_CATEGORIES_INCOMPLETE",
                                "Each of the 9 non-CAPITAL categories must appear exactly once")
        seen.add(cat)
        entries.append({"category": cat, "revised_annual_amount_cents": amt})
    if seen != set(NON_CAPITAL_CATS):
        raise unprocessable("ERR_REFORECAST_CATEGORIES_INCOMPLETE",
                            "lines must cover each of the 9 non-CAPITAL categories exactly once")
    fm = fiscal_month(plan)
    if fm not in (4, 7, 10):
        raise unprocessable("ERR_REFORECAST_CADENCE",
                            "Reforecast creation requires the plan's current fiscal month "
                            "to be 4, 7, or 10")
    if plan["reforecast_count"] >= 3:
        raise conflict("ERR_REFORECAST_LIMIT", "The plan already has 3 APPLIED reforecasts")
    label = f"R{len(reforecasts_of_plan(pid)) + 1}"
    rec = new_record()
    rec.update({"plan_id": pid, "label": label, "effective_from_month": fm,
                "lines": entries, "status": "DRAFT"})
    store.reforecasts[rec["id"]] = rec
    return success_object(ser_reforecast(rec), 201)


@bp.route("/api/reforecasts/<string:rid>/submit", methods=["POST"])
def d_submit_reforecast(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    rf = get_or_404(store.reforecasts, rid, "reforecast")
    if rf["status"] != "DRAFT":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT reforecast may be submitted")
    rf["status"] = "SUBMITTED"
    touch(rf)
    return success_object(ser_reforecast(rf))


@bp.route("/api/reforecasts/<string:rid>/accept", methods=["POST"])
def d_accept_reforecast(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    rf = get_or_404(store.reforecasts, rid, "reforecast")
    b = body()
    expected = req_int(b, "expected_plan_version")
    plan = store.plans.get(rf["plan_id"])
    if plan is None:
        raise unprocessable("ERR_REFERENTIAL_INTEGRITY", "reforecast plan does not exist")
    if expected != plan["version"]:
        raise stale("ERR_STALE_PLAN_VERSION",
                    "expected_plan_version does not match the plan's current version")
    if rf["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED reforecast may be accepted")
    if plan["status"] != "APPROVED":
        raise conflict("ERR_PLAN_NOT_APPROVED", "The plan must be APPROVED")
    efm = rf["effective_from_month"]
    existing = {(l["category"], l["month_index"]): l for l in lines_of_plan(plan["id"])}
    spread = []
    for e in rf["lines"]:
        cat = e["category"]
        revised = e["revised_annual_amount_cents"]
        ytd = 0
        elapsed = 0
        for m in range(1, efm):
            l = existing.get((cat, m))
            if l is not None:
                if l["has_actual"]:
                    ytd += l["actual_amount_cents"]
                else:
                    elapsed += l["budget_amount_cents"]
        remaining = revised - ytd - elapsed
        if remaining < 0:
            raise conflict("ERR_REFORECAST_BELOW_ACTUALS",
                           f"revised_annual_amount_cents for {cat} is below posted actuals "
                           "plus elapsed budget")
        n = 12 - efm + 1
        per = remaining // n
        spread.append((cat, per, remaining - per * (n - 1)))
    for cat, per, last in spread:
        for m in range(efm, 13):
            value = last if m == 12 else per
            l = existing.get((cat, m))
            if l is None:
                rec = new_record()
                rec.update({"plan_id": plan["id"], "category": cat, "month_index": m,
                            "budget_amount_cents": value, "actual_amount_cents": 0,
                            "has_actual": False})
                store.budget_lines[rec["id"]] = rec
            else:
                l["budget_amount_cents"] = value
                touch(l)
    rf["status"] = "APPLIED"
    touch(rf)
    plan["reforecast_count"] += 1
    touch(plan)
    return success_object(ser_reforecast(rf))


@bp.route("/api/reforecasts/<string:rid>/reject", methods=["POST"])
def d_reject_reforecast(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    rf = get_or_404(store.reforecasts, rid, "reforecast")
    if rf["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a SUBMITTED reforecast may be rejected")
    rf["status"] = "REJECTED"
    touch(rf)
    return success_object(ser_reforecast(rf))


# ---------------------------------------------------------------------------
# Disposition decisions
# ---------------------------------------------------------------------------

@bp.route("/api/disposition-decisions", methods=["POST"])
def d_create_decision():
    uid, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    aid = req_str(b, "asset_id")
    asset = get_or_404(store.assets, aid, "asset")
    ttype = req_enum(b, "trigger_type", TRIGGER_TYPES)
    loan = active_loan(aid)
    dscr = None
    if loan is not None:
        dscr_tests = []
        for t in store.covenant_tests.values():
            cov = store.covenants.get(t["covenant_id"])
            if cov is not None and cov["loan_id"] == loan["id"] \
                    and cov["covenant_type"] == "MIN_DSCR":
                dscr_tests.append(t)
        if dscr_tests:
            dscr_tests.sort(key=lambda t: t["_seq"])
            dscr = dscr_tests[-1]["measured_value_bps"]
    ltv = None
    if loan is not None and asset["current_value_cents"] is not None:
        ltv = rhu_div(loan["principal_balance_cents"] * 10000, asset["current_value_cents"])
    hold_years = months_between(date.fromisoformat(asset["acquisition_date"]),
                                clock_date()) // 12
    gain = None
    if asset["current_value_cents"] is not None:
        gain = rhu_div((asset["current_value_cents"] - asset["acquisition_price_cents"])
                       * 10000, asset["acquisition_price_cents"])
    refi = False
    if loan is not None:
        mtm = months_between(clock_date(), date.fromisoformat(loan["maturity_date"]))
        refi = (dscr is not None and dscr >= 14000
                and ltv is not None and ltv <= 6000
                and mtm <= 18)
    sell = (hold_years >= asset["hold_period_years"]) or (gain is not None and gain >= 2500)
    if ttype == "SELL" and not sell:
        raise conflict("ERR_DECISION_TRIGGER_NOT_ARMED", "sell_signal is false")
    if ttype == "REFINANCE" and not refi:
        raise conflict("ERR_DECISION_TRIGGER_NOT_ARMED", "refinance_signal is false")
    rec = new_record()
    rec.update({"asset_id": aid, "trigger_type": ttype, "dscr_bps_snapshot": dscr,
                "ltv_bps_snapshot": ltv, "hold_years_elapsed": hold_years,
                "value_gain_bps": gain, "refinance_signal": refi, "sell_signal": sell,
                "created_by_user_id": uid, "status": "SCREENING"})
    store.decisions[rec["id"]] = rec
    return success_object(ser_decision(rec), 201)


@bp.route("/api/disposition-decisions/<string:rid>/submit-review", methods=["POST"])
def d_submit_review(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    d = get_or_404(store.decisions, rid, "disposition decision")
    if d["status"] != "SCREENING":
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Only a SCREENING decision may move to committee review")
    d["status"] = "COMMITTEE_REVIEW"
    touch(d)
    return success_object(ser_decision(d))


@bp.route("/api/disposition-decisions/<string:rid>/ratify", methods=["POST"])
def d_ratify_decision(rid):
    uid, role = auth_user()
    require_role(role, ["InvestmentCommittee"])
    d = get_or_404(store.decisions, rid, "disposition decision")
    if d["status"] != "COMMITTEE_REVIEW":
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Only a COMMITTEE_REVIEW decision may be ratified")
    if uid == d["created_by_user_id"]:
        raise ApiError("ERR_SELF_APPROVAL_FORBIDDEN", 403,
                       "The ratifier must differ from the decision's creator")
    d["status"] = "RATIFIED"
    touch(d)
    return success_object(ser_decision(d))


@bp.route("/api/disposition-decisions/<string:rid>/shelve", methods=["POST"])
def d_shelve_decision(rid):
    _, role = auth_user()
    require_role(role, ["InvestmentCommittee"])
    d = get_or_404(store.decisions, rid, "disposition decision")
    if d["status"] not in ("COMMITTEE_REVIEW", "RATIFIED"):
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Only a COMMITTEE_REVIEW or RATIFIED decision may be shelved")
    d["status"] = "SHELVED"
    touch(d)
    return success_object(ser_decision(d))


@bp.route("/api/disposition-decisions/<string:rid>/execute", methods=["POST"])
def d_execute_decision(rid):
    _, role = auth_user()
    require_role(role, ["PortfolioDirector"])
    d = get_or_404(store.decisions, rid, "disposition decision")
    if d["status"] != "RATIFIED":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a RATIFIED decision may be executed")
    asset = store.assets.get(d["asset_id"])
    b = body()
    if d["trigger_type"] == "SELL":
        if asset["status"] != "OWNED":
            raise conflict("ERR_ASSET_NOT_SELLABLE", "SELL execution requires the asset to be OWNED")
        asset["status"] = "LISTED_FOR_SALE"
        touch(asset)
    elif d["trigger_type"] == "REFINANCE":
        nl = b.get("new_loan")
        if not isinstance(nl, dict):
            raise bad_request("new_loan payload is required for a REFINANCE decision")
        lender = req_str(nl, "lender_name")
        principal = req_pos_int(nl, "principal_balance_cents")
        rate = req_pos_int(nl, "annual_interest_rate_bps")
        orig = req_date(nl, "origination_date")
        mat = req_date(nl, "maturity_date")
        if mat <= orig:
            raise bad_request("new_loan.maturity_date must be strictly after origination_date")
        for l in loans_of_asset(asset["id"]):
            if l["status"] in ("CURRENT", "WATCH"):
                l["status"] = "REFINANCED"
                touch(l)
                waive_loan_covenants(l)
        rec = new_record()
        rec.update({"asset_id": asset["id"], "lender_name": lender,
                    "principal_balance_cents": principal, "annual_interest_rate_bps": rate,
                    "origination_date": orig.isoformat(), "maturity_date": mat.isoformat(),
                    "status": "CURRENT"})
        store.loans[rec["id"]] = rec
    else:  # HOLD
        ext = req_int(b, "extension_years")
        if ext < 1:
            raise bad_request("extension_years must be an integer >= 1")
        asset["hold_period_years"] += ext
        touch(asset)
    d["status"] = "EXECUTED"
    touch(d)
    return success_object(ser_decision(d))


# ---------------------------------------------------------------------------
# Lender reports
# ---------------------------------------------------------------------------

@bp.route("/api/lender-reports", methods=["POST"])
def d_create_lender_report():
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    b = body()
    lid = req_str(b, "loan_id")
    loan = get_or_404(store.loans, lid, "loan")
    period = req_period(b, "period_label")
    year, q = parse_period(period)
    qend = quarter_end_for(year, q)
    if qend > clock_date():
        raise unprocessable("ERR_FUTURE_PERIOD",
                            "The labeled quarter must have ended under the logical clock")
    reps = reports_of_loan(lid)
    if any(r["period_label"] == period for r in reps):
        raise conflict("ERR_LENDER_REPORT_GAP",
                       "A report with this period_label already exists for the loan")
    if reps:
        py, pq = prev_quarter(year, q)
        prev_label = f"{py}-Q{pq}"
        if not any(r["period_label"] == prev_label
                   and r["status"] in ("SUBMITTED", "ACKNOWLEDGED") for r in reps):
            raise conflict("ERR_LENDER_REPORT_GAP",
                           "The previous calendar quarter's report must exist in "
                           "SUBMITTED or ACKNOWLEDGED")
    due = qend + timedelta(days=45)
    rec = new_record()
    rec.update({"loan_id": lid, "period_label": period,
                "quarter_end_date": qend.isoformat(), "due_date": due.isoformat(),
                "submitted_at": None, "is_late": None, "noi_ttm_cents": None,
                "dscr_bps": None, "ltv_bps": None, "status": "DRAFT"})
    store.lender_reports[rec["id"]] = rec
    return success_object(ser_lender_report(rec), 201)


@bp.route("/api/lender-reports/<string:rid>/submit", methods=["POST"])
def d_submit_lender_report(rid):
    _, role = auth_user()
    require_role(role, ["AssetManager"])
    rep = get_or_404(store.lender_reports, rid, "lender report")
    if rep["status"] != "DRAFT":
        raise conflict("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT report may be submitted")
    loan = store.loans.get(rep["loan_id"])
    if loan is None or loan["status"] not in ("CURRENT", "WATCH"):
        raise conflict("ERR_LOAN_NOT_REPORTABLE",
                       "The loan must be CURRENT or WATCH to submit a report")
    asset = store.assets.get(loan["asset_id"])
    rep["submitted_at"] = now_iso()
    rep["is_late"] = clock_date() > date.fromisoformat(rep["due_date"])
    noi = annualized_noi(asset) if asset is not None else None
    rep["noi_ttm_cents"] = noi
    rep["dscr_bps"] = rhu_div(noi * 10000, annual_debt_service(loan)) if noi is not None else None
    rep["ltv_bps"] = (rhu_div(loan["principal_balance_cents"] * 10000,
                              asset["current_value_cents"])
                      if asset is not None and asset["current_value_cents"] is not None else None)
    rep["status"] = "SUBMITTED"
    touch(rep)
    if rep["is_late"] and loan["status"] == "CURRENT":
        loan["status"] = "WATCH"
        touch(loan)
    return success_object(ser_lender_report(rep))


@bp.route("/api/lender-reports/<string:rid>/acknowledge", methods=["POST"])
def d_acknowledge_lender_report(rid):
    _, role = auth_user()
    require_role(role, ["Lender"])
    rep = get_or_404(store.lender_reports, rid, "lender report")
    if rep["status"] != "SUBMITTED":
        raise conflict("ERR_INVALID_STATE_TRANSITION",
                       "Only a SUBMITTED report may be acknowledged")
    rep["status"] = "ACKNOWLEDGED"
    touch(rep)
    return success_object(ser_lender_report(rep))
