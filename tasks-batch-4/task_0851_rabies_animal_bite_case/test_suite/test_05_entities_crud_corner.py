"""Breadth probes: entity creation, computed fields, defaults, required-field
and enum validation, and not-found reads.

Covers Corner section `entities`.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_owner,
    assert_bite_case,
    assert_animal,
    create_owner_payload,
    create_bite_case_payload,
)


def test_owner_creation_returns_201_compliant_zero_balance(api, intake_officer_headers):
    """PRD §3.1: "A newly registered owner starts `COMPLIANT` with
    `outstanding_fines_cents` of zero."

    Design: Corner/entities/owner_creation_returns_201_compliant_zero_balance
    """
    owner = validate_success(
        api.create_owner(create_owner_payload(full_name="Mia Owner", phone="555-0200"),
                         intake_officer_headers), 201)
    assert_owner(owner)
    assert owner["compliance_status"] == "COMPLIANT"
    assert owner["outstanding_fines_cents"] == 0


def test_unidentified_animal_case_risk_high_initiate(api, intake_officer_headers):
    """PRD §3.1: "Otherwise, if there is no `animal_id`, or the referenced
    animal's `identified` flag is false, or that animal's status is `AT_LARGE`,
    the `risk_level` is `HIGH` — an animal that cannot be produced for
    observation is treated as the worst case."
    PRD §3.1: "`NONE` maps to `NOT_INDICATED`, `LOW` maps to `DEFER`, `MODERATE`
    maps to `INITIATE`, and `HIGH` maps to `INITIATE`."

    Design: Corner/entities/bite_case_unidentified_animal_risk_high_empty_set
    """
    case = validate_success(
        api.create_bite_case(create_bite_case_payload(
            region_code="RB-C1", wound_category="CATEGORY_III", victim_name="W1", victim_age=40),
            intake_officer_headers), 201)
    assert_bite_case(case)
    assert case["risk_level"] == "HIGH"
    assert case["pep_indication"] == "INITIATE"
    assert case["status"] == "OPEN"


def test_animal_creation_defaults_vaccination_unknown_status_reported(api, intake_officer_headers):
    """PRD §3.1: "A new animal begins in status `REPORTED`, with `disposition`
    `NONE` and `control_status` `NONE`."
    PRD §3.1: "`vaccination_status` (one of `CURRENT`, `EXPIRED`, `UNKNOWN`, or
    `NONE`, defaulting to `UNKNOWN`)".

    Design: Corner/entities/animal_creation_defaults_vaccination_unknown_status_reported
    """
    animal = validate_success(
        api.create_animal({"species": "CAT", "animal_class": "DOMESTIC"},
                          intake_officer_headers), 201)
    assert_animal(animal)
    assert animal["vaccination_status"] == "UNKNOWN"
    assert animal["status"] == "REPORTED"
    assert animal["control_status"] == "NONE"


def test_bite_case_missing_wound_category_rejected(api, intake_officer_headers):
    """PRD §2.10: "then request well-formedness — required fields present, enum
    values legal, `victim_age` not negative, and `violations` non-empty — which
    otherwise yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/bite_case_missing_required_wound_category_returns_invalid_request
    """
    payload = create_bite_case_payload(region_code="RB-C2", victim_name="W2", victim_age=30)
    del payload["wound_category"]
    resp = api.create_bite_case(payload, intake_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_bite_case_invalid_exposure_type_enum_rejected(api, intake_officer_headers):
    """PRD §2.10: "then request well-formedness — required fields present, enum
    values legal, `victim_age` not negative, and `violations` non-empty — which
    otherwise yields `ERR_INVALID_REQUEST`."

    Design: Corner/entities/bite_case_invalid_enum_exposure_type_rejected
    """
    payload = create_bite_case_payload(region_code="RB-C3", exposure_type="HUG",
                                       victim_name="W3", victim_age=30)
    resp = api.create_bite_case(payload, intake_officer_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_get_owner_not_found_returns_404(api, health_dept_admin_headers):
    """PRD §2.9: "the first identifier that does not resolve to an existing
    resource produces that resource's specific not-found error — for example a
    missing owner yields `ERR_OWNER_NOT_FOUND`".

    Design: Corner/entities/get_owner_not_found_returns_404
    """
    resp = api.get_owner(NON_EXISTENT_UUID, health_dept_admin_headers)
    validate_error(resp, ApiErrorId.ERR_OWNER_NOT_FOUND)
