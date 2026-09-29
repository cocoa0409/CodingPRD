"""One test per endpoint shape: guarded write, action, refused action, read, link.

A basis revision that re-derives the whole ledger, a placed-in-service declaration
that opens the monitoring dimension, the same declaration refused too early, a
computed read that agrees with the persisted ledger, and a draft amendment that binds
three rows at once.
"""

from test_helpers import (
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    types,
    validate_error,
    validate_success,
)


def test_a_basis_revision_quoting_the_current_version_re_derives_the_ledger(api):
    """Dropping the basis below the qualified total flips the test and buys credit.

    Before the revision the 30000000 of qualified cost is short of the 60000000
    threshold, so the test reads NOT_MET. The revision quotes the project's current
    version and lowers the basis to 20000000, which the ripple carries all the way
    through: the window end is unchanged and the cost is still in period, the threshold
    follows the new basis, the test reads MET, and the schedule appears at 1200000 a
    year and 6000000 over five years, all unclaimed. The project's version advances
    exactly once.

    PRD: "A basis-and-period revision by the owning `Developer` may change `adjusted_basis_cents`, `measuring_period_start_date`, `measuring_period_months`, or any combination of them, and must carry `expected_project_version` as described in §2.8."
    PRD: "When a revision moves the window, the consequences ripple in a fixed order: `measuring_period_end_date` is recomputed, then every cost line item of the project has its `in_measuring_period` flag re-evaluated against the new half-open window, then the qualified/non-qualified segregation is recomputed, then the substantial rehabilitation test, and only then the ratable credit schedule."
    PRD: "`version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of that row; it is the value optimistic concurrency control is checked against."

    Design: Corner/endpoints/standard_crud_project_patch_with_current_version_recomputes_ledger
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    item = fixtures.add_qre_cost(
        api, cast, project["id"], 30_000_000, incurred_date="2027-05-01"
    )
    before = fixtures.read_project(api, cast, project["id"])
    assertions.assert_substantial_test(before, "NOT_MET")

    revised = validate_success(
        api.patch_project(
            project["id"],
            cast.developer_headers,
            expected_project_version=before["version"],
            adjusted_basis_cents=20_000_000,
        )
    )

    assertions.assert_fields(
        revised,
        "revised project",
        adjusted_basis_cents=20_000_000,
        measuring_period_end_date="2028-09-01",
        version=before["version"] + 1,
    )
    assertions.assert_substantial_test(revised, "MET", threshold_cents=20_000_000)
    assertions.assert_ratable_schedule(revised, 1_200_000)
    assertions.assert_ledger(
        revised,
        qre_total_final_cents=30_000_000,
        total_claimable_credit_cents=6_000_000,
        credit_unclaimed_cents=6_000_000,
    )
    assertions.assert_fields(
        get_success_data(api.get_cost_line_item(item["id"], cast.developer_headers)),
        "cost after the revision",
        in_measuring_period=True,
    )


def test_declaring_the_building_in_service_opens_the_monitoring_dimension(api):
    """The compliance dimension leaves NOT_MONITORED and certification stays put.

    The project has cleared Part 2, so the declaration is legal. It records the date,
    moves the compliance dimension into monitoring and leaves the certification
    dimension at PART2_APPROVED. With no investor admitted the standing maximum risk
    score is zero and nothing is outstanding, and the project's version advances once.

    PRD: "On success the compliance dimension moves `NOT_MONITORED → IN_SERVICE_MONITORING`, every `ADMITTED` investor interest is re-scored under the `IN_SERVICE` variant, `max_investor_risk_score` is refreshed from those scores, and the project's `version` increments. The certification dimension is not touched."
    PRD: "The project's `max_investor_risk_score` is the maximum `disqualification_risk_score` across its `ADMITTED` interests, and zero when the project has no `ADMITTED` interest at all."

    Design: Corner/endpoints/action_endpoint_place_in_service_opens_monitoring_dimension
    """
    scenario = fixtures.part2_approved_project(
        api, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    cast = scenario["cast"]
    project_id = scenario["project"]["id"]
    before = fixtures.read_project(api, cast, project_id)
    assertions.assert_project_state(before, compliance_status="NOT_MONITORED")
    fixtures.set_clock(api, "2029-01-15T00:00:00Z")

    declared = validate_success(
        api.place_in_service(
            project_id, cast.developer_headers, placed_in_service_date="2029-01-15"
        )
    )

    assertions.assert_fields(
        declared,
        "project placed in service",
        placed_in_service_date="2029-01-15",
        version=before["version"] + 1,
    )
    assertions.assert_project_state(
        declared,
        certification_status="PART2_APPROVED",
        compliance_status="IN_SERVICE_MONITORING",
    )
    assertions.assert_ledger(
        declared, max_investor_risk_score=0, recapture_balance_cents=0
    )
    assertions.assert_fields(
        get_success_data(
            api.get_part_application(scenario["part2"]["id"], cast.developer_headers)
        ),
        "part 2",
        status="APPROVED",
    )


def test_a_building_cannot_be_placed_in_service_before_part_two_clears(api):
    """Nothing has been reviewed, so the declaration is refused outright.

    The project is still at PRE_CERTIFICATION with no part application of any number,
    so the rehabilitation plan has not cleared Part 2 review. The declaration is
    refused, no date is recorded, both dimensions are where opening left them, and the
    project is still on its first version.

    PRD: "The owning `Developer` declares it by supplying `placed_in_service_date`, and the declaration is legal only once the project's certification dimension has reached `PART2_APPROVED` or `PART3_CERTIFIED` — a building cannot be placed in service before its rehabilitation plan has cleared Part 2 review — otherwise it is refused with `ERR_PROJECT_NOT_CERTIFIED`."
    PRD: "The project opens with `certification_status` at `PRE_CERTIFICATION` and `compliance_status` at `NOT_MONITORED`, with `placed_in_service_date` null, and with the whole credit ledger — `qre_total_final_cents`, `qre_total_provisional_cents`, `nonqualified_total_cents`, `classified_cost_total_cents`, `developer_fee_disallowed_cents`, `annual_credit_cents`, `total_claimable_credit_cents`, `credit_claimed_to_date_cents`, `credit_recaptured_cents`, `credit_unclaimed_cents`, `recapture_balance_cents`, `max_investor_risk_score` — at zero, with `substantial_test_status` at `NOT_MET` and `frozen_at_certification` false."

    Design: Corner/endpoints/conditional_action_place_in_service_before_part2_rejected
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )

    response = api.place_in_service(
        project["id"], cast.developer_headers, placed_in_service_date="2026-09-01"
    )

    validate_error(response, ApiErrorId.PROJECT_NOT_CERTIFIED.value, 409)
    stored = fixtures.read_project(api, cast, project["id"])
    assertions.assert_fields(
        stored,
        "project after the refused declaration",
        placed_in_service_date=None,
        version=1,
    )
    assertions.assert_project_state(
        stored,
        certification_status="PRE_CERTIFICATION",
        compliance_status="NOT_MONITORED",
    )


def test_the_computed_segregation_read_agrees_with_the_persisted_ledger(api):
    """The monitor's FINAL read reproduces the stored ledger and mutates nothing.

    One qualified 30000000 and one non-qualified 10000000 are both in period. The FINAL
    read reports exactly the three totals the project has persisted, reports no
    developer fee at all, and counts both items. The read is computed on demand, so the
    project's version is the same before and after it.

    PRD: "The segregation is available as a computed read on the project, which recomputes it on demand without mutating anything."
    PRD: "The response reports `variant_applied`, `qre_total_cents`, `hard_qre_cents`, `developer_fee_claimed_cents`, `developer_fee_allowed_cents`, `developer_fee_disallowed_cents`, `nonqualified_total_cents`, `classified_cost_total_cents`, `substantial_test_threshold_cents`, `substantial_test_status_under_variant` — the test outcome computed against the requested variant's qualified total rather than the stored `FINAL` one — plus `in_period_item_count`, the number of in-period line items, and `pending_classification_item_count`, the number of those still awaiting classification."
    PRD: "Under the `FINAL` variant, the counted qualified set is the items whose `classification` is `QRE` or `LOCKED_QRE`."

    Design: Corner/endpoints/computed_read_qre_summary_reconciles_with_persisted_project_ledger
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )
    fixtures.add_qre_cost(
        api, cast, project["id"], 30_000_000, incurred_date="2027-03-01"
    )
    fixtures.add_cost(
        api,
        cast,
        project["id"],
        category="ACQUISITION",
        amount_cents=10_000_000,
        incurred_date="2027-04-01",
        classification="NON_QRE",
    )
    before = fixtures.read_project(api, cast, project["id"])

    summary = validate_success(
        api.get_qre_summary(project["id"], fixtures.MONITOR, variant="FINAL")
    )

    assertions.assert_fields(
        summary,
        "monitor's final read",
        variant_applied="FINAL",
        qre_total_cents=30_000_000,
        nonqualified_total_cents=10_000_000,
        classified_cost_total_cents=40_000_000,
        developer_fee_claimed_cents=0,
        in_period_item_count=2,
    )
    after = fixtures.read_project(api, cast, project["id"])
    assertions.assert_ledger(
        after,
        qre_total_final_cents=summary["qre_total_cents"],
        nonqualified_total_cents=summary["nonqualified_total_cents"],
        classified_cost_total_cents=summary["classified_cost_total_cents"],
        version=before["version"],
    )


def test_a_drafted_amendment_binds_its_project_application_and_finding(api):
    """Three references are recorded on one row and nothing else moves.

    The amendment names the project, the application whose scope it alters and the
    outstanding condition it is aimed at. A masonry treatment with a 200000-cent delta
    against a CONDITION finding needs no federal concurrence, so the draft records both
    verdicts at NONE with no submission stamp. Drafting decides nothing: the finding is
    still unresolved and the application is still parked with one unresolved condition.

    PRD: "An amendment may also be aimed at an outstanding finding by supplying `addresses_finding_id`; omitting it makes the amendment a pure scope change that clears nothing."
    PRD: "The amendment begins in `DRAFT` with `shpo_decision` and `nps_decision` both `NONE` and `submitted_at` null."
    PRD: "It is true when any one of three conditions holds: the `scope_category` is `ADDITION` or `ROOF_ALTERATION`; or the magnitude of `cost_delta_cents`, ignoring its sign, is at least fifty thousand dollars' worth of cents; or the finding named by `addresses_finding_id` has `severity` of `VIOLATION`."

    Design: Corner/endpoints/cross_reference_link_amendment_binds_project_application_and_finding
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api, cast, structure_type="MASTER_LEASE", adjusted_basis_cents=60_000_000
    )
    application = fixtures.create_part_application(api, cast, project["id"], 1)
    fixtures.submit_part_application(api, cast, application["id"])
    fixtures.shpo_recommend(api, cast, application["id"])
    finding = fixtures.add_finding(
        api,
        cast,
        application["id"],
        headers=cast.nps_headers,
        standard_number=2,
        severity="CONDITION",
        description="The mortar mix must match the historic lime-rich profile.",
    )
    fixtures.nps_determine(api, cast, application["id"], determination="CONDITIONAL")

    response = api.create_amendment(
        cast.developer_headers,
        **factories.amendment_payload(
            project["id"],
            application["id"],
            scope_category="MASONRY_TREATMENT",
            change_description="Mortar mix revised to a lime-rich historic profile.",
            cost_delta_cents=200_000,
            addresses_finding_id=finding["id"],
        ),
    )

    amendment = validate_success(response, 201)
    types.assert_is_amendment(amendment)
    assertions.assert_fields(
        amendment,
        "drafted amendment",
        project_id=project["id"],
        part_application_id=application["id"],
        addresses_finding_id=finding["id"],
        status="DRAFT",
        requires_nps_concurrence=False,
        shpo_decision="NONE",
        nps_decision="NONE",
        submitted_at=None,
        version=1,
    )
    assertions.assert_fields(
        validate_success(api.get_finding(finding["id"], cast.nps_headers)),
        "addressed finding",
        resolution_state="UNRESOLVED",
    )
    assertions.assert_fields(
        get_success_data(
            api.get_part_application(application["id"], cast.developer_headers)
        ),
        "parked application",
        status="CONDITIONAL",
        unresolved_condition_count=1,
    )
