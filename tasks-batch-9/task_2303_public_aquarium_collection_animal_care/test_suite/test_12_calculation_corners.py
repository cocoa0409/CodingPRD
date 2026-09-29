"""Numeric and ordering corners of the aquarium's derived quantities.

Every figure asserted here is re-derived from the arithmetic published in the
PRD: the water-quality index and its habitat surcharge (§3.1), the bioload
ledger and the posture order (§3.2), the receiving-eligibility flag (§3.3), the
sourcing score and the permit document requirement (§3.5), the rolling welfare
index and the treatment withdrawal window (§3.7).
"""
from test_helpers import (
    AQUARIST_HEADERS,
    CLEARANCE_OFFICER_ID,
    DIRECTOR_HEADERS,
    PERMIT_OFFICER_HEADERS,
    VET_HEADERS,
    get_success_data,
    make_director_headers,
    shift,
    validate_error,
    validate_paginated,
)
from test_helpers.api_errors import (
    ERR_CLEARANCE_SCORE_TOO_LOW,
    ERR_MISSING_DOCUMENTS,
    ERR_TRANSFER_DATE_NOT_REACHED,
    ERR_TREATMENT_WITHDRAWAL_ACTIVE,
)


def instant_prefix(value):
    """The `YYYY-MM-DDTHH:MM:SS` head of a stamped instant, fractions aside."""
    assert isinstance(value, str), value
    return value[:19]


def test_plant_water_quality_index_follows_the_greatest_taken_at_not_the_insertion_order(build, api):
    """A back-dated sample moves the alarm band yet never speaks for the plant.

    PRD §3.1: "The plant-level `water_quality_index` is the `water_quality_index_snapshot` of the plant's latest reading, where "latest" means the greatest `taken_at`; ties on `taken_at` are broken by the greatest `created_at`, and any remaining tie by insertion order."

    PRD §3.1: "If the plant's latest reading has `severity` `NORMAL`, or the plant has no readings at all, it returns to `NORMAL`; if the latest reading is a `WARNING`, it returns to `WARNING`; and if the latest reading is a `CRITICAL`, it returns to `CRITICAL`."

    Design: Corner/calculations/calc_latest_reading_selector_ignores_insertion_order
    """
    build.advance_to("2026-08-03T00:00:00Z")
    plant = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    exhibit = build.create_exhibit(plant)

    # COLD_MARINE targets: temp 12.0/band 1.5, salinity 33.0/1.0, pH 8.1/0.2, oxygen warn 7.0.
    # Inserted FIRST but the newer sample: every ratio is 0 (7.4 mg/l is above the 7.0 warn
    # threshold, 0.01 is below the 0.02 ammonia pivot, 0.02 is below the 0.1 nitrite pivot).
    newer = build.append_reading(
        plant["id"],
        {
            "taken_at": "2026-08-02T00:00:00Z",
            "temperature_c": 12.0,
            "salinity_ppt": 33.0,
            "ph": 8.1,
            "dissolved_oxygen_mg_l": 7.4,
            "ammonia_mg_l": 0.01,
            "nitrite_mg_l": 0.02,
        },
    )
    # Inserted SECOND but back-dated by a day: the temperature ratio is |13.6 - 12.0| / 1.5.
    older = build.append_reading(
        plant["id"],
        {
            "taken_at": "2026-08-01T00:00:00Z",
            "temperature_c": 13.6,
            "salinity_ppt": 33.0,
            "ph": 8.1,
            "dissolved_oxygen_mg_l": 7.4,
            "ammonia_mg_l": 0.01,
            "nitrite_mg_l": 0.02,
        },
    )

    # 100 - 6.0 * 0 - 15.0 * 0 = 100.00, and NORMAL because the largest ratio is 0.0.
    assert float(newer["water_quality_index_snapshot"]) == 100.00
    assert newer["severity"] == "NORMAL"
    assert newer["breach_parameters"] == []
    # 100 - 6.0 * (1.6/1.5) - 15.0 * (1.6/1.5) = 100 - 21 * 1.0666... = 100 - 22.4 = 77.60.
    assert float(older["water_quality_index_snapshot"]) == 77.60
    # The largest ratio 1.0666... is at least 1.0 and below 2.0, so WARNING, and the only
    # parameter whose own ratio reaches 1.0 is temperature_c.
    assert older["severity"] == "WARNING"
    assert older["breach_parameters"] == ["temperature_c"]

    warned = build.get_plant(plant["id"])
    # The appended WARNING reading drives the band even though it is not the latest sample.
    assert warned["alarm_state"] == "WARNING"
    assert warned["consecutive_breach_readings"] == 1
    assert warned["consecutive_normal_readings"] == 0
    # The selector picks the greatest taken_at (2026-08-02), whose snapshot is 100.00 — not
    # the later-inserted 2026-08-01 snapshot of 77.60.
    assert float(warned["water_quality_index"]) == 100.00

    build.record_redundancy_test(plant["id"], "FAIL", "2026-08-03T00:00:00Z")
    offline = build.get_plant(plant["id"])
    assert offline["alarm_state"] == "OFFLINE"
    closed_exhibit = build.get_exhibit(exhibit["id"])
    assert closed_exhibit["posture"] == "CLOSED"
    assert closed_exhibit["last_posture_reason"] == "LSS_OFFLINE"

    build.record_redundancy_test(plant["id"], "PASS", "2026-08-03T00:00:00Z")
    recovered = build.get_plant(plant["id"])
    # The recovery fork reads the plant's latest reading, i.e. the greatest taken_at, which is
    # the NORMAL 2026-08-02 sample — so the band lands on NORMAL, not on WARNING.
    assert recovered["alarm_state"] == "NORMAL"
    assert instant_prefix(recovered["last_redundancy_test_at"]) == "2026-08-03T00:00:00"
    assert recovered["redundancy_overdue"] is False
    reopened = build.get_exhibit(exhibit["id"])
    # No plant driver, no overdue interval and no bioload at all, so none of the five posture
    # conditions matches and the exhibit is OPEN with a null reason.
    assert reopened["posture"] == "OPEN"
    assert reopened["last_posture_reason"] is None


def test_touch_pool_ammonia_surcharge_costs_five_index_points_a_cold_marine_plant_never_pays(build, api):
    """The contact surcharge is the only habitat-specific term in the index.

    PRD §3.1: "A `TOUCH_POOL` plant, where guests put their hands in the water, carries one further deduction: 10.0 multiplied by the greater of 0 and (the ammonia ratio minus 0.5)."

    Design: Corner/calculations/calc_touch_pool_contact_surcharge_is_the_only_habitat_specific_term
    """
    cold = build.create_plant(design_habitat="COLD_MARINE", redundancy_test_interval_days=90)
    touch = build.create_plant(design_habitat="TOUCH_POOL", redundancy_test_interval_days=90)

    # Ammonia 0.035 gives max(0, 0.035 - 0.02) / (0.05 - 0.02) * 2 = 0.015 / 0.03 * 2 = 1.0 on
    # both plants; every other parameter sits on its own habitat target or inside its
    # one-sided threshold, so every other ratio is 0.
    cold_reading = build.append_reading(
        cold["id"],
        {
            "taken_at": build.now,
            "temperature_c": 12.0,
            "salinity_ppt": 33.0,
            "ph": 8.1,
            "dissolved_oxygen_mg_l": 7.4,
            "ammonia_mg_l": 0.035,
            "nitrite_mg_l": 0.02,
        },
    )
    touch_reading = build.append_reading(
        touch["id"],
        {
            "taken_at": build.now,
            "temperature_c": 14.0,
            "salinity_ppt": 33.0,
            "ph": 8.1,
            "dissolved_oxygen_mg_l": 7.8,
            "ammonia_mg_l": 0.035,
            "nitrite_mg_l": 0.02,
        },
    )

    # 100 - 6.0 * 1.0 (the sum of the six ratios) - 15.0 * 1.0 (the largest) = 79.00.
    assert float(cold_reading["water_quality_index_snapshot"]) == 79.00
    # That same 79.00 less 10.0 * max(0, 1.0 - 0.5) = 5.00 of guest-contact surcharge = 74.00.
    assert float(touch_reading["water_quality_index_snapshot"]) == 74.00
    # The surcharge moves the index only: severity is read off the largest ratio alone.
    assert cold_reading["severity"] == "WARNING"
    assert touch_reading["severity"] == "WARNING"
    assert cold_reading["breach_parameters"] == ["ammonia_mg_l"]
    assert touch_reading["breach_parameters"] == ["ammonia_mg_l"]

    cold_plant = build.get_plant(cold["id"])
    touch_plant = build.get_plant(touch["id"])
    assert float(cold_plant["water_quality_index"]) == 79.00
    assert float(touch_plant["water_quality_index"]) == 74.00
    assert cold_plant["alarm_state"] == "WARNING"
    assert touch_plant["alarm_state"] == "WARNING"
    assert cold_plant["consecutive_breach_readings"] == 1
    assert touch_plant["consecutive_breach_readings"] == 1


def test_welfare_rolling_score_rises_when_the_oldest_feeding_leaves_the_five_log_window(build, api):
    """The sixth append pushes the worst feeding out of the rolling window.

    PRD §3.7: "The `ROLLING` variant, recomputed on every husbandry append and on every veterinary case opening and closure, takes as its window the 5 most recent records whose `log_type` is `FEEDING` or `BEHAVIOR`, ordered by `logged_at` descending and then by `created_at` descending."

    Design: Corner/calculations/calc_welfare_rolling_window_drops_the_sixth_oldest_log
    """
    world = build.quarantined_specimen(
        species_overrides={"bioload_units_per_specimen": 12.0, "wild_take_quota_annual": 4},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    specimen = world["specimen"]
    build.advance_to("2026-09-14T12:00:00Z")

    build.log_feeding(specimen["id"], appetite_score=1, logged_at="2026-09-10T09:00:00Z", feed_grams=30.0)
    build.log_feeding(specimen["id"], appetite_score=4, logged_at="2026-09-11T09:00:00Z", feed_grams=120.0)
    build.log_feeding(specimen["id"], appetite_score=5, logged_at="2026-09-12T09:00:00Z", feed_grams=150.0)
    build.log_behavior(specimen["id"], behavior_code="NORMAL", logged_at="2026-09-12T15:00:00Z")
    build.log_feeding(specimen["id"], appetite_score=3, logged_at="2026-09-13T09:00:00Z", feed_grams=90.0)

    before = build.get_specimen(specimen["id"])
    # The window holds all five records: base 40.0 + mean(1, 4, 5, 3) * 8.0 = 3.25 * 8 = 26.00
    # + the behaviour mean of NORMAL = 10.00, with no OPEN TREATMENT case to charge = 76.00.
    assert float(before["welfare_score"]) == 76.00
    assert before["welfare_score_variant"] == "ROLLING"

    build.log_behavior(specimen["id"], behavior_code="LETHARGIC", logged_at="2026-09-14T09:00:00Z")

    after = build.get_specimen(specimen["id"])
    # The 2026-09-10 appetite-1 record is now the sixth most recent and leaves the window:
    # 40.0 + mean(4, 5, 3) * 8.0 = 4.0 * 8 = 32.00 + mean(LETHARGIC 4.0, NORMAL 10.0) = 7.00,
    # giving 79.00; averaging all six rows would instead have given 40.0 + 26.00 + 7.00 = 73.00.
    assert float(after["welfare_score"]) == 79.00
    assert after["welfare_score_variant"] == "ROLLING"

    rows, meta = validate_paginated(
        api.list_husbandry_logs(specimen["id"], AQUARIST_HEADERS, {"limit": 10})
    )
    # All six rows remain on file; the appetite-1 record is merely outside the scoring window.
    assert meta["total_count"] == 6
    assert len(rows) == 6


def test_wild_collection_clearance_is_refused_when_the_final_score_falls_below_forty(build, api):
    """A fully permitted, in-quota clearance still fails the score floor.

    PRD §3.5: "It requires that the acting `X-User-ID` differ from the plan line's `approved_by_user_id`; that the recomputed `FINAL` score be at least 40.00, else `ERR_CLEARANCE_SCORE_TOO_LOW`; and, for a `WILD_COLLECTION` source, that `wild_take_quota_reserved` plus `requested_count` not exceed `wild_take_quota_annual`, else `ERR_QUOTA_EXCEEDED`."

    PRD §3.5: "When the score rule fails, the recomputed score is not persisted at all."

    Design: Corner/calculations/calc_final_score_below_min_clearance_score_blocks_the_clearance
    """
    world = build.approved_line(
        species_overrides={
            "protection_status": "ESA_LISTED",
            "sustainability_rating": "RED",
            "bioload_units_per_specimen": 30.0,
            "wild_take_quota_annual": 4,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "ANY_WITH_JUSTIFICATION"},
    )
    institution = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=62.0)
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
        justification="ex-situ conservation breeding programme under a federal recovery plan",
    )
    # PROVISIONAL at creation: RED 8.0 + WILD_COLLECTION 10.0 + 0.25 * 62.00 = 15.50 gives an
    # additive 33.50 (under the cap of 100), less the ESA_LISTED penalty of 18.00 = 15.50.
    assert float(request["sustainability_score"]) == 15.50
    assert request["sustainability_score_variant"] == "PROVISIONAL"
    assert request["permit_required"] is True

    submitted = build.submit_acquisition(request["id"])
    assert submitted["status"] == "PENDING_PERMIT"
    permit = build.issue_permit(
        request["id"],
        "IMPORT",
        ["HEALTH_CERTIFICATE", "ORIGIN_DECLARATION", "IMPORT_LICENSE", "ESA_AUTHORIZATION"],
    )
    assert permit["status"] == "ISSUED"

    species_before = build.get_species(world["species"]["id"])
    assert int(species_before["wild_take_quota_reserved"]) == 0

    response = api.clear_acquisition_request(
        request["id"],
        {"expected_species_version": species_before["version"]},
        make_director_headers(CLEARANCE_OFFICER_ID),
    )
    # FINAL: 8.0 + 10.0 + 0.25 * 62.00 = 33.50 additive, plus the 5.0 permit bonus = 38.50,
    # less the 18.00 ESA_LISTED penalty and 20.0 * ((0 + 1) / 4) = 5.00 of quota pressure,
    # which is 15.50 — below the 40.00 floor, while 0 + 1 is still inside the quota of 4.
    validate_error(response, ERR_CLEARANCE_SCORE_TOO_LOW)

    after = build.get_acquisition(request["id"])
    assert after["status"] == "PENDING_PERMIT"
    # The refused clearance persists neither the recomputed score nor the FINAL variant.
    assert float(after["sustainability_score"]) == 15.50
    assert after["sustainability_score_variant"] == "PROVISIONAL"
    assert after["cleared_by_user_id"] is None
    assert after["cleared_at"] is None

    species_after = build.get_species(world["species"]["id"])
    # No quota was reserved and the species' version did not move.
    assert int(species_after["wild_take_quota_reserved"]) == 0
    assert species_after["version"] == species_before["version"]
    assert build.get_permit(permit["id"])["status"] == "ISSUED"


def test_sustainability_score_rounds_a_true_half_up_to_two_decimals(build, api):
    """An institution component of 17.525 rounds up, never down.

    PRD §3.5: "Both then cap the additive total at 100 and subtract a protection penalty of 0.0 for `UNLISTED`, 6.0 for `CITES_APPENDIX_II`, 14.0 for `CITES_APPENDIX_I` or 18.0 for `ESA_LISTED`, before clamping into 0 to 100 and rounding half up to two decimals."

    Design: Corner/calculations/calc_sustainability_score_rounds_half_up_at_two_decimals
    """
    world = build.approved_line(
        species_overrides={
            "protection_status": "UNLISTED",
            "sustainability_rating": "GREEN",
            "bioload_units_per_specimen": 12.0,
            "wild_take_quota_annual": 4,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    institution = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=70.10)
    # ACCREDITED and 70.10 is at or above the inclusive floor of 70.0.
    assert institution["is_receiving_eligible"] is True

    request = build.create_acquisition(
        world["entry"],
        source_type="INSTITUTIONAL_TRANSFER",
        requested_count=1,
        source_institution_id=institution["id"],
    )
    # GREEN 40.0 + INSTITUTIONAL_TRANSFER 22.0 + 0.25 * 70.10 = 17.525 gives exactly 79.525,
    # under the additive cap and with an UNLISTED penalty of 0.0; round half up = 79.53.
    assert float(request["sustainability_score"]) == 79.53
    assert request["sustainability_score_variant"] == "PROVISIONAL"
    # An UNLISTED species obtained by a non-wild channel needs no permit.
    assert request["permit_required"] is False

    submitted = build.submit_acquisition(request["id"])
    assert submitted["status"] == "READY_FOR_CLEARANCE"
    assert submitted["permit_deadline_at"] is None

    cleared = build.clear_acquisition(request["id"], world["species"]["id"])
    assert cleared["status"] == "CLEARED"
    # The READY_FOR_CLEARANCE road earns no permit bonus and a non-wild source draws no quota
    # pressure, so the FINAL figure is the same 79.525 rounded half up.
    assert float(cleared["sustainability_score"]) == 79.53
    assert cleared["sustainability_score_variant"] == "FINAL"

    reread = build.get_acquisition(request["id"])
    assert float(reread["sustainability_score"]) == 79.53
    assert reread["sustainability_score_variant"] == "FINAL"


def test_missing_permit_documents_are_listed_in_the_order_the_requirement_enumerates_them(build, api):
    """A CITES_APPENDIX_I import pulls both conditional documents, in order.

    PRD §3.5: "`missing_document_codes` is the required codes absent from `document_codes`, emitted in the order the requirement itself enumerates them."

    Design: Corner/calculations/calc_permit_missing_documents_are_emitted_in_required_order
    """
    world = build.approved_line(
        species_overrides={
            "protection_status": "CITES_APPENDIX_I",
            "sustainability_rating": "YELLOW",
            "bioload_units_per_specimen": 20.0,
            "wild_take_quota_annual": 4,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "ANY_WITH_JUSTIFICATION"},
    )
    institution = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=88.0)
    request = build.create_acquisition(
        world["entry"],
        source_type="WILD_COLLECTION",
        requested_count=1,
        source_institution_id=institution["id"],
        justification="range-state managed collection under an existing CITES export quota",
    )
    submitted_request = build.submit_acquisition(request["id"])
    assert submitted_request["status"] == "PENDING_PERMIT"

    permit = build.draft_permit(request["id"], "IMPORT", ["ORIGIN_DECLARATION"])
    # The IMPORT requirement enumerates HEALTH_CERTIFICATE, ORIGIN_DECLARATION and
    # IMPORT_LICENSE, then adds CITES_PERMIT for a CITES-listed species and
    # ESA_AUTHORIZATION for an appendix-I one; only ORIGIN_DECLARATION was supplied.
    assert permit["missing_document_codes"] == [
        "HEALTH_CERTIFICATE",
        "IMPORT_LICENSE",
        "CITES_PERMIT",
        "ESA_AUTHORIZATION",
    ]

    refused = api.submit_permit(permit["id"], {}, PERMIT_OFFICER_HEADERS)
    validate_error(refused, ERR_MISSING_DOCUMENTS)

    still_draft = build.get_permit(permit["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["submission_round"] == 0
    # The refused submission changes nothing, so the gap list reads exactly as before.
    assert still_draft["missing_document_codes"] == [
        "HEALTH_CERTIFICATE",
        "IMPORT_LICENSE",
        "CITES_PERMIT",
        "ESA_AUTHORIZATION",
    ]

    complete_codes = [
        "HEALTH_CERTIFICATE",
        "ORIGIN_DECLARATION",
        "IMPORT_LICENSE",
        "CITES_PERMIT",
        "ESA_AUTHORIZATION",
    ]
    accepted = build.submit_permit(permit["id"], document_codes=complete_codes)
    assert accepted["status"] == "SUBMITTED"
    # A successful submission is round 1 and leaves nothing required but absent.
    assert accepted["submission_round"] == 1
    assert accepted["missing_document_codes"] == []
    assert accepted["document_codes"] == complete_codes
    assert build.get_acquisition(request["id"])["status"] == "PENDING_PERMIT"


def test_receiving_eligibility_needs_both_an_admitted_status_and_the_seventy_point_floor(build, api):
    """High scores never rescue an excluded status, and 69.99 misses the floor.

    PRD §3.3: "The derived `is_receiving_eligible` is true when `accreditation_status` is `ACCREDITED` or `PROVISIONAL` **and** `welfare_audit_score` is at least 70.0, both conditions required and the score boundary inclusive."

    Design: Corner/calculations/calc_receiving_eligibility_needs_both_the_status_set_and_the_score_floor
    """
    eligible = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=88.0)
    suspended = build.create_institution(accreditation_status="SUSPENDED", welfare_audit_score=99.0)
    unaccredited = build.create_institution(accreditation_status="NON_ACCREDITED", welfare_audit_score=100.0)
    just_short = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=69.99)

    # ACCREDITED with 88.00 >= 70.0 satisfies both clauses.
    assert eligible["is_receiving_eligible"] is True
    # SUSPENDED is outside the admitted set, so a score of 99.00 cannot rescue it.
    assert suspended["is_receiving_eligible"] is False
    # NON_ACCREDITED is outside the admitted set, so even 100.00 cannot rescue it.
    assert unaccredited["is_receiving_eligible"] is False
    # An admitted status with 69.99 misses the inclusive 70.0 floor by one hundredth.
    assert just_short["is_receiving_eligible"] is False

    rows, meta = validate_paginated(
        api.list_institutions(DIRECTOR_HEADERS, {"is_receiving_eligible": "true", "limit": 10})
    )
    # Exactly one of the four institutions satisfies both conditions at once.
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [eligible["id"]]

    patched = get_success_data(
        api.update_institution(just_short["id"], {"welfare_audit_score": 70.0}, DIRECTOR_HEADERS)
    )
    # Exactly 70.00 qualifies because the boundary is inclusive, and the single edit takes the
    # institution's version from 1 to 2.
    assert float(patched["welfare_audit_score"]) == 70.00
    assert patched["is_receiving_eligible"] is True
    assert patched["version"] == 2

    reread = get_success_data(api.get_institution(just_short["id"], DIRECTOR_HEADERS))
    assert reread["is_receiving_eligible"] is True
    assert get_success_data(api.get_institution(suspended["id"], DIRECTOR_HEADERS))["is_receiving_eligible"] is False
    assert get_success_data(api.get_institution(unaccredited["id"], DIRECTOR_HEADERS))["is_receiving_eligible"] is False

    rows_after, meta_after = validate_paginated(
        api.list_institutions(DIRECTOR_HEADERS, {"is_receiving_eligible": "true", "limit": 10})
    )
    # The flag is recomputed on update, not only at creation; rows come back oldest first.
    assert meta_after["total_count"] == 2
    assert [row["id"] for row in rows_after] == [eligible["id"], just_short["id"]]


def test_bioload_ledger_counts_only_the_placed_sibling_not_the_one_still_in_quarantine(build, api):
    """Two accessioned siblings of the same species, one ledger contribution.

    PRD §3.2: "`occupied_bioload_units` is the sum of `bioload_units` over every specimen whose `exhibit_id` is this exhibit and whose `disposition_status` is `ON_EXHIBIT` or `TRANSFER_PENDING`, rounded half up to two decimals."

    PRD §3.2: "Specimens in `QUARANTINE`, `CLEARED`, `TRANSFERRED` or `DECEASED` contribute nothing — a `TRANSFER_PENDING` animal is still in the tank and still consumes capacity, whereas a `CLEARED` animal has been moved to holding and does not."

    Design: Corner/calculations/calc_bioload_ledger_ignores_quarantined_stablemates
    """
    world = build.approved_line(
        species_overrides={"bioload_units_per_specimen": 12.0, "wild_take_quota_annual": 4},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
        exhibit_overrides={"bioload_capacity_units": 100.0},
    )
    world = build.cleared_acquisition(world=world, source_type="CAPTIVE_BRED", requested_count=2)

    first = build.accession_specimen(world["species"], world["request"])
    second = build.accession_specimen(world["species"], world["request"])
    case = build.quarantine_case_of(first["id"])

    exams = build.record_clean_exams(first["id"], 2)
    build.advance_to(case["projected_release_at"])
    build.close_clean_exams(exams)
    build.review_quarantine(case["id"], "CLEAR")
    build.place(first["id"], world["exhibit"]["id"])

    exhibit = build.get_exhibit(world["exhibit"]["id"])
    # Only the placed animal contributes 12.00 units; both siblings would have summed to 24.00.
    assert float(exhibit["occupied_bioload_units"]) == 12.00
    # 12.00 / 100.00 * 100 = 12.00 per cent.
    assert float(exhibit["bioload_utilization_pct"]) == 12.00
    # 12.00 is not strictly greater than 95.00 and no plant driver applies, so posture is OPEN.
    assert exhibit["posture"] == "OPEN"
    assert exhibit["last_posture_reason"] is None

    placed = build.get_specimen(first["id"])
    assert placed["disposition_status"] == "ON_EXHIBIT"
    assert placed["exhibit_id"] == world["exhibit"]["id"]
    quarantined = build.get_specimen(second["id"])
    # The sibling is still in QUARANTINE and carries no exhibit at all.
    assert quarantined["disposition_status"] == "QUARANTINE"
    assert quarantined["exhibit_id"] is None
    # Its own bioload is the full species figure, so it is the ledger's filter that excludes it.
    assert float(quarantined["bioload_units"]) == 12.00

    rows, meta = validate_paginated(
        api.list_specimens(AQUARIST_HEADERS, {"exhibit_id": world["exhibit"]["id"], "limit": 10})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [first["id"]]

    request = build.get_acquisition(world["request"]["id"])
    # Two specimens against a request for two: fulfilled_count reaches requested_count.
    assert request["fulfilled_count"] == 2
    assert request["status"] == "FULFILLED"


def test_transfer_pending_holds_the_bioload_until_completion_releases_it(build, api):
    """The tank stays occupied while the paperwork is open.

    PRD §3.8: "When the animal was `ON_EXHIBIT` its `exhibit_id` is retained and the exhibit's ledger is unchanged, because a `TRANSFER_PENDING` animal still occupies the tank and still consumes bioload."

    PRD §3.8: "Completion stamps `completed_at`, moves the request to the terminal `COMPLETED`, moves the specimen's `disposition_status` to the terminal `TRANSFERRED` with `exhibit_id` set to null, and recomputes the former exhibit's ledger and posture — the animal has left the building, and the bioload it was holding is released at last."

    Design: Corner/calculations/calc_bioload_ledger_holds_through_transfer_pending_and_releases_on_completion
    """
    world = build.specimen_on_exhibit(
        species_overrides={
            "protection_status": "UNLISTED",
            "bioload_units_per_specimen": 12.0,
            "wild_take_quota_annual": 4,
        },
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
        exhibit_overrides={"bioload_capacity_units": 100.0},
    )
    specimen = world["specimen"]
    exhibit_id = world["exhibit"]["id"]
    # An UNLISTED species needs no permit, so approval demands no TRANSPORT permit.
    assert build.get_species(world["species"]["id"])["permit_required"] is False

    placed_exhibit = build.get_exhibit(exhibit_id)
    # One ON_EXHIBIT specimen of 12.00 units against a capacity of 100.00.
    assert float(placed_exhibit["occupied_bioload_units"]) == 12.00
    assert float(placed_exhibit["bioload_utilization_pct"]) == 12.00

    institution = build.create_institution(accreditation_status="ACCREDITED", welfare_audit_score=88.0)
    proposed_at = shift(build.now, days=30)
    transfer = build.draft_transfer(
        specimen["id"],
        institution["id"],
        proposed_at,
        # An ACCREDITED receiver, an UNLISTED species and no TREATMENT case on file, so the
        # required set is exactly the two codes that are always required.
        welfare_conditions=["WATER_CHEMISTRY_MATCH", "TRANSPORT_OXYGEN_PLAN"],
    )
    submitted = build.submit_transfer(transfer["id"])
    assert submitted["status"] == "SUBMITTED"

    pending = build.get_specimen(specimen["id"])
    assert pending["disposition_status"] == "TRANSFER_PENDING"
    assert pending["pre_transfer_disposition"] == "ON_EXHIBIT"
    assert pending["exhibit_id"] == exhibit_id
    held = build.get_exhibit(exhibit_id)
    # A TRANSFER_PENDING animal still contributes, so the ledger holds at 12.00 units and
    # 12.00 per cent.
    assert float(held["occupied_bioload_units"]) == 12.00
    assert float(held["bioload_utilization_pct"]) == 12.00

    approved = build.decide_transfer(transfer["id"], "APPROVE")
    assert approved["status"] == "APPROVED"
    still_held = build.get_exhibit(exhibit_id)
    # Approval alone releases nothing, because the animal has not moved yet.
    assert float(still_held["occupied_bioload_units"]) == 12.00

    too_early = api.complete_transfer_request(transfer["id"], {}, PERMIT_OFFICER_HEADERS)
    validate_error(too_early, ERR_TRANSFER_DATE_NOT_REACHED)
    assert float(build.get_exhibit(exhibit_id)["occupied_bioload_units"]) == 12.00

    build.advance_to(proposed_at)
    completed = build.complete_transfer(transfer["id"])
    assert completed["status"] == "COMPLETED"
    # The clock has reached proposed_transfer_at exactly, and that boundary is inclusive.
    assert instant_prefix(completed["completed_at"]) == instant_prefix(proposed_at)

    transferred = build.get_specimen(specimen["id"])
    assert transferred["disposition_status"] == "TRANSFERRED"
    assert transferred["exhibit_id"] is None
    released = build.get_exhibit(exhibit_id)
    # The only contributor has left the tank: 12.00 - 12.00 = 0.00 units and 0.00 per cent.
    assert float(released["occupied_bioload_units"]) == 0.00
    assert float(released["bioload_utilization_pct"]) == 0.00
    assert released["posture"] == "OPEN"
    assert released["last_posture_reason"] is None


def test_life_support_warning_outranks_bioload_pressure_as_the_posture_reason(build, api):
    """The first matching condition names the driver, and chemistry is tested first.

    PRD §3.2: "It is derived by walking five conditions in order and stopping at the **first** that matches, which is what makes `last_posture_reason` a statement about the dominant driver rather than a list of grievances:"

    PRD §3.2: "The bioload comparison is strict: an exhibit sitting at exactly 95.00 per cent utilisation stays `OPEN`, and only 95.01 and above tips it to `RESTRICTED`."

    Design: Corner/calculations/calc_posture_reason_follows_the_normative_first_match_order
    """
    world = build.specimen_on_exhibit(
        species_overrides={"bioload_units_per_specimen": 12.0, "wild_take_quota_annual": 4},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
        exhibit_overrides={"bioload_capacity_units": 100.0},
    )
    plant = world["plant"]
    exhibit_id = world["exhibit"]["id"]

    open_exhibit = build.get_exhibit(exhibit_id)
    # 12.00 / 100.00 * 100 = 12.00 per cent, which is not above 95.00.
    assert float(open_exhibit["bioload_utilization_pct"]) == 12.00
    assert open_exhibit["posture"] == "OPEN"
    assert open_exhibit["last_posture_reason"] is None

    squeezed = get_success_data(
        api.update_exhibit(
            exhibit_id,
            {"expected_exhibit_version": open_exhibit["version"], "bioload_capacity_units": 12.0},
            DIRECTOR_HEADERS,
        )
    )
    # 12.00 / 12.00 * 100 = 100.00 per cent, strictly greater than 95.00, and with a NORMAL
    # plant the fifth condition is the first one to match.
    assert float(squeezed["bioload_utilization_pct"]) == 100.00
    assert squeezed["posture"] == "RESTRICTED"
    assert squeezed["last_posture_reason"] == "BIOLOAD_PRESSURE"

    build.append_graded_reading(plant, "WARNING")
    warned_plant = build.get_plant(plant["id"])
    assert warned_plant["alarm_state"] == "WARNING"
    warned_exhibit = build.get_exhibit(exhibit_id)
    # Both the third condition (plant WARNING) and the fifth (utilisation above 95.00) hold,
    # and the walk stops at the third, so the reason is LSS_WARNING, not BIOLOAD_PRESSURE.
    assert warned_exhibit["posture"] == "RESTRICTED"
    assert warned_exhibit["last_posture_reason"] == "LSS_WARNING"
    # The bioload did not change while the alarm was ringing.
    assert float(warned_exhibit["bioload_utilization_pct"]) == 100.00

    build.advance(hours=1)
    build.append_graded_reading(plant, "NORMAL")
    build.advance(hours=1)
    build.append_graded_reading(plant, "NORMAL")
    build.advance(hours=1)
    build.append_graded_reading(plant, "NORMAL")
    cleared_plant = build.get_plant(plant["id"])
    # Three consecutive NORMAL readings meet the hysteresis threshold of 3 from WARNING.
    assert cleared_plant["alarm_state"] == "NORMAL"
    assert cleared_plant["consecutive_normal_readings"] == 3

    recomputed = build.get_exhibit(exhibit_id)
    # With no plant condition matching, the walk falls through to the fifth, which still holds
    # at 100.00 per cent, so the exhibit stays RESTRICTED and names the bioload again.
    assert recomputed["posture"] == "RESTRICTED"
    assert recomputed["last_posture_reason"] == "BIOLOAD_PRESSURE"
    assert build.get_specimen(world["specimen"]["id"])["disposition_status"] == "ON_EXHIBIT"


def test_zero_day_withdrawal_window_admits_a_second_concurrent_treatment(build, api):
    """An empty window overlaps nothing, but a ten-day one blocks the next case.

    PRD §3.7: "Because the interval is half-open, a new window starting exactly where an existing one ends does not conflict, and a `withdrawal_days` of 0 produces an empty window that can never conflict with anything."

    PRD §3.7: "`treatment_withdrawal_until` on the specimen is the latest window end across its `OPEN` `TREATMENT` cases, and null when it has none."

    Design: Corner/calculations/calc_zero_day_withdrawal_window_never_conflicts
    """
    world = build.quarantined_specimen(
        species_overrides={"bioload_units_per_specimen": 12.0, "wild_take_quota_annual": 4},
        entry_overrides={"planned_count": 2, "sustainability_requirement": "GREEN_ONLY"},
    )
    specimen = world["specimen"]
    build.advance_to("2026-08-05T00:00:00Z")
    # No OPEN TREATMENT case yet, so there is no window end to report.
    assert build.get_specimen(specimen["id"])["treatment_withdrawal_until"] is None

    empty_window_case = build.open_vet_case(
        specimen["id"],
        "TREATMENT",
        treatment_start_at="2026-08-05T00:00:00Z",
        withdrawal_days=0,
        diagnosis_code="TOPICAL-RINSE",
    )
    assert empty_window_case["status"] == "OPEN"
    assert empty_window_case["withdrawal_days"] == 0

    first_view = build.get_specimen(specimen["id"])
    assert first_view["health_status"] == "UNDER_TREATMENT"
    # The window is 2026-08-05 advanced by 0 days, so its end is the start instant itself.
    assert instant_prefix(first_view["treatment_withdrawal_until"]) == "2026-08-05T00:00:00"
    # One OPEN TREATMENT case charges 6.0, but the rolling window holds no feeding or
    # behaviour record at all, so both the score and its variant are null.
    assert first_view["welfare_score"] is None
    assert first_view["welfare_score_variant"] is None

    ten_day_case = build.open_vet_case(
        specimen["id"],
        "TREATMENT",
        treatment_start_at="2026-08-05T00:00:00Z",
        withdrawal_days=10,
        diagnosis_code="BACT-DERM-02",
    )
    # Overlap needs the existing window to start strictly before the new one ends and the new
    # one to start strictly before the existing one ends; the empty window fails the second
    # test against itself, so the second treatment is admitted.
    assert ten_day_case["status"] == "OPEN"
    assert ten_day_case["withdrawal_days"] == 10

    second_view = build.get_specimen(specimen["id"])
    # The latest end across the two OPEN treatments is 2026-08-05 advanced by 10 days.
    assert instant_prefix(second_view["treatment_withdrawal_until"]) == "2026-08-15T00:00:00"
    assert second_view["health_status"] == "UNDER_TREATMENT"

    blocked = api.create_veterinary_case(
        {
            "specimen_id": specimen["id"],
            "case_type": "TREATMENT",
            "opened_at": "2026-08-05T00:00:00Z",
            "treatment_start_at": "2026-08-05T00:00:00Z",
            "withdrawal_days": 1,
        },
        VET_HEADERS,
    )
    # A third window of 2026-08-05 to 2026-08-06 does overlap the ten-day window, which is
    # exactly what the zero-day window could not do.
    validate_error(blocked, ERR_TREATMENT_WITHDRAWAL_ACTIVE)

    rows, meta = validate_paginated(
        api.list_specimen_veterinary_cases(
            specimen["id"], VET_HEADERS, {"case_type": "TREATMENT", "limit": 10}
        )
    )
    # The refused third case was never persisted, so exactly two treatments are on file.
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["OPEN", "OPEN"]
    # And the reported window end is unchanged by the refusal.
    assert instant_prefix(
        build.get_specimen(specimen["id"])["treatment_withdrawal_until"]
    ) == "2026-08-15T00:00:00"
