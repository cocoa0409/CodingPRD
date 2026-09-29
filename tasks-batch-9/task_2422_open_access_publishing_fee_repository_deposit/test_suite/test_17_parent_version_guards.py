"""Optimistic concurrency control on the two guarded create operations.

Drafting an agreement is guarded on the publisher's ``version`` and creating a
repository deposit is guarded on the article's ``version``.  Both guards compare
against the live version of the parent, so replaying a value that some other
mutation has since superseded is refused and writes nothing, while the refreshed
value creates the child.
"""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_repository_deposit_payload,
    create_transformative_agreement_payload,
    create_deposit,
    curate_deposit,
    make_corresponding_author_headers,
    read_article,
    read_deposit,
    read_publisher,
    record_article,
    register_author,
    register_journal,
    register_publisher,
    screen_publisher,
    set_clock,
    submit_deposit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["agreement_admin_headers"]
LIBRARIAN_HEADERS = TEST_USERS["librarian_headers"]


# --------------------------------------------------------------------------- #
# local preambles
# --------------------------------------------------------------------------- #
def _setup_article_with_ingested_first_deposit() -> dict:
    """An article whose first deposit has been carried all the way to INGESTED,
    capturing the article's version as it was at creation."""
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
    author = register_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        headers=LIBRARIAN_HEADERS,
        manuscript_title="Versioned deposits",
        accepted_on="2026-08-05",
    )
    first_deposit = create_deposit(
        article["id"],
        author["id"],
        expected_article_version=article["version"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="1122334455667788990011223344556677889900112233445566778899001122",
        license="CC_BY",
    )
    submit_deposit(first_deposit["id"], author["id"])
    ingested = curate_deposit(first_deposit["id"], "INGEST")
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "article_version_at_creation": article["version"],
        "article": read_article(article["id"]),
        "first_deposit": ingested,
    }


# --------------------------------------------------------------------------- #
# POST /transformative-agreements — expected_publisher_version
# --------------------------------------------------------------------------- #
def test_agreement_draft_with_a_superseded_publisher_version_is_rejected(api):
    """The publisher's version is read before a screening run bumps it. Replaying
    the earlier value is refused with ERR_STALE_PARENT_VERSION and writes nothing;
    re-reading the publisher and sending the current value drafts the agreement.

    PRD §2.6: "Drafting a transformative agreement requires `expected_publisher_version` in the request body, carrying the client's last observed `version` of the `Publisher` named by `publisher_id`."
    PRD §2.6: "If that value does not equal the publisher's current `version`, the create is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
    PRD §3.1: "The run also stamps `last_screened_at` from the logical clock and increments the publisher's `version` by one."
    PRD §3.1: "Anything below 35 is `CLEARED`."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    Design: Corner/cross_cutting_complexity_layers/corner_agreement_create_with_a_superseded_publisher_version_is_rejected
    """
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    version_at_registration = publisher["version"]
    assert version_at_registration == 1, (
        f"a freshly registered publisher must be at version 1, got "
        f"{version_at_registration}"
    )

    screened = screen_publisher(
        publisher["id"],
        doaj_indexed=True,
        cope_member=True,
        editorial_board_verified=True,
        retraction_rate_per_1000=0.0,
        peer_review_days_median=30,
        apc_transparency_score=90,
    )
    assert screened["screening_status"] == "CLEARED", (
        "a publisher with no adverse signals and full transparency credit scores "
        f"below 35 and is CLEARED, got {screened['screening_status']!r}"
    )
    assert screened["version"] == 2, (
        f"the screening run must increment the publisher's version to 2, got "
        f"{screened['version']}"
    )

    stale_payload = create_transformative_agreement_payload(
        publisher["id"],
        version_at_registration,
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    refused = api.create_transformative_agreement(stale_payload, ADMIN_HEADERS)
    error = validate_error(refused, ApiErrorId.ERR_STALE_PARENT_VERSION.value)
    assert error["error_id"] == ApiErrorId.ERR_STALE_PARENT_VERSION.value, (
        "replaying the pre-screening publisher version must be refused with "
        f"ERR_STALE_PARENT_VERSION, got {error['error_id']!r}"
    )

    fresh_payload = create_transformative_agreement_payload(
        publisher["id"],
        screened["version"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    agreement = validate_success(
        api.create_transformative_agreement(fresh_payload, ADMIN_HEADERS),
        expected_status=201,
    )
    assert agreement["status"] == "DRAFT", (
        f"a newly drafted agreement must be DRAFT, got {agreement['status']!r}"
    )
    assert agreement["articles_used"] == 0, (
        f"a newly drafted agreement must have articles_used 0, got "
        f"{agreement['articles_used']}"
    )
    assert agreement.get("activated_at") is None, (
        f"a newly drafted agreement must have no activated_at, got "
        f"{agreement.get('activated_at')!r}"
    )

    publisher_after = read_publisher(publisher["id"])
    assert publisher_after["version"] == 3, (
        "the refused draft must write nothing and the accepted draft must bump the "
        f"publisher to version 3, got {publisher_after['version']}"
    )

    agreements, meta = validate_paginated(
        api.list_publisher_agreements(publisher["id"], ADMIN_HEADERS)
    )
    assert meta["total_count"] == 1, (
        f"exactly one agreement must exist for the publisher, got "
        f"{meta['total_count']}"
    )
    assert [row["id"] for row in agreements] == [agreement["id"]], (
        "the only agreement of the publisher must be the one drafted against the "
        "current publisher version"
    )


# --------------------------------------------------------------------------- #
# POST /repository-deposits — expected_article_version
# --------------------------------------------------------------------------- #
def test_deposit_create_with_a_superseded_article_version_is_rejected(api):
    """The article's version is captured at creation, then the first deposit and
    its ingest bump it. Reusing the captured value is refused with
    ERR_STALE_PARENT_VERSION, while the refreshed value creates version_ordinal 2
    and leaves the previously ingested deposit as it stands.

    PRD §2.6: "Creating a repository deposit requires `expected_article_version` in the request body, carrying the client's last observed `version` of the `Article` named by `article_id`."
    PRD §2.6: "If that value does not equal the article's current `version`, the create is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412)."
    PRD §3.8: "A created deposit takes a `version_ordinal` of the article's `latest_deposit_ordinal` plus one, which makes ordinals monotonic and strictly increasing within an article, and it starts in `status` `DRAFT` with no `persistent_identifier`, no `submitted_at`, no `ingested_at`, no `curation_note`, no `embargo_until` and a `returned_count` of zero."
    PRD §3.8: "Creating it also increments the article's `version` by one and updates the article's `latest_deposit_ordinal`."
    Design: Corner/cross_cutting_complexity_layers/corner_deposit_create_with_a_superseded_article_version_is_rejected
    """
    set_clock("2026-08-12T00:00:00Z")
    scenario = _setup_article_with_ingested_first_deposit()
    article = scenario["article"]
    stale_version = scenario["article_version_at_creation"]
    first_deposit = scenario["first_deposit"]

    assert first_deposit["version_ordinal"] == 1, (
        f"the first deposit of an article must take version_ordinal 1, got "
        f"{first_deposit['version_ordinal']}"
    )
    assert first_deposit["status"] == "INGESTED", (
        f"the first deposit must have reached INGESTED, got "
        f"{first_deposit['status']!r}"
    )
    assert article["latest_deposit_ordinal"] == 1, (
        f"the article's latest_deposit_ordinal must be 1 after the first ingest, got "
        f"{article['latest_deposit_ordinal']}"
    )
    assert article["version"] != stale_version, (
        "creating and ingesting the first deposit must have moved the article's "
        f"version away from {stale_version}"
    )

    stale_payload = create_repository_deposit_payload(
        article["id"],
        stale_version,
        version_label="VERSION_OF_RECORD",
        file_checksum="2233445566778899001122334455667788990011223344556677889900112233",
        license="CC_BY",
    )
    author_headers = make_corresponding_author_headers(scenario["author"]["id"])
    refused = api.create_repository_deposit(stale_payload, author_headers)
    error = validate_error(refused, ApiErrorId.ERR_STALE_PARENT_VERSION.value)
    assert error["error_id"] == ApiErrorId.ERR_STALE_PARENT_VERSION.value, (
        "reusing the article version captured before the first deposit must be "
        f"refused with ERR_STALE_PARENT_VERSION, got {error['error_id']!r}"
    )

    fresh_payload = create_repository_deposit_payload(
        article["id"],
        article["version"],
        version_label="VERSION_OF_RECORD",
        file_checksum="2233445566778899001122334455667788990011223344556677889900112233",
        license="CC_BY",
    )
    second_deposit = validate_success(
        api.create_repository_deposit(fresh_payload, author_headers),
        expected_status=201,
    )
    assert second_deposit["version_ordinal"] == 2, (
        f"the second deposit must take version_ordinal 2, got "
        f"{second_deposit['version_ordinal']}"
    )
    assert second_deposit["status"] == "DRAFT", (
        f"a created deposit starts in DRAFT, got {second_deposit['status']!r}"
    )
    assert second_deposit.get("persistent_identifier") is None, (
        "a created deposit carries no persistent_identifier, got "
        f"{second_deposit.get('persistent_identifier')!r}"
    )
    assert second_deposit["returned_count"] == 0, (
        f"a created deposit starts with returned_count 0, got "
        f"{second_deposit['returned_count']}"
    )

    first_after = read_deposit(first_deposit["id"])
    assert first_after["status"] == "INGESTED", (
        "creating a further deposit must not disturb the previously ingested one, "
        f"got {first_after['status']!r}"
    )

    article_after = read_article(article["id"])
    assert article_after["latest_deposit_ordinal"] == 2, (
        "creating the second deposit must update the article's "
        f"latest_deposit_ordinal to 2, got {article_after['latest_deposit_ordinal']}"
    )
