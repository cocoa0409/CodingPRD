"""Monetary helpers - all amounts in integer cents.

Use Decimal for precision-sensitive calculations and round_half_up to integer
cents at the pinned rounding step. Float arithmetic is forbidden anywhere a
cents result is produced.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

NumberLike = Union[int, float, Decimal, str]


def D(value: NumberLike) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up_to_int(value: Union[Decimal, float, int]) -> int:
    """Round half-up to the nearest integer."""
    if isinstance(value, (int,)):
        return int(value)
    if isinstance(value, float):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
