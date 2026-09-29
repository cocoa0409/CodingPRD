"""Branches of the arithmetic that only fire on particular shapes of input.

Non-cattle species floors, the eligibility filter and flooring of the pooled
measurement, the empty priced set, the wholesale weighting branch, the degenerate
discrepancy denominator, and the empty source set.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import test_users as u
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_determination,
    assert_discrepancy_rates,
    assert_price_statistics,
    assert_registration_number_format,
    assert_report_masked,
    assert_submission_totals,
)
from test_helpers.types import (
    AggregationState,
    AuditCaseStatus,
    AuditFinding,
    BasisVariant,
    DeterminationOutcome,
    DisclosureState,
    PlantStatus,
    ProductClass,
    PublicationState,
    RegistrationStatus,
    ReportCategory,
    SaleType,
    Species,
    SubmissionStatus,
    SuppressionReason,
    WeightingVariant,
)

SWINE_HISTORY = {"2021": 99999, "2022": 99999, "2023": 99999, "2024": 99999, "2025": 99999}
LAMB_HISTORY = {"2021": 40000, "2022": 40000, "2023": 40000, "2024": 40000, "2025": 40000}

OPERATING_HISTORY = {
    "2021": 60000,
    "2022": 60000,
    "2023": 60000,
    "2024": 60000,
    "2025": 60001,
}
IDLE_HISTORY = {"2021": 20000, "2022": 20000, "2023": 20000, "2024": 20000, "2025": 20000}
CLOSED_HISTORY = {
    "2021": 200000,
    "2022": 200000,
    "2023": 200000,
    "2024": 200000,
    "2025": 200000,
}


def test_01_the_species_floor_is_looked_up_and_not_hard_coded_to_cattle(api):
    """A swine firm and a lamb firm, each one head off its own floor.

    Swine measuring 99,999 against a 100,000-head floor is exempt while lamb
    measuring 40,000 against a 35,000-head floor is mandatory, so neither was
    measured against the cattle floor of 125,000 -- and the number the lamb firm
    takes on activation is the program's first, because the exempt swine file
    never consumed one.

    PRD §3.2: "The threshold itself is copied onto the record as `threshold_head`
    at determination time, read from the species schedule by the firm's
    `species_scope`: 125,000 head for `CATTLE`, 100,000 head for `SWINE` and
    35,000 head for `LAMB`."

    Design: Corner/calculations/species_threshold_constants_swine_and_lamb
    """
    swine = fx.obligated_firm(
        api,
        legal_name="Swine Co",
        plant_code="EST-501",
        species=Species.SWINE.value,
        species_scope=Species.SWINE.value,
        annual_head_history=dict(SWINE_HISTORY),
        activate=False,
    )
    assert_determination(
        swine["registration"],
        k.THRESHOLD_HEAD_SWINE - 1,
        k.THRESHOLD_HEAD_SWINE,
        DeterminationOutcome.EXEMPT.value,
    )

    lamb = fx.obligated_firm(
        api,
        legal_name="Lamb Co",
        plant_code="EST-601",
        species=Species.LAMB.value,
        species_scope=Species.LAMB.value,
        annual_head_history=dict(LAMB_HISTORY),
        activate=False,
    )
    assert_determination(
        lamb["registration"],
        40000,
        k.THRESHOLD_HEAD_LAMB,
        DeterminationOutcome.MANDATORY.value,
    )

    activated = validate_success(
        api.activate_registration(lamb["registration"]["id"], u.PROGRAM_ADMIN)
    )
    assert activated["status"] == RegistrationStatus.ACTIVE.value, activated
    assert_registration_number_format(activated["registration_number"], 2026, 1)


def test_02_only_operating_plants_are_pooled_and_the_quotient_is_floored(api):
    """A closed plant's 1,000,000 head are invisible until it reopens.

    The active and idle plants pool to 400,001 head, which floors to 80,000 rather
    than rounding to 80,001, leaving the firm exempt -- and once the closed plant
    is reopened the very same redetermination pools 1,400,001 head and makes the
    firm mandatory, so eligibility is re-evaluated rather than cached.

    PRD §3.2: "Under `FIVE_YEAR_AVERAGE`, the platform pools every participating
    plant's head count for every one of the five lookback years into a single
    total, divides that one pooled total by five, and discards any fractional
    remainder".

    Design: Corner/calculations/closed_plants_excluded_and_pooled_average_floored
    """
    firm = fx.firm_with_plants(
        api,
        [
            {"plant_code": "EST-301", "annual_head_history": dict(OPERATING_HISTORY)},
            {
                "plant_code": "EST-302",
                "status": PlantStatus.IDLE.value,
                "annual_head_history": dict(IDLE_HISTORY),
            },
            {
                "plant_code": "EST-303",
                "status": PlantStatus.CLOSED.value,
                "annual_head_history": dict(CLOSED_HISTORY),
            },
        ],
        legal_name="Delta Beef",
        activate=False,
    )
    registration_id = firm["registration"]["id"]
    entity_id = firm["entity"]["id"]
    closed_plant = firm["plants"][2]

    assert_determination(
        firm["registration"], 80000, 125000, DeterminationOutcome.EXEMPT.value
    )

    appealed = validate_success(
        api.appeal_registration(
            registration_id,
            f.appeal_payload(
                appeal_reason="idle and reopened plants must be counted"
            ),
            u.reporter_agent(entity_id),
        )
    )
    assert appealed["status"] == RegistrationStatus.UNDER_APPEAL.value, appealed
    assert appealed["appeal_count"] == 1, appealed

    reopened = validate_success(
        api.update_plant(
            closed_plant["id"],
            f.plant_patch_payload(status=PlantStatus.ACTIVE.value),
            u.PROGRAM_ADMIN,
        )
    )
    assert reopened["status"] == PlantStatus.ACTIVE.value, reopened

    redetermined = validate_success(
        api.redetermine_registration(
            registration_id,
            f.redetermine_payload(basis_variant=BasisVariant.FIVE_YEAR_AVERAGE.value),
            u.PROGRAM_ADMIN,
        )
    )
    assert redetermined["status"] == RegistrationStatus.DETERMINED.value, redetermined
    assert_determination(
        redetermined, 280000, 125000, DeterminationOutcome.MANDATORY.value
    )

    assert (
        fx.read_plant(api, firm["plants"][0]["id"])["annual_head_history"]
        == OPERATING_HISTORY
    )
    assert (
        fx.read_plant(api, firm["plants"][1]["id"])["annual_head_history"]
        == IDLE_HISTORY
    )


def test_03_a_packer_owned_only_filing_prices_nothing_and_cannot_be_released(api):
    """Volume without price: the one purchase type carrying no price signal.

    The packer-owned transfer still books its 400 head and its full value on the
    filing and still counts toward the window's volume and reporter share, but the
    priced set it feeds is empty, so all three price statistics compute to null,
    the confidentiality review stops at its very first rung, and release is
    refused even at exactly the release instant.

    PRD §3.6: "When the priced subset is empty — a live-animal window carrying
    nothing but `PACKER_OWNED` lines, or a `NEGOTIATED_ONLY` report over a window
    with no negotiated trade — then `weighted_average_price_per_cwt`,
    `price_low_per_cwt` and `price_high_per_cwt` are all null, while the volume
    figures and `reporter_count` stand."

    Design: Corner/calculations/packer_owned_only_filing_yields_null_price_statistics
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_relaxed_window(api)
    filing = fx.accepted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.packer_owned_transaction_payload(
                head_count=400,
                avg_net_price_per_cwt=288.00,
                avg_carcass_weight_cwt=9.00,
            )
        ],
    )
    assert_submission_totals(
        filing,
        reported_head=400,
        reported_cwt=3600.00,
        reported_value_dollars=1036800.00,
    )

    report = fx.create_report(api, window["id"])
    computed = validate_success(
        api.compute_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert computed["aggregation_state"] == AggregationState.COMPUTED.value, computed
    assert_price_statistics(computed, None, None, None)
    assert computed["total_head"] == 400, computed
    assert computed["reporter_count"] == 1, computed
    assert computed["max_reporter_share_pct"] == 100.00, computed
    assert computed["source_submission_count"] == 1, computed

    withheld = validate_success(
        api.disclosure_review_market_report(report["id"], u.MARKET_ANALYST)
    )
    assert_report_masked(
        withheld,
        SuppressionReason.NO_ELIGIBLE_DATA.value,
        reporter_count=1,
        max_reporter_share_pct=100.00,
    )

    fx.lock_window(api, window["id"])
    fx.set_clock(api, k.WINDOW_PUBLICATION_RELEASE)

    validate_error(
        api.publish_market_report(report["id"], u.MARKET_ANALYST),
        ApiErrorId.ERR_CONFIDENTIALITY_SUPPRESSION_REQUIRED.value,
        409,
    )
    assert (
        fx.read_report(api, report["id"])["publication_state"]
        == PublicationState.UNPUBLISHED.value
    )


def test_04_the_wholesale_branch_weights_loads_and_pounds_instead_of_head(api):
    """Two deliberately non-proportional lots, so the variants cannot agree.

    On the wholesale side the volume axis is pounds and head is not reported at
    all, and the two weighting variants read the same two lots differently: loads
    as weights give 288.20 per cwt while pounds as weights give 288.00, off the
    same 285.50 low and 290.00 high.

    PRD §3.6: "Each lot's price is its `price_per_cwt`; under `HEAD_WEIGHTED` its
    weight is its `load_count`, and under `WEIGHT_WEIGHTED` its weight is its
    `total_pounds`."

    Design: Corner/calculations/boxed_beef_wholesale_aggregation_distinct_from_live_categories
    """
    scene = fx.boxed_beef_firm_and_window(api)
    entity_id = scene["firm"]["entity"]["id"]
    window_id = scene["window"]["id"]

    filing = fx.draft_filing(
        api, entity_id, scene["firm"]["plant"]["id"], window_id
    )
    choice = fx.add_wholesale_lot(
        api,
        entity_id,
        filing["id"],
        f.wholesale_lot_payload(
            product_class=ProductClass.BOXED_BEEF_CHOICE_CUTOUT.value,
            sale_type=SaleType.NEGOTIATED.value,
            load_count=10,
            total_pounds=400000.00,
            price_per_cwt=285.50,
        ),
    )
    select = fx.add_wholesale_lot(
        api,
        entity_id,
        filing["id"],
        f.wholesale_lot_payload(
            product_class=ProductClass.BOXED_BEEF_SELECT_CUTOUT.value,
            sale_type=SaleType.DELIVERED.value,
            load_count=15,
            total_pounds=500000.00,
            price_per_cwt=290.00,
        ),
    )
    assert choice["lot_value_dollars"] == 1142000.00, choice
    assert select["lot_value_dollars"] == 1450000.00, select

    validate_success(api.submit_submission(filing["id"], u.reporter_agent(entity_id)))
    booked = fx.accept_filing(api, filing["id"], review_note="clean")
    assert_submission_totals(
        booked,
        reported_head=0,
        reported_cwt=0.00,
        reported_value_dollars=2592000.00,
        reported_pounds=900000.00,
        reported_load_count=25,
    )

    by_loads = fx.create_report(
        api,
        window_id,
        category=ReportCategory.BOXED_BEEF_CUTOUT.value,
        weighting_variant=WeightingVariant.HEAD_WEIGHTED.value,
    )
    by_pounds = fx.create_report(
        api,
        window_id,
        category=ReportCategory.BOXED_BEEF_CUTOUT.value,
        weighting_variant=WeightingVariant.WEIGHT_WEIGHTED.value,
    )

    load_weighted = validate_success(
        api.compute_market_report(by_loads["id"], u.MARKET_ANALYST)
    )
    pound_weighted = validate_success(
        api.compute_market_report(by_pounds["id"], u.MARKET_ANALYST)
    )

    assert_price_statistics(load_weighted, 288.20, 285.50, 290.00)
    assert_price_statistics(pound_weighted, 288.00, 285.50, 290.00)
    for report in (load_weighted, pound_weighted):
        assert report["total_head"] is None, report
        assert report["total_pounds"] == 900000.00, report
        assert report["reporter_count"] == 1, report
        assert report["max_reporter_share_pct"] == 100.00, report
        assert report["source_submission_count"] == 1, report

    cleared = validate_success(
        api.disclosure_review_market_report(by_loads["id"], u.MARKET_ANALYST)
    )
    assert cleared["disclosure_state"] == DisclosureState.CLEARED.value, cleared
    assert cleared["suppression_reason"] is None, cleared


def test_05_a_zero_verified_denominator_is_a_stated_rule_not_a_division(api):
    """Nothing verified against something reported, and against nothing reported.

    Verified zero against 100 head and 224,000 dollars is a total deviation at
    100.00 percent on both axes and drives the enforcement branch, while verified
    zero against a wholesale filing that legitimately booked no head at all is
    0.00 percent -- and that branch reconciles the case and cascades nothing.

    PRD §3.7: "`head_discrepancy_rate_pct` is 0.00 when `verified_head` and
    `reported_head` are both zero; it is 100.00 when `verified_head` is zero but
    `reported_head` is not, since a nonzero report against nothing verified is a
    total deviation; and otherwise it is 100 multiplied by the absolute difference
    between `verified_head` and `reported_head`, divided by `verified_head`,
    rounded half up to 2 decimals."

    Design: Corner/calculations/zero_verified_denominator_audit_edge_cases
    """
    scene = fx.boxed_beef_firm_and_window(api)
    entity_id = scene["firm"]["entity"]["id"]
    plant_id = scene["firm"]["plant"]["id"]

    live_window = fx.create_relaxed_window(api)
    live_filing = fx.accepted_filing(
        api,
        entity_id,
        plant_id,
        live_window["id"],
        lines=[
            f.transaction_payload(
                head_count=100,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    assert_submission_totals(
        live_filing, reported_head=100, reported_value_dollars=224000.00
    )

    wholesale_filing = fx.draft_filing(
        api, entity_id, plant_id, scene["window"]["id"]
    )
    fx.add_wholesale_lot(api, entity_id, wholesale_filing["id"])
    validate_success(
        api.submit_submission(wholesale_filing["id"], u.reporter_agent(entity_id))
    )
    booked = fx.accept_filing(api, wholesale_filing["id"], review_note="clean")
    assert_submission_totals(
        booked, reported_head=0, reported_value_dollars=1142000.00
    )

    live_case = fx.fieldwork_case(api, live_filing["id"])
    settled_live = fx.finalize_case(api, live_case["id"], 0, 0.00)
    assert_discrepancy_rates(
        settled_live, 100.00, 100.00, AuditFinding.MATERIAL_BOTH.value
    )
    assert settled_live["status"] == AuditCaseStatus.DISCREPANCY.value, settled_live
    assert settled_live["finalized_by_user_id"] == "auditor-2", settled_live
    assert (
        fx.read_submission(api, live_filing["id"])["status"]
        == SubmissionStatus.UNDER_CORRECTION.value
    )

    wholesale_case = fx.fieldwork_case(api, wholesale_filing["id"])
    settled_wholesale = fx.finalize_case(api, wholesale_case["id"], 0, 1142000.00)
    assert_discrepancy_rates(
        settled_wholesale, 0.00, 0.00, AuditFinding.IMMATERIAL.value
    )
    assert (
        settled_wholesale["status"] == AuditCaseStatus.RECONCILED.value
    ), settled_wholesale
    assert (
        fx.read_submission(api, wholesale_filing["id"])["status"]
        == SubmissionStatus.ACCEPTED.value
    )


def test_06_aggregation_is_refused_until_a_filing_is_actually_accepted(api):
    """The source set is keyed on review state, not on the filing's existence.

    With the window's only filing still awaiting review the aggregation is refused
    outright and writes nothing -- the report is still pending with no computed
    timestamp -- and the identical call after acceptance succeeds over that one
    filing.

    PRD §3.6: "Either way the window must actually have data: if not one
    submission of the window is in `ACCEPTED` status, the attempt is rejected with
    `ERR_NO_ELIGIBLE_DATA`."

    Design: Corner/calculations/compute_with_no_accepted_filing_rejected
    """
    firm = fx.obligated_firm(api, legal_name="Alpha Packing")
    window = fx.create_relaxed_window(api)
    filing = fx.submitted_filing(
        api,
        firm["entity"]["id"],
        firm["plant"]["id"],
        window["id"],
        lines=[
            f.transaction_payload(
                head_count=200,
                avg_net_price_per_cwt=280.00,
                avg_carcass_weight_cwt=8.00,
            )
        ],
    )
    report = fx.create_report(api, window["id"])

    validate_error(
        api.compute_market_report(report["id"], u.MARKET_ANALYST),
        ApiErrorId.ERR_NO_ELIGIBLE_DATA.value,
        409,
    )
    untouched = fx.read_report(api, report["id"])
    assert untouched["aggregation_state"] == AggregationState.PENDING.value, untouched
    assert untouched["computed_at"] is None, untouched

    fx.accept_filing(api, filing["id"], review_note="clean")

    computed = get_success_data(
        api.compute_market_report(report["id"], u.MARKET_ANALYST),
        expected_status=200,
    )
    assert computed["aggregation_state"] == AggregationState.COMPUTED.value, computed
    assert computed["weighted_average_price_per_cwt"] == 280.00, computed
    assert computed["total_head"] == 200, computed
    assert computed["source_submission_count"] == 1, computed
