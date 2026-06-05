"""Entity CRUD, computed fields, RBAC denials, optimistic concurrency, consistency.

Translates corner queue B sections: entities, rbac, cross_cutting_complexity_layers,
consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_taxpayer_headers, make_preparer_headers, build_user_headers,
    create_taxpayer_payload, create_tax_return_payload,
    create_income_document_payload, create_dependent_payload,
    efile_payload, create_amended_return_payload,
)
from test_helpers import fixtures as FIX
from test_helpers import setup_computed_return, setup_filed_return


def _new_taxpayer(api, **tp_overrides):
    resp = api.create_taxpayer(create_taxpayer_payload(**tp_overrides),
                               make_taxpayer_headers("bootstrap"))
    return validate_success(resp, 201)


# =====================================================================
# Corner B / entities
# =====================================================================

def test_create_taxreturn_returns_201_with_defaults(api):
    """PRD §3.1: "The caller may also set `deduction_method`, which is either `STANDARD`
    or `ITEMIZED` and defaults to `STANDARD`."
    PRD §3.1: "A newly created return begins life in `DRAFT` status with `version` 1,
    and all of its computed money fields — `total_income_cents`, `agi_cents`,
    `taxable_income_cents`, `tax_before_credits_cents`, `total_credits_cents`,
    `tax_after_credits_cents`, `total_payments_cents`, and `balance_due_cents` — start
    at 0, with `computed_at` null until the first successful computation."

    Design: Corner/entities/create_taxreturn_returns_201_with_defaults
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    resp = api.create_tax_return(
        create_tax_return_payload(tp["id"], tax_year=2025, filing_status="SINGLE"), h)
    ret = validate_success(resp, 201)
    assert ret["status"] == "DRAFT"
    assert ret["deduction_method"] == "STANDARD"
    assert ret["version"] == 1


def test_get_taxreturn_returns_stored_entity(api):
    """PRD §3.1: "A return is opened against a taxpayer by supplying that taxpayer's
    `taxpayer_id`, the `tax_year` (an integer that must be at least 2020), and the
    `filing_status` for this particular return."

    Design: Corner/entities/get_taxreturn_returns_stored_entity
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    created = validate_success(api.create_tax_return(
        create_tax_return_payload(tp["id"], tax_year=2025, filing_status="SINGLE"), h), 201)
    fetched = validate_success(api.get_tax_return(created["id"], h), 200)
    assert fetched["tax_year"] == 2025
    assert fetched["taxpayer_id"] == tp["id"]


def test_list_taxreturns_paginated_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_taxreturns_paginated_envelope
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    validate_success(api.create_tax_return(
        create_tax_return_payload(tp["id"], tax_year=2025, filing_status="SINGLE"), h), 201)
    resp = api.list_tax_returns(h, params={"taxpayer_id": tp["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


def test_get_taxreturn_nonexistent_returns_not_found(api):
    """PRD §2.6: "A path that names a `TaxReturn`, `EFilingSubmission`, or
    `AmendedReturn` id that does not exist is rejected with `ERR_RETURN_NOT_FOUND` (HTTP
    404)."

    Design: Corner/entities/get_taxreturn_nonexistent_returns_not_found
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    resp = api.get_tax_return("00000000-0000-4000-8000-000000000000", h)
    validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND.value)


def test_create_taxreturn_missing_required_field_invalid(api):
    """PRD §2.9: "Then request-body well-formedness — required fields present, enum
    values in range, and money fields satisfying their declared sign and bound
    constraints (`ERR_INVALID_REQUEST`, HTTP 422)."
    PRD §3.1: "A return is opened against a taxpayer by supplying that taxpayer's
    `taxpayer_id`, the `tax_year` (an integer that must be at least 2020), and the
    `filing_status` for this particular return."

    Design: Corner/entities/create_taxreturn_missing_required_field_invalid_request
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    resp = api.create_tax_return(
        {"taxpayer_id": tp["id"], "filing_status": "SINGLE"}, h)  # tax_year omitted
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_income_document_negative_amount_invalid(api):
    """PRD §3.2: "The principal money box, `box_amount_cents`, holds W-2 box-1 wages,
    1099-NEC nonemployee compensation, 1099-INT interest, or 1099-DIV ordinary
    dividends, and must be at least 0."
    PRD §2.9: "money fields satisfying their declared sign and bound constraints
    (`ERR_INVALID_REQUEST`, HTTP 422)."

    Design: Corner/entities/create_income_document_negative_amount_invalid_request
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return()
    h = make_taxpayer_headers(taxpayer["id"])
    resp = api.create_income_document(
        tax_return["id"],
        {"doc_type": "W2", "payer_name": "Acme", "box_amount_cents": -100}, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_taxreturn_invalid_enum_filing_status(api):
    """PRD §2.9: "Then request-body well-formedness — required fields present, enum
    values in range, and money fields satisfying their declared sign and bound
    constraints (`ERR_INVALID_REQUEST`, HTTP 422)."
    PRD §3.1: "a default `filing_status` that is one of `SINGLE`, `MARRIED_JOINT`,
    `MARRIED_SEPARATE`, or `HEAD_OF_HOUSEHOLD`."

    Design: Corner/entities/create_taxreturn_invalid_enum_filing_status
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    resp = api.create_tax_return(
        {"taxpayer_id": tp["id"], "tax_year": 2025, "filing_status": "WIDOW_PENGUIN"}, h)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_computed_fields_default_zero_on_create(api):
    """PRD §3.1: "all of its computed money fields — `total_income_cents`, `agi_cents`,
    `taxable_income_cents`, `tax_before_credits_cents`, `total_credits_cents`,
    `tax_after_credits_cents`, `total_payments_cents`, and `balance_due_cents` — start
    at 0, with `computed_at` null until the first successful computation."

    Design: Corner/entities/computed_fields_ignored_on_input
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = validate_success(api.create_tax_return(
        create_tax_return_payload(tp["id"], tax_year=2025, filing_status="SINGLE"), h), 201)
    assert ret["balance_due_cents"] == 0
    assert ret["agi_cents"] == 0


def test_dependent_qualifies_ctc_computed_on_compute(api):
    """PRD §3.2: "Each dependent also carries a computed `qualifies_ctc` flag, defaulting
    to false, set true exactly when the dependent's `age_years` is less than 17 at year
    end; this flag drives the per-child count for the Child Tax Credit."

    Design: Corner/entities/dependent_qualifies_ctc_computed_on_compute
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(box_amount_cents=5_000_000,
                                                               federal_withholding_cents=0)
    h = make_taxpayer_headers(taxpayer["id"])
    dep = validate_success(api.create_dependent(
        tax_return["id"], create_dependent_payload(full_name="Kid", age_years=10), h), 201)
    validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    deps = validate_success(api.list_dependents(tax_return["id"], h), 200)
    fetched = next(d for d in deps if d["id"] == dep["id"])
    assert fetched["qualifies_ctc"] is True


def test_create_taxreturn_unknown_taxpayer_fk_not_found(api):
    """PRD §2.6: "when a request body names a foreign-key target — a `taxpayer_id`, a
    `return_id`, or an `original_return_id` — that does not resolve to an existing
    entity, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_taxreturn_unknown_taxpayer_fk_not_found
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    resp = api.create_tax_return(
        create_tax_return_payload("11111111-1111-4111-8111-111111111111",
                                  tax_year=2025, filing_status="SINGLE"), h)
    validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND.value)


# =====================================================================
# Corner B / rbac
# =====================================================================

def test_preparer_cannot_efile_forbidden_role(api):
    """PRD §3.6: "an action reserved to the `Taxpayer` role; a `Preparer` attempting it
    is denied with `ERR_FORBIDDEN_ROLE`."

    Design: Corner/rbac/preparer_cannot_efile_forbidden_role
    """
    # Build return as Preparer acting on the taxpayer (allowed for build/compute).
    tp = _new_taxpayer(api, filing_status="SINGLE")
    ph = make_preparer_headers(tp["id"])
    ret = validate_success(api.create_tax_return(
        create_tax_return_payload(tp["id"], tax_year=2025, filing_status="SINGLE"), ph), 201)
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_000,
                                                  federal_withholding_cents=900_000), ph), 201)
    computed = validate_success(api.compute_tax_return(ret["id"], ph), 200)
    resp = api.efile_tax_return(ret["id"], efile_payload(computed["version"]), ph)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_irsgateway_cannot_compute_forbidden_role(api):
    """PRD §2.1: "The gateway's sole mutating capability is recording an accept or reject
    acknowledgement on a transmitted submission."
    PRD §2.1: "When an authenticated caller attempts an operation their role is not
    permitted to perform, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/irsgateway_cannot_compute_forbidden_role
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(federal_withholding_cents=0)
    resp = api.compute_tax_return(
        tax_return["id"], build_user_headers("irs-op-1", "IrsGateway"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_taxpayer_cannot_act_on_other_taxpayers_return(api):
    """PRD §2.1: "For any operation that targets a specific return or amendment owned by
    a taxpayer, if the acting `Taxpayer` or `Preparer` `X-User-ID` does not match the
    owning taxpayer, the request is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/rbac/taxpayer_cannot_act_on_other_taxpayers_return
    """
    owner, tax_return, _doc = FIX.setup_draft_return_with_w2(federal_withholding_cents=0)
    other = _new_taxpayer(api, filing_status="SINGLE")
    resp = api.compute_tax_return(tax_return["id"], make_taxpayer_headers(other["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401). The system recognizes exactly three roles: `Taxpayer`, `Preparer`, and
    `IrsGateway`."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    taxpayer, tax_return = FIX.setup_taxpayer_and_return()
    resp = api.get_tax_return(tax_return["id"], build_user_headers(taxpayer["id"], "Ghost"))
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =====================================================================
# Corner B / cross_cutting_complexity_layers
# =====================================================================

def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "an integer `version` that begins at 1 on creation and increments by one
    with each subsequent mutation."
    PRD §2.7: "Every operation that mutates a return — whether a direct edit, a compute,
    an e-file transmission, an acknowledgement-driven transition, or an amendment cascade
    — refreshes the return's `updated_at` and increments its `version`."

    Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_every_mutation
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(federal_withholding_cents=0)
    h = make_taxpayer_headers(taxpayer["id"])
    # create (v1) -> add income doc (v2) -> compute (v3)
    computed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    assert computed["version"] == 3


def test_amend_create_correct_version_succeeds(api):
    """PRD §2.8: "The create request must carry `expected_return_version` equal to the
    current `version` of the original return being amended."
    PRD §3.7: "A created amendment begins in `DRAFT` status, and its creation increments
    the original return's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/amend_create_correct_version_succeeds
    """
    taxpayer, filed, _ef = setup_filed_return()
    h = make_taxpayer_headers(taxpayer["id"])
    current = validate_success(api.get_tax_return(filed["id"], h), 200)
    resp = api.create_amended_return(
        create_amended_return_payload(
            filed["id"], taxpayer["id"], current["version"],
            corrected_balance_due_cents=40_000,
            correction_period_start="2025-01-01T00:00:00Z",
            correction_period_end="2025-06-30T00:00:00Z"),
        h)
    amendment = validate_success(resp, 201)
    assert amendment["status"] == "DRAFT"


def test_amend_create_stale_version_rejected(api):
    """PRD §2.8: "If another amendment has already advanced the original return's
    `version` (for instance by moving it toward `AMENDED` and superseding the prior
    corrected figures), the creator's view is stale and the create is rejected with
    `ERR_STALE_RETURN_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/amend_create_stale_version_rejected
    """
    taxpayer, filed, _ef = setup_filed_return()
    h = make_taxpayer_headers(taxpayer["id"])
    current = validate_success(api.get_tax_return(filed["id"], h), 200)
    resp = api.create_amended_return(
        create_amended_return_payload(
            filed["id"], taxpayer["id"], current["version"] - 1,
            corrected_balance_due_cents=40_000,
            correction_period_start="2025-01-01T00:00:00Z",
            correction_period_end="2025-06-30T00:00:00Z"),
        h)
    validate_error(resp, ApiErrorId.ERR_STALE_RETURN_VERSION.value)


# =====================================================================
# Corner B / consistency_model
# =====================================================================

def test_compute_changes_visible_in_same_response(api):
    """PRD §3.5: "A compute on a `DRAFT` return advances it to `READY`; a compute on a
    return already in `READY` recomputes in place and leaves it `READY`."
    PRD §3.5: "`balance_due_cents` is `tax_after_credits_cents` minus
    `total_payments_cents`: a positive figure is owed by the filer, a negative figure is
    a refund owed to the filer."

    Design: Corner/consistency_model/compute_changes_visible_same_response
    """
    taxpayer, tax_return, _doc = FIX.setup_draft_return_with_w2(
        box_amount_cents=8_000_000, federal_withholding_cents=900_000)
    h = make_taxpayer_headers(taxpayer["id"])
    computed = validate_success(api.compute_tax_return(tax_return["id"], h), 200)
    assert computed["balance_due_cents"] == 35_300
    assert computed["status"] == "READY"
