"""App listings: creation, metadata edits, review rounds, publication, delisting."""
from test_helpers import (
    ApiErrorId,
    assert_app,
    assert_bare_uuid,
    assert_review_submission,
    configure_jurisdiction,
    create_app_payload,
    create_draft_app,
    create_developer,
    create_verified_developer,
    decide_review,
    make_developer_headers,
    publish_app,
    read_developer,
    set_clock,
    setup_approved_app,
    submit_for_review,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import add_pricing_plan, take_app_through_review


def test_create_listing_mints_system_fields_and_starts_at_draft(api):
    """PRD 2.4: "Every persisted resource carries a server-minted `id` that is a UUID
    string with no type prefix and no embedded meaning, and a `created_at` timestamp
    recorded as an ISO 8601 UTC string with three fractional digits."
    PRD 3.3: "The listing begins at `DRAFT` with `review_round` and `policy_strike_count`
    at 0."

    Design: Corner/entities/corner_app_system_fields_are_server_minted
    """
    developer = create_verified_developer(
        api, legal_name="System Fields Co", email="sf@x.test", country_code="US"
    )
    payload = create_app_payload(
        developer["id"], name="SysFields", category="HEALTH", listed_countries=["US"]
    )
    data = validate_success(
        api.create_app(payload, make_developer_headers(developer["id"])), 201
    )
    assert_app(data)
    assert_bare_uuid(data["id"])
    assert data["version"] == 1
    assert data["status"] == "DRAFT"
    assert data["review_round"] == 0
    assert data["policy_strike_count"] == 0


def test_create_listing_without_category_is_rejected(api):
    """PRD 2.8: "On every write endpoint: each required field is present and of the
    declared type, each enum-typed value is a declared member of that enumeration,
    monetary inputs such as `price_cents` and `amount_cents` are strictly greater than
    zero, `line_items` is a non-empty array whose objects each carry a `sku`, a
    `unit_price_cents` strictly greater than zero and a `quantity` strictly greater than
    zero, and uniqueness holds for `external_order_ref` across all purchases and for
    `network_case_ref` across all chargebacks. A failure here is `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/entities/corner_app_create_missing_required_category_returns_invalid_request
    """
    developer = create_verified_developer(
        api, legal_name="Missing Fields Co", email="mf@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    response = api.create_app(
        {"developer_id": developer["id"], "name": "No Category", "listed_countries": ["US"]},
        headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)
    assert response.status_code == 400

    apps, meta = validate_paginated(api.list_apps(headers, {"developer_id": developer["id"]}))
    assert meta["total_count"] == 0


def test_patch_listing_updates_supplied_fields_and_advances_version(api):
    """PRD 3.3: "Listing metadata may be edited afterwards by its owner, supplying any of
    `name`, `category` or `listed_countries`; an edit made while the listing sits at
    `CHANGES_REQUESTED` also moves it `CHANGES_REQUESTED → DRAFT`, on the logic that the
    developer has begun responding to the reviewer's notes."
    PRD 2.4: "The `version` of a resource begins at 1 when the resource is created and
    advances by exactly 1 on every mutation of that resource, with `updated_at` refreshed
    at the same moment."

    Design: Corner/endpoints/corner_app_patch_updates_metadata_and_bumps_version
    """
    developer = create_verified_developer(
        api, legal_name="Patch Co", email="pc@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(
        api, developer["id"], name="Patchable", category="GAMES",
        listed_countries=["US", "DE"],
    )
    assert app["version"] == 1

    data = validate_success(
        api.patch_app(app["id"], {"name": "Patched", "category": "PRODUCTIVITY"}, headers)
    )
    assert data["name"] == "Patched"
    assert data["category"] == "PRODUCTIVITY"
    assert data["version"] == 2
    assert data["listed_countries"] == ["US", "DE"]
    assert data["status"] == "DRAFT"


def test_rejected_review_round_returns_listing_to_changes_requested(api):
    """PRD 3.3: "A successful submission moves the listing to `IN_REVIEW`, increments
    `review_round` by 1, and opens a `ReviewSubmission` in status `SUBMITTED` whose
    `app_id` names the listing, whose `round_number` equals the listing's `review_round`
    at that moment, and which carries the developer's `submitted_notes`."
    PRD 3.3: "A `REJECTED` decision moves the submission `IN_TRIAGE → REJECTED` and drives
    the listing `IN_REVIEW → CHANGES_REQUESTED`, returning the ball to the developer."

    Design: Difficulty/non_linear_state_machine/app_review_revision_cycle_returns_listing_to_in_review_round_two
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Loop Studios", email="l@loop.test", country_code="US"
    )
    app = create_draft_app(api, developer["id"], name="Loop", category="GAMES",
                           listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=500,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    submission = submit_for_review(api, app["id"], developer["id"], "round one")
    assert_review_submission(submission)
    assert submission["round_number"] == 1

    decided = decide_review(api, submission["id"], "REJECTED", "missing privacy policy")
    assert decided["status"] == "REJECTED"

    headers = make_developer_headers(developer["id"])
    app_after = validate_success(api.get_app(app["id"], headers))
    assert app_after["status"] == "CHANGES_REQUESTED"
    assert app_after["review_round"] == 1


def test_second_review_round_carries_round_number_two(api):
    """PRD 3.3: "an edit made while the listing sits at `CHANGES_REQUESTED` also moves it
    `CHANGES_REQUESTED → DRAFT`, on the logic that the developer has begun responding to
    the reviewer's notes."
    PRD 3.3: "Because `CHANGES_REQUESTED → IN_REVIEW` is available without limit, a
    listing may cycle through review rounds any number of times, each round producing its
    own submission record with its own increasing `round_number`."

    Design: Difficulty/non_linear_state_machine/app_review_revision_cycle_returns_listing_to_in_review_round_two
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Loop Studios", email="l@loop.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Loop", category="GAMES",
                           listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=500,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    first = submit_for_review(api, app["id"], developer["id"], "round one")
    decide_review(api, first["id"], "REJECTED", "missing privacy policy")

    edited = validate_success(api.patch_app(app["id"], {"name": "Loop Deluxe"}, headers))
    assert edited["status"] == "DRAFT", "an edit at CHANGES_REQUESTED returns the listing to DRAFT"

    second = submit_for_review(api, app["id"], developer["id"], "round two with privacy policy")
    assert second["round_number"] == 2

    app_after = validate_success(api.get_app(app["id"], headers))
    assert app_after["status"] == "IN_REVIEW"
    assert app_after["review_round"] == 2

    first_after = validate_success(api.get_review_submission(first["id"], headers))
    assert first_after["status"] == "REJECTED"


def test_decision_before_triage_is_rejected(api, agent_headers):
    """PRD 3.3: "Only a submission already in `IN_TRIAGE` may be decided; the decision
    carries an `outcome` of either `PASSED` or `REJECTED` together with a
    `decision_reason`, which is stored on the submission."
    PRD 2.8: "State legality. The target resource is in a state from which the requested
    transition is declared — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_review_decision_before_triage_returns_invalid_state
    """
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Skip Triage Co", email="sk@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Skip", category="PRODUCTIVITY",
                           listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="IAP", price_cents=199, currency="USD",
        country_code="US", effective_from="2026-07-01T00:00:00Z",
        effective_to="2027-07-01T00:00:00Z",
    )
    submission = submit_for_review(api, app["id"], developer["id"])

    response = api.decide_review_submission(
        submission["id"], {"outcome": "PASSED", "decision_reason": "looks fine"}, agent_headers
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409

    assert validate_success(
        api.get_review_submission(submission["id"], headers)
    )["status"] == "SUBMITTED"
    assert validate_success(api.get_app(app["id"], headers))["status"] == "IN_REVIEW"


def test_publish_refused_while_owning_account_is_not_active(api):
    """PRD 3.3: "Publication is the owning developer's move and takes an `APPROVED`
    listing to `LIVE`. It is refused with `ERR_DEVELOPER_NOT_ACTIVE` unless the owning
    account is in status `ACTIVE` at that moment — an approved listing belonging to a
    suspended developer cannot go on sale."

    Design: Difficulty/cross_entity_state_dependency/app_publish_gated_on_owning_developer_being_active
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_developer(
        api, legal_name="Gate Software", email="g@gate.test", country_code="US",
        tax_id_provided=True,
    )
    assert developer["status"] == "PENDING_VERIFICATION"
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Gatekeeper",
                           category="PRODUCTIVITY", listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="SUBSCRIPTION", price_cents=1200,
        currency="USD", country_code="US", billing_period_months=1,
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    take_app_through_review(api, app["id"], developer["id"])

    response = api.publish_app(app["id"], headers)
    validate_error(response, ApiErrorId.ERR_DEVELOPER_NOT_ACTIVE)
    assert response.status_code == 409
    assert validate_success(api.get_app(app["id"], headers))["status"] == "APPROVED"


def test_publish_succeeds_once_the_owning_account_is_verified(api, admin_headers):
    """PRD 3.2: "Verification moves an account `PENDING_VERIFICATION → ACTIVE`, and it is
    refused unless `tax_id_provided` is already true — an attempt against an account with
    no tax identification on file is rejected with `ERR_TAX_ID_REQUIRED`."
    PRD 3.3: "Publication is the owning developer's move and takes an `APPROVED` listing
    to `LIVE`."

    Design: Difficulty/cross_entity_state_dependency/app_publish_gated_on_owning_developer_being_active
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_developer(
        api, legal_name="Gate Software", email="g@gate.test", country_code="US",
        tax_id_provided=True,
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Gatekeeper",
                           category="PRODUCTIVITY", listed_countries=["US"])
    add_pricing_plan(
        api, app["id"], developer["id"], kind="SUBSCRIPTION", price_cents=1200,
        currency="USD", country_code="US", billing_period_months=1,
        effective_from="2026-07-01T00:00:00Z", effective_to="2027-07-01T00:00:00Z",
    )
    take_app_through_review(api, app["id"], developer["id"])

    first = api.publish_app(app["id"], headers)
    validate_error(first, ApiErrorId.ERR_DEVELOPER_NOT_ACTIVE)

    verified = validate_success(api.verify_developer(developer["id"], admin_headers))
    assert verified["status"] == "ACTIVE"

    published = validate_success(api.publish_app(app["id"], headers))
    assert published["status"] == "LIVE"


def test_publish_a_delisted_listing_is_rejected(api, officer_headers):
    """PRD 3.3: "Delisting is the end of the road and is reachable from `DRAFT`, from
    `APPROVED`, from `LIVE` and from `SUSPENDED` — from any state except `DELISTED`
    itself."
    PRD 2.8: "State legality. The target resource is in a state from which the requested
    transition is declared — otherwise `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/corner_publish_a_delisted_app_returns_invalid_state
    """
    developer = create_verified_developer(
        api, legal_name="Terminal Co", email="tc@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Terminal", category="GAMES",
                           listed_countries=["US"])
    validate_success(api.delist_app(app["id"], {"reason": "policy"}, officer_headers))

    response = api.publish_app(app["id"], headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)
    assert response.status_code == 409
    assert validate_success(api.get_app(app["id"], headers))["status"] == "DELISTED"


def test_delisting_retires_every_active_plan_and_adds_a_strike(api, officer_headers):
    """PRD 3.3: "Whatever the origin, the effects are identical: the listing becomes
    `DELISTED`; every pricing plan of that listing whose status is `ACTIVE` moves to
    `RETIRED`; the listing's `policy_strike_count` and the owning developer's
    `policy_strike_count` each increment by 1; and when the developer's resulting strike
    count reaches three or more while that developer is `ACTIVE`, the developer is carried
    `ACTIVE → SUSPENDED` with every one of that transition's own effects, including the
    freezing of payout lines and the recomputation of batch totals."

    Design: Corner/state_machines/corner_delist_retires_every_active_pricing_plan
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Retire Co", email="rc@x.test", country_code="US"
    )
    headers = make_developer_headers(developer["id"])
    app = create_draft_app(api, developer["id"], name="Retire", category="GAMES",
                           listed_countries=["US"])
    plan1 = add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=500,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-10T00:00:00Z",
    )
    plan2 = add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=600,
        currency="USD", country_code="US",
        effective_from="2026-07-11T00:00:00Z", effective_to="2026-08-11T00:00:00Z",
    )

    delisted = validate_success(api.delist_app(app["id"], {"reason": "malware detected"},
                                               officer_headers))
    assert delisted["status"] == "DELISTED"
    assert delisted["policy_strike_count"] == 1

    for plan in (plan1, plan2):
        after = validate_success(api.get_pricing_plan(plan["id"], headers))
        assert after["status"] == "RETIRED"

    developer_after = read_developer(api, developer["id"])
    assert developer_after["policy_strike_count"] == 1
    assert developer_after["status"] == "ACTIVE", "one strike is below the suspension threshold"


def test_delist_cascade_is_already_visible_in_the_delist_response(api, officer_headers,
                                                                  admin_headers):
    """PRD 2.9: "A cascade is never partial: when an operation is accepted, every
    downstream effect described for it in §3 is applied within the same request, and each
    mutated record has its own `updated_at` refreshed and its own `version` advanced."
    PRD 3.3: "the listing's `policy_strike_count` and the owning developer's
    `policy_strike_count` each increment by 1"

    Design: Corner/consistency_model/corner_delist_cascade_is_visible_in_the_same_response
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    configure_jurisdiction(api, "US", 0, True)
    developer = create_verified_developer(
        api, legal_name="Immediate Co", email="im@x.test", country_code="US"
    )
    app = create_draft_app(api, developer["id"], name="Immediate", category="GAMES",
                           listed_countries=["US"])
    plan = add_pricing_plan(
        api, app["id"], developer["id"], kind="ONE_TIME", price_cents=400,
        currency="USD", country_code="US",
        effective_from="2026-07-01T00:00:00Z", effective_to="2026-07-10T00:00:00Z",
    )

    response_data = validate_success(
        api.delist_app(app["id"], {"reason": "policy violation"}, officer_headers)
    )
    assert response_data["status"] == "DELISTED"
    assert response_data["policy_strike_count"] == 1

    assert validate_success(
        api.get_developer(developer["id"], admin_headers)
    )["policy_strike_count"] == 1
    assert validate_success(
        api.get_pricing_plan(plan["id"], make_developer_headers(developer["id"]))
    )["status"] == "RETIRED"
