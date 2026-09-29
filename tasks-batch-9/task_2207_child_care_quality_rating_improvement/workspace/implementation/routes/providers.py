"""Providers, enrollment, standing changes and staff credentials (PRD §3.1, §3.2)."""

from decimal import Decimal

from flask import Blueprint, request

import calculations as calc
import cascades
import lookups
import response
import serializers
import store
import validation as v
from auth import require
from errors import fail
from validation import body

bp = Blueprint("providers", __name__)

HELD_CLAIM_STATES = ("SUBMITTED", "APPROVED", "RECONCILE_REQUIRED")


@bp.post("/providers")
def create_provider():
    require("StateAdministrator")
    data = body()
    legal_name = v.req_str(data, "legal_name")
    license_number = v.req_str(data, "license_number")
    county_code = v.req_str(data, "county_code")
    region_code = v.req_enum(data, "region_code", v.REGION_CODES)
    licensed_capacity = v.req_int(data, "licensed_capacity", 1)
    active_staff_fte = v.req_decimal(data, "active_staff_fte", minimum=0,
                                    exclusive_min=True, max_places=2)
    weekly_cap = v.opt_decimal(data, "weekly_onsite_cap_hours", minimum=0,
                               exclusive_min=True, max_places=1,
                               default=Decimal("12"))

    for existing in store.DB.providers.values():
        if existing["license_number"] == license_number:
            fail("ERR_DUPLICATE_RESOURCE",
                 "license_number %s is already registered" % license_number)

    rec = store.base_record(
        legal_name=legal_name,
        license_number=license_number,
        county_code=county_code,
        region_code=region_code,
        licensed_capacity=licensed_capacity,
        active_staff_fte=active_staff_fte,
        weekly_onsite_cap_hours=weekly_cap,
        status="APPLIED",
        enrolled_on=None,
        current_rating_cycle_id=None,
        current_tier=None,
        credential_compliance_pct=Decimal("0"),
        reimbursement_adjustment_cents=0,
        public_listing_visible=False,
    )
    store.DB.providers[rec["id"]] = rec
    return response.created(serializers.dump("provider", rec))


@bp.get("/providers")
def list_providers():
    require("StateAdministrator", "FamilyViewer")
    records = store.sort_created(list(store.DB.providers.values()))
    status = request.args.get("status")
    if status:
        records = [r for r in records if r["status"] == status]
    county_code = request.args.get("county_code")
    if county_code:
        records = [r for r in records if r["county_code"] == county_code]
    cycle_id = request.args.get("current_rating_cycle_id")
    if cycle_id:
        records = [r for r in records if r.get("current_rating_cycle_id") == cycle_id]
    return response.paginate(records, serializers.maker("provider"))


@bp.get("/providers/<provider_id>")
def read_provider(provider_id):
    principal = require("StateAdministrator", "Provider", "Coach", "FamilyViewer")
    provider = lookups.get_provider(provider_id)
    lookups.own_provider(principal, provider)
    return response.ok(serializers.dump("provider", provider))


@bp.post("/providers/<provider_id>/enrollment-decisions")
def enrollment_decision(provider_id):
    require("StateAdministrator")
    provider = lookups.get_provider(provider_id)
    data = body()
    decision = v.req_enum(data, "decision", ["APPROVE", "DENY"])
    if provider["status"] != "APPLIED":
        fail("ERR_PROVIDER_STATE_INVALID", "the provider is not in APPLIED")
    if decision == "APPROVE":
        for other in store.DB.providers.values():
            if other["id"] != provider["id"] and \
                    other["license_number"] == provider["license_number"]:
                fail("ERR_DUPLICATE_RESOURCE", "another provider holds this license_number")
        provider["status"] = "ENROLLED"
        provider["enrolled_on"] = store.now()
        calc.refresh_credential_compliance(provider)
    else:
        provider["status"] = "WITHDRAWN"
        provider["current_tier"] = None
        provider["public_listing_visible"] = False
    store.touch(provider)
    return response.ok(serializers.dump("provider", provider))


@bp.post("/providers/<provider_id>/status-changes")
def status_change(provider_id):
    require("StateAdministrator")
    provider = lookups.get_provider(provider_id)
    data = body()
    action = v.req_enum(data, "action", ["SUSPEND", "REINSTATE", "WITHDRAW"])
    v.opt_str(data, "reason")

    if action == "SUSPEND":
        if provider["status"] != "ACTIVE":
            fail("ERR_PROVIDER_STATE_INVALID", "suspension is available only from ACTIVE")
        provider["status"] = "SUSPENDED"
        for cycle in cascades.cycles_of(provider["id"]):
            if cycle["status"] != "ACTIVE":
                continue
            cycle["_publication_before_suspension"] = cycle["publication_status"]
            cycle["publication_status"] = "SUPPRESSED"
            store.touch(cycle)
        provider["public_listing_visible"] = False
        store.touch(provider)
        cascades.suspend_provider_allocations(provider)

    elif action == "REINSTATE":
        if provider["status"] != "SUSPENDED":
            fail("ERR_PROVIDER_STATE_INVALID", "reinstatement is available only from SUSPENDED")
        cycle_id = provider.get("current_rating_cycle_id")
        cycle = store.DB.rating_cycles.get(cycle_id) if cycle_id else None
        if cycle is None or cycle["status"] != "ACTIVE":
            fail("ERR_PROVIDER_STATE_INVALID",
                 "reinstatement requires a current rating cycle still in ACTIVE")
        provider["status"] = "ACTIVE"
        prior = cycle.pop("_publication_before_suspension", None)
        cycle["publication_status"] = "PUBLISHED" if prior == "PUBLISHED" else "UNPUBLISHED"
        store.touch(cycle)
        cascades.refresh_public_listing(provider)
        store.touch(provider)
        cascades.reactivate_provider_allocations(provider)

    else:
        if provider["status"] not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_PROVIDER_STATE_INVALID",
                 "withdrawal is available only from ACTIVE or SUSPENDED")
        for claim in cascades.claims_of(provider["id"]):
            if claim["status"] in HELD_CLAIM_STATES:
                fail("ERR_PROVIDER_STATE_INVALID",
                     "the provider still holds an unsettled subsidy claim")
        provider["status"] = "WITHDRAWN"
        cascades.withdraw_provider_cycles(provider)
        provider["current_rating_cycle_id"] = None
        provider["current_tier"] = None
        provider["public_listing_visible"] = False
        store.touch(provider)

    return response.ok(serializers.dump("provider", provider))


@bp.post("/providers/<provider_id>/staff-credentials")
def create_staff_credential(provider_id):
    principal = require("Provider", "StateAdministrator")
    provider = lookups.get_provider(provider_id)
    lookups.own_provider(principal, provider)
    data = body()
    staff_registry_id = v.req_str(data, "staff_registry_id")
    role_type = v.req_enum(data, "role_type", v.ROLE_TYPES)
    credential_level = v.req_int(data, "credential_level", 1, 6)
    fte = v.req_decimal(data, "fte", minimum=0, maximum=1, exclusive_min=True, max_places=2)
    employment_status = v.opt_enum(data, "employment_status", v.EMPLOYMENT_STATUSES, "ACTIVE")

    for existing in store.DB.staff_credentials.values():
        if existing["provider_id"] == provider["id"] and \
                existing["staff_registry_id"] == staff_registry_id:
            fail("ERR_DUPLICATE_RESOURCE",
                 "staff_registry_id %s is already registered for this provider"
                 % staff_registry_id)

    rec = store.base_record(
        provider_id=provider["id"],
        staff_registry_id=staff_registry_id,
        role_type=role_type,
        credential_level=credential_level,
        fte=fte,
        employment_status=employment_status,
        registry_status="UNLINKED",
        verified_on=None,
        expires_on=None,
    )
    store.DB.staff_credentials[rec["id"]] = rec
    calc.refresh_credential_compliance(provider)
    store.touch(provider)
    return response.created(serializers.dump("staff_credential", rec))


@bp.get("/staff-credentials")
def list_staff_credentials():
    require("StateAdministrator", "Provider")
    records = store.sort_created(list(store.DB.staff_credentials.values()))
    provider_id = request.args.get("provider_id")
    if provider_id:
        records = [r for r in records if r["provider_id"] == provider_id]
    registry_status = request.args.get("registry_status")
    if registry_status:
        records = [r for r in records if r["registry_status"] == registry_status]
    role_type = request.args.get("role_type")
    if role_type:
        records = [r for r in records if r["role_type"] == role_type]
    return response.paginate(records, serializers.maker("staff_credential"))


@bp.get("/staff-credentials/<credential_id>")
def read_staff_credential(credential_id):
    principal = require("StateAdministrator", "Provider")
    cred = lookups.get_credential(credential_id)
    lookups.own_provider_id(principal, cred["provider_id"])
    return response.ok(serializers.dump("staff_credential", cred))


@bp.post("/staff-credentials/<credential_id>/registry-link")
def registry_link(credential_id):
    require("StateAdministrator")
    cred = lookups.get_credential(credential_id)
    data = body()
    registry_status = v.req_enum(data, "registry_status", v.REGISTRY_STATUSES)
    verified_on = v.opt_instant(data, "verified_on")
    expires_on = v.opt_instant(data, "expires_on")
    credential_level = v.opt_int(data, "credential_level", 1, 6)
    if registry_status == "VERIFIED" and (verified_on is None or expires_on is None):
        fail("ERR_VALIDATION", "a VERIFIED registry response requires verified_on and expires_on")

    cred["registry_status"] = registry_status
    if verified_on is not None:
        cred["verified_on"] = verified_on
    if expires_on is not None:
        cred["expires_on"] = expires_on
    if credential_level is not None:
        cred["credential_level"] = credential_level
    store.touch(cred)

    provider = store.DB.providers.get(cred["provider_id"])
    if provider is not None:
        calc.refresh_credential_compliance(provider)
        store.touch(provider)
    return response.ok(serializers.dump("staff_credential", cred))


@bp.get("/providers/<provider_id>/credential-compliance")
def credential_compliance(provider_id):
    principal = require("StateAdministrator", "Provider")
    provider = lookups.get_provider(provider_id)
    lookups.own_provider(principal, provider)
    value, qualifying, denominator = calc.compute_credential_compliance(provider)
    if calc.dec(provider.get("credential_compliance_pct")) != value:
        provider["credential_compliance_pct"] = value
        store.touch(provider)
    extra = {
        "qualifying_fte": qualifying,
        "denominator_fte": denominator,
        "credential_compliance_pct": value,
    }
    return response.ok(serializers.dump("provider", provider, extra))
