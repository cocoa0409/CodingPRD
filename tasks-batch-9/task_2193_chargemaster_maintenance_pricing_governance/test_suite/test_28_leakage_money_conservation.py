"""Department leakage money is conserved across CONFIRM then the compensating RESOLVE."""
from test_helpers import (
    api_client, get_success_data,
    setup_base, create_active_item, create_batch, append_line, reconcile_batch,
    read_item, read_facility, read_batch, read_department, list_findings,
    disposition_finding, set_clock,
    STANDARD_TIERS, ANALYST,
)


def _read_line(line_id: str) -> dict:
    return get_success_data(api_client.get_captured_charge(line_id, ANALYST))

TIER_2_MARKUP_ITEM = dict(
    code_type="CDM_INTERNAL", cost_basis_cents=100000,
    medicare_rate_cents=50000, market_p75_cents=500000,
    effective_from="2026-08-01T00:00:00Z",
)
TIER_1_MARKUP_ITEM = dict(
    code_type="CDM_INTERNAL", cost_basis_cents=40000,
    medicare_rate_cents=20000, market_p75_cents=300000,
    effective_from="2026-08-01T00:00:00Z",
)


def _setup():
    """A RECONCILING batch of four MATCHED lines on two encounters, each encounter's companion
    posted 48 hours after its trigger, so two OPEN findings of 256000 cents each are waiting."""
    set_clock("2026-08-01T00:00:00Z")
    base = setup_base(
        facility_overrides={
            "name": "St Vitus Medical Center",
            "cms_certification_number": "CCN-2193-LEAKAGE",
            "rounding_mode": "NEAREST_CENT",
            "aggregate_markup_limit_bp": 40000,
        },
        revenue_code_overrides={
            "code": "0300", "description": "Laboratory - general", "requires_hcpcs": False,
            "allowed_code_types": ["CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL"],
            "pricing_class": "PROCEDURE", "status": "ACTIVE",
        },
        department_overrides={"name": "Cardiac Cath Lab", "cost_center_code": "CC-4100"},
        price_rule_overrides={
            "pricing_method": "COST_PLUS_MARKUP",
            "markup_tiers": STANDARD_TIERS,
            "min_medicare_multiple_bp": 10000,
            "market_cap_multiple_bp": 20000,
            "effective_from": "2026-08-01T00:00:00Z",
        },
        manager_user_id="dept_mgr_1",
    )
    companion = create_active_item(
        base, cdm_number="CDM-2002", description="Cardiac catheter sheath kit",
        **TIER_1_MARKUP_ITEM
    )
    trigger = create_active_item(
        base, cdm_number="CDM-1001", description="Left heart catheterization procedure",
        companion_required_item_id=companion["id"], companion_window_hours=24,
        **TIER_2_MARKUP_ITEM
    )
    batch = create_batch(
        base,
        window_start_date="2026-08-03T00:00:00Z",
        window_end_date="2026-08-10T23:59:59Z",
    )
    mgr = base["manager_headers"]

    def _line(cdm, encounter, when, posted):
        return append_line(
            batch["id"], cdm, mgr, encounter_id=encounter, payer_code="BCBS_STATE",
            service_datetime=when, quantity=2, posted_charge_cents=posted,
        )

    l1 = _line("CDM-1001", "ENC-1", "2026-08-04T08:00:00Z", 480000)
    l2 = _line("CDM-2002", "ENC-1", "2026-08-06T08:00:00Z", 256000)
    l3 = _line("CDM-1001", "ENC-2", "2026-08-05T09:00:00Z", 480000)
    l4 = _line("CDM-2002", "ENC-2", "2026-08-07T09:00:00Z", 256000)
    base.update({
        "companion_item": companion, "trigger_item": trigger,
        "batch": reconcile_batch(batch["id"]),
        "l1": l1, "l2": l2, "l3": l3, "l4": l4,
        "f1": list_findings(trigger_captured_charge_id=l1["id"])[0],
        "f3": list_findings(trigger_captured_charge_id=l3["id"])[0],
    })
    return base


def test_two_confirmations_accumulate_the_full_leakage_and_raise_the_hold():
    """PRD §3.9: "When no companion is present and no finding with that
    `trigger_captured_charge_id` already sits in `OPEN`, `CONFIRMED` or `RESOLVED`, a new
    `MissingChargeFinding` is created in `OPEN` with `batch_id` and `department_id` copied from
    the batch, `trigger_captured_charge_id` naming the unpaired line,
    `expected_charge_item_id` naming the companion item that should have been captured, and
    `estimated_lost_charge_cents` computed as the companion item's `gross_charge_cents`
    multiplied by the trigger line's `quantity`."
    PRD §3.9: "it records the payload's `disposition_note`, then adds the finding's
    `estimated_lost_charge_cents` to the department's `unresolved_finding_amount_cents` with
    `Department.version` advancing by 1, and — the second cascade link — sets the department's
    `capture_hold` to true once `unresolved_finding_amount_cents` reaches 500000 cents or more,
    which blocks that department from ingesting any further capture batch."
    PRD §2.11: "`aggregate_markup_ratio_bp` (the aggregate gross charge multiplied by 10000,
    divided by the aggregate cost basis, rounded half up — and defined as 0 when the aggregate
    cost basis is 0)"

    Design: Difficulty/compensating_invariant/compensating_invariant__department_leakage_money_conserved_across_confirm_then_resolve
    """
    s = _setup()
    assert read_item(s["companion_item"]["id"])["gross_charge_cents"] == 128000, (
        "40000 cents of cost in the 32000bp tier"
    )
    assert read_item(s["trigger_item"]["id"])["gross_charge_cents"] == 240000, (
        "100000 cents of cost in the 24000bp tier"
    )
    facility = read_facility(s["facility"]["id"])
    assert facility["aggregate_gross_charge_cents"] == 368000
    assert facility["aggregate_markup_ratio_bp"] == 26286, (
        "368000 * 10000 / 140000 = 26285.71, rounded half up"
    )

    line = _read_line(s["l1"]["id"])
    assert line["expected_charge_cents"] == 480000, "240000 cents times a quantity of 2"
    assert line["line_variance_bp"] == 0
    assert line["match_status"] == "MATCHED"
    batch = read_batch(s["batch"]["id"])
    assert batch["matched_line_count"] == 4
    assert batch["exception_line_count"] == 0
    assert batch["mean_line_variance_bp"] == 0
    assert batch["total_posted_charge_cents"] == 1472000
    assert batch["total_expected_charge_cents"] == 1472000
    assert s["f1"]["estimated_lost_charge_cents"] == 256000
    assert s["f3"]["estimated_lost_charge_cents"] == 256000

    first = disposition_finding(
        s["f1"]["id"], "CONFIRM",
        disposition_note="companion sheath kit never posted for ENC-1",
    )
    assert first["status"] == "CONFIRMED"
    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 256000
    assert department["recovered_charge_cents"] == 0
    assert department["capture_hold"] is False, "256000 is short of the 500000-cent threshold"

    disposition_finding(
        s["f3"]["id"], "CONFIRM",
        disposition_note="companion sheath kit never posted for ENC-2",
    )
    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 512000
    assert department["recovered_charge_cents"] == 0
    assert (
        department["unresolved_finding_amount_cents"]
        + department["recovered_charge_cents"] == 512000
    ), "the leakage total after the two forward actions"
    assert department["capture_hold"] is True, "512000 reaches the 500000-cent threshold"


def test_the_two_resolutions_move_every_cent_without_changing_the_total():
    """PRD §3.9: "On success `recovery_captured_charge_id` is stored, and the *same literal
    amount* — the finding's frozen `estimated_lost_charge_cents` — is subtracted from the
    department's `unresolved_finding_amount_cents` and added to its `recovered_charge_cents`, so
    that the department's total identified leakage is conserved: the sum of
    `unresolved_finding_amount_cents` and `recovered_charge_cents` always equals the sum of
    `estimated_lost_charge_cents` over all findings whose `status` is `CONFIRMED` or `RESOLVED`."
    PRD §3.9: "The department's `capture_hold` is then recomputed — which is how a department
    digs itself out of a hold — and `Department.version` advances by 1."
    PRD §3.9: "That amount is **frozen at creation** and is never recomputed, even if the
    companion item is later repriced."

    Design: Difficulty/compensating_invariant/compensating_invariant__department_leakage_money_conserved_across_confirm_then_resolve
    """
    s = _setup()
    for finding_id, encounter in ((s["f1"]["id"], "ENC-1"), (s["f3"]["id"], "ENC-2")):
        disposition_finding(finding_id, "CONFIRM",
                            disposition_note=f"companion sheath kit never posted for {encounter}")
    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 512000
    assert department["capture_hold"] is True

    first = disposition_finding(
        s["f1"]["id"], "RESOLVE",
        disposition_note="late-posted companion line located for ENC-1",
        recovery_captured_charge_id=s["l2"]["id"],
    )
    assert first["status"] == "RESOLVED"
    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 256000
    assert department["recovered_charge_cents"] == 256000
    assert (
        department["unresolved_finding_amount_cents"]
        + department["recovered_charge_cents"] == 512000
    ), "the compensating action moved money between the two buckets, it did not create any"
    assert department["capture_hold"] is False, "256000 no longer reaches the threshold"

    second = disposition_finding(
        s["f3"]["id"], "RESOLVE",
        disposition_note="late-posted companion line located for ENC-2",
        recovery_captured_charge_id=s["l4"]["id"],
    )
    assert second["status"] == "RESOLVED"
    department = read_department(s["department"]["id"])
    assert department["unresolved_finding_amount_cents"] == 0
    assert department["recovered_charge_cents"] == 512000
    assert (
        department["unresolved_finding_amount_cents"]
        + department["recovered_charge_cents"] == 512000
    ), "the invariant holds at every step of the confirm-then-resolve walk"
    assert department["capture_hold"] is False

    assert first["recovery_captured_charge_id"] == s["l2"]["id"]
    assert second["recovery_captured_charge_id"] == s["l4"]["id"]
    assert first["estimated_lost_charge_cents"] == 256000, "frozen at creation"
    assert second["estimated_lost_charge_cents"] == 256000
    assert read_batch(s["batch"]["id"])["open_finding_count"] == 0
