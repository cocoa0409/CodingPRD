"""Pre-built role headers for every role the PRD recognises.

`CallManager`, `JuryChair`, `Registrar` and `FinanceOfficer` are opaque: their
`X-User-ID` is an operator identifier not tied to any persisted entity, so the
shared constants below are the canonical form for those roles.

`Artist` and `Juror` are entity-backed: `X-User-ID` is the `id` of the acting
`Artist` or `Juror`. Any ownership-gated call for those two roles MUST use the
per-instance builders (`make_artist_headers`, `make_juror_headers`) with the
real entity id — the shared constants are only usable where no ownership check
runs (for example, a 401/403 header test).
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers. Two distinct identities exist for the two roles
# that carry a segregation-of-duties constraint, so tests can both violate and
# satisfy it.
CALL_MANAGER_USER_ID = "cm-001"
JURY_CHAIR_A_USER_ID = "chair-a"
JURY_CHAIR_B_USER_ID = "chair-b"
REGISTRAR_USER_ID = "reg-001"
FINANCE_OFFICER_A_USER_ID = "fin-a"
FINANCE_OFFICER_B_USER_ID = "fin-b"


TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "call_manager_headers": build_user_headers(CALL_MANAGER_USER_ID, "CallManager"),
    "jury_chair_headers": build_user_headers(JURY_CHAIR_A_USER_ID, "JuryChair"),
    "jury_chair_b_headers": build_user_headers(JURY_CHAIR_B_USER_ID, "JuryChair"),
    "registrar_headers": build_user_headers(REGISTRAR_USER_ID, "Registrar"),
    "finance_officer_headers": build_user_headers(
        FINANCE_OFFICER_A_USER_ID, "FinanceOfficer"
    ),
    "finance_officer_b_headers": build_user_headers(
        FINANCE_OFFICER_B_USER_ID, "FinanceOfficer"
    ),
    # Entity-backed roles — fallback only for tests that exercise no ownership
    # check (header-absence, role-permission).
    "artist_headers": build_user_headers("artist-not-a-real-id", "Artist"),
    "juror_headers": build_user_headers("juror-not-a-real-id", "Juror"),
}


def make_artist_headers(artist_id: str) -> dict:
    """Headers for the `Artist` role. `artist_id` must be the acting artist's id."""
    return build_user_headers(artist_id, "Artist")


def make_juror_headers(juror_id: str) -> dict:
    """Headers for the `Juror` role. `juror_id` must be the acting juror's id."""
    return build_user_headers(juror_id, "Juror")


def make_call_manager_headers(user_id: str = CALL_MANAGER_USER_ID) -> dict:
    return build_user_headers(user_id, "CallManager")


def make_jury_chair_headers(user_id: str = JURY_CHAIR_A_USER_ID) -> dict:
    return build_user_headers(user_id, "JuryChair")


def make_registrar_headers(user_id: str = REGISTRAR_USER_ID) -> dict:
    return build_user_headers(user_id, "Registrar")


def make_finance_officer_headers(user_id: str = FINANCE_OFFICER_A_USER_ID) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


CALL_MANAGER = TEST_USERS["call_manager_headers"]
JURY_CHAIR_A = TEST_USERS["jury_chair_headers"]
JURY_CHAIR_B = TEST_USERS["jury_chair_b_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
FINANCE_A = TEST_USERS["finance_officer_headers"]
FINANCE_B = TEST_USERS["finance_officer_b_headers"]
