"""Composite setup helpers.

Every helper builds its preconditions from scratch through the public API —
each test runs against a freshly restarted server with an empty database and
the logical clock at the startup default of 2026-08-01T00:00:00Z (PRD §2.5).

Role convention (PRD §2.9 segregation of duties): certificates and law labels
are created by ComplianceOfficer co-1 and approved/activated by co-2; foam
batches are poured by LineSupervisor ls-1 and cure-certified by QcInspector
qc-1. Retailer calls use the retailer entity id as X-User-ID.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_retailer_payload,
    create_model_payload,
    create_bom_line_payload,
    create_certificate_payload,
    create_law_label_spec_payload,
    create_foam_batch_payload,
    create_production_order_payload,
    create_shipment_payload,
    create_return_payload,
    create_inspect_payload,
    create_warranty_claim_payload,
    create_recycling_intake_payload,
)
from .test_users import (
    TEST_USERS,
    make_retailer_headers,
)

PM = TEST_USERS["plant_manager_headers"]
CO1 = TEST_USERS["compliance_creator_headers"]
CO2 = TEST_USERS["compliance_approver_headers"]
LS1 = TEST_USERS["line_supervisor_headers"]
QC1 = TEST_USERS["qc_inspector_headers"]
LOG1 = TEST_USERS["logistics_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation
# ---------------------------------------------------------------------------

def create_retailer_account(**overrides) -> dict:
    """POST /plant/retailers as PlantManager. Returns the Retailer."""
    resp = api_client.create_retailer(create_retailer_payload(**overrides), PM)
    return get_success_data(resp)


def create_model_with_bom(bom_lines=None, **model_overrides) -> dict:
    """Model in DRAFT with BOM lines. Returns {"model": ..., "lines": [...]}."""
    model = get_success_data(api_client.create_model(create_model_payload(**model_overrides), PM))
    lines = []
    for line in (bom_lines if bom_lines is not None else [create_bom_line_payload()]):
        lines.append(get_success_data(api_client.create_bom_line(model["id"], line, PM)))
    return {"model": model, "lines": lines}


def create_poured_batch(chamber_id="CH-1", poured_mass_kg=1000,
                        foam_density_class="STANDARD") -> dict:
    resp = api_client.create_foam_batch(
        create_foam_batch_payload(
            foam_density_class=foam_density_class,
            poured_mass_kg=poured_mass_kg,
            chamber_id=chamber_id,
        ),
        LS1,
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: model regulatory lifecycle
# ---------------------------------------------------------------------------

def submit_model_for_certification(model_id: str) -> dict:
    return get_success_data(api_client.submit_model_for_certification(model_id, PM))


def add_approved_flammability_cert(model_id: str, expires_on="2030-01-01T00:00:00Z",
                                   issued_on="2026-01-01T00:00:00Z") -> dict:
    """Submit (co-1) + approve (co-2) a FLAMMABILITY_16CFR1633 cert. Model must
    be in CERT_REVIEW. Returns the APPROVED certificate."""
    cert = get_success_data(api_client.create_certificate(
        model_id,
        create_certificate_payload(issued_on=issued_on, expires_on=expires_on),
        CO1,
    ))
    return get_success_data(api_client.approve_certificate(model_id, cert["id"], CO2))


def setup_certified_model(cert_expires_on="2030-01-01T00:00:00Z",
                          bom_lines=None, **model_overrides) -> dict:
    """Model walked DRAFT -> CERT_REVIEW -> CERTIFIED with one APPROVED
    flammability certificate. Returns {"model", "lines", "cert"}."""
    built = create_model_with_bom(bom_lines=bom_lines, **model_overrides)
    model_id = built["model"]["id"]
    submit_model_for_certification(model_id)
    cert = add_approved_flammability_cert(model_id, expires_on=cert_expires_on)
    model = get_success_data(api_client.certify_model(model_id, CO1))
    return {"model": model, "lines": built["lines"], "cert": cert}


def setup_active_model(cert_expires_on="2030-01-01T00:00:00Z",
                       bom_lines=None, **model_overrides) -> dict:
    """Model walked all the way to ACTIVE. Returns {"model", "lines", "cert"}."""
    ctx = setup_certified_model(cert_expires_on=cert_expires_on,
                                bom_lines=bom_lines, **model_overrides)
    model = get_success_data(api_client.activate_model(ctx["model"]["id"], PM))
    ctx["model"] = model
    return ctx


def publish_spec(state_code="CA", filling_content_codes=None, required_phrases=None,
                 prop65_warning_required=False) -> dict:
    """Create + publish a StateLawLabelSpec. Returns the PUBLISHED spec."""
    payload = {}
    if filling_content_codes is not None:
        payload["filling_content_codes"] = filling_content_codes
    if required_phrases is not None:
        payload["required_phrases"] = required_phrases
    spec = get_success_data(api_client.create_law_label_spec(
        create_law_label_spec_payload(
            state_code=state_code,
            prop65_warning_required=prop65_warning_required,
            **payload,
        ),
        CO1,
    ))
    return get_success_data(api_client.publish_law_label_spec(spec["id"], CO1))


def generate_label(model_id: str, state_code="CA") -> dict:
    """Generate a law label against the model's CURRENT version (OCC)."""
    current = get_success_data(api_client.get_model(model_id, PM))
    return get_success_data(api_client.create_law_label(
        model_id,
        {"state_code": state_code, "expected_model_version": current["version"]},
        CO1,
    ))


def setup_active_label(state_code="CA", prop65_warning_required=False,
                       cert_expires_on="2030-01-01T00:00:00Z",
                       required_phrases=None, **model_overrides) -> dict:
    """ACTIVE model + PUBLISHED spec + ACTIVE law label for the state.

    Returns {"model", "lines", "cert", "spec", "label"}."""
    ctx = setup_active_model(cert_expires_on=cert_expires_on, **model_overrides)
    spec = publish_spec(
        state_code=state_code,
        prop65_warning_required=prop65_warning_required,
        required_phrases=required_phrases,
    )
    label = generate_label(ctx["model"]["id"], state_code)
    label = get_success_data(
        api_client.approve_law_label(ctx["model"]["id"], label["id"], CO2)
    )
    label = get_success_data(
        api_client.activate_law_label(ctx["model"]["id"], label["id"], CO2)
    )
    ctx.update({"spec": spec, "label": label})
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: foam curing
# ---------------------------------------------------------------------------

def setup_cured_batch(chamber_id="CH-1", poured_mass_kg=1000,
                      foam_density_class="STANDARD", ambient_temp_c=20,
                      certify_clock="2026-08-02T00:00:00Z") -> dict:
    """Pour -> start-cure -> advance clock -> certify-cured. Returns CURED batch.

    Default: STANDARD at 20C (NORMAL tier) started at the 2026-08-01T00:00:00Z
    default clock, so cure_eligible_at is 2026-08-02T00:00:00Z.
    """
    batch = create_poured_batch(chamber_id=chamber_id, poured_mass_kg=poured_mass_kg,
                                foam_density_class=foam_density_class)
    get_success_data(api_client.start_cure(batch["id"], {"ambient_temp_c": ambient_temp_c}, LS1))
    get_success_data(api_client.set_clock(certify_clock, PM))
    return get_success_data(api_client.certify_cured(batch["id"], QC1))


# ---------------------------------------------------------------------------
# Tier 4: production pipeline
# ---------------------------------------------------------------------------

def list_order_units(order_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_units(PM, params={"order_id": order_id}))
    return data


def place_order(model_id: str, retailer_id: str, state_code="CA", quantity=1,
                unit_price_cents=200000, foam_mass_required_kg=10,
                ship_method="WAREHOUSE") -> dict:
    """Create one production order as PlantManager. Returns it (PLANNED)."""
    return get_success_data(api_client.create_production_order(
        create_production_order_payload(
            model_id=model_id,
            retailer_id=retailer_id,
            destination_state_code=state_code,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
            foam_mass_required_kg=foam_mass_required_kg,
            ship_method=ship_method,
        ),
        PM,
    ))


def allocate_order(order_id: str, batch_id: str) -> dict:
    """PLANNED -> MATERIAL_ALLOCATED against the given batch."""
    return get_success_data(
        api_client.allocate_materials(order_id, {"foam_batch_id": batch_id}, LS1)
    )


def setup_planned_order(state_code="NV", quantity=1,
                        unit_price_cents=200000, foam_mass_required_kg=10,
                        ship_method="WAREHOUSE", retailer_overrides=None,
                        drop_ship_enabled=True, **model_overrides) -> dict:
    """ACTIVE model (no law label) + retailer + one PLANNED order."""
    retailer = create_retailer_account(
        **(retailer_overrides if retailer_overrides is not None
           else {"drop_ship_enabled": drop_ship_enabled})
    )
    ctx = setup_active_model(**model_overrides)
    order = get_success_data(api_client.create_production_order(
        create_production_order_payload(
            model_id=ctx["model"]["id"],
            retailer_id=retailer["id"],
            destination_state_code=state_code,
            quantity=quantity,
            unit_price_cents=unit_price_cents,
            foam_mass_required_kg=foam_mass_required_kg,
            ship_method=ship_method,
        ),
        PM,
    ))
    return {"retailer": retailer, "model": ctx["model"], "cert": ctx["cert"],
            "lines": ctx["lines"], "order": order}


def setup_complete_order(state_code="CA", quantity=1, unit_price_cents=200000,
                         foam_mass_required_kg=10, ship_method="WAREHOUSE",
                         batch_mass_kg=1000, chamber_id="CH-1",
                         retailer_overrides=None, cert_expires_on="2030-01-01T00:00:00Z",
                         prop65_warning_required=False, **model_overrides) -> dict:
    """Full pipeline: ACTIVE label + CURED batch + order driven PLANNED ->
    MATERIAL_ALLOCATED -> IN_PRODUCTION -> QC_PENDING -> COMPLETE, with
    `quantity` MANUFACTURED units. Returns the whole namespace."""
    retailer = create_retailer_account(
        **(retailer_overrides if retailer_overrides is not None else {})
    )
    ctx = setup_active_label(
        state_code=state_code,
        prop65_warning_required=prop65_warning_required,
        cert_expires_on=cert_expires_on,
        **model_overrides,
    )
    batch = setup_cured_batch(chamber_id=chamber_id, poured_mass_kg=batch_mass_kg)
    order = place_order(
        ctx["model"]["id"], retailer["id"], state_code=state_code, quantity=quantity,
        unit_price_cents=unit_price_cents, foam_mass_required_kg=foam_mass_required_kg,
        ship_method=ship_method,
    )
    order = allocate_order(order["id"], batch["id"])
    order = get_success_data(api_client.start_production(order["id"], LS1))
    order = get_success_data(api_client.complete_production(order["id"], LS1))
    units = list_order_units(order["id"])
    return {"retailer": retailer, "model": ctx["model"], "lines": ctx["lines"],
            "cert": ctx["cert"], "spec": ctx["spec"], "label": ctx["label"],
            "batch": batch, "order": order, "units": units}


def setup_allocated_order(state_code="CA", quantity=1, unit_price_cents=200000,
                          foam_mass_required_kg=10, ship_method="WAREHOUSE",
                          batch_mass_kg=1000, chamber_id="CH-1",
                          cert_expires_on="2030-01-01T00:00:00Z",
                          **model_overrides) -> dict:
    """ACTIVE label + CURED batch + one order stopped at MATERIAL_ALLOCATED."""
    retailer = create_retailer_account()
    ctx = setup_active_label(state_code=state_code,
                             cert_expires_on=cert_expires_on, **model_overrides)
    batch = setup_cured_batch(chamber_id=chamber_id, poured_mass_kg=batch_mass_kg)
    order = place_order(
        ctx["model"]["id"], retailer["id"], state_code=state_code, quantity=quantity,
        unit_price_cents=unit_price_cents, foam_mass_required_kg=foam_mass_required_kg,
        ship_method=ship_method,
    )
    order = allocate_order(order["id"], batch["id"])
    return {"retailer": retailer, "model": ctx["model"], "lines": ctx["lines"],
            "cert": ctx["cert"], "spec": ctx["spec"], "label": ctx["label"],
            "batch": batch, "order": order}


def qc_pass_order(ctx: dict) -> dict:
    """Run the QC gate: QC_PENDING -> COMPLETE. Updates ctx["order"]."""
    ctx["order"] = get_success_data(api_client.qc_pass_order(ctx["order"]["id"], QC1))
    return ctx


def setup_delivered_order(quantity=1, deliver_clock=None, **kwargs) -> dict:
    """Everything in setup_complete_order plus qc-pass, one shipment covering
    all units, dispatch and deliver. Units end DELIVERED with delivered_at
    stamped from the logical clock (2026-08-02T00:00:00Z unless advanced)."""
    ctx = setup_complete_order(quantity=quantity, **kwargs)
    qc_pass_order(ctx)
    unit_ids = [u["id"] for u in ctx["units"]]
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(order_id=ctx["order"]["id"], unit_ids=unit_ids), LOG1
    ))
    if deliver_clock is not None:
        get_success_data(api_client.set_clock(deliver_clock, PM))
    get_success_data(api_client.dispatch_shipment(shipment["id"], LOG1))
    shipment = get_success_data(api_client.deliver_shipment(shipment["id"], LOG1))
    ctx["shipment"] = shipment
    ctx["units"] = [get_success_data(api_client.get_unit(u["id"], PM)) for u in ctx["units"]]
    ctx["order"] = get_success_data(api_client.get_production_order(ctx["order"]["id"], PM))
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: after-sale lifecycles (claims, returns, intakes)
# ---------------------------------------------------------------------------

def setup_filed_claim(claim_type="WORKMANSHIP", measured_sag_inches=0.5,
                      unit_price_cents=200000, credit_limit_cents=100000000,
                      quantity=1, **kwargs) -> dict:
    """Delivered unit + FILED warranty claim filed by the retailer itself."""
    ctx = setup_delivered_order(
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        retailer_overrides={"credit_limit_cents": credit_limit_cents},
        **kwargs,
    )
    claim = get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(
            unit_id=ctx["units"][0]["id"],
            retailer_id=ctx["retailer"]["id"],
            claim_type=claim_type,
            measured_sag_inches=measured_sag_inches,
        ),
        make_retailer_headers(ctx["retailer"]["id"]),
    ))
    ctx["claim"] = claim
    return ctx


def setup_approved_claim(approve_clock=None, **kwargs) -> dict:
    """FILED claim approved (credit computed at approval). Optionally advance
    the logical clock first to control the unit's age in months."""
    ctx = setup_filed_claim(**kwargs)
    if approve_clock is not None:
        get_success_data(api_client.set_clock(approve_clock, PM))
    ctx["claim"] = get_success_data(api_client.approve_warranty_claim(ctx["claim"]["id"], PM))
    return ctx


def setup_inspected_return(reason="DEFECT", measured_sag_inches=2.1, **kwargs) -> dict:
    """Delivered unit + return opened by the retailer, received and inspected."""
    ctx = setup_delivered_order(**kwargs)
    ret = get_success_data(api_client.create_return(
        create_return_payload(
            unit_id=ctx["units"][0]["id"],
            retailer_id=ctx["retailer"]["id"],
            reason=reason,
        ),
        make_retailer_headers(ctx["retailer"]["id"]),
    ))
    ret = get_success_data(api_client.receive_return(ret["id"], QC1))
    ret = get_success_data(
        api_client.inspect_return(ret["id"], create_inspect_payload(
            measured_sag_inches=measured_sag_inches
        ), QC1)
    )
    ctx["return"] = ret
    return ctx


def setup_recycling_retailer(credit_limit_cents=100000000) -> dict:
    """Enrolled retailer for take-back intake tests."""
    return create_retailer_account(
        recycling_enrolled=True, credit_limit_cents=credit_limit_cents
    )


def create_intake(retailer_id: str, declared_weight_kg=100, **extra) -> dict:
    payload = create_recycling_intake_payload(
        retailer_id=retailer_id, declared_weight_kg=declared_weight_kg, **extra
    )
    return get_success_data(api_client.create_recycling_intake(payload, LOG1))


def list_ledger(retailer_id: str) -> list:
    data, _meta = validate_paginated(api_client.list_credit_adjustments(retailer_id, PM))
    return data
