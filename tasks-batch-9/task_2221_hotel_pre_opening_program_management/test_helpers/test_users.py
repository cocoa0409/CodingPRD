"""Role header sets for the eight pre-opening roles.

The API authenticates on ``X-User-ID`` plus ``X-User-Role`` and treats the user
identifier as opaque: no endpoint compares it to an entity identifier. Two rule
families nevertheless care *which* user acts, because they require the second
actor to differ from the first:

* punch-list verification (submitter must differ from verifier),
* soft-opening authorization (baselining director must differ from authorizer),
* system certification (the executor of the latest run must differ from the
  certifier).

For those, mint a second header set for the same role with
``headers_for(role, user_id)``.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_CONSTRUCTION_MANAGER,
    ROLE_LICENSING_COORDINATOR,
    ROLE_PROCUREMENT_MANAGER,
    ROLE_PROGRAM_DIRECTOR,
    ROLE_QUALITY_INSPECTOR,
    ROLE_SYSTEMS_INTEGRATOR,
    ROLE_TALENT_MANAGER,
)

__test__ = False  # this module holds fixtures data, not test cases

# ─── Default user identifier per role ─────────────────────────────────────────

USER_ID_PROGRAM_DIRECTOR = "pd-1"
USER_ID_CONSTRUCTION_MANAGER = "cm-1"
USER_ID_LICENSING_COORDINATOR = "lc-1"
USER_ID_SYSTEMS_INTEGRATOR = "si-1"
USER_ID_TALENT_MANAGER = "tm-1"
USER_ID_PROCUREMENT_MANAGER = "pm-1"
USER_ID_COMMERCIAL_DIRECTOR = "cd-1"
USER_ID_QUALITY_INSPECTOR = "qi-1"


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role / user identifier pair."""
    return build_user_headers(user_id, role)


# ─── One ready-made header set per role ───────────────────────────────────────

PROGRAM_DIRECTOR = headers_for(ROLE_PROGRAM_DIRECTOR, USER_ID_PROGRAM_DIRECTOR)
CONSTRUCTION_MANAGER = headers_for(
    ROLE_CONSTRUCTION_MANAGER, USER_ID_CONSTRUCTION_MANAGER
)
LICENSING_COORDINATOR = headers_for(
    ROLE_LICENSING_COORDINATOR, USER_ID_LICENSING_COORDINATOR
)
SYSTEMS_INTEGRATOR = headers_for(ROLE_SYSTEMS_INTEGRATOR, USER_ID_SYSTEMS_INTEGRATOR)
TALENT_MANAGER = headers_for(ROLE_TALENT_MANAGER, USER_ID_TALENT_MANAGER)
PROCUREMENT_MANAGER = headers_for(ROLE_PROCUREMENT_MANAGER, USER_ID_PROCUREMENT_MANAGER)
COMMERCIAL_DIRECTOR = headers_for(ROLE_COMMERCIAL_DIRECTOR, USER_ID_COMMERCIAL_DIRECTOR)
QUALITY_INSPECTOR = headers_for(ROLE_QUALITY_INSPECTOR, USER_ID_QUALITY_INSPECTOR)

# ─── Second distinct actor per duty-separated role ────────────────────────────

PROGRAM_DIRECTOR_2 = headers_for(ROLE_PROGRAM_DIRECTOR, "pd-2")
CONSTRUCTION_MANAGER_2 = headers_for(ROLE_CONSTRUCTION_MANAGER, "cm-2")
SYSTEMS_INTEGRATOR_2 = headers_for(ROLE_SYSTEMS_INTEGRATOR, "si-2")
QUALITY_INSPECTOR_2 = headers_for(ROLE_QUALITY_INSPECTOR, "qi-2")

# Named actors used by the duty-separation scenarios.
BASELINING_DIRECTOR = headers_for(ROLE_PROGRAM_DIRECTOR, "pd-baseline-1")
TEST_RUNNER_INTEGRATOR = headers_for(ROLE_SYSTEMS_INTEGRATOR, "si-runner-1")
CERTIFYING_INTEGRATOR = headers_for(ROLE_SYSTEMS_INTEGRATOR, "si-certifier-2")

# ─── Lookup tables ────────────────────────────────────────────────────────────

HEADERS_BY_ROLE: Dict[str, Dict[str, str]] = {
    ROLE_PROGRAM_DIRECTOR: PROGRAM_DIRECTOR,
    ROLE_CONSTRUCTION_MANAGER: CONSTRUCTION_MANAGER,
    ROLE_LICENSING_COORDINATOR: LICENSING_COORDINATOR,
    ROLE_SYSTEMS_INTEGRATOR: SYSTEMS_INTEGRATOR,
    ROLE_TALENT_MANAGER: TALENT_MANAGER,
    ROLE_PROCUREMENT_MANAGER: PROCUREMENT_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR: COMMERCIAL_DIRECTOR,
    ROLE_QUALITY_INSPECTOR: QUALITY_INSPECTOR,
}

ALL_ROLE_HEADERS = list(HEADERS_BY_ROLE.values())

# Requests carrying no identity headers at all.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}
