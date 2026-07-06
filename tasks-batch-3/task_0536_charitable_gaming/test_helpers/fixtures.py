"""Composite setup helpers for multi-step Charitable Gaming test prerequisites.

Uses get_success_data() (lenient) internally so setup failures surface as clear
"Setup step failed" errors rather than confusing assertion failures.

Identity threading: after creating an Organization (OrgOfficer identity) or a
Supplier (Supplier identity), every ownership-gated call uses
make_orgofficer_headers(org_id) / make_supplier_headers(sup_id) so ownership
checks resolve to the real entity id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_organization_payload,
    create_license_payload,
    create_occasion_payload,
    report_occasion_payload,
    create_supplier_payload,
    create_equipment_payload,
)
from .test_users import (
    TEST_USERS,
    make_orgofficer_headers,
    make_supplier_headers,
)

REGULATOR = TEST_USERS["regulator_headers"]


# ─── Clock control (§2.5) ─────────────────────────────────────────────
def set_clock(iso: str):
    """Advance/set the logical clock to the given ISO instant (Regulator)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, REGULATOR))


# ─── Tier 1: Organization + License state progression ─────────────────
def create_organization(**overrides) -> dict:
    """Register an organization (Regulator). Defaults to an ELIGIBLE long-lived 501C3."""
    res = api_client.create_organization(create_organization_payload(**overrides), REGULATOR)
    return get_success_data(res)


def create_draft_license(org_id: str, **overrides) -> dict:
    """Create a DRAFT license for the org (OrgOfficer, ownership-threaded)."""
    res = api_client.create_license(
        create_license_payload(org_id, **overrides), make_orgofficer_headers(org_id)
    )
    return get_success_data(res)


def create_active_license(license_type: str = "BINGO", org_overrides=None,
                          license_overrides=None):
    """Eligible org + license created → submitted → approved (ACTIVE).

    Returns (org, license) where license is the fetched ACTIVE license.
    """
    org = create_organization(**(org_overrides or {}))
    officer = make_orgofficer_headers(org["id"])
    lic = create_draft_license(org["id"], license_type=license_type, **(license_overrides or {}))
    get_success_data(api_client.submit_license(lic["id"], officer))
    get_success_data(api_client.approve_license(lic["id"], REGULATOR))
    active = get_success_data(api_client.get_license(lic["id"], officer))
    return org, active


def create_submitted_license(license_type: str = "BINGO", org_overrides=None):
    """Org + license created → submitted (SUBMITTED, not yet approved).

    Returns (org, license).
    """
    org = create_organization(**(org_overrides or {}))
    officer = make_orgofficer_headers(org["id"])
    lic = create_draft_license(org["id"], license_type=license_type)
    get_success_data(api_client.submit_license(lic["id"], officer))
    submitted = get_success_data(api_client.get_license(lic["id"], officer))
    return org, submitted


# ─── Tier 2: Occasions ────────────────────────────────────────────────
def schedule_occasion(org_id: str, license_id: str, **overrides) -> dict:
    """Schedule a SCHEDULED occasion under a license (OrgOfficer)."""
    res = api_client.create_occasion(
        create_occasion_payload(license_id, **overrides), make_orgofficer_headers(org_id)
    )
    return get_success_data(res)


def create_held_occasion(org_id: str, license_id: str, **overrides) -> dict:
    """Schedule + hold an occasion (HELD). Returns the held occasion."""
    officer = make_orgofficer_headers(org_id)
    occ = schedule_occasion(org_id, license_id, **overrides)
    return get_success_data(api_client.hold_occasion(occ["id"], officer))


def create_reported_occasion(org_id: str, license_id: str, occasion_overrides=None,
                             report_overrides=None) -> dict:
    """Schedule + hold + report an occasion (REPORTED). Returns reported occasion."""
    officer = make_orgofficer_headers(org_id)
    occ = create_held_occasion(org_id, license_id, **(occasion_overrides or {}))
    return get_success_data(
        api_client.report_occasion(occ["id"], report_occasion_payload(**(report_overrides or {})), officer)
    )


# ─── Tier 3: Suppliers + Equipment ────────────────────────────────────
def create_registered_supplier(**overrides) -> dict:
    """Create a supplier and register it (REGISTERED). Returns the supplier."""
    sup = get_success_data(api_client.create_supplier(create_supplier_payload(**overrides), REGULATOR))
    return get_success_data(api_client.register_supplier(sup["id"], REGULATOR))


def create_registered_equipment(serial_number: str = "SN-1",
                                 equipment_type: str = "BINGO_BLOWER",
                                 supplier_overrides=None):
    """Registered supplier + one REGISTERED equipment item.

    Returns (supplier, equipment).
    """
    sup = create_registered_supplier(**(supplier_overrides or {}))
    eq = get_success_data(
        api_client.create_equipment(
            create_equipment_payload(sup["id"], equipment_type=equipment_type,
                                     serial_number=serial_number),
            make_supplier_headers(sup["id"]),
        )
    )
    return sup, eq


def create_active_allocation(org_id: str, equipment_id: str, occasion_id: str,
                             start_date: str, end_date: str) -> dict:
    """Allocate registered equipment to an occasion (ACTIVE). Returns allocation."""
    res = api_client.create_equipment_allocation(
        {
            "equipment_id": equipment_id,
            "occasion_id": occasion_id,
            "start_date": start_date,
            "end_date": end_date,
        },
        make_orgofficer_headers(org_id),
    )
    return get_success_data(res)


# ─── Helpers for reading version (OCC flows) ──────────────────────────
def get_license_version(org_id: str, license_id: str) -> int:
    lic = get_success_data(api_client.get_license(license_id, make_orgofficer_headers(org_id)))
    return lic["version"]
