"""Deferral elections: the gate ladder, the 180-day boundary and revocation."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_gain_dollars_conserved, assert_money
from test_helpers.factories import create_deferral_election_payload
from test_helpers.fixtures import (
    attest_investor,
    fund_version,
    list_gain_elections,
    make_attested_investor,
    make_deferral_election,
    make_eligible_gain,
    make_fund,
    make_investor,
    make_self_certified_fund,
    read_deferral_election,
    read_eligible_gain,
    read_fund,
    read_investor_statement,
    revoke_deferral_election,
    set_clock,
)
from test_helpers.test_users import make_investor_headers


def test_the_fund_certification_gate_outranks_the_closed_180_day_window(api):
    """
    "Fund certification gate: the owning fund's `certification_status` must be
    `SELF_CERTIFIED` — `ERR_FUND_NOT_CERTIFIED` (409)." That gate stands at rule 11
    while "The 180-day window has not closed — `ERR_180_DAY_WINDOW_CLOSED` (422), on
    election create" stands at rule 19, and "the **first** check that fails
    determines the response."

    Design: Difficulty/priority_pair_validation_conflict/fund_state_gate_precedes_180_day_window
    """
    investor = make_attested_investor(api)
    fund = make_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-01-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    assert gain["investment_deadline"].startswith("2026-06-30T00:00:00")

    response = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=100000.00
        ),
        make_investor_headers(investor["id"]),
    )

    error = validate_error(response, ApiErrorId.FUND_NOT_CERTIFIED.value, 409)
    assert error["error_id"] != ApiErrorId.WINDOW_180_DAY_CLOSED.value
    assert response.status_code != 422


def test_the_refused_election_writes_neither_gain_nor_fund_nor_investor(api):
    """
    "a request that fails any check in §2.11 mutates nothing." "The gain is created
    with `status` `ELIGIBLE`, `elected_amount` at 0.00, `unelected_amount` equal to
    `eligible_amount`, and `expired_at` empty".

    Design: Difficulty/priority_pair_validation_conflict/fund_state_gate_precedes_180_day_window
    """
    investor = make_attested_investor(api)
    fund = make_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-01-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )

    api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=100000.00
        ),
        make_investor_headers(investor["id"]),
    )

    gain_after = read_eligible_gain(api, gain["id"])
    assert gain_after["status"] == "ELIGIBLE"
    assert_money(gain_after["elected_amount"], 0.00, "elected_amount")
    assert_money(gain_after["unelected_amount"], 100000.00, "unelected_amount")
    fund_after = read_fund(api, fund["id"])
    assert fund_after["certification_status"] == "DRAFT"
    assert_money(fund_after["deferred_gain_committed"], 0.00, "deferred_gain_committed")
    assert fund_after["version"] == fund["version"]
    statement = read_investor_statement(api, investor["id"])
    assert_money(
        statement["deferred_gain_outstanding"], 0.00, "deferred_gain_outstanding"
    )
    assert statement["election_count"] == 0


def test_the_attestation_gate_outranks_the_election_amount_ceiling(api):
    """
    "Investor attestation: `compliance_attestation_status` must be `ATTESTED` —
    `ERR_INVESTOR_NOT_ATTESTED` (422), on election create and step-up filing." That gate stands at rule
    16 while "Election amount ceiling — `ERR_ELECTED_AMOUNT_EXCEEDS_GAIN` (422), on
    election create" stands at rule 35.

    Design: Difficulty/priority_pair_validation_conflict/attestation_gate_precedes_amount_ceiling
    """
    investor = make_investor(api, taxpayer_type="TRUST")
    assert investor["compliance_attestation_status"] == "PENDING"
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        gain_character="SHORT_TERM_CAPITAL",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )

    response = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=250000.00
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(response, ApiErrorId.INVESTOR_NOT_ATTESTED.value, 422)
    assert not list_gain_elections(api, gain["id"])


def test_attesting_the_investor_exposes_the_amount_ceiling_beneath_it(api):
    """
    "`elected_amount` may not exceed the gain's current `unelected_amount`, or the
    request is rejected with `ERR_ELECTED_AMOUNT_EXCEEDS_GAIN`." "Only an `ATTESTED`
    investor may make a deferral election or file a step-up election; a `PENDING` or
    `BLOCKED` investor attempting either is rejected with
    `ERR_INVESTOR_NOT_ATTESTED`."

    Design: Difficulty/priority_pair_validation_conflict/attestation_gate_precedes_amount_ceiling
    """
    investor = make_investor(api, taxpayer_type="TRUST")
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        gain_character="SHORT_TERM_CAPITAL",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=250000.00
        ),
        make_investor_headers(investor["id"]),
    )

    attested = attest_investor(api, investor["id"], "ATTESTED")
    assert attested["compliance_attestation_status"] == "ATTESTED"
    response = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=250000.00
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(response, ApiErrorId.ELECTED_AMOUNT_EXCEEDS_GAIN.value, 422)
    assert not list_gain_elections(api, gain["id"])
    fund_after = read_fund(api, fund["id"])
    assert fund_after["version"] == fund["version"]
    assert_money(fund_after["deferred_gain_committed"], 0.00, "deferred_gain_committed")


def test_an_election_exactly_180_days_from_the_basis_is_timely(api):
    """
    "The boundary is inclusive on both ends: a `days_from_basis` of exactly 180 is
    timely, 181 is rejected with `ERR_180_DAY_WINDOW_CLOSED`". "Timeliness is decided
    by `days_from_basis`, the number of whole elapsed days from the gain's
    `window_basis_date` to the election's `investment_date`, with any partial day
    discarded."

    Design: Difficulty/boundary_precision_check/deferral_election_day_180_boundary
    """
    investor = make_attested_investor(api)
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-02-02T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    assert gain["investment_deadline"].startswith("2026-08-01T00:00:00")

    response = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=50000.00
        ),
        make_investor_headers(investor["id"]),
    )
    election = validate_success(response, 201)

    assert election["days_from_basis"] == 180
    assert election["status"] == "DEFERRED"
    gain_after = read_eligible_gain(api, gain["id"])
    assert gain_after["status"] == "PARTIALLY_INVESTED"
    assert_money(gain_after["elected_amount"], 50000.00, "elected_amount")
    assert_money(gain_after["unelected_amount"], 50000.00, "unelected_amount")


def test_an_election_181_days_from_the_basis_is_out_of_time(api):
    """
    "The 180-day window has not closed — `ERR_180_DAY_WINDOW_CLOSED` (422), on
    election create." "Two ledgers outside the gain also move on every election: the
    fund's `deferred_gain_committed`, which is the sum of `elected_amount` over that
    fund's elections whose `status` is not `REVOKED`, and the investor's
    `deferred_gain_outstanding`."

    Design: Difficulty/boundary_precision_check/deferral_election_day_180_boundary
    """
    investor = make_attested_investor(api)
    fund = make_self_certified_fund(api)
    timely_gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-02-02T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    make_deferral_election(
        api,
        investor["id"],
        timely_gain["id"],
        fund["id"],
        elected_amount=50000.00,
    )

    late_gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-02-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    assert late_gain["investment_deadline"].startswith("2026-07-31T00:00:00")
    response = api.create_deferral_election(
        create_deferral_election_payload(
            late_gain["id"],
            fund["id"],
            fund_version(api, fund["id"]),
            elected_amount=50000.00,
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(response, ApiErrorId.WINDOW_180_DAY_CLOSED.value, 422)
    assert not list_gain_elections(api, late_gain["id"])
    late_after = read_eligible_gain(api, late_gain["id"])
    assert late_after["status"] == "ELIGIBLE"
    assert_money(late_after["unelected_amount"], 100000.00, "unelected_amount")
    assert_money(
        read_fund(api, fund["id"])["deferred_gain_committed"],
        50000.00,
        "deferred_gain_committed",
    )


def test_a_blocked_investor_cannot_elect_gain_into_a_certified_fund(api):
    """
    "Only an `ATTESTED` investor may make a deferral election or file a step-up
    election; a `PENDING` or `BLOCKED` investor attempting either is rejected with
    `ERR_INVESTOR_NOT_ATTESTED`."

    Design: Difficulty/cross_entity_state_dependency/deferral_election_blocked_by_investor_attestation
    """
    investor = make_investor(
        api, taxpayer_type="C_CORPORATION", compliance_attestation_status="BLOCKED"
    )
    assert investor["compliance_attestation_status"] == "BLOCKED"
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        gain_character="SECTION_1231_NET",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )

    response = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=100000.00
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(response, ApiErrorId.INVESTOR_NOT_ATTESTED.value, 422)
    fund_after = read_fund(api, fund["id"])
    assert fund_after["version"] == fund["version"]
    assert_money(fund_after["deferred_gain_committed"], 0.00, "deferred_gain_committed")


def test_moving_the_investor_to_attested_unblocks_the_same_election(api):
    """
    "it initializes `initial_basis` and `current_basis` at 0.00,
    `step_up_applied_pct` at 0.0000, `holding_tier` at `UNDER_FIVE`,
    `included_amount` at 0.00, `included_fraction_total` at 0.0000,
    `revoked_reason_code` at `NONE`, `deferred_remaining` at the full
    `elected_amount`, and `status` at `DEFERRED`."

    Design: Difficulty/cross_entity_state_dependency/deferral_election_blocked_by_investor_attestation
    """
    investor = make_investor(
        api, taxpayer_type="C_CORPORATION", compliance_attestation_status="BLOCKED"
    )
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        gain_character="SECTION_1231_NET",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=100000.00
        ),
        make_investor_headers(investor["id"]),
    )
    attest_investor(api, investor["id"], "ATTESTED")

    response = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"],
            fund["id"],
            fund_version(api, fund["id"]),
            elected_amount=100000.00,
        ),
        make_investor_headers(investor["id"]),
    )
    election = validate_success(response, 201)

    assert election["days_from_basis"] == 31
    assert election["status"] == "DEFERRED"
    assert election["holding_tier"] == "UNDER_FIVE"
    assert election["revoked_reason_code"] == "NONE"
    assert_money(election["initial_basis"], 0.00, "initial_basis")
    assert_money(election["current_basis"], 0.00, "current_basis")
    assert_money(election["deferred_remaining"], 100000.00, "deferred_remaining")
    assert float(election["step_up_applied_pct"]) == 0.0000
    gain_after = read_eligible_gain(api, gain["id"])
    assert gain_after["status"] == "FULLY_INVESTED"
    assert_money(gain_after["unelected_amount"], 0.00, "unelected_amount")
    statement = read_investor_statement(api, investor["id"])
    assert_money(
        statement["deferred_gain_outstanding"], 100000.00, "deferred_gain_outstanding"
    )
    assert_money(
        read_fund(api, fund["id"])["deferred_gain_committed"],
        100000.00,
        "deferred_gain_committed",
    )


def test_revoking_one_of_two_elections_walks_the_gain_back_one_step(api):
    """
    "the gain's `elected_amount` falls and its `unelected_amount` rises by exactly
    the revoked election's `elected_amount`; because the gain's elected total changed,
    its `status` is re-derived and walks back down — `FULLY_INVESTED →
    PARTIALLY_INVESTED` when other non-revoked elections remain against the gain".

    Design: Difficulty/compensating_invariant/eligible_gain_dollars_conserved_across_revocation
    """
    investor = make_attested_investor(api)
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=400000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    first = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=250000.00
    )
    second = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=150000.00
    )
    assert read_eligible_gain(api, gain["id"])["status"] == "FULLY_INVESTED"

    revoked = revoke_deferral_election(
        api,
        second["id"],
        investor_id=investor["id"],
        revoked_reason_code="INVESTOR_WITHDRAWAL",
    )

    assert revoked["status"] == "REVOKED"
    assert revoked["revoked_reason_code"] == "INVESTOR_WITHDRAWAL"
    assert_money(revoked["deferred_remaining"], 0.00, "deferred_remaining")
    gain_after = read_eligible_gain(api, gain["id"])
    assert gain_after["status"] == "PARTIALLY_INVESTED"
    assert_money(gain_after["elected_amount"], 250000.00, "elected_amount")
    assert_money(gain_after["unelected_amount"], 150000.00, "unelected_amount")
    assert_gain_dollars_conserved(gain_after, list_gain_elections(api, gain["id"]))
    assert read_deferral_election(api, first["id"])["status"] == "DEFERRED"
    assert_money(
        read_fund(api, fund["id"])["deferred_gain_committed"],
        250000.00,
        "deferred_gain_committed",
    )
    assert_money(
        read_investor_statement(api, investor["id"])["deferred_gain_outstanding"],
        250000.00,
        "deferred_gain_outstanding",
    )


def test_revoking_every_election_restores_the_gain_to_its_original_dollars(api):
    """
    "After the pair of actions the gain's `unelected_amount` is identical to its
    value before the election was ever created." "`PARTIALLY_INVESTED → ELIGIBLE`
    likewise when it was the only one".

    Design: Difficulty/compensating_invariant/eligible_gain_dollars_conserved_across_revocation
    """
    investor = make_attested_investor(api)
    fund = make_self_certified_fund(api)
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=400000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    first = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=250000.00
    )
    second = make_deferral_election(
        api, investor["id"], gain["id"], fund["id"], elected_amount=150000.00
    )

    revoke_deferral_election(
        api,
        second["id"],
        investor_id=investor["id"],
        revoked_reason_code="INVESTOR_WITHDRAWAL",
    )
    revoke_deferral_election(
        api,
        first["id"],
        investor_id=investor["id"],
        revoked_reason_code="INVESTOR_WITHDRAWAL",
    )

    gain_after = read_eligible_gain(api, gain["id"])
    assert gain_after["status"] == "ELIGIBLE"
    assert_money(gain_after["elected_amount"], 0.00, "elected_amount")
    assert_money(gain_after["unelected_amount"], 400000.00, "unelected_amount")
    elections = list_gain_elections(api, gain["id"])
    assert {election["status"] for election in elections} == {"REVOKED"}
    assert_gain_dollars_conserved(gain_after, elections)
    assert_money(
        read_fund(api, fund["id"])["deferred_gain_committed"],
        0.00,
        "deferred_gain_committed",
    )
    statement = read_investor_statement(api, investor["id"])
    assert_money(
        statement["deferred_gain_outstanding"], 0.00, "deferred_gain_outstanding"
    )
    assert_money(statement["included_gain_total"], 0.00, "included_gain_total")


def test_a_stale_expected_fund_version_refuses_the_second_investor(api):
    """
    "It must carry the `version` the client last observed on the fund named by
    `fund_id`. Two elections against the same `SELF_CERTIFIED` fund are both perfectly
    legal — any number of investors may invest — so no state check can catch a client
    whose picture of the fund's `deferred_gain_committed` predates someone else's
    election. The fund's `version` is the only observable that reveals it. If
    `expected_fund_version` does not equal the fund's current `version`, the create is
    rejected with `ERR_STALE_FUND_VERSION` (HTTP 412), and no election is written."

    Design: Corner/complexity_layers/deferral_election_stale_fund_version_rejected
    """
    first_investor = make_attested_investor(
        api, legal_name="OCC Investor One", taxpayer_type="TRUST"
    )
    second_investor = make_attested_investor(
        api, legal_name="OCC Investor Two", taxpayer_type="INDIVIDUAL"
    )
    fund = make_self_certified_fund(api, name="OCC Ladder QOF", entity_type="PARTNERSHIP")
    assert fund["version"] == 2, "creation then self-certification is two writes"
    first_gain = make_eligible_gain(
        api,
        first_investor["id"],
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )
    second_gain = make_eligible_gain(
        api,
        second_investor["id"],
        gain_character="SHORT_TERM_CAPITAL",
        eligible_amount=100000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="SALE_DATE",
    )

    first_election = make_deferral_election(
        api,
        first_investor["id"],
        first_gain["id"],
        fund["id"],
        expected_fund_version=2,
        elected_amount=100000.00,
    )

    assert first_election["status"] == "DEFERRED"
    assert first_election["days_from_basis"] == 31
    assert read_fund(api, fund["id"])["version"] == 3

    stale = api.create_deferral_election(
        create_deferral_election_payload(
            second_gain["id"], fund["id"], 2, elected_amount=100000.00
        ),
        make_investor_headers(second_investor["id"]),
    )

    validate_error(stale, ApiErrorId.STALE_FUND_VERSION.value, 412)
    fund_after_refusal = read_fund(api, fund["id"])
    assert fund_after_refusal["version"] == 3, "the refused create wrote nothing"
    assert_money(
        fund_after_refusal["deferred_gain_committed"],
        100000.00,
        "deferred_gain_committed",
    )
    refused_gain = read_eligible_gain(api, second_gain["id"])
    assert refused_gain["status"] == "ELIGIBLE"
    assert_money(refused_gain["unelected_amount"], 100000.00, "unelected_amount")
    assert not list_gain_elections(api, second_gain["id"])

    replayed = validate_success(
        api.create_deferral_election(
            create_deferral_election_payload(
                second_gain["id"], fund["id"], 3, elected_amount=100000.00
            ),
            make_investor_headers(second_investor["id"]),
        ),
        201,
    )

    assert replayed["status"] == "DEFERRED"
    fund_final = read_fund(api, fund["id"])
    assert fund_final["version"] == 4
    assert_money(
        fund_final["deferred_gain_committed"], 200000.00, "deferred_gain_committed"
    )


def test_a_pass_through_window_that_has_not_opened_yet_refuses_the_election(api):
    """
    "An election is timely when `days_from_basis` is at least 0 and at most 180." "a
    negative value — an election dated before the window even opened, which happens
    readily when the pass-through basis puts `window_basis_date` months after the sale
    — is rejected with `ERR_180_DAY_WINDOW_NOT_OPEN`." "when `deadline_basis` is
    `PARTNERSHIP_YEAR_END` or `SECTION_1231_YEAR_END`, it is the
    `pass_through_year_end`."

    Design: Corner/errors/deferral_election_before_window_basis_rejected
    """
    investor = make_attested_investor(
        api, legal_name="Early Bird Holdings LP", taxpayer_type="PARTNERSHIP"
    )
    gain = make_eligible_gain(
        api,
        investor["id"],
        eligible_amount=200000.00,
        realization_date="2026-07-01T00:00:00Z",
        deadline_basis="PARTNERSHIP_YEAR_END",
        pass_through_year_end="2026-12-31T00:00:00Z",
    )
    assert gain["window_basis_date"].startswith("2026-12-31T00:00:00")
    fund = make_self_certified_fund(
        api, name="Early Bird QOF", entity_type="PARTNERSHIP"
    )

    too_early = api.create_deferral_election(
        create_deferral_election_payload(
            gain["id"], fund["id"], fund["version"], elected_amount=200000.00
        ),
        make_investor_headers(investor["id"]),
    )

    validate_error(too_early, ApiErrorId.WINDOW_180_DAY_NOT_OPEN.value, 422)
    assert not list_gain_elections(api, gain["id"])
    refused = read_eligible_gain(api, gain["id"])
    assert refused["status"] == "ELIGIBLE"
    assert_money(refused["elected_amount"], 0.00, "elected_amount")
    assert_money(refused["unelected_amount"], 200000.00, "unelected_amount")

    set_clock(api, "2027-01-15T00:00:00Z")
    election = validate_success(
        api.create_deferral_election(
            create_deferral_election_payload(
                gain["id"], fund["id"], fund["version"], elected_amount=200000.00
            ),
            make_investor_headers(investor["id"]),
        ),
        201,
    )

    assert election["days_from_basis"] == 15
    assert election["status"] == "DEFERRED"
    invested = read_eligible_gain(api, gain["id"])
    assert invested["status"] == "FULLY_INVESTED"
    assert_money(invested["elected_amount"], 200000.00, "elected_amount")
    assert_money(invested["unelected_amount"], 0.00, "unelected_amount")
