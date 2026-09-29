"""Pair rules at receipt, the two relabelling guards and the certificate window at claim time."""
from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_case_label, assert_certification, assert_supplier_lot
from test_helpers.factories import case_label_payload
from test_helpers.test_users import (
    OFFICER_CLAIM_USER_ID,
    make_compliance_officer_headers,
    make_seafood_manager_headers,
)


def _mismatched_cod_lot_observed_as_pacific_cod(api) -> dict:
    """A cod lot whose laboratory result named Pacific Cod, so its label dimension is MISMATCHED."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    pacific = fixtures.register_species(api, factories.pacific_cod_payload())
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    fixtures.publish_case_label(api, counter_id, lot["id"])
    fixtures.sample_with_result(api, lot["id"], pacific["id"], lab_reference="LAB-2026-0801-1")
    env.update({"pacific": pacific, "lot": lot})
    return env


def _active_certificate_whose_window_has_just_lapsed(api) -> dict:
    """An ACTIVE certificate approved inside its window, read again after the window closed."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, supplier_id, env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    certification = fixtures.file_certification(
        api,
        counter_id,
        supplier_id,
        env["cod"]["id"],
        valid_until="2026-08-02T00:00:00Z",
    )
    approved = fixtures.review_certification(
        api,
        certification["id"],
        "APPROVE",
        "certificate verified against the program registry",
        officer_id=OFFICER_CLAIM_USER_ID,
    )
    assert approved["status"] == "ACTIVE"
    fixtures.set_clock(api, "2026-08-02T09:00:00Z")
    env.update({"lot": lot, "certification": certification})
    return env


def _two_pending_certificates_on_an_ineligible_species(api) -> dict:
    """Two filed certificates for a species that is not enrolled in any claim program."""
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter = fixtures.register_counter(api)
    supplier = fixtures.register_supplier(api)
    tilapia = fixtures.register_species(
        api,
        factories.species_payload(
            market_name="Farmed Tilapia",
            scientific_name="Oreochromis niloticus",
            acceptable_market_names=["Tilapia", "Farmed Tilapia"],
            simp_covered=False,
            high_risk_substitution=True,
            sustainability_program_eligible=False,
        ),
    )
    first = fixtures.file_certification(
        api,
        counter["id"],
        supplier["id"],
        tilapia["id"],
        program_name="Pond Stewardship Alliance",
        certificate_number="PSA-3301",
        claim_text="Responsibly farmed tilapia",
    )
    second = fixtures.file_certification(
        api,
        counter["id"],
        supplier["id"],
        tilapia["id"],
        program_name="Pond Stewardship Alliance",
        certificate_number="PSA-3302",
        claim_text="Responsibly farmed tilapia",
    )
    return {
        "counter": counter,
        "supplier": supplier,
        "tilapia": tilapia,
        "first": first,
        "second": second,
    }


def test_01_previously_frozen_is_legal_alone_and_illegal_beside_a_fresh_claim(api):
    """PRD §3.1: "Two booleans capture the freezing history: `previously_frozen` states that the
    lot was frozen and thawed before display, and `fresh_claim` states that the counter intends
    to advertise the lot as never-frozen fresh. Submitting both as true is a contradiction in
    terms and is rejected with `ERR_FROZEN_DISCLOSURE_CONFLICT`."

    Design: Corner/validations/lot_receipt_rejects_conflicting_frozen_and_fresh_claims
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)
    payload = factories.lot_payload(
        counter_id,
        env["supplier"]["id"],
        env["cod"]["id"],
        lot_code="COD-0801-F",
        previously_frozen=True,
        fresh_claim=True,
        received_weight_kg=10.000,
    )

    validate_error(
        api.create_lot(payload, manager),
        ApiErrorId.ERR_FROZEN_DISCLOSURE_CONFLICT.value,
        expected_status=422,
    )
    _, meta = validate_paginated(api.list_lots(manager, params={"counter_id": counter_id}))
    assert meta["total_count"] == 0, "the refused receipt must not have written a lot row"

    payload["fresh_claim"] = False
    accepted = validate_success(api.create_lot(payload, manager), expected_status=201)

    assert_supplier_lot(accepted)
    assert accepted["previously_frozen"] is True
    assert accepted["fresh_claim"] is False
    assert accepted["intake_status"] == "RECEIVED"


def test_02_naming_the_original_species_on_a_relabel_is_refused(api):
    """PRD §3.8: "The `corrected_species_id` must equal the `observed_species_id` of the most
    recent `VerificationSample` for that lot whose `status` is `MISMATCH`, where recency is
    decided by `result_recorded_at` descending with `created_at` descending as the tie-break; a
    different species is rejected with `ERR_RELABEL_SPECIES_MISMATCH`."

    Design: Corner/validations/relabel_guards_species_then_market_name_then_accepts
    """
    env = _mismatched_cod_lot_observed_as_pacific_cod(api)
    counter_id = env["counter"]["id"]

    response = api.relabel_lot(
        env["lot"]["id"],
        {"corrected_species_id": env["cod"]["id"], "corrected_market_name": "Atlantic Cod"},
        make_seafood_manager_headers(counter_id),
    )
    validate_error(response, ApiErrorId.ERR_RELABEL_SPECIES_MISMATCH.value, expected_status=422)

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert lot["label_status"] == "MISMATCHED"
    assert lot["species_id"] == env["cod"]["id"]


def test_03_the_corrected_market_name_must_belong_to_the_corrected_species(api):
    """PRD §3.8: "The `corrected_market_name` must be a member of the `acceptable_market_names`
    array of the species named by `corrected_species_id`, failing which the rejection is
    `ERR_MARKET_NAME_NOT_ACCEPTABLE`."

    Design: Corner/validations/relabel_guards_species_then_market_name_then_accepts
    """
    env = _mismatched_cod_lot_observed_as_pacific_cod(api)
    counter_id = env["counter"]["id"]
    manager = make_seafood_manager_headers(counter_id)

    borrowed_name = api.relabel_lot(
        env["lot"]["id"],
        {"corrected_species_id": env["pacific"]["id"], "corrected_market_name": "Cod"},
        manager,
    )
    validate_error(
        borrowed_name, ApiErrorId.ERR_MARKET_NAME_NOT_ACCEPTABLE.value, expected_status=422
    )
    assert (
        fixtures.read_lot(api, counter_id, env["lot"]["id"])["label_status"] == "MISMATCHED"
    )

    response = api.relabel_lot(
        env["lot"]["id"],
        {"corrected_species_id": env["pacific"]["id"], "corrected_market_name": "True Cod"},
        manager,
    )
    relabelled = validate_success(response, expected_status=200)

    assert relabelled["label_status"] == "RELABELED"
    assert relabelled["species_id"] == env["pacific"]["id"]
    assert relabelled["intake_status"] == "CASED"
    assert relabelled["case_slot"] == 1


def test_04_a_lapsed_window_refuses_the_claim_while_the_certificate_is_still_active(api):
    """PRD §3.4: "Separately, the logical clock must fall at or after the certificate's
    `valid_from` and strictly before its `valid_until`, failing which the rejection is
    `ERR_CERTIFICATION_EXPIRED`."

    Design: Corner/validations/certification_claim_refused_once_the_window_has_lapsed
    """
    env = _active_certificate_whose_window_has_just_lapsed(api)
    counter_id = env["counter"]["id"]

    payload = case_label_payload(
        env["lot"]["id"], fixtures.lot_version(api, counter_id, env["lot"]["id"])
    )
    payload["certification_id"] = env["certification"]["id"]
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))

    validate_error(response, ApiErrorId.ERR_CERTIFICATION_EXPIRED.value, expected_status=422)

    stored = fixtures.read_certification(
        api, env["supplier"]["id"], env["certification"]["id"]
    )
    assert_certification(stored)
    assert stored["status"] == "ACTIVE", "nothing sweeps a certificate when the clock moves"
    assert fixtures.list_case_labels(api, counter_id, {"lot_id": env["lot"]["id"]}) == []


def test_05_the_explicit_sweep_expires_it_and_a_plain_label_then_publishes(api):
    """PRD §3.5: "A `decision` of `SWEEP` represents the expiry sweep and moves it from `ACTIVE`
    to `EXPIRED`, but only when the logical clock has reached or passed the certificate's
    `valid_until`."

    Design: Corner/validations/certification_claim_refused_once_the_window_has_lapsed
    """
    env = _active_certificate_whose_window_has_just_lapsed(api)
    counter_id = env["counter"]["id"]

    swept = fixtures.enforce_certification(
        api,
        env["certification"]["id"],
        "SWEEP",
        "window lapsed at 2026-08-02T00:00:00Z",
        officer_id=OFFICER_CLAIM_USER_ID,
    )
    assert swept["status"] == "EXPIRED"

    label = fixtures.publish_case_label(api, counter_id, env["lot"]["id"])

    assert_case_label(label)
    assert label["status"] == "PUBLISHED"
    assert label["certification_id"] is None
    assert label["sustainability_claim_text"] is None


def test_06_approval_needs_an_eligible_species_while_rejection_stays_available(api):
    """PRD §3.5: "Approval requires two things beyond the state check: the certified species
    must have `sustainability_program_eligible` true, failing which the decision is rejected
    with `ERR_SPECIES_NOT_CLAIM_ELIGIBLE`, and the logical clock must fall at or after
    `valid_from` and strictly before `valid_until`."

    Design: Corner/validations/certification_approval_requires_a_claim_eligible_species
    """
    env = _two_pending_certificates_on_an_ineligible_species(api)
    officer = make_compliance_officer_headers(OFFICER_CLAIM_USER_ID)

    response = api.review_certification(
        env["first"]["id"], {"decision": "APPROVE", "review_note": "certificate is genuine"}, officer
    )
    validate_error(
        response, ApiErrorId.ERR_SPECIES_NOT_CLAIM_ELIGIBLE.value, expected_status=422
    )

    unchanged = fixtures.read_certification(api, env["supplier"]["id"], env["first"]["id"])
    assert unchanged["status"] == "PENDING_REVIEW"
    assert unchanged["review_note"] is None

    rejected = fixtures.review_certification(
        api,
        env["second"]["id"],
        "REJECT",
        "species is not enrolled in a counter claim program",
        officer_id=OFFICER_CLAIM_USER_ID,
    )
    assert rejected["status"] == "REVOKED"
    assert rejected["review_note"] == "species is not enrolled in a counter claim program"
