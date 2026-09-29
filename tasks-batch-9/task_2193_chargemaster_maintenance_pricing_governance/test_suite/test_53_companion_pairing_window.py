"""Companion pairing: inclusive at the far edge, blind backwards, and gated on quantity."""
from test_helpers import (
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    list_findings, read_batch, read_department, read_item, set_clock,
)

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


def test_only_a_forward_in_window_companion_of_sufficient_quantity_counts():
    """PRD §3.9: "Otherwise the pass looks for a companion line in the same batch satisfying **all**
    of four conditions: its `charge_item_id` equals the companion item's identifier; its
    `encounter_id` equals the trigger's `encounter_id`; its `match_status` is not `DUPLICATE_LINE`;
    its `quantity` is at least the trigger's `quantity`; and its `service_datetime` falls between the
    trigger's `service_datetime` and the trigger's `service_datetime` plus the triggering item's
    `companion_window_hours`, with **both** bounds inclusive. A companion posted exactly
    `companion_window_hours` after the trigger counts as present; a companion posted *before* the
    trigger does not count at all. Lines from other batches and other encounters never satisfy the
    pairing."
    PRD §3.9: "a new `MissingChargeFinding` is created in `OPEN` with `batch_id` and `department_id`
    copied from the batch, `trigger_captured_charge_id` naming the unpaired line,
    `expected_charge_item_id` naming the companion item that should have been captured, and
    `estimated_lost_charge_cents` computed as the companion item's `gross_charge_cents` multiplied by
    the trigger line's `quantity`."
    PRD §3.3: "`companion_window_hours` defaults to 24 when omitted, and `companion_required_item_id`
    is null when no pairing applies."

    Design: Corner/calculations/companion_window_is_inclusive_forward_only_and_quantity_gated
    """
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    companion_item = create_active_item(
        base, cdm_number="CDM-2002", description="RECOVERY SUITE HOUR",
        code_type="CPT", code_value="99213", cost_basis_cents=50000,
        medicare_rate_cents=10000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert companion_item["gross_charge_cents"] == 120000
    trigger_item = create_active_item(
        base, cdm_number="CDM-1001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
        companion_required_item_id=companion_item["id"],
    )
    assert trigger_item["gross_charge_cents"] == 240000
    assert read_item(trigger_item["id"])["companion_window_hours"] == 24, (
        "the omitted window defaults to 24 hours"
    )

    set_clock("2026-09-10T00:00:00Z")
    batch = create_batch(base, window_start_date="2026-09-01T00:00:00Z",
                         window_end_date="2026-09-07T00:00:00Z")

    def trigger(encounter, when, quantity):
        return append_line(
            batch["id"], "CDM-1001", base["manager_headers"], encounter_id=encounter,
            payer_code="BCBS", service_datetime=when, quantity=quantity,
            posted_charge_cents=240000 * quantity,
        )

    def companion(encounter, when, quantity):
        return append_line(
            batch["id"], "CDM-2002", base["manager_headers"], encounter_id=encounter,
            payer_code="BCBS", service_datetime=when, quantity=quantity,
            posted_charge_cents=120000 * quantity,
        )

    t_ok = trigger("ENC-1", "2026-09-02T08:00:00Z", 1)
    companion("ENC-1", "2026-09-03T08:00:00Z", 1)

    t_late = trigger("ENC-2", "2026-09-02T08:00:00Z", 1)
    companion("ENC-2", "2026-09-03T09:00:00Z", 1)

    t_early = trigger("ENC-3", "2026-09-03T08:00:00Z", 2)
    companion("ENC-3", "2026-09-03T07:00:00Z", 2)

    t_qty = trigger("ENC-4", "2026-09-04T08:00:00Z", 3)
    companion("ENC-4", "2026-09-04T09:00:00Z", 1)

    t_enc = trigger("ENC-5", "2026-09-05T08:00:00Z", 1)
    companion("ENC-6", "2026-09-05T09:00:00Z", 1)

    reconciled = reconcile_batch(batch["id"])
    assert reconciled["matched_line_count"] == 10, "every line was posted at expectation"
    assert reconciled["mean_line_variance_bp"] == 0
    assert reconciled["open_finding_count"] == 4, (
        "only the exactly-24-hour pairing counts as present"
    )

    def finding_for(line):
        return list_findings(trigger_captured_charge_id=line["id"])

    assert finding_for(t_ok) == [], "a companion exactly at the window edge is present"

    qty_findings = finding_for(t_qty)
    assert len(qty_findings) == 1
    assert qty_findings[0]["estimated_lost_charge_cents"] == 360000, (
        "the companion gross of 120000 times the trigger quantity of 3"
    )
    assert qty_findings[0]["status"] == "OPEN"
    assert qty_findings[0]["expected_charge_item_id"] == companion_item["id"]
    assert qty_findings[0]["department_id"] == base["department"]["id"]

    early_findings = finding_for(t_early)
    assert len(early_findings) == 1
    assert early_findings[0]["estimated_lost_charge_cents"] == 240000, (
        "a companion one hour before the trigger does not count at all"
    )
    assert early_findings[0]["status"] == "OPEN"

    late_findings = finding_for(t_late)
    assert len(late_findings) == 1
    assert late_findings[0]["estimated_lost_charge_cents"] == 120000, "25 hours is outside"

    enc_findings = finding_for(t_enc)
    assert len(enc_findings) == 1
    assert enc_findings[0]["estimated_lost_charge_cents"] == 120000, (
        "another encounter never satisfies the pairing"
    )

    open_in_batch = list_findings(batch_id=batch["id"], status="OPEN")
    assert len(open_in_batch) == 4
    assert {row["batch_id"] for row in open_in_batch} == {batch["id"]}

    stored = read_batch(batch["id"])
    assert stored["line_count"] == 10
    assert stored["exception_line_count"] == 0
    assert stored["total_expected_charge_cents"] == 2640000

    assert read_department(base["department"]["id"])["capture_hold"] is False, (
        "an OPEN finding books nothing until it is confirmed"
    )
