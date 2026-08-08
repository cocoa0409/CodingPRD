"""Placement creation, license-coverage resolution, and the scheduling/capacity guards."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_assignment_payload, create_license_payload,
)
from test_helpers.fixtures import (
    provision, create_per_diem, create_facility, create_clinician, create_verified_license,
    create_assignment_bundle, get_assignment_data,
)

RECRUITER = TEST_USERS["recruiter_headers"]
CS1 = TEST_USERS["credentialing_specialist_headers"]


def test_assignment_create_computes_end_date_and_hour_partition(api):
    """PRD §3.2: "Its end_date is computed as the start_date plus term_weeks times
    seven days, minus one day, so that the term spans exactly the intended number of
    whole weeks"
    PRD §3.2: "The assignment's guaranteed_hours_total and guaranteed_hours_remaining
    are both set to weekly_guaranteed_hours multiplied by term_weeks, while
    guaranteed_hours_consumed and guaranteed_hours_waived start at 0."

    Design: Corner/entities/corner_assignment_create_computes_end_date_and_hour_partition
    """
    fac = create_facility(api)
    clin = create_clinician(api)
    lic = create_verified_license(api, clin["id"])
    resp = api.create_assignment(create_assignment_payload(clin["id"], fac["id"]), RECRUITER)
    asg = validate_success(resp, 201)
    assert asg["end_date"] == "2026-09-05" and asg["term_weeks"] == 13
    assert asg["staffing_status"] == "DRAFT" and asg["compliance_status"] == "PENDING_CREDENTIALS"
    assert asg["guaranteed_hours_total"] == 468
    assert asg["guaranteed_hours_remaining"] == 468
    assert asg["guaranteed_hours_consumed"] == 0
    assert asg["guaranteed_hours_waived"] == 0
    assert asg["covering_license_id"] == lic["id"]
    assert asg["realized_gross_bill_cents"] == 0 and asg["realized_margin_pct"] == 0


def test_assignment_create_populates_projection_and_child_resources(api):
    """PRD §3.3: "Multiplying each weekly figure by term_weeks gives
    projected_pay_cost_cents and projected_gross_bill_cents; projected_margin_cents is
    the projected gross bill minus the projected pay cost; and projected_margin_pct is
    the projected margin divided by the projected gross bill, rounded half up to four
    decimal places, as a display value only."
    PRD §3.2: "a Contract is created in DRAFT carrying the same term_weeks,
    weekly_guaranteed_hours, base_pay_rate_cents_per_hour, and bill_rate_cents_per_hour;
    its revision_count starts at 0. A CredentialPacket is created in DRAFT with both
    readiness scores at 0 and both blocking counts at 5."

    Design: Corner/entities/corner_assignment_create_computes_end_date_and_hour_partition
    """
    create_per_diem(api)
    fac = create_facility(api)
    clin = create_clinician(api)
    create_verified_license(api, clin["id"])
    asg, con, pkt = create_assignment_bundle(api, clin["id"], fac["id"])
    assert asg["projected_gross_bill_cents"] == 6552000
    assert asg["projected_pay_cost_cents"] == 4967716
    assert asg["projected_margin_cents"] == 1584284
    assert asg["projected_margin_pct"] == 0.2418
    assert con["status"] == "DRAFT" and con["term_weeks"] == 13
    assert con["weekly_guaranteed_hours"] == 36 and con["base_pay_rate_cents_per_hour"] == 5200
    assert con["bill_rate_cents_per_hour"] == 14000 and con["revision_count"] == 0
    assert pkt["status"] == "DRAFT"
    assert pkt["readiness_score_start_basis"] == 0 and pkt["blocking_item_count_start_basis"] == 5
    assert pkt["readiness_score_full_term_basis"] == 0 and pkt["blocking_item_count_full_term_basis"] == 5


def test_assignment_list_filter_isolates_one_clinician(api):
    """PRD §2.10: "These reverse-reachability reads accept the standard pagination
    parameters and, where noted in Section 4, additional filter parameters."
    PRD §4: "GET /assignments | List assignments with filters"

    Design: Corner/entities/corner_assignment_list_filter_isolates_one_clinician
    """
    fac = create_facility(api)
    clin_a = create_clinician(api, full_name="Ada Reyes")
    create_verified_license(api, clin_a["id"])
    clin_b = create_clinician(api, full_name="Ben Osei")
    lic_b = create_verified_license(api, clin_b["id"])
    asg_a, _, _ = create_assignment_bundle(api, clin_a["id"], fac["id"])
    asg_b, _, _ = create_assignment_bundle(api, clin_b["id"], fac["id"])

    data, meta = validate_paginated(api.list_assignments(RECRUITER))
    assert meta["total_count"] == 2
    data_a, meta_a = validate_paginated(api.list_assignments(RECRUITER, params={"clinician_id": clin_a["id"]}))
    assert meta_a["total_count"] == 1 and data_a[0]["id"] == asg_a["id"]
    data_b, _ = validate_paginated(api.list_assignments(RECRUITER, params={"clinician_id": clin_b["id"]}))
    assert data_b[0]["id"] == asg_b["id"]
    data_lic, _ = validate_paginated(api.list_assignments(RECRUITER, params={"covering_license_id": lic_b["id"]}))
    assert len(data_lic) == 1 and data_lic[0]["id"] == asg_b["id"]


def test_facility_not_found_on_assignment_create(api):
    """PRD §3.2: "if the facility_id does not resolve the error is ERR_FACILITY_NOT_FOUND."
    PRD §2.8: "6. Body foreign keys — every foreign key in the body resolves to an
    existing row, else the matching not-found error." (before the priority-12 licensure check)

    Design: Corner/errors/corner_facility_not_found_on_assignment_create
    """
    clin = create_clinician(api)
    create_verified_license(api, clin["id"])
    resp = api.create_assignment(
        create_assignment_payload(clin["id"], "12121212-3434-4565-8787-909090909090"), RECRUITER)
    validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_FOUND.value)


def test_licenses_sub_resource_read_is_filtered_and_paginated(api):
    """PRD §2.10: "Several read endpoints expose a child collection reachable from a
    parent id embedded in the URL path (for example, the licenses of a clinician ...)."
    PRD §2.3: "The meta block of a list response reports limit, offset, total_count ...
    and has_more (true when rows remain beyond the current page)."

    Design: Corner/entities/corner_licenses_sub_resource_read_is_filtered_and_paginated
    """
    clin = create_clinician(api)
    lic_tx = create_verified_license(api, clin["id"], state_code="TX", license_number="TX-1")
    create_verified_license(api, clin["id"], state_code="AZ", license_number="AZ-1",
                            is_compact=False, verify=False)
    create_verified_license(api, clin["id"], state_code="NM", license_number="NM-1",
                            is_compact=False, verify=False)
    data, meta = validate_paginated(api.list_clinician_licenses(clin["id"], RECRUITER))
    assert meta["total_count"] == 3 and meta["has_more"] is False
    assert meta["limit"] == 10 and meta["offset"] == 0
    data_v, _ = validate_paginated(api.list_clinician_licenses(clin["id"], RECRUITER, params={"status": "VERIFIED"}))
    assert len(data_v) == 1 and data_v[0]["id"] == lic_tx["id"]
    data_p, meta_p = validate_paginated(
        api.list_clinician_licenses(clin["id"], RECRUITER, params={"limit": 2, "offset": 0}))
    assert len(data_p) == 2 and meta_p["total_count"] == 3 and meta_p["has_more"] is True


# --- Difficulty: safety priority (license coverage) beats constraint priority (capacity) ---
def test_license_coverage_error_beats_facility_capacity(api):
    """PRD §2.8: "12. License-coverage guard, else ERR_LICENSE_COVERAGE_MISSING." then
    "17. Facility capacity, else ERR_FACILITY_CAPACITY_EXCEEDED."
    PRD §2.8: "the first check that fails determines the returned error."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_beats_constraint_priority_on_assignment_create
    """
    ctx = provision(api, facility_overrides={"name": "Mesa Regional", "max_concurrent_travelers": 1},
                     contract_stage="executed")  # clinician A now PENDING_START, capacity 1 reached
    clin_b = create_clinician(api, full_name="Ben Osei")  # NO license at all
    resp = api.create_assignment(create_assignment_payload(clin_b["id"], ctx.fac_id), RECRUITER)
    validate_error(resp, ApiErrorId.ERR_LICENSE_COVERAGE_MISSING.value)


def test_no_assignment_created_on_license_coverage_rejection(api):
    """PRD §2.8: "the first check that fails determines the returned error" — a rejected
    POST /assignments must persist nothing.
    PRD §3.2: "if no license covers the window the whole creation is rejected with
    ERR_LICENSE_COVERAGE_MISSING."

    Design: Difficulty/priority_pair_validation_conflict/safety_priority_beats_constraint_priority_on_assignment_create
    """
    ctx = provision(api, facility_overrides={"name": "Mesa Regional", "max_concurrent_travelers": 1},
                     contract_stage="executed")
    clin_b = create_clinician(api, full_name="Ben Osei")
    api.create_assignment(create_assignment_payload(clin_b["id"], ctx.fac_id), RECRUITER)
    data_b, meta_b = validate_paginated(api.list_assignments(RECRUITER, params={"clinician_id": clin_b["id"]}))
    assert data_b == [] and meta_b["total_count"] == 0
    assert get_assignment_data(api, ctx.asg_id)["staffing_status"] == "PENDING_START"


# --- Difficulty: clinician schedule conflict uses buffered closed interval ---
def test_schedule_conflict_uses_buffered_travel_gap(api):
    """PRD §3.2: "no other assignment of the same clinician whose staffing_status is
    DRAFT, PENDING_START, or ACTIVE may overlap the new assignment's date interval once
    that interval is expanded by a two-day travel gap on both sides: a conflict exists
    when the new assignment's start_date minus two days is on or before the other
    assignment's end_date and the other assignment's start_date is on or before the new
    assignment's end_date plus two days (closed, buffered intervals). A conflict is
    rejected with ERR_CLINICIAN_SCHEDULE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/clinician_schedule_conflict_uses_buffered_closed_interval_travel_gap
    """
    ctx = provision(api)  # DRAFT assignment 2026-06-07 .. 2026-09-05
    assert get_assignment_data(api, ctx.asg_id)["end_date"] == "2026-09-05"
    resp = api.create_assignment(
        create_assignment_payload(ctx.clin_id, ctx.fac_id, start_date="2026-09-06"), RECRUITER)
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SCHEDULE_CONFLICT.value)


def test_schedule_conflict_leaves_only_the_original_assignment(api):
    """PRD §3.2: "A conflict is rejected with ERR_CLINICIAN_SCHEDULE_CONFLICT." — the
    rejected placement creates no new row even though 2026-09-06 is strictly after the
    prior end_date of 2026-09-05.

    Design: Difficulty/resource_temporal_overlap/clinician_schedule_conflict_uses_buffered_closed_interval_travel_gap
    """
    ctx = provision(api)
    api.create_assignment(
        create_assignment_payload(ctx.clin_id, ctx.fac_id, start_date="2026-09-06"), RECRUITER)
    data, meta = validate_paginated(api.list_assignments(RECRUITER, params={"clinician_id": ctx.clin_id}))
    assert len(data) == 1 and meta["total_count"] == 1


# --- Difficulty: facility capacity uses unbuffered aggregate interval count ---
def test_facility_capacity_exceeded_on_overlapping_placement(api):
    """PRD §3.2: "counting the facility's assignments whose staffing_status is
    PENDING_START or ACTIVE and whose unbuffered closed interval [start_date, end_date]
    intersects the new assignment's interval, that count must be strictly less than the
    facility's max_concurrent_travelers; if it has already reached that capacity the
    placement is rejected with ERR_FACILITY_CAPACITY_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/facility_capacity_uses_unbuffered_aggregate_interval_count
    """
    ctx = provision(api, facility_overrides={"name": "Mesa Regional", "max_concurrent_travelers": 1},
                     contract_stage="executed")  # A PENDING_START 2026-06-07 .. 2026-09-05
    clin_b = create_clinician(api, full_name="Ben Osei")
    create_verified_license(api, clin_b["id"])
    resp = api.create_assignment(
        create_assignment_payload(clin_b["id"], ctx.fac_id, start_date="2026-08-30"), RECRUITER)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED.value)


def test_facility_capacity_rejection_leaves_count_unchanged(api):
    """PRD §3.2: "if it has already reached that capacity the placement is rejected with
    ERR_FACILITY_CAPACITY_EXCEEDED." — the existing PENDING_START placement is untouched
    and no second facility row is created.

    Design: Difficulty/resource_temporal_overlap/facility_capacity_uses_unbuffered_aggregate_interval_count
    """
    ctx = provision(api, facility_overrides={"name": "Mesa Regional", "max_concurrent_travelers": 1},
                     contract_stage="executed")
    clin_b = create_clinician(api, full_name="Ben Osei")
    create_verified_license(api, clin_b["id"])
    api.create_assignment(
        create_assignment_payload(clin_b["id"], ctx.fac_id, start_date="2026-08-30"), RECRUITER)
    data, meta = validate_paginated(api.list_assignments(RECRUITER, params={"facility_id": ctx.fac_id}))
    assert len(data) == 1 and meta["total_count"] == 1
    assert get_assignment_data(api, ctx.asg_id)["staffing_status"] == "PENDING_START"
