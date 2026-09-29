"""Individual gauntlet checks and the exact instants and amounts at which they bite.

Each test probes one boundary from both sides where the rule has two sides, and
asserts the single error identifier the ordered gauntlet must produce.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers.assertions import assert_empty, assert_fields, assert_reason_codes, bps_of, ratio_bps
from test_helpers.test_users import ADMIN_HEADERS, AGENT_HEADERS, merchant_headers

UNKNOWN_PROJECT_ID = "11111111-1111-4111-8111-111111111111"
UNKNOWN_MERCHANT_ID = "88888888-8888-4888-8888-888888888888"


# ─── Module-private builders ──────────────

def _ticket_application(api, scenario, ticket_cents, ssn_last4):
    """File one application for the given ticket against a freshly registered homeowner."""
    consumer = S.register_consumer(api, scenario.merchant_id, ssn_last4=ssn_last4)
    return api.create_credit_application(
        F.credit_application_payload(
            scenario.merchant_id,
            consumer["id"],
            scenario.plan_id,
            project_amount_cents=ticket_cents,
        ),
        scenario.as_merchant,
    )


def _second_project(api, scenario, contract_amount_cents):
    """Open a second application, loan and project for the same homeowner, and return both ids."""
    application = get_success_data(
        api.create_credit_application(
            F.credit_application_payload(
                scenario.merchant_id,
                scenario.consumer_id,
                scenario.plan_id,
                project_amount_cents=contract_amount_cents,
            ),
            scenario.as_merchant,
        )
    )
    get_success_data(
        api.deliver_disclosure(
            application["id"], F.disclosure_delivery_payload(), scenario.as_merchant
        )
    )
    get_success_data(
        api.acknowledge_disclosure(
            application["id"], F.disclosure_acknowledgement_payload(), scenario.as_consumer
        )
    )
    loan = get_success_data(
        api.accept_offer(application["id"], F.acceptance_payload(), scenario.as_consumer)
    )
    project = get_success_data(
        api.create_project(
            F.project_payload(
                application["id"],
                contract_amount_cents=contract_amount_cents,
                scope_description="Second-storey deck rebuild",
            ),
            scenario.as_merchant,
        )
    )
    return loan["id"], project["id"]


def _disputed_project(api):
    """A 1000000-cent project with 300000 cents settled and one open dispute case."""
    scenario = S.settled_draw(
        api,
        amount_cents=300000,
        releases=(3000, 7000),
        verify=(0,),
        contract_amount_cents=1000000,
        ticket_cents=1000000,
    )
    case = S.file_dispute(api, scenario, 100000)
    return scenario, case


# ─── Ticket-band violations return their declared fiscal errors ──────────────

def test_a_ticket_one_cent_under_the_plan_minimum_is_refused(api):
    """99999 cents against a 100000-cent plan minimum is rejected and no application is written.

    PRD: "The requested `project_amount_cents` must be at least the plan's `min_ticket_cents`, otherwise `ERR_TICKET_BELOW_MINIMUM`."

    Design: Corner/validations/ticket_band_violations_return_their_declared_fiscal_errors
    """
    scenario = S.enrolled_merchant(api)

    response = _ticket_application(api, scenario, C.DEFERRED_INTEREST_PLAN["min_ticket_cents"] - 1, "3001")
    validate_error(response, E.ERR_TICKET_BELOW_MINIMUM)

    listing = api.list_credit_applications(ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


def test_a_ticket_one_cent_over_the_binding_maximum_is_refused(api):
    """5000001 cents exceeds the lower of the plan and trade-rule ceilings and is rejected.

    PRD: "The requested `project_amount_cents` must not exceed the lower of the plan's `max_ticket_cents` and the governing trade rule's `max_ticket_cents`, otherwise `ERR_TICKET_LIMIT_EXCEEDED`."

    Design: Corner/validations/ticket_band_violations_return_their_declared_fiscal_errors
    """
    scenario = S.enrolled_merchant(api)

    binding_max = min(
        C.DEFERRED_INTEREST_PLAN["max_ticket_cents"], C.ROOFING_TRADE_RULE["max_ticket_cents"]
    )
    assert binding_max == 5000000
    response = _ticket_application(api, scenario, binding_max + 1, "3002")
    validate_error(response, E.ERR_TICKET_LIMIT_EXCEEDED)

    listing = api.list_credit_applications(ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


# ─── Both ticket-band edges are inclusive and underwrite ──────────────

def test_a_ticket_exactly_at_the_plan_minimum_is_underwritten(api):
    """100000 cents sits on the inclusive lower edge and is approved on its merits.

    PRD: "The requested `project_amount_cents` must be at least the plan's `min_ticket_cents`, otherwise `ERR_TICKET_BELOW_MINIMUM`."

    Design: Corner/validations/ticket_band_endpoints_pass_at_both_inclusive_edges
    """
    scenario = S.enrolled_merchant(api)

    response = _ticket_application(api, scenario, 100000, "3003")
    data = validate_success(response, 201)

    # 100000 * 10000 / 9600000 = 104.16... -> 104, far under the 4500 bps ceiling
    assert_fields(
        data,
        project_amount_cents=100000,
        decision="APPROVED",
        decision_dti_bps=ratio_bps(100000, C.CANONICAL_CONSUMER["annual_income_cents"]),
        approved_limit_cents=C.CANONICAL_APPROVED_LIMIT_CENTS,
    )
    assert data["decision_dti_bps"] == 104
    assert_reason_codes(data, "WITHIN_LIMIT")


def test_a_ticket_exactly_at_the_binding_maximum_is_underwritten_and_declined_on_ratio(api):
    """5000000 cents clears the ticket band and is then declined by the debt-to-income ceiling.

    PRD: "If that figure is strictly greater than four thousand five hundred basis points, the application is declined: `decision` becomes `DECLINED`, `approved_limit_cents` stays at zero and `decision_reason_codes` is written as the single code `DTI_ABOVE_CEILING`."

    Design: Corner/validations/ticket_band_endpoints_pass_at_both_inclusive_edges
    """
    scenario = S.enrolled_merchant(api)

    response = _ticket_application(api, scenario, 5000000, "3004")
    data = validate_success(response, 201)

    # 5000000 * 10000 / 9600000 = 5208.33... -> 5208 > 4500
    assert_fields(
        data,
        project_amount_cents=5000000,
        decision="DECLINED",
        decision_dti_bps=ratio_bps(5000000, C.CANONICAL_CONSUMER["annual_income_cents"]),
        approved_limit_cents=0,
    )
    assert data["decision_dti_bps"] == 5208
    assert_reason_codes(data, "DTI_ABOVE_CEILING")


# ─── The role band decides before the schema band ──────────────

def test_a_forbidden_role_is_refused_before_its_malformed_body_is_examined(api):
    """A ServicingAgent posting a trade rule without `max_ticket_cents` is refused for its role.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Corner/validations/role_band_rejects_before_the_schema_band
    """
    response = api.create_trade_rule(F.trade_rule_payload(max_ticket_cents=None), AGENT_HEADERS)
    validate_error(response, E.ERR_ROLE_NOT_PERMITTED)

    listing = api.list_trade_rules(ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


def test_a_permitted_role_then_meets_the_schema_band_on_the_same_body(api):
    """The identical body from a ProgramAdmin gets past the role band and fails on its shape.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Corner/validations/role_band_rejects_before_the_schema_band
    """
    response = api.create_trade_rule(F.trade_rule_payload(max_ticket_cents=None), ADMIN_HEADERS)
    validate_error(response, E.ERR_INVALID_REQUEST)

    listing = api.list_trade_rules(ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


# ─── The schema band decides before path existence ──────────────

def test_a_malformed_body_is_refused_before_the_unknown_project_in_the_path(api):
    """A milestone body missing `release_pct_bps` fails on shape even though the project is fictional.

    PRD: "The first check whose condition is violated wins: the request is rejected with that check's error identifier and status, no later check runs, and no side effect of any kind is written."

    Design: Corner/validations/schema_band_rejects_before_the_path_existence_band
    """
    response = api.create_milestone(
        UNKNOWN_PROJECT_ID,
        F.milestone_payload(release_pct_bps=None),
        merchant_headers(UNKNOWN_MERCHANT_ID),
    )
    validate_error(response, E.ERR_INVALID_REQUEST)


def test_a_repaired_body_then_fails_on_the_unresolved_path_identifier(api):
    """With the body legal, the fictional project in the path decides before the unknown caller does.

    PRD: "Identifiers are resolved strictly left to right, and the request fails on the first identifier that does not resolve, with the not-found code belonging to that identifier rather than to any identifier further right."

    Design: Corner/validations/schema_band_rejects_before_the_path_existence_band
    """
    response = api.create_milestone(
        UNKNOWN_PROJECT_ID,
        F.milestone_payload(),
        merchant_headers(UNKNOWN_MERCHANT_ID),
    )
    validate_error(response, E.ERR_PROJECT_NOT_FOUND)


# ─── Dispute coherence is checked before the fiscal claim ──────────────

def test_a_case_naming_another_projects_loan_is_refused_for_incoherence(api):
    """Pairing loan A with project B fails on cross-aggregate coherence, not on the claim size.

    PRD: "Cross-aggregate coherence of a dispute: the `loan_account_id` recorded on the disputed project must equal the `loan_account_id` on the case, otherwise `ERR_DISPUTE_PROJECT_MISMATCH`."

    Design: Corner/validations/dispute_project_mismatch_is_rejected_before_the_fiscal_claim_check
    """
    scenario = S.project(api, contract_amount_cents=1000000, ticket_cents=1000000)
    _, project_b_id = _second_project(api, scenario, 1000000)

    response = api.create_dispute_case(
        F.dispute_case_payload(scenario.loan_id, project_b_id, 1), scenario.as_consumer
    )
    validate_error(response, E.ERR_DISPUTE_PROJECT_MISMATCH)

    listing = api.list_dispute_cases(ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


def test_a_coherent_case_over_unfunded_work_is_refused_for_the_claim_size(api):
    """With the pair coherent, a one-cent claim against zero settled funding is the next failure.

    PRD: "A dispute's `claimed_incomplete_amount_cents` must not exceed the project's `settled_funded_cents`, because a consumer cannot dispute money the program never advanced; a larger claim is `ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED`."

    Design: Corner/validations/dispute_project_mismatch_is_rejected_before_the_fiscal_claim_check
    """
    scenario = S.project(api, contract_amount_cents=1000000, ticket_cents=1000000)
    _second_project(api, scenario, 1000000)

    assert_fields(S.read_project(api, scenario.project_id), settled_funded_cents=0)
    response = api.create_dispute_case(
        F.dispute_case_payload(scenario.loan_id, scenario.project_id, 1), scenario.as_consumer
    )
    validate_error(response, E.ERR_DISPUTE_CLAIM_EXCEEDS_FUNDED)

    listing = api.list_dispute_cases(ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 0


# ─── The merchant response window closes exactly at response_due_at ──────────────

def test_filing_sets_the_response_clock_ten_days_out_at_midnight(api):
    """A case opened on 2026-08-01 is due at midnight UTC on 2026-08-11.

    PRD: "Filing stamps `opened_on` with the clock date and computes `response_due_at` as midnight UTC on the tenth day after `opened_on`, giving the contractor a ten-day response clock."

    Design: Corner/validations/merchant_response_window_closes_exactly_at_response_due_at
    """
    _, case = _disputed_project(api)

    assert_fields(case, opened_on=C.DEFAULT_CLOCK_DATE, status="MERCHANT_RESPONSE_PENDING")
    assert case["response_due_at"].replace(".000Z", "Z") == "2026-08-11T00:00:00Z"
    assert_empty(case, "merchant_responded_at", "response_type", "evidence_ref")


def test_a_response_one_day_before_the_deadline_is_accepted(api):
    """A response posted on 2026-08-10 arrives strictly before the deadline and is recorded.

    PRD: "A valid response stamps `merchant_responded_at` from the logical clock."

    Design: Corner/validations/merchant_response_window_closes_exactly_at_response_due_at
    """
    scenario, case = _disputed_project(api)

    S.set_clock(api, "2026-08-10T00:00:00Z")
    data = validate_success(
        api.respond_to_dispute(
            case["id"],
            F.merchant_response_payload("WORK_COMPLETE_EVIDENCE", evidence_ref="SIGNED-COC-A"),
            scenario.as_merchant,
        )
    )

    assert_fields(data, response_type="WORK_COMPLETE_EVIDENCE", evidence_ref="SIGNED-COC-A")
    assert data["merchant_responded_at"].replace(".000Z", "Z") == "2026-08-10T00:00:00Z"


def test_a_response_at_the_deadline_instant_is_refused(api):
    """A response posted at exactly 2026-08-11T00:00:00Z is too late and changes nothing.

    PRD: "A merchant response must arrive strictly before `response_due_at`; a response at that instant or later is `ERR_RESPONSE_WINDOW_CLOSED`."

    Design: Corner/validations/merchant_response_window_closes_exactly_at_response_due_at
    """
    scenario, case = _disputed_project(api)

    S.set_clock(api, "2026-08-11T00:00:00Z")
    response = api.respond_to_dispute(
        case["id"],
        F.merchant_response_payload("WORK_COMPLETE_EVIDENCE", evidence_ref="SIGNED-COC-B"),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_RESPONSE_WINDOW_CLOSED)

    unchanged = S.read_dispute(api, case["id"])
    assert_fields(unchanged, status="MERCHANT_RESPONSE_PENDING")
    assert_empty(unchanged, "merchant_responded_at", "response_type", "evidence_ref")


# ─── The milestone release budget is an aggregate ceiling ──────────────

def test_milestone_shares_summing_to_exactly_the_budget_are_accepted(api):
    """3000 plus 4000 plus 3000 lands exactly on ten thousand basis points and is allowed.

    PRD: "The sum of `release_pct_bps` across a project's milestones may not exceed ten thousand basis points; each individual milestone may be legal while the collection is not. Breaching the aggregate is `ERR_MILESTONE_RELEASE_TOTAL_EXCEEDED`."

    Design: Corner/validations/milestone_release_total_is_an_aggregate_ceiling
    """
    scenario = S.project(api)
    S.add_milestones(api, scenario, (3000, 4000, 3000))

    assert sum(m["release_pct_bps"] for m in scenario.milestones) == C.MILESTONE_RELEASE_BUDGET_BPS
    listing = api.list_milestones(scenario.project_id, ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 3
    assert_fields(S.read_project(api, scenario.project_id), verified_release_bps=0)


def test_one_basis_point_over_the_budget_is_refused_though_the_milestone_is_legal(api):
    """A fourth milestone of a single basis point is individually valid but breaches the collection.

    PRD: "The sum of `release_pct_bps` across a project's milestones may not exceed ten thousand basis points; each individual milestone may be legal while the collection is not. Breaching the aggregate is `ERR_MILESTONE_RELEASE_TOTAL_EXCEEDED`."

    Design: Corner/validations/milestone_release_total_is_an_aggregate_ceiling
    """
    scenario = S.project(api)
    S.add_milestones(api, scenario, (3000, 4000, 3000))

    response = api.create_milestone(
        scenario.project_id,
        F.milestone_payload(sequence_no=4, name="Punch list", release_pct_bps=1),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_MILESTONE_RELEASE_TOTAL_EXCEEDED)

    listing = api.list_milestones(scenario.project_id, ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 3


def test_a_duplicate_sequence_number_is_reported_before_the_aggregate_breach(api):
    """A fourth milestone reusing sequence 3 fails on uniqueness even though it also busts the budget.

    PRD: "A milestone's `sequence_no` must be unique within its project, otherwise `ERR_DUPLICATE_MILESTONE_SEQUENCE`."

    Design: Corner/validations/milestone_release_total_is_an_aggregate_ceiling
    """
    scenario = S.project(api)
    S.add_milestones(api, scenario, (3000, 4000, 3000))

    response = api.create_milestone(
        scenario.project_id,
        F.milestone_payload(sequence_no=3, name="Punch list", release_pct_bps=1),
        scenario.as_merchant,
    )
    validate_error(response, E.ERR_DUPLICATE_MILESTONE_SEQUENCE)

    listing = api.list_milestones(scenario.project_id, ADMIN_HEADERS)
    validate_success(listing)
    assert listing.json()["meta"]["total_count"] == 3


# ─── The completion certificate gate follows the trade rule's flag ──────────────

def test_a_pending_milestone_blocks_certification_when_the_trade_demands_a_certificate(api):
    """With the roofing flag true, one PENDING milestone refuses certification and changes nothing.

    PRD: "The requirements beyond that depend on the governing trade rule's `requires_completion_certificate` flag, and the two branches are genuinely different: when the flag is true, the supplied `completion_certificate_ref` must be non-empty **and** every milestone of the project must stand at `CLAIMED` or `VERIFIED`, with no milestone left at `PENDING` and none left at `REJECTED`, with either failure reported as `ERR_COMPLETION_CERTIFICATE_REQUIRED`; when the flag is false, neither clause is enforced and certification succeeds even with `PENDING` milestones still outstanding."

    Design: Corner/validations/completion_certificate_gate_applies_only_when_the_trade_rule_demands_it
    """
    scenario = S.project_with_milestones(api, releases=(3000, 4000), verify=(0,))
    assert scenario.trade_rule["requires_completion_certificate"] is True

    response = api.certify_completion(
        scenario.project_id,
        F.completion_certification_payload(completion_certificate_ref="COC-ROOF-1"),
        scenario.as_consumer,
    )
    validate_error(response, E.ERR_COMPLETION_CERTIFICATE_REQUIRED)

    project = S.read_project(api, scenario.project_id)
    assert_fields(project, completion_status="IN_PROGRESS", max_fundable_now_cents=1050000)
    assert_empty(project, "completion_certificate_ref", "certified_on")
    assert_fields(S.read_milestones(api, scenario.project_id)[1], status="PENDING")


def test_a_pending_milestone_is_tolerated_when_the_trade_waives_the_certificate(api):
    """With the remodel flag false, certification succeeds and lifts the cap to ten thousand bps.

    PRD: "Certification stores `completion_certificate_ref`, stamps `certified_on` from the logical clock, lifts the pre-completion release cap from the trade rule's `max_precompletion_release_bps` all the way to ten thousand basis points, and recomputes `max_fundable_now_cents` against the full contract."

    Design: Corner/validations/completion_certificate_gate_applies_only_when_the_trade_rule_demands_it
    """
    scenario = S.project_with_milestones(
        api,
        releases=(3000, 7000),
        verify=(0,),
        contract_amount_cents=1000000,
        ticket_cents=1000000,
        merchant={
            "legal_name": "Hill Country Remodel LLC",
            "trade_type": "GENERAL_REMODEL",
            "state_code": "TX",
            "contact_email": "office@hcremodel.example",
        },
        license_={
            "trade_type": "GENERAL_REMODEL",
            "license_number": "TX-GRM-40155",
            "state_code": "TX",
            "effective_from": "2026-01-01",
            "expires_on": "2027-06-30",
        },
        trade_rule={"trade_type": "GENERAL_REMODEL", "requires_completion_certificate": False},
    )

    data = validate_success(
        api.certify_completion(
            scenario.project_id,
            F.completion_certification_payload(completion_certificate_ref="COC-REMODEL-1"),
            scenario.as_consumer,
        )
    )

    # min(verified 3000, lifted cap 10000) = 3000; 1000000 * 3000 / 10000 = 300000
    assert_fields(
        data,
        completion_status="CERTIFIED_COMPLETE",
        completion_certificate_ref="COC-REMODEL-1",
        max_fundable_now_cents=bps_of(1000000, 3000),
    )
    # PRD pins only that `certified_on` is stamped from the logical clock, not its rendering.
    assert data["certified_on"].startswith(C.DEFAULT_CLOCK_DATE)
    assert data["max_fundable_now_cents"] == 300000
    assert_fields(S.read_milestones(api, scenario.project_id)[1], status="PENDING")
