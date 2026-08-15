"""Risk classification, pumping frequency table, and interceptor sizing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_interceptor,
    commission_interceptor,
    create_establishment,
    create_establishment_payload,
    create_interceptor,
    create_interceptor_payload,
    get_establishment,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]


class TestRiskClassification:
    def test_risk_score_capped_weighted_classification(self, api):
        """PRD: "The `risk_score` is the sum of three components: a seating
        contribution of one-tenth of a point per seat, capped at 40 points; an
        equipment contribution of 10 points per deep fryer plus a further 10
        points when a charbroiler is installed, capped at 30 points; and a
        cuisine contribution of 10 points for `LOW_GREASE`, 20 points for
        `MEDIUM_GREASE`, or 30 points for `HIGH_GREASE`."
        PRD: "An establishment's `pumping_frequency_days` is the value of its
        `variance_override_frequency_days` when one has been set by an
        approved variance, and otherwise the risk-table value for its class:
        90 days for `HIGH`, 180 days for `MEDIUM`, and 365 days for `LOW`."

        Design: Difficulty/combinatorial_formula/risk_score_capped_weighted_classification
        """
        est = validate_success(api.create_establishment(
            create_establishment_payload(
                name="Cap City BBQ", street_address="9 Cap Ave",
                seating_capacity=900, fryer_count=5, has_charbroiler=True,
                cuisine_profile="MEDIUM_GREASE"),
            ADMIN), 201)
        # min(40, 900*0.1)=40 + min(30, 5*10+10)=30 + MEDIUM_GREASE 20 = 90.
        # The uncapped linear sum would be 170, so the caps change the result.
        assert est["risk_score"] == 90, (
            f"Caps bind: expected 90, got {est['risk_score']}"
        )
        assert est["risk_class"] == "HIGH", "90 >= 70 classifies HIGH"
        assert est["pumping_frequency_days"] == 90

    def test_risk_score_boundary_inclusive_high_class(self, api):
        """PRD: "The `risk_class` derives from the exact score: at least 70 is
        `HIGH`, at least 40 but below 70 is `MEDIUM`, and anything below 40 is
        `LOW`. The boundaries are inclusive — a score of exactly 70 classifies
        `HIGH`, and exactly 40 classifies `MEDIUM`."

        Design: Difficulty/combinatorial_formula/risk_score_capped_weighted_classification
        """
        # seats 400 -> 40 (cap); no equipment; HIGH_GREASE -> 30; total 70.
        high_edge = validate_success(api.create_establishment(
            create_establishment_payload(
                name="Edge High", street_address="10 Cap Ave",
                seating_capacity=400, fryer_count=0, has_charbroiler=False,
                cuisine_profile="HIGH_GREASE"),
            ADMIN), 201)
        assert high_edge["risk_score"] == 70
        assert high_edge["risk_class"] == "HIGH", "exactly 70 classifies HIGH"

        # seats 100 -> 10; no equipment; HIGH_GREASE -> 30; total 40.
        med_edge = validate_success(api.create_establishment(
            create_establishment_payload(
                name="Edge Med", street_address="11 Cap Ave",
                seating_capacity=100, fryer_count=0, has_charbroiler=False,
                cuisine_profile="HIGH_GREASE"),
            ADMIN), 201)
        assert med_edge["risk_score"] == 40
        assert med_edge["risk_class"] == "MEDIUM", "exactly 40 classifies MEDIUM"


class TestPumpingFrequencyByRiskClass:
    def test_pumping_frequency_by_risk_class(self, api):
        """PRD: "An establishment's `pumping_frequency_days` is the value of
        its `variance_override_frequency_days` when one has been set by an
        approved variance, and otherwise the risk-table value for its class:
        90 days for `HIGH`, 180 days for `MEDIUM`, and 365 days for `LOW`."
        PRD: "The boundaries are inclusive — a score of exactly 70 classifies
        `HIGH`, and exactly 40 classifies `MEDIUM`."

        Design: Corner/calculations/c_pumping_frequency_by_risk_class
        """
        high = validate_success(api.create_establishment(
            create_establishment_payload(
                name="Freq High", street_address="12 K St",
                seating_capacity=200, fryer_count=3, has_charbroiler=False,
                cuisine_profile="HIGH_GREASE"),
            ADMIN), 201)
        # 20 + 30 + 30 = 80 -> HIGH.
        assert high["risk_class"] == "HIGH"
        assert high["pumping_frequency_days"] == 90

        med = validate_success(api.create_establishment(
            create_establishment_payload(
                name="Freq Med", street_address="13 K St",
                seating_capacity=100, fryer_count=1,
                cuisine_profile="MEDIUM_GREASE"),
            ADMIN), 201)
        # 10 + 10 + 20 = 40 -> MEDIUM (boundary inclusive).
        assert med["risk_score"] == 40
        assert med["risk_class"] == "MEDIUM"
        assert med["pumping_frequency_days"] == 180

        low = validate_success(api.create_establishment(
            create_establishment_payload(
                name="Freq Low", street_address="14 K St",
                seating_capacity=50, fryer_count=0,
                cuisine_profile="LOW_GREASE"),
            ADMIN), 201)
        # 5 + 0 + 10 = 15 -> LOW.
        assert low["risk_class"] == "LOW"
        assert low["pumping_frequency_days"] == 365


class TestInterceptorSizing:
    def test_interceptor_sizing_provisional_vs_measured(self, api):
        """PRD: "Consider a profile that yields 495 gallons against a measured
        20 gallons per minute: the measured variant computes to 600 gallons,
        so the interceptor is governed as `MEASURED` at 600 gallons."
        PRD: "At approval the server fixes the final sizing:
        `required_min_capacity_gal` is the provisional requirement when no
        measured flow was supplied, and otherwise the larger of the two
        variants; `sizing_method` is `MEASURED` only when measured flow was
        supplied *and* the measured variant strictly exceeds the provisional
        one, and `PROVISIONAL` in every other case."

        Design: Difficulty/dual_variant_calc/interceptor_sizing_provisional_vs_measured
        """
        est = create_establishment(name="Twin Grill", street_address="1 Main St",
                                   seating_capacity=200, fryer_count=3,
                                   has_charbroiler=False,
                                   cuisine_profile="HIGH_GREASE")
        i1 = create_interceptor(est["id"], nominal_capacity_gal=600)
        i2 = create_interceptor(est["id"], nominal_capacity_gal=700,
                                measured_flow_gpm=20)

        approved_i1 = approve_interceptor(i1["id"])
        approved_i2 = approve_interceptor(i2["id"])

        # Provisional variant: max(50, 200*2 + 3*15 + 0 + 50) = 495.
        assert approved_i1["required_min_capacity_gal"] == 495
        assert approved_i1["sizing_method"] == "PROVISIONAL"
        # Measured variant: ceil(20 gpm * 30 min) = 600 > 495 -> MEASURED.
        assert approved_i2["required_min_capacity_gal"] == 600
        assert approved_i2["sizing_method"] == "MEASURED"
        assert approved_i1["required_min_capacity_gal"] != (
            approved_i2["required_min_capacity_gal"]), (
            "Same establishment profile, different approved minimums"
        )

    def test_interceptor_measured_not_strictly_larger_stays_provisional(self, api):
        """PRD: "`sizing_method` is `MEASURED` only when measured flow was
        supplied *and* the measured variant strictly exceeds the provisional
        one, and `PROVISIONAL` in every other case."
        PRD: "When a `measured_flow_gpm` has been supplied, a second variant
        applies: the measured requirement is the measured flow multiplied by a
        30-minute retention time, again rounded up to the next whole gallon."

        Design: Difficulty/dual_variant_calc/interceptor_sizing_provisional_vs_measured
        """
        est = create_establishment(name="Twin Grill Annex",
                                   street_address="2 Main St",
                                   seating_capacity=200, fryer_count=3,
                                   has_charbroiler=False,
                                   cuisine_profile="HIGH_GREASE")
        # Provisional is 495 gal; measured ceil(10 * 30) = 300 < 495.
        interceptor = create_interceptor(est["id"], nominal_capacity_gal=600,
                                         measured_flow_gpm=10)
        approved = approve_interceptor(interceptor["id"])
        assert approved["required_min_capacity_gal"] == 495, (
            "The larger of the two variants governs"
        )
        assert approved["sizing_method"] == "PROVISIONAL", (
            "measured must strictly exceed provisional to select MEASURED"
        )

    def test_interceptor_sizing_floor_and_undersize_boundary(self, api):
        """PRD: "Take 2 gallons per seat, add 15 gallons per deep fryer, add
        40 gallons when the establishment has a charbroiler, and add a cuisine
        adder of 0 gallons for `LOW_GREASE`, 25 gallons for `MEDIUM_GREASE`,
        or 50 gallons for `HIGH_GREASE`; round the sum up to the next whole
        gallon; the provisional requirement is that figure or 50 gallons,
        whichever is larger."
        PRD: "The approval is rejected with `ERR_INTERCEPTOR_UNDERSIZED` (HTTP
        422) when `nominal_capacity_gal` is smaller than that final
        requirement."

        Design: Corner/calculations/c_interceptor_sizing_floor_and_undersize_boundary
        """
        est = create_establishment(name="Tiny Tea Room",
                                   street_address="16 M St")
        # Raw: 10*2 + 0 + 0 + 0 = 20 -> floor binds at 50.
        i49 = create_interceptor(est["id"], nominal_capacity_gal=49)
        i50 = create_interceptor(est["id"], nominal_capacity_gal=50)
        assert i49["provisional_required_gal"] == 50, (
            f"Floor of 50 gal binds for a tiny profile, got "
            f"{i49['provisional_required_gal']}"
        )

        resp = api.approve_interceptor(i49["id"], OFFICER)
        validate_error(resp, ApiErrorId.ERR_INTERCEPTOR_UNDERSIZED, 422)
        current = validate_success(api.get_interceptor(i49["id"], ADMIN))
        assert current["status"] == "PROPOSED", "Rejected approval changes nothing"

        approved = approve_interceptor(i50["id"])
        assert approved["status"] == "APPROVED", (
            "nominal == required is allowed: the comparison rejects only smaller"
        )

    def test_commission_proposed_interceptor_rejected(self, api):
        """PRD: "Sizing approval belongs to a `ComplianceOfficer` and is
        allowed only from `PROPOSED`."
        PRD: "Commissioning is the field-verified installation sign-off,
        performed by an `Inspector`, moving the interceptor from `APPROVED` to
        `ACTIVE` and recording `commissioned_by_user_id`."

        Design: Corner/state_machines/c_commission_proposed_interceptor_rejected
        """
        est = create_establishment(name="Skip Step Cafe",
                                   street_address="6 F St")
        interceptor = create_interceptor(est["id"], nominal_capacity_gal=50)
        resp = api.commission_interceptor(interceptor["id"], INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        current = validate_success(api.get_interceptor(interceptor["id"], ADMIN))
        assert current["status"] == "PROPOSED"


class TestImmediateConsistency:
    def test_immediate_read_after_write(self, api):
        """PRD: "Take 2 gallons per seat, add 15 gallons per deep fryer, add
        40 gallons when the establishment has a charbroiler, and add a cuisine
        adder of 0 gallons for `LOW_GREASE`, 25 gallons for `MEDIUM_GREASE`,
        or 50 gallons for `HIGH_GREASE`; round the sum up to the next whole
        gallon; the provisional requirement is that figure or 50 gallons,
        whichever is larger."
        PRD: "A newly proposed interceptor sits in `PROPOSED` status."
        PRD: "Unless otherwise specified, every list endpoint returns its
        resources sorted by creation timestamp in ascending order."

        Design: Corner/consistency_model/c_immediate_read_after_write
        """
        est = create_establishment(name="Immediate Inc", street_address="42 Z St",
                                   seating_capacity=200, fryer_count=3,
                                   has_charbroiler=False,
                                   cuisine_profile="HIGH_GREASE")
        created = validate_success(api.create_interceptor(
            create_interceptor_payload(est["id"], 600), ADMIN), 201)
        # max(50, 200*2 + 3*15 + 0 + 50) = 495.
        assert created["status"] == "PROPOSED"
        assert created["provisional_required_gal"] == 495

        fetched = validate_success(api.get_interceptor(created["id"], ADMIN))
        assert fetched["status"] == created["status"] == "PROPOSED"
        assert fetched["provisional_required_gal"] == created[
            "provisional_required_gal"] == 495

        interceptors, meta = validate_paginated(
            api.list_interceptors(ADMIN, {"establishment_id": est["id"]}))
        assert any(i["id"] == created["id"] for i in interceptors), (
            "List visibility is immediate"
        )
