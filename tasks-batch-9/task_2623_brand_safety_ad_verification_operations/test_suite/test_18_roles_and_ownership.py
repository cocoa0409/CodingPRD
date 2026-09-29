"""Roles, ownership scope and segregation of duties.

Three distinct refusals live in this file and the PRD gives each its own
identifier: a caller holding the wrong role for an endpoint is refused with
ERR_UNAUTHORIZED_ROLE, an entity-backed caller reaching outside its own
aggregate is refused with ERR_NOT_RESOURCE_OWNER, and an adjudicator who
already touched the record under adjudication is refused with
ERR_SEGREGATION_OF_DUTIES.
"""
import pytest

from test_helpers import (
    ANALYST_REVIEWER_USER_ID,
    AUDITOR_AUTHOR_USER_ID,
    AUDITOR_CONCLUDER_USER_ID,
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    advance_clock,
    factories,
    make_advertiser_headers,
    make_auditor_headers,
    make_publisher_headers,
    read_page,
    setup_advertiser,
    setup_methodology_version,
    setup_page,
    setup_published_list,
    setup_publisher,
    setup_reviewed_classification,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-10T00:00:00Z"


def test_seven_roles_are_each_locked_out_of_the_others_exclusive_operations(api):
    """Eight trespasses across the seven roles all answer the role refusal, and none of them leaks whether the named record exists.

    PRD: "Once authenticated, a caller whose role is not listed for the target
    endpoint in §4 is refused with `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

    Design: Corner/rbac/every_role_is_locked_out_of_the_other_roles_exclusive_operations
    """
    advance_clock(api, CLOCK)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/news")
    seed_page_version = page["version"]
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)

    trespasses = [
        (
            "Advertiser driving the PlatformAdmin-only logical clock",
            api.set_clock(
                factories.set_clock_payload("2026-09-01T00:00:00Z"),
                TEST_USERS["advertiser_headers"],
            ),
        ),
        (
            "Publisher creating an Advertiser-only inventory list",
            api.create_inventory_list(
                {
                    "advertiser_id": NON_EXISTENT_UUID,
                    "list_type": "INCLUSION",
                    "name": "Not mine to make",
                },
                TEST_USERS["publisher_headers"],
            ),
        ),
        (
            "Publisher writing a ClassificationAnalyst-only classification",
            api.create_page_classification(
                factories.create_page_classification_payload(
                    page["id"], NON_EXISTENT_UUID, seed_page_version
                ),
                TEST_USERS["publisher_headers"],
            ),
        ),
        (
            "ClassificationAnalyst deciding a DisputeOfficer-only appeal",
            api.decide_appeal(
                NON_EXISTENT_UUID,
                factories.decide_appeal_payload(outcome="UPHELD"),
                TEST_USERS["analyst_headers"],
            ),
        ),
        (
            "DisputeOfficer scoring a MeasurementOperator-only batch",
            api.score_measurement_batch(
                NON_EXISTENT_UUID, TEST_USERS["officer_headers"]
            ),
        ),
        (
            "MeasurementOperator approving a DisputeOfficer-only refund claim",
            api.approve_refund_claim(
                NON_EXISTENT_UUID,
                TEST_USERS["operator_headers"],
                {"decision_note": "Not my channel either"},
            ),
        ),
        (
            "MeasurementOperator authoring an AccreditationAuditor-only methodology version",
            api.create_methodology_version(
                factories.create_methodology_version_payload(
                    standard_family="SUITABILITY"
                ),
                TEST_USERS["operator_headers"],
            ),
        ),
        (
            "AccreditationAuditor registering a PlatformAdmin-only publisher",
            api.create_publisher(
                factories.create_publisher_payload(),
                TEST_USERS["auditor_headers"],
            ),
        ),
    ]

    for label, response in trespasses:
        error = validate_error(response, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)
        assert response.status_code == 403, (
            f"expected HTTP 403 for the trespass '{label}', "
            f"got {response.status_code}"
        )
        assert error["error_id"] == ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, (
            f"expected ERR_UNAUTHORIZED_ROLE for the trespass '{label}', "
            f"got {error['error_id']} - the role check must precede path and "
            "body reference existence"
        )

    # The refused classification write consumed nothing: the page is untouched.
    seeded = read_page(api, page["id"])
    assert seeded["classification_state"] == "UNCLASSIFIED", (
        "expected UNCLASSIFIED, got "
        f"{seeded['classification_state']} after the refused classification write"
    )
    assert seeded["version"] == seed_page_version, (
        f"expected page version {seed_page_version}, got {seeded['version']} "
        "after the refused classification write"
    )

    # The refused clock move had no effect either: publication still stamps
    # published_at from the logical clock as it stood at 2026-08-10.
    published = setup_published_list(
        api, advertiser, list_type="EXCLUSION",
        entries=[("DOMAIN", "other.example.com")],
    )
    assert published["list"]["published_at"].startswith("2026-08-10T00:00:00"), (
        "expected published_at stamped from the unchanged logical clock "
        f"2026-08-10T00:00:00Z, got {published['list']['published_at']}"
    )

    # Same operation, right role: the refusals were about the role, not the payload.
    allowed = api.create_publisher(
        factories.create_publisher_payload(
            name="Lantern Media",
            primary_domain="lantern.example.com",
            sourced_traffic_pct=0.10,
        ),
        TEST_USERS["admin_headers"],
    )
    created = validate_success(allowed, expected_status=201)
    assert created["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE, got {created['publisher_status']} for a newly "
        "registered publisher"
    )


def test_advertiser_reading_a_peer_advertisers_campaign_is_not_resource_owner(api):
    """One advertiser reads a rival advertiser's campaign and is refused as a non-owner rather than told the campaign does not exist.

    PRD: "When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id` of the
    acting advertiser; ownership checks on any resource that resolves to an
    advertiser compare that advertiser identifier to `X-User-ID` — a campaign's
    `advertiser_id`, an inventory list's `advertiser_id`, a pre-bid segment's
    campaign's `advertiser_id`, and a refund claim's campaign's
    `advertiser_id`."

    Design: Corner/rbac/advertiser_scope_is_its_own_aggregate_only
    """
    advance_clock(api, CLOCK)
    owner = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    rival = setup_advertiser(api, name="Rival Brands", credit_cap_cents=1000000)
    created = api.create_campaign(
        factories.create_campaign_payload(
            owner["id"],
            name="Q3 Display",
            cpm_cents=875,
            min_suitability_tier="MEDIUM_RISK",
            format="DISPLAY",
            target_coverage_rate=0.75,
        ),
        make_advertiser_headers(owner["id"]),
    )
    campaign = validate_success(created, expected_status=201)

    refused = api.get_campaign(campaign["id"], make_advertiser_headers(rival["id"]))
    error = validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert refused.status_code == 403, (
        f"expected HTTP 403 for a peer advertiser's read, got {refused.status_code}"
    )
    assert error["error_id"] == ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, (
        "expected ERR_NOT_RESOURCE_OWNER because the campaign exists and the "
        f"caller is simply not its owner, got {error['error_id']}"
    )

    # The owner still reads its own campaign.
    own = api.get_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
    own_data = validate_success(own, expected_status=200)
    assert own_data["advertiser_id"] == owner["id"], (
        f"expected advertiser_id {owner['id']}, got {own_data['advertiser_id']}"
    )


def test_platform_admin_reads_a_campaign_without_any_ownership_restriction(api):
    """The campaign a rival advertiser could not read is read unrestricted by the platform's own operator.

    PRD: "A `PlatformAdmin` caller reads every collection without any ownership
    restriction."

    Design: Corner/rbac/advertiser_scope_is_its_own_aggregate_only
    """
    advance_clock(api, CLOCK)
    owner = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    created = api.create_campaign(
        factories.create_campaign_payload(
            owner["id"],
            name="Q3 Display",
            cpm_cents=875,
            min_suitability_tier="MEDIUM_RISK",
            format="DISPLAY",
            target_coverage_rate=0.75,
        ),
        make_advertiser_headers(owner["id"]),
    )
    campaign = validate_success(created, expected_status=201)

    admin_read = api.get_campaign(campaign["id"], TEST_USERS["admin_headers"])
    data = validate_success(admin_read, expected_status=200)
    assert data["id"] == campaign["id"], (
        f"expected campaign {campaign['id']}, got {data['id']} from the "
        "PlatformAdmin read"
    )
    assert data["advertiser_id"] == owner["id"], (
        f"expected advertiser_id {owner['id']}, got {data['advertiser_id']}"
    )


def test_advertiser_cannot_create_an_inventory_list_under_a_peers_advertiser_id(api):
    """An advertiser plants a blocklist under a rival's identifier, is refused as a non-owner, and nothing is written.

    PRD: "A mismatch is refused with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/advertiser_scope_is_its_own_aggregate_only
    """
    advance_clock(api, CLOCK)
    owner = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    rival = setup_advertiser(api, name="Rival Brands", credit_cap_cents=1000000)

    refused = api.create_inventory_list(
        factories.create_inventory_list_payload(
            owner["id"], list_type="EXCLUSION", name="Planted Blocklist"
        ),
        make_advertiser_headers(rival["id"]),
    )
    error = validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert refused.status_code == 403, (
        f"expected HTTP 403 for a list planted under a peer's advertiser_id, "
        f"got {refused.status_code}"
    )
    assert error["error_id"] == ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, (
        f"expected ERR_NOT_RESOURCE_OWNER, got {error['error_id']}"
    )

    listed = api.list_inventory_lists(
        TEST_USERS["admin_headers"], params={"advertiser_id": owner["id"]}
    )
    lists, meta = validate_paginated(listed)
    assert meta["total_count"] == 0, (
        f"expected 0 lists under the owning advertiser, got {meta['total_count']}"
    )
    assert lists == [], f"expected no list to have been written, got {lists}"

    # The same shape of write under the caller's own advertiser_id succeeds.
    allowed = api.create_inventory_list(
        factories.create_inventory_list_payload(
            rival["id"], list_type="EXCLUSION", name="Own Blocklist"
        ),
        make_advertiser_headers(rival["id"]),
    )
    own_list = validate_success(allowed, expected_status=201)
    assert own_list["advertiser_id"] == rival["id"], (
        f"expected advertiser_id {rival['id']}, got {own_list['advertiser_id']}"
    )
    assert own_list["status"] == "DRAFT", (
        f"expected a new list at DRAFT, got {own_list['status']}"
    )


def test_publisher_reading_a_rival_publishers_scorecard_is_not_resource_owner(api):
    """A publisher asks for a rival publisher's quality scorecard and is refused as a non-owner, while its own scorecard reads fine.

    PRD: "When `X-User-Role` is `Publisher`, `X-User-ID` is the `id` of the
    acting publisher; ownership checks compare `X-User-ID` to a page's
    `publisher_id`, to the `publisher_id` of the page behind an appealed
    classification, to a measurement batch's `publisher_id`, and to the
    publisher whose scorecard is being read."

    Design: Corner/rbac/publisher_scope_is_its_own_aggregate_only
    """
    advance_clock(api, CLOCK)
    owner = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    rival = setup_publisher(
        api,
        name="Lantern Media",
        primary_domain="lantern.example.com",
        sourced_traffic_pct=0.10,
    )

    refused = api.get_publisher_scorecard(
        owner["id"], make_publisher_headers(rival["id"])
    )
    error = validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert refused.status_code == 403, (
        f"expected HTTP 403 for a rival publisher's scorecard read, "
        f"got {refused.status_code}"
    )
    assert error["error_id"] == ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, (
        f"expected ERR_NOT_RESOURCE_OWNER, got {error['error_id']}"
    )

    own = api.get_publisher_scorecard(
        owner["id"], make_publisher_headers(owner["id"])
    )
    own_card = validate_success(own, expected_status=200)
    assert own_card["publisher_id"] == owner["id"], (
        f"expected the publisher's own scorecard for {owner['id']}, "
        f"got {own_card['publisher_id']}"
    )


def test_rival_publisher_cannot_appeal_a_classification_of_a_page_it_does_not_own(api):
    """A rival publisher files an appeal against another publisher's attested classification and is refused as a non-owner, not told the target is unappealable.

    PRD: "Appeals are filed only by the owning `Publisher`, and only against the
    page's currently effective record: the payload's `classification_id` must
    equal the page's `current_classification_id` and that record's
    `review_state` must be `CONFIRMED` or `OVERRIDDEN`."

    Design: Corner/rbac/publisher_scope_is_its_own_aggregate_only
    """
    advance_clock(api, CLOCK)
    owner = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    rival = setup_publisher(
        api,
        name="Lantern Media",
        primary_domain="lantern.example.com",
        sourced_traffic_pct=0.10,
    )
    suitability_version = setup_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2026.1"
    )
    page = setup_page(api, owner["id"], url="https://beacon.example.com/odds")
    classification = setup_reviewed_classification(
        api,
        page,
        suitability_version["id"],
        decision="CONFIRM",
        reviewer_user_id=ANALYST_REVIEWER_USER_ID,
        classification_overrides={
            "classifier_kind": "HUMAN",
            "category_codes": ["GAMBLING"],
            "ad_density_ratio": 0.10,
            "refresh_seconds": 0,
            "originality_score": 90,
        },
        review_note="Sportsbook odds page",
    )
    assert classification["review_state"] == "CONFIRMED", (
        "the appeal target must be attested before the probe, got "
        f"{classification['review_state']}"
    )

    refused = api.create_appeal(
        factories.create_appeal_payload(
            classification["id"],
            reason_code="CATEGORY_MISREAD",
            evidence_note="Filed by a publisher who does not own the page",
        ),
        make_publisher_headers(rival["id"]),
    )
    error = validate_error(refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)
    assert refused.status_code == 403, (
        f"expected HTTP 403 for an appeal filed by a rival publisher, "
        f"got {refused.status_code}"
    )
    assert error["error_id"] == ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, (
        "expected ERR_NOT_RESOURCE_OWNER for a rival publisher's filing, got "
        f"{error['error_id']}"
    )

    untouched = read_page(api, page["id"])
    assert untouched["appeal_count"] == 0, (
        f"expected appeal_count 0 after the refused filing, "
        f"got {untouched['appeal_count']}"
    )
    assert untouched["classification_state"] == "HUMAN_CONFIRMED", (
        "expected the page to stay at HUMAN_CONFIRMED after the refused filing, "
        f"got {untouched['classification_state']}"
    )

    # The owning publisher files the identical appeal successfully, which is
    # what proves the refusal above was about ownership and not eligibility.
    allowed = api.create_appeal(
        factories.create_appeal_payload(
            classification["id"],
            reason_code="CATEGORY_MISREAD",
            evidence_note="Editorial coverage of odds, no wagering offered",
        ),
        make_publisher_headers(owner["id"]),
    )
    appeal = validate_success(allowed, expected_status=201)
    assert appeal["appeal_state"] == "FILED", (
        f"expected appeal_state FILED, got {appeal['appeal_state']}"
    )
    assert appeal["round_no"] == 1, (
        f"expected round_no 1 on a freshly filed appeal, got {appeal['round_no']}"
    )
    appealed = read_page(api, page["id"])
    assert appealed["classification_state"] == "APPEALED", (
        f"expected the page at APPEALED, got {appealed['classification_state']}"
    )
    assert appealed["appeal_count"] == 1, (
        f"expected appeal_count 1, got {appealed['appeal_count']}"
    )


def test_dispute_officer_reads_a_publisher_scorecard_without_ownership_scope(api):
    """The scorecard a rival publisher may not read is a shared read for the dispute channel.

    PRD: "A publisher's own reputation is exposed as a computed scorecard,
    readable by a `PlatformAdmin`, a `DisputeOfficer`, or the publisher itself."

    Design: Corner/rbac/publisher_scope_is_its_own_aggregate_only
    """
    advance_clock(api, CLOCK)
    publisher = setup_publisher(
        api,
        name="Beacon Digital",
        primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )

    officer_view = api.get_publisher_scorecard(
        publisher["id"], TEST_USERS["officer_headers"]
    )
    card = validate_success(officer_view, expected_status=200)
    assert card["publisher_id"] == publisher["id"], (
        f"expected scorecard for publisher {publisher['id']}, "
        f"got {card['publisher_id']}"
    )


def test_authoring_auditor_cannot_conclude_the_audit_of_its_own_methodology_version(api):
    """The auditor who wrote the standard holds exactly the right role and is still refused, on identity, when signing off on it.

    PRD: "If the concluding auditor's `X-User-ID` equals the version's
    `authored_by_user_id`, the conclusion is refused with
    `ERR_SEGREGATION_OF_DUTIES` before either branch is considered."

    Design: Corner/rbac/audit_conclusion_requires_a_second_auditor_identity
    """
    advance_clock(api, CLOCK)
    version = setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        author_user_id=AUDITOR_AUTHOR_USER_ID,
        version_code="VIEW-2026.1",
        display_in_view_seconds=1.0,
        display_pixel_pct=0.5,
        coverage_rate_floor=0.7,
        ivt_rate_ceiling=0.02,
    )
    assert version["authored_by_user_id"] == AUDITOR_AUTHOR_USER_ID, (
        f"expected authored_by_user_id {AUDITOR_AUTHOR_USER_ID}, "
        f"got {version['authored_by_user_id']}"
    )
    assert version["version"] == 1, (
        f"expected version 1 on a freshly authored standard, got {version['version']}"
    )

    refused = api.conclude_audit(
        version["id"],
        factories.conclude_audit_payload(outcome="PASSED", audit_finding_rate=0.01),
        make_auditor_headers(AUDITOR_AUTHOR_USER_ID),
    )
    error = validate_error(refused, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
    assert refused.status_code == 403, (
        f"expected HTTP 403 for a self-signed audit conclusion, "
        f"got {refused.status_code}"
    )
    assert error["error_id"] == ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, (
        "expected ERR_SEGREGATION_OF_DUTIES rather than a role refusal, got "
        f"{error['error_id']} - the author holds the AccreditationAuditor role"
    )

    after = validate_success(
        api.get_methodology_version(version["id"], TEST_USERS["auditor_headers"]),
        expected_status=200,
    )
    assert after["accreditation_status"] == "PROVISIONAL", (
        f"expected the standard still PROVISIONAL, "
        f"got {after['accreditation_status']}"
    )
    assert after["audit_outcome"] is None, (
        f"expected audit_outcome null after the refusal, got {after['audit_outcome']}"
    )
    assert after["lead_auditor_user_id"] is None, (
        f"expected lead_auditor_user_id null after the refusal, "
        f"got {after['lead_auditor_user_id']}"
    )
    assert after["audit_finding_rate"] is None, (
        f"expected audit_finding_rate null after the refusal, "
        f"got {after['audit_finding_rate']}"
    )
    assert after["version"] == version["version"], (
        f"expected version {version['version']} after the refusal, "
        f"got {after['version']}"
    )


def test_a_second_auditor_identity_concludes_the_same_audit(api):
    """The byte-identical conclusion from a different auditor identity accredits the standard, which is what separates an identity check from a role check.

    PRD: "A `PROVISIONAL` version moves `PROVISIONAL → ACCREDITED`, and the
    platform records `audit_outcome` `PASSED`, `lead_auditor_user_id` from the
    concluding auditor's `X-User-ID`, and the reported `audit_finding_rate`."

    Design: Corner/rbac/audit_conclusion_requires_a_second_auditor_identity
    """
    advance_clock(api, CLOCK)
    version = setup_methodology_version(
        api,
        standard_family="VIEWABILITY",
        author_user_id=AUDITOR_AUTHOR_USER_ID,
        version_code="VIEW-2026.1",
        display_in_view_seconds=1.0,
        display_pixel_pct=0.5,
        coverage_rate_floor=0.7,
        ivt_rate_ceiling=0.02,
    )

    concluded = api.conclude_audit(
        version["id"],
        factories.conclude_audit_payload(outcome="PASSED", audit_finding_rate=0.01),
        make_auditor_headers(AUDITOR_CONCLUDER_USER_ID),
    )
    data = validate_success(concluded, expected_status=200)
    assert data["accreditation_status"] == "ACCREDITED", (
        f"expected ACCREDITED, got {data['accreditation_status']} after a "
        "passing conclusion by a second auditor"
    )
    assert data["audit_outcome"] == "PASSED", (
        f"expected audit_outcome PASSED, got {data['audit_outcome']}"
    )
    assert data["lead_auditor_user_id"] == AUDITOR_CONCLUDER_USER_ID, (
        f"expected lead_auditor_user_id {AUDITOR_CONCLUDER_USER_ID}, "
        f"got {data['lead_auditor_user_id']}"
    )
    assert data["authored_by_user_id"] == AUDITOR_AUTHOR_USER_ID, (
        f"expected authored_by_user_id {AUDITOR_AUTHOR_USER_ID} to be retained, "
        f"got {data['authored_by_user_id']}"
    )
    assert float(data["audit_finding_rate"]) == pytest.approx(0.01, abs=0.0001), (
        f"expected audit_finding_rate 0.01, got {data['audit_finding_rate']}"
    )
    assert data["version"] == version["version"] + 1, (
        f"expected version {version['version'] + 1} after the conclusion, "
        f"got {data['version']}"
    )
