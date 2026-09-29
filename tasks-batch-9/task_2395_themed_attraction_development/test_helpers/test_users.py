"""Pre-built identity headers for the seven roles the system recognises.

None of the seven roles is backed by a persisted entity, so the accompanying
`X-User-ID` is an opaque operator identifier. Two workflows nevertheless compare
recorded identifiers to each other — segregation of duties on package approval
and one-ballot-per-party on value engineering — so tests must be able to mint
headers for an arbitrary operator identifier as well as use the shared ones.
"""
from prd_bench_local_runner.testing import build_user_headers

OWNER_REP_USER_ID = "u-owner-1"
CREATIVE_DIRECTOR_USER_ID = "u-cd-1"
RIDE_ENGINEER_USER_ID = "u-eng-1"
SHOW_PROGRAMMER_USER_ID = "u-prog-1"
THIRD_PARTY_REVIEWER_USER_ID = "u-tpr-1"
CONTRACTOR_PM_USER_ID = "u-cpm-1"
PROGRAM_ADMIN_USER_ID = "u-adm-1"

# A second owner identity, for workflows where the approving owner must differ
# from the submitting owner.
SECOND_OWNER_REP_USER_ID = "u-owner-2"

TEST_USERS = {
    "owner_rep_headers": build_user_headers(OWNER_REP_USER_ID, "OwnerRep"),
    "second_owner_rep_headers": build_user_headers(SECOND_OWNER_REP_USER_ID, "OwnerRep"),
    "creative_director_headers": build_user_headers(CREATIVE_DIRECTOR_USER_ID, "CreativeDirector"),
    "ride_engineer_headers": build_user_headers(RIDE_ENGINEER_USER_ID, "RideEngineer"),
    "show_programmer_headers": build_user_headers(SHOW_PROGRAMMER_USER_ID, "ShowProgrammer"),
    "third_party_reviewer_headers": build_user_headers(THIRD_PARTY_REVIEWER_USER_ID, "ThirdPartyReviewer"),
    "contractor_pm_headers": build_user_headers(CONTRACTOR_PM_USER_ID, "ContractorPM"),
    "program_admin_headers": build_user_headers(PROGRAM_ADMIN_USER_ID, "ProgramAdmin"),
}

# Headers carrying no identity at all — neither X-User-ID nor X-User-Role.
NO_IDENTITY_HEADERS = {"Content-Type": "application/json"}


def make_owner_rep_headers(user_id: str) -> dict:
    """Headers for an OwnerRep acting under a specific operator identifier."""
    return build_user_headers(user_id, "OwnerRep")


def make_creative_director_headers(user_id: str) -> dict:
    """Headers for a CreativeDirector acting under a specific operator identifier."""
    return build_user_headers(user_id, "CreativeDirector")


def make_ride_engineer_headers(user_id: str) -> dict:
    """Headers for a RideEngineer acting under a specific operator identifier."""
    return build_user_headers(user_id, "RideEngineer")


def make_show_programmer_headers(user_id: str) -> dict:
    """Headers for a ShowProgrammer acting under a specific operator identifier."""
    return build_user_headers(user_id, "ShowProgrammer")


def make_third_party_reviewer_headers(user_id: str) -> dict:
    """Headers for a ThirdPartyReviewer acting under a specific operator identifier."""
    return build_user_headers(user_id, "ThirdPartyReviewer")


def make_contractor_pm_headers(user_id: str) -> dict:
    """Headers for a ContractorPM acting under a specific operator identifier."""
    return build_user_headers(user_id, "ContractorPM")


def make_program_admin_headers(user_id: str) -> dict:
    """Headers for a ProgramAdmin acting under a specific operator identifier."""
    return build_user_headers(user_id, "ProgramAdmin")
