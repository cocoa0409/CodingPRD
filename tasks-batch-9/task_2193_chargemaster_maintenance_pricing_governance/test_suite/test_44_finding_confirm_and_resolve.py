"""Confirming a finding raises the department's capture hold; resolving it conserves the leakage."""
from test_helpers import (
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    list_findings, disposition_finding, read_batch, read_department, set_clock,
    assert_missing_charge_finding, assert_department_leakage_conserved,
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


def _setup():
    """A reconciled batch holding one unpaired trigger line and one OPEN finding of 900000."""
    set_clock("2026-09-01T00:00:00Z")
    base = setup_base(**MERCY)
    companion = create_active_item(
        base, cdm_number="CDM-2002", description="RECOVERY SUITE HOUR",
        code_type="CPT", code_value="99213", cost_basis_cents=250000,
        medicare_rate_cents=100000, market_p75_cents=2000000,
        effective_from="2026-09-01T00:00:00Z",
    )
    assert companion["gross_charge_cents"] == 450000, "250000 of cost reaches the 18000bp band"
    trigger_item = create_active_item(
        base, cdm_number="CDM-2001", description="CARDIAC CATH BASIC",
        code_type="CPT", code_value="93458", cost_basis_cents=100000,
        medicare_rate_cents=50000, market_p75_cents=900000,
        effective_from="2026-09-01T00:00:00Z",
        companion_required_item_id=companion["id"], companion_window_hours=24,
    )
    assert trigger_item["gross_charge_cents"] == 240000

    set_clock("2026-09-10T00:00:00Z")
    batch = create_batch(
        base,
        window_start_date="2026-09-01T00:00:00Z",
        window_end_date="2026-09-07T00:00:00Z",
    )
    line1 = append_line(
        batch["id"], "CDM-2001", base["manager_headers"], encounter_id="ENC-1",
        payer_code="BCBS", service_datetime="2026-09-03T08:00:00Z", quantity=2,
        posted_charge_cents=480000,
    )
    line2 = append_line(
        batch["id"], "CDM-2002", base["manager_headers"], encounter_id="ENC-2",
        payer_code="BCBS", service_datetime="2026-09-04T08:00:00Z", quantity=1,
        posted_charge_cents=460000,
    )
    reconciled = reconcile_batch(batch["id"])
    findings = list_findings(batch_id=batch["id"])
    assert len(findings) == 1
    base.update(companion=companion, trigger_item=trigger_item, batch=reconciled,
                line1=line1, line2=line2, finding=findings[0])
    return base


def test_confirming_the_finding_books_the_leakage_and_trips_the_capture_hold():
    """PRD §3.9: "`estimated_lost_charge_cents` computed as the companion item's
    `gross_charge_cents` multiplied by the trigger line's `quantity`. That amount is **frozen at
    creation** and is never recomputed, even if the companion item is later repriced."
    PRD §3.9: "it records the payload's `disposition_note`, then adds the finding's
    `estimated_lost_charge_cents` to the department's `unresolved_finding_amount_cents` with
    `Department.version` advancing by 1, and — the second cascade link — sets the department's
    `capture_hold` to true once `unresolved_finding_amount_cents` reaches 500000 cents or more,
    which blocks that department from ingesting any further capture batch. The batch's
    `open_finding_count` is recomputed and `ChargeCaptureBatch.version` advances by 1."
    PRD §3.9: "Otherwise `mean_line_variance_bp` is the sum of the scored lines' already-rounded
    `line_variance_bp` values divided by the count of scored lines, rounded half up to whole basis
    points."

    Design: Corner/state_machines/finding_confirm_bubbles_up_department_capture_hold_at_threshold
    """
    base = _setup()
    batch = base["batch"]
    assert batch["mean_line_variance_bp"] == 111, (
        "line 1 scores 0 bp and line 2 scores 222 bp, so the mean of the rounded values is 111"
    )
    assert batch["open_finding_count"] == 1
    assert batch["matched_line_count"] == 1
    assert batch["exception_line_count"] == 1
    assert batch["total_expected_charge_cents"] == 930000
    assert batch["total_posted_charge_cents"] == 940000

    finding = base["finding"]
    assert_missing_charge_finding(finding)
    assert finding["status"] == "OPEN"
    assert finding["expected_charge_item_id"] == base["companion"]["id"]
    assert finding["trigger_captured_charge_id"] == base["line1"]["id"]
    assert finding["estimated_lost_charge_cents"] == 900000, (
        "the companion's 450000 gross charge times the trigger line's quantity of 2"
    )

    confirmed = disposition_finding(
        finding["id"], "CONFIRM",
        disposition_note="Recovery suite charge was never posted for ENC-1",
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["estimated_lost_charge_cents"] == 900000
    assert confirmed["version"] == 2

    department = read_department(base["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 900000
    assert department["recovered_charge_cents"] == 0
    assert department["capture_hold"] is True, "900000 is past the 500000 threshold"
    assert read_batch(base["batch"]["id"])["open_finding_count"] == 0


def test_resolving_the_finding_moves_the_same_amount_across_and_releases_the_hold():
    """PRD §3.9: "On success `recovery_captured_charge_id` is stored, and the *same literal amount* —
    the finding's frozen `estimated_lost_charge_cents` — is subtracted from the department's
    `unresolved_finding_amount_cents` and added to its `recovered_charge_cents`, so that the
    department's total identified leakage is conserved: the sum of `unresolved_finding_amount_cents`
    and `recovered_charge_cents` always equals the sum of `estimated_lost_charge_cents` over all
    findings whose `status` is `CONFIRMED` or `RESOLVED`."
    PRD §3.9: "The department's `capture_hold` is then recomputed — which is how a department digs
    itself out of a hold — and `Department.version` advances by 1."
    PRD §3.9: "It requires that the supplied `recovery_captured_charge_id` resolve to a
    `CapturedCharge` in the **same** batch whose `charge_item_id` equals the finding's
    `expected_charge_item_id`, otherwise `ERR_RECOVERY_LINE_INVALID` (422), and that the batch's
    `status` not be `CLOSED`, otherwise `ERR_INVALID_BATCH_STATE`."

    Design: Corner/state_machines/finding_resolve_conserves_department_leakage_and_releases_capture_hold
    """
    base = _setup()
    disposition_finding(base["finding"]["id"], "CONFIRM",
                        disposition_note="Companion charge is genuinely missing")
    before = read_department(base["department"]["id"])
    assert before["unresolved_finding_amount_cents"] == 900000
    assert before["capture_hold"] is True

    resolved = disposition_finding(
        base["finding"]["id"], "RESOLVE",
        recovery_captured_charge_id=base["line2"]["id"],
        disposition_note="Late posted recovery suite line located",
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["recovery_captured_charge_id"] == base["line2"]["id"]
    assert resolved["estimated_lost_charge_cents"] == 900000, "the frozen amount is untouched"
    assert resolved["version"] == 3, "created OPEN, confirmed, resolved"

    department = read_department(base["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 0
    assert department["recovered_charge_cents"] == 900000, (
        "the same literal amount moved across, conserving the identified leakage"
    )
    assert (
        department["unresolved_finding_amount_cents"] + department["recovered_charge_cents"]
        == 900000
    )
    assert department["capture_hold"] is False, "the recomputation digs the department out"
    assert_department_leakage_conserved(department, 900000)
    assert read_batch(base["batch"]["id"])["open_finding_count"] == 0
