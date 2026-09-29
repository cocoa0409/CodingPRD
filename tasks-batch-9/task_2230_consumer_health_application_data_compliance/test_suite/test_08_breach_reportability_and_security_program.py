"""Breach reportability analysis, notification gating, and the security risk program."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiClient,
    ApiErrorId,
    assert_breach_incident,
    assert_security_risk_assessment,
    assess_breach,
    build_regulated_product,
    create_breach,
    create_element,
    create_product,
    create_sra,
    create_submitted_assessment,
    make_compliance_approver_headers,
    make_platform_admin_headers,
    make_security_engineer_headers,
    set_clock,
    validate_error,
    validate_success,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating the rendered fractional digits."""
    assert isinstance(value, str), f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _read_product(api: ApiClient, app_product_id: str) -> dict[str, Any]:
    """Read the app product so its derived counters are visible."""
    return validate_success(
        api.get_app_product(app_product_id, make_platform_admin_headers())
    )


def _read_incident(api: ApiClient, incident_id: str) -> dict[str, Any]:
    """Read one breach incident with both rule deadlines."""
    data = validate_success(
        api.get_breach_incident(incident_id, make_security_engineer_headers())
    )
    assert_breach_incident(data)
    return data


def _read_sra(api: ApiClient, sra_id: str) -> dict[str, Any]:
    """Read one security risk assessment with its score and banded tier."""
    data = validate_success(
        api.get_security_risk_assessment(sra_id, make_security_engineer_headers())
    )
    assert_security_risk_assessment(data)
    return data


# ---------------------------------------------------------------------------
# The two notification regimes and the governing deadline
# ---------------------------------------------------------------------------


def test_mixed_scope_breach_records_both_deadlines_and_the_general_rule_governs(
    api: ApiClient,
) -> None:
    """PRD §3.9: "Where the health-specific rule applies, `health_rule_deadline_at` is
    sixty days after `discovered_at`, and otherwise it is null."
    PRD §3.9: "Where the general rule applies, `general_rule_deadline_at` is thirty days
    after `discovered_at`, and otherwise it is null."
    PRD §3.9: "The `governing_deadline_at` is then whichever of the non-null values is
    earlier."
    PRD §3.9: "The practical consequence deserves emphasis: a `CHD_ONLY` breach is
    governed by the sixty-day health deadline; a `GENERAL_PII_ONLY` breach by the
    thirty-day general deadline; and a `MIXED` breach by the thirty-day general deadline,
    which overrides the co-applicable sixty-day health deadline even though both are
    recorded."

    Design: Difficulty/dual_variant_calc/breach_deadline_mixed_scope_general_rule_governs_over_health_rule
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Object store exposure",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="MIXED",
        protection_state="UNPROTECTED",
        affected_consumer_count=120,
        affected_state_max_count=120,
    )

    assessed = validate_success(
        api.assess_breach_incident(incident["id"], make_security_engineer_headers())
    )
    assert_breach_incident(assessed)

    assert assessed["state"] == "REPORTABLE"
    assert _instant(assessed["health_rule_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert _instant(assessed["general_rule_deadline_at"]) == _instant(
        "2026-09-04T00:00:00Z"
    )
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-09-04T00:00:00Z"
    )
    assert assessed["media_notice_required"] is False
    assert assessed["exposure_contribution_cents"] == 144000
    assert _read_product(api, product["id"])["exposure_cents"] == 144000


def test_chd_only_breach_is_governed_by_the_sixty_day_health_deadline_alone(
    api: ApiClient,
) -> None:
    """PRD §3.9: "The health-specific rule applies when the `breach_scope` is `CHD_ONLY`
    or `MIXED`; the general breach rule applies when the `breach_scope` is
    `GENERAL_PII_ONLY` or `MIXED`."
    PRD §3.9: "Where the general rule applies, `general_rule_deadline_at` is thirty days
    after `discovered_at`, and otherwise it is null."
    PRD §3.9: "The `governing_deadline_at` is then whichever of the non-null values is
    earlier."

    Design: Difficulty/dual_variant_calc/breach_deadline_mixed_scope_general_rule_governs_over_health_rule
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Sleep diary leak",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=120,
        affected_state_max_count=120,
    )

    assessed = assess_breach(incident["id"], api)

    assert assessed["state"] == "REPORTABLE"
    assert _instant(assessed["health_rule_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert assessed["general_rule_deadline_at"] is None
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert assessed["exposure_contribution_cents"] == 144000
    assert _read_product(api, product["id"])["exposure_cents"] == 144000


def test_general_pii_only_breach_is_governed_by_the_thirty_day_general_deadline_alone(
    api: ApiClient,
) -> None:
    """PRD §3.9: "The health-specific rule applies when the `breach_scope` is `CHD_ONLY`
    or `MIXED`; the general breach rule applies when the `breach_scope` is
    `GENERAL_PII_ONLY` or `MIXED`."
    PRD §3.9: "Where the health-specific rule applies, `health_rule_deadline_at` is
    sixty days after `discovered_at`, and otherwise it is null."
    PRD §3.9: "The `governing_deadline_at` is then whichever of the non-null values is
    earlier."

    Design: Difficulty/dual_variant_calc/breach_deadline_mixed_scope_general_rule_governs_over_health_rule
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Billing address dump",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="GENERAL_PII_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=120,
        affected_state_max_count=120,
    )

    assessed = assess_breach(incident["id"], api)

    assert assessed["state"] == "REPORTABLE"
    assert assessed["health_rule_deadline_at"] is None
    assert _instant(assessed["general_rule_deadline_at"]) == _instant(
        "2026-09-04T00:00:00Z"
    )
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-09-04T00:00:00Z"
    )
    assert assessed["exposure_contribution_cents"] == 144000
    assert _read_product(api, product["id"])["exposure_cents"] == 144000


# ---------------------------------------------------------------------------
# The assessment fork on the protection state
# ---------------------------------------------------------------------------


def test_assessing_an_unprotected_breach_writes_deadlines_and_adds_its_exposure(
    api: ApiClient,
) -> None:
    """PRD §3.9: "When `protection_state` is `UNPROTECTED`, the incident moves
    `DISCOVERED → REPORTABLE` and the full deadline analysis runs."
    PRD §3.9: "And `exposure_contribution_cents` becomes `affected_consumer_count`
    multiplied by twelve dollars per exposed consumer, which is 1200 cents each; that
    amount is added to the product's `exposure_cents` by exactly that much."

    Design: Difficulty/non_linear_state_machine/breach_assess_fork_diverges_on_protection_state
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    unprotected = create_breach(
        product["id"],
        api,
        incident_label="Plaintext log leak",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=200,
        affected_state_max_count=200,
    )

    assessed = validate_success(
        api.assess_breach_incident(unprotected["id"], make_security_engineer_headers())
    )
    assert_breach_incident(assessed)

    assert assessed["state"] == "REPORTABLE"
    assert _instant(assessed["health_rule_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert assessed["general_rule_deadline_at"] is None
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert assessed["exposure_contribution_cents"] == 240000
    assert _read_product(api, product["id"])["exposure_cents"] == 240000


def test_assessing_an_encrypted_breach_takes_the_safe_harbour_branch_with_no_exposure(
    api: ApiClient,
) -> None:
    """PRD §3.9: "When `protection_state` is `ENCRYPTED_SECURED`, the encryption safe
    harbour applies: the incident moves `DISCOVERED → NOT_REPORTABLE`, all three deadline
    fields stay null, `media_notice_required` stays false, `exposure_contribution_cents`
    stays at zero, and the product's `exposure_cents` is therefore unchanged."
    PRD §2.11: "`exposure_cents` is the sum of `exposure_contribution_cents` over the
    product's breach incidents whose `state` is `REPORTABLE` or `NOTIFIED`."

    Design: Difficulty/non_linear_state_machine/breach_assess_fork_diverges_on_protection_state
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    unprotected = create_breach(
        product["id"],
        api,
        incident_label="Plaintext log leak",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=200,
        affected_state_max_count=200,
    )
    encrypted = create_breach(
        product["id"],
        api,
        incident_label="Encrypted backup tape loss",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="ENCRYPTED_SECURED",
        affected_consumer_count=300,
        affected_state_max_count=300,
    )
    assess_breach(unprotected["id"], api)

    safe = validate_success(
        api.assess_breach_incident(encrypted["id"], make_security_engineer_headers())
    )
    assert_breach_incident(safe)

    assert safe["state"] == "NOT_REPORTABLE"
    assert safe["health_rule_deadline_at"] is None
    assert safe["general_rule_deadline_at"] is None
    assert safe["governing_deadline_at"] is None
    assert safe["media_notice_required"] is False
    assert safe["exposure_contribution_cents"] == 0
    assert _read_product(api, product["id"])["exposure_cents"] == 240000


# ---------------------------------------------------------------------------
# The media notice threshold
# ---------------------------------------------------------------------------


def test_media_notice_required_at_exactly_five_hundred_state_residents(
    api: ApiClient,
) -> None:
    """PRD §3.9: "`media_notice_required` becomes true when `affected_state_max_count` is
    at least five hundred — a concentration that large in one state triggers substitute
    media notice — and false otherwise."
    PRD §3.9: "And `exposure_contribution_cents` becomes `affected_consumer_count`
    multiplied by twelve dollars per exposed consumer, which is 1200 cents each; that
    amount is added to the product's `exposure_cents` by exactly that much."

    Design: Difficulty/boundary_precision_check/media_notice_threshold_at_exactly_five_hundred_state_residents
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Vendor API misconfiguration",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=900,
        affected_state_max_count=500,
    )

    assessed = validate_success(
        api.assess_breach_incident(incident["id"], make_security_engineer_headers())
    )
    assert_breach_incident(assessed)

    assert assessed["state"] == "REPORTABLE"
    assert assessed["media_notice_required"] is True
    assert assessed["media_notice_sent"] is False
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert assessed["exposure_contribution_cents"] == 1080000
    assert _read_product(api, product["id"])["exposure_cents"] == 1080000


def test_media_notice_not_required_one_resident_below_the_five_hundred_threshold(
    api: ApiClient,
) -> None:
    """PRD §3.9: "`media_notice_required` becomes true when `affected_state_max_count` is
    at least five hundred — a concentration that large in one state triggers substitute
    media notice — and false otherwise."

    Design: Difficulty/boundary_precision_check/media_notice_threshold_at_exactly_five_hundred_state_residents
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Vendor API misconfiguration",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=900,
        affected_state_max_count=499,
    )

    assessed = validate_success(
        api.assess_breach_incident(incident["id"], make_security_engineer_headers())
    )
    assert_breach_incident(assessed)

    assert assessed["state"] == "REPORTABLE"
    assert assessed["media_notice_required"] is False
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-10-04T00:00:00Z"
    )
    assert assessed["exposure_contribution_cents"] == 1080000
    assert _read_product(api, product["id"])["exposure_cents"] == 1080000


# ---------------------------------------------------------------------------
# Notification gating
# ---------------------------------------------------------------------------


def test_notifying_without_the_required_media_notice_is_refused(api: ApiClient) -> None:
    """PRD §3.9: "And when `media_notice_required` is true, the body must set
    `media_notice_sent` to true; a notification that omits the required media
    accompaniment is refused with `ERR_MEDIA_NOTICE_REQUIRED`."

    Design: Corner/endpoints/conditional_action_notify_without_the_media_notice_rejected
    """
    set_clock("2026-08-10T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Analytics bucket left public",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=700,
        affected_state_max_count=700,
    )
    assessed = assess_breach(incident["id"], api)
    assert assessed["media_notice_required"] is True

    response = api.notify_breach_incident(
        incident["id"], {"media_notice_sent": False}, make_security_engineer_headers()
    )
    validate_error(response, ApiErrorId.MEDIA_NOTICE_REQUIRED.value)

    after = _read_incident(api, incident["id"])
    assert after["state"] == "REPORTABLE"
    assert after["media_notice_required"] is True
    assert _instant(after["governing_deadline_at"]) == _instant("2026-10-04T00:00:00Z")
    assert after["notified_at"] is None
    assert _read_product(api, product["id"])["exposure_cents"] == 840000


def test_notifying_after_the_governing_deadline_has_passed_is_refused(
    api: ApiClient,
) -> None:
    """PRD §3.9: "It is admitted only while the logical clock is not later than
    `governing_deadline_at`, a late notification being refused with
    `ERR_NOTIFICATION_DEADLINE_PASSED`."
    PRD §3.9: "Where the health-specific rule applies, `health_rule_deadline_at` is sixty
    days after `discovered_at`, and otherwise it is null."

    Design: Corner/errors/error_notification_deadline_passed_on_notify
    """
    set_clock("2026-08-02T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Sync log exposure",
        discovered_at="2026-08-01T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=100,
        affected_state_max_count=90,
    )
    assessed = assess_breach(incident["id"], api)
    assert _instant(assessed["governing_deadline_at"]) == _instant(
        "2026-09-30T00:00:00Z"
    )
    set_clock("2026-10-01T00:00:00Z", api)

    response = api.notify_breach_incident(
        incident["id"], {"media_notice_sent": False}, make_security_engineer_headers()
    )
    validate_error(response, ApiErrorId.NOTIFICATION_DEADLINE_PASSED.value)

    after = _read_incident(api, incident["id"])
    assert after["state"] == "REPORTABLE"
    assert _instant(after["health_rule_deadline_at"]) == _instant(
        "2026-09-30T00:00:00Z"
    )
    assert after["general_rule_deadline_at"] is None
    assert _instant(after["governing_deadline_at"]) == _instant("2026-09-30T00:00:00Z")
    assert after["media_notice_required"] is False
    assert after["notified_at"] is None
    assert _read_product(api, product["id"])["exposure_cents"] == 120000


# ---------------------------------------------------------------------------
# Retraction compensates the assessment exactly
# ---------------------------------------------------------------------------


def test_retracting_a_reportable_finding_returns_product_exposure_to_its_start(
    api: ApiClient,
) -> None:
    """PRD §3.9: "An engineer who concludes on further investigation that the incident was
    not reportable after all may retract the finding, moving it
    `REPORTABLE → DISCOVERED`."
    PRD §3.9: "Retraction compensates the assessment exactly: it clears
    `health_rule_deadline_at`, `general_rule_deadline_at` and `governing_deadline_at` back
    to null, resets `media_notice_required` to false, subtracts the incident's previous
    `exposure_contribution_cents` from the product's `exposure_cents`, and resets
    `exposure_contribution_cents` to zero."
    PRD §3.9: "Because the subtraction is exactly the amount the assessment added, a
    `DISCOVERED → REPORTABLE → DISCOVERED` round trip leaves the product's
    `exposure_cents` exactly where it started."

    Design: Difficulty/compensating_invariant/breach_assess_then_retract_conserves_product_exposure_cents
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    assert _read_product(api, product["id"])["exposure_cents"] == 0
    incident = create_breach(
        product["id"],
        api,
        incident_label="Object store exposure",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="MIXED",
        protection_state="UNPROTECTED",
        affected_consumer_count=120,
        affected_state_max_count=120,
    )
    assess_breach(incident["id"], api)
    assert _read_product(api, product["id"])["exposure_cents"] == 144000

    retracted = validate_success(
        api.retract_breach_incident(incident["id"], make_security_engineer_headers())
    )
    assert_breach_incident(retracted)

    assert retracted["state"] == "DISCOVERED"
    assert retracted["exposure_contribution_cents"] == 0
    assert retracted["health_rule_deadline_at"] is None
    assert retracted["general_rule_deadline_at"] is None
    assert retracted["governing_deadline_at"] is None
    assert retracted["media_notice_required"] is False
    assert _read_product(api, product["id"])["exposure_cents"] == 0


def test_retraction_clears_a_required_media_notice_and_reassessment_restores_the_ledger(
    api: ApiClient,
) -> None:
    """PRD §3.9: "Retraction compensates the assessment exactly: it clears
    `health_rule_deadline_at`, `general_rule_deadline_at` and `governing_deadline_at` back
    to null, resets `media_notice_required` to false, subtracts the incident's previous
    `exposure_contribution_cents` from the product's `exposure_cents`, and resets
    `exposure_contribution_cents` to zero."
    PRD §3.9: "And `exposure_contribution_cents` becomes `affected_consumer_count`
    multiplied by twelve dollars per exposed consumer, which is 1200 cents each; that
    amount is added to the product's `exposure_cents` by exactly that much."
    PRD §3.9: "`media_notice_required` becomes true when `affected_state_max_count` is at
    least five hundred — a concentration that large in one state triggers substitute media
    notice — and false otherwise."

    Design: Difficulty/compensating_invariant/breach_assess_then_retract_conserves_product_exposure_cents
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    incident = create_breach(
        product["id"],
        api,
        incident_label="Vendor API misconfiguration",
        discovered_at="2026-08-05T00:00:00Z",
        breach_scope="CHD_ONLY",
        protection_state="UNPROTECTED",
        affected_consumer_count=900,
        affected_state_max_count=500,
    )
    first = assess_breach(incident["id"], api)
    assert first["media_notice_required"] is True
    assert _read_product(api, product["id"])["exposure_cents"] == 1080000

    retracted = validate_success(
        api.retract_breach_incident(incident["id"], make_security_engineer_headers())
    )
    assert retracted["state"] == "DISCOVERED"
    assert retracted["media_notice_required"] is False
    assert retracted["exposure_contribution_cents"] == 0
    assert _read_product(api, product["id"])["exposure_cents"] == 0

    second = validate_success(
        api.assess_breach_incident(incident["id"], make_security_engineer_headers())
    )
    assert_breach_incident(second)
    assert second["state"] == "REPORTABLE"
    assert second["media_notice_required"] is True
    assert second["exposure_contribution_cents"] == 1080000
    assert _instant(second["governing_deadline_at"]) == _instant("2026-10-04T00:00:00Z")
    assert _read_product(api, product["id"])["exposure_cents"] == 1080000


# ---------------------------------------------------------------------------
# Unknown breach incident identifiers
# ---------------------------------------------------------------------------


def test_reading_a_breach_incident_by_unknown_id_yields_the_generic_not_found(
    api: ApiClient,
) -> None:
    """PRD §2.6: "Which 404 is returned depends on the entity the segment addresses: an
    unresolved app product yields `ERR_APP_PRODUCT_NOT_FOUND`, an unresolved consumer
    `ERR_CONSUMER_NOT_FOUND`, an unresolved vendor `ERR_VENDOR_NOT_FOUND`, an unresolved
    data element `ERR_DATA_ELEMENT_NOT_FOUND`, an unresolved processing purpose
    `ERR_PURPOSE_NOT_FOUND`, and an unresolved row of any other type — applicability
    assessment, element-purpose mapping, consent record, privacy policy version, consumer
    request, deletion task, geofence zone, geofence campaign, breach incident, or security
    risk assessment — yields the generic `ERR_RESOURCE_NOT_FOUND`."

    Design: Corner/entities/not_found_breach_incident_by_unknown_id
    """
    response = api.get_breach_incident(
        NON_EXISTENT_UUID, make_security_engineer_headers()
    )
    validate_error(response, ApiErrorId.RESOURCE_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Residual risk scoring
# ---------------------------------------------------------------------------


def test_residual_risk_score_is_rounded_once_after_the_weighted_terms_are_summed(
    api: ApiClient,
) -> None:
    """PRD §3.9: "Residual risk is scored on creation, on every revision, and again on
    finalisation, and the rounding order is pinned: weight first, sum the unrounded
    weighted terms, and round once at the end."
    PRD §3.9: "Rounding each weighted domain term to two decimals before summing produces
    a different score for some inputs and is wrong."
    PRD §3.9: "**Step three** multiplies each raw gap by the penalty multiplier and by
    that domain's weight — thirty per cent for administrative, thirty-five per cent for
    technical, ten per cent for physical, twenty-five per cent for vendor oversight — and
    does not round the result."
    PRD §3.9: "**Step four** sums those four weighted terms and rounds the single total
    half-up to two decimal places, giving `residual_risk_score`."
    PRD §3.9: "**Step five** bands the score into `risk_tier`: strictly below 20 is
    `LOW`; from 20 up to but not including 40 is `MODERATE`; from 40 up to but not
    including 60 is `HIGH`; and 60 or above is `CRITICAL`."

    Design: Difficulty/combinatorial_formula/residual_risk_rounding_order_pinned_to_weight_then_sum_then_round
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)

    created = validate_success(
        api.create_security_risk_assessment(
            {
                "app_product_id": product["id"],
                "assessment_label": "FY26 program review",
                "admin_control_score": 60,
                "technical_control_score": 60,
                "physical_control_score": 70,
                "vendor_oversight_score": 75,
                "documented_gap_count": 1,
                "remediation_plan_present": False,
            },
            make_security_engineer_headers(),
        ),
        201,
    )
    assert_security_risk_assessment(created)

    assert float(created["residual_risk_score"]) == 36.48
    assert float(created["residual_risk_score"]) != 36.49
    assert created["risk_tier"] == "MODERATE"
    assert created["state"] == "DRAFT"
    assert _read_product(api, product["id"])["security_program_state"] == "NONE"


def test_finalisation_rescores_residual_risk_with_the_same_single_rounding_step(
    api: ApiClient,
) -> None:
    """PRD §3.9: "Residual risk is scored on creation, on every revision, and again on
    finalisation, and the rounding order is pinned: weight first, sum the unrounded
    weighted terms, and round once at the end."
    PRD §3.9: "**Step four** sums those four weighted terms and rounds the single total
    half-up to two decimal places, giving `residual_risk_score`."
    PRD §3.9: "Finalisation moves the assessment `DRAFT → FINALIZED` and stamps
    `finalized_at` with the logical clock."
    PRD §2.11: "`security_program_state` likewise takes three values: `NONE` while no
    security risk assessment for the product has reached `FINALIZED`; `CURRENT` when the
    `FINALIZED` assessment with the greatest `created_at` carries a `risk_tier` of `LOW`
    or `MODERATE`; and `STALE` when that same assessment carries a `risk_tier` of `HIGH`
    or `CRITICAL`."

    Design: Difficulty/combinatorial_formula/residual_risk_rounding_order_pinned_to_weight_then_sum_then_round
    """
    set_clock("2026-08-05T00:00:00Z", api)
    scenario = build_regulated_product(api)
    product_id = scenario["product"]["id"]
    sra = create_sra(
        product_id,
        api,
        assessment_label="FY26 program review",
        admin_control_score=60,
        technical_control_score=60,
        physical_control_score=70,
        vendor_oversight_score=75,
        documented_gap_count=1,
        remediation_plan_present=False,
    )
    assert float(sra["residual_risk_score"]) == 36.48

    finalized = validate_success(
        api.finalize_security_risk_assessment(
            sra["id"], make_security_engineer_headers()
        )
    )
    assert_security_risk_assessment(finalized)

    assert finalized["state"] == "FINALIZED"
    assert finalized["finalized_at"] is not None
    assert float(finalized["residual_risk_score"]) == 36.48
    assert float(finalized["residual_risk_score"]) != 36.49
    assert finalized["risk_tier"] == "MODERATE"
    assert _read_product(api, product_id)["security_program_state"] == "CURRENT"


def test_risk_tier_boundary_puts_a_score_of_exactly_forty_in_the_high_band(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """PRD §3.9: "**Step five** bands the score into `risk_tier`: strictly below 20 is
    `LOW`; from 20 up to but not including 40 is `MODERATE`; from 40 up to but not
    including 60 is `HIGH`; and 60 or above is `CRITICAL`."
    PRD §3.9: "**Step four** sums those four weighted terms and rounds the single total
    half-up to two decimal places, giving `residual_risk_score`."

    Design: Corner/calculations/threshold_residual_risk_tier_boundary_at_exactly_forty
    """
    product = create_product(api)
    below = validate_success(
        api.create_security_risk_assessment(
            {
                "app_product_id": product["id"],
                "assessment_label": "Just below the cut",
                "admin_control_score": 66,
                "technical_control_score": 71,
                "physical_control_score": 58,
                "vendor_oversight_score": 63,
                "documented_gap_count": 5,
                "remediation_plan_present": False,
            },
            make_security_engineer_headers(),
        ),
        201,
    )
    assert_security_risk_assessment(below)
    assert float(below["residual_risk_score"]) == 39.72
    assert below["risk_tier"] == "MODERATE"

    at_boundary = validate_success(
        api.create_security_risk_assessment(
            {
                "app_product_id": product["id"],
                "assessment_label": "Exactly at the cut",
                "admin_control_score": 60,
                "technical_control_score": 60,
                "physical_control_score": 60,
                "vendor_oversight_score": 60,
                "documented_gap_count": 0,
                "remediation_plan_present": False,
            },
            make_security_engineer_headers(),
        ),
        201,
    )
    assert_security_risk_assessment(at_boundary)
    assert float(at_boundary["residual_risk_score"]) == 40.00
    assert at_boundary["risk_tier"] == "HIGH"


def test_gap_penalty_multiplier_is_capped_at_two_so_extra_gaps_do_not_raise_the_score(
    api: ApiClient, clock_at_epoch: str
) -> None:
    """PRD §3.9: "**Step one** computes a penalty multiplier as one plus three and a half
    per cent per documented gap — that is, one plus 0.035 multiplied by
    `documented_gap_count` — capped at 2.00, so that once `documented_gap_count` reaches
    twenty-nine the multiplier is pinned at exactly 2.00 and further gaps no longer raise
    it."
    PRD §3.9: "**Step two** computes each domain's raw gap as one hundred less that
    domain's maturity score, taken in the fixed order administrative, technical, physical,
    vendor."
    PRD §3.9: "**Step five** bands the score into `risk_tier`: strictly below 20 is
    `LOW`; from 20 up to but not including 40 is `MODERATE`; from 40 up to but not
    including 60 is `HIGH`; and 60 or above is `CRITICAL`."

    Design: Corner/calculations/weighted_scoring_penalty_multiplier_capped_at_two
    """
    product = create_product(api)
    twenty_nine_gaps = validate_success(
        api.create_security_risk_assessment(
            {
                "app_product_id": product["id"],
                "assessment_label": "Twenty nine gaps",
                "admin_control_score": 50,
                "technical_control_score": 50,
                "physical_control_score": 50,
                "vendor_oversight_score": 50,
                "documented_gap_count": 29,
                "remediation_plan_present": True,
            },
            make_security_engineer_headers(),
        ),
        201,
    )
    assert_security_risk_assessment(twenty_nine_gaps)
    assert float(twenty_nine_gaps["residual_risk_score"]) == 100.00
    assert twenty_nine_gaps["risk_tier"] == "CRITICAL"

    forty_gaps = validate_success(
        api.create_security_risk_assessment(
            {
                "app_product_id": product["id"],
                "assessment_label": "Forty gaps",
                "admin_control_score": 50,
                "technical_control_score": 50,
                "physical_control_score": 50,
                "vendor_oversight_score": 50,
                "documented_gap_count": 40,
                "remediation_plan_present": True,
            },
            make_security_engineer_headers(),
        ),
        201,
    )
    assert_security_risk_assessment(forty_gaps)
    assert float(forty_gaps["residual_risk_score"]) == 100.00
    assert forty_gaps["risk_tier"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Finalisation gates
# ---------------------------------------------------------------------------


def test_finalisation_requires_an_approved_applicability_assessment_on_the_product(
    api: ApiClient,
) -> None:
    """PRD §3.9: "The product must have an applicability assessment currently in
    `APPROVED` — there is no point documenting a security program for a product whose
    regulatory track is unsettled, and the attempt is refused with
    `ERR_ASSESSMENT_NOT_APPROVED`."
    PRD §3.9: "Finalisation moves the assessment `DRAFT → FINALIZED` and stamps
    `finalized_at` with the logical clock."
    PRD §3.9: "Finalisation then refreshes the product's `security_program_state` from
    this assessment's `risk_tier`, per §2.11."

    Design: Corner/validations/cross_entity_validation_finalize_requires_an_approved_applicability_assessment
    """
    set_clock("2026-08-05T00:00:00Z", api)
    product = create_product(api)
    create_element(product["id"], api)
    applicability = create_submitted_assessment(product["id"], api)
    assert applicability["state"] == "SUBMITTED"
    sra = create_sra(
        product["id"],
        api,
        assessment_label="Annual review",
        admin_control_score=95,
        technical_control_score=95,
        physical_control_score=95,
        vendor_oversight_score=95,
        documented_gap_count=0,
        remediation_plan_present=False,
    )
    assert float(sra["residual_risk_score"]) == 5.00
    assert sra["risk_tier"] == "LOW"

    response = api.finalize_security_risk_assessment(
        sra["id"], make_security_engineer_headers()
    )
    validate_error(response, ApiErrorId.ASSESSMENT_NOT_APPROVED.value)

    blocked = _read_sra(api, sra["id"])
    assert blocked["state"] == "DRAFT"
    assert blocked["finalized_at"] is None
    assert float(blocked["residual_risk_score"]) == 5.00
    assert blocked["risk_tier"] == "LOW"
    assert _read_product(api, product["id"])["security_program_state"] == "NONE"

    approved = validate_success(
        api.approve_applicability_assessment(
            applicability["id"], make_compliance_approver_headers()
        )
    )
    assert approved["state"] == "APPROVED"

    finalized = validate_success(
        api.finalize_security_risk_assessment(
            sra["id"], make_security_engineer_headers()
        )
    )
    assert_security_risk_assessment(finalized)
    assert finalized["state"] == "FINALIZED"
    assert finalized["finalized_at"] is not None
    assert _read_product(api, product["id"])["security_program_state"] == "CURRENT"


def test_finalising_a_high_tier_assessment_without_a_remediation_plan_is_refused(
    api: ApiClient,
) -> None:
    """PRD §3.9: "And a `risk_tier` of `HIGH` or `CRITICAL` may be finalised only when
    `remediation_plan_present` is true; a high-risk posture with no written plan is
    refused with `ERR_REMEDIATION_PLAN_REQUIRED`, whereas a `LOW` or `MODERATE` tier
    finalises with or without a plan."
    PRD §3.9: "**Step five** bands the score into `risk_tier`: strictly below 20 is
    `LOW`; from 20 up to but not including 40 is `MODERATE`; from 40 up to but not
    including 60 is `HIGH`; and 60 or above is `CRITICAL`."

    Design: Corner/errors/error_remediation_plan_required_on_finalizing_a_high_tier_assessment
    """
    set_clock("2026-08-05T00:00:00Z", api)
    scenario = build_regulated_product(api)
    product_id = scenario["product"]["id"]
    sra = create_sra(
        product_id,
        api,
        assessment_label="Annual review",
        admin_control_score=60,
        technical_control_score=60,
        physical_control_score=60,
        vendor_oversight_score=60,
        documented_gap_count=0,
        remediation_plan_present=False,
    )
    assert float(sra["residual_risk_score"]) == 40.00
    assert sra["risk_tier"] == "HIGH"

    response = api.finalize_security_risk_assessment(
        sra["id"], make_security_engineer_headers()
    )
    validate_error(response, ApiErrorId.REMEDIATION_PLAN_REQUIRED.value)

    after = _read_sra(api, sra["id"])
    assert float(after["residual_risk_score"]) == 40.00
    assert after["risk_tier"] == "HIGH"
    assert after["state"] == "DRAFT"
    assert after["finalized_at"] is None
    assert _read_product(api, product_id)["security_program_state"] == "NONE"
