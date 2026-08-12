"""State machine guards: initial states, inadmissible transitions, terminal
lockdown, single-fire execution (PRD §2.8 rule 5, §3)."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    ApiErrorId,
    create_active_indenture_with_tranche, setup_indenture_with_positions,
    register_account, register_position, create_obligation, create_interest_run,
    fund_run, execute_run, declare_default, confirm_default, create_direction,
    create_annual_invoice, issue_invoice, get_default_case, get_direction,
    get_fee_invoice, get_payment_run, list_run_records,
    create_appointment,
    make_platform_admin_headers, make_issuer_headers, make_trust_manager_headers,
    make_trust_officer_headers,
)

ADMIN = make_platform_admin_headers("admin-1")


class TestInitialStates:
    def test_entities_created_in_initial_states(self, api):
        """PRD §3.3: "Obligations are created `OPEN`"
        PRD §3.4: "A run is created `UNFUNDED` and `SCHEDULED`"
        PRD §3.5: "Declaration ... sets the case `ALLEGED`"
        PRD §3.8: "Drafting records `drafted_by_user_id` and leaves the
        invoice `DRAFT`."
        PRD §3.9: "Creation snapshots the indenture's `current_trustee_ref`
        into `outgoing_trustee_ref`, supersedes any in-flight appointment on
        the same indenture — both `PROPOSED` and `ACCEPTED` siblings become
        `SUPERSEDED` — increments the indenture's `version` by one, and
        starts the appointment `PROPOSED`."
        PRD §3.8: "The `amount_cents` of an `ANNUAL_ADMIN` invoice is simply
        the indenture's `annual_admin_fee_cents`."

        Design: Corner/state_machines/initial_states_on_creation
        """
        indenture, tranche = create_active_indenture_with_tranche()
        account = register_account("H-A", "Holder A", "a@x.com")
        register_position(tranche["id"], account["id"], 400000000)

        obligation = create_obligation(indenture["id"])
        assert obligation["status"] == "OPEN"
        assert obligation["next_due_date"] == "2026-06-30"

        run = create_interest_run(tranche["id"])
        assert run["funding_status"] == "UNFUNDED"
        assert run["distribution_status"] == "SCHEDULED"

        case = declare_default(indenture["id"], officer_id="officer-1")
        assert case["status"] == "ALLEGED"

        invoice = create_annual_invoice(indenture["id"], officer_id="officer-1")
        assert invoice["status"] == "DRAFT"
        assert invoice["amount_cents"] == 2500000

        appointment = create_appointment(indenture, incoming_trustee_ref="trustee-beta")
        assert appointment["status"] == "PROPOSED"
        assert appointment["outgoing_trustee_ref"] == "trustee-alpha"


class TestInadmissibleTransitions:
    def test_cure_alleged_default_rejected(self, api):
        """PRD §3.5: "A `TrustManager` may cure a `CONFIRMED` case while the
        logical clock reads at or before `cure_deadline`"
        PRD §2.8: "State admissibility: the target resource's state admits the
        operation — `ERR_INVALID_STATE`"

        Design: Corner/state_machines/cure_from_alleged_rejected_invalid_state
        """
        indenture, tranche = create_active_indenture_with_tranche()
        case = declare_default(indenture["id"], officer_id="officer-1")

        resp = api.cure_default_case(case["id"], make_trust_manager_headers("manager-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        case_after = get_default_case(case["id"])
        assert case_after["status"] == "ALLEGED", "case unchanged"

    def test_execute_circulating_direction_rejected(self, api):
        """PRD §3.5: "Execution belongs to the `TrustManager` and requires the
        direction to be `EFFECTIVE` at that moment — executing one that is not
        is rejected with `ERR_THRESHOLD_NOT_MET`."

        Design: Corner/state_machines/execute_circulating_direction_rejected_threshold_not_met
        """
        ctx = setup_indenture_with_positions(amounts=(400000000,), holder_prefixes=("H-A",))
        case = confirm_default(declare_default(ctx["indenture"]["id"])["id"])
        direction = create_direction(case["id"], "ACCELERATE")
        assert direction["status"] == "CIRCULATING"

        resp = api.execute_direction(direction["id"], make_trust_manager_headers("manager-1"))
        validate_error(resp, ApiErrorId.ERR_THRESHOLD_NOT_MET)

        direction_after = get_direction(direction["id"])
        assert direction_after["status"] == "CIRCULATING", "direction unchanged"

    def test_dispute_paid_invoice_rejected_terminal(self, api):
        """PRD §3.8: "The owning issuer then either pays the `ISSUED` invoice,
        moving it to the terminal `PAID`, or disputes it"
        PRD §2.8: "writes against a terminal state are rejected as
        `ERR_ALREADY_TERMINAL`"

        Design: Corner/state_machines/dispute_paid_invoice_rejected_already_terminal
        """
        indenture, tranche = create_active_indenture_with_tranche()
        invoice = create_annual_invoice(indenture["id"], officer_id="officer-1")
        issue_invoice(invoice["id"], manager_id="manager-1")
        paid = api.pay_fee_invoice(invoice["id"], make_issuer_headers("issuer-1"))
        validate_success(paid)

        resp = api.dispute_fee_invoice(invoice["id"], make_issuer_headers("issuer-1"))
        validate_error(resp, ApiErrorId.ERR_ALREADY_TERMINAL)

        invoice_after = get_fee_invoice(invoice["id"])
        assert invoice_after["status"] == "PAID", "invoice unchanged"

    def test_amend_draft_invoice_rejected(self, api):
        """PRD §3.8: "A `TrustOfficer` amends a `DISPUTED` invoice, replacing
        `extraordinary_hours` and/or `description`"
        PRD §2.8: "State admissibility: the target resource's state admits the
        operation — `ERR_INVALID_STATE`"

        Design: Corner/endpoints/amend_draft_invoice_rejected_conditional_action
        """
        indenture, tranche = create_active_indenture_with_tranche()
        invoice = create_annual_invoice(indenture["id"], officer_id="officer-1")
        assert invoice["status"] == "DRAFT"

        resp = api.amend_fee_invoice(
            invoice["id"], {"description": "premature"},
            make_trust_officer_headers("officer-1"))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_double_execute_rejected_single_fire(self, api):
        """PRD §3.4: "Execution, a `TrustOfficer` action, is gated by three
        checks: the run must be `FUNDED` (a shortfall is rejected with
        `ERR_FUNDING_SHORTFALL`, equality executes), the indenture must be
        `ACTIVE` (otherwise `ERR_INDENTURE_NOT_ACTIVE`), and the tranche must
        be `ACTIVE` (otherwise `ERR_INVALID_STATE`); a run whose distribution
        status is `SUSPENDED` also refuses execution under the state rules."
        PRD §3.4: "On execution `executed_at` is stamped from the logical
        clock and the run creates one **DistributionRecord**, status
        `PENDING`, per `ACTIVE` position of the tranche"

        Design: Corner/state_machines/double_execute_rejected_idempotency
        """
        ctx = setup_indenture_with_positions(amounts=(400000000,), holder_prefixes=("H-A",))
        run = create_interest_run(ctx["tranche"]["id"])
        fund_run(run["id"], 10166667, issuer_ref="issuer-1")
        execute_run(run["id"])

        # A DISTRIBUTED run admits no further execute transition; PRD §2.8
        # rule 5 names both the state-admissibility id and the terminal-write
        # id, and §3.4 calls DISTRIBUTED the run's terminal combined state.
        resp = api.execute_payment_run(run["id"], make_trust_officer_headers("officer-1"))
        actual = validate_error_is_one_of(
            resp, [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL])

        records = list_run_records(run["id"])
        assert len(records) == 1, "no duplicate allocation created"
