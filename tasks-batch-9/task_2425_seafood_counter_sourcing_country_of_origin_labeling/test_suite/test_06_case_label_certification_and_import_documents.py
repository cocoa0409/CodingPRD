"""Claim substantiation on a label and the import-monitoring gate in front of casing."""
from test_helpers import ApiErrorId, fixtures, validate_error, validate_success
from test_helpers.assertions import (
    assert_case_label,
    assert_instant,
    assert_simp_document,
    assert_supplier_lot,
)
from test_helpers.factories import case_label_payload
from test_helpers.test_users import (
    OFFICER_CLAIM_USER_ID,
    OFFICER_SIMP_USER_ID,
    make_seafood_manager_headers,
)


def _cod_lot_with_pending_certificate(api) -> dict:
    """A cased cod lot plus a certificate for it that has not yet been reviewed."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(api, counter_id, env["supplier"]["id"], env["cod"]["id"])
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    certification = fixtures.file_certification(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"]
    )
    env["lot"] = lot
    env["certification"] = certification
    return env


def _snapper_lot_with_submitted_document(api) -> dict:
    """A covered-species lot whose import-monitoring record is only `SUBMITTED`."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    supplier_id = env["supplier"]["id"]
    snapper = fixtures.register_red_snapper(api)
    lot = fixtures.receive_snapper_lot(api, counter_id, supplier_id, snapper["id"])
    document = fixtures.create_simp_document(api, supplier_id, lot["id"])
    fixtures.submit_simp_document(api, supplier_id, document["id"])
    env.update({"snapper": snapper, "lot": lot, "document": document})
    return env


def test_01_a_claim_backed_by_an_unreviewed_certificate_is_refused(api):
    """PRD §3.4: "Whenever a `certification_id` is supplied on a label, the claim must
    actually be substantiated. The certificate must have `status` `ACTIVE` and its
    `counter_id`, `supplier_id` and `species_id` must each match the lot's `counter_id`,
    `supplier_id` and `species_id`; a failure on any of those four points is
    `ERR_CLAIM_NOT_SUBSTANTIATED`."

    Design: Difficulty/cross_entity_state_dependency/case_label_claim_requires_active_certification
    """
    env = _cod_lot_with_pending_certificate(api)
    counter_id = env["counter"]["id"]
    assert env["certification"]["status"] == "PENDING_REVIEW"

    payload = case_label_payload(
        env["lot"]["id"], fixtures.lot_version(api, counter_id, env["lot"]["id"])
    )
    payload["certification_id"] = env["certification"]["id"]
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))

    validate_error(response, ApiErrorId.ERR_CLAIM_NOT_SUBSTANTIATED.value, expected_status=422)
    assert fixtures.list_case_labels(api, counter_id, {"lot_id": env["lot"]["id"]}) == []


def test_02_an_approved_certificate_puts_its_claim_text_on_the_composed_label(api):
    """PRD §3.4: "`sustainability_claim_text` is null when no `certification_id` was
    supplied, and otherwise is copied verbatim from the referenced certificate's
    `claim_text`."

    Design: Difficulty/cross_entity_state_dependency/case_label_claim_requires_active_certification
    """
    env = _cod_lot_with_pending_certificate(api)
    counter_id = env["counter"]["id"]
    approved = fixtures.review_certification(
        api, env["certification"]["id"], "APPROVE", officer_id=OFFICER_CLAIM_USER_ID
    )
    assert approved["status"] == "ACTIVE"

    payload = case_label_payload(
        env["lot"]["id"], fixtures.lot_version(api, counter_id, env["lot"]["id"])
    )
    payload["certification_id"] = env["certification"]["id"]
    response = api.create_case_label(payload, make_seafood_manager_headers(counter_id))
    label = validate_success(response, expected_status=201)

    assert_case_label(label)
    assert label["status"] == "PUBLISHED"
    assert label["sustainability_claim_text"] == "Certified sustainable wild-capture fishery"
    assert label["display_market_name"] == "Atlantic Cod"
    assert label["production_method_statement"] == "WILD CAUGHT"
    assert label["origin_statement"] == "Wild caught in US (WILD_LONGLINE)"
    assert label["frozen_disclosure_statement"] == "FRESH - NEVER FROZEN"


def test_03_casing_a_covered_species_lot_is_blocked_while_the_document_is_unreviewed(api):
    """PRD §3.3: "And when the lot's species has `simp_covered` true, an import-monitoring
    record for that lot must exist with `status` `ACCEPTED`; otherwise the request fails with
    `ERR_SIMP_DOCUMENT_MISSING`."

    Design: Difficulty/cross_entity_state_dependency/casing_covered_species_requires_accepted_import_document
    """
    env = _snapper_lot_with_submitted_document(api)
    counter_id = env["counter"]["id"]

    response = api.case_lot(
        env["lot"]["id"], {"case_slot": 1}, make_seafood_manager_headers(counter_id)
    )
    validate_error(response, ApiErrorId.ERR_SIMP_DOCUMENT_MISSING.value, expected_status=409)

    lot = fixtures.read_lot(api, counter_id, env["lot"]["id"])
    assert_supplier_lot(lot)
    assert lot["intake_status"] == "RECEIVED"
    assert lot["case_slot"] is None


def test_04_accepting_the_import_record_unblocks_casing_for_that_lot(api):
    """PRD §3.2: "A `decision` of `ACCEPT` moves the record from `SUBMITTED` to `ACCEPTED`,
    stamps `reviewed_at` from the logical clock, unblocks casing for the covered-species lot,
    and cures any `ComplianceViolation` for that lot whose `category` is `SIMP_DEFICIENT` and
    whose `status` is `OPEN` — those violations move to `CURED`, which in turn re-derives the
    counter's posture at the halved weight."

    Design: Difficulty/cross_entity_state_dependency/casing_covered_species_requires_accepted_import_document
    """
    env = _snapper_lot_with_submitted_document(api)

    accepted = fixtures.review_simp_document(
        api, env["document"]["id"], "ACCEPT", officer_id=OFFICER_SIMP_USER_ID
    )

    assert_simp_document(accepted)
    assert accepted["status"] == "ACCEPTED"
    assert_instant(accepted["reviewed_at"], "2026-08-01T08:00:00Z")


def test_05_casing_succeeds_once_the_import_record_is_accepted(api):
    """PRD §3.3: "The `SeafoodManager` names the target `case_slot` and the lot advances from
    `RECEIVED` to `CASED`, at which point the lot's `case_slot` is set to the requested slot
    and `cased_at` is stamped from the logical clock."

    Design: Difficulty/cross_entity_state_dependency/casing_covered_species_requires_accepted_import_document
    """
    env = _snapper_lot_with_submitted_document(api)
    counter_id = env["counter"]["id"]
    fixtures.review_simp_document(
        api, env["document"]["id"], "ACCEPT", officer_id=OFFICER_SIMP_USER_ID
    )

    response = api.case_lot(
        env["lot"]["id"], {"case_slot": 1}, make_seafood_manager_headers(counter_id)
    )
    lot = validate_success(response, expected_status=200)

    assert lot["intake_status"] == "CASED"
    assert lot["case_slot"] == 1
    assert_instant(lot["cased_at"], "2026-08-01T08:00:00Z")
