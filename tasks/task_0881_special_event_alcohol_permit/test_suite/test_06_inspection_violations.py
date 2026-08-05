"""Field inspections, the failure cascade, violation fines, and the buffer rule.

Difficulty: transitive_cascade, dual_variant_calc (fine), compensating_invariant,
resource_temporal_overlap (inspector buffer).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, find_ledger_entry,
    create_violation_payload, create_inspection_payload, fixtures,
)
from test_helpers.test_users import TEST_USERS, make_inspector_headers

APPLICANT = TEST_USERS["applicant_headers"]
CLERK = TEST_USERS["clerk_headers"]


def _approved_paid_with_inspection(api):
    """APPROVED application, full balance (incl. deposit) paid, inspection SCHEDULED."""
    ctx = fixtures.drive_to_approved_with_inspection(api)
    app_id = ctx["application"]["id"]
    balance = fixtures.get_application(api, app_id)["balance_due_cents"]
    fixtures.pay_balance(api, app_id, balance)
    return ctx


def test_failed_inspection_revokes_application_and_forfeits_deposit(api):
    """PRD §2.8: "When a scheduled inspection is recorded as failed and its parent
    application is `APPROVED`, the application cascades to `REVOKED`: the system forfeits
    the held or paid portion of the deposit by appending a `DEPOSIT_FORFEIT` ledger entry
    for the smaller of `deposit_cents` and the amount of deposit actually paid, sets
    `deposit_status` to `FORFEITED`, and recomputes `balance_due_cents` from the new
    ledger total."

    Design: Difficulty/transitive_cascade/inspection_fail_revokes_and_forfeits
    """
    ctx = _approved_paid_with_inspection(api)
    fixtures.record_inspection(api, ctx["inspection"]["id"], ctx["inspector_id"], "FAILED")
    app = fixtures.get_application(api, ctx["application"]["id"])
    assert app["status"] == "REVOKED"
    assert app["deposit_status"] == "FORFEITED"


def test_failed_inspection_posts_deposit_forfeit_entry(api):
    """PRD §3.6: "A `FAILED` result advances the inspection to `FAILED` and, when the
    parent application is `APPROVED`, cascades it to `REVOKED` with the deposit forfeiture
    described in §2.8."

    Design: Difficulty/transitive_cascade/inspection_fail_revokes_and_forfeits
    """
    ctx = _approved_paid_with_inspection(api)
    inspection = fixtures.record_inspection(
        api, ctx["inspection"]["id"], ctx["inspector_id"], "FAILED")
    assert inspection["result"] == "FAILED"
    entries = fixtures.list_ledger_entries(api, ctx["application"]["id"])
    forfeit = find_ledger_entry(entries, "DEPOSIT_FORFEIT")
    assert forfeit is not None, f"expected a DEPOSIT_FORFEIT entry in {entries}"


def test_first_critical_violation_uses_standard_fine(api):
    """PRD §3.8: "The base fine is 2,500 cents for a `MINOR` violation, 10,000 cents for a
    `MAJOR` violation, and 25,000 cents for a `CRITICAL` violation." and "If there are no
    such prior violations, the fine equals the base and the `penalty_variant` is `STANDARD`."

    Design: Difficulty/dual_variant_calc/fine_standard_vs_repeat
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)
    insp_headers = make_inspector_headers(ctx["inspector_id"])
    payload = create_violation_payload(ctx["inspection"]["id"], severity="CRITICAL")
    data = validate_success(api.create_violation(payload, insp_headers), expected_status=201)
    assert data["fine_cents"] == 25000
    assert data["penalty_variant"] == "STANDARD"


def test_second_critical_violation_uses_repeat_multiplier(api):
    """PRD §3.8: "Otherwise this is a repeat offense: the fine is the base multiplied by a
    repeat multiplier of 1.5, rounded half-up to whole cents, and the `penalty_variant` is
    `REPEAT`."

    Second CRITICAL: round_half_up(25000 * 1.5) = 37500.

    Design: Difficulty/dual_variant_calc/fine_standard_vs_repeat
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)
    insp_headers = make_inspector_headers(ctx["inspector_id"])
    insp_id = ctx["inspection"]["id"]
    validate_success(api.create_violation(
        create_violation_payload(insp_id, severity="CRITICAL"), insp_headers), expected_status=201)
    second = validate_success(api.create_violation(
        create_violation_payload(insp_id, severity="CRITICAL", description="Overserving"),
        insp_headers), expected_status=201)
    assert second["fine_cents"] == 37500
    assert second["penalty_variant"] == "REPEAT"


def test_dismissing_violation_restores_balance(api):
    """PRD §3.8: "A `DISMISSED` decision moves it to `DISMISSED` and appends a compensating
    `FINE_REVERSAL` ledger entry for the negative of the fine, recomputing
    `balance_due_cents`."

    Balance 33789 before the MINOR fine; the FINE_REVERSAL restores it to 33789.

    Design: Difficulty/compensating_invariant/fine_reversal_conserves_balance
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)
    app_id = ctx["application"]["id"]
    insp_headers = make_inspector_headers(ctx["inspector_id"])
    before = fixtures.get_application(api, app_id)["balance_due_cents"]
    vio = validate_success(api.create_violation(
        create_violation_payload(ctx["inspection"]["id"], severity="MINOR",
                                 description="Signage missing"), insp_headers),
        expected_status=201)
    validate_success(api.contest_violation(vio["id"], APPLICANT))
    validate_success(api.resolve_violation(vio["id"], {"decision": "DISMISSED"}, CLERK))
    entries = fixtures.list_ledger_entries(api, app_id)
    assert find_ledger_entry(entries, "FINE_REVERSAL", -2500) is not None
    assert fixtures.get_application(api, app_id)["balance_due_cents"] == before


def test_dismissed_violation_keeps_offsetting_ledger_pair(api):
    """PRD §3.8: "The computed amount is written to `fine_cents`, and a `FINE` ledger entry
    for that amount (a positive debit) is appended and `balance_due_cents` recomputed."
    PRD §3.8: "A `DISMISSED` decision moves it to `DISMISSED` and appends a compensating
    `FINE_REVERSAL` ledger entry for the negative of the fine".

    Design: Difficulty/compensating_invariant/fine_reversal_conserves_balance
    """
    ctx = fixtures.drive_to_approved_with_inspection(api)
    app_id = ctx["application"]["id"]
    insp_headers = make_inspector_headers(ctx["inspector_id"])
    vio = validate_success(api.create_violation(
        create_violation_payload(ctx["inspection"]["id"], severity="MINOR",
                                 description="Signage missing"), insp_headers),
        expected_status=201)
    validate_success(api.contest_violation(vio["id"], APPLICANT))
    resolved = validate_success(api.resolve_violation(vio["id"], {"decision": "DISMISSED"}, CLERK))
    assert resolved["status"] == "DISMISSED"
    entries = fixtures.list_ledger_entries(api, app_id)
    assert find_ledger_entry(entries, "FINE", 2500) is not None
    assert find_ledger_entry(entries, "FINE_REVERSAL", -2500) is not None


def test_inspector_second_window_inside_buffer_rejected(api):
    """PRD §3.6: "The scheduling is refused if the named inspector already has another
    inspection whose window falls within 60 minutes of the requested window — that is, the
    two windows are less than an hour apart — in which case the request is rejected with
    `ERR_INSPECTOR_UNAVAILABLE`."

    First 10:00-11:00, second 11:30-12:00 (30 minutes apart).

    Design: Difficulty/resource_temporal_overlap/inspector_buffer_overlap
    """
    ctx = fixtures.drive_to_approved(api)
    app_id = ctx["application"]["id"]
    inspector = fixtures.create_inspector(api)
    validate_success(api.create_inspection(
        create_inspection_payload(app_id, inspector["id"],
                                  scheduled_start="2026-06-14T10:00:00Z",
                                  scheduled_end="2026-06-14T11:00:00Z"), CLERK),
        expected_status=201)
    resp = api.create_inspection(
        create_inspection_payload(app_id, inspector["id"],
                                  scheduled_start="2026-06-14T11:30:00Z",
                                  scheduled_end="2026-06-14T12:00:00Z"), CLERK)
    validate_error(resp, ApiErrorId.ERR_INSPECTOR_UNAVAILABLE)


def test_inspector_second_window_exactly_one_hour_apart_allowed(api):
    """PRD §3.6: "The scheduling is refused if the named inspector already has another
    inspection whose window falls within 60 minutes of the requested window — that is, the
    two windows are less than an hour apart — in which case the request is rejected with
    `ERR_INSPECTOR_UNAVAILABLE`."

    First 10:00-11:00, second 12:00-12:30 (a full 60 minutes apart, not less than an hour).

    Design: Difficulty/resource_temporal_overlap/inspector_buffer_overlap
    """
    ctx = fixtures.drive_to_approved(api)
    app_id = ctx["application"]["id"]
    inspector = fixtures.create_inspector(api)
    validate_success(api.create_inspection(
        create_inspection_payload(app_id, inspector["id"],
                                  scheduled_start="2026-06-14T10:00:00Z",
                                  scheduled_end="2026-06-14T11:00:00Z"), CLERK),
        expected_status=201)
    data = validate_success(api.create_inspection(
        create_inspection_payload(app_id, inspector["id"],
                                  scheduled_start="2026-06-14T12:00:00Z",
                                  scheduled_end="2026-06-14T12:30:00Z"), CLERK),
        expected_status=201)
    assert data["result"] == "SCHEDULED"
