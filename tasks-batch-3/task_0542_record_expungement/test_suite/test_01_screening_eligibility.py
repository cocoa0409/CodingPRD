"""Eligibility screening: base-date selection and the inclusive waiting-period boundary."""
from test_helpers import fixtures, validate_success
from test_helpers.constants import CLOCK_START


def test_convicted_record_waiting_period_measured_from_sentence_date(api):
    """PRD §3.2: "for a `CONVICTED` disposition the base date is the
    `sentence_completion_date`; for a `DISMISSED`, `ARREST_ONLY`, or `ACQUITTED`
    disposition — where no sentence exists — the base date is the `disposition_date`."
    PRD §3.2: "The record's `eligible_on` — the earliest date the record may be
    expunged — is that base date advanced by a whole number of calendar years
    determined by the offense class: 1 year for an `INFRACTION`, 2 years for a
    `MISDEMEANOR`, 3 years for a `FELONY_CLASS_C`, 5 years for a `FELONY_CLASS_B`,
    and 7 years for a `FELONY_CLASS_A`."

    Design: Difficulty/dual_variant_calc/record_eligibility_sentence_vs_disposition
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(
        api, p["id"], offense_class="MISDEMEANOR", disposition="CONVICTED",
        disposition_date="2023-01-01T00:00:00Z",
        sentence_completion_date="2024-05-01T00:00:00Z")
    data = validate_success(api.screen_criminal_record(r["id"], fixtures.CLERK))
    # sentence 2024-05-01 + 2 years -> 2026-05-01 (NOT disposition_date 2023-01-01 -> 2025-01-01)
    assert data["eligible_on"][:10] == "2026-05-01", (
        f"eligible_on must be sentence-based 2026-05-01, got {data['eligible_on']}")
    assert data["status"] == "ELIGIBLE"


def test_non_convicted_record_waiting_period_measured_from_disposition_date(api):
    """PRD §3.2: "for a `CONVICTED` disposition the base date is the
    `sentence_completion_date`; for a `DISMISSED`, `ARREST_ONLY`, or `ACQUITTED`
    disposition — where no sentence exists — the base date is the `disposition_date`."
    PRD §3.2: "The record's `eligible_on` — the earliest date the record may be
    expunged — is that base date advanced by a whole number of calendar years
    determined by the offense class: 1 year for an `INFRACTION`, 2 years for a
    `MISDEMEANOR`, 3 years for a `FELONY_CLASS_C`, 5 years for a `FELONY_CLASS_B`,
    and 7 years for a `FELONY_CLASS_A`."

    Design: Difficulty/dual_variant_calc/record_eligibility_sentence_vs_disposition
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(
        api, p["id"], offense_class="MISDEMEANOR", disposition="DISMISSED",
        disposition_date="2023-01-01T00:00:00Z")
    data = validate_success(api.screen_criminal_record(r["id"], fixtures.CLERK))
    # disposition 2023-01-01 + 2 years -> 2025-01-01 (disposition-based, no sentence exists)
    assert data["eligible_on"][:10] == "2025-01-01", (
        f"eligible_on must be disposition-based 2025-01-01, got {data['eligible_on']}")
    assert data["status"] == "ELIGIBLE"


def test_record_eligible_on_exact_clock_is_eligible_inclusive(api):
    """PRD §3.2: "if the current time is at or after `eligible_on` (the boundary is
    inclusive — the exact `eligible_on` instant already qualifies), the record
    becomes `ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/waiting_period_exact_date_eligible
    """
    fixtures.set_clock(api, CLOCK_START)  # 2026-05-01
    p = fixtures.create_petitioner(api)
    # MISDEMEANOR/CONVICTED sentence 2024-05-01 + 2y -> eligible_on 2026-05-01 == clock
    r = fixtures.create_record(
        api, p["id"], offense_class="MISDEMEANOR", disposition="CONVICTED",
        disposition_date="2023-01-01T00:00:00Z",
        sentence_completion_date="2024-05-01T00:00:00Z")
    data = validate_success(api.screen_criminal_record(r["id"], fixtures.CLERK))
    assert data["status"] == "ELIGIBLE", (
        "clock == eligible_on (2026-05-01) must qualify inclusively")


def test_record_eligible_on_day_after_clock_is_ineligible_waiting_period(api):
    """PRD §3.2: "If the current time is strictly before `eligible_on`, the record
    becomes `INELIGIBLE` with `ineligible_reason` set to `WAITING_PERIOD`, and
    `eligible_on` is retained so the record can be re-screened later."

    Design: Difficulty/boundary_precision_check/waiting_period_exact_date_eligible
    """
    fixtures.set_clock(api, CLOCK_START)  # 2026-05-01
    p = fixtures.create_petitioner(api)
    # sentence 2024-05-02 + 2y -> eligible_on 2026-05-02, strictly after the clock
    r = fixtures.create_record(
        api, p["id"], offense_class="MISDEMEANOR", disposition="CONVICTED",
        disposition_date="2023-01-01T00:00:00Z",
        sentence_completion_date="2024-05-02T00:00:00Z")
    data = validate_success(api.screen_criminal_record(r["id"], fixtures.CLERK))
    assert data["status"] == "INELIGIBLE"
    assert data["ineligible_reason"] == "WAITING_PERIOD"
