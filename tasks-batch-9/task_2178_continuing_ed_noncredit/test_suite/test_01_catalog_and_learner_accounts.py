"""Catalog formation, section publication and learner accounts."""

from test_helpers import (
    ADMIN,
    ANON,
    COURSE_EXT_050,
    COURSE_EXT_101,
    COURSE_EXT_150,
    COURSE_EXT_201,
    REGISTRAR,
    ApiErrorId,
    assert_course,
    assert_learner,
    assert_offering,
    assert_registration,
    create_course_payload,
    create_offering_payload,
    is_valid_uuid,
    list_memberships,
    make_learner_headers,
    memberships_by_segment,
    new_course,
    new_learner,
    register_learner,
    reset_clock,
    setup_draft_offering,
    setup_open_offering,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_create_course_starts_active_with_zero_offering_count(api):
    """PRD 3.1: "A course is created directly in `status` `ACTIVE` with an
    `active_offering_count` of 0."
    PRD 3.1: "`prerequisite_course_id` defaults to null, meaning the course has no
    prerequisite."
    PRD 2.4: "Every resource the API creates is identified by an `id`, which is a
    server-minted UUID carrying no type prefix and no embedded semantics."

    Design: Corner/entities/create_course_returns_201_with_active_status_and_zero_offering_count
    """
    reset_clock()
    resp = api.create_course(create_course_payload(**COURSE_EXT_101), ADMIN)
    data = validate_success(resp, 201)
    assert_course(data)
    assert data["status"] == "ACTIVE", f"Expected ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"Expected version 1 on creation, got {data['version']}"
    assert data["active_offering_count"] == 0
    assert data["prerequisite_course_id"] is None
    assert is_valid_uuid(data["id"]), f"id must be a bare UUID, got {data['id']!r}"
    assert "_" not in data["id"], "the id carries no type prefix"


def test_get_course_with_unknown_id_returns_course_not_found(api):
    """PRD 2.8: "Path existence — every resource named by a path segment exists,
    validated left to right; otherwise the not-found code for the first unresolvable
    segment."
    PRD 2.9: "Each resource type has its own not-found code: `ERR_COURSE_NOT_FOUND`,
    `ERR_OFFERING_NOT_FOUND`, `ERR_LEARNER_NOT_FOUND`, `ERR_INSTRUCTOR_NOT_FOUND`,
    `ERR_ACCOUNT_NOT_FOUND`, `ERR_VOUCHER_NOT_FOUND`, `ERR_REGISTRATION_NOT_FOUND`,
    `ERR_CONTRACT_NOT_FOUND`, `ERR_COMPLETION_RECORD_NOT_FOUND`, `ERR_PETITION_NOT_FOUND`
    and `ERR_REQUEST_NOT_FOUND`, each returned with HTTP 404."

    Design: Corner/entities/get_course_with_unknown_id_returns_course_not_found
    """
    reset_clock()
    resp = api.get_course("00000000-0000-4000-8000-000000000000", ADMIN)
    validate_error(resp, ApiErrorId.ERR_COURSE_NOT_FOUND, 404)
    assert resp.json()["response_type"] == "error"


def test_list_courses_paginates_with_total_count_and_has_more(api):
    """PRD 2.3: "For list responses the `meta` object carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows matching
    the filter before pagination is applied and `has_more` indicates whether any
    matching row remains beyond the current page."

    Design: Corner/entities/list_courses_paginates_with_total_count_and_has_more
    """
    reset_clock()
    for spec in (COURSE_EXT_050, COURSE_EXT_101, COURSE_EXT_150):
        new_course(**spec)

    first, meta = validate_paginated(
        api.list_courses(REGISTRAR, params={"limit": 2, "offset": 0})
    )
    assert len(first) == 2, f"Expected 2 rows on the first page, got {len(first)}"
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert api.list_courses(REGISTRAR, params={"limit": 2, "offset": 0}).json()[
        "response_type"
    ] == "array"

    second, meta2 = validate_paginated(
        api.list_courses(REGISTRAR, params={"limit": 2, "offset": 2})
    )
    assert len(second) == 1, f"Expected 1 row on the second page, got {len(second)}"
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_create_course_missing_ceu_units_returns_invalid_request(api):
    """PRD 3.1: "A `ProgramAdmin` creates one by supplying a `course_code`, a `title`,
    a `ceu_units` value, a `contact_hours` figure, a `list_price_cents` reference
    price, a `delivery_mode`, a `cpl_credit_units` figure, and optionally a
    `prerequisite_course_id`."
    PRD 2.8: "Request shape, evaluated before any database lookup — every required
    input field present, types correct, enum members valid, monetary and count fields
    non-negative integers, `ceu_units` and `weight` within their declared ranges,
    `course_code` and `email` uniqueness, `end_date` strictly later than `start_date`,
    `census_at` no later than `start_date`, `term_code` present exactly when
    `scheduling_mode` is `TERM`, `max_enrollment` no smaller than `min_enrollment`,
    `target_offering_id` present exactly when `request_type` is `TRANSFER`, `limit`
    within 1 to 100 and `offset` at least 0; otherwise `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_course_missing_ceu_units_returns_invalid_request
    """
    reset_clock()
    payload = create_course_payload(**COURSE_EXT_101)
    payload.pop("ceu_units")
    validate_error(
        api.create_course(payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST, 400
    )
    _, meta = validate_paginated(api.list_courses(ADMIN))
    assert meta["total_count"] == 0, "a rejected create must persist no Course row"


def test_create_course_with_duplicate_course_code_returns_invalid_request(api):
    """PRD 3.1: "The `course_code` is the catalog's human-facing key: it must be
    between 1 and 32 characters long and must be unique across all courses, compared
    as an exact case-sensitive match, so `MGMT-101` and `mgmt-101` are two different
    codes and neither collides with the other. A duplicate `course_code` is a
    malformed request and yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_course_with_duplicate_course_code_returns_invalid_request
    """
    reset_clock()
    new_course(**COURSE_EXT_101)
    dup = create_course_payload(
        course_code="EXT-101",
        title="Duplicate Attempt",
        ceu_units=0.9,
        contact_hours=9,
        list_price_cents=30000,
        delivery_mode="IN_PERSON",
        cpl_credit_units=1.0,
    )
    validate_error(api.create_course(dup, ADMIN), ApiErrorId.ERR_INVALID_REQUEST, 400)
    _, meta = validate_paginated(api.list_courses(ADMIN))
    assert meta["total_count"] == 1


def test_term_offering_requires_term_code_while_rolling_omits_it(api):
    """PRD 3.2: "Term sections belong to an academic term and must carry a `term_code`
    such as `2026FA`; rolling sections start on demand and must omit `term_code` or
    send it as null. Supplying `term_code` on a rolling section, or omitting it on a
    term section, is `ERR_INVALID_REQUEST`."
    PRD 3.2: "Newly created sections sit in `status` `DRAFT` with `cancellation_reason`
    null and all four derived counters at zero: `confirmed_enrollment_count`,
    `paid_enrollment_count`, `waitlist_count` and `net_program_revenue_cents`."

    Design: Corner/entities/create_term_offering_without_term_code_returns_invalid_request
    """
    reset_clock()
    course = new_course(**COURSE_EXT_101)

    term_payload = create_offering_payload(course["id"])
    term_payload.pop("term_code")
    validate_error(
        api.create_offering(term_payload, ADMIN), ApiErrorId.ERR_INVALID_REQUEST, 400
    )

    rolling_payload = create_offering_payload(course["id"], scheduling_mode="ROLLING")
    rolling_payload.pop("term_code")
    rolling = validate_success(api.create_offering(rolling_payload, ADMIN), 201)
    assert_offering(rolling)
    assert rolling["term_code"] is None
    assert rolling["scheduling_mode"] == "ROLLING"
    assert rolling["status"] == "DRAFT"


def test_create_offering_with_unknown_course_id_returns_course_not_found(api):
    """PRD 2.8: "Body existence — every foreign key supplied in the request body
    resolves to an existing row, covering `course_id`, `learner_id`, `instructor_id`,
    `offering_id`, `voucher_id`, `target_offering_id`, `completion_record_id`,
    `prerequisite_course_id` and `target_course_id`; otherwise the corresponding
    not-found code."

    Design: Corner/entities/create_offering_with_unknown_course_id_returns_course_not_found
    """
    reset_clock()
    payload = create_offering_payload("00000000-0000-4000-8000-000000000000")
    validate_error(
        api.create_offering(payload, ADMIN), ApiErrorId.ERR_COURSE_NOT_FOUND, 404
    )


def test_list_courses_filtered_by_prerequisite_course_id_returns_dependents(api):
    """PRD 3.1: "Because the prerequisite pointer runs from dependent course to
    prerequisite course, the only way to discover what depends on a given course is to
    filter the catalog listing by `prerequisite_course_id`."
    PRD 2.3: "Courses may be filtered by `status`, by `prerequisite_course_id`, and by
    `delivery_mode`."

    Design: Corner/entities/list_courses_filtered_by_prerequisite_course_id_returns_dependents
    """
    reset_clock()
    base = new_course(**COURSE_EXT_101)
    advanced = new_course(**COURSE_EXT_201, prerequisite_course_id=base["id"])

    rows, meta = validate_paginated(
        api.list_courses(REGISTRAR, params={"prerequisite_course_id": base["id"]})
    )
    assert meta["total_count"] == 1, f"Expected exactly 1 dependent, got {meta['total_count']}"
    assert rows[0]["id"] == advanced["id"]
    assert rows[0]["prerequisite_course_id"] == base["id"]


def test_pagination_limit_above_max_returns_invalid_request(api):
    """PRD 2.3: "A `limit` outside the inclusive range from 1 to 100, or a negative
    `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`
    (HTTP 400)."

    Design: Corner/validations/pagination_limit_above_max_returns_invalid_request
    """
    reset_clock()
    new_course(**COURSE_EXT_101)
    validate_error(
        api.list_courses(REGISTRAR, params={"limit": 500}),
        ApiErrorId.ERR_INVALID_REQUEST,
        400,
    )


def test_offering_starts_draft_and_second_open_returns_invalid_state(api):
    """PRD 3.2: "Publication is the `ProgramAdmin`'s act of opening a draft section
    for business, moving it `DRAFT → OPEN` and incrementing its `version` by 1. Four
    conditions gate it. The section must currently be `DRAFT`."
    PRD 2.8: "From-state legality — the addressed resource sits in a state from which
    the requested transition is declared; otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/offering_is_created_in_draft_and_open_twice_returns_invalid_state
    """
    reset_clock()
    scene = setup_draft_offering()
    assert scene["offering"]["status"] == "DRAFT"

    opened = validate_success(api.open_offering(scene["offering_id"], ADMIN))
    assert opened["status"] == "OPEN"
    opened_version = opened["version"]

    validate_error(
        api.open_offering(scene["offering_id"], ADMIN),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    after = validate_success(api.get_offering(scene["offering_id"], ADMIN))
    assert after["status"] == "OPEN"
    assert after["version"] == opened_version, (
        "a rejected second open must not bump the section's version"
    )


def test_new_learner_defaults_to_subscribed_with_prospect_membership(api):
    """PRD 3.3: "`marketing_opt_in` defaults to true when omitted, and it is a
    one-time consent flag captured at signup; the learner's live standing is carried
    separately in `marketing_status`, which is set to `SUBSCRIBED` at creation when
    `marketing_opt_in` is true and to `UNSUBSCRIBED` otherwise."
    PRD 3.3: "New learners begin with `lifetime_completed_count` at 0,
    `lifetime_ceu_total` at 0.0, and `loyalty_tier` at `NEW`."
    PRD 3.3: "The **exclusive axis** admits exactly one active segment at a time and
    is keyed purely on `lifetime_completed_count`: a count of zero puts the learner in
    `PROSPECT`, a count of exactly one puts them in `FIRST_TIME`, and a count of two or
    more puts them in `REPEAT`."

    Design: Corner/entities/create_learner_defaults_marketing_opt_in_to_true_and_subscribed
    """
    reset_clock()
    data = validate_success(
        api.create_learner({"email": "ada@x.com", "full_name": "Ada Ito"}, ANON), 201
    )
    assert_learner(data)
    assert data["marketing_status"] == "SUBSCRIBED"
    assert data["loyalty_tier"] == "NEW"
    assert data["lifetime_completed_count"] == 0
    assert data["lifetime_ceu_total"] == 0.0

    rows, meta = validate_paginated(
        api.list_marketing_memberships(data["id"], REGISTRAR)
    )
    assert meta["total_count"] == 1, f"Expected one membership, got {meta['total_count']}"
    assert rows[0]["segment"] == "PROSPECT"
    assert rows[0]["state"] == "ACTIVE"


def test_marketing_unsubscribe_moves_memberships_to_lapsed(api):
    """PRD 3.3: "Either the learner themselves or a `Registrar` may toggle the flag by
    sending a fresh `marketing_opt_in` value; the learner's `marketing_status` is
    rewritten to `SUBSCRIBED` or `UNSUBSCRIBED` accordingly, the segmentation
    recompute described below runs, and the learner's `version` increments by 1."
    PRD 3.3: "If the learner's `marketing_status` is `UNSUBSCRIBED`, every one of that
    learner's memberships moves to `state` `REMOVED` and a single `LAPSED` membership
    is left `ACTIVE`, created if it does not already exist."

    Design: Corner/endpoints/marketing_preference_unsubscribe_moves_memberships_to_lapsed
    """
    reset_clock()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito", marketing_opt_in=True)

    updated = validate_success(
        api.set_marketing_preference(
            learner["id"], {"marketing_opt_in": False}, make_learner_headers(learner["id"])
        )
    )
    assert updated["marketing_status"] == "UNSUBSCRIBED"

    states = memberships_by_segment(list_memberships(learner["id"]))
    assert states.get("PROSPECT") == "REMOVED", (
        f"PROSPECT must be REMOVED after unsubscribe, got {states.get('PROSPECT')}"
    )
    assert states.get("LAPSED") == "ACTIVE"
    active = [seg for seg, state in states.items() if state == "ACTIVE"]
    assert active == ["LAPSED"], f"Only LAPSED may remain ACTIVE, got {active}"


def test_registration_snapshots_total_sessions_and_list_tuition(api):
    """PRD 3.5: "Two snapshots are taken at this moment: `total_sessions` is copied
    from the section's `session_count` and becomes the fixed denominator of this
    registration's attendance ratio forever after, and the price is resolved and
    frozen."
    PRD 3.5: "The registration is created with `enrollment_status` `PENDING` and
    `payment_status` `UNPAID`, holding no seat whatsoever — a pending registration is
    a quotation, not a place in the room — with `voucher_id` and
    `transferred_to_registration_id` both null, `amount_paid_cents` and
    `amount_refunded_cents` both zero, `sessions_attended` at zero, and `enrolled_at`
    null."
    PRD 3.5: "Step one sets `list_tuition_cents` to the section's `tuition_cents` —
    the course's `list_price_cents` plays no part in the arithmetic."

    Design: Corner/entities/registration_creation_snapshots_total_sessions_from_offering
    """
    reset_clock()
    scene = setup_open_offering()
    learner = new_learner(email="ada@x.com", full_name="Ada Ito")

    data = validate_success(
        api.create_registration(
            scene["offering_id"],
            {"learner_id": learner["id"], "expected_offering_version": scene["version"]},
            make_learner_headers(learner["id"]),
        ),
        201,
    )
    assert_registration(data)
    assert data["total_sessions"] == 10
    assert data["list_tuition_cents"] == 60000
    assert data["amount_paid_cents"] == 0
    assert data["amount_refunded_cents"] == 0
    assert data["sessions_attended"] == 0
    assert data["enrolled_at"] is None
    assert data["voucher_id"] is None
    assert data["transferred_to_registration_id"] is None
