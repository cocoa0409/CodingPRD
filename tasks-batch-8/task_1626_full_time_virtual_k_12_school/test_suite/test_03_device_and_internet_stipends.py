"""Device and internet stipends: issuance, returns, forfeiture, uniqueness."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_device_stipend,
    create_district,
    create_enrolled_student,
    create_issued_stipend,
    create_stipend,
    get_stipend,
    set_clock,
    validate_error,
    validate_success,
    withdraw_student,
)

FINANCE = TEST_USERS["finance_officer_headers"]


class TestStipendStateMachine:
    def test_mark_returned_on_requested_stipend_rejected(self, api):
        """PRD §3.4: "When the family sends the device back, a
        `FinanceOfficer` marks the stipend returned, moving it from
        `RETURN_REQUESTED` to `RETURNED` with `clawback_cents` set to zero and
        the `version` incremented."
        PRD §2.7: "The target entity must be in a state that admits the
        requested transition."

        Design: Corner/state_machines/mark_returned_on_requested_stipend_rejected
        """
        _, student = create_enrolled_student(
            district=create_district(district_code="D-112", state_code="WA",
                                     funding_rate_cents=400, enrollment_cap=50))
        stipend = create_stipend(student["id"], stipend_type="DEVICE",
                                 amount_cents=20000)
        assert stipend["issue_status"] == "REQUESTED"
        resp = api.mark_stipend_returned(stipend["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_internet_stipend_forfeited_without_clawback_on_withdrawal(self, api):
        """PRD §3.3: "Each `INTERNET` stipend still `ISSUED` is forfeited on
        the spot — `FORFEITED` with `clawback_cents` set to zero, because
        internet stipends are never clawed back."

        Design: Corner/cross_cutting_layers/internet_stipend_forfeits_without_clawback_on_withdrawal
        """
        _, student = create_enrolled_student(
            district=create_district(district_code="D-171", state_code="CA",
                                     funding_rate_cents=500, enrollment_cap=50))
        stipend = create_issued_stipend(student["id"], stipend_type="INTERNET",
                                        amount_cents=5000)
        assert stipend["issue_status"] == "ISSUED"
        set_clock("2026-08-10T08:00:00Z")
        withdraw_student(student["id"], "MOVED_DISTRICT")
        stipend = get_stipend(stipend["id"])
        assert stipend["issue_status"] == "FORFEITED"
        assert stipend["clawback_cents"] == 0


class TestDeviceForfeitureCascade:
    def _setup_withdrawn_with_issued_device(self):
        """Student enrolled; DEVICE stipend of 50000 issued; withdrawn
        2026-08-10 (return_due_date 2026-09-09); clock advanced past it."""
        _, student = create_enrolled_student(
            district=create_district(district_code="D-030", state_code="CA",
                                     funding_rate_cents=500, enrollment_cap=10))
        stipend = create_issued_stipend(student["id"], stipend_type="DEVICE",
                                        amount_cents=50000)
        set_clock("2026-08-10T08:00:00Z")
        withdraw_student(student["id"], "DROPOUT")
        mid = get_stipend(stipend["id"])
        assert mid["issue_status"] == "RETURN_REQUESTED"
        assert mid["return_due_date"].startswith("2026-09-09"), (
            f"return deadline is thirty days out, got {mid['return_due_date']!r}")
        set_clock("2026-09-10T08:00:00Z")
        return stipend["id"]

    def test_device_stipend_forfeited_after_return_deadline(self, api):
        """PRD §2.5: "Setting the clock triggers a sweep of pending
        time-driven transitions: any assessment window whose `window_start`
        has been reached or passed moves from `SCHEDULED` to `OPEN`; any open
        window whose `window_end` is now strictly in the past moves from
        `OPEN` to `CLOSED`, cascading its still-booked seats to no-shows as
        §3.7 describes; and any device stipend still awaiting hardware return
        whose `return_due_date` has passed is forfeited, as §3.4 describes."
        PRD §3.4: "If instead the logical-clock date moves past the
        `return_due_date` while the stipend is still `RETURN_REQUESTED`, the
        stipend is forfeited automatically: its `issue_status` becomes
        `FORFEITED`, `clawback_cents` is set to the full `amount_cents`
        originally issued, and the stipend's `version` increments."

        Design: Difficulty/transitive_cascade/withdraw_cascade_stipend_forfeit_and_clawback
        """
        stipend_id = self._setup_withdrawn_with_issued_device()
        stipend = get_stipend(stipend_id)
        assert stipend["issue_status"] == "FORFEITED"

    def test_forfeited_device_stipend_clawback_equals_full_amount(self, api):
        """PRD §3.4: "If instead the logical-clock date moves past the
        `return_due_date` while the stipend is still `RETURN_REQUESTED`, the
        stipend is forfeited automatically: its `issue_status` becomes
        `FORFEITED`, `clawback_cents` is set to the full `amount_cents`
        originally issued, and the stipend's `version` increments."

        Design: Difficulty/transitive_cascade/withdraw_cascade_stipend_forfeit_and_clawback
        """
        stipend_id = self._setup_withdrawn_with_issued_device()
        stipend = get_stipend(stipend_id)
        assert stipend["clawback_cents"] == 50000, (
            "forfeiture claws back the full amount originally issued")
        assert stipend["amount_cents"] == 50000


class TestIssueReturnConservation:
    def _setup_return_requested_device(self):
        """DEVICE stipend of 50000 issued, then student withdrawn so the
        stipend sits in RETURN_REQUESTED."""
        _, student = create_enrolled_student(
            district=create_district(district_code="D-080", state_code="CA",
                                     funding_rate_cents=500, enrollment_cap=10))
        stipend = create_issued_stipend(student["id"], stipend_type="DEVICE",
                                        amount_cents=50000)
        set_clock("2026-08-10T08:00:00Z")
        withdraw_student(student["id"], "MOVED_DISTRICT")
        return stipend

    def test_mark_returned_moves_to_returned_with_zero_clawback(self, api):
        """PRD §3.4: "When the family sends the device back, a
        `FinanceOfficer` marks the stipend returned, moving it from
        `RETURN_REQUESTED` to `RETURNED` with `clawback_cents` set to zero and
        the `version` incremented."

        Design: Difficulty/compensating_invariant/stipend_issuance_and_return_conserve_funds
        """
        stipend = self._setup_return_requested_device()
        resp = api.mark_stipend_returned(stipend["id"], FINANCE)
        returned = validate_success(resp, 200)
        assert_device_stipend(returned)
        assert returned["issue_status"] == "RETURNED"
        assert returned["clawback_cents"] == 0

    def test_returned_stipend_preserves_issued_amount(self, api):
        """PRD §3.4: "A new request sits in `REQUESTED` status with
        `issued_at` null and `clawback_cents` zero; `return_due_date` is null
        at creation and remains null throughout the life of an internet
        stipend, since connectivity funding has no hardware to recover."
        PRD §3.4: "When the family sends the device back, a
        `FinanceOfficer` marks the stipend returned, moving it from
        `RETURN_REQUESTED` to `RETURNED` with `clawback_cents` set to zero and
        the `version` incremented."

        Design: Difficulty/compensating_invariant/stipend_issuance_and_return_conserve_funds
        """
        stipend = self._setup_return_requested_device()
        returned = validate_success(
            api.mark_stipend_returned(stipend["id"], FINANCE), 200)
        assert returned["amount_cents"] == 50000, (
            "the issued amount is untouched by the return")
        assert returned["issued_at"] is not None
        assert returned["version"] > stipend["version"], (
            "marking returned increments the stipend's version")


class TestStipendUniqueness:
    def _setup_second_requested_device_stipend(self):
        """Student enrolled; first DEVICE stipend ISSUED; second DEVICE
        stipend created (sits REQUESTED)."""
        _, student = create_enrolled_student(
            district=create_district(district_code="D-041", state_code="CA",
                                     funding_rate_cents=500, enrollment_cap=10))
        first = create_issued_stipend(student["id"], stipend_type="DEVICE",
                                      amount_cents=40000)
        second = create_stipend(student["id"], stipend_type="DEVICE",
                                amount_cents=40000)
        return first, second

    def test_second_device_stipend_issue_rejected_duplicate(self, api):
        """PRD §3.4: "Only after those pass does the uniqueness rule apply: no
        other stipend for the same student and the same `stipend_type` may be
        in `REQUESTED`, `ISSUED`, or `RETURN_REQUESTED`, so a second live
        stipend of one type is rejected with `ERR_DUPLICATE_ACTIVE_STIPEND`."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_stipend_issue
        """
        _, second = self._setup_second_requested_device_stipend()
        resp = api.issue_stipend(second["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_STIPEND)

    def test_rejected_duplicate_issue_leaves_stipend_requested(self, api):
        """PRD §3.4: "Only after those pass does the uniqueness rule apply: no
        other stipend for the same student and the same `stipend_type` may be
        in `REQUESTED`, `ISSUED`, or `RETURN_REQUESTED`, so a second live
        stipend of one type is rejected with `ERR_DUPLICATE_ACTIVE_STIPEND`."

        Design: Difficulty/priority_pair_validation_conflict/business_constraint_vs_business_fiscal_on_stipend_issue
        """
        _, second = self._setup_second_requested_device_stipend()
        validate_error(api.issue_stipend(second["id"], FINANCE),
                       ApiErrorId.ERR_DUPLICATE_ACTIVE_STIPEND)
        after = get_stipend(second["id"])
        assert after["issue_status"] == "REQUESTED", (
            "the rejected issuance must not move the stipend out of REQUESTED")
        assert after["issued_at"] is None
