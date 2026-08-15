"""Survey cycle lifecycle: initial state, configure gate, OCC, single-open."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_survey_cycle,
    configure_cycle,
    get_success_data,
    make_active_bank,
    make_cycle,
    make_employee,
    make_unit,
    pin_items,
    api_client,
    set_clock,
    setup_cycle_with_field_results,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

HR_ADMIN = TEST_USERS["hr_admin_headers"]
PEOPLE_ANALYST = TEST_USERS["people_analyst_headers"]


def test_cycle_created_in_draft_initial_state(api):
    """PRD §3.3: "A survey cycle is created by an `HRAdmin` in `DRAFT` status,
    carrying a `label` such as "2026 Census", a `cycle_kind` of `CENSUS` or
    `PULSE`, the `bank_id` of the instrument it draws from, and the window
    bounds `opens_at` and `closes_at`."
    PRD §2.4: "`version` is an integer that starts at 1 and increments by
    exactly 1 on every mutation of the resource"

    Design: Corner/state_machines/cycle_starts_in_draft_initial_state
    """
    bank, _items = make_active_bank("Init Bank", framework="EWI")
    resp = api.create_survey_cycle(
        {
            "label": "Init Cycle",
            "cycle_kind": "CENSUS",
            "bank_id": bank["id"],
            "opens_at": "2026-09-01T00:00:00Z",
            "closes_at": "2026-09-15T00:00:00Z",
        },
        HR_ADMIN,
    )
    cycle = validate_success(resp, 201)
    assert_survey_cycle(cycle)
    assert cycle["status"] == "DRAFT"
    assert cycle["version"] == 1
    assert cycle["invited_count"] == 0
    assert cycle["submitted_count"] == 0
    assert cycle["partial_count"] == 0


def test_configure_requires_three_pinned_items(api):
    """PRD §3.3: "Three conditions must hold: the cycle has at least three
    pinned cycle items (otherwise `ERR_INSUFFICIENT_ITEMS`), `closes_at` is
    strictly after `opens_at`, and the linked item bank is in `ACTIVE` status."

    Design: Corner/validations/configure_with_fewer_than_three_items_rejected
    """
    bank, items = make_active_bank("Floor Bank")
    cycle = make_cycle(bank["id"], label="Floor Cycle")
    pin_items(cycle["id"], items[:2])
    current = get_success_data(api.get_survey_cycle(cycle["id"], HR_ADMIN))

    resp = api.configure_cycle(
        cycle["id"], {"expected_cycle_version": current["version"]}, HR_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ITEMS)

    after = get_success_data(api.get_survey_cycle(cycle["id"], HR_ADMIN))
    assert after["status"] == "DRAFT", "rejected configure leaves the cycle DRAFT"


def test_get_nonexistent_cycle_returns_not_found(api):
    """PRD §2.9: "For any endpoint whose URL contains multiple resource
    identifiers, the platform validates existence strictly left to right and
    rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier
    that does not correspond to an existing resource."

    Design: Corner/entities/get_nonexistent_cycle_returns_not_found
    """
    resp = api.get_survey_cycle(NON_EXISTENT_UUID, HR_ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_archived_cycle_is_terminal_lockdown(api):
    """PRD §3.5: "Archiving is the cycle's terminal move, `REPORTED →
    ARCHIVED`, performed by an `HRAdmin` once every action plan belonging to
    the cycle has reached `COMPLETED` or `ABANDONED`; an outstanding plan
    blocks archival with `ERR_INVALID_STATE`."
    PRD §2.8: "an action that the target resource's current state does not
    permit is rejected with `ERR_INVALID_STATE` (HTTP 409), so an illegal
    transition always surfaces as a state error rather than being masked by a
    business rule."

    Design: Corner/state_machines/archived_cycle_is_terminal_lockdown
    """
    scenario = setup_cycle_with_field_results(
        unit_name="TermUnit",
        manager_user_id="mgr-term",
        num_employees=1,
        target_state="ARCHIVED",
    )
    cycle_id = scenario["cycle"]["id"]
    assert scenario["cycle"]["status"] == "ARCHIVED"

    for attempt in (
        api.open_cycle(cycle_id, HR_ADMIN),
        api.close_cycle(cycle_id, HR_ADMIN),
        api.archive_cycle(cycle_id, HR_ADMIN),
    ):
        validate_error(attempt, ApiErrorId.ERR_INVALID_STATE)


def test_second_cycle_open_rejected_while_first_is_open(api):
    """PRD §3.3: "The logical clock must have reached `opens_at`, and no other
    cycle may currently be in `OPEN` status — the platform admits exactly one
    open cycle at a time, and a second open attempt is rejected with
    `ERR_CYCLE_ALREADY_OPEN` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/single_open_cycle_capacity_conflict
    """
    bank, items = make_active_bank("Overlap Bank")
    unit = make_unit("Unit N", "mgr-n")
    make_employee(unit["id"], "N001")

    set_clock("2026-09-01T00:00:00Z")
    cycle_a = make_cycle(bank["id"], label="Cycle A", cycle_kind="CENSUS",
                         opens_at="2026-09-01T00:00:00Z", closes_at="2026-09-15T00:00:00Z")
    pin_items(cycle_a["id"], items)
    cycle_a = configure_cycle(cycle_a["id"])
    cycle_a = get_success_data(api.open_cycle(cycle_a["id"], HR_ADMIN))
    assert cycle_a["status"] == "OPEN"

    cycle_b = make_cycle(bank["id"], label="Cycle B", cycle_kind="PULSE",
                         opens_at="2026-09-05T00:00:00Z", closes_at="2026-09-08T00:00:00Z",
                         sampling_ratio=1.0)
    pin_items(cycle_b["id"], items)
    cycle_b = configure_cycle(cycle_b["id"])

    set_clock("2026-09-05T00:00:00Z")
    resp = api.open_cycle(cycle_b["id"], HR_ADMIN)
    validate_error(resp, ApiErrorId.ERR_CYCLE_ALREADY_OPEN)

    b_after = get_success_data(api.get_survey_cycle(cycle_b["id"], HR_ADMIN))
    a_after = get_success_data(api.get_survey_cycle(cycle_a["id"], HR_ADMIN))
    assert b_after["status"] == "CONFIGURED", "rejected open leaves B CONFIGURED"
    assert a_after["status"] == "OPEN", "the rejected second open must not disturb A"


def test_open_succeeds_once_prior_cycle_is_closed(api):
    """PRD §3.3: "The logical clock must have reached `opens_at`, and no other
    cycle may currently be in `OPEN` status — the platform admits exactly one
    open cycle at a time, and a second open attempt is rejected with
    `ERR_CYCLE_ALREADY_OPEN` (HTTP 409)."
    PRD §3.5: "A cycle leaves the field in one of two ways: an `HRAdmin` closes
    it deliberately at any time after opening, or the system closes it
    automatically once the logical clock reaches `closes_at`."

    Design: Difficulty/resource_temporal_overlap/single_open_cycle_capacity_conflict
    """
    bank, items = make_active_bank("Overlap2 Bank")
    unit = make_unit("Unit N2", "mgr-n2")
    make_employee(unit["id"], "N201")

    set_clock("2026-09-01T00:00:00Z")
    cycle_a = make_cycle(bank["id"], label="Cycle A2", cycle_kind="CENSUS",
                         opens_at="2026-09-01T00:00:00Z", closes_at="2026-09-15T00:00:00Z")
    pin_items(cycle_a["id"], items)
    cycle_a = configure_cycle(cycle_a["id"])
    cycle_a = get_success_data(api.open_cycle(cycle_a["id"], HR_ADMIN))
    assert cycle_a["status"] == "OPEN"

    cycle_b = make_cycle(bank["id"], label="Cycle B2", cycle_kind="PULSE",
                         opens_at="2026-09-05T00:00:00Z", closes_at="2026-09-08T00:00:00Z",
                         sampling_ratio=1.0)
    pin_items(cycle_b["id"], items)
    cycle_b = configure_cycle(cycle_b["id"])

    set_clock("2026-09-05T00:00:00Z")
    closed_a = get_success_data(api.close_cycle(cycle_a["id"], HR_ADMIN))
    assert closed_a["status"] == "CLOSED"

    opened_b = get_success_data(api.open_cycle(cycle_b["id"], HR_ADMIN))
    assert_survey_cycle(opened_b)
    assert opened_b["status"] == "OPEN", "closing A frees the single-open slot for B"


def test_occ_stale_cycle_version_on_configure(api):
    """PRD §2.12: "First, configuring a survey cycle requires the request to
    carry `expected_cycle_version`, holding the cycle's `version` as the client
    last observed it; if the cycle's current `version` has advanced since then
    — for example because another writer pinned or removed a cycle item, which
    bumps the cycle's `version` as a cascade — the configure is rejected with
    `ERR_STALE_VERSION` (HTTP 412), preventing the client from committing a
    configuration against items it never saw."

    Design: Corner/cross_cutting_layers/occ_stale_cycle_version_on_configure
    """
    bank, items = make_active_bank(
        "OCC Bank",
        item_specs=[
            {"item_code": "OC-1", "dimension": "PURPOSE", "weight": 1.0},
            {"item_code": "OC-2", "dimension": "PURPOSE", "weight": 1.0},
            {"item_code": "OC-3", "dimension": "PURPOSE", "weight": 1.0},
            {"item_code": "OC-4", "dimension": "GROWTH", "weight": 1.0},
        ],
    )
    cycle = make_cycle(bank["id"], label="OCC Cycle")
    pin_items(cycle["id"], items[:3])
    observed = get_success_data(api.get_survey_cycle(cycle["id"], HR_ADMIN))
    observed_version = observed["version"]

    # Another writer pins a 4th item, cascading a cycle version bump.
    pin_items(cycle["id"], items[3:], pinned_weights=[items[3]["weight"]],
              start_order=4)

    resp = api.configure_cycle(
        cycle["id"], {"expected_cycle_version": observed_version}, HR_ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    after = get_success_data(api.get_survey_cycle(cycle["id"], HR_ADMIN))
    assert after["status"] == "DRAFT", "stale configure leaves the cycle DRAFT"
    assert after["version"] == observed_version + 1, (
        "the item-pin cascade bumped the cycle version exactly once"
    )

    retry = api.configure_cycle(
        cycle["id"], {"expected_cycle_version": after["version"]}, HR_ADMIN
    )
    configured = validate_success(retry, 200)
    assert configured["status"] == "CONFIGURED", "a fresh version configures cleanly"
