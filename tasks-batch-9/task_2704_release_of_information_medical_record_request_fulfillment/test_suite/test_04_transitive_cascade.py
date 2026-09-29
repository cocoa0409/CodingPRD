"""Multi-hop cascades driven from a single call on a distant entity."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_event_count, assert_facility_money, event_types
from test_helpers.test_users import PRIVACY_1, PRIVACY_2


# --------------------------------------------------------------------------
# authorization_revoke_cascades_through_segments_invoice_and_facility_ledger
# --------------------------------------------------------------------------
def _issued_invoice_on_an_included_sensitive_segment(api):
    """40 general-medical + 22 behavioural-health pages included without redaction, so
    the request is RELEASE_READY at 62 billable pages with a 4501-cent ISSUED invoice."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api,
        world,
        requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH"],
        delivery_format="PAPER_MAIL",
        certification_requested=True,
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
        ],
    )
    fx.run_sensitive_review(api, request["id"], [f.include_decision(ids["bh"], redaction_required=False)])
    invoice = fx.create_invoice(api, request["id"])
    fx.issue_invoice(api, invoice["id"])
    return {"world": world, "request_id": request["id"], "segment_ids": ids, "invoice_id": invoice["id"]}


def _revoke(api, authorization_id):
    return get_success_data(api.revoke_authorization(authorization_id, f.revoke_payload(), PRIVACY_1))


def test_revoking_the_authorization_pushes_the_request_back_and_reopens_its_segments(api):
    """Hops one to four: authorization, request state, segment sensitivity, page ledger.

    PRD: "Revocation is the widest cascade in the system. It sets `revoked_at` to the current logical clock, increments the authorization's `version` by 1, and then, for every request on that authorization whose `fulfillment_status` is not one of `RELEASED`, `DENIED`, `CLOSED` or `CANCELLED`, drives that request from `INTAKE_REVIEW`, `COMPILATION`, `SENSITIVE_REVIEW`, `REDACTION` or `RELEASE_READY` to `AUTH_DEFECT_PENDING` with the full effect list: `defect_opened_at` is set to the current logical clock, opening a tolling interval; `release_reviewer_user_id` is cleared; every record segment of that request whose `sensitivity_status` is `AUTHORIZED_INCLUDE` or `WITHHELD` reverts to `SEGREGATED_PENDING_REVIEW`, and every segment whose `redaction_status` is `OPEN`, `APPLIED`, `APPROVED` or `REWORK` is reset to `OPEN` with `redaction_approved_by_user_id` cleared; the request's four page-ledger fields are re-derived; every invoice of that request whose `status` is `DRAFT` or `ISSUED` is driven to `VOIDED` with `void_reason` set to `AUTHORIZATION_REVOKED` and the request's `billing_status` is returned to `PENDING_INVOICE`; the facility's `receivable_cents` is re-derived; a compliance event of type `AUTHORIZATION_REVOKED` is appended against the request; and the request's `version` increments by 1."

    Design: Difficulty/transitive_cascade/authorization_revoke_cascades_through_segments_invoice_and_facility_ledger
    """
    scenario = _issued_invoice_on_an_included_sensitive_segment(api)
    before = fx.read_request(api, scenario["request_id"])
    assert before["billing_status"] == "INVOICED"
    assert before["billable_page_count"] == 62

    authorization = _revoke(api, scenario["world"]["authorization_id"])
    assert authorization["status"] == "REVOKED"

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "AUTH_DEFECT_PENDING"
    assert request["defect_opened_at"] == Instant("2026-08-01T00:00:00Z")
    assert request["release_reviewer_user_id"] is None
    assert request["billable_page_count"] == 40
    assert request["page_count_total"] == 62

    assert fx.read_segment(api, scenario["segment_ids"]["bh"])["sensitivity_status"] == "SEGREGATED_PENDING_REVIEW"
    assert fx.read_segment(api, scenario["segment_ids"]["gen"])["sensitivity_status"] == "NOT_SENSITIVE"


def test_the_cascade_voids_the_issued_invoice_without_any_call_touching_it(api):
    """Hop five: the invoice nobody named is voided with the revocation reason.

    PRD: "`VOID` is permitted from `DRAFT`, `ISSUED` or `WAIVED`, records the supplied `reason` as `void_reason` — the reason vocabulary being `SUPERSEDED_BY_REPRICE`, `AUTHORIZATION_REVOKED` and `BILLING_CLERK_VOID` — sets `settled_at`, moves the invoice to `VOIDED`, returns the request's `billing_status` to `PENDING_INVOICE` from `INVOICED` or from `WAIVED`, and reverses whichever ledger postings that invoice had made, so that the facility's `receivable_cents`, `collected_cents` and `written_off_cents` return together to their pre-issue values."

    Design: Difficulty/transitive_cascade/authorization_revoke_cascades_through_segments_invoice_and_facility_ledger
    """
    scenario = _issued_invoice_on_an_included_sensitive_segment(api)
    assert fx.read_invoice(api, scenario["invoice_id"])["status"] == "ISSUED"

    _revoke(api, scenario["world"]["authorization_id"])

    invoice = fx.read_invoice(api, scenario["invoice_id"])
    assert invoice["status"] == "VOIDED"
    assert invoice["void_reason"] == "AUTHORIZATION_REVOKED"
    assert invoice["settled_at"] == Instant("2026-08-01T00:00:00Z")
    assert fx.read_request(api, scenario["request_id"])["billing_status"] == "PENDING_INVOICE"


def test_the_cascade_reaches_the_facility_receivable_and_leaves_one_event(api):
    """Hop six: the voided invoice contributes to no ledger bucket.

    PRD: "Invoices in `DRAFT` or `VOIDED` contribute to no bucket."

    Design: Difficulty/transitive_cascade/authorization_revoke_cascades_through_segments_invoice_and_facility_ledger
    """
    scenario = _issued_invoice_on_an_included_sensitive_segment(api)
    facility_id = scenario["world"]["facility_id"]
    assert_facility_money(fx.read_facility(api, facility_id), 4501, 0, 0)

    _revoke(api, scenario["world"]["authorization_id"])

    assert_facility_money(fx.read_facility(api, facility_id), 0, 0, 0)
    assert_event_count(fx.read_events(api, scenario["request_id"]), "AUTHORIZATION_REVOKED", 1)


# --------------------------------------------------------------------------
# denial_overturn_cascades_to_reopen_ledger_and_penalty
# --------------------------------------------------------------------------
def _denial_under_review_five_days_past_the_deadline(api):
    """80 retrieved pages with HIV withheld, denied on reviewable harm grounds, with the
    clock moved to 2026-09-05T00:00:00Z and a second officer's review started."""
    world = fx.third_party_world(
        api,
        scope_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"],
        sensitive_categories_authorized=["BEHAVIORAL_HEALTH"],
    )
    request = fx.open_third_party_request(
        api, world, requested_categories=["GENERAL_MEDICAL", "BEHAVIORAL_HEALTH", "HIV"]
    )
    ids = fx.walk_to_sensitive_review(
        api,
        request["id"],
        [
            {"label": "gen", "category": "GENERAL_MEDICAL", "page_count": 40},
            {"label": "bh", "category": "BEHAVIORAL_HEALTH", "page_count": 22},
            {"label": "hiv", "category": "HIV", "page_count": 18, "source_system": "SCANNED_PAPER"},
        ],
    )
    fx.run_sensitive_review(
        api,
        request["id"],
        [f.include_decision(ids["bh"], redaction_required=True), f.withhold_decision(ids["hiv"])],
    )
    denial = get_success_data(
        api.create_denial(
            f.denial_payload(request["id"], "HARM_REVIEW_LICENSED_PROFESSIONAL"), PRIVACY_1
        )
    )
    fx.set_clock(api, "2026-09-05T00:00:00Z")
    get_success_data(api.review_denial(denial["id"], f.denial_review_payload("START_REVIEW"), PRIVACY_2))
    return {
        "world": world,
        "request_id": request["id"],
        "segment_ids": ids,
        "denial_id": denial["id"],
    }


def _overturn(api, denial_id):
    return get_success_data(api.review_denial(denial_id, f.denial_review_payload("OVERTURN"), PRIVACY_2))


def test_overturning_a_denial_reopens_the_request_and_its_withheld_segments(api):
    """Hops one to four: decision, request state, segment sensitivity, page ledger.

    PRD: "`OVERTURN` moves the decision from `UNDER_REVIEW` to `OVERTURNED`, sets `decided_at` to the current logical clock, increments the decision's `version` by 1, and cascades the parent request from `DENIED` all the way back to `COMPILATION` with its full effect list: every record segment of the request whose `sensitivity_status` is `WITHHELD` reverts to `SEGREGATED_PENDING_REVIEW` — and any of those segments holding `redaction_status` `APPLIED`, `APPROVED` or `REWORK` is reset to `OPEN` with `redaction_approved_by_user_id` cleared — so the reviewer must decide the same segments again; the four page-ledger fields are re-derived; both penalty measures are re-derived at the current logical clock; the facility's `penalty_exposure_cents` is re-derived; a `DENIAL_OVERTURNED` compliance event is appended, together with a `PENALTY_ACCRUED` event when the penalty figure actually changed; and the request's `version` increments by 1."

    Design: Difficulty/transitive_cascade/denial_overturn_cascades_to_reopen_ledger_and_penalty
    """
    scenario = _denial_under_review_five_days_past_the_deadline(api)
    before = fx.read_request(api, scenario["request_id"])
    assert before["fulfillment_status"] == "DENIED"

    denial = get_success_data(api.get_denial(scenario["denial_id"], PRIVACY_1))
    assert denial["status"] == "UNDER_REVIEW"
    assert denial["reviewable"] is True
    assert denial["reviewer_user_id"] == "u-privacy-2"
    assert denial["review_due_at"] == Instant("2026-08-31T00:00:00Z")

    overturned = _overturn(api, scenario["denial_id"])
    assert overturned["status"] == "OVERTURNED"
    assert overturned["decided_at"] == Instant("2026-09-05T00:00:00Z")

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "COMPILATION"
    assert request["withheld_page_count"] == 0
    assert request["page_count_total"] == 80
    assert fx.read_segment(api, scenario["segment_ids"]["hiv"])["sensitivity_status"] == "SEGREGATED_PENDING_REVIEW"


def test_the_clock_kept_running_while_the_request_sat_denied(api):
    """Hop five: the overturn re-derives both measures at the current clock.

    PRD: "Crucially, a denial does **not** stop the statutory clock: `penalty_exposure_cents` keeps accruing against the moving logical clock while the request sits in `DENIED`."

    Design: Difficulty/transitive_cascade/denial_overturn_cascades_to_reopen_ledger_and_penalty
    """
    scenario = _denial_under_review_five_days_past_the_deadline(api)
    _overturn(api, scenario["denial_id"])

    request = fx.read_request(api, scenario["request_id"])
    assert request["penalty_exposure_cents"] == 12500
    assert request["safe_harbor_penalty_cents"] == 5000


def test_the_reopened_penalty_reaches_the_facility_and_the_event_trail(api):
    """Hop six: the facility aggregate and the four evidentiary events.

    PRD: "Any movement in a request's statutory measure re-derives the facility's `penalty_exposure_cents`."

    Design: Difficulty/transitive_cascade/denial_overturn_cascades_to_reopen_ledger_and_penalty
    """
    scenario = _denial_under_review_five_days_past_the_deadline(api)
    _overturn(api, scenario["denial_id"])

    facility = fx.read_facility(api, scenario["world"]["facility_id"])
    assert facility["penalty_exposure_cents"] == 12500

    kinds = event_types(fx.read_events(api, scenario["request_id"]))
    for expected in ("DENIAL_ISSUED", "DENIAL_OVERTURNED", "STATUTORY_DEADLINE_BREACHED", "PENALTY_ACCRUED"):
        assert expected in kinds, f"missing {expected} in {kinds}"


# --------------------------------------------------------------------------
# amendment_accept_cascades_notice_onto_released_request
# --------------------------------------------------------------------------
def _amendment_under_review_on_a_released_segment(api):
    """A released 62-page paper request, then an amendment filed at 2026-08-10T00:00:00Z
    against its disclosed segment and taken under review."""
    world = fx.third_party_world(api)
    scenario = fx.released_third_party_request(
        api, world, 62, delivery_format="PAPER_MAIL", certification_requested=True
    )
    fx.set_clock(api, "2026-08-10T00:00:00Z")
    amendment = get_success_data(
        api.create_amendment_request(
            f.amendment_payload(
                scenario["request_id"], world["patient_id"], scenario["segment_ids"]["gen"]
            ),
            world["requester_headers"],
        )
    )
    get_success_data(
        api.amendment_decision(amendment["id"], f.amendment_decision_payload("START_REVIEW"), PRIVACY_1)
    )
    return {
        "world": world,
        "request_id": scenario["request_id"],
        "segment_id": scenario["segment_ids"]["gen"],
        "invoice_id": scenario["invoice_id"],
        "amendment_id": amendment["id"],
    }


def _accept_amendment(api, amendment_id):
    return get_success_data(
        api.amendment_decision(amendment_id, f.amendment_decision_payload("ACCEPT"), PRIVACY_1)
    )


def test_accepting_an_amendment_flags_the_segment_and_notices_the_request(api):
    """Hops one to three: the decision, the segment flag, the notice on the request.

    PRD: "`ACCEPT` moves it from `UNDER_REVIEW` to `ACCEPTED`, requires that the target segment's `retrieval_status` still be `RETRIEVED`, sets `decided_at` to the current logical clock, sets the target segment's `amended` flag to true, sets the parent request's `amendment_notice_required` to true when and only when that request's `released_at` is not null, and appends an `AMENDMENT_NOTICE_REQUIRED` compliance event."

    Design: Difficulty/transitive_cascade/amendment_accept_cascades_notice_onto_released_request
    """
    scenario = _amendment_under_review_on_a_released_segment(api)

    accepted = _accept_amendment(api, scenario["amendment_id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["decided_at"] == Instant("2026-08-10T00:00:00Z")

    assert fx.read_segment(api, scenario["segment_id"])["amended"] is True
    assert fx.read_request(api, scenario["request_id"])["amendment_notice_required"] is True
    assert_event_count(fx.read_events(api, scenario["request_id"]), "AMENDMENT_NOTICE_REQUIRED", 1)


def test_the_amendment_window_and_submission_count_are_stamped_at_creation(api):
    """Sixty whole days from creation, and a first submission counted as one.

    PRD: "On creation `status` starts at `SUBMITTED`, `submission_count` starts at 1, `additional_information`, `rationale` and `decided_at` start null, and `decision_due_at` is derived by adding an amendment window of sixty whole days to the record's `created_at`."

    Design: Difficulty/transitive_cascade/amendment_accept_cascades_notice_onto_released_request
    """
    scenario = _amendment_under_review_on_a_released_segment(api)
    amendment = get_success_data(api.get_amendment_request(scenario["amendment_id"], PRIVACY_1))

    assert amendment["decision_due_at"] == Instant("2026-10-09T00:00:00Z")
    assert amendment["submission_count"] == 1


def test_the_cascade_does_not_disturb_the_released_workflow_or_the_money(api):
    """The request stays RELEASED with its original release instant, ledger and invoice.

    PRD: "A successful release sets `released_at` to the current logical clock and `release_reviewer_user_id` to the acting `X-User-ID`, then freezes both `penalty_exposure_cents` and `safe_harbor_penalty_cents` by evaluating them with the completion instant taken as `released_at` rather than as the moving clock."

    Design: Difficulty/transitive_cascade/amendment_accept_cascades_notice_onto_released_request
    """
    scenario = _amendment_under_review_on_a_released_segment(api)
    _accept_amendment(api, scenario["amendment_id"])

    request = fx.read_request(api, scenario["request_id"])
    assert request["fulfillment_status"] == "RELEASED"
    assert request["released_at"] == Instant("2026-08-01T00:00:00Z")
    assert request["billable_page_count"] == 62
    assert fx.read_invoice(api, scenario["invoice_id"])["status"] == "PAID"
