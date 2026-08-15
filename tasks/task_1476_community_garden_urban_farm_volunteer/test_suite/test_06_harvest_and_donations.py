"""Harvest logging pipeline, donation split arithmetic, segregation of duties,
and the season reconciliation guards (PRD §3.8, §3.3, §2.6)."""
from test_helpers import (
    ApiErrorId,
    assert_allocation,
    assert_harvest_log,
    create_harvest_log_payload,
    make_admin_headers,
    make_bed,
    make_certified_participant,
    make_officer_headers,
    make_participating_volunteer,
    make_volunteer_headers,
    setup_harvest_scenario,
    setup_season_harvesting,
    submit_log,
    validate_error,
    validate_success,
    verify_log,
)


def test_donation_split_floor_then_remainder_order(api):
    """PRD §3.8: "First, `volunteer_share_grams` is computed as the log's
    `weight_grams` multiplied by 0.20 and rounded down to a whole gram — the
    rounding happens first, before anything else. Second, `donatable_grams` is the
    remainder, `weight_grams` minus `volunteer_share_grams`, so the donatable pool
    absorbs the rounding rather than the volunteer share. Third, the request's
    line amounts are absolute integer grams, and they must sum exactly to
    `donatable_grams` — neither rounding the share to nearest nor
    summing-then-rounding is acceptable, and any mismatch is rejected with
    `ERR_SPLIT_MISMATCH`."

    Design: Difficulty/combinatorial_formula/donation_split_floor_then_remainder_order
    """
    admin = make_admin_headers()
    ctx = setup_harvest_scenario(weight_grams=9999, recipient_count=2)
    r1, r2 = ctx["recipients"]
    submit_log(ctx)
    verify_log(ctx)

    # floor(9999 * 0.20) == 1999; donatable == 8000. 5000 + 2999 == 7999 != 8000.
    err = validate_error(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [
                    {"recipient_id": r1["id"], "grams": 5000},
                    {"recipient_id": r2["id"], "grams": 2999},
                ],
            },
            admin,
        ),
        ApiErrorId.ERR_SPLIT_MISMATCH,
    )
    assert err["error_id"] == "ERR_SPLIT_MISMATCH"

    allocation = validate_success(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [
                    {"recipient_id": r1["id"], "grams": 5000},
                    {"recipient_id": r2["id"], "grams": 3000},
                ],
            },
            admin,
        ),
        expected_status=201,
    )
    assert_allocation(allocation)
    assert allocation["volunteer_share_grams"] == 1999, "share floored FIRST"
    assert allocation["donatable_grams"] == 8000, "the remainder absorbs the rounding"
    assert allocation["status"] == "PENDING"


def test_allocation_blocked_until_harvest_verified(api):
    """PRD §3.8: "The referenced log must be `VERIFIED` (otherwise
    `ERR_HARVEST_LOG_NOT_VERIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/allocation_blocked_until_harvest_verified
    """
    admin = make_admin_headers()
    ctx = setup_harvest_scenario(weight_grams=10000, recipient_count=1)
    (r1,) = ctx["recipients"]
    submit_log(ctx)

    # Split sums exactly (share 2000, donatable 8000) — state, not math, blocks.
    err = validate_error(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        ApiErrorId.ERR_HARVEST_LOG_NOT_VERIFIED,
    )
    assert err["error_id"] == "ERR_HARVEST_LOG_NOT_VERIFIED"

    verify_log(ctx)
    allocation = validate_success(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        expected_status=201,
    )
    assert_allocation(allocation)
    assert allocation["status"] == "PENDING"


def test_allocation_approve_distribute_finalizes_harvest_log(api):
    """PRD §3.8: "Segregation of duties applies: the verifier's identity must
    differ from the log's `logged_by_volunteer_id` (otherwise
    `ERR_SEGREGATION_OF_DUTIES`)".
    PRD §3.8: "segregation of duties bars the harvest's logger from approving
    (otherwise `ERR_SEGREGATION_OF_DUTIES`)".
    PRD §3.8: "On approval each recipient's `committed_this_week_grams` rises by
    its line grams."
    PRD §3.8: "Distribution cascades: the harvest log moves from `VERIFIED` to
    `SPLIT_FINALIZED`, and both the allocation's and the log's `version`
    increment."

    Design: Corner/state_machines/allocation_approve_distribute_finalizes_harvest_log
    """
    admin = make_admin_headers()
    ctx = setup_harvest_scenario(weight_grams=10000, recipient_count=1)
    (r1,) = ctx["recipients"]
    logger, officer = ctx["logger"], ctx["officer"]
    submit_log(ctx)

    # An officer acting with the LOGGER's identity fails the SoD comparison.
    err = validate_error(
        api.transition_harvest_log(
            ctx["log"]["id"], {"to_state": "VERIFIED"}, make_officer_headers(logger["id"])
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES"

    verified = validate_success(
        api.transition_harvest_log(
            ctx["log"]["id"], {"to_state": "VERIFIED"}, make_officer_headers(officer["id"])
        )
    )
    assert verified["status"] == "VERIFIED"

    allocation = validate_success(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        expected_status=201,
    )

    err = validate_error(
        api.transition_donation_allocation(
            allocation["id"], {"to_state": "APPROVED"}, make_officer_headers(logger["id"])
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
    )
    assert err["error_id"] == "ERR_SEGREGATION_OF_DUTIES", "approver == logger"

    approved = validate_success(
        api.transition_donation_allocation(
            allocation["id"], {"to_state": "APPROVED"}, make_officer_headers(officer["id"])
        )
    )
    assert approved["status"] == "APPROVED"
    recipient_now = validate_success(api.get_donation_recipient(r1["id"], admin))
    assert recipient_now["committed_this_week_grams"] == 8000, (
        "weekly commitment booked at approval"
    )

    distributed = validate_success(
        api.transition_donation_allocation(
            allocation["id"], {"to_state": "DISTRIBUTED"}, admin
        )
    )
    assert distributed["status"] == "DISTRIBUTED"
    log_now = validate_success(api.get_harvest_log(ctx["log"]["id"], admin))
    assert_harvest_log(log_now)
    assert log_now["status"] == "SPLIT_FINALIZED", "distribution cascade to terminal"


def test_harvest_reject_edit_resubmit_cycle(api):
    """PRD §3.8: "While a log is `DRAFT`, staff or the logger may edit its
    `crop_type`, `weight_grams`, `quality_grade`, `harvested_at`,
    `safety_attestation`, or `crop_plan_id`; editing a log in any other status is
    rejected with `ERR_INVALID_HARVEST_STATE`".
    PRD §3.8: "A rejected log is not dead: staff or the logger may return it from
    `REJECTED` to `DRAFT`, which clears `rejection_reason` to null and reopens
    editing."

    Design: Corner/state_machines/harvest_reject_edit_resubmit_cycle
    """
    ctx = setup_harvest_scenario(weight_grams=5000, recipient_count=0)
    logger, officer = ctx["logger"], ctx["officer"]
    logger_headers = make_volunteer_headers(logger["id"])
    officer_headers = make_officer_headers(officer["id"])
    submit_log(ctx)

    err = validate_error(
        api.patch_harvest_log(ctx["log"]["id"], {"weight_grams": 6000}, logger_headers),
        ApiErrorId.ERR_INVALID_HARVEST_STATE,
    )
    assert err["error_id"] == "ERR_INVALID_HARVEST_STATE", "PATCH allowed only while DRAFT"

    rejected = validate_success(
        api.transition_harvest_log(
            ctx["log"]["id"],
            {"to_state": "REJECTED", "rejection_reason": "scale uncalibrated"},
            officer_headers,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "scale uncalibrated"

    draft = validate_success(
        api.transition_harvest_log(ctx["log"]["id"], {"to_state": "DRAFT"}, logger_headers)
    )
    assert draft["status"] == "DRAFT"
    assert draft["rejection_reason"] is None, "resubmission clears the reason"

    patched = validate_success(
        api.patch_harvest_log(ctx["log"]["id"], {"weight_grams": 6000}, logger_headers)
    )
    assert patched["weight_grams"] == 6000, "edit applies while DRAFT"

    resubmitted = validate_success(
        api.transition_harvest_log(ctx["log"]["id"], {"to_state": "SUBMITTED"}, logger_headers)
    )
    assert resubmitted["status"] == "SUBMITTED"
    verified = validate_success(
        api.transition_harvest_log(
            ctx["log"]["id"], {"to_state": "VERIFIED"}, officer_headers
        )
    )
    assert verified["status"] == "VERIFIED"


def test_season_reconciliation_blocked_by_submitted_log_then_pending_allocation(api):
    """PRD §3.3: "`HARVESTING → RECONCILIATION` requires zero harvest logs for
    the season in `SUBMITTED`, otherwise `ERR_HARVEST_LOGS_UNVERIFIED`, and zero
    donation allocations for the season's logs in `PENDING`, otherwise
    `ERR_ALLOCATIONS_PENDING`."

    Design: Corner/state_machines/season_reconciliation_blocked_by_submitted_log_then_pending_allocation
    """
    admin = make_admin_headers()
    ctx = setup_harvest_scenario(weight_grams=10000, recipient_count=1)
    (r1,) = ctx["recipients"]
    submit_log(ctx)

    err = validate_error(
        api.transition_season(ctx["season"]["id"], {"to_state": "RECONCILIATION"}, admin),
        ApiErrorId.ERR_HARVEST_LOGS_UNVERIFIED,
    )
    assert err["error_id"] == "ERR_HARVEST_LOGS_UNVERIFIED"

    verify_log(ctx)
    allocation = validate_success(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        expected_status=201,
    )

    err = validate_error(
        api.transition_season(ctx["season"]["id"], {"to_state": "RECONCILIATION"}, admin),
        ApiErrorId.ERR_ALLOCATIONS_PENDING,
    )
    assert err["error_id"] == "ERR_ALLOCATIONS_PENDING"

    validate_success(
        api.transition_donation_allocation(
            allocation["id"], {"to_state": "APPROVED"},
            make_officer_headers(ctx["officer"]["id"]),
        )
    )
    validate_success(
        api.transition_donation_allocation(
            allocation["id"], {"to_state": "DISTRIBUTED"}, admin
        )
    )
    reconciled = validate_success(
        api.transition_season(ctx["season"]["id"], {"to_state": "RECONCILIATION"}, admin)
    )
    assert reconciled["status"] == "RECONCILIATION"


def test_bed_state_beats_missing_cert_on_harvest_create(api):
    """PRD §2.6: "When several checks could reject the same request, the server
    evaluates them in a fixed global order and reports the first failure
    encountered — first match wins."
    PRD §2.6: "7. **Cross-entity state guards.** The referenced season, bed, slot,
    or harvest log is in a status that accepts the operation, otherwise the
    guard-specific 409 error (`ERR_SEASON_NOT_ACCEPTING`, `ERR_BED_NOT_AVAILABLE`,
    `ERR_BED_NOT_HARVEST_OPEN`, `ERR_HARVEST_LOG_NOT_VERIFIED`, or a season-level
    guard such as `ERR_CROP_PLANS_UNRESOLVED`)."
    PRD §2.6: "9. **Certification gates.** `ERR_PRODUCE_SAFETY_CERT_REQUIRED`,
    `ERR_TOOL_CERT_REQUIRED`, and `ERR_SAFETY_ATTESTATION_REQUIRED` (409)."
    PRD §3.8: "the bed must be in `HARVEST_OPEN` (otherwise
    `ERR_BED_NOT_HARVEST_OPEN`)".

    Design: Difficulty/priority_pair_validation_conflict/bed_state_beats_missing_cert_on_harvest_create
    """
    admin = make_admin_headers()
    ctx = setup_season_harvesting()  # bed B-01 reaches HARVEST_OPEN
    bed2 = make_bed(bed_code="B-02", size_sq_ft=80, sun_exposure="SHADE",
                    irrigation_zone="Z2")  # stays FALLOW
    logger = make_participating_volunteer()  # oriented + signed, NO produce cert
    validate_success(api.set_clock({"to_iso8601": "2026-09-15T12:00:00Z"}, admin))

    err = validate_error(
        api.create_harvest_log(
            create_harvest_log_payload(
                season_id=ctx["season"]["id"],
                bed_id=bed2["id"],
                logged_by_volunteer_id=logger["id"],
                crop_type="Kale",
                weight_grams=1000,
            ),
            make_volunteer_headers(logger["id"]),
        ),
        ApiErrorId.ERR_BED_NOT_HARVEST_OPEN,
    )
    assert err["error_id"] == "ERR_BED_NOT_HARVEST_OPEN", (
        "the cross-entity state guard (tier 7) precedes the certification gate "
        "(tier 9), even though the logger also lacks PRODUCE_SAFETY"
    )


def test_donation_split_even_weight_exact_boundary(api):
    """PRD §3.8: "First, `volunteer_share_grams` is computed as the log's
    `weight_grams` multiplied by 0.20 and rounded down to a whole gram — the
    rounding happens first, before anything else. Second, `donatable_grams` is the
    remainder, `weight_grams` minus `volunteer_share_grams`, so the donatable pool
    absorbs the rounding rather than the volunteer share. Third, the request's
    line amounts are absolute integer grams, and they must sum exactly to
    `donatable_grams` — neither rounding the share to nearest nor
    summing-then-rounding is acceptable, and any mismatch is rejected with
    `ERR_SPLIT_MISMATCH`."

    Design: Difficulty/combinatorial_formula/donation_split_floor_then_remainder_order
    """
    admin = make_admin_headers()
    ctx = setup_harvest_scenario(weight_grams=10000, recipient_count=1)
    (r1,) = ctx["recipients"]
    submit_log(ctx)
    verify_log(ctx)

    # floor(10000 * 0.20) == 2000 exactly; donatable == 8000.
    err = validate_error(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 7999}],
            },
            admin,
        ),
        ApiErrorId.ERR_SPLIT_MISMATCH,
    )
    assert err["error_id"] == "ERR_SPLIT_MISMATCH", "7999 != 8000: exact sum required"

    allocation = validate_success(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        expected_status=201,
    )
    assert_allocation(allocation)
    assert allocation["volunteer_share_grams"] == 2000
    assert allocation["donatable_grams"] == 8000
    assert allocation["status"] == "PENDING"


def test_allocation_rejected_for_draft_log(api):
    """PRD §3.8: "The referenced log must be `VERIFIED` (otherwise
    `ERR_HARVEST_LOG_NOT_VERIFIED`)".

    Design: Difficulty/cross_entity_state_dependency/allocation_blocked_until_harvest_verified
    """
    admin = make_admin_headers()
    ctx = setup_harvest_scenario(weight_grams=10000, recipient_count=1)
    (r1,) = ctx["recipients"]
    assert ctx["log"]["status"] == "DRAFT"

    err = validate_error(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        ApiErrorId.ERR_HARVEST_LOG_NOT_VERIFIED,
    )
    assert err["error_id"] == "ERR_HARVEST_LOG_NOT_VERIFIED", "a DRAFT log cannot be split"

    submit_log(ctx)
    verify_log(ctx)
    allocation = validate_success(
        api.create_donation_allocation(
            {
                "harvest_log_id": ctx["log"]["id"],
                "lines": [{"recipient_id": r1["id"], "grams": 8000}],
            },
            admin,
        ),
        expected_status=201,
    )
    assert allocation["status"] == "PENDING"


def test_harvest_create_isolated_state_and_cert_failures(api):
    """PRD §3.8: "Creation applies its gates in sequence: the season must be in
    `HARVESTING` (otherwise `ERR_SEASON_NOT_ACCEPTING`); the bed must be in
    `HARVEST_OPEN` (otherwise `ERR_BED_NOT_HARVEST_OPEN`); the logger must pass
    the participation gates of §2.8 (`ERR_ORIENTATION_REQUIRED`,
    `ERR_WAIVER_REQUIRED`, `ERR_VOLUNTEER_SUSPENDED`); the logger must hold an
    `ACTIVE` `PRODUCE_SAFETY` certification (otherwise
    `ERR_PRODUCE_SAFETY_CERT_REQUIRED`)".

    Design: Difficulty/priority_pair_validation_conflict/bed_state_beats_missing_cert_on_harvest_create
    """
    admin = make_admin_headers()
    ctx = setup_season_harvesting()  # ctx["bed"] is HARVEST_OPEN
    bed2 = make_bed(bed_code="B-77", size_sq_ft=80, sun_exposure="SHADE",
                    irrigation_zone="Z9")  # stays FALLOW
    certified_logger, _cert, _officer = make_certified_participant("PRODUCE_SAFETY")
    plain_logger = make_participating_volunteer()  # no certification
    validate_success(api.set_clock({"to_iso8601": "2026-09-15T12:00:00Z"}, admin))

    # Only the bed gate fails: the logger holds the certification.
    err = validate_error(
        api.create_harvest_log(
            create_harvest_log_payload(
                season_id=ctx["season"]["id"],
                bed_id=bed2["id"],
                logged_by_volunteer_id=certified_logger["id"],
                crop_type="Kale",
                weight_grams=1000,
            ),
            make_volunteer_headers(certified_logger["id"]),
        ),
        ApiErrorId.ERR_BED_NOT_HARVEST_OPEN,
    )
    assert err["error_id"] == "ERR_BED_NOT_HARVEST_OPEN"

    # Only the certification gate fails: the bed is HARVEST_OPEN.
    err = validate_error(
        api.create_harvest_log(
            create_harvest_log_payload(
                season_id=ctx["season"]["id"],
                bed_id=ctx["bed"]["id"],
                logged_by_volunteer_id=plain_logger["id"],
                crop_type="Kale",
                weight_grams=1000,
            ),
            make_volunteer_headers(plain_logger["id"]),
        ),
        ApiErrorId.ERR_PRODUCE_SAFETY_CERT_REQUIRED,
    )
    assert err["error_id"] == "ERR_PRODUCE_SAFETY_CERT_REQUIRED"
