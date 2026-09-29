"""Registry shape, declared defaults and server-derived seed values.

Covers what the governance registries return the moment a row is minted: the
optional inputs the governance office may omit and the standing values that
replace them, the counters a freshly defined domain seeds, the identity and
version fields only the server may write, the percentages computed on an
ingested master record, the immutability of a scorecard run, and the not-found
and schema refusals that keep unusable rows out of the registries.
"""

from test_helpers import (
    AUDITOR_HEADERS,
    CLOCK,
    CLOCK_DEFAULT_START,
    GOVERNANCE_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_master_record,
    assert_consumer_subscription,
    assert_domain,
    assert_instant_equals,
    assert_master_record,
    assert_quality_rule,
    assert_scorecard_run,
    assert_source_registration,
    assert_source_system,
    assert_steward,
    consumer_subscription_payload,
    create_domain,
    create_quality_rule,
    create_source_system,
    is_iso8601_timestamp,
    is_valid_uuid,
    quality_rule_payload,
    read_domain,
    register_source,
    run_scorecard,
    set_clock,
    setup_draft_domain,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_omitted_notice_floor_and_attribute_expectation_take_their_standing_values(
    api,
):
    """A domain defined with only its required inputs still governs by the
    standing notice floor and the standing attribute expectation, and its
    sensitivity flag is derived from the classification rather than supplied.

    PRD §3.1: "`notification_lead_days_floor` sets the minimum notice, in whole
    days between 0 and 30, that the domain will impose on any change that
    impacts a downstream consumer; when the caller omits it the floor is five
    days."

    PRD §3.1: "`expected_attribute_count` declares how many attribute keys a
    complete record in this domain is supposed to carry, from 1 to 50, and when
    omitted it is five; this number is the denominator of every completeness
    measurement in the domain, so a domain expecting five attributes treats a
    record carrying three populated keys as sixty percent complete."

    PRD §2.10: "The boolean `sensitive_handling_required` is derived, never
    supplied: it is true exactly when the domain's `classification_level` is
    `CONFIDENTIAL` or `RESTRICTED`, and false for `PUBLIC` and `INTERNAL`."

    PRD §4: "Operations that create a brand-new resource — a domain, a source
    system, a steward, a source registration, a steward assignment, a quality
    rule, a scorecard run, a master record, a merge proposal, a change request
    or a consumer subscription — respond with HTTP 201 and return the created
    resource in `data`."

    Design: Corner/entities/domain_creation_applies_every_declared_default
    """
    set_clock(CLOCK_DEFAULT_START)

    response = api.create_domain(
        {
            "code": "VENDOR",
            "name": "Vendor Master",
            "classification_level": "INTERNAL",
        },
        GOVERNANCE_ADMIN_HEADERS,
    )
    domain = validate_success(response, expected_status=201)
    assert_domain(domain)

    assert domain["notification_lead_days_floor"] == 5, (
        "a domain defined without a notice floor must impose the standing "
        f"floor of five days, got {domain['notification_lead_days_floor']}"
    )
    assert domain["expected_attribute_count"] == 5, (
        "a domain defined without an attribute expectation must expect five "
        f"attribute keys, got {domain['expected_attribute_count']}"
    )
    assert domain["sensitive_handling_required"] is False, (
        "an INTERNAL domain must not require sensitive handling, got "
        f"{domain['sensitive_handling_required']!r}"
    )


def test_freshly_defined_domain_is_frozen_with_every_counter_seeded_empty(api):
    """A domain that has not yet been given an authoritative source is already
    frozen, is still a draft, and carries no accumulated governance history.

    PRD §3.1: "A newly defined domain lands in `status` `DRAFT` with
    `activated_at` still null, and — because it has not yet been given an
    authoritative source — its derived `governance_posture` is already
    `FROZEN`."

    PRD §3.1: "Its `version` starts at 1."

    PRD §3.1: "Every derived quantity starts empty: `open_finding_weight` at 0,
    `published_master_record_count` at 0, `scheduled_change_count` at 0,
    `scorecard_run_seq` at 0, `reference_data_revision` at 0, and
    `authoritative_source_code`, `quality_score_provisional` and
    `quality_score_certified` all null."

    PRD §2.6: "A domain still in `DRAFT` can already be `FROZEN` (indeed a
    freshly defined domain always is, because it has no authoritative source
    yet), and an `ACTIVE` domain moves freely among all three postures without
    any `status` change."

    Design: Corner/entities/domain_creation_applies_every_declared_default
    """
    set_clock(CLOCK_DEFAULT_START)

    response = api.create_domain(
        {
            "code": "VENDOR",
            "name": "Vendor Master",
            "classification_level": "INTERNAL",
        },
        GOVERNANCE_ADMIN_HEADERS,
    )
    domain = validate_success(response, expected_status=201)
    assert_domain(domain)

    assert domain["status"] == "DRAFT", (
        f"a newly defined domain must land in DRAFT, got {domain['status']}"
    )
    assert domain["activated_at"] is None, (
        f"activated_at must still be null, got {domain['activated_at']!r}"
    )
    assert domain["governance_posture"] == "FROZEN", (
        "a domain with no authoritative source must already be FROZEN, got "
        f"{domain['governance_posture']}"
    )
    assert domain["version"] == 1, (
        f"version must start at 1, got {domain['version']!r}"
    )
    assert domain["open_finding_weight"] == 0, (
        f"open_finding_weight must start at 0, got {domain['open_finding_weight']!r}"
    )
    assert domain["published_master_record_count"] == 0, (
        "published_master_record_count must start at 0, got "
        f"{domain['published_master_record_count']!r}"
    )
    assert domain["scheduled_change_count"] == 0, (
        "scheduled_change_count must start at 0, got "
        f"{domain['scheduled_change_count']!r}"
    )
    assert domain["scorecard_run_seq"] == 0, (
        f"scorecard_run_seq must start at 0, got {domain['scorecard_run_seq']!r}"
    )
    assert domain["reference_data_revision"] == 0, (
        "reference_data_revision must start at 0, got "
        f"{domain['reference_data_revision']!r}"
    )
    assert domain["authoritative_source_code"] is None, (
        "authoritative_source_code must be null before any authoritative "
        f"registration exists, got {domain['authoritative_source_code']!r}"
    )
    assert domain["quality_score_provisional"] is None, (
        "quality_score_provisional must be null before any run, got "
        f"{domain['quality_score_provisional']!r}"
    )
    assert domain["quality_score_certified"] is None, (
        "quality_score_certified must be null before any run, got "
        f"{domain['quality_score_certified']!r}"
    )


def test_registering_a_steward_returns_the_declared_identity_and_no_debt(api):
    """The steward registry echoes back the name, the unique email and the
    certification level it was given, and starts the steward carrying no
    remediation debt.

    PRD §3.1: "A `Steward` row carries a `full_name`, an `email` that must be
    unique across all stewards (`ERR_DUPLICATE_STEWARD_EMAIL` otherwise), and a
    `certification_level` of `JUNIOR`, `SENIOR` or `PRINCIPAL`."

    PRD §3.1: "Its `open_finding_load` begins at 0 and is thereafter maintained
    by the system, never supplied."

    PRD §4: "Operations that create a brand-new resource — a domain, a source
    system, a steward, a source registration, a steward assignment, a quality
    rule, a scorecard run, a master record, a merge proposal, a change request
    or a consumer subscription — respond with HTTP 201 and return the created
    resource in `data`."

    Design: Corner/entities/steward_creation_returns_all_input_fields
    """
    set_clock(CLOCK_DEFAULT_START)

    response = api.create_steward(
        {
            "full_name": "Priya Raman",
            "email": "priya.raman@example.test",
            "certification_level": "SENIOR",
        },
        GOVERNANCE_ADMIN_HEADERS,
    )
    steward = validate_success(response, expected_status=201)
    assert_steward(steward)

    assert steward["full_name"] == "Priya Raman", (
        f"full_name must be returned as declared, got {steward['full_name']!r}"
    )
    assert steward["email"] == "priya.raman@example.test", (
        f"email must be returned as declared, got {steward['email']!r}"
    )
    assert steward["certification_level"] == "SENIOR", (
        "certification_level must be returned as declared, got "
        f"{steward['certification_level']!r}"
    )
    assert steward["open_finding_load"] == 0, (
        f"open_finding_load must begin at 0, got {steward['open_finding_load']!r}"
    )


def test_steward_identity_and_version_fields_are_minted_by_the_server(api):
    """The steward registry mints the identifier, the audit timestamps and the
    starting version itself, and the response envelope carries the server's own
    request identifier and shape.

    PRD §2.4: "Every persisted resource carries a server-minted `id`, which is a
    UUID string with no type prefix of any kind, and a `created_at` timestamp
    recorded as an ISO 8601 UTC instant with three fractional digits."

    PRD §2.4: "Almost every resource additionally carries `updated_at`,
    refreshed to the current instant whenever any of the resource's own fields
    change, and `version`, an integer that starts at 1 on creation and
    increments on mutation."

    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for
    the request that starts with `req_`."

    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/entities/steward_system_fields_are_server_generated
    """
    set_clock(CLOCK_DEFAULT_START)

    response = api.create_steward(
        {
            "full_name": "Priya Raman",
            "email": "priya.raman@example.test",
            "certification_level": "SENIOR",
        },
        GOVERNANCE_ADMIN_HEADERS,
    )
    steward = validate_success(response, expected_status=201)

    assert is_valid_uuid(steward["id"]), (
        f"id must be a bare UUID string, got {steward['id']!r}"
    )
    assert ":" not in steward["id"] and "_" not in steward["id"], (
        f"id must carry no type prefix of any kind, got {steward['id']!r}"
    )
    assert is_iso8601_timestamp(steward["created_at"]), (
        f"created_at must be an ISO 8601 UTC instant, got {steward['created_at']!r}"
    )
    assert is_iso8601_timestamp(steward["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC instant, got {steward['updated_at']!r}"
    )
    assert steward["version"] == 1, (
        f"version must start at 1 on creation, got {steward['version']!r}"
    )

    envelope = response.json()
    assert envelope["response_type"] == "object", (
        "a single steward must be returned as an object response, got "
        f"{envelope['response_type']!r}"
    )
    assert envelope["meta"]["api_request_id"].startswith("req_"), (
        "the server-generated request identifier must start with req_, got "
        f"{envelope['meta']['api_request_id']!r}"
    )


def test_reading_a_certified_source_system_shows_the_certification_stamp(api):
    """A source system reads back as registered with nothing certified until the
    governance office certifies it, after which the read shows the certification
    instant taken from the logical clock and no decertification trace.

    PRD §3.1: "A freshly registered system begins in `status` `REGISTERED` with
    `certified_at`, `decertified_at` and `decertification_reason` all null, and
    source systems may be listed filtered by `status`."

    PRD §3.1: "Certification is the gate that lets a source become authoritative
    and contribute curated records: the transition `REGISTERED → CERTIFIED` is
    available only while the system is still `REGISTERED` (attempting it on an
    already-certified or `DECERTIFIED` system is `ERR_INVALID_STATE_TRANSITION`),
    it stamps `certified_at` from the logical clock, and — because certification
    can be the missing ingredient that a domain's posture was waiting on — it
    also recomputes the `governance_posture` of every domain that already holds
    an `ACTIVE` `AUTHORITATIVE` registration on the newly certified system."

    Design: Corner/entities/source_system_retrieval_returns_stored_state_after_certify
    """
    set_clock(CLOCK)
    system = create_source_system(
        certify=False, code="ERP", name="ERP Core", trust_tier=4
    )

    assert system["status"] == "REGISTERED", (
        f"a freshly registered system must be REGISTERED, got {system['status']}"
    )
    assert system["certified_at"] is None, (
        f"certified_at must start null, got {system['certified_at']!r}"
    )

    validate_success(api.certify_source_system(system["id"], GOVERNANCE_ADMIN_HEADERS))

    stored = validate_success(api.get_source_system(system["id"], AUDITOR_HEADERS))
    assert_source_system(stored)

    assert stored["id"] == system["id"], (
        "the read must return the same source system that was certified"
    )
    assert stored["code"] == "ERP", (
        f"the stored short code must be returned, got {stored['code']!r}"
    )
    assert stored["name"] == "ERP Core", (
        f"the stored name must be returned, got {stored['name']!r}"
    )
    assert stored["trust_tier"] == 4, (
        f"the stored trust tier must be returned, got {stored['trust_tier']!r}"
    )
    assert stored["status"] == "CERTIFIED", (
        f"a certified system must read back as CERTIFIED, got {stored['status']}"
    )
    assert_instant_equals(stored["certified_at"], CLOCK, "certified_at")
    assert stored["decertified_at"] is None, (
        f"decertified_at must still be null, got {stored['decertified_at']!r}"
    )
    assert stored["decertification_reason"] is None, (
        "decertification_reason must still be null, got "
        f"{stored['decertification_reason']!r}"
    )


def test_quality_rule_pages_run_in_creation_order_over_an_accurate_total(api):
    """Listing a domain's quality rules two at a time walks them in the order
    they were defined and reports the size of the whole filtered set on every
    page, not just the size of the page returned.

    PRD §2.3: "`limit` caps the number of rows returned; when omitted it
    defaults to 10, its minimum accepted value is 1 and its maximum accepted
    value is 100."

    PRD §2.3: "Unless a specific endpoint says otherwise, list results are
    ordered by `created_at` ascending — never by `id`."

    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`,
    `total_count` and `has_more` alongside the `data` array, where `total_count`
    is the size of the full filtered result set and `has_more` states whether
    rows remain beyond the returned page."

    Design: Corner/entities/quality_rules_list_paginates_with_total_count_and_has_more
    """
    ctx = setup_draft_domain(rules=[])
    domain_id = ctx["domain"]["id"]
    steward_id = ctx["steward"]["id"]

    set_clock("2026-08-05T01:00:00Z")
    create_quality_rule(
        domain_id,
        steward_id,
        ctx["steward_headers"],
        rule_code="QR1",
        dimension="COMPLETENESS",
        weight_points=30,
        threshold_pct=90.00,
        severity="HIGH",
    )
    set_clock("2026-08-05T02:00:00Z")
    create_quality_rule(
        domain_id,
        steward_id,
        ctx["steward_headers"],
        rule_code="QR2",
        dimension="VALIDITY",
        weight_points=20,
        threshold_pct=80.00,
        severity="MEDIUM",
    )
    set_clock("2026-08-05T03:00:00Z")
    create_quality_rule(
        domain_id,
        steward_id,
        ctx["steward_headers"],
        rule_code="QR3",
        dimension="TIMELINESS",
        weight_points=10,
        threshold_pct=70.00,
        severity="LOW",
    )

    first_page, first_meta = validate_paginated(
        api.list_quality_rules(
            AUDITOR_HEADERS,
            params={"domain_id": domain_id, "limit": 2, "offset": 0},
        )
    )
    for rule in first_page:
        assert_quality_rule(rule)

    assert len(first_page) == 2, (
        f"a limit of two must return two rules, got {len(first_page)}"
    )
    assert [rule["rule_code"] for rule in first_page] == ["QR1", "QR2"], (
        "the first page must hold the two earliest-defined rules in definition "
        f"order, got {[rule['rule_code'] for rule in first_page]}"
    )
    assert first_meta["limit"] == 2, (
        f"meta must echo the requested limit, got {first_meta['limit']!r}"
    )
    assert first_meta["offset"] == 0, (
        f"meta must echo the requested offset, got {first_meta['offset']!r}"
    )
    assert first_meta["total_count"] == 3, (
        "total_count must report all three rules of the filtered set, got "
        f"{first_meta['total_count']!r}"
    )
    assert first_meta["has_more"] is True, (
        "has_more must state that a third rule remains beyond the first page, "
        f"got {first_meta['has_more']!r}"
    )

    second_page, second_meta = validate_paginated(
        api.list_quality_rules(
            AUDITOR_HEADERS,
            params={"domain_id": domain_id, "limit": 2, "offset": 2},
        )
    )

    assert [rule["rule_code"] for rule in second_page] == ["QR3"], (
        "the second page must hold only the last-defined rule, got "
        f"{[rule['rule_code'] for rule in second_page]}"
    )
    assert second_meta["total_count"] == 3, (
        "total_count must stay the size of the whole filtered set on the last "
        f"page, got {second_meta['total_count']!r}"
    )
    assert second_meta["has_more"] is False, (
        "has_more must state that no rules remain beyond the last page, got "
        f"{second_meta['has_more']!r}"
    )


def test_reading_an_unknown_master_record_names_the_record_registry(api):
    """A master record identifier that resolves to no row is refused with the
    error that names the master record registry specifically.

    PRD §2.9: "Path parameters are validated left to right, and the first
    identifier in the path that does not resolve to an existing row determines
    the 404 error returned."

    PRD §2.9: "The parameter names and their corresponding errors are:
    `domain_id` → `ERR_DOMAIN_NOT_FOUND`; `source_system_id` →
    `ERR_SOURCE_SYSTEM_NOT_FOUND`; `steward_id` → `ERR_STEWARD_NOT_FOUND`;
    `registration_id` → `ERR_REGISTRATION_NOT_FOUND`; `assignment_id` →
    `ERR_ASSIGNMENT_NOT_FOUND`; `rule_id` → `ERR_QUALITY_RULE_NOT_FOUND`;
    `run_id` → `ERR_SCORECARD_RUN_NOT_FOUND`; `finding_id` →
    `ERR_FINDING_NOT_FOUND`; `record_id` → `ERR_MASTER_RECORD_NOT_FOUND`;
    `proposal_id` → `ERR_MERGE_PROPOSAL_NOT_FOUND`; `change_request_id` →
    `ERR_CHANGE_REQUEST_NOT_FOUND`; `subscription_id` →
    `ERR_SUBSCRIPTION_NOT_FOUND`."

    Design: Corner/entities/master_record_not_found_returns_error
    """
    set_clock(CLOCK)

    response = api.get_master_record(NON_EXISTENT_UUID, AUDITOR_HEADERS)

    validate_error(response, ApiErrorId.ERR_MASTER_RECORD_NOT_FOUND)


def test_defining_a_domain_without_a_classification_level_is_refused(api):
    """A domain definition that omits the classification governing sensitive
    handling is a schema violation, and nothing is registered.

    PRD §3.1: "A `GovernanceAdmin` supplies the domain's `code` — one of the
    four master data domains `CUSTOMER`, `PRODUCT`, `VENDOR` or `LOCATION`, and
    no two domain definitions may share a code, a second attempt being rejected
    with `ERR_DUPLICATE_DOMAIN_CODE` — together with a human-readable `name` of
    between 1 and 120 characters and the `classification_level` that governs
    sensitive handling."

    PRD §2.9: "Required fields present, enum members valid, numeric ranges
    respected, array shapes valid — a `measurements` array whose entries each
    carry `rule_code` and `measured_pct`, a `lineage_path` with at least three
    entries — and string minimum lengths met."

    PRD §2.9: "Violation: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/domain_creation_missing_classification_level_rejected
    """
    set_clock(CLOCK)

    response = api.create_domain(
        {"code": "PRODUCT", "name": "Product Master"}, GOVERNANCE_ADMIN_HEADERS
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    remaining, meta = validate_paginated(api.list_domains(AUDITOR_HEADERS))
    assert meta["total_count"] == 0, (
        "a refused definition must leave no domain behind, got "
        f"{meta['total_count']} domains"
    )
    assert remaining == [], (
        f"a refused definition must leave the registry empty, got {remaining!r}"
    )


def test_consumer_subscription_with_an_unknown_criticality_tier_is_refused(api):
    """A downstream consumer may only be registered at one of the three declared
    criticality tiers, and a tier outside that set is a schema violation.

    PRD §3.9: "The governance office registers it with the `domain_id` consumed,
    a `consumer_code` of 1 to 40 characters unique across all subscriptions
    (`ERR_DUPLICATE_CONSUMER_CODE` on a collision), the `reporting_asset_key`
    naming the terminal reporting asset the consumer produces, a
    `clearance_level`, a `criticality` of `TIER1`, `TIER2` or `TIER3`, and the
    `required_lead_days` — between 1 and 30 — of notice this consumer needs
    before a structural change."

    PRD §2.9: "Required fields present, enum members valid, numeric ranges
    respected, array shapes valid — a `measurements` array whose entries each
    carry `rule_code` and `measured_pct`, a `lineage_path` with at least three
    entries — and string minimum lengths met."

    PRD §2.9: "Violation: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/consumer_subscription_type_constraints_enforced
    """
    set_clock(CLOCK)
    domain = create_domain()

    response = api.create_consumer_subscription(
        consumer_subscription_payload(domain["id"], criticality="TIER0"),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(api.list_consumer_subscriptions(AUDITOR_HEADERS))
    assert meta["total_count"] == 0, (
        "a refused registration must leave no subscription behind, got "
        f"{meta['total_count']} subscriptions"
    )


def test_consumer_subscription_demanding_more_than_thirty_days_notice_is_refused(
    api,
):
    """A downstream consumer may demand at most thirty days of notice, and a
    demand beyond that range is a schema violation.

    PRD §3.9: "The governance office registers it with the `domain_id` consumed,
    a `consumer_code` of 1 to 40 characters unique across all subscriptions
    (`ERR_DUPLICATE_CONSUMER_CODE` on a collision), the `reporting_asset_key`
    naming the terminal reporting asset the consumer produces, a
    `clearance_level`, a `criticality` of `TIER1`, `TIER2` or `TIER3`, and the
    `required_lead_days` — between 1 and 30 — of notice this consumer needs
    before a structural change."

    PRD §2.9: "Required fields present, enum members valid, numeric ranges
    respected, array shapes valid — a `measurements` array whose entries each
    carry `rule_code` and `measured_pct`, a `lineage_path` with at least three
    entries — and string minimum lengths met."

    PRD §2.9: "Violation: `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/consumer_subscription_type_constraints_enforced
    """
    set_clock(CLOCK)
    domain = create_domain()

    response = api.create_consumer_subscription(
        consumer_subscription_payload(domain["id"], required_lead_days=31),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    accepted = validate_success(
        api.create_consumer_subscription(
            consumer_subscription_payload(domain["id"], required_lead_days=30),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        expected_status=201,
    )
    assert_consumer_subscription(accepted)
    assert accepted["required_lead_days"] == 30, (
        "thirty days of notice is inside the accepted range, got "
        f"{accepted['required_lead_days']!r}"
    )
    assert accepted["criticality"] == "TIER1", (
        f"the declared criticality tier must be stored, got {accepted['criticality']!r}"
    )


def test_ingested_record_completeness_counts_only_usable_attribute_keys(api):
    """Completeness is measured by the server against the domain's attribute
    expectation, counting neither absent keys, nor null values, nor empty
    strings, whatever the caller might wish it to be.

    PRD §3.6: "The system counts the attribute keys that are physically present
    in `attributes` with a value that is neither null nor the empty string — an
    absent key and a null-valued key are both counted as missing, and so is an
    empty string."

    PRD §3.6: "That count is divided by the domain's `expected_attribute_count`,
    multiplied by one hundred, and rounded half up to two decimal places; the
    result is then capped at 100.00, so a record carrying more populated keys
    than the domain expects reads as exactly complete rather than
    over-complete."

    PRD §3.6: "A newly ingested record begins with `curation_status`
    `CANDIDATE` and `publication_status` `UNPUBLISHED`, and with
    `superseded_by_master_record_id`, `published_at` and `quarantine_reason` all
    null."

    Design: Corner/entities/master_record_completeness_pct_is_computed_not_supplied
    """
    ctx = setup_draft_domain()

    record = add_master_record(
        ctx,
        source_code="ERP",
        curate=False,
        natural_key="ERP-CUST-2001",
        attributes={
            "legal_name": "Beta Holdings",
            "tax_id": "TX-91",
            "billing_city": "Denver",
            "contact_email": None,
            "duns": "",
        },
        last_verified_at=CLOCK,
    )
    assert_master_record(record)

    assert ctx["domain"]["expected_attribute_count"] == 5, (
        "this domain expects five attribute keys, got "
        f"{ctx['domain']['expected_attribute_count']!r}"
    )
    assert record["completeness_pct"] == 60.00, (
        "three usable keys out of the five expected must read as 60.00 percent "
        f"complete, got {record['completeness_pct']!r}"
    )
    assert record["curation_status"] == "CANDIDATE", (
        f"a newly ingested record must be a CANDIDATE, got {record['curation_status']}"
    )
    assert record["publication_status"] == "UNPUBLISHED", (
        "a newly ingested record must be UNPUBLISHED, got "
        f"{record['publication_status']}"
    )
    assert record["published_at"] is None, (
        f"published_at must start null, got {record['published_at']!r}"
    )
    assert record["superseded_by_master_record_id"] is None, (
        "superseded_by_master_record_id must start null, got "
        f"{record['superseded_by_master_record_id']!r}"
    )
    assert record["quarantine_reason"] is None, (
        f"quarantine_reason must start null, got {record['quarantine_reason']!r}"
    )


def test_ingested_record_survivorship_adds_trust_completeness_and_recency(api):
    """The survivorship score is computed by the server from the contributing
    source's trust tier, the record's own completeness and the freshness of its
    verification instant.

    PRD §3.6: "The **trust component** is the contributing source system's
    `trust_tier` multiplied by ten, so it ranges from 10 points for a tier-1
    system up to 50 points for a tier-5 one."

    PRD §3.6: "The **completeness component** is the record's `completeness_pct`
    multiplied by four tenths and rounded half up to two decimal places, so it
    ranges from 0 up to 40 points."

    PRD §3.6: "The **recency component** starts from a maximum of 20 points and
    decays by 4 points for every whole month of staleness, where staleness in
    months is the number of whole days between the record's `last_verified_at`
    and the current logical clock, divided by thirty and rounded down to a whole
    number; the component is floored at zero, so a record more than five whole
    months stale contributes 0 rather than a negative number."

    PRD §3.6: "The three components are added and the total rounded half up to
    two decimal places."

    Design: Corner/entities/master_record_completeness_pct_is_computed_not_supplied
    """
    ctx = setup_draft_domain()

    assert ctx["sources"]["ERP"]["trust_tier"] == 4, (
        "the contributing source sits at trust tier four, got "
        f"{ctx['sources']['ERP']['trust_tier']!r}"
    )

    record = add_master_record(
        ctx,
        source_code="ERP",
        curate=False,
        natural_key="ERP-CUST-2001",
        attributes={
            "legal_name": "Beta Holdings",
            "tax_id": "TX-91",
            "billing_city": "Denver",
            "contact_email": None,
            "duns": "",
        },
        last_verified_at=CLOCK,
    )
    assert_master_record(record)

    assert record["completeness_pct"] == 60.00, (
        "three usable keys out of five expected must read as 60.00 percent "
        f"complete, got {record['completeness_pct']!r}"
    )
    assert record["survivorship_score"] == 84.00, (
        "forty trust points, twenty-four completeness points and a full twenty "
        "recency points for a record verified at the current instant must total "
        f"84.00, got {record['survivorship_score']!r}"
    )


def test_scorecard_run_reads_back_as_an_immutable_audit_row(api):
    """A recorded scorecard run carries an identifier and a creation instant but
    neither an update instant nor a version, because nothing may ever rewrite
    it.

    PRD §2.4: "The single exception is `ScorecardRun`: a scorecard run is an
    immutable audit artefact, so it carries only `id` and `created_at` — it has
    neither `updated_at` nor `version`, and nothing in the system ever rewrites
    a run once it has been recorded."

    PRD §3.4: "Runs are immutable once written: they may be read individually
    and listed filtered by `domain_id` and by `basis`, but never modified, which
    is why a run carries no `updated_at` and no `version`."

    PRD §3.4: "The domain's `scorecard_run_seq` is incremented by one and the
    resulting value is copied onto the run as `run_seq`, the run's `measured_at`
    is stamped from the logical clock, and the run's `domain_id` records the
    domain scored."

    Design: Corner/entities/scorecard_run_is_immutable_and_carries_no_version
    """
    ctx = setup_draft_domain()

    run = run_scorecard(
        ctx,
        basis="PROVISIONAL",
        measurements=[{"rule_code": "QR1", "measured_pct": 95.00}],
    )

    stored = validate_success(api.get_scorecard_run(run["id"], AUDITOR_HEADERS))
    assert_scorecard_run(stored)

    assert stored["id"] == run["id"], (
        "the read must return the run that was recorded"
    )
    assert is_valid_uuid(stored["id"]), (
        f"id must be a bare UUID string, got {stored['id']!r}"
    )
    assert is_iso8601_timestamp(stored["created_at"]), (
        f"created_at must be an ISO 8601 UTC instant, got {stored['created_at']!r}"
    )
    assert "updated_at" not in stored, (
        "an immutable audit artefact must carry no updated_at, got "
        f"{stored.get('updated_at')!r}"
    )
    assert "version" not in stored, (
        f"an immutable audit artefact must carry no version, got {stored.get('version')!r}"
    )
    assert stored["run_seq"] == 1, (
        f"the first run of a domain must carry run_seq 1, got {stored['run_seq']!r}"
    )
    assert stored["domain_id"] == ctx["domain"]["id"], (
        f"the run must record the domain scored, got {stored['domain_id']!r}"
    )
    assert_instant_equals(stored["measured_at"], CLOCK, "measured_at")


def test_quality_rule_naming_an_unregistered_domain_is_refused(api):
    """A quality rule may only be defined against a domain that exists, and an
    unknown domain in the body is refused before any rule is written.

    PRD §2.9: "Every identifier supplied in the request body resolves to an
    existing row — `domain_id`, `source_system_id`, `steward_id`,
    `owner_steward_id`, `assigned_steward_id`, `survivor_master_record_id` and
    `duplicate_master_record_id` — yielding the corresponding 404
    (`ERR_DOMAIN_NOT_FOUND`, `ERR_SOURCE_SYSTEM_NOT_FOUND`,
    `ERR_STEWARD_NOT_FOUND`, `ERR_MASTER_RECORD_NOT_FOUND`)."

    PRD §2.9: "This step guards source-registration creation, steward-assignment
    creation, quality-rule creation, master-record ingestion, merge-proposal
    creation, change-request creation, consumer-subscription creation, and
    remediation planning on a finding."

    Design: Corner/entities/quality_rule_body_fk_domain_not_found
    """
    ctx = setup_draft_domain(rules=[])

    response = api.create_quality_rule(
        quality_rule_payload(NON_EXISTENT_UUID, ctx["steward"]["id"]),
        ctx["steward_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DOMAIN_NOT_FOUND)

    _, meta = validate_paginated(
        api.list_quality_rules(
            AUDITOR_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused definition must leave no rule behind, got {meta['total_count']} rules"
    )


def test_quality_rule_naming_an_unregistered_owner_steward_is_refused(api):
    """A quality rule must name an owning steward that exists, and an unknown
    steward in the body is refused before any rule is written.

    PRD §2.9: "Every identifier supplied in the request body resolves to an
    existing row — `domain_id`, `source_system_id`, `steward_id`,
    `owner_steward_id`, `assigned_steward_id`, `survivor_master_record_id` and
    `duplicate_master_record_id` — yielding the corresponding 404
    (`ERR_DOMAIN_NOT_FOUND`, `ERR_SOURCE_SYSTEM_NOT_FOUND`,
    `ERR_STEWARD_NOT_FOUND`, `ERR_MASTER_RECORD_NOT_FOUND`)."

    PRD §2.9: "This step guards source-registration creation, steward-assignment
    creation, quality-rule creation, master-record ingestion, merge-proposal
    creation, change-request creation, consumer-subscription creation, and
    remediation planning on a finding."

    Design: Corner/entities/quality_rule_body_fk_domain_not_found
    """
    ctx = setup_draft_domain(rules=[])

    response = api.create_quality_rule(
        quality_rule_payload(ctx["domain"]["id"], NON_EXISTENT_UUID),
        ctx["steward_headers"],
    )

    validate_error(response, ApiErrorId.ERR_STEWARD_NOT_FOUND)

    _, meta = validate_paginated(
        api.list_quality_rules(
            AUDITOR_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"a refused definition must leave no rule behind, got {meta['total_count']} rules"
    )


def test_one_source_system_serves_two_domains_through_separate_registrations(api):
    """A single source system may be registered into two domains at once, each
    registration standing on its own with its own role and its own trust rank.

    PRD §3.2: "Registrations are created in `status` `ACTIVE` with
    `superseded_at` and `revoked_reason` null, and may be listed filtered by
    `domain_id`, `source_system_id`, `role` and `status`."

    PRD §3.2: "Registering a source against a domain is how the governance
    office declares what a system means to that domain."

    PRD §3.2: "The registration payload carries the `domain_id`, the
    `source_system_id`, the designated `role` — `AUTHORITATIVE`, `CONTRIBUTING`
    or `CONSUMING` — a domain-local `trust_rank` between 1 and 10 in which 1 is
    the highest precedence, an inclusive `effective_from`, an optional exclusive
    `effective_to`, and the `expected_domain_version` demanded by §2.5."

    Design: Corner/entities/one_source_system_registers_into_two_domains_independently
    """
    set_clock(CLOCK)
    erp = create_source_system(certify=True, code="ERP", name="ERP Core", trust_tier=4)
    customer = create_domain(code="CUSTOMER", name="Customer Master")
    product = create_domain(code="PRODUCT", name="Product Master")

    customer_registration = register_source(
        customer["id"], erp["id"], role="AUTHORITATIVE", trust_rank=1
    )
    product_registration = register_source(
        product["id"], erp["id"], role="CONTRIBUTING", trust_rank=2
    )
    assert_source_registration(customer_registration)
    assert_source_registration(product_registration)

    assert customer_registration["id"] != product_registration["id"], (
        "each domain must hold its own registration row for the shared source"
    )
    assert customer_registration["role"] == "AUTHORITATIVE", (
        "the customer domain draws from the shared source as its system of "
        f"record, got {customer_registration['role']}"
    )
    assert customer_registration["trust_rank"] == 1, (
        f"the declared trust rank must be stored, got {customer_registration['trust_rank']!r}"
    )
    assert product_registration["role"] == "CONTRIBUTING", (
        "the product domain only draws candidate records from the shared "
        f"source, got {product_registration['role']}"
    )
    assert product_registration["trust_rank"] == 2, (
        f"the declared trust rank must be stored, got {product_registration['trust_rank']!r}"
    )
    for registration in (customer_registration, product_registration):
        assert registration["status"] == "ACTIVE", (
            f"a new registration must be ACTIVE, got {registration['status']}"
        )
        assert registration["superseded_at"] is None, (
            f"superseded_at must start null, got {registration['superseded_at']!r}"
        )
        assert registration["revoked_reason"] is None, (
            f"revoked_reason must start null, got {registration['revoked_reason']!r}"
        )

    shared, meta = validate_paginated(
        api.list_source_registrations(
            AUDITOR_HEADERS, params={"source_system_id": erp["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "the shared source must carry exactly two registrations, got "
        f"{meta['total_count']}"
    )
    assert {row["domain_id"] for row in shared} == {customer["id"], product["id"]}, (
        "the shared source must be registered into both domains, got "
        f"{[row['domain_id'] for row in shared]}"
    )


def test_only_the_authoritative_registration_names_the_domain_source_of_record(api):
    """Sharing a source system between two domains gives only the domain holding
    the authoritative registration a source of record, and only that domain's
    posture is unblocked by it.

    PRD §3.2: "Note that `authoritative_source_code` holds a source system's
    short code, not an identifier, and that it is derived rather than declared:
    it always reflects whichever registration currently has `role` of
    `AUTHORITATIVE` and `status` of `ACTIVE` for the domain, and it is null when
    no such registration exists."

    PRD §2.6: "The posture is then determined in this priority order: it is
    `FROZEN` if the domain holds no such active authoritative registration, or
    if `open_finding_weight` is at least 40.00; otherwise it is `RESTRICTED` if
    `open_finding_weight` is at least 15.00, or if at least one finding in the
    open set is governed by a rule whose `severity` is `CRITICAL`; otherwise it
    is `OPEN`."

    Design: Corner/entities/one_source_system_registers_into_two_domains_independently
    """
    set_clock(CLOCK)
    erp = create_source_system(certify=True, code="ERP", name="ERP Core", trust_tier=4)
    customer = create_domain(code="CUSTOMER", name="Customer Master")
    product = create_domain(code="PRODUCT", name="Product Master")

    register_source(customer["id"], erp["id"], role="AUTHORITATIVE", trust_rank=1)
    register_source(product["id"], erp["id"], role="CONTRIBUTING", trust_rank=2)

    customer_state = read_domain(customer["id"])
    product_state = read_domain(product["id"])
    assert_domain(customer_state)
    assert_domain(product_state)

    assert customer_state["authoritative_source_code"] == "ERP", (
        "the domain holding the authoritative registration must report the "
        f"source's short code, got {customer_state['authoritative_source_code']!r}"
    )
    assert customer_state["governance_posture"] == "OPEN", (
        "a domain with a certified authoritative source and no open findings "
        f"must be OPEN, got {customer_state['governance_posture']}"
    )
    assert product_state["authoritative_source_code"] is None, (
        "a domain holding only a contributing registration has no source of "
        f"record, got {product_state['authoritative_source_code']!r}"
    )
    assert product_state["governance_posture"] == "FROZEN", (
        "a domain with no active authoritative registration must stay FROZEN, "
        f"got {product_state['governance_posture']}"
    )
