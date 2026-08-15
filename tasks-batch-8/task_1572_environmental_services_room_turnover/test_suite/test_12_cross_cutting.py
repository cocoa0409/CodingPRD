"""Cross-cutting claims: OCC rules, threshold triggers, selector policy,
ops-run epoch bookkeeping, immediate consistency."""
from test_helpers import (
    assert_instant_equal,
    ApiErrorId,
    CLOCK_T0800,
    api_client,
    create_clean_request_payload,
    get_success_data,
    make_technician_headers,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)
from test_helpers.fixtures import (
    create_bed,
    create_request,
    create_standard,
    create_technician,
    create_unit,
)

ADMIN = TEST_USERS["admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


def test_occ_reassign_accepts_current_rejects_stale(api):
    """PRD §2.7: "Reassigning a clean request requires
    `expected_clean_request_version` matching the request's current `version`.
    ... if another writer has advanced the request's version since the client
    last read it, the reassign is rejected with `ERR_STALE_REQUEST_VERSION`
    (HTTP 412), preventing the client from overwriting an assignment it has not
    observed."

    Design: Corner/cross_cutting_layers/occ_reassign_accepts_current_rejects_stale
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    t1 = create_technician("T1")
    t2 = create_technician("T2")
    bed = create_bed(unit["id"])
    req = create_request(bed["id"], "ROUTINE")

    assigned = get_success_data(
        api.assign_clean_request(req["id"], {"staff_id": t1["id"]}, DISPATCHER)
    )
    v_after_assign = assigned["version"]
    assert v_after_assign == 2

    moved = get_success_data(
        api.reassign_clean_request(
            req["id"],
            {"staff_id": t2["id"], "expected_clean_request_version": v_after_assign},
            DISPATCHER,
        )
    )
    assert moved["assigned_staff_id"] == t2["id"]
    assert moved["version"] == 3

    replay = api.reassign_clean_request(
        req["id"],
        {"staff_id": t1["id"], "expected_clean_request_version": v_after_assign},
        DISPATCHER,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_REQUEST_VERSION)

    after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert after["assigned_staff_id"] == t2["id"]
    assert after["version"] == 3

    t1_after = get_success_data(api.get_staff(t1["id"], ANY))
    assert t1_after["active_clean_count"] == 0
    t2_after = get_success_data(api.get_staff(t2["id"], ANY))
    assert t2_after["active_clean_count"] == 1


def test_occ_recount_accepts_current_rejects_stale(api):
    """PRD §2.7: "Recounting a supply item requires
    `expected_supply_item_version` matching the item's current `version`. ...
    restocks, consumptions, and earlier recounts all advance that version, so a
    recount submitted against a superseded version is rejected with
    `ERR_STALE_SUPPLY_VERSION` (HTTP 412) even though the same recount with a
    fresh version would succeed."
    PRD §3.1: "a physical recount asserts a `counted_on_hand` and, guarded by
    `expected_supply_item_version` per §2.7, writes a `RECOUNT_ADJUSTMENT`
    entry whose delta is the counted value minus the current
    `on_hand_quantity`."

    Design: Corner/cross_cutting_layers/occ_recount_accepts_current_rejects_stale
    """
    set_clock(CLOCK_T0800)
    item = get_success_data(
        api.create_supply_item(
            {
                "item_code": "DISINFECTANT",
                "display_name": "Disinfectant",
                "initial_on_hand": 100,
                "reorder_threshold": 10,
            },
            ADMIN,
        )
    )
    v1 = item["version"]
    restocked = get_success_data(
        api.restock_supply_item(item["id"], {"quantity": 10}, ADMIN)
    )
    v2 = restocked["version"]
    assert restocked["on_hand_quantity"] == 110

    stale = api.recount_supply_item(
        item["id"],
        {"counted_on_hand": 105, "expected_supply_item_version": v1},
        ADMIN,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_SUPPLY_VERSION)

    fresh = get_success_data(
        api.recount_supply_item(
            item["id"],
            {"counted_on_hand": 105, "expected_supply_item_version": v2},
            ADMIN,
        )
    )
    assert fresh["on_hand_quantity"] == 105
    assert fresh["version"] == 3
    assert fresh["reserved_quantity"] == 0

    entries, meta = validate_paginated(
        api.list_supply_ledger_entries(ANY, params={"supply_item_id": item["id"]})
    )
    assert len(entries) == 3
    total = sum(e["quantity_delta"] for e in entries)
    assert total == 105
    types = sorted(e["entry_type"] for e in entries)
    assert types == ["RECOUNT_ADJUSTMENT", "RESTOCK", "RESTOCK"]


def test_occ_standard_update_version_gate_and_pin_divergence(api):
    """PRD §2.7: "Updating a clean standard requires `expected_standard_version`
    matching the standard row's current `version`. ... an update carrying an
    older version is rejected with `ERR_STALE_STANDARD_VERSION` (HTTP 412)."
    PRD §3.1: "Updating a standard is an OCC-guarded supersede write per §2.7;
    in-flight requests keep their pinned values, and the new row governs only
    future pins and the `current_estimate_minutes` computation."

    Design: Corner/cross_cutting_layers/occ_standard_update_version_gate_and_pin_divergence
    """
    set_clock(CLOCK_T0800)
    std = get_success_data(
        api.create_clean_standard(
            {
                "clean_type": "ROUTINE",
                "base_minutes": 45,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
            },
            ADMIN,
        )
    )
    std_v = std["version"]
    unit = create_unit()
    bed = create_bed(unit["id"])
    req = create_request(bed["id"], "ROUTINE")

    updated = get_success_data(
        api.update_clean_standard(
            "ROUTINE",
            {
                "base_minutes": 50,
                "outbreak_multiplier_bps": 15000,
                "atp_rlu_threshold": 250,
                "expected_standard_version": std_v,
            },
            ADMIN,
        )
    )
    assert updated["version"] == 2

    req_after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert req_after["sla_target_minutes"] == 45
    assert req_after["current_estimate_minutes"] == 50

    replay = api.update_clean_standard(
        "ROUTINE",
        {
            "base_minutes": 55,
            "outbreak_multiplier_bps": 15000,
            "atp_rlu_threshold": 250,
            "expected_standard_version": std_v,
        },
        ADMIN,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_STANDARD_VERSION)

    row = get_success_data(api.get_clean_standard("ROUTINE", ANY))
    assert row["base_minutes"] == 50


def test_low_stock_threshold_boundary(api):
    """PRD §2.9: "an item's `stock_status` reads `LOW` whenever its
    `on_hand_quantity` has fallen to or below its `reorder_threshold`, and
    `STOCKED` otherwise."

    Design: Corner/cross_cutting_layers/low_stock_threshold_boundary
    """
    set_clock(CLOCK_T0800)
    item = get_success_data(
        api.create_supply_item(
            {
                "item_code": "DISINFECTANT",
                "display_name": "Disinfectant",
                "initial_on_hand": 11,
                "reorder_threshold": 10,
            },
            ADMIN,
        )
    )
    assert item["stock_status"] == "STOCKED"
    v1 = item["version"]

    at_threshold = get_success_data(
        api.recount_supply_item(
            item["id"],
            {"counted_on_hand": 10, "expected_supply_item_version": v1},
            ADMIN,
        )
    )
    assert at_threshold["stock_status"] == "LOW"

    restocked = get_success_data(
        api.restock_supply_item(item["id"], {"quantity": 1}, ADMIN)
    )
    assert restocked["on_hand_quantity"] == 11
    assert restocked["stock_status"] == "STOCKED"


def test_pull_selector_orders_by_sla_due_then_created(api):
    """PRD §3.2: "Queue ordering, wherever the system must pick a request, is
    fixed: `priority_tier` rank descending, then `priority_score` descending,
    then `sla_due_at` ascending, then `created_at` ascending. No random or
    identifier-based tie-break appears anywhere in the ordering; the final
    tie-break is creation time."
    PRD §3.4: "the top request becomes `ASSIGNED` to the puller with
    `planned_start_at` set to now."

    Design: Corner/cross_cutting_layers/pull_selector_orders_by_sla_due_then_created
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    t1 = create_technician("T1")
    t2 = create_technician("T2")
    get_success_data(api.clock_in_staff(t1["id"], make_technician_headers(t1["id"])))
    get_success_data(api.clock_in_staff(t2["id"], make_technician_headers(t2["id"])))
    b1 = create_bed(unit["id"], "B1", "STANDARD")
    r1 = create_request(b1["id"], "ROUTINE")

    set_clock("2026-08-01T08:10:00Z")
    b2 = create_bed(unit["id"], "B2", "STANDARD")
    r2 = create_request(b2["id"], "ROUTINE")

    p1 = get_success_data(api.pull_clean_request(make_technician_headers(t1["id"])))
    assert p1["id"] == r1["id"]
    assert_instant_equal(p1["planned_start_at"], "2026-08-01T08:10:00Z")
    assert p1["assigned_staff_id"] == t1["id"]
    assert p1["status"] == "ASSIGNED"

    p2 = get_success_data(api.pull_clean_request(make_technician_headers(t2["id"])))
    assert p2["id"] == r2["id"]
    assert p2["assigned_staff_id"] == t2["id"]


def test_pull_selector_filters_certification_and_shift_state(api):
    """PRD §3.4: "The puller must be `ON_SHIFT`, and this is verified before
    selection runs (`ERR_STAFF_NOT_ON_SHIFT`). Eligibility then filters the
    queue: the request's `clean_type` must be covered by the puller's
    certifications, a `STAT`-tier request is invisible to a puller whose
    `stat_eligible` is false. ... When no request is eligible, the pull is
    rejected with `ERR_QUEUE_EMPTY`."

    Design: Corner/cross_cutting_layers/pull_selector_filters_certification_and_shift_state
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ISOLATION")
    t1 = create_technician("T1")  # no certs
    t2 = create_technician("T2", certifications=["ISO_CERT"])  # stays OFF_SHIFT
    get_success_data(api.clock_in_staff(t1["id"], make_technician_headers(t1["id"])))
    bi1 = create_bed(unit["id"], "BI1", "ISOLATION")
    req = create_request(bi1["id"], "ISOLATION")

    r_pool = api.pull_clean_request(make_technician_headers(t1["id"]))
    validate_error(r_pool, ApiErrorId.ERR_QUEUE_EMPTY)

    r_shift = api.pull_clean_request(make_technician_headers(t2["id"]))
    validate_error(r_shift, ApiErrorId.ERR_STAFF_NOT_ON_SHIFT)

    after = get_success_data(api.get_clean_request(req["id"], ANY))
    assert after["status"] == "QUEUED"
    assert after["assigned_staff_id"] is None


def test_unit_version_and_ops_run_index_increment_per_run(api):
    """PRD §3.1: "Each unit also carries an `ops_run_index`, a monotonic
    ops-run epoch that starts at 0 and increments by 1 on each ops-run executed
    for the unit."
    PRD §3.9: "the snapshot records those bounds as `window_start` and
    `window_end`, along with the unit's `ops_run_index` value *before* this run
    incremented it. Completing the run increments the unit's `ops_run_index`
    by one (and with it the unit's `version`)."

    Design: Corner/cross_cutting_layers/unit_version_and_ops_run_index_increment_per_run
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    assert unit["version"] == 1
    assert unit["ops_run_index"] == 0

    s1 = get_success_data(api.run_ops_run(unit["id"], ADMIN))
    assert s1["ops_run_index"] == 0
    u1 = get_success_data(api.get_unit(unit["id"], ANY))
    assert u1["ops_run_index"] == 1
    assert u1["version"] == 2

    s2 = get_success_data(api.run_ops_run(unit["id"], ADMIN))
    assert s2["ops_run_index"] == 1
    u2 = get_success_data(api.get_unit(unit["id"], ANY))
    assert u2["ops_run_index"] == 2
    assert u2["version"] == 3

    snaps, meta = validate_paginated(api.list_turnaround_snapshots(unit["id"], ANY))
    assert len(snaps) == 2


def test_immediate_visibility_after_mutation(api):
    """PRD §2.6: "the system keeps them aligned without waiting for client
    calls on each one."
    PRD §3.3: "The request denormalizes a `unit_id` copied from its bed at
    creation so the queue can be filtered per unit."
    PRD §3.4: "A successful assignment stamps `assigned_staff_id`, sets the
    planned window, raises the staff member's derived `active_clean_count` —
    the count of their requests in `ASSIGNED` or `IN_PROGRESS` — by one."

    Design: Corner/consistency_model/immediate_visibility_after_mutation
    """
    set_clock(CLOCK_T0800)
    unit = create_unit()
    create_standard("ROUTINE")
    tech = create_technician("T1")
    bed = create_bed(unit["id"])

    req = get_success_data(
        api.create_clean_request(
            create_clean_request_payload(bed_id=bed["id"]), DISPATCHER
        )
    )
    assert req["unit_id"] == unit["id"]
    assert_instant_equal(req["sla_due_at"], "2026-08-01T08:45:00Z")

    assigned = get_success_data(
        api.assign_clean_request(req["id"], {"staff_id": tech["id"]}, DISPATCHER)
    )
    assert assigned["assigned_staff_id"] == tech["id"]

    staff = get_success_data(api.get_staff(tech["id"], ANY))
    assert staff["active_clean_count"] == 1

    reread = get_success_data(api.get_clean_request(req["id"], ANY))
    assert reread["status"] == "ASSIGNED"
    assert reread["assigned_staff_id"] == tech["id"]

    assert_instant_equal(req["created_at"], CLOCK_T0800)
    assert_instant_equal(reread["created_at"], CLOCK_T0800)
    assert_instant_equal(staff["created_at"], CLOCK_T0800)
