"""Validation conflicts: interval overlap semantics, capacity, stock,
enrollment duplicates, order gating, and error-priority pairs."""
from test_helpers import (
    ApiErrorId,
    assert_agreement,
    assert_wholesale_quote,
    create_approved_adoption,
    create_agreement,
    create_agreement_payload,
    create_enrollment_payload,
    create_faculty,
    create_order_payload,
    create_publisher,
    create_publisher_with_agreement,
    create_section,
    create_student,
    create_term,
    create_title,
    create_title_payload,
    create_wholesale_quote_payload,
    enroll_student,
    get_first_order_line,
    get_success_data,
    make_student_headers,
    open_section,
    open_term_adoption,
    place_order,
    reset_clock,
    create_adoption,
    drive_term_to_sales_open,
    set_clock,
    setup_sales_open_with_approved_adoption,
    submit_adoption,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ADMIN, MANAGER


def test_wholesale_quote_half_open_adjacency(api, platform_admin_headers):
    """PRD §3.2: "Two quotes for the same title and condition may not overlap
    on half-open semantics — overlap exists when the new `effective_from` is
    before the existing `effective_to` and the new `effective_to` is after the
    existing `effective_from` — and unlike agreements, adjacency is permitted:
    a quote whose `effective_from` equals a prior quote's `effective_to` does
    not overlap and is accepted. A violating quote is rejected with
    `ERR_QUOTE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/wholesale_quote_half_open_adjacency
    """
    reset_clock()
    pub = create_publisher()
    title = create_title(
        pub["id"], isbn="9780000000012", has_rental=False, has_digital=False
    )
    q1 = validate_success(
        api.create_wholesale_quote(
            title["id"],
            create_wholesale_quote_payload(
                effective_from="2026-12-01T00:00:00Z",
                effective_to="2026-12-10T00:00:00Z",
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    assert_wholesale_quote(q1)

    # Adjacent (from == prior to): allowed.
    q2 = validate_success(
        api.create_wholesale_quote(
            title["id"],
            create_wholesale_quote_payload(
                price_cents=2500,
                effective_from="2026-12-10T00:00:00Z",
                effective_to="2026-12-20T00:00:00Z",
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    assert q2["price_cents"] == 2500

    # Strictly overlapping window: rejected.
    resp = api.create_wholesale_quote(
        title["id"],
        create_wholesale_quote_payload(
            price_cents=3000,
            effective_from="2026-12-05T00:00:00Z",
            effective_to="2026-12-15T00:00:00Z",
        ),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_WINDOW_OVERLAP)


def test_wholesale_quote_containment_is_overlap(api, platform_admin_headers):
    """PRD §3.2: "Two quotes for the same title and condition may not overlap
    on half-open semantics — overlap exists when the new `effective_from` is
    before the existing `effective_to` and the new `effective_to` is after the
    existing `effective_from` — and unlike agreements, adjacency is permitted:
    a quote whose `effective_from` equals a prior quote's `effective_to` does
    not overlap and is accepted. A violating quote is rejected with
    `ERR_QUOTE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/wholesale_quote_half_open_adjacency
    """
    reset_clock()
    pub = create_publisher()
    title = create_title(
        pub["id"], isbn="9780000000036", has_rental=False, has_digital=False
    )
    validate_success(
        api.create_wholesale_quote(
            title["id"],
            create_wholesale_quote_payload(
                effective_from="2026-12-01T00:00:00Z",
                effective_to="2026-12-10T00:00:00Z",
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    # Contained strictly inside the existing window: overlap on both tests.
    resp = api.create_wholesale_quote(
        title["id"],
        create_wholesale_quote_payload(
            price_cents=3000,
            effective_from="2026-12-03T00:00:00Z",
            effective_to="2026-12-08T00:00:00Z",
        ),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_QUOTE_WINDOW_OVERLAP)


def test_publisher_agreement_closed_interval_adjacency(api, platform_admin_headers):
    """PRD §3.2: "Two agreements for the same publisher may not overlap on
    their closed intervals: an overlap exists when the new agreement's
    `start_date` is on or before the existing agreement's `end_date` and the
    new `end_date` is on or after the existing `start_date`. Note that
    adjacency counts as overlap here — a new agreement starting exactly on the
    day an existing one ends is rejected with `ERR_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/publisher_agreement_closed_interval_adjacency
    """
    reset_clock()
    pub = create_publisher()
    first = validate_success(
        api.create_agreement(
            pub["id"],
            create_agreement_payload(start_date="2026-01-01", end_date="2026-06-30"),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    assert_agreement(first)

    # Touching on the closed boundary day: overlap.
    resp = api.create_agreement(
        pub["id"],
        create_agreement_payload(
            start_date="2026-06-30", end_date="2026-12-31", discount_pct=0.12
        ),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)

    # Starting the day after: disjoint, accepted.
    second = validate_success(
        api.create_agreement(
            pub["id"],
            create_agreement_payload(
                start_date="2026-07-01", end_date="2026-12-31", discount_pct=0.12
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    assert_agreement(second)


def test_publisher_agreement_strict_containment_rejected(api, platform_admin_headers):
    """PRD §3.2: "Two agreements for the same publisher may not overlap on
    their closed intervals: an overlap exists when the new agreement's
    `start_date` is on or before the existing agreement's `end_date` and the
    new `end_date` is on or after the existing `start_date`. Note that
    adjacency counts as overlap here — a new agreement starting exactly on the
    day an existing one ends is rejected with `ERR_AGREEMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/publisher_agreement_closed_interval_adjacency
    """
    reset_clock()
    pub = create_publisher()
    validate_success(
        api.create_agreement(
            pub["id"],
            create_agreement_payload(start_date="2026-01-01", end_date="2026-06-30"),
            platform_admin_headers,
        ),
        expected_status=201,
    )
    resp = api.create_agreement(
        pub["id"],
        create_agreement_payload(start_date="2026-03-01", end_date="2026-05-31"),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)


def test_enrollment_capacity_boundary(api, platform_admin_headers):
    """PRD §3.3: "Enrollments are created against a section by `PlatformAdmin`,
    one per student: supplying a `student_id` yields an `ENROLLED` enrollment,
    provided no enrollment already exists for the same section and student
    (`ERR_ENROLLMENT_DUPLICATE`) and the count of `ENROLLED` enrollments is
    still below the section's `enrollment_capacity`
    (`ERR_SECTION_CAPACITY_REACHED`)."

    Design: Corner/validations/enrollment_capacity_boundary
    """
    reset_clock()
    term = create_term()
    faculty = create_faculty()
    stu1 = create_student(email="stu1@uni.edu", awarded_aid_cents=None)
    stu2 = create_student(full_name="Stu Two", email="stu2@uni.edu",
                          awarded_aid_cents=None)
    section = create_section(
        term["id"], faculty["id"], enrollment_capacity=1
    )
    open_term_adoption(term["id"])
    open_section(section["id"])

    first = validate_success(
        api.enroll_student(section["id"], create_enrollment_payload(student_id=stu1["id"]),
                           platform_admin_headers),
        expected_status=201,
    )
    assert first["status"] == "ENROLLED"

    resp = api.enroll_student(
        section["id"], create_enrollment_payload(student_id=stu2["id"]),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_SECTION_CAPACITY_REACHED)


def test_enrollment_duplicate_rejected(api, platform_admin_headers):
    """PRD §3.3: "Enrollments are created against a section by `PlatformAdmin`,
    one per student: supplying a `student_id` yields an `ENROLLED` enrollment,
    provided no enrollment already exists for the same section and student
    (`ERR_ENROLLMENT_DUPLICATE`) and the count of `ENROLLED` enrollments is
    still below the section's `enrollment_capacity`
    (`ERR_SECTION_CAPACITY_REACHED`)."

    Design: Corner/validations/enrollment_capacity_boundary
    """
    reset_clock()
    term = create_term()
    faculty = create_faculty()
    stu = create_student(awarded_aid_cents=None)
    section = create_section(term["id"], faculty["id"], enrollment_capacity=5)
    open_term_adoption(term["id"])
    open_section(section["id"])
    enroll_student(section["id"], stu["id"])

    resp = api.enroll_student(
        section["id"], create_enrollment_payload(student_id=stu["id"]),
        platform_admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_DUPLICATE)


def test_insufficient_stock_rejected(api):
    """PRD §3.6: "Each referenced adoption must be `APPROVED`
    (`ERR_ADOPTION_NOT_APPROVED`), an active agreement must cover each title's
    publisher at now (`ERR_NO_ACTIVE_AGREEMENT`), the requested format must be
    offered by the title (`ERR_FORMAT_NOT_OFFERED`), and the title's on-hand
    stock for the requested format must be at least the line quantity
    (`ERR_INSUFFICIENT_STOCK`)."

    Design: Corner/endpoints/insufficient_stock_rejected
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=2,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "has_used": False,
                         "has_rental": False, "has_digital": False},
        isbn="9780000001013",
    )
    resp = api.create_order(
        create_order_payload(
            term_id=base["term"]["id"],
            lines=[{"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 2}],
        ),
        make_student_headers(base["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)
    title = get_success_data(api.get_title(base["title"]["id"], MANAGER))
    assert title["new_stock_qty"] == 1


def test_order_referential_beats_fiscal(api):
    """PRD §2.8: "9. Business referential: an active publisher agreement covers
    the title's publisher at now (`ERR_NO_ACTIVE_AGREEMENT`); the referenced
    adoption is approved (`ERR_ADOPTION_NOT_APPROVED`); the wholesale variant
    has an active quote (`ERR_WHOLESALE_QUOTE_MISSING`); the term's compliance
    posture permits commission issue (`ERR_TERM_NOT_COMPLIANT`). 10. Business
    fiscal: the term buy budget (`ERR_TERM_BUDGET_EXCEEDED`) and full aid
    coverage of an aid-only order (`ERR_INSUFFICIENT_AID`)."

    Design: Difficulty/priority_pair_validation_conflict/order_referential_beats_fiscal
    """
    reset_clock()
    term = create_term()
    pub, _agr = create_publisher_with_agreement()
    title = create_title(
        pub["id"], isbn="9780000000008", has_used=False, has_rental=False,
        has_digital=False, initial_new_stock_qty=5,
    )
    faculty = create_faculty()
    student = create_student(full_name="Stu Poor", email="poor@uni.edu",
                             awarded_aid_cents=1000)
    section = create_section(term["id"], faculty["id"])
    open_term_adoption(term["id"])
    opened = open_section(section["id"])
    adoption = create_adoption(
        section["id"], title["id"], faculty["id"], opened["version"],
        qty_new=5, posted_price_cents=10000,
    )
    # Stuck in SUBMITTED: survives the close-adoption sweep.
    submit_adoption(adoption["id"], faculty["id"])
    drive_term_to_sales_open(term["id"])
    set_clock("2026-08-20T00:00:00Z")

    resp = api.create_order(
        create_order_payload(
            term_id=term["id"],
            aid_only=True,
            lines=[{"adoption_id": adoption["id"], "format": "NEW", "qty": 1}],
        ),
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ADOPTION_NOT_APPROVED)

    orders = get_success_data(
        api.list_orders(MANAGER, params={"student_id": student["id"]})
    )
    assert orders == []


def test_order_aid_only_insufficient_aid_isolated(api):
    """PRD §3.6: "If `aid_only` is true and the summed aid falls short of
    `total_cents`, the placement fails with `ERR_INSUFFICIENT_AID` (HTTP 402)."

    Design: Difficulty/priority_pair_validation_conflict/order_referential_beats_fiscal
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=5,
        posted_price_cents=10000,
        title_overrides={"initial_new_stock_qty": 5, "has_used": False,
                         "has_rental": False, "has_digital": False},
        awarded_aid_cents=1000,
        isbn="9780000000037",
    )
    resp = api.create_order(
        create_order_payload(
            term_id=base["term"]["id"],
            aid_only=True,
            lines=[{"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1}],
        ),
        make_student_headers(base["student"]["id"]),
    )
    # Adoption is APPROVED, so only the fiscal rule can fire: aid 1000 <
    # total 10000.
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AID)


def test_titles_pagination_and_filter_interaction(api, platform_admin_headers, manager_headers):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; the `offset` defaults to 0. Results are sorted by `created_at`
    ascending. The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, so a client can page deterministically
    through any collection."

    Design: Corner/cross_cutting_layers/titles_pagination_and_filter_interaction
    """
    pub_a = validate_success(
        api.create_publisher({"name": "Penguin"}, platform_admin_headers),
        expected_status=201,
    )
    pub_b = validate_success(
        api.create_publisher({"name": "Oxford"}, platform_admin_headers),
        expected_status=201,
    )
    for isbn in ("9780000001023", "9780000001024", "9780000001025"):
        validate_success(
            api.create_title(
                create_title_payload(
                    isbn=isbn, publisher_id=pub_a["id"], list_price_cents=1000,
                    has_used=False, has_rental=False, has_digital=False,
                ),
                platform_admin_headers,
            ),
            expected_status=201,
        )
    validate_success(
        api.create_title(
            create_title_payload(
                isbn="9780000001026", publisher_id=pub_b["id"],
                list_price_cents=1000, has_used=False, has_rental=False,
                has_digital=False,
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )

    page1, meta1 = validate_paginated(
        api.list_titles(manager_headers,
                        params={"publisher_id": pub_a["id"], "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_titles(manager_headers,
                        params={"publisher_id": pub_a["id"], "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_titles_pagination_filter_counts_only_matches(api, platform_admin_headers, manager_headers):
    """PRD §2.3: "List endpoints accept the query parameters `limit` and
    `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of
    100; the `offset` defaults to 0. Results are sorted by `created_at`
    ascending. The `meta` block of a list response carries `limit`, `offset`,
    `total_count`, and `has_more`, so a client can page deterministically
    through any collection."

    Design: Corner/cross_cutting_layers/titles_pagination_and_filter_interaction
    """
    pub_a = validate_success(
        api.create_publisher({"name": "Penguin"}, platform_admin_headers),
        expected_status=201,
    )
    pub_b = validate_success(
        api.create_publisher({"name": "Oxford"}, platform_admin_headers),
        expected_status=201,
    )
    for isbn in ("9780000001023", "9780000001024", "9780000001025"):
        validate_success(
            api.create_title(
                create_title_payload(
                    isbn=isbn, publisher_id=pub_a["id"], list_price_cents=1000,
                    has_used=False, has_rental=False, has_digital=False,
                ),
                platform_admin_headers,
            ),
            expected_status=201,
        )
    validate_success(
        api.create_title(
            create_title_payload(
                isbn="9780000001026", publisher_id=pub_b["id"],
                list_price_cents=1000, has_used=False, has_rental=False,
                has_digital=False,
            ),
            platform_admin_headers,
        ),
        expected_status=201,
    )

    # The filtered total reflects only publisher A's titles; an unfiltered
    # page sees all four.
    _, meta_b = validate_paginated(
        api.list_titles(manager_headers, params={"publisher_id": pub_b["id"]})
    )
    assert meta_b["total_count"] == 1
    page_all, meta_all = validate_paginated(
        api.list_titles(manager_headers, params={"limit": 10, "offset": 0})
    )
    assert meta_all["total_count"] == 4
    assert len(page_all) == 4
    assert meta_all["has_more"] is False


def test_aid_conservation_forward_and_return(api):
    """PRD §3.7: "The student's `aid_balance_cents` is credited by
    `aid_refunded_cents`, bumping the student's `version`."
    PRD §3.6: "Otherwise the student's `aid_balance_cents` is debited by the
    order's `aid_tendered_cents`."
    PRD §3.6: "For `DIGITAL`, the base is the list price reduced by the active
    agreement's `digital_discount_pct`, rounded half-up to integer cents."

    Design: Difficulty/compensating_invariant/aid_conservation_forward_and_return
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1, qty_digital=1,
        posted_price_cents=12000,
        title_overrides={"initial_new_stock_qty": 1, "has_used": False,
                         "has_rental": False},
        awarded_aid_cents=50000,
        isbn="9780000000013",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [
            {"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1},
            {"adoption_id": base["adoption"]["id"], "format": "DIGITAL", "qty": 1},
        ],
    )
    # NEW 10000 + DIGITAL 7500, fully aid-tendered.
    assert order["total_cents"] == 17500
    assert order["aid_tendered_cents"] == 17500

    lines = get_success_data(
        api.list_order_lines(order["id"], make_student_headers(base["student"]["id"]))
    )
    by_format = {line["format"]: line for line in lines}

    returned = validate_success(
        api.return_order_line(
            order["id"], by_format["NEW"]["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    assert returned["status"] == "RETURNED"
    assert returned["aid_refunded_cents"] == 10000

    student = get_success_data(
        api.get_student(base["student"]["id"], make_student_headers(base["student"]["id"]))
    )
    # 50000 - 17500 + 10000 = 42500; the conservation equation holds exactly:
    # 50000 == 42500 (balance) + 7500 (still-held DIGITAL aid) + 0 forfeited.
    assert student["aid_balance_cents"] == 42500
    assert by_format["DIGITAL"]["aid_tendered_cents"] == 7500
    assert student["aid_balance_cents"] + by_format["DIGITAL"]["aid_tendered_cents"] == 50000


def test_aid_conservation_aid_only_order_fully_returned(api):
    """PRD §3.6: "Otherwise the student's `aid_balance_cents` is debited by the
    order's `aid_tendered_cents`."
    PRD §3.7: "The student's `aid_balance_cents` is credited by
    `aid_refunded_cents`, bumping the student's `version`."
    PRD §3.7: "Within the applicable window, the refund is the full
    `line_total_cents`, returned to the original tenders."

    Design: Difficulty/compensating_invariant/aid_conservation_forward_and_return
    """
    base = setup_sales_open_with_approved_adoption(
        qty_new=1,
        posted_price_cents=10000,
        title_overrides={"initial_new_stock_qty": 1, "has_used": False,
                         "has_rental": False, "has_digital": False},
        awarded_aid_cents=20000,
        isbn="9780000000043",
    )
    order = place_order(
        base["term"]["id"], base["student"]["id"],
        [{"adoption_id": base["adoption"]["id"], "format": "NEW", "qty": 1}],
        aid_only=True,
    )
    assert order["aid_tendered_cents"] == 10000
    assert order["card_tendered_cents"] == 0

    student = get_success_data(
        api.get_student(base["student"]["id"], make_student_headers(base["student"]["id"]))
    )
    assert student["aid_balance_cents"] == 10000

    line = get_first_order_line(order["id"])
    returned = validate_success(
        api.return_order_line(
            order["id"], line["id"], {},
            make_student_headers(base["student"]["id"]),
        )
    )
    assert returned["aid_refunded_cents"] == 10000
    assert returned["card_refunded_cents"] == 0

    # The forward debit and the compensating credit cancel exactly.
    student = get_success_data(
        api.get_student(base["student"]["id"], make_student_headers(base["student"]["id"]))
    )
    assert student["aid_balance_cents"] == 20000
    order_after = get_success_data(api.get_order(order["id"], MANAGER))
    assert order_after["status"] == "REFUNDED"
    assert order_after["refund_total_cents"] == 10000
