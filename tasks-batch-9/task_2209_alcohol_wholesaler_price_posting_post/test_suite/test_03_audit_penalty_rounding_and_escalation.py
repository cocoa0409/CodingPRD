"""Per-finding rounding, the base penalty sum, and the escalation tier boundary."""

from test_helpers import (
    assert_audit_finding,
    assert_compliance_audit,
    assess_audit,
    collect_audit,
    list_findings,
    new_audit,
    new_invoice,
    new_invoice_line,
    read_audit,
    read_wholesaler,
    set_clock,
    setup_effective_schedule,
    validate_invoice,
)

NEVADA_PROGRAM = {
    "state_code": "NV",
    "program_name": "Nevada Price Posting Program",
    "off_posted_penalty_rate_pct": 0.375,
}


def _flagged_invoice(scene, invoice_date, charged_case_prices):
    """Open an invoice, add one single-case line per charged price, and validate it."""
    item = scene["items"][0]
    invoice = new_invoice(
        scene["wholesaler"]["id"], invoice_date, scene["agent_headers"]
    )
    for charged in charged_case_prices:
        new_invoice_line(
            invoice["id"],
            item["id"],
            charged,
            item["unit_price_cents"],
            scene["agent_headers"],
            cases_quantity=1,
            bottles_quantity=0,
        )
    return validate_invoice(invoice["id"], scene["agent_headers"])


def _fractional_rate_scene():
    """A program whose penalty rate produces a half cent on every finding."""
    scene = setup_effective_schedule(program_overrides=NEVADA_PROGRAM)

    _flagged_invoice(scene, "2026-10-03T00:00:00Z", [119_000, 119_000, 119_000])
    audit_one = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], "2026-10"
    )
    collect_audit(audit_one["id"])
    scene["audit_one"] = assess_audit(audit_one["id"])

    _flagged_invoice(scene, "2026-11-04T00:00:00Z", [115_900, 111_700])
    audit_two = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], "2026-11"
    )
    scene["audit_two"] = collect_audit(audit_two["id"])
    return scene


def _violation_history_scene():
    """Two prior violations recorded, then two further audits waiting to be assessed."""
    scene = setup_effective_schedule()

    _flagged_invoice(scene, "2026-10-05T00:00:00Z", [118_000, 118_000])
    audit_one = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], "2026-10"
    )
    collect_audit(audit_one["id"])
    scene["audit_one"] = assess_audit(audit_one["id"])

    set_clock("2026-11-06T00:00:00Z")
    _flagged_invoice(scene, "2026-11-05T00:00:00Z", [110_000])
    audit_two = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], "2026-11"
    )
    scene["audit_two"] = collect_audit(audit_two["id"])

    set_clock("2026-12-06T00:00:00Z")
    _flagged_invoice(scene, "2026-12-05T00:00:00Z", [100_000])
    audit_three = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], "2026-12"
    )
    scene["audit_three"] = collect_audit(audit_three["id"])
    return scene


def test_base_penalty_rounds_each_finding_before_summing_them():
    """Two half-cent components round up individually, so the base is a cent above the raw sum.

    PRD §3.9: "Rounding each finding before summing is the rule; summing the raw
    products and rounding once at the end produces a different figure and is not
    permitted."

    Design: Difficulty/combinatorial_formula/audit_penalty_rounds_each_finding_before_summing_then_escalates_by_prior_history
    """
    scene = _fractional_rate_scene()
    audit = read_audit(scene["audit_two"]["id"])

    assert_compliance_audit(audit)
    assert audit["status"] == "COLLECTED"
    assert audit["finding_count"] == 2
    assert audit["total_variance_cents"] == 12_400
    assert audit["base_penalty_cents"] == 4_651

    findings = list_findings(audit["id"])
    assert len(findings) == 2
    for finding in findings:
        assert_audit_finding(finding)
    assert [finding["variance_cents"] for finding in findings] == [4_100, 8_300]
    assert [finding["penalty_component_cents"] for finding in findings] == [1_538, 3_113]


def test_escalated_penalty_applies_the_tier_to_the_already_rounded_base():
    """Three prior violations lift the multiplier, and the escalated half cent rounds up too.

    PRD §3.9: "The `penalty_assessed_cents` is then `base_penalty_cents` multiplied by
    `tier_multiplier`, rounded half up to whole cents — a second rounding, applied after
    the per-finding rounding that produced `base_penalty_cents`."

    Design: Difficulty/combinatorial_formula/audit_penalty_rounds_each_finding_before_summing_then_escalates_by_prior_history
    """
    scene = _fractional_rate_scene()

    first = read_audit(scene["audit_one"]["id"])
    assert first["finding_count"] == 3
    assert first["base_penalty_cents"] == 1_125
    assert first["prior_violation_count"] == 0
    assert first["tier_multiplier"] == 1.0
    assert first["penalty_assessed_cents"] == 1_125

    second = assess_audit(scene["audit_two"]["id"])
    assert_compliance_audit(second)
    assert second["status"] == "ASSESSED"
    assert second["prior_violation_count"] == 3
    assert second["tier_multiplier"] == 1.5
    assert second["penalty_assessed_cents"] == 6_977

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["assessed_penalty_cents"] == 8_102
    assert wholesaler["off_posted_violation_count"] == 5
    assert wholesaler["penalty_exposure_cents"] == 8_102


def test_tier_multiplier_holds_at_exactly_two_prior_violations():
    """A history of exactly two violations is still the unescalated band.

    PRD §3.9: "The escalation tier is read from that captured figure: a
    `prior_violation_count` of 2 or fewer yields a `tier_multiplier` of `1.00`; a
    `prior_violation_count` of at least 3 and at most 9 yields `1.50`; a
    `prior_violation_count` of 10 or more yields `2.00`."

    Design: Difficulty/boundary_precision_check/audit_tier_multiplier_holds_at_exactly_two_prior_violations_and_escalates_at_three
    """
    scene = _violation_history_scene()

    first = read_audit(scene["audit_one"]["id"])
    assert first["finding_count"] == 2
    assert first["penalty_assessed_cents"] == 1_600

    before = read_wholesaler(scene["wholesaler"]["id"])
    assert before["off_posted_violation_count"] == 2

    second = assess_audit(scene["audit_two"]["id"])
    assert_compliance_audit(second)
    assert second["base_penalty_cents"] == 4_000
    assert second["prior_violation_count"] == 2
    assert second["tier_multiplier"] == 1.0
    assert second["penalty_assessed_cents"] == 4_000


def test_tier_multiplier_escalates_at_three_prior_violations():
    """One violation past the boundary and the same base penalty is charged at one and a half.

    PRD §3.9: "Its first act is the one most easily got wrong: the audit captures
    `prior_violation_count` from the wholesaler's `off_posted_violation_count` **as it
    stands before this audit's own `finding_count` is added to it**."

    Design: Difficulty/boundary_precision_check/audit_tier_multiplier_holds_at_exactly_two_prior_violations_and_escalates_at_three
    """
    scene = _violation_history_scene()

    assess_audit(scene["audit_two"]["id"])
    third = assess_audit(scene["audit_three"]["id"])

    assert_compliance_audit(third)
    assert third["status"] == "ASSESSED"
    assert third["base_penalty_cents"] == 8_000
    assert third["prior_violation_count"] == 3
    assert third["tier_multiplier"] == 1.5
    assert third["penalty_assessed_cents"] == 12_000


def test_both_assessments_accumulate_into_the_wholesaler_ledger():
    """Each assessment adds its own penalty and its own finding count to the wholesaler.

    PRD §3.9: "The audit's `penalty_assessed_cents` is added to the wholesaler's
    `assessed_penalty_cents`, the audit's `finding_count` is added to the wholesaler's
    `off_posted_violation_count`, `penalty_exposure_cents` is recomputed as the sum of
    the four buckets, and the wholesaler's `version` is advanced by 1."

    Design: Difficulty/boundary_precision_check/audit_tier_multiplier_holds_at_exactly_two_prior_violations_and_escalates_at_three
    """
    scene = _violation_history_scene()

    assess_audit(scene["audit_two"]["id"])
    assess_audit(scene["audit_three"]["id"])

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["off_posted_violation_count"] == 4
    assert wholesaler["assessed_penalty_cents"] == 17_600
    assert wholesaler["penalty_exposure_cents"] == 17_600

    assert read_audit(scene["audit_two"]["id"])["status"] == "ASSESSED"
    assert read_audit(scene["audit_three"]["id"])["status"] == "ASSESSED"

    findings = list_findings(scene["audit_two"]["id"])
    assert len(findings) == 1
    assert findings[0]["variance_cents"] == 10_000
    assert findings[0]["penalty_component_cents"] == 4_000
