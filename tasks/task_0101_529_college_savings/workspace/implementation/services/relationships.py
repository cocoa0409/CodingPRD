"""IRS family relationship permissibility and generation-skip detection."""

# Permissible target family codes for a beneficiary change (per PRD §3.6).
PERMISSIBLE_TARGET_FAMILY_CODES = {
    "CHILD", "SIBLING", "NIECE_NEPHEW", "COUSIN",
    "FIRST_COUSIN_ONCE_REMOVED", "SPOUSE", "IN_LAW", "PARENT",
}

# Generation index: higher = older generation.
# This is used to detect upward generation skip (more than one generation older).
GENERATION = {
    "SELF":                       0,
    "SPOUSE":                     0,
    "SIBLING":                    0,
    "COUSIN":                     0,
    "FIRST_COUSIN_ONCE_REMOVED":  0,
    "IN_LAW":                     1,   # parent-in-law generation (older)
    "PARENT":                     1,   # one generation up
    "NIECE_NEPHEW":              -1,   # one generation down
    "CHILD":                     -1,
}


def is_permissible(target_code: str) -> bool:
    return target_code in PERMISSIBLE_TARGET_FAMILY_CODES


def is_generation_skip(current_code: str, proposed_code: str) -> bool:
    """Return True when proposed is more than one generation removed UPWARD
    from current. The canonical example in the PRD is CHILD -> PARENT or
    CHILD -> IN_LAW where the proposed beneficiary is at least 2 generations
    older than the current."""
    cur_g = GENERATION.get(current_code, 0)
    new_g = GENERATION.get(proposed_code, 0)
    return (new_g - cur_g) >= 2
