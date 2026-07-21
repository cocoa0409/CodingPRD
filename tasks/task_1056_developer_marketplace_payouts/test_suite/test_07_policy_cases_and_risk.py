"""Trust and safety: policy cases, the takedown cascade, appeals and risk scoring."""
from test_helpers import (
    ApiErrorId,
    accumulate_policy_strikes,
    appeal_case,
    calculate_batch,
    create_draft_app,
    create_verified_developer,
    decide_appeal,
    decide_case,
    execute_refund_flow,
    investigate_case,
    make_platform_admin_headers,
    make_policy_officer_headers,
    only_line,
    open_batch,
    open_policy_case,
    read_developer,
    record_and_capture,
    set_clock,
    setup_marketplace_with_live_app,
    single_line_purchase,
    uphold_case_on_app,
    validate_error,
    validate_paginated,
    validate_success,
)


def _cascade_context(api):
    """LIVE listing with two prior strikes and one CALCULATED batch line of 13300."""
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 20000},
        app_overrides={"name": "Cascade Main", "category": "GAMES"},
        developer_overrides={"legal_name": "Cascade Games", "email": "c@cascade.test"},
    )
    accumulate_policy_strikes(api, ctx["developer_id"], 2)
    assert read_developer(api, ctx["developer_id"])["policy_strike_count"] == 2

    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-CASCADE",
        line_items=single_line_purchase(20000),
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculated = calculate_batch(api, batch["id"])
    assert calculated["total_payable_cents"] == 13300
    ctx["batch_id"] = batch["id"]
    return ctx


def test_upheld_case_delists_the_listing_and_suspends_the_developer(api):
    """PRD 3.8: "An `UPHELD` outcome moves the case `INVESTIGATING → UPHELD`, stamps
    `decided_by_user_id`, and fires the full takedown cascade: the linked listing is
    driven to `DELISTED` with every one of that transition's effects — plans retired, both
    strike counters incremented — and, when the developer's resulting
    `policy_strike_count` reaches three or more while the account is `ACTIVE`, the account
    is carried `ACTIVE → SUSPENDED`, which in turn holds its payouts, flips its `PAYABLE`
    lines in `CALCULATED` and `PENDING_APPROVAL` batches to `HELD_DEVELOPER`, and forces
    those batches to recompute their totals. Five records deep, in one request."

    Design: Difficulty/transitive_cascade/policy_uphold_delists_app_then_suspends_developer_then_holds_line_then_rewrites_batch_totals
    """
    ctx = _cascade_context(api)
    decided = uphold_case_on_app(api, ctx["app_id"], category="IP_INFRINGEMENT",
                                 severity="HIGH")
    assert decided["status"] == "UPHELD"

    officer = make_policy_officer_headers("officer-decide")
    assert validate_success(api.get_app(ctx["app_id"], officer))["status"] == "DELISTED"
    assert validate_success(
        api.get_pricing_plan(ctx["plan_id"], make_platform_admin_headers("admin-cascade"))
    )["status"] == "RETIRED"

    developer = read_developer(api, ctx["developer_id"])
    assert developer["policy_strike_count"] == 3
    assert developer["status"] == "SUSPENDED"
    assert developer["payout_hold"] is True


def test_takedown_cascade_freezes_the_payout_line_and_rewrites_batch_totals(api,
                                                                            finance_headers):
    """PRD 3.2: "every payout line of that developer that is still `PAYABLE` and belongs
    to a batch in `CALCULATED` or `PENDING_APPROVAL` flips `PAYABLE → HELD_DEVELOPER` with
    its `payout_amount_cents` forced to 0. Each line that flips forces its owning batch to
    recompute `total_payable_cents` and `total_withholding_cents` over the lines that
    remain `PAYABLE`."
    PRD 2.9: "When a cascade re-enters a state machine — a policy decision that delists a
    listing, a delisting that suspends an account, a suspension that freezes payout lines,
    frozen lines that force a batch's totals to be recomputed — the downstream transition
    carries all of *its* declared effects too, recursively."

    Design: Difficulty/transitive_cascade/policy_uphold_delists_app_then_suspends_developer_then_holds_line_then_rewrites_batch_totals
    """
    ctx = _cascade_context(api)
    uphold_case_on_app(api, ctx["app_id"], category="IP_INFRINGEMENT", severity="HIGH")

    line = only_line(api, ctx["batch_id"])
    assert line["status"] == "HELD_DEVELOPER"
    assert line["payout_amount_cents"] == 0

    batch = validate_success(api.get_payout_batch(ctx["batch_id"], finance_headers))
    assert batch["total_payable_cents"] == 0
    assert batch["line_count"] == 1


def test_officer_who_opened_a_case_may_not_decide_it(api):
    """PRD 2.1: "A `PolicyOfficer` whose `X-User-ID` equals the `opened_by_user_id`
    recorded on a policy case may not decide that case, and may not decide an appeal
    against it; both attempts are rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/corner_same_officer_cannot_decide_the_case_they_opened
    """
    developer = create_verified_developer(
        api, legal_name="SoD Co", email="sod@x.test", country_code="US"
    )
    app = create_draft_app(api, developer["id"], name="SoD App", category="HEALTH",
                           listed_countries=["US"])
    case = open_policy_case(api, app["id"], opened_by="officer-open",
                            category="MALWARE", severity="HIGH")
    assert case["opened_by_user_id"] == "officer-open"
    investigate_case(api, case["id"], "officer-open")

    opener = make_policy_officer_headers("officer-open")
    response = api.decide_policy_case(
        case["id"], {"outcome": "UPHELD", "rationale": "self decision attempt"}, opener
    )
    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert response.status_code == 403

    assert validate_success(
        api.get_policy_case(case["id"], opener)
    )["status"] == "INVESTIGATING"
    assert validate_success(api.get_app(app["id"], opener))["status"] == "DRAFT"
    assert read_developer(api, developer["id"])["policy_strike_count"] == 0


def test_denied_appeal_returns_the_case_to_upheld(api):
    """PRD 3.8: "The developer may appeal an upheld case by supplying an
    `appeal_statement`, moving it `UPHELD → APPEALED`. Only the developer named on the
    case may appeal it."
    PRD 3.8: "A `DENIED` appeal returns the case `APPEALED → UPHELD`, and because appeal
    is available again from `UPHELD`, a case may be appealed and re-upheld any number of
    times."

    Design: Corner/state_machines/corner_policy_case_appeal_denied_returns_case_to_upheld
    """
    developer = create_verified_developer(
        api, legal_name="Appeal Co", email="ap@x.test", country_code="US"
    )
    app = create_draft_app(api, developer["id"], name="Appeal App", category="GAMES",
                           listed_countries=["US"])
    case = uphold_case_on_app(api, app["id"], category="CONTENT", severity="LOW")

    appealed = appeal_case(api, case["id"], developer["id"], "the content was licensed")
    assert appealed["status"] == "APPEALED"

    final = decide_appeal(api, case["id"], "DENIED", "license not verifiable")
    assert final["status"] == "UPHELD"

    assert read_developer(api, developer["id"])["policy_strike_count"] == 1
    officer = make_policy_officer_headers("officer-decide")
    assert validate_success(api.get_app(app["id"], officer))["status"] == "DELISTED"


def test_granted_appeal_decrements_both_strike_counters(api):
    """PRD 3.8: "A `GRANTED` appeal moves the case `APPEALED → REINSTATED` and decrements
    both the listing's `policy_strike_count` and the developer's `policy_strike_count` by
    1, each floored at 0. The listing itself stays `DELISTED`; restoring a delisted
    listing is out of scope for this system."

    Design: Corner/state_machines/corner_policy_case_appeal_granted_decrements_strike_counters
    """
    developer = create_verified_developer(
        api, legal_name="Reinstate Co", email="ri@x.test", country_code="US"
    )
    app = create_draft_app(api, developer["id"], name="Reinstate App",
                           category="PRODUCTIVITY", listed_countries=["US"])
    case = uphold_case_on_app(api, app["id"], category="IP_INFRINGEMENT",
                              severity="MEDIUM")
    appeal_case(api, case["id"], developer["id"], "counter-notice filed")

    final = decide_appeal(api, case["id"], "GRANTED", "counter-notice accepted")
    assert final["status"] == "REINSTATED"

    assert read_developer(api, developer["id"])["policy_strike_count"] == 0
    officer = make_policy_officer_headers("officer-decide")
    app_after = validate_success(api.get_app(app["id"], officer))
    assert app_after["policy_strike_count"] == 0
    assert app_after["status"] == "DELISTED"


def _risk_context(api):
    """One fully refunded purchase in July and one clean capture in August."""
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Bits Tracker", "category": "HEALTH"},
        developer_overrides={"legal_name": "Risky Bits Inc", "email": "risk@bits.test"},
    )
    set_clock(api, "2026-07-05T00:00:00Z")
    purchase_a = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-A",
        line_items=single_line_purchase(10000),
    )
    set_clock(api, "2026-07-06T00:00:00Z")
    execute_refund_flow(api, purchase_a["id"], 10000)

    set_clock(api, "2026-08-10T00:00:00Z")
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-B",
        line_items=single_line_purchase(10000),
    )
    return ctx


def test_standard_variant_scores_every_captured_purchase_for_all_time(api):
    """PRD 3.8: "The denominator is the sum of `gross_cents` over the scored set. If that
    denominator is 0, both the refund rate and the chargeback rate are taken as 0.
    Otherwise the refund rate is the sum of `refunded_gross_cents` over the scored set
    divided by that denominator, and the chargeback rate is the sum of `gross_cents` over
    only those scored purchases whose `payment_status` is `CHARGED_BACK`, divided by the
    same denominator."
    PRD 3.8: "When `risk_watch` is false the variant is `STANDARD` and the scored set
    spans every such purchase for all time, so old refunds keep depressing the score
    indefinitely."

    Design: Difficulty/dual_variant_calc/developer_risk_score_standard_vs_accelerated_window
    """
    ctx = _risk_context(api)
    developer = read_developer(api, ctx["developer_id"])
    assert developer["risk_variant"] == "STANDARD"
    assert developer["risk_score"] == 20, (
        "a 10000-cent refund against a 20000-cent all-time denominator is forty times 0.5"
    )


def test_accelerated_variant_clips_the_scored_set_to_thirty_days(api):
    """PRD 3.8: "Moving a case `OPEN → INVESTIGATING` does more than change its own state:
    it sets the owning developer's `risk_watch` to true and `risk_variant` to
    `ACCELERATED`, switching that developer's risk scoring to the thirty-day trailing
    window for as long as the watch stands."
    PRD 3.8: "When `risk_watch` is true the variant is `ACCELERATED` and the scored set is
    additionally clipped to purchases whose `captured_at` is at or after the current
    logical clock minus thirty days — the same underlying data therefore yields a
    different score."

    Design: Difficulty/dual_variant_calc/developer_risk_score_standard_vs_accelerated_window
    """
    ctx = _risk_context(api)
    assert read_developer(api, ctx["developer_id"])["risk_score"] == 20

    set_clock(api, "2026-09-01T00:00:00Z")
    case = open_policy_case(api, ctx["app_id"], opened_by="officer-open",
                            category="PAYMENT_ABUSE", severity="MEDIUM")
    investigate_case(api, case["id"], "officer-open")

    developer = read_developer(api, ctx["developer_id"])
    assert developer["risk_watch"] is True
    assert developer["risk_variant"] == "ACCELERATED"
    assert developer["risk_score"] == 0, (
        "the refunded July purchase falls outside the thirty-day trailing window"
    )
