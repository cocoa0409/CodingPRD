"""Operations gated on a second entity's state rather than on their own."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_line, line_types
from test_helpers.test_users import BILLING_1, INTAKE_1


# --------------------------------------------------------------------------
# intake_accept_requires_valid_and_unexpired_authorization
# --------------------------------------------------------------------------
def _two_requests_on_two_flawed_authorizations(api):
    """One request rests on a DEFECTIVE authorization; the other rests on a VALID
    authorization that lapses at 2026-08-20T00:00:00Z.  Neither is accepted yet."""
    world = fx.base_world(api)
    attorney = fx.make_attorney(api)
    insurer = fx.make_insurer(api)
    defective = fx.make_authorization(
        api, world["patient_id"], attorney["id"], signature_verified=False
    )
    lapsing = fx.make_authorization(
        api,
        world["patient_id"],
        insurer["id"],
        expires_at="2026-08-20T00:00:00Z",
        designated_recipient_endpoint="claims@carrier.example",
    )
    request_1 = get_success_data(
        api.create_request(
            f.third_party_request_payload(
                world["facility_id"],
                world["patient_id"],
                attorney["id"],
                defective["id"],
                date_range_start="2024-01-01",
                date_range_end="2024-12-31",
            ),
            INTAKE_1,
        )
    )
    request_2 = get_success_data(
        api.create_request(
            f.third_party_request_payload(
                world["facility_id"],
                world["patient_id"],
                insurer["id"],
                lapsing["id"],
                date_range_start="2024-01-01",
                date_range_end="2024-12-31",
            ),
            INTAKE_1,
        )
    )
    return {
        "world": world,
        "defective_authorization": defective["id"],
        "lapsing_authorization": lapsing["id"],
        "request_1": request_1["id"],
        "request_2": request_2["id"],
    }


def _accept(api, request_id):
    return api.intake_decision(request_id, f.intake_decision_payload("ACCEPT"), INTAKE_1)


def test_a_request_may_be_opened_on_an_authorization_that_is_already_defective(api):
    """Creation looks at no other entity's status; both requests land in INTAKE_REVIEW.

    PRD: "On success the system stamps `received_at` with the current logical clock — this is the statutory clock's arrival anchor — records `intake_user_id` as the creating `X-User-ID`, sets `fulfillment_status` to `INTAKE_REVIEW` and `billing_status` to `PENDING_INVOICE`, leaves `release_reviewer_user_id` null, and computes `statutory_due_at`."

    Design: Difficulty/cross_entity_state_dependency/intake_accept_requires_valid_and_unexpired_authorization
    """
    scenario = _two_requests_on_two_flawed_authorizations(api)

    assert fx.read_request(api, scenario["request_1"])["fulfillment_status"] == "INTAKE_REVIEW"
    assert fx.read_request(api, scenario["request_2"])["fulfillment_status"] == "INTAKE_REVIEW"
    authorization = get_success_data(
        api.get_authorization(scenario["defective_authorization"], INTAKE_1)
    )
    assert authorization["status"] == "DEFECTIVE"


def test_accept_is_refused_while_the_governing_authorization_is_defective(api):
    """The request's own state is impeccable; the other entity's status blocks it.

    PRD: "An authorization whose `status` is not `VALID` reports `ERR_AUTHORIZATION_NOT_VALID`; an authorization whose `expires_at` is at or before the current logical clock reports `ERR_AUTHORIZATION_EXPIRED` — the boundary is exclusive at the top, so an `expires_at` exactly equal to the clock is already lapsed."

    Design: Difficulty/cross_entity_state_dependency/intake_accept_requires_valid_and_unexpired_authorization
    """
    scenario = _two_requests_on_two_flawed_authorizations(api)
    before = fx.read_request(api, scenario["request_1"])

    validate_error(_accept(api, scenario["request_1"]), e.ERR_AUTHORIZATION_NOT_VALID, 409)

    after = fx.read_request(api, scenario["request_1"])
    assert after["fulfillment_status"] == "INTAKE_REVIEW"
    assert after["version"] == before["version"]


def test_curing_the_other_entity_moves_it_from_defective_to_valid(api):
    """The gate is opened by writing to the authorization, not to the request.

    PRD: "**Curing a defect** is an `IntakeSpecialist` capability and moves the authorization from `DEFECTIVE` to `VALID`."

    Design: Difficulty/cross_entity_state_dependency/intake_accept_requires_valid_and_unexpired_authorization
    """
    scenario = _two_requests_on_two_flawed_authorizations(api)

    get_success_data(
        api.cure_authorization(
            scenario["defective_authorization"], f.authorization_cure_payload(), INTAKE_1
        )
    )

    authorization = get_success_data(
        api.get_authorization(scenario["defective_authorization"], INTAKE_1)
    )
    assert authorization["status"] == "VALID"


def test_the_cure_clears_the_recorded_defect_reasons(api):
    """SIGNATURE_UNVERIFIED disappears once the signature is verified.

    PRD: "On success `defect_reasons` is cleared, the authorization's `version` increments by 1, and every request whose `authorization_id` names this authorization and which is parked in `AUTH_DEFECT_PENDING` cascades back to `INTAKE_REVIEW`, closing its tolling interval and recomputing its `statutory_due_at` as described in §3.3."

    Design: Difficulty/cross_entity_state_dependency/intake_accept_requires_valid_and_unexpired_authorization
    """
    scenario = _two_requests_on_two_flawed_authorizations(api)
    before = get_success_data(
        api.get_authorization(scenario["defective_authorization"], INTAKE_1)
    )
    assert before["defect_reasons"] == ["SIGNATURE_UNVERIFIED"]

    get_success_data(
        api.cure_authorization(
            scenario["defective_authorization"], f.authorization_cure_payload(), INTAKE_1
        )
    )

    after = get_success_data(api.get_authorization(scenario["defective_authorization"], INTAKE_1))
    assert after["defect_reasons"] == []
    assert after["version"] == before["version"] + 1


def test_the_same_accept_call_succeeds_once_the_authorization_is_valid(api):
    """Nothing about the request changed; only the entity it depends on did.

    PRD: "A `decision` of `ACCEPT` moves the request from `INTAKE_REVIEW` to `COMPILATION`; it requires that the governing facility's `status` be `ACTIVE`, and, when the `access_basis` is `THIRD_PARTY_AUTHORIZATION`, that the governing authorization's `status` be `VALID` and its `expires_at` be strictly after the current logical clock; when the `access_basis` is `PATIENT_RIGHT_OF_ACCESS` the `authorization_id` must be null."

    Design: Difficulty/cross_entity_state_dependency/intake_accept_requires_valid_and_unexpired_authorization
    """
    scenario = _two_requests_on_two_flawed_authorizations(api)
    validate_error(_accept(api, scenario["request_1"]), e.ERR_AUTHORIZATION_NOT_VALID, 409)
    get_success_data(
        api.cure_authorization(
            scenario["defective_authorization"], f.authorization_cure_payload(), INTAKE_1
        )
    )

    validate_success(_accept(api, scenario["request_1"]), 200)

    accepted = fx.read_request(api, scenario["request_1"])
    assert accepted["fulfillment_status"] == "COMPILATION"
    assert accepted["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")


def test_an_authorization_expiring_exactly_now_is_already_lapsed(api):
    """At a clock equal to expires_at the coverage interval is already closed.

    PRD: "An authorization whose `status` is not `VALID` reports `ERR_AUTHORIZATION_NOT_VALID`; an authorization whose `expires_at` is at or before the current logical clock reports `ERR_AUTHORIZATION_EXPIRED` — the boundary is exclusive at the top, so an `expires_at` exactly equal to the clock is already lapsed."

    Design: Difficulty/cross_entity_state_dependency/intake_accept_requires_valid_and_unexpired_authorization
    """
    scenario = _two_requests_on_two_flawed_authorizations(api)
    fx.set_clock(api, "2026-08-20T00:00:00Z")

    validate_error(_accept(api, scenario["request_2"]), e.ERR_AUTHORIZATION_EXPIRED, 409)

    assert fx.read_request(api, scenario["request_2"])["fulfillment_status"] == "INTAKE_REVIEW"
    lapsing = get_success_data(api.get_authorization(scenario["lapsing_authorization"], INTAKE_1))
    assert lapsing["status"] == "VALID"


# --------------------------------------------------------------------------
# invoice_creation_requires_request_release_ready
# --------------------------------------------------------------------------
def _compiled_request_with_a_segregated_segment(api):
    """40 general-medical pages plus 22 behavioural-health pages retrieved, the parent
    request still sitting in COMPILATION."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"]
    )
    fx.accept_request(api, request["id"])
    ids = fx.build_segments(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
        ],
    )
    return {"world": world, "request_id": request["id"], "segment_ids": ids}


def _try_to_invoice(api, request_id):
    """Always re-read the version first so the OCC guard can never mask a state error."""
    payload = f.invoice_payload(request_id, fx.request_version(api, request_id))
    return api.create_invoice(payload, BILLING_1)


def _walk_into_redaction(api, scenario):
    fx.complete_compilation(api, scenario["request_id"])
    fx.run_sensitive_review(
        api,
        scenario["request_id"],
        [f.include_decision(scenario["segment_ids"]["bh"], redaction_required=True)],
    )
    return scenario


def test_the_child_cannot_be_born_while_the_parent_is_still_compiling(api):
    """Pricing a request in COMPILATION is refused and leaves no partial invoice.

    PRD: "Pricing is refused unless the request's `fulfillment_status` is `RELEASE_READY` or `RELEASED`, with `ERR_REQUEST_NOT_RELEASE_READY`; unless every redaction is settled, since a segment still holding `redaction_status` `OPEN`, `APPLIED` or `REWORK` yields `ERR_REDACTION_NOT_APPROVED`; and unless there is something to bill, since a request whose `billing_status` is already `NOT_BILLABLE`, or whose computed `subtotal_cents` works out to 0, yields `ERR_NOTHING_TO_INVOICE`."

    Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_request_release_ready
    """
    scenario = _compiled_request_with_a_segregated_segment(api)
    assert fx.read_request(api, scenario["request_id"])["fulfillment_status"] == "COMPILATION"

    validate_error(
        _try_to_invoice(api, scenario["request_id"]), e.ERR_REQUEST_NOT_RELEASE_READY, 409
    )

    rows, _meta = fx.list_invoices_for(api, scenario["request_id"])
    assert rows == []


def test_the_parent_state_check_outranks_the_unsettled_redaction_check(api):
    """In REDACTION with the redaction OPEN and then APPLIED, the state error still wins.

    PRD: "Validation is a single ordered pipeline, and the **first** violated rule determines the response; later violations are not reported."

    Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_request_release_ready
    """
    scenario = _walk_into_redaction(api, _compiled_request_with_a_segregated_segment(api))
    request_id = scenario["request_id"]
    assert fx.read_request(api, request_id)["fulfillment_status"] == "REDACTION"
    assert fx.read_segment(api, scenario["segment_ids"]["bh"])["redaction_status"] == "OPEN"

    validate_error(_try_to_invoice(api, request_id), e.ERR_REQUEST_NOT_RELEASE_READY, 409)

    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 5)
    assert fx.read_segment(api, scenario["segment_ids"]["bh"])["redaction_status"] == "APPLIED"

    validate_error(_try_to_invoice(api, request_id), e.ERR_REQUEST_NOT_RELEASE_READY, 409)

    rows, _meta = fx.list_invoices_for(api, request_id)
    assert rows == []


def test_the_invoice_freezes_the_parent_page_count_once_the_parent_is_ready(api):
    """The approval bubbles the parent up and the fourth attempt snapshots 57 pages.

    PRD: "At creation the request's `billable_page_count` is frozen onto the invoice as `billable_page_count_snapshot`, and that frozen page count — call it the priced page count — is what every per-page line uses."

    Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_request_release_ready
    """
    scenario = _walk_into_redaction(api, _compiled_request_with_a_segregated_segment(api))
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 5)
    fx.approve_redaction(api, scenario["segment_ids"]["bh"])
    assert fx.read_request(api, scenario["request_id"])["fulfillment_status"] == "RELEASE_READY"

    invoice = validate_success(_try_to_invoice(api, scenario["request_id"]), 201)

    assert invoice["billable_page_count_snapshot"] == 57
    assert invoice["status"] == "DRAFT"


def test_the_accepted_attempt_prices_the_snapshot_and_leaves_exactly_one_invoice(api):
    """57 pages price at 1500 + 688 + 400, and the three rejections left nothing behind.

    PRD: "The invoice's `subtotal_cents` is the plain sum of `amount_cents` over the emitted lines, and the two adjustment line types described next — `CAP_ADJUSTMENT` and `LATE_FEE_FORFEITURE` — are deliberately **not** part of that subtotal."

    Design: Difficulty/cross_entity_state_dependency/invoice_creation_requires_request_release_ready
    """
    scenario = _walk_into_redaction(api, _compiled_request_with_a_segregated_segment(api))
    request_id = scenario["request_id"]
    validate_error(_try_to_invoice(api, request_id), e.ERR_REQUEST_NOT_RELEASE_READY, 409)
    fx.apply_redaction(api, scenario["segment_ids"]["bh"], 5)
    fx.approve_redaction(api, scenario["segment_ids"]["bh"])

    invoice = validate_success(_try_to_invoice(api, request_id), 201)
    lines = fx.read_lines(api, invoice["id"])

    assert len(lines) == 3, line_types(lines)
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "PER_PAGE_TIER2", 32, 12500, 400)
    assert invoice["subtotal_cents"] == 2588
    assert invoice["amount_due_cents"] == 2588

    rows, meta = fx.list_invoices_for(api, request_id)
    assert len(rows) == 1
    assert meta["total_count"] == 1
