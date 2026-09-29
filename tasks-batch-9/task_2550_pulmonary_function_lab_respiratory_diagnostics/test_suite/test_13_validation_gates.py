"""Gates whose verdict turns on stored state rather than on the request body.

A byte-identical request can be refused and then accepted one logical minute
later, refused on one instrument and accepted on another of a different
modality, or refused until a compliance witness has signed — and the coaching
note a blow must carry cannot be judged until the acceptability calculation has
already run.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_COACHING_NOTE_REQUIRED,
    ERR_LEAK_CHECK_MISSING,
    ERR_MED_HOLD_NOT_ELAPSED,
    ERR_MED_HOLD_VIOLATED,
    ERR_WITNESS_ATTESTATION_MISSING,
)
from test_helpers.assertions import (
    assert_3dp,
    assert_instant,
    assert_maneuver_acceptable,
    assert_maneuver_unacceptable,
    assert_page,
)
from test_helpers.constants import MORNING_CLOCK
from test_helpers.test_users import LAB_MANAGER

EARLY_MORNING = "2026-08-01T06:00:00Z"
AFTERNOON_WINDOW = ("2026-08-01T13:00:00Z", "2026-08-01T13:30:00Z")


def _order_on_a_short_acting_inhaler(api):
    """A submitted order for a patient on a SABA, with its hold already issued."""
    lab = fx.build_lab(api, clock=EARLY_MORNING)
    order = fx.draft_and_submit_order(
        api, lab.patient_id, lab.doc1, current_medication_classes=("SABA",)
    )
    hold = validate_success(
        api.create_medication_hold(
            order["id"], f.medication_hold_payload("SABA", order["version"]), lab.tech1
        ),
        expected_status=201,
    )
    return lab, order, hold


def _attest(api, hold_id, result, tech_headers):
    """The technologist's check-in attestation of what the patient did."""
    return validate_success(
        api.attest_medication_hold(hold_id, {"attestation_result": result}, tech_headers)
    )


class TestHoldReleaseWindow:
    """The withholding window is a clock comparison with an inclusive edge."""

    def test_one_minute_before_the_release_instant_is_refused_and_the_instant_itself_is_not(
        self, api
    ):
        """The identical request fails at 11:59 and succeeds at exactly 12:00.

        PRD 3.4: "The server stamps `instructed_at` from the logical clock, reads
        `required_hold_hours` from the fixed per-class table (`SABA` 6 hours,
        `SAMA` 8, `LABA` 24, `LAMA` 36, `ICS_LABA` 24, `ANTIHISTAMINE` 72 and
        `CAFFEINE` 8) and computes that hold's own `release_at` as
        `instructed_at` plus `required_hold_hours` hours."

        PRD 3.5: "And the current logical clock must be at or after the order's
        `hold_release_at`, with the comparison inclusive so that a study
        beginning at exactly `hold_release_at` is permitted."

        Design: Corner/validations/hold_release_gate_is_inclusive_at_exactly_hold_release_at
        """
        lab, order, hold = _order_on_a_short_acting_inhaler(api)
        start, end = AFTERNOON_WINDOW

        attested = _attest(api, hold["id"], "WITHHELD", lab.tech1)
        assert attested["status"] == "ATTESTED"
        assert attested["attestation_result"] == "WITHHELD"
        assert attested["required_hold_hours"] == 6
        assert_instant(attested["release_at"], "2026-08-01T12:00:00Z")

        ready = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert ready["status"] == "READY"
        assert_instant(ready["hold_release_at"], "2026-08-01T12:00:00Z")

        fx.set_clock(api, "2026-08-01T11:59:00Z")
        validate_error(
            api.create_test_session(
                f.test_session_payload(order["id"], lab.device_id, start, end),
                lab.tech1,
            ),
            ERR_MED_HOLD_NOT_ELAPSED,
        )

        still_ready = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert still_ready["status"] == "READY"
        _, meta = validate_paginated(
            api.list_test_sessions(LAB_MANAGER, order_id=order["id"])
        )
        assert_page(meta, total_count=0, has_more=False)

        fx.set_clock(api, "2026-08-01T12:00:00Z")
        session = validate_success(
            api.create_test_session(
                f.test_session_payload(order["id"], lab.device_id, start, end),
                lab.tech1,
            ),
            expected_status=201,
        )
        assert session["session_status"] == "SCHEDULED"

        testing = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert testing["status"] == "IN_TESTING"


class TestViolatedHoldRemediation:
    """A ready order can still be unschedulable, and only a replacement clears it."""

    def test_a_taken_attestation_blocks_scheduling_until_a_replacement_is_withheld(
        self, api
    ):
        """READY does not mean compliant: the block lifts only on the second hold.

        PRD 3.4: "`WITHHELD` moves the hold to `ATTESTED`; `TAKEN` moves it to
        `VIOLATED`, and because a violated hold leaves the participating set,
        `hold_release_at` is recomputed over the remaining `PENDING` and
        `ATTESTED` holds."

        PRD 3.4: "A `VIOLATED` hold leaves the order `READY` while independently
        blocking study creation with `ERR_MED_HOLD_VIOLATED`. The remediation
        loop is to issue a replacement hold for that class, which supersedes the
        violation and pushes the order from `READY` back to `MED_HOLD_ISSUED` —
        deliberately removing it from the schedulable set — and then to attest
        the replacement `WITHHELD`, which returns it to `READY` with the
        violation superseded and the block lifted."

        Design: Corner/validations/violated_hold_blocks_the_session_until_a_replacement_is_attested
        """
        lab, order, hold = _order_on_a_short_acting_inhaler(api)

        violated = _attest(api, hold["id"], "TAKEN", lab.tech1)
        assert violated["status"] == "VIOLATED"

        ready = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert ready["status"] == "READY"
        assert ready["hold_release_at"] is None

        fx.set_clock(api, "2026-08-01T12:00:00Z")
        validate_error(
            api.create_test_session(
                f.test_session_payload(
                    order["id"], lab.device_id, *AFTERNOON_WINDOW
                ),
                lab.tech1,
            ),
            ERR_MED_HOLD_VIOLATED,
        )

        blocked = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert blocked["status"] == "READY"

        replacement = validate_success(
            api.create_medication_hold(
                order["id"],
                f.medication_hold_payload("SABA", blocked["version"]),
                lab.tech1,
            ),
            expected_status=201,
        )
        assert replacement["status"] == "PENDING"
        assert_instant(replacement["instructed_at"], "2026-08-01T12:00:00Z")
        assert_instant(replacement["release_at"], "2026-08-01T18:00:00Z")

        superseded = validate_success(api.get_medication_hold(hold["id"], LAB_MANAGER))
        assert superseded["status"] == "SUPERSEDED"

        reissued = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert reissued["status"] == "MED_HOLD_ISSUED"

        attested = _attest(api, replacement["id"], "WITHHELD", lab.tech1)
        assert attested["status"] == "ATTESTED"

        cleared = validate_success(api.get_test_order(order["id"], LAB_MANAGER))
        assert cleared["status"] == "READY"
        assert_instant(cleared["hold_release_at"], "2026-08-01T18:00:00Z")

        fx.set_clock(api, "2026-08-01T18:00:00Z")
        session = validate_success(
            api.create_test_session(
                f.test_session_payload(
                    order["id"],
                    lab.device_id,
                    "2026-08-01T19:00:00Z",
                    "2026-08-01T19:30:00Z",
                ),
                lab.tech1,
            ),
            expected_status=201,
        )
        assert session["session_status"] == "SCHEDULED"


def _lab_with_a_spirometer_and_a_diffusion_bench(api):
    """Two instruments of different modality, both through today's quality program.

    Neither has had a leak check recorded, which is exactly the difference the
    closed-circuit requirement turns on.
    """
    fx.set_clock(api, MORNING_CLOCK)
    roster = fx.build_roster(api)
    fx.publish_reference_equation(api, modality_scope=("SPIROMETRY", "DLCO"))
    spirometer = fx.register_device(api, "SPIRO-1", "SPIROMETRY")
    bench = fx.register_device(api, "DLCO-1", "DLCO")
    for index, device_id in enumerate((spirometer["id"], bench["id"]), start=1):
        fx.run_daily_quality_program(
            api, device_id, roster.tech1, roster.bcs_id, filter_serial=f"F-100{index}"
        )
    patient = fx.register_patient(api)
    return roster, patient["id"], spirometer["id"], bench["id"]


class TestClosedCircuitLeakCheck:
    """The leak-check gate reads the device's modality and nothing else."""

    def test_the_same_booking_is_refused_on_the_diffusion_bench_and_taken_on_the_spirometer(
        self, api
    ):
        """One leak check flips the closed-circuit instrument and only that one.

        PRD 3.2: "Their only consequence is that the record now satisfies the
        same-day leak-check requirement that closed-circuit modalities carry — a
        requirement that binds `DLCO` and `PLETHYSMOGRAPHY` devices and does not
        exist at all for `SPIROMETRY` devices, so the identical scheduling
        request is legal on one instrument and refused with
        `ERR_LEAK_CHECK_MISSING` on another."

        PRD 3.2: "**Leak checks** are the simpler ritual: they record
        `ambient_temp_c` and `barometric_pressure_kpa` and nothing else, their
        `outcome` is always `COMPLETE` and their `failure_reason` always null, and
        no device field changes."

        Design: Corner/validations/leak_check_is_required_only_for_closed_circuit_modalities
        """
        roster, patient_id, spirometer_id, bench_id = (
            _lab_with_a_spirometer_and_a_diffusion_bench(api)
        )
        both = ("SPIROMETRY", "DLCO")
        first_order = fx.draft_and_submit_order(
            api, patient_id, roster.doc1, requested_modalities=both
        )
        second_order = fx.draft_and_submit_order(
            api, patient_id, roster.doc1, requested_modalities=both
        )

        validate_error(
            api.create_test_session(
                f.test_session_payload(
                    first_order["id"],
                    bench_id,
                    "2026-08-03T09:00:00Z",
                    "2026-08-03T09:30:00Z",
                ),
                roster.tech1,
            ),
            ERR_LEAK_CHECK_MISSING,
        )

        leak_check = fx.append_quality_event(
            api, bench_id, f.leak_check_event_payload(), roster.tech1
        )
        assert leak_check["outcome"] == "COMPLETE"
        assert leak_check["failure_reason"] is None

        on_the_bench = validate_success(
            api.create_test_session(
                f.test_session_payload(
                    first_order["id"],
                    bench_id,
                    "2026-08-03T09:00:00Z",
                    "2026-08-03T09:30:00Z",
                ),
                roster.tech1,
            ),
            expected_status=201,
        )
        assert on_the_bench["device_id"] == bench_id
        assert on_the_bench["session_status"] == "SCHEDULED"

        on_the_spirometer = validate_success(
            api.create_test_session(
                f.test_session_payload(
                    second_order["id"],
                    spirometer_id,
                    "2026-08-03T11:00:00Z",
                    "2026-08-03T11:30:00Z",
                ),
                roster.tech1,
            ),
            expected_status=201,
        )
        assert on_the_spirometer["device_id"] == spirometer_id
        assert on_the_spirometer["session_status"] == "SCHEDULED"

        _, meta = validate_paginated(
            api.list_quality_events(
                LAB_MANAGER, device_id=spirometer_id, event_type="LEAK_CHECK"
            )
        )
        assert_page(meta, total_count=0, has_more=False)


def _sealed_disability_study_with_a_report(api):
    """A disability study sealed by its technologist and handed to an interpreter."""
    lab = fx.build_lab(api, interpreters=1)
    session = fx.build_scheduled_session(
        api,
        lab,
        indication_code="DISABILITY_ASSESSMENT",
        test_context="DISABILITY_EVALUATION",
    )
    fx.verify_identity(api, session["id"], lab.tech1)
    fx.apply_seal(api, session["id"], lab.tech1)
    fx.append_maneuver_series(api, session["id"], lab.tech1)
    closed = fx.finalize_quality(api, session["id"], lab.tech1)
    report = fx.assign_report(api, session["id"], closed["version"])
    return lab, closed, report


class TestWitnessAttestationGate:
    """Only the disability context needs the compliance auditor's signature."""

    def test_signing_waits_for_the_auditors_attestation_and_the_seal_stays_put(self, api):
        """The witness event unlocks the signature without moving the custody state.

        PRD 3.8: "For a study whose `test_context` is specifically
        `DISABILITY_EVALUATION`, at least one custody event with `event_type`
        `WITNESS_SIGNED` must additionally exist on that study, otherwise
        `ERR_WITNESS_ATTESTATION_MISSING`."

        PRD 3.8: "The fourth type, `WITNESS_SIGNED`, behaves differently in three
        respects. It is legal from any applicable custody state — `CUSTODY_OPEN`,
        `CUSTODY_ID_VERIFIED`, `CUSTODY_SEALED` or `CUSTODY_BROKEN` — it leaves
        `custody_status` exactly where it was, and it is reserved to the
        `ComplianceAuditor` role; a `Technologist` submitting a witness
        attestation is refused with `ERR_ROLE_NOT_PERMITTED`."

        PRD 3.4: "When a study for the order reaches `REPORTED`, the order becomes
        `COMPLETED` and the patient's `completed_order_count` increases by one."

        Design: Corner/validations/witness_attestation_is_required_only_for_the_disability_context
        """
        lab, closed, report = _sealed_disability_study_with_a_report(api)
        assert closed["custody_status"] == "CUSTODY_SEALED"

        validate_error(
            api.sign_interpretation_report(
                report["id"], f.sign_report_payload(), lab.roster.interpreters[0]
            ),
            ERR_WITNESS_ATTESTATION_MISSING,
        )

        unsigned = validate_success(
            api.get_interpretation_report(report["id"], LAB_MANAGER)
        )
        assert unsigned["status"] == "ASSIGNED"
        assert unsigned["signed_at"] is None

        witnessed = fx.witness_session(api, closed["id"])
        assert witnessed["event_type"] == "WITNESS_SIGNED"
        assert witnessed["actor_role"] == "ComplianceAuditor"

        still_sealed = validate_success(api.get_test_session(closed["id"], LAB_MANAGER))
        assert still_sealed["custody_status"] == "CUSTODY_SEALED"
        assert still_sealed["session_status"] == "ACCEPTED"

        signed = fx.sign_report(api, report["id"], lab.roster.interpreters[0])
        assert signed["status"] == "SIGNED"

        reported = validate_success(api.get_test_session(closed["id"], LAB_MANAGER))
        assert reported["session_status"] == "REPORTED"
        completed = validate_success(
            api.get_test_order(reported["order_id"], LAB_MANAGER)
        )
        assert completed["status"] == "COMPLETED"


class TestCoachingNoteGate:
    """The note requirement is decided by the computed verdict, not by the body."""

    def test_the_same_cough_blow_is_refused_without_a_note_and_stored_with_one(self, api):
        """An unacceptable effort needs the note; the acceptable one before it did not.

        PRD 3.6: "Because an unacceptable blow must leave a coaching record,
        `coaching_note` is required and must be non-empty whenever the computed
        `acceptability` is `UNACCEPTABLE`, and its absence reports
        `ERR_COACHING_NOTE_REQUIRED`. A `USABLE_FEV1_ONLY` blow does not require
        one."

        PRD 3.6: "`acceptable_maneuver_count` counts only the `PRE_BD` maneuvers
        whose `acceptability` is exactly `ACCEPTABLE`."

        PRD 3.6: "`repeatability_delta_ml` is the whole-millilitre difference
        between the largest and second-largest `fev1_l` in the FEV1 pool, and is
        null while that pool holds fewer than two maneuvers."

        Design: Corner/validations/coaching_note_requirement_depends_on_the_computed_acceptability
        """
        lab = fx.build_lab(api)
        session = fx.build_scheduled_session(api, lab)

        clean = fx.append_maneuver(
            api, session["id"], f.maneuver_payload(3.200, 2.400), lab.tech1
        )
        assert_maneuver_acceptable(clean)

        coughed = f.maneuver_payload(
            3.150,
            2.250,
            pef_l_s=5.80,
            back_extrapolated_volume_ml=120,
            expiratory_time_s=16.0,
            cough_in_first_second=True,
        )
        validate_error(
            api.create_maneuver(session["id"], coughed, lab.tech1),
            ERR_COACHING_NOTE_REQUIRED,
        )

        _, meta = validate_paginated(
            api.list_maneuvers(LAB_MANAGER, session_id=session["id"])
        )
        assert_page(meta, total_count=1, has_more=False)

        coughed_with_a_note = dict(
            coughed,
            coaching_note="Coached the patient to suppress the cough and repeat the effort.",
        )
        stored = fx.append_maneuver(
            api, session["id"], coughed_with_a_note, lab.tech1
        )
        assert_maneuver_unacceptable(stored, ["COUGH_ARTIFACT"])
        assert stored["maneuver_index"] == 2

        current = validate_success(api.get_test_session(session["id"], LAB_MANAGER))
        assert current["acceptable_maneuver_count"] == 1
        assert_3dp(current["best_fev1_l"], 2.400)
        assert current["repeatability_delta_ml"] is None
