"""Party setup, immutable attachments, reads, and FK-reverse listings.

Covers corner instances from sections entities, endpoints, and consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_patient, assert_immutable_attachment_shape,
    make_frontoffice_headers, make_biller_headers,
    create_patient_payload,
)
from test_helpers import fixtures as fx


def test_create_patient_defaults_active_zero_balance(api):
    """PRD §3.1: "A new patient begins with `status` of `ACTIVE` and a
    `balance_cents` of 0; both are computed thereafter and are never supplied by
    the client."
    PRD §2.4: an integer `version` that starts at 1.

    Design: Corner/entities/create_patient_defaults_active_zero_balance
    """
    resp = api.create_patient(
        create_patient_payload(full_name="Def Pat", date_of_birth="1990-02-02",
                               email="def@x.com"),
        make_frontoffice_headers())
    data = validate_success(resp, 201)
    assert_patient(data)
    assert data["status"] == "ACTIVE", f"expected ACTIVE, got {data['status']}"
    assert data["balance_cents"] == 0, f"expected 0, got {data['balance_cents']}"
    assert data["version"] == 1, f"expected version 1, got {data['version']}"


def test_attachment_is_immutable_no_version(api):
    """PRD §3.4: "Attachments are immutable once created and therefore carry no
    `updated_at` or `version`."

    Design: Corner/entities/attachment_is_immutable_no_version
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_procedure(api, cdt_code="D0220", description="PA xray",
                     category="BASIC", ucr_fee_cents=3500)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D0220", "billed_fee_cents": 3500}])
    resp = api.create_attachment(
        {"claim_id": claim["id"], "kind": "XRAY", "filename": "pa.png"},
        make_biller_headers())
    data = validate_success(resp, 201)
    assert "id" in data and "created_at" in data
    assert_immutable_attachment_shape(data)


def test_get_nonexistent_claim_returns_not_found(api):
    """PRD §2.6: "Every referenced resource must exist ... rejects the request
    with `ERR_NOT_FOUND` at the first identifier that does not resolve to an
    existing resource."

    Design: Corner/entities/get_nonexistent_claim_returns_not_found
    """
    resp = api.get_claim(NON_EXISTENT_UUID, make_biller_headers())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_claims_by_patient_fk_reverse(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object."
    PRD §4: GET `/claims` List or filter Claims.

    Design: Corner/endpoints/list_claims_by_patient_fk_reverse
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000)
    fx.new_procedure(api)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.list_claims(make_biller_headers(),
                           params={"patient_id": patient["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    ids = [c["id"] for c in data]
    assert claim["id"] in ids, f"claim {claim['id']} not in listing {ids}"
    assert "total_count" in meta and "has_more" in meta


def test_verifications_by_coverage_fk_reverse(api):
    """PRD §3.2: "A verification's `status` is `VERIFIED` while the clock is at
    or before `expires_at`."
    PRD §4: GET `/verifications` List or filter Verifications.

    Design: Corner/endpoints/verifications_by_coverage_fk_reverse
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    ver = fx.new_verification(api, cov)
    resp = api.list_verifications(make_frontoffice_headers(),
                                  params={"coverage_id": cov["id"]})
    data, meta = validate_paginated(resp)
    match = [v for v in data if v["id"] == ver["id"]]
    assert match, f"verification {ver['id']} not in listing"
    assert match[0]["status"] == "VERIFIED"


def test_immediate_visibility_of_estimate_on_submit(api):
    """PRD §3.5: "The line's benefit is the allowed amount minus its deductible
    bite, multiplied by the applicable percent, divided by 100, and rounded half
    up to whole cents."
    PRD §2.4: computations use the logical clock; the submit response returns the
    updated resource (§2.2).

    Design: Corner/consistency_model/immediate_visibility_of_estimate_on_submit
    """
    sc = fx.crown_scenario(api, plan_overrides={"annual_maximum_cents": 150000,
                                                "deductible_cents": 5000,
                                                "major_coinsurance_pct": 50})
    claim = fx.new_claim(api, sc["patient"]["id"], sc["coverage"]["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.submit_claim(claim["id"], make_biller_headers("biller_alice"))
    data = validate_success(resp, 200)
    assert data["estimated_insurance_cents"] == 57500, \
        f"expected 57500, got {data['estimated_insurance_cents']}"
