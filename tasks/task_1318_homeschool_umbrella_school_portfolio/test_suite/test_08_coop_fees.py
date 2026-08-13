"""Co-op registration: fee calculation (per-line rounding, early-bird, sibling),
capacity boundary, schedule overlap, and registration gates."""
from test_helpers import (
    ApiErrorId,
    assert_coop_enrollment,
    create_coop_class,
    create_open_coop_class,
    create_open_year,
    get_ledger,
    get_success_data,
    register_coop,
    register_coop_ok,
    setup_active_enrollment,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

REGISTRAR = TEST_USERS["registrar_headers"]


def _sibling_family_setup(api, year_id):
    """Family with three ACTIVE enrollments (grades 2/3/4) under one family id."""
    from test_helpers import (
        activate_enrollment,
        add_student,
        create_acknowledged_notice,
        create_approved_plan,
        create_enrollment,
        create_family,
    )

    family = create_family(display_name="Family Round", district_code="D-03")
    enrollments = []
    for name, dob, grade in (
        ("Kid Two", "2018-01-01", 2),
        ("Kid Three", "2016-06-06", 3),
        ("Kid Four", "2014-04-04", 4),
    ):
        student = add_student(family, full_name=name, date_of_birth=dob)
        enrollment = create_enrollment(student, family, year_id, grade)
        create_acknowledged_notice(enrollment, family, district_code="D-03")
        create_approved_plan(enrollment, family)
        enrollments.append(activate_enrollment(enrollment))
    return family, enrollments


def test_coop_fee_per_line_discounts(api):
    """PRD §3.7: "An early-bird discount of ten percent applies when the co-op
    enrollment was created at least thirty days before the class's first session
    date. A sibling discount of fifteen percent applies when another co-op
    enrollment, belonging to an enrollment of the same family in the same
    academic year, already stands `CONFIRMED` or `COMPLETED` and was created
    before this one — the comparison is made on creation timestamps alone and
    never consults entity identifiers. The two discounts add, capped at a
    combined twenty-five percent, and the result is recorded as
    `discount_pct_applied`."

    Design: Difficulty/combinatorial_formula/coop_fee_per_line_rounding_vs_sum_rounding
    """
    year = create_open_year()
    family, enrollments = _sibling_family_setup(api, year["id"])
    # Registration at the 2026-08-01 default clock; start 2026-09-10 is exactly
    # 40 days out, so every line qualifies for early-bird; siblings stack to 25%.
    coop_class = create_open_coop_class(
        year["id"], title="Art Studio", start_date="2026-09-10", capacity=10,
        fee_base_cents=9999, materials_fee_cents=0,
    )

    ce1 = validate_success(
        register_coop(coop_class["id"], enrollments[0]["id"], family["id"]), 201
    )
    assert_coop_enrollment(ce1)
    assert ce1["status"] == "CONFIRMED"
    assert ce1["discount_pct_applied"] == 10
    assert ce1["fee_cents"] == 8999, "round_half_up(9999 * 0.90) = 8999"

    ce2 = validate_success(
        register_coop(coop_class["id"], enrollments[1]["id"], family["id"]), 201
    )
    assert ce2["discount_pct_applied"] == 25, "10 early-bird + 15 sibling, at the cap"
    assert ce2["fee_cents"] == 7499, "round_half_up(9999 * 0.75) = 7499"

    ce3 = validate_success(
        register_coop(coop_class["id"], enrollments[2]["id"], family["id"]), 201
    )
    assert ce3["discount_pct_applied"] == 25
    assert ce3["fee_cents"] == 7499


def test_coop_fee_family_ledger_sums_rounded_lines(api):
    """PRD §2.9: "Fees are rounded per enrollment line using round-half-up to
    whole cents, and the family ledger is always the sum of those individually
    rounded lines — the family total itself is never rounded as a whole."
    PRD §3.7: "Confirmation moves money: the family's `fee_balance_cents` is
    debited by the line's `fee_cents`, the class's `seats_taken` increments, and
    the class's `version` increments."

    Design: Difficulty/combinatorial_formula/coop_fee_per_line_rounding_vs_sum_rounding
    """
    year = create_open_year()
    family, enrollments = _sibling_family_setup(api, year["id"])
    coop_class = create_open_coop_class(
        year["id"], title="Art Studio", start_date="2026-09-10", capacity=10,
        fee_base_cents=9999, materials_fee_cents=0,
    )
    for enrollment in enrollments:
        register_coop_ok(coop_class["id"], enrollment["id"], family["id"])

    ledger = get_ledger(family["id"])
    # 8999 + 7499 + 7499 = 23997 (sum-then-round of the bases would give 23998).
    assert ledger["fee_balance_cents"] == 23997
    coop_after = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert coop_after["seats_taken"] == 3


def test_early_bird_exactly_thirty_days(api):
    """PRD §3.7: "An early-bird discount of ten percent applies when the co-op
    enrollment was created at least thirty days before the class's first session
    date."

    Design: Corner/calculations/early_bird_exactly_thirty_days
    """
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 4, family_name="Fam E",
                                    district_code="D-44")
    ctx_b = setup_active_enrollment(year["id"], 4, family_name="Fam L",
                                    district_code="D-45", student_name="Kid L",
                                    date_of_birth="2016-02-02")
    # Registration happens at the 2026-08-01 default clock.
    class_e = create_open_coop_class(  # start is exactly 30 days after registration
        year["id"], title="Early", start_date="2026-08-31", capacity=10,
        fee_base_cents=10000, materials_fee_cents=500,
    )
    class_l = create_open_coop_class(  # start is 29 days after registration
        year["id"], title="Late", meeting_day="TUE", start_date="2026-08-30",
        capacity=10, fee_base_cents=10000, materials_fee_cents=500,
    )
    ce_e = validate_success(
        register_coop(class_e["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"]), 201
    )
    assert ce_e["discount_pct_applied"] == 10, "created exactly 30 days before start qualifies"
    assert ce_e["fee_cents"] == 9500, "round_half_up(10000 * 0.90) + 500"

    ce_l = validate_success(
        register_coop(class_l["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"]), 201
    )
    assert ce_l["discount_pct_applied"] == 0, "29 days before start does not qualify"
    assert ce_l["fee_cents"] == 10500


def test_coop_capacity_boundary_first_two_confirmed(api):
    """PRD §3.7: "The new co-op enrollment lands `CONFIRMED` when the class
    still has a free seat, otherwise `WAITLISTED`, and the roster link back to
    the class is recorded as `coop_class_id`."
    PRD §3.7: "The class is born `DRAFT` with `seats_taken` at zero, where
    `seats_taken` counts co-op enrollments in `CONFIRMED` or `COMPLETED`."

    Design: Difficulty/boundary_precision_check/coop_capacity_boundary_and_waitlist
    """
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 4, family_name="Fam A",
                                    district_code="D-17")
    ctx_b = setup_active_enrollment(year["id"], 5, family_name="Fam B",
                                    district_code="D-18", student_name="Kid B",
                                    date_of_birth="2015-02-02")
    coop_class = create_open_coop_class(year["id"], title="Drama", capacity=2)

    ce_a = validate_success(
        register_coop(coop_class["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"]), 201
    )
    assert ce_a["status"] == "CONFIRMED", "seats 0 < 2"
    assert ce_a["fee_cents"] == 11000

    ce_b = validate_success(
        register_coop(coop_class["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"]), 201
    )
    assert ce_b["status"] == "CONFIRMED", "boundary: the last free seat confirms"


def test_coop_capacity_boundary_third_waitlisted(api):
    """PRD §3.7: "The new co-op enrollment lands `CONFIRMED` when the class
    still has a free seat, otherwise `WAITLISTED`, and the roster link back to
    the class is recorded as `coop_class_id`."
    PRD §3.7: "A `WAITLISTED` line carries a `fee_cents` of zero until promoted."

    Design: Difficulty/boundary_precision_check/coop_capacity_boundary_and_waitlist
    """
    year = create_open_year()
    ctx_a = setup_active_enrollment(year["id"], 4, family_name="Fam A",
                                    district_code="D-17")
    ctx_b = setup_active_enrollment(year["id"], 5, family_name="Fam B",
                                    district_code="D-18", student_name="Kid B",
                                    date_of_birth="2015-02-02")
    ctx_c = setup_active_enrollment(year["id"], 6, family_name="Fam C",
                                    district_code="D-19", student_name="Kid C",
                                    date_of_birth="2014-03-03")
    coop_class = create_open_coop_class(year["id"], title="Drama", capacity=2)
    register_coop_ok(coop_class["id"], ctx_a["enrollment"]["id"], ctx_a["family"]["id"])
    register_coop_ok(coop_class["id"], ctx_b["enrollment"]["id"], ctx_b["family"]["id"])

    ce_c = validate_success(
        register_coop(coop_class["id"], ctx_c["enrollment"]["id"], ctx_c["family"]["id"]), 201
    )
    assert ce_c["status"] == "WAITLISTED", "seats == capacity: waitlisted"
    assert ce_c["fee_cents"] == 0

    coop_after = get_success_data(api.get_coop_class(coop_class["id"], REGISTRAR))
    assert coop_after["seats_taken"] == 2
    ledger_c = get_ledger(ctx_c["family"]["id"])
    assert ledger_c["fee_balance_cents"] == 0, "waitlist never charges"


def test_coop_meeting_adjacent_windows_allowed(api):
    """PRD §2.9: "Meeting and sitting windows are half-open intervals — a window
    occupies its start instant up to but not including its end instant — so two
    windows on the same weekday that merely touch, one ending exactly when the
    other begins, do not conflict; genuine intersection is required for
    `ERR_COOP_SCHEDULE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/coop_meeting_time_half_open_overlap
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Ovl",
                                  district_code="D-22", date_of_birth="2016-10-10")
    c1 = create_open_coop_class(year["id"], title="C1", meeting_day="MON",
                                meeting_start_minutes=540, meeting_end_minutes=630,
                                capacity=10, fee_base_cents=1000, materials_fee_cents=0)
    c2 = create_open_coop_class(year["id"], title="C2", subject="Music",
                                meeting_day="MON", meeting_start_minutes=630,
                                meeting_end_minutes=720, capacity=10,
                                fee_base_cents=1000, materials_fee_cents=0)
    ce1 = validate_success(
        register_coop(c1["id"], ctx["enrollment"]["id"], ctx["family"]["id"]), 201
    )
    assert ce1["status"] == "CONFIRMED"
    assert ce1["fee_cents"] == 1000, "no early-bird (24 days out), no sibling"

    # [540,630) and [630,720) merely touch at 630: allowed.
    ce2 = validate_success(
        register_coop(c2["id"], ctx["enrollment"]["id"], ctx["family"]["id"]), 201
    )
    assert ce2["status"] == "CONFIRMED"
    assert ce2["discount_pct_applied"] == 15, "sibling discount on the second enrollment"
    assert ce2["fee_cents"] == 850, "round_half_up(1000 * 0.85)"


def test_coop_meeting_intersecting_windows_rejected(api):
    """PRD §3.7: "the weekly meeting window must not intersect, on the same
    `meeting_day`, the window of any other class in which the student holds a
    `CONFIRMED` enrollment — windows are half-open, so touching endpoints are
    allowed — else `ERR_COOP_SCHEDULE_OVERLAP`"

    Design: Difficulty/resource_temporal_overlap/coop_meeting_time_half_open_overlap
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Ovl",
                                  district_code="D-22", date_of_birth="2016-10-10")
    c1 = create_open_coop_class(year["id"], title="C1", meeting_day="MON",
                                meeting_start_minutes=540, meeting_end_minutes=630,
                                capacity=10, fee_base_cents=1000, materials_fee_cents=0)
    c3 = create_open_coop_class(year["id"], title="C3", subject="PE",
                                meeting_day="MON", meeting_start_minutes=600,
                                meeting_end_minutes=660, capacity=10,
                                fee_base_cents=1000, materials_fee_cents=0)
    register_coop_ok(c1["id"], ctx["enrollment"]["id"], ctx["family"]["id"])

    # [600,660) properly intersects the held [540,630).
    resp = register_coop(c3["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_COOP_SCHEDULE_OVERLAP)
    c3_after = get_success_data(api.get_coop_class(c3["id"], REGISTRAR))
    assert c3_after["seats_taken"] == 0, "rejection does not hold a seat"


def test_coop_grade_ineligible_rejected(api):
    """PRD §3.7: "the enrollment's `grade_level` must fall within the class's
    grade band (else `ERR_COOP_GRADE_INELIGIBLE`)"

    Design: Corner/validations/coop_grade_ineligible_rejected
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 9, family_name="Fam Gi",
                                  district_code="D-52", date_of_birth="2011-01-01")
    coop_class = create_open_coop_class(year["id"], title="Kids Crafts",
                                        meeting_day="FRI", grade_min=0, grade_max=6,
                                        start_date="2026-09-20", fee_base_cents=2000,
                                        materials_fee_cents=0)
    resp = register_coop(coop_class["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_COOP_GRADE_INELIGIBLE)


def test_coop_class_not_open_rejected(api):
    """PRD §3.7: "Registration then passes through its gates: the class must be
    `OPEN` (else `ERR_COOP_CLASS_NOT_OPEN`)"

    Design: Corner/errors/coop_class_not_open_rejected
    """
    year = create_open_year()
    ctx = setup_active_enrollment(year["id"], 4, family_name="Fam Cn",
                                  district_code="D-76")
    coop_class = create_coop_class(year["id"], title="DraftOnly", meeting_day="FRI",
                                   start_date="2026-09-20", fee_base_cents=2000,
                                   materials_fee_cents=0)
    # Class never opened; the OCC version read is fresh, so the state gate fires.
    resp = register_coop(coop_class["id"], ctx["enrollment"]["id"], ctx["family"]["id"])
    validate_error(resp, ApiErrorId.ERR_COOP_CLASS_NOT_OPEN)
    items, meta = validate_paginated(
        api.list_coop_enrollments(coop_class["id"], REGISTRAR)
    )
    assert meta["total_count"] == 0


def test_coop_class_cancel_from_draft_rejected(api):
    """PRD §3.7: "A registrar may instead cancel a class from `OPEN` or
    `IN_SESSION`; cancellation drops every `CONFIRMED` enrollment with
    `drop_reason` `SCHOOL_CANCEL` and a full refund — `refund_cents` equal to the
    entire `fee_cents`, no administrative fee, materials included — crediting
    each family ledger, cancels every `WAITLISTED` enrollment (which was never
    charged), recomputes `seats_taken` to zero, and increments the class's
    `version`."
    PRD §2.8: "State feasibility: the target resource's current state must permit
    the operation."

    Design: Corner/state_machines/coop_class_cancel_from_draft_rejected
    """
    year = create_open_year()
    coop_class = create_coop_class(year["id"], title="Drafty", meeting_day="THU",
                                   start_date="2026-09-01", fee_base_cents=1000,
                                   materials_fee_cents=0)
    resp = api.cancel_coop_class(coop_class["id"], REGISTRAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
