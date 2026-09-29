"""Who may act: identity headers, the nine peer roles, the funding-read
exception, an artist representative acting only for their own work, and the
segregation of duties that keeps a surveyor from signing off their own survey.
"""

from test_helpers import (
    ApiErrorId,
    assert_no_version_change,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import artwork_payload
from test_helpers.fixtures import (
    create_artist,
    create_conservator,
    create_pool,
    create_site,
    create_artwork,
    open_consultation,
    read_artwork,
    read_assessment,
    read_consultation,
    read_pool,
    setup_assessment_submitted,
    setup_register,
)
from test_helpers.test_users import (
    CHIEF_CONSERVATOR_USER_ID,
    REGISTRAR_USER_ID,
    SECOND_SURVEYOR_USER_ID,
    SURVEYOR_USER_ID,
    TEST_USERS,
    make_artist_representative_headers,
    make_chief_conservator_headers,
    make_conservator_vendor_headers,
    make_headers,
    make_surveyor_headers,
)


def test_reading_a_work_without_a_role_header_is_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act."
    PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the nine roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "All nine roles may read artists, sites, artworks, protocols, conservators, condition surveys, maintenance visits, treatment proposals, consultations, notices, deaccession cases and damage incidents."

    A register read that every one of the nine roles is entitled to make still
    fails with 401 when the caller declares no capacity at all.

    Design: Corner/rbac/requests_with_no_role_header_are_unauthenticated
    """
    register = setup_register(api)
    artwork = register["artwork"]

    # An identifier without a declared capacity: the role header is absent.
    headers_without_role = {
        "X-User-ID": REGISTRAR_USER_ID,
        "Content-Type": "application/json",
    }
    validate_error(
        api.get_artwork(artwork["id"], headers_without_role),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    after = read_artwork(api, artwork["id"])
    assert_no_version_change(artwork, after, "artwork")
    assert after["custody_status"] == "ON_VIEW"
    assert after["conservation_status"] == "MONITORED"


def test_an_anonymous_accession_attempt_creates_no_artwork(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the nine roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §3.1: "Accessioning is the `CollectionsRegistrar`'s exclusive act."

    Authentication is decided before anything else, so a write carrying neither
    header is refused with 401 and leaves the collection exactly as it was.

    Design: Corner/rbac/requests_with_no_role_header_are_unauthenticated
    """
    register = setup_register(api)

    anonymous_headers = {"Content-Type": "application/json"}
    validate_error(
        api.create_artwork(
            artwork_payload(
                register["artist"]["id"],
                register["site"]["id"],
                accession_number="2024.099",
                title="Anonymous Gift",
                material_class="STONE",
                significance_tier="STANDARD",
                footprint_units=1,
                insured_value_cents=1000,
            ),
            anonymous_headers,
        ),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    artworks, meta = validate_paginated(
        api.list_artworks(TEST_USERS["registrar_headers"])
    )
    assert meta["total_count"] == 1, "the anonymous write must have created nothing"
    assert [row["id"] for row in artworks] == [register["artwork"]["id"]]

    after = read_artwork(api, register["artwork"]["id"])
    assert_no_version_change(register["artwork"], after, "artwork")


def test_an_unrecognised_role_string_is_unauthenticated_not_unauthorized(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of the nine roles below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.1: "If the headers are well formed but the declared role is not among those authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    "Auditor" is not one of the nine declared roles, so the request never
    reaches the endpoint's authorization check: it is 401, not 403.

    Design: Corner/rbac/requests_with_no_role_header_are_unauthenticated
    """
    register = setup_register(api)
    artwork = register["artwork"]

    validate_error(
        api.get_artwork(artwork["id"], make_headers("aud-1", "Auditor")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
    )

    after = read_artwork(api, artwork["id"])
    assert_no_version_change(artwork, after, "artwork")


def test_a_condition_surveyor_may_not_finalize_a_submitted_survey(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among those authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §2.1: "`ConditionSurveyor` — performs condition surveys and attaches photographic documentation; may submit a survey but never finalize one."
    PRD §3.2: "Finalization is the `ChiefConservator`'s act, carries an optional `finalization_note`, and moves the survey `SUBMITTED → FINALIZED`."

    A surveyor who did not submit this survey — so no segregation question
    arises — is still refused on the role alone, and the survey does not move.

    Design: Corner/rbac/role_exclusive_operations_are_unauthorized_for_peer_roles
    """
    register = setup_register(api)
    assessment = setup_assessment_submitted(api, register["artwork"]["id"])
    assert assessment["status"] == "SUBMITTED"

    validate_error(
        api.finalize_condition_assessment(
            assessment["id"],
            {"finalization_note": "signing this off myself"},
            make_surveyor_headers(SECOND_SURVEYOR_USER_ID),
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    after = read_assessment(api, assessment["id"])
    assert_no_version_change(assessment, after, "condition survey")
    assert after["status"] == "SUBMITTED"
    assert after["condition_index"] is None
    assert after.get("finalized_by_user_id") is None

    artwork_after = read_artwork(api, register["artwork"]["id"])
    assert artwork_after["condition_index"] is None
    assert artwork_after["conservation_status"] == "MONITORED"


def test_a_public_art_manager_may_read_a_funding_pool_but_not_open_one(api):
    """PRD §2.1: "If the headers are well formed but the declared role is not among those authorized for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.10: "Conservation is paid for from two kinds of pool, both opened by the `FinanceOfficer`."
    PRD §2.1: "Funding pools and funding allocations are the exception: only `FinanceOfficer`, `PublicArtManager` and `ChiefConservator` may read them, and any other role attempting a funding read receives `ERR_UNAUTHORIZED`."

    The nine roles are peers with disjoint exclusive operations: the programme
    manager is one of the three roles allowed to inspect the money, yet opening
    a pool remains the finance officer's act alone.

    Design: Corner/rbac/role_exclusive_operations_are_unauthorized_for_peer_roles
    """
    pool = create_pool(api)

    validate_error(
        api.create_funding_pool(
            {
                "pool_code": "PFA-2026",
                "pool_type": "PERCENT_FOR_ART",
                "fiscal_year": 2026,
                "set_aside_cents": 100_000,
            },
            TEST_USERS["manager_headers"],
        ),
        ApiErrorId.ERR_UNAUTHORIZED.value,
    )

    pools, meta = validate_paginated(
        api.list_funding_pools(TEST_USERS["finance_headers"])
    )
    assert meta["total_count"] == 1, "the manager's pool must not have been opened"
    assert [row["id"] for row in pools] == [pool["id"]]

    # The manager is nonetheless one of the three roles that may read the money.
    manager_view = validate_success(
        api.get_funding_pool(pool["id"], TEST_USERS["manager_headers"])
    )
    assert manager_view["id"] == pool["id"]
    assert_no_version_change(pool, manager_view, "funding pool")


def test_roles_outside_the_three_named_cannot_read_the_money(api):
    """PRD §2.1: "Funding pools and funding allocations are the exception: only `FinanceOfficer`, `PublicArtManager` and `ChiefConservator` may read them, and any other role attempting a funding read receives `ERR_UNAUTHORIZED`."
    PRD §2.1: "All nine roles may read artists, sites, artworks, protocols, conservators, condition surveys, maintenance visits, treatment proposals, consultations, notices, deaccession cases and damage incidents."

    Read access is broad everywhere else, so the funding rows are the one place
    where a peer role — including the two entity-backed ones acting as
    themselves — is turned away from a plain read.

    Design: Corner/rbac/role_exclusive_operations_are_unauthorized_for_peer_roles
    """
    pool = create_pool(api)
    artist = create_artist(api)
    conservator = create_conservator(api)

    barred_headers = [
        make_headers("reg-9", "CollectionsRegistrar"),
        make_headers("surv-9", "ConditionSurveyor"),
        make_headers("crew-9", "MaintenanceCrew"),
        make_headers("acm-9", "ArtCommissionMember"),
        make_artist_representative_headers(artist["id"]),
        make_conservator_vendor_headers(conservator["id"]),
    ]
    for headers in barred_headers:
        validate_error(
            api.get_funding_pool(pool["id"], headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )
        validate_error(
            api.list_funding_pools(headers),
            ApiErrorId.ERR_UNAUTHORIZED.value,
        )

    # The three named roles read the same row without trouble.
    for headers in (
        TEST_USERS["finance_headers"],
        TEST_USERS["manager_headers"],
        TEST_USERS["chief_conservator_headers"],
    ):
        seen = validate_success(api.get_funding_pool(pool["id"], headers))
        assert seen["id"] == pool["id"]

    assert_no_version_change(pool, read_pool(api, pool["id"]), "funding pool")


def test_an_artist_representative_cannot_answer_another_artists_consultation(api):
    """PRD §2.1: "When `X-User-Role` is `ArtistRepresentative`, `X-User-ID` is the `id` of the acting `Artist`; ownership checks on any resource that references an `Artist` compare the resource's `artist_id` to `X-User-ID`."
    PRD §2.1: "A mismatch on either is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."
    PRD §3.6: "The artist answers through their representative, and only for their own work: the acting `X-User-ID` must equal the consultation's `artist_id`."
    PRD §3.6: "A `CONCUR` moves the row `PENDING → CONCURRED` and an `OBJECT` moves it `PENDING → OBJECTED`; both stamp `responded_at` from the logical clock, and both require the logical clock to be strictly before `due_at`."

    Holding the role is not enough: a second, really-registered artist objecting
    to a consultation addressed to the first is refused, and their objection is
    never recorded — the consultation is still answerable by its own artist.

    Design: Corner/rbac/an_artist_representative_cannot_answer_another_artists_consultation
    """
    artist_a = create_artist(api)
    artist_b = create_artist(api, full_name="Bo Reyes", contact_email="bo@example.gov")
    site = create_site(api)
    artwork = create_artwork(api, artist_a["id"], site["id"])
    consultation = open_consultation(
        api, artwork["id"], artist_a["id"], subject="RELOCATION"
    )
    assert consultation["status"] == "PENDING"

    validate_error(
        api.respond_to_consultation(
            consultation["id"],
            {"response": "OBJECT", "response_note": "not my work, but I object"},
            make_artist_representative_headers(artist_b["id"]),
        ),
        ApiErrorId.ERR_NOT_RESOURCE_OWNER.value,
    )

    after = read_consultation(api, consultation["id"])
    assert_no_version_change(consultation, after, "artist consultation")
    assert after["status"] == "PENDING"
    assert after.get("responded_at") is None

    # The artist named on the row answers it, inside the response window.
    answered = validate_success(
        api.respond_to_consultation(
            consultation["id"],
            {"response": "CONCUR", "response_note": "acceptable to me"},
            make_artist_representative_headers(artist_a["id"]),
        )
    )
    assert answered["status"] == "CONCURRED"
    assert answered["responded_at"].startswith("2026-08-01T00:00:00")
    assert read_artwork(api, artwork["id"])["moral_rights_status"] == "ACTIVE"


def test_the_submitter_of_a_survey_is_barred_from_finalizing_it(api):
    """PRD §3.2: "Every submission stamps `submitted_by_user_id` with the acting `X-User-ID`, restamping it on each round so that the identity recorded is always that of the most recent submitter."
    PRD §3.2: "It is barred to the user who submitted it: when the acting `X-User-ID` equals `submitted_by_user_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES`."

    The role is right and the state is right — only the identity is wrong: the
    very user who submitted the survey comes back wearing the ChiefConservator
    role and is refused, leaving the survey and the work untouched.

    Design: Corner/rbac/the_submitter_of_a_survey_is_barred_from_finalizing_it
    """
    register = setup_register(api)
    assessment = setup_assessment_submitted(
        api,
        register["artwork"]["id"],
        surface_score=3,
        structural_score=3,
        coating_score=3,
        mount_score=2,
        graffiti_score=2,
    )
    assert assessment["submitted_by_user_id"] == SURVEYOR_USER_ID

    validate_error(
        api.finalize_condition_assessment(
            assessment["id"],
            {"finalization_note": "signing off on my own survey"},
            make_chief_conservator_headers(SURVEYOR_USER_ID),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    after = read_assessment(api, assessment["id"])
    assert_no_version_change(assessment, after, "condition survey")
    assert after["status"] == "SUBMITTED"
    assert after["condition_index"] is None
    assert after["recommendation"] == "NONE"
    assert after.get("finalized_by_user_id") is None

    artwork_after = read_artwork(api, register["artwork"]["id"])
    assert artwork_after["condition_index"] is None
    assert artwork_after["conservation_status"] == "MONITORED"
    assert artwork_after["priority_basis"] == "NONE"


def test_the_submitter_may_send_a_survey_back_and_another_chief_finalizes_it(api):
    """PRD §3.2: "Review belongs to the `ChiefConservator`, who may send a `SUBMITTED` survey back with a mandatory `reviewer_note`, moving it `SUBMITTED → REVISION_REQUESTED` and increasing `revision_rounds` by one."
    PRD §3.2: "It is barred to the user who submitted it: when the acting `X-User-ID` equals `submitted_by_user_id`, the request is refused with `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "On success `finalized_by_user_id` records the acting user."
    PRD §3.2: "The index is then 100, less 25 times the weighted defect figure, less the penalty, rounded half up to one decimal place and finally floored at 0.0."

    The bar is scoped to finalization: the submitting user may still return the
    survey for revision, and a different chief conservator then finalizes the
    resubmission — a BRONZE work on an URBAN site scoring 3/3/3/2/2 lands at
    100 - 25 x 2.75 - 1.5 = 29.8.

    Design: Corner/rbac/the_submitter_of_a_survey_is_barred_from_finalizing_it
    """
    register = setup_register(api)
    assessment = setup_assessment_submitted(
        api,
        register["artwork"]["id"],
        surface_score=3,
        structural_score=3,
        coating_score=3,
        mount_score=2,
        graffiti_score=2,
    )

    returned = validate_success(
        api.request_assessment_revision(
            assessment["id"],
            {"reviewer_note": "clarify the mount score"},
            make_chief_conservator_headers(SURVEYOR_USER_ID),
        )
    )
    assert returned["status"] == "REVISION_REQUESTED"
    assert returned["revision_rounds"] == 1

    resubmitted = validate_success(
        api.submit_condition_assessment(
            assessment["id"],
            {"surveyor_note": "mount score confirmed"},
            TEST_USERS["surveyor_headers"],
        )
    )
    assert resubmitted["status"] == "SUBMITTED"

    finalized = validate_success(
        api.finalize_condition_assessment(
            assessment["id"], {}, make_chief_conservator_headers(CHIEF_CONSERVATOR_USER_ID)
        )
    )
    assert finalized["status"] == "FINALIZED"
    assert finalized["finalized_by_user_id"] == CHIEF_CONSERVATOR_USER_ID
    assert finalized["submitted_by_user_id"] == SURVEYOR_USER_ID
    assert finalized["condition_index"] == 29.8
    assert finalized["recommendation"] == "URGENT"
    assert finalized["revision_rounds"] == 1
