"""Run import, charge synthesis, and the level-of-service coding calculations.

Tests translate difficulty queue (combinatorial_formula, non_linear_state_machine,
boundary_precision_check) and corner queue (entities, calculations, state_machines).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    setup_agency_org,
    create_patient_with_coverages,
    import_transport,
    code_transport,
    make_billing_admin_headers,
    NON_EXISTENT_UUID,
)
from test_helpers import factories as F


# ---------------------------------------------------------------------------
# combinatorial_formula / mileage_round_per_tier_then_sum_rural  (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_rural_mileage_rounds_each_tier_before_summing(api):
    """PRD §3.3: "it then computes the rural tier as the rural miles multiplied by
    1750 cents and by the rural bonus factor of 1.5, rounds that tier half up to a
    whole cent, computes the normal tier as the normal miles multiplied by 1750
    cents, rounds that tier half up to a whole cent, and sums the two rounded tiers."
    PRD §3.3: "When `is_rural_pickup` is true, the system splits the mileage into a
    rural portion equal to the lesser of the loaded miles and 17.0 and a normal
    portion equal to the loaded miles minus 17.0 but not below zero".

    Design: Difficulty/combinatorial_formula/mileage_round_per_tier_then_sum_rural
    """
    org = setup_agency_org(state_code="MT")
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "R20", origin_modifier="R", destination_modifier="H",
                         loaded_miles=20.0, is_rural_pickup=True, emergency_indicator=False)
    code_transport(org, t["id"], "BLS")

    data, _meta = validate_paginated(api.list_transport_charges(t["id"], org["coder_h"]))
    by_type = {c["charge_type"]: c for c in data}
    # rural tier1 = round(17*1750*1.5)=44625; normal tier2 = round(3*1750)=5250; sum 49875
    assert by_type["MILEAGE"]["billed_amount_cents"] == 49875, \
        f"expected per-tier rural mileage 49875, got {by_type['MILEAGE']['billed_amount_cents']}"
    assert by_type["BASE_RATE"]["billed_amount_cents"] == 45000, "BLS non-emergency base A0428 = 45000"


def test_rural_coding_recomputes_total_billed(api):
    """PRD §3.3: "Coding assigns the `level_of_service`, resolves the two HCPCS lines,
    synthesizes the two `Charge` rows, recomputes `total_billed_cents` as the sum of
    those charges, and recomputes `balance_cents`."

    Design: Difficulty/combinatorial_formula/mileage_round_per_tier_then_sum_rural
    """
    org = setup_agency_org(state_code="MT")
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "R20b", origin_modifier="R", destination_modifier="H",
                         loaded_miles=20.0, is_rural_pickup=True, emergency_indicator=False)
    coded = code_transport(org, t["id"], "BLS")
    # 45000 base + 49875 mileage = 94875
    assert coded["total_billed_cents"] == 94875, \
        f"expected total_billed 94875, got {coded['total_billed_cents']}"


# ---------------------------------------------------------------------------
# non_linear_state_machine / transport_parallel_documentation_and_billing_dimensions
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_coding_advances_documentation_without_touching_billing(api):
    """PRD §2.8: "A `Transport` advances along two independent state dimensions."
    PRD §3.3: "Coding the transport advances `documentation_status` from `IMPORTED`
    to `CODED` and is performed by a `Coder`".

    Design: Difficulty/non_linear_state_machine/transport_parallel_documentation_and_billing_dimensions
    """
    org = setup_agency_org()
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "PAR1", loaded_miles=10.0, emergency_indicator=True)
    coded = code_transport(org, t["id"], "BLS")
    assert coded["documentation_status"] == "CODED"
    assert coded["billing_status"] == "UNBILLED", \
        "billing dimension must stay UNBILLED while documentation advances"


def test_import_initializes_both_dimensions_at_start_states(api):
    """PRD §3.3: "A freshly imported transport begins with `documentation_status`
    `IMPORTED` and `billing_status` `UNBILLED`, with its `level_of_service` null".

    Design: Difficulty/non_linear_state_machine/transport_parallel_documentation_and_billing_dimensions
    """
    org = setup_agency_org()
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "PAR2", loaded_miles=10.0, emergency_indicator=True)
    assert t["documentation_status"] == "IMPORTED"
    assert t["billing_status"] == "UNBILLED"
    assert t["level_of_service"] is None


# ---------------------------------------------------------------------------
# boundary_precision_check / loaded_miles_zero_rejected_smallest_positive_accepted
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_loaded_miles_zero_rejected(api):
    """PRD §3.3: "The `loaded_miles` is the odometer loaded mileage (patient onboard)
    to one decimal place and must be strictly greater than zero; a `loaded_miles` of
    zero or less is rejected with `ERR_INVALID_LOADED_MILES` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/loaded_miles_zero_rejected_smallest_positive_accepted
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    payload = F.create_transport_payload(org["agency"]["id"], pat["id"], "Z0",
                                         loaded_miles=0, emergency_indicator=True)
    resp = api.create_transport(payload, org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_LOADED_MILES.value)


def test_loaded_miles_smallest_positive_accepted(api):
    """PRD §3.3: "must be strictly greater than zero; a `loaded_miles` of zero or
    less is rejected with `ERR_INVALID_LOADED_MILES` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/loaded_miles_zero_rejected_smallest_positive_accepted
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    payload = F.create_transport_payload(org["agency"]["id"], pat["id"], "Z1",
                                         loaded_miles=0.1, emergency_indicator=True)
    resp = api.create_transport(payload, org["dispatcher_h"])
    data = validate_success(resp, expected_status=201)
    assert data["loaded_miles"] == 0.1


# ---------------------------------------------------------------------------
# corner / entities
# ---------------------------------------------------------------------------

def test_create_agency_returns_201_with_defaults(api):
    """PRD §3.1: "The `base_state_is_no_surprises` flag — defaulting to false".
    PRD §3.1: "The `charity_fpl_threshold_pct` — defaulting to 200".
    PRD §3.1: "A new agency is created with `status` `ACTIVE`."

    Design: Corner/entities/create_agency_returns_201_with_defaults
    """
    admin = make_billing_admin_headers()
    resp = api.create_agency(F.create_agency_payload(name="Boot EMS", state_code="TX"), admin)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "ACTIVE"
    assert data["base_state_is_no_surprises"] is False
    assert data["charity_fpl_threshold_pct"] == 200
    assert data["version"] == 1


def test_get_transport_not_found_returns_404(api):
    """PRD §2.5: "the system validates each identifier left-to-right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first path segment whose resource
    does not exist".

    Design: Corner/entities/get_transport_not_found_returns_404
    """
    admin = make_billing_admin_headers()
    resp = api.get_transport(NON_EXISTENT_UUID, admin)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_transport_missing_required_field(api):
    """PRD §3.11: "the request shape is checked: required body fields present and
    well-typed (such as `loaded_miles`, `dispatch_iso`, `origin_modifier`,
    `run_number`, and `level_of_service` on coding) yield `ERR_INVALID_REQUEST`
    when violated".

    Design: Corner/entities/create_transport_missing_required_field_returns_invalid_request
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    payload = {
        "agency_id": org["agency"]["id"],
        "patient_id": pat["id"],
        "run_number": "MISS1",
        "dispatch_iso": "2026-06-11T08:00:00.000Z",
        "destination_modifier": "H",
        "loaded_miles": 10.0,
    }  # origin_modifier omitted
    resp = api.create_transport(payload, org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_transport_invalid_origin_enum(api):
    """PRD §3.11: "enum fields carrying a value outside their allowed set
    (`origin_modifier`, `destination_modifier`, `level_of_service`, `payer_type`,
    `outcome`, `adjustment_type`) yield `ERR_INVALID_ENUM`."

    Design: Corner/entities/create_transport_invalid_origin_enum_returns_invalid_enum
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    payload = F.create_transport_payload(org["agency"]["id"], pat["id"], "ENUM1",
                                         origin_modifier="Z", loaded_miles=10.0)
    resp = api.create_transport(payload, org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_create_transport_nonexistent_patient(api):
    """PRD §2.5: "Foreign-key targets named in the request body — `payer_plan_id`,
    `patient_id`, `prior_claim_id`, `agency_id`, `transport_id`, and `claim_id` —
    are validated only after the path resolves; a missing body FK target is rejected
    with `ERR_REFERENCED_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/create_transport_with_nonexistent_patient_returns_referenced_not_found
    """
    org = setup_agency_org(with_compliance=False)
    payload = F.create_transport_payload(org["agency"]["id"], NON_EXISTENT_UUID, "FK1",
                                         loaded_miles=10.0)
    resp = api.create_transport(payload, org["dispatcher_h"])
    validate_error(resp, ApiErrorId.ERR_REFERENCED_RESOURCE_NOT_FOUND.value)


def test_transport_computed_fields_initialized_on_import(api):
    """PRD §3.3: "with its `level_of_service` null, `medical_necessity_met` false,
    `pcs_signed` false, and every derived ledger total — `total_billed_cents`,
    `total_allowed_cents`, `total_paid_cents`, `total_writeoff_cents`,
    `patient_responsibility_cents`, and `balance_cents` — at zero."

    Design: Corner/entities/transport_computed_fields_initialized_on_import
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "COMP1", loaded_miles=10.0, emergency_indicator=True)
    assert t["level_of_service"] is None
    assert t["documentation_status"] == "IMPORTED"
    assert t["billing_status"] == "UNBILLED"
    assert t["total_billed_cents"] == 0


def test_list_transports_pagination_envelope(api):
    """PRD §2.3: "List responses include `limit`, `offset`, `total_count`, and
    `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/list_transports_pagination_envelope
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    import_transport(org, pat["id"], "L1", loaded_miles=10.0)
    resp = api.list_transports(org["admin_h"], params={"agency_id": org["agency"]["id"],
                                                       "limit": 10, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    assert meta["has_more"] is False


# ---------------------------------------------------------------------------
# corner / calculations  (coding-time charge split)
# ---------------------------------------------------------------------------

def test_sct_base_rate_and_mileage_charge_split(api):
    """PRD §3.3: "For `SCT`, the base code is always `A0434`."
    PRD §3.3: "The mileage line always uses the ground-mileage code `A0425`."
    PRD §3.3: "`A0434` is 130000 cents" (base-rate schedule) and "The `MILEAGE`
    line's `billed_amount_cents` is computed at 1750 cents per loaded mile".

    Design: Corner/calculations/sct_base_rate_and_mileage_charge_split
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_transport(org, pat["id"], "SCT1", origin_modifier="H", destination_modifier="H",
                         loaded_miles=8.0, emergency_indicator=True)
    coded = code_transport(org, t["id"], "SCT")
    assert coded["total_billed_cents"] == 144000, "A0434 130000 + 8*1750 14000 = 144000"

    charges, _meta = validate_paginated(api.list_transport_charges(t["id"], org["coder_h"]))
    by_type = {c["charge_type"]: c for c in charges}
    assert by_type["BASE_RATE"]["hcpcs_code"] == "A0434"
    assert by_type["BASE_RATE"]["billed_amount_cents"] == 130000
    assert by_type["MILEAGE"]["hcpcs_code"] == "A0425"
    assert by_type["MILEAGE"]["billed_amount_cents"] == 14000
