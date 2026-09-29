"""Two refusals the PRD explicitly orders: safety before temporal on order
confirmation, and provider state before credit capacity on certification filing.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    SAFETY,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_ALT,
    api_client,
    factories,
    fixtures,
    validate_error,
)


# --------------------------------------------------------------------------- #
# An acknowledged order whose part was restricted and whose ruling then expired
# --------------------------------------------------------------------------- #
def _acknowledged_order_with_restricted_part_and_expired_ruling():
    """Both the band 6 and the band 9 confirmation conditions hold at once."""
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-A100",
        product_family="CRX",
        market_release_date="2025-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-A100-CELL", list_price_cents=3000)
    fixtures.create_compatibility(
        part["id"], model["id"], effective_from="2025-02-01T00:00:00Z", install_minutes=30
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-A100-CELL"], safety_warning_count=2
    )
    assessment = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    fixtures.append_line(order["id"], part["id"], 1, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    fixtures.restrict_part(
        part["id"],
        SAFETY,
        safety_class="SAFETY_RESTRICTED_BATTERY",
        restriction_reason="thermal runaway advisory",
    )
    fixtures.move_clock("2026-10-11T00:00:00Z")
    return {"assessment": assessment, "part": part, "order": order}


def test_confirm_reports_the_restricted_part_before_the_expired_assessment():
    """PRD §2.9: "On order confirmation, the restricted-part interlock in band 6 is
    evaluated **before** the expired-assessment check in band 9: an order that both
    holds a line on a restricted part and carries an assessment past its validity
    window is rejected with `ERR_ORDER_CONTAINS_RESTRICTED_PART`, not with
    `ERR_ASSESSMENT_EXPIRED`."
    PRD §3.6: "No line may reference a part in `RESTRICTED` status, whatever the
    buyer class, otherwise `ERR_ORDER_CONTAINS_RESTRICTED_PART`."

    Design: Difficulty/priority_pair_validation_conflict/confirm_prefers_restricted_part_error_over_expired_assessment
    """
    bundle = _acknowledged_order_with_restricted_part_and_expired_ruling()

    part = fixtures.read_part(bundle["part"]["id"])
    assert part["status"] == "RESTRICTED", (
        f"Expected the band 6 condition to hold, got {part['status']}"
    )
    assessment = fixtures.read_assessment(bundle["assessment"]["id"])
    assert assessment["expires_at"].startswith("2026-09-30"), (
        "the ruling must already be past its validity window at the 2026-10-11 clock, "
        f"got {assessment['expires_at']}"
    )

    response = api_client.confirm_order(bundle["order"]["id"], CUSTOMER)
    validate_error(response, "ERR_ORDER_CONTAINS_RESTRICTED_PART", 422)


def test_refused_confirm_leaves_the_order_pending_and_commits_no_core_liability():
    """PRD §3.6: "Confirmation stamps `confirmed_at` from the logical clock."
    PRD §3.6: "For each such part, both `core_face_value_committed_cents` and
    `core_liability_outstanding_cents` rise by that part's face value on this order."

    Design: Difficulty/priority_pair_validation_conflict/confirm_prefers_restricted_part_error_over_expired_assessment
    """
    bundle = _acknowledged_order_with_restricted_part_and_expired_ruling()
    api_client.confirm_order(bundle["order"]["id"], CUSTOMER)

    order = fixtures.read_order(bundle["order"]["id"])
    assert order["fulfillment_status"] == "PENDING_DISCLOSURE", (
        f"the refused confirmation must not transition the order, got "
        f"{order['fulfillment_status']}"
    )
    assert order["confirmed_at"] is None, (
        f"a refused confirmation stamps nothing, got {order['confirmed_at']}"
    )

    part = fixtures.read_part(bundle["part"]["id"])
    assert part["core_face_value_committed_cents"] == 0, (
        f"the rejected confirm committed nothing, got "
        f"{part['core_face_value_committed_cents']}"
    )


# --------------------------------------------------------------------------- #
# A suspended provider that has also run out of training credits
# --------------------------------------------------------------------------- #
def _suspended_provider_with_no_credits():
    """Both the band 7 and the band 10 certification conditions hold at once."""
    fixtures.create_region(region_code="US-CA")
    provider = fixtures.create_provider(
        "US-CA",
        ADMIN,
        legal_name="Cascade Devices Repair",
        requested_access_tier="TIER_3_STANDARD",
        technician_count=4,
    )
    fixtures.begin_training(provider["id"], 2, ADMIN)
    fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        valid_from="2026-07-01T00:00:00Z",
        valid_until="2027-07-01T00:00:00Z",
        exam_score=91,
    )
    fixtures.decide_authorization(
        provider["id"],
        "AUTHORIZE",
        ADMIN,
        decision_reason="coverage met",
        granted_access_tier="TIER_3_STANDARD",
    )
    fixtures.decide_authorization(
        provider["id"], "SUSPEND", COMPLIANCE, decision_reason="audit finding open"
    )
    return {"provider": provider}


def test_certification_filing_reports_provider_state_before_credit_shortfall():
    """PRD §2.9: "On certification filing, the provider-state check in band 7 is
    evaluated **before** the training-credit balance check in band 10: a
    certification filed against a provider that is not accepting certifications and
    that also has no credits left is rejected with
    `ERR_PROVIDER_NOT_ACCEPTING_CERTS`, not with `ERR_TRAINING_CREDIT_INSUFFICIENT`."
    PRD §3.8: "The provider must be accepting certifications, meaning its
    `authorization_status` is `TRAINING_IN_PROGRESS` or `AUTHORIZED`; a filing
    against an `APPLIED`, `SUSPENDED`, or `REVOKED` provider is refused with
    `ERR_PROVIDER_NOT_ACCEPTING_CERTS`."

    Design: Difficulty/priority_pair_validation_conflict/certification_prefers_provider_state_error_over_credit_shortfall
    """
    bundle = _suspended_provider_with_no_credits()

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["authorization_status"] == "SUSPENDED", (
        f"Expected the band 7 condition to hold, got {provider['authorization_status']}"
    )
    assert provider["training_credit_balance"] == 0, (
        "the one filed certification consumed both granted credits, got "
        f"{provider['training_credit_balance']}"
    )

    response = api_client.create_training_certification(
        factories.training_certification_payload(
            bundle["provider"]["id"],
            TECHNICIAN_USER_ID_ALT,
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z",
            exam_score=84,
        ),
        ADMIN,
    )
    validate_error(response, "ERR_PROVIDER_NOT_ACCEPTING_CERTS", 409)


def test_refused_certification_filing_creates_no_row_and_moves_no_credits():
    """PRD §3.8: "A filed certification begins with `status` at `ACTIVE`,
    `credits_consumed` at two, and `void_reason` null; the provider's
    `training_credit_balance` drops by two and its `active_cert_count` rises by one,
    while `required_cert_count` is left untouched."
    PRD §3.8: "Finally the provider must be able to pay: a filing when
    `training_credit_balance` is below two is refused with
    `ERR_TRAINING_CREDIT_INSUFFICIENT`."

    Design: Difficulty/priority_pair_validation_conflict/certification_prefers_provider_state_error_over_credit_shortfall
    """
    bundle = _suspended_provider_with_no_credits()
    api_client.create_training_certification(
        factories.training_certification_payload(
            bundle["provider"]["id"],
            TECHNICIAN_USER_ID_ALT,
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z",
            exam_score=84,
        ),
        ADMIN,
    )

    provider = fixtures.read_provider(bundle["provider"]["id"])
    assert provider["active_cert_count"] == 1, (
        f"no certification row may be created by a refused filing, got "
        f"{provider['active_cert_count']}"
    )
    assert provider["training_credit_balance"] == 0, (
        f"Expected the balance untouched at 0, got {provider['training_credit_balance']}"
    )
    assert provider["required_cert_count"] == 1, (
        f"Expected 4 technicians divided by four rounded up, got "
        f"{provider['required_cert_count']}"
    )

    certifications = fixtures.list_provider_certifications(bundle["provider"]["id"])
    assert len(certifications) == 1, (
        f"Expected only the originally filed certification, got {len(certifications)}"
    )
