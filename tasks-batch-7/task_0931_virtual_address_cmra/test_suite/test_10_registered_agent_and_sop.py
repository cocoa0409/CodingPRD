"""The registered-agent add-on and service-of-process handling."""

import pytest

from test_helpers import (
    CMRA_OPERATOR,
    PLATFORM_ADMIN,
    ApiErrorId,
    assert_registered_agent_service,
    assert_same_instant,
    attach_registered_agent,
    create_carrier_rule,
    log_and_match_package,
    log_and_match_sop,
    lodge_disposition,
    read_mail_item,
    registered_agent_payload,
    set_clock,
    setup_releasable_box,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_deactivating_the_add_on_flips_the_flag_and_stamps_the_clock(api):
    """PRD §3.10: "It names a `jurisdiction_code`, exactly two uppercase letters
    identifying the state whose statute governs service-of-process retention, and an
    optional `retention_days` which defaults to 1,095 days — three years — and must be at
    least 1."
    PRD §3.10: "Deactivating it sets `active` false, stamps `deactivated_at` from the
    clock, and bumps `RegisteredAgentService.version` by one."

    Design: Corner/state_machines/registered_agent_deactivation_sets_the_flag_and_timestamp
    """
    ctx = setup_releasable_box("Z-1009", "Ras Agent", holder_email="ras@example.com")
    add_on = validate_success(
        api.create_registered_agent(
            ctx["box_id"], registered_agent_payload("DE"), PLATFORM_ADMIN
        ),
        201,
    )
    assert_registered_agent_service(add_on)
    assert add_on["active"] is True
    assert add_on["deactivated_at"] is None
    assert add_on["retention_days"] == 1095

    deactivated = validate_success(
        api.deactivate_registered_agent(ctx["box_id"], PLATFORM_ADMIN)
    )
    assert deactivated["active"] is False
    assert_same_instant(
        deactivated["deactivated_at"], "2026-05-01T00:00:00.000Z", "deactivated_at"
    )
    assert deactivated["retention_days"] == 1095
    assert deactivated["jurisdiction_code"] == "DE"

    _, meta = validate_paginated(
        api.list_registered_agents(ctx["box_id"], CMRA_OPERATOR)
    )
    assert meta["total_count"] == 1


def test_a_service_of_process_piece_is_free_and_runs_the_four_hour_clock(api):
    """PRD §3.5: "For a service-of-process piece, `package_acceptance_fee_cents` is zero
    — statutory documents are handled free as part of the registered-agent add-on."
    PRD §3.5: "Acceptance also starts the notification obligation.
    `notification_status` moves from `NOT_REQUIRED` to `PENDING` and
    `notification_due_at` is computed from `accepted_at`: for a service-of-process piece
    on a mailbox carrying an add-on with `active` true, the deadline is `accepted_at`
    plus **4 hours**, the same-business-day statutory clock; for every other case — an
    ordinary package, or a service-of-process piece with no active add-on — the deadline
    is `accepted_at` plus **24 hours**."

    Design: Corner/calculations/sop_acceptance_is_free_and_uses_the_four_hour_sla
    """
    ctx = setup_releasable_box("Z-2002", "Tia Serve", holder_email="tia2@example.com")
    rule = create_carrier_rule(carrier_code="UPS")
    attach_registered_agent(ctx["box_id"], "DE", 1095)
    sop = log_and_match_sop(
        ctx, rule["id"], actual_weight_lb=5.0, length_in=10.0, width_in=8.0, height_in=6.0
    )
    package = log_and_match_package(
        ctx, rule["id"], actual_weight_lb=5.0, length_in=10.0, width_in=8.0, height_in=6.0
    )

    accepted_sop = validate_success(api.accept_package(sop["id"], CMRA_OPERATOR))
    assert accepted_sop["billable_weight_lb"] == pytest.approx(5.0, abs=0.01)
    assert accepted_sop["package_acceptance_fee_cents"] == 0
    assert_same_instant(accepted_sop["accepted_at"], "2026-05-01T00:00:00.000Z", "accepted_at")
    assert_same_instant(
        accepted_sop["notification_due_at"], "2026-05-01T04:00:00.000Z", "notification_due_at"
    )
    assert accepted_sop["notification_status"] == "PENDING"

    accepted_package = validate_success(api.accept_package(package["id"], CMRA_OPERATOR))
    assert accepted_package["package_acceptance_fee_cents"] == 500
    assert_same_instant(
        accepted_package["notification_due_at"],
        "2026-05-02T00:00:00.000Z",
        "notification_due_at",
    )


def test_a_service_of_process_piece_cannot_be_accepted_without_an_active_add_on(api):
    """PRD §3.10: "they may only be accepted, scanned or notified while an active add-on
    exists (`ERR_RA_SERVICE_REQUIRED`); their acceptance fee is zero; their notification
    deadline is 4 hours rather than 24; they are exempt from storage accrual, so their
    `free_storage_days_used` equals their total custody days and their
    `billable_storage_days` is always zero no matter how long custody runs, and their
    storage axis never leaves `FREE_WINDOW` for `ACCRUING`; they bypass the scan-page
    quota entirely; and they are never eligible for consolidation onto a forward
    shipment."
    PRD §2.9 rung 20: "A service-of-process piece requires an add-on with `active` true
    on its mailbox before it may be accepted, scanned or notified. Otherwise
    `ERR_RA_SERVICE_REQUIRED` (403)."

    Design: Corner/validations/sop_handling_without_the_registered_agent_addon_is_rejected
    """
    ctx = setup_releasable_box("Z-3007", "Ike Serve", holder_email="ike@example.com")
    rule = create_carrier_rule(carrier_code="UPS")
    sop = log_and_match_sop(
        ctx,
        rule["id"],
        actual_weight_lb=1.0,
        length_in=10.0,
        width_in=8.0,
        height_in=1.0,
        interior_scan_consent=True,
    )

    blocked = api.accept_package(sop["id"], CMRA_OPERATOR)
    validate_error(blocked, ApiErrorId.ERR_RA_SERVICE_REQUIRED.value)

    add_on = validate_success(
        api.create_registered_agent(
            ctx["box_id"], registered_agent_payload("NV", 730), PLATFORM_ADMIN
        ),
        201,
    )
    assert add_on["retention_days"] == 730

    accepted = validate_success(api.accept_package(sop["id"], CMRA_OPERATOR))
    assert accepted["package_acceptance_fee_cents"] == 0
    assert_same_instant(
        accepted["notification_due_at"], "2026-05-01T04:00:00.000Z", "notification_due_at"
    )


def test_a_service_of_process_piece_cannot_be_shredded_inside_its_retention_period(api):
    """PRD §3.10: "For a service-of-process piece on a mailbox with an active add-on, the
    retention deadline is the calendar date of the piece's `received_at` plus the add-on's
    `retention_days`."
    PRD §3.10: "Destruction is refused while the clock date is **strictly less than**
    that deadline, which is to say destruction becomes permissible on the deadline date
    itself."
    PRD §3.12: "For a service-of-process piece the split is different and unconditional:
    `free_storage_days_used` equals total custody days and `billable_storage_days` is
    zero, however long custody runs."

    2026-06-01 sits far below the 2028-04-30 deadline of a 730-day retention that
    started on 2026-05-01.

    Design: Corner/validations/sop_shred_inside_the_statutory_retention_is_rejected
    """
    ctx = setup_releasable_box("Z-3008", "Jon Keep", holder_email="jon@example.com")
    rule = create_carrier_rule(carrier_code="UPS")
    attach_registered_agent(ctx["box_id"], "NV", 730)
    sop = log_and_match_sop(
        ctx,
        rule["id"],
        actual_weight_lb=1.0,
        length_in=10.0,
        width_in=8.0,
        height_in=1.0,
        interior_scan_consent=True,
    )
    validate_success(api.accept_package(sop["id"], CMRA_OPERATOR))
    disposition = lodge_disposition(ctx, sop["id"], "SHRED")
    set_clock("2026-06-01T00:00:00Z")

    response = api.execute_disposition(disposition["id"], CMRA_OPERATOR)
    validate_error(response, ApiErrorId.ERR_RA_RETENTION_ACTIVE.value)

    still_pending = validate_success(
        api.list_dispositions(sop["id"], CMRA_OPERATOR)
    )
    assert still_pending[0]["status"] == "PENDING"

    piece = read_mail_item(sop["id"])
    assert piece["handling_status"] == "PENDING_DISPOSITION"
    assert piece["storage_status"] == "FREE_WINDOW"
    assert piece["billable_storage_days"] == 0
