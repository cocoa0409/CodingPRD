"""Every rejection edge of the batch machine on one clean batch, plus the unreachable residual guard."""
from test_helpers import (
    api_client, validate_error, validate_paginated, ApiErrorId, factories,
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    batch_lifecycle, read_batch, read_department, set_clock,
    ANALYST, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-BATCHERR",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-100",
                         "allowed_revenue_code_values": []},
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)


def test_the_batch_rejects_an_empty_reconcile_a_late_line_a_clean_dispute_and_a_closed_replay():
    """PRD §3.9: "Both require `line_count` to be at least 1, since an empty batch cannot be reconciled,
    and both report `ERR_BATCH_HAS_NO_LINES` (422) when it is 0."
    PRD §3.9: "Lines are appended by the same manager while the batch's `status` is `INGESTED`; appending
    to a batch in any other status is `ERR_INVALID_BATCH_STATE` (409)."
    PRD §3.9: "Once the pass is done the analyst finalizes the batch, `RECONCILING → RECONCILED`, on the
    single precondition that no line still carries `match_status` of `UNRECONCILED`; a residual
    unreconciled line is `ERR_BATCH_LINES_UNRECONCILED` (409)."
    PRD §3.9: "From `RECONCILED` the department manager may dispute — `RECONCILED → DISPUTED` — which
    requires that `X-User-ID` equal the department's `manager_user_id`
    (`ERR_DEPARTMENT_SCOPE_VIOLATION`) and that `exception_line_count` be at least 1, since there must be
    something to argue about; a clean batch yields `ERR_NOTHING_TO_DISPUTE` (422)."
    PRD §3.9: "`CLOSED` is the batch's terminal state, and the three lifecycle actions are named
    `FINALIZE`, `DISPUTE` and `CLOSE`, each accepting an optional `note`."

    Design: Corner/errors/batch_lifecycle_rejects_empty_reconcile_late_lines_and_dispute_without_exceptions
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    department_id = base["department"]["id"]
    item = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                             code_type="CPT", code_value="93458", cost_basis_cents=100000,
                             medicare_rate_cents=50000, market_p75_cents=900000,
                             effective_from="2026-09-01T00:00:00Z")
    assert item["gross_charge_cents"] == 240000

    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T23:59:59Z")
    assert batch["status"] == "INGESTED"
    assert batch["line_count"] == 0
    assert batch["reconcile_pass_count"] == 0

    validate_error(api_client.reconcile_batch(batch["id"], ANALYST),
                   ApiErrorId.ERR_BATCH_HAS_NO_LINES.value, 422)

    line = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-1",
                       payer_code="AETNA", service_datetime="2026-09-02T10:00:00Z",
                       quantity=1, posted_charge_cents=240000)
    assert line["match_status"] == "UNRECONCILED"

    reconciled = reconcile_batch(batch["id"])
    assert reconciled["status"] == "RECONCILING"
    assert reconciled["matched_line_count"] == 1
    assert reconciled["exception_line_count"] == 0
    assert reconciled["mean_line_variance_bp"] == 0
    assert reconciled["reconcile_pass_count"] == 1

    validate_error(
        api_client.create_captured_charge(
            batch["id"],
            factories.create_captured_charge_payload(
                "CDM-1001", encounter_id="ENC-2", payer_code="AETNA",
                service_datetime="2026-09-03T10:00:00Z", quantity=1,
                posted_charge_cents=240000),
            base["manager_headers"]),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409,
    )

    finalized = batch_lifecycle(batch["id"], "FINALIZE")
    assert finalized["status"] == "RECONCILED", (
        "the pass left no UNRECONCILED line, which is why the residual guard cannot fire"
    )

    validate_error(
        api_client.batch_lifecycle(
            batch["id"], {"action": "DISPUTE"}, base["manager_headers"]),
        ApiErrorId.ERR_NOTHING_TO_DISPUTE.value, 422,
    )
    validate_error(
        api_client.batch_lifecycle(batch["id"], {"action": "FINALIZE"}, ANALYST),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409,
    )

    closed = batch_lifecycle(batch["id"], "CLOSE")
    assert closed["status"] == "CLOSED"

    validate_error(api_client.reconcile_batch(batch["id"], ANALYST),
                   ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409)

    final = read_batch(batch["id"])
    assert final["total_expected_charge_cents"] == 240000
    assert final["total_posted_charge_cents"] == 240000
    assert final["open_finding_count"] == 0
    assert final["reconcile_pass_count"] == 1, "no rejected call incremented the pass counter"

    rows, meta = validate_paginated(api_client.list_captured_charges(
        ANALYST, {"batch_id": batch["id"], "match_status": "MATCHED"}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == line["id"]
    assert rows[0]["expected_charge_cents"] == 240000
    assert rows[0]["line_variance_bp"] == 0

    department = read_department(department_id)
    assert department["capture_hold"] is False
    assert department["unresolved_finding_amount_cents"] == 0
    assert validate_paginated(api_client.list_missing_charge_findings(
        COMPLIANCE, {"batch_id": batch["id"]}))[1]["total_count"] == 0
