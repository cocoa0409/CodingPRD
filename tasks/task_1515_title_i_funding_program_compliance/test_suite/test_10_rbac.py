"""Role-based access control denials (PRD §2.1, §4)."""

from test_helpers import (
    ApiErrorId,
    api_client,
    build_user_headers,
    charge_expenditure,
    create_grant_payload,
    setup_certified_allocation,
    setup_ranking_locked,
    validate_error,
    validate_success,
)

DIRECTOR = build_user_headers("director-1", "FederalProgramsDirector")
ANALYST = build_user_headers("analyst-1", "ComplianceAnalyst")
MONITOR = build_user_headers("monitor-1", "SEAMonitor")
OMBUDSMAN = build_user_headers("omb-1", "PrivateSchoolOmbudsman")


class TestRoleDenials:

    def test_analyst_cannot_finalize_allocations(self):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §4: the finalize-allocations row authorizes only
        `FederalProgramsDirector`.

        Design: Corner/rbac/analyst_cannot_finalize_allocations
        """
        ctx = setup_ranking_locked(2098, [(50, 100)],
                                   total_allocation_cents=5_000_000)
        resp = api_client.finalize_allocations(ctx["grant"]["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        grant = validate_success(api_client.get_grant(ctx["grant"]["id"],
                                                      DIRECTOR))
        assert grant["status"] == "RANKING_LOCKED"

    def test_monitor_cannot_create_grant(self):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.1: "A `FederalProgramsDirector` opens the fiscal year by
        creating the **district grant**".

        Design: Corner/rbac/monitor_cannot_create_grant
        """
        resp = api_client.create_grant(
            create_grant_payload(fiscal_year=2099,
                                 total_allocation_cents=5_000_000),
            MONITOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_ombudsman_cannot_review_expenditure(self):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.7: "Allowable-cost review belongs to the director and never to
        the filer (§2.9)."

        Design: Corner/rbac/ombudsman_cannot_review_expenditure
        """
        ctx = setup_certified_allocation(2100, [(100, 100)])
        exp = charge_expenditure(ctx["grant"], 1000,
                                 school_allocation_id=ctx["allocation"]["id"],
                                 incurred_date="2099-09-01",
                                 description="supplies")
        resp = api_client.review_expenditure(exp["id"], {"decision": "ALLOW"},
                                             OMBUDSMAN)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        after = validate_success(api_client.get_expenditure(exp["id"],
                                                            DIRECTOR))
        assert after["status"] == "PENDING_REVIEW"

    def test_director_cannot_decide_waiver(self):
        """PRD §2.1: "A request whose role is recognized but not permitted to
        call the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS`
        (HTTP 403)."
        PRD §3.10: "The `SEAMonitor` decides a `REQUESTED` waiver — any other
        waiver status is rejected with `ERR_WAIVER_INVALID_STATE` — with a
        `decision` of `GRANT` or `DENY` and an optional `decision_note`."

        Design: Corner/rbac/director_cannot_decide_waiver
        """
        # ALLOCATED grant with zero expenditures: provisional carryover is
        # 100%, so the waiver request itself is valid.
        ctx = setup_certified_allocation(2099, [(100, 100)])
        grant_id = ctx["grant"]["id"]
        validate_success(api_client.request_carryover_waiver(
            grant_id,
            {"justification": "documented extraordinary circumstances justify "
                              "carrying more than fifteen percent forward"},
            DIRECTOR))
        resp = api_client.decide_carryover_waiver(
            grant_id, {"decision": "GRANT"}, DIRECTOR)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        grant = validate_success(api_client.get_grant(grant_id, DIRECTOR))
        assert grant["carryover_waiver_status"] == "REQUESTED", \
            "the district cannot grant its own waiver"
