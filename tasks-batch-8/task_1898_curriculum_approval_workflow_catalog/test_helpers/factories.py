"""Payload factories — one per creatable resource, input fields only.

Defaults are chosen so the credit-hour workload check passes for the
standard 3-credit shape: (3 contact + 6 out-of-class) * 15 weeks / 45
Carnegie hours = 3.0 computed credits, within the inclusive 0.5 tolerance
of proposed_credit_hours 3 (PRD §3.4).
"""

# -------------------------------------------------------------------------
# Canonical term frames. All freeze instants sit after the logical clock's
# 2026-08-01T00:00:00Z startup default, so freshly created terms accept
# submissions until a test deliberately advances the clock.
# -------------------------------------------------------------------------
TERM_2026FA = {
    "term_code": "2026FA",
    "academic_year": "2026-2027",
    "sequence_index": 1,
    "classes_start_date": "2026-08-24",
    "classes_end_date": "2026-12-15",
    "proposal_freeze_at": "2026-10-01T00:00:00Z",
    "catalog_freeze_at": "2027-01-10T00:00:00Z",
}
TERM_2027SP = {
    "term_code": "2027SP",
    "academic_year": "2026-2027",
    "sequence_index": 2,
    "classes_start_date": "2027-01-16",
    "classes_end_date": "2027-05-10",
    "proposal_freeze_at": "2027-02-01T00:00:00Z",
    "catalog_freeze_at": "2027-05-20T00:00:00Z",
}
TERM_2027SU = {
    "term_code": "2027SU",
    "academic_year": "2026-2027",
    "sequence_index": 3,
    "classes_start_date": "2027-06-01",
    "classes_end_date": "2027-08-10",
    "proposal_freeze_at": "2027-05-01T00:00:00Z",
    "catalog_freeze_at": "2027-07-01T00:00:00Z",
}
TERM_2027FA = {
    "term_code": "2027FA",
    "academic_year": "2027-2028",
    "sequence_index": 4,
    "classes_start_date": "2027-08-24",
    "classes_end_date": "2027-12-15",
    "proposal_freeze_at": "2027-10-01T00:00:00Z",
    "catalog_freeze_at": "2027-11-01T00:00:00Z",
}

EDITION_2026_2027 = {
    "edition_label": "2026-2027 Catalog",
    "academic_year": "2026-2027",
    "year_start_date": "2026-08-01",
    "year_end_date": "2027-07-31",
}
EDITION_2027_2028 = {
    "edition_label": "2027-2028 Catalog",
    "academic_year": "2027-2028",
    "year_start_date": "2027-08-01",
    "year_end_date": "2028-07-31",
}


def create_department_payload(**overrides) -> dict:
    defaults = {
        "dept_name": "Computer Science",
        "subject_codes": ["CS"],
        "college": "Engineering",
    }
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = dict(TERM_2026FA)
    defaults.update(overrides)
    return defaults


def create_course_payload(owning_department_id, introduced_in_term_id,
                          **overrides) -> dict:
    defaults = {
        "subject_code": "CS",
        "course_number": "301",
        "title": "Systems",
        "credit_hours": 3,
        "contact_hours_per_week": 3,
        "out_of_class_hours_per_week": 6,
        "learning_outcomes": ["design systems"],
        "owning_department_id": owning_department_id,
        "introduced_in_term_id": introduced_in_term_id,
    }
    defaults.update(overrides)
    return defaults


def create_new_course_proposal_payload(proposer_department_id,
                                       requested_effective_term_id,
                                       proposed_course_number,
                                       **overrides) -> dict:
    defaults = {
        "proposal_type": "NEW_COURSE",
        "proposer_department_id": proposer_department_id,
        "requested_effective_term_id": requested_effective_term_id,
        "proposed_subject_code": "CS",
        "proposed_course_number": proposed_course_number,
        "proposed_title": "Compilers",
        "proposed_credit_hours": 3,
        "contact_hours_per_week": 3,
        "out_of_class_hours_per_week": 6,
        "learning_outcomes": ["build a compiler"],
        "justification": "curriculum gap",
    }
    defaults.update(overrides)
    return defaults


def create_course_change_proposal_payload(proposer_department_id,
                                          requested_effective_term_id,
                                          target_course_id,
                                          **overrides) -> dict:
    defaults = {
        "proposal_type": "COURSE_CHANGE",
        "proposer_department_id": proposer_department_id,
        "requested_effective_term_id": requested_effective_term_id,
        "target_course_id": target_course_id,
        "proposed_subject_code": "CS",
        "proposed_course_number": "301",
        "proposed_title": "Systems (revamped)",
        "proposed_credit_hours": 3,
        "contact_hours_per_week": 3,
        "out_of_class_hours_per_week": 6,
        "learning_outcomes": ["design modern systems"],
        "justification": "rebalance",
    }
    defaults.update(overrides)
    return defaults


def create_deactivation_proposal_payload(proposer_department_id,
                                         requested_effective_term_id,
                                         target_course_id,
                                         declared_remaining_cohorts,
                                         **overrides) -> dict:
    defaults = {
        "proposal_type": "DEACTIVATION",
        "proposer_department_id": proposer_department_id,
        "requested_effective_term_id": requested_effective_term_id,
        "target_course_id": target_course_id,
        "declared_remaining_cohorts": declared_remaining_cohorts,
        "justification": "obsolete content",
    }
    defaults.update(overrides)
    return defaults


def create_teach_out_plan_payload(enrolled_cohort_count, cohort_sizes,
                                  last_enrolled_term_id, **overrides) -> dict:
    defaults = {
        "enrolled_cohort_count": enrolled_cohort_count,
        "cohort_sizes": cohort_sizes,
        "last_enrolled_term_id": last_enrolled_term_id,
    }
    defaults.update(overrides)
    return defaults


def create_cross_listing_payload(home_course_id, partner_course_id,
                                 **overrides) -> dict:
    defaults = {
        "home_course_id": home_course_id,
        "partner_course_id": partner_course_id,
    }
    defaults.update(overrides)
    return defaults


def create_edition_payload(**overrides) -> dict:
    defaults = dict(EDITION_2026_2027)
    defaults.update(overrides)
    return defaults
