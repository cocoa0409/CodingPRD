"""Case transfers (PRD §3.6): the freeze while INITIATED, the divergent
ACCEPTED/REJECTED branches, withdrawal, the single-open-transfer rule, and
the full transfer-out cascade.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    setup_arrived_case, get_case, get_housing_unit,
    make_orientation_session, make_benefit_application, transition_application,
    make_employment_plan, make_case_transfer, respond_case_transfer,
    withdraw_case_transfer, get_benchmark_by_type, list_orientation_sessions,
)
from test_helpers.fixtures import CM, HC, ES


def _arrived_case_with_transfer(case_number, members=(), household_size=1,
                                receiving="AFF-99", reason="SECONDARY_MIGRATION"):
    ctx = setup_arrived_case(case_number=case_number, household_size=household_size,
                             members=members)
    transfer = make_case_transfer(ctx["case"]["id"],
                                  receiving_affiliate_code=receiving,
                                  reason=reason)
    return ctx, transfer


class TestTransferFreeze:
    def test_orientation_session_create_frozen_while_transfer_open(self, api):
        """PRD §3.6: "While a transfer is `INITIATED`, the freeze blocks
        child mutations on the case — benefit application creation,
        employment plan creation, orientation session scheduling and
        completion, benchmark fulfillment, manual waiver, and rescind all
        fail with `ERR_CASE_TRANSFER_PENDING`".

        Design: Difficulty/cross_entity_state_dependency/transfer_open_blocks_orientation
        """
        ctx, _ = _arrived_case_with_transfer("CASE-XD2",
                                             reason="EMPLOYMENT_OPPORTUNITY")
        resp = api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "US_LAWS",
             "start_at": "2026-08-20T09:00:00Z", "end_at": "2026-08-20T10:00:00Z"}, CM)
        validate_error(resp, ApiErrorId.ERR_CASE_TRANSFER_PENDING)

    def test_withdraw_unfreezes_and_session_create_succeeds(self, api):
        """PRD §3.6: "The initiator may also abandon the process:
        withdrawing an `INITIATED` transfer moves it `INITIATED → WITHDRAWN`,
        clears the case's `open_transfer_id` to null, and increments the
        case's `version` by 1 — like rejection, withdrawal performs no
        service cascade."

        Design: Difficulty/cross_entity_state_dependency/transfer_open_blocks_orientation
        """
        ctx, transfer = _arrived_case_with_transfer("CASE-XD2B",
                                                    reason="EMPLOYMENT_OPPORTUNITY")
        withdrawn = withdraw_case_transfer(transfer["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["open_transfer_id"] is None
        session = validate_success(api.create_orientation_session(
            {"case_id": ctx["case"]["id"], "topic": "US_LAWS",
             "start_at": "2026-08-20T09:00:00Z", "end_at": "2026-08-20T10:00:00Z"}, CM), 201)
        assert session["status"] == "SCHEDULED"

    def test_benefit_application_create_frozen_while_transfer_open(self, api):
        """PRD §3.6: "While a transfer is `INITIATED`, the freeze blocks
        child mutations on the case — benefit application creation,
        employment plan creation, orientation session scheduling and
        completion, benchmark fulfillment, manual waiver, and rescind all
        fail with `ERR_CASE_TRANSFER_PENDING`".

        Design: Corner/validations/transfer_freeze_blocks_application_create
        """
        ctx, _ = _arrived_case_with_transfer(
            "CASE-V10", household_size=1,
            members=[{"full_name": "Adult W", "date_of_birth": "1990-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True}])
        resp = api.create_benefit_application(
            {"case_id": ctx["case"]["id"], "member_id": ctx["members"][0]["id"],
             "benefit_type": "SSN"}, CM)
        validate_error(resp, ApiErrorId.ERR_CASE_TRANSFER_PENDING)


class TestSingleOpenTransfer:
    def test_second_transfer_while_open_rejected(self, api):
        """PRD §3.6: "Only one transfer may be open per case: initiating
        while another transfer for the same case is `INITIATED` is rejected
        with `ERR_TRANSFER_ALREADY_OPEN` (HTTP 409)."

        Design: Corner/validations/duplicate_open_transfer_returns_already_open
        """
        ctx, _ = _arrived_case_with_transfer("CASE-V11")
        resp = api.create_case_transfer(
            {"case_id": ctx["case"]["id"], "receiving_affiliate_code": "AFF-77",
             "reason": "FAMILY_REUNIFICATION"}, CM)
        validate_error(resp, ApiErrorId.ERR_TRANSFER_ALREADY_OPEN)


class TestTransferBranchingDivergentEffects:
    def _case_with_session_and_transfer(self, case_number):
        ctx = setup_arrived_case(case_number=case_number, household_size=1)
        session = make_orientation_session(
            ctx["case"]["id"], topic="US_LAWS",
            start_at="2026-08-20T09:00:00Z", end_at="2026-08-20T10:00:00Z")
        transfer = make_case_transfer(ctx["case"]["id"],
                                      receiving_affiliate_code="AFF-99",
                                      reason="SECONDARY_MIGRATION")
        return ctx, session, transfer

    def test_rejected_branch_unfreezes_without_cascade(self, api):
        """PRD §3.6: "On `REJECTED`, the transfer moves `INITIATED →
        REJECTED`, the case's `open_transfer_id` clears to null, the case's
        `version` increments by 1, and nothing else happens — no service
        cascade touches the sessions, applications, plan, or housing setup."

        Design: Difficulty/non_linear_state_machine/transfer_branching_divergent_effects
        """
        ctx, session, transfer = self._case_with_session_and_transfer("CASE-NL2X")
        responded = respond_case_transfer(
            transfer["id"], "REJECTED",
            decision_note="Receiving affiliate at capacity")
        assert responded["status"] == "REJECTED"
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["status"] == "ARRIVED"
        assert case["open_transfer_id"] is None
        sessions = list_orientation_sessions(ctx["case"]["id"], headers=CM)
        assert [s["status"] for s in sessions if s["id"] == session["id"]] == ["SCHEDULED"]

    def test_accepted_branch_runs_full_cascade(self, api):
        """PRD §3.6: "On `ACCEPTED`, the transfer moves `INITIATED →
        COMPLETED` and the case itself transitions `ARRIVED →
        TRANSFERRED_OUT`, firing the full transfer-out cascade in the same
        request: `open_transfer_id` clears to null" and "every `SCHEDULED`
        orientation session moves to `CANCELLED`".

        Design: Difficulty/non_linear_state_machine/transfer_branching_divergent_effects
        """
        ctx, session, transfer = self._case_with_session_and_transfer("CASE-NL2Y")
        responded = respond_case_transfer(transfer["id"], "ACCEPTED",
                                          decision_note="Case accepted")
        assert responded["status"] == "COMPLETED"
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["status"] == "TRANSFERRED_OUT"
        assert case["open_transfer_id"] is None
        sessions = list_orientation_sessions(ctx["case"]["id"], headers=CM)
        assert [s["status"] for s in sessions if s["id"] == session["id"]] == ["CANCELLED"]


class TestTransferAcceptDepthCascade:
    def _loaded_case_with_transfer(self):
        ctx = setup_arrived_case(
            case_number="CASE-TC1", household_size=1,
            members=[{"full_name": "Adult T", "date_of_birth": "1990-01-01",
                      "relationship": "PRINCIPAL", "work_eligible": True}])
        case_id = ctx["case"]["id"]
        session = make_orientation_session(
            case_id, topic="US_LAWS",
            start_at="2026-08-20T09:00:00Z", end_at="2026-08-20T10:00:00Z")
        app = make_benefit_application(case_id, ctx["members"][0]["id"])
        transition_application(app["id"], "FILED")
        plan = make_employment_plan(case_id)
        transfer = make_case_transfer(case_id, receiving_affiliate_code="AFF-99",
                                      reason="FAMILY_REUNIFICATION")
        return ctx, session, app, plan, transfer

    def test_accept_cascades_through_session_cancel_to_benchmark_waive(self, api):
        """PRD §3.6: "every `SCHEDULED` orientation session moves to
        `CANCELLED`; because those sessions were cancelled, the case's
        `CULTURAL_ORIENTATION` benchmark, if still `PENDING`, moves to
        `WAIVED` with `waived_reason` recorded as `TRANSFER`; and every other
        `PENDING` benchmark likewise moves to `WAIVED` with `waived_reason`
        `TRANSFER`."

        Design: Difficulty/transitive_cascade/transfer_accept_depth3_cascade
        """
        ctx, session, _, _, transfer = self._loaded_case_with_transfer()
        responded = respond_case_transfer(transfer["id"], "ACCEPTED",
                                          decision_note="Accepted")
        assert responded["status"] == "COMPLETED"
        case = get_case(ctx["case"]["id"], headers=CM)
        assert case["status"] == "TRANSFERRED_OUT"
        sessions = list_orientation_sessions(ctx["case"]["id"], headers=CM)
        assert [s["status"] for s in sessions if s["id"] == session["id"]] == ["CANCELLED"]
        co = get_benchmark_by_type(ctx["case"]["id"], "CULTURAL_ORIENTATION")
        assert co["status"] == "WAIVED"
        assert co["waived_reason"] == "TRANSFER"

    def test_accept_cascade_fans_to_application_plan_and_housing(self, api):
        """PRD §3.6: "the case's non-terminal housing setup (whether
        `PREPARING`, `READY`, or `OCCUPIED`) moves to `VACATED` and the
        unit's derived status recomputes — `AVAILABLE` unless another
        non-terminal setup still covers today; any `ACTIVE` employment plan
        moves to `CLOSED_TRANSFERRED`; every benefit application in `DRAFT`,
        `FILED`, `DENIED`, or `APPEALED` moves to `WITHDRAWN`".

        Design: Difficulty/transitive_cascade/transfer_accept_depth3_cascade
        """
        ctx, _, app, plan, transfer = self._loaded_case_with_transfer()
        respond_case_transfer(transfer["id"], "ACCEPTED", decision_note="Accepted")
        apps = get_success_data(api.list_benefit_applications(
            CM, params={"case_id": ctx["case"]["id"]}))
        assert [a["status"] for a in apps if a["id"] == app["id"]] == ["WITHDRAWN"]
        plans = get_success_data(
            api.list_employment_plans(ctx["case"]["id"], ES))
        assert [p["status"] for p in plans if p["id"] == plan["id"]] == ["CLOSED_TRANSFERRED"]
        setups = get_success_data(
            api.list_case_housing_setups(ctx["case"]["id"], HC))
        assert setups[0]["status"] == "VACATED"
        unit = get_housing_unit(ctx["unit"]["id"], headers=HC)
        assert unit["status"] == "AVAILABLE"
