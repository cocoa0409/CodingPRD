"""Title commitments, junior liens, lien releases, and the case gates that depend
on title state (PRD §2.7, §2.9, §3.4, §3.5)."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_junior_lien,
    assert_settlement_agreement,
    assert_title_commitment,
    create_lien_payload,
    create_lien_release_payload,
    get_case,
    get_title_commitment,
    make_borrower_headers,
    setup_case_at_terms_negotiation,
    setup_case_at_title_review,
    create_draft_agreement,
    validate_error,
    validate_success,
)


def _add_lien(api, commitment_id, title_officer_headers, **overrides):
    return validate_success(
        api.add_lien(commitment_id, create_lien_payload(**overrides), title_officer_headers), 201
    )


def test_zero_lien_commitment_auto_clears(api, title_officer_headers):
    """Receiving a commitment with zero unreleased liens bubbles up to CLEARED in
    the same operation.

    PRD §3.4: "Recording receipt of the commitment — with the `vested_owner_name` as it appears on title — moves it from `ORDERED` to `RECEIVED` (any other source state draws `ERR_TITLE_INVALID_STATE`) and increments its `version`; when the commitment shows no unreleased liens at that moment, it immediately bubbles up from `RECEIVED` to `CLEARED` in the same operation."

    Design: Corner/state_machines/zero_lien_commitment_auto_clears_on_receive
    """
    bundle = setup_case_at_title_review(loan_number="LN-S5")
    commitment = validate_success(
        api.create_title_commitment({"case_id": bundle["case"]["id"]}, title_officer_headers), 201
    )
    assert_title_commitment(commitment)
    assert commitment["status"] == "ORDERED"

    received = validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "S. Five"}, title_officer_headers)
    )
    assert received["status"] == "CLEARED", (
        f"zero-lien receive must bubble up to CLEARED in the same operation, got {received['status']}"
    )
    assert received["unreleased_lien_count"] == 0
    assert received["vested_owner_name"] == "S. Five"


def test_unreleased_lien_count_reconciles(api, title_officer_headers):
    """The derived unreleased_lien_count reconciles at every mutation and drives
    the CLEARED/RECEIVED bubble-up both ways.

    PRD §3.4: "A commitment's `unreleased_lien_count` is the count of its junior liens still in `UNRELEASED` status."
    PRD §3.4: "adding a lien to a `CLEARED` commitment — supplemental title work turning up a newly discovered lien — reopens it, reverting it from `CLEARED` to `RECEIVED`."
    PRD §3.4: "A successful release stamps the lien's `settlement_amount_cents` and `released_at`, moves it to its terminal `RELEASED` state, decrements the commitment's `unreleased_lien_count` by one, and increments the commitment's `version`; when that count reaches zero, the commitment bubbles up from `RECEIVED` to `CLEARED` with another version increment."

    Design: Corner/cross_cutting_layers/derived_field_unreleased_lien_count
    """
    bundle = setup_case_at_title_review(loan_number="LN-L3")
    commitment = validate_success(
        api.create_title_commitment({"case_id": bundle["case"]["id"]}, title_officer_headers), 201
    )
    received = validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "L. Three"}, title_officer_headers)
    )
    assert received["unreleased_lien_count"] == 0 and received["status"] == "CLEARED"

    lien1 = _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HOA Corp",
                      amount_cents=50000, position=2)
    mid = get_title_commitment(commitment["id"])
    assert mid["unreleased_lien_count"] == 1 and mid["status"] == "RECEIVED", "first lien reopens CLEARED -> RECEIVED"

    _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HELOC Bank",
              amount_cents=80000, position=3)
    two = get_title_commitment(commitment["id"])
    assert two["unreleased_lien_count"] == 2 and two["status"] == "RECEIVED"

    released = validate_success(
        api.release_lien(
            commitment["id"],
            create_lien_release_payload(lien1["id"], 50000, two["version"]),
            title_officer_headers,
        )
    )
    assert_junior_lien(released)
    assert released["status"] == "RELEASED" and released["settlement_amount_cents"] == 50000
    one = get_title_commitment(commitment["id"])
    assert one["unreleased_lien_count"] == 1 and one["status"] == "RECEIVED"


def test_duplicate_lien_position_rejected(api, title_officer_headers):
    """Positions are unique within a commitment; the duplicate add is refused.

    PRD §3.4: "Each lien carries a `title_commitment_id` tying it back to the commitment on which it appears, and each takes a `lienholder_name`, an `amount_cents` strictly greater than zero, and a `position` that must be at least 2 (position 1 belongs to the senior lien) and unique within the commitment — a duplicate position is refused with `ERR_LIEN_POSITION_DUPLICATE`."

    Design: Corner/validations/duplicate_lien_position_rejected
    """
    bundle = setup_case_at_title_review(loan_number="LN-V8")
    commitment = validate_success(
        api.create_title_commitment({"case_id": bundle["case"]["id"]}, title_officer_headers), 201
    )
    validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "V. Eight"}, title_officer_headers)
    )
    _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HOA Corp",
              amount_cents=50000, position=2)

    resp = api.add_lien(
        commitment["id"],
        create_lien_payload(lienholder_name="HELOC Bank", amount_cents=80000, position=2),
        title_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LIEN_POSITION_DUPLICATE.value)
    assert get_title_commitment(commitment["id"])["unreleased_lien_count"] == 1


def test_settlement_exceeds_lien_rejected(api, title_officer_headers):
    """A settlement above the lien's own amount is refused and nothing mutates.

    PRD §3.4: "The lien must be `UNRELEASED` (`ERR_LIEN_INVALID_STATE` otherwise), and the settlement must not exceed the lien's own `amount_cents` — a settlement that does is rejected with `ERR_SETTLEMENT_EXCEEDS_LIEN`."

    Design: Corner/validations/settlement_exceeds_lien_rejected
    """
    bundle = setup_case_at_title_review(loan_number="LN-V7")
    commitment = validate_success(
        api.create_title_commitment({"case_id": bundle["case"]["id"]}, title_officer_headers), 201
    )
    validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "V. Seven"}, title_officer_headers)
    )
    lien = _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HOA Corp",
                     amount_cents=50000, position=2)
    version = get_title_commitment(commitment["id"])["version"]

    resp = api.release_lien(
        commitment["id"], create_lien_release_payload(lien["id"], 50001, version), title_officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXCEEDS_LIEN.value)

    liens = validate_success(api.list_liens(commitment["id"], title_officer_headers))
    assert liens[0]["status"] == "UNRELEASED"
    assert get_title_commitment(commitment["id"])["version"] == version, "rejected release must not advance the version"


def test_occ_stale_title_version_on_lien_release(api, title_officer_headers):
    """A lien release carrying a pre-release commitment version is a stale write;
    the refetched version succeeds.

    PRD §2.7: "Releasing a junior lien through `POST /property-solutions/title-commitments/{id}/lien-releases` likewise requires a non-optional `expected_title_commitment_version` matching the title commitment's current `version`; a mismatch is rejected with `ERR_STALE_TITLE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/occ_stale_title_version_on_lien_release
    """
    bundle = setup_case_at_title_review(loan_number="LN-L2")
    commitment = validate_success(
        api.create_title_commitment({"case_id": bundle["case"]["id"]}, title_officer_headers), 201
    )
    validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "L. Two"}, title_officer_headers)
    )
    lien1 = _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HOA Corp",
                      amount_cents=50000, position=2)
    lien2 = _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HELOC Bank",
                      amount_cents=80000, position=3)
    stale_version = get_title_commitment(commitment["id"])["version"]

    first = validate_success(
        api.release_lien(commitment["id"], create_lien_release_payload(lien1["id"], 50000, stale_version),
                         title_officer_headers)
    )
    assert first["status"] == "RELEASED"

    resp = api.release_lien(
        commitment["id"], create_lien_release_payload(lien2["id"], 80000, stale_version), title_officer_headers
    )
    validate_error(resp, ApiErrorId.ERR_STALE_TITLE_VERSION.value)

    fresh_version = get_title_commitment(commitment["id"])["version"]
    second = validate_success(
        api.release_lien(commitment["id"], create_lien_release_payload(lien2["id"], 80000, fresh_version),
                         title_officer_headers)
    )
    assert second["status"] == "RELEASED"
    cleared = get_title_commitment(commitment["id"])
    assert cleared["unreleased_lien_count"] == 0 and cleared["status"] == "CLEARED"


def test_release_unknown_lien_not_found(api, title_officer_headers):
    """A lien-release body naming a lien that does not resolve on the addressed
    commitment fails FK resolution with the lien 404.

    PRD §2.9: "The same resolution duty applies to foreign-key references inside request payloads — `loan_id`, `borrower_id`, `case_id`, `agreement_id`, and `lien_id` must each resolve, and a `lien_id` in a lien-release payload must resolve on the addressed title commitment."

    Design: Corner/errors_not_found_sweep/release_unknown_lien_returns_not_found
    """
    bundle = setup_case_at_title_review(loan_number="LN-NF")
    commitment = validate_success(
        api.create_title_commitment({"case_id": bundle["case"]["id"]}, title_officer_headers), 201
    )
    validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "N. Eff"}, title_officer_headers)
    )
    version = get_title_commitment(commitment["id"])["version"]

    resp = api.release_lien(
        commitment["id"],
        create_lien_release_payload(NON_EXISTENT_UUID, 10000, version),
        title_officer_headers,
    )
    validate_error(resp, ApiErrorId.ERR_LIEN_NOT_FOUND.value)


def test_certify_title_missing_then_ordered_commitment(api, specialist_headers, title_officer_headers):
    """certify-title fails with no commitment at all (missing) and with an ORDERED
    zero-lien commitment (invalid state).

    PRD §3.4: "A title commitment must exist for the case (`ERR_TITLE_COMMITMENT_MISSING` otherwise), and it must be `CLEARED`: a commitment still `ORDERED` — not yet received, with zero liens recorded — is rejected with `ERR_TITLE_INVALID_STATE`, while one still carrying an `UNRELEASED` junior lien is rejected with `ERR_JUNIOR_LIENS_OUTSTANDING`."

    Design: Difficulty/cross_entity_state_dependency/certify_title_requires_commitment_cleared
    """
    bundle = setup_case_at_title_review(loan_number="LN-CS1")
    case_id = bundle["case"]["id"]

    resp1 = api.certify_title(case_id, specialist_headers)
    validate_error(resp1, ApiErrorId.ERR_TITLE_COMMITMENT_MISSING.value)

    commitment = validate_success(
        api.create_title_commitment({"case_id": case_id}, title_officer_headers), 201
    )
    assert commitment["status"] == "ORDERED"

    resp2 = api.certify_title(case_id, specialist_headers)
    validate_error(resp2, ApiErrorId.ERR_TITLE_INVALID_STATE.value)
    assert get_case(case_id)["status"] == "TITLE_REVIEW"


def test_certify_title_succeeds_once_cleared(api, specialist_headers, title_officer_headers):
    """After a zero-lien receive auto-CLEARS the commitment, certify-title passes.

    PRD §3.4: "A title commitment must exist for the case (`ERR_TITLE_COMMITMENT_MISSING` otherwise), and it must be `CLEARED`: a commitment still `ORDERED` — not yet received, with zero liens recorded — is rejected with `ERR_TITLE_INVALID_STATE`, while one still carrying an `UNRELEASED` junior lien is rejected with `ERR_JUNIOR_LIENS_OUTSTANDING`."
    PRD §3.4: "Certifying title moves the case from `TITLE_REVIEW` to `TERMS_NEGOTIATION` and increments the case's `version`."

    Design: Difficulty/cross_entity_state_dependency/certify_title_requires_commitment_cleared
    """
    bundle = setup_case_at_title_review(loan_number="LN-CS1")
    case_id = bundle["case"]["id"]
    commitment = validate_success(
        api.create_title_commitment({"case_id": case_id}, title_officer_headers), 201
    )
    received = validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "A. Borrower"}, title_officer_headers)
    )
    assert received["status"] == "CLEARED", "zero-lien receive must auto-CLEAR"

    certified = validate_success(api.certify_title(case_id, specialist_headers))
    assert certified["status"] == "TERMS_NEGOTIATION"


def test_unreleased_lien_blocks_certify_title(api, specialist_headers, title_officer_headers):
    """Exactly one outstanding lien blocks title certification (count gate at 1).

    PRD §3.4: "A title commitment must exist for the case (`ERR_TITLE_COMMITMENT_MISSING` otherwise), and it must be `CLEARED`: a commitment still `ORDERED` — not yet received, with zero liens recorded — is rejected with `ERR_TITLE_INVALID_STATE`, while one still carrying an `UNRELEASED` junior lien is rejected with `ERR_JUNIOR_LIENS_OUTSTANDING`."

    Design: Difficulty/boundary_precision_check/unreleased_lien_count_zero_gate
    """
    bundle = setup_case_at_title_review(loan_number="LN-BP2")
    case_id = bundle["case"]["id"]
    commitment = validate_success(
        api.create_title_commitment({"case_id": case_id}, title_officer_headers), 201
    )
    validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "A. Borrower"}, title_officer_headers)
    )
    _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HOA Corp",
              amount_cents=50000, position=2)
    assert get_title_commitment(commitment["id"])["unreleased_lien_count"] == 1

    resp = api.certify_title(case_id, specialist_headers)
    validate_error(resp, ApiErrorId.ERR_JUNIOR_LIENS_OUTSTANDING.value)
    assert get_case(case_id)["status"] == "TITLE_REVIEW"


def test_lien_release_unblocks_certify_title(api, specialist_headers, title_officer_headers):
    """Releasing the last lien bubbles the commitment to CLEARED (count 0) and
    the gate opens.

    PRD §3.4: "A successful release stamps the lien's `settlement_amount_cents` and `released_at`, moves it to its terminal `RELEASED` state, decrements the commitment's `unreleased_lien_count` by one, and increments the commitment's `version`; when that count reaches zero, the commitment bubbles up from `RECEIVED` to `CLEARED` with another version increment."
    PRD §3.4: "Certifying title moves the case from `TITLE_REVIEW` to `TERMS_NEGOTIATION` and increments the case's `version`."

    Design: Difficulty/boundary_precision_check/unreleased_lien_count_zero_gate
    """
    bundle = setup_case_at_title_review(loan_number="LN-BP2")
    case_id = bundle["case"]["id"]
    commitment = validate_success(
        api.create_title_commitment({"case_id": case_id}, title_officer_headers), 201
    )
    validate_success(
        api.receive_title_commitment(commitment["id"], {"vested_owner_name": "A. Borrower"}, title_officer_headers)
    )
    lien = _add_lien(api, commitment["id"], title_officer_headers, lienholder_name="HOA Corp",
                     amount_cents=50000, position=2)
    version = get_title_commitment(commitment["id"])["version"]

    released = validate_success(
        api.release_lien(commitment["id"], create_lien_release_payload(lien["id"], 40000, version),
                         title_officer_headers)
    )
    assert released["status"] == "RELEASED"
    assert released["settlement_amount_cents"] == 40000
    assert released["released_at"] is not None
    cleared = get_title_commitment(commitment["id"])
    assert cleared["unreleased_lien_count"] == 0 and cleared["status"] == "CLEARED"

    certified = validate_success(api.certify_title(case_id, specialist_headers))
    assert certified["status"] == "TERMS_NEGOTIATION"


def _offered_case_with_reopened_lien(api, loan_number, program_type, borrower_name, borrower_email,
                                     specialist_headers, title_officer_headers):
    """Drive a case to an OFFERED agreement, then reopen its commitment with a
    newly discovered junior lien (CLEARED -> RECEIVED)."""
    bundle = setup_case_at_terms_negotiation(
        loan_number=loan_number,
        program_type=program_type,
        borrower_overrides={"full_name": borrower_name, "email": borrower_email},
    )
    agreement = create_draft_agreement(bundle["case"]["id"])
    agreement = validate_success(
        api.offer_agreement(agreement["id"], {"offer_valid_days": 10}, specialist_headers)
    )
    assert agreement["status"] == "OFFERED"
    _add_lien(api, bundle["title_commitment"]["id"], title_officer_headers,
              lienholder_name="HOA Corp", amount_cents=50000, position=2)
    return bundle, agreement


def test_dil_accept_blocked_by_outstanding_lien(api, specialist_headers, title_officer_headers):
    """For DEED_IN_LIEU, accept is gated on junior-lien clearance.

    PRD §3.5: "Then, for `DEED_IN_LIEU` cases only, every junior lien on the case's title commitment must be out of `UNRELEASED`; an outstanding lien blocks acceptance with `ERR_JUNIOR_LIENS_OUTSTANDING`, a check skipped entirely for `CASH_FOR_KEYS`."
    PRD §3.4: "adding a lien to a `CLEARED` commitment — supplemental title work turning up a newly discovered lien — reopens it, reverting it from `CLEARED` to `RECEIVED`."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_lien_clearance_dil_only
    """
    bundle, agreement = _offered_case_with_reopened_lien(
        api, "LN-CS2", "DEED_IN_LIEU", "C. Dee", "cd@x.com", specialist_headers, title_officer_headers
    )
    assert get_title_commitment(bundle["title_commitment"]["id"])["status"] == "RECEIVED"

    resp = api.accept_agreement(agreement["id"], make_borrower_headers(bundle["borrower"]["id"]))
    validate_error(resp, ApiErrorId.ERR_JUNIOR_LIENS_OUTSTANDING.value)

    after = validate_success(api.get_agreement(agreement["id"], specialist_headers))
    assert_settlement_agreement(after)
    assert after["status"] == "OFFERED"
    assert get_case(bundle["case"]["id"])["status"] == "TERMS_NEGOTIATION"


def test_cfk_accept_skips_lien_clearance(api, specialist_headers, title_officer_headers):
    """The lien-clearance gate is skipped entirely for CASH_FOR_KEYS: the same
    outstanding lien does not block acceptance.

    PRD §3.5: "Then, for `DEED_IN_LIEU` cases only, every junior lien on the case's title commitment must be out of `UNRELEASED`; an outstanding lien blocks acceptance with `ERR_JUNIOR_LIENS_OUTSTANDING`, a check skipped entirely for `CASH_FOR_KEYS`."
    PRD §3.5: "Acceptance bubbles up: the case moves from `TERMS_NEGOTIATION` to `AGREEMENT_ACTIVE` with a version increment, and for deed-in-lieu cases the system creates a DeficiencyWaiver in `DRAFT` status — its `case_id` set from the case, its `loan_id` copied from the case, and its `projected_waiver_cents` computed per the projected variant described in §3.8."

    Design: Difficulty/cross_entity_state_dependency/accept_requires_lien_clearance_dil_only
    """
    bundle, agreement = _offered_case_with_reopened_lien(
        api, "LN-CS3", "CASH_FOR_KEYS", "C. Kay", "ck@x.com", specialist_headers, title_officer_headers
    )

    accepted = validate_success(
        api.accept_agreement(agreement["id"], make_borrower_headers(bundle["borrower"]["id"]))
    )
    assert accepted["status"] == "ACCEPTED"
    assert get_case(bundle["case"]["id"])["status"] == "AGREEMENT_ACTIVE"
