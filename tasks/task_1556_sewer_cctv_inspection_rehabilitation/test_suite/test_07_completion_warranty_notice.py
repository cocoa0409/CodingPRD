"""Completion cascade, lateral reinstatement invariant, warranty lifecycle, notices."""
from test_helpers import (
    ApiErrorId,
    complete_work_order,
    get_district,
    get_plan,
    get_segment,
    set_clock,
    setup_cipp_ready_to_complete,
    setup_completed_spot_repair,
    setup_notice_ctx,
    open_warranty_case,
    drive_reinspection_to_certified,
    validate_error,
    validate_paginated,
    validate_success,
    get_success_data,
    TEST_USERS,
)

ENGINEER = TEST_USERS["engineer_headers"]
CSR = TEST_USERS["csr_headers"]


def _list_laterals(api, segment_id):
    data, _ = validate_paginated(api.list_laterals(segment_id, ENGINEER))
    return data


def test_work_order_complete_depth3_cascade_states(api):
    """PRD §3.7: "When the finishing work order is the plan's last non-cancelled one,
    the plan completes automatically, `EXECUTING` → `COMPLETED`, and the cascade runs
    to the top: the district's `budget_committed_cents` releases the plan's
    provisional commitment, the segment's `rehab_status` becomes `REHABILITATED`, its
    `last_rehab_completed_at` is stamped, and — for lining plans — the lateral reset
    described above fires."

    Design: Difficulty/transitive_cascade/work_order_complete_depth3_cascade
    """
    ctx = setup_cipp_ready_to_complete()
    completed = complete_work_order(ctx["work_order"]["id"], ctx["crew"]["id"])
    assert completed["execution_status"] == "COMPLETED", "hop 1: work order"
    assert get_plan(ctx["plan"]["id"])["status"] == "COMPLETED", "hop 2: plan bubbles up"
    segment = get_segment(ctx["segment"]["id"])
    assert segment["rehab_status"] == "REHABILITATED", "hop 3: segment"
    assert segment["last_rehab_completed_at"] is not None


def test_work_order_complete_depth3_cascade_ledger_and_laterals(api):
    """PRD §3.7: "When the finishing work order is the plan's last non-cancelled one,
    the plan completes automatically, `EXECUTING` → `COMPLETED`, and the cascade runs
    to the top: the district's `budget_committed_cents` releases the plan's
    provisional commitment, the segment's `rehab_status` becomes `REHABILITATED`, its
    `last_rehab_completed_at` is stamped, and — for lining plans — the lateral reset
    described above fires."
    The provisional commitment was 100 x 8000 + 150000 (MOB_SMALL) = 950000; after
    completion the ledger releases it back to 0, and every active lateral's
    `reinstated` flag is reset to false.

    Design: Difficulty/transitive_cascade/work_order_complete_depth3_cascade
    """
    ctx = setup_cipp_ready_to_complete()
    assert get_district(ctx["district"]["id"])["budget_committed_cents"] == 950000
    complete_work_order(ctx["work_order"]["id"], ctx["crew"]["id"])
    assert get_district(ctx["district"]["id"])["budget_committed_cents"] == 0
    laterals = _list_laterals(api, ctx["segment"]["id"])
    assert len(laterals) == 2
    assert all(lat["reinstated"] is False for lat in laterals), (
        "hop 4: CIPP completion resets reinstatement tracking"
    )


def test_lateral_reinstatement_marks_before_completion(api):
    """PRD §3.7: "Reinstatement is recorded one lateral at a time by the `CrewLead`.
    Each reinstatement flips the lateral's `reinstated` to true, increments the
    lateral's `version`, and recomputes the segment's reinstatement progress across
    the active-lateral set."
    Before completion both active laterals carry reinstated == true (tally 2).

    Design: Difficulty/compensating_invariant/lateral_reinstatement_count_invariant_on_cipp_cycle
    """
    ctx = setup_cipp_ready_to_complete()
    laterals = _list_laterals(api, ctx["segment"]["id"])
    assert len(laterals) == 2
    assert all(lat["reinstated"] is True for lat in laterals)
    completed = complete_work_order(ctx["work_order"]["id"], ctx["crew"]["id"])
    assert completed["execution_status"] == "COMPLETED"


def test_lateral_reinstatement_tally_returns_to_zero_on_completion(api):
    """PRD §3.7: "Note the reset semantics that make this meaningful: completing a
    lining work order first sets every active lateral's `reinstated` back to false,
    and reinstatement recordings from that point flip them true again — the flags
    always describe the most recent lining job."
    The completion compensates every reinstatement mark: the active-lateral
    reinstated tally returns to 0 across the CIPP cycle.

    Design: Difficulty/compensating_invariant/lateral_reinstatement_count_invariant_on_cipp_cycle
    """
    ctx = setup_cipp_ready_to_complete()
    complete_work_order(ctx["work_order"]["id"], ctx["crew"]["id"])
    laterals = _list_laterals(api, ctx["segment"]["id"])
    assert sum(1 for lat in laterals if lat["reinstated"]) == 0


def _setup_resolved_warranty_case(api):
    """Completed SPOT_REPAIR work order (warranty 12 months from 2026-08-10), then a
    warranty case driven OPENED -> RE_INSPECTION -> UNDER_REPAIR -> RESOLVED with a
    certified grade-5 re-inspection. Clock sits at 2026-09-01, inside the window."""
    ctx = setup_completed_spot_repair(cert_kwargs={
        "district_overrides": {"warranty_months": 12},
        "cycle_end": "2026-12-01T00:00:00Z",
        "cert_expires_at": "2027-06-01T00:00:00Z",
    })
    case = open_warranty_case(ctx, clock="2026-09-01T00:00:00Z",
                              scheduled_at="2026-09-02T08:00:00Z",
                              defect_summary="blister at repair")
    drive_reinspection_to_certified(case, ctx["coder"]["id"], ctx["qa"]["id"],
                                    [{"pacp_code": "B", "family": "STRUCTURAL", "grade": 5,
                                      "distance_m": 30, "clock_position": 12}])
    validate_success(api.authorize_repair(case["id"], ENGINEER), 200)
    resolved = validate_success(
        api.resolve_warranty_case(case["id"], {"resolution_note": "repaired under warranty"}, ENGINEER),
        200,
    )
    return ctx, case, resolved


def test_warranty_case_reaches_resolved_before_reopen(api):
    """PRD §3.8: "Authorizing repair — `RE_INSPECTION` → `UNDER_REPAIR` — requires
    the linked re-inspection to be `CERTIFIED` with a `structural_grade` of at least
    4 on the segment; anything less is `ERR_DEFECT_UNCONFIRMED`."
    PRD §3.8: "Resolving a repaired claim — `UNDER_REPAIR` → `RESOLVED` — likewise
    requires a `resolution_note`."

    Design: Difficulty/non_linear_state_machine/warranty_case_reopen_cycle_within_window
    """
    _, _, resolved = _setup_resolved_warranty_case(api)
    assert resolved["status"] == "RESOLVED"


def test_warranty_case_reopen_cycle_within_window(api):
    """PRD §3.8: "A resolved claim can recur: reopening moves `RESOLVED` → `OPENED`
    and is permitted only while the logical clock is at or before the referenced work
    order's `warranty_expires_at` (`ERR_WARRANTY_EXPIRED`)."
    The clock (2026-09-01) is before the warranty expiry (2026-08-10 completion +
    12 months), so the cyclic reopen is legal.

    Design: Difficulty/non_linear_state_machine/warranty_case_reopen_cycle_within_window
    """
    _, case, _ = _setup_resolved_warranty_case(api)
    reopened = validate_success(api.reopen_warranty_case(case["id"], ENGINEER), 200)
    assert reopened["status"] == "OPENED"


def test_warranty_claim_after_expiry_rejected(api):
    """PRD §3.8: "The case's `opened_at` is stamped from the logical clock and must
    be at or before the referenced work order's `warranty_expires_at`; a claim filed
    after the warranty window closes is rejected with `ERR_WARRANTY_EXPIRED`."
    PRD §3.7: "Completion stamps `completed_at` from the logical clock and derives
    `warranty_expires_at` as `completed_at` plus the district's `warranty_months`."
    Completion was stamped 2026-08-10 and warranty_months is 12, so a claim opened
    one second after 2027-08-10T00:00:00Z is too late.

    Design: Corner/validations/warranty_claim_after_expiry_rejected
    """
    ctx = setup_completed_spot_repair(cert_kwargs={
        "district_overrides": {"warranty_months": 12},
        "cycle_end": "2027-12-01T00:00:00Z",
        "cert_expires_at": "2028-01-01T00:00:00Z",
    })
    set_clock("2027-08-10T00:00:01Z")
    resp = api.create_warranty_case(
        ctx["segment"]["id"],
        {"work_order_id": ctx["work_order"]["id"], "defect_summary": "late claim",
         "cycle_id": ctx["cycle"]["id"], "scheduled_at": "2027-08-11T08:00:00Z",
         "coder_id": ctx["coder"]["id"]},
        ENGINEER,
    )
    validate_error(resp, ApiErrorId.ERR_WARRANTY_EXPIRED)


def test_notice_expiry_sweep_on_clock_advance(api):
    """PRD §2.4: "Setting the clock also runs the customer-notice expiry sweep across
    every district: any notice still in `QUEUED` status whose `event_start` has been
    reached by the new clock transitions to `EXPIRED`."

    Design: Corner/state_machines/notice_expiry_sweep_on_clock_advance
    """
    ctx = setup_notice_ctx(event_start="2026-08-15T00:00:00Z", address="5 Elm St",
                           channel="DOOR_HANGER")
    assert ctx["notice"]["status"] == "QUEUED"
    set_clock("2026-08-15T00:00:01Z")
    notice = get_success_data(api.get_customer_notice(ctx["notice"]["id"], CSR))
    assert notice["status"] == "EXPIRED"


def test_notice_send_inside_lead_window_rejected(api):
    """PRD §3.6: "Sending enforces the district's lead time: the send must occur no
    later than `event_start` minus the district's `notice_lead_hours` — with the
    default 48-hour lead, a notice for a 09:00 Monday event must go out by 09:00 the
    previous Saturday — and a late send is rejected with `ERR_NOTICE_LEAD_VIOLATION`."
    At 2026-08-12T00:01:00Z only 47h59m remain before the 2026-08-14T00:00:00Z event.

    Design: Corner/validations/notice_send_inside_lead_window_rejected
    """
    ctx = setup_notice_ctx(event_start="2026-08-14T00:00:00Z", address="7 Elm St",
                           channel="SMS", notice_lead_hours=48)
    set_clock("2026-08-12T00:01:00Z")
    resp = api.send_notice(ctx["notice"]["id"], CSR)
    validate_error(resp, ApiErrorId.ERR_NOTICE_LEAD_VIOLATION)
    notice = get_success_data(api.get_customer_notice(ctx["notice"]["id"], CSR))
    assert notice["status"] == "QUEUED"


def test_temporal_notice_lead_exactly_at_boundary_send_ok(api):
    """PRD §3.6: "Sending enforces the district's lead time: the send must occur no
    later than `event_start` minus the district's `notice_lead_hours` — with the
    default 48-hour lead, a notice for a 09:00 Monday event must go out by 09:00 the
    previous Saturday — and a late send is rejected with `ERR_NOTICE_LEAD_VIOLATION`."
    PRD §3.6: "A successful send stamps `sent_at` and moves the notice to `SENT`"
    "No later than" is inclusive: sending at exactly event_start - 48h succeeds.

    Design: Corner/cross_cutting_layers/temporal_notice_lead_exactly_at_boundary_send_ok
    """
    ctx = setup_notice_ctx(event_start="2026-08-14T00:00:00Z", address="11 Elm St",
                           channel="EMAIL", notice_lead_hours=48)
    set_clock("2026-08-12T00:00:00Z")  # exactly event_start - 48h
    data = validate_success(api.send_notice(ctx["notice"]["id"], CSR), 200)
    assert data["status"] == "SENT"
    assert isinstance(data["sent_at"], str)
    assert data["sent_at"].startswith("2026-08-12T00:00:00"), (
        "sent_at is stamped from the logical clock"
    )
