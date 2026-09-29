"""Death-loss reporting, verification and the chronological liability sweep."""

from test_helpers import (
    ApiErrorId,
    assert_death_loss_report,
    make_grazier_headers,
    make_range_consultant_headers,
    read_lot,
    read_pasture,
    report_death_loss,
    review_death_loss_as_consultant,
    review_death_loss_as_grazier,
    setup_north_bench_lot_on_feed,
    setup_school_section_lot_on_feed,
    setup_two_contracts_two_liability_regimes,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# The two liability regimes on identical losses
# ===========================================================================

def test_owner_bears_all_absorbs_the_whole_loss_with_no_credit(api):
    """PRD 3.6: "Otherwise, if the contract's `death_loss_terms` is `OWNER_BEARS_ALL`,
    the owner absorbs the whole report: `owner_liable_head` is the full `head_lost` and
    `grazier_liable_head` is 0."
    PRD 3.6: "Each row's `credit_cents` is then its grazier-liable head multiplied by
    the contract's `head_value_cents`, multiplied by 60 percent — the platform's
    death-credit factor, since a dead animal is not worth its full declared value to the
    owner — and rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/death_loss_liability_owner_bears_all_vs_threshold_share
    """
    world = setup_two_contracts_two_liability_regimes()

    resp = api.review_death_loss(
        world.report_a["id"], {"decision": "CONFIRM"},
        make_range_consultant_headers(world.consultant_id),
    )
    confirmed = validate_success(resp, 200)
    assert_death_loss_report(confirmed)

    assert confirmed["owner_liable_head"] == 3
    assert confirmed["grazier_liable_head"] == 0
    assert confirmed["credit_cents"] == 0

    assert read_lot(world.lot_a["id"], world.grazier_id)["confirmed_death_head"] == 3
    assert read_pasture(world.pasture_a["id"], world.grazier_id)["stocked_head_count"] == 97


def test_the_threshold_regime_splits_the_same_loss_and_pays_a_credit(api):
    """PRD 3.6: "Otherwise the regime is `GRAZIER_SHARE_ABOVE_THRESHOLD`, and the owner
    absorbs whatever remains of the threshold at the time this row is reached: the
    threshold in head less the running total already swept, floored at 0 so it never
    goes negative, and then capped at the row's own `head_lost`."
    PRD 3.6: "Before the sweep begins, a threshold in head is computed as the lot's
    `head_count_received` multiplied by the contract's `death_loss_threshold_pct`
    divided by 100, with any fraction discarded."
    PRD 3.6: "Each row's `credit_cents` is then its grazier-liable head multiplied by
    the contract's `head_value_cents`, multiplied by 60 percent — the platform's
    death-credit factor, since a dead animal is not worth its full declared value to the
    owner — and rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/death_loss_liability_owner_bears_all_vs_threshold_share
    """
    world = setup_two_contracts_two_liability_regimes()

    resp = api.review_death_loss(
        world.report_b["id"], {"decision": "CONFIRM"},
        make_range_consultant_headers(world.consultant_id),
    )
    confirmed = validate_success(resp, 200)

    assert confirmed["owner_liable_head"] == 2, "The threshold on 100 head at 2.0 percent"
    assert confirmed["grazier_liable_head"] == 1
    assert confirmed["credit_cents"] == 78000

    assert read_lot(world.lot_b["id"], world.grazier_id)["confirmed_death_head"] == 3
    assert read_pasture(world.pasture_b["id"], world.grazier_id)["stocked_head_count"] == 97


# ===========================================================================
# Head-count conservation across confirm and void
# ===========================================================================

def test_confirming_two_losses_walks_the_threshold_and_drops_the_stocked_count(api):
    """PRD 3.6: "Consider a lot that received 150 head under a contract with a 2.0
    percent threshold and a declared per-head value of 140000 cents. The threshold works
    out to 3 head. Two head die of disease on the 20th of August and two more die of
    disease on the 5th of September. The first report is entirely inside the threshold,
    so it splits 2 head to the owner and none to the grazier; the second finds only 1
    head of threshold left, so it splits 1 to the owner and 1 to the grazier, and the
    lot's total death-loss credit comes to 84000 cents."
    PRD 2.9: "Its `stocked_head_count` is the sum, over the lots on that pasture whose
    `status` is `ON_FEED` or `REMOVAL_SCHEDULED`, of the head received on the lot less
    the head confirmed dead on it."

    Design: Difficulty/compensating_invariant/head_count_conserved_across_death_confirm_and_void
    """
    world = setup_north_bench_lot_on_feed()
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 150

    first = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-08-20", head_lost=2, cause="DISEASE"
    )
    second = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-09-05", head_lost=2, cause="DISEASE"
    )
    first = review_death_loss_as_consultant(first["id"], world.consultant_id, "CONFIRM")
    second = review_death_loss_as_consultant(second["id"], world.consultant_id, "CONFIRM")

    assert first["owner_liable_head"] == 2 and first["grazier_liable_head"] == 0
    assert first["credit_cents"] == 0
    assert second["owner_liable_head"] == 1 and second["grazier_liable_head"] == 1
    assert second["credit_cents"] == 84000

    assert read_lot(world.lot_id, world.grazier_id)["confirmed_death_head"] == 4
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 146


def test_voiding_both_confirmed_losses_restores_every_head(api):
    """PRD 3.6: "Rows outside the sweep hold zeros. `REPORTED`, `REJECTED` and `VOIDED`
    reports all carry `owner_liable_head`, `grazier_liable_head` and `credit_cents` at
    0, and voiding a previously confirmed report zeroes its three figures before the
    remaining confirmed rows are swept again."
    PRD 2.9: "Recomputation is idempotent: a recompute that finds nothing changed is not
    an error, and a void that reverses a cascade must restore the pre-cascade values
    exactly — voiding a confirmed death loss, for instance, restores the pasture's
    `stocked_head_count` to the value it held before the confirmation, because head
    counts are conserved."

    Design: Difficulty/compensating_invariant/head_count_conserved_across_death_confirm_and_void
    """
    world = setup_north_bench_lot_on_feed()
    first = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-08-20", head_lost=2, cause="DISEASE"
    )
    second = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-09-05", head_lost=2, cause="DISEASE"
    )
    review_death_loss_as_consultant(first["id"], world.consultant_id, "CONFIRM")
    review_death_loss_as_consultant(second["id"], world.consultant_id, "CONFIRM")
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 146

    second = review_death_loss_as_grazier(
        second["id"], world.grazier_id, "VOID", note="Head recovered on a neighbour's lease"
    )
    assert second["status"] == "VOIDED"
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 148

    first = review_death_loss_as_grazier(
        first["id"], world.grazier_id, "VOID", note="Head recovered on a neighbour's lease"
    )

    assert first["status"] == "VOIDED"
    assert first["grazier_liable_head"] == 0 and first["credit_cents"] == 0
    assert second["grazier_liable_head"] == 0 and second["credit_cents"] == 0
    assert read_lot(world.lot_id, world.grazier_id)["confirmed_death_head"] == 0
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 150


# ===========================================================================
# Rejection, the infrastructure override and the head-count guard
# ===========================================================================

def test_a_rejected_report_moves_no_head_and_cannot_be_confirmed_afterwards(api):
    """PRD 3.6: "Verification belongs to a `RangeConsultant`, who confirms the report
    (`REPORTED → CONFIRMED`) or rejects it (`REPORTED → REJECTED`); no ownership tie is
    required of them, because the consultant's whole value here is independence."
    PRD 3.6: "`REJECTED` and `VOIDED` are terminal; a `decision` the current `status`
    does not permit is rejected with `ERR_DEATH_LOSS_INVALID_STATE`."
    PRD 3.6: "Rows outside the sweep hold zeros. `REPORTED`, `REJECTED` and `VOIDED`
    reports all carry `owner_liable_head`, `grazier_liable_head` and `credit_cents` at
    0, and voiding a previously confirmed report zeroes its three figures before the
    remaining confirmed rows are swept again."

    Design: Corner/state_machines/rejected_death_report_moves_no_head_and_cannot_be_confirmed_later
    """
    world = setup_north_bench_lot_on_feed()
    report = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-08-20", head_lost=2, cause="UNKNOWN"
    )

    rejected = review_death_loss_as_consultant(
        report["id"], world.consultant_id, "REJECT", note="No carcass located"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["owner_liable_head"] == 0
    assert rejected["grazier_liable_head"] == 0
    assert rejected["credit_cents"] == 0
    assert read_lot(world.lot_id, world.grazier_id)["confirmed_death_head"] == 0
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 150

    resp = api.review_death_loss(
        report["id"], {"decision": "CONFIRM"},
        make_range_consultant_headers(world.consultant_id),
    )
    validate_error(resp, ApiErrorId.ERR_DEATH_LOSS_INVALID_STATE.value, 409)


def test_an_infrastructure_failure_death_is_grazier_liable_under_owner_bears_all(api):
    """PRD 3.6: "A report whose `cause` is `INFRASTRUCTURE_FAILURE` is always entirely
    the grazier's exposure regardless of the contract's regime — a failed water gap or a
    downed fence is the grazier's job — so its `owner_liable_head` is 0 and its
    `grazier_liable_head` is the full `head_lost`."
    PRD 3.6: "Each row's `credit_cents` is then its grazier-liable head multiplied by
    the contract's `head_value_cents`, multiplied by 60 percent — the platform's
    death-credit factor, since a dead animal is not worth its full declared value to the
    owner — and rounded half up to a whole cent."

    Design: Corner/calculations/infrastructure_failure_death_is_grazier_liable_even_under_owner_bears_all
    """
    world = setup_school_section_lot_on_feed(death_loss=True)
    assert world.death_report["owner_liable_head"] == 2
    assert world.death_report["credit_cents"] == 0

    infra = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-09-20", head_lost=3,
        cause="INFRASTRUCTURE_FAILURE", necropsy_performed=True,
    )
    resp = api.review_death_loss(
        infra["id"], {"decision": "CONFIRM", "note": "Cattle went down in a dry tank"},
        make_range_consultant_headers(world.consultant_id),
    )
    confirmed = validate_success(resp, 200)

    assert confirmed["owner_liable_head"] == 0
    assert confirmed["grazier_liable_head"] == 3
    assert confirmed["credit_cents"] == 234000
    assert read_lot(world.lot_id, world.grazier_id)["confirmed_death_head"] == 5
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 35


def test_a_report_claiming_more_head_than_are_alive_is_rejected(api):
    """PRD 3.6: "A report may not claim more head than are still alive: `head_lost` may
    not exceed the head received on the lot less the head already confirmed dead, and a
    claim beyond that is rejected with `ERR_HEAD_COUNT_INCONSISTENT`."
    PRD 2.9: "On the lot side, `confirmed_death_head` is the sum of head lost across the
    lot's confirmed death-loss reports, and `days_on_feed` is the whole number of days
    from the `in_date` to the `out_date`, computed by discarding any fractional
    remainder and left at 0 until the weigh-out lands."

    Design: Corner/validations/death_report_exceeding_live_head_returns_head_count_inconsistent
    """
    world = setup_north_bench_lot_on_feed()
    first = report_death_loss(
        world.lot_id, world.grazier_id, death_date="2026-08-20", head_lost=2, cause="DISEASE"
    )
    review_death_loss_as_consultant(first["id"], world.consultant_id, "CONFIRM")

    resp = api.create_death_loss(
        world.lot_id,
        {
            "death_date": "2026-08-25", "head_lost": 149, "cause": "WEATHER",
            "necropsy_performed": False,
        },
        make_grazier_headers(world.grazier_id),
    )
    validate_error(resp, ApiErrorId.ERR_HEAD_COUNT_INCONSISTENT.value, 422)

    assert read_lot(world.lot_id, world.grazier_id)["confirmed_death_head"] == 2
    assert read_pasture(world.pasture_id, world.grazier_id)["stocked_head_count"] == 148
    _, meta = validate_paginated(
        api.list_death_losses(world.lot_id, make_grazier_headers(world.grazier_id))
    )
    assert meta["total_count"] == 1, "The rejected report wrote no row"
