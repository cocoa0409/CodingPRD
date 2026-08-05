"""Subletting and amenities: posture gate, fee floor, clock activation, window
validation, overlap, aggregate capacity, referential precedence, and release.

Translates corner instances (sublet activation/completion, min-fee floor,
window/overlap rules, subtenant-is-leaseholder, amenity release) and three
difficulty instances: `sublet_request_gated_by_property_listing_posture`,
`amenity_closed_interval_aggregate_capacity_ceiling`, and
`amenity_referential_mismatch_outranks_window_temporal_violation` (queue A).
"""
from test_helpers import validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS
from test_helpers import fixtures as fx
from test_helpers import make_student_headers

ADMIN = TEST_USERS["admin_headers"]
MGR = TEST_USERS["manager_headers"]


# --------------------------------------------------------------------------
# Subletting
# --------------------------------------------------------------------------
def test_sublet_request_rejected_while_property_suspended(api):
    """PRD §3.7: "The host lease must be ACTIVE (else ERR_LEASE_NOT_ACTIVE) and
    its property LISTED or FULLY_COMMITTED (else ERR_PROPERTY_NOT_ACTIVE)."

    Design: Difficulty/cross_entity_state_dependency/sublet_request_gated_by_property_listing_posture
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    s6 = fx.verified_student(api, sc["uni"]["id"], "fay@su.edu", full_name="Fay Six",
                             cleanliness_level=3, noise_tolerance=3)
    api.suspend_property(sc["prop"]["id"], ADMIN, {"reason": "Fire-safety inspection"})
    resp = api.create_sublet({"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
                              "start_date": "2027-05-20", "end_date": "2027-07-31",
                              "sublet_rent_cents": 85000}, make_student_headers(sc["student_id"]))
    validate_error(resp, ApiErrorId.ERR_PROPERTY_NOT_ACTIVE.value)
    _, meta = validate_paginated(api.list_sublets(ADMIN, params={"lease_id": sc["lease"]["id"]}))
    assert meta["total_count"] == 0


def test_sublet_request_succeeds_after_reinstate_with_computed_fields(api):
    """PRD §3.7: "the sublet stamps window_days and sublet_total_cents (the
    sublet_rent_cents times the whole-month count, where the month count divides
    window_days by 30 and rounds up) and is born REQUESTED." PRD §3.2:
    "Reinstating a SUSPENDED property returns it to LISTED when it has available
    beds".

    Design: Difficulty/cross_entity_state_dependency/sublet_request_gated_by_property_listing_posture
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    s6 = fx.verified_student(api, sc["uni"]["id"], "fay@su.edu", full_name="Fay Six",
                             cleanliness_level=3, noise_tolerance=3)
    api.suspend_property(sc["prop"]["id"], ADMIN, {"reason": "Fire-safety inspection"})
    reins = validate_success(api.reinstate_property(sc["prop"]["id"], ADMIN), 200)
    assert reins["status"] == "LISTED" and reins["available_bed_count"] == 3
    sub = validate_success(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-05-20", "end_date": "2027-07-31", "sublet_rent_cents": 85000},
        make_student_headers(sc["student_id"])), 201)
    assert sub["status"] == "REQUESTED"
    assert sub["window_days"] == 72 and sub["sublet_total_cents"] == 255000
    assert sub["platform_fee_cents"] is None


def test_sublet_activates_and_completes_on_clock_then_locks_out_new_decisions(api):
    """PRD §3.7: "APPROVE stamps platform_fee_cents as the larger of 2500 cents
    and the sublet_total_cents times 800 basis points ... and mints a SUBLET_FEE
    Installment on the host lease whose amount_cents equals platform_fee_cents,
    whose due_date is the sublet's start_date, and whose sequence_number is one
    past the current maximum". PRD §3.7: "an APPROVED sublet whose start_date has
    arrived becomes ACTIVE, and an ACTIVE sublet whose end_date has arrived
    becomes COMPLETED." PRD §3.7: "A decision on a sublet that is not REQUESTED
    is ERR_SUBLET_INVALID_STATE."

    Design: Corner/state_machines/sublet_activates_and_completes_on_clock_then_locks_out_new_decisions
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    s6 = fx.verified_student(api, sc["uni"]["id"], "fay@su.edu", full_name="Fay Six",
                             cleanliness_level=3, noise_tolerance=3)
    sub = validate_success(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-05-20", "end_date": "2027-07-31", "sublet_rent_cents": 85000},
        make_student_headers(sc["student_id"])), 201)
    appr = validate_success(api.decide_sublet(sub["id"], {"decision": "APPROVE"}, MGR), 200)
    assert appr["platform_fee_cents"] == 20400 and appr["sublet_total_cents"] == 255000 and appr["window_days"] == 72
    fee_rows, _ = fx.all_installments(api, sc["lease"]["id"], sc["student_id"], {"kind": "SUBLET_FEE"})
    assert len(fee_rows) == 1
    fee = fee_rows[0]
    assert fee["amount_cents"] == 20400 and fee["due_date"] == "2027-05-20" and fee["sequence_number"] == 11
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["amenity_fee_total_cents"] == 20400 and lease["billed_total_cents"] == 1007079
    clk1 = validate_success(api.set_clock("2027-05-20T00:00:00Z", ADMIN), 200)
    assert clk1["sublets_activated_count"] == 1 and clk1["installments_marked_late_count"] == 10
    assert api.get_sublet(sub["id"], ADMIN).json()["data"]["status"] == "ACTIVE"
    clk2 = validate_success(api.set_clock("2027-07-31T00:00:00Z", ADMIN), 200)
    assert clk2["sublets_completed_count"] == 1 and clk2["installments_marked_late_count"] == 1
    assert api.get_sublet(sub["id"], ADMIN).json()["data"]["status"] == "COMPLETED"
    assert fx.get_lease(api, sc["lease"]["id"])["lease_status"] == "ACTIVE"
    validate_error(api.decide_sublet(sub["id"], {"decision": "DECLINE"}, MGR),
                   ApiErrorId.ERR_SUBLET_INVALID_STATE.value)


def test_sublet_platform_fee_uses_the_minimum_fee_floor(api):
    """PRD §3.7: "the larger of 2500 cents and the sublet_total_cents times 800
    basis points divided by 10000 and rounded half up - an 8.00% fee with a
    2500-cent floor".

    Design: Corner/calculations/sublet_platform_fee_uses_the_minimum_fee_floor
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    s6 = fx.verified_student(api, sc["uni"]["id"], "fay@su.edu", full_name="Fay Six",
                             cleanliness_level=3, noise_tolerance=3)
    sub = validate_success(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-05-20", "end_date": "2027-06-15", "sublet_rent_cents": 1000},
        make_student_headers(sc["student_id"])), 201)
    assert sub["window_days"] == 26 and sub["sublet_total_cents"] == 1000
    appr = validate_success(api.decide_sublet(sub["id"], {"decision": "APPROVE"}, MGR), 200)
    assert appr["platform_fee_cents"] == 2500
    fee_rows, _ = fx.all_installments(api, sc["lease"]["id"], sc["student_id"], {"kind": "SUBLET_FEE"})
    assert fee_rows[0]["amount_cents"] == 2500 and fee_rows[0]["due_date"] == "2027-05-20"
    lease = fx.get_lease(api, sc["lease"]["id"])
    assert lease["amenity_fee_total_cents"] == 2500 and lease["billed_total_cents"] == 989179


def test_sublet_window_bounds_and_minimum_and_overlap_rules(api):
    """PRD §3.7: "its window_days ... must be at least 21 days (else
    ERR_WINDOW_TOO_SHORT), and the window must lie inside the host lease term
    ... or it is ERR_WINDOW_OUTSIDE_LEASE_TERM. The requested window may not
    overlap another sublet ... two windows that merely touch at a shared
    endpoint are permitted, but any real overlap is ERR_SUBLET_OVERLAP."

    Design: Corner/validations/sublet_window_bounds_and_minimum_and_overlap_rules
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    s6 = fx.verified_student(api, sc["uni"]["id"], "fay@su.edu", full_name="Fay Six",
                             cleanliness_level=3, noise_tolerance=3)
    sid = make_student_headers(sc["student_id"])
    validate_success(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-05-20", "end_date": "2027-06-20", "sublet_rent_cents": 85000}, sid), 201)
    validate_error(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-07-15", "end_date": "2027-08-15", "sublet_rent_cents": 85000}, sid),
        ApiErrorId.ERR_WINDOW_OUTSIDE_LEASE_TERM.value)
    validate_error(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-06-25", "end_date": "2027-07-15", "sublet_rent_cents": 85000}, sid),
        ApiErrorId.ERR_WINDOW_TOO_SHORT.value)
    validate_error(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-06-10", "end_date": "2027-07-10", "sublet_rent_cents": 85000}, sid),
        ApiErrorId.ERR_SUBLET_OVERLAP.value)
    validate_success(api.create_sublet(
        {"lease_id": sc["lease"]["id"], "subtenant_student_id": s6["id"],
         "start_date": "2027-06-20", "end_date": "2027-07-25", "sublet_rent_cents": 85000}, sid), 201)
    _, meta = validate_paginated(api.list_sublets(ADMIN, params={"lease_id": sc["lease"]["id"]}))
    assert meta["total_count"] == 2


def test_subtenant_cannot_be_the_leaseholder(api):
    """PRD §3.7: "The subtenant must differ from the host student_id (else
    ERR_SUBTENANT_IS_LEASEHOLDER)".

    Design: Corner/validations/subtenant_cannot_be_the_leaseholder
    """
    sc = fx.setup_active_lease(api, bed_label="A")
    resp = api.create_sublet({"lease_id": sc["lease"]["id"], "subtenant_student_id": sc["student_id"],
                              "start_date": "2027-05-20", "end_date": "2027-07-31",
                              "sublet_rent_cents": 85000}, make_student_headers(sc["student_id"]))
    validate_error(resp, ApiErrorId.ERR_SUBTENANT_IS_LEASEHOLDER.value)
    _, meta = validate_paginated(api.list_sublets(ADMIN, params={"lease_id": sc["lease"]["id"]}))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------
# Amenities
# --------------------------------------------------------------------------
def _three_active_leases(api, base, amenity_cap=2, amenity_fee=12000):
    """base property + amenity am1 + three verified students each holding an
    ACTIVE lease on beds A/B/C. Returns (am1, [lease_a, lease_b, lease_c],
    [sid_a, sid_b, sid_c])."""
    am1 = validate_success(api.create_amenity(
        {"property_id": base["prop"]["id"], "name": "Lot A Parking", "amenity_type": "PARKING",
         "capacity": amenity_cap, "monthly_fee_cents": amenity_fee}, MGR), 201)
    leases, sids = [], []
    for email, name, bed, attrs in [
        ("ava@su.edu", "Ava Lead", "A", {}),
        ("ben@su.edu", "Ben Two", "B", dict(cleanliness_level=3, noise_tolerance=4)),
        ("cara@su.edu", "Cara Three", "C", dict(cleanliness_level=5, noise_tolerance=2, sleep_schedule="LATE")),
    ]:
        s = fx.verified_student(api, base["uni"]["id"], email, full_name=name, **attrs)
        lease = fx.active_lease(api, s["id"], base["unit"]["id"], bed)
        leases.append(lease)
        sids.append(s["id"])
    return am1, leases, sids


def test_amenity_aggregate_capacity_ceiling_rejects_touching_window(api):
    """PRD §3.8: "the assignment is admitted only if, for every calendar day in
    its closed window, the count of currently ACTIVE assignments whose closed
    windows contain that day plus this one does not exceed the amenity's
    capacity; because the windows are closed, two that merely touch at a single
    day do collide. Exceeding capacity on any day is ERR_AMENITY_CAPACITY_EXCEEDED."

    Design: Difficulty/resource_temporal_overlap/amenity_closed_interval_aggregate_capacity_ceiling
    """
    base = fx.base_property(api)
    am1, leases, sids = _three_active_leases(api, base, amenity_cap=2, amenity_fee=12000)
    aa1 = validate_success(api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": leases[0]["id"],
         "start_date": "2026-09-01", "end_date": "2026-12-31"}, make_student_headers(sids[0])), 201)
    assert aa1["window_days"] == 122 and aa1["billed_months"] == 5 and aa1["total_fee_cents"] == 60000
    aa2 = validate_success(api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": leases[1]["id"],
         "start_date": "2026-10-01", "end_date": "2027-01-31"}, make_student_headers(sids[1])), 201)
    assert aa2["window_days"] == 123 and aa2["billed_months"] == 5 and aa2["total_fee_cents"] == 60000
    over = api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": leases[2]["id"],
         "start_date": "2026-12-31", "end_date": "2027-02-28"}, make_student_headers(sids[2]))
    validate_error(over, ApiErrorId.ERR_AMENITY_CAPACITY_EXCEEDED.value)


def test_amenity_aggregate_capacity_admits_disjoint_window(api):
    """PRD §3.8: "On success the assignment stamps window_days, billed_months
    (the window_days divided by 30 and rounded up), and total_fee_cents (the
    amenity's monthly_fee_cents times billed_months) ... Creating the assignment
    increments the amenity's active_assignment_count by 1".

    Design: Difficulty/resource_temporal_overlap/amenity_closed_interval_aggregate_capacity_ceiling
    """
    base = fx.base_property(api)
    am1, leases, sids = _three_active_leases(api, base, amenity_cap=2, amenity_fee=12000)
    api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": leases[0]["id"],
         "start_date": "2026-09-01", "end_date": "2026-12-31"}, make_student_headers(sids[0]))
    api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": leases[1]["id"],
         "start_date": "2026-10-01", "end_date": "2027-01-31"}, make_student_headers(sids[1]))
    aa3 = validate_success(api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": leases[2]["id"],
         "start_date": "2027-01-01", "end_date": "2027-02-28"}, make_student_headers(sids[2])), 201)
    assert aa3["window_days"] == 59 and aa3["billed_months"] == 2 and aa3["total_fee_cents"] == 24000
    assert api.get_amenity(am1["id"], ADMIN).json()["data"]["active_assignment_count"] == 3
    lease_c = fx.get_lease(api, leases[2]["id"])
    assert lease_c["amenity_fee_total_cents"] == 24000 and lease_c["billed_total_cents"] == 1010679


def test_amenity_property_mismatch_outranks_window_violation(api):
    """PRD §2.9: the fixed ascending priority order means a lower-priority rule
    fires first. PRD §3.8: "The amenity's property_id must equal the billed
    lease's property_id (else ERR_AMENITY_PROPERTY_MISMATCH)".

    Design: Difficulty/priority_pair_validation_conflict/amenity_referential_mismatch_outranks_window_temporal_violation
    """
    base = fx.base_property(api)
    am1 = validate_success(api.create_amenity(
        {"property_id": base["prop"]["id"], "name": "Lot A Parking", "amenity_type": "PARKING",
         "capacity": 2, "monthly_fee_cents": 12000}, MGR), 201)
    prop2 = fx.create_property(api, base["uni"]["id"], name="Birch House")
    fx.create_unit(api, prop2["id"], unit_number="1", floorplan_code="2x1", bedroom_count=2,
                   bathroom_count=1, bed_labels=["A", "B"], base_rent_cents_per_bed_monthly=70000)
    fx.list_property(api, prop2["id"])
    am2 = validate_success(api.create_amenity(
        {"property_id": prop2["id"], "name": "Birch Storage", "amenity_type": "STORAGE",
         "capacity": 1, "monthly_fee_cents": 5000}, MGR), 201)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.active_lease(api, student["id"], base["unit"]["id"], "A")
    # window 2027-09-01..2027-10-15 is outside the lease term AND am2 is the wrong property
    dual = api.create_amenity_assignment(
        {"amenity_id": am2["id"], "lease_id": lease["id"],
         "start_date": "2027-09-01", "end_date": "2027-10-15"}, make_student_headers(student["id"]))
    validate_error(dual, ApiErrorId.ERR_AMENITY_PROPERTY_MISMATCH.value)


def test_amenity_window_outside_lease_term_is_the_control(api):
    """PRD §3.8: "it must be at least 30 days (else ERR_WINDOW_TOO_SHORT) and
    must lie inside the lease term (else ERR_WINDOW_OUTSIDE_LEASE_TERM)."

    Design: Difficulty/priority_pair_validation_conflict/amenity_referential_mismatch_outranks_window_temporal_violation
    """
    base = fx.base_property(api)
    am1 = validate_success(api.create_amenity(
        {"property_id": base["prop"]["id"], "name": "Lot A Parking", "amenity_type": "PARKING",
         "capacity": 2, "monthly_fee_cents": 12000}, MGR), 201)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.active_lease(api, student["id"], base["unit"]["id"], "A")
    control = api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": lease["id"],
         "start_date": "2027-09-01", "end_date": "2027-10-15"}, make_student_headers(student["id"]))
    validate_error(control, ApiErrorId.ERR_WINDOW_OUTSIDE_LEASE_TERM.value)
    _, meta = validate_paginated(api.list_amenity_assignments(ADMIN, params={"lease_id": lease["id"]}))
    assert meta["total_count"] == 0
    assert api.get_amenity(am1["id"], ADMIN).json()["data"]["active_assignment_count"] == 0
    lease_after = fx.get_lease(api, lease["id"])
    assert lease_after["amenity_fee_total_cents"] == 0 and lease_after["billed_total_cents"] == 986679


def test_amenity_release_voids_charge_frees_capacity_and_blocks_second_release(api):
    """PRD §3.8: "The leaseholder may release an ACTIVE assignment, moving it
    ACTIVE -> RELEASED, stamping released_at, voiding the linked AMENITY charge
    when it is still SCHEDULED or LATE, decrementing the amenity's
    active_assignment_count by 1 ... Releasing an already-RELEASED assignment is
    ERR_ASSIGNMENT_INVALID_STATE."

    Design: Corner/state_machines/amenity_release_voids_charge_frees_capacity_and_blocks_second_release
    """
    base = fx.base_property(api)
    am1 = validate_success(api.create_amenity(
        {"property_id": base["prop"]["id"], "name": "Reserved Stall", "amenity_type": "PARKING",
         "capacity": 1, "monthly_fee_cents": 12000}, MGR), 201)
    student = fx.verified_student(api, base["uni"]["id"], "ava@su.edu", full_name="Ava Lead")
    lease = fx.active_lease(api, student["id"], base["unit"]["id"], "A")
    sid = make_student_headers(student["id"])
    aa1 = validate_success(api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": lease["id"],
         "start_date": "2026-09-01", "end_date": "2026-12-31"}, sid), 201)
    assert aa1["total_fee_cents"] == 60000 and aa1["billed_months"] == 5
    assert api.get_amenity(am1["id"], ADMIN).json()["data"]["active_assignment_count"] == 1
    assert fx.get_lease(api, lease["id"])["billed_total_cents"] == 1046679
    rel = validate_success(api.release_amenity_assignment(aa1["id"], sid), 200)
    assert rel["status"] == "RELEASED" and rel["released_at"] is not None
    charge_rows, _ = fx.all_installments(api, lease["id"], student["id"], {"kind": "AMENITY"})
    assert charge_rows[0]["status"] == "VOID"
    assert api.get_amenity(am1["id"], ADMIN).json()["data"]["active_assignment_count"] == 0
    lease_after = fx.get_lease(api, lease["id"])
    assert lease_after["amenity_fee_total_cents"] == 0 and lease_after["billed_total_cents"] == 986679
    validate_error(api.release_amenity_assignment(aa1["id"], sid),
                   ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE.value)
    aa2 = validate_success(api.create_amenity_assignment(
        {"amenity_id": am1["id"], "lease_id": lease["id"],
         "start_date": "2026-09-01", "end_date": "2026-12-31"}, sid), 201)
    assert aa2["status"] == "ACTIVE" and aa2["total_fee_cents"] == 60000
    assert api.get_amenity(am1["id"], ADMIN).json()["data"]["active_assignment_count"] == 1
