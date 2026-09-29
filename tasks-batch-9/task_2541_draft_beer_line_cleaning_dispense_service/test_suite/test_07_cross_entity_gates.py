"""Writes gated on the state of an entity the request body never names."""

from test_helpers import (
    ApiErrorId,
    BillingMode,
    ComplianceResult,
    ContractStatus,
    DISPATCH_HEADERS,
    FundingStatus,
    GlycolStatus,
    LineStatus,
    ProgramStatus,
    ReadingSource,
    assert_liters,
    assert_pct,
    assert_score,
    factories,
    fixtures,
    validate_error,
)

CAUSTIC_CYCLE = {
    "chemical_type": "CAUSTIC",
    "contact_minutes": 20,
    "recirculation_temp_f": 96.0,
    "concentrate_liters_used": 0.31,
}


def _chilled_venue(api):
    """A glycol venue with an open job, a caustic lot, and no readings yet."""
    return fixtures.setup_started_visit(
        api,
        venue_name="Frostline Public House",
        glycol_system_present=True,
    )


def _attempt_cycle(api, ground):
    return api.create_cleaning_cycle(
        factories.cleaning_cycle_payload(
            ground["visit"]["id"], ground["line"]["id"], ground["lot"]["id"], **CAUSTIC_CYCLE
        ),
        ground["tech_headers"],
    )


def test_an_alarming_glycol_loop_blocks_a_cycle_that_never_names_it(api):
    """PRD §3.4: "If the account has a glycol loop, that loop's `status` must not be
    `ALARM`, else `ERR_GLYCOL_ALARM_BLOCK` — chemistry cannot be circulated through a
    failing chiller bath."
    PRD §3.9: "The scoring window is the newest three readings on the loop, ordered by
    `reading_at` descending and then, for ties, by `created_at` descending, and never by
    identifier."

    Design: Difficulty/cross_entity_state_dependency/cleaning_cycle_blocked_while_the_accounts_glycol_loop_sits_in_the_alarm_band
    """
    ground = _chilled_venue(api)
    readings = fixtures.post_cooler_readings(
        api,
        ground["loop"]["id"],
        (45.0, 45.0, 45.0),
        ground["manager_headers"],
        glycol_supply_temp_f=33.0,
    )
    assert readings[0]["source"] == ReadingSource.VENUE_MANUAL

    alarming = fixtures.read_loop(api, ground["loop"]["id"])
    assert_score(alarming["health_score"], 44.0)
    assert alarming["status"] == GlycolStatus.ALARM
    assert alarming["window_avg_cooler_temp_f"] == 45.0

    refused = _attempt_cycle(api, ground)

    validate_error(refused, ApiErrorId.GLYCOL_ALARM_BLOCK, 422)


def test_displacing_the_bad_readings_lets_the_identical_cycle_body_through(api):
    """PRD §3.9: "Because only the newest three readings count, a fourth reading pushes the
    oldest out, so the score can **improve** after a bad reading is displaced — nothing is
    averaged over history."
    PRD §3.9: "Readings from a technician and from a venue manager are weighted
    identically."

    Design: Difficulty/cross_entity_state_dependency/cleaning_cycle_blocked_while_the_accounts_glycol_loop_sits_in_the_alarm_band
    """
    ground = _chilled_venue(api)
    fixtures.post_cooler_readings(
        api,
        ground["loop"]["id"],
        (45.0, 45.0, 45.0),
        ground["manager_headers"],
        glycol_supply_temp_f=33.0,
    )
    validate_error(_attempt_cycle(api, ground), ApiErrorId.GLYCOL_ALARM_BLOCK, 422)

    fixtures.set_clock(api, "2026-08-05T09:30:00Z")
    fresh = fixtures.post_cooler_readings(
        api, ground["loop"]["id"], (38.0, 38.0, 38.0), ground["tech_headers"]
    )
    assert fresh[0]["source"] == ReadingSource.TECH_MANUAL

    recovered = fixtures.read_loop(api, ground["loop"]["id"])
    # The three warm readings have rolled out of the window entirely.
    assert_score(recovered["health_score"], 100.0)
    assert recovered["status"] == GlycolStatus.NORMAL
    assert recovered["window_avg_cooler_temp_f"] == 38.0

    cycle = fixtures.log_cleaning_cycle(
        api,
        ground["visit"]["id"],
        ground["line"]["id"],
        ground["lot"]["id"],
        ground["technician"]["id"],
        **CAUSTIC_CYCLE,
    )

    assert cycle["compliance_result"] == ComplianceResult.PASS
    assert_pct(cycle["effective_active_pct"], 1.993)
    assert cycle["required_contact_minutes"] == 20
    assert_liters(fixtures.read_lot(api, ground["lot"]["id"])["liters_remaining"], 19.690)
    assert fixtures.read_line(api, ground["line"]["id"])["status"] == LineStatus.IN_SERVICE


def _draft_contract_on_a_programme(api):
    """A structurally perfect DRAFT contract backed by a live programme."""
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    funded = fixtures.create_brewer_program(api, brewer_name="Southside Brewing")
    other = fixtures.create_brewer_program(
        api,
        brewer_name="Harbor Craft Co",
        funded_scope="FULL",
        co_pay_bps=1000,
        funding_cap_cents=60000,
    )
    account = fixtures.create_account(api, venue_name="Lamplighter Inn")
    contract = fixtures.draft_contract(
        api,
        account["id"],
        account["version"],
        cleaning_frequency_days=28,
        contracted_line_count=3,
        brewer_program_id=funded["id"],
    )
    assert funded["remaining_cents"] == 50000
    assert contract["funding_status"] == FundingStatus.BREWER_FUNDED
    return account, funded, other, contract


def test_ending_the_programme_defunds_the_draft_and_bars_its_activation(api):
    """PRD §3.1: "Closing a programme is the mirror image: a `BrewerRep` supplies an
    `end_note` and the programme moves from `ACTIVE` or from `EXHAUSTED` to `ENDED`,
    whereupon every contract naming it whose status is `DRAFT`, `ACTIVE` or `SUSPENDED` has
    its `funding_status` recomputed to `SELF_FUNDED` in ascending `created_at` order and
    each such contract's account has its `billing_mode` recomputed to `DIRECT_BILL`."
    PRD §3.1: "`ENDED` is terminal: no further settlement may draw on the programme, and a
    `DRAFT` contract naming it can no longer be activated."

    Design: Difficulty/cross_entity_state_dependency/contract_activation_blocked_because_its_brewer_program_was_ended
    """
    account, funded, _other, contract = _draft_contract_on_a_programme(api)

    ended = fixtures.end_program(api, funded["id"])

    assert ended["status"] == ProgramStatus.ENDED
    defunded = fixtures.read_contract(api, contract["id"])
    assert defunded["funding_status"] == FundingStatus.SELF_FUNDED, (
        "the /end call rewrote a contract no request named"
    )
    assert defunded["status"] == ContractStatus.DRAFT
    assert fixtures.read_account(api, account["id"])["billing_mode"] == BillingMode.DIRECT_BILL

    refused = api.set_contract_status(contract["id"], ContractStatus.ACTIVE, DISPATCH_HEADERS)

    validate_error(refused, ApiErrorId.PROGRAM_NOT_ACTIVE, 409)


def test_a_sibling_draft_on_a_live_programme_still_activates(api):
    """PRD §3.1: "when the contract names a `brewer_program_id`, that programme's `status`
    must be `ACTIVE` — an exhausted or ended programme cannot back a newly activated
    contract, which is refused with `ERR_PROGRAM_NOT_ACTIVE`."
    PRD §3.1: "the account's `billing_mode` becomes `PROGRAM_BILL` when this contract's
    `funding_status` is `BREWER_FUNDED` and `DIRECT_BILL` otherwise"

    Design: Difficulty/cross_entity_state_dependency/contract_activation_blocked_because_its_brewer_program_was_ended
    """
    account, funded, other, contract = _draft_contract_on_a_programme(api)
    fixtures.end_program(api, funded["id"])
    validate_error(
        api.set_contract_status(contract["id"], ContractStatus.ACTIVE, DISPATCH_HEADERS),
        ApiErrorId.PROGRAM_NOT_ACTIVE,
        409,
    )

    sibling = fixtures.draft_contract(
        api,
        account["id"],
        fixtures.read_account(api, account["id"])["version"],
        contracted_line_count=3,
        brewer_program_id=other["id"],
    )
    assert sibling["funding_status"] == FundingStatus.BREWER_FUNDED

    activated = fixtures.activate_contract(api, sibling["id"])

    assert activated["status"] == ContractStatus.ACTIVE, (
        "only the ended programme was ever the obstacle"
    )
    assert fixtures.read_account(api, account["id"])["billing_mode"] == BillingMode.PROGRAM_BILL
    assert fixtures.read_program(api, other["id"])["status"] == ProgramStatus.ACTIVE
