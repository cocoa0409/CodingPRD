"""The finding's two terminals, the RESOLVE-only-from-CONFIRMED gate, and the closed-batch guard."""
from test_helpers import (
    api_client, validate_error, ApiErrorId,
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    batch_lifecycle, read_batch, read_department, list_findings, disposition_finding,
    set_clock, ANALYST, COMPLIANCE,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-FINDERR",
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
PRICING = dict(cost_basis_cents=100000, medicare_rate_cents=50000,
               market_p75_cents=900000, effective_from="2026-09-01T00:00:00Z")


def _disposition_error(finding_id, payload, error_id, status):
    validate_error(api_client.disposition_finding(finding_id, payload, ANALYST),
                   error_id, status)


def test_a_finding_resolves_only_from_confirmed_and_both_terminals_refuse_everything_after():
    """PRD §3.9: "Confirming, `OPEN → CONFIRMED`, requires the owning batch's `status` to be
    `RECONCILING`, `RECONCILED` or `DISPUTED` (otherwise `ERR_INVALID_BATCH_STATE`, 409); it records the
    payload's `disposition_note`, then adds the finding's `estimated_lost_charge_cents` to the
    department's `unresolved_finding_amount_cents` with `Department.version` advancing by 1, and — the
    second cascade link — sets the department's `capture_hold` to true once
    `unresolved_finding_amount_cents` reaches 500000 cents or more, which blocks that department from
    ingesting any further capture batch."
    PRD §3.9: "Dismissing, `OPEN → DISMISSED`, requires the same three batch statuses
    (`ERR_INVALID_BATCH_STATE`) and additionally a non-empty `disposition_note` (`ERR_VALIDATION`); it
    sets `status` to `DISMISSED` and prompts a recomputation of the batch's `open_finding_count`."
    PRD §3.9: "It requires that the supplied `recovery_captured_charge_id` resolve to a `CapturedCharge`
    in the **same** batch whose `charge_item_id` equals the finding's `expected_charge_item_id`, otherwise
    `ERR_RECOVERY_LINE_INVALID` (422), and that the batch's `status` not be `CLOSED`, otherwise
    `ERR_INVALID_BATCH_STATE`."
    PRD §3.9: "`DISMISSED` and `RESOLVED` are the finding's terminal states, and a disposition not
    declared from the finding's current status (resolving an `OPEN` finding, confirming a `DISMISSED` one)
    is `ERR_INVALID_FINDING_STATE` (409)."
    PRD §3.9: "That amount is **frozen at creation** and is never recomputed, even if the companion item
    is later repriced."

    Design: Corner/errors/finding_disposition_rejects_resolve_before_confirm_and_any_second_disposition
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    department_id = base["department"]["id"]
    companion = create_active_item(base, cdm_number="CDM-2001",
                                   description="CARDIAC CATH SUPPLY TRAY",
                                   code_type="CPT", code_value="93461", **PRICING)
    assert companion["gross_charge_cents"] == 240000
    trigger = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                                 code_type="CPT", code_value="93458",
                                 companion_required_item_id=companion["id"], **PRICING)
    assert trigger["companion_required_item_id"] == companion["id"]
    assert trigger["companion_window_hours"] == 24

    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T23:59:59Z")
    first_trigger = append_line(batch["id"], "CDM-1001", base["manager_headers"],
                                encounter_id="ENC-1", payer_code="AETNA",
                                service_datetime="2026-09-02T10:00:00Z", quantity=1,
                                posted_charge_cents=240000)
    second_trigger = append_line(batch["id"], "CDM-1001", base["manager_headers"],
                                 encounter_id="ENC-2", payer_code="AETNA",
                                 service_datetime="2026-09-03T10:00:00Z", quantity=1,
                                 posted_charge_cents=240000)
    # A tray line on a third encounter can never pair with either trigger (the encounter ids
    # differ), yet it is a line of the same batch whose item is the expected companion — which
    # is exactly what the recovery-line rule demands.
    recovery = append_line(batch["id"], "CDM-2001", base["manager_headers"],
                           encounter_id="ENC-3", payer_code="AETNA",
                           service_datetime="2026-09-04T10:00:00Z", quantity=1,
                           posted_charge_cents=240000)

    reconciling = reconcile_batch(batch["id"])
    assert reconciling["status"] == "RECONCILING"
    assert reconciling["open_finding_count"] == 2, "one unpaired trigger line per encounter"

    def finding_for(line_id):
        rows = list_findings(batch_id=batch["id"], trigger_captured_charge_id=line_id)
        assert len(rows) == 1
        return rows[0]

    f1 = finding_for(first_trigger["id"])
    f2 = finding_for(second_trigger["id"])
    for finding in (f1, f2):
        assert finding["status"] == "OPEN"
        assert finding["estimated_lost_charge_cents"] == 240000, (
            "the companion's gross 240000 times the trigger quantity 1, frozen at creation"
        )
        assert finding["expected_charge_item_id"] == companion["id"]
        assert finding["recovery_captured_charge_id"] is None

    _disposition_error(f1["id"],
                       {"action": "RESOLVE", "recovery_captured_charge_id": recovery["id"]},
                       ApiErrorId.ERR_INVALID_FINDING_STATE.value, 409)

    dismissed = disposition_finding(f1["id"], "DISMISS",
                                    disposition_note="Tray issued from floor stock")
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["disposition_note"] == "Tray issued from floor stock"
    _disposition_error(f1["id"], {"action": "CONFIRM", "disposition_note": "Reopening"},
                       ApiErrorId.ERR_INVALID_FINDING_STATE.value, 409)

    confirmed = disposition_finding(f2["id"], "CONFIRM", disposition_note="Genuine leakage")
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["estimated_lost_charge_cents"] == 240000
    _disposition_error(f2["id"], {"action": "CONFIRM", "disposition_note": "Again"},
                       ApiErrorId.ERR_INVALID_FINDING_STATE.value, 409)
    _disposition_error(f2["id"], {"action": "DISMISS", "disposition_note": "Changed my mind"},
                       ApiErrorId.ERR_INVALID_FINDING_STATE.value, 409)

    department = read_department(department_id)
    assert department["unresolved_finding_amount_cents"] == 240000, (
        "only the CONFIRMED finding moves money; the DISMISSED one contributes nothing"
    )
    assert department["capture_hold"] is False, "240000 has not reached the 500000 boundary"
    assert department["recovered_charge_cents"] == 0

    assert batch_lifecycle(batch["id"], "FINALIZE")["status"] == "RECONCILED"
    closed = batch_lifecycle(batch["id"], "CLOSE")
    assert closed["status"] == "CLOSED", "open_finding_count is 0 once both findings left OPEN"

    _disposition_error(f2["id"],
                       {"action": "RESOLVE", "recovery_captured_charge_id": recovery["id"]},
                       ApiErrorId.ERR_INVALID_BATCH_STATE.value, 409)

    assert read_department(department_id)["unresolved_finding_amount_cents"] == 240000, (
        "the rejected RESOLVE neither moved nor lost the identified leakage"
    )
    final_f2 = list_findings(batch_id=batch["id"],
                             trigger_captured_charge_id=second_trigger["id"])[0]
    assert final_f2["status"] == "CONFIRMED"
    assert final_f2["recovery_captured_charge_id"] is None
    assert read_batch(batch["id"])["open_finding_count"] == 0
    assert len(list_findings(batch_id=batch["id"], status="OPEN")) == 0
    assert api_client.get_missing_charge_finding(f1["id"], COMPLIANCE).status_code == 200
