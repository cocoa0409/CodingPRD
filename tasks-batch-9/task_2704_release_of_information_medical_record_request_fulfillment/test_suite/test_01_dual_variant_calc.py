"""Two-variant calculations: one input set, two pinned answers."""

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    Instant,
    assert_event_count,
    assert_line,
    assert_line_sequence_contiguous,
    assert_no_line_type,
    assert_page_ledger,
    assert_subtotal_reconciles,
    line_types,
)
from test_helpers.test_users import PLATFORM_ADMIN


# --------------------------------------------------------------------------
# invoice_variant_divergence_third_party_retail_vs_patient_access_cost_based
# --------------------------------------------------------------------------
def _two_variants_on_the_same_page_count(api):
    """One 62-page retail request with certification and one 62-page right-of-access
    request, both electronic, both at RELEASE_READY, both priced."""
    world = fx.base_world(api)
    attorney = fx.make_attorney(api)
    authorization = fx.make_authorization(api, world["patient_id"], attorney["id"])
    self_requester = fx.make_patient_requester(api, world["patient_id"])

    retail = fx.open_third_party_request(
        api,
        {**world, "requester_id": attorney["id"], "authorization_id": authorization["id"]},
        date_range_start="2024-01-01",
        date_range_end="2024-12-31",
        delivery_format="SECURE_PORTAL",
        certification_requested=True,
    )
    fx.walk_to_sensitive_review(
        api, retail["id"], [{"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 62}]
    )
    fx.run_sensitive_review(api, retail["id"], [])
    retail_invoice = fx.create_invoice(api, retail["id"])

    access = fx.open_patient_access_request(
        api,
        {**world, "requester_id": self_requester["id"]},
        date_range_start="2025-01-01",
        date_range_end="2025-12-31",
        delivery_format="SECURE_PORTAL",
    )
    fx.walk_to_sensitive_review(
        api, access["id"], [{"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 62}]
    )
    fx.run_sensitive_review(api, access["id"], [])
    access_invoice = fx.create_invoice(api, access["id"])

    return {
        "world": world,
        "retail_request_id": retail["id"],
        "retail_invoice": retail_invoice,
        "access_request_id": access["id"],
        "access_invoice": access_invoice,
    }


def test_third_party_retail_variant_prices_sixty_two_pages_with_tiers_and_certification(api):
    """The retail variant emits base retrieval, both tiers and a certification line.

    PRD: "The invoice's `variant` is computed, never supplied: it is `PATIENT_ACCESS_COST_BASED` when the request's `access_basis` is `PATIENT_RIGHT_OF_ACCESS`, and `THIRD_PARTY_RETAIL` otherwise."

    Design: Difficulty/dual_variant_calc/invoice_variant_divergence_third_party_retail_vs_patient_access_cost_based
    """
    scenario = _two_variants_on_the_same_page_count(api)
    invoice = scenario["retail_invoice"]

    assert invoice["variant"] == "THIRD_PARTY_RETAIL"
    assert invoice["billable_page_count_snapshot"] == 62
    assert invoice["subtotal_cents"] == 3651
    assert invoice["applicable_cap_cents"] == 6500
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["amount_due_cents"] == 3651

    lines = fx.read_lines(api, invoice["id"])
    assert_line_sequence_contiguous(lines)
    assert line_types(lines) == [
        "BASE_RETRIEVAL",
        "PER_PAGE_TIER1",
        "PER_PAGE_TIER2",
        "CERTIFICATION",
    ]
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "PER_PAGE_TIER2", 37, 12500, 463)
    assert_line(lines[3], "CERTIFICATION", 1, 1000000, 1000)
    assert_no_line_type(lines, "POSTAGE")
    assert_subtotal_reconciles(invoice, lines)


def test_patient_access_cost_based_variant_prices_the_same_pages_with_one_flat_line(api):
    """The cost-based variant charges copying cost alone: a single flat per-page line.

    PRD: "This variant emits no `BASE_RETRIEVAL` line, no `CERTIFICATION` line, no `LEGACY_RETRIEVAL` line, and no tiered per-page lines at all: there is no clerical fee and no certification fee under the right of access."

    Design: Difficulty/dual_variant_calc/invoice_variant_divergence_third_party_retail_vs_patient_access_cost_based
    """
    scenario = _two_variants_on_the_same_page_count(api)
    invoice = scenario["access_invoice"]

    assert invoice["variant"] == "PATIENT_ACCESS_COST_BASED"
    assert invoice["billable_page_count_snapshot"] == 62
    assert invoice["subtotal_cents"] == 620
    assert invoice["amount_due_cents"] == 620

    lines = fx.read_lines(api, invoice["id"])
    assert len(lines) == 1
    assert_line(lines[0], "PER_PAGE_FLAT", 62, 10000, 620)
    assert lines[0]["sequence"] == 1
    assert_no_line_type(lines, "BASE_RETRIEVAL")
    assert_no_line_type(lines, "CERTIFICATION")
    assert_no_line_type(lines, "PER_PAGE_TIER1")
    assert_no_line_type(lines, "PER_PAGE_TIER2")
    assert_subtotal_reconciles(invoice, lines)


def test_the_two_variants_diverge_by_3031_cents_on_identical_page_counts(api):
    """Identical 62-page sets, identical fee rule, two answers 3031 cents apart.

    PRD: "The `access_basis` is the polymorphic pivot of the whole system: it selects which deadline field governs, which invoice variant prices the pages, whether an authorization is needed at all, and whether an unsecured transmission is ever permissible."

    Design: Difficulty/dual_variant_calc/invoice_variant_divergence_third_party_retail_vs_patient_access_cost_based
    """
    scenario = _two_variants_on_the_same_page_count(api)
    retail = scenario["retail_invoice"]
    access = scenario["access_invoice"]

    assert retail["billable_page_count_snapshot"] == access["billable_page_count_snapshot"] == 62
    assert retail["subtotal_cents"] - access["subtotal_cents"] == 3031
    assert retail["amount_due_cents"] - access["amount_due_cents"] == 3031
    assert len(fx.read_lines(api, retail["id"])) == 4
    assert len(fx.read_lines(api, access["id"])) == 1


# --------------------------------------------------------------------------
# turnaround_penalty_variant_divergence_strict_vs_safe_harbor
# --------------------------------------------------------------------------
def _released_five_and_a_quarter_days_late(api):
    """62 pages by paper mail with certification, invoiced at 4501 and paid, then
    released at 2026-09-05T06:00:00Z against a 2026-08-31T00:00:00Z deadline."""
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(
        api, world, 62, delivery_format="PAPER_MAIL", certification_requested=True
    )
    request_id = scenario["request_id"]
    invoice = fx.create_invoice(api, request_id)
    assert invoice["amount_due_cents"] == 4501
    fx.issue_invoice(api, invoice["id"])
    fx.pay_invoice(api, invoice["id"], 4501)

    before = fx.read_request(api, request_id)
    assert before["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")

    fx.set_clock(api, "2026-09-05T06:00:00Z")
    fx.release_request(api, request_id)
    return {"world": world, "request_id": request_id, "invoice_id": invoice["id"]}


def test_strict_lateness_rounds_a_partial_day_up_and_charges_six_days(api):
    """5.25 days of overrun is six chargeable days under the statutory measure.

    PRD: "Five and a quarter days overrun therefore counts as six late days."

    Design: Difficulty/dual_variant_calc/turnaround_penalty_variant_divergence_strict_vs_safe_harbor
    """
    scenario = _released_five_and_a_quarter_days_late(api)
    request = fx.read_request(api, scenario["request_id"])

    assert request["released_at"] == Instant("2026-09-05T06:00:00Z")
    assert request["penalty_exposure_cents"] == 15000

    turnaround = fx.get_success_data(api.get_turnaround(scenario["request_id"], PLATFORM_ADMIN))
    assert turnaround["breached"] is True
    assert turnaround["days_late_strict"] == 6
    assert turnaround["penalty_exposure_cents"] == 15000


def test_safe_harbor_lateness_counts_business_days_and_forgives_the_grace(api):
    """The same overrun is four business days, two of which the grace forgives.

    PRD: "Both measures therefore share one per-day rate and one ceiling, and differ only in how they count days."

    Design: Difficulty/dual_variant_calc/turnaround_penalty_variant_divergence_strict_vs_safe_harbor
    """
    scenario = _released_five_and_a_quarter_days_late(api)
    request = fx.read_request(api, scenario["request_id"])

    assert request["safe_harbor_penalty_cents"] == 5000

    turnaround = fx.get_success_data(api.get_turnaround(scenario["request_id"], PLATFORM_ADMIN))
    assert turnaround["days_late_business"] == 4
    assert turnaround["chargeable_days"] == 2
    assert turnaround["safe_harbor_penalty_cents"] == 5000
    assert turnaround["days_late_strict"] == 6
    assert turnaround["penalty_exposure_cents"] == 15000


def test_the_facility_ledger_and_the_breach_event_follow_the_strict_measure_only(api):
    """The facility aggregate mirrors the strict figure, and one breach event is appended.

    PRD: "The fourth field, `penalty_exposure_cents` on the facility, is the sum of `penalty_exposure_cents` over every request whose `facility_id` names this facility, and it is refreshed whenever any request's penalty exposure moves."

    Design: Difficulty/dual_variant_calc/turnaround_penalty_variant_divergence_strict_vs_safe_harbor
    """
    scenario = _released_five_and_a_quarter_days_late(api)

    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert facility["penalty_exposure_cents"] == 15000

    events = fx.read_events(api, scenario["request_id"])
    assert_event_count(events, "STATUTORY_DEADLINE_BREACHED", 1)


# --------------------------------------------------------------------------
# page_ledger_variant_gross_retrieved_vs_net_released
# --------------------------------------------------------------------------
def _gross_eighty_pages_net_fifty_seven(api):
    """40 general-medical + 22 behavioural-health + 18 HIV pages; the HIV segment is
    withheld and five behavioural-health pages are redacted and approved."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api,
        world,
        requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
            {"label": "hiv", "category": "HIV", "page_count": 18, "source_system": "SCANNED_PAPER"},
        ],
    )
    fx.run_sensitive_review(
        api,
        request["id"],
        [f.include_decision(ids["bh"], redaction_required=True), f.withhold_decision(ids["hiv"])],
    )
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def test_gross_retrieved_and_net_releasable_page_measures_diverge(api):
    """80 pages retrieved, 57 releasable: the ledger partitions rather than overlaps.

    PRD: "Redacted pages therefore count only once a redaction has been approved: an `APPLIED`-but-unapproved redaction leaves `billable_page_count` completely untouched."

    Design: Difficulty/dual_variant_calc/page_ledger_variant_gross_retrieved_vs_net_released
    """
    scenario = _gross_eighty_pages_net_fifty_seven(api)
    request_id = scenario["request_id"]
    bh = scenario["segment_ids"]["bh"]

    fx.apply_redaction(api, bh, 5)
    assert_page_ledger(fx.read_request(api, request_id), 80, 62, 18, 0)

    fx.approve_redaction(api, bh)
    released = fx.read_request(api, request_id)
    assert released["fulfillment_status"] == "RELEASE_READY"
    assert_page_ledger(released, 80, 57, 18, 5)
    assert 80 == 57 + 18 + 5


def test_withheld_pages_leave_the_billable_measure_and_append_one_event(api):
    """A WITHHOLD moves its pages into withheld_page_count and records one event.

    PRD: "A `WITHHOLD` moves the segment to `WITHHELD` with no preconditions of its own beyond the completeness rule, appends a `SENSITIVE_WITHHOLD` compliance event for that segment, and moves that segment's `page_count` out of `billable_page_count` and into `withheld_page_count`."

    Design: Difficulty/dual_variant_calc/page_ledger_variant_gross_retrieved_vs_net_released
    """
    scenario = _gross_eighty_pages_net_fifty_seven(api)
    request_id = scenario["request_id"]

    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 5)
    fx.approve_redaction(api, scenario["segment_ids"]["bh"])

    request = fx.read_request(api, request_id)
    assert request["withheld_page_count"] == 18
    assert request["billable_page_count"] == 57
    assert fx.read_segment(api, scenario["segment_ids"]["hiv"])["sensitivity_status"] == "WITHHELD"
    assert_event_count(fx.read_events(api, request_id), "SENSITIVE_WITHHOLD", 1)


def test_only_the_net_measure_reaches_the_invoice(api):
    """The invoice prices 57 pages even though 80 were retrieved.

    PRD: "`billable_page_count` is the only page count an invoice may ever price."

    Design: Difficulty/dual_variant_calc/page_ledger_variant_gross_retrieved_vs_net_released
    """
    scenario = _gross_eighty_pages_net_fifty_seven(api)
    request_id = scenario["request_id"]
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 5)
    fx.approve_redaction(api, scenario["segment_ids"]["bh"])

    invoice = fx.create_invoice(api, request_id)
    assert invoice["billable_page_count_snapshot"] == 57
    assert fx.read_request(api, request_id)["page_count_total"] == 80

    lines = fx.read_lines(api, invoice["id"])
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "PER_PAGE_TIER2", 32, 12500, 400)
    assert invoice["subtotal_cents"] == 2588
    assert invoice["amount_due_cents"] == 2588
