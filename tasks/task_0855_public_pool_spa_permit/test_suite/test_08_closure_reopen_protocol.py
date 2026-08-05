"""Closure orders, the cyclic reopen protocol and the two remediation variants."""

from test_helpers import (
    ADMIN,
    ADMIN_ONE_ID,
    INSPECTOR,
    INSPECTOR_TWO,
    INSPECTOR_TWO_ID,
    UNKNOWN_UUIDS,
    ApiErrorId,
    assert_posture,
    facility_version,
    log_water_reading,
    open_closure_order,
    read_closure_order,
    read_facility,
    request_reopen,
    set_clock,
    setup_closure_with_pending_reopen,
    setup_facility_with_issued_permit,
    setup_operator_and_pool,
    setup_operator_with_two_pools,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_denied_reopen_returns_the_order_to_open_and_counts_the_denial(api):
    """PRD 3.7: Denying returns the order `REOPEN_REQUESTED → OPEN`, increments
    `denial_count` by 1, stores the supplied `denial_reason` into
    `reopen_denial_reason` — one of `REMEDIATION_INCOMPLETE`,
    `WATER_NOT_IN_RANGE` or `VIOLATIONS_OPEN` — and stamps `reopen_decided_at`
    and `reopen_decided_by_user_id`. Crucially, a denial leaves
    `required_remediation_minutes`, `remediation_variant` and
    `earliest_reopen_at` exactly as the preceding request computed them; the
    operator may request again with a fresh verification reading, closing the
    `OPEN → REOPEN_REQUESTED → OPEN` cycle as many times as necessary.

    Design: Corner/state_machines/closure_reopen_denied_returns_order_to_open_and_counts_the_denial
    """
    ctx = setup_closure_with_pending_reopen()

    denied = validate_success(
        api.decide_reopen(
            ctx["closure_order_id"],
            {"decision": "DENY", "denial_reason": "VIOLATIONS_OPEN"},
            INSPECTOR_TWO,
        )
    )

    assert denied["status"] == "OPEN"
    assert denied["denial_count"] == 1
    assert denied["reopen_denial_reason"] == "VIOLATIONS_OPEN"
    assert denied["reopen_decided_by_user_id"] == INSPECTOR_TWO_ID
    assert denied["reopen_decided_at"] == "2026-05-01T02:00:00.000Z"
    assert denied["earliest_reopen_at"] == "2026-05-01T01:00:00.000Z"
    assert denied["cleared_at"] is None

    assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "CLOSURE_ORDER_OPEN")


def test_an_admin_may_void_an_order_they_raised_themselves(api):
    """PRD 3.7: Voiding is the administrative rescission of an order raised in
    error: only a `HealthAuthorityAdmin` may use it, it requires the order to be
    in `OPEN`, it is exempt from the four-eyes rule, and it moves the order
    `OPEN → VOIDED` while stamping `reopen_decided_at` and
    `reopen_decided_by_user_id` and recomputing the facility posture.
    PRD 2.6: **Closure state precondition**: a reopen request needs `OPEN`, an
    approve or deny needs `REOPEN_REQUESTED`, a void needs `OPEN` →
    `ERR_INVALID_CLOSURE_STATE` (409), on
    `POST /closure-orders/{id}/reopen-request` and
    `POST /closure-orders/{id}/reopen-decision`.

    Design: Corner/state_machines/closure_order_voided_by_admin_stops_gating_the_facility
    """
    ctx = setup_facility_with_issued_permit()
    order = open_closure_order(
        ctx["facility_id"], ADMIN, "EQUIPMENT", note="Filter pump alarm"
    )
    assert order["ordered_by_user_id"] == ADMIN_ONE_ID

    voided = validate_success(
        api.decide_reopen(order["id"], {"decision": "VOID"}, ADMIN)
    )
    assert voided["status"] == "VOIDED", (
        "The four-eyes rule is not applied to an administrative void"
    )

    assert_posture(
        read_facility(ctx["facility_id"]), "RESTRICTED", "SIGNAGE_INCOMPLETE"
    )

    validate_error(
        api.decide_reopen(order["id"], {"decision": "VOID"}, ADMIN),
        ApiErrorId.ERR_INVALID_CLOSURE_STATE.value, 409,
    )


def test_contact_time_target_is_multiplied_when_the_treatment_ph_is_high(api):
    """PRD 3.7: In that case `remediation_variant` becomes `CT_COMPUTED`: a
    contact-time target of 15300 parts-per-million-minutes is taken, multiplied
    by 1.5 when `treatment_ph` is strictly greater than 7.5 and left unmultiplied
    otherwise, then divided by the treatment chlorine level and rounded **up** to
    a whole number of minutes; `required_remediation_minutes` is the larger of
    that quotient and a 30-minute floor.
    PRD 3.7: In both variants `earliest_reopen_at` is recomputed as `ordered_at`
    advanced by the new duration; it is always measured from `ordered_at`, never
    from `reopen_requested_at`.

    Design: Corner/calculations/ct_window_multiplied_when_treatment_ph_above_threshold
    """
    ctx = setup_operator_and_pool()
    order = open_closure_order(ctx["facility_id"], INSPECTOR, "FECAL_DIARRHEAL")
    set_clock("2026-05-01T02:00:00Z")
    reading = log_water_reading(
        ctx["facility_id"], ctx["op_headers"],
        sampled_at="2026-05-01T01:30:00Z", source="REOPEN_VERIFICATION",
        free_chlorine_ppm=3.0, combined_chloramine_ppm=0.2,
    )

    requested = validate_success(
        api.request_reopen(
            order["id"],
            {
                "verification_reading_id": reading["id"],
                "treatment_free_chlorine_ppm": 40,
                "treatment_ph": 7.6,
            },
            ctx["op_headers"],
        )
    )

    assert requested["remediation_variant"] == "CT_COMPUTED"
    assert requested["required_remediation_minutes"] == 574
    assert requested["earliest_reopen_at"] == "2026-05-01T09:34:00.000Z"
    assert requested["status"] == "REOPEN_REQUESTED"


def test_contact_time_window_is_floored_at_thirty_minutes(api):
    """PRD 3.7: `required_remediation_minutes` is the larger of that quotient and
    a 30-minute floor.
    PRD 3.7: On success the order moves `REOPEN_REQUESTED → CLEARED`,
    `cleared_at` and `reopen_decided_at` are stamped from the logical clock,
    `reopen_decided_by_user_id` records the deciding principal, any
    `reopen_denial_reason` left by an earlier denial is cleared back to null, and
    the facility's posture is recomputed with its `version` incremented.

    Design: Corner/calculations/ct_window_floored_at_minimum_remediation_minutes
    """
    ctx = setup_operator_and_pool()
    order = open_closure_order(ctx["facility_id"], INSPECTOR, "FECAL_DIARRHEAL")
    set_clock("2026-05-01T02:00:00Z")
    reading = log_water_reading(
        ctx["facility_id"], ctx["op_headers"],
        sampled_at="2026-05-01T01:30:00Z", source="REOPEN_VERIFICATION",
        free_chlorine_ppm=3.0, combined_chloramine_ppm=0.2,
    )

    requested = request_reopen(
        order["id"], reading["id"], ctx["op_headers"],
        treatment_free_chlorine_ppm=600, treatment_ph=7.2,
    )
    assert requested["required_remediation_minutes"] == 30, (
        "ceil(15300/600) is 26, raised to the 30-minute floor"
    )
    assert requested["earliest_reopen_at"] == "2026-05-01T00:30:00.000Z"

    cleared = validate_success(
        api.decide_reopen(order["id"], {"decision": "APPROVE"}, INSPECTOR_TWO)
    )
    assert cleared["status"] == "CLEARED"
    assert cleared["cleared_at"] == "2026-05-01T02:00:00.000Z"


def test_a_verification_reading_older_than_sixty_minutes_is_stale(api):
    """PRD 3.7: The named reading must exist, must belong to this closure order's
    facility — otherwise `ERR_READING_FACILITY_MISMATCH` — and must be fresh: its
    `sampled_at` may be no more than 60 minutes before the logical clock and may
    not lie in the future, or the request is rejected with
    `ERR_VERIFICATION_READING_STALE`.

    Design: Corner/validations/reopen_request_with_a_stale_verification_reading_rejected
    """
    ctx = setup_operator_and_pool()
    order = open_closure_order(ctx["facility_id"], INSPECTOR, "CHEMICAL")
    set_clock("2026-05-01T01:30:00Z")
    reading = log_water_reading(
        ctx["facility_id"], ctx["op_headers"],
        sampled_at="2026-05-01T01:30:00Z", source="REOPEN_VERIFICATION",
    )
    set_clock("2026-05-01T03:00:00Z")

    validate_error(
        api.request_reopen(
            order["id"], {"verification_reading_id": reading["id"]}, ctx["op_headers"]
        ),
        ApiErrorId.ERR_VERIFICATION_READING_STALE.value, 409,
    )

    untouched = read_closure_order(order["id"])
    assert untouched["status"] == "OPEN"
    assert untouched["reopen_requested_at"] is None
    assert untouched["verification_reading_id"] is None


def test_a_verification_reading_from_another_venue_is_rejected(api):
    """PRD 2.6: **Verification-reading consistency.** The verification reading
    supplied on a reopen request belongs to the closure order's facility →
    `ERR_READING_FACILITY_MISMATCH` (409), on
    `POST /closure-orders/{id}/reopen-request`.

    Design: Corner/validations/reopen_request_with_a_reading_from_another_facility_rejected
    """
    ctx = setup_operator_with_two_pools(
        operator_overrides={
            "legal_name": "Twin Pools Trust",
            "contact_email": "ops@twinpools.example",
        }
    )
    order = open_closure_order(ctx["facility_a_id"], INSPECTOR, "CHEMICAL")
    set_clock("2026-05-01T02:00:00Z")
    other_reading = log_water_reading(
        ctx["facility_b_id"], ctx["op_headers"],
        sampled_at="2026-05-01T01:30:00Z", source="REOPEN_VERIFICATION",
    )

    validate_error(
        api.request_reopen(
            order["id"],
            {"verification_reading_id": other_reading["id"]},
            ctx["op_headers"],
        ),
        ApiErrorId.ERR_READING_FACILITY_MISMATCH.value, 409,
    )

    assert read_closure_order(order["id"])["status"] == "OPEN"


def test_an_imminent_hazard_reading_outranks_the_out_of_range_refusal(api):
    """PRD 3.7: Approving carries four further guards, checked in this order: the
    facility must have no violation whose own status is `OPEN` and whose severity
    is `IMMINENT_HEALTH_HAZARD` on a `FINALIZED` inspection, or
    `ERR_OPEN_CRITICAL_VIOLATIONS`; the stored verification reading must not be
    classified `IMMINENT_HAZARD`, or `ERR_IMMINENT_HEALTH_HAZARD`; it must be
    classified exactly `IN_RANGE`, so an `OUT_OF_RANGE` reading draws
    `ERR_WATER_NOT_IN_RANGE`; and the logical clock must have reached or passed
    `earliest_reopen_at`, or `ERR_REMEDIATION_INCOMPLETE`.

    Design: Corner/validations/imminent_hazard_reading_outranks_out_of_range_on_reopen_approval
    """
    ctx = setup_closure_with_pending_reopen(
        reading_overrides={"free_chlorine_ppm": 0.2}
    )

    response = api.decide_reopen(
        ctx["closure_order_id"], {"decision": "APPROVE"}, INSPECTOR_TWO
    )
    validate_error(response, ApiErrorId.ERR_IMMINENT_HEALTH_HAZARD.value, 409)
    assert response.json()["data"]["error_id"] != "ERR_WATER_NOT_IN_RANGE"

    assert ctx["reading"]["compliance_status"] == "IMMINENT_HAZARD"
    assert ctx["reading"]["triggered_closure_order_id"] is None, (
        "An order was already open, so no second order was created"
    )

    orders, meta = validate_paginated(
        api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 1
    assert read_closure_order(ctx["closure_order_id"])["status"] == "REOPEN_REQUESTED"


def test_approval_before_the_remediation_window_elapses_is_refused(api):
    """PRD 3.7: and the logical clock must have reached or passed
    `earliest_reopen_at`, or `ERR_REMEDIATION_INCOMPLETE`.
    PRD 3.7: The nine reasons and the remediation duration each one carries are
    fixed: `FECAL_FORMED` 30 minutes, `FECAL_DIARRHEAL` 765 minutes (twelve and
    three-quarter hours), `VOMIT` 30 minutes, `BLOOD` 30 minutes, `CHEMICAL` 60
    minutes, `WATER_CHEMISTRY` 30 minutes, `EQUIPMENT` 60 minutes,
    `RWI_OUTBREAK` 1440 minutes (a full day), and `PERMIT_ACTION` 0 minutes.

    Design: Corner/errors/reopen_approved_before_the_remediation_window_rejected
    """
    ctx = setup_closure_with_pending_reopen(
        clock_at_request=None, reading_sampled_at="2026-05-01T00:00:00Z"
    )

    validate_error(
        api.decide_reopen(
            ctx["closure_order_id"], {"decision": "APPROVE"}, INSPECTOR_TWO
        ),
        ApiErrorId.ERR_REMEDIATION_INCOMPLETE.value, 409,
    )

    order = read_closure_order(ctx["closure_order_id"])
    assert order["earliest_reopen_at"] == "2026-05-01T01:00:00.000Z"
    assert order["status"] == "REOPEN_REQUESTED"
    assert order["cleared_at"] is None
    assert ctx["reading"]["compliance_status"] == "IN_RANGE", (
        "The refusal is purely about the elapsed window"
    )


def test_stacking_a_closure_on_a_stale_facility_version_is_rejected(api):
    """PRD 2.7: Ordering a closure requires `expected_facility_version` as a
    non-optional field in the request body of `POST /closure-orders`, carrying
    the client's last observed `version` of the target facility. If it does not
    equal the facility's current `version`, the request is rejected with
    `ERR_STALE_FACILITY_VERSION` and HTTP 412.
    PRD 3.7: The facility's `operating_posture` is recomputed to `CLOSED` with
    `posture_reason` of `CLOSURE_ORDER_OPEN`, and on every manual creation the
    facility's `version` increments by 1 **whether or not the posture value
    actually changed** — a second order stacked on an already-closed venue still
    bumps the version.

    Design: Corner/cross_cutting_layers/occ_stale_facility_version_rejected_on_closure_create
    """
    ctx = setup_operator_and_pool()
    stale_version = ctx["facility"]["version"]
    first = open_closure_order(
        ctx["facility_id"], INSPECTOR, "CHEMICAL",
        note="Acid spill", expected_facility_version=stale_version,
    )

    validate_error(
        api.create_closure_order(
            {
                "facility_id": ctx["facility_id"],
                "closure_reason": "EQUIPMENT",
                "expected_facility_version": stale_version,
                "note": "Pump failure noticed on the same visit",
            },
            INSPECTOR,
        ),
        ApiErrorId.ERR_STALE_FACILITY_VERSION.value, 412,
    )

    fresh_version = facility_version(ctx["facility_id"], INSPECTOR)
    assert fresh_version > stale_version

    second = validate_success(
        api.create_closure_order(
            {
                "facility_id": ctx["facility_id"],
                "closure_reason": "EQUIPMENT",
                "expected_facility_version": fresh_version,
                "note": "Pump failure noticed on the same visit",
            },
            INSPECTOR,
        ),
        201,
    )
    assert second["closure_reason"] == "EQUIPMENT"
    assert second["status"] == "OPEN"
    assert facility_version(ctx["facility_id"], INSPECTOR) > fresh_version

    orders, meta = validate_paginated(
        api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in orders} == {first["id"], second["id"]}


class TestRemediationWindowVariants:
    """The same order yields a different reopen verdict under the two variants."""

    @staticmethod
    def _setup():
        ctx = setup_operator_and_pool()
        ctx["order"] = open_closure_order(
            ctx["facility_id"], INSPECTOR, "FECAL_DIARRHEAL",
            note="Diarrheal accident reported by lifeguard",
        )
        set_clock("2026-05-01T07:00:00Z")
        ctx["reading"] = log_water_reading(
            ctx["facility_id"], ctx["op_headers"],
            sampled_at="2026-05-01T06:30:00Z", source="REOPEN_VERIFICATION",
            free_chlorine_ppm=3.0, combined_chloramine_ppm=0.2,
        )
        return ctx

    def test_the_order_opens_on_the_table_window_and_the_request_recomputes_it(
        self, api
    ):
        """PRD 3.7: At creation the order stamps `ordered_at` from the logical
        clock, records `ordered_by_user_id` and `ordered_by_role` from the acting
        principal, sets `remediation_variant` to `FIXED_TABLE`, sets
        `required_remediation_minutes` to the table value for the reason, and
        sets `earliest_reopen_at` to `ordered_at` advanced by that many minutes.
        PRD 3.7: The contact-time variant applies when the order's
        `closure_reason` is `FECAL_DIARRHEAL` or `RWI_OUTBREAK` **and** the
        request supplied both a `treatment_free_chlorine_ppm` strictly greater
        than zero and a non-null `treatment_ph`.

        Design: Difficulty/dual_variant_calc/closure_reopen_window_fixed_table_vs_ct_computed
        """
        ctx = self._setup()

        assert ctx["order"]["remediation_variant"] == "FIXED_TABLE"
        assert ctx["order"]["required_remediation_minutes"] == 765
        assert ctx["order"]["earliest_reopen_at"] == "2026-05-01T12:45:00.000Z"

        requested = validate_success(
            api.request_reopen(
                ctx["order"]["id"],
                {
                    "verification_reading_id": ctx["reading"]["id"],
                    "treatment_free_chlorine_ppm": 40,
                    "treatment_ph": 7.2,
                },
                ctx["op_headers"],
            )
        )

        assert requested["remediation_variant"] == "CT_COMPUTED"
        assert requested["required_remediation_minutes"] == 383
        assert requested["earliest_reopen_at"] == "2026-05-01T06:23:00.000Z"

    def test_the_contact_time_window_clears_a_reopen_the_table_window_would_refuse(
        self, api
    ):
        """PRD 3.7: The practical effect is large: a diarrheal closure
        hyperchlorinated to 40 parts per million at pH 7.2 needs 383 minutes
        rather than the table's 765, so the same order reaches its reopen window
        hours earlier.
        PRD 3.7: On success the order moves `REOPEN_REQUESTED → CLEARED`,
        `cleared_at` and `reopen_decided_at` are stamped from the logical clock,
        `reopen_decided_by_user_id` records the deciding principal, any
        `reopen_denial_reason` left by an earlier denial is cleared back to null,
        and the facility's posture is recomputed with its `version` incremented.

        Design: Difficulty/dual_variant_calc/closure_reopen_window_fixed_table_vs_ct_computed
        """
        ctx = self._setup()
        request_reopen(
            ctx["order"]["id"], ctx["reading"]["id"], ctx["op_headers"],
            treatment_free_chlorine_ppm=40, treatment_ph=7.2,
        )

        cleared = validate_success(
            api.decide_reopen(
                ctx["order"]["id"], {"decision": "APPROVE"}, INSPECTOR_TWO
            )
        )

        assert cleared["status"] == "CLEARED", (
            "The clock is past the 383-minute window but hours short of the 765"
        )
        assert cleared["cleared_at"] == "2026-05-01T07:00:00.000Z"
        assert_posture(read_facility(ctx["facility_id"]), "CLOSED", "PERMIT_MISSING")


class TestReopenGatedOnTheVerificationReading:
    """The CLEARED edge depends on the classification the attached reading holds."""

    @staticmethod
    def _setup():
        return setup_closure_with_pending_reopen(
            reading_overrides={"free_chlorine_ppm": 0.8}
        )

    def test_an_out_of_range_reading_blocks_the_approval(self, api):
        """PRD 3.7: it must be classified exactly `IN_RANGE`, so an
        `OUT_OF_RANGE` reading draws `ERR_WATER_NOT_IN_RANGE`
        PRD 3.7: `compliance_status` is then `IMMINENT_HAZARD` if that hazard
        test fires, otherwise `OUT_OF_RANGE` if `out_of_range_parameters` is
        non-empty, otherwise `IN_RANGE`.

        Design: Difficulty/cross_entity_state_dependency/reopen_approval_gated_on_verification_reading_in_range_state
        """
        ctx = self._setup()

        response = api.decide_reopen(
            ctx["closure_order_id"], {"decision": "APPROVE"}, INSPECTOR_TWO
        )

        validate_error(response, ApiErrorId.ERR_WATER_NOT_IN_RANGE.value, 409)
        assert response.json()["data"]["error_id"] != "ERR_REMEDIATION_INCOMPLETE"
        assert ctx["reading"]["compliance_status"] == "OUT_OF_RANGE"
        assert ctx["reading"]["out_of_range_parameters"] == ["FREE_CHLORINE_LOW"]

    def test_the_refused_order_keeps_its_state_and_its_table_window(self, api):
        """PRD 3.7: Whenever either condition fails — the reason is not
        contact-time-eligible, or one of the treatment fields is missing or the
        chlorine level is not above zero — `remediation_variant` stays or reverts
        to `FIXED_TABLE` and `required_remediation_minutes` returns to the
        published table value for the reason.
        PRD 2.9: The facility has at least one closure order whose status is
        `OPEN` or `REOPEN_REQUESTED` → `CLOSED` with reason `CLOSURE_ORDER_OPEN`.

        Design: Difficulty/cross_entity_state_dependency/reopen_approval_gated_on_verification_reading_in_range_state
        """
        ctx = self._setup()
        validate_error(
            api.decide_reopen(
                ctx["closure_order_id"], {"decision": "APPROVE"}, INSPECTOR_TWO
            ),
            ApiErrorId.ERR_WATER_NOT_IN_RANGE.value, 409,
        )

        order = read_closure_order(ctx["closure_order_id"])
        assert order["status"] == "REOPEN_REQUESTED"
        assert order["cleared_at"] is None
        assert order["remediation_variant"] == "FIXED_TABLE"
        assert order["required_remediation_minutes"] == 60
        assert order["earliest_reopen_at"] == "2026-05-01T01:00:00.000Z", (
            "The clock is well past the window, so timing is not the blocker"
        )

        assert_posture(
            read_facility(ctx["facility_id"]), "CLOSED", "CLOSURE_ORDER_OPEN"
        )
