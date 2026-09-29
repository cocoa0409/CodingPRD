"""Identity headers for every role declared by the PRD.

The PRD splits the seven roles into two groups:

* Opaque identities -- ProgramAdmin, FireMarshal and TitleAgent authenticate
  with any non-blank ``X-User-ID``; the district never resolves the value to a
  stored row.
* Entity-backed identities -- an Inspector's ``X-User-ID`` is the Inspector's
  own id, a PropertyOwner's is the id of the Parcel they own, a Contractor's is
  the Contractor's id and a CommunityOrganizer's is the Community's id.  These
  headers can therefore only be built *after* the backing row exists, which is
  why they are exposed as functions rather than as module constants.
"""

from prd_bench_local_runner.testing import build_user_headers

# --- Role names -------------------------------------------------------------
ROLE_PROGRAM_ADMIN = "ProgramAdmin"
ROLE_FIRE_MARSHAL = "FireMarshal"
ROLE_INSPECTOR = "Inspector"
ROLE_PROPERTY_OWNER = "PropertyOwner"
ROLE_CONTRACTOR = "Contractor"
ROLE_COMMUNITY_ORGANIZER = "CommunityOrganizer"
ROLE_TITLE_AGENT = "TitleAgent"

ALL_ROLES = (
    ROLE_PROGRAM_ADMIN,
    ROLE_FIRE_MARSHAL,
    ROLE_INSPECTOR,
    ROLE_PROPERTY_OWNER,
    ROLE_CONTRACTOR,
    ROLE_COMMUNITY_ORGANIZER,
    ROLE_TITLE_AGENT,
)

ENTITY_BACKED_ROLES = (
    ROLE_INSPECTOR,
    ROLE_PROPERTY_OWNER,
    ROLE_CONTRACTOR,
    ROLE_COMMUNITY_ORGANIZER,
)

OPAQUE_ROLES = (ROLE_PROGRAM_ADMIN, ROLE_FIRE_MARSHAL, ROLE_TITLE_AGENT)

# --- Opaque identities ------------------------------------------------------
PROGRAM_ADMIN_ID = "admin-user-001"
FIRE_MARSHAL_ID = "marshal-user-001"
TITLE_AGENT_ID = "title-agent-001"

PROGRAM_ADMIN_HEADERS = build_user_headers(PROGRAM_ADMIN_ID, ROLE_PROGRAM_ADMIN)
FIRE_MARSHAL_HEADERS = build_user_headers(FIRE_MARSHAL_ID, ROLE_FIRE_MARSHAL)
TITLE_AGENT_HEADERS = build_user_headers(TITLE_AGENT_ID, ROLE_TITLE_AGENT)

# A second marshal identity, needed whenever a test must prove that the
# separation-of-duties rule keys on the recorded verifier and not on the role.
SECOND_FIRE_MARSHAL_ID = "marshal-user-002"
SECOND_FIRE_MARSHAL_HEADERS = build_user_headers(
    SECOND_FIRE_MARSHAL_ID, ROLE_FIRE_MARSHAL
)


def make_program_admin_headers(user_id=PROGRAM_ADMIN_ID):
    """ProgramAdmin headers; the id is opaque to the district."""
    return build_user_headers(user_id, ROLE_PROGRAM_ADMIN)


def make_fire_marshal_headers(user_id=FIRE_MARSHAL_ID):
    """FireMarshal headers; the id is opaque to the district."""
    return build_user_headers(user_id, ROLE_FIRE_MARSHAL)


def make_title_agent_headers(user_id=TITLE_AGENT_ID):
    """TitleAgent headers; the id is opaque to the district."""
    return build_user_headers(user_id, ROLE_TITLE_AGENT)


# --- Entity-backed identities ----------------------------------------------
def make_inspector_headers(inspector_id):
    """Inspector headers carrying the Inspector row's own id."""
    return build_user_headers(str(inspector_id), ROLE_INSPECTOR)


def make_property_owner_headers(parcel_id):
    """PropertyOwner headers carrying the id of the Parcel they own."""
    return build_user_headers(str(parcel_id), ROLE_PROPERTY_OWNER)


def make_contractor_headers(contractor_id):
    """Contractor headers carrying the Contractor row's own id."""
    return build_user_headers(str(contractor_id), ROLE_CONTRACTOR)


def make_community_organizer_headers(community_id):
    """CommunityOrganizer headers carrying the id of the Community they run."""
    return build_user_headers(str(community_id), ROLE_COMMUNITY_ORGANIZER)


def make_headers(role, user_id):
    """Build headers for an arbitrary role/id pair."""
    return build_user_headers(str(user_id), role)


# --- Malformed identities ---------------------------------------------------
def blank_headers():
    """Headers whose identity values are present but blank."""
    return {"X-User-ID": "", "X-User-Role": "", "Content-Type": "application/json"}


def no_headers():
    """Headers with no identity at all."""
    return {"Content-Type": "application/json"}


UNKNOWN_ROLE = "Auditor"


def unknown_role_headers(user_id="ghost-user-001"):
    """Headers naming a role the PRD never declares."""
    return build_user_headers(user_id, UNKNOWN_ROLE)
