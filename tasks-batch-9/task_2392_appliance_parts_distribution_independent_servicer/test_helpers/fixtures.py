"""Composite setup helpers.

Every helper builds its state from scratch through the API, because each test
starts against an empty database.  Setup calls use the lenient
``get_success_data`` validator so a broken precondition surfaces as a clear
"Setup step failed" message rather than an obscure assertion.

Identity threading: a ``Servicer`` acts as its ``ServicerAccount`` and a
``BranchCounterRep`` acts as its ``Branch``, so every ownership-gated call below
threads the real entity id through ``make_servicer_headers`` /
``make_branch_counter_rep_headers``.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    branch_payload,
    cancellation_payload,
    credit_decision_payload,
    inventory_adjustment_payload,
    inventory_record_payload,
    model_part_xref_payload,
    oem_response_payload,
    order_line_payload,
    part_payload,
    payment_payload,
    price_file_line_payload,
    price_file_payload,
    pricing_tier_payload,
    resubmit_payload,
    return_authorization_payload,
    return_decision_payload,
    revocation_payload,
    rollback_payload,
    servicer_account_payload,
    substitute_approval_payload,
    substitute_rejection_payload,
    substitute_withdrawal_payload,
    supersession_payload,
    technician_certification_payload,
    warranty_claim_payload,
    will_call_order_payload,
    drop_ship_order_payload,
)
from .test_users import (
    CREDIT_MANAGER_USER_ONE,
    PLATFORM_ADMIN,
    PRICING_ADMIN,
    WARRANTY_ADMIN,
    make_branch_counter_rep_headers,
    make_credit_manager_headers,
    make_servicer_headers,
)

# Reads are always performed as a PlatformAdmin: that role is authorized on
# every read endpoint and is never compared against an entity id.
READER = PLATFORM_ADMIN


# ===========================================================================
# Logical clock
# ===========================================================================

def set_clock(current_utc: str) -> dict:
    """Move the server's logical UTC clock to an arbitrary instant."""
    return get_success_data(api_client.set_clock(current_utc, PLATFORM_ADMIN))


# ===========================================================================
# Reads
# ===========================================================================

def read_branch(branch_id: str) -> dict:
    return get_success_data(api_client.get_branch(branch_id, READER))


def read_part(part_id: str) -> dict:
    return get_success_data(api_client.get_part(part_id, READER))


def read_xref(xref_id: str) -> dict:
    return get_success_data(api_client.get_model_part_xref(xref_id, READER))


def read_account(account_id: str) -> dict:
    return get_success_data(api_client.get_servicer_account(account_id, READER))


def read_credit_summary(account_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_credit_summary(account_id, headers or READER)
    )


def read_certification(cert_id: str) -> dict:
    return get_success_data(
        api_client.get_technician_certification(cert_id, READER)
    )


def read_inventory(record_id: str) -> dict:
    return get_success_data(api_client.get_inventory_record(record_id, READER))


def read_price_file(price_file_id: str) -> dict:
    return get_success_data(api_client.get_price_file(price_file_id, READER))


def read_price_file_line(line_id: str) -> dict:
    return get_success_data(api_client.get_price_file_line(line_id, READER))


def read_order(order_id: str) -> dict:
    return get_success_data(api_client.get_part_order(order_id, READER))


def read_line(line_id: str) -> dict:
    return get_success_data(api_client.get_order_line(line_id, READER))


def read_substitute_request(request_id: str) -> dict:
    return get_success_data(api_client.get_substitute_request(request_id, READER))


def read_claim(claim_id: str) -> dict:
    return get_success_data(api_client.get_warranty_claim(claim_id, READER))


def read_return_authorization(ra_id: str) -> dict:
    return get_success_data(api_client.get_return_authorization(ra_id, READER))


def list_rows(list_method, **params) -> list:
    """Run a list endpoint as a reader and return just the rows."""
    body = get_success_data(list_method(READER, params=params or None))
    return body


def list_parts(**params) -> list:
    return list_rows(api_client.list_parts, **params)


def list_xrefs(**params) -> list:
    return list_rows(api_client.list_model_part_xrefs, **params)


def list_certifications(**params) -> list:
    return list_rows(api_client.list_technician_certifications, **params)


def list_inventory_records(**params) -> list:
    return list_rows(api_client.list_inventory_records, **params)


def list_orders(**params) -> list:
    return list_rows(api_client.list_part_orders, **params)


def list_order_lines(**params) -> list:
    return list_rows(api_client.list_order_lines, **params)


def list_substitute_requests(**params) -> list:
    return list_rows(api_client.list_substitute_requests, **params)


def list_warranty_claims(**params) -> list:
    return list_rows(api_client.list_warranty_claims, **params)


def list_return_authorizations(**params) -> list:
    return list_rows(api_client.list_return_authorizations, **params)


def list_price_files(**params) -> list:
    return list_rows(api_client.list_price_files, **params)


def inventory_for(branch_id: str, part_id: str) -> dict:
    """The single inventory position for one branch-and-part pair."""
    rows = list_inventory_records(branch_id=branch_id, part_id=part_id)
    assert rows, f"No inventory position for branch {branch_id} / part {part_id}"
    return rows[0]


# ===========================================================================
# Tier 1 primitives — one API call each
# ===========================================================================

def make_branch(code="STL", name="St Louis DC", region_code="MW", **options) -> dict:
    payload = branch_payload(code=code, name=name, region_code=region_code, **options)
    return get_success_data(api_client.create_branch(payload, PLATFORM_ADMIN))


def patch_branch(branch_id: str, **fields) -> dict:
    return get_success_data(
        api_client.update_branch(branch_id, dict(fields), PLATFORM_ADMIN)
    )


def make_part(part_number="W10-PUMP", oem_code="WHIRLPOOL", category="MECHANICAL",
              list_price_cents=12999, weight_grams=5200, description=None,
              **options) -> dict:
    payload = part_payload(
        part_number=part_number,
        oem_code=oem_code,
        category=category,
        list_price_cents=list_price_cents,
        weight_grams=weight_grams,
        description=description or f"{part_number} service part",
        **options,
    )
    return get_success_data(api_client.create_part(payload, PRICING_ADMIN))


def record_supersession(part: dict, target_part: dict,
                       expected_part_version=None) -> dict:
    """Link `part` onto `target_part`, guarding on the part's current version."""
    version = (
        expected_part_version
        if expected_part_version is not None
        else read_part(part["id"])["version"]
    )
    payload = supersession_payload(target_part["id"], version)
    return get_success_data(
        api_client.record_supersession(part["id"], payload, PRICING_ADMIN)
    )


def make_xref(part: dict, model_number="WTW5000DW1", position_code="P-14",
              xref_source="OEM_PUBLICATION") -> dict:
    payload = model_part_xref_payload(
        part["id"],
        model_number=model_number,
        position_code=position_code,
        xref_source=xref_source,
    )
    return get_success_data(api_client.create_model_part_xref(payload, PRICING_ADMIN))


def make_pricing_tier(tier_code="GOLD", name=None, electrical=0.15, mechanical=0.20,
                      cosmetic=0.25, sealed_system=0.10,
                      min_annual_volume_cents=5000000) -> dict:
    payload = pricing_tier_payload(
        tier_code=tier_code,
        name=name or f"{tier_code} Contract",
        discount_pct_electrical=electrical,
        discount_pct_mechanical=mechanical,
        discount_pct_cosmetic=cosmetic,
        discount_pct_sealed_system=sealed_system,
        min_annual_volume_cents=min_annual_volume_cents,
    )
    return get_success_data(api_client.create_pricing_tier(payload, PRICING_ADMIN))


def make_account(tier: dict, business_name="Ace Appliance Repair",
                 oem_authorizations=None, credit_terms="NET_30",
                 credit_limit_cents=10000000,
                 core_liability_limit_cents=10000000,
                 as_user_id=CREDIT_MANAGER_USER_ONE) -> dict:
    payload = servicer_account_payload(
        tier["id"],
        business_name=business_name,
        oem_authorizations=(
            ["WHIRLPOOL"] if oem_authorizations is None else oem_authorizations
        ),
        credit_terms=credit_terms,
        credit_limit_cents=credit_limit_cents,
        core_liability_limit_cents=core_liability_limit_cents,
    )
    return get_success_data(
        api_client.create_servicer_account(
            payload, make_credit_manager_headers(as_user_id)
        )
    )


def patch_account(account_id: str, as_user_id=CREDIT_MANAGER_USER_ONE, **fields) -> dict:
    return get_success_data(
        api_client.update_servicer_account(
            account_id, dict(fields), make_credit_manager_headers(as_user_id)
        )
    )


def run_tier_review(account_id: str, as_user_id=CREDIT_MANAGER_USER_ONE) -> dict:
    return get_success_data(
        api_client.tier_review(account_id, make_credit_manager_headers(as_user_id))
    )


def make_certification(account: dict, technician_name="Dana Ruiz",
                       oem_code="WHIRLPOOL", cert_level="BASIC",
                       training_completed_at="2026-01-01T00:00:00Z",
                       expires_at="2027-01-01T00:00:00Z") -> dict:
    payload = technician_certification_payload(
        account["id"],
        technician_name=technician_name,
        oem_code=oem_code,
        cert_level=cert_level,
        training_completed_at=training_completed_at,
        expires_at=expires_at,
    )
    return get_success_data(
        api_client.create_technician_certification(payload, WARRANTY_ADMIN)
    )


def revoke_certification(cert_id: str,
                         reason="technician left the business") -> dict:
    return get_success_data(
        api_client.revoke_technician_certification(
            cert_id, revocation_payload(reason), WARRANTY_ADMIN
        )
    )


def make_inventory(branch: dict, part: dict, on_hand_units=10, **options) -> dict:
    payload = inventory_record_payload(
        branch["id"], part["id"], on_hand_units=on_hand_units, **options
    )
    return get_success_data(
        api_client.create_inventory_record(
            payload, make_branch_counter_rep_headers(branch["id"])
        )
    )


def adjust_inventory(record: dict, branch: dict, delta_units: int,
                     reason="cycle count") -> dict:
    return get_success_data(
        api_client.adjust_inventory_record(
            record["id"],
            inventory_adjustment_payload(delta_units, reason),
            make_branch_counter_rep_headers(branch["id"]),
        )
    )


def make_price_file(file_version: int, effective_at="2026-08-01T00:00:00Z",
                    effective_until=None) -> dict:
    payload = price_file_payload(
        file_version=file_version, effective_at=effective_at
    )
    if effective_until is not None:
        payload["effective_until"] = effective_until
    return get_success_data(api_client.create_price_file(payload, PRICING_ADMIN))


def add_price_file_line(price_file: dict, part: dict, new_list_price_cents: int,
                        **options) -> dict:
    payload = price_file_line_payload(
        part["id"], new_list_price_cents, **options
    )
    return get_success_data(
        api_client.create_price_file_line(price_file["id"], payload, PRICING_ADMIN)
    )


def publish_price_file(price_file_id: str) -> dict:
    return get_success_data(
        api_client.publish_price_file(price_file_id, PRICING_ADMIN)
    )


def rollback_price_file(price_file_id: str, reason="published in error") -> dict:
    return get_success_data(
        api_client.rollback_price_file(
            price_file_id, rollback_payload(reason), PRICING_ADMIN
        )
    )


# ===========================================================================
# Tier 2 primitives — order intake
# ===========================================================================

def open_will_call_order(account: dict, branch: dict,
                         purchase_order_ref=None) -> dict:
    payload = will_call_order_payload(account["id"], branch["id"])
    if purchase_order_ref is not None:
        payload["purchase_order_ref"] = purchase_order_ref
    return get_success_data(
        api_client.create_part_order(payload, make_servicer_headers(account["id"]))
    )


def open_drop_ship_order(account: dict, ship_to_zip: str,
                         purchase_order_ref=None) -> dict:
    payload = drop_ship_order_payload(account["id"], ship_to_zip)
    if purchase_order_ref is not None:
        payload["purchase_order_ref"] = purchase_order_ref
    return get_success_data(
        api_client.create_part_order(payload, make_servicer_headers(account["id"]))
    )


def add_line(order: dict, part: dict, quantity=1, expected_version=None) -> dict:
    """Add one line to a draft order, re-reading the order's current version
    unless the caller pins one explicitly."""
    version = (
        expected_version
        if expected_version is not None
        else read_order(order["id"])["version"]
    )
    payload = order_line_payload(part["id"], quantity, version)
    return get_success_data(
        api_client.add_order_line(
            order["id"], payload, make_servicer_headers(order["servicer_account_id"])
        )
    )


def cancel_line(line: dict, order: dict,
                reason="servicer changed their mind") -> dict:
    return get_success_data(
        api_client.cancel_order_line(
            line["id"],
            cancellation_payload(reason),
            make_servicer_headers(order["servicer_account_id"]),
        )
    )


def cancel_order(order: dict, reason="servicer changed their mind") -> dict:
    return get_success_data(
        api_client.cancel_part_order(
            order["id"],
            cancellation_payload(reason),
            make_servicer_headers(order["servicer_account_id"]),
        )
    )


def approve_credit(order: dict, as_user_id=CREDIT_MANAGER_USER_ONE,
                   decision_note=None) -> dict:
    payload = credit_decision_payload("APPROVE")
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(
        api_client.credit_decision(
            order["id"], payload, make_credit_manager_headers(as_user_id)
        )
    )


def decline_credit(order: dict, as_user_id=CREDIT_MANAGER_USER_ONE,
                   decision_note=None) -> dict:
    payload = credit_decision_payload("DECLINE")
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(
        api_client.credit_decision(
            order["id"], payload, make_credit_manager_headers(as_user_id)
        )
    )


def allocate_order(order: dict, branch: dict) -> dict:
    return get_success_data(
        api_client.allocate_part_order(
            order["id"], make_branch_counter_rep_headers(branch["id"])
        )
    )


def fulfill_order(order: dict, branch: dict, tracking_ref=None) -> dict:
    payload = {} if tracking_ref is None else {"tracking_ref": tracking_ref}
    return get_success_data(
        api_client.fulfill_part_order(
            order["id"], payload, make_branch_counter_rep_headers(branch["id"])
        )
    )


def pay_order(order: dict, amount_cents: int, payment_reference=None,
              as_user_id=CREDIT_MANAGER_USER_ONE) -> dict:
    payload = payment_payload(amount_cents)
    if payment_reference is not None:
        payload["payment_reference"] = payment_reference
    return get_success_data(
        api_client.post_payment(
            order["id"], payload, make_credit_manager_headers(as_user_id)
        )
    )


# ===========================================================================
# Tier 2 primitives — substitutes, warranty, returns
# ===========================================================================

def pending_substitute_request_for(line_id: str) -> dict:
    """The substitute request opened against one order line."""
    rows = list_substitute_requests(order_line_id=line_id)
    assert rows, f"No substitute request opened for line {line_id}"
    return rows[0]


def approve_substitute(request_id: str, substitute_part: dict,
                       decision_note="only stock available") -> dict:
    payload = substitute_approval_payload(
        substitute_part["id"], decision_note=decision_note
    )
    return get_success_data(
        api_client.decide_substitute_request(request_id, payload, WARRANTY_ADMIN)
    )


def reject_substitute(request_id: str,
                      decision_note="no comparable part exists") -> dict:
    payload = substitute_rejection_payload(decision_note=decision_note)
    return get_success_data(
        api_client.decide_substitute_request(request_id, payload, WARRANTY_ADMIN)
    )


def withdraw_substitute(request_id: str, account: dict,
                        reason="servicer sourced the part elsewhere") -> dict:
    return get_success_data(
        api_client.withdraw_substitute_request(
            request_id,
            substitute_withdrawal_payload(reason),
            make_servicer_headers(account["id"]),
        )
    )


def make_claim(account: dict, line: dict, defect_code="PUMP-SEIZED",
               appliance_model_number="WTW5000DW1") -> dict:
    payload = warranty_claim_payload(
        account["id"],
        line["id"],
        defect_code=defect_code,
        appliance_model_number=appliance_model_number,
    )
    return get_success_data(api_client.create_warranty_claim(payload, WARRANTY_ADMIN))


def submit_claim(claim_id: str, oem_reference=None) -> dict:
    payload = {} if oem_reference is None else {"oem_reference": oem_reference}
    return get_success_data(
        api_client.submit_warranty_claim(claim_id, payload, WARRANTY_ADMIN)
    )


def record_oem_outcome(claim_id: str, outcome: str, **options) -> dict:
    return get_success_data(
        api_client.record_oem_response(
            claim_id, oem_response_payload(outcome, **options), WARRANTY_ADMIN
        )
    )


def resubmit_claim(claim_id: str,
                   additional_info="photographs of the failed part") -> dict:
    return get_success_data(
        api_client.resubmit_warranty_claim(
            claim_id, resubmit_payload(additional_info), WARRANTY_ADMIN
        )
    )


def credit_claim(claim_id: str, as_user_id=CREDIT_MANAGER_USER_ONE) -> dict:
    return get_success_data(
        api_client.credit_warranty_claim(
            claim_id, make_credit_manager_headers(as_user_id)
        )
    )


def request_return(account: dict, line: dict, quantity: int, reason_code: str,
                   return_branch: dict) -> dict:
    payload = return_authorization_payload(
        account["id"], line["id"], quantity, reason_code, return_branch["id"]
    )
    return get_success_data(
        api_client.create_return_authorization(
            payload, make_servicer_headers(account["id"])
        )
    )


def decide_return(ra_id: str, decision="APPROVE", waive_restocking_fee=None,
                  decision_note=None, as_user_id=CREDIT_MANAGER_USER_ONE) -> dict:
    payload = return_decision_payload(decision)
    if waive_restocking_fee is not None:
        payload["waive_restocking_fee"] = waive_restocking_fee
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(
        api_client.decide_return_authorization(
            ra_id, payload, make_credit_manager_headers(as_user_id)
        )
    )


def receive_return(ra_id: str, branch: dict) -> dict:
    return get_success_data(
        api_client.receive_return_authorization(
            ra_id, make_branch_counter_rep_headers(branch["id"])
        )
    )


# ===========================================================================
# Tier 3 composites — recurring order lifecycles
# ===========================================================================

def setup_catalog(tier_kwargs=None, branch_kwargs=None, part_kwargs=None,
                  on_hand_units=10, account_kwargs=None, cert_kwargs=None) -> dict:
    """Contract tier, one open branch, one catalog part, one inventory position,
    one servicer account, and optionally one technician certification."""
    tier = make_pricing_tier(**(tier_kwargs or {}))
    branch = make_branch(**(branch_kwargs or {}))
    part = make_part(**(part_kwargs or {}))
    inventory = (
        make_inventory(branch, part, on_hand_units=on_hand_units)
        if on_hand_units is not None
        else None
    )
    account = make_account(tier, **(account_kwargs or {}))
    cert = make_certification(account, **cert_kwargs) if cert_kwargs else None
    return {
        "tier": tier,
        "branch": branch,
        "part": part,
        "inventory": inventory,
        "account": account,
        "cert": cert,
    }


def setup_will_call_order(stage="fulfilled", quantity=3, tier_kwargs=None,
                          branch_kwargs=None, part_kwargs=None,
                          account_kwargs=None, cert_kwargs=None,
                          on_hand_units=10, purchase_order_ref=None,
                          tracking_ref=None) -> dict:
    """Walk a will-call order to the requested stage.

    Stages, in order: ``draft`` (order only), ``lines`` (one line added),
    ``credit`` (credit approved), ``allocated``, ``fulfilled``.
    Returns the world dict plus ``order`` and ``line``.
    """
    world = setup_catalog(
        tier_kwargs=tier_kwargs,
        branch_kwargs=branch_kwargs,
        part_kwargs=part_kwargs,
        on_hand_units=on_hand_units,
        account_kwargs=account_kwargs,
        cert_kwargs=cert_kwargs,
    )
    order = open_will_call_order(
        world["account"], world["branch"], purchase_order_ref=purchase_order_ref
    )
    world["order"] = order
    world["line"] = None
    if stage == "draft":
        return world

    world["line"] = add_line(order, world["part"], quantity=quantity)
    if stage == "lines":
        return world

    approve_credit(order)
    if stage == "credit":
        return world

    allocate_order(order, world["branch"])
    if stage == "allocated":
        return world

    fulfill_order(order, world["branch"], tracking_ref=tracking_ref)
    if stage == "fulfilled":
        return world

    raise ValueError(f"Unknown stage {stage!r}")


def setup_fulfilled_line(quantity=3, **kwargs) -> dict:
    """A shipped will-call line — the precondition for returns and warranty."""
    return setup_will_call_order(stage="fulfilled", quantity=quantity, **kwargs)


def setup_obsolete_part_line(obsolete_part_kwargs=None, tier_kwargs=None,
                             branch_kwargs=None, account_kwargs=None,
                             quantity=1, purchase_order_ref=None) -> dict:
    """A will-call order whose only line resolved onto an obsolete part, so the
    line sits in SUBSTITUTE_PENDING with a PENDING substitute request."""
    tier = make_pricing_tier(**(tier_kwargs or {}))
    branch = make_branch(**(branch_kwargs or {}))
    defaults = {
        "part_number": "W10-OLDPUMP",
        "category": "MECHANICAL",
        "list_price_cents": 12999,
        "weight_grams": 5200,
        "lifecycle_status": "OBSOLETE",
    }
    defaults.update(obsolete_part_kwargs or {})
    obsolete_part = make_part(**defaults)
    account = make_account(tier, **(account_kwargs or {}))
    order = open_will_call_order(
        account, branch, purchase_order_ref=purchase_order_ref
    )
    line = add_line(order, obsolete_part, quantity=quantity)
    request = pending_substitute_request_for(line["id"])
    return {
        "tier": tier,
        "branch": branch,
        "part": obsolete_part,
        "account": account,
        "order": order,
        "line": line,
        "substitute_request": request,
    }


def setup_supersession_chain(specs, oem_code="WHIRLPOOL",
                             category="MECHANICAL", weight_grams=5200) -> list:
    """Create parts newest-first from ``specs`` (a list of
    ``(part_number, list_price_cents)`` in walk order) and link each onto its
    successor, so ``specs[0]`` is the head of the chain."""
    parts = []
    for part_number, price in reversed(specs):
        parts.append(
            make_part(
                part_number=part_number,
                oem_code=oem_code,
                category=category,
                list_price_cents=price,
                weight_grams=weight_grams,
            )
        )
    parts.reverse()  # back to walk order: head first
    for source, target in zip(parts, parts[1:]):
        record_supersession(source, target)
    return parts


def setup_published_price_file(part: dict, new_list_price_cents: int,
                              file_version=20260801,
                              effective_at="2026-08-01T00:00:00Z",
                              effective_until=None, **line_options) -> dict:
    """Draft a single-line price file against one part and publish it."""
    price_file = make_price_file(
        file_version, effective_at=effective_at, effective_until=effective_until
    )
    line = add_price_file_line(
        price_file, part, new_list_price_cents, **line_options
    )
    published = publish_price_file(price_file["id"])
    return {"price_file": published, "price_file_line": line}


# ===========================================================================
# Tier 4 composites — accumulation and threshold targeting
# ===========================================================================

def setup_order_at_credit_limit(unit_quantity=3, credit_limit_cents=31197,
                                **kwargs) -> dict:
    """A credit-approved will-call order whose exposure sits exactly on the
    account's credit limit."""
    account_kwargs = dict(kwargs.pop("account_kwargs", None) or {})
    account_kwargs["credit_limit_cents"] = credit_limit_cents
    return setup_will_call_order(
        stage="credit", quantity=unit_quantity,
        account_kwargs=account_kwargs, **kwargs
    )


def setup_approved_return(reason_code="NO_LONGER_NEEDED", return_quantity=1,
                          quantity=3, request_clock=None,
                          waive_restocking_fee=None,
                          decide_as_user_id=CREDIT_MANAGER_USER_ONE,
                          **kwargs) -> dict:
    """Ship a will-call line, then raise and approve a return against it."""
    world = setup_fulfilled_line(quantity=quantity, **kwargs)
    if request_clock is not None:
        set_clock(request_clock)
    ra = request_return(
        world["account"], world["line"], return_quantity, reason_code,
        world["branch"],
    )
    decided = decide_return(
        ra["id"], "APPROVE",
        waive_restocking_fee=waive_restocking_fee,
        as_user_id=decide_as_user_id,
    )
    world["return_authorization"] = decided
    return world


def setup_credited_return(**kwargs) -> dict:
    """Ship a line, approve a return against it, and physically receive it so
    the credit posts."""
    world = setup_approved_return(**kwargs)
    world["return_authorization"] = receive_return(
        world["return_authorization"]["id"], world["branch"]
    )
    return world


def setup_submitted_claim(quantity=3, cert_kwargs=None, oem_reference=None,
                          **kwargs) -> dict:
    """Ship a line and submit a warranty claim against it."""
    world = setup_fulfilled_line(
        quantity=quantity,
        cert_kwargs=cert_kwargs or {"cert_level": "BASIC"},
        **kwargs,
    )
    claim = make_claim(world["account"], world["line"])
    world["claim"] = submit_claim(claim["id"], oem_reference=oem_reference)
    return world


def setup_claim_in_info_requested(**kwargs) -> dict:
    """Submit a claim and have the OEM ask for more information."""
    world = setup_submitted_claim(**kwargs)
    world["claim"] = record_oem_outcome(world["claim"]["id"], "INFO_REQUESTED")
    return world


# ===========================================================================
# Tier 5 composites — terminal and finalized states
# ===========================================================================

def setup_paid_prepay_order(quantity=1, **kwargs) -> dict:
    """A PREPAY account whose order has been paid while still in DRAFT."""
    account_kwargs = dict(kwargs.pop("account_kwargs", None) or {})
    account_kwargs["credit_terms"] = "PREPAY"
    world = setup_will_call_order(
        stage="credit", quantity=quantity, account_kwargs=account_kwargs, **kwargs
    )
    order = read_order(world["order"]["id"])
    pay_order(order, order["total_cents"])
    return world


def setup_written_off_account(**kwargs) -> dict:
    """An account suspended after one order has already shipped."""
    world = setup_fulfilled_line(**kwargs)
    patch_account(world["account"]["id"], account_status="SUSPENDED")
    return world
