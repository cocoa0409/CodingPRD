"""Optimistic concurrency, validation priority ordering, fund invariants."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_fund_availability_invariant,
    create_donor,
    create_draft_application,
    create_fund,
    create_offered_award,
    create_open_program,
    create_program,
    create_student,
    drive_to_selected,
    get_fund,
    get_success_data,
    make_student_headers,
    run_daily,
    set_clock,
    setup_offered_award,
    submit_application,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestOptimisticConcurrency:
    def test_program_edit_stale_version(self, api):
        """PRD §2.7: "Editing a scholarship program (`PUT
        /api/scholarship-programs/{id}`) requires the request to carry
        `expected_program_version`, holding the program `version` the client
        last observed. Two sequential edits carrying the same observed version
        cannot both succeed: the first commits and bumps the version, and the
        second is stale."
        PRD §2.7: "when the expected version in the request does not match the
        parent resource's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
        PRD §3.2: "a successful edit increments the program's `version` by
        one."

        Design: Corner/cross_cutting_layers/occ_program_edit_stale_version
        """
        donor = create_donor()
        fund = create_fund()
        program = create_program(donor["id"], fund["id"])
        v_1 = program["version"]

        edited = validate_success(
            api.update_program(
                program["id"],
                {
                    "expected_program_version": v_1,
                    "name": "Occ Award v2",
                    "min_gpa_hundredths": 310,
                },
                COORD,
            )
        )
        assert edited["version"] == v_1 + 1
        assert edited["min_gpa_hundredths"] == 310

        # Replaying the pre-edit version is stale.
        resp = api.update_program(
            program["id"],
            {"expected_program_version": v_1, "name": "Occ Award STALE"},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        current = validate_success(api.get_program(program["id"], COORD))
        assert current["name"] == "Occ Award v2", "nothing written on stale replay"

    def test_fund_commitment_stale_version(self, api):
        """PRD §2.7: "Adding a commitment to an award fund (`POST
        /api/award-funds/{id}/commitments`) requires `expected_fund_version`,
        holding the fund `version` the client last observed. Additive
        commitments are each independently valid, so without this check a
        stale write would silently double-count committed money."
        PRD §2.7: "when the expected version in the request does not match
        the parent resource's current `version`, the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and nothing is written."
        PRD §3.1: "a successful commitment adds the amount to
        `committed_cents`, recomputes `available_cents`, and increments the
        fund's `version` by one."

        Design: Corner/cross_cutting_layers/occ_fund_commitment_stale_version
        """
        fund = create_fund(committed_cents=1000000)
        v_1 = fund["version"]

        committed = validate_success(
            api.add_commitment(
                fund["id"],
                {"amount_cents": 500000, "expected_fund_version": v_1},
                COORD,
            )
        )
        assert committed["committed_cents"] == 1500000
        assert committed["version"] == v_1 + 1
        assert committed["available_cents"] == 1500000

        resp = api.add_commitment(
            fund["id"],
            {"amount_cents": 500000, "expected_fund_version": v_1},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_fund(fund["id"])["committed_cents"] == 1500000, (
            "no double-count on stale replay"
        )

    def test_award_patch_stale_version_and_reserve_recompute(self, api):
        """PRD §2.7: "Adjusting the amount of an offered award (`PATCH
        /api/awards/{id}`) requires `expected_award_version`, holding the
        award `version` the client last observed."
        PRD §3.6: "While an offer is still `OFFERED`, the coordinator may
        adjust its amount; the edit carries the OCC guard
        `expected_award_version` (§2.7), recomputes the fund's reservation,
        and increments the award's `version` by one."

        Design: Corner/cross_cutting_layers/occ_award_patch_stale_version_and_reserve_recompute
        """
        ctx = setup_offered_award(amount_cents=500000)
        award = ctx["award"]
        fund_id = ctx["fund"]["id"]
        assert get_fund(fund_id)["reserved_cents"] == 500000
        assert get_fund(fund_id)["available_cents"] == 4500000
        v_1 = award["version"]

        patched = validate_success(
            api.patch_award(
                award["id"],
                {"expected_award_version": v_1, "amount_cents": 400000},
                COORD,
            )
        )
        assert patched["version"] == v_1 + 1
        assert patched["amount_cents"] == 400000
        fund = get_fund(fund_id)
        assert fund["reserved_cents"] == 400000, "reservation shrank with patch"
        assert fund["available_cents"] == 4600000
        assert_fund_availability_invariant(fund)

        resp = api.patch_award(
            award["id"],
            {"expected_award_version": v_1, "amount_cents": 300000},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_fund(fund_id)["reserved_cents"] == 400000

    def test_stale_version_checked_before_state(self, api):
        """PRD §2.8: "When a request arrives, the server evaluates its checks
        in a fixed priority order, and a failure at any step surfaces that
        step's error and masks every later check" — "5. **Concurrency** — for
        the three optimistic-concurrency endpoints of §2.7, the expected
        version matches the parent's current `version`; otherwise
        `ERR_STALE_VERSION`" precedes "7. **Own-state** — the target
        resource's own state permits the requested transition; otherwise
        `ERR_INVALID_STATE`."
        PRD §3.6: "While an offer is still `OFFERED`, the coordinator may
        adjust its amount".

        Design: Corner/validations/validation_occ_stale_version_beats_state
        """
        ctx = setup_offered_award(amount_cents=500000)
        award = ctx["award"]
        stale_version = award["version"]
        # The accept mutates the award (bumping its version) and moves it out
        # of OFFERED: a PATCH carrying the pre-accept version is BOTH stale
        # (priority 5) and state-illegal (priority 7); the stale error wins.
        get_success_data(
            api.accept_award(
                award["id"], make_student_headers(ctx["students"][0]["id"])
            )
        )

        resp = api.patch_award(
            award["id"],
            {"expected_award_version": stale_version, "amount_cents": 400000},
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert api.get_award(award["id"], COORD).json()["data"]["amount_cents"] == 500000


class TestValidationPriority:
    def test_resubmit_after_deadline_reports_state_error(self, api):
        """PRD §2.8: "the server evaluates its checks in a fixed priority
        order, and a failure at any step surfaces that step's error and masks
        every later check" — "7. **Own-state** — the target resource's own
        state permits the requested transition; otherwise `ERR_INVALID_STATE`.
        The target's own state is always validated before any cross-entity
        state." precedes "11. **Temporal windows** — publish before the
        window opens (`ERR_WINDOW_NOT_OPEN`), submit at or after the deadline
        (`ERR_DEADLINE_PASSED`), and disbursement send before its scheduled
        date (`ERR_DISBURSEMENT_TOO_EARLY`)".
        PRD §3.3: "The application must be in `DRAFT` (otherwise
        `ERR_INVALID_STATE`)."

        Design: Difficulty/priority_pair_validation_conflict/resubmit_after_deadline_state_beats_temporal
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(
            donor["id"], fund["id"],
            application_close_at="2026-09-01T00:00:00Z",
        )
        app = create_draft_application(student["id"], program["id"])
        submit_application(app["id"])

        # Advance past the close and let the ops run close the program.
        set_clock("2026-09-02T00:00:00Z")
        run_daily()

        # The resubmission violates BOTH own-state (already SUBMITTED) and the
        # deadline gate; the state category wins.
        resp = api.submit_application(app["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_masked_resubmit_leaves_no_side_effects(self, api):
        """PRD §2.8: "a failure at any step surfaces that step's error and
        masks every later check".
        PRD §3.3: "On success the application moves `DRAFT` → `SUBMITTED`,
        its `verified_match_score` is recomputed using
        `verified_gpa_hundredths` when set and `gpa_hundredths` otherwise,
        `submitted_at` is stamped with the current logical instant, and every
        `SCHEDULED` reminder is suppressed" — a masked failure performs none
        of the success side effects.
        PRD §3.3: "a `SUBMITTED` application returns to `DRAFT`, its
        `returned_count` increases by one" — the counter starts at zero and
        only the return action moves it.

        Design: Difficulty/priority_pair_validation_conflict/resubmit_after_deadline_state_beats_temporal
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(
            donor["id"], fund["id"],
            application_close_at="2026-09-01T00:00:00Z",
        )
        app = create_draft_application(student["id"], program["id"])
        submitted = submit_application(app["id"])
        first_submitted_at = submitted["submitted_at"]

        set_clock("2026-09-02T00:00:00Z")
        run_daily()
        validate_error(
            api.submit_application(app["id"], COORD),
            ApiErrorId.ERR_INVALID_STATE,
        )

        current = validate_success(api.get_application(app["id"], COORD))
        assert current["status"] == "SUBMITTED"
        assert current["returned_count"] == 0
        assert current["submitted_at"] == first_submitted_at


class TestCrossEntityProgramGate:
    def test_submit_into_closed_program_rejected(self, api):
        """PRD §3.3: "The program must be `OPEN` (otherwise
        `ERR_PROGRAM_NOT_OPEN`)."
        PRD §3.2: "Closing moves `OPEN` to `CLOSED` and comes in two flavors
        with different blast radii: a coordinator's manual close simply flips
        the status" — the deadline itself is unmoved, so the cross-entity
        state gate (not the temporal gate) is what rejects.

        Design: Difficulty/cross_entity_state_dependency/submit_requires_program_open
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        app = create_draft_application(student["id"], program["id"])

        # Manual close: status flips; application_close_at stays in the future.
        get_success_data(api.close_program(program["id"], COORD))
        resp = api.submit_application(app["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_OPEN)

    def test_rejected_submit_leaves_application_draft(self, api):
        """PRD §3.3: "The program must be `OPEN` (otherwise
        `ERR_PROGRAM_NOT_OPEN`)."
        PRD §2.8: "a failure at any step surfaces that step's error and masks
        every later check" — a refused submit leaves the application
        untouched.

        Design: Difficulty/cross_entity_state_dependency/submit_requires_program_open
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund()
        program = create_open_program(donor["id"], fund["id"])
        app = create_draft_application(student["id"], program["id"])
        get_success_data(api.close_program(program["id"], COORD))

        validate_error(
            api.submit_application(app["id"], COORD),
            ApiErrorId.ERR_PROGRAM_NOT_OPEN,
        )
        current = validate_success(api.get_application(app["id"], COORD))
        assert current["status"] == "DRAFT"
        assert current["submitted_at"] is None


class TestFundAvailabilityInvariant:
    def test_offer_reserves_from_available(self, api):
        """PRD §3.6: "Creation sets `offer_status` to `OFFERED` and
        `funding_status` to `NONE`, increases the fund's `reserved_cents` by
        the offered amount".
        PRD §2.9: "`available_cents` equals `committed_cents` minus
        `reserved_cents` minus `disbursed_cents` plus `returned_cents`."
        PRD §2.9: "A freshly created fund starts with `reserved_cents`,
        `disbursed_cents`, and `returned_cents` at zero, so its
        `available_cents` equals its initial `committed_cents`."

        Design: Difficulty/compensating_invariant/fund_offer_revoke_available_conservation
        """
        student = create_student()
        donor = create_donor()
        fund = create_fund(committed_cents=5000000)
        baseline = get_fund(fund["id"])
        assert baseline["available_cents"] == 5000000
        assert baseline["reserved_cents"] == 0

        # PRD §3.6 caps an offer at the program's award_amount_cents, so the
        # program is built with a cap covering the 1000000-cent offer.
        program = create_open_program(
            donor["id"], fund["id"], award_amount_cents=1000000
        )
        flow = drive_to_selected(student["id"], program["id"])
        create_offered_award(flow["application"]["id"], student["id"], 1000000)

        after_offer = get_fund(fund["id"])
        assert after_offer["reserved_cents"] == 1000000
        assert after_offer["available_cents"] == 4000000
        assert_fund_availability_invariant(after_offer)

    def test_revoke_restores_available_exactly(self, api):
        """PRD §2.9: "A useful consequence is that an offer followed by a
        revoke leaves `available_cents` unchanged."
        PRD §3.6: "the fund's `reserved_cents` decreases by the positive part
        of `amount_cents` minus the award's net confirmed amount".
        PRD §2.9: "This availability identity is an invariant: it holds after
        every mutation that touches fund arithmetic — award create, accept,
        decline, revoke, and expiry; disbursement confirm and mark-returned;
        adjustment apply; renewal; and commitment."

        Design: Difficulty/compensating_invariant/fund_offer_revoke_available_conservation
        """
        ctx = setup_offered_award(
            amount_cents=1000000,
            program_overrides={"award_amount_cents": 1000000,
                               "program_type": "NEED"},
        )
        fund_id = ctx["fund"]["id"]
        assert get_fund(fund_id)["available_cents"] == 4000000

        revoked = validate_success(api.revoke_award(ctx["award"]["id"], COORD))
        assert revoked["offer_status"] == "REVOKED"

        fund = get_fund(fund_id)
        assert fund["available_cents"] == 5000000, "compensating release, no drift"
        assert fund["reserved_cents"] == 0
        assert fund["disbursed_cents"] == 0
        assert fund["returned_cents"] == 0
        assert_fund_availability_invariant(fund)
