"""Composite setup helpers: multi-step scenario builders used by the suite.

Every helper builds preconditions from scratch via PRD-declared endpoints and
returns plain dicts (validated leniently with get_success_data, so a broken
setup surfaces as a clear setup error rather than a confusing assertion).
"""
from types import SimpleNamespace as _SN

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_adjustment_payload,
    create_compliance_filing_payload,
    create_customer_class_payload,
    create_data_request_payload,
    create_intervenor_payload,
    create_rate_base_item_payload,
    create_rate_case_payload,
    create_regulatory_asset_payload,
    create_settlement_proposal_payload,
    create_tariff_rate_payload,
    create_test_year_entry_payload,
    COM_CLASS,
    RB2,
    T_COM_2027,
)
from .test_users import (
    TEST_USERS,
    UF_ALICE,
    UF_BOB,
    make_intervenor_rep_headers,
    make_utility_filer_headers,
)

UF = TEST_USERS["utility_filer_alice"]
STAFF = TEST_USERS["commission_staff"]
ALJ = TEST_USERS["alj"]


# ─── Atomic builders ─────────────────────────────────────────────────────────

def create_case(**overrides):
    """POST /rate-cases; returns the DRAFT case."""
    return get_success_data(api_client.create_rate_case(create_rate_case_payload(**overrides), UF))


def get_case(case_id):
    return get_success_data(api_client.get_rate_case(case_id, UF))


def add_entry(case_id, account_code="900", category="O_AND_M", booked=1000000000):
    return get_success_data(api_client.create_test_year_entry(
        create_test_year_entry_payload(
            case_id, account_code=account_code, category=category,
            booked_amount_cents=booked),
        UF))


def add_adjustment(case_id, entry_id, amount=50000000, reason="Annualize pension cost",
                   proposer_headers=None):
    return get_success_data(api_client.create_adjustment(
        create_adjustment_payload(case_id, entry_id, amount_cents=amount, reason=reason),
        proposer_headers or make_utility_filer_headers(UF_ALICE)))


def verify_adjustment(adjustment_id, verifier_headers=None):
    return get_success_data(api_client.verify_adjustment(
        adjustment_id, verifier_headers or make_utility_filer_headers(UF_BOB)))


def submit_entry(entry_id):
    return get_success_data(api_client.submit_entry(entry_id, UF))


def lock_entry(entry_id):
    return get_success_data(api_client.lock_entry(entry_id, UF))


def submit_and_lock_entry(entry_id):
    submit_entry(entry_id)
    return lock_entry(entry_id)


def add_rate_base_item(case_id, submit=True, **overrides):
    item = get_success_data(api_client.create_rate_base_item(
        create_rate_base_item_payload(case_id, **overrides), UF))
    if submit:
        item = get_success_data(api_client.submit_rate_base_item(item["id"], UF))
    return item


def add_class(case_id, **overrides):
    return get_success_data(api_client.create_customer_class(
        create_customer_class_payload(case_id, **overrides), UF))


def add_res_class(case_id, **overrides):
    return add_class(case_id, **overrides)


def add_com_class(case_id, **overrides):
    ov = {k: v for k, v in COM_CLASS.items() if k != "present_tiers"}
    ov["present_tiers"] = [dict(t) for t in COM_CLASS["present_tiers"]]
    ov.update(overrides)
    return add_class(case_id, **ov)


def add_regulatory_asset(case_id, **overrides):
    return get_success_data(api_client.create_regulatory_asset(
        create_regulatory_asset_payload(case_id, **overrides), UF))


def add_intervenor(case_id, party_name="AAA Industrial Group",
                   representative_name="Rae Torres", contact_email="rae@aaa.example"):
    return get_success_data(api_client.create_intervenor(
        create_intervenor_payload(
            case_id, party_name=party_name, representative_name=representative_name,
            contact_email=contact_email),
        TEST_USERS["intervenor_rep"]))


def add_data_request(case_id, intervenor_id=None, subject="Pension normalization",
                     body="Produce workpapers supporting adjustment A1", **extra):
    """Intervenor-issued when intervenor_id is given; staff-issued otherwise."""
    payload = create_data_request_payload(case_id, subject=subject, body=body, **extra)
    if intervenor_id is not None:
        payload["issuing_intervenor_id"] = intervenor_id
        return get_success_data(api_client.create_data_request(
            payload, make_intervenor_rep_headers(intervenor_id)))
    return get_success_data(api_client.create_data_request(payload, STAFF))


def add_tariff(case_id, class_id, **overrides):
    return get_success_data(api_client.create_tariff_rate(
        create_tariff_rate_payload(case_id, class_id, **overrides), UF))


def add_com_tariff_2027(case_id, com_class_id, **overrides):
    ov = {k: v for k, v in T_COM_2027.items() if k != "proposed_tiers"}
    ov["proposed_tiers"] = [dict(t) for t in T_COM_2027["proposed_tiers"]]
    ov.update(overrides)
    return add_tariff(case_id, com_class_id, **ov)


def get_adjustment(adjustment_id):
    return get_success_data(api_client.get_adjustment(adjustment_id, UF))


def get_entry(entry_id):
    return get_success_data(api_client.get_test_year_entry(entry_id, UF))


def get_asset(asset_id):
    return get_success_data(api_client.get_regulatory_asset(asset_id, UF))


def get_signatory(signatory_id):
    return get_success_data(api_client.get_settlement_signatory(signatory_id, UF))


def get_data_request(request_id):
    return get_success_data(api_client.get_data_request(request_id, UF))


def get_tariff(tariff_id):
    return get_success_data(api_client.get_tariff_rate(tariff_id, UF))


def get_class(class_id):
    return get_success_data(api_client.get_customer_class(class_id, UF))


def get_intervenor(intervenor_id):
    return get_success_data(api_client.get_intervenor(intervenor_id, UF))


# ─── Case phase walkers ──────────────────────────────────────────────────────

def file_case(case_id):
    return get_success_data(api_client.submit_filing(case_id, UF))


def accept_case(case_id):
    return get_success_data(api_client.deficiency_review(case_id, {"outcome": "ACCEPTED"}, STAFF))


def open_discovery(case_id):
    return get_success_data(api_client.open_discovery(case_id, STAFF))


def advance_to_hearing(case_id):
    return get_success_data(api_client.advance_to_hearing(case_id, ALJ))


def open_settlement_window(case_id):
    return get_success_data(api_client.open_settlement_window(case_id, ALJ))


def advance_to_order_pending(case_id):
    return get_success_data(api_client.advance_to_order_pending(case_id, ALJ))


def issue_order(case_id, tariff_ids, asset_ids):
    return get_success_data(api_client.issue_order(
        case_id, {"approved_tariff_ids": tariff_ids, "approved_asset_ids": asset_ids}, ALJ))


def implement_rates(case_id):
    return get_success_data(api_client.implement_rates(case_id, UF))


def begin_compliance_monitoring(case_id):
    return get_success_data(api_client.begin_compliance_monitoring(case_id, STAFF))


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, STAFF))


# ─── Settlement helpers ──────────────────────────────────────────────────────

def create_proposal(case_id, rr=1850000000, terms="Black-box settlement at 1.85B cents"):
    """OCC-guarded create: reads the current case version first."""
    version = get_case(case_id)["version"]
    return get_success_data(api_client.create_settlement_proposal(
        create_settlement_proposal_payload(
            case_id, version, proposed_revenue_requirement_cents=rr, terms=terms), UF), 201)


def get_proposal(proposal_id):
    return get_success_data(api_client.get_settlement_proposal(proposal_id, UF))


def circulate_proposal(proposal_id):
    return get_success_data(api_client.circulate_proposal(proposal_id, UF))


def list_signatories(proposal_id):
    data, _meta = validate_paginated(api_client.list_settlement_signatories(
        UF, params={"settlement_proposal_id": proposal_id}))
    return data


def sign_signatory(signatory_id, intervenor_id):
    return get_success_data(api_client.sign_signatory(
        signatory_id, make_intervenor_rep_headers(intervenor_id)))


def sign_all_signatories(signatories):
    out = []
    for s in signatories:
        out.append(sign_signatory(s["id"], s["intervenor_id"]))
    return out


def recommend_proposal(proposal_id):
    return get_success_data(api_client.recommend_proposal(proposal_id, ALJ))


# ─── Compliance helpers ──────────────────────────────────────────────────────

def create_filing(case_id, actual_revenue_by_class, period_label="RATE_YEAR_1"):
    version = get_case(case_id)["version"]
    return get_success_data(api_client.create_compliance_filing(
        create_compliance_filing_payload(
            case_id, version, period_label=period_label,
            actual_revenue_by_class=actual_revenue_by_class), UF), 201)


def get_filing(filing_id):
    return get_success_data(api_client.get_compliance_filing(filing_id, UF))


def submit_compliance_filing(filing_id):
    return get_success_data(api_client.submit_compliance_filing(filing_id, UF))


def review_compliance_filing(filing_id, outcome, **extra):
    payload = {"outcome": outcome}
    payload.update(extra)
    return get_success_data(api_client.review_compliance_filing(filing_id, payload, STAFF))


# ─── Composite scenario builders (canonical RR == 1,897,500,000) ─────────────

def setup_draft_case(with_adjustment=True, with_rate_base=True, classes=None,
                     with_asset=False, lock_entries=True, case_overrides=None):
    """Canonical DRAFT case: E1/E2/E3 (+A1 VERIFIED), RB1+RB2 SUBMITTED, optional
    customer classes (classes="both" | "res" | "com" | None) and the RA1 asset.
    Computed as-filed RR == 1,897,500,000 == the case's proposed RR."""
    case = create_case(**(case_overrides or {}))
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    e2 = add_entry(case["id"], "901", "DEPRECIATION", 400000000)
    e3 = add_entry(case["id"], "902", "TAXES", 200000000)
    a1 = None
    if with_adjustment:
        a1 = add_adjustment(case["id"], e1["id"], 50000000,
                            proposer_headers=make_utility_filer_headers(UF_ALICE))
        verify_adjustment(a1["id"], make_utility_filer_headers(UF_BOB))
    if lock_entries:
        for e in (e1, e2, e3):
            submit_and_lock_entry(e["id"])
    rb1 = rb2 = None
    if with_rate_base:
        rb1 = add_rate_base_item(case["id"])
        rb2 = add_rate_base_item(case["id"], **RB2)
    cls_res = cls_com = None
    if classes in ("both", "res"):
        cls_res = add_res_class(case["id"])
    if classes in ("both", "com"):
        cls_com = add_com_class(case["id"])
    ra1 = add_regulatory_asset(case["id"]) if with_asset else None
    return _SN(case=case, e1=e1, e2=e2, e3=e3, a1=a1, rb1=rb1, rb2=rb2,
               cls_res=cls_res, cls_com=cls_com, ra1=ra1)


def setup_filed_case(**kwargs):
    """Canonical case through submit-filing (A1 cascades to ACCEPTED)."""
    s = setup_draft_case(**kwargs)
    s.case = file_case(s.case["id"])
    return s


def setup_discovery_case(**kwargs):
    """Canonical case in DISCOVERY."""
    s = setup_filed_case(**kwargs)
    accept_case(s.case["id"])
    s.case = open_discovery(s.case["id"])
    return s


def setup_settlement_case(num_intervenors=2, **kwargs):
    """Canonical case in SETTLEMENT with intervenor parties registered."""
    s = setup_discovery_case(**kwargs)
    s.i1 = add_intervenor(s.case["id"])
    s.i2 = None
    if num_intervenors >= 2:
        s.i2 = add_intervenor(s.case["id"], "BBB Consumer Advocates", "Sam Cho",
                              "sam@bbb.example")
    advance_to_hearing(s.case["id"])
    s.case = open_settlement_window(s.case["id"])
    return s


def setup_circulated_proposal(num_intervenors=2, **kwargs):
    """Case in SETTLEMENT; SP1 created and circulated (signatories PENDING)."""
    s = setup_settlement_case(num_intervenors=num_intervenors, **kwargs)
    s.sp1 = create_proposal(s.case["id"])
    s.sp1 = circulate_proposal(s.sp1["id"])
    s.signatories = list_signatories(s.sp1["id"])
    return s


def setup_assented_case(num_intervenors=2, **kwargs):
    """SP1 circulated and fully signed -> ASSENTED."""
    s = setup_circulated_proposal(num_intervenors=num_intervenors, **kwargs)
    sign_all_signatories(s.signatories)
    s.sp1 = get_proposal(s.sp1["id"])
    return s


def setup_order_pending_case(num_intervenors=2, **kwargs):
    """SP1 RECOMMENDED; case in ORDER_PENDING."""
    s = setup_assented_case(num_intervenors=num_intervenors, **kwargs)
    recommend_proposal(s.sp1["id"])
    s.case = advance_to_order_pending(s.case["id"])
    return s


def setup_decided_case(tariff_ids=(), asset_ids=(), **kwargs):
    """Case in DECIDED after issue-order with the given approval lists."""
    s = setup_order_pending_case(**kwargs)
    s.case = issue_order(s.case["id"], list(tariff_ids), list(asset_ids))
    return s


def setup_rates_implemented_case(tariff_ids=(), asset_ids=(), **kwargs):
    s = setup_decided_case(tariff_ids=tariff_ids, asset_ids=asset_ids, **kwargs)
    s.case = implement_rates(s.case["id"])
    return s


def setup_compliance_case(tariff_ids=(), asset_ids=(), **kwargs):
    s = setup_rates_implemented_case(tariff_ids=tariff_ids, asset_ids=asset_ids, **kwargs)
    s.case = begin_compliance_monitoring(s.case["id"])
    return s


def setup_decided_with_tariffs_and_asset(num_intervenors=2, with_com_tariff=True,
                                         extra_com_tariff_2029=False,
                                         extra_res_tariff_2028=False,
                                         classes="both", with_asset=True,
                                         issue=True):
    """Full canonical chain: classes + RA1 created pre-filing, tariffs created
    during DISCOVERY, SP1 RECOMMENDED, case ORDER_PENDING; with issue=True the
    order approving the 2027 tariffs (and RA1) lands the case in DECIDED."""
    s = setup_discovery_case(classes=classes, with_asset=with_asset)
    s.t_res = add_tariff(s.case["id"], s.cls_res["id"]) if s.cls_res else None
    s.t_com = None
    if with_com_tariff and s.cls_com:
        s.t_com = add_com_tariff_2027(s.case["id"], s.cls_com["id"])
    s.t_x = None
    if extra_com_tariff_2029 and s.cls_com:
        s.t_x = add_tariff(
            s.case["id"], s.cls_com["id"],
            label="COM schedule 2029", proposed_customer_charge_cents=1500,
            proposed_tiers=[{"up_to_kwh": None, "rate_mills": 1050}],
            effective_start="2029-01-01T00:00:00Z",
            effective_end="2030-01-01T00:00:00Z")
    s.t_res_b = None
    if extra_res_tariff_2028 and s.cls_res:
        s.t_res_b = add_tariff(
            s.case["id"], s.cls_res["id"],
            label="RES 2028", proposed_customer_charge_cents=950,
            proposed_tiers=[
                {"up_to_kwh": 300, "rate_mills": 780},
                {"up_to_kwh": 600, "rate_mills": 980},
                {"up_to_kwh": None, "rate_mills": 1250},
            ],
            effective_start="2028-01-01T00:00:00Z",
            effective_end="2029-01-01T00:00:00Z")
    s.i1 = add_intervenor(s.case["id"])
    s.i2 = None
    if num_intervenors >= 2:
        s.i2 = add_intervenor(s.case["id"], "BBB Consumer Advocates", "Sam Cho",
                              "sam@bbb.example")
    advance_to_hearing(s.case["id"])
    s.case = open_settlement_window(s.case["id"])
    s.sp1 = create_proposal(s.case["id"])
    s.sp1 = circulate_proposal(s.sp1["id"])
    s.signatories = list_signatories(s.sp1["id"])
    sign_all_signatories(s.signatories)
    s.sp1 = get_proposal(s.sp1["id"])
    recommend_proposal(s.sp1["id"])
    s.case = advance_to_order_pending(s.case["id"])
    if issue:
        tariff_ids = [t["id"] for t in (s.t_res, s.t_com, s.t_res_b) if t]
        asset_ids = [s.ra1["id"]] if s.ra1 else []
        s.case = issue_order(s.case["id"], tariff_ids, asset_ids)
    return s


def setup_rates_implemented_with_asset(classes=None):
    """Zero-class (default) canonical case in RATES_IMPLEMENTED with RA1
    AMORTIZING and its four PENDING amortization entries (period order)."""
    s = setup_decided_with_tariffs_and_asset(
        num_intervenors=1, with_com_tariff=False, classes=classes, with_asset=True)
    s.case = implement_rates(s.case["id"])
    entries, _meta = validate_paginated(api_client.list_amortization_entries(
        UF, params={"regulatory_asset_id": s.ra1["id"], "status": "PENDING"}))
    s.pending_entries = entries
    return s


def setup_compliance_res_only():
    """RES-only canonical case in COMPLIANCE_MONITORING with the RES 2027
    tariff EFFECTIVE and authorized RR 1,850,000,000 (adopted settlement)."""
    s = setup_decided_with_tariffs_and_asset(
        num_intervenors=1, with_com_tariff=False, classes="res", with_asset=False)
    s.case = implement_rates(s.case["id"])
    s.case = begin_compliance_monitoring(s.case["id"])
    return s


def setup_compliance_both_classes():
    """RES+COM canonical case in COMPLIANCE_MONITORING; both 2027 tariffs
    EFFECTIVE; authorized RR 1,850,000,000."""
    s = setup_decided_with_tariffs_and_asset(
        num_intervenors=2, with_com_tariff=True, classes="both", with_asset=False)
    s.case = implement_rates(s.case["id"])
    s.case = begin_compliance_monitoring(s.case["id"])
    return s


# ─── Light fixture (single-entry case, proposed RR 1,180,000,000) ────────────

def setup_filed_case_light(proposed_rr=1180000000):
    """Single 1e9 O&M entry LOCKED + one SUBMITTED rate-base item (net 2.4e9);
    computed as-filed RR == 1,180,000,000 == proposed. Returns namespace."""
    case = create_case(proposed_revenue_requirement_cents=proposed_rr)
    e1 = add_entry(case["id"], "900", "O_AND_M", 1000000000)
    submit_and_lock_entry(e1["id"])
    rb1 = add_rate_base_item(case["id"])
    filed = file_case(case["id"])
    return _SN(case=filed, e1=e1, rb1=rb1)


def setup_discovery_case_light(**kwargs):
    s = setup_filed_case_light(**kwargs)
    accept_case(s.case["id"])
    s.case = open_discovery(s.case["id"])
    return s
