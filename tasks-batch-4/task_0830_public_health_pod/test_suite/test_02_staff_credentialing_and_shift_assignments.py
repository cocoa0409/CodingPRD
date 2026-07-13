"""Volunteer roster/credentialing and shift-assignment confirmation safeguards:
required fields, direct PENDING->REVOKED transition, time-range validation,
cross-entity credential gating, pairwise/aggregate overlap, boundary-precise
credential expiry, validation-priority ordering, the committed_staff_hours
compensating invariant, and Volunteer ownership."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_volunteer_headers,
    create_staff_member_payload,
    create_activated_hazard_plan,
    create_open_pod,
    create_unverified_staff_member,
    create_verified_staff_member,
    create_shift_assignment,
    confirm_shift_assignment,
    create_confirmed_shift_assignment,
    check_in_shift_assignment,
    cancel_shift_assignment,
    set_clock,
)


def test_staff_member_missing_credential_expires_at_rejected(api, admin_headers):
    """PRD §3.3: "`PublicHealthAdmin` registers each Medical Reserve Corps
    volunteer by supplying a `full_name`, a contact `email` (which must be
    unique across every `StaffMember`), a `primary_role` — one of
    `CLINICAL_LEAD`, `SCREENER`, `VACCINATOR`, `RUNNER`, `TRAFFIC_CONTROL`, or
    `GREETER` — an `mrc_unit` affiliation, a `credential_type` — one of
    `RN_LICENSE`, `MD_LICENSE`, `EMT_CERT`, `NIMS_IS100_700`,
    `BACKGROUND_CHECK`, or `PODS_TRAINING` — and that credential's
    `credential_expires_at` timestamp."

    Design: Corner/entities/staff_member_missing_required_field_rejected
    """
    payload = create_staff_member_payload(
        full_name="Incomplete Staff", email="incomplete@example.org",
        primary_role="GREETER", mrc_unit="UnitN", credential_type="PODS_TRAINING",
    )
    del payload["credential_expires_at"]
    res = api.create_staff_member(payload, admin_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_staff_member_pending_directly_to_revoked(api, admin_headers):
    """PRD §3.3: "`PublicHealthAdmin` verifies the credential to move it to
    `VERIFIED`, or revokes it — from either `PENDING` or `VERIFIED` — to move it
    to the terminal `REVOKED` state."

    Design: Corner/state_machines/staff_member_pending_directly_to_revoked
    """
    staff = create_unverified_staff_member(primary_role="RUNNER", credential_type="BACKGROUND_CHECK")
    assert staff["credential_status"] == "PENDING"

    res = api.revoke_staff_credential(staff["id"], admin_headers)
    revoked = validate_success(res, 200)
    assert revoked["credential_status"] == "REVOKED"


def test_shift_assignment_invalid_time_range_rejected(api, admin_headers):
    """PRD §3.3: "The proposer supplies `pod_id`, `staff_member_id`,
    `assigned_role`, a `start_time`, and an `end_time`; the request is rejected
    with `ERR_INVALID_TIME_RANGE` unless `start_time` is strictly before
    `end_time`."

    Design: Corner/validations/shift_assignment_invalid_time_range_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_unverified_staff_member(primary_role="RUNNER")

    res = api.create_shift_assignment(
        {
            "pod_id": pod["id"], "staff_member_id": staff["id"], "assigned_role": "RUNNER",
            "start_time": "2026-03-10T16:00:00Z", "end_time": "2026-03-10T08:00:00Z",
        },
        admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_RANGE)


def test_shift_confirm_blocked_while_credential_pending(api, admin_headers, clinical_headers):
    """PRD §2.10: "A staff member's credential must additionally be `VERIFIED`,
    and its `credential_expires_at` must be strictly later than the current
    logical clock time, before any shift for that staff member can be
    confirmed."

    Design: Difficulty/cross_entity_state_dependency/shift_confirm_blocked_by_unverified_credential
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_unverified_staff_member(primary_role="VACCINATOR")
    shift = create_shift_assignment(pod["id"], staff["id"], assigned_role="VACCINATOR")

    res = api.confirm_shift_assignment(shift["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_CREDENTIAL_NOT_VERIFIED)


def test_shift_confirm_succeeds_after_credential_verified(api, admin_headers, clinical_headers):
    """PRD §2.10: "A staff member's credential must additionally be `VERIFIED`,
    and its `credential_expires_at` must be strictly later than the current
    logical clock time, before any shift for that staff member can be
    confirmed."

    Design: Difficulty/cross_entity_state_dependency/shift_confirm_blocked_by_unverified_credential
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_unverified_staff_member(primary_role="VACCINATOR")
    shift = create_shift_assignment(pod["id"], staff["id"], assigned_role="VACCINATOR")
    validate_error(api.confirm_shift_assignment(shift["id"], clinical_headers), ApiErrorId.ERR_CREDENTIAL_NOT_VERIFIED)

    api.verify_staff_credential(staff["id"], admin_headers)
    res = api.confirm_shift_assignment(shift["id"], clinical_headers)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED"


def test_overlapping_shift_confirm_rejected_same_staff_member(api, clinical_headers):
    """PRD §2.10: "The first is pairwise: no two `ShiftAssignment` rows for the
    same `staff_member_id`, both in `CONFIRMED` or `CHECKED_IN` status, may have
    overlapping `[start_time, end_time)` intervals — the interval is half-open,
    so a shift ending exactly when another begins does not count as an
    overlap."

    Design: Difficulty/resource_temporal_overlap/shift_overlap_rejected_same_staff_member
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")
    create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )
    shift2 = create_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T12:00:00Z", end_time="2026-03-05T20:00:00Z",
    )

    res = api.confirm_shift_assignment(shift2["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_adjacent_non_overlapping_shift_confirm_succeeds(api, clinical_headers):
    """PRD §2.10: "The first is pairwise: no two `ShiftAssignment` rows for the
    same `staff_member_id`, both in `CONFIRMED` or `CHECKED_IN` status, may have
    overlapping `[start_time, end_time)` intervals — the interval is half-open,
    so a shift ending exactly when another begins does not count as an
    overlap."

    Design: Difficulty/resource_temporal_overlap/shift_overlap_rejected_same_staff_member
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")
    create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )
    shift2 = create_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T16:00:00Z", end_time="2026-03-05T20:00:00Z",
    )

    res = api.confirm_shift_assignment(shift2["id"], clinical_headers)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED", (
        "a shift starting exactly when another ends must not be treated as overlapping"
    )


def test_third_overlapping_confirm_exceeds_pod_capacity(api, admin_headers, clinical_headers):
    """PRD §2.10: "The second is aggregate: counting every `CONFIRMED` or
    `CHECKED_IN` `ShiftAssignment` at the same POD whose interval overlaps the
    one being confirmed (including the one being confirmed itself), that count
    may not exceed the POD's `staffing_capacity_lanes`."

    Design: Difficulty/resource_temporal_overlap/pod_capacity_exceeded_on_third_overlapping_confirm
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"], staffing_capacity_lanes=2)
    window = {"start_time": "2026-03-06T08:00:00Z", "end_time": "2026-03-06T16:00:00Z"}

    staff1 = create_verified_staff_member(primary_role="VACCINATOR")
    create_confirmed_shift_assignment(pod["id"], staff1["id"], assigned_role="VACCINATOR", **window)
    staff2 = create_verified_staff_member(primary_role="SCREENER")
    create_confirmed_shift_assignment(pod["id"], staff2["id"], assigned_role="SCREENER", **window)

    staff3 = create_verified_staff_member(primary_role="RUNNER")
    shift3 = create_shift_assignment(pod["id"], staff3["id"], assigned_role="RUNNER", **window)

    res = api.confirm_shift_assignment(shift3["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_POD_CAPACITY_EXCEEDED)


def test_confirm_at_exact_pod_capacity_succeeds(api, admin_headers, clinical_headers):
    """PRD §2.10: "The second is aggregate: counting every `CONFIRMED` or
    `CHECKED_IN` `ShiftAssignment` at the same POD whose interval overlaps the
    one being confirmed (including the one being confirmed itself), that count
    may not exceed the POD's `staffing_capacity_lanes`."

    Design: Difficulty/resource_temporal_overlap/pod_capacity_exceeded_on_third_overlapping_confirm
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"], staffing_capacity_lanes=2)
    window = {"start_time": "2026-03-06T08:00:00Z", "end_time": "2026-03-06T16:00:00Z"}

    staff1 = create_verified_staff_member(primary_role="VACCINATOR")
    create_confirmed_shift_assignment(pod["id"], staff1["id"], assigned_role="VACCINATOR", **window)

    staff2 = create_verified_staff_member(primary_role="SCREENER")
    shift2 = create_shift_assignment(pod["id"], staff2["id"], assigned_role="SCREENER", **window)
    res = api.confirm_shift_assignment(shift2["id"], clinical_headers)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED", (
        "the overlapping-CONFIRMED count reaches exactly staffing_capacity_lanes(2); "
        "must not be exceeded, so this confirm succeeds"
    )


def test_confirm_rejected_when_credential_expires_at_exactly_equals_clock(api, admin_headers, clinical_headers):
    """PRD §2.10: "A staff member's credential must additionally be `VERIFIED`,
    and its `credential_expires_at` must be strictly later than the current
    logical clock time, before any shift for that staff member can be
    confirmed."

    Design: Difficulty/boundary_precision_check/credential_expires_at_exact_equal_to_clock_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    set_clock("2026-03-02T10:00:00Z")
    staff = create_verified_staff_member(
        primary_role="VACCINATOR", credential_expires_at="2026-03-02T10:00:00Z",
    )
    shift = create_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )

    res = api.confirm_shift_assignment(shift["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_CREDENTIAL_EXPIRED)


def test_confirm_succeeds_when_credential_expires_at_one_second_after_clock(api, admin_headers, clinical_headers):
    """PRD §2.10: "A staff member's credential must additionally be `VERIFIED`,
    and its `credential_expires_at` must be strictly later than the current
    logical clock time, before any shift for that staff member can be
    confirmed."

    Design: Difficulty/boundary_precision_check/credential_expires_at_exact_equal_to_clock_rejected
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    set_clock("2026-03-02T10:00:00Z")
    staff = create_verified_staff_member(
        primary_role="SCREENER", credential_expires_at="2026-03-02T10:00:01Z",
    )
    shift = create_shift_assignment(
        pod["id"], staff["id"], assigned_role="SCREENER",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )

    res = api.confirm_shift_assignment(shift["id"], clinical_headers)
    confirmed = validate_success(res, 200)
    assert confirmed["status"] == "CONFIRMED"


def test_second_confirm_on_confirmed_assignment_returns_invalid_state_not_credential_expired(
    api, admin_headers, clinical_headers
):
    """PRD §2.6: "Only after both existence passes succeed does the system
    evaluate whether the target resource is in a state from which the
    requested trigger has a declared transition (`ERR_INVALID_STATE`, 409),
    followed by the endpoint's specific business-safety, business-temporal,
    business-referential, and business-constraint checks..."

    Design: Difficulty/priority_pair_validation_conflict/shift_confirm_wrong_state_beats_credential_expired
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    set_clock("2026-03-01T00:00:00Z")
    staff = create_verified_staff_member(
        primary_role="VACCINATOR", credential_expires_at="2026-03-02T09:00:00Z",
    )
    shift = create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )
    set_clock("2026-03-03T00:00:00Z")  # now after staff's credential_expires_at

    res = api.confirm_shift_assignment(shift["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_on_cancelled_assignment_with_expired_credential_returns_invalid_state(
    api, admin_headers, clinical_headers
):
    """PRD §2.6: "Only after both existence passes succeed does the system
    evaluate whether the target resource is in a state from which the
    requested trigger has a declared transition (`ERR_INVALID_STATE`, 409),
    followed by the endpoint's specific business-safety, business-temporal,
    business-referential, and business-constraint checks..."

    Design: Difficulty/priority_pair_validation_conflict/shift_confirm_wrong_state_beats_credential_expired
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    set_clock("2026-03-02T10:00:00Z")
    staff = create_verified_staff_member(
        primary_role="RUNNER", credential_expires_at="2026-03-02T11:00:00Z",
    )
    shift = create_shift_assignment(
        pod["id"], staff["id"], assigned_role="RUNNER",
        start_time="2026-03-05T08:00:00Z", end_time="2026-03-05T16:00:00Z",
    )
    cancel_shift_assignment(shift["id"], admin_headers)
    set_clock("2026-03-03T00:00:00Z")  # now after staff's credential_expires_at

    res = api.confirm_shift_assignment(shift["id"], clinical_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_shift_increases_committed_staff_hours(api, admin_headers):
    """PRD §3.2: "`committed_staff_hours` sums, in hours, the `end_time` minus
    `start_time` interval of every `ShiftAssignment` at this POD currently
    `CONFIRMED`, `CHECKED_IN`, or `COMPLETED`; confirming a shift adds its
    duration..."

    Design: Difficulty/compensating_invariant/shift_confirm_then_cancel_restores_committed_staff_hours
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")

    create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-07T08:00:00Z", end_time="2026-03-07T16:00:00Z",
    )

    pod_after = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after["committed_staff_hours"] == 8


def test_cancel_confirmed_shift_restores_committed_staff_hours_to_zero(api, admin_headers):
    """PRD §3.3: "...cancelling a `CONFIRMED` assignment restores the POD's
    `committed_staff_hours` by subtracting exactly the amount that confirming
    it had added."

    Design: Difficulty/compensating_invariant/shift_confirm_then_cancel_restores_committed_staff_hours
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    staff = create_verified_staff_member(primary_role="VACCINATOR")

    shift = create_confirmed_shift_assignment(
        pod["id"], staff["id"], assigned_role="VACCINATOR",
        start_time="2026-03-07T08:00:00Z", end_time="2026-03-07T16:00:00Z",
    )
    pod_after_confirm = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after_confirm["committed_staff_hours"] == 8

    cancel_shift_assignment(shift["id"], admin_headers)
    pod_after_cancel = validate_success(api.get_pod(pod["id"], admin_headers), 200)
    assert pod_after_cancel["committed_staff_hours"] == 0


def test_volunteer_ownership_mismatch_on_shift_cancel(api):
    """PRD §2.1: "...when the acting role is `Volunteer` on the shift-proposal
    endpoint, the shift-cancellation endpoint, or the shift-check-in endpoint,
    `X-User-ID` must equal the resource's `staff_member_id` (or, on creation,
    the `staff_member_id` supplied in the payload); a mismatch is rejected with
    `ERR_OWNERSHIP_MISMATCH` (403)."

    Design: Corner/rbac/volunteer_ownership_mismatch_on_shift_cancel
    """
    hp = create_activated_hazard_plan()
    pod = create_open_pod(hp["id"])
    vol_a = create_unverified_staff_member(primary_role="GREETER", credential_type="PODS_TRAINING")
    vol_b = create_unverified_staff_member(primary_role="GREETER", credential_type="PODS_TRAINING")

    shift = create_shift_assignment(
        pod["id"], vol_a["id"], assigned_role="GREETER",
        start_time="2026-03-12T08:00:00Z", end_time="2026-03-12T16:00:00Z",
        headers=make_volunteer_headers(vol_a["id"]),
    )

    res = api.cancel_shift_assignment(shift["id"], make_volunteer_headers(vol_b["id"]))
    validate_error(res, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
