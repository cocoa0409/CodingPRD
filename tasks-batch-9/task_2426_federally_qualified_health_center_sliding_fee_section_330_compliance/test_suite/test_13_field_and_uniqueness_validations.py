"""Field-shape, period, uniqueness and ladder validations, each with its own error."""

from test_helpers import (
    OFFICER,
    REP,
    ApiErrorId,
    adopt_fee_schedule_payload,
    api_client,
    create_board_member_payload,
    create_discount_tier_payload,
    create_fee_schedule_payload,
    create_patient_payload,
    make_board_chair_headers,
    refresh_fee_schedule,
    refresh_health_center,
    refresh_patient,
    seed_poverty_guidelines,
    setup_baseline_service,
    setup_baseline_site,
    setup_board_seat,
    setup_draft_fee_schedule,
    setup_grantee,
    setup_patient,
    validate_error,
    validate_paginated,
    validate_success,
)

CORNER_2026_GUIDELINE = ((2026, 1620000, 570000),)


def _guideline_and_grantee():
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)
    return setup_grantee(
        legal_name="Corner Community Health",
        grant_number="H80CS00500",
        pps_base_rate_cents=20000,
    )


def test_a_page_size_above_the_declared_maximum_is_refused_not_clamped():
    """The maximum is a validation bound, not a silent ceiling.

    PRD 2.3: "A `limit` below 1 or above 100, or a negative `offset`, is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    Design: Corner/validations/list_limit_above_one_hundred_returns_invalid_pagination
    """
    seed_poverty_guidelines(CORNER_2026_GUIDELINE)

    validate_error(
        api_client.list_poverty_guidelines(OFFICER, {"limit": 101}),
        ApiErrorId.ERR_INVALID_PAGINATION.value,
        400,
    )

    rows, meta = validate_paginated(
        api_client.list_poverty_guidelines(OFFICER, {"limit": 100})
    )
    assert meta["total_count"] == 1, (
        "the largest accepted page size still works, got "
        f"{meta['total_count']} rows in the count"
    )
    assert meta["limit"] == 100
    assert len(rows) == 1


def test_a_fee_schedule_period_that_ends_before_it_starts_is_refused_at_draft_time():
    """The ordering is strict and is checked while the schedule is still a draft.

    PRD 2.12: "21. A fee schedule's `effective_start` is strictly earlier than its
    `effective_end`, on fee-schedule drafting — otherwise `ERR_INVALID_PERIOD` (422)."

    Design: Corner/validations/fee_schedule_effective_start_not_before_end_rejected
    """
    grantee = _guideline_and_grantee()

    validate_error(
        api_client.create_fee_schedule(
            grantee["id"],
            create_fee_schedule_payload(
                effective_start="2027-01-01T00:00:00Z",
                effective_end="2026-01-01T00:00:00Z",
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_PERIOD.value,
        422,
    )

    _, meta = validate_paginated(
        api_client.list_fee_schedules(OFFICER, {"health_center_id": grantee["id"]})
    )
    assert meta["total_count"] == 0, "no draft was stored"


def test_a_board_term_that_starts_after_it_ends_is_refused():
    """The term ordering check fires before any seat can join the roster.

    PRD 3.2: "`term_start` must be at or before `term_end`, or the seating is rejected
    with `ERR_INVALID_TERM`."

    Design: Corner/validations/board_member_term_start_after_term_end_rejected
    """
    grantee = _guideline_and_grantee()

    validate_error(
        api_client.create_board_member(
            grantee["id"],
            create_board_member_payload(
                term_start="2028-01-01T00:00:00Z", term_end="2026-01-01T00:00:00Z"
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_INVALID_TERM.value,
        422,
    )

    unchanged = refresh_health_center(grantee["id"])
    assert unchanged["seated_board_count"] == 0
    assert unchanged["governance_posture"] == "GOVERNANCE_DEFICIENT", (
        "an empty board cannot hold a patient majority"
    )


def test_a_second_band_claiming_the_same_rung_of_the_ladder_is_refused():
    """`sort_order` is unique within one schedule, whatever the band is called.

    PRD 3.3: "a repeated `tier_label` or `sort_order` within one schedule is rejected
    with `ERR_DUPLICATE_CHILD_KEY`."

    Design: Corner/validations/duplicate_discount_tier_sort_order_within_one_schedule_rejected
    """
    grantee = _guideline_and_grantee()
    draft = setup_draft_fee_schedule(grantee["id"], ladder=None)
    validate_success(
        api_client.create_discount_tier(
            draft["fee_schedule"]["id"], create_discount_tier_payload(), OFFICER
        ),
        201,
    )

    validate_error(
        api_client.create_discount_tier(
            draft["fee_schedule"]["id"],
            create_discount_tier_payload(
                tier_label="PARTIAL_X",
                fpg_min_pct=100,
                fpg_max_pct=150,
                discount_kind="PERCENT_DISCOUNT",
                discount_pct=0.5,
                sort_order=1,
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_DUPLICATE_CHILD_KEY.value,
        409,
    )

    _, meta = validate_paginated(
        api_client.list_fee_schedule_discount_tiers(
            draft["fee_schedule"]["id"], OFFICER
        )
    )
    assert meta["total_count"] == 1, "the ladder still has exactly one rung"


def test_a_patient_seat_with_an_expertise_category_and_no_patient_is_refused():
    """Both halves of the conditional-field rule are violated by the same body.

    PRD 3.2: "A `PATIENT` seat must name the occupant's `patient_id` and must leave
    `expertise_category` null."

    Design: Corner/validations/patient_seat_without_patient_id_rejected
    """
    grantee = _guideline_and_grantee()

    validate_error(
        api_client.create_board_member(
            grantee["id"],
            create_board_member_payload(
                seat_number=2, seat_type="PATIENT", expertise_category="COMMUNITY"
            ),
            OFFICER,
        ),
        ApiErrorId.ERR_SEAT_FIELD_MISMATCH.value,
        422,
    )

    _, meta = validate_paginated(
        api_client.list_board_members(OFFICER, {"health_center_id": grantee["id"]})
    )
    assert meta["total_count"] == 0, "no seat joined the roster"


def test_a_nominal_band_carrying_a_percentage_is_refused():
    """`discount_pct` belongs to exactly one kind of band.

    PRD 3.3: "`discount_pct` is required when and only when `discount_kind` is
    `PERCENT_DISCOUNT`, in which case it must be strictly greater than 0 and strictly
    less than 1; for `NOMINAL` and `NONE` it must be null. A mismatch here is rejected
    with `ERR_TIER_DISCOUNT_MISMATCH`"

    Design: Corner/validations/nominal_tier_carrying_a_discount_pct_rejected
    """
    grantee = _guideline_and_grantee()
    draft = setup_draft_fee_schedule(grantee["id"], ladder=None)

    validate_error(
        api_client.create_discount_tier(
            draft["fee_schedule"]["id"],
            create_discount_tier_payload(discount_kind="NOMINAL", discount_pct=0.8),
            OFFICER,
        ),
        ApiErrorId.ERR_TIER_DISCOUNT_MISMATCH.value,
        422,
    )

    _, meta = validate_paginated(
        api_client.list_fee_schedule_discount_tiers(
            draft["fee_schedule"]["id"], OFFICER
        )
    )
    assert meta["total_count"] == 0, "the refused band was not stored"


def test_a_repeated_medical_record_number_is_refused_and_overwrites_nothing():
    """The record number is unique across all patients, not merely within a grantee.

    PRD 3.4: "A `PatientServicesRep` registers a **patient** with an `mrn` — the medical
    record number, unique across all patients and non-empty — a `full_name`, and a
    `household_size` of at least 1 recording the declared family size of record. A
    duplicate `mrn` is rejected with `ERR_DUPLICATE_KEY`."

    Design: Corner/validations/duplicate_patient_mrn_rejected
    """
    original = setup_patient(mrn="MRN-C01", full_name="Val Osei", household_size=1)

    validate_error(
        api_client.create_patient(
            create_patient_payload(
                mrn="MRN-C01", full_name="Imposter Osei", household_size=3
            ),
            REP,
        ),
        ApiErrorId.ERR_DUPLICATE_KEY.value,
        409,
    )

    unchanged = refresh_patient(original["id"])
    assert unchanged["full_name"] == "Val Osei", (
        f"the stored name survives the refused registration, got {unchanged['full_name']}"
    )
    assert unchanged["household_size"] == 1
    _, meta = validate_paginated(api_client.list_patients(REP))
    assert meta["total_count"] == 1


def test_a_ladder_with_a_fifty_point_gap_is_only_caught_at_adoption():
    """The half-built ladder is legal until the board tries to adopt it.

    PRD 3.3: "each subsequent band's `fpg_min_pct` equals the previous band's
    `fpg_max_pct`, so that on the half-open convention the ladder has neither a gap nor
    an overlap"

    PRD 3.3: "Notably, the *shape of the ladder as a whole* is not checked while tiers
    are being added one at a time; a half-built ladder with gaps is a legitimate
    intermediate state. The whole ladder is validated once, at adoption."

    Design: Corner/validations/tier_ladder_with_a_band_gap_rejected_at_adoption
    """
    grantee = _guideline_and_grantee()
    setup_baseline_site(grantee["id"], site_name="Corner Clinic")
    setup_baseline_service(grantee["id"])
    chair = setup_board_seat(grantee["id"])
    draft = setup_draft_fee_schedule(grantee["id"], ladder=None)
    schedule_id = draft["fee_schedule"]["id"]
    validate_success(
        api_client.create_discount_tier(
            schedule_id, create_discount_tier_payload(), OFFICER
        ),
        201,
    )
    validate_success(
        api_client.create_discount_tier(
            schedule_id,
            create_discount_tier_payload(
                tier_label="FULL_CHARGE",
                fpg_min_pct=150,
                fpg_max_pct=None,
                discount_kind="NONE",
                sort_order=2,
            ),
            OFFICER,
        ),
        201,
    )
    chair_headers = make_board_chair_headers(chair["id"])
    observed = validate_success(
        api_client.get_health_center(grantee["id"], chair_headers)
    )
    assert observed["version"] == 4, (
        "registration, the baseline site, the baseline service and the seating are four "
        f"mutations, got {observed['version']}"
    )

    validate_error(
        api_client.adopt_fee_schedule(
            schedule_id, adopt_fee_schedule_payload(observed["version"]), chair_headers
        ),
        ApiErrorId.ERR_TIER_BANDS_INVALID.value,
        422,
    )

    still_draft = refresh_fee_schedule(schedule_id)
    assert still_draft["status"] == "DRAFT"
    assert still_draft["adopted_at"] is None
    assert still_draft["adopted_by_user_id"] is None
    assert refresh_health_center(grantee["id"])["version"] == 4, (
        "the refused adoption took no version bump with it"
    )
