"""Case resolution-track workflow, parallel litigation track, and version bumps (PRD §2.4, §3.2)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_expense_claim,
    create_case,
    create_member,
    get_case,
    notify_attorney,
    validate_error,
    validate_success,
)

SPEC = TEST_USERS["specialist_headers"]


class TestAttorneyNotification:
    def test_notify_attorney_twice_rejected(self, api):
        """PRD §3.2: "A `RecoverySpecialist` records it against a case in `IDENTIFIED` status, moving the case to `ATTORNEY_NOTIFIED`, stamping `attorney_notified_at` — null until this step is taken — with the current logical clock, and incrementing the case's `version`. Attempting it from any other status is a generic state error, `ERR_INVALID_STATE_TRANSITION` (HTTP 409)."

        Design: Corner/state_machines/notify_attorney_twice_returns_invalid_state
        """
        member = create_member(state_code="CA")
        case = create_case(member["id"])
        notify_attorney(case["id"])
        resp = api.notify_attorney(case["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_case(case["id"])["status"] == "ATTORNEY_NOTIFIED"


class TestCaseClose:
    def test_close_terminal_case_rejected(self, api):
        """PRD §3.2: "While a case stands at `IDENTIFIED` or `ATTORNEY_NOTIFIED`, a `RecoverySpecialist` or `RecoverySupervisor` may close it with no recovery, moving it to the terminal `CLOSED_NO_RECOVERY` status and incrementing the case's `version`; from `LIEN_FILED` onward the close is a generic state error."

        Design: Corner/state_machines/close_closed_case_returns_invalid_state
        """
        member = create_member(state_code="CA")
        case = create_case(member["id"])
        closed = validate_success(api.close_case(case["id"], SPEC), 200)
        assert closed["status"] == "CLOSED_NO_RECOVERY"
        resp = api.close_case(case["id"], SPEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_case(case["id"])["status"] == "CLOSED_NO_RECOVERY"


class TestLitigationTrack:
    def test_litigation_event_blocked_on_terminal_case(self, api):
        """PRD §3.2: "Filing suit — whether the initial filing or a refiling after dismissal — is accepted only while the case's resolution track is non-terminal, that is, not `RESOLVED`, `CLOSED_NO_RECOVERY`, or `SOL_EXPIRED`; otherwise the event is rejected with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/terminal_case_blocks_litigation_event
        """
        member = create_member(state_code="CA")
        case = create_case(member["id"])
        validate_success(api.close_case(case["id"], SPEC), 200)
        resp = api.record_litigation(case["id"], "FILE_SUIT", SPEC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        assert get_case(case["id"])["litigation_status"] == "NO_SUIT"

    def test_litigation_dismissed_then_refiled(self, api):
        """PRD §3.2: "`FILE_SUIT` moves `NO_SUIT` to `SUIT_FILED`; `RECORD_JUDGMENT` moves `SUIT_FILED` to `JUDGMENT`; `RECORD_DISMISSAL` moves `SUIT_FILED` to `SUIT_DISMISSED`; and a further `FILE_SUIT` after dismissal refills the track, moving `SUIT_DISMISSED` back to `SUIT_FILED`."

        Design: Corner/state_machines/litigation_dismissed_then_refiled
        """
        member = create_member(state_code="CA")
        case = create_case(member["id"])
        filed = validate_success(
            api.record_litigation(case["id"], "FILE_SUIT", SPEC), 200
        )
        assert filed["litigation_status"] == "SUIT_FILED"
        dismissed = validate_success(
            api.record_litigation(case["id"], "RECORD_DISMISSAL", SPEC), 200
        )
        assert dismissed["litigation_status"] == "SUIT_DISMISSED"
        refiled = validate_success(
            api.record_litigation(case["id"], "FILE_SUIT", SPEC), 200
        )
        assert refiled["litigation_status"] == "SUIT_FILED"
        final = get_case(case["id"])
        assert final["status"] == "IDENTIFIED", (
            "Litigation events must not move the resolution track"
        )

    def test_litigation_advances_while_resolution_stays_identified(self, api):
        """PRD §3.2: "Litigation proceeds on a parallel dimension, `litigation_status`, which evolves independently of the resolution-track `status`."

        Design: Difficulty/non_linear_state_machine/tpl_case_parallel_litigation_dimensions
        """
        member = create_member(state_code="CA", medicaid_id="M-LT-1")
        case = create_case(member["id"], injury_date="2026-01-01")
        after_suit = validate_success(
            api.record_litigation(case["id"], "FILE_SUIT", SPEC), 200
        )
        assert after_suit["litigation_status"] == "SUIT_FILED"
        assert after_suit["status"] == "IDENTIFIED", (
            "FILE_SUIT must not advance the resolution track"
        )

    def test_resolution_advances_while_litigation_holds_then_judgment(self, api):
        """PRD §3.2: "Litigation proceeds on a parallel dimension, `litigation_status`, which evolves independently of the resolution-track `status`."
        PRD §3.2: "`RECORD_JUDGMENT` moves `SUIT_FILED` to `JUDGMENT`"

        Design: Difficulty/non_linear_state_machine/tpl_case_parallel_litigation_dimensions
        """
        member = create_member(state_code="CA", medicaid_id="M-LT-1C")
        case = create_case(member["id"], injury_date="2026-01-01")
        validate_success(api.record_litigation(case["id"], "FILE_SUIT", SPEC), 200)
        after_notify = validate_success(api.notify_attorney(case["id"], SPEC), 200)
        assert after_notify["status"] == "ATTORNEY_NOTIFIED"
        assert after_notify["litigation_status"] == "SUIT_FILED", (
            "Attorney notification must not advance the litigation track"
        )
        after_judgment = validate_success(
            api.record_litigation(case["id"], "RECORD_JUDGMENT", SPEC), 200
        )
        assert after_judgment["litigation_status"] == "JUDGMENT"
        assert after_judgment["status"] == "ATTORNEY_NOTIFIED"


class TestCaseVersionBumps:
    def test_version_increments_once_per_case_mutation(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that increments with every modification to the resource."
        PRD §3.2: "The case's `total_paid_claims_cents` is then recomputed as the sum of `paid_amount_cents` over all of the case's expense claims — included in the lien basis or not — and each addition increments the case's `version`"

        Design: Corner/cross_cutting_complexity_layers/version_increments_on_each_mutation
        """
        member = create_member(state_code="CA")
        case = create_case(member["id"])
        v_created = case["version"]
        after_notify = validate_success(api.notify_attorney(case["id"], SPEC), 200)
        v_notify = after_notify["version"]
        assert v_notify == v_created + 1, (
            f"notify-attorney must increment the case version by one: "
            f"{v_created} -> {v_notify}"
        )
        add_expense_claim(case["id"], "2026-01-10", 100000)
        v_after_claim = get_case(case["id"])["version"]
        assert v_after_claim == v_notify + 1, (
            f"adding an expense claim must increment the case version by one: "
            f"{v_notify} -> {v_after_claim}"
        )
