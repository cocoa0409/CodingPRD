"""Consistency corners: an accepted write is complete for the very next reader, and every
aggregate that lives on another entity settles inside the write that moves it.

Two design details are adjusted to the PRD.  The first instance expects `statutory_due_at`
to be null before the accept, but §3.4 has intake creation compute it, so the pre-accept
read is pinned to the value the creation returned; and it names a `statutory_anchor_at`
field the PRD does not declare, so the anchor is read as `received_at`.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import Instant, assert_line, assert_page_ledger, assert_facility_money
from test_helpers.test_users import ANALYST_1, BILLING_1, INTAKE_1, PLATFORM_ADMIN, PRIVACY_1


# --------------------------------------------------------------------------
# accepted_write_is_fully_visible_to_the_very_next_read
# --------------------------------------------------------------------------
def _request_awaiting_the_intake_decision(api):
    """One third-party request sitting in INTAKE_REVIEW, deadline already computed."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    return world, request


def test_the_accept_response_and_the_next_readers_view_are_the_same_instant(api):
    """A different user in a different role sees the accept without any settling step.

    PRD: "Acceptance re-derives `statutory_due_at`, re-derives both `penalty_exposure_cents` and `safe_harbor_penalty_cents`, and increments the request's `version` by 1."

    Design: Corner/consistency model/accepted_write_is_fully_visible_to_the_very_next_read
    """
    _, request = _request_awaiting_the_intake_decision(api)
    assert request["fulfillment_status"] == "INTAKE_REVIEW"
    assert request["received_at"] == Instant("2026-08-01T00:00:00Z")
    assert request["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")

    accepted = validate_success(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1), 200
    )

    assert accepted["fulfillment_status"] == "COMPILATION"
    assert accepted["received_at"] == Instant("2026-08-01T00:00:00Z")
    assert accepted["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    next_reader = validate_success(api.get_request(request["id"], BILLING_1), 200)
    assert next_reader["fulfillment_status"] == accepted["fulfillment_status"]
    assert next_reader["statutory_due_at"] == accepted["statutory_due_at"]
    assert next_reader["version"] == accepted["version"]
    assert next_reader["updated_at"] == accepted["updated_at"]


def test_the_computed_read_agrees_with_the_stored_request_at_once(api):
    """The derived deadline is on the first computed read, not on the one after a sweep.

    PRD: "A non-persisting computed read exposes the whole calculation for one request: it returns `statutory_due_at`, `effective_completion_at`, `tolled_seconds`, `extension_applied`, a `breached` boolean that is true exactly when the effective completion instant is strictly later than `statutory_due_at`, `days_late_strict`, `days_late_business`, `chargeable_days`, `penalty_exposure_cents` and `safe_harbor_penalty_cents`."

    Design: Corner/consistency model/accepted_write_is_fully_visible_to_the_very_next_read
    """
    _, request = _request_awaiting_the_intake_decision(api)
    before = validate_success(api.get_turnaround(request["id"], PRIVACY_1), 200)
    assert before["statutory_due_at"] == Instant("2026-08-31T00:00:00Z")
    assert before["breached"] is False
    assert before["penalty_exposure_cents"] == 0

    accepted = validate_success(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1), 200
    )
    after = validate_success(api.get_turnaround(request["id"], PRIVACY_1), 200)

    assert after["statutory_due_at"] == accepted["statutory_due_at"]
    assert after["tolled_seconds"] == 0
    assert after["extension_applied"] is False
    assert after["breached"] is False
    assert after["days_late_strict"] == 0
    assert after["days_late_business"] == 0
    assert after["chargeable_days"] == 0
    assert after["penalty_exposure_cents"] == 0
    assert after["safe_harbor_penalty_cents"] == 0


def test_the_new_bucket_and_the_empty_event_log_are_current_at_the_same_instant(api):
    """A just-moved request is never missing from the status bucket it just entered.

    PRD: "Requests are readable individually and listable with optional `facility_id`, `patient_id`, `requester_id`, `authorization_id`, `predecessor_request_id`, `fulfillment_status` and `billing_status` filters."

    Design: Corner/consistency model/accepted_write_is_fully_visible_to_the_very_next_read
    """
    world, request = _request_awaiting_the_intake_decision(api)
    validate_success(
        api.intake_decision(request["id"], f.intake_decision_payload("ACCEPT"), INTAKE_1), 200
    )

    rows, meta = validate_paginated(
        api.list_requests(
            INTAKE_1,
            {
                "facility_id": world["facility_id"],
                "fulfillment_status": "COMPILATION",
                "limit": 10,
            },
        )
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [request["id"]]

    _, intake_review = validate_paginated(
        api.list_requests(
            INTAKE_1,
            {
                "facility_id": world["facility_id"],
                "fulfillment_status": "INTAKE_REVIEW",
                "limit": 10,
            },
        )
    )
    assert intake_review["total_count"] == 0
    _, events = fx.list_events_of(api, request["id"])
    assert events["total_count"] == 0


# --------------------------------------------------------------------------
# derived_aggregates_settle_inside_the_write_that_moves_them
# --------------------------------------------------------------------------
def _request_with_one_pending_forty_page_segment(api):
    """An accepted request whose single segment is opened but not yet dispositioned."""
    world = fx.third_party_world(api)
    request = fx.open_third_party_request(api, world)
    fx.accept_request(api, request["id"])
    segment = fx.open_segment(api, request["id"])
    return world, request["id"], segment["id"]


def test_the_child_write_leaves_the_parents_ledger_correct_for_the_next_reader(api):
    """The disposition returns a segment, yet the parent's ledger is already re-derived.

    PRD: "Four fields on the request summarise the compiled set, all defaulting to 0, all re-derived on every segment write and on every `fulfillment_status` transition, and all computed over the same input population: the segments of this request whose `retrieval_status` is `RETRIEVED`."

    Design: Corner/consistency model/derived_aggregates_settle_inside_the_write_that_moves_them
    """
    _, request_id, segment_id = _request_with_one_pending_forty_page_segment(api)
    assert_page_ledger(fx.read_request(api, request_id), total=0, billable=0, withheld=0, redacted=0)

    dispositioned = validate_success(
        api.segment_disposition(segment_id, f.retrieved_payload(40), ANALYST_1), 200
    )

    assert dispositioned["page_count"] == 40
    assert dispositioned["retrieval_status"] == "RETRIEVED"
    assert_page_ledger(
        fx.read_request(api, request_id), total=40, billable=40, withheld=0, redacted=0
    )


def test_a_draft_invoice_is_priced_exactly_and_still_outside_the_money_ledger(api):
    """Immediate does not mean eager: a DRAFT is priced to the cent but posts nothing.

    PRD: "`receivable_cents` is the sum, over those invoices whose `status` is `ISSUED`, of the invoice's `amount_due_cents` minus its `paid_cents`."

    Design: Corner/consistency model/derived_aggregates_settle_inside_the_write_that_moves_them
    """
    world, request_id, segment_id = _request_with_one_pending_forty_page_segment(api)
    fx.retrieve_segment(api, segment_id, 40)
    fx.complete_compilation(api, request_id)
    fx.run_sensitive_review(api, request_id, [])

    invoice = fx.create_invoice(api, request_id)

    assert invoice["status"] == "DRAFT"
    assert invoice["subtotal_cents"] == 2376
    assert invoice["cap_adjustment_cents"] == 0
    assert invoice["amount_due_cents"] == 2376
    assert_facility_money(
        fx.read_facility(api, world["facility_id"]), receivable=0, collected=0, written_off=0
    )

    lines, meta = fx.list_lines_of(api, invoice["id"])
    assert meta["total_count"] == 3
    assert_line(lines[0], "BASE_RETRIEVAL", 1, 1500000, 1500)
    assert_line(lines[1], "PER_PAGE_TIER1", 25, 27500, 688)
    assert_line(lines[2], "PER_PAGE_TIER2", 15, 12500, 188)
    assert [line["sequence"] for line in lines] == [1, 2, 3]
    assert sum(line["amount_cents"] for line in lines) == 2376


def test_the_issue_moves_the_receivable_and_the_sweep_moves_nothing(api):
    """One call earlier the ledger was 0, with nothing in between; the sweep changes none of it.

    PRD: "The response reports `swept_request_count`, the number of requests examined; `breached_request_ids`, the identifiers of requests whose deadline is breached; `penalized_request_ids`, the identifiers of requests whose statutory penalty moved; `total_penalty_delta_cents`, the summed increase across the sweep; and `expired_authorization_ids`, the identifiers of the authorizations that lapsed."

    Design: Corner/consistency model/derived_aggregates_settle_inside_the_write_that_moves_them
    """
    world, request_id, segment_id = _request_with_one_pending_forty_page_segment(api)
    fx.retrieve_segment(api, segment_id, 40)
    fx.complete_compilation(api, request_id)
    fx.run_sensitive_review(api, request_id, [])
    invoice = fx.create_invoice(api, request_id)
    assert fx.read_facility(api, world["facility_id"])["receivable_cents"] == 0

    fx.issue_invoice(api, invoice["id"])

    before_sweep = fx.read_facility(api, world["facility_id"])
    assert_facility_money(before_sweep, receivable=2376, collected=0, written_off=0)
    assert fx.read_request(api, request_id)["billing_status"] == "INVOICED"

    sweep = validate_success(api.run_compliance_sweep({}, PLATFORM_ADMIN), 200)

    assert sweep["swept_request_count"] >= 1
    assert sweep["total_penalty_delta_cents"] == 0
    assert sweep["breached_request_ids"] == []
    assert sweep["penalized_request_ids"] == []
    after_sweep = fx.read_facility(api, world["facility_id"])
    assert_facility_money(after_sweep, receivable=2376, collected=0, written_off=0)
    assert after_sweep["penalty_exposure_cents"] == 0
    assert after_sweep["receivable_cents"] == before_sweep["receivable_cents"]
