"""Optimistic concurrency, RBAC / segregation-of-duties, entity defaults and
computed fields, not-found and required-field validation, and filtered listing.

Covers the Corner queue sections cross_cutting_complexity_layers, rbac, entities,
and endpoints.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    TEST_USERS, make_analyst_headers, make_officer_headers, make_field_tech_headers,
    fixtures as fx,
)

CARE = TEST_USERS["customer_care_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
BILLING = TEST_USERS["billing_headers"]
ANY_READER = TEST_USERS["program_admin_headers"]
ALL_ZERO_UUID = "00000000-0000-0000-0000-000000000000"


# =====================================================================
# Corner — cross_cutting_complexity_layers / OCC
# =====================================================================
def test_invoice_payment_stale_version_rejected(api):
    """PRD §2.7: "If the invoice's current `version` has advanced beyond that value —
    because a prior payment already updated the running total — the payment is rejected
    with `ERR_STALE_VERSION` (HTTP 412), preventing the caller from posting a payment
    computed against a superseded balance."

    Design: Corner/cross_cutting_complexity_layers/occ_invoice_payment_stale_version_conflict
    """
    ctx = fx.setup_active_subscription(api, homes_passed=100, price=6000)
    invoice = fx.generate_invoice(api, ctx["subscription"]["id"])
    v1 = invoice["version"]
    validate_success(api.record_payment(
        invoice["id"], {"amount_cents": 1000, "expected_invoice_version": v1}, BILLING))
    # Second payment still carrying the pre-payment version is stale.
    validate_error(
        api.record_payment(invoice["id"], {"amount_cents": 1000, "expected_invoice_version": v1}, BILLING),
        ApiErrorId.ERR_STALE_VERSION)
    fetched = validate_success(api.get_invoice(invoice["id"], ANY_READER))
    assert fetched["amount_paid_cents"] == 1000, "the stale second payment must not be applied"


def test_grant_claim_create_stale_grant_version_rejected(api):
    """PRD §2.7: "a create carrying a `version` that no longer matches the grant's
    current `version` reflects a view taken before another claim advanced the grant,
    and it is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_grant_claim_create_stale_grant_conflict
    """
    grant = fx.create_grant(api)
    g_v = grant["version"]
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    analyst = make_analyst_headers("analyst-1")
    validate_success(api.create_grant_claim(
        grant["id"],
        {"claim_period_start": "2026-06-01T00:00:00Z", "claim_period_end": "2026-07-01T00:00:00Z",
         "service_area_ids": [area["id"]], "expected_grant_version": g_v}, analyst),
        expected_status=201)
    # Second create still carrying the pre-advance grant version is stale.
    validate_error(
        api.create_grant_claim(
            grant["id"],
            {"claim_period_start": "2026-07-01T00:00:00Z", "claim_period_end": "2026-08-01T00:00:00Z",
             "service_area_ids": [area["id"]], "expected_grant_version": g_v}, analyst),
        ApiErrorId.ERR_STALE_VERSION)


# =====================================================================
# Corner — rbac
# =====================================================================
def test_customercare_cannot_create_grant(api):
    """PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`."
    PRD §3.1: "Program setup is the exclusive province of the `ProgramAdmin`."

    Design: Corner/rbac/customercare_cannot_create_grant_unauthorized
    """
    validate_error(
        api.create_grant(
            {"funding_source": "BEAD", "program_name": "Bad", "award_amount_cents": 1000,
             "match_required_pct": 25, "take_rate_milestone_pct": 40}, CARE),
        ApiErrorId.ERR_UNAUTHORIZED)


def test_sod_approver_equals_submitter_rejected(api):
    """PRD §3.7: "An officer then decides the `SUBMITTED` claim, and the acting
    `X-User-ID` must differ from `submitted_by`, failing otherwise with
    `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/sod_approver_equals_submitter_rejected
    """
    grant = fx.create_grant(api)
    g_v = grant["version"]
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    claim = fx.create_claim(api, grant["id"], [area["id"]], g_v)
    fx.submit_claim(api, claim["id"], analyst_user_id="analyst-1")
    # Officer role but the same X-User-ID (analyst-1) that submitted.
    validate_error(api.approve_grant_claim(claim["id"], make_officer_headers("analyst-1")),
                   ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    fetched = validate_success(api.get_grant_claim(claim["id"], ANY_READER))
    assert fetched["status"] == "SUBMITTED"


def test_fieldtech_completing_others_install_unauthorized(api):
    """PRD §2.1: "Ownership checks on install completion compare the install order's
    `technician_id` to `X-User-ID`, so a field technician may only complete installs
    assigned to them."
    PRD §3.3: "completion is allowed only when the acting `X-User-ID` equals the
    order's `technician_id` and the subscription's `service_status` is still
    `PENDING_INSTALL`."

    Design: Corner/rbac/fieldtech_complete_wrong_technician_unauthorized
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    plan = fx.create_plan(api)
    subscriber = fx.create_subscriber(api, area["id"])
    subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    tech_a = fx.create_technician(api, name="Tech A")
    tech_b = fx.create_technician(api, name="Tech B")
    io = fx.schedule_install(api, subscription["id"], tech_a["id"], "2026-06-01T09:00:00Z")
    validate_error(api.complete_install_order(io["id"], make_field_tech_headers(tech_b["id"])),
                   ApiErrorId.ERR_UNAUTHORIZED)
    fetched = validate_success(api.get_install_order(io["id"], ANY_READER))
    assert fetched["status"] == "SCHEDULED"


# =====================================================================
# Corner — entities
# =====================================================================
def test_subscriber_not_found_returns_404(api):
    """PRD §2.5: "Each entity has its own not-found code — ... `ERR_SUBSCRIBER_NOT_FOUND`"

    Design: Corner/entities/subscriber_not_found_returns_404
    """
    validate_error(api.get_subscriber(ALL_ZERO_UUID, CARE), ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND)


def test_subscription_create_missing_plan_id_validation(api):
    """PRD §2.5: "A request whose body omits a required field, carries a value of the
    wrong type, or supplies an invalid enumeration value is rejected with
    `ERR_VALIDATION`."
    PRD §3.2: "The same operator creates a subscription by supplying the
    `subscriber_id`, the `plan_id`, and the `service_area_id`."

    Design: Corner/entities/subscription_create_missing_required_field
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    subscriber = fx.create_subscriber(api, area["id"])
    validate_error(
        api.create_subscription(
            {"subscriber_id": subscriber["id"], "service_area_id": area["id"]}, CARE),
        ApiErrorId.ERR_VALIDATION)


def test_service_area_default_fiber_ready_false(api):
    """PRD §3.1: "a `homes_passed` count that serves as the take-rate denominator, and
    a `fiber_ready` flag defaulting to false. A newly created area is `PLANNED`."

    Design: Corner/entities/service_area_default_fiber_ready_false
    """
    grant = fx.create_grant(api)
    created = validate_success(
        api.create_service_area(
            {"grant_id": grant["id"], "name": "Area X", "census_block_group": "010010009999",
             "homes_passed": 50}, ANY_READER),
        expected_status=201)
    assert created["fiber_ready"] is False
    assert created["status"] == "PLANNED"


def test_subscription_price_snapshot_computed(api):
    """PRD §3.2: "At creation the subscription snapshots the plan's price into its own
    `monthly_price_cents`, so later plan repricing never disturbs an existing
    subscription."

    Design: Corner/entities/subscription_price_snapshot_computed
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    plan = fx.create_plan(api, monthly_price_cents=6000)
    subscriber = fx.create_subscriber(api, area["id"])
    created = validate_success(
        api.create_subscription(
            {"subscriber_id": subscriber["id"], "plan_id": plan["id"], "service_area_id": area["id"]}, CARE),
        expected_status=201)
    assert created["monthly_price_cents"] == 6000
    assert created["service_status"] == "PENDING_INSTALL"
    assert created["billing_status"] == "CURRENT"


# =====================================================================
# Corner — endpoints
# =====================================================================
def test_list_subscriptions_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_subscriptions_filtered_by_subscriber
    """
    grant = fx.create_grant(api)
    area = fx.create_serviceable_area(api, grant["id"], homes_passed=100)
    plan = fx.create_plan(api)
    subscriber = fx.create_subscriber(api, area["id"])
    subscription = fx.create_pending_subscription(api, subscriber["id"], plan["id"], area["id"])
    data, meta = validate_paginated(
        api.list_subscriptions(CARE, params={"subscriber_id": subscriber["id"]}))
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert any(s["id"] == subscription["id"] for s in data), \
        "the created subscription must appear in the listing"
