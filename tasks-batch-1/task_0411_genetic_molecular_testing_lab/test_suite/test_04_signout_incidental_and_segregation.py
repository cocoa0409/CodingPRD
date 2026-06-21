"""Sign-out gating and the incidental-findings policy: billing-cleared and
consent-signed cross-entity dependencies, segregation of duties, VUS-referral
gate, adult-vs-minor incidental disclosure, age boundary, and the
AUTH_APPROVED->PATIENT_PAY sign-out cascade.

Translates queue A dual_variant_calc/incidental_disclosure_adult_vs_minor_findings,
boundary_precision_check/incidental_minor_age_18_inclusive_boundary,
priority_pair_validation_conflict/signout_safety_beats_constraint,
cross_entity_state_dependency/{signout_depends_on_billing_cleared,
accession_depends_on_consent_signed}; plus queue B validations and cross_cutting
sign-out instances.
"""
from test_helpers import (
    api_client,
    validate_success, validate_error, get_success_data,
    TEST_USERS, make_headers,
)
from test_helpers import factories as F
from test_helpers import fixtures as FX
from test_helpers.api_errors import ApiErrorId

DIRECTOR = TEST_USERS["director_headers"]
INTAKE = TEST_USERS["intake_headers"]
ACCESSIONING = TEST_USERS["accessioning_headers"]
MOLECULAR = TEST_USERS["molecular_headers"]
BILLING = TEST_USERS["billing_headers"]


def _on_gene(panel):
    """Return the single INCLUDED gene id for a panel built by create_published_panel."""
    pgs = get_success_data(api_client.list_panel_panel_genes(panel["id"], DIRECTOR))
    return pgs[0]["gene_id"]


def _build_incidental_order(off_gene_symbol, classification, patient_dob, opt_in=True,
                            on_symbol="GONP", insurance_payer="SELF_PAY",
                            panel_name="IncP", list_price_cents=40000):
    """Build a DRAFT-report order with one off-panel ACMG incidental variant.
    Returns (order, report, off_gene, var). Stops at DRAFT report (not signed out)."""
    on_gene = FX.create_gene(on_symbol)
    off_gene = FX.create_gene(off_gene_symbol, is_acmg_reportable=True)
    panel = get_success_data(api_client.create_panel(
        F.create_panel_payload(name=panel_name, list_price_cents=list_price_cents,
                               requires_consent=False), DIRECTOR))
    get_success_data(api_client.add_panel_gene(panel["id"], F.add_panel_gene_payload(on_gene["id"]), DIRECTOR))
    panel = get_success_data(api_client.publish_panel(panel["id"], DIRECTOR))
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"], patient_dob=patient_dob)
    FX.add_requisition(order["id"], insurance_payer)
    FX.submit_requisition(order["id"])
    FX.add_signed_consent(order["id"], incidental_findings_opt_in=opt_in)
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api_client.start_sequencing(order["id"], ACCESSIONING))
    var = FX.add_variant(order["id"], off_gene["id"], hgvs="c.200G>A")
    FX.classify(order["id"], var["id"], classification, user_id="tech-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"])
    return order, report, off_gene, var


def test_signout_billing_not_cleared_when_auth_denied(api):
    """PRD §3.8: "3. **Billing cleared.** The order's `financial_status` must be one
    of `AUTH_APPROVED`, `PATIENT_PAY`, or `SETTLED`; otherwise the sign-out is
    rejected with `ERR_BILLING_NOT_CLEARED` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/signout_depends_on_billing_cleared
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(list_price_cents=100000, gene_symbols=("GD1",),
                                         name="PD1")
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"])
    FX.add_requisition(order["id"], "COMMERCIAL")
    FX.submit_requisition(order["id"])
    FX.auth_deny(order["id"])  # financial AUTH_DENIED — not cleared
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    var = FX.add_variant(order["id"], _on_gene(panel), hgvs="c.15A>T")
    FX.classify(order["id"], var["id"], "BENIGN", user_id="tech-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"])
    resp = api.sign_out_report(order["id"], report["id"], make_headers("director-1", "LabDirector"))
    validate_error(resp, ApiErrorId.ERR_BILLING_NOT_CLEARED.value, 402)
    reread = FX.get_order(order["id"])
    assert reread["pipeline_status"] == "CLASSIFIED"


def test_accession_blocked_when_consent_only_draft(api):
    """PRD §3.3: "When the ordered panel's `requires_consent` was true — that is,
    when the order's `report_required_consent` snapshot is true — a consent in
    `SIGNED` status must exist before a specimen can be accessioned; absent one,
    accessioning is rejected with `ERR_CONSENT_REQUIRED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/accession_depends_on_consent_signed
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", requires_consent=True,
                                 gene_symbols=("GE1",), name="PE1")
    # Create a DRAFT (unsigned) consent only.
    get_success_data(api.create_consent(
        ctx["order"]["id"], F.create_consent_payload(incidental_findings_opt_in=False), INTAKE))
    spec = FX.add_specimen(ctx["order"]["id"])
    resp = api.accession_specimen(ctx["order"]["id"], spec["id"], ACCESSIONING)
    validate_error(resp, ApiErrorId.ERR_CONSENT_REQUIRED.value, 409)
    spec_re = validate_success(api.get_specimen(spec["id"], ACCESSIONING), 200)
    assert spec_re["status"] == "RECEIVED"
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "REQUISITIONED"


def test_signout_segregation_of_duties_beats_vus(api):
    """PRD §3.8: "Its preconditions are evaluated in this order: ... 4. **Segregation
    of duties.** The signing director's `X-User-ID` must not equal the
    `classified_by_user_id` of any variant on the order ... A violation is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). 5. **VUS handling.** No variant on
    the order may carry classification `VUS` unless a counselor referral with
    `reason` `VUS_FOLLOWUP` exists ..."

    Design: Difficulty/priority_pair_validation_conflict/signout_safety_beats_constraint
    """
    # CLASSIFIED SELF_PAY order, one VUS variant, NO VUS_FOLLOWUP referral,
    # financial PATIENT_PAY; the SAME director-1 X-User-ID both classified and signs.
    FX.set_clock()
    panel, _ = FX.create_published_panel(gene_symbols=("GW",), name="PW")
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"])
    FX.add_requisition(order["id"], "SELF_PAY")
    FX.submit_requisition(order["id"])
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    gene_id = _on_gene(panel)
    var = FX.add_variant(order["id"], gene_id, hgvs="c.13A>T")
    # Classify as director-1 so the signer (director-1) collides with classifier.
    FX.classify(order["id"], var["id"], "VUS", user_id="director-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"], headers=make_headers("director-1", "LabDirector"))
    resp = api.sign_out_report(order["id"], report["id"], make_headers("director-1", "LabDirector"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


def test_vus_referral_required_blocks_signout(api):
    """PRD §3.8: "5. **VUS handling.** No variant on the order may carry
    classification `VUS` unless a counselor referral with `reason` `VUS_FOLLOWUP`
    exists for the order in `REQUESTED`, `SCHEDULED`, or `COMPLETED` status. A
    signed-out attempt with an open `VUS` and no such referral is rejected with
    `ERR_VUS_REFERRAL_REQUIRED` (HTTP 409)."

    Design: Corner/validations/vus_referral_required_blocks_signout
    """
    # signer differs from classifier so SoD passes; SELF_PAY so billing cleared.
    ctx = FX.setup_draft_report(classification="VUS", insurance_payer="SELF_PAY",
                                classifier_user_id="tech-1", gene_symbols=("GVAL3",), name="VAL3")
    resp = api.sign_out_report(ctx["order"]["id"], ctx["report"]["id"],
                               make_headers("director-1", "LabDirector"))
    validate_error(resp, ApiErrorId.ERR_VUS_REFERRAL_REQUIRED.value, 409)
    reread = validate_success(api.get_report(ctx["report"]["id"], DIRECTOR), 200)
    assert reread["status"] == "DRAFT"


def test_signout_clean_order_succeeds(api):
    """PRD §3.8: "the report's `status` moves from `DRAFT` to `SIGNED_OUT` and
    `signed_out_by_user_id` is set to the director's `X-User-ID`; the order's
    `pipeline_status` advances to `SIGNED_OUT`."

    Design: Corner/validations/signout_satisfies_all_gates_succeeds
    """
    ctx = FX.setup_draft_report(classification="BENIGN", insurance_payer="SELF_PAY",
                                classifier_user_id="tech-1", gene_symbols=("GVAL4",), name="VAL4")
    resp = api.sign_out_report(ctx["order"]["id"], ctx["report"]["id"],
                               make_headers("director-1", "LabDirector"))
    data = validate_success(resp, 200)
    assert data["status"] == "SIGNED_OUT"
    assert data["signed_out_by_user_id"] == "director-1"
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "SIGNED_OUT"


def test_signout_auth_approved_cascades_to_patient_pay(api):
    """PRD §3.8: "Finally, if the order's `financial_status` was `AUTH_APPROVED` at
    sign-out, the billing record advances from `AUTH_APPROVED` to `PATIENT_PAY`,
    the order's `financial_status` becomes `PATIENT_PAY`, and the patient's
    coinsurance becomes owed."

    Design: Corner/cross_cutting/signout_auth_approved_cascades_to_patient_pay
    """
    FX.set_clock()
    panel, _ = FX.create_published_panel(list_price_cents=200000, gene_symbols=("GCC5",),
                                         name="CC5")
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"])
    FX.add_requisition(order["id"], "COMMERCIAL")
    FX.submit_requisition(order["id"])
    FX.auth_approve(order["id"], 100000)
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    var = FX.add_variant(order["id"], _on_gene(panel), hgvs="c.92A>T")
    FX.classify(order["id"], var["id"], "BENIGN", user_id="tech-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"])
    resp = api.sign_out_report(order["id"], report["id"], make_headers("director-1", "LabDirector"))
    validate_success(resp, 200)
    order_after = FX.get_order(order["id"])
    billing = validate_success(api.list_order_billing(order["id"], BILLING), 200)[0]
    assert order_after["financial_status"] == "PATIENT_PAY"
    assert billing["status"] == "PATIENT_PAY"
    assert order_after["pipeline_status"] == "SIGNED_OUT"


# --------------------------------------------------------------------------- #
# Incidental-findings policy: adult vs minor + age boundary
# --------------------------------------------------------------------------- #
def test_incidental_disclosure_adult_vs_minor(api):
    """PRD §3.8: "An incidental finding is admitted if and only if the patient's
    `incidental_findings_opt_in` is true **and** either the patient is not a minor,
    or the patient is a minor but the gene is ACMG-reportable and the finding's
    classification is exactly `PATHOGENIC`. In plain terms: an adult who opted in
    receives all pathogenic and likely-pathogenic secondary findings; a minor who
    opted in receives only `PATHOGENIC` ACMG secondary findings, with
    likely-pathogenic incidentals withheld."
    PRD §3.8: "If any admitted reportable variant is incidental, the order's
    `has_reportable_incidental` is set to true."

    Design: Difficulty/dual_variant_calc/incidental_disclosure_adult_vs_minor_findings
    """
    # MINOR (age 16, dob 2010-06-19) with LIKELY_PATHOGENIC incidental -> withheld.
    FX.set_clock("2026-06-19T00:00:00.000Z")
    minor_order, minor_report, _, _ = _build_incidental_order(
        "TP53M", "LIKELY_PATHOGENIC", patient_dob="2010-06-19", opt_in=True,
        on_symbol="APCM", panel_name="MiniPanelM")
    FX.sign_out(minor_order["id"], minor_report["id"], director_user_id="director-1")
    minor_report_re = validate_success(api.get_report(minor_report["id"], DIRECTOR), 200)
    minor_order_re = FX.get_order(minor_order["id"])
    assert minor_report_re["incidental_disclosed"] is False
    assert minor_order_re["has_reportable_incidental"] is False

    # ADULT (age 18, dob 2008-06-01) with LIKELY_PATHOGENIC incidental -> disclosed.
    adult_order, adult_report, _, _ = _build_incidental_order(
        "TP53A", "LIKELY_PATHOGENIC", patient_dob="2008-06-01", opt_in=True,
        on_symbol="APCA", panel_name="MiniPanelA")
    FX.sign_out(adult_order["id"], adult_report["id"], director_user_id="director-1")
    adult_report_re = validate_success(api.get_report(adult_report["id"], DIRECTOR), 200)
    adult_order_re = FX.get_order(adult_order["id"])
    assert adult_report_re["incidental_disclosed"] is True
    assert adult_order_re["has_reportable_incidental"] is True


def test_incidental_age_18_inclusive_adult_boundary(api):
    """PRD §3.8: "The patient is a minor when that age is strictly less than 18; a
    patient whose age is exactly 18 is an adult (the boundary is inclusive of
    adulthood)."

    Design: Difficulty/boundary_precision_check/incidental_minor_age_18_inclusive_boundary
    """
    # dob 2008-06-01 at clock 2026-06-19 -> exactly 18 -> adult -> LP incidental disclosed.
    FX.set_clock("2026-06-19T00:00:00.000Z")
    order, report, _, _ = _build_incidental_order(
        "OFF1", "LIKELY_PATHOGENIC", patient_dob="2008-06-01", opt_in=True,
        on_symbol="ON1", panel_name="PAdult")
    FX.sign_out(order["id"], report["id"], director_user_id="director-1")
    report_re = validate_success(api.get_report(report["id"], DIRECTOR), 200)
    assert report_re["incidental_disclosed"] is True


# --------------------------------------------------------------------------- #
# Second tests for queue A coverage (≥2 per instance)
# --------------------------------------------------------------------------- #
def test_signout_billing_cleared_pending_blocks(api):
    """PRD §3.8: "3. **Billing cleared.** The order's `financial_status` must be one
    of `AUTH_APPROVED`, `PATIENT_PAY`, or `SETTLED`; otherwise the sign-out is
    rejected with `ERR_BILLING_NOT_CLEARED` (HTTP 402)."

    Design: Difficulty/cross_entity_state_dependency/signout_depends_on_billing_cleared
    """
    # COMMERCIAL order with NO auth decision: financial_status stays AUTH_REQUESTED,
    # which is also "not cleared" -> ERR_BILLING_NOT_CLEARED at sign-out.
    FX.set_clock()
    panel, _ = FX.create_published_panel(list_price_cents=100000, gene_symbols=("GD2",),
                                         name="PD2")
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"])
    FX.add_requisition(order["id"], "COMMERCIAL")
    FX.submit_requisition(order["id"])  # financial AUTH_REQUESTED (not cleared)
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    var = FX.add_variant(order["id"], _on_gene(panel), hgvs="c.16A>T")
    FX.classify(order["id"], var["id"], "BENIGN", user_id="tech-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"])
    resp = api.sign_out_report(order["id"], report["id"], make_headers("director-1", "LabDirector"))
    validate_error(resp, ApiErrorId.ERR_BILLING_NOT_CLEARED.value, 402)


def test_accession_allowed_when_consent_signed(api):
    """PRD §3.3: "a consent in `SIGNED` status must exist before a specimen can be
    accessioned."
    PRD §3.4: "On the sufficient branch, the server ... moves the specimen from
    `RECEIVED` to `ACCESSIONED`, and advances the order's `pipeline_status` from
    `REQUISITIONED` to `ACCESSIONED`."

    Design: Difficulty/cross_entity_state_dependency/accession_depends_on_consent_signed
    """
    ctx = FX.setup_requisitioned(insurance_payer="SELF_PAY", requires_consent=True,
                                 gene_symbols=("GE2",), name="PE2")
    FX.add_signed_consent(ctx["order"]["id"], incidental_findings_opt_in=False)
    spec = FX.add_specimen(ctx["order"]["id"])
    resp = api.accession_specimen(ctx["order"]["id"], spec["id"], ACCESSIONING)
    data = validate_success(resp, 200)
    assert data["status"] == "ACCESSIONED"
    order = FX.get_order(ctx["order"]["id"])
    assert order["pipeline_status"] == "ACCESSIONED"


def test_signout_sod_precedence_leaves_report_draft(api):
    """PRD §3.8: "4. **Segregation of duties.** The signing director's `X-User-ID`
    must not equal the `classified_by_user_id` of any variant on the order ... A
    violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). 5. **VUS
    handling.** No variant on the order may carry classification `VUS` unless a
    counselor referral with `reason` `VUS_FOLLOWUP` exists ..."

    Design: Difficulty/priority_pair_validation_conflict/signout_safety_beats_constraint
    """
    # Same dual violation (SoD + open VUS, no referral); assert the higher-priority
    # SoD error fires AND the report is left DRAFT (no state mutation on rejection).
    FX.set_clock()
    panel, _ = FX.create_published_panel(gene_symbols=("GW2",), name="PW2")
    provider = FX.create_provider()
    order = FX.place_order(panel["id"], provider["id"])
    FX.add_requisition(order["id"], "SELF_PAY")
    FX.submit_requisition(order["id"])
    spec = FX.add_specimen(order["id"])
    FX.accession(order["id"], spec["id"])
    get_success_data(api.start_sequencing(order["id"], ACCESSIONING))
    var = FX.add_variant(order["id"], _on_gene(panel), hgvs="c.17A>T")
    FX.classify(order["id"], var["id"], "VUS", user_id="director-1")
    FX.complete_classification(order["id"])
    report = FX.create_report(order["id"], headers=make_headers("director-1", "LabDirector"))
    resp = api.sign_out_report(order["id"], report["id"], make_headers("director-1", "LabDirector"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    reread = validate_success(api.get_report(report["id"], DIRECTOR), 200)
    assert reread["status"] == "DRAFT"
    assert FX.get_order(order["id"])["pipeline_status"] == "CLASSIFIED"


def test_incidental_minor_pathogenic_acmg_disclosed(api):
    """PRD §3.8: "a minor who opted in receives only `PATHOGENIC` ACMG secondary
    findings, with likely-pathogenic incidentals withheld."

    Design: Difficulty/dual_variant_calc/incidental_disclosure_adult_vs_minor_findings
    """
    # Minor (age 16) with a PATHOGENIC ACMG incidental and opt-in -> disclosed.
    FX.set_clock("2026-06-19T00:00:00.000Z")
    order, report, _, _ = _build_incidental_order(
        "BRCA2MP", "PATHOGENIC", patient_dob="2010-06-19", opt_in=True,
        on_symbol="ONMP", panel_name="MinorPathoPanel")
    FX.sign_out(order["id"], report["id"], director_user_id="director-1")
    report_re = validate_success(api.get_report(report["id"], DIRECTOR), 200)
    order_re = FX.get_order(order["id"])
    assert report_re["incidental_disclosed"] is True
    assert order_re["has_reportable_incidental"] is True


def test_incidental_age_just_under_18_minor_boundary(api):
    """PRD §3.8: "The patient is a minor when that age is strictly less than 18 ...
    a minor who opted in receives only `PATHOGENIC` ACMG secondary findings, with
    likely-pathogenic incidentals withheld."

    Design: Difficulty/boundary_precision_check/incidental_minor_age_18_inclusive_boundary
    """
    # dob 2008-06-20 at clock 2026-06-19 -> age 17 (one day short of 18) -> minor;
    # LIKELY_PATHOGENIC incidental withheld for minors -> not disclosed (X-1 side).
    FX.set_clock("2026-06-19T00:00:00.000Z")
    order, report, _, _ = _build_incidental_order(
        "OFF17", "LIKELY_PATHOGENIC", patient_dob="2008-06-20", opt_in=True,
        on_symbol="ON17", panel_name="PMinor17")
    FX.sign_out(order["id"], report["id"], director_user_id="director-1")
    report_re = validate_success(api.get_report(report["id"], DIRECTOR), 200)
    assert report_re["incidental_disclosed"] is False
