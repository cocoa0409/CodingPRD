"""Abandonment reviews: depth-3 execute cascade, family lifecycle gates,
pruning savings, SoD, open-review uniqueness (PRD §3.6, §3.1)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_us_rule,
    create_client,
    create_family,
    create_pending_application,
    create_granted_application,
    setup_counsel_firm,
    setup_oa_response_entry,
    send_instruction,
    acknowledge_instruction,
    authorize_obligation,
    propose_review,
    approved_review,
    list_obligations,
    get_application,
    get_family,
    create_rule,
)

ANY = TEST_USERS["any_headers"]
CLERK = TEST_USERS["clerk_headers"]
MGR = TEST_USERS["manager_headers"]
MGR2 = TEST_USERS["manager2_headers"]


def _prune_world():
    """US rule; firm; client+contact; family in PRUNING_REVIEW; GRANTED app with
    y3 obligation AUTHORIZED at 10000 (committed 10000) and y4/y5 SCHEDULED;
    OA-response entry IN_PROGRESS with an ACKNOWLEDGED linked instruction and an
    unlinked SENT FILING instruction; review APPROVED (submit mgr-1, approve
    mgr-2). Returns a context dict."""
    create_us_rule()
    firm = setup_counsel_firm()
    client = create_client("PruneCo")
    from test_helpers import create_contact
    contact = create_contact(client["id"])
    family = create_family(client["id"], budget_cap_cents=1000000)
    app = create_pending_application(family["id"], application_number="US-P")
    action, entry = setup_oa_response_entry(app["id"], mail_date="2026-05-20")
    validate_success(api_client.start_docket_entry(entry["id"], CLERK), 200)
    ins1 = send_instruction(app["id"], firm, instruction_type="OA_RESPONSE",
                            due_date="2026-08-20", docket_entry_id=entry["id"])
    acknowledge_instruction(ins1["id"], firm["id"])
    ins2 = send_instruction(app["id"], firm, instruction_type="FILING", due_date="2026-09-30")
    validate_success(api_client.grant_application(app["id"], {"grant_date": "2026-03-01"}, CLERK), 200)
    obligation = list_obligations(app["id"])[0]
    au = authorize_obligation(obligation["id"], 10000, contact["id"])
    validate_success(api_client.enter_pruning_review(family["id"], MGR), 200)
    review = approved_review(app["id"])
    return {
        "firm": firm, "client": client, "contact": contact, "family": family,
        "app": app, "action": action, "entry": entry, "ins1": ins1, "ins2": ins2,
        "obligation": obligation, "authorization": au, "review": review,
    }


class TestAbandonmentExecuteCascade:
    def test_execute_abandons_application_and_cancels_entries(self):
        """PRD §3.6: "Hop one: the application becomes `ABANDONED` — the cascade
        is identical whether it was `PENDING` or `GRANTED`. Hop two: every
        non-terminal docket entry of the application — `PENDING`,
        `IN_PROGRESS`, or `RESPONSE_FILED` — moves to `CANCELLED`, each
        decrementing the application's `open_docket_count`"

        Design: Difficulty/transitive_cascade/abandonment_execute_depth3_cascade
        """
        ctx = _prune_world()
        validate_success(api_client.execute_abandonment_review(ctx["review"]["id"], MGR2), 200)
        app = get_application(ctx["app"]["id"])
        assert app["status"] == "ABANDONED"
        assert app["open_docket_count"] == 0
        entry = validate_success(api_client.get_docket_entry(ctx["entry"]["id"], ANY), 200)
        assert entry["status"] == "CANCELLED"

    def test_execute_cancels_instructions_obligations_and_unwinds_rollup(self):
        """PRD §3.6: "every non-terminal annuity obligation — `SCHEDULED`,
        `PENDING_AUTHORIZATION`, `AUTHORIZED`, `PAYMENT_INSTRUCTED`, or
        `CONFIRMATION_QUERY` — moves to `CANCELLED`, where obligations in the
        three committed states additionally subtract their
        `authorized_amount_cents` from the family's `committed_forecast_cents`
        and supersede their current authorization (→ `SUPERSEDED`). Hop three:
        each entry cancellation cancels any instruction linked to that entry
        while the instruction is `DRAFT`, `SENT`, `ACKNOWLEDGED`, or
        `CONFIRMED` (→ `CANCELLED`), and closes any office action referencing
        the entry while it is `RECEIVED` or `UNDER_RESPONSE` (→ `CLOSED`).
        Finally, any remaining non-terminal instructions of the application
        that were never linked to an entry are cancelled as well."

        Design: Difficulty/transitive_cascade/abandonment_execute_depth3_cascade
        """
        ctx = _prune_world()
        validate_success(api_client.execute_abandonment_review(ctx["review"]["id"], MGR2), 200)
        # Linked instruction cancelled via the entry cascade (hop 3).
        ins1 = validate_success(api_client.get_instruction(ctx["ins1"]["id"], ANY), 200)
        assert ins1["status"] == "CANCELLED"
        # Unlinked instruction cancelled by the final sweep of the cascade.
        ins2 = validate_success(api_client.get_instruction(ctx["ins2"]["id"], ANY), 200)
        assert ins2["status"] == "CANCELLED"
        # Committed obligation cancelled, authorization superseded, rollup unwound.
        ob = validate_success(api_client.get_annuity_obligation(ctx["obligation"]["id"], ANY), 200)
        assert ob["status"] == "CANCELLED"
        au = validate_success(api_client.get_authorization(ctx["authorization"]["id"], ANY), 200)
        assert au["status"] == "SUPERSEDED"
        assert get_family(ctx["family"]["id"])["committed_forecast_cents"] == 0
        # Hop 3 also closes the office action referencing the cancelled entry.
        action = validate_success(api_client.get_office_action(ctx["action"]["id"], ANY), 200)
        assert action["status"] == "CLOSED"

    def test_review_savings_estimate_excludes_committed_obligations(self):
        """PRD §3.6: "the sum of `estimated_amount_usd_cents` over the
        application's obligations currently in `SCHEDULED` status, minus a
        fixed pruning administration fee of 15000 cents, floored at zero so a
        heavily committed application never shows negative savings.
        Obligations already `PENDING_AUTHORIZATION` or `AUTHORIZED` contribute
        nothing to the estimate — their spend is already committed"

        Design: Difficulty/transitive_cascade/abandonment_execute_depth3_cascade
        """
        ctx = _prune_world()
        # SCHEDULED y4 20000 + y5 20000 = 40000 gross, minus 15000 -> 25000;
        # the AUTHORIZED y3 obligation is excluded.
        assert ctx["review"]["estimated_savings_usd_cents"] == 25000


class TestPruningSavingsZeroFloor:
    def test_negative_net_savings_floored_at_zero(self):
        """PRD §3.6: "minus a fixed pruning administration fee of 15000 cents,
        floored at zero so a heavily committed application never shows negative
        savings."

        Design: Corner/calculations/pruning_savings_zero_floor
        """
        from test_helpers.factories import create_jurisdiction_rule_payload
        create_rule(create_jurisdiction_rule_payload(
            jurisdiction="CN", annuity_start_year=3, term_years=3))
        client = create_client("SaveCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_granted_application(
            family["id"], jurisdiction="CN", application_number="CN-S")
        # Only obligation estimates 10000: gross 10000 - 15000 < 0 -> 0.
        review = propose_review(app["id"], rationale="floor check")
        assert review["status"] == "PROPOSED"
        assert review["estimated_savings_usd_cents"] == 0


class TestFamilyLifecycleGates:
    def test_close_blocked_while_application_open(self):
        """PRD §3.1: "Closing a family — defined from both `ACTIVE` and
        `PRUNING_REVIEW` — requires every application of the family to already
        sit in a terminal state, that is `ABANDONED`, `LAPSED`, or `WITHDRAWN`;
        if any application is still open, the close is rejected with
        `ERR_FAMILY_HAS_OPEN_APPLICATIONS`."

        Design: Corner/validations/family_lifecycle_gates_close_exit_execute
        """
        create_us_rule()
        client = create_client("GateFam")
        family = create_family(client["id"], title="F1")
        create_pending_application(family["id"], application_number="US-G1")
        validate_error(api_client.close_family(family["id"], MGR),
                       ApiErrorId.ERR_FAMILY_HAS_OPEN_APPLICATIONS)

    def test_execute_blocked_until_family_in_pruning_review_then_succeeds(self):
        """PRD §3.6: "Executing an approved review requires the family to be in
        `PRUNING_REVIEW` (`ERR_FAMILY_NOT_IN_PRUNING_REVIEW`) and fires the
        abandonment cascade in hops."

        Design: Corner/validations/family_lifecycle_gates_close_exit_execute
        """
        create_us_rule()
        client = create_client("GateFam")
        family = create_family(client["id"], title="F2")
        app = create_pending_application(family["id"], application_number="US-G2")
        review = approved_review(app["id"])
        validate_error(api_client.execute_abandonment_review(review["id"], MGR2),
                       ApiErrorId.ERR_FAMILY_NOT_IN_PRUNING_REVIEW)
        validate_success(api_client.enter_pruning_review(family["id"], MGR), 200)
        data = validate_success(api_client.execute_abandonment_review(review["id"], MGR2), 200)
        assert data["status"] == "EXECUTED"
        assert get_application(app["id"])["status"] == "ABANDONED"

    def test_exit_pruning_review_blocked_while_approved_review_exists(self):
        """PRD §3.1: "the exit is blocked while any application of the family
        carries an abandonment review in `APPROVED` status, surfacing
        `ERR_FAMILY_HAS_APPROVED_REVIEWS`."

        Design: Corner/validations/family_lifecycle_gates_close_exit_execute
        """
        create_us_rule()
        client = create_client("GateFam")
        family = create_family(client["id"], title="F2")
        app = create_pending_application(family["id"], application_number="US-G2")
        approved_review(app["id"])
        validate_success(api_client.enter_pruning_review(family["id"], MGR), 200)
        validate_error(api_client.exit_pruning_review(family["id"], MGR),
                       ApiErrorId.ERR_FAMILY_HAS_APPROVED_REVIEWS)


class TestSegregationOfDutiesOnReview:
    def test_submitter_cannot_approve(self):
        """PRD §3.6: "Approving (`UNDER_REVIEW → APPROVED`) and rejecting
        (`UNDER_REVIEW → REJECTED`) are segregation-of-duties gated: the
        deciding user's `X-User-ID` must differ from the recorded
        `submitted_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/sod_review_submitter_cannot_approve
        """
        from test_helpers import propose_and_submit_review
        create_us_rule()
        client = create_client("SoDCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-SD")
        review = propose_and_submit_review(app["id"], submitter_headers=MGR)
        validate_error(api_client.approve_abandonment_review(review["id"], MGR),
                       ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        data = validate_success(api_client.approve_abandonment_review(review["id"], MGR2), 200)
        assert data["status"] == "APPROVED"


class TestReviewAlreadyOpen:
    def test_second_review_with_fresh_version_rejected_already_open(self):
        """PRD §3.6: "At most one review per application may be open at a time —
        open meaning any of `PROPOSED`, `UNDER_REVIEW`, or `APPROVED` — and a
        second proposal while one is open is rejected with
        `ERR_REVIEW_ALREADY_OPEN`."

        Design: Corner/validations/review_already_open_and_occ_precedence
        """
        create_us_rule()
        client = create_client("RvCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-RV")
        propose_review(app["id"], rationale="first")
        # The second proposal carries the CURRENT application version, so the
        # optimistic-concurrency check passes and the open-review rule fires.
        app_now = get_application(app["id"])
        resp = api_client.create_abandonment_review(
            app["id"],
            {"rationale": "second", "expected_application_version": app_now["version"]},
            MGR,
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_ALREADY_OPEN)
