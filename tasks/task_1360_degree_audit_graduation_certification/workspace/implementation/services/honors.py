"""Honors designation calculation per SCAFFOLD `honors_designation` / PRD §3.7."""

import db


def find_covering_policy(program_id, catalog_year):
    """HonorsPolicy of the program whose CLOSED [effective_first_year,
    effective_last_year] contains catalog_year."""
    for p in db.honors_policies.values():
        if p["program_id"] != program_id:
            continue
        if p["effective_first_year"] <= catalog_year <= p["effective_last_year"]:
            return p
    return None


def compute_honors_designation(student, policy):
    """Return NONE | CUM_LAUDE | MAGNA_CUM_LAUDE | SUMMA_CUM_LAUDE."""
    # Residency gate first
    if student["institutional_earned_credits"] < policy["residency_min_credits"]:
        return "NONE"
    if policy["honors_gpa_basis"] == "INSTITUTIONAL":
        basis = student["institutional_gpa"]
    else:
        basis = student["cumulative_gpa"]
    if basis >= policy["summa_threshold"]:
        return "SUMMA_CUM_LAUDE"
    if basis >= policy["magna_threshold"]:
        return "MAGNA_CUM_LAUDE"
    if basis >= policy["cum_threshold"]:
        return "CUM_LAUDE"
    return "NONE"
