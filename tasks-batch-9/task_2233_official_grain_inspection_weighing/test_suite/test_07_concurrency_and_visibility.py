"""Optimistic concurrency on the two version echoes, and the immediacy of every
derived figure a write produces."""

from test_helpers import (
    ADMIN,
    CORN_NO_2_FACTORS,
    INSPECTOR,
    SUPERVISOR,
    ApiErrorId,
    api_client,
    appeal_payload,
    appeal_vote_payload,
    assert_ledger,
    certificate_payload,
    dismiss,
    make_applicant_headers,
    payment_payload,
    read_appeal,
    read_applicant,
    read_area,
    read_certificate,
    read_request,
    setup_appeal_under_review,
    setup_filed_appeal,
    setup_graded_request,
    setup_office,
    validate_error,
    validate_paginated,
    validate_success,
    vessel_watch_payload,
)


GRADING_SCHEDULE = {
    "service_class": "GRADING",
    "base_fee_cents": 8000,
    "per_thousand_bushel_rate_cents": 2000,
}

APPEAL_SCHEDULE = {"service_class": "APPEAL", "base_fee_cents": 20000}


def test_a_certificate_written_twice_behind_the_client_refuses_the_stale_filing():
    """Filing an appeal requires `expected_certificate_version` in the body — a
    non-optional integer carrying the `version` of the challenged certificate as
    the client last read it. If it does not equal the certificate's current
    `version`, the filing is refused with `ERR_CERTIFICATE_VERSION_CONFLICT`
    (HTTP 412), the certificate is not moved to `UNDER_APPEAL`, and no deposit is
    charged.

    All resources except appeal votes additionally carry `updated_at` — the same
    format, refreshed on every mutation of the row — and `version`, an integer
    that begins at 1 and increments by exactly one on every mutation.

    Dismissal is the administrator's early exit and is available from either
    `FILED` or `SAMPLE_ASSIGNED`, with an optional `reason`. In both cases
    `refund_cents` is half of `deposit_cents` truncated downward, credited to the
    applicant, and the challenged certificate returns to `ISSUED`; where the
    appeal had already reached `SAMPLE_ASSIGNED`, the retained portion is
    additionally released with `portions_retained` decreasing by one.

    Design: Corner/cross_cutting_complexity_layers/stale_certificate_version_is_refused_when_filing_an_appeal
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE),
    )
    applicant_id = office["applicant"]["id"]
    staged = setup_filed_appeal(
        office,
        declared_quantity_bushels=900,
        portions_count=4,
        lot_identifier="LOT-CV1",
        seal_number="SEAL-CV1",
    )
    certificate_id = staged["certificate"]["id"]
    stale_version = staged["certificate"]["version"]
    assert staged["certificate"]["fee_total_cents"] == 10000
    assert staged["appeal"]["deposit_cents"] == 20000
    assert read_certificate(certificate_id)["status"] == "UNDER_APPEAL"
    assert read_request(staged["request"]["id"])["grading_status"] == "UNDER_APPEAL"

    dismissed = dismiss(staged["appeal"]["id"])
    assert dismissed["status"] == "DISMISSED"
    assert dismissed["refund_cents"] == 10000

    returned = read_certificate(certificate_id)
    assert returned["status"] == "ISSUED"
    assert returned["version"] == stale_version + 2
    assert read_request(staged["request"]["id"])["grading_status"] == "GRADE_CERTIFIED"
    assert_ledger(
        read_applicant(applicant_id), charges=30000, credits=10000, open_balance=20000
    )

    refused = api_client.create_appeal(
        appeal_payload(certificate_id, applicant_id, stale_version, "APPEAL"), ADMIN
    )
    validate_error(refused, ApiErrorId.ERR_CERTIFICATE_VERSION_CONFLICT.value, 412)

    untouched = read_certificate(certificate_id)
    assert untouched["status"] == "ISSUED"
    assert untouched["version"] == returned["version"]
    assert_ledger(
        read_applicant(applicant_id), charges=30000, credits=10000, open_balance=20000
    )

    filed_rows, filed_meta = validate_paginated(
        api_client.list_certificate_appeals(certificate_id, ADMIN)
    )
    assert filed_meta["total_count"] == 1
    assert filed_rows[0]["id"] == staged["appeal"]["id"]
    assert filed_rows[0]["status"] == "DISMISSED"

    accepted = validate_success(
        api_client.create_appeal(
            appeal_payload(
                certificate_id, applicant_id, untouched["version"], "APPEAL"
            ),
            ADMIN,
        ),
        201,
    )
    assert accepted["status"] == "FILED"
    assert accepted["deposit_cents"] == 20000
    assert accepted["refund_cents"] == 0

    refiled = read_certificate(certificate_id)
    assert refiled["status"] == "UNDER_APPEAL"
    assert refiled["version"] == untouched["version"] + 1
    assert_ledger(
        read_applicant(applicant_id), charges=50000, credits=10000, open_balance=40000
    )
    _rows, meta = validate_paginated(
        api_client.list_certificate_appeals(certificate_id, ADMIN)
    )
    assert meta["total_count"] == 2


def test_the_second_panel_member_voting_on_a_shared_read_is_refused():
    """Casting a panel vote requires `expected_appeal_version` in the body —
    again non-optional — carrying the `version` of the appeal as that panel
    member last read it. A mismatch with the appeal's current `version` is
    refused with `ERR_APPEAL_VERSION_CONFLICT` (HTTP 412) and no vote is
    recorded; the member must re-read the tally and resubmit. Since every
    accepted vote increments the appeal's `version`, a member whose read predates
    another member's vote is refused.

    Each accepted vote increments `votes_cast_count` and the counter for its own
    value, recomputes `effective_votes_count` as `revise_votes_count` plus
    `uphold_votes_count` — abstentions count toward neither side and are excluded
    from the denominator — and advances the appeal's `version`.

    Votes are immutable once cast and may be listed by `appeal_id` and
    `inspector_id`.

    5. **Schema** — required body fields present, correctly typed, inside their
    declared ranges and enum domains, with unknown fields rejected, else
    `ERR_INVALID_REQUEST` (422). Applies to every write endpoint.

    Design: Corner/cross_cutting_complexity_layers/stale_appeal_version_is_refused_when_casting_a_vote
    """
    office = setup_office(
        "DELEGATED",
        area_overrides={"supervision_required": False},
        fee_schedules=(GRADING_SCHEDULE, APPEAL_SCHEDULE),
    )
    staged = setup_appeal_under_review(
        office,
        appeal_type="APPEAL",
        regrade_factors=CORN_NO_2_FACTORS,
        panel_size=4,
        portions_count=4,
        declared_quantity_bushels=900,
        lot_identifier="LOT-AV1",
        seal_number="SEAL-AV1",
    )
    appeal_id = staged["appeal"]["id"]
    first, second, third = staged["voters"][0], staged["voters"][1], staged["voters"][2]

    shared = read_appeal(appeal_id)
    assert shared["status"] == "UNDER_REVIEW"
    assert shared["required_panel_size"] == 3
    assert shared["votes_cast_count"] == 0

    # Both members read the same tally; the first write moves the version.
    winner = validate_success(
        api_client.create_appeal_vote(
            appeal_vote_payload(appeal_id, first["id"], "UPHOLD", shared["version"]),
            SUPERVISOR,
        ),
        201,
    )

    loser = api_client.create_appeal_vote(
        appeal_vote_payload(appeal_id, second["id"], "REVISE", shared["version"]),
        SUPERVISOR,
    )
    validate_error(loser, ApiErrorId.ERR_APPEAL_VERSION_CONFLICT.value, 412)

    intact = read_appeal(appeal_id)
    assert intact["votes_cast_count"] == 1
    assert intact["uphold_votes_count"] == 1
    assert intact["revise_votes_count"] == 0
    assert intact["abstain_votes_count"] == 0
    assert intact["effective_votes_count"] == 1
    assert intact["version"] == shared["version"] + 1

    only_rows, only_meta = validate_paginated(
        api_client.list_appeal_votes(ADMIN, {"appeal_id": appeal_id})
    )
    assert only_meta["total_count"] == 1
    assert only_rows[0]["id"] == winner["id"]

    # Re-reading the tally is the member's remedy.
    resubmitted = validate_success(
        api_client.create_appeal_vote(
            appeal_vote_payload(appeal_id, second["id"], "REVISE", intact["version"]),
            SUPERVISOR,
        ),
        201,
    )
    assert resubmitted["id"] != winner["id"]

    tallied = read_appeal(appeal_id)
    assert tallied["votes_cast_count"] == 2
    assert tallied["revise_votes_count"] == 1
    assert tallied["uphold_votes_count"] == 1
    assert tallied["effective_votes_count"] == 2
    assert tallied["version"] == intact["version"] + 1

    # The echo is required, not merely checked.
    without_echo = api_client.create_appeal_vote(
        {"appeal_id": appeal_id, "inspector_id": third["id"], "vote": "UPHOLD"},
        SUPERVISOR,
    )
    validate_error(without_echo, ApiErrorId.ERR_INVALID_REQUEST.value, 422)

    unmoved = read_appeal(appeal_id)
    assert unmoved["votes_cast_count"] == 2
    assert unmoved["version"] == tallied["version"]
    _rows, meta = validate_paginated(
        api_client.list_appeal_votes(ADMIN, {"appeal_id": appeal_id})
    )
    assert meta["total_count"] == 2


def test_a_write_returns_every_figure_it_derived_with_nothing_left_to_settle():
    """Issuance stamps `issued_at` from the logical clock, assigns a
    `sequence_no` that is monotonically increasing per applicant starting at 1,
    and freezes the state of the request into snapshots: `grade_snapshot` and
    `limiting_factor_snapshot` copy the `assigned_grade` and `limiting_factor` of
    the request's `FINAL` determination and are null on a `WEIGHT` certificate;
    `net_lbs_snapshot` and `net_bushels_snapshot` copy the operative weighing
    record's `net_lbs` and `net_bushels` and are null when no weighing is
    certified; `protein_reported_pct_snapshot` copies the operative analysis's
    `protein_reported_pct` and is null when protein was not ordered; and
    `certified_quantity_bushels` copies the request's own
    `certified_quantity_bushels`, which is what the fee is assessed on. Two
    rights deadlines are computed and stored: `reinspection_deadline_at` is
    exactly 5 days after `issued_at` and `appeal_deadline_at` exactly 10 days
    after `issued_at`.

    The assessed fee is charged before the certificate is returned: it is added
    to the applicant's `charges_total_cents`, `open_balance_cents` is recomputed,
    and the certificate begins with `fee_paid_cents` 0 and `fee_settlement_status`
    `UNPAID`.

    `open_balance_cents` is always `charges_total_cents` minus
    `credits_total_cents`.

    The walk stops when the payment is exhausted, and the whole `amount_cents` is
    added to the applicant's `credits_total_cents`.

    A new watch is `SCHEDULED` with `stowage_certified` false, a null
    `started_at`, a null `closed_at` and a null `supervision_minutes`, and the
    owning area's `open_watch_count` increases by one.

    A watch may be aborted with an optional `reason` from either `SCHEDULED` or
    `IN_PROGRESS`; in both cases the area's `open_watch_count` decreases by one
    and the window is released for capacity purposes, so a later watch may occupy
    it.

    Design: Corner/consistency_model/every_derived_field_is_visible_in_the_same_response
    """
    office = setup_office("DESIGNATED", fee_schedules=(GRADING_SCHEDULE,))
    area_id = office["area"]["id"]
    applicant_id = office["applicant"]["id"]
    staged = setup_graded_request(
        office,
        declared_quantity_bushels=900,
        portions_count=2,
        requested_services=("GRADING", "EXPORT_SUPERVISION"),
        lot_identifier="LOT-DV1",
        seal_number="SEAL-DV1",
    )
    assert read_request(staged["request"]["id"])["certified_quantity_bushels"] == 900

    issued = validate_success(
        api_client.create_certificate(
            certificate_payload(
                staged["request"]["id"], office["inspector"]["id"], "GRADE"
            ),
            INSPECTOR,
        ),
        201,
    )
    # The creating response already carries every derived figure.
    assert issued["sequence_no"] == 1
    assert issued["fee_total_cents"] == 10000
    assert issued["fee_paid_cents"] == 0
    assert issued["fee_settlement_status"] == "UNPAID"
    assert issued["overtime_applied"] is False
    assert issued["grade_snapshot"] == "US_NO_1"
    assert issued["limiting_factor_snapshot"] == "NONE"
    assert issued["certified_quantity_bushels"] == 900
    assert issued["net_lbs_snapshot"] is None
    assert issued["net_bushels_snapshot"] is None
    assert issued["protein_reported_pct_snapshot"] is None
    assert issued["issued_at"].startswith("2026-08-03T09:00:00")
    assert issued["reinspection_deadline_at"].startswith("2026-08-08T09:00:00")
    assert issued["appeal_deadline_at"].startswith("2026-08-13T09:00:00")

    assert_ledger(
        read_applicant(applicant_id), charges=10000, credits=0, open_balance=10000
    )
    assert read_request(staged["request"]["id"])["grading_status"] == "GRADE_CERTIFIED"

    as_applicant = make_applicant_headers(applicant_id)
    validate_success(
        api_client.record_payment(applicant_id, payment_payload(10000), as_applicant),
        200,
    )
    assert_ledger(
        read_applicant(applicant_id), charges=10000, credits=10000, open_balance=0
    )
    settled = read_certificate(issued["id"])
    assert settled["fee_paid_cents"] == 10000
    assert settled["fee_settlement_status"] == "PAID"

    before = read_area(area_id)
    assert before["open_watch_count"] == 0

    watch = validate_success(
        api_client.create_vessel_watch(
            vessel_watch_payload(
                staged["request"]["id"],
                office["supervisor"]["id"],
                "2026-08-03T10:00:00Z",
                "2026-08-03T14:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert watch["status"] == "SCHEDULED"
    assert watch["stowage_certified"] is False
    assert watch["started_at"] is None
    assert watch["closed_at"] is None
    assert watch["supervision_minutes"] is None
    assert watch["service_area_id"] == area_id

    occupied = read_area(area_id)
    assert occupied["open_watch_count"] == 1
    assert occupied["version"] == before["version"] + 1

    validate_success(api_client.abort_vessel_watch(watch["id"], ADMIN), 200)
    released = read_area(area_id)
    assert released["open_watch_count"] == 0
    assert released["version"] == occupied["version"] + 1
