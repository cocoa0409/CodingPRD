"""Two version guards on parent rows, and the time-driven re-scoring of a partner."""

from test_helpers import (
    ADMIN_HEADERS,
    OFFICER_A_HEADERS,
    ApiErrorId,
    assert_case_state,
    assert_page_meta,
    assert_partner_gate,
    assert_plan_state,
    assert_score_equal,
    factories as f,
    fixtures as fx,
    make_partner_manager_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-20T12:00:00Z"
EPOCH = "2026-08-02T12:00:00Z"
DAY_NINETY = "2026-10-31T12:00:00Z"
DAY_NINETY_ONE = "2026-11-01T12:00:00Z"
TOMORROW_EVENING = "2026-08-21T18:00:00Z"
PROBE_MOMENT = "2026-08-03T18:00:00Z"
PLAN_DUE = "2026-09-15T12:00:00Z"
LATER_PLAN_DUE = "2026-09-20T12:00:00Z"


def _instant(value):
    """The instant a timestamp names, without the fractional digits of PRD 2.4."""
    assert value is not None, "the timestamp must not be null"
    return value.replace("Z", "").split(".")[0]


def test_01_the_purchaser_version_guard_rejects_both_a_stale_and_a_replayed_number(api):
    """PRD 2.8: "A request that creates an `IdentityCheck` under a customer must carry
    `expected_customer_version`, a non-optional input field holding the `version` of that
    `Customer` row as the client last observed it. If it does not equal the customer's current
    `version`, the request is rejected with `ERR_STALE_CUSTOMER_VERSION` and HTTP 412."

    PRD 3.2: "The customer's `latest_identity_check_result` is then re-derived as the `result`
    of whichever of that customer's checks has `status` of `VALID` and the greatest
    `created_at`, falling back to `NONE` when no such row exists, and the customer's `version`
    advances by one."

    Design: Corner/cross_cutting_complexity_layers/corner_identity_check_creation_enforces_the_customer_occ_field
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    attested = fx.attest_customer(api, customer["id"], f.ADULT_DOB)
    observed_version = attested["version"]

    behind = api.create_identity_check(
        customer["id"], f.identity_check_payload(observed_version - 1), OFFICER_A_HEADERS
    )

    validate_error(behind, ApiErrorId.STALE_CUSTOMER_VERSION.value)
    _, empty_meta = validate_paginated(
        api.list_identity_checks(customer["id"], OFFICER_A_HEADERS)
    )
    assert_page_meta(empty_meta, total_count=0)
    untouched = fx.read_customer(api, customer["id"])
    assert untouched["version"] == observed_version, (
        f"the refused write left the purchaser at {observed_version}; got {untouched['version']}"
    )
    assert untouched["latest_identity_check_result"] == "NONE"

    stored = validate_success(
        api.create_identity_check(
            customer["id"], f.identity_check_payload(observed_version), OFFICER_A_HEADERS
        ),
        expected_status=201,
    )

    assert stored["result"] == "MATCH"
    assert stored["status"] == "VALID"
    consumed = fx.read_customer(api, customer["id"])
    assert consumed["version"] == observed_version + 1, (
        "the child write advances the parent's `version`; got "
        f"{consumed['version']} instead of {observed_version + 1}"
    )
    assert consumed["latest_identity_check_result"] == "MATCH"

    replay = api.create_identity_check(
        customer["id"],
        f.identity_check_payload(
            observed_version,
            provider="TELCO_VERIFY",
            source_signals=f.source_signals(
                government_id_db=False,
                credit_bureau=False,
                mobile_carrier=True,
                watchlist_negative=False,
            ),
        ),
        OFFICER_A_HEADERS,
    )

    validate_error(replay, ApiErrorId.STALE_CUSTOMER_VERSION.value)
    rows, meta = validate_paginated(api.list_identity_checks(customer["id"], OFFICER_A_HEADERS))
    assert_page_meta(meta, total_count=1)
    assert rows[0]["status"] == "VALID", (
        f"the replayed number superseded nothing; got {rows[0]['status']!r}"
    )


def test_02_the_case_version_guard_rejects_both_a_stale_and_a_replayed_number(api):
    """PRD 2.8: "A request that files a `CorrectiveActionPlan` against a violation case must
    carry `expected_violation_case_version`, a non-optional input field holding the `version`
    of that `ViolationCase` row as the client last observed it. If it does not equal the
    case's current `version`, the request is rejected with `ERR_STALE_CASE_VERSION` and HTTP
    412."

    PRD 3.9: "The new plan opens in `state` `SUBMITTED` with `revision_round` 0 and
    `reviewed_by_user_id`, `verified_by_user_id`, `verification_outcome` and `notes` all null;
    filing it marks every earlier plan of the same case whose `state` is `SUBMITTED`,
    `ACCEPTED`, `REVISION_REQUESTED` or `FAILED_VERIFICATION` as `SUPERSEDED` — the edge
    `SUBMITTED → SUPERSEDED` and its counterparts from the other three non-terminal plan
    states — and advances the case's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/corner_corrective_action_plan_creation_enforces_the_case_occ_field
    """
    fx.set_clock(api, CLOCK)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], TOMORROW_EVENING, 600
    )
    probe = fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type="UNDERAGE_PRESENTER",
        scheduled_at=TOMORROW_EVENING,
        expected_outcome="REFUSAL",
    )
    case = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="MAJOR",
        officer_headers=OFFICER_A_HEADERS,
    )
    observed_version = case["version"]
    partner_headers = make_partner_manager_headers(partner["id"])

    behind = api.create_corrective_action_plan(
        case["id"],
        f.corrective_action_plan_payload(
            observed_version - 1,
            due_at=PLAN_DUE,
            remediation_items=["Retrain the courier"],
        ),
        partner_headers,
    )

    validate_error(behind, ApiErrorId.STALE_CASE_VERSION.value)
    _, empty_meta = validate_paginated(
        api.list_corrective_action_plans(case["id"], OFFICER_A_HEADERS)
    )
    assert_page_meta(empty_meta, total_count=0)
    untouched = fx.read_case(api, case["id"])
    assert untouched["version"] == observed_version, (
        f"the refused filing left the case at {observed_version}; got {untouched['version']}"
    )
    assert_case_state(untouched, "SUBSTANTIATED")

    plan = validate_success(
        api.create_corrective_action_plan(
            case["id"],
            f.corrective_action_plan_payload(
                observed_version,
                due_at=PLAN_DUE,
                remediation_items=[
                    "Retrain the courier",
                    "Add a scan prompt to the courier app",
                ],
            ),
            partner_headers,
        ),
        expected_status=201,
    )

    assert_plan_state(plan, "SUBMITTED")
    assert plan["revision_round"] == 0, (
        f"a freshly filed plan has taken no revisions; got {plan['revision_round']}"
    )
    assert plan["violation_case_id"] == case["id"]
    consumed = fx.read_case(api, case["id"])
    assert consumed["version"] == observed_version + 1, (
        "the child write advances the parent's `version`; got "
        f"{consumed['version']} instead of {observed_version + 1}"
    )

    replay = api.create_corrective_action_plan(
        case["id"],
        f.corrective_action_plan_payload(
            observed_version,
            due_at=LATER_PLAN_DUE,
            remediation_items=["Second attempt from a stale view"],
        ),
        partner_headers,
    )

    validate_error(replay, ApiErrorId.STALE_CASE_VERSION.value)
    plans, meta = validate_paginated(
        api.list_corrective_action_plans(case["id"], OFFICER_A_HEADERS)
    )
    assert_page_meta(meta, total_count=1)
    assert_plan_state(plans[0], "SUBMITTED")


def test_03_the_sweep_repostures_a_partner_the_day_the_rolling_window_lets_go(api):
    """PRD 2.5: "Step three re-scores partners: every `DeliveryPartner` has both
    `license_risk_score` and `lifetime_risk_score` recomputed, because risk decay is a
    function of elapsed time, after which the posture derivation runs and may worsen or
    improve `posture` — and a worsening posture cascades to that partner's dispatched
    orders in `created_at` ascending order exactly as it does when a case decision
    triggers it."

    PRD 2.5: "The response reports `current_utc` together with `expired_identity_check_count`,
    `expired_certification_count` and `repostured_partner_count`, the last counting partners
    whose `posture` value actually changed during step three."

    PRD 3.9: "The **rolling** variant, written to `license_risk_score`, includes only cases
    whose age is 90 days or fewer and weights every included case at 1.00 — a case older than
    ninety days vanishes from it entirely. This is the only variant that drives posture
    derivation. The **lifetime** variant, written to `lifetime_risk_score`, includes every
    substantiated case forever and weights each by a decaying factor: one full point minus a
    tenth for each complete 90-day step of age, floored at a quarter point, so the weight
    never decays below 0.25."

    PRD 3.4: "The derivation is a two-step threshold ladder evaluated in this order: if the
    partner's `license_risk_score` is at or above 60.00, **or** its
    `open_critical_case_count` is at least 2, the posture becomes `SUSPENDED`; otherwise, if
    `license_risk_score` is at or above 25.00, **or** `open_case_count` is at least 3, the
    posture becomes `RESTRICTED`; otherwise it becomes `OPEN`."

    Design: Corner/cross_cutting_complexity_layers/corner_the_clock_sweep_reposts_a_partner_only_when_the_window_actually_expires
    """
    fx.set_clock(api, EPOCH)
    jurisdiction = fx.create_jurisdiction(
        api, code="US-NY", name="New York", dry_status="WET", utc_offset_minutes=-240
    )
    customer = fx.create_customer(api, jurisdiction["id"], full_name="Ada Lin")
    partner = fx.create_partner(
        api, legal_name="Empire Last Mile", license_reference="NY-DEL-0001"
    )
    courier = fx.create_courier(api, partner["id"], full_name="Dana Reyes")
    decoy = fx.create_order(
        api, customer["id"], jurisdiction["id"], partner["id"], PROBE_MOMENT, 600
    )
    probe = fx.schedule_shopper_test(
        api,
        courier["id"],
        decoy["id"],
        scenario_type="INTOXICATION_CUES",
        scheduled_at=PROBE_MOMENT,
        expected_outcome="REFUSAL",
    )
    case = fx.build_substantiated_case(
        api,
        partner["id"],
        secret_shopper_test_id=probe["id"],
        severity="CRITICAL",
        officer_headers=OFFICER_A_HEADERS,
    )

    assert _instant(case["decided_at"]) == _instant(EPOCH)
    assert_score_equal(case["risk_contribution"], 40.00, "risk_contribution")
    assert_partner_gate(
        fx.read_partner(api, partner["id"]),
        posture="RESTRICTED",
        license_risk_score=40.00,
        lifetime_risk_score=40.00,
    )

    ninetieth_day = validate_success(
        api.set_clock(f.clock_payload(DAY_NINETY), ADMIN_HEADERS)
    )

    assert _instant(ninetieth_day["current_utc"]) == _instant(DAY_NINETY)
    assert ninetieth_day["repostured_partner_count"] == 0, (
        "at ninety days the case is still inside the rolling window, so no posture moved; got "
        f"{ninetieth_day['repostured_partner_count']}"
    )
    assert ninetieth_day["expired_identity_check_count"] == 0
    assert ninetieth_day["expired_certification_count"] == 0
    still_restricted = fx.read_partner(api, partner["id"])
    assert_partner_gate(
        still_restricted,
        posture="RESTRICTED",
        license_risk_score=40.00,
        lifetime_risk_score=36.00,
    )

    ninety_first_day = validate_success(
        api.set_clock(f.clock_payload(DAY_NINETY_ONE), ADMIN_HEADERS)
    )

    assert ninety_first_day["repostured_partner_count"] == 1, (
        "the day after the window closes the score collapses and exactly one partner moves; "
        f"got {ninety_first_day['repostured_partner_count']}"
    )
    released = fx.read_partner(api, partner["id"])
    assert_partner_gate(
        released,
        posture="OPEN",
        open_case_count=0,
        open_critical_case_count=0,
        license_risk_score=0.00,
        lifetime_risk_score=36.00,
    )
    assessment = validate_success(api.get_risk_assessment(partner["id"], OFFICER_A_HEADERS))
    assert_score_equal(assessment["rolling_90d_score"], 0.00, "rolling_90d_score")
    assert_score_equal(assessment["lifetime_weighted_score"], 36.00, "lifetime_weighted_score")
    assert_score_equal(assessment["tier_multiplier"], 1.00, "tier_multiplier")
    assert assessment["open_case_count"] == 0
    assert assessment["open_critical_case_count"] == 0
    assert assessment["posture"] == "OPEN"
    unrewritten = fx.read_case(api, case["id"])
    assert_case_state(unrewritten, "SUBSTANTIATED")
    assert unrewritten["assessed_severity"] == "CRITICAL", (
        "the sweep re-scores; it never rewrites case state; got "
        f"{unrewritten['assessed_severity']!r}"
    )
