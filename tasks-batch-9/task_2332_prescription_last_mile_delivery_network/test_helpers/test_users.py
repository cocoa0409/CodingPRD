"""Header builders for the five acting roles.

Four of the five roles carry an ownership claim rather than an audit label: the
``X-User-ID`` of a PharmacyOperator is the acting pharmacy's own ``id``, a
Patient's is the patient row's ``id``, a Courier's is the courier row's ``id``,
and a PlanAdministrator's is the health plan's ``id``. Tests must therefore
thread the freshly created entity's identifier into the headers rather than
reuse a fixed constant. Only NetworkOps is opaque: any identifier that matches
no stored pharmacy, patient, courier or health plan resolves to NetworkOps.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import OPS_REVIEWER, OPS_USER_A, OPS_USER_B, OPS_USER_C

Headers = Dict[str, str]


def make_pharmacy_headers(pharmacy_id: str) -> Headers:
    """Act as the dispensing site whose row id is ``pharmacy_id``."""
    return build_user_headers(pharmacy_id, "PharmacyOperator")


def make_patient_headers(patient_id: str) -> Headers:
    """Act as the recipient whose row id is ``patient_id``."""
    return build_user_headers(patient_id, "Patient")


def make_courier_headers(courier_id: str) -> Headers:
    """Act as the courier whose row id is ``courier_id``."""
    return build_user_headers(courier_id, "Courier")


def make_plan_admin_headers(health_plan_id: str) -> Headers:
    """Act as the administrator of the plan whose row id is ``health_plan_id``."""
    return build_user_headers(health_plan_id, "PlanAdministrator")


def make_ops_headers(ops_user_id: str = OPS_USER_A) -> Headers:
    """Act as a network operations user under an opaque operator identifier."""
    return build_user_headers(ops_user_id, "NetworkOps")


# Shared identities that carry no ownership claim.
TEST_USERS = {
    "ops": make_ops_headers(OPS_USER_A),
    "ops_second": make_ops_headers(OPS_USER_B),
    "ops_third": make_ops_headers(OPS_USER_C),
    "ops_reviewer": make_ops_headers(OPS_REVIEWER),
}

OPS_HEADERS = TEST_USERS["ops"]
