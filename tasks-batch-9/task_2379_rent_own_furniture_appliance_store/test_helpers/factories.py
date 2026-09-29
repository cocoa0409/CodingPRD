"""Request-body builders. Every payload here is a literal the tests can reason about.

Nothing in this module talks to the API; it only shapes bodies. Optional fields
are omitted rather than sent as null wherever the API declares a default, so that
tests which exercise a declared default really do omit the field.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    AUSTIN_MAIN,
    MN_RULE,
    NV_RULE,
    SOFA_CASH_PRICE_CENTS,
    SOFA_MODEL,
    TX_RULE,
    WASHER_CASH_PRICE_CENTS,
    WASHER_MODEL,
    Category,
    Channel,
    CrewStatus,
    Decision,
    Outcome,
    Relationship,
    ReturnReason,
    ServiceType,
    TermType,
)

JsonDict = Dict[str, Any]


# ---------------------------------------------------------------------------
# Statutory rules
# ---------------------------------------------------------------------------


def tx_rule_payload(**overrides: Any) -> JsonDict:
    """The Texas statutory profile."""
    return dict(TX_RULE, **overrides)


def mn_rule_payload(**overrides: Any) -> JsonDict:
    """The Minnesota statutory profile."""
    return dict(MN_RULE, **overrides)


def nv_rule_payload(**overrides: Any) -> JsonDict:
    """The Nevada statutory profile."""
    return dict(NV_RULE, **overrides)


def rule_payload_for(state_code: str, **overrides: Any) -> JsonDict:
    """A profile keyed by state code, defaulting to the Texas economics."""
    return dict(TX_RULE, state_code=state_code, **overrides)


# ---------------------------------------------------------------------------
# Stores, units and crews
# ---------------------------------------------------------------------------


def store_payload(
    name: str = AUSTIN_MAIN,
    state_code: str = "TX",
    service_bay_capacity: Optional[int] = 1,
) -> JsonDict:
    """A store opened in a jurisdiction whose statutory rule already exists."""
    payload: JsonDict = {"name": name, "state_code": state_code}
    if service_bay_capacity is not None:
        payload["service_bay_capacity"] = service_bay_capacity
    return payload


def unit_payload(
    serial_number: str,
    model_code: str = SOFA_MODEL,
    category: str = Category.FURNITURE,
    cash_price_cents: int = SOFA_CASH_PRICE_CENTS,
) -> JsonDict:
    """An inventory unit with a serial number unique among that store's units."""
    return {
        "model_code": model_code,
        "serial_number": serial_number,
        "category": category,
        "cash_price_cents": cash_price_cents,
    }


def sofa_payload(serial_number: str) -> JsonDict:
    """The canonical brand-new furniture unit at 120,000 cents."""
    return unit_payload(
        serial_number,
        model_code=SOFA_MODEL,
        category=Category.FURNITURE,
        cash_price_cents=SOFA_CASH_PRICE_CENTS,
    )


def washer_payload(serial_number: str) -> JsonDict:
    """The canonical appliance unit at 30,000 cents."""
    return unit_payload(
        serial_number,
        model_code=WASHER_MODEL,
        category=Category.APPLIANCE,
        cash_price_cents=WASHER_CASH_PRICE_CENTS,
    )


def crew_payload(
    crew_name: str,
    setup_certified: bool = True,
    status: Optional[str] = None,
) -> JsonDict:
    """A delivery crew; ``status`` is omitted to exercise its ACTIVE default."""
    payload: JsonDict = {"crew_name": crew_name, "setup_certified": setup_certified}
    if status is not None:
        payload["status"] = status
    return payload


def inactive_crew_payload(crew_name: str, setup_certified: bool = True) -> JsonDict:
    """A crew hired but not yet cleared for dispatch."""
    return crew_payload(crew_name, setup_certified, CrewStatus.INACTIVE)


# ---------------------------------------------------------------------------
# Customers and references
# ---------------------------------------------------------------------------


def customer_payload(
    full_name: str,
    email: str,
    phone: str,
    state_code: str,
    monthly_income_cents: int,
    residence_months: int,
    employer_name: Optional[str] = None,
    employer_verified: Optional[bool] = None,
    government_id_verified: Optional[bool] = None,
    in_person_contact_consent: Optional[bool] = None,
) -> JsonDict:
    """A renter record. The three physically-checked booleans are omitted unless given."""
    payload: JsonDict = {
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "state_code": state_code,
        "monthly_income_cents": monthly_income_cents,
        "residence_months": residence_months,
    }
    if employer_name is not None:
        payload["employer_name"] = employer_name
    if employer_verified is not None:
        payload["employer_verified"] = employer_verified
    if government_id_verified is not None:
        payload["government_id_verified"] = government_id_verified
    if in_person_contact_consent is not None:
        payload["in_person_contact_consent"] = in_person_contact_consent
    return payload


def dana_reyes_payload(**overrides: Any) -> JsonDict:
    """The canonical Texas renter: employer reached, ID inspected, consent on file."""
    return dict(
        customer_payload(
            full_name="Dana Reyes",
            email="dana@example.com",
            phone="+15125550101",
            state_code="TX",
            monthly_income_cents=300000,
            residence_months=18,
            employer_name="Bluebonnet Foods",
            employer_verified=True,
            government_id_verified=True,
            in_person_contact_consent=True,
        ),
        **overrides,
    )


def dana_reyes_references() -> List[JsonDict]:
    """Two references which, once VERIFIED, take Dana Reyes to a score of 95."""
    return [
        reference_payload("Ruth Vega", Relationship.FAMILY, "+15125550102"),
        reference_payload("Sam Ortiz", Relationship.LANDLORD, "+15125550103"),
    ]


def ivar_holm_payload(**overrides: Any) -> JsonDict:
    """A Minnesota renter. Callers set ``in_person_contact_consent`` deliberately."""
    return dict(
        customer_payload(
            full_name="Ivar Holm",
            email="ivar@example.com",
            phone="+16515550201",
            state_code="MN",
            monthly_income_cents=300000,
            residence_months=18,
            employer_name="North Loop Bakery",
            employer_verified=True,
            government_id_verified=True,
            in_person_contact_consent=False,
        ),
        **overrides,
    )


def ivar_holm_references() -> List[JsonDict]:
    return [
        reference_payload("Lena Ek", Relationship.FAMILY, "+16515550202"),
        reference_payload("Pia Nord", Relationship.LANDLORD, "+16515550203"),
    ]


def duluth_ivar_payload(**overrides: Any) -> JsonDict:
    """The Duluth variant of the Minnesota renter, with no doorstep consent."""
    return dict(
        customer_payload(
            full_name="Ivar Holm",
            email="ivar@example.com",
            phone="+12185550101",
            state_code="MN",
            monthly_income_cents=300000,
            residence_months=18,
            employer_name="North Shore Freight",
            employer_verified=True,
            government_id_verified=True,
            in_person_contact_consent=False,
        ),
        **overrides,
    )


def duluth_ivar_references() -> List[JsonDict]:
    return [
        reference_payload("Britt Lund", Relationship.FAMILY, "+12185550102"),
        reference_payload("Otto Berg", Relationship.LANDLORD, "+12185550103"),
    ]


def ivy_chen_payload(**overrides: Any) -> JsonDict:
    """A renter whose employer was never reached, so the 40-point term is absent."""
    return dict(
        customer_payload(
            full_name="Ivy Chen",
            email="ivy@example.com",
            phone="+15125550111",
            state_code="TX",
            monthly_income_cents=300000,
            residence_months=24,
            employer_name="Barton Springs Cafe",
            employer_verified=False,
            government_id_verified=True,
            in_person_contact_consent=True,
        ),
        **overrides,
    )


def milo_chen_payload(**overrides: Any) -> JsonDict:
    """A renter created with only the required fields, so every default applies."""
    return dict(
        customer_payload(
            full_name="Milo Chen",
            email="milo@example.com",
            phone="+15125550190",
            state_code="TX",
            monthly_income_cents=180000,
            residence_months=4,
        ),
        **overrides,
    )


def mo_klein_payload(**overrides: Any) -> JsonDict:
    """A second Texas renter, used where two distinct renters are needed."""
    return dict(
        customer_payload(
            full_name="Mo Klein",
            email="mo@example.com",
            phone="+15125550131",
            state_code="TX",
            monthly_income_cents=300000,
            residence_months=18,
            employer_name="Zilker Freight",
            employer_verified=True,
            government_id_verified=True,
            in_person_contact_consent=True,
        ),
        **overrides,
    )


def reference_payload(
    reference_name: str, relationship: str, phone: str
) -> JsonDict:
    """A personal reference, born PENDING."""
    return {
        "reference_name": reference_name,
        "relationship": relationship,
        "phone": phone,
    }


def check_payload(result: str) -> JsonDict:
    """The outcome of the telephone call to a reference."""
    return {"result": result}


def verify_payload(
    decision: str = Decision.APPROVE, credit_score: Optional[int] = None
) -> JsonDict:
    """A verification decision. A credit score is supplied only to be refused."""
    payload: JsonDict = {"decision": decision}
    if credit_score is not None:
        payload["credit_score"] = credit_score
    return payload


# ---------------------------------------------------------------------------
# Agreements
# ---------------------------------------------------------------------------


def agreement_payload(
    customer_id: str,
    unit_id: str,
    term_type: str = TermType.WEEKLY,
    renewal_count: int = 52,
    disclosure_acknowledged: Optional[bool] = True,
) -> JsonDict:
    """A rent-to-own agreement against a verified customer and an available unit."""
    payload: JsonDict = {
        "customer_id": customer_id,
        "unit_id": unit_id,
        "term_type": term_type,
        "renewal_count": renewal_count,
    }
    if disclosure_acknowledged is not None:
        payload["disclosure_acknowledged"] = disclosure_acknowledged
    return payload


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def delivery_order_payload(
    crew_id: str,
    expected_agreement_version: int,
    window_start_at: str,
    window_end_at: str,
    service_type: str = ServiceType.DELIVERY_ONLY,
) -> JsonDict:
    """A delivery booking over an inclusive start and an exclusive end."""
    return {
        "crew_id": crew_id,
        "service_type": service_type,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
        "expected_agreement_version": expected_agreement_version,
    }


def complete_delivery_payload(setup_completed: bool = False) -> JsonDict:
    return {"setup_completed": setup_completed}


def fail_attempt_payload(reason: str) -> JsonDict:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


def payment_payload(
    amount_cents: int,
    payment_method: str,
    apply_customer_credit: Optional[bool] = None,
) -> JsonDict:
    """A gross tender of at least one cent."""
    payload: JsonDict = {
        "amount_cents": amount_cents,
        "payment_method": payment_method,
    }
    if apply_customer_credit is not None:
        payload["apply_customer_credit"] = apply_customer_credit
    return payload


def reversal_payload(reason: str) -> JsonDict:
    return {"reason": reason}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def service_ticket_payload(
    issue_code: str, window_start_at: str, window_end_at: str
) -> JsonDict:
    """A bay window from a start to a strictly later end."""
    return {
        "issue_code": issue_code,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }


def issue_swap_payload(replacement_unit_id: str) -> JsonDict:
    return {"replacement_unit_id": replacement_unit_id}


def resolve_ticket_payload(resolution: str, rent_credit_days: int = 0) -> JsonDict:
    return {"resolution": resolution, "rent_credit_days": rent_credit_days}


# ---------------------------------------------------------------------------
# Returns and grading
# ---------------------------------------------------------------------------


def return_payload(return_reason: str = ReturnReason.VOLUNTARY_RETURN) -> JsonDict:
    return {"return_reason": return_reason}


def grade_payload(
    assessed_grade: str,
    damage_deduction_cents: int = 0,
    missing_parts_count: int = 0,
) -> JsonDict:
    return {
        "assessed_grade": assessed_grade,
        "damage_deduction_cents": damage_deduction_cents,
        "missing_parts_count": missing_parts_count,
    }


# ---------------------------------------------------------------------------
# Early purchase
# ---------------------------------------------------------------------------


def quote_payload(expected_agreement_version: int) -> JsonDict:
    return {"expected_agreement_version": expected_agreement_version}


def accept_quote_payload(payment_amount_cents: int) -> JsonDict:
    return {"payment_amount_cents": payment_amount_cents}


# ---------------------------------------------------------------------------
# Collections and repossession
# ---------------------------------------------------------------------------


def collection_contact_payload(
    channel: str = Channel.PHONE, outcome: str = Outcome.NO_ANSWER
) -> JsonDict:
    return {"channel": channel, "outcome": outcome}


def repossess_payload(confirm: bool = True) -> JsonDict:
    return {"confirm": confirm}
