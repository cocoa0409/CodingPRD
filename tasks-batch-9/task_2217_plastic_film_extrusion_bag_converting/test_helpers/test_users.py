"""Pre-built request headers for every role the PRD declares.

All six roles are opaque identities: the ``X-User-ID`` value never has to match
any stored entity id. It does, however, matter for the two segregation-of-duties
rules, which compare the acting ``X-User-ID`` against a previously recorded one.
The ``make_*_headers`` builders exist for exactly those cases so a test can pin
a specific acting user id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Canonical user ids used by the shared setup chains.
PLANT_ADMIN_USER = "u-pa-1"
BLEND_ENGINEER_USER = "u-be-1"
BLEND_ENGINEER_USER_2 = "u-be-2"
QUALITY_MANAGER_USER = "u-qm-1"
QUALITY_MANAGER_USER_2 = "u-qm-2"
EXTRUSION_OPERATOR_USER = "u-eo-1"
PRINT_OPERATOR_USER = "u-po-1"
CONVERTING_OPERATOR_USER = "u-co-1"


TEST_USERS = {
    "plant_admin_headers": build_user_headers(PLANT_ADMIN_USER, "PlantAdmin"),
    "blend_engineer_headers": build_user_headers(BLEND_ENGINEER_USER, "BlendEngineer"),
    "quality_manager_headers": build_user_headers(QUALITY_MANAGER_USER, "QualityManager"),
    "extrusion_operator_headers": build_user_headers(EXTRUSION_OPERATOR_USER,
                                                     "ExtrusionOperator"),
    "print_operator_headers": build_user_headers(PRINT_OPERATOR_USER, "PrintOperator"),
    "converting_operator_headers": build_user_headers(CONVERTING_OPERATOR_USER,
                                                      "ConvertingOperator"),
}


def make_plant_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlantAdmin")


def make_blend_engineer_headers(user_id: str) -> dict:
    """Pin the acting user id for recipe submit/approve duty-separation tests."""
    return build_user_headers(user_id, "BlendEngineer")


def make_quality_manager_headers(user_id: str) -> dict:
    """Pin the acting user id for approve and dossier-issue duty-separation tests."""
    return build_user_headers(user_id, "QualityManager")


def make_extrusion_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ExtrusionOperator")


def make_print_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PrintOperator")


def make_converting_operator_headers(user_id: str) -> dict:
    """Pin the acting user id for seal-specimen attribution tests."""
    return build_user_headers(user_id, "ConvertingOperator")


def make_headers(user_id: str, role: str) -> dict:
    return build_user_headers(user_id, role)


HEADERS_BUILDERS = {
    "PlantAdmin": make_plant_admin_headers,
    "BlendEngineer": make_blend_engineer_headers,
    "QualityManager": make_quality_manager_headers,
    "ExtrusionOperator": make_extrusion_operator_headers,
    "PrintOperator": make_print_operator_headers,
    "ConvertingOperator": make_converting_operator_headers,
}
