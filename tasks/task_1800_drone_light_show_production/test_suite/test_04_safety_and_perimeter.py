"""Safety configuration approval gates, segregation of duties, OCC on
creation, and crowd-distance perimeter governance (PLANNED and AS_FLOWN)."""
from test_helpers import (
    ApiErrorId,
    approve_safety_config,
    authorize_show,
    create_authorization,
    create_design,
    create_safety_config,
    create_show,
    create_site,
    decide_authorization,
    get_show,
    lock_design,
    record_simulation,
    set_clock,
    setup_executed_show,
    setup_show_with_locked_design,
    submit_authorization,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_safety_officer_headers

PLANNER = TEST_USERS["planner_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]


class TestSafetyApprovalGates:
    def test_safety_approve_sod_creator_cannot_approve(self, api):
        """PRD: "A `SafetyOfficer` approving a safety configuration must not be
        the user who created it: the caller must differ from the
        configuration's `created_by_user_id`." — "Each violation is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        PRD: "A successful approval stamps the configuration `APPROVED`,
        records the approver as `approved_by_user_id`"

        Design: Corner/validations/safety_approve_sod_creator_cannot_approve
        """
        ctx = setup_show_with_locked_design()
        config = create_safety_config(ctx["show"]["id"], creator_user_id="planner-1")

        # The creating user id cannot approve, even wearing a SafetyOfficer role.
        resp = api.approve_safety_configuration(
            config["id"], make_safety_officer_headers("planner-1"))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        approved = validate_success(api.approve_safety_configuration(
            config["id"], make_safety_officer_headers("so-1")))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "so-1"

    def test_approve_without_locked_design_returns_design_not_locked(self, api):
        """PRD: "The parent show must hold a pinned design in `LOCKED` status,
        else `ERR_DESIGN_NOT_LOCKED`."

        Design: Corner/validations/safety_approve_without_locked_design_returns_design_not_locked
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        design = create_design(show["id"])
        record_simulation(design["id"])  # SIMULATED, never locked
        config = create_safety_config(show["id"])

        resp = api.approve_safety_configuration(
            config["id"], make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_LOCKED)

    def test_geofence_below_required_rejected(self, api):
        """PRD: "The `geofence_radius_m` must be at least the required
        crowd-distance radius computed for the pinned design under the `PLANNED`
        variant, else `ERR_GEOFENCE_BELOW_REQUIRED`."
        PRD: "The **required radius** is 40 meters, plus 0.4 meters for every
        foot of altitude, plus 1.2 meters per drone, rounded half up to one
        decimal place."

        Design: Corner/validations/geofence_below_required_rejected
        """
        ctx = setup_show_with_locked_design()  # 300 ft / 10 drones -> 172.0 m
        config = create_safety_config(ctx["show"]["id"], geofence_radius_m=171.9)
        resp = api.approve_safety_configuration(
            config["id"], make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_GEOFENCE_BELOW_REQUIRED)

    def test_config_ceiling_below_design_rejected(self, api):
        """PRD: "The `altitude_hard_ceiling_ft` must be at least the pinned
        design's `max_altitude_ft`, else `ERR_CEILING_BELOW_DESIGN`, while also
        not exceeding the venue's `site_max_altitude_ft`, else
        `ERR_ALTITUDE_CEILING_EXCEEDS_SITE`."

        Design: Corner/validations/config_ceiling_below_design_rejected
        """
        ctx = setup_show_with_locked_design()  # design max altitude 300 ft
        config = create_safety_config(ctx["show"]["id"], geofence_radius_m=250,
                                      altitude_hard_ceiling_ft=250)
        resp = api.approve_safety_configuration(
            config["id"], make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_CEILING_BELOW_DESIGN)


class TestSafetyConfigOcc:
    def test_stale_show_version_rejected_on_create(self, api):
        """PRD: "Creating a safety configuration supersedes the show's current
        non-superseded configuration, and locking a show design re-pins the show
        while superseding the previously locked design; in both cases the
        request body must carry `expected_show_event_version` holding the show's
        `version` as the caller last read it. If the show's current `version`
        does not match the supplied value — because the caller's view of the
        show is stale relative to writes it has not observed — the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412), and no supersession or
        re-pin occurs."

        Design: Corner/cross_cutting_layers/occ_stale_version_safety_config_create
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        stale_version = show["version"]
        # C1's creation mutates the show, advancing its version past our read.
        c1 = create_safety_config(show["id"])

        resp = api.create_safety_configuration(
            {"show_event_id": show["id"], "geofence_radius_m": 260,
             "altitude_hard_ceiling_ft": 400, "lost_link_action": "HOVER_THEN_LAND",
             "geofence_breach_action": "RETURN_TO_HOME",
             "battery_rtl_threshold_pct": 25,
             "expected_show_event_version": stale_version},
            PLANNER)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_show(show["id"])["version"]
        resp = api.create_safety_configuration(
            {"show_event_id": show["id"], "geofence_radius_m": 260,
             "altitude_hard_ceiling_ft": 400, "lost_link_action": "HOVER_THEN_LAND",
             "geofence_breach_action": "RETURN_TO_HOME",
             "battery_rtl_threshold_pct": 25,
             "expected_show_event_version": fresh_version},
            PLANNER)
        validate_success(resp, 201)

        c1_after = validate_success(api.get_safety_configuration(c1["id"], PLANNER))
        assert c1_after["status"] == "SUPERSEDED", \
            "the new configuration supersedes the show's previous one"


class TestPerimeterAssessment:
    def test_as_flown_without_flight_logs_returns_no_flight_data(self, api):
        """PRD: "requesting `AS_FLOWN` for a show with no flight logs is
        rejected with `ERR_NO_FLIGHT_DATA`."
        PRD: "The `PLANNED` variant — the default whenever a pinned design
        exists — draws altitude and count from the pinned design's
        `max_altitude_ft` and `drone_count`."

        Design: Corner/validations/as_flown_perimeter_without_logs_returns_no_flight_data
        """
        ctx = setup_show_with_locked_design()  # 300 ft / 10 drones
        resp = api.get_perimeter_assessment(ctx["show"]["id"], SAFETY,
                                            params={"variant": "AS_FLOWN"})
        validate_error(resp, ApiErrorId.ERR_NO_FLIGHT_DATA)

        planned = validate_success(api.get_perimeter_assessment(
            ctx["show"]["id"], SAFETY, params={"variant": "PLANNED"}))
        assert planned["required_radius_m"] == 172.0, \
            "40 + 0.4*300 + 1.2*10 for the pinned design"

    def test_perimeter_insufficient_blocks_authorize(self, api):
        """PRD: "**Containment** is `VALID` when the required radius plus a
        15-meter buffer fits within half of the smaller of the site's
        `ground_length_m` and `ground_width_m`; otherwise it is `INSUFFICIENT`."
        PRD: "and `PLANNED` perimeter containment equal to `VALID` (else
        `ERR_PERIMETER_INSUFFICIENT`)."

        Design: Corner/calculations/perimeter_insufficient_blocks_authorize
        """
        site = create_site(ground_length_m=500, ground_width_m=400)
        set_clock()
        show = create_show(site["id"], drone_count_planned=60)
        design = create_design(show["id"], drone_count=60, max_altitude_ft=400)
        record_simulation(design["id"])
        lock_design(show["id"], design["id"])
        # 400 ft / 60 drones -> 40 + 160 + 72 = 272.0 m; +15 buffer = 287.0,
        # which exceeds half the smaller ground dimension (400/2 = 200).
        config = create_safety_config(show["id"], geofence_radius_m=300,
                                      altitude_hard_ceiling_ft=400)
        approve_safety_config(config["id"])
        auth = create_authorization(show["id"])
        submit_authorization(auth["id"])
        decide_authorization(auth["id"], "APPROVED")

        assessment = validate_success(api.get_perimeter_assessment(
            show["id"], PLANNER))
        assert assessment["required_radius_m"] == 272.0
        assert assessment["containment"] == "INSUFFICIENT"

        resp = api.authorize_show(show["id"], {"authorization_id": auth["id"]},
                                  PLANNER)
        validate_error(resp, ApiErrorId.ERR_PERIMETER_INSUFFICIENT)


class TestPerimeterVariantDivergence:
    def _executed_show_with_telemetry(self):
        """Show flown to EXECUTED: pinned design 300 ft / 10 drones, and ten
        flight logs reporting max altitude 295 ft."""
        return setup_executed_show(
            design_overrides={"drone_count": 10, "max_altitude_ft": 300},
            show_overrides={"drone_count_planned": 10},
            with_flight_logs=True, battery_consumed_pct=42,
            max_altitude_reached_ft=295, max_deviation_m=1.2)

    def test_planned_variant_uses_pinned_design_parameters(self, api):
        """PRD: "The `PLANNED` variant — the default whenever a pinned design
        exists — draws altitude and count from the pinned design's
        `max_altitude_ft` and `drone_count`."
        PRD: "The **required radius** is 40 meters, plus 0.4 meters for every
        foot of altitude, plus 1.2 meters per drone, rounded half up to one
        decimal place."

        Design: Difficulty/dual_variant_calc/crowd_radius_planned_vs_as_flown_divergence
        """
        ctx = self._executed_show_with_telemetry()
        planned = validate_success(api.get_perimeter_assessment(
            ctx["show"]["id"], SAFETY, params={"variant": "PLANNED"}))
        assert planned["required_radius_m"] == 172.0, \
            "40 + 0.4*300 + 1.2*10 from the pinned design"
        assert planned["containment"] == "VALID", "172.0 + 15 fits within 400 m"

    def test_as_flown_variant_uses_telemetry_and_diverges(self, api):
        """PRD: "The `AS_FLOWN` variant is a post-flight audit: it uses the
        highest `max_altitude_reached_ft` across the show's flight logs and the
        count of those logs, producing a different radius whenever reality
        deviated from the plan"

        Design: Difficulty/dual_variant_calc/crowd_radius_planned_vs_as_flown_divergence
        """
        ctx = self._executed_show_with_telemetry()
        planned = validate_success(api.get_perimeter_assessment(
            ctx["show"]["id"], SAFETY, params={"variant": "PLANNED"}))
        flown = validate_success(api.get_perimeter_assessment(
            ctx["show"]["id"], SAFETY, params={"variant": "AS_FLOWN"}))
        # Telemetry: max altitude 295 ft over 10 flight logs.
        assert flown["required_radius_m"] == 170.0, "40 + 0.4*295 + 1.2*10"
        assert flown["containment"] == "VALID"
        assert planned["required_radius_m"] != flown["required_radius_m"], \
            "same show, two variants, different radii (172.0 vs 170.0)"
