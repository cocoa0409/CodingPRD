"""State-machine corners: initial states, illegal origins, transition preconditions and
the declared side-effect list of one accepted transition."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import ANALYST_1, INTAKE_1, PRIVACY_1, REVIEWER_1
from test_helpers.assertions import Instant


def test_a_fresh_segment_holds_all_three_dimensions_at_their_declared_origin(api):
    """PENDING, UNCLASSIFIED and NOT_REQUIRED move independently and all start at once.

    PRD: "A newly created segment has `retrieval_status` `PENDING`, `sensitivity_status` `UNCLASSIFIED`, `redaction_status` `NOT_REQUIRED`, `page_count` 0, `redacted_page_count` 0, `retrieved_at` null, `unavailable_reason` null, `redaction_applied_by_user_id` null, `redaction_approved_by_user_id` null, and `amended` false."

    Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_states
    """
    world = fx.third_party_world(api)
    assert world["authorization"]["status"] == "VALID"
    request = fx.open_third_party_request(api, world)
    assert request["fulfillment_status"] == "INTAKE_REVIEW"
    assert request["billing_status"] == "PENDING_INVOICE"
    fx.accept_request(api, request["id"])

    segment = validate_success(
        api.create_record_segment(
            f.record_segment_payload(request["id"], "GENERAL_MEDICAL", "EHR_CURRENT"), ANALYST_1
        ),
        201,
    )

    assert segment["retrieval_status"] == "PENDING"
    assert segment["sensitivity_status"] == "UNCLASSIFIED"
    assert segment["redaction_status"] == "NOT_REQUIRED"
    assert segment["page_count"] == 0
    assert segment["redacted_page_count"] == 0
    assert segment["retrieved_at"] is None
    assert segment["legacy_job_start_at"] is None
    assert segment["legacy_job_end_at"] is None
    assert fx.read_request(api, request["id"])["page_count_total"] == 0


def test_a_freshly_priced_invoice_starts_in_draft(api):
    """The money machine's origin state, before any issuance.

    PRD: "An invoice's `status` starts at `DRAFT` and takes `DRAFT`, `ISSUED`, `PAID`, `WAIVED` or `VOIDED`, with `PAID` and `VOIDED` terminal."

    Design: Corner/state_machines/newly_created_entities_start_in_declared_initial_states
    """
    world = fx.third_party_world(api)
    scenario = fx.simple_third_party_request_at_release_ready(api, world, 25)

    invoice = fx.create_invoice(api, scenario["request_id"])

    assert invoice["status"] == "DRAFT"
    assert invoice["paid_cents"] == 0
    assert invoice["issued_at"] is None
    assert invoice["settled_at"] is None
    assert invoice["void_reason"] is None
    assert invoice["waiver_reason"] is None
    assert invoice["version"] == 1


def test_compilation_completion_from_intake_review_reports_the_state_rule(api):
    """Position 10 fires ahead of the segment-population rule even though both are violated.

    PRD: "Any transition attempted from outside its declared origin set is refused with `ERR_REQUEST_STATE_INVALID`."

    Design: Corner/state_machines/complete_compilation_from_intake_review_rejected
    """
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    version_before = request["version"]

    validate_error(
        api.complete_compilation(request["id"], {}, ANALYST_1), e.ERR_REQUEST_STATE_INVALID, 409
    )
    validate_error(
        api.sensitive_review(request["id"], f.sensitive_review_payload([]), REVIEWER_1),
        e.ERR_REQUEST_STATE_INVALID,
        409,
    )

    after = fx.read_request(api, request["id"])
    assert after["fulfillment_status"] == "INTAKE_REVIEW"
    assert after["version"] == version_before


def test_a_second_identical_accept_is_refused_and_recomputes_no_deadline(api):
    """ACCEPT is not idempotent: COMPILATION is not one of its origins.

    PRD: "A `decision` of `ACCEPT` moves the request from `INTAKE_REVIEW` to `COMPILATION`; it requires that the governing facility's `status` be `ACTIVE`, and, when the `access_basis` is `THIRD_PARTY_AUTHORIZATION`, that the governing authorization's `status` be `VALID` and its `expires_at` be strictly after the current logical clock; when the `access_basis` is `PATIENT_RIGHT_OF_ACCESS` the `authorization_id` must be null."

    Design: Corner/state_machines/second_intake_accept_on_same_request_rejected
    """
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)

    first = validate_success(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1), 200
    )
    assert first["fulfillment_status"] == "COMPILATION"
    assert first["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    assert first["version"] == 2

    validate_error(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1),
        e.ERR_REQUEST_STATE_INVALID,
        409,
    )

    after = fx.read_request(api, request["id"])
    assert after["version"] == 2
    assert after["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")


def test_the_same_legal_origin_violates_the_population_precondition_twice(api):
    """Zero segments and one PENDING segment both fail from COMPILATION; UNAVAILABLE unblocks.

    PRD: "It moves the request from `COMPILATION` to `SENSITIVE_REVIEW`, and it requires that the request have at least one record segment and that no segment of the request still hold `retrieval_status` `PENDING`; a request with no segments at all, or with any segment still `PENDING`, is refused with `ERR_SEGMENTS_PENDING`."

    Design: Corner/state_machines/complete_compilation_precondition_requires_at_least_one_non_pending_segment
    """
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])

    validate_error(
        api.complete_compilation(request["id"], {}, ANALYST_1), e.ERR_SEGMENTS_PENDING, 409
    )

    segment = fx.open_segment(api, request["id"])
    validate_error(
        api.complete_compilation(request["id"], {}, ANALYST_1), e.ERR_SEGMENTS_PENDING, 409
    )

    get_success_data(
        api.segment_disposition(segment["id"], f.unavailable_payload("chart destroyed"), ANALYST_1)
    )
    unavailable = fx.read_segment(api, segment["id"])
    assert unavailable["retrieval_status"] == "UNAVAILABLE"
    assert unavailable["page_count"] == 0

    moved = validate_success(api.complete_compilation(request["id"], {}, ANALYST_1), 200)
    assert moved["fulfillment_status"] == "SENSITIVE_REVIEW"
    assert fx.read_request(api, request["id"])["page_count_total"] == 0


def _withdrawn_twelve_page_segment(api):
    """One retrieved 12-page segment withdrawn again while the request sits in COMPILATION."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])
    segment_id = fx.add_retrieved_segment(api, request["id"], 12)
    get_success_data(api.segment_disposition(segment_id, f.withdrawn_payload(), ANALYST_1))
    return {"request_id": request["id"], "segment_id": segment_id}


def test_a_withdrawn_segment_cannot_be_retrieved_a_second_time(api):
    """RETRIEVED demands PENDING, and a withdrawn segment will never be PENDING again.

    PRD: "A disposition attempted on a segment that is no longer `PENDING` where `PENDING` is required is refused with `ERR_SEGMENT_STATE_INVALID`."

    Design: Corner/state_machines/withdrawn_segment_cannot_be_dispositioned_again
    """
    scenario = _withdrawn_twelve_page_segment(api)
    before = fx.read_segment(api, scenario["segment_id"])

    validate_error(
        api.segment_disposition(scenario["segment_id"], f.retrieved_payload(12), ANALYST_1),
        e.ERR_SEGMENT_STATE_INVALID,
        409,
    )

    after = fx.read_segment(api, scenario["segment_id"])
    assert after["retrieval_status"] == "WITHDRAWN"
    assert after["page_count"] == 12
    assert after["version"] == before["version"]


def test_no_disposition_leaves_a_terminal_retrieval_status_not_even_to_the_other_one(api):
    """A second WITHDRAWN and an UNAVAILABLE are both refused from WITHDRAWN.

    PRD: "`UNAVAILABLE` and `WITHDRAWN` are both terminal for the retrieval dimension."

    Design: Corner/state_machines/withdrawn_segment_cannot_be_dispositioned_again
    """
    scenario = _withdrawn_twelve_page_segment(api)
    before = fx.read_segment(api, scenario["segment_id"])

    validate_error(
        api.segment_disposition(scenario["segment_id"], f.withdrawn_payload(), ANALYST_1),
        e.ERR_SEGMENT_STATE_INVALID,
        409,
    )
    validate_error(
        api.segment_disposition(
            scenario["segment_id"], f.unavailable_payload("chart destroyed"), ANALYST_1
        ),
        e.ERR_SEGMENT_STATE_INVALID,
        409,
    )

    after = fx.read_segment(api, scenario["segment_id"])
    assert after["retrieval_status"] == "WITHDRAWN"
    assert after["version"] == before["version"]
    request = fx.read_request(api, scenario["request_id"])
    assert request["page_count_total"] == 0
    assert request["billable_page_count"] == 0


def test_a_revoked_authorization_can_be_neither_revoked_again_nor_cured(api):
    """REVOKED is terminal, and cure demands DEFECTIVE.

    PRD: "**Revocation** is shared by `PrivacyOfficer` and the `Requester` named on the authorization, takes a `revocation_reason`, and is permitted only from `VALID` or `DEFECTIVE` — from `REVOKED`, `EXPIRED` or `SUPERSEDED` it is refused with `ERR_AUTHORIZATION_STATE_INVALID`."

    Design: Corner/state_machines/authorization_revoke_from_revoked_rejected
    """
    world = fx.third_party_world(api)
    authorization_id = world["authorization_id"]
    get_success_data(api.revoke_authorization(authorization_id, f.revoke_payload(), PRIVACY_1))
    before = get_success_data(api.get_authorization(authorization_id, INTAKE_1))
    assert before["status"] == "REVOKED"

    validate_error(
        api.revoke_authorization(authorization_id, f.revoke_payload(), PRIVACY_1),
        e.ERR_AUTHORIZATION_STATE_INVALID,
        409,
    )
    validate_error(
        api.cure_authorization(authorization_id, f.authorization_cure_payload(), INTAKE_1),
        e.ERR_AUTHORIZATION_STATE_INVALID,
        409,
    )

    after = get_success_data(api.get_authorization(authorization_id, INTAKE_1))
    assert after["status"] == "REVOKED"
    assert after["version"] == before["version"]


def test_the_accept_transition_stamps_every_declared_side_effect_at_once(api):
    """An authorization signed after arrival pushes the anchor, and the accept re-derives it.

    PRD: "Step two selects the anchor, and it does so *before* any days are added: for a `PATIENT_RIGHT_OF_ACCESS` request the anchor is simply the request's `received_at`, because such a request has no authorization; for a `THIRD_PARTY_AUTHORIZATION` request the anchor is the later of the request's `received_at` and the governing authorization's `signed_at`, so an authorization signed after the request arrived pushes the anchor forward."

    Design: Corner/state_machines/intake_accept_side_effects_stamp_anchor_and_deadline
    """
    world = fx.third_party_world(api, signed_at="2026-08-07T12:00:00Z")
    request = fx.open_third_party_request(api, world)
    assert request["received_at"] == Instant("2026-08-01T00:00:00Z")

    accepted = validate_success(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1), 200
    )

    assert accepted["fulfillment_status"] == "COMPILATION"
    assert accepted["received_at"] == Instant("2026-08-01T00:00:00Z")
    assert accepted["statutory_due_at"] == Instant("2026-09-06T12:00:00Z")
    assert accepted["statutory_due_at"] != Instant("2026-08-31T00:00:00Z")
    assert accepted["tolled_seconds"] == 0
    assert accepted["extension_applied"] is False
    assert accepted["penalty_exposure_cents"] == 0
    assert accepted["safe_harbor_penalty_cents"] == 0
    assert accepted["version"] == 2
    assert accepted["billing_status"] == "PENDING_INVOICE"
