"""Cascades: one call whose effects travel across entities the caller never named.

Publication walks determination to agreement to publisher, and a second ingest walks
new deposit to superseded deposit to article to grant to author profile.
"""

from test_helpers import (
    activate_agreement,
    add_coverage,
    create_deposit,
    curate_deposit,
    draft_agreement,
    publish_article,
    read_agreement,
    read_article,
    read_author,
    read_deposit,
    read_grant,
    read_publisher,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    submit_deposit,
)


# --------------------------------------------------------------------------- #
# preambles
# --------------------------------------------------------------------------- #
def _setup_single_token_agreement_consumed() -> dict:
    """A one-token agreement whose only quota token has been consumed by a
    PROVISIONAL determination, leaving the agreement EXHAUSTED. The agreement's
    coverage line closes on 2026-09-30 while its own window runs to 2026-12-01."""
    set_clock("2026-09-20T00:00:00Z")
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
    author = register_author(
        full_name="Ines Ravel",
        email="ines.ravel@uni.example",
        orcid="0000-0002-1825-0097",
        department_code="BIO",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2026-12-01",
        article_quota=1,
        discount_pct=0.25,
        covered_oa_models=["HYBRID"],
    )
    add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-09-30",
    )
    activated = activate_agreement(agreement["id"])
    article = record_article(
        journal["id"],
        author["id"],
        manuscript_title="Cascade propagation in signalling networks",
        accepted_on="2026-09-15",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "agreement": agreement,
        "activated": activated,
        "article": article,
        "determination": determination,
    }


def _setup_two_deposit_lineage() -> dict:
    """An immediate-CC-BY article whose first deposit is already INGESTED and whose
    second deposit sits in SUBMITTED awaiting curation at clock 2026-08-12."""
    set_clock("2026-08-05T00:00:00Z")
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
    funder = register_funder(
        name="Open Horizon Trust",
        funder_code="OHT",
        mandate_type="IMMEDIATE_CC_BY",
        max_embargo_months=0,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="OHT-2026-004",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Version lineage of deposited manuscripts",
        accepted_on="2026-08-05",
    )

    set_clock("2026-08-10T00:00:00Z")
    first = create_deposit(
        article["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
        license="CC_BY",
    )
    submit_deposit(first["id"], author["id"])
    first_ingested = curate_deposit(first["id"], "INGEST")
    after_first = read_article(article["id"])

    second = create_deposit(
        article["id"],
        author["id"],
        version_label="VERSION_OF_RECORD",
        file_checksum="b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1",
        license="CC_BY",
    )
    submit_deposit(second["id"], author["id"])
    set_clock("2026-08-12T00:00:00Z")
    return {
        "publisher": publisher,
        "journal": journal,
        "author": author,
        "funder": funder,
        "grant": grant,
        "article": article,
        "first_deposit": first_ingested,
        "article_after_first": after_first,
        "second_deposit": second,
    }


# --------------------------------------------------------------------------- #
# publication: determination -> agreement -> publisher
# --------------------------------------------------------------------------- #
def test_provisional_determination_exhausts_the_quota_and_drops_the_publisher_count():
    """The determination that takes the agreement's only token cascades on its own:
    the agreement's articles_used rises to 1, the agreement leaves ACTIVE for
    EXHAUSTED, and the publisher's active_agreement_count falls back to zero.

    PRD §3.2: "Activation by an `AgreementAdmin` moves the agreement from `DRAFT` to `ACTIVE`."
    PRD §3.4: "The `quota_position` is the number of tokens already held on that agreement plus one, making it a one-based index of where this article sits in the agreement's quota."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    PRD §2.10: "`TransformativeAgreement.articles_used` is the number of articles whose effective eligibility determination names this agreement and whose determination route is either `TA_FULL` or `TA_CAPPED`."
    PRD §3.2: "When a determination is written and the recomputed `articles_used` reaches or exceeds `article_quota`, the agreement moves itself from `ACTIVE` to `EXHAUSTED`, which decreases the publisher's `active_agreement_count` by one and increments the publisher's `version` by one."
    PRD §2.10: "`Publisher.active_agreement_count` is the number of that publisher's transformative agreements whose `status` is `ACTIVE`."
    Design: Difficulty/transitive_cascade/publication_cascade_determination_to_agreement_to_publisher
    """
    scenario = _setup_single_token_agreement_consumed()

    assert scenario["activated"]["status"] == "ACTIVE", (
        f"activation moves DRAFT to ACTIVE, got {scenario['activated']['status']!r}"
    )
    assert scenario["determination"]["route"] == "TA_FULL", (
        "the FULL_APC coverage line on the reference date gives TA_FULL, got "
        f"{scenario['determination']['route']!r}"
    )
    assert scenario["determination"]["quota_position"] == 1, (
        "the first token on the agreement is quota_position 1, got "
        f"{scenario['determination']['quota_position']}"
    )

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["articles_used"] == 1, (
        f"the determination holds one quota token, got articles_used {agreement['articles_used']}"
    )
    assert agreement["status"] == "EXHAUSTED", (
        "articles_used reaching the quota of 1 moves the agreement to EXHAUSTED, got "
        f"{agreement['status']!r}"
    )

    publisher = read_publisher(scenario["publisher"]["id"])
    assert publisher["active_agreement_count"] == 0, (
        "the publisher's only agreement is no longer ACTIVE, so the count is 0, got "
        f"{publisher['active_agreement_count']}"
    )


def test_publication_releases_the_token_reactivating_the_agreement_and_bumping_the_publisher():
    """One publication call reaches four entities the caller never named: a second
    FINAL determination on the article, the released quota token on the agreement,
    the agreement's return from EXHAUSTED to ACTIVE, and the publisher's
    recomputed count with its version incremented by exactly one.

    PRD §3.6: "On success the `publication_date` is stored and a `doi` is minted in the form of the literal prefix `10.5555/`, then the publisher's `publisher_code`, then a full stop, then the publication sequence number — a server-maintained, institution-wide counter that begins at 1 and increases by one for every article published."
    PRD §3.6: "The third effect is the one with the widest reach: publication automatically runs a further coverage determination on the `FINAL` basis, exactly as described in §3.4 but with `reference_date` taken from the `publication_date` just set, with `list_base_cents` preferring the article's own `apc_list_cents` when it has one, and with the chronological quota gate that counts only committed tokens."
    PRD §3.6: "That determination is appended with the next `sequence_no`, `determination_count` rises by one, and it becomes the effective determination — which means the price the invoice will later be checked against is the price as at publication, not the price as at acceptance."
    PRD §3.6: "Because a new determination has become effective, `articles_used` is recomputed on the agreement the previous determination had selected, releasing its quota token, and on whichever agreement the final determination selects."
    PRD §3.6: "An agreement sitting in `EXHAUSTED` whose recomputed `articles_used` has fallen below its `article_quota` moves back to `ACTIVE`, provided the clock date is still strictly before its `effective_until`; the publisher's `active_agreement_count` is recomputed and the publisher's `version` is incremented by one whenever an agreement's status changes this way."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §2.10: "`Publisher.active_agreement_count` is the number of that publisher's transformative agreements whose `status` is `ACTIVE`. Whenever an agreement of a publisher changes `status`, this count is recomputed and `Publisher.version` is incremented by one."
    Design: Difficulty/transitive_cascade/publication_cascade_determination_to_agreement_to_publisher
    """
    scenario = _setup_single_token_agreement_consumed()
    version_before_publication = read_publisher(scenario["publisher"]["id"])["version"]

    set_clock("2026-11-20T00:00:00Z")
    published = publish_article(scenario["article"]["id"], "2026-11-20")

    assert published["eligibility_route"] == "AUTHOR_PAYS", (
        "the coverage line closed on 2026-09-30, so the FINAL determination at "
        f"2026-11-20 routes AUTHOR_PAYS, got {published['eligibility_route']!r}"
    )
    assert published["determination_count"] == 2, (
        "publication appends a second determination, got determination_count "
        f"{published['determination_count']}"
    )
    assert published.get("doi") is not None, (
        f"publication mints a doi, got {published.get('doi')!r}"
    )
    assert read_article(scenario["article"]["id"])["publication_date"] == "2026-11-20", (
        "the supplied publication_date is stored, got "
        f"{read_article(scenario['article']['id'])['publication_date']!r}"
    )

    agreement = read_agreement(scenario["agreement"]["id"])
    assert agreement["articles_used"] == 0, (
        "the superseded determination's token is handed back, so articles_used is 0, got "
        f"{agreement['articles_used']}"
    )
    assert agreement["status"] == "ACTIVE", (
        "articles_used below the quota with the clock still before 2026-12-01 returns "
        f"the agreement to ACTIVE, got {agreement['status']!r}"
    )

    publisher = read_publisher(scenario["publisher"]["id"])
    assert publisher["active_agreement_count"] == 1, (
        "the reactivated agreement is counted again, expected 1, got "
        f"{publisher['active_agreement_count']}"
    )
    assert publisher["version"] == version_before_publication + 1, (
        "the single agreement status change increments the publisher version exactly "
        f"once, expected {version_before_publication + 1}, got {publisher['version']}"
    )


# --------------------------------------------------------------------------- #
# ingest: new deposit -> superseded deposit -> article -> grant -> author
# --------------------------------------------------------------------------- #
def test_first_ingest_of_an_immediate_cc_by_output_marks_the_article_compliant():
    """With an IMMEDIATE_CC_BY mandate the embargo length is zero, so embargo_until
    equals the acceptance date and the ingest on 2026-08-10 lands on or after it:
    the article is COMPLIANT at the first deposit and carries ordinal 1.

    PRD §3.8: "The embargo length in months is zero when the funder's `mandate_type` is `IMMEDIATE_CC_BY`, and otherwise the smaller of the funder's `max_embargo_months` and the journal's `required_embargo_months` — the institution never applies a longer embargo than either party requires."
    PRD §3.8: "Otherwise, if the clock date is **on or after** `embargo_until`, the article is `COMPLIANT`; the embargo releases on its stated date rather than the day after."
    PRD §3.8: "A created deposit takes a `version_ordinal` of the article's `latest_deposit_ordinal` plus one, which makes ordinals monotonic and strictly increasing within an article, and it starts in `status` `DRAFT` with no `persistent_identifier`, no `submitted_at`, no `ingested_at`, no `curation_note`, no `embargo_until` and a `returned_count` of zero."
    PRD §3.8: "On success the deposit moves from `SUBMITTED` to `INGESTED`, `ingested_at` is stamped from the logical clock, and a `persistent_identifier` is minted as the literal prefix `hdl:2027/ir.` followed by the institutional ingest counter rendered as six digits with leading zeros — the counter begins at 1, so the first ingest in the system produces `hdl:2027/ir.000001`."
    PRD §2.10: "`Article.determination_count` is the number of determinations written for that article and equals the highest `sequence_no` among them; `Article.latest_deposit_ordinal` is the highest `version_ordinal` among that article's deposits."
    Design: Difficulty/transitive_cascade/ingest_cascade_supersede_to_article_to_grant
    """
    scenario = _setup_two_deposit_lineage()
    article_after_first = scenario["article_after_first"]

    assert article_after_first["compliance_status"] == "COMPLIANT", (
        "a zero-month embargo is already released at ingest, so the article is "
        f"COMPLIANT, got {article_after_first['compliance_status']!r}"
    )
    assert article_after_first["latest_deposit_ordinal"] == 1, (
        "the first deposit carries ordinal 1, got "
        f"{article_after_first['latest_deposit_ordinal']}"
    )
    assert scenario["first_deposit"].get("persistent_identifier") is not None, (
        "the first ingest mints a persistent identifier, got "
        f"{scenario['first_deposit'].get('persistent_identifier')!r}"
    )
    assert scenario["second_deposit"]["version_ordinal"] == 2, (
        "the second deposit takes latest_deposit_ordinal plus one, expected 2, got "
        f"{scenario['second_deposit']['version_ordinal']}"
    )


def test_second_ingest_supersedes_the_first_deposit_and_recomputes_the_whole_chain():
    """The one curation-decision call on the second deposit propagates through four
    entities: the new deposit is INGESTED with its own identifier, the earlier
    deposit becomes SUPERSEDED while keeping its identifier, the article's ordinal
    and compliance are recomputed, the grant reaches SATISFIED, and the author's
    linked_output_count is recomputed.

    PRD §3.8: "On success the deposit moves from `SUBMITTED` to `INGESTED`, `ingested_at` is stamped from the logical clock, and a `persistent_identifier` is minted as the literal prefix `hdl:2027/ir.` followed by the institutional ingest counter rendered as six digits with leading zeros — the counter begins at 1, so the first ingest in the system produces `hdl:2027/ir.000001`."
    PRD §3.8: "First, any other deposit of the same article that was in `INGESTED` becomes `SUPERSEDED`; a superseded row **retains its `persistent_identifier`** so that citations of the older version keep resolving, and `SUPERSEDED` is terminal."
    PRD §3.8: "Second, the article's `latest_deposit_ordinal`, `embargo_until` and `compliance_status` are recomputed by the mandate rule above, moving the compliance dimension from `PENDING_DEPOSIT` to `EMBARGOED` when the embargo has not yet elapsed, to `COMPLIANT` when it has, and to `NON_COMPLIANT` when the ingest came after the deadline."
    PRD §3.8: "Third, the grant's `compliant_output_count` and `mandate_status` are recomputed."
    PRD §3.8: "The author's `linked_output_count` is recomputed as well, since it counts ingested deposits of that author's articles."
    PRD §3.8: "`Grant.output_count` is the number of articles referencing the grant and `Grant.compliant_output_count` is how many of those are `COMPLIANT` or `EXEMPT`."
    PRD §3.8: "Otherwise, if the grant has at least one article and every one of them is `COMPLIANT` or `EXEMPT`, the `mandate_status` is `SATISFIED`."
    PRD §2.10: "`Author.linked_output_count` is the number of that author's articles' deposits whose `status` is `INGESTED`, counted across deposits whose article has this author as corresponding author."
    Design: Difficulty/transitive_cascade/ingest_cascade_supersede_to_article_to_grant
    """
    scenario = _setup_two_deposit_lineage()
    first_identifier = scenario["first_deposit"]["persistent_identifier"]

    second_ingested = curate_deposit(scenario["second_deposit"]["id"], "INGEST")

    assert second_ingested["status"] == "INGESTED", (
        f"the second deposit must reach INGESTED, got {second_ingested['status']!r}"
    )
    assert second_ingested.get("persistent_identifier") is not None, (
        "the second ingest mints its own persistent identifier, got "
        f"{second_ingested.get('persistent_identifier')!r}"
    )
    assert second_ingested["persistent_identifier"] != first_identifier, (
        "each ingest draws the next value of the ingest counter, so the identifiers "
        f"differ, got {second_ingested['persistent_identifier']!r} twice"
    )

    superseded = read_deposit(scenario["first_deposit"]["id"])
    assert superseded["status"] == "SUPERSEDED", (
        "the previously ingested deposit becomes SUPERSEDED, got "
        f"{superseded['status']!r}"
    )
    assert superseded["persistent_identifier"] == first_identifier, (
        "a superseded row retains its persistent identifier so older citations keep "
        f"resolving, expected {first_identifier!r}, got "
        f"{superseded['persistent_identifier']!r}"
    )

    article = read_article(scenario["article"]["id"])
    assert article["latest_deposit_ordinal"] == 2, (
        f"the article's ordinal follows the new deposit, got {article['latest_deposit_ordinal']}"
    )
    assert article["compliance_status"] == "COMPLIANT", (
        "the recomputed verdict is still COMPLIANT under the zero-month embargo, got "
        f"{article['compliance_status']!r}"
    )
    assert article["embargo_until"] == "2026-08-05", (
        "an unpublished article measures its zero-month embargo from acceptance, "
        f"expected 2026-08-05, got {article['embargo_until']!r}"
    )

    grant = read_grant(scenario["grant"]["id"])
    assert grant["output_count"] == 1, (
        f"one article references the grant, got output_count {grant['output_count']}"
    )
    assert grant["compliant_output_count"] == 1, (
        "the grant's only article is COMPLIANT, got "
        f"{grant['compliant_output_count']}"
    )
    assert grant["mandate_status"] == "SATISFIED", (
        "every article of the grant is COMPLIANT, so the mandate is SATISFIED, got "
        f"{grant['mandate_status']!r}"
    )

    author = read_author(scenario["author"]["id"])
    assert author["linked_output_count"] == 1, (
        "only the surviving INGESTED deposit is counted, expected 1, got "
        f"{author['linked_output_count']}"
    )
