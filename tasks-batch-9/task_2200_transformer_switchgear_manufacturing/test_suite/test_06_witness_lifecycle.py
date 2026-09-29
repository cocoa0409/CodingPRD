"""Witness administration: the two arms of decline, and the day-bucket capacity
gate against the travel blackout day set."""

from test_helpers import (
    CONTRACT_ADMIN,
    TEST_ENGINEER,
    WITNESS_COORDINATOR,
    assert_bay_scheduled_hours,
    assert_instant_equals,
    assert_order_state,
    create_bay,
    create_component,
    create_fat,
    create_order,
    create_supplier,
    create_witness_party,
    drive_order_to_in_production,
    make_customer_witness_headers,
    read_bay,
    read_order,
    schedule_fat,
    set_clock,
    witness_assignment_payload,
)
from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers.api_errors import ApiErrorId


def test_decline_has_two_arms_and_the_bay_window_survives_the_whole_churn(api):
    """PRD 3.5: "Declining from `CONFIRMED`... decreases `confirmed_witness_count`
    by 1, and — when that count falls to 0 while `witness_required` is still true —
    pulls the test back `WITNESS_CONFIRMED → BAY_SCHEDULED`, adds the reason
    `WITNESS_MISSING`... The bay window is deliberately retained across this
    cycle... Declining from `INVITED` records the reason and leaves
    `confirmed_witness_count` untouched."

    Design: Difficulty/non_linear_state_machine/witness_churn_cycle_bay_scheduled_confirmed_twice_with_two_different_decline_arms
    """
    set_clock(api, "2026-02-01T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-N05", legal_name="Basin Windings", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="COIL-N",
        category="CORE_STEEL_COIL",
        lead_time_days=45,
        quantity_on_hand=8,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-NLS-0005",
        customer_name="Basin Electric Coop",
        product_family="POWER_TRANSFORMER",
        rated_kv=69,
        contract_value_cents=3000000,
        sold_at="2026-02-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=2,
        need_by_date="2026-07-01T00:00:00Z",
        drawing_set_code="DS-N",
    )
    bay = create_bay(
        api,
        bay_code="BAY-NL1",
        max_kv=145,
        changeover_buffer_hours=4,
        supports_impulse=True,
    )
    party = create_witness_party(
        api,
        party_code="WP-NL1",
        display_name="Basin Electric Witness",
        party_type="CUSTOMER",
        home_region="NA",
        daily_witness_capacity=1,
        credential_expires_at="2027-01-01T00:00:00Z",
    )
    witness = make_customer_witness_headers(party["id"])
    fat = create_fat(
        api, order["id"], test_duration_hours=8, witness_required=True
    )
    schedule_fat(api, fat["id"], bay["id"], "2026-02-10T08:00:00Z")
    assignment = validate_success(
        api.create_witness_assignment(
            fat["id"], witness_assignment_payload(party["id"], travel_region="NA"),
            WITNESS_COORDINATOR,
        ),
        201,
    )
    assert assignment["status"] == "INVITED"

    def read_fat():
        return validate_success(
            api.get_factory_acceptance_test(fat["id"], TEST_ENGINEER)
        )

    confirmed = validate_success(
        api.confirm_witness_assignment(assignment["id"], {}, witness)
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["blackout_days"] == 0
    assert_instant_equals(confirmed["confirmed_at"], "2026-02-01T00:00:00Z")
    first_pass = read_fat()
    assert first_pass["status"] == "WITNESS_CONFIRMED"
    assert first_pass["confirmed_witness_count"] == 1
    assert_order_state(
        read_order(api, order["id"]),
        production_posture="OPEN",
        posture_reason_codes=[],
    )

    # Arm one: from CONFIRMED the decline drags the parent test backwards.
    declined = validate_success(
        api.decline_witness_assignment(
            assignment["id"], {"decline_reason": "Travel budget frozen"}, witness
        )
    )
    assert declined["status"] == "DECLINED"
    dragged = read_fat()
    assert dragged["status"] == "BAY_SCHEDULED"
    assert dragged["confirmed_witness_count"] == 0
    assert dragged["test_bay_id"] == bay["id"]
    assert_instant_equals(dragged["window_end_at"], "2026-02-10T20:00:00Z")
    assert_order_state(
        read_order(api, order["id"]),
        production_posture="RESTRICTED",
        posture_reason_codes=["WITNESS_MISSING"],
    )

    reinvited = validate_success(
        api.reinvite_witness_assignment(assignment["id"], {}, WITNESS_COORDINATOR)
    )
    assert reinvited["status"] == "INVITED"
    assert reinvited["decline_reason"] is None
    still_scheduled = read_fat()
    assert still_scheduled["status"] == "BAY_SCHEDULED"
    assert still_scheduled["confirmed_witness_count"] == 0

    # Arm two: from INVITED the very same endpoint has no parent-level effect.
    second_decline = validate_success(
        api.decline_witness_assignment(
            assignment["id"], {"decline_reason": "Still unresolved"}, witness
        )
    )
    assert second_decline["status"] == "DECLINED"
    untouched = read_fat()
    assert untouched["status"] == "BAY_SCHEDULED"
    assert untouched["confirmed_witness_count"] == 0

    validate_success(
        api.reinvite_witness_assignment(assignment["id"], {}, WITNESS_COORDINATOR)
    )
    validate_success(api.confirm_witness_assignment(assignment["id"], {}, witness))
    second_pass = read_fat()
    assert second_pass["status"] == "WITNESS_CONFIRMED"
    assert second_pass["confirmed_witness_count"] == 1
    assert_order_state(
        read_order(api, order["id"]),
        production_posture="OPEN",
        posture_reason_codes=[],
    )

    # The slot was never surrendered, so the bay never re-accrued its hours.
    assert_bay_scheduled_hours(read_bay(api, bay["id"]), 8)


def test_day_bucket_capacity_and_the_symmetric_travel_blackout_day_set(api):
    """PRD 3.5: "The **day** of an assignment is the UTC calendar date of its
    parent test's `window_start_at`, with the time of day discarded... the
    party's existing load on the candidate's day must be strictly less than
    `daily_witness_capacity`... An assignment whose `travel_region` is any other
    region has `blackout_days` of 1 and blacks out the day immediately before and
    the day immediately after its own day. Confirmation is refused when the
    candidate's day falls inside the union of the blackout day sets of the
    party's already-confirmed assignments, and equally when any already-confirmed
    assignment's day falls inside the candidate's own blackout set."

    Design: Difficulty/resource_temporal_overlap/witness_day_bucket_capacity_versus_travel_blackout_day_set_symmetry
    """
    set_clock(api, "2026-06-20T00:00:00Z")
    supplier = create_supplier(
        api, supplier_code="SUP-WIT", legal_name="Basin Muni Supply", region="NA"
    )
    component = create_component(
        api,
        supplier["id"],
        part_number="WIT-BSH",
        category="HV_BUSHING",
        lead_time_days=20,
        quantity_on_hand=10,
        allocation_policy="PROTECTED",
    )
    order = create_order(
        api,
        order_number="TX-WIT-0001",
        customer_name="Basin Electric Muni",
        product_family="POWER_TRANSFORMER",
        rated_kv=12,
        contract_value_cents=15000000,
        sold_at="2026-03-01T00:00:00Z",
        promised_ship_at="2026-12-01T00:00:00Z",
    )
    drive_order_to_in_production(
        api,
        order,
        component["id"],
        quantity=2,
        need_by_date="2026-12-01T00:00:00Z",
        drawing_set_code="DS-WIT-A",
    )
    bay = create_bay(
        api,
        bay_code="BAY-WIT",
        max_kv=145,
        changeover_buffer_hours=1,
        supports_impulse=False,
    )
    party = create_witness_party(
        api,
        party_code="WP-WIT-1",
        display_name="Basin Muni Witness",
        party_type="CUSTOMER",
        home_region="NA",
        daily_witness_capacity=2,
        credential_expires_at="2027-12-31T00:00:00Z",
    )

    def scheduled_fat(window_start_at):
        fat = create_fat(
            api, order["id"], test_duration_hours=4, witness_required=True
        )
        schedule_fat(api, fat["id"], bay["id"], window_start_at)
        return fat

    fat_e = scheduled_fat("2026-07-04T12:00:00Z")
    fat_a = scheduled_fat("2026-07-05T01:00:00Z")
    fat_c = scheduled_fat("2026-07-05T07:00:00Z")
    fat_b = scheduled_fat("2026-07-05T22:00:00Z")
    fat_d = scheduled_fat("2026-07-06T12:00:00Z")
    fat_f = scheduled_fat("2026-07-08T09:00:00Z")
    fat_g = scheduled_fat("2026-07-09T09:00:00Z")

    def invite(fat, travel_region):
        return validate_success(
            api.create_witness_assignment(
                fat["id"],
                witness_assignment_payload(party["id"], travel_region=travel_region),
                WITNESS_COORDINATOR,
            ),
            201,
        )

    def confirm(assignment):
        return api.confirm_witness_assignment(
            assignment["id"], {}, WITNESS_COORDINATOR
        )

    # First 07-05 confirmation: load 0 < capacity 2, and NA blacks out nothing.
    wa_a = invite(fat_a, "NA")
    confirmed_a = validate_success(confirm(wa_a))
    assert confirmed_a["status"] == "CONFIRMED"
    assert confirmed_a["blackout_days"] == 0
    advanced = validate_success(
        api.get_factory_acceptance_test(fat_a["id"], TEST_ENGINEER)
    )
    assert advanced["status"] == "WITNESS_CONFIRMED"
    assert advanced["confirmed_witness_count"] == 1

    # Adjacency is irrelevant while every confirmed row is NA.
    wa_d = invite(fat_d, "NA")
    assert validate_success(confirm(wa_d))["status"] == "CONFIRMED"

    # A window that runs past midnight still buckets only on its start day.
    wa_b = invite(fat_b, "NA")
    assert validate_success(confirm(wa_b))["status"] == "CONFIRMED"

    # The third 07-05 candidate is the first refusal: the gate runs before the
    # candidate is counted, so two confirmed is the last accepted state.
    wa_c = invite(fat_c, "NA")
    validate_error(confirm(wa_c), ApiErrorId.WITNESS_DAY_CAPACITY, 409)
    assert validate_success(
        api.get_witness_assignment(wa_c["id"], WITNESS_COORDINATOR)
    )["status"] == "INVITED"
    assert validate_success(
        api.get_factory_acceptance_test(fat_c["id"], TEST_ENGINEER)
    )["confirmed_witness_count"] == 0

    # 07-04 has a load of 0, yet the candidate's own EU blackout set
    # {07-03, 07-05} contains two confirmed days.
    wa_e = invite(fat_e, "EU")
    validate_error(confirm(wa_e), ApiErrorId.WITNESS_TRAVEL_BLACKOUT, 422)

    # An EU assignment is admissible in isolation, and its blackout set
    # {07-07, 07-09} then goes live.
    wa_f = invite(fat_f, "EU")
    confirmed_f = validate_success(confirm(wa_f))
    assert confirmed_f["status"] == "CONFIRMED"
    assert confirmed_f["blackout_days"] == 1

    # The other direction of the same rule: the candidate is NA and contributes
    # no blackout of its own, but the confirmed EU row blocks it.
    wa_g = invite(fat_g, "NA")
    validate_error(confirm(wa_g), ApiErrorId.WITNESS_TRAVEL_BLACKOUT, 422)

    body = api.list_witness_assignments(
        WITNESS_COORDINATOR,
        {"witness_party_id": party["id"], "status": "CONFIRMED", "limit": 100},
    ).json()
    assert len(body["data"]) == 4
    assert {row["id"] for row in body["data"]} == {
        wa_a["id"], wa_b["id"], wa_d["id"], wa_f["id"]
    }
    validate_success(api.get_witness_party_load(party["id"], WITNESS_COORDINATOR))
    assert validate_success(
        api.get_engineered_order(order["id"], CONTRACT_ADMIN)
    )["fulfillment_status"] == "IN_PRODUCTION"
