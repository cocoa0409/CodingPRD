"""Access control and validation ordering: authentication, authorization,
dealer ownership scoping, and existence-vs-state gate order."""

import test_helpers as fx
from test_helpers import (
    NON_EXISTENT_UUID,
    PLANT_MANAGER,
    ApiErrorId,
    make_dealer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "A request whose role header is missing or does not name one
    of these six roles is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.9: "Gate one is authentication: the role header must be present
    and name a declared role, else `ERR_UNAUTHENTICATED`."
    PRD §2.9: "Gate four is existence: every identifier in the path and in
    the body must exist, validated left to right through the path, with the
    first missing identifier producing `ERR_NOT_FOUND`."

    Design: Corner/validations/missing_role_header_unauthenticated
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    # No X-User-Role at all, against a non-existent resource: authentication
    # (gate 1) answers before existence (gate 4) is even considered.
    response = api.get_mill(NON_EXISTENT_UUID, headers={"X-User-ID": "op-1"})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)


def test_existence_beats_state_on_missing_order_cancel(api):
    """PRD §2.9: "Gate four is existence: every identifier in the path and in
    the body must exist, validated left to right through the path, with the
    first missing identifier producing `ERR_NOT_FOUND`."
    PRD §2.9: "Gate six is state permission: the target resource must be in a
    state that permits the operation — this is the gate that catches
    stale-cycle color measurements, cancellation of an order already in
    production, completion of a hazardous disposal that never passed through
    its manifest, and adjustments recorded in the wrong batch phase, all as
    `ERR_INVALID_STATE`."

    Design: Corner/validations/existence_beats_state_on_missing_order_cancel
    """
    fx.set_clock("2026-05-01T00:00:00Z")

    # Cancel is a state-transition endpoint, but the order does not exist:
    # existence (gate 4) masks any state reasoning (gate 6).
    response = api.cancel_order(NON_EXISTENT_UUID, PLANT_MANAGER)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND.value, 404)


def test_dealer_cannot_activate_formula_forbidden(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the
    target endpoint — or a `Dealer` attempting to act on a resource belonging
    to a different customer — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §3.1: "A `LabTechnician` activates a `DRAFT` formula only when it has
    at least one colorant line, every line's colorant exists, and no other
    non-`DEPRECATED` formula carries the same `formula_code`
    (`ERR_DUPLICATE_CODE`)."

    Design: Corner/rbac/dealer_cannot_activate_formula_forbidden
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    tb1, c1, f1 = fx.setup_lab_catalog()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ")

    # Formula activation is LabTechnician-exclusive; even a valid dealer is
    # refused, and the formula is untouched.
    refused = api.activate_formula(f1["id"], make_dealer_headers(cu1["id"]))
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN.value, 403)
    assert fx.read_formula(f1["id"])["status"] == "DRAFT"


def test_dealer_cannot_cancel_others_order_forbidden(api):
    """PRD §3.3: "Cancellation is available to the owning `Dealer` or a
    `PlantManager` while the order is `PLACED`, in `RUSH_REVIEW`,
    `SCHEDULED`, or `BLOCKED`, landing in the terminal `CANCELLED` state."
    PRD §2.1: "When `X-User-Role` is `Dealer`, `X-User-ID` is the `id` of the
    acting `Customer`; ownership checks on any resource that references a
    `Customer` compare the resource's foreign-key field to `X-User-ID`."

    Design: Corner/rbac/dealer_cannot_cancel_others_order_forbidden
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1 = fx.setup_lab_catalog_active()
    cu1 = fx.create_customer(name="Sunbelt Paints AZ", home_state_code="AZ")
    cu2 = fx.create_customer(name="Rio Grande Coatings NM",
                             home_state_code="NM")
    o1 = validate_success(
        api.create_order(fx.create_order_payload(cu1["id"], f1["id"]),
                         make_dealer_headers(cu1["id"])),
        expected_status=201,
    )

    # Dealer is in the endpoint's role list, but this dealer does not own it.
    refused = api.cancel_order(o1["id"], make_dealer_headers(cu2["id"]))
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN.value, 403)
    assert fx.read_order(o1["id"])["status"] == "PLACED"

    # The owning dealer cancels the same order.
    cancelled = validate_success(
        api.cancel_order(o1["id"], make_dealer_headers(cu1["id"]))
    )
    assert cancelled["status"] == "CANCELLED"


def test_qc_inspector_cannot_record_fill_forbidden(api):
    """PRD §2.1: "A request whose role is valid but not permitted for the
    target endpoint — or a `Dealer` attempting to act on a resource belonging
    to a different customer — is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §2.9: "Gate two is authorization: the acting role must be listed for
    the endpoint, and entity-backed dealer ownership must hold, else
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/qc_inspector_cannot_record_fill_forbidden
    """
    fx.set_clock("2026-05-01T00:00:00Z")
    _tb1, _c1, f1, m1 = fx.setup_plant()
    b1 = fx.plan_batch(f1["id"], m1["id"], planned_gallons=3)

    # Filling is ProductionOperator-exclusive. The batch is only PLANNED,
    # but authorization (gate 2) fires before the state gate (gate 6).
    refused = api.record_fill(b1["id"],
                              {"size_code": "GALLON", "actual_fill_g": 4600},
                              fx.QC_INSPECTOR)
    validate_error(refused, ApiErrorId.ERR_FORBIDDEN.value, 403)

    containers, meta = validate_paginated(
        api.list_containers(fx.QC_INSPECTOR, params={"batch_id": b1["id"]})
    )
    assert containers == []
    assert meta["total_count"] == 0
