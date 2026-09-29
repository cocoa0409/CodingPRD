"""Two counting doctrines on one dataset: statement basis, and gross versus deduplicated reach."""

from prd_bench_local_runner.testing import validate_success

from test_helpers.api_client import api_client
from test_helpers.factories import digital_snapshot_payload
from test_helpers.fixtures import (
    add_complete_rule_set,
    move_clock,
    open_statement,
    qualify_subscriber,
    read_statement,
    read_subscriber,
    recompute_statement,
    register_publication,
)
from test_helpers.test_users import MANAGER_HEADERS

PERIOD_START = "2026-07-01T00:00:00Z"
PERIOD_END = "2026-09-01T00:00:00Z"


def test_basis_switch_on_recompute_reshapes_the_whole_breakdown():
    """Purging one recipient's evidence shrinks the core, which re-derives a smaller allowance.

    "Under `AUDIT_VERIFIED`, a recipient additionally needs a qualification request
    of its own in status `VERIFIED` whose cited source document has `purge_status`
    `RETAINED` **and** whose `retention_expires_at` is at or after `period_end`.
    Recipients whose evidence was purged, or whose evidence would already have
    expired by the close of the period, drop out of the population."

    Design: Difficulty/dual_variant_calc/breakdown_basis_variant_divergence_on_recompute
    """
    publication = register_publication(
        name="Basis Divergence Monthly",
        industry_code="MANUFACTURING",
        controlled_cap_pct=25.00,
        source_doc_retention_months=36,
    )
    add_complete_rule_set(publication["id"])

    def enrol(company_name, subscription_class, copies, **extra):
        return qualify_subscriber(
            publication["id"],
            signed_at="2026-07-01T00:00:00Z",
            captured_at="2026-07-15T00:00:00Z",
            company_name=company_name,
            subscription_class=subscription_class,
            copies=copies,
            **extra,
        )

    paid = enrol("Alpha Paid Works", "PAID", 600, paid_amount_cents=48000)
    non_paid = enrol("Bravo Requested Works", "QUALIFIED_NON_PAID", 300)
    controlled = enrol("Charlie Directed Works", "CONTROLLED", 400)
    assert paid["subscriber"]["qualified_at"].startswith("2026-08-01T00:00:00")

    move_clock("2026-10-01T00:00:00Z")
    statement = open_statement(
        publication["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["statement_type"] == "PUBLISHER_STATEMENT"
    assert statement["paid_copies"] == 600
    assert statement["qualified_non_paid_copies"] == 300
    # A core of 900 under a 25.00 percent cap admits 300 of the 400 directed copies.
    assert statement["controlled_copies_included"] == 300
    assert statement["controlled_copies_excess"] == 100
    assert statement["total_qualified_copies"] == 1200

    # Retention is 36 months from capture, so the card may be destroyed in 2029.
    move_clock("2029-07-15T00:00:00Z")
    purged = validate_success(
        api_client.purge_source_document(
            non_paid["source_document"]["id"],
            {"purge_reason": "retention elapsed"},
            MANAGER_HEADERS,
        ),
        200,
    )
    assert purged["purge_status"] == "PURGED"

    audited = recompute_statement(statement["id"], basis="AUDIT_VERIFIED")
    assert audited["statement_type"] == "AUDITED"
    assert audited["paid_copies"] == 600
    # The purged recipient leaves the population entirely, not merely its copies.
    assert audited["qualified_non_paid_copies"] == 0
    # A core of 600 re-derives an allowance of 200, so 200 of the 400 are admitted.
    assert audited["controlled_copies_included"] == 200
    assert audited["controlled_copies_excess"] == 200
    assert audited["total_qualified_copies"] == 800
    # The 400-copy delta is larger than the 300 purged copies.
    assert statement["total_qualified_copies"] - audited["total_qualified_copies"] == 400

    stored = read_statement(statement["id"])
    assert stored["basis"] == "AUDIT_VERIFIED"
    assert stored["total_qualified_copies"] == 800
    # Evidence retention is not a qualification dimension, so the recipient holds.
    assert read_subscriber(non_paid["subscriber"]["id"])["qualification_status"] == "QUALIFIED"
    assert read_subscriber(controlled["subscriber"]["id"])["copies"] == 400


def test_audit_verified_drops_evidence_that_expired_before_period_end():
    """A retained card whose retention had already lapsed by the close is still no evidence.

    "Under `AUDIT_VERIFIED`, a recipient additionally needs a qualification request
    of its own in status `VERIFIED` whose cited source document has `purge_status`
    `RETAINED` **and** whose `retention_expires_at` is at or after `period_end`."

    Design: Difficulty/dual_variant_calc/breakdown_basis_variant_divergence_on_recompute
    """
    publication = register_publication(
        name="Evidence Horizon Monthly",
        industry_code="MANUFACTURING",
        controlled_cap_pct=25.00,
        source_doc_retention_months=3,
    )
    add_complete_rule_set(publication["id"])

    paid = qualify_subscriber(
        publication["id"],
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name="Delta Paid Works",
        subscription_class="PAID",
        copies=600,
        paid_amount_cents=48000,
    )
    # Captured in April under a three-month retention, so the card expires
    # 2026-07-15 — before the period closes on 2026-09-01 — yet is never purged.
    stale_evidence = qualify_subscriber(
        publication["id"],
        signed_at="2026-04-01T00:00:00Z",
        captured_at="2026-04-15T00:00:00Z",
        company_name="Echo Requested Works",
        subscription_class="QUALIFIED_NON_PAID",
        copies=300,
    )
    qualify_subscriber(
        publication["id"],
        signed_at="2026-07-01T00:00:00Z",
        captured_at="2026-07-15T00:00:00Z",
        company_name="Foxtrot Directed Works",
        subscription_class="CONTROLLED",
        copies=250,
    )
    assert stale_evidence["source_document"]["purge_status"] == "RETAINED"
    assert stale_evidence["source_document"]["retention_expires_at"].startswith(
        "2026-07-15T00:00:00"
    )
    assert paid["source_document"]["retention_expires_at"].startswith(
        "2026-10-15T00:00:00"
    )

    move_clock("2026-10-01T00:00:00Z")
    audited = open_statement(
        publication["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AUDIT_VERIFIED",
    )
    # The basis is supplied, so `statement_type` is derived rather than sent.
    assert audited["statement_type"] == "AUDITED"
    assert audited["paid_copies"] == 600
    assert audited["qualified_non_paid_copies"] == 0
    assert audited["controlled_copies_included"] == 200
    assert audited["controlled_copies_excess"] == 50
    assert audited["total_qualified_copies"] == 800

    publisher_view = recompute_statement(audited["id"], basis="AS_OF_PERIOD_END")
    assert publisher_view["statement_type"] == "PUBLISHER_STATEMENT"
    assert publisher_view["paid_copies"] == 600
    # No evidence gate at all under the publisher's own doctrine.
    assert publisher_view["qualified_non_paid_copies"] == 300
    # A core of 900 allows 300, so all 250 directed copies are admitted.
    assert publisher_view["controlled_copies_included"] == 250
    assert publisher_view["controlled_copies_excess"] == 0
    assert publisher_view["total_qualified_copies"] == 1150
    assert publisher_view["breakdown_stale"] is False


def record_snapshot_on(publication_id, **overrides):
    response = api_client.create_digital_snapshot(
        publication_id, digital_snapshot_payload(**overrides), MANAGER_HEADERS
    )
    return validate_success(response, 201)


def test_digital_reach_gross_and_deduplicated_are_both_stored():
    """Both reach figures are written from identical inputs and differ by the discount.

    "With 48,000 website visitors, 12,500 unique newsletter opens and an overlap of
    15.00 percent, the deduplicated figure is 58,625 while the gross figure is
    60,500. Only the deduplicated figure is ever admissible into a circulation
    statement."

    Design: Difficulty/dual_variant_calc/digital_reach_gross_versus_deduplicated_divergence
    """
    publication = register_publication(
        name="Digital Divergence Monthly", industry_code="MANUFACTURING"
    )
    move_clock("2026-10-01T00:00:00Z")

    snapshot = record_snapshot_on(
        publication["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        website_unique_visitors=48000,
        newsletter_sends=40000,
        newsletter_unique_opens=12500,
        overlap_pct=15.00,
        source="THIRD_PARTY_CERTIFIED",
    )
    assert snapshot["combined_reach_gross"] == 60500
    assert snapshot["combined_reach_deduplicated"] == 58625
    # The gap is the discount on the newsletter side alone, not on the sum.
    assert (
        snapshot["combined_reach_gross"] - snapshot["combined_reach_deduplicated"]
        == 1875
    )
    # Neither figure is admissible into a statement before adjudication.
    assert snapshot["status"] == "RECORDED"

    statement = open_statement(
        publication["id"],
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        basis="AS_OF_PERIOD_END",
    )
    assert statement["digital_reach_verified"] == 0


def test_deduplicated_reach_discounts_the_newsletter_side_before_adding():
    """The discount lands on the opens and is rounded to a person before the addition.

    "the newsletter opens are multiplied by the complement of the overlap share —
    that is, by one hundred minus `overlap_pct`, divided by one hundred — and that
    product is rounded half up to a whole person *before*
    `website_unique_visitors` is added to it."

    Design: Difficulty/dual_variant_calc/digital_reach_gross_versus_deduplicated_divergence
    """
    publication = register_publication(
        name="Overlap Extremes Monthly", industry_code="MANUFACTURING"
    )
    move_clock("2026-10-01T00:00:00Z")

    # 10 opens at 85 percent is exactly 8.5 people, which rounds half up to 9.
    half_way = record_snapshot_on(
        publication["id"],
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
        website_unique_visitors=1000,
        newsletter_sends=500,
        newsletter_unique_opens=10,
        overlap_pct=15.00,
        source="THIRD_PARTY_CERTIFIED",
    )
    assert half_way["combined_reach_gross"] == 1010
    assert half_way["combined_reach_deduplicated"] == 1009

    # With no estimated overlap the two doctrines coincide.
    no_overlap = record_snapshot_on(
        publication["id"],
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-09-01T00:00:00Z",
        website_unique_visitors=1000,
        newsletter_sends=500,
        newsletter_unique_opens=500,
        overlap_pct=0.00,
        source="THIRD_PARTY_CERTIFIED",
    )
    assert no_overlap["combined_reach_gross"] == 1500
    assert no_overlap["combined_reach_deduplicated"] == 1500

    # With total overlap the newsletter contributes nobody new.
    total_overlap = record_snapshot_on(
        publication["id"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-10-01T00:00:00Z",
        website_unique_visitors=1000,
        newsletter_sends=500,
        newsletter_unique_opens=400,
        overlap_pct=100.00,
        source="INTERNAL_ANALYTICS",
    )
    assert total_overlap["combined_reach_gross"] == 1400
    assert total_overlap["combined_reach_deduplicated"] == 1000
