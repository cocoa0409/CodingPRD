"""Prior authorization: evaluation on accept, auth lifecycle, booking gate, expiry."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_plan, create_provider, create_patient, create_specialist,
    create_participation, create_auth_rule, create_referral, accept_referral,
    assign_specialist, get_referral, set_clock, book_appointment,
    run_aging_sweep, list_referral_authorization_records,
    assert_authorization_record, assert_instant_equals,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


class TestAuthEvaluationOnAccept:
    def test_auth_evaluation_on_accept(self, api):
        """PRD §3.4: "During the accept transition the system looks for an `ACTIVE`
        prior-auth rule matching the referral's `specialty` and `insurance_plan_id`
        with `requires_auth` true. If such a rule exists, `auth_status` becomes
        `AUTH_REQUIRED`; otherwise it becomes `NOT_REQUIRED`."
        PRD §3.3: "`sla_due_at` is computed as `triaged_at` plus the urgency's
        service-level window — 2 days for `STAT`, 7 days for `URGENT`, 30 days for
        `ROUTINE`, using exact second arithmetic".

        Design: Corner/state_machines/auth_evaluation_on_accept
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        create_auth_rule("CARDIOLOGY", plan["id"], requires_auth=True, auth_validity_days=10)
        provider = create_provider()
        patient = create_patient(plan["id"])
        r1 = create_referral(provider["id"], patient["id"], specialty="CARDIOLOGY")
        r2 = create_referral(provider["id"], patient["id"], specialty="DERMATOLOGY",
                             diagnosis_code="L20")

        a1 = accept_referral(r1["id"])
        a2 = accept_referral(r2["id"])
        assert a1["auth_status"] == "AUTH_REQUIRED", "Matching requires_auth rule flags the referral"
        assert a2["auth_status"] == "NOT_REQUIRED", "No matching rule -> NOT_REQUIRED"
        assert_instant_equals(a1["sla_due_at"], "2026-08-31T00:00:00Z", label="r1 sla_due_at")
        assert_instant_equals(a2["sla_due_at"], "2026-08-31T00:00:00Z", label="r2 sla_due_at")


class TestAuthLifecycle:
    def test_auth_denied_retry_cycle_and_obtained(self, api):
        """PRD §3.4: "From `AUTH_REQUIRED` — and equally from `AUTH_DENIED` or
        `AUTH_EXPIRED` — a `ReferralCoordinator` may submit the case to the payer,
        moving `auth_status` to `AUTH_PENDING`."
        PRD §3.4: "Recording `DENIED` moves `auth_status` to `AUTH_DENIED` and creates
        no record."
        PRD §3.4: "Recording `OBTAINED` requires a non-empty `auth_number` in the
        payload — its absence fails with `ERR_INVALID_REQUEST` — and creates an
        `AuthorizationRecord` stamped with the `referral_id` of the referral it
        belongs to, the `auth_number`, an `obtained_at` of the current clock, and an
        `expires_on` computed as `obtained_at` plus the matching rule's
        `auth_validity_days` using exact second arithmetic; the record starts `ACTIVE`
        and the referral's `auth_status` becomes `AUTH_OBTAINED`."

        Design: Corner/state_machines/auth_denied_retry_cycle_and_obtained
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        create_auth_rule("CARDIOLOGY", plan["id"], requires_auth=True, auth_validity_days=10)
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"])
        accepted = accept_referral(referral["id"])
        assert accepted["auth_status"] == "AUTH_REQUIRED"

        pending = validate_success(api.submit_auth(referral["id"], COORD))
        assert pending["auth_status"] == "AUTH_PENDING"

        denied = validate_success(api.record_auth_outcome(
            referral["id"], {"outcome": "DENIED"}, COORD
        ))
        assert denied["auth_status"] == "AUTH_DENIED"
        assert list_referral_authorization_records(referral["id"]) == [], (
            "DENIED creates no record"
        )

        pending2 = validate_success(api.submit_auth(referral["id"], COORD))
        assert pending2["auth_status"] == "AUTH_PENDING", "Retry from AUTH_DENIED is allowed"

        obtained = validate_success(api.record_auth_outcome(
            referral["id"], {"outcome": "OBTAINED", "auth_number": "AUTH-123"}, COORD
        ))
        assert obtained["auth_status"] == "AUTH_OBTAINED"

        records = list_referral_authorization_records(referral["id"])
        assert len(records) == 1
        record = records[0]
        assert_authorization_record(record)
        assert record["auth_number"] == "AUTH-123"
        assert record["status"] == "ACTIVE"
        assert_instant_equals(record["obtained_at"], "2026-08-01T00:00:00Z",
                              label="obtained_at (current clock)")
        assert_instant_equals(record["expires_on"], "2026-08-11T00:00:00Z",
                              label="expires_on (obtained_at + 10 days)")


class TestBookingAuthGate:
    def test_booking_blocked_while_auth_required(self, api):
        """PRD §3.6: "Authorization first: the referral's `auth_status` must be
        `NOT_REQUIRED`, or `AUTH_OBTAINED` with the latest `AuthorizationRecord` still
        `ACTIVE`; booking against `AUTH_REQUIRED`, `AUTH_PENDING`, `AUTH_DENIED`, or
        `AUTH_EXPIRED` — or against an obtained authorization whose record has lapsed
        — fails with `ERR_AUTH_NOT_SATISFIED`."

        Design: Corner/state_machines/booking_blocked_while_auth_required
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        create_auth_rule("CARDIOLOGY", plan["id"], requires_auth=True, auth_validity_days=10)
        specialist = create_specialist()
        create_participation(specialist["id"], plan["id"])
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"])
        accepted = accept_referral(referral["id"])
        assert accepted["auth_status"] == "AUTH_REQUIRED"
        assigned = assign_specialist(referral["id"], specialist["id"])

        res = api.book_appointment(
            referral["id"],
            {
                "expected_referral_version": assigned["version"],
                "scheduled_start": "2026-08-02T10:00:00Z",
                "scheduled_end": "2026-08-02T11:00:00Z",
            },
            COORD,
        )
        validate_error(res, ApiErrorId.ERR_AUTH_NOT_SATISFIED, expected_status=409)
        assert get_referral(referral["id"])["status"] == "ACCEPTED"


class TestAuthRecordExpiry:
    def test_auth_record_expiry_via_sweep(self, api):
        """PRD §3.4: "Authorizations age out through the aging sweep: when a referral
        is in `AUTH_OBTAINED` with main status `ACCEPTED` or `SCHEDULED`, and its
        latest `AuthorizationRecord` is still `ACTIVE`, and now has reached or passed
        that record's `expires_on` — the boundary is inclusive — the record flips to
        `EXPIRED` and the referral's `auth_status` becomes `AUTH_EXPIRED`, from which
        a fresh submission can restart the cycle."
        PRD §3.8: "The sweep reports back the expired referral ids, how many referrals
        expired, and the expired authorization record ids."

        Design: Corner/state_machines/auth_record_expiry_via_sweep
        """
        set_clock("2026-08-01T00:00:00Z")
        plan = create_plan()
        create_auth_rule("CARDIOLOGY", plan["id"], requires_auth=True, auth_validity_days=2)
        provider = create_provider()
        patient = create_patient(plan["id"])
        referral = create_referral(provider["id"], patient["id"])
        accept_referral(referral["id"])
        validate_success(api.submit_auth(referral["id"], COORD))
        validate_success(api.record_auth_outcome(
            referral["id"], {"outcome": "OBTAINED", "auth_number": "AUTH-9"}, COORD
        ))
        records = list_referral_authorization_records(referral["id"])
        assert len(records) == 1 and records[0]["status"] == "ACTIVE"

        # ROUTINE sla_due_at is 2026-08-31, so the referral itself does not expire.
        set_clock("2026-08-03T00:00:00Z")  # exactly expires_on (inclusive boundary)
        sweep = validate_success(api.run_aging_sweep(COORD))

        after = get_referral(referral["id"])
        assert after["auth_status"] == "AUTH_EXPIRED", (
            "now == expires_on is inclusive: the record must age out"
        )
        assert after["status"] == "ACCEPTED", "ROUTINE SLA not yet reached; referral unaffected"
        records_after = list_referral_authorization_records(referral["id"])
        assert len(records_after) == 1
        assert records_after[0]["status"] == "EXPIRED"
