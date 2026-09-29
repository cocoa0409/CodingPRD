"""
Version guards on the two parent records, and reads that never lag their writes.

Two writes in this API demand that the client prove which picture of a parent
record it planned against: scheduling a maintenance order states the parcel
version it read, and planning a demolition run states the funding source
version it read. Both are exercised the same way here - an unrelated writer
moves the parent between the read and the write, the write is refused, nothing
is left behind, and the identical body replayed at the refreshed version is
accepted.

The last two tests look at the other side of the same coin: once a write has
been accepted, the very next read - including the derived ledger and the
computed authority-wide position - already reflects it.
"""

from test_helpers import (
    INTAKE_1,
    INV_1,
    TREAS_1,
    ApiErrorId,
    assert_ledger_position,
    assert_maintenance_order,
    expected_mow_estimate_cents,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)

# Ten thousand square feet of mowing: ten started thousand-square-foot blocks at
# 1,850 cents, plus county overhead of 6.5 percent on that subtotal.
MOW_ESTIMATE_CENTS = expected_mow_estimate_cents(10000)


# ── a parcel whose version moved under the client ───────────────────────────
def _acquired_parcel_moved_by_an_unrelated_writer(api):
    """
    An ACQUIRED 10,000 square foot parcel on an unrestricted 1,000,000-cent
    source, with a licensed mowing crew. The client reads the parcel's version,
    and intake then files a code-enforcement snapshot on the same parcel, which
    advances that version behind the client's back.
    """
    source = fixtures.create_funding_source(
        api,
        name="OCC Property Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    parcel = fixtures.create_property(
        api,
        address="3320 Hornbeam Row",
        situs_ward=6,
        lot_area_sqft=10000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    fixtures.acquire_property(
        api, parcel["id"], source["id"], donor_name="Hornbeam Trust"
    )
    contractor = fixtures.create_contractor(
        api,
        name="Hornbeam Mowing",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )

    stale_version = fixtures.property_version(api, parcel["id"])
    refreshed = fixtures.post_code_violations(
        api, parcel["id"], open_code_violation_count=1, nuisance_complaint_count=2
    )

    return {
        "source_id": source["id"],
        "property_id": parcel["id"],
        "contractor_id": contractor["id"],
        "stale_version": stale_version,
        "current_version": refreshed["version"],
    }


def _mow_order_payload(scene, expected_property_version):
    """The same order body throughout: only the stated parcel version differs."""
    return factories.maintenance_order_payload(
        scene["contractor_id"],
        scene["source_id"],
        expected_property_version,
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-06T00:00:00Z",
    )


def test_scheduling_against_a_stale_parcel_version_is_refused_and_writes_nothing(api):
    """
    A maintenance order that states a parcel version an unrelated code-enforcement posting has already moved past is refused, and no order and no commitment are left behind.

    If its value differs from the parcel's current `version` — and code-violation reports, tax roll postings, order completions, adjacency recordings and every cascade in this document advance that `version` — the request is rejected with `ERR_STALE_PROPERTY_VERSION` (412) and nothing is written.

    Design: Corner/cross_cutting_complexity_layers/stale_property_version_rejected_then_current_version_accepted
    """
    scene = _acquired_parcel_moved_by_an_unrelated_writer(api)
    assert scene["current_version"] == scene["stale_version"] + 1

    response = api.create_maintenance_order(
        scene["property_id"], _mow_order_payload(scene, scene["stale_version"]), INV_1
    )

    validate_error(response, ApiErrorId.STALE_PROPERTY_VERSION.value, 412)
    assert fixtures.list_orders(api, property_id=scene["property_id"]) == []
    ledger = fixtures.read_funding_source(api, scene["source_id"])
    assert_ledger_position(
        ledger,
        authorized_cents=1000000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=1000000,
    )
    parcel = fixtures.read_property(api, scene["property_id"])
    assert parcel["version"] == scene["current_version"]


def test_the_same_order_replayed_at_the_refreshed_parcel_version_is_accepted(api):
    """
    Replaying the identical order body with the parcel version freshly re-read succeeds, which shows the refusal was about staleness alone.

    If its value differs from the parcel's current `version` — and code-violation reports, tax roll postings, order completions, adjacency recordings and every cascade in this document advance that `version` — the request is rejected with `ERR_STALE_PROPERTY_VERSION` (412) and nothing is written.

    Design: Corner/cross_cutting_complexity_layers/stale_property_version_rejected_then_current_version_accepted
    """
    scene = _acquired_parcel_moved_by_an_unrelated_writer(api)

    validate_error(
        api.create_maintenance_order(
            scene["property_id"],
            _mow_order_payload(scene, scene["stale_version"]),
            INV_1,
        ),
        ApiErrorId.STALE_PROPERTY_VERSION.value,
        412,
    )

    order = validate_success(
        api.create_maintenance_order(
            scene["property_id"],
            _mow_order_payload(scene, scene["current_version"]),
            INV_1,
        ),
        201,
    )

    assert_maintenance_order(order)
    assert order["status"] == "SCHEDULED"
    assert order["estimated_cost_cents"] == MOW_ESTIMATE_CENTS
    parcel = fixtures.read_property(api, scene["property_id"])
    assert parcel["version"] == scene["current_version"] + 1


# ── a funding source whose version moved under the planner ──────────────────
def _funding_source_moved_by_an_acquisition_commitment(api):
    """
    An unrestricted 1,000,000-cent source. The planner reads its version, and a
    board approval then commits 200,000 cents of acquisition money against the
    same source, which advances that version behind the planner's back.
    """
    source = fixtures.create_funding_source(
        api,
        name="OCC Source Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    stale_version = source["version"]
    parcel = fixtures.create_property(
        api,
        address="3330 Ironbark Row",
        situs_ward=6,
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    # A negotiated purchase carries neither a foreclosure docket nor a donor.
    packet_payload = factories.without(
        factories.acquisition_packet_payload(
            parcel["id"],
            source["id"],
            channel="NEGOTIATED_PURCHASE",
            offer_price_cents=195000,
            title_search_fee_cents=5000,
        ),
        "donor_name",
    )
    packet = get_success_data(api.create_acquisition_packet(packet_payload, INTAKE_1))
    fixtures.board_approve_packet(api, packet["id"])

    committed = fixtures.read_funding_source(api, source["id"])

    return {
        "source_id": source["id"],
        "stale_version": stale_version,
        "current_version": committed["version"],
        "committed_cents": committed["committed_cents"],
        "available_cents": committed["available_cents"],
    }


def test_planning_a_run_against_a_stale_funding_source_version_is_refused(api):
    """
    A demolition run planned against a budget picture an acquisition commitment has already moved past is refused, and no run is created.

    If its value differs from the funding source's current `version`, the request is rejected with `ERR_STALE_FUNDING_SOURCE_VERSION` (412), so a run can never be planned against a budget picture that has already moved.

    Design: Corner/cross_cutting_complexity_layers/stale_funding_source_version_rejected_then_current_version_accepted
    """
    scene = _funding_source_moved_by_an_acquisition_commitment(api)
    assert scene["committed_cents"] == 200000
    assert scene["available_cents"] == 800000
    assert scene["current_version"] > scene["stale_version"]

    response = api.create_demolition_run(
        factories.demolition_run_payload(
            scene["source_id"], 500000, scene["stale_version"]
        ),
        INV_1,
    )

    validate_error(response, ApiErrorId.STALE_FUNDING_SOURCE_VERSION.value, 412)
    runs = validate_success(
        api.list_funding_source_demolition_runs(scene["source_id"], INV_1), 200
    )
    assert runs == []
    ledger = fixtures.read_funding_source(api, scene["source_id"])
    assert ledger["version"] == scene["current_version"]
    assert ledger["open_run_count"] == 0
    assert_ledger_position(
        ledger,
        authorized_cents=1000000,
        committed_cents=200000,
        disbursed_cents=0,
        available_cents=800000,
    )


def test_the_same_run_replanned_at_the_refreshed_source_version_is_accepted(api):
    """
    Replanning the identical budget with the funding source version freshly re-read succeeds, and the refused attempt consumed no run sequence.

    If its value differs from the funding source's current `version`, the request is rejected with `ERR_STALE_FUNDING_SOURCE_VERSION` (412), so a run can never be planned against a budget picture that has already moved.

    Design: Corner/cross_cutting_complexity_layers/stale_funding_source_version_rejected_then_current_version_accepted
    """
    scene = _funding_source_moved_by_an_acquisition_commitment(api)

    validate_error(
        api.create_demolition_run(
            factories.demolition_run_payload(
                scene["source_id"], 500000, scene["stale_version"]
            ),
            INV_1,
        ),
        ApiErrorId.STALE_FUNDING_SOURCE_VERSION.value,
        412,
    )

    run = validate_success(
        api.create_demolition_run(
            factories.demolition_run_payload(
                scene["source_id"], 500000, scene["current_version"]
            ),
            INV_1,
        ),
        201,
    )

    assert run["status"] == "PLANNED"
    assert run["run_sequence"] == 1
    ledger = fixtures.read_funding_source(api, scene["source_id"])
    assert ledger["open_run_count"] == 1
    # Planning reserves nothing: only the acquisition commitment stands.
    assert_ledger_position(
        ledger, committed_cents=200000, disbursed_cents=0, available_cents=800000
    )


# ── reads that already carry the write that just happened ───────────────────
def _order_scheduled_on_an_acquired_parcel(api):
    """
    An ACQUIRED 10,000 square foot parcel on an unrestricted 1,000,000-cent
    source, with one mowing order scheduled against that source. The scheduling
    response itself is returned alongside the ids.
    """
    source = fixtures.create_funding_source(
        api,
        name="Immediate Read Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    parcel = fixtures.create_property(
        api,
        address="3340 Juneberry Row",
        situs_ward=6,
        lot_area_sqft=10000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    packet = fixtures.acquire_property(
        api, parcel["id"], source["id"], donor_name="Juneberry Trust"
    )
    contractor = fixtures.create_contractor(
        api,
        name="Juneberry Mowing",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )
    order = validate_success(
        api.create_maintenance_order(
            parcel["id"],
            factories.maintenance_order_payload(
                contractor["id"],
                source["id"],
                fixtures.property_version(api, parcel["id"]),
                window_start="2026-08-05T00:00:00Z",
                window_end="2026-08-06T00:00:00Z",
            ),
            INV_1,
        ),
        201,
    )
    return {
        "source_id": source["id"],
        "property_id": parcel["id"],
        "packet_status": packet["status"],
        "order": order,
    }


def test_the_committed_estimate_is_current_on_the_very_next_ledger_read(api):
    """
    The scheduling response already carries the computed estimate, and the next read of the funding source already shows that estimate committed with available reduced by the same amount.

    The identity that authorized money always equals available plus committed plus disbursed money holds before and after every operation in this specification; each compensating pair — approve/decline, schedule/cancel, commit/disburse — restores it exactly.

    Design: Corner/consistency_model/ledger_and_derived_reads_are_current_in_the_same_request
    """
    scene = _order_scheduled_on_an_acquired_parcel(api)
    assert scene["packet_status"] == "CLOSED"
    # No second read and no settle step: the estimate is in the creation body.
    assert scene["order"]["estimated_cost_cents"] == MOW_ESTIMATE_CENTS
    assert scene["order"]["status"] == "SCHEDULED"
    assert scene["order"]["actual_cost_cents"] is None

    ledger = fixtures.read_funding_source(api, scene["source_id"], TREAS_1)

    assert_ledger_position(
        ledger,
        authorized_cents=1000000,
        committed_cents=MOW_ESTIMATE_CENTS,
        disbursed_cents=0,
        available_cents=1000000 - MOW_ESTIMATE_CENTS,
        status="ACTIVE",
    )


def test_the_authority_wide_summary_is_current_in_the_same_pass(api):
    """
    The computed authority-wide read already counts the parcel the acquisition brought into inventory and already carries the estimate the scheduling committed.

    `inventory_area_sqft` is the sum of `lot_area_sqft` over every parcel whose `custody_status` is `ACQUIRED`, `LISTED` or `REVERTED`; `conveyed_area_sqft` is the same sum over parcels in `CONVEYED`; and `inventory_property_count` is the number of parcels in the three inventory states.

    Design: Corner/consistency_model/ledger_and_derived_reads_are_current_in_the_same_request
    """
    scene = _order_scheduled_on_an_acquired_parcel(api)
    assert scene["order"]["estimated_cost_cents"] == MOW_ESTIMATE_CENTS

    summary = fixtures.inventory_summary(api, situs_ward=6, headers=TREAS_1)

    assert summary["inventory_property_count"] == 1
    assert summary["inventory_area_sqft"] == 10000
    assert summary["conveyed_area_sqft"] == 0
    # The ledger totals across every funding source agree on the same pass.
    assert summary["total_committed_cents"] == MOW_ESTIMATE_CENTS
    assert summary["total_disbursed_cents"] == 0
    assert summary["total_authorized_cents"] == (
        summary["total_available_cents"]
        + summary["total_committed_cents"]
        + summary["total_disbursed_cents"]
    )
