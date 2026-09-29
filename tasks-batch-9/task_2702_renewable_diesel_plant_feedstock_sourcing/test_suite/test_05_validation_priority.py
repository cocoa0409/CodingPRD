"""Requests that break two rules at once, where only the higher rule may speak.

Each pair is proved twice: once with both conditions live so the winner surfaces,
and once with only the loser live so it is clear the loser was reachable all along.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_INVALID_RUN_STATE,
    ERR_LOT_MASS_EXCEEDED,
    ERR_PRETREATMENT_REQUIRED,
    ERR_SUPPLIER_DUE_DILIGENCE_EXPIRED,
)
from test_helpers.assertions import assert_mass, assert_timestamp_equals
from test_helpers.test_users import OPERATOR_HEADERS, TRADER_HEADERS
from test_helpers.types import (
    DD_VERIFIED,
    LOT_ACCEPTED,
    LOT_PRETREAT_REQUIRED,
    RUN_RUNNING,
    TIER_HEAVY,
)


def test_running_campaign_state_pre_empts_the_lot_mass_shortfall(api):
    """PRD §2.7: "The target resource named in the path is in a state that permits the
    requested transition — one of `ERR_INVALID_SUPPLIER_STATE`, `ERR_INVALID_LOT_STATE`,
    `ERR_INVALID_UNIT_STATE`, `ERR_INVALID_WINDOW_STATE`, `ERR_INVALID_NOMINATION_STATE`,
    `ERR_INVALID_RUN_STATE`, `ERR_INVALID_ALLOCATION_STATE`,
    `ERR_INVALID_BATCH_CERT_STATE`, `ERR_INVALID_BATCH_DISTRIBUTION_STATE`,
    `ERR_INVALID_PATHWAY_STATE`, `ERR_INVALID_CREDIT_BLOCK_STATE` or
    `ERR_INVALID_HEDGE_STATE`, all 409."
    PRD §3.5: "After the global rungs of §2.7 — role, path existence, the existence of the
    cited `lot_id`, body shape, then the `expected_run_version` concurrency check, then the
    campaign's own state — the domain conditions are evaluated in exactly this sequence"

    Design: Difficulty/priority_pair_validation_conflict/run_state_beats_lot_mass_on_allocation_to_running_run
    """
    ctx = fx.running_and_planned_runs(api)
    assert ctx["run"]["status"] == RUN_RUNNING, f"expected RUNNING, got {ctx['run']['status']}"
    assert_mass(ctx["run"]["consumed_mass_mt"], 400.000, "consumed_mass_mt")

    validate_error(
        api.create_allocation(
            ctx["run"]["id"],
            f.allocation_payload(ctx["lot2"]["id"], 200.000, ctx["run"]["version"]),
            TRADER_HEADERS,
        ),
        ERR_INVALID_RUN_STATE,
    )

    lot2 = validate_success(api.get_feedstock_lot(ctx["lot2"]["id"], TRADER_HEADERS))
    assert lot2["status"] == LOT_ACCEPTED
    assert_mass(lot2["remaining_mass_mt"], 50.000, "remaining_mass_mt")
    assert_mass(lot2["allocated_mass_mt"], 0.000, "allocated_mass_mt")


def test_planned_campaign_lets_the_losing_lot_mass_error_surface(api):
    """PRD §3.5: "The requested `mass_mt` must be no greater than the lot's
    `remaining_mass_mt`, otherwise `ERR_LOT_MASS_EXCEEDED`."
    PRD §3.5: "A newly created campaign is `PLANNED`. Its `run_days` is the whole number of
    days between `window_start` and `window_end`. Its `reserved_mass_mt` and
    `consumed_mass_mt` are 0.000"

    Design: Difficulty/priority_pair_validation_conflict/run_state_beats_lot_mass_on_allocation_to_running_run
    """
    ctx = fx.running_and_planned_runs(api)

    validate_error(
        api.create_allocation(
            ctx["run2"]["id"],
            f.allocation_payload(ctx["lot2"]["id"], 200.000, ctx["run2"]["version"]),
            TRADER_HEADERS,
        ),
        ERR_LOT_MASS_EXCEEDED,
    )

    run2 = validate_success(api.get_processing_run(ctx["run2"]["id"], OPERATOR_HEADERS))
    assert_mass(run2["reserved_mass_mt"], 0.000, "reserved_mass_mt")


def test_live_verification_reports_only_the_pretreatment_debt(api):
    """PRD §3.5: "The cited lot must not be awaiting pretreatment. A lot at
    `PRETREAT_REQUIRED` yields `ERR_PRETREATMENT_REQUIRED`, which names the tier still
    owed."
    PRD §3.1: "sets `dd_expires_at` to the current logical clock advanced by `valid_months`
    multiplied by 30 days (months are treated as exactly 30 days each, never as calendar
    months)"

    Design: Difficulty/priority_pair_validation_conflict/expired_due_diligence_beats_pretreatment_requirement
    """
    ctx = fx.pretreatment_owed_lot_and_run(api, valid_months=1)

    assert ctx["supplier"]["dd_status"] == DD_VERIFIED
    assert_timestamp_equals(
        ctx["supplier"]["dd_expires_at"], "2026-08-31T00:00:00Z", "dd_expires_at"
    )
    assert ctx["lot"]["status"] == LOT_PRETREAT_REQUIRED
    assert ctx["lot"]["pretreatment_tier"] == TIER_HEAVY

    validate_error(
        api.create_allocation(
            ctx["run"]["id"],
            f.allocation_payload(ctx["lot"]["id"], 150.000, ctx["run"]["version"]),
            TRADER_HEADERS,
        ),
        ERR_PRETREATMENT_REQUIRED,
    )


def test_lapsed_verification_takes_over_the_same_refusal(api):
    """PRD §3.5: "That supplier's `dd_expires_at` must be strictly after the current logical
    clock. A verification that has lapsed — typically because the clock was advanced past it
    — yields `ERR_SUPPLIER_DUE_DILIGENCE_EXPIRED`."
    PRD §3.5: "The cited lot must not be awaiting pretreatment. A lot at
    `PRETREAT_REQUIRED` yields `ERR_PRETREATMENT_REQUIRED`, which names the tier still
    owed."

    Design: Difficulty/priority_pair_validation_conflict/expired_due_diligence_beats_pretreatment_requirement
    """
    ctx = fx.pretreatment_owed_lot_and_run(api, valid_months=1)
    payload = f.allocation_payload(ctx["lot"]["id"], 150.000, ctx["run"]["version"])

    validate_error(
        api.create_allocation(ctx["run"]["id"], payload, TRADER_HEADERS),
        ERR_PRETREATMENT_REQUIRED,
    )

    fx.move_clock(api, "2026-09-05T00:00:00Z", headers=TRADER_HEADERS)

    validate_error(
        api.create_allocation(ctx["run"]["id"], payload, TRADER_HEADERS),
        ERR_SUPPLIER_DUE_DILIGENCE_EXPIRED,
    )

    lot = validate_success(api.get_feedstock_lot(ctx["lot"]["id"], TRADER_HEADERS))
    assert lot["status"] == LOT_PRETREAT_REQUIRED, "neither refusal moved the lot"
    assert_mass(lot["allocated_mass_mt"], 0.000, "allocated_mass_mt")

    run = validate_success(api.get_processing_run(ctx["run"]["id"], OPERATOR_HEADERS))
    assert_mass(run["reserved_mass_mt"], 0.000, "reserved_mass_mt")
