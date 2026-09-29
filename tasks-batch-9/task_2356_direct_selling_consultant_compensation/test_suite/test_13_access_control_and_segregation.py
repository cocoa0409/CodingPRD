"""Who may act: the exclusive operations no other role can borrow, the reads every listed role
shares, and the approval that one human may not give himself."""

from test_helpers import (
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    make_consultant_headers,
    make_headers,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CONTROLLER = TEST_USERS["finance_controller_headers"]
LEGAL = TEST_USERS["legal_reviewer_headers"]
APPLICANT = TEST_USERS["applicant_headers"]

# The role check short-circuits ahead of path resolution, so an identifier that resolves to
# nothing is enough to ask "may this role call this operation at all?".
MISSING_ID = "00000000-0000-0000-0000-000000000000"


def test_the_enrollment_and_discipline_operations_refuse_every_role_but_their_owner(api):
    """A PlatformAdmin may not sign an agreement, verify an identity, approve an application or
    reinstate a consultant; a ComplianceOfficer may not grant a rank; and neither may stand in for
    the consultant who appeals.

    PRD: "A `ComplianceOfficer` owns identity decisions, enrollment approval, the disciplinary
    process and reinstatement, but never touches money."

    PRD: "Accepting the consultant agreement is the one enrollment act a `PlatformAdmin` cannot
    perform on an applicant's behalf, because acceptance is a personal legal act reserved to
    `Applicant`; filing an appeal against a sanction is likewise reserved to `Consultant`."

    PRD: "**Role permitted** — `X-User-Role` is one of the seven roles and appears in the endpoint's
    authorised list, or `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/no_role_including_platform_admin_can_borrow_another_roles_exclusive_operation
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Root")

    validate_error(
        api.accept_agreement(MISSING_ID, f.accept_agreement_payload(), ADMIN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.decide_identity(MISSING_ID, f.identity_decision_payload("VERIFY"), ADMIN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.approve_enrollment_application(MISSING_ID, None, ADMIN), "ERR_UNAUTHORIZED", 403
    )
    validate_error(
        api.reinstate_consultant(ann["id"], f.reinstatement_payload("welcome back"), ADMIN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.adjust_consultant_rank(
            ann["id"], f.rank_adjustment_payload("DIRECTOR"), COMPLIANCE
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.create_compliance_case(
            f.compliance_case_payload(ann["id"], "INCOME_CLAIM", "EV-1"), ADMIN
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.appeal_compliance_case(MISSING_ID, f.appeal_payload("Unfair"), COMPLIANCE),
        "ERR_UNAUTHORIZED",
        403,
    )

    untouched = fx.read_consultant(api, ann["id"])
    assert untouched["status"] == "ACTIVE", "none of the refused calls moved the consultant"
    assert untouched["rank_code"] == "CONSULTANT", "the rank the officer tried to grant is not there"
    assert untouched["open_case_count"] == 0, "and the case the administrator tried to open is not"
    assert untouched["reinstatement_count"] == 0, "nor was anything reinstated"


def test_the_money_pipeline_refuses_the_administrator_the_analyst_and_the_controller_in_turn(api):
    """The period, the run, the disclosure, the warehouse and the clock each answer to exactly one
    role, and the administrator excluded from the money path is refused four times over.

    PRD: "A `PlatformAdmin` configures plans, jurisdictions, products and periods, mints genealogy
    roots, adjusts ranks administratively, reopens closed periods, drives fulfillment and sets the
    logical clock, and is deliberately excluded from the money path: an administrator may not
    calculate, approve, pay or reverse a run, may not decide a compliance case, and may not publish
    a disclosure."

    PRD: "A `CommissionAnalyst` runs the qualification and commission cycle and prepares disclosures
    but can neither approve nor pay a run nor publish a disclosure."

    PRD: "The first rule a request violates decides the response, the request short-circuits at that
    point, and nothing at all is written — not even the parts of the operation that would have
    succeeded."

    Design: Corner/rbac/no_role_including_platform_admin_can_borrow_another_roles_exclusive_operation
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Root")
    period = env["periods"]["2026-08"]

    validate_error(api.lock_qualification_period(period["id"], None, ADMIN), "ERR_UNAUTHORIZED", 403)
    validate_error(
        api.reopen_qualification_period(period["id"], f.reopen_payload("Late volume"), ANALYST),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.calculate_commission_run(MISSING_ID, None, CONTROLLER), "ERR_UNAUTHORIZED", 403
    )
    validate_error(
        api.decide_commission_run_approval(
            MISSING_ID, f.approval_decision_payload("APPROVE"), ANALYST
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.reverse_commission_run(MISSING_ID, f.reversal_payload("wrong period"), ADMIN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.decide_disclosure_legal_review(MISSING_ID, f.legal_decision_payload("PUBLISH"), ADMIN),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.advance_fulfillment(
            MISSING_ID, f.fulfillment_payload("SHIP"), make_consultant_headers(ann["id"])
        ),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(
        api.set_clock(f.clock_payload("2027-01-01T00:00:00Z"), ANALYST), "ERR_UNAUTHORIZED", 403
    )
    validate_error(
        api.decide_buyback_request(MISSING_ID, f.buyback_decision_payload("APPROVE"), COMPLIANCE),
        "ERR_UNAUTHORIZED",
        403,
    )

    assert fx.read_period(api, period["id"])["status"] == "OPEN", (
        "the period the administrator tried to lock never left OPEN"
    )
    assert_instant(fx.read_clock(api)["current_utc"], k.INITIAL_CLOCK, "current_utc")


def test_five_roles_read_the_same_consultant_list_and_a_prospect_reads_the_catalogue(api):
    """The shared reads are genuinely shared: five operator roles and the consultant herself see one
    and the same row, and an Applicant who owns nothing may still browse products and tax rates.

    PRD: "When `X-User-Role` is `ComplianceOfficer`, `CommissionAnalyst`, `FinanceController`,
    `LegalReviewer` or `PlatformAdmin`, the server may record `X-User-ID` on a resource as an audit
    trail — as `reviewed_by_user_id` on a compliance case, `calculated_by_user_id` and
    `approved_by_user_id` on a commission run, `decided_by_user_id` on a buyback request, and
    `submitted_by_user_id` and `legal_reviewer_user_id` on an income disclosure statement — but it
    never compares that value to any entity's `id`, and no ownership filter applies to those roles."

    PRD: "**Row ownership** — for endpoints whose authorised roles include `Consultant` or
    `Applicant`, the acting caller owns the addressed resource, or `ERR_FORBIDDEN_RESOURCE`."

    Design: Corner/rbac/shared_reads_work_for_every_listed_role_and_only_for_them
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Root")
    active = {"status": "ACTIVE"}

    readers = {
        "ComplianceOfficer": COMPLIANCE,
        "CommissionAnalyst": ANALYST,
        "FinanceController": CONTROLLER,
        "LegalReviewer": LEGAL,
        "PlatformAdmin": ADMIN,
        "Consultant": make_consultant_headers(ann["id"]),
    }
    for role, headers in readers.items():
        rows = validate_success(api.list_consultants(headers, params=active))
        assert [row["id"] for row in rows] == [ann["id"]], (
            f"{role} reads the shared consultant list and sees the one active consultant"
        )

    kits = validate_success(api.list_products(APPLICANT, params={"is_starter_kit": True}))
    assert [row["sku"] for row in kits] == ["KIT-STD"], (
        "a prospect may price the starter kit before committing to enroll"
    )
    jurisdictions = validate_success(api.list_tax_jurisdictions(APPLICANT))
    assert [row["state_code"] for row in jurisdictions] == ["TX"], (
        "and may read the tax table that will decide what the kit costs her"
    )


def test_the_analyst_who_computes_the_money_may_not_read_the_disciplinary_collections(api):
    """Compliance cases and buyback requests are closed collections: the CommissionAnalyst is absent
    from both authorisation lists and is refused before any filter is applied.

    PRD: "If `X-User-Role` is not one of those seven, or is one of them but is not authorised for the
    endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/shared_reads_work_for_every_listed_role_and_only_for_them
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Root")
    case = fx.open_case(api, ann, claim_type="INCOME_CLAIM", evidence_reference="EV-1")

    validate_error(api.list_compliance_cases(ANALYST), "ERR_UNAUTHORIZED", 403)
    validate_error(
        api.list_compliance_cases(ANALYST, params={"consultant_id": ann["id"]}),
        "ERR_UNAUTHORIZED",
        403,
    )
    validate_error(api.get_compliance_case(case["id"], ANALYST), "ERR_UNAUTHORIZED", 403)
    validate_error(api.list_buyback_requests(ANALYST), "ERR_UNAUTHORIZED", 403)

    visible = validate_success(api.list_compliance_cases(COMPLIANCE))
    assert [row["id"] for row in visible] == [case["id"]], (
        "the officer who owns the disciplinary process reads the very row the analyst cannot"
    )


def test_the_controller_who_calculated_the_run_cannot_be_the_controller_who_approves_it(api):
    """The approval guard compares user identifiers, not roles: the analyst's own identifier wearing
    a controller's role is refused, and the identical request from a second human approves the run.

    PRD: "The controller taking an approval decision on a commission run must present an
    `X-User-ID` different from the run's `calculated_by_user_id`."

    PRD: "The check bites even though no single role can perform both halves, because the same human
    may hold two role headers under one `X-User-ID`."

    PRD: "`APPROVE` drives `CALCULATED → APPROVED`, records `approved_by_user_id`, and sets every
    `ACTIVE` statement's `payout_status` to `PAYABLE`."

    Design: Corner/rbac/the_same_human_cannot_calculate_and_then_approve_a_run
    """
    state = fx.setup_single_earner_closed_period(
        api, pairs=(("SAMPLE", 99),), order_type="PERSONAL_INVENTORY"
    )
    run = fx.calculate_run(api, fx.create_run(api, state["period"]))
    assert run["status"] == "CALCULATED", "the analyst has prepared the figures"
    assert run["calculated_by_user_id"] == k.ANALYST_USER_ID, "and is on record as their author"
    assert run["statement_count"] == 1, "one statement is waiting for a blessing"
    pending = fx.statement_of(api, run["id"], state["a"]["id"], headers=ANALYST)
    assert pending["payout_status"] == "PENDING", "which has not yet been made payable"

    validate_error(
        api.decide_commission_run_approval(
            run["id"],
            f.approval_decision_payload("APPROVE"),
            make_headers(k.ANALYST_USER_ID, "FinanceController"),
        ),
        "ERR_SEGREGATION_OF_DUTIES",
        409,
    )
    still_calculated = validate_success(api.get_commission_run(run["id"], CONTROLLER))
    assert still_calculated["status"] == "CALCULATED", "the collision approved nothing"
    assert still_calculated["approved_by_user_id"] is None, "and recorded no approver"

    approved = validate_success(
        api.decide_commission_run_approval(
            run["id"], f.approval_decision_payload("APPROVE"), CONTROLLER
        )
    )
    assert approved["status"] == "APPROVED", "the identical request from a second human is accepted"
    assert approved["approved_by_user_id"] == k.CONTROLLER_USER_ID, "the approver is recorded"
    assert approved["calculated_by_user_id"] == k.ANALYST_USER_ID, (
        "beside the different identifier that calculated it"
    )
    payable = fx.statement_of(api, run["id"], state["a"]["id"], headers=CONTROLLER)
    assert payable["payout_status"] == "PAYABLE", (
        "so the segregation check was gating a real money effect"
    )
