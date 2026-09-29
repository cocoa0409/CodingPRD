"""Derived figures pinned at their declared rounding points and input sets."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_created_at_ascending,
    assert_decimal_equals,
    assert_field_values,
    assert_fields_null,
    assert_integer_cents,
    assert_reserve_conserved,
    assert_unchanged,
    assert_unit_ledger_conserved,
)
from test_helpers.test_users import INTAKE_HEADERS, OFFICER_HEADERS

ANALYSIS_WINDOW = {
    "window_start": "2026-01-01T00:00:00Z",
    "window_end": "2026-02-28T00:00:00Z",
}

# Three clinic-treated hotline burns: 8 x 1.00 each, so the severity sum is
# 24.00 and the worst injury behind the docket is MEDICAL_TREATMENT.
TREATED_BURN_TRIO = (
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-12T00:00:00Z",
        "narrative": "Hotline report: clinic-treated burn from the thermostat.",
        "injury_class": "MEDICAL_TREATMENT",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-20T00:00:00Z",
        "narrative": "Hotline report: second clinic-treated burn on the same model.",
        "injury_class": "MEDICAL_TREATMENT",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-02-02T00:00:00Z",
        "narrative": "Hotline report: third clinic-treated burn, urgent care notes held.",
        "injury_class": "MEDICAL_TREATMENT",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
)

# Three verified medical-examiner fatalities: 50 x 1.50 each, so the severity
# sum is 225.00 on a model that only ever shipped 100 units.
FATAL_SHOCK_TRIO = (
    {
        "report_channel": "MEDICAL_EXAMINER",
        "incident_date": "2026-01-12T00:00:00Z",
        "narrative": "Fatal electrocution while the unit was plugged in, verified.",
        "injury_class": "FATALITY",
        "hazard_code": "ELECTRIC_SHOCK",
        "injury_verified": True,
    },
    {
        "report_channel": "MEDICAL_EXAMINER",
        "incident_date": "2026-01-22T00:00:00Z",
        "narrative": "Second fatal electrocution on the same housing fault, verified.",
        "injury_class": "FATALITY",
        "hazard_code": "ELECTRIC_SHOCK",
        "injury_verified": True,
    },
    {
        "report_channel": "MEDICAL_EXAMINER",
        "incident_date": "2026-02-02T00:00:00Z",
        "narrative": "Third fatal electrocution referred by the coroner, verified.",
        "injury_class": "FATALITY",
        "hazard_code": "ELECTRIC_SHOCK",
        "injury_verified": True,
    },
)

# Four first-aid reports whose hazard codes interleave, so the 2-2 tally tie is
# decided by which code the earliest-created report carries.
INTERLEAVED_TIE_REPORTS = (
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-05T00:00:00Z",
        "narrative": "Cut on the housing seam, dressed at home.",
        "injury_class": "FIRST_AID",
        "hazard_code": "LACERATION",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-06T00:00:00Z",
        "narrative": "Minor burn on the lever, cooled under a tap.",
        "injury_class": "FIRST_AID",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-07T00:00:00Z",
        "narrative": "Second seam cut, plaster applied.",
        "injury_class": "FIRST_AID",
        "hazard_code": "LACERATION",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-01-08T00:00:00Z",
        "narrative": "Second lever burn, no medical care sought.",
        "injury_class": "FIRST_AID",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
)

PERIOD_ONE = {
    "period_start": "2026-03-13T00:00:00Z",
    "period_end": "2026-04-12T00:00:00Z",
}

PERIOD_TWO = {
    "period_start": "2026-04-13T00:00:00Z",
    "period_end": "2026-05-13T00:00:00Z",
}

REFUND_CLAIM_PRICES = {"unit_price_cents": 4999, "shipping_cents_per_unit": 899}


def _dispose_incident(api, incident_id, **overrides):
    """Close one incident as a duplicate or as requiring no action."""
    return validate_success(
        api.dispose_incident(
            incident_id, f.dispose_payload(**overrides), headers=INTAKE_HEADERS
        )
    )


def _six_report_model_with_one_analysis(api):
    """Six reports on one model, of which only three may enter an analysis."""
    fx.set_clock(api, "2026-03-01T00:00:00Z")
    model = fx.create_product_model(
        api, model_code="TOAST-X1", units_distributed=100, units_registered=60
    )
    rows = {}
    rows["hospitalisation"] = fx.classified_incident(
        api,
        model["id"],
        report_channel="MEDICAL_EXAMINER",
        incident_date="2026-01-12T00:00:00Z",
        narrative="Qualifying: overnight admission for second-degree burns.",
        injury_class="HOSPITALIZATION",
        hazard_code="BURN",
        injury_verified=True,
    )
    rows["treatment"] = fx.classified_incident(
        api,
        model["id"],
        report_channel="RETAILER",
        incident_date="2026-01-20T00:00:00Z",
        narrative="Qualifying: store return, consumer treated at urgent care.",
        injury_class="MEDICAL_TREATMENT",
        hazard_code="BURN",
        injury_verified=True,
    )
    rows["first_aid"] = fx.classified_incident(
        api,
        model["id"],
        report_channel="CONSUMER_HOTLINE",
        incident_date="2026-02-02T00:00:00Z",
        narrative="Qualifying: minor burn to thumb, treated at home.",
        injury_class="FIRST_AID",
        hazard_code="BURN",
        injury_verified=True,
    )
    # Never triaged, so it is neither CLASSIFIED, CLUSTERED nor ESCALATED.
    rows["untriaged"] = fx.create_incident(
        api,
        model["id"],
        report_channel="MEDICAL_EXAMINER",
        incident_date="2026-02-05T00:00:00Z",
        narrative="Excluded: still awaiting triage; would weigh 30.00 if counted.",
    )
    closed = fx.classified_incident(
        api,
        model["id"],
        report_channel="MEDICAL_EXAMINER",
        incident_date="2026-02-06T00:00:00Z",
        narrative="Excluded: closed with no action after investigation.",
        injury_class="HOSPITALIZATION",
        hazard_code="BURN",
        injury_verified=True,
    )
    rows["closed"] = _dispose_incident(
        api, closed["id"], disposition="CLOSED_NO_ACTION"
    )
    duplicate = fx.classified_incident(
        api,
        model["id"],
        report_channel="MEDICAL_EXAMINER",
        incident_date="2026-02-07T00:00:00Z",
        narrative="Excluded: duplicate retelling of the January hospitalisation.",
        injury_class="HOSPITALIZATION",
        hazard_code="BURN",
        injury_verified=True,
    )
    rows["duplicate"] = _dispose_incident(
        api,
        duplicate["id"],
        disposition="MERGED_DUPLICATE",
        duplicate_of_incident_id=rows["hospitalisation"]["id"],
    )
    rows["out_of_window"] = fx.classified_incident(
        api,
        model["id"],
        report_channel="MEDICAL_EXAMINER",
        incident_date="2025-12-20T00:00:00Z",
        narrative="Excluded: classified but dated before the window opens.",
        injury_class="HOSPITALIZATION",
        hazard_code="BURN",
        injury_verified=True,
    )
    model = fx.get_product_model(api, model["id"])
    pattern = fx.create_pattern(
        api,
        model["id"],
        model["version"],
        analysis_basis="PRELIMINARY",
        **ANALYSIS_WINDOW,
    )
    return model, rows, pattern


def _interleaved_tie_analysis(api):
    """Four reports created an hour apart, alternating two hazard codes."""
    fx.set_clock(api, "2026-03-01T00:00:00Z")
    model = fx.create_product_model(
        api, model_code="TOAST-TIE", units_distributed=100, units_registered=50
    )
    rows = []
    for hour, spec in enumerate(INTERLEAVED_TIE_REPORTS):
        fx.set_clock(api, f"2026-03-01T{hour:02d}:00:00Z")
        rows.append(fx.classified_incident(api, model["id"], **spec))
    model = fx.get_product_model(api, model["id"])
    pattern = fx.create_pattern(
        api,
        model["id"],
        model["version"],
        analysis_basis="PRELIMINARY",
        **ANALYSIS_WINDOW,
    )
    return model, rows, pattern


def _thirteen_violation_penalty_case(api):
    """A report filed exactly on time, carrying a 13-violation penalty docket."""
    return fx.penalty_case_on_report_env(
        api,
        violation_count=13,
        model={
            "model_code": "TOAST-TIER",
            "units_distributed": 100,
            "units_registered": 60,
        },
        incidents=TREATED_BURN_TRIO,
        submit_clock="2026-03-11T00:00:00Z",
    )


class TestIncidentSeverityWeight:
    """One probe per injury class, each paired with a different intake channel."""

    def test_verified_reports_multiply_the_injury_base_by_the_channel_credibility(
        self, api
    ):
        """Three verified reports separate the injury base from the channel factor.

        The contract states: "Each injury class carries an injury base weight: 1
        for `NO_INJURY`, 3 for `FIRST_AID`, 8 for `MEDICAL_TREATMENT`, 20 for
        `HOSPITALIZATION` and 50 for `FATALITY`." It also states: "Each intake
        channel carries a credibility multiplier reflecting how much the office
        trusts the source: a report arriving through `CONSUMER_HOTLINE` or
        `WEB_FORM` is multiplied by 1.00, one arriving through a `RETAILER` by
        1.20, and one arriving from a `MEDICAL_EXAMINER` by 1.50."

        Design: Corner/calculations/severity_weight_spans_all_five_injury_classes_and_all_four_channels
        """
        fx.set_clock(api, "2026-03-01T00:00:00Z")
        model = fx.create_product_model(
            api, model_code="TOAST-X1", units_distributed=100, units_registered=60
        )

        hotline_first_aid = fx.classified_incident(
            api,
            model["id"],
            report_channel="CONSUMER_HOTLINE",
            incident_date="2026-01-06T00:00:00Z",
            narrative="Thumb burn treated with a plaster at home.",
            injury_class="FIRST_AID",
            hazard_code="BURN",
            injury_verified=True,
        )
        retailer_treatment = fx.classified_incident(
            api,
            model["id"],
            report_channel="RETAILER",
            incident_date="2026-01-07T00:00:00Z",
            narrative="Store escalation: customer treated at a walk-in clinic.",
            injury_class="MEDICAL_TREATMENT",
            hazard_code="BURN",
            injury_verified=True,
        )
        examiner_hospitalisation = fx.classified_incident(
            api,
            model["id"],
            report_channel="MEDICAL_EXAMINER",
            incident_date="2026-01-08T00:00:00Z",
            narrative="Overnight admission for second-degree burns.",
            injury_class="HOSPITALIZATION",
            hazard_code="BURN",
            injury_verified=True,
        )

        # 3 x 1.00, 8 x 1.20 and 20 x 1.50, each rounded to two places.
        assert_decimal_equals(hotline_first_aid["severity_weight"], "3.00")
        assert_decimal_equals(retailer_treatment["severity_weight"], "9.60")
        assert_decimal_equals(examiner_hospitalisation["severity_weight"], "30.00")

        for row in (hotline_first_aid, retailer_treatment, examiner_hospitalisation):
            assert_field_values(row, status="CLASSIFIED", injury_verified=True)

    def test_an_unverified_report_counts_for_exactly_half_of_the_same_product(
        self, api
    ):
        """The unverified discount halves the channel-weighted product.

        The contract states: "The injury base weight is multiplied by the
        credibility multiplier of the channel fixed at intake; then, if
        `injury_verified` is false, that product is halved — an unverified claim
        counts for exactly half."

        Design: Corner/calculations/severity_weight_spans_all_five_injury_classes_and_all_four_channels
        """
        fx.set_clock(api, "2026-03-01T00:00:00Z")
        model = fx.create_product_model(
            api, model_code="TOAST-X1", units_distributed=100, units_registered=60
        )

        unverified_web_no_injury = fx.classified_incident(
            api,
            model["id"],
            report_channel="WEB_FORM",
            incident_date="2026-01-05T00:00:00Z",
            narrative="Web form: smell of burning, nobody hurt, nothing corroborated.",
            injury_class="NO_INJURY",
            hazard_code="BURN",
            injury_verified=False,
        )
        unverified_fatality = fx.classified_incident(
            api,
            model["id"],
            report_channel="MEDICAL_EXAMINER",
            incident_date="2026-01-09T00:00:00Z",
            narrative="Fatality reported second-hand; causation not yet verified.",
            injury_class="FATALITY",
            hazard_code="BURN",
            injury_verified=False,
        )
        verified_fatality = fx.classified_incident(
            api,
            model["id"],
            report_channel="MEDICAL_EXAMINER",
            incident_date="2026-01-10T00:00:00Z",
            narrative="Fatality corroborated by the medical examiner's report.",
            injury_class="FATALITY",
            hazard_code="BURN",
            injury_verified=True,
        )

        # 1 x 1.00 halved, 50 x 1.50 halved, and the same 50 x 1.50 undiscounted.
        assert_decimal_equals(unverified_web_no_injury["severity_weight"], "0.50")
        assert_decimal_equals(unverified_fatality["severity_weight"], "37.50")
        assert_decimal_equals(verified_fatality["severity_weight"], "75.00")


class TestRiskIndexQualifyingInputSet:
    """Six reports on one model, of which only three may enter the analysis."""

    def test_only_triaged_undisposed_in_window_reports_reach_the_snapshot(self, api):
        """Three of six reports qualify, so the severity sum is 42.60 not 162.60.

        The contract states: "The analysis considers incidents whose
        `product_model_id` equals the pattern's, whose `incident_date` falls
        inside the closed window from `window_start` through `window_end` with
        both endpoints inclusive, whose `status` is one of `CLASSIFIED`,
        `CLUSTERED` or `ESCALATED`, and whose `duplicate_of_incident_id` is
        null."

        Design: Corner/calculations/risk_index_input_set_excludes_untriaged_disposed_and_out_of_window_rows
        """
        _model, _rows, pattern = _six_report_model_with_one_analysis(api)

        assert_field_values(
            pattern,
            incident_count=3,
            dominant_hazard_code="BURN",
            pattern_confirmed=True,
        )
        # 30.00 + 9.60 + 3.00; the three excluded classified rows would add 90.00.
        assert_decimal_equals(pattern["severity_sum"], "42.60")
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        assert_decimal_equals(pattern["exposure_per_10k"], "1.0000", places=4)
        assert_decimal_equals(pattern["risk_index"], "63.90")

    def test_the_excluded_reports_are_not_clustered_onto_the_new_pattern(self, api):
        """Only the qualifying rows are re-pointed at the analysis.

        The contract states: "A report with a non-null
        `duplicate_of_incident_id` is permanently excluded from every
        hazard-pattern input set, as are `INTAKE` reports that were never
        classified and `CLOSED_NO_ACTION` reports." It also states: "Every
        qualifying incident that was `CLASSIFIED` is flipped to `CLUSTERED` with
        its `hazard_pattern_id` set to the new pattern, processed in
        `created_at` ascending order".

        Design: Corner/calculations/risk_index_input_set_excludes_untriaged_disposed_and_out_of_window_rows
        """
        _model, rows, pattern = _six_report_model_with_one_analysis(api)

        for key in ("hospitalisation", "treatment", "first_aid"):
            clustered = fx.get_incident(api, rows[key]["id"])
            assert_field_values(
                clustered, status="CLUSTERED", hazard_pattern_id=pattern["id"]
            )

        untriaged = fx.get_incident(api, rows["untriaged"]["id"])
        assert_field_values(untriaged, status="INTAKE")
        assert_fields_null(untriaged, "hazard_pattern_id", "injury_class")

        closed = fx.get_incident(api, rows["closed"]["id"])
        assert_field_values(closed, status="CLOSED_NO_ACTION")
        assert_fields_null(closed, "hazard_pattern_id")

        duplicate = fx.get_incident(api, rows["duplicate"]["id"])
        assert_field_values(
            duplicate,
            status="MERGED_DUPLICATE",
            duplicate_of_incident_id=rows["hospitalisation"]["id"],
        )
        assert_fields_null(duplicate, "hazard_pattern_id")

        out_of_window = fx.get_incident(api, rows["out_of_window"]["id"])
        assert_field_values(out_of_window, status="CLASSIFIED")
        assert_fields_null(out_of_window, "hazard_pattern_id")


class TestRiskIndexRoundingSchedule:
    """Two rounding points only: the exposure normaliser and the final index."""

    def test_the_density_is_not_pre_rounded_before_the_concentration_factor(
        self, api
    ):
        """A 17,777-unit run rounds up to 35.95, which pre-rounding cannot reach.

        The contract states: "`exposure_per_10k` normalises the model's
        distribution volume: it is the model's `units_distributed` divided by
        10,000, but never allowed below a floor of 1.0, and the result is rounded
        half up to 4 decimal places". It also states: "Neither the density nor
        the raw index is rounded on the way through; the raw index is capped at
        a ceiling of 100, and only then is the result rounded half up to 2
        decimal places and stored as `risk_index`, which therefore always lies
        between 0.00 and 100.00."

        Design: Corner/calculations/risk_index_keeps_four_places_on_exposure_and_never_rounds_the_density
        """
        env = fx.analyzed_pattern_env(
            api,
            model={
                "model_code": "TOAST-A",
                "units_distributed": 17777,
                "units_registered": 900,
            },
        )
        pattern = env["pattern"]

        assert_field_values(
            pattern,
            incident_count=3,
            dominant_hazard_code="BURN",
            pattern_confirmed=True,
        )
        assert_decimal_equals(pattern["exposure_per_10k"], "1.7777", places=4)
        assert_decimal_equals(pattern["severity_sum"], "42.60")
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        # 42.60 / 1.7777 = 23.96354840..., x 1.5 = 35.94532260..., so 35.95.
        assert_decimal_equals(pattern["risk_index"], "35.95")

    def test_the_same_chain_rounds_the_index_down_on_a_larger_run(self, api):
        """A 33,333-unit run lands on 19.17, so the mode is half up, not truncation.

        The contract states: "Unless a rule below says otherwise, every derived
        decimal figure is rounded **half up**." It also states: "Neither the
        density nor the raw index is rounded on the way through; the raw index is
        capped at a ceiling of 100, and only then is the result rounded half up
        to 2 decimal places and stored as `risk_index`, which therefore always
        lies between 0.00 and 100.00."

        Design: Corner/calculations/risk_index_keeps_four_places_on_exposure_and_never_rounds_the_density
        """
        env = fx.analyzed_pattern_env(
            api,
            model={
                "model_code": "TOAST-B",
                "units_distributed": 33333,
                "units_registered": 900,
            },
        )
        pattern = env["pattern"]

        assert_decimal_equals(pattern["exposure_per_10k"], "3.3333", places=4)
        assert_decimal_equals(pattern["severity_sum"], "42.60")
        # 42.60 / 3.3333 = 12.78012780..., x 1.5 = 19.17019170..., so 19.17.
        assert_decimal_equals(pattern["risk_index"], "19.17")
        assert_field_values(pattern, incident_count=3, pattern_confirmed=True)


class TestExposureFloorAndIndexCeiling:
    """The two constants that only show themselves at the volume extremes."""

    def test_a_sub_ten_thousand_run_floors_the_exposure_normaliser_at_one(self, api):
        """7,777 units normalise to 1.0000, so the index is 63.90 and not 82.16.

        The contract states: "`exposure_per_10k` normalises the model's
        distribution volume: it is the model's `units_distributed` divided by
        10,000, but never allowed below a floor of 1.0, and the result is rounded
        half up to 4 decimal places — the floor exists so that a tiny production
        run does not divide by a fraction and explode the index."

        Design: Corner/calculations/exposure_floor_constant_rescues_a_low_volume_model_from_a_fractional_denominator
        """
        env = fx.analyzed_pattern_env(
            api,
            model={
                "model_code": "TOAST-L",
                "units_distributed": 7777,
                "units_registered": 400,
            },
        )
        pattern = env["pattern"]

        assert_decimal_equals(pattern["exposure_per_10k"], "1.0000", places=4)
        assert_decimal_equals(pattern["severity_sum"], "42.60")
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        # 42.60 / 1.0000 x 1.5 = 63.90; an unfloored 0.7777 would give 82.16.
        assert_decimal_equals(pattern["risk_index"], "63.90")
        assert_field_values(pattern, incident_count=3, pattern_confirmed=True)

    def test_a_fatality_cluster_is_clamped_to_the_index_ceiling_not_rescaled(
        self, api
    ):
        """A raw index of 337.50 is replaced by exactly 100.00.

        The contract states: "Neither the density nor the raw index is rounded on
        the way through; the raw index is capped at a ceiling of 100, and only
        then is the result rounded half up to 2 decimal places and stored as
        `risk_index`, which therefore always lies between 0.00 and 100.00."

        Design: Corner/calculations/exposure_floor_constant_rescues_a_low_volume_model_from_a_fractional_denominator
        """
        env = fx.analyzed_pattern_env(
            api,
            model={
                "model_code": "TOAST-H",
                "units_distributed": 100,
                "units_registered": 40,
            },
            incidents=FATAL_SHOCK_TRIO,
        )
        pattern = env["pattern"]

        for incident in env["incidents"]:
            assert_decimal_equals(incident["severity_weight"], "75.00")

        assert_decimal_equals(pattern["severity_sum"], "225.00")
        assert_decimal_equals(pattern["exposure_per_10k"], "1.0000", places=4)
        assert_decimal_equals(pattern["concentration_ratio"], "1.0000", places=4)
        # The raw index is 225.00 x 1.5 = 337.50, replaced outright by the ceiling.
        assert_decimal_equals(pattern["risk_index"], "100.00")
        assert_field_values(
            pattern,
            incident_count=3,
            dominant_hazard_code="ELECTRIC_SHOCK",
            pattern_confirmed=True,
        )


class TestModalHazardTieBreak:
    """A deliberate two-two tally tie between two interleaved hazard codes."""

    def test_a_two_two_tie_resolves_to_the_code_of_the_earliest_created_report(
        self, api
    ):
        """LACERATION wins the tie because its first report was recorded first.

        The contract states: "`dominant_hazard_code` is the modal `hazard_code`
        across the set; when two hazard codes tie on tally, the winner is the
        code carried by the earliest-created incident in the set, taking
        incidents in `created_at` ascending order and letting the first row win —
        never by `id`."

        Design: Corner/calculations/modal_hazard_tie_break_resolves_to_the_earliest_created_incident
        """
        _model, rows, pattern = _interleaved_tie_analysis(api)

        assert_created_at_ascending(rows)
        assert_field_values(rows[0], hazard_code="LACERATION")
        assert_field_values(rows[1], hazard_code="BURN")

        assert_field_values(
            pattern, incident_count=4, dominant_hazard_code="LACERATION"
        )
        assert_decimal_equals(pattern["severity_sum"], "12.00")
        # Two of four rows carry the dominant code.
        assert_decimal_equals(pattern["concentration_ratio"], "0.5000", places=4)
        # Density 12.00 x (0.5 + 0.5000) = 12.00.
        assert_decimal_equals(pattern["risk_index"], "12.00")

    def test_the_diluted_concentration_alone_makes_the_cluster_unconfirmable(
        self, api
    ):
        """A large, high-index cluster still fails on the concentration threshold.

        The contract states: "Finally `pattern_confirmed` is true only when all
        three of the following hold at once: `incident_count` is at least 3,
        `concentration_ratio` is at least 0.6000, and `risk_index` is at least
        10.00." It also states that a confirming adjudication "requires the
        pattern's stored `pattern_confirmed` to be true, and a pattern that
        failed any of the three confirmability thresholds is refused with
        `ERR_PATTERN_NOT_CONFIRMABLE` (HTTP 422)."

        Design: Corner/calculations/modal_hazard_tie_break_resolves_to_the_earliest_created_incident
        """
        _model, _rows, pattern = _interleaved_tie_analysis(api)

        # Four incidents and an index of 12.00 both clear their thresholds.
        assert_field_values(pattern, incident_count=4, pattern_confirmed=False)
        assert_decimal_equals(pattern["risk_index"], "12.00")
        assert_decimal_equals(pattern["concentration_ratio"], "0.5000", places=4)

        response = api.adjudicate_hazard_pattern(
            pattern["id"],
            f.adjudicate_payload(decision="CONFIRMED"),
            headers=OFFICER_HEADERS,
        )
        validate_error(response, "ERR_PATTERN_NOT_CONFIRMABLE", 422)

        assert_field_values(fx.get_pattern(api, pattern["id"]), pattern_status="ANALYZED")


class TestConsentAgreementTierEdges:
    """Both cooperation-credit tier edges probed from either side on one case."""

    def test_the_tier_one_upper_edge_and_the_tier_two_floor_are_exact(self, api):
        """4,999,999 is TIER_1 at ten percent and 5,000,000 is TIER_2 at fifteen.

        The contract states: "The cooperation credit tier is keyed on that
        **pre-credit** settlement base and never on the discounted total: when
        the base is below 5,000,000 cents the tier is `TIER_1` at ten percent;
        when the base is at least 5,000,000 and at most 12,000,000 cents the tier
        is `TIER_2` at fifteen percent; above 12,000,000 cents the tier is
        `TIER_3` at twenty percent." It also states: "The credit is the
        settlement base multiplied by the effective percentage, rounded half up
        to whole cents exactly once, and the total is the exact integer
        difference of the base minus the credit, so credit plus total always
        reconstructs the base."

        Design: Corner/calculations/consent_agreement_tier_edges_pinned_at_all_four_boundaries
        """
        env = _thirteen_violation_penalty_case(api)

        assert env["evaluation"]["report_due_at"].startswith("2026-03-11T00:00:00")
        assert_field_values(
            env["report"], status="SUBMITTED", days_late=0, late_surcharge_cents=0
        )

        case = env["case"]
        # 1,000,000 x 13 violations, severity 1.00 and lateness 1.00, under the cap.
        assert case["assessed_penalty_cents"] == 13000000
        assert_integer_cents(
            case, "assessed_penalty_cents", "consent_agreement_preview_cents"
        )
        # No standing offer, so the base is the assessment: TIER_3 credit 2,600,000.
        assert case["consent_agreement_preview_cents"] == 10400000

        below_the_floor = fx.make_offer(
            api, case["id"], 4999999, "AGENCY", case["version"]
        )
        # 4,999,999 x 0.10 = 499,999.9, rounded half up exactly once to 500,000.
        assert below_the_floor["consent_agreement_preview_cents"] == 4499999
        assert (
            4999999 - below_the_floor["consent_agreement_preview_cents"] == 500000
        ), "credit plus total must reconstruct the pre-credit base"
        assert_field_values(
            below_the_floor,
            status="OFFER_MADE",
            current_offer_round=1,
            current_offer_cents=4999999,
            current_offer_by="AGENCY",
        )

        on_the_floor = fx.make_offer(
            api, case["id"], 5000000, "RESPONDENT", below_the_floor["version"]
        )
        # 5,000,000 x 0.15 = 750,000 exactly.
        assert on_the_floor["consent_agreement_preview_cents"] == 4250000
        assert_field_values(
            on_the_floor,
            status="COUNTERED",
            current_offer_round=2,
            current_offer_cents=5000000,
        )
        assert_fields_null(
            on_the_floor,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )

    def test_the_tier_two_ceiling_is_inclusive_and_one_cent_more_is_tier_three(
        self, api
    ):
        """12,000,000 is still TIER_2 while 12,000,001 crosses into TIER_3.

        The contract states: "The edges are exact — 4,999,999 is `TIER_1`,
        5,000,000 is `TIER_2`, 12,000,000 is `TIER_2`, and 12,000,001 is
        `TIER_3`." It also states: "In the **preview** variant only
        `consent_agreement_preview_cents` is written and
        `cooperation_credit_tier`, `cooperation_credit_cents`,
        `consent_agreement_total_cents`, `compliance_program_required` and
        `reporting_obligation_months` are all left untouched at their null and
        zero values."

        Design: Corner/calculations/consent_agreement_tier_edges_pinned_at_all_four_boundaries
        """
        env = _thirteen_violation_penalty_case(api)
        case = env["case"]
        assert case["assessed_penalty_cents"] == 13000000

        on_the_ceiling = fx.make_offer(
            api, case["id"], 12000000, "AGENCY", case["version"]
        )
        # 12,000,000 x 0.15 = 1,800,000, still the middle tier.
        assert on_the_ceiling["consent_agreement_preview_cents"] == 10200000
        assert_field_values(
            on_the_ceiling, status="OFFER_MADE", current_offer_round=1
        )

        above_the_ceiling = fx.make_offer(
            api, case["id"], 12000001, "RESPONDENT", on_the_ceiling["version"]
        )
        # 12,000,001 x 0.20 = 2,400,000.2, rounded half up once to 2,400,000.
        assert above_the_ceiling["consent_agreement_preview_cents"] == 9600001
        assert (
            12000001 - above_the_ceiling["consent_agreement_preview_cents"] == 2400000
        ), "credit plus total must reconstruct the pre-credit base"
        assert_field_values(
            above_the_ceiling,
            status="COUNTERED",
            current_offer_round=2,
            cooperation_bonus_applied=False,
            compliance_program_required=False,
            reporting_obligation_months=0,
        )
        assert_fields_null(
            above_the_ceiling,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_reserve_conserved(above_the_ceiling)


class TestConsentPreviewVariantSelection:
    """The preview follows the standing offer; only acceptance writes anything."""

    def test_the_preview_rebases_onto_the_standing_offer_and_binds_nothing(self, api):
        """With no offer the preview keys on the assessment, then on the offer.

        The contract states: "In the **preview** variant the base is
        `current_offer_cents` when a standing offer exists and
        `assessed_penalty_cents` when none does." It also states: "In the
        **preview** variant only `consent_agreement_preview_cents` is written and
        `cooperation_credit_tier`, `cooperation_credit_cents`,
        `consent_agreement_total_cents`, `compliance_program_required` and
        `reporting_obligation_months` are all left untouched at their null and
        zero values."

        Design: Corner/calculations/consent_preview_rebases_on_the_standing_offer_but_only_acceptance_binds
        """
        env = _thirteen_violation_penalty_case(api)
        case = env["case"]

        # Opened with no offer: the base is the frozen 13,000,000 assessment,
        # which is above 12,000,000, so TIER_3 at twenty percent previews
        # 13,000,000 - 2,600,000.
        assert_field_values(
            case,
            status="ASSESSMENT_OPEN",
            assessed_penalty_cents=13000000,
            current_offer_round=0,
            reserved_cents=0,
            available_cents=13000000,
            cooperation_bonus_applied=False,
            compliance_program_required=False,
            reporting_obligation_months=0,
            consent_agreement_preview_cents=10400000,
        )
        assert_fields_null(
            case,
            "current_offer_cents",
            "current_offer_by",
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_reserve_conserved(case)

        offered = fx.make_offer(api, case["id"], 5000000, "AGENCY", case["version"])

        # The standing offer displaces the assessment as the base: 5,000,000 is
        # TIER_2 at fifteen percent, so the credit is 750,000.
        assert_field_values(
            offered,
            status="OFFER_MADE",
            assessed_penalty_cents=13000000,
            current_offer_cents=5000000,
            current_offer_by="AGENCY",
            current_offer_round=1,
            reserved_cents=5000000,
            available_cents=8000000,
            consent_agreement_preview_cents=4250000,
            compliance_program_required=False,
            reporting_obligation_months=0,
        )
        assert_fields_null(
            offered,
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
        )
        assert_reserve_conserved(offered)
        assert (
            offered["consent_agreement_preview_cents"]
            != case["consent_agreement_preview_cents"]
        ), "the preview must move when the standing offer changes the base"

        # A read-back proves nothing but the preview was persisted.
        assert_unchanged(
            case,
            fx.get_penalty_case(api, case["id"]),
            "assessed_penalty_cents",
            "cooperation_credit_tier",
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
            "compliance_program_required",
            "reporting_obligation_months",
        )

    def test_acceptance_binds_all_five_settlement_fields_at_the_previewed_figure(
        self, api
    ):
        """Accepting the 5,000,000 agency offer writes the tier, credit and total.

        The contract states: "In the **accepted** variant all five settlement
        fields are bound for good: `cooperation_credit_tier`,
        `cooperation_credit_cents` and `consent_agreement_total_cents` are
        written, `compliance_program_required` is set true when
        `consent_agreement_total_cents` has reached 5,000,000 cents and false
        otherwise, and `reporting_obligation_months` is set to 24 when the
        compliance programme is required and to 12 when it is not." It also
        states: "Acceptance also moves the reserve one last time, setting
        `reserved_cents` to `consent_agreement_total_cents` and `available_cents`
        to `assessed_penalty_cents` minus `consent_agreement_total_cents`,
        preserving the reserve identity in its final resting state."

        Design: Corner/calculations/consent_preview_rebases_on_the_standing_offer_but_only_acceptance_binds
        """
        env = _thirteen_violation_penalty_case(api)
        case = env["case"]

        offered = fx.make_offer(api, case["id"], 5000000, "AGENCY", case["version"])
        assert offered["consent_agreement_preview_cents"] == 4250000

        agreed = fx.resolve_offer(api, case["id"], "ACCEPTED")

        # The accepted base is the 5,000,000 offer: TIER_2, credit 750,000,
        # total 4,250,000, which is under 5,000,000 so no programme is required.
        assert_field_values(
            agreed,
            status="AGREED",
            assessed_penalty_cents=13000000,
            current_offer_cents=5000000,
            current_offer_by="AGENCY",
            cooperation_credit_tier="TIER_2",
            cooperation_credit_cents=750000,
            consent_agreement_total_cents=4250000,
            compliance_program_required=False,
            reporting_obligation_months=12,
            reserved_cents=4250000,
            available_cents=8750000,
        )
        assert (
            agreed["cooperation_credit_cents"]
            + agreed["consent_agreement_total_cents"]
            == 5000000
        ), "credit plus total must reconstruct the settlement base"
        assert (
            agreed["consent_agreement_total_cents"]
            == offered["consent_agreement_preview_cents"]
        ), "the bound total must land on the figure the preview advertised"
        assert_integer_cents(
            agreed,
            "cooperation_credit_cents",
            "consent_agreement_total_cents",
            "reserved_cents",
            "available_cents",
        )
        assert_reserve_conserved(agreed)


def _monitoring_recall_with_units_corrected(api, quantity):
    """A monitoring recall whose ledger stands at `quantity` of 100 units."""
    env = fx.monitoring_recall_env(api)
    env["claim"] = fx.fulfilled_claim(
        api,
        env["recall_id"],
        consumer_ref="CR-2001",
        remedy_type="REFUND",
        quantity=quantity,
        **REFUND_CLAIM_PRICES,
    )
    return env


class TestEffectivenessAssessmentBands:
    """The narrative band read off the rounded rate against a 30.00 percent goal."""

    def test_one_unit_short_of_half_the_goal_reads_critical(self, api):
        """Fourteen of a hundred units is 14.00 percent, under the 15.00 floor.

        The contract states: "Otherwise, when the rate is at least half of
        `participation_goal_pct` — that halved figure itself rounded half up to 2
        decimal places before the comparison — the `assessment` is
        `BELOW_TARGET`. Below that, the `assessment` is `CRITICAL`."

        Design: Corner/calculations/effectiveness_bands_pin_critical_and_the_exact_below_target_floor
        """
        env = _monitoring_recall_with_units_corrected(api, 14)

        recall = fx.get_recall(api, env["recall_id"])
        assert_decimal_equals(recall["participation_goal_pct"], "30.00")
        assert_field_values(
            recall, units_corrected=14, units_outstanding=86, effectiveness_flag="PENDING"
        )
        assert_unit_ledger_conserved(recall)

        fx.set_clock(api, "2026-04-13T00:00:00Z")
        report = fx.submitted_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **PERIOD_ONE,
        )

        # 14 x 100 / 100 = 14.00, and half of 30.00 rounds to 15.00.
        assert_decimal_equals(report["effectiveness_rate"], "14.00")
        assert_field_values(
            report,
            status="SUBMITTED",
            assessment="CRITICAL",
            units_corrected_in_period=14,
            cumulative_units_corrected=14,
        )

    def test_exactly_half_the_goal_reads_below_target_not_critical(self, api):
        """Fifteen of a hundred units lands on the floor, so the band is BELOW_TARGET.

        The contract states: "The narrative assessment attached to a filed
        progress report is derived from the rounded rate against the recall's
        goal, using non-strict comparisons so that a rate rounding up to exactly
        the goal counts as met."

        Design: Corner/calculations/effectiveness_bands_pin_critical_and_the_exact_below_target_floor
        """
        env = _monitoring_recall_with_units_corrected(api, 15)

        fx.set_clock(api, "2026-04-13T00:00:00Z")
        report = fx.submitted_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **PERIOD_ONE,
        )

        # 15 x 100 / 100 = 15.00, which is exactly half of the 30.00 goal.
        assert_decimal_equals(report["effectiveness_rate"], "15.00")
        assert_field_values(
            report,
            assessment="BELOW_TARGET",
            units_corrected_in_period=15,
            cumulative_units_corrected=15,
        )
        # Short of the goal, so the units-basis flag has still never reached MET.
        assert_field_values(
            fx.get_recall(api, env["recall_id"]), effectiveness_flag="PENDING"
        )

    def test_a_rate_standing_exactly_on_the_goal_reads_on_track(self, api):
        """Thirty of a hundred units meets the 30.00 goal on a non-strict test.

        The contract states: "When the rate is at least
        `participation_goal_pct`, the `assessment` is `ON_TRACK`."

        Design: Corner/calculations/effectiveness_bands_pin_critical_and_the_exact_below_target_floor
        """
        env = _monitoring_recall_with_units_corrected(api, 30)

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall, units_corrected=30, units_outstanding=70, effectiveness_flag="MET"
        )

        fx.set_clock(api, "2026-04-13T00:00:00Z")
        report = fx.submitted_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **PERIOD_ONE,
        )

        assert_decimal_equals(report["effectiveness_rate"], "30.00")
        assert_field_values(
            report,
            assessment="ON_TRACK",
            units_corrected_in_period=30,
            cumulative_units_corrected=30,
        )


def _mixed_claim_ledger(api):
    """A monitoring recall carrying one fulfilled, one voided and one approved claim."""
    env = fx.monitoring_recall_env(api)

    # Fulfilled inside the first period: the only claim that period may count.
    env["counted"] = fx.fulfilled_claim(
        api,
        env["recall_id"],
        consumer_ref="CR-3001",
        remedy_type="REFUND",
        quantity=14,
        **REFUND_CLAIM_PRICES,
    )

    # Fulfilled inside the first period as well, then voided a day later.
    fx.set_clock(api, "2026-03-20T00:00:00Z")
    voided = fx.fulfilled_claim(
        api,
        env["recall_id"],
        consumer_ref="CR-3002",
        remedy_type="REFUND",
        quantity=5,
        **REFUND_CLAIM_PRICES,
    )
    fx.set_clock(api, "2026-03-21T00:00:00Z")
    env["voided"] = fx.void_claim(api, voided["id"], reason="Consumer withdrew.")

    # Approved but never fulfilled, so it has no fulfilled_at at all.
    approved = fx.create_claim(
        api,
        env["recall_id"],
        consumer_ref="CR-3003",
        remedy_type="REFUND",
        quantity=50,
        **REFUND_CLAIM_PRICES,
    )
    env["approved"] = fx.approve_claim(api, approved["id"])
    return env


class TestProgressReportPeriodDelta:
    """The period delta counts only unvoided fulfilments inside the closed window."""

    def test_the_first_period_counts_the_fulfilled_claim_and_nothing_else(self, api):
        """A voided fulfilment and an approved claim both contribute zero units.

        The contract states: "`units_corrected_in_period` is the total `quantity`
        across this recall's claims that are in `status` `FULFILLED` and whose
        `fulfilled_at` falls inside the closed interval from `period_start`
        through `period_end`, both endpoints inclusive; claims that have been
        voided contribute nothing." It also states: "`cumulative_units_corrected`
        is a snapshot of the recall's `units_corrected` at the moment of filing."

        Design: Corner/calculations/progress_report_period_delta_counts_only_unvoided_fulfilments_inside_the_window
        """
        env = _mixed_claim_ledger(api)

        assert_field_values(env["voided"], status="VOID", quantity=5)
        assert_field_values(env["approved"], status="APPROVED", quantity=50)
        assert env["approved"]["fulfilled_at"] is None

        # The void compensated its own fulfilment exactly, so the ledger is back
        # to the 14 units of the single surviving fulfilment.
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, units_corrected=14, units_outstanding=86)
        assert_unit_ledger_conserved(recall)

        fx.set_clock(api, "2026-04-13T00:00:00Z")
        first = fx.submitted_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **PERIOD_ONE,
        )

        assert_field_values(
            first,
            status="SUBMITTED",
            units_corrected_in_period=14,
            cumulative_units_corrected=14,
            assessment="CRITICAL",
        )
        assert_decimal_equals(first["effectiveness_rate"], "14.00")
        # 19 fulfilled units fell inside the window before the void; 64 would be
        # the figure if the approved-only claim counted. Neither may show up.
        assert first["units_corrected_in_period"] == 14

    def test_the_second_period_counts_only_its_own_single_fulfilment(self, api):
        """A later one-unit fulfilment gives a period delta of 1 on a cumulative 15.

        The contract states: "The period and cumulative unit figures are reported
        for the record and do **not** feed the rate." It also states: "The rate
        always uses the recall's **cumulative** `units_corrected` as its numerator
        — never a period delta — multiplied by 100 and divided by a denominator
        chosen by the reporting basis, with the quotient rounded half up to 2
        decimal places."

        Design: Corner/calculations/progress_report_period_delta_counts_only_unvoided_fulfilments_inside_the_window
        """
        env = _mixed_claim_ledger(api)

        fx.set_clock(api, "2026-04-13T00:00:00Z")
        first = fx.submitted_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **PERIOD_ONE,
        )
        assert first["cumulative_units_corrected"] == 14

        fx.set_clock(api, "2026-04-20T00:00:00Z")
        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-3004",
            remedy_type="REFUND",
            quantity=1,
            **REFUND_CLAIM_PRICES,
        )

        fx.set_clock(api, "2026-05-14T00:00:00Z")
        second = fx.submitted_progress_report(
            api,
            env["recall_id"],
            effectiveness_basis="UNITS_BASIS",
            **PERIOD_TWO,
        )

        assert_field_values(
            second,
            units_corrected_in_period=1,
            cumulative_units_corrected=15,
            assessment="BELOW_TARGET",
        )
        # 15 x 100 / 100 = 15.00 from the cumulative figure, not from the delta.
        assert_decimal_equals(second["effectiveness_rate"], "15.00")
        assert (
            second["units_corrected_in_period"]
            != second["cumulative_units_corrected"]
        ), "the delta and the snapshot must be independently reported figures"

        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(
            recall,
            units_corrected=15,
            units_outstanding=85,
            effectiveness_flag="PENDING",
        )
        assert_unit_ledger_conserved(recall)
        # The earlier filing keeps its own frozen pair of unit figures.
        assert_unchanged(
            first,
            fx.get_progress_report(api, first["id"]),
            "units_corrected_in_period",
            "cumulative_units_corrected",
            "effectiveness_rate",
        )
