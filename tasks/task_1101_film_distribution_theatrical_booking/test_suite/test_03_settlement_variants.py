"""Dual settlement variants: provisional vs final (PRD §3.4, §3.7)."""
from test_helpers import (
    validate_success,
    get_success_data,
    setup_in_play_agreement,
    setup_distributor,
    setup_film,
    setup_theatre,
    setup_screen,
    setup_accepted_booking,
    file_and_submit_report,
    close_week,
    close_week_with_reports,
    create_box_office_report_payload,
    create_aggregate_deal_payload,
    create_dcp_shipment_payload,
    create_kdm_key_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def _provisional_records(api, did, baid):
    """Settlement records still carrying the forward-looking variant."""
    data = api.list_settlements(did, baid, CLERK).json()["data"]
    return [s for s in data if s.get("variant") == "PROVISIONAL" or s.get("status") == "PROVISIONAL"]


def _locked_based_records(api, did, baid):
    """Settlement records whose economics have been recomputed from LOCKED
    reports (the final-variant form, regardless of single- or dual-record
    implementations)."""
    data = api.list_settlements(did, baid, CLERK).json()["data"]
    return [
        s for s in data
        if s.get("variant") == "FINAL"
        or s.get("status") in ("PENDING_FINAL", "FINALIZED", "SETTLED", "DISPUTED", "WRITTEN_OFF")
    ]


def test_provisional_variant_includes_draft_and_submitted_reports(api):
    """PRD §3.7: "A `PROVISIONAL` variant is the forward-looking in-week preview: its
    gross sums reports in `DRAFT`, `SUBMITTED`, and `LOCKED` alike, and its house
    allowance is the plain per-theatre `house_allowance_cents` with no aggregate
    allocation."
    One SUBMITTED report (600000) plus one DRAFT report (400000) must give a
    provisional gross of 1000000.

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_draft_reports
    """
    env = setup_in_play_agreement(
        theatre_overrides={"house_allowance_cents": 100000},
        booking_overrides={
            "min_weeks_committed": 1,
            "week_one_rental_pct": 0.60,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
            "per_capita_floor_cents": 150,
        },
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 600000, 3000)
    get_success_data(api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=400000, admissions=1000
        ),
        EXHIBITOR,
    ))
    provisional = _provisional_records(api, did, baid)
    assert len(provisional) >= 1, "Setup failed: no provisional settlement found in-week"
    s = provisional[0]
    assert s["gross_cents"] == 1000000, (
        f"provisional gross must include DRAFT + SUBMITTED: expected 1000000, "
        f"got {s['gross_cents']}"
    )
    assert s["house_allowance_cents"] == 100000, (
        f"provisional house allowance must be the per-theatre value 100000, "
        f"got {s['house_allowance_cents']}"
    )


def test_provisional_share_applies_per_capita_floor(api):
    """PRD §3.7: "Sixth, the per-capita floor is the week's total `admissions` multiplied
    by `per_capita_floor_cents`. Seventh, `distributor_share_cents` is the greater of the
    pre-floor share and the per-capita floor."
    gross 1000000 - house 100000 = net 900000; pre-floor share round(900000*0.60)=540000;
    per-capita floor (3000+1000)*150 = 600000 -> distributor share 600000.

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_draft_reports
    """
    env = setup_in_play_agreement(
        theatre_overrides={"house_allowance_cents": 100000},
        booking_overrides={
            "min_weeks_committed": 1,
            "week_one_rental_pct": 0.60,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
            "per_capita_floor_cents": 150,
        },
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 600000, 3000)
    get_success_data(api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=400000, admissions=1000
        ),
        EXHIBITOR,
    ))
    provisional = _provisional_records(api, did, baid)
    assert len(provisional) >= 1, "Setup failed: no provisional settlement found in-week"
    s = provisional[0]
    assert s["gross_cents"] == 1000000
    assert s["distributor_share_cents"] == 600000, (
        f"per-capita floor (600000) must beat pre-floor share (540000); "
        f"got {s['distributor_share_cents']}"
    )


def test_final_variant_excludes_draft_reports_and_diverges(api):
    """PRD §3.7: "The `FINAL` variant is the locked form: its gross sums `LOCKED` reports
    only, and an active aggregate deal's allowance is split per screen as described in
    §3.4."
    After the weekly close the DRAFT report (400000) is excluded: gross 600000,
    net 500000, pre-floor share round(500000*0.60)=300000, per-capita floor
    3000*150=450000 -> final distributor share 450000, diverging from the provisional
    600000.

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverge_on_draft_reports
    """
    env = setup_in_play_agreement(
        theatre_overrides={"house_allowance_cents": 100000},
        booking_overrides={
            "min_weeks_committed": 1,
            "week_one_rental_pct": 0.60,
            "rental_decay_per_week": 0.05,
            "floor_pct": 0.30,
            "per_capita_floor_cents": 150,
        },
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 600000, 3000)
    get_success_data(api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=400000, admissions=1000
        ),
        EXHIBITOR,
    ))
    provisional = _provisional_records(api, did, baid)
    assert len(provisional) >= 1, "Setup failed: no provisional settlement found in-week"
    provisional_share = provisional[0]["distributor_share_cents"]

    close_week(did)
    finals = _locked_based_records(api, did, baid)
    assert len(finals) >= 1, "Setup failed: no locked-based settlement after close"
    f = finals[0]
    assert f["gross_cents"] == 600000, (
        f"final gross must count LOCKED reports only: expected 600000, got {f['gross_cents']}"
    )
    assert f["distributor_share_cents"] == 450000, (
        f"final share: net 500000, pre-floor 300000, per-capita 450000; "
        f"got {f['distributor_share_cents']}"
    )
    assert provisional_share != f["distributor_share_cents"], (
        "provisional and final variants must diverge when a DRAFT report is excluded"
    )


def _setup_aggregate_pair_in_play(api):
    """Two Alamo theatres, both agreements accepted into an ACTIVE aggregate deal
    (0.50 flat, aggregate house allowance 200000 across 2 screens) and walked
    through the print pipeline to IN_PLAY."""
    distributor = setup_distributor()
    did = distributor["id"]
    film = setup_film(did)
    t1 = setup_theatre(did, name="T1", circuit="Alamo", house_allowance_cents=80000)
    t2 = setup_theatre(did, name="T2", circuit="Alamo", house_allowance_cents=80000)
    s1 = setup_screen(did, t1["id"], auditorium_label="A1")
    s2 = setup_screen(did, t2["id"], auditorium_label="A1")
    deal = get_success_data(api.create_aggregate_deal(
        did,
        create_aggregate_deal_payload(
            film["id"], circuit="Alamo", aggregate_rental_pct=0.50,
            min_screens=2, aggregate_house_allowance_cents=200000,
        ),
        BOOKER,
    ))
    ba1 = setup_accepted_booking(
        did, film["id"], t1["id"], s1["id"],
        week_one_rental_pct=0.60, rental_decay_per_week=0.05, floor_pct=0.30,
        per_capita_floor_cents=100, aggregate_deal_id=deal["id"],
    )
    ba2 = setup_accepted_booking(
        did, film["id"], t2["id"], s2["id"],
        week_one_rental_pct=0.60, rental_decay_per_week=0.05, floor_pct=0.30,
        per_capita_floor_cents=100, aggregate_deal_id=deal["id"],
    )
    deal = validate_success(api.activate_aggregate_deal(did, deal["id"], BOOKER), 200)
    assert deal["deal_status"] == "ACTIVE"
    for i, ba in enumerate((ba1, ba2)):
        ship = get_success_data(api.create_dcp_shipment(
            did, ba["id"],
            create_dcp_shipment_payload(tracking_number=f"TN-AGG-{i}"),
            BOOKER,
        ))
        get_success_data(api.mark_dcp_delivered(did, ba["id"], ship["id"], EXHIBITOR))
        get_success_data(api.create_kdm_key(
            did, ba["id"],
            create_kdm_key_payload(screen_cert_fingerprint=f"FP-AGG-{i}"),
            BOOKER,
        ))
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-01T00:00:00Z"}, ADMIN))
    out = []
    for ba in (ba1, ba2):
        live = validate_success(api.get_booking_agreement(did, ba["id"], BOOKER), 200)
        assert live["deal_status"] == "IN_PLAY", (
            f"Setup failed: expected IN_PLAY, got {live['deal_status']}"
        )
        out.append(live)
    return distributor, film, out[0], out[1]


def test_provisional_uses_per_theatre_allowance_not_aggregate_split(api):
    """PRD §3.4: "The aggregate split applies only to final settlements; provisional
    estimates continue to use the plain per-theatre allowance (§3.7)."
    PRD §3.7: "its house allowance is the plain per-theatre `house_allowance_cents`
    with no aggregate allocation."

    Design: Difficulty/dual_variant_calc/coop_accrual_provisional_vs_final_aggregate_house_allowance_split
    """
    distributor, film, ba1, ba2 = _setup_aggregate_pair_in_play(api)
    did = distributor["id"]
    file_and_submit_report(did, ba1["id"], "2026-05-01T00:00:00Z", 500000, 2000)
    provisional = _provisional_records(api, did, ba1["id"])
    assert len(provisional) >= 1, "Setup failed: no provisional settlement found in-week"
    assert provisional[0]["house_allowance_cents"] == 80000, (
        f"provisional must use the per-theatre allowance 80000, not the aggregate "
        f"split 100000; got {provisional[0]['house_allowance_cents']}"
    )


def test_final_settlement_splits_aggregate_allowance_and_applies_flat_pct(api):
    """PRD §3.4: "instead of each theatre's own weekly allowance, the circuit-wide
    `aggregate_house_allowance_cents` is divided equally across the participating
    accepted agreements, and when the division is not exact the remainder cents go to
    the screen whose agreement has the earliest `created_at`."
    PRD §3.4: "The effective rental percentage is simply `aggregate_rental_pct` — flat,
    with no weekly decay and no floor".
    Aggregate 200000 across 2 participating agreements -> 100000 house each;
    net 500000 - 100000 = 400000; share round(400000 * 0.50) = 200000.

    Design: Difficulty/dual_variant_calc/coop_accrual_provisional_vs_final_aggregate_house_allowance_split
    """
    distributor, film, ba1, ba2 = _setup_aggregate_pair_in_play(api)
    did = distributor["id"]
    close_week_with_reports(
        did, 0, [(ba1["id"], 500000, 2000), (ba2["id"], 500000, 2000)]
    )
    finals = _locked_based_records(api, did, ba1["id"])
    assert len(finals) >= 1, "Setup failed: no locked-based settlement after close"
    f = finals[0]
    assert f["house_allowance_cents"] == 100000, (
        f"final must split aggregate 200000 across 2 screens: expected 100000, "
        f"got {f['house_allowance_cents']}"
    )
    assert f["rental_pct_applied"] == 0.50, (
        f"aggregate flat pct must apply (ignoring 0.60/decay/floor); "
        f"got {f['rental_pct_applied']}"
    )
    assert f["net_cents"] == 400000, f"expected net 400000, got {f['net_cents']}"
    assert f["distributor_share_cents"] == 200000, (
        f"expected share round(400000*0.50)=200000, got {f['distributor_share_cents']}"
    )
