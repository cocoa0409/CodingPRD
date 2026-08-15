"""Applications: priority windows, continuation chains, duplicate numbers,
state machine basics, suspended-client gate, initial defaults (PRD §3.1-§3.2)."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    NON_EXISTENT_UUID,
    create_us_rule,
    create_client,
    create_family,
    create_application,
    create_pending_application,
    create_application_payload,
)

ANY = TEST_USERS["any_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["clerk_headers"]
MGR = TEST_USERS["manager_headers"]


class TestParisWindowBoundary:
    def test_filing_on_last_window_day_allowed(self):
        """PRD §3.2: "Filing is permitted when the `filing_date` falls on or
        before that deadline — the boundary day itself is allowed — and a later
        filing date is rejected with `ERR_PRIORITY_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/paris_window_last_day_filing_allowed
        """
        create_us_rule()
        client = create_client("WinCo")
        family = create_family(client["id"], first_priority_date="2026-01-15")
        # Paris window 12 months: deadline 2027-01-15.
        data = validate_success(api_client.create_application(
            family["id"],
            create_application_payload(application_type="PARIS_CONVENTION",
                                       filing_date="2027-01-15",
                                       application_number="US-W1"),
            CLERK), 201)
        assert data["status"] == "DRAFT"

    def test_filing_one_day_past_window_rejected(self):
        """PRD §3.2: "a later filing date is rejected with
        `ERR_PRIORITY_WINDOW_EXPIRED`."

        Design: Difficulty/boundary_precision_check/paris_window_last_day_filing_allowed
        """
        create_us_rule()
        client = create_client("WinCo")
        family = create_family(client["id"], first_priority_date="2026-01-15")
        validate_error(api_client.create_application(
            family["id"],
            create_application_payload(application_type="PARIS_CONVENTION",
                                       filing_date="2027-01-16",
                                       application_number="US-W2"),
            CLERK), ApiErrorId.ERR_PRIORITY_WINDOW_EXPIRED)


class TestExistenceBeatsTemporal:
    def test_missing_parent_and_expired_window_reports_not_found(self):
        """PRD §2.9: "4. **Existence.** Path identifiers are validated left to
        right, and the request is rejected with `ERR_NOT_FOUND` for the first
        identifier that does not resolve; only then are body-supplied
        references — `parent_application_id`, `counsel_firm_id`,
        `docket_entry_id`, and each element of `inventor_ids` — resolved, each
        failure also producing `ERR_NOT_FOUND`" — evaluated before the business
        rules ("Only after all eight universal layers pass are business rules
        evaluated").

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_temporal_on_pct_national_phase_create
        """
        create_us_rule()
        client = create_client("ExCo")
        family = create_family(client["id"], first_priority_date="2026-01-15")
        # PCT deadline: 2026-01-15 + 30 months = 2028-07-15; filing 2028-08-01 is late.
        resp = api_client.create_application(
            family["id"],
            create_application_payload(application_type="PCT_NATIONAL_PHASE",
                                       filing_date="2028-08-01",
                                       application_number="US-NP",
                                       parent_application_id=NON_EXISTENT_UUID),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_missing_parent_reports_not_found_even_within_window(self):
        """PRD §3.2: "Every link must resolve to an existing application
        (`ERR_NOT_FOUND` otherwise); the proposed parent must not be in
        `LAPSED` status (`ERR_PARENT_APPLICATION_LAPSED`)"

        Design: Difficulty/priority_pair_validation_conflict/existence_vs_temporal_on_pct_national_phase_create
        """
        create_us_rule()
        client = create_client("ExCo")
        family = create_family(client["id"], first_priority_date="2026-01-15")
        # In-window filing (deadline 2028-07-15) with a non-existent parent:
        # only existence can fire.
        resp = api_client.create_application(
            family["id"],
            create_application_payload(application_type="PCT_NATIONAL_PHASE",
                                       filing_date="2028-07-15",
                                       application_number="US-NP",
                                       parent_application_id=NON_EXISTENT_UUID),
            CLERK)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestContinuationChains:
    def _chain_world(self):
        create_us_rule()
        client1 = create_client("ChainCo1")
        client2 = create_client("ChainCo2")
        fam1 = create_family(client1["id"], title="F1")
        fam2 = create_family(client2["id"], title="F2")
        p1 = create_pending_application(fam1["id"], application_number="US-P1")
        p2 = create_application(fam2["id"], application_number="US-P2")
        return fam1, fam2, p1, p2

    def test_valid_continuation_accepted_and_listed_under_parent(self):
        """PRD §3.2: "The `parent_application_id` field identifies the parent
        application for `CONTINUATION`, `DIVISIONAL`, and `PCT_NATIONAL_PHASE`
        filings"; "Applications are listed per family — optionally
        filtered by `status` — or across the portfolio filtered by
        `family_id`, `parent_application_id`, or `status`."

        Design: Corner/entities/self_referential_continuation_chain_rules
        """
        fam1, _, p1, _ = self._chain_world()
        child = validate_success(api_client.create_application(
            fam1["id"],
            create_application_payload(application_type="CONTINUATION",
                                       filing_date="2026-06-01",
                                       application_number="US-C1",
                                       parent_application_id=p1["id"]),
            CLERK), 201)
        children = validate_success(
            api_client.list_applications(ANY, params={"parent_application_id": p1["id"]}), 200)
        assert isinstance(children, list) and children[0]["id"] == child["id"]

    def test_cross_family_parent_rejected(self):
        """PRD §3.2: "the proposed parent must belong to the same patent family
        as the child (`ERR_PARENT_FAMILY_MISMATCH`); the chain must remain
        acyclic"

        Design: Corner/entities/self_referential_continuation_chain_rules
        """
        fam1, _, _, p2 = self._chain_world()
        validate_error(api_client.create_application(
            fam1["id"],
            create_application_payload(application_type="CONTINUATION",
                                       filing_date="2026-06-01",
                                       application_number="US-C2",
                                       parent_application_id=p2["id"]),
            CLERK), ApiErrorId.ERR_PARENT_FAMILY_MISMATCH)

    def test_pct_national_phase_requires_pct_international_parent(self):
        """PRD §3.2: "a `PCT_NATIONAL_PHASE` filing requires the proposed
        parent's `application_type` to be `PCT_INTERNATIONAL`
        (`ERR_PARENT_NOT_PCT`)."

        Design: Corner/entities/self_referential_continuation_chain_rules
        """
        fam1, _, p1, _ = self._chain_world()
        validate_error(api_client.create_application(
            fam1["id"],
            create_application_payload(application_type="PCT_NATIONAL_PHASE",
                                       filing_date="2026-06-01",
                                       application_number="US-NP1",
                                       parent_application_id=p1["id"]),
            CLERK), ApiErrorId.ERR_PARENT_NOT_PCT)


class TestParentApplicationLapsed:
    def test_continuation_under_lapsed_parent_rejected(self):
        """PRD §3.2: "the proposed parent must not be in `LAPSED` status
        (`ERR_PARENT_APPLICATION_LAPSED`); the proposed parent must belong to
        the same patent family as the child (`ERR_PARENT_FAMILY_MISMATCH`)"

        Design: Corner/errors/error_parent_application_lapsed_on_continuation
        """
        create_us_rule()
        client = create_client("LapCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        p1 = create_pending_application(family["id"], application_number="US-L1")
        validate_success(api_client.grant_application(p1["id"], {"grant_date": "2026-03-01"}, CLERK), 200)
        validate_success(api_client.record_lapse_application(p1["id"], CLERK), 200)
        validate_error(api_client.create_application(
            family["id"],
            create_application_payload(application_type="CONTINUATION",
                                       filing_date="2026-06-01",
                                       application_number="US-L2",
                                       parent_application_id=p1["id"]),
            CLERK), ApiErrorId.ERR_PARENT_APPLICATION_LAPSED)


class TestPriorityChainCycle:
    def test_reparent_under_own_child_is_cycle(self):
        """PRD §3.2: "the chain must remain acyclic — if following parent links
        from the proposed parent would arrive back at the application being
        created or re-parented, the write is rejected with
        `ERR_PRIORITY_CHAIN_CYCLE`; and a `PCT_NATIONAL_PHASE` filing requires
        the proposed parent's `application_type` to be `PCT_INTERNATIONAL`
        (`ERR_PARENT_NOT_PCT`)."

        Design: Corner/errors/error_priority_chain_cycle_on_reparent
        """
        create_us_rule()
        client = create_client("CycCo2")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app_a = create_application(family["id"], application_number="US-CA")
        app_b = create_application(
            family["id"],
            application_type="CONTINUATION",
            filing_date="2026-03-01",
            application_number="US-CB",
            parent_application_id=app_a["id"])
        validate_error(
            api_client.patch_application(app_a["id"], {"parent_application_id": app_b["id"]}, CLERK),
            ApiErrorId.ERR_PRIORITY_CHAIN_CYCLE)

    def test_reparent_non_draft_rejected_invalid_state(self):
        """PRD §3.2: "Re-parenting is defined only while the application is
        `DRAFT` — any other status fails with `ERR_INVALID_STATE` — and re-runs
        the entire chain check, including cycle detection, against the new
        parent."

        Design: Corner/errors/error_priority_chain_cycle_on_reparent
        """
        create_us_rule()
        client = create_client("CycCo2")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app_a = create_pending_application(family["id"], application_number="US-CA")
        app_b = create_application(family["id"], application_number="US-CB")
        validate_error(
            api_client.patch_application(app_a["id"], {"parent_application_id": app_b["id"]}, CLERK),
            ApiErrorId.ERR_INVALID_STATE)


class TestDuplicateApplicationNumber:
    def _dup_world(self):
        create_us_rule()
        client = create_client("DupCo")
        fam1 = create_family(client["id"], title="F1")
        fam2 = create_family(client["id"], title="F2")
        a1 = create_application(fam1["id"], application_number="US-DUP")
        return fam1, fam2, a1

    def test_duplicate_number_in_same_family_rejected(self):
        """PRD §3.2: "Within a family, `application_number` must be unique among
        the applications that are not `WITHDRAWN`; a number already carried by
        a live sibling — and equally by an abandoned or lapsed one — collides
        and is rejected with `ERR_DUPLICATE_APPLICATION_NUMBER`."

        Design: Corner/validations/duplicate_application_number_per_family
        """
        fam1, _, _ = self._dup_world()
        validate_error(api_client.create_application(
            fam1["id"], create_application_payload(filing_date="2026-02-02",
                                                   application_number="US-DUP",
                                                   entity_size="SMALL"), CLERK),
            ApiErrorId.ERR_DUPLICATE_APPLICATION_NUMBER)

    def test_same_number_in_other_family_and_after_withdrawal_accepted(self):
        """PRD §3.2: "Within a family, `application_number` must be unique among
        the applications that are not `WITHDRAWN`; a number already carried by
        a live sibling — and equally by an abandoned or lapsed one — collides
        and is rejected with `ERR_DUPLICATE_APPLICATION_NUMBER`."

        Design: Corner/validations/duplicate_application_number_per_family
        """
        fam1, fam2, a1 = self._dup_world()
        other = validate_success(api_client.create_application(
            fam2["id"], create_application_payload(filing_date="2026-02-02",
                                                   application_number="US-DUP"), CLERK), 201)
        assert other["application_number"] == "US-DUP"
        validate_success(api_client.withdraw_application(a1["id"], CLERK), 200)
        reused = validate_success(api_client.create_application(
            fam1["id"], create_application_payload(filing_date="2026-02-03",
                                                   application_number="US-DUP"), CLERK), 201)
        assert reused["application_number"] == "US-DUP"


class TestApplicationInvalidTransitions:
    def test_grant_from_draft_rejected(self):
        """PRD §3.2: "Filing moves an application `DRAFT → PENDING`"; PRD §3.4:
        "Granting moves an application `PENDING → GRANTED`"; PRD §2.9: "an
        undefined transition is rejected with `ERR_INVALID_STATE`, and any
        transition attempted on a resource already in a terminal state is
        rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/invalid_transition_application_grant_from_draft
        """
        create_us_rule()
        client = create_client("SMCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_application(family["id"], application_number="US-SM")
        validate_error(api_client.grant_application(app["id"], {"grant_date": "2026-03-01"}, CLERK),
                       ApiErrorId.ERR_INVALID_STATE)

    def test_double_file_rejected(self):
        """PRD §3.2: "Filing moves an application `DRAFT → PENDING`"; PRD §2.9:
        "an undefined transition is
        rejected with `ERR_INVALID_STATE`, and any transition attempted on
        a resource already in a terminal state is rejected with
        `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/invalid_transition_application_grant_from_draft
        """
        create_us_rule()
        client = create_client("SMCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-SM")
        validate_error(api_client.file_application(app["id"], CLERK),
                       ApiErrorId.ERR_INVALID_STATE)


class TestClientSuspendedGate:
    def test_descendant_writes_blocked_while_suspended(self):
        """PRD §3.1: "While a client is `SUSPENDED`, every creation scoped
        beneath it — patent families, applications, docket entries, office
        actions, payment authorizations, outside counsel instructions,
        abandonment reviews, assignment records, and docket audits — is
        rejected with `ERR_CLIENT_SUSPENDED`."

        Design: Corner/validations/client_suspended_gates_descendant_writes
        """
        create_us_rule()
        client = create_client("SuspCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-SU")
        validate_success(api_client.suspend_client(client["id"], ADMIN), 200)
        validate_error(api_client.create_family(
            client["id"], {"title": "SF2", "first_priority_date": "2026-01-15",
                           "budget_cap_cents": 100}, MGR),
            ApiErrorId.ERR_CLIENT_SUSPENDED)
        validate_error(api_client.create_docket_entry(
            app["id"],
            {"entry_type": "RECORDATION", "title": "blocked", "base_due_date": "2026-09-01"},
            CLERK), ApiErrorId.ERR_CLIENT_SUSPENDED)

    def test_writes_resume_after_reactivation(self):
        """PRD §3.1: "Suspension moves a client `ACTIVE → SUSPENDED`, and
        reactivation moves `SUSPENDED → ACTIVE`; both are `PlatformAdmin`
        operations and the client has no terminal state."

        Design: Corner/validations/client_suspended_gates_descendant_writes
        """
        create_us_rule()
        client = create_client("SuspCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_pending_application(family["id"], application_number="US-SU")
        validate_success(api_client.suspend_client(client["id"], ADMIN), 200)
        validate_success(api_client.reactivate_client(client["id"], ADMIN), 200)
        entry = validate_success(api_client.create_docket_entry(
            app["id"],
            {"entry_type": "RECORDATION", "title": "allowed", "base_due_date": "2026-09-01"},
            CLERK), 201)
        assert entry["status"] == "PENDING"


class TestCreationDefaults:
    def test_defaults_and_system_fields(self):
        """PRD §3.1: "the currency defaults to USD"; "A new family's `status` is
        `ACTIVE` and its `committed_forecast_cents` starts at zero." PRD §3.2:
        "A new application's `status` is `DRAFT` and its `open_docket_count`
        starts at zero." PRD §3.3: "A new entry starts `PENDING` with
        `extension_count` at zero, `extension_fees_total_cents` at zero, and
        `current_due_date` equal to its `base_due_date`, and the parent
        application's `open_docket_count` — the count of its entries
        currently `PENDING` or `IN_PROGRESS`, maintained on every entry
        creation, completion, cancellation, and lapse — increases by one."

        Design: Corner/entities/entity_creation_defaults_and_system_fields
        """
        create_us_rule()
        client = validate_success(api_client.create_client({"display_name": "DefaultCo"}, ADMIN), 201)
        assert client["default_currency"] == "USD"
        assert client["status"] == "ACTIVE"
        family = validate_success(api_client.create_family(
            client["id"],
            {"title": "DF", "first_priority_date": "2026-01-15", "budget_cap_cents": 1000000},
            MGR), 201)
        assert family["committed_forecast_cents"] == 0
        assert family["status"] == "ACTIVE"
        app = validate_success(api_client.create_application(
            family["id"], create_application_payload(application_number="US-D"), CLERK), 201)
        assert app["status"] == "DRAFT"
        assert app["open_docket_count"] == 0
        validate_success(api_client.file_application(app["id"], CLERK), 200)
        entry = validate_success(api_client.create_docket_entry(
            app["id"],
            {"entry_type": "STATUTORY", "title": "S1", "base_due_date": "2026-09-01"},
            CLERK), 201)
        assert entry["status"] == "PENDING"
        assert entry["extension_count"] == 0
        assert entry["extension_fees_total_cents"] == 0
        assert entry["current_due_date"] == "2026-09-01"


class TestInitialStates:
    def test_obligation_scheduled_review_proposed_audit_auto_advances(self):
        """PRD §3.4: "each starting in `SCHEDULED` status"; PRD §3.6: "The
        review starts `PROPOSED`"; PRD §3.9: "When the computed list is empty
        the audit stays `OPEN`; otherwise it auto-advances to `VARIANCE_FOUND`
        at creation."

        Design: Corner/state_machines/initial_states_are_as_declared
        """
        from test_helpers import create_granted_application, list_obligations, propose_review
        create_us_rule()
        client = create_client("IniCo")
        family = create_family(client["id"], budget_cap_cents=1000000)
        app = create_granted_application(family["id"], application_number="US-IN")
        assert list_obligations(app["id"])[0]["status"] == "SCHEDULED"
        review = propose_review(app["id"], rationale="check")
        assert review["status"] == "PROPOSED"
        audit_var = validate_success(api_client.create_audit(
            app["id"],
            {"window_start": "2026-08-01", "window_end": "2026-09-01",
             "register_entries": [{"entry_type": "STATUTORY", "due_date": "2026-08-15"}]},
            CLERK), 201)
        assert audit_var["status"] == "VARIANCE_FOUND"
        audit_clean = validate_success(api_client.create_audit(
            app["id"],
            {"window_start": "2026-09-01", "window_end": "2026-10-01", "register_entries": []},
            CLERK), 201)
        assert audit_clean["status"] == "OPEN"
