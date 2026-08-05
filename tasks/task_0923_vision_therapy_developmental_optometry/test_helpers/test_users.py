"""Pre-built role headers for every role the PRD defines.

Three roles are backed by a `Therapist` row (`Optometrist`, `VisionTherapist`,
`TherapyAssistant`) and one by a `Patient` row (`PatientUser`); for those the
`X-User-ID` must name an existing row of the backing entity, so tests MUST use
the per-instance builders with a real entity id.  `ClinicAdmin`, `FrontDesk`
and `BillingSpecialist` carry opaque operator identifiers.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — only safe for the opaque roles, and for entity-backed
# roles in tests that never reach the authorization rung's existence check.
TEST_USERS: Dict[str, Dict[str, str]] = {
    "clinic_admin_headers": build_user_headers("admin-op-1", "ClinicAdmin"),
    "front_desk_headers": build_user_headers("frontdesk-op-1", "FrontDesk"),
    "billing_specialist_headers": build_user_headers("biller-1", "BillingSpecialist"),
    # Entity-backed roles: fallback only, never for ownership-gated calls.
    "optometrist_headers": build_user_headers("optometrist-unbacked", "Optometrist"),
    "vision_therapist_headers": build_user_headers(
        "vision-therapist-unbacked", "VisionTherapist"
    ),
    "therapy_assistant_headers": build_user_headers(
        "therapy-assistant-unbacked", "TherapyAssistant"
    ),
    "patient_user_headers": build_user_headers("patient-unbacked", "PatientUser"),
}


# --- Per-instance builders (mandatory for entity-backed roles) ------------


def make_optometrist_headers(therapist_id: str) -> Dict[str, str]:
    """`Optometrist` acts as a `Therapist` row; pass that therapist's id."""
    return build_user_headers(therapist_id, "Optometrist")


def make_vision_therapist_headers(therapist_id: str) -> Dict[str, str]:
    """`VisionTherapist` acts as a `Therapist` row; pass that therapist's id."""
    return build_user_headers(therapist_id, "VisionTherapist")


def make_therapy_assistant_headers(therapist_id: str) -> Dict[str, str]:
    """`TherapyAssistant` acts as a `Therapist` row; pass that therapist's id."""
    return build_user_headers(therapist_id, "TherapyAssistant")


def make_patient_user_headers(patient_id: str) -> Dict[str, str]:
    """`PatientUser` acts as a `Patient` row; pass that patient's id."""
    return build_user_headers(patient_id, "PatientUser")


# --- Opaque-operator builders (distinct identities where the PRD compares) -


def make_clinic_admin_headers(user_id: str = "admin-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "ClinicAdmin")


def make_front_desk_headers(user_id: str = "frontdesk-op-1") -> Dict[str, str]:
    return build_user_headers(user_id, "FrontDesk")


def make_billing_specialist_headers(user_id: str = "biller-1") -> Dict[str, str]:
    """A claim's `submitted_by_user_id` is compared as a string against the
    correcting operator, so segregation tests need genuinely distinct ids."""
    return build_user_headers(user_id, "BillingSpecialist")


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role name (used for unknown-role tests)."""
    return build_user_headers(user_id, role)
