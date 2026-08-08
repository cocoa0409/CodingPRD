"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before each test.
Setup calls use get_success_data (lenient) so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating an entity_backed actor (Landlord, Tenant,
HearingOfficer), any ownership-gated call uses make_<role>_headers(actor["id"]).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_landlord_payload, create_tenant_payload, create_hearing_officer_payload,
    create_aga_payload, create_unit_payload, create_registration_payload,
    create_rent_adjustment_payload, create_tenancy_payload, create_petition_payload,
    create_hearing_payload, create_service_claim_payload, create_buyout_payload,
    create_exemption_payload, create_penalty_payload,
)
from .test_users import (
    TEST_USERS, make_landlord_headers, make_tenant_headers,
    make_hearing_officer_headers, make_clerk_headers, make_compliance_officer_headers,
)

CLERK = TEST_USERS["clerk_headers"]


# --------------------------------------------------------------------------
# Clock
# --------------------------------------------------------------------------
def set_clock(api, iso: str):
    """Advance the server logical clock to the supplied instant."""
    return get_success_data(api.set_clock({"to_iso8601": iso}, CLERK))


# --------------------------------------------------------------------------
# Tier 0: single-actor creation
# --------------------------------------------------------------------------
def create_landlord(api, **overrides) -> dict:
    return get_success_data(api.create_landlord(create_landlord_payload(**overrides), CLERK))


def create_tenant(api, **overrides) -> dict:
    return get_success_data(api.create_tenant(create_tenant_payload(**overrides), CLERK))


def create_officer(api, **overrides) -> dict:
    return get_success_data(api.create_hearing_officer(create_hearing_officer_payload(**overrides), CLERK))


def publish_aga(api, effective_year: int, aga_pct: float, **overrides) -> dict:
    return get_success_data(api.create_aga_determination(
        create_aga_payload(effective_year, aga_pct, **overrides), CLERK))


def create_unit(api, landlord_id: str, **overrides) -> dict:
    """Create a unit owned by landlord_id, acting as that landlord."""
    return get_success_data(api.create_unit(
        create_unit_payload(landlord_id, **overrides),
        make_landlord_headers(landlord_id)))


def create_active_tenancy(api, unit_id: str, tenant_id: str, landlord_id: str,
                          start_date: str = "2026-04-01", **overrides) -> dict:
    """Create an ACTIVE tenancy on a stabilized unit, acting as the owning landlord."""
    return get_success_data(api.create_tenancy(
        create_tenancy_payload(unit_id, tenant_id, start_date, **overrides),
        make_landlord_headers(landlord_id)))


# --------------------------------------------------------------------------
# Tier 1: landlord + unit
# --------------------------------------------------------------------------
def setup_landlord_and_unit(api, base_rent_cents: int = 300000, bedrooms: int = 2,
                            **unit_overrides) -> dict:
    """Landlord + STABILIZED unit. Returns dict(landlord, unit, landlord_id, unit_id)."""
    landlord = create_landlord(api)
    unit = create_unit(api, landlord["id"], base_rent_cents=base_rent_cents,
                       bedrooms=bedrooms, **unit_overrides)
    return {
        "landlord": landlord,
        "unit": unit,
        "landlord_id": landlord["id"],
        "unit_id": unit["id"],
    }


def setup_unit_with_active_tenancy(api, base_rent_cents: int = 300000, bedrooms: int = 2,
                                   start_date: str = "2026-04-01",
                                   end_date: str = None) -> dict:
    """Landlord + tenant + STABILIZED unit + ACTIVE tenancy.
    Returns dict(landlord, tenant, unit, tenancy, *_id)."""
    base = setup_landlord_and_unit(api, base_rent_cents=base_rent_cents, bedrooms=bedrooms)
    tenant = create_tenant(api)
    overrides = {}
    if end_date is not None:
        overrides["end_date"] = end_date
    tenancy = create_active_tenancy(api, base["unit_id"], tenant["id"],
                                    base["landlord_id"], start_date=start_date, **overrides)
    base.update({
        "tenant": tenant,
        "tenant_id": tenant["id"],
        "tenancy": tenancy,
        "tenancy_id": tenancy["id"],
    })
    return base


# --------------------------------------------------------------------------
# Tier 2: rent-adjustment banking setup
# --------------------------------------------------------------------------
def setup_unit_with_banked_headroom(api, base_rent_cents: int = 300000) -> dict:
    """Landlord + unit + AGA 2025(0.05)/2026(0.03) published; a 2025 zero-increase
    adjustment banks the full 0.05 headroom (banked_pct == 0.05, version now 2).

    Returns dict(landlord, unit, landlord_id, unit_id, unit_after) where unit_after
    reflects the post-2025-adjustment state (version 2, banked_pct 0.05)."""
    landlord = create_landlord(api)
    publish_aga(api, 2025, 0.05)
    publish_aga(api, 2026, 0.03)
    unit = create_unit(api, landlord["id"], base_rent_cents=base_rent_cents, bedrooms=2)
    lheaders = make_landlord_headers(landlord["id"])
    unit_after = get_success_data(api.create_rent_adjustment(
        unit["id"],
        create_rent_adjustment_payload("2025-06-01", base_rent_cents, False, unit["version"]),
        lheaders))
    return {
        "landlord": landlord,
        "unit": unit,
        "landlord_id": landlord["id"],
        "unit_id": unit["id"],
        "unit_after": unit_after,
    }


# --------------------------------------------------------------------------
# Tier 3: petitions and hearings
# --------------------------------------------------------------------------
def setup_petition_under_review(api, petition_type: str, base_rent_cents: int = 300000,
                                bedrooms: int = 2, petition_fields: dict = None) -> dict:
    """Landlord + officer + unit + petition walked DRAFT -> SUBMITTED -> UNDER_REVIEW.
    Returns dict(landlord, officer, unit, petition, *_id)."""
    petition_fields = petition_fields or {}
    landlord = create_landlord(api)
    officer = create_officer(api)
    unit = create_unit(api, landlord["id"], base_rent_cents=base_rent_cents, bedrooms=bedrooms)
    lheaders = make_landlord_headers(landlord["id"])
    oheaders = make_hearing_officer_headers(officer["id"])
    petition = get_success_data(api.create_petition(
        create_petition_payload(unit["id"], landlord["id"], petition_type, **petition_fields),
        lheaders))
    get_success_data(api.submit_petition(petition["id"], lheaders))
    get_success_data(api.review_petition(petition["id"], oheaders))
    return {
        "landlord": landlord,
        "officer": officer,
        "unit": unit,
        "petition": petition,
        "landlord_id": landlord["id"],
        "officer_id": officer["id"],
        "unit_id": unit["id"],
        "petition_id": petition["id"],
    }


def setup_petition_hearing_scheduled(api, petition_type: str, base_rent_cents: int = 300000,
                                     bedrooms: int = 2, petition_fields: dict = None,
                                     scheduled_start: str = "2026-06-10T10:00:00Z",
                                     scheduled_end: str = "2026-06-10T11:00:00Z") -> dict:
    """Petition walked to HEARING_SCHEDULED with a SCHEDULED hearing.
    Returns dict(..., hearing, hearing_id)."""
    ctx = setup_petition_under_review(api, petition_type, base_rent_cents=base_rent_cents,
                                      bedrooms=bedrooms, petition_fields=petition_fields)
    hearing = get_success_data(api.schedule_hearing(
        ctx["petition_id"],
        create_hearing_payload(ctx["officer_id"], scheduled_start, scheduled_end),
        CLERK))
    ctx["hearing"] = hearing
    ctx["hearing_id"] = hearing["id"]
    return ctx


def setup_capital_petition_hearing(api, base_rent_cents: int = 300000, bedrooms: int = 2,
                                   requested_cost_cents: int = 4800000,
                                   amortization_months: int = 120, **kw) -> dict:
    """Convenience: a CAPITAL_IMPROVEMENT petition at HEARING_SCHEDULED."""
    return setup_petition_hearing_scheduled(
        api, "CAPITAL_IMPROVEMENT", base_rent_cents=base_rent_cents, bedrooms=bedrooms,
        petition_fields={"requested_cost_cents": requested_cost_cents,
                         "amortization_months": amortization_months}, **kw)


def setup_hardship_petition_hearing(api, base_rent_cents: int = 300000, bedrooms: int = 2,
                                    requested_pct: float = 0.20, **kw) -> dict:
    """Convenience: a HARDSHIP petition at HEARING_SCHEDULED."""
    return setup_petition_hearing_scheduled(
        api, "HARDSHIP", base_rent_cents=base_rent_cents, bedrooms=bedrooms,
        petition_fields={"requested_pct": requested_pct}, **kw)


# --------------------------------------------------------------------------
# Tier 4: service claims
# --------------------------------------------------------------------------
def setup_service_claim_investigating(api, claim_type: str = "HEAT",
                                      severity: str = "SUBSTANTIAL",
                                      base_rent_cents: int = 300000) -> dict:
    """Landlord + tenant + unit + ACTIVE tenancy + officer, with a service claim
    walked OPEN -> INVESTIGATING. Returns dict(..., officer, claim, claim_id)."""
    ctx = setup_unit_with_active_tenancy(api, base_rent_cents=base_rent_cents)
    officer = create_officer(api)
    oheaders = make_hearing_officer_headers(officer["id"])
    claim = get_success_data(api.create_service_claim(
        create_service_claim_payload(ctx["unit_id"], ctx["tenant_id"], claim_type, severity),
        make_tenant_headers(ctx["tenant_id"])))
    get_success_data(api.investigate_service_claim(claim["id"], oheaders))
    ctx.update({
        "officer": officer,
        "officer_id": officer["id"],
        "claim": claim,
        "claim_id": claim["id"],
    })
    return ctx


def setup_service_claim_substantiated(api, claim_type: str = "WATER",
                                      severity: str = "SUBSTANTIAL",
                                      base_rent_cents: int = 300000) -> dict:
    """Service claim walked through to SUBSTANTIATED (rent already decreased)."""
    ctx = setup_service_claim_investigating(api, claim_type=claim_type, severity=severity,
                                            base_rent_cents=base_rent_cents)
    oheaders = make_hearing_officer_headers(ctx["officer_id"])
    claim = get_success_data(api.decide_service_claim(
        ctx["claim_id"], {"disposition": "SUBSTANTIATE"}, oheaders))
    ctx["claim"] = claim
    return ctx


# --------------------------------------------------------------------------
# Tier 5: buyouts
# --------------------------------------------------------------------------
def setup_buyout_draft(api, relocation_amount_cents: int = 1000000,
                       offer_amount_cents: int = 5000000,
                       base_rent_cents: int = 300000) -> dict:
    """Landlord + tenant + unit + ACTIVE tenancy + a DRAFT buyout.
    Returns dict(..., buyout, buyout_id)."""
    ctx = setup_unit_with_active_tenancy(api, base_rent_cents=base_rent_cents)
    buyout = get_success_data(api.create_buyout(
        create_buyout_payload(ctx["unit_id"], ctx["landlord_id"], ctx["tenant_id"],
                              offer_amount_cents, relocation_amount_cents),
        make_landlord_headers(ctx["landlord_id"])))
    ctx["buyout"] = buyout
    ctx["buyout_id"] = buyout["id"]
    return ctx


def setup_buyout_filed(api, relocation_amount_cents: int = 1000000,
                       offer_amount_cents: int = 5000000,
                       base_rent_cents: int = 300000) -> dict:
    """Buyout FILED at the default clock (filed_at 2026-05-01T00:00:00Z).
    Returns dict(..., buyout, buyout_id) where buyout reflects the FILED state."""
    ctx = setup_buyout_draft(api, relocation_amount_cents=relocation_amount_cents,
                             offer_amount_cents=offer_amount_cents,
                             base_rent_cents=base_rent_cents)
    filed = get_success_data(api.file_buyout(
        ctx["buyout_id"], {"disclosure_acknowledged": True},
        make_landlord_headers(ctx["landlord_id"])))
    ctx["buyout"] = filed
    return ctx


# --------------------------------------------------------------------------
# Tier 6: exemptions
# --------------------------------------------------------------------------
def setup_exemption_requested(api, exemption_type: str, base_rent_cents: int = 300000,
                              bedrooms: int = 2, exemption_fields: dict = None,
                              with_active_tenancy: bool = False) -> dict:
    """Landlord + unit (optionally with ACTIVE tenancy) + a REQUESTED exemption.
    Returns dict(..., exemption, exemption_id)."""
    exemption_fields = exemption_fields or {}
    if with_active_tenancy:
        ctx = setup_unit_with_active_tenancy(api, base_rent_cents=base_rent_cents, bedrooms=bedrooms)
    else:
        ctx = setup_landlord_and_unit(api, base_rent_cents=base_rent_cents, bedrooms=bedrooms)
    exemption = get_success_data(api.create_exemption(
        create_exemption_payload(ctx["unit_id"], exemption_type, **exemption_fields),
        make_landlord_headers(ctx["landlord_id"])))
    ctx["exemption"] = exemption
    ctx["exemption_id"] = exemption["id"]
    return ctx


# --------------------------------------------------------------------------
# Tier 7: penalties
# --------------------------------------------------------------------------
def assess_penalty(api, unit_id: str, landlord_id: str, penalty_type: str,
                   officer_user_id: str, **penalty_fields) -> dict:
    """Assess a penalty as a ComplianceOfficer identified by officer_user_id."""
    return get_success_data(api.create_penalty(
        create_penalty_payload(unit_id, landlord_id, penalty_type, **penalty_fields),
        make_compliance_officer_headers(officer_user_id)))
