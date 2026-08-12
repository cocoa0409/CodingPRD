"""Lease extensions, the surviving line set and the holdover accrual."""

from test_helpers import (
    CLERK,
    COORD,
    WAREHOUSE,
    ApiErrorId,
    assert_extension,
    assert_lease,
    assert_lease_cycle_conservation,
    assert_money,
    assert_same_instant,
    lease_version,
    make_listing_agent_headers,
    set_clock,
    setup_vacant_project_staged,
    validate_error,
    validate_success,
)


def test_applying_an_unadjudicated_extension_is_an_invalid_extension_state(api):
    """PRD §2.7: "Rung 27: the extension's `state` is a legal origin for the requested
    transition; otherwise `ERR_EXTENSION_INVALID_STATE`, HTTP 409."
    PRD §3.5: "Applying an approved extension moves it to `APPLIED`, and this is the only
    extension state that ever contributes to the lease."

    Design: Corner/state_machines/extension_apply_before_adjudication_rejected_as_extension_invalid_state
    """
    ctx = setup_vacant_project_staged()
    extension = validate_success(api.request_extension(
        ctx["lease_id"], 2, lease_version(ctx["lease_id"]), COORD), 201)

    resp = api.apply_extension(extension["id"], COORD)

    validate_error(resp, ApiErrorId.ERR_EXTENSION_INVALID_STATE.value, 409)
    stored = validate_success(api.get_extension(extension["id"], COORD))
    assert_extension(stored)
    assert stored["state"] == "REQUESTED"
    assert stored["granted_cycles"] == 0
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["billed_cycles"] == 4


def test_a_zero_cycle_extension_request_is_refused_on_business_grounds(api):
    """PRD §2.7: "Rung 45: the extension's `requested_cycles` is a whole positive multiple
    of the one-cycle extension increment, so fractional requests and zero are both rejected;
    otherwise `ERR_PARTIAL_CYCLE_EXTENSION`, HTTP 422."
    PRD §2.6: "`requested_cycles` on an extension from 0 through 12 inclusive at the shape
    gate — zero survives the shape check and is rejected later, on business grounds, by the
    rung that demands whole positive cycles; and the pagination `limit` from 1 through 100
    inclusive."

    Design: Corner/validations/zero_cycle_extension_request_rejected
    """
    ctx = setup_vacant_project_staged()

    resp = api.request_extension(ctx["lease_id"], 0, lease_version(ctx["lease_id"]), COORD)

    validate_error(resp, ApiErrorId.ERR_PARTIAL_CYCLE_EXTENSION.value, 422)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["billed_cycles"] == 4
    assert lease["extension_cycles"] == 0


def test_an_extension_past_the_lifetime_cycle_cap_is_refused(api):
    """PRD §2.7: "Rung 46: the lease's `extension_cycles` plus the cycles now being granted
    does not exceed 6; otherwise `ERR_EXTENSION_LIMIT_REACHED`, HTTP 409."
    PRD §3.5: "The request must name a whole positive number of cycles — the extension
    increment is 1 cycle, so fractional requests and zero are both refused with
    `ERR_PARTIAL_CYCLE_EXTENSION` even though zero survives the shape gate — and granting it
    must not push the lease's `extension_cycles` beyond a lifetime total of 6, which is
    `ERR_EXTENSION_LIMIT_REACHED`."

    Design: Corner/validations/extension_beyond_the_total_cycle_cap_rejected
    """
    ctx = setup_vacant_project_staged()

    resp = api.request_extension(ctx["lease_id"], 7, lease_version(ctx["lease_id"]), COORD)

    validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_REACHED.value, 409)
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["extension_cycles"] == 0
    assert lease["billed_cycles"] == 4


def test_a_full_approval_prices_the_whole_deployed_line_set(api):
    """PRD §3.5: "**`APPROVED_FULL`** is taken when every deployed line on the lease's
    project is free for the extended window: `granted_cycles` becomes `requested_cycles`,
    `extended_line_count` becomes the count of deployed lines, `returned_line_count` stays
    0, and the charge prices the entire deployed line set."
    PRD §3.5: "**`extension_charge`** is the surviving rate base multiplied by
    `granted_cycles`, rounded half-up to two decimal places."
    PRD §3.5: "On both arms the lease takes the `ACTIVE → EXTENDED` transition:
    `extension_cycles` grows by `granted_cycles`, `billed_cycles` becomes `initial_cycles`
    plus `extension_cycles`, `end_date` is recomputed from the unchanged `start_date`, the
    pickup window is re-derived, and `monthly_rent` is recomputed over the **surviving**
    line set."

    Design: Corner/calculations/vendor_shortfall_charge_falls_as_the_lease_is_extended
    """
    ctx = setup_vacant_project_staged()
    extension = validate_success(api.request_extension(
        ctx["lease_id"], 2, lease_version(ctx["lease_id"]), COORD), 201)
    validate_success(api.adjudicate_extension(extension["id"], "APPROVE", WAREHOUSE))

    validate_success(api.apply_extension(extension["id"], COORD))

    stored = validate_success(api.get_extension(extension["id"], COORD))
    assert stored["state"] == "APPLIED"
    assert stored["granted_cycles"] == 2
    assert stored["returned_line_count"] == 0
    assert_money(stored["extension_charge"], 3735.00, "extension.extension_charge")
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["billed_cycles"] == 6
    assert_lease_cycle_conservation(lease, 2)
    assert_same_instant(lease["end_date"], "2026-12-07T09:00:00Z", "lease.end_date")
    order = validate_success(api.get_rental_order(ctx["ro_id"], WAREHOUSE))
    assert order["effective_term_cycles"] == 6


def test_a_partial_approval_returns_the_vendor_line_and_credits_half_its_rate(api):
    """PRD §3.5: "Stated as a per-line rule, a deployed line survives the extension exactly
    when it is an owned line, or when it is a vendor line whose rental order's
    `effective_term_cycles` is at least the lease's `billed_cycles` plus the
    `requested_cycles`; any outcome in which some but not all lines survive is a partial
    approval."
    PRD §3.5: "**`swap_credit`** applies only on a partial approval and is the sum of the
    returned lines' rounded `monthly_rate` values multiplied by 50 percent, rounded half-up
    to two decimal places — a credit for the pieces that could not be swapped in."
    PRD §3.5: "On a partial, each returned line moves `DEPLOYED → SWAPPED` and its owned
    item moves `DEPLOYED → AVAILABLE`, incrementing the extension's `returned_line_count`."

    Design: Corner/errors/partial_extension_returns_the_vendor_lines_and_credits_half_a_cycle
    """
    ctx = setup_vacant_project_staged()
    extension = validate_success(api.request_extension(
        ctx["lease_id"], 3, lease_version(ctx["lease_id"]), COORD), 201)
    validate_success(api.adjudicate_extension(extension["id"], "APPROVE", WAREHOUSE))

    validate_success(api.apply_extension(extension["id"], COORD))

    stored = validate_success(api.get_extension(extension["id"], COORD))
    assert stored["state"] == "APPLIED"
    assert stored["granted_cycles"] == 3
    assert stored["extended_line_count"] == 3
    assert stored["returned_line_count"] == 1
    assert_money(stored["extension_charge"], 2160.00, "extension.extension_charge")
    assert_money(stored["swap_credit"], 573.75, "extension.swap_credit")
    assert validate_success(
        api.get_pull_line(ctx["line_v"], WAREHOUSE))["state"] == "SWAPPED"
    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["billed_cycles"] == 7
    assert_money(lease["monthly_rent"], 720.00, "lease.monthly_rent")


def test_seven_chargeable_holdover_days_stay_inside_the_first_tier(api):
    """PRD §3.5: "`holdover_days` counts whole days elapsed past `pickup_window_end`,
    computed by taking the elapsed time from `pickup_window_end` to the logical clock,
    flooring it to whole days, subtracting the grace, and flooring the result at 0."
    PRD §3.5: "Days are numbered cumulatively from the first chargeable day: days 1 through
    7 accrue at 45.00 each, and every day from the eighth onward accrues at 75.00 each."
    PRD §3.5: "If it reached `NO_ACCESS`, or there was no failed attempt at all, the grace
    is 2 days."

    Design: Difficulty/boundary_precision_check/holdover_tier_boundary_at_day_seven_versus_day_eight
    """
    ctx = setup_vacant_project_staged()
    set_clock("2026-10-08T09:00:00Z")
    validate_success(api.mark_term_complete(ctx["lease_id"], COORD))
    set_clock("2026-10-29T09:00:00Z")

    validate_success(api.accrue_holdover(ctx["lease_id"], CLERK))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert_lease(lease)
    assert lease["state"] == "HOLDOVER"
    assert lease["holdover_days"] == 7
    assert_money(lease["holdover_charge"], 315.00, "lease.holdover_charge")


def test_the_eighth_chargeable_holdover_day_crosses_into_the_second_tier(api):
    """PRD §3.5: "Days are numbered cumulatively from the first chargeable day: days 1
    through 7 accrue at 45.00 each, and every day from the eighth onward accrues at 75.00
    each."
    PRD §3.5: "Further accruals are taken from `HOLDOVER` back to `HOLDOVER`, re-deriving
    both figures each time."
    PRD §3.5: "**The pickup window** is derived from an anchor and is a closed interval."

    Design: Difficulty/boundary_precision_check/holdover_tier_boundary_at_day_seven_versus_day_eight
    """
    ctx = setup_vacant_project_staged()
    set_clock("2026-10-08T09:00:00Z")
    validate_success(api.mark_term_complete(ctx["lease_id"], COORD))
    set_clock("2026-10-29T09:00:00Z")
    validate_success(api.accrue_holdover(ctx["lease_id"], CLERK))
    set_clock("2026-10-30T09:00:00Z")

    validate_success(api.accrue_holdover(ctx["lease_id"], CLERK))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "HOLDOVER"
    assert lease["holdover_days"] == 8
    assert_money(lease["holdover_charge"], 390.00, "lease.holdover_charge")
    assert_same_instant(lease["pickup_window_end"], "2026-10-20T09:00:00Z",
                        "lease.pickup_window_end")


def test_the_holdover_cap_resets_when_the_thirty_day_period_rolls_over(api):
    """PRD §3.5: "The cap, however, does: chargeable days are grouped into consecutive
    periods of 30 days starting at `holdover_cap_period_start`, the amount accrued within
    each period is capped at 1800.00, and the charge is the sum of those capped period
    amounts, rounded half-up to two decimal places."
    PRD §3.5: "Each time the logical clock passes the end of the current period,
    `holdover_cap_period_start` advances by 30 days and **the period cap resets** — which is
    the whole point of tracking the period start on the row."

    Design: Corner/cross_cutting_complexity_layers/holdover_period_cap_resets_at_the_period_rollover
    """
    ctx = setup_vacant_project_staged()
    set_clock("2026-10-08T09:00:00Z")
    validate_success(api.mark_term_complete(ctx["lease_id"], COORD))
    set_clock("2026-11-21T09:00:00Z")
    validate_success(api.accrue_holdover(ctx["lease_id"], CLERK))
    set_clock("2026-11-26T09:00:00Z")

    validate_success(api.accrue_holdover(ctx["lease_id"], CLERK))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "HOLDOVER"
    assert lease["holdover_days"] == 35
    assert_money(lease["holdover_charge"], 2175.00, "lease.holdover_charge")
    assert_same_instant(lease["holdover_cap_period_start"], "2026-11-19T09:00:00Z",
                        "lease.holdover_cap_period_start")


def test_an_early_destage_moves_the_pickup_window_without_touching_the_billing(api):
    """PRD §3.5: "**An early de-stage moves the window and nothing else**: `billed_cycles`
    is not reduced, and the lease charge stays exactly where it was."
    PRD §3.5: "The lease reaches `ENDING` from `ACTIVE` or `EXTENDED` in two ways — the
    listing going under contract, or a coordinator or clerk marking the term complete."

    Design: Difficulty/compensating_invariant/early_destage_then_escrow_reversal_conserves_billed_cycles
    """
    ctx = setup_vacant_project_staged()

    validate_success(api.listing_under_contract(
        ctx["listing_id"], make_listing_agent_headers(ctx["agent_id"])))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "ENDING"
    assert lease["billed_cycles"] == 4
    assert_same_instant(lease["end_date"], "2026-10-08T09:00:00Z", "lease.end_date")
    assert_lease_cycle_conservation(lease, 0)


def test_the_escrow_round_trip_leaves_billed_cycles_and_the_end_date_intact(api):
    """PRD §2.11: "A lease's `billed_cycles` always equals its `initial_cycles` plus the sum
    of `granted_cycles` over the extensions on that lease that have reached state `APPLIED`."
    PRD §2.11: "**Neither may change `billed_cycles`.** An early de-stage moves the pickup
    window forward without reducing what the customer is billed, and the reversal moves it
    back without adding anything."
    PRD §3.5: "The reverse arc, `ENDING → ACTIVE`, is taken when escrow falls through, and
    it clears the derived pickup window."

    Design: Difficulty/compensating_invariant/early_destage_then_escrow_reversal_conserves_billed_cycles
    """
    ctx = setup_vacant_project_staged()
    agent = make_listing_agent_headers(ctx["agent_id"])
    validate_success(api.listing_under_contract(ctx["listing_id"], agent))

    validate_success(api.listing_fall_out_of_escrow(ctx["listing_id"], agent))

    lease = validate_success(api.get_lease(ctx["lease_id"], COORD))
    assert lease["state"] == "ACTIVE"
    assert lease["initial_cycles"] == 4
    assert lease["extension_cycles"] == 0
    assert lease["billed_cycles"] == 4
    assert_same_instant(lease["start_date"], "2026-06-10T09:00:00Z", "lease.start_date")
    assert_same_instant(lease["end_date"], "2026-10-08T09:00:00Z", "lease.end_date")
    assert_money(lease["monthly_rent"], 1867.50, "lease.monthly_rent")
