"""Recording instruments and reading them back: minted posture, defaults and listings."""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def test_a_recorded_lease_comes_back_with_the_posture_the_land_department_expects(api):
    """Nothing about tenure, obligations or acreage is a client input at recording time.

    A newly recorded lease begins with `tenure_status` set to `PRIMARY_TERM`, `obligation_status` set to `COMPLIANT`, `extension_exercised` set to false, `extension_bonus_paid_cents` set to 0, `shut_in_payments_made` set to 0, `committed_acres_total` and `held_acres` both 0, and a `version` of 1.
    Its `shut_in_start_date`, `shut_in_next_due_date`, `last_operation_end_date` and `continuous_dev_deadline` are all null, since nothing has yet been committed to a well and no maintenance event has been recorded.

    Design: Corner/entities/lease_creation_returns_the_declared_system_defaults
    """
    fixtures.set_clock(api, CLOCK)

    lease = validate_success(
        api.create_lease(factories.create_lease_payload(), fixtures.LAND_ADMIN), 201
    )

    assert is_valid_uuid(lease["id"])
    assert lease["lease_number"] == "L-001"
    assert lease["lessor_name"] == "Alpha Minerals"
    assert lease["gross_acres"] == 640.00
    assert lease["royalty_rate"] == 0.187500
    assert lease["tenure_status"] == "PRIMARY_TERM"
    assert lease["obligation_status"] == "COMPLIANT"
    assert lease["extension_exercised"] is False
    assert lease["extension_bonus_paid_cents"] == 0
    assert lease["shut_in_payments_made"] == 0
    assert lease["shut_in_start_date"] is None
    assert lease["shut_in_next_due_date"] is None
    assert lease["last_operation_end_date"] is None
    assert lease["continuous_dev_deadline"] is None
    assert lease["committed_acres_total"] == 0.00
    assert lease["held_acres"] == 0.00
    assert lease["version"] == 1


def test_reading_a_pooled_well_returns_its_stored_terms_and_its_derived_ledger(api):
    """The well read is the single place a bookkeeper can see depth, unit and money together.

    Its `plugging_liability_cents` is estimated immediately from depth alone — no cost history participates.
    After that adjustment the well's `allocation_factor_total` is exactly 1.000000.

    Design: Corner/entities/get_well_returns_the_stored_well_with_its_derived_ledger
    """
    fixtures.set_clock(api, CLOCK)
    lease1 = validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )
    lease2 = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-002",
                lessor_name="Beta Royalties",
                gross_acres=320.0,
                royalty_rate=0.25,
                primary_term_end_date="2027-12-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    well = _bare_well(api)
    fixtures.commit_acreage(api, well["id"], lease1["id"], 480.0)
    fixtures.commit_acreage(api, well["id"], lease2["id"], 160.0)
    fixtures.effectuate_pooling(api, well["id"], "2026-04-01")

    read = validate_success(api.get_well(well["id"], fixtures.JIB_ACCOUNTANT), 200)

    assert read["well_name"] == "Sandstone 1H"
    assert read["api_number"] == "42-123-45678"
    assert read["product_type"] == "OIL"
    assert read["total_depth_ft"] == 9500
    assert read["well_status"] == "PROPOSED"
    assert read["pooling_status"] == "POOLED_EFFECTIVE"
    assert read["allocation_factor_total"] == 1.000000
    assert read["plugging_liability_cents"] == 14_900_000
    assert read["billed_to_date_cents"] == 0
    assert read["consent_working_interest_pct"] == 0.000000


def test_the_lease_inventory_pages_newest_first_and_reports_the_full_match_count(api):
    """Land staff open the inventory on the instrument they just recorded, not the oldest one.

    List results are ordered by `created_at` ascending — oldest record first — with one deliberate exception: the lease inventory listing is presented newest first, ordered by `created_at` descending, because land staff work the most recently recorded instruments.
    When a list endpoint responds, the `meta` object carries `limit`, `offset`, `total_count` and `has_more`, where `total_count` is the number of records matching the filters before the page window is applied and `has_more` indicates whether any record remains beyond the current window.

    Design: Corner/entities/list_leases_returns_a_paginated_envelope_with_total_count
    """
    fixtures.set_clock(api, CLOCK)
    validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )
    validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-002",
                lessor_name="Beta Royalties",
                gross_acres=320.0,
                royalty_rate=0.25,
                primary_term_end_date="2027-12-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-003",
                lessor_name="Gamma Minerals",
                gross_acres=160.0,
                royalty_rate=0.2,
                primary_term_end_date="2028-06-30",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    first_page, meta = validate_paginated(
        api.list_leases(fixtures.AUDIT_REVIEWER, params={"limit": 2, "offset": 0})
    )
    assert len(first_page) == 2
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert [row["lease_number"] for row in first_page] == ["L-003", "L-002"]

    second_page, meta = validate_paginated(
        api.list_leases(fixtures.AUDIT_REVIEWER, params={"limit": 2, "offset": 2})
    )
    assert len(second_page) == 1
    assert meta["limit"] == 2
    assert meta["offset"] == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is False


def test_an_unknown_lease_identifier_is_a_missing_lease_not_an_empty_answer(api):
    """A well-formed identifier for an instrument that was never recorded is still a miss.

    `lease_id` must resolve to a lease, else `ERR_LEASE_NOT_FOUND` (404).

    Design: Corner/entities/get_lease_with_an_unknown_id_returns_lease_not_found
    """
    fixtures.set_clock(api, CLOCK)
    lease = validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )

    validate_error(
        api.get_lease(UNKNOWN_ID, fixtures.LAND_ADMIN), "ERR_LEASE_NOT_FOUND", 404
    )

    rows, meta = validate_paginated(api.list_leases(fixtures.LAND_ADMIN))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == lease["id"]
    assert rows[0]["version"] == 1


def test_a_lease_recorded_without_its_acreage_is_refused_outright(api):
    """Acreage has no sensible default, so the instrument cannot be filed without it.

    On every creating or mutating request, each field the endpoint declares as required is present and non-null, else `ERR_VALIDATION` (400).
    Gross acreage must be strictly greater than zero and is carried to two decimal places.

    Design: Corner/entities/create_lease_missing_required_gross_acres_is_rejected
    """
    fixtures.set_clock(api, CLOCK)

    validate_error(
        api.create_lease(
            factories.minimal_lease_payload(omit_fields=["gross_acres"]),
            fixtures.LAND_ADMIN,
        ),
        "ERR_VALIDATION",
        400,
    )

    rows, meta = validate_paginated(api.list_leases(fixtures.LAND_ADMIN))
    assert meta["total_count"] == 0


def test_the_least_generous_instrument_is_what_an_omitted_option_term_records(api):
    """A silent lease is filed with no option, no bonus, no shut-in rate and a 180-day window.

    Four further terms are optional at recording, each with a default that describes the least generous instrument.
    `continuous_dev_window_days` is the number of days allowed between the end of one continuous-development operation and the start of the next; it defaults to 180, and must be at least 30 and at most 365.

    Design: Corner/entities/omitted_lease_option_fields_take_their_declared_defaults
    """
    fixtures.set_clock(api, CLOCK)

    lease = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-009",
                lessor_name="Omega Minerals",
                gross_acres=100.0,
                royalty_rate=0.125,
                primary_term_end_date="2027-03-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    assert lease["extension_option_months"] == 0
    assert lease["extension_bonus_per_acre_cents"] == 0
    assert lease["shut_in_royalty_per_acre_cents"] == 0
    assert lease["continuous_dev_window_days"] == 180


def test_an_authorization_circulated_without_commercial_terms_takes_the_declared_ones(api):
    """The operator may circulate a bare authorization and still get the standard penalty and threshold.

    `non_consent_penalty_multiple` is the multiple of a non-consenting owner's capital share that the operator may later recover out of that owner's revenue; it defaults to 3.0 and must lie within the inclusive range 1.0 through 5.0 with at most one decimal place.
    A new AFE opens with `afe_status` of `ELECTIONS_OPEN`, `consent_working_interest_pct` and `non_consent_working_interest_pct` both 0, `elections_closed_at` null, and `version` 1.

    Design: Corner/entities/omitted_afe_election_terms_take_their_declared_defaults
    """
    fixtures.set_clock(api, CLOCK)
    well = _bare_well(api)

    afe = validate_success(
        api.create_afe(
            well["id"],
            factories.minimal_afe_payload(
                afe_number="AFE-900",
                operation_type="WORKOVER",
                estimated_cost_cents=1_500_000,
                cost_class="OPERATING",
                election_deadline_date="2026-08-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    assert afe["non_consent_penalty_multiple"] == 3.0
    assert afe["minimum_consent_pct"] == 0.500000
    assert afe["afe_status"] == "ELECTIONS_OPEN"
    assert afe["consent_working_interest_pct"] == 0.000000
    assert afe["non_consent_working_interest_pct"] == 0.000000
    assert afe["elections_closed_at"] is None
    assert afe["version"] == 1
    assert is_iso8601_timestamp(afe["created_at"])
