"""Endpoint-level corner cases: herd-profile repropagation, the nutrient-summary
defaults, renewal completion, the three-way transfer link and plan editability.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client as client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_common_fields,
    assert_operation_sizing,
    assert_quantity,
    assert_storage_balance,
    assert_storage_capacities,
)
from test_helpers.fixtures import (
    initiate_transfer,
    record_application,
    register_hauler,
    set_clock,
    setup_ready_operation,
    setup_scenario,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    make_hauler_headers,
    make_operator_headers,
)



def _instant(value):
    """Parse an ISO 8601 instant, tolerating the trailing Z and fractions."""
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _same_instant(actual, expected, label="instant"):
    assert actual is not None, f"{label} is missing"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def test_herd_profile_patch_repropagates_storage_days_to_every_structure():
    """A herd-profile patch re-derives production and pushes the new denominator
    into both the operation-wide storage days and each structure's own figure.

    Switching Willow Creek Dairy to DRY handling with no open lot drops the
    design annual volume to 2,700,000.00 gallons and daily production to
    7,397.26, which lifts the 4,488,300.00 gallons of operating capacity from
    485 to 606 days on the operation and on Lagoon 1 alike.

    PRD: "Any such revision re-derives `animal_units`, `size_class`, `permit_required`, `design_annual_manure_gallons` and `daily_production_gallons`; recomputes the operation's `design_storage_days`; recomputes `days_of_storage_available` on every storage structure of the operation, since the daily production figure is the denominator of both; and increments the operation's `version` by 1."
    PRD: "A dilution factor of 1.15 applies under `LIQUID` handling and 1.0 under `DRY` handling, reflecting the wash and flush water that a liquid system adds."
    Design: Corner/endpoints/patching_the_herd_profile_repropagates_storage_days_to_every_structure
    """
    ctx = setup_scenario(stage="STORAGE")
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = make_operator_headers(operation_id)

    before = validate_success(client.get_operation(operation_id, operator_headers))
    assert before["design_storage_days"] == 485, (
        "the liquid-handling baseline should hold 485 days of storage, "
        f"got {before['design_storage_days']}"
    )

    patched = validate_success(
        client.update_operation(
            operation_id,
            {"county": "Benton", "manure_handling": "DRY", "open_lot_area_sqft": 0},
            operator_headers,
        )
    )
    assert_common_fields(patched, "operation")
    assert patched["county"] == "Benton"
    assert patched["manure_handling"] == "DRY"
    assert_quantity(patched["open_lot_area_sqft"], 0, "open_lot_area_sqft")

    # The animal-unit factor does not depend on the handling system.
    assert_operation_sizing(
        patched,
        animal_units=420.00,
        size_class="MEDIUM",
        permit_required=True,
        design_annual_manure_gallons=2700000.00,
        daily_production_gallons=7397.26,
    )
    assert patched["design_storage_days"] == 606, (
        "4,488,300.00 gallons over 7,397.26 gallons a day floors to 606 days, "
        f"got {patched['design_storage_days']}"
    )
    assert patched["version"] == before["version"] + 1, (
        "the revision must increment the operation's version by exactly 1"
    )

    listed, meta = validate_paginated(
        client.list_manure_storages(REVIEWER_HEADERS, params={"operation_id": operation_id})
    )
    assert meta["total_count"] == 1
    structure = listed[0]
    assert structure["id"] == storage_id
    assert structure["days_of_storage_available"] == 606, (
        "the structure's own day count must be rewritten in the same request, "
        f"got {structure['days_of_storage_available']}"
    )
    # Geometry-derived capacities are untouched by a herd patch.
    assert_storage_capacities(
        structure, design=5385960.00, reserve=897660.00, operating=4488300.00
    )
    assert_storage_balance(
        structure, intake=0, precipitation=0, outflow=0, current=0, committed=0,
        available=4488300.00, days=606,
    )


def test_nutrient_summary_defaults_to_design_basis_and_the_clock_year():
    """With no query parameters the summary reports the logical clock's calendar
    year on the design basis, so a year rollover empties every recorded figure
    while the design figures stand — and the January clock swings the seasonal
    denominator behind design_storage_days.

    PRD: "It accepts an optional `basis` selector, which is either `DESIGN_BASIS` or `RECORDS_BASIS` and defaults to `DESIGN_BASIS`, and an optional `year`, which defaults to the calendar year of the logical clock."
    PRD: "That seasonal factor is 1.35 when the structure is an `EARTHEN_LAGOON` or a `STACKING_PAD` and the logical clock's UTC month is November, December, January, February or March — the months in which neither type can be emptied and both keep catching precipitation — and 1.0 in every other case; a `CONCRETE_TANK` never carries the seasonal factor."
    Design: Corner/endpoints/nutrient_summary_defaults_to_design_basis_and_the_clock_year
    """
    ctx = setup_ready_operation()
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]

    event = record_application(
        operation_id,
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-07-20T00:00:00Z",
        gallons_applied=300000,
        acres_treated=30,
    )
    assert_quantity(event["n_applied_lbs"], 4680.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 3000.00, "p2o5_applied_lbs")

    checkpoints = set_clock("2027-01-05T00:00:00Z")
    assert checkpoints["permits_expired_count"] == 0, (
        "coverage effective 2026-01-01 runs to 2031-01-01, so nothing expires"
    )
    assert checkpoints["storages_recomputed_count"] == 1, (
        "the single lagoon is recomputed for the January seasonal factor"
    )

    defaulted = validate_success(
        client.get_operation_nutrient_summary(operation_id, operator_headers)
    )
    # The defaulted year is 2027, so 2026's records contribute nothing.
    assert_quantity(
        defaulted["recorded_land_applied_gallons"], 0.00, "recorded_land_applied_gallons"
    )
    assert_quantity(
        defaulted["recorded_transferred_gallons"], 0.00, "recorded_transferred_gallons"
    )
    assert_quantity(
        defaulted["recorded_annual_manure_gallons"],
        0.00,
        "recorded_annual_manure_gallons",
    )
    assert_quantity(defaulted["total_n_applied_lbs"], 0.00, "total_n_applied_lbs")
    assert_quantity(defaulted["total_p2o5_applied_lbs"], 0.00, "total_p2o5_applied_lbs")
    # The design basis ignores every record ever filed.
    assert_quantity(
        defaulted["design_annual_manure_gallons"],
        3374298.00,
        "design_annual_manure_gallons",
    )
    assert defaulted["design_storage_days"] == 359, (
        "a January clock applies the 1.35 winter factor to the lagoon, giving "
        "12,480.2775 gallons a day and 359 whole days, got "
        f"{defaulted['design_storage_days']}"
    )
    assert defaulted["compliance_posture"] == "OPEN"

    stated = validate_success(
        client.get_operation_nutrient_summary(
            operation_id, operator_headers, params={"year": 2026}
        )
    )
    assert_quantity(
        stated["recorded_land_applied_gallons"],
        300000.00,
        "recorded_land_applied_gallons",
    )
    assert_quantity(
        stated["recorded_transferred_gallons"], 0.00, "recorded_transferred_gallons"
    )
    assert_quantity(
        stated["recorded_annual_manure_gallons"],
        300000.00,
        "recorded_annual_manure_gallons",
    )
    assert_quantity(stated["total_n_applied_lbs"], 4680.00, "total_n_applied_lbs")
    assert_quantity(stated["total_p2o5_applied_lbs"], 3000.00, "total_p2o5_applied_lbs")

    stored_event = validate_success(
        client.get_application_event(event["id"], operator_headers)
    )
    assert stored_event["event_status"] == "RECORDED"

    operation = validate_success(client.get_operation(operation_id, operator_headers))
    assert_quantity(
        operation["recorded_annual_manure_gallons"],
        0.00,
        "operation.recorded_annual_manure_gallons",
    )


def test_completing_a_renewal_rolls_coverage_into_a_fresh_five_year_term():
    """An on-time renewal inside the window owes exactly the net fee, and
    completion re-dates the whole permit: effective_on advances to the old
    expiration, the new expiration is five years later and both renewal dates
    are recomputed from it.

    PRD: "Initiation stamps `renewal_submitted_at` from the logical clock and sets `is_late_renewal` to true exactly when `renewal_submitted_at` is strictly later than `renewal_due_on`."
    PRD: "`late_surcharge_amount` is `net_fee` multiplied by 0.25, rounded half up to 2 decimal places, when `is_late_renewal` is true; it is exactly 0.00 when `is_late_renewal` is false."
    PRD: "Completion advances `effective_on` to what was previously `expiration_on`, sets a new `expiration_on` 5 years after that new `effective_on`, and recomputes `renewal_window_opens_on` and `renewal_due_on` from the new `expiration_on` using the same 180-day and 90-day offsets."
    Design: Corner/endpoints/completing_a_renewal_rolls_coverage_into_a_fresh_five_year_term
    """
    ctx = setup_scenario(stage="APPROVED")
    permit_id = ctx["permit"]["id"]
    operator_headers = ctx["operator_headers"]

    covered = ctx["permit"]
    _same_instant(covered["expiration_on"], "2031-01-01T00:00:00Z", "expiration_on")
    _same_instant(
        covered["renewal_window_opens_on"],
        "2030-07-05T00:00:00Z",
        "renewal_window_opens_on",
    )
    _same_instant(covered["renewal_due_on"], "2030-10-03T00:00:00Z", "renewal_due_on")

    checkpoints = set_clock("2030-08-01T00:00:00Z")
    assert checkpoints["permits_expired_count"] == 0, (
        "2030-08-01 is before the 2031-01-01 expiration"
    )

    pending = validate_success(
        client.initiate_permit_renewal(permit_id, operator_headers)
    )
    assert pending["coverage_status"] == "RENEWAL_PENDING"
    _same_instant(
        pending["renewal_submitted_at"], "2030-08-01T00:00:00Z", "renewal_submitted_at"
    )
    assert pending["is_late_renewal"] is False, (
        "2030-08-01 is earlier than the 2030-10-03 due date"
    )
    # MEDIUM base 400 plus 420.00 animal units at 0.45 each.
    assert_quantity(pending["gross_fee"], 589.00, "gross_fee")
    assert_quantity(
        pending["conservation_discount_pct"], 0.05, "conservation_discount_pct"
    )
    assert_quantity(
        pending["conservation_discount_amount"], 29.45, "conservation_discount_amount"
    )
    assert_quantity(pending["net_fee"], 559.55, "net_fee")
    assert_quantity(pending["late_surcharge_amount"], 0.00, "late_surcharge_amount")
    assert_quantity(pending["total_due"], 559.55, "total_due")

    renewed = validate_success(
        client.complete_permit_renewal(permit_id, REVIEWER_HEADERS)
    )
    assert renewed["coverage_status"] == "COVERED"
    _same_instant(renewed["effective_on"], "2031-01-01T00:00:00Z", "effective_on")
    _same_instant(renewed["expiration_on"], "2036-01-01T00:00:00Z", "expiration_on")
    _same_instant(
        renewed["renewal_window_opens_on"],
        "2035-07-05T00:00:00Z",
        "renewal_window_opens_on",
    )
    _same_instant(renewed["renewal_due_on"], "2035-10-03T00:00:00Z", "renewal_due_on")
    # The compliance dimension is never written by a coverage transition.
    assert renewed["compliance_status"] == "IN_GOOD_STANDING"

    plan = validate_success(client.get_nutrient_plan(ctx["plan"]["id"], operator_headers))
    assert plan["plan_status"] == "APPROVED"


def test_transfer_links_operation_storage_and_hauler_and_is_findable_from_each():
    """Two transfers drawn on one lagoon through two haulers are retrievable by
    either foreign key, carry total rather than plant-available nitrogen, and
    stack their commitments on the same structure.

    PRD: "Because the receiving party makes its own availability assumption, a transfer reports **total** nitrogen rather than plant-available nitrogen: `recipient_n_lbs` is `gallons_transferred` divided by 1,000, multiplied by the manure nitrogen concentration for the operation's animal group — 24 pounds per thousand gallons for dairy, 32 for beef, 40 for swine, 60 for layer — rounded half up to 2 decimal places, with no availability factor applied at all."
    PRD: "The transfer is written with `transfer_status` of `INITIATED` and `recipient_ack_signed_at` null, and `gallons_transferred` is added to the source structure's `committed_outflow_gallons`, after which `available_capacity_gallons` and `days_of_storage_available` are recomputed."
    PRD: "Haulers themselves are registered by a `ComplianceAdmin` with a `business_name`, a state `license_number`, and a `license_expires_on` instant at which the licence lapses; `certified_applicator`, recording whether the hauler holds a certified applicator endorsement, defaults to false."
    Design: Corner/endpoints/transfer_links_operation_storage_and_hauler_and_is_findable_from_each
    """
    ctx = setup_scenario(stage="COVERED", intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    hauler_a = register_hauler(
        business_name="Prairie Pumping",
        license_number="HL-7781",
        license_expires_on="2027-06-30T00:00:00Z",
        certified_applicator=True,
    )
    # Registered without the optional endorsement flag, so its default applies.
    hauler_b = validate_success(
        client.create_hauler(
            {
                "business_name": "Cedar Valley Custom",
                "license_number": "HL-9042",
                "license_expires_on": "2028-03-31T00:00:00Z",
            },
            ADMIN_HEADERS,
        ),
        201,
    )

    transfer_a = initiate_transfer(
        operation_id,
        storage_id,
        hauler_a["id"],
        operator_headers,
        recipient_name="Vogel Row Crops",
        recipient_address="1180 County Road E, Linn",
        transferred_on="2026-07-28T00:00:00Z",
        gallons_transferred=200000,
    )
    transfer_b = initiate_transfer(
        operation_id,
        storage_id,
        hauler_b["id"],
        operator_headers,
        recipient_name="Kettle Ridge Farms",
        recipient_address="4402 190th Street, Benton",
        transferred_on="2026-07-29T00:00:00Z",
        gallons_transferred=300000,
    )

    assert_quantity(transfer_a["recipient_n_lbs"], 4800.00, "a.recipient_n_lbs")
    assert_quantity(transfer_a["recipient_p2o5_lbs"], 2000.00, "a.recipient_p2o5_lbs")
    assert_quantity(transfer_b["recipient_n_lbs"], 7200.00, "b.recipient_n_lbs")
    assert_quantity(transfer_b["recipient_p2o5_lbs"], 3000.00, "b.recipient_p2o5_lbs")
    for label, transfer in (("a", transfer_a), ("b", transfer_b)):
        assert transfer["transfer_status"] == "INITIATED", label
        assert transfer["recipient_ack_signed_at"] is None, label

    by_hauler, hauler_meta = validate_paginated(
        client.list_manure_transfers(
            REVIEWER_HEADERS, params={"hauler_id": hauler_a["id"]}
        )
    )
    assert hauler_meta["total_count"] == 1
    assert len(by_hauler) == 1
    assert by_hauler[0]["id"] == transfer_a["id"]
    assert_quantity(by_hauler[0]["recipient_n_lbs"], 4800.00, "filtered n")

    by_storage, storage_meta = validate_paginated(
        client.list_manure_transfers(
            REVIEWER_HEADERS,
            params={"storage_id": storage_id, "transfer_status": "INITIATED"},
        )
    )
    assert storage_meta["total_count"] == 2
    assert storage_meta["has_more"] is False
    assert len(by_storage) == 2
    assert_quantity(
        by_storage[0]["gallons_transferred"], 200000.00, "first row gallons"
    )

    structure = validate_success(client.get_manure_storage(storage_id, operator_headers))
    assert_storage_balance(
        structure,
        intake=1000000.00,
        outflow=0.00,
        current=1000000.00,
        committed=500000.00,
        available=2988300.00,
        days=323,
    )

    read_hauler = validate_success(
        client.get_hauler(hauler_b["id"], make_hauler_headers(hauler_b["id"]))
    )
    assert read_hauler["hauler_status"] == "ACTIVE"
    assert read_hauler["certified_applicator"] is False


def test_patching_a_plan_is_allowed_only_while_it_is_still_editable():
    """The same plan edit is accepted while the plan is DRAFT and refused once
    the planner has certified it, leaving the certified content intact.

    PRD: "A plan in `REVISION_REQUIRED` returns to `DRAFT` when a `CertifiedPlanner` revises it, which is also the only way to edit `plan_year`, `allowed_application_methods` or `winter_application_allowed` after creation."
    PRD: "Revision is admissible while the plan is in `DRAFT` or `REVISION_REQUIRED`, sets `plan_status` to `DRAFT`, and clears both `certifying_planner_user_id` and `certified_at` — a revised plan must be certified afresh."
    PRD: "Certification stamps `certifying_planner_user_id` with the acting planner's `X-User-ID` and `certified_at` with the logical clock."
    Design: Corner/endpoints/patching_a_plan_is_allowed_only_while_it_is_still_editable
    """
    ctx = setup_scenario(stage="BUDGET", plan={"allowed_application_methods": ["INJECTION"]})
    plan_id = ctx["plan"]["id"]
    budget_id = ctx["budget"]["id"]

    patched = validate_success(
        client.update_nutrient_plan(
            plan_id,
            {
                "allowed_application_methods": ["INJECTION", "INCORPORATED_24H"],
                "winter_application_allowed": True,
            },
            PLANNER_HEADERS,
        )
    )
    assert patched["plan_status"] == "DRAFT"
    assert patched["allowed_application_methods"] == ["INJECTION", "INCORPORATED_24H"]
    assert patched["winter_application_allowed"] is True
    assert patched["certifying_planner_user_id"] is None
    assert patched["certified_at"] is None

    certified = validate_success(client.certify_nutrient_plan(plan_id, PLANNER_HEADERS))
    assert certified["plan_status"] == "CERTIFIED"
    assert certified["certifying_planner_user_id"] == "planner-1"
    _same_instant(certified["certified_at"], "2026-08-01T00:00:00Z", "certified_at")

    validate_error(
        client.update_nutrient_plan(plan_id, {"plan_year": 2027}, PLANNER_HEADERS),
        ApiErrorId.ERR_PLAN_STATE_INVALID.value,
    )

    unchanged = validate_success(
        client.get_nutrient_plan(plan_id, ctx["operator_headers"])
    )
    assert unchanged["plan_year"] == 2026
    assert unchanged["plan_status"] == "CERTIFIED"
    assert unchanged["allowed_application_methods"] == ["INJECTION", "INCORPORATED_24H"]

    # Only plan approval activates a budget; certification does not.
    budget = validate_success(
        client.get_field_budget(budget_id, ctx["operator_headers"])
    )
    assert budget["budget_status"] == "LOCKED"
