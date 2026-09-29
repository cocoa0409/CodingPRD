"""The initial creation payment: one composed rounding, and the union floor."""

from test_helpers import assertions, fixtures

# A non-union performer, so no statutory floor can mask the rounding position.
NON_UNION_TALENT = {"legal_name": "Ines Okafor", "union_code": "NONE"}

THREE_YEAR_EXCLUSIVE_GRANT = {
    "permitted_media_types": ["ADVERTISING", "EPISODIC"],
    "territory_codes": ["US", "MX"],
    "permitted_use_notes": "Exclusive three-year replica licence",
    "exclusivity": "EXCLUSIVE",
    "effective_from": "2026-08-01T00:00:00Z",
    "effective_until": "2029-08-01T00:00:00Z",
    "initial_creation_fee_cents": 123457,
    "per_use_base_fee_cents": 90000,
}

# Two SAG_AFTRA grants sitting one cent apart around a 300000 initial floor.
AT_THE_FLOOR_GRANT = {
    "permitted_media_types": ["ADVERTISING"],
    "territory_codes": ["US"],
    "permitted_use_notes": "At the floor",
    "exclusivity": "NON_EXCLUSIVE",
    "effective_from": "2026-08-01T00:00:00Z",
    "effective_until": "2027-08-01T00:00:00Z",
    "initial_creation_fee_cents": 300_000,
    "per_use_base_fee_cents": 150_000,
}

ONE_CENT_UNDER_GRANT = dict(
    AT_THE_FLOOR_GRANT,
    permitted_use_notes="One cent under the floor",
    initial_creation_fee_cents=299_999,
)


def _non_union_exclusive_grant() -> dict:
    return fixtures.setup_active_grant(
        grant_overrides=THREE_YEAR_EXCLUSIVE_GRANT,
        talent_overrides=NON_UNION_TALENT,
        profile_overrides=fixtures.CAMPAIGN_PROFILE,
    )


def test_composed_scope_chain_is_rounded_half_up_exactly_once():
    """A 36-month, two-medium, exclusive grant at 123457 cents.

    The PRD states: "The negotiated `initial_creation_fee_cents` is multiplied by
    the breadth factor, then by the duration factor, then by the exclusivity
    factor, and the fully composed product is rounded half up to a whole number
    of cents exactly once — never factor by factor." 123457 * 1.15 * 1.25 * 1.35
    composes to 239583.740625 and lands on 239584, where rounding after each
    factor in turn would have reached 239585.

    Design: Difficulty/combinatorial_formula/initial_creation_single_rounding_of_composed_product
    """
    scenario = _non_union_exclusive_grant()

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "ACTIVE"
    assert grant["union_code_snapshot"] is None
    assert grant["initial_compensation_cents"] == 239584
    assert grant["initial_compensation_cents"] != 239585
    assert grant["union_topup_cents"] == 0
    assert grant["total_compensation_cents"] == 239584


def test_single_creation_entry_carries_the_independently_rounded_shares():
    """The 239584-cent entry splits 179688 / 47917 / 11979.

    The PRD states: "Because each slice is rounded on its own, the three may not
    sum to the entry amount; the difference between the entry amount and the sum
    of the three rounded slices is then added to the talent's slice." Here the
    three slices already reconstruct the amount, and only one entry may exist
    because a non-union grant has no floor to top up.

    Design: Difficulty/combinatorial_formula/initial_creation_single_rounding_of_composed_product
    """
    scenario = _non_union_exclusive_grant()

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 239584, 179688, 47917, 11979)
    assertions.assert_immutable_record(entries[0])
    assertions.assert_ledger_sums_to(entries, 239584)
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=239584
    )


def _sag_grant(grant_overrides: dict, legal_name: str) -> dict:
    return fixtures.setup_active_grant(
        grant_overrides=grant_overrides,
        talent_overrides={"legal_name": legal_name, "union_code": "SAG_AFTRA"},
        profile_overrides=fixtures.CAMPAIGN_PROFILE,
        union_rows=[fixtures.SAG_ADVERTISING_ROW],
    )


def test_fee_exactly_at_the_union_floor_appends_no_topup_entry():
    """300000 cents against a 300000-cent floor.

    The PRD states: "A negotiated fee of 300000 cents for a single-media,
    twelve-month, non-exclusive grant under a floor of 300000 gives
    `initial_compensation_cents` of 300000 and `union_topup_cents` of zero —
    equality meets the floor." Equality is not a shortfall, so the ledger carries
    the creation entry alone.

    Design: Difficulty/boundary_precision_check/union_floor_equality_produces_no_topup_entry
    """
    scenario = _sag_grant(AT_THE_FLOOR_GRANT, "Ava Reyes")

    grant = fixtures.refresh_grant(scenario)
    assert grant["status"] == "ACTIVE"
    assert grant["countersigned_at"] == "2026-08-01T00:00:00Z"
    assert grant["initial_compensation_cents"] == 300_000
    assert grant["union_topup_cents"] == 0
    assert grant["total_compensation_cents"] == 300_000

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 300_000, 225_000, 60_000, 15_000)


def test_fee_one_cent_under_the_floor_appends_a_one_cent_topup_entry():
    """299999 cents against the same 300000-cent floor.

    The PRD states: "One entry of type `INITIAL_CREATION` is appended for the
    rounded amount, and only when the union floor strictly exceeds that amount is
    a second entry of type `UNION_TOPUP` appended for the difference." The
    one-cent difference is its own entry, split like any other, and the talent's
    lifetime roll-up counts the topped-up total once.

    Design: Difficulty/boundary_precision_check/union_floor_equality_produces_no_topup_entry
    """
    scenario = _sag_grant(ONE_CENT_UNDER_GRANT, "Ben Ortiz")

    grant = fixtures.refresh_grant(scenario)
    assert grant["initial_compensation_cents"] == 300_000
    assert grant["union_topup_cents"] == 1
    assert grant["total_compensation_cents"] == 300_000

    entries = fixtures.grant_ledger(scenario)
    assertions.assert_entry_types(entries, ["INITIAL_CREATION", "UNION_TOPUP"])
    assertions.assert_ledger_entry(entries[0], "INITIAL_CREATION", 299_999, 224_999, 60_000, 15_000)
    assertions.assert_ledger_entry(entries[1], "UNION_TOPUP", 1, 1, 0, 0)
    assertions.assert_talent_counters(
        fixtures.read_talent(scenario), lifetime_compensation_cents=300_000
    )


def test_one_cent_apart_the_two_grants_differ_only_in_the_topup_row():
    """Both grants countersigned in one office day, one cent apart.

    The PRD states: "`initial_compensation_cents` is then whichever is greater,
    the rounded amount or the floor, and `union_topup_cents` is the amount by
    which the floor exceeds the rounded amount, or zero when it does not exceed
    it." Both grants therefore report the same compensation while only the
    shortfall grant carries a second ledger row.

    Design: Difficulty/boundary_precision_check/union_floor_equality_produces_no_topup_entry
    """
    scenario = fixtures.setup_reference_data(
        fixtures.CAMPAIGN_PROFILE, [fixtures.SAG_ADVERTISING_ROW]
    )

    fixtures.create_talent(scenario, {"legal_name": "Ava Reyes", "union_code": "SAG_AFTRA"})
    fixtures.draft_consent_grant(scenario, AT_THE_FLOOR_GRANT)
    fixtures.countersign_grant(scenario)
    grant_at_floor = fixtures.refresh_grant(scenario)
    entries_at_floor = fixtures.grant_ledger(scenario, grant_at_floor)

    fixtures.create_talent(scenario, {"legal_name": "Ben Ortiz", "union_code": "SAG_AFTRA"})
    fixtures.draft_consent_grant(scenario, ONE_CENT_UNDER_GRANT)
    fixtures.countersign_grant(scenario)
    grant_under_floor = fixtures.refresh_grant(scenario)
    entries_under_floor = fixtures.grant_ledger(scenario, grant_under_floor)

    assert grant_at_floor["initial_compensation_cents"] == 300_000
    assert grant_under_floor["initial_compensation_cents"] == 300_000
    assert grant_at_floor["union_topup_cents"] == 0
    assert grant_under_floor["union_topup_cents"] == 1
    assertions.assert_entry_types(entries_at_floor, ["INITIAL_CREATION"])
    assertions.assert_entry_types(
        entries_under_floor, ["INITIAL_CREATION", "UNION_TOPUP"]
    )
