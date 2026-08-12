"""Temporal overlap rules, idempotent vend, OCC (PRD §2.8, §2.9, §3.5, §3.6, §3.7)."""
from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import (
    ADMIN,
    ANY,
    ApiErrorId,
    FINANCE,
    TECH,
    create_chargeback_batch_payload,
    create_contract_price_payload,
    create_issuance_payload,
    create_manager_override_payload,
    create_service_ticket_payload,
    create_slot_payload,
    grant_override,
    open_batch,
    setup_cost_center,
    setup_employee,
    setup_item,
    setup_job_role,
    setup_machine,
    setup_machine_with_slot,
    setup_manager,
    setup_slot_for_machine,
    setup_vend_scenario,
    stock_slot,
    vend,
    vend_ok,
)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / service_window_half_open_adjacency
# ---------------------------------------------------------------------------


def test_service_window_adjacent_allowed(api):
    """PRD §3.6: "For the same machine, no other ticket in `OPEN` or
    `IN_PROGRESS` may intersect that half-open window — intersection fails
    with `ERR_SERVICE_WINDOW_OVERLAP` — while pure adjacency, one ticket's
    `window_end` equal to another's `window_start`, is allowed."

    Design: Difficulty/resource_temporal_overlap/service_window_half_open_adjacency
    """
    machine = setup_machine(location_code="LOC-SW1", site_name="P16", model="VM-500")
    t1 = get_success_data(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="PREVENTIVE",
                window_start="2026-05-10T08:00:00Z",
                window_end="2026-05-10T12:00:00Z",
            ),
            TECH,
        )
    )
    # Adjacent: starts exactly at T1's window_end.
    t2 = validate_success(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="JAM",
                window_start="2026-05-10T12:00:00Z",
                window_end="2026-05-10T16:00:00Z",
            ),
            TECH,
        ),
        201,
    )
    assert t2["status"] == "OPEN"

    rows = get_success_data(
        api.list_service_tickets(ANY, params={"machine_id": machine["id"]})
    )
    assert len(rows) == 2


def test_service_window_intersecting_rejected(api):
    """PRD §3.6: "For the same machine, no other ticket in `OPEN` or
    `IN_PROGRESS` may intersect that half-open window — intersection fails
    with `ERR_SERVICE_WINDOW_OVERLAP`".

    Design: Difficulty/resource_temporal_overlap/service_window_half_open_adjacency
    """
    machine = setup_machine(location_code="LOC-SW1", site_name="P16", model="VM-500")
    get_success_data(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="PREVENTIVE",
                window_start="2026-05-10T08:00:00Z",
                window_end="2026-05-10T12:00:00Z",
            ),
            TECH,
        )
    )
    resp = api.create_service_ticket(
        create_service_ticket_payload(
            machine_id=machine["id"], issue_code="NETWORK",
            window_start="2026-05-10T11:00:00Z",
            window_end="2026-05-10T13:00:00Z",
        ),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_SERVICE_WINDOW_OVERLAP)


# ---------------------------------------------------------------------------
# Queue A: resource_temporal_overlap / override_window_closed_gap_required
# ---------------------------------------------------------------------------


def _setup_override_gap_scenario():
    cc = setup_cost_center(code="CC-GO1", name="Machining")
    role = setup_job_role(role_name="MACHINIST-GO")
    item = setup_item(sku="GAP-O", base_list_price_cents=300)
    emp, _ = setup_employee(role["id"], cc["id"], employee_code="E-GO1",
                            full_name="Machinist Two")
    mgr, mgr_headers = setup_manager(role["id"], cc["id"], employee_code="M-GO1",
                                     full_name="Mgr GO")
    ov1 = grant_override(mgr_headers, employee_id=emp["id"], item_id=item["id"],
                         approved_qty=2, valid_from="2026-05-10",
                         valid_until="2026-05-20", reason_code="PROJECT")
    return {"cc": cc, "role": role, "item": item, "employee": emp,
            "manager": mgr, "manager_headers": mgr_headers, "ov1": ov1}


def test_override_window_one_day_after_valid_until_rejected(api):
    """PRD §3.5: "Against every other `ACTIVE` override for the pair, the
    new closed interval must leave at least one full calendar day of
    separation: the new `valid_from` must fall at least two calendar days
    after the existing window's `valid_until`, or the new `valid_until`
    must fall at least two calendar days before the existing window's
    `valid_from`. A closer window is rejected with
    `ERR_OVERRIDE_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/override_window_closed_gap_required
    """
    fx = _setup_override_gap_scenario()
    resp = api.create_manager_override(
        create_manager_override_payload(
            employee_id=fx["employee"]["id"], item_id=fx["item"]["id"],
            approved_qty=2, valid_from="2026-05-21", valid_until="2026-05-25",
            reason_code="PROJECT",
        ),
        fx["manager_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_OVERRIDE_WINDOW_OVERLAP)


def test_override_window_two_days_after_valid_until_accepted(api):
    """PRD §3.5: "the new `valid_from` must fall at least two calendar days
    after the existing window's `valid_until`".

    Design: Difficulty/resource_temporal_overlap/override_window_closed_gap_required
    """
    fx = _setup_override_gap_scenario()
    validate_error(
        api.create_manager_override(
            create_manager_override_payload(
                employee_id=fx["employee"]["id"], item_id=fx["item"]["id"],
                approved_qty=2, valid_from="2026-05-21", valid_until="2026-05-25",
                reason_code="PROJECT",
            ),
            fx["manager_headers"],
        ),
        ApiErrorId.ERR_OVERRIDE_WINDOW_OVERLAP,
    )
    ok = validate_success(
        api.create_manager_override(
            create_manager_override_payload(
                employee_id=fx["employee"]["id"], item_id=fx["item"]["id"],
                approved_qty=2, valid_from="2026-05-22", valid_until="2026-05-26",
                reason_code="INCIDENT",
            ),
            fx["manager_headers"],
        ),
        201,
    )
    assert ok["status"] == "ACTIVE"
    rows = get_success_data(
        api.list_manager_overrides(
            ANY, params={"employee_id": fx["employee"]["id"], "status": "ACTIVE"}
        )
    )
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Queue B: endpoints / issuance_idempotent_replay_same_result
# ---------------------------------------------------------------------------


def test_issuance_idempotent_replay_same_result(api):
    """PRD §2.9: "an identical payload returns the original transaction with
    a 201 status (a replay, not a second vend)".

    Design: Corner/endpoints/issuance_idempotent_replay_same_result
    """
    sc = setup_vend_scenario(sku="EP-ID", base_price=100, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    first = validate_success(
        api.create_issuance(
            create_issuance_payload(
                machine_id=sc["machine"]["id"], slot_id=sc["slot"]["id"], qty=2,
                idempotency_key="ei-same",
            ),
            sc["employee_headers"],
        ),
        201,
    )
    replay = validate_success(
        api.create_issuance(
            create_issuance_payload(
                machine_id=sc["machine"]["id"], slot_id=sc["slot"]["id"], qty=2,
                idempotency_key="ei-same",
            ),
            sc["employee_headers"],
        ),
        201,
    )
    assert replay["id"] == first["id"], "replay returns the original transaction"
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 8, "decremented exactly once"


def test_idempotency_key_reuse_with_different_payload_rejected(api):
    """PRD §2.9: "a difference in any other field is rejected with
    `ERR_IDEMPOTENCY_CONFLICT` (409)".

    Design: Corner/endpoints/idempotency_key_reuse_with_different_payload_rejected
    """
    sc = setup_vend_scenario(sku="EP-IC", base_price=100, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=2,
            idempotency_key="ec-key")
    resp = api.create_issuance(
        create_issuance_payload(
            machine_id=sc["machine"]["id"], slot_id=sc["slot"]["id"], qty=3,
            idempotency_key="ec-key",
        ),
        sc["employee_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_IDEMPOTENCY_CONFLICT)
    slot_now = get_success_data(api.get_slot(sc["slot"]["id"], ANY))
    assert slot_now["on_hand_qty"] == 8


# ---------------------------------------------------------------------------
# Queue B: endpoints / list_endpoints_filter_and_paginate
# ---------------------------------------------------------------------------


def test_list_endpoints_filter_and_paginate(api):
    """PRD §2.3: "List responses carry `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the response envelope."
    PRD §3.4: "The issuance ledger can be read back filtered by any
    combination of `employee_id`, `machine_id`, `slot_id`, `item_id`,
    `cost_center_id`, `manager_override_id`, `serialized_unit_id`,
    `chargeback_batch_id`, or `status`."

    Design: Corner/endpoints/list_endpoints_filter_and_paginate
    """
    sc = setup_vend_scenario(sku="EP-LP", base_price=100, period_limit_qty=10,
                             period_window_days=30, capacity=20, par_level=0,
                             initial_stock=10)
    # Add a second employee in the same cost center.
    emp_b, emp_b_headers = setup_employee(sc["job_role"]["id"],
                                          sc["cost_center"]["id"],
                                          employee_code="E-EP4B",
                                          full_name="Tech LB")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="lp-a1")
    vend_ok(sc["employee_headers"], sc["machine"], sc["slot"], qty=1,
            idempotency_key="lp-a2")
    vend_ok(emp_b_headers, sc["machine"], sc["slot"], qty=1,
            idempotency_key="lp-b1")

    # Filter by employee A with limit=1: has_more true, total_count 2.
    resp = api.list_issuances(
        ANY, params={"employee_id": sc["employee"]["id"], "limit": 1, "offset": 0}
    )
    body = resp.json()
    assert body["meta"]["has_more"] is True
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["limit"] == 1
    data = body["data"]
    assert len(data) == 1
    assert data[0]["employee_id"] == sc["employee"]["id"]

    # Unfiltered list for employee A contains both rows, none of B.
    rows = get_success_data(
        api.list_issuances(ANY, params={"employee_id": sc["employee"]["id"]})
    )
    assert len(rows) == 2
    assert all(r["employee_id"] == sc["employee"]["id"] for r in rows)


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers / occ_slot_create_stale_machine_version
# ---------------------------------------------------------------------------


def test_occ_slot_create_stale_machine_version(api):
    """PRD §2.8: "`POST /machines/{machineId}/slots` — creating a planogram
    slot — requires the request to carry `expected_machine_version` as a
    non-optional field, equal to the parent machine's current `version`; if
    another write — commissioning, an offline toggle, a service start, or
    an earlier slot create — has advanced the machine since the client last
    read it, the caller's planogram view is stale and the create is
    rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_slot_create_stale_machine_version
    """
    item = setup_item(sku="OCC-C", base_list_price_cents=100)
    machine = setup_machine(location_code="LOC-OC1", site_name="P32", model="VM-1")
    captured_v = machine["version"]

    # First create succeeds with captured version.
    s1 = validate_success(
        api.create_slot(
            machine["id"],
            create_slot_payload(slot_code="A1", item_id=item["id"], capacity=10,
                                par_level=0,
                                expected_machine_version=captured_v),
            TECH,
        ),
        201,
    )

    # Second create with the same captured (now stale) version fails.
    resp = api.create_slot(
        machine["id"],
        create_slot_payload(slot_code="A2", item_id=item["id"], capacity=10,
                            par_level=0,
                            expected_machine_version=captured_v),
        TECH,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    m = get_success_data(api.get_machine(machine["id"], ANY))
    assert m["version"] == captured_v + 1


# ---------------------------------------------------------------------------
# Queue B: cross_cutting_layers / occ_slot_update_stale_slot_version
# ---------------------------------------------------------------------------


def test_occ_slot_update_stale_slot_version(api):
    """PRD §2.8: "`PUT /slots/{slotId}` — updating a planogram slot (an item
    swap, a capacity change, or a par-level change) — likewise requires
    `expected_slot_version` as a non-optional field matching the slot's
    current `version`; a prior planogram edit that has already superseded
    the caller's view produces the same `ERR_STALE_VERSION` (412)
    rejection."

    Design: Corner/cross_cutting_layers/occ_slot_update_stale_slot_version
    """
    item = setup_item(sku="OCC-U", base_list_price_cents=100)
    machine = setup_machine(location_code="LOC-OC2", site_name="P33", model="VM-1")
    slot = setup_slot_for_machine(machine, item_id=item["id"], capacity=10,
                                  par_level=2, slot_code="A1")
    captured_v = slot["version"]

    ok = validate_success(
        api.update_slot(slot["id"],
                        {"par_level": 3, "expected_slot_version": captured_v},
                        TECH),
        200,
    )
    assert ok["par_level"] == 3
    assert ok["version"] == captured_v + 1

    # Stale: same version on second PUT.
    resp = api.update_slot(slot["id"],
                           {"par_level": 4, "expected_slot_version": captured_v},
                           TECH)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    final = get_success_data(api.get_slot(slot["id"], ANY))
    assert final["par_level"] == 3, "failed write left no drift"


# ---------------------------------------------------------------------------
# Queue B: errors / error_batch_period_overlap_rejected
# ---------------------------------------------------------------------------


def test_batch_period_overlap_rejected_and_adjacent_allowed(api):
    """PRD §3.7: "Periods for the same cost center must not overlap under
    half-open comparison — `ERR_BATCH_PERIOD_OVERLAP` — while adjacency,
    one batch's `period_end` equal to the next's `period_start`, is
    allowed."

    Design: Corner/errors/error_batch_period_overlap_rejected
    """
    cc = setup_cost_center(code="CC-ER1", name="Ops")
    open_batch(cc["id"], period_start="2026-05-01", period_end="2026-06-01")

    # Overlap: [2026-05-15, 2026-06-15) intersects existing.
    resp = api.create_chargeback_batch(
        create_chargeback_batch_payload(
            cost_center_id=cc["id"], period_start="2026-05-15",
            period_end="2026-06-15",
        ),
        FINANCE,
    )
    validate_error(resp, ApiErrorId.ERR_BATCH_PERIOD_OVERLAP)

    # Adjacent: [2026-06-01, 2026-07-01) is allowed.
    ok = validate_success(
        api.create_chargeback_batch(
            create_chargeback_batch_payload(
                cost_center_id=cc["id"], period_start="2026-06-01",
                period_end="2026-07-01",
            ),
            FINANCE,
        ),
        201,
    )
    assert ok["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue B: errors / error_empty_chargeback_close_rejected
# ---------------------------------------------------------------------------


def test_empty_chargeback_close_rejected(api):
    """PRD §3.7: "the close is refused with `ERR_EMPTY_CHARGEBACK_BATCH`
    unless the sweep set is non-empty or `adjustment_cents` is non-zero."

    Design: Corner/errors/error_empty_chargeback_close_rejected
    """
    cc = setup_cost_center(code="CC-ER2", name="Ops")
    batch = open_batch(cc["id"])
    resp = api.close_chargeback_batch(batch["id"], FINANCE)
    validate_error(resp, ApiErrorId.ERR_EMPTY_CHARGEBACK_BATCH)
    now = get_success_data(api.get_chargeback_batch(batch["id"], ANY))
    assert now["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Queue B: errors / error_duplicate_employee_code_rejected
# ---------------------------------------------------------------------------


def test_duplicate_employee_code_rejected(api):
    """PRD §3.2: "An `EHSAdministrator` creates each employee with a unique
    `employee_code` (duplicates fail with `ERR_DUPLICATE_EMPLOYEE_CODE`)".

    Design: Corner/errors/error_duplicate_employee_code_rejected
    """
    from test_helpers import create_employee_payload as _mk_emp
    cc = setup_cost_center(code="CC-ER3", name="Ops")
    role = setup_job_role(role_name="TECH-ED")
    setup_employee(role["id"], cc["id"], employee_code="E-DUP", full_name="First")
    resp = api.create_employee(
        _mk_emp(employee_code="E-DUP", full_name="Second",
                job_role_id=role["id"], home_cost_center_id=cc["id"]),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_CODE)


# ---------------------------------------------------------------------------
# Queue B: errors / error_service_start_before_window_rejected
# ---------------------------------------------------------------------------


def test_service_start_before_window_rejected(api):
    """PRD §3.6: "the logical clock must fall within the half-open window —
    on or after `window_start` and before `window_end`, otherwise
    `ERR_SERVICE_WINDOW_NOT_REACHED`".

    Design: Corner/errors/error_service_start_before_window_rejected
    """
    item = setup_item(sku="ER-SW", base_list_price_cents=100)
    machine, _slot = setup_machine_with_slot(item["id"], capacity=10, par_level=0)
    ticket = get_success_data(
        api.create_service_ticket(
            create_service_ticket_payload(
                machine_id=machine["id"], issue_code="PREVENTIVE",
                window_start="2026-05-10T08:00:00Z",
                window_end="2026-05-10T12:00:00Z",
            ),
            TECH,
        )
    )
    resp = api.start_service_ticket(ticket["id"], TECH)
    validate_error(resp, ApiErrorId.ERR_SERVICE_WINDOW_NOT_REACHED)
    t_now = get_success_data(api.get_service_ticket(ticket["id"], ANY))
    assert t_now["status"] == "OPEN"
    m_now = get_success_data(api.get_machine(machine["id"], ANY))
    assert m_now["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Queue B: errors / error_contract_price_window_conflict_rejected
# ---------------------------------------------------------------------------


def test_contract_price_window_conflict_closed_interval(api):
    """PRD §3.1: "Windows for the same item must not intersect under
    closed-interval comparison — a new row whose window touches any
    existing row's window for the same item is rejected with
    `ERR_CONTRACT_PRICE_WINDOW_CONFLICT` — while gaps between windows are
    perfectly legal."

    Design: Corner/errors/error_contract_price_window_conflict_rejected
    """
    item = setup_item(sku="ER-CP", base_list_price_cents=100)
    get_success_data(
        api.create_contract_price(
            create_contract_price_payload(
                item_id=item["id"], min_period_qty=0, unit_price_cents=90,
                effective_from="2026-01-01", effective_to="2026-06-30",
            ),
            ADMIN,
        )
    )
    # Closed-interval touch: effective_from == prior effective_to is overlap.
    resp = api.create_contract_price(
        create_contract_price_payload(
            item_id=item["id"], min_period_qty=0, unit_price_cents=95,
            effective_from="2026-06-30", effective_to="2026-12-31",
        ),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_PRICE_WINDOW_CONFLICT)

    # Gap by one day is accepted.
    ok = validate_success(
        api.create_contract_price(
            create_contract_price_payload(
                item_id=item["id"], min_period_qty=0, unit_price_cents=95,
                effective_from="2026-07-01", effective_to="2026-12-31",
            ),
            ADMIN,
        ),
        201,
    )
    assert ok["item_id"] == item["id"]
