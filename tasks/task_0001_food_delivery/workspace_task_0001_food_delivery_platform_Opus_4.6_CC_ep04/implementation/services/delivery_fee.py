import math


def compute_delivery_fee(distance_km, is_peak):
    base = 300
    bands = math.ceil(distance_km)
    per_km = bands * 120
    peak = 200 if is_peak else 0
    return base + per_km + peak


def compute_final_delivery_fee(distance_km, is_peak, is_merged):
    solo_fee = compute_delivery_fee(distance_km, is_peak)
    if is_merged:
        discount = math.floor(solo_fee * 0.25)
        return solo_fee - discount
    return solo_fee
