"""Composite setup helpers for multi-step test preconditions.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors instead of confusing assertion failures.

Every helper builds its preconditions from scratch via PRD-declared
endpoints — each test runs against a freshly restarted server with an empty
database and the logical clock at its default 2026-08-01T00:00:00Z (§2.5).

Identity threading: LesseeRep is entity-backed (PRD §2.1), so every
LesseeRep call is made with make_lessee_rep_headers(lessee["id"]).
Retirement proposers/approvers get explicit operator ids (PRD §2.8 SoD).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_capital_pool_payload,
    create_cleaning_record_payload,
    create_commitment_payload,
    create_damage_assessment_payload,
    create_directive_payload,
    create_lease_agreement_payload,
    create_lease_assignment_payload,
    create_lessee_payload,
    create_mileage_report_payload,
    create_railcar_payload,
    create_repair_authorization_payload,
    create_retirement_case_payload,
    create_retrofit_order_payload,
    create_tariff_rate_payload,
    damage_line_item,
)
from .test_users import (
    TEST_USERS,
    make_compliance_officer_headers,
    make_fleet_planner_headers,
    make_lessee_rep_headers,
)

ADMIN = TEST_USERS["system_admin_headers"]
LEASE_ADMIN = TEST_USERS["lease_admin_headers"]
PLANNER = TEST_USERS["fleet_planner_headers"]
MAINT = TEST_USERS["maintenance_controller_headers"]
BILLING = TEST_USERS["billing_analyst_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]

# Operator ids used for the retirement segregation-of-duties flow (PRD §2.8):
# proposer and approver must differ.
DEFAULT_PROPOSER_ID = "fp-proposer-1"
DEFAULT_APPROVER_ID = "co-approver-1"


# ─── Tier 0: clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the logical clock (PRD §2.5; SystemAdmin only)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-resource creation ───────────────────────────────────────

def create_lessee(**overrides):
    return get_success_data(
        api_client.create_lessee(create_lessee_payload(**overrides), LEASE_ADMIN)
    )


def create_railcar(**overrides):
    return get_success_data(
        api_client.create_railcar(create_railcar_payload(**overrides), PLANNER)
    )


def create_tariff(car_type, rate_kind, unit_rate_cents,
                  effective_from="2026-01-01", effective_to="2027-01-01"):
    return get_success_data(
        api_client.create_tariff_rate(
            create_tariff_rate_payload(
                car_type=car_type,
                rate_kind=rate_kind,
                effective_from=effective_from,
                effective_to=effective_to,
                unit_rate_cents=unit_rate_cents,
            ),
            LEASE_ADMIN,
        )
    )


def create_tariff_pair(car_type="COVERED_HOPPER", hire_rate=9000,
                       mileage_rate=55, effective_from="2026-01-01",
                       effective_to="2027-01-01"):
    """Both tariff kinds an assignment needs (PRD §3.4 tariff coverage)."""
    hire = create_tariff(car_type, "CAR_HIRE_BASE", hire_rate,
                         effective_from, effective_to)
    mileage = create_tariff(car_type, "MILEAGE_CREDIT", mileage_rate,
                            effective_from, effective_to)
    return {"car_hire": hire, "mileage_credit": mileage}


def create_lease(lessee_id, **overrides):
    return get_success_data(
        api_client.create_lease_agreement(
            create_lease_agreement_payload(lessee_id=lessee_id, **overrides),
            LEASE_ADMIN,
        )
    )


def activate_lease(lease_id):
    """DRAFT -> PENDING_APPROVAL -> ACTIVE (PRD §3.3)."""
    get_success_data(api_client.submit_lease_agreement(lease_id, LEASE_ADMIN))
    return get_success_data(api_client.approve_lease_agreement(lease_id, COMPLIANCE))


def create_active_lease(lessee_id, **overrides):
    lease = create_lease(lessee_id, **overrides)
    activate_lease(lease["id"])
    return get_success_data(api_client.get_lease_agreement(lease["id"], LEASE_ADMIN))


def create_assignment(lease_id, railcar_id, **overrides):
    return get_success_data(
        api_client.create_lease_assignment(
            create_lease_assignment_payload(
                lease_id=lease_id, railcar_id=railcar_id, **overrides
            ),
            PLANNER,
        )
    )


def deliver_assignment(assignment_id):
    return get_success_data(api_client.deliver_assignment(assignment_id, PLANNER))


def return_assignment(assignment_id):
    return get_success_data(api_client.return_assignment(assignment_id, PLANNER))


# ─── Tier 2: full scenario (tariffs + lessee + car + ACTIVE lease) ─────────

def setup_active_lease_scenario(
    car_mark="GATX1001",
    car_type="COVERED_HOPPER",
    built_year=2015,
    commodity="GRAIN",
    lease_type="FULL_SERVICE",
    base_daily_rate_cents=5000,
    lessor_share_pct=100,
    repair_cap_cents=20000,
    credit_limit_cents=100000000,
    credit_tier="TIER_A",
    hire_rate=9000,
    mileage_rate=55,
    tariff_from="2026-01-01",
    tariff_to="2027-01-01",
    lease_start="2026-08-01",
    lease_end="2027-07-31",
    window_start="2026-08-01",
    window_end="2026-12-31",
    with_assignment=True,
    deliver=False,
    company_name="L",
):
    """Tariff pair + lessee + railcar + ACTIVE lease (+ SCHEDULED assignment,
    optionally delivered). Returns a dict with every created resource."""
    tariffs = create_tariff_pair(car_type, hire_rate, mileage_rate,
                                 tariff_from, tariff_to)
    lessee = create_lessee(company_name=company_name, credit_tier=credit_tier,
                           credit_limit_cents=credit_limit_cents)
    railcar = create_railcar(car_mark=car_mark, car_type=car_type,
                             built_year=built_year)
    lease = create_active_lease(
        lessee["id"],
        lease_type=lease_type,
        base_daily_rate_cents=base_daily_rate_cents,
        car_hire_lessor_share_pct=lessor_share_pct,
        authorized_repair_cap_cents=repair_cap_cents,
        start_date=lease_start,
        end_date=lease_end,
    )
    assignment = None
    if with_assignment:
        assignment = create_assignment(
            lease["id"], railcar["id"],
            planned_commodity=commodity,
            scheduled_start=window_start,
            scheduled_end=window_end,
        )
        if deliver:
            assignment = deliver_assignment(assignment["id"])
    return {
        "tariffs": tariffs,
        "lessee": lessee,
        "railcar": railcar,
        "lease": lease,
        "assignment": assignment,
    }


# ─── Tier 3: mileage / statement lifecycle ──────────────────────────────────

def submit_mileage_report(railcar_id, assignment_id, lessee_id, report_month,
                          loaded_miles, empty_miles):
    """LesseeRep submits; identity is the owning lessee (PRD §2.1)."""
    return get_success_data(
        api_client.create_mileage_report(
            create_mileage_report_payload(
                railcar_id=railcar_id,
                lease_assignment_id=assignment_id,
                report_month=report_month,
                loaded_miles=loaded_miles,
                empty_miles=empty_miles,
            ),
            make_lessee_rep_headers(lessee_id),
        )
    )


def validate_report(report_id, validated_loaded_miles=None,
                    validated_empty_miles=None):
    payload = {}
    if validated_loaded_miles is not None:
        payload["validated_loaded_miles"] = validated_loaded_miles
    if validated_empty_miles is not None:
        payload["validated_empty_miles"] = validated_empty_miles
    return get_success_data(
        api_client.validate_mileage_report(report_id, payload, BILLING)
    )


def generate_statements(statement_month):
    """Returns the full list produced by the generate batch (PRD §3.7)."""
    return get_success_data(
        api_client.generate_car_hire_statements(statement_month, BILLING)
    )


def setup_provisional_statement(
    statement_month="2026-08",
    loaded_miles=1000,
    empty_miles=200,
    validate=True,
    validated_loaded_miles=None,
    validated_empty_miles=None,
    **scenario_overrides,
):
    """Full chain: scenario + delivered assignment + mileage report (validated
    unless validate=False) + generated PROVISIONAL statement for the month.
    Returns dict(scenario fields, report, statement)."""
    scenario = setup_active_lease_scenario(deliver=True, **scenario_overrides)
    report = submit_mileage_report(
        scenario["railcar"]["id"], scenario["assignment"]["id"],
        scenario["lessee"]["id"], statement_month, loaded_miles, empty_miles,
    )
    if validate:
        report = validate_report(
            report["id"], validated_loaded_miles, validated_empty_miles
        )
    statements = generate_statements(statement_month)
    scenario["report"] = report
    scenario["statement"] = statements[0]
    return scenario


def get_lessee_balance(lessee_id):
    lessee = get_success_data(api_client.get_lessee(lessee_id, BILLING))
    return lessee["outstanding_balance_cents"]


def get_statement(statement_id):
    return get_success_data(api_client.get_car_hire_statement(statement_id, BILLING))


def get_assignment(assignment_id):
    return get_success_data(api_client.get_lease_assignment(assignment_id, PLANNER))


def get_railcar(railcar_id):
    return get_success_data(api_client.get_railcar(railcar_id, PLANNER))


# ─── Tier 4: repairs / shop ────────────────────────────────────────────────

def create_repair(railcar_id, assignment_id=None, defect_cause="WEAR_AND_TEAR",
                  estimate_cents=100000, requires_shop=False,
                  defect_description="defect"):
    payload = create_repair_authorization_payload(
        railcar_id=railcar_id,
        defect_description=defect_description,
        defect_cause=defect_cause,
        estimate_cents=estimate_cents,
        requires_shop=requires_shop,
    )
    if assignment_id is not None:
        payload["lease_assignment_id"] = assignment_id
    return get_success_data(api_client.create_repair_authorization(payload, MAINT))


def approve_repair(repair_id, amount_cents):
    return get_success_data(
        api_client.approve_repair(repair_id, amount_cents, MAINT)
    )


def preauthorize_repair(repair_id, lessee_id):
    return get_success_data(
        api_client.preauthorize_repair(repair_id, make_lessee_rep_headers(lessee_id))
    )


# ─── Tier 5: damage assessments and settle preconditions ───────────────────

ZERO_LINE = {
    "component": "INSPECTION_ONLY",
    "severity": "MINOR",
    "cause": "WEAR_AND_TEAR",
    "parts_cents": 0,
    "labor_hours": 0.0,
    "replaced": False,
}


def create_damage_assessment(assignment_id, railcar_id):
    return get_success_data(
        api_client.create_damage_assessment(
            create_damage_assessment_payload(
                lease_assignment_id=assignment_id, railcar_id=railcar_id
            ),
            MAINT,
        )
    )


def submit_assessment(assessment_id, line_items):
    return get_success_data(
        api_client.submit_damage_assessment(assessment_id, line_items, MAINT)
    )


def finalize_assessment(assessment_id):
    return get_success_data(
        api_client.finalize_damage_assessment(assessment_id, MAINT)
    )


def close_open_damage_assessments(assignment_id):
    """Bring every damage assessment on the assignment to a settle-compatible
    state (PRD §3.6 requires FINALIZED/INVOICED/PAID and none INVOICED-unpaid;
    the return cascade creates a DRAFT per §3.4). Open assessments are closed
    with a zero-cost WEAR_AND_TEAR line so no lessee liability is added."""
    resp = api_client.list_damage_assessments(MAINT, params={"limit": 100})
    items, _meta = validate_paginated(resp)
    for item in items:
        if item.get("lease_assignment_id") != assignment_id:
            continue
        status = item.get("status")
        if status in ("DRAFT",):
            submit_assessment(item["id"], [dict(ZERO_LINE)])
            finalize_assessment(item["id"])
        elif status == "SUBMITTED":
            finalize_assessment(item["id"])
        elif status == "DISPUTED":
            get_success_data(
                api_client.resubmit_damage_assessment(
                    item["id"], [dict(ZERO_LINE)], MAINT
                )
            )
            finalize_assessment(item["id"])
        elif status == "INVOICED":
            current = get_success_data(
                api_client.get_damage_assessment(item["id"], MAINT)
            )
            get_success_data(
                api_client.record_damage_payment(
                    item["id"], current["lessee_liable_cents"], BILLING
                )
            )


# ─── Cleaning ───────────────────────────────────────────────────────────────

def create_cleaning(railcar_id, prior_commodity="GRAIN", next_commodity="COAL",
                    planned_date="2026-08-16", attributable_to_lessee=None):
    payload = create_cleaning_record_payload(
        railcar_id=railcar_id,
        prior_commodity=prior_commodity,
        next_commodity=next_commodity,
        planned_date=planned_date,
    )
    if attributable_to_lessee is not None:
        payload["attributable_to_lessee"] = attributable_to_lessee
    return get_success_data(api_client.create_cleaning_record(payload, MAINT))


def certify_cleaning_record(cleaning_id, grade="WASH", cost_cents=50000,
                            certificate_ref="CLN-1"):
    get_success_data(
        api_client.complete_cleaning(cleaning_id, grade, cost_cents, MAINT)
    )
    return get_success_data(
        api_client.certify_cleaning(cleaning_id, certificate_ref, COMPLIANCE)
    )


# ─── Directives / retrofit ──────────────────────────────────────────────────

def create_directive(**overrides):
    return get_success_data(
        api_client.create_compliance_directive(
            create_directive_payload(**overrides), COMPLIANCE
        )
    )


def promote_directive(directive_id):
    return get_success_data(api_client.promote_directive(directive_id, COMPLIANCE))


def create_retrofit(railcar_id, directive_id, scheduled_date="2026-08-10"):
    return get_success_data(
        api_client.create_retrofit_order(
            create_retrofit_order_payload(
                railcar_id=railcar_id,
                directive_id=directive_id,
                scheduled_date=scheduled_date,
            ),
            MAINT,
        )
    )


def certify_retrofit_order(order_id, certification_ref="CERT-1"):
    get_success_data(api_client.start_retrofit(order_id, MAINT))
    get_success_data(api_client.complete_retrofit(order_id, MAINT))
    return get_success_data(
        api_client.certify_retrofit(order_id, certification_ref, COMPLIANCE)
    )


# ─── Retirement / capital pool ──────────────────────────────────────────────

def propose_retirement(railcar_id, reason="AGE_LIMIT",
                       proposer_id=DEFAULT_PROPOSER_ID):
    """PRD §2.8: proposer_user_id is the creator's X-User-ID."""
    return get_success_data(
        api_client.create_retirement_case(
            create_retirement_case_payload(railcar_id=railcar_id, reason=reason),
            make_fleet_planner_headers(proposer_id),
        )
    )


def appraise_retirement(case_id, salvage_value_cents=1500000,
                        book_value_cents=8000000):
    return get_success_data(
        api_client.appraise_retirement(
            case_id, salvage_value_cents, book_value_cents, PLANNER
        )
    )


def approve_retirement(case_id, approver_id=DEFAULT_APPROVER_ID):
    return get_success_data(
        api_client.approve_retirement(
            case_id, make_compliance_officer_headers(approver_id)
        )
    )


def create_pool(fiscal_year=2026, opening_balance_cents=100000000):
    return get_success_data(
        api_client.create_capital_pool(
            create_capital_pool_payload(
                fiscal_year=fiscal_year,
                opening_balance_cents=opening_balance_cents,
            ),
            ADMIN,
        )
    )


def create_commitment(pool_id, unit_cost_cents, expected_pool_version,
                      car_type="COVERED_HOPPER"):
    return get_success_data(
        api_client.create_commitment(
            pool_id,
            create_commitment_payload(
                car_type=car_type,
                unit_cost_cents=unit_cost_cents,
                expected_pool_version=expected_pool_version,
            ),
            PLANNER,
        )
    )


def get_pool(pool_id):
    return get_success_data(api_client.get_capital_pool(pool_id, PLANNER))
