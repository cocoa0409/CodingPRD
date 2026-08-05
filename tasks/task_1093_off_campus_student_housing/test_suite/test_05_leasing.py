"""Lease application, dual-variant pricing, term validation, guarantor gate,
lifecycle transitions, turnover buffer, and the bed-partition invariant.

Translates corner instances (lease lifecycle, term bounds, guarantor threshold,
occupancy walk, partial-term pricing) and three difficulty instances:
`lease_quoted_whole_month_vs_contracted_daily_proration`,
`bed_slot_halfopen_interval_with_mandatory_turnover_buffer`, and
`bed_reservation_and_cancellation_conserve_unit_bed_partition` (queue A).
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx
from test_helpers import make_student_headers
from test_helpers.assertions import assert_unit_partition

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


def test_lease_quoted_and_contracted_totals_diverge(api):
    """PRD §3.4: "The quoted reading bills the term as whole months: divide
    term_days by 30 and round up to the next whole month, then multiply by the
    list monthly_rent_cents. No university partner discount is ever applied to
    the quoted figure." PRD §3.4: "total_contract_cents is the gross minus the
    discount."

    Design: Difficulty/dual_variant_calc/lease_quoted_whole_month_vs_contracted_daily_proration
    """
    sc = fx.setup_active_lease(api, rent=90000, installment_count=10, bed_label="A")
    lease = sc["lease"]
    assert lease["term_days"] == 351
    assert lease["quoted_total_cents"] == 1080000
    assert lease["total_contract_cents"] == 986679
    assert lease["quoted_total_cents"] - lease["total_contract_cents"] == 93321
    assert lease["lease_status"] == "ACTIVE"


def test_lease_contracted_stamps_term_type_daily_rate_and_discount(api):
    """PRD §3.4: "it is ACADEMIC_YEAR when the lease's term_start_date is at or
    before the student's university academic_year_start_date and its
    term_end_date is at or after that university's academic_year_end_date". PRD
    §3.4: "It converts monthly rent to a daily rate by multiplying
    monthly_rent_cents by 12, dividing by 365, and rounding half up ... The
    partner_discount_bps is the university's partner_discount_bps when term_type
    is ACADEMIC_YEAR".

    Design: Difficulty/dual_variant_calc/lease_quoted_whole_month_vs_contracted_daily_proration
    """
    sc = fx.setup_active_lease(api, rent=90000, installment_count=10, bed_label="A")
    lease = sc["lease"]
    assert lease["term_type"] == "ACADEMIC_YEAR"
    assert lease["daily_rate_cents"] == 2959
    assert lease["partner_discount_bps"] == 500
    assert lease["partner_discount_cents"] == 51930


def test_partial_term_lease_receives_no_partner_discount(api):
    """PRD §3.4: "The partner_discount_bps is the university's
    partner_discount_bps when term_type is ACADEMIC_YEAR, and 0 otherwise". PRD
    §3.6: "floor the per-installment base share first ... and push the entire
    residual onto the last installment".

    Design: Corner/calculations/partial_term_lease_receives_no_partner_discount
    """
    base = fx.base_property(api)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.draft_lease(api, student["id"], base["unit"]["id"], "B",
                           term_start_date="2026-09-01", term_end_date="2027-03-01",
                           installment_count=6)
    assert lease["term_days"] == 181
    assert lease["quoted_total_cents"] == 630000
    fx.submit_lease(api, lease["id"], student["id"])
    signed = fx.sign_lease(api, lease["id"], student["id"])
    assert signed["term_type"] == "PARTIAL_TERM"
    assert signed["partner_discount_bps"] == 0 and signed["partner_discount_cents"] == 0
    assert signed["daily_rate_cents"] == 2959 and signed["total_contract_cents"] == 535579
    rows = fx.rent_installments(api, lease["id"], student["id"])
    assert len(rows) == 6
    amounts = [r["amount_cents"] for r in rows]
    assert amounts == [89263, 89263, 89263, 89263, 89263, 89264]
    assert sum(amounts) == 535579
    due = [r["due_date"] for r in rows]
    assert due == ["2026-09-01", "2026-10-01", "2026-10-31", "2026-11-30", "2026-12-30", "2027-01-29"]


def test_guarantor_rent_threshold_uses_strict_greater_than(api):
    """PRD §3.4: "it is true when the leaseholder's credit_score_band is THIN or
    LOW, or when the snapshotted monthly_rent_cents is strictly greater than
    120000 cents - a bed renting for exactly 120000 does not on its own demand a
    guarantor."

    Design: Corner/calculations/guarantor_rent_threshold_uses_strict_greater_than
    """
    uni = fx.create_university(api)
    prop = fx.create_property(api, uni["id"], name="Threshold Row")
    unit_at = fx.create_unit(api, prop["id"], unit_number="T1", floorplan_code="1x1",
                             bedroom_count=1, bathroom_count=1, bed_labels=["A"],
                             base_rent_cents_per_bed_monthly=120000)
    unit_over = fx.create_unit(api, prop["id"], unit_number="T2", floorplan_code="1x1",
                               bedroom_count=1, bathroom_count=1, bed_labels=["A"],
                               base_rent_cents_per_bed_monthly=120001)
    fx.list_property(api, prop["id"])
    student = fx.verified_student(api, uni["id"], "ava@su.edu", full_name="Ava Lead")
    l_at = fx.draft_lease(api, student["id"], unit_at["id"], "A")
    l_over = fx.draft_lease(api, student["id"], unit_over["id"], "A")
    assert l_at["monthly_rent_cents"] == 120000 and l_at["guarantor_required"] is False
    assert l_over["monthly_rent_cents"] == 120001 and l_over["guarantor_required"] is True
    at_sub = fx.submit_lease(api, l_at["id"], student["id"])
    over_sub = fx.submit_lease(api, l_over["id"], student["id"])
    assert at_sub["lease_status"] == "PENDING_SIGNATURE"
    assert over_sub["lease_status"] == "PENDING_GUARANTOR"


def test_unit_occupancy_status_walks_available_partial_and_full(api):
    """PRD §2.8: "The unit's occupancy_status is FULLY_LEASED when
    available_bed_count is 0, AVAILABLE when leased_bed_count is 0, and
    PARTIALLY_LEASED otherwise."

    Design: Corner/calculations/unit_occupancy_status_walks_available_partial_and_full
    """
    base = fx.base_property(api, bed_labels=("A", "B"), unit_over={"unit_number": "D1",
                            "floorplan_code": "2x1", "bathroom_count": 1})
    s1 = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.verified_student(api, base["uni"]["id"], "ben@su.edu", full_name="Ben Two",
                             cleanliness_level=3, noise_tolerance=4)
    l1 = fx.draft_lease(api, s1["id"], base["unit"]["id"], "A")
    l2 = fx.draft_lease(api, s2["id"], base["unit"]["id"], "B")
    before = fx.get_unit(api, base["unit"]["id"])
    assert before["occupancy_status"] == "AVAILABLE" and before["leased_bed_count"] == 0 and before["available_bed_count"] == 2
    fx.submit_lease(api, l1["id"], s1["id"])
    mid = fx.get_unit(api, base["unit"]["id"])
    assert mid["occupancy_status"] == "PARTIALLY_LEASED" and mid["leased_bed_count"] == 1 and mid["available_bed_count"] == 1
    fx.submit_lease(api, l2["id"], s2["id"])
    full = fx.get_unit(api, base["unit"]["id"])
    assert full["occupancy_status"] == "FULLY_LEASED" and full["leased_bed_count"] == 2 and full["available_bed_count"] == 0
    prop = fx.get_property(api, base["prop"]["id"])
    assert prop["available_bed_count"] == 0 and prop["status"] == "FULLY_COMMITTED"


def test_lease_invalid_lifecycle_transitions_rejected(api):
    """PRD §3.4: "Signing a lease that is not PENDING_SIGNATURE is
    ERR_LEASE_INVALID_STATE." PRD §3.10: "terminating a lease that is not
    ACTIVE is ERR_LEASE_INVALID_STATE". PRD §3.4: "Cancelling a signed or
    terminal lease is ERR_LEASE_INVALID_STATE."

    Design: Corner/state_machines/lease_invalid_lifecycle_transitions_rejected
    """
    base = fx.base_property(api)
    s1 = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    s2 = fx.verified_student(api, base["uni"]["id"], "ben@su.edu", full_name="Ben Two",
                             cleanliness_level=3, noise_tolerance=4)
    l1 = fx.draft_lease(api, s1["id"], base["unit"]["id"], "A")
    l2 = fx.active_lease(api, s2["id"], base["unit"]["id"], "B")
    validate_error(api.sign_lease(l1["id"], make_student_headers(s1["id"])),
                   ApiErrorId.ERR_LEASE_INVALID_STATE.value)
    validate_error(api.terminate_lease(l1["id"], MGR, {"reason": "too early"}),
                   ApiErrorId.ERR_LEASE_INVALID_STATE.value)
    validate_error(api.cancel_lease(l2["id"], make_student_headers(s2["id"]), {"reason": "too late"}),
                   ApiErrorId.ERR_LEASE_INVALID_STATE.value)
    l1r = fx.get_lease(api, l1["id"])
    assert l1r["lease_status"] == "DRAFT" and l1r["total_contract_cents"] is None
    l2r = fx.get_lease(api, l2["id"])
    assert l2r["lease_status"] == "ACTIVE" and l2r["total_contract_cents"] == 986679
    unit = fx.get_unit(api, base["unit"]["id"])
    assert unit["leased_bed_count"] == 1 and unit["available_bed_count"] == 3
    _, meta = fx.all_installments(api, l1["id"], s1["id"])
    assert meta["total_count"] == 0


def test_lease_term_length_and_start_bounds_enforced(api):
    """PRD §3.4: "must lie between 90 and 400 inclusive, or the request is
    ERR_TERM_LENGTH_INVALID; the start may not be earlier than the current clock
    date, or it is ERR_TERM_START_IN_PAST."

    Design: Corner/validations/lease_term_length_and_start_bounds_enforced
    """
    base = fx.base_property(api)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    sid = make_student_headers(student["id"])
    short = api.create_lease({"student_id": student["id"], "unit_id": base["unit"]["id"],
                              "bed_label": "A", "term_start_date": "2026-08-15",
                              "term_end_date": "2026-11-12", "installment_count": 3}, sid)
    validate_error(short, ApiErrorId.ERR_TERM_LENGTH_INVALID.value)
    long = api.create_lease({"student_id": student["id"], "unit_id": base["unit"]["id"],
                             "bed_label": "A", "term_start_date": "2026-08-15",
                             "term_end_date": "2027-09-20", "installment_count": 12}, sid)
    validate_error(long, ApiErrorId.ERR_TERM_LENGTH_INVALID.value)
    past = api.create_lease({"student_id": student["id"], "unit_id": base["unit"]["id"],
                             "bed_label": "A", "term_start_date": "2026-05-15",
                             "term_end_date": "2027-03-01", "installment_count": 9}, sid)
    validate_error(past, ApiErrorId.ERR_TERM_START_IN_PAST.value)
    _, meta = validate_paginated(api.list_leases(ADMIN, params={"unit_id": base["unit"]["id"]}))
    assert meta["total_count"] == 0


def test_renewal_turnover_buffer_boundary_strict(api):
    """PRD §3.10: "a candidate that would begin before that buffer clears is
    rejected with ERR_BED_TURNOVER_CONFLICT; a candidate starting exactly on the
    existing end date plus 14 days is accepted." PRD §3.10: "A new Lease is
    minted in DRAFT carrying the same student_id, unit_id, and bed_label, with
    replaces_lease_id pointing at the predecessor".

    Design: Difficulty/resource_temporal_overlap/bed_slot_halfopen_interval_with_mandatory_turnover_buffer
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    l1, sid = sc["lease"], sc["student_id"]
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    early = api.renew_lease(l1["id"], {"term_start_date": "2027-08-14",
                            "term_end_date": "2028-05-14", "installment_count": 9},
                            make_student_headers(sid))
    validate_error(early, ApiErrorId.ERR_BED_TURNOVER_CONFLICT.value)
    ok = validate_success(api.renew_lease(l1["id"], {"term_start_date": "2027-08-15",
                          "term_end_date": "2028-05-15", "installment_count": 9},
                          make_student_headers(sid)), 201)
    assert ok["replaces_lease_id"] == l1["id"]
    assert ok["unit_id"] == sc["unit"]["id"] and ok["bed_label"] == "A"
    assert ok["lease_status"] == "DRAFT" and ok["term_days"] == 274


def test_renewal_quoted_total_and_predecessor_untouched(api):
    """PRD §3.10: "its quoted_total_cents and guarantor_required are stamped
    exactly as for a fresh application. The self-referential replaces_lease_id
    chain records the turnover history." PRD §3.10: "with replaces_lease_id
    pointing at the predecessor, whose row is left untouched."

    Design: Difficulty/resource_temporal_overlap/bed_slot_halfopen_interval_with_mandatory_turnover_buffer
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    l1, sid = sc["lease"], sc["student_id"]
    fx.set_clock(api, "2026-08-16T00:00:00Z")
    ok = validate_success(api.renew_lease(l1["id"], {"term_start_date": "2027-08-15",
                          "term_end_date": "2028-05-15", "installment_count": 9},
                          make_student_headers(sid)), 201)
    assert ok["quoted_total_cents"] == 900000
    pred = fx.get_lease(api, l1["id"])
    assert pred["lease_status"] == "ACTIVE"
    unit = fx.get_unit(api, sc["unit"]["id"])
    assert unit["leased_bed_count"] == 1  # a DRAFT successor holds no bed
    _, meta = validate_paginated(api.list_leases(ADMIN, params={"replaces_lease_id": l1["id"]}))
    assert meta["total_count"] == 1


def test_bed_reservation_conserves_partition(api):
    """PRD §2.8: "The partition holds as a conserved invariant: the number of
    bed labels always equals leased_bed_count plus available_bed_count." PRD
    §3.4: "It reserves the slot - recomputing the unit rollups".

    Design: Difficulty/compensating_invariant/bed_reservation_and_cancellation_conserve_unit_bed_partition
    """
    base = fx.base_property(api)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.draft_lease(api, student["id"], base["unit"]["id"], "A")
    before = fx.get_unit(api, base["unit"]["id"])
    assert before["leased_bed_count"] == 0 and before["available_bed_count"] == 4
    assert before["occupancy_status"] == "AVAILABLE"
    assert fx.get_property(api, base["prop"]["id"])["available_bed_count"] == 4
    assert_unit_partition(before)
    submitted = fx.submit_lease(api, lease["id"], student["id"])
    assert submitted["lease_status"] == "PENDING_SIGNATURE"
    after_sub = fx.get_unit(api, base["unit"]["id"])
    assert after_sub["leased_bed_count"] == 1 and after_sub["available_bed_count"] == 3
    assert after_sub["occupancy_status"] == "PARTIALLY_LEASED"
    prop_sub = fx.get_property(api, base["prop"]["id"])
    assert prop_sub["available_bed_count"] == 3 and prop_sub["status"] == "LISTED"
    assert_unit_partition(after_sub)


def test_bed_cancellation_restores_partition(api):
    """PRD §3.4: "If the cancelled lease held a bed, the slot is released and the
    unit and property rollups and posture are re-evaluated". PRD §3.4: "moving
    it to CANCELLED and stamping terminated_at."

    Design: Difficulty/compensating_invariant/bed_reservation_and_cancellation_conserve_unit_bed_partition
    """
    base = fx.base_property(api)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.draft_lease(api, student["id"], base["unit"]["id"], "A")
    fx.submit_lease(api, lease["id"], student["id"])
    cancelled = validate_success(api.cancel_lease(lease["id"], make_student_headers(student["id"]),
                                 {"reason": "Changed plans"}), 200)
    assert cancelled["lease_status"] == "CANCELLED" and cancelled["terminated_at"] is not None
    unit = fx.get_unit(api, base["unit"]["id"])
    assert unit["leased_bed_count"] == 0 and unit["available_bed_count"] == 4
    assert unit["occupancy_status"] == "AVAILABLE"
    assert_unit_partition(unit)
    prop = fx.get_property(api, base["prop"]["id"])
    assert prop["available_bed_count"] == 4 and prop["total_bed_count"] == 4
    _, meta = validate_paginated(api.list_leases(ADMIN, params={"unit_id": base["unit"]["id"],
                                 "lease_status": "CANCELLED"}))
    assert meta["total_count"] == 1
