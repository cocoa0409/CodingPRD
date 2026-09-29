"""Three declared refusals read straight from the catalogue: every not-found code on its
own collection, the one attestation code that guards two separate conditions, and the
training-credit shortfall that survives once the provider-state gate is satisfied.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    DOCS,
    FAILURE_ENGINEER,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_ALT,
    api_client,
    assert_training_credit_balanced,
    factories,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_every_declared_not_found_code_is_reachable_through_its_own_collection():
    """PRD §2.8: "Each identifier has its own not-found code: `model_id` yields
    `ERR_MODEL_NOT_FOUND`, `part_id` yields `ERR_PART_NOT_FOUND`, `compatibility_id`
    yields `ERR_COMPATIBILITY_NOT_FOUND`, `revision_id` yields
    `ERR_MANUAL_REVISION_NOT_FOUND`, `assessment_id` yields `ERR_ASSESSMENT_NOT_FOUND`,
    `order_id` yields `ERR_ORDER_NOT_FOUND`, `line_id` yields
    `ERR_ORDER_LINE_NOT_FOUND`, `provider_id` yields `ERR_PROVIDER_NOT_FOUND`,
    `certification_id` yields `ERR_CERTIFICATION_NOT_FOUND`, `case_id` yields
    `ERR_RETURN_CASE_NOT_FOUND`, `obligation_id` yields `ERR_OBLIGATION_NOT_FOUND`, and
    `acknowledgment_id` yields `ERR_ACKNOWLEDGMENT_NOT_FOUND`."
    PRD §2.8: "All twelve are 404 responses."
    PRD §2.8: "Region codes are resolved as a natural key rather than by identifier: any
    `region_code` supplied when creating an obligation, an eligibility assessment, an
    order, or a provider must match an existing regional profile, otherwise the request is
    rejected with `ERR_REGION_PROFILE_NOT_FOUND` (404)."

    Design: Corner/errors/every_declared_not_found_code_is_returned_for_an_unknown_uuid
    """
    model = fixtures.create_model(
        model_code="CRX-E0",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )

    probes = (
        (
            "ERR_MODEL_NOT_FOUND",
            api_client.get_product_model(
                "11111111-1111-1111-1111-111111111111", ADMIN
            ),
        ),
        (
            "ERR_PART_NOT_FOUND",
            api_client.get_part_catalog_item(
                "22222222-2222-2222-2222-222222222222", ADMIN
            ),
        ),
        (
            "ERR_COMPATIBILITY_NOT_FOUND",
            api_client.get_part_compatibility(
                "33333333-3333-3333-3333-333333333333", ADMIN
            ),
        ),
        (
            "ERR_MANUAL_REVISION_NOT_FOUND",
            api_client.get_manual_revision(
                "44444444-4444-4444-4444-444444444444", DOCS
            ),
        ),
        (
            "ERR_ASSESSMENT_NOT_FOUND",
            api_client.get_eligibility_assessment(
                "55555555-5555-5555-5555-555555555555", CUSTOMER
            ),
        ),
        (
            "ERR_ORDER_NOT_FOUND",
            api_client.get_parts_order(
                "66666666-6666-6666-6666-666666666666", CUSTOMER
            ),
        ),
        (
            "ERR_ORDER_LINE_NOT_FOUND",
            api_client.get_order_line(
                "77777777-7777-7777-7777-777777777777", CUSTOMER
            ),
        ),
        (
            "ERR_PROVIDER_NOT_FOUND",
            api_client.get_repair_provider(
                "88888888-8888-8888-8888-888888888888", ADMIN
            ),
        ),
        (
            "ERR_CERTIFICATION_NOT_FOUND",
            api_client.get_training_certification(
                "99999999-9999-9999-9999-999999999999", ADMIN
            ),
        ),
        (
            "ERR_RETURN_CASE_NOT_FOUND",
            api_client.get_defective_return(
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", FAILURE_ENGINEER
            ),
        ),
        (
            "ERR_OBLIGATION_NOT_FOUND",
            api_client.get_compliance_obligation(
                "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", COMPLIANCE
            ),
        ),
        (
            "ERR_ACKNOWLEDGMENT_NOT_FOUND",
            api_client.get_disclosure_acknowledgment(
                "cccccccc-cccc-cccc-cccc-cccccccccccc", COMPLIANCE
            ),
        ),
    )
    for expected_error_id, response in probes:
        validate_error(response, expected_error_id, 404)

    unknown_region = api_client.create_compliance_obligation(
        factories.compliance_obligation_payload(model["id"], "ZZ-ZZ"), COMPLIANCE
    )
    validate_error(unknown_region, "ERR_REGION_PROFILE_NOT_FOUND", 404)

    _, obligation_meta = validate_paginated(
        api_client.list_compliance_obligations(COMPLIANCE, params={"limit": 100})
    )
    assert obligation_meta["total_count"] == 0, (
        f"the refused create stored no obligation, got {obligation_meta['total_count']}"
    )
    _, model_meta = validate_paginated(
        api_client.list_product_models(ADMIN, params={"limit": 100})
    )
    assert model_meta["total_count"] == 1, (
        f"only the one model of the setup exists, got {model_meta['total_count']}"
    )


def test_attestation_is_refused_for_a_false_flag_and_again_for_a_missing_manual():
    """PRD §3.2: "Attestation is refused with `ERR_ATTESTATION_UNSUPPORTED` when
    `documentation_verified` is anything other than true — an attestation must assert
    verification — and equally when the parent model's `documentation_posture` is not
    `CURRENT`, so both `STALE` and `MISSING` block it."
    PRD §3.2: "Third: when the model's `documentation_posture` is `MISSING`, the status is
    `BREACHED_DOCUMENTATION`."
    PRD §3.2: "A successful attestation stores `last_attested_at` from the logical clock,
    `last_attested_by_user_id` from the caller's `X-User-ID`, and the
    `documentation_verified` flag, then rolls the model's posture up again; an `ATTESTED`
    row counts as open, never as breached, so the posture drops back to `OPEN` or `WATCH`
    when no sibling obligation is breached."
    PRD §2.7: "One consequence is worth stating plainly: an `ATTESTED` obligation status
    is written only by the attestation action and is not preserved by re-evaluation, so
    the next sweep or cascade re-derives one of the other five values."

    Design: Corner/errors/attestation_is_rejected_while_verification_is_false_or_the_posture_is_not_current
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-E7",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    part = fixtures.create_part(sku="SKU-E7-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])
    obligation = fixtures.create_obligation(model["id"], "US-CA", COMPLIANCE)

    assert obligation["status"] == "BREACHED_DOCUMENTATION", (
        f"a published part but no published manual, got {obligation['status']}"
    )
    assert obligation["breach_count"] == 1, obligation["breach_count"]
    assert fixtures.read_model(model["id"])["documentation_posture"] == "MISSING", (
        "no guide has ever been published for this model"
    )

    unverified = api_client.attest_obligation(
        obligation["id"],
        factories.attestation_payload(
            attestation_note="records reviewed", documentation_verified=False
        ),
        COMPLIANCE,
    )
    validate_error(unverified, "ERR_ATTESTATION_UNSUPPORTED", 422)

    verified_but_undocumented = api_client.attest_obligation(
        obligation["id"],
        factories.attestation_payload(
            attestation_note="records reviewed", documentation_verified=True
        ),
        COMPLIANCE,
    )
    validate_error(verified_but_undocumented, "ERR_ATTESTATION_UNSUPPORTED", 422)

    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-E7-A"], safety_warning_count=2
    )
    assert fixtures.read_model(model["id"])["documentation_posture"] == "CURRENT", (
        "the published guide covers the only published in-window part"
    )
    recovered = get_success_data(
        api_client.get_compliance_obligation(obligation["id"], COMPLIANCE)
    )
    assert recovered["status"] == "OPEN", (
        f"the publication cascade re-derived the obligation, got {recovered['status']}"
    )

    attested = validate_success(
        api_client.attest_obligation(
            obligation["id"],
            factories.attestation_payload(
                attestation_note="manual published and verified",
                documentation_verified=True,
            ),
            COMPLIANCE,
        ),
        200,
    )
    assert attested["status"] == "ATTESTED", attested["status"]
    assert attested["documentation_verified"] is True, (
        attested["documentation_verified"]
    )
    assert attested["last_attested_by_user_id"] == "user_compliance_001", (
        attested["last_attested_by_user_id"]
    )
    assert attested["last_attested_at"].startswith("2026-08-01T00:00:00"), (
        attested["last_attested_at"]
    )

    fixtures.run_sweep(model_id=model["id"])
    swept = get_success_data(
        api_client.get_compliance_obligation(obligation["id"], COMPLIANCE)
    )
    assert swept["status"] == "OPEN", (
        f"the attested value is not preserved by re-evaluation, got {swept['status']}"
    )
    assert swept["breach_count"] == 1, (
        f"the sweep found nothing new to hold against it, got {swept['breach_count']}"
    )


def test_a_spent_credit_balance_refuses_the_next_certification_on_its_own():
    """PRD §3.8: "Finally the provider must be able to pay: a filing when
    `training_credit_balance` is below two is refused with
    `ERR_TRAINING_CREDIT_INSUFFICIENT`."
    PRD §3.8: "The provider must be accepting certifications, meaning its
    `authorization_status` is `TRAINING_IN_PROGRESS` or `AUTHORIZED`; a filing against an
    `APPLIED`, `SUSPENDED`, or `REVOKED` provider is refused with
    `ERR_PROVIDER_NOT_ACCEPTING_CERTS`."
    PRD §3.8: "A filed certification begins with `status` at `ACTIVE`, `credits_consumed`
    at two, and `void_reason` null; the provider's `training_credit_balance` drops by two
    and its `active_cert_count` rises by one, while `required_cert_count` is left
    untouched."
    PRD §3.8: "Registration derives `required_cert_count` as the technician head count
    divided by four and rounded up — one certified technician per four on staff — and
    starts `active_cert_count` at zero, `authorization_status` at `APPLIED`,
    `parts_access_tier` at null, `attested_compliance_score` at null,
    `suspension_reason` at null, and all three training-credit aggregates
    (`training_credit_granted_total`, `training_credit_balance`, and
    `training_credit_forfeited_total`) at zero."

    Design: Corner/errors/certification_is_rejected_once_the_providers_training_credit_balance_is_spent
    """
    fixtures.create_region(region_code="US-CA")
    provider = fixtures.create_provider(
        "US-CA", technician_count=8, requested_access_tier="TIER_2_SAFETY"
    )
    assert provider["required_cert_count"] == 2, (
        f"eight technicians at one certificate per four, got "
        f"{provider['required_cert_count']}"
    )
    funded = fixtures.begin_training(provider["id"], 2)
    assert funded["training_credit_balance"] == 2, (
        f"exactly one certification's worth of credit was granted, got "
        f"{funded['training_credit_balance']}"
    )

    certification = fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        course_code="CRS_GENERAL_REPAIR",
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2027-08-01T00:00:00Z",
        exam_score=90,
    )
    assert certification["credits_consumed"] == 2, certification["credits_consumed"]

    spent = fixtures.read_provider(provider["id"])
    assert spent["training_credit_balance"] == 0, spent["training_credit_balance"]
    assert spent["active_cert_count"] == 1, spent["active_cert_count"]
    assert spent["authorization_status"] == "TRAINING_IN_PROGRESS", (
        f"the provider is still squarely inside the accepting set, got "
        f"{spent['authorization_status']}"
    )

    unaffordable = api_client.create_training_certification(
        factories.training_certification_payload(
            provider["id"],
            TECHNICIAN_USER_ID_ALT,
            course_code="CRS_GENERAL_REPAIR",
            valid_from="2026-08-01T00:00:00Z",
            valid_until="2027-08-01T00:00:00Z",
            exam_score=90,
        ),
        ADMIN,
    )
    validate_error(unaffordable, "ERR_TRAINING_CREDIT_INSUFFICIENT", 409)

    rows = fixtures.list_provider_certifications(provider["id"])
    assert len(rows) == 1, (
        f"the refused filing created no certification row, got {len(rows)}"
    )
    assert rows[0]["id"] == certification["id"], rows[0]["id"]
    assert rows[0]["status"] == "ACTIVE", rows[0]["status"]

    short_coverage = api_client.decide_provider_authorization(
        provider["id"],
        factories.authorization_decision_payload(
            "AUTHORIZE", decision_reason="premature"
        ),
        ADMIN,
    )
    validate_error(short_coverage, "ERR_TRAINING_COVERAGE_INSUFFICIENT", 409)

    unchanged = fixtures.read_provider(provider["id"])
    assert unchanged["training_credit_granted_total"] == 2, (
        unchanged["training_credit_granted_total"]
    )
    assert unchanged["training_credit_forfeited_total"] == 0, (
        unchanged["training_credit_forfeited_total"]
    )
    assert_training_credit_balanced(unchanged, rows)
