"""Utility helpers: timestamps, decimal math, month arithmetic, distances."""

import hashlib
import math
import re
import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$"
)


def fmt_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.microsecond // 1000
    return f"{base}.{millis:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None when the value is not a parseable datetime string.
    """
    if not isinstance(value, str):
        return None
    if not _TS_RE.match(value.strip()):
        return None
    s = value.strip().replace("Z", "+00:00").replace("z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def wall_now_ts():
    """Wall-clock UTC timestamp with millisecond precision (for meta block)."""
    return fmt_ts(datetime.now(timezone.utc))


def new_uuid():
    return str(uuid.uuid4())


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    total = (dt.year * 12 + (dt.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Decimal math -- hours: 2dp round-half-up; money: 0dp round-half-up
# ---------------------------------------------------------------------------

HOUR_Q = Decimal("0.01")
MONEY_Q = Decimal("1")


def D(x):
    """Coerce an int/float/str/Decimal into a Decimal exactly."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        raise ValueError("boolean is not numeric")
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(str(x))
    if isinstance(x, str):
        return Decimal(x)
    raise ValueError(f"not numeric: {type(x)}")


def round_hours(x):
    return D(x).quantize(HOUR_Q, rounding=ROUND_HALF_UP)


def round_money(x):
    return int(D(x).quantize(MONEY_Q, rounding=ROUND_HALF_UP))


def hours_json(d):
    """Serialize a Decimal hour quantity as a JSON number with <=2dp."""
    if d is None:
        return None
    return float(round_hours(d))


# ---------------------------------------------------------------------------
# Airport coordinates and great-circle distance (nautical miles)
# ---------------------------------------------------------------------------

# Fixed coordinate table for common ICAO codes (lat, lon degrees).
AIRPORT_COORDS = {
    "KJFK": (40.6413, -73.7781), "KLGA": (40.7769, -73.8740),
    "KEWR": (40.6895, -74.1745), "KTEB": (40.8501, -74.0608),
    "KLAX": (33.9416, -118.4085), "KVNY": (34.2098, -118.4899),
    "KSNA": (33.6757, -117.8682), "KSAN": (32.7338, -117.1933),
    "KOAK": (37.7213, -122.2208), "KSJC": (37.3639, -121.9289),
    "KSFO": (37.6213, -122.3790), "KSMF": (38.6954, -121.5908),
    "KORD": (41.9742, -87.9073), "KMDW": (41.7868, -87.7522),
    "KDFW": (32.8998, -97.0403), "KDAL": (32.8471, -96.8518),
    "KHOU": (29.6454, -95.2789), "KIAH": (29.9902, -95.3368),
    "KDEN": (39.8561, -104.6737), "KSEA": (47.4502, -122.3088),
    "KPDX": (45.5898, -122.5951), "KGEG": (47.6199, -117.5338),
    "KBOI": (43.5644, -116.2228), "KSLC": (40.7899, -111.9791),
    "KPHX": (33.4373, -112.0078), "KTUS": (32.1161, -110.9410),
    "KABQ": (35.0402, -106.6090), "KELP": (31.8072, -106.3776),
    "KLAS": (36.0840, -115.1537), "KRNO": (39.4991, -119.7681),
    "KMIA": (25.7959, -80.2870), "KFLL": (26.0742, -80.1506),
    "KPBI": (26.6832, -80.0956), "KRSW": (26.5362, -81.7552),
    "KTPA": (27.9755, -82.5332), "KMCO": (28.4312, -81.3081),
    "KJAX": (30.4941, -81.6879), "KBOS": (42.3656, -71.0096),
    "KATL": (33.6407, -84.4277), "KCLT": (35.2144, -80.9473),
    "KRDU": (35.8801, -78.7880), "KBNA": (36.1263, -86.6774),
    "KMEM": (35.0424, -89.9767), "KMSY": (29.9934, -90.2580),
    "KSTL": (38.7487, -90.3700), "KMCI": (39.2976, -94.7139),
    "KMSP": (44.8848, -93.2223), "KDTW": (42.2162, -83.3554),
    "KCLE": (41.4117, -81.8498), "KCMH": (39.9980, -82.8919),
    "KIND": (39.7173, -86.2944), "KPIT": (40.4915, -80.2329),
    "KPHL": (39.8744, -75.2424), "KBWI": (39.1774, -76.6684),
    "KDCA": (38.8512, -77.0402), "KIAD": (38.9531, -77.4565),
    "KAUS": (30.1975, -97.6664), "KSAT": (29.5337, -98.4698),
    "KOKC": (35.3931, -97.6007), "KTUL": (36.1984, -95.8881),
    "KOMA": (41.3032, -95.8941), "KANC": (61.1743, -149.9963),
    "PANC": (61.1743, -149.9963), "KHNL": (21.3245, -157.9251),
    "PHNL": (21.3245, -157.9251), "KOGG": (20.8986, -156.4305),
    "KPSP": (33.8303, -116.5070), "KSDL": (33.6229, -111.9105),
    "KASP": (40.5350, -105.0100), "KASE": (39.2232, -106.8687),
    "KJAC": (43.6073, -110.7377), "KSUN": (43.5044, -114.2962),
    "KMSO": (46.9163, -114.0906), "KBZN": (45.7775, -111.1520),
    "KBIL": (45.8077, -108.5429), "KGEG2": (47.6199, -117.5338),
    "KHYA": (41.6693, -70.2804), "KACK": (41.2531, -70.0602),
    "KMVY": (41.3931, -70.6143), "KBED": (42.4700, -71.2890),
    "KPVD": (41.7240, -71.4282), "KBDL": (41.9389, -72.6832),
    "KHPN": (41.0670, -73.7076), "KFRG": (40.7288, -73.4134),
    "KISP": (40.7952, -73.1002), "KMMU": (40.7994, -74.4149),
    "KAPF": (26.1526, -81.7753), "KOPF": (25.9070, -80.2784),
    "KFXE": (26.1973, -80.1707), "KSUA": (27.1817, -80.2211),
    "KVRB": (27.6556, -80.4179), "KDAB": (29.1799, -81.0581),
    "KCHS": (32.8986, -80.0405), "KSAV": (32.1276, -81.2021),
    "KHHI": (31.8890, -81.5623), "KMYR": (33.6797, -78.9283),
    "KGSP": (34.8957, -82.2189), "KCAE": (33.9388, -81.1195),
    "KORF": (36.8946, -76.2012), "KRIC": (37.5052, -77.3197),
    "KROA": (37.3255, -79.9754), "KCRW": (38.3731, -81.5932),
    "KLEX": (38.0365, -84.6059), "KSDF": (38.1744, -85.7360),
    "KCVG": (39.0488, -84.6678), "KDAY": (39.9024, -84.2194),
    "KTYS": (35.8124, -83.9928), "KGPT": (30.4073, -89.0701),
    "KBHM": (33.5629, -86.7535), "KHSV": (34.6372, -86.7751),
    "KLIT": (34.7294, -92.2243), "KXNA": (36.2819, -94.3068),
    "KFSM": (35.3366, -94.3674), "KSGF": (37.2457, -93.3886),
    "KICT": (37.6499, -97.4331), "KDSM": (41.5340, -93.6631),
    "KCID": (41.8847, -91.7108), "KFAR": (46.9207, -96.8158),
    "KBIS": (46.7727, -100.7460), "KRAP": (44.0453, -103.0574),
    "KFSD": (43.5820, -96.7419), "KGRR": (42.8808, -85.5228),
    "KLAN": (42.7787, -84.5874), "KTVC": (44.7414, -85.5822),
    "KMSN": (43.1399, -89.3375), "KMKE": (42.9472, -87.8966),
    "KATW": (44.2581, -88.5191), "KGRB": (44.4851, -88.1296),
    "KEAU": (44.8658, -91.4843), "KDLH": (46.8421, -92.1936),
    "KPSM": (43.0779, -70.8233), "KBGR": (44.8074, -68.8281),
    "KPWM": (43.6462, -70.3093), "KBTV": (44.4719, -73.1533),
    "KALB": (42.7483, -73.8017), "KSYR": (43.1112, -76.1063),
    "KBUF": (42.9405, -78.7322), "KROC": (43.1189, -77.6724),
}

EARTH_RADIUS_NM = 3440.065


def _fallback_coord(icao):
    """Deterministic pseudo-coordinate for ICAO codes outside the table."""
    h = hashlib.sha256(("coord:" + icao).encode("utf-8")).digest()
    lat = (int.from_bytes(h[0:4], "big") % 14000) / 100.0 - 55.0   # -55..85
    lon = (int.from_bytes(h[4:8], "big") % 36000) / 100.0 - 180.0  # -180..180
    return (lat, lon)


def _coord(icao):
    return AIRPORT_COORDS.get(icao.upper(), _fallback_coord(icao.upper()))


def distance_nm(icao_a, icao_b):
    """Great-circle distance in nautical miles between two ICAO airports."""
    lat1, lon1 = _coord(icao_a)
    lat2, lon2 = _coord(icao_b)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_NM * c


CATEGORY_ORDER = ["LIGHT", "MIDSIZE", "SUPER_MID", "HEAVY"]


def category_rank(cat):
    try:
        return CATEGORY_ORDER.index(cat)
    except ValueError:
        return -1
