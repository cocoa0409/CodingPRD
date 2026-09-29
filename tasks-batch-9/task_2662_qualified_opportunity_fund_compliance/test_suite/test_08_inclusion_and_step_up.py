"""Ten-year step-up filings and the holding-tier basis step on inclusion."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_money, assert_percent
from test_helpers.factories import (
    create_inclusion_event_payload,
    create_step_up_election_payload,
)
from test_helpers.fixtures import (
    decertify_fund,
    list_election_inclusion_events,
    make_attested_investor,
    make_deferral_election,
    make_deferred_election_context,
    make_eligible_gain,
    make_fund_asset,
    make_inclusion_event,
    make_self_certified_fund,
    make_step_up_election,
    read_deferral_election,
    read_eligible_gain,
    read_fund,
    read_fund_asset,
    read_investor_statement,
    revoke_deferral_election,
    set_clock,
)
from test_helpers.test_users import ADMIN_HEADERS, make_investor_headers


def _decertified_election_context(api):
    """An election ten years old sitting on a fund a compliance officer decertified."""
    investor = make_attested_investor(api)
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=400000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=400000.00
    )
    set_clock(api, "2036-08-01T00:00:00Z")
    decertify_fund(api, fund["id"])
    return {"investor": investor, "fund": fund, "gain": gain, "election": election}


def test_a_ten_year_hold_is_still_denied_on_a_decertified_fund(api):
    """
    "If `holding_period_days` is below 3653 the election is `DENIED` with
    `denial_reason` `HOLD_UNDER_TEN_YEARS`. Otherwise, if the fund's
    `certification_status` is `DECERTIFIED` the election is `DENIED` with
    `denial_reason` `FUND_DECERTIFIED`." "`stepped_up_basis` is `claimed_fmv` when
    granted and 0.00 when denied."

    Design: Difficulty/cross_entity_state_dependency/step_up_denied_because_fund_decertified
    """
    context = _decertified_election_context(api)

    step_up = make_step_up_election(
        api,
        context["election"]["id"],
        investor_id=context["investor"]["id"],
        claimed_fmv=900000.00,
    )

    assert step_up["status"] == "DENIED"
    assert step_up["denial_reason"] == "FUND_DECERTIFIED"
    assert step_up["holding_period_days"] == 3653
    assert_money(step_up["stepped_up_basis"], 0.00, "stepped_up_basis")
    assert step_up["election_date"].startswith("2036-08-01T00:00:00")
    election_after = read_deferral_election(api, context["election"]["id"])
    assert election_after["status"] == "INCLUDED_FULL"
    assert_money(election_after["current_basis"], 0.00, "current_basis")
    assert float(election_after["step_up_applied_pct"]) == 0.0000


def test_the_decertification_inclusion_event_applies_the_ten_year_basis_step(api):
    """
    "at least 3653 days is `TEN_YEAR`" and "The basis step that follows from the tier
    is 0.15 for `SEVEN_YEAR` and `TEN_YEAR`, 0.10 for `FIVE_YEAR`, and 0.00 for
    `UNDER_FIVE`." "`gross_inclusion_amount` is the election's `elected_amount`
    multiplied by `included_fraction`, rounded half up to two decimal places.
    `basis_offset_amount` is `elected_amount` multiplied by `included_fraction` and by
    the tier's step, rounded half up to two decimal places. `net_inclusion_amount` is
    the gross less the offset, rounded half up to two decimal places."

    Design: Difficulty/cross_entity_state_dependency/step_up_denied_because_fund_decertified
    """
    context = _decertified_election_context(api)

    events = list_election_inclusion_events(api, context["election"]["id"])

    assert len(events) == 1, "Decertification writes exactly one inclusion event"
    event = events[0]
    assert event["event_type"] == "FUND_DECERTIFICATION"
    assert float(event["included_fraction"]) == 1.0000
    assert event["holding_days"] == 3653
    assert event["holding_tier_applied"] == "TEN_YEAR"
    assert_money(event["gross_inclusion_amount"], 400000.00, "gross_inclusion_amount")
    assert_money(event["basis_offset_amount"], 60000.00, "basis_offset_amount")
    assert_money(event["net_inclusion_amount"], 340000.00, "net_inclusion_amount")
    assert event["is_full"] is True
    election_after = read_deferral_election(api, context["election"]["id"])
    # `included_amount` (and therefore the `included_gain_total` rollup that sums
    # it) is not given a formula anywhere in the PRD: §3.10 says only that
    # recording an event "recomputes the election's `included_amount`" and that
    # the figure "grow[s]" on a further event. A faithful reader may accumulate
    # either `gross_inclusion_amount` or `net_inclusion_amount`, so the value is
    # not asserted here where the 0.15 TEN_YEAR step makes the two differ.
    assert_money(election_after["deferred_remaining"], 0.00, "deferred_remaining")
    statement = read_investor_statement(api, context["investor"]["id"])
    assert_money(
        statement["deferred_gain_outstanding"], 0.00, "deferred_gain_outstanding"
    )


def test_one_partial_event_moves_the_election_and_both_investor_rollups(api):
    """
    "From `DEFERRED`, an event leaving the running fraction total below 1.0000 moves
    the election `DEFERRED → INCLUDED_PARTIAL`". "Recording the event recomputes the
    election's `included_amount`, `included_fraction_total` and `deferred_remaining`,
    and then recomputes the investor's `deferred_gain_outstanding` and
    `included_gain_total`." "The basis step that follows from the tier is 0.15 for
    `SEVEN_YEAR` and `TEN_YEAR`, 0.10 for `FIVE_YEAR`, and 0.00 for `UNDER_FIVE`."

    Design: Corner/state_machines/partial_inclusion_event_updates_election_and_investor
    """
    context = make_deferred_election_context(api)
    election = context["election"]
    investor = context["investor"]

    event = make_inclusion_event(
        api,
        election["id"],
        investor_id=investor["id"],
        event_type="PARTIAL_REDEMPTION",
        included_fraction=0.4000,
    )

    assert event["holding_days"] == 0
    assert event["holding_tier_applied"] == "UNDER_FIVE"
    assert_money(event["gross_inclusion_amount"], 40000.00, "gross_inclusion_amount")
    assert_money(event["basis_offset_amount"], 0.00, "basis_offset_amount")
    assert_money(event["net_inclusion_amount"], 40000.00, "net_inclusion_amount")
    assert event["is_full"] is False
    election_after = read_deferral_election(api, election["id"])
    assert election_after["status"] == "INCLUDED_PARTIAL"
    assert_money(election_after["included_amount"], 40000.00, "included_amount")
    assert_percent(
        election_after["included_fraction_total"], 0.4000, "included_fraction_total"
    )
    assert_money(election_after["deferred_remaining"], 60000.00, "deferred_remaining")
    assert election_after["version"] == 2
    investor_after = validate_success(
        api.get_investor(investor["id"], context["investor_headers"])
    )
    assert_money(
        investor_after["deferred_gain_outstanding"], 60000.00, "deferred_gain_outstanding"
    )
    assert_money(investor_after["included_gain_total"], 40000.00, "included_gain_total")
    gain_after = read_eligible_gain(api, context["gain"]["id"])
    assert gain_after["status"] == "FULLY_INVESTED"
    assert_money(gain_after["elected_amount"], 100000.00, "elected_amount")
    assert_money(gain_after["unelected_amount"], 0.00, "unelected_amount")
    assert_money(
        read_fund(api, context["fund"]["id"])["deferred_gain_committed"],
        100000.00,
        "deferred_gain_committed",
    )


def test_both_halves_of_an_odd_cent_election_round_up_independently(api):
    """
    "`gross_inclusion_amount` is the election's `elected_amount` multiplied by
    `included_fraction`, rounded half up to two decimal places." "Recording the event
    recomputes the election's `included_amount`, `included_fraction_total` and
    `deferred_remaining`". "**Money** — every dollar field, whether supplied by a client
    or derived by the server — is carried to exactly 2 decimal places and rounded half
    up."

    Design: Corner/calculations/inclusion_amount_rounds_half_up_at_the_half_cent
    """
    context = make_deferred_election_context(
        api, eligible_amount=99999.99, elected_amount=99999.99
    )
    election = context["election"]

    event = make_inclusion_event(
        api,
        election["id"],
        investor_id=context["investor"]["id"],
        event_type="SALE_OF_INTEREST",
        included_fraction=0.5000,
    )

    assert_money(event["gross_inclusion_amount"], 50000.00, "gross_inclusion_amount")
    assert_money(event["basis_offset_amount"], 0.00, "basis_offset_amount")
    assert_money(event["net_inclusion_amount"], 50000.00, "net_inclusion_amount")
    assert event["is_full"] is False
    election_after = read_deferral_election(api, election["id"])
    assert election_after["status"] == "INCLUDED_PARTIAL"
    assert_percent(
        election_after["included_fraction_total"], 0.5000, "included_fraction_total"
    )
    assert_money(election_after["included_amount"], 50000.00, "included_amount")
    assert_money(election_after["deferred_remaining"], 50000.00, "deferred_remaining")
    halves = round(
        float(election_after["included_amount"])
        + float(election_after["deferred_remaining"]),
        2,
    )
    assert halves == 100000.00, (
        "each field rounds half up independently, so the two halves sum one cent "
        "above the elected amount"
    )


def test_the_three_step_up_filing_guards_each_refuse_the_filing_outright(api):
    """
    "Because a shorter hold produces a recorded denial rather than a rejection,
    `ERR_TEN_YEAR_HOLD_NOT_MET` covers only the filing whose hold cannot be evaluated at
    all: an election whose `investment_date` lies strictly after the logical clock."
    "Every listed asset must belong to the election's fund, must be `HELD`, must appear
    at most once, and the list must be non-empty when supplied, or the filing is
    rejected with `ERR_DISPOSITION_SEQUENCE_INVALID`". "The one deferral-election status
    that bars a filing outright is `REVOKED`, which yields `ERR_ELECTION_REVOKED`: a
    revoked election has no qualifying investment left to step up."

    Design: Corner/errors/step_up_election_filing_guards_rejected
    """
    investor = make_attested_investor(
        api, legal_name="Step Guard Trust", taxpayer_type="TRUST"
    )
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=300000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    fund = make_self_certified_fund(
        api, name="Step Guard QOF", entity_type="PARTNERSHIP"
    )
    asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="CASH",
        acquisition_date="2026-01-05T00:00:00Z",
        unadjusted_cost_basis=150000.00,
        afs_fair_value=150000.00,
    )
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=300000.00
    )
    assert election["investment_date"].startswith("2026-08-01T00:00:00")
    headers = make_investor_headers(investor["id"])

    rewound = set_clock(api, "2026-07-15T00:00:00Z")
    assert rewound["previous_utc"].startswith("2026-08-01T00:00:00")
    unevaluable = api.create_step_up_election(
        election["id"], create_step_up_election_payload(claimed_fmv=500000.00), headers
    )

    validate_error(unevaluable, ApiErrorId.TEN_YEAR_HOLD_NOT_MET.value, 422)

    set_clock(api, "2036-08-01T00:00:00Z")
    duplicated = api.create_step_up_election(
        election["id"],
        create_step_up_election_payload(
            claimed_fmv=500000.00, disposition_sequence=[asset["id"], asset["id"]]
        ),
        headers,
    )
    empty = api.create_step_up_election(
        election["id"],
        create_step_up_election_payload(claimed_fmv=500000.00, disposition_sequence=[]),
        headers,
    )

    validate_error(duplicated, ApiErrorId.DISPOSITION_SEQUENCE_INVALID.value, 422)
    validate_error(empty, ApiErrorId.DISPOSITION_SEQUENCE_INVALID.value, 422)
    rows, meta = validate_paginated(
        api.list_step_up_elections(election["id"], ADMIN_HEADERS, {"limit": 100})
    )
    assert rows == []
    assert meta["total_count"] == 0, "three rejections wrote no step-up row"
    still_deferred = read_deferral_election(api, election["id"])
    assert still_deferred["status"] == "DEFERRED"
    assert_money(still_deferred["current_basis"], 0.00, "current_basis")
    assert float(still_deferred["step_up_applied_pct"]) == 0.0000
    assert not read_fund_asset(api, asset["id"])["disposition_sequence_index"]

    revoked = revoke_deferral_election(api, election["id"], investor["id"])
    assert revoked["status"] == "REVOKED"

    barred = api.create_step_up_election(
        election["id"], create_step_up_election_payload(claimed_fmv=500000.00), headers
    )

    validate_error(barred, ApiErrorId.ELECTION_REVOKED.value, 409)
    released = read_eligible_gain(api, gain["id"])
    assert released["status"] == "ELIGIBLE"
    assert_money(released["elected_amount"], 0.00, "elected_amount")
    assert_money(released["unelected_amount"], 300000.00, "unelected_amount")


def test_the_running_fraction_total_and_not_the_single_event_is_what_is_capped(api):
    """
    "`is_full` is true exactly when the election's `included_fraction_total` plus this
    event's `included_fraction`, rounded half up to four decimal places, reaches
    1.0000. The election may never be over-included: that same sum must be at most
    1.0000, and a request that would exceed the remaining fraction is rejected with
    `ERR_INCLUSION_FRACTION_EXCEEDS_REMAINING`." "From `INCLUDED_PARTIAL`, a further
    event still short of 1.0000 is a self-loop `INCLUDED_PARTIAL → INCLUDED_PARTIAL` in
    which `included_amount` and `included_fraction_total` grow while `deferred_remaining`
    shrinks, and an event closing the remaining fraction moves it `INCLUDED_PARTIAL →
    INCLUDED_FULL`, again zeroing `deferred_remaining` and marking the event full."

    Design: Corner/errors/inclusion_fraction_over_remaining_rejected
    """
    investor = make_attested_investor(
        api, legal_name="Fraction Ceiling Trust", taxpayer_type="TRUST"
    )
    gain = make_eligible_gain(
        api,
        investor["id"],
        gain_character="SHORT_TERM_CAPITAL",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    fund = make_self_certified_fund(
        api, name="Fraction Ceiling QOF", entity_type="CORPORATION"
    )
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=100000.00
    )
    headers = make_investor_headers(investor["id"])

    first = make_inclusion_event(
        api,
        election["id"],
        investor_id=investor["id"],
        event_type="PARTIAL_REDEMPTION",
        included_fraction=0.6000,
    )

    assert_money(first["gross_inclusion_amount"], 60000.00, "gross_inclusion_amount")
    assert_money(first["net_inclusion_amount"], 60000.00, "net_inclusion_amount")
    assert first["holding_tier_applied"] == "UNDER_FIVE"
    after_first = read_deferral_election(api, election["id"])
    assert after_first["status"] == "INCLUDED_PARTIAL"
    assert_percent(
        after_first["included_fraction_total"], 0.6000, "included_fraction_total"
    )
    assert_money(after_first["deferred_remaining"], 40000.00, "deferred_remaining")

    over = api.create_inclusion_event(
        election["id"],
        create_inclusion_event_payload(
            event_type="PARTIAL_REDEMPTION", included_fraction=0.5000
        ),
        headers,
    )

    validate_error(over, ApiErrorId.INCLUSION_FRACTION_EXCEEDS_REMAINING.value, 422)
    unchanged = read_deferral_election(api, election["id"])
    assert_percent(
        unchanged["included_fraction_total"], 0.6000, "included_fraction_total"
    )
    assert_money(unchanged["included_amount"], 60000.00, "included_amount")
    assert len(list_election_inclusion_events(api, election["id"])) == 1

    closing = make_inclusion_event(
        api,
        election["id"],
        investor_id=investor["id"],
        event_type="SALE_OF_INTEREST",
        included_fraction=0.4000,
    )

    assert_money(closing["gross_inclusion_amount"], 40000.00, "gross_inclusion_amount")
    assert_money(closing["net_inclusion_amount"], 40000.00, "net_inclusion_amount")
    assert closing["is_full"] is True
    closed = read_deferral_election(api, election["id"])
    assert closed["status"] == "INCLUDED_FULL"
    assert_percent(closed["included_fraction_total"], 1.0000, "included_fraction_total")
    assert_money(closed["included_amount"], 100000.00, "included_amount")
    assert_money(closed["deferred_remaining"], 0.00, "deferred_remaining")
    statement = read_investor_statement(api, investor["id"])
    assert_money(statement["included_gain_total"], 100000.00, "included_gain_total")
    assert_money(
        statement["deferred_gain_outstanding"], 0.00, "deferred_gain_outstanding"
    )


def test_the_statement_reconciles_two_gains_two_elections_and_one_event(api):
    """
    "It returns the `investor_id` together with `eligible_gain_total`,
    `deferred_gain_outstanding` and `included_gain_total` as defined in §3.1, plus
    `election_count`, the number of deferral elections belonging to that investor, and
    `inclusion_event_count`, the number of inclusion events recorded against those
    elections." "when `deadline_basis` is `PARTNERSHIP_YEAR_END` or
    `SECTION_1231_YEAR_END`, it is the `pass_through_year_end`."

    Design: Corner/endpoints/investor_statement_computed_read_matches_election_rollups
    """
    investor = make_attested_investor(
        api, legal_name="Stella Statement", taxpayer_type="INDIVIDUAL"
    )
    first_gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=150000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    second_gain = make_eligible_gain(
        api,
        investor["id"],
        gain_character="SECTION_1231_NET",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SECTION_1231_YEAR_END",
        pass_through_year_end="2026-07-31T00:00:00Z",
    )
    assert second_gain["window_basis_date"].startswith("2026-07-31T00:00:00")
    assert second_gain["investment_deadline"].startswith("2027-01-27T00:00:00")
    fund = make_self_certified_fund(
        api, name="Statement Fund", entity_type="CORPORATION"
    )
    first_election = make_deferral_election(
        api, investor["id"], first_gain["id"], fund["id"], elected_amount=150000.00
    )
    second_election = make_deferral_election(
        api, investor["id"], second_gain["id"], fund["id"], elected_amount=100000.00
    )
    event = make_inclusion_event(
        api,
        first_election["id"],
        investor_id=investor["id"],
        event_type="PARTIAL_REDEMPTION",
        included_fraction=0.4000,
    )
    assert_money(event["net_inclusion_amount"], 60000.00, "net_inclusion_amount")
    assert_money(event["basis_offset_amount"], 0.00, "basis_offset_amount")

    statement = read_investor_statement(api, investor["id"])

    assert statement["investor_id"] == investor["id"]
    assert_money(statement["eligible_gain_total"], 250000.00, "eligible_gain_total")
    assert_money(statement["included_gain_total"], 60000.00, "included_gain_total")
    assert_money(
        statement["deferred_gain_outstanding"], 190000.00, "deferred_gain_outstanding"
    )
    assert statement["election_count"] == 2
    assert statement["inclusion_event_count"] == 1
    stored = validate_success(
        api.get_investor(investor["id"], make_investor_headers(investor["id"]))
    )
    for field in (
        "eligible_gain_total",
        "included_gain_total",
        "deferred_gain_outstanding",
    ):
        assert_money(statement[field], float(stored[field]), field)
    assert read_deferral_election(api, first_election["id"])["status"] == (
        "INCLUDED_PARTIAL"
    )
    assert read_deferral_election(api, second_election["id"])["status"] == "DEFERRED"


def test_a_hold_of_exactly_3653_days_grants_and_pins_the_disposal_order(api):
    """
    "The ten-year boundary is inclusive at 3653: a `holding_period_days` of exactly 3653
    grants, and 3652 denies with `HOLD_UNDER_TEN_YEARS`." "Otherwise it is `GRANTED` with
    `denial_reason` `NONE`. `stepped_up_basis` is `claimed_fmv` when granted". "A granted
    election drives the deferral election `DEFERRED → STEPPED_UP`, setting its
    `current_basis` to the `claimed_fmv`, its `step_up_applied_pct` to 1.0000 and its
    `holding_tier` to `TEN_YEAR`. When a `disposition_sequence` was supplied, position `i`
    of the list, counting from 1, is written to the `disposition_sequence_index` of the
    asset named at that position."

    Design: Corner/endpoints/step_up_election_granted_at_exactly_ten_years
    """
    investor = make_attested_investor(
        api, legal_name="Theo Tenyear", taxpayer_type="INDIVIDUAL"
    )
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=200000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    fund = make_self_certified_fund(api, name="Ten Year Fund", entity_type="CORPORATION")
    first_asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-10T00:00:00Z",
        unadjusted_cost_basis=600000.00,
        afs_fair_value=600000.00,
        original_use_in_zone=True,
    )
    second_asset = make_fund_asset(
        api,
        fund["id"],
        asset_class="QOZ_BUSINESS_PROPERTY",
        acquisition_date="2026-01-20T00:00:00Z",
        unadjusted_cost_basis=400000.00,
        afs_fair_value=400000.00,
        original_use_in_zone=True,
    )
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=200000.00
    )
    assert election["investment_date"].startswith("2026-08-01T00:00:00")
    set_clock(api, "2036-08-01T00:00:00Z")

    step_up = make_step_up_election(
        api,
        election["id"],
        investor_id=investor["id"],
        claimed_fmv=340000.00,
        disposition_sequence=[second_asset["id"], first_asset["id"]],
    )

    assert step_up["holding_period_days"] == 3653
    assert step_up["status"] == "GRANTED"
    assert step_up["denial_reason"] == "NONE"
    assert step_up["deferral_election_id"] == election["id"]
    assert_money(step_up["stepped_up_basis"], 340000.00, "stepped_up_basis")
    stepped = read_deferral_election(api, election["id"])
    assert stepped["status"] == "STEPPED_UP"
    assert_money(stepped["current_basis"], 340000.00, "current_basis")
    assert_percent(stepped["step_up_applied_pct"], 1.0000, "step_up_applied_pct")
    assert stepped["holding_tier"] == "TEN_YEAR"
    # The request order is authoritative: not creation order, not identifier order.
    assert read_fund_asset(api, second_asset["id"])["disposition_sequence_index"] == 1
    assert read_fund_asset(api, first_asset["id"])["disposition_sequence_index"] == 2
    assert read_eligible_gain(api, gain["id"])["status"] == "FULLY_INVESTED"
    assert_money(
        read_investor_statement(api, investor["id"])["deferred_gain_outstanding"],
        200000.00,
        "deferred_gain_outstanding",
    )


def test_one_event_agrees_with_the_election_and_the_statement_at_once(api):
    """
    "`gross_inclusion_amount` is the election's `elected_amount` multiplied by
    `included_fraction`, rounded half up to two decimal places."
    "The basis step that follows from the tier is 0.15 for `SEVEN_YEAR` and `TEN_YEAR`,
    0.10 for `FIVE_YEAR`, and 0.00 for `UNDER_FIVE`."
    "Recording the event recomputes the election's `included_amount`,
    `included_fraction_total` and `deferred_remaining`, and then recomputes the
    investor's `deferred_gain_outstanding` and `included_gain_total`."
    "From `DEFERRED`, an event leaving the running fraction total below 1.0000 moves the
    election `DEFERRED → INCLUDED_PARTIAL`"

    Design: Corner/consistency_model/inclusion_event_rollups_visible_without_lag
    """
    investor = make_attested_investor(
        api,
        legal_name="No Lag Holdings LLC",
        taxpayer_type="PARTNERSHIP",
        tax_year_end_month=12,
    )
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=250000.00,
        realization_date="2026-07-01T00:00:00Z",
    )
    fund = make_self_certified_fund(api, name="No Lag QOF", entity_type="PARTNERSHIP")
    election = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=200000.00
    )

    event = make_inclusion_event(
        api,
        election["id"],
        investor_id=investor["id"],
        event_type="PARTIAL_REDEMPTION",
        included_fraction=0.2500,
    )
    assert event["event_date"].startswith("2026-08-01T00:00:00")
    assert event["holding_tier_applied"] == "UNDER_FIVE"
    assert event["is_full"] is False
    assert_money(event["gross_inclusion_amount"], 50000.00, "gross_inclusion_amount")
    assert_money(event["basis_offset_amount"], 0.00, "basis_offset_amount")
    assert_money(event["net_inclusion_amount"], 50000.00, "net_inclusion_amount")

    election_after = read_deferral_election(api, election["id"])
    assert election_after["status"] == "INCLUDED_PARTIAL"
    assert_money(election_after["included_amount"], 50000.00, "included_amount")
    assert_percent(
        election_after["included_fraction_total"], 0.2500, "included_fraction_total"
    )
    assert_money(election_after["deferred_remaining"], 150000.00, "deferred_remaining")

    statement = read_investor_statement(api, investor["id"])
    assert_money(statement["eligible_gain_total"], 250000.00, "eligible_gain_total")
    assert_money(
        statement["deferred_gain_outstanding"], 150000.00, "deferred_gain_outstanding"
    )
    assert_money(statement["included_gain_total"], 50000.00, "included_gain_total")
    assert statement["election_count"] == 1
    assert statement["inclusion_event_count"] == 1

    gain_after = read_eligible_gain(api, gain["id"])
    assert_money(gain_after["elected_amount"], 200000.00, "EligibleGain.elected_amount")
    assert_money(
        gain_after["unelected_amount"], 50000.00, "EligibleGain.unelected_amount"
    )
