"""Composite setup helpers (PRD §3 workflows).

Every helper builds its preconditions from scratch through the public API —
the test runner restarts the server before each test, so nothing carries over.
All setup calls use the lenient get_success_data() so failures surface as
clear "Setup step failed" errors.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_accept_proposal_payload,
    create_appeal_payload,
    create_claim_line_payload,
    create_claim_payload,
    create_clock_payload,
    create_contract_proposal_payload,
    create_contract_term_payload,
    create_network_agreement_payload,
    create_payer_contract_payload,
    create_payer_payload,
    create_rate_amendment_payload,
    create_rate_escalator_payload,
    create_record_outcome_payload,
    create_remittance_payload,
    create_stop_loss_provision_payload,
    create_write_off_payload,
)
from .test_users import (
    TEST_USERS,
    make_contract_analyst_headers,
    make_contract_manager_headers,
    make_finance_director_headers,
    make_recovery_manager_headers,
    make_revenue_integrity_analyst_headers,
    make_system_admin_headers,
)

CM = TEST_USERS["contract_manager_headers"]
CA = TEST_USERS["contract_analyst_headers"]
RIA = TEST_USERS["revenue_integrity_analyst_headers"]
RM = TEST_USERS["recovery_manager_headers"]
FD = TEST_USERS["finance_director_headers"]
SA = TEST_USERS["system_admin_headers"]
AUD = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: payer, contract, term, claim primitives
# ---------------------------------------------------------------------------

def create_test_payer(headers=None, **overrides) -> dict:
    resp = api_client.create_payer(create_payer_payload(**overrides), headers or CM)
    return get_success_data(resp)


def create_draft_contract(payer_id: str, headers=None, **overrides) -> dict:
    resp = api_client.create_payer_contract(
        create_payer_contract_payload(payer_id, **overrides), headers or CA
    )
    return get_success_data(resp)


def add_contract_term(contract_id: str, headers=None, **overrides) -> dict:
    resp = api_client.create_contract_term(
        create_contract_term_payload(contract_id, **overrides), headers or CA
    )
    return get_success_data(resp)


def activate_contract(contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.activate_payer_contract(contract_id, headers or CM))


def setup_active_contract(
    service_category: str = "INPATIENT_MEDICAL",
    rate_model: str = "PER_DIEM",
    base_rate_cents=100000,
    percent_of_charge_bp=None,
    payer_overrides: dict = None,
    contract_overrides: dict = None,
    term_overrides: dict = None,
) -> dict:
    """Payer + DRAFT contract + one rate term + activation.

    Returns {"payer", "contract", "term", "contract_version"} where
    contract_version is the PayerContract.version observed right after
    activation (the OCC token for amendment/proposal creation).
    """
    payer = create_test_payer(**(payer_overrides or {}))
    contract = create_draft_contract(payer["id"], **(contract_overrides or {}))
    term_kwargs = {"service_category": service_category, "rate_model": rate_model}
    if base_rate_cents is not None:
        term_kwargs["base_rate_cents"] = base_rate_cents
    if percent_of_charge_bp is not None:
        term_kwargs["percent_of_charge_bp"] = percent_of_charge_bp
    term_kwargs.update(term_overrides or {})
    term = add_contract_term(contract["id"], **term_kwargs)
    contract = activate_contract(contract["id"])
    return {
        "payer": payer,
        "contract": contract,
        "term": term,
        "contract_version": contract["version"],
    }


def create_test_claim(payer_id: str, headers=None, **overrides) -> dict:
    resp = api_client.create_claim(create_claim_payload(payer_id, **overrides), headers or RIA)
    return get_success_data(resp)


def add_claim_line(claim_id: str, headers=None, **overrides) -> dict:
    resp = api_client.add_claim_line(
        claim_id, create_claim_line_payload(**overrides), headers or RIA
    )
    return get_success_data(resp)


def price_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.price_claim(claim_id, headers or RIA))


def reprice_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.reprice_claim(claim_id, headers or RIA))


def get_claim(claim_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_claim(claim_id, headers or RIA))


def list_claim_lines(claim_id: str, headers=None) -> list:
    resp = api_client.list_claim_lines(claim_id, headers or RIA)
    data, _meta = validate_paginated(resp)
    return data


# ---------------------------------------------------------------------------
# Tier 3: priced-claim and case setups
# ---------------------------------------------------------------------------

DEFAULT_CLAIM_WINDOW = {"admission_date": "2026-06-01", "discharge_date": "2026-06-03"}


def setup_priced_claim(
    payer_overrides: dict = None,
    contract_overrides: dict = None,
    service_category: str = "INPATIENT_MEDICAL",
    rate_model: str = "PER_DIEM",
    base_rate_cents=100000,
    percent_of_charge_bp=None,
    term_overrides: dict = None,
    claim_overrides: dict = None,
    lines: list = None,
) -> dict:
    """Active contract + claim with lines, priced once (PROSPECTIVE).

    Default claim: stay 2026-06-01..2026-06-03 (2 per-diem nights), billed
    500000, one 250000 line -> expected 200000 under a 100000/day PER_DIEM term.
    Returns ctx dict with payer/contract/term/contract_version/claim/lines.
    """
    ctx = setup_active_contract(
        service_category=service_category,
        rate_model=rate_model,
        base_rate_cents=base_rate_cents,
        percent_of_charge_bp=percent_of_charge_bp,
        payer_overrides=payer_overrides,
        contract_overrides=contract_overrides,
        term_overrides=term_overrides,
    )
    claim_kw = {"service_category": service_category}
    claim_kw.update(DEFAULT_CLAIM_WINDOW)
    claim_kw.update(claim_overrides or {})
    claim = create_test_claim(ctx["payer"]["id"], **claim_kw)
    line_specs = lines if lines is not None else [{}]
    created_lines = [add_claim_line(claim["id"], **spec) for spec in line_specs]
    ctx["claim"] = price_claim(claim["id"])
    ctx["lines"] = created_lines
    return ctx


def post_remittance(claim_id: str, paid_amount_cents: int, headers=None, **overrides) -> dict:
    payload = create_remittance_payload(
        claim_id, paid_amount_cents=paid_amount_cents, **overrides
    )
    return get_success_data(api_client.create_remittance(payload, headers or RIA))


def list_cases_for_claim(claim_id: str, headers=None) -> list:
    resp = api_client.list_underpayment_cases(
        headers or RIA, params={"claim_id": claim_id}
    )
    data, _meta = validate_paginated(resp)
    return data


def get_single_case_for_claim(claim_id: str, headers=None) -> dict:
    cases = list_cases_for_claim(claim_id, headers)
    assert len(cases) == 1, (
        f"Expected exactly one underpayment case for claim {claim_id}, got {len(cases)}"
    )
    return cases[0]


def get_case(case_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_underpayment_case(case_id, headers or RM))


def setup_case(paid_amount_cents: int = 100000, remittance_overrides: dict = None,
               **priced_kwargs) -> dict:
    """Priced claim + one remittance that queues a QUEUED underpayment case.

    Returns ctx with payer/contract/term/claim/lines/remittance/case.
    """
    ctx = setup_priced_claim(**priced_kwargs)
    remittance = post_remittance(
        ctx["claim"]["id"], paid_amount_cents, **(remittance_overrides or {})
    )
    ctx["remittance"] = remittance
    ctx["case"] = get_single_case_for_claim(ctx["claim"]["id"])
    return ctx


def pick_up_case(case_id: str, user_id: str = "rm-1") -> dict:
    return get_success_data(
        api_client.pick_up_underpayment_case(
            case_id, make_recovery_manager_headers(user_id)
        )
    )


def setup_case_under_review(claimer_user_id: str = "rm-1", **case_kwargs) -> dict:
    """QUEUED case picked up -> UNDER_REVIEW, claimed by claimer_user_id."""
    ctx = setup_case(**case_kwargs)
    ctx["case"] = pick_up_case(ctx["case"]["id"], claimer_user_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 (appeals): appeal ladder helpers
# ---------------------------------------------------------------------------

def create_appeal(case_id: str, level: int, user_id: str = "rm-1") -> dict:
    return get_success_data(
        api_client.create_appeal(
            create_appeal_payload(case_id, level),
            make_recovery_manager_headers(user_id),
        )
    )


def file_appeal(appeal_id: str, user_id: str = "rm-1") -> dict:
    return get_success_data(
        api_client.file_appeal(appeal_id, make_recovery_manager_headers(user_id))
    )


def record_appeal_outcome(appeal_id: str, outcome: str,
                          recovered_amount_cents=None, user_id: str = "rm-2") -> dict:
    payload = create_record_outcome_payload(outcome)
    if recovered_amount_cents is not None:
        payload["recovered_amount_cents"] = recovered_amount_cents
    return get_success_data(
        api_client.record_appeal_outcome(
            appeal_id, payload, make_recovery_manager_headers(user_id)
        )
    )


def withdraw_appeal(appeal_id: str, user_id: str = "rm-1") -> dict:
    return get_success_data(
        api_client.withdraw_appeal(appeal_id, make_recovery_manager_headers(user_id))
    )


def setup_case_with_filed_appeal(level: int = 1, claimer_user_id: str = "rm-1",
                                 **case_kwargs) -> dict:
    """UNDER_REVIEW case with one appeal created and filed at `level`."""
    ctx = setup_case_under_review(claimer_user_id=claimer_user_id, **case_kwargs)
    appeal = create_appeal(ctx["case"]["id"], level, user_id=claimer_user_id)
    appeal = file_appeal(appeal["id"], user_id=claimer_user_id)
    ctx["appeal"] = appeal
    ctx["case"] = get_case(ctx["case"]["id"])
    return ctx


def escalate_case_with_denied_appeal(case_id: str, level: int,
                                     filer: str = "rm-1",
                                     outcome_recorder: str = "rm-2") -> dict:
    """Create + file + record DENIED for the appeal at `level`. Returns it."""
    appeal = create_appeal(case_id, level, user_id=filer)
    appeal = file_appeal(appeal["id"], user_id=filer)
    return record_appeal_outcome(appeal["id"], "DENIED", user_id=outcome_recorder)


def setup_case_at_mediation(outstanding_hint: int = 50000, **case_kwargs) -> dict:
    """Case driven to MEDIATION: levels 1-3 each filed and DENIED same day.

    Default setup prices a 200000 claim and remits 150000, leaving a 50000
    outstanding balance (below the 100000 arbitration minimum).
    """
    case_kwargs.setdefault("paid_amount_cents", 150000)
    ctx = setup_case_under_review(**case_kwargs)
    case_id = ctx["case"]["id"]
    ctx["appeal_l1"] = escalate_case_with_denied_appeal(case_id, 1)
    ctx["appeal_l2"] = escalate_case_with_denied_appeal(case_id, 2)
    ctx["appeal_l3"] = escalate_case_with_denied_appeal(case_id, 3)
    ctx["case"] = get_case(case_id)
    return ctx


# ---------------------------------------------------------------------------
# Tier 1 (rate content): escalators / amendments / proposals
# ---------------------------------------------------------------------------

def create_escalator(contract_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_rate_escalator(
            create_rate_escalator_payload(contract_id, **overrides), headers or CA
        )
    )


def create_amendment(contract_id: str, expected_contract_version: int,
                     creator_user_id: str = "ca-1", creator_role: str = "analyst",
                     **overrides) -> dict:
    if creator_role == "analyst":
        headers = make_contract_analyst_headers(creator_user_id)
    else:
        headers = make_contract_manager_headers(creator_user_id)
    return get_success_data(
        api_client.create_rate_amendment(
            create_rate_amendment_payload(
                contract_id, expected_contract_version, **overrides
            ),
            headers,
        )
    )


def approve_amendment(amendment_id: str, approver_user_id: str = "cm-2") -> dict:
    return get_success_data(
        api_client.approve_rate_amendment(
            amendment_id, make_contract_manager_headers(approver_user_id)
        )
    )


def get_amendment(amendment_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_rate_amendment(amendment_id, headers or CA))


def create_proposal(contract_id: str, expected_contract_version: int,
                    headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract_proposal(
            create_contract_proposal_payload(
                contract_id, expected_contract_version, **overrides
            ),
            headers or CA,
        )
    )


def get_proposal(proposal_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_contract_proposal(proposal_id, headers or CA))


def get_contract(contract_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_payer_contract(contract_id, headers or CA))


def create_network_agreement(payer_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_network_agreement(
            create_network_agreement_payload(payer_id, **overrides), headers or CA
        )
    )


def add_stop_loss_provision(contract_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_stop_loss_provision(
            create_stop_loss_provision_payload(contract_id, **overrides), headers or CA
        )
    )


def set_clock(to_iso8601: str) -> dict:
    """Advance/rewind the logical clock and run the full sweep (PRD §3.9)."""
    return get_success_data(
        api_client.set_clock(create_clock_payload(to_iso8601), SA)
    )


def list_alerts(headers=None, **params) -> list:
    data, _meta = validate_paginated(api_client.list_contract_alerts(headers or CM, params=params))
    return data
