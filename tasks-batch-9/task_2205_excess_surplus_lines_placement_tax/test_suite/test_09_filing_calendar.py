"""The filing calendar: batch birth, the sweep, the due date and its penalty
floor, and the two rungs that guard submission and remittance.
"""

from test_helpers import (
    ERR_BATCH_EMPTY,
    ERR_BROKER_LICENSE_NOT_ACTIVE,
    ERR_ENDORSEMENT_ALREADY_REMITTED,
    ERR_PERIOD_KEY_MALFORMED,
    ERR_REMITTANCE_AMOUNT_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    PLATFORM_ADMIN,
    TAX_FILER_NINA,
    TAX_FILER_NINA_ID,
    TAX_FILER_OMAR,
    TAX_FILER_OWEN,
    TAX_FILER_OWEN_ID,
    assert_common_fields,
    assert_policy_dimensions,
    exposure,
    tx_program_payload,
    validate_error,
    validate_success,
)


def test_filing_batch_is_born_open_with_a_null_due_date_and_zero_totals(
    configured_world,
):
    """Nothing is computed until preparation runs.

    PRD 3.9: "A new batch's `status` is `OPEN`, its `line_count` is 0, its
    `total_tax_cents`, `total_stamping_fee_cents`, `penalty_cents` and
    `total_due_cents` are all 0, its `late` flag is false, its `due_date` is null,
    and both `prepared_by_user_id` and `remitted_by_user_id` are null."

    Design: Corner/state_machines/filing_batch_is_born_open_with_a_null_due_date_and_zero_totals
    """
    world = configured_world
    batch = world.open_batch("TX")

    assert_common_fields(batch, expected_version=1)
    assert batch["status"] == "OPEN"
    assert batch["state_program_id"] == world.program_id("TX")
    assert batch["broker_id"] == world.broker["id"]
    assert batch["period_key"] == "2026-08"
    assert batch["line_count"] == 0
    assert batch["total_tax_cents"] == 0
    assert batch["total_stamping_fee_cents"] == 0
    assert batch["penalty_cents"] == 0
    assert batch["total_due_cents"] == 0
    assert batch["late"] is False
    assert batch["due_date"] is None
    assert batch["prepared_by_user_id"] is None
    assert batch["remitted_by_user_id"] is None


def test_the_late_filing_penalty_floor_beats_the_percentage_term(calculated_world):
    """Ten percent of the tax is less than twenty-five dollars, so the floor wins.

    PRD 3.9: "The `due_date` is derived from the state's own calendar: take the
    last calendar day of the period named by `period_key`, add the state's
    `filing_deadline_days` calendar days, and set the instant to 23:59:59.999Z on
    that day. Lateness is **strictly** determined: the batch's `late` flag is true
    only when the current logical clock is strictly after the `due_date`, so a
    batch prepared at exactly the `due_date` instant is on time. When the batch is
    not late, `penalty_cents` is 0. When it is late, `penalty_cents` is the larger
    of two figures: the batch's `total_tax_cents` multiplied by a late penalty rate
    of 0.10 — using zero in place of a negative tax total, so a refund-heavy batch
    is never penalised on a negative base — rounded half up to whole cents; and a
    statutory floor of 2,500 cents, that is twenty-five dollars. The batch's
    `total_due_cents` is then its `total_tax_cents` plus its
    `total_stamping_fee_cents` plus its `penalty_cents`, and it may legitimately be
    negative when net return premium exceeds new business."

    Design: Corner/calculations/the_late_filing_penalty_floor_beats_the_percentage_term
    """
    world = calculated_world
    world.set_clock("2026-10-01T00:00:00Z")

    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)

    assert prepared["status"] == "PREPARED"
    assert prepared["line_count"] == 1
    assert prepared["total_tax_cents"] == 16571
    assert prepared["total_stamping_fee_cents"] == 512
    # 2026-08-31 plus Texas's 30 filing deadline days.
    assert prepared["due_date"] == "2026-09-30T23:59:59.999Z"
    assert prepared["late"] is True
    # 10% of 16,571 is 1,657 cents, below the 2,500-cent statutory floor.
    assert prepared["penalty_cents"] == 2500
    assert prepared["total_due_cents"] == 19583
    assert prepared["prepared_by_user_id"] == TAX_FILER_NINA_ID


def test_a_monthly_period_key_on_a_quarterly_program_is_refused(configured_world):
    """The period key must speak the state's own filing frequency.

    PRD 3.9: "Its single precondition is that the batch's `period_key` matches the
    format the state's `filing_frequency` demands — `YYYY-MM` when the frequency is
    `MONTHLY`, or `YYYY-Qn` with the quarter number between 1 and 4 when the
    frequency is `QUARTERLY` — else `ERR_PERIOD_KEY_MALFORMED`."

    Design: Corner/errors/a_monthly_period_key_on_a_quarterly_program_is_refused
    """
    world = configured_world
    assert world.program("CA")["filing_frequency"] == "QUARTERLY"

    monthly = world.open_batch("CA", period_key="2026-08")
    validate_error(
        world.api.prepare_filing_batch(monthly["id"], TAX_FILER_NINA),
        ERR_PERIOD_KEY_MALFORMED,
        422,
    )
    still_open = validate_success(
        world.api.get_filing_batch(monthly["id"], TAX_FILER_NINA), 200
    )
    assert still_open["status"] == "OPEN"
    assert still_open["due_date"] is None
    assert still_open["version"] == monthly["version"]

    quarterly = world.open_batch("CA", period_key="2026-Q3")
    prepared = world.prepare_batch(quarterly)
    assert prepared["status"] == "PREPARED"
    # 2026-09-30 plus California's 45 filing deadline days.
    assert prepared["due_date"] == "2026-11-14T23:59:59.999Z"
    assert prepared["late"] is False


def test_submitting_a_batch_that_swept_no_lines_is_refused(configured_world):
    """An empty batch prepares cleanly and then refuses to file.

    PRD 3.9: "Two preconditions apply: the batch's `line_count` must be greater
    than 0, else `ERR_BATCH_EMPTY`; and the batch's brokerage must hold a licence
    of `license_type` `SURPLUS_LINES` whose `state_code` equals the batch state's
    `state_code` and whose computed `status` is `ACTIVE`, else
    `ERR_BROKER_LICENSE_NOT_ACTIVE`."

    Design: Corner/errors/submitting_a_batch_that_swept_no_lines_is_refused
    """
    world = configured_world
    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)

    assert prepared["status"] == "PREPARED"
    assert prepared["line_count"] == 0
    assert prepared["total_tax_cents"] == 0
    assert prepared["penalty_cents"] == 0
    assert prepared["total_due_cents"] == 0

    validate_error(
        world.api.submit_filing_batch(batch["id"], TAX_FILER_NINA),
        ERR_BATCH_EMPTY,
        409,
    )
    after = validate_success(world.api.get_filing_batch(batch["id"], TAX_FILER_NINA), 200)
    assert after["status"] == "PREPARED"
    assert after["version"] == prepared["version"]


def test_voiding_an_endorsement_whose_tax_was_already_remitted_is_refused(
    endorsed_world,
):
    """Once the state has the money the endorsement can no longer be unwound.

    PRD 3.8: "From `ISSUED → VOIDED`, the void is refused with
    `ERR_ENDORSEMENT_ALREADY_REMITTED` when any tax filing line whose
    `source_endorsement_id` is this endorsement has already reached `status`
    `REMITTED`."

    Design: Corner/errors/voiding_an_endorsement_whose_tax_was_already_remitted_is_refused
    """
    world = endorsed_world
    endorsement = world.endorsement

    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)
    assert prepared["line_count"] == 2
    assert prepared["total_tax_cents"] == 19804
    assert prepared["total_stamping_fee_cents"] == 612
    assert prepared["late"] is False
    assert prepared["total_due_cents"] == 20416

    world.submit_batch(prepared)
    remitted = world.remit_batch(prepared, 20416, filer=TAX_FILER_OMAR)
    assert remitted["status"] == "REMITTED"

    # PRD 5 catalogues `ERR_ENDORSEMENT_ALREADY_REMITTED` at HTTP 409, and PRD
    # 2.11 rung 9 lists it among the state-legality errors.
    validate_error(
        world.api.void_endorsement(endorsement["id"], world.broker_headers),
        ERR_ENDORSEMENT_ALREADY_REMITTED,
        409,
    )
    unchanged = validate_success(
        world.api.get_endorsement(endorsement["id"], world.broker_headers), 200
    )
    assert unchanged["status"] == "ISSUED"
    assert unchanged["version"] == endorsement["version"]


def test_the_remittance_segregation_check_pre_empts_the_amount_check(calculated_world):
    """The preparer paying the wrong amount is told about the conflict, not the sum.

    PRD 2.11: "**Segregation of duties.** The acting `X-User-ID` is not the same
    principal who performed the paired earlier step. Applies to exactly two
    operations: remitting a filing batch, where the actor must differ from the
    batch's `prepared_by_user_id`; and signing an affidavit, where the actor must
    differ from the `reviewer_user_id` of every `APPROVED` or `CONDITIONAL` market
    security review of the policy's carrier. Violation: `ERR_SEGREGATION_OF_DUTIES`
    (409)."

    Design: Difficulty/priority_pair_validation_conflict/batch_remit_segregation_of_duties_pre_empts_amount_mismatch
    """
    world = calculated_world
    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)
    assert prepared["prepared_by_user_id"] == TAX_FILER_NINA_ID
    assert prepared["total_due_cents"] == 17083
    submitted = world.submit_batch(prepared)

    # Both rules are broken at once: wrong actor and wrong amount.
    validate_error(
        world.api.remit_filing_batch(
            batch["id"], {"remitted_amount_cents": 99999}, TAX_FILER_NINA
        ),
        ERR_SEGREGATION_OF_DUTIES,
        409,
    )
    after = validate_success(world.api.get_filing_batch(batch["id"], TAX_FILER_NINA), 200)
    assert after["status"] == "SUBMITTED"
    assert after["remitted_by_user_id"] is None
    assert after["version"] == submitted["version"]


def test_a_second_filer_remitting_the_wrong_amount_reaches_the_money_rung(
    calculated_world,
):
    """With the actor corrected the amount check finally reports.

    PRD 3.9: "Two preconditions apply, and both belong to the segregation-and-money
    rungs of the ladder: the acting `X-User-ID` must differ from the batch's
    `prepared_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`; and
    `remitted_amount_cents` must equal the batch's computed `total_due_cents`
    exactly, else `ERR_REMITTANCE_AMOUNT_MISMATCH` — including when that total is
    negative."

    Design: Difficulty/priority_pair_validation_conflict/batch_remit_segregation_of_duties_pre_empts_amount_mismatch
    """
    world = calculated_world
    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)
    world.submit_batch(prepared)

    validate_error(
        world.api.remit_filing_batch(
            batch["id"], {"remitted_amount_cents": 99999}, TAX_FILER_OWEN
        ),
        ERR_REMITTANCE_AMOUNT_MISMATCH,
        422,
    )

    remitted = world.remit_batch(prepared, 17083, filer=TAX_FILER_OWEN)
    assert remitted["status"] == "REMITTED"
    assert remitted["remitted_by_user_id"] == TAX_FILER_OWEN_ID
    lines = world.filing_lines(filing_batch_id=batch["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "REMITTED"


def _texas_only_world(world, license_expires_on):
    """A single-state Texas risk whose whole ledger fits in one batch."""
    world.create_broker()
    world.add_license(
        state_code="TX", license_number="SL-TX-1001", expires_on=license_expires_on
    )
    world.create_program(tx_program_payload())
    world.create_carrier()
    world.review_carrier("APPROVE")
    world.white_list("TX")
    world.searched_placement(
        insured_name="Llano Pipe and Supply LLC",
        state_exposures=[exposure("TX", 300_000_000)],
    )
    world.issue_policy(policy_number="SL-2026-0700")
    return world.calculate_tax()


def test_a_lapsed_surplus_lines_licence_blocks_batch_submission(world):
    """The batch is perfectly prepared; the brokerage's licence is not.

    PRD 2.11: "**Broker licensing.** The brokerage holds a licence of
    `license_type` `SURPLUS_LINES` for the relevant state whose computed `status`
    is `ACTIVE`. Applies to two operations: policy issuance, where the relevant
    state is the placement's `home_state`; and filing-batch submission, where it is
    the batch state's `state_code`. Violation: `ERR_BROKER_LICENSE_NOT_ACTIVE`
    (409). A licence whose `expires_on` is exactly the current logical clock is
    already `LAPSED`."

    Design: Difficulty/cross_entity_state_dependency/batch_submission_depends_on_the_brokers_license_status
    """
    policy = _texas_only_world(world, "2026-09-01T00:00:00Z")
    assert policy["total_tax_cents"] == 49713
    assert policy["total_stamping_fee_cents"] == 1538

    world.set_clock("2026-10-01T00:00:00Z")
    licences = validate_success(
        world.api.list_broker_licenses(world.broker["id"], PLATFORM_ADMIN), 200
    )
    assert [licence["status"] for licence in licences] == ["LAPSED"]

    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)
    assert prepared["status"] == "PREPARED"
    assert prepared["line_count"] == 1

    validate_error(
        world.api.submit_filing_batch(batch["id"], TAX_FILER_NINA),
        ERR_BROKER_LICENSE_NOT_ACTIVE,
        409,
    )
    after = validate_success(world.api.get_filing_batch(batch["id"], TAX_FILER_NINA), 200)
    assert after["status"] == "PREPARED"
    assert after["version"] == prepared["version"]
    assert world.filing_lines(filing_batch_id=batch["id"])[0]["status"] == "BATCHED"
    assert_policy_dimensions(world.get_policy(), tax_status="CALCULATED")


def test_a_fresh_licence_lets_the_batch_file_and_marks_the_policy_filed(world):
    """Restoring the licence unblocks the same submission and cascades to the policy.

    PRD 3.9: "On success every `BATCHED` line of the batch moves to `FILED`, the
    batch's `status` becomes `SUBMITTED`, and the batch's `version` increments. Each
    policy touched by the batch then advances its tax dimension to `FILED` once all
    of that policy's lines are `FILED`, `VOIDED` or `REMITTED`, incrementing that
    policy's `version` — reached as `CALCULATED → FILED` when at least one of the
    policy's lines was swept into this batch and the policy had never been adjusted,
    and as `ADJUSTED → FILED` when the policy had been adjusted and every one of
    its lines now stands at `FILED` or `VOIDED`."

    Design: Difficulty/cross_entity_state_dependency/batch_submission_depends_on_the_brokers_license_status
    """
    _texas_only_world(world, "2026-09-01T00:00:00Z")
    world.set_clock("2026-10-01T00:00:00Z")

    batch = world.open_batch("TX")
    prepared = world.prepare_batch(batch)
    before_policy = world.get_policy()

    world.add_license(
        state_code="TX", license_number="SL-TX-2002", expires_on="2027-12-31T00:00:00Z"
    )
    submitted = world.submit_batch(prepared)

    assert submitted["status"] == "SUBMITTED"
    assert submitted["version"] == prepared["version"] + 1
    lines = world.filing_lines(filing_batch_id=batch["id"])
    assert len(lines) == 1
    assert lines[0]["status"] == "FILED"

    policy = world.get_policy()
    assert_policy_dimensions(policy, status="ISSUED", tax_status="FILED")
    assert policy["version"] == before_policy["version"] + 1
