"""Cross-entity gates on a lot, the specimen-pool boundary, and the tear-down
cascade a mandatory failure fires."""

import pytest

from test_helpers import (
    SALT_SPRAY_WINDOW,
    TEST_USERS,
    ApiErrorId,
    advance_lot,
    advance_payload,
    api_client,
    assert_specimen_ledger,
    complete_campaign,
    create_chamber,
    create_furnace,
    create_lot,
    create_sku,
    read_campaign,
    read_lot,
    read_test_run,
    schedule_campaign,
    schedule_test_run,
    setup_lot_with_completed_campaign,
    submit_results,
    make_test_run_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

PP = TEST_USERS["production_planner_headers"]
QE = TEST_USERS["quality_engineer_headers"]

CAMPAIGN_ONE = ("2026-08-02T06:00:00Z", "2026-08-02T10:00:00Z")
CAMPAIGN_TWO = ("2026-08-05T06:00:00Z", "2026-08-05T10:00:00Z")
TEARDOWN_DIMENSIONAL_WINDOW = ("2026-08-03T12:00:00Z", "2026-08-03T13:00:00Z")
TEARDOWN_TORQUE_WINDOW = ("2026-08-03T14:00:00Z", "2026-08-03T15:00:00Z")
BOUNDARY_HARDNESS_WINDOW = ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
BOUNDARY_DIMENSIONAL_WINDOW = ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z")


# ---------------------------------------------------------------------------
# The heat-treat gate on the step into HEAT_TREATED
# ---------------------------------------------------------------------------


def _lot_with_scheduled_campaign():
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"], specimen_pool_total=20)
    campaign = schedule_campaign(
        lot["id"],
        furnace["id"],
        window_start=CAMPAIGN_ONE[0],
        window_end=CAMPAIGN_ONE[1],
        charge_kg=800,
    )
    return {"sku": sku, "furnace": furnace, "lot": lot, "campaign": campaign}


def test_advance_into_heat_treated_is_refused_while_the_campaign_is_only_scheduled():
    """The lot has a campaign booked on a qualified furnace, but nobody has
    recorded the soak yet, so the routing dimension cannot move.

    PRD §3.2: "A campaign that is still `SCHEDULED`, or one that was `RELEASED`
    by a rejection cascade, does not satisfy the gate, and the refusal is
    `ERR_HEAT_TREAT_NOT_COMPLETED`."

    Design: Difficulty/cross_entity_state_dependency/lot_advance_requires_completed_furnace_campaign
    """
    ctx = _lot_with_scheduled_campaign()
    assert ctx["campaign"]["status"] == "SCHEDULED"

    validate_error(
        api_client.advance_production_lot(
            ctx["lot"]["id"], advance_payload("HEAT_TREATED"), PP
        ),
        ApiErrorId.ERR_HEAT_TREAT_NOT_COMPLETED,
        409,
    )

    refused = read_lot(ctx["lot"]["id"])
    assert refused["process_status"] == "FORGED"
    assert refused["cert_status"] == "DRAFT"
    assert refused["disposition"] == "IN_PROCESS"


def test_completing_the_campaign_unlocks_the_identical_advance_request():
    """Recording a 120 minute soak satisfies the gate, and the same advance that
    was refused a moment ago now succeeds.

    PRD §3.2: "The step into `HEAT_TREATED` carries one extra gate, evaluated
    after the quarantine check: at least one heat-treat campaign on this lot must
    have reached `COMPLETED` status."

    Design: Difficulty/cross_entity_state_dependency/lot_advance_requires_completed_furnace_campaign
    """
    ctx = _lot_with_scheduled_campaign()
    validate_error(
        api_client.advance_production_lot(
            ctx["lot"]["id"], advance_payload("HEAT_TREATED"), PP
        ),
        ApiErrorId.ERR_HEAT_TREAT_NOT_COMPLETED,
        409,
    )

    completed = complete_campaign(ctx["campaign"]["id"], soak_minutes=120)
    assert completed["status"] == "COMPLETED"
    assert completed["soak_minutes"] == 120

    advanced = validate_success(
        api_client.advance_production_lot(
            ctx["lot"]["id"], advance_payload("HEAT_TREATED"), PP
        )
    )

    assert advanced["process_status"] == "HEAT_TREATED"
    assert advanced["cert_status"] == "DRAFT"
    assert advanced["disposition"] == "IN_PROCESS"


# ---------------------------------------------------------------------------
# The specimen-pool boundary
# ---------------------------------------------------------------------------


def _lot_on_the_pool_boundary():
    """A twelve-specimen lot at PLATED with five specimens already committed, so
    exactly seven remain available."""
    ctx = setup_lot_with_completed_campaign(lot_overrides={"specimen_pool_total": 12})
    lot_id = ctx["lot"]["id"]
    for stage in ("HEAT_TREATED", "MACHINED", "PLATED"):
        advance_lot(lot_id, stage)
    ctx["chamber"] = create_chamber(coupon_capacity=24)
    ctx["hardness_run"] = schedule_test_run(lot_id, "HARDNESS", 5, BOUNDARY_HARDNESS_WINDOW)
    ctx["lot"] = read_lot(lot_id)
    return ctx


def test_a_run_may_commit_exactly_the_specimens_that_remain_available():
    """Seven specimens are available and a seven-specimen run is accepted,
    driving the available count to zero.

    PRD §3.3: "First the specimen pool: `specimen_count` may not exceed the
    lot's current `specimens_available`, and exact equality is accepted and
    drives `specimens_available` to zero."

    Design: Difficulty/boundary_precision_check/test_run_specimen_count_equals_available_pool_boundary
    """
    ctx = _lot_on_the_pool_boundary()
    assert ctx["lot"]["specimens_available"] == 7

    run = validate_success(
        api_client.create_test_run(
            make_test_run_payload(
                ctx["lot"]["id"],
                test_type="DIMENSIONAL",
                specimen_count=7,
                window_start=BOUNDARY_DIMENSIONAL_WINDOW[0],
                window_end=BOUNDARY_DIMENSIONAL_WINDOW[1],
            ),
            QE,
        ),
        201,
    )

    assert run["specimen_count"] == 7
    assert run["status"] == "SCHEDULED"

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimens_available"] == 0
    assert lot["specimens_committed"] == 12
    assert lot["specimens_consumed"] == 0
    assert_specimen_ledger(lot)


def test_one_specimen_more_than_the_pool_holds_is_refused():
    """With the pool driven to zero, even a single-specimen corrosion run has
    nothing left to draw on.

    PRD §3.3: "Asking for more is `ERR_SPECIMENS_EXHAUSTED`."

    Design: Difficulty/boundary_precision_check/test_run_specimen_count_equals_available_pool_boundary
    """
    ctx = _lot_on_the_pool_boundary()
    schedule_test_run(ctx["lot"]["id"], "DIMENSIONAL", 7, BOUNDARY_DIMENSIONAL_WINDOW)
    assert read_lot(ctx["lot"]["id"])["specimens_available"] == 0

    validate_error(
        api_client.create_test_run(
            make_test_run_payload(
                ctx["lot"]["id"],
                test_type="SALT_SPRAY",
                specimen_count=1,
                window_start=SALT_SPRAY_WINDOW[0],
                window_end=SALT_SPRAY_WINDOW[1],
                chamber_id=ctx["chamber"]["id"],
            ),
            QE,
        ),
        ApiErrorId.ERR_SPECIMENS_EXHAUSTED,
        409,
    )


def test_the_refused_run_commits_nothing_and_is_never_persisted():
    """A refusal must leave both the run collection and the specimen ledger
    exactly as they were.

    PRD §3.3: "A successfully scheduled run is created with `status`
    `SCHEDULED`, and its `specimen_count` moves from the lot's
    `specimens_available` into `specimens_committed`, which increments the lot's
    `version` as well as creating the run."

    Design: Difficulty/boundary_precision_check/test_run_specimen_count_equals_available_pool_boundary
    """
    ctx = _lot_on_the_pool_boundary()
    lot_id = ctx["lot"]["id"]
    schedule_test_run(lot_id, "DIMENSIONAL", 7, BOUNDARY_DIMENSIONAL_WINDOW)

    validate_error(
        api_client.create_test_run(
            make_test_run_payload(
                lot_id,
                test_type="SALT_SPRAY",
                specimen_count=1,
                window_start=SALT_SPRAY_WINDOW[0],
                window_end=SALT_SPRAY_WINDOW[1],
                chamber_id=ctx["chamber"]["id"],
            ),
            QE,
        ),
        ApiErrorId.ERR_SPECIMENS_EXHAUSTED,
    )

    runs, meta = validate_paginated(api_client.list_lot_test_runs(lot_id, QE))
    assert meta["total_count"] == 2
    assert {run["test_type"] for run in runs} == {"HARDNESS", "DIMENSIONAL"}

    lot = read_lot(lot_id)
    assert lot["specimens_committed"] == 12
    assert lot["specimens_available"] == 0
    assert_specimen_ledger(lot)


# ---------------------------------------------------------------------------
# The mandatory-failure tear-down cascade
# ---------------------------------------------------------------------------


def _lot_with_an_open_schedule():
    """An ASSEMBLED lot carrying one COMPLETED campaign, one SCHEDULED campaign,
    one SCHEDULED dimensional run and one SCHEDULED proof-torque run."""
    sku = create_sku()
    furnace = create_furnace()
    lot = create_lot(sku["id"], specimen_pool_total=40)
    lot_id = lot["id"]

    first = schedule_campaign(
        lot_id,
        furnace["id"],
        window_start=CAMPAIGN_ONE[0],
        window_end=CAMPAIGN_ONE[1],
        charge_kg=800,
    )
    first = complete_campaign(first["id"], soak_minutes=120)
    for stage in ("HEAT_TREATED", "MACHINED", "PLATED", "ASSEMBLED"):
        advance_lot(lot_id, stage)
    second = schedule_campaign(
        lot_id,
        furnace["id"],
        window_start=CAMPAIGN_TWO[0],
        window_end=CAMPAIGN_TWO[1],
        charge_kg=800,
    )

    dimensional = schedule_test_run(lot_id, "DIMENSIONAL", 3, TEARDOWN_DIMENSIONAL_WINDOW)
    torque = schedule_test_run(lot_id, "PROOF_TORQUE", 2, TEARDOWN_TORQUE_WINDOW)
    return {
        "sku": sku,
        "furnace": furnace,
        "lot": read_lot(lot_id),
        "first_campaign": first,
        "second_campaign": second,
        "dimensional_run": dimensional,
        "torque_run": torque,
    }


def test_a_failing_proof_torque_run_is_judged_on_its_weakest_specimen():
    """Readings of 100.0 and 110.0 Nm against a 115.8 Nm bar are governed by the
    100.0 figure, giving 13.64 percent of negative headroom.

    PRD §3.4: "For `PROOF_TORQUE` the governing statistic is the **smallest**
    reading, because the weakest specimen defines the product, and the
    requirement is the lot's pinned `proof_torque_required_nm`, again
    pass-when-at-least."

    Design: Difficulty/transitive_cascade/mandatory_test_failure_cascades_to_campaign_release
    """
    ctx = _lot_with_an_open_schedule()

    resolved = submit_results(ctx["torque_run"]["id"], [100.0, 110.0])

    assert resolved["status"] == "FAILED"
    assert resolved["mandatory"] is True
    assert resolved["governing_statistic"] == pytest.approx(100.0, abs=0.01)
    assert resolved["requirement_value"] == pytest.approx(115.8, abs=0.01)
    assert resolved["result_margin_pct"] == pytest.approx(-13.64, abs=0.01)


def test_the_mandatory_failure_rejects_and_quarantines_without_rewinding_the_routing():
    """The dossier and the material dimension both move, while the metal stays
    where it physically is.

    PRD §3.4: "Link two sets the lot's `disposition` to `QUARANTINED`, which
    immediately closes the lot to further test scheduling, campaign booking,
    advancement, certification and release."

    Design: Difficulty/transitive_cascade/mandatory_test_failure_cascades_to_campaign_release
    """
    ctx = _lot_with_an_open_schedule()
    submit_results(ctx["torque_run"]["id"], [100.0, 110.0])

    lot = read_lot(ctx["lot"]["id"])
    assert lot["cert_status"] == "REJECTED"
    assert lot["disposition"] == "QUARANTINED"
    assert lot["process_status"] == "ASSEMBLED"


def test_the_tear_down_releases_the_scheduled_campaign_and_voids_the_sibling_run():
    """One request tears down the lot's open schedule: the booked furnace window
    is freed, the untouched sibling run is voided with the literal cascade
    reason, and the specimen identity still closes.

    PRD §3.4: "Link three tears down the lot's open schedule in two parts, each
    processing its rows in `created_at` ascending order: every heat-treat
    campaign on the lot still in `SCHEDULED` status becomes `RELEASED`, freeing
    that furnace's buffered window for other work, and every **other** test run
    on the lot still in `SCHEDULED` status becomes `VOID` with `void_reason` set
    to the literal string `CASCADE_LOT_REJECTED`, returning each run's specimens
    from `specimens_committed` to `specimens_available`."

    Design: Difficulty/transitive_cascade/mandatory_test_failure_cascades_to_campaign_release
    """
    ctx = _lot_with_an_open_schedule()
    submit_results(ctx["torque_run"]["id"], [100.0, 110.0])

    assert read_campaign(ctx["second_campaign"]["id"])["status"] == "RELEASED"
    assert read_campaign(ctx["first_campaign"]["id"])["status"] == "COMPLETED"

    voided = read_test_run(ctx["dimensional_run"]["id"])
    assert voided["status"] == "VOID"
    assert voided["void_reason"] == "CASCADE_LOT_REJECTED"

    lot = read_lot(ctx["lot"]["id"])
    assert lot["specimen_pool_total"] == 40
    assert lot["specimens_available"] == 38
    assert lot["specimens_committed"] == 0
    assert lot["specimens_consumed"] == 2
    assert_specimen_ledger(lot)
