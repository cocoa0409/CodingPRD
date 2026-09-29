"""Out-of-order work is refused rather than absorbed: the two per-line service steps,
the documentation review chain with its spent rejection budget, and the credit decision
that surfaces one blocker at a time.
"""
from test_helpers import (
    ADMIN,
    CUSTOMER,
    DOCS,
    DOCS_ALT,
    FAILURE_ENGINEER,
    SAFETY,
    api_client,
    factories,
    fixtures,
    get_success_data,
    make_headers,
    validate_error,
    validate_success,
)


def _read_line(line_id, headers=CUSTOMER):
    return get_success_data(api_client.get_order_line(line_id, headers))


def _read_revision(revision_id, headers=DOCS):
    return get_success_data(api_client.get_manual_revision(revision_id, headers))


def test_the_service_steps_refuse_every_out_of_order_call_in_ladder_order():
    """PRD §3.7: "Attempting to authenticate a line whose part has
    `requires_authentication` false is refused with
    `ERR_AUTHENTICATION_NOT_APPLICABLE`."
    PRD §3.7: "It requires the line's `authentication_status` to be either
    `NOT_REQUIRED` or `AUTHENTIC`: a line whose part requires authentication but whose
    authentication is not yet `AUTHENTIC` is refused with
    `ERR_AUTHENTICATION_REQUIRED_FIRST`."
    PRD §3.7: "It also requires the model to have a published `CALIBRATION_PROCEDURE`
    revision, otherwise `ERR_NO_PUBLISHED_CALIBRATION_PROCEDURE`."
    PRD §3.7: "Any further calibrate call — a fourth attempt, or any attempt on an
    already escalated line — is refused with `ERR_CALIBRATION_ATTEMPTS_EXHAUSTED`."
    PRD §2.8: "A line identifier that resolves to a row belonging to a different order
    than the one named in the path is treated as not found and yields
    `ERR_ORDER_LINE_NOT_FOUND`, on both the authenticate and the calibrate actions."

    Design: Corner/validations/authentication_and_calibration_guards_reject_out_of_order_service_steps
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-V06",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    serviced = fixtures.create_part(
        sku="SKU-V06-AUTH",
        list_price_cents=2000,
        requires_authentication=True,
        requires_calibration=True,
    )
    plain = fixtures.create_part(sku="SKU-V06-PLAIN", list_price_cents=1000)
    for part in (serviced, plain):
        fixtures.create_compatibility(
            part["id"],
            model["id"],
            effective_from="2024-02-01T00:00:00Z",
            install_minutes=30,
        )
        fixtures.publish_part(part["id"])
    fixtures.publish_disassembly_guide(
        model["id"], ["SKU-V06-AUTH", "SKU-V06-PLAIN"], safety_warning_count=2
    )

    assessment = fixtures.create_assessment(
        model["id"], serviced["id"], "US-CA", CUSTOMER
    )
    order = fixtures.create_order(assessment["id"], "US-CA", CUSTOMER)
    serviced_line = fixtures.append_line(order["id"], serviced["id"], 1, CUSTOMER)
    plain_line = fixtures.append_line(order["id"], plain["id"], 1, CUSTOMER)
    fixtures.request_disclosure(order["id"], CUSTOMER)
    fixtures.acknowledge_disclosure(order["id"], CUSTOMER)
    fixtures.confirm_order(order["id"], CUSTOMER)
    fixtures.deliver_order(order["id"], ADMIN)

    foreign_assessment = fixtures.create_assessment(
        model["id"], serviced["id"], "US-CA", CUSTOMER
    )
    foreign_order = fixtures.create_order(foreign_assessment["id"], "US-CA", CUSTOMER)
    foreign_line = fixtures.append_line(
        foreign_order["id"], serviced["id"], 1, CUSTOMER
    )

    not_applicable = api_client.authenticate_line(
        order["id"],
        plain_line["id"],
        factories.authenticate_payload("ANY-TOKEN"),
        CUSTOMER,
    )
    validate_error(not_applicable, "ERR_AUTHENTICATION_NOT_APPLICABLE", 422)
    assert _read_line(plain_line["id"])["authentication_status"] == "NOT_REQUIRED", (
        "the refused call leaves the plain line where delivery left it"
    )

    calibrate_too_early = api_client.calibrate_line(
        order["id"],
        serviced_line["id"],
        factories.calibrate_payload(10),
        CUSTOMER,
    )
    validate_error(calibrate_too_early, "ERR_AUTHENTICATION_REQUIRED_FIRST", 409)

    token = _read_line(serviced_line["id"])["pairing_token"]
    authenticated = fixtures.authenticate_line(
        order["id"], serviced_line["id"], token, CUSTOMER
    )
    assert authenticated["authentication_status"] == "AUTHENTIC", (
        authenticated["authentication_status"]
    )
    assert authenticated["calibration_attempt_count"] == 0, (
        f"authentication is not an attempt, got "
        f"{authenticated['calibration_attempt_count']}"
    )

    no_procedure = api_client.calibrate_line(
        order["id"],
        serviced_line["id"],
        factories.calibrate_payload(10),
        CUSTOMER,
    )
    validate_error(no_procedure, "ERR_NO_PUBLISHED_CALIBRATION_PROCEDURE", 422)

    fixtures.publish_calibration_procedure(
        model["id"], ["SKU-V06-AUTH"], safety_warning_count=1
    )

    for expected_status, expected_attempts in (
        ("CALIBRATION_FAILED", 1),
        ("CALIBRATION_FAILED", 2),
        ("CALIBRATION_ESCALATED", 3),
    ):
        line = fixtures.calibrate_line(
            order["id"], serviced_line["id"], 400, CUSTOMER
        )
        assert line["calibration_status"] == expected_status, (
            f"attempt {expected_attempts} expected {expected_status}, got "
            f"{line['calibration_status']}"
        )
        assert line["calibration_attempt_count"] == expected_attempts, (
            line["calibration_attempt_count"]
        )

    exhausted = api_client.calibrate_line(
        order["id"],
        serviced_line["id"],
        factories.calibrate_payload(10),
        CUSTOMER,
    )
    validate_error(exhausted, "ERR_CALIBRATION_ATTEMPTS_EXHAUSTED", 409)
    assert _read_line(serviced_line["id"])["calibration_attempt_count"] == 3, (
        "an in-tolerance reading after the cap changes nothing"
    )

    nested = api_client.calibrate_line(
        order["id"],
        foreign_line["id"],
        factories.calibrate_payload(10),
        CUSTOMER,
    )
    validate_error(nested, "ERR_ORDER_LINE_NOT_FOUND", 404)


def test_the_review_chain_refuses_self_review_then_a_gap_then_a_spent_budget():
    """PRD §2.6: "If that value does not equal the model's current `version`, the create
    is rejected with `ERR_STALE_MODEL_VERSION` (412)."
    PRD §2.11: "On documentation, the individual whose `X-User-ID` was recorded as a
    revision's `authored_by_user_id` may never supply that revision's review decision;
    the attempt is refused with `ERR_SELF_REVIEW_FORBIDDEN` (403)."
    PRD §3.4: "An approval moves `IN_REVIEW` to `APPROVED` and stores
    `reviewed_by_user_id`, and carries three guards of its own: the caller's `X-User-ID`
    must differ from `authored_by_user_id`, or the decision is refused with
    `ERR_SELF_REVIEW_FORBIDDEN`; the parent model's `support_state` must not be
    `SUPPORT_ENDED`, or the approval is refused with `ERR_INVALID_STATE_TRANSITION`; and
    for a `DISASSEMBLY_GUIDE` the `coverage_gap_sku_count` must be exactly zero, or the
    approval is refused with `ERR_REVISION_COVERAGE_GAP`, because a guide that omits a
    published, in-window part of the model is not a complete guide."
    PRD §3.4: "A revision whose `rejection_cycle_count` has already reached three cannot
    be resubmitted; the fourth submission is refused with
    `ERR_REVISION_CYCLE_CAP_REACHED`."
    PRD §3.4: "A `DISASSEMBLY_GUIDE` or `SAFETY_SHEET` may not be published with a
    `safety_warning_count` of zero or with an empty `covered_part_skus` list; either is
    refused with `ERR_SAFETY_WARNINGS_REQUIRED`."

    Design: Corner/validations/documentation_review_chain_rejects_self_review_coverage_gaps_and_a_spent_cycle_budget
    """
    fixtures.create_region(region_code="US-CA")
    model = fixtures.create_model(
        model_code="CRX-V07",
        product_family="CRX",
        market_release_date="2024-01-01T00:00:00Z",
        repairability_tier="TIER_A_SELF_SERVICE",
    )
    for sku, price, minutes in (
        ("SKU-V07-A", 1000, 20),
        ("SKU-V07-B", 1500, 25),
    ):
        part = fixtures.create_part(sku=sku, list_price_cents=price)
        fixtures.create_compatibility(
            part["id"],
            model["id"],
            effective_from="2024-02-01T00:00:00Z",
            install_minutes=minutes,
        )
        fixtures.publish_part(part["id"])

    stale_version = fixtures.model_version(model["id"], DOCS)
    guide = get_success_data(
        api_client.create_manual_revision(
            factories.manual_revision_payload(
                model["id"],
                stale_version,
                doc_type="DISASSEMBLY_GUIDE",
                covered_part_skus=["SKU-V07-A"],
                safety_warning_count=2,
            ),
            DOCS,
        )
    )
    assert guide["coverage_gap_sku_count"] == 1, (
        f"SKU-V07-B is published and in window but not covered, got "
        f"{guide['coverage_gap_sku_count']}"
    )

    reused_version = api_client.create_manual_revision(
        factories.manual_revision_payload(
            model["id"],
            stale_version,
            doc_type="SAFETY_SHEET",
            covered_part_skus=["SKU-V07-A", "SKU-V07-B"],
            safety_warning_count=4,
        ),
        DOCS,
    )
    validate_error(reused_version, "ERR_STALE_MODEL_VERSION", 412)

    submitted = fixtures.submit_revision(guide["id"], DOCS)
    assert submitted["coverage_gap_sku_count"] == 1, (
        f"submission recomputes the gap from the live part population, got "
        f"{submitted['coverage_gap_sku_count']}"
    )

    self_review = api_client.review_manual_revision(
        guide["id"],
        factories.review_decision_payload("APPROVE", review_note="self approval attempt"),
        make_headers("user_docs_001", "SafetyReviewer"),
    )
    validate_error(self_review, "ERR_SELF_REVIEW_FORBIDDEN", 403)

    gap_approval = api_client.review_manual_revision(
        guide["id"],
        factories.review_decision_payload("APPROVE", review_note="looks fine to me"),
        SAFETY,
    )
    validate_error(gap_approval, "ERR_REVISION_COVERAGE_GAP", 422)

    for expected_cycles, note in (
        (1, "add SKU-V07-B"),
        (2, "still incomplete"),
        (3, "third strike"),
    ):
        if expected_cycles > 1:
            fixtures.submit_revision(guide["id"], DOCS)
        rejected = fixtures.review_revision(
            guide["id"], "REJECT", SAFETY, review_note=note
        )
        assert rejected["rejection_cycle_count"] == expected_cycles, (
            f"Expected cycle {expected_cycles}, got {rejected['rejection_cycle_count']}"
        )
        assert rejected["status"] == "DRAFT", (
            f"a rejection returns the revision to draft, got {rejected['status']}"
        )

    spent_budget = api_client.submit_manual_revision(guide["id"], DOCS)
    validate_error(spent_budget, "ERR_REVISION_CYCLE_CAP_REACHED", 409)
    assert _read_revision(guide["id"])["status"] == "DRAFT", (
        "the refused fourth submission leaves the revision where the rejection put it"
    )

    replacement = fixtures.create_draft_revision(
        model["id"],
        DOCS_ALT,
        doc_type="DISASSEMBLY_GUIDE",
        covered_part_skus=["SKU-V07-A", "SKU-V07-B"],
        safety_warning_count=0,
    )
    assert replacement["coverage_gap_sku_count"] == 0, (
        replacement["coverage_gap_sku_count"]
    )
    fixtures.submit_revision(replacement["id"], DOCS_ALT)
    approved = fixtures.review_revision(replacement["id"], "APPROVE", SAFETY)
    assert approved["status"] == "APPROVED", (
        f"complete coverage clears the gap guard, got {approved['status']}"
    )

    warningless = api_client.publish_manual_revision(replacement["id"], SAFETY, {})
    validate_error(warningless, "ERR_SAFETY_WARNINGS_REQUIRED", 422)
    assert fixtures.read_model(model["id"])["documentation_posture"] == "MISSING", (
        "no guide ever reached publication, so the posture never left missing"
    )


def test_the_credit_decision_surfaces_its_three_blockers_one_at_a_time():
    """PRD §3.9: "The requested return quantity plus the quantities of all previously
    filed cases against that line that are not in `REJECTED` status may not exceed the
    line's `quantity`; a filing that would exceed it is refused with
    `ERR_RETURN_QUANTITY_EXCEEDS_LINE`."
    PRD §3.9: "Both branches require the case to be in `ANALYSIS_COMPLETE` and require
    the caller's `X-User-ID` to differ from `analyzed_by_user_id`, otherwise
    `ERR_SELF_DECISION_FORBIDDEN`."
    PRD §3.9: "And the source line must have finished its mandated post-replacement
    service steps: a line whose `calibration_status` is any of `CALIBRATION_REQUIRED`,
    `CALIBRATION_IN_PROGRESS`, `CALIBRATION_FAILED`, or `CALIBRATION_ESCALATED`, or whose
    `authentication_status` is `PENDING_AUTHENTICATION`, is refused with
    `ERR_CALIBRATION_INCOMPLETE`."
    PRD §3.9: "A case whose `root_cause_code` is `CUSTOMER_MISUSE` may never be credited
    and is refused with `ERR_CREDIT_NOT_ALLOWED_FOR_ROOT_CAUSE`."
    PRD §3.9: "Rejecting sets `final_credit_cents` to zero without evaluating any
    root-cause factor at all, and leaves `provisional_credit_cents` untouched as the
    audit record of the goodwill offer that was made."

    Design: Corner/validations/credit_decision_rejects_a_self_decision_then_an_incomplete_calibration_then_the_root_cause
    """
    setup = fixtures.build_orderable_setup(
        region_overrides={"region_code": "US-CA", "max_documentation_fee_cents": 2000},
        model_overrides={
            "model_code": "CRX-V11",
            "product_family": "CRX",
            "market_release_date": "2024-01-01T00:00:00Z",
            "repairability_tier": "TIER_A_SELF_SERVICE",
        },
        part_overrides={
            "sku": "SKU-V11-CAL",
            "list_price_cents": 3000,
            "requires_calibration": True,
        },
        compatibility_overrides={
            "effective_from": "2024-02-01T00:00:00Z",
            "install_minutes": 30,
        },
        safety_warning_count=2,
    )
    fixtures.publish_calibration_procedure(
        setup["model"]["id"], ["SKU-V11-CAL"], safety_warning_count=1
    )
    bundle = fixtures.build_delivered_order(setup, 2, CUSTOMER)
    line = bundle["lines"][0]
    assert line["line_total_cents"] == 6000, line["line_total_cents"]
    assert line["calibration_status"] == "CALIBRATION_REQUIRED", (
        line["calibration_status"]
    )

    over_quantity = api_client.create_defective_return(
        factories.defective_return_payload(line["id"], 3), CUSTOMER
    )
    validate_error(over_quantity, "ERR_RETURN_QUANTITY_EXCEEDS_LINE", 422)

    case = fixtures.create_defective_return(line["id"], 2, CUSTOMER)
    received = fixtures.receive_defective_return(case["id"], ADMIN)
    assert received["provisional_credit_cents"] == 3000, (
        f"Expected half of the full pro-rata basis of 6000, got "
        f"{received['provisional_credit_cents']}"
    )

    fixtures.record_analysis(
        case["id"],
        "CUSTOMER_MISUSE",
        False,
        FAILURE_ENGINEER,
        analysis_note="impact damage on the connector",
    )

    self_decision = api_client.decide_defective_credit(
        case["id"], factories.credit_decision_payload("ISSUE_CREDIT"), FAILURE_ENGINEER
    )
    validate_error(self_decision, "ERR_SELF_DECISION_FORBIDDEN", 403)

    unfinished_service = api_client.decide_defective_credit(
        case["id"], factories.credit_decision_payload("ISSUE_CREDIT"), ADMIN
    )
    validate_error(unfinished_service, "ERR_CALIBRATION_INCOMPLETE", 422)

    calibrated = fixtures.calibrate_line(
        bundle["order"]["id"], line["id"], 100, CUSTOMER
    )
    assert calibrated["calibration_status"] == "CALIBRATION_PASSED", (
        calibrated["calibration_status"]
    )
    assert calibrated["calibration_attempt_count"] == 1, (
        calibrated["calibration_attempt_count"]
    )

    disqualified = api_client.decide_defective_credit(
        case["id"], factories.credit_decision_payload("ISSUE_CREDIT"), ADMIN
    )
    validate_error(disqualified, "ERR_CREDIT_NOT_ALLOWED_FOR_ROOT_CAUSE", 422)

    rejected = validate_success(
        api_client.decide_defective_credit(
            case["id"], factories.credit_decision_payload("REJECT"), ADMIN
        ),
        200,
    )
    assert rejected["status"] == "REJECTED", rejected["status"]
    assert rejected["final_credit_cents"] == 0, rejected["final_credit_cents"]
    assert rejected["provisional_credit_cents"] == 3000, (
        f"the goodwill offer survives as the audit record, got "
        f"{rejected['provisional_credit_cents']}"
    )
