"""Composite setup helpers for the real-estate-closing-escrow benchmark.

Each fixture builds its preconditions from scratch through PRD-declared
endpoints (PRD §3.x, §4). The runner restarts the API server before every
individual pytest test, so every fixture starts from an empty database — no
entities, no clock state, no users.

Fixtures use `get_success_data()` (lenient validator) so setup failures
surface as clear "Setup failed" traces rather than cryptic assertion noise.

Identity threading: all three roles are entity-backed (PRD §2.1). Each
fixture below first registers the required `User` rows (the bootstrap-CO
trick allows the very first `POST /users` because the server cannot have
a registered ComplianceOfficer yet), captures their `id` values, and then
threads those ids into the per-instance header builders so that the
escrow ownership and segregation-of-duties checks see real `User.id`s.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_user_payload,
    create_purchase_agreement_payload,
    create_earnest_money_deposit_payload,
    confirm_deposit_payload,
    create_title_search_payload,
    complete_title_search_payload,
    resolve_title_search_payload,
    create_title_insurance_policy_payload,
    create_ccr_review_payload,
    create_closing_disclosure_payload,
    reissue_closing_disclosure_payload,
    create_wire_instruction_payload,
    callback_verify_wire_payload,
    create_disbursement_payload,
    create_exchange_account_payload,
    identify_exchange_account_payload,
    terminate_purchase_agreement_payload,
    set_clock_payload,
    advance_clock_payload,
)
from .test_users import (
    make_escrow_officer_headers,
    make_title_agent_headers,
    make_compliance_officer_headers,
)


# ─── Tier 0: clock + user bootstrap ──────────────────────────────


def bootstrap_compliance_officer(full_name: str = "Compliance Root") -> tuple[str, dict]:
    """Register the very first ComplianceOfficer (PRD §2.1).

    The server's user table is empty at test start; the first `POST /users`
    must be allowed to bootstrap a compliance officer (any later user
    registration is performed *by* a ComplianceOfficer per PRD §4). We pass
    a placeholder X-User-ID with X-User-Role=ComplianceOfficer for this
    very first call, then return the real id + headers bound to it.
    """
    bootstrap_headers = make_compliance_officer_headers("bootstrap")
    res = api_client.create_user(
        create_user_payload(full_name=full_name, role="ComplianceOfficer"),
        bootstrap_headers,
    )
    co = get_success_data(res)
    return co["id"], make_compliance_officer_headers(co["id"])


def register_user(role: str, full_name: str, co_headers: dict) -> str:
    """Register an additional User of `role`; returns the new User.id (PRD §2.1)."""
    res = api_client.create_user(
        create_user_payload(full_name=full_name, role=role), co_headers
    )
    return get_success_data(res)["id"]


def set_clock(iso8601: str, co_headers: dict) -> None:
    """Pin the server's logical UTC clock (PRD §3.8)."""
    api_client.set_clock(set_clock_payload(iso8601), co_headers)


def advance_clock(seconds: int, co_headers: dict) -> None:
    """Advance the server's logical UTC clock (PRD §3.8)."""
    api_client.advance_clock(advance_clock_payload(seconds), co_headers)


# ─── Tier 1: actors bundle ──────────────────────────────────────


def setup_actors(
    initial_iso8601: str = "2026-06-01T00:00:00Z",
    extra_escrow_officers: int = 1,
    title_agents: int = 1,
) -> dict:
    """Bootstrap the standard cast: 1 CO, 1 EO, optionally a second EO (for SoD),
    optionally a TA. Sets the clock to `initial_iso8601` (PRD §3.8).

    Returns a dict with keys: co_id, co, eo_id, eo, eo2_id?, eo2?,
    ta_id?, ta?.  *_id keys carry the User.id; bare-name keys carry the
    request headers bound to that id (PRD §2.1).
    """
    co_id, co_headers = bootstrap_compliance_officer()
    out = {"co_id": co_id, "co": co_headers}

    eo_id = register_user("EscrowOfficer", "Escrow Officer 1", co_headers)
    out["eo_id"] = eo_id
    out["eo"] = make_escrow_officer_headers(eo_id)

    if extra_escrow_officers >= 1:
        eo2_id = register_user("EscrowOfficer", "Escrow Officer 2", co_headers)
        out["eo2_id"] = eo2_id
        out["eo2"] = make_escrow_officer_headers(eo2_id)

    if title_agents >= 1:
        ta_id = register_user("TitleAgent", "Title Agent 1", co_headers)
        out["ta_id"] = ta_id
        out["ta"] = make_title_agent_headers(ta_id)

    set_clock(initial_iso8601, co_headers)
    return out


# ─── Tier 2: leaf creators ──────────────────────────────────────


def create_agreement(
    actors: dict,
    *,
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    scheduled_closing_date: str = "2026-08-01T00:00:00Z",
    exchange_account_id: str = None,
    buyer_name: str = "Test Buyer",
    seller_name: str = "Test Seller",
    property_address: str = "1 Test Lane",
) -> dict:
    """Create a PurchaseAgreement in DRAFT (PRD §3.1)."""
    payload = create_purchase_agreement_payload(
        buyer_name=buyer_name,
        seller_name=seller_name,
        property_address=property_address,
        purchase_price_cents=purchase_price_cents,
        earnest_money_required_cents=earnest_money_required_cents,
        scheduled_closing_date=scheduled_closing_date,
    )
    if exchange_account_id is not None:
        payload["exchange_account_id"] = exchange_account_id
    res = api_client.create_purchase_agreement(payload, actors["eo"])
    return get_success_data(res)


def activate_agreement(actors: dict, agreement_id: str) -> dict:
    """DRAFT -> ACTIVE; auto-creates escrow account (PRD §3.1)."""
    res = api_client.activate_purchase_agreement(agreement_id, actors["eo"])
    return get_success_data(res)


def fetch_escrow_for_agreement(actors: dict, agreement_id: str) -> dict:
    """Look up the auto-created EscrowAccount for an agreement (PRD §3.1)."""
    res = api_client.list_escrow_accounts(
        actors["eo"], params={"agreement_id": agreement_id}
    )
    data = get_success_data(res)
    # `data` may be the list directly or live inside the envelope's data field;
    # validate_paginated would expose meta separately. The lenient
    # get_success_data returns whatever's in `data`. List endpoint convention:
    # `data` is the array.
    assert isinstance(data, list) and len(data) >= 1, \
        f"Setup failed: no EscrowAccount auto-created for agreement {agreement_id}"
    return data[0]


def create_deposit(
    actors: dict,
    escrow_id: str,
    *,
    amount_cents: int = 1_000_000,
    depositor_role: str = "BUYER",
) -> dict:
    """Create a PENDING EarnestMoneyDeposit (PRD §3.1)."""
    res = api_client.create_earnest_money_deposit(
        create_earnest_money_deposit_payload(
            escrow_account_id=escrow_id,
            amount_cents=amount_cents,
            depositor_role=depositor_role,
        ),
        actors["eo"],
    )
    return get_success_data(res)


def confirm_deposit(
    actors: dict, deposit_id: str, *, confirmation_reference: str = "BANK-001"
) -> dict:
    """PENDING -> CONFIRMED; may bubble agreement to UNDER_CONTRACT (PRD §3.1, §2.9)."""
    res = api_client.confirm_earnest_money_deposit(
        deposit_id, confirm_deposit_payload(confirmation_reference), actors["eo"]
    )
    return get_success_data(res)


def create_title_search(actors: dict, agreement_id: str) -> dict:
    """Order a TitleSearch (PRD §3.2)."""
    res = api_client.create_title_search(
        create_title_search_payload(agreement_id), actors["ta"]
    )
    return get_success_data(res)


def complete_title_search(actors: dict, search_id: str, defects: list = None) -> dict:
    """ORDERED -> COMPLETED with defects (PRD §3.2)."""
    res = api_client.complete_title_search(
        search_id,
        complete_title_search_payload(defects=defects or []),
        actors["ta"],
    )
    return get_success_data(res)


def resolve_title_search(actors: dict, search_id: str, resolution_notes: str = None) -> dict:
    """COMPLETED -> RESOLVED (PRD §3.2)."""
    payload = {}
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    res = api_client.resolve_title_search(search_id, payload, actors["ta"])
    return get_success_data(res)


def issue_title_policy(
    actors: dict, title_search_id: str, expected_title_search_version: int
) -> dict:
    """Issue a TitleInsurancePolicy (OCC-gated on TitleSearch.version, PRD §2.7, §3.2)."""
    res = api_client.create_title_insurance_policy(
        create_title_insurance_policy_payload(
            title_search_id=title_search_id,
            expected_title_search_version=expected_title_search_version,
        ),
        actors["ta"],
    )
    return get_success_data(res)


def create_ccr_review(
    actors: dict,
    agreement_id: str,
    *,
    hoa_name: str = "Test HOA",
    restrictions_summary: str = "Standard CC&Rs reviewed.",
    buyer_acknowledged: bool = True,
) -> dict:
    """Append a CCRReview (PRD §3.3)."""
    res = api_client.create_ccr_review(
        create_ccr_review_payload(
            agreement_id=agreement_id,
            hoa_name=hoa_name,
            restrictions_summary=restrictions_summary,
            buyer_acknowledged=buyer_acknowledged,
        ),
        actors["co"],
    )
    return get_success_data(res)


def create_closing_disclosure(
    actors: dict,
    agreement_id: str,
    expected_agreement_version: int,
    *,
    cd_apr_bps: int = 600,
    cd_product_type: str = "FIXED",
    cd_prepayment_penalty: bool = False,
    cd_total_loan_amount_cents: int = 40_000_000,
    cd_monthly_payment_cents: int = 250_000,
) -> dict:
    """Create a CD in DRAFT (OCC-gated on PurchaseAgreement.version, PRD §2.7, §3.4)."""
    res = api_client.create_closing_disclosure(
        create_closing_disclosure_payload(
            agreement_id=agreement_id,
            expected_agreement_version=expected_agreement_version,
            cd_apr_bps=cd_apr_bps,
            cd_total_loan_amount_cents=cd_total_loan_amount_cents,
            cd_monthly_payment_cents=cd_monthly_payment_cents,
            cd_product_type=cd_product_type,
            cd_prepayment_penalty=cd_prepayment_penalty,
        ),
        actors["eo"],
    )
    return get_success_data(res)


def deliver_closing_disclosure(actors: dict, cd_id: str) -> dict:
    """DRAFT -> DELIVERED; stamps issued_at & earliest_consummation_at (PRD §3.4)."""
    res = api_client.deliver_closing_disclosure(cd_id, actors["eo"])
    return get_success_data(res)


def acknowledge_closing_disclosure(actors: dict, cd_id: str) -> dict:
    """DELIVERED/REISSUED -> ACKNOWLEDGED; clock must be >= earliest_consummation_at (PRD §3.4)."""
    res = api_client.acknowledge_closing_disclosure(cd_id, actors["eo"])
    return get_success_data(res)


def create_wire(
    actors: dict,
    agreement_id: str,
    *,
    party: str = "BUYER",
    beneficiary_bank_name: str = "Acme Bank",
    beneficiary_account_last4: str = "1234",
    routing_number: str = "021000021",
) -> dict:
    """Submit a WireInstruction (PRD §3.5, §2.6)."""
    res = api_client.create_wire_instruction(
        create_wire_instruction_payload(
            agreement_id=agreement_id,
            party=party,
            beneficiary_bank_name=beneficiary_bank_name,
            beneficiary_account_last4=beneficiary_account_last4,
            routing_number=routing_number,
        ),
        actors["eo"],
    )
    return get_success_data(res)


def callback_verify_wire(
    actors: dict, wire_id: str, *, verifier_id: str, voice_callback_reference: str = "VC-001",
    as_user: str = "eo",
) -> dict:
    """PROVIDED -> VERIFIED via voice callback (PRD §2.6).

    `as_user` selects which actor performs the call ("eo" or "eo2"). The
    verifier_id in the body must equal the acting X-User-ID per PRD §2.6.
    """
    headers = actors[as_user]
    res = api_client.callback_verify_wire_instruction(
        wire_id,
        callback_verify_wire_payload(
            verifier_id=verifier_id, voice_callback_reference=voice_callback_reference
        ),
        headers,
    )
    return get_success_data(res)


def lock_wire(actors: dict, wire_id: str) -> dict:
    """VERIFIED -> LOCKED by a different officer than the callback verifier (PRD §2.6).

    Locking is performed by the ComplianceOfficer.
    """
    res = api_client.lock_wire_instruction(wire_id, actors["co"])
    return get_success_data(res)


def reject_wire(actors: dict, wire_id: str) -> dict:
    """PROVIDED/VERIFIED -> REJECTED (PRD §2.6)."""
    res = api_client.reject_wire_instruction(wire_id, actors["co"])
    return get_success_data(res)


def verify_and_lock_wire(actors: dict, wire_id: str, *, verifier_user_id: str,
                          voice_callback_reference: str = "VC-001",
                          verify_as: str = "eo") -> dict:
    """Walk a wire from PROVIDED -> VERIFIED -> LOCKED.

    `verifier_user_id` should equal the X-User-ID of `verify_as`. The CO
    performs the lock (a different officer than the verifier — PRD §2.6).
    """
    callback_verify_wire(
        actors, wire_id,
        verifier_id=verifier_user_id,
        voice_callback_reference=voice_callback_reference,
        as_user=verify_as,
    )
    return lock_wire(actors, wire_id)


def queue_disbursement(
    actors: dict,
    escrow_id: str,
    wire_id: str,
    *,
    purpose: str = "SELLER_PROCEEDS",
    amount_cents: int = 10_000_000,
) -> dict:
    """Queue a Disbursement (PRD §3.5)."""
    res = api_client.create_disbursement(
        create_disbursement_payload(
            escrow_account_id=escrow_id,
            wire_instruction_id=wire_id,
            purpose=purpose,
            amount_cents=amount_cents,
        ),
        actors["eo"],
    )
    return get_success_data(res)


def create_exchange_account(
    actors: dict,
    *,
    taxpayer_name: str = "Test Taxpayer",
    qualified_intermediary_name: str = "Acme QI",
    relinquished_closing_date: str = "2026-06-01T00:00:00Z",
) -> dict:
    """Open an ExchangeAccount in OPEN (PRD §3.7)."""
    res = api_client.create_exchange_account(
        create_exchange_account_payload(
            taxpayer_name=taxpayer_name,
            qualified_intermediary_name=qualified_intermediary_name,
            relinquished_closing_date=relinquished_closing_date,
        ),
        actors["eo"],
    )
    return get_success_data(res)


def identify_exchange_account(
    actors: dict, exchange_id: str, *, replacement_property_address: str = "999 Replacement Ave"
) -> dict:
    """OPEN -> IDENTIFIED (PRD §3.7)."""
    res = api_client.identify_exchange_account(
        exchange_id,
        identify_exchange_account_payload(replacement_property_address),
        actors["eo"],
    )
    return get_success_data(res)


# ─── Tier 3: composite helpers used by the difficulty / corner indices ─────


def setup_active_agreement(
    actors: dict = None,
    *,
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    exchange_account_id: str = None,
    scheduled_closing_date: str = "2026-08-01T00:00:00Z",
    initial_iso8601: str = "2026-06-01T00:00:00Z",
) -> dict:
    """Bootstrap actors + a PurchaseAgreement activated to ACTIVE with an auto-created EscrowAccount.

    Returns {"actors", "agreement", "escrow"} (PRD §3.1).
    """
    if actors is None:
        actors = setup_actors(initial_iso8601=initial_iso8601)
    agreement = create_agreement(
        actors,
        purchase_price_cents=purchase_price_cents,
        earnest_money_required_cents=earnest_money_required_cents,
        exchange_account_id=exchange_account_id,
        scheduled_closing_date=scheduled_closing_date,
    )
    activate_agreement(actors, agreement["id"])
    escrow = fetch_escrow_for_agreement(actors, agreement["id"])
    return {"actors": actors, "agreement": agreement, "escrow": escrow}


def setup_under_contract_agreement(
    *,
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    exchange_account_id: str = None,
    scheduled_closing_date: str = "2026-08-01T00:00:00Z",
    initial_iso8601: str = "2026-06-01T00:00:00Z",
    actors: dict = None,
) -> dict:
    """Active agreement + one CONFIRMED EMD that meets earnest_money_required_cents.

    The confirm triggers the ACTIVE->UNDER_CONTRACT cascade (PRD §2.9). Returns
    {"actors", "agreement_id", "escrow_id", "deposit_id", "agreement_version"}.
    `agreement_version` is the version observed *after* the cascade — usable
    as `expected_agreement_version` for the CD-create OCC check (PRD §2.7).
    """
    base = setup_active_agreement(
        actors=actors,
        purchase_price_cents=purchase_price_cents,
        earnest_money_required_cents=earnest_money_required_cents,
        exchange_account_id=exchange_account_id,
        scheduled_closing_date=scheduled_closing_date,
        initial_iso8601=initial_iso8601,
    )
    actors = base["actors"]
    agreement = base["agreement"]
    escrow = base["escrow"]
    deposit = create_deposit(
        actors, escrow["id"], amount_cents=earnest_money_required_cents
    )
    confirm_deposit(actors, deposit["id"])
    agr_fresh = get_success_data(
        api_client.get_purchase_agreement(agreement["id"], actors["eo"])
    )
    return {
        "actors": actors,
        "agreement_id": agreement["id"],
        "escrow_id": escrow["id"],
        "deposit_id": deposit["id"],
        "agreement_version": agr_fresh["version"],
        "agreement_status": agr_fresh["status"],
    }


def setup_resolved_clean_title(
    actors: dict, agreement_id: str
) -> dict:
    """Order, complete-with-clean-defects, and resolve a TitleSearch (PRD §3.2).

    Returns {"search_id", "version"} where `version` is the post-resolve version
    — usable as `expected_title_search_version` for policy issuance (PRD §2.7).
    """
    search = create_title_search(actors, agreement_id)
    complete_title_search(actors, search["id"], defects=[])
    resolved = resolve_title_search(actors, search["id"])
    return {"search_id": resolved["id"], "version": resolved["version"]}


def setup_locked_wire(
    actors: dict,
    agreement_id: str,
    *,
    party: str = "BUYER",
    voice_callback_reference: str = "VC-LOCK",
    verify_as: str = "eo",
    beneficiary_account_last4: str = "1111",
) -> dict:
    """Submit + verify + lock a WireInstruction (PRD §2.6).

    `verify_as` chooses which escrow officer records the callback. The CO
    then locks (different person — PRD §2.6 segregation of duties).
    """
    wire = create_wire(
        actors, agreement_id,
        party=party,
        beneficiary_account_last4=beneficiary_account_last4,
    )
    verifier_user_id = actors[f"{verify_as}_id"]
    verify_and_lock_wire(
        actors, wire["id"],
        verifier_user_id=verifier_user_id,
        voice_callback_reference=voice_callback_reference,
        verify_as=verify_as,
    )
    return get_success_data(api_client.get_wire_instruction(wire["id"], actors["eo"]))


def setup_delivered_cd(
    *,
    actors: dict = None,
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    initial_iso8601: str = "2026-06-01T00:00:00Z",
    cd_apr_bps: int = 600,
    cd_product_type: str = "FIXED",
    cd_prepayment_penalty: bool = False,
) -> dict:
    """UNDER_CONTRACT agreement + a DELIVERED ClosingDisclosure (PRD §3.4).

    The clock is left at `initial_iso8601` (no advance), so the CD's
    `earliest_consummation_at` equals `initial_iso8601` + 72h. Returns
    {"actors", "agreement_id", "escrow_id", "cd_id", "cd"}.
    """
    base = setup_under_contract_agreement(
        actors=actors,
        purchase_price_cents=purchase_price_cents,
        earnest_money_required_cents=earnest_money_required_cents,
        initial_iso8601=initial_iso8601,
    )
    cd = create_closing_disclosure(
        base["actors"], base["agreement_id"], base["agreement_version"],
        cd_apr_bps=cd_apr_bps,
        cd_product_type=cd_product_type,
        cd_prepayment_penalty=cd_prepayment_penalty,
    )
    delivered = deliver_closing_disclosure(base["actors"], cd["id"])
    return {
        "actors": base["actors"],
        "agreement_id": base["agreement_id"],
        "escrow_id": base["escrow_id"],
        "cd_id": cd["id"],
        "cd": delivered,
    }


def setup_ready_for_clear_to_close(
    *,
    actors: dict = None,
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    initial_iso8601: str = "2026-06-01T00:00:00Z",
    skip_seller_wire: bool = False,
    skip_buyer_wire: bool = False,
    skip_ccr: bool = False,
    skip_ack_cd: bool = False,
    ccr_buyer_acknowledged: bool = True,
    skip_clock_advance: bool = False,
    extra_wire_party: str = None,
    extra_wire_verify_as: str = "eo2",
    extra_wire_callback_reference: str = "VC-EXTRA",
    exchange_account_id: str = None,
    scheduled_closing_date: str = "2026-08-01T00:00:00Z",
    title_defects: list = None,
    resolve_title: bool = True,
) -> dict:
    """Build the full prerequisite stack for clear-to-close (PRD §3.5):

      * agreement in UNDER_CONTRACT
      * RESOLVED clean TitleSearch + ISSUED TitleInsurancePolicy
      * one CCRReview with buyer_acknowledged=true (toggleable)
      * one ClosingDisclosure DELIVERED (and ACKNOWLEDGED once clock advances)
      * one BUYER + one SELLER (and optional EXCHANGE_ACCOMMODATOR) WireInstruction LOCKED
      * clock advanced 72h past CD delivery (toggleable)

    Use the `skip_*` flags to drop a single precondition for negative tests.
    Returns a rich dict of all created ids/headers so the trigger call has
    everything it needs.
    """
    base = setup_under_contract_agreement(
        actors=actors,
        purchase_price_cents=purchase_price_cents,
        earnest_money_required_cents=earnest_money_required_cents,
        exchange_account_id=exchange_account_id,
        scheduled_closing_date=scheduled_closing_date,
        initial_iso8601=initial_iso8601,
    )
    actors = base["actors"]
    out = {
        "actors": actors,
        "agreement_id": base["agreement_id"],
        "escrow_id": base["escrow_id"],
        "deposit_id": base["deposit_id"],
        "agreement_version": base["agreement_version"],
    }

    # Title work
    search = create_title_search(actors, base["agreement_id"])
    complete_title_search(actors, search["id"], defects=title_defects or [])
    out["title_search_id"] = search["id"]
    if resolve_title:
        resolved = resolve_title_search(actors, search["id"])
        out["title_search_version"] = resolved["version"]
        policy = issue_title_policy(actors, search["id"], resolved["version"])
        out["title_policy_id"] = policy["id"]

    # CC&R
    if not skip_ccr:
        ccr = create_ccr_review(
            actors, base["agreement_id"], buyer_acknowledged=ccr_buyer_acknowledged
        )
        out["ccr_id"] = ccr["id"]

    # Closing Disclosure
    cd = create_closing_disclosure(
        actors, base["agreement_id"], base["agreement_version"]
    )
    delivered = deliver_closing_disclosure(actors, cd["id"])
    out["cd_id"] = cd["id"]
    out["cd_issued_at"] = delivered["issued_at"]

    # Wires (BUYER + SELLER required; the CO performs the lock, so verify
    # must be performed by EO and EO2 across the two wires so they aren't
    # the same user as the locker).
    if not skip_buyer_wire:
        buyer_wire = create_wire(
            actors, base["agreement_id"], party="BUYER",
            beneficiary_account_last4="1111",
        )
        verify_and_lock_wire(
            actors, buyer_wire["id"],
            verifier_user_id=actors["eo_id"],
            voice_callback_reference="VC-BUYER",
            verify_as="eo",
        )
        out["buyer_wire_id"] = buyer_wire["id"]
    if not skip_seller_wire:
        seller_wire = create_wire(
            actors, base["agreement_id"], party="SELLER",
            beneficiary_account_last4="2222",
        )
        verify_and_lock_wire(
            actors, seller_wire["id"],
            verifier_user_id=actors["eo2_id"],
            voice_callback_reference="VC-SELLER",
            verify_as="eo2",
        )
        out["seller_wire_id"] = seller_wire["id"]
    if extra_wire_party is not None:
        extra_wire = create_wire(
            actors, base["agreement_id"], party=extra_wire_party,
            beneficiary_account_last4="9999",
        )
        verify_user_id = actors[f"{extra_wire_verify_as}_id"]
        verify_and_lock_wire(
            actors, extra_wire["id"],
            verifier_user_id=verify_user_id,
            voice_callback_reference=extra_wire_callback_reference,
            verify_as=extra_wire_verify_as,
        )
        out["extra_wire_id"] = extra_wire["id"]

    # Advance clock past 72h and acknowledge the CD (unless caller wants to skip)
    if not skip_clock_advance:
        advance_clock(72 * 3600, actors["co"])
    if not skip_ack_cd and not skip_clock_advance:
        acknowledge_closing_disclosure(actors, cd["id"])

    return out


def setup_cleared_to_close(
    *, exchange_account_id: str = None,
    purchase_price_cents: int = 50_000_000,
    earnest_money_required_cents: int = 1_000_000,
    initial_iso8601: str = "2026-06-01T00:00:00Z",
    scheduled_closing_date: str = "2026-09-15T00:00:00Z",
    extra_wire_party: str = None,
    extra_wire_callback_reference: str = "VC-EXTRA",
    actors: dict = None,
) -> dict:
    """Same as `setup_ready_for_clear_to_close` but additionally performs the
    UNDER_CONTRACT -> CLEARED_TO_CLOSE transition.

    Returns the same dict plus `agreement_status=CLEARED_TO_CLOSE`.
    """
    ready = setup_ready_for_clear_to_close(
        actors=actors,
        purchase_price_cents=purchase_price_cents,
        earnest_money_required_cents=earnest_money_required_cents,
        initial_iso8601=initial_iso8601,
        exchange_account_id=exchange_account_id,
        scheduled_closing_date=scheduled_closing_date,
        extra_wire_party=extra_wire_party,
        extra_wire_callback_reference=extra_wire_callback_reference,
    )
    res = api_client.clear_to_close_purchase_agreement(
        ready["agreement_id"], ready["actors"]["co"]
    )
    agr = get_success_data(res)
    ready["agreement_status"] = agr["status"]
    return ready
