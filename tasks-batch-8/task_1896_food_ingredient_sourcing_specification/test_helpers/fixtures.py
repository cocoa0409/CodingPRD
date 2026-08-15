"""Composite setup helpers.

The harness restarts the API server before every test, so each test rebuilds
its preconditions from scratch through these helpers. All helpers use the
lenient get_success_data() validator and raise AssertionError with context on
failure, so a broken setup reads as "Setup failed: <step>".

OCC threading: every OCC-guarded create (spec, approved source, contract — PRD
§2.7) re-reads the parent's current version immediately before the write, so
fixtures never depend on a cached version going stale mid-chain.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AUTHOR_1,
    COA_RECEIVED_AT,
    CONTRACT_WINDOW_END,
    CONTRACT_WINDOW_START,
    DECLARATION_VALID_FROM,
    DECLARATION_VALID_UNTIL,
    PM_1,
    QM_1,
    QM_2,
    RA_1,
    SPEC_EFFECTIVE_DATE,
    SQE_1,
)
from .factories import (
    create_allergen_declaration_payload,
    create_approved_source_payload,
    create_audit_payload,
    create_capa_payload,
    create_coa_payload,
    create_contract_payload,
    create_coo_declaration_payload,
    create_ingredient_payload,
    create_parameter_payload,
    create_qualification_payload,
    create_spec_payload,
    create_substitution_request_payload,
    create_supplier_payload,
)
from .test_users import (
    TEST_USERS,
    make_procurement_manager_headers,
    make_quality_manager_headers,
    make_regulatory_affairs_headers,
    make_spec_author_headers,
    make_sqe_headers,
)

PM = TEST_USERS["procurement_manager_headers"]
QM = TEST_USERS["quality_manager_headers"]
SQE = TEST_USERS["sqe_headers"]
RA = TEST_USERS["regulatory_affairs_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]
AUTHOR = TEST_USERS["spec_author_headers"]


def _data(resp, what):
    if resp.status_code >= 400:
        raise AssertionError(f"Setup failed during {what}: HTTP {resp.status_code} {resp.text[:400]}")
    return get_success_data(resp)


# --- Clock -------------------------------------------------------------------

def set_clock(to_iso8601):
    return _data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN), f"set clock to {to_iso8601}")


# --- Ingredients and specs ---------------------------------------------------

def create_ingredient_entity(ingredient_code="ENZ-1", name=None, allergen_profile=None, requires_dual_source=False):
    payload = create_ingredient_payload(
        ingredient_code=ingredient_code,
        name=name or f"Ingredient {ingredient_code}",
        allergen_profile=allergen_profile if allergen_profile is not None else ["NONE"],
        requires_dual_source=requires_dual_source,
    )
    return _data(api_client.create_ingredient(payload, PM), f"create ingredient {ingredient_code}")


def fresh_ingredient(ingredient_id):
    return _data(api_client.get_ingredient(ingredient_id, PM), f"get ingredient {ingredient_id}")


def fresh_ingredient_version(ingredient_id):
    return fresh_ingredient(ingredient_id)["version"]


def create_draft_spec(ingredient_id, label="v1", effective_date=SPEC_EFFECTIVE_DATE,
                      version_note="initial spec version", supersedes_spec_id=None,
                      author_id=AUTHOR_1):
    payload = create_spec_payload(
        fresh_ingredient_version(ingredient_id),
        spec_version_label=label,
        effective_date=effective_date,
        version_note=version_note,
    )
    if supersedes_spec_id is not None:
        payload["supersedes_spec_id"] = supersedes_spec_id
    headers = make_spec_author_headers(author_id)
    return _data(api_client.create_spec(ingredient_id, payload, headers), f"create spec {label}")


def add_parameter(ingredient_id, spec_id, parameter_name="moisture", criticality="MINOR",
                  uom="percent", target_value=5, min_value=0, max_value=10, author_id=AUTHOR_1):
    payload = create_parameter_payload(
        parameter_name=parameter_name, criticality=criticality, uom=uom,
        target_value=target_value, min_value=min_value, max_value=max_value,
    )
    headers = make_spec_author_headers(author_id)
    return _data(
        api_client.add_spec_parameter(ingredient_id, spec_id, payload, headers),
        f"add parameter {parameter_name}",
    )


def submit_spec(ingredient_id, spec_id, author_id=AUTHOR_1):
    headers = make_spec_author_headers(author_id)
    return _data(api_client.submit_spec(ingredient_id, spec_id, headers), "submit spec")


def approve_spec(ingredient_id, spec_id, qm_id=QM_1):
    headers = make_quality_manager_headers(qm_id)
    return _data(api_client.approve_spec(ingredient_id, spec_id, headers), "approve spec")


def make_spec_effective(ingredient_id, spec_id, qm_id=QM_1):
    headers = make_quality_manager_headers(qm_id)
    return _data(api_client.make_spec_effective(ingredient_id, spec_id, headers), "make spec effective")


def create_draft_spec_with_parameters(ingredient_id, parameters=None, label="v1",
                                      effective_date=SPEC_EFFECTIVE_DATE,
                                      version_note="initial spec version",
                                      supersedes_spec_id=None, author_id=AUTHOR_1):
    """DRAFT spec carrying the given parameter rows (list of add_parameter kwargs)."""
    spec = create_draft_spec(
        ingredient_id, label=label, effective_date=effective_date,
        version_note=version_note, supersedes_spec_id=supersedes_spec_id, author_id=author_id,
    )
    for param in (parameters if parameters is not None else [{}]):
        add_parameter(ingredient_id, spec["id"], author_id=author_id, **param)
    return spec


def create_ingredient_with_effective_spec(ingredient_code="ENZ-1", parameters=None,
                                          requires_dual_source=False, allergen_profile=None,
                                          effective_date=SPEC_EFFECTIVE_DATE,
                                          author_id=AUTHOR_1, qm_id=QM_1):
    """Ingredient + one spec walked DRAFT -> PENDING_REVIEW -> APPROVED -> EFFECTIVE.

    Returns (ingredient_refreshed, spec).
    """
    ingredient = create_ingredient_entity(
        ingredient_code, allergen_profile=allergen_profile, requires_dual_source=requires_dual_source,
    )
    spec = create_draft_spec_with_parameters(
        ingredient["id"], parameters=parameters, effective_date=effective_date, author_id=author_id,
    )
    submit_spec(ingredient["id"], spec["id"], author_id=author_id)
    approve_spec(ingredient["id"], spec["id"], qm_id=qm_id)
    make_spec_effective(ingredient["id"], spec["id"], qm_id=qm_id)
    return fresh_ingredient(ingredient["id"]), spec


# --- Suppliers and qualifications ---------------------------------------------

def create_supplier_entity(supplier_code="SUP-1", risk_tier="TIER_A", country_of_operation="US"):
    payload = create_supplier_payload(
        supplier_code=supplier_code, risk_tier=risk_tier, country_of_operation=country_of_operation,
        legal_name=f"Supplier {supplier_code}",
    )
    return _data(api_client.create_supplier(payload, PM), f"create supplier {supplier_code}")


def create_qualified_supplier(supplier_code="SUP-1", risk_tier="TIER_A", questionnaire_score=90,
                              document_pack_complete=True, country_of_operation="US",
                              sqe_id=SQE_1, qm_id=QM_1):
    """Supplier walked PROSPECT -> IN_QUALIFICATION -> QUALIFIED."""
    supplier = create_supplier_entity(supplier_code, risk_tier=risk_tier, country_of_operation=country_of_operation)
    sqe_headers = make_sqe_headers(sqe_id)
    qual = _data(
        api_client.create_qualification(
            supplier["id"],
            create_qualification_payload(
                questionnaire_score=questionnaire_score,
                document_pack_complete=document_pack_complete,
            ),
            sqe_headers,
        ),
        f"open qualification for {supplier_code}",
    )
    qm_headers = make_quality_manager_headers(qm_id)
    _data(api_client.evaluate_qualification(supplier["id"], qual["id"], qm_headers), "evaluate qualification")
    _data(
        api_client.decide_qualification(
            supplier["id"], qual["id"],
            {"decision": "APPROVE", "decision_note": "qualification approved"},
            qm_headers,
        ),
        "approve qualification",
    )
    return _data(api_client.get_supplier(supplier["id"], QM), f"get supplier {supplier_code}")


# --- Approved sources and declarations ----------------------------------------

def fresh_source(source_id):
    return _data(api_client.get_approved_source(source_id, PM), f"get approved source {source_id}")


def fresh_source_version(source_id):
    return fresh_source(source_id)["version"]


def create_provisional_source(ingredient_id, supplier_id, spec_id):
    payload = create_approved_source_payload(
        supplier_id, spec_id, fresh_ingredient_version(ingredient_id),
    )
    return _data(api_client.create_approved_source(ingredient_id, payload, PM), "create approved source")


def collect_declarations(source_id, allergen_tags=None, primary_country="US",
                         valid_from=DECLARATION_VALID_FROM, valid_until=DECLARATION_VALID_UNTIL,
                         ra_id=RA_1):
    headers = make_regulatory_affairs_headers(ra_id)
    allergen = _data(
        api_client.create_declaration(
            source_id,
            create_allergen_declaration_payload(
                payload={"allergen_tags": list(allergen_tags) if allergen_tags is not None else ["NONE"]},
                valid_from=valid_from, valid_until=valid_until,
            ),
            headers,
        ),
        "collect ALLERGEN declaration",
    )
    coo = _data(
        api_client.create_declaration(
            source_id,
            create_coo_declaration_payload(
                payload={"country_codes": [primary_country], "primary_country": primary_country},
                valid_from=valid_from, valid_until=valid_until,
            ),
            headers,
        ),
        "collect COUNTRY_OF_ORIGIN declaration",
    )
    return allergen, coo


def activate_source(ingredient_id, source_id):
    return _data(api_client.activate_approved_source(ingredient_id, source_id, PM), "activate source")


def create_active_source(ingredient_id, supplier_id, spec_id, allergen_tags=None,
                         primary_country="US", valid_from=DECLARATION_VALID_FROM,
                         valid_until=DECLARATION_VALID_UNTIL):
    """PROVISIONAL source + both CURRENT declarations + activate. Returns ACTIVE source."""
    source = create_provisional_source(ingredient_id, supplier_id, spec_id)
    collect_declarations(
        source["id"], allergen_tags=allergen_tags, primary_country=primary_country,
        valid_from=valid_from, valid_until=valid_until,
    )
    return activate_source(ingredient_id, source["id"])


# --- Contracts -----------------------------------------------------------------

def create_pending_contract(source_id, annual_committed_volume_kg=10000, index_base_value=100,
                            index_pass_through_pct=0.5, window_start=CONTRACT_WINDOW_START,
                            window_end=CONTRACT_WINDOW_END):
    payload = create_contract_payload(
        fresh_source_version(source_id),
        annual_committed_volume_kg=annual_committed_volume_kg,
        index_base_value=index_base_value,
        index_pass_through_pct=index_pass_through_pct,
        window_start=window_start,
        window_end=window_end,
    )
    return _data(api_client.create_contract(source_id, payload, PM), "create contract")


def activate_contract(source_id, contract_id):
    return _data(api_client.activate_contract(source_id, contract_id, PM), "activate contract")


def create_active_contract(source_id, **kwargs):
    contract = create_pending_contract(source_id, **kwargs)
    return activate_contract(source_id, contract["id"])


# --- Composite: active source with active contract ------------------------------

def setup_source_with_contract(ingredient_code="ENZ-1", parameters=None, supplier_code="SUP-1",
                               requires_dual_source=False, allergen_profile=None,
                               supplier_risk_tier="TIER_A", supplier_country="US",
                               contract_kwargs=None, questionnaire_score=90,
                               declaration_kwargs=None):
    """Full chain: EFFECTIVE spec + QUALIFIED supplier + ACTIVE source (both
    declarations) + ACTIVE contract. Returns a context dict."""
    ingredient, spec = create_ingredient_with_effective_spec(
        ingredient_code, parameters=parameters, requires_dual_source=requires_dual_source,
        allergen_profile=allergen_profile,
    )
    supplier = create_qualified_supplier(
        supplier_code, risk_tier=supplier_risk_tier, country_of_operation=supplier_country,
        questionnaire_score=questionnaire_score,
    )
    decl = declaration_kwargs or {}
    source = create_active_source(ingredient["id"], supplier["id"], spec["id"], **decl)
    contract = create_active_contract(source["id"], **(contract_kwargs or {}))
    return {
        "ingredient": ingredient,
        "spec": spec,
        "supplier": supplier,
        "source": source,
        "contract": contract,
    }


def setup_dual_sourced_ingredient(ingredient_code="DUAL-1", parameters=None,
                                  supplier_codes=("SUP-A", "SUP-B"),
                                  countries=("US", "CA")):
    """requires_dual_source ingredient with two ACTIVE sources pinned to the one
    EFFECTIVE spec. Returns a context dict; breach flag is false at return."""
    ingredient, spec = create_ingredient_with_effective_spec(
        ingredient_code, parameters=parameters, requires_dual_source=True,
    )
    sources = []
    suppliers = []
    for code, country in zip(supplier_codes, countries):
        supplier = create_qualified_supplier(code, country_of_operation=country)
        source = create_active_source(ingredient["id"], supplier["id"], spec["id"], primary_country=country)
        suppliers.append(supplier)
        sources.append(source)
    return {
        "ingredient": fresh_ingredient(ingredient["id"]),
        "spec": spec,
        "suppliers": suppliers,
        "sources": sources,
    }


# --- CoAs -----------------------------------------------------------------------

def register_coa(source_id, contract_id, lot_number="L1", shipped_qty_kg=100,
                 received_at=COA_RECEIVED_AT, measured_values=None, registrar_id=SQE_1):
    if measured_values is None:
        measured_values = [{"parameter_name": "moisture", "observed_value": 5}]
    payload = create_coa_payload(
        contract_id, measured_values,
        lot_number=lot_number, shipped_qty_kg=shipped_qty_kg, received_at=received_at,
    )
    headers = make_sqe_headers(registrar_id)
    return _data(api_client.register_coa(source_id, payload, headers), f"register CoA {lot_number}")


def start_coa_review(source_id, coa_id, qm_id=QM_1):
    """REGISTERED -> UNDER_REVIEW. Returns (coa, findings_list_in_creation_order)."""
    headers = make_quality_manager_headers(qm_id)
    coa = _data(api_client.start_coa_review(source_id, coa_id, headers), "start CoA review")
    findings = _data(api_client.list_coa_findings(source_id, coa_id, headers), "list CoA findings")
    return coa, findings


def disposition_finding(source_id, coa_id, finding_id, disposition,
                        note="disposition rationale text", qm_id=QM_1):
    headers = make_quality_manager_headers(qm_id)
    return _data(
        api_client.disposition_finding(
            source_id, coa_id, finding_id,
            {"disposition": disposition, "disposition_note": note},
            headers,
        ),
        f"disposition finding {finding_id} as {disposition}",
    )


def close_coa_review_response(source_id, coa_id, outcome, closer_id=QM_2):
    """Raw response of close-review (tests assert on success or error)."""
    headers = make_quality_manager_headers(closer_id)
    return api_client.close_coa_review(source_id, coa_id, {"outcome": outcome}, headers)


def register_and_accept_coa(source_id, contract_id, lot_number, shipped_qty_kg,
                            received_at, measured_values, registrar_id=SQE_1, closer_id=QM_1):
    """Register an in-spec lot and accept it (no findings expected)."""
    coa = register_coa(
        source_id, contract_id, lot_number=lot_number, shipped_qty_kg=shipped_qty_kg,
        received_at=received_at, measured_values=measured_values, registrar_id=registrar_id,
    )
    start_coa_review(source_id, coa["id"])
    resp = close_coa_review_response(source_id, coa["id"], "ACCEPT", closer_id=closer_id)
    return _data(resp, f"accept CoA {lot_number}")


# --- Substitution requests --------------------------------------------------------

def create_substitution_request(ingredient_id, from_source_id, to_source_id,
                                reason_code="COST_REDUCTION", sensitivities=None, pm_id=PM_1):
    payload = create_substitution_request_payload(
        from_source_id, to_source_id,
        reason_code=reason_code,
        formula_unit_cost_sensitivities=(
            sensitivities if sensitivities is not None
            else [{"parameter_name": "moisture", "cost_per_unit_delta": 0.10}]
        ),
    )
    headers = make_procurement_manager_headers(pm_id)
    return _data(api_client.create_substitution_request(ingredient_id, payload, headers), "create substitution request")


def setup_two_spec_sources(ingredient_code="IMP-1", v1_parameters=None, v2_parameters=None,
                           sensitivities=None):
    """v1 EFFECTIVE with source A ACTIVE -> v2 supersedes v1 (A swept to SUSPENDED)
    -> source B pinned to v2 ACTIVE. Returns ctx for substitution scenarios."""
    ingredient, spec1 = create_ingredient_with_effective_spec(ingredient_code, parameters=v1_parameters)
    supplier_a = create_qualified_supplier(f"{ingredient_code}-A")
    src_a = create_active_source(ingredient["id"], supplier_a["id"], spec1["id"])
    spec2 = create_draft_spec_with_parameters(
        ingredient["id"], parameters=v2_parameters, label="v2",
        effective_date="2026-07-15T00:00:00Z", version_note="revised spec version",
        supersedes_spec_id=spec1["id"],
    )
    submit_spec(ingredient["id"], spec2["id"])
    approve_spec(ingredient["id"], spec2["id"])
    make_spec_effective(ingredient["id"], spec2["id"])
    supplier_b = create_qualified_supplier(f"{ingredient_code}-B")
    src_b = create_active_source(ingredient["id"], supplier_b["id"], spec2["id"])
    return {
        "ingredient": fresh_ingredient(ingredient["id"]),
        "spec1": spec1,
        "spec2": spec2,
        "supplier_a": supplier_a,
        "supplier_b": supplier_b,
        "src_a": src_a,
        "src_b": src_b,
    }


def setup_two_active_sources_same_spec(ingredient_code="EXE-1", parameters=None):
    """Two ACTIVE sources pinned to the same EFFECTIVE spec (for same-spec
    substitution scenarios). Returns ctx."""
    ingredient, spec = create_ingredient_with_effective_spec(ingredient_code, parameters=parameters)
    sup_a = create_qualified_supplier(f"{ingredient_code}-A")
    src_a = create_active_source(ingredient["id"], sup_a["id"], spec["id"])
    sup_b = create_qualified_supplier(f"{ingredient_code}-B")
    src_b = create_active_source(ingredient["id"], sup_b["id"], spec["id"])
    return {
        "ingredient": fresh_ingredient(ingredient["id"]),
        "spec": spec,
        "sup_a": sup_a,
        "sup_b": sup_b,
        "src_a": src_a,
        "src_b": src_b,
    }


# --- Audits and corrective actions -------------------------------------------------

def schedule_audit(supplier_id, window_start="2026-08-01T00:00:00Z",
                   window_end="2026-08-15T00:00:00Z", sqe_id=SQE_1):
    headers = make_sqe_headers(sqe_id)
    return _data(
        api_client.schedule_audit(
            supplier_id,
            create_audit_payload(
                scheduled_window_start=window_start, scheduled_window_end=window_end,
            ),
            headers,
        ),
        "schedule audit",
    )


def start_audit(supplier_id, audit_id, sqe_id=SQE_1):
    return _data(api_client.start_audit(supplier_id, audit_id, make_sqe_headers(sqe_id)), "start audit")


def issue_audit_report(supplier_id, audit_id, audit_score=85,
                       findings_summary="audit findings narrative", sqe_id=SQE_1):
    return _data(
        api_client.issue_audit_report(
            supplier_id, audit_id,
            {"audit_score": audit_score, "findings_summary": findings_summary},
            make_sqe_headers(sqe_id),
        ),
        "issue audit report",
    )


def create_reported_audit(supplier_id, window_start="2026-08-01T00:00:00Z",
                          window_end="2026-08-15T00:00:00Z", audit_score=85,
                          findings_summary="audit findings narrative"):
    """Audit walked SCHEDULED -> IN_PROGRESS -> REPORT_ISSUED (clock must be inside
    the window; the default clock 2026-08-01T00:00:00Z is inside the default window)."""
    audit = schedule_audit(supplier_id, window_start, window_end)
    start_audit(supplier_id, audit["id"])
    issue_audit_report(supplier_id, audit["id"], audit_score, findings_summary)
    return _data(api_client.get_audit_flat(audit["id"], QM), "get audit")


def create_capa(supplier_id, audit_id, description="corrective action description",
                due_date="2026-08-20T00:00:00Z", qm_id=QM_1):
    headers = make_quality_manager_headers(qm_id)
    return _data(
        api_client.create_corrective_action(
            supplier_id, audit_id,
            create_capa_payload(description=description, due_date=due_date),
            headers,
        ),
        "raise CAPA",
    )


def submit_capa(supplier_id, audit_id, capa_id, response_text="response from supplier", sqe_id=SQE_1):
    return _data(
        api_client.submit_capa_response(
            supplier_id, audit_id, capa_id, {"response_text": response_text},
            make_sqe_headers(sqe_id),
        ),
        "submit CAPA response",
    )


def verify_capa(supplier_id, audit_id, capa_id, note="verified on site visit", qm_id=QM_1):
    return _data(
        api_client.verify_capa(
            supplier_id, audit_id, capa_id, {"verification_note": note},
            make_quality_manager_headers(qm_id),
        ),
        "verify CAPA",
    )


def reject_capa(supplier_id, audit_id, capa_id, note="evidence insufficient", qm_id=QM_1):
    return _data(
        api_client.reject_capa_response(
            supplier_id, audit_id, capa_id, {"verification_note": note},
            make_quality_manager_headers(qm_id),
        ),
        "reject CAPA response",
    )
