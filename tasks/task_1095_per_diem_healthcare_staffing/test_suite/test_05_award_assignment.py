"""Awarding, the assignment lifecycle, the two independent state axes, backfill,
the empty-pool fallback, ranking, and the shift-version OCC guard.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_scheduler_headers,
    make_clinician_headers,
    fixtures as fx,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


# --------------------------------------------------------------------------- #
# Corner
# --------------------------------------------------------------------------- #
def test_no_show_from_pending_confirmation_returns_not_confirmed(api):
    """PRD 3.5: "A no-show is only valid on an assignment whose `work_status` is
    `CONFIRMED` and only once the current instant is at or after the shift's
    `scheduled_start`; a no-show against an assignment not in `CONFIRMED` raises
    `ERR_ASSIGNMENT_NOT_CONFIRMED`."

    Design: Corner/state_machines/no_show_from_pending_confirmation_returns_assignment_not_confirmed
    """
    bundle = fx.setup_awarded_assignment(facility_overrides={"name": "Zephyr Health"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    fx.set_clock("2026-06-08T08:00:00Z")
    resp = api.no_show_assignment(asg["id"], {"note": "never confirmed and never arrived"},
                                  fx.make_verifier_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_CONFIRMED.value, 409)
    got = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert got["work_status"] == "PENDING_CONFIRMATION" and got["pay_status"] == "UNBILLED"
    shift = validate_success(api.get_shift(bundle["shift"]["id"], make_scheduler_headers(fac_id)), 200)
    assert shift["status"] == "ASSIGNED"
    events, meta = validate_paginated(api.list_clinician_reliability_events(cl_id, OFFICER))
    assert meta["total_count"] == 0


def test_award_declines_every_sibling_pending_claim(api):
    """PRD 3.5: "The award sets the winning claim `PENDING → AWARDED` and every other
    `PENDING` claim on the shift `PENDING → DECLINED`, recomputes `Shift.claim_count`,
    moves the shift `OPEN → ASSIGNED`, bumps the shift's `version`, and triggers the
    parent order's fill-posture recompute."

    Design: Corner/state_machines/award_declines_every_sibling_pending_claim
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Bramble")
    fx.add_rate_card(fac["id"])
    cl_a = fx.new_clinician(full_name="Ada Wu", email="ada.wu@example.com")
    fx.add_verified_credential(cl_a["id"])
    cl_b = fx.new_clinician(full_name="Bo Iversen", email="bo.iversen@example.com")
    fx.add_verified_credential(cl_b["id"])
    order = fx.new_order(fac["id"])
    shift = fx.add_shift(order["id"], fac["id"])
    clm_a = fx.place_claim(shift["id"], cl_a["id"])
    clm_b = fx.place_claim(shift["id"], cl_b["id"])
    before = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac["id"])), 200)
    assert before["claim_count"] == 2

    asg = fx.award(shift["id"], fac["id"], claim_id=clm_a["id"], expected_version=before["version"])
    assert asg["clinician_id"] == cl_a["id"]
    assert validate_success(api.get_claim(clm_a["id"], ADMIN), 200)["status"] == "AWARDED"
    assert validate_success(api.get_claim(clm_b["id"], ADMIN), 200)["status"] == "DECLINED"
    shift_after = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac["id"])), 200)
    assert shift_after["claim_count"] == 0 and shift_after["status"] == "ASSIGNED"
    assert asg["claim_id"] == clm_a["id"] and asg["replaces_assignment_id"] is None
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac["id"])), 200)
    assert order_after["status"] == "FILLED" and order_after["filled_count"] == 1


def test_backfill_after_cancellation_sets_replaces_assignment_id(api):
    """PRD 3.5: "When the slot being awarded had previously carried an assignment that
    was released back to `OPEN`, the new assignment's `replaces_assignment_id` is set
    to that prior assignment; on a first fill it stays null."

    Design: Corner/state_machines/backfill_after_cancellation_sets_replaces_assignment_id
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Cobalt")
    fx.add_rate_card(fac["id"])
    cl_a = fx.new_clinician(full_name="Cal Reyes", email="cal.reyes@example.com")
    fx.add_verified_credential(cl_a["id"])
    cl_b = fx.new_clinician(full_name="Dee Alonzo", email="dee.alonzo@example.com")
    fx.add_verified_credential(cl_b["id"])
    order = fx.new_order(fac["id"])
    shift = fx.add_shift(order["id"], fac["id"])
    clm_a = fx.place_claim(shift["id"], cl_a["id"])
    asg_a = fx.award(shift["id"], fac["id"], claim_id=clm_a["id"])
    cancelled = validate_success(
        api.cancel_assignment(asg_a["id"], {"reason": "took a permanent post elsewhere"},
                              make_clinician_headers(cl_a["id"])), 200)
    assert cancelled["work_status"] == "CANCELLED_BY_CLINICIAN"
    clm_b = fx.place_claim(shift["id"], cl_b["id"])
    reopened = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac["id"])), 200)
    assert reopened["status"] == "OPEN"

    asg_b = fx.award(shift["id"], fac["id"], claim_id=clm_b["id"], expected_version=reopened["version"])
    assert asg_b["replaces_assignment_id"] == asg_a["id"]
    assert asg_b["clinician_id"] == cl_b["id"]
    assert asg_b["work_status"] == "PENDING_CONFIRMATION" and asg_b["pay_status"] == "UNBILLED"
    listed, meta = validate_paginated(
        api.list_assignments(make_scheduler_headers(fac["id"]), params={"replaces_assignment_id": asg_a["id"]}))
    assert meta["total_count"] == 1 and listed[0]["id"] == asg_b["id"]


def test_award_on_cancelled_shift_returns_shift_not_open(api):
    """PRD 3.5: "An award is only valid on a shift in `OPEN` status whose parent order
    is `OPEN` or `PARTIALLY_FILLED`; an award on any other shift state raises
    `ERR_SHIFT_NOT_OPEN`."

    Design: Corner/state_machines/award_on_cancelled_shift_returns_shift_not_open
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    base = fx.setup_facility_with_verified_clinician(facility_overrides={"name": "Fernwood"}, clock=None)
    fac_id, cl_id = base["facility"]["id"], base["clinician"]["id"]
    order = fx.new_order(fac_id)
    shift = fx.add_shift(order["id"], fac_id)
    clm = fx.place_claim(shift["id"], cl_id)
    version = fx.read_shift_version(shift["id"], fac_id)
    cancelled_order = validate_success(
        api.cancel_order(order["id"], {"reason": "unit closed"}, make_scheduler_headers(fac_id)), 200)
    assert cancelled_order["status"] == "CANCELLED"
    shift_after = validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac_id)), 200)
    assert shift_after["status"] == "CANCELLED"
    assert validate_success(api.get_claim(clm["id"], ADMIN), 200)["status"] == "DECLINED"

    resp = api.award_shift(shift["id"], {"expected_shift_version": shift_after["version"], "claim_id": clm["id"]},
                           make_scheduler_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_OPEN.value, 409)
    asgs, meta = validate_paginated(api.list_assignments(make_scheduler_headers(fac_id), params={"shift_id": shift["id"]}))
    assert meta["total_count"] == 0
    order_after = validate_success(api.get_order(order["id"], make_scheduler_headers(fac_id)), 200)
    assert order_after["cancelled_count"] == 1 and order_after["open_count"] == 0


def test_award_ranking_prefers_higher_reliability_over_earlier_claim(api):
    """PRD 3.5: "it filters to the shift's `PENDING` claims whose clinician is `ACTIVE`
    and passes the credential, overlap, rest, and weekly-hours gates, then ranks the
    survivors by live `reliability_score` descending, breaking ties by earliest
    `claimed_at` and then earliest `created_at`, and takes the top candidate. Note that
    the ranking reads the clinician's live `reliability_score`, not the
    `reliability_snapshot` frozen on the claim."

    Design: Corner/calculations/award_ranking_prefers_higher_reliability_over_earlier_claim
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Petrel")
    fx.add_rate_card(fac["id"])
    fac_id = fac["id"]
    cl_o = fx.new_clinician(full_name="Otto Vance", email="otto.vance@example.com")
    fx.add_verified_credential(cl_o["id"])
    cl_p = fx.new_clinician(full_name="Pilar Marchetti", email="pilar.marchetti@example.com")
    fx.add_verified_credential(cl_p["id"])

    # Drive Otto to a CONFIRMED no-show, then adjudicate it so reliability_score == 70.
    order1 = fx.new_order(fac_id)
    s1 = fx.add_shift(order1["id"], fac_id)
    c_o1 = fx.place_claim(s1["id"], cl_o["id"])
    a_o1 = fx.award(s1["id"], fac_id, claim_id=c_o1["id"])
    fx.confirm(a_o1["id"], cl_o["id"])
    fx.set_clock("2026-06-08T08:00:00Z")
    fx.no_show(a_o1["id"], fac_id)
    events = validate_success(api.list_assignment_reliability_events(a_o1["id"], OFFICER), 200)
    fx.api_client.adjudicate_event(events[0]["id"], {"decision": "CONFIRMED"}, OFFICER)
    otto = validate_success(api.get_clinician(cl_o["id"], make_scheduler_headers(fac_id)), 200)
    assert otto["reliability_score"] == 70

    # A fresh shift both claim; Otto claims first.
    order2 = fx.new_order(fac_id, window_start="2026-06-15T00:00:00Z", window_end="2026-06-22T00:00:00Z")
    s2 = fx.add_shift(order2["id"], fac_id, scheduled_start="2026-06-16T07:00:00Z", scheduled_end="2026-06-16T19:00:00Z")
    c_o2 = fx.place_claim(s2["id"], cl_o["id"])
    c_p2 = fx.place_claim(s2["id"], cl_p["id"])
    s2_state = validate_success(api.get_shift(s2["id"], make_scheduler_headers(fac_id)), 200)
    assert s2_state["claim_count"] == 2

    asg = fx.award(s2["id"], fac_id, claim_id=None, expected_version=s2_state["version"])
    assert asg["clinician_id"] == cl_p["id"]
    assert asg["claim_id"] == c_p2["id"]
    assert validate_success(api.get_claim(c_p2["id"], ADMIN), 200)["status"] == "AWARDED"
    declined = validate_success(api.get_claim(c_o2["id"], ADMIN), 200)
    assert declined["status"] == "DECLINED"
    assert declined["reliability_snapshot"] == 70


def test_award_with_stale_shift_version_returns_412(api):
    """PRD 2.5: "When `expected_shift_version` does not equal the shift's current
    `version`, the award is rejected with `ERR_STALE_SHIFT_VERSION` (HTTP 412), and the
    scheduler must re-read the shift and re-decide."

    Design: Corner/cross_cutting/award_with_stale_shift_version_returns_412
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Ivywood")
    fx.add_rate_card(fac["id"])
    fac_id = fac["id"]
    cl1 = fx.new_clinician(full_name="Ivo One", email="ivo.one@example.com")
    fx.add_verified_credential(cl1["id"])
    cl2 = fx.new_clinician(full_name="Ida Two", email="ida.two@example.com")
    fx.add_verified_credential(cl2["id"])
    order = fx.new_order(fac_id)
    shift = fx.add_shift(order["id"], fac_id)
    clm1 = fx.place_claim(shift["id"], cl1["id"])
    stale_version = fx.read_shift_version(shift["id"], fac_id)
    clm2 = fx.place_claim(shift["id"], cl2["id"])  # bumps Shift.version

    resp = api.award_shift(shift["id"], {"expected_shift_version": stale_version, "claim_id": clm1["id"]},
                           make_scheduler_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_STALE_SHIFT_VERSION.value, 412)

    fresh_version = fx.read_shift_version(shift["id"], fac_id)
    retry = api.award_shift(shift["id"], {"expected_shift_version": fresh_version, "claim_id": clm1["id"]},
                            make_scheduler_headers(fac_id))
    asg = validate_success(retry, 201)
    assert asg["clinician_id"] == cl1["id"]
    assert validate_success(api.get_claim(clm1["id"], ADMIN), 200)["status"] == "AWARDED"
    assert validate_success(api.get_claim(clm2["id"], ADMIN), 200)["status"] == "DECLINED"
    assert validate_success(api.get_shift(shift["id"], make_scheduler_headers(fac_id)), 200)["status"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# Difficulty: parallel work_status and pay_status axes
# --------------------------------------------------------------------------- #
def test_assignment_axes_snapshot_advance_independently(api):
    """PRD 3.5: "it moves `work_status` `PENDING_CONFIRMATION → CONFIRMED`, records
    `confirmed_at`, bumps the assignment's `version`, and leaves the pay axis
    untouched."
    PRD 3.6: "On submission the assignment moves `work_status` `CONFIRMED → WORKED`, the
    clinician's `completed_shift_count` increments by 1, and the assignment's
    `pay_status` moves `UNBILLED → TIMESHEET_PENDING`."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_work_and_pay_axes_advance_independently
    """
    bundle = fx.setup_awarded_assignment(facility_overrides={"name": "Cedar Ridge"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    assert asg["work_status"] == "PENDING_CONFIRMATION" and asg["pay_status"] == "UNBILLED"

    confirmed = fx.confirm(asg["id"], cl_id)
    assert confirmed["work_status"] == "CONFIRMED" and confirmed["pay_status"] == "UNBILLED"

    fx.set_clock("2026-06-08T19:30:00Z")
    fx.submit_timesheet(asg["id"], cl_id)
    after_submit = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert after_submit["work_status"] == "WORKED" and after_submit["pay_status"] == "TIMESHEET_PENDING"


def test_assignment_pay_axis_advances_to_payable_on_verify(api):
    """PRD 3.6: "Because the timesheet became verified, the assignment's pay axis moves
    `TIMESHEET_PENDING → PAYABLE`, the assignment's `final_pay_cents` is set to the
    timesheet's `gross_pay_cents`".
    PRD 3.6: "On submission the assignment moves `work_status` `CONFIRMED → WORKED`, the
    clinician's `completed_shift_count` increments by 1, and the assignment's
    `pay_status` moves `UNBILLED → TIMESHEET_PENDING`."

    Design: Difficulty/non_linear_state_machine/assignment_parallel_work_and_pay_axes_advance_independently
    """
    bundle = fx.setup_verified_timesheet(facility_overrides={"name": "Cedar Ridge"})
    fac_id, cl_id, asg = bundle["facility"]["id"], bundle["clinician"]["id"], bundle["assignment"]
    final = validate_success(api.get_assignment(asg["id"], make_scheduler_headers(fac_id)), 200)
    assert final["work_status"] == "WORKED"
    assert final["pay_status"] == "PAYABLE"
    assert final["final_pay_cents"] == 86250
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["completed_shift_count"] == 1


# --------------------------------------------------------------------------- #
# Difficulty: empty eligible pool -> ERR_NO_ELIGIBLE_CLAIM
# --------------------------------------------------------------------------- #
def _setup_revoked_claimant():
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Willow Bend")
    fx.add_rate_card(fac["id"])
    cl = fx.new_clinician(full_name="Lena Kwan", email="lena.kwan@example.com")
    cred = fx.add_verified_credential(cl["id"])
    order = fx.new_order(fac["id"])
    shift = fx.add_shift(order["id"], fac["id"])
    clm = fx.place_claim(shift["id"], cl["id"])
    revoke = fx.api_client.revoke_credential(cred["id"], {"reason": "licence surrendered"}, OFFICER)
    assert revoke.status_code < 300, revoke.text
    return fac["id"], cl["id"], order["id"], shift["id"], clm["id"]


def test_award_empty_pool_returns_no_eligible_claim(api):
    """PRD 3.5: "If the filtered pool is empty, the award fails with
    `ERR_NO_ELIGIBLE_CLAIM`."

    Design: Difficulty/boundary_precision_check/award_with_empty_eligible_pool_returns_no_eligible_claim
    """
    fac_id, cl_id, order_id, shift_id, clm_id = _setup_revoked_claimant()
    shift = validate_success(api.get_shift(shift_id, make_scheduler_headers(fac_id)), 200)
    assert shift["claim_count"] == 1
    resp = api.award_shift(shift_id, {"expected_shift_version": shift["version"]}, make_scheduler_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CLAIM.value, 409)
    shift_after = validate_success(api.get_shift(shift_id, make_scheduler_headers(fac_id)), 200)
    assert shift_after["status"] == "OPEN"


def test_award_empty_pool_leaves_claim_pending_and_no_assignment(api):
    """PRD 3.5: "it filters to the shift's `PENDING` claims whose clinician is `ACTIVE`
    and passes the credential, overlap, rest, and weekly-hours gates, then ranks the
    survivors by live `reliability_score` descending, breaking ties by earliest
    `claimed_at` and then earliest `created_at`, and takes the top candidate."

    Design: Difficulty/boundary_precision_check/award_with_empty_eligible_pool_returns_no_eligible_claim
    """
    fac_id, cl_id, order_id, shift_id, clm_id = _setup_revoked_claimant()
    shift = validate_success(api.get_shift(shift_id, make_scheduler_headers(fac_id)), 200)
    resp = api.award_shift(shift_id, {"expected_shift_version": shift["version"]}, make_scheduler_headers(fac_id))
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CLAIM.value, 409)
    assert validate_success(api.get_claim(clm_id, ADMIN), 200)["status"] == "PENDING"
    order_after = validate_success(api.get_order(order_id, make_scheduler_headers(fac_id)), 200)
    assert order_after["filled_count"] == 0 and order_after["open_count"] == 1
    asgs, meta = validate_paginated(api.list_assignments(make_scheduler_headers(fac_id), params={"shift_id": shift_id}))
    assert meta["total_count"] == 0


# --------------------------------------------------------------------------- #
# Difficulty: confirm blocked because a DIFFERENT entity (the Clinician) is suspended
# --------------------------------------------------------------------------- #
def _setup_suspended_with_unconfirmed_third_assignment():
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Ironwood", unit_capacity=2)
    fx.add_rate_card(fac["id"])
    cl = fx.new_clinician(full_name="Milo Reyes", email="milo.reyes@example.com")
    fx.add_verified_credential(cl["id"])
    fac_id, cl_id = fac["id"], cl["id"]
    order = fx.new_order(fac_id, headcount=3)
    s1 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    s2 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-09T07:00:00Z", scheduled_end="2026-06-09T15:00:00Z")
    s3 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-10T07:00:00Z", scheduled_end="2026-06-10T19:00:00Z")
    c1 = fx.place_claim(s1["id"], cl_id)
    a1 = fx.award(s1["id"], fac_id, claim_id=c1["id"])
    fx.confirm(a1["id"], cl_id)
    c2 = fx.place_claim(s2["id"], cl_id)
    a2 = fx.award(s2["id"], fac_id, claim_id=c2["id"])
    fx.confirm(a2["id"], cl_id)
    c3 = fx.place_claim(s3["id"], cl_id)
    a3 = fx.award(s3["id"], fac_id, claim_id=c3["id"])
    fx.set_clock("2026-06-09T15:30:00Z")
    fx.no_show(a1["id"], fac_id, note="absent")
    fx.no_show(a2["id"], fac_id, note="absent again")
    return fac_id, cl_id, s3["id"], a3["id"]


def test_confirm_blocked_by_suspended_clinician_error_id(api):
    """PRD 3.5: "Confirming a suspended clinician's assignment raises
    `ERR_CLINICIAN_SUSPENDED`; confirming an assignment whose work axis is already
    terminal raises `ERR_ASSIGNMENT_NOT_CANCELLABLE`."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_suspended_clinician
    """
    fac_id, cl_id, s3_id, a3_id = _setup_suspended_with_unconfirmed_third_assignment()
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["status"] == "SUSPENDED"
    assert clinician["provisional_reliability_score"] == 40
    resp = api.confirm_assignment(a3_id, {}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SUSPENDED.value, 409)


def test_confirm_blocked_by_suspended_clinician_leaves_assignment_pending(api):
    """PRD 3.5: "Confirmation is permitted only by the assigned clinician, only while
    the assignment is in `PENDING_CONFIRMATION`, only while the clinician is `ACTIVE`,
    and only before the shift's `scheduled_start`; it moves `work_status`
    `PENDING_CONFIRMATION → CONFIRMED`, records `confirmed_at`, bumps the assignment's
    `version`, and leaves the pay axis untouched."

    Design: Difficulty/cross_entity_state_dependency/confirm_blocked_by_suspended_clinician
    """
    fac_id, cl_id, s3_id, a3_id = _setup_suspended_with_unconfirmed_third_assignment()
    resp = api.confirm_assignment(a3_id, {}, make_clinician_headers(cl_id))
    validate_error(resp, ApiErrorId.ERR_CLINICIAN_SUSPENDED.value, 409)
    asg = validate_success(api.get_assignment(a3_id, make_scheduler_headers(fac_id)), 200)
    assert asg["work_status"] == "PENDING_CONFIRMATION" and asg["pay_status"] == "UNBILLED"
    shift = validate_success(api.get_shift(s3_id, make_scheduler_headers(fac_id)), 200)
    assert shift["status"] == "ASSIGNED"


# --------------------------------------------------------------------------- #
# Difficulty: award then compensating cancel restores the slot partition
# --------------------------------------------------------------------------- #
def _setup_award_then_prepare_cancel():
    fx.set_clock("2026-06-01T00:00:00Z")
    fac = fx.new_facility(name="Ashfield", unit_capacity=2)
    fx.add_rate_card(fac["id"])
    cl = fx.new_clinician(full_name="Pia Larsen", email="pia.larsen@example.com")
    fx.add_verified_credential(cl["id"])
    fac_id, cl_id = fac["id"], cl["id"]
    order = fx.new_order(fac_id, headcount=2)
    s1 = fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-08T07:00:00Z", scheduled_end="2026-06-08T19:00:00Z")
    fx.add_shift(order["id"], fac_id, scheduled_start="2026-06-09T07:00:00Z", scheduled_end="2026-06-09T15:00:00Z")
    before = validate_success(fx.api_client.get_order(order["id"], make_scheduler_headers(fac_id)), 200)
    assert before["open_count"] == 2 and before["filled_count"] == 0 and before["status"] == "OPEN"
    clm = fx.place_claim(s1["id"], cl_id)
    asg = fx.award(s1["id"], fac_id, claim_id=clm["id"])
    mid = validate_success(fx.api_client.get_order(order["id"], make_scheduler_headers(fac_id)), 200)
    assert mid["open_count"] == 1 and mid["filled_count"] == 1 and mid["status"] == "PARTIALLY_FILLED"
    return fac_id, cl_id, order["id"], s1["id"], clm["id"], asg["id"]


def test_award_then_cancel_restores_slot_partition(api):
    """PRD 3.3: "these counters always satisfy `shift_count` equals `open_count` plus
    `filled_count` plus `cancelled_count`."
    PRD 3.5: "the shift returns `ASSIGNED → OPEN` so the slot can be backfilled, the
    order's fill posture is recomputed, and the assignment's `version` is bumped."

    Design: Difficulty/compensating_invariant/award_then_cancel_restores_order_slot_partition
    """
    fac_id, cl_id, order_id, s1_id, clm_id, asg_id = _setup_award_then_prepare_cancel()
    cancelled = validate_success(
        api.cancel_assignment(asg_id, {"reason": "family emergency, cancelled a week ahead"},
                              make_clinician_headers(cl_id)), 200)
    assert cancelled["work_status"] == "CANCELLED_BY_CLINICIAN"
    # lead = 2026-06-08T07:00 - 2026-06-01T00:00 = 175.00 hours (well above the free tier).
    assert cancelled["cancellation_lead_hours"] == 175.00
    order_after = validate_success(api.get_order(order_id, make_scheduler_headers(fac_id)), 200)
    assert order_after["status"] == "OPEN"
    assert order_after["open_count"] == 2 and order_after["filled_count"] == 0
    assert order_after["cancelled_count"] == 0 and order_after["shift_count"] == 2
    assert order_after["shift_count"] == (
        order_after["open_count"] + order_after["filled_count"] + order_after["cancelled_count"]
    )


def test_award_then_cancel_waives_pay_and_records_no_reliability_event(api):
    """PRD 3.5: "if the lead is at least 72 hours, no reliability event is recorded at
    all".
    PRD 3.5: "A cancellation computes `cancellation_lead_hours` as the span from the
    current instant to the shift's `scheduled_start`, expressed in hours to two
    decimals, and sets `pay_status` to `WAIVED` and `cancellation_reason` to the
    supplied `reason`."

    Design: Difficulty/compensating_invariant/award_then_cancel_restores_order_slot_partition
    """
    fac_id, cl_id, order_id, s1_id, clm_id, asg_id = _setup_award_then_prepare_cancel()
    cancelled = validate_success(
        api.cancel_assignment(asg_id, {"reason": "family emergency, cancelled a week ahead"},
                              make_clinician_headers(cl_id)), 200)
    assert cancelled["pay_status"] == "WAIVED"
    shift = validate_success(api.get_shift(s1_id, make_scheduler_headers(fac_id)), 200)
    assert shift["status"] == "OPEN"
    events, meta = validate_paginated(api.list_clinician_reliability_events(cl_id, OFFICER))
    assert meta["total_count"] == 0
    clinician = validate_success(api.get_clinician(cl_id, ADMIN), 200)
    assert clinician["provisional_reliability_score"] == 100 and clinician["reliability_score"] == 100
    assert validate_success(api.get_claim(clm_id, ADMIN), 200)["status"] == "AWARDED"
