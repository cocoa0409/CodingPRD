"""Pre-built role headers for every role in the PRD.

AirportAdmin is an opaque role: its X-User-ID is not tied to any persisted
entity, so the shared constant is canonical.

WildlifeBiologist, ATCController and RegulatorAgent are entity-backed roles:
ownership-gated calls MUST be made with headers built from the actual entity
id via the make_*_headers builders below. The shared constants for those
roles are safe only for tests whose outcome does not depend on the caller
owning the subject resource (e.g. 400-on-bad-payload or 404 tests).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque role — canonical shared form.
    "admin_headers": build_user_headers("test-admin-1", "AirportAdmin"),
    # Entity-backed roles — shared constants for non-ownership tests only.
    "biologist_headers": build_user_headers("test-biologist-1", "WildlifeBiologist"),
    "atc_headers": build_user_headers("test-atc-1", "ATCController"),
    "regulator_headers": build_user_headers("test-regulator-1", "RegulatorAgent"),
}


def make_biologist_headers(user_id: str) -> dict:
    """Headers for WildlifeBiologist (entity-backed). Pass the actual
    WildlifeBiologist.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "WildlifeBiologist")


def make_atc_controller_headers(user_id: str) -> dict:
    """Headers for ATCController (entity-backed). Pass the actual
    ATCController.id whenever the call is cross-facility-gated."""
    return build_user_headers(user_id, "ATCController")


def make_regulator_headers(user_id: str) -> dict:
    """Headers for RegulatorAgent (entity-backed). Pass the actual
    RegulatorAgent.id whenever the call is agency-gated."""
    return build_user_headers(user_id, "RegulatorAgent")
