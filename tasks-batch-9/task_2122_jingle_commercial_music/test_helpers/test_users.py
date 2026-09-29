"""Pre-built role headers for every role in the PRD.

Two of the five roles are backed by persisted entities: a ClientRep sends the
acting Client's id as X-User-ID, and a Composer sends the acting Composer's id.
For those two the per-instance builders below are mandatory whenever the call
is ownership-gated. The other three roles carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Two distinct rights-desk operator identifiers: the licence a rights operator
# drafts may never be issued by that same operator.
RIGHTS_ADMIN_DRAFTER_ID = "rights-admin-alpha"
RIGHTS_ADMIN_ISSUER_ID = "rights-admin-beta"
RIGHTS_ADMIN_THIRD_ID = "rights-admin-gamma"
PRODUCER_ID = "producer-1"
AFM_STEWARD_ID = "afm-steward-1"

# Shared constants - safe for the opaque roles, and for entity-backed roles
# only in tests that do not exercise ownership.
TEST_USERS = {
    "producer_headers": build_user_headers(PRODUCER_ID, "MusicHouseProducer"),
    "client_rep_headers": build_user_headers("test-client-rep-1", "ClientRep"),
    "composer_headers": build_user_headers("test-composer-1", "Composer"),
    "rights_admin_headers": build_user_headers(RIGHTS_ADMIN_DRAFTER_ID, "RightsAdmin"),
    "rights_admin_issuer_headers": build_user_headers(RIGHTS_ADMIN_ISSUER_ID, "RightsAdmin"),
    "afm_steward_headers": build_user_headers(AFM_STEWARD_ID, "AFMSteward"),
}


def make_producer_headers(user_id: str = PRODUCER_ID) -> dict:
    """MusicHouseProducer acts under an opaque operator identifier."""
    return build_user_headers(user_id, "MusicHouseProducer")


def make_client_rep_headers(user_id: str) -> dict:
    """ClientRep is backed by a Client row: pass the acting Client's id."""
    return build_user_headers(user_id, "ClientRep")


def make_composer_headers(user_id: str) -> dict:
    """Composer is backed by a Composer row: pass the acting Composer's id."""
    return build_user_headers(user_id, "Composer")


def make_rights_admin_headers(user_id: str = RIGHTS_ADMIN_DRAFTER_ID) -> dict:
    """RightsAdmin acts under an opaque operator identifier that the deal records."""
    return build_user_headers(user_id, "RightsAdmin")


def make_afm_steward_headers(user_id: str = AFM_STEWARD_ID) -> dict:
    """AFMSteward acts under an opaque operator identifier."""
    return build_user_headers(user_id, "AFMSteward")


def make_headers(role: str, user_id: str) -> dict:
    """Free-form header builder for access-control tests."""
    return build_user_headers(user_id, role)
