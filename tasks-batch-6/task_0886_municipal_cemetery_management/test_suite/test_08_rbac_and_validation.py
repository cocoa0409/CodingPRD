"""Authentication, authorization, body validation, and existence errors."""
from test_helpers import (
    validate_error, NON_EXISTENT_UUID,
    TEST_USERS, create_cemetery, create_plot_payload,
)

REG = TEST_USERS["registrar_headers"]
DIR = TEST_USERS["cemetery_director_headers"]
GF = TEST_USERS["grounds_foreman_headers"]


# ── Corner: validations / missing_auth_header_unauthenticated ──

def test_missing_role_header_unauthenticated(api):
    """PRD §2.1: "When the X-User-Role header is missing or does not name one of the
    recognized roles, the request is rejected with ERR_UNAUTHENTICATED."

    Design: Corner/validations/missing_auth_header_unauthenticated
    """
    res = api.create_cemetery({"name": "Ghost"}, {"Content-Type": "application/json"})
    validate_error(res, "ERR_UNAUTHENTICATED")


# ── Corner: validations / grounds_foreman_cannot_create_plot_forbidden ──

def test_grounds_foreman_cannot_create_plot(api):
    """PRD §2.1: "When the role is recognized but is not permitted to perform the
    requested operation — or, for an entity-backed role, does not own the target
    resource — the request is rejected with ERR_FORBIDDEN." Plot creation is a
    Registrar operation (PRD §3.1 / §4).

    Design: Corner/validations/grounds_foreman_cannot_create_plot_forbidden
    """
    cem = create_cemetery()
    res = api.create_plot(create_plot_payload(cem["id"]), GF)
    validate_error(res, "ERR_FORBIDDEN")


# ── Corner: entities / create_plot_missing_required_plot_type ──

def test_create_plot_missing_plot_type_validation(api):
    """PRD §2.5: "Body validation — required fields present, enum values in range,
    numeric fields non-negative or strictly positive as noted, and scheduled_end
    strictly after scheduled_start, else ERR_VALIDATION (400)." PRD §3.1: "Its
    plot_type is one of GRAVE, LAWN_CRYPT, NICHE, or MAUSOLEUM".

    Design: Corner/entities/create_plot_missing_required_plot_type
    """
    cem = create_cemetery()
    payload = create_plot_payload(cem["id"])
    del payload["plot_type"]
    res = api.create_plot(payload, REG)
    validate_error(res, "ERR_VALIDATION")


# ── Corner: entities / create_plot_bad_enum_plot_type ──

def test_create_plot_bad_enum_plot_type_validation(api):
    """PRD §2.5: "Body validation — required fields present, enum values in range,
    numeric fields non-negative or strictly positive as noted, and scheduled_end
    strictly after scheduled_start, else ERR_VALIDATION (400)." PRD §3.1: "Its
    plot_type is one of GRAVE, LAWN_CRYPT, NICHE, or MAUSOLEUM".

    Design: Corner/entities/create_plot_bad_enum_plot_type
    """
    cem = create_cemetery()
    res = api.create_plot(create_plot_payload(cem["id"], plot_type="MANSION"), REG)
    validate_error(res, "ERR_VALIDATION")


# ── Corner: entities / get_plot_nonexistent_returns_not_found ──

def test_get_nonexistent_plot_not_found(api):
    """PRD §2.5: "Existence — path identifiers and referenced foreign keys must
    resolve, checked left to right, else ERR_NOT_FOUND (404)."

    Design: Corner/entities/get_plot_nonexistent_returns_not_found
    """
    res = api.get_plot(NON_EXISTENT_UUID, REG)
    validate_error(res, "ERR_NOT_FOUND")
