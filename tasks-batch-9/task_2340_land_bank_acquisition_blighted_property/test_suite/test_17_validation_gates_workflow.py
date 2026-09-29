"""
The workflow-side rejections: work windows, contractor and structure fitness,
the demolition buffer, run execution, recommendation and agreement execution.

Each test drives one rejection, pins the error identifier the PRD names for it,
and then proves nothing moved behind it - no order written, no money committed,
no status or version advanced on the row the request aimed at.
"""

from test_helpers import (
    ApiErrorId,
    CLERK_1,
    DISP_1,
    DISP_2,
    INV_1,
    expected_admin_fee_cents,
    expected_demolition_estimate_cents,
    factories,
    fixtures,
    get_success_data,
    validate_error,
)


# ── the work window must be non-empty ───────────────────────────────────────
def test_order_whose_window_ends_at_its_own_start_is_refused(api):
    """
    A maintenance order whose window closes at the very instant it opens is refused as an empty work window.

    Scheduling an order names the `work_type` (`SECURE`, `MOW` or `DEMOLITION`), the `contractor_id` to perform it, the `funding_source_id` to pay for it, and a half-open work window running from an inclusive `window_start` to an exclusive `window_end` that must fall strictly after it — an inverted or empty window is refused with `ERR_WINDOW_INVALID`.

    Design: Corner/validations/order_window_end_not_after_start_rejected
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Window Rule Line",
        source_type="GRANT",
        authorized_cents=1000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    bundle = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203010",
            "address": "3010 Alder Ct",
            "situs_ward": 3,
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": False,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Alder Court Estate"},
    )
    prop = bundle["property"]
    contractor = fixtures.create_contractor(
        api,
        name="Window Rule Mowing",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=2,
        specialties=["MOW"],
    )

    # Everything else about the request is sound: an inventory parcel, a
    # licensed mowing crew and an unrestricted budget. Only the window is empty.
    payload = factories.maintenance_order_payload(
        contractor["id"],
        funding_source["id"],
        prop["version"],
        work_type="MOW",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-05T00:00:00Z",
    )
    response = api.create_maintenance_order(prop["id"], payload, INV_1)
    validate_error(response, ApiErrorId.WINDOW_INVALID.value)

    assert fixtures.list_orders(api, property_id=prop["id"]) == []
    ledger = fixtures.read_funding_source(api, funding_source["id"])
    assert ledger["committed_cents"] == 0
    assert ledger["available_cents"] == 1000000
    assert fixtures.read_property(api, prop["id"])["version"] == prop["version"]


# ── contractor fitness and the structure the work presupposes ───────────────
def _order_gate_fixture(api):
    """
    An unrestricted budget, two acquired parcels - one carrying a structure and
    one vacant - and two crews: a mowing-only crew licensed well into the
    future, and a fully qualified crew whose licence runs out on 10 August 2026.
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Order Gate Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    with_structure = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203090",
            "address": "3090 Ironwood Ln",
            "situs_ward": 3,
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": True,
            "structure_condition_grade": "D",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Ironwood Estate"},
    )["property"]
    vacant = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203091",
            "address": "3091 Ironwood Ln",
            "situs_ward": 3,
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": False,
            "structure_condition_grade": "D",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Ironwood Estate"},
    )["property"]
    mow_only = fixtures.create_contractor(
        api,
        name="Mow Only Crew",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=3,
        specialties=["MOW"],
    )
    short_licence = fixtures.create_contractor(
        api,
        name="Short Licence Crew",
        license_expires_on="2026-08-10T00:00:00Z",
        max_concurrent_crews=3,
        specialties=["MOW", "SECURE", "DEMOLITION"],
    )
    return funding_source, with_structure, vacant, mow_only, short_licence


def _assert_nothing_was_scheduled(api, funding_source_id, *properties):
    """No order row, no commitment and no parcel version bump."""
    ledger = fixtures.read_funding_source(api, funding_source_id)
    assert ledger["committed_cents"] == 0
    assert ledger["available_cents"] == 5000000
    for prop in properties:
        assert fixtures.list_orders(api, property_id=prop["id"]) == []
        assert fixtures.read_property(api, prop["id"])["version"] == prop["version"]


def test_demolition_assigned_to_a_mowing_only_crew_is_refused(api):
    """
    A demolition order handed to a crew whose specialties list only mowing is refused for the specialty mismatch.

    The assigned contractor must not be `debarred` (`ERR_CONTRACTOR_DEBARRED`), its `specialties` must include the requested `work_type` (`ERR_CONTRACTOR_SPECIALTY_MISMATCH`), and the window may not extend past its licence: `window_end` at or before `license_expires_on` is accepted, anything later is refused with `ERR_CONTRACTOR_LICENSE_EXPIRED`.

    Design: Corner/validations/order_gate_family_specialty_license_and_structure_rejected
    """
    funding_source, with_structure, _vacant, mow_only, _short = _order_gate_fixture(api)

    # The crew is not debarred, the parcel carries a structure and the window
    # sits far inside the licence, so the specialty is the only failing test.
    payload = factories.maintenance_order_payload(
        mow_only["id"],
        funding_source["id"],
        with_structure["version"],
        work_type="DEMOLITION",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-09T00:00:00Z",
    )
    response = api.create_maintenance_order(with_structure["id"], payload, INV_1)
    validate_error(response, ApiErrorId.CONTRACTOR_SPECIALTY_MISMATCH.value)

    _assert_nothing_was_scheduled(api, funding_source["id"], with_structure)


def test_order_window_running_past_the_crew_licence_is_refused(api):
    """
    A mowing order whose window closes after the assigned crew's licence expires is refused even though the crew is qualified for the work.

    The assigned contractor must not be `debarred` (`ERR_CONTRACTOR_DEBARRED`), its `specialties` must include the requested `work_type` (`ERR_CONTRACTOR_SPECIALTY_MISMATCH`), and the window may not extend past its licence: `window_end` at or before `license_expires_on` is accepted, anything later is refused with `ERR_CONTRACTOR_LICENSE_EXPIRED`.

    Design: Corner/validations/order_gate_family_specialty_license_and_structure_rejected
    """
    funding_source, with_structure, _vacant, _mow_only, short = _order_gate_fixture(api)

    # The crew mows, so only the licence date fails: the window closes on
    # 20 August 2026, ten days past the licence.
    payload = factories.maintenance_order_payload(
        short["id"],
        funding_source["id"],
        with_structure["version"],
        work_type="MOW",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    response = api.create_maintenance_order(with_structure["id"], payload, INV_1)
    validate_error(response, ApiErrorId.CONTRACTOR_LICENSE_EXPIRED.value)

    _assert_nothing_was_scheduled(api, funding_source["id"], with_structure)


def test_demolition_on_a_parcel_with_no_structure_is_refused(api):
    """
    A demolition order on a parcel that carries no structure is refused even when the crew and the window are beyond reproach.

    A demolition order additionally requires `structure_present` to be true on the parcel, or the request is refused with `ERR_DEMOLITION_REQUIRES_STRUCTURE`.

    Design: Corner/validations/order_gate_family_specialty_license_and_structure_rejected
    """
    funding_source, _with_structure, vacant, _mow_only, short = _order_gate_fixture(api)

    # The crew demolishes and the window closes a day before its licence does,
    # so the missing structure is the only failing test.
    payload = factories.maintenance_order_payload(
        short["id"],
        funding_source["id"],
        vacant["version"],
        work_type="DEMOLITION",
        window_start="2026-08-05T00:00:00Z",
        window_end="2026-08-09T00:00:00Z",
    )
    response = api.create_maintenance_order(vacant["id"], payload, INV_1)
    validate_error(response, ApiErrorId.DEMOLITION_REQUIRES_STRUCTURE.value)

    _assert_nothing_was_scheduled(api, funding_source["id"], vacant)


# ── the 72-hour breathing room around demolition ────────────────────────────
def test_demolition_a_day_after_a_scheduled_mow_breaches_the_buffer(api):
    """
    A demolition order that leaves only a day between itself and an existing scheduled mowing order is refused, even though the two windows never overlap.

    Second, demolition needs breathing room: a demolition order must stand clear of every other `SCHEDULED` order on the same parcel by at least 72 hours, and the pair is rejected with `ERR_DEMOLITION_BUFFER_VIOLATION` when the other order starts strictly before the demolition window's end advanced by 72 hours *and* the other order ends strictly after the demolition window's start pulled back by 72 hours.

    Design: Corner/validations/demolition_buffer_violation_rejected
    """
    funding_source = fixtures.create_funding_source(
        api,
        name="Buffer Rule Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="ANY",
        expires_on="2029-12-31T00:00:00Z",
    )
    prop = fixtures.acquired_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203100",
            "address": "3100 Juniper Ln",
            "situs_ward": 3,
            "lot_area_sqft": 10000,
            "assessed_value_cents": 300000,
            "structure_present": True,
            "structure_condition_grade": "D",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Juniper Estate"},
    )["property"]
    contractor = fixtures.create_contractor(
        api,
        name="Full Service Crew",
        license_expires_on="2027-12-31T00:00:00Z",
        max_concurrent_crews=3,
        specialties=["MOW", "SECURE", "DEMOLITION"],
    )
    mow = fixtures.schedule_order(
        api,
        prop["id"],
        funding_source_id=funding_source["id"],
        contractor_id=contractor["id"],
        work_type="MOW",
        window_start="2026-08-10T00:00:00Z",
        window_end="2026-08-11T00:00:00Z",
    )
    before = fixtures.read_property(api, prop["id"])

    # The mowing window closes on 11 August and the demolition opens on
    # 12 August, so the exclusivity rule is satisfied and only the 72-hour
    # demolition buffer is breached.
    payload = factories.maintenance_order_payload(
        contractor["id"],
        funding_source["id"],
        before["version"],
        work_type="DEMOLITION",
        window_start="2026-08-12T00:00:00Z",
        window_end="2026-08-20T00:00:00Z",
    )
    response = api.create_maintenance_order(prop["id"], payload, INV_1)
    validate_error(response, ApiErrorId.DEMOLITION_BUFFER_VIOLATION.value)

    orders = fixtures.list_orders(api, property_id=prop["id"])
    assert [row["id"] for row in orders] == [mow["id"]]
    assert orders[0]["status"] == "SCHEDULED"

    ledger = fixtures.read_funding_source(api, funding_source["id"])
    assert ledger["committed_cents"] == mow["estimated_cost_cents"]
    assert fixtures.read_property(api, prop["id"])["version"] == before["version"]


# ── execution is only valid from PLANNED ────────────────────────────────────
def test_replaying_execution_on_an_executed_run_is_refused(api):
    """
    Executing a demolition run a second time is refused, and the replay neither creates a second demolition order nor commits the administrative fee twice.

    Executing a run that is not `PLANNED` is refused with `ERR_RUN_NOT_PLANNED`.

    Design: Corner/validations/run_execute_replay_on_executed_run_rejected
    """
    acquisition_source = fixtures.create_acquisition_funding_source(
        api, name="Replay Acquisition Line"
    )
    operations_source = fixtures.create_funding_source(
        api,
        name="Replay Operations Line",
        source_type="GRANT",
        authorized_cents=5000000,
        restriction="DEMOLITION_ONLY",
        expires_on="2029-12-31T00:00:00Z",
    )
    prop = fixtures.demolition_candidate(
        api,
        acquisition_source["id"],
        parcel_id="APN-203080",
        address="3080 Hemlock Ln",
        situs_ward=8,
        lot_area_sqft=3000,
        assessed_value_cents=150000,
        structure_condition_grade="F",
        vacancy_months=0,
    )
    run = fixtures.plan_demolition_run(
        api, operations_source["id"], 3000000, situs_ward_filter=8
    )
    assert run["selected_property_ids"] == [prop["id"]]
    executed = fixtures.execute_demolition_run(api, run["id"])
    assert executed["status"] == "EXECUTED"
    assert executed["orders_created_count"] == 1

    response = api.execute_demolition_run(run["id"], INV_1)
    validate_error(response, ApiErrorId.RUN_NOT_PLANNED.value)

    orders = fixtures.list_orders(api, demolition_run_id=run["id"])
    assert len(orders) == 1
    assert orders[0]["work_type"] == "DEMOLITION"
    assert orders[0]["contractor_id"] is None
    assert orders[0]["status"] == "SCHEDULED"

    # The one demolition estimate plus the one administrative fee, committed
    # exactly once.
    estimate = expected_demolition_estimate_cents(3000, "F")
    committed = estimate + expected_admin_fee_cents(estimate)
    ledger = fixtures.read_funding_source(api, operations_source["id"])
    assert ledger["committed_cents"] == committed
    assert ledger["available_cents"] == 5000000 - committed
    assert ledger["open_run_count"] == 0

    runs = get_success_data(
        api.list_funding_source_demolition_runs(operations_source["id"], INV_1)
    )
    stored = [row for row in runs if row["id"] == run["id"]][0]
    assert stored["status"] == "EXECUTED"
    assert stored["orders_created_count"] == 1
    assert stored["version"] == executed["version"]


# ── recommendation is only valid from SCREENED ──────────────────────────────
def test_recommending_a_merely_submitted_application_is_refused(api):
    """
    An application that has been submitted but never screened cannot be recommended to the board.

    A `DispositionOfficer` recommends an application in `SCREENED`, supplying a `recommendation_memo`, and drives `SCREENED → RECOMMENDED`.

    Design: Corner/validations/recommend_before_screening_rejected
    """
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Recommend Order Line"
    )
    prop = fixtures.listed_parcel(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203070",
            "address": "3070 Gum Ln",
            "situs_ward": 3,
            "lot_area_sqft": 6000,
            "assessed_value_cents": 100000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Gum Lane Estate"},
    )["property"]
    applicant = fixtures.create_applicant(
        api,
        legal_name="Jonas Petrov",
        applicant_type="INDIVIDUAL",
        contact_email="jonas@example.com",
    )
    application = fixtures.draft_application(
        api,
        prop["id"],
        applicant["id"],
        program="HOMEOWNER_SALE",
        proposed_use="Owner-occupied single family",
        offer_price_cents=100000,
    )
    submitted = fixtures.submit_application(api, application["id"], applicant["id"])
    assert submitted["status"] == "SUBMITTED"

    # A second disposition officer asks for the recommendation, so no
    # segregation-of-duties question arises: the status alone decides.
    response = api.recommend_application(
        application["id"], {"recommendation_memo": "Skipping screening"}, DISP_2
    )
    validate_error(response, ApiErrorId.APPLICATION_INVALID_STATE.value)

    after = fixtures.read_application(api, application["id"], DISP_1)
    assert after["status"] == "SUBMITTED"
    assert after["recommended_by_user_id"] is None
    assert after["screening_count"] == 0
    assert after["version"] == submitted["version"]


# ── the three gates on executing a development agreement ────────────────────
def _board_approved_award(api):
    """
    A listed grade C parcel assessed at 400,000 cents, awarded by the board to a
    clean developer whose offer meets the 500,000-cent developer quote.
    """
    funding_source = fixtures.create_acquisition_funding_source(
        api, name="Agreement Gate Line"
    )
    bundle = fixtures.screened_application(
        api,
        funding_source=funding_source,
        property_overrides={
            "parcel_id": "APN-203110",
            "address": "3110 Katsura Ln",
            "situs_ward": 3,
            "lot_area_sqft": 9000,
            "assessed_value_cents": 400000,
            "structure_present": True,
            "structure_condition_grade": "C",
            "vacancy_months": 4,
        },
        packet_overrides={"donor_name": "Katsura Estate"},
        applicant=fixtures.create_developer_applicant(
            api,
            legal_name="Katsura Infill Partners LLC",
            contact_email="bids@katsura-infill.example",
        ),
        application_overrides={
            "program": "DEVELOPER_RFP",
            "proposed_use": "Six-unit workforce housing",
            "offer_price_cents": 500000,
        },
    )
    assert bundle["screening"]["outcome"] == "PASS"
    application_id = bundle["application"]["id"]
    fixtures.recommend_application(api, application_id, "Recommend award")
    approved = fixtures.board_decide(api, application_id, "APPROVE")
    assert approved["status"] == "BOARD_APPROVED"
    bundle["application"] = approved
    return bundle


def _agreement_payload(application_id, **overrides):
    """A four-milestone statutory agreement, with the terms under test pinned."""
    payload = {
        "application_id": application_id,
        "performance_deadline": "2027-08-01T00:00:00Z",
        "milestone_count": 4,
        "reverter_clause_active": True,
        "abatement_years": 10,
        "discharge_mode": "STATUTORY",
        "projected_improved_value_cents": 4000000,
    }
    payload.update(overrides)
    return payload


def test_performance_deadline_equal_to_the_clock_is_refused(api):
    """
    A development agreement whose performance deadline falls exactly on the current instant is refused, because the deadline must lie strictly in the future.

    The `performance_deadline` must fall strictly after the current instant (`ERR_DEADLINE_IN_PAST`), and `abatement_years` must lie between 0 and 10 inclusive — 10 is accepted, 11 is refused with `ERR_ABATEMENT_YEARS_EXCEED_CAP`.

    Design: Corner/validations/agreement_gate_family_deadline_cap_and_duplicate_rejected
    """
    bundle = _board_approved_award(api)
    application = bundle["application"]

    # The abatement term is well inside the cap, so the deadline is the single
    # failing term; the clock still stands at its default instant.
    response = api.create_development_agreement(
        _agreement_payload(
            application["id"],
            performance_deadline="2026-08-01T00:00:00Z",
            abatement_years=5,
        ),
        CLERK_1,
    )
    validate_error(response, ApiErrorId.DEADLINE_IN_PAST.value)

    agreements = get_success_data(
        api.list_development_agreements(CLERK_1, {"application_id": application["id"]})
    )
    assert agreements == []

    after = fixtures.read_application(api, application["id"], DISP_1)
    assert after["status"] == "BOARD_APPROVED"
    assert after["version"] == application["version"]
    parcel = fixtures.read_property(api, bundle["property"]["id"])
    assert parcel["custody_status"] == "LISTED"


def test_eleven_abatement_years_are_refused_while_ten_are_accepted(api):
    """
    An agreement granting eleven years of tax abatement is refused, while the same agreement at the ten-year cap is executed.

    The `performance_deadline` must fall strictly after the current instant (`ERR_DEADLINE_IN_PAST`), and `abatement_years` must lie between 0 and 10 inclusive — 10 is accepted, 11 is refused with `ERR_ABATEMENT_YEARS_EXCEED_CAP`.

    Design: Corner/validations/agreement_gate_family_deadline_cap_and_duplicate_rejected
    """
    bundle = _board_approved_award(api)
    application = bundle["application"]

    # The deadline is comfortably in the future, so the abatement term is the
    # single failing term.
    response = api.create_development_agreement(
        _agreement_payload(application["id"], abatement_years=11), CLERK_1
    )
    validate_error(response, ApiErrorId.ABATEMENT_YEARS_EXCEED_CAP.value)

    agreements = get_success_data(
        api.list_development_agreements(CLERK_1, {"application_id": application["id"]})
    )
    assert agreements == []
    unchanged = fixtures.read_application(api, application["id"], DISP_1)
    assert unchanged["status"] == "BOARD_APPROVED"
    assert unchanged["version"] == application["version"]

    # The cap value itself is a lawful term.
    accepted = get_success_data(
        api.create_development_agreement(
            _agreement_payload(application["id"], abatement_years=10), CLERK_1
        )
    )
    assert accepted["abatement_years"] == 10
    assert accepted["status"] == "EXECUTED"


def test_second_agreement_on_the_same_application_is_refused_as_a_duplicate(api):
    """
    Replaying the execution of a development agreement is refused for the one-agreement-per-application rule rather than for the status the first execution left behind.

    At most one agreement may exist per application, and this uniqueness test is evaluated before the application-state and parcel-custody tests, so a replayed execution reports `ERR_AGREEMENT_ALREADY_EXISTS` rather than a misleading state error.

    Design: Corner/validations/agreement_gate_family_deadline_cap_and_duplicate_rejected
    """
    bundle = _board_approved_award(api)
    application_id = bundle["application"]["id"]
    agreement = get_success_data(
        api.create_development_agreement(_agreement_payload(application_id), CLERK_1)
    )
    awarded = fixtures.read_application(api, application_id, DISP_1)
    assert awarded["status"] == "AWARDED"

    # The first execution already carried the application to AWARDED and the
    # parcel to CONVEYED, and the uniqueness rule outranks both of those states.
    response = api.create_development_agreement(
        _agreement_payload(application_id), CLERK_1
    )
    validate_error(response, ApiErrorId.AGREEMENT_ALREADY_EXISTS.value)

    agreements = get_success_data(
        api.list_development_agreements(CLERK_1, {"application_id": application_id})
    )
    assert [row["id"] for row in agreements] == [agreement["id"]]
    stored = fixtures.read_agreement(api, agreement["id"])
    assert stored["status"] == "EXECUTED"
    assert stored["milestones_completed"] == 0
    assert stored["version"] == agreement["version"]

    after = fixtures.read_application(api, application_id, DISP_1)
    assert after["status"] == "AWARDED"
    assert after["version"] == awarded["version"]
    parcel = fixtures.read_property(api, bundle["property"]["id"])
    assert parcel["custody_status"] == "CONVEYED"
