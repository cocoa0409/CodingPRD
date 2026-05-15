"""Payload factories — one per endpoint that takes a body.

Each factory accepts **overrides so tests can vary specific values
without re-typing the whole payload. Factories emit ONLY source=input
fields per PRD §3 / §4.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Address (used inside customer + subscription payloads, PRD §3.1)
# ---------------------------------------------------------------------------
def make_address(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Address payloads share a consistent shape: line1,
    optional line2, city, region, postal_code, country (ISO 3166-1
    alpha-2), and verified.'

    Builds an address that will pass address_verification (PRD §3.1):
    country in supported set, US postal_code matches ^\\d{5}(-\\d{4})?$,
    line1 + city non-empty.
    """
    defaults: Dict[str, Any] = {
        "line1": "100 Test Lane",
        "city": "Testville",
        "region": TEST_DEFAULTS["REGION"],
        "postal_code": TEST_DEFAULTS["POSTAL_CODE_US"],
        "country": TEST_DEFAULTS["COUNTRY_US"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Customer (PRD §3.1)
# ---------------------------------------------------------------------------
def create_customer_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'The acting party submits an email (unique per
    Customer) and a display_name, optionally with a
    default_shipping_address.'"""
    suffix = uuid.uuid4().hex[:10]
    defaults: Dict[str, Any] = {
        "email": (
            f"{TEST_DEFAULTS['EMAIL_PREFIX']}-{suffix}"
            f"@{TEST_DEFAULTS['EMAIL_DOMAIN']}"
        ),
        "display_name": TEST_DEFAULTS["DISPLAY_NAME"],
        "default_shipping_address": make_address(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Pet (PRD §3.1)
# ---------------------------------------------------------------------------
def create_pet_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'A pet carries a name, a species (one of DOG or CAT),
    a free-text breed, a birthdate (ISO date YYYY-MM-DD), an integer-
    or-decimal weight_kg strictly greater than 0 and at most 100, an
    activity_level (one of LOW, MODERATE, or HIGH), and four optional
    ingredient-token lists allergies, intolerances, dietary_preferences,
    and dietary_aversions.'

    Default birthdate is chosen so the dog is ADULT under PRD §3.1
    derivation (>=12 months, <84 months).
    """
    defaults: Dict[str, Any] = {
        "name": TEST_DEFAULTS["PET_NAME"],
        "species": "DOG",
        "breed": TEST_DEFAULTS["BREED"],
        "birthdate": "2022-01-01",  # roughly 3-4 years → ADULT
        "weight_kg": TEST_DEFAULTS["WEIGHT_KG"],
        "activity_level": TEST_DEFAULTS["ACTIVITY"],
        "allergies": [],
        "intolerances": [],
        "dietary_preferences": [],
        "dietary_aversions": [],
        "health_conditions": [],
    }
    defaults.update(overrides)
    return defaults


def update_pet_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'The pet update capability accepts changes to
    weight_kg, activity_level, allergies, intolerances,
    dietary_preferences, dietary_aversions, and health_conditions,
    with an optional version for the concurrency check.'"""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def add_pet_photo_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: 'Customers append photos one at a time by calling
    the photo-gallery capability with a single url.'"""
    defaults: Dict[str, Any] = {
        "url": f"https://example.com/photos/{uuid.uuid4().hex}.jpg",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Subscription (PRD §3.2)
# ---------------------------------------------------------------------------
def create_subscription_payload(pet_ids: List[str],
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'On creation, the customer supplies pet_ids (a non-
    empty array of distinct Pet.id values, all of which must belong to
    this customer and all of which must be in ACTIVE status), a
    frequency (WEEKLY, BIWEEKLY, or MONTHLY), a shipping_address, and
    an optional is_trial flag that defaults to false.'"""
    defaults: Dict[str, Any] = {
        "pet_ids": list(pet_ids),
        "frequency": "WEEKLY",
        "shipping_address": make_address(),
        "is_trial": False,
    }
    defaults.update(overrides)
    return defaults


def update_subscription_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'The subscription modify capability accepts changes
    to frequency, pet_ids, and shipping_address, plus an optional
    version for the concurrency check.'"""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def pause_subscription_payload(pause_until: str,
                               **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'The pause call accepts a single pause_until instant
    in the request body.'"""
    payload: Dict[str, Any] = {"pause_until": pause_until}
    payload.update(overrides)
    return payload


def cancel_subscription_payload(cancel_reason: str,
                                force: Optional[bool] = None,
                                **overrides: Any) -> Dict[str, Any]:
    """PRD §3.2: 'The customer invokes cancel with a cancel_reason
    field whose value must be one of PRICE, QUALITY, PET_NO_LONGER, or
    OTHER ... and an optional force flag.'"""
    payload: Dict[str, Any] = {"cancel_reason": cancel_reason}
    if force is not None:
        payload["force"] = force
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recipe (PRD §3.3)
# ---------------------------------------------------------------------------
def create_recipe_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.3: 'A Recipe carries a stable code, a target_species of
    DOG or CAT, a target_life_stage ..., three ingredient-token lists
    protein_sources, grain_sources (empty for grain-free recipes), and
    supplement_sources, an energy density kcal_per_gram strictly
    greater than 0 and at most 10, a unit_price_cents_per_100g of at
    least 1, a vet_prescribed boolean that defaults to false, a
    prescribed_for list ..., a rotation-grouping monotony_class label,
    and a trial_eligible boolean that defaults to true.'"""
    suffix = uuid.uuid4().hex[:8].upper()
    defaults: Dict[str, Any] = {
        "code": f"R-{suffix}",
        "target_species": "DOG",
        "target_life_stage": "ADULT",
        "protein_sources": ["SALMON"],
        "grain_sources": [],
        "supplement_sources": ["OMEGA3"],
        "kcal_per_gram": TEST_DEFAULTS["KCAL_PER_GRAM"],
        "unit_price_cents_per_100g": TEST_DEFAULTS[
            "UNIT_PRICE_CENTS_PER_100G"
        ],
        "vet_prescribed": False,
        "prescribed_for": [],
        "monotony_class": TEST_DEFAULTS["MONOTONY_CLASS_A"],
        "trial_eligible": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Warehouse + Inventory (PRD §3.6)
# ---------------------------------------------------------------------------
def create_warehouse_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'Each Warehouse carries a unique code, a
    serves_regions list ..., a priority_rank in the range 1 to 100 ...,
    a daily_outbound_capacity of at least 1, and a status of ONLINE or
    OFFLINE.'"""
    suffix = uuid.uuid4().hex[:6].upper()
    defaults: Dict[str, Any] = {
        "code": f"WH-{suffix}",
        "serves_regions": [TEST_DEFAULTS["REGION"]],
        "priority_rank": TEST_DEFAULTS["PRIORITY_RANK"],
        "daily_outbound_capacity": TEST_DEFAULTS["DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def update_warehouse_payload(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'The warehouse-update capability accepts changes to
    status, daily_outbound_capacity, and priority_rank, with the
    optional version for concurrency control.'"""
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


def create_inventory_lot_payload(recipe_id: str,
                                 **overrides: Any) -> Dict[str, Any]:
    """PRD §3.6: 'Inventory lots are added underneath a warehouse and
    carry warehouse_id (system-set from the path), a recipe_id, a
    batch_code (unique per warehouse and recipe), an expiration_date
    (an ISO date string ...), and an integer quantity_grams of at
    least 0.'"""
    suffix = uuid.uuid4().hex[:8].upper()
    defaults: Dict[str, Any] = {
        "recipe_id": recipe_id,
        "batch_code": f"B-{suffix}",
        "expiration_date": "2099-12-31",
        "quantity_grams": TEST_DEFAULTS["BATCH_QUANTITY_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# ShipmentFeedback (PRD §3.5)
# ---------------------------------------------------------------------------
def submit_feedback_payload(pet_id: str,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'a request body containing the pet_id (which must be
    one of the subscription's pet_ids), integer ratings palatability,
    stool_quality, and coat_condition each in the range 1 to 5
    inclusive, a signed integer weight_change_grams, and an optional
    free-text notes.'"""
    defaults: Dict[str, Any] = {
        "pet_id": pet_id,
        "palatability": 5,
        "stool_quality": 5,
        "coat_condition": 5,
        "weight_change_grams": 0,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Event payloads (PRD §3.4)
# ---------------------------------------------------------------------------
def payment_event_payload(event_type: str,
                          amount_cents: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'Payment events arrive from the payment system as
    PaymentAdapter posts carrying an event_type and optionally an
    amount_cents.'"""
    payload: Dict[str, Any] = {"event_type": event_type}
    if amount_cents is not None:
        payload["amount_cents"] = amount_cents
    payload.update(overrides)
    return payload


def logistics_event_payload(event_type: str,
                            tracking_number: Optional[str] = None,
                            **overrides: Any) -> Dict[str, Any]:
    """PRD §3.4: 'Logistics events arrive from LogisticsAdapter posts
    carrying an event_type and optionally a tracking_number.'"""
    payload: Dict[str, Any] = {"event_type": event_type}
    if tracking_number is not None:
        payload["tracking_number"] = tracking_number
    payload.update(overrides)
    return payload


def vet_event_payload(event_type: str,
                      **overrides: Any) -> Dict[str, Any]:
    """PRD §3.5: 'The vet system then delivers a verdict by posting a
    vet event with event_type VET_APPROVED or VET_REJECTED.'"""
    payload: Dict[str, Any] = {"event_type": event_type}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.8 / §3.7)
# ---------------------------------------------------------------------------
def clock_advance_payload(to: Optional[str] = None,
                          by_hours: Optional[int] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """PRD §3.7: 'logical-clock advance capability that accepts either
    an absolute to instant or a relative by_hours duration.'"""
    payload: Dict[str, Any] = {}
    if to is not None:
        payload["to"] = to
    if by_hours is not None:
        payload["by_hours"] = by_hours
    payload.update(overrides)
    return payload


__all__ = [
    "make_address",
    "create_customer_payload",
    "create_pet_payload",
    "update_pet_payload",
    "add_pet_photo_payload",
    "create_subscription_payload",
    "update_subscription_payload",
    "pause_subscription_payload",
    "cancel_subscription_payload",
    "create_recipe_payload",
    "create_warehouse_payload",
    "update_warehouse_payload",
    "create_inventory_lot_payload",
    "submit_feedback_payload",
    "payment_event_payload",
    "logistics_event_payload",
    "vet_event_payload",
    "clock_advance_payload",
]
