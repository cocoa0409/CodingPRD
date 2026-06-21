"""Deferment lifecycle (ACTIVE <-> DEFERRED cycle), eligibility, temporal
overlaps for income reports and deferment windows, and settlement blocked while
deferred.

Translates difficulty `non_linear_state_machine` (cycle),
`cross_entity_state_dependency` (settle blocked), `resource_temporal_overlap`,
and corner `validations` (deferment eligibility) instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_income_report_payload,
    create_deferment_request_payload,
    setup_graduated_isa,
    setup_deferred_isa,
    file_income_report,
)

SERVICING = TEST_USERS["servicing_officer_headers"]


def test_isa_active_deferred_active_cycle():
    """PRD §3.10: "On approval the request moves `REQUESTED → APPROVED` and the contract cascades `ACTIVE → DEFERRED`, after which no new payment obligation accrues for periods inside the window and the term clock effectively pauses."
    PRD §3.10: "Ending an approved deferment moves the request `APPROVED → ENDED` and requires the contract to be `DEFERRED`; it cascades the contract `DEFERRED → ACTIVE`, resuming payment obligations for periods after the window."

    Design: Difficulty/non_linear_state_machine/isa_active_deferred_active_cycle
    """
    _, _, enrollment, isa = setup_graduated_isa(email="cycle@example.com")
    isa_id = isa["id"]
    # Latest report UNEMPLOYED -> UNEMPLOYMENT deferment eligible.
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 0, "UNEMPLOYED")
    dr = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        SERVICING))
    get_success_data(api_client.approve_deferment_request(dr["id"], SERVICING))
    deferred = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert deferred["status"] == "DEFERRED"
    # End the deferment -> contract returns to ACTIVE.
    ended = validate_success(api_client.end_deferment_request(dr["id"], SERVICING), 200)
    assert ended["status"] == "ENDED"
    active = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert active["status"] == "ACTIVE", "DEFERRED -> ACTIVE return leg"


def test_deferred_contract_blocks_new_obligation_zero():
    """PRD §3.8: "If the contract is currently `DEFERRED`, the obligation is zero — no obligation accrues while deferred."
    PRD §3.10: "On approval the request moves `REQUESTED → APPROVED` and the contract cascades `ACTIVE → DEFERRED`, after which no new payment obligation accrues for periods inside the window and the term clock effectively pauses."

    Design: Difficulty/non_linear_state_machine/isa_active_deferred_active_cycle
    """
    _, _, enrollment, isa = setup_graduated_isa(email="defzero@example.com")
    isa_id = isa["id"]
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 0, "UNEMPLOYED")
    dr = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        SERVICING))
    get_success_data(api_client.approve_deferment_request(dr["id"], SERVICING))
    deferred = get_success_data(api_client.get_isa_contract(isa_id, SERVICING))
    assert deferred["status"] == "DEFERRED"
    # A new income report while DEFERRED owes zero even though income is over threshold.
    report = validate_success(api_client.create_income_report(
        create_income_report_payload(isa_id, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", 600_000, "EMPLOYED"),
        SERVICING), 201)
    assert report["obligation_cents"] == 0, "no obligation accrues while the contract is DEFERRED"


def test_deferment_ineligible_when_latest_income_employed():
    """PRD §3.10: "an `UNEMPLOYMENT` deferment requires that the most recent IncomeReport has `employment_status` equal to `UNEMPLOYED`, and an `INCOME_FLOOR` deferment requires that the most recent report's `gross_income_cents` is at or below the contract's `income_threshold_cents`; a reason the latest report does not support is rejected with `ERR_DEFERMENT_INELIGIBLE`."

    Design: Corner/validations/deferment_ineligible_when_latest_income_employed
    """
    _, _, enrollment, isa = setup_graduated_isa(email="inelig@example.com")
    isa_id = isa["id"]
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 600_000, "EMPLOYED")
    dr = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        SERVICING))
    resp = api_client.approve_deferment_request(dr["id"], SERVICING)
    validate_error(resp, ApiErrorId.ERR_DEFERMENT_INELIGIBLE.value)


def test_payment_settle_blocked_while_contract_deferred():
    """PRD §3.9: "Settling a payment moves its `collection_status` from `PENDING` to `SETTLED`, but only when the linked ISA contract is `ACTIVE` — a `DEFERRED` contract blocks settlement, and an attempt against a contract not in `ACTIVE` is an `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/payment_settle_blocked_while_contract_deferred
    """
    isa, pay_id, dr_id = setup_deferred_isa(email="blocked@example.com")
    assert isa["status"] == "DEFERRED"
    resp = api_client.settle_payment(pay_id, SERVICING)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    pay = get_success_data(api_client.get_payment(pay_id, SERVICING))
    assert pay["collection_status"] == "PENDING", "payment unchanged while contract deferred"


def test_payment_settle_resumes_after_deferment_ends():
    """PRD §3.9: "Settling a payment moves its `collection_status` from `PENDING` to `SETTLED`, but only when the linked ISA contract is `ACTIVE` — a `DEFERRED` contract blocks settlement, and an attempt against a contract not in `ACTIVE` is an `ERR_INVALID_STATE`."
    PRD §3.10: "Ending an approved deferment moves the request `APPROVED → ENDED` and requires the contract to be `DEFERRED`; it cascades the contract `DEFERRED → ACTIVE`, resuming payment obligations for periods after the window."

    Design: Difficulty/cross_entity_state_dependency/payment_settle_blocked_while_contract_deferred
    """
    isa, pay_id, dr_id = setup_deferred_isa(email="resume@example.com")
    assert isa["status"] == "DEFERRED"
    # End the deferment -> contract ACTIVE -> the same PENDING payment now settles.
    get_success_data(api_client.end_deferment_request(dr_id, SERVICING))
    active = get_success_data(api_client.get_isa_contract(isa["id"], SERVICING))
    assert active["status"] == "ACTIVE"
    settled = validate_success(api_client.settle_payment(pay_id, SERVICING), 200)
    assert settled["collection_status"] == "SETTLED"


def test_income_report_periods_half_open_overlap_rejected():
    """PRD §3.8: "A report's monthly period may not overlap an existing report for the same contract; an overlapping half-open period is rejected with `ERR_INCOME_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/income_report_periods_half_open_overlap_rejected
    """
    _, _, enrollment, isa = setup_graduated_isa(email="overlap@example.com")
    isa_id = isa["id"]
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 300_000, "EMPLOYED")
    # [2026-06-15, 2026-07-15) overlaps [2026-06-01, 2026-07-01).
    resp = api_client.create_income_report(
        create_income_report_payload(isa_id, "2026-06-15T00:00:00Z", "2026-07-15T00:00:00Z", 300_000),
        SERVICING,
    )
    validate_error(resp, ApiErrorId.ERR_INCOME_PERIOD_OVERLAP.value)


def test_income_report_adjacent_half_open_period_allowed():
    """PRD §3.8: "a `period_end` (the first day of the following month, exclusive — so the period is the half-open interval from start up to but not including end), a verified `gross_income_cents` of zero or more, and an `employment_status` of `EMPLOYED`, `UNEMPLOYED`, or `UNDEREMPLOYED`."
    PRD §3.8: "A report's monthly period may not overlap an existing report for the same contract; an overlapping half-open period is rejected with `ERR_INCOME_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/income_report_periods_half_open_overlap_rejected
    """
    _, _, enrollment, isa = setup_graduated_isa(email="adjacent@example.com")
    isa_id = isa["id"]
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 300_000, "EMPLOYED")
    # A report starting exactly at the prior period_end does NOT overlap (half-open).
    resp = api_client.create_income_report(
        create_income_report_payload(isa_id, "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 300_000),
        SERVICING,
    )
    validate_success(resp, 201)


def test_deferment_windows_closed_with_buffer_overlap_rejected():
    """PRD §3.10: "the requested window must not overlap any prior deferment window for the same contract that was ever approved — whether it is still `APPROVED` or has since `ENDED` — and the overlap test treats the intervals as closed and includes a one-day buffer on each side, so a span stays reserved even after it ends; a colliding window is rejected with `ERR_DEFERMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/deferment_windows_closed_with_buffer_overlap_rejected
    """
    _, _, enrollment, isa = setup_graduated_isa(email="defoverlap@example.com")
    isa_id = isa["id"]
    # First UNEMPLOYMENT deferment [2026-07-01, 2026-09-30], approved then ended.
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 0, "UNEMPLOYED")
    dr1 = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        SERVICING))
    get_success_data(api_client.approve_deferment_request(dr1["id"], SERVICING))
    get_success_data(api_client.end_deferment_request(dr1["id"], SERVICING))
    # New latest report still UNEMPLOYED so eligibility passes; second window
    # [2026-10-01, 2026-12-31] abuts the ENDED window within the 1-day buffer.
    file_income_report(isa_id, "2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z", 0, "UNEMPLOYED")
    dr2 = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-10-01T00:00:00Z", "2026-12-31T00:00:00Z"),
        SERVICING))
    resp = api_client.approve_deferment_request(dr2["id"], SERVICING)
    validate_error(resp, ApiErrorId.ERR_DEFERMENT_OVERLAP.value)


def test_deferment_window_directly_overlapping_prior_approved_rejected():
    """PRD §3.10: "the requested window must not overlap any prior deferment window for the same contract that was ever approved — whether it is still `APPROVED` or has since `ENDED` — and the overlap test treats the intervals as closed and includes a one-day buffer on each side, so a span stays reserved even after it ends; a colliding window is rejected with `ERR_DEFERMENT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/deferment_windows_closed_with_buffer_overlap_rejected
    """
    _, _, enrollment, isa = setup_graduated_isa(email="defdirect@example.com")
    isa_id = isa["id"]
    file_income_report(isa_id, "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 0, "UNEMPLOYED")
    dr1 = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-07-01T00:00:00Z", "2026-09-30T00:00:00Z"),
        SERVICING))
    get_success_data(api_client.approve_deferment_request(dr1["id"], SERVICING))
    # End dr1 so the contract returns to ACTIVE (PRD §3.10 requires the contract
    # be ACTIVE to approve a deferment, and that ACTIVE check is evaluated before
    # the overlap check). The dr1 window stays reserved while ENDED per PRD.
    get_success_data(api_client.end_deferment_request(dr1["id"], SERVICING))
    # A second window strictly inside the now-ENDED first window directly overlaps.
    dr2 = get_success_data(api_client.create_deferment_request(
        create_deferment_request_payload(isa_id, "UNEMPLOYMENT", "2026-08-01T00:00:00Z", "2026-08-31T00:00:00Z"),
        SERVICING))
    resp = api_client.approve_deferment_request(dr2["id"], SERVICING)
    validate_error(resp, ApiErrorId.ERR_DEFERMENT_OVERLAP.value)
