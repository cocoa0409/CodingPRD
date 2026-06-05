"""FK reverse-reachability list endpoints and filter parameters.

Covers corner queue (B) second 'entities' section (Listing claims).
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    make_taxpayer_headers,
    make_hearing_officer_headers,
    create_owner,
    create_open_roll,
    create_parcel,
    create_assessment,
    claim_exemption,
    setup_draft_assessment,
    setup_final_assessment,
    setup_filed_appeal,
    setup_scheduled_hearing,
    setup_deferral_with_accrual,
)
from test_helpers import factories as f

ASSESSOR = TEST_USERS["assessor_headers"]


def test_list_exemptions_by_assessment(api):
    """PRD §4 (GET /assessments/{id}/exemptions): "List exemptions on an assessment".
    PRD §2.6: "Several read endpoints are nested under a parent — for example, the
    assessments of a parcel, the exemptions of an assessment".

    Design: Corner/entities/fk_reverse_list_exemptions_by_assessment
    """
    owner, roll, parcel, asmt = setup_draft_assessment(
        market_value=100000, reassessment_event="NONE",
        owner_overrides={"is_veteran": True}, parcel_overrides={"is_primary_residence": True},
    )
    claim_exemption(asmt["id"], "HOMESTEAD")
    claim_exemption(asmt["id"], "VETERAN")
    data, meta = validate_paginated(api.list_assessment_exemptions(asmt["id"], ASSESSOR))
    assert len(data) == 2
    assert all(item["assessment_id"] == asmt["id"] for item in data)


def test_list_payments_by_deferral(api):
    """PRD §3.9: "The payments applied to an agreement are retrievable as a list."

    Design: Corner/entities/fk_reverse_list_payments_by_deferral
    """
    owner, roll, parcel, final, bill, deferral = setup_deferral_with_accrual(
        principal_market=200000, annual_interest_rate=0.05
    )
    validate_success(
        api.create_payment(deferral["id"], f.create_payment_payload(3000, deferral["version"]), ASSESSOR),
        expected_status=201,
    )
    data, meta = validate_paginated(api.list_deferral_payments(deferral["id"], ASSESSOR))
    assert len(data) == 1
    assert data[0]["deferral_agreement_id"] == deferral["id"]


def test_list_hearings_by_panel(api):
    """PRD §3.7: "The hearings on a given appeal, and the hearings on a given panel, are each
    retrievable as a list."

    Design: Corner/entities/fk_reverse_list_hearings_by_panel
    """
    owner, roll, parcel, asmt, appeal, panel, hearing, ho_id = setup_scheduled_hearing(
        market_value=100000
    )
    data, meta = validate_paginated(
        api.list_panel_hearings(panel["id"], make_hearing_officer_headers(ho_id))
    )
    assert len(data) == 1
    assert data[0]["board_panel_id"] == panel["id"]


def test_list_appeals_by_owner(api):
    """PRD §3.6: "Appeals are listed in `created_at` order and may be filtered by
    `assessment_id` and by `filed_by_owner_id`."

    Design: Corner/entities/fk_reverse_list_appeals_by_owner
    """
    owner, roll, parcel, asmt, appeal = setup_filed_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    data, meta = validate_paginated(
        api.list_appeals(ASSESSOR, params={"filed_by_owner_id": owner["id"]})
    )
    assert len(data) == 1
    assert data[0]["filed_by_owner_id"] == owner["id"]


def test_list_bills_by_assessment(api):
    """PRD §3.8: "The bills belonging to an assessment are retrievable as a list."

    Design: Corner/entities/fk_reverse_list_bills_by_assessment
    """
    owner, roll, parcel, final = setup_final_assessment(market_value=100000, reassessment_event="SALE")
    bill = validate_success(api.issue_bill(final["id"], ASSESSOR), expected_status=201)
    data, meta = validate_paginated(api.list_assessment_bills(final["id"], ASSESSOR))
    assert len(data) == 1
    assert data[0]["assessment_id"] == final["id"]


def test_list_deferrals_by_parcel(api):
    """PRD §3.2: "The set of assessments and the set of deferral agreements belonging to a
    parcel are each retrievable as a list."

    Design: Corner/entities/fk_reverse_list_deferrals_by_parcel
    """
    owner = create_owner(birth_date="1950-01-01T00:00:00.000Z")
    parcel = create_parcel(owner["id"], is_primary_residence=True)
    deferral = validate_success(
        api.create_deferral(f.create_deferral_payload(parcel["id"], owner["id"], 0.05), ASSESSOR),
        expected_status=201,
    )
    data, meta = validate_paginated(api.list_parcel_deferrals(parcel["id"], ASSESSOR))
    assert len(data) == 1
    assert data[0]["parcel_id"] == parcel["id"]


def test_list_assessments_by_parcel(api):
    """PRD §3.2: "The set of assessments and the set of deferral agreements belonging to a
    parcel are each retrievable as a list."

    Design: Corner/entities/fk_reverse_list_assessments_by_parcel
    """
    owner = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(owner["id"])
    create_assessment(parcel["id"], roll["id"], 100000, reassessment_event="NONE")
    data, meta = validate_paginated(api.list_parcel_assessments(parcel["id"], ASSESSOR))
    assert len(data) == 1
    assert data[0]["parcel_id"] == parcel["id"]


def test_list_hearings_by_appeal(api):
    """PRD §3.7: "The hearings on a given appeal, and the hearings on a given panel, are each
    retrievable as a list."

    Design: Corner/entities/fk_reverse_list_hearings_by_appeal
    """
    owner, roll, parcel, asmt, appeal, panel, hearing, ho_id = setup_scheduled_hearing(
        market_value=100000
    )
    data, meta = validate_paginated(
        api.list_appeal_hearings(appeal["id"], make_hearing_officer_headers(ho_id))
    )
    assert len(data) == 1
    assert data[0]["appeal_id"] == appeal["id"]


def test_list_appeals_by_assessment(api):
    """PRD §3.6: "Appeals are listed in `created_at` order and may be filtered by
    `assessment_id` and by `filed_by_owner_id`."

    Design: Corner/entities/fk_reverse_list_appeals_by_assessment
    """
    owner, roll, parcel, asmt, appeal = setup_filed_appeal(
        requested_taxable_value=80000, market_value=100000
    )
    data, meta = validate_paginated(api.list_assessment_appeals(asmt["id"], ASSESSOR))
    assert len(data) == 1
    assert data[0]["assessment_id"] == asmt["id"]


def test_assessments_filtered_by_tax_roll(api):
    """PRD §3.3: "Assessments are listed in `created_at` order and may be filtered by
    `tax_roll_id` and by `parcel_id`."

    Design: Corner/entities/fk_reverse_assessments_filtered_by_tax_roll
    """
    owner = create_owner()
    roll = create_open_roll()
    parcel = create_parcel(owner["id"])
    create_assessment(parcel["id"], roll["id"], 100000, reassessment_event="NONE")
    data, meta = validate_paginated(api.list_assessments(ASSESSOR, params={"tax_roll_id": roll["id"]}))
    assert len(data) == 1
    assert data[0]["tax_roll_id"] == roll["id"]


def test_tax_rolls_filtered_by_prior_roll(api):
    """PRD §3.1: "Rolls are listed in `created_at` order and may be filtered by
    `prior_roll_id`."

    Design: Corner/entities/fk_reverse_taxroll_prior_roll_filter
    """
    roll1 = create_open_roll(tax_year=2025)
    validate_success(api.certify_tax_roll(roll1["id"], ASSESSOR))  # empty roll certifies
    roll2 = validate_success(
        api.create_tax_roll(f.create_tax_roll_payload(tax_year=2026, prior_roll_id=roll1["id"]), ASSESSOR),
        expected_status=201,
    )
    data, meta = validate_paginated(api.list_tax_rolls(ASSESSOR, params={"prior_roll_id": roll1["id"]}))
    assert len(data) == 1
    assert data[0]["prior_roll_id"] == roll1["id"]


def test_parcels_filtered_by_owner(api):
    """PRD §3.2: "Parcels are listed in `created_at` order, filterable by `owner_id`".

    Design: Corner/entities/fk_reverse_parcels_filtered_by_owner
    """
    owner = create_owner()
    parcel = create_parcel(owner["id"])
    data, meta = validate_paginated(api.list_parcels(ASSESSOR, params={"owner_id": owner["id"]}))
    assert len(data) == 1
    assert data[0]["owner_id"] == owner["id"]


def test_deferral_owner_id_exposed_via_parcel_list(api):
    """PRD §3.2: "The set of assessments and the set of deferral agreements belonging to a
    parcel are each retrievable as a list."
    PRD §3.9: "a deferral agreement the assessor opens against a `parcel_id`, the `owner_id`
    granted the deferral".

    Design: Corner/entities/fk_reverse_deferral_owner_via_parcel_list
    """
    owner = create_owner(birth_date="1950-01-01T00:00:00.000Z")
    parcel = create_parcel(owner["id"], is_primary_residence=True)
    validate_success(
        api.create_deferral(f.create_deferral_payload(parcel["id"], owner["id"], 0.05), ASSESSOR),
        expected_status=201,
    )
    data, meta = validate_paginated(api.list_parcel_deferrals(parcel["id"], ASSESSOR))
    assert data[0]["owner_id"] == owner["id"]
    assert data[0]["parcel_id"] == parcel["id"]
