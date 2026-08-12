"""ISP lifecycle: amendment cycle, terminal lockdown, OCC, supersede.

PRD 2.5 (OCC) and 3.3 (ISP workflow).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_isp,
    create_authorization_payload,
    create_isp_draft,
    create_isp_payload,
    get_success_data,
    make_case_manager_headers,
    make_qidp_headers,
    set_clock,
    setup_agency_with_core_staff,
    setup_enrolled_individual,
    api_client,
    validate_error,
    validate_success,
)

ANY = TEST_USERS["any_headers"]


def _setup_enrolled_with_clock(clock_iso="2026-06-01T00:00:00Z"):
    base = setup_agency_with_core_staff()
    ind = setup_enrolled_individual(base["agency"], base["cm"], base["q"])
    set_clock(clock_iso)
    return base, ind


class TestIspAmendmentCycle:
    """Cyclic ISP machine: ACTIVE -> AMENDMENT_DRAFT -> ... -> ACTIVE."""

    def test_amend_moves_active_plan_to_amendment_draft(self, api):
        """PRD 3.3: "Amending an `ACTIVE` plan transitions it to
        `AMENDMENT_DRAFT`".

        Design: Difficulty/non_linear_state_machine/isp_amendment_cycle_returns_to_active
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_active_isp(ind, base["cm"], base["q"])
        amended = get_success_data(api_client.amend_isp(
            isp["id"],
            {"expected_isp_version": isp["version"],
             "goals_summary": "Amended: add employment goal"},
            make_case_manager_headers(base["cm"]["id"]),
        ))
        assert amended["status"] == "AMENDMENT_DRAFT"
        assert amended["amendment_count"] == 1

    def test_full_amendment_loop_returns_to_active_with_count_one(self, api):
        """PRD 3.3: "The amendment is then submitted for review, approved, and
        activated through the same path as a fresh plan." And "In both cases
        `amendment_count` increments by 1 and `version` increments by 1."

        Design: Difficulty/non_linear_state_machine/isp_amendment_cycle_returns_to_active
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_active_isp(ind, base["cm"], base["q"])
        v_active = isp["version"]
        amended = get_success_data(api_client.amend_isp(
            isp["id"],
            {"expected_isp_version": v_active,
             "goals_summary": "Amended: add employment goal"},
            make_case_manager_headers(base["cm"]["id"]),
        ))
        submitted = get_success_data(api_client.submit_isp_review(
            amended["id"], make_case_manager_headers(base["cm"]["id"]),
        ))
        assert submitted["status"] == "PENDING_REVIEW"
        approved = get_success_data(api_client.approve_isp(
            submitted["id"], make_qidp_headers(base["q"]["id"]),
        ))
        activated = get_success_data(api_client.activate_isp(
            approved["id"], make_qidp_headers(base["q"]["id"]),
        ))
        assert activated["status"] == "ACTIVE"
        assert activated["amendment_count"] == 1
        # create(1) + submit(2) + approve(3) + activate(4) + amend(5) + submit(6)
        # + approve(7) + activate(8).
        assert activated["version"] == v_active + 4


class TestIspInitialStateAndReturnLoop:
    """ISP DRAFT initial state and PENDING_REVIEW -> DRAFT revert (PRD 3.3)."""

    def test_new_isp_starts_draft_with_zero_amendments(self, api):
        """PRD 3.3: "A newly created ISP starts in `DRAFT` status with
        `amendment_count` equal to zero."

        Design: Corner/state_machines/isp_initial_state_and_return_loop
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_isp_draft(ind, base["cm"])
        assert isp["status"] == "DRAFT"
        assert isp["amendment_count"] == 0

    def test_return_reverts_to_draft_and_resubmit_reenters_review(self, api):
        """PRD 3.3: "From `PENDING_REVIEW`, a `QIDP` may either return the plan
        to `DRAFT` for revision (optionally carrying a `return_reason`) or
        approve it."

        Design: Corner/state_machines/isp_initial_state_and_return_loop
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_isp_draft(ind, base["cm"])
        submitted = get_success_data(api_client.submit_isp_review(
            isp["id"], make_case_manager_headers(base["cm"]["id"]),
        ))
        assert submitted["status"] == "PENDING_REVIEW"
        returned = get_success_data(api_client.return_isp(
            isp["id"], make_qidp_headers(base["q"]["id"]),
            payload={"return_reason": "Goals need measurable outcomes"},
        ))
        assert returned["status"] == "DRAFT"
        resubmitted = get_success_data(api_client.submit_isp_review(
            isp["id"], make_case_manager_headers(base["cm"]["id"]),
        ))
        assert resubmitted["status"] == "PENDING_REVIEW"


class TestIspApproveFromDraftRejected:
    """approve is declared only from PENDING_REVIEW (PRD 3.3)."""

    def test_approve_on_draft_fails_invalid_state(self, api):
        """PRD 3.3: "From `PENDING_REVIEW`, a `QIDP` may either return the plan
        to `DRAFT` for revision (optionally carrying a `return_reason`) or
        approve it." A DRAFT ISP permits neither approve nor activate.

        Design: Corner/state_machines/isp_approve_from_draft_rejected
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_isp_draft(ind, base["cm"])
        resp = api_client.approve_isp(isp["id"], make_qidp_headers(base["q"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_approve_leaves_no_side_effects(self, api):
        """PRD 3.3: "On successful approval the system writes
        `approved_by_staff_id` from the caller's `X-User-ID` and transitions the
        plan to `APPROVED`." A rejected approval performs neither mutation.

        Design: Corner/state_machines/isp_approve_from_draft_rejected
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_isp_draft(ind, base["cm"])
        validate_error(
            api_client.approve_isp(isp["id"], make_qidp_headers(base["q"]["id"])),
            ApiErrorId.ERR_INVALID_STATE,
        )
        after = get_success_data(api_client.get_isp(isp["id"], ANY))
        assert after["status"] == "DRAFT"
        assert after["version"] == isp["version"]


class TestIspTerminalExpiredLockdown:
    """EXPIRED is terminal: all further actions rejected (PRD 3.3)."""

    def _setup_expired_isp(self, api):
        base, ind = _setup_enrolled_with_clock()
        isp = create_active_isp(
            ind, base["cm"], base["q"], plan_year_end="2026-06-30",
        )
        set_clock("2026-07-01T00:00:00Z")
        expired = get_success_data(api_client.get_isp(isp["id"], ANY))
        return base, expired

    def test_clock_past_plan_year_end_expires_active_isp(self, api):
        """PRD 3.3: "when the logical clock advances past `plan_year_end`, an
        `ACTIVE` ISP transitions automatically to `EXPIRED`."

        Design: Corner/state_machines/isp_terminal_expired_lockdown
        """
        _base, expired = self._setup_expired_isp(api)
        assert expired["status"] == "EXPIRED"

    def test_submit_review_and_amend_on_expired_rejected(self, api):
        """PRD 3.3: submit-review applies to plans "From `DRAFT` (or from
        `AMENDMENT_DRAFT`)" and amending applies to `ACTIVE` / `AMENDMENT_DRAFT`
        plans; an EXPIRED plan is in neither state.

        Design: Corner/state_machines/isp_terminal_expired_lockdown
        """
        base, expired = self._setup_expired_isp(api)
        resp1 = api_client.submit_isp_review(
            expired["id"], make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api_client.amend_isp(
            expired["id"],
            {"expected_isp_version": expired["version"],
             "goals_summary": "Attempted amendment of expired plan"},
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestIspCreateStaleIndividualOcc:
    """OCC guard on POST /isps (PRD 2.5)."""

    def _setup_first_draft_created(self, api):
        base, ind = _setup_enrolled_with_clock()
        stale_version = ind["version"]  # captured before first create
        isp1 = create_isp_draft(ind, base["cm"])
        fresh = get_success_data(api_client.get_individual(ind["id"], ANY))
        return base, ind, stale_version, fresh["version"], isp1

    def test_stale_individual_version_rejected_412(self, api):
        """PRD 2.5: "If the `Individual` resource's current `version` does not
        match `expected_individual_version` at the moment of the write, the
        request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/isp_create_with_stale_individual_version_rejected
        """
        base, ind, stale_v, _fresh_v, _isp1 = self._setup_first_draft_created(api)
        resp = api_client.create_isp(
            create_isp_payload(
                ind["id"], stale_v,
                plan_year_start="2026-06-01", plan_year_end="2027-05-31",
                goals_summary="Rival draft plan from stale client",
            ),
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_fresh_version_create_supersedes_prior_draft(self, api):
        """PRD 3.3: "If another ISP for the same individual already exists in
        `DRAFT` state, the existing DRAFT is immediately transitioned to
        `SUPERSEDED` (a system-side transition) when the new draft is created".

        Design: Corner/cross_cutting_layers/isp_create_with_stale_individual_version_rejected
        """
        base, ind, _stale_v, fresh_v, isp1 = self._setup_first_draft_created(api)
        isp2 = get_success_data(api_client.create_isp(
            create_isp_payload(
                ind["id"], fresh_v,
                plan_year_start="2026-06-01", plan_year_end="2027-05-31",
                goals_summary="Rival draft plan from fresh client",
            ),
            make_case_manager_headers(base["cm"]["id"]),
        ))
        assert isp2["status"] == "DRAFT"
        isp1_after = get_success_data(api_client.get_isp(isp1["id"], ANY))
        assert isp1_after["status"] == "SUPERSEDED"


class TestIspAmendStaleVersionOcc:
    """OCC guard on POST /isps/{id}/amend (PRD 2.5)."""

    def test_stale_isp_version_amend_rejected_412(self, api):
        """PRD 2.5: "If the `ISP` resource's current `version` does not match
        `expected_isp_version` at the moment of the write, the request is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/isp_amend_with_stale_version_rejected
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_active_isp(ind, base["cm"], base["q"])
        stale_v = isp["version"] - 1  # pre-activation version
        resp = api_client.amend_isp(
            isp["id"],
            {"expected_isp_version": stale_v, "goals_summary": "Stale amendment attempt"},
            make_case_manager_headers(base["cm"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_fresh_version_amend_succeeds_and_increments_count(self, api):
        """PRD 3.3: "Amending an `ACTIVE` plan transitions it to
        `AMENDMENT_DRAFT`; amending an `AMENDMENT_DRAFT` plan leaves it in
        `AMENDMENT_DRAFT` and supersedes the in-flight amendment content. In
        both cases `amendment_count` increments by 1 and `version` increments
        by 1."

        Design: Corner/cross_cutting_layers/isp_amend_with_stale_version_rejected
        """
        base, ind = _setup_enrolled_with_clock()
        isp = create_active_isp(ind, base["cm"], base["q"])
        amended = get_success_data(api_client.amend_isp(
            isp["id"],
            {"expected_isp_version": isp["version"],
             "goals_summary": "Fresh amendment attempt"},
            make_case_manager_headers(base["cm"]["id"]),
        ))
        assert amended["status"] == "AMENDMENT_DRAFT"
        assert amended["amendment_count"] == 1
        assert amended["version"] == isp["version"] + 1
