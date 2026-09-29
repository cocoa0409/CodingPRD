"""Lifecycle transitions: initial states, valid edges, refused edges and cascades.

Each test drives one documented transition (or one documented refusal) and then
reads back every row the PRD says the transition touches — and, where the PRD says
a row must not move, reads that row back too.
"""

from test_helpers import (
    ApiErrorId,
    activate_agreement,
    add_coverage,
    assert_persistent_identifier_format,
    assert_timestamp_has_three_fractional_digits,
    create_curation_decision_payload,
    create_payment_payload,
    create_transformative_agreement_payload,
    create_deposit,
    curate_deposit,
    decide_request,
    draft_agreement,
    make_corresponding_author_headers,
    open_fund,
    open_fund_request,
    read_agreement,
    read_article,
    read_deposit,
    read_publisher,
    receive_invoice,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    start_review,
    submit_deposit,
    validate_error,
    validate_invoice,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# private preamble helpers (multi-step setups that fixtures.py does not offer)
# --------------------------------------------------------------------------- #
def _register_meridian_with_hybrid_journal():
    """Publisher MERID and its HYBRID journal listed at 380000 cents."""
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


def _register_halden_with_fully_oa_journal():
    """Publisher HALDEN and its FULLY_OA journal listed at 300000 cents."""
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
    return publisher, journal


def _register_tomas_berg():
    """The ORCID-bearing faculty author used by the deposit scenarios."""
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


def _register_nrc_gold_oa_grant(author_id):
    """A GOLD_OA funder with a 90-day deposit deadline and one ACTIVE award."""
    funder = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author_id,
        grant_number="NRC-2026-0451",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=1000000,
    )
    return funder, grant


def _draft_meridian_agreement_with_coverage(publisher_id, journal_id, **overrides):
    """A DRAFT agreement over the HYBRID journal with one FULL_APC coverage line."""
    agreement_kwargs = {
        "agreement_code": "TA-MERID-2027",
        "effective_from": "2026-07-01",
        "effective_until": "2027-07-01",
        "article_quota": 5,
        "discount_pct": 0.20,
        "covered_oa_models": ["HYBRID"],
    }
    agreement_kwargs.update(overrides)
    agreement = draft_agreement(publisher_id, **agreement_kwargs)
    coverage = add_coverage(
        agreement["id"],
        journal_id,
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2027-06-30",
    )
    return agreement, coverage


# --------------------------------------------------------------------------- #
# transformative agreement lifecycle
# --------------------------------------------------------------------------- #
def test_agreement_initial_state_is_draft_with_zero_quota_used(
    api, agreement_admin_headers
):
    """A drafted agreement starts DRAFT with no quota used and no activation stamp.

    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    PRD §3.1: "A freshly registered publisher has not been screened: its `screening_status` is `UNSCREENED`, its `predatory_score` is absent, its `active_agreement_count` is zero, and the signal snapshot fields and `author_guidance` and `last_screened_at` are all absent."
    PRD §3.2: "Activation stamps `activated_at` from the logical clock, recomputes the publisher's `active_agreement_count` — which rises by one, since the agreement has just become active — and increments the publisher's `version` by one."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    PRD §4: "Operations that mint a brand-new, independently addressable resource — registering a publisher, journal, agreement, coverage line, author, funder, grant or fund; recording an article; appending an eligibility determination; opening a fund request; receiving an invoice; creating a deposit — return `201 Created`."
    Design: Corner/state_machines/corner_agreement_initial_state_is_draft_with_zero_quota_used
    """
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )

    payload = create_transformative_agreement_payload(
        publisher["id"],
        publisher["version"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    agreement = validate_success(
        api.create_transformative_agreement(payload, agreement_admin_headers),
        expected_status=201,
    )

    assert agreement["status"] == "DRAFT", (
        f"a newly drafted agreement starts DRAFT, got {agreement['status']!r}"
    )
    assert agreement["articles_used"] == 0, (
        f"a newly drafted agreement has articles_used zero, got {agreement['articles_used']}"
    )
    assert agreement.get("activated_at") is None, (
        f"a newly drafted agreement has no activated_at, got {agreement.get('activated_at')!r}"
    )
    assert agreement["version"] == 1, (
        f"the agreement row starts at version 1, got {agreement['version']}"
    )

    publisher_after = read_publisher(publisher["id"])
    assert publisher_after["active_agreement_count"] == 0, (
        "drafting must not make the agreement active, so active_agreement_count stays 0, got "
        f"{publisher_after['active_agreement_count']}"
    )
    assert publisher_after["version"] == 2, (
        f"drafting increments the publisher's version to 2, got {publisher_after['version']}"
    )


def test_activation_without_coverage_lines_rejected(api, agreement_admin_headers):
    """Activating an agreement that has no coverage line is refused with 409.

    PRD §2.11: "Activation requires the agreement's `status` to be `DRAFT` and requires at least one coverage line to exist for it — otherwise `ERR_AGREEMENT_NOT_ACTIVATABLE` (409)."
    PRD §3.2: "It requires the agreement still to be in `DRAFT` and to have at least one coverage line; failing either condition yields `ERR_AGREEMENT_NOT_ACTIVATABLE`."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    PRD §3.2: "Activation stamps `activated_at` from the logical clock, recomputes the publisher's `active_agreement_count` — which rises by one, since the agreement has just become active — and increments the publisher's `version` by one."
    Design: Corner/state_machines/corner_activation_without_coverage_lines_rejected
    """
    publisher = register_publisher(
        publisher_code="MERID", name="Meridian Academic Press", country_code="NL"
    )
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-2027",
        effective_from="2026-07-01",
        effective_until="2027-07-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )

    validate_error(
        api.activate_transformative_agreement(agreement["id"], agreement_admin_headers),
        ApiErrorId.ERR_AGREEMENT_NOT_ACTIVATABLE.value,
    )

    agreement_after = read_agreement(agreement["id"])
    assert agreement_after["status"] == "DRAFT", (
        f"the refused activation must leave the agreement DRAFT, got {agreement_after['status']!r}"
    )
    assert agreement_after.get("activated_at") is None, (
        f"the refused activation must not stamp activated_at, got {agreement_after.get('activated_at')!r}"
    )

    publisher_after = read_publisher(publisher["id"])
    assert publisher_after["active_agreement_count"] == 0, (
        "the refused activation must not raise active_agreement_count, got "
        f"{publisher_after['active_agreement_count']}"
    )
    assert publisher_after["version"] == 2, (
        "the publisher's version must still be the 2 that drafting produced, got "
        f"{publisher_after['version']}"
    )


def test_activation_bumps_publisher_counters_and_stamps_activated_at(
    api, agreement_admin_headers
):
    """Activation stamps activated_at and raises the publisher's count and version.

    PRD §3.2: "Activation by an `AgreementAdmin` moves the agreement from `DRAFT` to `ACTIVE`."
    PRD §3.2: "Activation stamps `activated_at` from the logical clock, recomputes the publisher's `active_agreement_count` — which rises by one, since the agreement has just become active — and increments the publisher's `version` by one."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    PRD §1: "Every date comparison, every `created_at` and `updated_at` value, and every event stamp such as `activated_at`, `submitted_at`, `ingested_at` or `last_screened_at` is taken from that clock, which an operator may advance explicitly."
    Design: Corner/state_machines/corner_activation_bumps_publisher_counters_and_stamps_activated_at
    """
    set_clock("2026-08-03T00:00:00Z")
    publisher, journal = _register_meridian_with_hybrid_journal()
    agreement, _coverage = _draft_meridian_agreement_with_coverage(
        publisher["id"], journal["id"]
    )

    publisher_before = read_publisher(publisher["id"])
    assert publisher_before["version"] == 2, (
        f"drafting leaves the publisher at version 2, got {publisher_before['version']}"
    )
    assert publisher_before["active_agreement_count"] == 0, (
        "no agreement is active yet, got "
        f"{publisher_before['active_agreement_count']}"
    )

    activated = validate_success(
        api.activate_transformative_agreement(agreement["id"], agreement_admin_headers)
    )

    assert activated["status"] == "ACTIVE", (
        f"activation moves the agreement to ACTIVE, got {activated['status']!r}"
    )
    assert activated["activated_at"].startswith("2026-08-03T00:00:00"), (
        "activated_at is stamped from the logical clock 2026-08-03T00:00:00Z, got "
        f"{activated['activated_at']!r}"
    )
    assert_timestamp_has_three_fractional_digits(activated["activated_at"])

    publisher_after = read_publisher(publisher["id"])
    assert publisher_after["version"] == 3, (
        f"activation increments the publisher's version to 3, got {publisher_after['version']}"
    )
    assert publisher_after["active_agreement_count"] == 1, (
        "activation raises active_agreement_count to 1, got "
        f"{publisher_after['active_agreement_count']}"
    )


def test_repeated_activation_is_rejected_rather_than_ignored(
    api, agreement_admin_headers
):
    """A second activation of an ACTIVE agreement is a 409, not a silent no-op.

    PRD §2.11: "Activation requires the agreement's `status` to be `DRAFT` and requires at least one coverage line to exist for it — otherwise `ERR_AGREEMENT_NOT_ACTIVATABLE` (409)."
    PRD §3.2: "It requires the agreement still to be in `DRAFT` and to have at least one coverage line; failing either condition yields `ERR_AGREEMENT_NOT_ACTIVATABLE`."
    PRD §3.2: "Activation stamps `activated_at` from the logical clock, recomputes the publisher's `active_agreement_count` — which rises by one, since the agreement has just become active — and increments the publisher's `version` by one."
    PRD §2.4: "`version` — an integer that starts at 1 on creation and increases by exactly 1 on every mutation of the row."
    Design: Corner/state_machines/corner_repeated_activation_returns_4XX_rather_than_being_ignored
    """
    set_clock("2026-08-03T00:00:00Z")
    publisher, journal = _register_meridian_with_hybrid_journal()
    agreement, _coverage = _draft_meridian_agreement_with_coverage(
        publisher["id"], journal["id"]
    )
    first = activate_agreement(agreement["id"])
    assert first["status"] == "ACTIVE", (
        f"the first activation must succeed and yield ACTIVE, got {first['status']!r}"
    )

    validate_error(
        api.activate_transformative_agreement(agreement["id"], agreement_admin_headers),
        ApiErrorId.ERR_AGREEMENT_NOT_ACTIVATABLE.value,
    )

    publisher_after = read_publisher(publisher["id"])
    assert publisher_after["active_agreement_count"] == 1, (
        "the refused second activation must not count the agreement twice, got "
        f"{publisher_after['active_agreement_count']}"
    )
    assert publisher_after["version"] == 3, (
        "the refused second activation is not a mutation, so the publisher stays at version 3, got "
        f"{publisher_after['version']}"
    )


def test_expired_agreement_cannot_be_activated_afterwards(
    api, agreement_admin_headers, librarian_headers
):
    """The sweep expires a DRAFT agreement and EXPIRED admits no later activation.

    PRD §3.9: "Phase one expires agreements: every transformative agreement in `DRAFT`, `ACTIVE` or `EXHAUSTED` whose `effective_until` is on or before the clock date moves to `EXPIRED`, with the publisher's `active_agreement_count` recomputed and the publisher's `version` incremented for those that were `ACTIVE`."
    PRD §3.9: "Its response carries `swept_at_utc` as the logical-clock instant of the run, `agreements_expired_count`, `grants_closed_count`, `articles_marked_non_compliant_count` and `articles_promoted_compliant_count`, each being the number of rows the corresponding phase actually changed."
    PRD §2.11: "Activation requires the agreement's `status` to be `DRAFT` and requires at least one coverage line to exist for it — otherwise `ERR_AGREEMENT_NOT_ACTIVATABLE` (409)."
    PRD §3.2: "A newly drafted agreement has `status` `DRAFT`, `articles_used` of zero and no `activated_at`; drafting it also increments the publisher's `version` by one."
    Design: Corner/state_machines/corner_expired_agreement_cannot_be_activated_afterwards
    """
    set_clock("2026-08-03T00:00:00Z")
    publisher, journal = _register_meridian_with_hybrid_journal()
    agreement = draft_agreement(
        publisher["id"],
        agreement_code="TA-MERID-H1",
        effective_from="2026-07-01",
        effective_until="2026-09-01",
        article_quota=5,
        discount_pct=0.20,
        covered_oa_models=["HYBRID"],
    )
    add_coverage(
        agreement["id"],
        journal["id"],
        coverage_type="FULL_APC",
        covered_from="2026-07-01",
        covered_until="2026-08-31",
    )
    set_clock("2026-12-01T00:00:00Z")

    sweep = validate_success(api.create_compliance_sweep(librarian_headers))
    assert sweep["agreements_expired_count"] == 1, (
        f"the sweep should expire exactly one agreement, got {sweep['agreements_expired_count']}"
    )
    expired = read_agreement(agreement["id"])
    assert expired["status"] == "EXPIRED", (
        f"phase one moves the agreement to EXPIRED, got {expired['status']!r}"
    )

    validate_error(
        api.activate_transformative_agreement(agreement["id"], agreement_admin_headers),
        ApiErrorId.ERR_AGREEMENT_NOT_ACTIVATABLE.value,
    )

    agreement_after = read_agreement(agreement["id"])
    assert agreement_after.get("activated_at") is None, (
        "an expired agreement was never activated, so activated_at stays absent, got "
        f"{agreement_after.get('activated_at')!r}"
    )
    publisher_after = read_publisher(publisher["id"])
    assert publisher_after["active_agreement_count"] == 0, (
        "no agreement of this publisher ever became active, got "
        f"{publisher_after['active_agreement_count']}"
    )


# --------------------------------------------------------------------------- #
# repository deposit lifecycle
# --------------------------------------------------------------------------- #
def test_deposit_draft_to_submitted_stamps_submitted_at(api, librarian_headers):
    """Submission moves the deposit DRAFT to SUBMITTED and stamps the clock.

    PRD §3.8: "The author submits the draft for curation, which requires the deposit to be in `DRAFT` and which moves it from `DRAFT` to `SUBMITTED` while stamping `submitted_at` from the logical clock."
    PRD §3.8: "If the article names no grant, or if the grant's funder has a `mandate_type` of `NONE`, the article is `EXEMPT` outright with no `deposit_deadline_on` and no `embargo_until`; an exempt article never enters the sweep and counts as satisfying its grant for roll-up purposes."
    PRD §3.8: "A created deposit takes a `version_ordinal` of the article's `latest_deposit_ordinal` plus one, which makes ordinals monotonic and strictly increasing within an article, and it starts in `status` `DRAFT` with no `persistent_identifier`, no `submitted_at`, no `ingested_at`, no `curation_note`, no `embargo_until` and a `returned_count` of zero."
    PRD §1: "Every date comparison, every `created_at` and `updated_at` value, and every event stamp such as `activated_at`, `submitted_at`, `ingested_at` or `last_screened_at` is taken from that clock, which an operator may advance explicitly."
    Design: Corner/state_machines/corner_deposit_draft_to_submitted_stamps_submitted_at
    """
    set_clock("2026-08-12T00:00:00Z")
    _publisher, journal = _register_halden_with_fully_oa_journal()
    author = _register_tomas_berg()
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="Submission stamps the clock",
        accepted_on="2026-08-05",
    )
    assert article["compliance_status"] == "EXEMPT", (
        f"a grant-free article is EXEMPT at creation, got {article['compliance_status']!r}"
    )
    assert article.get("deposit_deadline_on") is None, (
        f"an EXEMPT article has no deposit_deadline_on, got {article.get('deposit_deadline_on')!r}"
    )
    deposit = create_deposit(
        article["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="b1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f91",
        license="CC_BY",
    )
    assert deposit["status"] == "DRAFT", (
        f"a created deposit starts DRAFT, got {deposit['status']!r}"
    )

    submitted = validate_success(
        api.submit_repository_deposit(
            deposit["id"], make_corresponding_author_headers(author["id"])
        )
    )

    assert submitted["status"] == "SUBMITTED", (
        f"submission moves the deposit to SUBMITTED, got {submitted['status']!r}"
    )
    assert submitted["submitted_at"].startswith("2026-08-12T00:00:00"), (
        "submitted_at is stamped from the logical clock 2026-08-12T00:00:00Z, got "
        f"{submitted['submitted_at']!r}"
    )
    assert_timestamp_has_three_fractional_digits(submitted["submitted_at"])
    assert submitted.get("persistent_identifier") is None, (
        "submission mints no persistent_identifier, got "
        f"{submitted.get('persistent_identifier')!r}"
    )
    assert submitted["returned_count"] == 0, (
        f"submission leaves returned_count at zero, got {submitted['returned_count']}"
    )
    assert read_deposit(deposit["id"]).get("ingested_at") is None, (
        "a submitted deposit has not been ingested, so ingested_at stays absent"
    )


def test_submission_of_ingested_deposit_is_rejected(api, librarian_headers):
    """There is no way back from INGESTED: re-submitting is a 409 and changes nothing.

    PRD §2.11: "Submission requires the deposit's `status` to be `DRAFT`; a curation decision requires it to be `SUBMITTED`."
    PRD §2.11: "Otherwise `ERR_DEPOSIT_INVALID_STATE` (409)."
    PRD §3.8: "On success the deposit moves from `SUBMITTED` to `INGESTED`, `ingested_at` is stamped from the logical clock, and a `persistent_identifier` is minted as the literal prefix `hdl:2027/ir.` followed by the institutional ingest counter rendered as six digits with leading zeros — the counter begins at 1, so the first ingest in the system produces `hdl:2027/ir.000001`."
    PRD §3.8: "The author submits the draft for curation, which requires the deposit to be in `DRAFT` and which moves it from `DRAFT` to `SUBMITTED` while stamping `submitted_at` from the logical clock."
    Design: Corner/state_machines/corner_submission_of_ingested_deposit_returns_4XX
    """
    set_clock("2026-08-12T00:00:00Z")
    _publisher, journal = _register_halden_with_fully_oa_journal()
    author = _register_tomas_berg()
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="No edge back from INGESTED",
        accepted_on="2026-08-05",
    )
    deposit = create_deposit(
        article["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="c1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f92",
        license="CC_BY",
    )
    submit_deposit(deposit["id"], author["id"])
    ingested = curate_deposit(
        deposit["id"], "INGEST", "Accepted manuscript verified."
    )
    assert ingested["status"] == "INGESTED", (
        f"the curation decision must ingest the deposit, got {ingested['status']!r}"
    )
    assert ingested.get("persistent_identifier") is not None, (
        "ingest mints a persistent_identifier"
    )
    assert_persistent_identifier_format(ingested["persistent_identifier"])

    validate_error(
        api.submit_repository_deposit(
            deposit["id"], make_corresponding_author_headers(author["id"])
        ),
        ApiErrorId.ERR_DEPOSIT_INVALID_STATE.value,
    )

    after = read_deposit(deposit["id"])
    assert after["status"] == "INGESTED", (
        f"the refused re-submission must leave the deposit INGESTED, got {after['status']!r}"
    )
    assert after["persistent_identifier"] == ingested["persistent_identifier"], (
        "the minted persistent_identifier must be untouched, got "
        f"{after['persistent_identifier']!r}"
    )
    assert after["ingested_at"].startswith("2026-08-12T00:00:00"), (
        "ingested_at was stamped from the clock at 2026-08-12T00:00:00Z and must be untouched, got "
        f"{after['ingested_at']!r}"
    )


def test_deposit_return_cycle_increments_returned_count(
    api, curator_headers, librarian_headers
):
    """DRAFT to SUBMITTED to DRAFT is a real cycle and each return is counted.

    PRD §3.8: "Returning the deposit moves it from `SUBMITTED` back to `DRAFT`, increases `returned_count` by one and records the `curation_note`."
    PRD §3.8: "The `DRAFT` → `SUBMITTED` → `DRAFT` cycle may repeat without limit, and `returned_count` records how often curation sent the file back."
    PRD §3.8: "A return has **no compliance side effects at all**: the article's `compliance_status`, `embargo_until` and `latest_deposit_ordinal` are untouched, no grant counter moves, and no persistent identifier is minted."
    PRD §3.8: "The author submits the draft for curation, which requires the deposit to be in `DRAFT` and which moves it from `DRAFT` to `SUBMITTED` while stamping `submitted_at` from the logical clock."
    PRD §3.8: "`Grant.output_count` is the number of articles referencing the grant and `Grant.compliant_output_count` is how many of those are `COMPLIANT` or `EXEMPT`."
    PRD §3.8: "In every other case it is `IN_PROGRESS`."
    Design: Corner/state_machines/corner_deposit_return_cycle_increments_returned_count
    """
    set_clock("2026-08-12T00:00:00Z")
    _publisher, journal = _register_halden_with_fully_oa_journal()
    author = _register_tomas_berg()
    _funder, grant = _register_nrc_gold_oa_grant(author["id"])
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="Returned twice by the curator",
        accepted_on="2026-08-05",
        grant_id=grant["id"],
    )
    deposit = create_deposit(
        article["id"],
        author["id"],
        version_label="ACCEPTED_MANUSCRIPT",
        file_checksum="d1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f93",
        license="CC_BY",
    )
    assert deposit["version_ordinal"] == 1, (
        f"the first deposit takes version_ordinal 1, got {deposit['version_ordinal']}"
    )
    submit_deposit(deposit["id"], author["id"])
    first_return = curate_deposit(
        deposit["id"], "RETURN", "Missing funder acknowledgement."
    )
    assert first_return["status"] == "DRAFT", (
        f"a return sends the deposit back to DRAFT, got {first_return['status']!r}"
    )
    assert first_return["returned_count"] == 1, (
        f"the first return raises returned_count to 1, got {first_return['returned_count']}"
    )
    second_submission = submit_deposit(deposit["id"], author["id"])
    assert second_submission["status"] == "SUBMITTED", (
        f"the returned draft may be submitted again, got {second_submission['status']!r}"
    )

    returned = validate_success(
        api.decide_repository_deposit_curation(
            deposit["id"],
            create_curation_decision_payload("RETURN", "Acknowledgement still missing."),
            curator_headers,
        )
    )

    assert returned["status"] == "DRAFT", (
        f"the second return sends the deposit back to DRAFT, got {returned['status']!r}"
    )
    assert returned["returned_count"] == 2, (
        f"the second return raises returned_count to 2, got {returned['returned_count']}"
    )
    assert returned.get("persistent_identifier") is None, (
        f"a return mints no persistent identifier, got {returned.get('persistent_identifier')!r}"
    )
    assert returned["version_ordinal"] == 1, (
        f"the cycle stays on one row, so version_ordinal is still 1, got {returned['version_ordinal']}"
    )

    article_after = read_article(article["id"])
    assert article_after["compliance_status"] == "PENDING_DEPOSIT", (
        "a return has no compliance side effects, got "
        f"{article_after['compliance_status']!r}"
    )
    assert article_after["latest_deposit_ordinal"] == 1, (
        "a return leaves latest_deposit_ordinal untouched at 1, got "
        f"{article_after['latest_deposit_ordinal']}"
    )
    grant_after = validate_success(api.get_grant(grant["id"], librarian_headers))
    assert grant_after["compliant_output_count"] == 0, (
        "nothing has been ingested, so the grant counts no compliant output, got "
        f"{grant_after['compliant_output_count']}"
    )
    assert grant_after["mandate_status"] == "IN_PROGRESS", (
        f"the grant's mandate dimension stays IN_PROGRESS, got {grant_after['mandate_status']!r}"
    )


# --------------------------------------------------------------------------- #
# invoice, grant and ledger lifecycles
# --------------------------------------------------------------------------- #
def test_invoice_validation_branches_to_disputed_on_discount_shortfall(
    api, librarian_headers, fund_manager_headers
):
    """An under-applied agreement discount disputes the invoice and blocks payment.

    PRD §3.7: "It first recomputes the whole pricing — refreshing `entitled_discount_pct`, `net_cents`, `vat_cents`, `expected_amount_cents` and `variance_cents`, since a determination may have changed since receipt — and then branches on the recomputed `validation_outcome`."
    PRD §3.7: "A `DISCOUNT_SHORTFALL` or an `AMOUNT_VARIANCE` moves the invoice from `RECEIVED` to `DISPUTED` and sets `dispute_reason` to that same outcome value."
    PRD §3.7: "`DISPUTED` is terminal and has no payment path whatsoever: to be paid, the publisher must issue a fresh invoice under a new `invoice_number`."
    PRD §3.7: "If the `claimed_discount_pct` is less than the `entitled_discount_pct` by more than one ten-thousandth — that is, if the claimed discount falls below the entitled discount minus 0.0001 — the outcome is `DISCOUNT_SHORTFALL`, because the publisher under-applied the negotiated discount; the small epsilon exists so that floating-point noise in a claimed fraction is not read as a shortfall."
    PRD §3.7: "The `entitled_discount_pct` — the discount the institution is actually entitled to — depends on the route: when the determination's route is `TA_FULL` or `TA_CAPPED`, it is that determination's `discount_pct_applied`, because the agreement fixes the discount; when the route is `FUND_APC` or `AUTHOR_PAYS`, there is no agreement and the entitlement comes instead from the publisher's volume tier described below."
    PRD §3.7: "First, `net_cents` is the base multiplied by one minus the `entitled_discount_pct`, rounded half up to whole cents."
    PRD §3.7: "Second, `vat_cents` is that already-rounded `net_cents` multiplied by the invoice's `vat_pct`, rounded half up to whole cents — the tax is computed on the rounded net, not on the unrounded net."
    PRD §3.7: "Third, `expected_amount_cents` is `net_cents` plus `vat_cents` with no further rounding applied to the sum."
    PRD §3.7: "Finally, `variance_cents` is the invoice's `invoice_amount_cents` less the `expected_amount_cents`, and may be negative when the publisher under-billed."
    PRD §3.7: "A recorded invoice starts in `status` `RECEIVED` with no `dispute_reason`, no `payment_approved_by_user_id` and no `payment_reference`, and the expected amount is priced immediately at creation."
    PRD §3.7: "A `FundManager` approves a `VALIDATED` invoice for payment, which requires the invoiced article's `funding_status` to be one of `FUNDED`, `PARTIALLY_FUNDED` or `SELF_FUNDED` — an article still in `DRAFT`, `ELIGIBILITY_CHECKED`, `FUNDING_REQUESTED` or `DECLINED` yields `ERR_ARTICLE_NOT_FUNDED` — and which moves the invoice from `VALIDATED` to `APPROVED_FOR_PAYMENT` while recording the acting `X-User-ID` as `payment_approved_by_user_id`."
    PRD §2.11: "Validation requires the invoice's `status` to be `RECEIVED`; payment approval requires `VALIDATED`; payment requires `APPROVED_FOR_PAYMENT`."
    PRD §2.11: "Otherwise `ERR_INVOICE_INVALID_STATE` (409)."
    PRD §3.4: "The `discount_pct_applied` is that agreement's `discount_pct`, and the discounted price is `list_base_cents` multiplied by one minus the discount, rounded half up to whole cents — this is the only rounding step in the whole determination."
    PRD §3.4: "If the matched coverage line's `coverage_type` is `FULL_APC`, the `route` is `TA_FULL`, `covered_amount_cents` is the whole discounted price, `author_share_cents` is 0, `eligible_request_cents` is 0 because there is nothing left to subsidise, and `determination_reason` is `TA_FULL_COVERAGE`."
    Design: Corner/state_machines/corner_invoice_validation_branch_to_disputed_on_discount_shortfall
    """
    set_clock("2026-08-12T00:00:00Z")
    publisher, journal = _register_meridian_with_hybrid_journal()
    author = register_author(
        full_name="Ilse Vermeer",
        email="ilse.vermeer@uni.example",
        orcid="0000-0002-1111-2222",
        department_code="CEL",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    agreement, _coverage = _draft_meridian_agreement_with_coverage(
        publisher["id"], journal["id"]
    )
    activate_agreement(agreement["id"])
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="Publisher under-applied the negotiated discount",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    assert determination["route"] == "TA_FULL", (
        f"the FULL_APC coverage line routes the article TA_FULL, got {determination['route']!r}"
    )
    assert determination["discount_pct_applied"] == 0.20, (
        "discount_pct_applied is the agreement's 0.20, got "
        f"{determination['discount_pct_applied']}"
    )
    invoice = receive_invoice(
        publisher["id"],
        article["id"],
        "MERID-9001",
        342000,
        0.10,
        0.06,
        "2026-08-12",
    )
    assert invoice["validation_outcome"] == "DISCOUNT_SHORTFALL", (
        "the invoice is priced at creation and already reads DISCOUNT_SHORTFALL, got "
        f"{invoice['validation_outcome']!r}"
    )

    validated = validate_success(
        api.validate_publisher_invoice(invoice["id"], librarian_headers)
    )

    assert validated["entitled_discount_pct"] == 0.20, (
        f"the entitled discount is the agreement's 0.20, got {validated['entitled_discount_pct']}"
    )
    assert validated["net_cents"] == 304000, (
        f"net_cents should be 304000, got {validated['net_cents']}"
    )
    assert validated["vat_cents"] == 18240, (
        f"vat_cents should be 18240 on the rounded net, got {validated['vat_cents']}"
    )
    assert validated["expected_amount_cents"] == 322240, (
        f"expected_amount_cents should be 322240, got {validated['expected_amount_cents']}"
    )
    assert validated["variance_cents"] == 19760, (
        f"variance_cents should be 19760, got {validated['variance_cents']}"
    )
    assert validated["validation_outcome"] == "DISCOUNT_SHORTFALL", (
        f"the discount test wins, got {validated['validation_outcome']!r}"
    )
    assert validated["status"] == "DISPUTED", (
        f"a DISCOUNT_SHORTFALL moves the invoice to DISPUTED, got {validated['status']!r}"
    )
    assert validated["dispute_reason"] == "DISCOUNT_SHORTFALL", (
        f"dispute_reason takes the outcome value, got {validated['dispute_reason']!r}"
    )

    validate_error(
        api.approve_publisher_invoice_payment(invoice["id"], fund_manager_headers),
        ApiErrorId.ERR_INVOICE_INVALID_STATE.value,
    )
    after = validate_success(api.get_publisher_invoice(invoice["id"], librarian_headers))
    assert after.get("payment_approved_by_user_id") is None, (
        "the refused approval must record no payment_approved_by_user_id, got "
        f"{after.get('payment_approved_by_user_id')!r}"
    )


def test_grant_mandate_breaches_while_grant_status_stays_active(
    api, librarian_headers
):
    """A missed deposit deadline breaches the mandate but leaves the award ACTIVE.

    PRD §3.9: "Phase three catches missed deposit deadlines: every article whose `compliance_status` is still `PENDING_DEPOSIT` and whose `deposit_deadline_on` is strictly before the clock date moves to `NON_COMPLIANT`, and the owning grant's `mandate_status` moves to `BREACHED`."
    PRD §3.9: "Phase two closes grants: every `ACTIVE` grant whose `award_until` is strictly before the clock date moves to `CLOSED`."
    PRD §3.9: "Its response carries `swept_at_utc` as the logical-clock instant of the run, `agreements_expired_count`, `grants_closed_count`, `articles_marked_non_compliant_count` and `articles_promoted_compliant_count`, each being the number of rows the corresponding phase actually changed."
    PRD §3.8: "The `deposit_deadline_on` is the article's `accepted_on` advanced by the funder's `deposit_deadline_days` in whole calendar days."
    PRD §3.8: "If **any** article of the grant is `NON_COMPLIANT`, the `mandate_status` is `BREACHED`."
    PRD §3.8: "`Grant.output_count` is the number of articles referencing the grant and `Grant.compliant_output_count` is how many of those are `COMPLIANT` or `EXEMPT`."
    PRD §3.4: "A newly recorded article always starts with `funding_status` `DRAFT`, while its `compliance_status` is set at creation to either `PENDING_DEPOSIT` or `EXEMPT` by the mandate rule described in §3.8, which also sets `deposit_deadline_on` and `embargo_until`."
    Design: Corner/state_machines/corner_grant_mandate_breaches_while_grant_status_stays_active
    """
    set_clock("2026-08-10T00:00:00Z")
    _publisher, journal = _register_halden_with_fully_oa_journal()
    author = _register_tomas_berg()
    _funder, grant = _register_nrc_gold_oa_grant(author["id"])
    assert grant["status"] == "ACTIVE", (
        f"a recorded grant starts ACTIVE, got {grant['status']!r}"
    )
    assert grant["mandate_status"] == "IN_PROGRESS", (
        f"a recorded grant starts IN_PROGRESS, got {grant['mandate_status']!r}"
    )
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="Deposit deadline missed",
        accepted_on="2026-08-05",
        grant_id=grant["id"],
    )
    assert article["deposit_deadline_on"] == "2026-11-03", (
        "accepted_on 2026-08-05 plus 90 days is 2026-11-03, got "
        f"{article['deposit_deadline_on']!r}"
    )
    assert article["compliance_status"] == "PENDING_DEPOSIT", (
        f"a mandated article starts PENDING_DEPOSIT, got {article['compliance_status']!r}"
    )
    set_clock("2026-11-04T00:00:00Z")

    sweep = validate_success(api.create_compliance_sweep(librarian_headers))

    assert sweep["articles_marked_non_compliant_count"] == 1, (
        "phase three should mark exactly one article, got "
        f"{sweep['articles_marked_non_compliant_count']}"
    )
    assert sweep["grants_closed_count"] == 0, (
        f"the award runs to 2027-12-31, so no grant closes, got {sweep['grants_closed_count']}"
    )
    assert sweep["articles_promoted_compliant_count"] == 0, (
        f"no embargo elapses in this sweep, got {sweep['articles_promoted_compliant_count']}"
    )

    article_after = read_article(article["id"])
    assert article_after["compliance_status"] == "NON_COMPLIANT", (
        f"the missed deadline marks the article NON_COMPLIANT, got {article_after['compliance_status']!r}"
    )
    assert article_after["funding_status"] == "DRAFT", (
        "the compliance sweep never touches the funding dimension, got "
        f"{article_after['funding_status']!r}"
    )
    grant_after = validate_success(api.get_grant(grant["id"], librarian_headers))
    assert grant_after["status"] == "ACTIVE", (
        f"the award window has not elapsed, so the grant stays ACTIVE, got {grant_after['status']!r}"
    )
    assert grant_after["mandate_status"] == "BREACHED", (
        f"one NON_COMPLIANT article breaches the mandate, got {grant_after['mandate_status']!r}"
    )
    assert grant_after["output_count"] == 1, (
        f"one article references the grant, got {grant_after['output_count']}"
    )
    assert grant_after["compliant_output_count"] == 0, (
        f"that article is not compliant, got {grant_after['compliant_output_count']}"
    )


def test_invoice_payment_syncs_allocation_and_fund_ledgers(
    api, librarian_headers, fund_manager_headers, fund_payer_headers
):
    """Paying the invoice runs all three ledger hops in one request.

    PRD §3.7: "A different `FundManager` then pays it, supplying the bank `payment_reference`, which moves the invoice from `APPROVED_FOR_PAYMENT` to `PAID`."
    PRD §3.7: "Payment is the largest cascade in the system and it runs three further hops beyond the invoice itself."
    PRD §3.7: "First, the article's fund request whose `status` is `APPROVED` moves to `PAID`."
    PRD §3.7: "Second, every allocation line of that request whose `status` is `ENCUMBERED` becomes `DISBURSED`."
    PRD §3.7: "Third, for each of those lines, the owning fund moves the line's `amount_cents` out of `committed_cents` and into `spent_cents`, leaving `available_cents` unchanged in total but converting a promise into a payment."
    PRD §3.7: "The author's `apc_committed_cents` and `apc_disbursed_cents` are then both recomputed, the first falling and the second rising."
    PRD §3.7: "A `MATCH` or a `WITHIN_TOLERANCE` moves the invoice from `RECEIVED` to `VALIDATED` and records no dispute."
    PRD §3.7: "Otherwise, if `variance_cents` is exactly zero the outcome is `MATCH`."
    PRD §3.7: "First, `net_cents` is the base multiplied by one minus the `entitled_discount_pct`, rounded half up to whole cents."
    PRD §3.7: "Second, `vat_cents` is that already-rounded `net_cents` multiplied by the invoice's `vat_pct`, rounded half up to whole cents — the tax is computed on the rounded net, not on the unrounded net."
    PRD §3.7: "Tier boundaries are inclusive: prior paid net spend of fifty thousand dollars or more (5000000 cents) earns a twenty percent entitlement, at least twenty thousand dollars (2000000 cents) earns fifteen percent, at least five thousand dollars (500000 cents) earns ten percent, and anything below five thousand dollars earns nothing at all."
    PRD §3.4: "If it qualifies, the `route` is `FUND_APC`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is likewise the whole `list_base_cents`, and `determination_reason` is `NO_COVERAGE_FUND_ELIGIBLE`."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    PRD §3.5: "The request moves from `UNDER_REVIEW` to `APPROVED`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §3.3: "Whenever an allocation is encumbered or disbursed against a fund, the fund is re-examined: if `committed_cents` plus `spent_cents` reaches or exceeds ninety-eight percent of `total_budget_cents` — computed as `total_budget_cents` multiplied by 0.98 and rounded half up to whole cents — the fund moves from `OPEN` to `FROZEN` with `freeze_reason` set to the literal value `AUTO_THRESHOLD`."
    Design: Corner/state_machines/corner_invoice_payment_syncs_allocation_and_fund_ledgers
    """
    set_clock("2026-08-10T00:00:00Z")
    publisher, journal = _register_halden_with_fully_oa_journal()
    author = _register_tomas_berg()
    _funder, grant = _register_nrc_gold_oa_grant(author["id"])
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=400000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="Ledger sync at payment time",
        accepted_on="2026-08-05",
        grant_id=grant["id"],
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    assert determination["route"] == "FUND_APC", (
        f"an uncovered FULLY_OA journal under a GOLD_OA grant routes FUND_APC, got {determination['route']!r}"
    )
    assert determination["eligible_request_cents"] == 300000, (
        "the whole 300000-cent list base is subsidisable, got "
        f"{determination['eligible_request_cents']}"
    )
    request = open_fund_request(article["id"], author["id"], 300000)
    start_review(request["id"])
    approved = decide_request(
        request["id"],
        "APPROVE",
        "Within the annual cap and the fund's per-article cap.",
        headers=fund_manager_headers,
    )
    assert approved["status"] == "APPROVED", (
        f"the decision moves the request to APPROVED, got {approved['status']!r}"
    )
    assert approved["approved_cents"] == 300000, (
        f"the waterfall approves the whole 300000, got {approved['approved_cents']}"
    )

    fund_before = validate_success(api.get_apc_fund(fund["id"], fund_manager_headers))
    assert fund_before["committed_cents"] == 300000, (
        f"approval encumbers 300000, got {fund_before['committed_cents']}"
    )
    assert fund_before["spent_cents"] == 0, (
        f"nothing is spent before payment, got {fund_before['spent_cents']}"
    )
    assert fund_before["available_cents"] == 200000, (
        f"available_cents is 500000 less 300000, got {fund_before['available_cents']}"
    )
    assert fund_before["status"] == "OPEN", (
        f"300000 is below the 490000 auto-freeze threshold, got {fund_before['status']!r}"
    )

    invoice = receive_invoice(
        publisher["id"],
        article["id"],
        "HALDEN-4400",
        318000,
        0.0,
        0.06,
        "2026-08-10",
    )
    assert invoice["net_cents"] == 300000, (
        f"with no tier entitlement net_cents is the full 300000, got {invoice['net_cents']}"
    )
    assert invoice["vat_cents"] == 18000, (
        f"vat_cents is 6 percent of the rounded net, got {invoice['vat_cents']}"
    )
    validated = validate_invoice(invoice["id"])
    assert validated["validation_outcome"] == "MATCH", (
        f"a zero variance is a MATCH, got {validated['validation_outcome']!r}"
    )
    assert validated["status"] == "VALIDATED", (
        f"a MATCH moves the invoice to VALIDATED, got {validated['status']!r}"
    )
    validate_success(
        api.approve_publisher_invoice_payment(invoice["id"], fund_manager_headers)
    )

    paid = validate_success(
        api.pay_publisher_invoice(
            invoice["id"], create_payment_payload("WIRE-88010"), fund_payer_headers
        )
    )

    assert paid["status"] == "PAID", (
        f"payment moves the invoice to PAID, got {paid['status']!r}"
    )

    fund_after = validate_success(api.get_apc_fund(fund["id"], fund_manager_headers))
    assert fund_after["committed_cents"] == 0, (
        f"the encumbrance leaves committed_cents, got {fund_after['committed_cents']}"
    )
    assert fund_after["spent_cents"] == 300000, (
        f"the same 300000 arrives in spent_cents, got {fund_after['spent_cents']}"
    )
    assert fund_after["available_cents"] == 200000, (
        f"available_cents is unchanged in total at 200000, got {fund_after['available_cents']}"
    )
    assert fund_after["status"] == "OPEN", (
        f"committed plus spent is still below 490000, got {fund_after['status']!r}"
    )

    author_after = validate_success(api.get_author(author["id"], fund_manager_headers))
    assert author_after["apc_committed_cents"] == 0, (
        f"the author's committed figure falls to 0, got {author_after['apc_committed_cents']}"
    )
    assert author_after["apc_disbursed_cents"] == 300000, (
        f"the author's disbursed figure rises to 300000, got {author_after['apc_disbursed_cents']}"
    )

    request_after = validate_success(
        api.get_fund_request(request["id"], fund_manager_headers)
    )
    assert request_after["status"] == "PAID", (
        f"hop one moves the fund request to PAID, got {request_after['status']!r}"
    )

    allocations, meta = validate_paginated(
        api.list_fund_request_allocations(request["id"], fund_manager_headers)
    )
    assert meta["total_count"] == 1 and len(allocations) == 1, (
        f"the request holds exactly one allocation line, got {meta['total_count']}"
    )
    assert allocations[0]["status"] == "DISBURSED", (
        f"hop two disburses the line, got {allocations[0]['status']!r}"
    )
    assert allocations[0]["amount_cents"] == 300000, (
        f"the line still carries 300000, got {allocations[0]['amount_cents']}"
    )


def test_payment_without_approved_request_skips_the_ledger_hops(
    api, librarian_headers, fund_manager_headers, fund_payer_headers
):
    """A self-funded article's invoice reaches PAID without moving any ledger.

    PRD §3.7: "When the article has no approved fund request at all — the self-funded case, where the author or their grant paid the publisher directly — the invoice still reaches `PAID`, but none of the three hops fire and no ledger moves."
    PRD §3.7: "A different `FundManager` then pays it, supplying the bank `payment_reference`, which moves the invoice from `APPROVED_FOR_PAYMENT` to `PAID`."
    PRD §3.7: "Otherwise, if `variance_cents` is exactly zero the outcome is `MATCH`."
    PRD §3.7: "A `MATCH` or a `WITHIN_TOLERANCE` moves the invoice from `RECEIVED` to `VALIDATED` and records no dispute."
    PRD §3.4: "If it does not qualify, the `route` is `AUTHOR_PAYS`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is 0, and `determination_reason` is `NO_COVERAGE_AUTHOR_PAYS`."
    PRD §3.4: "Read in state-machine terms, a first check on a fresh article moves it from `DRAFT` to `FUNDED` when the route is `TA_FULL`, from `DRAFT` to `ELIGIBILITY_CHECKED` when the route is `FUND_APC` or is `TA_CAPPED` with a positive `eligible_request_cents`, and from `DRAFT` to `SELF_FUNDED` when the route is `AUTHOR_PAYS` or is `TA_CAPPED` with `eligible_request_cents` of zero."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    Design: Corner/state_machines/corner_payment_without_approved_request_skips_the_ledger_hops
    """
    set_clock("2026-08-10T00:00:00Z")
    publisher = register_publisher(
        publisher_code="SELKIE", name="Selkie Press", country_code="IE"
    )
    journal = register_journal(
        publisher["id"],
        issn="2050-084X",
        title="Selkie Journal of Marine Ecology",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Maeve Lynch",
        email="maeve.lynch@uni.example",
        orcid="0000-0002-7654-3210",
        department_code="MAR",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=500000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=400000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        headers=librarian_headers,
        manuscript_title="Author pays out of pocket",
        accepted_on="2026-08-05",
    )
    determination = run_eligibility_check(article["id"], basis="PROVISIONAL")
    assert determination["route"] == "AUTHOR_PAYS", (
        f"no cover and no grant routes the article AUTHOR_PAYS, got {determination['route']!r}"
    )
    assert determination["eligible_request_cents"] == 0, (
        f"an AUTHOR_PAYS route leaves nothing subsidisable, got {determination['eligible_request_cents']}"
    )
    article_after_check = read_article(article["id"])
    assert article_after_check["funding_status"] == "SELF_FUNDED", (
        "an AUTHOR_PAYS route moves the funding dimension to SELF_FUNDED, got "
        f"{article_after_check['funding_status']!r}"
    )
    invoice = receive_invoice(
        publisher["id"],
        article["id"],
        "SELKIE-2001",
        318000,
        0.0,
        0.06,
        "2026-08-10",
    )
    validated = validate_invoice(invoice["id"])
    assert validated["validation_outcome"] == "MATCH", (
        f"a zero variance is a MATCH, got {validated['validation_outcome']!r}"
    )
    validate_success(
        api.approve_publisher_invoice_payment(invoice["id"], fund_manager_headers)
    )

    paid = validate_success(
        api.pay_publisher_invoice(
            invoice["id"], create_payment_payload("WIRE-88011"), fund_payer_headers
        )
    )

    assert paid["status"] == "PAID", (
        f"the self-funded invoice still reaches PAID, got {paid['status']!r}"
    )
    assert paid["payment_reference"] == "WIRE-88011", (
        f"the supplied payment_reference is recorded, got {paid['payment_reference']!r}"
    )

    fund_after = validate_success(api.get_apc_fund(fund["id"], fund_manager_headers))
    assert fund_after["committed_cents"] == 0, (
        f"no hop fired, so committed_cents stays 0, got {fund_after['committed_cents']}"
    )
    assert fund_after["spent_cents"] == 0, (
        f"no hop fired, so spent_cents stays 0, got {fund_after['spent_cents']}"
    )
    assert fund_after["available_cents"] == 500000, (
        f"the whole 500000 budget is still available, got {fund_after['available_cents']}"
    )

    allocations, alloc_meta = validate_paginated(
        api.list_fund_allocations(fund["id"], fund_manager_headers)
    )
    assert allocations == [] and alloc_meta["total_count"] == 0, (
        f"no allocation line exists at all, got {alloc_meta['total_count']}"
    )

    requests, request_meta = validate_paginated(
        api.list_article_fund_requests(article["id"], fund_manager_headers)
    )
    assert requests == [] and request_meta["total_count"] == 0, (
        f"the article never opened a fund request, got {request_meta['total_count']}"
    )
