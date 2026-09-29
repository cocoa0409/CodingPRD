"""Declared moves that are admitted, and undeclared or out-of-order ones that are refused."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories, fixtures

CLOCK = "2026-08-10T00:00:00Z"


def _bare_well(api, **overrides):
    return validate_success(
        api.create_well(
            factories.create_well_payload(omit_fields=["spud_date"], **overrides),
            fixtures.LAND_ADMIN,
        ),
        201,
    )


def _forming_unit(api, clock=CLOCK):
    """Two tracts committed to one well, unit assembled but not yet in force."""
    fixtures.set_clock(api, clock)
    lease1 = validate_success(
        api.create_lease(factories.minimal_lease_payload(), fixtures.LAND_ADMIN), 201
    )
    lease2 = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-002",
                lessor_name="Beta Royalties",
                gross_acres=320.0,
                royalty_rate=0.25,
                primary_term_end_date="2027-12-31",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    well = _bare_well(api)
    fixtures.commit_acreage(api, well["id"], lease1["id"], 480.0)
    fixtures.commit_acreage(api, well["id"], lease2["id"], 160.0)
    return {"lease1": lease1, "lease2": lease2, "well": well, "well_id": well["id"]}


def test_exercising_the_option_advances_the_term_without_leaving_the_primary_term(api):
    """The option is a self-loop: the instrument stays in its primary term, just a longer one.

    The tendered amount is then checked against what the instrument actually calls for: the required bonus is the lease's `gross_acres` multiplied by `extension_bonus_per_acre_cents`, rounded half up to whole cents, and if `bonus_paid_cents` is not exactly equal to that figure the exercise is rejected with `ERR_EXTENSION_BONUS_MISMATCH`.
    On success the lease stays in `PRIMARY_TERM` — this is a self-loop on the tenure dimension, not a move — while `primary_term_end_date` advances by `extension_option_months` calendar months, clamping the day of month to the last day of the target month when the target month is shorter than the source month.

    Design: Corner/state_machines/lease_extension_advances_the_primary_term_by_the_option_months
    """
    fixtures.set_clock(api, CLOCK)
    lease = validate_success(
        api.create_lease(
            factories.create_lease_payload(
                omit_fields=[
                    "shut_in_royalty_per_acre_cents",
                    "continuous_dev_window_days",
                ]
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )

    extended = validate_success(
        api.exercise_lease_extension(
            lease["id"],
            factories.lease_extension_payload(9_600_000),
            fixtures.LAND_ADMIN,
        ),
        200,
    )

    assert extended["primary_term_end_date"] == "2028-09-30"
    assert extended["extension_exercised"] is True
    assert extended["extension_bonus_paid_cents"] == 9_600_000
    assert extended["tenure_status"] == "PRIMARY_TERM"
    assert extended["obligation_status"] == "COMPLIANT"
    assert extended["version"] == 2


def test_a_well_cannot_be_spudded_before_its_pooled_unit_is_in_force(api):
    """Acreage gathered is not the same as a unit declared: the rig waits for effectuation.

    Moving `PROPOSED → DRILLING` requires the unit to be in force: the well's `pooling_status` must be `POOLED_EFFECTIVE`, because a well is not spudded before its pooled unit exists, and a well that fails this is rejected with `ERR_WELL_NOT_POOLED`.

    Design: Corner/state_machines/drilling_a_well_before_pooling_effectuation_is_rejected
    """
    context = _forming_unit(api)
    before = validate_success(
        api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200
    )

    validate_error(
        api.change_well_status(
            context["well_id"],
            factories.well_status_change_payload(
                "DRILLING", effective_date="2026-07-10"
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_WELL_NOT_POOLED",
        409,
    )

    after = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert after["well_status"] == "PROPOSED"
    assert after["pooling_status"] == "POOLED_FORMING"
    assert after["spud_date"] is None
    assert after["version"] == before["version"]


def test_a_well_cannot_start_producing_without_an_operator_of_record(api):
    """Someone has to answer for the joint account before the first barrel is sold.

    Moving `DRILLING → PRODUCING` requires an operator of record: at least one working-interest position on the well must be `ACTIVE` with `is_operator` true, else the request is rejected with `ERR_NO_OPERATOR_INTEREST`.

    Design: Corner/state_machines/moving_a_well_to_producing_without_an_operator_interest_is_rejected
    """
    context = _forming_unit(api)
    owner = validate_success(
        api.create_interest_owner(
            factories.create_interest_owner_payload(
                owner_name="Delta Partners LP",
                contact_email="delta@example.com",
                bond_posted_cents=10_000_000,
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    fixtures.add_interest(
        api, context["well_id"], owner["id"], 0.3, 0.24, is_operator=False
    )
    fixtures.effectuate_pooling(api, context["well_id"], "2026-04-01")
    fixtures.change_status(api, context["well_id"], "DRILLING", "2026-07-10")

    validate_error(
        api.change_well_status(
            context["well_id"],
            factories.well_status_change_payload(
                "PRODUCING", effective_date="2026-07-10"
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_NO_OPERATOR_INTEREST",
        409,
    )

    after = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert after["well_status"] == "DRILLING"
    assert after["first_production_date"] is None


def test_shutting_the_well_in_starts_a_shut_in_chain_on_every_contributing_tract(api):
    """One operational decision on the well reaches into every land record beneath it.

    Moving `PRODUCING → SHUT_IN` records `shut_in_since` as the logical clock date and reaches across into the land records: **every lease with a committed allocation to this well** has its `shut_in_start_date` set to the logical clock date, its `shut_in_payments_made` reset to 0, and its `shut_in_next_due_date` set to the clock date plus 90 days.

    Design: Corner/state_machines/shutting_in_the_well_stamps_the_shut_in_clock_on_every_committed_lease
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)

    changed = validate_success(
        api.change_well_status(
            context["well_id"],
            factories.well_status_change_payload("SHUT_IN", effective_date="2026-07-10"),
            fixtures.LAND_ADMIN,
        ),
        200,
    )

    assert changed["well_status"] == "SHUT_IN"
    assert changed["shut_in_since"] == "2026-08-10"

    for lease_id in (context["lease1_id"], context["lease2_id"]):
        lease = validate_success(api.get_lease(lease_id, fixtures.LAND_ADMIN), 200)
        assert lease["shut_in_start_date"] == "2026-08-10"
        assert lease["shut_in_payments_made"] == 0
        assert lease["shut_in_next_due_date"] == "2026-11-08"
        assert lease["tenure_status"] == "PRIMARY_TERM"


def test_a_producing_well_cannot_be_walked_backwards_into_drilling(api):
    """Production is not un-drilled; the only ways out of PRODUCING are downhole ones.

    Any requested `to_status` that is not a declared transition out of the well's present `well_status` is rejected with `ERR_WELL_INVALID_STATUS`.

    Design: Corner/state_machines/moving_a_producing_well_back_to_drilling_is_rejected
    """
    context = fixtures.setup_pooled_producing_well(api, clock=CLOCK)

    validate_error(
        api.change_well_status(
            context["well_id"],
            factories.well_status_change_payload(
                "DRILLING", effective_date="2026-07-10"
            ),
            fixtures.LAND_ADMIN,
        ),
        "ERR_WELL_INVALID_STATUS",
        409,
    )

    after = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert after["well_status"] == "PRODUCING"
    assert after["first_production_date"] == "2026-08-10"


def test_a_freshly_filed_contest_opens_with_no_rounds_spent_and_both_clocks_running(api):
    """Filing starts the exchange calendar; it does not itself unwind a single cent.

    On success the dispute is created with `dispute_status` of `OPEN` and `round_count` of 0; `filed_at` is taken from the logical clock; `response_due_date` is 60 days after the date part of `filed_at`, and `rebuttal_due_date` is 30 days after `response_due_date`; `adjustment_amount_cents` is 0, `deemed_in_favor_of_partner` is false, `operator_responded_at` and `resolved_by_user_id` are null.
    Critically, `DISPUTED` is still a **billed** status: the well's `billed_to_date_cents` does not change, because contesting a bill does not un-bill it.

    Design: Corner/state_machines/a_newly_filed_dispute_starts_open_with_zero_rounds
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)

    dispute = validate_success(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                context["partner_b_id"],
                100_000,
                basis_note="Overhead allocation on the June statement is contested",
            ),
            context["partner_b_headers"],
        ),
        201,
    )

    assert dispute["dispute_status"] == "OPEN"
    assert dispute["round_count"] == 0
    assert dispute["filed_at"] == "2026-08-10T00:00:00.000Z"
    assert dispute["response_due_date"] == "2026-10-09"
    assert dispute["rebuttal_due_date"] == "2026-11-08"
    assert dispute["adjustment_amount_cents"] == 0
    assert dispute["deemed_in_favor_of_partner"] is False
    assert dispute["operator_responded_at"] is None
    assert dispute["resolved_by_user_id"] is None
    assert dispute["version"] == 1

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "DISPUTED"

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000


def test_an_expired_instrument_accepts_no_further_maintenance_event(api):
    """Once the term has run out, recording an operation cannot resurrect the lease.

    The addressed entity is not already in a terminal state, else `ERR_TERMINAL_STATE` (409).
    Expiry arrives on three paths, all of them driven by the evaluation pass, and all three write the same terminal outcome: `tenure_status` becomes `EXPIRED`, `obligation_status` becomes `IN_BREACH`, and `held_acres` is set to 0.

    Design: Corner/state_machines/an_expired_lease_refuses_a_further_obligation_event
    """
    fixtures.set_clock(api, CLOCK)
    lease = validate_success(
        api.create_lease(
            factories.minimal_lease_payload(
                lease_number="L-003",
                lessor_name="Gamma Minerals",
                gross_acres=160.0,
                royalty_rate=0.2,
                primary_term_end_date="2026-06-30",
            ),
            fixtures.LAND_ADMIN,
        ),
        201,
    )
    run = fixtures.run_obligation_pass(api)
    assert run["leases_expired"] == 1

    validate_error(
        api.record_obligation_event(
            lease["id"],
            factories.obligation_event_payload("CONTINUOUS_OPERATION", "2026-07-01"),
            fixtures.LAND_ADMIN,
        ),
        "ERR_TERMINAL_STATE",
        409,
    )

    after = validate_success(api.get_lease(lease["id"], fixtures.LAND_ADMIN), 200)
    assert after["tenure_status"] == "EXPIRED"
    assert after["obligation_status"] == "IN_BREACH"
    assert after["held_acres"] == 0.00
    assert after["last_operation_end_date"] is None
    assert after["continuous_dev_deadline"] is None


def test_a_unit_already_in_force_cannot_be_declared_effective_a_second_time(api):
    """Effectuation is the one-way door out of unit assembly, so it does not replay.

    The well's `pooling_status` must be `POOLED_FORMING` — a unit that is already effective, already terminated, or still unpooled is rejected with `ERR_POOLING_NOT_FORMING`.

    Design: Corner/state_machines/a_second_pooling_effectuation_on_the_same_well_is_rejected
    """
    context = _forming_unit(api)
    effectuated = fixtures.effectuate_pooling(api, context["well_id"], "2026-04-01")
    version_after_first = effectuated["version"]

    validate_error(
        api.effectuate_pooling(
            context["well_id"],
            factories.pooling_effectuation_payload("2026-04-01"),
            fixtures.LAND_ADMIN,
        ),
        "ERR_POOLING_NOT_FORMING",
        409,
    )

    after = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert after["pooling_status"] == "POOLED_EFFECTIVE"
    assert after["version"] == version_after_first


def test_a_contest_that_is_turned_down_puts_the_bill_back_where_it_was(api):
    """The audit reviewer siding with the operator restores the bill, it does not re-issue it.

    Upholding sets `dispute_status` to `RESOLVED_UPHELD`, `adjustment_amount_cents` to 0 and `resolved_by_user_id` to the acting `X-User-ID`, and returns the statement from `DISPUTED` to `ISSUED` once no other dispute against it remains live. There is no ledger change: the bill stood.

    Design: Corner/state_machines/upheld_resolution_bubbles_the_statement_back_from_disputed_to_issued
    """
    context = fixtures.setup_issued_june_statement(api, clock=CLOCK)
    dispute = validate_success(
        api.file_dispute(
            context["statement_id"],
            factories.file_dispute_payload(
                context["partner_b_id"],
                100_000,
                basis_note="Overhead allocation on the June statement is contested",
            ),
            context["partner_b_headers"],
        ),
        201,
    )
    validate_success(
        api.create_dispute_exchange(
            dispute["id"],
            factories.dispute_exchange_payload(
                "OPERATOR_RESPONSE",
                exchange_note=(
                    "Overhead was charged on the PERCENTAGE_BASIS class elected "
                    "for this period"
                ),
            ),
            fixtures.JIB_ACCOUNTANT,
        ),
        200,
    )

    resolved = validate_success(
        api.resolve_dispute(
            dispute["id"],
            factories.dispute_resolution_payload("UPHELD", 0),
            fixtures.AUDIT_REVIEWER,
        ),
        200,
    )

    assert resolved["dispute_status"] == "RESOLVED_UPHELD"
    assert resolved["adjustment_amount_cents"] == 0
    assert resolved["resolved_by_user_id"] == "u-audit-1"

    statement = validate_success(
        api.get_jib_statement(context["statement_id"], fixtures.JIB_ACCOUNTANT), 200
    )
    assert statement["statement_status"] == "ISSUED"
    assert statement["total_billed_cents"] == 2_934_000

    well = validate_success(api.get_well(context["well_id"], fixtures.LAND_ADMIN), 200)
    assert well["billed_to_date_cents"] == 2_934_000

    _, meta = validate_paginated(
        api.list_jib_statements(
            fixtures.JIB_ACCOUNTANT,
            params={"superseded_statement_id": context["statement_id"]},
        )
    )
    assert meta["total_count"] == 0
