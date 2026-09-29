"""The pinned parent version, the version counter itself, and derived totals.

Two creations that must prove they were looking at a current parent, the counter
that moves on writes and stands still on reads, the weight rollup recomputed on
every append, and the acceptance whose whole cascade is already in its own
response.
"""

from test_helpers import (
    ADMIN,
    ENGINEER,
    LOGISTICS,
    PLANNER,
    SALES,
    accept_quote,
    anchored_bom,
    assert_credit_ledger_conserved,
    assert_order_dimensions,
    assert_pounds_ledger_conserved,
    assert_weight,
    authorize_builder,
    cancel_load,
    cancel_order_release,
    chain_authorized_builder,
    chain_locked_configuration,
    chain_sealed_order,
    connection_component_payload,
    create_builder,
    create_configuration,
    create_design,
    create_design_payload,
    create_jurisdiction,
    create_quote,
    create_shipment_load_payload,
    get_builder,
    get_configuration,
    get_design,
    get_order,
    get_quote,
    issue_quote,
    list_design_components,
    lock_configuration,
    make_builder_headers,
    member_component_payload,
    plan_load,
    release_order,
    release_payload,
    set_clock,
    suspend_builder,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The unload window the primary-frame truck asks for.
FRAME_UNLOAD_WINDOW = {
    "unload_window_start": "2026-09-18T08:00:00Z",
    "unload_window_end": "2026-09-18T12:00:00Z",
}


def test_01_a_design_may_only_be_opened_against_the_version_it_last_saw(api):
    """The lock advanced the configuration, so the pre-lock pin is stale.

    PRD §2.8: "Opening an engineering design requires
    ``expected_configuration_version`` as a mandatory input field carrying the
    client's last observed ``version`` of the target building configuration."

    PRD §2.8: "If that value does not equal the configuration's current
    ``version``, the request is rejected with ``ERR_STALE_CONFIGURATION_VERSION``
    at HTTP 412 and no design is created."

    PRD §3.6: "A freshly opened design is ``DRAFT`` with ``frame_weight_lbs``,
    ``shippable_weight_lbs``, ``component_count`` and ``revision_count`` all at 0,
    and ``submitted_by_user_id`` and ``reviewed_by_user_id`` both null."

    Design: Corner/complexity_layers/a_stale_expected_configuration_version_blocks_the_design_create_with_412
    """
    chain = chain_authorized_builder()
    draft = create_configuration(chain["builder"]["id"], chain["jurisdiction"]["id"])

    locked = lock_configuration(draft["id"])

    # The lock is a write, so it bumped the version the client had in hand.
    assert locked["version"] == draft["version"] + 1
    assert locked["status"] == "LOCKED"

    stale = api.create_design(create_design_payload(draft["id"], draft["version"]), ENGINEER)

    refused = validate_error(
        stale, "ERR_STALE_CONFIGURATION_VERSION", expected_status=412
    )
    # The configuration is LOCKED; only the client's view of it is behind.
    assert refused["error_id"] != "ERR_CONFIGURATION_NOT_LOCKED"
    _, meta = validate_paginated(api.list_designs(ENGINEER))
    assert meta["total_count"] == 0
    # A rejected write bumps nothing.
    assert get_configuration(draft["id"])["version"] == locked["version"]

    design = create_design(draft["id"], locked["version"])

    assert design["status"] == "DRAFT"
    assert design["revision_count"] == 0
    assert design["component_count"] == 0
    assert design["submitted_by_user_id"] is None


def test_02_a_load_may_only_be_planned_against_the_version_it_last_saw(api):
    """Release moved the order, so the pin taken at seal time no longer holds.

    PRD §2.8: "Planning a shipment load requires ``expected_order_version`` as a
    mandatory input field carrying the client's last observed ``version`` of the
    target order."

    PRD §2.8: "A mismatch against the order's current ``version`` is rejected with
    ``ERR_STALE_ORDER_VERSION`` at HTTP 412 and no load is created."

    PRD §2.9: "At release to fabrication an order's
    ``total_shippable_weight_lbs`` is fixed, ``assigned_weight_lbs`` is set to 0
    and ``unassigned_weight_lbs`` is set equal to the total."

    Design: Corner/complexity_layers/a_stale_expected_order_version_blocks_load_planning_and_cancel_release_with_412
    """
    chain = chain_sealed_order(components=anchored_bom())
    sealed = chain["order"]

    released = release_order(sealed["id"], sealed["version"])

    # Release writes the order and its ledger.
    assert released["version"] == sealed["version"] + 1
    # C-1 plus AB-1; the two connection details contribute nothing.
    assert_weight(released["total_shippable_weight_lbs"], 15308.80)
    assert_weight(released["unassigned_weight_lbs"], 15308.80)
    assert_weight(released["assigned_weight_lbs"], 0)

    stale = api.create_shipment_load(
        create_shipment_load_payload(
            sealed["id"], sealed["version"],
            component_marks=["C-1"], erection_stage="PRIMARY_FRAME",
            **FRAME_UNLOAD_WINDOW,
        ),
        LOGISTICS,
    )

    validate_error(stale, "ERR_STALE_ORDER_VERSION", expected_status=412)
    _, meta = validate_paginated(
        api.list_shipment_loads(LOGISTICS, params={"order_id": sealed["id"]})
    )
    assert meta["total_count"] == 0

    load = plan_load(
        sealed["id"], expected_order_version=released["version"],
        component_marks=["C-1"], erection_stage="PRIMARY_FRAME",
        **FRAME_UNLOAD_WINDOW,
    )

    assert_weight(load["gross_weight_lbs"], 15275.80)
    assert_pounds_ledger_conserved(get_order(sealed["id"]))


def test_03_the_version_pin_is_checked_before_the_active_work_test(api):
    """A cancel-release on a stale pin reports 412, never the work conflict.

    PRD §2.8: "The same ``expected_order_version`` field, with the same mismatch
    code ``ERR_STALE_ORDER_VERSION`` at HTTP 412, is also required on release to
    fabrication and on cancellation of a release, for the same reason: both rewrite
    the order's money and pounds ledgers wholesale."

    PRD §2.5: "Sixth comes version pinning, described in §2.8."

    PRD §2.9: "Cancelling a release resets all three fields to 0."

    Design: Corner/complexity_layers/a_stale_expected_order_version_blocks_load_planning_and_cancel_release_with_412
    """
    chain = chain_sealed_order(components=anchored_bom())
    released = release_order(chain["order"]["id"], chain["order"]["version"])
    order_id = released["id"]
    load = plan_load(
        order_id, expected_order_version=released["version"],
        component_marks=["C-1"], erection_stage="PRIMARY_FRAME",
        **FRAME_UNLOAD_WINDOW,
    )
    assert_weight(load["gross_weight_lbs"], 15275.80)

    stale_cancel = api.cancel_order_release(
        order_id, release_payload(released["version"]), PLANNER
    )

    # The planned load both staled the pin and constitutes active work; the
    # version band is evaluated first.
    refused = validate_error(stale_cancel, "ERR_STALE_ORDER_VERSION", expected_status=412)
    assert refused["error_id"] != "ERR_ORDER_HAS_ACTIVE_WORK"
    still_released = get_order(order_id)
    assert still_released["production_status"] == "PROD_RELEASED"
    assert_weight(still_released["total_shippable_weight_lbs"], 15308.80)

    cancel_load(load["id"])
    current = get_order(order_id)

    cancelled = cancel_order_release(order_id, current["version"])

    assert cancelled["production_status"] == "PROD_NOT_RELEASED"
    assert_weight(cancelled["total_shippable_weight_lbs"], 0)
    assert_weight(cancelled["assigned_weight_lbs"], 0)
    assert_weight(cancelled["unassigned_weight_lbs"], 0)


def test_04_the_version_counter_moves_on_writes_and_stands_still_on_reads():
    """Three writes, three increments, and three reads that change nothing.

    PRD §2.4: "Most resources additionally carry ``updated_at``, an ISO 8601 UTC
    timestamp with the same three-fractional-digit format that is refreshed on
    every mutation, and ``version``, an integer that starts at 1 on creation and
    increases by exactly 1 on every mutation of that row."

    PRD §3.2: "Authorization is the transition into ``AUTHORIZED``, and it is
    available from both ``PENDING_AUTHORIZATION`` and ``SUSPENDED`` — the same
    operation onboards a new builder and rehabilitates a suspended one."

    PRD §2.4: "Every resource also carries ``created_at``, an ISO 8601 UTC
    timestamp with three fractional digits recorded when the row is inserted."

    Design: Corner/complexity_layers/version_advances_on_every_write_and_never_on_a_read
    """
    set_clock()
    jurisdiction = create_jurisdiction()
    created = create_builder(jurisdiction["id"])

    assert created["version"] == 1
    assert created["status"] == "PENDING_AUTHORIZATION"
    first_read = get_builder(created["id"], headers=SALES)
    second_read = get_builder(created["id"], headers=SALES)
    # Reads never advance the counter.
    assert first_read["version"] == created["version"]
    assert second_read["version"] == created["version"]

    authorized = authorize_builder(created["id"])
    set_clock("2026-08-06T00:00:00Z")
    suspended = suspend_builder(created["id"])
    set_clock("2026-08-07T00:00:00Z")
    reauthorized = authorize_builder(created["id"])

    assert authorized["version"] == 2
    assert suspended["version"] == 3
    assert reauthorized["version"] == 4

    final_read = get_builder(created["id"], headers=ADMIN)

    # The row held AUTHORIZED at version 2 as well, so version is not derivable
    # from status.
    assert final_read["version"] == 4
    assert final_read["status"] == "AUTHORIZED"
    assert authorized["status"] == "AUTHORIZED"
    for row in (first_read, authorized, suspended, reauthorized, final_read):
        assert row["created_at"] == created["created_at"]
    assert authorized["updated_at"] == "2026-08-05T00:00:00.000Z"
    assert suspended["updated_at"] == "2026-08-06T00:00:00.000Z"
    assert reauthorized["updated_at"] == "2026-08-07T00:00:00.000Z"
    assert final_read["updated_at"] == reauthorized["updated_at"]


def test_05_every_append_recomputes_the_two_weight_totals(api):
    """Frame steel, an anchor package and a detail each land differently.

    PRD §3.6: "The design's ``frame_weight_lbs`` is then the sum of
    ``line_weight_lbs`` over only those components whose ``component_class`` is
    ``PRIMARY_FRAME_MEMBER`` or ``SECONDARY_MEMBER``, rounded half up to two
    decimal places, and ``shippable_weight_lbs`` is the sum of ``line_weight_lbs``
    over every component of the design regardless of class, likewise rounded half
    up to two decimal places."

    PRD §3.6: "A ``CONNECTION_DETAIL`` component has ``unit_weight_lbs`` of 0 and
    ``line_weight_lbs`` of 0 — a detail is a drawing, not steel."

    PRD §3.6: "``component_count`` is the plain count of component rows on the
    design."

    PRD §2.4: "Design components are the single exception: a component row carries
    only ``id`` and ``created_at``."

    Design: Corner/complexity_layers/design_weight_rollups_reconcile_after_every_component_append
    """
    chain = chain_locked_configuration()
    design = create_design(
        chain["configuration"]["id"], chain["configuration"]["version"]
    )

    empty = get_design(design["id"])
    assert empty["component_count"] == 0
    assert_weight(empty["frame_weight_lbs"], 0)
    assert_weight(empty["shippable_weight_lbs"], 0)
    # The load combination arithmetic ran at creation and the appends never touch
    # it.
    assert_weight(empty["required_moment_kip_ft"], 1010.94)
    assert empty["governing_combination"] == "ASD_D_PLUS_0_6W"

    validate_success(
        api.create_design_component(design["id"], member_component_payload(), ENGINEER),
        expected_status=201,
    )
    after_column = get_design(design["id"])
    # 24.5 ft at 62.35 lb/ft rounds to 1527.58 per column, times ten.
    assert after_column["component_count"] == 1
    assert_weight(after_column["frame_weight_lbs"], 15275.80)
    assert_weight(after_column["shippable_weight_lbs"], 15275.80)

    validate_success(
        api.create_design_component(
            design["id"],
            member_component_payload(
                mark="AB-1", component_class="ANCHOR_PACKAGE",
                member_type="ANCHOR_BOLT", erection_stage="ANCHORAGE",
                quantity=10, length_ft=1.5, weight_per_ft=2.2,
            ),
            ENGINEER,
        ),
        expected_status=201,
    )
    after_anchors = get_design(design["id"])
    # The anchor package ships but is not frame steel.
    assert after_anchors["component_count"] == 2
    assert_weight(after_anchors["frame_weight_lbs"], 15275.80)
    assert_weight(after_anchors["shippable_weight_lbs"], 15308.80)

    validate_success(
        api.create_design_component(
            design["id"],
            connection_component_payload(
                mark="K-1", connection_type="KNEE", capacity_moment_kip_ft=1100
            ),
            ENGINEER,
        ),
        expected_status=201,
    )
    after_detail = get_design(design["id"])

    assert after_detail["component_count"] == 3
    assert_weight(after_detail["frame_weight_lbs"], 15275.80)
    assert_weight(after_detail["shippable_weight_lbs"], 15308.80)
    assert_weight(after_detail["required_moment_kip_ft"], 1010.94)
    assert after_detail["governing_combination"] == "ASD_D_PLUS_0_6W"
    rows = list_design_components(design["id"])
    assert len(rows) == 3
    detail = next(row for row in rows if row["mark"] == "K-1")
    assert_weight(detail["unit_weight_lbs"], 0)
    assert_weight(detail["line_weight_lbs"], 0)
    for row in rows:
        assert "version" not in row


def test_06_an_acceptance_reports_its_whole_cascade_in_its_own_response():
    """The order, the ledger and the source quote all settle inside the request.

    PRD §2.10: "When an upstream fact changes, the system does not mark downstream
    artifacts for later reconciliation — it propagates the consequence to its full
    depth inside the same request, and every row touched has its ``updated_at``
    refreshed and its ``version`` incremented by 1."

    PRD §3.5: "Acceptance mints exactly one order and returns it."

    PRD §3.5: "In the same request the builder's ``credit_used_cents`` increases by
    the quote's ``quoted_price_cents`` and ``credit_available_cents`` is
    recomputed, the quote's ``status`` becomes ``ACCEPTED``, and both the quote's
    ``version`` and the builder's ``version`` increment."

    PRD §2.9: "The invariant is that used plus available equals the limit at all
    times."

    Design: Corner/consistency_model/every_cascade_and_rollup_is_visible_in_the_response_that_caused_it
    """
    chain = chain_locked_configuration()
    builder_id = chain["builder"]["id"]
    quote = create_quote(builder_id, chain["configuration"]["id"])
    issue_quote(quote["id"])
    assert quote["quoted_price_cents"] == 8589227

    order = accept_quote(quote["id"], builder_id)

    # The response that caused the cascade already carries its result.
    assert_order_dimensions(order, "ENG_PENDING", "PROD_NOT_RELEASED")
    assert order["quote_id"] == quote["id"]
    assert order["builder_id"] == builder_id

    builder = get_builder(builder_id, headers=SALES)
    accepted_quote = get_quote(quote["id"], headers=SALES)
    order_read = get_order(order["id"], headers=SALES)

    # The ledger moved inside the accept, not afterwards.
    assert builder["credit_used_cents"] == 8589227
    assert builder["credit_available_cents"] == 191410773
    assert_credit_ledger_conserved(builder)
    assert builder["credit_used_cents"] + builder["credit_available_cents"] == 200000000
    # The source row was updated in the same transaction.
    assert accepted_quote["status"] == "ACCEPTED"
    # No field settles to a different value on a second look.
    assert order_read == order
    assert_credit_ledger_conserved(
        get_builder(builder_id, headers=make_builder_headers(builder_id))
    )
