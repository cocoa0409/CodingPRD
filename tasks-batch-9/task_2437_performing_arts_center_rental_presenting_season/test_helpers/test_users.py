"""Pre-built role headers for every role the PRD recognizes.

Two of the eight roles are entity-backed: when ``X-User-Role`` is
``ArtistRepresentative`` the ``X-User-ID`` header must be the acting
``Artist.id``, and when it is ``RentalClientContact`` it must be the acting
``RentalClient.id``. For those roles the shared constants below are only safe
in scenarios that never reach an ownership comparison; every ownership-gated
call must use the matching ``make_*_headers()`` builder with the real entity
id.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identities. The server records these raw values wherever an
# audit trail or a separation-of-duties rule needs one, but never compares them
# to an entity id.
CENTER_ADMIN_USER_ID = "user-admin-1"
PROGRAMMING_DIRECTOR_USER_ID = "user-pd-1"
RENTAL_MANAGER_USER_ID = "user-rm-1"
TECHNICAL_DIRECTOR_USER_ID = "user-td-1"
BOX_OFFICE_MANAGER_USER_ID = "user-bom-1"
FINANCE_CONTROLLER_USER_ID = "user-fc-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque roles — the shared constant is the canonical form.
    "center_admin_headers": build_user_headers(CENTER_ADMIN_USER_ID, "CenterAdmin"),
    "programming_director_headers": build_user_headers(
        PROGRAMMING_DIRECTOR_USER_ID, "ProgrammingDirector"
    ),
    "rental_manager_headers": build_user_headers(
        RENTAL_MANAGER_USER_ID, "RentalManager"
    ),
    "technical_director_headers": build_user_headers(
        TECHNICAL_DIRECTOR_USER_ID, "TechnicalDirector"
    ),
    "box_office_manager_headers": build_user_headers(
        BOX_OFFICE_MANAGER_USER_ID, "BoxOfficeManager"
    ),
    "finance_controller_headers": build_user_headers(
        FINANCE_CONTROLLER_USER_ID, "FinanceController"
    ),
    # Entity-backed roles — fallback only for scenarios that never reach an
    # ownership comparison (for example a role-authorization rejection).
    "artist_representative_headers": build_user_headers(
        "user-artist-x", "ArtistRepresentative"
    ),
    "rental_client_contact_headers": build_user_headers(
        "user-client-x", "RentalClientContact"
    ),
}


# ─── Per-instance builders ────────────────────────────

def make_center_admin_headers(user_id: str = CENTER_ADMIN_USER_ID) -> dict:
    """Headers for a CenterAdmin acting under the given operator identifier."""
    return build_user_headers(user_id, "CenterAdmin")


def make_programming_director_headers(
    user_id: str = PROGRAMMING_DIRECTOR_USER_ID,
) -> dict:
    """Headers for a ProgrammingDirector acting under the given operator id.

    The raw value lands in ``opened_by_user_id`` on a negotiation round and in
    ``fee_accepted_by_user_id`` on the engagement when this user accepts.
    """
    return build_user_headers(user_id, "ProgrammingDirector")


def make_rental_manager_headers(user_id: str = RENTAL_MANAGER_USER_ID) -> dict:
    """Headers for a RentalManager acting under the given operator identifier."""
    return build_user_headers(user_id, "RentalManager")


def make_technical_director_headers(user_id: str = TECHNICAL_DIRECTOR_USER_ID) -> dict:
    """Headers for a TechnicalDirector; the raw value lands in
    ``reviewed_by_user_id`` on a rider it reviews."""
    return build_user_headers(user_id, "TechnicalDirector")


def make_box_office_manager_headers(user_id: str = BOX_OFFICE_MANAGER_USER_ID) -> dict:
    """Headers for a BoxOfficeManager acting under the given operator id."""
    return build_user_headers(user_id, "BoxOfficeManager")


def make_finance_controller_headers(user_id: str = FINANCE_CONTROLLER_USER_ID) -> dict:
    """Headers for a FinanceController; the raw value lands in
    ``finalized_by_user_id`` on a settlement it finalizes and is compared
    against ``fee_accepted_by_user_id`` by the segregation-of-duties gate."""
    return build_user_headers(user_id, "FinanceController")


def make_artist_representative_headers(artist_id: str) -> dict:
    """Headers for the ArtistRepresentative of ``artist_id``.

    ``X-User-ID`` must be the acting ``Artist.id``: pass the real artist id
    whenever the call is ownership-gated.
    """
    return build_user_headers(artist_id, "ArtistRepresentative")


def make_rental_client_contact_headers(rental_client_id: str) -> dict:
    """Headers for the RentalClientContact of ``rental_client_id``.

    ``X-User-ID`` must be the acting ``RentalClient.id``: pass the real client
    id whenever the call is ownership-gated.
    """
    return build_user_headers(rental_client_id, "RentalClientContact")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary role name, including names the system does not
    recognize as one of its eight roles."""
    return build_user_headers(user_id, role)


def make_partial_headers(user_id: Optional[str] = None,
                         role: Optional[str] = None) -> dict:
    """Headers with either identity header deliberately omitted."""
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-ID"] = user_id
    if role is not None:
        headers["X-User-Role"] = role
    return headers


__all__ = [
    "TEST_USERS",
    "CENTER_ADMIN_USER_ID",
    "PROGRAMMING_DIRECTOR_USER_ID",
    "RENTAL_MANAGER_USER_ID",
    "TECHNICAL_DIRECTOR_USER_ID",
    "BOX_OFFICE_MANAGER_USER_ID",
    "FINANCE_CONTROLLER_USER_ID",
    "make_center_admin_headers",
    "make_programming_director_headers",
    "make_rental_manager_headers",
    "make_technical_director_headers",
    "make_box_office_manager_headers",
    "make_finance_controller_headers",
    "make_artist_representative_headers",
    "make_rental_client_contact_headers",
    "make_headers",
    "make_partial_headers",
]
