"""Coverage/rider/event-profile selection validations and computed rating fields.

Translates queue B `validations` instances guarding coverage add and event profiles, plus
the computed-field `entities` instances for rider/coverage rating at bind.
"""
from test_helpers import (
    validate_success, validate_error, make_policyholder_headers, TEST_USERS,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.constants import RANDOM_UUID

_admin = TEST_USERS["admin_headers"]
_uw = TEST_USERS["underwriter_headers"]
_ph = make_policyholder_headers("ph-1")


def test_single_event_second_event_profile_rejected(api):
    """PRD §3.2: "Because a `SINGLE_EVENT` policy covers exactly one event, attempting to
    add a second event profile to such a policy is rejected with
    `ERR_SINGLE_EVENT_MULTIPLE_PROFILES`".

    Design: Corner/validations/single_event_second_event_profile_rejected
    """
    venue = FX.create_venue()
    policy = FX.create_quoted_policy(policy_form="SINGLE_EVENT")
    FX.add_event_profile(policy["id"], venue["id"], event_name="First")
    res = api.create_event_profile(policy["id"], F.event_profile_payload(
        venue["id"], event_name="Second", expected_attendance=80,
        event_start_at="2026-09-01T18:00:00Z", event_end_at="2026-09-01T23:00:00Z"), _ph)
    validate_error(res, "ERR_SINGLE_EVENT_MULTIPLE_PROFILES", 422)


def test_event_profile_non_venue_vendor_rejected(api):
    """PRD §3.2: "the `venue_vendor_id` must resolve to an existing vendor, and that
    vendor's `category` must be `VENUE`; a non-venue reference is rejected with
    `ERR_VENUE_VENDOR_REQUIRED`."

    Design: Corner/validations/event_profile_non_venue_vendor_rejected
    """
    caterer = FX.create_caterer()
    policy = FX.create_quoted_policy()
    res = api.create_event_profile(policy["id"], F.event_profile_payload(
        caterer["id"], event_name="Smith Wedding"), _ph)
    validate_error(res, "ERR_VENUE_VENDOR_REQUIRED", 422)


def test_duplicate_coverage_same_type_tier_rejected(api):
    """PRD §3.3: "a policy may hold at most one coverage line per product, identified by
    its `coverage_type` and `tier` combination; a duplicate add is rejected with
    `ERR_DUPLICATE_COVERAGE`."

    Design: Corner/validations/duplicate_coverage_same_type_tier_rejected
    """
    product = FX.create_cancellation_product()
    policy = FX.create_quoted_policy()
    FX.add_coverage(policy["id"], product["id"])
    res = api.create_coverage(policy["id"], F.coverage_payload(product["id"]), _ph)
    validate_error(res, "ERR_DUPLICATE_COVERAGE", 409)


def test_protected_vendor_on_liability_coverage_rejected(api):
    """PRD §3.3: "A `protected_vendor_id` may be supplied only when the product's
    `coverage_type` is `CANCELLATION`; supplying it on any other coverage type is rejected
    with `ERR_PROTECTED_VENDOR_NOT_ALLOWED`."

    Design: Corner/validations/protected_vendor_on_liability_coverage_rejected
    """
    product = FX.create_liability_product()
    caterer = FX.create_caterer()
    policy = FX.create_quoted_policy()
    res = api.create_coverage(policy["id"], F.coverage_payload(
        product["id"], protected_vendor_id=caterer["id"]), _ph)
    validate_error(res, "ERR_PROTECTED_VENDOR_NOT_ALLOWED", 422)


def test_add_retired_product_coverage_rejected(api):
    """PRD §3.3: "A `RETIRED` product cannot be added and yields `ERR_PRODUCT_RETIRED`."

    Design: Corner/validations/add_retired_product_coverage_rejected
    """
    product = FX.create_cancellation_product()
    api.retire_coverage_product(product["id"], _admin)
    policy = FX.create_quoted_policy()
    res = api.create_coverage(policy["id"], F.coverage_payload(product["id"]), _ph)
    validate_error(res, "ERR_PRODUCT_RETIRED", 422)


def test_reference_not_found_unknown_coverage_product(api):
    """PRD §3.3: "The referenced product must exist, or the request is rejected with
    `ERR_REFERENCE_NOT_FOUND`."

    Design: Corner/validations/reference_not_found_unknown_coverage_product
    """
    policy = FX.create_quoted_policy()
    res = api.create_coverage(policy["id"], F.coverage_payload(RANDOM_UUID), _ph)
    validate_error(res, "ERR_REFERENCE_NOT_FOUND", 404)


def test_coverage_rated_premium_computed_input_ignored(api):
    """PRD §3.4: "A coverage line's `rated_premium_cents` is the product's
    `base_premium_cents` plus its `per_guest_premium_cents` multiplied by that total
    attendance."
    PRD §3.4: "Every `SELECTED` coverage line is rated and flipped to `ACTIVE`".

    Design: Corner/entities/coverage_rated_premium_computed_input_ignored
    """
    ctx = FX.setup_quoted_single_event(attendance=150)
    FX.bind_policy(ctx["policy"]["id"])
    coverage = validate_success(
        api.get_coverage(ctx["policy"]["id"], ctx["coverage"]["id"], _uw), 200)
    assert coverage["rated_premium_cents"] == 65000
    assert coverage["status"] == "ACTIVE"


def test_rider_premium_clamp_ceiling_on_high_value(api):
    """PRD §3.3: "The system multiplies the rider's `scheduled_value_cents` by the rider
    rate of 1.5 percent and rounds that product up to the next whole cent; this rounded-up
    figure is then clamped so that it is never below a floor of 2,500 cents and never above
    a ceiling of 50,000 cents."
    PRD §3.3: "becomes `ACTIVE` once the policy is bound".

    Design: Corner/entities/rider_premium_clamp_ceiling_on_high_value
    """
    product = FX.create_cancellation_product()
    venue = FX.create_venue()
    policy = FX.create_quoted_policy()
    FX.add_event_profile(policy["id"], venue["id"], expected_attendance=150)
    FX.add_coverage(policy["id"], product["id"])
    rider = FX.add_rider(policy["id"], "GIFTS", 5000000)
    FX.bind_policy(policy["id"])
    riders = validate_success(api.list_riders(policy["id"], _uw), 200)
    rider_after = next(r for r in riders if r["id"] == rider["id"])
    assert rider_after["rider_premium_cents"] == 50000
    assert rider_after["status"] == "ACTIVE"
