"""Validation priority pairs and resource temporal-overlap semantics."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    MGR,
    NON_EXISTENT_UUID,
    OP,
    abort_load_run,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_fixture,
    create_permit,
    create_titrated_bath,
    get_bath,
    get_bath_version,
    get_success_data,
    get_work_order,
    prepare_work_order,
    route_work_order,
    set_clock,
    setup_routed_order,
    start_load_run,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_discharge_permit_payload,
    create_work_order_payload,
)
from test_helpers.test_users import make_customer_headers


def test_stale_version_beats_bath_occupied():
    """PRD §2.7: "Starting a load run (`POST /work-orders/{id}/load-runs`) requires
    `expected_bath_version` matching the routed PlatingBath's current `version`.
    Because the stale-version check fires before the state checks, a stale-version
    start is rejected with HTTP 412 even when the bath is already occupied by another
    running load — a situation that would otherwise surface as `ERR_BATH_OCCUPIED`."

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_bath_occupied
    """
    customer = create_customer(company_name="Iota Castings")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-9", routing_modes_supported=["BARREL"])
    wa = setup_routed_order(customer["id"], bath["id"], part_number="PN-900A")
    v_pre = get_bath_version(bath["id"])
    # Occupy the bath — this advances the bath version past v_pre.
    start_load_run(wa["id"], bath_version=v_pre)
    wb = setup_routed_order(customer["id"], bath["id"], part_number="PN-900B")
    # Stale start: 412 ERR_STALE_VERSION, NOT 409 ERR_BATH_OCCUPIED.
    resp_stale = api_client.start_load_run(
        wb["id"],
        {"duration_minutes": 40, "current_density_a_dm2": 1.5,
         "expected_bath_version": v_pre},
        OP,
    )
    validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)


def test_fresh_version_start_on_occupied_bath_yields_bath_occupied():
    """PRD §3.5: "the bath must be `ACTIVE` (else `ERR_BATH_NOT_ACTIVE`) with no
    `RUNNING` load — a bath runs at most one load at a time, tracked by
    `active_load_run_id`, and a busy bath yields `ERR_BATH_OCCUPIED`"

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_bath_occupied
    """
    customer = create_customer(company_name="Iota Castings 2")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-9B", routing_modes_supported=["BARREL"])
    wa = setup_routed_order(customer["id"], bath["id"], part_number="PN-900A2")
    start_load_run(wa["id"], bath_id=bath["id"])
    wb = setup_routed_order(customer["id"], bath["id"], part_number="PN-900B2")
    # Fresh-version control: occupancy failure is independently live.
    resp = api_client.start_load_run(
        wb["id"],
        {"duration_minutes": 40, "current_density_a_dm2": 1.5,
         "expected_bath_version": get_bath_version(bath["id"])},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_BATH_OCCUPIED)


def test_alloy_incompatibility_beats_credit_hold():
    """PRD §2.8: "All requests pass through a fixed twelve-tier validation cascade, and
    a request fails at the earliest tier that rejects it — earlier tiers mask later
    ones."
    PRD §2.8 tier 8: "Chemistry and alloy safety. Alloy compatibility (a missing rule
    or an `INCOMPATIBLE` rule rejects), the pre-dip gate for `CONDITIONAL`
    compatibility, bath concentration within its inclusive control band and titrated
    at least once, and no unverified dose at load start. Violations yield
    `ERR_ALLOY_BATH_INCOMPATIBLE`, `ERR_PREDIP_REQUIRED`,
    `ERR_BATH_CONCENTRATION_OUT_OF_BAND`, or `ERR_DOSE_VERIFICATION_PENDING`
    (HTTP 422)."
    PRD §2.8 tier 11: "Capacity and fiscal gates. Route-time effective bath-life
    sufficiency, load-start nameplate capacity (used plus reserved plus estimate must
    not exceed capacity, equality allowed), and customer credit hold or suspension.
    Violations yield `ERR_BATH_LIFE_INSUFFICIENT`, `ERR_BATH_CAPACITY_EXCEEDED`
    (HTTP 409), `ERR_CUSTOMER_CREDIT_HOLD` (HTTP 402), or `ERR_CUSTOMER_SUSPENDED`
    (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/alloy_incompatibility_beats_credit_hold
    """
    customer = create_customer(company_name="Kappa Implants")
    bath = create_titrated_bath(bath_code="ANO-10", routing_modes_supported=["BARREL"])
    # No compatibility rule exists for TI64/ANODIZE/SULFURIC (fail-closed).
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-1000",
                                  alloy_code="TI64"),
        MGR,
    ))
    prepare_work_order(wo["id"])
    # Credit hold is applied only after intake: PRD §3.4 fiscally gates creation,
    # so the hold must arrive via PATCH for the order to exist at all.
    get_success_data(api_client.patch_customer(customer["id"], {"credit_hold": True}, MGR))
    # Safety (tier 8) precedes fiscal (tier 11): ERR_ALLOY_BATH_INCOMPATIBLE wins.
    resp = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_ALLOY_BATH_INCOMPATIBLE)


def test_credit_hold_surfaces_once_alloy_rule_exists():
    """PRD §3.1: "When `credit_hold` is true, routing new work and shipping are blocked
    at the fiscal gate of §2.8 with `ERR_CUSTOMER_CREDIT_HOLD`"
    PRD §3.5: "the alloy compatibility rule for the order's alloy, process, and the
    bath's chemistry family must exist and not be `INCOMPATIBLE` (a missing rule fails
    closed and either case yields `ERR_ALLOY_BATH_INCOMPATIBLE`)"

    Design: Difficulty/priority_pair_validation_conflict/alloy_incompatibility_beats_credit_hold
    """
    customer = create_customer(company_name="Kappa Implants 2")
    bath = create_titrated_bath(bath_code="ANO-10B", routing_modes_supported=["BARREL"])
    wo = get_success_data(api_client.create_work_order(
        create_work_order_payload(customer_id=customer["id"], part_number="PN-1001",
                                  alloy_code="TI64"),
        MGR,
    ))
    prepare_work_order(wo["id"])
    # Credit hold arrives via PATCH after intake (creation is fiscally gated, §3.4).
    get_success_data(api_client.patch_customer(customer["id"], {"credit_hold": True}, MGR))
    resp1 = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp1, ApiErrorId.ERR_ALLOY_BATH_INCOMPATIBLE)
    # With the rule in place, the fiscal failure is independently live.
    create_compat_rule(alloy_code="TI64", process_type="ANODIZE",
                       chemistry_family="SULFURIC", compatibility="COMPATIBLE")
    resp2 = api_client.route_work_order(
        wo["id"],
        {"bath_id": bath["id"], "planned_duration_minutes": 40,
         "planned_current_density_a_dm2": 1.5},
        OP,
    )
    validate_error(resp2, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD)


def _setup_two_rack_orders_one_fixture():
    """Two baths, one shared RACK fixture, two ROUTED orders; clock at 2026-08-10."""
    customer = create_customer(company_name="Omicron Bikes")
    create_compat_rule()
    fixture = create_fixture(fixture_code="RACK-17", routing_mode="RACK", capacity_dm2=500,
                             purchase_cost_cents=120000, rated_uses=50)
    bath_a = create_titrated_bath(bath_code="ANO-17A", routing_modes_supported=["RACK"])
    bath_b = create_titrated_bath(bath_code="ANO-17B", routing_modes_supported=["RACK"])
    # Clock set in the canonical three-fractional-digit form of §2.2/§2.4 so the
    # started_at/ended_at string equality below holds for any PRD-faithful serializer.
    set_clock("2026-08-10T00:00:00.000Z")
    wa = setup_routed_order(customer["id"], bath_a["id"], fixture_id=fixture["id"],
                            part_number="PN-170A", routing_mode="RACK",
                            planned_duration_minutes=60, planned_current_density_a_dm2=1.0)
    wb = setup_routed_order(customer["id"], bath_b["id"], fixture_id=fixture["id"],
                            part_number="PN-170B", routing_mode="RACK",
                            planned_duration_minutes=60, planned_current_density_a_dm2=1.0)
    return bath_a, bath_b, fixture, wa, wb


def test_fixture_occupied_while_running():
    """PRD §3.5: "for rack work no other `RUNNING` load may reference the same fixture
    (else `ERR_FIXTURE_OCCUPIED`)"

    Design: Difficulty/resource_temporal_overlap/fixture_half_open_occupancy
    """
    bath_a, bath_b, _fixture, wa, wb = _setup_two_rack_orders_one_fixture()
    lr_a = start_load_run(wa["id"], bath_id=bath_a["id"], duration_minutes=60,
                          current_density_a_dm2=1.0)
    assert lr_a["started_at"] == "2026-08-10T00:00:00.000Z"
    resp = api_client.start_load_run(
        wb["id"],
        {"duration_minutes": 60, "current_density_a_dm2": 1.0,
         "expected_bath_version": get_bath_version(bath_b["id"])},
        OP,
    )
    validate_error(resp, ApiErrorId.ERR_FIXTURE_OCCUPIED)


def test_fixture_half_open_boundary_allows_adjacent_start():
    """PRD §3.5: "fixture occupation follows a half-open interval from a load's
    `started_at` up to but not including its `ended_at`, so a load starting at the
    exact instant the previous load ended is allowed"

    Design: Difficulty/resource_temporal_overlap/fixture_half_open_occupancy
    """
    bath_a, bath_b, _fixture, wa, wb = _setup_two_rack_orders_one_fixture()
    lr_a = start_load_run(wa["id"], bath_id=bath_a["id"], duration_minutes=60,
                          current_density_a_dm2=1.0)
    set_clock("2026-08-10T01:00:00.000Z")
    completed = complete_load_run(lr_a["id"])
    assert completed["ended_at"] == "2026-08-10T01:00:00.000Z"
    # Start at exactly the previous load's ended_at: allowed (half-open).
    lr_b = start_load_run(wb["id"], bath_id=bath_b["id"], duration_minutes=60,
                          current_density_a_dm2=1.0)
    assert lr_b["status"] == "RUNNING"
    assert lr_b["started_at"] == "2026-08-10T01:00:00.000Z"


def test_permit_closed_window_boundary_overlap_rejected():
    """PRD §3.8: "Two permits for the same outfall may not overlap: the windows are
    closed on both ends, so sharing even a single boundary date counts as overlap and
    the creation is rejected with `ERR_PERMIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/permit_closed_window_overlap
    """
    create_permit(outfall_code="OUTFALL-X", effective_from="2026-08-01",
                  effective_to="2026-08-31")
    # Sharing the boundary date 2026-08-31 counts as overlap (closed-closed).
    resp = api_client.create_discharge_permit(
        create_discharge_permit_payload(outfall_code="OUTFALL-X",
                                        effective_from="2026-08-31",
                                        effective_to="2026-09-30"),
        EHS,
    )
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_OVERLAP)


def test_permit_disjoint_window_and_other_outfall_accepted():
    """PRD §3.8: "Two permits for the same outfall may not overlap: the windows are
    closed on both ends, so sharing even a single boundary date counts as overlap and
    the creation is rejected with `ERR_PERMIT_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/permit_closed_window_overlap
    """
    create_permit(outfall_code="OUTFALL-X", effective_from="2026-08-01",
                  effective_to="2026-08-31")
    # First disjoint day after the window: accepted.
    resp = api_client.create_discharge_permit(
        create_discharge_permit_payload(outfall_code="OUTFALL-X",
                                        effective_from="2026-09-01",
                                        effective_to="2026-09-30"),
        EHS,
    )
    validate_success(resp, expected_status=201)
    # Fully overlapping dates on a DIFFERENT outfall: accepted (overlap is per-outfall).
    resp2 = api_client.create_discharge_permit(
        create_discharge_permit_payload(
            outfall_code="OUTFALL-Y", effective_from="2026-08-15",
            effective_to="2026-09-15",
            limits=[{"analyte_code": "ZINC", "max_concentration_mg_l": 3.0,
                     "monthly_mass_cap_g": 400.0}],
        ),
        EHS,
    )
    validate_success(resp2, expected_status=201)


def test_amp_hour_ledger_invariant_across_abort_and_complete():
    """PRD §3.3: "`amp_hour_used` is the sum of `amp_hours_consumed` over the bath's
    `COMPLETED` load runs — the irrevocable spend. `amp_hour_reserved` is the sum of
    `estimated_amp_hours` over the bath's `RUNNING` load runs — the
    committed-but-unspent reserve. Aborted runs contribute to neither account: an abort
    releases its reservation and leaves `amp_hour_used` untouched, and these two
    identities hold as invariants at every instant."

    Design: Difficulty/compensating_invariant/amp_hour_ledger_invariant
    """
    customer = create_customer(company_name="Pi Hobbies")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-18", routing_modes_supported=["BARREL"], amp_hour_capacity=540,
    )
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-1800",
                            part_count=10, surface_area_dm2_per_part=1.0,
                            planned_duration_minutes=540,
                            planned_current_density_a_dm2=1.0)
    # 10 dm2 x 1.0 x 540 / 60 = 90.0 Ah
    lr = start_load_run(wo["id"], bath_id=bath["id"], duration_minutes=540,
                        current_density_a_dm2=1.0)
    assert lr["estimated_amp_hours"] == 90.0
    detail = get_bath(bath["id"])
    assert detail["amp_hour_reserved"] == 90.0
    assert detail["amp_hour_used"] == 0
    # Abort (the compensating action): zero drift.
    abort_load_run(lr["id"])
    detail = get_bath(bath["id"])
    assert detail["amp_hour_reserved"] == 0
    assert detail["amp_hour_used"] == 0
    assert detail["active_load_run_id"] is None
    assert get_work_order(wo["id"])["status"] == "ROUTED"


def test_amp_hour_ledger_invariant_after_restart_and_complete():
    """PRD §3.5: "Completing the run — allowed only while the load is `RUNNING`, else
    `ERR_LOAD_RUN_NOT_RUNNING` — moves it to `COMPLETED`, sets `amp_hours_consumed`
    equal to the estimate, stamps `ended_at` from the logical clock"
    PRD §3.3: "`amp_hour_used` is the sum of `amp_hours_consumed` over the bath's
    `COMPLETED` load runs — the irrevocable spend."

    Design: Difficulty/compensating_invariant/amp_hour_ledger_invariant
    """
    customer = create_customer(company_name="Pi Hobbies 2")
    create_compat_rule()
    bath = create_titrated_bath(
        bath_code="ANO-18B", routing_modes_supported=["BARREL"], amp_hour_capacity=540,
    )
    wo = setup_routed_order(customer["id"], bath["id"], part_number="PN-1801",
                            part_count=10, surface_area_dm2_per_part=1.0,
                            planned_duration_minutes=540,
                            planned_current_density_a_dm2=1.0)
    lr1 = start_load_run(wo["id"], bath_id=bath["id"], duration_minutes=540,
                         current_density_a_dm2=1.0)
    abort_load_run(lr1["id"])
    lr2 = start_load_run(wo["id"], bath_id=bath["id"], duration_minutes=540,
                         current_density_a_dm2=1.0)
    complete_load_run(lr2["id"])
    detail = get_bath(bath["id"])
    assert detail["amp_hour_reserved"] == 0
    assert detail["amp_hour_used"] == 90.0
    # The aborted run contributes nothing: one ABORTED (null consumed), one COMPLETED.
    runs, _meta = validate_paginated(
        api_client.list_work_order_load_runs(wo["id"], OP)
    )
    by_status = {r["status"]: r for r in runs}
    assert len(runs) == 2
    assert by_status["ABORTED"]["amp_hours_consumed"] is None
    assert by_status["COMPLETED"]["amp_hours_consumed"] == 90.0
