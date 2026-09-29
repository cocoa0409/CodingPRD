"""Endpoint-shape corners: partial update, branch-selecting action, referential
link, derived read and conditional waiver.

Each test here pins what one operation of the HTTP surface does with the body it
is handed: an adjustment that must overwrite only the fields it was given, an
acknowledgement whose target state is chosen by a payload field, a create that
joins three referenced rows, a ledger read whose rows must reproduce the money
calculation exactly, and a reissue whose fee waiver is conditional on the reason
already recorded on the row.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures
from test_helpers.api_errors import (
    ERR_ORDER_BATCH_NOT_FOUND,
    ERR_REPLACEMENT_FEE_NOT_WAIVABLE,
)
from test_helpers.test_users import (
    PROGRAM_ADMIN,
    make_order_desk_headers,
    make_payroll_processor_headers,
)

WINDOW_CUTOFF_AT = "2026-08-20T00:00:00Z"
COVERAGE_START_AT = "2026-08-01T00:00:00Z"
COVERAGE_END_AT = "2026-08-31T00:00:00Z"

# Syntactically well-formed but belonging to no OrderBatch row.
UNKNOWN_ORDER_BATCH_ID = "00000000-0000-4000-8000-000000000999"

SEAL_USER_ID = "desk-a"
RELEASE_USER_ID = "desk-b"


# ---------------------------------------------------------------------------
# Composite preconditions used by more than one test in this module.
# ---------------------------------------------------------------------------
def _link_ready_program(api):
    """A PENDING election awaiting media, an eligible medium and an OPEN batch that
    still carries no lines, so a single create can be aimed at all three rows."""
    built = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={"legal_name": "Link Check Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
    )
    media = fixtures.make_transit_media(
        api,
        sku="AUS-LK",
        media_type="PAPER_PASS",
        region_code=constants.REGION_AUS,
        eligible_category_type="TRANSIT_PASS",
        unit_price_cents=3000,
    )
    election = fixtures.make_election(
        api,
        built["employee"]["id"],
        built["window"]["id"],
        built["category"]["id"],
        built["account"]["id"],
        pretax_amount_cents=3000,
        posttax_amount_cents=0,
        transit_media_id=media["id"],
        media_quantity=1,
    )
    batch = fixtures.make_open_batch(
        api, built["window"]["id"], constants.REGION_AUS, "desk-link"
    )
    built["media"] = media
    built["election"] = election
    built["batch"] = batch
    return built


def _undelivered_line(api, reason):
    """One shipped media line reported UNDELIVERED with the given reason, over an
    account seeded with 10000 cents of carried-in balance."""
    chain = fixtures.make_procurement_chain(
        api,
        region_code=constants.REGION_AUS,
        media_quantity=1,
        pretax_amount_cents=3000,
        unit_price_cents=3000,
        seal_user_id=SEAL_USER_ID,
        release_user_id=RELEASE_USER_ID,
        stop_after="shipped",
        employer_overrides={"legal_name": "Waiver Rules Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        account_overrides={"opening_rollover_cents": 10000},
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
        media_overrides={
            "sku": "AUS-WV",
            "replacement_fee_cents": 500,
            "requires_physical_fulfillment": True,
        },
        coverage_start_at=COVERAGE_START_AT,
        coverage_end_at=COVERAGE_END_AT,
    )
    chain["order"] = validate_success(
        api.report_media_order_undelivered(
            chain["order"]["id"],
            {"reason": reason},
            make_order_desk_headers(SEAL_USER_ID),
        )
    )
    return chain


# ---------------------------------------------------------------------------
# The adjustment operation is a partial update, not a replacement
# ---------------------------------------------------------------------------
def test_01_employer_adjustment_overwrites_only_the_supplied_setup_fields(api):
    """A two-field adjustment against an ACTIVE program overwrites exactly the two
    fields it names and leaves every other setup value byte-identical.

    PRD: "All eight of these setup values — the two group limits, the program cap, the ratio cap, the two policy flags, the rollover cap and the grace period — remain editable while the program is `DRAFT` or `ACTIVE` through the employer adjustment operation, which overwrites only the fields supplied and advances `Employer.version` by 1."

    PRD: "A newly registered employer lands in `program_status` `DRAFT` with `ordinance_mandate_status` `UNASSESSED`, `total_pretax_committed_cents` and `enrolled_employee_count` both at zero, and `version` 1."

    PRD: "On success the employer's `program_status` becomes `ACTIVE`, `enrolled_employee_count` is recomputed as the number of that employer's employees whose `status` is `ACTIVE`, and `Employer.version` advances by 1."

    PRD: "`spill_policy` decides what happens when a pre-tax request exceeds the available exclusion headroom and defaults to `SPILL_TO_POSTTAX`, the alternative being `REJECT_OVERAGE`."

    Design: Corner/endpoints/employer_patch_overwrites_only_the_supplied_setup_fields
    """
    created = fixtures.make_draft_employer(
        api,
        PROGRAM_ADMIN,
        legal_name="Patch Me Co",
        region_code=constants.REGION_SEA,
        transit_group_limit_cents=30000,
        parking_group_limit_cents=28000,
        program_cap_cents=5000000,
        pretax_ratio_cap_pct=90,
        rollover_policy="CAP_ROLLOVER",
        rollover_cap_cents=9000,
    )
    assert created["version"] == 1
    assert created["program_status"] == "DRAFT"
    assert created["spill_policy"] == "SPILL_TO_POSTTAX"

    validate_success(
        api.create_benefit_category(
            factories.benefit_category_payload(
                created["id"],
                category_type="TRANSIT_PASS",
                monthly_exclusion_limit_cents=30000,
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    activated = validate_success(api.activate_employer(created["id"], PROGRAM_ADMIN))
    assert activated["program_status"] == "ACTIVE"
    assert activated["version"] == 2

    fixtures.make_employee(
        api,
        created["id"],
        PROGRAM_ADMIN,
        external_ref="SEA-PM-1",
        work_region_code=constants.REGION_SEA,
    )
    before = fixtures.read_employer(api, created["id"])
    assert before["enrolled_employee_count"] == 1

    after = validate_success(
        api.patch_employer(
            created["id"],
            {"spill_policy": "REJECT_OVERAGE", "program_cap_cents": 7000},
            PROGRAM_ADMIN,
        )
    )

    # The two supplied fields moved.
    assert after["spill_policy"] == "REJECT_OVERAGE"
    assert after["program_cap_cents"] == 7000

    # Everything the body did not name is byte-identical.
    untouched = (
        "legal_name",
        "region_code",
        "transit_group_limit_cents",
        "parking_group_limit_cents",
        "pretax_ratio_cap_pct",
        "rollover_policy",
        "rollover_cap_cents",
        "forfeiture_grace_days",
        "enrolled_employee_count",
        "program_status",
        "ordinance_mandate_status",
        "total_pretax_committed_cents",
        "created_at",
    )
    assertions.assert_unchanged(
        {field: before[field] for field in untouched},
        {field: after[field] for field in untouched},
        *untouched,
    )
    assert after["transit_group_limit_cents"] == 30000
    assert after["parking_group_limit_cents"] == 28000
    assert after["pretax_ratio_cap_pct"] == 90
    assert after["rollover_policy"] == "CAP_ROLLOVER"
    assert after["rollover_cap_cents"] == 9000
    assert after["enrolled_employee_count"] == 1
    assert after["program_status"] == "ACTIVE"
    assert after["version"] == before["version"] + 1


# ---------------------------------------------------------------------------
# One action endpoint, two target states chosen by the payload
# ---------------------------------------------------------------------------
def test_02_payroll_acknowledge_with_a_rejected_outcome_takes_the_rejected_branch(api):
    """The acknowledgement outcome selects the target state: `REJECTED` must land the
    transmitted file in REJECTED rather than ACKNOWLEDGED, store the supplied code,
    keep the transmit stamp and leave the derived money rollup alone.

    PRD: "An `outcome` of `ACCEPTED` moves the file `TRANSMITTED → ACKNOWLEDGED`; an `outcome` of `REJECTED` moves it `TRANSMITTED → REJECTED`. Both are terminal, both store the supplied `acknowledgement_code` (leaving it null when the field is omitted), and both advance `PayrollFile.version` by 1."

    PRD: "Only a `PayrollProcessor` transmits. Transmission requires the file's `status` to be `GENERATED` and its `participant_count` to be at least 1 — an empty file is never sent — and moves it `GENERATED → TRANSMITTED`, stamping `transmitted_at` with the current logical clock instant."

    PRD: "**Step two** derives the administration fee from headcount alone: `admin_fee_cents` is the larger of a 5000-cent monthly minimum — fifty dollars — and the participant count multiplied by 425 cents per participant."

    PRD: "**Step five** sets `employer_charge_cents` to `pre_waiver_charge_cents` minus `fee_waiver_cents`, and the tier is **never** re-derived from that final figure — a charge that drops below a tier boundary because of its own waiver keeps the tier it was assigned."

    Design: Corner/endpoints/payroll_acknowledge_with_rejected_outcome_takes_the_rejected_branch
    """
    built = fixtures.make_funded_election(
        api,
        region_code=constants.REGION_AUS,
        pretax_amount_cents=5000,
        employer_overrides={"legal_name": "Ack Branch Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
    )
    assertions.assert_election_axes(built["election"], "FUNDED", "NOT_REQUIRED")

    payroll_headers = make_payroll_processor_headers("pay-ack")
    draft = fixtures.make_draft_payroll_file(
        api, built["employer"]["id"], "2026-08", "pay-ack"
    )
    assert draft["version"] == 1

    generated = validate_success(api.generate_payroll_file(draft["id"], payroll_headers))
    assert generated["participant_count"] == 1
    assert generated["total_pretax_cents"] == 5000
    assert generated["total_posttax_cents"] == 0
    assert generated["admin_fee_cents"] == 5000
    assert generated["pre_waiver_charge_cents"] == 10000
    assert generated["fee_waiver_cents"] == 0
    assert generated["employer_charge_cents"] == 10000

    transmitted = validate_success(api.transmit_payroll_file(draft["id"], payroll_headers))
    assert transmitted["status"] == "TRANSMITTED"
    assert transmitted["version"] == 3
    assert transmitted["transmitted_at"] is not None

    acknowledged = validate_success(
        api.acknowledge_payroll_file(
            draft["id"],
            {"outcome": "REJECTED", "acknowledgement_code": "E42-BAD-FORMAT"},
            payroll_headers,
        )
    )

    assert acknowledged["status"] == "REJECTED"
    assert acknowledged["status"] != "ACKNOWLEDGED"
    assert acknowledged["acknowledgement_code"] == "E42-BAD-FORMAT"
    assert acknowledged["transmitted_at"] == transmitted["transmitted_at"]
    assert acknowledged["version"] == 4

    money = (
        "participant_count",
        "total_pretax_cents",
        "total_posttax_cents",
        "admin_fee_cents",
        "pre_waiver_charge_cents",
        "fee_waiver_cents",
        "employer_charge_cents",
        "transmitted_at",
    )
    assertions.assert_unchanged(
        {field: transmitted[field] for field in money},
        {field: acknowledged[field] for field in money},
        *money,
    )
    assert fixtures.read_payroll_file(api, draft["id"])["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# The line create joins three referenced rows
# ---------------------------------------------------------------------------
def test_03_media_line_create_with_an_unknown_order_batch_is_a_not_found(api):
    """The batch identifier travels in the request body, and a body identifier that
    resolves to no row is the same 404 family as a path identifier.

    PRD: "Every creation payload that names another record — `employer_id`, `employee_id`, `election_window_id`, `benefit_category_id`, `transit_media_id`, `election_id`, `order_batch_id`, `card_transaction_id` — must resolve to an existing row, and the failure carries the same per-entity code (with a body `order_batch_id` reported as `ERR_ORDER_BATCH_NOT_FOUND`, a body `card_transaction_id` as `ERR_CARD_TRANSACTION_NOT_FOUND`, and a non-resolving benefit account as `ERR_BENEFIT_ACCOUNT_NOT_FOUND`)."

    Design: Corner/endpoints/media_order_link_requires_all_three_referenced_rows_to_exist
    """
    built = _link_ready_program(api)
    election, media, batch = built["election"], built["media"], built["batch"]
    assertions.assert_election_axes(election, "PENDING", "AWAITING_ORDER")
    assert batch["line_count"] == 0

    response = api.create_media_order(
        factories.media_order_payload(
            election["id"],
            media["id"],
            UNKNOWN_ORDER_BATCH_ID,
            election["version"],
            quantity=1,
            coverage_start_at=COVERAGE_START_AT,
            coverage_end_at=COVERAGE_END_AT,
        ),
        make_order_desk_headers("desk-link"),
    )
    validate_error(response, ERR_ORDER_BATCH_NOT_FOUND, expected_status=404)

    settled = fixtures.read_election(api, election["id"])
    assertions.assert_election_axes(settled, "PENDING", "AWAITING_ORDER")
    assertions.assert_unchanged(election, settled, "fulfillment_status")
    assert fixtures.read_batch(api, batch["id"])["line_count"] == 0


def test_04_media_line_create_links_election_medium_and_batch_together(api):
    """With all three referenced rows present the same body creates the association:
    the line echoes each identifier, opens PENDING, lifts the batch line count and
    moves the parent election off AWAITING_ORDER.

    PRD: "A successful line create opens the row in `status` `PENDING` with `unit_price_cents_snapshot` copied from the catalogue product's current `unit_price_cents`"

    PRD: "The create then re-derives the parent election's `fulfillment_status` and advances `Election.version` by 1 — which is exactly why the create carries `expected_election_version`."

    PRD: "Creating a media line for an election that was waiting therefore advances the election `AWAITING_ORDER → ORDERED`, provided `entitled_media_units` is greater than zero and at least one of the election's media orders is not `CANCELLED`."

    PRD: "Computed rollup counters are recomputed as part of the same request rather than lazily: `enrolled_employee_count` on an employer, `active_election_count` on a benefit category, `election_count` on an election window, `ledger_entry_count` on a benefit account and `line_count` on a procurement batch are all correct at the moment the response is emitted."

    Design: Corner/endpoints/media_order_link_requires_all_three_referenced_rows_to_exist
    """
    built = _link_ready_program(api)
    election, media, batch = built["election"], built["media"], built["batch"]

    order = validate_success(
        api.create_media_order(
            factories.media_order_payload(
                election["id"],
                media["id"],
                batch["id"],
                election["version"],
                quantity=1,
                coverage_start_at=COVERAGE_START_AT,
                coverage_end_at=COVERAGE_END_AT,
            ),
            make_order_desk_headers("desk-link"),
        ),
        expected_status=201,
    )

    assert order["election_id"] == election["id"]
    assert order["transit_media_id"] == media["id"]
    assert order["order_batch_id"] == batch["id"]
    assert order["status"] == "PENDING"
    assert order["quantity"] == 1
    assert order["unit_price_cents_snapshot"] == 3000
    assert order["replacement_count"] == 0

    assert fixtures.read_batch(api, batch["id"])["line_count"] == 1
    settled = fixtures.read_election(api, election["id"])
    assertions.assert_election_axes(settled, "PENDING", "ORDERED")
    assert settled["version"] == election["version"] + 1


# ---------------------------------------------------------------------------
# The ledger read must reproduce the money calculation exactly
# ---------------------------------------------------------------------------
def test_05_account_ledger_read_carries_the_running_balance_oldest_first(api):
    """A 10000-cent carried-in balance followed by a 2000-cent auto-substantiated
    swipe leaves two rows whose stored running totals must read 10000 then 8000, with
    the spend signed negative and the account agreeing with the log.

    PRD: "When a non-zero opening balance is supplied, the account's very first ledger entry is written at creation with `entry_type` `ROLLOVER_IN` and a positive `amount_cents` equal to that opening balance, with `source_entity` `BenefitAccount` and `source_id` the account's own identifier, and the account's `available_balance_cents` is set accordingly."

    PRD: "a swipe of 2500 cents or less — twenty-five dollars, with the boundary inclusive, so exactly 2500 clears and 2501 does not — is created in `AUTO_SUBSTANTIATED`, and a larger swipe is created in `PENDING_DOCS` awaiting documentation."

    PRD: "one ledger entry is appended with `entry_type` `SPEND` and a negative `amount_cents` equal to the posted spend, with `source_entity` `CardTransaction` and `source_id` the transaction's identifier; the account's `spent_cents` increases by the posted amount and `available_balance_cents` is recomputed."

    PRD: "A third, order-sensitive identity governs the log itself: each entry's `balance_after_cents` equals the running signed total of all entries for that account up to and including itself, taken in ascending `created_at` order."

    PRD: "Unless a specific endpoint states otherwise, list results are ordered by `created_at` ascending."

    Design: Corner/endpoints/ledger_read_filters_by_entry_type_and_carries_the_running_balance
    """
    built = fixtures.make_program_with_participant(
        api,
        region_code=constants.REGION_AUS,
        employer_overrides={"legal_name": "Ledger Read Co"},
        category_overrides={
            "category_type": "TRANSIT_PASS",
            "monthly_exclusion_limit_cents": 30000,
        },
        account_overrides={"opening_rollover_cents": 10000},
        window_overrides={"benefit_month": "2026-08", "cutoff_at": WINDOW_CUTOFF_AT},
    )
    account_id = built["account"]["id"]
    assert built["account"]["rollover_in_cents"] == 10000
    assert built["account"]["available_balance_cents"] == 10000

    election = fixtures.make_election(
        api,
        built["employee"]["id"],
        built["window"]["id"],
        built["category"]["id"],
        account_id,
        pretax_amount_cents=3000,
        posttax_amount_cents=0,
    )
    assertions.assert_election_axes(election, "PENDING", "NOT_REQUIRED")

    transaction = validate_success(
        api.create_card_transaction(
            factories.card_transaction_payload(
                election["id"],
                amount_cents=2000,
                merchant_category_code=4111,
                merchant_name="Austin Metro Rail",
                transaction_at="2026-08-01T09:00:00Z",
            ),
            PROGRAM_ADMIN,
        ),
        expected_status=201,
    )
    assert transaction["substantiation_status"] == "AUTO_SUBSTANTIATED"
    assert transaction["posted_spend_cents"] == 2000
    assert transaction["benefit_account_id"] == account_id

    entries, meta = validate_paginated(
        api.list_account_ledger_entries(account_id, PROGRAM_ADMIN, {"limit": 100})
    )
    assert meta["total_count"] == 2
    assert len(entries) == 2
    assertions.assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 10000, 10000), ("SPEND", -2000, 8000)]
    )
    assert entries[0]["source_entity"] == "BenefitAccount"
    assert entries[0]["source_id"] == account_id
    assert entries[1]["source_entity"] == "CardTransaction"
    assert entries[1]["source_id"] == transaction["id"]
    for entry in entries:
        assertions.assert_append_only_common_fields(entry)
        assert entry["benefit_account_id"] == account_id

    account = fixtures.read_account(api, account_id)
    assert account["available_balance_cents"] == 8000
    assert account["spent_cents"] == 2000
    assert account["ledger_entry_count"] == 2
    assertions.assert_account_conservation(account)
    assertions.assert_ledger_matches_account(account, entries)


# ---------------------------------------------------------------------------
# The reissue fee waiver is conditional on the reason already recorded
# ---------------------------------------------------------------------------
def test_06_reissue_fee_waiver_is_refused_when_the_recorded_reason_is_lost(api):
    """The waiver flag is not the caller's to assert: against a line reported LOST the
    waived reissue is refused outright, and neither the line nor the account moves.

    PRD: "The payload accepts an optional `waive_replacement_fee` flag; when it is true, the line's `undelivered_reason` must be `NEVER_ARRIVED`, the only waivable reason, and any other reason with the flag set is refused with `ERR_REPLACEMENT_FEE_NOT_WAIVABLE`."

    PRD: "Media that was lost, stolen or damaged in the employee's own custody is always chargeable."

    Design: Corner/endpoints/reissue_fee_waiver_allowed_only_for_the_never_arrived_reason
    """
    chain = _undelivered_line(api, "LOST")
    order_before = chain["order"]
    assert order_before["status"] == "UNDELIVERED"
    assert order_before["undelivered_reason"] == "LOST"
    assert order_before["replacement_count"] == 0
    assert order_before["replacement_fee_charged_cents"] == 0

    account_before = fixtures.read_account(api, chain["account"]["id"])
    assert account_before["fee_charged_cents"] == 0
    assert account_before["available_balance_cents"] == 10000
    assert account_before["ledger_entry_count"] == 1

    response = api.reissue_media_order(
        order_before["id"],
        {"waive_replacement_fee": True},
        make_order_desk_headers(SEAL_USER_ID),
    )
    validate_error(response, ERR_REPLACEMENT_FEE_NOT_WAIVABLE, expected_status=422)

    order_after = fixtures.read_media_order(api, order_before["id"])
    assert order_after["status"] == "UNDELIVERED"
    assert order_after["replacement_count"] == 0
    assertions.assert_unchanged(
        order_before,
        order_after,
        "status",
        "undelivered_reason",
        "replacement_count",
        "replacement_fee_charged_cents",
        "tracking_ref",
    )

    account_after = fixtures.read_account(api, chain["account"]["id"])
    assertions.assert_unchanged(
        account_before,
        account_after,
        "fee_charged_cents",
        "available_balance_cents",
        "ledger_entry_count",
    )
    assertions.assert_account_conservation(account_after)


def test_07_reissue_fee_waiver_zeroes_the_escalated_fee_for_a_never_arrived_report(api):
    """The unwaived first reissue charges the flat catalogue fee; the second reissue
    would have charged double, but a NEVER_ARRIVED report makes the waiver legal and
    the fee is zero instead — so nothing is added to the account the second time.

    PRD: "It requires the line's `status` to be `UNDELIVERED` and its `replacement_count` to be strictly below the reissue allowance of 2, so a line that has already been reissued twice is refused with `ERR_REISSUE_LIMIT_EXCEEDED`."

    PRD: "When `waive_replacement_fee` is true — which, by the gate above, means the reason was `NEVER_ARRIVED` — the fee is zero. Otherwise, when the line's `replacement_count` is currently zero, the fee is the catalogue product's `replacement_fee_cents` exactly."

    PRD: "Otherwise — meaning this is the second reissue of the same row — the fee is that `replacement_fee_cents` multiplied by two, an escalation intended to make repeated loss visible."

    PRD: "When the fee is zero, no ledger entry is written and the account is untouched."

    PRD: "Alongside the fee, the reissue increments the line's `replacement_count` by 1 and adds the fee to its `replacement_fee_charged_cents`, moves the line `UNDELIVERED → SUBMITTED` on the **same row with the same `quantity`**, and clears `tracking_ref` back to null so the next shipment can record a fresh one."

    PRD: "The parent election's `fulfillment_status` is re-derived back to `ORDERED` — the `REPLACEMENT_PENDING → ORDERED` step, which holds when no media order of the election is `UNDELIVERED` after the reissue and none is yet `SHIPPED`"

    Design: Corner/endpoints/reissue_fee_waiver_allowed_only_for_the_never_arrived_reason
    """
    chain = _undelivered_line(api, "LOST")
    desk_headers = make_order_desk_headers(SEAL_USER_ID)
    order_id = chain["order"]["id"]
    account_id = chain["account"]["id"]
    assert chain["media"]["replacement_fee_cents"] == 500

    first_lap = validate_success(api.reissue_media_order(order_id, {}, desk_headers))
    assert first_lap["status"] == "SUBMITTED"
    assert first_lap["replacement_count"] == 1
    assert first_lap["replacement_fee_charged_cents"] == 500
    assert first_lap["tracking_ref"] is None
    assert first_lap["quantity"] == chain["order"]["quantity"]

    validate_success(
        api.ship_media_order(order_id, {"tracking_ref": "TRK-WV-2"}, desk_headers)
    )
    reported = validate_success(
        api.report_media_order_undelivered(
            order_id, {"reason": "NEVER_ARRIVED"}, desk_headers
        )
    )
    assert reported["undelivered_reason"] == "NEVER_ARRIVED"
    assert reported["replacement_count"] == 1

    second_lap = validate_success(
        api.reissue_media_order(
            order_id, {"waive_replacement_fee": True}, desk_headers
        )
    )
    assert second_lap["status"] == "SUBMITTED"
    assert second_lap["replacement_count"] == 2
    assert second_lap["replacement_fee_charged_cents"] == 500
    assert second_lap["replacement_fee_charged_cents"] != 1500
    assert second_lap["tracking_ref"] is None

    account = fixtures.read_account(api, account_id)
    assert account["fee_charged_cents"] == 500
    assert account["available_balance_cents"] == 9500
    assert account["ledger_entry_count"] == 2
    assertions.assert_account_conservation(account)

    entries = fixtures.read_ledger(api, account_id)
    assertions.assert_ledger_sequence(
        entries, [("ROLLOVER_IN", 10000, 10000), ("REPLACEMENT_FEE", -500, 9500)]
    )
    assert entries[1]["source_entity"] == "MediaOrder"
    assert entries[1]["source_id"] == order_id
    assertions.assert_ledger_matches_account(account, entries)

    assertions.assert_election_axes(
        fixtures.read_election(api, chain["election"]["id"]), "PENDING", "ORDERED"
    )
