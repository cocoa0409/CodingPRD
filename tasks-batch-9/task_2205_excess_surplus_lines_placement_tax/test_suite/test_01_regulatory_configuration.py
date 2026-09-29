"""Registering the regulatory landscape: brokerages, licences, state programs
and carriers, plus the per-entity 404 vocabulary and the uniqueness conflicts.
"""

import pytest

from test_helpers import (
    ERR_AFFIDAVIT_NOT_FOUND,
    ERR_BROKER_NOT_FOUND,
    ERR_CANCELLATION_NOT_FOUND,
    ERR_CARRIER_DUPLICATE,
    ERR_CARRIER_ELIGIBILITY_NOT_FOUND,
    ERR_CARRIER_NOT_FOUND,
    ERR_DECLINATION_NOT_FOUND,
    ERR_ENDORSEMENT_NOT_FOUND,
    ERR_FILING_BATCH_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_MARKET_SECURITY_REVIEW_NOT_FOUND,
    ERR_PLACEMENT_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_STATE_PROGRAM_DUPLICATE,
    ERR_STATE_PROGRAM_NOT_FOUND,
    ERR_TAX_FILING_LINE_NOT_FOUND,
    NON_EXISTENT_UUID,
    COMPLIANCE_OFFICER_ANDERS,
    PLATFORM_ADMIN,
    assert_common_fields,
    assert_three_fraction_digits,
    broker_payload,
    carrier_payload,
    make_placement_broker_headers,
    tx_program_payload,
    validate_error,
    validate_success,
)


def test_broker_registration_returns_every_declared_field_and_starts_active(world):
    """A brokerage comes back fully formed on creation.

    PRD 3.1: "A new brokerage's `status` begins at `ACTIVE`; the only other
    value is `SUSPENDED`, reached by an administrative suspension."

    Design: Corner/entities/broker_create_returns_every_declared_field_and_starts_active
    """
    response = world.api.create_broker(
        broker_payload(firm_name="Lone Star Surplus Partners", home_state="TX"),
        PLATFORM_ADMIN,
    )
    broker = validate_success(response, 201)

    assert broker["firm_name"] == "Lone Star Surplus Partners"
    assert broker["home_state"] == "TX"
    assert broker["status"] == "ACTIVE"
    assert_common_fields(broker, expected_version=1)
    assert_three_fraction_digits(broker["created_at"])
    assert_three_fraction_digits(broker["updated_at"])

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert_three_fraction_digits(envelope["meta"]["api_request_timestamp"])


def test_state_program_get_returns_the_stored_configuration_unchanged(world):
    """Reading a program back yields exactly the configuration that was filed.

    PRD 3.1: "an optional `stamping_fee_cap_cents`, which is a per-allocation
    ceiling on the stamping fee in cents and which defaults to null meaning
    uncapped"

    Design: Corner/entities/state_program_get_returns_the_stored_configuration_unchanged
    """
    payload = tx_program_payload()
    created = validate_success(world.api.create_state_program(payload, PLATFORM_ADMIN), 201)
    fetched = validate_success(world.api.get_state_program(created["id"], PLATFORM_ADMIN), 200)

    assert fetched["id"] == created["id"]
    assert fetched["state_code"] == "TX"
    assert fetched["premium_tax_rate"] == pytest.approx(0.0485)
    assert fetched["stamping_fee_rate"] == pytest.approx(0.0015)
    assert fetched["stamping_fee_cap_cents"] is None
    assert fetched["stamping_office_required"] is True
    assert fetched["allocation_method"] == "ALLOCATED_MULTI"
    assert fetched["diligent_search_min_declinations"] == 3
    assert fetched["export_list_exempts_search"] is True
    assert fetched["filing_frequency"] == "MONTHLY"
    assert fetched["filing_deadline_days"] == 30
    assert fetched["return_premium_tax_refundable"] is True
    assert fetched["return_premium_stamping_refundable"] is False
    assert fetched["min_carrier_capital_surplus_cents"] == 1_500_000_000
    assert fetched["required_notice_codes"] == ["TX-SL-1", "TX-SL-2"]
    assert_common_fields(fetched, expected_version=1)


def test_carrier_get_with_an_unknown_id_returns_carrier_not_found(world):
    """An unknown carrier id gets the carrier's own 404, not a generic one.

    PRD 2.9: "The 404 vocabulary is one error per entity: `ERR_BROKER_NOT_FOUND`,
    `ERR_STATE_PROGRAM_NOT_FOUND`, `ERR_CARRIER_NOT_FOUND`,
    `ERR_CARRIER_ELIGIBILITY_NOT_FOUND`, `ERR_MARKET_SECURITY_REVIEW_NOT_FOUND`,
    `ERR_PLACEMENT_NOT_FOUND`, `ERR_DECLINATION_NOT_FOUND`,
    `ERR_POLICY_NOT_FOUND`, `ERR_ENDORSEMENT_NOT_FOUND`,
    `ERR_CANCELLATION_NOT_FOUND`, `ERR_TAX_FILING_LINE_NOT_FOUND`,
    `ERR_FILING_BATCH_NOT_FOUND` and `ERR_AFFIDAVIT_NOT_FOUND`."

    Design: Corner/entities/carrier_get_with_an_unknown_id_returns_carrier_not_found
    """
    validate_error(
        world.api.get_carrier(NON_EXISTENT_UUID, PLATFORM_ADMIN),
        ERR_CARRIER_NOT_FOUND,
        404,
    )


def test_carrier_create_with_an_out_of_enum_am_best_rating_returns_invalid_request(world):
    """A rating outside the declared table is a field-shape failure.

    PRD 2.11: "This rung covers missing required fields, wrong types,
    out-of-range numerics, state codes that are not exactly two uppercase ASCII
    letters, unrecognised enum members, negative money where money must be
    non-negative, an `expiration_date` that is not strictly after
    `effective_date`, and a `removed_on` that precedes `listed_on`."

    Design: Corner/entities/carrier_create_with_an_out_of_enum_am_best_rating_returns_invalid_request
    """
    validate_error(
        world.api.create_carrier(
            carrier_payload(naic_number="12345", am_best_rating="AAA"), PLATFORM_ADMIN
        ),
        ERR_INVALID_REQUEST,
        400,
    )


def test_broker_license_status_is_computed_on_read_and_never_stored(world):
    """The licence's status follows the logical clock across three reads.

    PRD 3.1: "A licence's `status` is never stored: it is recomputed on every
    read as `ACTIVE` while the logical clock is strictly before `expires_on` and
    `LAPSED` from the moment the clock reaches or passes it."

    Design: Corner/entities/broker_license_status_is_computed_on_read_and_never_stored
    """
    world.create_broker()
    licence = world.add_license(
        state_code="TX", license_number="SL-TX-9001", expires_on="2026-09-01T00:00:00Z"
    )
    stored_version = licence["version"]

    def read_licence():
        rows = validate_success(
            world.api.list_broker_licenses(world.broker["id"], PLATFORM_ADMIN), 200
        )
        return next(row for row in rows if row["id"] == licence["id"])

    assert read_licence()["status"] == "ACTIVE"

    world.set_clock("2026-08-31T23:59:59Z")
    assert read_licence()["status"] == "ACTIVE"

    world.set_clock("2026-09-01T00:00:00Z")
    lapsed = read_licence()
    assert lapsed["status"] == "LAPSED"
    assert lapsed["version"] == stored_version


def test_duplicate_state_program_and_duplicate_carrier_registrations_are_refused(world):
    """Both global uniqueness constraints report their own 409.

    PRD 2.11: "Uniqueness conflicts sit alongside the interval rung as 409s: a
    second state program for an existing `state_code` is
    `ERR_STATE_PROGRAM_DUPLICATE`, a second carrier with an existing
    `naic_number` is `ERR_CARRIER_DUPLICATE`, and adding a carrier whose
    `capital_surplus_cents` falls below a state's
    `min_carrier_capital_surplus_cents` to that state's list is
    `ERR_CARRIER_BELOW_STATE_CAPITAL_MINIMUM`."

    Design: Corner/errors/duplicate_state_program_and_duplicate_carrier_registrations_are_refused
    """
    program = world.create_program(tx_program_payload())
    carrier = world.create_carrier(naic_number="12345")

    validate_error(
        world.api.create_state_program(
            tx_program_payload(premium_tax_rate=0.02), PLATFORM_ADMIN
        ),
        ERR_STATE_PROGRAM_DUPLICATE,
        409,
    )
    validate_error(
        world.api.create_carrier(
            carrier_payload(naic_number="12345", legal_name="Copycat Specialty Ltd"),
            PLATFORM_ADMIN,
        ),
        ERR_CARRIER_DUPLICATE,
        409,
    )

    # The originals are untouched by the refused duplicates.
    surviving_program = validate_success(
        world.api.get_state_program(program["id"], PLATFORM_ADMIN), 200
    )
    assert surviving_program["premium_tax_rate"] == pytest.approx(0.0485)
    assert surviving_program["version"] == 1

    surviving_carrier = validate_success(
        world.api.get_carrier(carrier["id"], PLATFORM_ADMIN), 200
    )
    assert surviving_carrier["legal_name"] == "Atlas Specialty Insurance Company"
    assert surviving_carrier["version"] == 1


def test_every_get_by_id_endpoint_reports_its_own_not_found_error(world):
    """Each retrieval endpoint owns a distinct 404 error id.

    PRD 2.11: "**Path existence, left to right.** Every templated path segment
    resolves."

    Design: Corner/errors/every_get_by_id_endpoint_reports_its_own_not_found_error
    """
    probes = [
        (world.api.get_broker, ERR_BROKER_NOT_FOUND),
        (world.api.get_state_program, ERR_STATE_PROGRAM_NOT_FOUND),
        (world.api.get_carrier, ERR_CARRIER_NOT_FOUND),
        (world.api.get_carrier_eligibility, ERR_CARRIER_ELIGIBILITY_NOT_FOUND),
        (world.api.get_placement, ERR_PLACEMENT_NOT_FOUND),
        (world.api.get_policy, ERR_POLICY_NOT_FOUND),
        (world.api.get_endorsement, ERR_ENDORSEMENT_NOT_FOUND),
        (world.api.get_tax_filing_line, ERR_TAX_FILING_LINE_NOT_FOUND),
        (world.api.get_filing_batch, ERR_FILING_BATCH_NOT_FOUND),
    ]
    seen = set()
    for endpoint, expected_error in probes:
        validate_error(endpoint(NON_EXISTENT_UUID, PLATFORM_ADMIN), expected_error, 404)
        seen.add(expected_error)
    assert len(seen) == len(probes), "each entity must report its own 404 error id"


def test_action_endpoints_on_entities_without_a_get_by_id_still_report_not_found(world):
    """Reviews, declinations, cancellations and affidavits are addressable only
    through actions, and those actions still resolve the path first.

    PRD 2.9: "When a path carries a templated segment, existence is resolved
    **left to right**, and the first unresolvable segment determines the error."

    Design: Corner/errors/action_endpoints_on_entities_without_a_get_by_id_still_report_not_found
    """
    broker_headers = make_placement_broker_headers("br-nobody")

    validate_error(
        world.api.start_security_review(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_ANDERS),
        ERR_MARKET_SECURITY_REVIEW_NOT_FOUND,
        404,
    )
    validate_error(
        world.api.invalidate_declination(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_ANDERS),
        ERR_DECLINATION_NOT_FOUND,
        404,
    )
    validate_error(
        world.api.process_cancellation(NON_EXISTENT_UUID, broker_headers),
        ERR_CANCELLATION_NOT_FOUND,
        404,
    )
    validate_error(
        world.api.sign_affidavit(NON_EXISTENT_UUID, COMPLIANCE_OFFICER_ANDERS),
        ERR_AFFIDAVIT_NOT_FOUND,
        404,
    )
