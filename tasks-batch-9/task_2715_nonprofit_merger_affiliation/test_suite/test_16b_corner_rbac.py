"""Role-based access control compliance tests, second file.

Every test in this module builds its own preconditions through the API, because
the harness restarts the server and empties the database before each test.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ROLE_NOT_PERMITTED,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field,
    assert_seat_ledger_conserved,
    assert_version_is,
    find_by_id,
)
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    INTEGRATION_MANAGER,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)


def test_diligence_lead_cannot_clear_the_finding_it_raised(api):
    """The lead who raised a finding may neither clear nor waive it, both refusals answer
    ERR_SEGREGATION_OF_DUTIES and mutate nothing, and a second lead's clear closes diligence.

    PRD 3.4 says a finding lands "with raised_by_user_id set to the acting X-User-ID - the
    comparand for every later segregation-of-duties check on this row", that clearance
    requires "a DiligenceLead whose X-User-ID differs from the finding's raised_by_user_id"
    and "the same lead who raised it is refused with ERR_SEGREGATION_OF_DUTIES", and that
    waiving "carries the same independence control". PRD 2.7 rule 14 guards exactly clear,
    waive and certify, and a request refused by any validation "increments nothing and
    mutates nothing" (PRD 2.5). Clearance "records cleared_by_user_id as the acting user",
    and PRD 3.4 closes diligence when a deal in DILIGENCE has at least one finding and
    "every one of them is either CLEARED or WAIVED". Structure selection is
    StrategyOfficer-only per PRD 4, refused at rule 2 with ERR_ROLE_NOT_PERMITTED.

    Design: Corner/rbac/diligence_lead_cannot_clear_the_finding_it_raised
    """
    ctx = fx.setup_deal_diligence(api)
    org_a, deal = ctx["org_a"], ctx["deal"]
    finding = validate_success(
        api.create_diligence_request(
            f.diligence_request_payload(
                deal["id"],
                workstream="WORKFORCE",
                severity="HIGH",
                summary="Unfunded accrued leave liability",
                exposure_cents=4000000,
            ),
            DILIGENCE_LEAD,
        ),
        201,
    )
    responded = validate_success(
        api.respond_diligence_request(
            finding["id"],
            f.diligence_respond_payload(response_ref="RESP-0007"),
            make_strategy_officer_headers(org_a["id"]),
        )
    )
    responded_version = responded["version"]

    validate_error(
        api.clear_diligence_request(
            finding["id"], f.diligence_clear_payload(clearance_note="self-cleared"), DILIGENCE_LEAD
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api.waive_diligence_request(
            finding["id"], f.diligence_waive_payload(waiver_justification="self-waived"), DILIGENCE_LEAD
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api.select_structure(deal["id"], f.select_structure_payload(), DILIGENCE_LEAD),
        ERR_ROLE_NOT_PERMITTED,
    )

    rows, _meta = validate_paginated(api.list_deal_diligence_requests(deal["id"], PLATFORM_ADMIN))
    untouched = find_by_id(rows, finding["id"])
    assert_field(untouched, "status", "RESPONDED")
    assert_version_is(untouched, responded_version, "diligence request")

    cleared = validate_success(
        api.clear_diligence_request(
            finding["id"],
            f.diligence_clear_payload(clearance_note="Reviewed by the second lead against the leave schedule"),
            DILIGENCE_LEAD_2,
        )
    )
    assert_field(cleared, "status", "CLEARED")
    assert_field(cleared, "cleared_by_user_id", DILIGENCE_LEAD_2["X-User-ID"])
    assert_field(fx.read_deal(api, deal["id"]), "status", "DILIGENCE_CLOSED")


def test_certifying_secretary_must_not_be_the_recording_secretary(api):
    """Certification runs the two-signature control on the staff reference pair: an equal
    pair answers ERR_SEGREGATION_OF_DUTIES seat-neutrally on each approval row, and distinct
    references certify, allocate the seats and pin the evidentiary basis.

    PRD 3.5 says the certifying secretary supplies "a certifying_secretary_ref naming the
    secretary attesting to the minutes. That reference must differ from the resolution's
    stored recording_secretary_ref, and an equal pair is refused with
    ERR_SEGREGATION_OF_DUTIES", because "a secretary's X-User-ID is the party organization's
    own identifier" and "cannot by itself distinguish two staff members of that
    organization". PRD 2.5 adds that a refused request "increments nothing and mutates
    nothing". On success PRD 3.5 pins "composite_score and sequence_no from the deal's latest
    DILIGENCE_ADJUSTED alignment assessment into pinned_composite_score and
    pinned_assessment_sequence_no", writes the seats due (board_seat_split_initiator for the
    INITIATOR, combined_board_seats less that figure for the TARGET), and advances the deal
    BOARD_APPROVAL to REGULATORY_REVIEW once both parties are certified. PRD 3.2 gives that
    snapshot a sequence_no of "one plus the count of prior snapshots of the same deal and the
    same variant", so the deal's only diligence-adjusted snapshot is number 1, and PRD 2.8
    holds the seat ledger identity continuously.

    Design: Corner/rbac/certifying_secretary_must_not_be_the_recording_secretary
    """
    ctx = fx.setup_deal_board_approval(api)
    org_a, org_b, deal = ctx["org_a"], ctx["org_b"], ctx["deal"]
    ba_i, ba_t = ctx["approval_initiator"], ctx["approval_target"]
    sec_a = make_board_secretary_headers(org_a["id"])
    sec_b = make_board_secretary_headers(org_b["id"])

    validate_error(
        api.certify_board_approval(
            ba_i["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-1"),
            sec_a,
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )
    validate_error(
        api.certify_board_approval(
            ba_t["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-B-1", certifying_secretary_ref="SEC-B-1"),
            sec_b,
        ),
        ERR_SEGREGATION_OF_DUTIES,
    )

    rows, _meta = validate_paginated(api.list_deal_board_approvals(deal["id"], PLATFORM_ADMIN))
    for approval_id in (ba_i["id"], ba_t["id"]):
        row = find_by_id(rows, approval_id)
        assert_field(row, "status", "RECORDED")
        assert_field(row, "allocated_seats", 0)
    assert_field(fx.read_deal(api, deal["id"]), "reserved_seat_pool", 15)
    assert_field(validate_success(api.get_organization(org_a["id"], PLATFORM_ADMIN)), "governance_seats", 0)
    assert_field(validate_success(api.get_organization(org_b["id"], PLATFORM_ADMIN)), "governance_seats", 0)

    certified_i = validate_success(
        api.certify_board_approval(
            ba_i["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-A-1", certifying_secretary_ref="SEC-A-2"),
            sec_a,
        )
    )
    certified_t = validate_success(
        api.certify_board_approval(
            ba_t["id"],
            f.certify_payload(fiduciary_memo_ref="MEMO-B-1", certifying_secretary_ref="SEC-B-2"),
            sec_b,
        )
    )
    assert_field(certified_i, "allocated_seats", 8)
    assert_field(certified_t, "allocated_seats", 15 - 8)
    assert_decimal_equals(certified_i["pinned_composite_score"], 60.00, 2, "pinned_composite_score")
    assert_field(certified_i, "pinned_assessment_sequence_no", 1)

    dossier = fx.dossier(api, deal["id"])
    assert_field(dossier, "reserved_seat_pool", 0)
    assert_seat_ledger_conserved(dossier)
    assert_field(fx.read_deal(api, deal["id"]), "status", "REGULATORY_REVIEW")


def test_counsel_and_regulator_are_barred_from_each_others_side_of_the_filing_desk(api):
    """Counsel owns the fund branches and the filing while the regulator owns nothing but the
    decision, and the regulator's five shared reads never imply a write.

    PRD 4 gives POST /restricted-funds/{id}/seek-consent and POST /ag-filings to the
    CharitableTrustCounsel, POST /restricted-funds to PlatformAdmin and CharitableTrustCounsel
    only, and POST /ag-filings/{id}/decision to the StateCharitiesRegulator alone, while
    GET /restructurings/{id}/ag-filings is readable by PlatformAdmin, StrategyOfficer,
    CharitableTrustCounsel and StateCharitiesRegulator. PRD 2.7 rule 2 refuses a caller whose
    role is not listed for the endpoint with ERR_ROLE_NOT_PERMITTED, and PRD 2.5 says such a
    request "increments nothing and mutates nothing". PRD 3.6 moves a solicited fund
    "HELD to CONSENT_SOUGHT". PRD 3.7 says "Only the StateCharitiesRegulator may answer, never
    the counsel who filed", that "decision_recorded_at is stamped from the logical clock", and
    that "An approval moves the filing SUBMITTED to APPROVED and releases the deal
    REGULATORY_REVIEW to INTEGRATION". PRD 2.4 makes that instant the startup default clock
    value rendered with three fractional digits.

    Design: Corner/rbac/counsel_and_regulator_are_barred_from_each_others_side_of_the_filing_desk
    """
    ctx = fx.setup_deal_regulatory_review(api)
    org_a, deal = ctx["org_a"], ctx["deal"]
    fund = fx.create_fund(api, org_a["id"])
    filing = validate_success(
        api.create_ag_filing(
            f.ag_filing_payload(deal["id"], state_code="CA", filing_type="NOTICE", legal_costs_cents=1000000),
            TRUST_COUNSEL,
        ),
        201,
    )

    solicited = validate_success(
        api.seek_consent(fund["id"], f.seek_consent_payload(consent_method="WRITTEN"), TRUST_COUNSEL)
    )
    assert_field(solicited, "transfer_status", "CONSENT_SOUGHT")

    validate_error(
        api.record_ag_decision(filing["id"], f.ag_decision_payload("APPROVED"), TRUST_COUNSEL),
        ERR_ROLE_NOT_PERMITTED,
    )
    rows, _meta = validate_paginated(api.list_deal_ag_filings(deal["id"], CHARITIES_REGULATOR))
    assert len(rows) == 1, f"the deal holds exactly one filing, got {len(rows)}"
    assert_field(find_by_id(rows, filing["id"]), "status", "SUBMITTED")

    validate_error(
        api.create_ag_filing(
            f.ag_filing_payload(deal["id"], state_code="CA", filing_type="NOTICE", legal_costs_cents=1000000),
            CHARITIES_REGULATOR,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.create_restricted_fund(
            f.restricted_fund_payload(
                org_a["id"],
                fund_name="Regulator Invented Fund",
                principal_cents=1000000,
                accumulated_appreciation_cents=0,
            ),
            CHARITIES_REGULATOR,
        ),
        ERR_ROLE_NOT_PERMITTED,
    )

    decided = validate_success(
        api.record_ag_decision(filing["id"], f.ag_decision_payload("APPROVED"), CHARITIES_REGULATOR)
    )
    assert_field(decided, "status", "APPROVED")
    assert_field(decided, "decision_recorded_at", "2026-08-01T00:00:00.000Z")
    assert_field(fx.read_deal(api, deal["id"]), "status", "INTEGRATION")


def test_integration_manager_owns_the_task_board_and_the_continuity_decision(api):
    """The IntegrationManager may register a program, dispose of one and plan a task from
    STRUCTURE_SELECTED onwards, while the initiator's officer may not plan the task, the
    PlatformAdmin may not dispose of a program and the manager may not close the deal.

    PRD 4 lists POST /programs for PlatformAdmin, StrategyOfficer and IntegrationManager, gives
    POST /programs/{id}/continuity-decision and POST /integration-tasks to the
    IntegrationManager alone, shares GET /integration-tasks with PlatformAdmin and
    StrategyOfficer, and reserves POST /restructurings/{id}/consummate for the StrategyOfficer.
    PRD 2.7 refuses an unlisted role at rule 2 with ERR_ROLE_NOT_PERMITTED, ahead of the deal
    state check at rule 16, and PRD 2.5 says a refused request "increments nothing and mutates
    nothing". PRD 3.8 says "A TRANSFER disposition moves the program ACTIVE to
    PLANNED_TRANSFER", that a new program starts with "continuity_status is ACTIVE", and that
    every workstream and posture combination other than PROGRAM_CONTINUITY against a
    RESTRICTED_PENDING or BLOCKED posture "creates the task in PLANNED with held_reason null" -
    this deal holds no restricted fund, so its posture is NOT_ASSESSED. PRD 3.8 also admits
    integration planning from STRUCTURE_SELECTED onwards, while consummation requires
    INTEGRATION.

    Design: Corner/rbac/integration_manager_owns_the_task_board_and_the_continuity_decision
    """
    ctx = fx.setup_deal_structure_selected(api)
    org_a, org_b, deal = ctx["org_a"], ctx["org_b"], ctx["deal"]
    prog_a = fx.create_program(api, org_a["id"], name="Riverside Mentor Match", clients_served=240)

    prog_b = validate_success(
        api.create_program(
            f.program_payload(
                org_b["id"],
                name="Harbor Peer Navigators",
                annual_expense_cents=5000000,
                clients_served=130,
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )
    decided = validate_success(
        api.continuity_decision(
            prog_a["id"],
            f.continuity_decision_payload(deal["id"], disposition="TRANSFER"),
            INTEGRATION_MANAGER,
        )
    )
    assert_field(decided, "continuity_status", "PLANNED_TRANSFER")

    task = validate_success(
        api.create_integration_task(
            f.integration_task_payload(
                deal["id"],
                workstream="BRANDING",
                crew_code="CREW-A1",
                title="Unified letterhead rollout",
            ),
            INTEGRATION_MANAGER,
        ),
        201,
    )
    assert_field(task, "status", "PLANNED")
    assert_field(task, "held_reason", None)
    rows, _meta = validate_paginated(
        api.list_integration_tasks(INTEGRATION_MANAGER, {"restructuring_id": deal["id"]})
    )
    assert len(rows) == 1, f"the deal holds exactly one planned task, got {len(rows)}"

    validate_error(
        api.create_integration_task(
            f.integration_task_payload(deal["id"], crew_code="CREW-D1", title="Officer planned task"),
            make_strategy_officer_headers(org_a["id"]),
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.continuity_decision(
            prog_b["id"], f.continuity_decision_payload(deal["id"], disposition="SUNSET"), PLATFORM_ADMIN
        ),
        ERR_ROLE_NOT_PERMITTED,
    )
    validate_error(
        api.consummate(deal["id"], f.consummate_payload(closing_memo_ref="CLOSE-8888"), INTEGRATION_MANAGER),
        ERR_ROLE_NOT_PERMITTED,
    )

    programs, _pmeta = validate_paginated(
        api.list_organization_programs(org_b["id"], PLATFORM_ADMIN)
    )
    assert_field(find_by_id(programs, prog_b["id"]), "continuity_status", "ACTIVE")
    rows_after, _meta_after = validate_paginated(
        api.list_integration_tasks(INTEGRATION_MANAGER, {"restructuring_id": deal["id"]})
    )
    assert len(rows_after) == 1, f"the refusals created no task, got {len(rows_after)}"
