"""Rep assignment, touchpoint cadence and the account relationship cycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_ticket_account,
    cancel_order,
    create_account,
    create_confirmed_order,
    create_rep,
    log_touchpoint,
    read_account,
    read_rep,
    run_ops,
    set_clock,
    setup_four_seat_zone_c_world,
    setup_selling_world,
    validate_error,
    validate_success,
    OPS_HEADERS,
)


def test_rep_selector_ranks_by_load_then_prefers_the_larger_book():
    """PRD 3.2: "The eligible candidate pool is every rep whose `rep_status` is `ACTIVE`, whose `territory_code` equals the account's `territory_code`, and whose `assigned_account_count` is strictly less than their `book_capacity`. Candidates are ranked by load ratio ascending, where the load ratio is the rep's `assigned_account_count` divided by their `book_capacity`, rounded to four decimal places before any comparison is made. The first tie-break prefers the larger `book_capacity`; the second tie-break prefers the earlier `created_at`."
    PRD 3.2: "On success the account's `assigned_rep_id` is written, the chosen rep's `assigned_account_count` increases by 1, and the account's `version` increments by 1."

    Design: Corner/calculations/calc_rep_selector_picks_lowest_load_then_largest_book
    """
    small = create_rep(rep_name="R Small", territory_code="NORTH", book_capacity=2)
    big = create_rep(rep_name="R Big", territory_code="NORTH", book_capacity=4)
    south = create_rep(rep_name="R South", territory_code="SOUTH", book_capacity=3)
    a1 = create_account(account_name="A1", territory_code="NORTH")
    a2 = create_account(account_name="A2", territory_code="NORTH")
    a3 = create_account(account_name="A3", territory_code="NORTH")

    first = validate_success(api_client.assign_rep(a1["id"], OPS_HEADERS), 200)
    second = validate_success(api_client.assign_rep(a2["id"], OPS_HEADERS), 200)
    third = validate_success(api_client.assign_rep(a3["id"], OPS_HEADERS), 200)

    assert_ticket_account(first)
    assert first["assigned_rep_id"] == big["id"], "0.0000 tie is broken by the larger book"
    assert second["assigned_rep_id"] == small["id"], "0.0000 beats 0.2500"
    assert third["assigned_rep_id"] == big["id"], "0.2500 beats 0.5000"
    assert read_rep(big["id"])["assigned_account_count"] == 2
    assert read_rep(small["id"])["assigned_account_count"] == 1
    assert read_rep(south["id"])["assigned_account_count"] == 0


def test_rep_assignment_with_no_eligible_candidate_is_rejected():
    """PRD 3.2: "The eligible candidate pool is every rep whose `rep_status` is `ACTIVE`, whose `territory_code` equals the account's `territory_code`, and whose `assigned_account_count` is strictly less than their `book_capacity`."
    PRD 3.2: "If the candidate pool is empty, the request is refused with `ERR_NO_ELIGIBLE_REP` and no rep is assigned."

    Design: Corner/calculations/calc_rep_selector_with_empty_candidate_pool_returns_no_eligible_rep
    """
    north = create_rep(rep_name="R North", territory_code="NORTH", book_capacity=4)
    west = create_rep(
        rep_name="R West", territory_code="WEST", book_capacity=4, rep_status="ON_LEAVE"
    )
    account = create_account(account_name="A West", territory_code="WEST")

    response = api_client.assign_rep(account["id"], OPS_HEADERS)

    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_REP.value, 422)
    assert read_account(account["id"])["assigned_rep_id"] is None
    assert read_rep(west["id"])["assigned_account_count"] == 0
    assert read_rep(north["id"])["assigned_account_count"] == 0


def test_reassigning_an_account_that_already_has_a_rep_is_rejected():
    """PRD 3.2: "An account that already has an `assigned_rep_id` cannot be re-assigned; that attempt is `ERR_ACCOUNT_STATE_INVALID`."
    PRD 2.9: "Rep assignment requires the account's `assigned_rep_id` to still be null, and a win-back touchpoint requires the account's `service_status` to be `CHURNED`; violations are `ERR_ACCOUNT_STATE_INVALID`."

    Design: Corner/errors/err_assign_rep_on_an_already_assigned_account_returns_account_state_invalid
    """
    rep = create_rep()
    account = create_account()
    first = validate_success(api_client.assign_rep(account["id"], OPS_HEADERS), 200)
    assert first["assigned_rep_id"] == rep["id"]

    response = api_client.assign_rep(account["id"], OPS_HEADERS)

    validate_error(response, ApiErrorId.ERR_ACCOUNT_STATE_INVALID.value, 409)
    assert read_account(account["id"])["assigned_rep_id"] == rep["id"]
    assert read_rep(rep["id"])["assigned_account_count"] == 1


def test_churned_account_is_won_back_by_a_win_back_touchpoint():
    """PRD 3.2: "An account already sitting in `AT_RISK` becomes `CHURNED` when the season has left the renewal window — that is, when `season_status` is `GENERAL_ONSALE`, `IN_SEASON` or `ARCHIVED` — it still holds zero confirmed orders in this season, and a full thirty days have elapsed since its `at_risk_since_utc`."
    PRD 3.2: "An outcome of `WIN_BACK_ACCEPTED` on an account whose `service_status` is `CHURNED` moves it to `WON_BACK`, sets `last_touchpoint_at_utc` to the current instant and clears `at_risk_since_utc`; this path additionally requires the account's `billing_status` not to be `WRITTEN_OFF`, and a win-back outcome aimed at an account that is not `CHURNED` is `ERR_ACCOUNT_STATE_INVALID`."
    PRD 3.2: "Every touchpoint sets the account's `last_touchpoint_at_utc` to the current instant, increments the acting rep's `touchpoints_logged_count` by 1, recomputes the account's `churn_risk_rolling`, and bumps the account's `version` by 1."

    Design: Corner/state_machines/sm_churned_account_returns_through_win_back_touchpoint
    """
    world = setup_selling_world()

    set_clock("2026-08-20T00:00:00Z")
    run_ops(world["season_id"])
    at_risk = read_account(world["account_id"])
    assert at_risk["service_status"] == "AT_RISK"
    assert at_risk["at_risk_since_utc"] == "2026-08-20T00:00:00.000Z"

    set_clock("2026-09-20T00:00:00Z")
    run_ops(world["season_id"])
    churned = read_account(world["account_id"])
    assert churned["service_status"] == "CHURNED"

    won_back = log_touchpoint(
        world["account_id"],
        world["rep_headers"],
        touchpoint_type="EMAIL",
        outcome="WIN_BACK_ACCEPTED",
        note="campaign reply",
    )

    assert won_back["service_status"] == "WON_BACK"
    assert won_back["last_touchpoint_at_utc"] == "2026-09-20T00:00:00.000Z"
    assert read_rep(world["rep_id"])["touchpoints_logged_count"] == 1


def test_ops_checkpoint_moves_a_silent_active_account_to_at_risk():
    """PRD 3.2: "While a season is in `RENEWAL_OPEN`, an account whose silence has run to a full fortnight — that is, where the whole number of days between the current instant and the later of its `last_touchpoint_at_utc` or, if it has never been touched, its `created_at`, computed by taking the elapsed seconds divided by 86,400 and discarding the fraction, has reached 14 — and which holds no confirmed order in this season, is moved from `PROSPECT` or from `ACTIVE` to `AT_RISK`, with `at_risk_since_utc` stamped at the current instant and `churn_risk_campaign` recomputed."
    PRD 3.6: "The account's relationship dimension advances: a `PROSPECT` account becomes `ACTIVE`, a `WON_BACK` account becomes `ACTIVE`, and an `AT_RISK` account becomes `ACTIVE` with `at_risk_since_utc` cleared to null."

    Design: Difficulty/non_linear_state_machine/ticket_account_service_status_cycles_active_at_risk_active
    """
    world = setup_four_seat_zone_c_world()
    order = create_confirmed_order(
        world["account_id"],
        world["plan_id"],
        world["seat_ids"],
        world["rep_headers"],
        installment_count=1,
    )
    assert read_account(world["account_id"])["service_status"] == "ACTIVE"
    # Cancelling leaves the relationship dimension ACTIVE while removing the
    # season's only confirmed order, which is what the cadence rule reads.
    cancel_order(order["id"], world["rep_headers"], cancel_reason="buyer withdrew")
    before = read_account(world["account_id"])
    assert before["service_status"] == "ACTIVE"
    assert before["at_risk_since_utc"] is None

    set_clock("2026-08-20T00:00:00Z")
    run_ops(world["season_id"])

    after = read_account(world["account_id"])
    assert after["service_status"] == "AT_RISK", "19 days of silence passes the fortnight"
    assert after["at_risk_since_utc"] == "2026-08-20T00:00:00.000Z"


def test_committed_touchpoint_returns_an_at_risk_account_to_active():
    """PRD 3.2: "An outcome of `COMMITTED` on an account whose `service_status` is `AT_RISK` returns it to `ACTIVE` and clears `at_risk_since_utc` back to null, closing the `ACTIVE` → `AT_RISK` → `ACTIVE` cycle."
    PRD 3.2: "Every touchpoint sets the account's `last_touchpoint_at_utc` to the current instant, increments the acting rep's `touchpoints_logged_count` by 1, recomputes the account's `churn_risk_rolling`, and bumps the account's `version` by 1."

    Design: Difficulty/non_linear_state_machine/ticket_account_service_status_cycles_active_at_risk_active
    """
    world = setup_four_seat_zone_c_world()
    order = create_confirmed_order(
        world["account_id"],
        world["plan_id"],
        world["seat_ids"],
        world["rep_headers"],
        installment_count=1,
    )
    cancel_order(order["id"], world["rep_headers"], cancel_reason="buyer withdrew")
    set_clock("2026-08-20T00:00:00Z")
    run_ops(world["season_id"])
    assert read_account(world["account_id"])["service_status"] == "AT_RISK"

    revived = log_touchpoint(
        world["account_id"],
        world["rep_headers"],
        touchpoint_type="CALL",
        outcome="COMMITTED",
        note="renewal commitment",
    )

    assert revived["service_status"] == "ACTIVE"
    assert revived["at_risk_since_utc"] is None
    assert revived["last_touchpoint_at_utc"] == "2026-08-20T00:00:00.000Z"
    assert read_rep(world["rep_id"])["touchpoints_logged_count"] == 1
