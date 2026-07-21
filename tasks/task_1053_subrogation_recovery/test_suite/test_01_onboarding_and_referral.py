"""Onboarding carriers/adverse parties and referring claims — creation, defaults,
required-field and existence validation, append-only documents, immediate reads."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_carrier_payload, create_claim_payload, create_document_payload,
    assess_liability_payload,
    assert_carrier, assert_claim, assert_claim_document,
    make_carrier_user_headers,
    create_carrier, create_adverse_party, refer_claim, suspend_carrier,
    setup_referred_claim,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
SPECIALIST = TEST_USERS["specialist_headers"]
READER = TEST_USERS["reader_headers"]


def test_carrier_create_returns_201_active_version_one(api):
    """PRD §4: "Operations that create a new resource return `201 Created`."
    PRD §3.1: "A newly created carrier begins in `status` `ACTIVE`."
    PRD §2.4: "an integer `version` that starts at 1 and increments by one on every
    mutation of the resource."

    Design: Corner/entities/carrier_create_returns_201_with_fields
    """
    resp = api.create_carrier(
        create_carrier_payload(name="Acme Mutual", naic_code="12345",
                               commission_rate_bps=2500, commission_basis="NET"),
        MANAGER,
    )
    data = validate_success(resp, 201)
    assert_carrier(data)
    assert data["status"] == "ACTIVE", f"new carrier must be ACTIVE, got {data['status']}"
    assert data["version"] == 1, f"new carrier version must be 1, got {data['version']}"
    assert data["commission_rate_bps"] == 2500


def test_carrier_commission_basis_defaults_to_net(api):
    """PRD §3.1: "When omitted, `commission_basis` defaults to `NET`, meaning
    commission is charged on recovery net of the deductible returned to the insured".

    Design: Corner/entities/carrier_commission_basis_defaults_net
    """
    resp = api.create_carrier(
        {"name": "Default Ins", "naic_code": "99999", "commission_rate_bps": 2000},
        MANAGER,
    )
    data = validate_success(resp, 201)
    assert data["commission_basis"] == "NET", (
        f"omitted commission_basis must default to NET, got {data['commission_basis']}"
    )


def test_claim_missing_paid_loss_rejected(api):
    """PRD §3.2: "Referral supplies the `carrier_id` of the referring carrier, the
    `adverse_party_id` of the party to recover against, the carrier's external
    `claim_reference`, the `loss_date`, and three monetary figures: `paid_loss_cents`
    (what the carrier paid its insured, excluding the deductible), `deductible_cents`
    (the insured's deductible, to be recovered on a make-whole priority), and
    `total_damages_cents` (the full claimed damages, against which liability is applied)."
    PRD §2.11: "(5) well-formedness of the request body — correct types, valid enum
    members, positive amounts where required, a `liability_pct` between 0 and 100
    inclusive, and `hearing_start` strictly before `hearing_end` (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/claim_create_missing_paid_loss_returns_invalid_request
    """
    carrier = create_carrier(api)
    ap = create_adverse_party(api)
    payload = create_claim_payload(carrier["id"], ap["id"], claim_reference="CLM-M")
    del payload["paid_loss_cents"]
    resp = api.create_claim(payload, make_carrier_user_headers(carrier["id"]))
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_claim_unknown_adverse_party_rejected(api):
    """PRD §2.7: "the server confirms each referenced resource exists in path order
    before validating request-body foreign keys, and the first identifier that does
    not resolve produces `ERR_NOT_FOUND`."

    Design: Corner/entities/claim_create_unknown_adverse_party_returns_not_found
    """
    carrier = create_carrier(api)
    payload = create_claim_payload(
        carrier["id"], "00000000-0000-4000-8000-000000000abc", claim_reference="CLM-NF",
    )
    resp = api.create_claim(payload, make_carrier_user_headers(carrier["id"]))
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_get_claim_nonexistent_returns_not_found(api):
    """PRD §2.11: "(3) existence of every referenced resource, validated left-to-right
    in the path and then for body foreign keys (`ERR_NOT_FOUND`)".

    Design: Corner/entities/get_claim_nonexistent_returns_not_found
    """
    resp = api.get_claim("00000000-0000-4000-8000-000000000000", READER)
    validate_error(resp, "ERR_NOT_FOUND", 404)


def test_claim_ledger_fields_default_zero_on_referral(api):
    """PRD §2.4: "the ledger fields maintained on a `Claim` — `final_recovered_cents`,
    `deductible_reimbursed_cents`, `carrier_recovered_cents`, and
    `accrued_commission_cents` — are computed properties that the server keeps current
    as payments clear and reverse".
    PRD §3.2: "On referral the claim is stamped with a system `referral_date` taken
    from the logical clock and enters `status` `REFERRED`."

    Design: Corner/entities/claim_ledger_fields_default_zero_on_referral
    """
    ctx = setup_referred_claim(api)
    claim = ctx["claim"]
    assert_claim(claim)
    assert claim["status"] == "REFERRED"
    assert claim["final_recovered_cents"] == 0
    assert claim["deductible_reimbursed_cents"] == 0
    assert claim["carrier_recovered_cents"] == 0
    assert claim["accrued_commission_cents"] == 0


def test_assess_liability_pct_above_100_rejected(api):
    """PRD §3.2: "The specialist supplies `liability_pct`, the assessed adverse-liability
    percentage, which must lie between 0 and 100 inclusive".
    PRD §2.11: "(5) well-formedness of the request body — correct types, valid enum
    members, positive amounts where required, a `liability_pct` between 0 and 100
    inclusive, and `hearing_start` strictly before `hearing_end` (`ERR_INVALID_REQUEST`)".

    Design: Corner/entities/assess_liability_pct_above_100_returns_invalid_request
    """
    ctx = setup_referred_claim(api)
    resp = api.assess_liability(ctx["claim"]["id"], assess_liability_payload(150), SPECIALIST)
    validate_error(resp, "ERR_INVALID_REQUEST", 400)


def test_claim_document_append_only_created_and_listed(api):
    """PRD §2.4: "A `ClaimDocument` is append-only evidence: it is immutable once
    created and therefore carries only `id` and `created_at`. It has no `updated_at`
    and no `version` field."

    Design: Corner/entities/claim_document_append_only_created
    """
    ctx = setup_referred_claim(api)
    claim_id = ctx["claim"]["id"]
    resp = api.add_document(
        claim_id, create_document_payload(doc_type="POLICE_REPORT", title="Report 1", uri="s3://x/1"),
        make_carrier_user_headers(ctx["carrier"]["id"]),
    )
    doc = validate_success(resp, 201)
    assert_claim_document(doc)
    data, meta = validate_paginated(api.list_documents(claim_id, READER))
    assert meta["total_count"] == 1
    assert any(d["id"] == doc["id"] for d in data), "created document must be listed under the claim"


def test_claim_readable_immediately_after_referral(api):
    """PRD §3.2: "Referral supplies the `carrier_id` of the referring carrier, the
    `adverse_party_id` of the party to recover against, the carrier's external
    `claim_reference`, the `loss_date`, and three monetary figures: `paid_loss_cents`
    (what the carrier paid its insured, excluding the deductible), `deductible_cents`
    (the insured's deductible, to be recovered on a make-whole priority), and
    `total_damages_cents` (the full claimed damages, against which liability is applied)."

    Design: Corner/consistency_model/immediate_consistency_claim_read_after_create
    """
    ctx = setup_referred_claim(api, claim_overrides={"paid_loss_cents": 2_500_000, "deductible_cents": 500_000})
    fetched = validate_success(api.get_claim(ctx["claim"]["id"], READER))
    assert fetched["paid_loss_cents"] == 2_500_000
    assert fetched["deductible_cents"] == 500_000


def test_refer_claim_to_suspended_carrier_rejected(api):
    """PRD §3.2: "A referral naming a carrier that is not `ACTIVE` is rejected with
    `ERR_CARRIER_SUSPENDED`."

    Design: Corner/errors/refer_claim_to_suspended_carrier_returns_error
    """
    carrier = create_carrier(api, name="Suspended Ins", naic_code="44444")
    suspend_carrier(api, carrier["id"])
    ap = create_adverse_party(api)
    payload = create_claim_payload(carrier["id"], ap["id"], claim_reference="CLM-CS")
    resp = api.create_claim(payload, make_carrier_user_headers(carrier["id"]))
    validate_error(resp, "ERR_CARRIER_SUSPENDED", 409)
