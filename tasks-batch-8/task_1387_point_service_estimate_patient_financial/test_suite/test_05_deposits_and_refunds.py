"""Deposit ledger, refund business-day schedule, and clearance regression."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_case,
    create_deposit_payload,
    create_patient,
    pledge_and_post_deposit,
    set_clock,
    setup_accepted_insured_estimate,
    setup_cleared_insured_case,
    setup_presented_insured_estimate,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)

COUNSELOR = TEST_USERS["counselor_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestRefundRegressesClearedCase:
    """Depth-2 chain: refund mutates the case ledger, which recomputes
    deposit_satisfied and regresses the case."""

    def _setup(self):
        ctx = setup_cleared_insured_case(mrn="MRN-R-1", requires_auth_prior=True)
        assert ctx["case"]["status"] == "CLEARED"
        # Eight business days before the 2026-08-20 service date.
        set_clock("2026-08-10T09:00:00Z")
        res = api_client.refund_deposit(ctx["deposit"]["id"], SUPERVISOR)
        ctx["refunded"] = validate_success(res, 200)
        ctx["case_after"] = validate_success(
            api_client.get_case(ctx["case"]["id"], SUPERVISOR), 200)
        return ctx

    def test_refund_full_amount_leaves_deposit_ledger(self, api):
        """PRD §3.6: "the case's `deposit_posted_cents` decreases by the
        deposit's full `amount_cents`, not by the refunded portion: any
        retained cancellation fee leaves the deposit ledger entirely."
        PRD §3.6: "When at least two business days remain before service, the
        patient receives a full refund of the pledged amount — exactly two
        business days out still qualifies for the full amount."

        Design: Difficulty/transitive_cascade/deposit_refund_ledger_posture_regression
        """
        ctx = self._setup()
        assert ctx["refunded"]["status"] == "REFUNDED"
        assert ctx["refunded"]["refund_amount_cents"] == 125000, (
            "8 business days before service -> 100% tier")
        assert ctx["refunded"]["refund_reason"] == "SERVICE_CANCELLED"
        assert ctx["case_after"]["deposit_posted_cents"] == 0, (
            "the full posted amount leaves the ledger")

    def test_ledger_drop_breaks_deposit_satisfied_and_regresses_case(self, api):
        """PRD §3.6: "if the case was `CLEARED` and the requirement is no
        longer met, the case automatically regresses to `IN_REVIEW` with
        `clearance_posture` back to `BLOCKED`."

        Design: Difficulty/transitive_cascade/deposit_refund_ledger_posture_regression
        """
        ctx = self._setup()
        assert ctx["case_after"]["deposit_satisfied"] is False
        assert ctx["case_after"]["status"] == "IN_REVIEW"
        assert ctx["case_after"]["clearance_posture"] == "BLOCKED"
        # The regression is fiscal, not compliance: the authorization remains
        # APPROVED within its validity window.
        assert ctx["case_after"]["auth_satisfied"] is True


class TestDepositLedgerConservation:
    """The case ledger equals the sum of POSTED amounts across a post/refund pair."""

    def _setup(self):
        ctx = setup_accepted_insured_estimate(mrn="MRN-L-1")
        case_id = ctx["case"]["id"]
        case_before = validate_success(api_client.get_case(case_id, COUNSELOR), 200)
        dep1 = pledge_and_post_deposit(case_id, 100000, method="CARD")
        dep2 = pledge_and_post_deposit(case_id, 50000, method="CHECK")
        case_mid = validate_success(api_client.get_case(case_id, COUNSELOR), 200)
        return ctx, case_before, dep1, dep2, case_mid

    def test_post_pair_accumulates_ledger(self, api):
        """PRD §3.3: "`deposit_posted_cents` is a ledger: the sum of
        `amount_cents` over the case's deposits currently in `POSTED` status."
        PRD §3.6: "Posting the deposit — also a counselor action — moves
        `PLEDGED` → `POSTED`, stamps `posted_at`, and syncs the ledger: the
        case's `deposit_posted_cents` increases by the deposit's amount and
        `deposit_satisfied` is recomputed."

        Design: Difficulty/compensating_invariant/deposit_post_refund_ledger_conservation
        """
        _ctx, case_before, dep1, dep2, case_mid = self._setup()
        assert case_before["deposit_posted_cents"] == 0
        assert dep1["status"] == "POSTED" and dep2["status"] == "POSTED"
        assert case_mid["deposit_posted_cents"] == 150000, (
            "100000 + 50000, the sum over POSTED deposits")

    def test_refund_returns_ledger_to_surviving_posted_sum(self, api):
        """PRD §3.6: "the case's `deposit_posted_cents` decreases by the
        deposit's full `amount_cents`, not by the refunded portion: any
        retained cancellation fee leaves the deposit ledger entirely."
        PRD §3.3: "`deposit_posted_cents` is a ledger: the sum of
        `amount_cents` over the case's deposits currently in `POSTED` status."

        Design: Difficulty/compensating_invariant/deposit_post_refund_ledger_conservation
        """
        ctx, case_before, dep1, dep2, case_mid = self._setup()
        # Clock still 2026-08-03, thirteen business days before service: 100%.
        refunded = validate_success(api_client.refund_deposit(dep1["id"], SUPERVISOR), 200)
        assert refunded["refund_amount_cents"] == 100000
        assert refunded["status"] == "REFUNDED"
        case_after = validate_success(
            api_client.get_case(ctx["case"]["id"], COUNSELOR), 200)
        assert case_after["deposit_posted_cents"] == 50000, (
            "post+refund pair leaves the ledger changed only by the surviving "
            "deposit — no drift")
        dep2_after = validate_success(
            api_client.list_case_deposits(ctx["case"]["id"], COUNSELOR), 200)
        statuses = {d["id"]: d["status"] for d in dep2_after}
        assert statuses[dep2["id"]] == "POSTED"


class TestRefundWindowBoundary:
    def test_refund_window_boundary_two_business_days(self, api):
        """PRD §3.6: "When at least two business days remain before service,
        the patient receives a full refund of the pledged amount — exactly two
        business days out still qualifies for the full amount. When exactly one
        business day remains, the refund is fifty percent of the amount,
        rounded half up to a whole cent."
        PRD §2.4: "When a rule speaks of the number of business days between a
        date A and a later date B, it means the count of weekdays that fall
        strictly after A and on or before B."

        Design: Corner/calculations/refund_window_boundary_two_business_days
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-CA-8")
        case_a = create_case(patient["id"], service_date="2026-08-20",
                             service_description="Case A")
        dep_a = pledge_and_post_deposit(case_a["id"], 125000)
        case_b = create_case(patient["id"], service_date="2026-08-20",
                             service_description="Case B")
        dep_b = pledge_and_post_deposit(case_b["id"], 125000)

        # 2026-08-18 (Tue): weekdays in (18, 20] = {19, 20} = 2 -> full refund.
        set_clock("2026-08-18T09:00:00Z")
        refund_a = validate_success(api_client.refund_deposit(dep_a["id"], SUPERVISOR), 200)
        assert refund_a["refund_amount_cents"] == 125000, "boundary included"
        assert refund_a["status"] == "REFUNDED"
        assert refund_a["refund_reason"] == "SERVICE_CANCELLED"

        # 2026-08-19 (Wed): weekdays in (19, 20] = {20} = 1 -> 50% tier.
        set_clock("2026-08-19T09:00:00Z")
        refund_b = validate_success(api_client.refund_deposit(dep_b["id"], SUPERVISOR), 200)
        assert refund_b["refund_amount_cents"] == 62500, "half of 125000"
        assert refund_b["status"] == "REFUNDED"
        assert refund_b["refund_reason"] == "SERVICE_CANCELLED"


class TestRefundStateGuard:
    def test_refund_pledged_deposit_returns_invalid_state(self, api):
        """PRD §3.6: "Only `POSTED` deposits count toward the requirement, and
        only a `POSTED` deposit can be refunded — attempting the refund
        transition on a deposit in any other state is `ERR_INVALID_STATE`."

        Design: Corner/state_machines/refund_pledged_deposit_returns_invalid_state
        """
        set_clock("2026-08-03T09:00:00Z")
        patient = create_patient(mrn="MRN-SM-3")
        case = create_case(patient["id"], service_date="2026-08-20")
        pledged = validate_success(api_client.create_deposit(
            case["id"], create_deposit_payload(amount_cents=100000, method="CARD"),
            COUNSELOR), 201)
        res = api_client.refund_deposit(pledged["id"], SUPERVISOR)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        deposits, _m = validate_paginated(
            api_client.list_case_deposits(case["id"], SUPERVISOR))
        assert deposits[0]["status"] == "PLEDGED"


class TestDepositPostingVisibility:
    def test_deposit_post_immediately_visible_on_case(self, api):
        """PRD §3.6: "Posting the deposit — also a counselor action — moves
        `PLEDGED` → `POSTED`, stamps `posted_at`, and syncs the ledger: the
        case's `deposit_posted_cents` increases by the deposit's amount and
        `deposit_satisfied` is recomputed."
        PRD §2.10: "Whenever a child event changes the inputs to one of these
        derived values, the server recomputes the case immediately, within the
        same operation".

        Design: Corner/consistency_model/deposit_post_immediately_visible_on_case
        """
        ctx = setup_accepted_insured_estimate(mrn="MRN-IM-1")
        case_id = ctx["case"]["id"]
        pledged = validate_success(api_client.create_deposit(
            case_id, create_deposit_payload(amount_cents=125000, method="CARD"),
            COUNSELOR), 201)
        posted = validate_success(api_client.post_deposit(pledged["id"], COUNSELOR), 200)
        assert posted["status"] == "POSTED"
        assert posted["posted_at"] == "2026-08-03T09:00:00.000Z", (
            "posted_at stamps the current logical time")
        case = validate_success(api_client.get_case(case_id, COUNSELOR), 200)
        assert case["deposit_posted_cents"] == 125000
        assert case["deposit_satisfied"] is True, "125000 >= 125000"


class TestRequiredDepositConstant:
    def test_required_deposit_is_quarter_of_responsibility(self, api):
        """PRD §3.3: "`required_deposit_cents` is zero until an estimate on the
        case is accepted, and thereafter is twenty-five percent of the accepted
        estimate's `patient_responsibility_cents`, rounded half up to a whole
        cent."
        PRD §3.3: "`deposit_satisfied` is true when the active estimate is
        `FINALIZED`, or when the posted ledger meets or exceeds
        `required_deposit_cents` while an estimate stands `ACCEPTED` or
        `FINALIZED`."

        Design: Corner/calculations/required_deposit_is_quarter_of_responsibility
        """
        ctx = setup_presented_insured_estimate(mrn="MRN-CA-6")
        case_id = ctx["case"]["id"]
        case_before = validate_success(api_client.get_case(case_id, COUNSELOR), 200)
        assert case_before["required_deposit_cents"] == 0, (
            "zero until an estimate is accepted")
        accept_res = api_client.accept_estimate(ctx["estimate"]["id"], COUNSELOR)
        validate_success(accept_res, 200)
        case = validate_success(api_client.get_case(case_id, COUNSELOR), 200)
        assert case["required_deposit_cents"] == 125000, (
            "round_half_up(25% x 500000)")
        assert case["deposit_satisfied"] is False, "no deposit posted yet"
