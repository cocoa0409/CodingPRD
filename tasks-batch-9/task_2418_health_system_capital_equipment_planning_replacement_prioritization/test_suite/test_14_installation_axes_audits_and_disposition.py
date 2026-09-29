"""Getting the machine in: two project axes, the go-live join, the audit and the scrapyard."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_cents,
    assert_decimal,
    assert_installation_project,
    assert_instant,
    assert_utilization_audit,
    cancel_project,
    collect_audit,
    collect_audit_payload,
    create_project_payload,
    create_service_event_payload,
    decommission,
    decommission_payload,
    get_success_data,
    make_facility_director_headers,
    make_project,
    refresh_asset,
    refresh_audit,
    refresh_department,
    refresh_facility,
    refresh_project,
    refresh_request,
    setup_commissioned_project,
    setup_estate,
    setup_funded_request,
    setup_project,
    setup_scheduled_audit,
    validate_error,
    validate_success,
)

CLOCK = "2026-08-01T00:00:00Z"
_PLANNER = TEST_USERS["planner_headers"]
_AUDITOR = TEST_USERS["auditor_headers"]


def _funded_request_at_a_single_construction_slot():
    """A FUNDED request at NRH, whose director may now open installation projects."""
    ctx = setup_funded_request()
    ctx["director"] = make_facility_director_headers(ctx["facility"]["id"])
    return ctx


def _two_projects_chained_on_one_request():
    """P1 and P2 on the same request, P2 naming P1 as its predecessor and already commissioned."""
    ctx = _funded_request_at_a_single_construction_slot()
    ctx["first_project"] = make_project(
        ctx["request"]["id"], ctx["facility"]["id"],
        downtime_start="2026-09-01T00:00:00Z", downtime_end="2026-09-02T00:00:00Z",
    )
    ctx["second_project"] = make_project(
        ctx["request"]["id"], ctx["facility"]["id"],
        downtime_start="2026-09-10T00:00:00Z", downtime_end="2026-09-11T00:00:00Z",
        predecessor_project_id=ctx["first_project"]["id"],
    )
    return ctx


def _project_holding_both_a_downtime_and_a_construction_window():
    """One project at a facility whose concurrency ceiling is exactly one."""
    ctx = _funded_request_at_a_single_construction_slot()
    ctx["project"] = make_project(
        ctx["request"]["id"], ctx["facility"]["id"],
        downtime_start="2026-09-01T00:00:00Z", downtime_end="2026-09-02T00:00:00Z",
        construction_required=True, construction_start="2026-08-10T00:00:00Z",
        construction_end="2026-08-31T00:00:00Z",
    )
    return ctx


def _advance_equipment(api, project_id, director, steps):
    for _ in range(steps):
        validate_success(api.advance_equipment(project_id, director))


# ─── Opening the project ──────────────────────────────────────────────


def test_a_new_project_carries_three_statuses_and_borrows_its_own_scope(api):
    """PRD §3.10: "An installation project is opened by the facility director once the request
    stands in `FUNDED`."
    PRD §3.10: "A new project starts with `record_status` `ACTIVE`, `equipment_status`
    `AWAITING_DELIVERY`, `go_live_at` null, and `construction_status` `DESIGN` when
    `construction_required` is true or `NOT_REQUIRED` when it is false."
    PRD §3.10: "The project's `request_id` comes from the path, and its `facility_id` and
    `department_id` are copied from the request's department at creation — construction capacity
    is evaluated per facility while downtime conflicts are evaluated per department."
    PRD §3.10: "The project carries two independent state dimensions that advance separately."
    PRD §3.9: "On success the request moves `APPROVED → FUNDED`, `funded_amount_cents` is written
    and the request's `version` is incremented; the allocation's `committed_cents` rises by the
    funded amount, `available_cents` is recomputed and the allocation's `version` is incremented;
    and the asset moves from `IN_SERVICE` or `DERATED` to `REPLACEMENT_PENDING` — either
    `IN_SERVICE → REPLACEMENT_PENDING` or `DERATED → REPLACEMENT_PENDING` — with the asset's
    `version` incremented."

    Design: Corner/state_machines/installation_project_is_born_with_two_independent_axes_and_no_go_live
    """
    ctx = _funded_request_at_a_single_construction_slot()

    project = validate_success(
        api.create_installation_project(
            ctx["request"]["id"],
            create_project_payload(
                downtime_start="2026-10-05T00:00:00Z", downtime_end="2026-10-07T00:00:00Z",
                construction_required=True, construction_start="2026-09-01T00:00:00Z",
                construction_end="2026-10-01T00:00:00Z",
            ),
            ctx["director"],
        ),
        201,
    )
    assert_installation_project(project)
    assert project["construction_status"] == "DESIGN"
    assert project["equipment_status"] == "AWAITING_DELIVERY"
    assert project["record_status"] == "ACTIVE"
    assert project["go_live_at"] is None
    assert project["version"] == 1
    assert project["facility_id"] == ctx["facility"]["id"]
    assert project["department_id"] == ctx["department"]["id"]
    assert project["request_id"] == ctx["request"]["id"]

    request = refresh_request(ctx["request"]["id"])
    assert request["status"] == "FUNDED"
    assert_cents(request["funded_amount_cents"], 100000000, "funded_amount_cents")
    assert refresh_asset(ctx["asset"]["id"])["status"] == "REPLACEMENT_PENDING"


def test_three_shape_guards_on_one_project_endpoint_each_name_their_own_fault(api):
    """PRD §3.10: "First, intervals must be well-formed: `downtime_end` must be strictly later
    than `downtime_start` and `construction_end` may not precede `construction_start`, and a
    violation is `ERR_INVALID_INTERVAL`."
    PRD §3.10: "Second, the construction window must be present exactly when it is needed:
    `construction_required` true with either construction bound null, or `construction_required`
    false with either bound supplied, is rejected with `ERR_CONSTRUCTION_WINDOW_REQUIRED`."
    PRD §3.10: "Whenever `predecessor_project_id` is supplied, the server follows predecessor
    links transitively from the incoming value; if that walk reaches the project being written the
    edge would close a cycle and the write is rejected with `ERR_PROJECT_DEPENDENCY_CYCLE`."
    PRD §3.10: "A project may also not name itself as its own predecessor."
    PRD §2.11: "43. An interval whose end does not follow its start, on installation-project
    creation, project patch and audit creation — `ERR_INVALID_INTERVAL`, 422."
    PRD §2.11: "47. A predecessor edge that would close a dependency cycle, on
    installation-project creation and project patch — `ERR_PROJECT_DEPENDENCY_CYCLE`, 422."

    Design: Corner/validations/project_interval_construction_and_self_dependency_guards_each_reject_the_write
    """
    ctx = _funded_request_at_a_single_construction_slot()

    validate_error(
        api.create_installation_project(
            ctx["request"]["id"],
            {"downtime_start": "2026-09-01T00:00:00Z", "downtime_end": "2026-09-01T00:00:00Z"},
            ctx["director"],
        ),
        ApiErrorId.ERR_INVALID_INTERVAL.value, 422,
    )
    validate_error(
        api.create_installation_project(
            ctx["request"]["id"],
            {"downtime_start": "2026-09-01T00:00:00Z", "downtime_end": "2026-09-02T00:00:00Z",
             "construction_required": True},
            ctx["director"],
        ),
        ApiErrorId.ERR_CONSTRUCTION_WINDOW_REQUIRED.value, 422,
    )
    validate_error(
        api.create_installation_project(
            ctx["request"]["id"],
            {"downtime_start": "2026-09-01T00:00:00Z", "downtime_end": "2026-09-02T00:00:00Z",
             "construction_required": False, "construction_start": "2026-08-10T00:00:00Z"},
            ctx["director"],
        ),
        ApiErrorId.ERR_CONSTRUCTION_WINDOW_REQUIRED.value, 422,
    )

    project = validate_success(
        api.create_installation_project(
            ctx["request"]["id"],
            {"downtime_start": "2026-09-01T00:00:00Z", "downtime_end": "2026-09-02T00:00:00Z",
             "construction_required": True, "construction_start": "2026-08-10T00:00:00Z",
             "construction_end": "2026-08-31T00:00:00Z"},
            ctx["director"],
        ),
        201,
    )
    assert project["construction_status"] == "DESIGN"
    assert project["equipment_status"] == "AWAITING_DELIVERY"
    assert project["record_status"] == "ACTIVE"
    assert project["go_live_at"] is None
    assert project["predecessor_project_id"] is None
    assert project["version"] == 1

    validate_error(
        api.patch_installation_project(
            project["id"], {"predecessor_project_id": project["id"]}, ctx["director"]
        ),
        ApiErrorId.ERR_PROJECT_DEPENDENCY_CYCLE.value, 422,
    )
    unmoved = refresh_project(project["id"])
    assert unmoved["version"] == 1
    assert unmoved["predecessor_project_id"] is None

    rows = get_success_data(
        api.list_installation_projects(_PLANNER, params={"request_id": ctx["request"]["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == project["id"]


def test_a_patch_never_collides_with_the_row_it_is_editing(api):
    """PRD §3.10: "The same six inputs are editable afterwards, and turning `construction_required`
    on sets `construction_status` to `DESIGN` while turning it off sets it to `NOT_REQUIRED` and
    clears both construction bounds."
    PRD §3.10: "A conflict exists when some other project with `record_status` `ACTIVE` in the same
    `department_id` — excluding the row being edited — has a `downtime_end` strictly later than the
    incoming start minus twenty-four hours **and** a `downtime_start` strictly earlier than the
    incoming end plus twenty-four hours; the rejection is `ERR_DOWNTIME_WINDOW_CONFLICT`."
    PRD §3.10: "Counting projects with `record_status` `ACTIVE` and `construction_required` true in
    the same `facility_id` — again excluding the row being edited — whose **closed** construction
    interval intersects the incoming closed interval, meaning the other project's
    `construction_start` is at or before the incoming end and the incoming start is at or before
    the other project's `construction_end`, the write is rejected with
    `ERR_CONSTRUCTION_CAPACITY_EXCEEDED` when that count plus one exceeds the facility's
    `max_concurrent_construction`."
    PRD §3.10: "The equipment axis walks `AWAITING_DELIVERY → DELIVERED → INSTALLED →
    COMMISSIONED`, one step per call, and never reads the construction axis."
    PRD §2.11: "44. A construction window required but absent, or supplied when construction is
    not required, on installation-project creation and project patch —
    `ERR_CONSTRUCTION_WINDOW_REQUIRED`, 422."

    Design: Corner/endpoints/patching_a_project_excludes_its_own_row_and_clearing_the_flag_drops_both_bounds
    """
    ctx = _project_holding_both_a_downtime_and_a_construction_window()
    project_id = ctx["project"]["id"]
    assert ctx["facility"]["max_concurrent_construction"] == 1

    shifted = validate_success(
        api.patch_installation_project(
            project_id,
            {"downtime_start": "2026-09-01T12:00:00Z", "downtime_end": "2026-09-02T12:00:00Z"},
            ctx["director"],
        )
    )
    assert shifted["version"] == 2
    assert_instant(shifted["downtime_start"], "2026-09-01T12:00:00Z", "downtime_start")

    rebuilt = validate_success(
        api.patch_installation_project(
            project_id,
            {"construction_start": "2026-08-11T00:00:00Z",
             "construction_end": "2026-09-01T00:00:00Z"},
            ctx["director"],
        )
    )
    assert rebuilt["version"] == 3
    assert rebuilt["construction_status"] == "DESIGN"

    cleared = validate_success(
        api.patch_installation_project(
            project_id, {"construction_required": False}, ctx["director"]
        )
    )
    assert cleared["version"] == 4
    assert cleared["construction_required"] is False
    assert cleared["construction_status"] == "NOT_REQUIRED"
    assert cleared["construction_start"] is None
    assert cleared["construction_end"] is None

    validate_error(
        api.patch_installation_project(
            project_id, {"construction_start": "2026-08-12T00:00:00Z"}, ctx["director"]
        ),
        ApiErrorId.ERR_CONSTRUCTION_WINDOW_REQUIRED.value, 422,
    )

    final = refresh_project(project_id)
    assert final["version"] == 4
    assert final["construction_start"] is None
    assert final["equipment_status"] == "AWAITING_DELIVERY"


# ─── The join step and the observation window ─────────────────────────


def test_go_live_reads_the_predecessors_axis_and_the_audit_window_reads_the_stamp(api):
    """PRD §3.10: "It requires `record_status` `ACTIVE` with `go_live_at` still null, requires
    `construction_status` to read either `NOT_REQUIRED` or `COMPLETE`, requires `equipment_status`
    to read `COMMISSIONED`, requires the owning request to stand in `FUNDED`, and — where a
    `predecessor_project_id` is set — requires the predecessor to be active and its own
    `equipment_status` to read `COMMISSIONED`."
    PRD §3.10: "An unconverged axis is a project-state fault and yields
    `ERR_PROJECT_INVALID_STATE`, whereas a predecessor that is cancelled or not yet commissioned
    yields `ERR_PREDECESSOR_NOT_COMMISSIONED`."
    PRD §3.10: "On success `go_live_at` is set to the logical clock instant and the project's
    `version` is incremented, and the request moves `FUNDED → IMPLEMENTED` with its own `version`
    incremented."
    PRD §3.11: "The referenced project must belong to this same request, must already have a
    `go_live_at`, and the `audit_window_start` may not precede that `go_live_at`; any of those
    three failures is rejected with `ERR_AUDIT_WINDOW_INVALID`."
    PRD §3.11: "A new audit is born in `SCHEDULED` with `projected_annual_volume_snapshot` and
    `baseline_year1_opex_snapshot` pinned from the request's current `projected_annual_volume` and
    `baseline_year1_opex_cents`, both actuals and both percentages null."

    Design: Corner/validations/go_live_and_the_audit_window_both_read_the_predecessor_and_the_go_live_stamp
    """
    ctx = _two_projects_chained_on_one_request()
    first_id = ctx["first_project"]["id"]
    second_id = ctx["second_project"]["id"]
    _advance_equipment(api, second_id, ctx["director"], 3)
    assert refresh_project(second_id)["equipment_status"] == "COMMISSIONED"

    validate_error(
        api.go_live_project(second_id, ctx["director"]),
        ApiErrorId.ERR_PREDECESSOR_NOT_COMMISSIONED.value, 409,
    )
    blocked = refresh_project(second_id)
    assert blocked["go_live_at"] is None
    assert blocked["construction_status"] == "NOT_REQUIRED"
    assert refresh_request(ctx["request"]["id"])["status"] == "FUNDED"

    _advance_equipment(api, first_id, ctx["director"], 3)
    live = validate_success(api.go_live_project(first_id, ctx["director"]))
    assert_instant(live["go_live_at"], CLOCK, "go_live_at")
    assert refresh_request(ctx["request"]["id"])["status"] == "IMPLEMENTED"

    validate_error(
        api.create_audit(
            ctx["request"]["id"],
            {"installation_project_id": second_id,
             "audit_window_start": "2026-09-01T00:00:00Z",
             "audit_window_end": "2027-09-01T00:00:00Z"},
            _AUDITOR,
        ),
        ApiErrorId.ERR_AUDIT_WINDOW_INVALID.value, 422,
    )
    validate_error(
        api.create_audit(
            ctx["request"]["id"],
            {"installation_project_id": first_id,
             "audit_window_start": "2026-07-01T00:00:00Z",
             "audit_window_end": "2027-07-01T00:00:00Z"},
            _AUDITOR,
        ),
        ApiErrorId.ERR_AUDIT_WINDOW_INVALID.value, 422,
    )

    audit = validate_success(
        api.create_audit(
            ctx["request"]["id"],
            {"installation_project_id": first_id,
             "audit_window_start": "2026-09-01T00:00:00Z",
             "audit_window_end": "2027-09-01T00:00:00Z"},
            _AUDITOR,
        ),
        201,
    )
    assert_utilization_audit(audit)
    assert audit["status"] == "SCHEDULED"
    assert audit["projected_annual_volume_snapshot"] == 2000
    assert_cents(audit["baseline_year1_opex_snapshot"], 10850000, "baseline_year1_opex_snapshot")
    assert audit["actual_annual_volume"] is None
    assert audit["volume_attainment_pct"] is None
    assert audit["opex_variance_pct"] is None
    assert audit["version"] == 1

    rows = get_success_data(
        api.list_audits(_AUDITOR, params={"request_id": ctx["request"]["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["id"] == audit["id"]


def test_the_second_collect_answers_for_the_audit_row_rather_than_the_request(api):
    """PRD §3.11: "The audit must stand in `SCHEDULED` — a second collect is rejected with
    `ERR_AUDIT_INVALID_STATE` — and the request must stand in `IMPLEMENTED`."
    PRD §3.11: "`volume_attainment_pct` is `actual_annual_volume` divided by
    `projected_annual_volume_snapshot`, multiplied by one hundred, rounded half up to two
    decimals."
    PRD §3.11: "The audit moves `SCHEDULED → PASSED` when `volume_attainment_pct` is at least
    80.00 **and** `opex_variance_pct` is at most 10.00; both boundaries are inclusive, so an
    attainment of exactly 80.00 and an overrun of exactly 10.00 both pass."
    PRD §3.11: "A passing verdict changes nothing outside the audit row."
    PRD §2.11: "15. The utilization audit not in `SCHEDULED`, on audit collect —
    `ERR_AUDIT_INVALID_STATE`, 409. This is deliberately ordered ahead of the request-state check
    that follows: a second collect on an already-collected audit is an audit-row fault, while a
    first collect on a `SCHEDULED` audit whose request has already been moved to `AUDITED` by a
    sibling audit is a request-state fault."

    Design: Corner/state_machines/second_collect_on_a_completed_audit_is_an_audit_state_fault_not_a_request_fault
    """
    ctx = setup_scheduled_audit()
    assert ctx["audit"]["projected_annual_volume_snapshot"] == 2000
    assert_cents(
        ctx["audit"]["baseline_year1_opex_snapshot"], 10850000, "baseline_year1_opex_snapshot"
    )

    collected = collect_audit(ctx["audit"]["id"], 1600, 11935542)
    assert collected["status"] == "PASSED"
    assert_decimal(collected["volume_attainment_pct"], 80.00, "volume_attainment_pct")
    assert_decimal(collected["opex_variance_pct"], 10.00, "opex_variance_pct")
    assert refresh_request(ctx["request"]["id"])["status"] == "AUDITED"

    validate_error(
        api.collect_audit(ctx["audit"]["id"], collect_audit_payload(1900, 10850000), _AUDITOR),
        ApiErrorId.ERR_AUDIT_INVALID_STATE.value, 409,
    )

    audit = refresh_audit(ctx["audit"]["id"])
    assert audit["status"] == "PASSED"
    assert audit["actual_annual_volume"] == 1600
    assert_cents(audit["actual_annual_opex_cents"], 11935542, "actual_annual_opex_cents")
    assert audit["version"] == 2

    department = refresh_department(ctx["department"]["id"])
    assert department["utilization_penalty_points"] == 0
    assert department["underperformance_flag"] is False


def test_a_cancelled_project_freezes_both_axes_and_its_own_windows(api):
    """PRD §3.10: "A project created with `construction_required` false has no construction axis at
    all, so `construction_status` stands at `NOT_REQUIRED` and an attempt to advance construction
    is rejected with `ERR_PROJECT_INVALID_STATE`; the same rejection covers advancing construction
    that already reads `COMPLETE`, advancing equipment that already reads `COMMISSIONED`, acting on
    a project whose `record_status` is `CANCELLED`, and acting on a project whose `go_live_at` is
    already set."
    PRD §3.10: "It accepts an optional `cancellation_reason`, requires `record_status` `ACTIVE`
    with `go_live_at` still null, moves `record_status` from `ACTIVE` to `CANCELLED` — the
    transition `ACTIVE → CANCELLED` on that axis — and increments the project's `version`."
    PRD §3.10: "A cancelled project's downtime and construction intervals stop occupying their
    resources immediately, so a later project — or a later edit of an existing project — may claim
    windows that overlap them."
    PRD §2.11: "19. The installation project not in a state that allows the operation, on project
    patch, construction advance, equipment advance, go-live and cancel —
    `ERR_PROJECT_INVALID_STATE`, 409."

    Design: Corner/state_machines/advance_equipment_on_a_cancelled_project_is_locked_out
    """
    ctx = setup_project()
    director = make_facility_director_headers(ctx["facility"]["id"])
    cancelled = cancel_project(ctx["project"]["id"])
    assert cancelled["record_status"] == "CANCELLED"
    assert cancelled["version"] == 2

    validate_error(
        api.advance_equipment(ctx["project"]["id"], director),
        ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409,
    )
    validate_error(
        api.patch_installation_project(
            ctx["project"]["id"],
            {"downtime_start": "2026-11-05T00:00:00Z", "downtime_end": "2026-11-07T00:00:00Z"},
            director,
        ),
        ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409,
    )
    validate_error(
        api.cancel_project(ctx["project"]["id"], _PLANNER),
        ApiErrorId.ERR_PROJECT_INVALID_STATE.value, 409,
    )

    frozen = refresh_project(ctx["project"]["id"])
    assert frozen["record_status"] == "CANCELLED"
    assert frozen["equipment_status"] == "AWAITING_DELIVERY"
    assert_instant(frozen["downtime_start"], "2026-10-05T00:00:00Z", "downtime_start")
    assert frozen["version"] == 2
    assert refresh_request(ctx["request"]["id"])["status"] == "FUNDED"


# ─── Closing the old machine's life ───────────────────────────────────


def test_decommissioning_a_machine_still_in_service_is_an_asset_state_fault(api):
    """PRD §3.11: "Decommissioning closes the asset's life and is a planner act carrying a single
    `disposition` input of either `TRADED_IN` or `SCRAPPED`."
    PRD §3.11: "It requires the asset to stand in `REPLACEMENT_PENDING`, and otherwise fails with
    `ERR_ASSET_INVALID_STATE`."
    PRD §3.1: "The server maintains `active_asset_count` on the facility, which starts at 0 and
    always equals the number of equipment assets at that facility whose `status` is anything other
    than `DECOMMISSIONED`."
    PRD §2.11: "17. The equipment asset not in a state that allows the operation, on service-event
    append, asset patch and decommission — `ERR_ASSET_INVALID_STATE`, 409."
    PRD §2.11: "Nothing later in the order is evaluated, and no side effect is written."

    Design: Corner/state_machines/decommission_of_an_in_service_asset_is_rejected_as_an_asset_state_fault
    """
    ctx = setup_estate()
    assert ctx["asset"]["status"] == "IN_SERVICE"

    validate_error(
        api.decommission_asset(ctx["asset"]["id"], decommission_payload("SCRAPPED"), _PLANNER),
        ApiErrorId.ERR_ASSET_INVALID_STATE.value, 409,
    )

    asset = refresh_asset(ctx["asset"]["id"])
    assert asset["status"] == "IN_SERVICE"
    assert asset["disposition_status"] == "NONE"
    assert asset["version"] == 1
    assert refresh_facility(ctx["facility"]["id"])["active_asset_count"] == 1


def test_a_traded_in_disposition_needs_a_claim_while_scrapping_needs_only_the_install(api):
    """PRD §3.11: "A `disposition` of `TRADED_IN` additionally requires the asset's
    `disposition_status` to be `HELD_FOR_TRADE_IN`, meaning an accepted quote is claiming it;
    otherwise the call is rejected with `ERR_TRADE_IN_NOT_HELD`."
    PRD §3.11: "It also requires the replacement to be physically in place: the installation
    project of the funding request whose `record_status` is `ACTIVE` must have `equipment_status`
    `COMMISSIONED`, and an asset with no such project, or one whose project is not yet
    commissioned, is rejected with `ERR_INSTALLATION_NOT_COMMISSIONED`."
    PRD §3.11: "On success the asset moves `REPLACEMENT_PENDING → DECOMMISSIONED`, its
    `disposition_status` becomes `TRADED_IN` or `SCRAPPED` per the input and its `version` is
    incremented, and the owning facility's `active_asset_count` falls by one with the facility's
    `version` incremented."
    PRD §3.1: "Once an asset reaches `DECOMMISSIONED` it is closed: edits and service-event appends
    are both rejected with `ERR_ASSET_INVALID_STATE`."
    PRD §2.11: "52. A `TRADED_IN` disposition on an asset not held for trade-in, on asset
    decommission — `ERR_TRADE_IN_NOT_HELD`, 422."

    Design: Corner/validations/traded_in_disposition_requires_a_held_trade_in_claim
    """
    ctx = setup_commissioned_project()
    facility_before = refresh_facility(ctx["facility"]["id"])
    assert facility_before["active_asset_count"] == 1
    assert refresh_asset(ctx["asset"]["id"])["disposition_status"] == "NONE"

    validate_error(
        api.decommission_asset(ctx["asset"]["id"], decommission_payload("TRADED_IN"), _PLANNER),
        ApiErrorId.ERR_TRADE_IN_NOT_HELD.value, 422,
    )
    held_back = refresh_asset(ctx["asset"]["id"])
    assert held_back["status"] == "REPLACEMENT_PENDING"
    assert held_back["disposition_status"] == "NONE"
    assert refresh_facility(ctx["facility"]["id"])["active_asset_count"] == 1

    scrapped = decommission(ctx["asset"]["id"], "SCRAPPED")
    assert scrapped["status"] == "DECOMMISSIONED"
    assert scrapped["disposition_status"] == "SCRAPPED"

    facility_after = refresh_facility(ctx["facility"]["id"])
    assert facility_after["active_asset_count"] == 0
    assert facility_after["version"] == facility_before["version"] + 1

    project = refresh_project(ctx["project"]["id"])
    assert project["record_status"] == "ACTIVE"
    assert project["equipment_status"] == "COMMISSIONED"
    assert refresh_request(ctx["request"]["id"])["status"] == "FUNDED"

    validate_error(
        api.create_service_event(
            ctx["asset"]["id"],
            create_service_event_payload(CLOCK, "PM", downtime_hours=1.00),
            _PLANNER,
        ),
        ApiErrorId.ERR_ASSET_INVALID_STATE.value, 409,
    )
