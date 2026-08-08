"""Role-based access denials, household-membership enforcement, unauthenticated
reads, and optimistic-concurrency on subscription plan changes.
"""
from test_helpers import (
    validate_success, validate_error,
    make_household_owner_headers, make_household_member_headers,
    new_manufacturer, new_household, new_owner, add_member, new_subscription,
    create_recall_notice_payload, create_product_payload, create_subscription_payload,
)


def test_household_owner_cannot_publish_recall(api):
    """PRD 2.1: "When the headers are present and well-formed but the named role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/household_owner_cannot_publish_recall_unauthorized
    """
    mfr = new_manufacturer()
    hh = new_household()
    owner = new_owner(hh["id"])
    payload = create_recall_notice_payload(mfr["id"], affected_model_number="Z",
                                           serial_range_start=1, serial_range_end=2,
                                           severity="LOW", remedy_type="REPAIR",
                                           effective_from="2025-01-01T00:00:00Z",
                                           effective_to="2025-02-01T00:00:00Z")
    res = api.create_recall_notice(payload, make_household_owner_headers(owner["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_member_cannot_create_subscription(api):
    """PRD 2.1: "`HouseholdOwner` is the single `OWNER`-role member of a household and
    additionally manages subscriptions, membership, the registry, and match dismissals;
    `HouseholdMember` is any `ADULT` or `MINOR` member and may register products, file
    and manage claims, and acknowledge alerts."

    Design: Corner/rbac/member_cannot_create_subscription_unauthorized
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    adult = add_member(hh["id"], owner["id"], role="ADULT")
    payload = create_subscription_payload(tier="BASIC", period_start="2025-01-01T00:00:00Z",
                                          period_end="2026-01-01T00:00:00Z")
    res = api.create_subscription(hh["id"], payload, make_household_member_headers(adult["id"]))
    validate_error(res, "ERR_UNAUTHORIZED")


def test_owner_registering_foreign_household_product_rejected(api):
    """PRD 2.1: "If an entity-backed household principal acts on a resource whose
    household they do not belong to, the request is rejected with
    `ERR_NOT_HOUSEHOLD_MEMBER`."

    Design: Corner/rbac/not_household_member_registering_foreign_product_rejected
    """
    mfr = new_manufacturer()
    hh_a = new_household(display_name="A")
    owner_a = new_owner(hh_a["id"])
    hh_b = new_household(display_name="B")
    payload = create_product_payload(hh_b["id"], mfr["id"], model_number="F-1",
                                     serial_number=1, purchase_price_cents=100,
                                     warranty_months=12)
    res = api.create_product(payload, make_household_owner_headers(owner_a["id"]))
    validate_error(res, "ERR_NOT_HOUSEHOLD_MEMBER")


def test_get_household_without_headers_unauthenticated(api):
    """PRD 2.1: "When either header is missing or malformed on an endpoint that requires
    authentication, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/get_household_unauthenticated_missing_headers
    """
    hh = new_household()
    res = api.get_household(hh["id"], {})
    validate_error(res, "ERR_UNAUTHENTICATED")


def test_change_plan_stale_version_conflict(api):
    """PRD 2.5: "If that value does not match the subscription's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412) and the tier is left
    unchanged."
    PRD 2.5: "A successful plan change sets the new `tier` and increments the
    subscription's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/change_plan_stale_subscription_version_conflict
    """
    hh = new_household()
    owner = new_owner(hh["id"])
    sub = new_subscription(hh["id"], owner["id"], tier="BASIC")
    observed_version = sub["version"]
    headers = make_household_owner_headers(owner["id"])

    first = validate_success(api.change_plan(
        sub["id"], {"tier": "PLUS", "expected_subscription_version": observed_version}, headers), 200)
    assert first["tier"] == "PLUS"
    assert first["version"] == observed_version + 1

    second = api.change_plan(
        sub["id"], {"tier": "PREMIUM", "expected_subscription_version": observed_version}, headers)
    validate_error(second, "ERR_STALE_VERSION")
