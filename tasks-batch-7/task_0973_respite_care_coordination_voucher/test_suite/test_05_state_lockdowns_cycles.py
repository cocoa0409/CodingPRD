"""Terminal-state lockdowns, invalid transitions, no-show ops sweep, snapshot cycle."""
from test_helpers import (
    ADMIN,
    ANON,
    COORD,
    ApiErrorId,
    book_and_confirm,
    create_explicit_booking,
    create_program,
    create_provider_payload,
    make_caregiver_headers,
    make_provider_headers,
    run_ops_run,
    set_clock,
    setup_service_world,
    setup_verified_service,
    validate_error,
    validate_success,
)


def test_revoke_redeemed_voucher_rejected(api):
    """PRD §3.4: "A `Coordinator` may revoke an `ISSUED` voucher by posting to its
    revoke endpoint with an optional `reason`."
    PRD §2.9: "(7) generic state-machine validity (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/voucher_revoke_from_redeemed_rejected
    """
    ctx = setup_verified_service()  # voucher is REDEEMED after verification
    voucher = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
    assert voucher["status"] == "REDEEMED"
    res = api.revoke_voucher(ctx["voucher"]["id"], {"reason": "clawback attempt"}, COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
    assert after["status"] == "REDEEMED"


def test_confirm_cancelled_booking_rejected(api):
    """PRD §3.7: "A booking in `PENDING_CONFIRMATION` is confirmed by its owning
    provider."
    PRD §2.9: "(7) generic state-machine validity (`ERR_INVALID_STATE`)".
    PRD §3.7: "if every booking of the voucher is now in `CANCELLED` or `NO_SHOW`
    status, the voucher transitions back from `COMMITTED` to `ISSUED` with its
    `committed_hours` reset to 0."

    Design: Corner/state_machines/booking_confirm_after_cancel_rejected
    """
    ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                              window_end="2026-05-06T20:00:00Z",
                              window_capacity=1, voucher_hours=10)
    booking = create_explicit_booking(ctx["voucher"]["id"], ctx["caregiver"]["id"],
                                      ctx["provider"]["id"], ctx["window"]["id"],
                                      "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    validate_success(
        api.cancel_booking(booking["id"], {"reason": "plans changed"},
                           make_caregiver_headers(ctx["caregiver"]["id"])),
        200)
    res = api.confirm_booking(booking["id"],
                              make_provider_headers(ctx["provider"]["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    booking_after = validate_success(api.get_booking(booking["id"], COORD), 200)
    assert booking_after["status"] == "CANCELLED"
    voucher_after = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
    assert voucher_after["status"] == "ISSUED"
    assert voucher_after["committed_hours"] == 0.00


def test_terminated_provider_activation_rejected(api):
    """PRD §3.5: "`TERMINATED` is terminal."
    PRD §2.9: "(7) generic state-machine validity (`ERR_INVALID_STATE`)".

    Design: Corner/state_machines/provider_terminated_lockdown_rejected
    """
    create_program()
    provider = validate_success(api.create_provider(create_provider_payload(), ANON), 201)
    validate_success(
        api.transition_provider(provider["id"],
                                {"target_status": "TERMINATED", "reason": "fraud"}, COORD),
        200)
    res = api.transition_provider(provider["id"], {"target_status": "ACTIVE"}, COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_provider(provider["id"], COORD), 200)
    assert after["credential_status"] == "TERMINATED"


def test_no_show_ops_run_releases_commitment(api):
    """PRD §3.7: "If a booking in `CONFIRMED` never receives a check-in, an ops-run
    that observes `start_at` plus the program's `no_show_grace_minutes` (default 30)
    earlier than now, with no visit record present, transitions the booking to
    `NO_SHOW`. The voucher and window release effects are the same as a cancellation."
    PRD §3.7: "if every booking of the voucher is now in `CANCELLED` or `NO_SHOW`
    status, the voucher transitions back from `COMMITTED` to `ISSUED` with its
    `committed_hours` reset to 0."

    Design: Corner/state_machines/no_show_ops_run_releases_commitment
    """
    ctx = setup_service_world(window_start="2026-05-06T08:00:00Z",
                              window_end="2026-05-06T20:00:00Z",
                              window_capacity=1, voucher_hours=10)
    booking = book_and_confirm(ctx, "2026-05-06T10:00:00Z", "2026-05-06T12:00:00Z")
    set_clock("2026-05-06T10:31:00Z")  # past start + 30-minute grace
    run_ops_run(ctx["program"]["id"], "STANDARD")

    booking_after = validate_success(api.get_booking(booking["id"], COORD), 200)
    assert booking_after["status"] == "NO_SHOW"
    voucher_after = validate_success(api.get_voucher(ctx["voucher"]["id"], COORD), 200)
    assert voucher_after["status"] == "ISSUED"
    assert voucher_after["committed_hours"] == 0.00


def test_report_snapshot_amendment_cycle(api):
    """PRD §3.13: "From `GENERATED` the snapshot moves to `FINALIZED`. From
    `FINALIZED` it moves to `SUBMITTED_TO_FUNDER` or back into `UNDER_AMENDMENT`.
    From `SUBMITTED_TO_FUNDER` it moves to `UNDER_AMENDMENT`. From `UNDER_AMENDMENT`
    it moves back to `FINALIZED`. Each transition increments the snapshot's `version`
    by 1."
    PRD §2.4: "`version` is an integer that starts at 1 on creation and increments by
    exactly 1 on every mutation of the resource".

    Design: Corner/state_machines/report_snapshot_amendment_cycle
    """
    program = create_program()
    snapshot = run_ops_run(program["id"], "STANDARD")
    assert snapshot["status"] == "GENERATED"
    assert snapshot["version"] == 1

    for target in ("FINALIZED", "SUBMITTED_TO_FUNDER", "UNDER_AMENDMENT", "FINALIZED"):
        snapshot = validate_success(
            api.transition_report_snapshot(
                snapshot["id"],
                {"target_status": target, "note": "funder requested correction"},
                ADMIN),
            200)
    assert snapshot["status"] == "FINALIZED"
    assert snapshot["version"] == 5
