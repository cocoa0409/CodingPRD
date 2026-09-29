"""The refusal contract of the governance API: which rejection, and nothing moved.

Governance is mostly a story about what the system declines to do. These tests
walk the refusals one identifier at a time — unresolvable path identifiers,
colliding registry codes, scoped uniqueness, self-merges, an unjustified
medium-confidence merge, malformed lineage geometry, a self-parenting hierarchy
node, a degenerate registration interval, the finding and rule-retirement gates,
the curation and publication gates, the domain lifecycle gates, incomplete
stewardship, a missing certified authoritative source, and the five gates that
guard applying a scheduled change — and in each case check that the refused
write left no trace behind it.
"""

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    CLOCK,
    GOVERNANCE_ADMIN_HEADERS,
    NON_EXISTENT_UUID,
    add_change_request,
    add_consumer_subscription,
    add_master_record,
    add_merge_proposal,
    assert_instant_equals,
    change_request_payload,
    consumer_subscription_payload,
    create_domain,
    create_quality_rule,
    create_source_system,
    create_steward,
    document_lineage_for,
    domain_payload,
    domain_version,
    make_consumer_rep_headers,
    master_record_payload,
    merge_proposal_payload,
    open_finding,
    quality_rule_payload,
    read_domain,
    register_source,
    set_clock,
    setup_domain_awaiting_data_steward,
    setup_draft_domain,
    setup_governed_domain,
    source_registration_payload,
    source_system_payload,
    steward_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The CUSTOMER domain expects five attribute keys, so a five-key record reads as
# exactly complete and clears the sixty-percent publication bar.
COMPLETE_ATTRIBUTES = {
    "legal_name": "Orion Foundry",
    "tax_id": "TX-8801",
    "billing_city": "Duluth",
    "contact_email": "ap@orion.test",
    "duns": "22-880-1000",
}
NEAR_DUPLICATE_ATTRIBUTES = {
    "legal_name": "Orion Foundry Inc",
    "tax_id": "TX-8801",
    "billing_city": "Duluth",
    "contact_email": "ar@orion.test",
    "duns": "22-880-1000",
}

UNCERTIFIED_CRM = {
    "code": "CRM",
    "name": "CRM Cloud",
    "trust_tier": 3,
    "certify": False,
    "register": False,
}
CERTIFIED_AUTHORITATIVE_ERP = {
    "code": "ERP",
    "name": "ERP Core",
    "trust_tier": 4,
    "role": "AUTHORITATIVE",
    "trust_rank": 1,
    "certify": True,
    "register": True,
}
UNREGISTERED_CERTIFIED_ERP = {
    "code": "ERP",
    "name": "ERP Core",
    "trust_tier": 4,
    "certify": True,
    "register": False,
}


# ---------------------------------------------------------------------------
# Unresolvable path identifiers
# ---------------------------------------------------------------------------

_MISSING_ROW_READS = [
    ("domain", lambda api: api.get_domain(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_DOMAIN_NOT_FOUND"),
    ("source_system",
     lambda api: api.get_source_system(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_SOURCE_SYSTEM_NOT_FOUND"),
    ("steward", lambda api: api.get_steward(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_STEWARD_NOT_FOUND"),
    ("source_registration",
     lambda api: api.get_source_registration(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_REGISTRATION_NOT_FOUND"),
    ("steward_assignment",
     lambda api: api.get_steward_assignment(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_ASSIGNMENT_NOT_FOUND"),
    ("quality_rule",
     lambda api: api.get_quality_rule(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_QUALITY_RULE_NOT_FOUND"),
    ("scorecard_run",
     lambda api: api.get_scorecard_run(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_SCORECARD_RUN_NOT_FOUND"),
    ("quality_finding",
     lambda api: api.get_quality_finding(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_FINDING_NOT_FOUND"),
    ("master_record",
     lambda api: api.get_master_record(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_MASTER_RECORD_NOT_FOUND"),
    ("merge_proposal",
     lambda api: api.get_merge_proposal(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_MERGE_PROPOSAL_NOT_FOUND"),
    ("change_request",
     lambda api: api.get_change_request(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_CHANGE_REQUEST_NOT_FOUND"),
    ("consumer_subscription",
     lambda api: api.get_consumer_subscription(NON_EXISTENT_UUID, AUDITOR_HEADERS),
     "ERR_SUBSCRIPTION_NOT_FOUND"),
]


@pytest.mark.parametrize(
    "read_missing_row,expected_error_id",
    [(probe, error_id) for _, probe, error_id in _MISSING_ROW_READS],
    ids=[name for name, _, _ in _MISSING_ROW_READS],
)
def test_every_resource_names_its_own_not_found_error(
    api, read_missing_row, expected_error_id
):
    """Each path parameter reports the 404 identifier that belongs to its resource.

    PRD §2.9: "Path parameters are validated left to right, and the first identifier in the path that does not resolve to an existing row determines the 404 error returned. The parameter names and their corresponding errors are: `domain_id` → `ERR_DOMAIN_NOT_FOUND`; `source_system_id` → `ERR_SOURCE_SYSTEM_NOT_FOUND`; `steward_id` → `ERR_STEWARD_NOT_FOUND`; `registration_id` → `ERR_REGISTRATION_NOT_FOUND`; `assignment_id` → `ERR_ASSIGNMENT_NOT_FOUND`; `rule_id` → `ERR_QUALITY_RULE_NOT_FOUND`; `run_id` → `ERR_SCORECARD_RUN_NOT_FOUND`; `finding_id` → `ERR_FINDING_NOT_FOUND`; `record_id` → `ERR_MASTER_RECORD_NOT_FOUND`; `proposal_id` → `ERR_MERGE_PROPOSAL_NOT_FOUND`; `change_request_id` → `ERR_CHANGE_REQUEST_NOT_FOUND`; `subscription_id` → `ERR_SUBSCRIPTION_NOT_FOUND`."

    Design: Corner/errors/path_id_not_found_sweep_across_every_resource
    """
    set_clock()

    validate_error(read_missing_row(api), expected_error_id)


# ---------------------------------------------------------------------------
# Globally unique registry codes
# ---------------------------------------------------------------------------


def _seed_registries():
    """One domain, one source system and one steward, each with its own code."""
    set_clock()
    domain = create_domain()
    source_system = create_source_system(certify=False)
    steward = create_steward()
    return domain, source_system, steward


def test_each_registry_collision_reports_its_own_duplicate_error(api):
    """A domain code, a source code and a steward email each collide differently.

    PRD §3.1: "A `GovernanceAdmin` supplies the domain's `code` — one of the four master data domains `CUSTOMER`, `PRODUCT`, `VENDOR` or `LOCATION`, and no two domain definitions may share a code, a second attempt being rejected with `ERR_DUPLICATE_DOMAIN_CODE` — together with a human-readable `name` of between 1 and 120 characters and the `classification_level` that governs sensitive handling."
    PRD §3.1: "Each `SourceSystem` carries a short `code` of 1 to 30 characters that must be unique system-wide — a collision is `ERR_DUPLICATE_SOURCE_CODE` — a descriptive `name`, and a `trust_tier` between 1 and 5 in which 5 denotes the most trusted system."
    PRD §3.1: "A `Steward` row carries a `full_name`, an `email` that must be unique across all stewards (`ERR_DUPLICATE_STEWARD_EMAIL` otherwise), and a `certification_level` of `JUNIOR`, `SENIOR` or `PRINCIPAL`."

    Design: Corner/errors/registry_codes_are_globally_unique
    """
    _seed_registries()

    validate_error(
        api.create_domain(
            domain_payload(code="CUSTOMER", name="Customer Master Second Attempt"),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_DUPLICATE_DOMAIN_CODE",
    )
    validate_error(
        api.create_source_system(
            source_system_payload(code="ERP", name="ERP Secondary", trust_tier=2),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_DUPLICATE_SOURCE_CODE",
    )
    validate_error(
        api.create_steward(
            steward_payload(
                full_name="Sam Namesake",
                email="sam@mdm.test",
                certification_level="JUNIOR",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_DUPLICATE_STEWARD_EMAIL",
    )


def test_refused_registry_duplicates_leave_one_row_in_each_registry(api):
    """None of the three refused registrations persisted anything.

    PRD §3.1: "A `GovernanceAdmin` supplies the domain's `code` — one of the four master data domains `CUSTOMER`, `PRODUCT`, `VENDOR` or `LOCATION`, and no two domain definitions may share a code, a second attempt being rejected with `ERR_DUPLICATE_DOMAIN_CODE` — together with a human-readable `name` of between 1 and 120 characters and the `classification_level` that governs sensitive handling."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more` alongside the `data` array, where `total_count` is the size of the full filtered result set and `has_more` states whether rows remain beyond the returned page."

    Design: Corner/errors/registry_codes_are_globally_unique
    """
    _seed_registries()
    validate_error(
        api.create_domain(
            domain_payload(code="CUSTOMER", name="Customer Master Second Attempt"),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_DUPLICATE_DOMAIN_CODE",
    )
    validate_error(
        api.create_source_system(
            source_system_payload(code="ERP", name="ERP Secondary", trust_tier=2),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_DUPLICATE_SOURCE_CODE",
    )
    validate_error(
        api.create_steward(
            steward_payload(
                full_name="Sam Namesake",
                email="sam@mdm.test",
                certification_level="JUNIOR",
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_DUPLICATE_STEWARD_EMAIL",
    )

    for label, response in [
        ("domains", api.list_domains(AUDITOR_HEADERS)),
        ("source systems", api.list_source_systems(AUDITOR_HEADERS)),
        ("stewards", api.list_stewards(AUDITOR_HEADERS)),
    ]:
        rows, meta = validate_paginated(response)
        assert meta["total_count"] == 1, (
            f"the refused duplicate must leave exactly one row among the {label}, "
            f"got {meta['total_count']}"
        )
        assert meta["has_more"] is False, (
            f"one row fits on a single page of {label}, got has_more "
            f"{meta['has_more']}"
        )
        assert len(rows) == 1, (
            f"the {label} page must carry the single surviving row, got {len(rows)}"
        )


# ---------------------------------------------------------------------------
# Scoped uniqueness
# ---------------------------------------------------------------------------


def test_a_rule_code_may_not_repeat_within_its_domain(api):
    """A second rule reusing a live rule code in the same domain is refused.

    PRD §3.3: "A steward defines one by naming the `domain_id` it scores, the `owner_steward_id` accountable for it and its findings, a `rule_code` of 1 to 20 characters that must be unique within the domain (`ERR_DUPLICATE_RULE_CODE` otherwise), the `dimension` measured — one of `COMPLETENESS`, `VALIDITY`, `UNIQUENESS`, `TIMELINESS` or `CONSISTENCY` — a `weight_points` value between 1 and 100 expressing the rule's share of the scorecard, a `threshold_pct` between 0.00 and 100.00 carried to two decimal places, and a `severity` of `LOW`, `MEDIUM`, `HIGH` or `CRITICAL` that determines how heavily a breach of the rule weighs on the domain."

    Design: Corner/errors/scoped_uniqueness_holds_per_domain_and_per_source_pair
    """
    ctx = setup_draft_domain()

    response = api.create_quality_rule(
        quality_rule_payload(
            ctx["domain"]["id"],
            ctx["steward"]["id"],
            rule_code="QR1",
            dimension="VALIDITY",
            weight_points=10,
            threshold_pct=80.00,
            severity="LOW",
        ),
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_DUPLICATE_RULE_CODE")

    rows, meta = validate_paginated(
        api.list_quality_rules(AUDITOR_HEADERS, params={"domain_id": ctx["domain"]["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the refused rule must not have been defined, got {meta['total_count']} "
        "rules on the domain"
    )
    assert rows[0]["dimension"] == "COMPLETENESS", (
        "the surviving rule is the original completeness rule, got "
        f"{rows[0]['dimension']}"
    )


def test_a_natural_key_repeats_across_systems_but_not_within_one(api):
    """The same business key from a second system is the normal duplicate case.

    PRD §3.6: "The `natural_key` must be unique for the combination of domain and source system: the same business key arriving from two different systems is the normal duplicate case and is allowed, but the same key arriving twice from the same system is rejected with `ERR_DUPLICATE_NATURAL_KEY`."

    Design: Corner/errors/scoped_uniqueness_holds_per_domain_and_per_source_pair
    """
    ctx = setup_draft_domain(sources=[CERTIFIED_AUTHORITATIVE_ERP, UNCERTIFIED_CRM])
    add_master_record(
        ctx,
        source_code="ERP",
        curate=False,
        natural_key="CUST-1",
        attributes=COMPLETE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )

    same_system_again = api.create_master_record(
        master_record_payload(
            ctx["domain"]["id"],
            ctx["sources"]["ERP"]["id"],
            natural_key="CUST-1",
            attributes=NEAR_DUPLICATE_ATTRIBUTES,
            last_verified_at=CLOCK,
        ),
        ctx["steward_headers"],
    )
    validate_error(same_system_again, "ERR_DUPLICATE_NATURAL_KEY")

    from_the_other_system = validate_success(
        api.create_master_record(
            master_record_payload(
                ctx["domain"]["id"],
                ctx["sources"]["CRM"]["id"],
                natural_key="CUST-1",
                attributes=NEAR_DUPLICATE_ATTRIBUTES,
                last_verified_at=CLOCK,
            ),
            ctx["steward_headers"],
        ),
        201,
    )

    assert from_the_other_system["natural_key"] == "CUST-1", (
        "the second system contributes its own claim under the same business key, "
        f"got {from_the_other_system['natural_key']}"
    )
    assert from_the_other_system["source_system_id"] == ctx["sources"]["CRM"]["id"], (
        "the accepted record belongs to the second source system, got "
        f"{from_the_other_system['source_system_id']}"
    )


def test_a_consumer_code_may_not_repeat_anywhere(api):
    """A consumer code already in use is refused even under a different asset key.

    PRD §3.9: "The governance office registers it with the `domain_id` consumed, a `consumer_code` of 1 to 40 characters unique across all subscriptions (`ERR_DUPLICATE_CONSUMER_CODE` on a collision), the `reporting_asset_key` naming the terminal reporting asset the consumer produces, a `clearance_level`, a `criticality` of `TIER1`, `TIER2` or `TIER3`, and the `required_lead_days` — between 1 and 30 — of notice this consumer needs before a structural change."

    Design: Corner/errors/scoped_uniqueness_holds_per_domain_and_per_source_pair
    """
    ctx = setup_draft_domain()
    add_consumer_subscription(
        ctx,
        consumer_code="BI_A",
        reporting_asset_key="RPT_A",
        clearance_level="INTERNAL",
        criticality="TIER2",
        required_lead_days=5,
    )

    response = api.create_consumer_subscription(
        consumer_subscription_payload(
            ctx["domain"]["id"],
            consumer_code="BI_A",
            reporting_asset_key="RPT_B",
            clearance_level="INTERNAL",
            criticality="TIER3",
            required_lead_days=2,
        ),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(response, "ERR_DUPLICATE_CONSUMER_CODE")

    _, meta = validate_paginated(
        api.list_consumer_subscriptions(
            AUDITOR_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"the refused registration must not have persisted, got {meta['total_count']} "
        "subscriptions"
    )


# ---------------------------------------------------------------------------
# Merging a record with itself
# ---------------------------------------------------------------------------


def test_proposing_a_record_as_its_own_duplicate_is_refused(api):
    """A proposal naming one record twice is not a duplicate hypothesis.

    PRD §3.7: "The two records must belong to the same domain, or the proposal is rejected with `ERR_CROSS_DOMAIN_MERGE`, and they must be distinct rows, a proposal naming the same record twice being rejected with `ERR_SELF_MERGE`."

    Design: Corner/errors/self_merge_is_refused
    """
    ctx = setup_draft_domain()
    record = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-1001",
        attributes=COMPLETE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )

    response = api.create_merge_proposal(
        merge_proposal_payload(record["id"], record["id"]),
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_SELF_MERGE")


def test_a_refused_self_merge_leaves_no_proposal_behind(api):
    """The refused self-merge persisted no proposal on the domain.

    PRD §3.7: "The two records must belong to the same domain, or the proposal is rejected with `ERR_CROSS_DOMAIN_MERGE`, and they must be distinct rows, a proposal naming the same record twice being rejected with `ERR_SELF_MERGE`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more` alongside the `data` array, where `total_count` is the size of the full filtered result set and `has_more` states whether rows remain beyond the returned page."

    Design: Corner/errors/self_merge_is_refused
    """
    ctx = setup_draft_domain()
    record = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-1001",
        attributes=COMPLETE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    validate_error(
        api.create_merge_proposal(
            merge_proposal_payload(record["id"], record["id"]),
            ctx["steward_headers"],
        ),
        "ERR_SELF_MERGE",
    )

    rows, meta = validate_paginated(
        api.list_merge_proposals(
            AUDITOR_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )

    assert meta["total_count"] == 0, (
        f"a refused proposal is never persisted, got {meta['total_count']}"
    )
    assert rows == [], f"the proposal page must be empty, got {rows}"


# ---------------------------------------------------------------------------
# The confidence bar on a merge decision
# ---------------------------------------------------------------------------


def _medium_confidence_proposal_under_review(ctx):
    """Two intra-source ERP claims proposed and taken under review by the owner."""
    primary = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-8801-A",
        attributes=COMPLETE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    secondary = add_master_record(
        ctx,
        source_code="ERP",
        natural_key="ERP-CUST-8801-B",
        attributes=NEAR_DUPLICATE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    proposal = add_merge_proposal(
        ctx,
        primary,
        secondary,
        review=True,
        name_similarity_pct=90.00,
        key_overlap_pct=100.00,
    )
    assert proposal["match_score"] == 76.00, (
        "half of 90.00 plus three tenths of 100.00 plus two tenths of 100.00 is "
        "95.00, and the intra-source discount takes it to 76.00, got "
        f"{proposal['match_score']}"
    )
    assert proposal["match_confidence"] == "MEDIUM", (
        f"76.00 sits in the medium confidence band, got {proposal['match_confidence']}"
    )
    assert proposal["status"] == "UNDER_REVIEW", (
        f"the proposal must be under review before a decision, got {proposal['status']}"
    )
    return primary, secondary, proposal


def test_a_medium_confidence_merge_without_a_justification_is_refused(api):
    """Medium confidence buys no merge unless the owner justifies the override.

    PRD §3.7: "And the confidence bar must be met: a `HIGH`-confidence proposal merges freely, a `MEDIUM`-confidence proposal merges only when the data owner supplies an `override_justification` of at least 20 characters, and a `LOW`-confidence proposal cannot be merged at all — the failures in the medium-without-justification and low cases are both `ERR_MATCH_CONFIDENCE_TOO_LOW`."

    Design: Corner/errors/medium_confidence_merge_needs_an_override_justification
    """
    ctx = setup_governed_domain()
    primary, secondary, proposal = _medium_confidence_proposal_under_review(ctx)

    response = api.decide_merge_proposal(
        proposal["id"], {"decision": "MERGE"}, ctx["owner_headers"]
    )

    validate_error(response, "ERR_MATCH_CONFIDENCE_TOO_LOW")

    untouched = validate_success(api.get_merge_proposal(proposal["id"], AUDITOR_HEADERS))
    assert untouched["status"] == "UNDER_REVIEW", (
        f"a refused decision leaves the proposal under review, got {untouched['status']}"
    )
    assert untouched["effective_survivor_master_record_id"] is None, (
        "a refused decision selects no survivor, got "
        f"{untouched['effective_survivor_master_record_id']!r}"
    )
    loser = validate_success(api.get_master_record(secondary["id"], AUDITOR_HEADERS))
    assert loser["curation_status"] == "CURATED", (
        f"neither record was absorbed, got {loser['curation_status']}"
    )
    survivor = validate_success(api.get_master_record(primary["id"], AUDITOR_HEADERS))
    assert survivor["curation_status"] == "CURATED", (
        f"the nominated survivor is untouched, got {survivor['curation_status']}"
    )


def test_a_justified_medium_confidence_merge_absorbs_the_loser(api):
    """With a written override the merge lands and the loser is superseded.

    PRD §3.7: "And the confidence bar must be met: a `HIGH`-confidence proposal merges freely, a `MEDIUM`-confidence proposal merges only when the data owner supplies an `override_justification` of at least 20 characters, and a `LOW`-confidence proposal cannot be merged at all — the failures in the medium-without-justification and low cases are both `ERR_MATCH_CONFIDENCE_TOO_LOW`."
    PRD §3.7: "The **score-priority** variant applies when both candidates share the authoritative `source_system_id`, and equally when neither of them carries it — including the case where the authoritative registration has been superseded onto some third source system altogether. In that case the survivor is the candidate with the higher `survivorship_score`, breaking ties first by the later `last_verified_at` and then by the earlier `created_at`, and never by `id`."
    PRD §3.7: "Whichever variant ran is recorded as `survivorship_variant`, the chosen record's identifier is recorded as `effective_survivor_master_record_id`, and `survivor_swapped` is set true exactly when that identifier differs from the `survivor_master_record_id` the proposer originally nominated."
    PRD §3.7: "**Hop 3**, caused by hop 2's absorption of the loser, drives the loser's `curation_status` to `MERGED_AWAY` and writes the effective survivor's identifier into the loser's `superseded_by_master_record_id`; if the loser was `PUBLISHED` its `publication_status` becomes `RETRACTED` and the domain's `published_master_record_count` is decremented by one."

    Design: Corner/errors/medium_confidence_merge_needs_an_override_justification
    """
    ctx = setup_governed_domain()
    primary, secondary, proposal = _medium_confidence_proposal_under_review(ctx)

    decided = validate_success(
        api.decide_merge_proposal(
            proposal["id"],
            {
                "decision": "MERGE",
                "override_justification": (
                    "Both ERP claims describe the same legal entity and the tax "
                    "identifier matches exactly."
                ),
            },
            ctx["owner_headers"],
        )
    )

    assert decided["status"] == "MERGED", (
        f"a justified override completes the merge, got {decided['status']}"
    )
    assert decided["effective_survivor_master_record_id"] == primary["id"], (
        "both claims come from the authoritative source and score identically, so "
        "the earlier-created record survives, expected "
        f"{primary['id']}, got {decided['effective_survivor_master_record_id']}"
    )
    assert decided["survivor_swapped"] is False, (
        "the system chose the record the proposer nominated, so nothing was "
        f"swapped, got {decided['survivor_swapped']}"
    )

    loser = validate_success(api.get_master_record(secondary["id"], AUDITOR_HEADERS))
    assert loser["curation_status"] == "MERGED_AWAY", (
        f"the absorbed record is merged away, got {loser['curation_status']}"
    )
    assert loser["superseded_by_master_record_id"] == primary["id"], (
        "the loser points at the effective survivor, expected "
        f"{primary['id']}, got {loser['superseded_by_master_record_id']}"
    )


# ---------------------------------------------------------------------------
# Lineage path geometry
# ---------------------------------------------------------------------------


def _consumer_awaiting_lineage(register_authoritative=True):
    """A draft domain and one undocumented consumer of it."""
    ctx = setup_draft_domain(sources=[UNREGISTERED_CERTIFIED_ERP])
    if register_authoritative:
        register_source(
            ctx["domain"]["id"],
            ctx["sources"]["ERP"]["id"],
            role="AUTHORITATIVE",
            trust_rank=1,
        )
    subscription = add_consumer_subscription(
        ctx,
        consumer_code="BI_A",
        reporting_asset_key="RPT_A",
        clearance_level="INTERNAL",
        criticality="TIER1",
        required_lead_days=5,
    )
    return ctx, subscription


def test_lineage_cannot_be_documented_while_no_source_is_authoritative(api):
    """With no authoritative registration there is no valid first node at all.

    PRD §3.9: "Underlying all three, the domain must actually hold an `ACTIVE` `AUTHORITATIVE` registration — with no authoritative source there is no valid first node at all, and the attempt is rejected with `ERR_AUTHORITATIVE_SOURCE_UNDEFINED`."

    Design: Corner/errors/lineage_path_geometry_errors_are_distinguished
    """
    ctx, subscription = _consumer_awaiting_lineage(register_authoritative=False)
    assert read_domain(ctx["domain"]["id"])["authoritative_source_code"] is None, (
        "the domain holds no authoritative registration yet"
    )

    response = api.document_consumer_lineage(
        subscription["id"],
        {"lineage_path": ["ERP", "STG_CUSTOMER", "RPT_A"]},
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_AUTHORITATIVE_SOURCE_UNDEFINED")


def test_the_three_lineage_geometry_faults_are_reported_separately(api):
    """A wrong start, a wrong end and a repeated node are three different faults.

    PRD §3.9: "Its first node must equal the domain's current `authoritative_source_code`, otherwise `ERR_LINEAGE_SOURCE_MISMATCH`."
    PRD §3.9: "Its last node must equal the subscription's `reporting_asset_key`, otherwise `ERR_LINEAGE_TARGET_MISMATCH`."
    PRD §3.9: "And no node key may appear twice, because a documented flow must be acyclic; a repeat is rejected with `ERR_LINEAGE_CYCLE`."

    Design: Corner/errors/lineage_path_geometry_errors_are_distinguished
    """
    ctx, subscription = _consumer_awaiting_lineage()
    assert read_domain(ctx["domain"]["id"])["authoritative_source_code"] == "ERP", (
        "the ERP system is the domain's authoritative source"
    )

    validate_error(
        api.document_consumer_lineage(
            subscription["id"],
            {"lineage_path": ["CRM", "STG_CUSTOMER", "RPT_A"]},
            ctx["steward_headers"],
        ),
        "ERR_LINEAGE_SOURCE_MISMATCH",
    )
    validate_error(
        api.document_consumer_lineage(
            subscription["id"],
            {"lineage_path": ["ERP", "STG_CUSTOMER", "RPT_OTHER"]},
            ctx["steward_headers"],
        ),
        "ERR_LINEAGE_TARGET_MISMATCH",
    )
    validate_error(
        api.document_consumer_lineage(
            subscription["id"],
            {"lineage_path": ["ERP", "STG_CUSTOMER", "STG_CUSTOMER", "RPT_A"]},
            ctx["steward_headers"],
        ),
        "ERR_LINEAGE_CYCLE",
    )


def test_a_two_node_lineage_path_is_a_schema_violation_and_documents_nothing(api):
    """A source and a target with no transformation between them is not a flow.

    PRD §3.9: "The path must contain at least three node keys, since a source and a target with no transformation between them is not a documented flow; a shorter array is a schema violation."
    PRD §2.9: "Required fields present, enum members valid, numeric ranges respected, array shapes valid — a `measurements` array whose entries each carry `rule_code` and `measured_pct`, a `lineage_path` with at least three entries — and string minimum lengths met. Violation: `ERR_INVALID_REQUEST` (400). Applies to every endpoint that takes a request body."

    Design: Corner/errors/lineage_path_geometry_errors_are_distinguished
    """
    ctx, subscription = _consumer_awaiting_lineage()

    response = api.document_consumer_lineage(
        subscription["id"],
        {"lineage_path": ["ERP", "RPT_A"]},
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_INVALID_REQUEST")

    after = validate_success(
        api.get_consumer_subscription(subscription["id"], AUDITOR_HEADERS)
    )
    assert after["lineage_status"] == "UNDOCUMENTED", (
        "the refused path documented nothing, got "
        f"{after['lineage_status']}"
    )


# ---------------------------------------------------------------------------
# A hierarchy node re-parented under itself
# ---------------------------------------------------------------------------


def test_re_parenting_a_node_under_itself_is_refused(api):
    """A restructure naming one node as both parent and child is a cycle.

    PRD §3.8: "`HIERARCHY_RESTRUCTURE` re-parents a node and requires the keys `parent_node_key` and `child_node_key`; naming the same node key for both is a cycle and is rejected with `ERR_HIERARCHY_CYCLE`."

    Design: Corner/errors/hierarchy_restructure_naming_one_node_twice_is_refused
    """
    ctx = setup_draft_domain()

    response = api.create_change_request(
        change_request_payload(
            ctx["domain"]["id"],
            change_type="HIERARCHY_RESTRUCTURE",
            title="Re-parent EMEA sales under EMEA sales",
            proposed_values={
                "parent_node_key": "EMEA_SALES",
                "child_node_key": "EMEA_SALES",
            },
        ),
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_HIERARCHY_CYCLE")


def test_a_refused_hierarchy_restructure_raises_no_change_request(api):
    """The refused restructure left the domain's change calendar empty.

    PRD §3.8: "`HIERARCHY_RESTRUCTURE` re-parents a node and requires the keys `parent_node_key` and `child_node_key`; naming the same node key for both is a cycle and is rejected with `ERR_HIERARCHY_CYCLE`."
    PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count` and `has_more` alongside the `data` array, where `total_count` is the size of the full filtered result set and `has_more` states whether rows remain beyond the returned page."

    Design: Corner/errors/hierarchy_restructure_naming_one_node_twice_is_refused
    """
    ctx = setup_draft_domain()
    validate_error(
        api.create_change_request(
            change_request_payload(
                ctx["domain"]["id"],
                change_type="HIERARCHY_RESTRUCTURE",
                title="Re-parent EMEA sales under EMEA sales",
                proposed_values={
                    "parent_node_key": "EMEA_SALES",
                    "child_node_key": "EMEA_SALES",
                },
            ),
            ctx["steward_headers"],
        ),
        "ERR_HIERARCHY_CYCLE",
    )

    rows, meta = validate_paginated(
        api.list_change_requests(
            AUDITOR_HEADERS, params={"domain_id": ctx["domain"]["id"]}
        )
    )

    assert meta["total_count"] == 0, (
        f"a refused request is never raised, got {meta['total_count']}"
    )
    assert rows == [], f"the change request page must be empty, got {rows}"


# ---------------------------------------------------------------------------
# A degenerate source registration interval
# ---------------------------------------------------------------------------


def _domain_and_certified_source():
    set_clock()
    domain = create_domain()
    source_system = create_source_system(certify=True)
    return domain, source_system


def test_a_registration_ending_when_it_begins_is_refused(api):
    """An effective_to equal to effective_from is not a strictly ordered interval.

    PRD §2.9: "Steward-assignment intervals may not overlap for the same domain and accountability role unless the incoming assignment is explicitly superseding (`ERR_ASSIGNMENT_OVERLAP`, 409); a supplied `effective_to` must fall strictly after `effective_from` (`ERR_INVALID_INTERVAL`, 422); a freeze window must clear every other scheduled window on the domain by at least 72 hours (`ERR_FREEZE_WINDOW_CONFLICT`, 409); `scheduled_apply_at` must be at or after the computed `earliest_apply_at` (`ERR_LEAD_TIME_NOT_SATISFIED`, 409); and applying requires the logical clock to have reached `scheduled_apply_at` (`ERR_APPLY_WINDOW_NOT_REACHED`, 409). This step guards steward-assignment creation, source-registration creation, change-request scheduling and change-request application."

    Design: Corner/errors/source_registration_interval_must_be_strictly_ordered
    """
    domain, source_system = _domain_and_certified_source()

    response = api.create_source_registration(
        source_registration_payload(
            domain["id"],
            source_system["id"],
            domain_version(domain["id"]),
            role="CONTRIBUTING",
            trust_rank=2,
            effective_from=CLOCK,
            effective_to=CLOCK,
        ),
        GOVERNANCE_ADMIN_HEADERS,
    )

    validate_error(response, "ERR_INVALID_INTERVAL")


def test_a_refused_registration_neither_persists_nor_moves_the_domain_version(api):
    """A write that never happened leaves the concurrency anchor where it was.

    PRD §2.9: "Steward-assignment intervals may not overlap for the same domain and accountability role unless the incoming assignment is explicitly superseding (`ERR_ASSIGNMENT_OVERLAP`, 409); a supplied `effective_to` must fall strictly after `effective_from` (`ERR_INVALID_INTERVAL`, 422); a freeze window must clear every other scheduled window on the domain by at least 72 hours (`ERR_FREEZE_WINDOW_CONFLICT`, 409); `scheduled_apply_at` must be at or after the computed `earliest_apply_at` (`ERR_LEAD_TIME_NOT_SATISFIED`, 409); and applying requires the logical clock to have reached `scheduled_apply_at` (`ERR_APPLY_WINDOW_NOT_REACHED`, 409). This step guards steward-assignment creation, source-registration creation, change-request scheduling and change-request application."
    PRD §2.5: "A request that ends up mutating nothing on the domain leaves `version` untouched."

    Design: Corner/errors/source_registration_interval_must_be_strictly_ordered
    """
    domain, source_system = _domain_and_certified_source()
    version_before = domain_version(domain["id"])
    assert version_before == 1, (
        f"a freshly defined domain starts at version 1, got {version_before}"
    )

    validate_error(
        api.create_source_registration(
            source_registration_payload(
                domain["id"],
                source_system["id"],
                version_before,
                role="CONTRIBUTING",
                trust_rank=2,
                effective_from=CLOCK,
                effective_to=CLOCK,
            ),
            GOVERNANCE_ADMIN_HEADERS,
        ),
        "ERR_INVALID_INTERVAL",
    )

    _, meta = validate_paginated(
        api.list_source_registrations(
            AUDITOR_HEADERS, params={"domain_id": domain["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"the refused registration must not persist, got {meta['total_count']}"
    )
    assert domain_version(domain["id"]) == version_before, (
        "a refused registration mutates nothing on the domain, so its version must "
        f"still be {version_before}"
    )


# ---------------------------------------------------------------------------
# Closing a finding and retiring its rule
# ---------------------------------------------------------------------------


def _domain_with_one_open_finding():
    ctx = setup_draft_domain()
    run, finding = open_finding(ctx, "QR1", 45.00, basis="PROVISIONAL")
    return ctx, run, finding


def test_resolving_a_finding_below_the_rule_threshold_is_refused(api):
    """Evidence short of the rule's own pass threshold does not close the finding.

    PRD §3.5: "The caller supplies a `verified_measured_pct` and an optional `resolution_note`, and that percentage must be greater than or equal to the breached rule's `threshold_pct`; a shortfall is rejected with `ERR_RESOLUTION_BELOW_THRESHOLD`."

    Design: Corner/errors/finding_resolution_and_rule_retirement_gates
    """
    ctx, _, finding = _domain_with_one_open_finding()

    response = api.resolve_quality_finding(
        finding["id"], {"verified_measured_pct": 89.99}, ctx["steward_headers"]
    )

    validate_error(response, "ERR_RESOLUTION_BELOW_THRESHOLD")

    still_open = validate_success(
        api.get_quality_finding(finding["id"], AUDITOR_HEADERS)
    )
    assert still_open["status"] == "OPEN", (
        f"the finding stays open on refused evidence, got {still_open['status']}"
    )
    assert still_open["measured_pct"] == 45.00, (
        "the refused evidence was not written onto the finding, got "
        f"{still_open['measured_pct']}"
    )


def test_retiring_a_rule_that_still_carries_an_open_finding_is_refused(api):
    """A rule may not be retired out from under its own outstanding quality debt.

    PRD §3.3: "Retirement is the transition `ACTIVE → RETIRED` and it is guarded: a rule that still carries any finding in `OPEN` or `REMEDIATION_PLANNED` status cannot be retired, and the attempt is rejected with `ERR_RULE_HAS_OPEN_FINDINGS`."

    Design: Corner/errors/finding_resolution_and_rule_retirement_gates
    """
    ctx, _, _ = _domain_with_one_open_finding()
    rule = ctx["rules"]["QR1"]

    response = api.update_quality_rule(
        rule["id"], {"status": "RETIRED"}, ctx["steward_headers"]
    )

    validate_error(response, "ERR_RULE_HAS_OPEN_FINDINGS")

    still_active = validate_success(api.get_quality_rule(rule["id"], AUDITOR_HEADERS))
    assert still_active["status"] == "ACTIVE", (
        f"the refused retirement leaves the rule active, got {still_active['status']}"
    )


def test_resolving_exactly_at_the_threshold_clears_the_debt_and_frees_the_rule(api):
    """Evidence exactly at the threshold closes the finding and unblocks retirement.

    PRD §3.5: "The caller supplies a `verified_measured_pct` and an optional `resolution_note`, and that percentage must be greater than or equal to the breached rule's `threshold_pct`; a shortfall is rejected with `ERR_RESOLUTION_BELOW_THRESHOLD`."
    PRD §3.5: "From `OPEN → RESOLVED`, everything is identical — `status` `RESOLVED`, `resolved_at` stamped, `measured_pct` overwritten, `gap_pct` set to 0.00, `open_finding_weight` recomputed and posture recomputed — except that no steward's `open_finding_load` moves, because no assignment was ever charged."
    PRD §3.3: "Retirement is the transition `ACTIVE → RETIRED` and it is guarded: a rule that still carries any finding in `OPEN` or `REMEDIATION_PLANNED` status cannot be retired, and the attempt is rejected with `ERR_RULE_HAS_OPEN_FINDINGS`."
    PRD §2.8: "`Domain.open_finding_weight` is the two-decimal, half-up-rounded sum of `severity_weight` over the domain's findings whose `status` is `OPEN` or `REMEDIATION_PLANNED`."

    Design: Corner/errors/finding_resolution_and_rule_retirement_gates
    """
    ctx, _, finding = _domain_with_one_open_finding()
    rule = ctx["rules"]["QR1"]

    resolved = validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {
                "verified_measured_pct": 90.00,
                "resolution_note": "Completeness back-fill verified against ERP",
            },
            ctx["steward_headers"],
        )
    )

    assert resolved["status"] == "RESOLVED", (
        f"evidence at the threshold closes the finding, got {resolved['status']}"
    )
    assert resolved["measured_pct"] == 90.00, (
        f"the verified figure overwrites the observation, got {resolved['measured_pct']}"
    )
    assert resolved["gap_pct"] == 0.00, (
        f"a resolved finding carries no gap, got {resolved['gap_pct']}"
    )
    assert_instant_equals(resolved["resolved_at"], CLOCK, "resolved_at")

    retired = validate_success(
        api.update_quality_rule(
            rule["id"], {"status": "RETIRED"}, ctx["steward_headers"]
        )
    )
    assert retired["status"] == "RETIRED", (
        f"with no open finding left the rule may retire, got {retired['status']}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["open_finding_weight"] == 0.00, (
        "the resolved finding leaves the open set, so the domain carries no quality "
        f"debt, got {domain['open_finding_weight']}"
    )


def test_planning_remediation_on_a_closed_finding_is_refused(api):
    """A finding already resolved cannot be handed to anyone for remediation.

    PRD §3.5: "The finding must still be `OPEN`; attempting to plan a finding that is already `RESOLVED` or `WAIVED` is rejected with `ERR_FINDING_ALREADY_CLOSED`."

    Design: Corner/errors/finding_resolution_and_rule_retirement_gates
    """
    ctx, _, finding = _domain_with_one_open_finding()
    validate_success(
        api.resolve_quality_finding(
            finding["id"],
            {
                "verified_measured_pct": 90.00,
                "resolution_note": "Completeness back-fill verified against ERP",
            },
            ctx["steward_headers"],
        )
    )

    response = api.plan_finding_remediation(
        finding["id"],
        {
            "assigned_steward_id": ctx["steward"]["id"],
            "due_at": "2026-09-01T00:00:00Z",
            "plan_note": "Re-profile the completeness gap",
        },
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_FINDING_ALREADY_CLOSED")


# ---------------------------------------------------------------------------
# Curating and publishing a master record
# ---------------------------------------------------------------------------


def _active_domain_with_two_candidate_records():
    """An active domain holding one ERP candidate and one CRM candidate."""
    ctx = setup_governed_domain(
        sources=[CERTIFIED_AUTHORITATIVE_ERP, UNCERTIFIED_CRM]
    )
    from_erp = add_master_record(
        ctx,
        source_code="ERP",
        curate=False,
        natural_key="ERP-CUST-1001",
        attributes=COMPLETE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    from_crm = add_master_record(
        ctx,
        source_code="CRM",
        curate=False,
        natural_key="CRM-CUST-9001",
        attributes=NEAR_DUPLICATE_ATTRIBUTES,
        last_verified_at=CLOCK,
    )
    return ctx, from_erp, from_crm


def test_curating_a_record_from_an_uncertified_source_is_refused(api):
    """Only a certified system's claims may join the golden set.

    PRD §3.6: "`CANDIDATE → CURATED` requires only that the record's contributing source system is in `CERTIFIED` status — curating a record from a `REGISTERED` or `DECERTIFIED` system is rejected with `ERR_SOURCE_NOT_CERTIFIED` — and it accepts an optional `last_verified_at`, which is stored when supplied."

    Design: Corner/errors/master_record_curation_and_publication_gates
    """
    ctx, _, from_crm = _active_domain_with_two_candidate_records()
    assert ctx["sources"]["CRM"]["status"] == "REGISTERED", (
        f"the CRM system has not been certified, got {ctx['sources']['CRM']['status']}"
    )

    response = api.curate_master_record(from_crm["id"], ctx["steward_headers"])

    validate_error(response, "ERR_SOURCE_NOT_CERTIFIED")

    untouched = validate_success(
        api.get_master_record(from_crm["id"], AUDITOR_HEADERS)
    )
    assert untouched["curation_status"] == "CANDIDATE", (
        f"the refused endorsement leaves it a candidate, got "
        f"{untouched['curation_status']}"
    )


def test_publishing_an_uncurated_record_is_refused(api):
    """Nothing is released downstream before a steward has endorsed it.

    PRD §3.6: "The record's `curation_status` must be `CURATED`, otherwise `ERR_RECORD_NOT_CURATED`."

    Design: Corner/errors/master_record_curation_and_publication_gates
    """
    ctx, from_erp, _ = _active_domain_with_two_candidate_records()

    response = api.publish_master_record(from_erp["id"], ctx["steward_headers"])

    validate_error(response, "ERR_RECORD_NOT_CURATED")

    domain = read_domain(ctx["domain"]["id"])
    assert domain["published_master_record_count"] == 0, (
        "a refused publication moves no counter, got "
        f"{domain['published_master_record_count']}"
    )


def test_publishing_an_already_published_record_a_second_time_is_refused(api):
    """A record released downstream once is not released again.

    PRD §3.6: "A record already in `publication_status` `PUBLISHED` cannot be published again and the attempt is rejected with `ERR_RECORD_ALREADY_PUBLISHED`."
    PRD §3.6: "On success `publication_status` becomes `PUBLISHED`, `published_at` is stamped from the logical clock, the domain's `published_master_record_count` is incremented by one, and the domain's `version` advances by one."

    Design: Corner/errors/master_record_curation_and_publication_gates
    """
    ctx, from_erp, _ = _active_domain_with_two_candidate_records()
    curated = validate_success(
        api.curate_master_record(from_erp["id"], ctx["steward_headers"])
    )
    assert curated["curation_status"] == "CURATED", (
        f"the certified source's claim is endorsed, got {curated['curation_status']}"
    )
    published = validate_success(
        api.publish_master_record(from_erp["id"], ctx["steward_headers"])
    )
    assert published["publication_status"] == "PUBLISHED", (
        f"the endorsed record is released, got {published['publication_status']}"
    )

    response = api.publish_master_record(from_erp["id"], ctx["steward_headers"])

    validate_error(response, "ERR_RECORD_ALREADY_PUBLISHED")

    domain = read_domain(ctx["domain"]["id"])
    assert domain["published_master_record_count"] == 1, (
        "the refused second publication does not double-count the record, got "
        f"{domain['published_master_record_count']}"
    )


# ---------------------------------------------------------------------------
# The domain lifecycle gates
# ---------------------------------------------------------------------------


def test_submitting_a_change_request_on_a_draft_domain_is_refused(api):
    """Change control only opens once the domain is actually governing data.

    PRD §3.8: "Both paths require the owning domain's `status` to be `ACTIVE`, otherwise `ERR_DOMAIN_NOT_ACTIVE`, and both require the acting `X-User-ID` to equal the request's `requester_steward_id`: only the originator resubmits their own request."

    Design: Corner/errors/domain_lifecycle_state_gates
    """
    ctx = setup_draft_domain()
    request = add_change_request(ctx, stage="DRAFT")
    assert ctx["domain"]["status"] == "DRAFT", (
        f"the domain has not been activated yet, got {ctx['domain']['status']}"
    )

    response = api.submit_change_request(request["id"], ctx["steward_headers"])

    validate_error(response, "ERR_DOMAIN_NOT_ACTIVE")

    still_draft = validate_success(
        api.get_change_request(request["id"], AUDITOR_HEADERS)
    )
    assert still_draft["status"] == "DRAFT", (
        f"the refused submission leaves the request in draft, got "
        f"{still_draft['status']}"
    )


def test_activating_a_domain_that_is_already_active_is_refused(api):
    """Activation is a one-way door out of DRAFT.

    PRD §3.1: "The domain must still be in `DRAFT` — attempting activation on a domain that is already `ACTIVE` is `ERR_DOMAIN_NOT_DRAFT`."
    PRD §3.1: "When all four hold, the `DRAFT → ACTIVE` transition sets `status` to `ACTIVE`, stamps `activated_at` from the logical clock, recomputes `governance_posture`, and advances the domain's `version` by one."

    Design: Corner/errors/domain_lifecycle_state_gates
    """
    ctx = setup_draft_domain()

    activated = validate_success(
        api.activate_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert activated["status"] == "ACTIVE", (
        f"a ready domain activates, got {activated['status']}"
    )
    assert_instant_equals(activated["activated_at"], CLOCK, "activated_at")

    response = api.activate_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, "ERR_DOMAIN_NOT_DRAFT")


def test_change_request_submission_reports_no_impact_without_consumers(api):
    """Once the domain is active a submission succeeds and finds nobody impacted.

    PRD §3.8: "Both paths require the owning domain's `status` to be `ACTIVE`, otherwise `ERR_DOMAIN_NOT_ACTIVE`, and both require the acting `X-User-ID` to equal the request's `requester_steward_id`: only the originator resubmits their own request."
    PRD §3.8: "First the impacted consumer set is determined: it is every `ConsumerSubscription` of the request's domain whose `status` is `ACTIVE` and which is either impacted by virtue of the change being structural, or — for a non-structural change — carries a `criticality` of `TIER1`."
    PRD §3.8: "Second, a base lead time is taken as the largest `required_lead_days` among the impacted consumers, or zero when the impacted set is empty. Third, a floor lead time is taken as the domain's `notification_lead_days_floor` when at least one consumer is impacted, and zero when none is."

    Design: Corner/errors/domain_lifecycle_state_gates
    """
    ctx = setup_draft_domain()
    request = add_change_request(ctx, stage="DRAFT")
    validate_success(api.activate_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS))

    submitted = validate_success(
        api.submit_change_request(request["id"], ctx["steward_headers"])
    )

    assert submitted["status"] == "SUBMITTED", (
        f"submission is now open, got {submitted['status']}"
    )
    assert submitted["impact_consumer_count"] == 0, (
        "the domain has no consumers, so nobody is impacted, got "
        f"{submitted['impact_consumer_count']}"
    )
    assert submitted["required_lead_days"] == 0, (
        "with an empty impacted set both the base lead and the floor lead are zero, "
        f"got {submitted['required_lead_days']}"
    )


# ---------------------------------------------------------------------------
# Activation readiness
# ---------------------------------------------------------------------------


def _domain_ready_but_for_the_data_steward():
    """A DRAFT domain with an owner, a certified authoritative source and a rule."""
    setup = setup_domain_awaiting_data_steward()
    domain = setup["domain"]
    source_system = create_source_system(certify=True)
    register_source(
        domain["id"], source_system["id"], role="AUTHORITATIVE", trust_rank=1
    )
    rule = create_quality_rule(
        domain["id"],
        setup["owner"]["id"],
        setup["owner_headers"],
        severity="CRITICAL",
    )
    return setup, rule


def test_activation_without_a_data_steward_is_refused(api):
    """An owner alone is not stewardship; the domain needs both accountability seats.

    PRD §3.1: "The domain must have both an `ACTIVE` `DATA_OWNER` assignment and an `ACTIVE` `DATA_STEWARD` assignment whose intervals cover the clock; a domain with an owner but no steward, or a steward but no owner, is rejected with `ERR_STEWARDSHIP_INCOMPLETE`."
    PRD §3.3: "Only a `PRINCIPAL`-certified steward may own a `CRITICAL`-severity rule: naming an owner whose `certification_level` is `JUNIOR` or `SENIOR` on a `CRITICAL` rule is rejected with `ERR_OWNER_NOT_PRINCIPAL`."

    Design: Corner/errors/activation_requires_both_accountability_roles
    """
    setup, rule = _domain_ready_but_for_the_data_steward()
    assert rule["status"] == "ACTIVE", (
        "the principal owner may hold a critical rule and it opens active, got "
        f"{rule['status']}"
    )
    assert read_domain(setup["domain"]["id"])["authoritative_source_code"] == "ERP", (
        "the domain holds a certified authoritative source"
    )

    response = api.activate_domain(setup["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, "ERR_STEWARDSHIP_INCOMPLETE")


def test_a_refused_activation_leaves_the_domain_in_draft(api):
    """The domain is unchanged by an activation it was not ready for.

    PRD §3.1: "The domain must have both an `ACTIVE` `DATA_OWNER` assignment and an `ACTIVE` `DATA_STEWARD` assignment whose intervals cover the clock; a domain with an owner but no steward, or a steward but no owner, is rejected with `ERR_STEWARDSHIP_INCOMPLETE`."
    PRD §3.1: "A newly defined domain lands in `status` `DRAFT` with `activated_at` still null, and — because it has not yet been given an authoritative source — its derived `governance_posture` is already `FROZEN`."

    Design: Corner/errors/activation_requires_both_accountability_roles
    """
    setup, _ = _domain_ready_but_for_the_data_steward()
    validate_error(
        api.activate_domain(setup["domain"]["id"], GOVERNANCE_ADMIN_HEADERS),
        "ERR_STEWARDSHIP_INCOMPLETE",
    )

    domain = read_domain(setup["domain"]["id"])

    assert domain["status"] == "DRAFT", (
        f"a refused activation leaves the domain in draft, got {domain['status']}"
    )
    assert domain["activated_at"] is None, (
        f"a refused activation stamps nothing, got {domain['activated_at']!r}"
    )


# ---------------------------------------------------------------------------
# The certified authoritative source requirement
# ---------------------------------------------------------------------------


def test_activation_without_a_certified_authoritative_source_is_refused(api):
    """A domain with no authoritative source has nothing to govern data against.

    PRD §3.1: "And the domain must hold an `ACTIVE` `AUTHORITATIVE` source registration whose underlying source system is in `CERTIFIED` status, otherwise `ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE`."

    Design: Corner/errors/certified_basis_requires_a_certified_authoritative_source
    """
    ctx = setup_draft_domain(sources=[])
    assert ctx["domain"]["authoritative_source_code"] is None, (
        "no source has been registered against the domain, got "
        f"{ctx['domain']['authoritative_source_code']!r}"
    )

    response = api.activate_domain(ctx["domain"]["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, "ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE")


def test_a_certified_basis_scorecard_run_needs_a_certified_authoritative_source(api):
    """The certified basis is the auditable one and demands a certified source.

    PRD §3.4: "A `CERTIFIED` run additionally requires the domain to hold an `ACTIVE` `AUTHORITATIVE` registration whose source system is in `CERTIFIED` status, and is otherwise rejected with `ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE`."

    Design: Corner/errors/certified_basis_requires_a_certified_authoritative_source
    """
    ctx = setup_draft_domain(sources=[])

    response = api.create_scorecard_run(
        ctx["domain"]["id"],
        {
            "basis": "CERTIFIED",
            "measurements": [{"rule_code": "QR1", "measured_pct": 95.00}],
        },
        ctx["steward_headers"],
    )

    validate_error(response, "ERR_NO_CERTIFIED_AUTHORITATIVE_SOURCE")

    domain = read_domain(ctx["domain"]["id"])
    assert domain["scorecard_run_seq"] == 0, (
        f"the refused run recorded no epoch, got {domain['scorecard_run_seq']}"
    )
    assert domain["quality_score_certified"] is None, (
        "the refused run stored no certified score, got "
        f"{domain['quality_score_certified']!r}"
    )


def test_a_provisional_scorecard_run_is_allowed_without_any_certified_source(api):
    """The provisional basis is always available, even to an ungoverned domain.

    PRD §3.4: "A `PROVISIONAL` run is always permitted, including while the domain holds no certified authoritative source at all."
    PRD §3.4: "The run's `weighted_score` is one hundred times the earned total divided by that denominator, rounded half up to two decimal places — a second and final rounding."
    PRD §3.4: "The multiplier is derived from the posture as it stood at the instant the run started, which the run records as `posture_before`; it is computed once and recorded as `posture_multiplier_applied`, and the *same* multiplier is applied to every finding the run creates."
    PRD §3.1: "A newly defined domain lands in `status` `DRAFT` with `activated_at` still null, and — because it has not yet been given an authoritative source — its derived `governance_posture` is already `FROZEN`."

    Design: Corner/errors/certified_basis_requires_a_certified_authoritative_source
    """
    ctx = setup_draft_domain(sources=[])

    run = validate_success(
        api.create_scorecard_run(
            ctx["domain"]["id"],
            {
                "basis": "PROVISIONAL",
                "measurements": [{"rule_code": "QR1", "measured_pct": 95.00}],
            },
            ctx["steward_headers"],
        ),
        201,
    )

    assert run["basis"] == "PROVISIONAL", (
        f"the run records the requested basis, got {run['basis']}"
    )
    assert run["weighted_score"] == 100.00, (
        "95.00 clears the 90.00 threshold, so the rule earns its whole forty points "
        f"out of a forty-point denominator, got {run['weighted_score']}"
    )
    assert run["rules_failed_count"] == 0, (
        f"the measured rule passed, got {run['rules_failed_count']}"
    )
    assert run["posture_before"] == "FROZEN", (
        "the domain has never held an authoritative source, so it was frozen when "
        f"the run started, got {run['posture_before']}"
    )
    assert run["posture_after"] == "FROZEN", (
        "a passing run opens no finding and the domain still has no authoritative "
        f"source, so it stays frozen, got {run['posture_after']}"
    )


# ---------------------------------------------------------------------------
# The five gates on applying a scheduled change
# ---------------------------------------------------------------------------

HIERARCHY_CHANGE = {
    "change_type": "HIERARCHY_RESTRUCTURE",
    "title": "Move EMEA sales under the global hierarchy",
    "proposed_values": {"parent_node_key": "GLOBAL", "child_node_key": "EMEA_SALES"},
}
LINEAGE_PATH = ["ERP", "STG_CUSTOMER", "RPT_A"]
SCHEDULED_APPLY_AT = "2026-08-12T00:00:00Z"


def _structural_change_with_one_tier1_consumer(stage, document_lineage=True,
                                               scheduled_apply_at=None):
    """An active domain, one TIER1 consumer and one hierarchy restructure."""
    ctx = setup_governed_domain()
    subscription = add_consumer_subscription(
        ctx,
        consumer_code="BI_A",
        reporting_asset_key="RPT_A",
        clearance_level="INTERNAL",
        criticality="TIER1",
        required_lead_days=5,
    )
    if document_lineage:
        subscription = document_lineage_for(ctx, subscription, LINEAGE_PATH)
    request = add_change_request(
        ctx,
        stage=stage,
        scheduled_apply_at=scheduled_apply_at,
        review_note="Hierarchy realignment approved by the reference data board",
        **HIERARCHY_CHANGE,
    )
    return ctx, subscription, request


def test_applying_a_change_that_was_never_scheduled_is_refused(api):
    """Application reaches only into the change calendar, never into a draft.

    PRD §3.8: "The request must be in `SCHEDULED` status, otherwise `ERR_CHANGE_REQUEST_NOT_SCHEDULED`."

    Design: Corner/errors/change_request_apply_gate_errors
    """
    ctx, _, request = _structural_change_with_one_tier1_consumer("DRAFT")
    assert request["status"] == "DRAFT", (
        f"the request has not been through review, got {request['status']}"
    )

    response = api.apply_change_request(request["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, "ERR_CHANGE_REQUEST_NOT_SCHEDULED")

    domain = read_domain(ctx["domain"]["id"])
    assert domain["reference_data_revision"] == 0, (
        "nothing was applied, so the reference data revision holds at 0, got "
        f"{domain['reference_data_revision']}"
    )


def test_approving_a_structural_change_needs_every_tier1_lineage_documented(api):
    """A structural change cannot be approved over an undocumented critical consumer.

    PRD §3.8: "`APPROVE` drives `UNDER_REVIEW → APPROVED`, stores the `review_note`, retains `reviewer_steward_id`, and retains the impact assessment as computed; for a structural change it carries one extra precondition — every `ACTIVE` `TIER1` consumer of the domain must already have `lineage_status` `DOCUMENTED`, and if any does not, the approval is refused with `ERR_LINEAGE_INCOMPLETE`."
    PRD §3.8: "Second, a base lead time is taken as the largest `required_lead_days` among the impacted consumers, or zero when the impacted set is empty. Third, a floor lead time is taken as the domain's `notification_lead_days_floor` when at least one consumer is impacted, and zero when none is."
    PRD §3.8: "Finally, `earliest_apply_at` is set to `submitted_at` advanced by `required_lead_days` whole days."

    Design: Corner/errors/change_request_apply_gate_errors
    """
    ctx, subscription, request = _structural_change_with_one_tier1_consumer(
        "UNDER_REVIEW", document_lineage=False
    )
    assert request["impact_consumer_count"] == 1, (
        "a structural change impacts every active consumer, and there is one, got "
        f"{request['impact_consumer_count']}"
    )
    assert request["required_lead_days"] == 5, (
        "the consumer wants five days and the domain's floor is five, so the notice "
        f"is five days, got {request['required_lead_days']}"
    )
    assert_instant_equals(
        request["earliest_apply_at"], "2026-08-10T00:00:00Z", "earliest_apply_at"
    )

    refused = api.decide_change_request(
        request["id"],
        {
            "decision": "APPROVE",
            "review_note": "Hierarchy realignment approved by the reference data board",
        },
        ctx["owner_headers"],
    )
    validate_error(refused, "ERR_LINEAGE_INCOMPLETE")

    documented = document_lineage_for(ctx, subscription, LINEAGE_PATH)
    assert documented["lineage_status"] == "DOCUMENTED", (
        f"the consumer's flow is now on record, got {documented['lineage_status']}"
    )
    assert documented["lineage_revision"] == 0, (
        "the documentation is dated at the domain's current reference data "
        f"revision, got {documented['lineage_revision']}"
    )

    approved = validate_success(
        api.decide_change_request(
            request["id"],
            {
                "decision": "APPROVE",
                "review_note": (
                    "Hierarchy realignment approved by the reference data board"
                ),
            },
            ctx["owner_headers"],
        )
    )
    assert approved["status"] == "APPROVED", (
        f"with the lineage on record the approval lands, got {approved['status']}"
    )


def test_scheduling_inside_the_notification_lead_time_is_refused(api):
    """A change may not land before its consumers have had their notice.

    PRD §3.8: "The data owner supplies `scheduled_apply_at`, which must be at or after the computed `earliest_apply_at`; an earlier instant is rejected with `ERR_LEAD_TIME_NOT_SATISFIED`."
    PRD §3.8: "The freeze window is a closed interval around that instant whose extent depends on whether the change is structural: a structural change reserves 24 hours of lead before the instant and 48 hours of trail after it, while a non-structural change reserves no lead at all and 12 hours of trail. Those become `freeze_window_start` and `freeze_window_end`."

    Design: Corner/errors/change_request_apply_gate_errors
    """
    ctx, _, request = _structural_change_with_one_tier1_consumer("APPROVED")
    assert_instant_equals(
        request["earliest_apply_at"], "2026-08-10T00:00:00Z", "earliest_apply_at"
    )

    response = api.schedule_change_request(
        request["id"],
        {"scheduled_apply_at": "2026-08-09T00:00:00Z"},
        ctx["owner_headers"],
    )
    validate_error(response, "ERR_LEAD_TIME_NOT_SATISFIED")

    scheduled = validate_success(
        api.schedule_change_request(
            request["id"],
            {"scheduled_apply_at": SCHEDULED_APPLY_AT},
            ctx["owner_headers"],
        )
    )
    assert scheduled["status"] == "SCHEDULED", (
        f"an instant at or after the earliest is accepted, got {scheduled['status']}"
    )
    assert_instant_equals(
        scheduled["freeze_window_start"],
        "2026-08-11T00:00:00Z",
        "freeze_window_start",
    )
    assert_instant_equals(
        scheduled["freeze_window_end"], "2026-08-14T00:00:00Z", "freeze_window_end"
    )


def test_applying_before_the_scheduled_instant_is_refused(api):
    """The governance office cannot bring a scheduled change forward.

    PRD §3.8: "The logical clock must have reached `scheduled_apply_at`, with equality acceptable; an earlier clock yields `ERR_APPLY_WINDOW_NOT_REACHED`."
    PRD §3.8: "On success the `status` becomes `SCHEDULED`, `scheduled_apply_at` and the two window boundaries are stored, the domain's `scheduled_change_count` is incremented by one and its `version` advances by one, and the notification fan-out runs: every consumer subscription in the impacted set — determined by exactly the same filter the impact assessment used — has its `pending_change_request_id` set to this request, its `notified_at` stamped from the clock, and its `acknowledged_at` and `acknowledged_revision` cleared to null so that a stale acknowledgement from an earlier notification cannot be mistaken for a fresh one."

    Design: Corner/errors/change_request_apply_gate_errors
    """
    ctx, subscription, request = _structural_change_with_one_tier1_consumer(
        "SCHEDULED", scheduled_apply_at=SCHEDULED_APPLY_AT
    )
    notified = validate_success(
        api.get_consumer_subscription(subscription["id"], AUDITOR_HEADERS)
    )
    assert notified["pending_change_request_id"] == request["id"], (
        "scheduling notifies the impacted consumer, got "
        f"{notified['pending_change_request_id']!r}"
    )
    assert_instant_equals(notified["notified_at"], CLOCK, "notified_at")
    assert notified["acknowledged_at"] is None, (
        f"the consumer has not signed off yet, got {notified['acknowledged_at']!r}"
    )

    response = api.apply_change_request(request["id"], GOVERNANCE_ADMIN_HEADERS)

    validate_error(response, "ERR_APPLY_WINDOW_NOT_REACHED")


def test_applying_needs_every_tier1_consumer_to_have_acknowledged(api):
    """A critical consumer that has not signed off blocks the change from landing.

    PRD §3.8: "And every consumer subscription whose `pending_change_request_id` points at this request and whose `criticality` is `TIER1` must have a non-null `acknowledged_at`; an unacknowledged critical consumer blocks the change with `ERR_TIER1_ACK_MISSING`."
    PRD §3.8: "**Hop 1** sets `status` to `APPLIED`, stamps `applied_at` from the clock, increments the domain's `reference_data_revision` by one, decrements the domain's `scheduled_change_count` by one, releases the freeze window by setting both `freeze_window_start` and `freeze_window_end` to null, and advances the domain's `version` by one; when the `change_type` is `CLASSIFICATION_UPLIFT` it additionally writes the payload's `target_classification_level` into the domain's `classification_level` and recomputes `sensitive_handling_required` from the new level."
    PRD §3.8: "Two further effects complete the apply: every consumer subscription of the domain whose `lineage_status` is `DOCUMENTED` and whose `lineage_revision` is lower than the domain's new `reference_data_revision` is moved to `lineage_status` `STALE`, and every subscription still `ACTIVE` that was notified about this request has its `pending_change_request_id`, `notified_at` and `acknowledged_at` cleared to null now that the change has landed."
    PRD §3.9: "On success `acknowledged_at` is stamped from the logical clock and `acknowledged_revision` captures the domain's `reference_data_revision` at acknowledgement time, giving an auditable record of exactly which revision of the reference data the consumer signed off against."

    Design: Corner/errors/change_request_apply_gate_errors
    """
    ctx, subscription, request = _structural_change_with_one_tier1_consumer(
        "SCHEDULED", scheduled_apply_at=SCHEDULED_APPLY_AT
    )
    set_clock(SCHEDULED_APPLY_AT)

    validate_error(
        api.apply_change_request(request["id"], GOVERNANCE_ADMIN_HEADERS),
        "ERR_TIER1_ACK_MISSING",
    )

    acknowledged = validate_success(
        api.acknowledge_consumer_subscription(
            subscription["id"], make_consumer_rep_headers(subscription["id"])
        )
    )
    assert_instant_equals(
        acknowledged["acknowledged_at"], SCHEDULED_APPLY_AT, "acknowledged_at"
    )
    assert acknowledged["acknowledged_revision"] == 0, (
        "the consumer signs off against the revision standing at that moment, got "
        f"{acknowledged['acknowledged_revision']}"
    )

    applied = validate_success(
        api.apply_change_request(request["id"], GOVERNANCE_ADMIN_HEADERS)
    )
    assert applied["status"] == "APPLIED", (
        f"with the sign-off in hand the change lands, got {applied['status']}"
    )
    assert_instant_equals(applied["applied_at"], SCHEDULED_APPLY_AT, "applied_at")
    assert applied["freeze_window_start"] is None, (
        f"applying releases the window, got {applied['freeze_window_start']!r}"
    )
    assert applied["freeze_window_end"] is None, (
        f"applying releases the window, got {applied['freeze_window_end']!r}"
    )

    domain = read_domain(ctx["domain"]["id"])
    assert domain["reference_data_revision"] == 1, (
        f"the applied change advances the revision to 1, got "
        f"{domain['reference_data_revision']}"
    )
    assert domain["scheduled_change_count"] == 0, (
        f"the calendar slot is released, got {domain['scheduled_change_count']}"
    )

    consumer = validate_success(
        api.get_consumer_subscription(subscription["id"], AUDITOR_HEADERS)
    )
    assert consumer["lineage_status"] == "STALE", (
        "the documentation was dated at revision 0 and the domain has moved to 1, "
        f"so the flow is stale, got {consumer['lineage_status']}"
    )
    assert consumer["pending_change_request_id"] is None, (
        "the notification is cleared now the change has landed, got "
        f"{consumer['pending_change_request_id']!r}"
    )

    rows, meta = validate_paginated(
        api.list_consumer_subscriptions(
            AUDITOR_HEADERS,
            params={"domain_id": ctx["domain"]["id"], "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1, (
        "the consumer's clearance still covers the domain's classification, so it "
        f"stays active, got {meta['total_count']}"
    )
    assert rows[0]["id"] == subscription["id"], (
        f"the surviving active consumer is the one registered, got {rows[0]['id']}"
    )
