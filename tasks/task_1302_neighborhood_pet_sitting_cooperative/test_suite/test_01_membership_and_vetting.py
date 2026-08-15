"""Membership pipeline: application, mutual references, vetting gates, suspension,
reinstatement, and removal (PRD §2.1, §2.5, §2.9, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    NON_EXISTENT_UUID, ApiErrorId,
    assert_member,
    create_member_payload, create_reference_payload, create_incident_payload,
    make_member_headers,
    bootstrap_founders, create_applicant, create_vetted_member, create_pet,
    set_clock, get_member, list_ledger,
    ADMIN, ANON,
)


class TestApplication:
    def test_member_creation_defaults(self, api):
        """PRD §3.1: "A new application lands with `vetting_status` set to `APPLIED`,
        a `reliability_score` of 50, and both `credit_balance_hours` and
        `provisional_credit_hours` at zero."

        Design: Corner/entities/member_creation_defaults_and_system_fields
        """
        res = api.create_member(create_member_payload(
            display_name="Solo Applicant", email="solo@coop.test", phone="+15550301"), ANON)
        member = validate_success(res, 201)
        assert_member(member)
        assert member["vetting_status"] == "APPLIED"
        assert member["reliability_score"] == 50
        assert member["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)
        assert member["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert member["mediator_flag"] is False
        assert member["version"] == 1
        assert member["created_at"].startswith("2026-08-01T00:00:00"), (
            f"created_at should reflect the default logical clock, got {member['created_at']}")

        fetched = validate_success(api.get_member(member["id"], ADMIN), 200)
        assert fetched["vetting_status"] == "APPLIED"
        assert fetched["reliability_score"] == 50

    def test_member_missing_email_returns_400(self, api):
        """PRD §3.1: "The applicant supplies a `display_name` (their full legal name),
        an `email` that must be unique across the cooperative compared
        case-insensitively, an `address_block` identifying their neighborhood block
        (for example `MAPLE-100`) for the residency check, and a `phone` number
        capable of receiving SMS for emergency contact."
        PRD §3.3: "violations are rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/member_creation_missing_required_email_returns_400
        """
        payload = create_member_payload(display_name="No Email", phone="+15550302")
        del payload["email"]
        res = api.create_member(payload, ANON)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        data, meta = validate_paginated(api.list_members(ADMIN))
        assert meta["total_count"] == 0, f"Expected no members persisted, got {meta['total_count']}"

    def test_anonymous_application_grant(self, api):
        """PRD §2.1: "An `Anonymous` caller is an unauthenticated applicant;
        `X-User-ID` is an opaque identifier not tied to any persisted entity, and
        the only operation open to this role is submitting a membership application."

        Design: Corner/rbac/anonymous_can_apply
        """
        res = api.create_member(create_member_payload(
            display_name="New Applicant", email="new@coop.test", phone="+15550501"), ANON)
        member = validate_success(res, 201)
        assert member["vetting_status"] == "APPLIED"


class TestVettingGates:
    def test_finalize_from_applied_rejected(self, api):
        """PRD §3.1: "Once at least two references for the applicant exist in
        `PENDING`, an administrator advances the applicant from `APPLIED` to
        `REFERENCES_PENDING`; with fewer than two the attempt fails with
        `ERR_INSUFFICIENT_REFERENCES`."
        PRD §3.1: "Finalization moves the member from `REFERENCES_PENDING` to
        `VETTED` and enforces three gates: ..."

        Design: Corner/state_machines/finalize_from_applied_returns_invalid_state
        """
        f = bootstrap_founders()
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        get_success_data(api.accept_liability(x["id"], make_member_headers(x["id"])))
        api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], attestation_text="F1 vouches for applicant X."), ADMIN)
        api.create_reference(x["id"], create_reference_payload(
            f["f2"]["id"], attestation_text="F2 vouches for applicant X."), ADMIN)

        res = api.finalize_vetting(x["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = get_member(x["id"])
        assert after["vetting_status"] == "APPLIED"
        assert after["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)
        assert list_ledger(x["id"]) == []

    def test_insufficient_references_at_both_gates(self, api):
        """PRD §3.1: "Once at least two references for the applicant exist in
        `PENDING`, an administrator advances the applicant from `APPLIED` to
        `REFERENCES_PENDING`; with fewer than two the attempt fails with
        `ERR_INSUFFICIENT_REFERENCES`."
        PRD §3.1: "Finalization moves the member from `REFERENCES_PENDING` to
        `VETTED` and enforces three gates: at least two `ACCEPTED` references
        (otherwise `ERR_INSUFFICIENT_REFERENCES`), ..."

        Design: Corner/validations/insufficient_references_submit_and_finalize
        """
        f = bootstrap_founders()
        # Applicant X: exactly one PENDING reference.
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], attestation_text="Only reference for X."), ADMIN)
        res = api.submit_references(x["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_REFERENCES, expected_status=409)
        assert get_member(x["id"])["vetting_status"] == "APPLIED"

        # Applicant Y: two references but only one ACCEPTED; in REFERENCES_PENDING.
        y = create_applicant("Applicant Y", "y@coop.test", "+15550202")
        get_success_data(api.accept_liability(y["id"], make_member_headers(y["id"])))
        ref_y1 = get_success_data(api.create_reference(y["id"], create_reference_payload(
            f["f1"]["id"], attestation_text="F1 vouches for applicant Y."), ADMIN))
        api.create_reference(y["id"], create_reference_payload(
            f["f2"]["id"], attestation_text="F2 vouches for applicant Y."), ADMIN)
        get_success_data(api.submit_references(y["id"], ADMIN))
        get_success_data(api.accept_reference(ref_y1["id"], ADMIN))
        res = api.finalize_vetting(y["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_REFERENCES, expected_status=409)
        assert get_member(y["id"])["vetting_status"] == "REFERENCES_PENDING"

    def test_finalize_without_liability_rejected(self, api):
        """PRD §3.1: "Finalization moves the member from `REFERENCES_PENDING` to
        `VETTED` and enforces three gates: at least two `ACCEPTED` references
        (otherwise `ERR_INSUFFICIENT_REFERENCES`), reciprocity — for every accepted
        reference, the reverse reference must also be `ACCEPTED` (otherwise
        `ERR_RECIPROCITY_NOT_MET`) — and a non-null `accepted_liability_at`
        (otherwise `ERR_LIABILITY_NOT_ACCEPTED`)."

        Design: Corner/validations/finalize_without_liability_returns_liability_not_accepted
        """
        f = bootstrap_founders()
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        ref_xf1 = get_success_data(api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], attestation_text="F1 vouches for applicant X."), ADMIN))
        ref_xf2 = get_success_data(api.create_reference(x["id"], create_reference_payload(
            f["f2"]["id"], attestation_text="F2 vouches for applicant X."), ADMIN))
        get_success_data(api.submit_references(x["id"], ADMIN))
        get_success_data(api.accept_reference(ref_xf1["id"], ADMIN))
        get_success_data(api.accept_reference(ref_xf2["id"], ADMIN))
        # Reciprocal rows (X vouches back for F1 and F2), both accepted.
        rec1 = get_success_data(api.create_reference(f["f1"]["id"], create_reference_payload(
            x["id"], attestation_text="X vouches back for F1."), ADMIN))
        rec2 = get_success_data(api.create_reference(f["f2"]["id"], create_reference_payload(
            x["id"], attestation_text="X vouches back for F2."), ADMIN))
        get_success_data(api.accept_reference(rec1["id"], ADMIN))
        get_success_data(api.accept_reference(rec2["id"], ADMIN))

        # Liability was never accepted.
        res = api.finalize_vetting(x["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_LIABILITY_NOT_ACCEPTED, expected_status=409)
        assert get_member(x["id"])["vetting_status"] == "REFERENCES_PENDING"
        assert list_ledger(x["id"]) == []

    def test_finalize_blocked_until_reciprocal_accepted(self, api):
        """PRD §3.1: "Finalization moves the member from `REFERENCES_PENDING` to
        `VETTED` and enforces three gates: at least two `ACCEPTED` references
        (otherwise `ERR_INSUFFICIENT_REFERENCES`), reciprocity — for every accepted
        reference, the reverse reference must also be `ACCEPTED` (otherwise
        `ERR_RECIPROCITY_NOT_MET`) — and a non-null `accepted_liability_at`
        (otherwise `ERR_LIABILITY_NOT_ACCEPTED`)."

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_until_reciprocal_accepted
        """
        f = bootstrap_founders()
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        get_success_data(api.accept_liability(x["id"], make_member_headers(x["id"])))
        ref_xf1 = get_success_data(api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], attestation_text="F1 vouches for applicant X."), ADMIN))
        ref_xf2 = get_success_data(api.create_reference(x["id"], create_reference_payload(
            f["f2"]["id"], attestation_text="F2 vouches for applicant X."), ADMIN))
        get_success_data(api.submit_references(x["id"], ADMIN))
        get_success_data(api.accept_reference(ref_xf1["id"], ADMIN))
        get_success_data(api.accept_reference(ref_xf2["id"], ADMIN))
        rec1 = get_success_data(api.create_reference(f["f1"]["id"], create_reference_payload(
            x["id"], attestation_text="X vouches back for F1."), ADMIN))
        rec2 = get_success_data(api.create_reference(f["f2"]["id"], create_reference_payload(
            x["id"], attestation_text="X vouches back for F2."), ADMIN))

        # Reciprocal rows still PENDING: finalize must fail the reciprocity gate.
        res = api.finalize_vetting(x["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_RECIPROCITY_NOT_MET, expected_status=409)

        get_success_data(api.accept_reference(rec1["id"], ADMIN))
        get_success_data(api.accept_reference(rec2["id"], ADMIN))
        res = api.finalize_vetting(x["id"], ADMIN)
        vetted = validate_success(res, 200)
        assert vetted["vetting_status"] == "VETTED"
        assert vetted["co_op_joined_at"] is not None
        assert vetted["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)

        grants = list_ledger(x["id"], params={"entry_type": "JOINING_GRANT"})
        assert len(grants) == 1
        assert grants[0]["delta_hours"] == pytest.approx(10.0, abs=0.001)

        fwd = validate_success(api.get_reference(ref_xf1["id"], ADMIN), 200)
        rev = validate_success(api.get_reference(rec1["id"], ADMIN), 200)
        assert fwd["reciprocal_reference_id"] == rec1["id"]
        assert rev["reciprocal_reference_id"] == ref_xf1["id"]

    def test_reciprocal_linkage_and_joining_grant(self, api):
        """PRD §3.1: "Reciprocity is tracked automatically: when a reference is
        accepted and the reverse reference — the one in which the subject vouches
        for the referee — is also `ACCEPTED`, the system links the pair by setting
        `reciprocal_reference_id` on both rows."
        PRD §3.1: "On finalization the system stamps `co_op_joined_at`, grants the
        new member 10.0 hours by setting `credit_balance_hours` to 10.0, and appends
        a `JOINING_GRANT` ledger entry for +10.0 hours."

        Design: Difficulty/cross_entity_state_dependency/finalize_blocked_until_reciprocal_accepted
        """
        f = bootstrap_founders()
        ref_fwd = f["refs"][("f1", "f2")]
        ref_rev = f["refs"][("f2", "f1")]
        fwd = validate_success(api.get_reference(ref_fwd, ADMIN), 200)
        rev = validate_success(api.get_reference(ref_rev, ADMIN), 200)
        assert fwd["status"] == "ACCEPTED" and fwd["decided_at"] is not None
        assert rev["status"] == "ACCEPTED" and rev["decided_at"] is not None
        assert fwd["reciprocal_reference_id"] == ref_rev
        assert rev["reciprocal_reference_id"] == ref_fwd

        # Finalization posted the joining grant exactly once.
        grants = list_ledger(f["f1"]["id"], params={"entry_type": "JOINING_GRANT"})
        assert len(grants) == 1
        assert grants[0]["delta_hours"] == pytest.approx(10.0, abs=0.001)
        assert f["f1"]["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert f["f1"]["co_op_joined_at"] is not None

    def test_reciprocal_reference_linkage_on_mutual_accept(self, api):
        """PRD §3.1: "Reciprocity is tracked automatically: when a reference is
        accepted and the reverse reference — the one in which the subject vouches
        for the referee — is also `ACCEPTED`, the system links the pair by setting
        `reciprocal_reference_id` on both rows."

        Design: Corner/entities/reciprocal_reference_linkage_on_mutual_accept
        """
        f = bootstrap_founders()
        fwd = validate_success(api.get_reference(f["refs"][("f1", "f3")], ADMIN), 200)
        rev = validate_success(api.get_reference(f["refs"][("f3", "f1")], ADMIN), 200)
        assert fwd["reciprocal_reference_id"] == f["refs"][("f3", "f1")]
        assert rev["reciprocal_reference_id"] == f["refs"][("f1", "f3")]
        assert fwd["status"] == "ACCEPTED" and fwd["decided_at"] is not None
        assert rev["status"] == "ACCEPTED" and rev["decided_at"] is not None

    def test_referee_not_vetted_rejected(self, api):
        """PRD §3.1: "An administrator accepts or rejects a pending reference;
        acceptance additionally requires the referee to be `VETTED` (otherwise
        `ERR_REFEREE_NOT_VETTED`) and again rejects a self-pairing with
        `ERR_SELF_REFERENCE`."

        Design: Corner/validations/referee_not_vetted_returns_error
        """
        f = bootstrap_founders()
        get_success_data(api.suspend_member(
            f["f3"]["id"], {"suspension_reason": "Temporarily not in good standing"}, ADMIN))
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        ref = get_success_data(api.create_reference(x["id"], create_reference_payload(
            f["f3"]["id"], attestation_text="Suspended F3 vouches for X."), ADMIN))
        res = api.accept_reference(ref["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_REFEREE_NOT_VETTED, expected_status=409)

        after = validate_success(api.get_reference(ref["id"], ADMIN), 200)
        assert after["status"] == "PENDING"
        assert after["decided_at"] is None

    def test_reference_bounds(self, api):
        """PRD §3.1: "...each naming a `referee_member_id` for an existing vetted
        member who vouches for the applicant recorded as `subject_member_id`, a
        `relationship_years` count that must be at least 1, and an
        `attestation_text` of at least 20 characters."

        Design: Corner/validations/reference_bounds_validation
        """
        f = bootstrap_founders()
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")

        res = api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], relationship_years=0,
            attestation_text="Known for less than a year."), ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        res = api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], relationship_years=1,
            attestation_text="Nineteen chars text"), ADMIN)  # 19 chars
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        ok = api.create_reference(x["id"], create_reference_payload(
            f["f1"]["id"], relationship_years=1,
            attestation_text="Twenty chars exactly"), ADMIN)  # 20 chars
        ref = validate_success(ok, 201)
        assert ref["status"] == "PENDING"


class TestSuspendReinstateRemoval:
    def test_suspend_reinstate_cycle(self, api):
        """PRD §3.1: "An administrator may suspend a `VETTED` member, supplying a
        non-empty `suspension_reason` (an empty reason fails with
        `ERR_INVALID_REQUEST`)."
        PRD §3.1: "Reinstating a `SUSPENDED` member returns them to `VETTED` and
        clears `suspension_reason` to null."

        Design: Difficulty/non_linear_state_machine/member_vetting_suspend_reinstate_cycle
        """
        f = bootstrap_founders()
        res = api.suspend_member(f["f1"]["id"], {"suspension_reason": "First neighborhood complaint"}, ADMIN)
        assert validate_success(res, 200)["vetting_status"] == "SUSPENDED"

        res = api.reinstate_member(f["f1"]["id"], ADMIN)
        reinstated = validate_success(res, 200)
        assert reinstated["vetting_status"] == "VETTED"
        assert reinstated["suspension_reason"] is None

        res = api.suspend_member(f["f1"]["id"], {"suspension_reason": "Second neighborhood complaint"}, ADMIN)
        assert validate_success(res, 200)["vetting_status"] == "SUSPENDED"

        after = get_member(f["f1"]["id"])
        assert after["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert after["reliability_score"] == 50

    def test_cycle_preserves_balance_and_score(self, api):
        """PRD §3.1: "Reinstating a `SUSPENDED` member returns them to `VETTED` and
        clears `suspension_reason` to null."
        PRD §2.5: "The score moves event by event rather than being recomputed:
        settling a completed sit adds 2 points to the sitter; a sitter cancelling
        less than 24 hours before the scheduled start costs 8 points; being found
        at fault for an incident costs 15 points; an access handoff reported lost
        costs the sitter 10 points; and a dispute escalated to the removal track
        costs the respondent 25 points."

        Design: Difficulty/non_linear_state_machine/member_vetting_suspend_reinstate_cycle
        """
        f = bootstrap_founders()
        get_success_data(api.suspend_member(
            f["f1"]["id"], {"suspension_reason": "Complaint one"}, ADMIN))
        mid = get_member(f["f1"]["id"])
        assert mid["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert mid["reliability_score"] == 50
        get_success_data(api.reinstate_member(f["f1"]["id"], ADMIN))
        end = get_member(f["f1"]["id"])
        assert end["vetting_status"] == "VETTED"
        assert end["suspension_reason"] is None
        assert end["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert end["reliability_score"] == 50

    def test_reinstate_vetted_member_rejected(self, api):
        """PRD §3.1: "Reinstating a `SUSPENDED` member returns them to `VETTED` and
        clears `suspension_reason` to null."
        PRD §2.7: "5. State: the target resource must be in the state its transition
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/reinstate_vetted_member_returns_invalid_state
        """
        f = bootstrap_founders()
        res = api.reinstate_member(f["f1"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_member(f["f1"]["id"])["vetting_status"] == "VETTED"

    def test_removal_requires_escalated_dispute(self, api):
        """PRD §3.1: "An administrator may remove a member who is `VETTED` or
        `SUSPENDED` only when one of two eligibility paths holds: the member is the
        respondent on a dispute that has reached `ESCALATED_REMOVAL`, or the member
        has accumulated at least 2 incidents resolved `RESOLVED_AT_FAULT` within the
        trailing 365 days — an incident dated exactly 365 days ago still counts.
        Failing both paths rejects the removal with `ERR_REMOVAL_CRITERIA_NOT_MET`."
        PRD §3.7: "The third ending is escalation, permitted only for `ACCESS_DAMAGE`
        and `BEHAVIOR` disputes (anything else fails with `ERR_INVALID_REQUEST`):
        the mediator supplies `resolution_notes`, the dispute becomes
        `ESCALATED_REMOVAL`, the respondent's `reliability_score` drops by 25, and
        the respondent becomes eligible for administrative removal."

        Design: Difficulty/cross_entity_state_dependency/removal_requires_escalated_dispute
        """
        f = bootstrap_founders()
        pet2 = create_pet(f["f2"], pet_name="Mochi", species="CAT")
        dispute = get_success_data(api.create_dispute({
            "respondent_member_id": f["f2"]["id"],
            "dispute_type": "BEHAVIOR",
            "statement": "Repeated hostile messages toward neighbors in the co-op channel.",
        }, make_member_headers(f["f1"]["id"])))
        get_success_data(api.assign_mediator(dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))

        # Before escalation the eligibility gate rejects removal.
        res = api.remove_member(f["f2"]["id"], {"removal_reason": "Attempt before escalation"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_REMOVAL_CRITERIA_NOT_MET, expected_status=409)

        esc = get_success_data(api.escalate_dispute(
            dispute["id"], {"resolution_notes": "Mediation failed; escalating to removal track."},
            make_member_headers(f["f3"]["id"])))
        assert esc["status"] == "ESCALATED_REMOVAL"
        assert get_member(f["f2"]["id"])["reliability_score"] == 25

        res = api.remove_member(f["f2"]["id"], {"removal_reason": "Escalated behavior case"}, ADMIN)
        removed = validate_success(res, 200)
        assert removed["vetting_status"] == "REMOVED"
        assert removed["removal_reason"] == "Escalated behavior case"
        assert removed["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)
        adj = list_ledger(f["f2"]["id"], params={"entry_type": "MEDIATION_ADJUSTMENT"})
        assert len(adj) == 1
        assert adj[0]["delta_hours"] == pytest.approx(-10.0, abs=0.001)
        pet_after = validate_success(api.get_pet_profile(pet2["id"], ADMIN), 200)
        assert pet_after["active"] is False

    def test_removal_side_effects_after_escalation(self, api):
        """PRD §3.1: "Removal records the supplied `removal_reason`, zeroes both
        `credit_balance_hours` and `provisional_credit_hours` — appending a
        `MEDIATION_ADJUSTMENT` ledger entry equal to the negated pre-removal balance
        when that balance was non-zero — deactivates every pet profile the member
        owns, cancels all non-terminal sitting requests, and cancels all
        non-terminal assignments with provisional reversal."

        Design: Difficulty/cross_entity_state_dependency/removal_requires_escalated_dispute
        """
        f = bootstrap_founders()
        pet2 = create_pet(f["f2"], pet_name="Mochi", species="CAT")
        dispute = get_success_data(api.create_dispute({
            "respondent_member_id": f["f2"]["id"],
            "dispute_type": "BEHAVIOR",
            "statement": "Sustained pattern of hostile conduct toward neighbors.",
        }, make_member_headers(f["f1"]["id"])))
        get_success_data(api.assign_mediator(dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))
        get_success_data(api.escalate_dispute(
            dispute["id"], {"resolution_notes": "Escalating to removal track."},
            make_member_headers(f["f3"]["id"])))

        res = api.remove_member(f["f2"]["id"], {"removal_reason": "Removal after escalation"}, ADMIN)
        removed = validate_success(res, 200)
        assert removed["vetting_status"] == "REMOVED"
        assert removed["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)
        assert removed["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        pet_after = validate_success(api.get_pet_profile(pet2["id"], ADMIN), 200)
        assert pet_after["active"] is False

    def test_removal_without_eligibility_rejected(self, api):
        """PRD §3.1: "Failing both paths rejects the removal with
        `ERR_REMOVAL_CRITERIA_NOT_MET`."

        Design: Corner/validations/removal_without_eligibility_returns_criteria_not_met
        """
        f = bootstrap_founders()
        res = api.remove_member(f["f1"]["id"], {"removal_reason": "Arbitrary removal attempt"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_REMOVAL_CRITERIA_NOT_MET, expected_status=409)
        after = get_member(f["f1"]["id"])
        assert after["vetting_status"] == "VETTED"
        assert after["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)

    def test_removed_member_is_terminal(self, api):
        """PRD §3.1: "`REMOVED` is terminal; a removed member can never be
        reinstated."
        PRD §2.7: "5. State: the target resource must be in the state its transition
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/removed_member_is_terminal
        """
        f = bootstrap_founders()
        dispute = get_success_data(api.create_dispute({
            "respondent_member_id": f["f2"]["id"],
            "dispute_type": "BEHAVIOR",
            "statement": "Sustained pattern of hostile conduct toward neighbors.",
        }, make_member_headers(f["f1"]["id"])))
        get_success_data(api.assign_mediator(dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))
        get_success_data(api.escalate_dispute(
            dispute["id"], {"resolution_notes": "Escalating to removal track."},
            make_member_headers(f["f3"]["id"])))
        get_success_data(api.remove_member(
            f["f2"]["id"], {"removal_reason": "Escalated behavior removal"}, ADMIN))

        res = api.reinstate_member(f["f2"]["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        res = api.suspend_member(
            f["f2"]["id"], {"suspension_reason": "Attempting suspend on removed member"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        assert get_member(f["f2"]["id"])["vetting_status"] == "REMOVED"

    def test_removal_incident_count_365d_inclusive(self, api):
        """PRD §3.1: "An administrator may remove a member who is `VETTED` or
        `SUSPENDED` only when one of two eligibility paths holds: the member is the
        respondent on a dispute that has reached `ESCALATED_REMOVAL`, or the member
        has accumulated at least 2 incidents resolved `RESOLVED_AT_FAULT` within the
        trailing 365 days — an incident dated exactly 365 days ago still counts."

        Design: Difficulty/boundary_precision_check/removal_incident_count_365d_inclusive
        """
        from test_helpers import (
            setup_confirmed_sit, resolve_incident_at_fault, file_incident,
        )
        f = bootstrap_founders()
        # Two sits: F2 sits the canonical one, F3 sits a second one.
        sit_a = setup_confirmed_sit(founders=f)
        sit_b = setup_confirmed_sit(founders=f, start_at="2026-09-12T10:00:00Z",
                                    end_at="2026-09-12T14:00:00Z", sitter_key="f3",
                                    owner=f["f1"], pet=sit_a["pet"])
        # I1 against F2 resolved at the default clock (2026-08-01) — wait: incidents
        # resolve at the logical now, so keep the default clock for I1 and I3.
        i1 = file_incident(sit_a["assignment"]["id"], f["f1"],
                           severity="MAJOR",
                           description="I1: pet injured under sitter watch.",
                           vet_involved=True)
        resolve_incident_at_fault(i1["id"], f["f2"]["id"])
        i3 = file_incident(sit_b["assignment"]["id"], f["f1"],
                           severity="MAJOR",
                           description="I3: gate left open by the sitter.",
                           vet_involved=False)
        resolve_incident_at_fault(i3["id"], f["f3"]["id"])
        # I2 against F2 resolved one logical day later (2026-08-02).
        set_clock("2026-08-02T00:00:00Z")
        i2 = file_incident(sit_a["assignment"]["id"], f["f1"],
                           severity="MINOR",
                           description="I2: medication skipped by sitter.",
                           vet_involved=False)
        resolve_incident_at_fault(i2["id"], f["f2"]["id"])
        # Removal attempted exactly 365 days after I1/I3 (inclusive boundary).
        set_clock("2027-08-01T00:00:00Z")

        res = api.remove_member(f["f3"]["id"], {"removal_reason": "Single at-fault incident only"}, ADMIN)
        validate_error(res, ApiErrorId.ERR_REMOVAL_CRITERIA_NOT_MET, expected_status=409)

        res = api.remove_member(f["f2"]["id"], {"removal_reason": "Two at-fault incidents in window"}, ADMIN)
        removed = validate_success(res, 200)
        assert removed["vetting_status"] == "REMOVED"
        assert removed["credit_balance_hours"] == pytest.approx(0.0, abs=0.001)
        adj = list_ledger(f["f2"]["id"], params={"entry_type": "MEDIATION_ADJUSTMENT"})
        assert len(adj) == 1
        assert adj[0]["delta_hours"] == pytest.approx(-10.0, abs=0.001)
        assert get_member(f["f2"]["id"])["reliability_score"] == 20  # 50 - 15 - 15
        assert get_member(f["f3"]["id"])["reliability_score"] == 35  # 50 - 15

    def test_removal_incident_boundary_inclusion_proof(self, api):
        """PRD §3.1: "...or the member has accumulated at least 2 incidents resolved
        `RESOLVED_AT_FAULT` within the trailing 365 days — an incident dated exactly
        365 days ago still counts. Failing both paths rejects the removal with
        `ERR_REMOVAL_CRITERIA_NOT_MET`."

        Design: Difficulty/boundary_precision_check/removal_incident_count_365d_inclusive
        """
        from test_helpers import setup_confirmed_sit, resolve_incident_at_fault, file_incident
        f = bootstrap_founders()
        sit_a = setup_confirmed_sit(founders=f)
        # Two at-fault incidents against F2, resolved at the default clock.
        for desc in ("First at-fault incident recorded here.",
                     "Second at-fault incident recorded here."):
            inc = file_incident(sit_a["assignment"]["id"], f["f1"],
                                severity="MAJOR", description=desc, vet_involved=False)
            resolve_incident_at_fault(inc["id"], f["f2"]["id"])
        # Exactly 365 days later the count is still 2 (inclusive) -> removal succeeds.
        set_clock("2027-08-01T00:00:00Z")
        res = api.remove_member(f["f2"]["id"], {"removal_reason": "Two at-fault at boundary"}, ADMIN)
        assert validate_success(res, 200)["vetting_status"] == "REMOVED"
