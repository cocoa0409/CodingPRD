"""Petition filing (POST /cases) and case initial state.

PRD §3.1 — petition body, the FILED -> AWAITING_ANSWER transition, the
30-day answer deadline, docket-number minting, Party rows, served_at,
and the separation-after-marriage validation.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    advance_clock_to,
    api_client,
    ANSWER_WINDOW_DAYS,
    assert_case,
    assert_docket_number_format,
    create_case,
    create_case_payload,
    get_clock_now,
    iso_utc,
    parse_iso,
    server_now_dt,
    server_offset_iso,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Happy-path filing — PRD §3.1
# ===========================================================================
class TestPetitionHappyPath:

    def test_create_case_returns_case_with_required_fields(
        self, api, petitioner_fallback_headers,
    ):
        """PRD §3.1: 'On acceptance, the server mints a Case row in
        initial status FILED, mints two Party rows ... records the
        petitioner's Party.id on the case as petitioner_party_id and
        the respondent's Party.id as respondent_party_id ... The
        server also mints Case.docket_number in the format
        FC-YYYY-NNNNNN.'

        Claim: POST /cases returns a Case with docket_number,
        petitioner_party_id, respondent_party_id, and status either
        FILED (transient) or AWAITING_ANSWER (after the system auto-
        transition immediately fires).
        """
        payload = create_case_payload()
        res = api.create_case(payload, petitioner_fallback_headers)
        case = validate_success(res, 201)
        assert_case(case)
        # PRD §3.1: 'The system then immediately advances Case.status
        # from FILED to AWAITING_ANSWER'. We accept either FILED or
        # AWAITING_ANSWER for the snapshot returned by POST /cases,
        # since both are PRD-faithful (the auto-transition may fire
        # before or as part of the response).
        assert case["status"] in ("FILED", "AWAITING_ANSWER"), (
            f"freshly filed case status must be FILED or "
            f"AWAITING_ANSWER, got {case['status']!r}"
        )
        assert case["jurisdiction_state"] == payload["jurisdiction_state"]
        assert case["has_minor_children"] == payload["has_minor_children"]

    def test_case_advances_to_awaiting_answer(
        self, api, petitioner_fallback_headers,
    ):
        """PRD §3.1: 'The system then immediately advances Case.status
        from FILED to AWAITING_ANSWER and pins Case.answer_deadline_at
        to exactly thirty days after the case's created_at timestamp.'

        Claim: when re-read, the case is in AWAITING_ANSWER with a
        non-null answer_deadline_at.
        """
        case = create_case()
        again = api.get_case(
            case["id"], TEST_USERS["judge_headers"],
        )
        c = validate_success(again, 200)
        assert c["status"] == "AWAITING_ANSWER"
        assert c["answer_deadline_at"], "answer_deadline_at must be set"

    def test_docket_number_format(
        self, api, petitioner_fallback_headers,
    ):
        """PRD §3.1: 'The server also mints Case.docket_number in the
        format FC-YYYY-NNNNNN.'

        Claim: docket_number matches the literal format
        FC-YYYY-NNNNNN.
        """
        case = create_case()
        assert_docket_number_format(case["docket_number"])

    def test_answer_deadline_is_created_at_plus_30_days(
        self, api,
    ):
        """PRD §3.1: 'pins Case.answer_deadline_at to exactly thirty
        days after the case's created_at timestamp.'

        Claim: answer_deadline_at == created_at + 30 days.
        """
        case = create_case()
        created = parse_iso(case["created_at"])
        deadline = parse_iso(case["answer_deadline_at"])
        delta = deadline - created
        assert delta == timedelta(days=ANSWER_WINDOW_DAYS), (
            f"answer_deadline_at must be exactly created_at + "
            f"{ANSWER_WINDOW_DAYS} days; got delta={delta}"
        )

    def test_both_parties_minted_with_correct_roles(
        self, api,
    ):
        """PRD §3.1: 'mints two Party rows (one with role PETITIONER
        and one with role RESPONDENT)'.

        Claim: GET /cases/{id}/parties returns exactly two rows whose
        roles are PETITIONER and RESPONDENT.
        """
        case = create_case()
        res = api.list_parties(case["id"], TEST_USERS["judge_headers"])
        body = res.json()
        data = body["data"]
        assert isinstance(data, list)
        roles = sorted([p["role"] for p in data])
        assert roles == ["PETITIONER", "RESPONDENT"], (
            f"expected exactly Petitioner + Respondent parties; "
            f"got {roles}"
        )

    def test_respondent_has_served_at_petitioner_does_not(
        self, api,
    ):
        """PRD §3.1: 'stamps Party.served_at = now() on the
        respondent's row (the petitioner's served_at remains null).'

        Claim: respondent.served_at is non-null; petitioner.served_at
        is null.
        """
        case = create_case()
        res = api.list_parties(case["id"], TEST_USERS["judge_headers"])
        parties = res.json()["data"]
        by_role = {p["role"]: p for p in parties}
        assert by_role["RESPONDENT"]["served_at"], (
            "respondent must have served_at set; got "
            f"{by_role['RESPONDENT'].get('served_at')!r}"
        )
        assert by_role["PETITIONER"].get("served_at") in (None, ""), (
            "petitioner must have served_at null; got "
            f"{by_role['PETITIONER'].get('served_at')!r}"
        )

    def test_has_filed_answer_initialized_false_on_both(
        self, api,
    ):
        """PRD §3.1: 'The Party.has_filed_answer flag is initialized
        to false on both rows.'

        Claim: both parties' has_filed_answer is False on creation.
        """
        case = create_case()
        res = api.list_parties(case["id"], TEST_USERS["judge_headers"])
        for p in res.json()["data"]:
            assert p["has_filed_answer"] is False, (
                f"Party role={p['role']} has_filed_answer must be "
                f"false on creation; got {p['has_filed_answer']!r}"
            )


# ===========================================================================
# Validation: separation must be strictly after marriage — PRD §3.1
# ===========================================================================
class TestSeparationBeforeMarriage:

    def test_separation_equal_to_marriage_rejected(
        self, api, petitioner_fallback_headers,
    ):
        """PRD §3.1: 'The server validates that separation_date is
        strictly later than marriage_date; if not, it rejects with
        ERR_SEPARATION_BEFORE_MARRIAGE (HTTP 422).'

        Claim: separation_date == marriage_date is rejected.
        """
        payload = create_case_payload(
            marriage_date="2020-01-01",
            separation_date="2020-01-01",
        )
        res = api.create_case(payload, petitioner_fallback_headers)
        validate_error(
            res, "ERR_SEPARATION_BEFORE_MARRIAGE",
            expected_status=422,
        )

    def test_separation_before_marriage_rejected(
        self, api, petitioner_fallback_headers,
    ):
        """PRD §3.1: 'The server validates that separation_date is
        strictly later than marriage_date; if not, it rejects with
        ERR_SEPARATION_BEFORE_MARRIAGE (HTTP 422).'

        Claim: separation_date < marriage_date is rejected.
        """
        payload = create_case_payload(
            marriage_date="2020-01-01",
            separation_date="2019-12-31",
        )
        res = api.create_case(payload, petitioner_fallback_headers)
        validate_error(
            res, "ERR_SEPARATION_BEFORE_MARRIAGE",
            expected_status=422,
        )

    def test_separation_one_day_after_marriage_accepted(
        self, api,
    ):
        """PRD §3.1: 'The server validates that separation_date is
        strictly later than marriage_date'.

        Claim: separation_date = marriage_date + 1 day is accepted.
        """
        case = create_case(
            marriage_date="2020-01-01",
            separation_date="2020-01-02",
            has_minor_children=False,
        )
        assert_case(case)
