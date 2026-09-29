"""Transitive cascades out of a void or a revocation, the two fraud-scoring
variants, and the linkage status cycle."""
from test_helpers import (
    ADMIN,
    ANALYST,
    api_client,
    assert_instant_equals,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)


def _posted_basket_and_a_larger_authorization():
    """A member who earned 500 points on one basket and then committed 400 of
    them at the pump, in a household already carrying one analyst signal."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    banner = fixtures.create_banner(banner_code="CASC", name="Cascade Banner")
    fixtures.create_month_cycles(banner["id"], ("2026-08", "2026-09"))
    grocery = fixtures.create_grocery_site(banner["id"], "G-006")
    fuel = fixtures.create_owned_fuel_center(banner["id"], "F-006")
    household = fixtures.create_household(banner["id"], "HH-CASC-1")
    member = fixtures.create_member(banner["id"], alt_id="5550000007")
    fixtures.create_link(household["id"], member["id"], "PRIMARY", activate=True)
    fixtures.raise_signal(household["id"], "CROSS_BANNER_VELOCITY", 25)
    basket = fixtures.record_basket(
        member["id"],
        grocery["id"],
        [factories.purchase_line("GROCERY", 50000, 1)],
        "2026-08-05T10:00:00Z",
    )
    fixtures.post_basket(basket["id"], grocery["id"])
    redemption = fixtures.authorize_redemption(
        member["id"], fuel["id"], "5550000007", 400
    )
    return {
        "grocery": grocery,
        "member": member,
        "household": household,
        "basket": basket,
        "redemption": redemption,
    }


def test_voiding_a_posted_basket_reverses_the_accrual_and_repairs_the_overdraw():
    """Clawing back 500 points drives the balance below zero, and the repair
    voids the standing authorization to bring it back to zero.

    PRD: "Starting from the member's `available_points` as it stands after the
    hop 2 reversal, the repair walks that order and, before each candidate, stops
    if the balance has already reached zero or above; otherwise it voids that
    candidate, appends its `REDEMPTION_RELEASE` credit, and adds that credit to
    the running balance."

    Design: Difficulty/transitive_cascade/purchase_void_cascades_reversal_autovoid_signal_and_household_freeze
    """
    scenario = _posted_basket_and_a_larger_authorization()
    member_id = scenario["member"]["id"]

    voided = fixtures.void_basket(scenario["basket"]["id"], scenario["grocery"]["id"])

    assert voided["posting_status"] == "VOIDED"
    assert voided["accrual_status"] == "REVERSED"

    reversals, reversal_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REVERSAL"}
        )
    )
    assert reversal_meta["total_count"] == 1
    assert reversals[0]["points_delta"] == -500

    redemption = fixtures.get_redemption(scenario["redemption"]["id"])
    assert redemption["authorization_status"] == "VOIDED"
    assert redemption["points_debited_at_auth"] == 400

    releases, release_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REDEMPTION_RELEASE"}
        )
    )
    assert release_meta["total_count"] == 1
    assert releases[0]["points_delta"] == 400

    member = fixtures.get_member(member_id)
    assert member["available_points"] == 0
    assert member["lifetime_points"] == 0


def test_the_auto_void_raises_a_system_signal_that_freezes_the_household():
    """The fourth hop writes its own weighted signal, and the recomputed score
    crosses the threshold.

    PRD: "**Hop 4**, caused by hop 3: for **each** redemption actually voided in
    hop 3, one fraud signal is appended with `signal_type` `OVERDRAWN_AUTH`,
    `severity_weight` 40, `source` `SYSTEM`, `status` `OPEN`, and `household_id`
    set to the household of that member's **oldest** `ACTIVE` linkage ordered by
    the linkage's `created_at` ascending."

    Design: Difficulty/transitive_cascade/purchase_void_cascades_reversal_autovoid_signal_and_household_freeze
    """
    scenario = _posted_basket_and_a_larger_authorization()
    household_id = scenario["household"]["id"]

    fixtures.void_basket(scenario["basket"]["id"], scenario["grocery"]["id"])

    signals, signal_meta = validate_paginated(
        api_client.list_household_fraud_signals(
            household_id, ADMIN, {"signal_type": "OVERDRAWN_AUTH"}
        )
    )
    assert signal_meta["total_count"] == 1
    assert signals[0]["severity_weight"] == 40
    assert signals[0]["source"] == "SYSTEM"
    assert signals[0]["status"] == "OPEN"

    household = fixtures.get_household(household_id)
    assert household["fraud_score"] == 65
    assert household["status"] == "FROZEN"
    assert household["frozen_reason"] == "AUTO_FRAUD_SCORE"


def _cross_banner_member_with_a_live_authorization():
    """A member of one banner holding an active linkage into a second banner's
    household, with one authorization standing at that banner's pump."""
    fixtures.set_clock("2026-08-05T10:00:00Z")
    program = fixtures.cross_banner_program(points=300, alt_id="5550000008")
    program["redemption"] = fixtures.authorize_redemption(
        program["member"]["id"], program["fuel"]["id"], "5550000008", 300
    )
    return program


def test_revoking_a_linkage_recomputes_every_household_coverage_figure():
    """Revocation stamps its instant and empties the coverage sets the linkage
    was feeding.

    PRD: "Any linkage transition that adds a link to, or removes a link from, the
    `ACTIVE` set recomputes the household's `linked_member_count` (the count of
    its `ACTIVE` linkages), its `aggregate_available_points`, and its
    `cross_banner_member_ids` — the identifiers of the members holding an `ACTIVE`
    linkage to it whose own banner differs from the household's banner, ordered by
    the linkage's `created_at` ascending — and increments the household's
    `version` by one."

    Design: Difficulty/transitive_cascade/link_revoke_cascades_coverage_recompute_and_cross_banner_autovoid
    """
    program = _cross_banner_member_with_a_live_authorization()

    revoked = fixtures.revoke_link(program["link"]["id"])

    assert revoked["status"] == "REVOKED"
    assert_instant_equals(revoked["revoked_at"], "2026-08-05T10:00:00Z")

    household = fixtures.get_household(program["household"]["id"])
    assert household["linked_member_count"] == 0
    assert household["cross_banner_member_ids"] == []
    assert household["aggregate_available_points"] == 0


def test_losing_cross_banner_coverage_voids_the_authorization_it_had_supported():
    """The third hop reaches the pump: the redemption the lost coverage
    authorised is voided and its points credited back.

    PRD: "**Hop 3**, caused by hop 2: because this member's identifier is no
    longer present in that household's `cross_banner_member_ids`, every fuel
    redemption of this member that is still `AUTHORIZED` and sits at a site whose
    banner differs from the member's own banner is driven from `AUTHORIZED` to
    `VOIDED`, processed in `created_at` ascending order."

    Design: Difficulty/transitive_cascade/link_revoke_cascades_coverage_recompute_and_cross_banner_autovoid
    """
    program = _cross_banner_member_with_a_live_authorization()
    member_id = program["member"]["id"]

    fixtures.revoke_link(program["link"]["id"])

    assert (
        fixtures.get_redemption(program["redemption"]["id"])["authorization_status"]
        == "VOIDED"
    )

    releases, release_meta = validate_paginated(
        api_client.list_point_ledger_entries(
            ADMIN, {"member_id": member_id, "entry_type": "REDEMPTION_RELEASE"}
        )
    )
    assert release_meta["total_count"] == 1
    assert releases[0]["points_delta"] == 300

    assert fixtures.get_member(member_id)["available_points"] == 300


def _thawed_household_with_two_ageing_signals(scoring_mode: str, banner_code: str):
    """A household carrying two open signals of weight 35 and 45 raised on the
    first of August, manually thawed, observed ten days later.

    Both weights are analyst-supplied, so the sum of 80 crosses the default
    threshold of 60 on the way in and the household has to be thawed by hand
    before the variant under test can be observed from an `ACTIVE` start.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(
        banner_code=banner_code,
        name=f"{banner_code} Banner",
        fraud_scoring_mode=scoring_mode,
        freeze_threshold_score=60,
    )
    household = fixtures.create_household(banner["id"], f"HH-{banner_code}-1")
    first = fixtures.raise_signal(household["id"], "RAPID_TRANSFER", 35)
    second = fixtures.raise_signal(household["id"], "CROSS_BANNER_VELOCITY", 45)
    fixtures.unfreeze_household(household["id"])
    fixtures.set_clock("2026-08-11T00:00:00Z")
    return {"household": household, "signals": [first, second]}


def test_instantaneous_scoring_refreezes_the_household_when_a_third_signal_lands():
    """A plain sum of 85 crosses the threshold again, and the freeze is
    automatic.

    PRD: "Under `INSTANTANEOUS`, the household's `fraud_score` is the plain sum of
    the `severity_weight` values of its open signals."

    PRD: "A score at or above the threshold freezes an `ACTIVE` household, setting
    `frozen_reason` to `AUTO_FRAUD_SCORE`."

    Design: Difficulty/dual_variant_calc/fraud_score_instantaneous_refreezes_household_after_ten_days
    """
    scenario = _thawed_household_with_two_ageing_signals("INSTANTANEOUS", "INST")
    household_id = scenario["household"]["id"]

    fixtures.raise_signal(household_id, "CROSS_BANNER_VELOCITY", 5)

    household = fixtures.get_household(household_id)
    assert household["fraud_score"] == 85
    assert household["status"] == "FROZEN"
    assert household["frozen_reason"] == "AUTO_FRAUD_SCORE"

    _signals, meta = validate_paginated(
        api_client.list_household_fraud_signals(household_id, ADMIN, {"status": "OPEN"})
    )
    assert meta["total_count"] == 3


def test_instantaneous_scoring_ignores_the_logical_clock_entirely():
    """Ten days of ageing changes nothing while the signals stay open.

    PRD: "A signal never loses weight while it stays open, so the score does not
    depend on the logical clock at all."

    Design: Difficulty/dual_variant_calc/fraud_score_instantaneous_refreezes_household_after_ten_days
    """
    scenario = _thawed_household_with_two_ageing_signals("INSTANTANEOUS", "INST")
    household_id = scenario["household"]["id"]

    ten_days_later = fixtures.get_household(household_id)
    assert ten_days_later["fraud_score"] == 80
    assert ten_days_later["status"] == "ACTIVE"
    assert ten_days_later["frozen_reason"] is None

    fixtures.set_clock("2026-09-01T00:00:00Z")
    a_month_later = fixtures.get_household(household_id)
    assert a_month_later["fraud_score"] == 80
    assert a_month_later["version"] == ten_days_later["version"]


def test_trailing_weighted_scoring_stays_below_the_threshold_after_ten_days():
    """Half the weight has decayed away, so the same third signal leaves the
    household active.

    PRD: "Each signal's weighted contribution is its `severity_weight` multiplied
    by its decay factor, the contributions are summed at **full precision**, and
    the **sum** is rounded half up once to a whole score."

    Design: Difficulty/dual_variant_calc/fraud_score_trailing_weighted_decays_below_threshold_after_ten_days
    """
    scenario = _thawed_household_with_two_ageing_signals("TRAILING_WEIGHTED", "TRAIL")
    household_id = scenario["household"]["id"]

    fixtures.raise_signal(household_id, "CROSS_BANNER_VELOCITY", 5)

    household = fixtures.get_household(household_id)
    assert household["fraud_score"] == 45
    assert household["status"] == "ACTIVE"
    assert household["frozen_reason"] is None
    assert household["frozen_at"] is None

    _signals, meta = validate_paginated(
        api_client.list_household_fraud_signals(household_id, ADMIN, {"status": "OPEN"})
    )
    assert meta["total_count"] == 3


def test_trailing_weighted_decay_is_five_percent_per_whole_day_of_age():
    """Ten whole days halve both weights, and the drop is a read-only
    projection.

    PRD: "Its decay factor is one minus a per-day decay of 0.05 multiplied by
    that whole-day age, floored at 0.25: a signal loses five percent of its
    weight per full day until it bottoms out at a quarter of its original weight,
    which it then keeps indefinitely."

    Design: Difficulty/dual_variant_calc/fraud_score_trailing_weighted_decays_below_threshold_after_ten_days
    """
    scenario = _thawed_household_with_two_ageing_signals("TRAILING_WEIGHTED", "TRAIL")
    household_id = scenario["household"]["id"]

    ten_days_later = fixtures.get_household(household_id)
    assert ten_days_later["fraud_score"] == 40
    assert ten_days_later["status"] == "ACTIVE"

    fixtures.set_clock("2026-08-01T12:00:00Z")
    same_day = fixtures.get_household(household_id)
    assert same_day["fraud_score"] == 80, "half a day is zero whole days of age"
    assert same_day["version"] == ten_days_later["version"]


def _pending_primary_linkage():
    """A proposed linkage that has never been activated."""
    fixtures.set_clock("2026-08-01T00:00:00Z")
    banner = fixtures.create_banner(banner_code="LINK", name="Link Banner")
    household = fixtures.create_household(banner["id"], "HH-LINK-1")
    member = fixtures.create_member(banner["id"], alt_id="5550000005")
    link = validate_success(
        api_client.create_household_link(
            factories.household_link_payload(household["id"], member["id"], "PRIMARY"),
            ANALYST,
        ),
        201,
    )
    return {"household": household, "member": member, "link": link}


def test_reactivating_a_suspended_linkage_restamps_its_activation_instant():
    """The linkage returns to `ACTIVE` with a fresh `activated_at` and no
    revocation instant.

    PRD: "Either way, activation sets `status` to `ACTIVE` and stamps
    `activated_at` with the logical clock — overwriting the previous activation
    instant on a re-activation rather than preserving it — and then performs the
    coverage propagation of §2.11: `linked_member_count`,
    `aggregate_available_points` and `cross_banner_member_ids` are recomputed on
    the household and its `version` increments by one."

    Design: Difficulty/non_linear_state_machine/household_link_cycles_active_suspended_active_and_restamps_activation
    """
    scenario = _pending_primary_linkage()
    link_id = scenario["link"]["id"]

    first_activation = fixtures.activate_link(link_id)
    assert_instant_equals(first_activation["activated_at"], "2026-08-01T00:00:00Z")

    fixtures.suspend_link(link_id)
    fixtures.set_clock("2026-08-11T00:00:00Z")
    second_activation = fixtures.activate_link(link_id)

    assert second_activation["status"] == "ACTIVE"
    assert_instant_equals(second_activation["activated_at"], "2026-08-11T00:00:00Z")
    assert second_activation["revoked_at"] is None


def test_the_linkage_cycle_moves_the_household_count_out_and_back_in():
    """Coverage leaves the household on suspension and returns on
    reactivation.

    PRD: "Activation is the cycle hinge of the linkage lifecycle: the same action
    serves `PENDING → ACTIVE` and `SUSPENDED → ACTIVE`, and a linkage may traverse
    `ACTIVE → SUSPENDED → ACTIVE` any number of times."

    PRD: "Suspension takes an `ACTIVE` linkage to `SUSPENDED`. It performs the
    same coverage propagation — `linked_member_count`,
    `aggregate_available_points` and `cross_banner_member_ids` recomputed,
    household `version` incremented — and nothing more."

    Design: Difficulty/non_linear_state_machine/household_link_cycles_active_suspended_active_and_restamps_activation
    """
    scenario = _pending_primary_linkage()
    link_id = scenario["link"]["id"]
    household_id = scenario["household"]["id"]

    fixtures.activate_link(link_id)
    assert fixtures.get_household(household_id)["linked_member_count"] == 1

    fixtures.suspend_link(link_id)
    assert fixtures.get_household(household_id)["linked_member_count"] == 0

    fixtures.set_clock("2026-08-11T00:00:00Z")
    fixtures.activate_link(link_id)
    assert fixtures.get_household(household_id)["linked_member_count"] == 1

    _links, meta = validate_paginated(
        api_client.list_household_links(
            ADMIN, {"household_id": household_id, "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
