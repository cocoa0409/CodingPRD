"""Retirement's two collection guards: the looser batch test on DEACTIVATE, the strict one on ARCHIVE."""
from test_helpers import (
    api_client, validate_error, validate_paginated, ApiErrorId,
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    batch_lifecycle, create_change_request, decide_change_request, item_lifecycle,
    read_item, read_department, read_facility, set_clock,
    ANALYST,
)

MERCY = dict(
    facility_overrides={
        "name": "Mercy General", "cms_certification_number": "CCN-2193-RETIRE",
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


def _lifecycle_error(item_id, action, error_id, status):
    validate_error(api_client.charge_item_lifecycle(item_id, {"action": action}, ANALYST),
                   error_id, status)


def test_a_reconciled_batch_permits_deactivation_but_only_a_closed_one_permits_archival():
    """PRD §3.8: "Both are `RevenueIntegrityAnalyst` actions, both require the facility not to be
    `FROZEN`, and both are blocked while any `CapturedCharge` referencing the item sits in a
    `ChargeCaptureBatch` whose `status` is `INGESTED` or `RECONCILING`, which surfaces as
    `ERR_ITEM_IN_OPEN_BATCH` (409)."
    PRD §3.8: "Note this is looser than the archival rule of §3.3, which demands that *no* non-`CLOSED`
    batch reference the item: deactivation tolerates a `RECONCILED` or `DISPUTED` batch, archival does
    not."
    PRD §3.3: "No `ChangeRequest` targeting this item may sit in `SUBMITTED`, `UNDER_REVIEW`,
    `CHANGES_REQUESTED` or `APPROVED` status, otherwise `ERR_ITEM_HAS_OPEN_REQUEST` (409)."
    PRD §3.3: "And no `CapturedCharge` referencing this item may sit in a `ChargeCaptureBatch` whose
    `status` is anything other than `CLOSED`, otherwise `ERR_ITEM_IN_OPEN_BATCH` (409) — note that
    archival demands *fully settled* batches, a stricter test than the deactivation rule described in
    §3.8."
    PRD §3.5: "Withdrawal is the submitter's own escape hatch and is reachable from two states with
    identical treatment."

    Design: Corner/errors/item_retirement_rejected_while_a_batch_is_open_or_a_request_is_pending
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    department_id = base["department"]["id"]
    item_a = create_active_item(base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
                                code_type="CPT", code_value="93458", **PRICING)
    item_b = create_active_item(base, cdm_number="CDM-1002", description="CARDIAC CATH COMPLEX",
                                code_type="CPT", code_value="93460", **PRICING)
    assert item_a["gross_charge_cents"] == 240000 and item_b["gross_charge_cents"] == 240000

    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T23:59:59Z")
    line = append_line(batch["id"], "CDM-1001", base["manager_headers"], encounter_id="ENC-1",
                       payer_code="AETNA", service_datetime="2026-09-02T10:00:00Z",
                       quantity=1, posted_charge_cents=240000)
    reconciling = reconcile_batch(batch["id"])
    assert reconciling["status"] == "RECONCILING"

    _lifecycle_error(item_a["id"], "DEACTIVATE", ApiErrorId.ERR_ITEM_IN_OPEN_BATCH.value, 409)

    assert batch_lifecycle(batch["id"], "FINALIZE")["status"] == "RECONCILED"
    inactive_a = item_lifecycle(item_a["id"], "DEACTIVATE", ANALYST)
    assert inactive_a["lifecycle_status"] == "INACTIVE", (
        "the deactivation rule tolerates a RECONCILED batch"
    )

    _lifecycle_error(item_a["id"], "ARCHIVE", ApiErrorId.ERR_ITEM_IN_OPEN_BATCH.value, 409)
    assert read_item(item_a["id"])["lifecycle_status"] == "INACTIVE", "the refusal changed nothing"

    assert batch_lifecycle(batch["id"], "CLOSE")["status"] == "CLOSED"
    assert item_lifecycle(item_a["id"], "ARCHIVE", ANALYST)["lifecycle_status"] == "ARCHIVED"

    inactive_b = item_lifecycle(item_b["id"], "DEACTIVATE", ANALYST)
    assert inactive_b["lifecycle_status"] == "INACTIVE", "item B has no capture line at all"

    request = create_change_request(base, item_b["id"], "PRICE_CHANGE",
                                    justification="Retire at a lower cost basis instead",
                                    proposed_cost_basis_cents=150000)
    assert request["status"] == "SUBMITTED"

    _lifecycle_error(item_b["id"], "ARCHIVE", ApiErrorId.ERR_ITEM_HAS_OPEN_REQUEST.value, 409)

    withdrawn = decide_change_request(request["id"], "WITHDRAW", base["manager_headers"],
                                      decision_note="Archiving instead")
    assert withdrawn["status"] == "WITHDRAWN"
    assert item_lifecycle(item_b["id"], "ARCHIVE", ANALYST)["lifecycle_status"] == "ARCHIVED"

    assert read_item(item_a["id"])["lifecycle_status"] == "ARCHIVED"
    assert read_item(item_b["id"])["lifecycle_status"] == "ARCHIVED"
    assert read_department(department_id)["open_request_count"] == 0, (
        "WITHDRAWN is not one of the four open statuses"
    )
    facility = read_facility(base["facility"]["id"])
    assert facility["active_item_count"] == 0
    assert facility["aggregate_gross_charge_cents"] == 0
    assert facility["aggregate_cost_basis_cents"] == 0
    assert facility["stale_price_item_count"] == 0
    assert facility["chargemaster_posture"] == "OPEN"

    rows, meta = validate_paginated(api_client.list_captured_charges(
        ANALYST, {"batch_id": batch["id"]}))
    assert meta["total_count"] == 1
    assert rows[0]["id"] == line["id"]
    assert rows[0]["match_status"] == "MATCHED", (
        "archiving the item afterwards does not rewrite a closed batch"
    )
