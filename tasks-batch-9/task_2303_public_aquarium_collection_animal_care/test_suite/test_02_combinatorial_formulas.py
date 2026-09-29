"""Multi-term formulas: the water-quality index (§3.1), the readiness score
(§3.9) and the quarantine protocol length (§3.6).

Each of the three combines several terms in a way that a simplified
implementation gets subtly wrong: a maximum term nested over the same ratio set
that already feeds a sum, three distinct rounding steps stacked on one another,
and a six-step pipeline whose steps do not commute.
"""
from typing import Any, Dict

from test_helpers import (
    AQUARIST_HEADERS,
    Builder,
    DIRECTOR_HEADERS,
    assertions,
    make_director_headers,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ERR_SOD_VIOLATION


# --------------------------------------------------------------------------
# Bespoke helpers
# --------------------------------------------------------------------------
def _instant_seconds(value: str) -> str:
    """An ISO-8601 UTC instant reduced to whole seconds for comparison."""
    text = value.replace("Z", "")
    if "." in text:
        text = text.split(".")[0]
    return text + "Z"


def _cold_marine_plant_and_exhibit(build: Builder) -> Dict[str, Any]:
    """One COLD_MARINE plant serving one COLD_MARINE exhibit, clock at midday."""
    build.set_clock("2026-08-01T12:00:00Z")
    plant = build.create_plant(redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant)
    return {"plant": plant, "exhibit": exhibit}


def _specimen_on_exhibit_with_five_records(build: Builder) -> Dict[str, Any]:
    """One specimen `ON_EXHIBIT` carrying five husbandry records.

    Three `FEEDING` records fall on the three distinct calendar dates
    2026-09-11, 2026-09-12 and 2026-09-13 with appetite scores 4, 5 and 3, and
    two `BEHAVIOR` records carry `NORMAL` and `LETHARGIC` (§3.7).
    """
    world = build.specimen_on_exhibit(plant_overrides={"redundancy_test_interval_days": 90})
    specimen_id = world["specimen"]["id"]
    build.advance_to("2026-09-14T12:00:00Z")
    build.log_feeding(specimen_id, appetite_score=4, logged_at="2026-09-11T09:00:00Z", feed_grams=120.0)
    build.log_feeding(specimen_id, appetite_score=5, logged_at="2026-09-12T09:00:00Z", feed_grams=150.0)
    build.log_behavior(specimen_id, "NORMAL", logged_at="2026-09-12T15:00:00Z")
    build.log_feeding(specimen_id, appetite_score=3, logged_at="2026-09-13T09:00:00Z", feed_grams=90.0)
    build.log_behavior(specimen_id, "LETHARGIC", logged_at="2026-09-14T09:00:00Z")
    return world


def _started_audit(build: Builder) -> Dict[str, Any]:
    """The world above, inspected by an audit started at 2026-09-15T00:00:00Z."""
    world = _specimen_on_exhibit_with_five_records(build)
    build.advance_to("2026-09-15T00:00:00Z")
    audit = build.schedule_audit(scheduled_for="2026-09-15T00:00:00Z")
    world["audit"] = build.progress_audit(
        audit["id"], "START", headers=make_director_headers("dir-audit-opener")
    )
    return world


def _wild_collection_specimen(
    build: Builder,
    species_overrides: Dict[str, Any],
    institution_overrides: Dict[str, Any],
) -> Dict[str, Any]:
    """Accession one animal taken from the wild through a named source institution.

    The species is `UNLISTED`, so the `IMPORT` permit that §3.5 demands of a
    `WILD_COLLECTION` request needs only the base document set.
    """
    world = build.approved_line(
        plant_overrides={"redundancy_test_interval_days": 90},
        species_overrides=species_overrides,
        entry_overrides={"planned_count": 1, "sustainability_requirement": "GREEN_ONLY"},
    )
    institution = build.create_institution(**institution_overrides)
    world = build.cleared_acquisition(
        world=world,
        source_type="WILD_COLLECTION",
        requested_count=1,
        acquisition_overrides={"source_institution_id": institution["id"]},
    )
    world["institution"] = institution
    world["specimen"] = build.accession_specimen(
        world["species"], world["request"], holding_area="QT-BAY-1"
    )
    world["quarantine_case"] = build.quarantine_case_of(world["specimen"]["id"])
    return world


def _captive_bred_specimen(build: Builder, species_overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Accession one captive-bred animal with no source institution at all."""
    world = build.approved_line(
        plant_overrides={"redundancy_test_interval_days": 90},
        species_overrides=species_overrides,
        entry_overrides={"planned_count": 1, "sustainability_requirement": "GREEN_ONLY"},
    )
    world = build.cleared_acquisition(world=world, source_type="CAPTIVE_BRED", requested_count=1)
    world["specimen"] = build.accession_specimen(
        world["species"], world["request"], holding_area="QT-BAY-1"
    )
    world["quarantine_case"] = build.quarantine_case_of(world["specimen"]["id"])
    return world


# --------------------------------------------------------------------------
# The water-quality index: a sum term and a nested maximum term
# --------------------------------------------------------------------------
def test_water_quality_index_charges_the_largest_deviation_ratio_twice(build, api):
    """Four non-zero ratios feed the sum, and the largest also feeds the max term.

    PRD §3.1: "The raw index starts at 100 and subtracts two penalties: 6.0
    multiplied by the sum of all six ratios, and 15.0 multiplied by the single
    largest of them."

    Design: Difficulty/combinatorial_formula/combinatorial_wqi_multi_parameter_nested_max_term
    """
    world = _cold_marine_plant_and_exhibit(build)

    reading = validate_success(
        api.create_water_quality_reading(
            world["plant"]["id"],
            {
                "taken_at": "2026-08-01T09:00:00Z",
                "temperature_c": 13.65,
                "salinity_ppt": 33.5,
                "ph": 8.15,
                "dissolved_oxygen_mg_l": 6.25,
                "ammonia_mg_l": 0.02,
                "nitrite_mg_l": 0.1,
            },
            AQUARIST_HEADERS,
        ),
        201,
    )

    # §3.1 COLD_MARINE targets 12.0/1.5, 33.0/1.0, 8.1/0.2, oxygen 7.0/5.5:
    #   temperature |13.65 - 12.0| / 1.5      = 1.10
    #   salinity    |33.5 - 33.0| / 1.0       = 0.50
    #   pH          |8.15 - 8.1| / 0.2        = 0.25
    #   oxygen      (7.0 - 6.25) / 1.5 * 2    = 1.00
    #   ammonia     max(0, 0.02 - 0.02) ...   = 0.00
    #   nitrite     max(0, 0.1 - 0.1) ...     = 0.00
    # sum 2.85, largest 1.10 -> 100 - (6.0 * 2.85 + 15.0 * 1.10) = 66.40.
    # Dropping the nested maximum term would answer 100 - 17.10 = 82.90.
    assertions.assert_water_quality_reading(reading)
    assert reading["water_quality_index_snapshot"] == 66.40

    # §3.1: severity is read off the largest ratio alone; 1.10 is at least 1.0
    # and below 2.0.
    assert reading["severity"] == "WARNING"

    # §3.1: every parameter whose own ratio is at least 1.0, in canonical order.
    # The oxygen ratio of exactly 1.00 is a breach, while ammonia and nitrite
    # sitting exactly on their warn limits have ratios of 0.0 and are not.
    assert reading["breach_parameters"] == ["temperature_c", "dissolved_oxygen_mg_l"]

    plant = build.get_plant(world["plant"]["id"])
    assertions.assert_alarm(plant, "WARNING", normals=0, breaches=1)
    assert plant["water_quality_index"] == 66.40

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assertions.assert_posture(exhibit, "RESTRICTED", "LSS_WARNING")


def test_water_quality_index_separates_two_readings_that_share_one_deviation_sum(build, api):
    """The same ratio sum spread over more parameters costs less, and breaches nothing.

    PRD §3.1: "The largest ratio is therefore charged twice — once inside the
    sum and once again through the maximum term — which is what makes one badly
    out-of-range parameter cost far more than six mildly imperfect ones."

    Design: Difficulty/combinatorial_formula/combinatorial_wqi_multi_parameter_nested_max_term
    """
    world = _cold_marine_plant_and_exhibit(build)

    reading = validate_success(
        api.create_water_quality_reading(
            world["plant"]["id"],
            {
                "taken_at": "2026-08-01T09:00:00Z",
                "temperature_c": 12.9,
                "salinity_ppt": 33.75,
                "ph": 8.25,
                "dissolved_oxygen_mg_l": 6.4375,
                "ammonia_mg_l": 0.02,
                "nitrite_mg_l": 0.1,
            },
            AQUARIST_HEADERS,
        ),
        201,
    )

    # §3.1 ratios: temperature 0.9 / 1.5 = 0.60; salinity 0.75 / 1.0 = 0.75;
    # pH 0.15 / 0.2 = 0.75; oxygen (7.0 - 6.4375) / 1.5 * 2 = 0.75; ammonia and
    # nitrite 0.00. The sum is 2.85 — identical to the previous reading — but
    # the largest ratio is only 0.75, so the index is
    # 100 - (6.0 * 2.85 + 15.0 * 0.75) = 100 - 28.35 = 71.65. A sum-only
    # implementation answers 82.90 for both readings and cannot tell them apart.
    assert reading["water_quality_index_snapshot"] == 71.65

    # §3.1: the largest ratio is below 1.0, so nothing has breached.
    assert reading["severity"] == "NORMAL"
    assert reading["breach_parameters"] == []

    plant = build.get_plant(world["plant"]["id"])
    assertions.assert_alarm(plant, "NORMAL", normals=1, breaches=0)
    assert plant["water_quality_index"] == 71.65

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assertions.assert_posture(exhibit, "OPEN", None)


def test_water_quality_index_adds_an_ammonia_term_one_notch_above_the_warn_limit(build, api):
    """Nudging ammonia past its warn limit enters the sum and the breach list.

    PRD §3.1: "the ratio for `ammonia_mg_l` is the greater of 0 and
    (`ammonia_mg_l` minus 0.02), divided by (0.05 minus 0.02), multiplied by 2"

    Design: Difficulty/combinatorial_formula/combinatorial_wqi_multi_parameter_nested_max_term
    """
    world = _cold_marine_plant_and_exhibit(build)

    reading = validate_success(
        api.create_water_quality_reading(
            world["plant"]["id"],
            {
                "taken_at": "2026-08-01T09:00:00Z",
                "temperature_c": 13.65,
                "salinity_ppt": 33.5,
                "ph": 8.15,
                "dissolved_oxygen_mg_l": 6.25,
                "ammonia_mg_l": 0.035,
                "nitrite_mg_l": 0.1,
            },
            AQUARIST_HEADERS,
        ),
        201,
    )

    # §3.1 ammonia (0.035 - 0.02) / (0.05 - 0.02) * 2 = 1.00, joining
    # temperature 1.10, salinity 0.50, pH 0.25 and oxygen 1.00 for a sum of
    # 3.85; the largest ratio is still temperature 1.10, so the index is
    # 100 - (6.0 * 3.85 + 15.0 * 1.10) = 100 - 39.60 = 60.40. This plant is
    # not a TOUCH_POOL, so no ammonia surcharge applies.
    assert reading["water_quality_index_snapshot"] == 60.40
    assert reading["severity"] == "WARNING"

    # §3.1: a ratio of exactly 1.0 is a breach, and the list keeps the canonical
    # parameter order regardless of which breached worst.
    assert reading["breach_parameters"] == [
        "temperature_c",
        "dissolved_oxygen_mg_l",
        "ammonia_mg_l",
    ]

    plant = build.get_plant(world["plant"]["id"])
    assert plant["water_quality_index"] == 60.40


# --------------------------------------------------------------------------
# The readiness score: subscore rounding, then weighted-sum rounding
# --------------------------------------------------------------------------
def test_readiness_score_rounds_each_domain_subscore_before_weighting_it(build, api):
    """A repeating animal-health mean is rounded before it is weighted.

    PRD §3.9: "The already-rounded subscores are weighted 0.30 for
    `LIFE_SUPPORT`, 0.25 for `ANIMAL_HEALTH`, 0.20 for `RECORDS`, 0.15 for
    `PERMITS` and 0.10 for `PUBLIC_SAFETY`, and the weighted sum is rounded half
    up to two decimals."

    Design: Difficulty/combinatorial_formula/combinatorial_readiness_nested_rounding_per_subscore_then_weighted
    """
    world = _started_audit(build)
    audit = world["audit"]

    plant = build.get_plant(world["plant"]["id"])
    # §3.1: a plant with no readings at all reports 100.00, and its redundancy
    # interval of 90 days has not lapsed by 2026-09-15.
    assert plant["water_quality_index"] == 100.00
    assert plant["redundancy_overdue"] is False
    assert plant["alarm_state"] == "NORMAL"

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    assertions.assert_posture(exhibit, "OPEN", None)

    # §3.9 subscores: one healthy plant with no readings -> LIFE_SUPPORT 100.00;
    # the single CLEARED-or-ON_EXHIBIT specimen's AUDIT_SNAPSHOT welfare of
    # 20.86 -> ANIMAL_HEALTH 20.86; that specimen has five husbandry records, so
    # RECORDS loses nothing; the acquisition request is FULFILLED rather than
    # CLEARED and needs no permit, so PERMITS loses nothing; there are no
    # sessions at all, so PUBLIC_SAFETY loses nothing.
    assertions.assert_accreditation_audit(audit)
    assert audit["domain_subscores"] == {
        "LIFE_SUPPORT": 100.00,
        "ANIMAL_HEALTH": 20.86,
        "RECORDS": 100.00,
        "PERMITS": 100.00,
        "PUBLIC_SAFETY": 100.00,
    }

    # §3.9: no plant is CRITICAL or OFFLINE, no exhibit is CLOSED and no
    # specimen awaits necropsy.
    assert audit["blocking_finding_count"] == 0

    # §3.9 weighted sum of the already-rounded subscores:
    # 0.30 * 100.00 + 0.25 * 20.86 + 0.20 * 100.00 + 0.15 * 100.00
    # + 0.10 * 100.00 = 30.00 + 5.2150 + 20.00 + 15.00 + 10.00 = 80.2150
    # -> 80.22, then a zero blocking deduction. Weighting the unrounded
    # animal-health mean 20.857142857... instead gives 80.2142857... -> 80.21,
    # which §2.7 names as the wrong answer.
    assert audit["readiness_score"] == 80.22
    assert audit["status"] == "IN_PROGRESS"
    assert audit["opened_by_user_id"] == "dir-audit-opener"
    assert _instant_seconds(audit["started_at"]) == "2026-09-15T00:00:00Z"

    stored = validate_success(api.get_accreditation_audit(audit["id"], DIRECTOR_HEADERS))
    assert stored["readiness_score"] == 80.22
    assert stored["domain_subscores"]["ANIMAL_HEALTH"] == 20.86


def test_readiness_score_survives_closure_and_determines_a_conditional_outcome(build, api):
    """Closure reads the score START stamped; it never recomputes it.

    PRD §3.9: "it becomes `CONDITIONAL` when `readiness_score` is at least 70.00
    but the pass test failed, whether because the score is below 85.00 or
    because a blocking finding exists"

    Design: Difficulty/combinatorial_formula/combinatorial_readiness_nested_rounding_per_subscore_then_weighted
    """
    world = _started_audit(build)
    audit = world["audit"]
    assert audit["readiness_score"] == 80.22

    # §3.9: CLOSE requires the acting user to differ from `opened_by_user_id`,
    # and §2.8 places that check at rank 13 — before any score comparison.
    refused = api.progress_accreditation_audit(
        audit["id"], {"action": "CLOSE"}, make_director_headers("dir-audit-opener")
    )
    validate_error(refused, ERR_SOD_VIOLATION, 409)

    held = validate_success(api.get_accreditation_audit(audit["id"], DIRECTOR_HEADERS))
    assert held["status"] == "IN_PROGRESS"
    assert held["readiness_score"] == 80.22
    assert held["closed_by_user_id"] is None

    closed = build.progress_audit(
        audit["id"],
        "CLOSE",
        headers=make_director_headers("dir-audit-closer"),
        determination_note="one animal-health record gap",
    )

    # §3.9: 80.22 is at least 70.00 but below 85.00, so the determination is
    # CONDITIONAL, and the score itself is unchanged by the closure — it is
    # stamped by START, not recomputed here.
    assert closed["status"] == "CONDITIONAL"
    assert closed["readiness_score"] == 80.22
    assert closed["domain_subscores"]["ANIMAL_HEALTH"] == 20.86
    assert closed["blocking_finding_count"] == 0
    assert closed["closed_by_user_id"] == "dir-audit-closer"
    assert closed["determination_note"] == "one animal-health record gap"
    assert _instant_seconds(closed["closed_at"]) == "2026-09-15T00:00:00Z"


# --------------------------------------------------------------------------
# Quarantine length: six ordered steps whose order is load-bearing
# --------------------------------------------------------------------------
def test_quarantine_length_keys_the_risk_tier_on_the_taxon_days_not_the_subtotal(build):
    """A subtotal of 60 with taxon days of 36 stays in the standard tier.

    PRD §3.6: "A species with a `base_quarantine_days` of 24 and `taxon_group`
    `ELASMOBRANCH`, acquired by `WILD_COLLECTION` from a `NON_ACCREDITED`
    institution, yields taxon days of 36, a surcharge of 24 and a subtotal of 60
    — but the tier is standard, because 36 is below 45, so the answer is 60 and
    not 67."

    Design: Difficulty/combinatorial_formula/combinatorial_quarantine_days_six_step_non_commutative_pipeline
    """
    world = _wild_collection_specimen(
        build,
        species_overrides={
            "taxon_group": "ELASMOBRANCH",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "base_quarantine_days": 24,
            "bioload_units_per_specimen": 30.0,
            "wild_take_quota_annual": 4,
        },
        institution_overrides={
            "accreditation_status": "NON_ACCREDITED",
            "welfare_audit_score": 60.00,
            "last_audit_at": "2026-05-01T00:00:00Z",
        },
    )
    specimen = world["specimen"]

    # §3.6 step 1 base 24; step 2 ceil(24 * 1.5) = 36; step 3 surcharge
    # 14 (WILD_COLLECTION) + 10 (NON_ACCREDITED source) = 24; step 4 subtotal
    # 60; step 5 tier standard because the step-two taxon days 36 are below 45;
    # step 6 adds nothing -> 60. Testing the tier against the subtotal would
    # add 7 and answer 67.
    assertions.assert_specimen(specimen)
    assert specimen["quarantine_required_days"] == 60

    case = world["quarantine_case"]
    assertions.assert_quarantine_case(case)
    assert case["protocol_days"] == 60
    assert case["status"] == "ACTIVE"
    assert case["extension_count"] == 0
    assert case["total_extension_days"] == 0
    assert case["clearance_exam_count"] == 0
    # §3.6: `started_at` equals the specimen's `arrival_at`, and
    # `projected_release_at` is that instant advanced by 60 days.
    assert _instant_seconds(case["started_at"]) == "2026-08-01T00:00:00Z"
    assert _instant_seconds(case["projected_release_at"]) == "2026-09-30T00:00:00Z"

    # §3.6: accession snapshots `bioload_units` from the species and leaves the
    # animal in quarantine, on no exhibit.
    assert specimen["disposition_status"] == "QUARANTINE"
    assert specimen["health_status"] == "HEALTHY"
    assert specimen["bioload_units"] == 30.00
    assert specimen["exhibit_id"] is None

    request = build.get_acquisition(world["request"]["id"])
    # §3.5 FINAL at clearance: rating GREEN 40.0 + source WILD_COLLECTION 10.0
    # + institution 0.25 * 60.00 = 15.0 + permit bonus 5.0 = 70.0, capped at
    # 100, less a protection penalty of 0.0 for UNLISTED and quota pressure
    # 20.0 * ((0 + 1) / 4) = 5.0 -> 65.00.
    assert request["sustainability_score"] == 65.00
    assert request["sustainability_score_variant"] == "FINAL"
    assert request["status"] == "FULFILLED"
    assert request["fulfilled_count"] == 1
    assert request["quota_units_reserved"] == 1

    species = build.get_species(world["species"]["id"])
    assert species["wild_take_quota_reserved"] == 1


def test_quarantine_length_promotes_the_tier_when_taxon_days_hit_forty_five_exactly(build):
    """Taxon days of exactly 45 promote the tier even though the subtotal is 59.

    PRD §3.6: "A species with a `base_quarantine_days` of 30, also
    `ELASMOBRANCH`, acquired by `WILD_COLLECTION` from an `ACCREDITED`
    institution, yields taxon days of 45, a surcharge of 14 and a subtotal of
    59; here the tier is high, because 45 meets the threshold exactly, so the
    answer is 66."

    Design: Difficulty/combinatorial_formula/combinatorial_quarantine_days_six_step_non_commutative_pipeline
    """
    world = _wild_collection_specimen(
        build,
        species_overrides={
            "taxon_group": "ELASMOBRANCH",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "base_quarantine_days": 30,
            "bioload_units_per_specimen": 30.0,
            "wild_take_quota_annual": 4,
        },
        institution_overrides={
            "accreditation_status": "ACCREDITED",
            "welfare_audit_score": 90.00,
            "last_audit_at": "2026-05-01T00:00:00Z",
        },
    )

    # §3.6 step 2 ceil(30 * 1.5) = 45; step 3 surcharge 14 + 0 (an ACCREDITED
    # source adds nothing) = 14; step 4 subtotal 59; step 5 tier high because
    # the taxon days meet 45 exactly; step 6 adds 7 -> 66. The answer therefore
    # exceeds the 60 days of the base-24 animal even though this subtotal is
    # smaller.
    assert world["specimen"]["quarantine_required_days"] == 66

    case = world["quarantine_case"]
    assert case["protocol_days"] == 66
    assert _instant_seconds(case["started_at"]) == "2026-08-01T00:00:00Z"
    assert _instant_seconds(case["projected_release_at"]) == "2026-10-06T00:00:00Z"


def test_quarantine_length_leaves_a_teleost_in_the_standard_tier_despite_two_surcharges(build):
    """Two surcharges lift the subtotal past 45 without promoting the tier.

    PRD §3.6: "And a `TELEOST` with a `base_quarantine_days` of 30 acquired by
    `WILD_COLLECTION` from a `PROVISIONAL` institution yields taxon days of 30
    and a surcharge of 19, for 49 days."

    Design: Difficulty/combinatorial_formula/combinatorial_quarantine_days_six_step_non_commutative_pipeline
    """
    world = _wild_collection_specimen(
        build,
        species_overrides={
            "taxon_group": "TELEOST",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "base_quarantine_days": 30,
            "bioload_units_per_specimen": 10.0,
            "wild_take_quota_annual": 4,
        },
        institution_overrides={
            "accreditation_status": "PROVISIONAL",
            "welfare_audit_score": 90.00,
            "last_audit_at": "2026-05-01T00:00:00Z",
        },
    )

    # §3.6 step 2 ceil(30 * 1.0) = 30; step 3 surcharge 14 + 5 (a PROVISIONAL
    # source) = 19; step 4 subtotal 49; step 5 tier standard because 30 is below
    # 45 -> 49. A pipeline keyed on the subtotal would see 49 and answer 56.
    assert world["specimen"]["quarantine_required_days"] == 49

    case = world["quarantine_case"]
    assert case["protocol_days"] == 49
    assert _instant_seconds(case["projected_release_at"]) == "2026-09-19T00:00:00Z"


def test_quarantine_length_rounds_the_taxon_product_up_to_a_whole_day(build):
    """A fractional taxon product is rounded up before anything else happens.

    PRD §3.6: "Step two multiplies the base by the taxon multiplier ... and
    rounds the product **up** to a whole number of days; this is the only
    rounding in the calculation."

    Design: Difficulty/combinatorial_formula/combinatorial_quarantine_days_six_step_non_commutative_pipeline
    """
    world = _captive_bred_specimen(
        build,
        species_overrides={
            "taxon_group": "REPTILE",
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "base_quarantine_days": 25,
            "bioload_units_per_specimen": 10.0,
        },
    )

    # §3.6 step 2 25 * 1.25 = 31.25, rounded up to 32; step 3 surcharge 0
    # because the source is CAPTIVE_BRED with no source institution at all;
    # step 4 subtotal 32; step 5 tier standard -> 32. Truncating the product
    # instead would answer 31.
    assert world["specimen"]["quarantine_required_days"] == 32

    case = world["quarantine_case"]
    assert case["protocol_days"] == 32
    assert _instant_seconds(case["started_at"]) == "2026-08-01T00:00:00Z"
    assert _instant_seconds(case["projected_release_at"]) == "2026-09-02T00:00:00Z"
