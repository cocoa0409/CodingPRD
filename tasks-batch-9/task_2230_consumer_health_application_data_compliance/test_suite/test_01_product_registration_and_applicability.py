"""Product registration, amendment, and the applicability determination.

Covers the four-step applicability computation whose evaluation order is pinned,
the product posture defaults written at registration, the derived compliance
summary read, the bounded return/revise loop on an assessment, the active
inventory prerequisite on submission, and the role gates on the assessment
workflow.
"""

from __future__ import annotations

from test_helpers import (
    ApiClient,
    ApiErrorId,
    ROLE_PLATFORM_ADMIN,
    assert_app_product,
    assert_applicability_assessment,
    assert_compliance_summary,
    assess_breach,
    create_app_product_payload,
    create_applicability_assessment_payload,
    create_assessment,
    create_breach,
    create_consumer,
    create_element,
    create_product,
    file_request,
    get_success_data,
    grant_axes,
    make_compliance_approver_headers,
    make_data_steward_headers,
    make_platform_admin_headers,
    make_privacy_officer_headers,
    open_consent_record,
    read_product,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# The pinned four-step applicability determination
# ---------------------------------------------------------------------------


def test_submission_derives_dual_track_then_partial_scope_from_the_frozen_snapshots(
    api: ApiClient,
) -> None:
    """A covered claim at ratio 0.60 lands on DUAL_TRACK, and only then is scope derived.

    PRD §3.1: "Then the track: if the operator claims to be a `COVERED_ENTITY` or a
    `BUSINESS_ASSOCIATE` and its `hipaa_covered_transaction_ratio` is at least 0.95, the
    `determination` is `HIPAA_ONLY`; otherwise, if it makes one of those two claims and the
    ratio is at least 0.50, the `determination` is `DUAL_TRACK`; in every remaining case —
    including any claim of `NOT_COVERED` regardless of ratio, and a covered claim with a
    ratio below 0.50 — the `determination` is `CHD_REGULATED`."

    PRD §3.1: "Otherwise, if `regulated_element_count_snapshot` is at least the value
    obtained by taking half of `active_element_count_snapshot` and rounding up to the next
    whole number, the `regulated_scope` is `FULL`."

    PRD §3.1: "In the remaining case the `regulated_scope` is `PARTIAL`."

    PRD §3.1: "The `small_business_flag` is set to true when the product processes fewer
    than one hundred thousand consumers per year *and* its prior-year revenue is under
    twenty-five million dollars — that is, `consumer_count` strictly below 100000 and
    `annual_revenue_cents` strictly below 2500000000 — and false otherwise."

    Design: Difficulty/combinatorial_formula/applicability_determination_pinned_step_order_dual_track_partial_scope
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(
        api,
        product_name="CareBridge",
        company_legal_name="CareBridge Health LLC",
        primary_state_code="CA",
        consumer_count=150000,
        annual_revenue_cents=3000000000,
        hipaa_covered_transaction_ratio=0.60,
    )
    create_element(
        product["id"],
        api,
        element_key="dx_code",
        display_name="Diagnosis code",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    for key, label in (
        ("display_name_pref", "Display name"),
        ("locale", "Locale preference"),
    ):
        create_element(
            product["id"],
            api,
            element_key=key,
            display_name=label,
            source_kind="USER_PROVIDED",
            health_signal_kind="NON_HEALTH",
        )
    create_element(
        product["id"],
        api,
        element_key="device_model",
        display_name="Device model",
        source_kind="DEVICE_SENSOR",
        health_signal_kind="NON_HEALTH",
    )
    assessment = create_assessment(
        product["id"],
        api,
        entity_status_claim="COVERED_ENTITY",
        analyst_note="Mixed clinical and consumer flows",
    )

    response = api.submit_applicability_assessment(
        assessment["id"], make_privacy_officer_headers("po-1")
    )
    submitted = validate_success(response)
    assert_applicability_assessment(submitted)

    assert submitted["state"] == "SUBMITTED"
    assert submitted["determination"] == "DUAL_TRACK"
    assert submitted["active_element_count_snapshot"] == 4
    assert submitted["regulated_element_count_snapshot"] == 1
    assert submitted["regulated_scope"] == "PARTIAL"
    assert submitted["compliance_deadline_date"] == "2026-03-31"

    refreshed = read_product(product["id"], api)
    assert refreshed["small_business_flag"] is False
    assert refreshed["applicability_status"] == "UNDETERMINED"


def test_hipaa_only_determination_freezes_the_snapshots_but_leaves_scope_none(
    api: ApiClient,
) -> None:
    """A covered claim at ratio 0.98 yields HIPAA_ONLY with no scope and no deadline.

    PRD §3.1: "Both snapshots are frozen even when the `determination` came out as
    `HIPAA_ONLY`, so that a later re-analysis can see what the inventory looked like."

    PRD §3.1: "If the `determination` is `HIPAA_ONLY`, the `regulated_scope` is `NONE` and
    `compliance_deadline_date` is null."

    Design: Difficulty/combinatorial_formula/applicability_determination_pinned_step_order_dual_track_partial_scope
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(
        api,
        product_name="CareBridge",
        company_legal_name="CareBridge Health LLC",
        primary_state_code="CA",
        consumer_count=150000,
        annual_revenue_cents=3000000000,
        hipaa_covered_transaction_ratio=0.98,
    )
    create_element(
        product["id"],
        api,
        element_key="dx_code",
        display_name="Diagnosis code",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    create_element(
        product["id"],
        api,
        element_key="device_model",
        display_name="Device model",
        source_kind="DEVICE_SENSOR",
        health_signal_kind="NON_HEALTH",
    )
    assessment = create_assessment(
        product["id"],
        api,
        entity_status_claim="COVERED_ENTITY",
        analyst_note="Almost every flow is a covered transaction",
    )

    response = api.submit_applicability_assessment(
        assessment["id"], make_privacy_officer_headers("po-1")
    )
    submitted = validate_success(response)

    assert submitted["determination"] == "HIPAA_ONLY"
    assert submitted["active_element_count_snapshot"] == 2
    assert submitted["regulated_element_count_snapshot"] == 1
    assert submitted["regulated_scope"] == "NONE"
    assert submitted["compliance_deadline_date"] is None


def test_regulated_majority_rounded_up_yields_full_scope_on_an_odd_inventory(
    api: ApiClient,
) -> None:
    """Two regulated elements out of three active ones clear the rounded-up half.

    PRD §3.1: "Otherwise, if `regulated_element_count_snapshot` is at least the value
    obtained by taking half of `active_element_count_snapshot` and rounding up to the next
    whole number, the `regulated_scope` is `FULL`."

    PRD §3.1: "Whenever the `determination` is anything other than `HIPAA_ONLY`, the
    deadline is set as well: a product whose `small_business_flag` is true gets the
    small-business deadline of `2026-06-30`, and every other product gets the standard
    deadline of `2026-03-31`."

    Design: Difficulty/combinatorial_formula/applicability_determination_pinned_step_order_dual_track_partial_scope
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api, consumer_count=40000, annual_revenue_cents=900000000)
    create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    create_element(
        product["id"],
        api,
        element_key="resting_heart_rate",
        display_name="Resting heart rate",
        source_kind="DEVICE_SENSOR",
        health_signal_kind="MEASUREMENT",
    )
    create_element(
        product["id"],
        api,
        element_key="app_theme",
        display_name="App theme preference",
        source_kind="USER_PROVIDED",
        health_signal_kind="NON_HEALTH",
    )
    assessment = create_assessment(
        product["id"],
        api,
        entity_status_claim="NOT_COVERED",
        analyst_note="Consumer wellness app with two health signals",
    )

    response = api.submit_applicability_assessment(
        assessment["id"], make_privacy_officer_headers("po-1")
    )
    submitted = validate_success(response)

    assert submitted["determination"] == "CHD_REGULATED"
    assert submitted["active_element_count_snapshot"] == 3
    assert submitted["regulated_element_count_snapshot"] == 2
    assert submitted["regulated_scope"] == "FULL"
    assert submitted["compliance_deadline_date"] == "2026-06-30"

    refreshed = read_product(product["id"], api)
    assert refreshed["small_business_flag"] is True


# ---------------------------------------------------------------------------
# Registration, amendment and the derived posture reads
# ---------------------------------------------------------------------------


def test_registering_a_product_returns_its_declared_posture_defaults(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """Registration answers 201 with every derived posture field at its declared default.

    PRD §4: "Operations that bring a new resource into existence return `201 Created`."

    PRD §3.1: "The product begins life with `applicability_status` at `UNDETERMINED`,
    `regulated_scope` at `NONE`, `policy_compliance_state` at `NO_POLICY`,
    `security_program_state` at `NONE`, a null `compliance_deadline_date`, and every
    counter at zero."

    PRD §3.1: "The `small_business_flag` is set to true when the product processes fewer
    than one hundred thousand consumers per year *and* its prior-year revenue is under
    twenty-five million dollars — that is, `consumer_count` strictly below 100000 and
    `annual_revenue_cents` strictly below 2500000000 — and false otherwise."

    Design: Corner/entities/creation_app_product_returns_envelope_and_computed_defaults
    """
    response = api.create_app_product(
        create_app_product_payload(
            product_name="SleepSense",
            company_legal_name="SleepSense Inc",
            primary_state_code="WA",
            consumer_count=40000,
            annual_revenue_cents=900000000,
            hipaa_covered_transaction_ratio=0.10,
        ),
        make_platform_admin_headers(),
    )
    product = validate_success(response, 201)
    assert_app_product(product)

    assert product["small_business_flag"] is True
    assert product["applicability_status"] == "UNDETERMINED"
    assert product["regulated_scope"] == "NONE"
    assert product["active_element_count"] == 0
    assert product["regulated_element_count"] == 0
    assert product["active_share_consent_count"] == 0
    assert product["exposure_cents"] == 0
    assert product["policy_compliance_state"] == "NO_POLICY"
    assert product["security_program_state"] == "NONE"
    assert product["compliance_deadline_date"] is None
    assert product["version"] == 1


def test_amending_the_consumer_count_reflips_the_small_business_flag_and_bumps_version(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """Raising consumer_count past the threshold recomputes the flag and bumps the version.

    PRD §3.1: "The size and ratio inputs — along with `product_name` — remain amendable by
    a `PlatformAdmin` afterwards, and each amendment recomputes `small_business_flag` and
    bumps the product's `version`."

    PRD §3.1: "The `small_business_flag` is set to true when the product processes fewer
    than one hundred thousand consumers per year *and* its prior-year revenue is under
    twenty-five million dollars — that is, `consumer_count` strictly below 100000 and
    `annual_revenue_cents` strictly below 2500000000 — and false otherwise."

    Design: Corner/endpoints/standard_crud_patch_app_product_bumps_version_and_reflips_small_business_flag
    """
    product = create_product(
        api,
        product_name="SleepSense",
        company_legal_name="SleepSense Inc",
        primary_state_code="WA",
        consumer_count=40000,
        annual_revenue_cents=900000000,
        hipaa_covered_transaction_ratio=0.10,
    )
    assert product["small_business_flag"] is True
    assert product["version"] == 1

    response = api.update_app_product(
        product["id"], {"consumer_count": 150000}, make_platform_admin_headers()
    )
    amended = validate_success(response)
    assert_app_product(amended)

    assert amended["consumer_count"] == 150000
    assert amended["small_business_flag"] is False
    assert amended["annual_revenue_cents"] == 900000000
    assert amended["company_legal_name"] == "SleepSense Inc"
    assert amended["version"] == 2


def test_compliance_summary_reports_the_live_derived_counters(api: ApiClient) -> None:
    """The summary read recomputes every counter from live state.

    PRD §2.11: "A convenience read exposes the whole posture in one shape:
    `app_product_id`, `applicability_status`, `regulated_scope`, `active_element_count`,
    `regulated_element_count`, `active_share_consent_count`, `policy_compliance_state`,
    `security_program_state`, `exposure_cents`, plus two counts computed on demand —
    `open_request_count`, the number of rights requests belonging to the product's
    consumers whose `state` is neither `FULFILLED` nor `DENIED`, and
    `outstanding_deletion_task_count`, the number of deletion tasks under those requests
    whose `state` is `PENDING`, `NOTIFIED` or `FAILED`."

    PRD §3.9: "And `exposure_contribution_cents` becomes `affected_consumer_count`
    multiplied by twelve dollars per exposed consumer, which is 1200 cents each; that
    amount is added to the product's `exposure_cents` by exactly that much."

    Design: Corner/endpoints/computed_read_compliance_summary_matches_the_derived_counters
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    create_element(
        product["id"],
        api,
        element_key="app_theme",
        display_name="App theme preference",
        source_kind="USER_PROVIDED",
        health_signal_kind="NON_HEALTH",
    )
    consumer = create_consumer(product["id"], api, external_ref="acct-1")
    record = open_consent_record(consumer["id"], api)
    grant_axes(record["id"], consumer["id"], ["COLLECT"], api)
    grant_axes(record["id"], consumer["id"], ["SHARE"], api)
    file_request(
        consumer["id"], api, request_kind="ACCESS", submitted_channel="WEB_FORM"
    )
    incident = create_breach(
        product["id"],
        api,
        incident_label="Vendor log exposure",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=200,
        affected_state_max_count=120,
    )
    assess_breach(incident["id"], api)

    response = api.get_compliance_summary(
        product["id"], make_compliance_approver_headers()
    )
    summary = validate_success(response)
    assert_compliance_summary(summary)

    assert summary["app_product_id"] == product["id"]
    assert summary["applicability_status"] == "UNDETERMINED"
    assert summary["regulated_scope"] == "NONE"
    assert summary["active_element_count"] == 2
    assert summary["regulated_element_count"] == 1
    assert summary["active_share_consent_count"] == 1
    assert summary["policy_compliance_state"] == "NO_POLICY"
    assert summary["security_program_state"] == "NONE"
    assert summary["exposure_cents"] == 240000
    assert summary["open_request_count"] == 1
    assert summary["outstanding_deletion_task_count"] == 0


# ---------------------------------------------------------------------------
# Threshold and re-determination behaviour on approval
# ---------------------------------------------------------------------------


def test_consumer_count_exactly_at_the_threshold_takes_the_standard_deadline(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """A product at exactly 100000 consumers is not a small business.

    PRD §3.1: "The `small_business_flag` is set to true when the product processes fewer
    than one hundred thousand consumers per year *and* its prior-year revenue is under
    twenty-five million dollars — that is, `consumer_count` strictly below 100000 and
    `annual_revenue_cents` strictly below 2500000000 — and false otherwise."

    PRD §3.1: "Whenever the `determination` is anything other than `HIPAA_ONLY`, the
    deadline is set as well: a product whose `small_business_flag` is true gets the
    small-business deadline of `2026-06-30`, and every other product gets the standard
    deadline of `2026-03-31`."

    PRD §3.1: "Approval, admitted only from `SUBMITTED` and only when the approver's
    `X-User-ID` differs from the recorded `submitted_by_user_id`, advances it
    `SUBMITTED → APPROVED`, stamps `approved_by_user_id` with the approver's `X-User-ID`,
    and copies the determination onto the product: the product's `applicability_status`
    becomes the assessment's `determination`, its `regulated_scope` becomes the
    assessment's `regulated_scope`, and its `compliance_deadline_date` becomes the
    assessment's `compliance_deadline_date`."

    Design: Corner/calculations/constants_applied_consumer_count_exactly_at_small_business_max_uses_standard_deadline
    """
    product = create_product(
        api, consumer_count=100000, annual_revenue_cents=2400000000
    )
    create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    assessment = create_assessment(
        product["id"],
        api,
        entity_status_claim="NOT_COVERED",
        analyst_note="Consumer wellness app, no covered transactions",
    )
    get_success_data(
        api.submit_applicability_assessment(
            assessment["id"], make_privacy_officer_headers("po-1")
        )
    )

    response = api.approve_applicability_assessment(
        assessment["id"], make_compliance_approver_headers("ca-1")
    )
    approved = validate_success(response)
    assert approved["state"] == "APPROVED"

    refreshed = read_product(product["id"], api)
    assert refreshed["small_business_flag"] is False
    assert refreshed["applicability_status"] == "CHD_REGULATED"
    assert refreshed["regulated_scope"] == "FULL"
    assert refreshed["compliance_deadline_date"] == "2026-03-31"


def test_second_approval_redetermines_the_scope_from_full_to_partial(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """A grown non-health inventory drops the product's scope from FULL to PARTIAL.

    PRD §3.1: "Otherwise, if `regulated_element_count_snapshot` is at least the value
    obtained by taking half of `active_element_count_snapshot` and rounding up to the next
    whole number, the `regulated_scope` is `FULL`."

    PRD §3.1: "In the remaining case the `regulated_scope` is `PARTIAL`."

    PRD §3.1: "Approval, admitted only from `SUBMITTED` and only when the approver's
    `X-User-ID` differs from the recorded `submitted_by_user_id`, advances it
    `SUBMITTED → APPROVED`, stamps `approved_by_user_id` with the approver's `X-User-ID`,
    and copies the determination onto the product: the product's `applicability_status`
    becomes the assessment's `determination`, its `regulated_scope` becomes the
    assessment's `regulated_scope`, and its `compliance_deadline_date` becomes the
    assessment's `compliance_deadline_date`."

    Design: Corner/calculations/constraint_propagation_regulated_scope_redetermined_from_full_to_partial
    """
    product = create_product(api, consumer_count=40000, annual_revenue_cents=900000000)
    create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    create_element(
        product["id"],
        api,
        element_key="device_model",
        display_name="Device model",
        source_kind="DEVICE_SENSOR",
        health_signal_kind="NON_HEALTH",
    )
    first = create_assessment(
        product["id"],
        api,
        entity_status_claim="NOT_COVERED",
        analyst_note="First pass over the data map",
    )
    get_success_data(
        api.submit_applicability_assessment(
            first["id"], make_privacy_officer_headers("po-1")
        )
    )
    get_success_data(
        api.approve_applicability_assessment(
            first["id"], make_compliance_approver_headers("ca-1")
        )
    )
    assert read_product(product["id"], api)["regulated_scope"] == "FULL"

    for key, label in (
        ("app_theme", "App theme preference"),
        ("push_token", "Push notification token"),
    ):
        create_element(
            product["id"],
            api,
            element_key=key,
            display_name=label,
            source_kind="USER_PROVIDED",
            health_signal_kind="NON_HEALTH",
        )
    second = create_assessment(
        product["id"],
        api,
        entity_status_claim="NOT_COVERED",
        analyst_note="Second pass after the data map grew",
    )
    get_success_data(
        api.submit_applicability_assessment(
            second["id"], make_privacy_officer_headers("po-1")
        )
    )

    response = api.approve_applicability_assessment(
        second["id"], make_compliance_approver_headers("ca-1")
    )
    approved = validate_success(response)
    assert approved["state"] == "APPROVED"

    refreshed = read_product(product["id"], api)
    assert refreshed["active_element_count"] == 4
    assert refreshed["regulated_element_count"] == 1
    assert refreshed["applicability_status"] == "CHD_REGULATED"
    assert refreshed["regulated_scope"] == "PARTIAL"
    assert refreshed["compliance_deadline_date"] == "2026-06-30"


# ---------------------------------------------------------------------------
# The bounded return/revise loop and the active-inventory prerequisite
# ---------------------------------------------------------------------------


def test_third_reopening_of_a_returned_assessment_is_refused(api: ApiClient) -> None:
    """The return/revise loop is bounded at two revisions.

    PRD §3.1: "This `RETURNED → DRAFT → SUBMITTED → RETURNED` loop is bounded: reopening is
    admitted only while `revision_count` is strictly below two, and the third attempt is
    refused with `ERR_ASSESSMENT_REVISION_LIMIT`."

    PRD §3.1: "Returning the assessment, also admitted only from `SUBMITTED`, moves it
    `SUBMITTED → RETURNED` and records the approver's `return_reason` from the request
    body."

    Design: Corner/state_machines/cyclic_shape_assessment_return_revise_loop_bounded_at_two_revisions
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    assessment = create_assessment(
        product["id"],
        api,
        entity_status_claim="NOT_COVERED",
        analyst_note="Consumer wellness app",
    )

    for reason in (
        "Restate the covered-entity analysis",
        "Cite the transaction ratio source",
        "Still unclear",
    ):
        get_success_data(
            api.submit_applicability_assessment(
                assessment["id"], make_privacy_officer_headers("po-1")
            )
        )
        get_success_data(
            api.return_applicability_assessment(
                assessment["id"],
                {"return_reason": reason},
                make_compliance_approver_headers("ca-1"),
            )
        )
        if reason != "Still unclear":
            get_success_data(
                api.revise_applicability_assessment(
                    assessment["id"], make_privacy_officer_headers("po-1")
                )
            )

    response = api.revise_applicability_assessment(
        assessment["id"], make_privacy_officer_headers("po-1")
    )
    validate_error(response, ApiErrorId.ASSESSMENT_REVISION_LIMIT.value)

    current = validate_success(
        api.get_applicability_assessment(
            assessment["id"], make_privacy_officer_headers()
        )
    )
    assert current["state"] == "RETURNED"
    assert current["revision_count"] == 2
    assert current["return_reason"] == "Still unclear"


def test_submitting_with_only_a_retired_element_is_refused(api: ApiClient) -> None:
    """A product whose only element is retired has nothing to analyse.

    PRD §3.1: "Submission is admitted only from `DRAFT`, and only if the product has at
    least one data element whose `status` is `ACTIVE` — a product with an empty live
    inventory has nothing to analyse, and the attempt is refused with
    `ERR_NO_ACTIVE_ELEMENTS`."

    Design: Corner/validations/aggregate_validation_submit_with_no_active_elements_rejected
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    element = create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    get_success_data(
        api.retire_data_element(
            element["id"],
            {"retired_reason": "Feature removed before launch"},
            make_data_steward_headers(),
        )
    )
    assessment = create_assessment(
        product["id"],
        api,
        entity_status_claim="NOT_COVERED",
        analyst_note="Consumer wellness app",
    )

    response = api.submit_applicability_assessment(
        assessment["id"], make_privacy_officer_headers("po-1")
    )
    validate_error(response, ApiErrorId.NO_ACTIVE_ELEMENTS.value)

    current = validate_success(
        api.get_applicability_assessment(
            assessment["id"], make_privacy_officer_headers()
        )
    )
    assert current["state"] == "DRAFT"
    assert current["submitted_by_user_id"] is None
    assert read_product(product["id"], api)["applicability_status"] == "UNDETERMINED"


# ---------------------------------------------------------------------------
# Role gates on the assessment workflow
# ---------------------------------------------------------------------------


def test_privacy_officer_both_drafts_and_submits_the_assessment(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """The drafting officer submits its own assessment, and its id is recorded.

    PRD §3.1: "Submission stamps `submitted_by_user_id` with the caller's `X-User-ID` and
    refreshes the product's `small_business_flag`."

    PRD §2.9: "Note that the role check comes first: a `PrivacyOfficer` attempting to
    approve its own assessment is stopped by `ERR_UNAUTHORIZED` because approval is
    reserved to `ComplianceApprover`, and the segregation check bites only when a
    `ComplianceApprover` account was also the submitter or author."

    Design: Corner/rbac/role_permissions_privacy_officer_drafts_and_submits_an_assessment
    """
    product = create_product(api)
    create_element(
        product["id"],
        api,
        element_key="apnea_dx",
        display_name="Sleep apnea diagnosis",
        source_kind="USER_PROVIDED",
        health_signal_kind="DIAGNOSIS",
    )
    assessment = validate_success(
        api.create_applicability_assessment(
            create_applicability_assessment_payload(
                product["id"],
                entity_status_claim="NOT_COVERED",
                analyst_note="Consumer wellness app",
            ),
            make_privacy_officer_headers("po-1"),
        ),
        201,
    )

    response = api.submit_applicability_assessment(
        assessment["id"], make_privacy_officer_headers("po-1")
    )
    submitted = validate_success(response)

    assert submitted["state"] == "SUBMITTED"
    assert submitted["submitted_by_user_id"] == "po-1"
    assert read_product(product["id"], api)["applicability_status"] == "UNDETERMINED"


def test_data_steward_cannot_open_an_applicability_assessment(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """Opening an assessment is reserved to the PrivacyOfficer role.

    PRD §2.1: "If the headers are well-formed but the named role is not among the roles the
    target endpoint admits, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §2.7: "Lower-numbered checks therefore mask higher-numbered ones: a caller with the
    wrong role never learns that its payload was also malformed, and a caller acting on a
    policy that is not under review never learns that the policy's completeness score was
    also too low."

    Design: Corner/rbac/data_steward_cannot_create_an_applicability_assessment
    """
    product = create_product(api)

    response = api.create_applicability_assessment(
        create_applicability_assessment_payload(
            product["id"],
            entity_status_claim="NOT_COVERED",
            analyst_note="Consumer wellness app",
        ),
        make_data_steward_headers(),
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED.value)

    listed, meta = validate_paginated(
        api.list_applicability_assessments(
            make_privacy_officer_headers(), {"app_product_id": product["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert listed == []


def test_compliance_approver_cannot_submit_the_assessment_it_would_approve(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """The approver owns approval, not submission, so its submit is unauthorised.

    PRD §2.1: "If the headers are well-formed but the named role is not among the roles the
    target endpoint admits, the rejection is `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD §3.1: "Submission stamps `submitted_by_user_id` with the caller's `X-User-ID` and
    refreshes the product's `small_business_flag`."

    Design: Corner/rbac/compliance_approver_cannot_submit_the_assessment_it_would_approve
    """
    product = create_product(api)
    assessment = validate_success(
        api.create_applicability_assessment(
            create_applicability_assessment_payload(
                product["id"],
                entity_status_claim="NOT_COVERED",
                analyst_note="Consumer wellness app",
            ),
            make_privacy_officer_headers("po-1"),
        ),
        201,
    )

    response = api.submit_applicability_assessment(
        assessment["id"], make_compliance_approver_headers("ca-1")
    )
    validate_error(response, ApiErrorId.UNAUTHORIZED.value)

    current = validate_success(
        api.get_applicability_assessment(
            assessment["id"], make_privacy_officer_headers()
        )
    )
    assert current["state"] == "DRAFT"
    assert current["submitted_by_user_id"] is None


def test_registration_without_the_acting_user_header_is_unauthenticated(
    api: ApiClient,
) -> None:
    """A request carrying only the role header never reaches the body checks.

    PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capacity in which it acts."

    PRD §2.1: "If either header is absent, or if `X-User-Role` names something other than
    one of the six roles below, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/request_without_the_user_id_header_is_unauthorized
    """
    response = api.create_app_product(
        create_app_product_payload(
            product_name="SleepSense",
            company_legal_name="SleepSense Inc",
            primary_state_code="WA",
            consumer_count=40000,
            annual_revenue_cents=900000000,
            hipaa_covered_transaction_ratio=0.10,
        ),
        {"X-User-Role": ROLE_PLATFORM_ADMIN, "Content-Type": "application/json"},
    )
    validate_error(response, ApiErrorId.UNAUTHENTICATED.value)

    listed, meta = validate_paginated(
        api.list_app_products(make_platform_admin_headers())
    )
    assert meta["total_count"] == 0
    assert listed == []
