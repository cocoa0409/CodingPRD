"""Single-resource reads against the one UUID the service never mints: each of the
twelve entities must answer with its own not-found code rather than a shared one.
"""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    make_admin_headers,
    set_clock,
    validate_error,
)

CLOCK_START = "2026-08-01T00:00:00Z"


def test_reading_an_unminted_facility_names_the_facility_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_FACILITY_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/facility_get_with_an_unminted_id_returns_facility_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_facility(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.FACILITY_NOT_FOUND, 404)


def test_reading_an_unminted_supplier_names_the_supplier_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_SUPPLIER_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/supplier_get_with_an_unminted_id_returns_supplier_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_supplier(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.SUPPLIER_NOT_FOUND, 404)


def test_reading_an_unminted_supplier_document_names_the_supplier_document_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_SUPPLIER_DOCUMENT_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/supplier_document_get_with_an_unminted_id_returns_document_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_supplier_document(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.SUPPLIER_DOCUMENT_NOT_FOUND, 404)


def test_reading_an_unminted_ingredient_names_the_ingredient_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_INGREDIENT_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/ingredient_get_with_an_unminted_id_returns_ingredient_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_ingredient(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.INGREDIENT_NOT_FOUND, 404)


def test_reading_an_unminted_product_names_the_product_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_PRODUCT_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/product_get_with_an_unminted_id_returns_product_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_product(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.PRODUCT_NOT_FOUND, 404)


def test_reading_an_unminted_formula_line_names_the_formula_line_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_PRODUCT_INGREDIENT_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/product_ingredient_get_with_an_unminted_id_returns_link_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_product_ingredient(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.PRODUCT_INGREDIENT_NOT_FOUND, 404)


def test_reading_an_unminted_lot_test_names_the_lot_test_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_LOT_TEST_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/lot_test_get_with_an_unminted_id_returns_lot_test_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_lot_test(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.LOT_TEST_NOT_FOUND, 404)


def test_reading_an_unminted_audit_names_the_audit_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_AUDIT_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/audit_get_with_an_unminted_id_returns_audit_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_audit(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.AUDIT_NOT_FOUND, 404)


def test_reading_an_unminted_certificate_names_the_certificate_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_CERTIFICATE_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/certificate_get_with_an_unminted_id_returns_certificate_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_certificate(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.CERTIFICATE_NOT_FOUND, 404)


def test_reading_an_unminted_nonconformance_names_the_nonconformance_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_NONCONFORMANCE_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/nonconformance_get_with_an_unminted_id_returns_nonconformance_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_nonconformance(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.NONCONFORMANCE_NOT_FOUND, 404)


def test_reading_an_unminted_complaint_names_the_complaint_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_COMPLAINT_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/consumer_complaint_get_with_an_unminted_id_returns_complaint_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_complaint(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.COMPLAINT_NOT_FOUND, 404)


def test_reading_an_unminted_change_notification_names_the_change_notification_in_the_error(api):
    """A read of an id that was never minted answers 404 with
    ERR_CHANGE_NOTIFICATION_NOT_FOUND rather than a generic code.

    PRD: "**Path existence.** Every templated identifier in the URL resolves to a live
    row, checked strictly left to right so that the leftmost unresolvable segment decides
    the answer."
    PRD: "The error is the not-found code of the entity that failed to resolve:
    `ERR_APPLICANT_NOT_FOUND`, `ERR_FACILITY_NOT_FOUND`, `ERR_SUPPLIER_NOT_FOUND`,
    `ERR_SUPPLIER_DOCUMENT_NOT_FOUND`, `ERR_INGREDIENT_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_PRODUCT_INGREDIENT_NOT_FOUND`,
    `ERR_LOT_TEST_NOT_FOUND`, `ERR_AUDIT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_NONCONFORMANCE_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND` or
    `ERR_CHANGE_NOTIFICATION_NOT_FOUND`, each carrying HTTP 404."

    Design: Corner/entities/change_notification_get_with_an_unminted_id_returns_notification_not_found
    """
    set_clock(api, CLOCK_START)

    response = api.get_change_notification(NON_EXISTENT_UUID, make_admin_headers())
    validate_error(response, ApiErrorId.CHANGE_NOTIFICATION_NOT_FOUND, 404)
