"""Role authorization, Producer ownership scoping, the computed eligibility
read, and immediate read-after-write consistency (PRD sections 2.1, 2.2, 3.2,
3.5, 3.6, 3.9).
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    get_entry_for_application,
    get_producer,
    get_success_data,
    make_producer_headers,
    report_ce_credit,
    setup_approved_application,
    setup_jit_scenario,
    setup_producer_with_license,
    setup_suspended_producer,
    create_producer,
    validate_error,
    validate_success,
    assert_instant_equals,
    DEFAULT_CLOCK_ISO,
    TEST_USERS,
)

LC = TEST_USERS["licensing_coordinator_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


def test_ce_review_by_finance_ops_forbidden():
    """PRD section 2.1: "every operation is restricted by role; an attempt to
    perform an action outside the caller's designated role is rejected with
    `ERR_FORBIDDEN` (HTTP 403)." PRD section 3.2: "A `LicensingCoordinator`
    reviews each `REPORTED` credit" — the review is not a FinanceOps
    operation.

    Design: Corner/rbac/ce_credit_review_by_finance_ops_forbidden
    """
    bundle = setup_producer_with_license(npn="NPN-3030")
    credit = report_ce_credit(bundle["license"]["id"], course_title="X",
                              credit_hours=5)

    resp = api_client.review_ce_credit(credit["id"], {"decision": "ACCEPT"}, FINANCE)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_success_data(api_client.get_ce_credit(credit["id"], LC))["status"] == "REPORTED"


def test_producer_cannot_release_commission():
    """PRD section 3.6: "Release is a `ComplianceOfficer` decision". PRD
    section 2.1: "every operation is restricted by role; an attempt to perform
    an action outside the caller's designated role is rejected with
    `ERR_FORBIDDEN` (HTTP 403)" — the role gate binds the Producer even on its
    own entry.

    Design: Corner/rbac/producer_cannot_release_commission_forbidden
    """
    bundle = setup_jit_scenario(npn="NPN-3031", line_of_authority="LIFE",
                                premium_cents=1_000_000)
    entry = bundle["entry"]
    assert entry["status"] == "HELD"

    resp = api_client.release_commission_entry(
        entry["id"], make_producer_headers(bundle["producer"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    assert get_entry_for_application(bundle["application"]["id"])["status"] == "HELD"


def test_producer_reading_other_producer_forbidden():
    """PRD section 2.1: "When `X-User-Role` is `Producer`, `X-User-ID` is the
    `id` of the acting Producer record, and every ownership check compares a
    resource's producer foreign key to that value: a Producer may submit an
    application only when the payload's `producer_id` equals their `X-User-ID`,
    may report continuing-education credits only against licenses they hold,
    and may read only those records whose producer link equals their
    `X-User-ID`."

    Design: Corner/rbac/producer_reading_other_producer_forbidden
    """
    first = create_producer(npn="NPN-3032", full_name="Self")
    second = create_producer(npn="NPN-3033", full_name="Other")
    first_headers = make_producer_headers(first["id"])

    own = validate_success(api_client.get_producer(first["id"], first_headers), 200)
    assert own["id"] == first["id"]

    cross = api_client.get_producer(second["id"], first_headers)
    validate_error(cross, ApiErrorId.ERR_FORBIDDEN)


def test_eligibility_precedence_suspended_beats_license_gap():
    """PRD section 3.5: "The posture derivation has a fixed precedence: if the
    producer is not `ACTIVE` the posture is `PRODUCER_SUSPENDED`; otherwise, if
    the producer holds no `ACTIVE` license in the state covering the line, the
    posture is `LICENSE_GAP`".
    PRD section 3.9: "Given `state_code` and `line_of_authority`, the read
    returns `eligibility_status` — one of `ELIGIBLE`, `LICENSE_GAP`,
    `APPOINTMENT_GAP`, or `PRODUCER_SUSPENDED`, derived with the fixed
    precedence of §3.5 — together with the `license_id` and `appointment_id` of
    the covering records, each null when no such covering record exists, and
    `via_agency`, true exactly when only the affiliated agency's appointment
    provides the coverage."

    Design: Corner/endpoints/eligibility_precedence_suspended_beats_license_gap
    """
    bundle = setup_suspended_producer(npn="NPN-3028", reference_number="INQ-3028")
    producer_id = bundle["producer"]["id"]
    assert bundle["producer"]["status"] == "SUSPENDED"

    view = validate_success(
        api_client.get_producer_eligibility(
            producer_id, LC, params={"state_code": "TX", "line_of_authority": "LIFE"}
        ),
        200,
    )
    assert view["eligibility_status"] == "PRODUCER_SUSPENDED", (
        "the producer suspension outranks the license gap that also holds"
    )
    assert view["license_id"] is None
    assert view["appointment_id"] is None
    assert view["via_agency"] is False


def test_mutation_immediately_visible_in_same_response():
    """PRD section 2.2: "operations that create or modify a resource will
    return the created or updated resource object in the data field."
    PRD section 3.5: "On issue the application becomes `ISSUED` with
    `issued_at` stamped, the `eligibility_snapshot` is re-evaluated, the
    producer's year-to-date issued premium is recomputed with this application
    now in the input set, and the commission entry is repriced to its final
    figure per §3.6." The issued response, a follow-up read, and the derived
    counter all agree.

    Design: Corner/consistency_model/mutation_immediately_visible_in_same_response
    """
    bundle = setup_approved_application(
        npn="NPN-3038", line_of_authority="LIFE", premium_cents=1_000_000
    )
    issued = validate_success(
        api_client.issue_application(bundle["application"]["id"], LC), 200
    )
    assert issued["status"] == "ISSUED"
    assert_instant_equals(issued["issued_at"], DEFAULT_CLOCK_ISO, "issued_at")

    reread = validate_success(
        api_client.get_application(bundle["application"]["id"], LC), 200
    )
    assert reread["status"] == "ISSUED"
    assert reread["issued_at"] == issued["issued_at"], (
        "the read agrees with the mutation response"
    )

    producer = get_producer(bundle["producer"]["id"])
    assert producer["ytd_issued_premium_cents"] == 1_000_000, (
        "the derived counter is reconciled within the same request scope"
    )
