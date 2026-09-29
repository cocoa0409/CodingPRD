"""Batch ingestion capacity, the inclusive service-date window, and the close-path ladder."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_active_item, create_batch, append_line, reconcile_batch, batch_lifecycle,
    read_batch, read_department, list_findings, disposition_finding, get_success_data,
    set_clock, ANALYST, NON_EXISTENT_UUID,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-CAPTURE",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
        "allowed_revenue_code_values": [],
    },
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_day_capacity_and_the_window_bound_sit_below_existence_and_batch_state():
    """PRD §3.9: "And capacity is bounded per calendar day: no single day inside the new closed window
    may end up covered by more than two `ChargeCaptureBatch` rows of the same department whose `status`
    is anything other than `CLOSED`. A third overlapping batch on any one day is rejected with
    `ERR_BATCH_WINDOW_CAPACITY_EXCEEDED` (409)."
    PRD §3.9: "Lines are appended by the same manager while the batch's `status` is `INGESTED`;
    appending to a batch in any other status is `ERR_INVALID_BATCH_STATE` (409)."
    PRD §3.9: "The `service_datetime` must fall inside the batch's closed window — at or after
    `window_start_date` and at or before `window_end_date` — otherwise
    `ERR_SERVICE_DATE_OUTSIDE_WINDOW` (422)."
    PRD §2.9: "8. `batch_id` resolves to a `ChargeCaptureBatch`, `captured_charge_id` to a
    `CapturedCharge` and `finding_id` to a `MissingChargeFinding` — `ERR_CAPTURE_RESOURCE_NOT_FOUND`
    (404)."

    Design: Corner/validations/batch_capacity_and_service_date_window_sit_below_existence_and_batch_state_checks
    """
    set_clock("2026-09-15T00:00:00Z")
    base = setup_base(**MERCY)
    manager = base["manager_headers"]
    department_id = base["department"]["id"]

    first = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T23:59:59Z")
    assert first["status"] == "INGESTED"
    assert first["reconcile_pass_count"] == 0
    assert first["mean_line_variance_bp"] is None

    second = create_batch(base, window_start_date="2026-09-05T00:00:00Z",
                          window_end_date="2026-09-10T23:59:59Z")

    def batch_body(start, end):
        return factories.create_charge_capture_batch_payload(
            base["facility"]["id"], department_id,
            window_start_date=start, window_end_date=end,
        )

    validate_error(
        api_client.create_charge_capture_batch(
            batch_body("2026-09-07T00:00:00Z", "2026-09-12T23:59:59Z"), manager),
        ApiErrorId.ERR_BATCH_WINDOW_CAPACITY_EXCEEDED.value, 409,
    )
    third = validate_success(api_client.create_charge_capture_batch(
        batch_body("2026-09-08T00:00:00Z", "2026-09-12T23:59:59Z"), manager), 201)
    assert third["status"] == "INGESTED", "no day from 09-08 to 09-12 is covered twice yet"

    line_body = factories.create_captured_charge_payload(
        "CDM-1001", encounter_id="E1", payer_code="AETNA",
        service_datetime="2026-09-20T10:00:00Z", quantity=1, posted_charge_cents=240000,
    )
    validate_error(
        api_client.create_captured_charge(NON_EXISTENT_UUID, line_body, manager),
        ApiErrorId.ERR_CAPTURE_RESOURCE_NOT_FOUND.value, 404,
    )
    validate_error(
        api_client.create_captured_charge(
            first["id"],
            factories.create_captured_charge_payload(
                "CDM-1001", encounter_id="E1", payer_code="AETNA",
                service_datetime="2026-09-08T10:00:00Z", quantity=1,
                posted_charge_cents=240000),
            manager),
        ApiErrorId.ERR_SERVICE_DATE_OUTSIDE_WINDOW.value, 422,
    )

    edge = append_line(first["id"], "CDM-1001", manager, encounter_id="E1", payer_code="AETNA",
                       service_datetime="2026-09-07T23:59:59Z", quantity=1,
                       posted_charge_cents=240000)
    assert edge["match_status"] == "UNRECONCILED", "the inclusive window end is inside"

    reconciled = reconcile_batch(first["id"])
    assert reconciled["status"] == "RECONCILING"
    assert reconciled["exception_line_count"] == 1

    validate_error(
        api_client.create_captured_charge(first["id"], line_body, manager),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409,
    )

    stored_line = get_success_data(api_client.get_captured_charge(edge["id"], ANALYST))
    assert stored_line["match_status"] == "UNKNOWN_CODE", "no charge item carries that CDM number"
    assert stored_line["charge_item_id"] is None

    stored = read_batch(first["id"])
    assert stored["line_count"] == 1
    assert stored["total_posted_charge_cents"] == 240000
    assert stored["total_expected_charge_cents"] == 0
    assert stored["reconcile_pass_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_charge_capture_batches(ANALYST, {"department_id": department_id})
    )
    assert meta["total_count"] == 3, "the rejected window stored nothing"
    assert {row["id"] for row in rows} == {first["id"], second["id"], third["id"]}


def test_open_findings_outrank_the_hold_and_only_a_resolution_releases_it():
    """PRD §3.9: "Also from `RECONCILED`, the analyst may close — `RECONCILED → CLOSED` — which
    requires that `open_finding_count` be 0, meaning every finding of the batch is `CONFIRMED`,
    `DISMISSED` or `RESOLVED` (otherwise `ERR_FINDINGS_OPEN`, 409), and that the department's
    `capture_hold` be false (otherwise `ERR_DEPARTMENT_CAPTURE_HOLD`, 409)."
    PRD §3.9: "sets the department's `capture_hold` to true once `unresolved_finding_amount_cents`
    reaches 500000 cents or more, which blocks that department from ingesting any further capture
    batch."
    PRD §3.9: "It requires that the supplied `recovery_captured_charge_id` resolve to a
    `CapturedCharge` in the **same** batch whose `charge_item_id` equals the finding's
    `expected_charge_item_id`, otherwise `ERR_RECOVERY_LINE_INVALID` (422), and that the batch's
    `status` not be `CLOSED`, otherwise `ERR_INVALID_BATCH_STATE`. On success
    `recovery_captured_charge_id` is stored, and the *same literal amount* — the finding's frozen
    `estimated_lost_charge_cents` — is subtracted from the department's
    `unresolved_finding_amount_cents` and added to its `recovered_charge_cents`"

    Design: Corner/validations/close_checks_open_findings_before_capture_hold_and_resolution_reopens_the_close_path
    """
    set_clock("2026-09-15T00:00:00Z")
    base = setup_base(**MERCY)
    manager = base["manager_headers"]
    department_id = base["department"]["id"]

    companion_item = create_active_item(
        base, cdm_number="CDM-2001", description="CATH LAB SUPPLY TRAY",
        code_type="CPT", code_value="99070", cost_basis_cents=250000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-15T00:00:00Z",
    )
    assert companion_item["gross_charge_cents"] == 450000
    trigger_item = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-15T00:00:00Z",
        companion_required_item_id=companion_item["id"],
    )
    assert trigger_item["gross_charge_cents"] == 240000

    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T23:59:59Z")
    line_one = append_line(batch["id"], "CDM-1001", manager, encounter_id="ENC-1",
                           payer_code="AETNA", service_datetime="2026-09-02T08:00:00Z",
                           quantity=2, posted_charge_cents=480000)
    line_two = append_line(batch["id"], "CDM-1001", manager, encounter_id="ENC-2",
                           payer_code="AETNA", service_datetime="2026-09-03T08:00:00Z",
                           quantity=1, posted_charge_cents=240000)
    line_three = append_line(batch["id"], "CDM-2001", manager, encounter_id="ENC-1",
                             payer_code="AETNA", service_datetime="2026-09-04T08:00:00Z",
                             quantity=1, posted_charge_cents=450000)

    reconciled = reconcile_batch(batch["id"])
    assert reconciled["open_finding_count"] == 2
    assert reconciled["matched_line_count"] == 3
    assert reconciled["mean_line_variance_bp"] == 0

    finding_one = list_findings(trigger_captured_charge_id=line_one["id"])[0]
    finding_two = list_findings(trigger_captured_charge_id=line_two["id"])[0]
    assert finding_one["estimated_lost_charge_cents"] == 900000, (
        "the companion gross of 450000 times the trigger quantity of 2"
    )
    assert finding_two["estimated_lost_charge_cents"] == 450000
    assert finding_one["expected_charge_item_id"] == companion_item["id"]

    confirmed = disposition_finding(finding_one["id"], "CONFIRM",
                                    disposition_note="Tray was used but never posted")
    assert confirmed["status"] == "CONFIRMED"
    held = read_department(department_id)
    assert held["unresolved_finding_amount_cents"] == 900000
    assert held["capture_hold"] is True, "900000 cents is past the 500000 threshold"

    finalized = batch_lifecycle(batch["id"], "FINALIZE")
    assert finalized["status"] == "RECONCILED"

    validate_error(
        api_client.batch_lifecycle(batch["id"], {"action": "CLOSE"}, ANALYST),
        ApiErrorId.ERR_FINDINGS_OPEN.value, 409,
    )

    dismissed = disposition_finding(
        finding_two["id"], "DISMISS",
        disposition_note="Single-stage procedure, no tray required")
    assert dismissed["status"] == "DISMISSED"

    validate_error(
        api_client.batch_lifecycle(batch["id"], {"action": "CLOSE"}, ANALYST),
        ApiErrorId.ERR_DEPARTMENT_CAPTURE_HOLD.value, 409,
    )
    validate_error(
        api_client.create_charge_capture_batch(
            factories.create_charge_capture_batch_payload(
                base["facility"]["id"], department_id,
                window_start_date="2026-09-08T00:00:00Z",
                window_end_date="2026-09-09T23:59:59Z"),
            manager),
        ApiErrorId.ERR_DEPARTMENT_CAPTURE_HOLD.value, 409,
    )

    validate_error(
        api_client.disposition_finding(
            finding_one["id"],
            {"action": "RESOLVE", "recovery_captured_charge_id": line_two["id"]}, ANALYST),
        ApiErrorId.ERR_RECOVERY_LINE_INVALID.value, 422,
    )

    resolved = disposition_finding(finding_one["id"], "RESOLVE",
                                   recovery_captured_charge_id=line_three["id"])
    assert resolved["status"] == "RESOLVED"
    assert resolved["recovery_captured_charge_id"] == line_three["id"]

    released = read_department(department_id)
    assert released["unresolved_finding_amount_cents"] == 0
    assert released["recovered_charge_cents"] == 900000, "the frozen amount moves across intact"
    assert released["capture_hold"] is False

    closed = batch_lifecycle(batch["id"], "CLOSE")
    assert closed["status"] == "CLOSED"

    stored = read_batch(batch["id"])
    assert stored["open_finding_count"] == 0
    assert stored["total_expected_charge_cents"] == 1170000
    assert stored["total_posted_charge_cents"] == 1170000
