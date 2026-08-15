"""Technical inspection: the append-only weigh-in log, the weight-compliance
boundary, the re-inspection loop and disqualification thresholds, and the
all-or-nothing grid lock with its state and fiscal gates."""
from test_helpers import (
    ApiErrorId,
    assert_entry,
    assert_inspection,
    enter_driver,
    get_entry,
    record_inspection,
    register_active_driver,
    setup_grid_locked_event,
    setup_open_event,
    start_event,
    validate_error,
    validate_success,
)

def test_inspection_log_is_append_only_without_version_fields(
    api, league_admin_headers, race_director_headers
):
    """PRD 2.4: "Technical inspections are the deliberate exception. An inspection
    record is append-only and carries only `id` and `created_at`; both `updated_at` and
    `version` are absent, because an inspection is never modified after it is
    recorded."
    PRD 3.4: "Inspection records are append-only, listed in recording order, and — per
    §2.4 — carry no `updated_at` or `version`."

    Design: Corner/entities/tech_inspection_immutable_log
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Logged")["id"],
        ctx["race_class"]["id"],
    )
    first = record_inspection(entry["id"], 169.9)
    second = record_inspection(entry["id"], 170.5)

    listing = validate_success(
        api.list_inspections(entry["id"], league_admin_headers), 200
    )
    assert len(listing) == 2
    assert [row["id"] for row in listing] == [first["id"], second["id"]], (
        "inspections are listed in recording order"
    )
    assert listing[0]["outcome"] == "FAIL"
    assert listing[1]["outcome"] == "PASS"
    for row in listing:
        assert_inspection(row)


def test_weight_just_below_minimum_fails(api, league_admin_headers):
    """PRD 3.4: "The `outcome` is computed, never asserted: the reading earns a `PASS`
    when it is greater than or equal to the class's `min_combined_weight_kg`, with
    exact equality on the scale passing, and anything below the minimum earns a
    `FAIL`."

    Design: Corner/calculations/weight_just_below_minimum_fails
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Light")["id"],
        ctx["race_class"]["id"],
    )
    inspection = record_inspection(entry["id"], 169.9)
    assert inspection["outcome"] == "FAIL", "169.9 kg is below the 170.0 kg minimum"

    entry = get_entry(entry["id"])
    assert entry["status"] == "TECH_FAILED"
    assert entry["tech_fail_count"] == 1


def test_weight_exactly_at_minimum_passes(api, league_admin_headers):
    """PRD 3.4: "The `outcome` is computed, never asserted: the reading earns a `PASS`
    when it is greater than or equal to the class's `min_combined_weight_kg`, with
    exact equality on the scale passing, and anything below the minimum earns a
    `FAIL`."

    Design: Difficulty/boundary_precision_check/weight_exact_minimum_passes
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Exact")["id"],
        ctx["race_class"]["id"],
    )
    inspection = record_inspection(entry["id"], 170.0)
    assert inspection["outcome"] == "PASS", (
        "exact equality on the scale passes (170.0 >= 170.0)"
    )


def test_equality_pass_leaves_entry_tech_passed_without_failures(
    api, league_admin_headers
):
    """PRD 3.4: "Recording an inspection drives the entry's technical state machine.
    From `ENTERED` (the first inspection), from `TECH_FAILED` (a re-inspection), or
    from `TECH_PASSED` or `GRID_LOCKED` (a post-race re-weigh), the entry moves into
    `TECH_CHECK` and immediately resolves by outcome: a `PASS` settles it at
    `TECH_PASSED`, while a `FAIL` settles it at `TECH_FAILED` and adds one to the
    entry's `tech_fail_count`."

    Design: Difficulty/boundary_precision_check/weight_exact_minimum_passes
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Exact")["id"],
        ctx["race_class"]["id"],
    )
    record_inspection(entry["id"], 170.0)

    entry = get_entry(entry["id"])
    assert_entry(entry)
    assert entry["status"] == "TECH_PASSED"
    assert entry["tech_fail_count"] == 0


def test_failed_inspection_opens_reinspection_loop(api, league_admin_headers):
    """PRD 3.4: "Recording an inspection drives the entry's technical state machine.
    From `ENTERED` (the first inspection), from `TECH_FAILED` (a re-inspection), or
    from `TECH_PASSED` or `GRID_LOCKED` (a post-race re-weigh), the entry moves into
    `TECH_CHECK` and immediately resolves by outcome: a `PASS` settles it at
    `TECH_PASSED`, while a `FAIL` settles it at `TECH_FAILED` and adds one to the
    entry's `tech_fail_count`."
    PRD 3.4: "Before the count reaches two, the re-inspection loop is open-ended: an
    entry may cycle `TECH_FAILED → TECH_CHECK → TECH_PASSED` as many times as the
    officials allow."

    Design: Difficulty/non_linear_state_machine/entry_tech_reinspection_cycle
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Looper")["id"],
        ctx["race_class"]["id"],
    )
    inspection = record_inspection(entry["id"], 169.9)
    assert inspection["outcome"] == "FAIL"

    entry = get_entry(entry["id"])
    assert entry["status"] == "TECH_FAILED", (
        "the first inspection resolves ENTERED -> TECH_CHECK -> TECH_FAILED"
    )
    assert entry["tech_fail_count"] == 1, "one failure, below the threshold of two"


def test_reinspection_pass_returns_entry_to_tech_passed(api, league_admin_headers):
    """PRD 3.4: "Before the count reaches two, the re-inspection loop is open-ended: an
    entry may cycle `TECH_FAILED → TECH_CHECK → TECH_PASSED` as many times as the
    officials allow."
    PRD 3.4: "The count is cumulative over the entry's life in the event, and the
    second failed inspection disqualifies the entry outright — `DISQUALIFIED`, a
    terminal state."

    Design: Difficulty/non_linear_state_machine/entry_tech_reinspection_cycle
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Looper")["id"],
        ctx["race_class"]["id"],
    )
    record_inspection(entry["id"], 169.9)
    second = record_inspection(entry["id"], 170.5)
    assert second["outcome"] == "PASS"

    entry = get_entry(entry["id"])
    assert entry["status"] == "TECH_PASSED", (
        "the loop returns the entry TECH_FAILED -> TECH_CHECK -> TECH_PASSED"
    )
    assert entry["tech_fail_count"] == 1, (
        "the failure count is cumulative and stays below the disqualify threshold"
    )


def test_second_failed_inspection_disqualifies_entry(api, league_admin_headers):
    """PRD 3.4: "The count is cumulative over the entry's life in the event, and the
    second failed inspection disqualifies the entry outright — `DISQUALIFIED`, a
    terminal state."

    Design: Corner/state_machines/second_tech_fail_disqualifies_entry
    """
    ctx = setup_open_event()
    entry = enter_driver(
        ctx["event"]["id"],
        register_active_driver(full_name="Underweight")["id"],
        ctx["race_class"]["id"],
    )
    record_inspection(entry["id"], 169.0)
    second = record_inspection(entry["id"], 168.5)
    assert second["outcome"] == "FAIL"

    entry = get_entry(entry["id"])
    assert entry["tech_fail_count"] == 2
    assert entry["status"] == "DISQUALIFIED", (
        "the second failed inspection disqualifies the entry outright"
    )


def test_post_race_weight_failure_from_grid_locked_disqualifies(
    api, league_admin_headers
):
    """PRD 3.4: "A `FAIL` recorded against a `GRID_LOCKED` entry — the post-race weight
    failure — likewise disqualifies immediately, regardless of the count."
    PRD 3.4: "Disqualification, however it arrives, strips the entry's sporting yield
    for the event without rewriting history: every result the entry holds in the
    event's sessions has its `points_awarded` set to zero while its `finish_position`
    is left unchanged — no other competitor is moved up to fill the gap — and the
    entry's `event_points` is recomputed, which for a disqualified entry comes to
    zero."

    Design: Corner/state_machines/post_race_fail_from_grid_locked_disqualifies
    """
    ctx = setup_grid_locked_event(num_drivers=1)
    entry = ctx["entries"][0]
    assert entry["status"] == "GRID_LOCKED"
    assert entry["tech_fail_count"] == 0

    inspection = record_inspection(entry["id"], 169.9)
    assert inspection["outcome"] == "FAIL"

    entry = get_entry(entry["id"])
    assert entry["status"] == "DISQUALIFIED", (
        "a post-race weight failure from GRID_LOCKED disqualifies on the first failure"
    )
    assert entry["event_points"] == 0


def test_lock_grid_blocked_when_entry_not_tech_passed(
    api, race_director_headers
):
    """PRD 3.4: "The call is all-or-nothing across the event: every `TECH_PASSED` entry
    advances to `GRID_LOCKED` in one stroke, but if any non-`WITHDRAWN` entry is not in
    `TECH_PASSED` the whole call fails with `ERR_TECH_NOT_PASSED`, and if any
    non-`WITHDRAWN` entry's `fee_status` is not `PAID` the whole call fails with
    `ERR_ENTRY_FEE_UNPAID` (HTTP 402)."

    Design: Corner/validations/lock_grid_blocked_by_tech_not_passed
    """
    ctx = setup_open_event()
    entry_a = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"], pay=True, inspect_weight=171.0,
    )
    enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="B")["id"],
        ctx["race_class"]["id"], pay=True,
    )  # paid but never inspected: still ENTERED
    start_event(ctx["event"]["id"])

    response = api.lock_grid(ctx["event"]["id"], race_director_headers)
    validate_error(response, ApiErrorId.ERR_TECH_NOT_PASSED.value, 409)

    after = get_entry(entry_a["id"])
    assert after["status"] == "TECH_PASSED", (
        "the call is all-or-nothing: no partial grid lock"
    )


def test_lock_grid_blocked_by_unpaid_fee(api, race_director_headers):
    """PRD 3.4: "The call is all-or-nothing across the event: every `TECH_PASSED` entry
    advances to `GRID_LOCKED` in one stroke, but if any non-`WITHDRAWN` entry is not in
    `TECH_PASSED` the whole call fails with `ERR_TECH_NOT_PASSED`, and if any
    non-`WITHDRAWN` entry's `fee_status` is not `PAID` the whole call fails with
    `ERR_ENTRY_FEE_UNPAID` (HTTP 402)."

    Design: Corner/validations/lock_grid_blocked_by_unpaid_fee
    """
    ctx = setup_open_event()
    entry_a = enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="A")["id"],
        ctx["race_class"]["id"], pay=True, inspect_weight=171.0,
    )
    enter_driver(
        ctx["event"]["id"], register_active_driver(full_name="B")["id"],
        ctx["race_class"]["id"], pay=False, inspect_weight=172.0,
    )  # weighed in but fee UNPAID
    start_event(ctx["event"]["id"])

    response = api.lock_grid(ctx["event"]["id"], race_director_headers)
    validate_error(response, ApiErrorId.ERR_ENTRY_FEE_UNPAID.value, 402)

    after = get_entry(entry_a["id"])
    assert after["status"] == "TECH_PASSED", (
        "the fiscal gate is all-or-nothing too: no partial grid lock"
    )


def test_withdraw_from_grid_locked_rejected(api, league_admin_headers):
    """PRD 3.3: "Withdrawal, by the owning driver or a `LeagueAdmin`, moves an entry
    from `ENTERED`, `TECH_CHECK`, `TECH_FAILED`, or `TECH_PASSED` to `WITHDRAWN`;
    `GRID_LOCKED` and `DISQUALIFIED` entries can no longer withdraw
    (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/withdraw_from_grid_locked_rejected
    """
    ctx = setup_grid_locked_event(num_drivers=1)
    entry = ctx["entries"][0]

    response = api.withdraw_entry(entry["id"], league_admin_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value, 409)

    after = get_entry(entry["id"])
    assert after["status"] == "GRID_LOCKED"
    assert after["fee_status"] == "PAID", "a rejected withdrawal refunds nothing"
