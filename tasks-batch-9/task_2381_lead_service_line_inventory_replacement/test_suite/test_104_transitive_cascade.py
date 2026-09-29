"""Queue A - rule ``transitive_cascade``.

Two single writes each detonate an explicitly four-link chain: appointment
completion (evidence -> line -> counters -> amendment) and order completion
(allocations -> source buckets -> equity -> posture).
"""

import pytest

from test_helpers import ApiClient, fixtures
from test_helpers.types import (
    AllocationState,
    AppointmentState,
    CertaintyBasis,
    Classification,
    ConsentOutcome,
    EvidenceOrigin,
    FulfillmentState,
    FundingMode,
    InventoryState,
    InventoryStatus,
    Material,
    ProgramPosture,
    ReplacementState,
    Side,
    SourceKind,
    SourceType,
    VerificationMethod,
)


# ---------------------------------------------------------------------------
# appointment_completion_cascades_four_links_into_inventory_amendment
# ---------------------------------------------------------------------------


def _on_site_appointment(api: ApiClient):
    """A published UNKNOWN line with customer-side pothole evidence and a crew on site."""
    system = fixtures.create_water_system(
        api,
        "IL2031008",
        system_name="Foxglen Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=[],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.create_service_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-9900"
    )
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.PREDICTIVE_MODEL,
        side=Side.CUSTOMER,
        observed_material=Material.UNKNOWN,
        observed_at="2026-06-02T00:00:00Z",
    )
    fixtures.publish_inventory(api, system["id"], line["id"])
    fixtures.deliver_notification_for_line(api, line["id"], delivered_at="2026-08-01T09:00:00Z")
    fixtures.add_evidence(
        api,
        line["id"],
        source_type=SourceType.POTHOLE,
        side=Side.CUSTOMER,
        observed_material=Material.COPPER,
        observed_at="2026-07-20T00:00:00Z",
    )
    crew = fixtures.create_crew(
        api,
        system["id"],
        crew_name="Crew Alpha",
        shift_start_utc_time="08:00",
        shift_end_utc_time="18:00",
        daily_appointment_capacity=5,
        certified_methods=[VerificationMethod.POTHOLE],
    )
    appointment = fixtures.book_appointment(
        api,
        line["id"],
        crew["id"],
        method=VerificationMethod.POTHOLE,
        window_start_utc="2026-08-01T09:00:00Z",
        window_end_utc="2026-08-01T10:00:00Z",
    )
    fixtures.arrive(api, appointment["id"], crew["id"])
    return {"system": system, "line": line, "crew": crew, "appointment": appointment}


def test_completion_synthesizes_cascade_evidence_and_verifies_the_line(
    api: ApiClient,
) -> None:
    """Links one and two: an APPOINTMENT_CASCADE item rescores the line to NON_LEAD.

    PRD 3.3: "The first link synthesizes an evidence item for the appointment's
    `service_line_id`, with `source_type` copied from the appointment's `method`,
    `side` copied from `observed_side`, `observed_material` copied from
    `observed_material`, and `origin` set to `APPOINTMENT_CASCADE`; the new item's
    identifier is stored back onto the appointment as `emitted_evidence_item_id`,
    which is null until completion."
    PRD 3.3: "The second link runs that insertion through the service line's
    governing-evidence, `classification`, `certainty_score` and
    `replacement_priority_score` recompute, and may fire the line's
    `CLASSIFIED_PROVISIONAL → CLASSIFIED_VERIFIED` transition."
    PRD 3.2: "Symmetrically, a recompute that lands the classification at
    `NON_LEAD` moves a line sitting at `ELIGIBLE` back to `NOT_REQUIRED`, sets its
    `replacement_priority_score` to exactly 0.00, and advances its `version` by
    one."

    Design: Difficulty/transitive_cascade/appointment_completion_cascades_four_links_into_inventory_amendment
    """
    scenario = _on_site_appointment(api)

    before = fixtures.read_service_line(api, scenario["line"]["id"])
    assert before["classification"] == Classification.UNKNOWN
    assert before["certainty_score"] == pytest.approx(0.00)
    assert before["inventory_state"] == InventoryState.CLASSIFIED_PROVISIONAL
    assert before["replacement_state"] == ReplacementState.ELIGIBLE
    assert before["replacement_priority_score"] == pytest.approx(40.00)
    assert scenario["appointment"]["emitted_evidence_item_id"] is None

    completed = fixtures.complete_appointment(
        api,
        scenario["appointment"]["id"],
        scenario["crew"]["id"],
        observed_side=Side.UTILITY,
        observed_material=Material.COPPER,
    )

    assert completed["state"] == AppointmentState.COMPLETED
    assert completed["emitted_evidence_item_id"] is not None

    emitted = fixtures.read_evidence_item(api, completed["emitted_evidence_item_id"])
    assert emitted["service_line_id"] == scenario["line"]["id"]
    assert emitted["source_type"] == SourceType.POTHOLE
    assert emitted["side"] == Side.UTILITY
    assert emitted["observed_material"] == Material.COPPER
    assert emitted["origin"] == EvidenceOrigin.APPOINTMENT_CASCADE
    assert emitted["retracted"] is False

    line = fixtures.read_service_line(api, scenario["line"]["id"])
    assert line["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert line["certainty_basis"] == CertaintyBasis.FIELD_BASIS
    assert line["utility_side_material"] == Material.COPPER
    assert line["customer_side_material"] == Material.COPPER
    assert line["classification"] == Classification.NON_LEAD
    assert line["certainty_score"] == pytest.approx(100.00)
    assert line["replacement_state"] == ReplacementState.NOT_REQUIRED
    assert line["replacement_priority_score"] == pytest.approx(0.00)


def test_completion_bubbles_the_counters_and_forces_an_inventory_amendment(
    api: ApiClient,
) -> None:
    """Links three and four: the partition moves and the system leaves PUBLISHED.

    PRD 3.3: "The third link bubbles the change into the water system's
    `lead_count`, `grr_count`, `non_lead_count`, `unknown_count` and
    `unknown_share_pct` and recomputes `program_posture`."
    PRD 3.3: "The fourth link moves the water system from `PUBLISHED` to
    `AMENDMENT_PENDING` when it was published and the classification actually
    changed, which by clause 3 of the posture rule forces `program_posture` to
    `RESTRICTED`."
    PRD 3.3: "Completion also refreshes the crew's `scheduled_appointment_count`
    and advances the appointment's `version` by one."

    Design: Difficulty/transitive_cascade/appointment_completion_cascades_four_links_into_inventory_amendment
    """
    scenario = _on_site_appointment(api)

    before = fixtures.read_water_system(api, scenario["system"]["id"])
    assert before["inventory_status"] == InventoryStatus.PUBLISHED
    assert before["unknown_count"] == 1

    fixtures.complete_appointment(
        api,
        scenario["appointment"]["id"],
        scenario["crew"]["id"],
        observed_side=Side.UTILITY,
        observed_material=Material.COPPER,
    )

    system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert system["unknown_count"] == 0
    assert system["non_lead_count"] == 1
    assert system["lead_count"] == 0
    assert system["total_service_line_count"] == 1
    assert system["unknown_share_pct"] == pytest.approx(0.00)
    assert system["inventory_status"] == InventoryStatus.AMENDMENT_PENDING
    assert system["program_posture"] == ProgramPosture.RESTRICTED

    crew = fixtures.read_crew(api, scenario["crew"]["id"])
    assert crew["scheduled_appointment_count"] == 0


# ---------------------------------------------------------------------------
# order_completion_cascades_allocation_flip_into_equity_and_posture
# ---------------------------------------------------------------------------


def _order_under_way(api: ApiClient):
    """A disadvantaged lead replacement in progress against a single funding source."""
    system = fixtures.create_water_system(
        api,
        "IL2031009",
        system_name="Larkspur Water",
        compliance_deadline_date="2027-10-16",
        baseline_lead_and_grr_count=100,
        disadvantaged_tract_codes=["17031-8402"],
        funding_mode=FundingMode.WATERFALL,
    )
    line = fixtures.make_lead_line(
        api, system["id"], address_label="101 Elm St", census_tract_code="17031-8402"
    )
    fixtures.publish_inventory(api, system["id"], line["id"])
    fixtures.deliver_notification_for_line(api, line["id"], delivered_at="2026-08-01T09:00:00Z")
    source = fixtures.create_funding_source(
        api,
        system["id"],
        authorized_cents=200000,
        priority_rank=1,
        source_kind=SourceKind.STATE_REVOLVING_FUND,
        max_share_pct=100.0,
        equity_required_pct=0.0,
    )
    order = fixtures.open_order(
        api,
        line["id"],
        estimated_cost_cents=100000,
        excavation_start_date="2026-08-10",
        excavation_end_date="2026-08-11",
    )
    fixtures.resolve_consent(api, order["id"], outcome=ConsentOutcome.GRANTED)
    fixtures.plan_funding(api, order["id"])
    fixtures.schedule_order(api, order["id"], "2026-08-10", "2026-08-11")
    fixtures.start_order(api, order["id"])
    return {"system": system, "line": line, "source": source, "order": order}


def test_order_completion_flips_every_allocation_and_moves_the_source_buckets(
    api: ApiClient,
) -> None:
    """Links one to three: COMMITTED becomes DRAWN and available_cents does not move.

    PRD 3.7: "The first link flips every row of `funding_allocations` from
    `COMMITTED` to `DRAWN`."
    PRD 3.7: "The second moves each affected funding source's money from one
    bucket to the other — `committed_cents` decreases by the allocated amount and
    `drawn_cents` increases by the same amount — which leaves `available_cents`
    unchanged, since the conservation identity subtracts both buckets."
    PRD 3.7: "The third recomputes each affected source's
    `disadvantaged_share_pct` and `equity_shortfall_cents`."

    Design: Difficulty/transitive_cascade/order_completion_cascades_allocation_flip_into_equity_and_posture
    """
    scenario = _order_under_way(api)

    mid = fixtures.read_funding_source(api, scenario["source"]["id"])
    assert mid["committed_cents"] == 100000
    assert mid["drawn_cents"] == 0
    assert mid["available_cents"] == 100000
    assert mid["disadvantaged_share_pct"] == pytest.approx(100.00)

    completed = fixtures.complete_order(
        api,
        scenario["order"]["id"],
        "2026-08-01T12:00:00Z",
        [Side.UTILITY, Side.CUSTOMER],
    )

    assert completed["fulfillment_state"] == FulfillmentState.COMPLETED
    assert completed["allocated_total_cents"] == 100000
    assert completed["funding_allocations"] != []
    assert all(
        row["state"] == AllocationState.DRAWN for row in completed["funding_allocations"]
    )
    assert completed["flushing_duration_minutes"] == 31

    source = fixtures.read_funding_source(api, scenario["source"]["id"])
    assert source["authorized_cents"] == 200000
    assert source["committed_cents"] == 0
    assert source["drawn_cents"] == 100000
    assert source["available_cents"] == 100000
    assert source["disadvantaged_committed_cents"] == 100000
    assert source["disadvantaged_share_pct"] == pytest.approx(100.00)
    assert source["equity_shortfall_cents"] == 0


def test_order_completion_settles_the_line_and_drives_the_system_into_amendment(
    api: ApiClient,
) -> None:
    """Link four plus the line settlement: REPLACED_FULL, NON_LEAD and RESTRICTED.

    PRD 3.7: "The fourth recomputes the water system's `program_posture`, which
    clause 5 drives to `RESTRICTED` if any active source now carries a non-zero
    `equity_shortfall_cents`."
    PRD 3.7: "a full replacement lands field evidence on **both** sides, so the
    both-sides condition of §3.2 fires and the line reaches `CLASSIFIED_VERIFIED`
    with `classification` `NON_LEAD`"
    PRD 3.7: "Both `REPLACED_FULL` and `REPLACED_PARTIAL` are sticky: the
    `NON_LEAD` recompute does **not** drag `replacement_state` back to
    `NOT_REQUIRED`."

    Design: Difficulty/transitive_cascade/order_completion_cascades_allocation_flip_into_equity_and_posture
    """
    scenario = _order_under_way(api)

    mid_system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert mid_system["program_posture"] == ProgramPosture.OPEN
    assert mid_system["inventory_status"] == InventoryStatus.PUBLISHED

    completed = fixtures.complete_order(
        api,
        scenario["order"]["id"],
        "2026-08-01T12:00:00Z",
        [Side.UTILITY, Side.CUSTOMER],
    )
    assert completed["replaced_sides"] == [Side.UTILITY, Side.CUSTOMER]

    line = fixtures.read_service_line(api, scenario["line"]["id"])
    assert line["replacement_state"] == ReplacementState.REPLACED_FULL
    assert line["classification"] == Classification.NON_LEAD
    assert line["inventory_state"] == InventoryState.CLASSIFIED_VERIFIED
    assert line["certainty_score"] == pytest.approx(100.00)
    assert line["replacement_priority_score"] == pytest.approx(40.00)

    system = fixtures.read_water_system(api, scenario["system"]["id"])
    assert system["inventory_status"] == InventoryStatus.AMENDMENT_PENDING
    assert system["program_posture"] == ProgramPosture.RESTRICTED
