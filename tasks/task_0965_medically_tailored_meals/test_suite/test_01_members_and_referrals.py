"""Member enrollment/lifecycle and referral intake workflows (PRD §3.1, §3.2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_member_payload, create_referral_payload,
    create_member, activate_member, transition_member,
    create_referral, decide_referral,
    setup_scheduled_delivery, get_reauthorization, get_delivery,
)


class TestMemberCreation:
    def test_member_create_initial_state_and_computed_defaults(
            self, api, care_coordinator_headers):
        """PRD §3.1: "New members start in `INTAKE` status, with both adherence
        percentages initialized to 100.00 and `oop_accumulator_cents` at zero."

        Design: Corner/entities/member_create_initial_state_and_computed_defaults
        """
        resp = api.create_member(create_member_payload(
            full_name="C One", payer_member_id="W-C1", allergies=["PEANUT"]),
            care_coordinator_headers)
        member = validate_success(resp, 201)
        assert member["status"] == "INTAKE"
        assert member["adherence_delivered_pct"] == pytest.approx(100.00)
        assert member["adherence_confirmed_pct"] == pytest.approx(100.00)
        assert member["oop_accumulator_cents"] == 0

    def test_member_list_pagination_envelope(self, api, care_coordinator_headers,
                                             dietitian_headers):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100."
        PRD §2.3: "list responses carry `limit`, `offset`, `total_count`, and
        `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/member_list_pagination_envelope
        """
        create_member(full_name="C Two", payer_member_id="W-C2")
        create_member(full_name="C Three", payer_type="MEDICARE_ADVANTAGE",
                      payer_member_id="MA-C3", income_fpl_percent=160,
                      household_size=1)
        resp = api.list_members(dietitian_headers, params={"limit": 1})
        data, meta = validate_paginated(resp)
        assert len(data) == 1, f"limit=1 must return one row, got {len(data)}"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1

    def test_member_get_not_found_returns_404(self, api, dietitian_headers):
        """PRD §2.8: "every path identifier must resolve, validated left to
        right (`ERR_NOT_FOUND`, 404)."

        Design: Corner/entities/member_get_not_found_returns_404
        """
        resp = api.get_member(NON_EXISTENT_UUID, dietitian_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestMemberStatusMachine:
    def test_member_disenrolled_reactivation_rejected(
            self, api, care_coordinator_headers):
        """PRD §3.1: "Attempting a status change on a `DISENROLLED` member is
        rejected with `ERR_MEMBER_TERMINAL`; any other state mismatch (for
        example, suspending an `INTAKE` member) is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/member_disenrolled_reactivation_rejected
        """
        member = create_member(full_name="S Three", payer_member_id="W-S3")
        transition_member(member["id"], "ACTIVE")
        transition_member(member["id"], "DISENROLLED")
        resp = api.set_member_status(member["id"], "ACTIVE", care_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_TERMINAL)
        member = validate_success(api.get_member(member["id"], care_coordinator_headers))
        assert member["status"] == "DISENROLLED"

    def test_member_version_increments_on_every_mutation(
            self, api, care_coordinator_headers):
        """PRD §2.5: "`version` (integer): a system-managed integer that
        increments by one on every mutation, including mutations caused by
        cascades and by computed-ledger updates initiated from other resources."
        PRD §3.1: "Each transition increments the member's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/member_version_increments_on_every_mutation
        """
        member = create_member(full_name="L Three", payer_member_id="W-L3")
        v1 = member["version"]
        m2 = validate_success(api.set_member_status(member["id"], "ACTIVE",
                                                    care_coordinator_headers))
        assert m2["version"] == v1 + 1, "activation must increment version by one"
        m3 = validate_success(api.set_member_status(member["id"], "SUSPENDED",
                                                    care_coordinator_headers))
        assert m3["version"] == v1 + 2, "suspension must increment version by one"
        m4 = validate_success(api.set_member_status(member["id"], "ACTIVE",
                                                    care_coordinator_headers))
        assert m4["version"] == v1 + 3, "reactivation must increment version by one"
        assert m4["status"] == "ACTIVE"


class TestReferralWorkflow:
    def test_referral_accept_from_submitted_rejected(
            self, api, care_coordinator_headers):
        """PRD §3.2: "From `TRIAGED`, a decision of `ACCEPT` moves it to
        `ACCEPTED` — but only while the current logical date has not passed
        `expires_at`; if the referral's clock has run out, acceptance is
        rejected with `ERR_REFERRAL_EXPIRED`."
        PRD §3.2: "Any decision attempted against a referral not in the required
        source state is rejected with `ERR_REFERRAL_NOT_ACTIONABLE`."

        Design: Corner/state_machines/referral_accept_from_submitted_rejected
        """
        member = create_member(full_name="S One", payer_member_id="W-S1")
        referral = create_referral(member["id"])
        resp = api.decide_referral(referral["id"], "ACCEPT", care_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_ACTIONABLE)
        referral = validate_success(
            api.get_referral(referral["id"], care_coordinator_headers))
        assert referral["status"] == "SUBMITTED", \
            "rejected ACCEPT must not move the referral out of SUBMITTED"

    def test_referral_auto_expires_on_clock_sweep(
            self, api, program_admin_headers, care_coordinator_headers):
        """PRD §2.4: "Any referral still sitting in `SUBMITTED` or `TRIAGED`
        whose `expires_at` date has been passed by the logical clock transitions
        automatically to `EXPIRED`."

        Design: Corner/state_machines/referral_auto_expires_on_clock_sweep
        """
        member = create_member(full_name="S Two", payer_member_id="W-S2")
        referral = create_referral(member["id"], expires_at="2026-05-01")
        assert referral["status"] == "SUBMITTED"
        validate_success(
            api.set_clock("2026-05-02T00:00:00Z", program_admin_headers))
        referral = validate_success(
            api.get_referral(referral["id"], care_coordinator_headers))
        assert referral["status"] == "EXPIRED"


class TestMemberDisenrollCascade:
    def test_disenroll_cascades_to_prescription_and_cycle(self, api,
                                                          dietitian_headers):
        """PRD §3.1: "Disenrollment is terminal: from either `ACTIVE` or
        `SUSPENDED`, posting a `target_status` of `DISENROLLED` fires a
        three-link cascade. First, the member's `ACTIVE` diet prescription — if
        any — is revoked, moving it to `REVOKED`. Second, because that
        prescription mutation occurred, every one of the member's menu cycles in
        `PLANNED` or `FROZEN` whose `prescription_id` points at the now-revoked
        prescription is cancelled."

        Design: Difficulty/transitive_cascade/member_disenroll_depth3_cascade
        """
        ctx = setup_scheduled_delivery(
            member_overrides={"full_name": "M Seven", "payer_member_id": "W-700"},
            route_overrides={"driver_id": "drv-4"})
        member = transition_member(ctx["member"]["id"], "DISENROLLED")
        assert member["status"] == "DISENROLLED"
        prescription = validate_success(
            api.get_prescription(ctx["prescription"]["id"], dietitian_headers))
        assert prescription["status"] == "REVOKED", \
            "link 1: the ACTIVE prescription must be revoked by disenrollment"
        cycle = validate_success(
            api.get_menu_cycle(ctx["cycle"]["id"], dietitian_headers))
        assert cycle["status"] == "CANCELLED", \
            "link 2: the FROZEN cycle pinned to the revoked prescription must cancel"

    def test_disenroll_cascades_to_delivery_and_releases_reserved_unit(self, api):
        """PRD §3.1: "Third, because each of those cycles was cancelled, every
        delivery of such a cycle in `SCHEDULED` or `OUT_FOR_DELIVERY` is
        cancelled too, and each cancelled delivery releases its reserved unit
        back onto its reauthorization."

        Design: Difficulty/transitive_cascade/member_disenroll_depth3_cascade
        """
        ctx = setup_scheduled_delivery(
            member_overrides={"full_name": "M Seven", "payer_member_id": "W-700"},
            route_overrides={"driver_id": "drv-4"})
        auth_before = get_reauthorization(ctx["authorization"]["id"])
        assert auth_before["reserved_units"] == 1
        transition_member(ctx["member"]["id"], "DISENROLLED")
        delivery = get_delivery(ctx["delivery"]["id"])
        assert delivery["status"] == "CANCELLED", \
            "link 3: the open delivery must cancel with its cycle"
        auth = get_reauthorization(ctx["authorization"]["id"])
        assert auth["reserved_units"] == 0
        assert auth["used_units"] == 0
        assert auth["available_units"] == 4
