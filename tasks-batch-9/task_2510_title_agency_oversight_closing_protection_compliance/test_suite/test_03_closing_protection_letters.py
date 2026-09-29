"""Closing protection letters: routing, the four caps, issuance and void."""

from test_helpers import (
    ApiErrorId,
    agency_version,
    assert_exposure_ledger,
    assert_letter_status,
    assert_money_equal,
    assert_posture,
    assert_total_count,
    create_policy_file,
    factories,
    issue_policy,
    lapse_license,
    onboard_agency,
    read_agency,
    request_letter,
    suspend_agency,
    transition_letter,
    validate_error,
    validate_paginated,
    validate_success,
    verify_license,
    void_letter,
)
from test_helpers.fixtures import COUNSEL, OFFICER


class TestApprovedCoverageCaps:
    """`approved_coverage_cents` is the minimum of four independently floored caps."""

    def test_scope_scaled_state_cap_binds_below_the_request(self, api, env):
        """A 90,000,000 `LENDER_ONLY` request is trimmed to the 80,000,000 state cap.

        PRD: "Consider a request for 90,000,000 cents with a `LENDER_ONLY` scope
        against a state cap of 100,000,000 cents: the state cap becomes 80,000,000.
        With an `OPEN` posture and an effective errors-and-omissions limit of
        200,000,000 cents the sublimit is 100,000,000 and the state cap binds at
        80,000,000."

        Design: Corner/calculations/correct_result_cpl_approved_coverage_state_cap_binds_the_minimum
        """
        assert_posture(env.agency, "OPEN")

        letter = request_letter(
            api,
            env,
            coverage_scope="LENDER_ONLY",
            requested_coverage_cents=90_000_000,
            closing_date="2026-08-25",
        )

        assert_letter_status(letter, "REFERRED")
        assert letter["referral_reason"] == "STATE_REFERRAL_THRESHOLD", (
            "90,000,000 is strictly greater than the 60,000,000 referral threshold, so "
            f"the reason must be STATE_REFERRAL_THRESHOLD, got {letter['referral_reason']}"
        )

        issued = transition_letter(
            api,
            letter["id"],
            "ISSUED",
            COUNSEL,
            rationale="Counsel reviewed the commitment",
        )

        assert_money_equal(
            issued["approved_coverage_cents"], 80_000_000, "approved_coverage_cents"
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 80_000_000)

    def test_request_exactly_at_the_state_cap_passes_and_the_next_cent_does_not(
        self, api, state_program
    ):
        """The fiscal cap comparison is inclusive, so the cap itself is issuable.

        PRD: "Last of all, in the fiscal tier, `requested_coverage_cents` must not
        exceed the state's `cpl_coverage_cap_cents`, else
        `ERR_CPL_COVERAGE_CAP_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/satisfaction_to_pass_cpl_request_exactly_at_state_cap_is_accepted
        """
        env = onboard_agency(
            api,
            state_program=state_program,
            review_overrides={"submitted_eo_policy_limit_cents": 400_000_000},
        )

        at_cap = request_letter(api, env, requested_coverage_cents=100_000_000)
        assert_letter_status(at_cap, "REFERRED")
        assert at_cap["referral_reason"] == "STATE_REFERRAL_THRESHOLD", (
            "100,000,000 clears the cap check but exceeds the 60,000,000 referral "
            f"threshold, got referral_reason {at_cap['referral_reason']}"
        )

        issued = transition_letter(
            api, at_cap["id"], "ISSUED", COUNSEL, rationale="At the state cap"
        )
        assert_money_equal(
            issued["approved_coverage_cents"], 100_000_000, "approved_coverage_cents"
        )

        over_cap = api.request_letter(
            factories.request_letter_payload(
                env.agency_id,
                env.state_program_id,
                agency_version(api, env.agency_id),
                requested_coverage_cents=100_000_001,
                closing_date="2026-08-21",
            ),
            env.principal,
        )
        validate_error(over_cap, ApiErrorId.ERR_CPL_COVERAGE_CAP_EXCEEDED.value, 422)

        assert_exposure_ledger(read_agency(api, env.agency_id), 100_000_000)

    def test_scope_outside_the_state_allowlist_is_refused(self, api):
        """A valid enum member still has to appear in this state's allowlist.

        PRD: "the requested `coverage_scope` must be one of the members of that
        state's `cpl_scope_allowed` array, else `ERR_CPL_SCOPE_NOT_ALLOWED` (HTTP
        422)"

        Design: Corner/validations/violation_to_error_cpl_scope_outside_state_allowlist_returns_422
        """
        program = validate_success(
            api.create_state_program(
                factories.create_state_program_payload(
                    cpl_scope_allowed=factories.scopes("FULL_SETTLEMENT")
                ),
                OFFICER,
            ),
            201,
        )
        env = onboard_agency(api, state_program=program)
        version_before = agency_version(api, env.agency_id)

        response = api.request_letter(
            factories.request_letter_payload(
                env.agency_id,
                env.state_program_id,
                version_before,
                coverage_scope="LENDER_ONLY",
            ),
            env.principal,
        )

        validate_error(response, ApiErrorId.ERR_CPL_SCOPE_NOT_ALLOWED.value, 422)

        _rows, meta = validate_paginated(
            api.list_letters(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(meta, 0)
        after = read_agency(api, env.agency_id)
        assert after["version"] == version_before, (
            "a rejected request performs no versioned write, but the agency moved "
            f"{version_before} -> {after['version']}"
        )

    def test_state_that_forbids_letters_reports_the_prohibition_not_the_scope(self, api):
        """The `cpl_permitted` gate is evaluated ahead of the scope allowlist.

        PRD: "The state must permit letters at all — `cpl_permitted` must be true,
        else `ERR_CPL_NOT_PERMITTED_IN_STATE` — and the requested `coverage_scope`
        must be one of the members of that state's `cpl_scope_allowed` array, else
        `ERR_CPL_SCOPE_NOT_ALLOWED` (HTTP 422)."

        Design: Corner/errors/letter_request_in_a_state_that_forbids_letters_returns_422
        """
        program = validate_success(
            api.create_state_program(
                factories.create_state_program_payload(
                    cpl_permitted=False,
                    cpl_scope_allowed=factories.scopes("FULL_SETTLEMENT"),
                ),
                OFFICER,
            ),
            201,
        )
        env = onboard_agency(api, state_program=program)
        version_before = agency_version(api, env.agency_id)

        response = api.request_letter(
            factories.request_letter_payload(
                env.agency_id,
                env.state_program_id,
                version_before,
                coverage_scope="LENDER_ONLY",
                requested_coverage_cents=20_000_000,
                lender_name="Empire Savings",
            ),
            env.principal,
        )

        validate_error(response, ApiErrorId.ERR_CPL_NOT_PERMITTED_IN_STATE.value, 422)

        after = read_agency(api, env.agency_id)
        assert after["version"] == version_before, (
            f"the agency version must stand at {version_before}, got {after['version']}"
        )
        assert_exposure_ledger(after, 0)


class TestExposureLedger:
    """`cpl_outstanding_exposure_cents` is a sum over the `ISSUED` set only."""

    def test_exposure_ledger_sums_only_the_issued_letters(self, api, env):
        """Two issued letters aggregate; a letter left in `REQUESTED` contributes nothing.

        PRD: "`cpl_outstanding_exposure_cents` is the sum of `approved_coverage_cents`
        across the agency's closing protection letters whose `status` is `ISSUED`;
        issuing a letter raises it by that letter's approved coverage, and voiding an
        issued letter zeroes that letter's `approved_coverage_cents` and removes it
        from the issued set, returning the ledger to its exact pre-issuance value."

        Design: Corner/calculations/aggregation_cpl_exposure_ledger_sums_only_issued_letters
        """
        first = request_letter(api, env, requested_coverage_cents=30_000_000)
        second = request_letter(
            api, env, requested_coverage_cents=20_000_000, closing_date="2026-08-21"
        )
        third = request_letter(
            api, env, requested_coverage_cents=10_000_000, closing_date="2026-08-22"
        )
        assert_letter_status(first, "REQUESTED")
        assert_letter_status(third, "REQUESTED")

        issued_first = transition_letter(
            api, first["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        assert_money_equal(
            issued_first["approved_coverage_cents"],
            30_000_000,
            "first approved_coverage_cents",
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 30_000_000)

        issued_second = transition_letter(
            api, second["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        assert_money_equal(
            issued_second["approved_coverage_cents"],
            20_000_000,
            "second approved_coverage_cents",
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 50_000_000)

        still_requested = validate_success(api.get_letter(third["id"], OFFICER))
        assert_letter_status(still_requested, "REQUESTED")
        assert_money_equal(
            still_requested["approved_coverage_cents"],
            0,
            "the un-issued letter's approved_coverage_cents",
        )

    def test_voiding_a_letter_restores_the_ledger_to_its_pre_issuance_value(
        self, api, env
    ):
        """The void is the compensating action and it lands exactly, not approximately.

        PRD: "the agency's `cpl_outstanding_exposure_cents` is recomputed — which,
        because the letter has left the issued set and its approved coverage is now
        zero, restores the ledger to precisely the value it held before the letter was
        issued"

        Design: Difficulty/compensating_invariant/cpl_exposure_ledger_restored_exactly_by_letter_void
        """
        exposure_before = read_agency(api, env.agency_id)[
            "cpl_outstanding_exposure_cents"
        ]
        assert_money_equal(exposure_before, 0, "the pre-issuance ledger")

        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        issued = transition_letter(
            api, letter["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        assert_money_equal(
            issued["approved_coverage_cents"], 30_000_000, "approved_coverage_cents"
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 30_000_000)

        voided = void_letter(api, letter["id"], "Closing cancelled by the lender")

        assert_letter_status(voided, "VOIDED")
        assert_money_equal(
            voided["approved_coverage_cents"],
            0,
            "the voided letter's approved_coverage_cents",
        )
        after = read_agency(api, env.agency_id)
        assert_exposure_ledger(after, 0)
        assert after["cpl_outstanding_exposure_cents"] == exposure_before, (
            "the ledger must return to exactly its pre-issuance value "
            f"{exposure_before}, got {after['cpl_outstanding_exposure_cents']}"
        )

    def test_voided_letter_leaves_the_issued_set_empty(self, api, env):
        """After the void nothing remains in the summed set at all.

        PRD: "`DECLINED` and `VOIDED` are the two terminal values of the letter
        dimension; a further transition against either is refused with
        `ERR_ALREADY_TERMINAL`."

        Design: Difficulty/compensating_invariant/cpl_exposure_ledger_restored_exactly_by_letter_void
        """
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        transition_letter(
            api, letter["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        _issued_rows, issued_meta = validate_paginated(
            api.list_letters(
                OFFICER, params={"agency_id": env.agency_id, "status": "ISSUED"}
            )
        )
        assert_total_count(issued_meta, 1)

        void_letter(api, letter["id"], "Closing cancelled by the lender")

        rows, meta = validate_paginated(
            api.list_letters(
                OFFICER, params={"agency_id": env.agency_id, "status": "ISSUED"}
            )
        )
        assert_total_count(meta, 0)
        assert rows == [], f"no letter may remain in the ISSUED set, got {rows}"


class TestLetterVoidPreconditions:
    """Void is barred while the letter is backing paper, and `VOIDED` is terminal."""

    def test_void_is_barred_while_an_issued_policy_cites_the_letter(self, api, env):
        """The letter behind an issued policy cannot be voided; its sibling can.

        PRD: "It is barred while the letter is actually backing paper: if any policy
        file whose `cpl_id` references this letter has an `issuance_status` of `ISSUED`
        or `LATE_ISSUED`, the void is refused with `ERR_CPL_HAS_ISSUED_POLICY` (HTTP
        409)."

        Design: Corner/endpoints/conditional_action_letter_void_blocked_once_a_policy_issued_under_it_returns_409
        """
        used = request_letter(api, env, requested_coverage_cents=30_000_000)
        transition_letter(
            api, used["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        unused = request_letter(
            api, env, requested_coverage_cents=20_000_000, closing_date="2026-08-21"
        )
        transition_letter(
            api, unused["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 50_000_000)

        policy_file = create_policy_file(api, env, cpl_id=used["id"])
        issue_policy(api, env, policy_file["id"])

        blocked = api.transition_letter(
            used["id"],
            factories.letter_state_payload(
                "VOIDED", void_reason="Attempt to void a used letter"
            ),
            OFFICER,
        )
        validate_error(blocked, ApiErrorId.ERR_CPL_HAS_ISSUED_POLICY.value, 409)
        assert_letter_status(validate_success(api.get_letter(used["id"], OFFICER)), "ISSUED")

        voided = void_letter(api, unused["id"], "Closing cancelled")
        assert_letter_status(voided, "VOIDED")
        assert_money_equal(
            voided["approved_coverage_cents"], 0, "approved_coverage_cents"
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 30_000_000)

    def test_voided_letter_cannot_be_reissued(self, api, env):
        """`VOIDED` is terminal, so no re-credit of the exposure ledger is possible.

        PRD: "`DECLINED` and `VOIDED` are the two terminal values of the letter
        dimension; a further transition against either is refused with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/terminal_state_lockdown_voided_letter_cannot_be_reissued_returns_409
        """
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        transition_letter(
            api, letter["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )
        voided = void_letter(api, letter["id"], "Closing cancelled")
        assert_letter_status(voided, "VOIDED")

        response = api.transition_letter(
            letter["id"],
            factories.letter_state_payload("ISSUED", rationale="Re-issue attempt"),
            OFFICER,
        )

        validate_error(response, ApiErrorId.ERR_ALREADY_TERMINAL.value, 409)

        still_voided = validate_success(api.get_letter(letter["id"], OFFICER))
        assert_letter_status(still_voided, "VOIDED")
        assert_money_equal(
            still_voided["approved_coverage_cents"],
            0,
            "the voided letter's approved_coverage_cents",
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 0)


class TestFrozenPostureOutranksTheFiscalCap:
    """Pairing P1: the state tier answers before the fiscal tier."""

    def test_frozen_posture_is_reported_ahead_of_the_coverage_cap(self, api, env):
        """One request violates both gates and the frozen-posture gate must win.

        PRD: "That last check is the one outranked by the frozen-posture check, per
        pairing P1."

        Design: Difficulty/priority_pair_validation_conflict/cpl_request_frozen_posture_outranks_coverage_cap_returns_409
        """
        suspended = suspend_agency(api, env.agency_id)
        assert_posture(suspended, "FROZEN")

        response = api.request_letter(
            factories.request_letter_payload(
                env.agency_id,
                env.state_program_id,
                agency_version(api, env.agency_id),
                requested_coverage_cents=150_000_000,
            ),
            env.principal,
        )

        validate_error(response, ApiErrorId.ERR_AGENCY_POSTURE_FROZEN.value, 409)
        body = response.json()
        assert (
            body["data"]["error_id"] != ApiErrorId.ERR_CPL_COVERAGE_CAP_EXCEEDED.value
        ), (
            "the fiscal cap error must not surface while the posture is FROZEN, but "
            f"the response carried {body['data']['error_id']}"
        )

    def test_the_outranked_cap_violation_is_real_and_writes_no_letter(
        self, api, env, state_program
    ):
        """The same 150,000,000 request does breach the cap once nothing outranks it.

        PRD: "Last of all, in the fiscal tier, `requested_coverage_cents` must not
        exceed the state's `cpl_coverage_cap_cents`, else
        `ERR_CPL_COVERAGE_CAP_EXCEEDED` (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/cpl_request_frozen_posture_outranks_coverage_cap_returns_409
        """
        suspend_agency(api, env.agency_id)
        frozen_response = api.request_letter(
            factories.request_letter_payload(
                env.agency_id,
                env.state_program_id,
                agency_version(api, env.agency_id),
                requested_coverage_cents=150_000_000,
            ),
            env.principal,
        )
        validate_error(frozen_response, ApiErrorId.ERR_AGENCY_POSTURE_FROZEN.value, 409)

        _rows, meta = validate_paginated(
            api.list_letters(OFFICER, params={"agency_id": env.agency_id})
        )
        assert_total_count(meta, 0)

        peer = onboard_agency(api, state_program=state_program)
        assert_posture(peer.agency, "OPEN")
        peer_response = api.request_letter(
            factories.request_letter_payload(
                peer.agency_id,
                peer.state_program_id,
                agency_version(api, peer.agency_id),
                requested_coverage_cents=150_000_000,
            ),
            peer.principal,
        )
        validate_error(
            peer_response, ApiErrorId.ERR_CPL_COVERAGE_CAP_EXCEEDED.value, 422
        )


class TestIssuanceNeedsAnActiveAppointment:
    """The letter's own state is legal; the sibling appointment decides."""

    def test_issuance_is_refused_while_the_state_appointment_is_lapsed(self, api, env):
        """A `LAPSED` appointment blocks issuance even at an `OPEN` posture.

        PRD: "An appointment with `status` `ACTIVE` must exist for the agency-and-state
        pair, else `ERR_NO_ACTIVE_APPOINTMENT_IN_STATE`."

        Design: Difficulty/cross_entity_state_dependency/cpl_issue_requires_active_appointment_in_that_state_rejected
        """
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        assert_letter_status(letter, "REQUESTED")

        lapsed = lapse_license(api, env.appointment_id)
        assert lapsed["status"] == "LAPSED", (
            f"the appointment should read LAPSED, got {lapsed['status']}"
        )
        assert_posture(read_agency(api, env.agency_id), "OPEN")

        response = api.transition_letter(
            letter["id"],
            factories.letter_state_payload("ISSUED", rationale="Standard settlement"),
            OFFICER,
        )

        validate_error(
            response, ApiErrorId.ERR_NO_ACTIVE_APPOINTMENT_IN_STATE.value, 422
        )
        assert_letter_status(validate_success(api.get_letter(letter["id"], OFFICER)), "REQUESTED")
        assert_exposure_ledger(read_agency(api, env.agency_id), 0)

    def test_renewing_the_appointment_lets_the_identical_issuance_succeed(self, api, env):
        """Nothing but the sibling row changes, and the same request now passes.

        PRD: "Renewal reverses it: `LAPSED` back to `ACTIVE` under exactly the same two
        preconditions as the first verification — an unexpired confirmed expiry and an
        accepted financial review"

        Design: Difficulty/cross_entity_state_dependency/cpl_issue_requires_active_appointment_in_that_state_rejected
        """
        letter = request_letter(api, env, requested_coverage_cents=30_000_000)
        lapse_license(api, env.appointment_id)
        refused = api.transition_letter(
            letter["id"],
            factories.letter_state_payload("ISSUED", rationale="Standard settlement"),
            OFFICER,
        )
        validate_error(refused, ApiErrorId.ERR_NO_ACTIVE_APPOINTMENT_IN_STATE.value, 422)

        restored = verify_license(api, env.appointment_id)
        assert restored["status"] == "ACTIVE", (
            f"renewal must return the appointment to ACTIVE, got {restored['status']}"
        )

        issued = transition_letter(
            api, letter["id"], "ISSUED", OFFICER, rationale="Standard settlement"
        )

        assert_letter_status(issued, "ISSUED")
        assert_money_equal(
            issued["approved_coverage_cents"], 30_000_000, "approved_coverage_cents"
        )
        assert_exposure_ledger(read_agency(api, env.agency_id), 30_000_000)
