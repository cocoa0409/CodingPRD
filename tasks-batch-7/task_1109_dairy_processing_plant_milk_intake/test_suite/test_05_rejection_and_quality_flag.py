"""Rejection cascades: rolling rejection count, quality flag transitions, and
the PROBATION zero-premium consequence on settlements."""
from test_helpers import (
    TEST_USERS,
    get_producer,
    make_settlement,
    setup_intake_env,
    setup_producer_with_rejections,
    setup_rejected_receipt,
    setup_released_receipt,
    validate_success,
)

PC = TEST_USERS["plant_controller_headers"]


class TestRejectToProbationCascade:
    def test_two_rejections_drive_probation_and_zero_premium(self, api):
        """PRD §3.4: "Otherwise, if the count reaches or exceeds 2, the
        producer's `quality_flag` transitions to `PROBATION`." PRD §3.11: "The
        `over_order_premium_cents` is the total delivered hundredweight
        multiplied by a per-hundredweight tier that depends on the producer's
        `quality_flag`: 150 cents per hundredweight for `STANDARD`, 250 cents
        for `PREMIUM`, and 0 for `PROBATION`."

        Design: Difficulty/transitive_cascade/reject_to_probation_to_premium_loss_cascade
        """
        env = setup_intake_env(hauling_rate=100, pool=True)
        pid = env["producer"]["id"]
        setup_producer_with_rejections(pid, env["hauler"]["id"], 2)

        producer = get_producer(pid)
        assert producer["rolling_rejection_count_30d"] == 2
        assert producer["quality_flag"] == "PROBATION"

        # A released load gives the settlement nonzero delivered hundredweight,
        # so the PROBATION tier (0) is observable against a nonzero base.
        receipt = setup_released_receipt(
            pid, env["hauler"]["id"],
            gross=50000, tare=30000,
            arrived_at="2026-05-10T08:00:00Z",
            assay={},
        )
        assert receipt["net_weight_lbs"] == 20000  # 200 cwt

        res = api.create_settlement(
            pid,
            {"period_start_date": "2026-05-01T00:00:00Z",
             "period_end_date": "2026-05-31T23:59:59Z"},
            PC,
        )
        settlement = validate_success(res, 201)
        assert settlement["over_order_premium_cents"] == 0, (
            "PROBATION tier must zero the premium: 200 cwt x 0 cents/cwt"
        )

    def test_first_rejection_keeps_standard_flag(self, api):
        """PRD §3.4: "The producer's `rolling_rejection_count_30d` is recomputed
        as the count of this producer's receipts that entered `REJECTED` within
        the trailing 30-calendar-day window, inclusive of both endpoints of the
        window." PRD §3.4: "Otherwise, if the count is at least 1,
        `quality_flag` is `STANDARD`."

        Design: Difficulty/transitive_cascade/reject_to_probation_to_premium_loss_cascade
        """
        env = setup_intake_env()
        pid = env["producer"]["id"]
        setup_rejected_receipt(pid, env["hauler"]["id"], arrived_at="2026-05-05T08:00:00Z")

        producer = get_producer(pid)
        assert producer["rolling_rejection_count_30d"] == 1
        assert producer["quality_flag"] == "STANDARD"
        assert producer["status"] == "ACTIVE"


def test_probation_zeroes_over_order_premium(api):
    """PRD §3.11: "150 cents per hundredweight for `STANDARD`, 250 cents for
    `PREMIUM`, and 0 for `PROBATION`." PRD §3.4: "Otherwise, if the count
    reaches or exceeds 2, the producer's `quality_flag` transitions to
    `PROBATION`."

    Design: Corner/calculations/probation_flag_zeroes_over_order_premium
    """
    env = setup_intake_env(hauling_rate=100, pool=True)
    pid = env["producer"]["id"]
    setup_producer_with_rejections(pid, env["hauler"]["id"], 2)

    setup_released_receipt(
        pid, env["hauler"]["id"],
        gross=50000, tare=30000,
        arrived_at="2026-05-10T08:00:00Z",
        assay={},
    )
    settlement = make_settlement(pid)
    assert get_producer(pid)["quality_flag"] == "PROBATION"
    assert settlement["over_order_premium_cents"] == 0
