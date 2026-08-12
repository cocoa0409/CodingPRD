"""Payload factories — one per creatable resource, input fields only.

Every factory accepts **overrides so tests control exactly the fields the
scenario varies while everything else gets a PRD-consistent default.
"""
import itertools

from .constants import AGREEMENT_STANDARD, TERM_FALL_2026, TEST_DEFAULTS

_isbn_counter = itertools.count(1)


def create_term_payload(**overrides) -> dict:
    defaults = dict(TERM_FALL_2026)
    defaults.update(overrides)
    return defaults


def create_publisher_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["PUBLISHER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = dict(AGREEMENT_STANDARD)
    defaults.update(overrides)
    return defaults


def create_title_payload(**overrides) -> dict:
    defaults = {
        "isbn": f"978{next(_isbn_counter):010d}"[-13:],
        "publisher_id": None,  # caller must supply
        "list_price_cents": TEST_DEFAULTS["LIST_PRICE_CENTS"],
        "has_new": True,
        "has_used": True,
        "has_rental": True,
        "has_digital": True,
    }
    defaults.update(overrides)
    return defaults


def create_wholesale_quote_payload(**overrides) -> dict:
    defaults = {
        "condition": "GOOD",
        "price_cents": 2200,
        "effective_from": "2026-12-01T00:00:00Z",
        "effective_to": "2027-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_faculty_payload(**overrides) -> dict:
    defaults = {
        "full_name": TEST_DEFAULTS["FACULTY_NAME"],
        "email": TEST_DEFAULTS["FACULTY_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Stu One",
        "email": "stu1@uni.edu",
        "awarded_aid_cents": TEST_DEFAULTS["STUDENT_AID"],
    }
    defaults.update(overrides)
    return defaults


def create_section_payload(**overrides) -> dict:
    defaults = {
        "term_id": None,  # caller must supply
        "faculty_id": None,  # caller must supply
        "course_code": TEST_DEFAULTS["COURSE_CODE"],
        "section_code": TEST_DEFAULTS["SECTION_CODE"],
        "enrollment_capacity": TEST_DEFAULTS["ENROLLMENT_CAPACITY"],
        "ia_enabled": False,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {"student_id": None}  # caller must supply
    defaults.update(overrides)
    return defaults


def create_adoption_payload(**overrides) -> dict:
    defaults = {
        "section_id": None,  # caller must supply
        "title_id": None,  # caller must supply
        "qty_new_requested": 0,
        "qty_used_requested": 0,
        "qty_rental_requested": 0,
        "qty_digital_requested": 0,
        "posted_price_cents": 10000,
        "expected_section_version": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def create_order_line_request(**overrides) -> dict:
    defaults = {
        "adoption_id": None,  # caller must supply
        "format": "NEW",
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "term_id": None,  # caller must supply
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_buyback_ticket_payload(**overrides) -> dict:
    defaults = {
        "title_id": None,  # caller must supply
        "condition": "GOOD",
        "upcoming_term_id": None,  # caller must supply
        "expected_title_version": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults


def create_commission_statement_payload(**overrides) -> dict:
    defaults = {
        "publisher_id": None,  # caller must supply
        "term_id": None,  # caller must supply
    }
    defaults.update(overrides)
    return defaults
