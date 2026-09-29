"""Who may act: header authentication before anything else, one owner per write, carrier
scope that errors on single reads but silently filters lists, and the two-person bars on
the corrective-action plan.
"""

from typing import Any, Dict

from test_helpers import (
    AUDITOR_ALICE,
    AUDITOR_BOB,
    AUDITOR_CAROL,
    AUDITOR_DAVE,
    ApiErrorId,
    BasicCategory,
    CapDecision,
    CapItemAction,
    CapItemStatus,
    CapReviewBranch,
    CapReviewOutcome,
    CapStatus,
    SafetyFitnessStatus,
    UnitType,
    assert_one_decimal,
    factories as fac,
    fixtures as fx,
    get_success_data,
    make_auditor_headers,
    make_carrier_analyst_headers,
    make_carrier_safety_manager_headers,
    make_review_officer_headers,
    make_state_officer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

UD = BasicCategory.UNSAFE_DRIVING
HOS = BasicCategory.HOURS_OF_SERVICE

NO_ROLE_HEADERS = {"X-User-ID": AUDITOR_ALICE, "Content-Type": "application/json"}
NO_USER_HEADERS = {"X-User-Role": "FmcsaProgramAuditor", "Content-Type": "application/json"}
UNKNOWN_ROLE_HEADERS = {
    "X-User-ID": AUDITOR_ALICE,
    "X-User-Role": "SafetyDirector",
    "Content-Type": "application/json",
}


class TestHeaderAuthentication:
    def test_three_header_defects_all_read_as_unauthenticated(self, api):
        """PRD 2.1: "If either header is absent, or if `X-User-Role` is not one of those
        five strings, the request fails with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_or_unknown_role_headers_rejected
        """
        for headers in (NO_ROLE_HEADERS, NO_USER_HEADERS, UNKNOWN_ROLE_HEADERS):
            validate_error(
                api.list_carriers(headers), ApiErrorId.UNAUTHENTICATED, 401
            )

        blocked_write = api.create_carrier(
            fac.create_carrier_payload(
                dot_number="1000001",
                legal_name="Buckeye Freight LLC",
                average_power_units=20,
                annual_vmt=1600000,
            ),
            NO_ROLE_HEADERS,
        )
        validate_error(blocked_write, ApiErrorId.UNAUTHENTICATED, 401)

        _, meta = validate_paginated(api.list_carriers(fx.AUDITOR))
        assert meta["total_count"] == 0


class TestExclusiveOwnershipOfWrites:
    def test_no_role_may_borrow_another_roles_write(self, api):
        """PRD 2.1: "If the headers are well formed but the declared role is not among the
        roles authorised for the endpoint being called, the request fails with
        `ERR_ROLE_NOT_PERMITTED`."

        Design: Corner/rbac/exclusive_operations_of_other_roles_rejected
        """
        fx.set_clock(api)
        carrier = fx.create_carrier(api)
        carrier_id = carrier["id"]

        probes = [
            api.create_carrier(
                fac.create_carrier_payload(
                    dot_number="1000002",
                    legal_name="Analyst Attempt LLC",
                    average_power_units=5,
                    annual_vmt=200000,
                ),
                make_carrier_analyst_headers(carrier_id),
            ),
            api.create_inspection_report(
                fac.create_inspection_report_payload(
                    carrier_id,
                    report_number="OH2026080103",
                    vehicle_vin="1FUJA6CK21LK00420",
                    inspection_start="2026-08-01T09:00:00Z",
                    inspection_end="2026-08-01T10:00:00Z",
                ),
                make_review_officer_headers(),
            ),
            api.create_corrective_action_plan(
                fac.create_cap_payload(
                    carrier_id,
                    carrier["version"],
                    narrative="Manager attempting to open a plan.",
                ),
                make_carrier_safety_manager_headers(carrier_id),
            ),
            api.set_clock("2026-08-02T00:00:00Z", make_state_officer_headers()),
            api.create_scoring_run(
                fac.create_scoring_run_payload(
                    note="Officer attempting a program run."
                ),
                make_state_officer_headers(),
            ),
        ]
        for response in probes:
            validate_error(response, ApiErrorId.ROLE_NOT_PERMITTED, 403)

        carriers, carrier_meta = validate_paginated(api.list_carriers(fx.AUDITOR))
        assert carrier_meta["total_count"] == 1
        assert carriers[0]["id"] == carrier_id
        _, report_meta = validate_paginated(api.list_inspection_reports(fx.AUDITOR))
        assert report_meta["total_count"] == 0
        _, plan_meta = validate_paginated(
            api.list_corrective_action_plans(fx.AUDITOR)
        )
        assert plan_meta["total_count"] == 0


def _two_carriers_each_with_a_scored_report(api) -> Dict[str, Any]:
    """One scored report per carrier, so every collection holds exactly one row of each."""
    fx.set_clock(api)
    first = fx.create_carrier(api)
    second = fx.create_carrier(
        api,
        dot_number="1000002",
        legal_name="Scioto Logistics Inc",
        average_power_units=20,
        annual_vmt=1600000,
    )
    code = fx.create_violation_code(
        api, code="392.2S", basic_category=UD, severity_weight=5
    )
    fx.create_threshold(
        api,
        basic_category=UD,
        carrier_segment="MEDIUM",
        measure_at_p50=0.5,
        measure_at_p65=1.0,
        measure_at_p80=2.0,
    )
    own_report, own_rows = fx.build_scored_report(
        api,
        first["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070417",
        vehicle_vin="1FUJA6CK21LK00421",
        inspection_start="2026-07-01T14:00:00Z",
        inspection_end="2026-07-01T15:00:00Z",
    )
    peer_report, peer_rows = fx.build_scored_report(
        api,
        second["id"],
        [{"violation_code_id": code["id"], "unit_type": UnitType.VEHICLE}],
        report_number="OH2026070418",
        vehicle_vin="1FUJA6CK21LK00422",
        inspection_start="2026-07-02T14:00:00Z",
        inspection_end="2026-07-02T15:00:00Z",
    )
    return {
        "first": first,
        "second": second,
        "own_report": own_report,
        "own_violation": own_rows[0],
        "peer_report": peer_report,
        "peer_violation": peer_rows[0],
    }


class TestCarrierScope:
    def test_single_reads_of_a_peer_error_while_lists_just_hide_it(self, api):
        """PRD 2.1: "A carrier-side role that addresses a single resource belonging to a
        different carrier, or attempts a write against one, is rejected with
        `ERR_CARRIER_SCOPE_VIOLATION`. List endpoints behave differently: rather than
        erroring, they are silently filtered so that a carrier-side caller sees only rows
        belonging to its own carrier."

        Design: Corner/rbac/peer_carrier_resources_are_scoped_and_lists_silently_filtered
        """
        scenario = _two_carriers_each_with_a_scored_report(api)
        own_id = scenario["first"]["id"]
        peer_id = scenario["second"]["id"]
        analyst = make_carrier_analyst_headers(own_id)
        manager = make_carrier_safety_manager_headers(own_id)

        probes = [
            api.get_carrier(peer_id, analyst),
            api.get_inspection_report(scenario["peer_report"]["id"], analyst),
            api.get_violation(scenario["peer_violation"]["id"], manager),
            api.get_screening_risk(peer_id, analyst),
        ]
        for response in probes:
            validate_error(response, ApiErrorId.CARRIER_SCOPE_VIOLATION, 403)

        reports, report_meta = validate_paginated(api.list_inspection_reports(analyst))
        assert report_meta["total_count"] == 1
        assert reports[0]["id"] == scenario["own_report"]["id"]

        carriers, carrier_meta = validate_paginated(api.list_carriers(analyst))
        assert carrier_meta["total_count"] == 1
        assert carriers[0]["id"] == own_id

        own = validate_success(
            api.get_inspection_report(scenario["own_report"]["id"], analyst), 200
        )
        assert own["attributed_carrier_id"] == own_id


def _plan_awaiting_its_decision(api) -> Dict[str, Any]:
    """A plan cleared on both branches with its single item verified, so it waits in
    PENDING_DECISION on a carrier whose determination was made by auditor_bob."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    determined = fx.issue_fitness_determination(
        api,
        carrier["id"],
        SafetyFitnessStatus.CONDITIONAL,
        auditor_id=AUDITOR_BOB,
        basis_note="Compliance review found HOS recordkeeping deficiencies.",
    )
    assert determined["safety_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
    analyst = make_carrier_analyst_headers(carrier["id"])
    manager = make_carrier_safety_manager_headers(carrier["id"])
    plan = fx.create_cap(
        api, carrier["id"], narrative="Plan to correct HOS recordkeeping."
    )
    item = fx.add_cap_item(
        api,
        carrier["id"],
        plan["id"],
        basic_category=HOS,
        description="Retrain dispatch on ELD edits.",
        target_completion_date="2026-10-01T00:00:00Z",
    )
    fx.set_item_status(api, item["id"], CapItemAction.COMMIT, analyst, note="Committed.")
    get_success_data(api.submit_cap(plan["id"], manager))
    for branch, auditor in (
        (CapReviewBranch.SAFETY, AUDITOR_CAROL),
        (CapReviewBranch.DATA, AUDITOR_DAVE),
    ):
        get_success_data(
            api.review_cap(
                plan["id"],
                {
                    "branch": branch,
                    "outcome": CapReviewOutcome.CLEARED,
                    "note": f"{branch} branch cleared.",
                },
                make_auditor_headers(auditor),
            )
        )
    fx.set_item_status(
        api, item["id"], CapItemAction.IMPLEMENT, manager, note="Training delivered."
    )
    verified = fx.set_item_status(
        api,
        item["id"],
        CapItemAction.VERIFY,
        make_auditor_headers(AUDITOR_ALICE),
        note="Rosters and ELD audit reviewed.",
    )
    return {"carrier": carrier, "plan": plan, "item": item, "verified": verified}


class TestDecisionSegregation:
    def test_the_determining_auditor_alone_may_not_decide_the_plan(self, api):
        """PRD 2.11: "A later attempt to decide that carrier's corrective action plan —
        whether the decision is to accept or to return — is rejected when the deciding
        auditor's `X-User-ID` equals the stored `fitness_determined_by_user_id`."

        Design: Corner/rbac/cap_decision_by_the_fitness_determiner_rejected
        """
        scenario = _plan_awaiting_its_decision(api)
        plan_id = scenario["plan"]["id"]
        carrier_id = scenario["carrier"]["id"]

        assert scenario["verified"]["status"] == CapItemStatus.VERIFIED
        waiting = fx.read_cap(api, plan_id)
        assert waiting["status"] == CapStatus.PENDING_DECISION
        assert_one_decimal(waiting["completion_pct"], 100.0)
        assert (
            fx.read_carrier(api, carrier_id)["fitness_determined_by_user_id"]
            == AUDITOR_BOB
        )

        conflicted = api.decide_cap(
            plan_id,
            {"decision": CapDecision.ACCEPT, "note": "Deciding my own determination."},
            make_auditor_headers(AUDITOR_BOB),
        )
        validate_error(conflicted, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        held = fx.read_cap(api, plan_id)
        assert held["status"] == CapStatus.PENDING_DECISION
        assert held["decision"] is None
        assert (
            fx.read_carrier(api, carrier_id)["safety_fitness_status"]
            == SafetyFitnessStatus.CONDITIONAL
        )

        accepted = validate_success(
            api.decide_cap(
                plan_id,
                {
                    "decision": CapDecision.ACCEPT,
                    "note": "Plan accepted after independent review.",
                },
                make_auditor_headers(AUDITOR_ALICE),
            ),
            200,
        )
        assert accepted["status"] == CapStatus.ACCEPTED
        assert accepted["decision"] == CapDecision.ACCEPT
        assert accepted["decided_by_user_id"] == AUDITOR_ALICE
        assert accepted["decided_at"].startswith("2026-08-01T00:00:00")
        assert (
            fx.read_carrier(api, carrier_id)["safety_fitness_status"]
            == SafetyFitnessStatus.SATISFACTORY
        )


def _plan_with_its_safety_branch_cleared(api) -> Dict[str, Any]:
    """A submitted plan whose SAFETY branch has been cleared by auditor_carol, its single
    item still only COMMITTED."""
    fx.set_clock(api)
    carrier = fx.create_carrier(api)
    determined = fx.issue_fitness_determination(
        api,
        carrier["id"],
        SafetyFitnessStatus.CONDITIONAL,
        auditor_id=AUDITOR_BOB,
        basis_note="Compliance review found HOS recordkeeping deficiencies.",
    )
    assert determined["safety_fitness_status"] == SafetyFitnessStatus.CONDITIONAL
    analyst = make_carrier_analyst_headers(carrier["id"])
    manager = make_carrier_safety_manager_headers(carrier["id"])
    plan = fx.create_cap(
        api, carrier["id"], narrative="Plan to correct HOS recordkeeping."
    )
    item = fx.add_cap_item(
        api,
        carrier["id"],
        plan["id"],
        basic_category=HOS,
        description="Retrain dispatch on ELD edits.",
        target_completion_date="2026-10-01T00:00:00Z",
    )
    fx.set_item_status(api, item["id"], CapItemAction.COMMIT, analyst, note="Committed.")
    get_success_data(api.submit_cap(plan["id"], manager))
    get_success_data(
        api.review_cap(
            plan["id"],
            {
                "branch": CapReviewBranch.SAFETY,
                "outcome": CapReviewOutcome.CLEARED,
                "note": "Safety branch cleared.",
            },
            make_auditor_headers(AUDITOR_CAROL),
        )
    )
    return {"carrier": carrier, "plan": plan, "item": item}


class TestReviewBranchSegregation:
    def test_the_second_branch_needs_a_second_pair_of_eyes(self, api):
        """PRD 3.10: "And the acting `X-User-ID` must differ from the identifier already
        recorded for the other branch, else `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/both_cap_review_branches_by_the_same_auditor_rejected
        """
        scenario = _plan_with_its_safety_branch_cleared(api)
        plan_id = scenario["plan"]["id"]

        same_auditor = api.review_cap(
            plan_id,
            {
                "branch": CapReviewBranch.DATA,
                "outcome": CapReviewOutcome.CLEARED,
                "note": "Same auditor clearing the second branch.",
            },
            make_auditor_headers(AUDITOR_CAROL),
        )
        validate_error(same_auditor, ApiErrorId.SEGREGATION_OF_DUTIES, 403)
        held = fx.read_cap(api, plan_id)
        assert held["data_review_outcome"] is None
        assert held["data_review_user_id"] is None
        assert held["status"] == CapStatus.IN_REVIEW

        cleared = validate_success(
            api.review_cap(
                plan_id,
                {
                    "branch": CapReviewBranch.DATA,
                    "outcome": CapReviewOutcome.CLEARED,
                    "note": "Data branch cleared independently.",
                },
                make_auditor_headers(AUDITOR_DAVE),
            ),
            200,
        )
        assert cleared["data_review_outcome"] == CapReviewOutcome.CLEARED
        assert cleared["data_review_user_id"] == AUDITOR_DAVE
        assert cleared["safety_review_user_id"] == AUDITOR_CAROL
        assert_one_decimal(cleared["completion_pct"], 0.0)
        assert cleared["status"] == CapStatus.IN_REVIEW
