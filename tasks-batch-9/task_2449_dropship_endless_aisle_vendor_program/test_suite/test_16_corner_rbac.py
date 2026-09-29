"""Role boundaries: the administrator's exclusive operations, denial of roles that
sit outside an endpoint's authorized list, the vendor-backed identity's scope, the
feed endpoint shared between a vendor and an operator, and the identity split
between the operator who records an integration test and the one who judges it.
"""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_serviceability_rule,
    create_active_item,
    create_active_vendor,
    create_draft_vendor,
    create_integration_test_payload,
    create_inventory_snapshot_payload,
    create_seeded_scorecard,
    evaluate_integration_test_payload,
    get_success_data,
    make_merchandise_manager_headers,
    make_vendor_ops_analyst_headers,
    make_vendor_user_headers,
    refresh_item,
    refresh_vendor,
    reset_clock,
    run_integration_rounds,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OPS = TEST_USERS["vendor_ops_analyst_headers"]
CARE = TEST_USERS["care_agent_headers"]


def _row_by_id(rows, row_id):
    """The one row of a list response carrying this id."""
    matches = [row for row in rows if row["id"] == row_id]
    assert matches, f"expected a row with id {row_id} in {rows}"
    return matches[0]


def _seeded_september_scorecard(api, vendor_id):
    """A DRAFT scorecard over an empty September, seeded to a PLATINUM composite."""
    return create_seeded_scorecard(
        api,
        vendor_id,
        20.0,
        9500,
        300,
        400,
        period_start="2026-09-01",
        period_end="2026-09-30",
    )


def test_platform_admin_publishes_a_scorecard_and_drives_the_logical_clock(api):
    """PRD §2.1: "`PlatformAdmin` is the break-glass role and appears in the authorized-role list of every endpoint; it is also the only role that may publish a scorecard onto a vendor or drive the logical clock."

    Both operations reserved to the administrator succeed for it: the publish lands
    the scorecard's tier and padding on the vendor and bumps the vendor's version,
    and the clock moves on request.

    Design: Corner/rbac/corner_platform_admin_performs_its_two_exclusive_operations
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="R1")
    set_clock(api, "2026-10-01T00:00:00Z")
    scorecard = _seeded_september_scorecard(api, vendor["id"])
    before = refresh_vendor(api, vendor["id"])

    published = validate_success(
        api.publish_scorecard(scorecard["id"], before["version"], ADMIN)
    )
    assert published["status"] == "PUBLISHED"
    assert published["published_at"].startswith("2026-10-01T00:00:00")
    assert published["tier"] == "PLATINUM"

    after = refresh_vendor(api, vendor["id"])
    assert after["performance_tier"] == "PLATINUM"
    assert after["promise_padding_days"] == 0
    assert after["version"] == before["version"] + 1

    validate_success(api.set_clock("2026-10-02T00:00:00Z", ADMIN))


def test_care_agent_cannot_publish_a_scorecard(api):
    """PRD §2.1: "A caller whose role is recognized but is not listed among the roles authorized for the requested endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Publication belongs to the administrator alone. A customer-facing agent asking
    for it is refused and the scorecard stays DRAFT with the vendor unrated.

    Design: Corner/rbac/corner_roles_outside_an_endpoints_list_cannot_call_it
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="R2A")
    set_clock(api, "2026-10-01T00:00:00Z")
    scorecard = _seeded_september_scorecard(api, vendor["id"])
    before = refresh_vendor(api, vendor["id"])

    response = api.publish_scorecard(scorecard["id"], before["version"], CARE)

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    rows, _ = validate_paginated(api.list_scorecards(vendor["id"], ADMIN))
    assert _row_by_id(rows, scorecard["id"])["status"] == "DRAFT"
    after = refresh_vendor(api, vendor["id"])
    assert after["performance_tier"] == "UNRATED"
    assert after["version"] == before["version"]


def test_merchandise_manager_cannot_certify_a_vendor(api):
    """PRD §2.11: "At the role level, certification belongs to `VendorOpsAnalyst` and activation belongs to `MerchandiseManager`; neither role can perform the other's step."

    The vendor is genuinely ready to be certified — four passed families in the
    current round and live coverage — so only the caller's role explains the
    refusal, and no certifying identity is recorded.

    Design: Corner/rbac/corner_roles_outside_an_endpoints_list_cannot_call_it
    """
    reset_clock(api)
    vendor = create_draft_vendor(api, suffix="R2B")
    run_integration_rounds(api, vendor["id"], suffix="R2B")
    add_serviceability_rule(api, vendor["id"])

    response = api.certify_vendor(
        vendor["id"], make_merchandise_manager_headers("mm-cert-attempt")
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value)
    after = refresh_vendor(api, vendor["id"])
    assert after["onboarding_status"] == "INTEGRATION_TESTING"
    assert after["certified_by_user_id"] is None


def test_vendor_user_cannot_read_another_vendors_offer(api):
    """PRD §2.1: "Any request in which a `VendorUser` touches a vendor other than itself is refused with `ERR_VENDOR_SCOPE_VIOLATION` (HTTP 403)."

    Two vendors carry the same SKU. The second vendor reading the first's offer is
    refused as out of scope rather than as missing, while each vendor reads its own
    offer on the very same endpoint and sees its own derived unit cost.

    Design: Corner/rbac/corner_vendor_user_cannot_read_another_vendors_offer
    """
    reset_clock(api)
    vendor_one = create_active_vendor(api, suffix="R3A")
    offer_one = create_active_item(api, vendor_one["id"], sku="SKU-CHAIR-1")
    vendor_two = create_active_vendor(
        api,
        suffix="R3B",
        rules=[{"transit_days": 2, "cutoff_hour_utc": 20, "surcharge_cents": 500}],
        cost_model="WHOLESALE",
        wholesale_discount_bps=1000,
        inventory_refresh_cadence_minutes=120,
        safety_buffer_units=2,
        oversell_grace_units=3,
        default_lead_time_days=5,
    )
    offer_two = create_active_item(
        api,
        vendor_two["id"],
        sku="SKU-CHAIR-1",
        unit_wholesale_cost_cents=19000,
        lead_time_days=5,
        reverse_freight_owner="VENDOR",
        restock_policy="RETAILER_RESTOCK",
    )

    crossed = api.get_item(offer_one["id"], make_vendor_user_headers(vendor_two["id"]))
    validate_error(crossed, ApiErrorId.ERR_VENDOR_SCOPE_VIOLATION.value)

    own = validate_success(
        api.get_item(offer_one["id"], make_vendor_user_headers(vendor_one["id"]))
    )
    assert own["id"] == offer_one["id"]
    assert own["unit_cost_cents"] == 21249

    peer = validate_success(
        api.get_item(offer_two["id"], make_vendor_user_headers(vendor_two["id"]))
    )
    assert peer["id"] == offer_two["id"]
    assert peer["unit_cost_cents"] == 17100


def test_inventory_feed_is_shared_between_the_vendor_and_the_ops_analyst(api):
    """PRD §3.4: "A `VendorUser` posting for its own offer, or an analyst or administrator keying a correction, supplies `on_hand_units` — the units the vendor reports on hand, never negative — an `effective_from` instant that begins the window inclusively, an optional `effective_to` instant that ends it exclusively, `feed_sequence`, the 1-based per-offer counter of feed messages ordered by `created_at` ascending and never below 1, and the `expected_item_version` demanded by §2.9."

    The vendor posts its own refresh and an operator keys the next one by hand.
    Both are accepted, each bumps the offer's version, and the later window governs
    the offer's trusted on-hand figure.

    Design: Corner/rbac/corner_inventory_feed_is_shared_between_the_vendor_and_the_ops_analyst
    """
    reset_clock(api)
    vendor = create_active_vendor(api, suffix="R4")
    offer = create_active_item(api, vendor["id"])
    set_clock(api, "2026-08-03T09:00:00Z")

    before = refresh_item(api, offer["id"])
    validate_success(
        api.create_inventory_snapshot(
            offer["id"],
            create_inventory_snapshot_payload(
                before["version"],
                on_hand_units=40,
                effective_from="2026-08-03T09:00:00Z",
                feed_sequence=1,
            ),
            make_vendor_user_headers(vendor["id"]),
        ),
        201,
    )
    after_vendor_post = refresh_item(api, offer["id"])
    assert after_vendor_post["version"] == before["version"] + 1

    # The operator keys the correction as its window opens: a feed message whose
    # window has not begun yet leaves the offer with no governing snapshot, which
    # §3.4 answers by auto-suppressing it for ZERO_AVAILABILITY.
    set_clock(api, "2026-08-03T09:30:00Z")

    analyst_snapshot = validate_success(
        api.create_inventory_snapshot(
            offer["id"],
            create_inventory_snapshot_payload(
                after_vendor_post["version"],
                on_hand_units=25,
                effective_from="2026-08-03T09:30:00Z",
                feed_sequence=2,
                source="MANUAL_ADJUST",
            ),
            make_vendor_ops_analyst_headers("ops-feed-operator"),
        ),
        201,
    )
    assert analyst_snapshot["source"] == "MANUAL_ADJUST"
    assert analyst_snapshot["status"] == "ACTIVE"
    after_analyst_post = refresh_item(api, offer["id"])
    assert after_analyst_post["version"] == after_vendor_post["version"] + 1

    set_clock(api, "2026-08-03T10:00:00Z")
    live = refresh_item(api, offer["id"])
    assert live["inventory_is_stale"] is False
    assert live["effective_on_hand_units"] == 25
    assert live["available_units"] == 20


def test_the_operator_who_recorded_an_integration_test_cannot_evaluate_it(api):
    """PRD §2.6: "The `X-User-ID` activating a vendor differs from that vendor's `certified_by_user_id`, and the `X-User-ID` evaluating an integration test differs from the `X-User-ID` that recorded that test. Otherwise `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Applies to vendor activation and integration test evaluation."

    Both halves belong to the same role, so the role check passes and only the
    identity comparison can refuse. The recorder is blocked and the run stays
    PENDING; a second analyst identity then evaluates the identical payload.

    Design: Corner/rbac/corner_the_operator_who_recorded_an_integration_test_cannot_evaluate_it
    """
    reset_clock(api)
    vendor = create_draft_vendor(api, suffix="R5")
    get_success_data(api.begin_integration(vendor["id"], OPS))
    recorder = make_vendor_ops_analyst_headers("ops-recorder-VS")
    run = get_success_data(
        api.record_integration_test(
            vendor["id"], create_integration_test_payload("CATALOG"), recorder
        )
    )

    blocked = api.evaluate_integration_test(
        run["id"], evaluate_integration_test_payload("PASS"), recorder
    )
    validate_error(blocked, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    rows, _ = validate_paginated(api.list_integration_tests(vendor["id"], ADMIN))
    assert _row_by_id(rows, run["id"])["status"] == "PENDING"

    evaluated = validate_success(
        api.evaluate_integration_test(
            run["id"],
            evaluate_integration_test_payload("PASS"),
            make_vendor_ops_analyst_headers("ops-evaluator-VS"),
        )
    )
    assert evaluated["status"] == "PASSED"
    assert evaluated["evaluated_by_user_id"] == "ops-evaluator-VS"
    assert refresh_vendor(api, vendor["id"])["onboarding_status"] == "INTEGRATION_TESTING"
