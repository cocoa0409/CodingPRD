"""Loudness / format compliance evaluation (PRD section 2.8).

Loudness comparisons are carried at one decimal place; LUFS tolerance 0.5.
"""
from decimal import Decimal, ROUND_HALF_UP

LUFS_TOLERANCE = Decimal('0.5')
_1DP = Decimal('0.1')


def _q1(value):
    return Decimal(str(value)).quantize(_1DP, rounding=ROUND_HALF_UP)


def compliance_passed(deliverable, profile):
    lufs_ok = abs(_q1(deliverable['integrated_lufs']) - _q1(profile['integrated_lufs'])) <= LUFS_TOLERANCE
    tp_ok = _q1(deliverable['true_peak_dbtp']) <= _q1(profile['true_peak_dbtp'])
    lra_ok = _q1(deliverable['loudness_range_lu']) <= _q1(profile['loudness_range_lu'])
    fmt_ok = (deliverable['sample_rate_hz'] == profile['required_sample_rate_hz']
              and deliverable['bit_depth'] == profile['required_bit_depth'])
    return lufs_ok and tp_ok and lra_ok and fmt_ok
