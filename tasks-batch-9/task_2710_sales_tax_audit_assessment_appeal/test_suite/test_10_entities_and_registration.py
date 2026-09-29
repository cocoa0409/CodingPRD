"""Registering permit holders, loading information returns and reading them back."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_append_only_fields,
    assert_envelope_meta,
    assert_information_return,
    assert_taxpayer,
    create_information_return_payload,
    create_sample_unit_payload,
    create_taxpayer_payload,
    load_information_return,
    read_taxpayer,
    register_taxpayer,
    rescore_screening,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["selection_analyst_headers"]
AUDITOR = TEST_USERS["field_auditor_headers"]
GROCERY_NAICS = "445110"
GHOST_AGREEMENT_ID = "00000000-0000-0000-0000-000000000000"

HARBOR = {
    "legal_name": "Harbor Foods LLC",
    "industry_naics_code": GROCERY_NAICS,
    "filing_frequency": "MONTHLY",
    "gross_receipts_annual_cents": 250_000_000,
    "delinquent_period_count": 2,
}
SUMMIT = {
    "legal_name": "Summit Market Inc",
    "industry_naics_code": GROCERY_NAICS,
    "filing_frequency": "QUARTERLY",
    "gross_receipts_annual_cents": 100_000_000,
}


def _list_taxpayers(**params):
    return validate_paginated(api_client.list_taxpayers(ANALYST, params=params or None))


def test_registering_a_permit_holder_returns_its_first_triage_score():
    """One registration comes back in the declared envelope with the derived block seeded.

    PRD 2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD 2.2: "The `api_request_id` is a server-generated unique identifier for the
    request that starts with `req_`."
    PRD 3.1: "Registration also seeds the derived block. `reported_total_cents` and
    `matched_total_cents` both start at 0 because no information return is yet on
    file, `open_audit_count` starts at 0, and the four persisted component scores —
    `info_variance_bp`, `delinquency_bp`, `magnitude_bp` and `prior_audit_bp` — are
    computed immediately along with `screening_score`, so a freshly registered
    holder already carries a triage score."
    PRD 3.1: "The delinquency component is `delinquent_period_count` multiplied by
    2,500 basis points — twenty-five percentage points per missed or late period, so
    four missed periods alone saturate the component — capped at 10,000."

    Design: Corner/entities/taxpayer_creation_returns_the_full_success_envelope
    """
    response = api_client.create_taxpayer(create_taxpayer_payload(**HARBOR), ANALYST)
    taxpayer = validate_success(response, 201)

    body = response.json()
    assert body["response_type"] == "object"
    assert_envelope_meta(body)
    assert_taxpayer(taxpayer)

    assert taxpayer["info_variance_bp"] == 0
    assert taxpayer["delinquency_bp"] == 5_000
    # min(250,000,000, 5,000,000,000) * 10,000 / 5,000,000,000, rounded half up.
    assert taxpayer["magnitude_bp"] == 500
    assert taxpayer["prior_audit_bp"] == 3_500
    # Triage weights variance 60 and delinquency 40: (0*60 + 5000*40) / 1000.
    assert taxpayer["screening_score"] == 200
    assert taxpayer["reported_total_cents"] == 0
    assert taxpayer["matched_total_cents"] == 0
    assert taxpayer["open_audit_count"] == 0
    assert taxpayer["compliance_status"] == "COMPLIANT"
    assert taxpayer["version"] == 1


def test_the_three_optional_registration_inputs_take_their_declared_defaults():
    """Omitting the optional inputs leaves a never-audited, punctual, compliant holder.

    PRD 3.1: "`delinquent_period_count`, the number of filing periods filed late or
    not filed at all, defaults to 0 and may not exceed 40. `prior_audit_error_rate_bp`,
    the error rate the most recent prior audit measured, defaults to null — meaning
    never audited — and when supplied must lie between 0 and 10,000 basis points.
    `compliance_status` defaults to `COMPLIANT` and may be set at registration to
    `DELINQUENT` or `REVOKED`; thereafter the system also writes it as a cascade from
    collection and arrangement outcomes."
    PRD 3.1: "The prior-audit component is the neutral 3,500 basis points when
    `prior_audit_error_rate_bp` is null, and otherwise the smaller of that stored
    rate and 10,000."

    Design: Corner/entities/taxpayer_optional_fields_take_their_declared_defaults
    """
    taxpayer = register_taxpayer(**SUMMIT)

    assert taxpayer["delinquent_period_count"] == 0
    assert taxpayer["prior_audit_error_rate_bp"] is None
    assert taxpayer["compliance_status"] == "COMPLIANT"
    assert taxpayer["delinquency_bp"] == 0
    assert taxpayer["prior_audit_bp"] == 3_500
    # min(100,000,000, 5,000,000,000) * 10,000 / 5,000,000,000, rounded half up.
    assert taxpayer["magnitude_bp"] == 200
    # Neither triage factor scores: the prior-audit prior belongs to the full variant.
    assert taxpayer["screening_score"] == 0


def test_a_registration_without_a_permit_number_is_refused_and_stores_nothing():
    """The required permit number has no default, so the body fails schema validation.

    PRD 3.1: "A `SelectionAnalyst` or an `AuditSupervisor` registers one by supplying
    its `legal_name` (between 1 and 160 characters), its `permit_number`, its
    six-digit `industry_naics_code`, its `filing_frequency` — one of `MONTHLY`,
    `QUARTERLY` or `ANNUAL` — and its self-reported `gross_receipts_annual_cents`,
    which may be zero but never negative."
    PRD 2.8: "5. **Request shape.** Required body fields present; unknown enum
    values rejected; cents, basis-point and count fields non-negative;
    `in_state_usage_pct_bp` and `confidence_level_bp` within 0 through 10,000;
    `period_start` no later than `period_end`; dates parseable; `abatement_factors`
    non-empty and drawn only from the four recognized factor names. Violations are
    `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."

    Design: Corner/entities/taxpayer_creation_without_permit_number_rejected
    """
    payload = create_taxpayer_payload(
        legal_name="Nameless Trading Co",
        permit_number=...,
        industry_naics_code=GROCERY_NAICS,
        filing_frequency="MONTHLY",
        gross_receipts_annual_cents=100_000_000,
    )
    assert "permit_number" not in payload

    validate_error(
        api_client.create_taxpayer(payload, ANALYST),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    rows, meta = _list_taxpayers()
    assert rows == []
    assert meta["total_count"] == 0


def test_a_filing_frequency_outside_the_enumeration_is_refused():
    """A plausible but undeclared filing frequency is rejected, not stored as a string.

    PRD 3.1: "its `filing_frequency` — one of `MONTHLY`, `QUARTERLY` or `ANNUAL` —"
    PRD 2.8: "5. **Request shape.** Required body fields present; unknown enum
    values rejected; cents, basis-point and count fields non-negative;
    `in_state_usage_pct_bp` and `confidence_level_bp` within 0 through 10,000;
    `period_start` no later than `period_end`; dates parseable; `abatement_factors`
    non-empty and drawn only from the four recognized factor names. Violations are
    `ERR_INVALID_REQUEST` (400). Applies to every write endpoint."

    Design: Corner/entities/taxpayer_creation_with_an_undeclared_filing_frequency_rejected
    """
    payload = create_taxpayer_payload(
        legal_name="Biweekly Filers LLC",
        industry_naics_code=GROCERY_NAICS,
        filing_frequency="BIWEEKLY",
        gross_receipts_annual_cents=100_000_000,
    )

    validate_error(
        api_client.create_taxpayer(payload, ANALYST),
        ApiErrorId.ERR_INVALID_REQUEST.value,
        400,
    )

    rows, meta = _list_taxpayers()
    assert rows == []
    assert meta["total_count"] == 0


def test_the_permit_holder_list_pages_one_row_at_a_time_over_a_stable_total():
    """Two holders, two single-row pages, and a filter that keeps both.

    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` counts
    the records that match the filters before the limit and offset are applied."
    PRD 2.3: "Unless a specific endpoint states otherwise, every list is sorted by
    `created_at` ascending."
    PRD 2.2: "Pagination-related fields in `meta` (`limit`, `offset`, `total_count`,
    `has_more`) are included for list endpoints."

    Design: Corner/entities/taxpayer_list_paginates_with_total_count_and_has_more
    """
    harbor = register_taxpayer(**HARBOR)
    summit = register_taxpayer(**SUMMIT)

    response = api_client.list_taxpayers(ANALYST, params={"limit": 1, "offset": 0})
    first_page, first_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array"
    assert len(first_page) == 1
    assert first_meta["total_count"] == 2
    assert first_meta["limit"] == 1
    assert first_meta["offset"] == 0
    assert first_meta["has_more"] is True

    second_page, second_meta = _list_taxpayers(limit=1, offset=1)
    assert len(second_page) == 1
    assert second_meta["total_count"] == 2
    assert second_meta["offset"] == 1
    assert second_meta["has_more"] is False

    assert [row["id"] for row in first_page + second_page] == [harbor["id"], summit["id"]]

    filtered, filtered_meta = _list_taxpayers(
        industry_naics_code=GROCERY_NAICS, limit=10, offset=0
    )
    assert len(filtered) == 2
    assert filtered_meta["total_count"] == 2
    assert filtered_meta["has_more"] is False


def test_a_loaded_information_return_is_immutable_and_moves_the_holders_totals():
    """The return carries no version and no updated_at, and its amounts roll up.

    PRD 2.4: "The single exception is the **information return**. A third-party
    information return is immutable once loaded, so it carries only `id` and
    `created_at`; it has no `updated_at` field and no `version` field at all."
    PRD 3.1: "Loading computes `variance_cents` as the reported amount minus the
    matched amount, a signed value, and classifies the row in `match_status`:
    `MATCHED` when the variance is exactly zero, `UNDER_REPORTED` when it is
    positive, and `OVER_REPORTED` when it is negative."
    PRD 3.1: "A third computed flag, `in_scoring_window`, is true when the row's
    `period_end` is on or before the logical clock date; it is evaluated when the
    record is read rather than frozen at load time, so moving the clock moves the
    flag."
    PRD 3.1: "`reported_total_cents` is the sum of `reported_amount_cents`, and
    `matched_total_cents` the sum of `matched_return_amount_cents`, over that
    holder's returns whose `period_end` falls inside the scoring window"

    Design: Corner/entities/information_return_is_immutable_and_rolls_up_to_the_taxpayer
    """
    harbor = register_taxpayer(**HARBOR)
    assert harbor["screening_score"] == 200

    created = validate_success(
        api_client.create_information_return(
            create_information_return_payload(
                harbor["id"],
                source_type="FEDERAL_1099K",
                period_start="2026-01-01",
                period_end="2026-03-31",
                reported_amount_cents=120_000_000,
                matched_return_amount_cents=90_000_000,
            ),
            ANALYST,
        ),
        201,
    )
    assert created["variance_cents"] == 30_000_000
    assert created["match_status"] == "UNDER_REPORTED"

    stored = validate_success(
        api_client.get_information_return(created["id"], ANALYST), 200
    )
    assert_append_only_fields(stored, "information return")
    assert_information_return(stored)
    assert stored["in_scoring_window"] is True

    holder = read_taxpayer(harbor["id"])
    assert holder["reported_total_cents"] == 120_000_000
    assert holder["matched_total_cents"] == 90_000_000

    # |120,000,000 - 90,000,000| * 10,000 / 120,000,000 = 2,500 basis points.
    rescored = rescore_screening(harbor["id"])
    assert rescored["info_variance_bp"] == 2_500
    # Triage: (2500*60 + 5000*40) / 1000 = 350.
    assert rescored["screening_score"] == 350


def test_a_sample_unit_naming_an_unknown_agreement_is_a_not_found():
    """The body foreign key is resolved before any state rule about the agreement.

    PRD 2.8: "6. **Body foreign keys.** Every foreign key supplied in the body
    resolves to an existing record, producing that entity's 404 from the same
    catalogue as tier 3. Applies to every write endpoint whose body carries a foreign
    key."
    PRD 2.8: "3. **Path existence.** Every identifier embedded in the request path
    resolves to an existing record, validated left to right, producing that entity's
    own 404: `ERR_TAXPAYER_NOT_FOUND`, `ERR_INFORMATION_RETURN_NOT_FOUND`,
    `ERR_INDUSTRY_PROJECT_NOT_FOUND`, `ERR_AUDIT_LEAD_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_STATUTE_WAIVER_NOT_FOUND`,
    `ERR_SAMPLING_AGREEMENT_NOT_FOUND`, `ERR_SAMPLE_UNIT_NOT_FOUND`,
    `ERR_EXEMPTION_CERTIFICATE_NOT_FOUND`, `ERR_USE_TAX_PURCHASE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_ASSESSMENT_ADJUSTMENT_NOT_FOUND`,
    `ERR_APPEAL_PROCEEDING_NOT_FOUND` or `ERR_PAYMENT_ARRANGEMENT_NOT_FOUND`."
    PRD 3.4: "Each **sample unit** names the `sampling_agreement_id` it was drawn
    under, which must be the audit's `agreed_agreement_id`; a unit offered against
    any other agreement — a superseded round, or an audit with no accepted
    methodology at all — is refused with `ERR_AGREEMENT_NOT_AGREED`."

    Design: Corner/entities/sample_unit_body_foreign_key_must_resolve
    """
    response = api_client.create_sample_unit(
        create_sample_unit_payload(
            GHOST_AGREEMENT_ID,
            0,
            "2026-03-02",
            100_000,
            invoice_reference="GHOST-1",
            error_class="NO_ERROR",
        ),
        AUDITOR,
    )

    validate_error(
        response, ApiErrorId.ERR_SAMPLING_AGREEMENT_NOT_FOUND.value, 404
    )
    assert response.json()["data"]["error_id"] != "ERR_AGREEMENT_NOT_AGREED"
