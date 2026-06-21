"""Validation precedence ordering, conserved-quantity invariants, and boundary
precision.

Difficulty queue (A): priority_pair_validation_conflict, compensating_invariant,
boundary_precision_check.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    setup_site_floor_host,
    create_site, create_floor, create_host,
    create_visit, screen_visit, create_cleared_visit,
    get_floor_version, sign_in_visit, set_clock,
    setup_floor_at_capacity_with_pending_second_visit,
    TEST_USERS,
)

SO = TEST_USERS["security_officer_headers"]
LA = TEST_USERS["lobby_attendant_headers"]


def test_state_check_precedes_segregation_on_clearance(api):
    """PRD 2.7: "The state-machine guard comes sixth: a target resource that is not
    in a legal state for the requested transition yields `ERR_INVALID_STATE` (HTTP
    409). Only after all of those pass does the system evaluate the domain-specific
    business-safety, referential, temporal, and capacity rules."
    PRD 3.4: "Adjudication is permitted only while the visit is `FLAGGED`."

    A CLEARED (not FLAGGED) visit whose clearance is attempted by its own host returns
    ERR_INVALID_STATE — the state guard outranks the segregation-of-duties check.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_segregation_on_clearance
    """
    site, floor, host = setup_site_floor_host()
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Clean Visitor", visitor_company="CleanCo", id_scanned=True,
    )
    screened = screen_visit(visit["id"])  # no watchlist -> CLEARED
    assert screened["status"] == "CLEARED"
    # Officer's X-User-ID == host_id would trip segregation if state passed.
    from test_helpers import make_security_officer_headers
    res = api.clearance_visit(
        visit["id"],
        {"decision": "CLEAR", "expected_visit_version": screened["version"]},
        make_security_officer_headers(host["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_id_not_scanned_precedes_floor_capacity_on_signin(api):
    """PRD 3.6: "the visit's `id_scanned` must be `true`, or the request is rejected
    with `ERR_ID_NOT_SCANNED`; every agreement attached to the visit must be `SIGNED`
    with none left `PENDING`, or the request is rejected with `ERR_AGREEMENT_NOT_SIGNED`;
    if the visit carries a `contractor_pass_id`, the referenced pass must be in
    `ACTIVE` status, or the request is rejected with `ERR_PASS_NOT_ACTIVE`; and for a
    contractor-covered visit the `scheduled_start` must fall on or after
    `access_valid_from` and on or before `access_valid_until`, the inclusive
    recurring-access window, or the request is rejected with `ERR_PASS_WINDOW`. The
    floor must then have at least one free slot — `available_slots` of 1 or more — or
    the request is rejected with `ERR_FLOOR_AT_CAPACITY`".

    On a full floor, a CLEARED visit with id_scanned=false returns ERR_ID_NOT_SCANNED:
    the id-scan check is evaluated before the capacity check.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_idscan_beats_floor_capacity_on_signin
    """
    site, floor, host, v1, v2, floor_v_after = (
        setup_floor_at_capacity_with_pending_second_visit(second_id_scanned=False)
    )
    res = api.sign_in_visit(v2["id"], {"expected_floor_version": floor_v_after}, LA)
    validate_error(res, ApiErrorId.ERR_ID_NOT_SCANNED)

    fetched = validate_success(api.get_visit(v2["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_floor_occupancy_conserved_after_signin_then_signout(api):
    """PRD 2.9: "For each `Floor`, `current_occupancy` is the count of visits with
    that `floor_id` currently in `SIGNED_IN` status, and `available_slots` is
    `capacity` minus `current_occupancy`. The floor-occupancy invariant likewise holds
    at all times: `capacity` always equals `current_occupancy` plus `available_slots`.
    Signing a visitor in debits both pools by one; signing the visitor out is the
    compensating action that credits both pools back by one, restoring each invariant
    exactly."

    After sign-in then sign-out on a capacity-5 floor, current_occupancy returns to 0
    and available_slots to 5.

    Design: Difficulty/compensating_invariant/ci_floor_occupancy_conserved_signin_signout
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Conserve Me", visitor_company="CCo",
    )
    signed_in = sign_in_visit(visit["id"], floor["id"])
    validate_success(api.sign_out_visit(signed_in["id"], LA))

    fetched_floor = validate_success(api.get_floor(floor["id"], LA))
    assert fetched_floor["current_occupancy"] == 0, (
        f"expected current_occupancy 0, got {fetched_floor['current_occupancy']}"
    )
    assert fetched_floor["available_slots"] == 5, (
        f"expected available_slots 5, got {fetched_floor['available_slots']}"
    )


def test_badge_inventory_conserved_after_signin_then_signout(api):
    """PRD 2.9: "For each `Site`, `badge_in_use` is the count of visits at that site
    currently in `SIGNED_IN` status, and `badge_available` is `badge_total` minus
    `badge_in_use`. The badge-inventory invariant holds at all times: `badge_total`
    always equals `badge_in_use` plus `badge_available`. ... Signing a visitor in
    debits both pools by one; signing the visitor out is the compensating action that
    credits both pools back by one, restoring each invariant exactly."

    On a badge_total-3 site, after sign-in then sign-out badge_in_use returns to 0 and
    badge_available to 3.

    Design: Difficulty/compensating_invariant/ci_badge_inventory_conserved_signin_signout
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=3, capacity=5)
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Badge Me", visitor_company="BCo",
    )
    signed_in = sign_in_visit(visit["id"], floor["id"])
    validate_success(api.sign_out_visit(signed_in["id"], LA))

    fetched_site = validate_success(api.get_site(site["id"], SO))
    assert fetched_site["badge_in_use"] == 0, (
        f"expected badge_in_use 0, got {fetched_site['badge_in_use']}"
    )
    assert fetched_site["badge_available"] == 3, (
        f"expected badge_available 3, got {fetched_site['badge_available']}"
    )


def test_visit_duration_zero_elapsed_is_zero_minutes(api):
    """PRD 3.6: "The system computes `visit_duration_minutes` as the elapsed time from
    `sign_in_at` to `sign_out_at` rounded up to whole minutes: the elapsed number of
    seconds divided by 60 and rounded up to the next whole minute, with the boundary
    case of exactly zero elapsed seconds yielding 0 minutes rather than 1."

    Sign-in and sign-out both at 09:00:00 (0 elapsed seconds) -> 0 minutes.

    Design: Difficulty/boundary_precision_check/bpc_visit_duration_zero_seconds_is_zero_minutes
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Zero Dur", visitor_company="ZeroCo",
    )
    signed_in = sign_in_visit(visit["id"], floor["id"])
    signed_out = validate_success(api.sign_out_visit(signed_in["id"], LA))
    assert signed_out["visit_duration_minutes"] == 0, (
        f"expected 0 minutes, got {signed_out['visit_duration_minutes']}"
    )
    assert signed_out["status"] == "SIGNED_OUT", (
        f"expected SIGNED_OUT, got {signed_out['status']}"
    )


def test_evacuation_empty_floor_yields_zero_roster(api):
    """PRD 3.9: "it captures `roster_visit_ids` as the ordered array of `id` values of
    every visit currently in `SIGNED_IN` status on that floor, ordered by `sign_in_at`
    ascending and then by `created_at` ascending as the tie-break. The
    `roster_head_count` is the length of that snapshot array."

    A floor with no signed-in visitors yields roster_head_count 0 and an empty
    roster_visit_ids.

    Design: Difficulty/boundary_precision_check/bpc_evacuation_empty_roster_zero_head_count
    """
    site = create_site(badge_total=5)
    floor = create_floor(site["id"], capacity=5)
    event = validate_success(
        api.create_evacuation_event(
            {"floor_id": floor["id"], "triggered_reason": "FIRE_DRILL"}, SO
        ),
        201,
    )
    assert event["roster_head_count"] == 0, (
        f"expected roster_head_count 0, got {event['roster_head_count']}"
    )
    assert event["roster_visit_ids"] == [], (
        f"expected empty roster, got {event['roster_visit_ids']}"
    )


def test_cleared_state_check_does_not_change_visit_on_clearance(api):
    """PRD 2.7: "The state-machine guard comes sixth: a target resource that is not in
    a legal state for the requested transition yields `ERR_INVALID_STATE` (HTTP 409).
    Only after all of those pass does the system evaluate the domain-specific
    business-safety, referential, temporal, and capacity rules."
    PRD 3.4: "Adjudication is permitted only while the visit is `FLAGGED`."

    The rejected clearance leaves the visit CLEARED and does not stamp a denial — the
    state guard short-circuits before the segregation check could apply.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_state_beats_segregation_on_clearance
    """
    from test_helpers import make_security_officer_headers
    site, floor, host = setup_site_floor_host()
    visit = create_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Clean Visitor", visitor_company="CleanCo", id_scanned=True,
    )
    screened = screen_visit(visit["id"])
    res = api.clearance_visit(
        visit["id"],
        {"decision": "DENY", "expected_visit_version": screened["version"]},
        make_security_officer_headers(host["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)
    fetched = validate_success(api.get_visit(visit["id"], LA))
    assert fetched["status"] == "CLEARED", f"expected CLEARED, got {fetched['status']}"


def test_id_scan_rejection_does_not_print_badge_on_full_floor(api):
    """PRD 3.6: "the visit's `id_scanned` must be `true`, or the request is rejected
    with `ERR_ID_NOT_SCANNED`; ... The floor must then have at least one free slot —
    `available_slots` of 1 or more — or the request is rejected with
    `ERR_FLOOR_AT_CAPACITY`".

    The id-scan failure (evaluated first) leaves the second visit CLEARED with no
    badge — the capacity rule never fires.

    Design: Difficulty/priority_pair_validation_conflict/ppvc_idscan_beats_floor_capacity_on_signin
    """
    site, floor, host, v1, v2, floor_v_after = (
        setup_floor_at_capacity_with_pending_second_visit(second_id_scanned=False)
    )
    res = api.sign_in_visit(v2["id"], {"expected_floor_version": floor_v_after}, LA)
    validate_error(res, ApiErrorId.ERR_ID_NOT_SCANNED)
    fetched = validate_success(api.get_visit(v2["id"], LA))
    assert fetched["status"] == "CLEARED"
    assert fetched["badge_number"] is None, "no badge printed when sign-in is rejected"


def test_floor_invariant_holds_after_signin_signout_cycle(api):
    """PRD 2.9: "The floor-occupancy invariant likewise holds at all times:
    `capacity` always equals `current_occupancy` plus `available_slots`. Signing a
    visitor in debits both pools by one; signing the visitor out is the compensating
    action that credits both pools back by one, restoring each invariant exactly."

    capacity == current_occupancy + available_slots holds after the full cycle (5 == 0
    + 5), confirming the conserved-quantity equation, not just the reset values.

    Design: Difficulty/compensating_invariant/ci_floor_occupancy_conserved_signin_signout
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Conserve Me", visitor_company="CCo",
    )
    signed_in = sign_in_visit(visit["id"], floor["id"])
    validate_success(api.sign_out_visit(signed_in["id"], LA))
    fetched_floor = validate_success(api.get_floor(floor["id"], LA))
    assert (
        fetched_floor["capacity"]
        == fetched_floor["current_occupancy"] + fetched_floor["available_slots"]
    ), "floor-occupancy invariant must hold"
    assert fetched_floor["current_occupancy"] == 0


def test_badge_invariant_holds_after_signin_signout_cycle(api):
    """PRD 2.9: "The badge-inventory invariant holds at all times: `badge_total`
    always equals `badge_in_use` plus `badge_available`. ... Signing a visitor in
    debits both pools by one; signing the visitor out is the compensating action that
    credits both pools back by one, restoring each invariant exactly."

    badge_total == badge_in_use + badge_available holds after the cycle (3 == 0 + 3),
    confirming the conserved equation.

    Design: Difficulty/compensating_invariant/ci_badge_inventory_conserved_signin_signout
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=3, capacity=5)
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Badge Me", visitor_company="BCo",
    )
    signed_in = sign_in_visit(visit["id"], floor["id"])
    validate_success(api.sign_out_visit(signed_in["id"], LA))
    fetched_site = validate_success(api.get_site(site["id"], SO))
    assert (
        fetched_site["badge_total"]
        == fetched_site["badge_in_use"] + fetched_site["badge_available"]
    ), "badge-inventory invariant must hold"
    assert fetched_site["badge_in_use"] == 0


def test_visit_duration_zero_elapsed_reaches_signed_out(api):
    """PRD 3.6: "The visit moves `SIGNED_IN → SIGNED_OUT`, a terminal state, and the
    server stamps `sign_out_at`. The system computes `visit_duration_minutes` as the
    elapsed time from `sign_in_at` to `sign_out_at` rounded up to whole minutes: ...
    with the boundary case of exactly zero elapsed seconds yielding 0 minutes rather
    than 1."

    The zero-elapsed visit reaches the terminal SIGNED_OUT state with a stamped
    sign_out_at and duration 0.

    Design: Difficulty/boundary_precision_check/bpc_visit_duration_zero_seconds_is_zero_minutes
    """
    set_clock("2026-06-16T09:00:00Z")
    site, floor, host = setup_site_floor_host(badge_total=5, capacity=5)
    visit = create_cleared_visit(
        site["id"], host["id"], floor["id"],
        visitor_full_name="Zero Dur", visitor_company="ZeroCo",
    )
    signed_in = sign_in_visit(visit["id"], floor["id"])
    signed_out = validate_success(api.sign_out_visit(signed_in["id"], LA))
    assert signed_out["status"] == "SIGNED_OUT"
    assert signed_out["sign_out_at"] is not None, "sign_out_at must be stamped"
    assert signed_out["visit_duration_minutes"] == 0


def test_evacuation_empty_roster_head_count_matches_length(api):
    """PRD 3.9: "The `roster_head_count` is the length of that snapshot array."
    PRD 3.9: "it captures `roster_visit_ids` as the ordered array of `id` values of
    every visit currently in `SIGNED_IN` status on that floor".

    On an empty floor, roster_head_count equals len(roster_visit_ids) == 0 (the
    length relationship, not only the literal zero).

    Design: Difficulty/boundary_precision_check/bpc_evacuation_empty_roster_zero_head_count
    """
    site = create_site(badge_total=5)
    floor = create_floor(site["id"], capacity=5)
    event = validate_success(
        api.create_evacuation_event(
            {"floor_id": floor["id"], "triggered_reason": "FIRE_DRILL"}, SO
        ),
        201,
    )
    assert event["roster_head_count"] == len(event["roster_visit_ids"])
    assert event["roster_head_count"] == 0
