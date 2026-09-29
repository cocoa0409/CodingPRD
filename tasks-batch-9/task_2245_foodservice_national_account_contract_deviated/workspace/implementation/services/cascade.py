"""Multi-row cascades: contract termination and expiry, the clock expiry sweep,
the four-hop price-notice cost cascade and the four-hop dispute-credit cascade
(PRD sections 2.9, 3.3, 3.6, 3.9)."""

from db import db, touch, values
from services import billback
from services.compliance import recompute_posture
from services.pricing import rederive_deviated_price

DEVIATION_NON_TERMINAL = (
    "DRAFT", "SUBMITTED", "MANUFACTURER_APPROVED", "REVISION_REQUESTED",
    "ACTIVE", "PRICE_CEILING_BREACHED",
)


def _contract_deviations(contract_id):
    return [d for d in values(db.deviation_agreements) if d["contract_id"] == contract_id]


def _contract_tiers(contract_id):
    return [t for t in values(db.contract_tiers) if t["contract_id"] == contract_id]


def _contract_coverages(contract_id):
    return [c for c in values(db.dc_coverages) if c["contract_id"] == contract_id]


def supersede_tiers(contract_id):
    for tier in _contract_tiers(contract_id):
        if tier["status"] == "ACTIVE":
            tier["status"] = "SUPERSEDED"
            touch(tier)


def end_coverages(contract_id):
    for coverage in _contract_coverages(contract_id):
        if coverage["status"] == "ACTIVE":
            coverage["status"] = "ENDED"
            touch(coverage)


def terminate_deviations(contract_id):
    """Returns the ids of the agreements this cascade moved to TERMINATED."""
    touched = []
    for dev in _contract_deviations(contract_id):
        if dev["status"] in DEVIATION_NON_TERMINAL:
            dev["status"] = "TERMINATED"
            touch(dev)
            touched.append(dev["id"])
    return touched


def terminate_contract_cascade(contract):
    """PRD 3.3: deviations terminate, tiers supersede, coverages end, and an
    amendment draft hands its parent back to ACTIVE."""
    terminate_deviations(contract["id"])
    supersede_tiers(contract["id"])
    end_coverages(contract["id"])
    parent_id = contract.get("amends_contract_id")
    if parent_id:
        parent = db.contracts.get(parent_id)
        if parent is not None and parent["status"] == "AMENDING":
            parent["status"] = "ACTIVE"
            touch(parent)


def expire_parent_on_amendment_signature(contract):
    """PRD 3.3: signing an amendment draft expires its parent."""
    parent = db.contracts[contract["amends_contract_id"]]
    parent["status"] = "EXPIRED"
    supersede_tiers(parent["id"])
    end_coverages(parent["id"])
    touch(parent)


def clock_sweep(new_clock):
    """Expire contracts past effective_to and deviations at or past effective_to."""
    expired_contract_ids = []
    expired_deviation_ids = []

    for contract in values(db.contracts):
        if contract["status"] in ("ACTIVE", "SUSPENDED") and new_clock > contract["effective_to"]:
            contract["status"] = "EXPIRED"
            # PRD 3.3: the sweep reports every deviation row it touched, whether
            # the contract cascade TERMINATED it or the window EXPIRED it below.
            expired_deviation_ids.extend(terminate_deviations(contract["id"]))
            end_coverages(contract["id"])
            touch(contract)
            expired_contract_ids.append(contract["id"])

    for dev in values(db.deviation_agreements):
        if dev["status"] in ("ACTIVE", "PRICE_CEILING_BREACHED") and new_clock >= dev["effective_to"]:
            dev["status"] = "EXPIRED"
            touch(dev)
            expired_deviation_ids.append(dev["id"])

    return expired_contract_ids, expired_deviation_ids


def notice_activation_cascade(notice, clock):
    """Four-hop cost cascade of an activated price change notice (PRD 3.6)."""
    # HOP 1 -- the product's cost field moves.
    product = db.products[notice["product_id"]]
    from services.pricing import COST_FIELD
    product[COST_FIELD[notice["cost_basis"]]] = notice["new_cost_cents"]
    product["cost_effective_at"] = clock
    touch(product)

    # HOP 2 -- ACTIVE COST_PLUS_PROTECTED deviations on that product re-derive.
    for dev in values(db.deviation_agreements):
        if dev["product_id"] != product["id"]:
            continue
        if dev["status"] != "ACTIVE" or dev["bill_back_basis"] != "COST_PLUS_PROTECTED":
            continue
        dev["deviated_price_cents"] = rederive_deviated_price(dev, notice["cost_basis"])
        dev["price_revision_count"] += 1
        breached = dev["deviated_price_cents"] > dev["max_operator_price_cents"]
        if breached:
            # HOP 3 -- the ceiling was breached.
            dev["status"] = "PRICE_CEILING_BREACHED"
        touch(dev)
        if breached:
            contract = db.contracts.get(dev["contract_id"])
            if contract is not None:
                contract["deviation_breach_count"] += 1
                # HOP 4 -- posture is recomputed and lands on RESTRICTED.
                recompute_posture(contract)
                touch(contract)


def credit_issue_cascade(dispute, line, clock):
    """Four-hop credit cascade of an issued dispute credit (PRD 3.9)."""
    # HOP 2 -- the order line is credited and its invoiced price rewritten.
    line["pricing_status"] = "CREDITED"
    line["invoiced_unit_price_cents"] = dispute["audited_correct_unit_price_cents"]
    line["extended_price_cents"] = (
        line["invoiced_unit_price_cents"] * line["quantity_cases"])
    line["invoice_total_cents"] = line["extended_price_cents"] + line["service_fee_cents"]
    line["credited_amount_cents"] += dispute["credit_amount_cents"]
    touch(line)

    # SIDE BRANCH -- a claimed line forces its claim back to DISPUTED.
    if line["billback_status"] == "CLAIMED" and line["bill_back_claim_id"]:
        claim = db.bill_back_claims.get(line["bill_back_claim_id"])
        if claim is not None and claim["status"] == "SUBMITTED":
            claim["status"] = "DISPUTED"
            billback.recompute_claim_amount(claim)
            touch(claim)
            manufacturer = db.manufacturers.get(claim["manufacturer_id"])
            if manufacturer is not None:
                billback.recompute_exposure(manufacturer)

    # HOP 3 -- the covering CLOSED period reopens.
    period = db.rebate_periods.get(line["rebate_period_id"])
    if period is None or period["status"] != "CLOSED":
        return
    operator_rebate_cents = period["operator_rebate_cents"] or 0
    manufacturer_funded_cents = period["manufacturer_funded_cents"] or 0
    period["status"] = "OPEN"
    for field in ("gross_purchases_cents", "contracted_purchases_cents", "qualifying_cases",
                  "contracted_cases", "compliance_pct", "rebate_rate_pct",
                  "operator_rebate_cents", "manufacturer_funded_cents",
                  "distributor_funded_cents", "closed_at"):
        period[field] = None
    period["reopen_count"] += 1
    touch(period)

    # HOP 4 -- the contract and funding manufacturer ledgers unwind.
    contract = db.contracts.get(period["contract_id"])
    if contract is not None:
        contract["rebate_payable_cents"] -= operator_rebate_cents
        recompute_posture(contract)
        touch(contract)
        manufacturer = db.manufacturers.get(contract["rebate_funding_manufacturer_id"])
        if manufacturer is not None:
            manufacturer["rebate_funding_payable_cents"] -= manufacturer_funded_cents
            touch(manufacturer)
