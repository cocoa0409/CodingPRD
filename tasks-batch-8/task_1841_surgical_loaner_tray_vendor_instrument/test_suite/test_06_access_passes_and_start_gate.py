"""OR access passes (request, decide, admit, window boundaries) and the case
start readiness gate with its override path."""
from test_helpers import (
    ApiErrorId,
    assert_same_instant,
    coordinator,
    create_case,
    create_credentialed_rep,
    create_rep,
    create_room,
    create_vendor,
    credential_rep,
    deliver_and_verify,
    get_success_data,
    list_escalations_of_request,
    make_nurse_headers,
    make_scheduler_headers,
    rep_headers,
    set_clock,
    setup_approved_request,
    validate_error,
    validate_success,
)
from test_helpers.factories import (
    create_access_pass_payload,
    decide_access_pass_payload,
    start_case_payload,
)

NURSE = make_nurse_headers()
SCHEDULER = make_scheduler_headers()


def _vendor_rep_case(credential=True, **rep_kwargs):
    """Vendor + rep (credentialed when `credential`) + room + case."""
    vendor = create_vendor()
    if credential:
        rep = create_credentialed_rep(vendor["id"], **rep_kwargs)
    else:
        rep = create_rep(vendor["id"], **rep_kwargs)
    room = create_room()
    case = create_case(room["id"], case_number="C-1001")
    return vendor, rep, case


class TestPassDecide:
    def test_pass_deny_then_decide_locked(self, api):
        """PRD: "Denial moves the pass to terminal `DENIED` and stamps
        `denial_reason` from the payload's `reason`."
        PRD: "Only a `REQUESTED` pass can be decided, and later only an
        `APPROVED` pass can be admitted; acting on a pass in any other state
        is rejected with `ERR_PASS_INVALID_STATE` (409)."

        Design: Corner/state_machines/pass_deny_then_decide_locked
        """
        _vendor, rep, case = _vendor_rep_case()
        pass_ = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)
        denied = validate_success(
            api.decide_access_pass(
                pass_["id"],
                decide_access_pass_payload("DENY",
                                           reason="case does not need rep"),
                coordinator()))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "case does not need rep"

        resp = api.decide_access_pass(pass_["id"],
                                      decide_access_pass_payload("APPROVE"),
                                      coordinator())
        validate_error(resp, ApiErrorId.ERR_PASS_INVALID_STATE)

    def test_credential_window_insufficient_rejected(self, api):
        """PRD: "the credential must outlive the case, meaning
        `credential_expires_at` is strictly after the case's
        `scheduled_end_at` — an expiry at or before the scheduled end fails
        with `ERR_CREDENTIAL_WINDOW_INSUFFICIENT` (409)."
        PRD: "Credential approval moves a rep from `PENDING_VERIFICATION` to
        `ACTIVE`, and the same approval action also serves as the credential
        cycle: from `EXPIRED` back to `ACTIVE` as a renewal, and from
        `ACTIVE` to `ACTIVE` as an extension."

        Design: Corner/validations/credential_window_insufficient_rejected
        """
        # Credential expires exactly at the case's scheduled end (12:00):
        # "strictly after" fails on equality.
        vendor, rep, case = _vendor_rep_case(
            expires="2026-08-03T12:00:00Z")
        pass_ = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)
        resp = api.decide_access_pass(pass_["id"],
                                      decide_access_pass_payload("APPROVE"),
                                      coordinator())
        validate_error(resp, ApiErrorId.ERR_CREDENTIAL_WINDOW_INSUFFICIENT)
        assert validate_success(
            api.get_access_pass(pass_["id"], coordinator()))["status"] \
            == "REQUESTED"

        # Extending the credential one minute past the case end suffices.
        credential_rep(rep["id"], expires="2026-08-03T12:01:00Z")
        approved = validate_success(
            api.decide_access_pass(pass_["id"],
                                   decide_access_pass_payload("APPROVE"),
                                   coordinator()))
        assert approved["status"] == "APPROVED"


class TestPassApprovalCredentialGate:
    """Difficulty instance: pass approval gated by rep credential state."""

    def test_pass_approval_rejected_for_uncredentialed_rep(self, api):
        """PRD: "Approval runs four guards in the workflow's order: the case
        must still be `SCHEDULED` (`ERR_CASE_INVALID_STATE`); the rep's vendor
        must be `ACTIVE` (`ERR_VENDOR_NOT_ACTIVE`); the rep's
        `credential_status` must be `ACTIVE` (`ERR_REP_CREDENTIAL_NOT_ACTIVE`);
        and the credential must outlive the case, meaning
        `credential_expires_at` is strictly after the case's
        `scheduled_end_at`"

        Design: Difficulty/cross_entity_state_dependency/pass_approval_gated_by_rep_credential
        """
        vendor = create_vendor()
        rep = create_rep(vendor["id"])  # never credentialed
        room = create_room()
        case = create_case(room["id"], case_number="C-1001")
        pass_ = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)
        assert pass_["status"] == "REQUESTED"

        resp = api.decide_access_pass(pass_["id"],
                                      decide_access_pass_payload("APPROVE"),
                                      coordinator())
        validate_error(resp, ApiErrorId.ERR_REP_CREDENTIAL_NOT_ACTIVE)
        assert validate_success(
            api.get_access_pass(pass_["id"], coordinator()))["status"] \
            == "REQUESTED"

    def test_pass_approval_succeeds_after_credentialing(self, api):
        """PRD: "An approved pass computes its window: `window_start_at` is
        the case's `scheduled_start_at` minus two hours (120 minutes) and is
        inclusive, while `window_end_at` is the case's `scheduled_end_at`
        plus thirty minutes and is exclusive"

        Design: Difficulty/cross_entity_state_dependency/pass_approval_gated_by_rep_credential
        """
        vendor = create_vendor()
        rep = create_rep(vendor["id"])
        room = create_room()
        case = create_case(room["id"], case_number="C-1001")
        pass_ = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)

        credential_rep(rep["id"])  # ACTIVE, expiry 2026-08-10
        approved = validate_success(
            api.decide_access_pass(pass_["id"],
                                   decide_access_pass_payload("APPROVE"),
                                   coordinator()))
        assert approved["status"] == "APPROVED"
        assert_same_instant(approved["window_start_at"],
                            "2026-08-03T07:00:00Z", "pass.window_start_at")
        assert_same_instant(approved["window_end_at"],
                            "2026-08-03T12:30:00Z", "pass.window_end_at")


class TestAdmitWindow:
    def test_admit_before_window_opens_rejected(self, api):
        """PRD: "an `ORCirculatorNurse` admits a pass that is `APPROVED`, but
        only while the current time sits within the half-open window — at or
        after `window_start_at` and strictly before `window_end_at` — else
        `ERR_ACCESS_WINDOW_CLOSED` (409); admission moves the pass to
        `ADMITTED`."

        Design: Corner/validations/admit_before_window_opens_rejected
        """
        _vendor, rep, case = _vendor_rep_case()
        pass_ = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)
        get_success_data(
            api.decide_access_pass(pass_["id"],
                                   decide_access_pass_payload("APPROVE"),
                                   coordinator()))
        # Window opens at 07:00 (two hours before the 09:00 start).
        set_clock("2026-08-03T06:59:00Z")
        resp = api.admit_access_pass(pass_["id"], NURSE)
        validate_error(resp, ApiErrorId.ERR_ACCESS_WINDOW_CLOSED)
        assert validate_success(
            api.get_access_pass(pass_["id"], coordinator()))["status"] \
            == "APPROVED"

        # The lower bound is inclusive: at exactly 07:00 admission succeeds.
        set_clock("2026-08-03T07:00:00Z")
        admitted = validate_success(api.admit_access_pass(pass_["id"], NURSE))
        assert admitted["status"] == "ADMITTED"


class TestAdmitWindowEndExclusive:
    """Difficulty instance: the window's upper bound is exclusive and the
    clock sweep retires passes at exactly window_end."""

    def _two_approved_passes(self, api):
        vendor, rep, case = _vendor_rep_case()
        p1 = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                rep_headers(rep)), 201)
        p2 = validate_success(
            api.create_access_pass(
                create_access_pass_payload(rep["id"], case["id"]),
                coordinator()), 201)
        for p in (p1, p2):
            get_success_data(
                api.decide_access_pass(p["id"],
                                       decide_access_pass_payload("APPROVE"),
                                       coordinator()))
        return p1, p2

    def test_admit_before_window_end_and_sweep_at_window_end(self, api):
        """PRD: "an `ORCirculatorNurse` admits a pass that is `APPROVED`, but
        only while the current time sits within the half-open window — at or
        after `window_start_at` and strictly before `window_end_at`"
        PRD: "the clock sweep moves an `ADMITTED` pass to `EXITED` once the
        window's end has been reached, and an `APPROVED` pass that was never
        used moves to `EXPIRED` at the same boundary."

        Design: Difficulty/boundary_precision_check/admit_at_window_end_is_exclusive
        """
        p1, p2 = self._two_approved_passes(api)
        # Window is [07:00, 12:30): at 12:29 the admit is inside.
        set_clock("2026-08-03T12:29:00Z")
        admitted = validate_success(api.admit_access_pass(p1["id"], NURSE))
        assert admitted["status"] == "ADMITTED"

        # At exactly 12:30 the window has fully elapsed: the sweep moves the
        # admitted pass to EXITED and the never-admitted one to EXPIRED.
        set_clock("2026-08-03T12:30:00Z")
        p1_after = validate_success(api.get_access_pass(p1["id"], coordinator()))
        p2_after = validate_success(api.get_access_pass(p2["id"], coordinator()))
        assert p1_after["status"] == "EXITED"
        assert p2_after["status"] == "EXPIRED"

    def test_admit_at_window_end_is_exclusive(self, api):
        """PRD: "Only a `REQUESTED` pass can be decided, and later only an
        `APPROVED` pass can be admitted; acting on a pass in any other state
        is rejected with `ERR_PASS_INVALID_STATE` (409)."
        PRD: "an `ORCirculatorNurse` admits a pass that is `APPROVED`, but
        only while the current time sits within the half-open window — at or
        after `window_start_at` and strictly before `window_end_at` — else
        `ERR_ACCESS_WINDOW_CLOSED` (409)"

        Design: Difficulty/boundary_precision_check/admit_at_window_end_is_exclusive
        """
        p1, p2 = self._two_approved_passes(api)
        set_clock("2026-08-03T12:29:00Z")
        get_success_data(api.admit_access_pass(p1["id"], NURSE))
        set_clock("2026-08-03T12:30:00Z")
        # p2 was swept APPROVED -> EXPIRED at the window end; admitting it is
        # a state violation.
        resp = api.admit_access_pass(p2["id"], NURSE)
        validate_error(resp, ApiErrorId.ERR_PASS_INVALID_STATE)
        assert validate_success(
            api.get_access_pass(p2["id"], coordinator()))["status"] == "EXPIRED"


class TestCaseStartGate:
    """Difficulty instance: case start gated by linked-request readiness."""

    def _gated_world(self):
        """Tray delivered on time the day before but never sterilized: the
        request is AT_RISK (projection met) rather than READY at case time."""
        world = setup_approved_request()
        deliver_and_verify(world, at="2026-08-02T08:00:00Z")
        set_clock("2026-08-03T09:50:00Z")
        return world

    def test_case_start_blocked_when_request_not_ready(self, api):
        """PRD: "Every linked loaner request in `APPROVED` must then report
        readiness `READY`; if any does not, the start is blocked with
        `ERR_CASE_READINESS_BLOCKED` (409) unless the caller forces it with
        `override_readiness` set to true and a non-empty `override_reason`."

        Design: Difficulty/cross_entity_state_dependency/case_start_gated_by_request_readiness
        """
        world = self._gated_world()
        request = validate_success(
            api.get_request(world["request"]["id"], SCHEDULER))
        assert request["readiness"] == "AT_RISK", \
            "tray CHECKED_IN with a met projection is AT_RISK, not READY"

        resp = api.start_case(world["case"]["id"], {}, SCHEDULER)
        validate_error(resp, ApiErrorId.ERR_CASE_READINESS_BLOCKED)
        assert validate_success(
            api.get_case(world["case"]["id"], SCHEDULER))["status"] == "SCHEDULED"

    def test_case_start_override_succeeds_and_escalates(self, api):
        """PRD: "A successful start stamps `actual_start_at` from the clock,
        computes `delay_minutes_provisional` as the whole minutes by which the
        actual start passed the scheduled start (never below zero), and
        applies the all-or-nothing provisional attribution:
        `vendor_delay_minutes_provisional` equals the full provisional delay
        when the override was used, and 0 otherwise."
        PRD: "When the override was used, the system opens one `OPEN`
        escalation per non-`READY` `APPROVED` request, typed by cause —
        `MISSING_TRAY` if any of its trays is `EXPECTED` or `MISSING`, else
        `DOCUMENTATION` if any is `QUARANTINED`, else `STERILIZATION_DELAY`."
        PRD: "Trays of linked requests that stood `STAGED` move to `IN_USE`."

        Design: Difficulty/cross_entity_state_dependency/case_start_gated_by_request_readiness
        """
        world = self._gated_world()
        tray = world["trays"][0]
        # No escalation may exist before the override (the AT_RISK flip
        # happened more than twenty-four hours before the case).
        assert list_escalations_of_request(world["request"]["id"]) == []

        started = validate_success(
            api.start_case(
                world["case"]["id"],
                start_case_payload(override_readiness=True,
                                   override_reason="surgeon proceeds"),
                SCHEDULER))
        assert started["status"] == "IN_PROGRESS"
        assert_same_instant(started["actual_start_at"],
                            "2026-08-03T09:50:00Z", "case.actual_start_at")
        assert started["delay_minutes_provisional"] == 50
        assert started["vendor_delay_minutes_provisional"] == 50, \
            "override start attributes the full provisional delay to the vendor"

        escalations = list_escalations_of_request(world["request"]["id"])
        assert len(escalations) == 1, \
            "exactly one override escalation per non-READY APPROVED request"
        assert escalations[0]["type"] == "STERILIZATION_DELAY", \
            "tray is neither missing nor quarantined: late projection"
        assert escalations[0]["status"] == "OPEN"

        tray_after = validate_success(api.get_tray(tray["id"], SCHEDULER))
        assert tray_after["status"] == "CHECKED_IN", \
            "only STAGED trays move to IN_USE at case start"
