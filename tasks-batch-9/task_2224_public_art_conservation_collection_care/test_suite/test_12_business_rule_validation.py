"""Business-rule validation across the conservation register.

Four rules are exercised here: the natural-key uniqueness of accession numbers,
site codes, protocol codes and pool codes; the three-photograph documentation
minimum a survey must meet before it may be submitted; the site footprint
capacity that individually modest works can collectively exhaust; and the two
approval gates that read another row at approval time — the artist-consultation
gate that only bites when a proposal alters a work's appearance, and vendor
eligibility read from the conservator row.
"""

from test_helpers import (
    ApiErrorId,
    SURVEYOR_USER_ID,
    TEST_USERS,
    assert_no_version_change,
    assert_pool_availability_identity,
    make_artist_representative_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    artwork_payload,
    funding_pool_payload,
    maintenance_protocol_payload,
    site_payload,
)
from test_helpers.fixtures import (
    attach_photos,
    create_artist,
    create_artwork,
    create_assessment,
    create_pool,
    create_protocol,
    create_site,
    open_consultation,
    read_artwork,
    read_assessment,
    read_conservator,
    read_consultation,
    read_pool,
    read_proposal,
    read_site,
    reserve_allocation,
    setup_register,
    setup_submitted_proposal,
)

SINGLE_STABILIZATION_LINE = [
    {"labor_hours": 10, "complexity_class": "STABILIZATION", "materials_cents": 0}
]


def test_duplicate_business_code_is_refused_on_every_entity_that_carries_one(api):
    """PRD §2.8: "Uniqueness of `accession_number`, `site_code`, `protocol_code` and `pool_code`, each within its own record type — `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/business_codes_are_unique_within_their_own_entity
    """
    register = setup_register(api)
    protocol = create_protocol(api)
    pool = create_pool(api)
    # Accessioning the register's work already raised the site's
    # `installed_units_used`, so PRD §2.5 has legitimately bumped the site's
    # `version` since it was created.  The baseline for "a refused request
    # changes nothing" is therefore the site as it stands now, not as it stood
    # before the work was accessioned.
    site_before = read_site(api, register["site"]["id"])

    duplicate_accession = api.create_artwork(
        artwork_payload(
            register["artist"]["id"],
            register["site"]["id"],
            title="Different Title",
            material_class="STONE",
            significance_tier="STANDARD",
            footprint_units=1,
            insured_value_cents=1_000,
            acquisition_date="2020-01-01",
            acquisition_document_ref="DEED-X",
        ),
        TEST_USERS["registrar_headers"],
    )
    validate_error(duplicate_accession, ApiErrorId.ERR_DUPLICATE_CODE.value)

    duplicate_site = api.create_site(
        site_payload(
            name="Another Plaza",
            address_ref="7 Other Street",
            exposure_class="PARK",
            capacity_units=5,
        ),
        TEST_USERS["registrar_headers"],
    )
    validate_error(duplicate_site, ApiErrorId.ERR_DUPLICATE_CODE.value)

    duplicate_protocol = api.create_maintenance_protocol(
        maintenance_protocol_payload(material_class="STONE", cycle_days=365),
        TEST_USERS["chief_conservator_headers"],
    )
    validate_error(duplicate_protocol, ApiErrorId.ERR_DUPLICATE_CODE.value)

    duplicate_pool = api.create_funding_pool(
        funding_pool_payload(fiscal_year=2027),
        TEST_USERS["finance_headers"],
    )
    validate_error(duplicate_pool, ApiErrorId.ERR_DUPLICATE_CODE.value)

    # Nothing was inserted by any of the four refusals.
    for lister, headers in (
        (api.list_artworks, TEST_USERS["registrar_headers"]),
        (api.list_sites, TEST_USERS["registrar_headers"]),
        (api.list_maintenance_protocols, TEST_USERS["chief_conservator_headers"]),
        (api.list_funding_pools, TEST_USERS["finance_headers"]),
    ):
        _, meta = validate_paginated(lister(headers))
        assert meta["total_count"] == 1, (
            f"a refused duplicate code must insert nothing; {lister.__name__} "
            f"reports total_count {meta['total_count']}"
        )

    site_after = read_site(api, register["site"]["id"])
    assert site_after["installed_units_used"] == register["artwork"]["footprint_units"]
    assert_no_version_change(site_before, site_after, "site")
    assert_no_version_change(
        register["artwork"], read_artwork(api, register["artwork"]["id"]), "artwork"
    )
    protocol_after = validate_success(
        api.get_maintenance_protocol(
            protocol["id"], TEST_USERS["chief_conservator_headers"]
        )
    )
    assert_no_version_change(protocol, protocol_after, "protocol")
    assert_no_version_change(pool, read_pool(api, pool["id"]), "pool")


def test_one_code_string_is_legal_on_two_different_entity_types(api):
    """PRD §3.3: "A protocol carries a `protocol_code` unique across protocols, the `material_class` it applies to, and a `method` drawn from `WASH`, `WAX`, `GRAFFITI_REMOVAL`, `COATING_RENEWAL` and `INSPECTION`."
    PRD §2.8: "Uniqueness of `accession_number`, `site_code`, `protocol_code` and `pool_code`, each within its own record type — `ERR_DUPLICATE_CODE`."

    Design: Corner/validations/business_codes_are_unique_within_their_own_entity
    """
    protocol = create_protocol(api, protocol_code="WASH-BR")

    shared_string_site = validate_success(
        api.create_site(
            site_payload(
                site_code="WASH-BR",
                name="Confusingly Named Plaza",
                address_ref="8 Other Street",
                exposure_class="PARK",
                capacity_units=5,
            ),
            TEST_USERS["registrar_headers"],
        ),
        201,
    )
    assert shared_string_site["site_code"] == "WASH-BR"

    shared_string_pool = validate_success(
        api.create_funding_pool(
            funding_pool_payload(pool_code="WASH-BR"), TEST_USERS["finance_headers"]
        ),
        201,
    )
    assert shared_string_pool["pool_code"] == "WASH-BR"
    assert protocol["protocol_code"] == "WASH-BR", (
        "the protocol keeps the code it was declared with; uniqueness is per record type"
    )


def test_survey_with_only_two_photographs_cannot_be_submitted(api):
    """PRD §3.2: "Submission requires at least three photographic records; a survey with `photo_count` below three is refused with `ERR_PHOTO_DOCUMENTATION_INSUFFICIENT`."

    Design: Corner/validations/exactly_three_photographs_satisfy_the_documentation_minimum
    """
    register = setup_register(api)
    assessment = create_assessment(api, register["artwork"]["id"])
    attach_photos(api, assessment["id"], view_codes=["OVERALL", "DETAIL"])
    documented = read_assessment(api, assessment["id"])
    assert documented["photo_count"] == 2

    refused = api.submit_condition_assessment(
        assessment["id"], {"surveyor_note": "two views only"}, TEST_USERS["surveyor_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_PHOTO_DOCUMENTATION_INSUFFICIENT.value)

    unmoved = read_assessment(api, assessment["id"])
    assert unmoved["status"] == "DRAFT", "a refused submission leaves the survey in DRAFT"
    assert unmoved["photo_count"] == 2
    assert unmoved["condition_index"] is None
    assert_no_version_change(documented, unmoved, "condition survey")


def test_third_photograph_unlocks_submission_of_the_same_survey(api):
    """PRD §3.2: "Submission requires at least three photographic records; a survey with `photo_count` below three is refused with `ERR_PHOTO_DOCUMENTATION_INSUFFICIENT`."
    PRD §3.2: "Each attachment increases `photo_count` by one and appends its `view_code` to `photo_view_codes`, which holds the distinct view codes in attachment order."
    PRD §3.2: "Every submission stamps `submitted_by_user_id` with the acting `X-User-ID`, restamping it on each round so that the identity recorded is always that of the most recent submitter."

    Design: Corner/validations/exactly_three_photographs_satisfy_the_documentation_minimum
    """
    register = setup_register(api)
    assessment = create_assessment(api, register["artwork"]["id"])
    attach_photos(api, assessment["id"], view_codes=["OVERALL", "DETAIL"])
    validate_error(
        api.submit_condition_assessment(
            assessment["id"], {}, TEST_USERS["surveyor_headers"]
        ),
        ApiErrorId.ERR_PHOTO_DOCUMENTATION_INSUFFICIENT.value,
    )
    assert read_assessment(api, assessment["id"])["status"] == "DRAFT"

    third = validate_success(
        api.add_assessment_photo(
            assessment["id"],
            {"view_code": "BASE", "media_ref": "img/3.jpg"},
            TEST_USERS["surveyor_headers"],
        )
    )
    assert third["photo_count"] == 3
    assert third["photo_view_codes"] == ["OVERALL", "DETAIL", "BASE"]

    submitted = validate_success(
        api.submit_condition_assessment(
            assessment["id"], {}, TEST_USERS["surveyor_headers"]
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == SURVEYOR_USER_ID
    assert submitted["condition_index"] is None, (
        "submission computes no index; the index is computed at finalization"
    )


def test_small_works_collectively_exhaust_the_site_footprint(api):
    """PRD §3.1: "The work's `footprint_units`, at least 1, is what it consumes at the site, and accessioning is refused with `ERR_SITE_CAPACITY_EXCEEDED` when the site's existing `installed_units_used` plus this work's `footprint_units` would exceed the site's `capacity_units`."
    PRD §3.1: "A successful accession sets `custody_status` to `ON_VIEW` and `conservation_status` to `MONITORED`, raises the site's `installed_units_used` by the work's `footprint_units`, and raises the attributed artist's `artwork_count` by one."

    Design: Corner/validations/individually_valid_footprints_collectively_exhaust_the_site
    """
    artist = create_artist(api)
    site = create_site(
        api,
        site_code="PRK-1",
        name="Riverside Park",
        address_ref="40 River Road",
        exposure_class="PARK",
        capacity_units=10,
    )

    create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.040",
        title="Big Arch",
        material_class="STONE",
        significance_tier="SIGNIFICANT",
        footprint_units=6,
    )
    create_artwork(
        api,
        artist["id"],
        site["id"],
        accession_number="2024.041",
        title="Four Benches",
        material_class="STONE",
        significance_tier="STANDARD",
        footprint_units=4,
    )
    filled = read_site(api, site["id"])
    assert filled["installed_units_used"] == 10, (
        "6 plus 4 units fill the plaza to exactly its capacity; the comparison is "
        "less-or-equal, so both accessions are allowed"
    )

    refused = api.create_artwork(
        artwork_payload(
            artist["id"],
            site["id"],
            accession_number="2024.042",
            title="One More Marker",
            material_class="BRONZE",
            significance_tier="STANDARD",
            footprint_units=1,
            insured_value_cents=200_000,
        ),
        TEST_USERS["registrar_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_SITE_CAPACITY_EXCEEDED.value)

    after = read_site(api, site["id"])
    assert after["installed_units_used"] == 10
    assert_no_version_change(filled, after, "site")
    _, meta = validate_paginated(
        api.list_artworks(TEST_USERS["registrar_headers"], params={"site_id": site["id"]})
    )
    assert meta["total_count"] == 2, "the refused work was never accessioned"


def test_altering_proposal_is_blocked_first_for_a_missing_then_a_pending_consultation(api):
    """PRD §3.5: "When the proposal has `alters_appearance` set to true and the target work's `moral_rights_status` is `ACTIVE`, an artist consultation naming this proposal must exist at all — none, and the approval is refused with `ERR_ARTIST_CONSULTATION_REQUIRED`."
    PRD §3.5: "If one exists but is still `PENDING`, the approval is refused with `ERR_ARTIST_CONSULTATION_PENDING`."

    Design: Corner/validations/consultation_requirement_applies_only_when_the_proposal_alters_appearance
    """
    state = setup_submitted_proposal(
        api,
        proposal={"alters_appearance": True},
        lines=SINGLE_STABILIZATION_LINE,
    )
    artwork = read_artwork(api, state["artwork"]["id"])
    assert artwork["moral_rights_status"] == "ACTIVE", (
        "a living artist with no waiver on file leaves moral rights ACTIVE"
    )
    estimate = state["proposal"]["estimate_total_cents"]
    reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=estimate,
        proposal_id=state["proposal"]["id"],
    )

    no_consultation = api.approve_treatment_proposal(
        state["proposal"]["id"], {}, TEST_USERS["manager_headers"]
    )
    validate_error(no_consultation, ApiErrorId.ERR_ARTIST_CONSULTATION_REQUIRED.value)
    after_first = read_proposal(api, state["proposal"]["id"])
    assert after_first["status"] == "SUBMITTED"
    assert after_first["pinned_estimate_total_cents"] is None
    assert_no_version_change(state["proposal"], after_first, "treatment proposal")

    consultation = open_consultation(
        api,
        state["artwork"]["id"],
        state["artist"]["id"],
        subject="TREATMENT",
        proposal_id=state["proposal"]["id"],
    )
    assert consultation["status"] == "PENDING"

    still_pending = api.approve_treatment_proposal(
        state["proposal"]["id"], {}, TEST_USERS["manager_headers"]
    )
    validate_error(still_pending, ApiErrorId.ERR_ARTIST_CONSULTATION_PENDING.value)

    after_second = read_proposal(api, state["proposal"]["id"])
    assert after_second["status"] == "SUBMITTED"
    assert after_second["pinned_estimate_total_cents"] is None
    assert_no_version_change(after_first, after_second, "treatment proposal")
    assert read_conservator(api, state["conservator"]["id"])["active_engagement_count"] == 0
    assert_pool_availability_identity(read_pool(api, state["pool"]["id"]), estimate)


def test_concurred_consultation_clears_the_approval_gate_for_an_altering_proposal(api):
    """PRD §3.5: "Only `CONCURRED` or `LAPSED` clears the gate."
    PRD §3.6: "A `CONCUR` moves the row `PENDING → CONCURRED` and an `OBJECT` moves it `PENDING → OBJECTED`; both stamp `responded_at` from the logical clock, and both require the logical clock to be strictly before `due_at`."
    PRD §3.5: "On success, `pinned_estimate_total_cents` freezes at the proposal's `estimate_total_cents` at that instant, which later becomes the basis of a restoration insurance claim, and `approved_by_user_id` records the acting user."

    Design: Corner/validations/consultation_requirement_applies_only_when_the_proposal_alters_appearance
    """
    state = setup_submitted_proposal(
        api,
        proposal={"alters_appearance": True},
        lines=SINGLE_STABILIZATION_LINE,
    )
    estimate = state["proposal"]["estimate_total_cents"]
    reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=estimate,
        proposal_id=state["proposal"]["id"],
    )
    consultation = open_consultation(
        api,
        state["artwork"]["id"],
        state["artist"]["id"],
        subject="TREATMENT",
        proposal_id=state["proposal"]["id"],
    )

    answered = validate_success(
        api.respond_to_consultation(
            consultation["id"],
            {"response": "CONCUR", "response_note": "tone is acceptable"},
            make_artist_representative_headers(state["artist"]["id"]),
        )
    )
    assert answered["status"] == "CONCURRED"
    assert answered["responded_at"] is not None
    assert read_consultation(api, consultation["id"])["status"] == "CONCURRED"

    approved = validate_success(
        api.approve_treatment_proposal(
            state["proposal"]["id"],
            {"approval_note": "artist concurred"},
            TEST_USERS["manager_headers"],
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["pinned_estimate_total_cents"] == estimate
    assert read_conservator(api, state["conservator"]["id"])["active_engagement_count"] == 1
    assert_pool_availability_identity(read_pool(api, state["pool"]["id"]), estimate)


def test_conservator_without_the_work_s_material_specialty_cannot_be_approved(api):
    """PRD §3.5: "The engaged conservator's `status` must be `ACTIVE`, their `insurance_expires_on` must fall on or after the date of `engagement_end`, and the work's `material_class` must be a member of the conservator's `material_specialties`."
    PRD §3.5: "Any of those three failing yields `ERR_CONSERVATOR_NOT_ELIGIBLE`."

    Design: Corner/validations/conservator_eligibility_is_read_from_the_conservator_row_at_approval_time
    """
    state = setup_submitted_proposal(
        api,
        conservator={"firm_name": "Stoneworks Only", "material_specialties": ["STONE"]},
        lines=SINGLE_STABILIZATION_LINE,
    )
    assert read_artwork(api, state["artwork"]["id"])["material_class"] == "BRONZE"
    assert state["proposal"]["status"] == "SUBMITTED", (
        "drafting and submitting the proposal drew no complaint; eligibility is read "
        "at approval time"
    )
    estimate = state["proposal"]["estimate_total_cents"]
    reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=estimate,
        proposal_id=state["proposal"]["id"],
    )

    refused = api.approve_treatment_proposal(
        state["proposal"]["id"], {}, TEST_USERS["manager_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_CONSERVATOR_NOT_ELIGIBLE.value)

    after = read_proposal(api, state["proposal"]["id"])
    assert after["status"] == "SUBMITTED"
    assert after["pinned_estimate_total_cents"] is None
    assert_no_version_change(state["proposal"], after, "treatment proposal")
    assert read_conservator(api, state["conservator"]["id"])["active_engagement_count"] == 0
    assert_pool_availability_identity(read_pool(api, state["pool"]["id"]), estimate)


def test_insurance_lapsing_one_day_before_engagement_end_blocks_approval(api):
    """PRD §3.5: "The engaged conservator's `status` must be `ACTIVE`, their `insurance_expires_on` must fall on or after the date of `engagement_end`, and the work's `material_class` must be a member of the conservator's `material_specialties`."
    PRD §3.5: "Any of those three failing yields `ERR_CONSERVATOR_NOT_ELIGIBLE`."

    Design: Corner/validations/conservator_eligibility_is_read_from_the_conservator_row_at_approval_time
    """
    state = setup_submitted_proposal(
        api,
        conservator={
            "firm_name": "Lapsing Cover",
            "material_specialties": ["BRONZE"],
            "insurance_expires_on": "2026-09-04",
        },
        proposal={
            "engagement_start": "2026-09-01T00:00:00Z",
            "engagement_end": "2026-09-05T00:00:00Z",
        },
        lines=SINGLE_STABILIZATION_LINE,
    )
    conservator = read_conservator(api, state["conservator"]["id"])
    assert conservator["status"] == "ACTIVE"
    assert conservator["insurance_expires_on"] == "2026-09-04"
    assert state["proposal"]["engagement_end"].startswith("2026-09-05"), (
        "cover lapses one calendar day before the engagement ends"
    )
    estimate = state["proposal"]["estimate_total_cents"]
    reserve_allocation(
        api,
        state["pool"]["id"],
        purpose="TREATMENT",
        amount_cents=estimate,
        proposal_id=state["proposal"]["id"],
    )

    refused = api.approve_treatment_proposal(
        state["proposal"]["id"], {}, TEST_USERS["manager_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_CONSERVATOR_NOT_ELIGIBLE.value)

    after = read_proposal(api, state["proposal"]["id"])
    assert after["status"] == "SUBMITTED"
    assert after["pinned_estimate_total_cents"] is None
    assert_no_version_change(state["proposal"], after, "treatment proposal")
    assert read_conservator(api, state["conservator"]["id"])["active_engagement_count"] == 0
    assert_pool_availability_identity(read_pool(api, state["pool"]["id"]), estimate)
