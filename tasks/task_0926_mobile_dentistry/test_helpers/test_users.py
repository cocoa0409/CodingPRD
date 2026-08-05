"""Pre-built auth headers for each of the seven declared roles (PRD §2.1).

Identity binds differently per role:

* ``ProgramAdmin``, ``BillingSpecialist`` and ``Guardian`` carry an opaque
  ``X-User-ID`` that is never compared to a row's ``id`` — the shared constants
  below are the canonical form for them (the Guardian id is additionally matched
  against a report's ``recipient_user_id``, so tests that care pass their own).
* ``SiteCoordinator`` carries the ``id`` of the ``Site`` they coordinate.
* ``FieldDentist``, ``FieldHygienist`` and ``DentalAssistant`` each carry the
  ``id`` of the acting ``StaffMember`` record.

For the four entity-backed roles ALWAYS use the ``make_*_headers`` builders with
the real entity id. Never share one id between two distinct owners.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque identities — safe as shared constants.
    "program_admin_headers": build_user_headers("admin-operator-1", "ProgramAdmin"),
    "billing_specialist_headers": build_user_headers("billing-operator-1", "BillingSpecialist"),
    "guardian_headers": build_user_headers("guardian-user-001", "Guardian"),
    # Entity-backed identities — these constants are only for tests that never
    # reach an ownership check (e.g. a 403-at-rung-2 or 404-at-rung-3 probe).
    "site_coordinator_headers": build_user_headers("unbound-site-coordinator", "SiteCoordinator"),
    "field_dentist_headers": build_user_headers("unbound-field-dentist", "FieldDentist"),
    "field_hygienist_headers": build_user_headers("unbound-field-hygienist", "FieldHygienist"),
    "dental_assistant_headers": build_user_headers("unbound-dental-assistant", "DentalAssistant"),
}


def make_program_admin_headers(user_id: str = "admin-operator-1") -> Dict[str, str]:
    """ProgramAdmin identity is opaque and never compared to a row id."""
    return build_user_headers(user_id, "ProgramAdmin")


def make_site_coordinator_headers(site_id: str) -> Dict[str, str]:
    """SiteCoordinator: pass the id of the Site this coordinator runs."""
    return build_user_headers(site_id, "SiteCoordinator")


def make_field_dentist_headers(staff_id: str) -> Dict[str, str]:
    """FieldDentist: pass the id of the acting StaffMember record."""
    return build_user_headers(staff_id, "FieldDentist")


def make_field_hygienist_headers(staff_id: str) -> Dict[str, str]:
    """FieldHygienist: pass the id of the acting StaffMember record."""
    return build_user_headers(staff_id, "FieldHygienist")


def make_dental_assistant_headers(staff_id: str) -> Dict[str, str]:
    """DentalAssistant: pass the id of the acting StaffMember record."""
    return build_user_headers(staff_id, "DentalAssistant")


def make_billing_specialist_headers(user_id: str = "billing-operator-1") -> Dict[str, str]:
    """BillingSpecialist identity is opaque and never compared to a row id."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_guardian_headers(user_id: str) -> Dict[str, str]:
    """Guardian: pass the opaque identifier a PARENT report is addressed to."""
    return build_user_headers(user_id, "Guardian")
