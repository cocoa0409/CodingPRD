"""Sitter (1:1 observation) requests: window shape, fill preconditions, and
the diversion/restoration posture loop."""
import pytest

from test_helpers import (
    ADMIN,
    api_client,
    ApiErrorId,
    confirm_assignment,
    create_nurse,
    create_sitter,
    create_unit,
    get_shift,
    make_charge_nurse_headers,
    setup_staffed_shift,
    setup_unit_with_shift,
    validate_error,
    validate_success,
    walk_to_accepted,
)


class TestSitterWindowShape:

    def test_sitter_invalid_time_range_rejected(self):
        """PRD section 3.7: "A `ChargeNurse` opens a sitter request with the
        `unit_id`, a de-identified `patient_ref`, and an observation window
        from `start_at` to `end_at` — both ISO 8601 UTC instants, with
        `end_at` strictly after `start_at` or the request shape check rejects
        it."

        Design: Corner/validations/sitter_invalid_time_range_rejected
        """
        unit = create_unit(name="ICU V6", unit_type="ICU")
        cn = create_nurse(full_name="V6 Charge", employment_type="CORE",
                          competencies=["ICU"], base_hourly_rate_cents=7000,
                          home_unit_id=unit["id"], charge_qualified=True)
        resp = api_client.create_sitter_request(
            {"unit_id": unit["id"], "patient_ref": "P-4004",
             "start_at": "2026-08-10T14:00:00Z",
             "end_at": "2026-08-10T10:00:00Z"},
            make_charge_nurse_headers(cn["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestSitterFillCoveringAssignment:
    """Difficulty instance: sitter_fill_requires_confirmed_covering_assignment."""

    def _setup_pending_sitter(self):
        """ICU DAY shift (07:00-19:00Z) required 2; nurse ACCEPTED (not yet
        CONFIRMED); PENDING sitter window 09:00-13:00Z inside the shift."""
        sc = setup_unit_with_shift(name="ICU K", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Sara Sitter", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        asg = walk_to_accepted(sc["shift"]["id"], nurse, sc["charge_headers"])
        sr = create_sitter(sc["unit"]["id"], sc["charge_headers"],
                           patient_ref="P-1001",
                           start_at="2026-08-10T09:00:00Z",
                           end_at="2026-08-10T13:00:00Z")
        sc.update({"nurse": nurse, "asg": asg, "sr": sr})
        return sc

    def test_fill_rejected_while_covering_assignment_not_confirmed(self):
        """PRD section 3.7: "That nurse must hold a `CONFIRMED` assignment on
        the same unit whose shift interval fully contains the observation
        window — the shift's `start_at` at or before the window's start and
        the shift's `end_at` at or after the window's end — and that
        assignment must not already be covering another `FILLED` sitter
        request; failing either condition yields `ERR_NO_COVERING_ASSIGNMENT`."

        Design: Difficulty/cross_entity_state_dependency/sitter_fill_requires_confirmed_covering_assignment
        """
        sc = self._setup_pending_sitter()
        resp = api_client.fill_sitter_request(
            sc["sr"]["id"], {"nurse_id": sc["nurse"]["id"]},
            sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_ASSIGNMENT)

    def test_fill_succeeds_after_confirm_and_diverts(self):
        """PRD section 3.7: "A successful fill records `assigned_nurse_id` and
        `covering_assignment_id` on the now-`FILLED` request, increments the
        covering shift's `sitter_diversion_count` by one, and re-evaluates
        posture".

        Design: Difficulty/cross_entity_state_dependency/sitter_fill_requires_confirmed_covering_assignment
        """
        sc = self._setup_pending_sitter()
        resp = api_client.fill_sitter_request(
            sc["sr"]["id"], {"nurse_id": sc["nurse"]["id"]},
            sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_NO_COVERING_ASSIGNMENT)

        confirm_assignment(sc["asg"]["id"], sc["charge_headers"])
        filled = validate_success(
            api_client.fill_sitter_request(
                sc["sr"]["id"], {"nurse_id": sc["nurse"]["id"]},
                sc["charge_headers"]),
            expected_status=200)
        assert filled["status"] == "FILLED"
        assert filled["covering_assignment_id"] == sc["asg"]["id"]
        assert filled["assigned_nurse_id"] == sc["nurse"]["id"]

        shift = get_shift(sc["shift"]["id"])
        assert shift["sitter_diversion_count"] == 1


class TestSitterFillReleaseLoop:

    def test_sitter_fill_release_restores_posture(self):
        """PRD section 3.7: "note that diversion reduces
        `effective_assignments`, so filling a sitter can by itself push a shift
        from `ADEQUATE` to `UNDERSTAFFED` or `CRITICAL`."
        PRD section 3.7: "Releasing a filled request, permitted only from
        `FILLED` (else `ERR_SITTER_INVALID_STATE`), moves it to `RELEASED`,
        decrements the covering shift's `sitter_diversion_count`, and
        re-evaluates posture again."

        Design: Corner/state_machines/sitter_fill_release_restores_posture
        """
        sc = setup_staffed_shift(num_confirmed=2, charge_first=True,
                                 name="ICU B2", census=(4, 0, 0, 0))
        before = get_shift(sc["shift"]["id"])
        assert before["staffing_posture"] == "ADEQUATE"
        assert before["status"] == "STAFFED"

        sr = create_sitter(sc["unit"]["id"], sc["charge_headers"],
                           patient_ref="P-2002",
                           start_at="2026-08-10T10:00:00Z",
                           end_at="2026-08-10T14:00:00Z")
        filled = validate_success(
            api_client.fill_sitter_request(
                sr["id"], {"nurse_id": sc["nurses"][1]["id"]},
                sc["charge_headers"]),
            expected_status=200)
        assert filled["status"] == "FILLED"

        diverted = get_shift(sc["shift"]["id"])
        assert diverted["sitter_diversion_count"] == 1
        # effective 1 of required 2 -> UNDERSTAFFED, and status flips to OPEN
        assert diverted["staffing_posture"] == "UNDERSTAFFED"
        assert diverted["status"] == "OPEN"

        released = validate_success(
            api_client.release_sitter_request(sr["id"], sc["charge_headers"]),
            expected_status=200)
        assert released["status"] == "RELEASED"

        restored = get_shift(sc["shift"]["id"])
        assert restored["sitter_diversion_count"] == 0
        assert restored["staffing_posture"] == "ADEQUATE"
        assert restored["status"] == "STAFFED"

    def test_sitter_fill_twice_rejected(self):
        """PRD section 3.7: "Filling the request, again a `ChargeNurse` act,
        requires the request to be `PENDING` (else `ERR_SITTER_INVALID_STATE`)".

        Design: Corner/state_machines/sitter_fill_twice_rejected
        """
        sc = setup_unit_with_shift(name="ICU B6", census=(4, 0, 0, 0))
        nurse = create_nurse(full_name="Double Drew", employment_type="CORE",
                             competencies=["ICU"], base_hourly_rate_cents=5000,
                             home_unit_id=sc["unit"]["id"])
        asg = walk_to_accepted(sc["shift"]["id"], nurse, sc["charge_headers"])
        confirm_assignment(asg["id"], sc["charge_headers"])
        sr = create_sitter(sc["unit"]["id"], sc["charge_headers"],
                           patient_ref="P-3003",
                           start_at="2026-08-10T08:00:00Z",
                           end_at="2026-08-10T12:00:00Z")
        first = api_client.fill_sitter_request(
            sr["id"], {"nurse_id": nurse["id"]}, sc["charge_headers"])
        validate_success(first, expected_status=200)

        resp = api_client.fill_sitter_request(
            sr["id"], {"nurse_id": nurse["id"]}, sc["charge_headers"])
        validate_error(resp, ApiErrorId.ERR_SITTER_INVALID_STATE)
