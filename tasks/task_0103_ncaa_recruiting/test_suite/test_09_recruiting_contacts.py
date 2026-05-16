"""Recruiting contact log: calendar resolution and permission matrix.

PRD §3.8 (recruiting contact creation, calendar resolution, permission
matrix, half-open interval semantics).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_recruiting_contact,
    create_athlete,
    create_eligibility_record,
    create_program,
    create_recruiting_contact_payload,
    declare_calendar_window,
    setup_enrolled_athlete,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.8 No calendar window -> DEAD default
# ===========================================================================
class TestNoCalendarWindowDefaultsDead:
    """PRD §3.8: "If no window contains the timestamp,
    contact_period_type defaults to DEAD." """

    def test_phone_call_with_no_calendar_window_rejected_as_dead(
        self, api, coach_headers,
    ):
        """PRD §3.8: "If no window contains the timestamp,
        contact_period_type defaults to DEAD."
        PRD §3.8: "During a DEAD period, every modality is forbidden."

        Claim: a PHONE_CALL with no calendar declared falls into DEAD,
        is rejected with ERR_CONTACT_NOT_PERMITTED.
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="PHONE_CALL",
                contact_at="2026-06-15T12:00:00.000Z",
            ),
            coach_headers,
        )
        validate_error(res, "ERR_CONTACT_NOT_PERMITTED")


# ===========================================================================
# §3.8 Permission matrix
# ===========================================================================
class TestContactPermissionMatrix:
    """PRD §3.8: "During a CONTACT period, every modality is
    permitted ... During a QUIET period, PHONE_CALL,
    IN_PERSON_ON_CAMPUS, and TEXT_MESSAGE are permitted;
    IN_PERSON_OFF_CAMPUS and EVALUATION are not. During a DEAD
    period, every modality is forbidden. During an EVALUATION period,
    PHONE_CALL, TEXT_MESSAGE, and EVALUATION are permitted;
    IN_PERSON_OFF_CAMPUS and IN_PERSON_ON_CAMPUS are not." """

    def test_contact_period_permits_all_modalities(self, api, coach_headers):
        """PRD §3.8: "During a CONTACT period, every modality is
        permitted: PHONE_CALL, IN_PERSON_OFF_CAMPUS, IN_PERSON_ON_CAMPUS,
        TEXT_MESSAGE, and EVALUATION are all allowed."

        Claim: posting IN_PERSON_OFF_CAMPUS under a CONTACT window
        succeeds with contact_period_type=CONTACT and was_permitted=true.
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="CONTACT",
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-06-30T00:00:00.000Z",
        )
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="IN_PERSON_OFF_CAMPUS",
                contact_at="2026-06-15T12:00:00.000Z",
            ),
            coach_headers,
        )
        data = validate_success(res, expected_status=201)
        assert_recruiting_contact(data)
        assert data["contact_period_type"] == "CONTACT"
        assert data["was_permitted"] is True

    def test_quiet_period_blocks_in_person_off_campus(
        self, api, coach_headers,
    ):
        """PRD §3.8: "During a QUIET period, PHONE_CALL,
        IN_PERSON_ON_CAMPUS, and TEXT_MESSAGE are permitted;
        IN_PERSON_OFF_CAMPUS and EVALUATION are not."

        Claim: IN_PERSON_OFF_CAMPUS under a QUIET window ->
        ERR_CONTACT_NOT_PERMITTED.
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="QUIET",
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-06-30T00:00:00.000Z",
        )
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="IN_PERSON_OFF_CAMPUS",
                contact_at="2026-06-15T12:00:00.000Z",
            ),
            coach_headers,
        )
        validate_error(res, "ERR_CONTACT_NOT_PERMITTED")

    def test_dead_period_blocks_phone_call(self, api, coach_headers):
        """PRD §3.8: "During a DEAD period, every modality is forbidden."

        Claim: PHONE_CALL under a DEAD window ->
        ERR_CONTACT_NOT_PERMITTED.
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="DEAD",
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-06-30T00:00:00.000Z",
        )
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="PHONE_CALL",
                contact_at="2026-06-15T12:00:00.000Z",
            ),
            coach_headers,
        )
        validate_error(res, "ERR_CONTACT_NOT_PERMITTED")

    def test_evaluation_period_blocks_in_person_on_campus(
        self, api, coach_headers,
    ):
        """PRD §3.8: "During an EVALUATION period, PHONE_CALL,
        TEXT_MESSAGE, and EVALUATION are permitted;
        IN_PERSON_OFF_CAMPUS and IN_PERSON_ON_CAMPUS are not."

        Claim: IN_PERSON_ON_CAMPUS under an EVALUATION window ->
        ERR_CONTACT_NOT_PERMITTED.
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="EVALUATION",
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-06-30T00:00:00.000Z",
        )
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="IN_PERSON_ON_CAMPUS",
                contact_at="2026-06-15T12:00:00.000Z",
            ),
            coach_headers,
        )
        validate_error(res, "ERR_CONTACT_NOT_PERMITTED")

    def test_evaluation_period_permits_evaluation_modality(
        self, api, coach_headers,
    ):
        """PRD §3.8: "During an EVALUATION period, PHONE_CALL,
        TEXT_MESSAGE, and EVALUATION are permitted".

        Claim: EVALUATION-modality contact under an EVALUATION window
        succeeds with was_permitted=true and contact_period_type=
        EVALUATION.
        """
        program = create_program()
        athlete, _p, _s = setup_enrolled_athlete(program=program)
        declare_calendar_window(
            program["id"],
            period_type="EVALUATION",
            start_date="2026-06-01T00:00:00.000Z",
            end_date="2026-06-30T00:00:00.000Z",
        )
        res = api.create_recruiting_contact(
            create_recruiting_contact_payload(
                program_id=program["id"],
                athlete_id=athlete["id"],
                contact_type="EVALUATION",
                contact_at="2026-06-15T12:00:00.000Z",
            ),
            coach_headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["contact_period_type"] == "EVALUATION"
        assert data["was_permitted"] is True
