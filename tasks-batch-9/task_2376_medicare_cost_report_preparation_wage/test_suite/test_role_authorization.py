"""The segregation-of-duties control: the preparer's whole surface, the two
refusals across the preparer/attester split, the near-blind clerk's narrow
permission, the proposer-may-not-resolve rule, provider scoping, the missing
role header, and the one write two roles genuinely share."""

from test_helpers import (
    CANONICAL_UCC_DATA_SET,
    CANONICAL_WAGE_SUBMISSION,
    CLERK_HEADERS,
    ApiErrorId,
    assert_fte_equals,
    assert_money_equals,
    assert_ratio_equals,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.factories import (
    appeal_decision_payload,
    audit_resolution_payload,
    cost_center_payload,
    general_service_center_payload,
    map_payload,
    occ_mix_response_payload,
    reclassification_payload,
    resident_payload,
    rotation_assignment_payload,
    stepdown_run_payload,
    trial_balance_line_payload,
    workpaper_leg,
)
from test_helpers.fixtures import (
    accept_wage_submission,
    add_ucc_data_set,
    create_appeal_case,
    create_cost_report,
    create_other_provider,
    create_provider,
    create_settlement,
    file_report,
    new_scenario,
    propose_audit_adjustment,
    read_cost_center,
    read_cost_report,
    respond_to_audit_adjustment,
    role_headers_for,
    run_stepdown,
    set_clock,
    setup_two_center_report,
)
from test_helpers.test_users import (
    AUDITOR_ONE_ID,
    AUDITOR_TWO_ID,
    make_mac_auditor_headers,
    make_reimbursement_analyst_headers,
    no_auth_headers,
)


def _final_settlement_with_a_proposed_adjustment(api):
    """A FINAL_SETTLED two-center report carrying one PROPOSED audit exception."""
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    accept_wage_submission(api, scenario)
    add_ucc_data_set(api, scenario)
    file_report(api, scenario)
    create_settlement(api, scenario, "TENTATIVE")
    run_stepdown(api, scenario, "DOUBLE_APPORTIONMENT")
    create_settlement(api, scenario, "FINAL")
    propose_audit_adjustment(
        api,
        scenario,
        target_key="cc_routine",
        code="ADJ-A8-14",
        rationale="Non-allowable advertising in routine nursing",
        proposed_amount_cents=-1500000,
    )
    return scenario


def test_the_preparer_walks_its_whole_surface_without_a_single_refusal(api):
    """All thirteen preparation writes plus the two shared ones succeed under one
    analyst, so no preparation endpoint is gated behind another role.

    PRD 2.1: "A `ReimbursementAnalyst` prepares: cost centers, trial balance loading and mapping, workpaper entries and their reversal, wage index data collection and occupational mix responses, residents and rotation assignments, and the uncompensated care data set."

    PRD 2.1: "Analysts and auditors both may trigger a stepdown run and a recompute of the uncompensated care figures."

    PRD 3.7: "The `recompute_required` flag records whether these figures have gone stale: the server sets it to true when the report's allocation went `STALE` after the data set was last recomputed, and clears it to false on every recompute — whether triggered explicitly by an analyst or auditor, or as part of the completed-stepdown cascade."

    Design: Corner/rbac/analyst_can_perform_every_preparation_operation_it_owns
    """
    scenario = new_scenario(api)
    report_id = scenario["report_id"]
    analyst = scenario["analyst"]

    allocator = validate_success(
        api.create_cost_center(
            report_id,
            general_service_center_payload(statistics={"SQUARE_FEET": 0}),
            analyst,
        ),
        201,
    )
    receiver = validate_success(
        api.create_cost_center(
            report_id, cost_center_payload(statistics={"SQUARE_FEET": 2000}), analyst
        ),
        201,
    )
    validate_success(
        api.update_cost_center(
            receiver["id"], {"statistics": {"SQUARE_FEET": 3000}}, analyst
        )
    )
    validate_success(
        api.create_trial_balance_line(
            report_id,
            trial_balance_line_payload(
                gl_account="6000",
                description="Administration salaries",
                amount_cents=100000000,
                mapped_cost_center_id=allocator["id"],
            ),
            analyst,
        ),
        201,
    )
    nursing_line = validate_success(
        api.create_trial_balance_line(
            report_id,
            trial_balance_line_payload(
                gl_account="6200", description="Nursing salaries", amount_cents=200000000
            ),
            analyst,
        ),
        201,
    )
    validate_success(
        api.map_trial_balance_line(
            nursing_line["id"], map_payload(receiver["id"]), analyst
        )
    )
    entry = validate_success(
        api.create_workpaper_entry(
            report_id,
            reclassification_payload(
                [
                    workpaper_leg(allocator["id"], -5000000),
                    workpaper_leg(receiver["id"], 5000000),
                ],
                code="A-6-1",
                description="Move nursing administration to routine",
            ),
            analyst,
        ),
        201,
    )

    version = validate_success(api.get_cost_report(report_id, analyst))["version"]
    run = validate_success(
        api.create_stepdown_run(
            report_id, stepdown_run_payload(version, "SINGLE_APPORTIONMENT"), analyst
        ),
        201,
    )

    submission = validate_success(
        api.create_wage_index_submission(
            report_id, dict(CANONICAL_WAGE_SUBMISSION), analyst
        ),
        201,
    )
    validate_success(
        api.update_wage_index_submission(
            submission["id"], {"contract_labor_cents": 250000000}, analyst
        )
    )
    rn_response = validate_success(
        api.create_occ_mix_response(
            submission["id"], occ_mix_response_payload(), analyst
        ),
        201,
    )

    resident = validate_success(
        api.create_resident(
            scenario["provider_id"],
            resident_payload(full_name="Dana Okafor MD", irp_status="WITHIN_IRP"),
            analyst,
        ),
        201,
    )
    rotation = validate_success(
        api.create_rotation_assignment(
            resident["id"],
            rotation_assignment_payload(
                receiver["id"],
                start_date="2025-07-01",
                end_date="2025-08-01",
                fte_fraction=1.00,
            ),
            analyst,
        ),
        201,
    )

    data_set = validate_success(
        api.create_ucc_data_set(report_id, dict(CANONICAL_UCC_DATA_SET), analyst),
        201,
    )
    recomputed = validate_success(api.recompute_ucc_data_set(data_set["id"], analyst))
    assert recomputed["recompute_required"] is False
    assert_money_equals(
        recomputed["uncompensated_care_cost_cents"],
        36500000,
        "uncompensated_care_cost_cents",
    )
    assert_money_equals(recomputed["ucc_payment_cents"], 7300000, "ucc_payment_cents")

    voided = validate_success(api.void_rotation_assignment(rotation["id"], analyst))
    assert voided["status"] == "VOID"
    assert_fte_equals(voided["fte_days"], 0.0000, "fte_days")

    validate_success(api.reverse_workpaper_entry(entry["id"], analyst))

    assert_money_equals(
        read_cost_center(api, scenario, allocator["id"])["direct_cost_cents"],
        100000000,
        "00100 direct_cost_cents",
    )
    assert (
        read_cost_center(api, scenario, receiver["id"])["statistics"]["SQUARE_FEET"]
        == 3000
    )

    assert validate_success(api.get_stepdown_run(run["id"], analyst))["status"] == "STALE"
    assert_money_equals(
        validate_success(api.get_occ_mix_response(rn_response["id"], analyst))[
            "category_ahw_cents"
        ],
        3500,
        "category_ahw_cents",
    )
    assert_fte_equals(
        validate_success(api.get_resident(resident["id"], analyst))["assigned_fte_days"],
        0.0000,
        "assigned_fte_days",
    )
    assert (
        validate_success(api.get_ucc_data_set(data_set["id"], analyst))[
            "recompute_required"
        ]
        is True
    )

    report = read_cost_report(api, scenario)
    assert report["allocation_status"] == "STALE"
    assert report["status"] == "DRAFT"


def test_the_attester_may_not_build_the_worksheet(api):
    """The manager who is entitled to file this very report may not open a cost
    center on it, and the refusal writes nothing at all.

    PRD 2.1: "Neither role may perform the other's exclusive operations — an analyst attempting to file, or a manager attempting to load a trial balance line, receives `ERR_FORBIDDEN_ROLE`."

    PRD 4: "| POST | `/cost-reports/{id}/cost-centers` | Create a worksheet A cost center | `ReimbursementAnalyst` |"

    Design: Corner/rbac/manager_cannot_create_a_cost_center
    """
    scenario = new_scenario(api)

    response = api.create_cost_center(
        scenario["report_id"],
        general_service_center_payload(statistics={"SQUARE_FEET": 0}),
        scenario["manager"],
    )

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)

    centers, meta = validate_paginated(
        api.list_report_cost_centers(scenario["report_id"], scenario["analyst"])
    )
    assert meta["total_count"] == 0
    assert centers == []
    assert read_cost_report(api, scenario)["version"] == 1


def test_the_role_gate_outranks_every_filing_precondition(api):
    """The report has no centers, no ledger, no wage data and no care data, yet the
    analyst's filing attempt still answers on the role gate alone.

    PRD 2.1: "Neither role may perform the other's exclusive operations — an analyst attempting to file, or a manager attempting to load a trial balance line, receives `ERR_FORBIDDEN_ROLE`."

    PRD 2.10: "2. **Authorization by role** — the caller's role appears in the endpoint's permitted set, else `ERR_FORBIDDEN_ROLE` (403). Applies to every endpoint."

    Design: Corner/rbac/analyst_cannot_file_the_cost_report
    """
    scenario = new_scenario(api)

    response = api.file_cost_report(scenario["report_id"], scenario["analyst"])

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_UNMAPPED_TRIAL_BALANCE.value
    assert (
        response.json()["data"]["error_id"]
        != ApiErrorId.ERR_WAGE_SUBMISSION_NOT_ACCEPTED.value
    )

    report = read_cost_report(api, scenario)
    assert report["status"] == "DRAFT"
    assert report["filed_at"] is None


def test_the_board_clerk_may_not_read_the_cost_report_it_hears_about(api):
    """The clerk is the one authenticated role shut out of the report read, and the
    refusal is a role refusal rather than a pretence that the row is missing.

    PRD 2.1: "A `ReviewBoardClerk` is deliberately near-blind: it may read appeal cases and settlements and record board hearings and board decisions, and nothing else — a clerk reading a cost report receives `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/review_board_clerk_cannot_read_a_cost_report
    """
    scenario = new_scenario(api)

    response = api.get_cost_report(scenario["report_id"], CLERK_HEADERS)

    validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_COST_REPORT_NOT_FOUND.value
    assert "status" not in response.json()["data"]
    assert "allocation_status" not in response.json()["data"]


def test_the_board_clerk_hears_the_appeal_and_reads_what_it_is_about(api):
    """A hearing is not a decision: the case reaches HEARD with decided_at still
    null, and both reads the clerk is permitted return bodies.

    PRD 3.9: "`HEAR`, from `REQUESTED` on a case of `kind` `PRRB_APPEAL` whose referenced settlement has `status` `APPEALED`, advances the case to `HEARD`; it records the hearing in `decision_note` and deliberately leaves `decided_at` at null, since a hearing is not a decision."

    PRD 3.8: "`PROTEST` moves the adjustment to `PROTESTED`, imposes no additional report-status requirement, and — this is the branch-specific effect absent from the accept path — sets the parent settlement's `status` to `APPEALED`."

    Design: Corner/rbac/review_board_clerk_can_hear_a_prrb_appeal_and_read_its_settlement
    """
    scenario = _final_settlement_with_a_proposed_adjustment(api)
    respond_to_audit_adjustment(
        api,
        scenario,
        response="PROTEST",
        note="Advertising cost is community outreach, protested",
    )
    case = create_appeal_case(
        api,
        scenario,
        settlement_id=scenario["final_settlement_id"],
        kind="PRRB_APPEAL",
        issue_description="Wage index occupational mix hours misclassified",
        amount_at_issue_cents=2500000,
    )

    heard = validate_success(
        api.decide_appeal_case(
            case["id"],
            appeal_decision_payload(
                outcome="HEAR", decision_note="Hearing held, record closed"
            ),
            CLERK_HEADERS,
        )
    )

    assert heard["status"] == "HEARD"
    assert heard["decided_at"] is None
    assert heard["decision_note"] == "Hearing held, record closed"

    reread_case = validate_success(api.get_appeal_case(case["id"], CLERK_HEADERS))
    assert reread_case["status"] == "HEARD"
    assert reread_case["decided_at"] is None

    settlement = validate_success(
        api.get_settlement(scenario["final_settlement_id"], CLERK_HEADERS)
    )
    assert settlement["status"] == "APPEALED"
    assert settlement["stage"] == "FINAL"

    assert read_cost_report(api, scenario)["status"] == "FINAL_SETTLED"


def test_the_auditor_who_proposed_the_exception_may_not_resolve_it(api):
    """Both calls carry the auditor role, so the refusal turns on the user header
    alone, and the incorporation cascade never fires.

    PRD 2.1: "Finally, within the contractor's own staff, the auditor who proposed an audit adjustment may not resolve it; a resolution request whose `X-User-ID` equals the adjustment's `proposed_by_user_id` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    PRD 2.10: "7. **Segregation of duties** — on an audit adjustment resolution, `X-User-ID` differs from the adjustment's `proposed_by_user_id`, else `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Corner/rbac/the_auditor_who_proposed_an_adjustment_cannot_resolve_it
    """
    scenario = _final_settlement_with_a_proposed_adjustment(api)
    adjustment_id = scenario["adjustment_id"]
    proposer = make_mac_auditor_headers(AUDITOR_ONE_ID)
    peer = make_mac_auditor_headers(AUDITOR_TWO_ID)

    response = api.resolve_audit_adjustment(
        adjustment_id, audit_resolution_payload("INCORPORATE"), proposer
    )

    validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    reread = validate_success(api.get_audit_adjustment(adjustment_id, peer))
    assert reread["status"] == "PROPOSED"
    assert reread["proposed_by_user_id"] == AUDITOR_ONE_ID
    assert reread["resolved_by_user_id"] is None

    _entries, entries_meta = validate_paginated(
        api.list_audit_adjustment_workpaper_entries(adjustment_id, peer)
    )
    assert entries_meta["total_count"] == 0

    _proposed, proposed_meta = validate_paginated(
        api.list_audit_adjustments(
            peer,
            {"settlement_id": scenario["final_settlement_id"], "status": "PROPOSED"},
        )
    )
    assert proposed_meta["total_count"] == 1

    assert read_cost_report(api, scenario)["allocation_status"] == "CURRENT"
    settlement = validate_success(
        api.get_settlement(scenario["final_settlement_id"], peer)
    )
    assert settlement["recompute_required"] is False


def test_an_analyst_carrying_the_wrong_hospitals_identity_is_refused(api):
    """The role is right and the endpoint is the analyst's own, so the refusal is
    the scope violation and not a role complaint.

    PRD 2.1: "The header is optional for this role; when it is supplied, ownership checks on any target resource compare the `Provider` that ultimately owns that resource (a cost report's `provider_id`, a cost center's owning report, a resident's `provider_id`, and so on) against `X-User-ID`, and a mismatch is rejected with `ERR_PROVIDER_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/analyst_scoped_to_another_provider_is_rejected
    """
    set_clock(api)
    provider = create_provider(api)
    report = create_cost_report(api, provider["id"])
    other_provider = create_other_provider(api)

    response = api.create_cost_center(
        report["id"],
        general_service_center_payload(statistics={"SQUARE_FEET": 0}),
        make_reimbursement_analyst_headers(other_provider["id"]),
    )

    validate_error(response, ApiErrorId.ERR_PROVIDER_SCOPE_VIOLATION.value, 403)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value

    centers, meta = validate_paginated(
        api.list_report_cost_centers(
            report["id"], role_headers_for(provider["id"])["analyst"]
        )
    )
    assert meta["total_count"] == 0
    assert centers == []


def test_a_caller_with_no_role_header_is_not_any_role(api):
    """Authentication is decided first, so a read four of the five roles may perform
    answers 401 rather than the 403 or the 404 further down the ladder.

    PRD 2.1: "A request with no `X-User-Role` header, or with a value that is not one of the five recognized role names, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD 2.10: "1. **Authentication** — a recognized `X-User-Role` header is present, else `ERR_UNAUTHENTICATED` (401). Applies to every endpoint."

    Design: Corner/rbac/read_with_a_missing_auth_header_is_unauthenticated
    """
    scenario = new_scenario(api)

    response = api.get_cost_report(scenario["report_id"], no_auth_headers())

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_FORBIDDEN_ROLE.value
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_COST_REPORT_NOT_FOUND.value


def test_the_recompute_is_genuinely_shared_between_hospital_and_contractor(api):
    """The same care data set recomputes under the analyst and then under the
    auditor, both times to the same figures and neither time to a 403.

    PRD 2.1: "Analysts and auditors both may trigger a stepdown run and a recompute of the uncompensated care figures."

    PRD 3.7: "The data set's own `cost_to_charge_ratio` is a snapshot of the report's `cost_to_charge_ratio` taken at the moment of the compilation, held to six decimal places, and it reads 0.000000 until a stepdown run has completed."

    Design: Corner/rbac/the_shared_recompute_operation_works_for_the_analyst_and_the_auditor
    """
    scenario = setup_two_center_report(api)
    run_stepdown(api, scenario, "SINGLE_APPORTIONMENT")
    data_set = add_ucc_data_set(api, scenario)

    by_analyst = validate_success(
        api.recompute_ucc_data_set(data_set["id"], scenario["analyst"])
    )
    by_auditor = validate_success(
        api.recompute_ucc_data_set(
            data_set["id"], make_mac_auditor_headers(AUDITOR_TWO_ID)
        )
    )

    assert_money_equals(
        by_analyst["uncompensated_care_cost_cents"],
        36500000,
        "uncompensated_care_cost_cents",
    )
    assert_money_equals(
        by_auditor["uncompensated_care_cost_cents"],
        36500000,
        "uncompensated_care_cost_cents",
    )
    assert_money_equals(by_auditor["ucc_payment_cents"], 7300000, "ucc_payment_cents")
    assert_money_equals(
        by_analyst["ucc_payment_cents"], 7300000, "analyst ucc_payment_cents"
    )
    assert_ratio_equals(
        by_auditor["cost_to_charge_ratio"], 0.750000, "cost_to_charge_ratio"
    )
    assert by_auditor["recompute_required"] is False
    assert by_auditor["dsh_eligible"] is True
