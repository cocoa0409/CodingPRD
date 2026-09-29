"""Travelling members: inbound reciprocity transfers and the advance-coverage horizon."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_reciprocity_transfer,
    coverage_month_keys,
    create_reciprocity_transfer_payload,
    decide_transfer,
    granted_coverage_months,
    read_fund,
    read_participant,
    read_transfer,
    setup_pending_transfer_without_agreement,
    setup_reciprocity_horizon_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]


def test_a_transfer_that_would_buy_three_months_past_a_one_month_allowance_is_refused(api):
    """PRD §3.8: "And the acceptance must not push the participant past the
    fund's advance-coverage horizon: take the participant's current
    `hour_bank_hours` plus the transfer's `hours`, divide by the fund's
    `hours_per_coverage_month` and round down to a whole number of months, and
    that figure may not exceed the fund's `max_advance_coverage_months` less the
    participant's currently outstanding advance coverage months — the count of
    that participant's coverage months whose `status` is `GRANTED` and whose
    month key is strictly later than the logical clock's own year-and-month key.
    An acceptance that would exceed it is refused outright with
    `ERR_COVERAGE_HORIZON_EXCEEDED`, **before any replay runs**."
    PRD §3.8: "A recorded transfer opens with `status` `PENDING` and
    `applied_coverage_months` at 0, and nothing whatsoever is credited to the
    participant until the fund decides on it."

    Design: Difficulty/resource_temporal_overlap/reciprocity_accept_rejected_by_coverage_horizon
    """
    base = setup_reciprocity_horizon_scenario()
    participant_id = base["participant"]["id"]

    assert read_fund(base["sister"]["id"])["reciprocity_agreement_status"] == "EXECUTED"
    granted = granted_coverage_months(participant_id)
    assert len(granted) == 12
    assert coverage_month_keys(granted)[0] == "2026-05"
    assert coverage_month_keys(granted)[-1] == "2027-04"
    assert read_participant(participant_id)["hour_bank_hours"] == 120.00

    validate_error(
        api.decide_reciprocity_transfer(
            base["oversized_transfer"]["id"], {"decision": "ACCEPT"}, ADMIN
        ),
        ApiErrorId.ERR_COVERAGE_HORIZON_EXCEEDED.value,
    )

    refused = read_transfer(base["oversized_transfer"]["id"])
    assert refused["status"] == "PENDING", "the intake gate rejects rather than clipping"
    assert refused["applied_coverage_months"] == 0
    assert len(granted_coverage_months(participant_id)) == 12


def test_a_transfer_that_fits_the_remaining_allowance_is_accepted_and_replayed(api):
    """PRD §3.8: "An accepted transfer moves to `ACCEPTED` and pulls the
    participant's whole eligibility picture forward. The participant's
    `reciprocal_hours_total` is recomputed, and the eligibility replay of section
    3.4 reruns from scratch with this transfer now among the credit events —
    which means it takes its place in the chronological order by its own
    `work_period`, not at the end, and may therefore reshuffle which months
    earlier hours bought."
    PRD §3.8: "The coverage months this transfer's own replay step grants are
    minted with `source` `RECIPROCAL` and with `granting_report_id` null, and
    their count is recorded on the transfer as `applied_coverage_months`. The
    fund's `reciprocal_receipts_cents` is recomputed as the sum of
    `amount_cents` across every `ACCEPTED` transfer for participants of this
    fund."
    PRD §3.4: "Any leftover in excess of the fund's `bank_cap_hours` is
    forfeited: that excess, floored at zero, is added to the participant's
    `forfeited_hours_total`, and the participant's `hour_bank_hours` becomes the
    smaller of `bank_cap_hours` and the leftover."

    Design: Difficulty/resource_temporal_overlap/reciprocity_accept_rejected_by_coverage_horizon
    """
    base = setup_reciprocity_horizon_scenario()
    participant_id = base["participant"]["id"]
    api.decide_reciprocity_transfer(
        base["oversized_transfer"]["id"], {"decision": "ACCEPT"}, ADMIN
    )

    accepted = validate_success(
        api.decide_reciprocity_transfer(
            base["fitting_transfer"]["id"], {"decision": "ACCEPT"}, ADMIN
        )
    )

    assert_reciprocity_transfer(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["applied_coverage_months"] == 1

    participant = read_participant(participant_id)
    assert participant["coverage_through_month"] == "2027-05"
    assert participant["hour_bank_hours"] == 60.00
    assert participant["reciprocal_hours_total"] == 60.00

    granted = granted_coverage_months(participant_id)
    reciprocal = [row for row in granted if row["coverage_month"] == "2027-05"][0]
    assert reciprocal["source"] == "RECIPROCAL"
    assert reciprocal["granting_report_id"] is None

    assert read_fund(base["fund"]["id"])["reciprocal_receipts_cents"] == 49530


def test_a_rejected_transfer_is_terminal_and_credits_nothing(api):
    """PRD §3.8: "Deciding a transfer takes a `decision` of `ACCEPT` or `REJECT`,
    and a transfer that is no longer `PENDING` is refused with
    `ERR_TRANSFER_INVALID_STATE`."
    PRD §3.8: "`REJECT` is the simple branch: the transfer moves to `REJECTED`
    and nothing else changes — no participant roll-up, no coverage month, no fund
    aggregate."

    Design: Corner/state_machines/reciprocity_decision_on_rejected_transfer_returns_transfer_invalid_state
    """
    base = setup_pending_transfer_without_agreement()
    decide_transfer(base["transfer"]["id"], "REJECT")

    validate_error(
        api.decide_reciprocity_transfer(
            base["transfer"]["id"], {"decision": "ACCEPT"}, ADMIN
        ),
        ApiErrorId.ERR_TRANSFER_INVALID_STATE.value,
    )

    transfer = read_transfer(base["transfer"]["id"])
    assert transfer["status"] == "REJECTED"
    assert transfer["applied_coverage_months"] == 0

    participant = read_participant(base["participant"]["id"])
    assert participant["reciprocal_hours_total"] == 0
    assert participant["coverage_through_month"] is None
    assert granted_coverage_months(base["participant"]["id"]) == []

    assert read_fund(base["fund"]["id"])["reciprocal_receipts_cents"] == 0


def test_a_home_fund_sender_and_an_unexecuted_agreement_are_both_refused(api):
    """PRD §3.8: "The sending fund must be a genuine counterparty: a
    `sister_fund_id` naming a fund whose `fund_role` is `HOME`, or naming the
    participant's own fund, is refused with `ERR_SISTER_FUND_INVALID`."
    PRD §3.8: "The sending fund's `reciprocity_agreement_status` must read
    `EXECUTED`, which happens only when the board has carried a
    reciprocity-agreement motion naming that fund; accepting against a fund still
    at `NONE` is refused with `ERR_RECIPROCITY_AGREEMENT_NOT_EXECUTED`."
    PRD §3.8: "Transfers may be listed and filtered by `participant_id`, by
    `sister_fund_id`, by `status`, and by `transfer_type`."

    Design: Corner/validations/reciprocity_referential_guards_reject_home_role_sender_and_unexecuted_agreement
    """
    base = setup_pending_transfer_without_agreement()

    validate_error(
        api.create_reciprocity_transfer(
            create_reciprocity_transfer_payload(
                base["participant"]["id"],
                base["fund"]["id"],
                "PRO_RATA",
                "2026-03",
                120.00,
                99_060,
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_SISTER_FUND_INVALID.value,
    )

    validate_error(
        api.decide_reciprocity_transfer(
            base["transfer"]["id"], {"decision": "ACCEPT"}, ADMIN
        ),
        ApiErrorId.ERR_RECIPROCITY_AGREEMENT_NOT_EXECUTED.value,
    )

    assert read_fund(base["sister"]["id"])["reciprocity_agreement_status"] == "NONE"
    transfer = read_transfer(base["transfer"]["id"])
    assert transfer["status"] == "PENDING"
    assert transfer["applied_coverage_months"] == 0

    _rows, meta = validate_paginated(
        api.list_reciprocity_transfers(
            ADMIN, params={"sister_fund_id": base["sister"]["id"]}
        )
    )
    assert meta["total_count"] == 1
