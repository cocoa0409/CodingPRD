"""Resource-specific not-found errors for GET-by-id on unknown UUIDs (PRD §2.4).

Each resource type maps to its own *_NOT_FOUND code; the shared rule is quoted
once per test and the resource-specific fragment names the exact code asserted.
"""
from test_helpers import validate_error, TEST_USERS

ANALYST = TEST_USERS["analyst_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


def test_get_unknown_homeowner_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... a homeowner
    ERR_HOMEOWNER_NOT_FOUND".

    Design: Corner/errors/homeowner_get_nonexistent_returns_not_found
    """
    validate_error(api.get_homeowner(NON_EXISTENT, ANALYST), "ERR_HOMEOWNER_NOT_FOUND", 404)


def test_get_unknown_valuation_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... a valuation
    ERR_VALUATION_NOT_FOUND".

    Design: Corner/errors/valuation_get_nonexistent_returns_not_found
    """
    validate_error(api.get_valuation(NON_EXISTENT, ANALYST), "ERR_VALUATION_NOT_FOUND", 404)


def test_get_unknown_appraiser_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... an appraiser
    ERR_APPRAISER_NOT_FOUND".

    Design: Corner/errors/appraiser_get_nonexistent_returns_not_found
    """
    validate_error(api.get_appraiser(NON_EXISTENT, ANALYST), "ERR_APPRAISER_NOT_FOUND", 404)


def test_get_unknown_appointment_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... an appraisal
    appointment ERR_APPOINTMENT_NOT_FOUND".

    Design: Corner/errors/appointment_get_nonexistent_returns_not_found
    """
    validate_error(api.get_appointment(NON_EXISTENT, ANALYST), "ERR_APPOINTMENT_NOT_FOUND", 404)


def test_get_unknown_offer_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... an offer
    ERR_OFFER_NOT_FOUND".

    Design: Corner/errors/offer_get_nonexistent_returns_not_found
    """
    validate_error(api.get_offer(NON_EXISTENT, ANALYST), "ERR_OFFER_NOT_FOUND", 404)


def test_get_unknown_agreement_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... an agreement
    ERR_AGREEMENT_NOT_FOUND".

    Design: Corner/errors/agreement_get_nonexistent_returns_not_found
    """
    validate_error(api.get_agreement(NON_EXISTENT, ANALYST), "ERR_AGREEMENT_NOT_FOUND", 404)


def test_get_unknown_lien_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... a lien
    ERR_LIEN_NOT_FOUND".

    Design: Corner/errors/lien_get_nonexistent_returns_not_found
    """
    validate_error(api.get_lien(NON_EXISTENT, ANALYST), "ERR_LIEN_NOT_FOUND", 404)


def test_get_unknown_inspector_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... an inspector
    ERR_INSPECTOR_NOT_FOUND".

    Design: Corner/errors/inspector_get_nonexistent_returns_not_found
    """
    validate_error(api.get_inspector(NON_EXISTENT, ANALYST), "ERR_INSPECTOR_NOT_FOUND", 404)


def test_get_unknown_inspection_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... an inspection
    ERR_INSPECTION_NOT_FOUND".

    Design: Corner/errors/inspection_get_nonexistent_returns_not_found
    """
    validate_error(api.get_inspection(NON_EXISTENT, ANALYST), "ERR_INSPECTION_NOT_FOUND", 404)


def test_get_unknown_settlement_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... a settlement
    ERR_SETTLEMENT_NOT_FOUND".

    Design: Corner/errors/settlement_get_nonexistent_returns_not_found
    """
    validate_error(api.get_settlement(NON_EXISTENT, ANALYST), "ERR_SETTLEMENT_NOT_FOUND", 404)


def test_get_unknown_dispute_not_found(api):
    """PRD §2.4: "and the first unresolved segment yields that resource's
    specific not-found error, each carrying HTTP 404: ... and a dispute
    ERR_DISPUTE_NOT_FOUND".

    Design: Corner/errors/dispute_get_nonexistent_returns_not_found
    """
    validate_error(api.get_dispute(NON_EXISTENT, ANALYST), "ERR_DISPUTE_NOT_FOUND", 404)
