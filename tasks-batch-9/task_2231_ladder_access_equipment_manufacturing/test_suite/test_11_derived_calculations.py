"""Derived numbers: risk-score input sets, exposure bases, conformance rounding,
audit escalation, safety-factor adders and the ordered load-test verdict."""

from test_helpers import (
    add_joint_samples,
    announce_recall,
    api_client,
    create_campaign,
    create_draft_revision,
    create_joint_sample_payload,
    create_load_test_payload,
    create_product,
    create_product_payload,
    create_test_bench,
    dispose_lot,
    draft_recall,
    get_campaign_data,
    get_incident_data,
    get_listing_record_data,
    get_lot_data,
    get_product_data,
    open_lot,
    plan_audit_campaign,
    quarantine_lot,
    report_incident,
    reserve_bench,
    resolve_investigation_payload,
    run_audit_campaign,
    setup_frozen_product,
    setup_incident_under_investigation,
    setup_released_lot,
    start_campaign,
    start_lot_production,
    validate_success,
)
from test_helpers import TEST_USERS

ENGINEER = TEST_USERS["design_engineer_headers"]
TECHNICIAN = TEST_USERS["test_lab_technician_headers"]
SUPERVISOR = TEST_USERS["production_supervisor_headers"]
DIRECTOR = TEST_USERS["safety_director_headers"]


def test_risk_scores_ignore_reported_and_not_substantiated_incidents():
    """PRD §3.8: "Both read exactly the same input set: the model's field
    incidents whose `status` is `UNDER_INVESTIGATION`, `ROOT_CAUSE_IDENTIFIED`,
    `CAPA_OPENED`, or `CLOSED`. Incidents in `REPORTED` or `NOT_SUBSTANTIATED` are
    excluded from both."
    PRD §3.8: "A filed incident begins at `status` `REPORTED` with
    `requires_capa` false, `incident_points` null, and `finding`, `root_cause_code`,
    and `closed_at` all null. A `REPORTED` incident contributes nothing to either
    risk-score variant."

    Design: Corner/calculations/risk_score_excludes_reported_and_not_substantiated_incidents
    """
    product = create_product()
    reported = report_incident(
        product["id"], incident_type="RAIL_FRACTURE", injury_severity="HOSPITALIZATION"
    )
    light = setup_incident_under_investigation(
        product["id"], incident_type="SLIP_FALL", injury_severity="MINOR"
    )
    fatal = setup_incident_under_investigation(
        product["id"], incident_type="RAIL_FRACTURE", injury_severity="FATALITY"
    )
    # MINOR weight 4 times SLIP_FALL weight 1.5, and FATALITY weight 30 times
    # RAIL_FRACTURE weight 3.0.
    assert float(light["incident_points"]) == 6.00
    assert float(fatal["incident_points"]) == 90.00
    assert float(get_product_data(product["id"])["risk_score_gross"]) == 96.00

    resolved = validate_success(
        api_client.resolve_investigation(
            fatal["id"],
            resolve_investigation_payload("NOT_SUBSTANTIATED", None),
            DIRECTOR,
        )
    )

    assert resolved["status"] == "NOT_SUBSTANTIATED"
    assert resolved["finding"] == "NOT_SUBSTANTIATED"
    assert resolved["requires_capa"] is False

    still_reported = get_incident_data(reported["id"])
    assert still_reported["status"] == "REPORTED"
    assert still_reported["incident_points"] is None

    reread = get_product_data(product["id"])
    assert float(reread["risk_score_gross"]) == 6.00
    assert float(reread["risk_score_mitigated"]) == 6.00


def test_recall_exposure_ignores_a_scrapped_lot_on_both_bases():
    """PRD §3.9: "It is every production lot whose `product_id` is the recalled
    model, whose pinned `design_revision_id` is a member of
    `affected_revision_ids`, whose `status` is `RELEASED` or `QUARANTINED`, and
    whose `released_at` is not null. Lots in `SCRAPPED`, `OPEN`, or `IN_PROCESS`
    are excluded from both figures."
    PRD §3.6: "Because a scrapped lot never shipped in the eyes of the recall
    accounting, it leaves every recall exposure basis described in §3.9."

    Design: Corner/calculations/recall_exposure_excludes_scrapped_lot_from_both_bases
    """
    ctx, shipped = setup_released_lot(produced_units=400)
    doomed = open_lot(ctx["product"], ctx["revision"]["id"])
    doomed = start_lot_production(doomed["id"], 300)
    add_joint_samples(doomed["id"], [472.50, 472.50, 472.50, 472.50])
    validate_success(api_client.release_production_lot(doomed["id"], SUPERVISOR))
    quarantine_lot(doomed["id"], "JOINT_INTEGRITY")
    scrapped = dispose_lot(doomed["id"], "SCRAP", DIRECTOR)
    assert scrapped["status"] == "SCRAPPED"
    assert scrapped["units_scrapped"] == 300

    recall = draft_recall(ctx["product"]["id"], [ctx["revision"]["id"]])
    announced = announce_recall(recall["id"])

    assert announced["status"] == "ANNOUNCED"
    assert announced["exposure_units_shipped_basis"] == 400, (
        "only the released lot's units are in commerce"
    )
    assert announced["exposure_units_registered_basis"] == 0
    assert float(announced["notification_coverage_pct"]) == 0.00
    assert announced["units_remedied"] == 0
    assert announced["units_outstanding"] == 0

    product = get_product_data(ctx["product"]["id"])
    assert product["market_status"] == "RECALLED"
    assert product["design_status"] == "DESIGN_OBSOLETE"
    assert get_listing_record_data(ctx["listing_record"]["id"])["status"] == "WITHDRAWN"
    assert get_lot_data(shipped["id"])["status"] == "RELEASED"


def test_conformance_index_rounds_the_mean_of_whole_percent_margins_half_up():
    """PRD §3.6: "The lot's `conformance_index` is then the arithmetic mean of
    those whole-percent integers across every sample on the lot, rounded half up to
    two decimal places. Averaging the unrounded margins and rounding once at the end
    is a different and non-conforming result."
    PRD §3.6: "After each insert the lot's `joint_sample_count` is recounted as
    the number of sample rows and `joint_fail_count` as the number whose `result` is
    `FAIL`."

    Design: Corner/calculations/conformance_index_rounds_half_up_to_two_decimals
    """
    ctx = setup_frozen_product(material="FIBERGLASS_PULTRUSION")
    assert float(ctx["product"]["required_pull_force_lbf"]) == 450.00
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    earlier = add_joint_samples(lot["id"], [470.00, 462.00])
    assert int(earlier[0]["margin_pct"]) == 4
    assert int(earlier[1]["margin_pct"]) == 3

    third = validate_success(
        api_client.create_joint_sample(
            lot["id"], create_joint_sample_payload(3, 455.00), TECHNICIAN
        ),
        201,
    )

    assert int(third["margin_pct"]) == 1
    assert third["result"] == "PASS"

    reread = get_lot_data(lot["id"])
    assert reread["joint_sample_count"] == 3
    assert reread["joint_fail_count"] == 0
    # Mean of the whole percents 4, 3 and 1 is 2.666..., which rounds half up.
    assert float(reread["conformance_index"]) == 2.67


def test_joint_sample_margin_rounds_half_up_at_an_exact_half_percent():
    """PRD §3.6: "Each sample's `margin_pct` is the measured `pull_force_lbf`
    minus its snapshot requirement, divided by that snapshot requirement, expressed
    as a percentage, rounded half up to a whole number."
    PRD §2.4: "each joint sample's already-rounded whole-percent `margin_pct` is
    what enters the lot average — the lot average is never taken over unrounded
    margins."

    Design: Corner/calculations/joint_sample_margin_rounds_half_up_at_exact_half_percent
    """
    ctx = setup_frozen_product(material="FIBERGLASS_PULTRUSION")
    lot = open_lot(ctx["product"], ctx["revision"]["id"])
    lot = start_lot_production(lot["id"], 400)
    # 11.25 lbf over the 450.00 snapshot is exactly 2.5 percent.
    first = add_joint_samples(lot["id"], [461.25])[0]
    assert int(first["margin_pct"]) == 3

    # 15.75 lbf over the same snapshot is exactly 3.5 percent.
    second = validate_success(
        api_client.create_joint_sample(
            lot["id"], create_joint_sample_payload(2, 465.75), TECHNICIAN
        ),
        201,
    )

    assert int(second["margin_pct"]) == 4
    assert first["result"] == "PASS"
    assert second["result"] == "PASS"

    reread = get_lot_data(lot["id"])
    assert reread["joint_sample_count"] == 2
    assert float(reread["conformance_index"]) == 3.50


def test_audit_prior_is_the_latest_sample_window_not_the_latest_created_row():
    """PRD §3.5: "Order the survivors by `sample_window_end` descending, breaking
    ties by `created_at` descending, and take the first."
    PRD §3.5: "Otherwise it is `TIER_1` when `prior_failure_rate_pct` is 20.00 or
    less, `TIER_2` when it is 40.00 or less, and `TIER_3` above that."
    PRD §3.5: "it is the base audit sample of 5 units plus the tier adder —
    nothing for `TIER_0`, three more units for `TIER_1`, eight more for `TIER_2`,
    and fifteen more for `TIER_3`."

    Design: Corner/calculations/audit_prior_selected_by_sample_window_end_not_created_at
    """
    ctx, lot = setup_released_lot(produced_units=400)

    later_window = run_audit_campaign(
        ctx, lot["id"], "2026-08-16T00:00:00Z", "2026-08-20T00:00:00Z", failing_tests=1
    )
    assert later_window["status"] == "FAILED"
    assert later_window["audit_sample_size"] == 5
    assert later_window["failed_test_count"] == 1

    earlier_window = run_audit_campaign(
        ctx, lot["id"], "2026-08-05T00:00:00Z", "2026-08-09T00:00:00Z"
    )
    assert earlier_window["status"] == "PASSED"
    assert earlier_window["audit_sample_size"] == 8
    assert earlier_window["failed_test_count"] == 0

    planned = plan_audit_campaign(
        ctx, lot["id"], "2026-08-21T00:00:00Z", "2026-08-25T00:00:00Z"
    )

    assert planned["status"] == "PLANNED"
    # One failure out of the five-unit sample of the window that ended latest.
    assert float(planned["prior_failure_rate_pct"]) == 20.00
    assert planned["escalation_tier"] == "TIER_1"
    assert planned["audit_sample_size"] == 8


def test_articulated_family_bonus_applies_without_the_fiberglass_bonus():
    """PRD §3.1: "Add the product-family bonus: nothing for `STEP_LADDER`,
    `EXTENSION_LADDER`, or `PLATFORM_LADDER`, one tenth for `ARTICULATED_LADDER`,
    and one quarter for `MOBILE_SCAFFOLD_TOWER`. Add five hundredths when
    `material` is `FIBERGLASS_PULTRUSION`, and nothing for the other two
    materials."
    PRD §3.1: "Subtract the twelve-foot baseline from `working_length_ft`, divide
    the remainder by four feet, and round the quotient **up** to the next whole
    number; if the result is negative, use zero."

    Design: Corner/calculations/articulated_ladder_type_bonus_applied_without_material_bonus
    """
    payload = create_product_payload(
        product_type="ARTICULATED_LADDER",
        material="ALUMINUM_EXTRUSION",
        duty_rating="TYPE_I",
        working_length_ft=20.0,
    )

    product = validate_success(api_client.create_product(payload, ENGINEER), 201)

    assert float(product["rated_load_lb"]) == 250
    # Base 4.00 plus two length steps of 0.15 plus the articulated tenth.
    assert float(product["safety_factor"]) == 4.40
    assert float(product["required_test_load_lb"]) == 1100.00
    assert float(product["required_pull_force_lbf"]) == 375.00
    assert float(product["max_allowed_deflection_in"]) == 1.333


def test_permanent_set_is_the_third_criterion_in_the_ordered_verdict():
    """PRD §3.4: "The verdict is derived, never supplied, and three criteria are
    evaluated in a fixed order with the **first** failure recorded as the
    `failure_reason_code`"
    PRD §3.4: "3. Otherwise, if `permanent_set_in` is greater than twenty
    thousandths of an inch, the `outcome` is `FAIL` with `failure_reason_code`
    `PERMANENT_SET_EXCEEDED`."
    PRD §3.4: "After each insert, the campaign's `load_test_count` is recounted
    as the number of load test rows on the campaign regardless of outcome, and
    `failed_test_count` as the number whose `outcome` is `FAIL`."

    Design: Corner/calculations/load_test_permanent_set_exceeded_is_the_third_ordered_failure_code
    """
    product = create_product(material="FIBERGLASS_PULTRUSION")
    assert float(product["required_test_load_lb"]) == 1350.00
    assert float(product["max_allowed_deflection_in"]) == 1.600
    revision = create_draft_revision(product["id"])
    bench = create_test_bench()
    campaign = create_campaign(product["id"], revision["id"], "DESIGN_QUALIFICATION")
    reservation = reserve_bench(bench["id"], campaign["id"])
    start_campaign(campaign["id"], reservation["id"])

    recorded = validate_success(
        api_client.create_load_test(
            campaign["id"],
            create_load_test_payload(
                test_code="STATIC_VERTICAL",
                applied_load_lb=1400.00,
                measured_deflection_in=1.500,
                permanent_set_in=0.021,
            ),
            TECHNICIAN,
        ),
        201,
    )

    assert recorded["outcome"] == "FAIL"
    assert recorded["failure_reason_code"] == "PERMANENT_SET_EXCEEDED", (
        "the load clears 1350.00 and the deflection clears 1.600, so neither "
        "earlier criterion may fire"
    )

    reread = get_campaign_data(campaign["id"])
    assert reread["load_test_count"] == 1
    assert reread["failed_test_count"] == 1
    assert reread["status"] == "IN_PROGRESS"
