"""Payload builders and composite world builders.

Payload builders return plain dicts with the exact JSON types the PRD declares -
money as integer cents, volumes as numbers with at most three decimals,
percentages as numbers with at most two - never as strings.

The composite builders drive the real endpoints to assemble the recurring
starting positions the suite needs. Every one of them builds from scratch,
because the harness empties the database before each test.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import validate_success

from .constants import DEFAULT_CLOCK_ISO
from .test_users import (
    AUDITOR,
    AUDITOR_1_ID,
    CHAIR_1_ID,
    OFFICER,
    make_brand_licensee_headers,
    make_producer_representative_headers,
)

# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def holder_payload(
    legal_name: str = "Kilimo Coop",
    holder_type: str = "PRODUCER_ORG",
    country_code: str = "KE",
    product_code: str = "COFFEE_ARABICA",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "holder_type": holder_type,
        "country_code": country_code,
        "product_code": product_code,
    }
    payload.update(overrides)
    return payload


def node_payload(
    holder_id: str,
    node_role: str = "COOPERATIVE",
    traceability_mode: str = "PHYSICAL",
    upstream_node_id: Optional[str] = None,
    conversion_ratio: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "node_role": node_role,
        "traceability_mode": traceability_mode,
    }
    if upstream_node_id is not None:
        payload["upstream_node_id"] = upstream_node_id
    if conversion_ratio is not None:
        payload["conversion_ratio"] = conversion_ratio
    payload.update(overrides)
    return payload


def harvest_payload(
    certified_volume_kg: Any = 50000, harvest_season: str = "2026", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "certified_volume_kg": certified_volume_kg,
        "harvest_season": harvest_season,
    }
    payload.update(overrides)
    return payload


def trade_payload(
    seller_node_id: str,
    buyer_node_id: str,
    expected_seller_node_version: int,
    volume_kg: Any,
    declared_unit_price_cents_per_kg: int = 500,
    product_code: str = "COFFEE_ARABICA",
    quality_grade: str = "STANDARD",
    contract_date: str = "2026-08-01",
    is_organic: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "seller_node_id": seller_node_id,
        "buyer_node_id": buyer_node_id,
        "product_code": product_code,
        "quality_grade": quality_grade,
        "volume_kg": volume_kg,
        "declared_unit_price_cents_per_kg": int(declared_unit_price_cents_per_kg),
        "contract_date": contract_date,
        "expected_seller_node_version": int(expected_seller_node_version),
    }
    if is_organic is not None:
        payload["is_organic"] = is_organic
    payload.update(overrides)
    return payload


def committee_payload(
    holder_id: str,
    chair_user_id: str = CHAIR_1_ID,
    member_count: int = 5,
    approved_use_categories: Optional[List[str]] = None,
    quorum_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "chair_user_id": chair_user_id,
        "member_count": int(member_count),
        "approved_use_categories": list(approved_use_categories or ["EDUCATION"]),
    }
    if quorum_pct is not None:
        payload["quorum_pct"] = quorum_pct
    payload.update(overrides)
    return payload


def proposal_payload(
    committee_id: str,
    expected_fund_version: int,
    requested_amount_cents: int,
    title: str = "School roof",
    use_category: str = "EDUCATION",
    use_period_start: str = "2026-09-01",
    use_period_end: str = "2026-10-01",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "committee_id": committee_id,
        "title": title,
        "use_category": use_category,
        "requested_amount_cents": int(requested_amount_cents),
        "use_period_start": use_period_start,
        "use_period_end": use_period_end,
        "expected_fund_version": int(expected_fund_version),
    }
    payload.update(overrides)
    return payload


def vote_payload(ballot: str = "APPROVE", rationale: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ballot": ballot}
    if rationale is not None:
        payload["rationale"] = rationale
    return payload


def revision_payload(
    title: str, use_category: str, requested_amount_cents: int
) -> Dict[str, Any]:
    return {
        "title": title,
        "use_category": use_category,
        "requested_amount_cents": int(requested_amount_cents),
    }


def audit_payload(
    holder_id: str,
    window_start: str,
    window_end: str,
    auditor_user_id: str = AUDITOR_1_ID,
    audit_type: str = "INITIAL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "auditor_user_id": auditor_user_id,
        "audit_type": audit_type,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def nonconformity_payload(
    grade: str = "MAJOR",
    clause_code: str = "4.2.1",
    description: str = "Wage records incomplete",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "clause_code": clause_code,
        "grade": grade,
        "description": description,
    }
    payload.update(overrides)
    return payload


def cap_payload(narrative: str = "Payroll rebuilt and archived") -> Dict[str, Any]:
    return {"narrative": narrative}


def cap_review_payload(decision: str = "ACCEPT", review_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def license_payload(licensed_volume_kg: Any, license_year: int = 2026) -> Dict[str, Any]:
    return {"license_year": int(license_year), "licensed_volume_kg": licensed_volume_kg}


def payment_payload(amount_cents: int) -> Dict[str, Any]:
    return {"amount_cents": int(amount_cents)}


def mark_request_payload(
    brand_holder_id: str,
    claim_type: str = "FT_INGREDIENT_MASS_BALANCE",
    sku_code: str = "SKU-100",
    artwork_ref: str = "ART-100",
    requested_volume_kg: Any = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "brand_holder_id": brand_holder_id,
        "sku_code": sku_code,
        "artwork_ref": artwork_ref,
        "claim_type": claim_type,
        "requested_volume_kg": requested_volume_kg,
    }
    payload.update(overrides)
    return payload


def decision_payload(decision: str = "APPROVE", reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


def volume_report_payload(
    holder_id: str,
    counterparty_holder_id: str,
    period_start: str,
    period_end: str,
    declared_volume_kg: Any,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "holder_id": holder_id,
        "counterparty_holder_id": counterparty_holder_id,
        "period_start": period_start,
        "period_end": period_end,
        "declared_volume_kg": declared_volume_kg,
    }
    payload.update(overrides)
    return payload


def reconcile_payload(basis: str = "SELLER_BASIS") -> Dict[str, Any]:
    return {"basis": basis}


def reason_payload(reason: str = "MANUAL") -> Dict[str, Any]:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Small setup primitives
# ---------------------------------------------------------------------------


def set_clock(api, to_iso8601: str = DEFAULT_CLOCK_ISO) -> Dict[str, Any]:
    return validate_success(api.set_clock(to_iso8601, OFFICER), 200)


def register_holder(api, **kwargs: Any) -> Dict[str, Any]:
    return validate_success(api.create_holder(holder_payload(**kwargs), OFFICER), 201)


def register_node(api, headers: Dict[str, str], **kwargs: Any) -> Dict[str, Any]:
    return validate_success(api.create_node(node_payload(**kwargs), headers), 201)


def certify(api, holder_id: str) -> Dict[str, Any]:
    return validate_success(api.certify_holder(holder_id, OFFICER), 200)


def read_holder(api, holder_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_holder(holder_id, headers or OFFICER), 200)


def read_node(api, node_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_node(node_id, headers or OFFICER), 200)


def read_trade(api, trade_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_trade(trade_id, headers or OFFICER), 200)


def read_fund(api, holder_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The producer's single premium fund, read through the holder's fund list."""
    body = validate_success(api.list_holder_funds(holder_id, headers or OFFICER), 200)
    assert isinstance(body, list) and body, f"holder {holder_id} has no premium fund"
    return body[0]


def read_committee(api, committee_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_committee(committee_id, headers or OFFICER), 200)


def read_proposal(api, proposal_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_proposal(proposal_id, headers or OFFICER), 200)


def read_audit(api, audit_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_audit(audit_id, headers or OFFICER), 200)


def read_nonconformity(api, nc_id: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(api.get_nonconformity(nc_id, headers or OFFICER), 200)


def read_ledger_entries(api, headers: Optional[Dict[str, str]] = None, **params: Any) -> List[Dict[str, Any]]:
    return validate_success(api.list_ledger_entries(headers or OFFICER, params or None), 200)


# ---------------------------------------------------------------------------
# Composite builders
# ---------------------------------------------------------------------------


def build_certified_producer(
    api,
    legal_name: str = "Kilimo Coop",
    country_code: str = "KE",
    product_code: str = "COFFEE_ARABICA",
    node_role: str = "COOPERATIVE",
    traceability_mode: str = "PHYSICAL",
    harvest_kg: Optional[Any] = None,
    harvest_season: str = "2026",
) -> Dict[str, Any]:
    """A CERTIFIED PRODUCER_ORG holding one ACTIVE node and its zeroed premium fund.

    The node is registered while the holder is still PENDING, so certification
    is granted against a holder that "has at least one supply chain node whose
    status is REGISTERED" and the node reaches ACTIVE through the documented
    REGISTERED to ACTIVE cascade.
    """
    holder = register_holder(
        api, legal_name=legal_name, holder_type="PRODUCER_ORG",
        country_code=country_code, product_code=product_code,
    )
    holder_id = holder["id"]
    headers = make_producer_representative_headers(holder_id)
    node = register_node(
        api, headers, holder_id=holder_id, node_role=node_role, traceability_mode=traceability_mode
    )
    certify(api, holder_id)
    node_version = read_node(api, node["id"])["version"]
    if harvest_kg is not None:
        declared = validate_success(
            api.declare_harvest(
                node["id"], harvest_payload(harvest_kg, harvest_season), headers
            ),
            201,
        )
        node_version = read_node(api, node["id"])["version"]
        del declared
    return {
        "holder_id": holder_id,
        "holder_headers": headers,
        "node_id": node["id"],
        "node_version": node_version,
    }


def build_certified_chain(
    api,
    product_code: str = "COFFEE_ARABICA",
    seller_mode: str = "PHYSICAL",
    buyer_mode: Optional[str] = None,
    seller_role: str = "COOPERATIVE",
    buyer_role: str = "BRAND_NODE",
    conversion_ratio: Optional[float] = None,
    harvest_kg: Optional[Any] = 50000,
    harvest_season: str = "2026",
    producer_name: str = "Kilimo Coop",
    brand_name: str = "Nordic Roasters",
    producer_country: str = "KE",
    brand_country: str = "SE",
) -> Dict[str, Any]:
    """A CERTIFIED producer and a CERTIFIED brand joined by one certified link.

    The brand node names the producer's node as its immediate ``upstream_node_id``,
    which is the certified link a trade between the two requires, and the
    producer's node carries ``harvest_kg`` of declared certified input.
    """
    producer = register_holder(
        api, legal_name=producer_name, holder_type="PRODUCER_ORG",
        country_code=producer_country, product_code=product_code,
    )
    brand = register_holder(
        api, legal_name=brand_name, holder_type="BRAND",
        country_code=brand_country, product_code=product_code,
    )
    producer_id, brand_id = producer["id"], brand["id"]
    producer_headers = make_producer_representative_headers(producer_id)
    brand_headers = make_brand_licensee_headers(brand_id)

    seller_node = register_node(
        api, producer_headers, holder_id=producer_id, node_role=seller_role,
        traceability_mode=seller_mode,
    )
    buyer_node = register_node(
        api, brand_headers, holder_id=brand_id, node_role=buyer_role,
        traceability_mode=buyer_mode or seller_mode,
        upstream_node_id=seller_node["id"], conversion_ratio=conversion_ratio,
    )
    certify(api, producer_id)
    certify(api, brand_id)

    if harvest_kg is not None:
        validate_success(
            api.declare_harvest(
                seller_node["id"], harvest_payload(harvest_kg, harvest_season), producer_headers
            ),
            201,
        )
    seller_version = read_node(api, seller_node["id"])["version"]
    fund = read_fund(api, producer_id)
    return {
        "producer_id": producer_id,
        "brand_id": brand_id,
        "producer_headers": producer_headers,
        "brand_headers": brand_headers,
        "seller_node_id": seller_node["id"],
        "buyer_node_id": buyer_node["id"],
        "seller_node_version": seller_version,
        "fund_id": fund["id"],
        "fund_version": fund["version"],
    }


def record_trade(
    api,
    chain: Dict[str, Any],
    volume_kg: Any,
    declared_unit_price_cents_per_kg: int = 500,
    product_code: str = "COFFEE_ARABICA",
    quality_grade: str = "STANDARD",
    contract_date: str = "2026-08-01",
    is_organic: Optional[bool] = None,
    seller_node_version: Optional[int] = None,
) -> Dict[str, Any]:
    """Record one trade out of the chain's seller node and refresh the cached version.

    Unless the caller pins ``seller_node_version`` deliberately, the seller node's
    current version is read immediately before the create, because verification,
    settlement and every earlier create all bump it.
    """
    version = (
        seller_node_version
        if seller_node_version is not None
        else read_node(api, chain["seller_node_id"])["version"]
    )
    trade = validate_success(
        api.create_trade(
            trade_payload(
                chain["seller_node_id"], chain["buyer_node_id"], version, volume_kg,
                declared_unit_price_cents_per_kg=declared_unit_price_cents_per_kg,
                product_code=product_code, quality_grade=quality_grade,
                contract_date=contract_date, is_organic=is_organic,
            ),
            chain["producer_headers"],
        ),
        201,
    )
    chain["seller_node_version"] = read_node(api, chain["seller_node_id"])["version"]
    return trade


def verify_trade(api, trade_id: str, outcome: str = "VERIFIED", headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return validate_success(
        api.verify_trade(trade_id, {"outcome": outcome}, headers or AUDITOR), 200
    )


def settle_trade(api, trade_id: str) -> Dict[str, Any]:
    return validate_success(api.settle_trade(trade_id, OFFICER), 200)


def record_settled_trade(
    api, chain: Dict[str, Any], volume_kg: Any, **kwargs: Any
) -> Dict[str, Any]:
    """Record, verify and settle one trade, so its premium accrues into the fund."""
    trade = record_trade(api, chain, volume_kg, **kwargs)
    verify_trade(api, trade["id"])
    settled = settle_trade(api, trade["id"])
    chain["seller_node_version"] = read_node(api, chain["seller_node_id"])["version"]
    chain["fund_version"] = read_fund(api, chain["producer_id"])["version"]
    return settled


def constitute_committee(
    api,
    holder_id: str,
    chair_user_id: str = CHAIR_1_ID,
    member_count: int = 5,
    approved_use_categories: Optional[List[str]] = None,
    quorum_pct: Optional[float] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.create_committee(
            committee_payload(
                holder_id, chair_user_id=chair_user_id, member_count=member_count,
                approved_use_categories=approved_use_categories, quorum_pct=quorum_pct,
            ),
            OFFICER,
        ),
        201,
    )


def build_funded_committee(
    api,
    volume_kg: Any = 30000,
    approved_use_categories: Optional[List[str]] = None,
    member_count: int = 5,
    quorum_pct: Optional[float] = None,
    chair_user_id: str = CHAIR_1_ID,
    **chain_kwargs: Any,
) -> Dict[str, Any]:
    """A certified chain whose fund has been filled by one settled trade.

    A 30000 kg non-organic COFFEE_ARABICA shipment accrues 2400000 cents, which
    is past the 1000000 cent activation threshold, so the committee is ACTIVE.
    """
    chain = build_certified_chain(api, **chain_kwargs)
    committee = constitute_committee(
        api, chain["producer_id"], chair_user_id=chair_user_id, member_count=member_count,
        approved_use_categories=approved_use_categories, quorum_pct=quorum_pct,
    )
    trade = record_settled_trade(api, chain, volume_kg)
    fund = read_fund(api, chain["producer_id"])
    chain["committee_id"] = committee["id"]
    chain["trade_id"] = trade["id"]
    chain["fund_version"] = fund["version"]
    return chain


def draft_proposal(
    api,
    chain: Dict[str, Any],
    requested_amount_cents: int,
    title: str = "School roof",
    use_category: str = "EDUCATION",
    use_period_start: str = "2026-09-01",
    use_period_end: str = "2026-10-01",
    chair_headers: Optional[Dict[str, str]] = None,
    expected_fund_version: Optional[int] = None,
) -> Dict[str, Any]:
    from .test_users import CHAIR

    version = (
        expected_fund_version
        if expected_fund_version is not None
        else read_fund(api, chain["producer_id"])["version"]
    )
    proposal = validate_success(
        api.create_proposal(
            proposal_payload(
                chain["committee_id"], version, requested_amount_cents, title=title,
                use_category=use_category, use_period_start=use_period_start,
                use_period_end=use_period_end,
            ),
            chair_headers or CHAIR,
        ),
        201,
    )
    chain["fund_version"] = read_fund(api, chain["producer_id"])["version"]
    return proposal


def cast_ballots(api, proposal_id: str, ballots: List[str], member_headers: Optional[List[Dict[str, str]]] = None) -> None:
    from .test_users import MEMBERS

    headers_list = member_headers or list(MEMBERS)
    for index, ballot in enumerate(ballots):
        validate_success(
            api.cast_vote(proposal_id, vote_payload(ballot), headers_list[index]), 201
        )


def schedule_audit(
    api,
    holder_id: str,
    window_start: str = "2026-08-01",
    window_end: str = "2026-08-08",
    auditor_user_id: str = AUDITOR_1_ID,
    audit_type: str = "INITIAL",
) -> Dict[str, Any]:
    return validate_success(
        api.create_audit(
            audit_payload(
                holder_id, window_start, window_end,
                auditor_user_id=auditor_user_id, audit_type=audit_type,
            ),
            OFFICER,
        ),
        201,
    )


def build_started_audit(
    api,
    holder_id: str,
    window_start: str = "2026-08-01",
    window_end: str = "2026-08-08",
    auditor_user_id: str = AUDITOR_1_ID,
    audit_type: str = "INITIAL",
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """An IN_PROGRESS audit opened on site by its assigned auditor."""
    audit = schedule_audit(
        api, holder_id, window_start, window_end, auditor_user_id=auditor_user_id, audit_type=audit_type
    )
    return validate_success(api.start_audit(audit["id"], auditor_headers or AUDITOR), 200)


def raise_finding(
    api,
    audit_id: str,
    grade: str = "MAJOR",
    clause_code: str = "4.2.1",
    description: str = "Wage records incomplete",
    auditor_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.create_nonconformity(
            audit_id, nonconformity_payload(grade, clause_code, description),
            auditor_headers or AUDITOR,
        ),
        201,
    )


def issue_license(api, holder_id: str, licensed_volume_kg: Any, license_year: int = 2026) -> Dict[str, Any]:
    return validate_success(
        api.issue_label_license(holder_id, license_payload(licensed_volume_kg, license_year), OFFICER),
        200,
    )


def build_settled_license(
    api, holder_id: str, licensed_volume_kg: Any = 100000, license_year: int = 2026
) -> Dict[str, Any]:
    """An ACTIVE licence whose fee has been paid in full, so license_fee_settled is true."""
    holder = issue_license(api, holder_id, licensed_volume_kg, license_year)
    fee = int(holder["license_fee_cents"])
    return validate_success(
        api.pay_license_fee(
            holder_id, payment_payload(fee), make_brand_licensee_headers(holder_id)
        ),
        201,
    )


def file_mark_usage_request(
    api, brand_holder_id: str, claim_type: str = "FT_INGREDIENT_MASS_BALANCE", **kwargs: Any
) -> Dict[str, Any]:
    return validate_success(
        api.create_mark_usage_request(
            mark_request_payload(brand_holder_id, claim_type=claim_type, **kwargs),
            make_brand_licensee_headers(brand_holder_id),
        ),
        201,
    )


def file_volume_report(
    api,
    holder_id: str,
    counterparty_holder_id: str,
    period_start: str,
    period_end: str,
    declared_volume_kg: Any,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    return validate_success(
        api.create_volume_report(
            volume_report_payload(
                holder_id, counterparty_holder_id, period_start, period_end, declared_volume_kg
            ),
            headers or make_producer_representative_headers(holder_id),
        ),
        201,
    )
