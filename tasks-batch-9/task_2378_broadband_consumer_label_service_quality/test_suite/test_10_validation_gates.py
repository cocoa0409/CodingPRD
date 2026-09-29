"""Validation gates: notice periods, label-window intake, disclosure selection,
translation coverage, accessible formats, uniqueness ordering, the fiscal guard on
upholding, and sample-in-window admissibility.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ApiErrorId, api_client
from test_helpers.assertions import (
    assert_account_ledger,
    assert_evidence_sample_total,
    assert_label_dimensions,
    assert_posture,
)
from test_helpers.constants import (
    NOTICE_MIN_DAYS,
    PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD,
    REFERENCE_NOW,
)
from test_helpers.factories import (
    build_complaint_payload,
    build_disclosure_payload,
    build_dismiss_payload,
    build_fixed_fee_payload,
    build_measurement_probe_payload,
    build_plan_change_notice_payload,
    build_regulator_inquiry_payload,
    build_sample,
    build_service_plan_payload,
    build_subscriber_account_payload,
    build_test_run_payload,
    build_uphold_payload,
)
from test_helpers.fixtures import (
    add_translation,
    add_verified_translation,
    build_reference_environment,
    create_certified_attestation,
    create_measured_plan,
    create_measurement_probe,
    create_published_label,
    create_published_methodology,
    create_reference_plan,
    create_regulator_inquiry,
    create_subscriber_account,
    draft_label,
    file_complaint,
    investigate_complaint,
    read_complaint,
    read_label,
    read_service_plan,
    read_subscriber_account,
    record_test_run,
    set_clock,
    triage_complaint,
)
from test_helpers.test_users import (
    COMPLAINT_ANALYST_HEADERS,
    COMPLIANCE_OFFICER_2_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    LOCALIZATION_SPECIALIST_2_HEADERS,
    NETWORK_ENGINEER_HEADERS,
    REGULATORY_LIAISON_HEADERS,
    RETAIL_AGENT_HEADERS,
    make_subscriber_headers,
)
from test_helpers.types import (
    AccessibilityConformance,
    AccessibilityNeed,
    AccessibleFormat,
    AllegationType,
    ComplaintResolution,
    ComplaintSeverity,
    ComplaintState,
    CreditBasis,
    LabelPosture,
    NoticeState,
    NoticeType,
    PublicationState,
    SubscriptionState,
    SubstantiationStatus,
    TestRunStatus,
    TranslationStatus,
)

# The instant the reference label takes effect is also the instant every chain
# below reads as "now"; the dates in each scenario are relative to it.
OCTOBER_FIRST = "2026-10-01T00:00:00Z"
NOTICE_TWENTY_NINE_DAYS_OUT = "2026-09-30T00:00:00Z"
OBSERVED_INSIDE_WINDOW = "2026-09-02T12:00:00Z"
OBSERVED_BEFORE_WINDOW = "2026-08-15T12:00:00Z"

#: Net introductory monthly charge of the reference label, in whole cents.
REFERENCE_NET_MONTHLY_INTRO_CENTS = 3766

#: The reference plan carries exactly five itemised fee lines.
REFERENCE_FEE_LINE_COUNT = 5


def _create_bilingual_plan():
    """A plan with no promotional price and no fee lines that is obliged to
    serve two locales."""
    generated = build_service_plan_payload()
    payload = {
        "plan_code": generated["plan_code"],
        "display_name": "Fiber 300 Bilingual",
        "technology": generated["technology"],
        "advertised_download_mbps": generated["advertised_download_mbps"],
        "advertised_upload_mbps": generated["advertised_upload_mbps"],
        "monthly_price_cents": 7999,
        "early_termination_fee_cents": 0,
        "required_locales": ["en-US", "es-MX"],
    }
    return get_success_data(
        api_client.create_service_plan(payload, COMPLIANCE_OFFICER_HEADERS)
    )


def test_notice_period_shorter_than_thirty_days_rejected():
    """Twenty-nine days of notice is refused; exactly thirty is accepted.

    PRD: "And the `effective_date` must be at least thirty whole days after the
    logical clock, or the request answers `ERR_NOTICE_PERIOD_TOO_SHORT`."
    PRD: "Creating the notice records `notice_days` as the whole number of days
    between the logical clock at creation and the `effective_date` — the span in
    seconds divided by 86,400 and rounded down"
    PRD: "It also moves the account from `ACTIVE` to `PENDING_CHANGE` and
    increments the account's `version`."

    Design: Corner/validations/notice_period_shorter_than_thirty_days_rejected
    """
    env = build_reference_environment()

    too_short = api_client.create_plan_change_notice(
        build_plan_change_notice_payload(
            env.account_id,
            env.plan_id,
            NOTICE_TWENTY_NINE_DAYS_OUT,
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="Twenty-nine days of notice",
        ),
        RETAIL_AGENT_HEADERS,
    )
    validate_error(too_short, ApiErrorId.ERR_NOTICE_PERIOD_TOO_SHORT.value, 422)

    after_rejection = read_subscriber_account(env.account_id)
    assert after_rejection["subscription_state"] == SubscriptionState.ACTIVE.value, (
        "a rejected notice must not move the account into a pending-change posture"
    )

    accepted = api_client.create_plan_change_notice(
        build_plan_change_notice_payload(
            env.account_id,
            env.plan_id,
            OCTOBER_FIRST,
            notice_type=NoticeType.PRICE_INCREASE.value,
            reason="Exactly thirty days of notice",
        ),
        RETAIL_AGENT_HEADERS,
    )
    notice = validate_success(accepted, expected_status=201)
    assert notice["notice_days"] == NOTICE_MIN_DAYS, (
        "the notice-period boundary is inclusive, so exactly thirty days is admissible"
    )
    assert notice["state"] == NoticeState.SENT.value

    rows, meta = validate_paginated(
        api_client.list_plan_change_notices(
            RETAIL_AGENT_HEADERS, params={"account_id": env.account_id}
        )
    )
    assert meta["total_count"] == 1, "the refused attempt persisted no notice"
    assert [row["id"] for row in rows] == [notice["id"]]

    after_acceptance = read_subscriber_account(env.account_id)
    assert (
        after_acceptance["subscription_state"] == SubscriptionState.PENDING_CHANGE.value
    )


def test_complaint_must_cite_a_label_covering_the_observed_date():
    """Intake validity turns on the disputed label, not on the complaint body.

    PRD: "The disputed label must be a label a consumer could actually have been
    shown on the date in question: its display window must cover the
    `service_observed_date`, and its pinned typical figures must be non-null. A
    label that was never published carries null typical figures and therefore
    cannot be disputed — the intake answers `ERR_LABEL_INVALID_STATE`."

    Design: Corner/validations/complaint_must_cite_a_label_covering_the_observed_date
    """
    env = build_reference_environment()
    never_published_label = draft_label(env.plan_id, effective_from=OCTOBER_FIRST)

    before_window = api_client.create_complaint(
        build_complaint_payload(
            env.account_id,
            env.label_id,
            OBSERVED_BEFORE_WINDOW,
            affected_days=3,
            narrative="Observed before this label took effect",
            measured_download_mbps=120,
        ),
        COMPLAINT_ANALYST_HEADERS,
    )
    validate_error(before_window, ApiErrorId.ERR_LABEL_INVALID_STATE.value, 409)

    unpublished = api_client.create_complaint(
        build_complaint_payload(
            env.account_id,
            never_published_label["id"],
            OBSERVED_INSIDE_WINDOW,
            affected_days=3,
            narrative="Disputing a label that was never published",
            measured_download_mbps=120,
        ),
        COMPLAINT_ANALYST_HEADERS,
    )
    validate_error(unpublished, ApiErrorId.ERR_LABEL_INVALID_STATE.value, 409)

    in_window = api_client.create_complaint(
        build_complaint_payload(
            env.account_id,
            env.label_id,
            OBSERVED_INSIDE_WINDOW,
            affected_days=3,
            narrative="In-window shortfall against the published label",
            measured_download_mbps=120,
        ),
        COMPLAINT_ANALYST_HEADERS,
    )
    complaint = validate_success(in_window, expected_status=201)
    assert complaint["state"] == ComplaintState.INTAKE.value

    triage_complaint(complaint["id"])
    investigate_complaint(complaint["id"])
    assessed = read_complaint(complaint["id"])
    assert assessed["shortfall_ratio"] == pytest.approx(0.5000, abs=0.0001), (
        "the shortfall is measured against the figure pinned on the disputed label"
    )
    assert assessed["severity"] == ComplaintSeverity.SEVERE.value

    rows, meta = validate_paginated(
        api_client.list_complaints(
            COMPLAINT_ANALYST_HEADERS,
            params={"disputed_label_version_id": never_published_label["id"]},
        )
    )
    assert meta["total_count"] == 0, "no complaint was filed against the draft label"
    assert rows == []


def test_disclosure_requires_a_label_effective_at_the_clock():
    """A label published ahead of its window cannot yet be disclosed.

    PRD: "Selection considers the labels of the account's current plan whose
    `publication_state` is `PUBLISHED` and whose half-open display window contains
    the logical clock — that is, whose `effective_from` is at or before the clock
    and whose `effective_until` is either null or strictly after the clock."
    PRD: "An empty candidate set answers
    `ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE`."

    Design: Corner/validations/disclosure_requires_a_label_effective_at_the_clock
    """
    set_clock(REFERENCE_NOW)
    measured = create_measured_plan()
    plan_id = measured["plan"]["id"]
    label = create_published_label(plan_id, effective_from=OCTOBER_FIRST)
    account = create_subscriber_account(plan_id, service_start_date=REFERENCE_NOW)

    assert label["publication_state"] == PublicationState.PUBLISHED.value, (
        "the label is published a month before its window opens"
    )

    too_early = api_client.record_label_disclosure(
        account["id"], build_disclosure_payload(), RETAIL_AGENT_HEADERS
    )
    validate_error(
        too_early, ApiErrorId.ERR_LABEL_NOT_EFFECTIVE_FOR_SERVICE_DATE.value, 409
    )
    assert (
        read_subscriber_account(account["id"])["last_disclosed_label_version_id"] is None
    ), "a refused disclosure leaves the account with no disclosure history"

    set_clock(OCTOBER_FIRST)
    served = api_client.record_label_disclosure(
        account["id"], build_disclosure_payload(), RETAIL_AGENT_HEADERS
    )
    disclosure = validate_success(served, expected_status=201)
    assert disclosure["disclosed_label_version_seq"] == 1
    assert (
        disclosure["disclosed_net_monthly_cents"] == REFERENCE_NET_MONTHLY_INTRO_CENTS
    ), "the account is still in its introductory phase, so the intro net is disclosed"
    assert (
        read_subscriber_account(account["id"])["last_disclosed_label_version_id"]
        == label["id"]
    )


def test_translation_coverage_must_span_every_required_locale():
    """Publication waits until the verified set covers every required locale.

    PRD: "Then the referential prerequisites, in this order: the plan must have an
    attestation whose `status` is `CERTIFIED`, or `ERR_ATTESTATION_NOT_CERTIFIED`;
    every locale in the plan's `required_locales` must have a translation on this
    label whose `status` is `VERIFIED`, or `ERR_TRANSLATION_COVERAGE_INCOMPLETE`;
    and every fee line of the plan whose `label_category` is `MONTHLY_RECURRING`
    must appear in the label's `fee_itemization` for at least one phase, or
    `ERR_FEE_ITEMIZATION_INCOMPLETE`."
    PRD: "`LabelVersion.verified_locale_count` is the number of translations on
    that label whose `status` is `VERIFIED`."

    Design: Corner/validations/translation_coverage_must_span_every_required_locale
    """
    set_clock(REFERENCE_NOW)
    plan = _create_bilingual_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe(
        market_code="US-TX-SAT", panel_size=40, max_concurrent_windows=1
    )
    record_test_run(probe["id"], plan["id"], methodology["id"])
    attestation = create_certified_attestation(plan["id"], methodology["id"])

    label = draft_label(plan["id"], effective_from=REFERENCE_NOW)
    add_verified_translation(
        label["id"], locale="en-US", translated_summary="Bilingual plan label, English"
    )

    english_only = api_client.publish_label_version(
        label["id"], COMPLIANCE_OFFICER_2_HEADERS
    )
    validate_error(
        english_only, ApiErrorId.ERR_TRANSLATION_COVERAGE_INCOMPLETE.value, 409
    )
    assert read_label(label["id"])["verified_locale_count"] == 1

    spanish = add_translation(
        label["id"],
        locale="es-MX",
        translated_summary="Etiqueta del plan bilingue, espanol",
        machine_translated=True,
    )
    still_unverified = api_client.publish_label_version(
        label["id"], COMPLIANCE_OFFICER_2_HEADERS
    )
    validate_error(
        still_unverified, ApiErrorId.ERR_TRANSLATION_COVERAGE_INCOMPLETE.value, 409
    )
    assert read_label(label["id"])["verified_locale_count"] == 1, (
        "a draft translation does not count toward the verified aggregate"
    )

    verified = validate_success(
        api_client.verify_label_translation(
            label["id"], spanish["id"], LOCALIZATION_SPECIALIST_2_HEADERS
        )
    )
    assert verified["status"] == TranslationStatus.VERIFIED.value
    assert verified["machine_translated"] is True, (
        "a machine-produced translation is verified under exactly the same rules"
    )

    published = validate_success(
        api_client.publish_label_version(label["id"], COMPLIANCE_OFFICER_2_HEADERS)
    )
    assert published["verified_locale_count"] == 2
    assert_label_dimensions(
        published,
        PublicationState.PUBLISHED.value,
        SubstantiationStatus.SUBSTANTIATED.value,
    )
    assert published["attestation_id"] == attestation["id"]
    assert float(published["typical_download_mbps"]) == pytest.approx(
        PEAK_HOUR_MEDIAN_TYPICAL_DOWNLOAD, abs=0.01
    )

    _, meta = validate_paginated(
        api_client.list_label_translations(
            label["id"],
            COMPLIANCE_OFFICER_HEADERS,
            params={"status": TranslationStatus.VERIFIED.value},
        )
    )
    assert meta["total_count"] == 2


def test_accessibility_need_constrains_the_disclosure_format():
    """The format rule fires only for accounts that declare an accommodation.

    PRD: "Then accessibility: when the account's `accessibility_need` is
    `SCREEN_READER` the `accessible_format` must be `SCREEN_READER`, and when it is
    `LARGE_PRINT` the format must be `LARGE_PRINT`; additionally, any format other
    than `STANDARD_WEB` requires the selected label's `accessibility_conformance`
    to be `WCAG_AA`. A violation of either rule answers
    `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED`."
    PRD: "The label's `accessibility_conformance` must be `WCAG_AA` — a label that
    has not been brought to that conformance level cannot be published at all — or
    it answers `ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED`."

    Design: Corner/validations/accessibility_need_constrains_the_disclosure_format
    """
    env = build_reference_environment(
        account_overrides={
            "accessibility_need": AccessibilityNeed.SCREEN_READER.value
        }
    )
    unaccommodated = create_subscriber_account(
        env.plan_id,
        service_start_date=REFERENCE_NOW,
        accessibility_need=AccessibilityNeed.NONE.value,
    )

    standard_to_screen_reader = api_client.record_label_disclosure(
        env.account_id,
        build_disclosure_payload(
            accessible_format=AccessibleFormat.STANDARD_WEB.value
        ),
        RETAIL_AGENT_HEADERS,
    )
    validate_error(
        standard_to_screen_reader,
        ApiErrorId.ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED.value,
        422,
    )

    large_print_to_screen_reader = api_client.record_label_disclosure(
        env.account_id,
        build_disclosure_payload(
            accessible_format=AccessibleFormat.LARGE_PRINT.value
        ),
        RETAIL_AGENT_HEADERS,
    )
    validate_error(
        large_print_to_screen_reader,
        ApiErrorId.ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED.value,
        422,
    )

    accommodated = validate_success(
        api_client.record_label_disclosure(
            env.account_id,
            build_disclosure_payload(
                accessible_format=AccessibleFormat.SCREEN_READER.value
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert accommodated["accessible_format"] == AccessibleFormat.SCREEN_READER.value
    assert (
        accommodated["disclosed_net_monthly_cents"]
        == REFERENCE_NET_MONTHLY_INTRO_CENTS
    )

    plain = validate_success(
        api_client.record_label_disclosure(
            unaccommodated["id"],
            build_disclosure_payload(
                accessible_format=AccessibleFormat.STANDARD_WEB.value
            ),
            RETAIL_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert plain["accessible_format"] == AccessibleFormat.STANDARD_WEB.value, (
        "the format rule does not fire for an account whose need is NONE"
    )
    assert plain["disclosed_net_monthly_cents"] == REFERENCE_NET_MONTHLY_INTRO_CENTS

    unconformant = draft_label(
        env.plan_id,
        effective_from=OCTOBER_FIRST,
        accessibility_conformance=AccessibilityConformance.NONE.value,
    )
    add_verified_translation(
        unconformant["id"],
        locale="en-US",
        translated_summary="Label without accessible conformance",
    )
    refused = api_client.publish_label_version(
        unconformant["id"], COMPLIANCE_OFFICER_2_HEADERS
    )
    validate_error(
        refused, ApiErrorId.ERR_ACCESSIBILITY_FORMAT_UNSUPPORTED.value, 422
    )
    assert (
        read_label(unconformant["id"])["publication_state"]
        == PublicationState.DRAFT.value
    ), "a label that cannot reach WCAG_AA conformance never leaves DRAFT"
    assert read_service_plan(env.plan_id)["active_label_version_id"] == env.label_id


def test_uniqueness_is_checked_after_schema_conformance():
    """A request that is both malformed and duplicated reports the shape failure.

    PRD: "When several rules could reject the same request, the system evaluates
    them in the fixed order below and returns the first failure it finds."
    PRD: "On creating a plan, a methodology document, a probe, a subscriber
    account, a regulator inquiry, a fee line item and a translation — otherwise
    `ERR_DUPLICATE_PLAN_CODE`, `ERR_DUPLICATE_DOCKET_NUMBER` (both 409) or
    `ERR_INVALID_REQUEST`."

    Design: Corner/validations/uniqueness_is_checked_after_schema_conformance
    """
    env = build_reference_environment()
    complaint = file_complaint(
        env.account_id,
        env.label_id,
        service_observed_date=OBSERVED_INSIDE_WINDOW,
        allegation_type=AllegationType.LATENCY_SHORTFALL.value,
        affected_days=2,
        narrative="Latency far above the label",
        measured_latency_ms=90,
    )
    inquiry = create_regulator_inquiry(
        complaint["id"], response_due_at="2026-09-30T00:00:00Z"
    )

    taken_plan_code = env.plan["plan_code"]
    malformed_and_duplicated = {
        "plan_code": taken_plan_code,
        "display_name": "Duplicate code and missing price",
        "technology": env.plan["technology"],
        "advertised_download_mbps": 300,
        "advertised_upload_mbps": 140,
        "early_termination_fee_cents": 0,
        "required_locales": ["en-US"],
    }
    both_wrong = api_client.create_service_plan(
        malformed_and_duplicated, COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(both_wrong, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    well_formed_duplicate = dict(
        malformed_and_duplicated,
        display_name="Duplicate code only",
        monthly_price_cents=7999,
    )
    duplicate_only = api_client.create_service_plan(
        well_formed_duplicate, COMPLIANCE_OFFICER_HEADERS
    )
    validate_error(duplicate_only, ApiErrorId.ERR_DUPLICATE_PLAN_CODE.value, 409)

    duplicate_docket = api_client.create_regulator_inquiry(
        build_regulator_inquiry_payload(
            complaint["id"],
            response_due_at="2026-10-15T00:00:00Z",
            docket_number=inquiry["docket_number"],
        ),
        REGULATORY_LIAISON_HEADERS,
    )
    validate_error(
        duplicate_docket, ApiErrorId.ERR_DUPLICATE_DOCKET_NUMBER.value, 409
    )

    duplicate_fee_code = api_client.add_fee_line_item(
        env.plan_id,
        build_fixed_fee_payload(
            "EQUIP_RENTAL", 100, description="Second equipment rental line"
        ),
        COMPLIANCE_OFFICER_HEADERS,
    )
    validate_error(duplicate_fee_code, ApiErrorId.ERR_INVALID_REQUEST.value)
    _, fee_meta = validate_paginated(
        api_client.list_fee_line_items(env.plan_id, COMPLIANCE_OFFICER_HEADERS)
    )
    assert fee_meta["total_count"] == REFERENCE_FEE_LINE_COUNT, (
        "the refused line was not added; a fee code is unique among that plan's lines"
    )

    duplicate_account_code = api_client.create_subscriber_account(
        build_subscriber_account_payload(
            env.plan_id, REFERENCE_NOW, account_code=env.account["account_code"]
        ),
        RETAIL_AGENT_HEADERS,
    )
    validate_error(duplicate_account_code, ApiErrorId.ERR_INVALID_REQUEST.value)

    duplicate_probe_code = api_client.create_measurement_probe(
        build_measurement_probe_payload(probe_code=env.probe["probe_code"]),
        NETWORK_ENGINEER_HEADERS,
    )
    validate_error(duplicate_probe_code, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api_client.list_regulator_inquiries(
            REGULATORY_LIAISON_HEADERS, params={"complaint_id": complaint["id"]}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == inquiry["id"]


def test_upholding_a_zero_shortfall_complaint_rejected():
    """A fee dispute assesses to a zero shortfall and can only be dismissed.

    PRD: "For a `FEE_MISMATCH` — a pricing dispute that carries no speed shortfall
    by definition — the ratio is exactly zero."
    PRD: "Upholding additionally requires the assessed `severity` not to be
    `NONE`, so that no credit is ever issued against a zero shortfall; a
    zero-shortfall uphold answers `ERR_SHORTFALL_NOT_SUBSTANTIATED`."

    Design: Corner/validations/upholding_a_zero_shortfall_complaint_rejected
    """
    env = build_reference_environment()
    complaint = file_complaint(
        env.account_id,
        env.label_id,
        service_observed_date=OBSERVED_INSIDE_WINDOW,
        headers=make_subscriber_headers(env.account_id),
        allegation_type=AllegationType.FEE_MISMATCH.value,
        affected_days=30,
        narrative="Bill does not match the itemized label",
    )
    triage_complaint(complaint["id"])
    investigate_complaint(complaint["id"])

    assessed = read_complaint(complaint["id"])
    assert assessed["shortfall_ratio"] == pytest.approx(0.0, abs=0.0001), (
        "a fee dispute carries no speed shortfall however many days are claimed"
    )
    assert assessed["severity"] == ComplaintSeverity.NONE.value

    refused = api_client.resolve_complaint(
        complaint["id"],
        build_uphold_payload(
            credit_basis=CreditBasis.FLAT_SEVERITY_TIER.value,
            resolution_note="Agent agrees with the consumer",
        ),
        COMPLAINT_ANALYST_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_SHORTFALL_NOT_SUBSTANTIATED.value, 422)

    assert (
        read_complaint(complaint["id"])["state"]
        == ComplaintState.UNDER_INVESTIGATION.value
    ), "the refused resolution drove no transition"
    _, credit_meta = validate_paginated(
        api_client.list_complaint_remediation_credits(
            complaint["id"], COMPLAINT_ANALYST_HEADERS
        )
    )
    assert credit_meta["total_count"] == 0, "no credit is issued against a zero shortfall"

    dismissed = validate_success(
        api_client.resolve_complaint(
            complaint["id"],
            build_dismiss_payload(resolution_note="Itemization matches the bill"),
            COMPLAINT_ANALYST_HEADERS,
        )
    )
    assert dismissed["state"] == ComplaintState.DISMISSED.value
    assert dismissed["resolution"] == ComplaintResolution.DISMISSED.value

    assert_account_ledger(read_subscriber_account(env.account_id), 0, 0)
    plan = read_service_plan(env.plan_id)
    assert plan["upheld_complaint_count"] == 0, "a dismissal does not move the count"
    assert_posture(plan, LabelPosture.OPEN.value)


def test_sample_outside_the_run_window_rejected():
    """One sample a minute past the window sinks the whole run.

    PRD: "Then the run's own shape: the span from `window_start` to `window_end`
    must not exceed the cited document's `max_run_duration_days` days, or the
    request answers `ERR_RUN_DURATION_EXCEEDED`, and every sample's `observed_at`
    must fall inside the closed interval from `window_start` to `window_end`
    inclusive, or it answers `ERR_SAMPLE_OUTSIDE_WINDOW`."
    PRD: "Recording a run recomputes the plan's `evidence_sample_total` as the sum
    of `sample_count` over that plan's runs whose `status` is `INCLUDED`, and
    increments the plan's `version`."

    Design: Corner/validations/sample_outside_the_run_window_rejected
    """
    set_clock(REFERENCE_NOW)
    plan = create_reference_plan()
    methodology = create_published_methodology()
    probe = create_measurement_probe()
    record_test_run(probe["id"], plan["id"], methodology["id"])
    assert_evidence_sample_total(read_service_plan(plan["id"]), 6)

    window_start = "2026-08-11T00:00:00Z"
    window_end = "2026-08-12T00:00:00Z"
    inside_sample = build_sample("2026-08-11T19:10:00Z", 244, 116, 26)

    a_minute_late = api_client.create_test_run(
        build_test_run_payload(
            probe["id"],
            plan["id"],
            methodology["id"],
            window_start=window_start,
            window_end=window_end,
            samples=[
                inside_sample,
                build_sample("2026-08-12T00:01:00Z", 240, 114, 28),
            ],
        ),
        NETWORK_ENGINEER_HEADERS,
    )
    validate_error(a_minute_late, ApiErrorId.ERR_SAMPLE_OUTSIDE_WINDOW.value, 422)

    _, run_meta = validate_paginated(
        api_client.list_test_runs(
            NETWORK_ENGINEER_HEADERS, params={"plan_id": plan["id"]}
        )
    )
    assert run_meta["total_count"] == 1, "the refused batch persisted no run"
    assert_evidence_sample_total(read_service_plan(plan["id"]), 6)

    on_the_boundary = api_client.create_test_run(
        build_test_run_payload(
            probe["id"],
            plan["id"],
            methodology["id"],
            window_start=window_start,
            window_end=window_end,
            samples=[
                inside_sample,
                build_sample(window_end, 240, 114, 28),
            ],
        ),
        NETWORK_ENGINEER_HEADERS,
    )
    accepted_run = validate_success(on_the_boundary, expected_status=201)
    assert accepted_run["sample_count"] == 2, (
        "an observation at exactly window_end is inside the closed interval"
    )
    assert accepted_run["status"] == TestRunStatus.INCLUDED.value
    assert_evidence_sample_total(read_service_plan(plan["id"]), 8)
