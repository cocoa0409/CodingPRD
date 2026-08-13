"""Sitting request posting, pricing, claiming, acceptance, and cancellation
(PRD §2.11, §3.3, §3.4)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    create_sitting_request_payload, create_claim_payload, create_accept_claim_payload,
    create_cancel_payload, create_window,
    make_member_headers,
    bootstrap_founders, create_applicant, create_pet, post_request, claim_request,
    accept_claim, get_assignment_for_request, get_member, set_clock,
    ADMIN,
)


def _second_owner_with_pet(f):
    """Give founder f3 a pet so they can post their own requests."""
    return create_pet(f["f3"], pet_name="Kiwi", species="BIRD",
                      routine_notes="Cover cage at night.")


class TestRequestPosting:
    def test_computed_fields_at_posting(self, api):
        """PRD §3.3: "The offered price of the sit, `credit_hours_offered`, is
        computed once at posting."
        PRD §3.3: "A fresh request is `OPEN` and perishable: its `expires_at` is set
        to four hours before `start_at`, and when the logical clock reaches that
        moment with no accepted claim, the request moves to `EXPIRED` on its own."

        Design: Corner/entities/sitting_request_computed_fields_at_posting
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        assert request["credit_hours_offered"] == pytest.approx(4.0, abs=0.001)
        assert request["expires_at"].startswith("2026-09-10T06:00:00"), (
            f"expires_at must be start_at - 4h, got {request['expires_at']}")
        assert request["status"] == "OPEN"
        assert request["owner_member_id"] == f["f1"]["id"]
        assert request["version"] == 1

    def test_no_window_multiplier_one(self, api):
        """PRD §3.3: "The system then considers every enabled holiday window whose
        interval intersects the requested interval — meaning the window starts
        before the request ends and ends after the request starts — and takes the
        single highest `demand_multiplier` among them; multipliers never compound,
        and when no enabled window intersects, the multiplier is 1.0."

        Design: Corner/calculations/credit_hours_offered_no_window_multiplier_one
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet, start_at="2026-09-05T10:00:00Z",
                               end_at="2026-09-05T13:00:00Z", instructions="Three hour sit")
        assert request["credit_hours_offered"] == pytest.approx(3.0, abs=0.001)

    def test_precision_round_half_up(self, api):
        """PRD §3.3: "The offer is the duration multiplied by that multiplier,
        rounded half-up to 2 decimal places."
        PRD §2.10: "All hour amounts in the system — offers, settlements, penalties,
        grants, and balances — are decimal values rounded half-up to exactly 2
        decimal places, and all internal arithmetic on hours is performed in decimal
        to avoid floating-point drift."

        Design: Corner/calculations/credit_hours_offered_precision_round_half_up
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="TGiving", window_start="2026-11-26T00:00:00Z",
                      window_end="2026-11-28T00:00:00Z", demand_multiplier=1.5)
        # 2.25h x 1.5 = 3.375 -> round-half-up to 3.38 (not 3.37 banker's).
        request = post_request(f["f1"], pet, start_at="2026-11-26T10:00:00Z",
                               end_at="2026-11-26T12:15:00Z", instructions="2.25h rounding probe")
        assert request["credit_hours_offered"] == pytest.approx(3.38, abs=0.001)

    def test_max_window_no_compounding(self, api):
        """PRD §3.3: "The system then considers every enabled holiday window whose
        interval intersects the requested interval — meaning the window starts
        before the request ends and ends after the request starts — and takes the
        single highest `demand_multiplier` among them; multipliers never compound,
        and when no enabled window intersects, the multiplier is 1.0."

        Design: Difficulty/combinatorial_formula/credit_hours_offered_max_window_no_compounding
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="W1", window_start="2026-12-24T00:00:00Z",
                      window_end="2026-12-26T00:00:00Z", demand_multiplier=2.0)
        create_window(name="W2", window_start="2026-12-25T00:00:00Z",
                      window_end="2026-12-27T00:00:00Z", demand_multiplier=3.0)
        create_window(name="W3", window_start="2026-12-25T00:00:00Z",
                      window_end="2026-12-27T00:00:00Z", demand_multiplier=2.5,
                      enabled=False)
        # Intersects W1 (2.0) and W2 (3.0); W3 disabled. Highest only: 4h x 3.0.
        request = post_request(f["f1"], pet, start_at="2026-12-25T10:00:00Z",
                               end_at="2026-12-25T14:00:00Z", instructions="Multi-window sit")
        assert request["credit_hours_offered"] == pytest.approx(12.0, abs=0.001)
        assert request["status"] == "OPEN"
        assert request["expires_at"].startswith("2026-12-25T06:00:00")

    def test_max_window_disabled_excluded(self, api):
        """PRD §3.3: "...takes the single highest `demand_multiplier` among them;
        multipliers never compound, and when no enabled window intersects, the
        multiplier is 1.0."
        PRD §3.3: "Because the owner is spending hours, posting also requires the
        owner's credit to stretch far enough: the balance after subtracting the
        offer must not fall below a 5.0-hour overdraft floor — otherwise the posting
        is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/credit_hours_offered_max_window_no_compounding
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="W1", window_start="2026-12-24T00:00:00Z",
                      window_end="2026-12-26T00:00:00Z", demand_multiplier=2.0)
        create_window(name="W3", window_start="2026-12-25T00:00:00Z",
                      window_end="2026-12-27T00:00:00Z", demand_multiplier=2.5,
                      enabled=False)
        request = post_request(f["f1"], pet, start_at="2026-12-25T10:00:00Z",
                               end_at="2026-12-25T14:00:00Z", instructions="Enabled-max sit")
        # Disabled 2.5 window is excluded; 4h x 2.0 = 8.00, within the overdraft floor.
        assert request["credit_hours_offered"] == pytest.approx(8.0, abs=0.001)
        assert request["status"] == "OPEN"
        assert get_member(f["f1"]["id"])["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)

    def test_duration_out_of_bounds(self, api):
        """PRD §3.3: "Basic validation runs first: `start_at` must lie in the
        future, `end_at` must be after `start_at`, and the duration must be at least
        1 hour and at most 72 hours; violations are rejected with
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/duration_out_of_bounds_returns_invalid_request
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        res = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-09-05T10:00:00Z", end_at="2026-09-05T10:30:00Z",
            instructions="Half-hour sit"), make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

        res = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-09-05T14:00:00Z", end_at="2026-09-05T10:00:00Z",
            instructions="Backwards sit"), make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_overdraft_margin_boundary(self, api):
        """PRD §3.3: "Because the owner is spending hours, posting also requires the
        owner's credit to stretch far enough: the balance after subtracting the
        offer must not fall below a 5.0-hour overdraft floor — otherwise the posting
        is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/overdraft_margin_exactly_max_vs_beyond
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="Xmas", window_start="2026-12-24T00:00:00Z",
                      window_end="2026-12-27T00:00:00Z", demand_multiplier=3.0)
        # 5h x 3.0 = 15.00 -> margin 10.00 - 15.00 == -5.00, exactly at the floor.
        ok = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-12-25T10:00:00Z", end_at="2026-12-25T15:00:00Z",
            instructions="Exact overdraft edge"), make_member_headers(f["f1"]["id"]))
        request = validate_success(ok, 201)
        assert request["credit_hours_offered"] == pytest.approx(15.0, abs=0.001)
        assert request["status"] == "OPEN"

        # 5h10m x 3.0 = 15.50 -> margin -5.50, below the floor.
        bad = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-12-26T10:00:00Z", end_at="2026-12-26T15:10:00Z",
            instructions="Beyond overdraft edge"), make_member_headers(f["f1"]["id"]))
        validate_error(bad, ApiErrorId.ERR_INSUFFICIENT_CREDIT, expected_status=402)
        assert get_member(f["f1"]["id"])["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)

    def test_overdraft_beyond_rejected_only(self, api):
        """PRD §3.3: "Because the owner is spending hours, posting also requires the
        owner's credit to stretch far enough: the balance after subtracting the
        offer must not fall below a 5.0-hour overdraft floor — otherwise the posting
        is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/overdraft_margin_exactly_max_vs_beyond
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="Xmas", window_start="2026-12-24T00:00:00Z",
                      window_end="2026-12-27T00:00:00Z", demand_multiplier=3.0)
        res = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-12-26T10:00:00Z", end_at="2026-12-26T15:10:00Z",
            instructions="Beyond overdraft edge"), make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CREDIT, expected_status=402)
        data = get_success_data(api.list_sitting_requests(
            ADMIN, params={"owner_member_id": f["f1"]["id"]}))
        assert data == [], "No SittingRequest may persist after a rejected posting"

    def test_posting_fiscal_beats_constraint_duration(self, api):
        """PRD §2.7: "14. Owner credit sufficiency at posting — otherwise
        `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."
        PRD §2.7: "17. Basic field validation of the request payload — otherwise
        `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §2.7: "Earlier steps mask later ones: a request failing step 3 never
        reports a step-5 violation, and so on."

        Design: Difficulty/priority_pair_validation_conflict/posting_fiscal_beats_constraint_duration
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        # 100h sit violates both the duration bound (step 17) and the fiscal floor
        # (step 14): the earlier step must win.
        res = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-09-05T10:00:00Z", end_at="2026-09-09T14:00:00Z",
            instructions="100h marathon sit"), make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CREDIT, expected_status=402)

        data = get_success_data(api.list_sitting_requests(
            ADMIN, params={"owner_member_id": f["f1"]["id"]}))
        assert data == [], "No SittingRequest may persist after a rejected posting"

    def test_posting_priority_marathon_never_invalid_request(self, api):
        """PRD §2.7: "14. Owner credit sufficiency at posting — otherwise
        `ERR_INSUFFICIENT_CREDIT` (HTTP 402)."
        PRD §2.7: "Earlier steps mask later ones: a request failing step 3 never
        reports a step-5 violation, and so on."

        Design: Difficulty/priority_pair_validation_conflict/posting_fiscal_beats_constraint_duration
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        res = api.create_sitting_request(create_sitting_request_payload(
            pet["id"], start_at="2026-09-05T10:00:00Z", end_at="2026-09-09T14:00:00Z",
            instructions="100h marathon sit"), make_member_headers(f["f1"]["id"]))
        assert res.status_code == 402, (
            f"Step 14 (fiscal) must mask step 17 (field validation); got {res.status_code}")
        body = res.json()
        assert body["data"]["error_id"] == "ERR_INSUFFICIENT_CREDIT"
        assert body["data"]["error_id"] != "ERR_INVALID_REQUEST"

    def test_pet_profile_invalid_posts_rejected(self, api):
        """PRD §3.3: "The named pet profile must be active, must belong to the
        caller, and must carry an accepted liability waiver, or posting fails with
        `ERR_PET_PROFILE_INVALID`."

        Design: Corner/validations/pet_profile_invalid_posts_rejected
        """
        f = bootstrap_founders()
        pet_no_waiver = create_pet(f["f1"], pet_name="NoWaiver", species="CAT",
                                   routine_notes="Feed dry food.",
                                   liability_waiver_accepted=False)
        pet_gone = create_pet(f["f1"])
        get_success_data(api.deactivate_pet_profile(pet_gone["id"], make_member_headers(f["f1"]["id"])))

        res = api.create_sitting_request(create_sitting_request_payload(
            pet_no_waiver["id"], instructions="No-waiver pet sit"),
            make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_PET_PROFILE_INVALID, expected_status=409)

        res = api.create_sitting_request(create_sitting_request_payload(
            pet_gone["id"], instructions="Deactivated pet sit"),
            make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_PET_PROFILE_INVALID, expected_status=409)

        data = get_success_data(api.list_sitting_requests(
            ADMIN, params={"owner_member_id": f["f1"]["id"]}))
        assert data == [], "No SittingRequest may persist for an invalid pet profile"


class TestClaimsAndAcceptance:
    def test_claim_creation_pending_with_claimer(self, api):
        """PRD §3.4: "A vetted member who wants the sit claims an `OPEN` request
        with a short `message` pitch. The caller is recorded as `claimer_member_id`,
        the claim starts `PENDING`, and the sitting request is linked through
        `sitting_request_id`."

        Design: Corner/endpoints/claim_creation_returns_pending_with_claimer
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        res = api.create_claim(request["id"], create_claim_payload(
            message="Happy to sit Biscuit"), make_member_headers(f["f2"]["id"]))
        claim = validate_success(res, 201)
        assert claim["status"] == "PENDING"
        assert claim["claimer_member_id"] == f["f2"]["id"]
        assert claim["sitting_request_id"] == request["id"]

        fetched = validate_success(api.get_claim(claim["id"], ADMIN), 200)
        assert fetched["message"] == "Happy to sit Biscuit"
        assert fetched["decided_at"] is None

    def test_self_dealing_rejected_422(self, api):
        """PRD §3.1: "Self-vouching is prohibited: a reference whose referee equals
        its subject is rejected with `ERR_SELF_REFERENCE`."
        PRD §3.4: "Self-dealing is barred at this door: the claimer must not be the
        request's owner (`ERR_SELF_REFERENCE`), ..."

        Design: Corner/validations/self_reference_returns_422
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")

        res = api.create_reference(x["id"], {
            "referee_member_id": x["id"], "relationship_years": 9,
            "attestation_text": "I vouch for myself, which is forbidden."}, ADMIN)
        validate_error(res, ApiErrorId.ERR_SELF_REFERENCE, expected_status=422)

        res = api.create_claim(request["id"], create_claim_payload(
            message="Owner self-claims"), make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_SELF_REFERENCE, expected_status=422)

        claims = get_success_data(api.list_claims(request["id"], ADMIN))
        assert claims == [], "Self-claim must not persist"

    def test_claim_reject_then_reaccept_invalid_state(self, api):
        """PRD §3.4: "...the owner may reject a pending claim, which stamps
        `decided_at` and moves it to `REJECTED`."
        PRD §3.4: "...the request must still be `OPEN` and the claim still `PENDING`
        (either violation surfaces as `ERR_INVALID_STATE`); ..."

        Design: Corner/state_machines/claim_reject_then_reaccept_returns_invalid_state
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])
        rejected = validate_success(api.reject_claim(
            request["id"], claim["id"], make_member_headers(f["f1"]["id"])), 200)
        assert rejected["status"] == "REJECTED"
        assert rejected["decided_at"] is not None

        current = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        res = api.accept_claim(request["id"], claim["id"],
                               create_accept_claim_payload(current["version"]),
                               make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert after["status"] == "OPEN"
        assert get_success_data(api.get_request_assignment(request["id"], ADMIN)) == []

    def test_claim_withdraw_by_claimer(self, api):
        """PRD §3.4: "A claimer may withdraw their own pending claim — the caller
        must be the claimer, otherwise `ERR_FORBIDDEN` — moving it to `WITHDRAWN`,
        and the owner may reject a pending claim, which stamps `decided_at` and
        moves it to `REJECTED`."

        Design: Corner/state_machines/claim_withdraw_by_claimer_valid
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])
        res = api.withdraw_claim(request["id"], claim["id"], make_member_headers(f["f2"]["id"]))
        withdrawn = validate_success(res, 200)
        assert withdrawn["status"] == "WITHDRAWN"

        filtered = get_success_data(api.list_claims(request["id"], ADMIN, params={"status": "WITHDRAWN"}))
        assert [c["id"] for c in filtered] == [claim["id"]]
        pending = get_success_data(api.list_claims(request["id"], ADMIN, params={"status": "PENDING"}))
        assert pending == []
        after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert after["status"] == "OPEN"

    def test_withdraw_accepted_claim_rejected(self, api):
        """PRD §3.4: "A claimer may withdraw their own pending claim — the caller
        must be the claimer, otherwise `ERR_FORBIDDEN` — moving it to `WITHDRAWN`,
        ..."
        PRD §2.7: "5. State: the target resource must be in the state its transition
        requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/withdraw_accepted_claim_returns_invalid_state
        """
        from test_helpers import setup_confirmed_sit
        sit = setup_confirmed_sit()
        res = api.withdraw_claim(sit["request"]["id"], sit["claim"]["id"],
                                 make_member_headers(sit["sitter"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        asg = validate_success(api.get_assignment(sit["assignment"]["id"], ADMIN), 200)
        assert asg["status"] == "CONFIRMED"
        assert get_member(sit["sitter"]["id"])["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)

    def test_unvetted_claimant_accept_rejected(self, api):
        """PRD §3.4: "...the claimant must currently be `VETTED`
        (`ERR_MEMBER_NOT_VETTED`); ..."
        PRD §3.4: "A vetted member who wants the sit claims an `OPEN` request with a
        short `message` pitch."

        Design: Corner/validations/unvetted_claimant_accept_returns_member_not_vetted
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        # Claim creation itself is not vetting-gated: the applicant's claim lands PENDING.
        claim = validate_success(api.create_claim(
            request["id"], create_claim_payload(message="Applicant tries to claim"),
            make_member_headers(x["id"])), 201)
        assert claim["status"] == "PENDING"

        res = api.accept_claim(request["id"], claim["id"],
                               create_accept_claim_payload(request["version"]),
                               make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_MEMBER_NOT_VETTED, expected_status=409)

        after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert after["status"] == "OPEN"
        assert after["version"] == request["version"]
        assert get_success_data(api.get_request_assignment(request["id"], ADMIN)) == []

    def test_low_reliability_claim_rejected(self, api):
        """PRD §2.5: "Claiming a sitting request requires a score of at least 30."
        PRD §3.4: "...and a claimant whose `reliability_score` is below 30 is turned
        away with `ERR_RELIABILITY_TOO_LOW`."

        Design: Corner/validations/low_reliability_claim_returns_reliability_too_low
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        # Drive F2 to score 25 via an escalated BEHAVIOR dispute (50 - 25).
        dispute = get_success_data(api.create_dispute({
            "respondent_member_id": f["f2"]["id"],
            "dispute_type": "BEHAVIOR",
            "statement": "Pattern of missed handoffs and poor communication observed.",
        }, make_member_headers(f["f1"]["id"])))
        get_success_data(api.assign_mediator(dispute["id"], {"mediator_member_id": f["f3"]["id"]}, ADMIN))
        get_success_data(api.escalate_dispute(
            dispute["id"], {"resolution_notes": "Escalating after failed mediation."},
            make_member_headers(f["f3"]["id"])))
        assert get_member(f["f2"]["id"])["reliability_score"] == 25

        res = api.create_claim(request["id"], create_claim_payload(
            message="F2 tries to claim at score 25"), make_member_headers(f["f2"]["id"]))
        validate_error(res, ApiErrorId.ERR_RELIABILITY_TOO_LOW, expected_status=409)
        claims = get_success_data(api.list_claims(request["id"], ADMIN))
        assert claims == [], "Rejected claim must not persist"

    def test_occ_stale_version_412(self, api):
        """PRD §2.11: "The acceptance payload must carry
        `expected_sitting_request_version`, holding the request's `version` as the
        owner last observed it. If another writer has advanced the request's version
        since that observation — for example by accepting a different claim, which
        legitimately moves the request out of `OPEN`, or by cancelling it — the
        acceptance is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the
        owner from acting on a request they have not re-read."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_version_returns_412
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])
        res = api.accept_claim(request["id"], claim["id"],
                               create_accept_claim_payload(request["version"] - 1),
                               make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        claim_after = validate_success(api.get_claim(claim["id"], ADMIN), 200)
        assert claim_after["status"] == "PENDING"
        req_after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert req_after["status"] == "OPEN"
        assert req_after["version"] == request["version"]
        assert get_success_data(api.get_request_assignment(request["id"], ADMIN)) == []

    def test_accept_state_beats_sitter_overlap(self, api):
        """PRD §2.7: "5. State: the target resource must be in the state its
        transition requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.7: "10. Sitter scheduling overlap — otherwise `ERR_SITTER_OVERLAP`
        (HTTP 409)."
        PRD §2.7: "Earlier steps mask later ones: a request failing step 3 never
        reports a step-5 violation, and so on."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_sitter_overlap
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        # F2 occupies 10:00-14:00 on the canonical sit.
        sit = post_request(f["f1"], pet1)
        claim1 = claim_request(sit, f["f2"])
        accept_claim(sit, claim1, f["f1"])
        # F3 posts an overlapping sit; F2 claims it; F3 then cancels the request.
        pet3 = _second_owner_with_pet(f)
        req2 = post_request(f["f3"], pet3, start_at="2026-09-10T12:00:00Z",
                            end_at="2026-09-10T16:00:00Z", instructions="Overlapping afternoon sit")
        claim2 = claim_request(req2, f["f2"], message="F2 double-books")
        get_success_data(api.cancel_sitting_request(
            req2["id"], create_cancel_payload(cancelled_reason="F3 changed plans"),
            make_member_headers(f["f3"]["id"])))
        current = validate_success(api.get_sitting_request(req2["id"], ADMIN), 200)

        # Accept now violates both state (request CANCELLED, step 5) and overlap
        # (step 10); the earlier step must win.
        res = api.accept_claim(req2["id"], claim2["id"],
                               create_accept_claim_payload(current["version"]),
                               make_member_headers(f["f3"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        body = res.json()
        assert body["data"]["error_id"] != "ERR_SITTER_OVERLAP"

    def test_accept_state_masks_overlap_without_side_effects(self, api):
        """PRD §2.7: "5. State: the target resource must be in the state its
        transition requires — otherwise `ERR_INVALID_STATE` (HTTP 409)."
        PRD §2.7: "Earlier steps mask later ones: a request failing step 3 never
        reports a step-5 violation, and so on."
        PRD §2.11: "The acceptance payload must carry
        `expected_sitting_request_version`, holding the request's `version` as the
        owner last observed it."

        Design: Difficulty/priority_pair_validation_conflict/accept_state_beats_sitter_overlap
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        sit = post_request(f["f1"], pet1)
        claim1 = claim_request(sit, f["f2"])
        accept_claim(sit, claim1, f["f1"])
        pet3 = _second_owner_with_pet(f)
        req2 = post_request(f["f3"], pet3, start_at="2026-09-10T12:00:00Z",
                            end_at="2026-09-10T16:00:00Z", instructions="Overlapping afternoon sit")
        claim2 = claim_request(req2, f["f2"], message="F2 double-books")
        get_success_data(api.cancel_sitting_request(
            req2["id"], create_cancel_payload(cancelled_reason="F3 changed plans"),
            make_member_headers(f["f3"]["id"])))
        # Owner re-reads after the cancel, so OCC passes and the state rule decides.
        current = validate_success(api.get_sitting_request(req2["id"], ADMIN), 200)
        res = api.accept_claim(req2["id"], claim2["id"],
                               create_accept_claim_payload(current["version"]),
                               make_member_headers(f["f3"]["id"]))
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"

        claim_after = validate_success(api.get_claim(claim2["id"], ADMIN), 200)
        assert claim_after["status"] == "REJECTED"  # set by the owner-cancel cascade
        req_after = validate_success(api.get_sitting_request(req2["id"], ADMIN), 200)
        assert req_after["status"] == "CANCELLED"

    def test_accept_forbidden_beats_sitter_overlap(self, api):
        """PRD §2.7: "6. Identity and ownership: the caller must be the specific
        party the operation names — otherwise `ERR_FORBIDDEN` (HTTP 403)."
        PRD §2.7: "10. Sitter scheduling overlap — otherwise `ERR_SITTER_OVERLAP`
        (HTTP 409)."
        PRD §2.7: "Earlier steps mask later ones: a request failing step 3 never
        reports a step-5 violation, and so on."

        Design: Difficulty/priority_pair_validation_conflict/accept_forbidden_beats_sitter_overlap
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        sit = post_request(f["f1"], pet1)
        claim1 = claim_request(sit, f["f2"])
        accept_claim(sit, claim1, f["f1"])
        pet3 = _second_owner_with_pet(f)
        req2 = post_request(f["f3"], pet3, start_at="2026-09-10T12:00:00Z",
                            end_at="2026-09-10T16:00:00Z", instructions="Overlapping afternoon sit")
        claim2 = claim_request(req2, f["f2"], message="F2 double-books")
        observed = validate_success(api.get_sitting_request(
            req2["id"], make_member_headers(f["f1"]["id"])), 200)

        # F1 (not the owner) attempts the accept: step 6 masks the step-10 overlap.
        res = api.accept_claim(req2["id"], claim2["id"],
                               create_accept_claim_payload(observed["version"]),
                               make_member_headers(f["f1"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        assert res.json()["data"]["error_id"] != "ERR_SITTER_OVERLAP"

        claim_after = validate_success(api.get_claim(claim2["id"], ADMIN), 200)
        assert claim_after["status"] == "PENDING"
        req_after = validate_success(api.get_sitting_request(req2["id"], ADMIN), 200)
        assert req_after["status"] == "OPEN"

    def test_accept_forbidden_leaves_no_side_effects(self, api):
        """PRD §3.4: "The caller must be the request's owner (`ERR_FORBIDDEN`); the
        request must still be `OPEN` and the claim still `PENDING` (either violation
        surfaces as `ERR_INVALID_STATE`); ..."
        PRD §2.7: "Earlier steps mask later ones: a request failing step 3 never
        reports a step-5 violation, and so on."

        Design: Difficulty/priority_pair_validation_conflict/accept_forbidden_beats_sitter_overlap
        """
        f = bootstrap_founders()
        pet1 = create_pet(f["f1"])
        req = post_request(f["f1"], pet1)
        claim = claim_request(req, f["f2"])
        res = api.accept_claim(req["id"], claim["id"],
                               create_accept_claim_payload(req["version"]),
                               make_member_headers(f["f3"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        claim_after = validate_success(api.get_claim(claim["id"], ADMIN), 200)
        assert claim_after["status"] == "PENDING"
        req_after = validate_success(api.get_sitting_request(req["id"], ADMIN), 200)
        assert req_after["status"] == "OPEN"
        assert req_after["version"] == req["version"]
        assert get_success_data(api.get_request_assignment(req["id"], ADMIN)) == []

    def test_accept_transitive_cascade_chain(self, api):
        """PRD §3.4: "When acceptance succeeds, a cascade fires in one motion. The
        claim becomes `ACCEPTED` with `decided_at` stamped; the request moves `OPEN`
        → `CLAIMED` → `ASSIGNED` and its `version` increments; every other `PENDING`
        claim on the request is `REJECTED`; a new assignment is persisted in
        `CONFIRMED` with `scheduled_start_at` and `scheduled_end_at` copied from the
        request, the owner denormalized onto `owner_member_id`, and the sitter taken
        from the accepted claim as `sitter_member_id`; an access handoff is created
        in `PENDING`; and the sitter's `provisional_credit_hours` increases by the
        request's `credit_hours_offered` — the provisional variant of the settlement
        credit, an optimistic posting that settlement may later reduce."

        Design: Difficulty/transitive_cascade/claim_accept_transitive_assignment_handoff_provisional_chain
        """
        from test_helpers import get_handoff_for_assignment
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim2 = claim_request(request, f["f2"], message="Happy to sit Biscuit")
        claim3 = claim_request(request, f["f3"], message="F3 also available")

        accepted = accept_claim(request, claim2, f["f1"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["decided_at"] is not None

        req_after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert req_after["status"] == "ASSIGNED"
        assert req_after["version"] == request["version"] + 1

        assignment = get_assignment_for_request(request["id"])
        assert assignment["status"] == "CONFIRMED"
        assert assignment["sitter_member_id"] == f["f2"]["id"]
        assert assignment["owner_member_id"] == f["f1"]["id"]
        assert assignment["scheduled_start_at"].startswith("2026-09-10T10:00:00")
        assert assignment["scheduled_end_at"].startswith("2026-09-10T14:00:00")

        handoff = get_handoff_for_assignment(assignment["id"])
        assert handoff["status"] == "PENDING"

        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)

        losing = validate_success(api.get_claim(claim3["id"], ADMIN), 200)
        assert losing["status"] == "REJECTED"

    def test_accept_cascade_losing_claim_rejected(self, api):
        """PRD §3.4: "When acceptance succeeds, a cascade fires in one motion. ...
        every other `PENDING` claim on the request is `REJECTED`; a new assignment
        is persisted in `CONFIRMED` with `scheduled_start_at` and `scheduled_end_at`
        copied from the request, the owner denormalized onto `owner_member_id`, and
        the sitter taken from the accepted claim as `sitter_member_id`; an access
        handoff is created in `PENDING`; and the sitter's `provisional_credit_hours`
        increases by the request's `credit_hours_offered` — the provisional variant
        of the settlement credit, an optimistic posting that settlement may later
        reduce."

        Design: Difficulty/transitive_cascade/claim_accept_transitive_assignment_handoff_provisional_chain
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim2 = claim_request(request, f["f2"])
        claim3 = claim_request(request, f["f3"], message="F3 also available")
        accept_claim(request, claim2, f["f1"])

        losing = validate_success(api.get_claim(claim3["id"], ADMIN), 200)
        assert losing["status"] == "REJECTED"
        assert losing["decided_at"] is not None
        sitter = get_member(f["f2"]["id"])
        assert sitter["provisional_credit_hours"] == pytest.approx(4.0, abs=0.001)

    def test_accept_effects_immediately_visible(self, api):
        """PRD §3.4: "When acceptance succeeds, a cascade fires in one motion. The
        claim becomes `ACCEPTED` with `decided_at` stamped; the request moves `OPEN`
        → `CLAIMED` → `ASSIGNED` and its `version` increments; every other `PENDING`
        claim on the request is `REJECTED`; a new assignment is persisted in
        `CONFIRMED` with `scheduled_start_at` and `scheduled_end_at` copied from the
        request, the owner denormalized onto `owner_member_id`, and the sitter taken
        from the accepted claim as `sitter_member_id`; an access handoff is created
        in `PENDING`; and the sitter's `provisional_credit_hours` increases by the
        request's `credit_hours_offered` — the provisional variant of the settlement
        credit, an optimistic posting that settlement may later reduce."

        Design: Corner/consistency_model/accept_effects_immediately_visible
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])
        res = api.accept_claim(request["id"], claim["id"],
                               create_accept_claim_payload(request["version"]),
                               make_member_headers(f["f1"]["id"]))
        accepted = validate_success(res, 200)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["decided_at"] is not None

        req_after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert req_after["status"] == "ASSIGNED"
        assert req_after["version"] == 2

        assignment = get_assignment_for_request(request["id"])
        assert assignment["status"] == "CONFIRMED"
        assert assignment["sitter_member_id"] == f["f2"]["id"]

    def test_version_increments_on_each_mutation(self, api):
        """PRD §2.9: "The `version` is an integer that starts low and increments on
        every mutation of the resource."
        PRD §3.4: "When acceptance succeeds, a cascade fires in one motion. The
        claim becomes `ACCEPTED` with `decided_at` stamped; the request moves `OPEN`
        → `CLAIMED` → `ASSIGNED` and its `version` increments; ..."

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim = claim_request(request, f["f2"])

        x = create_applicant("Applicant X", "x@coop.test", "+15550201")
        assert x["version"] == 1
        get_success_data(api.accept_liability(x["id"], make_member_headers(x["id"])))
        after_liability = validate_success(api.get_member(x["id"], ADMIN), 200)
        assert after_liability["version"] == 2

        accept_claim(request, claim, f["f1"])
        req_after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert req_after["version"] == request["version"] + 1


class TestCancellation:
    def test_cancel_open_request_rejects_pending_claims(self, api):
        """PRD §3.4: "Cancelling a request in `OPEN` or `CLAIMED` is the owner's
        prerogative alone (`ERR_FORBIDDEN`); all `PENDING` claims are `REJECTED`,
        and if an accepted claim already existed its assignment becomes
        `CANCELLED_BY_OWNER` with the provisional hours reversed."

        Design: Corner/state_machines/cancel_open_request_rejects_pending_claims
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        claim2 = claim_request(request, f["f2"])
        claim3 = claim_request(request, f["f3"], message="F3 also available")

        res = api.cancel_sitting_request(request["id"], create_cancel_payload(
            cancelled_reason="Trip called off"), make_member_headers(f["f1"]["id"]))
        cancelled = validate_success(res, 200)
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancelled_reason"] == "Trip called off"

        for claim in (claim2, claim3):
            after = validate_success(api.get_claim(claim["id"], ADMIN), 200)
            assert after["status"] == "REJECTED"
            assert after["decided_at"] is not None
        assert get_success_data(api.get_request_assignment(request["id"], ADMIN)) == []

    def test_non_owner_cancel_forbidden(self, api):
        """PRD §3.4: "Cancelling a request in `OPEN` or `CLAIMED` is the owner's
        prerogative alone (`ERR_FORBIDDEN`); all `PENDING` claims are `REJECTED`,
        and if an accepted claim already existed its assignment becomes
        `CANCELLED_BY_OWNER` with the provisional hours reversed."

        Design: Corner/validations/non_owner_cancel_returns_forbidden
        """
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        request = post_request(f["f1"], pet)
        res = api.cancel_sitting_request(request["id"], create_cancel_payload(
            cancelled_reason="Bystander meddling"), make_member_headers(f["f3"]["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
        after = validate_success(api.get_sitting_request(request["id"], ADMIN), 200)
        assert after["status"] == "OPEN"

    def test_late_cancel_boundary_24h_vs_23h(self, api):
        """PRD §3.4: "A sitter who cancels late pays for it: when fewer than 24
        hours remain before `scheduled_start_at` — exactly 24 hours out is not late
        — the sitter's balance is debited a penalty equal to the request's
        `credit_hours_offered` multiplied by 0.25, rounded half-up to 2 decimal
        places, posted as a `CANCELLATION_PENALTY` ledger entry, and the sitter's
        `reliability_score` drops by 8."

        Design: Difficulty/boundary_precision_check/late_cancel_exactly_24h_vs_23h
        """
        from test_helpers import list_ledger
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        # Sit A: sitter cancels exactly 24.0h before start -> NOT late.
        req_a = post_request(f["f1"], pet, start_at="2026-09-20T12:00:00Z",
                             end_at="2026-09-20T16:00:00Z", instructions="Sit A 24h boundary")
        claim_a = claim_request(req_a, f["f2"], message="F2 takes A")
        accept_claim(req_a, claim_a, f["f1"])
        # Sit B: sitter cancels 23.0h before start -> late penalty applies.
        req_b = post_request(f["f1"], pet, start_at="2026-10-01T12:00:00Z",
                             end_at="2026-10-01T16:00:00Z", instructions="Sit B 23h case")
        claim_b = claim_request(req_b, f["f2"], message="F2 takes B")
        accept_claim(req_b, claim_b, f["f1"])

        set_clock("2026-09-19T12:00:00Z")  # exactly 24h before sit A
        res = api.cancel_sitting_request(req_a["id"], create_cancel_payload(
            cancelled_reason="Sitter conflict at exactly 24h"), make_member_headers(f["f2"]["id"]))
        validate_success(res, 200)
        penalties = list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"})
        assert penalties == [], "Exactly 24h out is not late — no penalty row"
        assert get_member(f["f2"]["id"])["credit_balance_hours"] == pytest.approx(10.0, abs=0.001)
        assert get_member(f["f2"]["id"])["reliability_score"] == 50

        set_clock("2026-09-30T13:00:00Z")  # 23h before sit B
        res = api.cancel_sitting_request(req_b["id"], create_cancel_payload(
            cancelled_reason="Sitter conflict at 23h"), make_member_headers(f["f2"]["id"]))
        validate_success(res, 200)
        penalties = list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"})
        assert len(penalties) == 1
        assert penalties[0]["delta_hours"] == pytest.approx(-1.0, abs=0.001)  # 4.00 x 0.25
        f2 = get_member(f["f2"]["id"])
        assert f2["credit_balance_hours"] == pytest.approx(9.0, abs=0.001)
        assert f2["reliability_score"] == 42

        asg_a = get_assignment_for_request(req_a["id"])
        asg_b = get_assignment_for_request(req_b["id"])
        assert validate_success(api.get_assignment(asg_a["id"], ADMIN), 200)["status"] == "CANCELLED_BY_SITTER"
        assert validate_success(api.get_assignment(asg_b["id"], ADMIN), 200)["status"] == "CANCELLED_BY_SITTER"
        assert validate_success(api.get_sitting_request(req_a["id"], ADMIN), 200)["status"] == "CANCELLED"
        assert validate_success(api.get_sitting_request(req_b["id"], ADMIN), 200)["status"] == "CANCELLED"
        assert get_member(f["f2"]["id"])["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)

    def test_late_cancel_penalty_applied_under_24h(self, api):
        """PRD §3.4: "A sitter who cancels late pays for it: when fewer than 24
        hours remain before `scheduled_start_at` — exactly 24 hours out is not late
        — the sitter's balance is debited a penalty equal to the request's
        `credit_hours_offered` multiplied by 0.25, rounded half-up to 2 decimal
        places, posted as a `CANCELLATION_PENALTY` ledger entry, and the sitter's
        `reliability_score` drops by 8."

        Design: Difficulty/boundary_precision_check/late_cancel_exactly_24h_vs_23h
        """
        from test_helpers import list_ledger
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        req = post_request(f["f1"], pet, start_at="2026-10-01T12:00:00Z",
                           end_at="2026-10-01T16:00:00Z", instructions="Late cancel sit")
        claim = claim_request(req, f["f2"])
        accept_claim(req, claim, f["f1"])
        set_clock("2026-09-30T13:00:00Z")  # 23h before start
        res = api.cancel_sitting_request(req["id"], create_cancel_payload(
            cancelled_reason="Sitter bails at 23h"), make_member_headers(f["f2"]["id"]))
        validate_success(res, 200)
        penalties = list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"})
        assert len(penalties) == 1
        assert penalties[0]["delta_hours"] == pytest.approx(-1.0, abs=0.001)
        f2 = get_member(f["f2"]["id"])
        assert f2["credit_balance_hours"] == pytest.approx(9.0, abs=0.001)
        assert f2["reliability_score"] == 42
        assert f2["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)

    def test_late_cancel_nested_rounding(self, api):
        """PRD §3.4: "A sitter who cancels late pays for it: when fewer than 24
        hours remain before `scheduled_start_at` — exactly 24 hours out is not late
        — the sitter's balance is debited a penalty equal to the request's
        `credit_hours_offered` multiplied by 0.25, rounded half-up to 2 decimal
        places, posted as a `CANCELLATION_PENALTY` ledger entry, and the sitter's
        `reliability_score` drops by 8."
        PRD §3.3: "The offered price of the sit, `credit_hours_offered`, is computed
        once at posting."

        Design: Difficulty/combinatorial_formula/late_cancel_penalty_nested_rounding_order
        """
        from test_helpers import list_ledger
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="TGiving", window_start="2026-11-26T00:00:00Z",
                      window_end="2026-11-28T00:00:00Z", demand_multiplier=1.5)
        # 2.25h x 1.5 = 3.375 -> locked at posting as 3.38.
        req = post_request(f["f1"], pet, start_at="2026-11-26T10:00:00Z",
                           end_at="2026-11-26T12:15:00Z", instructions="Nested rounding sit")
        assert req["credit_hours_offered"] == pytest.approx(3.38, abs=0.001)
        claim = claim_request(req, f["f2"])
        accept_claim(req, claim, f["f1"])
        asg = get_assignment_for_request(req["id"])

        set_clock("2026-11-25T11:00:00Z")  # 23h before start — inside the late window
        res = api.cancel_sitting_request(req["id"], create_cancel_payload(
            cancelled_reason="Sitter emergency"), make_member_headers(f["f2"]["id"]))
        validate_success(res, 200)

        # Penalty rounds the locked, already-rounded offer: round_half_up(3.38 x 0.25) = 0.85.
        penalties = list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"})
        assert len(penalties) == 1
        assert penalties[0]["delta_hours"] == pytest.approx(-0.85, abs=0.001)
        f2 = get_member(f["f2"]["id"])
        assert f2["credit_balance_hours"] == pytest.approx(9.15, abs=0.001)
        assert f2["reliability_score"] == 42
        assert f2["provisional_credit_hours"] == pytest.approx(0.0, abs=0.001)
        assert validate_success(api.get_assignment(asg["id"], ADMIN), 200)["status"] == "CANCELLED_BY_SITTER"
        assert validate_success(api.get_sitting_request(req["id"], ADMIN), 200)["status"] == "CANCELLED"

    def test_late_cancel_penalty_rounds_locked_offer(self, api):
        """PRD §3.4: "...the sitter's balance is debited a penalty equal to the
        request's `credit_hours_offered` multiplied by 0.25, rounded half-up to 2
        decimal places, posted as a `CANCELLATION_PENALTY` ledger entry, and the
        sitter's `reliability_score` drops by 8."
        PRD §3.3: "The offered price of the sit, `credit_hours_offered`, is computed
        once at posting."

        Design: Difficulty/combinatorial_formula/late_cancel_penalty_nested_rounding_order
        """
        from test_helpers import list_ledger
        f = bootstrap_founders()
        pet = create_pet(f["f1"])
        create_window(name="TGiving", window_start="2026-11-26T00:00:00Z",
                      window_end="2026-11-28T00:00:00Z", demand_multiplier=1.5)
        req = post_request(f["f1"], pet, start_at="2026-11-26T10:00:00Z",
                           end_at="2026-11-26T12:15:00Z", instructions="Nested rounding sit")
        claim = claim_request(req, f["f2"])
        accept_claim(req, claim, f["f1"])
        set_clock("2026-11-25T11:00:00Z")
        get_success_data(api.cancel_sitting_request(req["id"], create_cancel_payload(
            cancelled_reason="Sitter emergency"), make_member_headers(f["f2"]["id"])))
        penalties = list_ledger(f["f2"]["id"], params={"entry_type": "CANCELLATION_PENALTY"})
        assert len(penalties) == 1
        # round_half_up(3.38 * 0.25) = round_half_up(0.845) = 0.85, not 0.84.
        assert penalties[0]["delta_hours"] == pytest.approx(-0.85, abs=0.001)
