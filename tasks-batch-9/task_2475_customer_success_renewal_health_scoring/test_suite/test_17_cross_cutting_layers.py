"""Cross-cutting layers: optimistic concurrency and a cumulative quota.

The first two classes drive the two endpoints that carry an `expected_*_version`
field, showing both the 412 refusal and the retry that succeeds once the client
re-reads. The third drives the reference-call quota to its exact threshold.
"""

from typing import Any, Dict

from test_helpers import (
    ADVOCACY_HEADERS,
    ApiClient,
    ApiErrorId,
    ASSIGNMENT_COMMITTED,
    COMMITMENT_ACTION_ACCEPT,
    COMMITMENT_PROPOSED,
    ENROLLMENT_ACTION_ACTIVATE,
    ENROLLMENT_ACTION_APPROVE,
    ENROLLMENT_ACTION_LOG_REFERENCE_CALL,
    ENROLLMENT_ACTIVE,
    EXECUTIVE_HEADERS,
    HEALTH_AMBER,
    HEALTH_GREEN,
    OPS_ADMIN_HEADERS,
    POSTURE_OPEN,
    PROGRAM_REFERENCE,
    SEGMENT_SMB,
    TIER_DIGITAL,
    TIER_HIGH_TOUCH,
    add_usage_signal,
    assert_capacity_conserved,
    assert_created,
    assert_credit_ledger,
    assert_field,
    assert_fields,
    assert_null,
    assert_page,
    build_roster_and_account,
    commit_case,
    factories,
    NEWEST_USAGE_ROW,
    nominate_enrollment,
    open_coverage,
    propose_commitment,
    read_account,
    read_case,
    read_csm,
    read_enrollment,
    segment_account,
    transition_commitment,
    transition_enrollment,
    validate_error,
)

# The first tranche of the negotiated package; 400,000 and the 300,000 second
# tranche both sit well inside the ten-percent credit cap of a 30,000,000 account.
FIRST_TRANCHE_CENTS = 400_000
SECOND_TRANCHE_CENTS = 300_000


def _amber_segmented_account(api: ApiClient) -> Dict[str, Any]:
    """A HIGH_TOUCH, AMBER account, returning the stale and fresh account versions."""
    state = build_roster_and_account(api)
    stale_version = state["account"]["version"]
    add_usage_signal(
        api,
        state["account_id"],
        state["csm_id"],
        NEWEST_USAGE_ROW["period_end_date"],
        NEWEST_USAGE_ROW["weekly_active_users"],
        NEWEST_USAGE_ROW["licensed_seats"],
        NEWEST_USAGE_ROW["feature_depth_pct"],
    )
    segmented = segment_account(api, state["account_id"])
    assert_fields(
        segmented, {"coverage_tier": TIER_HIGH_TOUCH, "health_tier": HEALTH_AMBER}
    )
    assert segmented["version"] > stale_version, (
        "the signal and segmentation writes must have bumped the account version"
    )
    state["stale_version"] = stale_version
    state["fresh_version"] = segmented["version"]
    return state


def _first_tranche_then_commit(api: ApiClient, state: Dict[str, Any]) -> int:
    """Accept one commitment and commit the case, returning the stale case version."""
    stale_version = state["case_version"]
    first = propose_commitment(
        api, state["case_id"], FIRST_TRANCHE_CENTS, "2026-08-25", stale_version
    )
    transition_commitment(api, first["id"], COMMITMENT_ACTION_ACCEPT)
    commit_case(api, state)
    return stale_version


class TestStaleAccountVersionOnCoverageAssignment:
    """Coverage-assignment creation is guarded by the account's version."""

    def test_stale_expected_account_version_is_refused(self, api: ApiClient) -> None:
        """A version observed before segmentation yields 412 and writes nothing.

        PRD §2.7: "A request to `POST /coverage-assignments` must carry `expected_account_version` holding the `version` of the target account as the client last observed it."
        PRD §2.7: "If that value does not equal the account's current `version`, the create is rejected with `ERR_STALE_ACCOUNT_VERSION` (HTTP 412) and nothing is written."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation."

        Design: Corner/cross_cutting_complexity_layers/stale_account_version_on_coverage_assignment_create_returns_412
        """
        state = _amber_segmented_account(api)

        response = api.create_coverage_assignment(
            factories.coverage_assignment(
                state["account_id"], state["stale_version"]
            ),
            OPS_ADMIN_HEADERS,
        )

        validate_error(response, ApiErrorId.STALE_ACCOUNT_VERSION)
        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm, {"capacity_units_committed": 0, "capacity_units_available": 40}
        )
        assert_capacity_conserved(csm)
        account = read_account(api, state["account_id"])
        assert_null(account, "assigned_csm_id")
        assert_page(
            api.list_coverage_assignments(
                OPS_ADMIN_HEADERS, {"account_id": state["account_id"]}
            ),
            expected_total=0,
        )

    def test_freshly_read_version_admits_the_assignment(self, api: ApiClient) -> None:
        """Quoting the version returned by segmentation commits a 17-unit assignment.

        PRD §2.7: "A request to `POST /coverage-assignments` must carry `expected_account_version` holding the `version` of the target account as the client last observed it."
        PRD §3.4: "The single ceiling is load-bearing: a `HIGH_TOUCH`, `ENTERPRISE`, `AMBER` account at 30,000,000 cents gives 9 × 1.50 × 1.10 = 14.85, plus a surcharge of 2, giving 16.85, whose ceiling is `load_units` 17 — whereas taking a ceiling of the 13.50 sub-product before applying the risk multiplier would give 18, a different and incorrect cost."
        PRD §3.4: "On admission the manager's `capacity_units_committed` rises by the assignment's `load_units`, `capacity_units_available` is recomputed, the assignment's `committed_at` is stamped with the logical clock, the account's `assigned_csm_id` is set to the assignment's `csm_id`, and `coverage_posture` is re-derived — which is how an otherwise clean account finally reaches `OPEN`."

        Design: Corner/cross_cutting_complexity_layers/stale_account_version_on_coverage_assignment_create_returns_412
        """
        state = _amber_segmented_account(api)

        assignment = assert_created(
            api.create_coverage_assignment(
                factories.coverage_assignment(
                    state["account_id"], state["fresh_version"]
                ),
                OPS_ADMIN_HEADERS,
            )
        )

        assert_fields(
            assignment,
            {
                "state": ASSIGNMENT_COMMITTED,
                "load_units": 17,
                "coverage_tier": TIER_HIGH_TOUCH,
                "csm_id": state["csm_id"],
            },
        )
        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm, {"capacity_units_committed": 17, "capacity_units_available": 23}
        )
        assert_capacity_conserved(csm)
        account = read_account(api, state["account_id"])
        assert_fields(
            account,
            {"assigned_csm_id": state["csm_id"], "coverage_posture": POSTURE_OPEN},
        )
        assert account["version"] > state["fresh_version"], (
            "admission mutates the account, so its version must advance again"
        )


class TestStaleEscalationVersionOnCommitment:
    """Remediation-commitment creation is guarded by the case's version."""

    def test_stale_expected_case_version_is_refused(
        self, api: ApiClient, escalated_account
    ) -> None:
        """A case version observed before the commit transition yields 412.

        PRD §2.7: "A request to `POST /escalation-cases/{id}/remediation-commitments` must carry `expected_escalation_case_version` holding the `version` of the escalation case named in the path as the client last observed it."
        PRD §2.7: "A mismatch with the case's current `version` is rejected with `ERR_STALE_ESCALATION_VERSION` (HTTP 412)."
        PRD §2.4: "`version` is an integer that starts at 1 when the row is created and increments by exactly 1 on every mutation."

        Design: Corner/cross_cutting_complexity_layers/stale_escalation_version_on_commitment_create_returns_412
        """
        stale_version = _first_tranche_then_commit(api, escalated_account)
        case = read_case(api, escalated_account["case_id"])
        assert case["version"] > stale_version, (
            "committing the case mutates it, so its version must advance"
        )

        response = api.create_remediation_commitment(
            escalated_account["case_id"],
            factories.remediation_commitment(
                SECOND_TRANCHE_CENTS, "2026-08-27", stale_version
            ),
            EXECUTIVE_HEADERS,
        )

        validate_error(response, ApiErrorId.STALE_ESCALATION_VERSION)
        assert_page(
            api.list_remediation_commitments(
                escalated_account["case_id"], OPS_ADMIN_HEADERS
            ),
            expected_total=1,
        )
        assert_credit_ledger(
            read_account(api, escalated_account["account_id"]),
            FIRST_TRANCHE_CENTS,
            0,
        )

    def test_freshly_read_case_version_admits_the_commitment(
        self, api: ApiClient, escalated_account
    ) -> None:
        """Re-reading the case and quoting its current version proposes a second tranche.

        PRD §2.7: "A mismatch with the case's current `version` is rejected with `ERR_STALE_ESCALATION_VERSION` (HTTP 412)."
        PRD §2.7: "Again the guard is doing work no state check can do: multiple proposed commitments per negotiation round are perfectly legal, so the create is not blocked by state."
        PRD §3.5: "The commitment is created in state `PROPOSED` with its `round_index` snapshotted from the case's current `remediation_round`, and it moves no credit counter yet."

        Design: Corner/cross_cutting_complexity_layers/stale_escalation_version_on_commitment_create_returns_412
        """
        _first_tranche_then_commit(api, escalated_account)
        case = read_case(api, escalated_account["case_id"])

        commitment = assert_created(
            api.create_remediation_commitment(
                escalated_account["case_id"],
                factories.remediation_commitment(
                    SECOND_TRANCHE_CENTS, "2026-08-27", case["version"]
                ),
                EXECUTIVE_HEADERS,
            )
        )

        assert_fields(
            commitment,
            {
                "state": COMMITMENT_PROPOSED,
                "round_index": 1,
                "credit_cents": SECOND_TRANCHE_CENTS,
            },
        )
        assert_page(
            api.list_remediation_commitments(
                escalated_account["case_id"], OPS_ADMIN_HEADERS
            ),
            expected_total=2,
        )
        assert_credit_ledger(
            read_account(api, escalated_account["account_id"]),
            FIRST_TRANCHE_CENTS,
            0,
        )


class TestReferenceCallCap:
    """The reference quota is a cumulative threshold tested before each increment."""

    def test_cap_admits_two_calls_and_refuses_the_third(
        self, api: ApiClient, digital_smb_account
    ) -> None:
        """An SMB enrollment capped at 2 logs two calls and refuses the third.

        PRD §3.8: "It begins in state `NOMINATED` with `reference_calls_used` 0, `last_reference_call_at` null, and its own `reference_calls_cap` **snapshotted** from the account's `reference_calls_cap` at creation: 6 for an `ENTERPRISE` account, 4 for `MIDMARKET`, 2 for `SMB`."
        PRD §3.8: "It requires that `program_type` be `REFERENCE` — a `CAB` enrollment has no reference quota — and that `reference_calls_used` be **strictly less than** `reference_calls_cap`; otherwise the request is refused with `ERR_REFERENCE_CALL_CAP_REACHED`."
        PRD §3.8: "On success `reference_calls_used` is incremented by 1 and `last_reference_call_at` is stamped with the logical clock."
        PRD §3.8: "Because the test is taken before the increment, an `SMB` enrollment with a cap of 2 admits a first call (0 is less than 2) and a second (1 is less than 2) and refuses a third (2 is not less than 2)."

        Design: Corner/cross_cutting_complexity_layers/reference_call_cap_is_a_cumulative_threshold_at_exactly_two
        """
        state = open_coverage(api, digital_smb_account)
        assert_fields(
            state["account"],
            {
                "segment_band": SEGMENT_SMB,
                "coverage_tier": TIER_DIGITAL,
                "health_tier": HEALTH_GREEN,
                "coverage_posture": POSTURE_OPEN,
                "reference_calls_cap": 2,
            },
        )
        assert_field(state["assignment"], "load_units", 1)

        enrollment = nominate_enrollment(
            api, state["account_id"], PROGRAM_REFERENCE
        )
        assert_field(enrollment, "reference_calls_cap", 2)
        transition_enrollment(api, enrollment["id"], ENROLLMENT_ACTION_APPROVE)
        transition_enrollment(api, enrollment["id"], ENROLLMENT_ACTION_ACTIVATE)

        first = transition_enrollment(
            api, enrollment["id"], ENROLLMENT_ACTION_LOG_REFERENCE_CALL
        )
        assert_field(first, "reference_calls_used", 1)
        second = transition_enrollment(
            api, enrollment["id"], ENROLLMENT_ACTION_LOG_REFERENCE_CALL
        )
        assert_fields(
            second, {"reference_calls_used": 2, "state": ENROLLMENT_ACTIVE}
        )
        assert second["last_reference_call_at"] is not None

        response = api.transition_advocacy_enrollment(
            enrollment["id"],
            factories.enrollment_transition(ENROLLMENT_ACTION_LOG_REFERENCE_CALL),
            ADVOCACY_HEADERS,
        )

        validate_error(response, ApiErrorId.REFERENCE_CALL_CAP_REACHED)
        unchanged = read_enrollment(api, state["account_id"], enrollment["id"])
        assert_fields(
            unchanged, {"reference_calls_used": 2, "state": ENROLLMENT_ACTIVE}
        )
