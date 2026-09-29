"""
Successful state transitions and the side effects they carry.

Each test drives one declared transition from an empty database and then reads
back every record the transition is documented to touch: the row that moved, the
parcel dimensions, the funding ledger position and the records the cascade
reaches. Nothing here is a rejection - the refusals live alongside in the state
guard suite.
"""

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    DISP_1,
    INTAKE_1,
    INTAKE_OFFICER_1,
    INV_1,
    assert_acquisition_packet,
    assert_demolition_run,
    assert_ledger_position,
    assert_maintenance_order,
    assert_property,
    assert_score,
    assert_title_action,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)

# Securing three openings: a 45,000-cent base plus 3 x 12,750 cents gives an
# 83,250-cent subtotal, and county overhead of 6.5 percent rounded half up adds
# 5,411 cents.
SECURE_ESTIMATE_3_OPENINGS_CENTS = 88661

# A grade F, 3,000 sqft demolition: a 950,000-cent base, 186,000 cents of
# per-area charge, an 18 percent asbestos surcharge of 204,480 cents on those two
# and 87,131 cents of county overhead on the 1,340,480-cent subtotal.
DEMOLITION_ESTIMATE_3K_SQFT_GRADE_F_CENTS = 1427611

# A 3,000,000-cent run budget with the 7.5 percent administrative loading carved
# out in advance, floored to whole cents.
PROVISIONAL_CAP_OF_3M_BUDGET_CENTS = 2790697
# 7.5 percent of the committed subtotal, rounded half up after the walk.
ADMIN_FEE_OF_ONE_SELECTION_CENTS = 107071


def _assert_stamped_at(value: Any, instant: str) -> None:
    """Assert a server-stamped instant was taken from the logical clock."""
    assert value is not None, f"expected an instant of {instant}, got null"
    assert value.startswith(instant), f"expected an instant of {instant}, got {value}"


def _negotiated_packet(
    api: ApiClient,
    property_id: str,
    funding_source_id: str,
    *,
    offer_price_cents: int,
    title_search_fee_cents: int = 0,
) -> Dict[str, Any]:
    """
    Open a negotiated-purchase packet. A negotiated purchase carries neither a
    foreclosure case number nor a donor name.
    """
    payload = factories.without(
        factories.acquisition_packet_payload(
            property_id,
            funding_source_id,
            channel="NEGOTIATED_PURCHASE",
            offer_price_cents=offer_price_cents,
            title_search_fee_cents=title_search_fee_cents,
        ),
        "donor_name",
    )
    return validate_success(api.create_acquisition_packet(payload, INTAKE_1), 201)


def _constrained_source_with_parked_packet(api: ApiClient) -> Dict[str, Any]:
    """
    A 100,000-cent unrestricted source whose reserve floor is 5,000 cents, with a
    96,000-cent packet board-approved so that available_cents falls to 4,000 and
    the source is CONSTRAINED, and a second 1,000-cent packet that the constraint
    cascade parked in ON_HOLD_FUNDING.
    """
    source = fixtures.create_funding_source(
        api,
        name="Compensation Line",
        source_type="GENERAL_FUND",
        authorized_cents=100000,
        restriction="ANY",
    )
    assert source["reserve_floor_cents"] == 5000
    first_parcel = fixtures.create_property(api, address="1100 Rowan St")
    second_parcel = fixtures.create_property(api, address="1101 Rowan St")
    first_packet = _negotiated_packet(
        api, first_parcel["id"], source["id"], offer_price_cents=96000
    )
    second_packet = _negotiated_packet(
        api, second_parcel["id"], source["id"], offer_price_cents=1000
    )
    approved = fixtures.board_approve_packet(api, first_packet["id"])
    assert approved["committed_cents"] == 96000
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        committed_cents=96000,
        available_cents=4000,
        status="CONSTRAINED",
    )
    parked = fixtures.read_packet(api, second_packet["id"])
    assert parked["status"] == "ON_HOLD_FUNDING"
    assert parked["hold_reason"] == "FUNDING_SOURCE_CONSTRAINED"
    return {
        "funding_source": source,
        "approved_packet": first_packet,
        "parked_packet": second_packet,
    }


def test_new_acquisition_packet_opens_in_due_diligence(api: ApiClient) -> None:
    """
    Opening an acquisition packet leaves it in due diligence with nothing yet committed against the funding source.

    A packet opens in `DUE_DILIGENCE` with `committed_cents` at zero and `initiated_by_user_id` set to the opening officer.
    Design: Corner/state_machines/acquisition_packet_starts_in_due_diligence
    """
    source = fixtures.create_funding_source(
        api,
        name="Initial State Line",
        source_type="GENERAL_FUND",
        authorized_cents=500000,
        restriction="ANY",
    )
    parcel = fixtures.create_property(
        api,
        address="1001 Hazel St",
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )

    packet = _negotiated_packet(
        api,
        parcel["id"],
        source["id"],
        offer_price_cents=40000,
        title_search_fee_cents=5000,
    )

    assert_acquisition_packet(packet)
    assert packet["status"] == "DUE_DILIGENCE"
    assert packet["committed_cents"] == 0
    assert packet["initiated_by_user_id"] == INTAKE_OFFICER_1
    assert packet["hold_reason"] is None
    assert packet["resolution_no"] is None
    assert packet["closed_by_user_id"] is None
    # Only board approval reserves money, so the ledger has not moved.
    assert_ledger_position(
        fixtures.read_funding_source(api, source["id"]),
        authorized_cents=500000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=500000,
        status="ACTIVE",
    )
    assert fixtures.read_property(api, parcel["id"])["custody_status"] == "PROSPECT"


def test_defect_remains_adjudication_reclouds_the_title(api: ApiClient) -> None:
    """
    An adjudication that finds defects remaining closes the action as DEFECT_REMAINS and drives the parcel's title back to clouded.

    A `DEFECT_REMAINS` outcome must carry a `defect_count` of at least one; the action moves `FILED → DEFECT_REMAINS`, records `adjudicated_at` and the reported defect count, and drives the parcel `QUIET_TITLE_FILED → CLOUDED`, reopening the filing cycle for another round.
    Design: Corner/state_machines/defect_remains_adjudication_reclouds_title_and_reopens_round_two
    """
    parcel = fixtures.create_property(
        api,
        address="1010 Ivy St",
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    action = fixtures.open_title_action(api, parcel["id"])
    assert action["round_no"] == 1
    assert action["status"] == "FILED"

    adjudicated = validate_success(
        api.adjudicate_title_action(
            action["id"], {"outcome": "DEFECT_REMAINS", "defect_count": 3}, INTAKE_1
        )
    )

    assert_title_action(adjudicated)
    assert adjudicated["status"] == "DEFECT_REMAINS"
    assert adjudicated["defect_count"] == 3
    _assert_stamped_at(adjudicated["adjudicated_at"], "2026-08-01T00:00:00")
    parcel_after = fixtures.read_property(api, parcel["id"])
    assert parcel_after["title_status"] == "CLOUDED"
    # The custody dimension advances on its own schedule and is untouched here.
    assert parcel_after["custody_status"] == "PROSPECT"


def test_refiling_after_a_defective_adjudication_is_round_two(api: ApiClient) -> None:
    """
    A fresh title action filed after a defective adjudication is a second round and files the parcel's title dimension again.

    The new action opens in `FILED`, stamps `filed_at` at the current instant, and takes a `round_no` equal to the number of title actions already recorded on that parcel plus one, so the re-file that follows a defective adjudication is round 2.
    Design: Corner/state_machines/defect_remains_adjudication_reclouds_title_and_reopens_round_two
    """
    parcel = fixtures.create_property(
        api,
        address="1011 Ivy St",
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=True,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    first_action = fixtures.open_title_action(api, parcel["id"])
    fixtures.adjudicate_title_action(
        api, first_action["id"], "DEFECT_REMAINS", defect_count=3
    )

    second_action = validate_success(
        api.create_title_action(
            parcel["id"], {"action_type": "TAX_DEED_CONFIRMATION"}, INTAKE_1
        ),
        201,
    )

    assert_title_action(second_action)
    assert second_action["id"] != first_action["id"]
    assert second_action["round_no"] == 2
    assert second_action["status"] == "FILED"
    _assert_stamped_at(second_action["filed_at"], "2026-08-01T00:00:00")
    parcel_after = fixtures.read_property(api, parcel["id"])
    assert parcel_after["title_status"] == "QUIET_TITLE_FILED"
    assert parcel_after["custody_status"] == "PROSPECT"


def test_order_completion_swaps_the_estimate_for_the_invoice(api: ApiClient) -> None:
    """
    Completing a scheduled order releases its estimate from the commitment and books the invoiced actual cost as a disbursement.

    The funding source releases the estimate from `committed_cents` and adds the actual cost to `disbursed_cents` — the difference between estimate and invoice therefore returns to, or comes out of, `available_cents` — and the source's status is re-evaluated in both directions: a commitment-heavy position may still move `ACTIVE → CONSTRAINED` with the packet-parking cascade, while a favourable settlement may move `CONSTRAINED → ACTIVE` and release the parked packets back to `DUE_DILIGENCE`.
    Design: Corner/state_machines/secure_order_completion_disburses_and_marks_parcel_secured
    """
    acquisition_source = fixtures.create_acquisition_funding_source(
        api, name="Side Effect Acquisition Line"
    )
    operations_source = fixtures.create_funding_source(
        api,
        name="Side Effect Operations Line",
        source_type="GRANT",
        authorized_cents=500000,
        restriction="ANY",
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=acquisition_source,
        property_overrides={
            "address": "1030 Katsura St",
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
    )
    contractor = fixtures.create_contractor(
        api,
        name="Board-Up Crew LLC",
        max_concurrent_crews=3,
        specialties=["SECURE", "MOW"],
    )
    order = fixtures.schedule_order(
        api,
        bundle["property"]["id"],
        funding_source_id=operations_source["id"],
        contractor_id=contractor["id"],
        work_type="SECURE",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-07T00:00:00Z",
        openings_count=3,
    )
    assert order["estimated_cost_cents"] == SECURE_ESTIMATE_3_OPENINGS_CENTS
    assert_ledger_position(
        fixtures.read_funding_source(api, operations_source["id"]),
        committed_cents=SECURE_ESTIMATE_3_OPENINGS_CENTS,
        disbursed_cents=0,
        available_cents=500000 - SECURE_ESTIMATE_3_OPENINGS_CENTS,
    )

    completed = validate_success(
        api.complete_maintenance_order(
            order["id"], {"actual_cost_cents": 90000}, INV_1
        )
    )

    assert_maintenance_order(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["actual_cost_cents"] == 90000
    _assert_stamped_at(completed["completed_at"], "2026-08-01T00:00:00")
    # The 88,661-cent estimate leaves the commitment and the 90,000-cent invoice
    # enters the disbursement, so 1,339 cents come out of available_cents.
    assert_ledger_position(
        fixtures.read_funding_source(api, operations_source["id"]),
        authorized_cents=500000,
        committed_cents=0,
        disbursed_cents=90000,
        available_cents=410000,
        status="ACTIVE",
    )


def test_secure_order_completion_marks_the_parcel_secured(api: ApiClient) -> None:
    """
    Completing a securing order sets the parcel's secured flag and leaves the mowing and demolition fields alone.

    The work itself lands on the parcel according to its type: securing sets `secured` to true, mowing stamps `last_mow_at` at the current instant, and demolition stamps `demolished_at` and sets `structure_present` to false.
    Design: Corner/state_machines/secure_order_completion_disburses_and_marks_parcel_secured
    """
    acquisition_source = fixtures.create_acquisition_funding_source(
        api, name="Work Type Acquisition Line"
    )
    operations_source = fixtures.create_funding_source(
        api,
        name="Work Type Operations Line",
        source_type="GRANT",
        authorized_cents=500000,
        restriction="ANY",
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=acquisition_source,
        property_overrides={
            "address": "1031 Katsura St",
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
    )
    assert bundle["property"]["secured"] is False
    contractor = fixtures.create_contractor(
        api,
        name="Board-Up Crew LLC",
        max_concurrent_crews=3,
        specialties=["SECURE", "MOW"],
    )
    order = fixtures.schedule_order(
        api,
        bundle["property"]["id"],
        funding_source_id=operations_source["id"],
        contractor_id=contractor["id"],
        work_type="SECURE",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-07T00:00:00Z",
        openings_count=3,
    )

    validate_success(
        api.complete_maintenance_order(
            order["id"], {"actual_cost_cents": 90000}, INV_1
        )
    )

    parcel = fixtures.read_property(api, bundle["property"]["id"])
    assert_property(parcel)
    assert parcel["secured"] is True
    assert parcel["last_mow_at"] is None
    assert parcel["demolished_at"] is None
    assert parcel["structure_present"] is True
    # The live score after completion: 18 points for grade C plus 0.25 points for
    # each of 4 vacant months, with no complaints, violations, neighbours in
    # inventory, and no whole 30-day month of holding elapsed yet.
    assert_score(parcel["current_blight_score"], 19.0)


def test_sweep_opens_the_cure_window_ninety_days_out(api: ApiClient) -> None:
    """
    The sweep moves an executed agreement whose performance deadline has passed with milestones outstanding into a cure period ending 90 days later.

    **Step two** opens cure periods: every agreement in `EXECUTED` whose `performance_deadline` has passed while `milestones_completed` remains below `milestone_count` moves `EXECUTED → CURE_PENDING` and has its `cure_deadline` stamped 90 days after its `performance_deadline`.
    Design: Corner/state_machines/sweep_waives_reverter_when_clause_inactive
    """
    buyer = fixtures.create_developer_applicant(
        api, legal_name="Larch Street Partners LLC", contact_email="dev@larch.example"
    )
    bundle = fixtures.awarded_parcel(
        api,
        property_overrides={
            "address": "1040 Larch St",
            "lot_area_sqft": 8000,
            "assessed_value_cents": 400000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 0,
        },
        applicant=buyer,
        application_overrides={
            "proposed_use": "Six infill townhomes",
            "offer_price_cents": 500000,
        },
        agreement_overrides={
            "performance_deadline": "2026-09-01T00:00:00Z",
            "milestone_count": 2,
            "reverter_clause_active": False,
            "abatement_years": 5,
            "discharge_mode": "NEGOTIATED",
            "projected_improved_value_cents": 900000,
        },
    )
    agreement = bundle["agreement"]
    assert agreement["status"] == "EXECUTED"
    # A negotiated agreement abates against the parcel's assessed value: the
    # county millage on 400,000 cents rounded half up, over five years.
    assert agreement["abatement_annual_cents"] == 5680
    assert agreement["abatement_total_cents"] == 28400
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")

    tally = validate_success(api.run_compliance_sweep(INV_1))

    assert tally["cure_pending_count"] == 1
    assert tally["reverted_count"] == 0
    assert tally["waived_count"] == 0
    after = fixtures.read_agreement(api, agreement["id"])
    assert after["status"] == "CURE_PENDING"
    _assert_stamped_at(after["cure_deadline"], "2026-11-30T00:00:00")
    assert after["reverted_at"] is None
    assert fixtures.read_property(api, bundle["property"]["id"])["custody_status"] == (
        "CONVEYED"
    )


def test_sweep_waives_the_reverter_when_the_clause_is_inactive(api: ApiClient) -> None:
    """
    A breached agreement whose reverter clause is inactive is only counted as waived: it stays in its cure period and the parcel is not taken back.

    **Step three** enforces the reverter: every agreement in `CURE_PENDING` whose `cure_deadline` has passed while milestones remain outstanding, and whose `reverter_clause_active` is true, moves `CURE_PENDING → REVERTED` and stamps `reverted_at`; where `reverter_clause_active` is false the agreement is left in `CURE_PENDING` and the sweep merely counts it as waived.
    Design: Corner/state_machines/sweep_waives_reverter_when_clause_inactive
    """
    buyer = fixtures.create_developer_applicant(
        api, legal_name="Larch Street Partners LLC", contact_email="dev@larch.example"
    )
    bundle = fixtures.awarded_parcel(
        api,
        property_overrides={
            "address": "1041 Larch St",
            "lot_area_sqft": 8000,
            "assessed_value_cents": 400000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 0,
        },
        applicant=buyer,
        application_overrides={
            "proposed_use": "Six infill townhomes",
            "offer_price_cents": 500000,
        },
        agreement_overrides={
            "performance_deadline": "2026-09-01T00:00:00Z",
            "milestone_count": 2,
            "reverter_clause_active": False,
            "abatement_years": 5,
            "discharge_mode": "NEGOTIATED",
            "projected_improved_value_cents": 900000,
        },
    )
    agreement = bundle["agreement"]
    fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    first_tally = fixtures.run_compliance_sweep(api)
    assert first_tally["cure_pending_count"] == 1
    assert first_tally["reverted_count"] == 0
    # Past the cure deadline of 2026-11-30, with no milestone ever reported.
    fixtures.set_clock(api, "2026-12-01T00:00:00Z")

    tally = validate_success(api.run_compliance_sweep(INV_1))

    assert tally["waived_count"] == 1
    assert tally["reverted_count"] == 0
    assert tally["restored_inventory_sqft"] == 0
    after = fixtures.read_agreement(api, agreement["id"])
    assert after["status"] == "CURE_PENDING"
    assert after["reverted_at"] is None
    parcel = fixtures.read_property(api, bundle["property"]["id"])
    assert parcel["custody_status"] == "CONVEYED"
    assert parcel["title_status"] == "CLEAR"
    assert parcel["owner_of_record_applicant_id"] == buyer["id"]
    applicant = fixtures.read_applicant(api, buyer["id"])
    assert applicant["reverter_count"] == 0
    assert applicant["eligibility_status"] == "ELIGIBLE"


def test_title_dimension_advances_while_custody_stays_acquired(api: ApiClient) -> None:
    """
    A parcel's title runs from clouded to clear while its custody stays acquired, and only the listing call moves the custody dimension.

    Because the dimensions are independent, a parcel may be `ACQUIRED` with `CLOUDED` title, or `REVERTED` with `CLEAR` title.
    Design: Corner/state_machines/title_dimension_advances_while_custody_stays_acquired
    """
    source = fixtures.create_funding_source(
        api,
        name="Parallel Dimension Line",
        source_type="GENERAL_FUND",
        authorized_cents=500000,
        restriction="ACQUISITION_ONLY",
    )
    parcel = fixtures.create_property(
        api,
        address="1080 Poplar St",
        lot_area_sqft=6000,
        assessed_value_cents=300000,
        structure_present=False,
        structure_condition_grade="C",
        vacancy_months=4,
    )
    packet = fixtures.open_packet(
        api, parcel["id"], source["id"], title_search_fee_cents=4000
    )
    fixtures.board_approve_packet(api, packet["id"])
    closed = fixtures.close_packet(api, packet["id"])
    assert closed["status"] == "CLOSED"
    acquired = fixtures.read_property(api, parcel["id"])
    assert acquired["custody_status"] == "ACQUIRED"
    assert acquired["title_status"] == "CLOUDED"
    # A donation pays nothing but the title search and recording cost.
    assert acquired["acquisition_cost_cents"] == 4000

    action = validate_success(
        api.create_title_action(
            parcel["id"], {"action_type": "QUIET_TITLE_SUIT"}, INTAKE_1
        ),
        201,
    )
    filed = fixtures.read_property(api, parcel["id"])
    assert filed["custody_status"] == "ACQUIRED"
    assert filed["title_status"] == "QUIET_TITLE_FILED"

    validate_success(
        api.adjudicate_title_action(action["id"], {"outcome": "CLEARED"}, INTAKE_1)
    )
    cleared = fixtures.read_property(api, parcel["id"])
    assert cleared["custody_status"] == "ACQUIRED"
    assert cleared["title_status"] == "CLEAR"

    listed = validate_success(
        api.list_property_for_disposition(parcel["id"], DISP_1)
    )
    assert_property(listed)
    assert listed["custody_status"] == "LISTED"
    assert listed["title_status"] == "CLEAR"
    _assert_stamped_at(listed["listed_at"], "2026-08-01T00:00:00")


def test_declining_an_approved_packet_releases_its_commitment(api: ApiClient) -> None:
    """
    Declining a board-approved packet returns its commitment to zero on both the packet and the funding source, with nothing disbursed.

    Declining a packet that had been board-approved is the compensating action of approval: the packet's `committed_cents` returns to zero, the same amount is subtracted from the source's `committed_cents`, and `available_cents` is recomputed.
    Design: Corner/state_machines/packet_decline_releases_commitment_and_restores_constrained_source
    """
    bundle = _constrained_source_with_parked_packet(api)

    declined = validate_success(
        api.decline_packet(
            bundle["approved_packet"]["id"],
            {"declined_reason": "Seller withdrew before closing"},
            INTAKE_1,
        )
    )

    assert_acquisition_packet(declined)
    assert declined["status"] == "DECLINED"
    assert declined["committed_cents"] == 0
    assert_ledger_position(
        fixtures.read_funding_source(api, bundle["funding_source"]["id"]),
        authorized_cents=100000,
        committed_cents=0,
        disbursed_cents=0,
        available_cents=100000,
    )


def test_decline_release_restores_the_source_and_parked_packet(api: ApiClient) -> None:
    """
    When the released commitment lifts the source back over its reserve floor the source becomes active again and the packet parked on it resumes due diligence.

    If that release lifts `available_cents` back to at least `reserve_floor_cents`, the source moves `CONSTRAINED → ACTIVE` and every packet on it in `ON_HOLD_FUNDING` returns to `DUE_DILIGENCE`.
    Design: Corner/state_machines/packet_decline_releases_commitment_and_restores_constrained_source
    """
    bundle = _constrained_source_with_parked_packet(api)

    validate_success(
        api.decline_packet(
            bundle["approved_packet"]["id"],
            {"declined_reason": "Seller withdrew before closing"},
            INTAKE_1,
        )
    )

    assert_ledger_position(
        fixtures.read_funding_source(api, bundle["funding_source"]["id"]),
        committed_cents=0,
        available_cents=100000,
        status="ACTIVE",
    )
    released = fixtures.read_packet(api, bundle["parked_packet"]["id"])
    assert released["status"] == "DUE_DILIGENCE"
    assert released["hold_reason"] is None
    assert released["committed_cents"] == 0


def test_run_execution_voids_when_every_selection_is_dropped(api: ApiClient) -> None:
    """
    A planned run whose only selected parcel picked up a scheduled demolition order after planning is voided and commits nothing at all.

    When *no* selected parcel survives re-validation, the run moves `PLANNED → VOID` instead: `dropped_property_ids` becomes the whole of `selected_property_ids`, `orders_created_count` stays zero, not one cent is committed, the source's `open_run_count` still falls by one, and the run's and the source's `version` values still advance.
    Design: Corner/state_machines/run_execute_with_every_selection_dropped_moves_to_void
    """
    acquisition_source = fixtures.create_acquisition_funding_source(
        api, name="Void Run Acquisition Line"
    )
    operations_source = fixtures.create_funding_source(
        api,
        name="Void Run Operations Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
    )
    parcel = fixtures.demolition_candidate(
        api,
        acquisition_source["id"],
        address="1110 Sumac St",
        situs_ward=5,
        lot_area_sqft=3000,
        assessed_value_cents=150000,
        structure_condition_grade="F",
        vacancy_months=0,
    )
    # 44 points for a grade F structure and nothing else: above the 40-point bar.
    assert_score(parcel["current_blight_score"], 44.0)
    run = fixtures.plan_demolition_run(
        api, operations_source["id"], 3000000, situs_ward_filter=5
    )
    assert run["status"] == "PLANNED"
    assert run["provisional_cap_cents"] == PROVISIONAL_CAP_OF_3M_BUDGET_CENTS
    assert run["properties_selected_count"] == 1
    assert run["selected_property_ids"] == [parcel["id"]]
    assert run["committed_subtotal_cents"] == (
        DEMOLITION_ESTIMATE_3K_SQFT_GRADE_F_CENTS
    )
    assert run["admin_fee_cents"] == ADMIN_FEE_OF_ONE_SELECTION_CENTS
    assert run["total_committed_cents"] == 1534682
    assert fixtures.read_funding_source(api, operations_source["id"])[
        "open_run_count"
    ] == 1
    contractor = fixtures.create_contractor(
        api,
        name="Independent Demo Crew",
        max_concurrent_crews=2,
        specialties=["DEMOLITION"],
    )
    # A direct demolition order on the same parcel invalidates the run's frozen
    # selection, because a candidate may carry no demolition order.
    direct_order = fixtures.schedule_order(
        api,
        parcel["id"],
        funding_source_id=operations_source["id"],
        contractor_id=contractor["id"],
        work_type="DEMOLITION",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-12T00:00:00Z",
    )
    assert direct_order["estimated_cost_cents"] == (
        DEMOLITION_ESTIMATE_3K_SQFT_GRADE_F_CENTS
    )

    executed = validate_success(api.execute_demolition_run(run["id"], INV_1))

    assert_demolition_run(executed)
    assert executed["status"] == "VOID"
    assert executed["orders_created_count"] == 0
    _assert_stamped_at(executed["executed_at"], "2026-08-01T00:00:00")
    assert executed["dropped_property_ids"] == [parcel["id"]]
    assert executed["dropped_property_ids"] == executed["selected_property_ids"]
    # Only the direct order is committed: the void run committed no estimate and
    # no administrative fee.
    source_after = fixtures.read_funding_source(api, operations_source["id"])
    assert_ledger_position(
        source_after,
        authorized_cents=5000000,
        committed_cents=DEMOLITION_ESTIMATE_3K_SQFT_GRADE_F_CENTS,
        disbursed_cents=0,
        available_cents=5000000 - DEMOLITION_ESTIMATE_3K_SQFT_GRADE_F_CENTS,
        status="ACTIVE",
    )
    assert source_after["open_run_count"] == 0
    orders, meta = validate_paginated(
        api.list_maintenance_orders(INV_1, {"demolition_run_id": run["id"]})
    )
    assert meta["total_count"] == 0
    assert orders == []
