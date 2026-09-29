"""Lifecycle admissibility: initial states, refused re-entries and terminal lockdown.

An application opens in draft with three attempts on the clock, moves under review
only on the clerk's open decision, and refuses a second submission rather than
escrowing the program charge twice. An attempt already under way refuses a second
start; a rebuilt title refuses to mint before the attempt has passed; a withdrawn
application and a surrendered instrument are both locked against every further
transition; and an appeal may cycle back through review exactly once. The escrow
move published by submission is visible in the very response that performs it.
"""

from test_helpers import (
    BASE_APPLICATION_FEE_CENTS,
    DEFAULT_ATTEMPT_LIMIT,
    HEARING_OFFICER_USER_ID,
    TEST_USERS,
    api_client,
    assert_application,
    assert_fee_ledger_closes,
    checkpoint_results,
    create_application_payload,
    create_title_transfer_payload,
    decide_appeal_payload,
    docs_review_payload,
    issue_rebuilt_title_payload,
    make_inspector_headers,
    make_rebuilder_headers,
    start_inspection_payload,
    submit_application_payload,
    surrender_title_payload,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_application_payload,
)
from test_helpers.fixtures import (
    decide_appeal,
    file_appeal,
    read_appeal,
    read_application,
    read_inspection,
    read_rebuilder,
    read_title,
    read_vehicle,
    review_appeal,
    setup_completed_inspection,
    setup_docs_accepted_application,
    setup_draft_application,
    setup_inspection_in_progress,
    setup_program_actors,
    setup_salvage_titled_vehicle,
    setup_submission_ready_application,
    setup_submitted_application,
    surrender_title,
    withdraw_application,
)

api = api_client

ADMIN = TEST_USERS["program_admin_headers"]
CLERK = TEST_USERS["state_title_clerk_headers"]
HEARING_OFFICER = TEST_USERS["hearing_officer_headers"]

CLOCK_EPOCH_PREFIX = "2026-08-01T00:00:00"
SLOT_START_PREFIX = "2026-08-10T09:00:00"

# A TRAILER requires no part classes, so its only program charge is the base fee.
TRAILER_CHARGE_CENTS = 7500
TRAILER_DEPOSIT_CENTS = 500_000
TRAILER_BALANCE_AFTER_ESCROW_CENTS = 492_500


class TestInitialStates:
    """Where a row starts, and what the server seeds onto it."""

    def test_a_new_application_opens_in_draft_with_three_attempts(self):
        """A rebuilder's fresh application starts in draft, unescrowed, with three tries.

        PRD: "Its `fee_escrowed_cents` is 0, its `attempt_limit` is 3, and its `assessed_fee_cents` is initialised to the base application fee of 7,500 cents."

        Design: Corner/state_machines/new_application_starts_in_draft_with_attempt_limit_three
        """
        actors = setup_program_actors()
        branded = setup_salvage_titled_vehicle()

        response = api.create_application(
            create_application_payload(
                branded["vehicle_id"], actors["rebuilder_id"], branded["salvage_title_id"]
            ),
            make_rebuilder_headers(actors["rebuilder_id"]),
        )
        application = validate_success(response, expected_status=201)
        assert_application(application)

        assert application["status"] == "DRAFT", (
            f"a newly opened application begins in DRAFT, got {application['status']}"
        )
        assert application["attempt_limit"] == DEFAULT_ATTEMPT_LIMIT, (
            f"expected an attempt limit of 3, got {application['attempt_limit']}"
        )
        assert application["attempts_completed"] == 0, (
            f"no attempt has been made yet, got {application['attempts_completed']}"
        )
        assert application["fee_escrowed_cents"] == 0, (
            f"nothing is escrowed before submission, got {application['fee_escrowed_cents']}"
        )
        assert application["assessed_fee_cents"] == BASE_APPLICATION_FEE_CENTS, (
            f"expected the base application fee 7500, got {application['assessed_fee_cents']}"
        )
        assert application["documentation_completeness_pct"] == 0.00, (
            "a sedan starts with none of its three required classes covered, "
            f"got {application['documentation_completeness_pct']}"
        )
        assert application["photo_view_count"] == 0, (
            f"no camera angle is on file yet, got {application['photo_view_count']}"
        )
        assert application["last_inspection_result"] is None, (
            f"no attempt has been adjudicated, got {application['last_inspection_result']!r}"
        )
        assert application["terminal_at"] is None, (
            f"a draft application is not terminal, got {application['terminal_at']!r}"
        )

        vehicle = read_vehicle(branded["vehicle_id"])
        assert vehicle["open_application_count"] == 1, (
            f"the vehicle now carries one live application, "
            f"got {vehicle['open_application_count']}"
        )


class TestForwardEdgesAndRefusedRepeats:
    """The declared edge fires once; the same trigger a second time is refused."""

    def test_the_open_decision_moves_a_submitted_package_under_review(self):
        """The clerk opening the file moves it under review and leaves the escrow held.

        PRD: "A decision of `OPEN` takes a `SUBMITTED` application to `DOCS_UNDER_REVIEW`, records the note, and refreshes `updated_at` and `version`."

        Design: Corner/state_machines/docs_review_open_moves_a_submitted_application_to_docs_under_review
        """
        env = setup_submitted_application(body_class="TRAILER")

        reviewed = validate_success(
            api.review_application_docs(
                env["application_id"], docs_review_payload("OPEN"), CLERK
            )
        )
        assert reviewed["status"] == "DOCS_UNDER_REVIEW", (
            f"expected DOCS_UNDER_REVIEW after the open decision, got {reviewed['status']}"
        )
        assert reviewed["assessed_fee_cents"] == TRAILER_CHARGE_CENTS, (
            "a trailer draws no structural or donor surcharge, "
            f"got assessed_fee_cents {reviewed['assessed_fee_cents']}"
        )
        assert reviewed["total_program_charge_cents"] == TRAILER_CHARGE_CENTS, (
            f"expected a program charge of 7500, "
            f"got {reviewed['total_program_charge_cents']}"
        )
        assert reviewed["fee_escrowed_cents"] == TRAILER_CHARGE_CENTS, (
            f"the escrow taken at submission is still held, "
            f"got {reviewed['fee_escrowed_cents']}"
        )
        assert reviewed["documentation_completeness_pct"] == 100.00, (
            "a trailer's empty required list is vacuously complete, "
            f"got {reviewed['documentation_completeness_pct']}"
        )
        assert reviewed["photo_view_count"] == 4, (
            f"four distinct camera angles are on file, got {reviewed['photo_view_count']}"
        )

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["fee_balance_cents"] == TRAILER_BALANCE_AFTER_ESCROW_CENTS, (
            f"expected a spendable balance of 492500, got {rebuilder['fee_balance_cents']}"
        )
        assert rebuilder["escrowed_fee_total_cents"] == TRAILER_CHARGE_CENTS, (
            f"expected 7500 still escrowed, got {rebuilder['escrowed_fee_total_cents']}"
        )
        assert_fee_ledger_closes(rebuilder)

    def test_submitting_the_same_application_twice_escrows_nothing_further(self):
        """A second attestation on an already-submitted package cannot bill the rebuilder again.

        PRD: "The application must be in `DRAFT` — `ERR_APPLICATION_NOT_DRAFT` otherwise — and the acting rebuilder must own it."

        Design: Corner/state_machines/submitting_an_application_twice_is_rejected_as_not_draft
        """
        env = setup_submitted_application(body_class="TRAILER")

        validate_error(
            api.submit_application(
                env["application_id"],
                submit_application_payload(),
                make_rebuilder_headers(env["rebuilder_id"]),
            ),
            "ERR_APPLICATION_NOT_DRAFT",
        )

        application = read_application(env["application_id"])
        assert application["status"] == "SUBMITTED", (
            f"the refused call leaves the application SUBMITTED, got {application['status']}"
        )
        assert application["fee_escrowed_cents"] == TRAILER_CHARGE_CENTS, (
            f"the escrow is not taken twice, got {application['fee_escrowed_cents']}"
        )

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["fee_balance_cents"] == TRAILER_BALANCE_AFTER_ESCROW_CENTS, (
            f"the balance is charged exactly once, got {rebuilder['fee_balance_cents']}"
        )
        assert rebuilder["escrowed_fee_total_cents"] == TRAILER_CHARGE_CENTS, (
            f"expected 7500 escrowed in total, got {rebuilder['escrowed_fee_total_cents']}"
        )
        assert_fee_ledger_closes(rebuilder)

    def test_starting_an_attempt_already_under_way_is_refused(self):
        """An inspector cannot restart an attempt that is already open on the lift.

        PRD: "Starting is admissible only from `SCHEDULED`, requires the inspector's `credential_status` to be `CURRENT`, requires the logical clock to have reached or passed `scheduled_start_at`, and requires the vehicle's `fraud_hold` to be `NONE`."

        Design: Corner/state_machines/starting_an_inspection_twice_is_rejected_as_not_scheduled
        """
        env = setup_inspection_in_progress(body_class="TRAILER")
        first_started_at = env["inspection"]["started_at"]

        validate_error(
            api.start_inspection(
                env["inspection_id"],
                start_inspection_payload(),
                make_inspector_headers(env["inspector_id"]),
            ),
            "ERR_INSPECTION_NOT_SCHEDULED",
        )

        inspection = read_inspection(env["inspection_id"])
        assert inspection["status"] == "IN_PROGRESS", (
            f"the attempt stays open, got {inspection['status']}"
        )
        assert inspection["started_at"] == first_started_at, (
            f"the original start instant survives, expected {first_started_at}, "
            f"got {inspection['started_at']}"
        )
        assert inspection["started_at"].startswith(SLOT_START_PREFIX), (
            f"started_at was stamped at the slot's start, got {inspection['started_at']}"
        )

        application = read_application(env["application_id"])
        assert application["status"] == "IN_INSPECTION", (
            f"the application reads IN_INSPECTION while the attempt is open, "
            f"got {application['status']}"
        )

        rows, meta = validate_paginated(
            api.list_inspections(CLERK, {"application_id": env["application_id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused start creates no second attempt, got {meta['total_count']}"
        )
        assert len(rows) == 1, f"expected exactly one attempt row, got {len(rows)}"

    def test_a_rebuilt_title_cannot_be_minted_before_the_attempt_passes(self):
        """No brand converts on paperwork alone: the vehicle must have passed inspection.

        PRD: "The application's `status` must be exactly `PASSED`, or `ERR_INVALID_APPLICATION_STATE` results."

        Design: Corner/state_machines/issuing_a_rebuilt_title_from_docs_accepted_is_rejected_as_invalid_state
        """
        env = setup_docs_accepted_application(body_class="TRAILER")

        validate_error(
            api.issue_rebuilt_title(
                env["application_id"], issue_rebuilt_title_payload(), CLERK
            ),
            "ERR_INVALID_APPLICATION_STATE",
        )

        application = read_application(env["application_id"])
        assert application["status"] == "DOCS_ACCEPTED", (
            f"the application stays schedulable, got {application['status']}"
        )

        salvage_title = read_title(env["salvage_title_id"])
        assert salvage_title["status"] == "ACTIVE", (
            f"the salvage title is not superseded, got {salvage_title['status']}"
        )
        assert salvage_title["brand_code"] == "SALVAGE", (
            f"the salvage brand is untouched, got {salvage_title['brand_code']}"
        )

        _, meta = validate_paginated(
            api.list_title_records(CLERK, {"vehicle_id": env["vehicle_id"]})
        )
        assert meta["total_count"] == 1, (
            f"no successor instrument was minted, got {meta['total_count']} titles"
        )

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["applications_titled_count"] == 0, (
            f"no application has been titled, got {rebuilder['applications_titled_count']}"
        )
        assert rebuilder["fees_consumed_cents"] == 0, (
            f"no escrow was captured, got {rebuilder['fees_consumed_cents']}"
        )


class TestTerminalLockdown:
    """A row that has reached the end of its lifecycle accepts nothing further."""

    def test_a_withdrawn_application_cannot_be_resubmitted(self):
        """Pulling out is final: the withdrawn package is no longer a draft to submit.

        PRD: "The application must be in `DRAFT` — `ERR_APPLICATION_NOT_DRAFT` otherwise — and the acting rebuilder must own it."

        Design: Corner/state_machines/withdrawn_application_is_locked_against_further_transitions
        """
        env = setup_submission_ready_application(body_class="TRAILER")
        withdrawn = withdraw_application(env["application_id"], env["rebuilder_id"])
        assert withdrawn["status"] == "WITHDRAWN", (
            f"the fixture must reach WITHDRAWN first, got {withdrawn['status']}"
        )

        validate_error(
            api.submit_application(
                env["application_id"],
                submit_application_payload(),
                make_rebuilder_headers(env["rebuilder_id"]),
            ),
            "ERR_APPLICATION_NOT_DRAFT",
        )

        application = read_application(env["application_id"])
        assert application["status"] == "WITHDRAWN", (
            f"the application stays withdrawn, got {application['status']}"
        )
        assert application["fee_escrowed_cents"] == 0, (
            f"the refunded escrow is not re-taken, got {application['fee_escrowed_cents']}"
        )

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["fee_balance_cents"] == TRAILER_DEPOSIT_CENTS, (
            f"the whole deposit is spendable again, got {rebuilder['fee_balance_cents']}"
        )
        assert rebuilder["escrowed_fee_total_cents"] == 0, (
            f"nothing is held against the rebuilder, "
            f"got {rebuilder['escrowed_fee_total_cents']}"
        )
        assert_fee_ledger_closes(rebuilder)

    def test_a_withdrawn_application_cannot_be_withdrawn_a_second_time(self):
        """The exit door only opens once; a terminal application refuses the same call.

        PRD: "Withdrawing from a terminal status is refused with `ERR_INVALID_APPLICATION_STATE`."

        Design: Corner/state_machines/withdrawn_application_is_locked_against_further_transitions
        """
        env = setup_draft_application(body_class="TRAILER")
        withdrawn = withdraw_application(env["application_id"], env["rebuilder_id"])
        assert withdrawn["terminal_at"] is not None, (
            "a withdrawal stamps terminal_at, got None"
        )

        validate_error(
            api.withdraw_application(
                env["application_id"],
                withdraw_application_payload(),
                make_rebuilder_headers(env["rebuilder_id"]),
            ),
            "ERR_INVALID_APPLICATION_STATE",
        )

        application = read_application(env["application_id"])
        assert application["status"] == "WITHDRAWN", (
            f"the refused call leaves the terminal status alone, got {application['status']}"
        )
        assert application["terminal_at"] == withdrawn["terminal_at"], (
            f"the original terminal instant survives, expected {withdrawn['terminal_at']}, "
            f"got {application['terminal_at']}"
        )
        assert application["terminal_at"].startswith(CLOCK_EPOCH_PREFIX), (
            f"the withdrawal was stamped at the current reading of the clock, "
            f"got {application['terminal_at']}"
        )
        assert application["version"] == withdrawn["version"], (
            f"a refused transition bumps no version, expected {withdrawn['version']}, "
            f"got {application['version']}"
        )

        vehicle = read_vehicle(env["vehicle_id"])
        assert vehicle["open_application_count"] == 0, (
            f"the vehicle is free for a fresh application, "
            f"got {vehicle['open_application_count']}"
        )

    def test_a_surrendered_title_cannot_be_conveyed_to_a_buyer(self):
        """A handed-in write-off cannot be sold on: its certificate is no longer active.

        PRD: "The outgoing title must have `status` of `ACTIVE` with `is_current` true, or `ERR_TITLE_NOT_ACTIVE` results."

        Design: Corner/state_machines/surrendered_title_cannot_be_transferred_or_resurrendered
        """
        branded = setup_salvage_titled_vehicle(repair_estimate_cents=1_300_000)
        title_id = branded["salvage_title_id"]
        assert branded["salvage_title"]["brand_code"] == "NON_REPAIRABLE", (
            "a repair estimate of 1.30 times value brands the title beyond repair, "
            f"got {branded['salvage_title']['brand_code']}"
        )
        surrendered = surrender_title(title_id)
        assert surrendered["status"] == "SURRENDERED", (
            f"the fixture must reach SURRENDERED first, got {surrendered['status']}"
        )

        validate_error(
            api.create_title_transfer(create_title_transfer_payload(title_id), CLERK),
            "ERR_TITLE_NOT_ACTIVE",
        )

        _, meta = validate_paginated(
            api.list_title_transfers(CLERK, {"from_title_id": title_id})
        )
        assert meta["total_count"] == 0, (
            f"no conveyance was recorded off the surrendered title, got {meta['total_count']}"
        )

        title = read_title(title_id)
        assert title["status"] == "SURRENDERED", (
            f"the title stays surrendered, got {title['status']}"
        )
        assert title["is_current"] is False, (
            f"a surrendered certificate is not the current one, got {title['is_current']!r}"
        )
        assert title["version"] == surrendered["version"], (
            f"the refused conveyance bumps no version, expected {surrendered['version']}, "
            f"got {title['version']}"
        )

    def test_a_surrendered_title_cannot_be_surrendered_again(self):
        """Handing in the same certificate twice is refused rather than double-counted.

        PRD: "A title that is not `ACTIVE` with `is_current` true is refused with `ERR_TITLE_NOT_ACTIVE`."

        Design: Corner/state_machines/surrendered_title_cannot_be_transferred_or_resurrendered
        """
        branded = setup_salvage_titled_vehicle(repair_estimate_cents=1_300_000)
        title_id = branded["salvage_title_id"]
        surrendered = surrender_title(title_id)
        assert surrendered["brand_code"] == "NON_REPAIRABLE", (
            f"only a write-off may be surrendered, got {surrendered['brand_code']}"
        )

        validate_error(
            api.surrender_title_record(title_id, surrender_title_payload(), CLERK),
            "ERR_TITLE_NOT_ACTIVE",
        )

        title = read_title(title_id)
        assert title["status"] == "SURRENDERED", (
            f"the title stays surrendered, got {title['status']}"
        )
        assert title["version"] == surrendered["version"], (
            f"the refused surrender bumps no version, expected {surrendered['version']}, "
            f"got {title['version']}"
        )

        vehicle = read_vehicle(branded["vehicle_id"])
        assert vehicle["active_brand_code"] == "NONE", (
            f"surrender leaves no active brand on the vehicle, "
            f"got {vehicle['active_brand_code']}"
        )
        assert "NON_REPAIRABLE" in vehicle["brand_history"], (
            f"the write-off is remembered forever, got {vehicle['brand_history']}"
        )

        rows, meta = validate_paginated(
            api.list_title_records(CLERK, {"vehicle_id": branded["vehicle_id"]})
        )
        assert meta["total_count"] == 1, (
            f"the refused call minted nothing, got {meta['total_count']} titles"
        )
        assert len(rows) == 1, f"expected exactly one title row, got {len(rows)}"


class TestBoundedCycles:
    """An edge that loops back on itself is still bounded by a counter."""

    def test_an_appeal_may_be_remanded_only_once(self):
        """The hearing may be sent back for rework once; the second remand is refused.

        PRD: "Remands are bounded: an appeal may be remanded only while its `remand_count` is still below 1, so exactly one remand is ever permitted, and a second attempt to remand is refused with `ERR_APPEAL_STATE_INVALID`."

        Design: Corner/state_machines/appeal_remands_once_back_to_under_review_and_the_second_remand_is_rejected
        """
        env = setup_completed_inspection(
            results=checkpoint_results(structural_frame="FAIL"), body_class="TRAILER"
        )
        assert env["inspection"]["result"] == "FAIL", (
            f"a failed frame checkpoint is an automatic failure, "
            f"got {env['inspection']['result']}"
        )

        appeal = file_appeal(env["inspection_id"], env["rebuilder_id"])
        review_appeal(appeal["id"])
        remanded = decide_appeal(appeal["id"], "REMAND")
        assert remanded["status"] == "REMANDED", (
            f"the first remand lands the appeal in REMANDED, got {remanded['status']}"
        )
        assert remanded["remand_count"] == 1, (
            f"the first remand raises remand_count to 1, got {remanded['remand_count']}"
        )

        taken_up_again = review_appeal(appeal["id"])
        assert taken_up_again["status"] == "UNDER_REVIEW", (
            f"a remanded appeal cycles back to UNDER_REVIEW, got {taken_up_again['status']}"
        )

        validate_error(
            api.decide_appeal(appeal["id"], decide_appeal_payload("REMAND"), HEARING_OFFICER),
            "ERR_APPEAL_STATE_INVALID",
        )

        after = read_appeal(appeal["id"])
        assert after["status"] == "UNDER_REVIEW", (
            f"the refused second remand leaves the appeal under review, got {after['status']}"
        )
        assert after["remand_count"] == 1, (
            f"exactly one remand is ever counted, got {after['remand_count']}"
        )
        assert after["decided_at"] is None, (
            f"no terminal decision has been stamped, got {after['decided_at']!r}"
        )
        assert after["hearing_officer_user_id"] == HEARING_OFFICER_USER_ID, (
            f"the officer who took the appeal up again is on record, "
            f"got {after['hearing_officer_user_id']!r}"
        )

        application = read_application(env["application_id"])
        assert application["status"] == "APPEAL_PENDING", (
            f"the application waits on the live appeal, got {application['status']}"
        )
        assert application["attempt_limit"] == DEFAULT_ATTEMPT_LIMIT, (
            f"no remand restores an attempt, got {application['attempt_limit']}"
        )

        inspection = read_inspection(env["inspection_id"])
        assert inspection["status"] == "COMPLETED_FAIL", (
            f"the appealed attempt stays closed and failed, got {inspection['status']}"
        )
        assert inspection["adequacy_score"] == 65.00, (
            "a failed frame checkpoint leaves the other four weights, 20+20+15+10, "
            f"got {inspection['adequacy_score']}"
        )


class TestSameRequestVisibility:
    """A write that moves money publishes the moved money in its own response."""

    def test_the_submission_response_already_shows_the_escrowed_charge(self):
        """The escrow move is not deferred: the submit response itself carries the hold.

        PRD: "It then sets `fee_escrowed_cents` equal to the freshly computed `total_program_charge_cents`, raises the rebuilder's `escrowed_fee_total_cents` by that charge, lowers the rebuilder's `fee_balance_cents` by the same charge, and moves the application `DRAFT → SUBMITTED`."

        Design: Corner/consistency_model/submit_publishes_the_escrow_move_in_the_same_request
        """
        env = setup_submission_ready_application(body_class="TRAILER")
        draft_version = env["application"]["version"]

        submitted = validate_success(
            api.submit_application(
                env["application_id"],
                submit_application_payload(),
                make_rebuilder_headers(env["rebuilder_id"]),
            )
        )
        assert submitted["status"] == "SUBMITTED", (
            f"the same request moves DRAFT to SUBMITTED, got {submitted['status']}"
        )
        assert submitted["total_program_charge_cents"] == TRAILER_CHARGE_CENTS, (
            f"the charge is computed inside this request, "
            f"got {submitted['total_program_charge_cents']}"
        )
        assert submitted["fee_escrowed_cents"] == submitted["total_program_charge_cents"], (
            f"the escrow equals the freshly computed charge, "
            f"got {submitted['fee_escrowed_cents']} against "
            f"{submitted['total_program_charge_cents']}"
        )
        assert submitted["fee_escrowed_cents"] == TRAILER_CHARGE_CENTS, (
            f"expected 7500 escrowed, got {submitted['fee_escrowed_cents']}"
        )
        assert submitted["version"] > draft_version, (
            f"the submitted row is a later version than the draft, "
            f"expected more than {draft_version}, got {submitted['version']}"
        )

        rebuilder = read_rebuilder(env["rebuilder_id"])
        assert rebuilder["escrowed_fee_total_cents"] == TRAILER_CHARGE_CENTS, (
            f"the rebuilder's held total rose by the same charge, "
            f"got {rebuilder['escrowed_fee_total_cents']}"
        )
        assert rebuilder["fee_balance_cents"] == TRAILER_BALANCE_AFTER_ESCROW_CENTS, (
            f"the spendable balance fell by the same charge, "
            f"got {rebuilder['fee_balance_cents']}"
        )
        assert rebuilder["fees_deposited_cents"] == TRAILER_DEPOSIT_CENTS, (
            f"the deposit itself is untouched, got {rebuilder['fees_deposited_cents']}"
        )
        assert rebuilder["fees_consumed_cents"] == 0, (
            f"an escrow hold consumes nothing yet, got {rebuilder['fees_consumed_cents']}"
        )
        assert_fee_ledger_closes(rebuilder)
