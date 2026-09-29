"""Optimistic concurrency, cross-entity cascades and read-after-write consistency.

Every expectation here is fixed by the PRD: the two version-guarded creates of §2.12, the
error-correction approval cascade of §3.6 and §2.8, the certification cascade of §3.4 and
the assessment cascade of §3.9.
"""

from test_helpers import (
    certify_schedule,
    collect_audit,
    create_compliance_audit_payload,
    create_hold_amendment_payload,
    new_audit,
    new_correction,
    new_invoice,
    new_invoice_line,
    new_tier,
    read_exposure,
    read_invoice,
    read_item,
    read_schedule,
    read_tier,
    read_wholesaler,
    regulator_headers,
    set_clock,
    set_license_status_payload,
    setup_draft_schedule,
    setup_effective_schedule,
    setup_licensee_base,
    setup_submitted_schedule,
    setup_two_wholesalers_certified,
    submit_schedule,
    validate_error,
    validate_paginated,
    validate_success,
)

ITEM_750_12 = {
    "size_ml": 750,
    "bottles_per_case": 12,
    "case_price_cents": 120_000,
    "unit_price_cents": 11_000,
}


def test_01_a_successful_amendment_bumps_the_schedule_version_so_a_replay_is_stale(api):
    """PRD §2.12: "A successful create increments that schedule's `version` by 1 — which is precisely what invalidates every other client's previously read version."

    Two amendments are drafted against the same observed version of wholesaler A's schedule;
    the second one is exactly the replay the guard exists to reject.

    Design: Corner/cross-cutting complexity layers/a_successful_hold_amendment_bumps_the_schedule_version_so_replaying_the_same_expected_version_is_stale
    """
    scene = setup_two_wholesalers_certified(
        clock="2026-08-01T00:00:00Z",
        posting_month="2026-09",
        item_a_specs=[dict(ITEM_750_12)],
        item_b_spec={
            "size_ml": 750,
            "bottles_per_case": 12,
            "case_price_cents": 110_000,
            "unit_price_cents": 10_000,
        },
    )
    item_a = scene["items_a"][0]
    reference_id = scene["item_b"]["id"]
    observed_version = read_schedule(scene["schedule_a"]["id"])["version"]

    first = validate_success(
        api.create_hold_amendment(
            create_hold_amendment_payload(
                item_a["id"], reference_id, 114_000, 10_500, observed_version
            ),
            scene["agent_a_headers"],
        ),
        201,
    )
    assert first["status"] == "PENDING", (
        "the first amendment is created in PENDING, got {}".format(first["status"])
    )

    replay = api.create_hold_amendment(
        create_hold_amendment_payload(
            item_a["id"], reference_id, 113_000, 10_400, observed_version
        ),
        scene["agent_a_headers"],
    )
    validate_error(replay, "ERR_STALE_SCHEDULE_VERSION", 412)

    bumped_version = read_schedule(scene["schedule_a"]["id"])["version"]
    assert bumped_version == observed_version + 1, (
        "the successful create advanced the schedule version by exactly 1, {} became "
        "{}".format(observed_version, bumped_version)
    )

    retried = validate_success(
        api.create_hold_amendment(
            create_hold_amendment_payload(
                item_a["id"], reference_id, 113_000, 10_400, bumped_version
            ),
            scene["agent_a_headers"],
        ),
        201,
    )
    assert retried["status"] == "PENDING", (
        "the retry against the fresh version succeeds, got {}".format(retried["status"])
    )
    assert read_schedule(scene["schedule_a"]["id"])["version"] == bumped_version + 1, (
        "the second successful create advances the schedule version again"
    )

    data, meta = validate_paginated(
        api.list_hold_amendments(
            regulator_headers(), params={"amending_item_id": item_a["id"]}
        )
    )
    assert meta["total_count"] == 2, (
        "the stale replay created no amendment, got total_count {}".format(
            meta["total_count"]
        )
    )
    for amendment in data:
        assert amendment["status"] == "PENDING", (
            "neither amendment has been adjudicated, got {}".format(amendment["status"])
        )

    unchanged = read_item(item_a["id"])
    assert unchanged["case_price_cents"] == 120_000, (
        "filing alone never moves the item price, got {}".format(
            unchanged["case_price_cents"]
        )
    )


def test_02_audit_creation_uses_the_wholesaler_version_an_unrelated_change_invalidates(api):
    """PRD §2.12: "If that value does not equal the wholesaler's currently stored `version`, the request is rejected with `ERR_STALE_WHOLESALER_VERSION` (HTTP 412) and no `ComplianceAudit` is created."

    A licence-standing change is entirely unrelated to auditing, yet per §3.1 it advances the
    wholesaler's `version` and so invalidates the regulator's earlier read.

    Design: Corner/cross-cutting complexity layers/audit_creation_uses_the_wholesaler_version_which_an_unrelated_license_change_invalidates
    """
    scene = setup_licensee_base(clock="2026-08-20T00:00:00Z")
    wholesaler_id = scene["wholesaler"]["id"]
    observed_version = read_wholesaler(wholesaler_id)["version"]

    suspended = validate_success(
        api.set_wholesaler_license_status(
            wholesaler_id, set_license_status_payload("SUSPENDED"), regulator_headers()
        ),
        200,
    )
    assert suspended["license_status"] == "SUSPENDED", (
        "the licence-standing capability writes the supplied status, got {}".format(
            suspended["license_status"]
        )
    )

    stale = api.create_compliance_audit(
        create_compliance_audit_payload(
            wholesaler_id, scene["program"]["id"], "2026-08", observed_version
        ),
        regulator_headers(),
    )
    validate_error(stale, "ERR_STALE_WHOLESALER_VERSION", 412)

    _, meta = validate_paginated(api.list_compliance_audits(regulator_headers()))
    assert meta["total_count"] == 0, (
        "a stale audit create must persist nothing, got total_count {}".format(
            meta["total_count"]
        )
    )

    fresh_version = read_wholesaler(wholesaler_id)["version"]
    assert fresh_version == observed_version + 1, (
        "the licence change advanced the wholesaler version by 1, {} became {}".format(
            observed_version, fresh_version
        )
    )

    audit = validate_success(
        api.create_compliance_audit(
            create_compliance_audit_payload(
                wholesaler_id, scene["program"]["id"], "2026-08", fresh_version
            ),
            regulator_headers(),
        ),
        201,
    )
    assert audit["status"] == "OPEN", (
        "a new audit begins in OPEN, got {}".format(audit["status"])
    )
    assert audit["audit_period_month"] == "2026-08", (
        "the audit echoes its period month, got {}".format(audit["audit_period_month"])
    )
    assert audit["penalty_assessed_cents"] == 0, (
        "a new audit has assessed nothing, got {}".format(audit["penalty_assessed_cents"])
    )

    after = read_wholesaler(wholesaler_id)
    assert after["open_audit_count"] == 1, (
        "opening an audit increments open_audit_count to 1, got {}".format(
            after["open_audit_count"]
        )
    )
    assert after["version"] == fresh_version + 1, (
        "the successful create advanced the wholesaler version again, {} became {}".format(
            fresh_version, after["version"]
        )
    )


def test_03_approving_a_correction_cascades_through_the_item_the_tier_and_both_counters(api):
    """PRD §3.6: "Approval writes `corrected_case_price_cents` into the item's `case_price_cents` and `corrected_unit_price_cents` into the item's `unit_price_cents`, increments the item's `correction_count` by 1 and the owning schedule's `correction_count` by 1, recomputes `discounted_case_price_cents` on every `ACTIVE` quantity discount tier of the item, and advances the item's `version` by 1."

    The item carries an active five-case tier at ten percent, so approving the correction has
    to re-derive the tier price from the corrected case price.

    Design: Corner/cross-cutting complexity layers/approving_an_error_correction_cascades_through_the_item_the_tier_and_both_correction_counters
    """
    scene = setup_licensee_base(clock="2026-08-01T00:00:00Z")
    setup_draft_schedule(scene, posting_month="2026-09", item_specs=[dict(ITEM_750_12)])
    item = scene["items"][0]
    tier = new_tier(item["id"], scene["agent_headers"], min_cases=5, discount_pct=0.10)
    assert tier["discounted_case_price_cents"] == 108_000, (
        "120000 less ten percent is 108000, got {}".format(
            tier["discounted_case_price_cents"]
        )
    )
    submit_schedule(scene["schedule"]["id"], scene["agent_headers"])
    certify_schedule(scene["schedule"]["id"], scene["certifier_headers"])

    set_clock("2026-08-05T00:00:00.000Z")
    correction = new_correction(item["id"], 114_000, 10_500, scene["agent_headers"])
    assert correction["status"] == "SUBMITTED", (
        "a filed correction begins in SUBMITTED, got {}".format(correction["status"])
    )

    approved = validate_success(
        api.approve_error_correction(correction["id"], regulator_headers()), 200
    )
    assert approved["status"] == "APPROVED", (
        "approval is the SUBMITTED to APPROVED transition, got {}".format(
            approved["status"]
        )
    )

    corrected_item = read_item(item["id"])
    assert corrected_item["case_price_cents"] == 114_000, (
        "approval writes 114000 into the item, got {}".format(
            corrected_item["case_price_cents"]
        )
    )
    assert corrected_item["unit_price_cents"] == 10_500, (
        "approval writes 10500 into the item, got {}".format(
            corrected_item["unit_price_cents"]
        )
    )
    assert corrected_item["certified_case_price_cents"] == 120_000, (
        "the certification snapshot never changes, got {}".format(
            corrected_item["certified_case_price_cents"]
        )
    )
    assert corrected_item["correction_count"] == 1, (
        "the item's correction_count becomes 1, got {}".format(
            corrected_item["correction_count"]
        )
    )

    assert read_schedule(scene["schedule"]["id"])["correction_count"] == 1, (
        "the owning schedule's correction_count becomes 1"
    )

    recomputed_tier = read_tier(tier["id"])
    assert recomputed_tier["status"] == "ACTIVE", (
        "the tier stays ACTIVE through the cascade, got {}".format(
            recomputed_tier["status"]
        )
    )
    assert recomputed_tier["discounted_case_price_cents"] == 102_600, (
        "114000 less ten percent is 102600, got {}".format(
            recomputed_tier["discounted_case_price_cents"]
        )
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["correction_penalty_accrued_cents"] == 0, (
        "the first correction on a schedule is free, got {}".format(
            wholesaler["correction_penalty_accrued_cents"]
        )
    )
    assert wholesaler["penalty_exposure_cents"] == 0, (
        "no bucket moved, so exposure is still 0, got {}".format(
            wholesaler["penalty_exposure_cents"]
        )
    )


def test_04_the_certify_response_already_reflects_the_item_level_cascade_it_triggered(api):
    """PRD §3.4: "Every item of the schedule that is in `DRAFT` moves to `POSTED`, and for each such item the system snapshots the prices as filed: `case_price_cents` is copied into `certified_case_price_cents` and `unit_price_cents` into `certified_unit_price_cents`."

    The response to the certify call and an immediately following read must agree on every
    field certification wrote, and both items must already be posted.

    Design: Corner/consistency model/the_certify_response_itself_already_reflects_the_item_level_cascade_it_triggered
    """
    scene = setup_submitted_schedule(
        posting_month="2026-09",
        item_specs=[
            dict(ITEM_750_12),
            {
                "size_ml": 375,
                "bottles_per_case": 6,
                "case_price_cents": 30_000,
                "unit_price_cents": 5_500,
            },
        ],
        clock="2026-08-01T00:00:00Z",
    )
    schedule_id = scene["schedule"]["id"]

    certified = validate_success(
        api.certify_price_schedule(schedule_id, scene["certifier_headers"]), 200
    )
    assert certified["status"] == "POSTED", (
        "certification is the SUBMITTED to POSTED transition, got {}".format(
            certified["status"]
        )
    )
    assert certified["certified_at"] == "2026-08-01T00:00:00.000Z", (
        "certified_at is the current server time, got {}".format(
            certified["certified_at"]
        )
    )
    assert certified["hold_window_ends_at"] == "2026-08-04T00:00:00.000Z", (
        "a three-day hold window is 259200 seconds after certification, got {}".format(
            certified["hold_window_ends_at"]
        )
    )
    assert certified["effective_date"] == "2026-10-01T00:00:00.000Z", (
        "a 2026-09 posting month takes effect 2026-10-01T00:00:00.000Z, got {}".format(
            certified["effective_date"]
        )
    )
    assert certified["certified_by_user_id"] == scene["certifier"]["id"], (
        "the acting certifying officer is recorded, got {}".format(
            certified["certified_by_user_id"]
        )
    )

    fetched = read_schedule(schedule_id)
    for field in (
        "status",
        "certified_at",
        "certified_by_user_id",
        "hold_window_ends_at",
        "effective_date",
    ):
        assert fetched[field] == certified[field], (
            "the immediately following read must agree with the certify response on "
            "{}: {!r} against {!r}".format(field, fetched[field], certified[field])
        )

    posted_items, meta = validate_paginated(
        api.list_price_schedule_items(
            regulator_headers(), params={"schedule_id": schedule_id, "status": "POSTED"}
        )
    )
    assert meta["total_count"] == 2, (
        "both items moved to POSTED in the same request, got total_count {}".format(
            meta["total_count"]
        )
    )
    by_id = {row["id"]: row for row in posted_items}

    first = by_id[scene["items"][0]["id"]]
    assert first["certified_case_price_cents"] == 120_000, (
        "the first item snapshots 120000, got {}".format(
            first["certified_case_price_cents"]
        )
    )
    assert first["certified_unit_price_cents"] == 11_000, (
        "the first item snapshots 11000, got {}".format(
            first["certified_unit_price_cents"]
        )
    )

    second = by_id[scene["items"][1]["id"]]
    assert second["certified_case_price_cents"] == 30_000, (
        "the second item snapshots 30000, got {}".format(
            second["certified_case_price_cents"]
        )
    )
    assert second["certified_unit_price_cents"] == 5_500, (
        "the second item snapshots 5500, got {}".format(
            second["certified_unit_price_cents"]
        )
    )


def test_05_the_assess_response_and_a_following_wholesaler_read_agree_on_the_penalty(api):
    """PRD §3.9: "The audit's `penalty_assessed_cents` is added to the wholesaler's `assessed_penalty_cents`, the audit's `finding_count` is added to the wholesaler's `off_posted_violation_count`, `penalty_exposure_cents` is recomputed as the sum of the four buckets, and the wholesaler's `version` is advanced by 1."

    One undercharged invoice line worth 10,000 cents of variance produces a 4,000 cent
    penalty, and every read taken straight after assessment has to report that same figure.

    Design: Corner/consistency model/the_assess_response_and_an_immediately_following_wholesaler_read_agree_on_the_penalty
    """
    scene = setup_effective_schedule(
        posting_month="2026-08",
        item_specs=[dict(ITEM_750_12)],
        clock="2026-08-01T00:00:00Z",
        clock_before_run="2026-09-01T00:00:00Z",
    )
    item = scene["items"][0]
    assert scene["schedule"]["status"] == "EFFECTIVE", (
        "the August schedule takes effect on 2026-09-01, got {}".format(
            scene["schedule"]["status"]
        )
    )

    invoice = new_invoice(
        scene["wholesaler"]["id"], "2026-09-05T00:00:00Z", scene["agent_headers"]
    )
    new_invoice_line(
        invoice["id"], item["id"], 115_000, 11_000, scene["agent_headers"], cases_quantity=2
    )
    flagged = validate_success(
        api.validate_retailer_invoice(invoice["id"], scene["agent_headers"]), 200
    )
    assert flagged["validation_status"] == "FLAGGED", (
        "two cases charged at 115000 against a posted 120000 flags the invoice, got "
        "{}".format(flagged["validation_status"])
    )
    assert flagged["total_variance_cents"] == 10_000, (
        "the variance is 10000 cents, got {}".format(flagged["total_variance_cents"])
    )

    audit = new_audit(scene["wholesaler"]["id"], scene["program"]["id"], "2026-09")
    collect_audit(audit["id"])

    assessed = validate_success(
        api.assess_compliance_audit(audit["id"], regulator_headers()), 200
    )
    assert assessed["status"] == "ASSESSED", (
        "assessment is the COLLECTED to ASSESSED transition, got {}".format(
            assessed["status"]
        )
    )
    assert assessed["penalty_assessed_cents"] == 4_000, (
        "10000 cents at the default 0.40 rate and a 1.00 multiplier is 4000, got {}".format(
            assessed["penalty_assessed_cents"]
        )
    )
    assert assessed["tier_multiplier"] == 1.00, (
        "a prior_violation_count of 2 or fewer yields 1.00, got {}".format(
            assessed["tier_multiplier"]
        )
    )

    wholesaler = read_wholesaler(scene["wholesaler"]["id"])
    assert wholesaler["assessed_penalty_cents"] == 4_000, (
        "the assessed penalty lands in the assessed bucket, got {}".format(
            wholesaler["assessed_penalty_cents"]
        )
    )
    assert wholesaler["penalty_exposure_cents"] == 4_000, (
        "exposure is the plain sum of the four buckets, got {}".format(
            wholesaler["penalty_exposure_cents"]
        )
    )
    assert wholesaler["late_filing_penalty_accrued_cents"] == 0, (
        "the schedule was filed on time, so the late filing bucket is 0"
    )
    assert wholesaler["correction_penalty_accrued_cents"] == 0, (
        "no correction was approved, so the correction bucket is 0"
    )
    assert wholesaler["amendment_penalty_accrued_cents"] == 0, (
        "no amendment was rejected, so the amendment bucket is 0"
    )

    exposure = read_exposure(scene["wholesaler"]["id"])
    assert exposure["accrued_cents"] == 4_000, (
        "the exposure read reports 4000 accrued cents, got {}".format(
            exposure["accrued_cents"]
        )
    )
    assert exposure["provisional_cents"] == 0, (
        "nothing is in flight any more, got {}".format(exposure["provisional_cents"])
    )
    assert exposure["exposure_cents"] == 4_000, (
        "the exposure read reports 4000 cents, got {}".format(exposure["exposure_cents"])
    )

    findings, meta = validate_paginated(
        api.list_audit_findings(regulator_headers(), params={"audit_id": audit["id"]})
    )
    assert meta["total_count"] == 1, (
        "one off-posted line produced one finding, got total_count {}".format(
            meta["total_count"]
        )
    )
    assert findings[0]["variance_cents"] == 10_000, (
        "the finding carries the line's finding variance, got {}".format(
            findings[0]["variance_cents"]
        )
    )
    assert findings[0]["penalty_component_cents"] == 4_000, (
        "the finding's penalty component is 4000, got {}".format(
            findings[0]["penalty_component_cents"]
        )
    )

    collected_invoice = read_invoice(invoice["id"])
    assert collected_invoice["audit_status"] == "ASSESSED", (
        "every collected invoice moves from UNDER_AUDIT to ASSESSED, got {}".format(
            collected_invoice["audit_status"]
        )
    )
    assert collected_invoice["audit_id"] == audit["id"], (
        "the collected invoice still names the audit that took custody, got {}".format(
            collected_invoice["audit_id"]
        )
    )
