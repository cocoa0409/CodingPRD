"""The independent-provider programme: the two compliance-score variants, the
provider-state gate on order confirmation, certification slot collisions and the
training-credit conservation identity.
"""
import pytest

from test_helpers import (
    ADMIN,
    COMPLIANCE,
    TECH,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_ALT,
    api_client,
    assert_training_credit_balanced,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_success,
)

TECHNICIAN_USER_ID_THIRD = "user_tech_003"


def _read_case(case_id):
    return get_success_data(api_client.get_defective_return(case_id, ADMIN))


def _compliance_score(provider_id, variant):
    response = api_client.get_provider_compliance_score(
        provider_id, COMPLIANCE, params={"variant": variant}
    )
    return validate_success(response, 200)


# --------------------------------------------------------------------------- #
# One frozen provider data set read through both score variants
# --------------------------------------------------------------------------- #
def _provider_with_future_certs_and_open_install_error():
    """One in-window certification, two future ones, and an unclosed install-error case."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-2000",
        product_family="CRX",
        market_release_date="2025-03-01T00:00:00Z",
        repairability_tier="TIER_C_AUTHORIZED_ONLY",
    )
    part = fixtures.create_part(
        sku="SKU-CAL-SENSOR", list_price_cents=5000, requires_calibration=True
    )
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2025-04-01T00:00:00Z",
        self_service_eligible=False,
        install_minutes=45,
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-CAL-SENSOR"], safety_warning_count=3
    )
    fixtures.publish_calibration_procedure(
        model["id"], ["SKU-CAL-SENSOR"], safety_warning_count=2
    )

    provider = fixtures.create_provider(
        "US-CA",
        ADMIN,
        legal_name="Northwind Repair LLC",
        requested_access_tier="TIER_2_SAFETY",
        technician_count=9,
    )
    fixtures.begin_training(provider["id"], 10, ADMIN)
    fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2027-07-01T00:00:00Z",
        exam_score=88,
    )
    for technician in (TECHNICIAN_USER_ID_ALT, TECHNICIAN_USER_ID_THIRD):
        fixtures.file_certification(
            provider["id"],
            technician,
            ADMIN,
            valid_from="2026-10-01T00:00:00Z",
            valid_until="2027-10-01T00:00:00Z",
            exam_score=90,
        )
    provider = fixtures.decide_authorization(
        provider["id"],
        "AUTHORIZE",
        ADMIN,
        decision_reason="training coverage met",
        granted_access_tier="TIER_2_SAFETY",
    )

    assessment = fixtures.create_assessment(
        model["id"],
        part["id"],
        "US-CA",
        TECH,
        requester_class="AUTHORIZED_PROVIDER",
        provider_id=provider["id"],
    )
    order = fixtures.create_order(
        assessment["id"],
        "US-CA",
        TECH,
        buyer_class="AUTHORIZED_PROVIDER",
        provider_id=provider["id"],
    )
    line = fixtures.append_line(order["id"], part["id"], 1, TECH)
    fixtures.request_disclosure(order["id"], TECH)
    fixtures.acknowledge_disclosure(order["id"], TECH, "PROVIDER_MANAGED")
    fixtures.confirm_order(order["id"], TECH)
    fixtures.deliver_order(order["id"])
    fixtures.calibrate_line(order["id"], line["id"], 400, TECH)

    case = fixtures.create_defective_return(
        line["id"], 1, TECH, reported_failure_code="CALIBRATION_DRIFT"
    )
    fixtures.receive_defective_return(case["id"])
    case = fixtures.record_analysis(
        case["id"],
        "PROVIDER_INSTALL_ERROR",
        True,
        analysis_note="torque spec not followed",
    )
    return {"provider": provider, "order": order, "line": line, "case": case}


def test_provider_channel_line_carries_the_trade_discount_and_half_goodwill_credit():
    """PRD §3.6: "The line's `buyer_multiplier` is 1.00 when the order's
    `buyer_class` is `SELF_REPAIR_CONSUMER` and 0.82 when it is
    `AUTHORIZED_PROVIDER` — the eighteen percent trade discount that makes the
    provider channel worth joining."
    PRD §3.9: "The pro-rata basis is the line's `line_total_cents` multiplied by the
    case's `quantity` and divided by the line's `quantity`, rounded half up to whole
    cents. That is the first of two sequential, pinned roundings. The goodwill
    provisional figure is then the pro-rata basis multiplied by one half, rounded
    half up."

    Design: Difficulty/dual_variant_calc/provider_compliance_score_rolling_attested_vs_live_recompute_split_bands
    """
    bundle = _provider_with_future_certs_and_open_install_error()

    line = get_success_data(api_client.get_order_line(bundle["line"]["id"], ADMIN))
    assert line["line_total_cents"] == 4592, (
        f"Expected 5000 x 0.82 x 1.12 == 4592, got {line['line_total_cents']}"
    )

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["documentation_fee_cents"] == 860, (
        f"Expected 500 + 120 x 3 warnings == 860, got {order['documentation_fee_cents']}"
    )
    assert order["total_due_cents"] == 5452, (
        f"Expected 4592 + 860 == 5452, got {order['total_due_cents']}"
    )

    case = _read_case(bundle["case"]["id"])
    assert case["provisional_credit_cents"] == 2296, (
        f"Expected half of the 4592 pro-rata basis, got "
        f"{case['provisional_credit_cents']}"
    )


def test_rolling_attested_score_ignores_future_certs_and_unclosed_cases():
    """PRD §3.8: "`ROLLING_ATTESTED` is the default and is the figure the programme
    contractually stands behind: it counts only certifications whose `status` is
    `ACTIVE` and whose inclusive validity interval from `valid_from` to `valid_until`
    contains the logical clock, and it counts only closed defective-return cases,
    those in `CREDIT_ISSUED` or `REJECTED`."
    PRD §3.8: "The `score` is then 100 multiplied by the sum of three weighted terms
    — 0.45 times the certification coverage ratio, plus 0.35 times one minus the
    smaller of 1 and the breach count divided by a breach cap of five, plus 0.20
    times one minus the calibration failure ratio — rounded half up to a whole
    number."

    Design: Difficulty/dual_variant_calc/provider_compliance_score_rolling_attested_vs_live_recompute_split_bands
    """
    bundle = _provider_with_future_certs_and_open_install_error()
    score = _compliance_score(bundle["provider"]["id"], "ROLLING_ATTESTED")

    assert score["variant"] == "ROLLING_ATTESTED", score["variant"]
    assert score["cert_coverage_ratio"] == pytest.approx(1 / 3, abs=0.01), (
        f"Expected 1 in-window certification of 3 required, got "
        f"{score['cert_coverage_ratio']}"
    )
    assert score["breach_count"] == 0, (
        f"an ANALYSIS_COMPLETE case is not closed, got {score['breach_count']}"
    )
    assert score["calibration_failure_ratio"] == pytest.approx(1.0, abs=0.01), (
        f"the only attempted line failed, got {score['calibration_failure_ratio']}"
    )
    assert score["score"] == 50, (
        f"Expected 100 x (0.45/3 + 0.35 + 0) == 50, got {score['score']}"
    )
    assert score["access_tier_band"] == "TIER_3_STANDARD", score["access_tier_band"]


def test_live_recompute_score_counts_future_certs_and_the_open_case():
    """PRD §3.8: "`LIVE_RECOMPUTE` is the forward-looking figure, requested
    explicitly: it counts every certification whose `status` is `ACTIVE` regardless
    of whether the logical clock sits inside its validity window, so future-dated
    certifications count, and it counts cases in `REQUESTED`, `RECEIVED`,
    `ANALYSIS_COMPLETE`, `CREDIT_ISSUED`, and `REJECTED`, so an install-error case
    still under analysis lowers this score while the attested variant ignores it."
    PRD §3.8: "The `access_tier_band` is `TIER_1_UNRESTRICTED` when the score is at
    least 85, otherwise `TIER_2_SAFETY` when the score is at least 65, otherwise
    `TIER_3_STANDARD`; the comparisons are inclusive, so a score of exactly 85 lands
    in `TIER_1_UNRESTRICTED` and exactly 65 lands in `TIER_2_SAFETY`."

    Design: Difficulty/dual_variant_calc/provider_compliance_score_rolling_attested_vs_live_recompute_split_bands
    """
    bundle = _provider_with_future_certs_and_open_install_error()
    rolling = _compliance_score(bundle["provider"]["id"], "ROLLING_ATTESTED")
    live = _compliance_score(bundle["provider"]["id"], "LIVE_RECOMPUTE")

    assert live["variant"] == "LIVE_RECOMPUTE", live["variant"]
    assert live["cert_coverage_ratio"] == pytest.approx(1.0, abs=0.01), (
        f"all three ACTIVE certifications count here, got {live['cert_coverage_ratio']}"
    )
    assert live["breach_count"] == 1, (
        f"the install-error case under analysis counts here, got {live['breach_count']}"
    )
    assert live["score"] == 73, (
        f"Expected 100 x (0.45 + 0.35 x 0.8 + 0) == 73, got {live['score']}"
    )
    assert live["access_tier_band"] == "TIER_2_SAFETY", live["access_tier_band"]
    assert live["score"] - rolling["score"] == 23, (
        "the two variants must split on identical stored rows, got "
        f"{live['score']} and {rolling['score']}"
    )

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["required_cert_count"] == 3, provider["required_cert_count"]
    assert provider["active_cert_count"] == 3, provider["active_cert_count"]
    assert provider["attested_compliance_score"] == 70, (
        "the authorization decision snapshotted the rolling variant before any "
        f"calibration attempt, got {provider['attested_compliance_score']}"
    )
    assert provider["parts_access_tier"] == "TIER_2_SAFETY", (
        f"Expected the stricter of the granted tier and the score band, got "
        f"{provider['parts_access_tier']}"
    )


# --------------------------------------------------------------------------- #
# A provider suspended after its buyer signed the disclosure
# --------------------------------------------------------------------------- #
def _acknowledged_provider_order_then_suspended():
    """A provider order that satisfies every one of its own confirm preconditions."""
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA"},
        model_overrides={
            "model_code": "CRX-9300",
            "product_family": "CRX",
            "market_release_date": "2025-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={"sku": "SKU-PROV-1", "list_price_cents": 5000},
        compatibility_overrides={
            "effective_from": "2025-02-01T00:00:00Z",
            "install_minutes": 30,
        },
        safety_warning_count=2,
    )
    provider_bundle = fixtures.build_provider_order_setup(
        setup, TECHNICIAN_USER_ID, technician_count=4, training_credit_grant=2
    )
    provider_id = provider_bundle["provider"]["id"]
    headers = provider_bundle["headers"]

    bundle = fixtures.build_pending_disclosure_order(
        setup,
        1,
        headers,
        assessment_overrides={
            "requester_class": "AUTHORIZED_PROVIDER",
            "provider_id": provider_id,
        },
        order_overrides={"buyer_class": "AUTHORIZED_PROVIDER", "provider_id": provider_id},
    )
    fixtures.acknowledge_disclosure(bundle["order"]["id"], headers, "PROVIDER_MANAGED")
    fixtures.decide_authorization(
        provider_id, "SUSPEND", COMPLIANCE, decision_reason="field safety audit finding"
    )
    return {"provider_id": provider_id, "headers": headers, "order": bundle["order"]}


def test_confirm_is_refused_while_the_named_provider_sits_suspended():
    """PRD §3.6: "And when the `buyer_class` is `AUTHORIZED_PROVIDER`, the named
    provider's `authorization_status` must be exactly `AUTHORIZED` — `APPLIED`,
    `TRAINING_IN_PROGRESS`, `SUSPENDED`, and `REVOKED` are all refused with
    `ERR_PROVIDER_NOT_AUTHORIZED`."
    PRD §3.8: "Suspending is a `ComplianceOfficer` decision out of `AUTHORIZED` that
    stores `suspension_reason`, stops that provider's orders from being confirmed,
    and revokes every still-`VALID` assessment of the provider."

    Design: Difficulty/cross_entity_state_dependency/provider_order_confirm_blocked_while_provider_is_suspended
    """
    bundle = _acknowledged_provider_order_then_suspended()

    provider = fixtures.read_provider(bundle["provider_id"])
    assert provider["authorization_status"] == "SUSPENDED", (
        f"Expected the gating row to have left AUTHORIZED, got "
        f"{provider['authorization_status']}"
    )

    response = api_client.confirm_order(bundle["order"]["id"], bundle["headers"])
    validate_error(response, "ERR_PROVIDER_NOT_AUTHORIZED", 403)


def test_provider_order_stays_pending_disclosure_after_the_refused_confirm():
    """PRD §3.6: "**Confirmation** advances `PENDING_DISCLOSURE` to `CONFIRMED` and
    carries the densest precondition set in the programme."
    PRD §3.6: "Its `disclosure_acknowledged_at` must not be null, and there must
    exist an acknowledgment whose `acknowledged_scope` actually covers the order's
    contents — `FULL_SELF_REPAIR` for a consumer order containing components,
    `PROVIDER_MANAGED` for a provider order, and `TOOL_RENTAL_ONLY` only for an
    order limited to rentals and tools; a failure here is refused with
    `ERR_DISCLOSURE_NOT_ACKNOWLEDGED`."

    Design: Difficulty/cross_entity_state_dependency/provider_order_confirm_blocked_while_provider_is_suspended
    """
    bundle = _acknowledged_provider_order_then_suspended()
    api_client.confirm_order(bundle["order"]["id"], bundle["headers"])

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["disclosure_acknowledged_at"] is not None, (
        "nothing about the order itself blocks confirmation"
    )
    assert order["fulfillment_status"] == "PENDING_DISCLOSURE", (
        f"the refused confirmation must leave the order where it was, got "
        f"{order['fulfillment_status']}"
    )
    assert order["confirmed_at"] is None, (
        f"a refused confirmation stamps nothing, got {order['confirmed_at']}"
    )


# --------------------------------------------------------------------------- #
# Certification windows that merely touch at one day
# --------------------------------------------------------------------------- #
def _provider_holding_one_certification_window():
    """A provider in training with one ACTIVE certification over 2026-07-01..2026-12-31."""
    fixtures.create_region(region_code="US-CA")
    provider = fixtures.create_provider(
        "US-CA",
        ADMIN,
        legal_name="Northgate Device Service",
        requested_access_tier="TIER_2_SAFETY",
        technician_count=8,
    )
    fixtures.begin_training(provider["id"], 10, ADMIN)
    certification = fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        course_code="CRS_BATTERY_SAFETY",
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2026-12-31T00:00:00Z",
        exam_score=90,
    )
    return {"provider": provider, "certification": certification}


def test_certification_window_starting_on_the_incumbent_end_day_collides():
    """PRD §3.8: "Validity windows are unique per technician and course: a new closed
    window that overlaps an `ACTIVE` certification for the same `technician_user_id`
    and `course_code` is refused with `ERR_CERTIFICATION_WINDOW_OVERLAP`, and because
    both bounds are inclusive, windows that merely touch at an endpoint do collide."

    Design: Difficulty/resource_temporal_overlap/certification_windows_touching_at_one_day_collide_for_the_same_technician
    """
    bundle = _provider_holding_one_certification_window()

    response = api_client.create_training_certification(
        factories.training_certification_payload(
            bundle["provider"]["id"],
            TECHNICIAN_USER_ID,
            course_code="CRS_BATTERY_SAFETY",
            valid_from="2026-12-31T00:00:00Z",
            valid_until="2027-06-30T00:00:00Z",
            exam_score=88,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_CERTIFICATION_WINDOW_OVERLAP", 409)

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["training_credit_balance"] == 8, (
        f"the refused filing consumes no credit, got {provider['training_credit_balance']}"
    )
    assert provider["active_cert_count"] == 1, provider["active_cert_count"]


def test_certification_window_starting_the_day_after_is_accepted():
    """PRD §3.8: "A filed certification begins with `status` at `ACTIVE`,
    `credits_consumed` at two, and `void_reason` null; the provider's
    `training_credit_balance` drops by two and its `active_cert_count` rises by one,
    while `required_cert_count` is left untouched."

    Design: Difficulty/resource_temporal_overlap/certification_windows_touching_at_one_day_collide_for_the_same_technician
    """
    bundle = _provider_holding_one_certification_window()
    api_client.create_training_certification(
        factories.training_certification_payload(
            bundle["provider"]["id"],
            TECHNICIAN_USER_ID,
            course_code="CRS_BATTERY_SAFETY",
            valid_from="2026-12-31T00:00:00Z",
            valid_until="2027-06-30T00:00:00Z",
            exam_score=88,
        ),
        ADMIN,
    )

    accepted = fixtures.file_certification(
        bundle["provider"]["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        course_code="CRS_BATTERY_SAFETY",
        valid_from="2027-01-01T00:00:00Z",
        valid_until="2027-12-31T00:00:00Z",
        exam_score=88,
    )
    assert accepted["status"] == "ACTIVE", accepted["status"]
    assert accepted["credits_consumed"] == 2, accepted["credits_consumed"]

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["training_credit_balance"] == 6, (
        f"Expected 10 granted less two filings of two, got "
        f"{provider['training_credit_balance']}"
    )
    assert provider["active_cert_count"] == 2, provider["active_cert_count"]

    incumbent = get_success_data(
        api_client.get_training_certification(bundle["certification"]["id"], ADMIN)
    )
    assert incumbent["status"] == "ACTIVE", (
        f"the abutting filing leaves the incumbent alone, got {incumbent['status']}"
    )


# --------------------------------------------------------------------------- #
# Voiding the only certification an authorized provider holds
# --------------------------------------------------------------------------- #
def _authorized_provider_with_one_certification():
    """A provider authorized on exactly one certification out of six granted credits."""
    fixtures.create_region(region_code="US-CA")
    provider = fixtures.create_provider(
        "US-CA",
        ADMIN,
        legal_name="Harborview Electronics Service",
        requested_access_tier="TIER_2_SAFETY",
        technician_count=4,
    )
    fixtures.begin_training(provider["id"], 6, ADMIN)
    certification = fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        course_code="CRS_HIGH_VOLTAGE",
        valid_from="2026-07-15T00:00:00Z",
        valid_until="2027-07-15T00:00:00Z",
        exam_score=94,
    )
    provider = fixtures.decide_authorization(
        provider["id"], "AUTHORIZE", ADMIN, decision_reason="coverage satisfied"
    )
    return {"provider": provider, "certification": certification}


def test_voiding_a_certification_returns_its_two_credits_to_the_balance():
    """PRD §2.10: "For every `RepairProvider`, the sum of
    `training_credit_balance`, the `credits_consumed` totals of that provider's
    certifications whose `status` is `ACTIVE` or `EXPIRED`, and
    `training_credit_forfeited_total` must equal `training_credit_granted_total` at
    all times."
    PRD §3.8: "It compensates: `credits_consumed` returns to zero, the provider's
    `training_credit_balance` rises by two, and `active_cert_count` drops by one."

    Design: Difficulty/compensating_invariant/certification_void_restores_the_provider_training_credit_identity
    """
    bundle = _authorized_provider_with_one_certification()
    voided = fixtures.void_certification(
        bundle["certification"]["id"],
        ADMIN,
        void_reason="exam integrity review overturned the result",
    )

    assert voided["status"] == "VOIDED", voided["status"]
    assert voided["credits_consumed"] == 0, (
        f"a voided row contributes nothing, got {voided['credits_consumed']}"
    )

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["training_credit_balance"] == 6, (
        f"Expected the two consumed credits back on a granted total of 6, got "
        f"{provider['training_credit_balance']}"
    )
    assert provider["training_credit_granted_total"] == 6, (
        f"the grant total never moves on a void, got "
        f"{provider['training_credit_granted_total']}"
    )
    assert provider["training_credit_forfeited_total"] == 0, (
        f"a void is not a forfeiture, got {provider['training_credit_forfeited_total']}"
    )
    assert provider["active_cert_count"] == 0, provider["active_cert_count"]
    assert_training_credit_balanced(
        provider, fixtures.list_provider_certifications(bundle["provider"]["id"])
    )


def test_voiding_the_last_certification_also_suspends_the_provider():
    """PRD §3.8: "When a void pushes `active_cert_count` below `required_cert_count`
    for a provider that was `AUTHORIZED`, the provider is additionally suspended in
    the same request, moving `AUTHORIZED` to `SUSPENDED` with `suspension_reason`
    recorded as `CERT_COVERAGE_LOST`, which in turn revokes that provider's
    still-`VALID` eligibility assessments."

    Design: Difficulty/compensating_invariant/certification_void_restores_the_provider_training_credit_identity
    """
    bundle = _authorized_provider_with_one_certification()
    assert bundle["provider"]["authorization_status"] == "AUTHORIZED", (
        bundle["provider"]["authorization_status"]
    )

    fixtures.void_certification(
        bundle["certification"]["id"],
        ADMIN,
        void_reason="exam integrity review overturned the result",
    )

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["authorization_status"] == "SUSPENDED", (
        f"losing the only certification drops coverage below one, got "
        f"{provider['authorization_status']}"
    )
    assert provider["suspension_reason"] == "CERT_COVERAGE_LOST", (
        f"Expected CERT_COVERAGE_LOST, got {provider['suspension_reason']}"
    )
    assert provider["required_cert_count"] == 1, provider["required_cert_count"]
