"""Typed error identities: each guard answers its own error, not a generic conflict.

Every uniqueness scope, every state machine, every methodology guard, the
measurement intake boundaries, the publication gate, the appeal target and
remedy guards, the fiscal no-credit refusal and the two-part authentication rule
are exercised here against the identifiers the PRD names in prose.
"""
import pytest

from test_helpers import (
    ANALYST_AUTHOR_USER_ID,
    NON_EXISTENT_UUID,
    ANALYST_REVIEWER_USER_ID,
    AUDITOR_AUTHOR_USER_ID,
    AUDITOR_CONCLUDER_USER_ID,
    OFFICER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    add_list_entry,
    advance_clock,
    factories,
    get_success_data,
    headers_without_user_id,
    make_advertiser_headers,
    make_analyst_headers,
    make_auditor_headers,
    make_officer_headers,
    make_publisher_headers,
    read_advertiser,
    read_appeal,
    read_batch,
    read_campaign,
    read_claim,
    read_classification,
    read_finding,
    read_list,
    read_page,
    read_publisher,
    read_segment,
    setup_accredited_methodology_version,
    setup_advertiser,
    setup_base_world,
    setup_campaign,
    setup_classification,
    setup_confirmed_finding,
    setup_ingested_batch,
    setup_inventory_list,
    setup_methodology_version,
    setup_page,
    setup_proposed_finding,
    setup_published_list,
    setup_publisher,
    setup_reviewed_classification,
    setup_segment_world,
    setup_submitted_claim,
    setup_synced_segment,
    suspend_methodology_version,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
OPERATOR = TEST_USERS["operator_headers"]

CLOCK = "2026-08-10T00:00:00Z"


# ===========================================================================
# Uniqueness scopes: five scopes, five identifiers
# ===========================================================================
def test_second_publisher_on_the_same_primary_domain_is_refused(api):
    """A second publisher registering an already-taken flagship domain is refused.

    PRD: "Two publishers may not share a `primary_domain`; a collision answers `ERR_DUPLICATE_PUBLISHER_DOMAIN`."

    Design: Corner/errors/each_uniqueness_scope_answers_its_own_duplicate_error
    """
    advance_clock(api, CLOCK)
    setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )

    response = api.create_publisher(
        {
            "name": "Beacon Digital Group",
            "primary_domain": "beacon.example.com",
            "sourced_traffic_pct": 0.10,
        },
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_PUBLISHER_DOMAIN.value, 409)


def test_repeated_version_code_inside_one_family_is_refused(api):
    """A second methodology version reusing a version_code of the same family is refused
    even though its effectivity window merely abuts the first.

    PRD: "A version belongs to a `standard_family`, one of `VIEWABILITY`, `IVT` or `SUITABILITY`, carries a `version_code` of 1 to 40 characters that must be unique inside its family — a collision answers `ERR_DUPLICATE_VERSION_CODE` — and declares an effectivity window as `effective_from` and `effective_to`, both ISO 8601 UTC instants, with `effective_to` strictly after `effective_from`."

    Design: Corner/errors/each_uniqueness_scope_answers_its_own_duplicate_error
    """
    advance_clock(api, CLOCK)
    author = make_auditor_headers(AUDITOR_AUTHOR_USER_ID)
    setup_methodology_version(
        api, standard_family="VIEWABILITY", version_code="VIEW-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        display_in_view_seconds=1.0, display_pixel_pct=0.5,
        coverage_rate_floor=0.7, ivt_rate_ceiling=0.02,
    )

    clash = api.create_methodology_version(
        factories.create_methodology_version_payload(
            standard_family="VIEWABILITY", version_code="VIEW-2026.1",
            effective_from="2027-01-01T00:00:00Z", effective_to="2028-01-01T00:00:00Z",
        ),
        author,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_VERSION_CODE.value, 409)

    # The same abutting window under a free code is accepted, so the refusal
    # above was about the code and not about the window.
    successor = api.create_methodology_version(
        factories.create_methodology_version_payload(
            standard_family="VIEWABILITY", version_code="VIEW-2027.1",
            effective_from="2027-01-01T00:00:00Z", effective_to="2028-01-01T00:00:00Z",
        ),
        author,
    )
    created = validate_success(successor, expected_status=201)
    assert created["version_code"] == "VIEW-2027.1", (
        f"expected VIEW-2027.1, got {created['version_code']} for the abutting successor"
    )


def test_list_name_uniqueness_is_scoped_to_advertiser_and_list_type(api):
    """Reusing a list name inside one (advertiser, list_type) pair is refused while the
    same name under the other list type is accepted.

    PRD: "A list declares its owning `advertiser_id`, a `list_type` of `INCLUSION` or `EXCLUSION`, and a `name` of 1 to 120 characters that must be unique among that advertiser's lists of the same type; a collision answers `ERR_DUPLICATE_LIST_NAME`."

    Design: Corner/errors/each_uniqueness_scope_answers_its_own_duplicate_error
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    advertiser_headers = make_advertiser_headers(advertiser["id"])
    setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Allowlist"
    )

    clash = api.create_inventory_list(
        {
            "advertiser_id": advertiser["id"],
            "list_type": "INCLUSION",
            "name": "Beacon Allowlist",
        },
        advertiser_headers,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_LIST_NAME.value, 409)

    other_type = api.create_inventory_list(
        {
            "advertiser_id": advertiser["id"],
            "list_type": "EXCLUSION",
            "name": "Beacon Allowlist",
        },
        advertiser_headers,
    )
    accepted = validate_success(other_type, expected_status=201)
    assert accepted["status"] == "DRAFT", (
        f"expected DRAFT, got {accepted['status']} for the same name under EXCLUSION"
    )


def test_repeated_entry_triple_inside_one_list_is_refused(api):
    """Appending the same entry_type and entry_value twice to one list is refused and
    the list's entry_count does not move.

    PRD: "The combination of `list_id`, `entry_type` and `entry_value` must be unique inside the list; a repeat answers `ERR_DUPLICATE_LIST_ENTRY`."

    Design: Corner/errors/each_uniqueness_scope_answers_its_own_duplicate_error
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    inclusion = setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Allowlist"
    )
    add_list_entry(api, advertiser, inclusion["id"], "PUBLISHER", publisher["id"])

    clash = api.create_list_entry(
        inclusion["id"],
        {"entry_type": "PUBLISHER", "entry_value": publisher["id"]},
        make_advertiser_headers(advertiser["id"]),
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_LIST_ENTRY.value, 409)

    stored = read_list(api, inclusion["id"])
    assert stored["entry_count"] == 1, (
        f"expected 1, got {stored['entry_count']} after the refused duplicate entry"
    )


def test_repeated_page_url_under_one_publisher_is_refused(api):
    """Registering the same URL twice under one publisher is refused and no second page
    row appears.

    PRD: "The URL must be 1 to 300 characters and must begin with `https://`, and no publisher may register the same `url` twice — a repeat answers `ERR_DUPLICATE_PAGE_URL`, while the same URL under a different publisher is permitted."

    Design: Corner/errors/each_uniqueness_scope_answers_its_own_duplicate_error
    """
    advance_clock(api, CLOCK)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    publisher_headers = make_publisher_headers(publisher["id"])
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/news")

    clash = api.create_page(
        {"publisher_id": publisher["id"], "url": "https://beacon.example.com/news"},
        publisher_headers,
    )
    validate_error(clash, ApiErrorId.ERR_DUPLICATE_PAGE_URL.value, 409)

    rows, meta = validate_paginated(
        api.list_pages(ADMIN, params={"publisher_id": publisher["id"]})
    )
    assert meta["total_count"] == 1, (
        f"expected 1, got {meta['total_count']} pages after the refused duplicate URL"
    )
    assert rows[0]["id"] == page["id"], (
        f"expected {page['id']}, got {rows[0]['id']} as the only page of the publisher"
    )


# ===========================================================================
# Repeating a completed transition: six aggregates, six state identifiers
# ===========================================================================
def test_reinstating_an_already_active_publisher_answers_the_publisher_state_error(api):
    """Asking for ACTIVE on a publisher that already stands ACTIVE is not a declared
    transition.

    PRD: "`DELISTED` is terminal: any further standing change against a delisted publisher answers `ERR_PUBLISHER_DELISTED`, and a `new_status` that is not reachable from the publisher's current `publisher_status` — asking for `ACTIVE` on a publisher that is already `ACTIVE`, for instance — answers `ERR_INVALID_PUBLISHER_STATE`."

    Design: Corner/errors/repeating_a_completed_transition_answers_the_entity_specific_state_error
    """
    advance_clock(api, CLOCK)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    assert publisher["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE, got {publisher['publisher_status']} on registration"
    )

    response = api.change_publisher_status(
        publisher["id"],
        factories.change_publisher_status_payload(
            "ACTIVE", reason="No-op reinstatement of an already active publisher"
        ),
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PUBLISHER_STATE.value, 409)

    after = read_publisher(api, publisher["id"])
    assert after["publisher_status"] == "ACTIVE", (
        f"expected ACTIVE, got {after['publisher_status']} after the refused change"
    )
    assert after["version"] == publisher["version"], (
        f"expected version {publisher['version']}, got {after['version']} "
        "after a refused standing change"
    )


def test_concluding_an_audit_on_a_suspended_version_answers_the_methodology_state_error(api):
    """A second audit conclusion against a version already suspended by a deficient
    finding is refused.

    PRD: "A conclusion submitted against a version whose `accreditation_status` is already `SUSPENDED` or `LAPSED` answers `ERR_INVALID_METHODOLOGY_STATE`."

    Design: Corner/errors/repeating_a_completed_transition_answers_the_entity_specific_state_error
    """
    advance_clock(api, CLOCK)
    version = setup_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2027.1",
        effective_from="2027-01-01T00:00:00Z", effective_to="2028-01-01T00:00:00Z",
    )
    suspended = suspend_methodology_version(api, version["id"], audit_finding_rate=0.12)
    assert suspended["accreditation_status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {suspended['accreditation_status']} after DEFICIENT"
    )

    response = api.conclude_audit(
        version["id"],
        {"outcome": "PASSED", "audit_finding_rate": 0.01},
        make_auditor_headers(AUDITOR_CONCLUDER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_METHODOLOGY_STATE.value, 409)

    after = get_success_data(
        api.get_methodology_version(version["id"], ADMIN)
    )
    assert after["accreditation_status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {after['accreditation_status']} after the refused pass"
    )
    assert after["audit_outcome"] == "DEFICIENT", (
        f"expected DEFICIENT, got {after['audit_outcome']} after the refused pass"
    )
    assert after["version"] == suspended["version"], (
        f"expected version {suspended['version']}, got {after['version']} "
        "after a refused audit conclusion"
    )


def test_syncing_an_already_synced_segment_answers_the_segment_state_error(api):
    """A second sync of a segment already pushed to the buying platform is refused and
    the pinned snapshot is untouched.

    PRD: "It moves the segment `PENDING → SYNCED` on its first use and `STALE → SYNCED` afterwards; a sync against a segment already in `SYNCED` answers `ERR_INVALID_SEGMENT_STATE`."

    Design: Corner/errors/repeating_a_completed_transition_answers_the_entity_specific_state_error
    """
    world = setup_base_world(api, clock=CLOCK)
    segment_world = setup_segment_world(
        api, world, list_type="INCLUSION",
        entries=[("PUBLISHER", world["publisher"]["id"])],
    )
    before = read_segment(api, segment_world["segment"]["id"])
    assert before["sync_status"] == "SYNCED", (
        f"expected SYNCED, got {before['sync_status']} after the first sync"
    )

    response = api.sync_pre_bid_segment(
        segment_world["segment"]["id"], world["advertiser_headers"]
    )
    validate_error(response, ApiErrorId.ERR_INVALID_SEGMENT_STATE.value, 409)

    after = read_segment(api, segment_world["segment"]["id"])
    assert after["sync_status"] == "SYNCED", (
        f"expected SYNCED, got {after['sync_status']} after the refused re-sync"
    )
    assert after["synced_at"] == before["synced_at"], (
        f"expected synced_at {before['synced_at']}, got {after['synced_at']} "
        "after a refused re-sync"
    )
    assert after["synced_inclusion_version"] == before["synced_inclusion_version"], (
        f"expected synced_inclusion_version {before['synced_inclusion_version']}, "
        f"got {after['synced_inclusion_version']} after a refused re-sync"
    )
    assert after["version"] == before["version"], (
        f"expected version {before['version']}, got {after['version']} "
        "after a refused re-sync"
    )


def test_reviewing_an_already_confirmed_record_answers_the_classification_state_error(api):
    """A second human review of a record already confirmed is refused and the stamped
    reviewer identity is unchanged.

    PRD: "Review is only available on a record whose `review_state` is `PENDING_REVIEW` and which is the page's `current_classification_id`; anything else answers `ERR_INVALID_CLASSIFICATION_STATE`."

    Design: Corner/errors/repeating_a_completed_transition_answers_the_entity_specific_state_error
    """
    world = setup_base_world(api, clock=CLOCK)
    reviewed = setup_reviewed_classification(
        api, world["page"], world["suitability_version"]["id"], decision="CONFIRM"
    )
    assert reviewed["review_state"] == "CONFIRMED", (
        f"expected CONFIRMED, got {reviewed['review_state']} after the first review"
    )

    response = api.review_page_classification(
        reviewed["id"],
        {"decision": "CONFIRM", "review_note": "Second look"},
        make_analyst_headers(ANALYST_REVIEWER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_CLASSIFICATION_STATE.value, 409)

    after = read_classification(api, reviewed["id"])
    assert after["review_state"] == "CONFIRMED", (
        f"expected CONFIRMED, got {after['review_state']} after the refused re-review"
    )
    assert after["reviewed_by_user_id"] == ANALYST_REVIEWER_USER_ID, (
        f"expected {ANALYST_REVIEWER_USER_ID}, got {after['reviewed_by_user_id']} "
        "after a refused re-review"
    )
    assert after["version"] == reviewed["version"], (
        f"expected version {reviewed['version']}, got {after['version']} "
        "after a refused re-review"
    )


def test_confirming_an_already_confirmed_finding_answers_the_finding_state_error(api):
    """A second confirmation of one detector finding is refused and its flagged
    impressions are not counted twice.

    PRD: "Confirming a finding whose `status` is not `PROPOSED` answers `ERR_INVALID_FINDING_STATE`."

    Design: Corner/errors/repeating_a_completed_transition_answers_the_entity_specific_state_error
    """
    world = setup_base_world(api, clock=CLOCK)
    batch = setup_ingested_batch(api, world)
    finding = setup_confirmed_finding(
        api, batch["id"], ivt_class="DATACENTER", flagged_impressions=100,
        confidence=0.90, detector_note="Hosting ASN",
    )
    before = read_batch(api, batch["id"])
    assert before["ivt_impressions"] == 100, (
        f"expected 100, got {before['ivt_impressions']} after the first confirmation"
    )

    response = api.confirm_ivt_finding(finding["id"], OPERATOR)
    validate_error(response, ApiErrorId.ERR_INVALID_FINDING_STATE.value, 409)

    after_finding = read_finding(api, finding["id"])
    assert after_finding["status"] == "CONFIRMED", (
        f"expected CONFIRMED, got {after_finding['status']} after the refused re-confirm"
    )
    assert after_finding["version"] == finding["version"], (
        f"expected version {finding['version']}, got {after_finding['version']} "
        "after a refused re-confirm"
    )
    after_batch = read_batch(api, batch["id"])
    assert after_batch["ivt_impressions"] == 100, (
        f"expected 100, got {after_batch['ivt_impressions']} - the refused re-confirm "
        "double-counted the flagged impressions"
    )
    assert after_batch["version"] == before["version"], (
        f"expected version {before['version']}, got {after_batch['version']} "
        "after a refused re-confirm"
    )


def test_appealing_a_page_still_model_classified_answers_the_page_state_error(api):
    """An appeal filed against a page whose only verdict is an unreviewed model call is
    refused on the page's own state, not on the cited record.

    PRD: "Filing against a page whose `classification_state` does not declare the move — a page still at `MODEL_CLASSIFIED`, for instance — answers `ERR_INVALID_PAGE_STATE`."

    Design: Corner/errors/repeating_a_completed_transition_answers_the_entity_specific_state_error
    """
    world = setup_base_world(api, clock=CLOCK)
    classification = setup_classification(
        api, world["page"], world["suitability_version"]["id"]
    )
    before = read_page(api, world["page"]["id"])
    assert before["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED, got {before['classification_state']} "
        "after one model classification"
    )

    response = api.create_appeal(
        factories.create_appeal_payload(
            classification["id"], reason_code="CATEGORY_MISREAD",
            evidence_note="Editorial page, not gambling",
        ),
        world["publisher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_PAGE_STATE.value, 409)

    after = read_page(api, world["page"]["id"])
    assert after["appeal_count"] == 0, (
        f"expected 0, got {after['appeal_count']} after the refused filing"
    )
    assert after["classification_state"] == "MODEL_CLASSIFIED", (
        f"expected MODEL_CLASSIFIED, got {after['classification_state']} "
        "after the refused filing"
    )
    assert after["version"] == before["version"], (
        f"expected version {before['version']}, got {after['version']} "
        "after a refused filing"
    )
    _, meta = validate_paginated(api.list_appeals(ADMIN))
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} appeal rows after the refused filing"
    )


# ===========================================================================
# Accreditation and family guards: three distinct identifiers, one inclusive
# ceiling
# ===========================================================================
def test_passing_conclusion_above_the_finding_rate_ceiling_is_refused_but_the_ceiling_itself_passes(api):
    """A pass reported at 0.06 is refused on the rate while the very same pass at
    exactly 0.05 accredits the version.

    PRD: "The branch is admissible only while `audit_finding_rate` is at most 0.05; a passing conclusion reporting a higher error rate is refused with `ERR_AUDIT_FINDING_RATE_TOO_HIGH`."

    Design: Corner/errors/methodology_guards_answer_three_distinct_errors
    """
    advance_clock(api, CLOCK)
    version = setup_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    concluder = make_auditor_headers(AUDITOR_CONCLUDER_USER_ID)

    refused = api.conclude_audit(
        version["id"], {"outcome": "PASSED", "audit_finding_rate": 0.06}, concluder
    )
    validate_error(refused, ApiErrorId.ERR_AUDIT_FINDING_RATE_TOO_HIGH.value, 409)

    unmoved = get_success_data(api.get_methodology_version(version["id"], ADMIN))
    assert unmoved["accreditation_status"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {unmoved['accreditation_status']} "
        "after the refused pass"
    )
    assert unmoved["audit_outcome"] is None, (
        f"expected None, got {unmoved['audit_outcome']} after the refused pass"
    )

    accepted = api.conclude_audit(
        version["id"], {"outcome": "PASSED", "audit_finding_rate": 0.05}, concluder
    )
    accredited = validate_success(accepted, expected_status=200)
    assert accredited["accreditation_status"] == "ACCREDITED", (
        f"expected ACCREDITED, got {accredited['accreditation_status']} "
        "at exactly the 0.05 ceiling"
    )
    assert accredited["audit_outcome"] == "PASSED", (
        f"expected PASSED, got {accredited['audit_outcome']} at the 0.05 ceiling"
    )
    assert accredited["audit_finding_rate"] == pytest.approx(0.05, abs=0.0001), (
        f"expected 0.05, got {accredited['audit_finding_rate']} at the 0.05 ceiling"
    )
    assert accredited["lead_auditor_user_id"] == AUDITOR_CONCLUDER_USER_ID, (
        f"expected {AUDITOR_CONCLUDER_USER_ID}, got "
        f"{accredited['lead_auditor_user_id']} as the concluding auditor"
    )


def test_deficient_conclusion_without_a_note_is_refused_on_the_note_not_the_rate(api):
    """A deficient conclusion carrying a 0.06 finding rate but no note is judged on the
    missing note alone.

    PRD: "A deficient conclusion must supply a non-blank `deficiency_note`; omitting it or supplying it blank answers `ERR_DEFICIENCY_NOTE_REQUIRED`."

    Design: Corner/errors/methodology_guards_answer_three_distinct_errors
    """
    advance_clock(api, CLOCK)
    version = setup_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )

    response = api.conclude_audit(
        version["id"],
        {"outcome": "DEFICIENT", "audit_finding_rate": 0.06},
        make_auditor_headers(AUDITOR_CONCLUDER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_DEFICIENCY_NOTE_REQUIRED.value, 422)

    after = get_success_data(api.get_methodology_version(version["id"], ADMIN))
    assert after["accreditation_status"] == "PROVISIONAL", (
        f"expected PROVISIONAL, got {after['accreditation_status']} "
        "after the refused deficient conclusion"
    )
    assert after["audit_outcome"] is None, (
        f"expected None, got {after['audit_outcome']} "
        "after the refused deficient conclusion"
    )
    assert after["version"] == version["version"], (
        f"expected version {version['version']}, got {after['version']} "
        "after a refused deficient conclusion"
    )


def test_classification_pinning_a_viewability_version_is_refused_on_the_family(api):
    """A classification that pins a viewability standard is refused and the page's
    concurrency token is not consumed.

    PRD: "The pinned methodology version must belong to the `SUITABILITY` family — a version from any other family answers `ERR_METHODOLOGY_FAMILY_MISMATCH`, checked before the accreditation and effectivity guards — and its `accreditation_status` must be `PROVISIONAL` or `ACCREDITED`, failing which the write answers `ERR_METHODOLOGY_NOT_ACCREDITED`."

    Design: Corner/errors/methodology_guards_answer_three_distinct_errors
    """
    advance_clock(api, CLOCK)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    viewability = setup_methodology_version(
        api, standard_family="VIEWABILITY", version_code="VIEW-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
        display_in_view_seconds=1.0, display_pixel_pct=0.5,
        coverage_rate_floor=0.7, ivt_rate_ceiling=0.02,
    )
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/news")

    response = api.create_page_classification(
        factories.create_page_classification_payload(
            page["id"], viewability["id"], page["version"], model_confidence=0.95
        ),
        make_analyst_headers(ANALYST_AUTHOR_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_METHODOLOGY_FAMILY_MISMATCH.value, 409)

    after = read_page(api, page["id"])
    assert after["classification_state"] == "UNCLASSIFIED", (
        f"expected UNCLASSIFIED, got {after['classification_state']} "
        "after the refused classification"
    )
    assert after["version"] == page["version"], (
        f"expected version {page['version']}, got {after['version']} - the refused "
        "classification consumed the page's concurrency token"
    )


def test_batch_pinning_a_suitability_version_is_refused_on_the_family(api):
    """Measurement intake that pins a suitability standard is refused and no batch row
    is created.

    PRD: "The pinned methodology version must belong to the `VIEWABILITY` family; another family answers `ERR_METHODOLOGY_FAMILY_MISMATCH`."

    Design: Corner/errors/methodology_guards_answer_three_distinct_errors
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    suitability = setup_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    campaign = setup_campaign(
        api, advertiser["id"], name="Q3 Display", cpm_cents=875,
        min_suitability_tier="MEDIUM_RISK", format="DISPLAY", target_coverage_rate=0.75,
    )
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/news")

    response = api.create_measurement_batch(
        factories.create_measurement_batch_payload(
            campaign["id"], publisher["id"], page["id"], suitability["id"],
            window_start="2026-08-01T00:00:00Z", window_end="2026-08-01T01:00:00Z",
            measurable_impressions=9000, in_view_impressions=9000,
        ),
        OPERATOR,
    )
    validate_error(response, ApiErrorId.ERR_METHODOLOGY_FAMILY_MISMATCH.value, 409)

    _, meta = validate_paginated(
        api.list_measurement_batches(ADMIN, params={"campaign_id": campaign["id"]})
    )
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} batches after the refused intake"
    )


# ===========================================================================
# Measurement intake and confirmation boundaries
# ===========================================================================
def test_window_ending_at_the_clock_is_accepted_while_one_second_later_is_refused(api):
    """A delivery window may close exactly on the logical clock, but a window closing one
    second later is refused as still open.

    PRD: "A window whose `window_end` lies after the current logical clock, or whose `window_start` is not strictly before its `window_end`, answers `ERR_BATCH_WINDOW_IN_FUTURE`."

    Design: Corner/errors/intake_and_confirmation_guards_answer_their_own_errors
    """
    world = setup_base_world(api, clock=CLOCK)
    accepted = api.create_measurement_batch(
        factories.create_measurement_batch_payload(
            world["campaign"]["id"], world["publisher"]["id"], world["page"]["id"],
            world["viewability_version"]["id"],
            window_start="2026-08-09T23:00:00Z", window_end=CLOCK,
            measurable_impressions=9000, in_view_impressions=9000,
        ),
        OPERATOR,
    )
    ingested = validate_success(accepted, expected_status=201)
    assert ingested["scoring_status"] == "INGESTED", (
        f"expected INGESTED, got {ingested['scoring_status']} for a window closing "
        "exactly on the clock"
    )

    # The overshooting probe is measured on a second page of the same publisher so
    # that the campaign/page/format separation rule of the window-collision guard,
    # which is consulted earlier, cannot pre-empt the future-window refusal.
    second_page = setup_page(api, world["publisher"]["id"], url="https://beacon.example.com/sport")
    refused = api.create_measurement_batch(
        factories.create_measurement_batch_payload(
            world["campaign"]["id"], world["publisher"]["id"], second_page["id"],
            world["viewability_version"]["id"],
            window_start="2026-08-09T00:00:00Z", window_end="2026-08-10T00:00:01Z",
            measurable_impressions=9000, in_view_impressions=9000,
        ),
        OPERATOR,
    )
    validate_error(refused, ApiErrorId.ERR_BATCH_WINDOW_IN_FUTURE.value, 422)

    _, meta = validate_paginated(
        api.list_measurement_batches(
            ADMIN, params={"campaign_id": world["campaign"]["id"]}
        )
    )
    assert meta["total_count"] == 1, (
        f"expected 1, got {meta['total_count']} batches - only the window closing on "
        "the clock should have been ingested"
    )


def test_finding_below_the_confidence_floor_cannot_be_confirmed_while_the_floor_itself_can(api):
    """A detector signal of 0.7499 is refused confirmation while one at exactly 0.75 is
    confirmed and counted.

    PRD: "It requires a `confidence` of at least 0.75; a weaker detector signal answers `ERR_IVT_CONFIDENCE_TOO_LOW`."

    Design: Corner/errors/intake_and_confirmation_guards_answer_their_own_errors
    """
    world = setup_base_world(api, clock=CLOCK)
    batch = setup_ingested_batch(api, world)
    weak = setup_proposed_finding(
        api, batch["id"], ivt_class="GENERAL_BOT", flagged_impressions=100,
        confidence=0.7499, detector_note="Crawler heuristics, weak signal",
    )
    at_floor = setup_proposed_finding(
        api, batch["id"], ivt_class="DATACENTER", flagged_impressions=100,
        confidence=0.75, detector_note="Hosting ASN, at the floor",
    )

    refused = api.confirm_ivt_finding(weak["id"], OPERATOR)
    validate_error(refused, ApiErrorId.ERR_IVT_CONFIDENCE_TOO_LOW.value, 409)
    still_proposed = read_finding(api, weak["id"])
    assert still_proposed["status"] == "PROPOSED", (
        f"expected PROPOSED, got {still_proposed['status']} after the refused confirm"
    )
    before = read_batch(api, batch["id"])
    assert before["ivt_impressions"] == 0, (
        f"expected 0, got {before['ivt_impressions']} while no finding is confirmed"
    )

    accepted = api.confirm_ivt_finding(at_floor["id"], OPERATOR)
    confirmed = validate_success(accepted, expected_status=200)
    assert confirmed["status"] == "CONFIRMED", (
        f"expected CONFIRMED, got {confirmed['status']} at exactly the 0.75 floor"
    )
    after = read_batch(api, batch["id"])
    assert after["ivt_impressions"] == 100, (
        f"expected 100, got {after['ivt_impressions']} - only the confirmed finding "
        "may contribute"
    )

    rows, meta = validate_paginated(api.list_batch_ivt_findings(batch["id"], ADMIN))
    assert meta["total_count"] == 2, (
        f"expected 2, got {meta['total_count']} findings on the batch"
    )
    statuses = sorted(row["status"] for row in rows)
    assert statuses == ["CONFIRMED", "PROPOSED"], (
        f"expected ['CONFIRMED', 'PROPOSED'], got {statuses} after the two confirms"
    )


# ===========================================================================
# The publication gate is scoped to ALLOW + PUBLISHER entries only
# ===========================================================================
def test_publish_gate_fires_only_for_an_allow_publisher_entry_naming_a_delisted_publisher(api):
    """A delisted publisher blocks the allowlist that names it by identifier, but not the
    allowlist that names its domain nor the blocklist that shuts it out.

    PRD: "And a list may not be published while any of its entries has `action` `ALLOW`, `entry_type` `PUBLISHER`, and an `entry_value` naming a publisher whose `publisher_status` is `RESTRICTED` or `DELISTED`; that attempt answers `ERR_LIST_CONTAINS_RESTRICTED_PUBLISHER`."

    Design: Corner/errors/publish_gate_only_looks_at_allow_publisher_entries
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    advertiser_headers = make_advertiser_headers(advertiser["id"])
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )

    allow_by_publisher = setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Allowlist"
    )
    add_list_entry(
        api, advertiser, allow_by_publisher["id"], "PUBLISHER", publisher["id"]
    )
    allow_by_domain = setup_inventory_list(
        api, advertiser, list_type="INCLUSION", name="Beacon Domain Allowlist"
    )
    add_list_entry(
        api, advertiser, allow_by_domain["id"], "DOMAIN", "beacon.example.com"
    )
    block_by_publisher = setup_inventory_list(
        api, advertiser, list_type="EXCLUSION", name="Beacon Blocklist"
    )
    add_list_entry(
        api, advertiser, block_by_publisher["id"], "PUBLISHER", publisher["id"]
    )

    delisted = get_success_data(
        api.change_publisher_status(
            publisher["id"],
            factories.change_publisher_status_payload(
                "DELISTED", reason="Repeated fraud findings"
            ),
            ADMIN,
        )
    )
    assert delisted["publisher_status"] == "DELISTED", (
        f"expected DELISTED, got {delisted['publisher_status']} after the delisting"
    )

    refused = api.publish_inventory_list(allow_by_publisher["id"], advertiser_headers)
    validate_error(
        refused, ApiErrorId.ERR_LIST_CONTAINS_RESTRICTED_PUBLISHER.value, 409
    )
    held = read_list(api, allow_by_publisher["id"])
    assert held["status"] == "DRAFT", (
        f"expected DRAFT, got {held['status']} after the refused publication"
    )
    assert held["published_version"] is None, (
        f"expected None, got {held['published_version']} after the refused publication"
    )
    assert held["published_at"] is None, (
        f"expected None, got {held['published_at']} after the refused publication"
    )

    # A DOMAIN entry addresses the same publisher's inventory but is out of the
    # gate's scope, which names entry_type PUBLISHER only.
    by_domain = validate_success(
        api.publish_inventory_list(allow_by_domain["id"], advertiser_headers),
        expected_status=200,
    )
    assert by_domain["status"] == "PUBLISHED", (
        f"expected PUBLISHED, got {by_domain['status']} for the domain allowlist"
    )

    # The exclusion list's entries derive action BLOCK, so shutting a delisted
    # publisher out is exactly what the gate is meant to permit.
    by_block = validate_success(
        api.publish_inventory_list(block_by_publisher["id"], advertiser_headers),
        expected_status=200,
    )
    assert by_block["status"] == "PUBLISHED", (
        f"expected PUBLISHED, got {by_block['status']} for the blocklist"
    )

    unchanged = read_publisher(api, publisher["id"])
    assert unchanged["publisher_status"] == "DELISTED", (
        f"expected DELISTED, got {unchanged['publisher_status']} - a publication "
        "attempt must not move supply-side standing"
    )


# ===========================================================================
# Appeal target currency and the overturn remedy
# ===========================================================================
GAMBLING_CLASSIFICATION = {
    "classifier_kind": "HUMAN",
    "category_codes": ["GAMBLING"],
    "ad_density_ratio": 0.10,
    "refresh_seconds": 0,
    "originality_score": 90,
}


def _page_with_two_attested_records(api):
    """A page carrying two successive human GAMBLING verdicts, both confirmed, so the
    first is superseded while the second is the page's currently effective record.
    Fifteen risk points put both at MEDIUM_RISK.
    """
    world = setup_base_world(
        api, clock=CLOCK,
        publisher_overrides={
            "name": "Beacon Digital", "primary_domain": "beacon.example.com",
            "sourced_traffic_pct": 0.40,
        },
    )
    first = setup_reviewed_classification(
        api, world["page"], world["suitability_version"]["id"], decision="CONFIRM",
        classification_overrides=dict(GAMBLING_CLASSIFICATION),
        review_note="Sportsbook odds page",
    )
    second = setup_reviewed_classification(
        api, world["page"], world["suitability_version"]["id"], decision="CONFIRM",
        classification_overrides=dict(GAMBLING_CLASSIFICATION),
        review_note="Recrawl agrees with the first read",
    )
    return world, first, second


def test_appeal_against_a_superseded_record_answers_the_superseded_error(api):
    """An appeal citing the page's displaced first verdict is refused on the record's
    currency even though the page itself is legally appealable.

    PRD: "A target that is superseded, vacated or still unreviewed answers `ERR_CLASSIFICATION_SUPERSEDED`."

    Design: Corner/errors/appeal_target_and_remedy_guards_answer_their_own_errors
    """
    world, first, second = _page_with_two_attested_records(api)
    displaced = read_classification(api, first["id"])
    assert displaced["review_state"] == "SUPERSEDED", (
        f"expected SUPERSEDED, got {displaced['review_state']} for the displaced record"
    )
    current = read_classification(api, second["id"])
    assert current["review_state"] == "CONFIRMED", (
        f"expected CONFIRMED, got {current['review_state']} for the second record"
    )
    page = read_page(api, world["page"]["id"])
    assert page["current_classification_id"] == second["id"], (
        f"expected {second['id']}, got {page['current_classification_id']} as the "
        "page's effective record"
    )
    assert page["current_tier"] == "MEDIUM_RISK", (
        f"expected MEDIUM_RISK, got {page['current_tier']} for fifteen risk points"
    )
    assert page["classification_state"] == "HUMAN_CONFIRMED", (
        f"expected HUMAN_CONFIRMED, got {page['classification_state']} - the page "
        "itself is appealable"
    )

    response = api.create_appeal(
        factories.create_appeal_payload(
            first["id"], reason_code="STALE_CRAWL",
            evidence_note="The first crawl predates our sportsbook removal",
        ),
        world["publisher_headers"],
    )
    validate_error(response, ApiErrorId.ERR_CLASSIFICATION_SUPERSEDED.value, 409)

    after = read_page(api, world["page"]["id"])
    assert after["appeal_count"] == 0, (
        f"expected 0, got {after['appeal_count']} after the refused filing"
    )


@pytest.mark.parametrize("revised_tier", ["MEDIUM_RISK", "HIGH_RISK"])
def test_overturn_remedy_no_better_than_the_disputed_tier_is_refused(api, revised_tier):
    """An overturn awarding the same tier as the dispute, or a worse one, is refused and
    the appeal stays open.

    PRD: "An omitted `revised_tier`, or one no better than the tier under dispute, answers `ERR_REVISED_TIER_REQUIRED`."

    Design: Corner/errors/appeal_target_and_remedy_guards_answer_their_own_errors
    """
    world, _first, second = _page_with_two_attested_records(api)
    filed = get_success_data(
        api.create_appeal(
            factories.create_appeal_payload(
                second["id"], reason_code="CATEGORY_MISREAD",
                evidence_note="Editorial coverage of odds, no wagering offered",
            ),
            world["publisher_headers"],
        )
    )
    assert filed["appeal_state"] == "FILED", (
        f"expected FILED, got {filed['appeal_state']} on filing"
    )

    response = api.decide_appeal(
        filed["id"],
        factories.decide_appeal_payload(
            outcome="OVERTURNED", revised_tier=revised_tier,
            decision_note=f"Remedy {revised_tier} against a MEDIUM_RISK dispute",
        ),
        make_officer_headers(OFFICER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_REVISED_TIER_REQUIRED.value, 422)

    after = read_appeal(api, filed["id"])
    assert after["appeal_state"] == "FILED", (
        f"expected FILED, got {after['appeal_state']} after the refused decision"
    )
    assert after["round_no"] == 1, (
        f"expected 1, got {after['round_no']} after the refused decision"
    )
    assert after["decided_by_user_id"] is None, (
        f"expected None, got {after['decided_by_user_id']} after the refused decision"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 0, (
        f"expected 0, got {publisher['decided_appeal_count']} after the refused decision"
    )


def test_upheld_decision_carrying_a_revised_tier_is_refused(api):
    """An upheld decision that nevertheless awards a remedy tier is refused.

    PRD: "An `UPHELD` decision must not supply `revised_tier`; doing so answers `ERR_REVISED_TIER_REQUIRED`."

    Design: Corner/errors/appeal_target_and_remedy_guards_answer_their_own_errors
    """
    world, _first, second = _page_with_two_attested_records(api)
    filed = get_success_data(
        api.create_appeal(
            factories.create_appeal_payload(
                second["id"], reason_code="CATEGORY_MISREAD",
                evidence_note="Editorial coverage of odds, no wagering offered",
            ),
            world["publisher_headers"],
        )
    )

    response = api.decide_appeal(
        filed["id"],
        factories.decide_appeal_payload(
            outcome="UPHELD", revised_tier="SAFE",
            decision_note="Upheld but a tier was supplied anyway",
        ),
        make_officer_headers(OFFICER_USER_ID),
    )
    validate_error(response, ApiErrorId.ERR_REVISED_TIER_REQUIRED.value, 422)

    after = read_appeal(api, filed["id"])
    assert after["appeal_state"] == "FILED", (
        f"expected FILED, got {after['appeal_state']} after the refused decision"
    )
    assert after["revised_tier"] is None, (
        f"expected None, got {after['revised_tier']} after the refused decision"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["decided_appeal_count"] == 0, (
        f"expected 0, got {publisher['decided_appeal_count']} after the refused decision"
    )


def test_overturn_remedy_strictly_better_than_the_disputed_tier_is_accepted(api):
    """A remedy one rung better than the disputed tier is accepted, vacates the disputed
    record and reclassifies the page.

    PRD: "It requires `revised_tier`, and that tier must be strictly better than the disputed record's `assigned_tier` — strictly greater in rank on the ladder of §2.5."

    Design: Corner/errors/appeal_target_and_remedy_guards_answer_their_own_errors
    """
    world, _first, second = _page_with_two_attested_records(api)
    filed = get_success_data(
        api.create_appeal(
            factories.create_appeal_payload(
                second["id"], reason_code="CATEGORY_MISREAD",
                evidence_note="Editorial coverage of odds, no wagering offered",
            ),
            world["publisher_headers"],
        )
    )

    decided = validate_success(
        api.decide_appeal(
            filed["id"],
            factories.decide_appeal_payload(
                outcome="OVERTURNED", revised_tier="LOW_RISK",
                decision_note="Editorial context accepted",
            ),
            make_officer_headers(OFFICER_USER_ID),
        ),
        expected_status=200,
    )
    assert decided["appeal_state"] == "OVERTURNED", (
        f"expected OVERTURNED, got {decided['appeal_state']} for a strictly better tier"
    )
    assert decided["revised_tier"] == "LOW_RISK", (
        f"expected LOW_RISK, got {decided['revised_tier']} as the awarded remedy"
    )

    page = read_page(api, world["page"]["id"])
    assert page["classification_state"] == "RECLASSIFIED", (
        f"expected RECLASSIFIED, got {page['classification_state']} after the overturn"
    )
    assert page["current_tier"] == "LOW_RISK", (
        f"expected LOW_RISK, got {page['current_tier']} after the overturn"
    )
    vacated = read_classification(api, second["id"])
    assert vacated["review_state"] == "VACATED", (
        f"expected VACATED, got {vacated['review_state']} for the disputed record"
    )
    publisher = read_publisher(api, world["publisher"]["id"])
    assert publisher["overturned_appeal_count"] == 1, (
        f"expected 1, got {publisher['overturned_appeal_count']} after the overturn"
    )


# ===========================================================================
# A repudiated batch credits nothing, and the campaign it drags into
# remediation refuses to re-sync
# ===========================================================================
DEFECT_FREE_FIGURES = {
    "measured_impressions": 10000,
    "measurable_impressions": 7000,
    "in_view_impressions": 7000,
    "avg_in_view_seconds": 1.2,
    "avg_in_view_pixel_pct": 0.6,
}


def _certify_batch(api, campaign, publisher, page, version, window_start, window_end):
    """Ingest, score and certify one defect-free batch: coverage 0.7000 meets the
    0.7 floor, no invalid traffic, and a SAFE page clears the MEDIUM_RISK floor.
    """
    batch = get_success_data(
        api.create_measurement_batch(
            factories.create_measurement_batch_payload(
                campaign["id"], publisher["id"], page["id"], version["id"],
                window_start=window_start, window_end=window_end,
                **DEFECT_FREE_FIGURES,
            ),
            OPERATOR,
        )
    )
    get_success_data(api.score_measurement_batch(batch["id"], OPERATOR))
    return get_success_data(api.certify_measurement_batch(batch["id"], OPERATOR))


def _campaign_in_remediation_with_a_decertified_batch(api):
    """Two abutting viewability standards each certify one batch, so the campaign
    carries 20000 measured against 14000 measurable. Suspending the later standard
    repudiates only its own batch, which leaves the campaign still below its 0.75
    contracted coverage and therefore drives it into remediation - and stales the
    segment that was already synced.
    """
    advance_clock(api, "2026-08-04T00:00:00Z")
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )
    suitability = setup_accredited_methodology_version(
        api, standard_family="SUITABILITY", version_code="SUIT-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    early_viewability = setup_accredited_methodology_version(
        api, standard_family="VIEWABILITY", version_code="VIEW-2026.1",
        effective_from="2026-01-01T00:00:00Z", effective_to="2026-08-05T00:00:00Z",
    )
    campaign = setup_campaign(
        api, advertiser["id"], name="Q3 Display", cpm_cents=875,
        min_suitability_tier="MEDIUM_RISK", format="DISPLAY", target_coverage_rate=0.75,
    )
    page = setup_page(api, publisher["id"], url="https://beacon.example.com/news")
    setup_classification(api, page, suitability["id"], model_confidence=0.95)
    kept = _certify_batch(
        api, campaign, publisher, page, early_viewability,
        "2026-08-01T00:00:00Z", "2026-08-01T01:00:00Z",
    )

    advance_clock(api, CLOCK)
    late_viewability = setup_accredited_methodology_version(
        api, standard_family="VIEWABILITY", version_code="VIEW-2026.2",
        effective_from="2026-08-05T00:00:00Z", effective_to="2027-01-01T00:00:00Z",
    )
    repudiated = _certify_batch(
        api, campaign, publisher, page, late_viewability,
        "2026-08-06T00:00:00Z", "2026-08-06T01:00:00Z",
    )

    published = setup_published_list(
        api, advertiser, list_type="INCLUSION",
        entries=[("PUBLISHER", publisher["id"])], name="Beacon Allowlist",
    )
    segment = setup_synced_segment(
        api, advertiser, campaign["id"], suitability_floor_tier="MEDIUM_RISK",
        inclusion_list_id=published["list"]["id"],
    )
    suspended = suspend_methodology_version(
        api, late_viewability["id"], audit_finding_rate=0.18
    )
    return {
        "advertiser": advertiser,
        "publisher": publisher,
        "campaign": campaign,
        "page": page,
        "advertiser_headers": make_advertiser_headers(advertiser["id"]),
        "list": published["list"],
        "segment": segment,
        "kept_batch": kept,
        "repudiated_batch": repudiated,
        "suspended_version": suspended,
    }


def test_claim_on_a_defect_free_decertified_batch_cannot_be_approved(api):
    """A repudiated but otherwise flawless batch shows a real provisional credit at intake
    and yet supports no credit at all at approval.

    PRD: "A recomputed `credited_impressions` of 0 — and therefore a `net_credit_cents` that is not greater than zero — is refused with `ERR_NO_CREDITABLE_IMPRESSIONS`; such a claim must be rejected instead, not approved for nothing."

    Design: Corner/errors/decertified_batch_credits_nothing_and_a_remediated_campaign_refuses_sync
    """
    world = _campaign_in_remediation_with_a_decertified_batch(api)
    assert world["suspended_version"]["accreditation_status"] == "SUSPENDED", (
        f"expected SUSPENDED, got {world['suspended_version']['accreditation_status']} "
        "after the deficient conclusion"
    )
    assert world["suspended_version"]["decertified_batch_count"] == 1, (
        f"expected 1, got {world['suspended_version']['decertified_batch_count']} "
        "batches repudiated by the suspension"
    )
    repudiated = read_batch(api, world["repudiated_batch"]["id"])
    assert repudiated["scoring_status"] == "DECERTIFIED", (
        f"expected DECERTIFIED, got {repudiated['scoring_status']} after the suspension"
    )
    campaign = read_campaign(api, world["campaign"]["id"])
    assert campaign["certified_measured_impressions"] == 10000, (
        f"expected 10000, got {campaign['certified_measured_impressions']} after the "
        "repudiated batch left the certified set"
    )
    assert campaign["coverage_status"] == "BELOW_TARGET", (
        f"expected BELOW_TARGET, got {campaign['coverage_status']} for 7000 measurable "
        "against 10000 measured under a 0.75 target"
    )
    assert campaign["status"] == "UNDER_REMEDIATION", (
        f"expected UNDER_REMEDIATION, got {campaign['status']} after the recomputation"
    )

    claim = setup_submitted_claim(
        api, world, batch_ids=[world["repudiated_batch"]["id"]]
    )
    assert claim["claim_state"] == "SUBMITTED", (
        f"expected SUBMITTED, got {claim['claim_state']} - a decertified batch is "
        "claimable"
    )
    assert claim["claimed_impressions"] == 10000, (
        f"expected 10000, got {claim['claimed_impressions']} on the gross basis"
    )
    assert claim["provisional_credit_cents"] == 8750, (
        f"expected 8750, got {claim['provisional_credit_cents']} for 10000 impressions "
        "at 875 cents per thousand"
    )

    officer = make_officer_headers(OFFICER_USER_ID)
    reviewed = validate_success(
        api.review_refund_claim(claim["id"], officer), expected_status=200
    )
    assert reviewed["claim_state"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW, got {reviewed['claim_state']} after the review"
    )

    refused = api.approve_refund_claim(
        claim["id"], officer,
        payload={"decision_note": "Attempting to settle a defect-free repudiated batch"},
    )
    validate_error(refused, ApiErrorId.ERR_NO_CREDITABLE_IMPRESSIONS.value, 409)

    held = read_claim(api, claim["id"])
    assert held["claim_state"] == "UNDER_REVIEW", (
        f"expected UNDER_REVIEW, got {held['claim_state']} after the refused approval"
    )
    advertiser = read_advertiser(api, world["advertiser"]["id"])
    assert advertiser["credit_received_cents_total"] == 0, (
        f"expected 0, got {advertiser['credit_received_cents_total']} after the "
        "refused approval"
    )
    assert advertiser["settled_claim_count"] == 0, (
        f"expected 0, got {advertiser['settled_claim_count']} after the refused approval"
    )

    rejected = validate_success(
        api.reject_refund_claim(
            claim["id"],
            factories.reject_claim_payload(
                reject_reason_code="BATCH_RESCORED",
                decision_note="No creditable impressions after recomputation",
            ),
            officer,
        ),
        expected_status=200,
    )
    assert rejected["claim_state"] == "REJECTED", (
        f"expected REJECTED, got {rejected['claim_state']} after the rejection"
    )
    assert rejected["reject_reason_code"] == "BATCH_RESCORED", (
        f"expected BATCH_RESCORED, got {rejected['reject_reason_code']} on the "
        "rejected claim"
    )
    closed = read_batch(api, world["repudiated_batch"]["id"])
    assert closed["settlement_status"] == "CLOSED_NO_CREDIT", (
        f"expected CLOSED_NO_CREDIT, got {closed['settlement_status']} after the "
        "rejection"
    )
    settled_campaign = read_campaign(api, world["campaign"]["id"])
    assert settled_campaign["open_claim_count"] == 0, (
        f"expected 0, got {settled_campaign['open_claim_count']} after the rejection"
    )


def test_staled_segment_of_a_remediated_campaign_refuses_to_resync(api):
    """The segment staled by the campaign's remediation cannot be pushed again while the
    campaign is under remediation, even though its pinned list is still published.

    PRD: "And the owning campaign's `status` must be `ACTIVE`; a campaign in `UNDER_REMEDIATION` answers `ERR_CAMPAIGN_UNDER_REMEDIATION` and stays unsyncable until it returns to `ACTIVE`."

    Design: Corner/errors/decertified_batch_credits_nothing_and_a_remediated_campaign_refuses_sync
    """
    world = _campaign_in_remediation_with_a_decertified_batch(api)
    staled = read_segment(api, world["segment"]["id"])
    assert staled["sync_status"] == "STALE", (
        f"expected STALE, got {staled['sync_status']} after the campaign entered "
        "remediation"
    )
    assert staled["stale_reason"] == "CAMPAIGN_UNDER_REMEDIATION", (
        f"expected CAMPAIGN_UNDER_REMEDIATION, got {staled['stale_reason']} on the "
        "staled segment"
    )

    response = api.sync_pre_bid_segment(
        world["segment"]["id"], world["advertiser_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CAMPAIGN_UNDER_REMEDIATION.value, 409)

    pinned = read_list(api, world["list"]["id"])
    assert pinned["status"] == "PUBLISHED", (
        f"expected PUBLISHED, got {pinned['status']} - the refusal is about the "
        "campaign, not the pinned list"
    )
    after = read_segment(api, world["segment"]["id"])
    assert after["sync_status"] == "STALE", (
        f"expected STALE, got {after['sync_status']} after the refused re-sync"
    )


# ===========================================================================
# Two-part authentication: an entity-backed role needs an identity
# ===========================================================================
def test_advertiser_role_without_a_user_id_is_unauthenticated(api):
    """A campaign filed under the Advertiser role but with no caller identity fails
    authentication, while the same call from a non-entity role needs no identity.

    PRD: "If `X-User-Role` is absent or holds a value outside the seven declared roles, or if `X-User-ID` is absent for a role whose identity is entity-backed, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/entity_backed_role_without_a_user_id_is_unauthenticated
    """
    advance_clock(api, CLOCK)
    advertiser = setup_advertiser(api, name="Northwind Media", credit_cap_cents=1000000)
    campaign_payload = {
        "advertiser_id": advertiser["id"],
        "name": "Q3 Display",
        "cpm_cents": 875,
        "min_suitability_tier": "MEDIUM_RISK",
        "format": "DISPLAY",
        "target_coverage_rate": 0.75,
    }

    response = api.create_campaign(
        dict(campaign_payload), headers_without_user_id("Advertiser")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _, meta = validate_paginated(api.list_campaigns(ADMIN))
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} campaigns after the unauthenticated call"
    )

    accepted = validate_success(
        api.create_campaign(
            dict(campaign_payload), headers_without_user_id("PlatformAdmin")
        ),
        expected_status=201,
    )
    assert accepted["status"] == "ACTIVE", (
        f"expected ACTIVE, got {accepted['status']} for the administrator's campaign"
    )
    assert accepted["advertiser_id"] == advertiser["id"], (
        f"expected {advertiser['id']}, got {accepted['advertiser_id']} as the owning "
        "advertiser"
    )


def test_publisher_role_without_a_user_id_is_unauthenticated(api):
    """A page registered under the Publisher role but with no caller identity fails
    authentication and no page row appears.

    PRD: "If `X-User-Role` is absent or holds a value outside the seven declared roles, or if `X-User-ID` is absent for a role whose identity is entity-backed, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/entity_backed_role_without_a_user_id_is_unauthenticated
    """
    advance_clock(api, CLOCK)
    publisher = setup_publisher(
        api, name="Beacon Digital", primary_domain="beacon.example.com",
        sourced_traffic_pct=0.40,
    )

    response = api.create_page(
        {"publisher_id": publisher["id"], "url": "https://beacon.example.com/news"},
        headers_without_user_id("Publisher"),
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _, meta = validate_paginated(api.list_pages(ADMIN))
    assert meta["total_count"] == 0, (
        f"expected 0, got {meta['total_count']} pages after the unauthenticated call"
    )


# ===========================================================================
# A nested read answers its own parent's typed not-found
# ===========================================================================
def test_nested_reads_answer_their_own_parent_not_found_error(api):
    """Reading the entries of a list that does not exist, or the findings of a batch that
    does not exist, each answers that parent's own typed identifier.

    PRD: "For a nested read such as the entries of one inventory list or the invalid-traffic findings of one batch, the parent identifier is resolved first: an unresolvable parent yields that parent's own not-found error (`ERR_INVENTORY_LIST_NOT_FOUND`, `ERR_MEASUREMENT_BATCH_NOT_FOUND`) before any child filter or query parameter is examined."

    Design: Corner/errors/every_aggregate_answers_its_own_typed_not_found
    """
    world = setup_base_world(api, clock=CLOCK)
    real_list = setup_inventory_list(
        api, world["advertiser"], list_type="INCLUSION", name="Beacon Allowlist"
    )
    add_list_entry(
        api, world["advertiser"], real_list["id"], "PUBLISHER", world["publisher"]["id"]
    )
    real_batch = setup_ingested_batch(api, world)
    setup_proposed_finding(
        api, real_batch["id"], ivt_class="DATACENTER", flagged_impressions=100,
        confidence=0.90,
    )

    entries, entry_meta = validate_paginated(
        api.list_list_entries(real_list["id"], ADMIN)
    )
    assert entry_meta["total_count"] == 1, (
        f"expected 1, got {entry_meta['total_count']} entries on the real list"
    )
    _findings, finding_meta = validate_paginated(
        api.list_batch_ivt_findings(real_batch["id"], ADMIN)
    )
    assert finding_meta["total_count"] == 1, (
        f"expected 1, got {finding_meta['total_count']} findings on the real batch"
    )

    missing_list = api.list_list_entries(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing_list, ApiErrorId.ERR_INVENTORY_LIST_NOT_FOUND.value, 404)

    missing_batch = api.list_batch_ivt_findings(NON_EXISTENT_UUID, ADMIN)
    validate_error(missing_batch, ApiErrorId.ERR_MEASUREMENT_BATCH_NOT_FOUND.value, 404)
