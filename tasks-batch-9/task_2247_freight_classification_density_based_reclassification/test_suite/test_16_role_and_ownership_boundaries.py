"""Who may call what, whose rows they may touch, and who may sign off on whom.

Authentication is checked before authorization, authorization before ownership,
and ownership before any domain logic. The two entity-backed roles are scoped to
their own row, and one signature rule is keyed to the acting person rather than
to the role they present.
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    build_user_headers,
    factories,
    make_classification_auditor_headers,
    make_dispute_reviewer_headers,
    make_freight_inspector_headers,
    make_headers_without_role,
    make_headers_without_user_id,
    make_pricing_analyst_headers,
    make_shipper_headers,
    make_terminal_operator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import fixtures as fx

ANALYST = make_pricing_analyst_headers()
INSPECTOR = make_freight_inspector_headers("insp-1")
AUDITOR = make_classification_auditor_headers("aud-1")
REVIEWER = make_dispute_reviewer_headers("rev-1")

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


def _shipments_visible_to(headers):
    return validate_paginated(api_client.list_shipments(headers, params={"limit": 100}))


# ==========================================================================
# The shared read surface
# ==========================================================================


def test_all_six_roles_read_the_same_bill_of_lading():
    """The shared read surface is genuinely shared, and reading changes nothing.

    PRD: "Every request must carry two headers: `X-User-ID`, identifying the acting
    principal, and `X-User-Role`, declaring the capacity in which it acts. Six roles
    exist, and their names are spelled exactly as follows: `PricingAnalyst`,
    `TerminalOperator`, `FreightInspector`, `ClassificationAuditor`,
    `DisputeReviewer` and `Shipper`."

    Design: Corner/rbac/every_role_reaches_the_shared_shipment_read_surface
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_billed_shipment(
        env=env, pro_number="PROR001", line_specs=[STANDARD_LINE]
    )
    readers = [
        ANALYST,
        make_terminal_operator_headers(env["terminal_id"]),
        INSPECTOR,
        AUDITOR,
        REVIEWER,
        make_shipper_headers(env["customer_id"]),
    ]

    reads = [
        validate_success(api_client.get_shipment(scenario["shipment_id"], headers))
        for headers in readers
    ]

    assert len(reads) == 6
    for shipment in reads:
        assert shipment["billing_status"] == "BILLED"
        assert shipment["original_charge_cents"] == 12500
    versions = {shipment["version"] for shipment in reads}
    assert len(versions) == 1, (
        f"a read is not a mutation, so every reader saw one version, got {versions}"
    )

    line = validate_success(
        api_client.get_shipment_line(scenario["line_ids"][0], REVIEWER)
    )
    assert line["effective_class_code"] == 70
    assert line["classification_source"] == "BOL_DECLARED"
    assert line["declared_cubic_ft"] == 213.33
    assert line["declared_density_pcf"] == 1.88


# ==========================================================================
# Authorization, authentication and ownership
# ==========================================================================


def test_seven_exclusive_operations_refuse_the_wrong_role():
    """Even a caller who could functionally do the work is refused on role alone.

    PRD: "A request whose role is well-formed but is not among the roles authorized
    for the target operation is rejected with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/role_cannot_invoke_another_roles_exclusive_operation
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    scenario = fx.setup_captured_shipment_with_draft_notice(
        env=env, pro_number="PROR010"
    )
    finding = fx.record_finding(
        scenario["line_ids"][0], found_class_code=250, evidence_photo_count=3
    )
    fx.issue_notice(scenario["notice_id"])
    dispute = fx.file_dispute(scenario["notice_id"], env["customer_id"])

    attempts = [
        api_client.create_tariff_version(
            factories.create_tariff_version_payload(code="NMFC-2027A"), AUDITOR
        ),
        api_client.create_capture_event(
            factories.create_capture_event_payload(
                scenario["shipment_id"],
                600,
                fx.single_line_measurement(600),
                device_type="SCALE",
            ),
            INSPECTOR,
        ),
        api_client.accept_inspection_finding(finding["id"], {}, INSPECTOR),
        api_client.issue_correction_notice(scenario["notice_id"], {}, REVIEWER),
        api_client.resolve_dispute(
            dispute["id"], factories.resolve_dispute_payload("OVERTURNED"), AUDITOR
        ),
        api_client.create_shipment(
            factories.create_shipment_payload(
                env["customer_id"], env["terminal_id"], "PROR011"
            ),
            ANALYST,
        ),
        api_client.create_notice_sweep({}, AUDITOR),
    ]

    for attempt in attempts:
        validate_error(
            attempt, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, expected_status=403
        )
    stored_finding = validate_success(
        api_client.get_inspection_finding(finding["id"], AUDITOR)
    )
    assert stored_finding["status"] == "RECORDED"
    assert stored_finding["accepted_by_user_id"] is None
    notice = fx.get_notice(scenario["notice_id"])
    assert notice["status"] == "DISPUTED"
    assert notice["issued_by_user_id"] == "aud-1"
    assert fx.get_dispute(dispute["id"])["status"] == "OPEN"
    assert fx.list_credit_memos_for(env["customer_id"]) == []
    rows, meta = _shipments_visible_to(ANALYST)
    assert meta["total_count"] == 1
    assert rows[0]["id"] == scenario["shipment_id"]
    assert fx.get_shipment(scenario["shipment_id"])["assessed_total_cents"] == 45314, (
        "not one denied call moved the money"
    )
    captures, capture_meta = validate_paginated(
        api_client.list_capture_events(
            ANALYST, params={"shipment_id": scenario["shipment_id"], "limit": 100}
        )
    )
    assert capture_meta["total_count"] == 1
    assert captures[0]["measured_total_weight_lb"] == 520


def test_a_missing_or_unknown_role_is_refused_before_the_body_is_read():
    """Authentication precedes authorization and precedes payload validation.

    PRD: "A request missing either header, or naming a role outside those six, is
    rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_or_unknown_role_header_is_unauthenticated
    """
    fx.set_clock(CLOCK)
    terminal = fx.create_terminal()
    customer = fx.create_customer()

    no_role_header = api_client.list_shipments(make_headers_without_role())
    unknown_role = api_client.create_customer(
        factories.create_customer_payload(account_code="GHOST", name="Ghost Freight"),
        build_user_headers("ghost-1", "TariffClerk"),
    )
    shipper_without_identity = api_client.create_shipment(
        factories.create_shipment_payload(customer["id"], terminal["id"], "PROR020"),
        make_headers_without_user_id("Shipper"),
    )
    operator_without_identity = api_client.create_capture_event(
        {
            "shipment_id": customer["id"],
            "device_type": "NOT_A_DEVICE",
            "measured_total_weight_lb": -5,
            "line_measurements": [],
        },
        make_headers_without_user_id("TerminalOperator"),
    )

    validate_error(
        no_role_header, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
    )
    validate_error(
        unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, expected_status=401
    )
    validate_error(
        shipper_without_identity,
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )
    validate_error(
        operator_without_identity,
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )
    rows, meta = _shipments_visible_to(ANALYST)
    assert rows == []
    assert meta["total_count"] == 0
    assert fx.get_customer(customer["id"])["account_code"] == "ACME"
    assert fx.get_terminal(terminal["id"])["code"] == "TRM1"


def test_a_shipper_and_a_terminal_are_scoped_to_their_own_rows():
    """Cross-tenant writes are refused, while the scoped list simply narrows.

    PRD: "Violating an entity-backed ownership rule yields
    `ERR_NOT_RESOURCE_OWNER`. Ownership is enforced on bill-of-lading tender, line
    addition, dock capture, dispute filing, dispute supplementation, and on read
    access to shipper-owned resources."

    Design: Corner/rbac/shipper_and_operator_ownership_is_enforced_across_tenants
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    other_terminal = fx.create_terminal(code="TRM2", name="Dallas Dock")
    beta = fx.create_customer(account_code="BETA", name="Beta Foods")
    fx.create_active_rate_program(beta["id"])
    mine = fx.setup_billed_shipment(
        env=env, pro_number="PROR030", line_specs=[STANDARD_LINE]
    )
    theirs = fx.setup_billed_shipment(
        env={
            "customer_id": beta["id"],
            "terminal_id": env["terminal_id"],
            "commodity_profile_id": env["commodity_profile_id"],
        },
        pro_number="PROR031",
        line_specs=[STANDARD_LINE],
    )
    mine_headers = make_shipper_headers(env["customer_id"])

    foreign_read = api_client.get_shipment(theirs["shipment_id"], mine_headers)
    foreign_line = api_client.create_shipment_line(
        theirs["shipment_id"],
        factories.create_shipment_line_payload(
            env["commodity_profile_id"],
            line_no=2,
            declared_class_code=100,
            declared_weight_lb=300,
            pieces=1,
            declared_length_in=40.0,
            declared_width_in=40.0,
            declared_height_in=40.0,
        ),
        mine_headers,
    )
    foreign_tender = api_client.create_shipment(
        factories.create_shipment_payload(beta["id"], env["terminal_id"], "PROR032"),
        mine_headers,
    )
    foreign_capture = api_client.create_capture_event(
        factories.create_capture_event_payload(
            mine["shipment_id"], 520, fx.single_line_measurement(520)
        ),
        make_terminal_operator_headers(other_terminal["id"]),
    )

    for refused in (foreign_read, foreign_line, foreign_tender, foreign_capture):
        validate_error(
            refused, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403
        )
    rows, meta = _shipments_visible_to(mine_headers)
    assert [row["id"] for row in rows] == [mine["shipment_id"]], (
        "the scoped collection read narrows silently rather than refusing"
    )
    assert meta["total_count"] == 1
    assert fx.get_shipment(theirs["shipment_id"])["line_count"] == 1
    assert fx.get_shipment(theirs["shipment_id"])["assessed_total_cents"] == 12500
    mine_after = fx.get_shipment(mine["shipment_id"])
    assert mine_after["class_status"] == "DECLARED"
    assert mine_after["assessed_total_cents"] == 12500
    assert fx.get_terminal(other_terminal["id"])["captures_since_calibration"] == 0


# ==========================================================================
# Segregation of duties
# ==========================================================================


def test_the_inspector_who_recorded_a_finding_cannot_sign_it_off():
    """Presenting the auditor role does not launder the inspector's own identity.

    PRD: "A `ClassificationAuditor` may not accept an inspection finding whose
    `inspector_user_id` equals the auditor's own `X-User-ID`."

    Design: Corner/rbac/inspector_who_recorded_the_finding_cannot_accept_it
    """
    env = fx.setup_pricing_environment(clock=CLOCK)
    tendered = fx.setup_shipment_with_lines(
        env, "PROR040", line_specs=[STANDARD_LINE]
    )
    line_id = tendered["line_ids"][0]
    finding = fx.record_finding(
        line_id, inspector_user_id="insp-1", found_class_code=250, evidence_photo_count=3
    )

    self_acceptance = api_client.accept_inspection_finding(
        finding["id"], {}, make_classification_auditor_headers("insp-1")
    )

    validate_error(
        self_acceptance, ApiErrorId.ERR_SOD_VIOLATION.value, expected_status=403
    )
    unchanged = validate_success(
        api_client.get_inspection_finding(finding["id"], AUDITOR)
    )
    assert unchanged["status"] == "RECORDED"
    assert unchanged["accepted_by_user_id"] is None
    before = fx.get_shipment_line(line_id)
    assert before["effective_class_code"] == 70
    assert before["classification_source"] == "BOL_DECLARED"

    accepted = fx.accept_finding(finding["id"], auditor_user_id="aud-2")

    assert accepted["status"] == "ACCEPTED"
    assert accepted["accepted_by_user_id"] == "aud-2"
    assert accepted["inspector_user_id"] == "insp-1", (
        "the recording inspector is not restamped by whoever accepted the finding"
    )
    after = fx.get_shipment_line(line_id)
    assert after["effective_class_code"] == 250
    assert after["classification_source"] == "INSPECTION"
    assert fx.get_shipment(tendered["shipment_id"])["class_status"] == "RECLASS_PENDING"
