"""
Two occupancy rules whose intervals are measured to the day.

A pay period occupies calendar space for its employer with both ends inclusive,
and an indirect rollover occupies a rolling annual window for its saver. Each is
probed on the last day the interval still bites and on the first day it does
not.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    ADMIN,
    ERR_PAY_PERIOD_OVERLAP,
    ERR_ROLLOVER_FREQUENCY_LIMIT,
    PROGRAM_YEAR_2026,
    PROGRAM_YEAR_2027,
    assert_amounts,
    assert_fields,
    assert_total_count,
    build_active_saver_environment,
    build_funded_account_environment,
    create_remittance,
    make_employer_headers,
    make_participant_headers,
    read_account,
    read_participant,
    read_remittance,
    read_transfer,
    request_transfer,
    set_clock,
    settle_transfer,
)

FIRST_PERIOD = {
    "pay_period_start": "2026-02-01",
    "pay_period_end": "2026-02-28",
    "pay_date": "2026-03-05",
    "total_deducted_cents": 400000,
}

SHARED_BOUNDARY_PERIOD = {
    "pay_period_start": "2026-02-28",
    "pay_period_end": "2026-03-31",
    "pay_date": "2026-04-03",
    "total_deducted_cents": 400000,
}

NEXT_DAY_PERIOD = {
    "pay_period_start": "2026-03-01",
    "pay_period_end": "2026-03-31",
    "pay_date": "2026-04-03",
    "total_deducted_cents": 400000,
}

SECOND_ROLLOVER = {
    "destination_type": "EXTERNAL_IRA",
    "external_institution_name": "Southgate Custody Bank",
    "transfer_kind": "INDIRECT_60_DAY",
    "amount_cents": 100000,
}


def _employer_with_one_february_batch(api):
    """
    A registered employer with one live payroll batch already occupying the
    closed interval 1 February through 28 February 2026.
    """
    env = build_active_saver_environment(api)
    set_clock(api, "2026-04-05T00:00:00Z")
    first = create_remittance(api, env["employer_id"], **FIRST_PERIOD)
    env["first_remittance_id"] = first["id"]
    return env


def _saver_with_one_settled_indirect_rollover(api):
    """
    A saver whose account holds contributions and earnings and who has already
    taken one indirect rollover, settled on 1 May 2026. The clock is left on
    30 April 2027, the last day the trailing annual window still covers that
    settlement.
    """
    env = build_funded_account_environment(
        api, program_years=[PROGRAM_YEAR_2026, PROGRAM_YEAR_2027])
    set_clock(api, "2026-04-20T00:00:00Z")
    first = request_transfer(api, env["participant_id"], env["account_id"],
                            400000, transfer_kind="INDIRECT_60_DAY")
    set_clock(api, "2026-05-01T00:00:00Z")
    env["first_transfer"] = settle_transfer(api, first["id"], "2026-05-01",
                                           "RO-2026-0001")
    env["first_transfer_id"] = first["id"]
    set_clock(api, "2027-04-30T00:00:00Z")
    return env


def _second_rollover_payload(env):
    """The follow-up rollover request, identical on both attempt dates."""
    payload = dict(SECOND_ROLLOVER)
    payload["participant_id"] = env["participant_id"]
    payload["source_account_id"] = env["account_id"]
    return payload


def test_a_pay_period_sharing_only_its_first_day_still_collides(api):
    """
    A new batch that starts on the very last day of a live batch's period shares
    one calendar day with it, and one shared day is already an overlap.

    "Because both ends are inclusive, two periods that share a single boundary
    day collide, while a period beginning the day after another ends is
    accepted."

    Design: Difficulty/resource_temporal_overlap/pay_period_closed_interval_rejects_shared_boundary_day
    """
    env = _employer_with_one_february_batch(api)

    response = api.create_payroll_remittance(
        env["employer_id"], dict(SHARED_BOUNDARY_PERIOD),
        make_employer_headers(env["employer_id"]))

    validate_error(response, ERR_PAY_PERIOD_OVERLAP)
    assert_total_count(
        api.list_payroll_remittances(ADMIN, {"employer_id": env["employer_id"]}),
        1, label="batches of the employer after the refused period")


def test_a_pay_period_beginning_the_next_day_is_accepted(api):
    """
    Moved forward by a single day so that no calendar day is shared, the same
    batch is opened as a draft with its declared period stored unchanged.

    "A new batch whose `[pay_period_start, pay_period_end]` interval — **closed
    on both ends** — intersects the interval of another batch of the same
    employer whose status is anything other than `REVERSED` is refused with
    `ERR_PAY_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/pay_period_closed_interval_rejects_shared_boundary_day
    """
    env = _employer_with_one_february_batch(api)
    validate_error(
        api.create_payroll_remittance(
            env["employer_id"], dict(SHARED_BOUNDARY_PERIOD),
            make_employer_headers(env["employer_id"])),
        ERR_PAY_PERIOD_OVERLAP)

    response = api.create_payroll_remittance(
        env["employer_id"], dict(NEXT_DAY_PERIOD),
        make_employer_headers(env["employer_id"]))

    batch = validate_success(response, expected_status=201)
    assert_fields(batch, {
        "pay_period_start": "2026-03-01",
        "pay_period_end": "2026-03-31",
        "pay_date": "2026-04-03",
        "status": "DRAFT",
        "employer_id": env["employer_id"],
    }, label="batch for the following period")
    assert_total_count(
        api.list_payroll_remittances(ADMIN, {"employer_id": env["employer_id"]}),
        2, label="batches of the employer after the accepted period")


def test_the_refused_period_leaves_the_occupying_batch_untouched(api):
    """
    The employer keeps exactly the period it declared: the refusal changes
    neither the bounds nor the state of the batch that occupies February.

    "Pay periods occupy calendar space exclusively."

    Design: Difficulty/resource_temporal_overlap/pay_period_closed_interval_rejects_shared_boundary_day
    """
    env = _employer_with_one_february_batch(api)

    validate_error(
        api.create_payroll_remittance(
            env["employer_id"], dict(SHARED_BOUNDARY_PERIOD),
            make_employer_headers(env["employer_id"])),
        ERR_PAY_PERIOD_OVERLAP)

    occupying = read_remittance(api, env["first_remittance_id"])
    assert_fields(occupying, {
        "pay_period_start": "2026-02-01",
        "pay_period_end": "2026-02-28",
        "status": "DRAFT",
    }, label="batch occupying February")
    assert_amounts(occupying, {"total_deducted_cents": 400000},
                   label="batch occupying February")


def test_a_second_indirect_rollover_inside_the_trailing_year_is_refused(api):
    """
    Asked for on the 364th day after the earlier rollover settled, the follow-up
    indirect rollover falls inside the trailing annual window and is refused, so
    the saver still has exactly one transfer on file.

    "Concretely, a prior rollover settled on 1 May 2026 blocks a request on 30
    April 2027, because that window opens on 1 May 2026, and permits one on 1 May
    2027, because by then the window opens on 2 May 2026."

    Design: Difficulty/resource_temporal_overlap/indirect_rollover_rolling_365_day_window_admits_one_per_participant
    """
    env = _saver_with_one_settled_indirect_rollover(api)

    response = api.create_portability_transfer(
        _second_rollover_payload(env),
        make_participant_headers(env["participant_id"]))

    validate_error(response, ERR_ROLLOVER_FREQUENCY_LIMIT)
    assert_total_count(
        api.list_portability_transfers(
            ADMIN, {"participant_id": env["participant_id"]}),
        1, label="transfers of the saver after the refused request")


def test_one_day_later_the_same_indirect_rollover_is_admitted(api):
    """
    On the 365th day the window has moved past the earlier settlement, and the
    identical request is accepted with its own waterfall recomputed against the
    account's current balance and basis.

    "Second, `basis_portion_cents` is the gross amount multiplied by the source
    account's pre-debit `contribution_basis_cents`, divided by the source
    account's pre-debit `balance_cents`, rounded half up."

    Design: Difficulty/resource_temporal_overlap/indirect_rollover_rolling_365_day_window_admits_one_per_participant
    """
    env = _saver_with_one_settled_indirect_rollover(api)
    validate_error(
        api.create_portability_transfer(
            _second_rollover_payload(env),
            make_participant_headers(env["participant_id"])),
        ERR_ROLLOVER_FREQUENCY_LIMIT)

    set_clock(api, "2027-05-01T00:00:00Z")
    response = api.create_portability_transfer(
        _second_rollover_payload(env),
        make_participant_headers(env["participant_id"]))

    transfer = validate_success(response, expected_status=201)
    assert_fields(transfer, {
        "status": "REQUESTED",
        "transfer_kind": "INDIRECT_60_DAY",
        "requested_on": "2027-05-01",
        "settle_by_date": "2027-06-30",
    }, label="second indirect rollover")
    assert_amounts(transfer, {
        "amount_cents": 100000,
        "fee_cents": 400,
        "basis_portion_cents": 40000,
        "taxable_cents": 60000,
        "withholding_cents": 6000,
        "net_cents": 93600,
        "in_transit_cents": 100000,
    }, label="second indirect rollover")
    assert_amounts(read_account(api, env["account_id"]), {
        "balance_cents": 1000000,
        "contribution_basis_cents": 400000,
    }, label="account after the second rollover leaves")


def test_the_settled_rollover_is_what_occupies_the_window(api):
    """
    The exclusion is driven by the earlier transfer's settlement: it is stored as
    settled on 1 May 2026 with the whole waterfall pinned at request time, and it
    is the one movement the saver's settled-rollover count reports.

    "Three figures on the record are derived rather than supplied:
    `age_at_year_end`, the saver's whole years of age on 31 December of the
    calendar year in which the logical clock currently sits; `catch_up_eligible`,
    true exactly when `age_at_year_end` is at least 50; and
    `indirect_rollover_count`, the number of this saver's portability transfers
    whose kind is `INDIRECT_60_DAY` and whose status is `SETTLED`."

    Design: Difficulty/resource_temporal_overlap/indirect_rollover_rolling_365_day_window_admits_one_per_participant
    """
    env = _saver_with_one_settled_indirect_rollover(api)

    settled = read_transfer(api, env["first_transfer_id"])

    assert_fields(settled, {
        "status": "SETTLED",
        "requested_on": "2026-04-20",
        "settle_by_date": "2026-06-19",
        "settled_on": "2026-05-01",
        "is_taxable_distribution": True,
    }, label="first indirect rollover")
    assert_amounts(settled, {
        "amount_cents": 400000,
        "fee_cents": 1600,
        "basis_portion_cents": 160000,
        "taxable_cents": 240000,
        "withholding_cents": 24000,
        "net_cents": 374400,
        "in_transit_cents": 0,
    }, label="first indirect rollover")
    saver = read_participant(api, env["participant_id"])
    assert saver["indirect_rollover_count"] == 1
