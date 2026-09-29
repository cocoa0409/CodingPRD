"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch using only PRD-declared endpoints. Setup calls use the
lenient validator so a broken precondition reports as a setup failure rather than
as a confusing assertion failure inside a test.
"""
from typing import Iterable, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_CLOCK_ISO
from .factories import (
    claim_line_payload,
    create_accumulator_adjustment_payload,
    create_adjustment_payload,
    create_authorization_payload,
    create_benefit_plan_payload,
    create_claim_payload,
    create_contract_payload,
    create_coverage_payload,
    create_edit_rule_payload,
    create_fee_schedule_rate_payload,
    create_member_payload,
    create_provider_payload,
    other_payer_payment_payload,
    override_payload,
    set_clock_payload,
    terminate_contract_payload,
    terminate_coverage_payload,
)
from .test_users import TEST_USERS, make_claims_examiner_headers, make_medical_director_headers

PLAN_ADMIN = TEST_USERS["plan_admin_headers"]
NETWORK_MANAGER = TEST_USERS["network_manager_headers"]
CLAIMS_INTAKE = TEST_USERS["claims_intake_headers"]
CLAIMS_EXAMINER = TEST_USERS["claims_examiner_headers"]
UTILIZATION_REVIEWER = TEST_USERS["utilization_reviewer_headers"]
MEDICAL_DIRECTOR = TEST_USERS["medical_director_headers"]


# ─── Tier 0: single-call wrappers ─────────────────────────────────────────────

def set_clock(to_iso8601: str = TEST_CLOCK_ISO) -> None:
    """Move the server's logical clock. Every date comparison reads this value."""
    get_success_data(api_client.set_clock(set_clock_payload(to_iso8601), PLAN_ADMIN))


def create_plan(**overrides) -> dict:
    return get_success_data(
        api_client.create_benefit_plan(create_benefit_plan_payload(**overrides), PLAN_ADMIN)
    )


def publish_rate(
    plan_id: str,
    procedure_code: str = "73721",
    allowed_amount_cents: int = 40000,
    effective_date: str = "2026-01-01",
) -> dict:
    return get_success_data(
        api_client.create_fee_schedule_rate(
            plan_id,
            create_fee_schedule_rate_payload(
                procedure_code=procedure_code,
                allowed_amount_cents=allowed_amount_cents,
                effective_date=effective_date,
            ),
            NETWORK_MANAGER,
        )
    )


def create_provider(**overrides) -> dict:
    return get_success_data(
        api_client.create_provider(create_provider_payload(**overrides), PLAN_ADMIN)
    )


def create_member(plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_member(create_member_payload(plan_id, **overrides), PLAN_ADMIN)
    )


def add_coverage(member_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_coverage(member_id, create_coverage_payload(**overrides), PLAN_ADMIN)
    )


def terminate_coverage(coverage_id: str, term_date: str) -> dict:
    return get_success_data(
        api_client.terminate_coverage(
            coverage_id, terminate_coverage_payload(term_date), PLAN_ADMIN
        )
    )


def draft_contract(provider_id: str, plan_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(provider_id, plan_id, **overrides), NETWORK_MANAGER
        )
    )


def activate_contract(contract_id: str) -> dict:
    return get_success_data(api_client.activate_contract(contract_id, NETWORK_MANAGER))


def terminate_contract(contract_id: str, term_date: str) -> dict:
    return get_success_data(
        api_client.terminate_contract(
            contract_id, terminate_contract_payload(term_date), NETWORK_MANAGER
        )
    )


def create_active_contract(provider_id: str, plan_id: str, **overrides) -> dict:
    """Draft a contract and activate it so it starts pricing claims."""
    contract = draft_contract(provider_id, plan_id, **overrides)
    return activate_contract(contract["id"])


def publish_edit_rule(**overrides) -> dict:
    return get_success_data(
        api_client.create_edit_rule(create_edit_rule_payload(**overrides), PLAN_ADMIN)
    )


def publish_auth_required_rule(
    procedure_code: str = "73721",
    rule_code: str = "MP-AUTH-1",
    precedence_rank: int = 30,
    reason_code: str = "PEND_AUTH_MISSING",
) -> dict:
    """An AUTH_REQUIRED rule declares that lines on `procedure_code` need an authorization."""
    return publish_edit_rule(
        rule_code=rule_code,
        edit_type="AUTH_REQUIRED",
        primary_code=procedure_code,
        severity="PEND",
        precedence_rank=precedence_rank,
        reason_code=reason_code,
    )


def issue_authorization(member_id: str, provider_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_authorization(
            create_authorization_payload(member_id, provider_id, **overrides),
            UTILIZATION_REVIEWER,
        )
    )


def revoke_authorization(authorization_id: str) -> dict:
    return get_success_data(
        api_client.revoke_authorization(authorization_id, UTILIZATION_REVIEWER)
    )


def submit_claim(
    member_id: str,
    provider_id: str,
    lines: Optional[List[dict]] = None,
    claim_number: str = "CLM-1",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_claim(
            create_claim_payload(
                member_id, provider_id, lines, claim_number=claim_number, **overrides
            ),
            headers or CLAIMS_INTAKE,
        )
    )


def adjudicate(claim_id: str, user_id: Optional[str] = None) -> dict:
    """Run one adjudication pass. `user_id` lands in last_adjudicated_by_user_id."""
    headers = make_claims_examiner_headers(user_id) if user_id else CLAIMS_EXAMINER
    return get_success_data(api_client.adjudicate_claim(claim_id, headers))


def finalize(claim_id: str) -> dict:
    return get_success_data(api_client.finalize_claim(claim_id, CLAIMS_EXAMINER))


def void_claim(claim_id: str, void_reason_code: Optional[str] = None) -> dict:
    payload = {} if void_reason_code is None else {"void_reason_code": void_reason_code}
    return get_success_data(api_client.void_claim(claim_id, payload, CLAIMS_EXAMINER))


def create_adjustment(
    claim_id: str, claim_number: str, lines: List[dict], **overrides
) -> dict:
    return get_success_data(
        api_client.create_adjustment(
            claim_id, create_adjustment_payload(claim_number, lines, **overrides),
            CLAIMS_EXAMINER,
        )
    )


def override_claim(
    claim_id: str,
    decision: str,
    user_id: Optional[str] = None,
    override_reason_code: Optional[str] = None,
) -> dict:
    payload = override_payload(decision)
    if override_reason_code is not None:
        payload["override_reason_code"] = override_reason_code
    headers = make_medical_director_headers(user_id) if user_id else MEDICAL_DIRECTOR
    return get_success_data(api_client.override_claim(claim_id, payload, headers))


def post_other_payer_payment(
    claim_id: str, other_payer_paid_cents: int, expected_claim_version: int
) -> dict:
    return get_success_data(
        api_client.post_other_payer_payment(
            claim_id,
            other_payer_payment_payload(other_payer_paid_cents, expected_claim_version),
            CLAIMS_INTAKE,
        )
    )


def adjust_accumulator(
    accumulator_id: str,
    expected_accumulator_version: int,
    deductible_delta_cents: int = 0,
    oop_delta_cents: int = 0,
    note: Optional[str] = None,
) -> dict:
    payload = create_accumulator_adjustment_payload(
        expected_accumulator_version, deductible_delta_cents, oop_delta_cents
    )
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.adjust_accumulator(accumulator_id, payload, PLAN_ADMIN))


# ─── Tier 0: read helpers ─────────────────────────────────────────────────────

def get_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_claim(claim_id, CLAIMS_EXAMINER))


def get_authorization(authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_authorization(authorization_id, UTILIZATION_REVIEWER)
    )


def get_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_contract(contract_id, NETWORK_MANAGER))


def get_member(member_id: str) -> dict:
    return get_success_data(api_client.get_member(member_id, PLAN_ADMIN))


def get_coverage_rows(member_id: str) -> List[dict]:
    return get_success_data(api_client.list_coverages(member_id, PLAN_ADMIN))


def get_claim_lines(claim_id: str) -> List[dict]:
    """Service lines of a claim, returned by line_number ascending."""
    return get_success_data(
        api_client.list_claim_lines(CLAIMS_EXAMINER, params={"claim_id": claim_id})
    )


def lines_by_number(claim_id: str) -> dict:
    return {line["line_number"]: line for line in get_claim_lines(claim_id)}


def get_accumulators(member_id: str) -> List[dict]:
    """A member's benefit accumulators, newest plan year first."""
    return get_success_data(api_client.list_accumulators(member_id, PLAN_ADMIN))


def get_accumulator(member_id: str, plan_year: Optional[int] = None) -> dict:
    rows = get_accumulators(member_id)
    if plan_year is None:
        assert rows, f"Setup failed: member {member_id} has no benefit accumulator"
        return rows[0]
    for row in rows:
        if row["plan_year"] == plan_year:
            return row
    raise AssertionError(f"Setup failed: no accumulator for plan_year {plan_year}")


def get_remittances(claim_id: str) -> List[dict]:
    return get_success_data(api_client.list_remittances(claim_id, CLAIMS_EXAMINER))


def get_events(claim_id: str, **params) -> List[dict]:
    return get_success_data(
        api_client.list_events(claim_id, CLAIMS_EXAMINER, params=params or None)
    )


def seed_accumulator(
    member_id: str, deductible_delta_cents: int = 0, oop_delta_cents: int = 0
) -> dict:
    """Seed year-to-date balances through the manual-correction endpoint."""
    accumulator = get_accumulator(member_id)
    return adjust_accumulator(
        accumulator["id"],
        accumulator["version"],
        deductible_delta_cents=deductible_delta_cents,
        oop_delta_cents=oop_delta_cents,
    )


# ─── Tier 1/2: the standard configuration preamble ────────────────────────────

OPEN_PRIMARY_COVERAGE = {"effective_date": "2026-01-01", "cob_order": "PRIMARY"}
OPEN_SECONDARY_COVERAGE = {
    "effective_date": "2026-01-01",
    "cob_order": "SECONDARY",
    "other_payer_name": "Other Health",
}


def setup_environment(
    plan_overrides: Optional[dict] = None,
    provider_overrides: Optional[dict] = None,
    rates: Iterable = (),
    member_overrides: Optional[dict] = None,
    coverages: Optional[Iterable[dict]] = (OPEN_PRIMARY_COVERAGE,),
    edit_rules: Iterable[dict] = (),
    authorizations: Iterable[dict] = (),
    clock: Optional[str] = TEST_CLOCK_ISO,
    with_member: bool = True,
    with_provider: bool = True,
) -> dict:
    """Plan + provider + published rates + member + coverage segments.

    `rates` accepts (procedure_code, cents, effective_date) tuples or full dicts.
    Returns a dict with plan, provider, member, coverages, rates, rules and
    authorizations so a test can reach straight for the ids it needs.
    """
    if clock is not None:
        set_clock(clock)

    plan = create_plan(**(plan_overrides or {}))

    rate_rows = []
    for rate in rates:
        if isinstance(rate, dict):
            rate_rows.append(publish_rate(plan["id"], **rate))
        else:
            code, cents, effective = rate
            rate_rows.append(publish_rate(plan["id"], code, cents, effective))

    provider = create_provider(**(provider_overrides or {})) if with_provider else None

    member = None
    coverage_rows = []
    if with_member:
        member = create_member(plan["id"], **(member_overrides or {}))
        for coverage in coverages or ():
            coverage_rows.append(add_coverage(member["id"], **coverage))

    rule_rows = [publish_edit_rule(**rule) for rule in edit_rules]

    auth_rows = []
    for auth in authorizations:
        auth_rows.append(issue_authorization(member["id"], provider["id"], **auth))

    return {
        "plan": plan,
        "provider": provider,
        "member": member,
        "coverages": coverage_rows,
        "coverage": coverage_rows[0] if coverage_rows else None,
        "rates": rate_rows,
        "rules": rule_rows,
        "authorizations": auth_rows,
        "authorization": auth_rows[0] if auth_rows else None,
    }


def setup_open_plan_environment(**kwargs) -> dict:
    """Environment whose plan neutralises cost share (zero deductible, zero coinsurance,
    a very high out-of-pocket maximum) so the allowed amount is the only moving part."""
    plan_overrides = {
        "deductible_individual_cents": 0,
        "oop_max_individual_cents": 1000000,
        "coinsurance_member_pct": 0,
    }
    plan_overrides.update(kwargs.pop("plan_overrides", None) or {})
    return setup_environment(plan_overrides=plan_overrides, **kwargs)


def setup_imaging_environment(rate_cents: int = 40000, **kwargs) -> dict:
    """The most common preamble: neutral plan, IN_NETWORK provider, one imaging rate,
    one open-ended PRIMARY coverage segment."""
    kwargs.setdefault("rates", [("73721", rate_cents, "2026-01-01")])
    return setup_open_plan_environment(**kwargs)


def setup_auth_gated_environment(
    authorized_units: int = 4, rate_cents: int = 40000, rule_code: str = "MP-AUTH-1", **kwargs
) -> dict:
    """Imaging environment plus an AUTH_REQUIRED rule on 73721 and a matching grant."""
    kwargs.setdefault(
        "edit_rules",
        [
            {
                "rule_code": rule_code,
                "edit_type": "AUTH_REQUIRED",
                "primary_code": "73721",
                "severity": "PEND",
                "precedence_rank": 30,
                "reason_code": "PEND_AUTH_MISSING",
            }
        ],
    )
    kwargs.setdefault(
        "authorizations",
        [
            {
                "procedure_code": "73721",
                "authorized_units": authorized_units,
                "valid_from": "2026-01-01",
                "valid_to": "2026-12-31",
            }
        ],
    )
    return setup_imaging_environment(rate_cents=rate_cents, **kwargs)


# ─── Tier 3: lifecycle shortcuts ──────────────────────────────────────────────

def submit_and_adjudicate(
    env: dict,
    lines: Optional[List[dict]] = None,
    claim_number: str = "CLM-1",
    user_id: Optional[str] = None,
    **claim_overrides,
) -> dict:
    """Intake a claim into the given environment and run one adjudication pass."""
    claim = submit_claim(
        env["member"]["id"], env["provider"]["id"], lines, claim_number, **claim_overrides
    )
    return adjudicate(claim["id"], user_id=user_id)


def submit_adjudicate_finalize(
    env: dict,
    lines: Optional[List[dict]] = None,
    claim_number: str = "CLM-1",
    **claim_overrides,
) -> dict:
    """Intake -> adjudicate -> finalize. Returns the FINALIZED claim."""
    adjudicated = submit_and_adjudicate(env, lines, claim_number, **claim_overrides)
    return finalize(adjudicated["id"])


def setup_finalized_imaging_claim(
    plan_overrides: Optional[dict] = None,
    rate_cents: int = 40000,
    billed_cents: int = 60000,
    units: int = 1,
    claim_number: str = "CLM-FIN-1",
) -> dict:
    """Neutral plan, one priced imaging line, claim carried through to FINALIZED."""
    env = setup_imaging_environment(rate_cents=rate_cents, plan_overrides=plan_overrides)
    claim = submit_adjudicate_finalize(
        env,
        [claim_line_payload(1, "73721", units, billed_cents, "2026-02-10")],
        claim_number,
    )
    env["claim"] = claim
    return env


def setup_pended_auth_missing_claim(
    examiner_user_id: str = "u-examiner-1",
    units: int = 1,
    billed_cents: int = 60000,
    claim_number: str = "CLM-PEND-1",
) -> dict:
    """An AUTH_REQUIRED rule with no authorization on file pends the claim."""
    env = setup_imaging_environment(
        edit_rules=[
            {
                "rule_code": "MP-AUTH-PEND",
                "edit_type": "AUTH_REQUIRED",
                "primary_code": "73721",
                "severity": "PEND",
                "precedence_rank": 30,
                "reason_code": "PEND_AUTH_MISSING",
            }
        ]
    )
    claim = submit_and_adjudicate(
        env,
        [claim_line_payload(1, "73721", units, billed_cents, "2026-02-10")],
        claim_number,
        user_id=examiner_user_id,
    )
    env["claim"] = claim
    return env


def setup_pended_auth_units_exceeded_claim(
    authorized_units: int = 1,
    line_units: int = 3,
    billed_cents: int = 200000,
    examiner_user_id: str = "u-examiner-8",
    claim_number: str = "CLM-UNITS-1",
) -> dict:
    """A grant smaller than the billed units pends the line with PEND_AUTH_UNITS_EXCEEDED."""
    env = setup_auth_gated_environment(authorized_units=authorized_units)
    claim = submit_and_adjudicate(
        env,
        [claim_line_payload(1, "73721", line_units, billed_cents, "2026-02-10")],
        claim_number,
        user_id=examiner_user_id,
    )
    env["claim"] = claim
    return env


def setup_denied_no_coverage_claim(
    plan_overrides: Optional[dict] = None, claim_number: str = "CLM-NOCOV-1"
) -> dict:
    """The member's only coverage segment closes before the service date, so the
    adjudication pass resolves to DENIED with DENY_NO_COVERAGE."""
    env = setup_environment(
        plan_overrides=plan_overrides
        or {
            "deductible_individual_cents": 50000,
            "oop_max_individual_cents": 300000,
            "coinsurance_member_pct": 0.20,
        },
        rates=[("73721", 40000, "2026-01-01")],
        coverages=[
            {"effective_date": "2026-01-01", "term_date": "2026-02-01", "cob_order": "PRIMARY"}
        ],
    )
    claim = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], claim_number
    )
    env["claim"] = claim
    return env


def setup_duplicate_pair(
    baseline_billed: int = 10000,
    duplicate_billed: int = 10000,
    procedure_code: str = "99213",
    rate_cents: int = 10000,
) -> dict:
    """A baseline claim plus a second submission that repeats its line within tolerance."""
    env = setup_open_plan_environment(rates=[(procedure_code, rate_cents, "2026-01-01")])
    baseline = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, procedure_code, 1, baseline_billed, "2026-02-10")],
        "CLM-DUP-A",
    )
    repeat = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, procedure_code, 1, duplicate_billed, "2026-02-10")],
        "CLM-DUP-B",
    )
    env["baseline_claim"] = baseline
    env["repeat_claim"] = repeat
    return env


# ─── Tier 4/5: per-scenario composites for the harder assertions ──────────────

def setup_contract_then_fee_schedule_pricing() -> dict:
    """Price one line under an ACTIVE percent-of-fee-schedule contract, terminate the
    contract, then price an identical line with no contract in force."""
    env = setup_imaging_environment(
        plan_overrides={"plan_code": "PPO-PRICE"},
        provider_overrides={"npi": "1000000001", "name": "Alpha Imaging"},
        member_overrides={"member_number": "M-PRICE-1"},
    )
    contract = create_active_contract(
        env["provider"]["id"],
        env["plan"]["id"],
        effective_date="2026-01-01",
        term_date="2026-12-31",
        pricing_method="PCT_OF_FEE_SCHEDULE",
        contract_pct=0.755,
    )
    contracted = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], "CLM-PV-1"
    )
    terminate_contract(contract["id"], "2026-02-01")
    uncontracted = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 1, 61000, "2026-02-10")], "CLM-PV-2"
    )
    env["contract"] = contract
    env["contracted_claim"] = contracted
    env["uncontracted_claim"] = uncontracted
    return env


def setup_cob_variant_pair(other_payer_paid_cents: int = 24000) -> dict:
    """Two plans identical but for cob_method, each with one SECONDARY claim carrying
    the same allowed amount and the same reported other-payer payment."""
    set_clock()
    plan_cw = create_plan(
        plan_code="COB-CW",
        name="COB Come Out Whole",
        deductible_individual_cents=0,
        oop_max_individual_cents=1000000,
        coinsurance_member_pct=0.30,
        cob_method="COME_OUT_WHOLE",
    )
    plan_nd = create_plan(
        plan_code="COB-ND",
        name="COB Non Duplication",
        deductible_individual_cents=0,
        oop_max_individual_cents=1000000,
        coinsurance_member_pct=0.30,
        cob_method="NON_DUPLICATION",
    )
    provider = create_provider(npi="1000000002", name="Beta Imaging")
    publish_rate(plan_cw["id"], "73721", 40000, "2026-01-01")
    publish_rate(plan_nd["id"], "73721", 40000, "2026-01-01")

    member_cw = create_member(plan_cw["id"], member_number="M-CW")
    add_coverage(member_cw["id"], **OPEN_SECONDARY_COVERAGE)
    member_nd = create_member(plan_nd["id"], member_number="M-ND")
    add_coverage(member_nd["id"], **OPEN_SECONDARY_COVERAGE)

    line = [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")]
    claim_cw = submit_claim(
        member_cw["id"], provider["id"], line, "CLM-COB-CW",
        other_payer_paid_cents=other_payer_paid_cents,
    )
    claim_nd = submit_claim(
        member_nd["id"], provider["id"], line, "CLM-COB-ND",
        other_payer_paid_cents=other_payer_paid_cents,
    )
    return {
        "plan_come_out_whole": plan_cw,
        "plan_non_duplication": plan_nd,
        "provider": provider,
        "member_come_out_whole": member_cw,
        "member_non_duplication": member_nd,
        "claim_come_out_whole": adjudicate(claim_cw["id"]),
        "claim_non_duplication": adjudicate(claim_nd["id"]),
    }


def setup_three_line_rounding_claim() -> dict:
    """Three identical lines priced under a 0.755 contract multiplier, where the
    rounding order decides whether the claim total is 7548 or 7549."""
    env = setup_open_plan_environment(
        plan_overrides={"plan_code": "ROUND-1", "name": "Rounding Plan"},
        provider_overrides={"npi": "1000000003", "name": "Gamma Lab"},
        member_overrides={"member_number": "M-ROUND-1"},
        rates=[("82947", 3333, "2026-01-01")],
    )
    create_active_contract(
        env["provider"]["id"],
        env["plan"]["id"],
        effective_date="2026-01-01",
        term_date="2026-12-31",
        pricing_method="PCT_OF_FEE_SCHEDULE",
        contract_pct=0.755,
    )
    env["claim"] = submit_and_adjudicate(
        env,
        [claim_line_payload(n, "82947", 1, 5000, "2026-02-10") for n in (1, 2, 3)],
        "CLM-ROUND-1",
    )
    return env


def setup_oop_cap_snapshot_claim() -> dict:
    """A member already 6000 cents into a 10000-cent out-of-pocket maximum, with a
    two-line claim whose provisional liability overshoots the remaining room."""
    env = setup_environment(
        plan_overrides={
            "plan_code": "OOP-CAP",
            "name": "Out Of Pocket Cap Plan",
            "deductible_individual_cents": 0,
            "oop_max_individual_cents": 10000,
            "coinsurance_member_pct": 0.50,
        },
        provider_overrides={"npi": "1000000004", "name": "Delta Clinic"},
        member_overrides={"member_number": "M-OOP-1"},
        rates=[("73721", 20000, "2026-01-01")],
    )
    env["accumulator"] = seed_accumulator(env["member"]["id"], oop_delta_cents=6000)
    env["claim"] = submit_and_adjudicate(
        env,
        [
            claim_line_payload(1, "73721", 1, 30000, "2026-02-10"),
            claim_line_payload(2, "73721", 1, 30000, "2026-02-10"),
        ],
        "CLM-OOP-1",
    )
    return env


def setup_pend_cycle_then_cob_repost(examiner_user_id: str = "u-examiner-1") -> dict:
    """Two pends in a row, then a grant is issued and the claim adjudicates, then a
    late other-payer posting drives the claim back to RECEIVED."""
    env = setup_imaging_environment(
        plan_overrides={"plan_code": "CYCLE-1", "name": "Cycle Plan"},
        provider_overrides={"npi": "1000000005", "name": "Epsilon Imaging"},
        member_overrides={"member_number": "M-CYCLE-1"},
        coverages=[OPEN_SECONDARY_COVERAGE],
        edit_rules=[
            {
                "rule_code": "MP-73721-AUTH",
                "edit_type": "AUTH_REQUIRED",
                "primary_code": "73721",
                "severity": "PEND",
                "precedence_rank": 30,
                "reason_code": "PEND_AUTH_MISSING",
            }
        ],
    )
    claim = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, "73721", 2, 60000, "2026-02-10")],
        "CLM-CYCLE-1",
        other_payer_paid_cents=0,
    )
    env["pass_1"] = adjudicate(claim["id"], user_id=examiner_user_id)
    env["pass_2"] = adjudicate(claim["id"], user_id=examiner_user_id)
    env["authorization"] = issue_authorization(
        env["member"]["id"],
        env["provider"]["id"],
        procedure_code="73721",
        authorized_units=4,
        valid_from="2026-01-01",
        valid_to="2026-12-31",
    )
    env["pass_3"] = adjudicate(claim["id"], user_id=examiner_user_id)
    env["claim"] = claim
    return env


def setup_exhausted_authorization_with_finalized_claim() -> dict:
    """Two claims split a four-unit grant between them; the second is FINALIZED, so the
    grant sits EXHAUSTED and a void of the second claim releases half of it."""
    env = setup_auth_gated_environment(
        authorized_units=4,
        plan_overrides={"plan_code": "AUTH-CYC", "name": "Authorization Cycle Plan"},
        provider_overrides={"npi": "1000000006", "name": "Zeta Imaging"},
        member_overrides={"member_number": "M-AUTHCYC"},
        rule_code="MP-73721-AUTH-B",
    )
    holder = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 2, 60000, "2026-02-10")], "CLM-AC-1"
    )
    finalized = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 2, 61000, "2026-02-11")], "CLM-AC-2"
    )
    env["authorization_before_void"] = get_authorization(env["authorization"]["id"])
    env["holder_claim"] = holder
    env["finalized_claim"] = finalize(finalized["id"])
    return env


def setup_void_cascade_ready_claim() -> dict:
    """A FINALIZED claim that posted 50000/52000 to the accumulator and exhausted a
    two-unit authorization, ready for the void cascade."""
    env = setup_auth_gated_environment(
        authorized_units=2,
        plan_overrides={
            "plan_code": "VOID-CASC",
            "name": "Void Cascade Plan",
            "deductible_individual_cents": 50000,
            "oop_max_individual_cents": 300000,
            "coinsurance_member_pct": 0.20,
        },
        provider_overrides={"npi": "1000000007", "name": "Eta Imaging"},
        member_overrides={"member_number": "M-VOID-1"},
        rule_code="MP-73721-AUTH-C",
    )
    adjudicated = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 2, 60000, "2026-02-10")], "CLM-VOID-1"
    )
    env["claim"] = finalize(adjudicated["id"])
    env["accumulator_after_finalize"] = get_accumulator(env["member"]["id"])
    return env


def setup_coverage_termination_cascade_ready() -> dict:
    """An ADJUDICATED claim holding all four units of a grant, whose only coverage
    segment is about to be terminated behind its statement period."""
    env = setup_auth_gated_environment(
        authorized_units=4,
        plan_overrides={"plan_code": "ELIG-CASC", "name": "Eligibility Cascade Plan"},
        provider_overrides={"npi": "1000000008", "name": "Theta Imaging"},
        member_overrides={"member_number": "M-ELIG-1"},
        rule_code="MP-73721-AUTH-D",
        clock="2026-05-01T00:00:00Z",
    )
    env["claim_before"] = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 4, 200000, "2026-04-10")], "CLM-ELIG-1"
    )
    env["claim"] = env["claim_before"]
    return env


def setup_adjudicated_claim_for_override(shared_user_id: str = "u-shared-1") -> dict:
    """A claim that adjudicated cleanly (so it is not PENDED) under a known examiner id,
    which the same principal will then try to override."""
    env = setup_imaging_environment(
        plan_overrides={"plan_code": "PRIO-1", "name": "Priority Plan"},
        provider_overrides={"npi": "1000000009", "name": "Iota Clinic"},
        member_overrides={"member_number": "M-PRIO-1"},
    )
    env["claim"] = submit_and_adjudicate(
        env,
        [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
        "CLM-PRIO-1",
        user_id=shared_user_id,
    )
    return env


def setup_stale_filing_environment() -> dict:
    """Clock parked on the server default, plan on a 90-day filing window, member with
    coverage on file — the stage for an intake that is both late and over-billed."""
    return setup_imaging_environment(
        plan_overrides={
            "plan_code": "PRIO-2",
            "name": "Priority Plan Two",
            "timely_filing_days": 90,
        },
        provider_overrides={"npi": "1000000010", "name": "Kappa Clinic"},
        member_overrides={"member_number": "M-PRIO-2"},
        clock="2026-08-01T00:00:00Z",
    )


def setup_authorization_units_boundary() -> dict:
    """A four-unit grant already half spent, plus two unadjudicated claims: one asking
    for exactly the remaining units and one asking for a unit more than remains."""
    env = setup_auth_gated_environment(
        authorized_units=4,
        plan_overrides={"plan_code": "AUTH-BND", "name": "Authorization Boundary Plan"},
        provider_overrides={"npi": "1000000012", "name": "Mu Imaging"},
        member_overrides={"member_number": "M-AUTHBND"},
        rule_code="MP-73721-AUTH-E",
    )
    first = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 2, 60000, "2026-02-10")], "CLM-AB-1"
    )
    exact = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, "73721", 2, 61000, "2026-02-11")],
        "CLM-AB-2",
    )
    over = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, "73721", 1, 62000, "2026-02-12")],
        "CLM-AB-3",
    )
    env["first_claim"] = first
    env["exact_units_claim"] = exact
    env["over_units_claim"] = over
    return env


def setup_claim_outside_every_coverage_interval() -> dict:
    """The member's only segment closes at 2026-02-01 while the line is serviced on
    2026-02-10, so nothing contains the service date."""
    env = setup_environment(
        plan_overrides={
            "plan_code": "XENT-1",
            "name": "Cross Entity Plan",
            "deductible_individual_cents": 0,
            "oop_max_individual_cents": 1000000,
            "coinsurance_member_pct": 0,
        },
        provider_overrides={"npi": "1000000013", "name": "Nu Clinic"},
        member_overrides={"member_number": "M-XENT-1"},
        rates=[("73721", 40000, "2026-01-01")],
        coverages=[
            {"effective_date": "2026-01-01", "term_date": "2026-02-01", "cob_order": "PRIMARY"}
        ],
    )
    env["claim_at_intake"] = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")],
        "CLM-XENT-1",
    )
    return env


def setup_revoked_authorization_claim() -> dict:
    """The only grant matching the line has been revoked while still unconsumed."""
    env = setup_auth_gated_environment(
        authorized_units=4,
        plan_overrides={"plan_code": "XENT-2", "name": "Cross Entity Plan Two"},
        provider_overrides={"npi": "1000000014", "name": "Xi Imaging"},
        member_overrides={"member_number": "M-XENT-2"},
        rule_code="MP-73721-AUTH-F",
    )
    env["revoked_authorization"] = revoke_authorization(env["authorization"]["id"])
    env["claim_at_intake"] = submit_claim(
        env["member"]["id"],
        env["provider"]["id"],
        [claim_line_payload(1, "73721", 2, 60000, "2026-02-10")],
        "CLM-XENT-2",
    )
    return env


def setup_member_with_bounded_coverage() -> dict:
    """A member holding exactly one coverage segment over [2026-01-01, 2026-06-01)."""
    env = setup_environment(
        plan_overrides={
            "plan_code": "OVL-1",
            "name": "Overlap Plan",
            "deductible_individual_cents": 0,
            "oop_max_individual_cents": 1000000,
            "coinsurance_member_pct": 0,
        },
        member_overrides={"member_number": "M-OVL-1"},
        coverages=[
            {"effective_date": "2026-01-01", "term_date": "2026-06-01", "cob_order": "PRIMARY"}
        ],
        with_provider=False,
    )
    return env


def setup_provider_with_draft_contract() -> dict:
    """One DRAFT contract over the closed interval 2026-01-01..2026-06-30."""
    env = setup_environment(
        plan_overrides={
            "plan_code": "OVL-2",
            "name": "Overlap Plan Two",
            "deductible_individual_cents": 0,
            "oop_max_individual_cents": 1000000,
            "coinsurance_member_pct": 0,
        },
        provider_overrides={"npi": "1000000015", "name": "Omicron Group"},
        with_member=False,
        coverages=None,
    )
    env["contract"] = draft_contract(
        env["provider"]["id"],
        env["plan"]["id"],
        effective_date="2026-01-01",
        term_date="2026-06-30",
        pricing_method="PCT_OF_FEE_SCHEDULE",
        contract_pct=0.900,
    )
    return env


def setup_seeded_accumulator_finalized_claim() -> dict:
    """A finalized claim posted on top of a manually seeded accumulator, so the
    compensating void has a non-zero baseline to return to."""
    env = setup_environment(
        plan_overrides={
            "plan_code": "INV-1",
            "name": "Invariant Plan",
            "deductible_individual_cents": 50000,
            "oop_max_individual_cents": 300000,
            "coinsurance_member_pct": 0.20,
        },
        provider_overrides={"npi": "1000000016", "name": "Pi Clinic"},
        member_overrides={"member_number": "M-INV-1"},
        rates=[("73721", 40000, "2026-01-01")],
    )
    env["accumulator_baseline"] = seed_accumulator(
        env["member"]["id"], deductible_delta_cents=12000, oop_delta_cents=15000
    )
    env["adjudicated_claim"] = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 1, 60000, "2026-02-10")], "CLM-INV-1"
    )
    env["claim"] = finalize(env["adjudicated_claim"]["id"])
    env["accumulator_after_finalize"] = get_accumulator(env["member"]["id"])
    return env


def setup_finalized_claim_holding_four_units() -> dict:
    """A FINALIZED claim whose PAID line holds four units of a six-unit grant."""
    env = setup_auth_gated_environment(
        authorized_units=6,
        plan_overrides={"plan_code": "INV-2", "name": "Invariant Plan Two"},
        provider_overrides={"npi": "1000000017", "name": "Rho Imaging"},
        member_overrides={"member_number": "M-INV-2"},
        rule_code="MP-73721-AUTH-G",
    )
    adjudicated = submit_and_adjudicate(
        env, [claim_line_payload(1, "73721", 4, 200000, "2026-02-10")], "CLM-INV-2"
    )
    env["claim"] = finalize(adjudicated["id"])
    env["authorization_before"] = get_authorization(env["authorization"]["id"])
    return env
