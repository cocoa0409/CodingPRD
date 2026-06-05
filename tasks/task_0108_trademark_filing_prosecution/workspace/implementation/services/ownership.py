"""Ownership checks for entity-backed acting roles (validations priority 4,
PRD §2.1 / §3.8 -> ERR_NOT_RESOURCE_OWNER).

When X-User-Role is Applicant, X-User-ID is the acting Applicant.id; it must
match the resource's applicant foreign key. When X-User-Role is Attorney,
X-User-ID is the acting Attorney.id; it must match the resource's attorney_id
(attorney of record). Examiner and TTABClerk are opaque operators and are never
ownership-checked.
"""

from errors import raise_api


def check_application_owner(application, role, user_id):
    """Ownership for an operation acting on a TrademarkApplication."""
    if role == "Applicant":
        if application["applicant_id"] != user_id:
            raise_api("ERR_NOT_RESOURCE_OWNER", "Applicant does not own this application")
    elif role == "Attorney":
        if application.get("attorney_id") != user_id:
            raise_api(
                "ERR_NOT_RESOURCE_OWNER",
                "Attorney is not the attorney of record on this application",
            )


def check_proceeding_owner(proceeding, role, user_id):
    """Ownership for an operation acting on a TTABProceeding by its petitioner.

    A proceeding references an Applicant (petitioner) but no attorney. An
    attorney acts on behalf of the petitioner's marks; the PRD scopes proceeding
    ownership to the petitioner applicant. For an Attorney acting role there is
    no attorney_id on the proceeding, so the attorney is treated as permitted
    (no applicant-id to compare); the petitioner-applicant check applies only to
    the Applicant role.
    """
    if role == "Applicant":
        if proceeding["petitioner_applicant_id"] != user_id:
            raise_api(
                "ERR_NOT_RESOURCE_OWNER",
                "Applicant is not the petitioner of this proceeding",
            )
