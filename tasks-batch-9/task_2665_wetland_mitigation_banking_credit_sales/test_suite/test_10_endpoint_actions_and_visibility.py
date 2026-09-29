"""Endpoint action semantics, ledger visibility and immediate-consistency tests.

Covers the escrow deposit action, the bank ledger projection read with its
entry_type filter, the posture-keyed refusal of quote creation, and the
requirement that every derived value a write produces is already visible in
that write's own response body and in the very next read.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_cents,
    assert_credits,
    assert_ledger_sequence,
    assert_score,
    bank_state,
    bank_version,
    create_credit_sale_payload,
    create_deposit_payload,
    get_success_data,
    make_permittee_headers,
    make_program_admin_headers,
    open_monitoring_report,
    quote_credits,
    register_permittee,
    remedial_actions_for_report,
    reserve_sale,
    review_report_payload,
    set_clock,
    setup_draft_bank,
    setup_sellable_bank,
    submit_monitoring_report,
    validate_error,
    validate_paginated,
    validate_success,
)

# A monitoring year 3 whose measurements miss three of the bank's four
# standards, so the report scores 0.6150 and its compliance status is FAIL.
FAILING_YEAR3_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 96},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 20.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 60.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]

FAILING_YEAR3_WINDOW_START = "2029-08-01T00:00:00Z"
FAILING_YEAR3_WINDOW_END = "2029-09-01T00:00:00Z"
REVIEW_CLOCK = "2029-08-15T00:00:00Z"


def _build_failing_year3_world(quoted_credits=None):
    """A sellable bank whose year-3 report is SUBMITTED and will fail review.

    When `quoted_credits` is given, one quote for that quantity is opened
    against the bank before the clock is advanced, so the failing acceptance
    has a QUOTED sale to cancel.
    """
    world = setup_sellable_bank(permittee_required_credits=20.00)
    sale = None
    if quoted_credits is not None:
        sale = quote_credits(world, quoted_credits)
    set_clock(REVIEW_CLOCK)
    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start=FAILING_YEAR3_WINDOW_START,
        window_end=FAILING_YEAR3_WINDOW_END,
        measurements_array=FAILING_YEAR3_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    return world, report, sale


class TestEscrowDepositAction:
    """POST /mitigation/permittees/{id}/deposits."""

    def test_each_deposit_raises_deposited_and_escrow_together(self):
        """Two 40,000,000-cent deposits leave the deposited total and the escrow
        balance both at 80,000,000, and walk the permit holder's version 1 -> 2 -> 3.

        The first deposit is lodged by the permit holder itself, the second by a
        ProgramAdmin: both are admissible on the same account and both return 200.

        PRD §3.1: "Escrow is funded by a deposit carrying a single `amount_cents` figure, and either a `ProgramAdmin` or the permit holder itself may lodge one; a permit holder may only fund its own account. A deposit is the system's sole money-conservation source event: the deposited total and the escrow balance both rise by the deposited amount, and the permit holder's `version` increments by one."
        PRD §2.4: "`version` is an integer that begins at 1 and increments by exactly 1 on every mutation of the row; it is the token the optimistic-concurrency machinery of §2.7 is built on."

        Design: Corner/endpoints/deposit_action_endpoint_increases_deposited_and_escrow_together
        """
        permittee = register_permittee(required_credits=20.00)
        assert permittee["version"] == 1, (
            "a freshly registered permit holder must open at version 1, got "
            f"{permittee['version']}"
        )
        assert_cents(permittee["deposited_cents"], 0, "deposited_cents at registration")
        assert_cents(
            permittee["escrow_balance_cents"], 0, "escrow_balance_cents at registration"
        )

        first = validate_success(
            api_client.create_deposit(
                permittee["id"],
                create_deposit_payload(40_000_000),
                make_permittee_headers(permittee["id"]),
            ),
            200,
        )
        assert_cents(
            first["deposited_cents"], 40_000_000, "deposited_cents after one deposit"
        )
        assert_cents(
            first["escrow_balance_cents"],
            40_000_000,
            "escrow_balance_cents after one deposit",
        )
        assert first["version"] == 2, (
            f"the first deposit must bump the permit holder to version 2, got {first['version']}"
        )

        second = validate_success(
            api_client.create_deposit(
                permittee["id"],
                create_deposit_payload(40_000_000),
                make_program_admin_headers(),
            ),
            200,
        )
        assert_cents(
            second["deposited_cents"], 80_000_000, "deposited_cents after two deposits"
        )
        assert_cents(
            second["escrow_balance_cents"],
            80_000_000,
            "escrow_balance_cents after two deposits",
        )
        assert second["version"] == 3, (
            f"the second deposit must bump the permit holder to version 3, got {second['version']}"
        )

        reread = get_success_data(
            api_client.get_permittee(
                permittee["id"], make_permittee_headers(permittee["id"])
            )
        )
        assert_cents(
            reread["escrow_balance_cents"],
            80_000_000,
            "escrow_balance_cents on the follow-up read",
        )
        assert_cents(
            reread["deposited_cents"], 80_000_000, "deposited_cents on the follow-up read"
        )

    def test_deposits_leave_the_permit_obligation_counters_untouched(self):
        """A deposit moves money only: after two 40,000,000-cent deposits the
        permit holder's assigned credits are still 0.00 and its unmet obligation
        is still the full 20.00 credits it registered with.

        PRD §3.1: "`assigned_credits` is the total requested-credit quantity across this holder's sales standing in `ASSIGNED` status, starting at 0. `unmet_requirement_credits` is the required credits minus the assigned credits, floored at zero so it can never go negative, carried to 2 decimal places, and therefore equal to the required credits at registration."

        Design: Corner/endpoints/deposit_action_endpoint_increases_deposited_and_escrow_together
        """
        permittee = register_permittee(required_credits=20.00)
        for headers in (
            make_permittee_headers(permittee["id"]),
            make_program_admin_headers(),
        ):
            validate_success(
                api_client.create_deposit(
                    permittee["id"], create_deposit_payload(40_000_000), headers
                ),
                200,
            )

        reread = get_success_data(
            api_client.get_permittee(
                permittee["id"], make_permittee_headers(permittee["id"])
            )
        )
        assert_credits(
            reread["assigned_credits"], 0.00, "assigned_credits after funding escrow"
        )
        assert_credits(
            reread["unmet_requirement_credits"],
            20.00,
            "unmet_requirement_credits after funding escrow",
        )


def _bank_with_reserved_hold(credits_requested=8.00):
    """A sellable bank (14.82 credits released) carrying one reserved sale, so
    its ledger holds a GENERATED, a RELEASED and a HOLD_PLACED entry."""
    world = setup_sellable_bank(permittee_required_credits=20.00)
    sale = quote_credits(world, credits_requested)
    reserve_sale(world, sale["id"])
    return world, sale


class TestBankLedgerRead:
    """GET /mitigation/banks/{id}/ledger."""

    def test_ledger_read_is_ordered_by_sequence_number_ascending(self):
        """The unfiltered ledger of a bank that has executed its instrument,
        released 14.82 credits and placed an 8.00-credit hold returns exactly
        three rows in sequence order 1, 2, 3 — GENERATED, RELEASED, HOLD_PLACED —
        with running balances 0.00, 14.82 and 6.82.

        PRD §2.11: "The bank's ledger read is ordered by `sequence_number` ascending rather than by `created_at`, and accepts an optional `entry_type` filter."
        PRD §2.11: "Each entry belongs to exactly one bank through its `bank_id` and carries a `sequence_number` that starts at 1 for that bank's first entry and increases by one for each subsequent append, in append order."
        PRD §2.11: "`balance_after` records the bank's available credits immediately after the entry was appended, and is therefore the running accumulation of every `delta_credits` from sequence number 1 through this entry inclusive."

        Design: Corner/endpoints/ledger_read_filters_by_entry_type_and_orders_by_sequence_number
        """
        world, _sale = _bank_with_reserved_hold()

        rows, meta = validate_paginated(
            api_client.list_bank_ledger(
                world["bank"]["id"],
                world["sponsor_headers"],
                params={"limit": 100, "offset": 0},
            )
        )
        assert meta["total_count"] == 3, (
            f"the bank's ledger must hold exactly 3 rows, got {meta['total_count']}"
        )
        assert meta["has_more"] is False, "a 3-row ledger read at limit 100 has no more pages"
        assert [row["sequence_number"] for row in rows] == [1, 2, 3], (
            "ledger rows must arrive in ascending sequence_number order, got "
            f"{[row['sequence_number'] for row in rows]}"
        )
        assert [row["entry_type"] for row in rows] == [
            "GENERATED",
            "RELEASED",
            "HOLD_PLACED",
        ], f"unexpected ledger shape: {[row['entry_type'] for row in rows]}"
        for row, expected_balance in zip(rows, [0.00, 14.82, 6.82]):
            assert_credits(
                row["balance_after"],
                expected_balance,
                f"balance_after of the {row['entry_type']} entry",
            )
        assert_ledger_sequence(rows)

    def test_entry_type_filter_narrows_the_ledger_without_renumbering_it(self):
        """Filtering the same ledger by entry_type=HOLD_PLACED returns the single
        row whose sequence_number is still 3, whose delta is -8.00 and whose
        balance_after is 6.82, attributed to the credit sale that placed the hold;
        entry_type=SOLD matches nothing at all.

        PRD §2.11: "The bank's ledger read is ordered by `sequence_number` ascending rather than by `created_at`, and accepts an optional `entry_type` filter."
        PRD §2.3: "Four pagination fields accompany every list response inside `meta`: the echoed `limit`, the echoed `offset`, `total_count` carrying the number of rows matching the filter before pagination is applied, and `has_more` indicating whether any rows remain beyond the current page."
        PRD §3.8: "Reservation stamps `hold_start_at` with the current clock and `hold_expires_at` 30 days later, appends a `HOLD_PLACED` entry carrying the requested credits as a negative delta and attributed through a source entity type of `CREDIT_SALE` and the sale's own identifier, recomputes the bank's credits on hold and available credits and its posture, recomputes the bank's `open_quote_count`, and increments the bank's `version` by one."

        Design: Corner/endpoints/ledger_read_filters_by_entry_type_and_orders_by_sequence_number
        """
        world, sale = _bank_with_reserved_hold()

        held, held_meta = validate_paginated(
            api_client.list_bank_ledger(
                world["bank"]["id"],
                world["sponsor_headers"],
                params={"entry_type": "HOLD_PLACED", "limit": 100, "offset": 0},
            )
        )
        assert held_meta["total_count"] == 1, (
            f"exactly one HOLD_PLACED entry is expected, got {held_meta['total_count']}"
        )
        entry = held[0]
        assert entry["sequence_number"] == 3, (
            "the filter must not renumber the ledger: the HOLD_PLACED entry keeps "
            f"sequence_number 3, got {entry['sequence_number']}"
        )
        assert_credits(entry["delta_credits"], -8.00, "HOLD_PLACED delta_credits")
        assert_credits(entry["balance_after"], 6.82, "HOLD_PLACED balance_after")
        assert entry["source_entity_type"] == "CREDIT_SALE", (
            "a reservation hold is attributed to the credit sale, got "
            f"{entry['source_entity_type']}"
        )
        assert entry["source_id"] == sale["id"], (
            "the HOLD_PLACED entry must name the reserving sale as its source"
        )

        sold, sold_meta = validate_paginated(
            api_client.list_bank_ledger(
                world["bank"]["id"],
                world["sponsor_headers"],
                params={"entry_type": "SOLD", "limit": 100, "offset": 0},
            )
        )
        assert sold_meta["total_count"] == 0, (
            f"no sale has settled, so no SOLD entry exists, got {sold_meta['total_count']}"
        )
        assert sold == [], f"the SOLD-filtered ledger page must be empty, got {sold}"

        bank = bank_state(world)
        assert_credits(bank["credits_on_hold"], 8.00, "credits_on_hold after the reservation")
        assert_credits(bank["credits_available"], 6.82, "credits_available after the reservation")


class TestQuoteCreationPostureGate:
    """POST /mitigation/credit-sales under the derived sales-posture gate."""

    def test_quote_against_a_draft_bank_is_refused_as_frozen(self):
        """A bank still sitting in DRAFT carries a posture of FROZEN, so a quote
        against it is refused with the FROZEN-keyed code at HTTP 409 — not the
        RESTRICTED or SOLD_OUT variant — and nothing is written: no credit sale
        exists, the open quote count stays 0 and the bank stays at version 1.

        PRD §3.2: "A newly registered bank opens in `DRAFT` status with a `sales_posture` of `FROZEN`, and every credit aggregate — `total_authorized_credits`, `credits_released`, `credits_sold`, `credits_on_hold` and `credits_available` — initialised to 0.00."
        PRD §2.8: "Quoting and reserving both require a posture of exactly `OPEN`."
        PRD §2.8: "The rejection code is keyed to the offending posture value rather than to the operation: a `FROZEN` bank yields `ERR_BANK_SALES_FROZEN`, a `RESTRICTED` bank yields `ERR_BANK_SALES_RESTRICTED`, and a `SOLD_OUT` bank blocking a quote or a reservation yields `ERR_BANK_SOLD_OUT`. All three carry HTTP 409."

        Design: Corner/endpoints/quote_creation_on_a_frozen_bank_is_rejected
        """
        world = setup_draft_bank(permittee_required_credits=20.00)
        assert world["bank"]["status"] == "DRAFT", "the bank must open in DRAFT"
        assert world["bank"]["sales_posture"] == "FROZEN", (
            f"a DRAFT bank's posture is FROZEN, got {world['bank']['sales_posture']}"
        )
        assert world["bank"]["version"] == 1, "a freshly registered bank opens at version 1"

        response = api_client.create_credit_sale(
            create_credit_sale_payload(
                world["bank"]["id"],
                world["permittee"]["id"],
                3.00,
                world["bank"]["version"],
                impact_huc8_code=world["bank"]["site_huc8_code"],
            ),
            world["permittee_headers"],
        )
        validate_error(response, ApiErrorId.ERR_BANK_SALES_FROZEN, 409)

        sales, sales_meta = validate_paginated(
            api_client.list_credit_sales(
                world["admin_headers"],
                params={"bank_id": world["bank"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert sales_meta["total_count"] == 0, (
            f"the refused quote must not create a credit sale, got {sales_meta['total_count']}"
        )
        assert sales == [], f"no credit sale row may exist, got {sales}"

        bank = bank_state(world)
        assert bank["sales_posture"] == "FROZEN", "the posture is unchanged by the refusal"
        assert bank["open_quote_count"] == 0, (
            f"the refused quote must not raise open_quote_count, got {bank['open_quote_count']}"
        )
        assert bank["version"] == 1, (
            f"the refused quote must not bump the bank's version, got {bank['version']}"
        )

    def test_frozen_posture_is_reported_ahead_of_a_stale_bank_version(self):
        """A quote against the same DRAFT bank carrying a bank version the caller
        never observed still surfaces the posture code, because the posture gate is
        evaluated before the optimistic-concurrency check.

        PRD §2.10: "After identity comes state: first whether the target row is in a state from which the requested transition exists at all, returning the entity-specific code (`ERR_BANK_STATE_INVALID`, `ERR_PROSPECTUS_STATE_INVALID`, `ERR_WORK_PLAN_STATE_INVALID`, `ERR_MILESTONE_STATE_INVALID`, `ERR_REPORT_STATE_INVALID`, `ERR_REMEDIAL_STATE_INVALID` or `ERR_SALE_STATE_INVALID`); then the sales-posture gate of §2.8; then the optimistic-concurrency check (`ERR_STALE_BANK_VERSION`)."
        PRD §2.8: "The rejection code is keyed to the offending posture value rather than to the operation: a `FROZEN` bank yields `ERR_BANK_SALES_FROZEN`, a `RESTRICTED` bank yields `ERR_BANK_SALES_RESTRICTED`, and a `SOLD_OUT` bank blocking a quote or a reservation yields `ERR_BANK_SOLD_OUT`. All three carry HTTP 409."

        Design: Corner/endpoints/quote_creation_on_a_frozen_bank_is_rejected
        """
        world = setup_draft_bank(permittee_required_credits=20.00)
        stale_version = world["bank"]["version"] + 41
        assert stale_version != bank_version(world), "the supplied token must be stale"

        response = api_client.create_credit_sale(
            create_credit_sale_payload(
                world["bank"]["id"],
                world["permittee"]["id"],
                3.00,
                stale_version,
                impact_huc8_code=world["bank"]["site_huc8_code"],
            ),
            world["permittee_headers"],
        )
        validate_error(response, ApiErrorId.ERR_BANK_SALES_FROZEN, 409)

        bank = bank_state(world)
        assert bank["version"] == 1, (
            f"the refused quote must not bump the bank's version, got {bank['version']}"
        )
        assert bank["open_quote_count"] == 0, (
            f"the refused quote must not raise open_quote_count, got {bank['open_quote_count']}"
        )

    def test_quote_is_refused_while_a_remedial_action_stands_open(self):
        """An accepted year-3 report whose compliance status is FAIL opens a
        remedial action in OPEN, which drives the bank's posture to RESTRICTED even
        though the bank's released credits are neither sold nor held. A quote is then
        refused with the RESTRICTED-keyed code at HTTP 409 and no sale row is written.

        PRD §2.8: "Otherwise, if at least one remedial action reachable through the bank's monitoring reports is in `OPEN`, `WORK_SUBMITTED`, `REINSPECTION` or `FAILED`, the posture is again `RESTRICTED`; cleared actions are ignored by this test."
        PRD §2.8: "The rejection code is keyed to the offending posture value rather than to the operation: a `FROZEN` bank yields `ERR_BANK_SALES_FROZEN`, a `RESTRICTED` bank yields `ERR_BANK_SALES_RESTRICTED`, and a `SOLD_OUT` bank blocking a quote or a reservation yields `ERR_BANK_SOLD_OUT`. All three carry HTTP 409."
        PRD §3.7: "If the bank has never had an accepted report before, this acceptance additionally carries the bank `INSTRUMENT_EXECUTED → MONITORING`."

        Design: Corner/endpoints/quote_creation_while_a_remedial_action_is_open_is_rejected
        """
        world, report, _sale = _build_failing_year3_world()

        accepted = validate_success(
            api_client.review_monitoring_report(
                report["id"], review_report_payload("ACCEPT"), world["member_headers"][1]
            ),
            200,
        )
        assert accepted["review_status"] == "ACCEPTED", (
            f"the report must be accepted, got {accepted['review_status']}"
        )
        assert accepted["compliance_status"] == "FAIL", (
            f"the year-3 measurements must score FAIL, got {accepted['compliance_status']}"
        )

        actions = remedial_actions_for_report(world, report["id"])
        assert len(actions) == 1, (
            f"the failing acceptance must open exactly one remedial action, got {len(actions)}"
        )
        assert actions[0]["status"] == "OPEN", (
            f"a new remedial action opens in OPEN, got {actions[0]['status']}"
        )
        assert actions[0]["round_number"] == 1, (
            f"a new remedial action opens at round_number 1, got {actions[0]['round_number']}"
        )

        bank = bank_state(world)
        assert bank["status"] == "MONITORING", (
            f"the first accepted report carries the bank to MONITORING, got {bank['status']}"
        )
        assert bank["sales_posture"] == "RESTRICTED", (
            "an open remedial action forces the posture to RESTRICTED, got "
            f"{bank['sales_posture']}"
        )

        response = api_client.create_credit_sale(
            create_credit_sale_payload(
                world["bank"]["id"],
                world["permittee"]["id"],
                3.00,
                bank["version"],
                impact_huc8_code=bank["site_huc8_code"],
            ),
            world["permittee_headers"],
        )
        validate_error(response, ApiErrorId.ERR_BANK_SALES_RESTRICTED, 409)

        sales, sales_meta = validate_paginated(
            api_client.list_credit_sales(
                world["admin_headers"],
                params={"bank_id": world["bank"]["id"], "limit": 10, "offset": 0},
            )
        )
        assert sales_meta["total_count"] == 0, (
            f"the refused quote must not create a credit sale, got {sales_meta['total_count']}"
        )
        assert sales == [], f"no credit sale row may exist, got {sales}"


class TestFailingAcceptanceIsImmediatelyVisible:
    """POST /mitigation/monitoring-reports/{id}/review — consistency is immediate."""

    def test_review_response_itself_carries_the_scored_outcome(self):
        """The 200 body of the review call already carries review_status ACCEPTED,
        compliance_status FAIL and attainment_score 0.6150, with the three missed
        standards listed in ascending code order — no follow-up read is needed to
        observe them, and a follow-up read repeats exactly the same values.

        The score is the sum of the per-standard contributions, each rounded to 4dp
        before summation: 96/120 capped at 1.0 gives 0.8 * 0.300 = 0.2400; an invasive
        cover of 20.0 against a threshold of 10.0 overshoots by 100 percent so its
        ratio floors at 0.0 and contributes 0.0000; 60.0/80.0 gives 0.75 * 0.300 =
        0.2250; a stem density of exactly 400 meets its threshold and contributes
        1.0 * 0.150 = 0.1500. The four contributions total 0.6150 over a weight
        denominator of 1.000.

        PRD §3.7: "Accepting is the branch with teeth. The report's review status advances `SUBMITTED → ACCEPTED`, `reviewed_by_member_id` records the acting member, `reviewed_at` is stamped, and the report is scored against the standards effective for its monitoring year."
        PRD §3.7: "Each standard's contribution is its ratio multiplied by its weight, rounded half up to 4 decimal places; this per-standard rounding is pinned and precedes summation."
        PRD §3.7: "`failed_standard_codes` lists the codes of the standards not met, in ascending code order."
        PRD §3.7: "The compliance status then follows from those two outputs in order: it is `PASS` when no standard failed, otherwise `PARTIAL` when the attainment score is at least 0.85 — the boundary is inclusive — and otherwise `FAIL`."

        Design: Corner/consistency_model/cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        world, report, _sale = _build_failing_year3_world(quoted_credits=3.00)

        reviewed = validate_success(
            api_client.review_monitoring_report(
                report["id"], review_report_payload("ACCEPT"), world["member_headers"][1]
            ),
            200,
        )
        assert reviewed["review_status"] == "ACCEPTED", (
            "the review response body must already read ACCEPTED, got "
            f"{reviewed['review_status']}"
        )
        assert reviewed["compliance_status"] == "FAIL", (
            "the review response body must already read FAIL, got "
            f"{reviewed['compliance_status']}"
        )
        assert_score(reviewed["attainment_score"], 0.6150, "attainment_score in the review body")
        assert reviewed["failed_standard_codes"] == [
            "HYDROPERIOD_DAYS",
            "INVASIVE_COVER_PCT",
            "NATIVE_COVER_PCT",
        ], f"unexpected failed_standard_codes: {reviewed['failed_standard_codes']}"

        reread = get_success_data(
            api_client.get_monitoring_report(report["id"], world["sponsor_headers"])
        )
        assert reread["review_status"] == "ACCEPTED", "the follow-up read must agree"
        assert reread["compliance_status"] == "FAIL", "the follow-up read must agree"
        assert_score(reread["attainment_score"], 0.6150, "attainment_score on the follow-up read")

    def test_next_reads_already_show_the_cancelled_sale_and_the_new_action(self):
        """With no intervening write, no retry and no clock advance, the reads that
        immediately follow the failing acceptance already show the QUOTED sale
        cancelled for BANK_POSTURE_RESTRICTED, the bank's posture at RESTRICTED with
        an open quote count of 0, and one remedial action opened at round 1 whose
        due date is the review clock plus 365 days.

        PRD §3.7: "The third hop acts on that posture change: every credit sale of the bank standing in `QUOTED` or `RESERVED` is cancelled with a `cancelled_reason` of `BANK_POSTURE_RESTRICTED` and a `cancelled_at` stamp, and each formerly reserved sale appends a `HOLD_RELEASED` entry that restores its held credits to the bank's available pool."
        PRD §3.7: "It opens in `OPEN` status with `round_number` at 1, its `monitoring_report_id` naming the failing report, its `opened_at` stamped with the logical clock, its `due_at` set to that clock plus 365 days, and its `corrective_scope` auto-generated as the literal text `REMEDIATE: ` followed by the failed standard codes joined by commas in the same ascending order they were listed in."
        PRD §3.8: "That counter is a derived tally rather than a hand-maintained number: it is the count of the bank's credit sales standing in either `QUOTED` or `RESERVED`, so a quote that is placed on hold continues to be counted, and a sale leaves the tally only when it settles, is withdrawn or expires."

        Design: Corner/consistency_model/cascade_is_visible_in_the_same_response_and_immediate_reads
        """
        world, report, sale = _build_failing_year3_world(quoted_credits=3.00)
        assert sale["status"] == "QUOTED", "the sale must be standing in QUOTED"

        validate_success(
            api_client.review_monitoring_report(
                report["id"], review_report_payload("ACCEPT"), world["member_headers"][1]
            ),
            200,
        )

        sale_after = get_success_data(
            api_client.get_credit_sale(sale["id"], world["permittee_headers"])
        )
        assert sale_after["status"] == "CANCELLED", (
            f"the QUOTED sale must be cancelled by the cascade, got {sale_after['status']}"
        )
        assert sale_after["cancelled_reason"] == "BANK_POSTURE_RESTRICTED", (
            "the cascade records BANK_POSTURE_RESTRICTED as the reason, got "
            f"{sale_after['cancelled_reason']}"
        )
        assert sale_after["cancelled_at"] is not None, "cancelled_at must be stamped"

        bank = bank_state(world)
        assert bank["sales_posture"] == "RESTRICTED", (
            f"the posture must already read RESTRICTED, got {bank['sales_posture']}"
        )
        assert bank["open_quote_count"] == 0, (
            "the cancelled quote must already have left the open-quote tally, got "
            f"{bank['open_quote_count']}"
        )

        actions, actions_meta = validate_paginated(
            api_client.list_remedial_actions(
                world["chair_headers"],
                params={"monitoring_report_id": report["id"], "limit": 10, "offset": 0},
            )
        )
        assert actions_meta["total_count"] == 1, (
            f"exactly one remedial action must exist, got {actions_meta['total_count']}"
        )
        action = actions[0]
        assert action["status"] == "OPEN", f"the action opens in OPEN, got {action['status']}"
        assert action["round_number"] == 1, (
            f"the action opens at round_number 1, got {action['round_number']}"
        )
        assert action["monitoring_report_id"] == report["id"], (
            "the action must name the failing report"
        )
        assert action["opened_at"].startswith("2029-08-15T00:00:00"), (
            f"opened_at is stamped with the review clock, got {action['opened_at']}"
        )
        assert action["due_at"].startswith("2030-08-15T00:00:00"), (
            "due_at is the review clock plus 365 days, got " f"{action['due_at']}"
        )
        prefix = "REMEDIATE: "
        assert action["corrective_scope"].startswith(prefix), (
            f"corrective_scope must begin with the literal {prefix!r}, got "
            f"{action['corrective_scope']!r}"
        )
        listed = [
            code.strip() for code in action["corrective_scope"][len(prefix):].split(",")
        ]
        assert listed == [
            "HYDROPERIOD_DAYS",
            "INVASIVE_COVER_PCT",
            "NATIVE_COVER_PCT",
        ], f"corrective_scope must list the failed codes in ascending order, got {listed}"


def _quote_six_secondary_credits():
    """Open a 6.00-credit quote against the canonical DEPRESSIONAL bank for an
    impact in 03130003 — inside the service area but not the site watershed."""
    world = setup_sellable_bank(
        permittee_required_credits=12.00, permittee_impact_huc8_code="03130003"
    )
    response = api_client.create_credit_sale(
        create_credit_sale_payload(
            world["bank"]["id"],
            world["permittee"]["id"],
            6.00,
            bank_version(world),
            impact_huc8_code="03130003",
        ),
        world["permittee_headers"],
    )
    return world, response


class TestQuoteCreationResponseIsComplete:
    """POST /mitigation/credit-sales — every derived figure lands in the 201 body."""

    def test_creation_body_carries_the_cap_bound_price_tier_and_demand_index(self):
        """The 201 body of the quote already carries service_area_tier SECONDARY,
        quoted_demand_index 0.0000 and the cap-bound quoted_price_cents 26,001,500.

        The bank is DEPRESSIONAL, so the base price is 3,800,000 cents per credit.
        The 6.00 requested credits split 5.00 at the 1.000 multiplier, contributing
        19,000,000 cents, and 1.00 at the 0.950 multiplier, contributing 3,610,000
        cents, for a tiered subtotal of 22,610,000 cents. The SECONDARY tier adds
        12 percent and the endowment funded at 28,420,000 of 113,680,000 adds a
        further 8 percent, so the single-rounded premium is 4,522,000 cents. The bank
        has settled nothing, so the demand index is 0.0000 and the demand adjustment
        is 0, leaving a gross price of 27,132,000 cents. The cap of 22,610,000 * 1.15
        is 26,001,500 cents, which is the smaller of the two and therefore the price.

        PRD §3.8: "Pricing starts from the bank's hydrogeomorphic class, which fixes a base price per credit: 4,250,000 cents for `RIVERINE`, 3,800,000 cents for `DEPRESSIONAL`, 3,600,000 cents for `SLOPE`, 3,300,000 cents for `FLATS` and 5,100,000 cents for `ESTUARINE`."
        PRD §3.8: "Each tier carrying a non-zero quantity contributes its quantity multiplied by the base price and by its multiplier, rounded half up to whole cents, and the tiered subtotal is the sum of those already-rounded tier amounts; a tier carrying zero credits contributes nothing and is not rounded at all."
        PRD §3.8: "Finally a ceiling is applied: the price cap is the tiered subtotal multiplied by 1.15, rounded half up to whole cents, and the price charged is whichever of the gross price and the cap is smaller."
        PRD §3.8: "The impact watershed must fall inside the bank's service area, or the quote is rejected with `ERR_OUTSIDE_SERVICE_AREA`: this is the service-area limitation that gives mitigation banking its geographic integrity, and it is also what fixes the sale's `service_area_tier`, which is `PRIMARY` when the impact watershed is the bank's own site watershed and `SECONDARY` when it is any other member of the bank's service-area list."
        PRD §3.8: "Two figures are frozen onto it at creation: `quoted_demand_index`, a snapshot of the bank's service-area demand pressure, and `quoted_price_cents`, the quoted-variant price."

        Design: Corner/consistency_model/quote_creation_response_carries_the_computed_price_immediately
        """
        _world, response = _quote_six_secondary_credits()
        sale = validate_success(response, 201)

        assert sale["service_area_tier"] == "SECONDARY", (
            "an impact in 03130003 is inside the service area but is not the site "
            f"watershed, so the tier is SECONDARY, got {sale['service_area_tier']}"
        )
        assert_score(sale["quoted_demand_index"], 0.0000, "quoted_demand_index in the 201 body")
        assert_cents(sale["quoted_price_cents"], 26_001_500, "quoted_price_cents in the 201 body")
        assert sale["status"] == "QUOTED", (
            f"a new quote opens in QUOTED, got {sale['status']}"
        )

    def test_quote_read_repeats_the_creation_figures_and_the_bank_counts_it(self):
        """A read of the same sale returns the identical quoted price and a status of
        QUOTED, with the settlement and hold fields still null, while the bank's
        open quote count already reads 1 and no credits are on hold.

        PRD §3.8: "A quote opens in `QUOTED` status with `hold_start_at`, `hold_expires_at`, `executed_price_cents`, `executed_at`, `assigned_at`, `assignment_reference`, `cancelled_reason` and `cancelled_at` all null, raises the bank's `open_quote_count` by one and increments the bank's `version` by one."
        PRD §3.8: "The quoted variant runs at quote creation, using the bank's stewardship funding state and demand index as they stand at that moment, and the figure it produces never changes afterwards."

        Design: Corner/consistency_model/quote_creation_response_carries_the_computed_price_immediately
        """
        world, response = _quote_six_secondary_credits()
        created = validate_success(response, 201)

        read_back = get_success_data(
            api_client.get_credit_sale(created["id"], world["permittee_headers"])
        )
        assert_cents(
            read_back["quoted_price_cents"],
            created["quoted_price_cents"],
            "quoted_price_cents on the follow-up read",
        )
        assert_cents(
            read_back["quoted_price_cents"], 26_001_500, "quoted_price_cents on the follow-up read"
        )
        assert read_back["status"] == "QUOTED", (
            f"the sale must still be QUOTED, got {read_back['status']}"
        )
        for field in ("executed_price_cents", "hold_start_at", "hold_expires_at"):
            assert read_back[field] is None, (
                f"{field} must still be null on a quote, got {read_back[field]!r}"
            )

        bank = bank_state(world)
        assert bank["open_quote_count"] == 1, (
            f"the new quote must already be counted, got {bank['open_quote_count']}"
        )
        assert_credits(
            bank["credits_on_hold"], 0.00, "credits_on_hold behind an unreserved quote"
        )
