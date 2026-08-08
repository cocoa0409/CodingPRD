"""Permit lifecycle: fee assembly, issuance gates, renewal cycle, term overlap, OCC."""
from test_helpers import (
    ApiErrorId,
    validate_success, validate_error,
    make_producer_headers, TEST_USERS,
    create_permit_payload, create_inspection_payload,
    create_registered_producer, create_class_a_issued_permit,
    create_class_b_issued_permit,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def test_class_a_permit_fee_is_5000(api):
    """PRD §3.3: "a `CLASS_A` permit therefore totals 5,000 cents (2,500 base plus
    2,500 tier plus 0 inspection), and a `CLASS_B` permit totals 15,500 cents"

    Design: Corner/calculations/permit_fee_class_a_value
    """
    producer = create_registered_producer(api, business_name="FeeA Co")
    permit = create_class_a_issued_permit(api, producer["id"])
    assert permit["fee_cents"] == 5000


def test_class_b_permit_fee_is_15500(api):
    """PRD §3.3: "a `CLASS_A` permit therefore totals 5,000 cents (2,500 base plus
    2,500 tier plus 0 inspection), and a `CLASS_B` permit totals 15,500 cents (7,500
    base plus 5,000 tier plus 3,000 inspection)."

    Design: Difficulty/combinatorial_formula/permit_fee_class_b_three_input_tiered
    """
    producer = create_registered_producer(api, business_name="Pickle Pros")
    permit = create_class_b_issued_permit(api, producer["id"])
    assert permit["fee_cents"] == 15500


def test_class_b_permit_reaches_issued_after_inspection(api):
    """PRD §3.3: "For a `CLASS_B` permit, issuance goes from `UNDER_INSPECTION` to
    `ISSUED` and requires that a `PASSED` inspection exists for the permit"

    Design: Difficulty/combinatorial_formula/permit_fee_class_b_three_input_tiered
    """
    producer = create_registered_producer(api, business_name="Pickle Pros 2")
    permit = create_class_b_issued_permit(api, producer["id"])
    assert permit["status"] == "ISSUED"


def test_submit_already_issued_permit_rejected(api):
    """PRD §3.3: "Any request to submit, issue, or renew a permit that is not in a legal
    state for that transition is rejected with `ERR_PERMIT_INVALID_STATE`."

    Design: Corner/state_machines/permit_submit_from_issued_returns_invalid_state
    """
    producer = create_registered_producer(api, business_name="IsCo")
    permit = create_class_a_issued_permit(api, producer["id"])
    resp = api.submit_permit(permit["id"], make_producer_headers(producer["id"]))
    validate_error(resp, ApiErrorId.ERR_PERMIT_INVALID_STATE.value, 409)
    after = validate_success(api.get_permit(permit["id"], INSPECTOR), 200)
    assert after["status"] == "ISSUED"


def test_renewal_cycle_returns_permit_to_issued(api):
    """PRD §3.3: "Re-issuing a `RENEWAL_PENDING` permit is again a health inspector's
    action and returns it to `ISSUED`; for a `CLASS_B` permit this re-issue requires a
    `PASSED` inspection whose `inspection_type` is `RENEWAL`, failing otherwise with
    `ERR_INSPECTION_NOT_PASSED`."

    Design: Difficulty/non_linear_state_machine/permit_renewal_cycle_returns_to_issued
    """
    producer = create_registered_producer(api, business_name="Bread Basket")
    permit = create_class_a_issued_permit(api, producer["id"])
    ph = make_producer_headers(producer["id"])
    validate_success(api.renew_permit(permit["id"], {"expected_permit_version": permit["version"]}, ph), 200)
    reissued = validate_success(api.issue_permit(permit["id"], INSPECTOR), 200)
    assert reissued["status"] == "ISSUED"


def test_renewal_increments_renewal_count(api):
    """PRD §3.3: "Each re-issue on the renewal path increments `renewal_count` by one
    and resets `term_start` and `expires_at` to a fresh 365-day term from the current
    clock."

    Design: Difficulty/non_linear_state_machine/permit_renewal_cycle_returns_to_issued
    """
    producer = create_registered_producer(api, business_name="Bread Basket 2")
    permit = create_class_a_issued_permit(api, producer["id"])
    ph = make_producer_headers(producer["id"])
    validate_success(api.renew_permit(permit["id"], {"expected_permit_version": permit["version"]}, ph), 200)
    reissued = validate_success(api.issue_permit(permit["id"], INSPECTOR), 200)
    assert reissued["renewal_count"] == 1


def _classb_under_inspection(api, business_name):
    producer = create_registered_producer(api, business_name=business_name)
    pid = producer["id"]
    ph = make_producer_headers(pid)
    permit = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_B"), ph), 201)
    validate_success(api.submit_permit(permit["id"], ph), 200)
    # Scheduling an inspection advances a SUBMITTED permit to UNDER_INSPECTION.
    validate_success(api.create_inspection(create_inspection_payload(permit["id"], "ROUTINE"), INSPECTOR), 201)
    return permit["id"]


def test_classb_issue_without_passed_inspection_rejected(api):
    """PRD §3.3: "For a `CLASS_B` permit, issuance goes from `UNDER_INSPECTION` to
    `ISSUED` and requires that a `PASSED` inspection exists for the permit; absent one,
    issuance fails with `ERR_INSPECTION_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/classb_permit_issue_requires_passed_inspection
    """
    permit_id = _classb_under_inspection(api, "Inspect Me")
    resp = api.issue_permit(permit_id, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_PASSED.value, 409)


def test_classb_issue_without_passed_inspection_keeps_under_inspection(api):
    """PRD §3.3: "attempting the `CLASS_A` path on a `CLASS_B` permit is illegal because
    a `CLASS_B` permit must pass through `UNDER_INSPECTION` first. For a `CLASS_B`
    permit, issuance goes from `UNDER_INSPECTION` to `ISSUED` and requires that a
    `PASSED` inspection exists for the permit; absent one, issuance fails with
    `ERR_INSPECTION_NOT_PASSED`."

    Design: Difficulty/cross_entity_state_dependency/classb_permit_issue_requires_passed_inspection
    """
    permit_id = _classb_under_inspection(api, "Inspect Me 2")
    validate_error(api.issue_permit(permit_id, INSPECTOR), ApiErrorId.ERR_INSPECTION_NOT_PASSED.value, 409)
    after = validate_success(api.get_permit(permit_id, INSPECTOR), 200)
    assert after["status"] == "UNDER_INSPECTION"


def _producer_with_second_submitted_permit(api, business_name):
    producer = create_registered_producer(api, business_name=business_name)
    pid = producer["id"]
    ph = make_producer_headers(pid)
    create_class_a_issued_permit(api, pid)  # first ISSUED permit, term from default clock
    perm2 = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_A"), ph), 201)
    validate_success(api.submit_permit(perm2["id"], ph), 200)
    return perm2["id"]


def test_second_permit_overlapping_term_rejected(api):
    """PRD §3.3: "In both first-issue paths the server rejects issuance with
    `ERR_PERMIT_TERM_OVERLAP` if the producer already holds another `ISSUED` permit
    whose term interval overlaps the new term."

    Design: Difficulty/resource_temporal_overlap/permit_term_overlap_half_open
    """
    perm2_id = _producer_with_second_submitted_permit(api, "Overlap Co")
    resp = api.issue_permit(perm2_id, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_PERMIT_TERM_OVERLAP.value, 409)


def test_second_permit_overlapping_term_stays_submitted(api):
    """PRD §3.3: "In both first-issue paths the server rejects issuance with
    `ERR_PERMIT_TERM_OVERLAP` if the producer already holds another `ISSUED` permit
    whose term interval overlaps the new term."

    Design: Difficulty/resource_temporal_overlap/permit_term_overlap_half_open
    """
    perm2_id = _producer_with_second_submitted_permit(api, "Overlap Co 2")
    validate_error(api.issue_permit(perm2_id, INSPECTOR), ApiErrorId.ERR_PERMIT_TERM_OVERLAP.value, 409)
    after = validate_success(api.get_permit(perm2_id, INSPECTOR), 200)
    assert after["status"] == "SUBMITTED"


def test_close_passed_inspection_again_rejected(api):
    """PRD §3.6: "An inspection that is not in `SCHEDULED` cannot be closed and yields
    `ERR_INSPECTION_NOT_SCHEDULED`."

    Design: Corner/state_machines/inspection_close_twice_returns_invalid_state
    """
    producer = create_registered_producer(api, business_name="InsCo")
    pid = producer["id"]
    ph = make_producer_headers(pid)
    permit = validate_success(api.create_permit(create_permit_payload(pid, "CLASS_B"), ph), 201)
    validate_success(api.submit_permit(permit["id"], ph), 200)
    insp = validate_success(api.create_inspection(create_inspection_payload(permit["id"], "ROUTINE"), INSPECTOR), 201)
    validate_success(api.close_inspection(insp["id"], {"result": "PASS", "violation_count": 0}, INSPECTOR), 200)
    resp = api.close_inspection(insp["id"], {"result": "PASS", "violation_count": 0}, INSPECTOR)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_NOT_SCHEDULED.value, 409)
    after = validate_success(api.get_inspection(insp["id"], INSPECTOR), 200)
    assert after["status"] == "PASSED"


def test_renew_with_stale_permit_version_rejected(api):
    """PRD §2.9: "If the permit's `version` has advanced since the client read it —
    because a prior renewal, or a cascade that suspended the permit, legitimately bumped
    it — the request is rejected with `ERR_STALE_PERMIT_VERSION` at HTTP 412, preventing
    the producer from renewing a permit whose state they have not observed."

    Design: Corner/cross_cutting/occ_stale_permit_version_rejected
    """
    producer = create_registered_producer(api, business_name="OccP Co")
    permit = create_class_a_issued_permit(api, producer["id"])
    ph = make_producer_headers(producer["id"])
    resp = api.renew_permit(permit["id"], {"expected_permit_version": permit["version"] - 1}, ph)
    validate_error(resp, ApiErrorId.ERR_STALE_PERMIT_VERSION.value, 412)
    after = validate_success(api.get_permit(permit["id"], INSPECTOR), 200)
    assert after["status"] == "ISSUED"
