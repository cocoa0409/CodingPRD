"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient 2xx validator) internally so that a broken setup
step surfaces as a clear "setup failed" error rather than a confusing assertion.

Identity threading: GeneticCounselor and LabTechnician are entity-backed. Every
ownership-gated call routes through make_counselor_headers(counselor_id) /
make_lab_headers(lab_id) with the real entity id.

The test harness restarts the server (empty DB) before every test, so each helper
builds its entire precondition chain from scratch using only PRD endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_family_payload, create_counselor_payload, create_lab_payload,
    create_case_payload, create_pedigree_member_payload, create_consent_payload,
    create_session_payload, create_order_payload, create_result_payload,
    create_invitation_payload, create_claim_payload,
)
from .test_users import (
    TEST_USERS, make_counselor_headers, make_lab_headers,
)

ADMIN = TEST_USERS["admin_headers"]
BILLING = TEST_USERS["billing_headers"]


# --------------------------------------------------------------------------- #
# Logical clock
# --------------------------------------------------------------------------- #
def set_clock(iso: str):
    """Set the server logical clock (ProgramAdmin only)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, ADMIN))


# --------------------------------------------------------------------------- #
# Reference-resource creators (ProgramAdmin)
# --------------------------------------------------------------------------- #
def create_family(budget=100000, name="Test Kindred"):
    return get_success_data(api_client.create_family(
        create_family_payload(family_name=name, outreach_budget_cents=budget), ADMIN))


def create_counselor(name="Test Counselor", **overrides):
    return get_success_data(api_client.create_counselor(
        create_counselor_payload(full_name=name, **overrides), ADMIN))


def create_lab(capacity=5, turnaround=14, name="Test Lab"):
    return get_success_data(api_client.create_lab(
        create_lab_payload(lab_name=name, max_concurrent_capacity=capacity,
                           turnaround_days=turnaround), ADMIN))


# --------------------------------------------------------------------------- #
# Clinical-thread builders (GeneticCounselor / LabTechnician)
# --------------------------------------------------------------------------- #
def create_case(family_id, counselor_id, **overrides):
    hdr = make_counselor_headers(counselor_id)
    return get_success_data(api_client.create_case(
        create_case_payload(family_id, counselor_id, **overrides), hdr))


def add_member(case_id, counselor_id, **overrides):
    hdr = make_counselor_headers(counselor_id)
    return get_success_data(api_client.create_pedigree_member(
        create_pedigree_member_payload(case_id, **overrides), hdr))


def assess_risk(case_id, counselor_id):
    return get_success_data(api_client.assess_risk(case_id, make_counselor_headers(counselor_id)))


def create_signed_testing_consent(case_id, counselor_id):
    hdr = make_counselor_headers(counselor_id)
    consent = get_success_data(api_client.create_consent(
        create_consent_payload(case_id, "TESTING"), hdr))
    get_success_data(api_client.sign_consent(consent["id"], hdr))
    return consent


def create_order(case_id, lab_id, counselor_id, **overrides):
    hdr = make_counselor_headers(counselor_id)
    return get_success_data(api_client.create_order(
        create_order_payload(case_id, lab_id, **overrides), hdr))


def submit_order(order_id, counselor_id):
    return get_success_data(api_client.submit_order(order_id, make_counselor_headers(counselor_id)))


def enter_result(order_id, lab_id, classification="PATHOGENIC", **overrides):
    hdr = make_lab_headers(lab_id)
    return get_success_data(api_client.create_result(
        create_result_payload(order_id, classification=classification, **overrides), hdr))


def release_result(result_id, lab_id):
    return get_success_data(api_client.release_result(result_id, make_lab_headers(lab_id)))


def disclose_result(result_id, counselor_id):
    return get_success_data(api_client.disclose_result(result_id, make_counselor_headers(counselor_id)))


def create_invitation(family_id, proband_case_id, member_id, counselor_id, **overrides):
    hdr = make_counselor_headers(counselor_id)
    return get_success_data(api_client.create_invitation(
        create_invitation_payload(family_id, proband_case_id, member_id, **overrides), hdr))


def send_invitation(invitation_id, counselor_id):
    return get_success_data(api_client.send_invitation(invitation_id, make_counselor_headers(counselor_id)))


# --------------------------------------------------------------------------- #
# Tier: risk-assessed proband
# --------------------------------------------------------------------------- #
def setup_risk_assessed_case(members, ancestry="EUROPEAN", familial_variant_known=False,
                             budget=100000, covered_sessions=3, capacity=5):
    """Family + counselor + lab + proband case with the given pedigree members, then
    assess-risk. `members` is a list of pedigree-member override dicts. Returns a dict
    of the created entities plus the list of created member records.

    Reaches CounselingCase.clinical_status == RISK_ASSESSED.
    """
    fam = create_family(budget)
    gc = create_counselor()
    lab = create_lab(capacity=capacity)
    case = create_case(fam["id"], gc["id"], ancestry=ancestry,
                       familial_variant_known=familial_variant_known,
                       covered_sessions=covered_sessions)
    created_members = [add_member(case["id"], gc["id"], **m) for m in members]
    case = assess_risk(case["id"], gc["id"])
    return {
        "family": fam, "counselor": gc, "lab": lab, "case": case,
        "members": created_members,
        "family_id": fam["id"], "counselor_id": gc["id"], "lab_id": lab["id"],
        "case_id": case["id"],
    }


# --------------------------------------------------------------------------- #
# Tier: disclosed proband (full clinical chain through disclosure cascade)
# --------------------------------------------------------------------------- #
def setup_disclosed_case(members, classification="PATHOGENIC",
                         familial_variant_known=False, ancestry="EUROPEAN",
                         budget=100000, covered_sessions=3, capacity=5,
                         order_overrides=None, result_overrides=None):
    """Full chain: family/counselor/lab -> case -> pedigree -> assess-risk ->
    signed TESTING consent -> order -> submit -> enter result (classification) ->
    release -> disclose. Returns a dict with every created entity (re-fetched case
    reflects the post-disclosure state).
    """
    ctx = setup_risk_assessed_case(members, ancestry=ancestry,
                                   familial_variant_known=familial_variant_known,
                                   budget=budget, covered_sessions=covered_sessions,
                                   capacity=capacity)
    gc_id, lab_id, case_id = ctx["counselor_id"], ctx["lab_id"], ctx["case_id"]
    consent = create_signed_testing_consent(case_id, gc_id)
    order = create_order(case_id, lab_id, gc_id, **(order_overrides or {}))
    submit_order(order["id"], gc_id)
    result = enter_result(order["id"], lab_id, classification=classification,
                          **(result_overrides or {}))
    release_result(result["id"], lab_id)
    disclose_result(result["id"], gc_id)
    ctx["case"] = get_success_data(api_client.get_case(case_id, make_counselor_headers(gc_id)))
    ctx["consent"] = consent
    ctx["order"] = order
    ctx["result"] = result
    ctx["order_id"] = order["id"]
    ctx["result_id"] = result["id"]
    ctx["consent_id"] = consent["id"]
    return ctx


def setup_proband_disclosed_actionable(budget=100000, capacity=5):
    """Proband disclosed with a PATHOGENIC (actionable) result, plus one unaffected
    first-degree SIBLING who is the at-risk cascade candidate. Returns the disclosed
    context with `at_risk_member` / `at_risk_member_id` set to that sibling.

    The affected driver of prior risk is a first-degree PARENT (onset 40).
    """
    members = [
        {"relationship": "SIBLING", "degree": 1, "affected": False, "age_of_onset": None},
        {"relationship": "PARENT", "degree": 1, "affected": True, "age_of_onset": 40},
    ]
    ctx = setup_disclosed_case(members, classification="PATHOGENIC", budget=budget,
                               capacity=capacity)
    ctx["at_risk_member"] = ctx["members"][0]
    ctx["at_risk_member_id"] = ctx["members"][0]["id"]
    return ctx


def setup_sent_invitation(budget=100000, contact_method="EMAIL", degree=1,
                          relationship="SIBLING", expires_at="2026-07-01T00:00:00Z"):
    """Proband disclosed PATHOGENIC; one at-risk relative invitation created and SENT.
    Returns the disclosed context plus `invitation` / `invitation_id` (status SENT).
    """
    ctx = setup_proband_disclosed_actionable(budget=budget)
    inv = create_invitation(ctx["family_id"], ctx["case_id"], ctx["at_risk_member_id"],
                            ctx["counselor_id"], relationship=relationship, degree=degree,
                            contact_method=contact_method, expires_at=expires_at)
    inv = send_invitation(inv["id"], ctx["counselor_id"])
    ctx["invitation"] = inv
    ctx["invitation_id"] = inv["id"]
    return ctx


# --------------------------------------------------------------------------- #
# Tier: billing thread
# --------------------------------------------------------------------------- #
def setup_case_with_order(budget=100000, capacity=5, order_overrides=None,
                          covered_sessions=3, assess=False, members=None):
    """Family/counselor/lab + case + a DRAFT test order (no submit). Optionally
    assess-risk first (requires `members`). Returns dict with case + order.
    """
    fam = create_family(budget)
    gc = create_counselor()
    lab = create_lab(capacity=capacity)
    case = create_case(fam["id"], gc["id"], covered_sessions=covered_sessions)
    if assess:
        for m in (members or [{"relationship": "SIBLING", "degree": 1,
                               "affected": True, "age_of_onset": 60}]):
            add_member(case["id"], gc["id"], **m)
        case = assess_risk(case["id"], gc["id"])
    order = create_order(case["id"], lab["id"], gc["id"], **(order_overrides or {}))
    return {
        "family": fam, "counselor": gc, "lab": lab, "case": case, "order": order,
        "family_id": fam["id"], "counselor_id": gc["id"], "lab_id": lab["id"],
        "case_id": case["id"], "order_id": order["id"],
    }


def create_claim(case_id, order_id, **overrides):
    return get_success_data(api_client.create_claim(
        create_claim_payload(case_id, order_id, **overrides), BILLING))


def setup_claim_authorized(coverage_pct=0.8, estimated_allowed_rate=0.7, line_items=None,
                           billed_cents=300000):
    """Case + order + insurance claim walked to AUTHORIZED. Returns dict with claim.

    Order is left DRAFT (a claim does not require a submitted order per PRD 3.8).
    """
    ctx = setup_case_with_order()
    li = line_items if line_items is not None else [{"cpt": "81162", "billed_cents": billed_cents}]
    claim = create_claim(ctx["case_id"], ctx["order_id"], coverage_pct=coverage_pct,
                         estimated_allowed_rate=estimated_allowed_rate, line_items=li)
    claim = get_success_data(api_client.authorize_claim(claim["id"], BILLING))
    ctx["claim"] = claim
    ctx["claim_id"] = claim["id"]
    return ctx


def setup_claim_submitted(coverage_pct=0.8, estimated_allowed_rate=0.7, line_items=None,
                          billed_cents=300000):
    """Case + order + claim walked to SUBMITTED (ready to adjudicate)."""
    ctx = setup_claim_authorized(coverage_pct=coverage_pct,
                                 estimated_allowed_rate=estimated_allowed_rate,
                                 line_items=line_items, billed_cents=billed_cents)
    claim = get_success_data(api_client.submit_claim(ctx["claim_id"], BILLING))
    ctx["claim"] = claim
    return ctx
