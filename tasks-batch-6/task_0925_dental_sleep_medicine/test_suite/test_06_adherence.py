"""The two adherence denominators, the compliance edge and the summary read."""

from test_helpers import (
    approx_rate,
    assert_adherence_download,
    build_scenario,
    create_adherence_download_payload,
    record_adherence,
    validate_paginated,
    validate_success,
)


def test_payer_denominator_counts_every_night_of_the_window(api):
    """PRD §3.7: "`rate_of_window` divides `nights_at_or_above_min_hours` by the full 30-night
    window, rounded half up to 4 decimal places: this is the payer's figure, and nights on which
    the device was never worn at all count against the patient."
    PRD §3.7: "`compliant` is derived from `rate_of_window` and **never** from `rate_of_recorded`:
    it is true exactly when `rate_of_window` is at least 0.70."

    Design: Difficulty/dual_variant_calc/adherence_window_denominator_vs_recorded_denominator
    """
    scenario = build_scenario("fabricated")
    download = record_adherence(
        scenario,
        window_start="2026-07-08",
        window_end="2026-08-06",
        nights_recorded=24,
        nights_at_or_above_min_hours=20,
        mean_hours_per_worn_night=5.2,
    )
    assert_adherence_download(download)
    assert download["rate_of_window"] == approx_rate(0.6667)
    assert download["compliant"] is False


def test_clinic_denominator_diverges_from_the_payer_figure_on_one_row(api):
    """PRD §3.7: "`rate_of_recorded` divides the same numerator by `nights_recorded`, rounded
    half up to 4 decimal places: this is the clinic's figure, reported back to the patient as a
    measure of wear quality on the nights he did wear it, and it is null when `nights_recorded`
    is 0."
    PRD §3.7: "Consider 20 qualifying nights out of 24 recorded: the payer's figure is 20 divided
    by 30, which is **0.6667**, while the clinic's is 20 divided by 24, which is **0.8333**."

    Design: Difficulty/dual_variant_calc/adherence_window_denominator_vs_recorded_denominator
    """
    scenario = build_scenario("fabricated")
    download = record_adherence(
        scenario,
        window_start="2026-07-08",
        window_end="2026-08-06",
        nights_recorded=24,
        nights_at_or_above_min_hours=20,
        mean_hours_per_worn_night=5.2,
    )
    assert download["rate_of_recorded"] == approx_rate(0.8333)
    assert download["rate_of_window"] == approx_rate(0.6667)
    assert download["rate_of_recorded"] > download["rate_of_window"], (
        "the clinic denominator flatters the same numerator"
    )
    assert download["compliant"] is False


def test_adherence_is_compliant_at_exactly_seventy_percent(api):
    """PRD §3.7: "`compliant` is derived from `rate_of_window` and **never** from
    `rate_of_recorded`: it is true exactly when `rate_of_window` is at least 0.70."
    PRD §3.7: "The two agree only when `nights_recorded` equals 30 — 21 qualifying nights out of
    30 recorded gives **0.7000** on both."

    Design: Difficulty/boundary_precision_check/adherence_compliance_at_exact_seventy_percent
    """
    scenario = build_scenario("fabricated")
    download = record_adherence(
        scenario,
        window_start="2026-07-08",
        window_end="2026-08-06",
        nights_recorded=30,
        nights_at_or_above_min_hours=21,
        mean_hours_per_worn_night=6.1,
    )
    assert download["rate_of_window"] == approx_rate(0.7000)
    assert download["compliant"] is True
    assert download["rate_of_recorded"] == approx_rate(0.7000)


def test_adherence_is_not_compliant_one_night_below_the_edge(api):
    """PRD §3.7: "`compliant` is derived from `rate_of_window` and **never** from
    `rate_of_recorded`: it is true exactly when `rate_of_window` is at least 0.70."
    PRD §3.7: "`rate_of_window` divides `nights_at_or_above_min_hours` by the full 30-night
    window, rounded half up to 4 decimal places: this is the payer's figure, and nights on which
    the device was never worn at all count against the patient."

    Design: Difficulty/boundary_precision_check/adherence_compliance_at_exact_seventy_percent
    """
    scenario = build_scenario("fabricated")
    download = record_adherence(
        scenario,
        window_start="2026-08-07",
        window_end="2026-09-05",
        nights_recorded=30,
        nights_at_or_above_min_hours=20,
        mean_hours_per_worn_night=6.0,
    )
    assert download["rate_of_window"] == approx_rate(0.6667)
    assert download["compliant"] is False


def test_a_second_download_for_the_same_window_creates_a_second_row(api):
    """PRD §2.4: "The single exception is `AdherenceDownload`, which is an immutable observation:
    an adherence download carries `id` and `created_at` only — it has **no** `updated_at` and
    **no** `version` field at all, and neither key appears in its serialized form."
    PRD §3.7: "A download is an immutable observation: it carries no `updated_at` and no
    `version`, and it is never edited after the fact."

    Design: Corner/entities/adherence_download_is_an_immutable_event_row
    """
    scenario = build_scenario("fabricated")
    first = record_adherence(
        scenario,
        window_start="2026-07-08",
        window_end="2026-08-06",
        nights_recorded=30,
        nights_at_or_above_min_hours=25,
        mean_hours_per_worn_night=6.4,
    )
    second = validate_success(
        api.create_adherence_download(
            create_adherence_download_payload(
                scenario["app_id"],
                window_start="2026-07-08",
                window_end="2026-08-06",
                nights_recorded=30,
                nights_at_or_above_min_hours=10,
                mean_hours_per_worn_night=2.0,
            ),
            scenario["dent_headers"],
        ),
        201,
    )
    assert second["id"] != first["id"]
    reread = validate_success(
        api.get_adherence_download(first["id"], scenario["dent_headers"])
    )
    assert_adherence_download(reread)
    assert reread["nights_at_or_above_min_hours"] == 25, "the first row is untouched"
    assert reread["compliant"] is True
    assert second["compliant"] is False
    rows, meta = validate_paginated(
        api.list_adherence_downloads(
            scenario["dent_headers"], {"appliance_id": scenario["app_id"]}
        )
    )
    assert meta["total_count"] == 2 and len(rows) == 2


def test_adherence_summary_reports_both_sources_side_by_side(api):
    """PRD §3.7: "It returns `appliance_id`, then `objective_rate_of_window`,
    `objective_rate_of_recorded` and `objective_compliant` from the newest objective download,
    then `attested_rate_of_window` and `attested_compliant` from the newest attested download,
    and finally the `window_start` and `window_end` of the newest objective download when one
    exists and of the newest attested download otherwise."
    PRD §3.7: "The `source` is `OBJECTIVE_MICRORECORDER` when the figures were pulled off the
    chip embedded in the device, or `PATIENT_ATTESTED` when the patient reported them."

    Design: Corner/calculations/attested_adherence_never_satisfies_the_payer_figure
    """
    scenario = build_scenario("fabricated")
    attested = record_adherence(
        scenario,
        headers=scenario["patient_headers"],
        source="PATIENT_ATTESTED",
        window_start="2026-07-08",
        window_end="2026-08-06",
        nights_recorded=30,
        nights_at_or_above_min_hours=29,
        mean_hours_per_worn_night=7.0,
    )
    objective = record_adherence(
        scenario,
        source="OBJECTIVE_MICRORECORDER",
        window_start="2026-07-08",
        window_end="2026-08-06",
        nights_recorded=30,
        nights_at_or_above_min_hours=18,
        mean_hours_per_worn_night=3.9,
    )
    summary = validate_success(
        api.get_adherence_summary(scenario["app_id"], scenario["dent_headers"])
    )
    assert summary["attested_rate_of_window"] == approx_rate(0.9667)
    assert summary["attested_compliant"] is True
    assert summary["objective_rate_of_window"] == approx_rate(0.6000)
    assert summary["objective_compliant"] is False
    assert attested["source"] == "PATIENT_ATTESTED"
    assert objective["compliant"] is False
