"""Producer onboarding: defaults, computed-field handling, uniqueness."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    assert_producer,
    create_producer,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestProducerDefaults:
    def test_create_applies_defaults(self):
        """PRD §3.1: "The producer's compensation `tier` may be supplied as
        `STANDARD`, `GOLD`, or `PLATINUM`, defaulting to `STANDARD` when
        omitted."
        PRD §3.1: "The optional `tax_form_on_file` flag records whether a W-9
        is on file; it defaults to false, and while it remains false the
        payout workflow of §3.8 refuses to create payouts for the producer."
        PRD §3.1: "A producer's `status` begins at `ACTIVE`."

        Design: Corner/entities/producer_create_defaults_applied
        """
        created = validate_success(
            api_client.create_producer(
                {"name": "Plain Pam", "license_number": "LIC-D1"}, ADMIN
            ),
            201,
        )
        assert_producer(created)
        assert created["tier"] == "STANDARD"
        assert created["tax_form_on_file"] is False
        assert created["status"] == "ACTIVE"
        assert created["commission_balance_cents"] == 0
        assert created["pending_chargebacks_cents"] == 0

        fetched = validate_success(api_client.get_producer(created["id"], ADMIN), 200)
        assert fetched["tier"] == "STANDARD"
        assert fetched["tax_form_on_file"] is False
        assert fetched["status"] == "ACTIVE"

    def test_computed_balance_input_ignored(self):
        """PRD §3.1: "Two system-maintained aggregates ride on the record:
        `commission_balance_cents`, the earned-but-unpaid commission defined
        in §3.8, and `pending_chargebacks_cents`, the total still outstanding
        across the producer's unresolved chargebacks as defined in §3.6."

        Design: Corner/entities/producer_create_computed_field_input_ignored
        """
        created = validate_success(
            api_client.create_producer(
                {
                    "name": "Sneaky Sam",
                    "license_number": "LIC-D2",
                    "commission_balance_cents": 999999,
                },
                ADMIN,
            ),
            201,
        )
        assert created["commission_balance_cents"] == 0, (
            "system-maintained aggregate must be computed, not taken from input"
        )


class TestProducerUniqueness:
    def test_duplicate_license_number_rejected(self):
        """PRD §3.1: "the license number must be unique across all producers,
        and a duplicate is rejected with `ERR_LICENSE_NUMBER_EXISTS`."

        Design: Corner/entities/duplicate_license_number_rejected
        """
        first = create_producer(name="First", license_number="LIC-D7")
        assert first["status"] == "ACTIVE"
        res = api_client.create_producer(
            {"name": "Second", "license_number": "LIC-D7"}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_LICENSE_NUMBER_EXISTS, expected_status=409)
