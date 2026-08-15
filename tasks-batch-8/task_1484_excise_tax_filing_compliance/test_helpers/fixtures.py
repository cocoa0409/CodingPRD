"""Composite setup helpers for the excise-tax workflows (PRD §3).

The harness restarts the server before every test, so each fixture builds its
preconditions from scratch against an empty database. Jurisdiction and product
class codes are unique-per-call (uuid-suffixed) so a fixture may be invoked
more than once inside the same test without tripping code-uniqueness rules.

Conventions:
- Every setup call uses get_success_data() so failures surface as
  "Setup step failed" with the server's error payload.
- Segregation of duties (PRD §2.9): returns are submitted under one X-User-ID
  and filed under another; claims are submitted and approved likewise.
"""
import uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_audit_case_payload,
    create_bond_payload,
    create_bonded_movement_payload,
    create_credit_claim_payload,
    create_exemption_certificate_payload,
    create_jurisdiction_payload,
    create_product_class_payload,
    create_rate_change_notice_payload,
    create_registrant_payload,
    create_registration_payload,
    create_tax_rate_payload,
    create_taxable_event_payload,
)
from .test_users import (
    make_admin_headers,
    make_analyst_headers,
    make_auditor_headers,
    make_reviewer_headers,
)


def _uid() -> str:
    return uuid.uuid4().hex[:8].upper()


# ---------------------------------------------------------------------------
# Header factories (opaque roles; fresh per-call user ids keep SoD deterministic)
# ---------------------------------------------------------------------------
def new_admin_headers():
    return make_admin_headers(f"admin-{_uid()}")


def new_analyst_headers(user_id=None):
    return make_analyst_headers(user_id or f"analyst-{_uid()}")


def new_reviewer_headers(user_id=None):
    return make_reviewer_headers(user_id or f"reviewer-{_uid()}")


def new_auditor_headers():
    return make_auditor_headers(f"auditor-{_uid()}")


# ---------------------------------------------------------------------------
# Tier 2: configuration and base chain
# ---------------------------------------------------------------------------
def create_jurisdiction(**overrides):
    """Create a jurisdiction with a unique code. Returns the Jurisdiction."""
    overrides.setdefault("code", f"JUR-{_uid()}")
    return get_success_data(api_client.create_jurisdiction(
        create_jurisdiction_payload(**overrides), new_admin_headers()))


def create_product_class(code="DIESEL", **overrides):
    """Create a product class with a unique code. Returns the ProductClass."""
    overrides.setdefault("code", f"{code}-{_uid()}")
    return get_success_data(api_client.create_product_class(
        create_product_class_payload(**overrides), new_admin_headers()))


def create_tax_rate(jurisdiction_id, product_class_id,
                    rate_millicents_per_unit=24300,
                    effective_from="2026-01-01T00:00:00Z", **overrides):
    """Directly create a rate. Returns the TaxRate."""
    return get_success_data(api_client.create_tax_rate(
        create_tax_rate_payload(
            jurisdiction_id=jurisdiction_id,
            product_class_id=product_class_id,
            rate_millicents_per_unit=rate_millicents_per_unit,
            effective_from=effective_from,
            **overrides),
        new_admin_headers()))


def create_registrant(**overrides):
    """Create a registrant with a unique fein. Returns the Registrant."""
    overrides.setdefault("fein", f"{uuid.uuid4().int % 100:02d}-{_uid()[:7]}")
    return get_success_data(api_client.create_registrant(
        create_registrant_payload(**overrides), new_admin_headers()))


def create_pending_registration(registrant_id, jurisdiction_id,
                                deposit_method="SAFE_HARBOR", **overrides):
    """Create a PENDING registration. Returns the Registration."""
    return get_success_data(api_client.create_registration(
        create_registration_payload(
            registrant_id=registrant_id,
            jurisdiction_id=jurisdiction_id,
            deposit_method=deposit_method,
            **overrides),
        new_admin_headers()))


def create_and_activate_bond(registration_id, principal_amount_cents=1500000,
                             effective_from="2026-01-01T00:00:00Z",
                             effective_to="2027-06-01T00:00:00Z", **overrides):
    """Create a DRAFT bond and activate it. Returns the ACTIVE Bond."""
    bond = get_success_data(api_client.create_bond(
        create_bond_payload(
            registration_id=registration_id,
            principal_amount_cents=principal_amount_cents,
            effective_from=effective_from,
            effective_to=effective_to,
            **overrides),
        new_admin_headers()))
    return get_success_data(api_client.activate_bond(bond["id"], new_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 1: state progression
# ---------------------------------------------------------------------------
def setup_active_registration(deposit_method="SAFE_HARBOR",
                              bond_amount=1500000,
                              jurisdiction_overrides=None,
                              product_class_code="DIESEL",
                              rate_millicents=24300,
                              create_rate=True,
                              product_classes=None,
                              bond_overrides=None):
    """Jurisdiction + product class(es) + rate + registrant + bonded ACTIVE
    registration. Returns a dict with every created object.

    product_classes: optional list of (code, rate_millicents) tuples; when
    given, each class is created and rated, and ``product_class`` points at
    the first one (``rates`` maps class id -> rate).
    """
    jur = create_jurisdiction(**(jurisdiction_overrides or {}))
    rates = {}
    if product_classes:
        pcs = []
        for code, mc in product_classes:
            pc = create_product_class(code)
            pcs.append(pc)
            rates[pc["id"]] = create_tax_rate(jur["id"], pc["id"], mc)
        pc = pcs[0]
    else:
        pc = create_product_class(product_class_code)
        if create_rate:
            rates[pc["id"]] = create_tax_rate(jur["id"], pc["id"], rate_millicents)
    rgt = create_registrant()
    rgn = create_pending_registration(rgt["id"], jur["id"], deposit_method)
    bnd = create_and_activate_bond(rgn["id"], bond_amount,
                                   **(bond_overrides or {}))
    rgn = get_success_data(
        api_client.activate_registration(rgn["id"], new_admin_headers()))
    return {
        "jurisdiction": jur,
        "product_class": pc,
        "rates": rates,
        "registrant": rgt,
        "registration": rgn,
        "bond": bnd,
    }


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts — events, returns, claims
# ---------------------------------------------------------------------------
def create_event(registration, jurisdiction, product_class,
                 event_date="2026-08-03T00:00:00Z", quantity_units=1000,
                 headers=None, **overrides):
    """Record a DRAFT taxable event. Returns the TaxableEvent."""
    return get_success_data(api_client.create_taxable_event(
        create_taxable_event_payload(
            registration_id=registration["id"],
            jurisdiction_id=jurisdiction["id"],
            product_class_id=product_class["id"],
            event_date=event_date,
            quantity_units=quantity_units,
            **overrides),
        headers or new_analyst_headers()))


def classify_event(event_id, headers=None):
    """DRAFT -> CLASSIFIED. Returns the updated TaxableEvent."""
    return get_success_data(
        api_client.classify_event(event_id, headers or new_analyst_headers()))


def rate_event(event_id, headers=None, **linkage):
    """CLASSIFIED -> RATED (optionally linking a certificate or movement).
    Returns the updated TaxableEvent (its return_id names the period return)."""
    return get_success_data(
        api_client.rate_event(event_id, linkage, headers or new_analyst_headers()))


def create_classified_event(registration, jurisdiction, product_class,
                            **kwargs):
    """Create + classify. Returns the CLASSIFIED TaxableEvent."""
    ev = create_event(registration, jurisdiction, product_class, **kwargs)
    return classify_event(ev["id"])


def create_rated_event(registration, jurisdiction, product_class,
                       rate_headers=None, **kwargs):
    """Create + classify + rate. Returns the RATED TaxableEvent."""
    ev = create_classified_event(registration, jurisdiction, product_class,
                                 **kwargs)
    return rate_event(ev["id"], headers=rate_headers)


# Kwargs that belong on the taxable event, not the registration scenario.
_EVENT_KWARGS = {
    "event_date", "quantity_units", "destination_jurisdiction_id",
    "is_export", "is_interstate", "customer_reference", "certificate_id",
    "movement_id", "documented_volume_loss_units", "tax_class_code",
}


def _split_event_kwargs(scenario_kwargs):
    """Split kwargs into (scenario_kwargs, event_kwargs). Any key in
    _EVENT_KWARGS is routed to the event creation, the rest go to
    setup_active_registration."""
    event_kw = {}
    scen_kw = {}
    for k, v in scenario_kwargs.items():
        if k in _EVENT_KWARGS:
            event_kw[k] = v
        else:
            scen_kw[k] = v
    return scen_kw, event_kw


def setup_return_with_rated_event(event_overrides=None, **scenario_kwargs):
    """Active registration + one RATED event; returns (ctx, event, ret) where
    ctx is the setup_active_registration() dict and ret is the TaxReturn that
    auto-created at rating time."""
    scenario_kwargs, event_kw = _split_event_kwargs(scenario_kwargs)
    merged_event_overrides = dict(event_overrides or {})
    merged_event_overrides.update(event_kw)
    ctx = setup_active_registration(**scenario_kwargs)
    ev = create_rated_event(
        ctx["registration"], ctx["jurisdiction"], ctx["product_class"],
        **merged_event_overrides)
    ret = get_success_data(
        api_client.get_return(ev["return_id"], new_analyst_headers()))
    return ctx, ev, ret


def file_return(return_id, filer_headers=None, amend=False):
    """File a SUBMITTED return: reads the current version and files with it.
    Returns the filed TaxReturn."""
    filer = filer_headers or new_reviewer_headers()
    current = get_success_data(api_client.get_return(return_id, filer))
    payload_version = current["version"]
    return get_success_data(api_client.file_return(
        return_id, payload_version, filer))


def setup_filed_return(event_overrides=None, submitter_headers=None,
                       filer_headers=None, **scenario_kwargs):
    """Full lifecycle through filing: active registration + one RATED event +
    submit + file. Returns (ctx, event, filed_return)."""
    ctx, ev, ret = setup_return_with_rated_event(
        event_overrides=event_overrides, **scenario_kwargs)
    submitter = submitter_headers or new_analyst_headers()
    get_success_data(api_client.submit_return(ret["id"], submitter))
    filed = file_return(ret["id"], filer_headers=filer_headers)
    return ctx, ev, filed


def open_amendment(parent_return_id, add_event_ids=None, headers=None):
    """Open a DRAFT amendment of a FILED return (reads the parent's current
    version for the optimistic-concurrency field). Returns the amendment."""
    hdrs = headers or new_analyst_headers()
    parent = get_success_data(api_client.get_return(parent_return_id, hdrs))
    payload = {"expected_return_version": parent["version"]}
    if add_event_ids:
        payload["add_event_ids"] = list(add_event_ids)
    return get_success_data(
        api_client.amend_return(parent_return_id, payload, hdrs))


def create_claim(registration, filed_return, event_ids, claim_type="EXPORT",
                 claimed_cents=24300, justification="export docs",
                 headers=None):
    """Draft a credit claim. Returns the DRAFT CreditClaim."""
    return get_success_data(api_client.create_credit_claim(
        create_credit_claim_payload(
            registration_id=registration["id"],
            return_id=filed_return["id"],
            claim_type=claim_type,
            claimed_cents=claimed_cents,
            event_ids=list(event_ids),
            justification=justification),
        headers or new_analyst_headers()))


def submit_claim(claim_id, headers=None):
    """DRAFT -> SUBMITTED. Returns the updated CreditClaim."""
    return get_success_data(
        api_client.submit_credit_claim(claim_id, headers or new_analyst_headers()))


def approve_claim(claim_id, approved_cents, headers=None):
    """SUBMITTED -> APPROVED. Returns the updated CreditClaim."""
    return get_success_data(api_client.approve_credit_claim(
        claim_id, approved_cents, headers or new_reviewer_headers()))


def apply_claim(claim_id, headers=None):
    """APPROVED -> APPLIED. Returns the updated CreditClaim."""
    return get_success_data(
        api_client.apply_credit_claim(claim_id, headers or new_analyst_headers()))


def setup_applied_export_claim(event_overrides=None, claimed_cents=24300,
                               approved_cents=24300, **scenario_kwargs):
    """Filed EXPORT return + claim run through submit/approve/apply.
    Returns (ctx, event, filed_return, claim) with the claim APPLIED."""
    overrides = {"is_export": True}
    overrides.update(event_overrides or {})
    ctx, ev, filed = setup_filed_return(
        event_overrides=overrides, **scenario_kwargs)
    submitter = new_analyst_headers()
    approver = new_reviewer_headers()
    clm = create_claim(ctx["registration"], filed, [ev["id"]],
                       claimed_cents=claimed_cents, headers=submitter)
    submit_claim(clm["id"], headers=submitter)
    approve_claim(clm["id"], approved_cents, headers=approver)
    applied = apply_claim(clm["id"])
    return ctx, ev, filed, applied


# ---------------------------------------------------------------------------
# Tier 2/3: bonded movements
# ---------------------------------------------------------------------------
def create_movement(registration, bond, product_class, quantity_units=400,
                    headers=None, **overrides):
    """Document an INITIATED bonded movement. Returns the BondedMovement."""
    return get_success_data(api_client.create_bonded_movement(
        create_bonded_movement_payload(
            registration_id=registration["id"],
            bond_id=bond["id"],
            product_class_id=product_class["id"],
            quantity_units=quantity_units,
            **overrides),
        headers or new_analyst_headers()))


def create_dispatched_movement(registration, bond, product_class,
                               quantity_units=400, **overrides):
    """INITIATED -> IN_TRANSIT. Returns the dispatched BondedMovement."""
    mvt = create_movement(registration, bond, product_class, quantity_units,
                          **overrides)
    return get_success_data(
        api_client.dispatch_movement(mvt["id"], new_analyst_headers()))


# ---------------------------------------------------------------------------
# Tier 2: certificates
# ---------------------------------------------------------------------------
def create_certificate(registration, customer_reference="CUST-1",
                       certificate_type="RESALE",
                       valid_from="2026-03-01T00:00:00Z",
                       valid_to="2026-12-31T00:00:00Z", headers=None,
                       **overrides):
    """Create a PENDING_VERIFICATION certificate. Returns it."""
    return get_success_data(api_client.create_exemption_certificate(
        create_exemption_certificate_payload(
            registration_id=registration["id"],
            customer_reference=customer_reference,
            certificate_type=certificate_type,
            valid_from=valid_from,
            valid_to=valid_to,
            **overrides),
        headers or new_analyst_headers()))


def create_active_certificate(registration, **kwargs):
    """Create + verify. Returns the ACTIVE certificate."""
    crt = create_certificate(registration, **kwargs)
    return get_success_data(
        api_client.verify_exemption_certificate(crt["id"], new_reviewer_headers()))


# ---------------------------------------------------------------------------
# Tier 2: audit cases
# ---------------------------------------------------------------------------
def create_audit_case(registration, jurisdiction, period_start="2026-08",
                      period_end="2026-08", headers=None):
    """Open an audit case (records_hold true). Returns the OPENED AuditCase."""
    return get_success_data(api_client.create_audit_case(
        create_audit_case_payload(
            registration_id=registration["id"],
            jurisdiction_id=jurisdiction["id"],
            period_start=period_start,
            period_end=period_end),
        headers or new_auditor_headers()))


def close_audit_case_no_change(case_id):
    """Walk OPENED -> UNDER_REVIEW -> CLOSED_NO_CHANGE. Returns the case."""
    get_success_data(api_client.begin_audit_review(case_id, new_auditor_headers()))
    return get_success_data(api_client.close_audit_case(
        case_id, {"outcome": "NO_CHANGE"}, new_auditor_headers()))


# ---------------------------------------------------------------------------
# Tier 2: rate change notices
# ---------------------------------------------------------------------------
def create_validated_notice(jurisdiction, product_class, new_rate_millicents,
                            announced_effective_from, source_reference=None):
    """Record + validate a rate-change notice. Returns it (VALIDATED)."""
    ntc = get_success_data(api_client.create_rate_change_notice(
        create_rate_change_notice_payload(
            jurisdiction_id=jurisdiction["id"],
            product_class_id=product_class["id"],
            new_rate_millicents_per_unit=new_rate_millicents,
            announced_effective_from=announced_effective_from,
            source_reference=source_reference or f"BULL-{_uid()}"),
        new_analyst_headers()))
    return get_success_data(
        api_client.validate_rate_change_notice(ntc["id"], new_reviewer_headers()))


def apply_notice(notice_id, jurisdiction_id):
    """Apply a VALIDATED notice with the jurisdiction's current version.
    Returns the APPLIED notice."""
    jur = get_success_data(
        api_client.get_jurisdiction(jurisdiction_id, new_admin_headers()))
    return get_success_data(api_client.apply_rate_change_notice(
        notice_id, {"expected_jurisdiction_version": jur["version"]},
        new_admin_headers()))


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------
def list_period_deposits(registration_id, period):
    """List the period's deposit schedule (due_date ASC, created_at ASC)."""
    data, _meta = _list(api_client.list_deposits(
        new_analyst_headers(),
        params={"registration_id": registration_id, "period": period}))
    return data


def _list(response):
    """Thin wrapper: validate a 200 list envelope and return (data, meta)."""
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


def get_return_version(return_id, headers=None):
    """Read the return's current OCC version."""
    return get_success_data(
        api_client.get_return(return_id, headers or new_analyst_headers()))["version"]
