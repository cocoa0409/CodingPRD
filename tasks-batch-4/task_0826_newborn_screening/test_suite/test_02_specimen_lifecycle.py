"""Specimen collection, receipt, acceptability, and timeliness (Newborn Screening PRD)."""
from test_helpers import (
    validate_error,
    get_success_data,
    create_hospital_and_infant,
    create_specimen,
    receive_specimen,
    create_satisfactory_specimen,
    create_screen_on_satisfactory,
    set_clock,
    TEST_USERS,
)

LAB = TEST_USERS["lab_technician_headers"]


# ─── Corner: computed collection/transit hours ────────────────────────
def test_collection_and_transit_hours_computed(api):
    """PRD §2.9: "A specimen's `collection_age_hours` is the elapsed time from the infant's
    `birth_datetime` to the specimen's `collection_datetime`, expressed in hours and rounded
    half-up to two decimal places."
    PRD §2.9: "Its `transit_time_hours` is the elapsed time from `collection_datetime` to
    `received_datetime`, likewise in hours to two decimals; it is null until the specimen is
    received."

    Design: Corner/entities/specimen_collection_age_hours_computed
    """
    _facility, _infant, specimen = create_satisfactory_specimen()
    assert specimen["collection_age_hours"] == 30.0
    assert specimen["transit_time_hours"] == 18.0
    assert specimen["acceptability"] == "SATISFACTORY"


# ─── Corner: receive twice → ERR_INVALID_STATE ────────────────────────
def test_receive_twice_second_returns_409(api):
    """PRD §3.3: "Receipt is permitted only from the `COLLECTED` state and only when the
    infant's consent has not been refused (`ERR_CONSENT_REFUSED`)."
    PRD §2.10: "the target is in a state that permits the transition, else
    `ERR_INVALID_STATE` (409)."

    Design: Corner/state_machines/receive_twice_second_returns_409
    """
    _facility, _infant, specimen = create_satisfactory_specimen()
    res = api.receive_specimen(
        specimen["id"],
        {"received_datetime": "2026-03-01T08:00:00Z", "blood_spot_count": 5},
        LAB,
    )
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Difficulty: term-infant early-collection conditional branch ──────
def test_term_infant_early_collection_is_unsat_early(api):
    """PRD §3.3: "Otherwise, if the `collection_age_hours` is under 24 hours **and** the
    infant's `gestational_age_weeks` is at least 37 (a term infant), `acceptability` is
    `UNSAT_EARLY`."

    Design: Difficulty/combinatorial_formula/specimen_acceptability_term_early_conditional_branch
    """
    facility, infant = create_hospital_and_infant(gestational_age_weeks=39)
    specimen = create_specimen(
        facility, infant, collection_datetime="2026-02-27T18:00:00Z"  # 12h after birth
    )
    received = receive_specimen(
        specimen, received_datetime="2026-02-28T06:00:00Z", blood_spot_count=5
    )
    assert received["acceptability"] == "UNSAT_EARLY"
    assert received["status"] == "UNSATISFACTORY"


def test_preterm_infant_early_collection_is_exempt(api):
    """PRD §3.3: "Preterm infants — those below 37 completed weeks — are exempt from this
    early-collection rule and never fail on it."

    Design: Difficulty/combinatorial_formula/specimen_acceptability_term_early_conditional_branch
    """
    facility, infant = create_hospital_and_infant(gestational_age_weeks=33)
    specimen = create_specimen(
        facility, infant, collection_datetime="2026-02-27T18:00:00Z"  # 12h after birth
    )
    received = receive_specimen(
        specimen, received_datetime="2026-02-28T06:00:00Z", blood_spot_count=5
    )
    assert received["acceptability"] == "SATISFACTORY"
    assert received["status"] == "SATISFACTORY"


# ─── Difficulty: provisional ON_TIME vs final DELAYED on one specimen ──
def test_provisional_timeliness_on_time_at_receipt(api):
    """PRD §3.9: "The provisional timeliness on a specimen, recorded as
    `timeliness_provisional` and computed at receipt, classifies it `ON_TIME` when its
    `collection_age_hours` is at least 24 and at most 48 and its `transit_time_hours` is at
    most 24, and `LATE` otherwise."

    Design: Difficulty/dual_variant_calc/specimen_timeliness_provisional_ontime_vs_final_delayed
    """
    _facility, _infant, specimen = create_satisfactory_specimen()
    # collection age 30h in [24,48], transit 18h <= 24 → ON_TIME
    assert specimen["timeliness_provisional"] == "ON_TIME"


def test_final_timeliness_delayed_disagrees_with_provisional(api):
    """PRD §3.9: "The final timeliness, computed at metabolic reporting, classifies the
    specimen `TIMELY` when the total birth-to-report turnaround — the elapsed hours from the
    infant's `birth_datetime` to the specimen's `reported_datetime` — is at most 120 hours
    (five days), and `DELAYED` otherwise; the two classifications can disagree for the same
    specimen."

    Design: Difficulty/dual_variant_calc/specimen_timeliness_provisional_ontime_vs_final_delayed
    """
    _facility, _infant, specimen, screen = create_screen_on_satisfactory()
    set_clock("2026-03-04T16:00:00Z")  # 130h after birth 2026-02-27T06:00:00Z
    api.report_metabolic(screen["id"], {"metabolic_result": "NORMAL"}, LAB)
    reloaded = get_success_data(api.get_specimen(specimen["id"], LAB))
    assert reloaded["timeliness_provisional"] == "ON_TIME"
    assert reloaded["timeliness_final"] == "DELAYED"
    assert reloaded["status"] == "TESTED"


# ─── Difficulty: unsatisfactory receipt spawns recollection + bumps counter ──
def test_unsatisfactory_receipt_marks_specimen_unsatisfactory(api):
    """PRD §3.3: "If `blood_spot_count` is fewer than 4 spots, `acceptability` is
    `UNSAT_QUANTITY`."
    PRD §3.3: "When the outcome is anything other than satisfactory, the specimen
    auto-transitions from `RECEIVED` to `UNSATISFACTORY`, which is a terminal state, and the
    recollection cascade fires: a `RecollectionOrder` is created in `ORDERED` state..."

    Design: Difficulty/transitive_cascade/unsatisfactory_receipt_spawns_recollection_bumps_infant_counter
    """
    facility, infant = create_hospital_and_infant()
    specimen = create_specimen(facility, infant)
    received = receive_specimen(specimen, blood_spot_count=2)
    assert received["acceptability"] == "UNSAT_QUANTITY"
    assert received["status"] == "UNSATISFACTORY"


def test_unsatisfactory_receipt_increments_open_recollection_count(api):
    """PRD §3.3: "and that order's creation increments the infant's `open_recollection_count`
    by one."
    PRD §2.7: "An infant's `open_recollection_count` is the number of that infant's
    recollection orders currently in `ORDERED` state."

    Design: Difficulty/transitive_cascade/unsatisfactory_receipt_spawns_recollection_bumps_infant_counter
    """
    facility, infant = create_hospital_and_infant()
    specimen = create_specimen(facility, infant)
    receive_specimen(specimen, blood_spot_count=2)
    reloaded_infant = get_success_data(api.get_infant(infant["id"], LAB))
    assert reloaded_infant["open_recollection_count"] == 1
    orders = get_success_data(api.list_recollection_orders(specimen["id"], LAB))
    assert len(orders) == 1
    assert orders[0]["status"] == "ORDERED"
    assert orders[0]["reason"] == "UNSAT_QUANTITY"
