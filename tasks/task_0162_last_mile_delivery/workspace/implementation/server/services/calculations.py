"""Pricing, distance, and time-window calculations per PRD §3.7."""
import math
from decimal import Decimal, ROUND_HALF_UP


EARTH_RADIUS_KM = Decimal("6371.0")

# Quote constants
BASE_FEE = Decimal("5.00")
WEIGHT_FREE_KG = Decimal("1.0")
WEIGHT_PER_KG_FEE = Decimal("0.75")
DISTANCE_BUCKET_KM = Decimal("25.0")
DISTANCE_BUCKET_FEE = Decimal("1.50")
HAZMAT_SURCHARGE = Decimal("12.00")
SIGNATURE_SURCHARGE = Decimal("2.50")
RESIDENTIAL_SURCHARGE = Decimal("1.00")

# Final-fee constants
REATTEMPT_FEE = Decimal("3.00")
ADDRESS_CORRECTION_FEE = Decimal("8.00")
APPOINTMENT_CHANGE_FEE = Decimal("4.50")
RETURN_TO_SENDER_FEE = Decimal("7.00")

# Time-assignment constants
AVG_SPEED_KMH = Decimal("40.0")
SERVICE_TIME_MIN = 6
DEPART_HOUR_LOCAL = 8

# Caps
MAX_REDELIVERY_ATTEMPTS = 3
CUSTOMER_REDELIVERY_CAP_30D = 10
MIN_APPT_WINDOW_HOURS = 2


def dec2(value) -> Decimal:
    """Round-half-up to two decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def to_decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def haversine_km(lat1, lon1, lat2, lon2) -> Decimal:
    """Great-circle distance in kilometers using Earth radius 6371.0."""
    lat1_f = float(lat1)
    lon1_f = float(lon1)
    lat2_f = float(lat2)
    lon2_f = float(lon2)
    phi1 = math.radians(lat1_f)
    phi2 = math.radians(lat2_f)
    dphi = math.radians(lat2_f - lat1_f)
    dlam = math.radians(lon2_f - lon1_f)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    km = float(EARTH_RADIUS_KM) * c
    return Decimal(str(km))


def shipping_fee_quote(parcel: dict, destination_address: dict, origin_center: dict) -> Decimal:
    """Compute the forward-looking quote. Returns a Decimal rounded to 2 dp."""
    weight_kg = to_decimal(parcel.get("weight_kg", 0))
    # Weight fee
    excess = weight_kg - WEIGHT_FREE_KG
    if excess < 0:
        excess = Decimal("0")
    excess_ceil = int(excess.to_integral_value(rounding="ROUND_CEILING")) if excess > 0 else 0
    # Actually use math.ceil for clarity.
    excess_ceil = math.ceil(float(excess))
    weight_fee = Decimal(excess_ceil) * WEIGHT_PER_KG_FEE

    # Distance fee
    origin_lat = origin_center.get("latitude", 0.0)
    origin_lon = origin_center.get("longitude", 0.0)
    if origin_lat is None:
        origin_lat = 0.0
    if origin_lon is None:
        origin_lon = 0.0
    dest_lat = destination_address["latitude"]
    dest_lon = destination_address["longitude"]
    distance_km = haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
    buckets = math.ceil(float(distance_km) / float(DISTANCE_BUCKET_KM))
    distance_fee = Decimal(buckets) * DISTANCE_BUCKET_FEE

    hazmat_fee = HAZMAT_SURCHARGE if parcel.get("hazmat_class", "NONE") != "NONE" else Decimal("0")
    signature_fee = SIGNATURE_SURCHARGE if parcel.get("signature_required", False) else Decimal("0")
    residential_fee = RESIDENTIAL_SURCHARGE if destination_address.get("residential", True) else Decimal("0")

    raw = BASE_FEE + weight_fee + distance_fee + hazmat_fee + signature_fee + residential_fee
    return dec2(raw)


def shipping_fee_final(parcel: dict, attempts_sorted, accepted_appointment_count: int) -> Decimal:
    """Compute the chronological final fee. attempts_sorted is a list of attempts
    pre-sorted by attempted_at ASC."""
    total = to_decimal(parcel.get("quoted_fee", 0))
    for attempt in attempts_sorted:
        outcome = attempt["outcome"]
        if outcome in ("NO_ONE_HOME", "REFUSED"):
            total += REATTEMPT_FEE
        elif outcome == "ADDRESS_INVALID":
            total += ADDRESS_CORRECTION_FEE
            break
    total += APPOINTMENT_CHANGE_FEE * accepted_appointment_count
    if parcel.get("status") == "RETURNED_TO_SENDER":
        total += RETURN_TO_SENDER_FEE
    return dec2(total)


def route_total_distance_km(stops_in_seq, parcel_dest_addr_lookup, origin_lat, origin_lon) -> Decimal:
    """Sum haversine legs from origin -> each stop's destination address."""
    total_km = Decimal("0")
    prev_lat = origin_lat
    prev_lon = origin_lon
    for stop in stops_in_seq:
        addr = parcel_dest_addr_lookup(stop["parcel_id"])
        leg = haversine_km(prev_lat, prev_lon, addr["latitude"], addr["longitude"])
        total_km += leg
        prev_lat = addr["latitude"]
        prev_lon = addr["longitude"]
    return dec2(total_km)
