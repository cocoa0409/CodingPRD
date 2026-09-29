"""The error catalogue, exercised one distinguishable code at a time.

Each test drives the API to a single named failure and then shows what the
refusal did *not* do — no row appended, no counter moved, no state advanced —
before driving the same request home once the offending condition is repaired.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AMBIENT_OUT_OF_RANGE,
    ERR_CHALLENGE_NOT_REQUESTED,
    ERR_CUSTODY_NOT_APPLICABLE,
    ERR_CUSTODY_SEQUENCE_INVALID,
    ERR_DEVICE_MODALITY_MISMATCH,
    ERR_DEVICE_NOT_AVAILABLE,
    ERR_DEVICE_NOT_FOUND,
    ERR_DUPLICATE_IDENTIFIER,
    ERR_FILTER_SERIAL_REUSED,
    ERR_HOLD_NOT_FOUND,
    ERR_HOLD_STATE_INVALID,
    ERR_INDICATION_CONTEXT_MISMATCH,
    ERR_MAX_DOSE_EXCEEDED,
    ERR_MAX_REJECTION_ROUNDS_EXCEEDED,
    ERR_MISSING_EVENT_FIELDS,
    ERR_NO_ELIGIBLE_INTERPRETER,
    ERR_ORDER_NOT_FOUND,
    ERR_QUALITY_EVENT_NOT_FOUND,
    ERR_REPORT_NOT_FOUND,
    ERR_RUN_NOT_FOUND,
    ERR_RUN_STATE_INVALID,
    ERR_SELF_BIOLOGIC_CONTROL,
    ERR_STAFF_NOT_FOUND,
    ERR_TECH_NOT_QUALIFIED,
)
from test_helpers.assertions import (
    assert_2dp,
    assert_3dp,
    assert_envelope_meta,
    assert_instant,
    assert_page,
    assert_response_type,
    assert_version_is,
)
from test_helpers.constants import MORNING_CLOCK, UNKNOWN_UUID
from test_helpers.test_users import LAB_MANAGER, make_technologist_headers


class TestPathSegmentResolution:
    """Seven single-row reads, seven different not-found codes."""

    def test_each_unresolvable_path_segment_answers_with_its_own_code(self, api):
        """The same unknown identifier means something different on each route.

        PRD 2.9: "Requests whose URL contains more than one identifier are
        resolved strictly left to right, and the first identifier that fails to
        resolve determines the response."

        PRD 2.9: "**`{device_id}` resolves** — `ERR_DEVICE_NOT_FOUND` (404), on
        the single-device read, quality-event submission and return-to-service."
        and "**`{staff_id}` resolves** — `ERR_STAFF_NOT_FOUND` (404), on the
        single-staff read." and "**`{order_id}` resolves** —
        `ERR_ORDER_NOT_FOUND` (404), on every order route and every order
        sub-resource route." and "**`{hold_id}` resolves** —
        `ERR_HOLD_NOT_FOUND` (404), on hold attestation." and "**`{run_id}`
        resolves** — `ERR_RUN_NOT_FOUND` (404), on every challenge-run route."
        and "**`{report_id}` resolves** — `ERR_REPORT_NOT_FOUND` (404), on every
        interpretation-report route." and "**`{event_id}` resolves to a device
        quality record** — `ERR_QUALITY_EVENT_NOT_FOUND` (404), on the single
        quality-event read."

        Design: Corner/errors/each_path_id_segment_reports_its_own_not_found_error
        """
        fx.set_clock(api, MORNING_CLOCK)

        reads = (
            (api.get_device(UNKNOWN_UUID, LAB_MANAGER), ERR_DEVICE_NOT_FOUND),
            (api.get_staff(UNKNOWN_UUID, LAB_MANAGER), ERR_STAFF_NOT_FOUND),
            (api.get_test_order(UNKNOWN_UUID, LAB_MANAGER), ERR_ORDER_NOT_FOUND),
            (api.get_medication_hold(UNKNOWN_UUID, LAB_MANAGER), ERR_HOLD_NOT_FOUND),
            (api.get_challenge_run(UNKNOWN_UUID, LAB_MANAGER), ERR_RUN_NOT_FOUND),
            (
                api.get_interpretation_report(UNKNOWN_UUID, LAB_MANAGER),
                ERR_REPORT_NOT_FOUND,
            ),
            (
                api.get_quality_event(UNKNOWN_UUID, LAB_MANAGER),
                ERR_QUALITY_EVENT_NOT_FOUND,
            ),
        )

        for response, expected_error_id in reads:
            error = validate_error(response, expected_error_id)
            body = response.json()
            assert_envelope_meta(body)
            assert_response_type(body, "error")
            assert error["message"].strip() != ""


class TestQualityEventFieldSets:
    """One endpoint, five disjoint field sets, one code raised two ways."""

    def test_an_incomplete_set_and_a_foreign_field_are_both_refused(self, api):
        """Neither refusal appends a row, so the device is still brand new.

        PRD 3.2: "The remaining input fields are conditional on the type, and the
        conditional set must be both complete and exclusive: `VOLUME_CALIBRATION`
        requires `measured_volume_l`, `ambient_temp_c` and
        `barometric_pressure_kpa`; `LEAK_CHECK` requires `ambient_temp_c` and
        `barometric_pressure_kpa`; `BIOLOGIC_CONTROL` requires
        `subject_staff_id`, `measured_fev1_l` and `measured_fvc_l`;
        `FILTER_REPLACEMENT` requires `filter_serial`; and
        `HIGH_LEVEL_DISINFECT` requires `dwell_minutes`. Supplying a field that
        belongs to a different type, or omitting one the declared type needs,
        reports `ERR_MISSING_EVENT_FIELDS`."

        Design: Corner/errors/quality_event_field_sets_are_both_complete_and_exclusive
        """
        fx.set_clock(api, MORNING_CLOCK)
        tech = fx.register_technologist(api)
        tech_headers = make_technologist_headers(tech["id"])
        device = fx.register_device(api)

        incomplete = f.calibration_event_payload()
        del incomplete["barometric_pressure_kpa"]
        validate_error(
            api.create_quality_event(device["id"], incomplete, tech_headers),
            ERR_MISSING_EVENT_FIELDS,
        )

        validate_error(
            api.create_quality_event(
                device["id"],
                f.filter_replacement_event_payload("F-1001", dwell_minutes=25),
                tech_headers,
            ),
            ERR_MISSING_EVENT_FIELDS,
        )

        clean = fx.append_quality_event(
            api, device["id"], f.filter_replacement_event_payload("F-1001"), tech_headers
        )
        assert clean["outcome"] == "COMPLETE"

        _, meta = validate_paginated(
            api.list_quality_events(LAB_MANAGER, device_id=device["id"])
        )
        assert_page(meta, total_count=1, has_more=False)

        untouched = validate_success(api.get_device(device["id"], LAB_MANAGER))
        assert untouched["status"] == "NEW"


class TestAmbientDomainGuard:
    """The water-vapour table is total only over the accepted domain."""

    def test_both_ends_of_the_ambient_domain_are_inclusive_and_beyond_them_is_refused(
        self, api
    ):
        """28 degrees and 110.01 kPa fail; 20/80.00 and 27/110.00 are accepted.

        PRD 3.2: "Ambient temperature must be a whole number from 20 through 27
        inclusive and pressure must fall between 80.00 and 110.00 kilopascals
        inclusive; anything else is `ERR_AMBIENT_OUT_OF_RANGE`."

        PRD 3.2: "**Leak checks** are the simpler ritual: they record
        `ambient_temp_c` and `barometric_pressure_kpa` and nothing else, their
        `outcome` is always `COMPLETE` and their `failure_reason` always null, and
        no device field changes."

        Design: Corner/errors/ambient_conditions_outside_the_btps_domain_are_rejected
        """
        fx.set_clock(api, MORNING_CLOCK)
        tech = fx.register_technologist(api)
        tech_headers = make_technologist_headers(tech["id"])
        device = fx.register_device(api, "DLCO-1", "DLCO")

        validate_error(
            api.create_quality_event(
                device["id"],
                f.leak_check_event_payload(ambient_temp_c=28),
                tech_headers,
            ),
            ERR_AMBIENT_OUT_OF_RANGE,
        )
        validate_error(
            api.create_quality_event(
                device["id"],
                f.leak_check_event_payload(barometric_pressure_kpa=110.01),
                tech_headers,
            ),
            ERR_AMBIENT_OUT_OF_RANGE,
        )

        lower = fx.append_quality_event(
            api,
            device["id"],
            f.leak_check_event_payload(ambient_temp_c=20, barometric_pressure_kpa=80.00),
            tech_headers,
        )
        upper = fx.append_quality_event(
            api,
            device["id"],
            f.leak_check_event_payload(
                ambient_temp_c=27, barometric_pressure_kpa=110.00
            ),
            tech_headers,
        )
        for accepted in (lower, upper):
            assert accepted["outcome"] == "COMPLETE"
            assert accepted["failure_reason"] is None

        _, meta = validate_paginated(
            api.list_quality_events(LAB_MANAGER, device_id=device["id"])
        )
        assert_page(meta, total_count=2, has_more=False)


class TestNaturalKeyUniqueness:
    """Four registries share one uniqueness code; the filter serial has its own."""

    def test_the_four_natural_keys_collide_and_a_refitted_serial_is_its_own_refusal(
        self, api
    ):
        """The serial already on the device is refused; the same serial elsewhere is not.

        PRD 2.9: "**Natural-key uniqueness** — `ERR_DUPLICATE_IDENTIFIER` (409),
        on device registration (`device_code`), staff registration
        (`employee_code`), patient registration (`mrn`) and rescue-lot receipt
        (`lot_number`)."

        PRD 3.3: "**Filter replacement** carries a single input, `filter_serial`,
        the serial of the filter being fitted. It must not equal the device's
        `current_filter_serial`, because refitting the filter that is already
        installed is not a filter change; that reports
        `ERR_FILTER_SERIAL_REUSED`. A filter replacement always computes `outcome`
        `COMPLETE`, sets `current_filter_serial` to the supplied serial and resets
        `sessions_since_filter_change` to 0."

        Design: Corner/errors/natural_keys_are_unique_and_a_refitted_filter_is_not_a_change
        """
        fx.set_clock(api, MORNING_CLOCK)
        first_device = fx.register_device(api, "SPIRO-1")
        second_device = fx.register_device(api, "SPIRO-3")
        tech = fx.register_technologist(api)
        tech_headers = make_technologist_headers(tech["id"])
        fx.register_patient(api)
        fx.receive_rescue_lot(api)
        fx.append_quality_event(
            api,
            first_device["id"],
            f.filter_replacement_event_payload("F-1001"),
            tech_headers,
        )

        validate_error(
            api.create_device(f.device_payload("SPIRO-1"), LAB_MANAGER),
            ERR_DUPLICATE_IDENTIFIER,
        )
        validate_error(
            api.create_staff(
                f.technologist_payload(
                    employee_code="T-001",
                    full_name="Other Person",
                    credentialed_modalities=("SPIROMETRY",),
                ),
                LAB_MANAGER,
            ),
            ERR_DUPLICATE_IDENTIFIER,
        )
        validate_error(
            api.create_patient(f.patient_payload(), LAB_MANAGER),
            ERR_DUPLICATE_IDENTIFIER,
        )
        validate_error(
            api.create_rescue_lot(f.rescue_lot_payload(), LAB_MANAGER),
            ERR_DUPLICATE_IDENTIFIER,
        )

        validate_error(
            api.create_quality_event(
                first_device["id"],
                f.filter_replacement_event_payload("F-1001"),
                tech_headers,
            ),
            ERR_FILTER_SERIAL_REUSED,
        )

        elsewhere = fx.append_quality_event(
            api,
            second_device["id"],
            f.filter_replacement_event_payload("F-1001"),
            tech_headers,
        )
        assert elsewhere["outcome"] == "COMPLETE"

        unchanged = validate_success(api.get_device(first_device["id"], LAB_MANAGER))
        assert unchanged["current_filter_serial"] == "F-1001"
        assert unchanged["sessions_since_filter_change"] == 0


def _order_with_an_attested_hold(api):
    """A SABA hold instructed at 06:00 and attested WITHHELD, order back to READY."""
    lab = fx.build_lab(api, clock="2026-08-01T06:00:00Z")
    order = fx.draft_and_submit_order(
        api, lab.patient_id, lab.doc1, current_medication_classes=("SABA",)
    )
    hold = validate_success(
        api.create_medication_hold(
            order["id"], f.medication_hold_payload("SABA", order["version"]), lab.tech1
        ),
        expected_status=201,
    )
    attested = validate_success(
        api.attest_medication_hold(
            hold["id"], {"attestation_result": "WITHHELD"}, lab.tech1
        )
    )
    return lab, order, attested


class TestHoldAttestationIsTerminal:
    """An attested hold is finished with, so the endpoint is not idempotent."""

    def test_the_second_attestation_is_refused_and_recomputes_nothing(self, api):
        """The order's release instant and version are what the first call left.

        PRD 3.4: "The hold must still be `PENDING` — attesting an already-resolved
        hold reports `ERR_HOLD_STATE_INVALID` — and `attested_at` is stamped from
        the logical clock."

        Design: Corner/errors/attesting_the_same_hold_twice_is_rejected
        """
        lab, order, attested = _order_with_an_attested_hold(api)
        assert attested["status"] == "ATTESTED"

        ready = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert ready["status"] == "READY"
        assert_instant(ready["hold_release_at"], "2026-08-01T12:00:00Z")

        validate_error(
            api.attest_medication_hold(
                attested["id"], {"attestation_result": "TAKEN"}, lab.tech1
            ),
            ERR_HOLD_STATE_INVALID,
        )

        still_attested = validate_success(
            api.get_medication_hold(attested["id"], LAB_MANAGER)
        )
        assert still_attested["status"] == "ATTESTED"
        assert still_attested["attestation_result"] == "WITHHELD"

        unmoved = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert unmoved["status"] == "READY"
        assert_instant(unmoved["hold_release_at"], "2026-08-01T12:00:00Z")
        assert_version_is(unmoved, ready["version"])


class TestTerminatedChallengeRun:
    """An aborted run closes both of its write channels at once."""

    def test_stepping_or_aborting_an_aborted_run_is_refused_and_releases_nothing_twice(
        self, api
    ):
        """The undosed abort released its reservation exactly once.

        PRD 2.9: "**Challenge-run state admits the operation** —
        `ERR_RUN_STATE_INVALID` (409): both stepping and aborting require `ARMED`
        or `IN_PROGRESS`."

        PRD 3.7: "An abort with `current_step_index` still 0 means nothing was
        administered, so `rescue_doses_administered` stays 0, the lot's
        `doses_reserved` drops by 4 with `doses_remaining` untouched — a clean
        release of the whole reservation — and the study's `session_status` is
        left entirely alone, because the patient was never provoked."

        Design: Corner/errors/stepping_an_aborted_challenge_run_is_rejected
        """
        lab = fx.build_lab(api)
        lot = fx.receive_rescue_lot(api)
        session = fx.build_session_with_maneuvers(
            api,
            lab,
            indication_code="ASTHMA_DIAGNOSIS",
            challenge_type="METHACHOLINE",
        )
        run = fx.arm_challenge_run(api, session["id"], lot["id"], lab.tech1)

        aborted = validate_success(
            api.abort_challenge_run(
                run["id"],
                f.abort_challenge_run_payload(
                    "Patient reported chest tightness before the first dose."
                ),
                lab.tech1,
            )
        )
        assert aborted["status"] == "ABORTED_SAFETY"
        assert aborted["stop_reason"] == "TECHNOLOGIST_ABORT"

        validate_error(
            api.create_challenge_step(
                run["id"], f.challenge_step_payload(25, 2.300), lab.tech1
            ),
            ERR_RUN_STATE_INVALID,
        )
        validate_error(
            api.abort_challenge_run(
                run["id"],
                f.abort_challenge_run_payload("Second attempt at the same abort."),
                lab.tech1,
            ),
            ERR_RUN_STATE_INVALID,
        )

        settled = validate_success(api.get_challenge_run(run["id"], LAB_MANAGER))
        assert settled["status"] == "ABORTED_SAFETY"
        assert settled["current_step_index"] == 0
        assert settled["cumulative_dose_units"] == 0
        assert settled["rescue_doses_administered"] == 0

        released = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert released["doses_remaining"] == 10
        assert released["doses_reserved"] == 0
        assert released["status"] == "STOCKED"


class TestCoachingRoundCeiling:
    """The round ceiling is only reachable once the device is put back in service."""

    def test_the_soiled_device_masks_the_ceiling_until_the_hygiene_pair_is_repeated(
        self, api
    ):
        """Rung 28 answers first; only an available device exposes rung 29.

        PRD 2.9: "**The ladder is evaluated in ascending order and the first rule
        that is violated determines the entire response; no later rule is
        evaluated.**"

        PRD 2.9: "**Device state admits the operation** —
        `ERR_DEVICE_NOT_AVAILABLE` (409): study scheduling and maneuver appending
        require `AVAILABLE`; return-to-service requires `QUARANTINED`."

        PRD 3.6: "A grade of `D` or `F` rejects it: `rejection_round` increases by
        one and `session_status` becomes `REJECTED`, and the device is soiled
        **only** when the post-increment `rejection_round` has reached 2, because
        below that the patient is still at the instrument."

        PRD 3.6: "A rejected study reopens for another coaching round by appending
        a further maneuver, which returns `session_status` to `IN_PROGRESS`,
        provided `rejection_round` is still strictly below 2 and the device is
        `AVAILABLE`. Once `rejection_round` has reached 2 the cycle is closed and
        a further append reports `ERR_MAX_REJECTION_ROUNDS_EXCEEDED`."

        Design: Corner/errors/a_third_coaching_round_exceeds_the_rejection_ceiling
        """
        lab = fx.build_lab(api)
        session = fx.build_scheduled_session(api, lab)
        single_effort = f.maneuver_payload(
            3.100,
            2.300,
            pef_l_s=5.80,
            back_extrapolated_volume_ml=110,
            expiratory_time_s=15.5,
        )
        # The second round's effort ends early, so it is usable for FEV1 only and
        # never joins the acceptable count the grade ladder reads.
        early_stop = f.maneuver_payload(
            3.100,
            2.300,
            pef_l_s=5.80,
            back_extrapolated_volume_ml=110,
            expiratory_time_s=12.0,
        )

        fx.append_maneuver(api, session["id"], single_effort, lab.tech1)
        first_round = fx.finalize_quality(api, session["id"], lab.tech1)
        assert first_round["session_status"] == "REJECTED"
        assert first_round["quality_grade"] == "D"
        assert first_round["rejection_round"] == 1

        fx.append_maneuver(api, session["id"], early_stop, lab.tech1)
        second_round = fx.finalize_quality(api, session["id"], lab.tech1)
        assert second_round["session_status"] == "REJECTED"
        assert second_round["quality_grade"] == "D"
        assert second_round["rejection_round"] == 2

        soiled = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert soiled["status"] == "SOILED"

        validate_error(
            api.create_maneuver(session["id"], single_effort, lab.tech1),
            ERR_DEVICE_NOT_AVAILABLE,
        )

        fx.set_clock(api, "2026-08-03T09:40:00Z")
        fx.append_quality_event(
            api, lab.device_id, f.filter_replacement_event_payload("F-1002"), lab.tech1
        )
        fx.append_quality_event(
            api, lab.device_id, f.disinfection_event_payload(25), lab.tech1
        )
        restored = validate_success(api.get_device(lab.device_id, LAB_MANAGER))
        assert restored["status"] == "AVAILABLE"

        validate_error(
            api.create_maneuver(session["id"], single_effort, lab.tech1),
            ERR_MAX_REJECTION_ROUNDS_EXCEEDED,
        )

        closed = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert closed["session_status"] == "REJECTED"
        assert closed["rejection_round"] == 2


class TestIndicationContextAgreement:
    """The context guard fires at submission, not at creation."""

    def test_a_mismatched_indication_is_born_a_draft_and_refused_only_at_submit(self, api):
        """The refusal leaves a draft, not an indication-rejected order.

        PRD 3.4: "The **first gate is hard and administrative**:
        `indication_code` must belong to the order's `test_context`. A
        `test_context` of `DISABILITY_EVALUATION` admits only
        `DISABILITY_ASSESSMENT`; a `test_context` of `OCCUPATIONAL_SURVEILLANCE`
        admits only `OCCUPATIONAL_SURVEILLANCE_ANNUAL`; and a `test_context` of
        `ROUTINE_CLINICAL` admits `DYSPNEA_EVALUATION`, `ASTHMA_DIAGNOSIS`,
        `COPD_STAGING`, `PREOP_ASSESSMENT` or `RESTRICTIVE_DISEASE_EVALUATION`. A
        mismatch is `ERR_INDICATION_CONTEXT_MISMATCH` at HTTP 422 and nothing
        whatsoever is persisted — the order stays exactly as it was."

        PRD 3.4: "When `current_medication_classes` is the empty array there is
        nothing to withhold, so submission takes the order directly to `READY`
        with `hold_release_at` remaining null."

        Design: Corner/errors/indication_and_context_must_agree_at_submit_time
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)
        fx.publish_reference_equation(api)
        patient = fx.register_patient(api)

        order = fx.draft_order(
            api,
            patient["id"],
            roster.doc1,
            indication_code="DYSPNEA_EVALUATION",
            test_context="DISABILITY_EVALUATION",
        )
        assert order["status"] == "DRAFT"

        validate_error(
            api.submit_test_order(order["id"], roster.doc1, {}),
            ERR_INDICATION_CONTEXT_MISMATCH,
        )

        still_draft = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert still_draft["status"] == "DRAFT"
        assert still_draft["rejection_reason"] is None

        revised = validate_success(
            api.patch_test_order(
                order["id"], {"indication_code": "DISABILITY_ASSESSMENT"}, roster.doc1
            )
        )
        assert revised["indication_code"] == "DISABILITY_ASSESSMENT"

        submitted = validate_success(
            api.submit_test_order(order["id"], roster.doc1, {})
        )
        assert submitted["status"] == "READY"
        assert submitted["hold_release_at"] is None


def _a_spirometer_and_a_diffusion_bench(api):
    """Two instruments, two orders, and one technologist who may only spirometer."""
    fx.set_clock(api, MORNING_CLOCK)
    roster = fx.build_roster(api)
    limited = fx.register_technologist(
        api,
        employee_code="T-003",
        full_name="Tom Alvi",
        credentialed_modalities=("SPIROMETRY",),
    )
    limited_headers = make_technologist_headers(limited["id"])
    fx.publish_reference_equation(api, modality_scope=("SPIROMETRY", "DLCO"))
    spirometer = fx.register_device(api, "SPIRO-1", "SPIROMETRY")
    bench = fx.register_device(api, "DLCO-1", "DLCO")
    fx.run_daily_quality_program(
        api, spirometer["id"], roster.tech1, roster.bcs_id, filter_serial="F-1001"
    )
    fx.run_daily_quality_program(
        api,
        bench["id"],
        roster.tech1,
        roster.bcs_id,
        filter_serial="F-1002",
        leak_check=True,
    )
    patient = fx.register_patient(api)
    spirometry_only = fx.draft_and_submit_order(api, patient["id"], roster.doc1)
    both_modalities = fx.draft_and_submit_order(
        api,
        patient["id"],
        roster.doc1,
        requested_modalities=("SPIROMETRY", "DLCO"),
    )
    return roster, limited_headers, bench["id"], spirometry_only, both_modalities


class TestSchedulingModalityBeforeCredential:
    """Two gates one rung apart, put to a request that trips both at once."""

    def test_the_booking_error_is_reported_before_the_operators_credentials(self, api):
        """The instrument nobody asked for outranks the person who may not run it.

        PRD 2.9: "32. **Device modality was actually requested** —
        `ERR_DEVICE_MODALITY_MISMATCH` (422), on study scheduling."

        PRD 2.9: "33. **Acting technologist is qualified and current** —
        `ERR_TECH_NOT_QUALIFIED` (403), on study scheduling and maneuver
        appending."

        PRD 3.5: "The device's `modality` must be a member of the order's
        `requested_modalities`, since occupying a plethysmograph for a study that
        never asked for plethysmography is a booking error. The acting
        technologist's `credentialed_modalities` must contain the device's
        `modality` and their `competency_expires_on` must be on or after the
        current logical date."

        Design: Corner/errors/device_modality_and_technologist_credential_are_checked_in_that_order
        """
        roster, limited, bench_id, spirometry_only, both = _a_spirometer_and_a_diffusion_bench(
            api
        )
        start, end = "2026-08-03T09:00:00Z", "2026-08-03T09:30:00Z"

        validate_error(
            api.create_test_session(
                f.test_session_payload(spirometry_only["id"], bench_id, start, end),
                limited,
            ),
            ERR_DEVICE_MODALITY_MISMATCH,
        )
        validate_error(
            api.create_test_session(
                f.test_session_payload(spirometry_only["id"], bench_id, start, end),
                roster.tech1,
            ),
            ERR_DEVICE_MODALITY_MISMATCH,
        )
        validate_error(
            api.create_test_session(
                f.test_session_payload(both["id"], bench_id, start, end), limited
            ),
            ERR_TECH_NOT_QUALIFIED,
        )

        session = validate_success(
            api.create_test_session(
                f.test_session_payload(both["id"], bench_id, start, end), roster.tech1
            ),
            expected_status=201,
        )
        assert session["technologist_staff_id"] == roster.tech1_id
        assert session["session_status"] == "SCHEDULED"

        untouched = validate_success(
            api.get_test_order(spirometry_only["id"], LAB_MANAGER)
        )
        assert untouched["status"] == "READY"


class TestChallengeAgentMustMatchTheOrder:
    """An agent nobody ordered and a substituted agent share one refusal.

    Both misuses answer `ERR_CHALLENGE_NOT_REQUESTED`; the run only exists when
    the agent named equals the one the order asked for.
    """

    def test_an_unrequested_agent_and_a_substituted_agent_are_both_refused(self, api):
        """Neither refusal reserves a single dose from the rescue lot.

        PRD 3.7: "The order's `challenge_type` must be something other than
        `NONE` and the supplied `agent` must equal it, otherwise
        `ERR_CHALLENGE_NOT_REQUESTED`; a technologist may not provoke a patient
        with an agent nobody ordered, nor substitute one agent for another."

        PRD 3.7: "Finally it adds 4 to the lot's `doses_reserved` while leaving
        `doses_remaining` untouched, which is the reservation half of the ledger
        described in §2.11."

        Design: Corner/errors/challenge_arming_requires_the_agent_the_order_asked_for
        """
        lab = fx.build_lab(api)
        lot = fx.receive_rescue_lot(api)
        unprovoked = fx.build_session_with_maneuvers(api, lab)
        provoked = fx.build_session_with_maneuvers(
            api,
            lab,
            scheduled_start_at="2026-08-03T10:00:00Z",
            scheduled_end_at="2026-08-03T10:30:00Z",
            indication_code="ASTHMA_DIAGNOSIS",
            challenge_type="METHACHOLINE",
        )

        validate_error(
            api.create_challenge_run(
                unprovoked["id"],
                f.challenge_run_payload(lot["id"], agent="METHACHOLINE"),
                lab.tech1,
            ),
            ERR_CHALLENGE_NOT_REQUESTED,
        )
        validate_error(
            api.create_challenge_run(
                provoked["id"],
                f.challenge_run_payload(lot["id"], agent="MANNITOL"),
                lab.tech1,
            ),
            ERR_CHALLENGE_NOT_REQUESTED,
        )

        unreserved = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert unreserved["doses_reserved"] == 0
        assert unreserved["doses_remaining"] == 10

        run = validate_success(
            api.create_challenge_run(
                provoked["id"],
                f.challenge_run_payload(lot["id"], agent="METHACHOLINE"),
                lab.tech1,
            ),
            expected_status=201,
        )
        assert run["status"] == "ARMED"
        assert run["agent"] == "METHACHOLINE"

        reserved = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert reserved["doses_reserved"] == 4
        assert reserved["doses_remaining"] == 10

        _, meta = validate_paginated(
            api.list_challenge_runs(LAB_MANAGER, session_id=unprovoked["id"])
        )
        assert_page(meta, total_count=0, has_more=False)


def _a_run_four_steps_into_the_protocol(api):
    """A provocation run whose cumulative dose stands at 375 of 400 units."""
    lab = fx.build_lab(api)
    lot = fx.receive_rescue_lot(api)
    session = fx.build_session_with_maneuvers(
        api, lab, indication_code="ASTHMA_DIAGNOSIS", challenge_type="METHACHOLINE"
    )
    run = fx.arm_challenge_run(api, session["id"], lot["id"], lab.tech1)
    for dose, post_step_fev1 in ((25, 2.380), (50, 2.370), (100, 2.360), (200, 2.350)):
        fx.record_challenge_step(api, run["id"], dose, post_step_fev1, lab.tech1)
    return lab, lot, run


class TestDoseCeilingIsCheckedAgainstTheSum:
    """The ceiling reads the running total, so 26 units is illegal and 25 is not."""

    def test_the_refused_step_leaves_the_run_alive_and_the_legal_step_completes_it(
        self, api
    ):
        """Two steps differing by a single unit fall on opposite sides of 400.

        PRD 3.7: "Before anything is accumulated the server checks that
        `cumulative_dose_units` plus `dose_units` does not exceed the ceiling of
        400 units; the comparison is strict, so landing exactly on 400 is
        permitted and only overshooting it reports `ERR_MAX_DOSE_EXCEEDED`."

        PRD 3.7: "The step then captures its two interpolation anchors before
        mutating the totals: `last_step_dose_units` takes `cumulative_dose_units`
        as it stood before this step, which is 0 before the first step, and
        `last_step_drop_pct` takes the drop percent as it stood before this step —
        that is, the largest fall observed on earlier steps, which is 0 before the
        first step."

        PRD 3.7: "When instead the fall is below 20.00 percent and the post-step
        `cumulative_dose_units` has reached exactly 400, the patient has taken the
        full protocol without reacting: `status` becomes `COMPLETED_NEGATIVE` with
        `stop_reason` `MAX_CUMULATIVE_DOSE_REACHED` and `pc20_dose_units` stays
        null."

        Design: Corner/errors/a_step_that_would_cross_the_dose_ceiling_is_rejected
        """
        lab, lot, run = _a_run_four_steps_into_the_protocol(api)

        four_steps_in = validate_success(api.get_challenge_run(run["id"], LAB_MANAGER))
        assert_3dp(four_steps_in["cumulative_dose_units"], 375.000)
        assert four_steps_in["current_step_index"] == 4
        assert four_steps_in["status"] == "IN_PROGRESS"

        validate_error(
            api.create_challenge_step(
                run["id"], f.challenge_step_payload(26, 2.340), lab.tech1
            ),
            ERR_MAX_DOSE_EXCEEDED,
        )

        after_refusal = validate_success(api.get_challenge_run(run["id"], LAB_MANAGER))
        assert_3dp(after_refusal["cumulative_dose_units"], 375.000)
        assert after_refusal["current_step_index"] == 4
        assert after_refusal["status"] == "IN_PROGRESS"
        # Both anchors were captured before the fourth step mutated the totals.
        assert_3dp(after_refusal["last_step_dose_units"], 175.000)
        assert_2dp(after_refusal["last_step_drop_pct"], 1.67)
        assert_2dp(after_refusal["max_fev1_drop_pct"], 2.08)
        assert_version_is(after_refusal, four_steps_in["version"])

        completed = fx.record_challenge_step(api, run["id"], 25, 2.340, lab.tech1)
        assert_3dp(completed["cumulative_dose_units"], 400.000)
        assert completed["current_step_index"] == 5
        assert completed["status"] == "COMPLETED_NEGATIVE"
        assert completed["stop_reason"] == "MAX_CUMULATIVE_DOSE_REACHED"
        assert completed["pc20_dose_units"] is None

        spent = validate_success(api.get_rescue_lot(lot["id"], LAB_MANAGER))
        assert spent["doses_remaining"] == 6
        assert spent["doses_reserved"] == 0


class TestSelfBiologicControl:
    """The only fault in the refused measurement is who performed it."""

    def test_the_control_subject_may_not_measure_themselves_but_a_colleague_may(self, api):
        """The refusal is also what leaves the device without today's control.

        PRD 3.2: "The acting technologist's own identifier must differ from
        `subject_staff_id`, and the nominated subject must have
        `is_biologic_control` true with a non-null `baseline_fev1_l`; otherwise the
        submission is refused with `ERR_SELF_BIOLOGIC_CONTROL`."

        PRD 3.2: "It also promotes the device from `NEW` to `AVAILABLE` — but only
        from `NEW`."

        Design: Corner/errors/a_technologist_may_not_serve_as_their_own_biologic_control
        """
        fx.set_clock(api, MORNING_CLOCK)
        roster = fx.build_roster(api)
        device = fx.register_device(api)
        fx.append_quality_event(
            api, device["id"], f.calibration_event_payload(), roster.tech1
        )

        subject_headers = make_technologist_headers(roster.bcs_id)
        measurement = f.biologic_control_event_payload(roster.bcs_id)

        validate_error(
            api.create_quality_event(device["id"], measurement, subject_headers),
            ERR_SELF_BIOLOGIC_CONTROL,
        )

        uncontrolled = validate_success(api.get_device(device["id"], LAB_MANAGER))
        assert uncontrolled["last_biologic_control_date"] is None
        assert uncontrolled["status"] == "AVAILABLE"

        accepted = validate_success(
            api.create_quality_event(device["id"], measurement, roster.tech1),
            expected_status=201,
        )
        assert_2dp(accepted["deviation_pct"], 3.75)
        assert accepted["outcome"] == "PASS"

        controlled = validate_success(api.get_device(device["id"], LAB_MANAGER))
        assert controlled["last_biologic_control_date"] == "2026-08-03"


class TestCustodyScopeAndSequence:
    """One endpoint, three refusals, and only the fourth request appends a link."""

    def test_a_routine_study_admits_no_custody_event_and_the_chain_cannot_be_skipped(
        self, api
    ):
        """The legal identity check advances custody only, leaving the study scheduled.

        PRD 3.8: "A study whose `custody_status` is `NOT_APPLICABLE` accepts no
        custody events at all, reporting `ERR_CUSTODY_NOT_APPLICABLE`, and that
        value never changes for the life of the study."

        PRD 3.8: "`ID_VERIFIED` is accepted only from `CUSTODY_OPEN` and moves the
        study to `CUSTODY_ID_VERIFIED`; `SEAL_APPLIED` is accepted only from
        `CUSTODY_ID_VERIFIED` and moves it to `CUSTODY_SEALED`; and `SEAL_BROKEN`
        is accepted only from `CUSTODY_SEALED` and moves it to `CUSTODY_BROKEN`.
        Submitting one out of turn — sealing before verifying identity, verifying
        identity twice, or breaking a seal that was never applied — reports
        `ERR_CUSTODY_SEQUENCE_INVALID`."

        PRD 3.8: "`id_document_type` — one of `PHOTO_ID`, `PASSPORT` or
        `EMPLOYEE_BADGE` — is required when `event_type` is `ID_VERIFIED` and must
        be absent otherwise, and `seal_serial`, the tamper-evident seal serial, is
        required when `event_type` is `SEAL_APPLIED` or `SEAL_BROKEN` and must be
        absent otherwise."

        PRD 3.8: "`session_status` is untouched by custody activity, and
        `custody_status` is untouched by maneuvers, quality finalization and
        reporting, yet both share one optimistic-concurrency counter."

        Design: Corner/errors/custody_events_are_scoped_to_non_routine_contexts_and_strictly_sequenced
        """
        lab = fx.build_lab(api)
        routine = fx.build_scheduled_session(api, lab)
        disability = fx.build_scheduled_session(
            api,
            lab,
            scheduled_start_at="2026-08-03T10:00:00Z",
            scheduled_end_at="2026-08-03T10:30:00Z",
            indication_code="DISABILITY_ASSESSMENT",
            test_context="DISABILITY_EVALUATION",
        )
        assert routine["custody_status"] == "NOT_APPLICABLE"
        assert disability["custody_status"] == "CUSTODY_OPEN"

        validate_error(
            api.create_custody_event(routine["id"], f.id_verified_payload(), lab.tech1),
            ERR_CUSTODY_NOT_APPLICABLE,
        )
        validate_error(
            api.create_custody_event(
                disability["id"], f.seal_applied_payload("SEAL-4401"), lab.tech1
            ),
            ERR_CUSTODY_SEQUENCE_INVALID,
        )
        validate_error(
            api.create_custody_event(
                disability["id"], f.custody_event_payload("ID_VERIFIED"), lab.tech1
            ),
            ERR_MISSING_EVENT_FIELDS,
        )

        verified = validate_success(
            api.create_custody_event(
                disability["id"], f.id_verified_payload(), lab.tech1
            ),
            expected_status=201,
        )
        assert verified["event_type"] == "ID_VERIFIED"
        assert verified["id_document_type"] == "PHOTO_ID"
        assert verified["actor_role"] == "Technologist"

        advanced = validate_success(api.get_test_session(disability["id"], LAB_MANAGER))
        assert advanced["custody_status"] == "CUSTODY_ID_VERIFIED"
        assert advanced["session_status"] == "SCHEDULED"
        assert_version_is(advanced, disability["version"] + 1)

        untouched = validate_success(api.get_test_session(routine["id"], LAB_MANAGER))
        assert untouched["custody_status"] == "NOT_APPLICABLE"
        assert_version_is(untouched, routine["version"])


class TestOffDutyRosterHasNoEligibleInterpreter:
    """Two free report slots are worth nothing to an interpreter who is off duty."""

    def test_the_empty_candidate_pool_reports_one_uniform_code_and_assigns_nobody(
        self, api
    ):
        """Posture is filtered before capacity, so there is no capacity-specific error.

        PRD 3.9: "The candidate pool is every `Staff` row whose `role_type` is
        `INTERPRETING_PHYSICIAN`, whose `status` is `ON_DUTY`, whose
        `credentialed_modalities` contains the modality of the device the study ran
        on, whose `open_report_count` is strictly below their own
        `max_concurrent_reports`, and whose `id` differs from the study's
        `technologist_staff_id`."

        PRD 3.9: "An empty pool reports `ERR_NO_ELIGIBLE_INTERPRETER`, and it does
        so uniformly — a roster that is entirely off duty, entirely uncredentialed
        for this modality, or entirely at capacity all surface as the same error,
        with no capacity-specific variant."

        Design: Corner/errors/an_off_duty_roster_surfaces_as_no_eligible_interpreter
        """
        lab = fx.build_lab(api)
        off_duty = fx.register_interpreting_physician(
            api,
            employee_code="R-009",
            full_name="Nils Aro",
            max_concurrent_reports=2,
            status="OFF_DUTY",
        )
        session = fx.build_accepted_session(api, lab)
        assert session["session_status"] == "ACCEPTED"
        assert session["quality_grade"] == "A"

        validate_error(
            api.create_interpretation_report(
                session["id"],
                f.report_assignment_payload(session["version"]),
                LAB_MANAGER,
            ),
            ERR_NO_ELIGIBLE_INTERPRETER,
        )

        idle = validate_success(api.get_staff(off_duty["id"], LAB_MANAGER))
        assert idle["open_report_count"] == 0
        assert idle["status"] == "OFF_DUTY"

        unassigned = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert unassigned["session_status"] == "ACCEPTED"
        assert_version_is(unassigned, session["version"])

        _, meta = validate_paginated(
            api.list_interpretation_reports(LAB_MANAGER, session_id=session["id"])
        )
        assert_page(meta, total_count=0, has_more=False)
