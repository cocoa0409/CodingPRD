"""Collateral: appraiser capacity (closed intervals), dual-basis valuation,
review lifecycle, and the submit-to-committee appraisal gates (PRD sections 3.4, 3.5).
"""
from test_helpers import (
    ApiErrorId, api_client, assert_appraisal, create_appraiser, create_borrower,
    deal_appraisal_review, deal_underwritten, finalize_spreads, get_application,
    list_exceptions, loan_application_payload, order_and_accept_appraisal,
    order_appraisal, receive_report, review_appraisal, setup_officers,
    spread_and_finalize, spread_statement, finalize_statement, submit_application,
    submit_to_committee, validate_error, validate_paginated, validate_success,
    waive_all_open_exceptions, clear_exceptions, attach_statement,
)


def _window_deal():
    """Clean 20,000,000 deal in APPRAISAL_REVIEW (dscr 4.2085, no exceptions)."""
    return deal_appraisal_review(
        borrower_kw={"legal_name": "Window Watchers LLC", "naics_code": "332710",
                     "relationship_since": "2015-01-01"},
        app_kw={"requested_amount_cents": 20_000_000, "term_months": 60},
        statement_shape="WINDOW")


def test_end_touching_window_conflicts():
    """PRD section 3.4: "engagement windows are closed intervals, so a window whose
    start equals an existing window's end does overlap it; the count of the
    appraiser's engagements in `ENGAGED` or `REPORT_RECEIVED` status whose windows
    intersect the new one must be strictly less than `max_concurrent_engagements`,
    otherwise the order is refused with `ERR_APPRAISER_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/appraiser_closed_interval_adjacency_conflict
    """
    ctx = _window_deal()
    o = ctx["o"]
    appraiser = create_appraiser(o, name="SoloAppraise", license_number="LIC-900",
                                 max_concurrent_engagements=1)
    e1 = order_appraisal(o, ctx["application"]["id"], appraiser["id"],
                         engagement_start_date="2026-08-03", engagement_end_date="2026-08-07")
    assert e1["status"] == "ENGAGED"

    # Adjacent: new start == existing end (closed intervals share 2026-08-07).
    conflict = api_client.create_appraisal(
        {"loan_application_id": ctx["application"]["id"], "appraiser_id": appraiser["id"],
         "collateral_class": "EQUIPMENT", "engagement_start_date": "2026-08-07",
         "engagement_end_date": "2026-08-10"}, o["apm"]["headers"])
    validate_error(conflict, ApiErrorId.ERR_APPRAISER_WINDOW_CONFLICT)

    e1_after = validate_success(api_client.get_appraiser(appraiser["id"], o["apm"]["headers"]), 200)
    assert e1_after["status"] == "ELIGIBLE"
    rows, meta = validate_paginated(api_client.list_appraiser_appraisals(appraiser["id"], o["apm"]["headers"]))
    assert [r["id"] for r in rows] == [e1["id"]], "the rejected order persisted nothing"


def test_one_day_gap_admitted():
    """PRD section 3.4: "engagement windows are closed intervals" — so a start one
    day after the existing window's end does not intersect it — and "the count ...
    must be strictly less than `max_concurrent_engagements`".

    Design: Difficulty/resource_temporal_overlap/appraiser_closed_interval_adjacency_conflict
    """
    ctx = _window_deal()
    o = ctx["o"]
    appraiser = create_appraiser(o, name="SoloAppraise", license_number="LIC-900",
                                 max_concurrent_engagements=1)
    e1 = order_appraisal(o, ctx["application"]["id"], appraiser["id"],
                         engagement_start_date="2026-08-03", engagement_end_date="2026-08-07")

    e3 = validate_success(api_client.create_appraisal(
        {"loan_application_id": ctx["application"]["id"], "appraiser_id": appraiser["id"],
         "collateral_class": "EQUIPMENT", "engagement_start_date": "2026-08-08",
         "engagement_end_date": "2026-08-10"}, o["apm"]["headers"]), 201)
    assert e3["status"] == "ENGAGED"

    rows, meta = validate_paginated(api_client.list_appraiser_appraisals(appraiser["id"], o["apm"]["headers"]))
    assert meta["total_count"] == 2
    assert {r["id"] for r in rows} == {e1["id"], e3["id"]}


def test_committee_session_back_to_back_and_interior_overlap():
    """PRD section 3.5: "a new session conflicts with an existing `SCHEDULED` one
    exactly when the existing session starts strictly before the new session's end
    and the new session starts strictly before the existing session's end, and any
    such conflict is rejected with `ERR_COMMITTEE_SESSION_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/committee_session_half_open_back_to_back_allowed
    """
    o = setup_officers(["ch"])
    s1 = validate_success(api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T14:00:00Z",
         "ends_at": "2026-08-10T15:00:00Z"}, o["ch"]["headers"]), 201)
    assert s1["status"] == "SCHEDULED"

    # Back-to-back: 15:00 is NOT strictly before S1.ends_at 15:00 -> no overlap.
    s2 = validate_success(api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T15:00:00Z",
         "ends_at": "2026-08-10T16:00:00Z"}, o["ch"]["headers"]), 201)
    assert s2["status"] == "SCHEDULED"

    # Interior overlap: 14:00 < 15:30 and 14:30 < 15:00 -> conflict.
    conflict = api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T14:30:00Z",
         "ends_at": "2026-08-10T15:30:00Z"}, o["ch"]["headers"])
    validate_error(conflict, ApiErrorId.ERR_COMMITTEE_SESSION_CONFLICT)


def test_session_adjacent_on_early_side_allowed():
    """PRD section 3.5: "a new session conflicts with an existing `SCHEDULED` one
    exactly when the existing session starts strictly before the new session's end
    and the new session starts strictly before the existing session's end" — a
    session ending exactly at the existing session's start satisfies neither
    strict inequality.

    Design: Difficulty/resource_temporal_overlap/committee_session_half_open_back_to_back_allowed
    """
    o = setup_officers(["ch"])
    s1 = validate_success(api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T14:00:00Z",
         "ends_at": "2026-08-10T15:00:00Z"}, o["ch"]["headers"]), 201)

    s4 = validate_success(api_client.create_committee_session(
        {"level": "STANDARD", "starts_at": "2026-08-10T13:00:00Z",
         "ends_at": "2026-08-10T14:00:00Z"}, o["ch"]["headers"]), 201)
    assert s4["status"] == "SCHEDULED"

    s1_after = validate_success(api_client.get_committee_session(s1["id"], o["ch"]["headers"]), 200)
    assert s1_after["status"] == "SCHEDULED", "rejections never mutate existing sessions"


def test_appraisal_receive_report_records_concluded_values():
    """PRD section 3.4: "the manager records its conclusions — `appraised_value_cents`
    (the concluded market value) and `orderly_liquidation_value_cents` — moving the
    appraisal `ENGAGED` → `REPORT_RECEIVED`."

    Design: Corner/state_machines/appraisal_receive_report_records_concluded_values
    """
    ctx = _window_deal()
    o = ctx["o"]
    appraiser = create_appraiser(o)
    aprl = order_appraisal(o, ctx["application"]["id"], appraiser["id"])

    received = validate_success(api_client.receive_appraisal_report(
        aprl["id"], {"appraised_value_cents": 44_000_000,
                     "orderly_liquidation_value_cents": 40_000_000}, o["apm"]["headers"]), 200)
    assert received["status"] == "REPORT_RECEIVED"
    assert received["appraised_value_cents"] == 44_000_000
    assert received["orderly_liquidation_value_cents"] == 40_000_000


def test_appraisal_review_from_engaged_rejected():
    """PRD section 3.4: the manager records conclusions "moving the appraisal
    `ENGAGED` → `REPORT_RECEIVED`. The manager then reviews the report" — and
    PRD section 2.8: "The target entity is in a legal from-state for the requested
    transition; otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/appraisal_review_from_engaged_rejected
    """
    ctx = _window_deal()
    o = ctx["o"]
    appraiser = create_appraiser(o)
    aprl = order_appraisal(o, ctx["application"]["id"], appraiser["id"])

    resp = api_client.review_appraisal(aprl["id"], {"outcome": "ACCEPTED"}, o["apm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, _ = validate_paginated(api_client.list_application_appraisals(
        ctx["application"]["id"], o["apm"]["headers"]))
    assert rows[0]["status"] == "ENGAGED", "the rejected review changed nothing"


def test_appraisal_reject_frees_window_and_allows_reorder():
    """PRD section 3.4: "Rejection instead moves the appraisal to `REJECTED`, frees
    its engagement window so it no longer counts toward the appraiser's overlap
    capacity, and enables a replacement appraisal to be ordered — the reorder loop."

    Design: Corner/state_machines/appraisal_reject_frees_window_and_allows_reorder
    """
    ctx = _window_deal()
    o = ctx["o"]
    appraiser = create_appraiser(o, name="SoloAppraise", license_number="LIC-900",
                                 max_concurrent_engagements=1)
    e1 = order_appraisal(o, ctx["application"]["id"], appraiser["id"])
    receive_report(o, e1["id"], 44_000_000, 40_000_000)

    rejected = review_appraisal(o, e1["id"], "REJECTED")
    assert rejected["status"] == "REJECTED"

    e2 = order_appraisal(o, ctx["application"]["id"], appraiser["id"],
                         engagement_start_date="2026-08-03", engagement_end_date="2026-08-07")
    assert e2["status"] == "ENGAGED", "the REJECTED engagement no longer counts toward capacity"


def test_advance_rates_vary_by_collateral_class():
    """PRD section 3.4: "the lending-basis `eligible_value_cents` is the
    `appraised_value_cents` multiplied by the advance rate for its `collateral_class`
    — 0.75 for `REAL_ESTATE`, 0.80 for `EQUIPMENT`, 0.50 for `RECEIVABLES`, 0.50 for
    `INVENTORY`, and 0.70 for `AGRICULTURAL` — floored to whole cents; the
    `liquidation_basis_value_cents` is the `orderly_liquidation_value_cents`
    multiplied by a 0.85 liquidation haircut and then by the same advance rate, also
    floored to whole cents" and "Each acceptance also recomputes the application's
    collateral aggregates over its `ACCEPTED` appraisals".

    Design: Corner/calculations/advance_rates_vary_by_collateral_class
    """
    ctx = _window_deal()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    appraiser = create_appraiser(o)

    eq = order_and_accept_appraisal(o, app_id, appraiser["id"], 10_000_000, 9_000_000,
                                    collateral_class="EQUIPMENT")
    assert eq["eligible_value_cents"] == 8_000_000, "10,000,000 x 0.80"
    assert eq["liquidation_basis_value_cents"] == 6_120_000, "9,000,000 x 0.85 x 0.80 floored"

    ar = order_and_accept_appraisal(o, app_id, appraiser["id"], 12_000_000, 11_000_000,
                                    collateral_class="RECEIVABLES",
                                    engagement_start_date="2026-08-10",
                                    engagement_end_date="2026-08-14")
    assert ar["eligible_value_cents"] == 6_000_000, "12,000,000 x 0.50"
    assert ar["liquidation_basis_value_cents"] == 4_675_000, "11,000,000 x 0.85 x 0.50 floored"

    app = get_application(o, app_id)
    assert app["total_appraised_value_cents"] == 22_000_000
    assert app["total_eligible_collateral_cents"] == 14_000_000, "sum over ACCEPTED only"
    assert app["total_liquidation_collateral_cents"] == 10_795_000


def test_dual_basis_values_computed_at_acceptance():
    """PRD section 3.4: "the lending-basis `eligible_value_cents` is the
    `appraised_value_cents` multiplied by the advance rate for its `collateral_class`
    ... floored to whole cents; the `liquidation_basis_value_cents` is the
    `orderly_liquidation_value_cents` multiplied by a 0.85 liquidation haircut and
    then by the same advance rate, also floored to whole cents, and is therefore
    strictly lower than the lending basis for identical inputs."

    Design: Difficulty/dual_variant_calc/collateral_lending_vs_liquidation_basis_insider
    """
    # Reg O insider BEACON deal (stress + insider LOW exceptions, both waived).
    ctx = deal_appraisal_review(
        borrower_kw={"legal_name": "Insider Trading Post Inc", "naics_code": "441110",
                     "relationship_since": "2018-01-01", "is_reg_o_insider": True},
        app_kw={"requested_amount_cents": 30_000_000, "term_months": 60},
        statement_shape="BEACON")
    o = ctx["o"]
    appraiser = create_appraiser(o)
    aprl = order_and_accept_appraisal(o, ctx["application"]["id"], appraiser["id"],
                                      40_000_000, 34_000_000)
    assert aprl["eligible_value_cents"] == 30_000_000, "LENDING_BASIS: 40,000,000 x 0.75"
    assert aprl["liquidation_basis_value_cents"] == 21_675_000, (
        "LIQUIDATION_BASIS: 34,000,000 x 0.85 x 0.75 floored")
    assert aprl["eligible_value_cents"] - aprl["liquidation_basis_value_cents"] == 8_325_000, (
        "the two bases diverge on identical appraised inputs")


def test_reg_o_liquidation_floor_raises_high_exception():
    """PRD section 3.5: "when the borrower is a Regulation O insider, a further
    liquidation-basis test applies: if the ratio of `requested_amount_cents` to
    `total_liquidation_collateral_cents` exceeds the maximum loan-to-value ratio, a
    `COLLATERAL_COVERAGE_MIN` exception is created whose `detail` records that the
    liquidation basis failed." and "An `LTV_MAXIMUM` exception is created when the
    ratio of `requested_amount_cents` to `total_appraised_value_cents` exceeds the
    product's maximum loan-to-value ratio (an exactly-at-limit deal passes)."

    Design: Difficulty/dual_variant_calc/collateral_lending_vs_liquidation_basis_insider
    """
    ctx = deal_appraisal_review(
        borrower_kw={"legal_name": "Insider Trading Post Inc", "naics_code": "441110",
                     "relationship_since": "2018-01-01", "is_reg_o_insider": True},
        app_kw={"requested_amount_cents": 30_000_000, "term_months": 60},
        statement_shape="BEACON")
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    appraiser = create_appraiser(o)
    order_and_accept_appraisal(o, app_id, appraiser["id"], 40_000_000, 34_000_000)

    sized = submit_to_committee(o, app_id)
    assert sized["status"] == "COMMITTEE_REVIEW"
    # Sizing unconstrained: dscr cap 31,563,745; LTV cap 32,000,000; requested 30,000,000.
    assert sized["proposed_amount_cents"] == 30_000_000

    open_exc = list_exceptions(o, app_id, status="OPEN")
    assert not any(e["rule_code"] == "LTV_MAXIMUM" for e in open_exc), (
        "30,000,000 / 40,000,000 == 0.7500 <= 0.8000 on the lending basis")
    ccm = [e for e in open_exc if e["rule_code"] == "COLLATERAL_COVERAGE_MIN"]
    assert len(ccm) == 1, "exactly one liquidation-basis coverage exception"
    assert ccm[0]["severity"] == "HIGH", (
        "30,000,000 / 21,675,000 == 1.3841 > 0.8000 fails the Reg O liquidation floor")


def test_appraiser_suspension_blocks_new_orders():
    """PRD section 3.4: "The chosen appraiser must be `ELIGIBLE`, otherwise
    `ERR_APPRAISER_NOT_ELIGIBLE`." and "the manager may later update the `name` or
    move `status` between `ELIGIBLE` and `SUSPENDED`, and suspension blocks any new
    engagement orders."

    Design: Corner/validations/appraiser_suspension_blocks_new_orders
    """
    ctx = _window_deal()
    o = ctx["o"]
    appraiser = create_appraiser(o)

    suspended = validate_success(api_client.update_appraiser(
        appraiser["id"], {"status": "SUSPENDED"}, o["apm"]["headers"]), 200)
    assert suspended["status"] == "SUSPENDED"

    blocked = api_client.create_appraisal(
        {"loan_application_id": ctx["application"]["id"], "appraiser_id": appraiser["id"],
         "collateral_class": "REAL_ESTATE", "engagement_start_date": "2026-08-03",
         "engagement_end_date": "2026-08-07"}, o["apm"]["headers"])
    validate_error(blocked, ApiErrorId.ERR_APPRAISER_NOT_ELIGIBLE)

    validate_success(api_client.update_appraiser(
        appraiser["id"], {"status": "ELIGIBLE"}, o["apm"]["headers"]), 200)
    ok = validate_success(api_client.create_appraisal(
        {"loan_application_id": ctx["application"]["id"], "appraiser_id": appraiser["id"],
         "collateral_class": "REAL_ESTATE", "engagement_start_date": "2026-08-03",
         "engagement_end_date": "2026-08-07"}, o["apm"]["headers"]), 201)
    assert ok["status"] == "ENGAGED"


def test_appraiser_capacity_third_overlap_rejected():
    """PRD section 3.4: "the count of the appraiser's engagements in `ENGAGED` or
    `REPORT_RECEIVED` status whose windows intersect the new one must be strictly
    less than `max_concurrent_engagements`, otherwise the order is refused with
    `ERR_APPRAISER_WINDOW_CONFLICT`."

    Design: Corner/validations/appraiser_capacity_third_overlap_rejected
    """
    ctx = _window_deal()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    appraiser = create_appraiser(o, name="DuoAppraise", license_number="LIC-200",
                                 max_concurrent_engagements=2)

    e1 = order_appraisal(o, app_id, appraiser["id"],
                         engagement_start_date="2026-08-03", engagement_end_date="2026-08-10")
    e2 = order_appraisal(o, app_id, appraiser["id"], collateral_class="EQUIPMENT",
                         engagement_start_date="2026-08-05", engagement_end_date="2026-08-12")
    assert e1["status"] == "ENGAGED" and e2["status"] == "ENGAGED"

    third = api_client.create_appraisal(
        {"loan_application_id": app_id, "appraiser_id": appraiser["id"],
         "collateral_class": "RECEIVABLES", "engagement_start_date": "2026-08-06",
         "engagement_end_date": "2026-08-08"}, o["apm"]["headers"])
    validate_error(third, ApiErrorId.ERR_APPRAISER_WINDOW_CONFLICT)

    rows, meta = validate_paginated(api_client.list_appraiser_appraisals(appraiser["id"], o["apm"]["headers"]))
    assert meta["total_count"] == 2


def test_submit_to_committee_appraisal_gates():
    """PRD section 3.5: "at least one appraisal must stand `ACCEPTED` (otherwise
    `ERR_NO_ACCEPTED_APPRAISAL`); no appraisal may remain `ENGAGED` or
    `REPORT_RECEIVED` (otherwise `ERR_APPRAISALS_NOT_SETTLED`)".

    Design: Corner/validations/submit_to_committee_appraisal_gates
    """
    ctx = _window_deal()
    o = ctx["o"]
    app_id = ctx["application"]["id"]
    appraiser = create_appraiser(o)

    none = api_client.submit_to_committee(app_id, o["an"]["headers"])
    validate_error(none, ApiErrorId.ERR_NO_ACCEPTED_APPRAISAL)

    a1 = order_and_accept_appraisal(o, app_id, appraiser["id"], 44_000_000, 40_000_000)
    a2 = order_appraisal(o, app_id, appraiser["id"], collateral_class="EQUIPMENT",
                         engagement_start_date="2026-08-10", engagement_end_date="2026-08-12")

    unsettled = api_client.submit_to_committee(app_id, o["an"]["headers"])
    validate_error(unsettled, ApiErrorId.ERR_APPRAISALS_NOT_SETTLED)

    app = get_application(o, app_id)
    assert app["status"] == "APPRAISAL_REVIEW", "both rejections left the stage unchanged"


def test_appraisal_order_requires_review_stage():
    """PRD section 3.4: "The parent application must be in `APPRAISAL_REVIEW`,
    `EXCEPTION_REVIEW`, or `COMMITTEE_REVIEW` — the committee may order additional
    collateral opinions mid-review — otherwise `ERR_INVALID_STATE`."

    Design: Corner/validations/appraisal_order_requires_review_stage
    """
    o = setup_officers(["rm", "apm"])
    bor = create_borrower(o)
    app = validate_success(api_client.create_loan_application(
        loan_application_payload(bor["id"]), o["rm"]["headers"]), 201)
    appraiser = validate_success(api_client.create_appraiser(
        {"name": "AppraisalCo", "license_number": "LIC-100"}, o["apm"]["headers"]), 201)

    resp = api_client.create_appraisal(
        {"loan_application_id": app["id"], "appraiser_id": appraiser["id"],
         "collateral_class": "REAL_ESTATE", "engagement_start_date": "2026-08-03",
         "engagement_end_date": "2026-08-07"}, o["apm"]["headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    rows, meta = validate_paginated(api_client.list_application_appraisals(app["id"], o["apm"]["headers"]))
    assert rows == [] and meta["total_count"] == 0
