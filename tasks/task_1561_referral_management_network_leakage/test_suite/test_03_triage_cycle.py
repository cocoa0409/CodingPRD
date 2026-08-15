"""Triage: request-info/resubmit cycle, accept/reject guards, SLA constants."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_referral_payload, cancel_referral_payload,
    create_plan, create_provider, create_patient, create_referral,
    accept_referral, get_referral, set_clock,
    make_referring_provider_headers,
    assert_referral, assert_instant_equals,
    TEST_USERS,
)

COORD = TEST_USERS["coordinator_headers"]


def _bootstrap():
    plan = create_plan()
    provider = create_provider()
    patient = create_patient(plan["id"])
    return plan, provider, patient


class TestNeedsInfoResubmitCycle:
    def test_first_cycle_applies_updates(self, api):
        """PRD §3.3: "Requesting information moves the referral to `NEEDS_INFO` and
        stores the coordinator's note in `needs_info_note`; only a referral currently
        in `PENDING_TRIAGE` can be sent back this way, otherwise `ERR_INVALID_STATE`."
        PRD §3.3: "Resubmission returns the referral to `PENDING_TRIAGE` and applies
        whichever of the optional updates were supplied: a revised `diagnosis_code`,
        a revised `urgency`, a revised `in_network_preference`, or a revised
        `insurance_plan_id`. Fields not supplied remain as they were."

        Design: Difficulty/non_linear_state_machine/needs_info_resubmit_cycle
        """
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"], urgency="ROUTINE")

        res = api.request_info(referral["id"], {"note": "Need recent labs"}, COORD)
        after_info = validate_success(res)
        assert after_info["status"] == "NEEDS_INFO"
        assert after_info["needs_info_note"] == "Need recent labs"

        res = api.resubmit_referral(
            referral["id"], {"diagnosis_code": "I11"},
            make_referring_provider_headers(provider["id"]),
        )
        after_resubmit = validate_success(res)
        assert after_resubmit["status"] == "PENDING_TRIAGE"
        assert after_resubmit["diagnosis_code"] == "I11"
        assert after_resubmit["urgency"] == "ROUTINE", "Fields not supplied remain as they were"

    def test_two_cycles_then_accept(self, api):
        """PRD §3.3: "Resubmission returns the referral to `PENDING_TRIAGE` and
        applies whichever of the optional updates were supplied".
        PRD §3.3: "Accepting moves it to `ACCEPTED` and performs three bookkeeping
        steps ... and the prior-auth dimension is evaluated (see §3.4)."
        PRD §3.4: "If such a rule exists, `auth_status` becomes `AUTH_REQUIRED`;
        otherwise it becomes `NOT_REQUIRED`."
        PRD §2.4: "`version`, an integer starting at 1 that increments by exactly 1
        on every mutation of that resource."

        Design: Difficulty/non_linear_state_machine/needs_info_resubmit_cycle
        """
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"], urgency="ROUTINE")

        validate_success(api.request_info(referral["id"], {"note": "Need recent labs"}, COORD))
        validate_success(api.resubmit_referral(
            referral["id"], {"diagnosis_code": "I11"},
            make_referring_provider_headers(provider["id"]),
        ))
        validate_success(api.request_info(referral["id"], {"note": "Clarify urgency"}, COORD))
        resubmit2 = validate_success(api.resubmit_referral(
            referral["id"], {"urgency": "URGENT"},
            make_referring_provider_headers(provider["id"]),
        ))
        assert resubmit2["status"] == "PENDING_TRIAGE"
        assert resubmit2["urgency"] == "URGENT"

        accepted = validate_success(api.accept_referral(referral["id"], COORD))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["auth_status"] == "NOT_REQUIRED", "No ACTIVE prior-auth rule exists"
        assert accepted["version"] == 6, (
            "create(1) -> request-info(2) -> resubmit(3) -> request-info(4) -> "
            "resubmit(5) -> accept(6)"
        )


class TestAcceptRejectGuards:
    def test_double_accept_rejected_invalid_state(self, api):
        """PRD §3.3: "Accepting moves it to `ACCEPTED`..." (defined only from
        `PENDING_TRIAGE`).
        PRD §2.7: "Seventh, state preconditions of the invoked transition (priority 7
        — `ERR_INVALID_STATE`, ...)".
        PRD §2.4: "`version`, an integer starting at 1 that increments by exactly 1
        on every mutation of that resource."

        Design: Corner/state_machines/double_accept_rejected_invalid_state
        """
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"])
        accepted = accept_referral(referral["id"])
        assert accepted["version"] == 2

        res = api.accept_referral(referral["id"], COORD)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        after = get_referral(referral["id"])
        assert after["version"] == 2, "A rejected call must not mutate the referral"
        assert after["status"] == "ACCEPTED"

    def test_cancel_rejected_referral_rejected(self, api):
        """PRD §3.3: "Rejecting moves it to the terminal `REJECTED` state, also only
        from `PENDING_TRIAGE`."
        PRD §3.6: "either the owning `ReferringProvider` or any `ReferralCoordinator`
        may cancel a referral that is not yet terminal — `PENDING_TRIAGE`,
        `NEEDS_INFO`, `ACCEPTED`, `SCHEDULED`, `VISIT_COMPLETED`, or
        `PENDING_VERIFICATION` are all cancellable, anything else fails with
        `ERR_INVALID_STATE`".

        Design: Corner/state_machines/cancel_rejected_referral_rejected
        """
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"])
        validate_success(api.reject_referral(referral["id"], {"reason": "Duplicate order"}, COORD))

        res = api.cancel_referral(
            referral["id"], cancel_referral_payload("PATIENT_DECLINED"), COORD
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestAcceptResponseAndSla:
    def test_accept_response_reflects_mutation_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."
        PRD §3.3: "Accepting moves it to `ACCEPTED` and performs three bookkeeping
        steps: `triaged_at` is stamped with the current clock; `sla_due_at` is
        computed as `triaged_at` plus the urgency's service-level window — 2 days for
        `STAT`, 7 days for `URGENT`, 30 days for `ROUTINE`, using exact second
        arithmetic; and the prior-auth dimension is evaluated (see §3.4)."
        PRD §3.4: "If such a rule exists, `auth_status` becomes `AUTH_REQUIRED`;
        otherwise it becomes `NOT_REQUIRED`."

        Design: Corner/consistency_model/accept_response_reflects_mutation_immediately
        """
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap()
        referral = create_referral(provider["id"], patient["id"], urgency="ROUTINE")

        res = api.accept_referral(referral["id"], COORD)
        accepted = validate_success(res)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["auth_status"] == "NOT_REQUIRED"
        assert_instant_equals(accepted["sla_due_at"], "2026-08-31T00:00:00Z",
                              label="sla_due_at (ROUTINE = triaged_at + 30 days)")
        assert accepted["version"] == 2

    def test_sla_days_constants_applied_per_urgency(self, api):
        """PRD §3.3: "`sla_due_at` is computed as `triaged_at` plus the urgency's
        service-level window — 2 days for `STAT`, 7 days for `URGENT`, 30 days for
        `ROUTINE`, using exact second arithmetic".

        Design: Corner/calculations/sla_days_constants_applied_per_urgency
        """
        set_clock("2026-08-01T00:00:00Z")
        plan, provider, patient = _bootstrap()
        rs = create_referral(provider["id"], patient["id"], urgency="STAT", diagnosis_code="I21")
        ru = create_referral(provider["id"], patient["id"], urgency="URGENT", diagnosis_code="I20")
        rr = create_referral(provider["id"], patient["id"], urgency="ROUTINE", diagnosis_code="I10")

        s = accept_referral(rs["id"])
        u = accept_referral(ru["id"])
        r = accept_referral(rr["id"])
        assert_instant_equals(s["sla_due_at"], "2026-08-03T00:00:00Z", label="STAT sla_due_at")
        assert_instant_equals(u["sla_due_at"], "2026-08-08T00:00:00Z", label="URGENT sla_due_at")
        assert_instant_equals(r["sla_due_at"], "2026-08-31T00:00:00Z", label="ROUTINE sla_due_at")
