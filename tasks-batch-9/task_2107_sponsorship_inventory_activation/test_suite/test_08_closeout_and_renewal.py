"""Closing out a season: makegood credit, termination and renewal scoring."""

from test_helpers import (
    AFTER_TERM_END,
    ApiErrorId,
    TEST_USERS,
    assert_reserved_units_total,
    assert_sponsor_survey,
    assign_staff,
    cancel_booking,
    close_contract,
    countersign_contract,
    create_staff_member,
    file_survey,
    read_assignment,
    read_booking,
    read_contract,
    read_entitlement,
    read_inventory_asset,
    read_property,
    read_sponsor,
    set_clock,
    setup_active_contract_with_booking,
    setup_closed_partial_delivery_contract,
    setup_committed_value_conservation,
    setup_contract_scenario,
    setup_fully_delivered_contract,
    setup_makegood_split_contract,
    terminate_contract,
    validate_error,
    validate_success,
)

APPROVER = TEST_USERS["approver_headers"]


# ---------------------------------------------------------------------------
# Makegood credit: the pool, then the floor-then-remainder split
# ---------------------------------------------------------------------------
def test_makegood_pool_is_capped_at_fifteen_percent_of_the_cash_leg(api):
    """PRD §3.9: "For every entitlement of the contract whose `status` is not
    `WAIVED`, its shortfall value is the greater of zero and `promised_units`
    minus `delivered_units`, multiplied by that entitlement's `unit_value_cents`.
    The total shortfall is the sum of those shortfall values. The credit pool is
    the smaller of that total shortfall and 15 percent of `cash_value_cents` —
    that is, `cash_value_cents` multiplied by 0.15 and then truncated downward to
    a whole cent."
    PRD §3.9: "First the trade leg is re-valued under the **audited** ordering,
    which reverses the two operations used at signature: the ceiling —
    `cash_value_cents` multiplied by 0.25, rounded half up to a whole cent — is
    applied to the raw `in_kind_declared_value_cents` first, taking whichever of
    the two is smaller, and only then is that capped figure multiplied by one
    minus the category haircut rate and rounded half up to a whole cent."

    Design: Difficulty/combinatorial_formula/makegood_floor_per_bucket_then_remainder_mode_b
    """
    scenario = setup_makegood_split_contract()
    assert scenario["contract"]["cash_value_cents"] == 3_469_320

    closed = close_contract(scenario["contract"]["id"])

    assert closed["makegood_credit_cents"] == 520_398, (
        "the 2421000 total shortfall exceeds the 520398 allowance, so the pool "
        f"is the allowance; got {closed['makegood_credit_cents']}"
    )
    assert closed["in_kind_recognized_value_cents"] == 563_765
    assert closed["total_recognized_value_cents"] == 4_033_085


def test_makegood_shares_are_floored_with_the_remainder_to_the_largest_shortfall(api):
    """PRD §3.9: "Otherwise the entitlements carrying a positive shortfall value
    are ordered by shortfall value descending, ties broken by `created_at`
    ascending and never by identifier, and each in turn receives the credit pool
    multiplied by its own shortfall value, divided by the total shortfall,
    truncated downward to a whole cent. Truncating each share individually leaves
    a remainder — the credit pool less the sum of the truncated shares — and that
    entire remainder is added to the first entitlement in the ordering, the one
    with the largest shortfall."
    PRD §3.9: "Third, the entitlement statuses are frozen: every entitlement
    still `PENDING` or `PARTIAL` moves to `SHORTFALL`, while entitlements already
    `FULFILLED` or `WAIVED` are untouched."

    Design: Difficulty/combinatorial_formula/makegood_floor_per_bucket_then_remainder_mode_b
    """
    scenario = setup_makegood_split_contract()
    closed = close_contract(scenario["contract"]["id"])

    clause_a = read_entitlement(scenario["entitlements"][0]["id"])
    clause_b = read_entitlement(scenario["entitlements"][1]["id"])

    assert clause_a["makegood_credit_cents"] == 435_278, (
        "the largest shortfall takes its floored share plus the whole remainder; "
        f"got {clause_a['makegood_credit_cents']}"
    )
    assert clause_b["makegood_credit_cents"] == 85_120
    assert (
        clause_a["makegood_credit_cents"] + clause_b["makegood_credit_cents"]
        == closed["makegood_credit_cents"]
    )
    assert clause_a["status"] == "SHORTFALL"
    assert clause_b["status"] == "SHORTFALL"


# ---------------------------------------------------------------------------
# Renewal likelihood: two weightings over the same delivery data
# ---------------------------------------------------------------------------
def test_delivery_only_renewal_score_uses_the_seventy_five_twenty_five_weighting(api):
    """PRD §3.9: "The delivery factor is 100.00 when the target's non-`WAIVED`
    entitlements promise nothing at all; otherwise it is 100 multiplied by the sum
    of `delivered_units` over those entitlements, divided by the sum of
    `promised_units` over the same entitlements, rounded half up to 2 decimal
    places. The reliability factor starts from a penalty: zero when the target's
    `cash_value_cents` is 0, and otherwise 100 multiplied by the target's
    `makegood_credit_cents`, divided by its `cash_value_cents`, rounded half up to
    2 decimal places; reliability is then 100 less that penalty, with the penalty
    capped at 100 so reliability never goes below zero."
    PRD §3.9: "When no survey exists, the survey term is absent rather than
    treated as zero, and the raw score is the delivery factor weighted at 0.75
    plus the reliability factor weighted at 0.25 — so identical delivery data
    scores differently under the two variants."
    PRD §3.9: "`renewal_band` follows from it directly: `HIGH` at 70 or above,
    `MEDIUM` at 40 or above but below 70, and `LOW` below 40."

    Design: Difficulty/dual_variant_calc/renewal_score_survey_weighted_versus_delivery_only
    """
    scenario = setup_closed_partial_delivery_contract()
    assert scenario["contract"]["makegood_credit_cents"] == 465_750

    sponsor = read_sponsor(scenario["sponsor"]["id"])
    assert sponsor["renewal_likelihood_score"] == 51.25, (
        "0.75 * 40.00 delivery plus 0.25 * 85.00 reliability; got "
        f"{sponsor['renewal_likelihood_score']}"
    )
    assert sponsor["renewal_band"] == "MEDIUM"


def test_first_survey_switches_the_score_to_the_survey_weighted_variant(api):
    """PRD §3.9: "Its `composite_score` is computed at filing: the
    `satisfaction_score` weighted at 0.40, the `activation_quality_score` at 0.35
    and the `reporting_quality_score` at 0.25 are summed, that sum is multiplied
    by 10 and rounded half up to 2 decimal places, and then an intent adjustment
    of plus 10 for `YES`, zero for `MAYBE` and minus 15 for `NO` is added; the
    result is finally clamped into the range 0 to 100."
    PRD §3.9: "When at least one survey exists, the survey factor is weighted at
    0.50, the delivery factor at 0.35 and the reliability factor at 0.15, and the
    three weighted terms are summed."
    PRD §3.9: "`renewal_band` follows from it directly: `HIGH` at 70 or above,
    `MEDIUM` at 40 or above but below 70, and `LOW` below 40."

    Design: Difficulty/dual_variant_calc/renewal_score_survey_weighted_versus_delivery_only
    """
    scenario = setup_closed_partial_delivery_contract()
    before = read_sponsor(scenario["sponsor"]["id"])
    assert before["renewal_likelihood_score"] == 51.25

    survey = file_survey(
        scenario["contract"]["id"], scenario["sponsor"]["id"],
        satisfaction_score=8, activation_quality_score=9,
        reporting_quality_score=7, renewal_intent="YES",
    )
    assert survey["composite_score"] == 91.00

    after = read_sponsor(scenario["sponsor"]["id"])
    assert after["renewal_likelihood_score"] == 72.25, (
        "0.50 * 91.00 survey plus 0.35 * 40.00 delivery plus 0.15 * 85.00 "
        f"reliability; got {after['renewal_likelihood_score']}"
    )
    assert after["renewal_band"] == "HIGH"
    assert after["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Termination unwinds the whole subtree
# ---------------------------------------------------------------------------
def _terminable_scenario():
    scenario = setup_active_contract_with_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    scenario["staff_member"] = create_staff_member()
    scenario["assignment"] = assign_staff(
        scenario["booking"]["id"], scenario["staff_member"]["id"],
        shift_start="2026-09-10T18:00:00Z",
        shift_end="2026-09-10T21:00:00Z",
    )
    set_clock("2026-09-05T00:00:00Z")
    return scenario


def test_termination_waives_the_clause_and_preempts_its_booking(api):
    """PRD §3.9: "Termination unwinds the whole subtree in four hops. Every
    entitlement of the contract whose `status` is `PENDING` or `PARTIAL` moves to
    `WAIVED`; entitlements already `FULFILLED`, and any already `WAIVED`, are left
    alone. Each newly waived entitlement then drives its own `SCHEDULED` bookings
    `SCHEDULED → PREEMPTED` — a state reachable only through this cascade and
    never by operator request."

    Design: Difficulty/transitive_cascade/terminate_contract_cascades_entitlement_booking_asset_and_staff
    """
    scenario = _terminable_scenario()
    assert scenario["contract"]["total_recognized_value_cents"] == 3_105_000

    terminated = terminate_contract(
        scenario["contract"]["id"], reason="Sponsor insolvency"
    )
    assert terminated["status"] == "TERMINATED"

    assert read_entitlement(scenario["entitlement"]["id"])["status"] == "WAIVED"
    assert read_booking(scenario["booking"]["id"])["status"] == "PREEMPTED"


def test_termination_releases_the_asset_units_and_the_shift(api):
    """PRD §3.9: "Each preempted booking releases its hold, so the asset's
    `reserved_units_total` drops by that booking's `units_booked` and the asset's
    `version` increments by 1. Each preempted booking also moves its assignments
    sitting at `ASSIGNED` or `CHECKED_IN` to `RELEASED`, lowering each staffer's
    `scheduled_minutes` by the shift's whole-minute length."
    PRD §3.9: "In parallel the property's committed position is recomputed:
    because a `TERMINATED` contract belongs to neither of the contributing status
    sets, it drops out of `committed_gross_value_cents`, `sellout_pct` is
    refreshed, and the property's `version` increments by 1."

    Design: Difficulty/transitive_cascade/terminate_contract_cascades_entitlement_booking_asset_and_staff
    """
    scenario = _terminable_scenario()
    terminate_contract(scenario["contract"]["id"], reason="Sponsor insolvency")

    assert read_assignment(scenario["assignment"]["id"])["status"] == "RELEASED"
    assert_reserved_units_total(
        read_inventory_asset(scenario["asset"]["id"]), 0
    )

    prop = read_property(scenario["property"]["id"])
    assert prop["committed_gross_value_cents"] == 0
    assert prop["sellout_pct"] == 0.00


# ---------------------------------------------------------------------------
# Countersign then terminate conserves the property's committed position
# ---------------------------------------------------------------------------
def test_countersign_then_terminate_returns_the_committed_position(api):
    """PRD §2.9: "Third, `committed_gross_value_cents` on a property is at all
    times the sum of `total_recognized_value_cents` over that property's contracts
    whose `status` is `COUNTERSIGNED` or `ACTIVE`, so a contract entering or
    leaving that pair of states moves the property's position and, with it,
    `sellout_pct` and the property's `version`."
    PRD §3.1: "`sellout_pct` is 0.00 when `inventory_target_value_cents` is 0;
    otherwise it is 100 multiplied by `committed_gross_value_cents`, divided by
    `inventory_target_value_cents`, rounded half up to 2 decimal places."

    Design: Difficulty/compensating_invariant/countersign_then_terminate_conserves_property_committed_value
    """
    estate = setup_committed_value_conservation()
    before = estate["property"]
    assert before["committed_gross_value_cents"] == 3_105_000
    assert before["sellout_pct"] == 6.21

    countersign_contract(estate["contract_two"]["id"], before["id"])
    mid = read_property(before["id"])
    assert mid["committed_gross_value_cents"] == 4_545_000
    assert mid["sellout_pct"] == 9.09

    terminate_contract(estate["contract_two"]["id"], reason="Budget withdrawn")
    after = read_property(before["id"])
    assert after["committed_gross_value_cents"] == 3_105_000
    assert after["committed_gross_value_cents"] == before["committed_gross_value_cents"]
    assert after["sellout_pct"] == 6.21


def test_terminated_sibling_leaves_the_other_deal_untouched(api):
    """PRD §3.9: "Not every deal survives the season. A `ContractApprover` may
    terminate a contract that is `COUNTERSIGNED` or `ACTIVE`, optionally recording
    a `reason`; there is no other precondition, and the contract's
    `makegood_credit_cents` stays at 0 because a terminated deal earns no
    compensation."
    PRD §2.9: "Third, `committed_gross_value_cents` on a property is at all times
    the sum of `total_recognized_value_cents` over that property's contracts whose
    `status` is `COUNTERSIGNED` or `ACTIVE`, so a contract entering or leaving that
    pair of states moves the property's position and, with it, `sellout_pct` and
    the property's `version`."

    Design: Difficulty/compensating_invariant/countersign_then_terminate_conserves_property_committed_value
    """
    estate = setup_committed_value_conservation()

    countersigned = countersign_contract(
        estate["contract_two"]["id"], estate["property"]["id"]
    )
    assert countersigned["total_recognized_value_cents"] == 1_440_000

    terminated = terminate_contract(
        estate["contract_two"]["id"], reason="Budget withdrawn"
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated["makegood_credit_cents"] == 0

    survivor = read_contract(estate["contract_one"]["id"])
    assert survivor["status"] == "COUNTERSIGNED", (
        "terminating the sibling leaves the first deal untouched"
    )
    assert survivor["total_recognized_value_cents"] == 3_105_000


# ---------------------------------------------------------------------------
# A fully delivered deal closes clean
# ---------------------------------------------------------------------------
def test_full_delivery_closes_with_zero_makegood_and_a_perfect_renewal_score(api):
    """PRD §3.9: "If the total shortfall is zero, every entitlement's
    `makegood_credit_cents` and the contract's `makegood_credit_cents` are all 0
    and nothing further is allocated."
    PRD §3.9: "Third, the entitlement statuses are frozen: every entitlement
    still `PENDING` or `PARTIAL` moves to `SHORTFALL`, while entitlements already
    `FULFILLED` or `WAIVED` are untouched. Fourth, the contract's
    `fulfillment_status` is finalized to `SHORTFALL` if any entitlement ended in
    `SHORTFALL`, and to `FULFILLED` otherwise. Fifth, the contract's `status`
    becomes `CLOSED`. Sixth, the property is reconciled: a `CLOSED` contract no
    longer contributes to `committed_gross_value_cents` but does still contribute
    to `delivered_media_value_cents`, `sellout_pct` is refreshed, and the
    property's `version` increments by 1."
    PRD §3.9: "When no survey exists, the survey term is absent rather than
    treated as zero, and the raw score is the delivery factor weighted at 0.75
    plus the reliability factor weighted at 0.25 — so identical delivery data
    scores differently under the two variants."

    Design: Corner/calculations/full_delivery_closes_with_zero_makegood_and_perfect_renewal_score
    """
    scenario = setup_fully_delivered_contract()

    closed = close_contract(scenario["contract"]["id"])
    assert closed["status"] == "CLOSED"
    assert closed["fulfillment_status"] == "FULFILLED"
    assert closed["makegood_credit_cents"] == 0
    assert closed["delivered_media_value_cents"] == 3_375_000

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["status"] == "FULFILLED"
    assert entitlement["makegood_credit_cents"] == 0

    sponsor = read_sponsor(scenario["sponsor"]["id"])
    assert sponsor["renewal_likelihood_score"] == 100.00
    assert sponsor["renewal_band"] == "HIGH"
    assert sponsor["status"] == "ACTIVE"

    prop = read_property(scenario["property"]["id"])
    assert prop["committed_gross_value_cents"] == 0
    assert prop["delivered_media_value_cents"] == 3_375_000


def test_close_is_refused_while_a_booking_is_still_scheduled(api):
    """PRD §3.9: "Two conditions gate it, in this order: the logical clock must
    have reached `term_end` or passed it, or the request fails with
    `ERR_TERM_NOT_ENDED`; and no booking belonging to any of the contract's
    entitlements may still be `SCHEDULED`, or it fails with `ERR_OPEN_BOOKINGS` —
    every occupation must have been delivered, cancelled or preempted before the
    books can be shut."
    PRD §3.9: "Third, the entitlement statuses are frozen: every entitlement
    still `PENDING` or `PARTIAL` moves to `SHORTFALL`, while entitlements already
    `FULFILLED` or `WAIVED` are untouched. Fourth, the contract's
    `fulfillment_status` is finalized to `SHORTFALL` if any entitlement ended in
    `SHORTFALL`, and to `FULFILLED` otherwise."

    Design: Corner/state_machines/contract_close_with_scheduled_booking_returns_open_bookings
    """
    scenario = setup_active_contract_with_booking(
        units_booked=4, contract_overrides={"exclusivity_scope": "CATEGORY"}
    )
    set_clock(AFTER_TERM_END)

    blocked = api.close_contract(scenario["contract"]["id"], APPROVER)
    validate_error(blocked, ApiErrorId.ERR_OPEN_BOOKINGS.value)

    cancel_booking(scenario["booking"]["id"], reason="Season over, never ran")

    closed = validate_success(
        api.close_contract(scenario["contract"]["id"], APPROVER)
    )
    assert closed["status"] == "CLOSED"
    assert closed["makegood_credit_cents"] == 465_750
    assert closed["fulfillment_status"] == "SHORTFALL"

    entitlement = read_entitlement(scenario["entitlement"]["id"])
    assert entitlement["status"] == "SHORTFALL"
    assert entitlement["makegood_credit_cents"] == 465_750


def test_sponsor_survey_is_written_once_and_carries_no_version(api):
    """PRD §2.4: "Two resource kinds are exceptions and are written once: a
    rate-card line and a sponsor survey carry only `id` and `created_at`. Neither
    `updated_at` nor `version` exists on a rate-card line or on a sponsor survey,
    and neither is ever returned for them."
    PRD §3.9: "The survey records its `contract_id` from the request path and
    stamps `submitted_by_user_id` with the caller's `X-User-ID`, which by
    definition equals the contract's `sponsor_id`."
    PRD §3.9: "Its `composite_score` is computed at filing: the
    `satisfaction_score` weighted at 0.40, the `activation_quality_score` at 0.35
    and the `reporting_quality_score` at 0.25 are summed, that sum is multiplied
    by 10 and rounded half up to 2 decimal places, and then an intent adjustment
    of plus 10 for `YES`, zero for `MAYBE` and minus 15 for `NO` is added; the
    result is finally clamped into the range 0 to 100."

    Design: Corner/entities/sponsor_survey_is_immutable_and_carries_no_version
    """
    scenario = setup_contract_scenario(
        stage="ACTIVE", contract_overrides={"exclusivity_scope": "CATEGORY"}
    )

    survey = file_survey(
        scenario["contract"]["id"], scenario["sponsor"]["id"],
        satisfaction_score=6, activation_quality_score=6,
        reporting_quality_score=6, renewal_intent="MAYBE",
    )
    assert_sponsor_survey(survey)
    assert survey["composite_score"] == 60.00
    assert survey["submitted_by_user_id"] == scenario["sponsor"]["id"]
    assert "version" not in survey
    assert "updated_at" not in survey

    listed = validate_success(
        api.list_surveys(scenario["contract"]["id"], APPROVER)
    )
    assert len(listed) == 1
    assert listed[0]["id"] == survey["id"]
    assert "version" not in listed[0]
    assert "updated_at" not in listed[0]
