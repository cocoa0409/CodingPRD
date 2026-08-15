"""Release and atomic execution: happy-path effects, the daily outgoing limit
boundary, the ops-day posture gate, terminal lockdown, and OCC at release."""
from test_helpers import (
    ApiErrorId,
    assert_account,
    assert_wire,
    create_approved_wire,
    create_executed_wire,
    create_submitted_wire,
    create_wire,
    get_account,
    get_wire,
    list_wire_fees,
    place_fraud_hold,
    setup_wire_room,
    submit_wire,
    validate_error,
    validate_success,
    wire_version,
)
from test_helpers import TEST_USERS

OPERATOR = TEST_USERS["wire_operator_headers"]
APPROVER_1 = TEST_USERS["wire_approver_headers"]
ADMIN = TEST_USERS["wire_ops_admin_headers"]


class TestReleaseHappyPath:
    def test_release_happy_path_full_execution_effects(self, api):
        """PRD §3.5: "On success the wire reaches `EXECUTED`: `executed_at` is
        stamped, the reservation converts into the released tally, a `DORMANT`
        ordering account reactivates to `ACTIVE`, the beneficiary's
        `first_used_at` is stamped on its first execution, the wire's
        `version` increments, and execution is audit-logged as
        `wire.execute`."
        PRD §3.5: "The fee assessment runs in its `FINAL` variant (§3.7): a
        new `FeeAssessment` of `kind` `FINAL` is created in `OPEN` status"

        One release call produces every documented effect, verifiable on the
        response plus one fee listing.

        Design: Corner/endpoints/release_happy_path_full_execution_effects
        """
        room = setup_wire_room(business_date="2026-09-25")
        account = room["account"]
        wire = create_approved_wire(
            account["id"], room["beneficiary"]["id"], "2026-09-25", 200000)
        approved_version = wire["version"]

        released = validate_success(api.release_wire(
            wire["id"], {"expected_wire_version": approved_version}, OPERATOR), 200)
        assert_wire(released)
        assert released["status"] == "EXECUTED"
        assert released["executed_at"] is not None
        assert released["reservation_active"] is False
        assert released["version"] == approved_version + 1, (
            f"version advances exactly once: {approved_version} -> "
            f"{released['version']}")
        assert released["fee_assessed_cents"] == 2500

        account_after = get_account(account["id"])
        assert account_after["daily_reserved_cents"] == 0
        assert account_after["daily_released_cents"] == 200000

        fees = list_wire_fees(wire["id"])
        assert len(fees) == 1, f"exactly one FINAL assessment, got {len(fees)}"
        assert fees[0]["kind"] == "FINAL"
        assert fees[0]["status"] == "OPEN"
        assert fees[0]["total_fee_cents"] == 2500

    def test_immediate_consistency_release_response(self, api):
        """PRD §3.5: "A wire that clears the gates transitions `APPROVED →
        RELEASING`, and the network dispatch happens immediately within the
        same call."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the
        data field."

        The release response body itself already reflects every side effect —
        no re-read is needed.

        Design: Corner/consistency_model/immediate_consistency_release_response
        """
        room = setup_wire_room(business_date="2026-10-13")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-10-13", 100000)

        released = validate_success(api.release_wire(
            wire["id"], {"expected_wire_version": wire["version"]}, OPERATOR), 200)
        assert_wire(released)
        assert released["status"] == "EXECUTED"
        assert released["fee_assessed_cents"] == 2500
        assert released["reservation_active"] is False
        assert released["net_principal_cents"] == 100000
        assert released["executed_at"] is not None


class TestReleasePreconditions:
    def test_release_gated_by_business_date_posture(self, api):
        """PRD §3.5: "the business date of the wire's `value_date` must still
        be `OPEN` — a date that has passed cutoff or closed rejects with
        `ERR_CUTOFF_PASSED`."
        PRD §2.6: "A failed check aborts the release **atomically**: the wire
        remains in `APPROVED`, its reservation stays active"

        A fully approved, CLEAR, unheld wire cannot release once its
        value_date's business date has passed cutoff; the reservation is
        preserved for next-day handling.

        Design: Difficulty/cross_entity_state_dependency/release_gated_by_business_date_posture
        """
        room = setup_wire_room(business_date="2026-08-14")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-14", 300000)

        validate_success(api.close_cutoff(room["business_date"]["id"], ADMIN), 200)

        resp = api.release_wire(
            wire["id"], {"expected_wire_version": wire_version(wire["id"])}, OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "APPROVED"
        assert wire_after["reservation_active"] is True

    def test_release_succeeds_while_date_open_then_cutoff_gates(self, api):
        """PRD §2.5: "From the moment a date's cutoff passes, no wire may be
        submitted or released against that date; the rejection code is
        `ERR_CUTOFF_PASSED`."

        On one business date: a first approved wire releases while the date is
        OPEN; after the cutoff closes, a second approved wire on the same date
        is rejected — the gate is the date's posture, not the wire.

        Design: Difficulty/cross_entity_state_dependency/release_gated_by_business_date_posture
        """
        room = setup_wire_room(business_date="2026-08-14")
        account = room["account"]
        beneficiary = room["beneficiary"]

        wire_a = create_approved_wire(
            account["id"], beneficiary["id"], "2026-08-14", 300000)
        released = validate_success(api.release_wire(
            wire_a["id"], {"expected_wire_version": wire_a["version"]}, OPERATOR), 200)
        assert released["status"] == "EXECUTED", "control: release while OPEN succeeds"

        wire_b = create_approved_wire(
            account["id"], beneficiary["id"], "2026-08-14", 300000)
        validate_success(api.close_cutoff(room["business_date"]["id"], ADMIN), 200)

        resp = api.release_wire(
            wire_b["id"], {"expected_wire_version": wire_version(wire_b["id"])},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_CUTOFF_PASSED)


class TestDailyLimitBoundary:
    def test_daily_limit_exact_fit_then_one_cent_over(self, api):
        """PRD §2.6: "Execution proceeds if and only if the available headroom
        is greater than or equal to the wire's `amount_cents`. The boundary is
        inclusive: headroom exactly equal to the wire's principal is allowed,
        while headroom one cent short rejects the entire release with
        `ERR_DAILY_LIMIT_EXCEEDED`."
        PRD §2.6: "A failed check aborts the release **atomically**: the wire
        remains in `APPROVED`, its reservation stays active, and the account's
        `daily_reserved_cents` is left unchanged"

        With 600000 of headroom: a 600001-cent wire is rejected one cent
        short and stays APPROVED with its reservation; a 600000-cent wire
        executes exactly.

        Design: Difficulty/boundary_precision_check/daily_limit_exact_fit_then_one_cent_over
        """
        room = setup_wire_room(
            business_date="2026-08-13",
            account_overrides={"daily_outgoing_limit_cents": 1500000})
        account = room["account"]
        beneficiary = room["beneficiary"]

        seed = create_executed_wire(
            account["id"], beneficiary["id"], "2026-08-13", 900000)
        assert seed["status"] == "EXECUTED"

        wire_over = create_approved_wire(
            account["id"], beneficiary["id"], "2026-08-13", 600001)
        wire_fit = create_approved_wire(
            account["id"], beneficiary["id"], "2026-08-13", 600000)

        resp_over = api.release_wire(
            wire_over["id"],
            {"expected_wire_version": wire_version(wire_over["id"])}, OPERATOR)
        validate_error(resp_over, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED)

        over_after = get_wire(wire_over["id"])
        assert over_after["status"] == "APPROVED"
        assert over_after["reservation_active"] is True, (
            "the abort is atomic: reservation intact for remediation")

        fit_released = validate_success(api.release_wire(
            wire_fit["id"], {"expected_wire_version": wire_version(wire_fit["id"])},
            OPERATOR), 200)
        assert fit_released["status"] == "EXECUTED"

        account_after = get_account(account["id"])
        assert_account(account_after)
        assert account_after["daily_released_cents"] == 1500000
        assert account_after["daily_reserved_cents"] == 600001, (
            f"only the failed wire's reservation remains, got "
            f"{account_after['daily_reserved_cents']}")

    def test_daily_limit_full_limit_fit_then_zero_headroom(self, api):
        """PRD §2.6: "The boundary is inclusive: headroom exactly equal to the
        wire's principal is allowed, while headroom one cent short rejects the
        entire release with `ERR_DAILY_LIMIT_EXCEEDED`."

        A wire whose principal equals the whole daily limit executes; once
        the tally is exhausted, a further one-cent wire finds zero headroom
        and is rejected, staying APPROVED with its reservation.

        Design: Difficulty/boundary_precision_check/daily_limit_exact_fit_then_one_cent_over
        """
        room = setup_wire_room(
            business_date="2026-08-13",
            account_overrides={"daily_outgoing_limit_cents": 1000000})
        account = room["account"]
        beneficiary = room["beneficiary"]

        wire_full = create_approved_wire(
            account["id"], beneficiary["id"], "2026-08-13", 1000000)
        released = validate_success(api.release_wire(
            wire_full["id"], {"expected_wire_version": wire_full["version"]},
            OPERATOR), 200)
        assert released["status"] == "EXECUTED"

        wire_cent = create_approved_wire(
            account["id"], beneficiary["id"], "2026-08-13", 1)
        resp = api.release_wire(
            wire_cent["id"], {"expected_wire_version": wire_version(wire_cent["id"])},
            OPERATOR)
        validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED)

        cent_after = get_wire(wire_cent["id"])
        assert cent_after["status"] == "APPROVED"
        assert cent_after["reservation_active"] is True


class TestTerminalLockdown:
    def test_cancel_executed_wire_rejected(self, api):
        """PRD §4: POST /wire-ops/wires/{id}/cancel — "Cancel a wire in
        INITIATED, CALLBACK_PENDING, PENDING_APPROVAL, REPAIR, or unheld
        APPROVED".
        PRD §2.8: "(10) the generic state precondition on action endpoints
        (`ERR_INVALID_STATE`)"

        Cancellation is not defined from terminal EXECUTED; the attempt is
        rejected and the wire is unchanged.

        Design: Corner/state_machines/cancel_executed_wire_rejected
        """
        room = setup_wire_room(business_date="2026-08-25")
        wire = create_executed_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-08-25", 100000)
        assert wire["status"] == "EXECUTED"

        resp = api.cancel_wire(wire["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        wire_after = get_wire(wire["id"])
        assert wire_after["status"] == "EXECUTED"

    def test_terminal_rejected_wire_rejects_submit_and_cancel(self, api):
        """PRD §3.3: "Submission moves a wire from `INITIATED` — or from
        `CALLBACK_PENDING` once verification is satisfied — into
        `PENDING_APPROVAL`."
        PRD §4: POST /wire-ops/wires/{id}/cancel — "Cancel a wire in
        INITIATED, CALLBACK_PENDING, PENDING_APPROVAL, REPAIR, or unheld
        APPROVED".

        From terminal REJECTED neither submit nor cancel is defined; both are
        rejected with ERR_INVALID_STATE.

        Design: Corner/state_machines/terminal_rejected_wire_rejects_submit_and_cancel
        """
        room = setup_wire_room(business_date="2026-08-26")
        wire = create_wire(room["account"]["id"], room["beneficiary"]["id"], 100000)
        submit_wire(wire["id"], "2026-08-26")
        validate_success(api.reject_wire(
            wire["id"], {"reason": "compliance"}, APPROVER_1), 200)

        resp_submit = api.submit_wire(
            wire["id"], {"business_date": "2026-08-26"}, OPERATOR)
        validate_error(resp_submit, ApiErrorId.ERR_INVALID_STATE)

        resp_cancel = api.cancel_wire(wire["id"], OPERATOR)
        validate_error(resp_cancel, ApiErrorId.ERR_INVALID_STATE)

    def test_reject_from_pending_approval_releases_reservation(self, api):
        """PRD §3.4: "rejection moves the wire to `REJECTED`, releases its
        reservation back to the account, and is audit-logged."
        PRD §2.6: "Any path that ends a wire before execution — rejection,
        cancellation from `PENDING_APPROVAL` or `REPAIR`, or a sanctions
        confirmation that rejects the wire — releases the reservation by
        subtracting the wire's `amount_cents` (the current, post-repair amount
        where a repair changed it) from `daily_reserved_cents` and setting
        `reservation_active` to false."

        Design: Corner/state_machines/reject_from_pending_approval_releases_reservation
        """
        room = setup_wire_room(business_date="2026-08-24")
        account = room["account"]
        wire = create_submitted_wire(
            account["id"], room["beneficiary"]["id"], "2026-08-24", 400000)
        assert get_account(account["id"])["daily_reserved_cents"] == 400000

        rejected = validate_success(api.reject_wire(
            wire["id"], {"reason": "duplicate"}, APPROVER_1), 200)
        assert_wire(rejected)
        assert rejected["status"] == "REJECTED"
        assert rejected["reservation_active"] is False

        account_after = get_account(account["id"])
        assert account_after["daily_reserved_cents"] == 0


class TestOccAtRelease:
    def test_occ_release_stale_version_conflict(self, api):
        """PRD §2.7: "This stale-view check is evaluated immediately after
        existence and request-schema checks and **before** any state or
        business rule, so a client acting on a superseded view learns about
        the staleness even when a business gate would also have failed."
        PRD §2.7: "If the value does not equal the wire's current `version` —
        because another writer has meanwhile acted on the wire (a first
        approval recorded, a repair submitted, a cancellation, a hold placed,
        or a screening-driven rejection) — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        A fraud hold placed after the client's last read advances the wire
        version: the release carrying the pre-hold version is rejected 412,
        while the fresh version reaches the business gate (ERR_WIRE_ON_HOLD).

        Design: Corner/cross_cutting_layers/occ_release_stale_version_conflict
        """
        room = setup_wire_room(business_date="2026-10-07")
        wire = create_approved_wire(
            room["account"]["id"], room["beneficiary"]["id"], "2026-10-07", 100000)
        stale_version = wire["version"]

        place_fraud_hold(wire["id"], reason_code="ACCOUNT_TAKEOVER", note="ato")

        resp_stale = api.release_wire(
            wire["id"], {"expected_wire_version": stale_version}, OPERATOR)
        validate_error(resp_stale, ApiErrorId.ERR_STALE_VERSION)

        wire_mid = get_wire(wire["id"])
        assert wire_mid["status"] == "APPROVED", "nothing was released"

        resp_fresh = api.release_wire(
            wire["id"], {"expected_wire_version": wire_mid["version"]}, OPERATOR)
        validate_error(resp_fresh, ApiErrorId.ERR_WIRE_ON_HOLD)
