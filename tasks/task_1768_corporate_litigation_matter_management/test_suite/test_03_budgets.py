"""Budgets: optimistic concurrency, supersession chain, activation fiscal gate."""
from test_helpers import (
    TIER2_EXPOSURE,
    create_active_engagement,
    create_approved_budget,
    create_approved_firm,
    create_budget_payload,
    create_deadline,
    create_matter,
    create_settlement_request_payload,
    create_staff_user,
    fresh_matter_version,
    get_success_data,
    make_counsel_headers,
    setup_active_matter,
    setup_staffing_matter,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId, MatterStatus


class TestVersionGuardedBudgetCreate:
    def test_stale_matter_version_occ_conflict(self, api):
        """PRD §2.7: "Creating a budget for a matter and creating a settlement request
        for a matter each require the request body to carry `expected_matter_version`,
        a non-optional field holding the matter's `version` as the client last
        observed it."
        PRD §2.7: "the supplied value will not match the matter's current `version`,
        and the create is rejected with `ERR_STALE_MATTER_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_matter_version_occ_conflict
        """
        counsel = create_staff_user("Casey Counsel", "casey@corp.example", "LEGAL")
        headers = make_counsel_headers(counsel["id"])
        matter = create_matter(counsel["id"])
        stale_version = matter["version"]
        get_success_data(api.submit_assessment(matter["id"], headers))
        create_deadline(matter["id"], counsel["id"])
        get_success_data(api.advance_to_staffing(matter["id"], headers))

        resp = api.create_budget(
            matter["id"],
            create_budget_payload(expected_matter_version=stale_version), headers)
        validate_error(resp, ApiErrorId.ERR_STALE_MATTER_VERSION, 412)

        current_version = fresh_matter_version(matter["id"], headers)
        created = validate_success(api.create_budget(
            matter["id"],
            create_budget_payload(expected_matter_version=current_version), headers), 201)
        assert created["status"] == "DRAFT"

    def test_settlement_create_stale_occ_version(self, api):
        """PRD §2.7: "Creating a budget for a matter and creating a settlement request
        for a matter each require the request body to carry `expected_matter_version`,
        a non-optional field holding the matter's `version` as the client last
        observed it."
        PRD §2.7: "the supplied value will not match the matter's current `version`,
        and the create is rejected with `ERR_STALE_MATTER_VERSION` (HTTP 412)."

        Design: Corner/validations/settlement_create_stale_occ_version
        """
        ctx = setup_active_matter(exposure=TIER2_EXPOSURE)
        current = fresh_matter_version(ctx["matter_id"], ctx["counsel"])
        payload = create_settlement_request_payload(
            proposed_amount_cents=5_000_000,
            expected_matter_version=current - 1)
        resp = api.create_settlement_request(ctx["matter_id"], payload, ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_STALE_MATTER_VERSION, 412)


class TestBudgetSupersedeChain:
    def test_budget_supersede_chain_cascade(self, api):
        """PRD §3.2: "passing them moves the budget `SUBMITTED` → `APPROVED`, stamps
        `approved_by_user_id`, supersedes the referenced prior version (`APPROVED` →
        `SUPERSEDED`, a cascade that increments the old budget's `version`), and
        computes the budget's `utilization_pct`."
        PRD §3.2: "at most one budget per matter is ever `APPROVED` at a time."

        Design: Corner/state_machines/budget_supersede_chain_cascade
        """
        ctx = setup_staffing_matter()
        b1 = create_approved_budget(ctx["matter_id"], ctx["counsel_id"], ctx["fin_id"],
                                    fy_budget_cents=500_000_000)
        assert b1["status"] == "APPROVED"

        version = fresh_matter_version(ctx["matter_id"], ctx["counsel"])
        b2 = get_success_data(api.create_budget(
            ctx["matter_id"],
            create_budget_payload(lifecycle_budget_cents=1_200_000_000,
                                  fy_budget_cents=600_000_000,
                                  expected_matter_version=version,
                                  prior_version_id=b1["id"]),
            ctx["counsel"]))
        get_success_data(api.submit_budget(b2["id"], ctx["counsel"]))
        b2_after = validate_success(api.approve_budget(b2["id"], ctx["fin"]))
        assert b2_after["status"] == "APPROVED"

        b1_after = get_success_data(api.get_budget(b1["id"], ctx["fin"]))
        assert b1_after["status"] == "SUPERSEDED", \
            "approval of the revision must cascade the prior version to SUPERSEDED"

        data, _meta = validate_paginated(api.list_budgets(
            ctx["fin"], params={"matter_id": ctx["matter_id"], "status": "APPROVED"}))
        assert len(data) == 1, "exactly one APPROVED budget per matter"
        assert data[0]["id"] == b2["id"]


class TestActivationFiscalGate:
    def test_error_no_approved_budget_on_matter_activate(self, api):
        """PRD §3.2: "From `STAFFING`, activation to `ACTIVE` requires at least one
        engagement of the matter in `ACTIVE` status (else `ERR_NO_ACTIVE_ENGAGEMENT`),
        an `APPROVED` budget (else `ERR_NO_APPROVED_BUDGET`), and the owning counsel."

        Design: Corner/errors/error_no_approved_budget_on_matter_activate
        """
        ctx = setup_staffing_matter()
        firm = create_approved_firm(ctx["gc_id"])
        create_active_engagement(ctx["matter_id"], firm["id"],
                                 ctx["counsel_id"], ctx["dgc_id"])

        resp = api.activate_matter(ctx["matter_id"], ctx["counsel"])
        validate_error(resp, ApiErrorId.ERR_NO_APPROVED_BUDGET)
        matter = get_success_data(api.get_matter(ctx["matter_id"], ctx["counsel"]))
        assert matter["status"] == MatterStatus.STAFFING.value
