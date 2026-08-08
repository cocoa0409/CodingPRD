"""Waivers, amnesty programs, segregation of duties, and validation precedence."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    clerk_headers, supervisor_headers, admin_headers,
    set_clock, make_case, make_obligation, make_amnesty, setup_waiver_requested,
    api_client,
)


class TestWaiverApprovalWaivesObligation:
    def test_approve_full_waiver_moves_obligation_to_waived(self, api):
        """PRD §3.6: "The obligation then settles toward WAIVED: from OUTSTANDING when
        the waiver fully covers the balance ... its balance_cents becomes zero and the
        case aggregates (including total_waived_cents) are reconciled."

        Design: Difficulty/non_linear_state_machine/obligation_forks_to_waived_branch
        """
        case, obl, waiver, _amnesty = setup_waiver_requested(
            case_number="C-WAIVE", assessed_amount_cents=10000,
            requested_amount_cents=10000, requester_id="clerk-1", amnesty_pct=1.0,
        )

        validate_success(api.approve_waiver_request(waiver["id"], supervisor_headers("sup-1")))

        obl_after = validate_success(api.get_obligation(obl["id"], clerk_headers()))
        case_after = validate_success(api.get_case(case["id"], clerk_headers()))
        assert obl_after["status"] == "WAIVED"
        assert obl_after["balance_cents"] == 0
        assert case_after["total_waived_cents"] == 10000

    def test_approve_records_approver_and_waived_amount(self, api):
        """PRD §3.6: "On approval the request moves to APPROVED, the approver's X-User-ID
        is recorded in approved_by_user_id, and the obligation's waived_amount_cents
        increases by requested_amount_cents."

        Design: Difficulty/non_linear_state_machine/obligation_forks_to_waived_branch
        """
        case, obl, waiver, _amnesty = setup_waiver_requested(
            case_number="C-WAIVE2", assessed_amount_cents=10000,
            requested_amount_cents=10000, requester_id="clerk-1", amnesty_pct=1.0,
        )

        approved = validate_success(api.approve_waiver_request(waiver["id"], supervisor_headers("sup-1")))
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "sup-1"

        obl_after = validate_success(api.get_obligation(obl["id"], clerk_headers()))
        assert obl_after["waived_amount_cents"] == 10000


class TestWaiverApprovalStateBeatsSod:
    def test_reapprove_by_requester_hits_state_not_sod(self, api):
        """PRD §2.10: "6. State — the target resource is in a state that permits the
        requested transition, else ERR_INVALID_STATE (409). ... 9. Safety / segregation
        of duties — the waiver approver or denier differs from the requester, else
        ERR_SOD_CONFLICT (409)."

        Design: Difficulty/priority_pair_validation_conflict/waiver_approve_state_beats_sod
        """
        case, obl, waiver, _amnesty = setup_waiver_requested(
            case_number="C-SOD-STATE", assessed_amount_cents=10000,
            requested_amount_cents=10000, requester_id="sup-A", amnesty_pct=1.0,
        )
        validate_success(api.approve_waiver_request(waiver["id"], supervisor_headers("sup-B")))

        # Second approve by the original requester: violates both state and SoD; state wins.
        resp = api.approve_waiver_request(waiver["id"], supervisor_headers("sup-A"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_reapprove_by_third_supervisor_still_hits_state(self, api):
        """PRD §3.6: "On approval the request moves to APPROVED."
        PRD §2.10: "6. State — the target resource is in a state that permits the
        requested transition, else ERR_INVALID_STATE (409)."

        Design: Difficulty/priority_pair_validation_conflict/waiver_approve_state_beats_sod
        """
        case, obl, waiver, _amnesty = setup_waiver_requested(
            case_number="C-SOD-STATE2", assessed_amount_cents=10000,
            requested_amount_cents=10000, requester_id="sup-A", amnesty_pct=1.0,
        )
        validate_success(api.approve_waiver_request(waiver["id"], supervisor_headers("sup-B")))

        # A different (non-requester) supervisor: no SoD conflict, but state still blocks.
        resp = api.approve_waiver_request(waiver["id"], supervisor_headers("sup-C"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


class TestWaiverApprovalTemporalBeatsFiscal:
    def test_no_amnesty_program_hits_temporal_not_fiscal(self, api):
        """PRD §3.6: "an amnesty program window must cover the current logical-clock
        date, or the approval is rejected with ERR_NO_ACTIVE_AMNESTY; the
        requested_amount_cents must not exceed the obligation's current balance_cents,
        or it is rejected with ERR_WAIVER_EXCEEDS_BALANCE."

        Design: Difficulty/priority_pair_validation_conflict/waiver_approve_temporal_beats_fiscal
        """
        case, obl, waiver, _amnesty = setup_waiver_requested(
            case_number="C-TEMP-FISC", assessed_amount_cents=10000,
            requested_amount_cents=999999, requester_id="clerk-1", with_amnesty=False,
        )

        resp = api.approve_waiver_request(waiver["id"], supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AMNESTY.value, expected_status=409)

    def test_amnesty_not_covering_clock_hits_temporal_not_fiscal(self, api):
        """PRD §3.6: "an amnesty program window must cover the current logical-clock
        date, or the approval is rejected with ERR_NO_ACTIVE_AMNESTY."
        PRD §2.10: "8. Temporal business rules ... 11. Fiscal amount constraints."

        Design: Difficulty/priority_pair_validation_conflict/waiver_approve_temporal_beats_fiscal
        """
        set_clock("2026-06-01T00:00:00Z")
        # Amnesty window is entirely in the future — it does not cover the clock.
        make_amnesty(name="Future Amnesty", start_date="2026-07-01T00:00:00Z",
                     end_date="2026-08-01T00:00:00Z", waiver_pct=1.0)
        case = make_case(case_number="C-TEMP-FISC2")
        obl = make_obligation(case["id"], "COURT_FEE", 10000)
        wr = validate_success(api.create_waiver_request(
            {"case_id": case["id"], "obligation_id": obl["id"], "requested_amount_cents": 999999},
            clerk_headers("clerk-1"),
        ), expected_status=201)

        resp = api.approve_waiver_request(wr["id"], supervisor_headers("sup-1"))
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_AMNESTY.value, expected_status=409)


class TestAmnestyWindowOverlap:
    def test_interior_overlap_rejected(self, api):
        """PRD §3.6: "a new window conflicts with an existing one when the new window's
        start_date is before the existing window's end_date and the existing window's
        start_date is before the new window's end_date, and any such overlap is rejected
        with ERR_AMNESTY_WINDOW_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/amnesty_halfopen_window_overlap_rejected
        """
        make_amnesty(name="Window A", start_date="2026-01-01T00:00:00Z",
                     end_date="2026-06-01T00:00:00Z", waiver_pct=0.5)

        resp = api.create_amnesty_program(
            {"name": "Window B", "start_date": "2026-05-01T00:00:00Z",
             "end_date": "2026-07-01T00:00:00Z", "waiver_pct": 0.5},
            admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_AMNESTY_WINDOW_OVERLAP.value, expected_status=409)

    def test_contained_window_overlap_rejected(self, api):
        """PRD §3.6: "Amnesty windows may not overlap: a new window conflicts with an
        existing one when the new window's start_date is before the existing window's
        end_date and the existing window's start_date is before the new window's end_date."

        Design: Difficulty/resource_temporal_overlap/amnesty_halfopen_window_overlap_rejected
        """
        make_amnesty(name="Window A", start_date="2026-01-01T00:00:00Z",
                     end_date="2026-06-01T00:00:00Z", waiver_pct=0.5)

        resp = api.create_amnesty_program(
            {"name": "Window Inner", "start_date": "2026-02-01T00:00:00Z",
             "end_date": "2026-03-01T00:00:00Z", "waiver_pct": 0.5},
            admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_AMNESTY_WINDOW_OVERLAP.value, expected_status=409)


def test_amnesty_adjacent_window_allowed(api):
    """PRD §3.6: "Two windows that merely touch at an endpoint — where one's start_date
    equals the other's end_date — share no interior instant and are permitted."

    Design: Corner/endpoints/amnesty_adjacent_window_allowed
    """
    make_amnesty(name="Adj A", start_date="2026-01-01T00:00:00Z",
                 end_date="2026-06-01T00:00:00Z", waiver_pct=0.5)

    resp = api.create_amnesty_program(
        {"name": "Adj B", "start_date": "2026-06-01T00:00:00Z",
         "end_date": "2026-09-01T00:00:00Z", "waiver_pct": 0.5},
        admin_headers(),
    )
    created = validate_success(resp, expected_status=201)
    assert created["start_date"].startswith("2026-06-01")


def test_amnesty_end_not_after_start_rejected(api):
    """PRD §3.6: "end_date must be strictly after start_date, or the request is rejected
    with ERR_INVALID_DATE_RANGE."

    Design: Corner/errors/amnesty_end_not_after_start_returns_invalid_date_range
    """
    resp = api.create_amnesty_program(
        {"name": "Bad Window", "start_date": "2026-06-01T00:00:00Z",
         "end_date": "2026-06-01T00:00:00Z", "waiver_pct": 0.5},
        admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE.value, expected_status=422)


def test_waiver_obligation_case_mismatch_rejected(api):
    """PRD §3.6: "The named obligation must belong to the named case; if it does not,
    the request is rejected with `ERR_OBLIGATION_CASE_MISMATCH`."

    Design: Corner/errors/waiver_obligation_case_mismatch_returns_error
    """
    case_a = make_case(case_number="C-MISA")
    obl_a = make_obligation(case_a["id"], "COURT_FEE", 5000)
    case_b = make_case(case_number="C-MISB")

    resp = api.create_waiver_request(
        {"case_id": case_b["id"], "obligation_id": obl_a["id"], "requested_amount_cents": 1000},
        clerk_headers("clerk-9"),
    )
    validate_error(resp, ApiErrorId.ERR_OBLIGATION_CASE_MISMATCH.value, expected_status=422)


def test_waiver_exceeding_amnesty_cap_rejected(api):
    """PRD §3.6: "the `requested_amount_cents` must not exceed the amnesty cap, the floor
    of the obligation's `assessed_amount_cents` multiplied by the covering program's
    `waiver_pct`, or it is rejected with `ERR_WAIVER_EXCEEDS_AMNESTY_CAP`."

    Design: Corner/errors/waiver_exceeds_amnesty_cap_returns_error
    """
    case, obl, waiver, _amnesty = setup_waiver_requested(
        case_number="C-CAP", assessed_amount_cents=10000,
        requested_amount_cents=6000, requester_id="clerk-1", amnesty_pct=0.5,
    )

    resp = api.approve_waiver_request(waiver["id"], supervisor_headers("sup-1"))
    validate_error(resp, ApiErrorId.ERR_WAIVER_EXCEEDS_AMNESTY_CAP.value, expected_status=409)


def test_approve_denied_waiver_rejected(api):
    """PRD §3.6: "For a denial ... A denial moves the request to DENIED and leaves the
    obligation unchanged."
    PRD §2.10: "6. State — the target resource is in a state that permits the requested
    transition, else ERR_INVALID_STATE (409)."

    Design: Corner/state_machines/approve_denied_waiver_returns_invalid_state
    """
    case, obl, waiver, _amnesty = setup_waiver_requested(
        case_number="C-DENIED", assessed_amount_cents=10000,
        requested_amount_cents=4000, requester_id="clerk-1", amnesty_pct=1.0,
    )
    validate_success(api.deny_waiver_request(waiver["id"], supervisor_headers("sup-2")))

    resp = api.approve_waiver_request(waiver["id"], supervisor_headers("sup-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_clerk_cannot_approve_waiver_forbidden(api):
    """PRD §2.1: "If the header is present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/clerk_cannot_approve_waiver_returns_forbidden
    """
    case, obl, waiver, _amnesty = setup_waiver_requested(
        case_number="C-RBAC", assessed_amount_cents=10000,
        requested_amount_cents=4000, requester_id="clerk-1", amnesty_pct=1.0,
    )

    resp = api.approve_waiver_request(waiver["id"], clerk_headers("clerk-1"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value, expected_status=403)

