"""Dietary / allergen safety check (PRD §3.4)."""

# Map a requested dietary tag to the allergen codes it forbids.
DIETARY_FORBIDS = {
    "VEGAN": {"DAIRY", "EGG"},
    "GLUTEN_FREE": {"GLUTEN"},
}


def dietary_conflict(requested_dietary_codes, selected_option_codes,
                     option_by_code, effective_allergen_codes):
    """Return True when the line violates dietary safety.

    Part 1: no requested dietary tag may appear in any selected option's
            dietary_exclusion_codes.
    Part 2: effective_allergen_codes must not contain an allergen a requested
            dietary tag forbids.
    """
    requested = set(requested_dietary_codes or [])

    # Part 1
    for code in selected_option_codes or []:
        option = option_by_code.get(code)
        if option is None:
            continue
        exclusions = set(option.get("dietary_exclusion_codes") or [])
        if requested & exclusions:
            return True

    # Part 2
    effective = set(effective_allergen_codes or [])
    for tag in requested:
        forbidden = DIETARY_FORBIDS.get(tag, set())
        if effective & forbidden:
            return True

    return False
