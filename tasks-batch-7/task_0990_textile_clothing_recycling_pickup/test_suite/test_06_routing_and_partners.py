"""Routing selector policy, partner capacity partition, quality-score variants,
quarantine/remediation, and the quarantine safety gate."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_partner_manager_headers,
    new_zone, new_resident, new_partner, new_dropbox, post_reading, collect_box,
    certify_ticket, run_selector, accept_assignment, decline_assignment,
    complete_assignment, file_report, adjudicate_report, set_clock,
    read_partner, read_dropbox,
    ctx_certified,
    assert_partner_capacity_partition,
)

OP = TEST_USERS["zone_operator_headers"]


def test_selector_tiebreak_then_decline_exclusion(api):
    """PRD §3.7: "Ranking is by `routing_score` descending, with ties broken by
    the partner's `created_at` ascending."
    PRD §3.7: "The partner declines an assignment by optionally supplying a
    `reason`; the assignment transitions from `PENDING` to `DECLINED` with the
    supplied reason persisted on `decline_reason`, and the partner is excluded
    from the selector pool on any subsequent routing attempt for the same ticket."

    Design: Corner/endpoints/selector_tiebreak_then_decline_exclusion
    """
    p1 = new_partner("First Thrift", "THRIFT", ["RESALE"], 1000)
    p2 = new_partner("Second Thrift", "THRIFT", ["RESALE"], 1000)
    ctx = ctx_certified(zone_name="Zone EP2", resident_name="Rae R", resident_email="rae@x.com",
                        certified_weight_kg=12.5, grade="RESALE")
    a1 = run_selector(ctx["ticket"]["id"])
    assert a1["partner_id"] == p1["id"], "score tie (100/100) resolves by earliest created_at"
    assert a1["assigned_weight_kg"] == pytest.approx(12.5)

    declined = decline_assignment(a1["id"], p1["id"], reason="truck full")
    assert declined["status"] == "DECLINED"

    a2 = run_selector(ctx["ticket"]["id"])
    assert a2["partner_id"] == p2["id"], "decliner is excluded from the retry pool"


def test_selector_capacity_filter_skips_earlier_partner(api):
    """PRD §3.7: "The eligible pool is then filtered to partners whose `status` is
    `ELIGIBLE`, whose `accepted_grades` — a non-empty subset of `RESALE`,
    `RECYCLE`, `FIBER` chosen at registration — contains the ticket's `grade`,
    whose `remaining_kg` (computed as `capacity_kg` minus `committed_kg` minus
    `completed_kg`) is at least the ticket's `certified_weight_kg`, and who do not
    already hold a `DECLINED` assignment for this ticket."

    Design: Corner/endpoints/selector_capacity_filter_skips_earlier_partner
    """
    p_small = new_partner("Small Thrift", "THRIFT", ["RESALE"], 10)
    p_big = new_partner("Big Brand", "BRAND", ["RESALE"], 1000)
    ctx = ctx_certified(zone_name="Zone EP3", resident_name="Sid S", resident_email="sid@x.com",
                        certified_weight_kg=12.5, grade="RESALE")

    a = run_selector(ctx["ticket"]["id"])
    assert a["partner_id"] == p_big["id"], (
        "remaining 10 kg < 12.5 kg fails eligibility despite earlier created_at"
    )


def test_second_pending_assignment_rejected(api):
    """PRD §3.7: "Only one in-flight assignment may exist for a ticket. If any
    `PENDING` or `ACCEPTED` assignment already exists for the ticket, creating a
    new one is rejected with `ERR_ASSIGNMENT_PENDING_EXISTS`; a `DECLINED` or
    `COMPLETED` assignment does not block a new attempt."

    Design: Corner/validations/second_pending_assignment_rejected
    """
    ctx = ctx_certified(zone_name="Zone V11", resident_name="Ora O", resident_email="ora@x.com",
                        partner={"name": "ThriftCo", "partner_type": "THRIFT",
                                 "accepted_grades": ["RESALE"], "capacity_kg": 1000})
    run_selector(ctx["ticket"]["id"])

    resp = api_client.create_routing_assignment(ctx["ticket"]["id"], OP)
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_PENDING_EXISTS)

    assignments, meta = validate_paginated(
        api_client.list_ticket_routing_assignments(ctx["ticket"]["id"], OP)
    )
    assert len(assignments) == 1 and meta["total_count"] == 1


class TestPartnerCapacityPartition:
    def test_accept_moves_weight_free_to_committed(self, api):
        """PRD §3.7: "On success the assignment transitions to `ACCEPTED` and the
        partner's `committed_kg` increases by `assigned_weight_kg`."
        PRD §3.7: "whose `remaining_kg` (computed as `capacity_kg` minus
        `committed_kg` minus `completed_kg`) is at least the ticket's
        `certified_weight_kg`"

        Design: Difficulty/compensating_invariant/partner_accept_complete_capacity_partition_invariant
        """
        ctx = ctx_certified(zone_name="Zone CI2", resident_name="Omar Ott", resident_email="omar@x.com",
                            certified_weight_kg=12.5, grade="RESALE",
                            partner={"name": "BrandBack", "partner_type": "BRAND",
                                     "accepted_grades": ["RESALE"], "capacity_kg": 1000})
        a = run_selector(ctx["ticket"]["id"])
        assert a["assigned_weight_kg"] == pytest.approx(12.5), "snapshot of certified weight"

        accepted = accept_assignment(a["id"], ctx["partner"]["id"])
        assert accepted["status"] == "ACCEPTED"
        partner = read_partner(ctx["partner"]["id"])
        assert partner["committed_kg"] == pytest.approx(12.5)
        assert partner["completed_kg"] == pytest.approx(0)
        assert partner["remaining_kg"] == pytest.approx(987.5)
        assert_partner_capacity_partition(partner)

    def test_complete_moves_weight_committed_to_completed(self, api):
        """PRD §3.7: "Later, when the partner confirms the material was received,
        the assignment transitions from `ACCEPTED` to `COMPLETED`, the partner's
        `committed_kg` decreases by `assigned_weight_kg`, and the partner's
        `completed_kg` increases by the same amount."

        Design: Difficulty/compensating_invariant/partner_accept_complete_capacity_partition_invariant
        """
        ctx = ctx_certified(zone_name="Zone CI2", resident_name="Omar Ott", resident_email="omar@x.com",
                            certified_weight_kg=12.5, grade="RESALE",
                            partner={"name": "BrandBack", "partner_type": "BRAND",
                                     "accepted_grades": ["RESALE"], "capacity_kg": 1000})
        a = run_selector(ctx["ticket"]["id"])
        accept_assignment(a["id"], ctx["partner"]["id"])

        completed = complete_assignment(a["id"], ctx["partner"]["id"])
        assert completed["status"] == "COMPLETED"
        partner = read_partner(ctx["partner"]["id"])
        assert partner["committed_kg"] == pytest.approx(0)
        assert partner["completed_kg"] == pytest.approx(12.5)
        assert partner["remaining_kg"] == pytest.approx(987.5), (
            "remaining_kg identical before and after the accept/complete pair"
        )
        assert_partner_capacity_partition(partner)


class TestPartnerScoreVariants:
    def _setup_completed_partner_with_major(self):
        ctx = ctx_certified(zone_name="Zone DV2", resident_name="Sam Sew", resident_email="sam@x.com",
                            kit_type="BIN", certified_weight_kg=12.5, grade="RESALE",
                            partner={"name": "ThriftCo", "partner_type": "THRIFT",
                                     "accepted_grades": ["RESALE", "RECYCLE"], "capacity_kg": 1000})
        a = run_selector(ctx["ticket"]["id"])
        assert a["partner_id"] == ctx["partner"]["id"]
        accept_assignment(a["id"], ctx["partner"]["id"])
        complete_assignment(a["id"], ctx["partner"]["id"])
        report = file_report(ctx["ticket"]["id"], "MAJOR", notes="damp load")
        adjudicate_report(report["id"], "UPHELD")
        return ctx

    def test_adjudication_day_both_scores_drop_by_15(self, api):
        """PRD §2.9: "Each report contributes a penalty keyed by `severity`: a
        `SEVERE` finding subtracts 20 points, a `MAJOR` finding subtracts 15
        points, and a `MINOR` finding subtracts 0 points."
        PRD §2.9: "Recomputation happens on three triggers: when a contamination
        report is adjudicated, every time the routing selector runs, and on a read
        of a partner record."

        Design: Difficulty/dual_variant_calc/partner_score_rolling_vs_decay
        """
        ctx = self._setup_completed_partner_with_major()
        partner = read_partner(ctx["partner"]["id"])
        assert partner["routing_score"] == 85, f"100 - 15 = 85, got {partner['routing_score']}"
        assert partner["report_score"] == pytest.approx(85.0, abs=0.01)
        assert partner["status"] == "ELIGIBLE"

    def test_forty_days_later_variants_diverge(self, api):
        """PRD §2.9: "The routing variant uses a rolling 30-day window: only
        reports whose `adjudicated_at` falls within the half-open interval
        starting thirty days before the current logical clock (inclusive) and
        ending at the current logical clock contribute; findings older than thirty
        days contribute zero, so a partner recovers fully once findings age out."
        PRD §2.9: "The reporting variant is decay-weighted across all time: every
        finding contributes forever, with its penalty halved every thirty days of
        age — the contribution is the penalty multiplied by one-half raised to the
        power of the finding's age in days divided by thirty — and the result is
        the greater of zero and one hundred minus that weighted sum, rounded
        half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/partner_score_rolling_vs_decay
        """
        ctx = self._setup_completed_partner_with_major()
        day0 = read_partner(ctx["partner"]["id"])
        assert day0["routing_score"] == 85 and day0["report_score"] == pytest.approx(85.0, abs=0.01)

        set_clock("2026-06-10T00:00:00Z")
        day40 = read_partner(ctx["partner"]["id"])
        assert day40["routing_score"] == 100, "finding aged out of the 30-day rolling window"
        # 100 - 15 * 0.5^(40/30) = 94.0473 -> 94.05
        assert day40["report_score"] == pytest.approx(94.05, abs=0.01), (
            f"decay-weighted variant keeps the finding: expected 94.05, got {day40['report_score']}"
        )
        assert day40["status"] == "ELIGIBLE", "score never fell below the floor and MAJOR never quarantines"


def test_partner_quarantine_remediate_lifts_to_eligible(api):
    """PRD §3.6: "Any partner holding an `ACCEPTED` or `COMPLETED` assignment on
    this ticket transitions to `QUARANTINED` from either `ELIGIBLE` or
    `SUSPENDED`."
    PRD §3.6: "A `ZoneOperator` must explicitly remediate the partner, which
    transitions the partner from `QUARANTINED` to `SUSPENDED`, then immediately
    recomputes the `routing_score`; if the recomputed score is at least 40, the
    partner continues in the same request from `SUSPENDED` to `ELIGIBLE`."

    Design: Corner/state_machines/partner_quarantine_remediate_lifts_to_eligible
    """
    ctx = ctx_certified(zone_name="Zone SM12", resident_name="Cleo C", resident_email="cleo@x.com",
                        certified_weight_kg=12.5, grade="RESALE",
                        partner={"name": "BrandBack", "partner_type": "BRAND",
                                 "accepted_grades": ["RESALE"], "capacity_kg": 1000})
    a = run_selector(ctx["ticket"]["id"])
    accept_assignment(a["id"], ctx["partner"]["id"])
    complete_assignment(a["id"], ctx["partner"]["id"])
    report = file_report(ctx["ticket"]["id"], "SEVERE")
    adjudicate_report(report["id"], "UPHELD")

    partner = read_partner(ctx["partner"]["id"])
    assert partner["status"] == "QUARANTINED"
    assert partner["routing_score"] == 80, f"100 - 20 = 80, got {partner['routing_score']}"

    remediated = validate_success(api_client.remediate_partner(ctx["partner"]["id"], OP))
    assert remediated["status"] == "ELIGIBLE", (
        "QUARANTINED -> SUSPENDED, then 80 >= 40 lifts to ELIGIBLE in the same request"
    )


def test_partner_score_floor_suspension_and_recovery(api):
    """PRD §2.9: "A partner whose recomputed `routing_score` falls below the floor
    of 40 transitions from `ELIGIBLE` to `SUSPENDED`; one whose score recovers to
    at least 40 transitions from `SUSPENDED` back to `ELIGIBLE`."
    PRD §3.7: "The selector first recomputes the `routing_score` of every partner
    and applies any resulting `ELIGIBLE ↔ SUSPENDED` transitions (per §2.9), so a
    partner whose findings have just aged out of the 30-day window may be
    reinstated, and one whose score has just dipped below the floor may be
    suspended."

    Design: Corner/state_machines/partner_score_floor_suspension_and_recovery
    """
    zone = new_zone("Zone SM13")
    partner = new_partner("ThriftCo", "THRIFT", ["RECYCLE"], 1000)
    box = new_dropbox(zone["id"], "Box-11", "Station")
    post_reading(box["id"], 90.0, "2026-05-01T06:00:00Z")
    ticket = collect_box(box["id"], 30.0)
    certify_ticket(ticket["id"], 30.0, "RECYCLE")
    a = run_selector(ticket["id"])
    assert a["partner_id"] == partner["id"]
    accept_assignment(a["id"], partner["id"])
    complete_assignment(a["id"], partner["id"])

    for _ in range(4):
        report = file_report(ticket["id"], "MAJOR")
        adjudicate_report(report["id"], "UPHELD")
    partner = read_partner(partner["id"])
    assert partner["routing_score"] == 40, f"100 - 4*15 = 40, got {partner['routing_score']}"
    assert partner["status"] == "ELIGIBLE", "the floor is strict: exactly 40 stays ELIGIBLE"

    report = file_report(ticket["id"], "MAJOR")
    adjudicate_report(report["id"], "UPHELD")
    partner = read_partner(partner["id"])
    assert partner["routing_score"] == 25, f"100 - 5*15 = 25, got {partner['routing_score']}"
    assert partner["status"] == "SUSPENDED"

    # 40 days later the findings age out; a selector run reinstates the partner.
    set_clock("2026-06-10T00:00:00Z")
    post_reading(box["id"], 90.0, "2026-06-10T06:00:00Z")
    assert read_dropbox(box["id"])["posture"] == "FULL_PENDING_COLLECTION"
    ticket2 = collect_box(box["id"], 25.0)
    certify_ticket(ticket2["id"], 25.0, "RECYCLE")
    a2 = run_selector(ticket2["id"])
    assert a2["partner_id"] == partner["id"], "selector recomputed 100 and reinstated the partner"

    partner = read_partner(partner["id"])
    assert partner["status"] == "ELIGIBLE"
    assert partner["routing_score"] == 100


class TestQuarantineSafetyGate:
    def test_quarantine_gate_beats_empty_pool_error(self, api):
        """PRD §2.11: "When multiple validation rules apply to a single request,
        the server evaluates them in a fixed priority order and surfaces only the
        first failure."
        PRD §3.6: "Creating a routing assignment or a diversion credit on a
        `QUARANTINED` ticket is rejected with `ERR_TICKET_QUARANTINED`; this gate
        sits logically after the broader state check that admitted `QUARANTINED`
        as a certified-equivalent state, and it exists so that the routing and
        credit creation flows can distinguish a certified ticket from a
        quarantined one."

        Design: Difficulty/priority_pair_validation_conflict/quarantined_ticket_routing_safety_beats_empty_pool
        """
        ctx = ctx_certified(zone_name="Zone PP2", resident_name="Hana Hoe",
                            resident_email="hana@x.com", certified_weight_kg=12.5,
                            grade="RESALE")
        report = file_report(ctx["ticket"]["id"], "SEVERE")
        adjudicate_report(report["id"], "UPHELD")
        # No partners exist at all: the empty-pool check would also fail.

        resp = api_client.create_routing_assignment(ctx["ticket"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_TICKET_QUARANTINED)

    def test_quarantine_gate_creates_no_assignment(self, api):
        """PRD §3.6: "Creating a routing assignment or a diversion credit on a
        `QUARANTINED` ticket is rejected with `ERR_TICKET_QUARANTINED`"
        PRD §3.7: "An empty pool is rejected with `ERR_NO_ELIGIBLE_PARTNER`
        (HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/quarantined_ticket_routing_safety_beats_empty_pool
        """
        ctx = ctx_certified(zone_name="Zone PP2", resident_name="Hana Hoe",
                            resident_email="hana@x.com", certified_weight_kg=12.5,
                            grade="RESALE")
        report = file_report(ctx["ticket"]["id"], "SEVERE")
        adjudicate_report(report["id"], "UPHELD")

        resp = api_client.create_routing_assignment(ctx["ticket"]["id"], OP)
        validate_error(resp, ApiErrorId.ERR_TICKET_QUARANTINED)

        assignments, meta = validate_paginated(
            api_client.list_ticket_routing_assignments(ctx["ticket"]["id"], OP)
        )
        assert assignments == [] and meta["total_count"] == 0, (
            "the rejected selector run must not persist an assignment"
        )
