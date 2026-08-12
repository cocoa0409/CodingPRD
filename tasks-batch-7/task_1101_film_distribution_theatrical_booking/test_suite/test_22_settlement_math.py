"""Settlement arithmetic: per-capita floor and locked-only input set (PRD §3.7)."""
from test_helpers import (
    validate_success,
    get_success_data,
    setup_in_play_agreement,
    file_and_submit_report,
    close_week,
    create_box_office_report_payload,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
EXHIBITOR = TEST_USERS["exhibitor_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def test_per_capita_floor_applies_when_higher_than_split(api):
    """PRD §3.7: "Sixth, the per-capita floor is the week's total `admissions`
    multiplied by `per_capita_floor_cents`. Seventh, `distributor_share_cents` is the
    greater of the pre-floor share and the per-capita floor."
    gross 100000 - house 50000 = net 50000; pre-floor share round(50000*0.60)=30000;
    per-capita floor 500*150=75000 -> distributor share 75000 (the floor binds and
    exceeds the net — the deliberate fiscal edge of PRD §3.7).

    Design: Corner/calculations/per_capita_floor_applies_when_higher_than_split
    """
    env = setup_in_play_agreement(
        theatre_overrides={"house_allowance_cents": 50000},
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
    file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 100000, 500)
    close_week(did)

    settlements = api.list_settlements(did, baid, CLERK).json()["data"]
    finals = [s for s in settlements if s.get("status") in ("PENDING_FINAL", "FINALIZED")]
    assert len(finals) >= 1, "Setup failed: no finalized settlement after close"
    f = finals[0]
    assert f["gross_cents"] == 100000, f"expected gross 100000, got {f['gross_cents']}"
    assert f["net_cents"] == 50000, f"expected net 50000, got {f['net_cents']}"
    assert f["distributor_share_cents"] == 75000, (
        f"per-capita floor 75000 must beat pre-floor share 30000; "
        f"got {f['distributor_share_cents']}"
    )


def test_final_settlement_input_set_excludes_draft_and_voided(api):
    """PRD §3.7: "The `FINAL` variant is the locked form: its gross sums `LOCKED`
    reports only".
    Week reports: R1 SUBMITTED 500000 (locks at the close), R2 DRAFT 300000, R3
    created then voided 100000 — only R1 counts toward the locked gross.

    Design: Corner/calculations/box_office_input_set_filtering_excludes_draft_and_voided
    """
    env = setup_in_play_agreement(
        booking_overrides={"min_weeks_committed": 1, "per_capita_floor_cents": 100}
    )
    did = env["distributor"]["id"]
    baid = env["booking"]["id"]
    r1 = file_and_submit_report(did, baid, "2026-05-01T00:00:00Z", 500000, 2000)
    get_success_data(api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=300000, admissions=1000
        ),
        EXHIBITOR,
    ))
    r3 = get_success_data(api.create_box_office_report(
        did, baid,
        create_box_office_report_payload(
            report_date="2026-05-01T00:00:00Z", gross_cents=100000, admissions=500
        ),
        EXHIBITOR,
    ))
    voided = validate_success(api.void_box_office_report(did, baid, r3["id"], EXHIBITOR), 200)
    assert voided["status"] == "VOIDED"

    close_week(did)

    r1_after = validate_success(api.get_box_office_report(did, baid, r1["id"], CLERK), 200)
    assert r1_after["status"] == "LOCKED", (
        f"the close must lock SUBMITTED reports, got {r1_after['status']}"
    )

    settlements = api.list_settlements(did, baid, CLERK).json()["data"]
    locked_based = [
        s for s in settlements
        if s.get("variant") == "FINAL"
        or s.get("status") in ("PENDING_FINAL", "FINALIZED", "SETTLED")
    ]
    assert len(locked_based) >= 1, "Setup failed: no locked-based settlement after close"
    f = locked_based[0]
    assert f["gross_cents"] == 500000, (
        f"locked gross must exclude the DRAFT (300000) and VOIDED (100000) reports; "
        f"expected 500000, got {f['gross_cents']}"
    )
