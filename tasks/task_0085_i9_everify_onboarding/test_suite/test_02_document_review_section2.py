"""Section 2 document review: supersession cascade, document validity, the
documentary-combination rule, receipt handling, and conservation invariants.

Covers difficulty rules transitive_cascade (section2 branch), boundary_precision_check,
compensating_invariant (document branch), and corner calculations/validations.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    create_onboarding, present_document, attest_section1, complete_section2,
    set_clock, get_backing_form, api_client,
)
from test_helpers import fixtures as fx

HR = TEST_USERS["hr_reviewer_headers"]
CO = TEST_USERS["compliance_officer_headers"]


# ===========================================================================
# Queue A — transitive_cascade (section2 supersession)
# ===========================================================================
def test_section2_accept_list_a_supersedes_other_presented_documents(api):
    """PRD §3.3: "On success, the system marks each chosen document `accepted_for_section2` true and moves it from `PRESENTED` to `ACCEPTED`, and every other still-`PRESENTED` document for this onboarding is set to `SUPERSEDED`."
    PRD §3.3: "the single List A document proves both identity and work authorization and the form's `chosen_document_path` is recorded as `LIST_A`"

    Design: Difficulty/transitive_cascade/section2_complete_cascade_document_supersession
    """
    ob = create_onboarding(employee_full_name="Ha Yo", employee_email="ha@x.com",
                           requires_everify=False)
    form = get_backing_form(ob["id"])
    keep = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                            document_number="PA", expiration_date="2030-01-01T00:00:00Z")
    drop = present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                            document_number="DL", expiration_date="2029-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    complete_section2(ob["id"], [keep["id"]], ob_v1["version"])

    kept = validate_success(api.get_identity_document(keep["id"], HR))
    dropped = validate_success(api.get_identity_document(drop["id"], HR))
    assert kept["status"] == "ACCEPTED"
    assert dropped["status"] == "SUPERSEDED"
    form_after = validate_success(api.get_i9_form(form["id"], HR))
    assert form_after["chosen_document_path"] == "LIST_A"


def test_section2_accepted_list_a_doc_marked_accepted_for_section2(api):
    """PRD §3.3: "On success, the system marks each chosen document `accepted_for_section2` true and moves it from `PRESENTED` to `ACCEPTED`"

    Design: Difficulty/transitive_cascade/section2_complete_cascade_document_supersession
    """
    ob = create_onboarding(employee_full_name="Ha Yo2", employee_email="ha2@x.com",
                           requires_everify=False)
    keep = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                            document_number="PA2", expiration_date="2030-01-01T00:00:00Z")
    present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                     document_number="DL2", expiration_date="2029-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    complete_section2(ob["id"], [keep["id"]], ob_v1["version"])
    kept = validate_success(api.get_identity_document(keep["id"], HR))
    assert kept["accepted_for_section2"] is True
    assert kept["status"] == "ACCEPTED"


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================
def test_document_expiring_exactly_at_clock_is_expired(api):
    """PRD §3.3: "a document with a non-null `expiration_date` is valid only when that expiration is strictly after the clock. A document expiring exactly at the clock value is treated as expired. A non-receipt chosen document that is expired by this rule is rejected with `ERR_DOCUMENT_EXPIRED`."

    Design: Difficulty/boundary_precision_check/document_expiry_strict_greater_than_boundary
    """
    ob = create_onboarding(employee_full_name="Lo Pe", employee_email="lo@x.com",
                           requires_everify=False)
    set_clock("2026-06-15T12:00:00Z")
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="PE", expiration_date="2026-06-15T12:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    resp = api.section2_complete(
        ob["id"], {"document_ids": [doc["id"]], "expected_onboarding_version": ob_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_EXPIRED.value, 422)


def test_document_expiring_just_after_clock_is_valid(api):
    """PRD §3.3: "a document with a non-null `expiration_date` is valid only when that expiration is strictly after the clock."

    Design: Difficulty/boundary_precision_check/document_expiry_strict_greater_than_boundary
    """
    ob = create_onboarding(employee_full_name="Lo Pe2", employee_email="lo2@x.com",
                           requires_everify=False)
    set_clock("2026-06-15T12:00:00Z")
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="PE2", expiration_date="2026-06-15T12:00:01Z")
    ob_v1 = attest_section1(ob["id"])
    data = complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    assert data["status"] == "SECTION2_COMPLETE", "doc expiring after clock must be accepted"


def test_section2_empty_document_set_rejected(api):
    """PRD §3.3: "Any other cardinality — zero documents, two List A documents, a lone List B, a List B with two List C documents, and so on — is rejected with `ERR_DOCUMENT_COMBINATION_INVALID`; there is no partial credit."

    Design: Difficulty/boundary_precision_check/section2_empty_document_set_rejected
    """
    ob = create_onboarding(employee_full_name="Mo Qi", employee_email="mo@x.com",
                           requires_everify=False)
    ob_v1 = attest_section1(ob["id"])
    resp = api.section2_complete(
        ob["id"], {"document_ids": [], "expected_onboarding_version": ob_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_COMBINATION_INVALID.value, 422)


def test_section2_lone_list_b_rejected(api):
    """PRD §3.3: "Any other cardinality — zero documents, two List A documents, a lone List B, a List B with two List C documents, and so on — is rejected with `ERR_DOCUMENT_COMBINATION_INVALID`; there is no partial credit."

    Design: Difficulty/boundary_precision_check/section2_empty_document_set_rejected
    """
    ob = create_onboarding(employee_full_name="Mo Qi2", employee_email="mo2@x.com",
                           requires_everify=False)
    b = present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                         document_number="LB", expiration_date="2030-01-01T00:00:00Z")
    ob_v1 = attest_section1(ob["id"])
    resp = api.section2_complete(
        ob["id"], {"document_ids": [b["id"]], "expected_onboarding_version": ob_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_COMBINATION_INVALID.value, 422)


# ===========================================================================
# Queue A — compensating_invariant (document population conservation)
# ===========================================================================
def test_document_population_conserved_across_section2(api):
    """PRD §3.3: "On success, the system marks each chosen document `accepted_for_section2` true and moves it from `PRESENTED` to `ACCEPTED`, and every other still-`PRESENTED` document for this onboarding is set to `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/document_acceptance_count_invariant
    """
    ob = create_onboarding(employee_full_name="Ra Si", employee_email="ra@x.com",
                           requires_everify=False)
    d_a = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="IA", expiration_date="2030-01-01T00:00:00Z")
    present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                     document_number="IB", expiration_date="2029-01-01T00:00:00Z")
    present_document(ob["id"], list_category="LIST_C", document_title="SS_CARD",
                     document_number="IC", expiration_date=None)
    ob_v1 = attest_section1(ob["id"])
    complete_section2(ob["id"], [d_a["id"]], ob_v1["version"])

    data, meta = validate_paginated(
        api.list_identity_documents(HR, params={"onboarding_id": ob["id"]}))
    assert meta["total_count"] == 3, "no documents created or destroyed by Section 2"
    accepted = [d for d in data if d["status"] == "ACCEPTED"]
    superseded = [d for d in data if d["status"] == "SUPERSEDED"]
    assert len(accepted) == 1, "exactly one chosen List A document accepted"
    assert len(superseded) == 2, "the two unchosen documents superseded"


def test_section2_only_chosen_document_marked_accepted_others_superseded(api):
    """PRD §3.3: "On success, the system marks each chosen document `accepted_for_section2` true and moves it from `PRESENTED` to `ACCEPTED`, and every other still-`PRESENTED` document for this onboarding is set to `SUPERSEDED`."

    Design: Difficulty/compensating_invariant/document_acceptance_count_invariant
    """
    ob = create_onboarding(employee_full_name="Ra Si2", employee_email="ra2@x.com",
                           requires_everify=False)
    d_a = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="JA", expiration_date="2030-01-01T00:00:00Z")
    d_b = present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                           document_number="JB", expiration_date="2029-01-01T00:00:00Z")
    d_c = present_document(ob["id"], list_category="LIST_C", document_title="SS_CARD",
                           document_number="JC", expiration_date=None)
    ob_v1 = attest_section1(ob["id"])
    complete_section2(ob["id"], [d_a["id"]], ob_v1["version"])

    chosen = validate_success(api.get_identity_document(d_a["id"], HR))
    assert chosen["accepted_for_section2"] is True and chosen["status"] == "ACCEPTED"
    for other_id in (d_b["id"], d_c["id"]):
        other = validate_success(api.get_identity_document(other_id, HR))
        assert other["accepted_for_section2"] is False
        assert other["status"] == "SUPERSEDED", "unchosen presented documents become SUPERSEDED"


# ===========================================================================
# Queue B — corner: calculations
# ===========================================================================
def test_list_b_and_c_path_accepted(api):
    """PRD §3.3: "or exactly one List B document and exactly one List C document are chosen and no List A document is chosen, in which case the List B document proves identity, the List C document proves work authorization, and `chosen_document_path` is recorded as `LIST_B_AND_C`."

    Design: Corner/calculations/list_b_and_c_path_accepted_correctly
    """
    ob = create_onboarding(employee_full_name="Bc Pa", employee_email="bc@x.com",
                           requires_everify=False)
    form = get_backing_form(ob["id"])
    db = present_document(ob["id"], list_category="LIST_B", document_title="DRIVERS_LICENSE",
                          document_number="BB", expiration_date="2029-01-01T00:00:00Z")
    dc = present_document(ob["id"], list_category="LIST_C", document_title="SS_CARD",
                          document_number="CC", expiration_date=None)
    ob_v1 = attest_section1(ob["id"])
    data = complete_section2(ob["id"], [db["id"], dc["id"]], ob_v1["version"])
    assert data["status"] == "SECTION2_COMPLETE"
    form_after = validate_success(api.get_i9_form(form["id"], HR))
    assert form_after["chosen_document_path"] == "LIST_B_AND_C"


def test_stem_cap_gap_clamped_to_180(api):
    """PRD §3.6: "`cap_gap_days` is the requested number of days but capped at a ceiling of 180, so a request of 180 or fewer days grants exactly that many while a request exceeding 180 clamps to 180."
    PRD §3.6: "The new record's `effective_valid_until` is its base `valid_until` plus `cap_gap_days` days"

    Design: Corner/calculations/stem_cap_gap_clamped_to_180
    """
    ob, base = fx.setup_stem_base(base_valid_until="2026-09-30T00:00:00Z",
                                  filing_clock="2026-09-01T09:00:00Z",
                                  employee_full_name="Cap Ex", employee_email="cap@x.com")
    resp = fx.file_stem_extension(ob["id"], base["id"],
                                  valid_from="2026-09-30T00:00:00Z",
                                  valid_until="2028-09-30T00:00:00Z", requested_gap_days=250)
    data = validate_success(resp, 201)
    assert data["cap_gap_days"] == 180
    assert data["effective_valid_until"] == "2027-03-29T00:00:00.000Z"


def test_receipt_document_skips_expiry_and_gets_90day_deadline(api):
    """PRD §3.3: "Receipts are exempt from the expiry check at acceptance because they stand in for an expired or lost document"
    PRD §3.3: "For any accepted document that is a receipt, the system computes `receipt_resolution_deadline` as `section2_completed_at` plus 90 calendar days — the date by which the actual document must replace the receipt."

    Design: Corner/calculations/receipt_document_skips_expiry_and_gets_90day_deadline
    """
    ob = create_onboarding(employee_full_name="Rc Pt", employee_email="rc@x.com",
                           requires_everify=False)
    set_clock("2026-06-02T00:00:00Z")
    doc = present_document(ob["id"], list_category="LIST_A", document_title="US_PASSPORT",
                           document_number="RC", expiration_date=None, is_receipt=True)
    ob_v1 = attest_section1(ob["id"])
    complete_section2(ob["id"], [doc["id"]], ob_v1["version"])
    after = validate_success(api.get_identity_document(doc["id"], HR))
    assert after["status"] == "ACCEPTED"
    assert after["receipt_resolution_deadline"] == "2026-08-31T00:00:00.000Z"


# ===========================================================================
# Queue B — corner: validations (Section 1 incompleteness, ownership)
# ===========================================================================
def test_alien_authorized_missing_expiration_returns_section1_incomplete(api):
    """PRD §3.1: "Before Section 1 may complete, the system enforces that an `ALIEN_AUTHORIZED` attestation carries a present, well-formed `work_auth_expiration`; if it is missing, the attestation is rejected with `ERR_SECTION1_INCOMPLETE`."

    Design: Corner/validations/section1_alien_authorized_missing_expiration_returns_section1_incomplete
    """
    ob = create_onboarding(employee_full_name="Al No", employee_email="aln@x.com",
                           citizenship_status="ALIEN_AUTHORIZED", requires_everify=False)
    resp = api.section1_attest(ob["id"], {}, HR)
    validate_error(resp, ApiErrorId.ERR_SECTION1_INCOMPLETE.value, 422)


def test_document_owned_by_other_onboarding_returns_not_owned(api):
    """PRD §3.3: "Every chosen document named in `document_ids` must belong to the onboarding in the path; a chosen document that points at a different `onboarding_id` is rejected with `ERR_DOCUMENT_NOT_OWNED`."

    Design: Corner/validations/document_not_owned_returns_referential_error
    """
    ob_a = create_onboarding(employee_full_name="Ow A", employee_email="owa@x.com",
                             requires_everify=False)
    ob_b = create_onboarding(employee_full_name="Ow B", employee_email="owb@x.com",
                             requires_everify=False)
    doc_b = present_document(ob_b["id"], list_category="LIST_A", document_title="US_PASSPORT",
                             document_number="OB", expiration_date="2030-01-01T00:00:00Z")
    ob_a_v1 = attest_section1(ob_a["id"])
    resp = api.section2_complete(
        ob_a["id"], {"document_ids": [doc_b["id"]],
                     "expected_onboarding_version": ob_a_v1["version"]}, HR)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_OWNED.value, 422)
