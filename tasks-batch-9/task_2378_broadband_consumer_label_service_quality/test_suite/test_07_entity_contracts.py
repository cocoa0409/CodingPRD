"""Entity contracts: creation defaults, pinned snapshots, computed and system
fields, listing, not-found resolution and the immutable disclosure row.
"""

from typing import Any, Dict, List, Tuple

import pytest

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId
from test_helpers.assertions import (
    assert_immutable_audit_event,
    assert_mutable_resource,
    assert_pinned_typical_figures,
    assert_posture,
    assert_resource_identity,
)
from test_helpers.constants import (
    DEFAULT_PAGE_LIMIT,
    DEFAULT_PAGE_OFFSET,
    PEAK_HOUR_MEDIAN_POOLED_COUNT,
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
    REFERENCE_NOW,
    REFERENCE_SAMPLES,
)
from test_helpers.factories import (
    build_complaint_payload,
    build_disclosure_payload,
    build_fixed_fee_payload,
    build_label_version_payload,
    build_methodology_document_payload,
    build_percentage_fee_payload,
    build_plan_amendment_payload,
    build_regulator_inquiry_payload,
    build_sample,
    build_service_plan_payload,
    build_subscriber_account_payload,
    build_test_run_payload,
    build_translation_payload,
)
from test_helpers.fixtures import (
    build_reference_environment,
    create_measurement_probe,
    create_methodology_document,
    create_published_methodology,
    create_reference_plan,
    create_service_plan,
    current_plan_version,
    draft_label,
    invalidate_test_run,
    read_attestation,
    read_service_plan,
    read_subscriber_account,
    read_test_run,
    record_test_run,
    set_clock,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_USER_ID,
    COMPLIANCE_OFFICER_HEADERS,
    COMPLIANCE_OFFICER_USER_ID,
    LOCALIZATION_SPECIALIST_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
    RETAIL_AGENT_USER_ID,
)
from test_helpers.types import (
    AccessibilityNeed,
    AllegationType,
    DisclosureChannel,
    EtfProrationPolicy,
    FeeLabelCategory,
    ItemizationPhase,
    MetricVariant,
    PricingPhase,
    PublicationState,
    SubscriptionState,
    SubstantiationStatus,
    Technology,
    TestRunStatus,
)

# ---------------------------------------------------------------------------
# Fixture literals shared by the chains below
# ---------------------------------------------------------------------------

#: An id of the right shape that names nothing in the store.
UNKNOWN_ID = "00000000-0000-4000-8000-0000000000ff"

#: The logical clock every chain here is positioned at, in the three-fractional
#: digit form the server writes its own timestamps in.
CLOCK_TIMESTAMP = "2026-09-01T00:00:00.000Z"
LATER_EFFECTIVE_FROM = "2026-10-01T00:00:00Z"

# The reference plan's priced face: intro base 4999 and post-promotional base
# 7999 with the five reference fee lines, a 3,000-cent discount benefit in both
# phases and a six-month introductory term.
REFERENCE_MONTHLY_TOTAL_INTRO_CENTS = 6766
REFERENCE_NET_MONTHLY_INTRO_CENTS = 3766
REFERENCE_MONTHLY_TOTAL_POST_PROMO_CENTS = 10628
REFERENCE_NET_MONTHLY_POST_PROMO_CENTS = 7628
REFERENCE_ONE_TIME_FEE_TOTAL_CENTS = 9900
REFERENCE_FIRST_YEAR_PROMO_WEIGHTED_CENTS = 78264
REFERENCE_FIRST_YEAR_POST_PROMO_CENTS = 101436
REFERENCE_ETF_DISCLOSURE_CENTS = 12000
REFERENCE_DATA_ALLOWANCE_GB = 1200
REFERENCE_OVERAGE_RATE_CENTS_PER_GB = 1000

#: The itemisation the reference fee lines produce, phase by phase.
REFERENCE_ITEMIZATION: List[Tuple[str, str, str, int]] = [
    (
        ItemizationPhase.INTRO.value,
        "EQUIP_RENTAL",
        FeeLabelCategory.MONTHLY_RECURRING.value,
        1500,
    ),
    (
        ItemizationPhase.INTRO.value,
        "REG_RECOVERY",
        FeeLabelCategory.MONTHLY_RECURRING.value,
        162,
    ),
    (
        ItemizationPhase.INTRO.value,
        "STATE_USF",
        FeeLabelCategory.GOVERNMENT_TAX.value,
        105,
    ),
    (
        ItemizationPhase.POST_PROMO.value,
        "EQUIP_RENTAL",
        FeeLabelCategory.MONTHLY_RECURRING.value,
        1500,
    ),
    (
        ItemizationPhase.POST_PROMO.value,
        "NETWORK_ACCESS",
        FeeLabelCategory.MONTHLY_RECURRING.value,
        700,
    ),
    (
        ItemizationPhase.POST_PROMO.value,
        "REG_RECOVERY",
        FeeLabelCategory.MONTHLY_RECURRING.value,
        260,
    ),
    (
        ItemizationPhase.POST_PROMO.value,
        "STATE_USF",
        FeeLabelCategory.GOVERNMENT_TAX.value,
        169,
    ),
    (
        ItemizationPhase.ONE_TIME.value,
        "INSTALL",
        FeeLabelCategory.ONE_TIME.value,
        9900,
    ),
]

# Two further single-sample measurement windows on the reference probe, each
# clear of the previous window's trailing cooldown buffer.
SECOND_WINDOW_START = "2026-08-11T00:00:00Z"
SECOND_WINDOW_END = "2026-08-12T00:00:00Z"
SECOND_WINDOW_SAMPLES = [build_sample("2026-08-11T19:30:00Z", 244, 116, 26)]
THIRD_WINDOW_START = "2026-08-13T00:00:00Z"
THIRD_WINDOW_END = "2026-08-14T00:00:00Z"
THIRD_WINDOW_SAMPLES = [build_sample("2026-08-13T20:30:00Z", 236, 114, 28)]

# The minimal plan: every optional attribute omitted so the declared defaults
# are the only thing that can supply them.
MINIMAL_PLAN_OPTIONALS = (
    "intro_price_cents",
    "intro_term_months",
    "data_allowance_gb",
    "overage_rate_cents_per_gb",
    "etf_proration_policy",
    "discount_program_eligible",
)
MINIMAL_MONTHLY_PRICE_CENTS = 5000
MINIMAL_ETF_CENTS = 9000
MINIMAL_FIRST_YEAR_TOTAL_CENTS = 60000

# The plan amended to 8999 carries no fee lines, so the post-promotional total is
# the base charge alone and the benefit clamps at the 3,000-cent monthly cap.
AMENDED_MONTHLY_PRICE_CENTS = 8999
AMENDED_NET_MONTHLY_POST_PROMO_CENTS = 5999


def _plan_payload_without(*omitted: str, **overrides: Any) -> Dict[str, Any]:
    """A plan payload with `omitted` fields absent, so the server must either
    reject the request or supply the declared default itself."""
    payload = build_service_plan_payload(**overrides)
    for field in omitted:
        payload.pop(field, None)
    return payload


def _itemization_rows(label: Dict[str, Any]) -> List[Tuple[str, str, str, int]]:
    """Every itemisation entry as (phase, fee_code, label_category, amount)."""
    return sorted(
        (
            entry["phase"],
            entry["fee_code"],
            entry["label_category"],
            entry["amount_cents"],
        )
        for entry in label["fee_itemization"]
    )


def _plan_with_draft_label() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """The reference plan with one drafted label, so a child path has a real
    parent to hang from."""
    plan = create_service_plan()
    return plan, draft_label(plan["id"])


# ---------------------------------------------------------------------------
# Creation, retrieval and listing
# ---------------------------------------------------------------------------


def test_create_service_plan_initialises_every_derived_field(api):
    """A plan created with every input field present answers 201 with its six
    derived fields at their declared initial values rather than null.

    PRD: "A new plan starts with `label_posture` set to `RESTRICTED`,
    `evidence_sample_total` at 0, `upheld_complaint_count` at 0,
    `price_disclosure_drift` false, `active_label_version_id` null,
    `last_price_change_at` null and `version` at 1."

    Design: Corner/entities/create_service_plan_initialises_every_derived_field
    """
    set_clock(REFERENCE_NOW)

    payload = build_service_plan_payload()
    response = api.create_service_plan(payload, COMPLIANCE_OFFICER_HEADERS)
    plan = validate_success(response, expected_status=201)

    body = response.json()
    assert body["response_type"] == "object", "a single resource answers response_type object"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_, got {body['meta']['api_request_id']!r}"
    )
    assert body["meta"]["api_request_timestamp"], "api_request_timestamp must be present"

    assert plan["plan_code"] == payload["plan_code"]
    assert plan["technology"] == Technology.FIBER.value
    assert plan["advertised_download_mbps"] == 300
    assert plan["advertised_upload_mbps"] == 140
    assert plan["monthly_price_cents"] == 7999
    assert plan["intro_price_cents"] == 4999
    assert plan["intro_term_months"] == 6
    assert plan["required_locales"] == ["en-US"]

    assert_posture(plan, "RESTRICTED")
    assert plan["evidence_sample_total"] == 0, "a new plan has no evidence pool yet"
    assert plan["upheld_complaint_count"] == 0, "a new plan has no upheld complaints"
    assert plan["price_disclosure_drift"] is False, "a new plan has not drifted"
    assert plan["active_label_version_id"] is None, "a new plan has no published label"
    assert plan["last_price_change_at"] is None, "a new plan has never been repriced"

    assert_mutable_resource(plan)
    assert plan["version"] == 1, "version starts at 1 on creation"
    assert plan["created_at"] == CLOCK_TIMESTAMP, "created_at is taken from the logical clock"
    assert plan["updated_at"] == plan["created_at"], (
        "nothing has mutated the plan yet, so updated_at still equals created_at"
    )


def test_get_label_version_returns_the_pinned_snapshot(api):
    """Reading a published label answers the figures pinned on it at
    publication, not values re-derived from the plan at read time.

    PRD: "It copies `typical_download_mbps`, `typical_upload_mbps`,
    `typical_latency_ms` and `methodology_url_snapshot` from that attestation
    onto the label, so those three previously null figures become non-null and
    the printed claim is frozen against later measurement changes."

    Design: Corner/entities/get_label_version_returns_the_pinned_snapshot
    """
    env = build_reference_environment()

    label = validate_success(api.get_label_version(env.label_id, RETAIL_AGENT_HEADERS))

    assert label["id"] == env.label_id
    assert label["plan_id"] == env.plan_id
    assert label["version_seq"] == 1, "the plan's first label is sequence 1"
    assert label["publication_state"] == PublicationState.PUBLISHED.value
    assert label["substantiation_status"] == SubstantiationStatus.SUBSTANTIATED.value
    assert label["attestation_id"] == env.attestation_id

    assert_pinned_typical_figures(
        label,
        PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_UPLOAD,
        PEAK_HOUR_MEDIAN_TYPICAL_LATENCY,
    )
    assert label["methodology_url_snapshot"] == env.methodology["methodology_url"]

    assert label["monthly_total_intro_cents"] == REFERENCE_MONTHLY_TOTAL_INTRO_CENTS
    assert label["net_monthly_intro_cents"] == REFERENCE_NET_MONTHLY_INTRO_CENTS
    assert (
        label["monthly_total_post_promo_cents"]
        == REFERENCE_MONTHLY_TOTAL_POST_PROMO_CENTS
    )
    assert (
        label["net_monthly_post_promo_cents"] == REFERENCE_NET_MONTHLY_POST_PROMO_CENTS
    )
    assert label["one_time_fee_total_cents"] == REFERENCE_ONE_TIME_FEE_TOTAL_CENTS
    assert (
        label["first_year_total_promo_weighted_cents"]
        == REFERENCE_FIRST_YEAR_PROMO_WEIGHTED_CENTS
    )
    assert (
        label["first_year_total_post_promo_cents"]
        == REFERENCE_FIRST_YEAR_POST_PROMO_CENTS
    )

    assert label["etf_disclosure_cents"] == REFERENCE_ETF_DISCLOSURE_CENTS
    assert label["data_allowance_gb_snapshot"] == REFERENCE_DATA_ALLOWANCE_GB
    assert (
        label["overage_rate_cents_per_gb_snapshot"]
        == REFERENCE_OVERAGE_RATE_CENTS_PER_GB
    )

    assert _itemization_rows(label) == sorted(REFERENCE_ITEMIZATION), (
        "the snapshot itemises each recurring line under every phase it applies to, "
        "plus the one-time line"
    )
    assert label["created_by_user_id"] == COMPLIANCE_OFFICER_USER_ID
    assert label["published_by_user_id"] == COMPLIANCE_OFFICER_2_USER_ID


def test_list_test_runs_filters_and_paginates(api):
    """The run list honours limit and offset alongside the plan and status
    filters, and total_count counts the filtered set.

    PRD: "Every list response repeats `limit` and `offset` in the envelope's
    `meta` object alongside `total_count` (the number of records matching the
    filters before pagination is applied) and `has_more` (true when records
    matching the filters remain beyond the current page)."

    Design: Corner/entities/list_test_runs_filters_and_paginates
    """
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()

    record_test_run(probe["id"], plan["id"], methodology["id"])
    record_test_run(
        probe["id"],
        plan["id"],
        methodology["id"],
        window_start=SECOND_WINDOW_START,
        window_end=SECOND_WINDOW_END,
        samples=SECOND_WINDOW_SAMPLES,
    )
    invalidated = record_test_run(
        probe["id"],
        plan["id"],
        methodology["id"],
        window_start=THIRD_WINDOW_START,
        window_end=THIRD_WINDOW_END,
        samples=THIRD_WINDOW_SAMPLES,
    )
    invalidate_test_run(
        invalidated["id"], reason="Panel drift on the third window"
    )

    first_page = api.list_test_runs(
        NETWORK_ENGINEER_HEADERS,
        params={"plan_id": plan["id"], "limit": 2, "offset": 0},
    )
    rows, meta = validate_paginated(first_page)
    assert first_page.json()["response_type"] == "array", "a list answers response_type array"
    assert meta["total_count"] == 3, "three runs match the plan filter"
    assert meta["has_more"] is True, "a third run remains beyond the first page"
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert len(rows) == 2, "the page is capped at the requested limit"

    second_rows, second_meta = validate_paginated(
        api.list_test_runs(
            NETWORK_ENGINEER_HEADERS,
            params={"plan_id": plan["id"], "limit": 2, "offset": 2},
        )
    )
    assert second_meta["total_count"] == 3, "total_count ignores the page window"
    assert second_meta["has_more"] is False, "nothing remains beyond the second page"
    assert len(second_rows) == 1

    status_rows, status_meta = validate_paginated(
        api.list_test_runs(
            NETWORK_ENGINEER_HEADERS,
            params={
                "plan_id": plan["id"],
                "status": TestRunStatus.INVALIDATED.value,
            },
        )
    )
    assert status_meta["total_count"] == 1, "only the withdrawn run matches the status filter"
    assert status_rows[0]["id"] == invalidated["id"]
    assert status_rows[0]["status"] == TestRunStatus.INVALIDATED.value

    default_rows, default_meta = validate_paginated(
        api.list_test_runs(NETWORK_ENGINEER_HEADERS, params={"plan_id": plan["id"]})
    )
    assert default_meta["limit"] == DEFAULT_PAGE_LIMIT, "limit defaults to 10"
    assert default_meta["offset"] == DEFAULT_PAGE_OFFSET, "offset defaults to 0"
    assert default_meta["total_count"] == 3
    assert len(default_rows) == 3

    _, unfiltered_meta = validate_paginated(api.list_test_runs(NETWORK_ENGINEER_HEADERS))
    assert unfiltered_meta["limit"] == DEFAULT_PAGE_LIMIT, "limit defaults to 10 unfiltered too"
    assert unfiltered_meta["offset"] == DEFAULT_PAGE_OFFSET
    assert unfiltered_meta["total_count"] >= 3, (
        "the unfiltered count covers at least this plan's three runs"
    )

    assert read_service_plan(plan["id"])["evidence_sample_total"] == 7, (
        "six samples from the first run plus one from the second; the withdrawn "
        "run contributes nothing"
    )


# ---------------------------------------------------------------------------
# Existence resolution
# ---------------------------------------------------------------------------

_NOT_FOUND_CASES = [
    ("service_plan_path", ApiErrorId.ERR_SERVICE_PLAN_NOT_FOUND.value),
    ("methodology_document_path", ApiErrorId.ERR_METHODOLOGY_DOCUMENT_NOT_FOUND.value),
    ("measurement_probe_path", ApiErrorId.ERR_MEASUREMENT_PROBE_NOT_FOUND.value),
    ("test_run_path", ApiErrorId.ERR_TEST_RUN_NOT_FOUND.value),
    ("attestation_path", ApiErrorId.ERR_ATTESTATION_NOT_FOUND.value),
    ("label_version_path", ApiErrorId.ERR_LABEL_VERSION_NOT_FOUND.value),
    ("translation_path", ApiErrorId.ERR_TRANSLATION_NOT_FOUND.value),
    ("subscriber_account_path", ApiErrorId.ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND.value),
    ("complaint_path", ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value),
    ("remediation_credit_path", ApiErrorId.ERR_REMEDIATION_CREDIT_NOT_FOUND.value),
    ("regulator_inquiry_path", ApiErrorId.ERR_REGULATOR_INQUIRY_NOT_FOUND.value),
    ("plan_change_notice_path", ApiErrorId.ERR_PLAN_CHANGE_NOTICE_NOT_FOUND.value),
    ("complaint_body_account_fk", ApiErrorId.ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND.value),
]

_CASES_NEEDING_A_PARENT_LABEL = ("translation_path", "complaint_body_account_fk")


@pytest.mark.parametrize("case,expected_error_id", _NOT_FOUND_CASES)
def test_unknown_ids_return_not_found_for_every_entity(api, case, expected_error_id):
    """Every entity answers an unknown id with its own 404 code, whether the id
    arrives in the path or as a body foreign key.

    PRD: "Each entity has its own not-found code, all of them 404:
    `ERR_SERVICE_PLAN_NOT_FOUND` (for a plan named by a path segment or by
    `plan_id` or `target_plan_id`), `ERR_METHODOLOGY_DOCUMENT_NOT_FOUND`,
    `ERR_MEASUREMENT_PROBE_NOT_FOUND` (for a `probe_id` that names nothing),
    `ERR_TEST_RUN_NOT_FOUND`, `ERR_ATTESTATION_NOT_FOUND`,
    `ERR_LABEL_VERSION_NOT_FOUND` (for a path segment or a
    `disputed_label_version_id`), `ERR_TRANSLATION_NOT_FOUND`,
    `ERR_SUBSCRIBER_ACCOUNT_NOT_FOUND` (for a path segment or an `account_id`),
    `ERR_COMPLAINT_NOT_FOUND` (for a path segment or a `complaint_id`),
    `ERR_REMEDIATION_CREDIT_NOT_FOUND`, `ERR_REGULATOR_INQUIRY_NOT_FOUND` and
    `ERR_PLAN_CHANGE_NOTICE_NOT_FOUND`."

    Design: Corner/entities/unknown_ids_return_not_found_for_every_entity
    """
    set_clock(REFERENCE_NOW)

    label_id = None
    if case in _CASES_NEEDING_A_PARENT_LABEL:
        _, label = _plan_with_draft_label()
        label_id = label["id"]

    calls = {
        "service_plan_path": lambda: api.get_service_plan(
            UNKNOWN_ID, COMPLIANCE_OFFICER_HEADERS
        ),
        "methodology_document_path": lambda: api.get_methodology_document(
            UNKNOWN_ID, NETWORK_ENGINEER_HEADERS
        ),
        "measurement_probe_path": lambda: api.get_measurement_probe(
            UNKNOWN_ID, NETWORK_ENGINEER_HEADERS
        ),
        "test_run_path": lambda: api.get_test_run(UNKNOWN_ID, NETWORK_ENGINEER_HEADERS),
        "attestation_path": lambda: api.get_performance_attestation(
            UNKNOWN_ID, NETWORK_ENGINEER_HEADERS
        ),
        "label_version_path": lambda: api.get_label_version(
            UNKNOWN_ID, COMPLIANCE_OFFICER_HEADERS
        ),
        "translation_path": lambda: api.verify_label_translation(
            label_id, UNKNOWN_ID, LOCALIZATION_SPECIALIST_HEADERS
        ),
        "subscriber_account_path": lambda: api.get_subscriber_account(
            UNKNOWN_ID, RETAIL_AGENT_HEADERS
        ),
        "complaint_path": lambda: api.get_complaint(
            UNKNOWN_ID, COMPLAINT_ANALYST_HEADERS
        ),
        "remediation_credit_path": lambda: api.get_remediation_credit(
            UNKNOWN_ID, COMPLIANCE_OFFICER_HEADERS
        ),
        "regulator_inquiry_path": lambda: api.get_regulator_inquiry(
            UNKNOWN_ID, REGULATORY_LIAISON_HEADERS
        ),
        "plan_change_notice_path": lambda: api.get_plan_change_notice(
            UNKNOWN_ID, RETAIL_AGENT_HEADERS
        ),
        "complaint_body_account_fk": lambda: api.create_complaint(
            build_complaint_payload(
                UNKNOWN_ID,
                label_id,
                REFERENCE_NOW,
                allegation_type=AllegationType.FEE_MISMATCH.value,
                affected_days=1,
                narrative="Body FK that does not resolve",
            ),
            COMPLAINT_ANALYST_HEADERS,
        ),
    }

    response = calls[case]()
    error = validate_error(response, expected_error_id)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip(), "every rejection carries a human-readable message"

    if case == "complaint_body_account_fk":
        _, meta = validate_paginated(
            api.list_complaints(
                COMPLAINT_ANALYST_HEADERS,
                params={"disputed_label_version_id": label_id},
            )
        )
        assert meta["total_count"] == 0, "the rejected intake created no complaint row"

    if case == "translation_path":
        assert expected_error_id == ApiErrorId.ERR_TRANSLATION_NOT_FOUND.value, (
            "the label resolves, so the missing translation is what fails"
        )


def test_child_rows_require_an_existing_parent(api):
    """Both sub-resource collections resolve their parent first, so an unknown
    parent answers the parent's own 404 rather than a child-shaped error.

    PRD: "When a path contains more than one identifier, the identifiers are
    resolved strictly left to right, and the request fails on the first one
    that names nothing."

    Design: Corner/entities/child_rows_require_an_existing_parent
    """
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()

    orphan_fee = api.add_fee_line_item(
        UNKNOWN_ID,
        build_fixed_fee_payload("ORPHAN", 100, description="Fee under a missing plan"),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(orphan_fee, ApiErrorId.ERR_SERVICE_PLAN_NOT_FOUND.value)

    orphan_translation = api.create_label_translation(
        UNKNOWN_ID,
        build_translation_payload(
            locale="es-MX", translated_summary="Etiqueta huerfana"
        ),
        LOCALIZATION_SPECIALIST_HEADERS,
    )
    validate_error(orphan_translation, ApiErrorId.ERR_LABEL_VERSION_NOT_FOUND.value)

    orphan_listing = api.list_fee_line_items(UNKNOWN_ID, COMPLIANCE_OFFICER_HEADERS)
    validate_error(orphan_listing, ApiErrorId.ERR_SERVICE_PLAN_NOT_FOUND.value)

    rows, meta = validate_paginated(
        api.list_fee_line_items(plan["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 5, "the real plan still carries its five fee lines"
    assert len(rows) == 5


def test_flat_topology_cross_reference_integrity(api):
    """Every cross-aggregate reference is validated on its own terms: a run may
    name a real plan yet an unpublished methodology, and a docket may carry a
    well-formed docket number yet an unknown complaint.

    PRD: "`PUBLISHED` is terminal: only a published document may back a
    measurement run or an attestation, and a run or attestation that cites a
    document still in `DRAFT` is rejected with
    `ERR_METHODOLOGY_NOT_PUBLISHED`."

    Design: Corner/entities/flat_topology_cross_reference_integrity
    """
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    record_test_run(probe["id"], plan["id"], methodology["id"])

    draft_methodology = create_methodology_document(
        version_label="v2.0-draft",
        methodology_url="https://isp.example/methodology/v2.0",
        peak_hours_start_utc_hour=18,
        peak_hours_end_utc_hour=22,
    )
    plan_version = current_plan_version(plan["id"])

    run_response = api.create_test_run(
        build_test_run_payload(
            probe["id"],
            plan["id"],
            draft_methodology["id"],
            window_start=SECOND_WINDOW_START,
            window_end=SECOND_WINDOW_END,
            samples=SECOND_WINDOW_SAMPLES,
        ),
        NETWORK_ENGINEER_HEADERS,
    )
    validate_error(run_response, ApiErrorId.ERR_METHODOLOGY_NOT_PUBLISHED.value)

    inquiry_response = api.create_regulator_inquiry(
        build_regulator_inquiry_payload(UNKNOWN_ID),
        REGULATORY_LIAISON_HEADERS,
    )
    validate_error(inquiry_response, ApiErrorId.ERR_COMPLAINT_NOT_FOUND.value)

    plan_after = read_service_plan(plan["id"])
    assert plan_after["version"] == plan_version, (
        "a rejected write mutates nothing, so the plan's version is unchanged"
    )
    assert plan_after["evidence_sample_total"] == len(REFERENCE_SAMPLES), (
        "the rejected run never entered the evidence pool"
    )


# ---------------------------------------------------------------------------
# Field-level contracts
# ---------------------------------------------------------------------------


def test_missing_required_and_conditional_fields_rejected(api):
    """Absent required fields and unsatisfied conditional pairings are both
    malformed requests.

    PRD: "A `FIXED` line must carry `amount_cents` (zero or more) and must
    leave `rate_pct` null; a `PCT_OF_MONTHLY_CHARGE` line must carry `rate_pct`
    — a fraction strictly greater than 0 and strictly less than 1, with at most
    four decimal places — and must leave `amount_cents` null."

    Design: Corner/entities/missing_required_and_conditional_fields_rejected
    """
    set_clock(REFERENCE_NOW)
    plan = create_service_plan()
    label = draft_label(plan["id"])
    account = get_success_data(
        api.create_subscriber_account(
            build_subscriber_account_payload(plan["id"], REFERENCE_NOW),
            RETAIL_AGENT_HEADERS,
        )
    )

    invalid = ApiErrorId.ERR_INVALID_REQUEST.value

    validate_error(
        api.create_service_plan(
            _plan_payload_without(
                "monthly_price_cents",
                *MINIMAL_PLAN_OPTIONALS,
                display_name="No price",
                technology=Technology.CABLE.value,
                advertised_download_mbps=100,
                advertised_upload_mbps=20,
                early_termination_fee_cents=0,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.create_service_plan(
            _plan_payload_without(
                *MINIMAL_PLAN_OPTIONALS,
                display_name="No locale",
                technology=Technology.CABLE.value,
                advertised_download_mbps=100,
                advertised_upload_mbps=20,
                monthly_price_cents=5000,
                early_termination_fee_cents=0,
                required_locales=[],
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.create_service_plan(
            _plan_payload_without(
                "data_allowance_gb",
                "overage_rate_cents_per_gb",
                "etf_proration_policy",
                "discount_program_eligible",
                display_name="Intro without term",
                technology=Technology.CABLE.value,
                advertised_download_mbps=100,
                advertised_upload_mbps=20,
                monthly_price_cents=5000,
                early_termination_fee_cents=0,
                intro_price_cents=3000,
                intro_term_months=0,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    fixed_without_amount = build_fixed_fee_payload(
        "NOAMOUNT", 0, description="Fixed without amount"
    )
    fixed_without_amount.pop("amount_cents")
    validate_error(
        api.add_fee_line_item(
            plan["id"], fixed_without_amount, COMPLIANCE_OFFICER_HEADERS
        ),
        invalid,
    )

    percentage_without_rate = build_percentage_fee_payload(
        "NORATE", 0.05, description="Percentage without rate"
    )
    percentage_without_rate.pop("rate_pct")
    validate_error(
        api.add_fee_line_item(
            plan["id"], percentage_without_rate, COMPLIANCE_OFFICER_HEADERS
        ),
        invalid,
    )

    validate_error(
        api.add_fee_line_item(
            plan["id"],
            build_percentage_fee_payload(
                "ONETIMEPCT",
                0.05,
                label_category=FeeLabelCategory.ONE_TIME.value,
                description="One-time on a percentage basis",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    speed_without_measurement = build_complaint_payload(
        account["id"],
        label["id"],
        REFERENCE_NOW,
        allegation_type=AllegationType.SPEED_SHORTFALL.value,
        affected_days=3,
        narrative="Speed claim without a measurement",
    )
    speed_without_measurement.pop("measured_download_mbps")
    validate_error(
        api.create_complaint(speed_without_measurement, COMPLAINT_ANALYST_HEADERS),
        invalid,
    )

    _, meta = validate_paginated(
        api.list_fee_line_items(plan["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 0, "none of the rejected fee lines persisted"


def test_invalid_enum_and_range_values_rejected(api):
    """Enum membership, numeric bounds and the two-field ordering constraints
    are all malformed requests.

    PRD: "A `limit` outside the range 1 through 100 inclusive, or a negative
    `offset`, is a malformed request and is rejected with
    `ERR_INVALID_REQUEST`."

    Design: Corner/entities/invalid_enum_and_range_values_rejected
    """
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    record_test_run(probe["id"], plan["id"], methodology["id"])
    plan_version = current_plan_version(plan["id"])

    invalid = ApiErrorId.ERR_INVALID_REQUEST.value

    validate_error(
        api.create_service_plan(
            _plan_payload_without(
                *MINIMAL_PLAN_OPTIONALS,
                display_name="Unknown technology",
                technology="5G_HOME",
                advertised_download_mbps=100,
                advertised_upload_mbps=20,
                monthly_price_cents=5000,
                early_termination_fee_cents=0,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.add_fee_line_item(
            plan["id"],
            build_percentage_fee_payload(
                "BIGRATE", 1.5, description="Rate above one"
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.create_methodology_document(
            build_methodology_document_payload(
                version_label="v0.9",
                methodology_url="https://isp.example/methodology/v0.9",
                peak_hours_start_utc_hour=23,
                peak_hours_end_utc_hour=19,
            ),
            NETWORK_ENGINEER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.create_test_run(
            build_test_run_payload(
                probe["id"],
                plan["id"],
                methodology["id"],
                window_start=SECOND_WINDOW_END,
                window_end=SECOND_WINDOW_START,
                samples=SECOND_WINDOW_SAMPLES,
            ),
            NETWORK_ENGINEER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.list_test_runs(
            NETWORK_ENGINEER_HEADERS, params={"plan_id": plan["id"], "limit": 101}
        ),
        invalid,
    )

    validate_error(
        api.create_label_version(
            build_label_version_payload(
                plan["id"],
                LATER_EFFECTIVE_FROM,
                plan_version,
                effective_until=LATER_EFFECTIVE_FROM,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    validate_error(
        api.create_label_version(
            build_label_version_payload(
                plan["id"],
                LATER_EFFECTIVE_FROM,
                plan_version,
                accessibility_conformance="WCAG_AAA",
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        invalid,
    )

    _, run_meta = validate_paginated(
        api.list_test_runs(NETWORK_ENGINEER_HEADERS, params={"plan_id": plan["id"]})
    )
    assert run_meta["total_count"] == 1, "the malformed window recorded no run"

    _, label_meta = validate_paginated(
        api.list_label_versions(
            COMPLIANCE_OFFICER_HEADERS, params={"plan_id": plan["id"]}
        )
    )
    assert label_meta["total_count"] == 0, "neither malformed label draft persisted"

    assert current_plan_version(plan["id"]) == plan_version, (
        "no rejected request mutated the plan"
    )


def test_omitted_optional_fields_apply_declared_defaults(api):
    """A plan created with every optional field omitted takes its declared
    defaults, and the label drafted on it inherits the discount flag from the
    plan rather than defaulting on its own.

    PRD: "Two fields are optional: `effective_until`, the exclusive end of the
    display window, which defaults to null meaning open-ended and, when
    supplied, must be strictly after `effective_from`; and
    `discount_program_applied`, which when omitted defaults to the plan's
    current `discount_program_eligible` value."

    Design: Corner/entities/omitted_optional_fields_apply_declared_defaults
    """
    set_clock(REFERENCE_NOW)

    plan = get_success_data(
        api.create_service_plan(
            _plan_payload_without(
                *MINIMAL_PLAN_OPTIONALS,
                display_name="DSL Basic",
                technology=Technology.DSL.value,
                advertised_download_mbps=25,
                advertised_upload_mbps=3,
                monthly_price_cents=MINIMAL_MONTHLY_PRICE_CENTS,
                early_termination_fee_cents=MINIMAL_ETF_CENTS,
                required_locales=["en-US"],
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )

    assert plan["intro_price_cents"] is None, "intro_price_cents defaults to null"
    assert plan["intro_term_months"] == 0, "intro_term_months defaults to 0"
    assert plan["data_allowance_gb"] is None, "data_allowance_gb defaults to null"
    assert plan["overage_rate_cents_per_gb"] == 0, (
        "overage_rate_cents_per_gb defaults to 0"
    )
    assert plan["etf_proration_policy"] == EtfProrationPolicy.FULL.value, (
        "etf_proration_policy defaults to FULL"
    )
    assert plan["discount_program_eligible"] is False, (
        "discount_program_eligible defaults to false"
    )

    label = validate_success(
        api.create_label_version(
            build_label_version_payload(
                plan["id"], REFERENCE_NOW, current_plan_version(plan["id"])
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        expected_status=201,
    )

    assert label["discount_program_applied"] is False, (
        "the omitted flag is inherited from the plan, not defaulted to true"
    )
    assert label["fee_itemization"] == [], "a plan with no fee lines itemises nothing"
    assert label["monthly_total_intro_cents"] is None, (
        "there is no introductory phase to total"
    )
    assert label["net_monthly_intro_cents"] is None
    assert label["monthly_total_post_promo_cents"] == MINIMAL_MONTHLY_PRICE_CENTS
    assert label["net_monthly_post_promo_cents"] == MINIMAL_MONTHLY_PRICE_CENTS
    assert label["discount_program_benefit_post_promo_cents"] == 0, (
        "an ineligible plan earns no discount benefit"
    )
    assert label["one_time_fee_total_cents"] == 0
    assert (
        label["first_year_total_promo_weighted_cents"] == MINIMAL_FIRST_YEAR_TOTAL_CENTS
    )
    assert label["first_year_total_post_promo_cents"] == MINIMAL_FIRST_YEAR_TOTAL_CENTS
    assert (
        label["first_year_total_promo_weighted_cents"]
        == label["first_year_total_post_promo_cents"]
    ), "with no introductory months billed the two first-year variants coincide"
    assert label["etf_disclosure_cents"] == MINIMAL_ETF_CENTS
    assert label["data_allowance_gb_snapshot"] is None
    assert label["overage_rate_cents_per_gb_snapshot"] == 0

    account_payload = build_subscriber_account_payload(plan["id"], REFERENCE_NOW)
    for optional in ("accessibility_need", "discount_program_enrolled"):
        account_payload.pop(optional)
    account = validate_success(
        api.create_subscriber_account(account_payload, RETAIL_AGENT_HEADERS),
        expected_status=201,
    )

    assert account["accessibility_need"] == AccessibilityNeed.NONE.value
    assert account["discount_program_enrolled"] is False
    assert account["subscription_state"] == SubscriptionState.ACTIVE.value
    assert account["credit_balance_cents"] == 0
    assert account["remediation_count"] == 0
    assert account["audit_flag"] is False
    assert account["pricing_phase"] == PricingPhase.POST_PROMO.value, (
        "a plan with no introductory price puts the account straight in POST_PROMO"
    )


def test_computed_fields_are_derived_not_accepted_from_input(api):
    """The sequence number, the sample count, the itemisation and the
    methodology snapshot are all produced by the server.

    PRD: "The draft receives `version_seq`, a per-plan monotonic sequence
    number computed as one more than the highest `version_seq` among that
    plan's existing labels and starting at 1 for the plan's first label, and it
    records the drafting officer's `X-User-ID` in `created_by_user_id`."

    Design: Corner/entities/computed_fields_are_derived_not_accepted_from_input
    """
    env = build_reference_environment()

    second_label = validate_success(
        api.create_label_version(
            build_label_version_payload(
                env.plan_id, LATER_EFFECTIVE_FROM, current_plan_version(env.plan_id)
            ),
            COMPLIANCE_OFFICER_HEADERS,
        ),
        expected_status=201,
    )

    assert env.label["version_seq"] == 1, "the plan's first label is sequence 1"
    assert second_label["version_seq"] == 2, (
        "the second label is one more than the highest sequence, without the "
        "client saying so"
    )

    run = read_test_run(env.run_id)
    assert run["sample_count"] == len(REFERENCE_SAMPLES), (
        "sample_count is fixed at creation as the number of samples supplied"
    )

    attestation = read_attestation(env.attestation_id)
    assert attestation["methodology_snapshot"] == {
        "version_label": env.methodology["version_label"],
        "peak_hours_start_utc_hour": env.methodology["peak_hours_start_utc_hour"],
        "peak_hours_end_utc_hour": env.methodology["peak_hours_end_utc_hour"],
        "min_samples_required": env.methodology["min_samples_required"],
        "max_run_duration_days": env.methodology["max_run_duration_days"],
        "methodology_url": env.methodology["methodology_url"],
    }, "the snapshot is a version-locked copy of the document at creation time"
    assert attestation["included_run_ids"] == [env.run_id]
    assert attestation["pooled_sample_count"] == PEAK_HOUR_MEDIAN_POOLED_COUNT
    assert attestation["metric_variant"] == MetricVariant.PEAK_HOUR_MEDIAN.value

    assert _itemization_rows(second_label) == _itemization_rows(env.label), (
        "the second label recomputes the same itemisation from the same fee lines"
    )
    assert (
        second_label["monthly_total_intro_cents"]
        == REFERENCE_MONTHLY_TOTAL_INTRO_CENTS
    )
    assert second_label["publication_state"] == PublicationState.DRAFT.value
    assert (
        second_label["substantiation_status"]
        == SubstantiationStatus.PENDING_EVIDENCE.value
    ), "a second label does not inherit the first one's approval"


def test_system_fields_are_server_minted_and_versioned(api):
    """Ids are bare UUIDs, the acting principal is recorded from the header, and
    version increments on every mutation including a cascaded recomputation.

    PRD: "All resources except a `LabelDisclosure` additionally carry
    `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the
    record — and `version`, an integer that starts at 1 on creation and
    increments by one on every mutation, including mutations the server
    performs on its own initiative when reconciling a derived field."

    Design: Corner/entities/system_fields_are_server_minted_and_versioned
    """
    set_clock(REFERENCE_NOW)
    plan = create_service_plan()
    label = draft_label(plan["id"])

    assert_resource_identity(plan)
    assert_resource_identity(label)
    assert "_" not in plan["id"], "the plan id carries no type prefix"
    assert "_" not in label["id"], "the label id carries no type prefix"
    assert label["created_by_user_id"] == COMPLIANCE_OFFICER_USER_ID, (
        "created_by_user_id is taken from X-User-ID, never from the request body"
    )
    assert label["version"] == 1, "version starts at 1 on creation"

    # PRD: "Drafting a label also increments the plan's `version`." The plan was
    # minted at 1 and the draft above carried it to 2, so the amendment lands on 3.
    plan_before_amendment = validate_success(
        api.get_service_plan(plan["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert plan_before_amendment["version"] == 2, (
        "drafting the label was a server-initiated mutation of the plan"
    )

    amended = validate_success(
        api.amend_service_plan(
            plan["id"],
            build_plan_amendment_payload(
                change_justification="Annual repricing",
                monthly_price_cents=AMENDED_MONTHLY_PRICE_CENTS,
            ),
            COMPLIANCE_OFFICER_HEADERS,
        )
    )
    assert_mutable_resource(amended)
    assert amended["version"] == plan_before_amendment["version"] + 1, (
        "the amendment increments the plan's version"
    )
    assert amended["updated_at"] == CLOCK_TIMESTAMP, (
        "updated_at is written from the logical clock"
    )

    label_after = validate_success(
        api.get_label_version(label["id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert label_after["monthly_total_post_promo_cents"] == AMENDED_MONTHLY_PRICE_CENTS, (
        "the draft label was recomputed against the amended price"
    )
    assert (
        label_after["net_monthly_post_promo_cents"]
        == AMENDED_NET_MONTHLY_POST_PROMO_CENTS
    ), "the benefit clamps at the monthly cap, so the net is the base less 3,000 cents"
    assert label_after["version"] == 2, (
        "the cascaded recomputation is itself a mutation and bumps the label's version"
    )
    assert label_after["created_at"] == label["created_at"], (
        "created_at is untouched by the recomputation"
    )
    assert label_after["updated_at"] == CLOCK_TIMESTAMP, (
        "updated_at is rewritten from the logical clock, which has not moved"
    )


# ---------------------------------------------------------------------------
# The immutable disclosure row
# ---------------------------------------------------------------------------


def test_label_disclosure_rows_are_immutable(api):
    """Each disclosure appends a fresh audit row carrying only id and
    created_at, keeping the sequence and net figure it was served.

    PRD: "A `LabelDisclosure` is an immutable audit event: it carries only `id`
    and `created_at`, and both `updated_at` and `version` are absent from it."

    Design: Corner/entities/label_disclosure_rows_are_immutable
    """
    env = build_reference_environment()
    assert env.account["pricing_phase"] == PricingPhase.INTRO.value, (
        "the account is inside its introductory term, so the intro net is disclosed"
    )

    first = validate_success(
        api.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(channel=DisclosureChannel.POINT_OF_SALE.value),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    second = validate_success(
        api.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(channel=DisclosureChannel.ACCOUNT_PORTAL.value),
            env.subscriber_headers,
        ),
        expected_status=201,
    )

    assert first["id"] != second["id"], "the second call appended rather than overwrote"
    assert_immutable_audit_event(first)
    assert_immutable_audit_event(second)

    assert first["label_version_id"] == env.label_id
    assert first["disclosed_label_version_seq"] == 1
    assert first["disclosed_net_monthly_cents"] == REFERENCE_NET_MONTHLY_INTRO_CENTS
    assert first["disclosed_by_user_id"] == RETAIL_AGENT_USER_ID
    assert first["channel"] == DisclosureChannel.POINT_OF_SALE.value

    assert second["disclosed_by_user_id"] == env.account_id, (
        "for the Subscriber role X-User-ID is the acting account's own id"
    )
    assert second["channel"] == DisclosureChannel.ACCOUNT_PORTAL.value
    assert second["disclosed_label_version_seq"] == 1

    rows, meta = validate_paginated(
        api.list_label_version_disclosures(env.label_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 2, "both disclosures stand against the label"
    assert {row["id"] for row in rows} == {first["id"], second["id"]}

    account = read_subscriber_account(env.account_id)
    assert account["last_disclosed_label_version_id"] == env.label_id
