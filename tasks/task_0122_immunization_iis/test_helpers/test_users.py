"""Pre-built role headers for every role in PRD §2.1.

PRD §2.1: "For all four roles, X-User-ID is an opaque operator
identifier and is not the id of any persisted entity in the system.
The server does not compare X-User-ID to any entity's id."

All four roles are OPAQUE - shared TEST_USERS headers are canonical
for general use.

EXCEPTION - Segregation of duties on AdverseEvent (PRD §3.9):
"the acting X-User-ID must not equal the administering_clinician_id
recorded on the referenced dose. A self-review or self-submission
yields ERR_SOD_VIOLATION."

The shared default constants for ProviderClinician and
ReviewingClinician are deliberately DISTINCT so that the SoD check
passes by default in routine tests. Tests that need a specific
clinician id (to satisfy or provoke the SoD check) MUST mint headers
via make_provider_clinician_headers / make_reviewing_clinician_headers
with the explicit id.

PRD §3.3 records the X-User-ID of the administering ProviderClinician
on the dose as administering_clinician_id (input field on the
schedule-dose payload). The fixtures that schedule a dose must pass
the same clinician id into both the schedule payload's
administering_clinician_id AND the X-User-Role header (so that future
administer calls can be performed by that same clinician).
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers - PRD §2.1.
# All four roles are opaque, but we pre-mint distinct ids so the SoD
# pair (administering vs reviewing clinician) starts off non-colliding.
# ---------------------------------------------------------------------------
PROVIDER_CLINICIAN_ID = "provider-clinician-001"
PROVIDER_CLINICIAN_ID_ALT = "provider-clinician-002"
REVIEWING_CLINICIAN_ID = "reviewing-clinician-001"
REVIEWING_CLINICIAN_ID_ALT = "reviewing-clinician-002"
SCHOOL_REGISTRAR_ID = "school-registrar-001"
PUBLIC_HEALTH_OFFICER_ID = "public-health-officer-001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # ProviderClinician — PRD §2.1: schedules doses, administers,
    # records allergies, reports AEs.
    "provider_clinician_headers": build_user_headers(
        PROVIDER_CLINICIAN_ID, "ProviderClinician",
    ),
    "provider_clinician_headers_alt": build_user_headers(
        PROVIDER_CLINICIAN_ID_ALT, "ProviderClinician",
    ),
    # ReviewingClinician — PRD §2.1: distinct from administering
    # clinician (SoD); reviews and submits AEs to VAERS.
    "reviewing_clinician_headers": build_user_headers(
        REVIEWING_CLINICIAN_ID, "ReviewingClinician",
    ),
    "reviewing_clinician_headers_alt": build_user_headers(
        REVIEWING_CLINICIAN_ID_ALT, "ReviewingClinician",
    ),
    # SchoolRegistrar — PRD §2.1: manages school certificates.
    "school_registrar_headers": build_user_headers(
        SCHOOL_REGISTRAR_ID, "SchoolRegistrar",
    ),
    # PublicHealthOfficer — PRD §2.1: manages products, lots, recalls,
    # schedule rules, provider orgs; also drives the test-only
    # clock-advance and vaers-ack endpoints (PRD §2.10).
    "public_health_officer_headers": build_user_headers(
        PUBLIC_HEALTH_OFFICER_ID, "PublicHealthOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders.
#
# Although all four roles are "opaque" per PRD §2.1, the SoD check
# (PRD §3.9) compares the reviewing clinician's X-User-ID to the
# administering_clinician_id recorded on the dose. To PROVOKE the SoD
# violation a test must mint reviewing headers with the same id used
# for the dose's administering_clinician_id, and to AVOID it routine
# tests must use a distinct id. These per-instance builders make that
# explicit at call sites.
# ---------------------------------------------------------------------------
def make_provider_clinician_headers(user_id: str) -> Dict[str, str]:
    """For ProviderClinician (PRD §2.1 - opaque). Pass an explicit
    operator id - mandatory when a downstream AdverseEvent will check
    SoD against the dose's administering_clinician_id.

    PRD §3.3: "supplying a payload containing vaccine_product_id,
    lot_id, provider_organization_id, and administering_clinician_id
    (the opaque identifier of the clinician who will give the
    injection)."
    """
    return build_user_headers(user_id, "ProviderClinician")


def make_reviewing_clinician_headers(user_id: str) -> Dict[str, str]:
    """For ReviewingClinician (PRD §2.1 - opaque). Pass an explicit
    operator id whenever the test cares about SoD.

    PRD §3.9: "the acting X-User-ID must not equal the
    administering_clinician_id recorded on the referenced dose."

    To PROVOKE ERR_SOD_VIOLATION, pass the dose's
    administering_clinician_id as user_id; to satisfy SoD pass any
    other non-empty id.
    """
    return build_user_headers(user_id, "ReviewingClinician")


def make_school_registrar_headers(user_id: str) -> Dict[str, str]:
    """For SchoolRegistrar (PRD §2.1 - opaque). Any non-empty id."""
    return build_user_headers(user_id, "SchoolRegistrar")


def make_public_health_officer_headers(user_id: str) -> Dict[str, str]:
    """For PublicHealthOfficer (PRD §2.1 - opaque). Any non-empty id."""
    return build_user_headers(user_id, "PublicHealthOfficer")


__all__ = [
    "PROVIDER_CLINICIAN_ID",
    "PROVIDER_CLINICIAN_ID_ALT",
    "REVIEWING_CLINICIAN_ID",
    "REVIEWING_CLINICIAN_ID_ALT",
    "SCHOOL_REGISTRAR_ID",
    "PUBLIC_HEALTH_OFFICER_ID",
    "TEST_USERS",
    "make_provider_clinician_headers",
    "make_reviewing_clinician_headers",
    "make_school_registrar_headers",
    "make_public_health_officer_headers",
]
