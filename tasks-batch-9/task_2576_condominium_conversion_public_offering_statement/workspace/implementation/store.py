"""In-memory registry store.

Every collection is a plain dict keyed by the record's server-minted UUID.
Nothing here is persisted to disk and nothing is seeded at import time: a
freshly booted process holds fourteen empty maps.
"""

import uuid

import clock

# --- the fourteen resource maps -------------------------------------------
projects = {}
engineering_reports = {}
major_components = {}
suitability_assessments = {}
declaration_packages = {}
units = {}
public_offering_statements = {}
pos_sections = {}
tenant_households = {}
reserve_studies = {}
initial_budgets = {}
closing_batches = {}
purchase_agreements = {}
warranty_claims = {}

ALL_MAPS = {
    "ConversionProject": projects,
    "EngineeringReport": engineering_reports,
    "MajorComponent": major_components,
    "SuitabilityAssessment": suitability_assessments,
    "DeclarationPackage": declaration_packages,
    "Unit": units,
    "PublicOfferingStatement": public_offering_statements,
    "POSSection": pos_sections,
    "TenantHousehold": tenant_households,
    "ReserveStudy": reserve_studies,
    "InitialBudget": initial_budgets,
    "ClosingBatch": closing_batches,
    "PurchaseAgreement": purchase_agreements,
    "WarrantyClaim": warranty_claims,
}

# Monotonic insertion counter.  Many records share one logical-clock instant,
# so `created_at` alone is not a stable sort key; `_seq` breaks those ties in
# insertion order, which is the order the registry minted them.
_seq = [0]

# Records already version-bumped during the current request.  Section 2.5
# makes `version` per-record and per-mutation, so a record rewritten twice by
# one cascade still advances exactly one revision.
_touched = set()


def begin_request():
    _touched.clear()


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_record(store, fields):
    """Mint a record with the four common properties of section 2.5."""
    now = clock.now()
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    _touched.add(rec["id"])
    return rec


def touch(rec):
    """Refresh `updated_at` and increment `version` by exactly one."""
    if rec is None:
        return rec
    if rec["id"] in _touched:
        rec["updated_at"] = clock.now()
        return rec
    _touched.add(rec["id"])
    rec["updated_at"] = clock.now()
    rec["version"] = rec["version"] + 1
    return rec


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def ordered(records):
    """Default collection ordering: `created_at` ascending."""
    return sorted(records, key=sort_key)


def children(store, field, value):
    return ordered([r for r in store.values() if r.get(field) == value])


def project_units(project_id):
    return children(units, "conversion_project_id", project_id)


def included_units(project_id):
    return [u for u in project_units(project_id)
            if u["declaration_status"] == "INCLUDED"]


def package_units(package_id):
    return children(units, "declaration_package_id", package_id)


def project_agreements(project_id):
    return children(purchase_agreements, "conversion_project_id", project_id)


def unit_agreements(unit_id):
    return children(purchase_agreements, "unit_id", unit_id)


def project_reports(project_id):
    return children(engineering_reports, "conversion_project_id", project_id)


def report_components(report_id):
    return children(major_components, "engineering_report_id", report_id)


def report_assessments(report_id):
    return children(suitability_assessments, "engineering_report_id", report_id)


def project_households(project_id):
    return children(tenant_households, "conversion_project_id", project_id)


def project_batches(project_id):
    return children(closing_batches, "conversion_project_id", project_id)


def project_budgets(project_id):
    return children(initial_budgets, "conversion_project_id", project_id)


def project_studies(project_id):
    return children(reserve_studies, "conversion_project_id", project_id)


def project_claims(project_id):
    return children(warranty_claims, "conversion_project_id", project_id)


def project_package(project_id):
    found = children(declaration_packages, "conversion_project_id", project_id)
    return found[0] if found else None


def project_statement(project_id):
    found = children(public_offering_statements, "conversion_project_id",
                     project_id)
    return found[0] if found else None


def statement_sections(statement_id):
    return children(pos_sections, "public_offering_statement_id", statement_id)


def batch_agreements(batch_id):
    return children(purchase_agreements, "closing_batch_id", batch_id)
