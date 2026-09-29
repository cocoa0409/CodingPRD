"""The provider channel and the statutory clock: coverage before authorization, one
technician's writes confined to one shop, an irreversible forfeiture that blocks a void,
and the inclusive last day of the mandated parts window.
"""
from test_helpers import (
    ADMIN,
    COMPLIANCE,
    CUSTOMER,
    TECHNICIAN_USER_ID,
    TECHNICIAN_USER_ID_ALT,
    api_client,
    assert_training_credit_balanced,
    factories,
    fixtures,
    make_repair_provider_tech_headers,
    validate_error,
    validate_success,
)


def _certification_payload(provider_id, technician_user_id, **overrides):
    payload = {
        "course_code": "CRS_BATTERY_SAFETY",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_until": "2027-08-01T00:00:00Z",
        "exam_score": 88,
    }
    payload.update(overrides)
    return factories.training_certification_payload(
        provider_id, technician_user_id, **payload
    )


def test_authorization_waits_for_coverage_and_a_technician_may_not_write_next_door():
    """PRD §3.8: "Registration derives `required_cert_count` as the technician head count
    divided by four and rounded up — one certified technician per four on staff — and
    starts `active_cert_count` at zero, `authorization_status` at `APPLIED`,
    `parts_access_tier` at null, `attested_compliance_score` at null,
    `suspension_reason` at null, and all three training-credit aggregates
    (`training_credit_granted_total`, `training_credit_balance`, and
    `training_credit_forfeited_total`) at zero."
    PRD §3.8: "Authorizing moves `TRAINING_IN_PROGRESS` to `AUTHORIZED` and reinstating
    moves `SUSPENDED` back to `AUTHORIZED`; both require `active_cert_count` to be at
    least `required_cert_count`, otherwise the decision is refused with
    `ERR_TRAINING_COVERAGE_INSUFFICIENT`."
    PRD §3.8: "The certification must be usable: a `valid_until` that is not strictly
    after the logical clock, or an `exam_score` below the passing mark of 70, is refused
    with `ERR_CERTIFICATION_ALREADY_EXPIRED`."
    PRD §2.1: "A technician whose user id resolves to a different provider, or resolves
    to no provider at all, is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` (403)."
    PRD §3.6: "When the buyer class is `AUTHORIZED_PROVIDER`, the part's `safety_class`
    must not demand a stricter parts-access tier than the provider holds: a
    `SAFETY_RESTRICTED_HIGH_VOLTAGE` part requires the provider's `parts_access_tier` to
    be `TIER_1_UNRESTRICTED`, while `SAFETY_RESTRICTED_BATTERY` and `PAIRED_SECURITY`
    parts require either `TIER_1_UNRESTRICTED` or `TIER_2_SAFETY`; a shortfall is refused
    with `ERR_PARTS_ACCESS_TIER_INSUFFICIENT`."

    Design: Corner/validations/provider_onboarding_rejects_premature_authorization_and_cross_provider_writes
    """
    fixtures.create_region(region_code="US-CA")
    shop = fixtures.create_provider(
        "US-CA", technician_count=4, requested_access_tier="TIER_3_STANDARD"
    )
    assert shop["required_cert_count"] == 1, (
        f"four technicians at one certificate per four, got "
        f"{shop['required_cert_count']}"
    )
    assert shop["authorization_status"] == "APPLIED", shop["authorization_status"]
    neighbour = fixtures.create_provider(
        "US-CA", technician_count=4, requested_access_tier="TIER_1_UNRESTRICTED"
    )

    shop = fixtures.begin_training(shop["id"], 4)
    fixtures.begin_training(neighbour["id"], 4)
    assert shop["authorization_status"] == "TRAINING_IN_PROGRESS", (
        shop["authorization_status"]
    )
    assert shop["training_credit_balance"] == 4, shop["training_credit_balance"]

    premature = api_client.decide_provider_authorization(
        shop["id"],
        factories.authorization_decision_payload(
            "AUTHORIZE", granted_access_tier="TIER_3_STANDARD"
        ),
        ADMIN,
    )
    validate_error(premature, "ERR_TRAINING_COVERAGE_INSUFFICIENT", 409)
    assert fixtures.read_provider(shop["id"])["authorization_status"] == (
        "TRAINING_IN_PROGRESS"
    ), "the refused decision leaves the applicant in training"

    failed_exam = api_client.create_training_certification(
        _certification_payload(shop["id"], TECHNICIAN_USER_ID, exam_score=65), ADMIN
    )
    validate_error(failed_exam, "ERR_CERTIFICATION_ALREADY_EXPIRED", 422)

    lapsed_window = api_client.create_training_certification(
        _certification_payload(
            shop["id"],
            TECHNICIAN_USER_ID,
            valid_from="2026-06-01T00:00:00Z",
            valid_until="2026-07-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(lapsed_window, "ERR_CERTIFICATION_ALREADY_EXPIRED", 422)

    certification = validate_success(
        api_client.create_training_certification(
            _certification_payload(shop["id"], TECHNICIAN_USER_ID), ADMIN
        ),
        201,
    )
    assert certification["status"] == "ACTIVE", certification["status"]
    assert certification["credits_consumed"] == 2, certification["credits_consumed"]

    paid_up = fixtures.read_provider(shop["id"])
    assert paid_up["training_credit_balance"] == 2, (
        f"the filing costs two of the four granted units, got "
        f"{paid_up['training_credit_balance']}"
    )
    assert paid_up["active_cert_count"] == 1, paid_up["active_cert_count"]
    assert paid_up["required_cert_count"] == 1, (
        "filing never moves the requirement itself"
    )
    assert_training_credit_balanced(paid_up, [certification])

    authorized = fixtures.decide_authorization(
        shop["id"], "AUTHORIZE", ADMIN, granted_access_tier="TIER_3_STANDARD"
    )
    assert authorized["authorization_status"] == "AUTHORIZED", (
        authorized["authorization_status"]
    )
    assert authorized["attested_compliance_score"] == 100, (
        f"full coverage with no breaches and no calibration attempts, got "
        f"{authorized['attested_compliance_score']}"
    )
    assert authorized["parts_access_tier"] == "TIER_3_STANDARD", (
        "the requested tier is stricter than the tier the score would allow, and the "
        f"stricter of the two wins; got {authorized['parts_access_tier']}"
    )

    technician = make_repair_provider_tech_headers(TECHNICIAN_USER_ID)
    next_door = api_client.create_training_certification(
        _certification_payload(
            neighbour["id"], TECHNICIAN_USER_ID_ALT, course_code="CRS_HIGH_VOLTAGE"
        ),
        technician,
    )
    validate_error(next_door, "ERR_PROVIDER_SCOPE_VIOLATION", 403)
    assert len(fixtures.list_provider_certifications(neighbour["id"])) == 0, (
        "the neighbouring shop holds no certification filed from outside"
    )

    model = fixtures.create_model(
        model_code="CRX-V12",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    battery = fixtures.create_part(
        sku="SKU-V12-BAT",
        safety_class="SAFETY_RESTRICTED_BATTERY",
        list_price_cents=5000,
    )
    fixtures.create_compatibility(
        battery["id"],
        model["id"],
        effective_from="2024-02-01T00:00:00Z",
        install_minutes=40,
    )
    fixtures.publish_part(battery["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-V12-BAT"], safety_warning_count=2
    )

    ruling = fixtures.create_assessment(
        model["id"],
        battery["id"],
        "US-CA",
        technician,
        requester_class="AUTHORIZED_PROVIDER",
        provider_id=shop["id"],
    )
    assert ruling["decision"] == "ELIGIBLE", (
        f"the consumer-only safety branches do not touch a provider request, got "
        f"{ruling['decision']}"
    )
    assert ruling["warranty_impact_class"] == "WARRANTY_PRESERVED", (
        ruling["warranty_impact_class"]
    )

    order = fixtures.create_order(
        ruling["id"],
        "US-CA",
        technician,
        buyer_class="AUTHORIZED_PROVIDER",
        provider_id=shop["id"],
    )
    shortfall = api_client.append_order_line(
        order["id"],
        factories.order_line_payload(battery["id"], order["version"], 1),
        technician,
    )
    validate_error(shortfall, "ERR_PARTS_ACCESS_TIER_INSUFFICIENT", 403)

    unchanged = fixtures.read_order(order["id"], technician)
    assert unchanged["fulfillment_status"] == "DRAFT", (
        unchanged["fulfillment_status"]
    )
    assert len(fixtures.list_lines(order["id"], technician)) == 0, (
        "an eligible ruling does not buy a part the shop's tier cannot reach"
    )


def test_a_void_that_would_restore_swept_credit_to_a_revoked_provider_is_refused():
    """PRD §3.8: "Revoking is a `ComplianceOfficer` decision available from any state
    other than `REVOKED`; it is terminal, it sets `parts_access_tier` to null, and it
    sweeps the whole of `training_credit_balance` into `training_credit_forfeited_total`,
    leaving the balance at zero."
    PRD §3.8: "A void that would restore credit to a provider whose
    `authorization_status` is `REVOKED` — whose balance was already swept into
    `training_credit_forfeited_total` — is refused with `ERR_CREDIT_RESTORE_FORBIDDEN`."
    PRD §2.10: "For every `RepairProvider`, the sum of `training_credit_balance`, the
    `credits_consumed` totals of that provider's certifications whose `status` is
    `ACTIVE` or `EXPIRED`, and `training_credit_forfeited_total` must equal
    `training_credit_granted_total` at all times."

    Design: Corner/validations/void_on_a_revoked_provider_is_rejected_by_the_credit_conservation_guard
    """
    fixtures.create_region(region_code="US-CA")
    provider = fixtures.create_provider(
        "US-CA", technician_count=4, requested_access_tier="TIER_2_SAFETY"
    )
    fixtures.begin_training(provider["id"], 4)
    certification = fixtures.file_certification(
        provider["id"],
        TECHNICIAN_USER_ID,
        ADMIN,
        course_code="CRS_PAIRING_CALIBRATION",
        valid_from="2026-08-01T00:00:00Z",
        valid_until="2027-08-01T00:00:00Z",
        exam_score=90,
    )
    authorized = fixtures.decide_authorization(provider["id"], "AUTHORIZE", ADMIN)
    assert authorized["authorization_status"] == "AUTHORIZED", (
        authorized["authorization_status"]
    )
    assert_training_credit_balanced(authorized, [certification])

    revoked = fixtures.decide_authorization(
        provider["id"],
        "REVOKE",
        COMPLIANCE,
        decision_reason="Repeated unsafe battery handling found on audit.",
    )
    assert revoked["authorization_status"] == "REVOKED", (
        revoked["authorization_status"]
    )
    assert revoked["parts_access_tier"] is None, revoked["parts_access_tier"]
    assert revoked["training_credit_balance"] == 0, (
        f"the sweep empties the balance, got {revoked['training_credit_balance']}"
    )
    assert revoked["training_credit_forfeited_total"] == 2, (
        f"the two unspent units are the ones swept, got "
        f"{revoked['training_credit_forfeited_total']}"
    )
    assert revoked["training_credit_granted_total"] == 4, (
        revoked["training_credit_granted_total"]
    )
    assert_training_credit_balanced(revoked, [certification])

    refused = api_client.void_training_certification(
        certification["id"],
        factories.void_certification_payload(
            void_reason="Filed against the wrong technician."
        ),
        ADMIN,
    )
    validate_error(refused, "ERR_CREDIT_RESTORE_FORBIDDEN", 409)

    rows = fixtures.list_provider_certifications(provider["id"])
    assert len(rows) == 1, len(rows)
    assert rows[0]["status"] == "ACTIVE", (
        f"the refused void leaves the certification active, got {rows[0]['status']}"
    )
    assert rows[0]["void_reason"] is None, rows[0]["void_reason"]
    assert rows[0]["credits_consumed"] == 2, (
        f"the two units stay consumed rather than returning, got "
        f"{rows[0]['credits_consumed']}"
    )

    after = fixtures.read_provider(provider["id"])
    assert after["training_credit_balance"] == 0, after["training_credit_balance"]
    assert after["training_credit_forfeited_total"] == 2, (
        after["training_credit_forfeited_total"]
    )
    assert_training_credit_balanced(after, rows)


def test_confirmation_passes_on_the_last_mandated_day_and_fails_the_next_millisecond():
    """PRD §3.2: "Otherwise `deadline_basis` is `END_OF_PRODUCTION`;
    `parts_available_until` is the end of production advanced by the region's
    `min_parts_availability_years` whole calendar years, taken at the very end of that
    calendar day, namely 23:59:59.999Z; and `documentation_available_until` is the later
    of `parts_available_until` and the end of production advanced by the region's
    `min_documentation_years` whole calendar years, again at 23:59:59.999Z of that day."
    PRD §3.6: "The pinned assessment must not have expired: a confirmation attempted when
    the assessment's `expires_at` falls strictly before the logical clock is refused with
    `ERR_ASSESSMENT_EXPIRED`."
    PRD §3.6: "Where a compliance obligation exists for the order's model and region, the
    logical clock must not have passed that obligation's `parts_available_until`; because
    that deadline is an inclusive end-of-day instant, a clock reading exactly equal to it
    still passes and one millisecond later is refused with `ERR_PARTS_WINDOW_ELAPSED`."

    Design: Corner/validations/confirmation_at_the_inclusive_parts_deadline_passes_and_the_next_day_is_rejected
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-V08",
        product_family="CRX",
        market_release_date="2015-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
        end_of_production_date="2019-11-01T00:00:00Z",
    )
    part = fixtures.create_part(sku="SKU-V08-A", list_price_cents=1000)
    fixtures.create_compatibility(
        part["id"],
        model["id"],
        effective_from="2016-01-01T00:00:00Z",
        install_minutes=20,
    )
    fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-V08-A"], safety_warning_count=2
    )

    obligation = fixtures.create_obligation(model["id"], "US-CA", COMPLIANCE)
    assert obligation["deadline_basis"] == "END_OF_PRODUCTION", (
        obligation["deadline_basis"]
    )
    assert obligation["parts_available_until"].startswith("2026-11-01T23:59:59.999"), (
        f"Expected the end of production advanced by seven whole years, taken at the "
        f"end of that day, got {obligation['parts_available_until']}"
    )
    assert obligation["status"] == "OPEN", (
        f"the clock is still more than ninety days short of the deadline, got "
        f"{obligation['status']}"
    )

    def _acknowledged_order():
        ruling = fixtures.create_assessment(model["id"], part["id"], "US-CA", CUSTOMER)
        order = fixtures.create_order(ruling["id"], "US-CA", CUSTOMER)
        fixtures.append_line(order["id"], part["id"], 1, CUSTOMER)
        fixtures.request_disclosure(order["id"], CUSTOMER)
        fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
        return ruling, order

    early_ruling, early_order = _acknowledged_order()
    assert early_ruling["expires_at"].startswith("2026-09-30T00:00:00"), (
        early_ruling["expires_at"]
    )

    fixtures.move_clock("2026-11-01T23:59:59.999Z")

    stale_ruling = api_client.confirm_order(early_order["id"], CUSTOMER)
    validate_error(stale_ruling, "ERR_ASSESSMENT_EXPIRED", 422)

    _, deadline_order = _acknowledged_order()
    confirmed = validate_success(
        api_client.confirm_order(deadline_order["id"], CUSTOMER), 200
    )
    assert confirmed["fulfillment_status"] == "CONFIRMED", (
        f"a clock reading exactly the inclusive deadline still permits ordering, got "
        f"{confirmed['fulfillment_status']}"
    )
    assert confirmed["confirmed_at"].startswith("2026-11-01T23:59:59.999"), (
        confirmed["confirmed_at"]
    )

    fixtures.move_clock("2026-11-02T00:00:00Z")

    _, late_order = _acknowledged_order()
    elapsed = api_client.confirm_order(late_order["id"], CUSTOMER)
    validate_error(elapsed, "ERR_PARTS_WINDOW_ELAPSED", 422)

    for label, order_id in (("early", early_order["id"]), ("late", late_order["id"])):
        held = fixtures.read_order(order_id, CUSTOMER)
        assert held["fulfillment_status"] == "PENDING_DISCLOSURE", (
            f"{label}: a refused confirmation leaves the order signed but unconfirmed, "
            f"got {held['fulfillment_status']}"
        )
        assert held["confirmed_at"] is None, f"{label}: {held['confirmed_at']}"
