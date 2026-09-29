"""Two roles are pinned to a row rather than to an endpoint: the host site manager
to its own site, the technician to their own dispatch."""
from test_helpers import (
    NON_EXISTENT_UUID,
    OPERATOR_HEADERS,
    TECHNICIAN_1,
    TECHNICIAN_2,
    ApiErrorId,
    api_client,
    assert_pagination_meta,
    create_dispatch,
    ingest_and_classify_outage,
    make_field_technician_headers,
    make_host_site_manager_headers,
    read_charging_port,
    read_dispatch,
    read_host_site,
    register_host_site,
    setup_operational_station,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_manager_may_read_the_whole_network_but_amend_only_its_own_row():
    """The identity header is a HostSite id here, so this is a row comparison and
    not a role check — and it shares the endpoint with the operator.

    PRD §2.1: "When `X-User-Role` is `HostSiteManager`, `X-User-ID` is the `id` of
    the acting `HostSite`; ownership checks on any resource that references a
    `HostSite` compare the resource's foreign-key field to `X-User-ID`, so a
    `HostSiteManager` may amend only the host site whose `id` equals `X-User-ID` and
    any other target is rejected with `ERR_HOST_SITE_FORBIDDEN` (HTTP 403)."  PRD
    §3.1: "An amendment may carry any subset of those seven fields, is available to a
    `NetworkOperator` for any site and to a `HostSiteManager` only for the site whose
    `id` matches their `X-User-ID`, and increments the host site's `version`."  PRD
    §2.11 orders "Existence of every identifier" third and the host-site ownership
    rule fourth.  PRD §2.3 lists `agreement_status` among the host-site filters.

    Design: Corner/rbac/host_site_manager_cannot_amend_a_site_other_than_its_own
    """
    own_site = register_host_site("HS-1", committed_service_capacity_kw=400.00)
    other_site = register_host_site("HS-2", committed_service_capacity_kw=250.00)
    manager_headers = make_host_site_manager_headers(own_site["id"])

    validate_error(
        api_client.update_host_site(
            other_site["id"], {"agreement_status": "EXECUTED"}, manager_headers
        ),
        ApiErrorId.ERR_HOST_SITE_FORBIDDEN,
        403,
    )

    spared = read_host_site(other_site["id"])
    assert spared["agreement_status"] == "DRAFT"
    assert spared["version"] == 1

    validate_error(
        api_client.update_host_site(
            NON_EXISTENT_UUID, {"agreement_status": "EXECUTED"}, manager_headers
        ),
        ApiErrorId.ERR_HOST_SITE_NOT_FOUND,
        404,
    )

    amended = validate_success(
        api_client.update_host_site(
            own_site["id"],
            {
                "agreement_status": "EXECUTED",
                "power_upgrade_status": "IN_PROGRESS",
                "access_hours_mode": "RESTRICTED",
                "access_open_minute": 360,
                "access_close_minute": 1320,
                "parking_enforcement_mode": "SIGNAGE_ONLY",
            },
            manager_headers,
        )
    )

    assert amended["agreement_status"] == "EXECUTED"
    assert amended["power_upgrade_status"] == "IN_PROGRESS"
    assert amended["access_hours_mode"] == "RESTRICTED"
    assert amended["access_open_minute"] == 360
    assert amended["access_close_minute"] == 1320
    assert amended["parking_enforcement_mode"] == "SIGNAGE_ONLY"
    assert amended["version"] == 2, "one amendment, one version"

    by_operator = validate_success(
        api_client.update_host_site(
            other_site["id"], {"power_upgrade_status": "ENERGIZED"}, OPERATOR_HEADERS
        )
    )

    assert by_operator["power_upgrade_status"] == "ENERGIZED", "an opaque identity owns every site"
    assert by_operator["version"] == 2
    assert by_operator["agreement_status"] == "DRAFT", "the manager's PATCH never reached HS-2"

    rows, meta = validate_paginated(
        api_client.list_host_sites(
            manager_headers, {"agreement_status": "EXECUTED", "limit": 10, "offset": 0}
        )
    )
    assert [row["id"] for row in rows] == [own_site["id"]]
    assert_pagination_meta(meta, limit=10, offset=0, total_count=1, has_more=False)


def test_an_unassigned_technician_hears_about_the_state_before_the_assignment():
    """The two guards sit on the same call, and their order is fixed.

    PRD §3.5: "Progress is posted by the assigned `FieldTechnician` only — anyone
    else is rejected with `ERR_NOT_ASSIGNED_TECHNICIAN` — as an `event` drawn from
    `EN_ROUTE`, `ARRIVE`, and `RESUME_ONSITE`."  PRD §3.5 on the legal order:
    "`EN_ROUTE` advances the dispatch `CREATED → EN_ROUTE`"; "`ARRIVE` advances
    `EN_ROUTE → ON_SITE`, stamps `arrived_at` from the logical clock, and settles
    `response_met` once and for all ... it stays null until arrival is posted"; and
    "The assigned technician closes the dispatch out from `ON_SITE`".  PRD §2.11 puts
    "Transition legality ... including the sub-selector carried in the body for
    exclusion actions, progress events and reservation dispositions —
    `ERR_INVALID_STATE`" eighth and "Technician assignment: only the assigned
    technician may act — `ERR_NOT_ASSIGNED_TECHNICIAN`" twelfth.  PRD §3.2: "When a
    first dispatch is created for a dispenser sitting at `NONE`, the dimension moves
    `NONE → DISPATCH_PENDING`".

    Design: Corner/rbac/technician_cannot_act_on_a_dispatch_assigned_to_someone_else
    """
    scenario = setup_operational_station(
        clock="2026-08-01T00:00:00Z",
        site_code="HS-1",
        station_code="ST-1",
        port_count=1,
        committed_service_capacity_kw=400.00,
    )
    port_id = scenario["ports"][0]["id"]
    outage = ingest_and_classify_outage(
        port_id, "2026-08-01T00:00:00Z", fault_class="MAJOR", fault_code="EVSE-MAJ-11"
    )
    dispatch = create_dispatch(
        outage["id"],
        port_id,
        window_start_at="2026-08-01T01:00:00Z",
        window_end_at="2026-08-01T09:00:00Z",
        technician_user_id=TECHNICIAN_1,
    )
    assert dispatch["state"] == "CREATED"
    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"

    stranger = make_field_technician_headers(TECHNICIAN_2)

    validate_error(
        api_client.post_dispatch_progress(dispatch["id"], "EN_ROUTE", stranger),
        ApiErrorId.ERR_NOT_ASSIGNED_TECHNICIAN,
        403,
    )
    validate_error(
        api_client.post_dispatch_progress(dispatch["id"], "ARRIVE", stranger),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )
    validate_error(
        api_client.complete_dispatch(dispatch["id"], stranger),
        ApiErrorId.ERR_INVALID_STATE,
        409,
    )

    untouched = read_dispatch(dispatch["id"])
    assert untouched["state"] == "CREATED"
    assert untouched["arrived_at"] is None
    assert untouched["response_met"] is None
    assert untouched["version"] == dispatch["version"]
    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"

    moved = validate_success(
        api_client.post_dispatch_progress(
            dispatch["id"], "EN_ROUTE", make_field_technician_headers(TECHNICIAN_1)
        )
    )

    assert moved["state"] == "EN_ROUTE", "the identical request from the assignee succeeds"
    assert moved["arrived_at"] is None
    assert read_charging_port(port_id)["maintenance_state"] == "DISPATCH_PENDING"
