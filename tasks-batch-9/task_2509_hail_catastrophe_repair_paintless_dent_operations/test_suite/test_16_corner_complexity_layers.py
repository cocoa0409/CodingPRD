"""The two optimistic-concurrency guards, each read off its own parent row."""

from test_helpers import (
    CLOCK_T0,
    DIRECTOR,
    SHOP_ESTIMATOR,
    activate_rate_agreement,
    assert_money_chain,
    assert_supplement_state,
    authorize_vehicle,
    bring_vehicle_to,
    create_insurer,
    create_storm_event,
    draft_rate_agreement,
    file_supplement,
    ids_of,
    rate_agreement_activate_payload,
    read_facility,
    read_insurer,
    read_insurer_version,
    read_rate_agreement,
    read_vehicle,
    read_vehicle_version,
    set_clock,
    setup_operational_facility,
    supplement_payload,
    target_storm_event,
    validate_error,
    validate_paginated,
)

SECOND_SHEET = {
    "effective_from": "2026-08-10",
    "matrix_rate_dime_cents": 2300,
    "matrix_rate_nickel_cents": 3100,
    "matrix_rate_quarter_cents": 4300,
    "matrix_rate_half_dollar_cents": 5700,
    "labor_rate_cents_per_hour": 6600,
    "panel_cap_cents": 145000,
}


def _one_carrier_holding_two_draft_sheets(api):
    """A targeted event and a carrier with two `DRAFT` sheets awaiting promotion."""
    set_clock(api, CLOCK_T0)
    event = create_storm_event(api)
    target_storm_event(api, event["id"])
    insurer = create_insurer(api)
    first = draft_rate_agreement(api, insurer["id"], event["id"])
    second = draft_rate_agreement(api, insurer["id"], event["id"], **SECOND_SHEET)
    return insurer["id"], first, second


def test_activating_one_sheet_invalidates_the_version_the_next_one_was_holding(api):
    """PRD §2.9: "`POST /hail-ops/rate-agreements/{id}/activate` requires
    `expected_insurer_version` as a non-optional field of the request body, carrying
    the client's last observed `version` of the carrier named by the agreement's
    `insurer_id`. If that value does not equal the carrier's current `version`, the
    activation is rejected with `ERR_STALE_INSURER_VERSION` (HTTP 412)."

    PRD §3.4: "The cascade then runs two hops: every other agreement sharing the same
    carrier and the same storm event that was `ACTIVE` is moved to `SUPERSEDED` with
    its own `version` increment, and the carrier's `version` increments by one while
    its `active_rate_agreement_count` is recomputed. That carrier version bump is
    precisely what makes a second activation attempt with a now-stale
    `expected_insurer_version` fail."

    PRD §2.11: "**Carrier stale version** — `ERR_STALE_INSURER_VERSION` (412), on
    `POST /hail-ops/rate-agreements/{id}/activate`."

    Design: Corner/cross_cutting_complexity_layers/stale_insurer_version_blocks_activation_then_the_refreshed_one_supersedes
    """
    insurer_id, first, second = _one_carrier_holding_two_draft_sheets(api)
    observed_once = read_insurer_version(api, insurer_id)

    promoted = activate_rate_agreement(
        api, first["id"], insurer_id, expected_insurer_version=observed_once
    )
    assert promoted["status"] == "ACTIVE"
    assert promoted["activated_at"] == CLOCK_T0

    carrier = read_insurer(api, insurer_id)
    assert carrier["version"] == observed_once + 1
    assert carrier["active_rate_agreement_count"] == 1

    # The client's cached carrier version was spent by the first activation.
    replayed = api.activate_rate_agreement(
        second["id"], rate_agreement_activate_payload(observed_once), DIRECTOR
    )
    validate_error(replayed, "ERR_STALE_INSURER_VERSION", 412)

    still_draft = read_rate_agreement(api, second["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["activated_at"] is None
    assert still_draft["version"] == second["version"]

    # A rejected concurrency write bumps nothing, so one re-read is enough.
    observed_again = read_insurer_version(api, insurer_id)
    assert observed_again == observed_once + 1

    retried = activate_rate_agreement(
        api, second["id"], insurer_id, expected_insurer_version=observed_again
    )
    assert retried["status"] == "ACTIVE"
    assert read_rate_agreement(api, first["id"])["status"] == "SUPERSEDED"
    assert read_insurer(api, insurer_id)["active_rate_agreement_count"] == 1

    rows, meta = validate_paginated(
        api.list_rate_agreements(DIRECTOR, {"insurer_id": insurer_id, "status": "ACTIVE"})
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [second["id"]]


def test_the_carriers_authorization_invalidates_the_estimators_cached_version(api):
    """PRD §2.9: "`POST /hail-ops/supplements` requires `expected_vehicle_version` as
    a non-optional field of the request body, carrying the client's last observed
    `version` of the vehicle named by `vehicle_id`. If that value does not equal the
    vehicle's current `version`, the filing is rejected with
    `ERR_STALE_VEHICLE_VERSION` (HTTP 412)."

    PRD §2.11: "**Vehicle stale version** — `ERR_STALE_VEHICLE_VERSION` (412), on
    `POST /hail-ops/supplements`."

    PRD §2.11: "**Supplement cumulative cap** — `ERR_SUPPLEMENT_CUMULATIVE_CAP_EXCEEDED`
    (422), on `POST /hail-ops/supplements` and `POST /hail-ops/supplements/{id}/revise`."

    PRD §3.8: "When the amount under test is less than or equal to that threshold, and
    only when `round_index` is 1 so that the evaluation happens at creation and
    nowhere else, the supplement is born `AUTO_APPROVED`, a terminal state:
    `approved_amount_cents` is set to `requested_amount_cents` and `decided_at` is
    stamped from the logical clock."

    Design: Corner/cross_cutting_complexity_layers/stale_vehicle_version_blocks_a_supplement_until_the_client_re_reads
    """
    scenario = setup_operational_facility(api)
    car = bring_vehicle_to(
        api,
        scenario,
        "TRIAGED",
        damage_profile="single_panel_conventional",
        rental_required=False,
    )
    vehicle_id = car["vehicle_id"]
    insurer_id = scenario["insurer_id"]
    assert car["vehicle"]["approved_repair_cents"] == 77000
    observed_once = read_vehicle_version(api, vehicle_id)

    # The carrier writes to the same row the estimator is about to file against.
    authorize_vehicle(api, vehicle_id, insurer_id)
    observed_again = read_vehicle_version(api, vehicle_id)
    assert observed_again == observed_once + 1

    stale = api.create_supplement(
        supplement_payload(vehicle_id, 12000, observed_once), SHOP_ESTIMATOR
    )
    validate_error(stale, "ERR_STALE_VEHICLE_VERSION", 412)
    _, nothing_filed = validate_paginated(
        api.list_supplements(SHOP_ESTIMATOR, {"vehicle_id": vehicle_id})
    )
    assert nothing_filed["total_count"] == 0

    # 40,000 is over the 30,800 cap, yet the stale guard has the lower ordinal.
    stale_and_over_cap = api.create_supplement(
        supplement_payload(vehicle_id, 40000, observed_once), SHOP_ESTIMATOR
    )
    validate_error(stale_and_over_cap, "ERR_STALE_VEHICLE_VERSION", 412)

    rejected_twice = read_vehicle(api, vehicle_id)
    assert rejected_twice["version"] == observed_again
    assert rejected_twice["approved_supplement_cents"] == 0

    # 12,000 sits under the 15,000 floor, so the identical claim clears itself.
    filed = file_supplement(
        api, vehicle_id, 12000, expected_vehicle_version=observed_again
    )
    assert_supplement_state(
        filed, status="AUTO_APPROVED", round_index=1, approved_amount_cents=12000
    )
    assert filed["decided_at"] == CLOCK_T0

    vehicle = read_vehicle(api, vehicle_id)
    assert vehicle["approved_supplement_cents"] == 12000
    assert_money_chain(
        vehicle,
        admin_fee_cents=4450,
        gross_billable_cents=93450,
        discount_cents=0,
        net_billable_cents=93450,
    )
    assert read_facility(api, scenario["facility_id"])["billable_accrued_cents"] == 93450
    assert read_insurer(api, insurer_id)["outstanding_direct_bill_cents"] == 93450

    rows, meta = validate_paginated(
        api.list_supplements(
            SHOP_ESTIMATOR, {"vehicle_id": vehicle_id, "status": "AUTO_APPROVED"}
        )
    )
    assert meta["total_count"] == 1
    assert ids_of(rows) == [filed["id"]]
