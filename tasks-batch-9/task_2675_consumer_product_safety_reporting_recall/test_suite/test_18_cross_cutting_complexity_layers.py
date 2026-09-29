"""Version pinning and the three-part confirmability gate, end to end."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field_values,
    assert_ids_equal,
    assert_reserve_conserved,
)
from test_helpers.test_users import COUNSEL_HEADERS, OFFICER_HEADERS

# The closed window the canonical burn cluster sits inside.
ANALYSIS_WINDOW = {
    "window_start": "2026-01-01T00:00:00Z",
    "window_end": "2026-02-28T00:00:00Z",
}

# Five incident dates inside that window, recorded in this order so that the
# earliest-created row is the one that breaks a tally tie.
CONCENTRATION_DATES = (
    "2026-01-11T00:00:00Z",
    "2026-01-12T00:00:00Z",
    "2026-01-13T00:00:00Z",
    "2026-02-14T00:00:00Z",
    "2026-02-15T00:00:00Z",
)

# Two hazard tallies over five otherwise identical reports. Three of five lands
# the concentration ratio exactly on the floor; two of five lands one tally short.
TALLY_AT_THE_MINIMUM = ("BURN", "BURN", "BURN", "LACERATION", "CHOKING")
TALLY_ONE_SHORT = ("BURN", "BURN", "LACERATION", "LACERATION", "CHOKING")

# The frozen assessment behind the canonical docket: 1,000,000 cents times four
# alleged violations, scaled by 1.25 for the hospitalisation and by 1.10 for two
# late days.
ASSESSED_PENALTY_CENTS = 5500000


def _hotline_reports(hazard_codes):
    """Five verified first-aid hotline reports carrying the given hazard codes."""
    return tuple(
        {
            "report_channel": "CONSUMER_HOTLINE",
            "incident_date": incident_date,
            "narrative": f"Hotline report number {number} on this model.",
            "injury_class": "FIRST_AID",
            "hazard_code": hazard_code,
            "injury_verified": True,
        }
        for number, (incident_date, hazard_code) in enumerate(
            zip(CONCENTRATION_DATES, hazard_codes), start=1
        )
    )


def _model_with_three_verified_burns(api):
    """A hundred-unit model still at version 1 carrying the canonical cluster."""
    fx.set_clock(api, "2026-03-01T00:00:00Z")
    model = fx.create_product_model(
        api, model_code="TOAST-X1", units_distributed=100, units_registered=60
    )
    incidents = [
        fx.classified_incident(api, model["id"], **spec)
        for spec in fx.CANONICAL_INCIDENTS
    ]
    return fx.get_product_model(api, model["id"]), incidents


def _patterns_on(api, model_id):
    """Every hazard pattern recorded against one product model, in order."""
    return validate_paginated(
        api.list_hazard_patterns({"product_model_id": model_id}, headers=OFFICER_HEADERS)
    )


class TestPatternCreationPinsTheProductModelVersion:
    """A second analysis must carry the version the first analysis left behind."""

    def test_a_second_analysis_pinning_the_pre_supersession_version_is_refused(
        self, api
    ):
        """The token that opened the first analysis is already stale for the second.

        The contract states: "Opening a hazard-pattern analysis requires a
        non-optional `expected_product_model_version` field in the request body,
        carrying the client's last observed `version` of the `ProductModel` named
        by `product_model_id`. If that value does not equal the model's current
        `version`, the request is rejected with `ERR_STALE_PRODUCT_MODEL_VERSION`
        (HTTP 412)." The token moves because "The product model's `version` is
        incremented by 1 — which is why the next analysis of the same model needs
        a fresh `expected_product_model_version`."

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_pattern_create_is_a_412
        """
        model, incidents = _model_with_three_verified_burns(api)
        assert_field_values(model, version=1, hazard_posture="MONITORED")

        first = fx.create_pattern(
            api, model["id"], model["version"], analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )
        assert_field_values(
            fx.get_product_model(api, model["id"]), version=2
        )

        response = api.create_hazard_pattern(
            f.hazard_pattern_payload(
                model["id"], model["version"], analysis_basis="FINAL",
                **ANALYSIS_WINDOW,
            ),
            headers=OFFICER_HEADERS,
        )
        validate_error(response, "ERR_STALE_PRODUCT_MODEL_VERSION", 412)

        rows, meta = _patterns_on(api, model["id"])
        assert meta["total_count"] == 1, meta
        assert_ids_equal(rows, [first["id"]])
        assert_field_values(fx.get_pattern(api, first["id"]), pattern_status="ANALYZED")
        assert_field_values(fx.get_product_model(api, model["id"]), version=2)
        for incident in incidents:
            assert_field_values(
                fx.get_incident(api, incident["id"]),
                status="CLUSTERED",
                hazard_pattern_id=first["id"],
            )

    def test_the_refreshed_token_is_accepted_and_repoints_the_whole_cluster(self, api):
        """With the current version pinned the analysis lands and supersedes the first.

        The contract states: "Every other hazard pattern on the same product model
        whose `pattern_status` is `ANALYZED` or `CONFIRMED` is flipped to
        `SUPERSEDED`." It also states: "a qualifying incident that was already
        `CLUSTERED` to an older pattern is re-pointed to the new one, staying in
        `CLUSTERED`."

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_pattern_create_is_a_412
        """
        model, incidents = _model_with_three_verified_burns(api)

        first = fx.create_pattern(
            api, model["id"], model["version"], analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )
        refreshed = fx.get_product_model(api, model["id"])
        second = fx.create_pattern(
            api, model["id"], refreshed["version"], analysis_basis="FINAL",
            **ANALYSIS_WINDOW,
        )

        assert_field_values(
            second,
            pattern_status="ANALYZED",
            analysis_basis="FINAL",
            incident_count=3,
            product_model_id=model["id"],
        )
        assert_field_values(fx.get_product_model(api, model["id"]), version=3)
        assert_field_values(
            fx.get_pattern(api, first["id"]), pattern_status="SUPERSEDED"
        )
        for incident in incidents:
            assert_field_values(
                fx.get_incident(api, incident["id"]),
                status="CLUSTERED",
                hazard_pattern_id=second["id"],
            )

        rows, meta = _patterns_on(api, model["id"])
        assert meta["total_count"] == 2, meta
        assert_ids_equal(rows, [first["id"], second["id"]])

    def test_omitting_the_model_version_token_is_a_malformed_request(self, api):
        """The pin is a required field, so an analysis without one never runs.

        The contract states: "Opening a hazard-pattern analysis requires a
        non-optional `expected_product_model_version` field in the request body,
        carrying the client's last observed `version` of the `ProductModel` named
        by `product_model_id`." The shape check "requires every non-optional field
        to be present and non-null", else `ERR_INVALID_REQUEST`.

        Design: Corner/cross_cutting_complexity_layers/stale_product_model_version_on_pattern_create_is_a_412
        """
        model, _incidents = _model_with_three_verified_burns(api)

        payload = f.hazard_pattern_payload(
            model["id"], model["version"], analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )
        payload.pop("expected_product_model_version")

        response = api.create_hazard_pattern(payload, headers=OFFICER_HEADERS)
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        rows, meta = _patterns_on(api, model["id"])
        assert rows == [], f"the malformed analysis was persisted anyway: {rows}"
        assert meta["total_count"] == 0, meta
        assert_field_values(fx.get_product_model(api, model["id"]), version=1)


class TestOfferPinsTheCivilPenaltyCaseVersion:
    """The counter-offer guard, its own error code and its place in the order."""

    def _case_with_a_standing_agency_offer(self, api):
        """A five-and-a-half-million-cent case with one agency offer on the table."""
        env = fx.penalty_case_env(api)
        assert_field_values(
            env["case"],
            status="ASSESSMENT_OPEN",
            version=1,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
            current_offer_round=0,
            cooperation_bonus_applied=False,
        )
        env["standing"] = fx.make_offer(
            api, env["case_id"], 5000000, "AGENCY", env["case"]["version"]
        )
        assert_field_values(
            env["standing"],
            status="OFFER_MADE",
            version=2,
            current_offer_round=1,
            current_offer_cents=5000000,
            current_offer_by="AGENCY",
            reserved_cents=5000000,
            available_cents=500000,
        )
        assert_reserve_conserved(env["standing"])
        return env

    def test_a_counter_pinning_the_pre_offer_case_version_is_refused(self, api):
        """The respondent read the case before the agency offer re-cut the reserve.

        The contract states: "Tabling a settlement offer on a civil penalty case
        requires a non-optional `expected_case_version` field in the request body,
        carrying the client's last observed `version` of that `CivilPenaltyCase`.
        If that value does not equal the case's current `version`, the request is
        rejected with `ERR_STALE_PENALTY_CASE_VERSION` (HTTP 412)." One of the two
        ways the token moves is that "a new offer supersedes the standing one and
        re-cuts the reserve".

        Design: Corner/cross_cutting_complexity_layers/stale_penalty_case_version_on_a_counter_offer_is_a_412
        """
        env = self._case_with_a_standing_agency_offer(api)

        response = api.create_offer(
            env["case_id"],
            f.offer_payload(4000000, "RESPONDENT", env["case"]["version"]),
            headers=COUNSEL_HEADERS,
        )
        validate_error(response, "ERR_STALE_PENALTY_CASE_VERSION", 412)

        after = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            after,
            status="OFFER_MADE",
            version=2,
            current_offer_round=1,
            current_offer_cents=5000000,
            current_offer_by="AGENCY",
            reserved_cents=5000000,
            available_cents=500000,
        )
        assert_reserve_conserved(after)

    def test_the_refreshed_counter_is_accepted_and_releases_the_agency_reserve(
        self, api
    ):
        """Re-read, re-pinned and re-fired, the same counter lands and frees the money.

        The contract states: "A `RESPONDENT` counter is not the office's own
        commitment, so it releases the agency reserve entirely: `reserved_cents`
        returns to 0 and `available_cents` returns to the full
        `assessed_penalty_cents`." The round counter "counts every offer entered
        into the record regardless of which side made it".

        Design: Corner/cross_cutting_complexity_layers/stale_penalty_case_version_on_a_counter_offer_is_a_412
        """
        env = self._case_with_a_standing_agency_offer(api)

        countered = fx.make_offer(
            api, env["case_id"], 4000000, "RESPONDENT", env["standing"]["version"]
        )

        assert_field_values(
            countered,
            status="COUNTERED",
            version=3,
            current_offer_round=2,
            current_offer_cents=4000000,
            current_offer_by="RESPONDENT",
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
            assessed_penalty_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_reserve_conserved(countered)

    def test_the_cooperation_bonus_cascade_moves_the_version_behind_the_client(
        self, api
    ):
        """A fulfilled remedy claim advances the case, staling a token nobody misused.

        The contract states: "Here there are two independent ways the case's
        version can move ahead of a client's read: a new offer supersedes the
        standing one and re-cuts the reserve, and the remedy-fulfilment cascade
        described in §2.11 can advance the case by setting
        `cooperation_bonus_applied`." That fourth link means "that case has
        `cooperation_bonus_applied` set to true, its non-binding settlement
        preview recomputed, and its `version` incremented by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_penalty_case_version_on_a_counter_offer_is_a_412
        """
        env = fx.penalty_case_env(api)
        assert_field_values(
            env["case"], version=1, status="ASSESSMENT_OPEN",
            cooperation_bonus_applied=False,
        )

        fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-8001",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=4999,
            shipping_cents_per_unit=899,
        )
        assert_field_values(
            fx.get_recall(api, env["recall_id"]),
            units_corrected=30,
            effectiveness_flag="MET",
        )
        cascaded = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            cascaded, version=2, status="ASSESSMENT_OPEN",
            cooperation_bonus_applied=True,
        )

        response = api.create_offer(
            env["case_id"],
            f.offer_payload(5000000, "AGENCY", env["case"]["version"]),
            headers=COUNSEL_HEADERS,
        )
        validate_error(response, "ERR_STALE_PENALTY_CASE_VERSION", 412)

        offered = fx.make_offer(
            api, env["case_id"], 5000000, "AGENCY", cascaded["version"]
        )
        assert_field_values(
            offered,
            status="OFFER_MADE",
            version=3,
            current_offer_round=1,
            current_offer_cents=5000000,
            cooperation_bonus_applied=True,
        )
        assert_reserve_conserved(offered)

    def test_a_stale_offer_from_the_wrong_state_reports_the_version_not_the_state(
        self, api
    ):
        """An agency offer that is both stale and mis-timed names the stale token.

        The contract states: "Because the version check precedes the state check,
        an offer that is both stale and fired from the wrong state reports the
        stale version." The state rule it outranks is that "an `AGENCY` offer is
        legal from `ASSESSMENT_OPEN` and from `COUNTERED`, while a `RESPONDENT`
        offer is legal only from `OFFER_MADE`, and a mismatch draws
        `ERR_PENALTY_CASE_STATE_INVALID`."

        Design: Corner/cross_cutting_complexity_layers/stale_penalty_case_version_on_a_counter_offer_is_a_412
        """
        env = self._case_with_a_standing_agency_offer(api)

        both_wrong = api.create_offer(
            env["case_id"],
            f.offer_payload(4500000, "AGENCY", env["case"]["version"]),
            headers=COUNSEL_HEADERS,
        )
        validate_error(both_wrong, "ERR_STALE_PENALTY_CASE_VERSION", 412)

        state_only = api.create_offer(
            env["case_id"],
            f.offer_payload(4500000, "AGENCY", env["standing"]["version"]),
            headers=COUNSEL_HEADERS,
        )
        validate_error(state_only, "ERR_PENALTY_CASE_STATE_INVALID", 409)

        after = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            after,
            status="OFFER_MADE",
            version=2,
            current_offer_round=1,
            current_offer_cents=5000000,
            current_offer_by="AGENCY",
        )
        assert_reserve_conserved(after)

    def test_omitting_the_case_version_token_is_a_malformed_request(self, api):
        """The pin is a required field, so an offer without one never reaches the case.

        The contract states: "Tabling a settlement offer on a civil penalty case
        requires a non-optional `expected_case_version` field in the request body,
        carrying the client's last observed `version` of that `CivilPenaltyCase`."
        The shape check "requires every non-optional field to be present and
        non-null", else `ERR_INVALID_REQUEST`.

        Design: Corner/cross_cutting_complexity_layers/stale_penalty_case_version_on_a_counter_offer_is_a_412
        """
        env = fx.penalty_case_env(api)

        payload = f.offer_payload(5000000, "AGENCY", env["case"]["version"])
        payload.pop("expected_case_version")

        response = api.create_offer(
            env["case_id"], payload, headers=COUNSEL_HEADERS
        )
        validate_error(response, "ERR_INVALID_REQUEST", 400)

        after = fx.get_penalty_case(api, env["case_id"])
        assert_field_values(
            after,
            status="ASSESSMENT_OPEN",
            version=1,
            current_offer_round=0,
            reserved_cents=0,
            available_cents=ASSESSED_PENALTY_CENTS,
        )
        assert_reserve_conserved(after)


class TestConfirmabilityConcentrationFloor:
    """Five identical reports; only the hazard tally decides confirmability."""

    def _two_patterns_differing_only_in_the_tally(self, api):
        """One model at exactly the concentration floor and one a single tally short."""
        at_the_minimum = fx.analyzed_pattern_env(
            api,
            model={
                "model_code": "TOAST-A5",
                "units_distributed": 100,
                "units_registered": 60,
            },
            incidents=_hotline_reports(TALLY_AT_THE_MINIMUM),
            analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )
        one_short = fx.analyzed_pattern_env(
            api,
            clock=None,
            model={
                "model_code": "TOAST-B5",
                "units_distributed": 100,
                "units_registered": 60,
            },
            incidents=_hotline_reports(TALLY_ONE_SHORT),
            analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )
        for env in (at_the_minimum, one_short):
            assert_field_values(env["pattern"], incident_count=5)
            assert_decimal_equals(env["pattern"]["severity_sum"], "15.00")
            assert_decimal_equals(
                env["pattern"]["exposure_per_10k"], "1.0000", places=4
            )
        return at_the_minimum, one_short

    def test_a_concentration_exactly_at_the_minimum_is_confirmable(self, api):
        """Three of five dominant reports is 0.6000, which clears the gate.

        The contract states: "Finally `pattern_confirmed` is true only when all
        three of the following hold at once: `incident_count` is at least 3,
        `concentration_ratio` is at least 0.6000, and `risk_index` is at least
        10.00. Each is a non-strict boundary — a ratio of exactly 0.6000 and an
        index of exactly 10.00 both qualify." Confirmation "requires the pattern's
        stored `pattern_confirmed` to be true".

        Design: Corner/cross_cutting_complexity_layers/confirmability_gate_accepts_a_concentration_of_exactly_the_minimum
        """
        at_the_minimum, _one_short = self._two_patterns_differing_only_in_the_tally(api)
        pattern = at_the_minimum["pattern"]

        assert_field_values(
            pattern,
            pattern_status="ANALYZED",
            incident_count=5,
            dominant_hazard_code="BURN",
            pattern_confirmed=True,
        )
        assert_decimal_equals(pattern["concentration_ratio"], "0.6000", places=4)
        assert_decimal_equals(pattern["risk_index"], "16.50")

        adjudicated = fx.adjudicate_pattern(
            api,
            at_the_minimum["pattern_id"],
            "CONFIRMED",
            note="Concentration exactly at the minimum.",
        )
        assert_field_values(adjudicated, pattern_status="CONFIRMED")
        assert_field_values(
            fx.get_pattern(api, at_the_minimum["pattern_id"]),
            pattern_status="CONFIRMED",
            pattern_confirmed=True,
        )

    def test_a_concentration_one_tally_below_the_minimum_is_refused(self, api):
        """Two of five dominant reports is 0.4000, and only that leg fails.

        The contract states: "`concentration_ratio` is the tally of the dominant
        code divided by `incident_count`, rounded half up to 4 decimal places." A
        pattern "that failed any of the three confirmability thresholds is refused
        with `ERR_PATTERN_NOT_CONFIRMABLE` (HTTP 422)". The tie is broken because
        "when two hazard codes tie on tally, the winner is the code carried by the
        earliest-created incident in the set, taking incidents in `created_at`
        ascending order and letting the first row win — never by `id`".

        Design: Corner/cross_cutting_complexity_layers/confirmability_gate_accepts_a_concentration_of_exactly_the_minimum
        """
        _at_the_minimum, one_short = self._two_patterns_differing_only_in_the_tally(api)
        pattern = one_short["pattern"]

        assert_field_values(
            pattern,
            pattern_status="ANALYZED",
            incident_count=5,
            dominant_hazard_code="BURN",
            pattern_confirmed=False,
        )
        assert_decimal_equals(pattern["concentration_ratio"], "0.4000", places=4)
        assert_decimal_equals(pattern["risk_index"], "13.50")

        response = api.adjudicate_hazard_pattern(
            one_short["pattern_id"],
            f.adjudicate_payload(
                decision="CONFIRMED", note="Concentration one tally short."
            ),
            headers=OFFICER_HEADERS,
        )
        validate_error(response, "ERR_PATTERN_NOT_CONFIRMABLE", 422)

        after = fx.get_pattern(api, one_short["pattern_id"])
        assert_field_values(
            after,
            pattern_status="ANALYZED",
            dominant_hazard_code="BURN",
            pattern_confirmed=False,
            incident_count=5,
        )
        assert_decimal_equals(after["concentration_ratio"], "0.4000", places=4)
