"""Visa petitions: filing gates, the RFE negotiation cycle with its hard cap,
link side effects, activation preconditions, and withdrawal cascades."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjudicate_petition,
    create_application,
    create_grower,
    create_petition,
    create_petitioning_order,
    create_recruiting_order,
    create_wage_determination,
    create_worker,
    file_petition,
    get_success_data,
    issue_findings,
    link_worker,
    set_clock,
    submit_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
REVIEWER = TEST_USERS["program_reviewer_headers"]


class TestPetitionFilingGate:
    def _recruiting_order_with_draft_petition(self, api):
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_recruiting_order(grower["id"], wd["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=2)
        return jo, petition

    def test_petition_file_requires_order_petitioning(self, api):
        """PRD 3.4: "Filing the petition moves it from `DRAFT` to `FILED` and
        stamps `filed_on` with the clock date. Filing requires the parent order to
        have reached `PETITIONING` (else `ERR_JOB_ORDER_INVALID_STATE`) and
        requires `requested_worker_count` to fit within the order's
        `visa_worker_ceiling` — the count fixed by domestic hiring when recruitment
        closed — else the filing is rejected with
        `ERR_PETITION_EXCEEDS_VISA_CEILING`."

        Design: Difficulty/cross_entity_state_dependency/petition_file_requires_order_petitioning
        """
        _, petition = self._recruiting_order_with_draft_petition(api)

        resp = api.file_visa_petition(petition["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_JOB_ORDER_INVALID_STATE)

    def test_petition_file_rejection_leaves_draft_unchanged(self, api):
        """PRD 3.4: "A new petition starts in `DRAFT` with `rfe_count` at 0 and
        both `filed_on` and `approved_worker_count` null."

        Design: Difficulty/cross_entity_state_dependency/petition_file_requires_order_petitioning
        """
        _, petition = self._recruiting_order_with_draft_petition(api)
        validate_error(api.file_visa_petition(petition["id"], ADMIN), ApiErrorId.ERR_JOB_ORDER_INVALID_STATE)

        current = get_success_data(api.get_visa_petition(petition["id"], ADMIN))
        assert current["status"] == "DRAFT"
        assert current["filed_on"] is None


class TestRfeCycleHardLimit:
    def _filed_petition_two_workers(self, api):
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_petitioning_order(grower["id"], wd["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=2)
        wa = create_worker(passport_number="P0001", full_name="Worker A")
        wb = create_worker(passport_number="P0002", full_name="Worker B")
        link_worker(petition["id"], wa["id"])
        link_worker(petition["id"], wb["id"])
        file_petition(petition["id"])
        return jo, petition, wa, wb

    def test_third_rfe_rejected_after_two_cycles(self, api):
        """PRD 3.4: "A `ProgramReviewer` may issue a Request for Evidence on a
        `FILED` petition, moving it to `RFE` and incrementing `rfe_count` by one;
        at most two RFEs may ever be issued against a petition, so issuing a third
        is rejected with `ERR_RFE_LIMIT_REACHED`, and after two RFEs the petition
        must be adjudicated."
        PRD 3.4: "A `ContractorAdmin` responds to an RFE, moving the petition from
        `RFE` back to `FILED` with `rfe_count` unchanged; both the RFE and its
        response accept an optional `note`."

        Design: Difficulty/non_linear_state_machine/visa_petition_rfe_cycle_with_hard_limit
        """
        _, petition, _, _ = self._filed_petition_two_workers(api)

        for expected_count in (1, 2):
            rfe = validate_success(api.issue_rfe(petition["id"], {}, REVIEWER), 200)
            assert rfe["status"] == "RFE" and rfe["rfe_count"] == expected_count
            back = validate_success(api.respond_rfe(petition["id"], {}, ADMIN), 200)
            assert back["status"] == "FILED" and back["rfe_count"] == expected_count

        resp = api.issue_rfe(petition["id"], {}, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_RFE_LIMIT_REACHED)

    def test_petition_exits_cycle_via_adjudication(self, api):
        """PRD 3.4: "at most two RFEs may ever be issued against a petition, so
        issuing a third is rejected with `ERR_RFE_LIMIT_REACHED`, and after two
        RFEs the petition must be adjudicated."
        PRD 3.4: "Approval moves the petition to `APPROVED` and records
        `approved_worker_count`."

        Design: Difficulty/non_linear_state_machine/visa_petition_rfe_cycle_with_hard_limit
        """
        _, petition, _, _ = self._filed_petition_two_workers(api)
        for _ in range(2):
            validate_success(api.issue_rfe(petition["id"], {}, REVIEWER), 200)
            validate_success(api.respond_rfe(petition["id"], {}, ADMIN), 200)

        approved = adjudicate_petition(petition["id"], "APPROVE", approved_worker_count=2)
        assert approved["status"] == "APPROVED"
        assert approved["rfe_count"] == 2
        assert approved["approved_worker_count"] == 2


class TestPetitionGuards:
    def test_petition_guards_respond_overflow_mismatch_rejected(self, api):
        """PRD 3.4: "Responding from any status other than `RFE` is rejected with
        `ERR_PETITION_INVALID_STATE`."
        PRD 3.4: "The number of linked workers may never exceed the petition's
        `requested_worker_count`; a link that would overflow it is rejected with
        `ERR_PETITION_WORKER_OVERFLOW`."
        PRD 3.4: "Approval additionally requires an `approved_worker_count` input
        that must equal the number of workers currently linked to the petition — a
        mismatch is rejected with `ERR_APPROVED_COUNT_MISMATCH` — and must be at
        least 1 and no more than `requested_worker_count` (else
        `ERR_INVALID_REQUEST`)."

        Design: Corner/errors/petition_guards_respond_overflow_mismatch_rejected
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_petitioning_order(grower["id"], wd["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)
        wa = create_worker(passport_number="P0001", full_name="Worker A")
        wb = create_worker(passport_number="P0002", full_name="Worker B")
        link_worker(petition["id"], wa["id"])
        file_petition(petition["id"])

        # respond-rfe requires RFE; the petition is FILED.
        resp = api.respond_rfe(petition["id"], {}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PETITION_INVALID_STATE)

        # Linking a second worker would overflow requested_worker_count == 1.
        resp = api.link_worker(petition["id"], {"worker_id": wb["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PETITION_WORKER_OVERFLOW)
        assert get_success_data(api.get_worker(wb["id"], ADMIN))["status"] == "REGISTERED"

        # Approval count must equal the linked count (1), not 2.
        resp = api.adjudicate_petition(petition["id"], {"decision": "APPROVE", "approved_worker_count": 2}, REVIEWER)
        validate_error(resp, ApiErrorId.ERR_APPROVED_COUNT_MISMATCH)

        ok = validate_success(
            api.adjudicate_petition(petition["id"], {"decision": "APPROVE", "approved_worker_count": 1}, REVIEWER),
            200,
        )
        assert ok["status"] == "APPROVED"

    def test_link_worker_side_effects_visible(self, api):
        """PRD 3.4: "Linking moves the worker to `PETITIONED` and sets the worker's
        `petition_id` to the petition."

        Design: Corner/state_machines/link_worker_side_effects_visible
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_recruiting_order(grower["id"], wd["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)
        wa = create_worker(passport_number="P0001", full_name="Worker A")

        validate_success(api.link_worker(petition["id"], {"worker_id": wa["id"]}, ADMIN), 200)

        worker = get_success_data(api.get_worker(wa["id"], ADMIN))
        assert worker["status"] == "PETITIONED"
        assert worker["petition_id"] == petition["id"]


class TestActivationAndWithdrawal:
    def test_activate_without_approved_petition_rejected(self, api):
        """PRD 3.4: "Once at least one petition for the order is `APPROVED` (else
        `ERR_NO_APPROVED_PETITION`) and the clock date has reached
        `work_start_date` (else `ERR_ORDER_NOT_YET_STARTED`), a `ContractorAdmin`
        activates the order, moving it from `PETITIONING` to `ACTIVE`."

        Design: Corner/state_machines/activate_without_approved_petition_rejected
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_petitioning_order(grower["id"], wd["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)
        file_petition(petition["id"])
        set_clock("2026-09-01T00:00:00Z")

        resp = api.activate_job_order(jo["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_PETITION)
        assert get_success_data(api.get_job_order(jo["id"], ADMIN))["status"] == "PETITIONING"

    def test_withdraw_with_filed_petition_rejected(self, api):
        """PRD 3.2: "Withdrawal is blocked whenever the order has a petition in
        `FILED`, `RFE`, or `APPROVED` — rejected with `ERR_OPEN_PETITIONS_EXIST` —
        and this guard is precisely what blocks withdrawal once petitioning is
        genuinely underway."

        Design: Corner/state_machines/withdraw_with_filed_petition_rejected
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_petitioning_order(grower["id"], wd["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)
        file_petition(petition["id"])

        resp = api.withdraw_job_order(jo["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_OPEN_PETITIONS_EXIST)
        assert get_success_data(api.get_job_order(jo["id"], ADMIN))["status"] == "PETITIONING"
        assert get_success_data(api.get_visa_petition(petition["id"], ADMIN))["status"] == "FILED"

    def test_withdraw_cascades_draft_petition_and_application(self, api):
        """PRD 3.2: "A successful withdrawal moves the order to `WITHDRAWN` and
        cascades: every petition of the order still in `DRAFT` moves to
        `WITHDRAWN`, each worker linked to such a petition in `PETITIONED` status
        reverts to `REGISTERED` with its `petition_id` cleared to null, and every
        domestic application still in `APPLIED` moves to `WITHDRAWN`."

        Design: Corner/state_machines/withdraw_cascades_draft_petition_and_application
        """
        grower = create_grower()
        wd = create_wage_determination()
        jo = create_recruiting_order(grower["id"], wd["id"])
        app = create_application(jo["id"])
        petition = create_petition(jo["id"], receipt_code="RCPT-1", requested_worker_count=1)
        wa = create_worker(passport_number="P0001")
        link_worker(petition["id"], wa["id"])

        withdrawn = validate_success(api.withdraw_job_order(jo["id"], ADMIN), 200)
        assert withdrawn["status"] == "WITHDRAWN"

        petitions, _ = validate_paginated(api.list_visa_petitions(jo["id"], ADMIN))
        assert petitions[0]["id"] == petition["id"] and petitions[0]["status"] == "WITHDRAWN"

        worker = get_success_data(api.get_worker(wa["id"], ADMIN))
        assert worker["status"] == "REGISTERED"
        assert worker["petition_id"] is None

        apps, _ = validate_paginated(api.list_domestic_applications(jo["id"], ADMIN))
        assert apps[0]["id"] == app["id"] and apps[0]["status"] == "WITHDRAWN"
