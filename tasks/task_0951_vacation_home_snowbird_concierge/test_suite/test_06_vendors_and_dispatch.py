"""Vendor eligibility, the selection procedure, dispatch and the assignment lifecycle."""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUDITOR,
    DISPATCHER,
    ApiErrorId,
    assignment_for,
    make_vendor_headers,
    new_eligible_vendor,
    new_key_asset,
    new_vendor,
    refresh_assignment,
    refresh_vendor,
    refresh_work_order,
    set_clock,
    setup_completed_visit,
    setup_dispatched_work_order,
    setup_work_order,
    validate_error,
    validate_paginated,
    validate_success,
)

STANDARD = {"tier": "STANDARD", "monthly_fee_cents": 19986, "included_visit_units": 4,
            "covered_visit_types": ["ROUTINE_WATCH"]}


def test_reinstatement_below_the_rating_floor_is_refused(api):
    """PRD 3.6: "Reinstatement promotes an `ONBOARDING` or a `SUSPENDED` vendor to
    `ELIGIBLE`, and both edges carry the same three preconditions: `coi_expires_at`
    strictly after the logical clock, `license_expires_at` strictly after the logical
    clock, and a `rating` of at least 3.0. A rating below the floor is rejected with
    `ERR_VENDOR_RATING_BELOW_FLOOR`."

    Design: Corner/errors/err_vendor_rating_below_floor_on_reinstate_returns_409
    """
    set_clock("2026-06-01T00:00:00Z")
    vendor = new_vendor(legal_name="Low Rated Co", trade="HVAC", rating=2.5,
                        hourly_rate_cents=8000)
    assert vendor["status"] == "ONBOARDING"
    response = api.reinstate_vendor(vendor["id"], {}, DISPATCHER)
    validate_error(response, ApiErrorId.ERR_VENDOR_RATING_BELOW_FLOOR.value)
    assert refresh_vendor(vendor["id"])["status"] == "ONBOARDING"


def test_dispatch_creates_the_assignment_the_issuance_the_grant_and_the_rotation(api):
    """PRD 3.6: "It advances `dispatch_attempt_count` by one, creates a vendor assignment
    in `OFFERED` for the selected vendor with `offered_at` stamped to the logical clock and
    `coi_valid_at_offer` snapshotting whether the vendor's `coi_expires_at` was strictly
    after the clock at that instant"
    PRD 3.7: "`code_rotation_count` advances by one; `current_code` is rewritten to the
    previous code's integer value plus one, rendered as a four-character zero-padded
    decimal string, so that "1111" becomes "1112", and to the literal "0001" when the
    previous code was null or was not numeric"

    Design: Corner/endpoints/work_order_dispatch_action_endpoint_creates_the_whole_key_chain
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
                           description="Leaky joint", item_codes=("PLUMBING_CHECK",),
                           item_code="PLUMBING_CHECK")
    vendor = new_eligible_vendor(legal_name="Link Plumbing", trade="PLUMBING", rating=4.3)
    key_asset = new_key_asset(ctx["property_id"], key_type="LOCKBOX", label="Chain lockbox",
                              copies_total=2, current_code="5555")

    work_order = validate_success(api.dispatch_work_order(
        ctx["work_order_id"],
        {"window_start_at": "2026-06-03T09:00:00Z", "window_end_at": "2026-06-03T17:00:00Z"},
        DISPATCHER,
    ))
    assert work_order["status"] == "DISPATCHED"
    assert work_order["dispatch_attempt_count"] == 1

    assignments, meta = validate_paginated(
        api.list_vendor_assignments(headers=AUDITOR,
                                    params={"work_order_id": ctx["work_order_id"]})
    )
    assert meta["total_count"] == 1
    assert assignments[0]["status"] == "OFFERED"
    assert assignments[0]["vendor_id"] == vendor["id"]
    assert assignments[0]["access_blocked_flag"] is False

    issuances, i_meta = validate_paginated(
        api.list_key_issuances(headers=AUDITOR, params={"key_asset_id": key_asset["id"]})
    )
    assert i_meta["total_count"] == 1
    assert issuances[0]["status"] == "ISSUED"
    assert issuances[0]["copies_issued"] == 1

    grants, g_meta = validate_paginated(
        api.list_access_grants(headers=AUDITOR, params={"key_asset_id": key_asset["id"]})
    )
    assert g_meta["total_count"] == 1
    assert grants[0]["status"] == "PENDING"
    assert grants[0]["rotation_index_at_grant"] == 1

    reread_key = validate_success(api.get_key_asset(key_asset["id"], DISPATCHER))
    assert reread_key["code_rotation_count"] == 1
    assert reread_key["current_code"] == "5556"


def test_account_manager_may_not_dispatch(api):
    """PRD 2.1: "It exclusively owns seasonal transitions, vendor suspension, reinstatement
    and eligibility refresh, work-order dispatch, code rotation, key issuance, key return,
    overdue marking and loss declaration, access-grant creation, activation and
    revocation, assignment withdrawal, finding triage and monitoring, and visit conversion
    into a turnover inspection."
    PRD 2.8: "The acting role appears in the endpoint's declared role list, on every
    endpoint. Otherwise `ERR_ROLE_NOT_PERMITTED`, HTTP 403."

    Design: Corner/rbac/account_manager_cannot_dispatch_a_work_order
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
                           description="Drip", item_codes=("PLUMBING_CHECK",),
                           item_code="PLUMBING_CHECK")
    new_eligible_vendor(legal_name="Deny Plumbing", trade="PLUMBING", rating=4.0)

    response = api.dispatch_work_order(
        ctx["work_order_id"],
        {"window_start_at": "2026-06-03T09:00:00Z", "window_end_at": "2026-06-03T17:00:00Z"},
        ACCOUNT_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value)
    reread = refresh_work_order(ctx["work_order_id"])
    assert reread["status"] == "APPROVED"
    assert reread["dispatch_attempt_count"] == 0
    _, meta = validate_paginated(
        api.list_vendor_assignments(headers=AUDITOR,
                                    params={"work_order_id": ctx["work_order_id"]})
    )
    assert meta["total_count"] == 0


def test_a_second_vendor_cannot_accept_the_offer_addressed_to_the_first(api):
    """PRD 2.1: "When `X-User-Role` is `Vendor`, `X-User-ID` is the `id` of the acting
    `Vendor` row, and every assignment-scoped action compares
    `VendorAssignment.vendor_id` to `X-User-ID`; a mismatch is rejected with
    `ERR_NOT_ASSIGNED_VENDOR` (HTTP 403)."
    PRD 3.6: "The pool is ranked by `rating` descending, then by `hourly_rate_cents`
    ascending, then by `created_at` ascending; `created_at` ascending is the final
    tie-break and `id` is never consulted."

    Design: Corner/rbac/vendor_cannot_accept_another_vendors_assignment
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
                           description="Drip", item_codes=("PLUMBING_CHECK",),
                           item_code="PLUMBING_CHECK")
    top = new_eligible_vendor(legal_name="Top Plumbing", trade="PLUMBING", rating=4.8,
                              hourly_rate_cents=8500)
    other = new_eligible_vendor(legal_name="Other Plumbing", trade="PLUMBING", rating=3.9,
                                hourly_rate_cents=8000)
    new_key_asset(ctx["property_id"], key_type="LOCKBOX", label="Bid lockbox",
                  copies_total=3, current_code="1000")
    validate_success(api.dispatch_work_order(
        ctx["work_order_id"],
        {"window_start_at": "2026-06-03T09:00:00Z", "window_end_at": "2026-06-03T17:00:00Z"},
        DISPATCHER,
    ))
    assignment = assignment_for(ctx["work_order_id"])
    assert assignment["vendor_id"] == top["id"], "rating 4.8 outranks 3.9"

    response = api.accept_vendor_assignment(assignment["id"], {}, make_vendor_headers(other["id"]))
    assert response.status_code == 403, f"expected 403, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_NOT_ASSIGNED_VENDOR.value)
    reread = refresh_assignment(assignment["id"])
    assert reread["status"] == "OFFERED"
    assert reread["accepted_at"] is None


def test_suspension_after_acceptance_leaves_the_assignment_untouched(api):
    """PRD 3.6: "Suspension moves an `ELIGIBLE` vendor to `SUSPENDED` with no precondition,
    and it is deliberately **not retroactive**: assignments already `ACCEPTED` or
    `WORKING` are untouched and only new offers are blocked."

    Design: Corner/state_machines/vendor_suspend_does_not_retro_invalidate_accepted_assignment
    """
    ctx = setup_dispatched_work_order(
        plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
        description="Slow drain", item_codes=("PLUMBING_CHECK",), item_code="PLUMBING_CHECK",
        vendor_overrides={"legal_name": "Steady Plumbing", "trade": "PLUMBING", "rating": 4.1},
        key_asset_overrides={"key_type": "LOCKBOX", "label": "Hold lockbox",
                             "copies_total": 2, "current_code": "2000"},
    )
    validate_success(api.accept_vendor_assignment(ctx["assignment_id"], {},
                                                  ctx["vendor_headers"]))
    suspended = validate_success(api.suspend_vendor(ctx["vendor_id"], {}, DISPATCHER))

    assert suspended["status"] == "SUSPENDED"
    assignment = refresh_assignment(ctx["assignment_id"])
    assert assignment["status"] == "ACCEPTED"
    assert assignment["coi_valid_at_offer"] is True
    assert refresh_work_order(ctx["work_order_id"])["status"] == "DISPATCHED"


def test_a_suspended_vendor_cannot_accept_its_outstanding_offer(api):
    """PRD 3.6: "A vendor accepts an offer, which requires the vendor's `status` to be
    `ELIGIBLE`, requires that the vendor holds no key issuance in status `OVERDUE` or
    `LOST`, and requires that the window does not overlap another assignment of the same
    vendor."
    PRD 2.8: "The selected or targeted vendor has status `ELIGIBLE`. This applies to
    work-order dispatch and to assignment acceptance. Otherwise
    `ERR_VENDOR_NOT_ELIGIBLE`, HTTP 409."

    Design: Corner/errors/err_vendor_not_eligible_when_accepting_after_suspension_returns_409
    """
    ctx = setup_dispatched_work_order(
        plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
        description="Slow drain", item_codes=("PLUMBING_CHECK",), item_code="PLUMBING_CHECK",
        vendor_overrides={"legal_name": "Halted Plumbing", "trade": "PLUMBING", "rating": 4.2},
        key_asset_overrides={"key_type": "LOCKBOX", "label": "Halt lockbox",
                             "copies_total": 2, "current_code": "3000"},
    )
    validate_success(api.suspend_vendor(ctx["vendor_id"], {}, DISPATCHER))

    response = api.accept_vendor_assignment(ctx["assignment_id"], {}, ctx["vendor_headers"])
    validate_error(response, ApiErrorId.ERR_VENDOR_NOT_ELIGIBLE.value)
    assert refresh_vendor(ctx["vendor_id"])["status"] == "SUSPENDED"
    assignment = refresh_assignment(ctx["assignment_id"])
    assert assignment["status"] == "OFFERED"
    assert assignment["accepted_at"] is None
    reread = refresh_work_order(ctx["work_order_id"])
    assert reread["status"] == "DISPATCHED"
    assert reread["dispatch_attempt_count"] == 1


def test_three_declines_exhaust_the_dispatch_attempts(api):
    """PRD 3.6: "A vendor declines an offer with an optional `decline_reason`, and the
    decline has three consequences beyond recording the reason: the parent work order
    returns from `DISPATCHED` to `APPROVED` so it can be re-dispatched, with
    `dispatch_attempt_count` deliberately **not** decremented"
    PRD 2.8: "A work order being dispatched has a `dispatch_attempt_count` strictly less
    than three. Otherwise `ERR_DISPATCH_ATTEMPTS_EXHAUSTED`, HTTP 409."

    Design: Corner/errors/err_dispatch_attempts_exhausted_after_three_declines_returns_409
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
                           description="Slow drain", item_codes=("PLUMBING_CHECK",),
                           item_code="PLUMBING_CHECK")
    ranked = [
        new_eligible_vendor(legal_name="First Plumbing", trade="PLUMBING", rating=4.8,
                            hourly_rate_cents=8500),
        new_eligible_vendor(legal_name="Second Plumbing", trade="PLUMBING", rating=4.5,
                            hourly_rate_cents=8500),
        new_eligible_vendor(legal_name="Third Plumbing", trade="PLUMBING", rating=4.2,
                            hourly_rate_cents=8500),
    ]
    new_key_asset(ctx["property_id"], key_type="LOCKBOX", label="Retry lockbox",
                  copies_total=3, current_code="4000")

    for index, vendor in enumerate(ranked, start=1):
        validate_success(api.dispatch_work_order(
            ctx["work_order_id"],
            {"window_start_at": "2026-06-03T09:00:00Z", "window_end_at": "2026-06-03T17:00:00Z"},
            DISPATCHER,
        ))
        assignment = assignment_for(ctx["work_order_id"], vendor["id"])
        assert assignment["status"] == "OFFERED", (
            f"offer {index} must go to the vendor ranked {index} by rating descending"
        )
        validate_success(api.decline_vendor_assignment(
            assignment["id"], {"decline_reason": "Fully booked"},
            make_vendor_headers(vendor["id"]),
        ))
        assert refresh_work_order(ctx["work_order_id"])["status"] == "APPROVED"

    reread = refresh_work_order(ctx["work_order_id"])
    assert reread["dispatch_attempt_count"] == 3

    response = api.dispatch_work_order(
        ctx["work_order_id"],
        {"window_start_at": "2026-06-04T09:00:00Z", "window_end_at": "2026-06-04T17:00:00Z"},
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_DISPATCH_ATTEMPTS_EXHAUSTED.value)
    rows, meta = validate_paginated(
        api.list_vendor_assignments(headers=AUDITOR,
                                    params={"work_order_id": ctx["work_order_id"]})
    )
    assert meta["total_count"] == 3
    assert all(row["status"] == "DECLINED" for row in rows)


# --------------------------------------------------------------------------
# The candidate pool
# --------------------------------------------------------------------------

def test_dispatch_fails_when_the_only_vendor_has_lapsed(api):
    """PRD 3.6: "An eligibility refresh drops an `ELIGIBLE` vendor to `LAPSED` when either
    `coi_expires_at` or `license_expires_at` is at or before the logical clock, stamping
    `last_eligibility_evaluated_at` and leaving completed work untouched."
    PRD 3.6: "When the pool comes out empty no assignment is created,
    `dispatch_attempt_count` is **not** incremented, the work order stays `APPROVED`, and
    the request fails with `ERR_NO_ELIGIBLE_VENDOR`, HTTP 409."

    Design: Difficulty/cross_entity_state_dependency/dispatch_rejected_when_only_vendor_has_lapsed_credentials
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
                           description="Dripping valve", item_codes=("PLUMBING_CHECK",),
                           item_code="PLUMBING_CHECK")
    vendor = new_eligible_vendor(legal_name="Bayfront Plumbing", trade="PLUMBING", rating=4.0,
                                 coi_expires_at="2026-06-10T00:00:00Z",
                                 license_expires_at="2027-01-01T00:00:00Z")
    set_clock("2026-06-11T00:00:00Z")
    refreshed = validate_success(api.refresh_eligibility_vendor(vendor["id"], {}, DISPATCHER))
    assert refreshed["status"] == "LAPSED"

    response = api.dispatch_work_order(
        ctx["work_order_id"],
        {"window_start_at": "2026-06-11T09:00:00Z", "window_end_at": "2026-06-11T17:00:00Z"},
        DISPATCHER,
    )
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VENDOR.value)
    reread = refresh_work_order(ctx["work_order_id"])
    assert reread["status"] == "APPROVED"
    assert reread["dispatch_attempt_count"] == 0
    _, meta = validate_paginated(
        api.list_vendor_assignments(headers=AUDITOR,
                                    params={"work_order_id": ctx["work_order_id"]})
    )
    assert meta["total_count"] == 0


def test_dispatch_fails_when_no_vendor_holds_the_required_trade(api):
    """PRD 3.6: "The required trade is derived from the finding's `category` by a fixed
    map: `PLUMBING` needs a `PLUMBING` vendor, `HVAC` needs `HVAC`, `ELECTRICAL` needs
    `ELECTRICAL`, `SECURITY` needs `SECURITY`, `LANDSCAPE` needs `LANDSCAPE`, and each of
    `STRUCTURAL`, `PEST` and `OTHER` needs a `GENERAL` vendor."
    PRD 3.6: "The candidate pool is every vendor whose `status` is `ELIGIBLE`, whose
    `trade` equals the required trade, whose `coi_expires_at` and `license_expires_at` are
    both strictly after the logical clock, whose `rating` is at least 3.0 compared at one
    decimal place"

    Design: Difficulty/cross_entity_state_dependency/dispatch_rejected_when_only_vendor_has_lapsed_credentials
    """
    ctx = setup_work_order(plan_overrides=STANDARD, severity="MEDIUM", category="PLUMBING",
                           description="Dripping valve", item_codes=("PLUMBING_CHECK",),
                           item_code="PLUMBING_CHECK")
    hvac = new_eligible_vendor(legal_name="Cool Air HVAC", trade="HVAC", rating=4.9)
    assert hvac["status"] == "ELIGIBLE"

    response = api.dispatch_work_order(
        ctx["work_order_id"],
        {"window_start_at": "2026-06-03T09:00:00Z", "window_end_at": "2026-06-03T17:00:00Z"},
        DISPATCHER,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_VENDOR.value)
    reread = refresh_work_order(ctx["work_order_id"])
    assert reread["status"] == "APPROVED"
    assert reread["dispatch_attempt_count"] == 0


# --------------------------------------------------------------------------
# The vendor's own closed-interval occupancy
# --------------------------------------------------------------------------

def _two_work_orders_on_one_property():
    ctx = setup_completed_visit(
        plan_overrides=STANDARD,
        property_overrides={"label": "Double Booking Bungalow", "address_line": "48 Window Way",
                            "travel_distance_miles": 18.0},
        item_codes=("EXT_WALK", "INT_WALK"), critical_item_codes=(),
    )
    from test_helpers import create_work_order, record_finding, triage_finding
    work_orders = []
    for item_code, description in (("EXT_WALK", "Hose bib drip"), ("INT_WALK", "Sink trap seep")):
        finding = triage_finding(record_finding(
            ctx["visit_id"], item_code=item_code, severity="MEDIUM", category="PLUMBING",
            description=description)["id"])
        work_orders.append(create_work_order(finding["id"], finding["version"],
                                             estimated_labour_hours=2.0,
                                             estimated_parts_cents=5000))
    return ctx, work_orders


def test_touching_assignment_windows_conflict_for_one_vendor(api):
    """PRD 3.6: "That overlap test is a **closed-interval exclusive occupancy check with no
    buffer and a capacity of exactly one**: a conflict exists when some other assignment
    of the same vendor, in status `ACCEPTED` or `WORKING`, has a `window_start_at` at or
    before this assignment's `window_end_at` and a `window_start_at` of this assignment at
    or before that other assignment's `window_end_at`."
    PRD 3.6: "A conflict is rejected with `ERR_VENDOR_WINDOW_CONFLICT`. Acceptance stamps
    `accepted_at`."

    Design: Difficulty/resource_temporal_overlap/vendor_assignment_closed_interval_exclusive_occupancy_conflict
    """
    ctx, work_orders = _two_work_orders_on_one_property()
    vendor = new_eligible_vendor(legal_name="Tide Plumbing", trade="PLUMBING", rating=4.0,
                                 hourly_rate_cents=8500)
    new_key_asset(ctx["property_id"], key_type="PHYSICAL", label="Front key", copies_total=4)
    set_clock("2026-06-10T08:00:00Z")
    validate_success(api.dispatch_work_order(
        work_orders[0]["id"],
        {"window_start_at": "2026-06-11T09:00:00Z", "window_end_at": "2026-06-11T12:00:00Z"},
        DISPATCHER,
    ))
    validate_success(api.dispatch_work_order(
        work_orders[1]["id"],
        {"window_start_at": "2026-06-11T12:00:00Z", "window_end_at": "2026-06-11T15:00:00Z"},
        DISPATCHER,
    ))
    first = assignment_for(work_orders[0]["id"], vendor["id"])
    second = assignment_for(work_orders[1]["id"], vendor["id"])
    headers = make_vendor_headers(vendor["id"])
    validate_success(api.accept_vendor_assignment(first["id"], {}, headers))

    response = api.accept_vendor_assignment(second["id"], {}, headers)
    assert response.status_code == 409, f"expected 409, got {response.status_code}"
    validate_error(response, ApiErrorId.ERR_VENDOR_WINDOW_CONFLICT.value)
    assert refresh_assignment(first["id"])["status"] == "ACCEPTED"
    reread_second = refresh_assignment(second["id"])
    assert reread_second["status"] == "OFFERED"
    assert reread_second["accepted_at"] is None
    assert refresh_work_order(work_orders[1]["id"])["status"] == "DISPATCHED"


def test_assignment_windows_that_do_not_touch_are_both_acceptable(api):
    """PRD 3.6: "A vendor accepts an offer, which requires the vendor's `status` to be
    `ELIGIBLE`, requires that the vendor holds no key issuance in status `OVERDUE` or
    `LOST`, and requires that the window does not overlap another assignment of the same
    vendor."
    PRD 3.6: "A conflict is rejected with `ERR_VENDOR_WINDOW_CONFLICT`. Acceptance stamps
    `accepted_at`."

    Design: Difficulty/resource_temporal_overlap/vendor_assignment_closed_interval_exclusive_occupancy_conflict
    """
    ctx, work_orders = _two_work_orders_on_one_property()
    vendor = new_eligible_vendor(legal_name="Slack Plumbing", trade="PLUMBING", rating=4.0,
                                 hourly_rate_cents=8500)
    new_key_asset(ctx["property_id"], key_type="PHYSICAL", label="Front key", copies_total=4)
    set_clock("2026-06-10T08:00:00Z")
    validate_success(api.dispatch_work_order(
        work_orders[0]["id"],
        {"window_start_at": "2026-06-11T09:00:00Z", "window_end_at": "2026-06-11T12:00:00Z"},
        DISPATCHER,
    ))
    validate_success(api.dispatch_work_order(
        work_orders[1]["id"],
        {"window_start_at": "2026-06-11T12:00:01Z", "window_end_at": "2026-06-11T15:00:00Z"},
        DISPATCHER,
    ))
    first = assignment_for(work_orders[0]["id"], vendor["id"])
    second = assignment_for(work_orders[1]["id"], vendor["id"])
    headers = make_vendor_headers(vendor["id"])

    validate_success(api.accept_vendor_assignment(first["id"], {}, headers))
    accepted = validate_success(api.accept_vendor_assignment(second["id"], {}, headers))
    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_at"] is not None
    assert refresh_assignment(first["id"])["status"] == "ACCEPTED"
