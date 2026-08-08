"""Complaint investigation workflow and recreational-water-illness risk scoring."""

from test_helpers import (
    ADMIN,
    ANON,
    INSPECTOR,
    ApiErrorId,
    assert_complaint,
    assert_posture,
    create_rwi_complaint_payload,
    file_complaint,
    file_rwi_complaint,
    read_complaint,
    read_facility,
    read_inspection,
    setup_complaint_investigation,
    setup_operator_and_pool,
    setup_operator_with_two_pools,
    transition_complaint,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_water_quality_complaint_walks_the_full_investigation_to_closed(api):
    """PRD 3.9: For any `complaint_type` other than `RWI_ILLNESS` the outcome is
    fixed and trivial: `risk_variant` is null, `cluster_case_count` is 0,
    `risk_score` is 0 and `escalated` is false.
    PRD 3.9: From `INVESTIGATING` the complaint forks two ways with symmetric
    treatment: **substantiating** moves `INVESTIGATING → SUBSTANTIATED` and
    **unsubstantiating** moves `INVESTIGATING → UNSUBSTANTIATED`, both requiring
    that the linked inspection's `workflow_status` has reached `FINALIZED` and
    both storing the investigator's conclusion into `finding` from the request
    body.
    PRD 3.9: Finally a `HealthAuthorityAdmin` **closes** the matter from either
    branch, moving `SUBSTANTIATED → CLOSED` or `UNSUBSTANTIATED → CLOSED` with
    identical behaviour and no side effects.

    Design: Corner/state_machines/complaint_advances_through_full_investigation_to_closed
    """
    ctx = setup_operator_and_pool()
    complaint = file_complaint(
        ctx["facility_id"], ANON, reporter_contact="swimmer@example.com"
    )

    assert_complaint(complaint)
    assert complaint["risk_score"] == 0
    assert complaint["risk_variant"] is None
    assert complaint["cluster_case_count"] == 0
    assert complaint["escalated"] is False

    inspection = setup_complaint_investigation(
        ctx["facility_id"], complaint["id"]
    )
    assert read_complaint(complaint["id"])["linked_inspection_id"] == inspection["id"]
    assert inspection["score"] == 100
    assert inspection["result"] == "PASS"

    transition_complaint(
        complaint["id"], "SUBSTANTIATE", INSPECTOR,
        finding="Filter media exhausted; turbidity confirmed",
    )
    closed = validate_success(
        api.transition_complaint(complaint["id"], {"action": "CLOSE"}, ADMIN)
    )

    assert closed["status"] == "CLOSED"
    assert closed["finding"] == "Filter media exhausted; turbidity confirmed"

    rows, meta = validate_paginated(
        api.list_complaints(ADMIN, params={"linked_inspection_id": inspection["id"]})
    )
    assert meta["total_count"] == 1 and rows[0]["id"] == complaint["id"]


def test_starting_an_investigation_without_a_linked_inspection_is_rejected(api):
    """PRD 3.9: **Starting the investigation** moves `TRIAGED → INVESTIGATING`
    and requires `linked_inspection_id` to be non-null — a complaint triaged
    without an inspection attached cannot advance, and the attempt draws
    `ERR_INVALID_COMPLAINT_STATE`.
    PRD 3.9: **Triage** moves the complaint `RECEIVED → TRIAGED` and stores
    `linked_inspection_id` when the inspector supplies one; the referenced
    inspection must have `inspection_type` of `COMPLAINT` and belong to the same
    facility as the complaint, or the request is rejected with
    `ERR_PRIOR_INSPECTION_MISMATCH`.

    Design: Corner/state_machines/complaint_start_investigation_without_linked_inspection_rejected
    """
    ctx = setup_operator_and_pool()
    complaint = file_complaint(
        ctx["facility_id"], ANON, complaint_type="SANITATION",
        narrative="Changing rooms not cleaned",
    )
    transition_complaint(complaint["id"], "TRIAGE", INSPECTOR)

    validate_error(
        api.transition_complaint(
            complaint["id"], {"action": "START_INVESTIGATION"}, INSPECTOR
        ),
        ApiErrorId.ERR_INVALID_COMPLAINT_STATE.value, 409,
    )

    stored = read_complaint(complaint["id"])
    assert stored["status"] == "TRIAGED"
    assert stored["linked_inspection_id"] is None


def test_an_unsubstantiated_peer_drops_out_of_the_cluster_set(api):
    """PRD 3.9: For an illness report the scorer first looks for peers — other
    complaints at the same facility, excluding this one, whose `complaint_type`
    is also `RWI_ILLNESS`, whose `status` is neither `UNSUBSTANTIATED` nor
    `CLOSED`, and whose `reported_at` falls within the 14-day window ending at
    this complaint's `reported_at`, with both ends of that window inclusive.
    PRD 3.9: Note the feedback loop the surveillance rules create: an
    unsubstantiated or closed complaint drops out of the peer set for future
    cluster scoring, so resolving a report correctly also stops it inflating the
    risk score of the next one filed at that venue.

    Design: Corner/calculations/rwi_cluster_window_excludes_unsubstantiated_peer_complaint
    """
    ctx = setup_operator_and_pool()
    first = file_rwi_complaint(
        ctx["facility_id"], 2,
        narrative="Two swimmers reported respiratory illness",
        pathogen_suspected="LEGIONELLA",
    )
    setup_complaint_investigation(ctx["facility_id"], first["id"])
    transition_complaint(
        first["id"], "UNSUBSTANTIATE", INSPECTOR,
        finding="No environmental link found",
    )
    assert read_complaint(first["id"])["status"] == "UNSUBSTANTIATED"

    second = validate_success(
        api.create_complaint(
            create_rwi_complaint_payload(
                ctx["facility_id"], 2, narrative="Two more swimmers ill",
                pathogen_suspected="GIARDIA",
            ),
            ANON,
        ),
        201,
    )

    assert second["risk_variant"] == "SINGLE_REPORT"
    assert second["cluster_case_count"] == 2
    assert second["risk_score"] == 44, "24 case points plus 20 for GIARDIA"
    assert second["escalated"] is False

    orders, meta = validate_paginated(
        api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
    )
    assert meta["total_count"] == 0 and orders == []


class TestSingleReportVersusClusterAggregate:
    """The same complaint body scores differently once a peer exists."""

    @staticmethod
    def _setup():
        ctx = setup_operator_and_pool()
        ctx["first"] = file_rwi_complaint(
            ctx["facility_id"], 2,
            narrative="Two swimmers hospitalised with pneumonia after the weekend",
            pathogen_suspected="LEGIONELLA",
        )
        return ctx

    def test_a_lone_illness_report_is_scored_as_a_single_report(self, api):
        """PRD 3.9: Finding no peer selects the **single-report** variant:
        `risk_variant` is `SINGLE_REPORT`, `cluster_case_count` is this
        complaint's own `illness_case_count`, and the pathogen pool holds only
        this complaint's `pathogen_suspected`.
        PRD 3.9: The **case component** is the cluster case count multiplied by
        12 points per case, capped at 60 points. The **pathogen component** is
        the greatest weight found anywhere in the pathogen pool, where the
        weights are 30 for `CRYPTOSPORIDIUM`, 20 for `GIARDIA`, 35 for
        `LEGIONELLA`, 15 for `PSEUDOMONAS`, 25 for `NOROVIRUS`, 25 for `ECOLI`
        and 5 for `UNKNOWN`, and a null suspected pathogen contributes a weight
        of 0. The **recency component** is 10 points when the number of days
        between `symptom_onset_date` and the date part of `reported_at` is at
        most 7, and 0 points otherwise. `risk_score` is the sum of the three
        components, capped at 100. `escalated` is true exactly when `risk_score`
        reaches or exceeds 60.

        Design: Difficulty/dual_variant_calc/complaint_rwi_single_report_vs_cluster_aggregate
        """
        ctx = self._setup()

        first = ctx["first"]
        assert first["risk_variant"] == "SINGLE_REPORT"
        assert first["cluster_case_count"] == 2
        assert first["risk_score"] == 59, "24 case points plus 35 for LEGIONELLA"
        assert first["escalated"] is False

        orders, meta = validate_paginated(
            api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert meta["total_count"] == 0 and orders == []

    def test_a_peer_report_flips_the_variant_and_crosses_the_threshold(self, api):
        """PRD 3.9: Finding at least one peer selects the **cluster-aggregate**
        variant: `risk_variant` is `CLUSTER_AGGREGATE`, `cluster_case_count` is
        this complaint's `illness_case_count` plus the sum of every peer's, and
        the pathogen pool holds this complaint's `pathogen_suspected` together
        with every peer's.
        PRD 3.9: When `escalated` comes out true, the system immediately opens a
        closure order for the facility in `OPEN` with `closure_reason` of
        `RWI_OUTBREAK`, `ordered_by_user_id` set to the literal string `system`
        and `ordered_by_role` of `system`, which drives the venue's
        `operating_posture` to `CLOSED` and bumps its `version`.

        Design: Difficulty/dual_variant_calc/complaint_rwi_single_report_vs_cluster_aggregate
        """
        ctx = self._setup()

        second = validate_success(
            api.create_complaint(
                create_rwi_complaint_payload(
                    ctx["facility_id"], 2,
                    narrative="Two more swimmers ill after the same weekend",
                    pathogen_suspected="GIARDIA",
                ),
                ANON,
            ),
            201,
        )

        assert second["risk_variant"] == "CLUSTER_AGGREGATE"
        assert second["cluster_case_count"] == 4
        assert second["risk_score"] == 83, (
            "48 case points plus the cluster's worst pathogen weight of 35"
        )
        assert second["escalated"] is True

        orders, meta = validate_paginated(
            api.list_closure_orders(ADMIN, params={"facility_id": ctx["facility_id"]})
        )
        assert meta["total_count"] == 1
        assert orders[0]["closure_reason"] == "RWI_OUTBREAK"
        assert orders[0]["status"] == "OPEN"

        assert_posture(
            read_facility(ctx["facility_id"]), "CLOSED", "CLOSURE_ORDER_OPEN"
        )


class TestEscalationThresholdBoundary:
    """Escalation compares with >= 60, so a score of exactly 60 escalates."""

    @staticmethod
    def _setup():
        return setup_operator_with_two_pools(
            operator_overrides={
                "legal_name": "Twin Pools Trust",
                "contact_email": "ops@twinpools.example",
            }
        )

    def test_a_score_of_exactly_sixty_escalates_and_closes_the_venue(self, api):
        """PRD 3.9: `escalated` is true exactly when `risk_score` reaches or
        exceeds 60.
        PRD 3.9: The **case component** is the cluster case count multiplied by
        12 points per case, capped at 60 points.
        PRD 3.9: When `escalated` comes out true, the system immediately opens a
        closure order for the facility in `OPEN` with `closure_reason` of
        `RWI_OUTBREAK`, `ordered_by_user_id` set to the literal string `system`
        and `ordered_by_role` of `system`, which drives the venue's
        `operating_posture` to `CLOSED` and bumps its `version`.

        Design: Difficulty/boundary_precision_check/rwi_risk_score_exactly_at_escalation_threshold_escalates
        """
        ctx = self._setup()

        at_threshold = validate_success(
            api.create_complaint(
                create_rwi_complaint_payload(
                    ctx["facility_a_id"], 5,
                    narrative=(
                        "Five swimmers reported diarrhoeal illness after a "
                        "birthday party"
                    ),
                ),
                ANON,
            ),
            201,
        )

        assert at_threshold["risk_score"] == 60, (
            "The case component caps at exactly 60; a null pathogen adds 0 and "
            "the 10-day onset gap earns no recency bonus"
        )
        assert at_threshold["escalated"] is True

        orders, meta = validate_paginated(
            api.list_closure_orders(
                ADMIN, params={"facility_id": ctx["facility_a_id"]}
            )
        )
        assert meta["total_count"] == 1
        assert orders[0]["closure_reason"] == "RWI_OUTBREAK"
        assert (
            read_facility(ctx["facility_a_id"])["posture_reason"]
            == "CLOSURE_ORDER_OPEN"
        )

    def test_a_score_of_fifty_nine_stops_one_point_short(self, api):
        """PRD 3.9: `escalated` is true exactly when `risk_score` reaches or
        exceeds 60.
        PRD 3.9: The **recency component** is 10 points when the number of days
        between `symptom_onset_date` and the date part of `reported_at` is at
        most 7, and 0 points otherwise.
        PRD 2.9: The facility has no permit records at all → `CLOSED` with reason
        `PERMIT_MISSING`.

        Design: Difficulty/boundary_precision_check/rwi_risk_score_exactly_at_escalation_threshold_escalates
        """
        ctx = self._setup()

        below_threshold = validate_success(
            api.create_complaint(
                create_rwi_complaint_payload(
                    ctx["facility_b_id"], 2,
                    narrative="Two swimmers reported respiratory illness",
                    pathogen_suspected="LEGIONELLA",
                ),
                ANON,
            ),
            201,
        )

        assert below_threshold["risk_score"] == 59
        assert below_threshold["escalated"] is False

        orders, meta = validate_paginated(
            api.list_closure_orders(
                ADMIN, params={"facility_id": ctx["facility_b_id"]}
            )
        )
        assert meta["total_count"] == 0 and orders == []
        assert_posture(
            read_facility(ctx["facility_b_id"]), "CLOSED", "PERMIT_MISSING"
        )
