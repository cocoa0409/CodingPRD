"""Composite setup helpers.

The harness restarts the API server with an empty database before every test, so
every precondition has to be built from the endpoints the PRD declares. The helpers
below are layered:

* tier 1 — single-entity registrations that only need a state regulator;
* tier 2 — entity hierarchies (approved depository, funded account);
* tier 3 — lifecycle shortcuts (executed agreement, active allocation);
* tier 4 — accumulation and threshold targeting (deficient run, open margin call);
* tier 5 — terminal-state scenarios (settled substitution, suspended depository).

Every helper threads the entity-backed identities explicitly: a `Custodian` acts as
its own record `id` and a `PublicUnitTreasurer` acts as its `PublicUnit` record `id`,
so ownership-gated calls receive per-instance headers rather than shared constants.
"""

from itertools import count

from prd_bench_local_runner.testing import get_success_data

from .constants import DEFAULT_CLOCK_UTC, TEST_DEFAULTS
from .factories import (
    amount_payload,
    attest_payload,
    create_collateral_asset_payload,
    create_deposit_account_payload,
    create_depository_payload,
    create_custodian_payload,
    create_mtm_run_payload,
    create_pledge_agreement_payload,
    create_pledge_allocation_payload,
    create_pooled_program_payload,
    create_public_unit_payload,
    create_qualification_review_payload,
    create_safekeeping_receipt_payload,
    create_substitution_request_payload,
    cure_payload,
    decide_payload,
    mark_ineligible_payload,
    price_payload,
    projected_window,
    create_runoff_forecast_payload,
    reject_substitution_payload,
    set_clock_payload,
    signature_payload,
)
from .test_users import (
    TEST_USERS,
    make_custodian_headers,
    make_public_unit_treasurer_headers,
)

REGULATOR = TEST_USERS["state_regulator_headers"]
OFFICER = TEST_USERS["bank_collateral_officer_headers"]
COMPLIANCE = TEST_USERS["bank_compliance_officer_headers"]
SECOND_COMPLIANCE = TEST_USERS["second_bank_compliance_officer_headers"]
OPERATOR = TEST_USERS["system_operator_headers"]

_cusip_counter = count(1)
_agreement_counter = count(1)
_receipt_counter = count(1)


def next_cusip() -> str:
    """A fresh security identifier; `cusip` is unique within a depository."""
    return f"91282{next(_cusip_counter):04d}"


def next_agreement_number() -> str:
    """A fresh document number; `agreement_number` is unique within a depository."""
    return f"AG-{next(_agreement_counter):05d}"


def next_receipt_number() -> str:
    """A fresh receipt number; `receipt_number` is unique within an agreement."""
    return f"RCPT-{next(_receipt_counter):05d}"


# ─── Tier 0: the logical clock ────────────────────────


def set_clock(client, to_iso8601: str = DEFAULT_CLOCK_UTC) -> dict:
    """Drive the logical clock to a named instant. Mutates no domain record."""
    response = client.set_clock(set_clock_payload(to_iso8601=to_iso8601), OPERATOR)
    return get_success_data(response, 200)


def run_daily_cycle(client) -> dict:
    """Run the daily escalation and breach sweep at the current logical clock."""
    response = client.run_daily_cycle(OPERATOR)
    return get_success_data(response, 200)


# ─── Tier 1: single registrations ─────────────────────


def create_custodian(client, **overrides) -> dict:
    """Register a custodian; it starts at `PENDING_APPROVAL`."""
    response = client.create_custodian(create_custodian_payload(**overrides), REGULATOR)
    return get_success_data(response, 201)


def create_approved_custodian(client, **overrides) -> dict:
    """Register a custodian and approve it, so it may serve on a tri-party agreement."""
    custodian = create_custodian(client, **overrides)
    response = client.approve_custodian(custodian["id"], REGULATOR)
    return get_success_data(response, 200)


def create_pooled_program(client, **overrides) -> dict:
    """Create a state pooled collateral program."""
    response = client.create_pooled_program(
        create_pooled_program_payload(**overrides), REGULATOR
    )
    return get_success_data(response, 201)


def create_public_unit(client, **overrides) -> dict:
    """Register a public unit depositor."""
    response = client.create_public_unit(create_public_unit_payload(**overrides), REGULATOR)
    return get_success_data(response, 201)


def create_pooled_public_unit(client, **overrides) -> dict:
    """Register a public unit whose declared preference is `POOLED`."""
    overrides.setdefault("collateral_program_preference", "POOLED")
    return create_public_unit(client, **overrides)


def create_draft_depository(client, **overrides) -> dict:
    """Register a candidate depository; it starts at `approval_status` `DRAFT`."""
    response = client.create_depository(create_depository_payload(**overrides), OFFICER)
    return get_success_data(response, 201)


# ─── Tier 2: qualification and approval ───────────────


def file_qualification_review(
    client, depository_id, officer_headers=OFFICER, **overrides
) -> dict:
    """File a qualification package under a depository; the review starts `SUBMITTED`."""
    response = client.create_qualification_review(
        depository_id, create_qualification_review_payload(**overrides), officer_headers
    )
    return get_success_data(response, 201)


def attest_review(client, review_id, compliance_headers=COMPLIANCE, **overrides) -> dict:
    """Record the second line's attestation, driving the review to `ATTESTED`."""
    response = client.attest_qualification_review(
        review_id, attest_payload(**overrides), compliance_headers
    )
    return get_success_data(response, 200)


def begin_review(client, review_id) -> dict:
    """Take an attested package under review, also carrying the depository to
    `UNDER_REVIEW`."""
    response = client.begin_review_qualification_review(review_id, REGULATOR)
    return get_success_data(response, 200)


def decide_review(client, review_id, decision="APPROVE", **overrides) -> dict:
    """Approve or deny the depository."""
    response = client.decide_qualification_review(
        review_id, decide_payload(decision, **overrides), REGULATOR
    )
    return get_success_data(response, 200)


def create_depository_under_review(client, **overrides):
    """Return (depository, review) with the depository carried to `UNDER_REVIEW`."""
    depository = create_draft_depository(client, **overrides)
    review = file_qualification_review(client, depository["id"])
    attest_review(client, review["id"])
    review = begin_review(client, review["id"])
    depository = get_success_data(client.get_depository(depository["id"], OFFICER), 200)
    return depository, review


def create_approved_depository(
    client, requested_pledge_capacity_cents=None, **overrides
) -> dict:
    """Carry a depository all the way to `APPROVED`, granting it a pledge capacity.

    The full chain is file → attest → begin-review → decide, because approval requires
    an `UNDER_REVIEW` review with a non-null `attested_by_user_id`.
    """
    depository = create_draft_depository(client, **overrides)
    capacity = (
        requested_pledge_capacity_cents
        if requested_pledge_capacity_cents is not None
        else TEST_DEFAULTS["REQUESTED_PLEDGE_CAPACITY_CENTS"]
    )
    review = file_qualification_review(
        client, depository["id"], requested_pledge_capacity_cents=capacity
    )
    attest_review(client, review["id"])
    begin_review(client, review["id"])
    decide_review(client, review["id"], "APPROVE")
    return get_success_data(client.get_depository(depository["id"], OFFICER), 200)


def create_denied_depository(client, **overrides) -> dict:
    """Carry a depository to the terminal `DENIED` state."""
    depository = create_draft_depository(client, **overrides)
    review = file_qualification_review(client, depository["id"])
    attest_review(client, review["id"])
    begin_review(client, review["id"])
    decide_review(client, review["id"], "DENY")
    return get_success_data(client.get_depository(depository["id"], OFFICER), 200)


def suspend_depository(client, depository_id) -> dict:
    """Suspend an approved depository, firing the four-hop cascade."""
    response = client.suspend_depository(depository_id, REGULATOR)
    return get_success_data(response, 200)


# ─── Tier 2: deposit accounts ─────────────────────────


def create_deposit_account(client, depository_id, public_unit_id, **overrides) -> dict:
    """Open an account. The treasurer acts as its own `PublicUnit` record id."""
    response = client.create_deposit_account(
        create_deposit_account_payload(depository_id, public_unit_id, **overrides),
        make_public_unit_treasurer_headers(public_unit_id),
    )
    return get_success_data(response, 201)


def deposit(client, account_id, public_unit_id, amount_cents) -> dict:
    """Credit public funds, re-running the insurance and collateral chain."""
    response = client.create_deposit(
        account_id,
        amount_payload(amount_cents),
        make_public_unit_treasurer_headers(public_unit_id),
    )
    return get_success_data(response, 200)


def withdraw(client, account_id, public_unit_id, amount_cents) -> dict:
    """Debit public funds, re-running the same chain."""
    response = client.create_withdrawal(
        account_id,
        amount_payload(amount_cents),
        make_public_unit_treasurer_headers(public_unit_id),
    )
    return get_success_data(response, 200)


def create_funded_account(
    client, depository_id, public_unit_id, amount_cents, **overrides
) -> dict:
    """Open an account and credit it, so it lands at `funding_status` `FUNDED`."""
    account = create_deposit_account(client, depository_id, public_unit_id, **overrides)
    return deposit(client, account["id"], public_unit_id, amount_cents)


# ─── Tier 3: pledge documentation ─────────────────────


def draft_dedicated_agreement(
    client, depository_id, custodian_id, deposit_account_id, **overrides
) -> dict:
    """Draft a `DEPOSIT_ACCOUNT`-beneficiary agreement; it starts at `DRAFT`."""
    overrides.setdefault("agreement_number", next_agreement_number())
    payload = create_pledge_agreement_payload(
        depository_id,
        custodian_id,
        beneficiary_type="DEPOSIT_ACCOUNT",
        deposit_account_id=deposit_account_id,
        **overrides,
    )
    return get_success_data(client.create_pledge_agreement(payload, OFFICER), 201)


def draft_pooled_agreement(
    client, depository_id, custodian_id, pooled_program_id, **overrides
) -> dict:
    """Draft a `POOLED_PROGRAM`-beneficiary agreement; it starts at `DRAFT`."""
    overrides.setdefault("agreement_number", next_agreement_number())
    payload = create_pledge_agreement_payload(
        depository_id,
        custodian_id,
        beneficiary_type="POOLED_PROGRAM",
        pooled_program_id=pooled_program_id,
        **overrides,
    )
    return get_success_data(client.create_pledge_agreement(payload, OFFICER), 201)


def circulate(client, agreement_id) -> dict:
    """Carry a draft to `PENDING_SIGNATURES`."""
    return get_success_data(client.circulate_pledge_agreement(agreement_id, OFFICER), 200)


def sign(client, agreement_id, party, headers) -> dict:
    """Record one party's stamp. Entitlement is checked against the acting role and,
    for the entity-backed roles, against ownership as well."""
    return get_success_data(
        client.create_signature(agreement_id, signature_payload(party), headers), 200
    )


def collect_dedicated_quorum(client, agreement_id, custodian_id, public_unit_id) -> dict:
    """Stamp all three parties on a dedicated agreement, executing it.

    `DEPOSITORY` is stamped by the bank's second line, `PUBLIC_UNIT` by the treasurer of
    the beneficiary account's own unit, and `CUSTODIAN` by the named custodian itself.
    """
    sign(client, agreement_id, "DEPOSITORY", COMPLIANCE)
    sign(
        client,
        agreement_id,
        "PUBLIC_UNIT",
        make_public_unit_treasurer_headers(public_unit_id),
    )
    return sign(
        client, agreement_id, "CUSTODIAN", make_custodian_headers(custodian_id)
    )


def collect_pooled_quorum(client, agreement_id, custodian_id) -> dict:
    """Stamp all three parties on a pooled agreement, executing it.

    On a `POOLED_PROGRAM` agreement there is no single beneficiary unit, so the
    `PUBLIC_UNIT` party is stamped by a state regulator acting for the participants.
    """
    sign(client, agreement_id, "DEPOSITORY", COMPLIANCE)
    sign(client, agreement_id, "PUBLIC_UNIT", REGULATOR)
    return sign(
        client, agreement_id, "CUSTODIAN", make_custodian_headers(custodian_id)
    )


def create_executed_dedicated_agreement(
    client, depository_id, custodian_id, deposit_account_id, public_unit_id, **overrides
) -> dict:
    """Draft, circulate and fully sign a dedicated agreement, landing it at `EXECUTED`."""
    agreement = draft_dedicated_agreement(
        client, depository_id, custodian_id, deposit_account_id, **overrides
    )
    circulate(client, agreement["id"])
    return collect_dedicated_quorum(
        client, agreement["id"], custodian_id, public_unit_id
    )


def create_executed_pooled_agreement(
    client, depository_id, custodian_id, pooled_program_id, **overrides
) -> dict:
    """Draft, circulate and fully sign a pooled agreement, landing it at `EXECUTED`."""
    agreement = draft_pooled_agreement(
        client, depository_id, custodian_id, pooled_program_id, **overrides
    )
    circulate(client, agreement["id"])
    return collect_pooled_quorum(client, agreement["id"], custodian_id)


def terminate_agreement(client, agreement_id) -> dict:
    """Terminate an executed agreement, releasing every active allocation under it."""
    return get_success_data(
        client.terminate_pledge_agreement(agreement_id, REGULATOR), 200
    )


def request_amendment(client, agreement_id, headers) -> dict:
    """Request an amendment, voiding every signature already collected."""
    return get_success_data(client.request_amendment(agreement_id, headers), 200)


# ─── Tier 3: collateral inventory ─────────────────────


def create_collateral_asset(client, depository_id, custodian_id, **overrides) -> dict:
    """Register a security the bank intends to pledge."""
    overrides.setdefault("cusip", next_cusip())
    payload = create_collateral_asset_payload(depository_id, custodian_id, **overrides)
    return get_success_data(client.create_collateral_asset(payload, OFFICER), 201)


def post_price(client, asset_id, market_price_bps, headers=OFFICER) -> dict:
    """Post a new market price, revaluing the asset and every active allocation on it."""
    return get_success_data(
        client.post_price(asset_id, price_payload(market_price_bps), headers), 200
    )


def mark_ineligible(client, asset_id, **overrides) -> dict:
    """Declare an asset ineligible, releasing every active allocation on it."""
    return get_success_data(
        client.mark_asset_ineligible(asset_id, mark_ineligible_payload(**overrides), REGULATOR),
        200,
    )


def agreement_version(client, agreement_id, headers=OFFICER) -> int:
    """Read the agreement's current `version`.

    Every allocation increments it, which is why a client that has just created one
    allocation must re-read the agreement before creating a second.
    """
    agreement = get_success_data(client.get_pledge_agreement(agreement_id, headers), 200)
    return agreement["version"]


def depository_version(client, depository_id, headers=OFFICER) -> int:
    """Read the depository's current `version`; every run increments it."""
    depository = get_success_data(client.get_depository(depository_id, headers), 200)
    return depository["version"]


def account_version(client, account_id, headers) -> int:
    """Read the deposit account's current `version`; filing a forecast increments it."""
    account = get_success_data(client.get_deposit_account(account_id, headers), 200)
    return account["version"]


def create_allocation(
    client,
    agreement_id,
    asset_id,
    allocated_par_cents,
    effective_from=DEFAULT_CLOCK_UTC,
    effective_to=None,
    **overrides,
) -> dict:
    """Pledge par to an executed agreement, pinning the agreement version freshly read."""
    payload = create_pledge_allocation_payload(
        agreement_id,
        asset_id,
        allocated_par_cents,
        agreement_version(client, agreement_id),
        effective_from=effective_from,
        **overrides,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return get_success_data(client.create_pledge_allocation(payload, OFFICER), 201)


def release_allocation(client, allocation_id) -> dict:
    """Release an active allocation back into the bank's unpledged inventory."""
    return get_success_data(
        client.release_pledge_allocation(allocation_id, OFFICER), 200
    )


# ─── Tier 4: substitution, valuation and cure ─────────


def create_substitution_request(
    client, agreement_id, outgoing_allocation_id, incoming_asset_id, incoming_par_cents
) -> dict:
    """Open a substitution request; it starts at `SUBMITTED`."""
    payload = create_substitution_request_payload(
        agreement_id, outgoing_allocation_id, incoming_asset_id, incoming_par_cents
    )
    return get_success_data(client.create_substitution_request(payload, OFFICER), 201)


def compliance_approve(client, request_id, headers=COMPLIANCE) -> dict:
    """Run the compliance branch, which computes `value_adequacy_delta_cents`."""
    return get_success_data(
        client.compliance_approve_substitution(request_id, headers), 200
    )


def custodian_ack(client, request_id, custodian_id) -> dict:
    """Run the custodian branch; only the agreement's own custodian may acknowledge."""
    return get_success_data(
        client.custodian_ack_substitution(
            request_id, make_custodian_headers(custodian_id)
        ),
        200,
    )


def settle_substitution(client, request_id, custodian_id) -> dict:
    """Settle the join, swapping the allocations."""
    return get_success_data(
        client.settle_substitution(request_id, make_custodian_headers(custodian_id)), 200
    )


def reject_substitution(client, request_id, headers=COMPLIANCE, **overrides) -> dict:
    """Close a request without moving par, from `SUBMITTED` or `CUSTODIAN_ACKED`."""
    return get_success_data(
        client.reject_substitution(
            request_id, reject_substitution_payload(**overrides), headers
        ),
        200,
    )


def withdraw_substitution(client, request_id, headers=OFFICER) -> dict:
    """Withdraw a request that has not settled."""
    return get_success_data(client.withdraw_substitution(request_id, headers), 200)


def create_mtm_run(
    client,
    depository_id,
    window_start,
    window_end,
    basis="SUPERVISORY",
    headers=OFFICER,
    **overrides,
) -> dict:
    """Execute a run over a closed window, pinning the freshly read depository version."""
    payload = create_mtm_run_payload(
        window_start,
        window_end,
        depository_version(client, depository_id, headers),
        basis=basis,
        **overrides,
    )
    return get_success_data(client.create_mtm_run(depository_id, payload, headers), 201)


def latest_margin_call(client, depository_id, headers=OFFICER) -> dict:
    """The most recently issued margin call of a depository.

    Collections sort by `created_at` ascending, so the newest call is the last record.
    """
    response = client.list_margin_calls(headers, params={"depository_id": depository_id})
    calls = get_success_data(response, 200)
    assert calls, "expected at least one margin call for the depository"
    return calls[-1]


def cure_margin_call(client, margin_call_id, allocation_ids, headers=OFFICER) -> dict:
    """Credit newly pledged allocations against an open call."""
    return get_success_data(
        client.cure_margin_call(margin_call_id, cure_payload(allocation_ids), headers), 200
    )


# ─── Tier 4: custody confirmation and forecasting ─────


def issue_receipt(
    client, agreement_id, custodian_id, reported_par_cents, reported_asset_count, **overrides
) -> dict:
    """Issue a safekeeping receipt against an agreement naming the acting custodian."""
    overrides.setdefault("receipt_number", next_receipt_number())
    payload = create_safekeeping_receipt_payload(
        agreement_id, reported_par_cents, reported_asset_count, **overrides
    )
    return get_success_data(
        client.create_safekeeping_receipt(payload, make_custodian_headers(custodian_id)),
        201,
    )


def confirm_receipt(client, receipt_id) -> dict:
    """Audit-confirm a receipt, or record a reconciliation exception."""
    return get_success_data(client.confirm_safekeeping_receipt(receipt_id, REGULATOR), 200)


def file_forecast(
    client,
    account_id,
    public_unit_id,
    horizon_start,
    horizon_end,
    windows,
    cycle_label="TAX_COLLECTION",
    basis="PEAK_WINDOW",
    **overrides,
) -> dict:
    """File a runoff forecast on one of the treasurer's own accounts."""
    headers = make_public_unit_treasurer_headers(public_unit_id)
    payload = create_runoff_forecast_payload(
        account_id,
        horizon_start,
        horizon_end,
        windows,
        account_version(client, account_id, headers),
        cycle_label=cycle_label,
        basis=basis,
        **overrides,
    )
    return get_success_data(client.create_runoff_forecast(payload, headers), 201)


# ─── Tier 5: composite scenarios ──────────────────────


def build_dedicated_perimeter(
    client,
    deposit_cents=TEST_DEFAULTS["DEPOSIT_CENTS"],
    capital_ratio_bps=1200,
    insurance_determination_basis="AGGREGATED_BY_UNIT",
    deposit_class="DEMAND",
    unit_type="COUNTY",
    concentration_limit_bps=10000,
    requested_pledge_capacity_cents=None,
    clock=DEFAULT_CLOCK_UTC,
) -> dict:
    """The standard dedicated arrangement: approved custodian, registered public unit,
    approved depository, funded account and an executed dedicated agreement.

    Returns a dict keyed `custodian`, `public_unit`, `depository`, `account`,
    `agreement`, plus the shorthand id keys used by the callers.
    """
    set_clock(client, clock)
    custodian = create_approved_custodian(
        client, tri_party_capable=True, concentration_limit_bps=concentration_limit_bps
    )
    public_unit = create_public_unit(
        client, unit_type=unit_type, collateral_program_preference="DEDICATED"
    )
    depository = create_approved_depository(
        client,
        requested_pledge_capacity_cents=requested_pledge_capacity_cents,
        capital_ratio_bps=capital_ratio_bps,
        insurance_determination_basis=insurance_determination_basis,
    )
    account = create_funded_account(
        client,
        depository["id"],
        public_unit["id"],
        deposit_cents,
        deposit_class=deposit_class,
        pledging_mode="DEDICATED",
    )
    agreement = create_executed_dedicated_agreement(
        client,
        depository["id"],
        custodian["id"],
        account["id"],
        public_unit["id"],
    )
    return {
        "custodian": custodian,
        "custodian_id": custodian["id"],
        "public_unit": public_unit,
        "public_unit_id": public_unit["id"],
        "depository": depository,
        "depository_id": depository["id"],
        "account": account,
        "account_id": account["id"],
        "agreement": agreement,
        "agreement_id": agreement["id"],
    }


def build_pooled_perimeter(
    client,
    participants,
    minimum_pool_pct_bps=11000,
    capital_ratio_bps=1200,
    clock=DEFAULT_CLOCK_UTC,
) -> dict:
    """A pooled program with one member depository and one funded account per entry of
    `participants`, each entry being a `(unit_type, deposit_cents)` pair.

    Returns a dict keyed `pool`, `custodian`, `depository`, `agreement`, and `accounts`
    — a list of `(public_unit, account)` pairs in creation order.
    """
    set_clock(client, clock)
    custodian = create_approved_custodian(
        client, tri_party_capable=True, concentration_limit_bps=10000
    )
    pool = create_pooled_program(client, minimum_pool_pct_bps=minimum_pool_pct_bps)
    depository = create_approved_depository(
        client, capital_ratio_bps=capital_ratio_bps, pooled_program_id=pool["id"]
    )
    accounts = []
    for unit_type, deposit_cents in participants:
        public_unit = create_pooled_public_unit(client, unit_type=unit_type)
        account = create_funded_account(
            client,
            depository["id"],
            public_unit["id"],
            deposit_cents,
            pledging_mode="POOLED",
        )
        accounts.append((public_unit, account))
    agreement = create_executed_pooled_agreement(
        client, depository["id"], custodian["id"], pool["id"]
    )
    return {
        "custodian": custodian,
        "custodian_id": custodian["id"],
        "pool": pool,
        "pool_id": pool["id"],
        "depository": depository,
        "depository_id": depository["id"],
        "agreement": agreement,
        "agreement_id": agreement["id"],
        "accounts": accounts,
    }


def build_substitution_ready(
    client,
    outgoing_par_cents,
    incoming_par_cents,
    incoming_asset_type="US_TREASURY",
    incoming_market_price_bps=10000,
    deposit_cents=TEST_DEFAULTS["DEPOSIT_CENTS"],
) -> dict:
    """A dedicated arrangement with one active allocation and a second asset standing by,
    ready for a substitution request to be opened against it."""
    perimeter = build_dedicated_perimeter(client, deposit_cents=deposit_cents)
    outgoing_asset = create_collateral_asset(
        client, perimeter["depository_id"], perimeter["custodian_id"]
    )
    incoming_asset = create_collateral_asset(
        client,
        perimeter["depository_id"],
        perimeter["custodian_id"],
        asset_type=incoming_asset_type,
        par_value_cents=max(incoming_par_cents, 10_000_000),
        market_price_bps=incoming_market_price_bps,
    )
    allocation = create_allocation(
        client, perimeter["agreement_id"], outgoing_asset["id"], outgoing_par_cents
    )
    perimeter.update(
        {
            "outgoing_asset": outgoing_asset,
            "outgoing_asset_id": outgoing_asset["id"],
            "incoming_asset": incoming_asset,
            "incoming_asset_id": incoming_asset["id"],
            "allocation": allocation,
            "allocation_id": allocation["id"],
            "incoming_par_cents": incoming_par_cents,
        }
    )
    return perimeter


def contiguous_windows(boundaries, balances) -> list:
    """Build a contiguous, non-overlapping projected-window chain.

    `boundaries` holds n+1 instants and `balances` the n projected balances, so the
    windows form exactly one chain from the first boundary to the last.
    """
    assert len(boundaries) == len(balances) + 1, "n+1 boundaries for n windows"
    return [
        projected_window(boundaries[index], boundaries[index + 1], balances[index])
        for index in range(len(balances))
    ]
