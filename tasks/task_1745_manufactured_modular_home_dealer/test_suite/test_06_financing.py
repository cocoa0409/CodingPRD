"""Financing origination, underwriting, rate lock, and funding (PRD §2.7, §2.8, §3.5)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equals,
    canonical_community_scenario,
    create_application,
    create_financing_application_payload,
    create_title_record_payload,
    decide_application,
    get_success_data,
    issue_title_for_order,
    new_order_scenario,
    progress_to_site_approved,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

CONSULTANT = TEST_USERS["consultant_headers"]
LENDER = TEST_USERS["lender_headers"]


def _submitted_application(financing_type="CHATTEL", price=4_200_000, term_months=240, deposit=None):
    """Private-land order taken to SITE_APPROVED, then an application created and submitted."""
    scn = new_order_scenario(
        placement_type="PRIVATE_LAND",
        agreed_home_price_cents=price,
        financing_type=financing_type,
        double_wide=(price >= 9_000_000),
    )
    progress_to_site_approved(scn, deposit_cents=deposit)
    create_application(scn, term_months=term_months)
    submit_application(scn)
    return scn


# --- dual-variant loan pricing (chattel vs real property) -------------------

def _dual_variant_pair():
    scn_chattel = _submitted_application("CHATTEL", 9_200_000, deposit=456_850)
    scn_real = _submitted_application("REAL_PROPERTY", 9_200_000, deposit=456_850)
    return scn_chattel, scn_real


def test_variant_estimated_payments_at_submit(api):
    """PRD §3.5: "On submission the application moves `DRAFT` → `SUBMITTED` and
    two computed fields are fixed: `requested_amount_cents` is set to the order's
    current `amount_financed_cents`, and `estimated_payment_cents` is the annuity
    payment on that amount at the type's rate floor."
    PRD §3.5: "The rate floors are 700 basis points (7.00%) for `CHATTEL` and 450
    basis points (4.50%) for `REAL_PROPERTY`, so the same principal and term
    always price a strictly lower estimated payment under real-property financing
    than under chattel."

    Design: Difficulty/dual_variant_calc/chattel_vs_real_property_monthly_payment
    """
    scn_chattel, scn_real = _dual_variant_pair()
    for scn in (scn_chattel, scn_real):
        assert scn["order"]["total_price_cents"] == 9_137_000
        assert scn["order"]["amount_financed_cents"] == 8_680_150
        assert scn["application"]["requested_amount_cents"] == 8_680_150

    assert scn_chattel["application"]["estimated_payment_cents"] == 67_297
    assert scn_real["application"]["estimated_payment_cents"] == 54_915
    delta = scn_chattel["application"]["estimated_payment_cents"] - scn_real["application"]["estimated_payment_cents"]
    assert delta == 12_382, f"identical principal and term price chattel 12,382 higher, got {delta}"


def test_variant_monthly_payments_at_decide(api):
    """PRD §3.5: "on approval the application moves to `APPROVED`, records the
    agreed `apr_bps`, computes `monthly_payment_cents` as the annuity at that
    approved rate, sets `rate_lock_expires_at` to exactly 14 days after the
    approval instant, stamps `decided_by` with the lender's `X-User-ID`, and
    bubbles the order `PENDING_FINANCING` → `FINANCING_APPROVED`."
    PRD §3.5: "the monthly rate is the APR in basis points divided by ten
    thousand and then by twelve; the payment is the requested amount multiplied
    by that monthly rate, divided by one minus the quantity (one plus the monthly
    rate) raised to the power of negative `term_months`, rounded half-up to whole
    cents."

    Design: Difficulty/dual_variant_calc/chattel_vs_real_property_monthly_payment
    """
    scn_chattel, scn_real = _dual_variant_pair()
    app_chattel = decide_application(scn_chattel, "APPROVE", 725)
    app_real = decide_application(scn_real, "APPROVE", 500)

    assert app_chattel["monthly_payment_cents"] == 68_606
    assert app_real["monthly_payment_cents"] == 57_285
    assert app_chattel["monthly_payment_cents"] > app_real["monthly_payment_cents"]
    assert scn_chattel["order"]["deal_status"] == "FINANCING_APPROVED"
    assert scn_real["order"]["deal_status"] == "FINANCING_APPROVED"


# --- origination and supersession --------------------------------------------

def test_second_application_supersedes_first(api, consultant_headers):
    """PRD §3.5: "The first application created for an order bubbles the order
    `SITE_APPROVED` → `PENDING_FINANCING`; each subsequent application for the
    same order supersedes the prior one still in `DRAFT`, `SUBMITTED`,
    `CONDITIONALLY_APPROVED`, or `APPROVED` (the prior becomes `SUPERSEDED`),
    leaves the order in `PENDING_FINANCING`, and increments the order's `version`
    again."

    Design: Corner/state_machines/second_application_supersedes_first
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    progress_to_site_approved(scn, deposit_cents=212_100)
    app1 = create_application(scn, term_months=240)
    assert app1["status"] == "DRAFT"
    assert scn["order"]["deal_status"] == "PENDING_FINANCING"

    app2 = create_application(scn, term_months=180, lender_name="Rival Bank")
    assert app2["status"] == "DRAFT"
    app1_view = get_success_data(api.get_financing_application(app1["id"], consultant_headers))
    assert app1_view["status"] == "SUPERSEDED"
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "PENDING_FINANCING", "self-loop: no regression to SITE_APPROVED"


def test_conditional_approval_then_second_decide_approves(api, consultant_headers):
    """PRD §3.5: "A `CONDITIONAL` decision (same floor check) moves the
    application to `CONDITIONALLY_APPROVED`, stamps `decided_by`, and freezes
    `requested_amount_cents` — from that point the trade-in cascade of §3.9 no
    longer recomputes it. A conditionally approved application accepts a second
    decide with `decision` `APPROVE`, which computes `monthly_payment_cents`,
    sets the 14-day rate lock, and bubbles the order to `FINANCING_APPROVED`."

    Design: Corner/state_machines/conditional_approval_then_second_decide_approves
    """
    scn = _submitted_application("CHATTEL", 4_200_000)
    assert scn["application"]["requested_amount_cents"] == 4_029_900

    app = decide_application(scn, "CONDITIONAL", 750)
    assert app["status"] == "CONDITIONALLY_APPROVED"
    assert app["apr_bps"] == 750
    assert app["requested_amount_cents"] == 4_029_900, "requested amount is frozen at the conditional decision"
    assert scn["order"]["deal_status"] == "PENDING_FINANCING", "no bubble on a conditional decision"

    app2 = decide_application(scn, "APPROVE")
    assert app2["status"] == "APPROVED"
    assert app2["requested_amount_cents"] == 4_029_900
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "FINANCING_APPROVED"


def test_occ_stale_financing_create_rejected(api, consultant_headers):
    """PRD §2.7: "Two creation endpoints are guarded by optimistic concurrency
    control on the parent order: `POST /api/sales-orders/{id}/site-evaluations`
    and `POST /api/sales-orders/{id}/financing-applications`."
    PRD §2.7: "If that value does not match the order's current `version` — for
    example because another writer advanced the order since the client read it —
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_financing_create_rejected
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    progress_to_site_approved(scn, deposit_cents=212_100)
    stale_version = scn["order"]["version"]

    app1 = create_application(scn, term_months=240)
    assert app1["status"] == "DRAFT"

    resp = api.create_financing_application(
        scn["order"]["id"],
        create_financing_application_payload("CHATTEL", stale_version, lender_name="Rival Bank", down_payment_cents=212_100),
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    rows, meta = validate_paginated(api.list_financing_applications(scn["order"]["id"], consultant_headers))
    assert meta["total_count"] == 1 and rows[0]["id"] == app1["id"], "a stale create adds no application"


# --- decide guards -------------------------------------------------------------

def test_consultant_cannot_decide_financing(api, consultant_headers):
    """PRD §2.1: "`LenderAgent` — the lender-side decision maker; decides and
    funds applications but cannot originate them (segregation from
    `SalesConsultant`)."
    PRD §4: POST /api/financing-applications/{id}/decide — "Lender decision:
    APPROVE / CONDITIONAL / DENY; CONDITIONALLY_APPROVED accepts a second
    APPROVE | LenderAgent".

    Design: Corner/rbac/consultant_cannot_decide_financing
    """
    scn = _submitted_application("CHATTEL", 4_200_000)
    resp = api.decide_financing_application(scn["application"]["id"], {"decision": "APPROVE", "apr_bps": 725}, consultant_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
    view = get_success_data(api.get_financing_application(scn["application"]["id"], consultant_headers))
    assert view["status"] == "SUBMITTED"


def test_decide_rate_below_floor_rejected(api):
    """PRD §3.5: "An `APPROVE` decision requires the offered `apr_bps` to meet
    the type's floor — 700 for chattel, 450 for real property — else
    `ERR_RATE_BELOW_FLOOR`".

    Design: Corner/validations/decide_rate_below_floor_rejected
    """
    scn = _submitted_application("CHATTEL", 4_200_000)
    resp = api.decide_financing_application(scn["application"]["id"], {"decision": "APPROVE", "apr_bps": 699}, LENDER)
    validate_error(resp, ApiErrorId.ERR_RATE_BELOW_FLOOR)

    app = decide_application(scn, "APPROVE", 700)
    assert app["status"] == "APPROVED", "exactly the 700 bps floor must pass"


def test_chattel_term_over_cap_rejected(api, consultant_headers):
    """PRD §3.5: "Term caps depend on type: at most 240 months for `CHATTEL`, at
    most 360 months for `REAL_PROPERTY`, with over-cap requests rejected as
    `ERR_TERM_EXCEEDS_CAP` both at creation and again at submission."

    Design: Corner/validations/chattel_term_over_cap_rejected
    """
    scn = new_order_scenario(placement_type="PRIVATE_LAND", agreed_home_price_cents=4_200_000)
    progress_to_site_approved(scn, deposit_cents=212_100)

    version = scn["order"]["version"]
    resp = api.create_financing_application(
        scn["order"]["id"],
        create_financing_application_payload("CHATTEL", version, term_months=241, down_payment_cents=212_100),
        consultant_headers,
    )
    validate_error(resp, ApiErrorId.ERR_TERM_EXCEEDS_CAP)

    app = create_application(scn, term_months=240)
    assert app["status"] == "DRAFT", "the exact 240-month cap is accepted"


# --- estimated vs decided payment ----------------------------------------------

def test_estimated_vs_decided_payment_variant_selection(api):
    """PRD §3.5: "On submission the application moves `DRAFT` → `SUBMITTED` and
    two computed fields are fixed: `requested_amount_cents` is set to the order's
    current `amount_financed_cents`, and `estimated_payment_cents` is the annuity
    payment on that amount at the type's rate floor."
    PRD §3.5: "on approval the application moves to `APPROVED`, records the
    agreed `apr_bps`, computes `monthly_payment_cents` as the annuity at that
    approved rate, sets `rate_lock_expires_at` to exactly 14 days after the
    approval instant, stamps `decided_by` with the lender's `X-User-ID`, and
    bubbles the order `PENDING_FINANCING` → `FINANCING_APPROVED`."

    Design: Corner/calculations/estimated_vs_decided_payment_variant_selection
    """
    scn = new_order_scenario(placement_type="COMMUNITY_LOT", agreed_home_price_cents=9_200_000, double_wide=True, options=[
        {"option_code": "OPT-APP", "description": "Appliance package", "unit_price_cents": 125_050, "quantity": 2},
        {"option_code": "OPT-EXT", "description": "Exterior package", "unit_price_cents": 89_999, "quantity": 1},
    ])
    progress_to_site_approved(scn, deposit_cents=473_600)
    app = create_application(scn, term_months=240)
    submitted = submit_application(scn, app)
    assert submitted["requested_amount_cents"] == 8_998_397
    assert submitted["estimated_payment_cents"] == 69_764, "estimate uses the 700 bps chattel floor"

    decided = decide_application(scn, "APPROVE", 725)
    assert decided["monthly_payment_cents"] == 71_121, "monthly payment uses the approved 725 bps"
    assert decided["estimated_payment_cents"] == 69_764, "the estimate field remains the floor-rate figure"


# --- funding gates ---------------------------------------------------------------

def test_fund_state_check_precedes_amount_check(api):
    """PRD §2.8: "Incoming requests are validated against the following checks in
    the stated order; the first failing check determines the response."
    PRD §2.8: "(all action endpoints): the target resource is in a state from
    which the requested transition exists — this covers idempotent re-fires and
    terminal lockdown — else `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.8: "the funded amount must equal the application's requested amount,
    else `ERR_FUNDING_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_before_fiscal
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    app = create_application(scn)
    submit_application(scn, app)
    issue_title_for_order(scn)

    resp = api.fund_financing_application(app["id"], {"funded_amount_cents": 1}, LENDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_fund_state_rejection_leaves_application_untouched(api):
    """PRD §3.5: "The `funded_amount_cents` must equal the application's
    `requested_amount_cents` exactly, else `ERR_FUNDING_AMOUNT_MISMATCH`."
    PRD §3.5: "a funding attempted after the lock lapses is rejected with
    `ERR_RATE_LOCK_EXPIRED` and the application transitions to `EXPIRED` in the
    same breath."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_before_fiscal
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    app = create_application(scn)
    submitted = submit_application(scn, app)
    issue_title_for_order(scn)

    resp = api.fund_financing_application(app["id"], {"funded_amount_cents": 1}, LENDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    view = get_success_data(api.get_financing_application(app["id"], LENDER))
    assert view["status"] == "SUBMITTED", "no transition fires on a state-rejected fund (EXPIRED belongs to the rate-lock rule)"
    assert view["requested_amount_cents"] == submitted["requested_amount_cents"]


def test_fund_after_rate_lock_expires_and_marks_expired(api):
    """PRD §3.5: "The attempt must land no later than `rate_lock_expires_at` — a
    funding attempted after the lock lapses is rejected with
    `ERR_RATE_LOCK_EXPIRED` and the application transitions to `EXPIRED` in the
    same breath."
    PRD §2.8: "Incoming requests are validated against the following checks in
    the stated order; the first failing check determines the response."
    PRD §2.8: "funding must occur no later than the rate-lock expiry, else
    `ERR_RATE_LOCK_EXPIRED` (HTTP 409) and the application transitions to
    `EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/fund_temporal_before_fiscal
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    app = decide_application(scn, "APPROVE", 725)
    issue_title_for_order(scn)

    get_success_data(api.set_clock({"to_iso8601": "2026-08-16T00:00:00Z"}, TEST_USERS["admin_headers"]))
    resp = api.fund_financing_application(app["id"], {"funded_amount_cents": 1}, LENDER)
    validate_error(resp, ApiErrorId.ERR_RATE_LOCK_EXPIRED)

    view = get_success_data(api.get_financing_application(app["id"], LENDER))
    assert view["status"] == "EXPIRED", "the lazy expiry transition fires with the rejection"


def test_rate_lock_is_fourteen_days_after_approval(api):
    """PRD §3.5: "on approval the application moves to `APPROVED`, records the
    agreed `apr_bps`, computes `monthly_payment_cents` as the annuity at that
    approved rate, sets `rate_lock_expires_at` to exactly 14 days after the
    approval instant, stamps `decided_by` with the lender's `X-User-ID`, and
    bubbles the order `PENDING_FINANCING` → `FINANCING_APPROVED`."

    Design: Difficulty/priority_pair_validation_conflict/fund_temporal_before_fiscal
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    # The logical clock is still at its 2026-08-01T00:00:00Z startup default, so
    # the lock must expire exactly 14 days later.
    app = decide_application(scn, "APPROVE", 725)
    assert_instant_equals(app["rate_lock_expires_at"], "2026-08-15T00:00:00Z")


def test_fund_requires_issued_title_record(api):
    """PRD §3.5: "And the title gate: an `ISSUED` title record must exist for the
    unit whose `title_type` matches the financing type — `MANUFACTURED_CERTIFICATE`
    for `CHATTEL`, `REAL_PROPERTY_AFFIXED` for `REAL_PROPERTY` — else
    `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/fund_requires_title_state_by_financing_type
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    app = decide_application(scn, "APPROVE", 725)

    resp_no_title = api.fund_financing_application(app["id"], {"funded_amount_cents": 8_998_397}, LENDER)
    validate_error(resp_no_title, ApiErrorId.ERR_INVALID_STATE)

    title = get_success_data(api.create_title_record(scn["unit"]["id"], create_title_record_payload(), TEST_USERS["admin_headers"]))
    assert title["status"] == "APPLIED"
    resp_applied = api.fund_financing_application(app["id"], {"funded_amount_cents": 8_998_397}, LENDER)
    validate_error(resp_applied, ApiErrorId.ERR_INVALID_STATE)


def test_fund_succeeds_with_issued_title_and_bubbles_order(api, consultant_headers):
    """PRD §3.5: "A successful funding moves the application to `FUNDED`, bubbles
    the order `FINANCING_APPROVED` → `AWAITING_DELIVERY`, and moves
    `payment_status` to `FINANCED` — which, per §3.4, also locks the order
    against cancellation."

    Design: Difficulty/cross_entity_state_dependency/fund_requires_title_state_by_financing_type
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    app = decide_application(scn, "APPROVE", 725)
    title = issue_title_for_order(scn)
    assert title["status"] == "ISSUED"

    funded = validate_success(
        api.fund_financing_application(app["id"], {"funded_amount_cents": 8_998_397}, LENDER)
    )
    assert funded["status"] == "FUNDED"
    order = get_success_data(api.get_sales_order(scn["order"]["id"], consultant_headers))
    assert order["deal_status"] == "AWAITING_DELIVERY" and order["payment_status"] == "FINANCED"


def test_funding_amount_mismatch_rejected(api):
    """PRD §3.5: "The `funded_amount_cents` must equal the application's
    `requested_amount_cents` exactly, else `ERR_FUNDING_AMOUNT_MISMATCH`."

    Design: Corner/validations/funding_amount_mismatch_rejected
    """
    scn = canonical_community_scenario()
    progress_to_site_approved(scn, deposit_cents=473_600)
    create_application(scn)
    submit_application(scn)
    app = decide_application(scn, "APPROVE", 725)
    issue_title_for_order(scn)

    resp = api.fund_financing_application(app["id"], {"funded_amount_cents": 8_998_398}, LENDER)
    validate_error(resp, ApiErrorId.ERR_FUNDING_AMOUNT_MISMATCH)

    funded = validate_success(
        api.fund_financing_application(app["id"], {"funded_amount_cents": 8_998_397}, LENDER)
    )
    assert funded["status"] == "FUNDED", "the exact requested amount funds"
