"""COD extensions, commercial-operation declaration, and cluster closure."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_instant_equal,
    create_extension_payload,
    declare_commercial_operation,
    get_cluster_group,
    get_project,
    make_developer_headers,
    set_clock,
    setup_project_agreement_executed,
    setup_project_agreement_pending,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["queue_admin_headers"]


class TestExtensionConstraints:
    def test_extension_limit_and_date_range_enforced(self, api):
        """PRD §3.6: "Three constraints guard it: the agreement must be `EXECUTED`
        (otherwise `ERR_AGREEMENT_NOT_EXECUTED`); `extension_count` must still be
        below the maximum of two, or the request fails with
        `ERR_EXTENSION_LIMIT_REACHED`; and the request must arrive at least thirty
        days before the current `target_cod` — a request inside that window is
        rejected with `ERR_EXTENSION_WINDOW_MISSED`. The `new_target_cod` itself
        must be strictly after the current `target_cod` and no more than 365 days
        beyond it; anything outside that range is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/extension_limit_and_date_range_enforced
        """
        scenario = setup_project_agreement_executed(target_cod="2027-06-01T00:00:00Z")
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        headers = make_developer_headers(developer["id"])

        # 2027-06-01 + 365 days = 2028-05-31; 2028-07-06 is beyond the range.
        resp = api.request_extension(
            agreement["id"], create_extension_payload("2028-07-06T00:00:00Z"), headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        resp = api.request_extension(
            agreement["id"], create_extension_payload("2027-12-01T00:00:00Z"), headers)
        data = validate_success(resp, expected_status=201)
        assert_instant_equal(data["target_cod"], "2027-12-01T00:00:00Z")
        assert data["extension_count"] == 1, "the out-of-range attempt consumed no quota"

        resp = api.request_extension(
            agreement["id"], create_extension_payload("2028-03-01T00:00:00Z"), headers)
        data = validate_success(resp, expected_status=201)
        assert_instant_equal(data["target_cod"], "2028-03-01T00:00:00Z")
        assert data["extension_count"] == 2

        resp = api.request_extension(
            agreement["id"], create_extension_payload("2028-06-01T00:00:00Z"), headers)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_LIMIT_REACHED)

    def test_extension_window_boundary_exact_then_missed(self, api):
        """PRD §3.6: "the request must arrive at least thirty days before the
        current `target_cod` — a request inside that window is rejected with
        `ERR_EXTENSION_WINDOW_MISSED`."

        Design: Corner/validations/extension_window_boundary_exact_then_missed
        """
        scenario = setup_project_agreement_executed(target_cod="2027-06-01T00:00:00Z")
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        headers = make_developer_headers(developer["id"])

        # Exactly thirty days before the current target_cod: 2027-05-02.
        set_clock("2027-05-02T00:00:00Z")
        resp = api.request_extension(
            agreement["id"], create_extension_payload("2027-12-01T00:00:00Z"), headers)
        data = validate_success(resp, expected_status=201)
        assert data["extension_count"] == 1, (
            "the thirty-day notice window is inclusive at its boundary"
        )

        # New current target is 2027-12-01; 2027-11-15 is inside
        # target_cod - 30 days = 2027-11-01.
        set_clock("2027-11-15T00:00:00Z")
        resp = api.request_extension(
            agreement["id"], create_extension_payload("2028-06-01T00:00:00Z"), headers)
        validate_error(resp, ApiErrorId.ERR_EXTENSION_WINDOW_MISSED)

    def test_extension_requires_executed_agreement(self, api):
        """PRD §3.6: "the agreement must be `EXECUTED` (otherwise
        `ERR_AGREEMENT_NOT_EXECUTED`)"

        Design: Corner/validations/extension_requires_executed_agreement
        """
        scenario = setup_project_agreement_pending(finalize=False)
        agreement = scenario["agreement"]
        developer = scenario["developer"]
        assert agreement["status"] == "ISSUED"

        resp = api.request_extension(
            agreement["id"], create_extension_payload("2027-12-01T00:00:00Z"),
            make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_EXECUTED)


class TestCommercialOperation:
    def test_cod_deadline_passed_rejected(self, api):
        """PRD §3.8: "The declaration requires the project to be
        `AGREEMENT_EXECUTED` (otherwise `ERR_PROJECT_NOT_READY_FOR_OPERATION`) and
        requires the clock to be no later than the `target_cod` as extended by any
        granted extensions — a declaration after that date is rejected with
        `ERR_COD_DEADLINE_PASSED`."

        Design: Corner/validations/cod_deadline_passed_rejected
        """
        scenario = setup_project_agreement_executed(target_cod="2027-06-01T00:00:00Z")
        project = scenario["project"]
        developer = scenario["developer"]

        set_clock("2027-06-02T00:00:00Z")
        resp = api.declare_commercial_operation(
            project["id"], make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_COD_DEADLINE_PASSED)
        assert get_project(project["id"])["status"] == "AGREEMENT_EXECUTED"

    def test_declare_commercial_operation_wrong_state_rejected(self, api):
        """PRD §3.8: "The declaration requires the project to be
        `AGREEMENT_EXECUTED` (otherwise `ERR_PROJECT_NOT_READY_FOR_OPERATION`)"

        Design: Corner/validations/declare_commercial_operation_wrong_state_rejected
        """
        scenario = setup_project_agreement_pending(finalize=True)
        project = scenario["project"]
        developer = scenario["developer"]
        assert project["status"] == "AGREEMENT_PENDING"

        resp = api.declare_commercial_operation(
            project["id"], make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_READY_FOR_OPERATION)

    def test_declare_cod_moves_project_to_commercial_operation(self, api):
        """PRD §3.8: "Success moves the project to the terminal
        `COMMERCIAL_OPERATION` state and bubbles upward"

        Design: Difficulty/transitive_cascade/commercial_operation_closes_cluster
        """
        scenario = setup_project_agreement_executed(target_cod="2027-06-01T00:00:00Z")
        project = scenario["project"]
        developer = scenario["developer"]

        resp = api.declare_commercial_operation(
            project["id"], make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "COMMERCIAL_OPERATION"

    def test_declare_cod_closes_cluster_when_all_members_terminal(self, api):
        """PRD §3.8: "Success moves the project to the terminal
        `COMMERCIAL_OPERATION` state and bubbles upward: if the cluster is
        `STUDY_COMPLETE` and, counting this declaration, every member project now
        sits in a terminal state — `WITHDRAWN` or `COMMERCIAL_OPERATION` — the
        cluster closes, moving from `STUDY_COMPLETE` to `CLOSED`."

        Design: Difficulty/transitive_cascade/commercial_operation_closes_cluster
        """
        scenario = setup_project_agreement_executed(target_cod="2027-06-01T00:00:00Z")
        project = scenario["project"]
        developer = scenario["developer"]
        cluster = scenario["cluster"]
        assert get_cluster_group(cluster["id"])["status"] == "STUDY_COMPLETE"

        declare_commercial_operation(project["id"], developer["id"])

        assert get_project(project["id"])["status"] == "COMMERCIAL_OPERATION"
        assert get_cluster_group(cluster["id"])["status"] == "CLOSED", (
            "single-member cluster: the terminal declaration closes it"
        )

    def test_withdraw_from_commercial_operation_rejected(self, api):
        """PRD §3.7: "Withdrawal from `COMMERCIAL_OPERATION` or from `WITHDRAWN`
        itself is not permitted; the attempt is rejected with
        `ERR_PROJECT_NOT_WITHDRAWABLE` (HTTP 409)."

        Design: Corner/state_machines/withdraw_from_commercial_operation_rejected
        """
        scenario = setup_project_agreement_executed(target_cod="2027-06-01T00:00:00Z")
        project = scenario["project"]
        developer = scenario["developer"]
        declare_commercial_operation(project["id"], developer["id"])

        resp = api.withdraw_project(project["id"],
                                    make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_WITHDRAWABLE)

        after = get_project(project["id"])
        assert after["status"] == "COMMERCIAL_OPERATION"
        assert after["deposit_posted_cents"] == 1000000, "no forfeiture ran"
