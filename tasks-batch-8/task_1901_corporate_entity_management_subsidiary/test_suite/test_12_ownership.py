"""Ownership chart claims: DIRECT vs LOOK_THROUGH variants, the inclusive
10000-bps aggregate cap, supersession, self-ownership and cycle rejection,
void freeing capacity, the empty chart, body-FK existence, and OCC on create."""
from test_helpers import (
    ABSENT_UUID,
    SEC1,
    ApiErrorId,
    activate_entity,
    create_agent,
    create_draft_entity,
    create_jurisdiction_j1,
    create_ownership_record,
    create_ownership_record_payload,
    fetch_entity_version,
    setup_base_entity,
    setup_two_active_entities,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_three_entity_chart():
    """J1 + AG1 with ACTIVE entities U, A, E2 and the three ownership edges
    U->A 8000 bps, A->E2 5000 bps, U->E2 1000 bps (all effective 2026-01-01)."""
    j1 = create_jurisdiction_j1()
    ag1 = create_agent(j1["id"])
    u = activate_entity(j1["id"], ag1["id"], legal_name="Ultimate Parent Corp")
    a = activate_entity(j1["id"], ag1["id"], legal_name="Midco A LLC", entity_type="LLC",
                        authorized_shares=None)
    e2 = activate_entity(j1["id"], ag1["id"], legal_name="Opco E Inc")
    create_ownership_record(u["id"], a["id"], 8000)
    create_ownership_record(a["id"], e2["id"], 5000)
    create_ownership_record(u["id"], e2["id"], 1000)
    return u, a, e2


def _node(chart, entity_id):
    for node in chart["nodes"]:
        if node["entity_id"] == entity_id:
            return node
    raise AssertionError(f"node {entity_id} missing from ownership chart")


def test_ownership_look_through_sums_across_paths(api):
    """PRD 3.11: "Each node carries a `look_through_percentage_bps` computed as
    the sum over all directed paths from the root of the product of edge
    percentages, with integer division truncating toward zero applied per edge
    in path order. The root node is emitted with depth 0 and
    `look_through_percentage_bps` null."

    Design: Difficulty/dual_variant_calc/ownership_direct_vs_look_through
    """
    u, a, e2 = _setup_three_entity_chart()

    chart = validate_success(api.get_ownership_chart(u["id"], SEC1))

    root = _node(chart, u["id"])
    assert root["depth"] == 0
    assert root["look_through_percentage_bps"] is None

    # Path U->A: 8000.
    assert _node(chart, a["id"])["look_through_percentage_bps"] == 8000
    # Paths into E2: U->A->E2 contributes 8000 * 5000 / 10000 = 4000, and the
    # direct edge U->E2 contributes 1000; the look-through sum is 5000.
    assert _node(chart, e2["id"])["look_through_percentage_bps"] == 5000


def test_ownership_direct_edges_differ_from_look_through(api):
    """PRD 3.11: "Each edge contributes its direct `percentage_bps`."
    PRD 3.11: "Each node carries a `look_through_percentage_bps` computed as
    the sum over all directed paths from the root of the product of edge
    percentages, with integer division truncating toward zero applied per edge
    in path order."

    Design: Difficulty/dual_variant_calc/ownership_direct_vs_look_through
    """
    u, a, e2 = _setup_three_entity_chart()

    chart = validate_success(api.get_ownership_chart(u["id"], SEC1))

    direct = [
        edge
        for edge in chart["edges"]
        if edge["parent_entity_id"] == u["id"] and edge["subsidiary_entity_id"] == e2["id"]
    ]
    assert len(direct) == 1 and direct[0]["percentage_bps"] == 1000, (
        "the DIRECT variant reports the immediate edge percentage"
    )
    look_through = _node(chart, e2["id"])["look_through_percentage_bps"]
    assert look_through == 5000
    assert direct[0]["percentage_bps"] != look_through, (
        "DIRECT (1000) and LOOK_THROUGH (5000) diverge whenever an indirect path exists"
    )


def test_ownership_full_allocation_boundary_allows_10000(api):
    """PRD 3.11: "For every calendar date, the sum of `percentage_bps` over the
    subsidiary's `ACTIVE` records whose half-open windows cover that date must
    not exceed 10000; violations are rejected with
    `ERR_OWNERSHIP_TOTAL_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/ownership_full_allocation_boundary
    """
    ctx = setup_two_active_entities()
    parent, subsidiary = ctx["parent"], ctx["subsidiary"]

    record = create_ownership_record(parent["id"], subsidiary["id"], 10000)
    assert record["status"] == "ACTIVE"
    assert record["percentage_bps"] == 10000, "exactly 10000 bps (100.00%) is allowed: the cap is inclusive"


def test_ownership_full_allocation_boundary_rejects_10001(api):
    """PRD 3.11: "For every calendar date, the sum of `percentage_bps` over the
    subsidiary's `ACTIVE` records whose half-open windows cover that date must
    not exceed 10000; violations are rejected with
    `ERR_OWNERSHIP_TOTAL_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/ownership_full_allocation_boundary
    """
    ctx = setup_two_active_entities()
    j1, ag1 = ctx["jurisdiction"], ctx["agent"]
    parent, subsidiary = ctx["parent"], ctx["subsidiary"]
    other = activate_entity(j1["id"], ag1["id"], legal_name="Parent Q Inc", authorized_shares=None)
    create_ownership_record(parent["id"], subsidiary["id"], 10000)

    # One extra basis point overlapping the same dates breaches the cap.
    response = api.create_ownership_record(
        create_ownership_record_payload(
            other["id"], subsidiary["id"], 1, "2026-06-01",
            fetch_entity_version(subsidiary["id"]),
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_TOTAL_EXCEEDED)

    rows, meta = validate_paginated(
        api.list_ownership_records(
            SEC1, params={"subsidiary_entity_id": subsidiary["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1


def test_ownership_supersede_sets_end_date(api):
    """PRD 3.11: "A record may supersede an existing record by referencing
    `supersedes_record_id`. The superseded record transitions to `SUPERSEDED`
    and its `end_date` is set to the new record's `effective_date`."

    Design: Corner/state_machines/ownership_supersede_sets_end_date
    """
    ctx = setup_two_active_entities()
    parent, subsidiary = ctx["parent"], ctx["subsidiary"]
    r1 = create_ownership_record(parent["id"], subsidiary["id"], 4000)

    r2 = create_ownership_record(
        parent["id"], subsidiary["id"], 5000,
        effective_date="2026-07-01", supersedes_record_id=r1["id"],
    )
    assert r2["status"] == "ACTIVE"
    assert r2["percentage_bps"] == 5000

    superseded = validate_success(api.get_ownership_record(r1["id"], SEC1))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["end_date"] == "2026-07-01", (
        "stamped from the superseding record's effective_date"
    )

    rows, meta = validate_paginated(
        api.list_ownership_records(
            SEC1, params={"subsidiary_entity_id": subsidiary["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1


def test_self_ownership_rejected(api):
    """PRD 3.11: "The parent and subsidiary must differ; self-ownership is
    rejected with `ERR_SELF_OWNERSHIP`."

    Design: Corner/errors/self_ownership_rejected
    """
    ctx = setup_base_entity(legal_name="Selfown Corp", authorized_shares=None)
    entity = ctx["entity"]

    response = api.create_ownership_record(
        create_ownership_record_payload(
            entity["id"], entity["id"], 5000, "2026-01-01",
            fetch_entity_version(entity["id"]),
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_SELF_OWNERSHIP)


def test_ownership_cycle_rejected(api):
    """PRD 3.11: "The ownership graph among `ACTIVE` records must remain
    acyclic; a record that would create a cycle is rejected with
    `ERR_OWNERSHIP_CYCLE`."

    Design: Corner/errors/ownership_cycle_rejected
    """
    ctx = setup_two_active_entities(parent_name="Up Corp", subsidiary_name="A Corp")
    u, a = ctx["parent"], ctx["subsidiary"]
    create_ownership_record(u["id"], a["id"], 5000)

    # A->U would close the directed cycle U->A->U among ACTIVE records.
    response = api.create_ownership_record(
        create_ownership_record_payload(
            a["id"], u["id"], 1000, "2026-02-01", fetch_entity_version(u["id"])
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_OWNERSHIP_CYCLE)

    rows, meta = validate_paginated(
        api.list_ownership_records(SEC1, params={"status": "ACTIVE"})
    )
    assert meta["total_count"] == 1, "the graph stays a DAG"


def test_ownership_void_frees_capacity_and_double_void_rejected(api):
    """PRD 3.11: "A record may also be voided, transitioning to `VOIDED` and
    freeing its percentage from the subsidiary's aggregate at all covered
    dates. Attempting to void a non-`ACTIVE` record is rejected with
    `ERR_OWNERSHIP_RECORD_NOT_ACTIVE`."

    Design: Corner/errors/ownership_void_frees_capacity_and_double_void_rejected
    """
    ctx = setup_two_active_entities()
    parent, subsidiary = ctx["parent"], ctx["subsidiary"]
    r1 = create_ownership_record(parent["id"], subsidiary["id"], 10000)

    voided = validate_success(
        api.void_ownership_record(r1["id"], {"reason": "clerical error in recorded percentage"}, SEC1)
    )
    assert voided["status"] == "VOIDED"

    # The freed aggregate admits a replacement at the same dates.
    r2 = create_ownership_record(parent["id"], subsidiary["id"], 6000)
    assert r2["status"] == "ACTIVE"

    double_void = api.void_ownership_record(r1["id"], {"reason": "second void attempt"}, SEC1)
    validate_error(double_void, ApiErrorId.ERR_OWNERSHIP_RECORD_NOT_ACTIVE)


def test_ownership_chart_empty_for_isolated_entity(api):
    """PRD 3.11: "The root node is emitted with depth 0 and
    `look_through_percentage_bps` null."
    PRD 3.11: "The ownership chart is a computed read from a root entity. It
    traverses the directed graph of `ACTIVE` ownership records whose windows
    cover the current logical date."

    Design: Corner/endpoints/ownership_chart_empty_for_isolated_entity
    """
    ctx = setup_base_entity(legal_name="Solo Corp", authorized_shares=None)
    entity = ctx["entity"]

    chart = validate_success(api.get_ownership_chart(entity["id"], SEC1))
    assert len(chart["nodes"]) == 1, "an isolated entity's chart is just the root"
    root = chart["nodes"][0]
    assert root["entity_id"] == entity["id"]
    assert root["depth"] == 0
    assert root["look_through_percentage_bps"] is None
    assert chart["edges"] == []


def test_ownership_create_body_fk_not_found(api):
    """PRD 2.5: "Body-supplied foreign keys — such as `jurisdiction_id`,
    `agent_id`, `officer_id`, `agent_appointment_id`, `parent_entity_id`,
    `subsidiary_entity_id`, `delegated_from_grant_id`, `supersedes_record_id`,
    and identifiers inside a resolution's `payload` — are validated for
    existence after path parameters."
    PRD 5: ERR_ENTITY_NOT_FOUND maps to HTTP 404.

    Design: Corner/validations/ownership_create_body_fk_not_found
    """
    j1 = create_jurisdiction_j1()
    subsidiary = create_draft_entity(j1["id"], legal_name="Sub S Inc", authorized_shares=None)

    response = api.create_ownership_record(
        create_ownership_record_payload(
            ABSENT_UUID, subsidiary["id"], 5000, "2026-01-01", subsidiary["version"]
        ),
        SEC1,
    )
    validate_error(response, ApiErrorId.ERR_ENTITY_NOT_FOUND)


def test_occ_stale_version_on_ownership_create(api):
    """PRD 2.7: "Creating an `OwnershipRecord` requires the request body to
    carry `expected_entity_version`, which must equal the current `version` of
    the subsidiary `LegalEntity`. A mismatch is rejected with
    `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_version_on_ownership_create
    """
    ctx = setup_two_active_entities()
    parent, subsidiary = ctx["parent"], ctx["subsidiary"]
    stale_version = fetch_entity_version(subsidiary["id"])

    first = create_ownership_record(parent["id"], subsidiary["id"], 3000)
    assert first["status"] == "ACTIVE"

    # The successful create advanced the subsidiary's version, so the replayed
    # version is stale even though the business content (2000 bps) is valid.
    stale = api.create_ownership_record(
        create_ownership_record_payload(
            parent["id"], subsidiary["id"], 2000, "2026-01-01", stale_version
        ),
        SEC1,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = create_ownership_record(parent["id"], subsidiary["id"], 2000)
    assert fresh["status"] == "ACTIVE"

    rows, meta = validate_paginated(
        api.list_ownership_records(
            SEC1, params={"subsidiary_entity_id": subsidiary["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 2, "aggregate 5000 bps — the 412 was OCC, not business"
