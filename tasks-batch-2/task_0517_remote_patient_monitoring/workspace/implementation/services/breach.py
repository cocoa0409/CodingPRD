"""Breach evaluation (PRD §2.9 / scaffold breach_evaluation calc).

Evaluates a reading against the band defined by the patient's currently ACTIVE
care plan and the transmitting device's device_type. Returns one of
None / "WARNING" / "CRITICAL". CRITICAL wins over WARNING.

Boundaries are inclusive exactly as written:
  BP_CUFF:      WARNING if systolic >= 140 or diastolic >= 90;
                CRITICAL if systolic >= 180 or diastolic >= 120.
  GLUCOMETER:   WARNING if value >= 250 or value < 70;
                CRITICAL if value >= 400 or value < 54.
  PULSE_OX:     WARNING if value <= 92 and value > 88; CRITICAL if value <= 88.
                Never produces a high-side breach.
  WEIGHT_SCALE: WARNING if value >= prior_reading + 1.4 kg within preceding 24h;
                never CRITICAL.

Weight compared to one decimal place using round-half-up; other comparisons on
integer mmHg/mg-dL/% values.
"""
from decimal import Decimal, ROUND_HALF_UP

BP_SYS_WARN = 140
BP_SYS_CRIT = 180
BP_DIA_WARN = 90
BP_DIA_CRIT = 120
GLU_HI_WARN = 250
GLU_HI_CRIT = 400
GLU_LO_WARN = 70
GLU_LO_CRIT = 54
SPO2_WARN = 92
SPO2_CRIT = 88
WEIGHT_GAIN_KG = Decimal("1.4")


def _round1(value):
    return Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def evaluate(device_type, reading_value, secondary_value, prior_weight=None):
    """Return None, "WARNING", or "CRITICAL" for the reading.

    prior_weight: the immediately prior WEIGHT_SCALE reading_value within the
    preceding 24h (already resolved by the caller), or None.
    """
    if device_type == "BP_CUFF":
        systolic = reading_value
        diastolic = secondary_value
        crit = (systolic is not None and systolic >= BP_SYS_CRIT) or \
               (diastolic is not None and diastolic >= BP_DIA_CRIT)
        if crit:
            return "CRITICAL"
        warn = (systolic is not None and systolic >= BP_SYS_WARN) or \
               (diastolic is not None and diastolic >= BP_DIA_WARN)
        if warn:
            return "WARNING"
        return None

    if device_type == "GLUCOMETER":
        v = reading_value
        if v is None:
            return None
        if v >= GLU_HI_CRIT or v < GLU_LO_CRIT:
            return "CRITICAL"
        if v >= GLU_HI_WARN or v < GLU_LO_WARN:
            return "WARNING"
        return None

    if device_type == "PULSE_OX":
        v = reading_value
        if v is None:
            return None
        if v <= SPO2_CRIT:
            return "CRITICAL"
        if v <= SPO2_WARN and v > SPO2_CRIT:
            return "WARNING"
        return None

    if device_type == "WEIGHT_SCALE":
        if prior_weight is None or reading_value is None:
            return None
        current = _round1(reading_value)
        prior = _round1(prior_weight)
        if current >= prior + WEIGHT_GAIN_KG:
            return "WARNING"
        return None

    return None
