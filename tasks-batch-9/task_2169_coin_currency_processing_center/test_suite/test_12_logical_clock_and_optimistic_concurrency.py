"""The logical clock, the claim deadline it drives, and the two expected-version checks."""

from test_helpers import (
    ApiErrorId,
    DEFAULT_CLOCK_UTC,
    MANAGER_1,
    TELLER_1,
    adjust_inventory,
    assert_instant_equals,
    count_bag,
    create_count_session_payload,
    create_discrepancy_claim_payload,
    create_machine,
    file_claim,
    make_customer_account_holder_headers,
    make_manager_headers,
    make_teller_headers,
    read_account,
    read_bag,
    read_bag_version,
    read_coin_order,
    read_inventory_position,
    read_session,
    read_vault,
    read_vault_version,
    release_coin_order_payload,
    schedule_session,
    set_clock,
    setup_approved_coin_order,
    setup_intake_ticket,
    setup_verified_ticket,
    validate_error,
    validate_paginated,
    validate_success,
)

CURRENCY_BAG = {
    "bag_type": "CURRENCY",
    "declared_amount_cents": 100_000,
    "declared_note_count": 100,
    "declared_coin_weight_grams": 0,
}


class TestLogicalClock:
    def test_business_timestamps_read_the_default_clock_before_it_is_ever_set(self, api):
        """PRD §2.4: "Time in this system is not wall-clock time. The server holds a
        **logical clock**, and every deadline, occupancy window, and business timestamp —
        `counted_at`, `completed_at`, `filed_at`, `submitted_at`, `confirmed_at` — reads from
        it. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`, and
        it never falls back to real time."
        PRD §3.4: "On success the session moves `IN_PROGRESS → COMPLETED`, records the acting
        `X-User-ID` as `verifier_user_id`, and stamps `completed_at` from the logical clock."
        PRD §3.4: "Its `counted_amount_cents`, `counted_note_count` and
        `counted_coin_weight_grams` are copied from the session's reported readings, and
        `counted_at` is stamped with the same logical-clock instant, opening the customer's
        claim window."

        Design: Corner/endpoints/logical_clock_defaults_to_2026_08_01_before_any_set_call
        """
        scenario = setup_verified_ticket(bag_specs=[dict(CURRENCY_BAG)])
        bag = scenario["bag"]

        session = count_bag(
            bag["id"], bag["seal_number"], scenario["machine"]["id"], 100_000, 100
        )
        assert_instant_equals(session["completed_at"], DEFAULT_CLOCK_UTC, "completed_at")
        assert_instant_equals(read_bag(bag["id"])["counted_at"], DEFAULT_CLOCK_UTC, "counted_at")

    def test_a_window_starting_before_the_logical_clock_is_refused(self, api):
        """PRD §3.4: "Finally, `window_start` must be at or after the logical clock's current
        instant; a window that starts in the past is `ERR_WINDOW_IN_PAST`."
        PRD §2.4: "A `VaultManager` may advance or rewind the clock by supplying a
        `to_iso8601` instant; the response reports the new instant as `current_utc`, and no
        entity is mutated by the operation."

        Design: Corner/validations/count_session_window_in_past_rejected_against_logical_clock
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 50,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )
        bag = scenario["bag"]
        bag_version = read_bag_version(bag["id"])

        clock = set_clock("2026-08-10T00:00:00Z")
        assert_instant_equals(clock["current_utc"], "2026-08-10T00:00:00Z", "current_utc")

        response = api.create_count_session(
            create_count_session_payload(
                bag["id"],
                scenario["machine"]["id"],
                bag_version,
                "2026-08-03T09:00:00Z",
                "2026-08-03T10:00:00Z",
            ),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_WINDOW_IN_PAST.value)
        assert response.status_code == 422, (
            f"ERR_WINDOW_IN_PAST must be HTTP 422, got {response.status_code}"
        )

        _, meta = validate_paginated(
            api.list_count_sessions(
                make_manager_headers(MANAGER_1), params={"sealed_bag_id": bag["id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"No session may be booked in the past, got {meta['total_count']}"
        )

    def test_the_claim_window_is_half_open_at_twenty_four_hours(self, api):
        """PRD §3.6: "The claim window must still be open: the logical clock's current instant
        must be strictly earlier than the bag's `counted_at` plus 24 hours, so a customer has
        one full day from the moment the count completed. The window is half-open, meaning
        that filing at exactly the 24-hour boundary is already too late and is rejected with
        `ERR_CLAIM_WINDOW_CLOSED`."
        PRD §3.6: "A filed claim is created in `SUBMITTED` with `review_round` at 1,
        `filed_at` stamped from the logical clock, `resolution_amount_cents` at 0, and
        `decided_by_user_id`, `info_request_note` and `denial_reason` all null."

        Design: Corner/validations/claim_window_is_half_open_and_closes_exactly_24_hours_after_counted_at
        """
        scenario = setup_verified_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 102_500,
                    "declared_note_count": 100,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )
        bag = scenario["bag"]
        set_clock("2026-08-03T12:00:00Z")
        count_bag(
            bag["id"],
            bag["seal_number"],
            scenario["machine"]["id"],
            100_000,
            100,
            window_start="2026-08-03T13:00:00Z",
            window_end="2026-08-03T14:00:00Z",
        )
        assert_instant_equals(
            read_bag(bag["id"])["counted_at"], "2026-08-03T12:00:00Z", "counted_at"
        )

        set_clock("2026-08-04T11:59:59Z")
        inside = file_claim(bag["id"], scenario["account"]["id"], 2_500)
        assert inside["status"] == "SUBMITTED", (
            f"One second before the boundary the window is still open, got {inside['status']}"
        )
        assert_instant_equals(inside["filed_at"], "2026-08-04T11:59:59Z", "filed_at")

        set_clock("2026-08-04T12:00:00Z")
        response = api.create_discrepancy_claim(
            create_discrepancy_claim_payload(bag["id"], 1_000),
            make_customer_account_holder_headers(scenario["account"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value)
        assert response.status_code == 422, (
            f"ERR_CLAIM_WINDOW_CLOSED must be HTTP 422, got {response.status_code}"
        )

        _, meta = validate_paginated(
            api.list_discrepancy_claims(
                make_manager_headers(MANAGER_1), params={"sealed_bag_id": bag["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"Only the in-window claim may exist, got {meta['total_count']}"
        )


class TestOptimisticConcurrency:
    def test_a_stale_sealed_bag_version_is_refused_on_session_create(self, api):
        """PRD §2.8: "Creating a `CountSession` — the `POST /cash-vault/count-sessions`
        operation — requires `expected_sealed_bag_version` in the request body. This field is
        mandatory, not optional. Its value must equal the current `version` of the `SealedBag`
        named by `sealed_bag_id`. If the bag's `version` has advanced since the client last
        read it — a custody hop was appended, an earlier session was started, another session
        was scheduled — the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "Creating the new session increments the bag's `version` by 1, which is why
        two sessions cannot be scheduled back-to-back against the same observed bag version."
        PRD §3.2: "Each of these four hops increments the bag's `version` by 1, and a hop
        whose type does not match the bag's current custody position — a `PICKUP` on an
        already-received bag, for instance — is `ERR_INVALID_STATE`."

        Design: Corner/cross_cutting_complexity_layers/stale_sealed_bag_version_rejects_count_session_create
        """
        scenario = setup_intake_ticket(bag_specs=[dict(CURRENCY_BAG)])
        bag = scenario["bag"]
        second_machine = create_machine(scenario["vault"]["id"], machine_code="SORT-C52B")

        observed_version = read_bag_version(bag["id"])
        assert observed_version == 3, (
            "The bag is at version 3 after creation plus the PICKUP and VAULT_RECEIPT hops, got "
            f"{observed_version}"
        )

        first_session = schedule_session(
            bag["id"],
            scenario["machine"]["id"],
            "2026-08-03T09:00:00Z",
            "2026-08-03T10:00:00Z",
            expected_sealed_bag_version=observed_version,
        )

        response = api.create_count_session(
            create_count_session_payload(
                bag["id"],
                second_machine["id"],
                observed_version,
                "2026-08-03T11:00:00Z",
                "2026-08-03T12:00:00Z",
            ),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
        assert response.status_code == 412, (
            f"ERR_STALE_VERSION must be HTTP 412, got {response.status_code}"
        )

        assert read_session(first_session["id"])["status"] == "SCHEDULED"
        assert read_bag_version(bag["id"]) == 4, (
            "The accepted create advanced the bag to version 4 and the refused one added nothing"
        )
        _, meta = validate_paginated(
            api.list_count_sessions(
                make_manager_headers(MANAGER_1), params={"sealed_bag_id": bag["id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"Only the first session may exist, got {meta['total_count']}"
        )

    def test_a_stale_vault_version_is_refused_on_coin_release(self, api):
        """PRD §2.8: "Releasing a `CoinOrder` — the `POST
        /cash-vault/coin-orders/{id}/release` operation — requires `expected_vault_version` in
        the request body, likewise mandatory. Its value must equal the current `version` of the
        `Vault` fulfilling the order. If the vault's `version` has advanced since the client
        last read it — an inventory adjustment, a posture change, another order's approval or
        release — the release is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "Per denomination, the position's `on_hand_boxes` and `reserved_boxes` are
        each decreased by that line's `boxes_allocated`, with `available_boxes` recomputed as
        `on_hand_boxes` minus `reserved_boxes` floored at 0. The vault's
        `coin_face_value_on_hand_cents` is recomputed from the new positions."

        Design: Corner/cross_cutting_complexity_layers/stale_vault_version_rejects_coin_order_release
        """
        scenario = setup_approved_coin_order(
            {"QUARTER": 10}, {"QUARTER": 2}, allow_partial=False, approver_user_id=MANAGER_1
        )
        vault_id = scenario["vault"]["id"]
        stale_version = read_vault_version(vault_id)
        adjust_inventory(vault_id, "QUARTER", 1)

        response = api.release_coin_order(
            scenario["order"]["id"],
            release_coin_order_payload(stale_version),
            make_teller_headers(TELLER_1),
        )
        validate_error(response, ApiErrorId.ERR_STALE_VERSION.value)
        assert response.status_code == 412

        fresh_version = read_vault_version(vault_id)
        retry = api.release_coin_order(
            scenario["order"]["id"],
            release_coin_order_payload(fresh_version),
            make_teller_headers(TELLER_1),
        )
        released = validate_success(retry, 200)
        assert released["status"] == "RELEASED", f"Expected RELEASED, got {released['status']}"

        position = read_inventory_position(vault_id, "QUARTER")
        assert position["on_hand_boxes"] == 9, (
            f"11 boxes on hand minus the 2 released = 9, got {position['on_hand_boxes']}"
        )
        assert position["reserved_boxes"] == 0, (
            f"The reservation is consumed at release, got {position['reserved_boxes']}"
        )
        assert read_vault(vault_id)["coin_face_value_on_hand_cents"] == 450_000, (
            "9 quarter boxes are worth 9 * 50000 = 450000"
        )
        assert read_account(scenario["account"]["id"])["ledger_balance_cents"] == -100_000, (
            "The release debits the 2 * 50000 charge from the depositor's ledger"
        )
        assert read_coin_order(scenario["order"]["id"])["released_by_user_id"] == TELLER_1
