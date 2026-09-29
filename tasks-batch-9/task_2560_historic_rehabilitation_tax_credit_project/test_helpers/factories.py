"""Payload builders.

Every builder returns a plain dict of a valid request body, so a test can spread
it and override exactly the one field it is exercising. Names are uniquified with
a process counter, which keeps rows distinguishable inside a single test even
though the database starts empty for each one.
"""

import itertools

from . import constants

_counter = itertools.count(1)


def _seq():
    return next(_counter)


def developer_payload(**overrides):
    """A valid Developer body (PRD §3.1)."""
    index = _seq()
    payload = {
        "legal_name": "Beacon Rehabilitation Partners {0} LLC".format(index),
        "taxpayer_id_last4": "{0:04d}".format(1000 + (index % 9000)),
        "entity_type": "LLC",
        "contact_email": "principal{0}@beacon-rehab.example".format(index),
    }
    payload.update(overrides)
    return payload


def reviewer_payload(agency="SHPO", **overrides):
    """A valid Reviewer body (PRD §3.1)."""
    index = _seq()
    payload = {
        "full_name": "{0} Reviewer {1}".format(agency.title(), index),
        "agency": agency,
        "state_code": "MA",
        "credential_status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def property_payload(**overrides):
    """A valid Property body (PRD §3.1)."""
    index = _seq()
    payload = {
        "name": "Old Mill Building {0}".format(index),
        "street_address": "{0} Canal Street".format(100 + index),
        "city": "Lowell",
        "state_code": "MA",
        "year_built": 1902,
        "listing_status": "INDIVIDUAL_LISTED",
    }
    payload.update(overrides)
    return payload


def project_payload(developer_id, property_id, **overrides):
    """A valid Project body (PRD §3.2)."""
    index = _seq()
    payload = {
        "developer_id": developer_id,
        "property_id": property_id,
        "project_name": "Mill Conversion Phase {0}".format(index),
        "structure_type": "SINGLE_TIER",
        "adjusted_basis_cents": constants.TEST_DEFAULTS["ADJUSTED_BASIS_CENTS"],
        "measuring_period_months": constants.TEST_DEFAULTS["MEASURING_PERIOD_MONTHS"],
        "measuring_period_start_date": constants.TEST_DEFAULTS[
            "MEASURING_PERIOD_START"
        ],
    }
    payload.update(overrides)
    return payload


def part_application_payload(project_id, part_number, expected_project_version, **overrides):
    """A valid PartApplication body (PRD §3.3)."""
    payload = {
        "project_id": project_id,
        "part_number": part_number,
        "narrative": (
            "Part {0} narrative: the rehabilitation retains the historic "
            "character-defining features of the mill.".format(part_number)
        ),
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def finding_payload(**overrides):
    """A valid StandardFinding body (PRD §3.4)."""
    payload = {
        "standard_number": 2,
        "severity": "CONDITION",
        "description": (
            "The proposed storefront alteration must retain the original "
            "cast-iron piers."
        ),
    }
    payload.update(overrides)
    return payload


def cost_line_item_payload(project_id, **overrides):
    """A valid CostLineItem body (PRD §3.6)."""
    index = _seq()
    payload = {
        "project_id": project_id,
        "vendor_name": "Granite State Contracting {0}".format(index),
        "category": "HARD_CONSTRUCTION",
        "amount_cents": 10_000_000,
        "incurred_date": constants.TEST_DEFAULTS["IN_PERIOD_DATE"],
    }
    payload.update(overrides)
    return payload


def amendment_payload(project_id, part_application_id, **overrides):
    """A valid Amendment body (PRD §3.5)."""
    payload = {
        "project_id": project_id,
        "part_application_id": part_application_id,
        "scope_category": "WINDOW_REPLACEMENT",
        "change_description": (
            "Revised window schedule: repair the original double-hung sash in "
            "place rather than replace."
        ),
        "cost_delta_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def investor_interest_payload(project_id, **overrides):
    """A valid InvestorInterest body (PRD §3.7)."""
    index = _seq()
    payload = {
        "project_id": project_id,
        "kind": "DIRECT_PARTNER",
        "party_legal_name": "Harbor Tax Credit Fund {0}".format(index),
        "party_tax_status": "TAXABLE_C_CORP",
        "capital_committed_cents": constants.TEST_DEFAULTS["CAPITAL_COMMITTED_CENTS"],
        "credit_allocation_pct": constants.TEST_DEFAULTS["CREDIT_ALLOCATION_PCT"],
    }
    payload.update(overrides)
    return payload


def master_lease_interest_payload(project_id, **overrides):
    """A master-lease lessee interest, which carries a lease term (PRD §3.7)."""
    payload = investor_interest_payload(
        project_id,
        kind="MASTER_LEASE_LESSEE",
        party_tax_status="PARTNERSHIP",
        lease_term_years=constants.TEST_DEFAULTS["LEASE_TERM_YEARS"],
    )
    payload.update(overrides)
    return payload


def credit_claim_payload(project_id, **overrides):
    """A valid CreditClaim body (PRD §3.9)."""
    payload = {
        "project_id": project_id,
        "tax_year": constants.TEST_DEFAULTS["FIRST_TAX_YEAR"],
    }
    payload.update(overrides)
    return payload


def compliance_covenant_payload(project_id, **overrides):
    """A valid ComplianceCovenant body (PRD §3.8)."""
    payload = {
        "project_id": project_id,
        "covenant_type": "USE_RESTRICTION",
        "monitoring_frequency": "ANNUAL",
        "window_start_date": "2029-01-15",
        "window_end_date": "2030-01-14",
    }
    payload.update(overrides)
    return payload


def recapture_event_payload(project_id, **overrides):
    """A valid RecaptureEvent body (PRD §3.8)."""
    payload = {
        "project_id": project_id,
        "event_type": "COVENANT_BREACH",
        "event_date": "2030-01-20",
    }
    payload.update(overrides)
    return payload
