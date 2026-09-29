"""Privacy policy versions: completeness scoring, review gates and publication.

Every test builds its own product, inventory, purpose catalogue and approved
applicability assessment, because the server is restarted with an empty
database before each test.
"""

from __future__ import annotations

from typing import Any

from test_helpers import (
    ApiClient,
    ApiErrorId,
    USER_COMPLIANCE_APPROVER,
    USER_COMPLIANCE_APPROVER_ALT,
    USER_DUAL_HAT,
    USER_PRIVACY_OFFICER,
    assert_app_product,
    assert_applicability_assessment,
    assert_privacy_policy_version,
    create_approved_assessment,
    create_element,
    create_policy,
    create_product,
    create_published_policy,
    create_purpose,
    create_reviewed_policy,
    create_submitted_assessment,
    factories,
    make_compliance_approver_headers,
    make_platform_admin_headers,
    make_privacy_officer_headers,
    product_version,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_AUGUST_FIFTH = "2026-08-05T00:00:00Z"
CLOCK_AUGUST_FIFTEENTH = "2026-08-15T00:00:00Z"

# One directly collected DIAGNOSIS element, which classifies as CHD.
ONE_REGULATED_ELEMENT = (
    ("apnea_dx", "Sleep apnea diagnosis", "USER_PROVIDED", "DIAGNOSIS"),
)

# Four direct health signals plus one precise-location element, which
# classifies as CHD_BY_INFERENCE, so all five count as regulated.
FIVE_REGULATED_ELEMENTS = (
    ("apnea_dx", "Sleep apnea diagnosis", "USER_PROVIDED", "DIAGNOSIS"),
    ("cpap_use", "CPAP usage hours", "DEVICE_SENSOR", "TREATMENT"),
    ("spo2", "Blood oxygen saturation", "DEVICE_SENSOR", "MEASUREMENT"),
    ("hr_var", "Heart rate variability", "DEVICE_SENSOR", "MEASUREMENT"),
    ("clinic_geo", "Clinic visit location", "DEVICE_SENSOR", "PRECISE_LOCATION"),
)

FOUR_REGULATED_ELEMENTS = (
    ("e1", "Diagnosis one", "USER_PROVIDED", "DIAGNOSIS"),
    ("e2", "Treatment one", "USER_PROVIDED", "TREATMENT"),
    ("e3", "Measurement one", "DEVICE_SENSOR", "MEASUREMENT"),
    ("e4", "Biometric one", "DEVICE_SENSOR", "BIOMETRIC"),
)

ONE_PURPOSE = (
    ("core_service", "Deliver the sleep coaching service", "PRIMARY_SERVICE", "COLLECT"),
)

THREE_PURPOSES = (
    ("p1", "Deliver the service", "PRIMARY_SERVICE", "COLLECT"),
    ("p2", "Product analytics", "ANALYTICS", "COLLECT"),
    ("p3", "Research collaboration", "RESEARCH", "COLLECT"),
)

FOUR_PURPOSES = (
    ("core_service", "Deliver the sleep coaching service", "PRIMARY_SERVICE", "COLLECT"),
    ("product_analytics", "Improve the product", "ANALYTICS", "COLLECT"),
    ("ad_partner_share", "Share with advertising partners", "ADVERTISING", "SHARE"),
    ("data_sale", "Sell de-identified panels", "SALE", "SELL"),
)


def build_scored_product(
    api: ApiClient,
    element_specs: tuple[tuple[str, str, str, str], ...],
    purpose_specs: tuple[tuple[str, str, str, str], ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A product with the given inventory and purposes plus an APPROVED assessment."""
    product = create_product(api)
    for element_key, display_name, source_kind, health_signal_kind in element_specs:
        create_element(
            product["id"],
            api,
            element_key=element_key,
            display_name=display_name,
            source_kind=source_kind,
            health_signal_kind=health_signal_kind,
        )
    for purpose_key, description_text, purpose_kind, activity_kind in purpose_specs:
        create_purpose(
            product["id"],
            api,
            purpose_key=purpose_key,
            description_text=description_text,
            purpose_kind=purpose_kind,
            activity_kind=activity_kind,
        )
    assessment = create_approved_assessment(product["id"], api)
    return product, assessment


def read_policy(policy_id: str, api: ApiClient) -> dict[str, Any]:
    """Read one privacy policy version and assert its documented shape."""
    data = validate_success(
        api.get_privacy_policy_version(policy_id, make_privacy_officer_headers())
    )
    assert_privacy_policy_version(data)
    return data


def read_product_row(app_product_id: str, api: ApiClient) -> dict[str, Any]:
    """Read one app product and assert its documented shape."""
    data = validate_success(
        api.get_app_product(app_product_id, make_platform_admin_headers())
    )
    assert_app_product(data)
    return data


def read_assessment(assessment_id: str, api: ApiClient) -> dict[str, Any]:
    """Read one applicability assessment and assert its documented shape."""
    data = validate_success(
        api.get_applicability_assessment(assessment_id, make_privacy_officer_headers())
    )
    assert_applicability_assessment(data)
    return data


def policy_count_for_product(app_product_id: str, api: ApiClient) -> int:
    """Total number of policy versions recorded against the product."""
    _rows, meta = validate_paginated(
        api.list_privacy_policy_versions(
            make_privacy_officer_headers(), {"app_product_id": app_product_id}
        )
    )
    return int(meta["total_count"])


# ---------------------------------------------------------------------------
# Completeness scoring under the two specificity regimes
# ---------------------------------------------------------------------------


def test_element_level_specificity_scores_against_the_regulated_element_count(
    api: ApiClient,
) -> None:
    """PRD §3.6: "The category denominator is the product's current `regulated_element_count` when the version's `specificity_mode` is `ELEMENT_LEVEL`, and is the fixed statutory count of six categories when the `specificity_mode` is `CATEGORY_LEVEL`."
    PRD §3.6: "The purpose denominator is the number of processing purposes declared on the same product."
    PRD §3.6: "The third-party component is one when `disclosed_third_party_count` is zero, and otherwise the lesser of one and `named_third_party_count` divided by `disclosed_third_party_count`."
    PRD §3.6: "**Step three** sets `gap_count` to the number of those three components that are strictly less than one."
    PRD §3.6: "**Step four** takes the category component weighted at forty per cent, the purpose component weighted at thirty-five per cent, and the third-party component weighted at twenty-five per cent, sums the three weighted values, multiplies by one hundred, and rounds that single result half-up to one decimal place."

    Design: Difficulty/dual_variant_calc/policy_completeness_element_versus_category_specificity_divergence
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(
        api, FIVE_REGULATED_ELEMENTS, FOUR_PURPOSES
    )
    assert read_product_row(product["id"], api)["regulated_element_count"] == 5

    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1-element-level",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=4,
        disclosed_purpose_count=4,
        disclosed_third_party_count=2,
        named_third_party_count=2,
        effective_from="2026-09-01",
    )

    stored = read_policy(policy["id"], api)
    assert stored["state"] == "IN_REVIEW"
    assert stored["completeness_score"] == 92.0
    assert stored["gap_count"] == 1


def test_category_level_specificity_scores_against_the_six_statutory_categories(
    api: ApiClient,
) -> None:
    """PRD §3.6: "The category denominator is the product's current `regulated_element_count` when the version's `specificity_mode` is `ELEMENT_LEVEL`, and is the fixed statutory count of six categories when the `specificity_mode` is `CATEGORY_LEVEL`."
    PRD §3.6: "The category component is one when its denominator is zero, and otherwise the lesser of one and `disclosed_category_count` divided by the category denominator."
    PRD §3.6: "**Step four** takes the category component weighted at forty per cent, the purpose component weighted at thirty-five per cent, and the third-party component weighted at twenty-five per cent, sums the three weighted values, multiplies by one hundred, and rounds that single result half-up to one decimal place."
    PRD §3.6: "There is exactly one rounding step, and it comes after the weighting."
    PRD §3.6: "Under `CATEGORY_LEVEL`, the denominator is the fixed six statutory categories, so an identical `disclosed_category_count` produces a different score than it would under `ELEMENT_LEVEL` whenever the product's `regulated_element_count` differs from six."

    Design: Difficulty/dual_variant_calc/policy_completeness_element_versus_category_specificity_divergence
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(
        api, FIVE_REGULATED_ELEMENTS, FOUR_PURPOSES
    )
    assert read_product_row(product["id"], api)["regulated_element_count"] == 5

    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1-category-level",
        specificity_mode="CATEGORY_LEVEL",
        disclosed_category_count=4,
        disclosed_purpose_count=4,
        disclosed_third_party_count=2,
        named_third_party_count=2,
        effective_from="2026-09-02",
    )

    stored = read_policy(policy["id"], api)
    assert stored["state"] == "IN_REVIEW"
    assert stored["completeness_score"] == 86.7
    assert stored["gap_count"] == 1


# ---------------------------------------------------------------------------
# Segregation of duties against the completeness threshold on publication
# ---------------------------------------------------------------------------


def test_segregation_of_duties_masks_the_completeness_threshold_on_publish(
    api: ApiClient,
) -> None:
    """PRD §2.7: "Lower-numbered checks therefore mask higher-numbered ones: a caller with the wrong role never learns that its payload was also malformed, and a caller acting on a policy that is not under review never learns that the policy's completeness score was also too low."
    PRD §2.9: "Publishing a privacy policy version requires that the publisher's `X-User-ID` differ from the `authored_by_user_id` recorded when the version was drafted."
    PRD §2.9: "Either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.6: "The version's `completeness_score` must be at least 90.0, and a lower score is refused with `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_segregation_of_duties_beats_business_fiscal_threshold_on_publish
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(
        api, FIVE_REGULATED_ELEMENTS, FOUR_PURPOSES
    )
    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        author=USER_DUAL_HAT,
        version_label="v1-thin",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=3,
        disclosed_purpose_count=4,
        disclosed_third_party_count=2,
        named_third_party_count=2,
        effective_from="2026-09-01",
    )
    assert policy["completeness_score"] == 84.0

    response = api.publish_privacy_policy_version(
        policy["id"], make_compliance_approver_headers(USER_DUAL_HAT)
    )

    validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES.value)
    stored = read_policy(policy["id"], api)
    assert stored["state"] == "IN_REVIEW"
    assert stored["completeness_score"] == 84.0
    assert stored["published_by_user_id"] is None
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "NO_POLICY"


def test_completeness_threshold_bites_once_the_publisher_is_not_the_author(
    api: ApiClient,
) -> None:
    """PRD §3.6: "The version's `completeness_score` must be at least 90.0, and a lower score is refused with `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`."
    PRD §3.6: "The publisher's `X-User-ID` must differ from the recorded `authored_by_user_id`."
    PRD §2.7: "Checks are evaluated in the order below and the first failure short-circuits the request."

    Design: Difficulty/priority_pair_validation_conflict/business_constraint_segregation_of_duties_beats_business_fiscal_threshold_on_publish
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(
        api, FIVE_REGULATED_ELEMENTS, FOUR_PURPOSES
    )
    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        author=USER_DUAL_HAT,
        version_label="v1-thin",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=3,
        disclosed_purpose_count=4,
        disclosed_third_party_count=2,
        named_third_party_count=2,
        effective_from="2026-09-01",
    )
    assert policy["completeness_score"] == 84.0

    response = api.publish_privacy_policy_version(
        policy["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
    )

    validate_error(response, ApiErrorId.POLICY_COMPLETENESS_BELOW_THRESHOLD.value)
    stored = read_policy(policy["id"], api)
    assert stored["state"] == "IN_REVIEW"
    assert stored["completeness_score"] == 84.0
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "NO_POLICY"


# ---------------------------------------------------------------------------
# Submit-for-review depends on the referenced assessment's state
# ---------------------------------------------------------------------------


def test_submit_for_review_refused_while_the_assessment_is_only_submitted(
    api: ApiClient,
) -> None:
    """PRD §3.6: "Submitting the draft for review moves it `DRAFT → IN_REVIEW` and is admitted only when the referenced applicability assessment currently has `state` `APPROVED`; drafting against an assessment that has not cleared review, or that has since been superseded, is refused with `ERR_ASSESSMENT_NOT_APPROVED`."
    PRD §3.6: "A version is created in `DRAFT` with `completeness_score` at 0.0, `gap_count` at 0, `effective_to` null, `published_by_user_id` null, and `authored_by_user_id` stamped with the drafting officer's `X-User-ID`."

    Design: Difficulty/cross_entity_state_dependency/policy_submit_review_requires_approved_applicability_assessment
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product = create_product(api)
    create_element(product["id"], api, element_key="apnea_dx")
    create_purpose(product["id"], api, purpose_key="core_service")
    assessment = create_submitted_assessment(product["id"], api)
    assert assessment["state"] == "SUBMITTED"

    policy = create_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-09-01",
    )

    response = api.submit_policy_review(
        policy["id"], make_privacy_officer_headers(USER_PRIVACY_OFFICER)
    )

    validate_error(response, ApiErrorId.ASSESSMENT_NOT_APPROVED.value)
    assert read_assessment(assessment["id"], api)["state"] == "SUBMITTED"
    stored = read_policy(policy["id"], api)
    assert stored["state"] == "DRAFT"
    assert stored["completeness_score"] == 0.0
    assert stored["gap_count"] == 0


def test_submit_for_review_refused_once_the_assessment_has_been_superseded(
    api: ApiClient,
) -> None:
    """PRD §3.6: "Submitting the draft for review moves it `DRAFT → IN_REVIEW` and is admitted only when the referenced applicability assessment currently has `state` `APPROVED`; drafting against an assessment that has not cleared review, or that has since been superseded, is refused with `ERR_ASSESSMENT_NOT_APPROVED`."
    PRD §3.1: "Any other assessment on the same product that was itself sitting in `APPROVED` is moved `APPROVED → SUPERSEDED`; that supersession changes no product field, because the approving assessment has already rewritten them all."

    Design: Difficulty/cross_entity_state_dependency/policy_submit_review_requires_approved_applicability_assessment
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product = create_product(api)
    create_element(product["id"], api, element_key="apnea_dx")
    create_purpose(product["id"], api, purpose_key="core_service")
    first_assessment = create_approved_assessment(product["id"], api)

    policy = create_policy(
        product["id"],
        first_assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-09-01",
    )

    create_approved_assessment(product["id"], api)
    assert read_assessment(first_assessment["id"], api)["state"] == "SUPERSEDED"

    response = api.submit_policy_review(
        policy["id"], make_privacy_officer_headers(USER_PRIVACY_OFFICER)
    )

    validate_error(response, ApiErrorId.ASSESSMENT_NOT_APPROVED.value)
    stored = read_policy(policy["id"], api)
    assert stored["state"] == "DRAFT"
    assert stored["completeness_score"] == 0.0


# ---------------------------------------------------------------------------
# Effectivity window disjointness on publication
# ---------------------------------------------------------------------------


def test_publish_refused_when_effective_from_falls_inside_the_published_window(
    api: ApiClient,
) -> None:
    """PRD §3.6: "Finally, `effective_from` must not fall inside the effectivity window of any other policy version on the same product whose `state` is `PUBLISHED`, `SUPERSEDED_PENDING_UPDATE`, or `SUPERSEDED`."
    PRD §3.6: "Each such window runs from that version's `effective_from` inclusive up to its `effective_to` exclusive; a `PUBLISHED` or `SUPERSEDED_PENDING_UPDATE` version has no `effective_to` yet, so its window is treated as running forward without bound."
    PRD §3.6: "Because the upper bound is exclusive, a new `effective_from` falling exactly on a `SUPERSEDED` version's `effective_to` is admitted — the incumbent stopped being effective on that instant — whereas a date strictly inside any window is refused with `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_effective_from_inside_half_open_superseded_window_rejected
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(api, ONE_REGULATED_ELEMENT, ONE_PURPOSE)

    incumbent = create_published_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-09-01",
    )
    assert incumbent["state"] == "PUBLISHED"
    assert incumbent["effective_to"] is None

    candidate = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v2-inside-window",
        effective_from="2026-09-15",
    )
    assert candidate["completeness_score"] == 100.0

    response = api.publish_privacy_policy_version(
        candidate["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
    )

    validate_error(response, ApiErrorId.POLICY_WINDOW_OVERLAP.value)
    assert read_policy(candidate["id"], api)["state"] == "IN_REVIEW"
    stored_incumbent = read_policy(incumbent["id"], api)
    assert stored_incumbent["state"] == "PUBLISHED"
    assert stored_incumbent["effective_to"] is None
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "CURRENT"


def test_publish_refused_when_effective_from_equals_the_incumbent_window_start(
    api: ApiClient,
) -> None:
    """PRD §3.6: "Each such window runs from that version's `effective_from` inclusive up to its `effective_to` exclusive; a `PUBLISHED` or `SUPERSEDED_PENDING_UPDATE` version has no `effective_to` yet, so its window is treated as running forward without bound."
    PRD §3.6: "Because the upper bound is exclusive, a new `effective_from` falling exactly on a `SUPERSEDED` version's `effective_to` is admitted — the incumbent stopped being effective on that instant — whereas a date strictly inside any window is refused with `ERR_POLICY_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/policy_effective_from_inside_half_open_superseded_window_rejected
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(api, ONE_REGULATED_ELEMENT, ONE_PURPOSE)

    incumbent = create_published_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-09-01",
    )
    assert incumbent["state"] == "PUBLISHED"

    candidate = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v2-on-lower-bound",
        effective_from="2026-09-01",
    )
    assert candidate["completeness_score"] == 100.0

    response = api.publish_privacy_policy_version(
        candidate["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
    )

    validate_error(response, ApiErrorId.POLICY_WINDOW_OVERLAP.value)
    assert read_policy(candidate["id"], api)["state"] == "IN_REVIEW"
    assert read_policy(incumbent["id"], api)["state"] == "PUBLISHED"
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "CURRENT"


# ---------------------------------------------------------------------------
# Draft-time shape and concurrency guards
# ---------------------------------------------------------------------------


def test_named_third_party_count_above_the_disclosed_count_is_malformed(
    api: ApiClient,
) -> None:
    """PRD §3.6: "`disclosed_third_party_count` is the number of third-party recipients the text acknowledges, and `named_third_party_count` is how many of those recipients it names individually; the latter may never exceed the former, and a body that breaks that relation is a malformed request."

    Design: Corner/entities/type_constraints_named_third_party_count_above_disclosed_rejected
    """
    product = create_product(api)
    create_element(product["id"], api, element_key="apnea_dx")
    assessment = create_approved_assessment(product["id"], api)

    payload = factories.create_privacy_policy_version_payload(
        product["id"],
        assessment["id"],
        product_version(product["id"], api),
        version_label="v-bad",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=1,
        disclosed_purpose_count=0,
        disclosed_third_party_count=2,
        named_third_party_count=3,
        effective_from="2026-09-01",
    )

    response = api.create_privacy_policy_version(payload, make_privacy_officer_headers())

    validate_error(response, ApiErrorId.INVALID_REQUEST.value)
    assert policy_count_for_product(product["id"], api) == 0


def test_policy_draft_refused_on_a_stale_product_version(api: ApiClient) -> None:
    """PRD §2.8: "Drafting a privacy policy version — `POST /health-data/privacy-policy-versions` — must carry `expected_app_product_version`, a required (never optional) field holding the app product `version` the author last observed."
    PRD §2.8: "If it does not equal the product's current `version`, the request is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412)."
    PRD §2.4: "Approving an applicability assessment, and creating a privacy policy version, each increment the owning app product's `version` by one; amending the product's size or ratio inputs does the same."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_stale_product_version_on_policy_create_rejected
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product = create_product(api)
    stale_product_version = product["version"]
    create_element(product["id"], api, element_key="apnea_dx")
    assessment = create_approved_assessment(product["id"], api)

    payload = factories.create_privacy_policy_version_payload(
        product["id"],
        assessment["id"],
        stale_product_version,
        version_label="v1",
        disclosed_category_count=1,
        disclosed_purpose_count=0,
        disclosed_third_party_count=0,
        named_third_party_count=0,
        effective_from="2026-09-01",
    )

    response = api.create_privacy_policy_version(payload, make_privacy_officer_headers())

    validate_error(response, ApiErrorId.STALE_PRODUCT_VERSION.value)
    assert read_assessment(assessment["id"], api)["state"] == "APPROVED"
    stored_product = read_product_row(product["id"], api)
    assert stored_product["applicability_status"] == "CHD_REGULATED"
    assert stored_product["version"] > stale_product_version
    assert policy_count_for_product(product["id"], api) == 0


# ---------------------------------------------------------------------------
# Publication side effects, compensation, and the remaining publish gates
# ---------------------------------------------------------------------------


def test_publication_supersedes_the_incumbent_and_sets_the_product_current(
    api: ApiClient,
) -> None:
    """PRD §3.6: "A successful publication moves the version `IN_REVIEW → PUBLISHED`, stamps `published_by_user_id` with the publisher's `X-User-ID`, moves every policy version on the same product whose `state` is `PUBLISHED` or `SUPERSEDED_PENDING_UPDATE` to `SUPERSEDED` with its `effective_to` set to the newly published version's `effective_from`, and sets the product's `policy_compliance_state` to `CURRENT`."
    PRD §2.11: "It is `CURRENT` while exactly one privacy policy version for the product sits in `PUBLISHED`."

    Design: Corner/state_machines/side_effect_execution_publish_supersedes_incumbent_and_sets_policy_current
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(api, ONE_REGULATED_ELEMENT, ONE_PURPOSE)

    incumbent = create_published_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-09-20",
    )
    assert incumbent["state"] == "PUBLISHED"

    successor = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v2",
        effective_from="2026-09-01",
    )

    published = validate_success(
        api.publish_privacy_policy_version(
            successor["id"],
            make_compliance_approver_headers(USER_COMPLIANCE_APPROVER_ALT),
        )
    )

    assert_privacy_policy_version(published)
    assert published["state"] == "PUBLISHED"
    assert published["published_by_user_id"] == USER_COMPLIANCE_APPROVER_ALT
    assert published["completeness_score"] == 100.0
    assert published["gap_count"] == 0
    stored_incumbent = read_policy(incumbent["id"], api)
    assert stored_incumbent["state"] == "SUPERSEDED"
    assert stored_incumbent["effective_to"] == "2026-09-01"
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "CURRENT"


def test_return_to_draft_resets_the_completeness_score_and_gap_count(
    api: ApiClient,
) -> None:
    """PRD §3.6: "A `ComplianceApprover` may push a version under review back to the author, moving it `IN_REVIEW → DRAFT` with a `return_reason` in the body; doing so resets `completeness_score` to 0.0 and `gap_count` to 0, so a resubmission always rescores against the inventory as it stands at that later moment."
    PRD §2.11: "It is `NO_POLICY` while no privacy policy version for the product has ever reached `PUBLISHED`."

    Design: Corner/state_machines/compensation_return_to_draft_resets_completeness_score_and_gap_count
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(api, ONE_REGULATED_ELEMENT, ONE_PURPOSE)
    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-09-01",
    )
    assert policy["completeness_score"] == 100.0
    assert policy["gap_count"] == 0

    returned = validate_success(
        api.return_policy_to_draft(
            policy["id"],
            {"return_reason": "Name the advertising recipients explicitly"},
            make_compliance_approver_headers(USER_COMPLIANCE_APPROVER),
        )
    )

    assert_privacy_policy_version(returned)
    assert returned["state"] == "DRAFT"
    assert returned["completeness_score"] == 0.0
    assert returned["gap_count"] == 0
    assert returned["published_by_user_id"] is None
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "NO_POLICY"


def test_publish_admitted_at_exactly_the_completeness_threshold(api: ApiClient) -> None:
    """PRD §3.6: "The version's `completeness_score` must be at least 90.0, and a lower score is refused with `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`."
    PRD §3.6: "**Step three** sets `gap_count` to the number of those three components that are strictly less than one."
    PRD §3.6: "A successful publication moves the version `IN_REVIEW → PUBLISHED`, stamps `published_by_user_id` with the publisher's `X-User-ID`, moves every policy version on the same product whose `state` is `PUBLISHED` or `SUPERSEDED_PENDING_UPDATE` to `SUPERSEDED` with its `effective_to` set to the newly published version's `effective_from`, and sets the product's `policy_compliance_state` to `CURRENT`."

    Design: Corner/validations/satisfaction_to_pass_publish_at_exactly_the_completeness_threshold
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(
        api, FOUR_REGULATED_ELEMENTS, THREE_PURPOSES
    )
    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=3,
        disclosed_purpose_count=3,
        disclosed_third_party_count=2,
        named_third_party_count=2,
        effective_from="2026-09-01",
    )
    assert policy["completeness_score"] == 90.0
    assert policy["gap_count"] == 1

    published = validate_success(
        api.publish_privacy_policy_version(
            policy["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
        )
    )

    assert_privacy_policy_version(published)
    assert published["state"] == "PUBLISHED"
    assert published["completeness_score"] == 90.0
    assert published["gap_count"] == 1
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "CURRENT"


def test_publishing_a_draft_reports_not_in_review_ahead_of_the_threshold(
    api: ApiClient,
) -> None:
    """PRD §2.7: "Lower-numbered checks therefore mask higher-numbered ones: a caller with the wrong role never learns that its payload was also malformed, and a caller acting on a policy that is not under review never learns that the policy's completeness score was also too low."
    PRD §2.7: "A data element action that requires an `ACTIVE` element fails with `ERR_ELEMENT_RETIRED`; a policy publish or return-to-draft on a version not in `IN_REVIEW` fails with `ERR_POLICY_NOT_IN_REVIEW`; a deletion-task notify or reissue whose vendor agreement is not `EXECUTED` fails with `ERR_VENDOR_AGREEMENT_NOT_EXECUTED`; a target already sitting in one of its terminal states fails with `ERR_ALREADY_TERMINAL`; every other from-state mismatch fails with `ERR_INVALID_STATE`."
    PRD §3.6: "The version's `completeness_score` must be at least 90.0, and a lower score is refused with `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`."

    Design: Corner/validations/priority_ordering_state_check_precedes_completeness_check_on_publish
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(api, ONE_REGULATED_ELEMENT, ONE_PURPOSE)
    policy = create_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=0,
        disclosed_purpose_count=0,
        disclosed_third_party_count=0,
        named_third_party_count=0,
        effective_from="2026-09-01",
    )
    assert policy["state"] == "DRAFT"
    assert policy["completeness_score"] == 0.0

    response = api.publish_privacy_policy_version(
        policy["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
    )

    validate_error(response, ApiErrorId.POLICY_NOT_IN_REVIEW.value)
    stored = read_policy(policy["id"], api)
    assert stored["state"] == "DRAFT"
    assert stored["completeness_score"] == 0.0
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "NO_POLICY"


def test_publish_refused_once_the_effective_date_has_passed(api: ApiClient) -> None:
    """PRD §3.6: "The version's `effective_from` must not be earlier than the logical clock's date — publishing a policy that took effect in the past is refused with `ERR_EFFECTIVE_DATE_IN_PAST`, while a date exactly equal to today is admitted."

    Design: Corner/errors/error_effective_date_in_past_on_publish
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(api, ONE_REGULATED_ELEMENT, ONE_PURPOSE)
    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        effective_from="2026-08-10",
    )
    assert policy["completeness_score"] == 100.0

    set_clock(CLOCK_AUGUST_FIFTEENTH, api)

    response = api.publish_privacy_policy_version(
        policy["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
    )

    validate_error(response, ApiErrorId.EFFECTIVE_DATE_IN_PAST.value)
    stored = read_policy(policy["id"], api)
    assert stored["state"] == "IN_REVIEW"
    assert stored["completeness_score"] == 100.0
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "NO_POLICY"


def test_publish_refused_when_the_completeness_score_is_below_the_threshold(
    api: ApiClient,
) -> None:
    """PRD §3.6: "The version's `completeness_score` must be at least 90.0, and a lower score is refused with `ERR_POLICY_COMPLETENESS_BELOW_THRESHOLD`."
    PRD §3.6: "Under `ELEMENT_LEVEL`, the category denominator is the product's `regulated_element_count`, so the policy must name every regulated element individually to reach a full category component."

    Design: Corner/errors/error_policy_completeness_below_threshold_on_publish
    """
    set_clock(CLOCK_AUGUST_FIFTH, api)
    product, assessment = build_scored_product(
        api, FIVE_REGULATED_ELEMENTS, THREE_PURPOSES
    )
    policy = create_reviewed_policy(
        product["id"],
        assessment["id"],
        api,
        version_label="v1",
        specificity_mode="ELEMENT_LEVEL",
        disclosed_category_count=3,
        disclosed_purpose_count=3,
        disclosed_third_party_count=2,
        named_third_party_count=2,
        effective_from="2026-09-01",
    )

    response = api.publish_privacy_policy_version(
        policy["id"], make_compliance_approver_headers(USER_COMPLIANCE_APPROVER)
    )

    validate_error(response, ApiErrorId.POLICY_COMPLETENESS_BELOW_THRESHOLD.value)
    stored = read_policy(policy["id"], api)
    assert stored["completeness_score"] == 84.0
    assert stored["gap_count"] == 1
    assert stored["state"] == "IN_REVIEW"
    assert read_product_row(product["id"], api)["policy_compliance_state"] == "NO_POLICY"
