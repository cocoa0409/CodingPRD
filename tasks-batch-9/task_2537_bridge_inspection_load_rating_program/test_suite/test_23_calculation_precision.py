"""
The arithmetic: rounding order and direction, the filtered input sets the formulas
read from, and the derived counters that must agree with the rows they mirror.
"""

from prd_bench_local_runner.testing import validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import fhwa_reviewer_headers, program_admin_headers

FIELD_DAY = "2026-09-02T12:00:00Z"
QA_DAY = "2026-09-03T09:00:00Z"
DEADLINE = "2026-09-03T12:00:00Z"
ONE_SECOND_LATE = "2026-09-03T12:00:01Z"


# ─── The condition chain, element by element ────────────────────────────────
def test_each_element_row_is_scored_and_rounded_on_its_own(client, roster, bridge):
    """
    The four rows of the worked report each carry their own weighted index, computed
    at the moment the row is written and rounded there.

    PRD §3.2: "`element_health_index` scores the element on a 0-to-100 scale:
    multiply the good quantity by a full weight of 1.00, the fair quantity by 0.80,
    the poor quantity by 0.40 and the severe quantity by 0.00, sum those four
    products, divide by `total_quantity`, multiply by 100, and round the result half
    up to two decimal places."
    PRD §3.2: "An element of total quantity 1000 reporting 600 good, 200 fair, 150
    poor and 50 severe therefore scores 82.00; an element of total quantity 300
    reporting 0 good, 100 fair, 100 poor and 100 severe scores 40.00".

    Design: Corner/calculations/bridge_health_index_rounds_each_element_before_averaging
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    rows = draft["elements"]

    assert rows["deck"]["element_health_index"] == 82.00
    assert rows["girder"]["element_health_index"] == 40.00
    assert rows["bearing"]["element_health_index"] == 50.00
    assert rows["abutment"]["element_health_index"] == 95.00
    for row in rows.values():
        a.assert_two_decimals(row["element_health_index"], "element_health_index")


def test_the_report_index_averages_the_already_rounded_element_indices(
    client, roster, bridge
):
    """
    Submission re-normalises the element weights over the elements actually present
    and averages the rounded indices, giving the report's index and the three
    component ratings the descending ladder produces.

    PRD §3.3: "For a report carrying deck 82.00, girder 40.00, bearing 50.00 and
    abutment 95.00, the weights sum to 0.30 plus 0.25 plus 0.10 plus 0.10, which is
    0.75; the weighted scores sum to 24.60 plus 10.00 plus 5.00 plus 9.50, which is
    49.10; and 49.10 divided by 0.75 is 65.4666…, giving 65.47."
    PRD §3.3: "an index of at least 97 rates 9, at least 90 rates 8, at least 80
    rates 7, at least 70 rates 6, at least 60 rates 5, at least 45 rates 4, at least
    30 rates 3, at least 15 rates 2, at least 5 rates 1, and anything below 5 rates
    0."

    Design: Corner/calculations/bridge_health_index_rounds_each_element_before_averaging
    """
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    fx.set_clock(client, FIELD_DAY)

    submitted = fx.submit_report(client, draft["inspection"]["id"], roster)

    assert submitted["status"] == "SUBMITTED"
    a.assert_instant_equals(submitted["submitted_at"], FIELD_DAY, "submitted_at")
    assert submitted["deck_group_ehi"] == 82.00
    assert submitted["superstructure_group_ehi"] == 42.86
    assert submitted["substructure_group_ehi"] == 95.00
    assert submitted["computed_deck_rating"] == 7
    assert submitted["computed_superstructure_rating"] == 3
    assert submitted["computed_substructure_rating"] == 8
    assert submitted["bridge_health_index"] == 65.47
    a.assert_nbi_rating_from_index(submitted["computed_superstructure_rating"], 42.86)


def test_the_published_deficiency_sums_the_mixed_units_as_bare_numbers(
    client, roster, bridge
):
    """
    Acceptance publishes the quantity arithmetic: square metres, metres and counts
    are summed as bare numbers, and the deficient share of that total is rounded to
    two decimals.

    PRD §3.3: "Totals of 1000, 300, 4 and 4 against deficient quantities of 200, 200,
    2 and 0 give 100 times 402 divided by 1308, which is 30.7339…, rounded to 30.73."
    PRD §3.3: "The structure's `min_nbi_rating` is then recomputed as the smallest of
    the three component ratings, its `bridge_health_index` is copied from the
    report's, its `inventoried_quantity_total` is set to the sum of `total_quantity`
    across the report's element rows".

    Design: Corner/calculations/bridge_health_index_rounds_each_element_before_averaging
    """
    accepted = fx.accepted_report(client, bridge["id"], roster)

    report = accepted["inspection"]
    assert report["reported_quantity_total"] == 1308
    assert report["deficient_quantity_total"] == 402
    assert report["quantity_balanced"] is True

    structure = accepted["bridge"]
    assert structure["inventoried_quantity_total"] == 1308
    assert structure["deficiency_pct"] == 30.73
    assert structure["bridge_health_index"] == 65.47
    assert structure["min_nbi_rating"] == 3


# ─── The governing-rating candidate set ─────────────────────────────────────
def _one_approved_rating_and_one_better_sealed_rating(client, roster, bridge):
    """
    Cedar Creek carrying an approved rating that requires posting, plus a later,
    numerically better rating taken only as far as `SEALED`.
    """
    accepted = fx.accepted_report(client, bridge["id"], roster, qa_clock=QA_DAY)
    inspection_id = accepted["inspection"]["id"]
    governing = fx.approved_rating(client, bridge["id"], roster, inspection_id)
    better = fx.create_rating(
        client,
        bridge["id"],
        roster,
        inspection_id,
        dead_load_dc_kn_m=465.6,
        dead_load_dw_kn_m=33.5,
    )
    sealed = fx.seal_rating(client, better["id"], roster)
    return {"governing": governing, "better": better, "sealed": sealed}


def test_the_approved_rating_posts_the_structure_at_its_inventory_tonnage(
    client, roster, bridge
):
    """
    The operating factor decides that posting is required and the inventory tonnage
    decides the limit, quantised downward to the half ton.

    PRD §3.4: "The inventory denominator is 1.75 times 500 times 1.33, which is
    1163.75, giving a factor of 0.4769…, rounded to 0.477, and 0.477 times 36.0 is
    17.172, rounded to 17.2 tons."
    PRD §3.4: "Because 0.618 is below 1.000, posting is required, and the posted
    limit is 17.2 doubled to 34.4, floored to 34, halved to 17.0 tons."

    Design: Corner/calculations/governing_rating_selector_excludes_draft_and_sealed_rows
    """
    setup = _one_approved_rating_and_one_better_sealed_rating(client, roster, bridge)
    governing = setup["governing"]

    assert governing["rating_status"] == "APPROVED"
    assert governing["condition_factor_phi_c"] == 0.85
    assert governing["rating_factor_operating"] == 0.618
    assert governing["rating_factor_inventory"] == 0.477
    assert governing["operating_rating_tons"] == 22.2
    assert governing["inventory_rating_tons"] == 17.2
    assert governing["posting_required"] is True
    assert governing["posted_limit_tons"] == 17.0
    a.assert_half_ton_step(governing["posted_limit_tons"], "posted_limit_tons")


def test_a_better_but_unapproved_rating_never_displaces_the_governing_one(
    client, roster, bridge
):
    """
    The second rating is numerically better and needs no posting at all, yet while it
    is only sealed it is outside the candidate set: the structure keeps the approved
    rating's numbers and stays posted.

    PRD §3.4: "it considers only that structure's ratings whose `rating_status` is
    `APPROVED`, excluding `DRAFT`, `SEALED`, `REJECTED` and `SUPERSEDED` rows
    entirely."
    PRD §3.4: "so the operating factor is exactly 1.000 and posting is **not**
    required, leaving `posted_limit_tons` null while `operating_rating_tons` reads
    36.0."

    Design: Corner/calculations/governing_rating_selector_excludes_draft_and_sealed_rows
    """
    setup = _one_approved_rating_and_one_better_sealed_rating(client, roster, bridge)
    sealed = setup["sealed"]

    assert sealed["rating_status"] == "SEALED"
    assert sealed["rating_factor_operating"] == 1.000
    assert sealed["operating_rating_tons"] == 36.0
    assert sealed["posting_required"] is False
    assert sealed["posted_limit_tons"] is None

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["governing_load_rating_id"] == setup["governing"]["id"]
    assert structure["posting_required"] is True
    assert structure["posted_limit_tons"] == 17.0
    assert structure["operating_rating_tons"] == 22.2
    assert structure["inventory_rating_tons"] == 17.2
    assert structure["service_posture"] == "POSTED"


def test_the_structure_holds_exactly_one_approved_rating(client, roster, bridge):
    """
    Both rows exist on the structure and only one of them is approved, which is why
    the selector has anything to exclude.

    PRD §3.4: "Approval takes the rating `SEALED → APPROVED`, stores
    `approved_by_id`, and stamps `rating_effective_date` from the logical clock."
    PRD §3.4: "Sealing takes it from `DRAFT` to `SEALED`".

    Design: Corner/calculations/governing_rating_selector_excludes_draft_and_sealed_rows
    """
    setup = _one_approved_rating_and_one_better_sealed_rating(client, roster, bridge)

    listing = fx.ratings_for_bridge(client, bridge["id"])
    assert listing["meta"]["total_count"] == 2
    by_id = {row["id"]: row for row in listing["rows"]}
    assert by_id[setup["governing"]["id"]]["rating_status"] == "APPROVED"
    assert by_id[setup["better"]["id"]]["rating_status"] == "SEALED"
    approved = [
        row for row in listing["rows"] if row["rating_status"] == "APPROVED"
    ]
    assert [row["id"] for row in approved] == [setup["governing"]["id"]]


# ─── The compliance percentage and its acceptance threshold ─────────────────
def _three_structures_one_of_them_about_to_fall_due(client, roster, bridge):
    """
    Cedar Creek on the standard cycle alongside two modern low-traffic structures on
    the extended one, with a locked cycle holding a package ready to send.
    """
    for number, name, structure_type, area, detour in (
        ("STR-000002", "Willow Slough Bridge", "CULVERT", 600, 2.0),
        ("STR-000003", "Granite Ridge Overpass", "ARCH", 800, 5.0),
    ):
        fx.create_bridge(
            client,
            f.bridge_payload(
                number,
                name=name,
                structure_type=structure_type,
                deck_area_sqm=area,
                year_built=1995,
                adt=4000,
                detour_length_km=detour,
            ),
        )
    cycle = fx.create_cycle(client, fiscal_year=2029)
    submission = fx.start_submission(client, cycle["id"], submission_type="NBI_ANNUAL")
    fx.lock_cycle(client, cycle["id"])
    return {"cycle": cycle, "submission": submission}


def test_a_structure_is_still_compliant_on_its_due_date_itself(client, roster, bridge):
    """
    Two years on, at the exact instant Cedar Creek falls due, the overdue test is
    strictly less-than and reports it compliant; the modern structures are years from
    their own dates.

    PRD §3.1: "two booleans `routine_overdue` and `underwater_overdue` that are true
    when the corresponding due date lies strictly before the logical clock's current
    date".
    PRD §3.1: "A structure whose due date *is* today is compliant, not overdue — the
    comparison is strictly less-than."

    Design: Corner/calculations/inspection_compliance_pct_uses_strict_overdue_test_and_threshold_constant
    """
    _three_structures_one_of_them_about_to_fall_due(client, roster, bridge)
    fx.set_clock(client, "2028-09-01T00:00:00Z")

    compliance = fx.read_compliance(client, bridge["id"])

    a.assert_date_equals(
        compliance["next_inspection_due_date"], "2028-09-01", "next_inspection_due_date"
    )
    assert compliance["inspection_interval_months"] == 24
    assert compliance["routine_overdue"] is False
    assert compliance["underwater_overdue"] is False


def test_one_overdue_structure_in_three_rejects_the_package_on_compliance(
    client, roster, bridge
):
    """
    A day past the due date the snapshot reads two of three compliant, and 66.67 is
    below the acceptance threshold, so the rejection reason names the compliance
    picture rather than data gaps — and the cycle is returned to locked with its
    submission instant cleared.

    PRD §3.9: "`inspection_compliance_pct` is 100 if there are no structures at all;
    otherwise it is 100 multiplied by the compliant count, which is the total minus
    the overdue count, divided by the total, rounded half up to two decimal places.
    Three structures with one overdue gives 100 times 2 divided by 3, which is
    66.666…, rounded to 66.67."
    PRD §3.9: "records a `rejection_reason_code` derived from the snapshot:
    `COMPLIANCE_BELOW_THRESHOLD` when the stored `inspection_compliance_pct` is below
    90.00, and `DATA_GAPS` otherwise. The owning cycle returns `SUBMITTED → LOCKED`
    and its `submitted_at` is **cleared to null** so a corrected package can be sent
    afresh."

    Design: Corner/calculations/inspection_compliance_pct_uses_strict_overdue_test_and_threshold_constant
    """
    setup = _three_structures_one_of_them_about_to_fall_due(client, roster, bridge)
    fx.set_clock(client, "2028-09-02T00:00:00Z")

    sent = fx.send_submission(client, setup["submission"]["id"])
    assert sent["total_bridge_count"] == 3
    assert sent["overdue_inspection_count"] == 1
    assert sent["inspection_compliance_pct"] == 66.67
    assert sent["poa_noncompliant_count"] == 0
    assert sent["open_immediate_finding_count"] == 0
    assert sent["error_count"] == 0

    reviewed = fx.review_submission(
        client, setup["submission"]["id"], "REJECT", fhwa_reviewer_headers()
    )
    assert reviewed["status"] == "REJECTED"
    assert reviewed["rejection_reason_code"] == "COMPLIANCE_BELOW_THRESHOLD"

    cycle = fx.read_cycle(client, setup["cycle"]["id"])
    assert cycle["status"] == "LOCKED"
    assert cycle["submitted_at"] is None


# ─── Rounding half up at the third decimal ──────────────────────────────────
def _two_awkward_element_rows(client, roster, bridge):
    """One row whose index repeats and one that lands exactly on a half."""
    inspection = fx.open_inspection(client, bridge["id"], roster)
    deck = fx.add_element(
        client,
        inspection["id"],
        roster,
        f.element_condition_payload(
            "DECK",
            "SQM",
            7,
            3,
            2,
            1,
            1,
            photo_count=2,
            defect_notes="Two deck panels with through-cracking",
        ),
    )
    girder = fx.add_element(
        client,
        inspection["id"],
        roster,
        f.element_condition_payload(
            "GIRDER",
            "M",
            32,
            7,
            5,
            5,
            15,
            photo_count=9,
            defect_notes="Widespread section loss along the fascia girder",
        ),
    )
    return {"inspection": inspection, "deck": deck, "girder": girder}


def test_a_repeating_index_rounds_up_and_an_exact_half_carries_upward(
    client, roster, bridge
):
    """
    Two rows pin the direction of the rounding: a repeating decimal is rounded rather
    than truncated, and a value landing exactly on the half goes up rather than to
    the even neighbour.

    PRD §2.6: "All rounding in this system is **round half up** — a value exactly at
    the midpoint rounds away from zero."
    PRD §3.2: "sum those four products, divide by `total_quantity`, multiply by 100,
    and round the result half up to two decimal places."

    Design: Corner/calculations/element_health_index_half_up_at_the_third_decimal
    """
    setup = _two_awkward_element_rows(client, roster, bridge)

    assert setup["deck"]["element_health_index"] == 71.43
    assert setup["girder"]["element_health_index"] == 40.63
    a.assert_two_decimals(setup["deck"]["element_health_index"], "element_health_index")
    a.assert_two_decimals(
        setup["girder"]["element_health_index"], "element_health_index"
    )


def test_the_awkward_rows_still_balance_and_roll_up_exactly(client, roster, bridge):
    """
    Rounding touches only the index: the quantity arithmetic on both rows and on the
    report is exact integer bookkeeping.

    PRD §3.2: "`reported_sum` is the total of the four condition-state quantities.
    `balanced` is true exactly when `reported_sum` equals `total_quantity`.
    `deficient_quantity` is the sum of the poor and severe quantities — that is,
    `cs3_qty` plus `cs4_qty`."
    PRD §3.2: "Each element write also refreshes the parent report's rollup counters:
    `element_count` (the number of element rows), `reported_quantity_total` (the sum
    of `total_quantity` across rows), `deficient_quantity_total` (the sum of
    poor-plus-severe quantities across rows), `photo_count_total` (the sum of
    `photo_count` across rows)".

    Design: Corner/calculations/element_health_index_half_up_at_the_third_decimal
    """
    setup = _two_awkward_element_rows(client, roster, bridge)

    a.assert_element_derived_fields(setup["deck"], 7, 3, 2, 1, 1)
    a.assert_element_derived_fields(setup["girder"], 32, 7, 5, 5, 15)
    assert setup["deck"]["deficient_quantity"] == 2
    assert setup["girder"]["deficient_quantity"] == 20

    report = fx.read_inspection(client, setup["inspection"]["id"])
    assert report["element_count"] == 2
    assert report["reported_quantity_total"] == 39
    assert report["deficient_quantity_total"] == 22
    assert report["photo_count_total"] == 11


# ─── The notification deadline, to the second ───────────────────────────────
def _two_findings_aged_identically(client, roster, bridge):
    """Two urgent findings raised at the same instant off one submitted report."""
    draft = fx.draft_report_with_baseline(client, bridge["id"], roster)
    fx.set_clock(client, FIELD_DAY)
    fx.submit_report(client, draft["inspection"]["id"], roster)
    inspection_id = draft["inspection"]["id"]
    on_time = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        inspection_id,
        "URGENT",
        description="Advancing girder section loss - monitor weekly",
    )
    late = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        inspection_id,
        "URGENT",
        description="Abutment scour observed at the left wingwall",
    )
    return {"on_time": on_time, "late": late}


def test_a_notice_sent_at_the_deadline_instant_is_on_time(client, roster, bridge):
    """
    The deadline is the creation instant plus twenty-four hours and the lateness test
    is strict, so a notice sent at exactly that instant is not late.

    PRD §3.5: "Its `notification_due_at` is set to its own `created_at` plus 24 hours
    — the deadline for reaching the bridge owner."
    PRD §3.5: "an owner notice sent at exactly the deadline instant is on time, and
    one sent a single second later is late."

    Design: Corner/calculations/notification_exactly_at_the_deadline_is_not_late
    """
    setup = _two_findings_aged_identically(client, roster, bridge)
    a.assert_instant_equals(
        setup["on_time"]["notification_due_at"], DEADLINE, "notification_due_at"
    )
    a.assert_instant_equals(
        setup["late"]["notification_due_at"], DEADLINE, "notification_due_at"
    )

    fx.set_clock(client, DEADLINE)
    fx.notify_owner(
        client,
        setup["on_time"]["id"],
        roster,
        recipient_label="County bridge superintendent",
    )

    log = fx.logs_for_finding(client, setup["on_time"]["id"])[0]
    a.assert_instant_equals(log["sent_at"], DEADLINE, "sent_at")
    assert log["late"] is False

    finding = fx.read_finding(client, setup["on_time"]["id"])
    assert finding["notification_late"] is False
    assert finding["notification_status"] == "OWNER_NOTIFIED"


def test_a_notice_one_second_later_is_late_and_the_flag_sticks(client, roster, bridge):
    """
    The identically-aged second finding is notified one second past its deadline: the
    audit row records the lateness and the finding keeps the flag.

    PRD §3.5: "A log entry's `late` is true when its `tier` is `BRIDGE_OWNER` and its
    `sent_at` falls strictly after the finding's `notification_due_at`".
    PRD §3.5: "The finding's own `notification_late` is derived and sticky: it becomes
    true when a late owner notice is logged".

    Design: Corner/calculations/notification_exactly_at_the_deadline_is_not_late
    """
    setup = _two_findings_aged_identically(client, roster, bridge)

    fx.set_clock(client, ONE_SECOND_LATE)
    fx.notify_owner(
        client,
        setup["late"]["id"],
        roster,
        channel="PHONE",
        recipient_label="County bridge superintendent",
    )

    log = fx.logs_for_finding(client, setup["late"]["id"])[0]
    a.assert_instant_equals(log["sent_at"], ONE_SECOND_LATE, "sent_at")
    assert log["late"] is True
    assert log["channel"] == "PHONE"

    finding = fx.read_finding(client, setup["late"]["id"])
    assert finding["notification_late"] is True
    assert finding["notification_status"] == "OWNER_NOTIFIED"


# ─── A derived counter against the rows it mirrors ──────────────────────────
def test_the_open_finding_counter_mirrors_the_finding_rows(client, roster, bridge):
    """
    Two findings are raised and one is closed out, and the structure's counter tracks
    the unresolved slice rather than the row count.

    PRD §3.5: "Resolution stores the `resolution_note`, sets `finding_status` to
    `RESOLVED` (its terminal value), and then unwinds the structure:
    `open_critical_finding_count` is recomputed".
    PRD §3.5: "Creating the finding also increments the structure's
    `open_critical_finding_count`, which counts findings on that structure whose
    `finding_status` is `OPEN` or `MITIGATED`".

    Design: Corner/calculations/bridge_open_finding_counter_reconciles_with_filtered_finding_list
    """
    setup = _two_findings_aged_identically(client, roster, bridge)
    assert fx.read_bridge(client, bridge["id"])["open_critical_finding_count"] == 2

    fx.set_clock(client, "2026-09-03T00:00:00Z")
    fx.notify_owner(
        client,
        setup["on_time"]["id"],
        roster,
        recipient_label="County bridge superintendent",
    )
    resolved = fx.resolve(client, setup["on_time"]["id"], roster)
    assert resolved["finding_status"] == "RESOLVED"
    assert resolved["resolution_note"] is not None

    rows, meta = validate_paginated(
        client.list_critical_findings(program_admin_headers(), {"bridge_id": bridge["id"]})
    )
    assert meta["total_count"] == 2
    unresolved = [
        row for row in rows if row["finding_status"] in ("OPEN", "MITIGATED")
    ]
    assert [row["id"] for row in unresolved] == [setup["late"]["id"]]

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["open_critical_finding_count"] == len(unresolved) == 1
    assert structure["service_posture"] == "OPEN"
    assert structure["inspection_interval_months"] == 24
