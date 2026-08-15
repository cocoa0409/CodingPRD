"""Authentication, role authorization, and entity-backed ownership (PRD §2.1, §2.6)."""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_plan_payload, create_claim_payload, create_prior_authorization_payload,
    make_plan, make_drug, make_pharmacy, make_member, make_formulary_entry,
    make_adjudication_scenario, make_pending_pa, make_audit, record_findings,
    create_paid_claim, get_claim, get_pa, get_audit,
    make_pharmacist_headers, make_member_headers,
    TEST_USERS,
)


def test_unauthenticated_missing_headers_rejected(api):
    """PRD §2.1: "A request with missing headers or an unrecognized role is rejected
    with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/unauthenticated_missing_headers_rejected
    """
    res = api.create_plan(
        create_plan_payload(name="P-NOAUTH", oop_max_cents=1),
        headers={},
    )
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)


def test_pharmacist_cannot_approve_pa(api, pharmacist_headers):
    """PRD §2.1: "A request whose role is not among the roles authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /prior-authorizations/{id}/approve is authorized for ClinicalReviewer.

    Design: Corner/rbac/pharmacist_cannot_approve_pa
    """
    plan = make_plan(name="P-RB1")
    drug = make_drug(ndc="00000-9034", name="Rolevex", unit_cost_cents=100,
                     max_daily_dose_units=10)
    pharmacy = make_pharmacy(ncpdp_id="NCPDP-RB1", name="Rx Role")
    member = make_member(plan["id"], external_ref="M-RB1", full_name="Pat Role")
    pa = make_pending_pa(member["id"], drug["id"], requested_quantity=30)

    res = api.approve_prior_authorization(
        pa["id"], {"approved_quantity": 30, "expires_at": "2026-12-31"},
        make_pharmacist_headers(pharmacy["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
    assert get_pa(pa["id"])["status"] == "PENDING"


def test_member_cannot_submit_claim(api, pbm_admin_headers):
    """PRD §2.1: "A request whose role is not among the roles authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /claims is authorized for Pharmacist.

    Design: Corner/rbac/member_cannot_submit_claim
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9035", "name": "Submitden", "unit_cost_cents": 100,
                        "max_daily_dose_units": 10},
        entry_overrides={"quantity_limit_per_fill": 30, "max_days_supply": 30},
    )
    member = scenario["member"]
    res = api.create_claim(
        create_claim_payload(member["id"], scenario["drug"]["id"],
                             fill_date="2026-03-01"),
        make_member_headers(member["id"]),
    )
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_pharmacist_cannot_reverse_other_pharmacys_claim(api):
    """PRD §2.1: "When `X-User-Role` is `Pharmacist`, `X-User-ID` is the `id` of the
    acting `Pharmacy`; ownership checks on any resource that references a pharmacy
    compare that resource's pharmacy foreign key to `X-User-ID`, and a mismatch is
    rejected with `ERR_PHARMACY_MISMATCH` (HTTP 403)."
    PRD §3.7: "Reversal is performed by the owning pharmacy's pharmacist — any other
    pharmacy is `ERR_PHARMACY_MISMATCH`"

    Design: Corner/rbac/pharmacist_cannot_reverse_other_pharmacys_claim
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9036", "name": "Ownerex", "unit_cost_cents": 100,
                        "max_daily_dose_units": 100},
    )
    other_pharmacy = make_pharmacy(ncpdp_id="NCPDP-RBB", name="Rx Owner B")
    claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date="2026-03-01")

    res = api.reverse_claim(
        claim["id"], {"reversal_reason": "not mine"},
        make_pharmacist_headers(other_pharmacy["id"]),
    )
    validate_error(res, "ERR_PHARMACY_MISMATCH", expected_status=403)
    assert get_claim(claim["id"], scenario["pharmacist_headers"])["status"] == "PAID"


def test_member_cannot_request_pa_for_other_member(api):
    """PRD §3.3: "A `Member` creates a **PriorAuthorization** naming themselves as
    `member_id` — any other value is `ERR_MEMBER_MISMATCH`"

    Design: Corner/rbac/member_cannot_request_pa_for_other_member
    """
    plan = make_plan(name="P-RB4")
    drug = make_drug(ndc="00000-9037", name="Selfserv", unit_cost_cents=100,
                     max_daily_dose_units=10)
    member_a = make_member(plan["id"], external_ref="M-RB4A", full_name="Pat A")
    member_b = make_member(plan["id"], external_ref="M-RB4B", full_name="Pat B")

    res = api.create_prior_authorization(
        create_prior_authorization_payload(member_b["id"], drug["id"],
                                           requested_quantity=30),
        make_member_headers(member_a["id"]),
    )
    validate_error(res, "ERR_MEMBER_MISMATCH", expected_status=403)


def test_auditor_cannot_dispute_audit(api, auditor_headers):
    """PRD §2.1: "A request whose role is not among the roles authorized for the target
    endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §4: POST /audits/{id}/dispute is authorized for Pharmacist.

    Design: Corner/rbac/auditor_cannot_dispute_audit
    """
    scenario = make_adjudication_scenario(
        drug_overrides={"ndc": "00000-9038", "name": "Disputen", "unit_cost_cents": 1000,
                        "max_daily_dose_units": 100},
        entry_overrides={"copay_flat_cents": 0},
        pharmacy_overrides={"auto_suspend_threshold_cents": 50000},
    )
    claim = create_paid_claim(scenario["member"]["id"], scenario["drug"]["id"],
                              scenario["pharmacy"]["id"], fill_date="2026-03-01")
    audit = make_audit(scenario["pharmacy"]["id"], extrapolation_method="CLAIM_LEVEL")
    record_findings(audit["id"], [{"claim_id": claim["id"], "clawback_cents": 500}])

    res = api.dispute_audit(audit["id"], {"dispute_reason": "auditor overreach"},
                            auditor_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
    assert get_audit(audit["id"])["status"] == "FINDINGS_RECORDED"


def test_member_cannot_read_other_member(api):
    """PRD §2.1: "When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting
    `Member`; a member requesting a prior authorization must pass their own `id` as the
    payload's `member_id`, and member reads of member or claim resources are checked
    against `X-User-ID`, with violations rejected as `ERR_MEMBER_MISMATCH` (HTTP 403)."
    PRD §3.2: "a `Member` caller reading a member record may read only their own, with
    anything else rejected as `ERR_MEMBER_MISMATCH`."

    Design: Corner/rbac/member_cannot_read_other_member
    """
    plan = make_plan(name="P-RB6")
    member_a = make_member(plan["id"], external_ref="M-RB6A", full_name="Pat A6")
    member_b = make_member(plan["id"], external_ref="M-RB6B", full_name="Pat B6")

    res = api.get_member(member_b["id"], make_member_headers(member_a["id"]))
    validate_error(res, "ERR_MEMBER_MISMATCH", expected_status=403)
    own = validate_success(
        api.get_member(member_a["id"], make_member_headers(member_a["id"])), 200
    )
    assert own["id"] == member_a["id"]
