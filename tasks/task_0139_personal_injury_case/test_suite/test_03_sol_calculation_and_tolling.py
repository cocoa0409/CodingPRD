"""Statute of Limitations: computation, minor-tail, and tolling.

PRD §3.2 and §2.10.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    adult_dob_for,
    create_case,
    create_client,
    get_case,
    minor_dob_for,
    parse_iso_date,
    recent_incident_date,
    toll_case,
    validate_error,
    validate_success,
)


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # leap year corner — fall back to Feb 28
        return d.replace(year=d.year + years, day=28)


class TestSolBaseDeadline:

    def test_ca_auto_uses_two_years(self, api):
        """PRD §3.2: "California auto cases use 2 years".

        Claim: incident_date + 2 years == sol_deadline (no tolling, no
        minor tail).
        """
        incident_iso = recent_incident_date(days_ago=90)
        client = create_client(date_of_birth=adult_dob_for(incident_iso))
        case = create_case(
            client["id"], incident_date=incident_iso,
            incident_type="AUTO", jurisdiction_state="CA",
        )
        expected = _add_years(parse_iso_date(incident_iso), 2)
        assert case["sol_deadline"] == expected.isoformat(), (
            f"CA AUTO base years = 2; expected sol_deadline "
            f"{expected.isoformat()}, got {case['sol_deadline']}"
        )

    def test_ca_medical_malpractice_uses_three_years(self, api):
        """PRD §3.2: "California medical-malpractice cases use 3 years".

        Claim: CA MEDICAL_MALPRACTICE → incident_date + 3y.
        """
        incident_iso = recent_incident_date(days_ago=90)
        client = create_client(date_of_birth=adult_dob_for(incident_iso))
        case = create_case(
            client["id"], incident_date=incident_iso,
            incident_type="MEDICAL_MALPRACTICE", jurisdiction_state="CA",
        )
        expected = _add_years(parse_iso_date(incident_iso), 3)
        assert case["sol_deadline"] == expected.isoformat()

    def test_ny_auto_uses_three_years(self, api):
        """PRD §3.2: "New York auto, slip-and-fall, product-liability,
        premises, and dog-bite cases each use 3 years".

        Claim: NY AUTO → incident_date + 3y.
        """
        incident_iso = recent_incident_date(days_ago=90)
        client = create_client(
            date_of_birth=adult_dob_for(incident_iso),
            state_of_residence="NY",
        )
        case = create_case(
            client["id"], incident_date=incident_iso,
            incident_type="AUTO", jurisdiction_state="NY",
        )
        expected = _add_years(parse_iso_date(incident_iso), 3)
        assert case["sol_deadline"] == expected.isoformat()

    def test_tx_auto_uses_two_years(self, api):
        """PRD §3.2: "Texas cases of every type use 2 years".

        Claim: TX AUTO → incident_date + 2y.
        """
        incident_iso = recent_incident_date(days_ago=90)
        client = create_client(
            date_of_birth=adult_dob_for(incident_iso),
            state_of_residence="TX",
        )
        case = create_case(
            client["id"], incident_date=incident_iso,
            incident_type="AUTO", jurisdiction_state="TX",
        )
        expected = _add_years(parse_iso_date(incident_iso), 2)
        assert case["sol_deadline"] == expected.isoformat()


class TestMinorTail:

    def test_ca_minor_takes_later_of_base_and_minor_tail(self, api):
        """PRD §3.2: "if the client's is_minor_at_incident is true, the
        system computes a minor-tail deadline by adding 18 years plus a
        jurisdiction-specific minor tail to the client's date_of_birth
        (California's minor tail is 2 years ...) and replaces the base
        deadline with whichever of the base deadline and the minor-tail
        deadline is later."

        Claim: CA AUTO minor case → max(incident+2y, dob+20y).
        """
        incident_iso = recent_incident_date(days_ago=90)
        # 14-year-old: dob+20y is far later than incident+2y
        dob_iso = minor_dob_for(incident_iso, age_at_incident=14)
        client = create_client(date_of_birth=dob_iso)
        case = create_case(
            client["id"], incident_date=incident_iso,
            incident_type="AUTO", jurisdiction_state="CA",
        )
        dob = parse_iso_date(dob_iso)
        incident = parse_iso_date(incident_iso)
        # CA minor_tail = 2; minor deadline = dob + 18 + 2 = dob + 20y.
        minor_deadline = _add_years(dob, 18 + 2)
        base_deadline = _add_years(incident, 2)
        expected = max(minor_deadline, base_deadline)
        assert case["sol_deadline"] == expected.isoformat(), (
            f"PRD §3.2: minor-tail max — expected "
            f"{expected.isoformat()}, got {case['sol_deadline']}"
        )

    def test_ny_minor_tail_is_three_years(self, api):
        """PRD §3.2: "California's minor tail is 2 years, New York's
        is 3 years, and Texas's is 2 years".

        Claim: NY minor case → max(incident+base, dob+18+3y).
        """
        incident_iso = recent_incident_date(days_ago=90)
        dob_iso = minor_dob_for(incident_iso, age_at_incident=14)
        client = create_client(
            date_of_birth=dob_iso, state_of_residence="NY",
        )
        case = create_case(
            client["id"], incident_date=incident_iso,
            incident_type="AUTO", jurisdiction_state="NY",
        )
        dob = parse_iso_date(dob_iso)
        minor_deadline = _add_years(dob, 18 + 3)
        base_deadline = _add_years(parse_iso_date(incident_iso), 3)
        expected = max(minor_deadline, base_deadline)
        assert case["sol_deadline"] == expected.isoformat()


class TestTolling:

    def test_toll_adds_days_to_deadline(
        self, api, managing_partner_headers,
    ):
        """PRD §3.2: "the system adds additional_days to sol_tolled_days
        and reruns the deadline calculation."

        Claim: After a 10-day toll, sol_tolled_days == 10 and
        sol_deadline = base_deadline + 10 days.
        """
        incident_iso = recent_incident_date(days_ago=60)
        client = create_client(date_of_birth=adult_dob_for(incident_iso))
        case = create_case(client["id"], incident_date=incident_iso)
        base_deadline = case["sol_deadline"]
        # Apply toll
        toll_case(case["id"], 10, reason="incapacity")
        refreshed = get_case(case["id"])
        assert refreshed["sol_tolled_days"] == 10
        expected_date = (
            parse_iso_date(base_deadline) + timedelta(days=10)
        ).isoformat()
        assert refreshed["sol_deadline"] == expected_date, (
            f"PRD §3.2: expected base + 10 days "
            f"= {expected_date}, got {refreshed['sol_deadline']}"
        )

    def test_multiple_tolls_accumulate_exactly(
        self, api, managing_partner_headers,
    ):
        """PRD §3.2: "the system adds additional_days to sol_tolled_days
        and reruns the deadline calculation."

        Claim: Two tolls of 7 and 3 days accumulate to
        sol_tolled_days==10 and shift the deadline by exactly 10 days.
        """
        incident_iso = recent_incident_date(days_ago=60)
        client = create_client(date_of_birth=adult_dob_for(incident_iso))
        case = create_case(client["id"], incident_date=incident_iso)
        base_deadline = case["sol_deadline"]
        toll_case(case["id"], 7, reason="incapacity-1")
        toll_case(case["id"], 3, reason="incapacity-2")
        refreshed = get_case(case["id"])
        assert refreshed["sol_tolled_days"] == 10
        expected_date = (
            parse_iso_date(base_deadline) + timedelta(days=10)
        ).isoformat()
        assert refreshed["sol_deadline"] == expected_date


class TestRoleGuardOnToll:

    def test_paralegal_cannot_toll(
        self, api, paralegal_headers,
    ):
        """PRD §2.1: "If the role is recognized but is not authorized
        for the requested endpoint (per the RBAC implied by §4 and the
        workflow narratives in §3), the request is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: Paralegal toll → ERR_FORBIDDEN. PRD §4 lists toll as
        Attorney + ManagingPartner only.
        """
        incident_iso = recent_incident_date(days_ago=60)
        client = create_client(date_of_birth=adult_dob_for(incident_iso))
        case = create_case(client["id"], incident_date=incident_iso)
        resp = api.toll_case(
            case["id"], {"additional_days": 1, "reason": "x"},
            paralegal_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
