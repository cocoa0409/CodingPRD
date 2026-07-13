"""Certified-copy processing: dual-variant and combinatorial fee pricing,
public-record eligibility, the issue precondition ladder, and the void fee-ledger
compensation invariant."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    create_facility,
    create_vital_event,
    create_copy_request,
    verify_copy,
    event_version,
    setup_registered_birth_event,
    setup_id_verified_copy,
    create_copy_request_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
APPLICANT = TEST_USERS["applicant_headers"]


def _issue(api, copy_id, event_id):
    return api.issue_copy_request(
        copy_id, {"expected_vital_event_version": event_version(event_id)}, REGISTRAR
    )


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc / copy_fee_certified_vs_informational_same_copy_count
# ---------------------------------------------------------------------------
def test_copy_fee_certified_variant_standard_three_copies(api):
    """PRD §3.6: "For a `CERTIFIED` copy class, the base is a 1500-cent search fee
    plus 800 cents for each additional copy beyond the first, that is 800 cents
    times `copy_count` minus one; if `expedite` is true a 1900-cent surcharge is
    added to form the gross amount, and otherwise the gross equals the base."

    Design: Difficulty/dual_variant_calc/copy_fee_certified_vs_informational_same_copy_count
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-01",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="STANDARD",
        id_document_type="DRIVERS_LICENSE", copy_count=3, expedite=False,
    )
    issued = validate_success(_issue(api, copy["id"], ev["id"]))
    assert issued["copy_class"] == "CERTIFIED"
    assert issued["fee_total_cents"] == 3100


def test_copy_fee_informational_variant_same_copy_count(api):
    """PRD §3.6: "For an `INFORMATIONAL` copy class, the fee is a flat 1000 cents
    per copy — 1000 cents times `copy_count` — plus the 1900-cent expedite
    surcharge when `expedite` is true; informational copies carry no search fee
    and no category waiver, so veterans and indigent requesters pay the same as
    standard requesters."

    Design: Difficulty/dual_variant_calc/copy_fee_certified_vs_informational_same_copy_count
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-01",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="STANDARD",
        id_document_type="DRIVERS_LICENSE", copy_count=3, expedite=False,
    )
    set_clock("2102-01-01T00:00:00Z")  # record aged past the 75-year threshold
    issued = validate_success(_issue(api, copy["id"], ev["id"]))
    assert issued["copy_class"] == "INFORMATIONAL"
    assert issued["fee_total_cents"] == 3000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula / copy_fee_tiered_expedite_category_branch
# ---------------------------------------------------------------------------
def test_copy_fee_indigent_halved_rounds_half_up(api):
    """PRD §3.6: "The category then adjusts the gross: a `VETERAN` requester pays
    0, an `INDIGENT` requester pays the gross halved and rounded half up to a
    whole cent, and a `STANDARD` requester pays the full gross."

    Design: Difficulty/combinatorial_formula/copy_fee_tiered_expedite_category_branch
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-03",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="INDIGENT",
        id_document_type="STATE_ID", copy_count=3, expedite=False,
    )
    issued = validate_success(_issue(api, copy["id"], ev["id"]))
    assert issued["fee_total_cents"] == 1550  # round_half_up(3100 * 0.5)


def test_copy_fee_indigent_confidential_class_is_certified(api):
    """PRD §3.6: "When the age is below the threshold the record is confidential:
    `copy_class` is `CERTIFIED` only if `requester_relationship` is one of `SELF`,
    `PARENT`, `CHILD`, `SPOUSE`, `SIBLING`, `LEGAL_GUARDIAN`, or
    `LEGAL_REPRESENTATIVE`".

    Design: Difficulty/combinatorial_formula/copy_fee_tiered_expedite_category_branch
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-03",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="INDIGENT",
        id_document_type="STATE_ID", copy_count=3, expedite=False,
    )
    issued = validate_success(_issue(api, copy["id"], ev["id"]))
    assert issued["copy_class"] == "CERTIFIED"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / copy_request_zero_count_rejected_on_create
# ---------------------------------------------------------------------------
def test_copy_count_zero_rejected_on_create(api):
    """PRD §3.6: "a `copy_count` that must be at least one — a value below one is
    rejected with `ERR_INVALID_COPY_COUNT`".

    Design: Difficulty/boundary_precision_check/copy_request_zero_count_rejected_on_create
    """
    fac = create_facility(jurisdiction_code="CTY-16")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-16", sex="UNDETERMINED")
    resp = api.create_copy_request(
        create_copy_request_payload(
            ev["id"], requester_relationship="SELF", id_document_type="STATE_ID",
            copy_count=0,
        ),
        APPLICANT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_COPY_COUNT)


def test_copy_count_negative_rejected_on_create(api):
    """PRD §3.6: "a `copy_count` that must be at least one — a value below one is
    rejected with `ERR_INVALID_COPY_COUNT`".

    Design: Difficulty/boundary_precision_check/copy_request_zero_count_rejected_on_create
    """
    fac = create_facility(jurisdiction_code="CTY-16")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-16", sex="UNDETERMINED")
    resp = api.create_copy_request(
        create_copy_request_payload(
            ev["id"], requester_relationship="SELF", id_document_type="STATE_ID",
            copy_count=-1,
        ),
        APPLICANT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_COPY_COUNT)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / issue_event_not_registered_outprioritizes_not_eligible
# ---------------------------------------------------------------------------
def test_issue_unregistered_ineligible_returns_event_not_registered(api):
    """PRD §3.6: "Issuance enforces its preconditions in order: the request must
    already be `ID_VERIFIED` (an attempt while still `SUBMITTED` is rejected with
    `ERR_ID_NOT_VERIFIED`); the referenced record must be `REGISTERED` or
    `AMENDED` (else `ERR_EVENT_NOT_REGISTERED`); the eligibility rule below must
    resolve to a copy class; and finally `expected_vital_event_version` must match
    the record's current `version` (else `ERR_STALE_EVENT_VERSION`, HTTP 412)."

    Design: Difficulty/priority_pair_validation_conflict/issue_event_not_registered_outprioritizes_not_eligible
    """
    fac = create_facility(jurisdiction_code="CTY-13")
    ev = create_vital_event(fac["id"], event_type="BIRTH", jurisdiction_code="CTY-13")
    # file but do NOT register
    from test_helpers import file_event
    file_event(ev["id"], fac["id"])
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="OTHER", id_document_type="PASSPORT",
        copy_count=1,
    )
    resp = _issue(api, copy["id"], ev["id"])
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_REGISTERED)


def test_issue_registered_ineligible_surfaces_not_eligible(api):
    """PRD §3.6: "a `requester_relationship` of `OTHER` or `GENEALOGIST` against a
    confidential record is rejected with `ERR_NOT_ELIGIBLE` (HTTP 403)."
    PRD §3.6: "the referenced record must be `REGISTERED` or `AMENDED` (else
    `ERR_EVENT_NOT_REGISTERED`); the eligibility rule below must resolve to a copy
    class".

    Design: Difficulty/priority_pair_validation_conflict/issue_event_not_registered_outprioritizes_not_eligible
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-13",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="OTHER", id_document_type="PASSPORT",
        copy_count=1,
    )
    resp = _issue(api, copy["id"], ev["id"])
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant / void_conserves_event_fee_ledger
# ---------------------------------------------------------------------------
def test_issue_raises_event_fee_ledger(api):
    """PRD §2.5: "A `VitalEvent` tracks `fees_collected_cents`, the sum of
    `fee_total_cents` across its issued copies. It increases by the copy's fee
    when a copy is issued and decreases by that same fee when an issued copy is
    reversed on void."

    Design: Difficulty/compensating_invariant/void_conserves_event_fee_ledger
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-22",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="STANDARD",
        id_document_type="DRIVERS_LICENSE", copy_count=1,
    )
    validate_success(_issue(api, copy["id"], ev["id"]))
    ev_after = validate_success(api.get_vital_event(ev["id"], REGISTRAR))
    assert ev_after["fees_collected_cents"] == 1500
    assert ev_after["copies_issued_count"] == 1


def test_void_reverses_event_fee_ledger(api):
    """PRD §3.1: "for every certified-copy request of the record whose `status` is
    `ISSUED`, reverses that copy by decrementing the event's
    `copies_issued_count` by one and decrementing `fees_collected_cents` by that
    copy's `fee_total_cents`."

    Design: Difficulty/compensating_invariant/void_conserves_event_fee_ledger
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-22",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="STANDARD",
        id_document_type="DRIVERS_LICENSE", copy_count=1,
    )
    validate_success(_issue(api, copy["id"], ev["id"]))
    validate_success(api.void_vital_event(ev["id"], REGISTRAR))
    ev_after = validate_success(api.get_vital_event(ev["id"], REGISTRAR))
    assert ev_after["fees_collected_cents"] == 0
    assert ev_after["copies_issued_count"] == 0


# ---------------------------------------------------------------------------
# Corner: entities / copy_request_missing_relationship_returns_invalid_request
# ---------------------------------------------------------------------------
def test_copy_request_missing_relationship_returns_invalid_request(api):
    """PRD §2.9: "Request shape — all required fields are present with valid types
    and enum values, else `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/copy_request_missing_relationship_returns_invalid_request
    """
    fac = create_facility(jurisdiction_code="CTY-31")
    ev = create_vital_event(fac["id"], jurisdiction_code="CTY-31")
    resp = api.create_copy_request(
        {"vital_event_id": ev["id"], "requester_name": "No Rel",
         "id_document_type": "STATE_ID", "copy_count": 1},
        APPLICANT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


# ---------------------------------------------------------------------------
# Corner: state_machines / copy_issue_before_verify_returns_id_not_verified
# ---------------------------------------------------------------------------
def test_copy_issue_before_verify_returns_id_not_verified(api):
    """PRD §3.6: "the request must already be `ID_VERIFIED` (an attempt while
    still `SUBMITTED` is rejected with `ERR_ID_NOT_VERIFIED`)".

    Design: Corner/state_machines/copy_issue_before_verify_returns_id_not_verified
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-37",
                                           event_date="2026-02-25T00:00:00Z")
    copy = create_copy_request(
        ev["id"], requester_relationship="SELF", id_document_type="STATE_ID",
        copy_count=1,
    )  # left SUBMITTED, not verified
    resp = _issue(api, copy["id"], ev["id"])
    validate_error(resp, ApiErrorId.ERR_ID_NOT_VERIFIED)


# ---------------------------------------------------------------------------
# Corner: calculations / copy_fee_veteran_waived_to_zero
# ---------------------------------------------------------------------------
def test_copy_fee_veteran_waived_to_zero(api):
    """PRD §3.6: "The category then adjusts the gross: a `VETERAN` requester pays
    0, an `INDIGENT` requester pays the gross halved and rounded half up to a
    whole cent, and a `STANDARD` requester pays the full gross."

    Design: Corner/calculations/copy_fee_veteran_waived_to_zero
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-41",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="VETERAN",
        id_document_type="MILITARY_ID", copy_count=2,
    )
    issued = validate_success(_issue(api, copy["id"], ev["id"]))
    assert issued["copy_class"] == "CERTIFIED"
    assert issued["fee_total_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: calculations / copy_eligibility_public_at_seventy_five_years_boundary
# ---------------------------------------------------------------------------
def test_copy_eligibility_public_at_seventy_five_year_boundary(api):
    """PRD §3.6: "Each `event_type` has a public-record threshold: 75 years for
    `BIRTH`, 25 years for `DEATH`, and 25 years for `FETAL_DEATH`. When the age is
    at least the threshold the record is public: `copy_class` is `INFORMATIONAL`
    and any requester qualifies regardless of relationship."
    PRD §3.6: "For an `INFORMATIONAL` copy class, the fee is a flat 1000 cents per
    copy — 1000 cents times `copy_count` — plus the 1900-cent expedite surcharge
    when `expedite` is true".

    Design: Corner/calculations/copy_eligibility_public_at_seventy_five_years_boundary
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-42",
                                           event_date="2026-02-20T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="SELF", requester_category="STANDARD",
        id_document_type="PASSPORT", copy_count=2, expedite=True,
    )
    set_clock("2101-02-02T00:00:00Z")  # exactly 75 years old
    issued = validate_success(_issue(api, copy["id"], ev["id"]))
    assert issued["copy_class"] == "INFORMATIONAL"
    assert issued["fee_total_cents"] == 3900


# ---------------------------------------------------------------------------
# Corner: validations / issue_confidential_ineligible_returns_not_eligible
# ---------------------------------------------------------------------------
def test_issue_confidential_ineligible_returns_not_eligible(api):
    """PRD §3.6: "a `requester_relationship` of `OTHER` or `GENEALOGIST` against a
    confidential record is rejected with `ERR_NOT_ELIGIBLE` (HTTP 403)."

    Design: Corner/validations/issue_confidential_ineligible_returns_not_eligible
    """
    fac, ev = setup_registered_birth_event(jurisdiction_code="CTY-50",
                                           event_date="2026-02-25T00:00:00Z")
    copy = setup_id_verified_copy(
        ev["id"], requester_relationship="OTHER", id_document_type="PASSPORT",
        copy_count=1,
    )
    resp = _issue(api, copy["id"], ev["id"])
    validate_error(resp, ApiErrorId.ERR_NOT_ELIGIBLE)
