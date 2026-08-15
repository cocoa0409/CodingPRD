"""Composite setup helpers for the chargeback-representment test suite.

Every helper builds its preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before each test, so nothing is
carried over). Setup steps use the lenient get_success_data() validator so a
setup failure surfaces as a clear "Setup failed" error.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .factories import (
    create_chargeback_payload,
    create_evidence_item_payload,
    create_fee_assessment_payload,
    create_merchant_payload,
    create_prevention_alert_payload,
    create_program_enrollment_payload,
    create_reason_code_rule_payload,
    create_remediation_plan_payload,
    create_representment_payload,
    create_transaction_payload,
)
from .test_users import TEST_USERS, make_merchant_user_headers

OPS = TEST_USERS["acquirer_ops_headers"]
RISK = TEST_USERS["risk_officer_headers"]
FIN = TEST_USERS["finance_ops_headers"]


# --- Tier 1: single-entity creation helpers ---

def create_rule(api, **overrides):
    """Create a reason-code rule. Defaults: VISA 10.4 FRAUD, [RECEIPT],
    7 merchant days, 30 representment days, 2500-cent fee, open from 2026-01-01."""
    resp = api.create_reason_code_rule(create_reason_code_rule_payload(**overrides), OPS)
    return get_success_data(resp)


def create_merchant(api, **overrides):
    """Onboard a merchant (defaults: STANDARD tier, FIXED_TIER, 500 bps unless overridden)."""
    resp = api.create_merchant(create_merchant_payload(**overrides), OPS)
    return get_success_data(resp)


def get_merchant(api, merchant_id):
    return get_success_data(api.get_merchant(merchant_id, OPS))


def reserve_account_for(api, merchant_id):
    """Reverse-lookup of the merchant's 1:1 reserve account."""
    resp = api.list_reserve_accounts(RISK, params={"merchant_id": merchant_id})
    data, _meta = validate_paginated(resp)
    assert len(data) == 1, f"expected exactly one reserve account for {merchant_id}"
    return data[0]


def ledger_entries(api, reserve_account_id, limit=100):
    resp = api.list_ledger_entries(reserve_account_id, RISK, params={"limit": limit})
    data, _meta = validate_paginated(resp)
    return data


def set_clock(api, to_iso8601):
    """Set the logical clock (fires the alert/chargeback expiry sweeps)."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, OPS))


# --- Tier 2: transaction / chargeback ingest helpers ---

def ingest_sale(api, merchant_id, external_ref="T-1", amount_cents=10000,
                occurred_at="2026-07-10T00:00:00Z", network="VISA"):
    resp = api.create_transaction(
        create_transaction_payload(
            merchant_id=merchant_id,
            external_ref=external_ref,
            network=network,
            amount_cents=amount_cents,
            occurred_at=occurred_at,
        ),
        OPS,
    )
    return get_success_data(resp)


def ingest_sales_batch(api, merchant_id, prefix, count, amount_cents=10000,
                       occurred_at="2026-07-10T00:00:00Z", network="VISA"):
    """Batch-ingest `count` identical sales; refs are prefix-0001..prefix-count."""
    resp = api.create_transactions_batch(
        {
            "merchant_id": merchant_id,
            "network": network,
            "count": count,
            "amount_cents": amount_cents,
            "occurred_at": occurred_at,
            "external_ref_prefix": prefix,
        },
        OPS,
    )
    return get_success_data(resp)


def ingest_chargeback(api, merchant_id, external_ref, network_case_id,
                      amount_cents, reason_code="10.4"):
    resp = api.create_chargeback(
        create_chargeback_payload(
            merchant_id=merchant_id,
            transaction_external_ref=external_ref,
            network_case_id=network_case_id,
            reason_code=reason_code,
            amount_cents=amount_cents,
        ),
        OPS,
    )
    return get_success_data(resp)


def notify(api, chargeback_id):
    return get_success_data(api.notify_chargeback(chargeback_id, OPS))


def upload_evidence(api, chargeback_id, merchant_id, evidence_type="RECEIPT",
                    document_uri="s3://evidence/doc.pdf", as_ops=False):
    """Upload one DRAFT evidence item; MerchantUser identity threads the merchant id."""
    headers = OPS if as_ops else make_merchant_user_headers(merchant_id)
    resp = api.create_evidence_item(
        create_evidence_item_payload(
            chargeback_id=chargeback_id,
            evidence_type=evidence_type,
            document_uri=document_uri,
        ),
        headers,
    )
    return get_success_data(resp)


def chargeback_version(api, chargeback_id):
    return get_success_data(api.get_chargeback(chargeback_id, OPS))["version"]


def assemble_packet(api, chargeback_id, merchant_id, evidence_ids, as_ops=False):
    """Assemble a representment packet with the OCC token read fresh."""
    headers = OPS if as_ops else make_merchant_user_headers(merchant_id)
    version = chargeback_version(api, chargeback_id)
    resp = api.create_representment(
        create_representment_payload(
            chargeback_id=chargeback_id,
            evidence_item_ids=list(evidence_ids),
            expected_chargeback_version=version,
        ),
        headers,
    )
    return get_success_data(resp)


def submit_packet(api, representment_id, merchant_id, as_ops=False):
    headers = OPS if as_ops else make_merchant_user_headers(merchant_id)
    return get_success_data(api.submit_representment(representment_id, headers))


def post_outcome(api, representment_id, outcome, won_amount_cents=None):
    payload = {"outcome": outcome}
    if won_amount_cents is not None:
        payload["won_amount_cents"] = won_amount_cents
    return get_success_data(api.post_network_outcome(representment_id, payload, OPS))


# --- Tier 3: lifecycle shortcuts ---

def setup_case(api, required_types=("RECEIPT",), merchant_overrides=None,
               amount_cents=10000, occurred_at="2026-07-10T00:00:00Z",
               received_at=None, reason_code="10.4", rule_overrides=None):
    """Rule + merchant + one sale + one full-amount chargeback in RECEIVED.

    Returns dict(rule, merchant, txn, chargeback).
    """
    rule_kw = {"required_evidence_types": list(required_types)}
    if rule_overrides:
        rule_kw.update(rule_overrides)
    rule = create_rule(api, **rule_kw)
    merchant = create_merchant(api, **(merchant_overrides or {}))
    txn = ingest_sale(api, merchant["id"], "T-1", amount_cents, occurred_at,
                      network=rule["network"])
    if received_at is not None:
        set_clock(api, received_at)
    cb = ingest_chargeback(api, merchant["id"], "T-1", "NC-1", amount_cents,
                           reason_code=rule["reason_code"])
    return {"rule": rule, "merchant": merchant, "txn": txn, "chargeback": cb}


def setup_notified_case(api, required_types=("RECEIPT",), **kwargs):
    """setup_case + notify. Adds the notified chargeback under key 'chargeback'."""
    bundle = setup_case(api, required_types=required_types, **kwargs)
    bundle["chargeback"] = notify(api, bundle["chargeback"]["id"])
    return bundle


def setup_submitted_case(api, required_types=("RECEIPT",), **kwargs):
    """Notified case + complete evidence packet submitted (case REPRESENTED).

    Returns dict(rule, merchant, txn, chargeback, evidence, representment).
    """
    bundle = setup_notified_case(api, required_types=required_types, **kwargs)
    m_id = bundle["merchant"]["id"]
    cb_id = bundle["chargeback"]["id"]
    evidence = [
        upload_evidence(api, cb_id, m_id, et, f"s3://ev/{et.lower()}-{i}.pdf")
        for i, et in enumerate(required_types)
    ]
    rep = assemble_packet(api, cb_id, m_id, [e["id"] for e in evidence])
    rep = submit_packet(api, rep["id"], m_id)
    bundle["evidence"] = evidence
    bundle["representment"] = rep
    bundle["chargeback"] = get_success_data(api.get_chargeback(cb_id, OPS))
    return bundle


def setup_decided_case(api, outcome="WON", won_amount_cents=None,
                       required_types=("RECEIPT",), **kwargs):
    """Full pipeline through the network outcome. Returns the setup bundle."""
    bundle = setup_submitted_case(api, required_types=required_types, **kwargs)
    rep = post_outcome(api, bundle["representment"]["id"], outcome, won_amount_cents)
    bundle["representment"] = rep
    bundle["chargeback"] = get_success_data(
        api.get_chargeback(bundle["chargeback"]["id"], OPS)
    )
    return bundle


# --- Tier 4: monthly sweep / program helpers ---

def sweep(api, period_month, merchant_id=None):
    payload = {"period_month": period_month}
    if merchant_id is not None:
        payload["merchant_id"] = merchant_id
    return get_success_data(api.advance_month(payload, OPS))


def list_snapshots(api, merchant_id, params=None):
    resp = api.list_ratio_snapshots(merchant_id, OPS, params=params)
    data, _meta = validate_paginated(resp)
    return data


def list_enrollments(api, merchant_id=None):
    params = {"merchant_id": merchant_id} if merchant_id else None
    resp = api.list_program_enrollments(RISK, params=params)
    data, _meta = validate_paginated(resp)
    return data


def list_fees(api, **filters):
    resp = api.list_fee_assessments(FIN, params={k: v for k, v in filters.items() if v is not None})
    data, _meta = validate_paginated(resp)
    return data


def list_education(api, merchant_id):
    resp = api.list_education_assignments(merchant_id, RISK)
    data, _meta = validate_paginated(resp)
    return data


def run_over_threshold_month(api, merchant_id, month, prefix, sales=50,
                             chargebacks=5, sale_amount=10000, cb_amount=1000,
                             network="VISA", reason_code="10.4"):
    """Drive one over-threshold month: batch sales on the 10th, chargebacks
    received on the 15th, then the advance-month sweep. Returns sweep tallies."""
    ingest_sales_batch(api, merchant_id, prefix, sales, sale_amount,
                       occurred_at=f"{month}-10T00:00:00Z", network=network)
    set_clock(api, f"{month}-15T00:00:00Z")
    for i in range(1, chargebacks + 1):
        ingest_chargeback(api, merchant_id, f"{prefix}-{i:04d}", f"NC-{prefix}{i:02d}",
                          cb_amount, reason_code=reason_code)
    return sweep(api, month, merchant_id=merchant_id)


def run_clean_month(api, merchant_id, month, prefix, sales=100,
                    sale_amount=10000, network="VISA"):
    """Drive one under-threshold month: sales only, then sweep. Returns tallies."""
    ingest_sales_batch(api, merchant_id, prefix, sales, sale_amount,
                       occurred_at=f"{month}-10T00:00:00Z", network=network)
    return sweep(api, month, merchant_id=merchant_id)


# --- Tier 5: enrollment / remediation / exit helpers ---

def create_enrollment(api, merchant_id, network="VISA", program_code="VDMP_STANDARD",
                      enrolled_month="2026-05"):
    resp = api.create_program_enrollment(
        create_program_enrollment_payload(
            merchant_id=merchant_id,
            network=network,
            program_code=program_code,
            enrolled_month=enrolled_month,
        ),
        RISK,
    )
    return get_success_data(resp)


def create_plan(api, enrollment_id, merchant_id, root_cause_codes=("FRAUD_GAP",),
                corrective_actions=("deploy 3DS",)):
    resp = api.create_remediation_plan(
        create_remediation_plan_payload(
            enrollment_id=enrollment_id,
            root_cause_codes=list(root_cause_codes),
            corrective_actions=list(corrective_actions),
        ),
        make_merchant_user_headers(merchant_id),
    )
    return get_success_data(resp)


def submit_plan(api, plan_id, merchant_id):
    return get_success_data(
        api.submit_remediation_plan(plan_id, make_merchant_user_headers(merchant_id))
    )


def review_plan(api, plan_id, decision, decision_note=None):
    payload = {"decision": decision}
    if decision_note is not None:
        payload["decision_note"] = decision_note
    return get_success_data(api.review_remediation_plan(plan_id, payload, RISK))


def create_approved_plan(api, enrollment_id, merchant_id):
    """Draft -> submit -> APPROVE. Returns the APPROVED plan."""
    plan = create_plan(api, enrollment_id, merchant_id)
    submit_plan(api, plan["id"], merchant_id)
    return review_plan(api, plan["id"], "APPROVE", "ok")


def setup_exited_enrollment(api, enrolled_month="2026-05",
                            clean_months=("2026-06", "2026-07", "2026-08"),
                            exit_month="2026-08"):
    """Merchant + manual ACTIVE enrollment + APPROVED plan + three consecutive
    under-threshold POSTED snapshots, then a successful exit-review.

    Returns dict(merchant, enrollment_exited, plan).
    """
    merchant = create_merchant(api, reserve_rate_bps=0)
    m_id = merchant["id"]
    enrollment = create_enrollment(api, m_id, enrolled_month=enrolled_month)
    plan = create_approved_plan(api, enrollment["id"], m_id)
    for month in clean_months:
        run_clean_month(api, m_id, month, prefix=f"X{month[5:7]}")
    resp = api.exit_review_enrollment(enrollment["id"], {"exited_month": exit_month}, RISK)
    exited = get_success_data(resp)
    return {"merchant": merchant, "enrollment": exited, "plan": plan}


# --- Fees ---

def create_manual_fee(api, merchant_id, amount_cents=7500, assessed_by="fin-1"):
    """Manual ARBITRATION_FEE assessment by a FinanceOps user."""
    from .test_users import make_finance_ops_headers

    resp = api.create_fee_assessment(
        create_fee_assessment_payload(merchant_id=merchant_id, amount_cents=amount_cents),
        make_finance_ops_headers(assessed_by),
    )
    return get_success_data(resp)
