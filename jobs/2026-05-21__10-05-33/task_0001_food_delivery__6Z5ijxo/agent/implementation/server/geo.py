import math


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    r = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def haversine_meters(lat1, lng1, lat2, lng2) -> float:
    return haversine_km(lat1, lng1, lat2, lng2) * 1000.0


def round_distance_km(km: float) -> float:
    return round(km + 1e-9, 1)
