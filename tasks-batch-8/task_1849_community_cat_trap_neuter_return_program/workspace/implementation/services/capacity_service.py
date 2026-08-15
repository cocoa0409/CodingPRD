"""Clinic day effective capacity (PRD §2.7, calculation
clinic_day_effective_capacity).

During kitten season (March through July) a booking for a kitten is admitted
while booked_count < base_capacity + surge_capacity. In every other case — an
adult cat in any month, or any cat outside the season — admission requires
booked_count < base_capacity; surge slots are unreachable for adults. The
comparison is a strict less-than on the pre-increment count.
"""

KITTEN_SEASON_MONTHS = {3, 4, 5, 6, 7}


def capacity_admits(clinic_day, cat):
    month = clinic_day["_service_date"].month
    if cat["is_kitten"] and month in KITTEN_SEASON_MONTHS:
        return clinic_day["booked_count"] < (
            clinic_day["base_capacity"] + clinic_day["surge_capacity"])
    return clinic_day["booked_count"] < clinic_day["base_capacity"]
