"""Two reserved calendars: a facility's on-site audit window, which is half-open,
and a product's scheduled-sampling exclusion interval, which is closed.
"""

from test_helpers import (
    AirHandlingClass,
    ApiErrorId,
    AuditType,
    GlutenContainingOperations,
    IngredientSpec,
    LotTestType,
    RiskClass,
    create_facility,
    make_admin_headers,
    make_auditor_headers,
    make_lab_technician_headers,
    read_applicant,
    read_audit,
    read_product,
    record_lot_test,
    schedule_audit,
    set_clock,
    setup_applicant_with_facility,
    setup_certification_ready_product,
    start_audit,
    validate_error,
    validate_paginated,
)

AUDIT_DAY = "2026-08-10"
FIRST_SAMPLE_DAY = "2026-08-12T00:00:00Z"
LAST_BLOCKED_DAY = "2026-11-10T00:00:00Z"
FIRST_FREE_DAY = "2026-11-11T00:00:00Z"

TWO_LINES = (
    IngredientSpec(
        name="Brown Rice Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        inclusion_pct=60,
        doc_expires_on="2028-07-01T00:00:00Z",
    ),
    IngredientSpec(
        name="Millet Flour",
        risk_class=RiskClass.INHERENTLY_GF,
        inclusion_pct=40,
        doc_expires_on="2028-07-01T00:00:00Z",
    ),
)


def _a_day_tiled_with_touching_audits(api):
    """Facility A carries three audits that tile 2026-08-10 without overlapping —
    [06:00,08:00), [08:00,16:00) and [16:00,18:00) — and facility B carries one audit
    over exactly the same [08:00,16:00) window as A's middle one.

    The middle audit is then started, so the busy facility's contended window belongs
    to an IN_PROGRESS row rather than a merely SCHEDULED one.
    """
    context = setup_applicant_with_facility(api, clock="2026-08-01T00:00:00Z")
    facility_b = create_facility(
        api,
        context.applicant_id,
        site_name="Plant 9",
        air_handling_class=AirHandlingClass.DEDICATED_NEGATIVE_PRESSURE,
        shared_equipment_present=False,
        gluten_containing_operations=GlutenContainingOperations.NONE,
    )

    middle = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.INITIAL,
        onsite_start_at=f"{AUDIT_DAY}T08:00:00Z",
        onsite_end_at=f"{AUDIT_DAY}T16:00:00Z",
    )
    right = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.SURVEILLANCE,
        onsite_start_at=f"{AUDIT_DAY}T16:00:00Z",
        onsite_end_at=f"{AUDIT_DAY}T18:00:00Z",
    )
    left = schedule_audit(
        api,
        context.facility_id,
        audit_type=AuditType.FOR_CAUSE,
        onsite_start_at=f"{AUDIT_DAY}T06:00:00Z",
        onsite_end_at=f"{AUDIT_DAY}T08:00:00Z",
        auditor_user_id="aud-2",
    )
    other_site = schedule_audit(
        api,
        facility_b["id"],
        audit_type=AuditType.INITIAL,
        onsite_start_at=f"{AUDIT_DAY}T08:00:00Z",
        onsite_end_at=f"{AUDIT_DAY}T16:00:00Z",
        auditor_user_id="aud-2",
    )

    set_clock(api, f"{AUDIT_DAY}T08:30:00Z")
    start_audit(api, middle["id"])
    return context, facility_b, {
        "middle": middle,
        "right": right,
        "left": left,
        "other_site": other_site,
    }


def test_windows_that_only_touch_are_all_accepted_on_the_same_facility(api):
    """Three audits sharing endpoints at 08:00 and 16:00 are all SCHEDULED, and a
    fourth on another site may hold the identical middle window.

    PRD: "The interval is **half-open** — inclusive of its start, exclusive of its
    end — and it reserves the site: a new audit may not overlap the interval of any
    other audit of the same facility whose `status` is `SCHEDULED` or `IN_PROGRESS`,
    though because the end is exclusive an audit that begins exactly at an existing
    audit's `onsite_end_at` is accepted."

    Design: Difficulty/resource_temporal_overlap/audit_window_half_open_so_touching_is_free_and_one_second_overlap_is_not
    """
    _context, _facility_b, audits = _a_day_tiled_with_touching_audits(api)

    assert audits["left"]["status"] == "SCHEDULED"
    assert audits["right"]["status"] == "SCHEDULED"
    assert audits["other_site"]["status"] == "SCHEDULED"
    assert audits["left"]["onsite_end_at"] == f"{AUDIT_DAY}T08:00:00Z"
    assert audits["right"]["onsite_start_at"] == f"{AUDIT_DAY}T16:00:00Z"

    started = read_audit(api, audits["middle"]["id"])
    assert started["status"] == "IN_PROGRESS"
    assert started["lead_auditor_user_id"] == "aud-1"


def test_a_one_second_intrusion_into_an_in_progress_window_is_refused(api):
    """Asking for [15:59:59,16:30:00) overlaps the running audit by a single second,
    which is a 409 conflict.

    PRD: "**On-site window free.** A newly scheduled audit's half-open interval from
    `onsite_start_at` up to but excluding `onsite_end_at` does not overlap the
    interval of any other audit of the same facility whose `status` is `SCHEDULED` or
    `IN_PROGRESS`. Because the interval is half-open, an audit starting exactly at an
    existing audit's `onsite_end_at` is accepted. A breach is
    `ERR_AUDIT_WINDOW_CONFLICT` (409)."

    Design: Difficulty/resource_temporal_overlap/audit_window_half_open_so_touching_is_free_and_one_second_overlap_is_not
    """
    context, facility_b, _audits = _a_day_tiled_with_touching_audits(api)

    response = api.create_audit(
        make_auditor_headers("aud-2"),
        facility_id=context.facility_id,
        audit_type=AuditType.SURVEILLANCE,
        onsite_start_at=f"{AUDIT_DAY}T15:59:59Z",
        onsite_end_at=f"{AUDIT_DAY}T16:30:00Z",
    )
    validate_error(response, ApiErrorId.AUDIT_WINDOW_CONFLICT, 409)

    _rows, meta_a = validate_paginated(
        api.list_audits(make_admin_headers(), facility_id=context.facility_id)
    )
    assert meta_a["total_count"] == 3
    _rows_b, meta_b = validate_paginated(
        api.list_audits(make_admin_headers(), facility_id=facility_b["id"])
    )
    assert meta_b["total_count"] == 1


def _a_sampling_calendar_with_one_august_lot(api):
    """A two-line product whose plan gives a 91-day exclusion span, with a SCHEDULED
    lot on 2026-08-12 that blocks scheduled sampling through 2026-11-10 inclusive.

    An UNANNOUNCED lot is then pulled on the last blocked day and a SCHEDULED lot on
    the first free day, so the calendar holds one blocked interval that is already in
    the past relative to the newest scheduled lot.
    """
    context = setup_certification_ready_product(
        api,
        clock="2026-08-01T00:00:00Z",
        sanitation_validated_on="2026-08-01T00:00:00Z",
        ingredients=TWO_LINES,
        product_overrides={"name": "Multigrain Rice Loaf", "sku": "MRL-001"},
        review_label_decision=None,
        run_audit=False,
    )
    product = read_product(api, context.product_id)
    assert product["threshold_ppm"] == 10
    assert product["sampling_lots_per_year"] == 4
    assert product["sampling_exclusion_days"] == 91

    set_clock(api, FIRST_SAMPLE_DAY)
    august = record_lot_test(
        api,
        context.product_id,
        lot_code="L-2608-A",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=FIRST_SAMPLE_DAY,
        ppm_result=3.0,
    )
    set_clock(api, "2026-11-10T12:00:00Z")
    unannounced = record_lot_test(
        api,
        context.product_id,
        lot_code="L-2611-B",
        test_type=LotTestType.UNANNOUNCED,
        sample_collected_on=LAST_BLOCKED_DAY,
        ppm_result=4.0,
    )
    set_clock(api, FIRST_FREE_DAY)
    november = record_lot_test(
        api,
        context.product_id,
        lot_code="L-2611-C",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=FIRST_FREE_DAY,
        ppm_result=2.0,
    )
    return context, august, unannounced, november


def test_an_unannounced_lot_ignores_the_interval_that_the_next_scheduled_one_waits_out(api):
    """The UNANNOUNCED lot is accepted on the last blocked day, and the next SCHEDULED
    lot is accepted on the first day outside the closed interval.

    PRD: "That interval is closed and runs from the earlier lot's
    `sample_collected_on` through the day one day short of `sampling_exclusion_days`
    later — so with an exclusion span of 7 days, a sample on the earlier lot's date
    and each of the six days after it are all blocked, and the seventh day after is
    free."
    PRD: "`UNANNOUNCED` and `FOR_CAUSE` lots are entirely exempt from this interval
    and may be pulled at any time."

    Design: Difficulty/resource_temporal_overlap/scheduled_lot_sampling_exclusion_is_a_closed_interval_that_unannounced_lots_ignore
    """
    context, august, unannounced, november = _a_sampling_calendar_with_one_august_lot(api)

    assert august["verdict"] == "PASS"
    assert unannounced["status"] == "RECORDED"
    assert unannounced["verdict"] == "PASS"
    assert november["verdict"] == "PASS"

    product = read_product(api, context.product_id)
    assert product["last_scheduled_sample_on"] == FIRST_FREE_DAY
    assert product["testing_plan_status"] == "ACTIVE"


def test_a_back_dated_scheduled_lot_is_judged_against_every_earlier_window(api):
    """Back-dating a SCHEDULED lot to 2026-11-10 collides with the August lot's
    interval even though the newest scheduled lot's own window would allow it.

    PRD: "**Sampling exclusion window respected.** For a `SCHEDULED` lot only,
    `sample_collected_on` falls outside every exclusion interval described in §3.6 —
    otherwise `ERR_SAMPLING_EXCLUSION_WINDOW` (409). `UNANNOUNCED` and `FOR_CAUSE`
    lots are exempt."
    PRD: "For a `SCHEDULED` lot only, `sample_collected_on` must fall outside the
    exclusion interval of every existing `SCHEDULED` lot test of the same product
    whose `status` is `RECORDED`."

    Design: Difficulty/resource_temporal_overlap/scheduled_lot_sampling_exclusion_is_a_closed_interval_that_unannounced_lots_ignore
    """
    context, _august, _unannounced, _november = _a_sampling_calendar_with_one_august_lot(api)

    response = api.create_lot_test(
        make_lab_technician_headers(),
        product_id=context.product_id,
        lot_code="L-2611-D",
        test_type=LotTestType.SCHEDULED,
        sample_collected_on=LAST_BLOCKED_DAY,
        ppm_result=1.0,
        lab_method="R5_ELISA",
    )
    validate_error(response, ApiErrorId.SAMPLING_EXCLUSION_WINDOW, 409)

    _lots, lot_meta = validate_paginated(
        api.list_lot_tests(make_admin_headers(), product_id=context.product_id)
    )
    assert lot_meta["total_count"] == 3

    _findings, finding_meta = validate_paginated(
        api.list_nonconformances(make_admin_headers(), applicant_id=context.applicant_id)
    )
    assert finding_meta["total_count"] == 0
    assert read_applicant(api, context.applicant_id)["posture_score_cycle"] == 100
