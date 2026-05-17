"""Clinic bootstrap, deterministic clock, and time-driven cascades.

PRD §2.5 (logical clock), §3.1 (clinic bootstrap), §3.8 (clock advance).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    CLOCK_EPOCH,
    NON_EXISTENT_UUID,
    advance_clock,
    assert_clinic,
    clock_advance_payload,
    create_clinic,
    create_clinic_payload,
    get_clinic,
    parse_iso,
    setup_active_authorization,
    setup_active_treatment_plan,
    setup_clinic_with_roster,
    validate_error,
    validate_success,
)


class TestClinicCreation:
    """PRD §3.1 + §2.5: ClinicAdmin creates clinic; now_ts seeded."""

    def test_clinic_now_ts_seeded_at_epoch(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.5: "On clinic creation, now_ts is set to the
        deterministic epoch 2025-01-01T00:00:00.000Z."

        Claim: a freshly-created clinic has now_ts equal to
        2025-01-01T00:00:00.000Z.
        """
        res = api.create_clinic(
            create_clinic_payload(), clinic_admin_headers,
        )
        clinic = validate_success(res, expected_status=201)
        assert_clinic(clinic)
        assert clinic["now_ts"] == CLOCK_EPOCH

    def test_clinic_read_exposes_now_ts(self, api, clinic_admin_headers):
        """PRD §3.1: "Reads of the clinic include this now_ts so that
        operators and tests can observe the current logical wall."

        Claim: GET /clinics/{id} returns now_ts.
        """
        clinic = create_clinic()
        res = api.get_clinic(clinic["id"], clinic_admin_headers)
        data = validate_success(res)
        assert "now_ts" in data


class TestClockAdvance:
    """PRD §2.5 / §3.8: clock-advance is ClinicAdmin-only and increments
    now_ts by the supplied positive integer of seconds."""

    def test_clock_advance_moves_now_ts_forward(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.5: "Each Clinic carries a logical clock field, now_ts,
        that advances only through the test-driver capability that
        posts a forward delta in seconds against a particular clinic."

        Claim: POST /_clock/advance with seconds=60 increments now_ts
        by exactly 60 seconds.
        """
        clinic = create_clinic()
        before = parse_iso(clinic["now_ts"])
        res = api.clock_advance(
            clock_advance_payload(clinic_id=clinic["id"], seconds=60),
            clinic_admin_headers,
        )
        data = validate_success(res)
        after = parse_iso(data["now_ts"])
        assert int((after - before).total_seconds()) == 60

    @pytest.mark.parametrize("seconds", [0, -1, -3600])
    def test_clock_advance_non_positive_seconds_rejected(
        self, api, clinic_admin_headers, seconds,
    ):
        """PRD §2.5: "The clock-advance body carries the clinic_id and
        the seconds field; seconds must be a strictly positive integer."

        Claim: seconds <= 0 is rejected with ERR_VALIDATION (PRD §2.8:
        schema-level body validation failures not covered by a more
        specific code).
        """
        clinic = create_clinic()
        res = api.clock_advance(
            clock_advance_payload(
                clinic_id=clinic["id"], seconds=seconds,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_clock_advance_unknown_clinic_yields_not_found(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.7: "After the path is fully resolved, foreign-key
        fields in the request body … are then resolved; any unresolved
        body FK yields the same ERR_NOT_FOUND outcome with HTTP 404."

        Claim: clock-advance with an unknown clinic_id returns
        ERR_NOT_FOUND.
        """
        res = api.clock_advance(
            clock_advance_payload(
                clinic_id=NON_EXISTENT_UUID, seconds=10,
            ),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_clock_advance_rbac_blocks_non_clinic_admin(
        self, api, payer_admin_headers,
    ):
        """PRD §4: POST /_clock/advance is exclusive to ClinicAdmin.

        Claim: a PayerAdmin calling clock-advance returns ERR_FORBIDDEN.
        """
        clinic = create_clinic()
        res = api.clock_advance(
            clock_advance_payload(
                clinic_id=clinic["id"], seconds=10,
            ),
            payer_admin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


class TestClockAdvanceCascades:
    """PRD §3.8: clock-advance re-evaluates time-gated transitions on
    every invocation."""

    def test_clock_advance_promotes_approved_authorization_to_active(
        self, api,
    ):
        """PRD §3.4: "When the clinic's now_ts later crosses at or past
        the authorization's effective_start, the Authorization
        auto-transitions from APPROVED to ACTIVE on the next
        clock-advance."

        Claim: an APPROVED authorization whose effective_start is just
        crossed by the next clock-advance transitions to ACTIVE.
        """
        roster = setup_clinic_with_roster()
        clinic = roster["clinic"]
        bcba = roster["bcbas"][0]
        patient = roster["patient"]
        plan = setup_active_treatment_plan(
            clinic=clinic, patient=patient, bcba=bcba,
        )
        # setup_active_authorization itself approves and advances the
        # clock past effective_start; the auth returned is ACTIVE.
        auth, _now_ts = setup_active_authorization(
            clinic=clinic, patient=patient, plan=plan,
        )
        assert auth["status"] == "ACTIVE"
