"""Role-based access control corners: the seven role grants, the four refusals
that all look like "permission denied", and the segregation of duties between
the hand that measures and the hand that signs.

Queue B / rbac.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

import pytest

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import InsulationApiClient
from test_helpers.api_errors import ApiErrors
from test_helpers.assertions import assert_area, assert_close, assert_emissions, assert_field_equals
from test_helpers.constants import ZONES_470
from test_helpers.test_users import (
    ALL_ROLES,
    CERTIFICATION_OFFICER_USER_ID,
    CERTIFICATION_OFFICER_USER_ID_ALT,
    CHANNEL_BUYER_USER_ID,
    CHANNEL_BUYER_USER_ID_ALT,
    QUALITY_ENGINEER_USER_ID,
    UNKNOWN_PLANT_USER_ID,
    certification_officer_headers,
    channel_buyer_headers,
    channel_manager_headers,
    corporate_ops_headers,
    environmental_compliance_headers,
    headers_for_role,
    headers_missing_role,
    headers_missing_user_id,
    headers_with_unknown_role,
    headers_without_identity,
    plant_operator_headers,
    quality_engineer_headers,
)

RUN_START = "2026-08-03T06:00:00Z"
RUN_END = "2026-08-03T14:00:00Z"
LAB_START = "2026-08-03T08:00:00Z"
LAB_END = "2026-08-03T12:00:00Z"

CONFORMING_SPECIMENS = [13.10, 13.20, 12.90]


def _user_id_for(role: str) -> str:
    """A syntactically usable X-User-ID for a role that is about to be refused."""
    if role == "PlantOperator":
        return UNKNOWN_PLANT_USER_ID
    return f"probe-{role.lower()}"


# ---------------------------------------------------------------------------
# Every role runs the operations only it may run.
# ---------------------------------------------------------------------------


def test_all_seven_roles_cover_the_whole_plant_flow_without_a_super_user(
    client: InsulationApiClient,
) -> None:
    """PRD 2.1: "`CorporateOps` owns master and reference data. It registers plants,
    certification programs and SKUs, re-tunes packaging economics, and drives the
    server's logical clock."
    PRD 2.1: "`PlantOperator` is the forming-line hand, scoped to exactly one plant.
    It schedules and drives runs, opens and closes changeovers, repacks lots, and
    stages, reverses or rejects cullet."
    PRD 2.1: "`QualityEngineer` is the laboratory hand. It drafts and revises binder
    formulations, submits SKUs for thermal certification, requests and records thermal
    tests, and quarantines, scraps or releases finished-goods lots."
    PRD 2.1: "`CertificationOfficer` is the certification-program signatory. It records
    the binder emissions-test measurement and rules on both binder and SKU
    certification, including the derate decision."
    PRD 2.1: "`EnvironmentalCompliance` is the air-permit officer. It files permit-period
    emissions reports and reviews melt postures, and it holds the only authority to clear
    a plant whose melt shop has been frozen."
    PRD 2.1: "`ChannelManager` is the distributor and retail allocator. It opens,
    proposes, commits and cancels allocation cycles, cuts and revokes manual expedite
    lines, and ships orders."
    PRD 2.1: "`ChannelBuyer` is the distributor or retail buyer. It places its own orders
    and cancels only its own."

    Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
    """
    ops = corporate_ops_headers()
    qe = quality_engineer_headers()
    officer = certification_officer_headers()
    env = environmental_compliance_headers()
    manager = channel_manager_headers()
    buyer = channel_buyer_headers()

    fx.reset_clock(client)

    # The liveness probe is readable by every role, including a buyer.
    health = validate_success(client.health(buyer))
    assert health.get("status"), "the liveness probe reports a status"

    # CorporateOps: reference data.
    program = validate_success(
        client.create_certification_program(f.per_specimen_program_payload(), ops), 201
    )
    plant = validate_success(client.create_plant(f.plant_payload(), ops), 201)
    operator = plant_operator_headers(plant["id"])

    # QualityEngineer drafts and submits the chemistry; CertificationOfficer measures
    # and rules on it.
    binder = validate_success(
        client.create_binder_formulation(f.formaldehyde_free_binder_payload(), qe), 201
    )
    validate_success(client.submit_binder(binder["id"], qe))
    validate_success(
        client.record_binder_emissions_test(
            binder["id"], f.binder_emissions_test_payload(0, 3.2, "LAB-9001"), officer
        )
    )
    certified_binder = validate_success(
        client.binder_certification_decision(
            binder["id"],
            f.binder_decision_payload("CERTIFY", emissions_cert_id="EC-4411"),
            officer,
        )
    )
    assert_field_equals(certified_binder, "status", "CERTIFIED")

    # CorporateOps mints the SKU and drives the logical clock.
    sku = validate_success(
        client.create_product_line(
            f.product_line_payload(plant["id"], binder["id"], program["id"]), ops
        ),
        201,
    )
    validate_success(client.set_clock(RUN_START, ops))

    # PlantOperator drives the forming line.
    run = validate_success(
        client.create_production_run(
            f.production_run_payload(
                plant["id"],
                sku["id"],
                scheduled_start=RUN_START,
                scheduled_end=RUN_END,
                target_pull_kg=9200.0,
                zone_setpoints_f=list(ZONES_470),
            ),
            operator,
        ),
        201,
    )
    validate_success(client.start_melt(run["id"], [], operator))
    cured = validate_success(
        client.start_cure(
            run["id"],
            f.start_cure_payload(
                avg_zone_temp_f=470.0, line_speed_fpm=40.0, binder_applied_kg=900.0
            ),
            operator,
        )
    )
    assert_field_equals(cured, "run_status", "CURING")

    # QualityEngineer runs the laboratory.
    test = validate_success(
        client.create_thermal_test(
            f.thermal_test_payload(
                run["id"],
                sku["id"],
                program["id"],
                window_start=LAB_START,
                window_end=LAB_END,
            ),
            qe,
        ),
        201,
    )
    validate_success(client.start_lab(test["id"], qe))
    recorded = validate_success(
        client.record_result(test["id"], CONFORMING_SPECIMENS, qe)
    )
    assert_field_equals(recorded, "conformance_verdict", "CONFORMING")
    validate_success(client.submit_sku_certification(sku["id"], qe))

    # CertificationOfficer signs the SKU off.
    signed = validate_success(
        client.sku_certification_decision(
            sku["id"], f.sku_decision_payload("CERTIFY"), officer
        )
    )
    assert_field_equals(signed, "certification_status", "CERTIFIED")

    # PlantOperator packages: the lot is cascade-created and found by filtering.
    validate_success(client.package_run(run["id"], 120, operator))
    lots, lot_meta = validate_paginated(
        client.list_inventory_lots(operator, {"production_run_id": run["id"]})
    )
    assert lot_meta["total_count"] == 1, "packaging cascade-creates exactly one lot"
    assert_field_equals(lots[0], "bags", 120)
    assert_area(lots[0]["produced_sqft"], 10560.00, "lot.produced_sqft")

    # EnvironmentalCompliance files the permit-period report.
    reported = validate_success(
        client.file_emissions_report(
            plant["id"],
            f.emissions_report_payload("2026-08-01T00:00:00Z", RUN_START),
            env,
        )
    )
    assert_field_equals(reported, "emissions_status", "REPORTED")
    assert_emissions(
        reported["reported_formaldehyde_kg"], 0.0000, "reported_formaldehyde_kg"
    )
    assert_emissions(reported["reported_voc_kg"], 2.8800, "reported_voc_kg")
    assert_field_equals(reported, "melt_posture", "OPEN")

    # ChannelBuyer places its own order; ChannelManager opens the cycle.
    order = validate_success(
        client.create_channel_order(
            f.channel_order_payload(
                sku["id"],
                880.00,
                channel_type="RETAIL",
                priority_tier="SPOT",
                required_by="2026-08-20T00:00:00Z",
            ),
            buyer,
        ),
        201,
    )
    assert_field_equals(order, "placed_by_user_id", CHANNEL_BUYER_USER_ID)
    cycle = validate_success(
        client.create_allocation_cycle(
            f.allocation_cycle_payload(
                plant["id"], sku["id"], allocation_basis="PRO_RATA"
            ),
            manager,
        ),
        201,
    )
    assert_field_equals(cycle, "status", "OPEN")
    assert_field_equals(cycle, "allocation_basis", "PRO_RATA")

    # ChannelBuyer cancels only its own order - the one thing ChannelManager may not do.
    cancelled = validate_success(
        client.cancel_order(
            order["id"], buyer, {"cancel_reason": "buyer deferred to next season"}
        )
    )
    assert_field_equals(cancelled, "status", "CANCELLED")

    # CorporateOps re-tunes the packaging economics.
    retuned = validate_success(
        client.patch_packaging(
            sku["id"], f.packaging_patch_payload(compression_ratio=6.5), ops
        )
    )
    assert_close(retuned["compression_ratio"], 6.5, 1, "compression_ratio")
    assert_close(retuned["recovered_thickness_pct"], 87.50, 2, "recovered_thickness_pct")


# ---------------------------------------------------------------------------
# No role reaches another role's exclusive operation, and the four refusals
# stay in priority order.
# ---------------------------------------------------------------------------

_Call = Callable[[InsulationApiClient, Dict[str, str]], Any]

# One row per endpoint: the path, the roles PRD 4 authorizes for it, and a call
# whose only defect is the acting role.
_ENDPOINT_MATRIX: List[Tuple[str, Tuple[str, ...], _Call]] = [
    (
        "POST /_clock/set_current_utc",
        ("CorporateOps",),
        lambda c, h: c.set_clock("2026-08-05T00:00:00Z", h),
    ),
    (
        "POST /certification-programs",
        ("CorporateOps",),
        lambda c, h: c.create_certification_program(
            f.certification_program_payload(), h
        ),
    ),
    ("POST /plants", ("CorporateOps",), lambda c, h: c.create_plant(f.plant_payload(), h)),
    (
        "POST /product-lines",
        ("CorporateOps",),
        lambda c, h: c.create_product_line(
            f.product_line_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            h,
        ),
    ),
    (
        "PATCH /product-lines/{productLineId}/packaging",
        ("CorporateOps",),
        lambda c, h: c.patch_packaging(
            NON_EXISTENT_UUID, f.packaging_patch_payload(compression_ratio=5.0), h
        ),
    ),
    (
        "POST /binder-formulations",
        ("QualityEngineer",),
        lambda c, h: c.create_binder_formulation(f.binder_payload(), h),
    ),
    (
        "POST /product-lines/{productLineId}/submit-certification",
        ("QualityEngineer",),
        lambda c, h: c.submit_sku_certification(NON_EXISTENT_UUID, h),
    ),
    (
        "POST /thermal-tests",
        ("QualityEngineer",),
        lambda c, h: c.create_thermal_test(
            f.thermal_test_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
            ),
            h,
        ),
    ),
    (
        "POST /inventory-lots/{lotId}/quarantine",
        ("QualityEngineer",),
        lambda c, h: c.quarantine_lot(
            NON_EXISTENT_UUID, f.quarantine_payload("HOLD"), h
        ),
    ),
    (
        "POST /binder-formulations/{binderId}/emissions-test",
        ("CertificationOfficer",),
        lambda c, h: c.record_binder_emissions_test(
            NON_EXISTENT_UUID, f.binder_emissions_test_payload(120, 3.0), h
        ),
    ),
    (
        "POST /product-lines/{productLineId}/certification-decision",
        ("CertificationOfficer",),
        lambda c, h: c.sku_certification_decision(
            NON_EXISTENT_UUID, f.sku_decision_payload("CERTIFY"), h
        ),
    ),
    (
        "POST /production-runs",
        ("PlantOperator",),
        lambda c, h: c.create_production_run(
            f.production_run_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), h
        ),
    ),
    (
        "POST /production-runs/{runId}/start-melt",
        ("PlantOperator",),
        lambda c, h: c.start_melt(NON_EXISTENT_UUID, [], h),
    ),
    (
        "POST /changeover-events",
        ("PlantOperator",),
        lambda c, h: c.create_changeover(
            f.changeover_payload(
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                NON_EXISTENT_UUID,
                1,
                "2026-08-04T06:00:00Z",
                "2026-08-04T08:00:00Z",
            ),
            h,
        ),
    ),
    (
        "POST /cullet-batches",
        ("PlantOperator",),
        lambda c, h: c.create_cullet_batch(
            f.cullet_batch_payload(NON_EXISTENT_UUID, 500.00, 1), h
        ),
    ),
    (
        "POST /inventory-lots/{lotId}/repack",
        ("PlantOperator",),
        lambda c, h: c.repack_lot(NON_EXISTENT_UUID, [60, 60], h),
    ),
    (
        "POST /plants/{plantId}/emissions-report",
        ("EnvironmentalCompliance",),
        lambda c, h: c.file_emissions_report(
            NON_EXISTENT_UUID,
            f.emissions_report_payload("2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z"),
            h,
        ),
    ),
    (
        "POST /plants/{plantId}/posture-review",
        ("EnvironmentalCompliance",),
        lambda c, h: c.posture_review(
            NON_EXISTENT_UUID, f.posture_review_payload("RECOMPUTE"), h
        ),
    ),
    (
        "POST /allocation-cycles",
        ("ChannelManager",),
        lambda c, h: c.create_allocation_cycle(
            f.allocation_cycle_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID), h
        ),
    ),
    (
        "POST /allocation-lines",
        ("ChannelManager",),
        lambda c, h: c.create_allocation_line(
            f.allocation_line_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID, 88.00, 1
            ),
            h,
        ),
    ),
    (
        "POST /allocation-lines/{lineId}/revoke",
        ("ChannelManager",),
        lambda c, h: c.revoke_allocation_line(NON_EXISTENT_UUID, h),
    ),
    (
        "POST /channel-orders/{orderId}/ship",
        ("ChannelManager",),
        lambda c, h: c.ship_order(NON_EXISTENT_UUID, h),
    ),
    (
        "POST /channel-orders/{orderId}/cancel",
        ("ChannelBuyer",),
        lambda c, h: c.cancel_order(NON_EXISTENT_UUID, h, {"cancel_reason": "no longer needed"}),
    ),
    (
        "POST /channel-orders",
        ("ChannelBuyer", "ChannelManager"),
        lambda c, h: c.create_channel_order(
            f.channel_order_payload(NON_EXISTENT_UUID, 880.00), h
        ),
    ),
    (
        "GET /plants",
        ("CorporateOps", "EnvironmentalCompliance", "ChannelManager"),
        lambda c, h: c.list_plants(h),
    ),
    (
        "GET /cullet-batches",
        ("CorporateOps", "PlantOperator", "EnvironmentalCompliance"),
        lambda c, h: c.list_cullet_batches(h),
    ),
    (
        "GET /thermal-tests",
        ("CorporateOps", "QualityEngineer", "CertificationOfficer"),
        lambda c, h: c.list_thermal_tests(h),
    ),
]


@pytest.mark.parametrize(
    "endpoint,allowed_roles,call",
    _ENDPOINT_MATRIX,
    ids=[row[0] for row in _ENDPOINT_MATRIX],
)
def test_every_unauthorized_role_is_refused_on_each_endpoint(
    client: InsulationApiClient,
    endpoint: str,
    allowed_roles: Tuple[str, ...],
    call: _Call,
) -> None:
    """PRD 2.1: "If `X-User-Role` is not one of the seven role names below, or is a valid
    role that is not authorized for the endpoint being called, the request is rejected
    with `ERR_UNAUTHORIZED`."
    PRD 2.8: "2. Role recognized and authorized for the endpoint - `ERR_UNAUTHORIZED`."
    PRD 2.9: "Path identifiers are resolved strictly left to right before any body
    content is examined, and the leftmost unresolved identifier decides the error."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_unauthenticated_calls_are_refused_first
    """
    for role in ALL_ROLES:
        if role in allowed_roles:
            continue
        headers = headers_for_role(role, _user_id_for(role))
        response = call(client, headers)
        validate_error(response, ApiErrors.UNAUTHORIZED)
        assert response.status_code == 403, (
            f"{role} on {endpoint} must be refused with HTTP 403, "
            f"got {response.status_code}"
        )


@pytest.mark.parametrize(
    "label,headers",
    [
        ("no identity headers at all", headers_without_identity()),
        ("empty X-User-ID", headers_missing_user_id("CorporateOps")),
        ("empty X-User-Role", headers_missing_role("ops-1")),
        ("empty X-User-ID and an unauthorized role", headers_missing_user_id("PlantOperator")),
    ],
    ids=["no-headers", "empty-user-id", "empty-role", "empty-user-id-wrong-role"],
)
def test_missing_identity_headers_outrank_role_authorization(
    client: InsulationApiClient, label: str, headers: Dict[str, str]
) -> None:
    """PRD 2.1: "If either header is missing or empty, the request is rejected with
    `ERR_UNAUTHENTICATED`."
    PRD 2.8: "1. Identity headers present and non-empty - `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_unauthenticated_calls_are_refused_first
    """
    response = client.create_product_line(
        f.product_line_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
        ),
        headers,
    )
    validate_error(response, ApiErrors.UNAUTHENTICATED)
    assert response.status_code == 401, (
        f"{label} must be refused with HTTP 401, got {response.status_code}"
    )

    # Nothing was written by the refused call.
    _rows, meta = validate_paginated(
        client.list_product_lines(corporate_ops_headers())
    )
    assert meta["total_count"] == 0, "a refused call must not create a SKU"


def test_unrecognised_role_name_is_unauthorized_not_unauthenticated(
    client: InsulationApiClient,
) -> None:
    """PRD 2.1: "If `X-User-Role` is not one of the seven role names below, or is a valid
    role that is not authorized for the endpoint being called, the request is rejected
    with `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_unauthenticated_calls_are_refused_first
    """
    response = client.create_product_line(
        f.product_line_payload(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, NON_EXISTENT_UUID
        ),
        headers_with_unknown_role("aud-1"),
    )
    validate_error(response, ApiErrors.UNAUTHORIZED)
    assert response.status_code == 403, (
        "an X-User-Role outside the seven declared roles is a 403 - the headers "
        f"were present, got {response.status_code}"
    )

    _rows, meta = validate_paginated(
        client.list_product_lines(corporate_ops_headers())
    )
    assert meta["total_count"] == 0, "a refused call must not create a SKU"


def test_health_probe_is_the_only_endpoint_that_needs_no_identity_headers(
    client: InsulationApiClient,
) -> None:
    """PRD 2.4: "The liveness probe reports the clock's current value alongside its
    `status`, and it is the only endpoint in the API that does not require the two
    identity headers."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_unauthenticated_calls_are_refused_first
    """
    response = client.health(headers_without_identity())
    data = validate_success(response)
    assert data.get("status"), "the probe reports a status even with no identity headers"

    # The same headerless request on any other endpoint is refused at rung 1.
    refused = client.list_plants(headers_without_identity())
    validate_error(refused, ApiErrors.UNAUTHENTICATED)


def test_a_plant_operator_cannot_reach_another_plants_rows(
    client: InsulationApiClient,
) -> None:
    """PRD 2.1: "A `PlantOperator` acting on a row belonging to any other plant is
    rejected with `ERR_PLANT_NOT_OWNED`."
    PRD 2.8: "4. Plant ownership for a `PlantOperator` write - `ERR_PLANT_NOT_OWNED`;
    order ownership for a `ChannelBuyer` cancellation - `ERR_ORDER_NOT_OWNED`."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_unauthenticated_calls_are_refused_first
    """
    ctx = fx.base_setup(client)
    owner = ctx["operator"]
    other_plant = fx.create_plant(
        client, name="Trenton Forming Plant", site_code="TRN", permit_number="NJ-AIR-9002"
    )
    intruder = plant_operator_headers(other_plant["id"])

    # A payload naming plant A's id, sent by plant B's operator. `line_index` 99 is out
    # of range for a two-line plant, but ownership sits at rung 4 and the range check at
    # rung 11, so ownership decides.
    payload = f.production_run_payload(
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start=RUN_START,
        scheduled_end=RUN_END,
        line_index=99,
        zone_setpoints_f=list(ZONES_470),
    )
    refused = client.create_production_run(payload, intruder)
    validate_error(refused, ApiErrors.PLANT_NOT_OWNED)
    assert refused.status_code == 403, (
        f"cross-plant writes are a 403, got {refused.status_code}"
    )

    # The very same payload from the owning operator reaches rung 11, which proves the
    # refusal above was decided by ownership and not by the bad line index.
    owner_attempt = client.create_production_run(payload, owner)
    validate_error(owner_attempt, ApiErrors.LINE_INDEX_OUT_OF_RANGE)

    # Ownership is also transitive: a run row is reached through its plant_id.
    run = fx.schedule_run(
        client,
        ctx["plant_id"],
        ctx["sku_id"],
        scheduled_start=RUN_START,
        scheduled_end=RUN_END,
        line_index=1,
        zone_setpoints_f=list(ZONES_470),
    )
    validate_error(
        client.start_melt(run["id"], [], intruder), ApiErrors.PLANT_NOT_OWNED
    )

    # No run was created for the intruder, and plant A's run is untouched.
    runs, meta = validate_paginated(
        client.list_production_runs(corporate_ops_headers())
    )
    assert meta["total_count"] == 1, "only the owning operator's run exists"
    assert_field_equals(runs[0], "run_status", "SCHEDULED")
    assert_field_equals(runs[0], "plant_id", ctx["plant_id"])


def test_a_buyer_cannot_cancel_an_order_it_did_not_place(
    client: InsulationApiClient,
) -> None:
    """PRD 3.8: "Only the buyer who placed it may do so - the acting `X-User-ID` must
    equal `placed_by_user_id`, and any other buyer is refused with
    `ERR_ORDER_NOT_OWNED`."

    Design: Corner/rbac/no_role_can_reach_another_roles_exclusive_operation_and_unauthenticated_calls_are_refused_first
    """
    ctx = fx.certified_sku_with_lot(client)
    order = fx.place_order(
        client, ctx["sku_id"], 4400.00, buyer_user_id=CHANNEL_BUYER_USER_ID
    )
    assert_field_equals(order, "placed_by_user_id", CHANNEL_BUYER_USER_ID)
    assert_field_equals(order, "status", "SUBMITTED")

    refused = client.cancel_order(
        order["id"],
        channel_buyer_headers(CHANNEL_BUYER_USER_ID_ALT),
        {"cancel_reason": "wrong buyer"},
    )
    validate_error(refused, ApiErrors.ORDER_NOT_OWNED)
    assert refused.status_code == 403, (
        f"a foreign buyer's cancellation is a 403, got {refused.status_code}"
    )
    assert_field_equals(fx.get_order(client, order["id"]), "status", "SUBMITTED")

    # The placing buyer's own cancellation goes through.
    cancelled = validate_success(
        client.cancel_order(
            order["id"],
            channel_buyer_headers(CHANNEL_BUYER_USER_ID),
            {"cancel_reason": "customer withdrew"},
        )
    )
    assert_field_equals(cancelled, "status", "CANCELLED")


# ---------------------------------------------------------------------------
# The hand that measures may not be the hand that signs.
# ---------------------------------------------------------------------------


def _sku_awaiting_signature(
    client: InsulationApiClient,
    recorder_user_id: str,
    program_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """A PENDING_CERTIFICATION SKU whose only thermal test was recorded by one user."""
    ctx = fx.base_setup(client, program_overrides=program_overrides)
    fx.submit_sku(client, ctx["sku_id"])
    run = fx.run_to_packaged(client, ctx["plant_id"], ctx["sku_id"], bags_produced=120)
    test = fx.completed_thermal_test(
        client,
        run["id"],
        ctx["sku_id"],
        ctx["program_id"],
        CONFORMING_SPECIMENS,
        user_id=recorder_user_id,
    )
    assert_field_equals(test, "recorded_by_user_id", recorder_user_id)
    assert_field_equals(test, "conformance_verdict", "CONFORMING")
    ctx["run"] = run
    ctx["run_id"] = run["id"]
    ctx["test"] = test
    ctx["test_id"] = test["id"]
    return ctx


def test_the_officer_who_recorded_the_specimens_cannot_certify_the_sku(
    client: InsulationApiClient,
) -> None:
    """PRD 2.10: "The `X-User-ID` issuing a product-line certification decision must
    differ from **every** `recorded_by_user_id` present on the thermal tests of that
    product line, and - on any second or later decision against the same SKU - must also
    differ from that SKU's current `certified_by_user_id`. A violation is rejected with
    `ERR_SEGREGATION_OF_DUTIES` and HTTP 409."

    Design: Corner/rbac/the_same_user_cannot_record_specimens_and_sign_the_certification
    """
    ctx = _sku_awaiting_signature(client, CERTIFICATION_OFFICER_USER_ID)

    refused = client.sku_certification_decision(
        ctx["sku_id"],
        f.sku_decision_payload("CERTIFY"),
        certification_officer_headers(CERTIFICATION_OFFICER_USER_ID),
    )
    validate_error(refused, ApiErrors.SEGREGATION_OF_DUTIES)
    assert refused.status_code == 409, (
        f"a self-signed certification is a 409, got {refused.status_code}"
    )

    # The refusal wrote nothing: the SKU is still in the queue, unsigned.
    parked = fx.get_product_line(client, ctx["sku_id"])
    assert_field_equals(parked, "certification_status", "PENDING_CERTIFICATION")
    assert parked["effective_declared_r_value"] is None
    assert parked["certified_by_user_id"] is None

    # A different officer signs the very same SKU off unchanged.
    signed = validate_success(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("CERTIFY"),
            certification_officer_headers(CERTIFICATION_OFFICER_USER_ID_ALT),
        )
    )
    assert_field_equals(signed, "certification_status", "CERTIFIED")
    assert_field_equals(signed, "certified_by_user_id", CERTIFICATION_OFFICER_USER_ID_ALT)
    assert_close(signed["effective_declared_r_value"], 13.0, 2, "effective_declared_r_value")


def test_segregation_of_duties_outranks_the_derate_policy_switch(
    client: InsulationApiClient,
) -> None:
    """PRD 2.8: "10. Certification and safety integrity, in this order: the
    formaldehyde-free claim check `ERR_FORMALDEHYDE_FREE_CLAIM_INVALID`, the
    certified-binder gate `ERR_BINDER_NOT_CERTIFIED`, the binder emissions limit
    `ERR_FORMALDEHYDE_LIMIT_EXCEEDED`, the quarantined-lot block `ERR_LOT_QUARANTINED`,
    the conforming-run gate on lot release `ERR_RUN_NOT_CONFORMING`, and segregation of
    duties `ERR_SEGREGATION_OF_DUTIES`."
    PRD 3.7: "The resulting `effective_declared_r_value` must be strictly greater than 0
    **and** strictly less than `declared_r_value`, and any failure of the `derate_allowed`
    flag, the test-availability requirement or that strict band is refused with
    `ERR_DERATE_NOT_PERMITTED`."

    Design: Corner/rbac/the_same_user_cannot_record_specimens_and_sign_the_certification
    """
    ctx = _sku_awaiting_signature(
        client,
        CERTIFICATION_OFFICER_USER_ID,
        program_overrides={"code": "RCERT-ND", "derate_allowed": False},
    )
    assert_field_equals(ctx["program"], "derate_allowed", False)

    # This DERATE violates rung 10 (the recorder is the signer) and rung 12 (the program
    # forbids derating). Only rung 10 may be reported.
    refused = client.sku_certification_decision(
        ctx["sku_id"],
        f.sku_decision_payload("DERATE"),
        certification_officer_headers(CERTIFICATION_OFFICER_USER_ID),
    )
    validate_error(refused, ApiErrors.SEGREGATION_OF_DUTIES)

    # Clearing rung 10 with an independent officer exposes the rung-12 refusal, which
    # proves the first refusal was decided by segregation of duties.
    exposed = client.sku_certification_decision(
        ctx["sku_id"],
        f.sku_decision_payload("DERATE"),
        certification_officer_headers(CERTIFICATION_OFFICER_USER_ID_ALT),
    )
    validate_error(exposed, ApiErrors.DERATE_NOT_PERMITTED)

    parked = fx.get_product_line(client, ctx["sku_id"])
    assert_field_equals(parked, "certification_status", "PENDING_CERTIFICATION")
    assert parked["certified_by_user_id"] is None


def test_a_second_decision_is_barred_to_the_officer_who_signed_the_first(
    client: InsulationApiClient,
) -> None:
    """PRD 2.10: "The `X-User-ID` issuing a product-line certification decision must
    differ from **every** `recorded_by_user_id` present on the thermal tests of that
    product line, and - on any second or later decision against the same SKU - must also
    differ from that SKU's current `certified_by_user_id`."

    Design: Corner/rbac/the_same_user_cannot_record_specimens_and_sign_the_certification
    """
    ctx = _sku_awaiting_signature(client, QUALITY_ENGINEER_USER_ID)
    signed = validate_success(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("CERTIFY"),
            certification_officer_headers(CERTIFICATION_OFFICER_USER_ID),
        )
    )
    assert_field_equals(signed, "certified_by_user_id", CERTIFICATION_OFFICER_USER_ID)

    # The same officer coming back for a second ruling is now barred by their own
    # recorded signature.
    refused = client.sku_certification_decision(
        ctx["sku_id"],
        f.sku_decision_payload("SUSPEND"),
        certification_officer_headers(CERTIFICATION_OFFICER_USER_ID),
    )
    validate_error(refused, ApiErrors.SEGREGATION_OF_DUTIES)
    assert refused.status_code == 409, (
        f"a second self-decision is a 409, got {refused.status_code}"
    )
    assert_field_equals(
        fx.get_product_line(client, ctx["sku_id"]), "certification_status", "CERTIFIED"
    )

    # A third party may rule, because they match neither the recorder nor the signer.
    suspended = validate_success(
        client.sku_certification_decision(
            ctx["sku_id"],
            f.sku_decision_payload("SUSPEND"),
            certification_officer_headers("co-3"),
        )
    )
    assert_field_equals(suspended, "certification_status", "SUSPENDED")
