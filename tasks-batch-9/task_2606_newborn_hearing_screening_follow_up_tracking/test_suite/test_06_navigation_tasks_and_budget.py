"""Navigation tasks: the selector, the unit budget, capacity, buffers and states."""

import pytest

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import clock, factories, fixtures
from test_helpers.constants import CLOCK_START
from test_helpers.test_users import (
    make_navigator_headers,
    make_program_admin_headers,
)

ADMIN = make_program_admin_headers()


def _hospital_and_clinic(client, birth_budget=None):
    hospital = fixtures.create_facility(
        client,
        "BH1",
        "BIRTH_HOSPITAL",
        "R1",
        navigation_budget_units_total=birth_budget,
    )
    fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    return hospital, clinic


def _plain_infant(client, hospital, phone, birth_datetime=CLOCK_START):
    return fixtures.create_infant(
        client,
        hospital["id"],
        birth_datetime=birth_datetime,
        birth_setting="INPATIENT",
        guardian_name="G-NV",
        guardian_contact_phone=phone,
    )


def test_the_navigator_selector_breaks_a_load_tie_on_the_higher_ceiling(client):
    """The idle navigator with the larger ceiling wins; identifiers never decide.

    PRD: "The pool is then ordered by `open_task_count` ascending, with ties broken by
    `max_open_tasks` descending and any remaining ties by `created_at` ascending;
    provider identifiers are never consulted as a tie-break."

    Design: Corner/calculations/navigator_selector_ranks_by_load_then_by_capacity_ceiling
    """
    hospital, clinic = _hospital_and_clinic(client)
    loaded = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N1", "R1", max_open_tasks=5
    )
    small_ceiling = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N2", "R1", max_open_tasks=3
    )
    big_ceiling = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N3", "R1", max_open_tasks=6
    )
    infant = _plain_infant(client, hospital, "5554501")
    loaded_headers = make_navigator_headers(loaded["id"])
    fixtures.create_task(
        client,
        infant["id"],
        "OUTREACH_CALL",
        assigned_provider_id=loaded["id"],
        headers=loaded_headers,
    )

    chosen = fixtures.create_task(
        client,
        infant["id"],
        "APPOINTMENT_NAVIGATION",
        auto_assign=True,
        headers=loaded_headers,
    )
    assert chosen["assigned_provider_id"] == big_ceiling["id"]
    assert chosen["status"] == "OPEN"
    assert chosen["units_reserved"] == 2

    assert fixtures.read_provider(client, big_ceiling["id"])["open_task_count"] == 1
    assert fixtures.read_provider(client, small_ceiling["id"])["open_task_count"] == 0
    assert fixtures.read_provider(client, loaded["id"])["open_task_count"] == 1
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=36
    )


def test_the_open_task_ledger_rises_on_assignment_and_falls_on_completion(client):
    """Completion frees the navigator without refunding the consumed units.

    PRD: "A `COMPLETED` task keeps its `units_reserved`: completed work has been
    consumed, not released, so the funding facility's remaining budget does not
    recover."

    Design: Corner/state_machines/navigator_open_task_count_syncs_on_assignment_and_completion
    """
    hospital, clinic = _hospital_and_clinic(client)
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    navigator_headers = make_navigator_headers(navigator["id"])
    infant = _plain_infant(client, hospital, "5553801")

    task = fixtures.create_task(
        client,
        infant["id"],
        "OUTREACH_CALL",
        assigned_provider_id=navigator["id"],
        headers=navigator_headers,
    )
    assert task["status"] == "OPEN"
    assert task["assigned_provider_id"] == navigator["id"]
    assert task["units_reserved"] == 2
    assert task["funding_facility_id"] == hospital["id"]
    assert fixtures.read_provider(client, navigator["id"])["open_task_count"] == 1
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=38
    )

    closed = fixtures.close_task(
        client,
        task["id"],
        "COMPLETED",
        outcome="CONTACTED",
        contacted_language="EN",
        headers=navigator_headers,
    )
    assert closed["status"] == "COMPLETED"
    assert closed["outcome"] == "CONTACTED"
    assert closed["contacted_language"] == "EN"
    assert closed["units_reserved"] == 2
    assert fixtures.read_provider(client, navigator["id"])["open_task_count"] == 0
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=38
    )


def test_individually_affordable_tasks_can_still_exhaust_the_budget(client):
    """The third two-unit task cannot fit in the one unit that is left.

    PRD: "An operator-initiated task — one created directly, or a booking that asked
    for interpreter support — is rejected outright with
    `ERR_NAVIGATION_BUDGET_EXHAUSTED`, because the program will not promise support it
    cannot fund."

    Design: Corner/validations/three_two_unit_tasks_exhaust_a_five_unit_facility_budget
    """
    hospital, clinic = _hospital_and_clinic(client, birth_budget=5)
    navigator = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N1", "R1", max_open_tasks=5
    )
    navigator_headers = make_navigator_headers(navigator["id"])
    infant = _plain_infant(client, hospital, "5554801")

    first = fixtures.create_task(
        client,
        infant["id"],
        "OUTREACH_CALL",
        assigned_provider_id=navigator["id"],
        headers=navigator_headers,
    )
    assert first["units_reserved"] == 2
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=3
    )
    second = fixtures.create_task(
        client,
        infant["id"],
        "APPOINTMENT_NAVIGATION",
        assigned_provider_id=navigator["id"],
        headers=navigator_headers,
    )
    assert second["units_reserved"] == 2
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=1
    )

    third = client.create_task(
        factories.task_payload(
            infant_id=infant["id"],
            task_type="OUTREACH_CALL",
            assigned_provider_id=navigator["id"],
        ),
        headers=navigator_headers,
    )
    check.assert_error_envelope(third, errors.ERR_NAVIGATION_BUDGET_EXHAUSTED)

    facility = fixtures.read_facility(client, hospital["id"])
    check.assert_facility_ledger(facility, navigation_budget_units_remaining=1)
    tasks = check.assert_total_count(
        client.list_tasks(headers=ADMIN, infant_id=infant["id"]), 2
    )
    check.assert_budget_conservation(facility, tasks)


def test_the_visit_window_belongs_to_home_visits_and_nothing_else(client):
    """Missing on a home visit and present on a call are both schema failures.

    PRD: "A home visit, and only a home visit, must carry the window fields
    `visit_starts_at` and `visit_ends_at`, with the end strictly after the start;
    supplying either field on a task of any other type, or omitting them on a home
    visit, is a schema violation reported as `ERR_INVALID_REQUEST`"

    Design: Corner/validations/home_visit_window_is_required_only_for_home_visit_tasks
    """
    hospital, clinic = _hospital_and_clinic(client)
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    navigator_headers = make_navigator_headers(navigator["id"])
    infant = _plain_infant(client, hospital, "5554901")

    missing_window = client.create_task(
        factories.task_payload(
            infant_id=infant["id"],
            task_type="HOME_VISIT",
            assigned_provider_id=navigator["id"],
        ),
        headers=navigator_headers,
    )
    check.assert_error_envelope(missing_window, errors.ERR_INVALID_REQUEST)

    extra_window = client.create_task(
        factories.task_payload(
            infant_id=infant["id"],
            task_type="OUTREACH_CALL",
            visit_starts_at="2026-08-02T09:00:00Z",
            visit_ends_at="2026-08-02T10:00:00Z",
            assigned_provider_id=navigator["id"],
        ),
        headers=navigator_headers,
    )
    check.assert_error_envelope(extra_window, errors.ERR_INVALID_REQUEST)

    visit = fixtures.create_task(
        client,
        infant["id"],
        "HOME_VISIT",
        visit_starts_at="2026-08-02T09:00:00Z",
        visit_ends_at="2026-08-02T10:00:00Z",
        assigned_provider_id=navigator["id"],
        headers=navigator_headers,
    )
    assert visit["units_reserved"] == 6
    assert visit["status"] == "OPEN"
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=34
    )
    check.assert_total_count(client.list_tasks(headers=ADMIN, infant_id=infant["id"]), 1)


def test_auto_assignment_needs_at_least_one_eligible_navigator(client):
    """An empty pool refuses the operator's request and debits nothing.

    PRD: "When the pool is empty, an operator-initiated assignment is rejected with
    `ERR_NO_ELIGIBLE_NAVIGATOR`, whereas a cascade-minted task is simply left in
    `UNASSIGNED` with `assigned_provider_id` null, sitting in a deferred queue until
    somebody assigns it."

    Design: Corner/endpoints/auto_assign_is_allowed_only_when_the_navigator_pool_is_non_empty
    """
    hospital = fixtures.create_facility(client, "BH1", "BIRTH_HOSPITAL", "R1")
    fixtures.create_provider(client, hospital["id"], "SCREENER", "S1", "R1")
    fixtures.set_clock(client, clock.at(hours=6))
    infant = _plain_infant(client, hospital, "5555501")

    unstaffed = client.create_task(
        factories.task_payload(
            infant_id=infant["id"], task_type="OUTREACH_CALL", auto_assign=True
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(unstaffed, errors.ERR_NO_ELIGIBLE_NAVIGATOR)
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=40
    )
    check.assert_total_count(client.list_tasks(headers=ADMIN, infant_id=infant["id"]), 0)

    clinic = fixtures.create_facility(client, "AC1", "AUDIOLOGY_CLINIC", "R1")
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")

    staffed = fixtures.create_task(
        client, infant["id"], "OUTREACH_CALL", auto_assign=True, headers=ADMIN
    )
    assert staffed["status"] == "OPEN"
    assert staffed["assigned_provider_id"] == navigator["id"]
    assert staffed["units_reserved"] == 2
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=38
    )
    assert fixtures.read_provider(client, navigator["id"])["open_task_count"] == 1


def test_capacity_and_task_state_both_gate_assignment_and_closure(client):
    """A full navigator is refused twice over, and each action runs once only.

    PRD: "When the request names a navigator explicitly, that navigator must still
    satisfy the type, credential, and workload conditions: one already holding
    `max_open_tasks` tasks in `OPEN` is rejected with `ERR_NAVIGATOR_AT_CAPACITY`."

    Design: Corner/errors/assign_and_close_outside_the_allowed_task_states_are_rejected
    """
    hospital, clinic = _hospital_and_clinic(client)
    full = fixtures.create_provider(
        client, clinic["id"], "NAVIGATOR", "N1", "R1", max_open_tasks=1
    )
    spare = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N2", "R1")
    infant = _plain_infant(client, hospital, "5555901")
    fixtures.create_task(
        client, infant["id"], "OUTREACH_CALL", assigned_provider_id=full["id"], headers=ADMIN
    )

    at_capacity = client.create_task(
        factories.task_payload(
            infant_id=infant["id"],
            task_type="APPOINTMENT_NAVIGATION",
            assigned_provider_id=full["id"],
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(at_capacity, errors.ERR_NAVIGATOR_AT_CAPACITY)
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=38
    )
    check.assert_total_count(client.list_tasks(headers=ADMIN, infant_id=infant["id"]), 1)

    queued = fixtures.create_task(
        client, infant["id"], "APPOINTMENT_NAVIGATION", headers=ADMIN
    )
    assert queued["status"] == "UNASSIGNED"
    assert queued["assigned_provider_id"] is None
    assert queued["units_reserved"] == 2
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=36
    )

    to_full = client.assign_task(
        queued["id"], {"assigned_provider_id": full["id"]}, headers=ADMIN
    )
    check.assert_error_envelope(to_full, errors.ERR_NAVIGATOR_AT_CAPACITY)
    assert fixtures.read_task(client, queued["id"])["status"] == "UNASSIGNED"

    assigned = fixtures.assign_task(client, queued["id"], assigned_provider_id=spare["id"])
    assert assigned["status"] == "OPEN"
    assert assigned["assigned_provider_id"] == spare["id"]
    assert fixtures.read_provider(client, spare["id"])["open_task_count"] == 1

    again = client.assign_task(
        queued["id"], {"assigned_provider_id": spare["id"]}, headers=ADMIN
    )
    check.assert_error_envelope(again, errors.ERR_TASK_INVALID_STATE)

    closed = fixtures.close_task(
        client, queued["id"], "COMPLETED", outcome="CONTACTED", contacted_language="EN"
    )
    assert closed["status"] == "COMPLETED"
    assert closed["outcome"] == "CONTACTED"
    assert closed["units_reserved"] == 2
    assert fixtures.read_provider(client, spare["id"])["open_task_count"] == 0
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=36
    )

    reclose = client.close_task(
        queued["id"],
        {"disposition": "COMPLETED", "outcome": "CONTACTED", "contacted_language": "EN"},
        headers=ADMIN,
    )
    check.assert_error_envelope(reclose, errors.ERR_TASK_INVALID_STATE)
    assert fixtures.read_task(client, queued["id"])["status"] == "COMPLETED"


def test_a_second_home_visit_must_clear_the_travel_buffer(client):
    """Thirty minutes between visits is refused; forty-five is exactly enough.

    PRD: "the assignment is permitted only when the new visit's `visit_starts_at` is
    at or after the other visit's `visit_ends_at` plus 45 minutes, or the other
    visit's `visit_starts_at` is at or after the new visit's `visit_ends_at` plus 45
    minutes."

    Design: Corner/errors/home_visit_thirty_minutes_after_another_visit_is_rejected_by_the_travel_buffer
    """
    hospital, clinic = _hospital_and_clinic(client)
    navigator = fixtures.create_provider(client, clinic["id"], "NAVIGATOR", "N1", "R1")
    first_family = _plain_infant(client, hospital, "5556001")
    second_family = _plain_infant(client, hospital, "5556002", birth_datetime=clock.at(hours=1))

    first_visit = fixtures.create_task(
        client,
        first_family["id"],
        "HOME_VISIT",
        visit_starts_at="2026-08-02T10:00:00Z",
        visit_ends_at="2026-08-02T11:00:00Z",
        assigned_provider_id=navigator["id"],
        headers=ADMIN,
    )
    assert first_visit["status"] == "OPEN"
    assert first_visit["units_reserved"] == 6
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=34
    )

    too_soon = client.create_task(
        factories.task_payload(
            infant_id=second_family["id"],
            task_type="HOME_VISIT",
            visit_starts_at="2026-08-02T11:30:00Z",
            visit_ends_at="2026-08-02T12:30:00Z",
            assigned_provider_id=navigator["id"],
        ),
        headers=ADMIN,
    )
    check.assert_error_envelope(too_soon, errors.ERR_NAVIGATOR_TRAVEL_BUFFER)
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=34
    )
    assert fixtures.read_provider(client, navigator["id"])["open_task_count"] == 1

    exactly_enough = fixtures.create_task(
        client,
        second_family["id"],
        "HOME_VISIT",
        visit_starts_at="2026-08-02T11:45:00Z",
        visit_ends_at="2026-08-02T12:45:00Z",
        assigned_provider_id=navigator["id"],
        headers=ADMIN,
    )
    assert exactly_enough["status"] == "OPEN"
    assert exactly_enough["assigned_provider_id"] == navigator["id"]
    assert exactly_enough["units_reserved"] == 6
    check.assert_facility_ledger(
        fixtures.read_facility(client, hospital["id"]), navigation_budget_units_remaining=28
    )
    assert fixtures.read_provider(client, navigator["id"])["open_task_count"] == 2
