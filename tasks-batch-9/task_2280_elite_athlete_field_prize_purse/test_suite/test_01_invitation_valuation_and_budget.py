"""Valuing an invitation package, and conserving the appearance budget."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    api_client,
    assert_appearance_ledger,
    assign_bib,
    enroll_accepted_invitation,
    enroll_offered_invitation,
    list_fluid_slots,
    lock_field,
    make_athlete_agent_headers,
    read_edition,
    read_invitation,
    register_agent,
    reserve_fluid_slot,
    respond_as_agent,
    setup_field_open_edition,
    validate_error,
    withdraw_invitation,
)

# 3,000,000 fee + 540,000 BUSINESS air + 7 capped nights x 32,000 + 18,000 ground
RICH_PACKAGE = {
    "appearance_fee_cents": 3_000_000,
    "air_class": "BUSINESS",
    "hotel_nights": 9,
    "ground_transport": True,
}
RICH_GUARANTEED_CENTS = 3_782_000
# guaranteed + largest matching TIME_BONUS (1,000,000) + RECORD_BONUS (1,500,000)
RICH_FULL_EXPOSURE_CENTS = 6_282_000

# 1,702,000 fee + 120,000 ECONOMY air + 5 nights x 32,000 + 18,000 ground
ROUND_PACKAGE = {
    "appearance_fee_cents": 1_702_000,
    "air_class": "ECONOMY",
    "hotel_nights": 5,
    "ground_transport": True,
}
ROUND_GUARANTEED_CENTS = 2_000_000


def _bonus_bearing_field():
    """Three identical BUSINESS-class packages accepted against a 12,000,000
    appearance budget and a 6,000,000 bonus pool cap.

    No course record is on file for the open male class, so every entrant is a
    threat to it and the record bonus counts toward full exposure.
    """
    scenario = setup_field_open_edition(
        purse_lines=[
            {"category": "OVERALL", "gender": "MALE", "place": 1,
             "amount_cents": 5_000_000},
            {"category": "TIME_BONUS", "division": "ELITE", "gender": "MALE",
             "threshold_seconds": 7_600, "amount_cents": 1_000_000},
            {"category": "RECORD_BONUS", "division": "ELITE", "gender": "MALE",
             "amount_cents": 1_500_000},
        ],
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Metro Marathon 2026",
        appearance_budget_cents=12_000_000,
        total_purse_cents=10_000_000,
        bonus_pool_cap_cents=6_000_000,
    )
    agent = register_agent(agency_name="Apex Track Management")
    entrants = []
    for country, seconds in (("KEN", 7_900), ("ETH", 7_950), ("USA", 8_000)):
        entrants.append(
            enroll_accepted_invitation(
                scenario["edition"]["id"],
                offer=RICH_PACKAGE,
                agent=agent,
                athlete_overrides={"country_code": country},
                performance_overrides={"performance_seconds": seconds},
            )
        )
    scenario["agent"] = agent
    scenario["entrants"] = entrants
    scenario["edition"] = read_edition(scenario["edition"]["id"])
    return scenario


def test_acceptance_debits_the_guaranteed_valuation_only():
    """Accepting freezes the guaranteed valuation and moves the appearance ledger by it.

    PRD §3.4: "The guaranteed valuation is `current_appearance_fee_cents` plus the
    air component plus the hotel component plus the ground component, in integer
    cents, and it excludes every bonus exposure term." The air component is
    "540,000 cents for `BUSINESS`", and "the cap is applied to the night count
    before the nightly rate is multiplied, never to the product afterwards, so a
    fourteen-night package is valued at seven nights of hotel" — nine nights are
    therefore valued at seven. On success "the guaranteed valuation is frozen onto
    `guaranteed_commitment_cents`, the edition's `appearance_committed_cents` grows
    by that amount, `appearance_uncommitted_cents` is recomputed, and the edition's
    `version` is incremented alongside the invitation's."

    Design: Difficulty/dual_variant_calc/dual_variant_invitation_package_guaranteed_vs_full_exposure
    """
    scenario = _bonus_bearing_field()

    invitation = read_invitation(scenario["entrants"][0]["invitation"]["id"])
    assert invitation["status"] == "ACCEPTED"
    assert invitation["guaranteed_commitment_cents"] == RICH_GUARANTEED_CENTS, (
        "the guaranteed valuation is 3,000,000 fee plus 540,000 BUSINESS air plus "
        "224,000 hotel (seven capped nights at 32,000) plus 18,000 ground"
    )
    assert invitation["full_exposure_cents"] == 0, (
        "full exposure is stamped by the field lock, so it is still zero here"
    )

    assert_appearance_ledger(scenario["edition"], 3 * RICH_GUARANTEED_CENTS, 654_000)


def test_lock_field_ceiling_measures_the_full_exposure_variant():
    """The lock ceiling is tested against full exposure, not the guaranteed sum.

    PRD §3.4: "The lock is admitted only when the summed full exposure across all
    `ACCEPTED` invitations of the edition is no greater than `appearance_budget_cents`
    plus `bonus_pool_cap_cents`; over that ceiling it is refused with
    `ERR_FIELD_LOCK_EXPOSURE_EXCEEDED`." Full exposure adds the largest matching
    `TIME_BONUS` amount and, because "The athlete is treated as a threat to that
    record when the selected record field is null", the `RECORD_BONUS` amount too,
    so three entrants expose 18,846,000 cents against a ceiling of 18,000,000.

    Design: Difficulty/dual_variant_calc/dual_variant_invitation_package_guaranteed_vs_full_exposure
    """
    scenario = _bonus_bearing_field()
    edition_id = scenario["edition"]["id"]

    response = api_client.lock_field(edition_id, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_FIELD_LOCK_EXPOSURE_EXCEEDED.value, 422)

    edition = read_edition(edition_id)
    assert edition["status"] == "FIELD_OPEN", (
        "the refused lock left the edition where it was"
    )
    for entrant in scenario["entrants"]:
        invitation = read_invitation(entrant["invitation"]["id"])
        assert invitation["full_exposure_cents"] == 0, (
            "full exposure is stamped only when the lock succeeds, so a refused "
            "lock must not have stamped any invitation"
        )


def test_both_valuation_variants_coexist_after_the_field_locks():
    """One invitation carries the guaranteed figure and the full-exposure figure at once.

    PRD §3.4: "Visiting the `ACCEPTED` invitations in ascending `created_at`, it
    stamps each one's computed full exposure onto `full_exposure_cents` and
    increments that invitation's `version`." The appearance ledger keeps tracking
    the other variant, because "`appearance_committed_cents` is the sum of
    `guaranteed_commitment_cents` over the invitations of that edition whose
    `status` is `ACCEPTED`" (PRD §2.9), and a withdrawal from `ACCEPTED` "reduces
    the edition's `appearance_committed_cents` by the invitation's
    `guaranteed_commitment_cents`".

    Design: Difficulty/dual_variant_calc/dual_variant_invitation_package_guaranteed_vs_full_exposure
    """
    scenario = _bonus_bearing_field()
    edition_id = scenario["edition"]["id"]

    withdrawn = withdraw_invitation(
        scenario["entrants"][2]["invitation"]["id"],
        reason="exposure ceiling rebalance",
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["guaranteed_commitment_cents"] == 0

    edition = lock_field(edition_id)
    assert edition["status"] == "FIELD_LOCKED", (
        "two entrants expose 12,564,000 cents, inside the 18,000,000 ceiling"
    )

    invitation = read_invitation(scenario["entrants"][0]["invitation"]["id"])
    assert invitation["guaranteed_commitment_cents"] == RICH_GUARANTEED_CENTS
    assert invitation["full_exposure_cents"] == RICH_FULL_EXPOSURE_CENTS, (
        "full exposure is the guaranteed valuation plus the 1,000,000 time-bonus "
        "line and the 1,500,000 record-bonus line"
    )

    assert_appearance_ledger(read_edition(edition_id), 2 * RICH_GUARANTEED_CENTS,
                             4_436_000)


def _single_accepted_invitation_on_a_tight_budget():
    """One accepted 2,000,000 package against a 2,500,000 appearance budget, so a
    second commitment of the same size would not fit."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Priority State Marathon",
        appearance_budget_cents=2_500_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    entrant = enroll_accepted_invitation(
        scenario["edition"]["id"],
        offer=ROUND_PACKAGE,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_950},
    )
    scenario["entrant"] = entrant
    scenario["edition"] = read_edition(scenario["edition"]["id"])
    return scenario


def test_second_accept_is_refused_on_invitation_state_not_on_the_budget():
    """An already-accepted invitation fails the state check before the money ceiling.

    PRD §2.11 priority 8 is "**Target entity state.** The target entity is in a
    state that permits the requested transition, else one of
    `ERR_INVALID_INVITATION_STATE`", while priority 16 is "**Money ceilings,
    checked last.**" PRD §3.4 says the same thing directly: "if it is short, the
    acceptance is refused with `ERR_APPEARANCE_BUDGET_EXCEEDED`, and this fiscal
    ceiling is evaluated after every other check on the request." Re-committing
    2,000,000 against 500,000 of remaining budget would breach the ceiling, yet the
    state error must surface instead.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_ceiling_on_double_accept
    """
    scenario = _single_accepted_invitation_on_a_tight_budget()
    assert_appearance_ledger(scenario["edition"], ROUND_GUARANTEED_CENTS, 500_000)

    response = api_client.respond_to_invitation(
        scenario["entrant"]["invitation"]["id"],
        {"decision": "ACCEPT"},
        make_athlete_agent_headers(scenario["entrant"]["agent"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_INVITATION_STATE.value, 409)


def test_refused_second_accept_commits_nothing():
    """The rejected acceptance leaves both the ledger and the invitation untouched.

    PRD §2.9: "`appearance_committed_cents` is the sum of
    `guaranteed_commitment_cents` over the invitations of that edition whose
    `status` is `ACCEPTED`, and `appearance_uncommitted_cents` is
    `appearance_budget_cents` less `appearance_committed_cents`." A refused request
    changes no status, so neither projection may move.

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_ceiling_on_double_accept
    """
    scenario = _single_accepted_invitation_on_a_tight_budget()
    invitation_id = scenario["entrant"]["invitation"]["id"]

    response = api_client.respond_to_invitation(
        invitation_id,
        {"decision": "ACCEPT"},
        make_athlete_agent_headers(scenario["entrant"]["agent"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_INVITATION_STATE.value, 409)

    assert_appearance_ledger(read_edition(scenario["edition"]["id"]),
                             ROUND_GUARANTEED_CENTS, 500_000)
    invitation = read_invitation(invitation_id)
    assert invitation["status"] == "ACCEPTED"
    assert invitation["guaranteed_commitment_cents"] == ROUND_GUARANTEED_CENTS


def _bibbed_starter_and_a_standby():
    """A bibbed starter holding the only bib in the pool, plus a standby whose
    offer is still on the table."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 11}],
        name="Budget Invariant Marathon",
        appearance_budget_cents=10_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Invariant Athletics")
    starter = enroll_accepted_invitation(
        edition_id, offer=ROUND_PACKAGE, agent=agent,
        athlete_overrides={"country_code": "USA", "whereabouts_filed": True},
        performance_overrides={"performance_seconds": 7_900},
    )
    starter["invitation"] = assign_bib(starter["invitation"]["id"])
    starter["slot"] = reserve_fluid_slot(
        starter["invitation"]["id"], station_km=15.0, table_position=7, bottle_count=2
    )
    standby = enroll_offered_invitation(
        edition_id, offer=ROUND_PACKAGE, agent=agent,
        athlete_overrides={"country_code": "USA", "whereabouts_filed": True},
        performance_overrides={"performance_seconds": 7_910},
    )
    scenario["agent"] = agent
    scenario["starter"] = starter
    scenario["standby"] = standby
    scenario["edition"] = read_edition(edition_id)
    return scenario


def test_withdrawal_returns_the_committed_cents_to_the_uncommitted_pool():
    """Withdrawing from `ACCEPTED` returns the cents rather than merely zeroing them.

    PRD §3.4: "It reduces the edition's `appearance_committed_cents` by the
    invitation's `guaranteed_commitment_cents`, resets `guaranteed_commitment_cents`
    to zero and increments the edition's `version`, so that the appearance-budget
    invariant of §2.9 holds exactly again; it nulls `bib_number`, returning that bib to
    its division pool for immediate reuse; and it moves every fluid-station reservation
    belonging to the invitation from `RESERVED` to `RELEASED`." That invariant reads: "First,
    `appearance_budget_cents` equals `appearance_uncommitted_cents` plus the summed
    `guaranteed_commitment_cents` of the edition's `ACCEPTED` invitations."

    Design: Difficulty/compensating_invariant/compensating_appearance_budget_invariant_across_withdraw_and_reissue
    """
    scenario = _bibbed_starter_and_a_standby()
    assert_appearance_ledger(scenario["edition"], ROUND_GUARANTEED_CENTS, 8_000_000)

    withdraw_invitation(scenario["starter"]["invitation"]["id"],
                        reason="signed with a competing race")

    assert_appearance_ledger(read_edition(scenario["edition"]["id"]), 0, 10_000_000)
    invitation = read_invitation(scenario["starter"]["invitation"]["id"])
    assert invitation["status"] == "WITHDRAWN"
    assert invitation["guaranteed_commitment_cents"] == 0
    assert invitation["full_exposure_cents"] == 0


def test_withdrawal_releases_the_bib_and_every_fluid_reservation():
    """The discrete resources booked by the acceptance come back as well.

    PRD §3.4: the withdrawal "nulls `bib_number`, returning that bib to its division
    pool for immediate reuse; and it moves every fluid-station reservation belonging
    to the invitation from `RESERVED` to `RELEASED`."

    Design: Difficulty/compensating_invariant/compensating_appearance_budget_invariant_across_withdraw_and_reissue
    """
    scenario = _bibbed_starter_and_a_standby()
    invitation_id = scenario["starter"]["invitation"]["id"]
    assert scenario["starter"]["invitation"]["bib_number"] == 11
    assert scenario["starter"]["slot"]["status"] == "RESERVED"

    withdraw_invitation(invitation_id, reason="signed with a competing race")

    assert read_invitation(invitation_id)["bib_number"] is None
    slots, meta = list_fluid_slots(invitation_id)
    assert meta["total_count"] == 1
    assert slots[0]["status"] == "RELEASED"


def test_commit_decommit_recommit_cycle_leaves_no_drift():
    """A replacement entrant takes the identical bib and restores the identical ledger.

    PRD §3.5: "From that pool the server excludes every bib currently held by an
    `ACCEPTED` invitation of the same edition — and only of the same edition. Bibs
    held by invitations that have gone `WITHDRAWN`, `BREACHED`, `EXPIRED` or
    `DECLINED` are not held at all and are immediately reusable." And "The lowest
    remaining number is written to `bib_number`; because bib numbers are distinct
    integers there is never a tie to break, and the selector consults no identifier
    of any kind."

    Design: Difficulty/compensating_invariant/compensating_appearance_budget_invariant_across_withdraw_and_reissue
    """
    scenario = _bibbed_starter_and_a_standby()
    withdraw_invitation(scenario["starter"]["invitation"]["id"],
                        reason="signed with a competing race")

    respond_as_agent(scenario["standby"]["invitation"]["id"],
                     scenario["agent"]["id"], "ACCEPT")
    replacement = assign_bib(scenario["standby"]["invitation"]["id"])
    assert replacement["bib_number"] == 11, (
        "the bib freed by the withdrawal is the lowest free number in the pool"
    )

    assert_appearance_ledger(read_edition(scenario["edition"]["id"]),
                             ROUND_GUARANTEED_CENTS, 8_000_000)
