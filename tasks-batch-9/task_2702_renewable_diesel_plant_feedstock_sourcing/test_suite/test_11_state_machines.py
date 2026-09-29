"""Status machines: the hops that are allowed, the hops that are not.

Initial states, single valid transitions, the two-row side effect of taking a
unit down, terminal states that refuse a second attempt, and the guards that sit
on a transition beyond the status itself — the logical clock for a turnaround
start, the half-open window for a catalyst change.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CATALYST_CHANGE_OUTSIDE_WINDOW,
    ERR_INVALID_LOT_STATE,
    ERR_INVALID_NOMINATION_STATE,
    ERR_INVALID_PATHWAY_STATE,
    ERR_INVALID_WINDOW_STATE,
)
from test_helpers.assertions import (
    assert_activity_index,
    assert_fields_null,
    assert_mass,
    assert_money,
    assert_one_decimal,
    assert_timestamp_equals,
)
from test_helpers.test_users import (
    ANALYST_HEADERS,
    OFFICER_A_HEADERS,
    OFFICER_A_USER_ID,
    OPERATOR_HEADERS,
    TRADER_HEADERS,
    VERIFIER_HEADERS,
)
from test_helpers.types import (
    CHARGE_ACTIVE,
    DISPOSITION_REJECT,
    FEEDSTOCK_TALLOW,
    FEEDSTOCK_UCO,
    HEDGE_UNWOUND,
    INSTRUMENT_RIN_FORWARD,
    LOT_ACCEPTED,
    LOT_REJECTED,
    NOMINATION_CANCELLED,
    PATHWAY_DENIED,
    PATHWAY_DRAFT,
    PROGRAM_LCFS,
    REVIEW_DENY,
    TIER_HEAVY,
    TIER_NONE,
    TIER_T1,
    UNIT_DOWN_TURNAROUND,
    UNIT_IDLE,
    WINDOW_APPROVED,
    WINDOW_COMPLETED,
    WINDOW_IN_PROGRESS,
)


def test_a_clean_test_lets_the_lot_walk_from_tested_to_accepted(api):
    """PRD §3.2: "Acceptance is the gate to the reactor. A `QualityAnalyst` accepts a lot whose
    status is exactly `TESTED` **and** whose `pretreatment_tier` is `NONE`, moving it `TESTED →
    ACCEPTED` and bumping its `version`."
    PRD §3.2: "A `PASS` moves the lot to `TESTED`, sets `pretreatment_tier` to `NONE` and
    `pretreatment_fee_usd` to 0.00."

    Design: Corner/state_machines/lot_acceptance_transitions_tested_to_accepted
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.make_lot(api, supplier["id"], mass_mt=500.000)
    fx.add_quality_test(api, lot["id"], lot["version"])

    accepted = validate_success(api.accept_lot(lot["id"], ANALYST_HEADERS))

    assert accepted["status"] == LOT_ACCEPTED, f"got {accepted['status']}"
    assert accepted["pretreatment_tier"] == TIER_NONE
    assert_money(accepted["pretreatment_fee_usd"], 0.00, "pretreatment_fee_usd")
    assert_mass(accepted["remaining_mass_mt"], 500.000, "remaining_mass_mt")
    assert accepted["version"] == 3, (
        f"creation, the test append and the acceptance are three writes, got {accepted['version']}"
    )


def test_installing_the_charge_at_the_windows_exclusive_end_is_outside_it(api):
    """PRD §3.3: "The `installed_at` instant must fall inside a turnaround window on that unit
    whose `scope` is `CATALYST_CHANGE` and whose status is `APPROVED` or `IN_PROGRESS`, using
    the half-open interval convention — an `installed_at` exactly at such a window's `end_at`
    is outside it."
    PRD §3.3: "A new charge starts with status `ACTIVE`, `cumulative_throughput_mt` of 0.000 and
    `activity_index` of 1.0000, becomes the unit's `active_catalyst_charge_id`, clears the
    unit's `requires_turnaround` to `false`, and bumps the unit's `version`."

    Design: Corner/state_machines/catalyst_charge_install_outside_approved_window_is_rejected
    """
    unit = fx.make_unit(api)
    fx.make_approved_window(api, unit["id"])

    validate_error(
        api.create_catalyst_charge(
            unit["id"],
            f.catalyst_charge_payload(installed_at="2026-08-03T00:00:00Z"),
            OPERATOR_HEADERS,
        ),
        ERR_CATALYST_CHANGE_OUTSIDE_WINDOW,
    )

    barren = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert_fields_null(barren, "active_catalyst_charge_id")
    assert barren["version"] == 1, f"the refusal wrote nothing, got version {barren['version']}"

    charge = validate_success(
        api.create_catalyst_charge(
            unit["id"],
            f.catalyst_charge_payload(installed_at="2026-08-02T00:00:00Z"),
            OPERATOR_HEADERS,
        ),
        201,
    )
    assert charge["status"] == CHARGE_ACTIVE, f"got {charge['status']}"
    assert_mass(charge["cumulative_throughput_mt"], 0.000, "cumulative_throughput_mt")
    assert_activity_index(charge["activity_index"], 1.0000)

    loaded = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert loaded["active_catalyst_charge_id"] == charge["id"]
    assert loaded["requires_turnaround"] is False
    assert loaded["version"] == 2, f"got {loaded['version']}"


def test_starting_the_approved_window_takes_the_unit_down_and_back_up(api):
    """PRD §3.3: "Starting an `APPROVED` window requires that the current logical clock be at or
    after the window's `start_at` and strictly before its `end_at`, and that the unit be
    `IDLE`; the window moves `APPROVED → IN_PROGRESS` while the unit moves `IDLE →
    DOWN_TURNAROUND`, and both versions are bumped."
    PRD §3.3: "Completing an `IN_PROGRESS` window moves it `IN_PROGRESS → COMPLETED` and returns
    the unit `DOWN_TURNAROUND → IDLE`, bumping both versions"

    Design: Corner/state_machines/turnaround_window_start_sets_unit_down_turnaround
    """
    unit = fx.make_unit(api)
    window = fx.make_approved_window(api, unit["id"])
    assert window["status"] == WINDOW_APPROVED, f"got {window['status']}"

    started = validate_success(api.start_window(window["id"], OPERATOR_HEADERS))
    assert started["status"] == WINDOW_IN_PROGRESS, f"got {started['status']}"

    down = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert down["status"] == UNIT_DOWN_TURNAROUND, f"got {down['status']}"
    assert down["version"] == 2, f"got {down['version']}"

    finished = validate_success(api.complete_window(window["id"], OPERATOR_HEADERS))
    assert finished["status"] == WINDOW_COMPLETED, f"got {finished['status']}"

    back_up = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert back_up["status"] == UNIT_IDLE, f"got {back_up['status']}"
    assert back_up["version"] == 3, f"got {back_up['version']}"


def test_an_approved_window_a_month_away_cannot_be_started_yet(api):
    """PRD §3.3: "Starting an `APPROVED` window requires that the current logical clock be at or
    after the window's `start_at` and strictly before its `end_at`, and that the unit be
    `IDLE`; the window moves `APPROVED → IN_PROGRESS` while the unit moves `IDLE →
    DOWN_TURNAROUND`, and both versions are bumped."
    PRD §2.7: "The target resource named in the path is in a state that permits the requested
    transition"

    Design: Corner/state_machines/turnaround_window_start_before_its_window_opens_is_rejected
    """
    unit = fx.make_unit(api)
    window = fx.make_approved_window(
        api, unit["id"], start_at="2026-09-10T00:00:00Z", end_at="2026-09-12T00:00:00Z"
    )
    assert_timestamp_equals(window["start_at"], "2026-09-10T00:00:00Z", "start_at")

    validate_error(
        api.start_window(window["id"], OPERATOR_HEADERS), ERR_INVALID_WINDOW_STATE
    )

    windows = get_success_data(api.list_turnaround_windows(unit["id"], OPERATOR_HEADERS))
    assert len(windows) == 1, f"got {len(windows)}"
    assert windows[0]["status"] == WINDOW_APPROVED, f"got {windows[0]['status']}"

    untouched = validate_success(api.get_unit(unit["id"], OPERATOR_HEADERS))
    assert untouched["status"] == UNIT_IDLE, f"got {untouched['status']}"
    assert untouched["version"] == 1, f"got {untouched['version']}"


def test_a_rejected_lot_is_terminal_and_can_never_be_accepted(api):
    """PRD §3.2: "A `REJECT` moves the lot to `REJECTED`, sets `pretreatment_tier` to `HEAVY`,
    sets `pretreatment_fee_usd` to 0.00, and zeroes `remaining_mass_mt`; `REJECTED` is terminal
    and such a lot can never be allocated, pretreated or accepted."
    PRD §3.2: "Accepting a lot in any other status — a `RECEIVED` lot that has never been
    tested, for instance — is refused with `ERR_INVALID_LOT_STATE`."

    Design: Corner/state_machines/rejected_lot_cannot_be_accepted
    """
    supplier = fx.make_supplier(api, feedstock_types=[FEEDSTOCK_TALLOW])
    lot = fx.make_lot(
        api,
        supplier["id"],
        feedstock_type=FEEDSTOCK_TALLOW,
        mass_mt=300.000,
        attested_ci_gco2e_per_mj=28.00,
        purchase_price_usd_per_mt=850.00,
    )
    test_row = fx.add_quality_test(
        api, lot["id"], lot["version"], ffa_pct=20.00, moisture_pct=0.30, insolubles_ppm=200
    )
    assert test_row["disposition"] == DISPOSITION_REJECT, f"got {test_row['disposition']}"
    assert test_row["tier"] == TIER_HEAVY, f"got {test_row['tier']}"

    condemned = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert condemned["status"] == LOT_REJECTED, f"got {condemned['status']}"
    assert condemned["pretreatment_tier"] == TIER_HEAVY
    assert_money(condemned["pretreatment_fee_usd"], 0.00, "pretreatment_fee_usd")
    assert_mass(condemned["remaining_mass_mt"], 0.000, "remaining_mass_mt")

    validate_error(api.accept_lot(lot["id"], ANALYST_HEADERS), ERR_INVALID_LOT_STATE)

    still = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert still["status"] == LOT_REJECTED, f"got {still['status']}"


def test_a_freshly_registered_pathway_is_a_draft_with_nothing_approved(api):
    """PRD §3.8: "The new registration starts at `DRAFT` with `revision_round` 0,
    `variance_strikes` 0, `credits_outstanding_mtco2e` 0.000, and `certified_ci_gco2e_per_mj`
    and `info_request` both null."
    PRD §3.8: "Critically, the acting officer's `X-User-ID` is captured as
    `registered_by_user_id`; that stored value is the anchor of the segregation-of-duties rule
    below."

    Design: Corner/state_machines/pathway_registration_starts_in_draft_with_zero_revision_rounds
    """
    unit = fx.make_unit(api)

    pathway = validate_success(
        api.create_pathway(
            f.pathway_payload(unit["id"], feedstock_type=FEEDSTOCK_UCO), OFFICER_A_HEADERS
        ),
        201,
    )

    assert pathway["status"] == PATHWAY_DRAFT, f"got {pathway['status']}"
    assert pathway["program"] == PROGRAM_LCFS
    assert pathway["revision_round"] == 0, f"got {pathway['revision_round']}"
    assert pathway["variance_strikes"] == 0, f"got {pathway['variance_strikes']}"
    assert_mass(pathway["credits_outstanding_mtco2e"], 0.000, "credits_outstanding_mtco2e")
    assert_fields_null(pathway, "certified_ci_gco2e_per_mj", "info_request")
    assert pathway["registered_by_user_id"] == OFFICER_A_USER_ID, (
        f"got {pathway['registered_by_user_id']}"
    )
    assert pathway["version"] == 1, f"got {pathway['version']}"


def test_a_denied_pathway_is_closed_to_any_further_submission(api):
    """PRD §3.8: "A `DENY` decision moves it `UNDER_REVIEW → DENIED`, which is terminal."
    PRD §3.8: "Submitting a `DENIED` registration is refused with `ERR_INVALID_PATHWAY_STATE`."

    Design: Corner/state_machines/denied_pathway_cannot_be_resubmitted
    """
    ground = fx.registrable_unit(api, feedstock_type=FEEDSTOCK_UCO)
    pathway = fx.make_pathway(api, ground["unit"]["id"])

    validate_success(api.submit_pathway(pathway["id"], OFFICER_A_HEADERS))
    validate_success(api.start_pathway_review(pathway["id"], VERIFIER_HEADERS))
    denied = validate_success(
        api.decide_pathway_review(
            pathway["id"], f.review_decision_payload(REVIEW_DENY), VERIFIER_HEADERS
        )
    )
    assert denied["status"] == PATHWAY_DENIED, f"got {denied['status']}"

    validate_error(
        api.submit_pathway(pathway["id"], OFFICER_A_HEADERS), ERR_INVALID_PATHWAY_STATE
    )

    final = validate_success(api.get_pathway(pathway["id"], OFFICER_A_HEADERS))
    assert final["status"] == PATHWAY_DENIED, f"got {final['status']}"
    assert final["revision_round"] == 0, (
        f"a denial is not a return-for-info lap, got {final['revision_round']}"
    )
    assert_fields_null(final, "certified_ci_gco2e_per_mj")


def test_cancelling_the_same_nomination_twice_is_refused_not_ignored(api):
    """PRD §3.4: "A `PlantOperator` cancels a nomination whose status is `CONFIRMED` and whose
    supplied campaign is still `PLANNED` or `HYDROGEN_SECURED`; the nomination moves `CONFIRMED
    → CANCELLED`, the parent contract's `peak_committed_kg_per_day` is recomputed over the
    surviving `CONFIRMED` nominations, and both the nomination's and the contract's `version`
    are bumped."
    PRD §3.4: "Cancelling the same nomination twice is refused with
    `ERR_INVALID_NOMINATION_STATE`."

    Design: Corner/state_machines/duplicate_nomination_cancellation_returns_invalid_state
    """
    plant = fx.commissioned_unit(api)
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=10.00
    )
    contract = fx.make_contract(api)
    nomination = fx.make_nomination(api, contract["id"], run["id"], kg_per_day=2600.0)

    cancelled = validate_success(api.cancel_nomination(nomination["id"], OPERATOR_HEADERS))
    assert cancelled["status"] == NOMINATION_CANCELLED, f"got {cancelled['status']}"

    emptied = validate_success(api.get_hydrogen_contract(contract["id"], TRADER_HEADERS))
    assert_one_decimal(emptied["peak_committed_kg_per_day"], 0.0, "peak_committed_kg_per_day")

    validate_error(
        api.cancel_nomination(nomination["id"], OPERATOR_HEADERS), ERR_INVALID_NOMINATION_STATE
    )

    unchanged = validate_success(api.get_hydrogen_contract(contract["id"], TRADER_HEADERS))
    assert_one_decimal(
        unchanged["peak_committed_kg_per_day"], 0.0, "peak_committed_kg_per_day"
    )

    rows = get_success_data(api.list_run_nominations(run["id"], OPERATOR_HEADERS))
    assert len(rows) == 1, f"got {len(rows)}"
    assert rows[0]["status"] == NOMINATION_CANCELLED
    assert rows[0]["version"] == cancelled["version"], (
        f"the refused call must not bump the nomination, got {rows[0]['version']}"
    )


def test_unwinding_the_open_position_stamps_the_pnl_and_returns_the_margin(api):
    """PRD §3.9: "The position moves `OPEN → UNWOUND`, stores the settlement price, and stamps
    `realized_pnl_usd` as the settlement price less the `strike_price_usd`, multiplied by
    `notional_units`, rounded half up to 2 decimal places — a figure that is negative when the
    market moved against the position."
    PRD §3.9: "Margin is returned on unwind: `base_margin_usd`, `volatility_adder_usd` and
    `total_margin_usd` are all reset to 0.00 and `volatility_tier` returns to `T1`."

    Design: Corner/state_machines/hedge_position_linear_open_to_unwound_returns_margin
    """
    position = fx.make_hedge(
        api,
        instrument=INSTRUMENT_RIN_FORWARD,
        notional_units=10000,
        strike_price_usd=2.50,
        maturity_at="2026-12-31T00:00:00Z",
    )

    unwound = validate_success(
        api.unwind_hedge_position(position["id"], f.unwind_payload(3.00), TRADER_HEADERS)
    )

    assert unwound["status"] == HEDGE_UNWOUND, f"got {unwound['status']}"
    assert_money(unwound["settlement_price_usd"], 3.00, "settlement_price_usd")
    assert_money(unwound["realized_pnl_usd"], 5000.00, "realized_pnl_usd")
    assert_money(unwound["base_margin_usd"], 0.00, "base_margin_usd")
    assert_money(unwound["volatility_adder_usd"], 0.00, "volatility_adder_usd")
    assert_money(unwound["total_margin_usd"], 0.00, "total_margin_usd")
    assert unwound["volatility_tier"] == TIER_T1, f"got {unwound['volatility_tier']}"
    assert_money(unwound["gross_notional_usd"], 25000.00, "gross_notional_usd")
