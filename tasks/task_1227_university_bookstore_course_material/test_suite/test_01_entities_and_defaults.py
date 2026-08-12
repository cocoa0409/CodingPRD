"""Creation defaults, computed-field initialization, and lookup failures."""
from test_helpers import (
    CLOCK_DEFAULT,
    NON_EXISTENT_UUID,
    TERM_FALL_2026,
    ApiErrorId,
    assert_student,
    assert_term,
    assert_title,
    create_adoption_payload,
    create_section_payload,
    create_student_payload,
    create_term_payload,
    create_title_payload,
    get_success_data,
    make_faculty_headers,
    validate_error,
    validate_success,
)


def test_term_created_with_defaults(api, platform_admin_headers):
    """PRD §3.1: "A new term begins in `SETUP`, with
    `noncompliant_section_count` at 0 and `compliance_posture` at `CLEAR`."

    Design: Corner/entities/term_created_with_defaults
    """
    api.set_clock(CLOCK_DEFAULT, platform_admin_headers)
    resp = api.create_term(create_term_payload(), platform_admin_headers)
    term = validate_success(resp, expected_status=201)
    assert_term(term)
    assert term["status"] == "SETUP"
    assert term["compliance_posture"] == "CLEAR"
    assert term["noncompliant_section_count"] == 0
    assert term["version"] == 1


def test_title_stock_initialized_from_initial_fields(api, platform_admin_headers):
    """PRD §3.2: "The seeded values initialize the computed on-hand counters
    `new_stock_qty`, `used_stock_qty`, and `rental_stock_qty`, which then move
    with every placement, return, receipt, and buyback in the domain."

    Design: Corner/entities/title_stock_initialized_from_initial_fields
    """
    pub = validate_success(
        api.create_publisher({"name": "Penguin"}, platform_admin_headers),
        expected_status=201,
    )
    resp = api.create_title(
        create_title_payload(
            publisher_id=pub["id"],
            has_digital=False,
            initial_new_stock_qty=7,
            initial_used_stock_qty=3,
            initial_rental_stock_qty=2,
        ),
        platform_admin_headers,
    )
    title = validate_success(resp, expected_status=201)
    assert_title(title)
    assert title["new_stock_qty"] == 7
    assert title["used_stock_qty"] == 3
    assert title["rental_stock_qty"] == 2


def test_student_aid_balance_initialized_to_awarded(api, platform_admin_headers):
    """PRD §3.3: "each student record carries a `full_name`, a unique `email`,
    and an optional `awarded_aid_cents` — the total financial aid awarded for
    charges, defaulting to 0 — which seeds the student's computed
    `aid_balance_cents` at creation."

    Design: Corner/entities/student_aid_balance_initialized_to_awarded
    """
    stu = validate_success(
        api.create_student(
            create_student_payload(awarded_aid_cents=42000), platform_admin_headers
        ),
        expected_status=201,
    )
    assert_student(stu)
    assert stu["aid_balance_cents"] == 42000

    stu0 = validate_success(
        api.create_student(
            create_student_payload(
                full_name="Stu Zero", email="zero@uni.edu", awarded_aid_cents=None
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    assert_student(stu0)
    assert stu0["awarded_aid_cents"] == 0
    assert stu0["aid_balance_cents"] == 0


def test_entity_get_not_found_returns_404(api, platform_admin_headers):
    """PRD §2.8: "Existence: path identifiers and body foreign-key identifiers
    must exist, validated left to right as they appear in the URL and payload
    (`ERR_NOT_FOUND`)."

    Design: Corner/entities/entity_get_not_found_returns_404
    """
    resp = api.get_term(NON_EXISTENT_UUID, platform_admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_section_requires_fee_when_ia_enabled(api, platform_admin_headers):
    """PRD §3.3: "`ia_enabled`, and `ia_material_fee_cents`, which is required
    exactly when `ia_enabled` is true and must be at least 0."

    Design: Corner/entities/section_requires_fee_when_ia_enabled
    """
    term = validate_success(
        api.create_term(create_term_payload(), platform_admin_headers),
        expected_status=201,
    )
    fac = validate_success(
        api.create_faculty(
            {"full_name": "Prof Ada", "email": "ada@uni.edu"}, platform_admin_headers
        ),
        expected_status=201,
    )
    resp = api.create_section(
        create_section_payload(
            term_id=term["id"],
            faculty_id=fac["id"],
            course_code="BIO200",
            ia_enabled=True,
        ),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_adoption_posted_price_optional_at_create(api):
    """PRD §3.4: "A `Faculty` actor creates an adoption by naming the
    `section_id` and `title_id`, the requested quantities `qty_new_requested`,
    `qty_used_requested`, `qty_rental_requested`, and `qty_digital_requested`
    (each at least 0), optionally the `posted_price_cents`, and the
    `expected_section_version` required by §2.7."
    PRD §3.4: "While `DRAFT`, the owning faculty member may edit the quantities
    and `posted_price_cents` through the adoption edit operation, which requires
    `expected_adoption_version` per §2.7."

    Design: Corner/entities/adoption_posted_price_optional_at_create
    """
    from test_helpers import (
        ADMIN,
        create_adoption,
        create_publisher,
        create_section,
        create_faculty,
        create_term,
        create_title,
        open_section,
        open_term_adoption,
        reset_clock,
    )

    reset_clock()
    term = create_term()
    pub = create_publisher()
    title = create_title(
        pub["id"], isbn="9780000001002", has_used=False, has_rental=False,
        has_digital=False,
    )
    faculty = create_faculty()
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])

    # Create without posted_price_cents.
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=None,
    )
    assert adoption["status"] == "DRAFT"
    assert adoption["posted_price_cents"] is None

    # Backfill the posted price via the edit operation while DRAFT.
    resp = api.patch_adoption(
        adoption["id"],
        {"posted_price_cents": 9500, "expected_adoption_version": adoption["version"]},
        make_faculty_headers(faculty["id"]),
    )
    updated = validate_success(resp, expected_status=200)
    assert updated["posted_price_cents"] == 9500
    assert updated["status"] == "DRAFT"
