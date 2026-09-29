"""Consistency model: a create response already carries its whole cascade.

There is nothing to poll for and nothing to settle later, so the body returned
by the write is compared field by field against the rows read immediately after.
"""

from test_helpers import (
    ApiClient,
    ASSIGNMENT_COMMITTED,
    EXECUTIVE_HEADERS,
    HEALTH_RED,
    OPS_ADMIN_HEADERS,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    TIER_HIGH_TOUCH,
    assert_capacity_conserved,
    assert_created,
    assert_field,
    assert_fields,
    assert_null,
    assert_ok,
    build_roster_and_account,
    factories,
    read_account,
    read_csm,
    segment_account,
)


class TestCoverageAssignmentCreateIsFullySettled:
    """The admission cascade is complete before the create returns."""

    def test_create_response_already_reflects_the_committed_state(
        self, api: ApiClient
    ) -> None:
        """The 201 body shows COMMITTED and 19 units, and later reads add nothing new.

        PRD §2.10: "There is no eventual consistency and no deferred reconciliation: the response to a request already reflects the complete cascade."
        PRD §3.4: "Every assignment row is born in state `QUEUED`, and an admission test then runs immediately at the end of the same request."
        PRD §3.4: "On admission the manager's `capacity_units_committed` rises by the assignment's `load_units`, `capacity_units_available` is recomputed, the assignment's `committed_at` is stamped with the logical clock, the account's `assigned_csm_id` is set to the assignment's `csm_id`, and `coverage_posture` is re-derived — which is how an otherwise clean account finally reaches `OPEN`."
        PRD §3.4: "Flipping only the health tier to `RED` yields 16.88 plus 2, so 19; flipping only to `GREEN` yields 13.50 plus 2, so 16; flipping only the segment to `MIDMARKET` yields 9.90 plus 2, so 12; flipping only the coverage tier to `LOW_TOUCH` yields 8.25 plus 2, so 11."

        Design: Corner/consistency_model/coverage_assignment_create_response_already_reflects_the_committed_state
        """
        state = build_roster_and_account(api)
        assert_fields(
            state["account"],
            {"health_tier": HEALTH_RED, "coverage_posture": POSTURE_RESTRICTED},
        )
        assert_null(state["account"], "assigned_csm_id")
        segmented = segment_account(api, state["account_id"])
        assert_field(segmented, "coverage_tier", TIER_HIGH_TOUCH)

        created = assert_created(
            api.create_coverage_assignment(
                factories.coverage_assignment(
                    state["account_id"], segmented["version"]
                ),
                OPS_ADMIN_HEADERS,
            )
        )

        # The write's own body is already the settled row.
        assert_fields(
            created,
            {
                "state": ASSIGNMENT_COMMITTED,
                "load_units": 19,
                "coverage_tier": TIER_HIGH_TOUCH,
                "csm_id": state["csm_id"],
                "account_id": state["account_id"],
            },
        )
        assert created["committed_at"] is not None, (
            "committed_at must be stamped inside the create request"
        )
        assert_null(created, "released_at", "superseded_by_assignment_id")

        # Every row the cascade touched agrees with that body on the next read.
        csm = read_csm(api, state["csm_id"])
        assert_fields(
            csm,
            {
                "capacity_units_total": 40,
                "capacity_units_committed": 19,
                "capacity_units_available": 21,
            },
        )
        assert_capacity_conserved(csm)
        account = read_account(api, state["account_id"])
        assert_fields(
            account,
            {"assigned_csm_id": state["csm_id"], "coverage_posture": POSTURE_OPEN},
        )
        fetched = assert_ok(
            api.get_coverage_assignment(created["id"], EXECUTIVE_HEADERS)
        )
        assert_fields(
            fetched,
            {
                "state": ASSIGNMENT_COMMITTED,
                "load_units": 19,
                "committed_at": created["committed_at"],
                "version": created["version"],
            },
        )
