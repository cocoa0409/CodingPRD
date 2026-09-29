"""Gates that read the standing of a neighbouring actor rather than the target row.

A faultless application is still refused at submission when the rebuilder that owns
it has been suspended, and a free inspection slot is still refused when the
nominated inspector's commission has lapsed against the logical clock.
"""

from test_helpers import (
    ADMIN_USER_ID,
    api_client,
    make_program_admin_headers,
    make_rebuilder_headers,
    make_state_title_clerk_headers,
    read_application,
    read_inspector,
    read_rebuilder,
    read_station,
    schedule_inspection_payload,
    set_clock,
    setup_docs_accepted_application,
    setup_submission_ready_application,
    submit_application_payload,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import take_license_action

TRAILER_PROGRAM_CHARGE_CENTS = 7500
DEPOSIT_CENTS = 500000
CREDENTIAL_EXPIRY = "2026-09-01T00:00:00Z"
CLOCK_PAST_CREDENTIAL_EXPIRY = "2026-09-02T00:00:00Z"
LATE_SLOT_START = "2026-09-10T09:00:00Z"
LATE_SLOT_END = "2026-09-10T11:00:00Z"
EARLY_SLOT_START = "2026-08-10T09:00:00Z"
EARLY_SLOT_END = "2026-08-10T11:00:00Z"


def _submit(application_id: str, rebuilder_id: str):
    """Raw submit call, so the response envelope can be inspected directly."""
    return api_client.submit_application(
        application_id,
        submit_application_payload(),
        make_rebuilder_headers(rebuilder_id),
    )


def _schedule(env: dict, scheduled_start_at: str, scheduled_end_at: str):
    """Raw scheduling call against the application's last observed version."""
    return api_client.schedule_inspection(
        env["application_id"],
        schedule_inspection_payload(
            env["inspector_id"],
            env["station_id"],
            env["app_version"],
            scheduled_start_at,
            scheduled_end_at,
        ),
        make_state_title_clerk_headers(),
    )


# ===========================================================================
# the owning rebuilder's licence standing gates the submission
# ===========================================================================
def test_suspended_licence_refuses_the_owning_applications_submit():
    """A suspended rebuilder cannot submit even a complete trailer package.

    PRD: "The rebuilder's `license_status` must be `ACTIVE` or `PROBATION`, and a `SUSPENDED` or `REVOKED` licence is refused with `ERR_REBUILDER_LICENSE_INACTIVE` (HTTP 403) — the same code answers any action that demands a fully `ACTIVE` licence while the rebuilder sits on `PROBATION`."

    Design: Difficulty/cross_entity_state_dependency/submit_refused_because_owning_rebuilder_license_is_suspended
    """
    env = setup_submission_ready_application(body_class="TRAILER")
    take_license_action(env["rebuilder_id"], "SUSPEND", make_program_admin_headers())

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["license_status"] == "SUSPENDED", (
        f"expected license_status SUSPENDED, got {rebuilder['license_status']} after the action"
    )
    assert rebuilder["suspended_by_user_id"] == ADMIN_USER_ID, (
        f"expected suspended_by_user_id {ADMIN_USER_ID}, got {rebuilder['suspended_by_user_id']}"
    )

    validate_error(
        _submit(env["application_id"], env["rebuilder_id"]), "ERR_REBUILDER_LICENSE_INACTIVE"
    )


def test_licence_refusal_leaves_the_faultless_package_and_the_ledger_alone():
    """The refused submission escrows nothing and leaves the complete package in draft.

    PRD: "An action of `SUSPEND` moves the licence to `SUSPENDED` from either `ACTIVE` or `PROBATION`, records the acting administrator's `X-User-ID` as `suspended_by_user_id` (as well as in `last_license_action_by_user_id`), and thereafter refuses new applications and new submissions from that rebuilder; the same move happens on its own once `substantiated_referral_count` reaches 1."

    Design: Difficulty/cross_entity_state_dependency/submit_refused_because_owning_rebuilder_license_is_suspended
    """
    env = setup_submission_ready_application(body_class="TRAILER")
    take_license_action(env["rebuilder_id"], "SUSPEND", make_program_admin_headers())

    validate_error(
        _submit(env["application_id"], env["rebuilder_id"]), "ERR_REBUILDER_LICENSE_INACTIVE"
    )

    application = read_application(env["application_id"])
    assert application["status"] == "DRAFT", (
        f"expected status DRAFT, got {application['status']} after the refused submit"
    )
    assert application["documentation_completeness_pct"] == 100.00, (
        "a trailer requires no part classes, so documentation_completeness_pct must read "
        f"100.00, got {application['documentation_completeness_pct']}"
    )
    assert application["photo_view_count"] == 4, (
        f"expected photo_view_count 4, got {application['photo_view_count']} after four views"
    )
    assert application["fee_escrowed_cents"] == 0, (
        f"expected fee_escrowed_cents 0, got {application['fee_escrowed_cents']} "
        "after the refused submit"
    )
    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["fee_balance_cents"] == DEPOSIT_CENTS, (
        f"expected fee_balance_cents {DEPOSIT_CENTS}, got {rebuilder['fee_balance_cents']} "
        "after the refused submit"
    )
    assert rebuilder["escrowed_fee_total_cents"] == 0, (
        f"expected escrowed_fee_total_cents 0, got {rebuilder['escrowed_fee_total_cents']} "
        "after the refused submit"
    )


def test_probation_licence_still_admits_the_same_submission():
    """The same package goes through when the licence sits on probation instead.

    PRD: "A rebuilder on `PROBATION` may still open and submit applications."

    Design: Difficulty/cross_entity_state_dependency/submit_refused_because_owning_rebuilder_license_is_suspended
    """
    env = setup_submission_ready_application(body_class="TRAILER")
    take_license_action(env["rebuilder_id"], "PROBATION", make_program_admin_headers())

    rebuilder = read_rebuilder(env["rebuilder_id"])
    assert rebuilder["license_status"] == "PROBATION", (
        f"expected license_status PROBATION, got {rebuilder['license_status']}"
    )

    application = validate_success(_submit(env["application_id"], env["rebuilder_id"]))
    assert application["status"] == "SUBMITTED", (
        f"expected status SUBMITTED, got {application['status']} after a probation submit"
    )
    assert application["fee_escrowed_cents"] == TRAILER_PROGRAM_CHARGE_CENTS, (
        f"expected fee_escrowed_cents {TRAILER_PROGRAM_CHARGE_CENTS}, got "
        f"{application['fee_escrowed_cents']} for a trailer with no verified parts documents"
    )


# ===========================================================================
# the nominated inspector's credential standing gates the scheduling
# ===========================================================================
def test_lapsed_commission_refuses_the_scheduling_of_a_free_slot():
    """A booking into an empty calendar is refused once the inspector's commission lapses.

    PRD: "The acting inspector's `credential_status` must be `CURRENT`; an inspector whose `credential_expires_at` is at or before the logical clock is refused with `ERR_INSPECTOR_CREDENTIAL_EXPIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/scheduling_refused_because_assigned_inspector_credential_expired
    """
    env = setup_docs_accepted_application(
        body_class="TRAILER",
        inspector_overrides={"credential_expires_at": CREDENTIAL_EXPIRY},
    )
    set_clock(CLOCK_PAST_CREDENTIAL_EXPIRY)

    inspector = read_inspector(env["inspector_id"])
    assert inspector["credential_status"] == "EXPIRED", (
        f"expected credential_status EXPIRED, got {inspector['credential_status']} "
        "once the clock passed credential_expires_at"
    )

    validate_error(
        _schedule(env, LATE_SLOT_START, LATE_SLOT_END), "ERR_INSPECTOR_CREDENTIAL_EXPIRED"
    )


def test_credential_refusal_books_no_attempt_and_moves_no_occupancy():
    """The refused scheduling call creates no attempt and claims neither calendar nor bay.

    PRD: "A successful scheduling creates an attempt in `SCHEDULED`, computes its `effective_end_at`, assigns its `attempt_no`, moves the application's `status` to `SCHEDULED`, increments the application's `version` by 1, and increments both the inspector's `scheduled_inspection_count` and the station's `scheduled_occupancy_count`."

    Design: Difficulty/cross_entity_state_dependency/scheduling_refused_because_assigned_inspector_credential_expired
    """
    env = setup_docs_accepted_application(
        body_class="TRAILER",
        inspector_overrides={"credential_expires_at": CREDENTIAL_EXPIRY},
    )
    set_clock(CLOCK_PAST_CREDENTIAL_EXPIRY)

    validate_error(
        _schedule(env, LATE_SLOT_START, LATE_SLOT_END), "ERR_INSPECTOR_CREDENTIAL_EXPIRED"
    )

    attempts, meta = validate_paginated(
        api_client.list_inspections(
            make_state_title_clerk_headers(), params={"application_id": env["application_id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"expected total_count 0 attempts, got {meta['total_count']} after the refused scheduling"
    )
    assert attempts == [], f"expected no attempt rows, got {len(attempts)}"

    application = read_application(env["application_id"])
    assert application["status"] == "DOCS_ACCEPTED", (
        f"expected status DOCS_ACCEPTED, got {application['status']} after the refused scheduling"
    )
    inspector = read_inspector(env["inspector_id"])
    assert inspector["scheduled_inspection_count"] == 0, (
        f"expected scheduled_inspection_count 0, got {inspector['scheduled_inspection_count']}"
    )
    station = read_station(env["station_id"])
    assert station["scheduled_occupancy_count"] == 0, (
        f"expected scheduled_occupancy_count 0, got {station['scheduled_occupancy_count']}"
    )


def test_the_same_inspector_books_the_slot_while_the_commission_still_runs():
    """Credential standing is derived from the clock, so the booking is admitted before the lapse.

    PRD: "The inspector's `credential_status` is never supplied: it reads `EXPIRED` when `credential_expires_at` is at or before the logical clock and `CURRENT` otherwise, which means that advancing the clock past an expiry silently disqualifies that inspector from every operation that requires a current credential."

    Design: Difficulty/cross_entity_state_dependency/scheduling_refused_because_assigned_inspector_credential_expired
    """
    env = setup_docs_accepted_application(
        body_class="TRAILER",
        inspector_overrides={"credential_expires_at": CREDENTIAL_EXPIRY},
    )

    inspector = read_inspector(env["inspector_id"])
    assert inspector["credential_status"] == "CURRENT", (
        f"expected credential_status CURRENT, got {inspector['credential_status']} "
        "while the clock stands before credential_expires_at"
    )

    attempt = validate_success(_schedule(env, EARLY_SLOT_START, EARLY_SLOT_END), expected_status=201)
    assert attempt["status"] == "SCHEDULED", (
        f"expected status SCHEDULED, got {attempt['status']} for the booked attempt"
    )
    assert attempt["inspector_id"] == env["inspector_id"], (
        f"expected inspector_id {env['inspector_id']}, got {attempt['inspector_id']}"
    )

    set_clock(CLOCK_PAST_CREDENTIAL_EXPIRY)
    inspector = read_inspector(env["inspector_id"])
    assert inspector["credential_status"] == "EXPIRED", (
        f"expected credential_status EXPIRED, got {inspector['credential_status']} "
        "once the clock passed credential_expires_at"
    )
