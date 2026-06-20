"""Auth/role validation precedence, the RBAC denial matrix, the not-found error
family, and list/pagination/filter envelope claims.

Translates queue B sections `validations`, `errors`, `rbac`, and the listing
instances of `endpoints`.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    TEST_USERS, build_user_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
MOLECULAR = TEST_USERS["molecular_headers"]
BILLING = TEST_USERS["billing_headers"]
COUNSELOR = TEST_USERS["counselor_headers"]


# --------------------------------------------------------------------------- #
# Validation precedence (queue B: validations)
# --------------------------------------------------------------------------- #
def test_missing_user_context_returns_401(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized role names, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/validations/missing_user_context_returns_401
    """
    FX.set_clock()
    resp = api.list_genes({})
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value, 401)


def test_unknown_role_returns_401(api):
    """PRD §2.1: "if `X-User-Role` is not one of the recognized role names, the
    request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 401)."

    Design: Corner/validations/unknown_role_returns_401
    """
    FX.set_clock()
    resp = api.list_genes(build_user_headers("someone", "Janitor"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value, 401)


def test_auth_beats_existence_unknown_role_on_missing_order(api):
    """PRD §2.8: "The order is: first, user-context validity
    (`ERR_MISSING_OR_INVALID_USER_CONTEXT`); then role authorization
    (`ERR_FORBIDDEN_ROLE`); then existence of every path identifier, left to
    right."

    Design: Corner/validations/auth_beats_existence_unknown_role_on_missing_order
    """
    FX.set_clock()
    resp = api.get_test_order("00000000-0000-4000-8000-0000000000ff",
                              build_user_headers("w", "Wizard"))
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT.value, 401)


def test_forbidden_role_beats_existence_on_missing_order(api):
    """PRD §2.8: "then role authorization (`ERR_FORBIDDEN_ROLE`); then existence of
    every path identifier, left to right (the resource-specific not-found
    errors)."

    Design: Corner/validations/forbidden_role_beats_existence_on_missing_order
    """
    FX.set_clock()
    # BillingSpecialist is not permitted to cancel (LabIntake exclusive).
    resp = api.cancel_order("00000000-0000-4000-8000-0000000000ee", {"cancel_reason": "x"}, BILLING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_existence_beats_state_signout_missing_report(api):
    """PRD §2.8: "then existence of every path identifier, left to right ... then
    ... whether the target resource is in a state from which the requested
    transition is defined."
    PRD §2.5: "an unknown order id yields `ERR_ORDER_NOT_FOUND` before the nested
    specimen is even consulted."

    Design: Corner/validations/existence_beats_state_signout_missing_report
    """
    ctx = FX.setup_classified(classification="BENIGN", insurance_payer="SELF_PAY",
                              gene_symbols=("GVAL1",), name="VAL1")
    resp = api.sign_out_report(ctx["order"]["id"], "00000000-0000-4000-8000-0000000000dd",
                               DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_REPORT_NOT_FOUND.value, 404)


def test_invalid_classification_value_rejected(api):
    """PRD §3.5: "Classifying a variant assigns it a `classification` value, which
    must be one of the five ACMG tiers ... and never `UNCLASSIFIED` or
    `RECLASSIFIED`; a value outside the five tiers is rejected with
    `ERR_INVALID_CLASSIFICATION` (HTTP 422)."

    Design: Corner/validations/invalid_classification_value_returns_invalid_classification
    """
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GVAL2",), name="VAL2")
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.72A>T")
    resp = api.classify_variant(ctx["order"]["id"], var["id"],
                                F.classify_payload("UNCLASSIFIED"), MOLECULAR)
    validate_error(resp, ApiErrorId.ERR_INVALID_CLASSIFICATION.value, 422)
    reread = validate_success(api.get_variant(var["id"], MOLECULAR), 200)
    assert reread["classification"] == "UNCLASSIFIED"


# --------------------------------------------------------------------------- #
# RBAC denial matrix (queue B: rbac)
# --------------------------------------------------------------------------- #
def test_rbac_intake_cannot_create_gene(api):
    """PRD §4: "| POST | `/lab/genes` | Create a gene catalog entry | LabDirector |"
    PRD §2.1: "if a caller's role is not authorized for the requested operation,
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_labintake_cannot_create_gene
    """
    FX.set_clock()
    resp = api.create_gene({"symbol": "GRB1"}, INTAKE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_rbac_accessioning_cannot_publish_panel(api):
    """PRD §4: "| POST | `/lab/panels/{panelId}/publish` | Publish a DRAFT panel |
    LabDirector |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_accessioningtech_cannot_publish_panel
    """
    FX.set_clock()
    panel = get_success_data(api.create_panel(F.create_panel_payload(name="RB2"), DIRECTOR))
    resp = api.publish_panel(panel["id"], ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    reread = validate_success(api.get_panel(panel["id"], DIRECTOR), 200)
    assert reread["status"] == "DRAFT"


def test_rbac_molecular_cannot_place_order(api):
    """PRD §4: "| POST | `/lab/test-orders` | Place a test order | LabIntake |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_molecular_tech_cannot_place_order
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(gene_symbols=("GRB3",), name="RB3")
    provider = FX.create_provider()
    resp = api.create_test_order(
        F.create_test_order_payload(panel["id"], provider["id"], patient_mrn="MRN-RB3"),
        MOLECULAR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_rbac_intake_cannot_register_specimen(api):
    """PRD §4: "| POST | `/lab/test-orders/{orderId}/specimens` | Register a received
    specimen | AccessioningTech |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_labintake_cannot_register_specimen
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", gene_symbols=("GRB4",), name="RB4")
    resp = api.create_specimen(
        ctx["order"]["id"],
        F.create_specimen_payload(specimen_type="BLOOD", quantity_ng=80), INTAKE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_rbac_intake_cannot_classify_variant(api):
    """PRD §4: "| POST | `/lab/test-orders/{orderId}/variants/{variantId}/classify` |
    Classify or reclassify a variant | MolecularTechnologist |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_labintake_cannot_classify_variant
    """
    ctx = FX.setup_sequencing(insurance_payer="SELF_PAY", gene_symbols=("GRB5",), name="RB5")
    var = FX.add_variant(ctx["order"]["id"], ctx["genes"][0]["id"], hgvs="c.80A>T")
    resp = api.classify_variant(ctx["order"]["id"], var["id"],
                                F.classify_payload("BENIGN"), INTAKE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    reread = validate_success(api.get_variant(var["id"], MOLECULAR), 200)
    assert reread["classification"] == "UNCLASSIFIED"


def test_rbac_molecular_cannot_sign_out_report(api):
    """PRD §4: "| POST | `/lab/test-orders/{orderId}/reports/{reportId}/sign-out` |
    Sign out a DRAFT report | LabDirector |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_molecular_tech_cannot_sign_out_report
    """
    ctx = FX.setup_draft_report(classification="BENIGN", insurance_payer="SELF_PAY",
                                classifier_user_id="tech-1", gene_symbols=("GRB6",), name="RB6")
    resp = api.sign_out_report(ctx["order"]["id"], ctx["report"]["id"], MOLECULAR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    reread = validate_success(api.get_report(ctx["report"]["id"], DIRECTOR), 200)
    assert reread["status"] == "DRAFT"


def test_rbac_director_cannot_record_auth_decision(api):
    """PRD §4: "| POST | `/lab/test-orders/{orderId}/billing/auth-decision` | Record a
    prior-auth decision | BillingSpecialist |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_labdirector_cannot_record_auth_decision
    """
    ctx = FX.setup_requisitioned(insurance_payer="COMMERCIAL", gene_symbols=("GRB7",), name="RB7")
    resp = api.auth_decision(ctx["order"]["id"],
                             F.auth_decision_payload("APPROVED", 20000), DIRECTOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_rbac_billing_cannot_schedule_referral(api):
    """PRD §4: "| POST | `/lab/test-orders/{orderId}/referrals/{referralId}/schedule` |
    Schedule a requested referral | GeneticCounselor |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_billing_specialist_cannot_schedule_referral
    """
    FX.set_clock()
    gc = FX.create_counselor("GC RB8")
    ctx = FX.setup_ordered(gene_symbols=("GRB8",), name="RB8")
    ref = FX.request_referral(ctx["order"]["id"], gc["id"])
    resp = api.schedule_referral(ctx["order"]["id"], ref["id"],
                                 F.schedule_referral_payload("2026-06-25T10:00:00.000Z",
                                                             "2026-06-25T11:00:00.000Z"),
                                 BILLING)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)
    reread = validate_success(api.get_referral(ref["id"], DIRECTOR), 200)
    assert reread["status"] == "REQUESTED"


def test_rbac_counselor_cannot_set_clock(api):
    """PRD §4: "| POST | `/lab/_clock/set_current_utc` | Set the deterministic lab
    clock | LabDirector |"
    PRD §2.1: "the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/rbac_genetic_counselor_cannot_set_clock
    """
    FX.set_clock()
    resp = api.set_clock("2027-01-01T00:00:00.000Z", COUNSELOR)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


def test_rbac_shared_get_allowed_for_billing_specialist(api):
    """PRD §2.1: "All read (GET) endpoints are available to all six roles."

    Design: Corner/rbac/rbac_shared_get_allowed_for_billing_specialist
    """
    FX.set_clock()
    FX.create_gene("GRB9")
    resp = api.list_genes(BILLING)
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1


# --------------------------------------------------------------------------- #
# Not-found error family (queue B: errors)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("getter,bad_id,error_id", [
    ("get_test_order", "00000000-0000-4000-8000-0000000000a1", ApiErrorId.ERR_ORDER_NOT_FOUND),
    ("get_panel", "00000000-0000-4000-8000-0000000000a2", ApiErrorId.ERR_PANEL_NOT_FOUND),
    ("get_provider", "00000000-0000-4000-8000-0000000000a3", ApiErrorId.ERR_PROVIDER_NOT_FOUND),
    ("get_specimen", "00000000-0000-4000-8000-0000000000a4", ApiErrorId.ERR_SPECIMEN_NOT_FOUND),
    ("get_variant", "00000000-0000-4000-8000-0000000000a5", ApiErrorId.ERR_VARIANT_NOT_FOUND),
    ("get_report", "00000000-0000-4000-8000-0000000000a6", ApiErrorId.ERR_REPORT_NOT_FOUND),
    ("get_consent", "00000000-0000-4000-8000-0000000000a7", ApiErrorId.ERR_CONSENT_NOT_FOUND),
    ("get_requisition", "00000000-0000-4000-8000-0000000000a8", ApiErrorId.ERR_REQUISITION_NOT_FOUND),
    ("get_referral", "00000000-0000-4000-8000-0000000000a9", ApiErrorId.ERR_REFERRAL_NOT_FOUND),
    ("get_panel_gene", "00000000-0000-4000-8000-0000000000aa", ApiErrorId.ERR_PANEL_GENE_NOT_FOUND),
    ("get_sequencer", "00000000-0000-4000-8000-0000000000ab", ApiErrorId.ERR_SEQUENCER_NOT_FOUND),
    ("get_run", "00000000-0000-4000-8000-0000000000ac", ApiErrorId.ERR_RUN_NOT_FOUND),
    ("get_counselor", "00000000-0000-4000-8000-0000000000ad", ApiErrorId.ERR_COUNSELOR_NOT_FOUND),
])
def test_get_unknown_resource_returns_specific_not_found(api, getter, bad_id, error_id):
    """PRD §2.5: "The not-found errors are resource-specific: `ERR_ORDER_NOT_FOUND`,
    `ERR_PANEL_NOT_FOUND`, `ERR_GENE_NOT_FOUND`, `ERR_PROVIDER_NOT_FOUND`,
    `ERR_REQUISITION_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`,
    `ERR_VARIANT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_REFERRAL_NOT_FOUND`,
    `ERR_PANEL_GENE_NOT_FOUND`, `ERR_SEQUENCER_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, and
    `ERR_COUNSELOR_NOT_FOUND`."

    Design: Corner/errors/err_order_not_found_on_get_unknown_order
    Design: Corner/errors/err_panel_not_found_on_get_unknown_panel
    Design: Corner/errors/err_provider_not_found_on_get_unknown_provider
    Design: Corner/errors/err_specimen_not_found_on_get_unknown_specimen
    Design: Corner/errors/err_variant_not_found_on_get_unknown_variant
    Design: Corner/errors/err_report_not_found_on_get_unknown_report
    Design: Corner/errors/err_consent_not_found_on_get_unknown_consent
    Design: Corner/errors/err_requisition_not_found_on_get_unknown_requisition
    Design: Corner/errors/err_referral_not_found_on_get_unknown_referral
    Design: Corner/errors/err_panel_gene_not_found_on_get_unknown_panel_gene
    Design: Corner/errors/err_sequencer_not_found_on_get_unknown_sequencer
    Design: Corner/errors/err_run_not_found_on_get_unknown_run
    Design: Corner/errors/err_counselor_not_found_on_get_unknown_counselor
    """
    FX.set_clock()
    resp = getattr(api, getter)(bad_id, DIRECTOR)
    validate_error(resp, error_id.value, 404)


# --------------------------------------------------------------------------- #
# Listing / pagination / filtering (queue B: endpoints)
# --------------------------------------------------------------------------- #
def test_list_genes_pagination_envelope(api):
    """PRD §2.3: "The `limit` parameter caps how many items are returned ... Every
    list response carries the pagination fields `limit`, `offset`, `total_count`,
    and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_genes_pagination_envelope_fields
    """
    FX.set_clock()
    FX.create_gene("GLIST1")
    FX.create_gene("GLIST2")
    FX.create_gene("GLIST3")
    resp = api.list_genes(INTAKE, params={"limit": 2, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(data) == 2


def test_list_test_orders_filter_by_pipeline_status(api):
    """PRD §2.3: "Unless a specific endpoint states otherwise, list results are
    ordered by the resource's creation timestamp (`created_at`) in ascending
    order."
    PRD §3.2: "Submission moves the requisition from `PENDING` to `SUBMITTED` and
    advances the order from `ORDERED` to `REQUISITIONED`."

    Design: Corner/endpoints/list_test_orders_filter_by_pipeline_status
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", gene_symbols=("GLIST4",), name="LIST4")
    order2 = FX.place_order(ctx["panel"]["id"], ctx["provider"]["id"], patient_mrn="MRN-L4B")
    resp = api.list_test_orders(INTAKE, params={"pipeline_status": "REQUISITIONED"})
    data, meta = validate_paginated(resp)
    ids = [o["id"] for o in data]
    assert ctx["order"]["id"] in ids
    assert order2["id"] not in ids


def test_list_panel_genes_filter_by_status(api):
    """PRD §3.1: "The panel's `gene_count` is a derived figure equal to the number of
    `PanelGene` rows for that panel whose `status` is `INCLUDED`."

    Design: Corner/endpoints/list_panel_genes_filter_by_status_excludes_removed
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(gene_symbols=("GLIST5A", "GLIST5B"), name="LIST5")
    resp = api.list_panel_genes(DIRECTOR, params={"panel_id": panel["id"], "status": "INCLUDED"})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2


def test_list_specimens_filter_by_test_order(api):
    """PRD §2.5: "a specimen lives beneath its order."
    PRD §2.3: "Every list response carries the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` inside the `meta` object of the envelope."

    Design: Corner/endpoints/list_specimens_filtered_by_test_order_reverse_reach
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", gene_symbols=("GLIST7",), name="LIST7")
    spec = FX.add_specimen(ctx["order"]["id"])
    resp = api.list_specimens(ACCESSIONING, params={"test_order_id": ctx["order"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1
    assert spec["id"] in [s["id"] for s in data]


def test_get_billing_reverse_reach_for_order(api):
    """PRD §3.2: "As a side effect of placement, the server also creates the order's
    `Billing` record in `OPEN` status."

    Design: Corner/endpoints/get_billing_reverse_reach_for_order
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(gene_symbols=("GLIST8",), name="LIST8")
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"], patient_mrn="MRN-L8")
    resp = api.list_order_billing(order["id"], BILLING)
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["status"] == "OPEN"
