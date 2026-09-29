"""Caller identities and the header builders that thread them.

Four of the six roles are opaque operator identities: any stable user id will
do, so the suite pins one apiece. The remaining two are entity-backed — the
caller's X-User-ID must be the identifier of a row that exists:

* ``PartnerDelegate`` presents the ``CoalitionPartner.id`` it speaks for.
* ``Supporter`` presents its own ``Supporter.id``.

Because those two ids are minted at runtime, ownership-gated calls must go
through the ``make_*_headers`` builders rather than the shared constants.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import (
    ROLE_CAMPAIGN_DIRECTOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_FIELD_ORGANIZER,
    ROLE_MESSAGE_STRATEGIST,
    ROLE_PARTNER_DELEGATE,
    ROLE_SUPPORTER,
)


# --------------------------------------------------------------------------
# Opaque operator user ids
# --------------------------------------------------------------------------

USER_CAMPAIGN_DIRECTOR = "u_dir_1"
USER_FIELD_ORGANIZER = "u_field_1"
USER_COMPLIANCE_OFFICER = "u_comp_1"
USER_MESSAGE_STRATEGIST = "u_strat_1"

# A second strategist identity, for the cases that need the author of a variant
# and the caller attempting its review to be told apart.
USER_MESSAGE_STRATEGIST_ALT = "u_strat_2"

# A caller who holds both authoring and reviewing duties, used to show that
# holding the reviewing role is not enough to review your own submission.
USER_DUAL_ROLE = "u_dual_1"

# A second director and organizer for the cases that need two operators of the
# same role to be distinguished.
USER_CAMPAIGN_DIRECTOR_ALT = "u_dir_2"
USER_FIELD_ORGANIZER_ALT = "u_field_2"
USER_COMPLIANCE_OFFICER_ALT = "u_comp_2"


TEST_USERS = {
    ROLE_CAMPAIGN_DIRECTOR: {
        "user_id": USER_CAMPAIGN_DIRECTOR,
        "role": ROLE_CAMPAIGN_DIRECTOR,
    },
    ROLE_FIELD_ORGANIZER: {
        "user_id": USER_FIELD_ORGANIZER,
        "role": ROLE_FIELD_ORGANIZER,
    },
    ROLE_COMPLIANCE_OFFICER: {
        "user_id": USER_COMPLIANCE_OFFICER,
        "role": ROLE_COMPLIANCE_OFFICER,
    },
    ROLE_MESSAGE_STRATEGIST: {
        "user_id": USER_MESSAGE_STRATEGIST,
        "role": ROLE_MESSAGE_STRATEGIST,
    },
    # Entity-backed roles have no fixed user id: the id is whichever row the
    # caller owns, so these entries carry a placeholder that tests must not
    # send. Use make_partner_delegate_headers / make_supporter_headers.
    ROLE_PARTNER_DELEGATE: {
        "user_id": None,
        "role": ROLE_PARTNER_DELEGATE,
    },
    ROLE_SUPPORTER: {
        "user_id": None,
        "role": ROLE_SUPPORTER,
    },
}


# --------------------------------------------------------------------------
# Header builders
# --------------------------------------------------------------------------

def make_campaign_director_headers(user_id: str = USER_CAMPAIGN_DIRECTOR) -> dict:
    """Headers for a CampaignDirector caller."""
    return build_user_headers(user_id, ROLE_CAMPAIGN_DIRECTOR)


def make_field_organizer_headers(user_id: str = USER_FIELD_ORGANIZER) -> dict:
    """Headers for a FieldOrganizer caller."""
    return build_user_headers(user_id, ROLE_FIELD_ORGANIZER)


def make_compliance_officer_headers(user_id: str = USER_COMPLIANCE_OFFICER) -> dict:
    """Headers for a ComplianceOfficer caller."""
    return build_user_headers(user_id, ROLE_COMPLIANCE_OFFICER)


def make_message_strategist_headers(user_id: str = USER_MESSAGE_STRATEGIST) -> dict:
    """Headers for a MessageStrategist caller."""
    return build_user_headers(user_id, ROLE_MESSAGE_STRATEGIST)


def make_partner_delegate_headers(partner_id: str) -> dict:
    """Headers for the delegate of one coalition partner.

    ``partner_id`` must be the CoalitionPartner row this caller speaks for;
    presenting any other partner's id is an ownership failure.
    """
    return build_user_headers(partner_id, ROLE_PARTNER_DELEGATE)


def make_supporter_headers(supporter_id: str) -> dict:
    """Headers for one supporter acting on their own record."""
    return build_user_headers(supporter_id, ROLE_SUPPORTER)


def make_headers(role: str, user_id: str) -> dict:
    """Headers for an arbitrary role/user pairing.

    Used by the role-matrix cases that sweep every role against one endpoint.
    """
    return build_user_headers(user_id, role)


# A user id to present for a role that has no entity backing it, so that the
# role check rather than the ownership check is the one under test.
GENERIC_USER_ID = "u_generic_1"


def headers_missing_user_id(role: str) -> dict:
    """Headers carrying a role but no X-User-ID."""
    return {"X-User-Role": role, "Content-Type": "application/json"}


def headers_missing_role(user_id: str) -> dict:
    """Headers carrying a user id but no X-User-Role."""
    return {"X-User-ID": user_id, "Content-Type": "application/json"}


def headers_unrecognised_role(user_id: str = GENERIC_USER_ID,
                              role: str = "CoalitionBoss") -> dict:
    """Headers naming a role that is not one of the six the contract knows."""
    return build_user_headers(user_id, role)


NO_HEADERS: dict = {"Content-Type": "application/json"}
