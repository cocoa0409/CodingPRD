"""Treatment recommendations: media selection, softener sizing and acceptance."""

from test_helpers import (
    ApiErrorId,
    OFFICER_ALPHA,
    TEST_USERS,
    assert_close,
    assert_instant_equals,
    fixtures,
    ids_of,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OFFICER_B = TEST_USERS["compliance_officer_beta_headers"]

CLEAN_ANALYTES = {
    "nitrate_mg_l": 1.0,
    "arsenic_mg_l": 0.001,
    "lead_mg_l": 0.001,
    "iron_mg_l": 0.10,
}


def _hardwater_world():
    """A softener-sized recommendation on a well that then goes to ADVISORY."""
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Hardwater Homestead",
        email="ap@hardwater.example",
        membership_tier="NONE",
        address_line="5 Hardwater Ln",
        distance_miles=12.0,
        household_size=5,
        depth_feet=230.0,
        drawdown=8.0,
        technician_name="Otto Berger",
    )
    chem = fixtures.chemical_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T08:00:00Z",
        "2026-06-01T20:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=20.0,
        **CLEAN_ANALYTES,
    )
    world["recommendation"] = fixtures.create_recommendation(world["well_id"], chem["id"])
    world["recommendation_id"] = world["recommendation"]["id"]
    bac = fixtures.presumptive_positive_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-02T08:00:00Z",
        "2026-06-02T20:00:00Z",
        OFFICER_ALPHA,
    )
    world["bac_test_id"] = bac["id"]
    return world


def test_softener_sizing_runs_off_the_hardness_and_the_household(api):
    """PRD 3.4: "The **design grain load** is the test's `hardness_gpg` multiplied by the
    property's `household_size`, multiplied by `WATER_USE_GAL_PER_PERSON_PER_DAY` (75
    gallons per person per day), multiplied by `REGEN_INTERVAL_DAYS` (7 days), rounded
    half up to a whole number and stored as `design_grains`."
    PRD 3.4: "Finally, `monthly_salt_lbs` is the selected band's salt per regeneration
    multiplied by 30 and divided by `REGEN_INTERVAL_DAYS` (7), rounded half up to one
    decimal place: 6 pounds per regeneration gives 25.7, 9 gives 38.6, 12 gives 51.4, 15
    gives 64.3 and 18 gives 77.1."
    PRD 3.4: "Expiry is anchored on the **water test's** `sample_datetime`, never on the
    recommendation's own `created_at`: `expires_at` is the sample instant plus
    `RECOMMENDATION_VALIDITY_DAYS` (180 days)."

    Design: Difficulty/cross_entity_state_dependency/treatment_acceptance_depends_on_well_potability_posture
    """
    world = _hardwater_world()
    recommendation = fixtures.get_recommendation(world["recommendation_id"])
    assert recommendation["recommended_media"] == "SOFTENER_RESIN"
    assert recommendation["design_grains"] == 52500
    assert recommendation["selected_capacity"] == "CAP_64000"
    assert recommendation["salt_lbs_per_regen"] == 15
    assert_close(
        recommendation["monthly_salt_lbs"],
        64.3,
        "TreatmentRecommendation.monthly_salt_lbs",
    )
    assert_instant_equals(
        recommendation["expires_at"],
        "2026-11-28T08:00:00Z",
        "TreatmentRecommendation.expires_at",
    )


def test_acceptance_is_blocked_while_a_presumptive_advisory_is_open_then_allowed(api):
    """PRD 3.4: "The well must not be sitting at `ADVISORY` with `advisory_reason`
    `PRESUMPTIVE_COLIFORM` — an unresolved bacteriological question blocks a treatment
    decision, and the refusal is `ERR_POTABILITY_PENDING_CONFIRMATION`."
    PRD 3.4: "Acceptance installs the media and rewires the maintenance clocks. The
    well's `treatment_media` is set to `recommended_media`."

    Design: Difficulty/cross_entity_state_dependency/treatment_acceptance_depends_on_well_potability_posture
    """
    world = _hardwater_world()
    validate_error(
        api.accept_treatment_recommendation(
            world["recommendation_id"], world["customer_headers"]
        ),
        ApiErrorId.ERR_POTABILITY_PENDING_CONFIRMATION.value,
        422,
    )

    fixtures.set_clock("2026-06-10T09:00:00Z")
    validate_success(
        api.record_confirmatory_result(
            world["bac_test_id"],
            {
                "confirm_sample_datetime": "2026-06-10T08:00:00Z",
                "confirm_analyzed_at": "2026-06-10T20:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": world["technician_id"],
            },
            OFFICER_B,
        )
    )
    accepted = validate_success(
        api.accept_treatment_recommendation(
            world["recommendation_id"], world["customer_headers"]
        )
    )
    assert accepted["status"] == "ACCEPTED"
    well = fixtures.get_well(world["well_id"])
    assert well["potability_status"] == "SAFE"
    assert well["treatment_media"] == "SOFTENER_RESIN"


def test_a_new_recommendation_supersedes_the_previous_one(api):
    """PRD 3.4: "Creating a recommendation on a well sets **every earlier** `PROPOSED` or
    `ACCEPTED` recommendation on that well to `SUPERSEDED` with `superseded_by_id`
    pointing at the new row, and raises the well's `version` by 1."
    PRD 3.4: "If the test's `hardness_gpg` is present and is at least
    `HARDNESS_TREATMENT_TRIGGER_GPG` (7.0 grains per gallon — exactly 7.0 triggers), the
    `recommended_media` is `SOFTENER_RESIN`."

    Design: Corner/state_machines/corner_treatment_recommendation_supersedes_the_previous_one
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Supersede Co",
        email="sc@corner.example",
        address_line="10 Supersede",
        household_size=4,
        technician_name="Sup Tech",
    )
    chem1 = fixtures.chemical_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=12.0,
        **CLEAN_ANALYTES,
    )
    rec1 = fixtures.create_recommendation(world["well_id"], chem1["id"])

    chem2 = fixtures.chemical_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-02T00:00:00Z",
        "2026-06-02T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=12.0,
        **CLEAN_ANALYTES,
    )
    rec2 = fixtures.create_recommendation(world["well_id"], chem2["id"])

    first = fixtures.get_recommendation(rec1["id"])
    assert first["status"] == "SUPERSEDED"
    assert first["superseded_by_id"] == rec2["id"]

    second = fixtures.get_recommendation(rec2["id"])
    assert second["status"] == "PROPOSED"
    assert second["recommended_media"] == "SOFTENER_RESIN"
    assert second["design_grains"] == 25200
    assert second["selected_capacity"] == "CAP_32000"
    assert_close(
        second["monthly_salt_lbs"], 38.6, "TreatmentRecommendation.monthly_salt_lbs"
    )

    rows, _ = validate_paginated(
        api.list_treatment_recommendations(OFFICER, params={"superseded_by_id": rec2["id"]})
    )
    assert ids_of(rows) == [rec1["id"]]


def test_the_dual_tank_band_steps_the_monthly_salt_down(api):
    """PRD 3.4: "The last row is a genuine **step down**: a dual-tank unit alternates two
    64000-grain resin beds, so each regeneration consumes less salt than the single-tank
    band beneath it even though total capacity is larger."
    PRD 3.4: "The chain from hardness through design grains and capacity to monthly salt
    is therefore **not monotone**: with a household of 5, hardness 20.0 yields 64.3
    pounds a month, hardness 30.0 yields 77.1, and hardness 31.0 drops back to 64.3."

    Design: Corner/calculations/corner_softener_dual_tank_band_steps_salt_down
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Stepdown Co", "JUR_ALPHA", "sd@corner.example")
    prop = fixtures.new_property(account["id"], "30 Stepdown", "JUR_ALPHA", 10.0, 5)
    well_1 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_2 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 210.0)
    technician = fixtures.new_technician("Step Tech", "JOURNEYMAN", "JUR_ALPHA")

    chem1 = fixtures.chemical_panel(
        well_1["id"],
        technician["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=30.0,
        **CLEAN_ANALYTES,
    )
    chem2 = fixtures.chemical_panel(
        well_2["id"],
        technician["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=31.0,
        **CLEAN_ANALYTES,
    )
    rec1 = fixtures.create_recommendation(well_1["id"], chem1["id"])
    rec2 = fixtures.create_recommendation(well_2["id"], chem2["id"])

    assert rec1["design_grains"] == 78750
    assert rec1["selected_capacity"] == "CAP_80000"
    assert rec1["salt_lbs_per_regen"] == 18
    assert_close(rec1["monthly_salt_lbs"], 77.1, "rec1.monthly_salt_lbs")

    assert rec2["design_grains"] == 81375
    assert rec2["selected_capacity"] == "DUAL_TANK_64000"
    assert rec2["salt_lbs_per_regen"] == 15
    assert_close(rec2["monthly_salt_lbs"], 64.3, "rec2.monthly_salt_lbs")
    assert rec2["monthly_salt_lbs"] < rec1["monthly_salt_lbs"]


def test_softener_capacity_bands_below_the_step_down_are_increasing(api):
    """PRD 3.4: "Finally, `monthly_salt_lbs` is the selected band's salt per regeneration
    multiplied by 30 and divided by `REGEN_INTERVAL_DAYS` (7), rounded half up to one
    decimal place: 6 pounds per regeneration gives 25.7, 9 gives 38.6, 12 gives 51.4, 15
    gives 64.3 and 18 gives 77.1."
    PRD 3.4: "Expiry is anchored on the **water test's** `sample_datetime`, never on the
    recommendation's own `created_at`: `expires_at` is the sample instant plus
    `RECOMMENDATION_VALIDITY_DAYS` (180 days)."

    Design: Corner/calculations/corner_calc_softener_capacity_bands_below_the_step_down
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    account = fixtures.new_account("Softener Band Co", "JUR_ALPHA", "sf@corner.example")
    prop = fixtures.new_property(account["id"], "4 Softener", "JUR_ALPHA", 10.0, 4)
    technician = fixtures.new_technician("Sampler Tech", "JOURNEYMAN", "JUR_ALPHA")

    expectations = [
        (10.0, 21000, "CAP_24000", 6, 25.7),
        (15.0, 31500, "CAP_32000", 9, 38.6),
        (20.0, 42000, "CAP_48000", 12, 51.4),
    ]
    recommendations = []
    for hardness, grains, capacity, salt, monthly in expectations:
        well = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
        test = fixtures.collect_sample(
            well["id"], technician["id"], "CHEMICAL", "2026-06-01T00:00:00Z", headers=OFFICER
        )
        fixtures.record_lab_result(
            test["id"], {"analyzed_at": "2026-06-02T00:00:00Z", "hardness_gpg": hardness}
        )
        recommendation = fixtures.create_recommendation(well["id"], test["id"])
        recommendations.append(recommendation)
        assert recommendation["recommended_media"] == "SOFTENER_RESIN"
        assert recommendation["design_grains"] == grains
        assert recommendation["selected_capacity"] == capacity
        assert recommendation["salt_lbs_per_regen"] == salt
        assert_close(
            recommendation["monthly_salt_lbs"],
            monthly,
            "TreatmentRecommendation.monthly_salt_lbs",
        )

    assert_instant_equals(
        recommendations[0]["expires_at"],
        "2026-11-28T00:00:00Z",
        "TreatmentRecommendation.expires_at",
    )
    assert recommendations[0]["status"] == "PROPOSED"
    assert recommendations[0]["status_effective"] == "PROPOSED"


def test_carbon_media_drives_the_interval_onto_its_floor(api):
    """PRD 3.4: "Otherwise, if `nitrate_mg_l` is present and strictly above 10.0, or
    `arsenic_mg_l` is present and strictly above 0.010, or `lead_mg_l` is present and
    strictly above 0.015, the media is `CARBON`."
    PRD 3.10: "The **maintenance interval** is the base interval for the well's
    `duty_cycle_class` less a reduction for the installed media, floored at
    `MIN_MAINTENANCE_INTERVAL_DAYS` (120 days)."
    PRD 3.4: "When the media is not `SOFTENER_RESIN`, `design_grains`,
    `selected_capacity`, `salt_lbs_per_regen` and `monthly_salt_lbs` are all null."

    Design: Corner/calculations/corner_maintenance_interval_floor_binds_at_high_duty_with_carbon
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    world = fixtures.base_world(
        account_name="Floor Co",
        email="fl@corner.example",
        address_line="120 Floor",
        household_size=4,
        drawdown=4.0,
        technician_name="Floor Tech",
    )
    plan = fixtures.new_maintenance_plan(world["well_id"], world["account_id"])
    chem = fixtures.chemical_panel(
        world["well_id"],
        world["technician_id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        nitrate_mg_l=12.0,
        arsenic_mg_l=0.001,
        lead_mg_l=0.001,
        iron_mg_l=0.10,
        hardness_gpg=3.0,
    )
    recommendation = fixtures.create_recommendation(world["well_id"], chem["id"])
    assert recommendation["recommended_media"] == "CARBON"
    assert recommendation["design_grains"] is None

    validate_success(
        api.accept_treatment_recommendation(
            recommendation["id"], world["customer_headers"]
        )
    )
    well = fixtures.get_well(world["well_id"])
    assert well["treatment_media"] == "CARBON"
    assert well["duty_cycle_class"] == "HIGH"

    refreshed = fixtures.get_plan(plan["id"])
    assert refreshed["interval_days_as_designed"] == 180
    assert refreshed["interval_days_as_operated"] == 120
    assert refreshed["filter_media"] == "CARBON"
    assert_close(refreshed["monthly_salt_lbs"], 0.0, "MaintenancePlan.monthly_salt_lbs")
    assert_instant_equals(
        refreshed["next_due_at"], "2026-09-29T09:00:00Z", "MaintenancePlan.next_due_at"
    )


def test_treatment_family_gates_are_each_answered_by_their_own_error(api):
    """PRD 3.4: "If no clause matches, no media can be selected and the creation is
    refused with `ERR_NO_TREATMENT_INDICATED`."
    PRD 3.3: "Recording a laboratory result on a test that is not in `COLLECTED` is
    refused with `ERR_WATER_TEST_INVALID_STATE`."
    PRD 3.4: "The recommendation must not be effectively expired, or the answer is
    `ERR_TREATMENT_RECOMMENDATION_EXPIRED`."
    PRD 3.4: "it is `EXPIRED` when the stored status is `PROPOSED` and the logical clock
    has reached or passed `expires_at`, and otherwise it simply equals the stored
    status."

    Design: Corner/errors/corner_treatment_family_gates_rejected
    """
    fixtures.set_clock("2026-06-01T09:00:00Z")
    account = fixtures.new_account("Treatment Co", "JUR_ALPHA", "tr@corner.example")
    prop = fixtures.new_property(account["id"], "8 Treatment", "JUR_ALPHA", 10.0, 4)
    well_1 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 200.0)
    well_2 = fixtures.new_well(prop["id"], "JUR_ALPHA", "DRILLED", 220.0)
    technician = fixtures.new_technician("Treatment Tech", "JOURNEYMAN", "JUR_ALPHA")

    clean = fixtures.chemical_panel(
        well_1["id"],
        technician["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=3.0,
        **CLEAN_ANALYTES,
    )
    hard = fixtures.chemical_panel(
        well_2["id"],
        technician["id"],
        "2026-06-01T00:00:00Z",
        "2026-06-01T06:00:00Z",
        OFFICER_ALPHA,
        hardness_gpg=20.0,
        **CLEAN_ANALYTES,
    )
    recommendation = fixtures.create_recommendation(well_2["id"], hard["id"])
    well_1_version = fixtures.get_well(well_1["id"])["version"]
    bac = fixtures.presumptive_positive_panel(
        well_2["id"],
        technician["id"],
        "2026-06-02T00:00:00Z",
        "2026-06-02T06:00:00Z",
        OFFICER_ALPHA,
    )
    fixtures.set_clock("2026-11-28T00:00:00Z")

    validate_error(
        api.create_treatment_recommendation(
            well_1["id"],
            {
                "water_test_id": clean["id"],
                "expected_well_profile_version": well_1_version,
            },
            OFFICER,
        ),
        ApiErrorId.ERR_NO_TREATMENT_INDICATED.value,
        422,
    )
    validate_error(
        api.record_lab_result(
            hard["id"],
            {"analyzed_at": "2026-06-01T07:00:00Z", "hardness_gpg": 21.0},
            OFFICER,
        ),
        ApiErrorId.ERR_WATER_TEST_INVALID_STATE.value,
        409,
    )
    validate_error(
        api.record_confirmatory_result(
            bac["id"],
            {
                "confirm_sample_datetime": "2026-06-03T00:00:00Z",
                "confirm_analyzed_at": "2026-06-04T07:00:00Z",
                "confirm_coliform_present": False,
                "collected_by_technician_id": technician["id"],
            },
            OFFICER_B,
        ),
        ApiErrorId.ERR_WATER_TEST_HOLD_TIME_EXCEEDED.value,
        422,
    )

    current = fixtures.get_recommendation(recommendation["id"])
    assert_instant_equals(
        current["expires_at"],
        "2026-11-28T00:00:00Z",
        "TreatmentRecommendation.expires_at",
    )
    assert current["status_effective"] == "EXPIRED"

    validate_error(
        api.accept_treatment_recommendation(
            recommendation["id"], fixtures.make_customer_headers(account["id"])
        ),
        ApiErrorId.ERR_TREATMENT_RECOMMENDATION_EXPIRED.value,
        422,
    )
    assert fixtures.get_recommendation(recommendation["id"])["status"] == "PROPOSED"


def test_acceptance_is_guarded_on_the_stored_status_and_is_not_repeatable(api):
    """PRD 3.4: "Three business conditions guard it beyond the stored status being
    `PROPOSED` — which, if violated, is `ERR_TREATMENT_RECOMMENDATION_INVALID_STATE`."
    PRD 3.4: "Every `ACTIVE` maintenance plan on that well has its `filter_media` set to
    the same media and its `monthly_salt_lbs` set from the recommendation — which is 0.0
    whenever the media is not `SOFTENER_RESIN` — and then recomputes
    `interval_days_as_operated` and `next_due_at`."
    PRD 3.10: "The media reductions are 0 days for `NONE`, 30 for `SEDIMENT`, 90 for
    `CARBON` and 0 for `SOFTENER_RESIN`."

    Design: Corner/errors/corner_error_treatment_recommendation_accept_is_not_repeatable
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    world = fixtures.base_world(
        account_name="Accept Once Co",
        email="ac@corner.example",
        address_line="1 Accept",
        household_size=4,
        technician_name="Accept Tech",
    )
    plan = fixtures.new_maintenance_plan(world["well_id"], world["account_id"])
    test = fixtures.collect_sample(
        world["well_id"], world["technician_id"], "CHEMICAL", "2026-06-01T00:00:00Z",
        headers=OFFICER,
    )
    fixtures.record_lab_result(
        test["id"], {"analyzed_at": "2026-06-02T00:00:00Z", "hardness_gpg": 20.0}
    )
    recommendation = fixtures.create_recommendation(world["well_id"], test["id"])

    accepted = validate_success(
        api.accept_treatment_recommendation(
            recommendation["id"], world["customer_headers"]
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["status_effective"] == "ACCEPTED"
    assert accepted["selected_capacity"] == "CAP_48000"
    assert_close(
        accepted["monthly_salt_lbs"], 51.4, "TreatmentRecommendation.monthly_salt_lbs"
    )

    assert fixtures.get_well(world["well_id"])["treatment_media"] == "SOFTENER_RESIN"
    refreshed = fixtures.get_plan(plan["id"])
    assert refreshed["filter_media"] == "SOFTENER_RESIN"
    assert_close(refreshed["monthly_salt_lbs"], 51.4, "MaintenancePlan.monthly_salt_lbs")
    assert refreshed["interval_days_as_designed"] == 270
    assert refreshed["interval_days_as_operated"] == 270

    validate_error(
        api.accept_treatment_recommendation(
            recommendation["id"], world["customer_headers"]
        ),
        ApiErrorId.ERR_TREATMENT_RECOMMENDATION_INVALID_STATE.value,
        409,
    )
    assert fixtures.get_recommendation(recommendation["id"])["superseded_by_id"] is None


def test_recommendation_creation_rejects_a_stale_well_profile_version(api):
    """PRD 2.8: "Creating a treatment recommendation under a well profile requires
    `expected_well_profile_version` carrying the client's last observed `version` of that
    `WellProfile`. A mismatch with the stored value is rejected with
    `ERR_STALE_WELL_PROFILE_VERSION` (HTTP 412)."
    PRD 3.4: "Creating a recommendation on a well sets **every earlier** `PROPOSED` or
    `ACCEPTED` recommendation on that well to `SUPERSEDED` with `superseded_by_id`
    pointing at the new row, and raises the well's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/corner_occ_treatment_recommendation_rejects_a_stale_well_profile_version
    """
    fixtures.set_clock("2026-06-02T09:00:00Z")
    world = fixtures.base_world(
        account_name="Well OCC Co",
        email="wo@corner.example",
        address_line="412 Well",
        household_size=4,
        technician_name="Well OCC Tech",
    )
    test = fixtures.collect_sample(
        world["well_id"], world["technician_id"], "CHEMICAL", "2026-06-01T00:00:00Z",
        headers=OFFICER,
    )
    fixtures.record_lab_result(
        test["id"], {"analyzed_at": "2026-06-02T00:00:00Z", "hardness_gpg": 20.0}
    )
    observed = fixtures.get_well(world["well_id"])["version"]

    validate_error(
        api.create_treatment_recommendation(
            world["well_id"],
            {"water_test_id": test["id"], "expected_well_profile_version": observed - 1},
            OFFICER,
        ),
        ApiErrorId.ERR_STALE_WELL_PROFILE_VERSION.value,
        412,
    )
    recommendation = validate_success(
        api.create_treatment_recommendation(
            world["well_id"],
            {"water_test_id": test["id"], "expected_well_profile_version": observed},
            OFFICER,
        ),
        201,
    )
    assert_close(
        fixtures.get_well(world["well_id"])["hardness_gpg"],
        20.0,
        "WellProfile.hardness_gpg",
    )
    assert recommendation["recommended_media"] == "SOFTENER_RESIN"
    assert recommendation["design_grains"] == 42000
    assert recommendation["status"] == "PROPOSED"

    rows, _ = validate_paginated(
        api.list_water_test_recommendations(test["id"], OFFICER)
    )
    assert ids_of(rows) == [recommendation["id"]]
    assert fixtures.get_well(world["well_id"])["version"] == observed + 1
