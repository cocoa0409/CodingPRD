"""Domain thresholds — numeric constants the PRD pins.

These constants come from PRD §3.7 (pricing, distance, time assignment)
and PRD §3.5 (redelivery caps) and from the validation pins in §2.9.
Tests reference these by name so boundary tests stay readable.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pricing — PRD §3.7 forward-looking quote
# ---------------------------------------------------------------------------
BASE_FEE = 5.00
WEIGHT_FREE_KG = 1.0
WEIGHT_PER_KG_FEE = 0.75
DISTANCE_BUCKET_KM = 25.0
DISTANCE_BUCKET_FEE = 1.50
HAZMAT_SURCHARGE = 12.00
SIGNATURE_SURCHARGE = 2.50
RESIDENTIAL_SURCHARGE = 1.00

# ---------------------------------------------------------------------------
# Pricing — PRD §3.7 chronological final-fee
# ---------------------------------------------------------------------------
REATTEMPT_FEE = 3.00
ADDRESS_CORRECTION_FEE = 8.00
APPOINTMENT_CHANGE_FEE = 4.50
RETURN_TO_SENDER_FEE = 7.00

# ---------------------------------------------------------------------------
# Routing / time assignment — PRD §3.7
# ---------------------------------------------------------------------------
EARTH_RADIUS_KM = 6371.0
AVG_SPEED_KMH = 40.0
SERVICE_TIME_MIN = 6
DEPART_HOUR_LOCAL = 8

# ---------------------------------------------------------------------------
# Redelivery thresholds — PRD §3.5
# ---------------------------------------------------------------------------
MAX_REDELIVERY_ATTEMPTS = 3
CUSTOMER_REDELIVERY_CAP_30D = 10
CUSTOMER_REDELIVERY_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Parcel range checks — PRD §3.3
# ---------------------------------------------------------------------------
PARCEL_WEIGHT_MIN_EXCLUSIVE = 0.0
PARCEL_WEIGHT_MAX_INCLUSIVE = 70.0
PARCEL_DECLARED_VALUE_MIN_INCLUSIVE = 0.0
PARCEL_DECLARED_VALUE_MAX_INCLUSIVE = 50000.0

# ---------------------------------------------------------------------------
# Appointment window — PRD §3.5
# ---------------------------------------------------------------------------
MIN_APPT_WINDOW_HOURS = 2

# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_MIN_OFFSET = 0


# ---------------------------------------------------------------------------
# Reasonable test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "customer_email_suffix": "@example.com",
    "customer_phone": "+15551234567",
    "transit_center_postal_prefix": "902",
    "transit_center_lat": 33.94,
    "transit_center_lon": -118.40,
    "address_lat": 34.05,
    "address_lon": -118.25,
    "address_postal_code": "90210",
    "parcel_weight_kg": 3.0,
    "parcel_declared_value": 100.00,
}


__all__ = [
    "BASE_FEE",
    "WEIGHT_FREE_KG",
    "WEIGHT_PER_KG_FEE",
    "DISTANCE_BUCKET_KM",
    "DISTANCE_BUCKET_FEE",
    "HAZMAT_SURCHARGE",
    "SIGNATURE_SURCHARGE",
    "RESIDENTIAL_SURCHARGE",
    "REATTEMPT_FEE",
    "ADDRESS_CORRECTION_FEE",
    "APPOINTMENT_CHANGE_FEE",
    "RETURN_TO_SENDER_FEE",
    "EARTH_RADIUS_KM",
    "AVG_SPEED_KMH",
    "SERVICE_TIME_MIN",
    "DEPART_HOUR_LOCAL",
    "MAX_REDELIVERY_ATTEMPTS",
    "CUSTOMER_REDELIVERY_CAP_30D",
    "CUSTOMER_REDELIVERY_WINDOW_DAYS",
    "PARCEL_WEIGHT_MIN_EXCLUSIVE",
    "PARCEL_WEIGHT_MAX_INCLUSIVE",
    "PARCEL_DECLARED_VALUE_MIN_INCLUSIVE",
    "PARCEL_DECLARED_VALUE_MAX_INCLUSIVE",
    "MIN_APPT_WINDOW_HOURS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TEST_DEFAULTS",
]
