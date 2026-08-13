"""Athlete registration defaults, the five posture gates, physicals, and
baseline concussion tests (PRD §3.1)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_athlete,
    assert_instant_equals,
    assert_physical,
    begin_care,
    create_athlete_as_trainer,
    create_baseline_payload,
    create_injury_for,
    create_physical_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_nurse,
    make_trainer,
    nurse_headers,
    record_baseline,
    record_physical,
    setup_cleared_athlete,
    trainer_headers,
    validate_error,
    validate_success,
    verify_physical,
)


def _clearance(athlete_id, trainer):
    return validate_success(api_client.get_athlete_clearance(
        athlete_id, trainer_headers(trainer)))


class TestAthleteCreation:

    def test_new_athlete_posture_and_system_fields(self):
        """PRD §3.1: "A newly registered athlete starts with
        `participation_posture` set to `NOT_CLEARED` and `posture_reasons`
        holding the single code `NO_VERIFIED_PHYSICAL`."
        PRD §2.5: "a unique, server-minted identifier formatted as a UUID,
        with no type prefix."

        Design: Corner/entities/athlete_creation_defaults_and_system_fields
        """
        tr1 = make_trainer()
        resp = api_client.create_athlete(
            {
                "full_name": "New Athlete",
                "date_of_birth": "2010-01-15",
                "grade": 9,
                "sex": "F",
                "primary_sport": "TENNIS",
                "team_level": "FRESHMAN",
                "guardian_name": "Guard N",
                "guardian_user_id": "g-9001",
                "guardian_email": "gn@x.com",
            },
            trainer_headers(tr1))
        data = validate_success(resp, expected_status=201)
        assert_athlete(data)
        assert data["participation_posture"] == "NOT_CLEARED"
        assert data["posture_reasons"] == ["NO_VERIFIED_PHYSICAL"]
        assert data["version"] == 1
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert is_iso8601_timestamp(data["updated_at"])


class TestPhysicalIntake:

    def test_physical_missing_and_unknown_athlete_rejected(self):
        """PRD §2.9: "malformed payloads and missing required fields
        short-circuit with `ERR_INVALID_REQUEST` before any business rule
        runs".
        PRD §2.8: "References supplied in request bodies — an `athlete_id` on
        a new physical, a `venue_id` on a new event, a `supply_item_id` on a
        ledger entry — are validated for existence with the same
        family-specific errors before business rules run."

        Design: Corner/entities/physical_missing_athlete_rejected
        """
        tr1 = make_trainer()
        payload = create_physical_payload()
        del payload["athlete_id"]
        resp = api_client.create_physical(payload, trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        payload = create_physical_payload(athlete_id=NON_EXISTENT_UUID)
        resp = api_client.create_physical(payload, trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_ATHLETE_NOT_FOUND)

    def test_verify_side_effects_and_posture_gate_advance(self):
        """PRD §3.1: "A successful verification stamps `verified_by_staff_id`
        with the nurse's identity, moves the physical to `VERIFIED`, and
        recomputes the athlete's posture."
        PRD §3.1: "`INELIGIBLE` — the latest `VERIFIED` physical has expired
        (the clock is at or past its `expires_on`), or that physical's
        outcome is `NOT_CLEARED` or `DEFERRED`, or the athlete has no
        `CURRENT` baseline whose `valid_until` lies in the future."

        Design: Corner/state_machines/physical_verify_transition_side_effects
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete = create_athlete_as_trainer(tr1, sex="F")
        physical = record_physical(athlete["id"], tr1)
        assert physical["status"] == "RECORDED"
        assert_physical(physical)

        data = validate_success(api_client.verify_physical(
            physical["id"], nurse_headers(nr1)))
        assert data["status"] == "VERIFIED"
        assert data["verified_by_staff_id"] == nr1["id"]

        # Physical gate now passes but no baseline exists: INELIGIBLE.
        clearance = _clearance(athlete["id"], tr1)
        assert clearance["participation_posture"] == "INELIGIBLE"
        assert "NO_CURRENT_BASELINE" in clearance["posture_reasons"]

    def test_void_and_double_verify_state_lockdown(self):
        """PRD §3.1: "Verification requires the physical to still be
        `RECORDED` (any other status draws `ERR_INVALID_STATE`)".
        PRD §3.1: "A trainer who discovers a data-entry error can void a
        `RECORDED` physical, moving it to `VOIDED` and again recomputing
        posture."

        Design: Corner/state_machines/physical_void_and_double_verify_rejected
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete = create_athlete_as_trainer(tr1, primary_sport="BASEBALL",
                                            team_level="JV")
        p1 = record_physical(athlete["id"], tr1)
        verify_physical(p1["id"], nr1)
        p2 = record_physical(athlete["id"], tr1, exam_date="2026-07-20",
                             examining_physician_name="Dr Y")

        # Void is defined on a RECORDED physical; VERIFIED rejects it.
        resp = api_client.void_physical(p1["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        data = validate_success(api_client.verify_physical(
            p2["id"], nurse_headers(nr1)))
        assert data["status"] == "VERIFIED"

        # A second verify is a duplicate action on a non-RECORDED record.
        resp = api_client.verify_physical(p2["id"], nurse_headers(nr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        resp = api_client.void_physical(p2["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestBaselines:

    def test_newer_baseline_supersedes_current(self):
        """PRD §3.1: "One athlete has at most one `CURRENT` baseline:
        recording a newer test for the same athlete moves the previously
        `CURRENT` test to `SUPERSEDED`".
        PRD §3.1: "computes `valid_until` as twenty-four calendar months
        after the `test_date` at 00:00:00Z that day".

        Design: Corner/state_machines/baseline_supersede_on_new_test
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(tr1, sex="F")
        b1 = record_baseline(athlete["id"], tr1, test_date="2026-07-15")
        assert b1["status"] == "CURRENT"
        assert_instant_equals(b1["valid_until"], "2028-07-15T00:00:00Z",
                              "baseline valid_until")

        b2 = record_baseline(athlete["id"], tr1, test_date="2026-07-28",
                             instrument="IMPACT", symptom_score=1,
                             memory_index=94.0, reaction_time_ms=255.0,
                             balance_errors=2)
        assert b2["status"] == "CURRENT"

        b1_after = validate_success(api_client.get_baseline_test(
            b1["id"], trainer_headers(tr1)))
        assert b1_after["status"] == "SUPERSEDED"

    def test_baseline_score_range_and_instrument_enum_enforced(self):
        """PRD §3.1: "the four scores: `symptom_score` (an integer from 0 to
        132), `memory_index` (0 to 100)".
        PRD §3.1: "the `instrument` used (`SCAT6`, `IMPACT`, or `SWAY`), and
        the four scores".
        PRD §2.9: "Field-shape validation — required fields present, enum
        values valid, date ranges sane".

        Design: Corner/entities/baseline_invalid_request_rejected
        """
        tr1 = make_trainer()
        athlete = create_athlete_as_trainer(tr1)
        payload = create_baseline_payload(athlete_id=athlete["id"],
                                          symptom_score=200)
        resp = api_client.create_baseline_test(payload,
                                               trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        payload = create_baseline_payload(athlete_id=athlete["id"],
                                          instrument="XYZ", symptom_score=10)
        resp = api_client.create_baseline_test(payload,
                                               trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestClearanceRead:

    def test_clearance_summary_computed_fields(self):
        """PRD §3.1: "The clearance detail view for an athlete exposes this
        computation directly: `athlete_id`, `participation_posture`, the
        ordered `posture_reasons`, the governing physical's
        `physical_expires_on`, and the governing baseline's
        `baseline_valid_until`."

        Design: Corner/entities/clearance_summary_computed_read
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete = setup_cleared_athlete(
            tr1, nr1, athlete_overrides={"sex": "F"})
        clearance = _clearance(athlete["id"], tr1)
        assert clearance["participation_posture"] == "CLEARED"
        # exam_date 2026-07-01 + 13 calendar months -> 2027-08-01T00:00:00Z.
        assert_instant_equals(clearance["physical_expires_on"],
                              "2027-08-01T00:00:00Z", "physical_expires_on")
        # test_date 2026-07-15 + 24 calendar months -> 2028-07-15T00:00:00Z.
        assert_instant_equals(clearance["baseline_valid_until"],
                              "2028-07-15T00:00:00Z", "baseline_valid_until")

    def test_posture_gate_progression_end_to_end(self):
        """PRD §3.1: "The recompute walks five gates in strict order, and the
        first gate that matches wins".
        PRD §3.1: "`CLEARED` — every gate above passes, with no injury in
        `OPEN`, `UNDER_CARE`, `REFERRED`, or `RTP_IN_PROGRESS`.
        `posture_reasons` is empty."

        Design: Corner/calculations/posture_gate_progression_end_to_end
        """
        tr1 = make_trainer()
        nr1 = make_nurse()
        athlete = create_athlete_as_trainer(tr1, sex="F")

        # Gate 1: no VERIFIED physical has ever existed.
        assert _clearance(athlete["id"], tr1)["participation_posture"] == \
            "NOT_CLEARED"

        ph = record_physical(athlete["id"], tr1)
        verify_physical(ph["id"], nr1)
        # Gate 2: verified physical but no CURRENT baseline.
        assert _clearance(athlete["id"], tr1)["participation_posture"] == \
            "INELIGIBLE"

        record_baseline(athlete["id"], tr1)
        # Gate 5: everything passes.
        assert _clearance(athlete["id"], tr1)["participation_posture"] == \
            "CLEARED"

        injury = create_injury_for(athlete["id"], tr1)
        # Gate 3: an OPEN injury.
        assert _clearance(athlete["id"], tr1)["participation_posture"] == \
            "MEDICAL_HOLD"

        begin_care(injury["id"], tr1)
        # Gate 4: injury now UNDER_CARE.
        assert _clearance(athlete["id"], tr1)["participation_posture"] == \
            "CLEARED_WITH_RESTRICTIONS"

        validate_success(api_client.resolve_injury(injury["id"],
                                                   trainer_headers(tr1)))
        cleared = _clearance(athlete["id"], tr1)
        assert cleared["participation_posture"] == "CLEARED"
        assert cleared["posture_reasons"] == []


class TestPhysicalExpiryDualVariant:

    def _setup_two_physicals(self):
        tr1 = make_trainer()
        athlete_a = create_athlete_as_trainer(tr1, full_name="Athlete A")
        athlete_b = create_athlete_as_trainer(tr1, full_name="Athlete B",
                                              sex="F")
        ph_a = record_physical(athlete_a["id"], tr1, exam_date="2026-03-15",
                               validity_policy="DISTRICT_13MO")
        ph_b = record_physical(athlete_b["id"], tr1, exam_date="2026-03-15",
                               validity_policy="STATE_SCHOOL_YEAR")
        return tr1, ph_a, ph_b

    def test_district_13mo_expiry_thirteen_months(self):
        """PRD §3.1: "under `DISTRICT_13MO`, expiry falls thirteen calendar
        months after the `exam_date`, at the stroke of 00:00:00Z that day".

        Design: Difficulty/dual_variant_calc/physical_expiry_district13mo_vs_school_year
        """
        tr1, ph_a, _ = self._setup_two_physicals()
        data = validate_success(api_client.get_physical(
            ph_a["id"], trainer_headers(tr1)))
        assert_instant_equals(data["expires_on"], "2027-04-15T00:00:00Z",
                              "expires_on DISTRICT_13MO")

    def test_state_school_year_expiry_august_first(self):
        """PRD §3.1: "under `STATE_SCHOOL_YEAR`, the physical remains valid
        through the end of the school year and expires at 00:00:00Z on
        August 1 — of the same calendar year when the exam month is January
        through July, or of the following calendar year when the exam month
        is August through December."

        Design: Difficulty/dual_variant_calc/physical_expiry_district13mo_vs_school_year
        """
        tr1, ph_a, ph_b = self._setup_two_physicals()
        data_b = validate_success(api_client.get_physical(
            ph_b["id"], trainer_headers(tr1)))
        assert_instant_equals(data_b["expires_on"], "2026-08-01T00:00:00Z",
                              "expires_on STATE_SCHOOL_YEAR")
        data_a = validate_success(api_client.get_physical(
            ph_a["id"], trainer_headers(tr1)))
        # One exam date, two policies, two different expiries.
        assert data_a["expires_on"] != data_b["expires_on"]
