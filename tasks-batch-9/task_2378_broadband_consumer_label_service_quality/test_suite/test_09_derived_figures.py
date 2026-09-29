"""Derived figures on labels, disclosures, notices and attestations.

Every monetary and temporal expectation in this module is the figure the PRD's
own pinned formulas produce on the reference fixture: a fibre plan advertising
300/140 Mbps with an introductory charge of 4999 cents for six months, a
post-promotional charge of 7999 cents, five fee lines, and the six reference
samples of one measurement window.
"""

from typing import Any, Dict, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_account_ledger,
    assert_evidence_sample_total,
    assert_label_dimensions,
    assert_margins,
    assert_pinned_typical_figures,
    assert_posture,
)
from test_helpers.constants import (
    ALL_HOUR_P20_POOLED_COUNT,
    ALL_HOUR_P20_TYPICAL_DOWNLOAD,
    ALL_HOUR_P20_TYPICAL_LATENCY,
    ALL_HOUR_P20_TYPICAL_UPLOAD,
    PEAK_HOUR_MEDIAN_POOLED_COUNT,
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
    PEAK_HOUR_MEDIAN_UPLOAD_MARGIN,
    REFERENCE_NOW,
)
from test_helpers.factories import (
    build_attestation_payload,
    build_disclosure_payload,
    build_plan_amendment_payload,
    build_plan_change_notice_payload,
    build_sample,
    build_service_plan_payload,
    build_uphold_payload,
)
from test_helpers.fixtures import (
    certify_attestation,
    create_attestation,
    create_investigated_complaint,
    create_measurement_probe,
    create_published_label,
    create_published_methodology,
    create_reference_plan,
    create_subscriber_account,
    current_plan_version,
    draft_label,
    invalidate_test_run,
    read_attestation,
    read_label,
    read_service_plan,
    read_subscriber_account,
    record_test_run,
    set_clock,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    RETAIL_AGENT_HEADERS,
    make_subscriber_headers,
)
from test_helpers.types import (
    AttestationStatus,
    ComplaintSeverity,
    CreditBasis,
    DisclosureChannel,
    LabelPosture,
    MetricVariant,
    NoticeType,
    PricingPhase,
    PublicationState,
    SubstantiationStatus,
    SubscriptionState,
)

# ---------------------------------------------------------------------------
# Pre-computed figures of the reference plan
# ---------------------------------------------------------------------------

MONTHLY_TOTAL_INTRO_CENTS = 6766
MONTHLY_TOTAL_POST_PROMO_CENTS = 10628
NET_MONTHLY_INTRO_CENTS = 3766
NET_MONTHLY_POST_PROMO_CENTS = 7628
FIRST_YEAR_PROMO_WEIGHTED_CENTS = 78264
FIRST_YEAR_POST_PROMO_CENTS = 101436

#: The post-promotional base charge the repricing amendment moves the plan to.
REPRICED_MONTHLY_PRICE_CENTS = 8999
REPRICED_MONTHLY_TOTAL_POST_PROMO_CENTS = 11681
REPRICED_NET_MONTHLY_POST_PROMO_CENTS = 8681
REPRICED_FIRST_YEAR_PROMO_WEIGHTED_CENTS = 84582
REPRICED_FIRST_YEAR_POST_PROMO_CENTS = 114072

#: The early termination fee disclosed on a notice at nought, one and six whole
#: elapsed thirty-day months of a six-month introductory term.
ETF_AT_MONTH_ZERO_CENTS = 12000
ETF_AT_MONTH_ONE_CENTS = 10000
ETF_AFTER_INTRO_TERM_CENTS = 0

#: Remediation credits on the introductory net charge of 3766 cents.
SEVERE_PRORATA_CREDIT_CENTS = 942
FLOOR_LIFTED_CREDIT_CENTS = 500
THREE_CREDIT_BALANCE_CENTS = 2384

#: Second methodology pool: two samples of 100/40/90 and 104/44/92 Mbps/ms.
FOREIGN_POOL_SAMPLE_COUNT = 2
FOREIGN_POOL_TYPICAL_DOWNLOAD = 102.00
FOREIGN_POOL_TYPICAL_UPLOAD = 42.00
FOREIGN_POOL_TYPICAL_LATENCY = 92
FOREIGN_POOL_DOWNLOAD_MARGIN = 0.3400
FOREIGN_POOL_UPLOAD_MARGIN = 0.3000

#: The variant-comparison plan advertises 280/140 Mbps, charges 7999 cents with
#: no introductory price and carries no fee lines.
VARIANT_ADVERTISED_DOWNLOAD_MBPS = 280
VARIANT_MONTHLY_TOTAL_CENTS = 7999
VARIANT_FIRST_YEAR_CENTS = 95988
VARIANT_PEAK_DOWNLOAD_MARGIN = 0.8571
VARIANT_P20_DOWNLOAD_MARGIN = 0.8500
VARIANT_P20_UPLOAD_MARGIN = 0.8000

# Clock positions and window instants used by the chains below.
SUCCESSOR_EFFECTIVE_FROM = "2026-10-01T00:00:00Z"
CLOCK_AT_ONE_ELAPSED_MONTH = "2026-10-01T00:00:00Z"
CLOCK_AFTER_INTRO_TERM = "2027-03-01T00:00:00Z"
SECOND_NOTICE_EFFECTIVE_DATE = "2026-11-01T00:00:00Z"
THIRD_NOTICE_EFFECTIVE_DATE = "2027-04-01T00:00:00Z"
SERVICE_START_AT_SIX_ELAPSED_MONTHS = "2026-03-05T00:00:00Z"
SERVICE_START_AT_FIVE_ELAPSED_MONTHS = "2026-03-06T00:00:00Z"

FOREIGN_WINDOW_START = "2026-08-11T00:00:00Z"
FOREIGN_WINDOW_END = "2026-08-12T00:00:00Z"
FOREIGN_SAMPLES = [
    build_sample("2026-08-11T19:10:00Z", 100, 40, 90),
    build_sample("2026-08-11T20:10:00Z", 104, 44, 92),
]
WITHDRAWN_WINDOW_START = "2026-08-13T00:00:00Z"
WITHDRAWN_WINDOW_END = "2026-08-14T00:00:00Z"
WITHDRAWN_SAMPLES = [
    build_sample("2026-08-13T19:10:00Z", 12, 4, 300),
    build_sample("2026-08-13T20:10:00Z", 14, 5, 310),
]


# ---------------------------------------------------------------------------
# Setup chains unique to this module
# ---------------------------------------------------------------------------


def _build_two_methodology_world() -> Dict[str, Any]:
    """The reference plan measured under two published methodologies, with one
    run of the first methodology later withdrawn from the evidence pool."""
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    doc_a = create_published_methodology()
    probe = create_measurement_probe()
    run_a = record_test_run(probe["id"], plan["id"], doc_a["id"])

    doc_b = create_published_methodology(
        version_label="v2.0",
        methodology_url="https://isp.example/methodology/v2.0",
    )
    run_b = record_test_run(
        probe["id"],
        plan["id"],
        doc_b["id"],
        window_start=FOREIGN_WINDOW_START,
        window_end=FOREIGN_WINDOW_END,
        samples=FOREIGN_SAMPLES,
    )
    run_c = record_test_run(
        probe["id"],
        plan["id"],
        doc_a["id"],
        window_start=WITHDRAWN_WINDOW_START,
        window_end=WITHDRAWN_WINDOW_END,
        samples=WITHDRAWN_SAMPLES,
    )
    invalidate_test_run(
        run_c["id"], reason="Probe misconfiguration during the third window"
    )
    return {
        "plan": plan,
        "doc_a": doc_a,
        "doc_b": doc_b,
        "probe": probe,
        "run_a": run_a,
        "run_b": run_b,
        "run_c": run_c,
    }


def _build_variant_comparison_world() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """A plan advertising 280/140 Mbps with no introductory price and no fee
    lines, measured once under a published methodology."""
    set_clock(REFERENCE_NOW)
    payload = build_service_plan_payload(
        display_name="Fiber 280",
        advertised_download_mbps=VARIANT_ADVERTISED_DOWNLOAD_MBPS,
        advertised_upload_mbps=140,
        monthly_price_cents=VARIANT_MONTHLY_TOTAL_CENTS,
        early_termination_fee_cents=0,
        required_locales=["en-US"],
        discount_program_eligible=False,
    )
    for defaulted in (
        "intro_price_cents",
        "intro_term_months",
        "data_allowance_gb",
        "overage_rate_cents_per_gb",
        "etf_proration_policy",
    ):
        payload.pop(defaulted, None)
    plan = get_success_data(
        api_client.create_service_plan(payload, COMPLIANCE_OFFICER_HEADERS)
    )
    doc = create_published_methodology()
    probe = create_measurement_probe(panel_size=60, max_concurrent_windows=1)
    record_test_run(probe["id"], plan["id"], doc["id"])
    return plan, doc


# ---------------------------------------------------------------------------
# Pricing phase and the disclosed net charge
# ---------------------------------------------------------------------------


def test_disclosed_net_charge_follows_each_account_pricing_phase(
    reference_environment,
):
    """One published label discloses two different net charges, because the
    figure copied onto the disclosure is chosen by the account's pricing phase,
    and the thirty-day month boundary is exclusive.

    PRD: "The disclosure then records `label_version_id` as the selected label,
    `disclosed_label_version_seq` as that label's `version_seq`,
    `disclosed_net_monthly_cents` as the phase-appropriate figure — the label's
    `net_monthly_intro_cents` when the account's `pricing_phase` is `INTRO` and
    its `net_monthly_post_promo_cents` otherwise, copied as whole cents with no
    re-rounding — and `disclosed_by_user_id` as the acting `X-User-ID`."

    Design: Corner/calculations/pricing_phase_selects_the_disclosed_net_charge
    """
    env = reference_environment

    # The reference account starts service on the day the clock reads, so no
    # whole thirty-day month has elapsed for it yet.
    account_at_zero_months = env.account
    account_at_six_months = create_subscriber_account(
        env.plan_id, service_start_date=SERVICE_START_AT_SIX_ELAPSED_MONTHS
    )
    account_at_five_months = create_subscriber_account(
        env.plan_id, service_start_date=SERVICE_START_AT_FIVE_ELAPSED_MONTHS
    )

    disclosure_at_zero = validate_success(
        api_client.record_label_disclosure(
            account_at_zero_months["id"],
            build_disclosure_payload(
                channel=DisclosureChannel.POINT_OF_SALE.value
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    disclosure_at_six = validate_success(
        api_client.record_label_disclosure(
            account_at_six_months["id"],
            build_disclosure_payload(
                channel=DisclosureChannel.ACCOUNT_PORTAL.value
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    disclosure_at_five = validate_success(
        api_client.record_label_disclosure(
            account_at_five_months["id"],
            build_disclosure_payload(
                channel=DisclosureChannel.ACCOUNT_PORTAL.value
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )

    assert (
        read_subscriber_account(account_at_zero_months["id"])["pricing_phase"]
        == PricingPhase.INTRO.value
    ), "no elapsed month is still inside the six-month promotional term"
    assert (
        read_subscriber_account(account_at_six_months["id"])["pricing_phase"]
        == PricingPhase.POST_PROMO.value
    ), "exactly six elapsed thirty-day months is already post-promotional"
    assert (
        read_subscriber_account(account_at_five_months["id"])["pricing_phase"]
        == PricingPhase.INTRO.value
    ), "five elapsed thirty-day months is one day inside the promotional term"

    assert (
        disclosure_at_zero["disclosed_net_monthly_cents"]
        == NET_MONTHLY_INTRO_CENTS
    )
    assert (
        disclosure_at_five["disclosed_net_monthly_cents"]
        == NET_MONTHLY_INTRO_CENTS
    )
    assert (
        disclosure_at_six["disclosed_net_monthly_cents"]
        == NET_MONTHLY_POST_PROMO_CENTS
    ), "the post-promotional net is disclosed from the very same label row"

    for disclosure in (disclosure_at_zero, disclosure_at_five, disclosure_at_six):
        assert disclosure["label_version_id"] == env.label_id
        assert disclosure["disclosed_label_version_seq"] == 1


# ---------------------------------------------------------------------------
# The decaying early termination fee on a notice
# ---------------------------------------------------------------------------


def test_etf_disclosure_decays_by_whole_elapsed_months(reference_environment):
    """Three successive notices on one account disclose 12000, 10000 and 0
    cents, because the prorated fee is a step function of whole thirty-day
    months elapsed on the plan being left.

    PRD: "Under `PRORATED_MONTHLY` it decays with the introductory term: take
    the whole number of thirty-day months elapsed between the account's
    `service_start_date` and the logical clock (the elapsed seconds divided by
    2,592,000, rounded down), subtract that from the source plan's
    `intro_term_months` and treat any negative result as zero to obtain the
    remaining months, then multiply the source plan's
    `early_termination_fee_cents` by those remaining months, divide by the
    source plan's `intro_term_months` — or by 1 when that term is 0 — and round
    half up to a whole number of cents."

    Design: Corner/calculations/etf_disclosure_decays_by_whole_elapsed_months
    """
    env = reference_environment
    account_id = env.account_id

    first_notice = validate_success(
        api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                account_id,
                env.plan_id,
                SUCCESSOR_EFFECTIVE_FROM,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="First notice at month 0",
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert first_notice["etf_disclosed_cents"] == ETF_AT_MONTH_ZERO_CENTS
    assert first_notice["notice_days"] == 30

    validate_success(
        api_client.acknowledge_plan_change_notice(
            first_notice["id"], make_subscriber_headers(account_id)
        )
    )
    set_clock(CLOCK_AT_ONE_ELAPSED_MONTH)
    validate_success(
        api_client.effect_plan_change_notice(first_notice["id"], RETAIL_AGENT_HEADERS)
    )
    assert (
        read_subscriber_account(account_id)["pricing_phase"]
        == PricingPhase.INTRO.value
    ), "one elapsed thirty-day month is still inside the six-month term"

    second_notice = validate_success(
        api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                account_id,
                env.plan_id,
                SECOND_NOTICE_EFFECTIVE_DATE,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="Second notice at month 1",
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert second_notice["etf_disclosed_cents"] == ETF_AT_MONTH_ONE_CENTS
    assert second_notice["notice_days"] == 31

    validate_success(
        api_client.acknowledge_plan_change_notice(
            second_notice["id"], make_subscriber_headers(account_id)
        )
    )
    set_clock(CLOCK_AFTER_INTRO_TERM)
    validate_success(
        api_client.effect_plan_change_notice(second_notice["id"], RETAIL_AGENT_HEADERS)
    )
    assert (
        read_subscriber_account(account_id)["pricing_phase"]
        == PricingPhase.POST_PROMO.value
    ), "six elapsed thirty-day months has left the promotional term"

    third_notice = validate_success(
        api_client.create_plan_change_notice(
            build_plan_change_notice_payload(
                account_id,
                env.plan_id,
                THIRD_NOTICE_EFFECTIVE_DATE,
                notice_type=NoticeType.PRICE_INCREASE.value,
                reason="Third notice after the promotional period",
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert third_notice["etf_disclosed_cents"] == ETF_AFTER_INTRO_TERM_CENTS, (
        "the fee reaches zero once the elapsed month count equals the term"
    )
    assert third_notice["notice_days"] == 31

    for notice in (first_notice, second_notice, third_notice):
        assert notice["source_plan_id"] == env.plan_id, (
            "the fee is owed on the plan being left"
        )
        assert (
            notice["disclosed_net_monthly_cents"] == NET_MONTHLY_POST_PROMO_CENTS
        )

    assert (
        read_subscriber_account(account_id)["subscription_state"]
        == SubscriptionState.PENDING_CHANGE.value
    ), "the account stays pending while the third notice is outstanding"


# ---------------------------------------------------------------------------
# The attestation's evidence pool
# ---------------------------------------------------------------------------


def test_attestation_pool_admits_only_included_runs_of_its_own_methodology():
    """Two attestations over the same plan see disjoint pools: the run recorded
    under the other methodology and the withdrawn run are both left out of
    `included_run_ids` and `pooled_sample_count`.

    PRD: "The evidence pool is assembled from the plan's measurement runs whose
    `status` is `INCLUDED` and whose `methodology_doc_id` equals the
    attestation's own, taken in ascending `created_at` order."

    Design: Corner/calculations/attestation_pool_excludes_invalidated_and_foreign_runs
    """
    world = _build_two_methodology_world()
    plan_id = world["plan"]["id"]

    own_methodology_attestation = validate_success(
        api_client.create_performance_attestation(
            build_attestation_payload(
                plan_id,
                world["doc_a"]["id"],
                current_plan_version(plan_id),
                metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
            ),
            NETWORK_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )
    assert own_methodology_attestation["included_run_ids"] == [world["run_a"]["id"]], (
        "the foreign-methodology run and the invalidated run are both excluded"
    )
    assert (
        own_methodology_attestation["pooled_sample_count"]
        == PEAK_HOUR_MEDIAN_POOLED_COUNT
    )
    assert_pinned_typical_figures(
        own_methodology_attestation,
        PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    )

    foreign_methodology_attestation = validate_success(
        api_client.create_performance_attestation(
            build_attestation_payload(
                plan_id,
                world["doc_b"]["id"],
                current_plan_version(plan_id),
                metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
            ),
            NETWORK_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )
    assert foreign_methodology_attestation["included_run_ids"] == [
        world["run_b"]["id"]
    ]
    assert (
        foreign_methodology_attestation["pooled_sample_count"]
        == FOREIGN_POOL_SAMPLE_COUNT
    )
    assert_pinned_typical_figures(
        foreign_methodology_attestation,
        FOREIGN_POOL_TYPICAL_DOWNLOAD,
        FOREIGN_POOL_TYPICAL_UPLOAD,
        FOREIGN_POOL_TYPICAL_LATENCY,
    )
    assert_margins(
        foreign_methodology_attestation,
        FOREIGN_POOL_DOWNLOAD_MARGIN,
        FOREIGN_POOL_UPLOAD_MARGIN,
    )

    assert_evidence_sample_total(
        read_service_plan(plan_id),
        PEAK_HOUR_MEDIAN_POOLED_COUNT + 2 + FOREIGN_POOL_SAMPLE_COUNT,
    )


def test_attestation_is_rejected_once_its_own_run_pool_is_empty():
    """Withdrawing the only run of one methodology empties that attestation's
    pool while the plan still holds evidence recorded under the other
    methodology.

    PRD: "If the concatenation is empty, the create is rejected with
    `ERR_NO_ELIGIBLE_TEST_RUNS`."

    Design: Corner/calculations/attestation_pool_excludes_invalidated_and_foreign_runs
    """
    world = _build_two_methodology_world()
    plan_id = world["plan"]["id"]
    invalidate_test_run(
        world["run_a"]["id"], reason="Window withdrawn from the evidence pool"
    )

    response = api_client.create_performance_attestation(
        build_attestation_payload(
            plan_id,
            world["doc_a"]["id"],
            current_plan_version(plan_id),
            metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
        ),
        NETWORK_ENGINEER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_NO_ELIGIBLE_TEST_RUNS.value)

    assert_evidence_sample_total(
        read_service_plan(plan_id), FOREIGN_POOL_SAMPLE_COUNT
    )


# ---------------------------------------------------------------------------
# The posture freeze threshold
# ---------------------------------------------------------------------------


def test_posture_freezes_at_the_third_upheld_complaint(reference_environment):
    """The first two upheld complaints leave the plan open; the third freezes
    it, in the very resolve that issues the third credit.

    PRD: "One further consequence follows from hop 1 without being part of the
    declared four-hop chain: the plan the account is subscribed to has its
    `upheld_complaint_count` incremented by one, its disclosure posture
    recomputed — which drops it to `FROZEN` once the count reaches three — and
    its `version` incremented."

    Design: Corner/calculations/posture_freezes_at_the_third_upheld_complaint
    """
    env = reference_environment
    severe_complaint = create_investigated_complaint(
        env.account_id,
        env.label_id,
        service_observed_date="2026-09-02T12:00:00Z",
        narrative="Evening shortfall, week one",
        measured_download_mbps=120,
    )
    moderate_complaint = create_investigated_complaint(
        env.account_id,
        env.label_id,
        service_observed_date="2026-09-03T12:00:00Z",
        narrative="Evening shortfall, week two",
        measured_download_mbps=180,
    )
    third_complaint = create_investigated_complaint(
        env.account_id,
        env.label_id,
        service_observed_date="2026-09-04T12:00:00Z",
        narrative="Evening shortfall, week three",
        measured_download_mbps=120,
    )

    first_resolution = validate_success(
        api_client.resolve_complaint(
            severe_complaint["id"],
            build_uphold_payload(
                credit_basis=CreditBasis.PRORATA_DAYS.value,
                resolution_note="Shortfall confirmed",
            ),
            COMPLAINT_ANALYST_HEADERS,
        )
    )
    assert round(float(first_resolution["shortfall_ratio"]), 4) == 0.5000
    assert first_resolution["severity"] == ComplaintSeverity.SEVERE.value
    assert (
        first_resolution["remediation_credit_cents"] == SEVERE_PRORATA_CREDIT_CENTS
    )
    plan_after_first = validate_success(
        api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert plan_after_first["upheld_complaint_count"] == 1
    assert_posture(plan_after_first, LabelPosture.OPEN.value)

    second_resolution = validate_success(
        api_client.resolve_complaint(
            moderate_complaint["id"],
            build_uphold_payload(
                credit_basis=CreditBasis.PRORATA_DAYS.value,
                resolution_note="Moderate shortfall confirmed",
            ),
            COMPLAINT_ANALYST_HEADERS,
        )
    )
    assert round(float(second_resolution["shortfall_ratio"]), 4) == 0.2500
    assert second_resolution["severity"] == ComplaintSeverity.MODERATE.value
    assert (
        second_resolution["remediation_credit_cents"] == FLOOR_LIFTED_CREDIT_CENTS
    ), "the raw prorated figure is lifted to the credit floor"
    plan_after_second = validate_success(
        api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert plan_after_second["upheld_complaint_count"] == 2
    assert_posture(plan_after_second, LabelPosture.OPEN.value)

    third_resolution = validate_success(
        api_client.resolve_complaint(
            third_complaint["id"],
            build_uphold_payload(
                credit_basis=CreditBasis.PRORATA_DAYS.value,
                resolution_note="Third shortfall confirmed",
            ),
            COMPLAINT_ANALYST_HEADERS,
        )
    )
    assert (
        third_resolution["remediation_credit_cents"] == SEVERE_PRORATA_CREDIT_CENTS
    )
    plan_after_third = validate_success(
        api_client.get_service_plan(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert plan_after_third["upheld_complaint_count"] == 3
    assert_posture(plan_after_third, LabelPosture.FROZEN.value)

    assert_account_ledger(
        read_subscriber_account(env.account_id), THREE_CREDIT_BALANCE_CENTS, 3
    )

    blocked = api_client.record_label_disclosure(
        env.account_id,
        build_disclosure_payload(channel=DisclosureChannel.ACCOUNT_PORTAL.value),
        RETAIL_AGENT_HEADERS,
    )
    validate_error(blocked, ApiErrorId.ERR_PLAN_POSTURE_FROZEN.value)


# ---------------------------------------------------------------------------
# Repricing a plan
# ---------------------------------------------------------------------------


def test_repricing_recomputes_the_draft_label_and_pins_the_published_one(
    reference_environment,
):
    """A repricing amendment moves the draft label to the new base charge while
    the published label keeps every figure it disclosed and is flagged as
    drifted instead.

    PRD: "Whether or not a price moved, the amendment recomputes the
    itemisation, the discount benefit and both first-year totals for every label
    of the plan whose `publication_state` is `DRAFT`; published, archived and
    withdrawn labels keep the figures pinned on them."

    Design: Corner/calculations/price_change_recomputes_draft_labels_only
    """
    env = reference_environment
    successor_draft = draft_label(
        env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM
    )

    amended_plan = validate_success(
        api_client.amend_service_plan(
            env.plan_id,
            build_plan_amendment_payload(
                change_justification="Annual repricing of the post-promotional rate",
                monthly_price_cents=REPRICED_MONTHLY_PRICE_CENTS,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert amended_plan["monthly_price_cents"] == REPRICED_MONTHLY_PRICE_CENTS
    assert amended_plan["price_disclosure_drift"] is True
    assert amended_plan["last_price_change_at"] is not None
    assert amended_plan["last_price_change_at"].startswith("2026-09-01T00:00:00"), (
        "last_price_change_at is the logical clock at the amendment"
    )
    assert_posture(amended_plan, LabelPosture.RESTRICTED.value)

    recomputed = read_label(successor_draft["id"])
    assert (
        recomputed["monthly_total_post_promo_cents"]
        == REPRICED_MONTHLY_TOTAL_POST_PROMO_CENTS
    )
    assert (
        recomputed["net_monthly_post_promo_cents"]
        == REPRICED_NET_MONTHLY_POST_PROMO_CENTS
    )
    assert recomputed["monthly_total_intro_cents"] == MONTHLY_TOTAL_INTRO_CENTS, (
        "the introductory base charge did not move"
    )
    assert recomputed["net_monthly_intro_cents"] == NET_MONTHLY_INTRO_CENTS
    assert (
        recomputed["first_year_total_promo_weighted_cents"]
        == REPRICED_FIRST_YEAR_PROMO_WEIGHTED_CENTS
    )
    assert (
        recomputed["first_year_total_post_promo_cents"]
        == REPRICED_FIRST_YEAR_POST_PROMO_CENTS
    )

    pinned = read_label(env.label_id)
    assert_label_dimensions(
        pinned,
        PublicationState.PUBLISHED.value,
        SubstantiationStatus.SUBSTANTIATED.value,
    )
    assert (
        pinned["monthly_total_post_promo_cents"] == MONTHLY_TOTAL_POST_PROMO_CENTS
    )
    assert pinned["net_monthly_post_promo_cents"] == NET_MONTHLY_POST_PROMO_CENTS
    assert (
        pinned["first_year_total_promo_weighted_cents"]
        == FIRST_YEAR_PROMO_WEIGHTED_CENTS
    )
    assert (
        pinned["first_year_total_post_promo_cents"] == FIRST_YEAR_POST_PROMO_CENTS
    )
    assert pinned["price_disclosure_drift"] is True, (
        "the published label is flagged as stale rather than silently rewritten"
    )


def test_repricing_restricts_point_of_sale_but_not_the_account_portal(
    reference_environment,
):
    """The restricted posture a repricing produces closes the point-of-sale
    channel while the account portal keeps disclosing the pinned figure.

    PRD: "`RESTRICTED` blocks a disclosure whose `channel` is `POINT_OF_SALE`
    and a notice whose `notice_type` is `PRICE_INCREASE`, answering
    `ERR_PLAN_POSTURE_RESTRICTED` (409), while `ACCOUNT_PORTAL` disclosures and
    `PLAN_CHANGE` notices continue to be accepted."

    Design: Corner/calculations/price_change_recomputes_draft_labels_only
    """
    env = reference_environment
    draft_label(env.plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM)
    validate_success(
        api_client.amend_service_plan(
            env.plan_id,
            build_plan_amendment_payload(
                change_justification="Annual repricing of the post-promotional rate",
                monthly_price_cents=REPRICED_MONTHLY_PRICE_CENTS,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    blocked = api_client.record_label_disclosure(
        env.account_id,
        build_disclosure_payload(channel=DisclosureChannel.POINT_OF_SALE.value),
        RETAIL_AGENT_HEADERS,
    )
    validate_error(blocked, ApiErrorId.ERR_PLAN_POSTURE_RESTRICTED.value)

    permitted = validate_success(
        api_client.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(
                channel=DisclosureChannel.ACCOUNT_PORTAL.value
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert permitted["label_version_id"] == env.label_id
    assert permitted["disclosed_net_monthly_cents"] == NET_MONTHLY_INTRO_CENTS


# ---------------------------------------------------------------------------
# The metric variant a label pins
# ---------------------------------------------------------------------------


def test_label_pins_the_variant_of_its_certified_attestation():
    """Two attestations over one run pool, one per metric variant: each label
    keeps the typical figures of whichever attestation was certified when it was
    published.

    PRD: "Creating an attestation for a plan that already has a certified
    attestation is legitimate and supersedes it: the older attestation's
    `status` moves from `CERTIFIED` to `SUPERSEDED` — by invariant there is at
    most one certified attestation per plan — while any label already pinned to
    the superseded attestation keeps its pinned typical figures and its
    `substantiation_status` untouched, because a published label discloses what
    it disclosed."

    Design: Corner/calculations/label_pins_the_variant_of_its_certified_attestation
    """
    plan, methodology = _build_variant_comparison_world()
    plan_id = plan["id"]

    peak_attestation = create_attestation(
        plan_id,
        methodology["id"],
        metric_variant=MetricVariant.PEAK_HOUR_MEDIAN.value,
    )
    certify_attestation(peak_attestation["id"])
    peak_attestation = read_attestation(peak_attestation["id"])
    assert peak_attestation["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT
    assert_pinned_typical_figures(
        peak_attestation,
        PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    )
    assert_margins(
        peak_attestation,
        VARIANT_PEAK_DOWNLOAD_MARGIN,
        PEAK_HOUR_MEDIAN_UPLOAD_MARGIN,
    )
    peak_label = create_published_label(plan_id, effective_from=REFERENCE_NOW)

    p20_attestation = validate_success(
        api_client.create_performance_attestation(
            build_attestation_payload(
                plan_id,
                methodology["id"],
                current_plan_version(plan_id),
                metric_variant=MetricVariant.ALL_HOUR_P20.value,
            ),
            NETWORK_ENGINEER_HEADERS,
        ),
        expected_status=201,
    )
    assert p20_attestation["pooled_sample_count"] == ALL_HOUR_P20_POOLED_COUNT
    assert_pinned_typical_figures(
        p20_attestation,
        ALL_HOUR_P20_TYPICAL_DOWNLOAD,
        ALL_HOUR_P20_TYPICAL_UPLOAD,
        ALL_HOUR_P20_TYPICAL_LATENCY,
    )
    assert_margins(
        p20_attestation, VARIANT_P20_DOWNLOAD_MARGIN, VARIANT_P20_UPLOAD_MARGIN
    )
    assert (
        read_attestation(peak_attestation["id"])["status"]
        == AttestationStatus.SUPERSEDED.value
    ), "the second attestation supersedes the certified one"

    validate_success(
        api_client.certify_performance_attestation(
            p20_attestation["id"], COMPLIANCE_OFFICER_HEADERS
        )
    )
    p20_label = create_published_label(
        plan_id, effective_from=SUCCESSOR_EFFECTIVE_FROM
    )

    first_label = read_label(peak_label["id"])
    second_label = read_label(p20_label["id"])
    assert first_label["attestation_id"] == peak_attestation["id"]
    assert_pinned_typical_figures(
        first_label,
        PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    )
    assert second_label["attestation_id"] == p20_attestation["id"]
    assert_pinned_typical_figures(
        second_label,
        ALL_HOUR_P20_TYPICAL_DOWNLOAD,
        ALL_HOUR_P20_TYPICAL_UPLOAD,
        ALL_HOUR_P20_TYPICAL_LATENCY,
    )

    for label in (first_label, second_label):
        assert (
            label["monthly_total_post_promo_cents"] == VARIANT_MONTHLY_TOTAL_CENTS
        )
        assert label["net_monthly_post_promo_cents"] == VARIANT_MONTHLY_TOTAL_CENTS
        assert label["discount_program_applied"] is False
        assert label["monthly_total_intro_cents"] is None
        assert (
            label["first_year_total_promo_weighted_cents"] == VARIANT_FIRST_YEAR_CENTS
        )
        assert label["first_year_total_post_promo_cents"] == VARIANT_FIRST_YEAR_CENTS

    assert read_service_plan(plan_id)["active_label_version_id"] == p20_label["id"]
    assert (
        first_label["publication_state"] == PublicationState.ARCHIVED.value
    ), "the predecessor is archived rather than discarded"
    assert first_label["effective_until"] is not None
    assert first_label["effective_until"].startswith("2026-10-01T00:00:00"), (
        "the archived window is truncated to its successor's effective_from"
    )
