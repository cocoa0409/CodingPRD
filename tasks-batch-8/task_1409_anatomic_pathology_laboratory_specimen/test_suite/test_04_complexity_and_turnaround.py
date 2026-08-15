"""Case complexity classification, turnaround deadline variants, TAT breach
boundary, and wet-tissue retention disposal."""
from test_helpers import (
    ADMIN_HEADERS,
    HISTOTECH_HEADERS,
    ApiErrorId,
    accession_specimen,
    assert_instant_equal,
    assign_case,
    create_block,
    create_case,
    create_patient,
    create_slide,
    create_stain_order,
    create_pathologist,
    embed_block,
    get_case,
    get_specimen,
    gross_specimen,
    iso_after,
    make_pathologist_headers,
    qc_review_slide,
    section_slide,
    set_clock,
    setup_pending_signout_case,
    setup_workup_case,
    sign_out_case,
    stain_complete_slide,
    submit_for_signout,
    validate_error,
    validate_success,
)


def test_complexity_tier_boundary_exact_4_is_moderate(api):
    """PRD §3.3: "The score maps to `complexity_class` with inclusive lower and
    exclusive upper bounds: below 4.0 is `SIMPLE`, 4.0 up to but not including
    10.0 is `MODERATE`, 10.0 up to but not including 20.0 is `COMPLEX`, and
    20.0 or more is `HIGH_COMPLEXITY`."
    PRD §3.3: "A case's `complexity_score` is the maximum specimen base weight
    among its non-`REJECTED` specimens — 1 for `BIOPSY`, 2 for `EXCISION`, 3
    for `RESECTION`, 0 for `CYTOLOGY`, and 0 when no non-rejected specimen
    exists — plus 1.0 for every block of the case regardless of block status
    (`DEPLETED` included), plus 0.5 for every slide of the case that is not
    `CANCELLED`, plus 2.0 for every stain order of the case in `ORDERED`,
    `IN_PROGRESS`, or `RESULTED`."

    Design: Corner/calculations/complexity_tier_boundary_exact_4_is_moderate
    """
    # Case A: BIOPSY base 1 + 2 blocks + 2 slides = 4.0 -> MODERATE.
    ctx_a = setup_workup_case(mrn="MRN-C1", num_blocks=2, slides_per_block=1)
    case_a = get_case(ctx_a["case"]["id"])
    assert case_a["complexity_score"] == 4.0
    assert case_a["complexity_class"] == "MODERATE", (
        "the lower tier bound 4.0 is inclusive"
    )

    # Case B: BIOPSY base 1 + 2 blocks + 1 slide = 3.5 -> SIMPLE.
    ctx_b = setup_workup_case(num_blocks=2, slides_per_block=0)
    extra = create_slide(ctx_b["blocks"][0]["id"], slide_label="A1-1")
    assert extra["status"] == "ORDERED"
    case_b = get_case(ctx_b["case"]["id"])
    assert case_b["complexity_score"] == 3.5
    assert case_b["complexity_class"] == "SIMPLE"


def test_complexity_score_tiered_classification_moderate(api):
    """PRD §3.3: "A case's `complexity_score` is the maximum specimen base
    weight among its non-`REJECTED` specimens — 1 for `BIOPSY`, 2 for
    `EXCISION`, 3 for `RESECTION`, 0 for `CYTOLOGY`, and 0 when no non-rejected
    specimen exists — plus 1.0 for every block of the case regardless of block
    status (`DEPLETED` included), plus 0.5 for every slide of the case that is
    not `CANCELLED`, plus 2.0 for every stain order of the case in `ORDERED`,
    `IN_PROGRESS`, or `RESULTED`."
    PRD §3.1: "The allowance added to the base depends on the case's
    `complexity_class`: 48 hours for `SIMPLE`, 72 for `MODERATE`, 120 for
    `COMPLEX`, and 168 for `HIGH_COMPLEXITY`."

    Design: Difficulty/combinatorial_formula/complexity_score_tiered_classification
    """
    pathologist = create_pathologist(full_name="Dr Order")
    ctx = setup_workup_case(
        mrn="MRN-300",
        tat_mode="CALENDAR",
        specimen_type="RESECTION",
        anatomical_site="Sigmoid colon",
        container_count=2,
        num_blocks=2,
        slides_per_block=0,
    )
    case_id = ctx["case"]["id"]
    b1, b2 = ctx["blocks"]
    create_slide(b1["id"], slide_label="A1-1")
    create_slide(b1["id"], slide_label="A1-2")
    create_slide(b2["id"], slide_label="A2-1")
    create_stain_order(case_id, b1["id"], "HER2_IHC", pathologist["id"])

    case = get_case(case_id)
    # 3 (RESECTION base) + 2*1.0 (blocks) + 3*0.5 (slides) + 1*2.0 (stain) = 8.5.
    assert case["complexity_score"] == 8.5
    assert case["complexity_class"] == "MODERATE"
    # MODERATE allowance 72h from tat_base 2026-08-03T10:00:00Z.
    assert_instant_equal(
        case["turnaround_deadline"], "2026-08-06T10:00:00Z", "MODERATE deadline"
    )


def test_complexity_score_tiered_classification_crosses_to_complex(api):
    """PRD §3.3: "The score maps to `complexity_class` with inclusive lower and
    exclusive upper bounds: below 4.0 is `SIMPLE`, 4.0 up to but not including
    10.0 is `MODERATE`, 10.0 up to but not including 20.0 is `COMPLEX`, and
    20.0 or more is `HIGH_COMPLEXITY`."
    PRD §3.3: "on any change of `complexity_class` the `turnaround_deadline` is
    recomputed and `tat_breached` re-evaluated, since the deadline allowance
    depends on the class."

    Design: Difficulty/combinatorial_formula/complexity_score_tiered_classification
    """
    pathologist = create_pathologist(full_name="Dr Order")
    ctx = setup_workup_case(
        mrn="MRN-300",
        tat_mode="CALENDAR",
        specimen_type="RESECTION",
        anatomical_site="Sigmoid colon",
        container_count=2,
        num_blocks=2,
        slides_per_block=0,
    )
    case_id = ctx["case"]["id"]
    b1, b2 = ctx["blocks"]
    create_slide(b1["id"], slide_label="A1-1")
    create_slide(b1["id"], slide_label="A1-2")
    create_slide(b2["id"], slide_label="A2-1")
    create_stain_order(case_id, b1["id"], "HER2_IHC", pathologist["id"])
    assert get_case(case_id)["complexity_score"] == 8.5

    order2 = create_stain_order(case_id, b2["id"], "KI67", pathologist["id"])
    assert order2["status"] == "ORDERED"

    case = get_case(case_id)
    # 8.5 + 2.0 (second stain) = 10.5, crossing the inclusive 10.0 COMPLEX bound.
    assert case["complexity_score"] == 10.5
    assert case["complexity_class"] == "COMPLEX"
    # COMPLEX allowance 120h from tat_base 2026-08-03T10:00:00Z.
    assert_instant_equal(
        case["turnaround_deadline"], "2026-08-08T10:00:00Z", "COMPLEX deadline"
    )


def _tat_case(api, tat_mode, mrn="MRN-100"):
    """One CALENDAR/BUSINESS_HOURS GI case with a single BIOPSY specimen
    received Friday 2026-08-07T16:00:00Z; returns the fetched case."""
    patient = create_patient(mrn=mrn, full_name="Pat One", date_of_birth="1975-03-20")
    case = create_case(patient["id"], subspecialty="GI", tat_mode=tat_mode)
    accession_specimen(
        case["id"],
        patient_mrn=mrn,
        patient_dob="1975-03-20",
        collection_datetime="2026-08-07T15:30:00Z",
        received_datetime="2026-08-07T16:00:00Z",
    )
    return get_case(case["id"])


def test_tat_deadline_calendar_variant(api):
    """PRD §3.1: "The turnaround mode selects the deadline variant: `CALENDAR`,
    the default when omitted, counts plain clock hours with weekends and nights
    included"
    PRD §3.1: "The allowance added to the base depends on the case's
    `complexity_class`: 48 hours for `SIMPLE`, 72 for `MODERATE`, 120 for
    `COMPLEX`, and 168 for `HIGH_COMPLEXITY`."

    Design: Difficulty/dual_variant_calc/tat_deadline_calendar_vs_business_hours
    """
    case = _tat_case(api, "CALENDAR")
    assert case["complexity_class"] == "SIMPLE"
    assert_instant_equal(case["tat_base_time"], "2026-08-07T16:00:00Z", "tat_base_time")
    # 48 plain clock hours from Friday 16:00 (weekend counts).
    assert_instant_equal(
        case["turnaround_deadline"], "2026-08-09T16:00:00Z", "CALENDAR deadline"
    )


def test_tat_deadline_business_hours_variant(api):
    """PRD §3.1: "while `BUSINESS_HOURS` counts only Monday-through-Friday
    business time between 08:00 and 17:00 UTC — nine business hours per day.
    Under `BUSINESS_HOURS`, the base time is first advanced into the business
    window: a base before 08:00 moves to 08:00 the same day, and a base at or
    after 17:00, or falling on a Saturday or Sunday, moves to 08:00 on the next
    business day; only then are the allotted hours consumed."
    PRD §3.1: "Identical inputs therefore yield a later deadline under
    `BUSINESS_HOURS` than under `CALENDAR` whenever any weekend or off-hours
    time intervenes."

    Design: Difficulty/dual_variant_calc/tat_deadline_calendar_vs_business_hours
    """
    calendar_case = _tat_case(api, "CALENDAR", mrn="MRN-100")
    business_case = _tat_case(api, "BUSINESS_HOURS", mrn="MRN-100B")
    assert business_case["complexity_class"] == "SIMPLE"
    # 48 business hours from Friday 16:00: Fri 1h + next Mon-Fri 45h + Mon 2h.
    assert_instant_equal(
        business_case["turnaround_deadline"],
        "2026-08-17T10:00:00Z",
        "BUSINESS_HOURS deadline",
    )
    assert business_case["turnaround_deadline"] != calendar_case["turnaround_deadline"], (
        "identical inputs must yield a later deadline under BUSINESS_HOURS"
    )


def test_tat_breach_strict_greater_than_deadline_at_equality(api):
    """PRD §3.1: "`tat_breached` is true only when the reference time is
    strictly greater than the deadline — a reference exactly equal to the
    deadline is not a breach — and `breach_minutes` carries the whole-minute
    excess, truncated toward zero, or 0 when the case is not breached."

    Design: Difficulty/boundary_precision_check/tat_breach_strict_greater_than_deadline
    """
    ctx = setup_pending_signout_case(mrn="MRN-700", tat_mode="CALENDAR")
    case_id = ctx["case"]["id"]
    # SIMPLE CALENDAR: deadline = 2026-08-03T10:00:00Z + 48h = 2026-08-05T10:00:00Z.
    set_clock("2026-08-05T10:00:00Z")
    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "on the deadline"},
        make_pathologist_headers(ctx["pathologist"]["id"]),
    )
    signed = validate_success(resp, expected_status=200)
    assert_instant_equal(signed["finalized_at"], "2026-08-05T10:00:00Z", "finalized_at")
    assert signed["tat_breached"] is False, "equality with the deadline is not a breach"
    assert signed["breach_minutes"] == 0


def test_tat_breach_one_hour_past_deadline(api):
    """PRD §3.1: "`tat_breached` is true only when the reference time is
    strictly greater than the deadline — a reference exactly equal to the
    deadline is not a breach — and `breach_minutes` carries the whole-minute
    excess, truncated toward zero, or 0 when the case is not breached."
    PRD §3.1: "for a case in `FINAL` or `AMENDING` the reference is
    `finalized_at`"

    Design: Difficulty/boundary_precision_check/tat_breach_strict_greater_than_deadline
    """
    ctx = setup_pending_signout_case(mrn="MRN-700", tat_mode="CALENDAR")
    case_id = ctx["case"]["id"]
    set_clock("2026-08-05T11:00:00Z")
    resp = api.sign_out_case(
        case_id,
        {"diagnosis_text": "one hour late"},
        make_pathologist_headers(ctx["pathologist"]["id"]),
    )
    signed = validate_success(resp, expected_status=200)
    assert_instant_equal(signed["finalized_at"], "2026-08-05T11:00:00Z", "finalized_at")
    assert_instant_equal(
        signed["turnaround_deadline"], "2026-08-05T10:00:00Z", "turnaround_deadline"
    )
    assert signed["tat_breached"] is True, "finalized one hour past the deadline"
    assert signed["breach_minutes"] == 60


def test_retention_disposal_before_boundary_rejected(api):
    """PRD §3.2: "disposal requires the specimen to be `COMPLETE` with
    `wet_tissue_disposed_at` still null (otherwise `ERR_SPECIMEN_NOT_COMPLETE`,
    HTTP 409) and the current logical clock to be at or after `retention_until`
    — the boundary is inclusive, so disposal exactly at `retention_until` is
    eligible, while an earlier attempt is rejected with
    `ERR_RETENTION_NOT_ELAPSED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/retention_disposal_inclusive_boundary
    """
    ctx = setup_pending_signout_case(mrn="MRN-701")
    case_id = ctx["case"]["id"]
    specimen_id = ctx["specimen"]["id"]
    set_clock("2026-08-05T14:30:00Z")
    sign_out_case(case_id, ctx["pathologist"]["id"])
    retention_until = get_specimen(specimen_id)["retention_until"]
    assert retention_until is not None, "COMPLETE specimen carries retention_until"

    set_clock(iso_after(retention_until, seconds=-1))
    resp = api.dispose_wet_tissue(specimen_id, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_RETENTION_NOT_ELAPSED)
    assert get_specimen(specimen_id)["wet_tissue_disposed_at"] is None


def test_retention_disposal_at_boundary_succeeds(api):
    """PRD §3.2: "disposal requires the specimen to be `COMPLETE` with
    `wet_tissue_disposed_at` still null (otherwise `ERR_SPECIMEN_NOT_COMPLETE`,
    HTTP 409) and the current logical clock to be at or after `retention_until`
    — the boundary is inclusive, so disposal exactly at `retention_until` is
    eligible, while an earlier attempt is rejected with
    `ERR_RETENTION_NOT_ELAPSED` (HTTP 422). Disposal stamps
    `wet_tissue_disposed_at` and is not a status transition."

    Design: Difficulty/boundary_precision_check/retention_disposal_inclusive_boundary
    """
    ctx = setup_pending_signout_case(mrn="MRN-701")
    case_id = ctx["case"]["id"]
    specimen_id = ctx["specimen"]["id"]
    set_clock("2026-08-05T14:30:00Z")
    sign_out_case(case_id, ctx["pathologist"]["id"])
    retention_until = get_specimen(specimen_id)["retention_until"]

    set_clock(retention_until)
    resp = api.dispose_wet_tissue(specimen_id, HISTOTECH_HEADERS)
    disposed = validate_success(resp, expected_status=200)
    assert_instant_equal(
        disposed["wet_tissue_disposed_at"], retention_until, "wet_tissue_disposed_at"
    )
    assert disposed["status"] == "COMPLETE", "disposal is not a status transition"


def test_dispose_before_case_final_rejected(api):
    """PRD §3.2: "disposal requires the specimen to be `COMPLETE` with
    `wet_tissue_disposed_at` still null (otherwise `ERR_SPECIMEN_NOT_COMPLETE`,
    HTTP 409)"
    PRD §3.2: "A specimen reaches `COMPLETE` only as a cascade of case
    finalization (§3.6), never by direct client action"

    Design: Corner/errors/dispose_before_case_final_rejected
    """
    ctx = setup_workup_case(mrn="MRN-R8", num_blocks=1)
    specimen_id = ctx["specimen"]["id"]
    assert get_specimen(specimen_id)["status"] == "PROCESSING"
    resp = api.dispose_wet_tissue(specimen_id, HISTOTECH_HEADERS)
    validate_error(resp, ApiErrorId.ERR_SPECIMEN_NOT_COMPLETE)
    assert get_specimen(specimen_id)["wet_tissue_disposed_at"] is None
