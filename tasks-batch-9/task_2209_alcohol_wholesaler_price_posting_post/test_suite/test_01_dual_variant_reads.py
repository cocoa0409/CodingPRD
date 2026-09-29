"""Posted-price and penalty-exposure reads under both of their variants."""

from test_helpers import (
    assert_penalty_exposure_payload,
    assert_posted_price_payload,
    assert_wholesaler,
    collect_audit,
    new_audit,
    new_item,
    new_schedule,
    read_exposure,
    read_item,
    read_posted_price,
    read_wholesaler,
    run_posting,
    set_clock,
    setup_effective_schedule,
    setup_invoice_with_lines,
    setup_pending_amendment,
    submit_schedule,
    accept_amendment,
)


def _amended_and_effective_scene():
    """Two wholesalers on one posting key; A's item amended down, then made effective."""
    scene = setup_pending_amendment(
        new_case_price_cents=115_000, new_unit_price_cents=10_500
    )
    accept_amendment(scene["amendment"]["id"])
    set_clock("2026-10-01T00:00:00Z")
    scene["posting_run"] = run_posting(scene["program"]["id"])
    return scene


def _late_filing_with_collected_audit_scene():
    """One wholesaler carrying an accrued late filing penalty and a collected audit."""
    scene = setup_effective_schedule()
    item = scene["items"][0]
    setup_invoice_with_lines(
        scene,
        "2026-10-05T00:00:00Z",
        [
            {
                "item_id": item["id"],
                "cases_quantity": 10,
                "case_price_charged_cents": 115_000,
                "unit_price_charged_cents": 11_000,
            }
        ],
    )

    late_schedule = new_schedule(
        scene["wholesaler"]["id"],
        scene["program"]["id"],
        scene["agent_headers"],
        posting_month="2026-08",
    )
    new_item(
        late_schedule["id"],
        scene["brand"]["id"],
        scene["agent_headers"],
        size_ml=1_000,
        bottles_per_case=12,
        case_price_cents=121_000,
        unit_price_cents=11_000,
    )
    scene["late_schedule"] = submit_schedule(late_schedule["id"], scene["agent_headers"])

    audit = new_audit(
        scene["wholesaler"]["id"], scene["program"]["id"], "2026-10"
    )
    scene["audit"] = collect_audit(audit["id"])
    return scene


def test_as_amended_variant_reports_the_live_amended_prices():
    """An accepted amendment is visible to the default posted-price variant.

    PRD §3.7: "The **`as_amended`** variant, which applies when the `variant` query
    parameter is omitted or set to `as_amended`, reports the resolved item's live
    `case_price_cents` and `unit_price_cents` — reflecting every accepted hold amendment
    and every approved error correction."

    Design: Difficulty/dual_variant_calc/posted_price_as_certified_versus_as_amended_diverge_on_same_item
    """
    scene = _amended_and_effective_scene()
    item_a = scene["items_a"][0]

    payload = read_posted_price(
        item_a["id"], variant="as_amended", as_of="2026-10-01T00:00:00Z"
    )

    assert_posted_price_payload(payload)
    assert payload["variant"] == "as_amended"
    assert payload["item_id"] == item_a["id"]
    assert payload["resolved_item_id"] == item_a["id"]
    assert payload["posted_case_price_cents"] == 115_000
    assert payload["posted_unit_price_cents"] == 10_500


def test_as_certified_variant_reports_the_certification_snapshot():
    """The certified snapshot ignores the amendment that moved the live price.

    PRD §3.7: "The **`as_certified`** variant, which applies when `variant` is set to
    `as_certified`, reports the resolved item's `certified_case_price_cents` and
    `certified_unit_price_cents` snapshot taken at certification, ignoring every later
    amendment and correction."

    Design: Difficulty/dual_variant_calc/posted_price_as_certified_versus_as_amended_diverge_on_same_item
    """
    scene = _amended_and_effective_scene()
    item_a = scene["items_a"][0]

    payload = read_posted_price(
        item_a["id"], variant="as_certified", as_of="2026-10-01T00:00:00Z"
    )

    assert_posted_price_payload(payload)
    assert payload["variant"] == "as_certified"
    assert payload["resolved_item_id"] == item_a["id"]
    assert payload["posted_case_price_cents"] == 120_000
    assert payload["posted_unit_price_cents"] == 11_000


def test_both_posted_price_variants_resolve_one_item_and_diverge_by_the_reduction():
    """One candidate set, two answers: the divergence is exactly the amended reduction.

    PRD §3.7: "Resolution comes in two variants that read the identical candidate set
    and differ only in which price fields they report."

    Design: Difficulty/dual_variant_calc/posted_price_as_certified_versus_as_amended_diverge_on_same_item
    """
    scene = _amended_and_effective_scene()
    item_a = scene["items_a"][0]

    amended = read_posted_price(
        item_a["id"], variant="as_amended", as_of="2026-10-01T00:00:00Z"
    )
    certified = read_posted_price(
        item_a["id"], variant="as_certified", as_of="2026-10-01T00:00:00Z"
    )

    assert amended["resolved_item_id"] == certified["resolved_item_id"] == item_a["id"]
    assert amended["as_of"] == certified["as_of"] == "2026-10-01T00:00:00.000Z"
    assert (
        certified["posted_case_price_cents"] - amended["posted_case_price_cents"]
        == 5_000
    )
    assert (
        certified["posted_unit_price_cents"] - amended["posted_unit_price_cents"]
        == 500
    )

    stored = read_item(item_a["id"])
    assert stored["case_price_cents"] == 115_000
    assert stored["unit_price_cents"] == 10_500
    assert stored["certified_case_price_cents"] == 120_000
    assert stored["certified_unit_price_cents"] == 11_000


def test_assessed_exposure_variant_reports_only_the_accrued_buckets():
    """The assessed variant equals the stored exposure and projects nothing.

    PRD §3.9: "The **`assessed_exposure`** variant, which applies when the `variant`
    query parameter is omitted or set to `assessed_exposure`, reports that accrued
    figure as the exposure and nothing more; the stored `penalty_exposure_cents` on the
    wholesaler always equals this variant."

    Design: Difficulty/dual_variant_calc/penalty_exposure_assessed_versus_provisional_diverge_on_wholesaler
    """
    scene = _late_filing_with_collected_audit_scene()

    payload = read_exposure(scene["wholesaler"]["id"], variant="assessed_exposure")

    assert_penalty_exposure_payload(payload)
    assert payload["variant"] == "assessed_exposure"
    assert payload["accrued_cents"] == 250_000
    assert payload["provisional_cents"] == 0
    assert payload["exposure_cents"] == 250_000

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert_wholesaler(wholesaler)
    assert wholesaler["late_filing_penalty_accrued_cents"] == 250_000
    assert wholesaler["assessed_penalty_cents"] == 0
    assert wholesaler["penalty_exposure_cents"] == payload["exposure_cents"]


def test_provisional_exposure_variant_projects_collected_findings_without_escalation():
    """Findings of a collected audit are projected at the flat program rate.

    PRD §3.9: "No tier escalation whatsoever is applied to the provisional part — the
    multiplier is treated as `1.00` even for a wholesaler whose history would otherwise
    escalate it."

    Design: Difficulty/dual_variant_calc/penalty_exposure_assessed_versus_provisional_diverge_on_wholesaler
    """
    scene = _late_filing_with_collected_audit_scene()

    audit = scene["audit"]
    assert audit["status"] == "COLLECTED"
    assert audit["finding_count"] == 1
    assert audit["total_variance_cents"] == 50_000

    payload = read_exposure(scene["wholesaler"]["id"], variant="provisional_exposure")

    assert_penalty_exposure_payload(payload)
    assert payload["variant"] == "provisional_exposure"
    assert payload["accrued_cents"] == 250_000
    assert payload["provisional_cents"] == 20_000
    assert payload["exposure_cents"] == 270_000

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["penalty_exposure_cents"] == 250_000
    assert payload["exposure_cents"] > wholesaler["penalty_exposure_cents"]
