"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading rule (PRD §2.1):
  * Executor writes use `make_executor_headers(executor_id)` — Executor
    identity is entity_backed:Executor and X-User-ID must equal the
    acting row's id for ownership-gated calls.
  * Beneficiary writes use `make_beneficiary_headers(designation_id)` —
    Beneficiary identity is entity_backed:BeneficiaryDesignation.
  * All other roles are opaque.

Setup helpers use `get_success_data` from the framework so a failed setup
surfaces as a clear "setup failed" error rather than a misleading assertion
failure deep inside a test.
"""
from typing import Optional, Tuple, Dict, Any, List

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_decedent_payload,
    create_estate_payload,
    create_asset_payload,
    create_beneficiary_designation_payload,
    create_executor_payload,
    create_poa_payload,
    activate_poa_payload,
    create_directive_payload,
    create_guardianship_payload,
    create_creditor_claim_payload,
    create_probate_order_payload,
)
from .test_users import (
    make_planner_headers,
    make_judge_headers,
    make_registrar_headers,
    make_creditor_headers,
    make_platform_admin_headers,
    make_executor_headers,
    make_beneficiary_headers,
)


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(to_iso8601: str) -> None:
    """Pin the system clock for deterministic creditor-window and
    72-hour-supersede tests (PRD §3.10)."""
    api_client.set_clock(to_iso8601, make_platform_admin_headers())


# ─── Tier 1: Single-entity create + state advance ─────────────────────────

def create_decedent(
    full_legal_name: str = "Test Decedent",
    date_of_birth: str = "1950-01-01T00:00:00Z",
    domicile_state_code: str = "CA",
    ssn_last4: str = "0001",
    **overrides,
) -> dict:
    payload = create_decedent_payload(
        full_legal_name=full_legal_name,
        date_of_birth=date_of_birth,
        domicile_state_code=domicile_state_code,
        ssn_last4=ssn_last4,
        **overrides,
    )
    return get_success_data(api_client.create_decedent(payload, make_planner_headers()))


def create_estate(decedent_id: str) -> dict:
    payload = create_estate_payload(decedent_id)
    return get_success_data(api_client.create_estate(payload, make_planner_headers()))


def create_asset(
    estate_id: str,
    category: str = "BANK_ACCOUNT",
    description: str = "Test Asset",
    appraised_value_cents: int = 100000,
    beneficiary_designation_id: Optional[str] = None,
) -> dict:
    payload = create_asset_payload(
        estate_id=estate_id,
        category=category,
        description=description,
        appraised_value_cents=appraised_value_cents,
        beneficiary_designation_id=beneficiary_designation_id,
    )
    return get_success_data(api_client.create_asset(payload, make_planner_headers()))


def create_designation(
    estate_id: str,
    beneficiary_full_name: str = "Test Beneficiary",
    relationship: str = "CHILD",
    share_basis_points: int = 10000,
    contingent_of_designation_id: Optional[str] = None,
) -> dict:
    payload = create_beneficiary_designation_payload(
        estate_id=estate_id,
        beneficiary_full_name=beneficiary_full_name,
        relationship=relationship,
        share_basis_points=share_basis_points,
        contingent_of_designation_id=contingent_of_designation_id,
    )
    return get_success_data(
        api_client.create_beneficiary_designation(payload, make_planner_headers()),
    )


def activate_designation(designation_id: str) -> dict:
    return get_success_data(
        api_client.activate_beneficiary_designation(
            designation_id, make_planner_headers(),
        ),
    )


def create_executor(
    estate_id: str,
    full_legal_name: str = "Test Executor",
    role_type: str = "EXECUTOR",
    is_also_beneficiary: bool = False,
) -> dict:
    payload = create_executor_payload(
        estate_id=estate_id,
        full_legal_name=full_legal_name,
        role_type=role_type,
        is_also_beneficiary=is_also_beneficiary,
    )
    return get_success_data(api_client.create_executor(payload, make_planner_headers()))


def accept_executor(executor_id: str) -> dict:
    return get_success_data(
        api_client.accept_executor(executor_id, make_executor_headers(executor_id)),
    )


def finalize_plan(estate_id: str) -> dict:
    return get_success_data(
        api_client.finalize_plan(estate_id, make_planner_headers()),
    )


def register_death(decedent_id: str, date_of_death: str) -> dict:
    return get_success_data(
        api_client.register_death(
            decedent_id, {"date_of_death": date_of_death}, make_registrar_headers(),
        ),
    )


def file_for_probate(estate_id: str, executor_id: str) -> dict:
    return get_success_data(
        api_client.file_for_probate(estate_id, make_executor_headers(executor_id)),
    )


def create_probate_order(
    estate_id: str, order_type: str, judge_user_id: str = "test-judge-1",
) -> dict:
    payload = create_probate_order_payload(
        estate_id=estate_id, order_type=order_type, judge_user_id=judge_user_id,
    )
    return get_success_data(api_client.create_probate_order(payload, make_judge_headers()))


def enter_probate_order(order_id: str) -> dict:
    return get_success_data(
        api_client.enter_probate_order(order_id, make_judge_headers()),
    )


def create_poa(
    decedent_id: str,
    agent_full_name: str = "Test Agent",
    scope: str = "FINANCIAL",
) -> dict:
    payload = create_poa_payload(decedent_id, agent_full_name, scope)
    return get_success_data(api_client.create_poa(payload, make_planner_headers()))


def activate_poa(
    poa_id: str, effective_at: str, effective_until: Optional[str] = None,
) -> dict:
    payload = activate_poa_payload(effective_at, effective_until)
    return get_success_data(
        api_client.activate_poa(poa_id, payload, make_planner_headers()),
    )


def create_directive(
    decedent_id: str,
    directive_type: str = "LIVING_WILL",
    physician_attester_user_id: Optional[str] = None,
    hipaa_authorized_recipients: Optional[List[str]] = None,
) -> dict:
    payload = create_directive_payload(
        decedent_id=decedent_id,
        directive_type=directive_type,
        physician_attester_user_id=physician_attester_user_id,
        hipaa_authorized_recipients=hipaa_authorized_recipients,
    )
    return get_success_data(api_client.create_directive(payload, make_planner_headers()))


def witness_directive(directive_id: str) -> dict:
    return get_success_data(
        api_client.witness_directive(directive_id, make_planner_headers()),
    )


def notarize_directive(directive_id: str) -> dict:
    return get_success_data(
        api_client.notarize_directive(directive_id, make_planner_headers()),
    )


def create_guardianship(
    estate_id: str,
    ward_full_name: str = "Test Ward",
    ward_date_of_birth: str = "2015-01-01T00:00:00Z",
    guardian_full_name: str = "Test Guardian",
) -> dict:
    payload = create_guardianship_payload(
        estate_id=estate_id,
        ward_full_name=ward_full_name,
        ward_date_of_birth=ward_date_of_birth,
        guardian_full_name=guardian_full_name,
    )
    return get_success_data(api_client.create_guardianship(payload, make_planner_headers()))


def create_creditor_claim(
    estate_id: str,
    creditor_name: str = "Test Creditor",
    amount_cents: int = 10000,
    claim_class: str = "UNSECURED",
    filed_at: str = "2026-02-01T00:00:00Z",
) -> dict:
    payload = create_creditor_claim_payload(
        estate_id=estate_id,
        creditor_name=creditor_name,
        amount_cents=amount_cents,
        claim_class=claim_class,
        filed_at=filed_at,
    )
    return get_success_data(
        api_client.create_creditor_claim(payload, make_creditor_headers()),
    )


def allow_creditor_claim(claim_id: str, executor_id: str) -> dict:
    return get_success_data(
        api_client.allow_creditor_claim(claim_id, make_executor_headers(executor_id)),
    )


# ─── Tier 2: Bootstrap an estate to a particular lifecycle state ──────────

def bootstrap_estate_in_draft(
    clock: str = "2026-01-01T00:00:00Z",
    decedent_name: str = "Test Decedent",
    domicile_state_code: str = "CA",
    ssn_last4: str = "0001",
) -> Tuple[dict, dict]:
    """Decedent + Estate, both in initial state. Returns (decedent, estate)."""
    set_clock(clock)
    dec = create_decedent(
        full_legal_name=decedent_name,
        domicile_state_code=domicile_state_code,
        ssn_last4=ssn_last4,
    )
    estate = create_estate(dec["id"])
    return dec, estate


def bootstrap_estate_in_alive(
    clock: str = "2026-01-01T00:00:00Z",
    decedent_name: str = "Test Decedent",
    domicile_state_code: str = "CA",
    ssn_last4: str = "0001",
    asset_value_cents: int = 100000,
    asset_category: str = "BANK_ACCOUNT",
    executor_is_also_beneficiary: bool = False,
) -> Dict[str, Any]:
    """Decedent + Estate in ALIVE + one Asset (INCLUDED) + one designation
    (ACTIVE 10000 bp) + one Executor (ACCEPTED).

    Returns a dict with keys: decedent, estate, asset, designation, executor.
    The estate field is the response from POST /finalize-plan (so includes
    fresh gross_estate_value_cents and version after promotion).
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name=decedent_name,
        domicile_state_code=domicile_state_code,
        ssn_last4=ssn_last4,
    )
    estate = create_estate(dec["id"])
    asset = create_asset(
        estate["id"], category=asset_category, description="Bootstrap Asset",
        appraised_value_cents=asset_value_cents,
    )
    designation = create_designation(estate["id"], "Bootstrap Heir", "CHILD", 10000)
    executor = create_executor(
        estate["id"], "Bootstrap Executor", "EXECUTOR",
        is_also_beneficiary=executor_is_also_beneficiary,
    )
    executor = accept_executor(executor["id"])
    estate_alive = finalize_plan(estate["id"])
    return {
        "decedent": dec,
        "estate": estate_alive,
        "asset": asset,
        "designation": designation,
        "executor": executor,
    }


def bootstrap_estate_in_deceased(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Walks DRAFT -> ALIVE -> DECEASED via register-death.

    Returns dict with decedent, estate (post-death), asset, designation, executor.
    """
    ctx = bootstrap_estate_in_alive(clock=clock, **overrides)
    register_death(ctx["decedent"]["id"], date_of_death)
    # Refresh the estate so the caller sees DECEASED status & new version.
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    return ctx


def bootstrap_estate_in_probate_pending(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Walks through to PROBATE_PENDING via file-for-probate."""
    ctx = bootstrap_estate_in_deceased(
        clock=clock, date_of_death=date_of_death, **overrides,
    )
    file_for_probate(ctx["estate"]["id"], ctx["executor"]["id"])
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    return ctx


def bootstrap_estate_in_probate_open(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Walks through to PROBATE_OPEN by entering an OPEN_PROBATE order.

    Adds `open_order` key to the returned context.
    """
    ctx = bootstrap_estate_in_probate_pending(
        clock=clock, date_of_death=date_of_death, **overrides,
    )
    order = create_probate_order(ctx["estate"]["id"], "OPEN_PROBATE")
    enter_probate_order(order["id"])
    ctx["open_order"] = order
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    ctx["executor"] = get_success_data(
        api_client.get_executor(
            ctx["executor"]["id"], make_executor_headers(ctx["executor"]["id"]),
        ),
    )
    return ctx


def bootstrap_estate_in_administration(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Walks through to ADMINISTRATION by entering an APPROVE_INVENTORY order
    on top of an open probate. Adds `approve_order` key.
    """
    ctx = bootstrap_estate_in_probate_open(
        clock=clock, date_of_death=date_of_death, **overrides,
    )
    order = create_probate_order(ctx["estate"]["id"], "APPROVE_INVENTORY")
    enter_probate_order(order["id"])
    ctx["approve_order"] = order
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    return ctx


def bootstrap_estate_closed(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    **overrides,
) -> Dict[str, Any]:
    """Walks all the way through CLOSED.

    Path: ADMINISTRATION -> FINAL_DISTRIBUTION entered -> CLOSE_ESTATE entered.
    Requires that no ALLOWED claims exist (so FINAL_DISTRIBUTION precondition
    holds). Adds `final_order` and `close_order` keys.
    """
    ctx = bootstrap_estate_in_administration(
        clock=clock, date_of_death=date_of_death, **overrides,
    )
    # Trigger at least one net_taxable_estate calculation before CLOSE_ESTATE
    # (the close-estate precondition requires net_taxable_estate has run).
    get_success_data(
        api_client.get_net_taxable_summary(
            ctx["estate"]["id"], make_executor_headers(ctx["executor"]["id"]),
        ),
    )
    final_order = create_probate_order(ctx["estate"]["id"], "FINAL_DISTRIBUTION")
    enter_probate_order(final_order["id"])
    close_order = create_probate_order(ctx["estate"]["id"], "CLOSE_ESTATE")
    enter_probate_order(close_order["id"])
    ctx["final_order"] = final_order
    ctx["close_order"] = close_order
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    ctx["executor"] = get_success_data(
        api_client.get_executor(
            ctx["executor"]["id"], make_executor_headers(ctx["executor"]["id"]),
        ),
    )
    return ctx


# ─── Tier 3: Specialized fixtures for difficulty design instances ─────────

def bootstrap_probate_open_with_assets(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-02-15T00:00:00Z",
    asset_value_cents: int = 5000000,
    asset_category: str = "REAL_ESTATE",
    domicile_state_code: str = "CA",
) -> Dict[str, Any]:
    """Estate walked to PROBATE_OPEN with one INCLUDED asset, ready for the
    provisional-variant net_taxable_estate calculation.

    PRD §3.6 only allows creditor-claim allowance while the estate is in
    ADMINISTRATION, so we cannot place a claim in ALLOWED while in
    PROBATE_OPEN. The provisional-variant assertion therefore uses
    `allowed_claims_total_cents = 0` and `net = live_gross - exempt`.
    Returns context dict with decedent, estate, asset, executor, designation.
    """
    return bootstrap_estate_in_probate_open(
        clock=clock, date_of_death=date_of_death,
        asset_value_cents=asset_value_cents,
        asset_category=asset_category,
        domicile_state_code=domicile_state_code,
    )


def bootstrap_administration_with_assets_and_claim(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-02-15T00:00:00Z",
    asset_value_cents: int = 5000000,
    asset_category: str = "REAL_ESTATE",
    claim_amount_cents: int = 100000,
    claim_filed_at: str = "2026-04-01T00:00:00Z",
    claim_clock_advance: str = "2026-04-01T00:00:00Z",
    domicile_state_code: str = "CA",
) -> Dict[str, Any]:
    """Estate in ADMINISTRATION with one ALLOWED creditor claim.

    Used by the final-variant net_taxable_estate test. The APPROVE_INVENTORY
    order has been entered (so the estate is in ADMINISTRATION and the
    inventory snapshot is frozen). The creditor claim was filed and allowed
    while the estate is in ADMINISTRATION (PRD §3.6: allowance is permitted
    only in ADMINISTRATION and within the 120-day window).

    Returns context dict including decedent, estate, asset (home), executor,
    designation, claim, approve_order.
    """
    ctx = bootstrap_estate_in_probate_open(
        clock=clock, date_of_death=date_of_death,
        asset_value_cents=asset_value_cents,
        asset_category=asset_category,
        domicile_state_code=domicile_state_code,
    )
    # Enter APPROVE_INVENTORY → estate to ADMINISTRATION, snapshot frozen.
    approve_order = create_probate_order(ctx["estate"]["id"], "APPROVE_INVENTORY")
    enter_probate_order(approve_order["id"])
    ctx["approve_order"] = approve_order
    # Advance clock to a post-probate_opened_at instant within the 120-day
    # window, then file + allow the claim during ADMINISTRATION.
    set_clock(claim_clock_advance)
    claim = create_creditor_claim(
        ctx["estate"]["id"], creditor_name="BigBank",
        amount_cents=claim_amount_cents, claim_class="UNSECURED",
        filed_at=claim_filed_at,
    )
    allow_creditor_claim(claim["id"], ctx["executor"]["id"])
    ctx["claim"] = claim
    # Refresh estate to reflect ADMINISTRATION status + frozen snapshot.
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    return ctx


def bootstrap_administration_with_n_claims(
    claim_specs: List[Dict[str, Any]],
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    gross_asset_value_cents: int = 1000000,
    domicile_state_code: str = "NY",
) -> Dict[str, Any]:
    """Estate in ADMINISTRATION with one bank asset and N ALLOWED claims.

    claim_specs: list of dicts each with keys creditor_name, amount_cents,
    claim_class, filed_at.

    The order of claims is preserved (they are created in list order so
    `created_at` strictly ascending follows the list).

    Returns context with decedent, estate, executor, designation, asset,
    and `claims` (list of allowed-claim dicts in input order).
    """
    ctx = bootstrap_estate_in_probate_open(
        clock=clock,
        date_of_death=date_of_death,
        asset_value_cents=gross_asset_value_cents,
        asset_category="BANK_ACCOUNT",
        domicile_state_code=domicile_state_code,
    )
    claims = []
    for spec in claim_specs:
        c = create_creditor_claim(
            ctx["estate"]["id"],
            creditor_name=spec["creditor_name"],
            amount_cents=spec["amount_cents"],
            claim_class=spec["claim_class"],
            filed_at=spec["filed_at"],
        )
        claims.append(c)
    # Now enter APPROVE_INVENTORY (state becomes ADMINISTRATION).
    order = create_probate_order(ctx["estate"]["id"], "APPROVE_INVENTORY")
    enter_probate_order(order["id"])
    ctx["approve_order"] = order
    # Allow each claim in order.
    allowed_claims = []
    for c in claims:
        allowed_claims.append(
            allow_creditor_claim(c["id"], ctx["executor"]["id"]),
        )
    ctx["claims"] = allowed_claims
    ctx["estate"] = get_success_data(
        api_client.get_estate(ctx["estate"]["id"], make_planner_headers()),
    )
    return ctx


def bootstrap_intestacy_setup(
    clock: str = "2026-01-01T00:00:00Z",
    domicile_state_code: str = "CA",
    spouse_count: int = 1,
    child_count: int = 3,
) -> Dict[str, Any]:
    """Decedent + Estate (DRAFT) + N spouse + M child designations (DRAFT),
    each created at strictly increasing 1-second clock intervals so their
    `created_at` timestamps are monotonic. Returns context with `spouses` and
    `children` lists of designation dicts."""
    set_clock(clock)
    dec = create_decedent(domicile_state_code=domicile_state_code, ssn_last4="3456")
    estate = create_estate(dec["id"])
    # Bump clock 1s between each designation create.
    from datetime import datetime, timedelta, timezone

    def _parse(s):
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)

    def _fmt(dt):
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    base = _parse(clock)
    offset = 0

    spouses = []
    for i in range(spouse_count):
        offset += 1
        set_clock(_fmt(base + timedelta(seconds=offset)))
        s = create_designation(
            estate["id"], f"Spouse {i+1}", "SPOUSE", 1,
        )
        spouses.append(s)

    children = []
    for i in range(child_count):
        offset += 1
        set_clock(_fmt(base + timedelta(seconds=offset)))
        c = create_designation(
            estate["id"], f"Child {chr(ord('A')+i)}", "CHILD", 1,
        )
        children.append(c)

    return {
        "decedent": dec,
        "estate": estate,
        "spouses": spouses,
        "children": children,
    }


def bootstrap_executor_with_beneficiary_flag(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
    is_also_beneficiary: bool = True,
) -> Dict[str, Any]:
    """Walks through to PROBATE_PENDING with executor.is_also_beneficiary=True.

    Then drafts an OPEN_PROBATE order (without entering). Returns ctx with
    decedent, estate, asset, designation, executor, open_order.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Beneficiary Executor",
        domicile_state_code="CA",
        ssn_last4="1010",
    )
    estate = create_estate(dec["id"])
    asset = create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
    designation = create_designation(estate["id"], "Heir", "CHILD", 10000)
    executor = create_executor(
        estate["id"], "Exec Beneficiary", "EXECUTOR",
        is_also_beneficiary=is_also_beneficiary,
    )
    executor = accept_executor(executor["id"])
    estate_alive = finalize_plan(estate["id"])
    register_death(dec["id"], date_of_death)
    file_for_probate(estate["id"], executor["id"])
    open_order = create_probate_order(estate["id"], "OPEN_PROBATE")
    estate_pp = get_success_data(
        api_client.get_estate(estate["id"], make_planner_headers()),
    )
    return {
        "decedent": dec,
        "estate": estate_pp,
        "asset": asset,
        "designation": designation,
        "executor": executor,
        "open_order": open_order,
    }


def bootstrap_decedent_with_two_active_poas(
    clock: str = "2026-01-01T00:00:00Z",
    poa_a_start: str = "2026-01-01T00:00:00Z",
    poa_a_end: str = "2026-03-01T00:00:00Z",
    poa_scope: str = "FINANCIAL",
) -> Dict[str, Any]:
    """Decedent with ONE active POA spanning [poa_a_start, poa_a_end)
    plus two DRAFT POAs (named poa_b, poa_c) that callers can activate
    with their own intervals.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="POA Subject", domicile_state_code="NY", ssn_last4="2020",
    )
    poa_a = create_poa(dec["id"], "Agent X", poa_scope)
    activate_poa(poa_a["id"], poa_a_start, poa_a_end)
    poa_b = create_poa(dec["id"], "Agent Y", poa_scope)
    poa_c = create_poa(dec["id"], "Agent Z", poa_scope)
    return {
        "decedent": dec,
        "poa_a": poa_a,
        "poa_b": poa_b,
        "poa_c": poa_c,
    }


def bootstrap_estate_with_guardianship(
    clock: str = "2026-01-01T00:00:00Z",
    ward_full_name: str = "Junior Wei",
    ward_date_of_birth: str = "2020-06-06T00:00:00Z",
    domicile_state_code: str = "CA",
) -> Dict[str, Any]:
    """Decedent + Estate + Guardianship (PROPOSED). Returns ctx with
    decedent, estate, guardianship."""
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Ward Parent",
        domicile_state_code=domicile_state_code,
        ssn_last4="3030",
    )
    estate = create_estate(dec["id"])
    guard = create_guardianship(
        estate["id"], ward_full_name=ward_full_name,
        ward_date_of_birth=ward_date_of_birth,
        guardian_full_name="Test Guardian",
    )
    return {"decedent": dec, "estate": estate, "guardianship": guard}


def bootstrap_estate_with_contingent_designation_chain(
    clock: str = "2026-01-01T00:00:00Z",
    spouse_bp: int = 4000,
    primary_bp: int = 6000,
    contingent_bp: int = 6000,
) -> Dict[str, Any]:
    """Estate ALIVE with:
      - SPOUSE designation @ spouse_bp (ACTIVE)
      - CHILD primary designation @ primary_bp (ACTIVE)
      - CHILD contingent designation @ contingent_bp (DRAFT, contingent of primary)
    Returns ctx with decedent, estate (ALIVE), spouse, primary, contingent,
    executor.

    PRD §3.1: a designation with `contingent_of_designation_id` set requires
    the referenced parent to be currently ACTIVE — so the contingent row
    must be created AFTER finalize_plan has promoted the primary to ACTIVE.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Contingent Subject",
        domicile_state_code="NY",
        ssn_last4="4040",
    )
    estate = create_estate(dec["id"])
    create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 1000000)
    spouse = create_designation(
        estate["id"], "Spouse V", "SPOUSE", spouse_bp,
    )
    primary = create_designation(
        estate["id"], "Primary Child", "CHILD", primary_bp,
    )
    executor = create_executor(estate["id"], "Exec V", "EXECUTOR", False)
    executor = accept_executor(executor["id"])
    # Finalize plan first so spouse + primary advance DRAFT -> ACTIVE.
    finalize_plan(estate["id"])
    # Now primary is ACTIVE, so creating a contingent referencing it
    # passes the PRD §3.1 ERR_CONTINGENT_PARENT_INVALID check.
    contingent = create_designation(
        estate["id"], "Contingent Child", "CHILD", contingent_bp,
        contingent_of_designation_id=primary["id"],
    )
    # Re-fetch estate to capture post-finalize version (revoke's OCC token).
    estate_alive = get_success_data(
        api_client.get_estate(estate["id"], make_planner_headers()),
    )
    # Re-fetch primary and spouse to reflect ACTIVE status.
    primary = get_success_data(
        api_client.get_beneficiary_designation(
            primary["id"], make_planner_headers(),
        ),
    )
    spouse = get_success_data(
        api_client.get_beneficiary_designation(
            spouse["id"], make_planner_headers(),
        ),
    )
    return {
        "decedent": dec,
        "estate": estate_alive,
        "spouse": spouse,
        "primary": primary,
        "contingent": contingent,
        "executor": executor,
    }


def bootstrap_estate_in_alive_with_two_assets(
    clock: str = "2026-01-01T00:00:00Z",
    real_estate_value_cents: int = 500000,
    bank_value_cents: int = 300000,
) -> Dict[str, Any]:
    """Two-asset estate (REAL_ESTATE + BANK_ACCOUNT) walked through to
    PROBATE_OPEN. Returns ctx with both asset dicts as `real_estate_asset`
    and `bank_asset`, plus the usual keys.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Two-Asset Subject",
        domicile_state_code="TX", ssn_last4="5050",
    )
    estate = create_estate(dec["id"])
    re_asset = create_asset(
        estate["id"], "REAL_ESTATE", "Home", real_estate_value_cents,
    )
    bk_asset = create_asset(
        estate["id"], "BANK_ACCOUNT", "Chase", bank_value_cents,
    )
    create_designation(estate["id"], "Heir W", "CHILD", 10000)
    executor = create_executor(estate["id"], "Exec W", "EXECUTOR", False)
    executor = accept_executor(executor["id"])
    estate_alive = finalize_plan(estate["id"])
    register_death(dec["id"], "2026-01-15T00:00:00Z")
    file_for_probate(estate["id"], executor["id"])
    open_order = create_probate_order(estate["id"], "OPEN_PROBATE")
    enter_probate_order(open_order["id"])
    estate_open = get_success_data(
        api_client.get_estate(estate["id"], make_planner_headers()),
    )
    return {
        "decedent": dec,
        "estate": estate_open,
        "real_estate_asset": re_asset,
        "bank_asset": bk_asset,
        "executor": executor,
    }


def bootstrap_estate_with_two_active_designations(
    clock: str = "2026-01-01T00:00:00Z",
    a_bp: int = 6000,
    b_bp: int = 4000,
) -> Dict[str, Any]:
    """Estate ALIVE with two CHILD designations both ACTIVE (totaling 10000bp).
    Returns ctx with decedent, estate (ALIVE), designation_a, designation_b,
    executor.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Two-Designation Subject",
        domicile_state_code="CA",
        ssn_last4="0024",
    )
    estate = create_estate(dec["id"])
    create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
    a = create_designation(estate["id"], "Ben A", "CHILD", a_bp)
    b = create_designation(estate["id"], "Ben B", "CHILD", b_bp)
    executor = create_executor(estate["id"], "Exec R", "EXECUTOR", False)
    executor = accept_executor(executor["id"])
    estate_alive = finalize_plan(estate["id"])
    return {
        "decedent": dec,
        "estate": estate_alive,
        "designation_a": a,
        "designation_b": b,
        "executor": executor,
    }


def bootstrap_estate_in_probate_open_with_beneficiary(
    clock: str = "2026-01-01T00:00:00Z",
    date_of_death: str = "2026-01-15T00:00:00Z",
) -> Dict[str, Any]:
    """Estate in PROBATE_OPEN with one ACTIVE designation (returned as
    `beneficiary`) whose id can be used as Beneficiary.X-User-ID."""
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Contestable Subject",
        domicile_state_code="NY",
        ssn_last4="1111",
    )
    estate = create_estate(dec["id"])
    create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
    beneficiary = create_designation(estate["id"], "Heir J", "CHILD", 10000)
    executor = create_executor(estate["id"], "Exec J", "EXECUTOR", False)
    executor = accept_executor(executor["id"])
    finalize_plan(estate["id"])
    register_death(dec["id"], date_of_death)
    file_for_probate(estate["id"], executor["id"])
    open_order = create_probate_order(estate["id"], "OPEN_PROBATE")
    enter_probate_order(open_order["id"])
    estate_open = get_success_data(
        api_client.get_estate(estate["id"], make_planner_headers()),
    )
    return {
        "decedent": dec,
        "estate": estate_open,
        "beneficiary": beneficiary,
        "executor": executor,
        "open_order": open_order,
    }


def bootstrap_estate_with_non_durable_and_durable_poas(
    clock: str = "2026-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Estate in ALIVE; decedent has ACTIVE FINANCIAL (non-durable) and ACTIVE
    DURABLE_FINANCIAL POAs; also an IRA asset with beneficiary designation.

    Returns ctx with decedent, estate (ALIVE), poa_non_durable, poa_durable,
    ira_asset (with beneficiary), bank_asset (no beneficiary), ira_designation,
    executor.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="Cascade Subject", domicile_state_code="IL", ssn_last4="3333",
    )
    estate = create_estate(dec["id"])
    ira_ben = create_designation(estate["id"], "Heir L", "CHILD", 10000)
    ira_asset = create_asset(
        estate["id"], "RETIREMENT_IRA", "Vanguard IRA", 1000000,
        beneficiary_designation_id=ira_ben["id"],
    )
    bank_asset = create_asset(estate["id"], "BANK_ACCOUNT", "Chase", 500000)
    executor = create_executor(estate["id"], "Exec L", "EXECUTOR", False)
    executor = accept_executor(executor["id"])
    poa_nd = create_poa(dec["id"], "Agent F", "FINANCIAL")
    activate_poa(poa_nd["id"], "2026-01-02T00:00:00Z")
    poa_d = create_poa(dec["id"], "Agent H", "DURABLE_HEALTHCARE")
    activate_poa(poa_d["id"], "2026-01-02T00:00:00Z")
    estate_alive = finalize_plan(estate["id"])
    return {
        "decedent": dec,
        "estate": estate_alive,
        "ira_asset": ira_asset,
        "bank_asset": bank_asset,
        "ira_designation": ira_ben,
        "poa_non_durable": poa_nd,
        "poa_durable": poa_d,
        "executor": executor,
    }


def bootstrap_two_scope_poas_on_decedent(
    clock: str = "2026-01-01T00:00:00Z",
    scope_a: str = "FINANCIAL",
    scope_b: str = "DURABLE_FINANCIAL",
) -> Dict[str, Any]:
    """Decedent only (no estate); one ACTIVE POA of `scope_a` and one ACTIVE
    POA of `scope_b`. Returns ctx with decedent, poa_a, poa_b.

    Used for the cascade-terminates-non-durable corner test.
    """
    set_clock(clock)
    dec = create_decedent(
        full_legal_name="POA Cascade Subject",
        domicile_state_code="NY",
        ssn_last4="0026",
    )
    estate = create_estate(dec["id"])
    create_asset(estate["id"], "BANK_ACCOUNT", "Acct", 100000)
    create_designation(estate["id"], "Heir T", "CHILD", 10000)
    executor = create_executor(estate["id"], "Exec T", "EXECUTOR", False)
    accept_executor(executor["id"])
    poa_a = create_poa(dec["id"], "Agent A", scope_a)
    activate_poa(poa_a["id"], "2026-01-02T00:00:00Z")
    poa_b = create_poa(dec["id"], "Agent B", scope_b)
    activate_poa(poa_b["id"], "2026-01-02T00:00:00Z")
    finalize_plan(estate["id"])
    return {
        "decedent": dec,
        "estate": estate,
        "poa_a": poa_a,
        "poa_b": poa_b,
        "executor": executor,
    }
