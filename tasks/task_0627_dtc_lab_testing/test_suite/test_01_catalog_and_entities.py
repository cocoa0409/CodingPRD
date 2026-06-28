"""Breadth tests for catalog/entity creation, defaults, retrieval, validation,
and uniqueness.
"""
from test_helpers import (
    validate_success,
    validate_error,
    factories as F,
    fixtures as fx,
    make_patient_headers,
    ApiErrorId,
    TEST_USERS,
)

ADMIN = TEST_USERS["catalog_admin_headers"]


# ---------------------------------------------------------------------------
# Corner/entities/create_test_offering_returns_201_with_system_fields
# ---------------------------------------------------------------------------
def test_create_test_offering_defaults_active_version_one(api):
    """PRD 3.1: "A newly created offering is minted with status set to ACTIVE."
    PRD 2.4: "a version integer that begins at its initial value and increments
    by one on each mutation."

    Design: Corner/entities/create_test_offering_returns_201_with_system_fields
    """
    created = validate_success(
        api.create_test_offering(
            F.create_test_offering_payload(test_code="CBC", display_name="Complete Blood Count", list_price_cents=5500, specimen_type="BLOOD"),
            ADMIN,
        ),
        expected_status=201,
    )
    assert created["status"] == "ACTIVE"
    assert created["version"] == 1
    assert created["list_price_cents"] == 5500


# ---------------------------------------------------------------------------
# Corner/entities/get_offering_not_found_returns_404
# ---------------------------------------------------------------------------
def test_get_offering_not_found_returns_404(api):
    """PRD 2.5: "the first identifier that fails to resolve causes immediate
    rejection with ERR_NOT_FOUND before any business rule runs."

    Design: Corner/entities/get_offering_not_found_returns_404
    """
    resp = api.get_test_offering("00000000-0000-4000-8000-000000000abc", ADMIN)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ---------------------------------------------------------------------------
# Corner/entities/create_offering_missing_required_field_returns_422
# ---------------------------------------------------------------------------
def test_create_offering_missing_required_field_returns_422(api):
    """PRD 2.5: "then request-body well-formedness — required fields present, enum
    values within their domain, and integers non-negative where required
    (ERR_INVALID_REQUEST)".
    PRD 3.1: "A test offering is created with a catalog test_code, a patient-facing
    display_name, a self-pay list_price_cents that must be greater than zero, and a
    specimen_type".

    Design: Corner/entities/create_offering_missing_required_field_returns_422
    """
    resp = api.create_test_offering(
        {"test_code": "NOPRICE", "display_name": "No Price", "specimen_type": "BLOOD"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner/entities/create_offering_invalid_specimen_enum_returns_422
# ---------------------------------------------------------------------------
def test_create_offering_invalid_specimen_enum_returns_422(api):
    """PRD 2.5: "then request-body well-formedness — required fields present, enum
    values within their domain, and integers non-negative where required
    (ERR_INVALID_REQUEST)".
    PRD 3.1: "a specimen_type that is one of BLOOD, URINE, or SALIVA."

    Design: Corner/entities/create_offering_invalid_specimen_enum_returns_422
    """
    resp = api.create_test_offering(
        {"test_code": "BADTYPE", "display_name": "Bad Type", "list_price_cents": 1000, "specimen_type": "TISSUE"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Corner/entities/duplicate_test_code_returns_409
# ---------------------------------------------------------------------------
def test_duplicate_test_code_returns_409(api):
    """PRD 3.1: "A test_code must be unique among non-ARCHIVED offerings; a
    collision is rejected with ERR_DUPLICATE_CODE."

    Design: Corner/entities/duplicate_test_code_returns_409
    """
    fx.create_offering(api=api, test_code="DUP", display_name="Dup One", list_price_cents=1000, specimen_type="BLOOD")
    resp = api.create_test_offering(
        F.create_test_offering_payload(test_code="DUP", display_name="Dup Two", list_price_cents=2000, specimen_type="BLOOD"),
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value)


# ---------------------------------------------------------------------------
# Corner/entities/offering_home_kit_eligible_defaults_false
# ---------------------------------------------------------------------------
def test_offering_flag_defaults_false(api):
    """PRD 3.1: "Two boolean attributes, home_kit_eligible and requires_fasting,
    each default to false and govern fulfillment".

    Design: Corner/entities/offering_home_kit_eligible_defaults_false
    """
    created = validate_success(
        api.create_test_offering(
            {"test_code": "DEF", "display_name": "Default Flags", "list_price_cents": 1000, "specimen_type": "SALIVA"},
            ADMIN,
        ),
        expected_status=201,
    )
    assert created["home_kit_eligible"] is False
    assert created["requires_fasting"] is False


# ---------------------------------------------------------------------------
# Corner/entities/archived_offering_still_queryable
# ---------------------------------------------------------------------------
def test_archived_offering_still_queryable(api):
    """PRD 3.1: "An offering may be soft-deleted by archiving it, moving its status
    from ACTIVE to ARCHIVED. An ARCHIVED offering remains queryable".

    Design: Corner/entities/archived_offering_still_queryable
    """
    off = fx.create_offering(api=api, test_code="ARC", display_name="To Archive", list_price_cents=1000, specimen_type="BLOOD")
    fx.archive_offering(off["id"], api=api)
    got = validate_success(api.get_test_offering(off["id"], ADMIN))
    assert got["status"] == "ARCHIVED"


# ---------------------------------------------------------------------------
# Corner/entities/register_patient_duplicate_email_returns_409
# ---------------------------------------------------------------------------
def test_register_patient_duplicate_email_returns_409(api):
    """PRD 3.1: "A patient is registered with a unique email, a full_name, a
    date_of_birth as an ISO YYYY-MM-DD date, a two-letter state_code of residence,
    an optional starting hsa_balance_cents (defaulting to 0 and never negative),
    and an optional consent_share_results flag (defaulting to false)."
    PRD 3.1: "A duplicate email is rejected with ERR_DUPLICATE_CODE."

    Design: Corner/entities/register_patient_duplicate_email_returns_409
    """
    fx.create_patient(api=api, email="dup@x.com", full_name="Dup A", date_of_birth="1990-01-01", state_code="CA")
    resp = api.create_patient(
        {"email": "dup@x.com", "full_name": "Dup B", "date_of_birth": "1991-01-01", "state_code": "CA"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_CODE.value)


# ---------------------------------------------------------------------------
# Corner/entities/patient_hsa_and_consent_defaults
# ---------------------------------------------------------------------------
def test_patient_hsa_and_consent_defaults(api):
    """PRD 3.1: "an optional starting hsa_balance_cents (defaulting to 0 and never
    negative), and an optional consent_share_results flag (defaulting to false)."

    Design: Corner/entities/patient_hsa_and_consent_defaults
    """
    created = validate_success(
        api.create_patient(
            {"email": "defaults_corner@x.com", "full_name": "Defaults", "date_of_birth": "1990-01-01", "state_code": "CA"},
            ADMIN,
        ),
        expected_status=201,
    )
    assert created["hsa_balance_cents"] == 0
    assert created["consent_share_results"] is False


# ---------------------------------------------------------------------------
# Corner/entities/cart_id_is_system_minted_uuid_no_prefix
# ---------------------------------------------------------------------------
def test_new_cart_initial_state(api):
    """PRD 3.2: "A new cart begins in status OPEN with line_count, subtotal_cents,
    estimated_total_cents, estimated_hsa_applied_cents, and estimated_patient_due_cents
    all initialized to zero."

    Design: Corner/entities/cart_id_is_system_minted_uuid_no_prefix
    """
    patient = fx.create_patient(api=api, state_code="CA")
    cart = validate_success(
        api.create_cart(F.create_cart_payload(patient["id"], fund_source="CARD"), make_patient_headers(patient["id"])),
        expected_status=201,
    )
    assert cart["line_count"] == 0
    assert cart["subtotal_cents"] == 0
    assert cart["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Corner/entities/cart_fund_source_defaults_card
# ---------------------------------------------------------------------------
def test_cart_fund_source_defaults_card(api):
    """PRD 3.2: "an optional fund_source, which is either CARD or HSA_FSA and
    defaults to CARD."

    Design: Corner/entities/cart_fund_source_defaults_card
    """
    patient = fx.create_patient(api=api, state_code="CA")
    cart = validate_success(
        api.create_cart({"patient_id": patient["id"]}, make_patient_headers(patient["id"])),
        expected_status=201,
    )
    assert cart["fund_source"] == "CARD"
