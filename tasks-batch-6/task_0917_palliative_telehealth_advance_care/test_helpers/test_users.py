"""Pre-built role headers for every role in the PRD.

Nine of the ten roles carry an opaque operator identifier in `X-User-ID` that is
not tied to any persisted row, so a shared constant per role is the canonical
form for them. `Caregiver` is different: its `X-User-ID` is the `id` of the
acting surrogate designation row, so it needs a per-instance builder.

Several rules compare one recorded operator identifier against another (a
witness may not be the attending clinician, a verifier may not be the
prescriber, the second hospice certifier may not be the first), so the
identifiers below are deliberately all distinct from one another.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import USER_IDS

TEST_USERS = {
    "intake_headers": build_user_headers(USER_IDS["INTAKE"], "IntakeCoordinator"),
    "physician_headers": build_user_headers(
        USER_IDS["PHYSICIAN"], "PalliativePhysician"
    ),
    "physician_2_headers": build_user_headers(
        USER_IDS["PHYSICIAN_2"], "PalliativePhysician"
    ),
    "nurse_headers": build_user_headers(USER_IDS["NURSE"], "PalliativeNurse"),
    "social_worker_headers": build_user_headers(
        USER_IDS["SOCIAL_WORKER"], "SocialWorker"
    ),
    "chaplain_headers": build_user_headers(USER_IDS["CHAPLAIN"], "Chaplain"),
    "hospice_director_headers": build_user_headers(
        USER_IDS["HOSPICE_DIRECTOR"], "HospiceMedicalDirector"
    ),
    "oncall_headers": build_user_headers(USER_IDS["ONCALL"], "OnCallClinician"),
    "billing_headers": build_user_headers(USER_IDS["BILLING"], "BillingSpecialist"),
    "admin_headers": build_user_headers(USER_IDS["ADMIN"], "ProgramAdmin"),
}


def make_caregiver_headers(surrogate_designation_id: str) -> dict:
    """Headers for the `Caregiver` role.

    Pass the acting surrogate designation's `id`: for this role `X-User-ID` is
    that row's identifier, not an opaque operator string.
    """
    return build_user_headers(surrogate_designation_id, "Caregiver")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary user identifier acting in an arbitrary role."""
    return build_user_headers(user_id, role)


def headers_without_role(user_id: str) -> dict:
    """Headers that deliberately omit `X-User-Role`."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_without_user_id(role: str) -> dict:
    """Headers that deliberately omit `X-User-ID`."""
    return {"X-User-Role": role, "Content-Type": "application/json"}
