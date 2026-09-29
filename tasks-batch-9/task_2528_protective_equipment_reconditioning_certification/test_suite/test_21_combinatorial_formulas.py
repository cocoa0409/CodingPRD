"""Multi-factor formulas whose step order is part of the specification.

The severity index caps each weighted site term before summation, and the
settlement figure picks its discount tier from the gross before charging the
compliance surcharge on the net.
"""
from test_helpers import (
    CONDEMN_IMPACTS,
    read_account,
    read_shipment,
    setup_accepted_shipment,
    setup_tested_units,
)


def _date_of(timestamp: str) -> str:
    """The UTC calendar date part of an ISO 8601 instant."""
    return timestamp[:10]


def test_each_site_term_is_capped_before_the_three_terms_are_summed():
    """Readings of 400, 600 and 900 g weight to 200.0, 180.0 and 180.0, but every
    term is pulled back to 150.0 first, so the index is 450.0 and not 560.0.

    PRD §3.5: "readings of 400, 600 and 900 g would give uncapped contributions
    of 200.0, 180.0 and 180.0 for a total of 560.0, but the per-site cap pulls
    each to 150.0 for a capped total of 450.0 — still a `CONDEMN`, but at a very
    different number."

    Design: Difficulty/combinatorial_formula/severity_index_per_site_cap_applied_before_summation
    """
    ctx = setup_tested_units(unit_count=1, impacts=CONDEMN_IMPACTS)

    session = ctx["shell_test"]
    assert session["peak_g_front"] == 400
    assert session["peak_g_side"] == 600
    assert session["peak_g_crown"] == 900
    assert session["severity_index"] == 450.0
    assert session["computed_result"] == "CONDEMN"
    assert session["status"] == "COMPLETED"

    unit = ctx["unit"]
    assert unit["current_si"] == 450.0
    assert unit["recon_status"] == "TESTED"


def test_a_single_catastrophic_site_reading_cannot_dominate_the_index():
    """A 400 g front reading weights to 200.0 and is capped to 150.0, so with
    quiet side and crown sites the index is 200.0 rather than 250.0.

    PRD §3.5: "The front site contributes its peak-g reading multiplied by 0.5,
    the side site its reading multiplied by 0.3, and the crown site its reading
    multiplied by 0.2; each of the three contributions is then individually
    capped at 150.0, so a single catastrophic reading cannot dominate the whole
    index."

    Design: Difficulty/combinatorial_formula/severity_index_per_site_cap_applied_before_summation
    """
    ctx = setup_tested_units(unit_count=1, impacts=(400, 100, 100))

    session = ctx["shell_test"]
    assert session["severity_index"] == 200.0
    assert session["computed_result"] == "PASS"
    assert ctx["unit"]["current_si"] == 200.0


def test_discount_tier_comes_from_the_gross_and_the_surcharge_from_the_net():
    """Two STANDARD units gross 17,992 cents, which sits in the 0.125 band, and
    the 2 percent surcharge is charged on the discounted net of 15,743.

    PRD §3.9: "the discount rate is 0.000 when the gross is below 10,000 cents
    (100 dollars), 0.125 when the gross is below 100,000 cents (1,000 dollars),
    and 0.150 otherwise; the discount amount is the gross multiplied by that
    rate, rounded half up to whole cents; the net is the gross minus the
    discount; a compliance surcharge of 2 percent of the net is computed and
    rounded half up to whole cents; and the total is the net plus that
    surcharge."

    Design: Difficulty/combinatorial_formula/settlement_tier_selected_from_gross_then_surcharge_on_net
    """
    ctx = setup_accepted_shipment(unit_count=2, service_tier="STANDARD")

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["status"] == "ACCEPTED"
    assert shipment["provisional_total_cents"] == 16058
    assert shipment["final_total_cents"] is None
    assert shipment["units_in_process"] == 2
    assert _date_of(shipment["raw_due_at"]) == "2026-09-01"
    assert _date_of(shipment["committed_due_at"]) == "2026-08-18"
    assert shipment["loaner_required"] is True

    account = read_account(ctx["account"]["id"])
    assert account["open_shipment_count"] == 1
    assert account["loaner_recall_due_at"] is None


def test_a_gross_below_the_first_floor_takes_the_zero_discount_rate():
    """A single STANDARD unit grosses 8,996 cents, below the 10,000-cent floor,
    so no discount is taken and the surcharge is 2 percent of the full gross.

    PRD §3.9: "the discount rate is 0.000 when the gross is below 10,000 cents
    (100 dollars), 0.125 when the gross is below 100,000 cents (1,000 dollars),
    and 0.150 otherwise; the discount amount is the gross multiplied by that
    rate, rounded half up to whole cents; the net is the gross minus the
    discount; a compliance surcharge of 2 percent of the net is computed and
    rounded half up to whole cents; and the total is the net plus that
    surcharge."

    Design: Difficulty/combinatorial_formula/settlement_tier_selected_from_gross_then_surcharge_on_net
    """
    ctx = setup_accepted_shipment(unit_count=1, service_tier="STANDARD")

    shipment = read_shipment(ctx["shipment"]["id"])
    assert shipment["counted_unit_count"] == 1
    assert shipment["provisional_total_cents"] == 9176
