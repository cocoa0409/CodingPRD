"""Visit logging, the per-volunteer overlap gate, validation-priority precedence,
and monthly contact-compliance (standard vs strict variants).

Queue A (Difficulty): dual_variant_calc (compliance), combinatorial_formula
(rounding order), resource_temporal_overlap (visit half-open), and
priority_pair_validation_conflict (referential beats safety).
Queue B (Corner): enum/ordering validation, duration, reverse reachability.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    onboard_active_volunteer,
    make_volunteer_headers,
    setup_active_volunteer_assigned_case,
    setup_compliance_case,
    log_visit,
)

ADMIN = TEST_USERS["program_admin_headers"]


# --------------------- Difficulty: STANDARD vs STRICT compliance divergence
def test_standard_compliance_counts_video(api):
    """PRD 3.8: "In the live standard variant that feeds `contact_compliance_pct`,
    the qualifying contact types are `IN_PERSON` and `VIDEO`."

    Design: Difficulty/dual_variant_calc/compliance_standard_vs_strict_diverge
    """
    base = setup_compliance_case(api)
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["contact_compliance_pct"] == 66.5, \
        f"STANDARD compliance must be 66.5, got {case['contact_compliance_pct']}"


def test_strict_compliance_excludes_video_at_close(api):
    """PRD 3.8: "the read-only audit_compliance_pct is pinned using the strict
    variant of the same compliance calculation — identical in every respect
    except that only IN_PERSON contacts qualify, so VIDEO, PHONE, and COLLATERAL
    visits do not count; this field is null until the case is closed."

    Design: Difficulty/dual_variant_calc/compliance_standard_vs_strict_diverge
    """
    base = setup_compliance_case(api)
    closed = get_success_data(api.close_case(
        base["case_id"], {"outcome": "REUNIFICATION"}, base["supervisor_headers"]))
    assert closed["audit_compliance_pct"] == 50.0, \
        f"STRICT compliance must be 50.0, got {closed['audit_compliance_pct']}"


# --------------------- Difficulty: per-month-first rounding order (66.5 not 66.7)
def test_compliance_uses_per_month_rounding(api):
    """PRD 3.8: "each month score is rounded to two decimals first, only then are
    the month scores summed, divided by the month count, multiplied by 100, and
    rounded to one decimal — rounding the raw ratios only at the end would produce
    a different number and is not used."

    Design: Difficulty/combinatorial_formula/compliance_rounding_order_mode_b
    """
    base = setup_compliance_case(api)
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["contact_compliance_pct"] == 66.5


def test_compliance_not_end_only_rounding(api):
    """PRD 3.8: "rounding the raw ratios only at the end would produce a different
    number and is not used."

    Design: Difficulty/combinatorial_formula/compliance_rounding_order_mode_b
    """
    base = setup_compliance_case(api)
    case = get_success_data(api.get_case(base["case_id"], base["supervisor_headers"]))
    assert case["contact_compliance_pct"] != 66.7, \
        "end-only rounding (66.7) must not be used"


# ------------------------ Difficulty: half-open visit overlap on the volunteer
def test_overlapping_visit_rejected(api):
    """PRD 3.4: "the new visit is rejected with ERR_VISIT_OVERLAP if there exists
    such a logged visit whose interval and the new one overlap — that is, when the
    new contact_start is before the existing visit's contact_end and the existing
    visit's contact_start is before the new contact_end."

    Design: Difficulty/resource_temporal_overlap/visit_halfopen_interval_overlap_on_volunteer
    """
    base = setup_active_volunteer_assigned_case(api)
    log_visit(api, base, contact_start="2026-06-05T10:00:00Z",
              contact_end="2026-06-05T11:00:00Z")
    resp = api.create_visit(base["case_id"], {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-05T10:30:00Z",
        "contact_end": "2026-06-05T11:30:00Z", "miles": 10}, base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_VISIT_OVERLAP.value)


def test_adjacent_visit_allowed(api):
    """PRD 3.4: "Exact adjacency, where one interval's end equals the other's
    start, does not overlap and is allowed; voided visits are ignored entirely."

    Design: Difficulty/resource_temporal_overlap/visit_halfopen_interval_overlap_on_volunteer
    """
    base = setup_active_volunteer_assigned_case(api)
    log_visit(api, base, contact_start="2026-06-05T10:00:00Z",
              contact_end="2026-06-05T11:00:00Z")
    resp = api.create_visit(base["case_id"], {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-05T11:00:00Z",
        "contact_end": "2026-06-05T12:00:00Z", "miles": 10}, base["volunteer_headers"])
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "LOGGED"


# ---------------- Difficulty: referential (pri6) beats safety (pri7) on visit log
def test_visit_log_referential_beats_safety(api):
    """PRD 2.10: "Referential integrity — the acting volunteer is the case's
    active-assignment volunteer for visit logging, and a report's hearing belongs
    to the report's case, else ERR_NOT_ASSIGNED_VOLUNTEER or
    ERR_HEARING_CASE_MISMATCH (409)."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_visit_log
    """
    base = setup_active_volunteer_assigned_case(api)  # clock 2026-06-01
    v2 = onboard_active_volunteer(api, email="v2@casa.org", home_zip="94602")
    set_clock(api, "2027-07-01T00:00:00Z")  # v2 background now past its 2027-06-01 expiry
    resp = api.create_visit(base["case_id"], {
        "contact_type": "IN_PERSON",
        "contact_start": "2027-07-02T10:00:00Z",
        "contact_end": "2027-07-02T11:00:00Z", "miles": 10}, make_volunteer_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_VOLUNTEER.value)


def test_visit_log_not_reporting_background_expired(api):
    """PRD 3.4: "The acting volunteer's `background_status` must be `CLEARED` and
    not past expiry, else `ERR_BACKGROUND_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_visit_log
    """
    base = setup_active_volunteer_assigned_case(api)
    v2 = onboard_active_volunteer(api, email="v2@casa.org", home_zip="94602")
    set_clock(api, "2027-07-01T00:00:00Z")
    resp = api.create_visit(base["case_id"], {
        "contact_type": "IN_PERSON",
        "contact_start": "2027-07-02T10:00:00Z",
        "contact_end": "2027-07-02T11:00:00Z", "miles": 10}, make_volunteer_headers(v2["id"]))
    err = validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_VOLUNTEER.value)
    assert err["error_id"] != ApiErrorId.ERR_BACKGROUND_EXPIRED.value, \
        "referential failure must pre-empt the background-expired safety failure"


# ---------------------------------------------------- Corner: visit validation
def test_invalid_contact_type_rejected(api):
    """PRD 3.4: "A `Volunteer` logs a visit by supplying a `contact_type` — one of
    `IN_PERSON`, `VIDEO`, `PHONE`, or `COLLATERAL`".

    Design: Corner/entities/invalid_enum_contact_type_returns_400
    """
    base = setup_active_volunteer_assigned_case(api)
    resp = api.create_visit(base["case_id"], {
        "contact_type": "SMOKE_SIGNAL",
        "contact_start": "2026-06-05T10:00:00Z",
        "contact_end": "2026-06-05T11:00:00Z"}, base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_visit_duration_minutes_computed(api):
    """PRD 3.4: "its read-only duration_minutes is computed as the whole number of
    minutes between contact_start and contact_end."

    Design: Corner/calculations/visit_duration_minutes_computed
    """
    base = setup_active_volunteer_assigned_case(api)
    resp = api.create_visit(base["case_id"], {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-05T10:00:00Z",
        "contact_end": "2026-06-05T11:00:00Z", "miles": 8}, base["volunteer_headers"])
    data = validate_success(resp, expected_status=201)
    assert data["duration_minutes"] == 60


def test_contact_end_not_after_start_rejected(api):
    """PRD 3.4: "a `contact_start` and a `contact_end` (which must be strictly
    after `contact_start`, else `ERR_VALIDATION`)".

    Design: Corner/validations/contact_end_not_after_start_returns_400
    """
    base = setup_active_volunteer_assigned_case(api)
    resp = api.create_visit(base["case_id"], {
        "contact_type": "IN_PERSON",
        "contact_start": "2026-06-05T11:00:00Z",
        "contact_end": "2026-06-05T10:00:00Z"}, base["volunteer_headers"])
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_case_visits_list_reverse_reachable(api):
    """PRD 3.4: "The logged visit begins in LOGGED, its case_id is the case, its
    volunteer_id is set to the case's currently-active-assignment volunteer at log
    time, and its read-only duration_minutes is computed as the whole number of
    minutes between contact_start and contact_end."
    PRD 2.3: "Every list response echoes limit, offset, total_count, and has_more
    inside the meta object."

    Design: Corner/endpoints/reverse_reachability_case_visits_list
    """
    base = setup_active_volunteer_assigned_case(api)
    visit = log_visit(api, base, contact_start="2026-06-05T10:00:00Z",
                      contact_end="2026-06-05T11:00:00Z", miles=8)
    data, meta = validate_paginated(
        api.list_case_visits(base["case_id"], base["supervisor_headers"]))
    assert len(data) == 1 and data[0]["id"] == visit["id"]
