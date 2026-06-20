"""Pure calculation helpers (PRD §2.8, §3.2, §3.3, §3.7, §3.10, §3.11)."""
from decimal import Decimal, ROUND_HALF_UP

VALID_ADLS = {"BATHING", "DRESSING", "TOILETING", "TRANSFERRING", "CONTINENCE", "EATING"}

INFLATION_RATE = {
    "NONE": Decimal("0"),
    "COMPOUND_3PCT": Decimal("0.03"),
    "COMPOUND_5PCT": Decimal("0.05"),
}

# care_setting -> compatible provider_type (PRD §3.4)
SETTING_TO_PROVIDER_TYPE = {
    "NURSING_HOME": "NURSING_HOME",
    "ASSISTED_LIVING": "ASSISTED_LIVING",
    "HOME_HEALTH": "HOME_HEALTH_AGENCY",
    "ADULT_DAY": "ADULT_DAY_CARE",
    "INFORMAL": "INFORMAL_CAREGIVER",
}


def round_half_up(value):
    """Round a Decimal to the nearest integer using HALF_UP."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def grow(base_cents, rider, years):
    """Compound annual inflation growth, rounding half-up to cents each year
    in ascending year order (PRD §3.2)."""
    rate = INFLATION_RATE[rider]
    v = Decimal(int(base_cents))
    for _ in range(int(years)):
        v = Decimal(round_half_up(v * (Decimal("1") + rate)))
    return int(v)


def trigger_decision(adl_deficiencies, cognitive_impairment):
    """2-of-6 ADL or cognitive impairment -> CERTIFIED (PRD §3.3)."""
    valid = set()
    if isinstance(adl_deficiencies, list):
        for token in adl_deficiencies:
            if token in VALID_ADLS:
                valid.add(token)
    if len(valid) >= 2 or cognitive_impairment is True:
        return "CERTIFIED"
    return "NOT_CERTIFIED"


def premium_amount(base_premium_cents, approved_increase_pct):
    """amount = round_half_up(base * (100 + pct) / 100) (PRD §3.11)."""
    base = Decimal(int(base_premium_cents))
    pct = Decimal(int(approved_increase_pct))
    return round_half_up(base * (Decimal("100") + pct) / Decimal("100"))
