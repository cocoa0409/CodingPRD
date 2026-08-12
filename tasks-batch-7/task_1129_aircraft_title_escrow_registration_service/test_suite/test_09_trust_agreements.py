"""Owner-trust agreements: date-range validation, trustee qualification,
overlap guard with adjacency, and the reject/revise negotiation cycle
(PRD §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_trust_agreement,
    assert_trust_agreement,
    create_aircraft,
    create_party,
    create_trust_agreement,
    create_trust_agreement_payload,
    submit_trust_agreement,
    validate_error,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _setup_aircraft_and_trustee(api, n_number, serial, verified=True):
    aircraft = validate_success(
        api.create_aircraft(
            {"n_number": n_number, "serial_number": serial,
             "make_model": "Cirrus SR22", "year": 2020},
            OFFICER,
        ),
        201,
    )
    trustee = validate_success(
        api.create_party(
            {"party_type": "TRUSTEE", "legal_name": "Trustee Co",
             "is_citizenship_verified": verified},
            OFFICER,
        ),
        201,
    )
    return aircraft, trustee


class TestTrustDateRange:
    def test_effective_not_before_expiry_rejected(self, api):
        """PRD §3.7: "The `effective_date` must be strictly earlier than
        `expiry_date`; otherwise creation is rejected with
        `ERR_INVALID_DATE_RANGE`."

        Design: Corner/validations/v_trust_date_range_returns_invalid_date_range
        """
        aircraft, trustee = _setup_aircraft_and_trustee(api, "N142TD", "S-27")
        payload = create_trust_agreement_payload(
            aircraft["id"], trustee["id"],
            effective_date="2026-12-31", expiry_date="2026-01-01",
        )
        res = api.create_trust_agreement(payload, OFFICER)
        validate_error(res, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=422)
        data = validate_success(
            api.list_aircraft_trust_agreements(aircraft["id"], OFFICER), 200
        )
        assert data == []


class TestTrusteeQualification:
    def test_submit_with_unverified_trustee_rejected(self, api):
        """PRD §3.7: "Submitting the agreement requires that the trustee's
        `is_citizenship_verified` is `true`; otherwise the submit is rejected with
        `ERR_TRUSTEE_NOT_QUALIFIED`."

        Design: Corner/validations/v_trustee_not_qualified_on_submit
        """
        aircraft, trustee = _setup_aircraft_and_trustee(
            api, "N145TQ", "S-30", verified=False,
        )
        trust = create_trust_agreement(aircraft["id"], trustee["id"])
        res = api.submit_trust_agreement(trust["id"], OFFICER)
        validate_error(res, ApiErrorId.ERR_TRUSTEE_NOT_QUALIFIED, expected_status=422)
        after = validate_success(api.get_trust_agreement(trust["id"], OFFICER), 200)
        assert after["status"] == "DRAFT"


class TestTrustOverlapOnAccept:
    def test_strict_overlap_rejected_but_adjacent_term_accepted(self, api):
        """PRD §3.7: "Acceptance is an `EscrowManager` action and carries the
        trust-overlap guard: there must be no other `ACCEPTED` `TrustAgreement`
        for the same aircraft whose `[effective_date, expiry_date]` interval
        strictly overlaps the candidate's interval."
        PRD §3.7: "Touching endpoints — one agreement's `expiry_date` equal to
        another's `effective_date` — are permitted and do not constitute overlap."

        T1 ACCEPTED for 2026-01-01..2026-06-30; T2 (2026-06-01..2026-12-31) shares
        a strict interior -> rejected; T3 (2026-07-01..2026-12-31) does not
        overlap the closed T1 interval -> accepted.

        Design: Corner/validations/v_trust_overlap_on_accept
        """
        aircraft, trustee = _setup_aircraft_and_trustee(api, "N144TO", "S-29")

        t1 = create_trust_agreement(
            aircraft["id"], trustee["id"], beneficiary_name="Ben One",
            effective_date="2026-01-01", expiry_date="2026-06-30",
        )
        submit_trust_agreement(t1["id"])
        accepted_t1 = accept_trust_agreement(t1["id"])
        assert accepted_t1["status"] == "ACCEPTED"

        t2 = create_trust_agreement(
            aircraft["id"], trustee["id"], beneficiary_name="Ben Two",
            effective_date="2026-06-01", expiry_date="2026-12-31",
        )
        submit_trust_agreement(t2["id"])
        res = api.accept_trust_agreement(t2["id"], MANAGER)
        validate_error(res, ApiErrorId.ERR_TRUST_OVERLAP, expected_status=409)

        t3 = create_trust_agreement(
            aircraft["id"], trustee["id"], beneficiary_name="Ben Three",
            beneficiary_citizenship="US_CITIZEN",
            effective_date="2026-07-01", expiry_date="2026-12-31",
        )
        submit_trust_agreement(t3["id"])
        accepted_t3 = validate_success(api.accept_trust_agreement(t3["id"], MANAGER), 200)
        assert accepted_t3["status"] == "ACCEPTED"


class TestTrustRejectReviseCycle:
    def _setup_submitted_trust(self, api, n_number="N400TA", serial="S-400"):
        aircraft, trustee = _setup_aircraft_and_trustee(api, n_number, serial)
        trust = create_trust_agreement(aircraft["id"], trustee["id"])
        submit_trust_agreement(trust["id"])
        return trust

    def test_reject_then_revise_returns_draft_with_new_dates(self, api):
        """PRD §3.7: "An `EscrowManager` may instead reject the agreement, moving
        it to `REJECTED`; an `EscrowOfficer` may then revise a `REJECTED`
        agreement back to `DRAFT`, optionally supplying replacement
        `effective_date` and `expiry_date` values."
        PRD §3.7: "When dates are supplied on revise they must again satisfy
        `effective_date` strictly earlier than `expiry_date`, and `submitted_at`
        is cleared."

        Design: Difficulty/non_linear_state_machine/n2_trust_reject_revise_cycle
        """
        trust = self._setup_submitted_trust(api)
        rejected = validate_success(api.reject_trust_agreement(trust["id"], MANAGER), 200)
        assert rejected["status"] == "REJECTED"

        revised = validate_success(
            api.revise_trust_agreement(
                trust["id"],
                {"effective_date": "2026-02-01", "expiry_date": "2026-12-31"},
                OFFICER,
            ),
            200,
        )
        assert_trust_agreement(revised)
        assert revised["status"] == "DRAFT"
        assert revised["effective_date"] == "2026-02-01"
        assert revised["submitted_at"] is None

    def test_revised_trust_completes_loop_to_accepted(self, api):
        """PRD §3.7: "A successful submit stamps `submitted_at` to the logical
        instant and moves the agreement from `DRAFT` to `SUBMITTED`."
        PRD §3.7: "Acceptance moves the agreement from `SUBMITTED` to `ACCEPTED`
        and recomputes posture on every `EscrowFile` for the same aircraft whose
        `requires_trust` is `true`."

        The DRAFT -> SUBMITTED -> REJECTED -> DRAFT -> SUBMITTED -> ACCEPTED loop
        terminates.

        Design: Difficulty/non_linear_state_machine/n2_trust_reject_revise_cycle
        """
        trust = self._setup_submitted_trust(api, n_number="N400TB", serial="S-401")
        validate_success(api.reject_trust_agreement(trust["id"], MANAGER), 200)
        validate_success(
            api.revise_trust_agreement(
                trust["id"],
                {"effective_date": "2026-02-01", "expiry_date": "2026-12-31"},
                OFFICER,
            ),
            200,
        )
        validate_success(api.submit_trust_agreement(trust["id"], OFFICER), 200)
        accepted = validate_success(api.accept_trust_agreement(trust["id"], MANAGER), 200)
        assert accepted["status"] == "ACCEPTED"
