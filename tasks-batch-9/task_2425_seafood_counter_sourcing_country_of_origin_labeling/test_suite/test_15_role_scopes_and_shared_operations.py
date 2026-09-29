"""Authentication before authorization, horizontally partitioned scopes, and who shares what."""
from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_case_label, assert_simp_document
from test_helpers.factories import case_label_payload, simp_document_payload
from test_helpers.test_users import (
    OFFICER_CLAIM_USER_ID,
    OFFICER_COOL_USER_ID,
    headers_without_user_id,
    make_compliance_officer_headers,
    make_merchandising_lead_headers,
    make_seafood_manager_headers,
    make_supplier_rep_headers,
)


def _two_counters_two_dealers_and_a_snapper_lot(api) -> dict:
    """A snapper lot received at Counter A from Supplier 1, with peers standing by."""
    fixtures.set_clock(api, "2026-08-01T08:00:00Z")
    counter_a = fixtures.register_counter(api)
    counter_b = fixtures.register_counter(api, store_number="4130", case_slot_count=4)
    supplier_one = fixtures.register_supplier(api)
    supplier_two = fixtures.register_supplier(
        api, name="Coastline Wholesale", permit_number="PERMIT-8802"
    )
    snapper = fixtures.register_red_snapper(api)
    lot = fixtures.receive_snapper_lot(api, counter_a["id"], supplier_one["id"], snapper["id"])
    return {
        "counter_a": counter_a,
        "counter_b": counter_b,
        "supplier_one": supplier_one,
        "supplier_two": supplier_two,
        "snapper": snapper,
        "lot": lot,
    }


def _advertisement_with_its_origin_branch_already_cleared(api) -> dict:
    """A DRAFT advertisement whose country-of-origin branch was cleared by officer-cool-1."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    item = fixtures.draft_ad_item(
        api,
        counter_id,
        lot["id"],
        headline="Fresh Atlantic Cod at the Counter",
        ad_start_at="2026-08-01T09:00:00Z",
        ad_end_at="2026-08-01T10:00:00Z",
    )
    fixtures.clear_ad_cool(api, item["id"], officer_id=OFFICER_COOL_USER_ID)
    env.update({"lot": lot, "item": item})
    return env


def _cased_lot_with_one_published_label(api) -> dict:
    """A cod lot in slot 1 carrying its first PUBLISHED case label."""
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    lot = fixtures.receive_lot(
        api, counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    fixtures.case_lot(api, counter_id, lot["id"], 1)
    label = fixtures.publish_case_label(api, counter_id, lot["id"])
    env.update({"lot": lot, "label": label})
    return env


def test_01_the_headerless_caller_is_answered_before_the_wrong_role_is(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` is not one of those five
    strings, the request fails with `ERR_UNAUTHENTICATED` (HTTP 401). If the headers are well
    formed but the declared role is not among the roles authorised for the addressed operation
    in §4, the request fails with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/lot_receipt_denied_to_merchandising_lead_and_to_a_headerless_caller
    """
    env = fixtures.base_environment(api, "2026-08-01T08:00:00Z")
    counter_id = env["counter"]["id"]
    receipt = factories.lot_payload(
        counter_id, env["supplier"]["id"], env["cod"]["id"], received_weight_kg=10.000
    )
    manager = make_seafood_manager_headers(counter_id)

    validate_error(
        api.create_lot(receipt, headers_without_user_id("SeafoodManager")),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        expected_status=401,
    )
    validate_error(
        api.create_lot(receipt, make_merchandising_lead_headers()),
        ApiErrorId.ERR_UNAUTHORIZED.value,
        expected_status=403,
    )

    _, meta = validate_paginated(api.list_lots(manager, params={"counter_id": counter_id}))
    assert meta["total_count"] == 0, "neither refusal may leave a lot row behind"

    accepted = validate_success(api.create_lot(receipt, manager), expected_status=201)
    assert accepted["intake_status"] == "RECEIVED"


def test_02_a_dealer_may_only_file_documents_against_its_own_lots(api):
    """PRD §2.1: "When `X-User-Role` is `SupplierRep`, `X-User-ID` is the `id` of the acting
    `Supplier`; ownership checks on any resource that references a `Supplier` compare the
    resource's supplier foreign key to `X-User-ID`."

    Design: Corner/rbac/manager_and_supplier_scopes_are_peer_isolated
    """
    env = _two_counters_two_dealers_and_a_snapper_lot(api)
    lot_id = env["lot"]["id"]
    filing = simp_document_payload(
        lot_id,
        harvesting_vessel_name="Estrella del Golfo",
        harvest_date="2026-07-20T00:00:00Z",
        landing_date="2026-07-22T00:00:00Z",
        chain_of_custody_ref="COC-55210",
    )

    intruder = api.create_simp_document(
        filing, make_supplier_rep_headers(env["supplier_two"]["id"])
    )
    validate_error(intruder, ApiErrorId.ERR_SUPPLIER_SCOPE_FORBIDDEN.value, expected_status=403)

    owner = validate_success(
        api.create_simp_document(filing, make_supplier_rep_headers(env["supplier_one"]["id"])),
        expected_status=201,
    )

    assert_simp_document(owner)
    assert owner["status"] == "DRAFT"
    assert owner["lot_id"] == lot_id


def test_03_a_manager_may_only_case_lots_that_stand_at_its_own_counter(api):
    """PRD §2.1: "A mismatch is rejected with `ERR_COUNTER_SCOPE_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/manager_and_supplier_scopes_are_peer_isolated
    """
    env = _two_counters_two_dealers_and_a_snapper_lot(api)
    counter_a_id = env["counter_a"]["id"]
    lot_id = env["lot"]["id"]
    document = fixtures.accepted_simp_document(
        api,
        env["supplier_one"]["id"],
        lot_id,
        harvesting_vessel_name="Estrella del Golfo",
        harvest_date="2026-07-20T00:00:00Z",
        landing_date="2026-07-22T00:00:00Z",
        chain_of_custody_ref="COC-55210",
    )
    assert document["status"] == "ACCEPTED"

    peer = api.case_lot(
        lot_id, {"case_slot": 1}, make_seafood_manager_headers(env["counter_b"]["id"])
    )
    refusal = validate_error(
        peer, ApiErrorId.ERR_COUNTER_SCOPE_FORBIDDEN.value, expected_status=403
    )
    assert refusal["error_id"] != ApiErrorId.ERR_LOT_NOT_FOUND.value

    untouched = fixtures.read_lot(api, counter_a_id, lot_id)
    assert untouched["intake_status"] == "RECEIVED"
    assert untouched["case_slot"] is None

    cased = fixtures.case_lot(api, counter_a_id, lot_id, 1)
    assert cased["intake_status"] == "CASED"
    assert cased["case_slot"] == 1


def test_04_the_officer_who_cleared_the_origin_branch_may_not_clear_the_claim(api):
    """PRD §2.1: "When the acting `X-User-ID` on the claim branch equals the advertisement's
    recorded `cool_reviewer_user_id`, the request is rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    Design: Corner/rbac/claim_reviewer_must_differ_from_the_cool_reviewer
    """
    env = _advertisement_with_its_origin_branch_already_cleared(api)
    item_id = env["item"]["id"]

    same_officer = api.clear_ad_claim(
        item_id, {"decision": "CLEAR"}, make_compliance_officer_headers(OFFICER_COOL_USER_ID)
    )
    validate_error(same_officer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, expected_status=403)

    unchanged = fixtures.read_ad_item(api, item_id)
    assert unchanged["claim_review_status"] == "CLAIM_PENDING"
    assert unchanged["claim_reviewer_user_id"] is None
    assert unchanged["status"] == "DRAFT"

    cleared = fixtures.clear_ad_claim(api, item_id, officer_id=OFFICER_CLAIM_USER_ID)

    assert cleared["claim_review_status"] == "CLAIM_CLEARED"
    assert cleared["cool_reviewer_user_id"] == OFFICER_COOL_USER_ID
    assert cleared["claim_reviewer_user_id"] == OFFICER_CLAIM_USER_ID
    assert cleared["status"] == "APPROVED"


def test_05_withdrawal_answers_to_the_manager_and_the_officer_but_not_the_lead(api):
    """PRD §3.4: "An operator-initiated withdrawal — available to both the `SeafoodManager` and
    a `ComplianceOfficer` — carries a `reason` in the payload, which is stored in
    `withdraw_reason`, and stamps `withdrawn_at` from the logical clock; because an
    operator-submitted reason is never `SPECIES_MISMATCH`, no shrink event follows from it."

    Design: Corner/rbac/label_withdrawal_is_shared_by_manager_and_compliance_officer
    """
    env = _cased_lot_with_one_published_label(api)
    counter_id = env["counter"]["id"]
    lot_id = env["lot"]["id"]
    first_label_id = env["label"]["id"]

    lead = api.withdraw_case_label(
        first_label_id, {"reason": "MANUAL"}, make_merchandising_lead_headers()
    )
    validate_error(lead, ApiErrorId.ERR_UNAUTHORIZED.value, expected_status=403)
    assert fixtures.read_case_label(api, counter_id, first_label_id)["status"] == "PUBLISHED"

    by_manager = fixtures.withdraw_case_label(api, counter_id, first_label_id, "MANUAL")
    assert by_manager["status"] == "WITHDRAWN"
    assert by_manager["withdraw_reason"] == "MANUAL"

    second_label = validate_success(
        api.create_case_label(
            case_label_payload(lot_id, fixtures.lot_version(api, counter_id, lot_id)),
            make_seafood_manager_headers(counter_id),
        ),
        expected_status=201,
    )
    assert_case_label(second_label)
    assert second_label["status"] == "PUBLISHED"

    by_officer = validate_success(
        api.withdraw_case_label(
            second_label["id"],
            {"reason": "MANUAL"},
            make_compliance_officer_headers(OFFICER_COOL_USER_ID),
        ),
        expected_status=200,
    )
    assert by_officer["status"] == "WITHDRAWN"
    assert by_officer["withdraw_reason"] == "MANUAL"
    assert fixtures.read_lot(api, counter_id, lot_id)["intake_status"] == "CASED"
