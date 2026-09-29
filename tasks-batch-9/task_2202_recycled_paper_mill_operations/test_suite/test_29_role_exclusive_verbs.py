"""Which role may press which lever: the machine status patch, the weighbridge verdict
against the pulper charge, the steam header write against its shared read, and the
three roles that may move the logical clock.
"""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    TEST_USERS, declare_fiber_grade, declare_tl_140, publish_quote, register_supplier,
    register_machine, create_confirmed_po, record_receipt, disposition, queue_batch,
    furnish_line, lots_of_receipt, machine_version, create_steam_allocation_payload,
    sublot, set_clock,
)

PLANNER = TEST_USERS["planner_headers"]
BUYER = TEST_USERS["buyer_headers"]
OPERATOR = TEST_USERS["operator_headers"]
LAB = TEST_USERS["lab_headers"]
SAMPLER = TEST_USERS["lab_sampler_headers"]
DISPOSER = TEST_USERS["lab_dispo_headers"]
ENV = TEST_USERS["env_officer_headers"]
ENERGY = TEST_USERS["energy_headers"]

PM1 = {"name": "PM1", "wire_width_mm": 5600, "max_tons_per_hour": 20.00,
       "changeover_buffer_minutes": 30, "steam_tph_per_ton": 2.500}
CLEAN_TRUCK = [sublot(1, 30.000, 8.000, 10.00, 2.00)]


def test_the_operator_who_runs_the_machine_may_not_take_it_out_of_service():
    """PRD §2.1: "When the acting role is a valid role but that role is not authorised for
    the endpoint being addressed, the request is rejected with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."
    PRD §2.1: "A `MillPlanner` owns scheduling in the broad sense: paper machines and their
    operational status, paper grade specifications, customer master records, run windows,
    grade changes, order sequencing, and the discretionary decisions to divert a pulp
    batch, abort a run, or condemn its quality."
    PRD §3.4: "The planner may take a machine out of service or return it, setting `status`
    to `DOWN` or `RUNNABLE`; a `DOWN` machine blocks both new run scheduling and run
    starting."

    Design: Corner/rbac/mill_planner_alone_may_take_a_machine_down
    """
    machine = register_machine(**PM1)
    version_before = machine_version(machine["id"])

    response = api_client.patch_paper_machine_status(
        machine["id"],
        {"status": "DOWN", "expected_machine_version": version_before}, OPERATOR)
    validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    untouched = get_success_data(api_client.get_paper_machine(machine["id"], PLANNER))
    assert untouched["status"] == "RUNNABLE"
    assert untouched["version"] == version_before, "the refused call wrote nothing"

    downed = validate_success(api_client.patch_paper_machine_status(
        machine["id"],
        {"status": "DOWN", "expected_machine_version": version_before}, PLANNER))
    assert downed["status"] == "DOWN"
    assert downed["version"] == version_before + 1


def test_the_lab_judges_the_truck_and_the_operator_charges_the_pulper():
    """PRD §2.1: "A `QualityLab` operator owns sampling and quality judgement: recording
    truck samples and dispositioning them, approving pulp and recording brightness,
    certifying or holding run quality, and quarantining roll sets."
    PRD §2.1: "A `MachineOperator` runs the equipment: charging the pulper, screening,
    cleaning, deink passes, starting and completing runs, and winding, wrapping and
    rewinding rolls."
    PRD §2.1: "When the acting role is a valid role but that role is not authorised for the
    endpoint being addressed, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."
    PRD §3.3: "Charging the pulper moves the batch `QUEUED → PULPING` and is the point at
    which fiber actually leaves inventory."

    Design: Corner/rbac/quality_lab_alone_may_disposition_a_truck_and_the_operator_may_not
    """
    set_clock("2026-08-01T00:00:00Z")
    declare_tl_140()
    declare_fiber_grade(grade_code="OCC_11", index_symbol="PPI_OCC",
                        max_contamination_pct=3.00, max_moisture_pct=12.00,
                        nominal_yield_pct=88.00, rank_order=1)
    publish_quote(index_symbol="PPI_OCC", effective_month="2026-08",
                  published_price_per_ton=180.00)
    supplier = register_supplier(name="Delta Fiber Recovery", freight_per_ton=12.50)
    po = create_confirmed_po(supplier["id"], "OCC_11", contracted_tons=400.00,
                             negotiated_delta_per_ton=5.00)
    receipt = record_receipt(po["id"], CLEAN_TRUCK, truck_reference="TRK-0001",
                            sampler_headers=SAMPLER)

    by_the_operator = api_client.disposition_receipt(
        receipt["id"], {"disposition": "ACCEPT"}, OPERATOR)
    validate_error(by_the_operator, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert get_success_data(api_client.get_receipt(
        receipt["id"], BUYER))["status"] == "SAMPLED"

    accepted = disposition(receipt["id"], "ACCEPT", headers=DISPOSER)
    assert accepted["status"] == "ACCEPTED"
    assert accepted["dispositioned_by_user_id"] == "ql_dispo"

    lot = lots_of_receipt(receipt["id"])[0]
    batch = queue_batch("TL_140", [furnish_line(lot["id"], 20.000)])
    by_the_lab = api_client.start_pulp_batch(batch["id"], LAB)
    validate_error(by_the_lab, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)
    assert get_success_data(api_client.get_pulp_batch(
        batch["id"], OPERATOR))["status"] == "QUEUED"

    charged = validate_success(api_client.start_pulp_batch(batch["id"], OPERATOR))
    assert charged["status"] == "PULPING", "each role is refused the other's verb"


def test_the_planner_may_read_the_steam_header_but_never_book_it():
    """PRD §2.1: "An `EnergyManager` owns the steam header and cogeneration: allocation
    requests, curtailment outcomes, and releases."
    PRD §2.1: "When the acting role is a valid role but that role is not authorised for the
    endpoint being addressed, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."
    PRD §3.8: "Steam is a shared header with finite capacity, and the `EnergyManager` books
    it in windows."

    Design: Corner/rbac/only_the_energy_manager_touches_the_steam_header
    """
    set_clock("2026-08-01T00:00:00Z")
    machine = register_machine(**PM1)
    booked = validate_success(api_client.create_steam_allocation(
        create_steam_allocation_payload(
            consumer_kind="PAPER_MACHINE", consumer_ref_id=machine["id"],
            window_start="2026-09-01T06:00:00Z", window_end="2026-09-01T14:00:00Z",
            demand_tph=40.000, priority_rank=1), ENERGY), 201)

    refused = api_client.create_steam_allocation(
        create_steam_allocation_payload(
            consumer_kind="PAPER_MACHINE", consumer_ref_id=machine["id"],
            window_start="2026-09-01T06:00:00Z", window_end="2026-09-01T14:00:00Z",
            demand_tph=10.000, priority_rank=2), PLANNER)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    seen_by_the_planner = api_client.list_steam_allocations(PLANNER).json()
    assert seen_by_the_planner["meta"]["total_count"] == 1, \
        "the planner reads the header it may not book"
    assert seen_by_the_planner["data"][0]["id"] == booked["id"]
    assert api_client.list_steam_allocations(
        ENERGY).json()["meta"]["total_count"] == 1


def test_three_roles_may_move_the_logical_clock_and_the_operator_may_not():
    """PRD §2.9: "An administrative test-driving capability lets a `MillPlanner`, an
    `EnvironmentalOfficer`, or an `EnergyManager` move the clock forward or backward: the
    request carries a single field `to_iso8601` holding the target instant, the response
    body reports the resulting instant as `current_utc`, and the call recomputes no entity
    state — it only changes the instant from which subsequent writes stamp their
    timestamps."
    PRD §2.1: "When the acting role is a valid role but that role is not authorised for the
    endpoint being addressed, the request is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP
    403)."

    Design: Corner/rbac/the_clock_is_shared_by_exactly_three_roles
    """
    for headers, instant in ((PLANNER, "2026-08-01T00:00:00Z"),
                             (ENV, "2026-08-02T00:00:00Z"),
                             (ENERGY, "2026-08-03T00:00:00Z")):
        moved = validate_success(api_client.set_clock(instant, headers))
        assert moved["current_utc"].startswith(instant[:19]), \
            "the clock reports back exactly the instant it was given"

    refused = api_client.set_clock("2026-08-10T00:00:00Z", OPERATOR)
    validate_error(refused, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    stamped_after_the_refusal = register_machine(name="PM3", wire_width_mm=5600,
                                                max_tons_per_hour=20.00,
                                                changeover_buffer_minutes=30,
                                                steam_tph_per_ton=2.500)
    assert stamped_after_the_refusal["created_at"].startswith("2026-08-03"), \
        "the refused call did not advance the clock"
