"""Taxpayer onboarding and the intake of eligible gain."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_money,
    assert_pagination_meta,
    assert_request_id_prefixed,
)
from test_helpers.factories import (
    create_eligible_gain_payload,
    create_investor_payload,
)
from test_helpers.fixtures import make_investor, read_investor_statement
from test_helpers.test_users import (
    ADMIN_HEADERS,
    MEASURER_HEADERS,
    make_investor_headers,
)


def test_registering_a_taxpayer_echoes_every_declared_field(api):
    """
    "Registration takes the taxpayer's `legal_name` — between 1 and 200 characters
    and not blank — and its `taxpayer_type`, one of `INDIVIDUAL`, `PARTNERSHIP`,
    `C_CORPORATION` or `TRUST`, which determines later on which deadline bases are
    legal for that taxpayer's gains." "A freshly registered investor carries
    `eligible_gain_total`, `deferred_gain_outstanding` and `included_gain_total` all
    at 0.00."

    Design: Corner/entities/investor_creation_returns_every_declared_field
    """
    response = api.create_investor(
        create_investor_payload(
            legal_name="Marlow Family Trust",
            taxpayer_type="TRUST",
            tax_year_end_month=6,
            compliance_attestation_status="ATTESTED",
        ),
        ADMIN_HEADERS,
    )

    investor = validate_success(response, 201)

    assert investor["legal_name"] == "Marlow Family Trust"
    assert investor["taxpayer_type"] == "TRUST"
    assert investor["tax_year_end_month"] == 6
    assert investor["compliance_attestation_status"] == "ATTESTED"
    assert_money(investor["eligible_gain_total"], 0.00, "eligible_gain_total")
    assert_money(
        investor["deferred_gain_outstanding"], 0.00, "deferred_gain_outstanding"
    )
    assert_money(investor["included_gain_total"], 0.00, "included_gain_total")
    assert_common_fields(investor, "Investor")
    body = response.json()
    assert body["response_type"] == "object"
    assert_request_id_prefixed(body["meta"])
    assert body["meta"]["api_request_timestamp"]


def test_omitting_the_optional_inputs_applies_the_declared_defaults(api):
    """
    "Two further inputs are optional: `tax_year_end_month`, an integer from 1
    through 12 naming the calendar month in which the taxpayer's tax year ends,
    which defaults to 12; and `compliance_attestation_status`, which defaults to
    `PENDING` and may be supplied as `PENDING`, `ATTESTED` or `BLOCKED`."

    Design: Corner/entities/investor_defaults_applied_when_optional_inputs_omitted
    """
    response = api.create_investor(
        create_investor_payload(
            legal_name="Default Values LLC", taxpayer_type="PARTNERSHIP"
        ),
        ADMIN_HEADERS,
    )

    investor = validate_success(response, 201)

    assert investor["tax_year_end_month"] == 12
    assert investor["compliance_attestation_status"] == "PENDING"
    assert_money(investor["eligible_gain_total"], 0.00, "eligible_gain_total")


def test_a_two_row_page_over_three_gains_carries_the_pagination_counters(api):
    """
    "`limit` sets the maximum number of resources returned; it defaults to 10 when
    omitted, may not be smaller than 1, and may not be larger than 100. `offset` sets
    how many resources are skipped before the page begins; it defaults to 0 and may
    not be negative." "List responses carry `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope. `total_count` counts every
    resource matching the request's filters, not just the ones on the returned page."

    Design: Corner/entities/eligible_gain_listing_returns_pagination_envelope
    """
    investor = make_investor(
        api, legal_name="Listing Investor", compliance_attestation_status="ATTESTED"
    )
    headers = make_investor_headers(investor["id"])
    created = []
    for amount in (10000.00, 20000.00, 30000.00):
        created.append(
            validate_success(
                api.create_eligible_gain(
                    create_eligible_gain_payload(
                        investor["id"],
                        eligible_amount=amount,
                        realization_date="2026-07-01T00:00:00Z",
                        deadline_basis="SALE_DATE",
                    ),
                    headers,
                ),
                201,
            )["id"]
        )

    first_response = api.list_eligible_gains(
        MEASURER_HEADERS, {"investor_id": investor["id"], "limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    second_response = api.list_eligible_gains(
        MEASURER_HEADERS, {"investor_id": investor["id"], "limit": 2, "offset": 2}
    )
    second_rows, second_meta = validate_paginated(second_response)

    assert first_response.json()["response_type"] == "array"
    assert len(first_rows) == 2
    assert_pagination_meta(
        first_meta, total_count=3, has_more=True, limit=2, offset=0
    )
    assert len(second_rows) == 1
    assert_pagination_meta(
        second_meta, total_count=3, has_more=False, limit=2, offset=2
    )
    assert first_rows[0]["id"] != second_rows[0]["id"]
    assert first_rows[0]["id"] in created
    assert second_rows[0]["id"] in created
    statement = read_investor_statement(api, investor["id"])
    assert_money(statement["eligible_gain_total"], 60000.00, "eligible_gain_total")


def test_the_pass_through_basis_takes_its_window_from_the_year_end_instant(api):
    """
    "First, the `window_basis_date` is set: when `deadline_basis` is `SALE_DATE`, it
    is the `realization_date`; when `deadline_basis` is `PARTNERSHIP_YEAR_END` or
    `SECTION_1231_YEAR_END`, it is the `pass_through_year_end`." "Second, the
    `investment_deadline` is the `window_basis_date` advanced by exactly 180 calendar
    days. The gain is created with `status` `ELIGIBLE`, `elected_amount` at 0.00,
    `unelected_amount` equal to `eligible_amount`, and `expired_at` empty; the owning
    investor's `eligible_gain_total` is recomputed immediately."

    Design: Corner/entities/eligible_gain_computed_window_fields_derived_not_supplied
    """
    investor = make_investor(
        api,
        legal_name="Pass Through Investor",
        taxpayer_type="PARTNERSHIP",
        compliance_attestation_status="ATTESTED",
    )
    headers = make_investor_headers(investor["id"])

    response = api.create_eligible_gain(
        create_eligible_gain_payload(
            investor["id"],
            eligible_amount=250000.00,
            realization_date="2026-03-15T00:00:00Z",
            deadline_basis="PARTNERSHIP_YEAR_END",
            pass_through_year_end="2026-06-30T00:00:00Z",
        ),
        headers,
    )
    gain = validate_success(response, 201)

    assert gain["window_basis_date"].startswith("2026-06-30T00:00:00")
    assert gain["investment_deadline"].startswith("2026-12-27T00:00:00")
    assert_money(gain["elected_amount"], 0.00, "elected_amount")
    assert_money(gain["unelected_amount"], 250000.00, "unelected_amount")
    assert gain["status"] == "ELIGIBLE"
    assert not gain["expired_at"]
    statement = read_investor_statement(api, investor["id"])
    assert_money(statement["eligible_gain_total"], 250000.00, "eligible_gain_total")


def test_a_gain_character_outside_the_closed_enum_is_a_schema_rejection(api):
    """
    "Request-body and query schema on every write endpoint: all required fields
    present, no unknown fields, correct types, legal enum members, and each number
    inside its declared bounds — `ERR_INVALID_REQUEST` (400). The bounded cases
    include `eligible_amount` strictly greater than 0.00".

    Design: Corner/entities/eligible_gain_invalid_enum_gain_character_rejected
    """
    investor = make_investor(
        api, legal_name="Enum Investor", compliance_attestation_status="ATTESTED"
    )
    headers = make_investor_headers(investor["id"])

    enum_response = api.create_eligible_gain(
        create_eligible_gain_payload(
            investor["id"],
            gain_character="COLLECTIBLES_GAIN",
            eligible_amount=50000.00,
        ),
        headers,
    )
    amount_response = api.create_eligible_gain(
        create_eligible_gain_payload(investor["id"], eligible_amount=0.00),
        headers,
    )

    validate_error(enum_response, ApiErrorId.INVALID_REQUEST.value, 400)
    validate_error(amount_response, ApiErrorId.INVALID_REQUEST.value, 400)
    statement = read_investor_statement(api, investor["id"])
    assert_money(statement["eligible_gain_total"], 0.00, "eligible_gain_total")
    rows, meta = validate_paginated(
        api.list_eligible_gains(MEASURER_HEADERS, {"investor_id": investor["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_ordinary_gain_and_a_1231_basis_on_the_wrong_character_are_both_refused(api):
    """
    "Ordinary income is never deferrable: a gain whose `gain_character` is `ORDINARY` is
    rejected with `ERR_GAIN_NOT_ELIGIBLE`, and so is a gain that asks for the
    `SECTION_1231_YEAR_END` basis without being `SECTION_1231_NET`." "when
    `deadline_basis` is `PARTNERSHIP_YEAR_END` or `SECTION_1231_YEAR_END`, it is the
    `pass_through_year_end`" and "the `investment_deadline` is the `window_basis_date`
    advanced by exactly 180 calendar days."

    Design: Corner/errors/ordinary_character_and_mismatched_1231_basis_rejected
    """
    investor = make_investor(
        api,
        legal_name="Character Test Partners",
        taxpayer_type="PARTNERSHIP",
        tax_year_end_month=12,
        compliance_attestation_status="ATTESTED",
    )
    headers = make_investor_headers(investor["id"])

    ordinary = api.create_eligible_gain(
        create_eligible_gain_payload(
            investor["id"],
            gain_character="ORDINARY",
            eligible_amount=100000.00,
            realization_date="2026-07-01T00:00:00Z",
            deadline_basis="SALE_DATE",
        ),
        headers,
    )
    mismatched = api.create_eligible_gain(
        create_eligible_gain_payload(
            investor["id"],
            gain_character="LONG_TERM_CAPITAL",
            eligible_amount=100000.00,
            realization_date="2026-07-01T00:00:00Z",
            deadline_basis="SECTION_1231_YEAR_END",
            pass_through_year_end="2026-12-31T00:00:00Z",
        ),
        headers,
    )

    validate_error(ordinary, ApiErrorId.GAIN_NOT_ELIGIBLE.value, 422)
    validate_error(mismatched, ApiErrorId.GAIN_NOT_ELIGIBLE.value, 422)

    matched = validate_success(
        api.create_eligible_gain(
            create_eligible_gain_payload(
                investor["id"],
                gain_character="SECTION_1231_NET",
                eligible_amount=100000.00,
                realization_date="2026-07-01T00:00:00Z",
                deadline_basis="SECTION_1231_YEAR_END",
                pass_through_year_end="2026-12-31T00:00:00Z",
            ),
            headers,
        ),
        201,
    )

    assert matched["window_basis_date"].startswith("2026-12-31T00:00:00")
    assert matched["investment_deadline"].startswith("2027-06-29T00:00:00")
    assert matched["status"] == "ELIGIBLE"
    rows, meta = validate_paginated(
        api.list_investor_eligible_gains(investor["id"], headers, {"limit": 100})
    )
    assert meta["total_count"] == 1, "neither rejection left a gain row behind"
    assert rows[0]["id"] == matched["id"]
