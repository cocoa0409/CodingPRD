"""
Closure: the widest-reaching act of authority, four hops from finding to permit.

PRD §3.5: "Escalating to `CLOSE` is permitted from `restriction_action` `NONE` or
`RESTRICT`, and it additionally requires the finding's `severity` to be
`IMMEDIATE` ... Closure runs a four-hop cascade and is the widest-reaching act of
authority in the system."
"""

from test_helpers import assertions as a
from test_helpers import fixtures as fx

FIELD_DAY = "2026-09-02T12:00:00Z"


def _approved_permit_over_an_adequately_rated_structure(client, roster, bridge):
    """
    An approved boundary rating whose operating factor is exactly 1.000, an
    approved permit whose 36.0-ton load exactly matches the rating vehicle, and an
    `IMMEDIATE` finding still sitting `OPEN` on the same structure.
    """
    report = fx.accepted_report(client, bridge["id"], roster, qa_clock=FIELD_DAY)
    rating = fx.approved_rating(
        client,
        bridge["id"],
        roster,
        report["inspection"]["id"],
        dead_load_dc_kn_m=465.6,
        dead_load_dw_kn_m=33.5,
    )
    permit = fx.receive_permit(
        client,
        "OW-2026-0002",
        [bridge["id"]],
        axle_loads_tons=[10.0, 10.0, 10.0, 6.0],
    )
    fx.analyze_permit(client, permit["id"])
    fx.decide_permit(client, permit["id"], "APPROVE")
    finding = fx.raise_finding(
        client,
        roster,
        bridge["id"],
        report["inspection"]["id"],
        "IMMEDIATE",
        element_condition_id=report["elements"]["deck"]["id"],
    )
    return {"report": report, "rating": rating, "permit": permit, "finding": finding}


def test_the_route_is_permissible_before_any_authority_is_exercised(
    client, roster, bridge
):
    """
    The starting position: a structure rated exactly at the boundary, an analysis
    row that clears the adequate band, an approved permit and an open structure.

    PRD §3.7: "A factor of 1.000 or greater gives `analysis_result` `ALLOWED` with
    `result_reason` `RF_ADEQUATE`."
    PRD §3.4: "so the operating factor is exactly 1.000 and posting is **not**
    required, leaving `posted_limit_tons` null while `operating_rating_tons` reads
    36.0."

    Design: Difficulty/transitive_cascade/finding_closure_cascade_posture_permit_analysis_revocation
    """
    setup = _approved_permit_over_an_adequately_rated_structure(client, roster, bridge)

    analyses = fx.analyses_for_permit(client, setup["permit"]["id"])
    assert len(analyses) == 1
    assert analyses[0]["rating_factor_permit"] == 1.000
    assert analyses[0]["analysis_result"] == "ALLOWED"
    assert analyses[0]["result_reason"] == "RF_ADEQUATE"
    assert analyses[0]["sequence_index"] == 0

    permit = fx.read_permit(client, setup["permit"]["id"])
    assert permit["status"] == "APPROVED"
    assert permit["gross_weight_tons"] == 36.0
    assert permit["recommended_decision"] == "APPROVE"
    assert permit["revoked_at"] is None

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["service_posture"] == "OPEN"
    assert structure["posting_required"] is False
    assert structure["posted_limit_tons"] is None
    assert structure["inspection_interval_months"] == 12


def test_hop_one_records_the_closure_without_touching_the_lifecycle(
    client, roster, bridge
):
    """
    Closure writes only the authority dimension; the finding is still `OPEN`
    because nothing has been mitigated or resolved.

    PRD §3.5: "**Hop 1** sets `restriction_action` to `CLOSE`, records
    `restriction_authorized_by_id`, and stamps `restriction_imposed_at`."
    PRD §3.5: "The authorising engineer may not be the team leader of the source
    inspection — the segregation-of-duties rule again."

    Design: Difficulty/transitive_cascade/finding_closure_cascade_posture_permit_analysis_revocation
    """
    setup = _approved_permit_over_an_adequately_rated_structure(client, roster, bridge)

    closed = fx.impose(client, setup["finding"]["id"], roster, "CLOSE")

    assert closed["restriction_action"] == "CLOSE"
    assert closed["restriction_authorized_by_id"] == roster.district_id
    assert closed["finding_status"] == "OPEN"
    a.assert_instant_equals(
        closed["restriction_imposed_at"], FIELD_DAY, "restriction_imposed_at"
    )


def test_hop_two_closes_the_structure_and_tightens_its_cycle(client, roster, bridge):
    """
    The posture ladder puts the closure above everything else and the six-month
    posture floor takes over the inspection cycle.

    PRD §3.5: "**Hop 2**, caused by hop 1, sets the structure's `service_posture`
    to `CLOSED` — an `OPEN → CLOSED` move when no restriction was previously in
    force, or a `RESTRICTED → CLOSED` move when one was — takes its
    `inspection_interval_months` down to the smaller of its current interval and 6
    months, and increments its `version` by one."

    Design: Difficulty/transitive_cascade/finding_closure_cascade_posture_permit_analysis_revocation
    """
    setup = _approved_permit_over_an_adequately_rated_structure(client, roster, bridge)

    fx.impose(client, setup["finding"]["id"], roster, "CLOSE")

    structure = fx.read_bridge(client, bridge["id"])
    assert structure["service_posture"] == "CLOSED"
    assert structure["inspection_interval_months"] == 6
    a.assert_date_equals(
        structure["next_inspection_due_date"], "2027-03-02", "next_inspection_due_date"
    )


def test_hop_three_denies_the_analysis_row_without_erasing_its_factor(
    client, roster, bridge
):
    """
    The analysis row flips to denied on the closure reason while the rating factor
    it computed stays on the record — the arithmetic was never wrong, the
    structure simply became unavailable.

    PRD §3.5: "**Hop 3**, caused by the posture change in hop 2, reaches into the
    permit domain. Every per-bridge permit analysis row naming this structure whose
    parent permit application is in `ANALYZED`, `APPROVED` or
    `APPROVED_WITH_CONDITIONS` has its `analysis_result` set to `DENIED` and its
    `result_reason` set to `BRIDGE_CLOSED`."

    Design: Difficulty/transitive_cascade/finding_closure_cascade_posture_permit_analysis_revocation
    """
    setup = _approved_permit_over_an_adequately_rated_structure(client, roster, bridge)
    before = fx.analyses_for_permit(client, setup["permit"]["id"])[0]

    fx.impose(client, setup["finding"]["id"], roster, "CLOSE")

    after = fx.analyses_for_permit(client, setup["permit"]["id"])
    assert len(after) == 1, "the cascade flips the existing row, it does not add one"
    assert after[0]["id"] == before["id"]
    assert after[0]["analysis_result"] == "DENIED"
    assert after[0]["result_reason"] == "BRIDGE_CLOSED"
    assert after[0]["rating_factor_permit"] == 1.000


def test_hop_four_revokes_the_permit_and_the_rating_survives_untouched(
    client, roster, bridge
):
    """
    The re-aggregation sinks the whole route and revokes the approved permit,
    while the load rating that produced the numbers is not part of the cascade at
    all.

    PRD §3.5: "**Hop 4**, caused by those analysis flips, re-aggregates each
    affected application: its `recommended_decision` becomes `DENY` and its
    `governing_analysis_min_rf` is recomputed, and any such application that was in
    `APPROVED` or `APPROVED_WITH_CONDITIONS` transitions to `REVOKED` with
    `revoked_at` stamped from the logical clock."
    PRD §3.7: "the closure cascade of §3.5 drives it to `REVOKED` with `revoked_at`
    stamped, and `REVOKED` is terminal — reopening the structure does not restore
    the permit."

    Design: Difficulty/transitive_cascade/finding_closure_cascade_posture_permit_analysis_revocation
    """
    setup = _approved_permit_over_an_adequately_rated_structure(client, roster, bridge)

    fx.impose(client, setup["finding"]["id"], roster, "CLOSE")

    permit = fx.read_permit(client, setup["permit"]["id"])
    assert permit["status"] == "REVOKED"
    assert permit["recommended_decision"] == "DENY"
    a.assert_instant_equals(permit["revoked_at"], FIELD_DAY, "revoked_at")

    rating = fx.read_rating(client, setup["rating"]["id"])
    assert rating["rating_status"] == "APPROVED"
    assert rating["operating_rating_tons"] == 36.0
    assert rating["rating_factor_operating"] == 1.000
    assert rating["posting_required"] is False
