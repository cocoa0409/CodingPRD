"""Policy intake: creation defaults, required fields, enums, FK existence,
uniqueness, and the auto-generated compensation disclosure."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_policy,
    create_carrier,
    create_policy,
    create_policy_payload,
    create_producer,
    create_product,
    create_schedule,
    get_policy_disclosure,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def _producer_product():
    producer = create_producer()
    carrier = create_carrier()
    product = create_product(carrier["id"])
    return producer, carrier, product


class TestPolicyCreation:
    def test_new_policy_starts_quoted(self):
        """PRD §3.3: "A new policy starts in `QUOTED` status, with
        `cancel_effective_date` and `cancelled_at` null until a cancellation
        occurs."

        Design: Corner/state_machines/policy_initial_state_quoted
        """
        producer, _, product = _producer_product()
        policy = validate_success(
            api_client.create_policy(
                create_policy_payload(
                    product["id"], producer["id"], policy_number="P-S1C"
                ),
                ADMIN,
            ),
            201,
        )
        assert_policy(policy)
        assert policy["status"] == "QUOTED"
        assert policy["cancel_effective_date"] is None
        assert policy["cancelled_at"] is None

    def test_missing_required_premium_rejected(self):
        """PRD §2.9: "10. **Request shape** — required fields present, amounts
        positive integers, enum values valid, and `cancel_effective_date` not
        earlier than the policy's `effective_date`, else
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "quotes a **Policy** by supplying a `policy_number`, the
        `product_id` being sold, the `producer_id` of the writing agent, the
        `insured_name`, the `billing_type` (`AGENCY_BILL` or `DIRECT_BILL`),
        the `premium_annual_cents` (a positive whole-cent amount), and the
        `effective_date` on which coverage starts."

        Design: Corner/entities/policy_create_missing_required_returns_invalid_request
        """
        producer, _, product = _producer_product()
        payload = create_policy_payload(
            product["id"], producer["id"], policy_number="P-D3"
        )
        del payload["premium_annual_cents"]
        res = api_client.create_policy(payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_invalid_billing_type_enum_rejected(self):
        """PRD §2.9: "10. **Request shape** — required fields present, amounts
        positive integers, enum values valid, and `cancel_effective_date` not
        earlier than the policy's `effective_date`, else
        `ERR_INVALID_REQUEST`."
        PRD §3.3: "the `billing_type` (`AGENCY_BILL` or `DIRECT_BILL`)".

        Design: Corner/entities/policy_create_invalid_enum_rejected
        """
        producer, _, product = _producer_product()
        payload = create_policy_payload(
            product["id"],
            producer["id"],
            policy_number="P-D4",
            billing_type="MONTHLY",
        )
        res = api_client.create_policy(payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_get_nonexistent_policy_not_found(self):
        """PRD §2.9: "3. **Existence** — path identifiers validated
        left-to-right, then body foreign-key references such as `product_id`,
        `producer_id`, `upline_producer_id`, and `carrier_id`, else
        `ERR_NOT_FOUND`."

        Design: Corner/entities/get_nonexistent_policy_returns_not_found
        """
        res = api_client.get_policy(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_bogus_product_reference_not_found(self):
        """PRD §2.10: "Body-supplied references to other resources are
        validated after the path identifiers, under the same error code."

        Design: Corner/entities/policy_create_with_bogus_product_returns_not_found
        """
        producer = create_producer(name="FK F", license_number="LIC-D5")
        payload = create_policy_payload(
            NON_EXISTENT_UUID, producer["id"], policy_number="P-D5"
        )
        res = api_client.create_policy(payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_duplicate_policy_number_rejected(self):
        """PRD §3.3: "Policy numbers are unique across the book — carrier
        statement lines later match on this exact string — and a duplicate is
        rejected with `ERR_POLICY_NUMBER_EXISTS`."

        Design: Corner/entities/duplicate_policy_number_rejected
        """
        producer, _, product = _producer_product()
        create_policy(product["id"], producer["id"], policy_number="P-D6")
        res = api_client.create_policy(
            create_policy_payload(
                product["id"],
                producer["id"],
                policy_number="P-D6",
                insured_name="I2",
                premium_annual_cents=1000000,
            ),
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_NUMBER_EXISTS, expected_status=409)


class TestProductUniqueness:
    def test_duplicate_product_code_per_carrier_rejected(self):
        """PRD §3.2: "The product code must be unique within its carrier;
        reusing a code already present on the same carrier is rejected with
        `ERR_PRODUCT_CODE_EXISTS`."

        Design: Corner/entities/duplicate_product_code_per_carrier_rejected
        """
        carrier = create_carrier(name="Carrier D8", carrier_code="CD8")
        create_product(carrier["id"], product_code="PD8", name="First")
        res = api_client.create_product(
            {
                "carrier_id": carrier["id"],
                "product_code": "PD8",
                "name": "Second",
                "line_of_business": "HEALTH",
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_PRODUCT_CODE_EXISTS, expected_status=409)


class TestDisclosureProjection:
    def test_projected_comp_computed_at_policy_create(self):
        """PRD §3.3: "Creating the policy automatically generates its
        **ProducerDisclosure**, one per policy, in `GENERATED` status."
        PRD §3.3: "The disclosure's `projected_comp_cents` projects the
        first-year `BASE` commission for the policy at creation time, using
        the `ACTIVE` schedule for the product and the writing producer's tier
        whose window covers the policy's `effective_date`; when no such
        schedule exists yet, the projection is 0."

        Design: Corner/entities/disclosure_projected_comp_computed_at_policy_create
        """
        producer = create_producer(name="Disc D", license_number="LIC-D9")
        carrier = create_carrier(name="Carrier D9", carrier_code="CD9")
        product = create_product(carrier["id"], product_code="PD9")
        create_schedule(
            product["id"],
            tier="STANDARD",
            commission_rate_bps=5000,
            override_rate_bps=0,
            advance_months=12,
            effective_from="2026-01-01",
        )
        policy = create_policy(
            product["id"],
            producer["id"],
            policy_number="P-D9",
            premium_annual_cents=2400000,
            effective_date="2026-08-01",
        )
        disclosure = get_policy_disclosure(policy["id"])
        assert disclosure["status"] == "GENERATED"
        # 2400000 * 5000 bps / 10000 = 1200000 first-year BASE projection.
        assert disclosure["projected_comp_cents"] == 1200000
        assert disclosure["producer_id"] == producer["id"]
