"""Two-variant computations whose variants diverge on identical stored data.

Service age is computed under two mutually exclusive ageing bases, and the
settlement total is computed under two rounding orders. Both pairs are
deliberately observable: the same rows produce different answers.
"""
from test_helpers import (
    identify_unit,
    read_account,
    read_shipment,
    setup_accepted_shipment,
    setup_settled_shipment,
)

MANUFACTURE_SEPTEMBER_2016 = "2016-09-15T00:00:00Z"


def _date_of(timestamp: str) -> str:
    """The UTC calendar date part of an ISO 8601 instant."""
    return timestamp[:10]


def test_manufacture_date_basis_yields_nine_whole_years_and_leaves_life_expired_false():
    """A shell made 15 September 2016 read on 1 August 2026 has completed nine
    whole 365-day service years, which is below a ten-year service ceiling.

    PRD §3.4: "Under the `MANUFACTURE_DATE` basis, `service_age_years` is the
    whole number of elapsed days between the manufacture date and the current
    date on the logical clock, divided by 365 days per service year and rounded
    down to a whole number."

    Design: Difficulty/dual_variant_calc/unit_service_age_manufacture_vs_season_basis_diverge
    """
    ctx = setup_accepted_shipment(
        unit_count=1, model_overrides={"max_service_life_years": 10}
    )

    unit = identify_unit(
        ctx["unit"]["id"],
        ctx["model"]["id"],
        manufacture_date=MANUFACTURE_SEPTEMBER_2016,
        age_basis="MANUFACTURE_DATE",
    )

    assert unit["age_basis"] == "MANUFACTURE_DATE"
    assert unit["service_age_years"] == 9
    assert unit["life_expired"] is False
    assert unit["warranty_coverage"] == "OUT_OF_WARRANTY"
    assert unit["condemn_required"] is False
    assert unit["recon_status"] == "IDENTIFIED"


def test_first_season_basis_yields_ten_seasons_and_sets_life_expired_true():
    """The same stored manufacture date counted in competition seasons is ten,
    which reaches the ten-year ceiling and expires the shell.

    PRD §3.4: "Under the `FIRST_SEASON` basis, `service_age_years` is instead
    the calendar year of the logical clock minus the calendar year of the
    manufacture date, because season-anchored ageing counts competition seasons
    rather than elapsed days: a shell manufactured in September 2016 has been
    through ten seasons by August 2026 even though only nine full years have
    passed."

    Design: Difficulty/dual_variant_calc/unit_service_age_manufacture_vs_season_basis_diverge
    """
    ctx = setup_accepted_shipment(
        unit_count=1, model_overrides={"max_service_life_years": 10}
    )

    unit = identify_unit(
        ctx["unit"]["id"],
        ctx["model"]["id"],
        manufacture_date=MANUFACTURE_SEPTEMBER_2016,
        age_basis="FIRST_SEASON",
    )

    assert unit["age_basis"] == "FIRST_SEASON"
    assert unit["service_age_years"] == 10
    assert unit["life_expired"] is True
    assert unit["warranty_coverage"] == "OUT_OF_WARRANTY"
    assert unit["condemn_required"] is True
    assert unit["recon_status"] == "IDENTIFIED"


def test_the_two_ageing_bases_disagree_on_identical_stored_data():
    """Two units of the same model bearing the same manufacture date, separated
    only by the frozen ageing basis, reach opposite life-expiry verdicts.

    PRD §3.4: "Consider a unit whose stored `manufacture_date` is 15 September
    2016 read against a clock of 1 August 2026, on a model whose
    `max_service_life_years` is 10: the `MANUFACTURE_DATE` basis yields nine
    whole years and leaves `life_expired` false, while the `FIRST_SEASON` basis
    yields ten and sets it true."

    Design: Difficulty/dual_variant_calc/unit_service_age_manufacture_vs_season_basis_diverge
    """
    ctx = setup_accepted_shipment(
        unit_count=2, model_overrides={"max_service_life_years": 10}
    )

    by_manufacture = identify_unit(
        ctx["units"][0]["id"],
        ctx["model"]["id"],
        manufacture_date=MANUFACTURE_SEPTEMBER_2016,
        age_basis="MANUFACTURE_DATE",
    )
    by_season = identify_unit(
        ctx["units"][1]["id"],
        ctx["model"]["id"],
        manufacture_date=MANUFACTURE_SEPTEMBER_2016,
        age_basis="FIRST_SEASON",
    )

    assert by_manufacture["manufacture_date"][:10] == by_season["manufacture_date"][:10]
    assert by_season["service_age_years"] - by_manufacture["service_age_years"] == 1
    assert by_manufacture["life_expired"] is False
    assert by_season["life_expired"] is True


def test_provisional_settlement_sums_the_exact_lines_and_rounds_once_at_the_end():
    """A two-unit PRIORITY_RUSH shipment priced at acceptance sums two exact
    12,144.60-cent lines and rounds the aggregate a single time.

    PRD §3.9: "The `PROVISIONAL` variant runs at acceptance and writes
    `provisional_total_cents`; it sums the exact line amounts across the set and
    rounds *once*, half up, at the end."

    Design: Difficulty/dual_variant_calc/shipment_settlement_provisional_vs_final_rounding_order_diverge
    """
    ctx = setup_accepted_shipment(unit_count=2, service_tier="PRIORITY_RUSH")

    shipment = read_shipment(ctx["shipment"]["id"])

    assert shipment["status"] == "ACCEPTED"
    assert shipment["counted_unit_count"] == 2
    assert shipment["provisional_total_cents"] == 21678
    assert shipment["final_total_cents"] is None
    assert shipment["settlement_locked"] is False
    assert _date_of(shipment["raw_due_at"]) == "2026-08-12"
    assert _date_of(shipment["committed_due_at"]) == "2026-08-12"
    assert shipment["loaner_required"] is False


def test_final_settlement_rounds_each_line_first_and_diverges_by_one_cent():
    """The same two units priced at settlement round line by line, so the final
    total lands one cent above the provisional total and the shipment closes.

    PRD §3.9: "The `FINAL` variant runs at settlement and writes
    `final_total_cents`; it rounds *each* line's exact amount half up to whole
    cents first and then sums the rounded lines, and it operates on the real
    billable set, so it also picks up the condemned-handling charge and the
    closed-repair labour."

    Design: Difficulty/dual_variant_calc/shipment_settlement_provisional_vs_final_rounding_order_diverge
    """
    ctx = setup_settled_shipment(unit_count=2, service_tier="PRIORITY_RUSH")

    shipment = ctx["shipment"]

    assert shipment["provisional_total_cents"] == 21678
    assert shipment["final_total_cents"] == 21679
    assert shipment["final_total_cents"] - shipment["provisional_total_cents"] == 1
    assert shipment["settlement_locked"] is True
    assert shipment["status"] == "CLOSED"
    assert read_account(ctx["account"]["id"])["open_shipment_count"] == 0
