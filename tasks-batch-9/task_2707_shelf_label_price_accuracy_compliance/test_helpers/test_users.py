"""Identity header builders for the six roles.

Header-based authentication: every request carries ``X-User-Role``.  The three
opaque roles (PricingAdmin, ComplianceOfficer, CustomerServiceDesk) are not
required to send ``X-User-ID`` at all, so their builders omit it entirely.  The
three entity-backed roles (StoreManager, LabelAssociate, PriceAuditor) must
send the id of a real associate whose ``role_code`` corresponds to the claimed
role, so their builders take that associate id as a required argument -- every
distinct associate therefore gets a distinct ``X-User-ID``.
"""

from typing import Dict, Optional

from .constants import (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_CUSTOMER_SERVICE_DESK,
    ROLE_LABEL_ASSOCIATE,
    ROLE_PRICE_AUDITOR,
    ROLE_PRICING_ADMIN,
    ROLE_STORE_MANAGER,
)

JSON_CONTENT_TYPE = "application/json"


def _headers(role: Optional[str], user_id: Optional[str] = None) -> Dict[str, str]:
    built: Dict[str, str] = {"Content-Type": JSON_CONTENT_TYPE}
    if role is not None:
        built["X-User-Role"] = role
    if user_id is not None:
        built["X-User-ID"] = user_id
    return built


# --- Opaque roles: no X-User-ID ------------------------------------------------
def make_pricing_admin_headers() -> Dict[str, str]:
    return _headers(ROLE_PRICING_ADMIN)


def make_compliance_officer_headers() -> Dict[str, str]:
    return _headers(ROLE_COMPLIANCE_OFFICER)


def make_customer_service_desk_headers() -> Dict[str, str]:
    return _headers(ROLE_CUSTOMER_SERVICE_DESK)


# --- Entity-backed roles: X-User-ID names the acting associate ----------------
def make_store_manager_headers(associate_id: str) -> Dict[str, str]:
    """Headers for a StoreManager acting as the associate ``associate_id``."""
    return _headers(ROLE_STORE_MANAGER, associate_id)


def make_label_associate_headers(associate_id: str) -> Dict[str, str]:
    """Headers for a LabelAssociate acting as the associate ``associate_id``."""
    return _headers(ROLE_LABEL_ASSOCIATE, associate_id)


def make_price_auditor_headers(associate_id: str) -> Dict[str, str]:
    """Headers for a PriceAuditor acting as the associate ``associate_id``."""
    return _headers(ROLE_PRICE_AUDITOR, associate_id)


# --- Deliberately malformed identities ---------------------------------------
def make_headers_without_role(associate_id: Optional[str] = None) -> Dict[str, str]:
    """No ``X-User-Role`` at all."""
    return _headers(None, associate_id)


def make_headers_with_empty_role() -> Dict[str, str]:
    """``X-User-Role`` present but empty."""
    return {"Content-Type": JSON_CONTENT_TYPE, "X-User-Role": ""}


def make_entity_backed_headers_without_user_id(role: str) -> Dict[str, str]:
    """An entity-backed role claim carrying no ``X-User-ID``."""
    return _headers(role)


def make_headers_with_empty_user_id(role: str) -> Dict[str, str]:
    """An entity-backed role claim whose ``X-User-ID`` is empty."""
    return {"Content-Type": JSON_CONTENT_TYPE, "X-User-Role": role, "X-User-ID": ""}


def make_headers(role: str, associate_id: Optional[str] = None) -> Dict[str, str]:
    """Generic builder: any role, optionally acting as ``associate_id``."""
    return _headers(role, associate_id)


def make_unknown_role_headers(role_name: str = "RegionalDirector") -> Dict[str, str]:
    """A role spelling that is not one of the six declared roles."""
    return _headers(role_name)
