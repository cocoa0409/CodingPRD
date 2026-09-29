"""Error precedence pairs of the multi-dose adherence mail pharmacy API.

Each class holds one pair of validation rules that can hold on the very same
request. The first test of a pair makes both conditions true at once and pins the
error identifier that must come back; the remaining tests remove the higher rule's
condition and show the lower rule answering, which is what proves the first result
was an ordering result rather than a coincidence.
"""

from test_helpers import (
    ApiErrorId,
    adjudicate_payload,
    api_client,
    assert_cycle_state,
    assert_line_state,
    assert_roll_state,
    assert_total_count,
    decide_vacation,
    do_generate_roll,
    do_image_pouch,
    get_success_data,
    insulin_payload,
    line_by_prescription,
    metformin_payload,
    ops_headers,
    pharmacist_headers,
    pouch_by_index,
    pouch_image_payload,
    prescription_payload,
    read_cycle,
    read_lines,
    read_patient,
    read_pouches,
    read_prescription,
    read_roll,
    request_vacation,
    setup_draft_cycle,
    setup_packed_cycle,
    setup_synced_patient,
    technician_headers,
    vacation_exception_payload,
    validate_error,
    TECHNICIAN_ID,
    TECHNICIAN_ID_2,
)

CLOCK = "2026-08-10T00:00:00Z"


def _prednisolone_liquid(patient_id, days_supply_written=30, refills_authorized=3):
    """A non-packable evening liquid, last filled 2026-07-25 for 28 days."""
    return prescription_payload(
        patient_id,
        drug_name="Prednisolone",
        ndc="00054-3727-63",
        strength="15mg/5mL",
        form="LIQUID",
        copay_tier="GENERIC",
        dose_times=["EVENING"],
        quantity_per_dose=1,
        days_supply_written=days_supply_written,
        refills_authorized=refills_authorized,
        last_dispensed_date="2026-07-25",
        last_dispensed_days_supply=28,
    )


def _packed_roll_with_first_pouch_imaged():
    """A roll packed by tech-01 whose first pouch has already been imaged by tech-02."""
    scenario = setup_packed_cycle(
        clock=CLOCK,
        packer=TECHNICIAN_ID,
        cycle_start_date="2026-08-15",
        day_supply_days=28,
    )
    first_pouch = pouch_by_index(read_pouches(scenario.roll_id), 1)
    do_image_pouch(
        first_pouch["id"],
        detected_pill_count=1,
        image_confidence_pct=96,
        user_id=TECHNICIAN_ID_2,
    )
    return scenario


def _patient_whose_yearly_travel_allowance_is_spent():
    """A patient holding one pharmacist-approved travel exception on a one-per-year plan."""
    scenario = setup_synced_patient(
        clock=CLOCK,
        plan_overrides={"vacation_overrides_per_year": 1},
        synchronize=False,
    )
    scenario.vacation = request_vacation(
        scenario.patient_id,
        travel_start_date="2026-08-20",
        travel_end_date="2026-08-31",
        requested_extra_days=5,
    )
    scenario.vacation = decide_vacation(
        scenario.vacation["id"], "APPROVE_PHARMACIST", 5
    )
    return scenario


class TestImageAlreadyCapturedOutranksSegregationOfDuties:
    """A duplicate image by the packer reports the state error, not the compliance error."""

    def test_duplicate_image_by_the_packer_reports_the_already_captured_error(self):
        """A second image on an imaged pouch, sent by the packer, returns the duplicate-image error.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied. The single-pouch route takes `detected_pill_count` and `image_confidence_pct` (0 through 100) and applies three gates in order: the pouch's roll must have `verification_status` `PACKED`, otherwise `ERR_INVALID_ROLL_STATE`; the pouch's `verification_result` must still be `PENDING`, otherwise `ERR_IMAGE_ALREADY_CAPTURED`; and the caller's `X-User-ID` must not equal the roll's `packed_by_user_id`, otherwise `ERR_SEGREGATION_OF_DUTIES`.

        Design: Difficulty/priority_pair_validation_conflict/image_already_captured_outranks_segregation_of_duties
        """
        scenario = _packed_roll_with_first_pouch_imaged()
        first_pouch = pouch_by_index(read_pouches(scenario.roll_id), 1)
        roll_before = read_roll(scenario.roll_id)
        assert roll_before["packed_by_user_id"] == TECHNICIAN_ID

        response = api_client.capture_pouch_image(
            first_pouch["id"],
            pouch_image_payload(1, 96),
            technician_headers(TECHNICIAN_ID),
        )
        validate_error(response, ApiErrorId.IMAGE_ALREADY_CAPTURED)

        pouch_after = get_success_data(
            api_client.get_pouch(first_pouch["id"], ops_headers())
        )
        assert pouch_after["imaged_by_user_id"] == TECHNICIAN_ID_2
        assert pouch_after["verification_result"] == "MATCH"

        roll_after = read_roll(scenario.roll_id)
        assert_roll_state(roll_after, mismatch_pouch_count=0)
        assert roll_after["version"] == roll_before["version"]

    def test_packer_imaging_a_still_pending_pouch_reports_segregation_of_duties(self):
        """With no earlier image on the pouch, the packer's own image trips the two-person control.

        The user identified by `packed_by_user_id` may not capture a verification image for any pouch of that roll, whether through the single-pouch route or the whole-roll scanner route. Either attempt fails with `ERR_SEGREGATION_OF_DUTIES` and HTTP 409.

        Design: Difficulty/priority_pair_validation_conflict/image_already_captured_outranks_segregation_of_duties
        """
        scenario = _packed_roll_with_first_pouch_imaged()
        second_pouch = pouch_by_index(read_pouches(scenario.roll_id), 2)
        assert second_pouch["verification_result"] == "PENDING"

        response = api_client.capture_pouch_image(
            second_pouch["id"],
            pouch_image_payload(1, 96),
            technician_headers(TECHNICIAN_ID),
        )
        validate_error(response, ApiErrorId.SEGREGATION_OF_DUTIES)

        pouch_after = get_success_data(
            api_client.get_pouch(second_pouch["id"], ops_headers())
        )
        assert pouch_after["verification_result"] == "PENDING"
        assert pouch_after["imaged_by_user_id"] is None


class TestVacationWindowInvalidOutranksYearlyLimit:
    """A back-dated trip reports the window error even when the allowance is spent."""

    def test_back_dated_window_outranks_the_exhausted_yearly_allowance(self):
        """A travel request that is both back-dated and over the yearly allowance reports the window error.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied. The trip must be in the future and long enough to justify the request: `travel_start_date` must not be before the clock date, and the number of days from `travel_start_date` through `travel_end_date` counted inclusively must be at least `requested_extra_days`; otherwise `ERR_VACATION_WINDOW_INVALID`. The patient must also have an unused allowance: if `vacation_exceptions_used_this_year` is already greater than or equal to the plan's `vacation_overrides_per_year`, the request fails with `ERR_VACATION_LIMIT_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/vacation_window_invalid_outranks_yearly_override_limit
        """
        scenario = _patient_whose_yearly_travel_allowance_is_spent()
        assert read_patient(scenario.patient_id)["vacation_exceptions_used_this_year"] == 1

        response = api_client.create_vacation_exception(
            vacation_exception_payload(
                scenario.patient_id,
                travel_start_date="2026-08-05",
                travel_end_date="2026-08-31",
                requested_extra_days=5,
            ),
            ops_headers(),
        )
        validate_error(response, ApiErrorId.VACATION_WINDOW_INVALID)

        assert read_patient(scenario.patient_id)["vacation_exceptions_used_this_year"] == 1
        rows = assert_total_count(
            api_client.list_vacation_exceptions(
                ops_headers(), {"patient_id": scenario.patient_id, "limit": 100}
            ),
            1,
        )
        assert rows[0]["id"] == scenario.vacation["id"]

    def test_legal_future_window_surfaces_the_yearly_allowance_error(self):
        """With a legal future trip the spent yearly allowance is the rule that answers.

        The patient must also have an unused allowance: if `vacation_exceptions_used_this_year` is already greater than or equal to the plan's `vacation_overrides_per_year`, the request fails with `ERR_VACATION_LIMIT_EXCEEDED`. Both approvals raise the patient's `vacation_exceptions_used_this_year` by 1 and increment the patient's `version`.

        Design: Difficulty/priority_pair_validation_conflict/vacation_window_invalid_outranks_yearly_override_limit
        """
        scenario = _patient_whose_yearly_travel_allowance_is_spent()

        response = api_client.create_vacation_exception(
            vacation_exception_payload(
                scenario.patient_id,
                travel_start_date="2026-09-01",
                travel_end_date="2026-09-30",
                requested_extra_days=5,
            ),
            ops_headers(),
        )
        validate_error(response, ApiErrorId.VACATION_LIMIT_EXCEEDED)

        assert read_patient(scenario.patient_id)["vacation_exceptions_used_this_year"] == 1
        rows = assert_total_count(
            api_client.list_vacation_exceptions(
                ops_headers(), {"patient_id": scenario.patient_id, "limit": 100}
            ),
            1,
        )
        assert rows[0]["id"] == scenario.vacation["id"]


class TestNonPackableRouteOutranksDaySupplyAllowance:
    """Forcing a liquid into the pouch route answers before the day-supply breach."""

    def test_forced_pouch_route_outranks_the_day_supply_breach(self):
        """Forcing the over-supplied liquid into the pouch roll reports the routing error.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied. Every prescription named in `force_pouch_prescription_ids` must have `refrigerated` false, otherwise `ERR_COLD_CHAIN_NOT_PACKABLE`, and must have `packable` true, otherwise `ERR_NON_PACKABLE_IN_POUCH_ROUTE` — the refrigeration check is reported first when both hold. Lastly, once every line's figures have been computed, no line may have `days_supply_filled` greater than its `allowance_days`, otherwise `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE`; this check is evaluated across all lines before any line's state or any prescription is committed, so a single over-supplied line aborts the entire adjudication with nothing written.

        Design: Difficulty/priority_pair_validation_conflict/non_packable_route_outranks_day_supply_allowance
        """
        scenario = setup_draft_cycle(
            clock=CLOCK,
            prescriptions=[
                metformin_payload,
                lambda patient_id: _prednisolone_liquid(
                    patient_id, days_supply_written=10, refills_authorized=1
                ),
            ],
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )
        liquid = scenario.rx_named("Prednisolone")

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(force_pouch_prescription_ids=[liquid["id"]]),
        )
        validate_error(response, ApiErrorId.NON_PACKABLE_IN_POUCH_ROUTE)

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
        )
        for line in read_lines(scenario.cycle_id):
            assert_line_state(line, line_status="PLANNED")
            assert line["copay_cents"] == 0

    def test_unforced_adjudication_exposes_the_day_supply_error_underneath(self):
        """Without the force array the liquid's twenty-day allowance is the rule that answers.

        Start with the smallest of three values: the plan's `max_day_supply_days`; the prescription's `days_supply_written` multiplied by one more than its `refills_remaining`; and the cycle's `day_supply_days` plus the line's `bridge_days_applied` plus the cycle's `approved_vacation_extra_days`. Lastly, once every line's figures have been computed, no line may have `days_supply_filled` greater than its `allowance_days`, otherwise `ERR_DAY_SUPPLY_EXCEEDS_ALLOWANCE`; this check is evaluated across all lines before any line's state or any prescription is committed, so a single over-supplied line aborts the entire adjudication with nothing written.

        Design: Difficulty/priority_pair_validation_conflict/non_packable_route_outranks_day_supply_allowance
        """
        scenario = setup_draft_cycle(
            clock=CLOCK,
            prescriptions=[
                metformin_payload,
                lambda patient_id: _prednisolone_liquid(
                    patient_id, days_supply_written=10, refills_authorized=1
                ),
            ],
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )
        tablet = scenario.rx_named("Metformin ER")

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id, pharmacist_headers(), adjudicate_payload()
        )
        validate_error(response, ApiErrorId.DAY_SUPPLY_EXCEEDS_ALLOWANCE)

        cycle = read_cycle(scenario.cycle_id)
        assert_cycle_state(
            cycle, packaging_status="DRAFT", insurance_status="NOT_ADJUDICATED"
        )
        for line in read_lines(scenario.cycle_id):
            assert_line_state(line, line_status="PLANNED")
            assert line["copay_cents"] == 0
        assert read_prescription(tablet["id"])["refills_remaining"] == 3


class TestColdChainNotPackableOutranksNonPackableRoute:
    """A refrigerated pen in the force array answers before a merely non-packable liquid."""

    def _draft_cycle_spanning_three_routes(self):
        """A draft cycle carrying a pouch tablet, a refrigerated pen and a non-packable liquid."""
        return setup_draft_cycle(
            clock=CLOCK,
            prescriptions=[metformin_payload, insulin_payload, _prednisolone_liquid],
            cycle_start_date="2026-08-15",
            day_supply_days=28,
        )

    def test_refrigerated_force_outranks_the_non_packable_force(self):
        """Forcing a refrigerated pen and a liquid together reports the cold-chain error.

        Validation rules are evaluated in strict ascending priority order. The **first** rule whose condition holds returns its error immediately; no later rule is evaluated, and no state change is applied. Every prescription named in `force_pouch_prescription_ids` must have `refrigerated` false, otherwise `ERR_COLD_CHAIN_NOT_PACKABLE`, and must have `packable` true, otherwise `ERR_NON_PACKABLE_IN_POUCH_ROUTE` — the refrigeration check is reported first when both hold.

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_not_packable_outranks_non_packable_route
        """
        scenario = self._draft_cycle_spanning_three_routes()
        refrigerated = scenario.rx_named("Insulin glargine")
        liquid = scenario.rx_named("Prednisolone")

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(
                force_pouch_prescription_ids=[refrigerated["id"], liquid["id"]]
            ),
        )
        validate_error(response, ApiErrorId.COLD_CHAIN_NOT_PACKABLE)

        assert_cycle_state(
            read_cycle(scenario.cycle_id),
            packaging_status="DRAFT",
            insurance_status="NOT_ADJUDICATED",
        )

    def test_liquid_alone_in_the_force_array_reports_the_routing_error(self):
        """With the refrigerated identifier removed the routing rule is the one that answers.

        Every prescription named in `force_pouch_prescription_ids` must have `refrigerated` false, otherwise `ERR_COLD_CHAIN_NOT_PACKABLE`, and must have `packable` true, otherwise `ERR_NON_PACKABLE_IN_POUCH_ROUTE` — the refrigeration check is reported first when both hold. The system computes `packable` and the caller may not supply it: `packable` is true exactly when `form` is `TABLET` or `CAPSULE` **and** `refrigerated` is false.

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_not_packable_outranks_non_packable_route
        """
        scenario = self._draft_cycle_spanning_three_routes()
        liquid = scenario.rx_named("Prednisolone")

        response = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(force_pouch_prescription_ids=[liquid["id"]]),
        )
        validate_error(response, ApiErrorId.NON_PACKABLE_IN_POUCH_ROUTE)

        assert_cycle_state(
            read_cycle(scenario.cycle_id),
            packaging_status="DRAFT",
            insurance_status="NOT_ADJUDICATED",
        )

    def test_adjudication_without_the_force_array_routes_each_line_by_the_drug(self):
        """After both rejections the plain adjudication clears and routes every line by its drug.

        Each line's `packable_route` is determined by the prescription: `COLD_CHAIN` when `refrigerated` is true, `POUCH` when `refrigerated` is false and `packable` is true, and `LOOSE_SPLIT` otherwise — that is, a non-refrigerated item whose `form` is not `TABLET` or `CAPSULE`. Cold-chain and non-packable lines never contribute a pouch — they ship loose — so the roll's shape is a function of the pouch-routed subset alone.

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_not_packable_outranks_non_packable_route
        """
        scenario = self._draft_cycle_spanning_three_routes()
        refrigerated = scenario.rx_named("Insulin glargine")
        liquid = scenario.rx_named("Prednisolone")

        rejected_cold = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(
                force_pouch_prescription_ids=[refrigerated["id"], liquid["id"]]
            ),
        )
        validate_error(rejected_cold, ApiErrorId.COLD_CHAIN_NOT_PACKABLE)

        rejected_route = api_client.adjudicate_fill_cycle(
            scenario.cycle_id,
            pharmacist_headers(),
            adjudicate_payload(force_pouch_prescription_ids=[liquid["id"]]),
        )
        validate_error(rejected_route, ApiErrorId.NON_PACKABLE_IN_POUCH_ROUTE)

        cleared = get_success_data(
            api_client.adjudicate_fill_cycle(
                scenario.cycle_id, pharmacist_headers(), adjudicate_payload()
            )
        )
        assert_cycle_state(
            cleared,
            packaging_status="LINES_ADJUDICATED",
            insurance_status="CLEARED",
        )

        lines = read_lines(scenario.cycle_id)
        assert_line_state(
            line_by_prescription(lines, refrigerated["id"]), packable_route="COLD_CHAIN"
        )
        assert_line_state(
            line_by_prescription(lines, liquid["id"]), packable_route="LOOSE_SPLIT"
        )

        roll = do_generate_roll(scenario.cycle_id, TECHNICIAN_ID)
        assert roll["pouch_count"] == 28
