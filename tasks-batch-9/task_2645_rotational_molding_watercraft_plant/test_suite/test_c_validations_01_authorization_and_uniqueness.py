"""Corner validations, band 1 and band 3: who may act, whose identity resolves, and
which business codes are unique.

PRD.md section 2.7 fixes the evaluation order every endpoint follows: "Each endpoint
evaluates its applicable checks in a fixed ascending priority order and returns on the
first failure it finds; no endpoint reports two errors, and no later check runs after an
earlier one has failed."  Its first band is "**Authentication and authorization** —
header presence, role validity, endpoint permission, identity resolution, role/identity
agreement, customer scope", and its third is "**Schema, range, enum and uniqueness** —
required fields, JSON types, numeric bounds, enum membership, measurement-count
minimums, date-window sanity, and business-code uniqueness".

Each test in this module drives a request that is defective in a way band 1 or band 3
catches, and pairs it with the otherwise-identical request that succeeds, so the error
is attributable to the single header or the single field under test and to nothing else.
PRD.md section 2.10 supplies the "nothing was written" half of every assertion: "when
any validation the triggering request declares fails, nothing at all is persisted: no
child row, no ledger movement, no status change, no version increment."
"""

from test_helpers import (
    ApiErrorId,
    CERT_FIXTURE_ASSEMBLY,
    CERT_RESIN_BLENDING,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    ROLE_PLANT_ADMIN,
    ROLE_RESIN_TECHNICIAN,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_resin_ledger_conserved,
    build_user_headers,
    create_plant_baseline,
    create_technician,
    production_order_payload,
    resin_charge_payload,
    resin_lot_version,
    retire_mold_payload,
    setup_scheduled_cycle,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    warehouse_payload,
    zone,
)


def test_empty_user_id_header_is_missing_auth_and_leaves_no_order_row(api, admin_headers):
    """An empty ``X-User-ID`` is a *missing* header, not an unresolved identity.

    PRD.md section 2.1: "Every request must carry two headers: `X-User-ID`, which
    identifies the acting principal, and `X-User-Role`, which names the role being
    asserted. When either header is absent or empty the request is rejected with
    `ERR_MISSING_AUTH_HEADERS` (HTTP 401)."

    That is the only defect available here, because for the acting role PRD.md
    section 2.1 also says: "Three roles — `PlantAdmin`, `LogisticsPlanner` and
    `WarrantyAgent` — have an opaque identity: any non-empty `X-User-ID` string is
    accepted and no lookup is performed."  So `ERR_IDENTITY_NOT_FOUND`, which
    section 2.1 reserves for the entity-backed roles, cannot be the answer.

    The rejection is a gate rather than an audit note: PRD.md section 2.10 says that
    "when any validation the triggering request declares fails, nothing at all is
    persisted: no child row, no ledger movement, no status change, no version
    increment", so the `order_code` the refused body carried is still free and the
    byte-identical retry under a non-empty id succeeds.

    Design: Corner/validations/val_violation_missing_auth_headers_rejected_before_any_write
    """
    ctx = create_plant_baseline()
    payload = production_order_payload(
        ctx["product_model_id"], ctx["warehouse_id"], ordered_qty=2
    )

    refused = api.create_production_order(payload, build_user_headers("", ROLE_PLANT_ADMIN))
    validate_error(refused, ApiErrorId.MISSING_AUTH_HEADERS, 401)

    # Nothing was written: the site the refused order targeted holds no orders at all.
    _rows, meta = validate_paginated(
        api.list_production_orders({"target_warehouse_id": ctx["warehouse_id"]}, admin_headers)
    )
    assert meta["total_count"] == 0, (
        "a request refused at PRD.md section 2.7 band 1 must not have created a row"
    )

    # The same body, differing only in X-User-ID, is accepted.
    accepted = validate_success(api.create_production_order(payload, admin_headers), 201)
    assert accepted["order_code"] == payload["order_code"]
    assert accepted["status"] == "DRAFT"
    assert accepted["version"] == 1

    rows, meta = validate_paginated(
        api.list_production_orders({"target_warehouse_id": ctx["warehouse_id"]}, admin_headers)
    )
    assert meta["total_count"] == 1, "exactly one of the two attempts may persist"
    assert [row["order_code"] for row in rows] == [payload["order_code"]]


def test_role_not_permitted_is_reported_before_an_absent_path_id_is_resolved(api, admin_headers):
    """The endpoint-permission check hides which identifiers exist.

    PRD.md section 4: "The Authorized Role(s) column is exhaustive: a syntactically
    valid request from a role not listed for that row is rejected with
    `ERR_ROLE_NOT_PERMITTED` and HTTP 403 before any business rule runs."  The row for
    `POST /molds/{mold_id}/retire` lists `PlantAdmin` alone, so `MoldingOperator` is
    refused there.

    PRD.md section 2.7 ranks the two candidate failures: band 1 is "**Authentication
    and authorization** — header presence, role validity, endpoint permission,
    identity resolution, role/identity agreement, customer scope" and band 2 is
    "**Existence** — path identifiers first, then body foreign keys, each reported
    with its entity-specific not-found code where one exists and with
    `ERR_RESOURCE_NOT_FOUND` otherwise".  An unauthorised caller therefore gets the
    identical 403 whether the path id exists or not, while the authorised caller does
    reach band 2 and is told the tool is absent.

    Design: Corner/validations/val_priority_ordering_role_not_permitted_beats_unresolved_path_id
    """
    ctx = create_plant_baseline()
    operator_headers = ctx["operator_headers"]
    absent_mold_id = "mold-p6-absent-0000"

    # Both defects at once: a role the endpoint does not list AND a path id that
    # resolves to nothing. Band 1 wins.
    on_absent = api.retire_mold(
        absent_mold_id,
        retire_mold_payload("probing an id the caller may not touch"),
        operator_headers,
    )
    validate_error(on_absent, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    # The same unauthorised role against a REAL tool is indistinguishable.
    on_real = api.retire_mold(
        ctx["mold_id"],
        retire_mold_payload("probing a real id the caller may not touch"),
        operator_headers,
    )
    validate_error(on_real, ApiErrorId.ROLE_NOT_PERMITTED, 403)

    # Band 2 does fire once band 1 is satisfied, which proves the two 403s above were
    # ordering and not a missing existence check.
    authorised_on_absent = api.retire_mold(
        absent_mold_id, retire_mold_payload("authorised caller, absent id"), admin_headers
    )
    assert authorised_on_absent.status_code == 404, (
        "PRD.md section 2.7 band 2 resolves the path id for an authorised caller"
    )
    validate_error_is_one_of(
        authorised_on_absent,
        [ApiErrorId.MOLD_NOT_FOUND, ApiErrorId.RESOURCE_NOT_FOUND],
    )

    # Neither refused retire wrote anything.
    mold = api.read_entity("get_mold", ctx["mold_id"], admin_headers)
    assert mold["status"] == "AVAILABLE"
    assert mold["version"] == 1


def test_resin_charge_as_a_technician_of_another_role_is_a_role_identity_mismatch(
    api, unresolvable_role_headers
):
    """Asserting `ResinTechnician` with another role's technician id is a 403 mismatch.

    PRD.md section 2.1: "Because all four shop-floor roles share a single backing
    entity, the role asserted in the header must agree with the backing technician's
    `role_code`: `ResinTechnician` requires `role_code` `RESIN_TECH`, `MoldingOperator`
    requires `MOLDING_OPERATOR`, `AssemblyTechnician` requires `ASSEMBLY_TECH`, and
    `QualityInspector` requires `QUALITY_INSPECTOR`. Asserting one shop-floor role with
    the identifier of a technician carrying a different `role_code` fails with
    `ERR_ROLE_IDENTITY_MISMATCH` (HTTP 403)."

    The acting technician here deliberately holds `RESIN_BLENDING` as well as
    `FIXTURE_ASSEMBLY`, so the certification rule of PRD.md section 2.1 — "A technician
    who lacks the certification an operation requires is refused with
    `ERR_TECHNICIAN_NOT_CERTIFIED` (HTTP 403)" — has nothing to complain about and the
    role disagreement is the request's only defect.

    The unresolved-identity probe is ordered against it by PRD.md section 2.7 band 1,
    which lists "identity resolution" ahead of "role/identity agreement": an id backing
    no `Technician` row therefore never reaches the role comparison, and PRD.md
    section 2.1 names that failure "if it does not, the request fails with
    `ERR_IDENTITY_NOT_FOUND` (HTTP 401)".

    Design: Corner/validations/val_violation_role_identity_mismatch_when_the_technician_holds_another_role
    """
    ctx = setup_scheduled_cycle(charge=False, lot_overrides={"received_kg": 100.0})
    lot_id = ctx["resin_lot_id"]

    # A real Technician row whose role_code is ASSEMBLY_TECH, but which also carries
    # RESIN_BLENDING so that no certification rule can explain the refusal.
    dual_certified_assembler = create_technician(
        "ASSEMBLY_TECH", certifications=[CERT_FIXTURE_ASSEMBLY, CERT_RESIN_BLENDING]
    )
    assert dual_certified_assembler["technician"]["role_code"] == "ASSEMBLY_TECH"
    assert sorted(dual_certified_assembler["technician"]["certifications"]) == sorted(
        [CERT_FIXTURE_ASSEMBLY, CERT_RESIN_BLENDING]
    )

    body = resin_charge_payload(
        ctx["molding_cycle_id"],
        lot_id,
        resin_lot_version(lot_id),
        charge_kg=20.0,
        regrind_kg=2.0,
    )

    mismatched = api.create_resin_charge(
        body,
        build_user_headers(dual_certified_assembler["technician_id"], ROLE_RESIN_TECHNICIAN),
    )
    validate_error(mismatched, ApiErrorId.ROLE_IDENTITY_MISMATCH, 403)

    # Same body, an id that resolves to no Technician row: identity resolution first.
    unresolved = api.create_resin_charge(body, unresolvable_role_headers["ResinTechnician"])
    validate_error(unresolved, ApiErrorId.IDENTITY_NOT_FOUND, 401)

    # Same body again, this time from a genuine RESIN_TECH: the body was legal all along.
    accepted = validate_success(
        api.create_resin_charge(body, ctx["resin_tech_headers"]), 201
    )
    assert accepted["status"] == "RESERVED"
    assert accepted["created_by_technician_id"] == ctx["resin_technician_id"]

    # Exactly one of the three attempts moved mass.
    lot = api.read_entity("get_resin_lot", lot_id, ctx["admin_headers"])
    assert_decimal_equals(lot["available_kg"], 80.0, Q_MASS, "available_kg")
    assert_decimal_equals(lot["reserved_kg"], 20.0, Q_MASS, "reserved_kg")
    assert_decimal_equals(lot["consumed_kg"], 0.0, Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(lot)


def test_duplicate_zone_code_inside_one_site_is_refused_but_reused_across_sites(
    api, admin_headers, planner_headers
):
    """`zone_code` uniqueness is scoped to one site's `zones` array; `site_code` is global.

    PRD.md section 2.8 states both scopes in one sentence of the `Warehouse` field
    reference: "Client-supplied: `site_code` (required, 2–32 characters, globally unique,
    duplicate rejected as `ERR_DUPLICATE_CODE`); `footprint_capacity_cube_m3` (required,
    greater than zero, four decimals, and must equal the sum of the zone capacities
    rounded to four decimals or `ERR_VALIDATION`); `zones` (required array of 1 to 12
    elements, each an object holding `zone_code` — 2–16 characters and unique within the
    site, a repeat being `ERR_DUPLICATE_CODE` — and `capacity_cube_m3`, greater than zero
    with four decimals)".  The two scopes together make the zone scoping falsifiable: an
    implementation holding a global zone index would wrongly refuse the second site
    below, whose zone reuses the first site's `Z1`.

    The refused body is otherwise impeccable — 5.0000 plus 5.0000 equals the declared
    10.0000 exactly, so the capacity-sum clause of that same sentence cannot explain the
    409 — and a separate body violating only that sum is checked here as the contrast.
    PRD.md section 3.1 restates it: "Warehouses are registered by `PlantAdmin` or
    `LogisticsPlanner` with a `zones` array whose per-zone `capacity_cube_m3` values must
    sum, at four decimals, to the declared `footprint_capacity_cube_m3`."  The same
    section supplies the two defaults asserted below: "`restricted_threshold_pct` and
    `frozen_threshold_pct` default to 85.00 and 95.00 when omitted."

    Design: Corner/validations/val_violation_duplicate_zone_code_within_one_warehouse_rejected
    """
    # Two zones sharing one zone_code inside a single body, capacities summing exactly.
    duplicated = api.create_warehouse(
        warehouse_payload(
            footprint_capacity_cube_m3=10.0,
            zones=[zone("Z1", 5.0), zone("Z1", 5.0)],
        ),
        admin_headers,
    )
    validate_error(duplicated, ApiErrorId.DUPLICATE_CODE, 409)

    # A first accepted site. The two threshold fields are omitted so that the defaults
    # PRD.md section 2.8 declares are what the response has to show.
    first_payload = warehouse_payload(
        footprint_capacity_cube_m3=10.0, zones=[zone("Z1", 4.0), zone("Z2", 6.0)]
    )
    del first_payload["restricted_threshold_pct"]
    del first_payload["frozen_threshold_pct"]
    first = validate_success(api.create_warehouse(first_payload, admin_headers), 201)
    assert_decimal_equals(first["committed_cube_m3"], 0.0, Q_CUBE, "committed_cube_m3")
    assert_decimal_equals(first["utilization_pct"], 0.0, Q_PERCENT, "utilization_pct")
    assert first["posture"] == "NORMAL"
    assert_decimal_equals(
        first["restricted_threshold_pct"], 85.0, Q_PERCENT, "restricted_threshold_pct"
    )
    assert_decimal_equals(
        first["frozen_threshold_pct"], 95.0, Q_PERCENT, "frozen_threshold_pct"
    )

    # A second site reusing the zone_code Z1: accepted, and accepted from the other
    # authorised role of the same endpoint row.
    second = validate_success(
        api.create_warehouse(
            warehouse_payload(footprint_capacity_cube_m3=3.0, zones=[zone("Z1", 3.0)]),
            planner_headers,
        ),
        201,
    )
    assert second["id"] != first["id"]

    # site_code, by contrast, IS global: a distinct zones array does not rescue it.
    repeated_site_code = api.create_warehouse(
        warehouse_payload(
            site_code=first["site_code"],
            footprint_capacity_cube_m3=8.0,
            zones=[zone("ZA", 8.0)],
        ),
        admin_headers,
    )
    validate_error(repeated_site_code, ApiErrorId.DUPLICATE_CODE, 409)

    # Unique zone codes but a sum that misses the declared footprint.
    bad_sum = api.create_warehouse(
        warehouse_payload(
            footprint_capacity_cube_m3=10.0, zones=[zone("Z1", 4.0), zone("Z2", 5.0)]
        ),
        admin_headers,
    )
    validate_error(bad_sum, ApiErrorId.VALIDATION, 422)

    # Both accepted sites are readable and internally consistent.
    first_summary = api.read_footprint_summary(first["id"], planner_headers)
    assert_footprint_summary_consistent(first_summary)
    assert first_summary["blocked_production_order_count"] == 0
    first_zones = {z["zone_code"]: z for z in first_summary["zones"]}
    assert sorted(first_zones) == ["Z1", "Z2"]
    assert_decimal_equals(first_zones["Z1"]["remaining_cube_m3"], 4.0, Q_CUBE, "Z1 remaining")
    assert_decimal_equals(first_zones["Z2"]["remaining_cube_m3"], 6.0, Q_CUBE, "Z2 remaining")
    assert first_zones["Z1"]["stored_unit_count"] == 0
    assert first_zones["Z2"]["stored_unit_count"] == 0

    second_summary = api.read_footprint_summary(second["id"], planner_headers)
    assert_footprint_summary_consistent(second_summary)
    second_zones = {z["zone_code"]: z for z in second_summary["zones"]}
    assert sorted(second_zones) == ["Z1"]
    assert_decimal_equals(second_zones["Z1"]["remaining_cube_m3"], 3.0, Q_CUBE, "Z1 remaining")
