"""Endpoint behaviour: linking a loaner, reading a unit's derived fields, and
staging then releasing a certified unit.

Every expectation below is taken from the reconditioning API's product
requirements: the loaner booking rules of the loaner-substitution narrative, the
age/warranty/severity derivations carried on an equipment unit, and the custody
axis that stages and releases a certified shell.
"""
from test_helpers import (
    INSPECTOR_1,
    INTAKE_CLERK,
    REPAIR_IMPACTS,
    assert_disposition_ledger_conserved,
    assert_equipment_unit,
    assert_loaner_assignment,
    create_loaner_assignment_payload,
    read_loaner_unit,
    read_shipment,
    release_unit_payload,
    setup_certified_units,
    setup_loaner_pool,
    setup_tested_units,
    validate_paginated,
    validate_success,
)

RELEASED_TO = "Northside High - J. Ruiz, equipment manager"


def test_booking_a_loaner_links_the_account_and_the_loaner_unit(api):
    """Booking a named loaner joins the account and the loaner unit.

    The requirements state: "The clerk may name a specific `loaner_unit_id`, in
    which case `selected_by` is recorded as `EXPLICIT`; omitting it delegates the
    choice to the plant's selector policy and records `selected_by` as
    `SERVER_SELECTED`." They further state: "The assignment's initial `status`
    depends on the clock at creation: `OUT_ON_LOAN` when `window_start` is less
    than or equal to the logical clock, and `RESERVED` when `window_start` is
    strictly later." and "Booking drives the chosen loaner `AVAILABLE →
    RESERVED` or `AVAILABLE → OUT_ON_LOAN` to match, increments that loaner's
    `assignment_count` by one, and advances the loaner's `version` by one."
    With the clock at 2026-08-01 and a window opening 2026-08-05, the new
    assignment is RESERVED and is reachable from the account side and from the
    loaner side alike.

    Design: Corner/endpoints/booking_a_loaner_links_the_account_and_the_loaner_unit
    """
    ctx = setup_loaner_pool(grades=("A",))
    account_id = ctx["account"]["id"]
    loaner_id = ctx["loaner"]["id"]

    response = api.create_loaner_assignment(
        create_loaner_assignment_payload(
            account_id, ctx["model"]["id"], loaner_unit_id=loaner_id
        ),
        INTAKE_CLERK,
    )
    assignment = validate_success(response, 201)
    assert_loaner_assignment(assignment)
    assert assignment["customer_account_id"] == account_id
    assert assignment["requested_model_spec_id"] == ctx["model"]["id"]
    assert assignment["loaner_unit_id"] == loaner_id
    assert assignment["selected_by"] == "EXPLICIT"
    assert assignment["status"] == "RESERVED"
    assert assignment["returned_at"] is None
    assert assignment["version"] == 1

    loaner = read_loaner_unit(loaner_id)
    assert loaner["status"] == "RESERVED"
    assert loaner["assignment_count"] == 1
    assert loaner["version"] == ctx["loaner"]["version"] + 1

    by_account, account_meta = validate_paginated(
        api.list_loaner_assignments(INTAKE_CLERK, params={"customer_account_id": account_id})
    )
    assert account_meta["total_count"] == 1
    assert [row["id"] for row in by_account] == [assignment["id"]]

    by_loaner, loaner_meta = validate_paginated(
        api.list_loaner_assignments(INTAKE_CLERK, params={"loaner_unit_id": loaner_id})
    )
    assert loaner_meta["total_count"] == 1
    assert [row["id"] for row in by_loaner] == [assignment["id"]]


def test_reading_a_unit_returns_every_derived_field_at_once(api):
    """One unit read reconciles age, warranty, verdict rollup and severity index.

    The requirements state: "Under the `MANUFACTURE_DATE` basis,
    `service_age_years` is the whole number of elapsed days between the
    manufacture date and the current date on the logical clock, divided by 365
    days per service year and rounded down to a whole number." They also state:
    "`warranty_coverage`, which reads `PENDING` on an unidentified unit, becomes
    `IN_WARRANTY` when `service_age_years` is less than or equal to the model's
    `warranty_years` and `OUT_OF_WARRANTY` otherwise." and "Recording stores the
    three readings, computes the severity index and the machine result, advances
    the session `SCHEDULED → COMPLETED`, advances the unit `INSPECTED → TESTED`
    or `REPAIRED → TESTED` depending on which side of the recertification cycle
    the unit is on, copies the session's `severity_index` onto the unit as
    `current_si`, and advances both the session's and the unit's `version` by
    one." A shell manufactured 2018-09-15 read against a clock of 2026-08-01 is
    seven service years old on a ten-year model, so it is not life expired but is
    out of its five-year warranty; readings of 300/340/290 taken AMBIENT on a
    POLYCARBONATE model weight to 150.0 + 102.0 + 58.0, a severity index of
    310.0.

    Design: Corner/endpoints/reading_a_unit_returns_every_derived_field_at_once
    """
    ctx = setup_tested_units(unit_count=1, impacts=REPAIR_IMPACTS)

    unit = validate_success(api.get_equipment_unit(ctx["unit"]["id"], INSPECTOR_1), 200)
    assert_equipment_unit(unit)
    assert unit["service_age_years"] == 7
    assert unit["life_expired"] is False
    assert unit["warranty_coverage"] == "OUT_OF_WARRANTY"
    assert unit["inspection_verdict_summary"] == "CLEAR"
    assert unit["condemn_required"] is False
    assert unit["current_si"] == 310.0
    assert unit["retest_count"] == 0
    assert unit["recon_status"] == "TESTED"
    assert unit["custody_status"] == "AT_PLANT"


def test_staging_then_releasing_a_unit_records_the_recipient(api):
    """Release stamps the recipient and moves one unit between two counters.

    The requirements state: "An `IntakeClerk` stages a unit for return, moving
    its `custody_status` `AT_PLANT → STAGED_FOR_RETURN`; the unit's
    `recon_status` must be `CERTIFIED` for staging to be defined, and the unit's
    `version` advances by one." They continue: "Release moves `custody_status`
    `STAGED_FOR_RETURN → RETURNED`, records `released_to`, moves one unit on the
    parent shipment out of `units_certified` and into `units_released`, and
    advances the unit's `version` by one." The custody axis "advances under its
    own requests and never touches `recon_status`", so the released shell is
    still CERTIFIED.

    Design: Corner/endpoints/staging_then_releasing_a_unit_records_the_recipient
    """
    ctx = setup_certified_units(unit_count=1)
    unit_id = ctx["unit"]["id"]
    certified_version = ctx["unit"]["version"]

    staged = validate_success(api.stage_return_equipment_unit(unit_id, INTAKE_CLERK), 200)
    assert staged["custody_status"] == "STAGED_FOR_RETURN"
    assert staged["recon_status"] == "CERTIFIED"
    assert staged["version"] == certified_version + 1

    released = validate_success(
        api.release_equipment_unit(
            unit_id, release_unit_payload(released_to=RELEASED_TO), INTAKE_CLERK
        ),
        200,
    )
    assert_equipment_unit(released)
    assert released["custody_status"] == "RETURNED"
    assert released["recon_status"] == "CERTIFIED"
    assert released["released_to"] == RELEASED_TO
    assert released["version"] == certified_version + 2

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["units_in_process"] == 0
    assert shipment["units_certified"] == 0
    assert shipment["units_condemned"] == 0
    assert shipment["units_released"] == 1
    assert shipment["counted_unit_count"] == 1
    assert shipment["status"] == "READY_FOR_RETURN"
    assert_disposition_ledger_conserved(shipment)
