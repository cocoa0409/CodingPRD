"""One incident, two insurance bases, two entirely different settlements.

Actual cash value writes the work down for age and scales by the measured extent
of the damage, while restoration reads the pinned repair estimate and ignores the
insured value, the acquisition age and the extent altogether.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import assert_damage_incident
from test_helpers.test_users import TEST_USERS


def _work_with_a_priced_repair(api):
    """A vandalised work insured for 12,000,000 cents with a priced repair on file."""
    state = fixtures.setup_approved_proposal(api)
    assert state["artwork"]["insured_value_cents"] == 12_000_000
    assert state["artwork"]["acquisition_date"] == "2014-06-01"
    assert state["proposal"]["pinned_estimate_total_cents"] == 683_269
    assert fixtures.read_pool(api, state["pool"]["id"])["available_cents"] == 19_827_500
    return state


def test_an_actual_cash_value_claim_depreciates_the_insured_value(api):
    """PRD §3.11: "Under **actual cash value**, the work is written down for age."
    PRD §3.11: "The elapsed days between the work's `acquisition_date` and the logical
    clock's date are divided by 365 and truncated down to a whole number of years, and
    that age is capped at 25 years."
    PRD §3.11: "The depreciated value is the work's `insured_value_cents` multiplied by
    0.98 raised to the power of that age in years, rounded half up to a whole cent."
    PRD §3.11: "`claimed_gross_cents` is then that depreciated value multiplied by
    `damage_extent_pct`, rounded half up to a whole cent — note that the depreciation
    is rounded once before the extent multiplier is applied, and the product is
    rounded again after."

    Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_restoration_variant
    """
    state = _work_with_a_priced_repair(api)
    incident = fixtures.setup_incident_triaged(api, state["artwork"]["id"])
    assert incident["damage_extent_pct"] == 0.35
    assert incident["claim_status"] == "NONE"

    filed = fixtures.file_claim(
        api,
        incident["id"],
        "ACV",
        credited_pool_id=state["pool"]["id"],
        policy_note="actual cash value basis",
    )
    # 2014-06-01 to the clock at 2026-08-01 is 4444 days, so the age is 12 whole
    # years: 12000000 x 0.98^12 = 9416600.68 -> 9416601, and 35 percent of that is
    # 3295810.35 -> 3295810.
    assert filed["claim_basis"] == "ACV"
    assert filed["claim_status"] == "FILED"
    assert filed["claimed_gross_cents"] == 3_295_810
    assert_damage_incident(filed)


def test_a_restoration_claim_reads_the_pinned_repair_estimate(api):
    """PRD §3.11: "Under **restoration**, `claimed_gross_cents` is simply the
    `pinned_estimate_total_cents` of the linked proposal, wholly independent of insured
    value, acquisition age and `damage_extent_pct`."
    PRD §3.11: "A `RESTORATION` basis additionally requires `linked_proposal_id` to be
    set, that proposal to be in `APPROVED`, `IN_EXECUTION` or `COMPLETED`, and its
    `pinned_estimate_total_cents` to be non-null; any of those missing yields
    `ERR_CLAIM_BASIS_UNSUPPORTED`."

    Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_restoration_variant
    """
    state = _work_with_a_priced_repair(api)
    incident = fixtures.setup_incident_triaged(
        api,
        state["artwork"]["id"],
        narrative="Second strike, same measured extent",
        linked_proposal_id=state["proposal"]["id"],
    )

    filed = fixtures.file_claim(
        api,
        incident["id"],
        "RESTORATION",
        credited_pool_id=state["pool"]["id"],
        policy_note="restoration cost basis",
    )
    assert filed["claim_basis"] == "RESTORATION"
    assert filed["claimed_gross_cents"] == 683_269
    assert filed["damage_extent_pct"] == 0.35


def test_the_deductible_comes_off_both_bases_alike(api):
    """PRD §3.11: "`settlement_cents` follows from the gross figure in both cases."
    PRD §3.11: "The gross claim is first capped at the policy limit of 25,000,000 cents
    (250,000 dollars), the deductible of 250,000 cents (2,500 dollars) is then
    subtracted, and the result is floored at zero."

    Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_restoration_variant
    """
    state = _work_with_a_priced_repair(api)
    acv_incident = fixtures.setup_incident_triaged(api, state["artwork"]["id"])
    restoration_incident = fixtures.setup_incident_triaged(
        api,
        state["artwork"]["id"],
        narrative="Second strike, same measured extent",
        linked_proposal_id=state["proposal"]["id"],
    )

    acv = fixtures.file_claim(
        api, acv_incident["id"], "ACV", credited_pool_id=state["pool"]["id"]
    )
    restoration = fixtures.file_claim(
        api,
        restoration_incident["id"],
        "RESTORATION",
        credited_pool_id=state["pool"]["id"],
    )
    # Neither gross figure reaches the 25,000,000 cent policy limit, so each simply
    # loses the 250,000 cent deductible.
    assert acv["settlement_cents"] == 3_045_810
    assert restoration["settlement_cents"] == 433_269


def test_identical_damage_settles_at_different_amounts_under_the_two_bases(api):
    """PRD §3.11: "The two bases compute a gross claim in entirely different ways, which
    is the point: identical incident data settles at different amounts depending on
    which basis the filer chooses."

    Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_restoration_variant
    """
    state = _work_with_a_priced_repair(api)
    first = fixtures.setup_incident_triaged(api, state["artwork"]["id"])
    second = fixtures.setup_incident_triaged(
        api,
        state["artwork"]["id"],
        narrative="Second strike, same measured extent",
        linked_proposal_id=state["proposal"]["id"],
    )
    assert first["damage_extent_pct"] == second["damage_extent_pct"] == 0.35
    assert first["incident_type"] == second["incident_type"] == "VANDALISM"

    acv = fixtures.file_claim(
        api, first["id"], "ACV", credited_pool_id=state["pool"]["id"]
    )
    restoration = fixtures.file_claim(
        api, second["id"], "RESTORATION", credited_pool_id=state["pool"]["id"]
    )

    # Same work, same incident type, same measured extent, same clock — and the
    # settlements differ by more than 2.6 million cents.
    assert acv["settlement_cents"] != restoration["settlement_cents"]
    assert acv["settlement_cents"] == 3_045_810
    assert restoration["settlement_cents"] == 433_269
    assert acv["claimed_gross_cents"] > restoration["claimed_gross_cents"]


def test_a_restoration_gross_ignores_the_extent_of_the_damage(api):
    """PRD §3.11: "A `ChiefConservator` triages the incident, moving `damage_status`
    `REPORTED → TRIAGED` and setting `triage_class` from the request to
    `ROUTINE_MAINTENANCE`, `CONSERVATOR_TREATMENT` or `TOTAL_LOSS`, with an optional
    `triage_note`."
    PRD §3.11: "On settlement the named pool's `recovery_credits_cents` rises by
    `settlement_cents` and its `available_cents` rises by the same amount, and the
    pool's `version` increments — which is exactly the kind of unrequested movement
    that makes the pool version check in §2.11 necessary."

    Design: Difficulty/dual_variant_calc/claim_settlement_acv_vs_restoration_variant
    """
    state = _work_with_a_priced_repair(api)
    slight = fixtures.setup_incident_triaged(
        api,
        state["artwork"]["id"],
        damage_extent_pct=0.05,
        narrative="Superficial scuffing near the base",
        linked_proposal_id=state["proposal"]["id"],
    )
    assert slight["damage_extent_pct"] == 0.05
    assert slight["triage_class"] == "CONSERVATOR_TREATMENT"

    filed = fixtures.file_claim(
        api, slight["id"], "RESTORATION", credited_pool_id=state["pool"]["id"]
    )
    # A seventh of the earlier extent, and the restoration gross is unchanged.
    assert filed["claimed_gross_cents"] == 683_269
    assert filed["settlement_cents"] == 433_269

    settled = validate_success(
        api.resolve_insurance_claim(
            slight["id"],
            {"outcome": "SETTLE", "resolution_note": "paid on the repair estimate"},
            TEST_USERS["finance_headers"],
        )
    )
    assert settled["claim_status"] == "SETTLED"

    pool = fixtures.read_pool(api, state["pool"]["id"])
    assert pool["recovery_credits_cents"] == 433_269
    assert pool["available_cents"] == 20_260_769
