"""Identity headers for every role in the PRD access-control table.

Six roles carry an opaque identity: the ``X-User-ID`` is an arbitrary operator
string and the API never resolves it to a row. Three roles are entity-backed --
``Technician`` and ``QualityInspector`` resolve to a technician row and
``Distributor`` resolves to a distributor row -- so their headers must be built
from the actual resource id created during setup. Use the ``make_*`` builders
for those three; never reuse a fixed constant on an ownership-gated call.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CHANNEL_MANAGER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DISTRIBUTOR,
    ROLE_PLANT_MANAGER,
    ROLE_PRODUCT_ENGINEER,
    ROLE_QUALITY_INSPECTOR,
    ROLE_TECHNICIAN,
    ROLE_TRAINING_ADMINISTRATOR,
    ROLE_WARRANTY_ANALYST,
)

# ─── Opaque-identity user ids ─────────────────────────────────────────────
UID_PRODUCT_ENGINEER = "u-pe-01"
UID_PRODUCT_ENGINEER_ALT = "u-pe-02"
UID_COMPLIANCE_OFFICER = "u-co-01"
UID_DOSSIER_PREPARER = "u-prep-01"
UID_ENERGY_REVIEWER = "u-rev-e"
UID_WATER_REVIEWER = "u-rev-w"
UID_PLANT_MANAGER = "u-pm-01"
UID_TRAINING_ADMIN = "u-ta-01"
UID_CHANNEL_MANAGER = "u-cm-01"
UID_WARRANTY_ANALYST = "u-wa-01"

# ─── Opaque-identity header sets ──────────────────────────────────────────
PRODUCT_ENGINEER = build_user_headers(UID_PRODUCT_ENGINEER, ROLE_PRODUCT_ENGINEER)
PRODUCT_ENGINEER_ALT = build_user_headers(
    UID_PRODUCT_ENGINEER_ALT, ROLE_PRODUCT_ENGINEER
)
COMPLIANCE_OFFICER = build_user_headers(UID_COMPLIANCE_OFFICER, ROLE_COMPLIANCE_OFFICER)
# Segregation of duties (PRD 2.10): the officer who prepares a dossier may not
# review either of its dimensions, and the two dimensions need two reviewers.
DOSSIER_PREPARER = build_user_headers(UID_DOSSIER_PREPARER, ROLE_COMPLIANCE_OFFICER)
ENERGY_REVIEWER = build_user_headers(UID_ENERGY_REVIEWER, ROLE_COMPLIANCE_OFFICER)
WATER_REVIEWER = build_user_headers(UID_WATER_REVIEWER, ROLE_COMPLIANCE_OFFICER)
PLANT_MANAGER = build_user_headers(UID_PLANT_MANAGER, ROLE_PLANT_MANAGER)
TRAINING_ADMIN = build_user_headers(UID_TRAINING_ADMIN, ROLE_TRAINING_ADMINISTRATOR)
CHANNEL_MANAGER = build_user_headers(UID_CHANNEL_MANAGER, ROLE_CHANNEL_MANAGER)
WARRANTY_ANALYST = build_user_headers(UID_WARRANTY_ANALYST, ROLE_WARRANTY_ANALYST)

TEST_USERS = {
    "product_engineer": PRODUCT_ENGINEER,
    "product_engineer_alt": PRODUCT_ENGINEER_ALT,
    "compliance_officer": COMPLIANCE_OFFICER,
    "dossier_preparer": DOSSIER_PREPARER,
    "energy_reviewer": ENERGY_REVIEWER,
    "water_reviewer": WATER_REVIEWER,
    "plant_manager": PLANT_MANAGER,
    "training_admin": TRAINING_ADMIN,
    "channel_manager": CHANNEL_MANAGER,
    "warranty_analyst": WARRANTY_ANALYST,
}


# ─── Entity-backed identity builders ──────────────────────────────────────
def make_technician_headers(technician_id: str) -> dict:
    """Headers for the Technician role, backed by a real technician row id."""
    return build_user_headers(technician_id, ROLE_TECHNICIAN)


def make_quality_inspector_headers(technician_id: str) -> dict:
    """Headers for the QualityInspector role, backed by a real technician row id."""
    return build_user_headers(technician_id, ROLE_QUALITY_INSPECTOR)


def make_distributor_headers(distributor_id: str) -> dict:
    """Headers for the Distributor role, backed by a real distributor row id."""
    return build_user_headers(distributor_id, ROLE_DISTRIBUTOR)


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary id/role pair, for undeclared-role probes."""
    return build_user_headers(user_id, role)


def headers_without_identity() -> dict:
    """A request that carries no identity headers at all (PRD 2.1)."""
    return {"Content-Type": "application/json"}
