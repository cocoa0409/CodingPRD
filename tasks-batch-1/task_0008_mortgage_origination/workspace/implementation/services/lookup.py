"""Entity lookup helpers — raise scaffold-defined errors."""
from __future__ import annotations

from typing import Any

import db
from errors import (
    ApiError,
    ERR_APPLICANT_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_SUBRESOURCE_NOT_FOUND,
)


def get_application_or_404(application_id: str) -> dict[str, Any]:
    app = db.loan_applications.get(application_id)
    if app is None:
        raise ApiError(ERR_APPLICATION_NOT_FOUND, "Loan application not found.")
    return app


def get_applicant_or_404(applicant_id: str) -> dict[str, Any]:
    a = db.applicants.get(applicant_id)
    if a is None:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "Applicant not found.")
    return a


def get_application_by_body_or_404(application_id: str) -> dict[str, Any]:
    """When application_id is referenced from a body (vs URL path)."""
    app = db.loan_applications.get(application_id)
    if app is None:
        raise ApiError(ERR_APPLICANT_NOT_FOUND, "Referenced application_id does not exist.")
    return app


def get_subresource_or_404(store: dict[str, Any], resource_id: str) -> dict[str, Any]:
    obj = store.get(resource_id)
    if obj is None:
        raise ApiError(ERR_SUBRESOURCE_NOT_FOUND, "Sub-resource not found.")
    return obj
