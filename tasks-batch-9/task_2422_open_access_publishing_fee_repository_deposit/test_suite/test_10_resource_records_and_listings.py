"""Resource records, server-assigned fields, declared defaults and list views.

Every test builds its own world from scratch through PRD-declared endpoints and
then checks exactly what the PRD pins about the stored row, the response envelope
or the rejection.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_coverage,
    assert_append_only_fields,
    assert_pagination_meta,
    assert_timestamp_has_three_fractional_digits,
    create_agreement_coverage_payload,
    create_author_payload,
    create_journal_payload,
    create_publisher_payload,
    create_repository_deposit_payload,
    draft_agreement,
    make_corresponding_author_headers,
    read_article,
    record_article,
    register_author,
    register_journal,
    register_publisher,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# private preamble helpers (multi-step setups that fixtures.py does not offer)
# --------------------------------------------------------------------------- #
def _register_meridian_with_hybrid_journal():
    """Publisher MERID plus its HYBRID journal at a 380000-cent list charge."""
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    journal = register_journal(
        publisher["id"],
        issn="2041-1723",
        title="Meridian Journal of Cell Signalling",
        oa_model="HYBRID",
        list_apc_cents=380000,
        required_embargo_months=12,
    )
    return publisher, journal


def _register_tomas_berg():
    """The recipe's ORCID-bearing faculty author with an explicit annual cap."""
    return register_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )


# --------------------------------------------------------------------------- #
# creation, retrieval and system-assigned fields
# --------------------------------------------------------------------------- #
def test_publisher_creation_returns_system_and_default_fields(
    api, agreement_admin_headers
):
    """Registering a publisher returns the unscreened defaults and system fields.

    PRD §4: "Operations that mint a brand-new, independently addressable resource — registering a publisher, journal, agreement, coverage line, author, funder, grant or fund; recording an article; appending an eligibility determination; opening a fund request; receiving an invoice; creating a deposit — return `201 Created`."
    PRD §3.1: "An `AgreementAdmin` registers a publisher by supplying its legal `name`, which must be between 1 and 200 characters, a short `publisher_code` of between 2 and 16 uppercase alphanumeric characters that must be unique across all publishers and that later appears inside minted DOIs and in negotiation reporting, and a `country_code` of exactly two uppercase letters giving the ISO 3166-1 alpha-2 country of incorporation."
    PRD §3.1: "A freshly registered publisher has not been screened: its `screening_status` is `UNSCREENED`, its `predatory_score` is absent, its `active_agreement_count` is zero, and the signal snapshot fields and `author_guidance` and `last_screened_at` are all absent."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    PRD §2.2: "The `response_type` is either "object" for a single resource or "array" for a list of resources."
    Design: Corner/entities/corner_publisher_creation_returns_system_and_default_fields
    """
    payload = create_publisher_payload(
        name="Meridian Academic Press", publisher_code="MERID", country_code="NL"
    )

    response = api.create_publisher(payload, agreement_admin_headers)
    data = validate_success(response, expected_status=201)

    assert data.get("id"), f"a created publisher must carry a server-minted id, got {data.get('id')!r}"
    assert data["screening_status"] == "UNSCREENED", (
        f"a freshly registered publisher is UNSCREENED, got {data['screening_status']!r}"
    )
    assert data["active_agreement_count"] == 0, (
        f"active_agreement_count starts at zero, got {data['active_agreement_count']}"
    )
    assert data.get("predatory_score") is None, (
        f"predatory_score is absent before screening, got {data.get('predatory_score')!r}"
    )
    assert data.get("author_guidance") is None, (
        f"author_guidance is absent before screening, got {data.get('author_guidance')!r}"
    )
    assert data.get("last_screened_at") is None, (
        f"last_screened_at is absent before screening, got {data.get('last_screened_at')!r}"
    )
    assert data["version"] == 1, f"version starts at 1 on creation, got {data['version']}"
    assert data["name"] == "Meridian Academic Press", (
        f"the supplied name must be stored verbatim, got {data['name']!r}"
    )
    assert data["publisher_code"] == "MERID", (
        f"the supplied publisher_code must be stored verbatim, got {data['publisher_code']!r}"
    )
    assert data["country_code"] == "NL", (
        f"the supplied country_code must be stored verbatim, got {data['country_code']!r}"
    )

    body = response.json()
    assert body["response_type"] == "object", (
        f"a single resource carries response_type 'object', got {body['response_type']!r}"
    )
    assert isinstance(body["meta"].get("api_request_id"), str) and body["meta"][
        "api_request_id"
    ], "the envelope must carry meta.api_request_id"
    assert isinstance(body["meta"].get("api_request_timestamp"), str) and body["meta"][
        "api_request_timestamp"
    ], "the envelope must carry meta.api_request_timestamp"


def test_journal_retrieval_returns_stored_fields(api, librarian_headers):
    """Reading a journal returns exactly the values it was registered with.

    PRD §3.1: "An `AgreementAdmin` registers each journal under its owner by supplying the `publisher_id`, the `issn` in the four-digit, hyphen, three-digit, final-character form (`NNNN-NNNX`) which must be unique across all journals, the `title`, the `oa_model` — one of `FULLY_OA`, `HYBRID` or `SUBSCRIPTION` — the publisher's `list_apc_cents`, which is the list article processing charge in cents and may not be negative, and optionally `required_embargo_months`, the publisher-imposed embargo on the accepted manuscript expressed in whole months, which must be between 0 and 48 inclusive and which defaults to twelve months when omitted."
    PRD §4: "Operations that modify an existing resource, drive a state transition on it, or read data return `200 OK`."
    Design: Corner/entities/corner_journal_retrieval_returns_stored_fields
    """
    publisher, journal = _register_meridian_with_hybrid_journal()

    data = validate_success(api.get_journal(journal["id"], librarian_headers))

    assert data["publisher_id"] == publisher["id"], (
        f"the journal must stay under its owning publisher, got {data['publisher_id']!r}"
    )
    assert data["issn"] == "2041-1723", f"issn must round-trip, got {data['issn']!r}"
    assert data["oa_model"] == "HYBRID", f"oa_model must round-trip, got {data['oa_model']!r}"
    assert data["list_apc_cents"] == 380000, (
        f"list_apc_cents must round-trip exactly, got {data['list_apc_cents']}"
    )
    assert data["required_embargo_months"] == 12, (
        f"required_embargo_months must round-trip, got {data['required_embargo_months']}"
    )
    assert data["title"] == "Meridian Journal of Cell Signalling", (
        f"title must round-trip, got {data['title']!r}"
    )


def test_deposit_system_fields_are_server_assigned(api):
    """The first deposit of an article gets its ordinal, status and stamps from the server.

    PRD §3.8: "A created deposit takes a `version_ordinal` of the article's `latest_deposit_ordinal` plus one, which makes ordinals monotonic and strictly increasing within an article, and it starts in `status` `DRAFT` with no `persistent_identifier`, no `submitted_at`, no `ingested_at`, no `curation_note`, no `embargo_until` and a `returned_count` of zero."
    PRD §3.8: "Creating it also increments the article's `version` by one and updates the article's `latest_deposit_ordinal`."
    PRD §2.4: "`created_at` — an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock at the moment the row was inserted."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    Design: Corner/entities/corner_deposit_system_fields_are_server_assigned
    """
    set_clock("2026-08-10T00:00:00Z")
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = _register_tomas_berg()
    article = record_article(
        journal["id"],
        author["id"],
        manuscript_title="System fields on first deposit",
        accepted_on="2026-08-05",
    )

    payload = create_repository_deposit_payload(
        article["id"],
        article["version"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        license="CC_BY",
    )
    data = validate_success(
        api.create_repository_deposit(
            payload, make_corresponding_author_headers(author["id"])
        ),
        expected_status=201,
    )

    assert data["version_ordinal"] == 1, (
        f"the first deposit of an article takes version_ordinal 1, got {data['version_ordinal']}"
    )
    assert data["status"] == "DRAFT", f"a created deposit starts in DRAFT, got {data['status']!r}"
    assert data.get("persistent_identifier") is None, (
        f"a created deposit has no persistent_identifier, got {data.get('persistent_identifier')!r}"
    )
    assert data["returned_count"] == 0, (
        f"a created deposit has returned_count zero, got {data['returned_count']}"
    )
    assert data["version"] == 1, f"version starts at 1 on creation, got {data['version']}"
    assert data.get("submitted_at") is None, (
        f"a created deposit has no submitted_at, got {data.get('submitted_at')!r}"
    )
    assert data.get("ingested_at") is None, (
        f"a created deposit has no ingested_at, got {data.get('ingested_at')!r}"
    )
    assert data["created_at"].startswith("2026-08-10T00:00:00"), (
        f"created_at is taken from the logical clock 2026-08-10T00:00:00Z, got {data['created_at']!r}"
    )
    assert_timestamp_has_three_fractional_digits(data["created_at"])

    article_after = read_article(article["id"])
    assert article_after["latest_deposit_ordinal"] == 1, (
        "creating the deposit must update the article's latest_deposit_ordinal to 1, "
        f"got {article_after['latest_deposit_ordinal']}"
    )


def test_author_create_omitting_annual_cap_applies_default(api, agreement_admin_headers):
    """Omitted optional fields fall back to the defaults the PRD declares.

    PRD §3.3: "An `AgreementAdmin` registers each corresponding author with the attributes that fund eligibility depends on: a `full_name`, an institutional `email`, an optional `orcid` iD in the four-groups-of-four form (`NNNN-NNNN-NNNN-NNNX`) which must be unique across all authors that have one, a `department_code` used for recharge, an `affiliation_status` drawn from `ELIGIBLE_FACULTY`, `ELIGIBLE_POSTDOC`, `ELIGIBLE_GRAD`, `VISITING`, `EMERITUS` and `UNAFFILIATED`, an `appointment_from` and `appointment_until` pair delimiting the current appointment as a closed window, and an optional `annual_cap_cents` giving the author's own annual subsidy ceiling, which may not be negative and which defaults to five thousand dollars — that is, 500000 cents — when omitted."
    PRD §3.3: "A newly registered author has zero `apc_committed_cents`, zero `apc_disbursed_cents` and zero `linked_output_count`."
    PRD §3.3: "The ORCID iD is optional at registration but becomes mandatory later: without it, no deposit of the author's work can be ingested, because ingest is what links the deposited output to the author profile."
    PRD §3.1: "An `AgreementAdmin` registers each journal under its owner by supplying the `publisher_id`, the `issn` in the four-digit, hyphen, three-digit, final-character form (`NNNN-NNNX`) which must be unique across all journals, the `title`, the `oa_model` — one of `FULLY_OA`, `HYBRID` or `SUBSCRIPTION` — the publisher's `list_apc_cents`, which is the list article processing charge in cents and may not be negative, and optionally `required_embargo_months`, the publisher-imposed embargo on the accepted manuscript expressed in whole months, which must be between 0 and 48 inclusive and which defaults to twelve months when omitted."
    Design: Corner/entities/corner_author_create_omitting_annual_cap_applies_default
    """
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )

    author_payload = create_author_payload(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
    )
    assert "annual_cap_cents" not in author_payload, "the payload must omit annual_cap_cents"
    assert "orcid" not in author_payload, "the payload must omit orcid"
    author = validate_success(
        api.create_author(author_payload, agreement_admin_headers), expected_status=201
    )

    journal_payload = create_journal_payload(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
    )
    assert "required_embargo_months" not in journal_payload, (
        "the payload must omit required_embargo_months"
    )
    journal = validate_success(
        api.create_journal(journal_payload, agreement_admin_headers), expected_status=201
    )

    assert author["annual_cap_cents"] == 500000, (
        f"an omitted annual_cap_cents defaults to 500000 cents, got {author['annual_cap_cents']}"
    )
    assert author.get("orcid") is None, (
        f"an omitted orcid stays absent, got {author.get('orcid')!r}"
    )
    assert author["apc_committed_cents"] == 0, (
        f"a new author has zero apc_committed_cents, got {author['apc_committed_cents']}"
    )
    assert author["apc_disbursed_cents"] == 0, (
        f"a new author has zero apc_disbursed_cents, got {author['apc_disbursed_cents']}"
    )
    assert author["linked_output_count"] == 0, (
        f"a new author has zero linked_output_count, got {author['linked_output_count']}"
    )
    assert journal["required_embargo_months"] == 12, (
        "an omitted required_embargo_months defaults to twelve months, got "
        f"{journal['required_embargo_months']}"
    )


def test_agreement_coverage_carries_no_version_or_updated_at(api, agreement_admin_headers):
    """A coverage line is an append-only ledger row: no version, no updated_at.

    PRD §2.4: "Two entities are append-only ledger rows that are never revised after insertion, and they therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from an `AgreementCoverage` and from an `EligibilityDetermination`."
    PRD §3.2: "A coverage line names a `journal_id`, a `coverage_type` of `FULL_APC`, `CAPPED_APC` or `READ_ONLY`, an optional `capped_amount_cents`, and a `covered_from` and `covered_until` pair whose window is closed at both ends."
    PRD §3.2: "`CAPPED_APC` means the agreement pays up to a per-article ceiling, and for this type `capped_amount_cents` is required and must be greater than zero; for the other two types it must be absent."
    Design: Corner/entities/corner_agreement_coverage_is_immutable_without_version_field
    """
    publisher, journal = _register_meridian_with_hybrid_journal()
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )

    payload = create_agreement_coverage_payload(
        journal["id"],
        coverage_type="READ_ONLY",
        covered_from="2026-07-01",
        covered_until="2027-06-30",
    )
    data = validate_success(
        api.create_agreement_coverage(agreement["id"], payload, agreement_admin_headers),
        expected_status=201,
    )

    assert data["coverage_type"] == "READ_ONLY", (
        f"coverage_type must round-trip, got {data['coverage_type']!r}"
    )
    assert data.get("capped_amount_cents") is None, (
        "capped_amount_cents must be absent unless coverage_type is CAPPED_APC, got "
        f"{data.get('capped_amount_cents')!r}"
    )
    assert "version" not in data or data["version"] is None, (
        "an AgreementCoverage carries no version field"
    )
    assert "updated_at" not in data or data["updated_at"] is None, (
        "an AgreementCoverage carries no updated_at field"
    )
    assert_append_only_fields(data)

    rows, _meta = validate_paginated(
        api.list_agreement_coverages(agreement["id"], agreement_admin_headers)
    )
    assert len(rows) == 1, f"the agreement should hold exactly one coverage line, got {len(rows)}"
    assert rows[0]["id"] == data["id"], (
        f"the listed coverage line should be the created one, got {rows[0]['id']!r}"
    )


def test_coverage_junction_links_many_agreements_to_many_journals(
    api, agreement_admin_headers
):
    """Coverage lines form a many-to-many junction between agreements and journals.

    PRD §3.2: "A coverage line names a `journal_id`, a `coverage_type` of `FULL_APC`, `CAPPED_APC` or `READ_ONLY`, an optional `capped_amount_cents`, and a `covered_from` and `covered_until` pair whose window is closed at both ends."
    PRD §3.1: "Read views exist to list a publisher's journals, optionally narrowed by `publisher_id` and by `oa_model`; to list a publisher's agreements, optionally narrowed by `publisher_id` and by `status`; and to list every coverage line touching a given journal across all agreements, optionally narrowed by `journal_id`."
    Design: Corner/entities/corner_coverage_junction_links_many_agreements_to_many_journals
    """
    publisher, journal_one = _register_meridian_with_hybrid_journal()
    journal_two = register_journal(
        publisher["id"],
        issn="2397-3374",
        title="Meridian Journal of Structural Biology",
        oa_model="HYBRID",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    agreement_one = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-H1",
        effective_from="2026-07-01",
        effective_until="2026-10-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    agreement_two = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-H2",
        effective_from="2026-10-01",
        effective_until="2027-01-01",
        article_quota=5,
        discount_pct=0.25,
        covered_oa_models=["HYBRID"],
    )
    coverage_a1j1 = add_coverage(
        agreement_one["id"],
        journal_one["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-09-30",
    )
    coverage_a1j2 = add_coverage(
        agreement_one["id"],
        journal_two["id"],
        coverage_type="CAPPED_APC",
        capped_amount_cents=150000,
        covered_from="2026-07-01",
        covered_until="2026-09-30",
    )

    payload = create_agreement_coverage_payload(
        journal_one["id"],
        coverage_type="FULL_APC",
        covered_from="2026-10-02",
        covered_until="2026-12-31",
    )
    coverage_a2j1 = validate_success(
        api.create_agreement_coverage(
            agreement_two["id"], payload, agreement_admin_headers
        ),
        expected_status=201,
    )

    assert coverage_a2j1["journal_id"] == journal_one["id"], (
        f"the new coverage line must name journal one, got {coverage_a2j1['journal_id']!r}"
    )

    rows_a1, _ = validate_paginated(
        api.list_agreement_coverages(agreement_one["id"], agreement_admin_headers)
    )
    assert {row["id"] for row in rows_a1} == {coverage_a1j1["id"], coverage_a1j2["id"]}, (
        f"agreement one should hold its two coverage lines, got {[r['id'] for r in rows_a1]}"
    )

    rows_a2, _ = validate_paginated(
        api.list_agreement_coverages(agreement_two["id"], agreement_admin_headers)
    )
    assert [row["id"] for row in rows_a2] == [coverage_a2j1["id"]], (
        f"agreement two should hold exactly its one coverage line, got {[r['id'] for r in rows_a2]}"
    )

    rows_j1, meta_j1 = validate_paginated(
        api.list_journal_coverages(journal_one["id"], agreement_admin_headers)
    )
    assert meta_j1["total_count"] == 2, (
        f"journal one is covered by two agreements, got total_count {meta_j1['total_count']}"
    )
    assert {row["id"] for row in rows_j1} == {coverage_a1j1["id"], coverage_a2j1["id"]}, (
        f"journal one's coverage lines should span both agreements, got {[r['id'] for r in rows_j1]}"
    )

    rows_j2, meta_j2 = validate_paginated(
        api.list_journal_coverages(journal_two["id"], agreement_admin_headers)
    )
    assert meta_j2["total_count"] == 1, (
        f"journal two is covered once, got total_count {meta_j2['total_count']}"
    )
    assert [row["id"] for row in rows_j2] == [coverage_a1j2["id"]], (
        f"journal two should hold exactly its one coverage line, got {[r['id'] for r in rows_j2]}"
    )


# --------------------------------------------------------------------------- #
# list views
# --------------------------------------------------------------------------- #
def test_article_listing_paginates_with_total_count_and_has_more(api, librarian_headers):
    """Article pages carry the resolved window, the pre-pagination count and has_more.

    PRD §2.3: "When a list endpoint responds, the `meta` object carries `limit` and `offset` as they were resolved for the request, `total_count` as the number of rows matching the filters before pagination was applied, and `has_more` as a boolean that is true exactly when rows matching the filters remain beyond the current page."
    PRD §2.3: "List results are ordered by `created_at` ascending unless a specific endpoint narrative states otherwise; rows created earlier appear earlier in the page."
    PRD §3.4: "Articles may be listed with optional `journal_id`, `corresponding_author_id`, `grant_id`, `funding_status` and `compliance_status` filters, and read individually to see both dimensions together with the coverage amounts."
    PRD §3.4: "A newly recorded article always starts with `funding_status` `DRAFT`, while its `compliance_status` is set at creation to either `PENDING_DEPOSIT` or `EXEMPT` by the mandate rule described in §3.8, which also sets `deposit_deadline_on` and `embargo_until`."
    Design: Corner/entities/corner_article_listing_paginates_with_total_count_and_has_more
    """
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = _register_tomas_berg()
    for title in ("Listing fixture one", "Listing fixture two", "Listing fixture three"):
        record_article(
            journal["id"],
            author["id"],
            headers=librarian_headers,
            manuscript_title=title,
            accepted_on="2026-08-05",
        )

    first_response = api.list_articles(
        librarian_headers, params={"limit": 2, "offset": 0}
    )
    first_rows, first_meta = validate_paginated(first_response)
    assert len(first_rows) == 2, f"the first page should hold 2 rows, got {len(first_rows)}"
    assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
    assert first_response.json()["response_type"] == "array", (
        "a list endpoint carries response_type 'array'"
    )

    second_rows, second_meta = validate_paginated(
        api.list_articles(librarian_headers, params={"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1, f"the second page should hold 1 row, got {len(second_rows)}"
    assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)

    filtered_rows, filtered_meta = validate_paginated(
        api.list_articles(
            librarian_headers, params={"funding_status": "DRAFT", "limit": 10, "offset": 0}
        )
    )
    assert len(filtered_rows) == 3, (
        f"all three articles are in funding_status DRAFT, got {len(filtered_rows)} rows"
    )
    assert filtered_meta["total_count"] == 3, (
        f"the DRAFT filter matches three rows, got total_count {filtered_meta['total_count']}"
    )
    assert filtered_meta["has_more"] is False, (
        f"a page of 10 exhausts three rows, got has_more {filtered_meta['has_more']}"
    )

    first_ids = {row["id"] for row in first_rows}
    second_ids = {row["id"] for row in second_rows}
    assert not first_ids & second_ids, (
        f"pages must not overlap, {first_ids & second_ids} appeared twice"
    )


# --------------------------------------------------------------------------- #
# rejections
# --------------------------------------------------------------------------- #
def test_journal_read_with_unknown_id_returns_not_found(api, librarian_headers):
    """Reading a journal id that was never issued is a 404 with the journal code.

    PRD §2.5: "Each entity has its own not-found code, all of them HTTP 404: `ERR_PUBLISHER_NOT_FOUND`, `ERR_JOURNAL_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_AUTHOR_NOT_FOUND`, `ERR_FUNDER_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_FUND_REQUEST_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`."
    Design: Corner/entities/corner_journal_read_with_unknown_id_returns_not_found
    """
    response = api.get_journal(NON_EXISTENT_UUID, librarian_headers)

    validate_error(response, ApiErrorId.ERR_JOURNAL_NOT_FOUND.value)
    assert response.json()["response_type"] == "error", (
        "a rejection carries response_type 'error'"
    )


def test_journal_create_missing_required_oa_model_returns_invalid_request(
    api, agreement_admin_headers
):
    """Omitting the required oa_model is a malformed request and stores nothing.

    PRD §2.11: "Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`."
    PRD §2.11: "Otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "An `AgreementAdmin` registers each journal under its owner by supplying the `publisher_id`, the `issn` in the four-digit, hyphen, three-digit, final-character form (`NNNN-NNNX`) which must be unique across all journals, the `title`, the `oa_model` — one of `FULLY_OA`, `HYBRID` or `SUBSCRIPTION` — the publisher's `list_apc_cents`, which is the list article processing charge in cents and may not be negative, and optionally `required_embargo_months`, the publisher-imposed embargo on the accepted manuscript expressed in whole months, which must be between 0 and 48 inclusive and which defaults to twelve months when omitted."
    Design: Corner/entities/corner_journal_create_missing_required_oa_model_returns_invalid_request
    """
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )

    payload = create_journal_payload(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        list_apc_cents=300000,
    )
    payload.pop("oa_model")

    validate_error(
        api.create_journal(payload, agreement_admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(
        api.list_publisher_journals(publisher["id"], agreement_admin_headers)
    )
    assert rows == [] and meta["total_count"] == 0, (
        f"the rejected create must store no journal, got {meta['total_count']} rows"
    )


@pytest.mark.parametrize(
    "field, value",
    [("oa_model", "DIAMOND_OA"), ("list_apc_cents", -1)],
    ids=["oa_model_outside_enum", "negative_list_apc_cents"],
)
def test_journal_create_with_out_of_range_field_is_rejected(
    api, agreement_admin_headers, field, value
):
    """An unrecognised oa_model and a negative list charge are both malformed.

    PRD §2.11: "Required fields are present; enum members are recognised; integer amounts are not negative; discount and VAT fractions lie inside their declared ranges; `currency` is `USD`; `capped_amount_cents` is present when and only when `coverage_type` is `CAPPED_APC`; the pagination `limit` lies in 1 through 100 and `offset` is not negative; `effective_until` is strictly after `effective_from`; `covered_until` is not before `covered_from`."
    PRD §2.11: "Otherwise `ERR_INVALID_REQUEST` (400)."
    PRD §3.1: "An `AgreementAdmin` registers each journal under its owner by supplying the `publisher_id`, the `issn` in the four-digit, hyphen, three-digit, final-character form (`NNNN-NNNX`) which must be unique across all journals, the `title`, the `oa_model` — one of `FULLY_OA`, `HYBRID` or `SUBSCRIPTION` — the publisher's `list_apc_cents`, which is the list article processing charge in cents and may not be negative, and optionally `required_embargo_months`, the publisher-imposed embargo on the accepted manuscript expressed in whole months, which must be between 0 and 48 inclusive and which defaults to twelve months when omitted."
    Design: Corner/entities/corner_journal_create_with_invalid_oa_model_enum_rejected
    """
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )

    payload = create_journal_payload(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
    )
    payload[field] = value

    validate_error(
        api.create_journal(payload, agreement_admin_headers),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )

    rows, meta = validate_paginated(
        api.list_publisher_journals(publisher["id"], agreement_admin_headers)
    )
    assert rows == [] and meta["total_count"] == 0, (
        f"the rejected create must store no journal, got {meta['total_count']} rows"
    )


def test_journal_create_with_unknown_publisher_returns_not_found(
    api, agreement_admin_headers
):
    """A body foreign key that resolves to nothing is a 404 before any other check.

    PRD §2.5: "Requests are checked for the existence of everything they reference before any business rule is evaluated."
    PRD §2.5: "Each entity has its own not-found code, all of them HTTP 404: `ERR_PUBLISHER_NOT_FOUND`, `ERR_JOURNAL_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_COVERAGE_NOT_FOUND`, `ERR_AUTHOR_NOT_FOUND`, `ERR_FUNDER_NOT_FOUND`, `ERR_GRANT_NOT_FOUND`, `ERR_FUND_NOT_FOUND`, `ERR_ARTICLE_NOT_FOUND`, `ERR_DETERMINATION_NOT_FOUND`, `ERR_FUND_REQUEST_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND` and `ERR_DEPOSIT_NOT_FOUND`."
    Design: Corner/entities/corner_journal_create_with_unknown_publisher_returns_not_found
    """
    payload = create_journal_payload(
        NON_EXISTENT_UUID,
        issn="2515-0847",
        title="Orphan Journal",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
    )

    validate_error(
        api.create_journal(payload, agreement_admin_headers),
        ApiErrorId.ERR_PUBLISHER_NOT_FOUND.value,
    )
