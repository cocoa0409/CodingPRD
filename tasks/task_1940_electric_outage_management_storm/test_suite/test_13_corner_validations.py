"""Corner tests — validations section (priority cascade)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    create_accepted_assessment,
    create_and_activate_event,
    create_available_mutual_aid_crew,
    create_confirm_outage_payload,
    create_crew,
    create_feeder_record,
    create_material_stock_payload,
    create_mutual_aid_crew_payload,
    create_outage_payload,
    create_ready_work_order,
    create_stock,
    create_work_order_payload,
    get_success_data,
    set_clock,
    setup_event_with_feeder,
    setup_outage_with_accepted_assessment,
    validate_error,
)

ED = TEST_USERS["emergency_director_headers"]
DISP = TEST_USERS["dispatcher_headers"]
TG = TEST_USERS["telemetry_gateway_headers"]
MAC = TEST_USERS["mutual_aid_coordinator_headers"]
MM = TEST_USERS["materials_manager_headers"]


def test_missing_auth_header_returns_400(api):
    """PRD §2.1: "A request in which either header is missing or empty is
    rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/missing_auth_header_returns_400
    """
    set_clock("2026-08-10T00:00:00Z")
    resp = api.list_storm_events(NO_AUTH_HEADERS)
    err = validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_CONTEXT_HEADER)
    assert err["error_id"] == "ERR_MISSING_OR_INVALID_CONTEXT_HEADER"


def test_role_forbidden_for_telemetry_gateway_on_outage_create(api):
    """PRD §2.1: "A request whose `X-User-Role` is not among the roles
    authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)." The endpoint table (§4) authorizes only `Dispatcher` for
    `POST /om/outages`.

    Design: Corner/validations/role_forbidden_for_telemetry_gateway_on_outage_create
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    resp = api.create_outage(
        create_outage_payload(ev["id"], fd["id"]),
        TEST_USERS["telemetry_gateway_headers"],
    )
    err = validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
    assert err["error_id"] == "ERR_FORBIDDEN_ROLE"


def test_referential_cross_event_link_rejected(api):
    """PRD §3.3: "The parent must belong to the same storm event
    (`ERR_CROSS_EVENT_LINK`)".

    Design: Corner/validations/referential_cross_event_link_rejected
    """
    set_clock("2026-08-10T00:00:00Z")
    ev1 = create_and_activate_event(event_name="Storm V3a", event_type="HURRICANE")
    ev2 = create_and_activate_event(event_name="Storm V3b", event_type="TORNADO")
    fd = create_feeder_record(county_code="C1", customer_count=1000)
    parent = get_success_data(
        api.create_outage(create_outage_payload(ev1["id"], fd["id"]), DISP)
    )
    resp = api.create_outage(
        create_outage_payload(ev2["id"], fd["id"], parent_outage_id=parent["id"]),
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_CROSS_EVENT_LINK)
    assert err["error_id"] == "ERR_CROSS_EVENT_LINK"


def test_merge_cycle_rejected(api):
    """PRD §3.3: "must be neither the source itself nor one of its transitive
    descendants — the server walks the `parent_outage_id` chain to check —
    (`ERR_MERGE_CYCLE`)."

    Design: Corner/validations/merge_cycle_rejected
    """
    ev, fd = setup_event_with_feeder(clock_iso="2026-08-10T00:00:00Z")
    oa = get_success_data(api.create_outage(create_outage_payload(ev["id"], fd["id"]), DISP))
    ob = get_success_data(
        api.create_outage(
            create_outage_payload(ev["id"], fd["id"], parent_outage_id=oa["id"]),
            DISP,
        )
    )
    resp = api.merge_outage(oa["id"], {"target_outage_id": ob["id"]}, DISP)
    err = validate_error(resp, ApiErrorId.ERR_MERGE_CYCLE)
    assert err["error_id"] == "ERR_MERGE_CYCLE"
    # No merge side effects fired.
    a = get_success_data(api.get_outage(oa["id"], DISP))
    b = get_success_data(api.get_outage(ob["id"], DISP))
    assert a["outage_status"] == "SUSPECTED"
    assert b["outage_status"] == "SUSPECTED"


def test_assign_ambiguous_assignee_rejected(api):
    """PRD §3.5: "The payload names exactly one assignee: a `crew_id` for an
    internal crew or a `mutual_aid_crew_id` for an external one. Supplying
    both is rejected with `ERR_ASSIGNEE_AMBIGUOUS` (400); supplying neither
    is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/assign_ambiguous_assignee_rejected
    """
    _ev, _fd, ot, _cr_a, _da = setup_outage_with_accepted_assessment()
    cr_l = create_crew(crew_type="LINE")
    ma = create_available_mutual_aid_crew(_ev["id"], crew_type="LINE")
    wo = create_ready_work_order(ot["id"])
    resp = api.assign_work_order(
        wo["id"],
        {"crew_id": cr_l["id"], "mutual_aid_crew_id": ma["id"]},
        DISP,
    )
    err = validate_error(resp, ApiErrorId.ERR_ASSIGNEE_AMBIGUOUS)
    assert err["error_id"] == "ERR_ASSIGNEE_AMBIGUOUS"
    # The failed assign left state untouched.
    wo_read = get_success_data(api.get_work_order(wo["id"], DISP))
    assert wo_read["execution_status"] == "READY"
    crew_read = get_success_data(api.get_crew(cr_l["id"], DISP))
    assert crew_read["crew_status"] == "AVAILABLE"


def test_duplicate_stock_rejected_409(api):
    """PRD §3.8: "the pair of warehouse and SKU must be unique, and a
    duplicate registration is rejected with `ERR_DUPLICATE_STOCK` (409)."

    Design: Corner/validations/duplicate_stock_rejected_409
    """
    set_clock("2026-08-10T00:00:00Z")
    create_stock(warehouse_code="W1", material_sku="SKU-1")
    resp = api.create_material_stock(
        create_material_stock_payload(
            warehouse_code="W1",
            material_sku="SKU-1",
            quantity_on_hand=50,
            unit_cost_cents=600,
        ),
        MM,
    )
    err = validate_error(resp, ApiErrorId.ERR_DUPLICATE_STOCK)
    assert err["error_id"] == "ERR_DUPLICATE_STOCK"
    # A different sku in the same warehouse succeeds.
    ok = get_success_data(
        api.create_material_stock(
            create_material_stock_payload(
                warehouse_code="W1",
                material_sku="SKU-2",
                quantity_on_hand=50,
                unit_cost_cents=600,
            ),
            MM,
        )
    )
    assert ok["id"] is not None
