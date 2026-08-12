"""Client lifecycle cascades and conserved-quantity invariants (PRD §3.1, §3.2,
§3.3, §3.6, §3.8, §2.7)."""
from test_helpers import (
    validate_success, validate_error_is_one_of,
    set_logical_clock, make_platform_profile, make_client, make_project,
    make_engineer, make_rush_tier_rule,
    setup_booked_project, setup_project_in_revision, approve_current_round,
    setup_archived_project, create_credit_adjustment_payload,
    create_project_payload, make_client_headers, TEST_USERS, ApiErrorId,
)

MANAGER = TEST_USERS["manager_headers"]

SUSPEND_QUOTE = (
    "Moving a client from `ACTIVE` to `SUSPENDED` releases every session slot in "
    "`HELD` status attached to projects owned by that client, cancels every project "
    "of that client still in `DRAFT`, `BOOKED`, or `INTAKE` — each landing in "
    "`CANCELLED` — and increments the client's `version`."
)

APC_QUOTE = (
    "The `active_project_count` tracks how many of the engineer's assigned projects "
    "currently sit in `BOOKED`, `INTAKE`, `MASTERING`, or `REVISION`; it bumps when "
    "a booking assigns the engineer and again when a recalled project resumes into "
    "mastering, and it decrements when a project is archived, when a booked or "
    "in-progress project is cancelled, and when a booked slot is cancelled."
)


class TestClientSuspendCascade:

    def test_suspend_cancels_booked_project(self, api):
        """PRD §3.1: "%s"

        The BOOKED project owned by the suspended client lands in CANCELLED.

        Design: Difficulty/transitive_cascade/client_suspend_depth3_cascade
        """ % SUSPEND_QUOTE
        ctx = setup_booked_project()
        client = validate_success(
            api.suspend_client(ctx["client"]["id"], MANAGER), 200)
        assert client["status"] == "SUSPENDED"
        project = validate_success(
            api.get_project(ctx["project"]["id"], MANAGER), 200)
        assert project["status"] == "CANCELLED"

    def test_suspend_reconciles_engineer_active_project_count(self, api):
        """PRD §3.1: "%s" PRD §3.2: "%s"

        The cancellation cascade decrements the assigned engineer's
        active_project_count back to zero.

        Design: Difficulty/transitive_cascade/client_suspend_depth3_cascade
        """ % (SUSPEND_QUOTE, APC_QUOTE)
        ctx = setup_booked_project()
        engineer = validate_success(
            api.get_engineer(ctx["engineer"]["id"], MANAGER), 200)
        assert engineer["active_project_count"] == 1

        api.suspend_client(ctx["client"]["id"], MANAGER)
        engineer = validate_success(
            api.get_engineer(ctx["engineer"]["id"], MANAGER), 200)
        assert engineer["active_project_count"] == 0


class TestEngineerActiveProjectCountConserved:

    def test_booking_bumps_active_project_count(self, api):
        """PRD §3.2: "%s"

        Design: Difficulty/compensating_invariant/engineer_active_project_count_conserved_across_book_and_archive
        """ % APC_QUOTE
        ctx = setup_booked_project()
        engineer = validate_success(
            api.get_engineer(ctx["engineer"]["id"], MANAGER), 200)
        assert engineer["active_project_count"] == 1

    def test_archive_restores_active_project_count_to_zero(self, api):
        """PRD §3.2: "%s" PRD §3.8: "Archiving creates the project's ArchiveBundle
        with `recall_status` set to `NONE` — exactly one archive bundle may exist per
        project — writes the project's `archive_bundle_id`, moves the project
        `DELIVERED → ARCHIVED`, decrements the assigned engineer's
        `active_project_count`, and increments the project's `version`."

        Book (+1) then archive (-1): the counter is conserved across the lifecycle.

        Design: Difficulty/compensating_invariant/engineer_active_project_count_conserved_across_book_and_archive
        """ % APC_QUOTE
        ctx = setup_archived_project()
        assert ctx["project"]["status"] == "ARCHIVED"
        engineer = validate_success(
            api.get_engineer(ctx["engineer"]["id"], MANAGER), 200)
        assert engineer["active_project_count"] == 0


class TestClientCreditConserved:

    def test_approval_debits_client_by_final_price(self, api):
        """PRD §3.6: "Approval moves the round `SUBMITTED → APPROVED`, stamps
        `resolved_at`, runs the final quote and writes `final_price_cents` in place
        of the provisional figure, debits the client's `account_credit_cents` by that
        amount — a debit that would push the balance negative is rejected with
        `ERR_INSUFFICIENT_CREDIT` (HTTP 402) — and moves the project `REVISION →
        APPROVED` with its `version` incremented."

        STANDARD tier, 1 hour at 80000 cents: final price 80000 is debited from the
        100000 balance, leaving 20000. The ledger plus the project price equals the
        pre-approval balance.

        Design: Difficulty/compensating_invariant/client_credit_conserved_debit_matches_project_price
        """
        ctx = setup_project_in_revision(credit_cents=100000)
        ctx = approve_current_round(ctx)
        assert ctx["project"]["final_price_cents"] == 80000
        assert ctx["client"]["account_credit_cents"] == 100000 - 80000
        assert (ctx["client"]["account_credit_cents"]
                + ctx["project"]["final_price_cents"]) == 100000

    def test_credit_adjustment_restores_balance_after_debit(self, api):
        """PRD §2.7: "A studio manager may adjust a client's prepaid balance at any
        time by posting a signed `amount_cents` — positive to add credit, negative to
        remove it — together with a `reason`; the adjustment lands directly on
        `account_credit_cents`." PRD §2.7: "The ledger is debited when a revision
        round is approved (by the project's `final_price_cents`) and when an archive
        recall is requested (by the bundle's `recall_fee_cents`)."

        A compensating +80000 adjustment after the 80000 approval debit restores the
        original 100000 balance.

        Design: Difficulty/compensating_invariant/client_credit_conserved_debit_matches_project_price
        """
        ctx = setup_project_in_revision(credit_cents=100000)
        ctx = approve_current_round(ctx)
        client = validate_success(api.create_credit_adjustment(
            ctx["client"]["id"],
            create_credit_adjustment_payload(amount_cents=80000, reason="refund"),
            MANAGER), 201)
        assert client["account_credit_cents"] == 100000


class TestProjectCancelAndInitialState:

    def test_second_cancel_on_cancelled_project_rejected(self, api):
        """PRD §3.3: "Cancellation is available while a project is in `DRAFT`,
        `BOOKED`, or `INTAKE`, to the owning client or a studio manager, and lands
        the project in the terminal `CANCELLED` state." PRD §2.5: "Fifth (priority
        5), state admissibility: the resource's current state must permit the
        requested transition on every action endpoint, failing with
        `ERR_INVALID_STATE` (HTTP 409); an entity that has already reached a terminal
        state rejects further transitions with `ERR_ALREADY_TERMINAL` (HTTP 409)."

        A second cancel on the terminal CANCELLED project is rejected with a 409
        conflict.

        Design: Corner/state_machines/cancel_booking_from_already_cancelled_returns_invalid_state
        """
        set_logical_clock()
        profile = make_platform_profile()
        client = make_client()
        project = make_project(client["id"], profile["id"], upc=None)
        validate_success(api.cancel_project(
            project["id"], make_client_headers(client["id"])), 200)
        res = api.cancel_project(project["id"], make_client_headers(client["id"]))
        assert res.status_code == 409
        validate_error_is_one_of(res, [
            ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_ALREADY_TERMINAL])

    def test_new_project_starts_in_draft(self, api):
        """PRD §3.3: "A new project starts in `DRAFT` with `revision_round_count` at
        zero."

        Design: Corner/state_machines/initial_state_project_is_draft
        """
        set_logical_clock()
        profile = make_platform_profile()
        client = make_client()
        project = validate_success(api.create_project(
            create_project_payload(client["id"], profile["id"], rush_tier="STANDARD"),
            make_client_headers(client["id"])), 201)
        assert project["status"] == "DRAFT"
        assert project["revision_round_count"] == 0
        assert project.get("current_revision_round_id") in (None,), (
            "no revision round exists before mastering starts")
