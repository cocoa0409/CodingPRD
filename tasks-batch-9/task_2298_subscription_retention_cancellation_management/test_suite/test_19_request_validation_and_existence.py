"""Bad requests are refused by the right band, and nothing is left behind.

An unresolvable path id, a missing required field, an out-of-range enum or integer and an
unresolvable body foreign key each produce their own typed error, and in every case no
row is persisted and no counter moves.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    api_client,
    create_payment_method_payload,
    create_subscriber_payload,
    create_subscription_payload,
    new_core_plan,
    new_payment_method,
    new_subscriber,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _subscriber_with_a_card():
    set_clock("2026-01-10")
    subscriber = new_subscriber(acquisition_channel="SEARCH")
    return subscriber, new_payment_method(subscriber["id"])


class TestPathExistence:

    def test_reading_an_unknown_subscription_id_is_a_typed_404(self):
        """A well-formed UUID matching no row is a not-found, not an empty 200.

        PRD §2.5: "Where a path does contain more than one identifier, identifiers are
        resolved strictly left to right, and the request fails on the **first**
        unresolvable segment with that segment's own not-found code."

        Design: Corner/entities/subscription_read_with_unknown_id_returns_not_found
        """
        set_clock("2026-01-10")
        validate_error(api_client.get_subscription(NON_EXISTENT_UUID, ADMIN),
                       ApiErrorId.ERR_SUBSCRIPTION_NOT_FOUND, 404)


class TestRequestSchema:

    def test_a_signup_without_frequency_weeks_is_rejected_rather_than_defaulted(self):
        """frequency_weeks has no default, so its absence is a 400 and no row appears.

        PRD §2.6: "**Request schema** — required fields present, enum members in range,
        integers non-negative, datetimes well-formed ISO 8601, and `cohort_month`
        matching a four-digit year, a hyphen and a two-digit month in the range 01
        through 12 (`ERR_INVALID_REQUEST`, 400). This band applies to every write
        endpoint."

        Design: Corner/entities/subscription_create_missing_required_frequency_weeks_returns_invalid_request
        """
        subscriber, card = _subscriber_with_a_card()
        plan = new_core_plan()

        payload = create_subscription_payload(
            subscriber["id"], plan["id"], card["id"], drop_keys=("frequency_weeks",))
        validate_error(api_client.create_subscription(payload, ADMIN),
                       ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(
            api_client.list_subscriptions(ADMIN, params={"subscriber_id": subscriber["id"]}))
        assert meta["total_count"] == 0
        assert validate_success(api_client.get_plan(plan["id"], ADMIN),
                                200)["active_subscription_count"] == 0

    def test_an_unknown_enum_member_and_an_out_of_range_month_are_both_invalid_requests(self):
        """An acquisition channel outside the five members and an exp_month of 13 both fail.

        PRD §3.2: "A `PlatformAdmin` registers a **Subscriber** with an `email` unique
        across subscribers and an `acquisition_channel`, one of `PAID_SOCIAL`, `SEARCH`,
        `AFFILIATE`, `ORGANIC` or `REFERRAL`." and "A **payment method** is attached by
        the subscriber (or by a `PlatformAdmin` on their behalf) with a `subscriber_id`,
        a `card_last4` that must be exactly four digits, an `exp_month` between 1 and 12
        inclusive, an `exp_year` of 2020 or later, and a `network` of `VISA`,
        `MASTERCARD`, `AMEX` or `DISCOVER`."

        Design: Corner/entities/enum_and_range_constraints_reject_invalid_enum_and_out_of_range_month
        """
        set_clock("2026-01-10")
        subscriber = new_subscriber(acquisition_channel="SEARCH")

        validate_error(
            api_client.create_subscriber(
                create_subscriber_payload(acquisition_channel="TIKTOK"), ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST, 400)

        validate_error(
            api_client.create_payment_method(
                create_payment_method_payload(subscriber["id"], exp_month=13), ADMIN),
            ApiErrorId.ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(
            api_client.list_payment_methods(ADMIN, params={"subscriber_id": subscriber["id"]}))
        assert meta["total_count"] == 0


class TestBodyForeignKeys:

    def test_an_unknown_plan_id_is_a_404_even_when_a_domain_rule_also_fails(self):
        """Foreign-key existence outranks the negative-option disclosure rule.

        PRD §2.6: "**Body foreign-key existence** — every foreign key supplied in the
        body resolves; this covers `subscriber_id`, `plan_id`, `payment_method_id`,
        `subscription_id`, `target_plan_id` and `winback_target_id` (404 codes per
        §2.5)."

        Design: Corner/entities/subscription_create_with_unknown_plan_id_returns_not_found
        """
        subscriber, card = _subscriber_with_a_card()

        payload = create_subscription_payload(
            subscriber["id"], NON_EXISTENT_UUID, card["id"], disclosure_acknowledged=False)
        validate_error(api_client.create_subscription(payload, ADMIN),
                       ApiErrorId.ERR_PLAN_NOT_FOUND, 404)

        _, meta = validate_paginated(
            api_client.list_subscriptions(ADMIN, params={"subscriber_id": subscriber["id"]}))
        assert meta["total_count"] == 0

    def test_a_card_for_an_unknown_subscriber_is_refused_and_no_orphan_row_appears(self):
        """The parent must exist before a payment method can hang off it.

        PRD §2.5: "Body-borne foreign keys are resolved after the path and before any
        business rule: `subscriber_id` failures yield `ERR_SUBSCRIBER_NOT_FOUND`,
        `plan_id`, `target_plan_id` and `downgrade_target_plan_id` failures yield
        `ERR_PLAN_NOT_FOUND`, `subscription_id` yields `ERR_SUBSCRIPTION_NOT_FOUND`,
        `payment_method_id` yields `ERR_PAYMENT_METHOD_NOT_FOUND`, `invoice_id` yields
        `ERR_INVOICE_NOT_FOUND`, and `winback_target_id` yields
        `ERR_WINBACK_TARGET_NOT_FOUND`."

        Design: Corner/entities/payment_method_create_with_unknown_subscriber_returns_not_found
        """
        set_clock("2026-01-10")
        validate_error(
            api_client.create_payment_method(
                create_payment_method_payload(NON_EXISTENT_UUID), ADMIN),
            ApiErrorId.ERR_SUBSCRIBER_NOT_FOUND, 404)

        _, meta = validate_paginated(api_client.list_payment_methods(ADMIN))
        assert meta["total_count"] == 0
