"""Cascades whose third hop lands on a resource the request never named."""

from test_helpers import (
    activate_storm_event,
    add_technician_to_site,
    assert_housing_occupancy,
    assert_insurer_ledger,
    assert_money_chain,
    assert_supplement_state,
    bring_vehicle_to,
    clear_the_lot_and_demobilize,
    commission_facility,
    file_supplement,
    is_iso8601_timestamp,
    read_deployment,
    read_event,
    read_facility,
    read_housing_units,
    read_insurer,
    read_technician,
    read_vehicle,
    setup_housed_crew,
    setup_operational_facility,
    tech_id,
)

DEMOBILIZE_CLOCK = "2026-08-20T09:00:00Z"
DEMOBILIZE_DATE = "2026-08-20"


def _housed_site_ready_to_wind_down(api):
    """One commissioned lot on an active event, one housed technician, no cars."""
    scenario = setup_housed_crew(api, bed_count=2)
    add_technician_to_site(
        api,
        scenario,
        "TA",
        on_site=True,
        housing_unit_id=scenario["housing_unit_id"],
    )
    scenario["facility"] = commission_facility(api, scenario["facility_id"])
    scenario["event"] = activate_storm_event(api, scenario["event_id"])
    return scenario


def test_demobilizing_the_event_freezes_the_lot_and_sends_the_crew_home(api):
    """PRD §3.9: "On success the event's `status` becomes `DEMOBILIZING`,
    `demobilized_at` is stamped from the logical clock, and `version` increments,
    followed by a three-hop cascade. Hop one: every facility of the event whose
    `status` is `SETUP`, `COMMISSIONED` or `SUSPENDED` moves to `DEMOBILIZED`,
    terminal, with `posture` forced to `FROZEN` and a `version` increment each."

    PRD §3.9: "Hop two, caused by hop one: for each facility that just became
    `DEMOBILIZED`, every crew deployment at that facility whose `status` is
    `CONFIRMED` or `ON_SITE` is moved to `ENDED`, terminal, with
    `actual_end_date` written from the current clock date and a `version`
    increment — the crew goes home whether or not it was formally on site."

    Design: Difficulty/transitive_cascade/demobilization_cascade_ends_deployments_and_releases_housing
    """
    scenario = _housed_site_ready_to_wind_down(api)
    deployment_id = scenario["deployments"]["TA"]["id"]

    event = clear_the_lot_and_demobilize(api, scenario, at_clock=DEMOBILIZE_CLOCK)

    assert event["status"] == "DEMOBILIZING"
    assert is_iso8601_timestamp(event["demobilized_at"])
    assert event["demobilized_at"] == DEMOBILIZE_CLOCK
    assert read_event(api, scenario["event_id"])["status"] == "DEMOBILIZING"

    facility = read_facility(api, scenario["facility_id"])
    assert facility["status"] == "DEMOBILIZED"
    assert facility["posture"] == "FROZEN"

    deployment = read_deployment(api, deployment_id)
    assert deployment["status"] == "ENDED"
    assert deployment["actual_end_date"] == DEMOBILIZE_DATE
    assert deployment["effective_end_date"] == DEMOBILIZE_DATE


def test_the_shortened_deployment_reaches_housing_and_the_roster(api):
    """PRD §3.9: "Hop three, caused by hop two: for each deployment that just
    ended, its housing unit — where `housing_unit_id` is not null — recomputes
    `occupied_beds` and `bed_nights_committed` from the newly shortened
    `effective_end_date`, and its technician recomputes `deployment_state`, which
    for most of the crew flips `DEPLOYED` back to `AVAILABLE`."

    PRD §3.3: "`bed_nights_committed` sums, over the unit's deployments that are
    `CONFIRMED`, `ON_SITE` or `ENDED`, the whole number of days from `start_date`
    to the deployment's effective end date — so a cancelled booking contributes
    nothing while an ended one contributes its shortened stay."

    Design: Difficulty/transitive_cascade/demobilization_cascade_ends_deployments_and_releases_housing
    """
    scenario = _housed_site_ready_to_wind_down(api)
    clear_the_lot_and_demobilize(api, scenario, at_clock=DEMOBILIZE_CLOCK)

    units = read_housing_units(api, scenario["facility_id"])
    assert len(units) == 1
    # The stay ran from 5 August to the 20th, and the bed is empty from the 20th.
    assert_housing_occupancy(units[0], occupied_beds=0, bed_nights_committed=15)

    technician = read_technician(api, tech_id(scenario, "TA"))
    assert technician["deployment_state"] == "AVAILABLE"


AUTO_APPROVE_THRESHOLD_CENTS = 20289


def _auto_approved_supplement(api):
    """File a supplement for exactly the auto-approval threshold."""
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(api, scenario, "AUTHORIZED", damage_profile="three_panel")
    supplement = file_supplement(
        api,
        car["vehicle_id"],
        AUTO_APPROVE_THRESHOLD_CENTS,
        reason_code="R_AND_I_ADDITION",
    )
    return scenario, car, supplement


def test_a_supplement_at_exactly_the_threshold_is_born_approved(api):
    """PRD §3.8: "The auto-approval threshold is the larger of 15,000 cents (150
    dollars) and the pinned sheet's `supplement_auto_approve_pct` multiplied by
    the vehicle's `approved_repair_cents`, rounded half up to whole cents — the
    floor exists so that trivial supplements clear even on cheap repairs."

    PRD §3.8: "When the amount under test is less than or equal to that
    threshold, and only when `round_index` is 1 so that the evaluation happens at
    creation and nowhere else, the supplement is born `AUTO_APPROVED`, a terminal
    state: `approved_amount_cents` is set to `requested_amount_cents` and
    `decided_at` is stamped from the logical clock."

    PRD §3.8: "A new supplement copies the vehicle's `pinned_rate_agreement_id`
    into its own `rate_agreement_id`, starts at `round_index` 1, and increments
    the vehicle's `version` by one."

    Design: Difficulty/transitive_cascade/supplement_auto_approval_cascades_vehicle_facility_and_insurer_ledgers
    """
    scenario, car, supplement = _auto_approved_supplement(api)

    assert_supplement_state(
        supplement,
        status="AUTO_APPROVED",
        round_index=1,
        approved_amount_cents=AUTO_APPROVE_THRESHOLD_CENTS,
        requested_amount_cents=AUTO_APPROVE_THRESHOLD_CENTS,
    )
    assert supplement["reason_code"] == "R_AND_I_ADDITION"
    assert is_iso8601_timestamp(supplement["decided_at"])
    assert supplement["rate_agreement_id"] == scenario["rate_agreement_id"]


def test_the_auto_approval_walks_the_vehicle_the_lot_and_the_carrier(api):
    """PRD §3.8: "An auto-approval cascades three hops. Hop one: the vehicle's
    `approved_supplement_cents` grows by the approved amount and the whole
    net-billable chain is recomputed. Hop two, caused by hop one: when the
    vehicle's `billing_status` is `AUTHORIZED`, `BILLED` or `PAID`, the
    facility's `billable_accrued_cents` absorbs the change in
    `net_billable_cents`. Hop three, caused by hop two: the vehicle's carrier
    recomputes `outstanding_direct_bill_cents` and `settled_cents` from the same
    change."

    Design: Difficulty/transitive_cascade/supplement_auto_approval_cascades_vehicle_facility_and_insurer_ledgers
    """
    scenario, car, _ = _auto_approved_supplement(api)

    vehicle = read_vehicle(api, car["vehicle_id"])
    assert vehicle["approved_repair_cents"] == 202886
    assert vehicle["approved_supplement_cents"] == AUTO_APPROVE_THRESHOLD_CENTS
    assert_money_chain(
        vehicle,
        admin_fee_cents=11159,
        gross_billable_cents=234334,
        discount_cents=0,
        net_billable_cents=234334,
    )

    facility = read_facility(api, scenario["facility_id"])
    assert facility["billable_accrued_cents"] == 234334

    assert_insurer_ledger(
        read_insurer(api, scenario["insurer_id"]),
        outstanding_direct_bill_cents=234334,
        settled_cents=0,
    )
