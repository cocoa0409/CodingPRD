"""Program, applicant, application and faculty registry contracts.

Covers the declared input echo, the optional-input defaults, the system-minted
fields, the type and enum constraints, the not-found ordering, the list
envelope, the computed screening figures, and the interview-assignment
junction that joins a slot to its panel.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_applicant,
    assert_application,
    assert_interview_assignment,
    assert_program,
    assert_provisional_score,
    assert_system_fields,
    find_by,
)
from test_helpers.constants import (
    PATHOLOGY_PROGRAM_CODE,
    PATHOLOGY_PROGRAM_NAME,
    PATHOLOGY_SPECIALTY,
    PROGRAM_CODE,
    PROGRAM_NAME,
    PROGRAM_SPECIALTY,
)
from test_helpers.factories import (
    OMIT,
    build_applicant_payload,
    build_application_payload,
    build_application_review_payload,
    build_interview_assignment_payload,
    build_minimal_program_payload,
    build_program_payload,
    build_second_applicant_payload,
)
from test_helpers.fixtures import (
    SeasonBuilder,
    setup_program,
    setup_reviewed_application,
    setup_screened_application,
    setup_staffed_program,
)
from test_helpers.types import (
    AssignmentStatus,
    PanelRole,
    ScreeningStatus,
    SeasonPhase,
)

# ======================================================================
# Program registration: echo, defaults, read-back, not found
# ======================================================================


def test_program_create_echoes_every_declared_input_and_initialises_its_counters(api):
    """Registering a program echoes all eight declared inputs and initialises every counter.

    A naive implementation stores the inputs but leaves `season_phase` and the
    derived counters absent from the create response, expecting a later GET to
    materialise them. The registration narrative writes them at creation time.

    PRD 3.1: "An `NrmpAdmin` registers a participating program by supplying its display `name` (non-empty, at most 200 characters), its NRMP-assigned `nrmp_program_code` (non-empty and unique across every program on the platform), its ACGME `specialty_code` abbreviation such as IM, EM or PEDS (non-empty), and `quota_positions` — the number of PGY-1 positions the program is certified to fill, which must be at least 1."
    PRD 3.1: "The program materialises in `PRE_SEASON` with `matched_count` at 0, `unfilled_positions` equal to `quota_positions`, `invited_count` at 0, `soap_offer_budget` at 0, and `rank_list_certified_at` null."

    Design: Corner/entities/program_create_with_every_declared_field_returns_201_and_echoes_them
    """
    builder = SeasonBuilder()

    response = api.create_program(
        build_program_payload(quota_positions=3), builder.admin
    )

    data = validate_success(response, 201)
    assert_program(data)
    assert data["name"] == PROGRAM_NAME, "Program.name must echo the supplied name"
    assert (
        data["nrmp_program_code"] == PROGRAM_CODE
    ), "Program.nrmp_program_code must echo the supplied NRMP code"
    assert (
        data["specialty_code"] == PROGRAM_SPECIALTY
    ), "Program.specialty_code must echo the supplied specialty"
    assert data["quota_positions"] == 3, "Program.quota_positions must echo the input 3"
    assert (
        data["visa_sponsorship_allowed"] is True
    ), "Program.visa_sponsorship_allowed must echo the supplied true"
    assert (
        data["soap_participating"] is True
    ), "Program.soap_participating must echo the supplied true"
    assert (
        data["min_step2_score"] == 220
    ), "Program.min_step2_score must echo the supplied 220"
    assert data["img_accepted"] is True, "Program.img_accepted must echo the supplied true"
    assert (
        data["season_phase"] == SeasonPhase.PRE_SEASON
    ), f"a new program must materialise in PRE_SEASON, got {data['season_phase']}"
    assert data["matched_count"] == 0, "Program.matched_count must materialise at 0"
    assert data["invited_count"] == 0, "Program.invited_count must materialise at 0"
    assert (
        data["soap_offer_budget"] == 0
    ), "Program.soap_offer_budget must materialise at 0"
    assert (
        data["rank_list_certified_at"] is None
    ), "Program.rank_list_certified_at must materialise null"
    assert isinstance(data["id"], str) and data["id"], "Program.id must be a minted string"


def test_program_create_omitting_the_optional_switches_applies_the_declared_defaults(api):
    """Supplying only the four required inputs yields the four declared defaults.

    An implementation that stores null, or omits the key entirely, for an input
    the client never sent fails: each optional switch has a declared default.

    PRD 3.1: "Four screening and policy switches are optional at registration and carry defaults when omitted: `visa_sponsorship_allowed` defaults to false, `soap_participating` defaults to false, `min_step2_score` defaults to 220 and must lie between 1 and 300 inclusive, and `img_accepted` defaults to false."
    PRD 3.1: "The program materialises in `PRE_SEASON` with `matched_count` at 0, `unfilled_positions` equal to `quota_positions`, `invited_count` at 0, `soap_offer_budget` at 0, and `rank_list_certified_at` null."

    Design: Corner/entities/program_create_omitting_the_optional_inputs_applies_the_declared_defaults
    """
    builder = SeasonBuilder()

    response = api.create_program(build_minimal_program_payload(), builder.admin)

    data = validate_success(response, 201)
    assert data["name"] == PATHOLOGY_PROGRAM_NAME, "Program.name must echo the input"
    assert (
        data["nrmp_program_code"] == PATHOLOGY_PROGRAM_CODE
    ), "Program.nrmp_program_code must echo the input"
    assert (
        data["specialty_code"] == PATHOLOGY_SPECIALTY
    ), "Program.specialty_code must echo the input"
    assert (
        data["min_step2_score"] == 220
    ), f"min_step2_score must default to 220, got {data['min_step2_score']}"
    assert (
        data["visa_sponsorship_allowed"] is False
    ), "visa_sponsorship_allowed must default to false"
    assert (
        data["soap_participating"] is False
    ), "soap_participating must default to false"
    assert data["img_accepted"] is False, "img_accepted must default to false"
    assert (
        data["season_phase"] == SeasonPhase.PRE_SEASON
    ), "a new program must materialise in PRE_SEASON"
    assert data["matched_count"] == 0, "Program.matched_count must materialise at 0"


def test_program_read_back_returns_the_stored_representation(api):
    """Reading a program back returns the same id and the same stored field values.

    The row must be persisted, not synthesised per request: the read-back has
    to agree with the create response on every declared field.

    PRD 3.1: "An `NrmpAdmin` registers a participating program by supplying its display `name` (non-empty, at most 200 characters), its NRMP-assigned `nrmp_program_code` (non-empty and unique across every program on the platform), its ACGME `specialty_code` abbreviation such as IM, EM or PEDS (non-empty), and `quota_positions` — the number of PGY-1 positions the program is certified to fill, which must be at least 1."
    PRD 2.4: "A newly registered program begins in `PRE_SEASON`."

    Design: Corner/entities/program_get_by_id_returns_the_stored_representation
    """
    builder = setup_program(quota_positions=3)
    program_id = builder.id("program")

    response = api.get_program(program_id, builder.admin)

    data = validate_success(response, 200)
    assert data["id"] == program_id, "the read-back must carry the created program's id"
    assert (
        data["nrmp_program_code"] == PROGRAM_CODE
    ), "the stored nrmp_program_code must survive the read-back"
    assert (
        data["quota_positions"] == 3
    ), f"the stored quota_positions must survive the read-back, got {data['quota_positions']}"
    assert (
        data["season_phase"] == SeasonPhase.PRE_SEASON
    ), "the stored program must still read PRE_SEASON"


def test_program_read_with_an_unknown_id_is_not_found(api):
    """A syntactically valid but unknown program id is refused as not found.

    The existence check runs ahead of every body-shape check, so an unknown
    path id must never surface as a validation error, and the store must be
    left untouched.

    PRD 2.12: "Every resource named in the URL path exists, checked left to right; then every foreign key supplied in the request body exists."
    PRD 2.12: "Every such failure carries the single code `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/program_get_with_an_unknown_id_returns_not_found
    """
    builder = setup_program(quota_positions=2)
    program_id = builder.id("program")

    response = api.get_program(NON_EXISTENT_UUID, builder.admin)

    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    surviving = validate_success(api.get_program(program_id, builder.admin), 200)
    assert (
        surviving["id"] == program_id
    ), "the unrelated program must be unaffected and still readable"


# ======================================================================
# Applicant registry: system fields, constraints, list envelope
# ======================================================================


def test_applicant_create_mints_the_system_fields_the_client_cannot_supply(api):
    """Every applicant create mints id, created_at, updated_at and version server-side.

    Two creates of the same shape must not collide on `id`, and `version` must
    be an integer starting at 1 rather than a string or a null placeholder.

    PRD 2.6: "No resource is exempt; there is no immutable sub-resource in this domain that omits `updated_at` or `version`."
    PRD 2.6: "`version` (integer): starts at 1 on creation and increments by one on every mutation."

    Design: Corner/entities/applicant_create_mints_the_system_fields_the_client_cannot_supply
    """
    builder = SeasonBuilder()
    builder.add_applicant("cand1")
    first_id = builder.id("cand1")

    response = api.create_applicant(build_second_applicant_payload(), builder.admin)

    data = validate_success(response, 201)
    assert_applicant(data)
    assert_system_fields(data, "Applicant")
    assert isinstance(
        data["version"], int
    ), f"Applicant.version must be an integer, got {type(data['version']).__name__}"
    assert (
        data["id"] != first_id
    ), "two applicant creates must mint two different ids, not reuse one"


def test_applicant_create_missing_the_required_step2_score_is_rejected(api):
    """Omitting the required step2_score is a request-shape violation with no row written.

    `step2_score` has no declared default, so a create without it must fail the
    shape check outright rather than storing a partial applicant row.

    PRD 3.1: "Each `Applicant` carries an `eras_id` (non-empty and unique across the registry), a non-empty legal `full_name`, a `medical_school_type` that is one of `US_MD`, `US_DO` or `IMG`, a `visa_status` that is one of `US_CITIZEN`, `PERMANENT_RESIDENT`, `NEEDS_J1` or `NEEDS_H1B`, and a three-digit USMLE Step 2 CK `step2_score` between 1 and 300 inclusive."
    PRD 2.12: "Every field the endpoint requires is present, every field has its declared type, every enum-valued field holds a declared member, and every numeric field lies inside its declared range — including `limit` between 1 and 100 inclusive and `offset` at 0 or above on list endpoints."

    Design: Corner/entities/applicant_create_missing_the_required_step2_score_is_rejected
    """
    builder = SeasonBuilder()

    response = api.create_applicant(
        build_applicant_payload(
            step2_score=OMIT, pipeline_program_alum=OMIT, self_identified_group=OMIT
        ),
        builder.admin,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(api.list_applicants(builder.admin))
    assert (
        meta["total_count"] == 0
    ), f"no partial applicant row may be written, found {meta['total_count']}"


def test_applicant_create_with_an_undeclared_enum_member_is_rejected(api):
    """A medical_school_type outside the declared enum is refused and stores nothing.

    The declared members are US_MD, US_DO and IMG; anything else is an
    enum-membership breach, not a free-text value to be persisted.

    PRD 3.1: "Each `Applicant` carries an `eras_id` (non-empty and unique across the registry), a non-empty legal `full_name`, a `medical_school_type` that is one of `US_MD`, `US_DO` or `IMG`, a `visa_status` that is one of `US_CITIZEN`, `PERMANENT_RESIDENT`, `NEEDS_J1` or `NEEDS_H1B`, and a three-digit USMLE Step 2 CK `step2_score` between 1 and 300 inclusive."
    PRD 2.12: "Every field the endpoint requires is present, every field has its declared type, every enum-valued field holds a declared member, and every numeric field lies inside its declared range — including `limit` between 1 and 100 inclusive and `offset` at 0 or above on list endpoints."

    Design: Corner/entities/applicant_create_with_an_undeclared_enum_member_is_rejected
    """
    builder = SeasonBuilder()

    response = api.create_applicant(
        build_applicant_payload(
            medical_school_type="CARIBBEAN_MD",
            pipeline_program_alum=OMIT,
            self_identified_group=OMIT,
        ),
        builder.admin,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(api.list_applicants(builder.admin))
    assert (
        meta["total_count"] == 0
    ), f"an undeclared enum member must store no applicant row, found {meta['total_count']}"


def test_applicant_create_above_the_declared_step2_range_is_rejected(api):
    """A step2_score of 301 breaches the declared 1 to 300 range and stores nothing.

    The field is present and of the right type, so only an explicit range check
    catches it — a distinct failure mode from enum membership.

    PRD 3.1: "Each `Applicant` carries an `eras_id` (non-empty and unique across the registry), a non-empty legal `full_name`, a `medical_school_type` that is one of `US_MD`, `US_DO` or `IMG`, a `visa_status` that is one of `US_CITIZEN`, `PERMANENT_RESIDENT`, `NEEDS_J1` or `NEEDS_H1B`, and a three-digit USMLE Step 2 CK `step2_score` between 1 and 300 inclusive."
    PRD 2.12: "Every field the endpoint requires is present, every field has its declared type, every enum-valued field holds a declared member, and every numeric field lies inside its declared range — including `limit` between 1 and 100 inclusive and `offset` at 0 or above on list endpoints."

    Design: Corner/entities/applicant_create_above_the_declared_step2_range_is_rejected
    """
    builder = SeasonBuilder()

    response = api.create_applicant(
        build_applicant_payload(
            step2_score=301, pipeline_program_alum=OMIT, self_identified_group=OMIT
        ),
        builder.admin,
    )

    validate_error(response, ApiErrorId.ERR_VALIDATION)
    _, meta = validate_paginated(api.list_applicants(builder.admin))
    assert (
        meta["total_count"] == 0
    ), f"an out-of-range step2_score must store no applicant row, found {meta['total_count']}"


def test_applicant_list_with_limit_one_reports_the_whole_matching_set(api):
    """With two applicants and limit 1 the envelope reports total_count 2 and has_more true.

    `total_count` must count the whole matching set rather than the returned
    page, and `has_more` must be derived from the window position, so page two
    flips it to false while `total_count` stays at 2.

    PRD 2.3: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope."
    PRD 2.3: "`total_count` counts all rows matching the filter before the window is applied, and `has_more` is true when rows remain beyond the current window."

    Design: Corner/entities/applicant_list_with_limit_one_reports_total_count_two_and_has_more_true
    """
    builder = SeasonBuilder()
    builder.add_applicant("cand1")
    builder.add_applicant("cand2")

    rows, meta = validate_paginated(
        api.list_applicants(builder.admin, params={"limit": 1, "offset": 0})
    )

    assert len(rows) == 1, f"limit 1 must return exactly one row, got {len(rows)}"
    assert meta["limit"] == 1, f"meta.limit must echo the requested 1, got {meta['limit']}"
    assert (
        meta["offset"] == 0
    ), f"meta.offset must echo the requested 0, got {meta['offset']}"
    assert (
        meta["total_count"] == 2
    ), f"meta.total_count must count both applicants, got {meta['total_count']}"
    assert (
        meta["has_more"] is True
    ), "meta.has_more must be true while a row remains beyond the first window"

    page_two, meta_two = validate_paginated(
        api.list_applicants(builder.admin, params={"limit": 1, "offset": 1})
    )
    assert len(page_two) == 1, "the second window must also return exactly one row"
    assert (
        meta_two["total_count"] == 2
    ), f"meta.total_count must stay at 2 on page two, got {meta_two['total_count']}"
    assert (
        meta_two["has_more"] is False
    ), "meta.has_more must be false once no row remains beyond the window"


# ======================================================================
# Application: computed screening figures and body foreign keys
# ======================================================================


def test_application_review_count_and_provisional_score_are_computed_from_the_reviews(
    api,
):
    """A second review drives review_count to 2 and recomputes the provisional score.

    Both figures are computed, never client-supplied: two (30, 20, 20) reviews
    give a base of 0.45*30 + 0.30*20 + 0.25*20 = 24.50, the paper dimension is
    already UNDER_REVIEW, and final_screen_score stays null until screening.

    PRD 3.2: "Each individual review contributes a raw figure equal to its `academic_points` multiplied by 0.45, plus its `experience_points` multiplied by 0.30, plus its `holistic_points` multiplied by 0.25."
    PRD 3.2: "`provisional_screen_score` is **Variant A**: the base alone, rounded half up to two decimal places, with the rounding applied once at the very end."
    PRD 3.2: "`review_count` is by definition the number of submitted `ApplicationReview` rows for the application."

    Design: Corner/entities/application_review_count_and_provisional_score_are_computed_from_the_reviews
    """
    builder = setup_reviewed_application(applicant_count=1, review_count=1)
    application_id = builder.id("app1")

    response = api.create_application_review(
        application_id,
        build_application_review_payload(
            academic_points=30, experience_points=20, holistic_points=20
        ),
        builder.reviewer("f2"),
    )

    validate_success(response, 201)
    application = validate_success(api.get_application(application_id, builder.coordinator), 200)
    assert_application(application)
    assert (
        application["review_count"] == 2
    ), f"review_count must count both submitted reviews, got {application['review_count']}"
    assert_provisional_score(application, [(30, 20, 20), (30, 20, 20)])
    assert (
        application["screening_status"] == ScreeningStatus.UNDER_REVIEW
    ), f"the paper dimension must read UNDER_REVIEW, got {application['screening_status']}"
    assert (
        application["final_screen_score"] is None
    ), "final_screen_score must stay null until a screening decision is recorded"


def test_application_create_with_an_unknown_applicant_id_is_not_found(api):
    """An unknown applicant_id in the body is not found even though program_id resolves.

    Body foreign keys are resolved after path identifiers and before any
    shape check, so the resolvable program_id in the same payload must not
    turn the refusal into a validation error, and no row may be written.

    PRD 2.12: "After path identifiers are resolved, foreign keys supplied in the request body are resolved."
    PRD 2.12: "Every resource named in the URL path exists, checked left to right; then every foreign key supplied in the request body exists."

    Design: Corner/entities/application_create_with_an_unknown_applicant_id_returns_not_found
    """
    builder = setup_staffed_program(applicant_count=0)
    builder.open_review()
    program_id = builder.id("program")

    response = api.create_application(
        build_application_payload(program_id, NON_EXISTENT_UUID), builder.coordinator
    )

    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND)
    _, meta = validate_paginated(
        api.list_applications(builder.coordinator, params={"program_id": program_id})
    )
    assert (
        meta["total_count"] == 0
    ), f"no application row may be written for an unknown applicant, found {meta['total_count']}"


# ======================================================================
# InterviewAssignment: the slot-to-faculty junction
# ======================================================================


def test_two_faculty_members_on_one_slot_form_a_traversable_junction_pair(api):
    """Two panel seats on one slot are traversable from the slot end and the faculty end.

    The assignment table is the many-to-many junction of slot and faculty
    member: filtered by slot_id it must return both panel rows with their own
    panel roles, and filtered by faculty_member_id it must return only the one
    seat that member holds.

    PRD 3.5: "The resulting `InterviewAssignment` is created with `status` `ASSIGNED` — the only other value is `RELEASED` — and immediately triggers a recomputation of that faculty member's `scheduled_load`."
    PRD 3.5: "Assignments are listed with optional `slot_id`, `faculty_member_id` and `status` filters, and a single assignment read exposes its `panel_role` and current `status`."

    Design: Corner/entities/two_faculty_members_on_one_slot_form_a_traversable_junction_pair
    """
    builder = setup_screened_application(applicant_count=1)
    builder.open_interviews()
    builder.create_wave(seat_capacity=1)
    builder.create_slot(applicant_capacity=1)
    slot_id = builder.id("slot1")

    lead_response = api.create_interview_assignment(
        build_interview_assignment_payload(
            slot_id, builder.id("f1"), PanelRole.LEAD
        ),
        builder.coordinator,
    )
    member_response = api.create_interview_assignment(
        build_interview_assignment_payload(
            slot_id, builder.id("f2"), PanelRole.MEMBER
        ),
        builder.coordinator,
    )

    lead = validate_success(lead_response, 201)
    member = validate_success(member_response, 201)
    assert_interview_assignment(lead)
    assert_interview_assignment(member)
    for seat, label in ((lead, "LEAD seat"), (member, "MEMBER seat")):
        assert (
            seat["status"] == AssignmentStatus.ASSIGNED
        ), f"the {label} must be created ASSIGNED, got {seat['status']}"

    by_slot, slot_meta = validate_paginated(
        api.list_interview_assignments(builder.coordinator, params={"slot_id": slot_id})
    )
    assert (
        slot_meta["total_count"] == 2
    ), f"the slot end of the junction must hold 2 rows, got {slot_meta['total_count']}"
    assert (
        find_by(by_slot, faculty_member_id=builder.id("f1"))["panel_role"]
        == PanelRole.LEAD
    ), "the first faculty member's seat must carry panel_role LEAD"
    assert (
        find_by(by_slot, faculty_member_id=builder.id("f2"))["panel_role"]
        == PanelRole.MEMBER
    ), "the second faculty member's seat must carry panel_role MEMBER"

    by_faculty, faculty_meta = validate_paginated(
        api.list_interview_assignments(
            builder.coordinator, params={"faculty_member_id": builder.id("f1")}
        )
    )
    assert (
        faculty_meta["total_count"] == 1
    ), f"the faculty end of the junction must hold 1 row, got {faculty_meta['total_count']}"
    assert (
        by_faculty[0]["id"] == lead["id"]
    ), "the faculty-filtered row must be that member's own panel seat"
