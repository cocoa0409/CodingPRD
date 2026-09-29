"""Each declared refusal reached from its own distinct cause.

Several refusals that read alike are separated here on purpose: three different
uniqueness rules split across three error ids, two different evidence floors
share one error id, and the same dispute filing that succeeds at the deadline
instant is refused one day later.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    make_freight_inspector_headers,
    make_pricing_analyst_headers,
    make_shipper_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()
AUDITOR = fx.AUDITOR_HEADERS

CLOCK = "2026-01-10T08:00:00Z"

STANDARD_LINE = {
    "line_no": 1,
    "declared_class_code": 70,
    "declared_weight_lb": 400,
    "pieces": 4,
    "declared_length_in": 48.0,
    "declared_width_in": 40.0,
    "declared_height_in": 48.0,
}

SECOND_LINE_BODY = {
    "line_no": 1,
    "declared_class_code": 100,
    "declared_weight_lb": 700,
    "pieces": 2,
    "declared_length_in": 40.0,
    "declared_width_in": 40.0,
    "declared_height_in": 40.0,
}


def _add_line(shipment_id, customer_id, profile_id, **overrides):
    return api_client.create_shipment_line(
        shipment_id,
        factories.create_shipment_line_payload(profile_id, **overrides),
        make_shipper_headers(customer_id),
    )


def _tender(customer_id, terminal_id, pro_number, **overrides):
    return api_client.create_shipment(
        factories.create_shipment_payload(
            customer_id, terminal_id, pro_number, **overrides
        ),
        make_shipper_headers(customer_id),
    )


# ==========================================================================
# Malformed input, separated field by field
# ==========================================================================


def test_five_malformed_fields_report_five_different_error_ids():
    """A bad discount, class, dimension, bracket table and interval each own a code.

    PRD: "Domain-typed shape checks — `ERR_INVALID_CLASS_CODE` when a class-code
    field is not a recognized classification code, `ERR_INVALID_DIMENSIONS` when a
    dimension is zero, negative or carries more than one decimal place,
    `ERR_INVALID_DENSITY_BREAKS` when a bracket table is malformed, and
    `ERR_INVALID_INTERVAL` when an interval's end is not strictly after its start."

    Design: Corner/errors/shape_and_domain_typed_input_errors_are_triggerable
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.tender_shipment(env["customer_id"], env["terminal_id"], "PROX001")

    bad_discount = api_client.create_rate_program(
        factories.create_rate_program_payload(env["customer_id"], discount_pct=0.9),
        ANALYST,
    )
    bad_class = _add_line(
        tendered["id"],
        env["customer_id"],
        env["commodity_profile_id"],
        declared_class_code=77,
    )
    bad_dimension = _add_line(
        tendered["id"],
        env["customer_id"],
        env["commodity_profile_id"],
        declared_length_in=48.25,
    )
    bad_breaks = api_client.create_tariff_version(
        factories.create_tariff_version_payload(
            code="NMFC-2027A",
            effective_at="2027-01-01T00:00:00Z",
            density_breaks=[
                {"min_density_pcf": 15, "class_code": 70},
                {"min_density_pcf": 30, "class_code": 60},
            ],
        ),
        ANALYST,
    )
    empty_agreement_interval = api_client.create_exception_agreement(
        factories.create_exception_agreement_payload(
            env["customer_id"],
            env["commodity_profile_id"],
            "2026-02-01T00:00:00Z",
            "2026-02-01T00:00:00Z",
            agreement_type="EXCEPTION_CLASS",
            agreed_class_code=92.5,
        ),
        ANALYST,
    )
    reversed_sample_window = api_client.create_repricing_run(
        factories.create_repricing_run_payload(
            env["tariff_version_id"],
            "2026-01-01T00:00:00Z",
            "2025-12-01T00:00:00Z",
            scope="ALL_ACTIVE",
        ),
        ANALYST,
    )

    validate_error(bad_discount, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400)
    validate_error(
        bad_class, ApiErrorId.ERR_INVALID_CLASS_CODE.value, expected_status=422
    )
    validate_error(
        bad_dimension, ApiErrorId.ERR_INVALID_DIMENSIONS.value, expected_status=422
    )
    validate_error(
        bad_breaks, ApiErrorId.ERR_INVALID_DENSITY_BREAKS.value, expected_status=422
    )
    validate_error(
        empty_agreement_interval,
        ApiErrorId.ERR_INVALID_INTERVAL.value,
        expected_status=422,
    )
    validate_error(
        reversed_sample_window,
        ApiErrorId.ERR_INVALID_INTERVAL.value,
        expected_status=422,
    )
    shipment = fx.get_shipment(tendered["id"])
    assert shipment["line_count"] == 0
    assert shipment["declared_total_weight_lb"] == 0
    assert fx.list_shipment_lines_for(tendered["id"]) == []


def test_three_uniqueness_rules_report_three_different_error_ids():
    """A duplicate code is a 400, a duplicate PRO and a duplicate line ordinal are 409s.

    PRD: "a shipment's `pro_number` is globally unique and a duplicate yields
    `ERR_DUPLICATE_PRO_NUMBER`; a line's `line_no` is unique within its own shipment
    and a duplicate yields `ERR_DUPLICATE_LINE_NO`."

    Design: Corner/errors/uniqueness_violations_split_across_three_error_ids
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    first = fx.setup_shipment_with_lines(env, "PROX010", line_specs=[STANDARD_LINE])
    second = fx.tender_shipment(env["customer_id"], env["terminal_id"], "PROX011")

    duplicate_terminal = api_client.create_terminal(
        factories.create_terminal_payload(code="TRM1", name="Chicago Dock Annex"),
        ANALYST,
    )
    duplicate_customer = api_client.create_customer(
        factories.create_customer_payload(account_code="ACME", name="Acme Mfg West"),
        ANALYST,
    )
    duplicate_release = api_client.create_tariff_version(
        factories.create_tariff_version_payload(
            code="NMFC-2026A", effective_at="2026-06-01T00:00:00Z"
        ),
        ANALYST,
    )
    duplicate_pro = _tender(env["customer_id"], env["terminal_id"], "PROX010")
    duplicate_line_no = _add_line(
        first["shipment_id"],
        env["customer_id"],
        env["commodity_profile_id"],
        **SECOND_LINE_BODY,
    )
    same_line_no_elsewhere = _add_line(
        second["id"],
        env["customer_id"],
        env["commodity_profile_id"],
        **SECOND_LINE_BODY,
    )

    validate_error(
        duplicate_terminal, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )
    validate_error(
        duplicate_customer, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )
    validate_error(
        duplicate_release, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=400
    )
    validate_error(
        duplicate_pro, ApiErrorId.ERR_DUPLICATE_PRO_NUMBER.value, expected_status=409
    )
    validate_error(
        duplicate_line_no, ApiErrorId.ERR_DUPLICATE_LINE_NO.value, expected_status=409
    )
    accepted_elsewhere = validate_success(same_line_no_elsewhere, expected_status=201)
    assert accepted_elsewhere["line_no"] == 1, (
        "line ordinal uniqueness is scoped to one shipment"
    )
    first_after = fx.get_shipment(first["shipment_id"])
    second_after = fx.get_shipment(second["id"])
    assert first_after["line_count"] == 1
    assert first_after["declared_total_weight_lb"] == 400
    assert second_after["line_count"] == 1
    assert second_after["declared_total_weight_lb"] == 700


# ==========================================================================
# Preconditions on tender, billing and dock capture
# ==========================================================================


def test_tender_billing_and_capture_each_refuse_their_own_missing_precondition():
    """No program, no effective standard, no lines, an unknown ordinal and a hold.

    PRD: "Fiscal preconditions — `ERR_NO_ACTIVE_RATE_PROGRAM`,
    `ERR_NO_EFFECTIVE_TARIFF`, `ERR_ZERO_DELTA_NOTICE` and `ERR_NO_SHIPMENT_LINES`,
    guarding bill-of-lading tender, program approval, notice issuance and shipment
    billing."

    Design: Corner/errors/tender_billing_and_capture_precondition_errors_are_triggerable
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    programless = fx.create_customer(account_code="NOPRG", name="No Program Inc")
    tendered = fx.tender_shipment(env["customer_id"], env["terminal_id"], "PROX020")

    no_program = _tender(programless["id"], env["terminal_id"], "PROX021")
    validate_error(
        no_program, ApiErrorId.ERR_NO_ACTIVE_RATE_PROGRAM.value, expected_status=422
    )

    before_any_standard = _tender(
        env["customer_id"],
        env["terminal_id"],
        "PROX022",
        pickup_at="2025-06-01T00:00:00Z",
    )
    validate_error(
        before_any_standard, ApiErrorId.ERR_NO_EFFECTIVE_TARIFF.value, expected_status=422
    )

    bill_without_lines = api_client.bill_shipment(tendered["id"], {}, ANALYST)
    validate_error(
        bill_without_lines, ApiErrorId.ERR_NO_SHIPMENT_LINES.value, expected_status=422
    )

    capture_without_lines = api_client.create_capture_event(
        factories.create_capture_event_payload(
            tendered["id"], 400, fx.single_line_measurement(400), device_type="SCALE"
        ),
        env["operator_headers"],
    )
    validate_error(
        capture_without_lines,
        ApiErrorId.ERR_NO_SHIPMENT_LINES.value,
        expected_status=422,
    )

    fx.add_shipment_line(
        tendered["id"], env["customer_id"], env["commodity_profile_id"], **STANDARD_LINE
    )
    close_before_billing = api_client.close_shipment(tendered["id"], {}, ANALYST)
    validate_error(
        close_before_billing,
        ApiErrorId.ERR_SHIPMENT_NOT_BILLED.value,
        expected_status=409,
    )

    unknown_ordinal = api_client.create_capture_event(
        factories.create_capture_event_payload(
            tendered["id"], 400, fx.single_line_measurement(400, line_no=7)
        ),
        env["operator_headers"],
    )
    validate_error(
        unknown_ordinal, ApiErrorId.ERR_LINE_NO_MISMATCH.value, expected_status=422
    )

    fx.change_posture(env["customer_id"], "CREDIT_HOLD")
    on_hold = _tender(env["customer_id"], env["terminal_id"], "PROX023")
    validate_error(
        on_hold, ApiErrorId.ERR_CUSTOMER_CREDIT_HOLD.value, expected_status=409
    )

    assert fx.get_customer(env["customer_id"])["billing_posture"] == "CREDIT_HOLD"
    shipment = fx.get_shipment(tendered["id"])
    assert shipment["billing_status"] == "UNBILLED"
    assert shipment["class_status"] == "DECLARED"
    assert shipment["measured_total_weight_lb"] is None
    assert fx.get_terminal(env["terminal_id"])["captures_since_calibration"] == 0, (
        "neither refused capture was recorded"
    )


# ==========================================================================
# Evidence floors and an unpublished standard
# ==========================================================================


def test_a_missing_basis_two_evidence_floors_and_a_draft_standard_each_refuse():
    """One error id guards two different floors; the run is opened but not modelled.

    PRD: "Three evidence floors apply, all reported through
    `ERR_INSUFFICIENT_EVIDENCE` at HTTP 422. An inspection finding needs at least
    two photographs attached before it can be accepted. A correction notice needs an
    evidence bundle of at least one item before it can be issued. A dispute needs at
    least one attached document before it can be filed."

    Design: Corner/errors/evidence_basis_and_unpublished_standard_errors_are_triggerable
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    unpublished = fx.create_draft_tariff_version(
        code="NMFC-2027A", effective_at="2027-01-01T00:00:00Z"
    )
    scenario = fx.setup_billed_shipment(
        env=env, pro_number="PROX030", line_specs=[STANDARD_LINE]
    )
    line_id = scenario["line_ids"][0]

    no_basis = api_client.create_correction_notice(
        factories.create_correction_notice_payload(
            scenario["shipment_id"],
            fx.get_shipment(scenario["shipment_id"])["version"],
            notice_type="RECLASS",
        ),
        AUDITOR,
    )
    validate_error(
        no_basis, ApiErrorId.ERR_NO_RECLASS_BASIS.value, expected_status=422
    )

    under_photographed = fx.record_finding(
        line_id, found_class_code=250, evidence_photo_count=1
    )
    refused_acceptance = api_client.accept_inspection_finding(
        under_photographed["id"], {}, AUDITOR
    )
    validate_error(
        refused_acceptance,
        ApiErrorId.ERR_INSUFFICIENT_EVIDENCE.value,
        expected_status=422,
    )
    assert fx.get_shipment_line(line_id)["effective_class_code"] == 70
    stored_finding = validate_success(
        api_client.get_inspection_finding(under_photographed["id"], AUDITOR)
    )
    assert stored_finding["status"] == "RECORDED"

    fx.record_and_accept_finding(line_id, found_class_code=250, evidence_photo_count=3)
    notice = fx.draft_manual_notice(scenario["shipment_id"], notice_type="RECLASS")
    assert notice["evidence_bundle_count"] == 4, (
        f"no capture cited, plus one for the accepted finding itself and its three "
        f"photographs, got {notice['evidence_bundle_count']}"
    )
    assert notice["uses_inspection_findings"] is True
    assert notice["final_delta_cents"] == 22990
    fx.issue_notice(notice["id"])

    undocumented_dispute = api_client.create_dispute(
        factories.create_dispute_payload(notice["id"], evidence_doc_count=0),
        make_shipper_headers(env["customer_id"]),
    )
    validate_error(
        undocumented_dispute,
        ApiErrorId.ERR_INSUFFICIENT_EVIDENCE.value,
        expected_status=422,
    )
    issued = fx.get_notice(notice["id"])
    assert issued["status"] == "ISSUED"
    assert issued["dispute_round_count"] == 0

    run = fx.create_repricing_run(
        unpublished["id"],
        "2026-01-01T00:00:00Z",
        "2026-02-01T00:00:00Z",
        scope="ALL_ACTIVE",
    )
    assert run["status"] == "DRAFT"

    modelling = api_client.model_repricing_run(run["id"], {}, ANALYST)

    validate_error(
        modelling, ApiErrorId.ERR_TARIFF_NOT_PUBLISHED.value, expected_status=409
    )
    assert fx.get_repricing_run(run["id"])["modeled_at"] is None
    assert fx.get_tariff_version(unpublished["id"])["status"] == "DRAFT"


# ==========================================================================
# The closed dispute window
# ==========================================================================


def test_a_dispute_filed_one_day_past_the_deadline_is_refused():
    """The notice stays ISSUED and the sweep is still free to uphold it.

    PRD: "that the current logical instant is at or before the notice's
    `dispute_deadline_at`, or `ERR_DISPUTE_WINDOW_CLOSED`"

    Design: Corner/errors/dispute_filed_after_the_deadline_is_rejected
    """
    scenario = fx.setup_issued_notice_scenario(pro_number="PROX040")
    assert scenario["notice"]["dispute_deadline_at"].startswith("2026-02-09T08:00:00")
    fx.set_clock("2026-02-10T08:00:00Z")

    too_late = api_client.create_dispute(
        factories.create_dispute_payload(scenario["notice_id"], evidence_doc_count=4),
        make_shipper_headers(scenario["customer_id"]),
    )

    validate_error(
        too_late, ApiErrorId.ERR_DISPUTE_WINDOW_CLOSED.value, expected_status=409
    )
    unchanged = fx.get_notice(scenario["notice_id"])
    assert unchanged["status"] == "ISSUED"
    assert unchanged["dispute_round_count"] == 0
    assert unchanged["supplement_request_count"] == 0
    assert unchanged["dispute_deadline_at"].startswith("2026-02-09T08:00:00"), (
        f"the refused filing does not move the deadline, "
        f"got {unchanged['dispute_deadline_at']}"
    )

    swept = fx.sweep_notices()

    assert swept["swept_count"] == 1
    upheld = fx.get_notice(scenario["notice_id"])
    assert upheld["status"] == "UPHELD"
    assert upheld["resolved_at"].startswith("2026-02-10T08:00:00")
    assert fx.get_shipment(scenario["shipment_id"])["assessed_total_cents"] == 45314
