"""Shared derivations, state transitions and the four named cascades.

Every entity a cascade touches gets its own updated_at refresh and its own
version increment (PRD section 2.9). Derived fields are recomputed after the
state change that caused them.
"""

import clock
import db
from services import calc


def bump(table, row):
    return db.touch(table, row)


def recompute_product_derived(product):
    """Gap score first, then posture: the posture reads the fresh score."""
    product["risk_weighted_gap_score"] = calc.risk_weighted_gap_score(product)
    product["compliance_posture"] = calc.compliance_posture(product)
    return product


def recompute_distribution(product):
    calc.recompute_distribution_ledger(product)
    return product


def resize_plan(plan, product):
    category = db.get("product_categories", product["category_id"])
    plan["units_authorized"] = calc.sampling_plan_units_authorized(
        product, category, plan
    )
    calc.recompute_plan_ledger(plan)
    return plan


def refresh_plan_ledger(plan):
    return calc.recompute_plan_ledger(plan)


def stamp_periodic_due(plan, product):
    plan["periodic_due_at"] = calc.periodic_due_at(product, plan["last_verified_at"])
    return plan


# --------------------------------------------------------------------------
# Component part reliance eligibility
# --------------------------------------------------------------------------

def rules_applying_to_part(product, part):
    """Rules of required_rule_ids whose mapping predicate holds for this part."""
    now = clock.now()
    out = []
    for rule_id in product["required_rule_ids"]:
        for mapping in db.all_rows("category_rule_mappings"):
            if mapping["category_id"] != product["category_id"]:
                continue
            if mapping["rule_id"] != rule_id:
                continue
            if mapping["mapping_state"] != "ACTIVE":
                continue
            if mapping["effective_from"] > now:
                continue
            if calc._condition_holds(mapping["applicability_condition"], [part]):
                out.append(rule_id)
                break
    return out


def maybe_promote_part(part, product):
    """PENDING -> VALID once every applicable required rule is relied upon."""
    if part["reliance_status"] != "PENDING":
        return False
    applicable = rules_applying_to_part(product, part)
    if not applicable:
        return False
    certs = db.find("component_part_certificates", component_part_id=part["id"])
    relied = {c["rule_id"] for c in certs if c["reliance_state"] == "RELIED_UPON"}
    if all(rule_id in relied for rule_id in applicable):
        part["reliance_status"] = "VALID"
        bump("component_parts", part)
        return True
    return False


# --------------------------------------------------------------------------
# Order compensation shared by cancellation and invalidation
# --------------------------------------------------------------------------

def release_order_commitments(order, laboratory=None):
    """Return sample units to the plan and credit the fee to the laboratory."""
    plan = db.get("sampling_plans", order["sampling_plan_id"])
    if plan is not None:
        refresh_plan_ledger(plan)
        bump("sampling_plans", plan)
    lab = laboratory or db.get("laboratories", order["laboratory_id"])
    if lab is not None:
        lab["credited_fee_cents_total"] += order["invoice_total_cents"]
        bump("laboratories", lab)
    return plan, lab


# --------------------------------------------------------------------------
# Cascade 1: accreditation suspension
# --------------------------------------------------------------------------

def cascade_accreditation_suspension(accreditation):
    laboratory = db.get("laboratories", accreditation["laboratory_id"])
    method = accreditation["test_method_code"]
    affected_orders = []
    for order in db.all_rows("test_orders"):
        if order["laboratory_id"] != accreditation["laboratory_id"]:
            continue
        if order["order_state"] not in ("SCHEDULED", "IN_TESTING"):
            continue
        rule = db.get("applicable_rules", order["rule_id"])
        if rule is None or rule["test_method_code"] != method:
            continue
        affected_orders.append(order)

    touched_plans = {}
    lab_touched = False
    for order in affected_orders:
        order["order_state"] = "INVALIDATED"
        bump("test_orders", order)
        plan = db.get("sampling_plans", order["sampling_plan_id"])
        if plan is not None:
            touched_plans[plan["id"]] = plan
        if laboratory is not None:
            laboratory["credited_fee_cents_total"] += order["invoice_total_cents"]
            lab_touched = True

    touched_products = {}
    for plan in touched_plans.values():
        refresh_plan_ledger(plan)
        if plan["plan_state"] == "ACTIVE":
            plan["plan_state"] = "RESAMPLE_DUE"
            plan["resample_trigger"] = "RELIANCE_VOID"
            product = db.get("products", plan["product_id"])
            if product is not None:
                resize_plan(plan, product)
                touched_products[product["id"]] = product
        bump("sampling_plans", plan)

    if lab_touched:
        bump("laboratories", laboratory)

    for product in touched_products.values():
        recompute_product_derived(product)
        product["compliance_posture"] = "RESTRICTED"
        bump("products", product)

    return affected_orders


# --------------------------------------------------------------------------
# Cascade 2: failed test stop-distribution
# --------------------------------------------------------------------------

def cascade_failed_test(order, product, actor_user_id):
    """Hops one to four of PRD section 3.6's failing-report cascade."""
    # Hop 1
    if order["is_retest"]:
        case = None
        if order["retest_case_id"] is not None:
            candidate = db.get("noncompliance_cases", order["retest_case_id"])
            if (
                candidate is not None
                and candidate["active_retest_order_id"] == order["id"]
                and candidate["case_state"] == "RETEST_ORDERED"
            ):
                case = candidate
        if case is not None:
            case["case_state"] = "RETEST_FAILED"
            case["active_retest_order_id"] = None
            bump("noncompliance_cases", case)
    else:
        case = db.insert(
            "noncompliance_cases",
            {
                "product_id": product["id"],
                "triggering_test_order_id": order["id"],
                "failed_rule_id": order["rule_id"],
                "case_state": "OPEN",
                "retest_round_count": 0,
                "active_retest_order_id": None,
                "scope_variant": "BATCH_SCOPED",
                "scope_units": 0,
                "corrective_action_ref": None,
                "corrective_action_revision": 0,
                "opened_by_user_id": actor_user_id,
                "closed_by_user_id": None,
            },
        )

    # Hop 2
    if order["rule_id"] in product["required_rule_ids"] and product[
        "certification_state"
    ] in ("CERTIFIED", "EVIDENCE_COMPLETE"):
        product["certification_state"] = "SUSPENDED"

    # Hop 3
    withdrawn_ids = []
    for certificate in db.find("certificates", product_id=product["id"]):
        if certificate["issuance_status"] == "ISSUED":
            certificate["issuance_status"] = "WITHDRAWN"
            bump("certificates", certificate)
            withdrawn_ids.append(certificate["id"])

    # Hop 4
    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["certificate_id"] in withdrawn_ids and batch["distribution_state"] == "RELEASED":
            batch["distribution_state"] = "STOP_DISTRIBUTION"
            bump("production_batches", batch)

    recompute_distribution(product)
    recompute_product_derived(product)
    product["compliance_posture"] = "SUSPENDED"
    bump("products", product)
    return product


# --------------------------------------------------------------------------
# Cascade 3: material change resample
# --------------------------------------------------------------------------

def cascade_material_change(product, part, change_kind):
    voided_any = False
    if part is not None:
        previous = part["reliance_status"]
        part["last_material_change_at"] = clock.now()
        if previous in ("VALID", "PENDING"):
            part["reliance_status"] = "SUPERSEDED"
        bump("component_parts", part)
        if previous == "VALID":
            for cert in db.find("component_part_certificates", component_part_id=part["id"]):
                if cert["reliance_state"] != "RELIED_UPON":
                    continue
                cert["reliance_state"] = "RELIANCE_VOID"
                bump("component_part_certificates", cert)
                voided_any = True
                supplier = db.get("suppliers", cert["supplier_id"])
                if supplier is not None:
                    supplier["certificates_issued_count"] -= 1
                    bump("suppliers", supplier)

    trigger = "RELIANCE_VOID" if voided_any else "MATERIAL_CHANGE"
    for plan in db.find("sampling_plans", product_id=product["id"]):
        if plan["plan_state"] != "ACTIVE":
            continue
        plan["plan_state"] = "RESAMPLE_DUE"
        plan["resample_trigger"] = trigger
        resize_plan(plan, product)
        bump("sampling_plans", plan)

    recompute_product_derived(product)
    product["compliance_posture"] = "RESTRICTED"
    return product


# --------------------------------------------------------------------------
# Cascade 4: noncompliance closure
# --------------------------------------------------------------------------

def cascade_case_closure(case, product, actor_user_id):
    case["case_state"] = "CLOSED"
    case["closed_by_user_id"] = actor_user_id
    bump("noncompliance_cases", case)

    for batch in db.find("production_batches", product_id=product["id"]):
        if batch["distribution_state"] == "STOP_DISTRIBUTION":
            batch["distribution_state"] = "HELD"
            bump("production_batches", batch)

    others_open = [
        c
        for c in db.find("noncompliance_cases", product_id=product["id"])
        if c["id"] != case["id"]
        and c["case_state"] not in ("CLOSED", "ESCALATED_RECALL")
    ]
    if product["certification_state"] == "REMEDIATION" and not others_open:
        product["certification_state"] = "EVIDENCE_COMPLETE"

    recompute_distribution(product)
    recompute_product_derived(product)
    bump("products", product)
    return product
