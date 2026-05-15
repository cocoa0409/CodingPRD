"""2024 federal poverty guidelines (annual, cents). Per PRD §3.7."""
from __future__ import annotations

# Three regional partitions: 48 contiguous + DC; AK; HI.
POVERTY_48_DC: dict[int, int] = {
    1: 1506000,
    2: 2034000,
    3: 2562000,
    4: 3090000,
    5: 3618000,
}
POVERTY_AK: dict[int, int] = {
    1: 1882000,
    2: 2542000,
    3: 3202000,
    4: 3862000,
    5: 4522000,
}
POVERTY_HI: dict[int, int] = {
    1: 1732000,
    2: 2340000,
    3: 2948000,
    4: 3556000,
    5: 4164000,
}

# Per-additional-person increments derived from the 2024 tables (approximate
# extrapolation for borrowers with family_size > 5). The scaffold/PRD only
# pins sizes 1..5; we extrapolate by linear extension using the last delta.
def _extrapolate(table: dict[int, int], family_size: int) -> int:
    if family_size in table:
        return table[family_size]
    if family_size < 1:
        family_size = 1
    if family_size <= 5:
        return table[family_size]
    # extend linearly beyond size 5 using the (5 - 4) delta.
    delta = table[5] - table[4]
    return table[5] + delta * (family_size - 5)


# Two-letter codes for the 48 contiguous states + DC. Any code not in AK/HI
# falls back to 48_DC.
_NON_CONTIG = {"AK", "HI"}


def poverty_line_cents(state_code: str | None, family_size: int) -> int:
    state = (state_code or "").upper()
    if state == "AK":
        return _extrapolate(POVERTY_AK, family_size)
    if state == "HI":
        return _extrapolate(POVERTY_HI, family_size)
    return _extrapolate(POVERTY_48_DC, family_size)
