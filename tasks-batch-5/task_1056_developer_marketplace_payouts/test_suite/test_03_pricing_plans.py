"""Pricing plans: model rules, the effective-window chain and the version guard."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_pricing_plan,
    configure_jurisdiction,
    create_draft_app,
    create_pricing_plan_payload,
    create_verified_developer,
    make_developer_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import add_pricing_plan, app_version


def test_plan_with_undeclared_kind_is_rejected(api):
    """PRD 2.8: "each enum-typed value is a declared member of that enumeration"
    PRD 3.4: "A pricing plan is attached to a listing by its owner and priced in one of
    three monetisation models named by `kind`: `ONE_TIME`, `SUBSCRIPTION` or `IAP`."

    Design: Corner/entities/corner_pricing_plan_invalid_kind_enum_returns_invalid_request
    """
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Enum Co", email="en@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Enum App", category="FINANCE",
                           listed_countries=["US"])

    payload = create_pricing_plan_payload(
        app["version"], kind="RENTAL", price_cents=100, currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    response = api.create_pricing_plan(app["id"], payload, headers)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.status_code == 400

    _plans, meta = validate_paginated(api.list_app_pricing_plans(app["id"], headers))
    assert meta["total_count"] == 0


def test_plan_under_an_unknown_listing_returns_app_not_found(api):
    """PRD 2.8: "Existence. Every resource named in the URL path exists, validated left to
    right, so that the outermost missing segment is the one reported."
    PRD 2.8: "The error identifier names the missing resource type:
    `ERR_DEVELOPER_NOT_FOUND`, `ERR_APP_NOT_FOUND`, `ERR_REVIEW_SUBMISSION_NOT_FOUND`,
    `ERR_PRICING_PLAN_NOT_FOUND`, `ERR_TAX_JURISDICTION_NOT_FOUND`,
    `ERR_REVENUE_SHARE_TIER_NOT_FOUND`, `ERR_PURCHASE_NOT_FOUND`, `ERR_REFUND_NOT_FOUND`,
    `ERR_CHARGEBACK_NOT_FOUND`, `ERR_POLICY_CASE_NOT_FOUND`,
    `ERR_PAYOUT_BATCH_NOT_FOUND`, `ERR_PAYOUT_LINE_NOT_FOUND`,
    `ERR_LEDGER_ENTRY_NOT_FOUND` or `ERR_TAX_FORM_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/corner_pricing_plan_create_under_unknown_app_returns_app_not_found
    """
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Orphan Plans Co", email="op@x.test", country_code="US"
    )
    payload = create_pricing_plan_payload(
        1, kind="ONE_TIME", price_cents=100, currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    response = api.create_pricing_plan(
        NON_EXISTENT_UUID, payload, make_developer_headers(developer["id"])
    )
    validate_error(response, ApiErrorId.ERR_APP_NOT_FOUND)
    assert response.status_code == 404


def test_subscription_plan_without_billing_period_is_rejected(api):
    """PRD 3.4: "The `billing_period_months` field defaults to 0 and is where the three
    models diverge. For a `SUBSCRIPTION` plan it must be at least 1, naming the renewal
    period in months. For a `ONE_TIME` plan and for an `IAP` plan it must be exactly 0.
    Either violation — a subscription with a zero period, or a one-time or in-app-purchase
    plan with a non-zero one — is rejected with `ERR_INVALID_PRICING`."

    Design: Corner/validations/corner_subscription_plan_without_billing_period_returns_invalid_pricing
    """
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Sub Co", email="sub@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Sub App",
                           category="PRODUCTIVITY", listed_countries=["US"])

    payload = create_pricing_plan_payload(
        app["version"], kind="SUBSCRIPTION", price_cents=999, currency="USD",
        country_code="US", effective_from="2026-07-01T00:00:00Z",
        effective_to="2027-07-01T00:00:00Z",
    )
    payload.pop("billing_period_months", None)
    response = api.create_pricing_plan(app["id"], payload, headers)
    validate_error(response, ApiErrorId.ERR_INVALID_PRICING)
    assert response.status_code == 422

    _plans, meta = validate_paginated(api.list_app_pricing_plans(app["id"], headers))
    assert meta["total_count"] == 0


def test_retiring_a_plan_moves_it_to_retired(api):
    """PRD 3.4: "A new plan is born `ACTIVE`. Its owner may retire it explicitly, moving
    `ACTIVE → RETIRED`, and delisting the parent listing retires every `ACTIVE` plan on
    it."

    Design: Corner/endpoints/corner_pricing_plan_retire_sets_status_retired
    """
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Retire Plan Co", email="rpc@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="RetirePlan", category="HEALTH",
                           listed_countries=["US"])
    plan = add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=300,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    assert_pricing_plan(plan)
    assert plan["status"] == "ACTIVE"

    retired = validate_success(api.retire_pricing_plan(plan["id"], headers))
    assert retired["status"] == "RETIRED"

    plans, meta = validate_paginated(
        api.list_app_pricing_plans(app["id"], headers, {"status": "RETIRED"})
    )
    assert meta["total_count"] == 1
    assert plans[0]["id"] == plan["id"]


def test_plan_creation_with_a_stale_app_version_is_rejected(api):
    """PRD 2.7: "Attaching a pricing plan to a listing requires the request body to carry
    `expected_app_version`, a non-optional field holding the client's last observed
    `version` of the target `App`. If that value does not equal the app's current
    `version`, the request is rejected with `ERR_STALE_APP_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/corner_pricing_plan_create_with_stale_app_version_returns_412
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="OCC App Co", email="occ@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="OCC App",
                           category="DEVELOPER_TOOLS", listed_countries=["US"])
    assert app["version"] == 1

    add_pricing_plan(
        api, app["id"], developer["id"], expected_app_version=1, kind="ONE_TIME",
        price_cents=500, currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-10T00:00:00Z",
    )
    assert app_version(api, app["id"], developer["id"]) == 2, (
        "creating a plan mutates the listing, so App.version advances to 2"
    )

    stale = create_pricing_plan_payload(
        1, kind="ONE_TIME", price_cents=600, currency="USD", country_code="US",
        effective_from="2026-07-11T00:00:00Z", effective_to="2026-08-11T00:00:00Z",
    )
    response = api.create_pricing_plan(app["id"], stale, headers)
    validate_error(response, ApiErrorId.ERR_STALE_APP_VERSION)
    assert response.status_code == 412

    _plans, meta = validate_paginated(api.list_app_pricing_plans(app["id"], headers))
    assert meta["total_count"] == 1
    assert app_version(api, app["id"], developer["id"]) == 2


def test_successor_plan_exactly_twenty_four_hours_later_is_accepted(api):
    """PRD 3.4: "Successive plans of the same `kind` on the same listing form a chain
    rather than a set: a new plan must begin at least twenty-four hours after the
    inclusive end of every existing plan of that `kind` on that listing that is not
    `RETIRED`. Exactly twenty-four hours after the prior window's end is acceptable;
    anything closer, or any overlap, is rejected with `ERR_PRICING_WINDOW_CONFLICT` — as
    is an inverted window whose start falls after its end."

    Design: Difficulty/resource_temporal_overlap/pricing_plan_closed_window_cooldown_exact_boundary_accepted_shortfall_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Cooldown Co", email="c@cool.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Cooldown",
                           category="PRODUCTIVITY", listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=500,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-10T00:00:00Z",
    )

    payload = create_pricing_plan_payload(
        app_version(api, app["id"], developer["id"]), kind="ONE_TIME", price_cents=600,
        currency="USD", country_code="US",
        effective_from="2026-07-11T00:00:00Z", effective_to="2026-08-11T00:00:00Z",
    )
    data = validate_success(api.create_pricing_plan(app["id"], payload, headers), 201)
    assert data["status"] == "ACTIVE"

    _plans, meta = validate_paginated(api.list_app_pricing_plans(app["id"], headers))
    assert meta["total_count"] == 2


def test_successor_plan_only_twelve_hours_later_is_rejected(api):
    """PRD 3.4: "Exactly twenty-four hours after the prior window's end is acceptable;
    anything closer, or any overlap, is rejected with `ERR_PRICING_WINDOW_CONFLICT` — as
    is an inverted window whose start falls after its end."

    Design: Difficulty/resource_temporal_overlap/pricing_plan_closed_window_cooldown_exact_boundary_accepted_shortfall_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Cooldown Co", email="c@cool.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Cooldown",
                           category="PRODUCTIVITY", listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=500,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-10T00:00:00Z",
    )
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=600,
        currency="USD", country_code="US",
        effective_from="2026-07-11T00:00:00Z", effective_to="2026-08-11T00:00:00Z",
    )

    payload = create_pricing_plan_payload(
        app_version(api, app["id"], developer["id"]), kind="ONE_TIME", price_cents=700,
        currency="USD", country_code="US",
        effective_from="2026-08-11T12:00:00Z", effective_to="2026-12-01T00:00:00Z",
    )
    response = api.create_pricing_plan(app["id"], payload, headers)
    validate_error(response, ApiErrorId.ERR_PRICING_WINDOW_CONFLICT)
    assert response.status_code == 409

    _plans, meta = validate_paginated(api.list_app_pricing_plans(app["id"], headers))
    assert meta["total_count"] == 2


def test_unconfigured_jurisdiction_pre_empts_the_window_conflict(api):
    """PRD 2.8: "When a single request would fail several checks, the rejection that is
    returned is fixed and not implementation-dependent. Checks are evaluated in the
    following order, and the first one that fails determines the response:"
    PRD 2.8: "Jurisdiction configuration (`ERR_JURISDICTION_NOT_CONFIGURED`), then
    plan-to-app agreement (`ERR_PLAN_APP_MISMATCH`)."
    PRD 2.8: "Pricing-window spacing (`ERR_PRICING_WINDOW_CONFLICT`), then payout-period
    overlap (`ERR_BATCH_PERIOD_OVERLAP`), then the refund window
    (`ERR_REFUND_WINDOW_EXPIRED`), then the representment window
    (`ERR_REPRESENTMENT_WINDOW_EXPIRED`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_pricing_plan_create
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    configure_jurisdiction(api, "DE", 1900, True)
    developer = create_verified_developer(
        api, legal_name="Refer Temporal Co", email="rt@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="RT App",
                           category="PRODUCTIVITY", listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=999,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )

    # FR is deliberately unconfigured AND the window overlaps the existing plan.
    payload = create_pricing_plan_payload(
        app_version(api, app["id"], developer["id"]), kind="ONE_TIME", price_cents=499,
        currency="USD", country_code="FR",
        effective_from="2026-08-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    response = api.create_pricing_plan(app["id"], payload, headers)
    validate_error(response, ApiErrorId.ERR_JURISDICTION_NOT_CONFIGURED)
    assert response.status_code == 422

    _plans, meta = validate_paginated(api.list_app_pricing_plans(app["id"], headers))
    assert meta["total_count"] == 1


def test_window_conflict_surfaces_once_the_jurisdiction_is_configured(api):
    """PRD 3.4: "A plan for a country with no registered jurisdiction is rejected with
    `ERR_JURISDICTION_NOT_CONFIGURED`."
    PRD 3.4: "Exactly twenty-four hours after the prior window's end is acceptable;
    anything closer, or any overlap, is rejected with `ERR_PRICING_WINDOW_CONFLICT` — as
    is an inverted window whose start falls after its end."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_pricing_plan_create
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    configure_jurisdiction(api, "FR", 2000, True)
    developer = create_verified_developer(
        api, legal_name="Refer Temporal Co", email="rt@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="RT App",
                           category="PRODUCTIVITY", listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=999,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )

    payload = create_pricing_plan_payload(
        app_version(api, app["id"], developer["id"]), kind="ONE_TIME", price_cents=499,
        currency="USD", country_code="FR",
        effective_from="2026-08-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    response = api.create_pricing_plan(app["id"], payload, headers)
    validate_error(response, ApiErrorId.ERR_PRICING_WINDOW_CONFLICT)
    assert response.status_code == 409
