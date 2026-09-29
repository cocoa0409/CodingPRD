"""The dispute loop is re-traversable; CLOSED refuses every further batch operation."""
from test_helpers import (
    api_client, validate_error, ApiErrorId, factories,
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    batch_lifecycle, read_batch, set_clock,
    get_success_data,
    ANALYST,
)


def _read_line(line_id: str) -> dict:
    return get_success_data(api_client.get_captured_charge(line_id, ANALYST))


MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-MERCY",
        "rounding_mode": "NEAREST_CENT", "aggregate_markup_limit_bp": 40000,
    },
    revenue_code_overrides={
        "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
        "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
        "pricing_class": "PROCEDURE", "status": "ACTIVE",
    },
    department_overrides={
        "name": "Cardiac Cath Lab", "cost_center_code": "CC-4100",
        "allowed_revenue_code_values": [],
    },
    price_rule_overrides={"effective_from": "2026-01-01T00:00:00Z"},
)

ITEM = dict(
    cdm_number="CDM-2001", description="CARDIAC CATH BASIC",
    code_type="CPT", code_value="93458", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=900000,
    effective_from="2026-09-01T00:00:00Z",
)


def _setup():
    """An ACTIVE item at gross 240000 and an INGESTED batch over a closed past window."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    item = create_active_item(base, **ITEM)
    assert item["gross_charge_cents"] == 240000
    set_clock("2026-09-10T00:00:00Z")
    base["item"] = item
    base["batch"] = create_batch(
        base,
        window_start_date="2026-09-01T00:00:00Z",
        window_end_date="2026-09-07T00:00:00Z",
    )
    return base


def test_the_dispute_loop_runs_a_second_reconciliation_pass():
    """PRD §3.9: "Reconciliation is the analyst's pass over the batch, and it is reachable from two
    states with identical effect: `INGESTED → RECONCILING` and `DISPUTED → RECONCILING`. Both
    require `line_count` to be at least 1, since an empty batch cannot be reconciled, and both
    report `ERR_BATCH_HAS_NO_LINES` (422) when it is 0. Both set `status` to `RECONCILING`, increase
    `reconcile_pass_count` by 1, advance the batch's `version` by 1, and re-execute the complete set
    of line-level and finding-level side effects described below. The dispute cycle
    `RECONCILED → DISPUTED → RECONCILING → RECONCILED` may therefore be walked repeatedly."
    PRD §3.9: "From `RECONCILED` the department manager may dispute — `RECONCILED → DISPUTED` —
    which requires that `X-User-ID` equal the department's `manager_user_id`
    (`ERR_DEPARTMENT_SCOPE_VIOLATION`) and that `exception_line_count` be at least 1, since there
    must be something to argue about; a clean batch yields `ERR_NOTHING_TO_DISPUTE` (422)."
    PRD §3.9: "If the absolute value of `line_variance_bp` is greater than 100 basis points — that
    is, more than one percent away from expected — `match_status` becomes `PRICE_VARIANCE`."

    Design: Corner/state_machines/batch_dispute_cycle_returns_to_reconciling_and_increments_pass_count
    """
    base = _setup()
    line1 = append_line(
        base["batch"]["id"], "CDM-2001", base["manager_headers"], encounter_id="ENC-1",
        payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=1,
        posted_charge_cents=240000,
    )
    line2 = append_line(
        base["batch"]["id"], "CDM-2001", base["manager_headers"], encounter_id="ENC-2",
        payer_code="BCBS", service_datetime="2026-09-04T08:00:00Z", quantity=1,
        posted_charge_cents=250000,
    )
    first_pass = reconcile_batch(base["batch"]["id"])
    assert first_pass["reconcile_pass_count"] == 1
    assert first_pass["mean_line_variance_bp"] == 209, (
        "the mean of the rounded per-line values 0 and 417 is 208.5, which rounds half up to 209"
    )
    batch_lifecycle(base["batch"]["id"], "FINALIZE")

    disputed = batch_lifecycle(base["batch"]["id"], "DISPUTE", base["manager_headers"],
                               note="Department challenges the variance line")
    assert disputed["status"] == "DISPUTED"

    second_pass = reconcile_batch(base["batch"]["id"])
    assert second_pass["status"] == "RECONCILING"
    assert second_pass["reconcile_pass_count"] == 2
    assert second_pass["mean_line_variance_bp"] == 209, (
        "the re-executed pass reaches the same verdict on the same lines"
    )

    finalized = batch_lifecycle(base["batch"]["id"], "FINALIZE")
    assert finalized["status"] == "RECONCILED"
    assert finalized["reconcile_pass_count"] == 2
    assert finalized["matched_line_count"] == 1
    assert finalized["exception_line_count"] == 1

    l1 = _read_line(line1["id"])
    assert l1["match_status"] == "MATCHED"
    assert l1["line_variance_bp"] == 0
    l2 = _read_line(line2["id"])
    assert l2["match_status"] == "PRICE_VARIANCE"
    assert l2["line_variance_bp"] == 417, "(250000 - 240000) * 10000 / 240000 rounded half up"


def test_a_closed_batch_refuses_reconciliation_dispute_and_new_lines():
    """PRD §3.9: "Also from `RECONCILED`, the analyst may close — `RECONCILED → CLOSED` — which
    requires that `open_finding_count` be 0, meaning every finding of the batch is `CONFIRMED`,
    `DISMISSED` or `RESOLVED` (otherwise `ERR_FINDINGS_OPEN`, 409), and that the department's
    `capture_hold` be false (otherwise `ERR_DEPARTMENT_CAPTURE_HOLD`, 409)."
    PRD §3.9: "`CLOSED` is the batch's terminal state, and the three lifecycle actions are named
    `FINALIZE`, `DISPUTE` and `CLOSE`, each accepting an optional `note`."
    PRD §3.9: "Lines are appended by the same manager while the batch's `status` is `INGESTED`;
    appending to a batch in any other status is `ERR_INVALID_BATCH_STATE` (409)."

    Design: Corner/state_machines/closed_batch_terminal_state_rejects_reconcile_dispute_and_new_lines
    """
    base = _setup()
    line = append_line(
        base["batch"]["id"], "CDM-2001", base["manager_headers"], encounter_id="ENC-1",
        payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=1,
        posted_charge_cents=240000,
    )
    reconcile_batch(base["batch"]["id"])
    batch_lifecycle(base["batch"]["id"], "FINALIZE")
    closed = batch_lifecycle(base["batch"]["id"], "CLOSE", note="Settled")
    assert closed["status"] == "CLOSED"
    assert closed["open_finding_count"] == 0
    frozen_version = closed["version"]

    validate_error(
        api_client.reconcile_batch(base["batch"]["id"], ANALYST),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409,
    )
    validate_error(
        api_client.batch_lifecycle(
            base["batch"]["id"], {"action": "DISPUTE", "note": "Too late"},
            base["manager_headers"],
        ),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409,
    )
    validate_error(
        api_client.create_captured_charge(
            base["batch"]["id"],
            factories.create_captured_charge_payload(
                "CDM-2001", encounter_id="ENC-9", payer_code="BCBS",
                service_datetime="2026-09-04T08:00:00Z", quantity=1,
                posted_charge_cents=240000,
            ),
            base["manager_headers"],
        ),
        ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409,
    )

    after = read_batch(base["batch"]["id"])
    assert after["status"] == "CLOSED", "the terminal state has no exit"
    assert after["reconcile_pass_count"] == 1
    assert after["line_count"] == 1
    assert after["version"] == frozen_version, "three refusals moved no counter"
    assert _read_line(line["id"])["match_status"] == "MATCHED"
