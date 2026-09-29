"""Two boundaries probed at the exact value that decides the outcome.

The first is the inquiry-velocity count, probed one below the threshold and on it; the
second is the cardinality of a reserve basis, probed at its degenerate value of zero.
"""

from test_helpers import expected_inquiry_drain_score
from test_helpers.constants import CLOCK_ORIGIN
from test_helpers.fixtures import (
    create_rack,
    create_store,
    funded_physical_card,
    inquire,
    list_data_and_meta,
    open_period,
    parse_instant,
    read_card,
    read_exposure_summary,
    read_period,
    close_period,
    total_count,
)
from test_helpers.test_users import (
    make_fraud_analyst_headers,
    make_platform_admin_headers,
    make_reseller_partner_headers,
    make_risk_manager_headers,
)


class TestInquiryVelocityBoundary:
    """"A breach occurs when that count is at or above inquiry_velocity_threshold — at
    exactly the threshold, never one below it"."""

    def _card(self, client):
        """A 10000-cent card with no redemptions, so "recent_redemption_count is not an
        input at all" to the inquiry-weighted score and the drawdown term is zero."""
        store = create_store(client, name="Beltway Convenience", region_code="SE", address_line="410 Beltway Cir")
        rack = create_rack(client, store["id"], rack_label="RACK-B1", expected_card_count=9)
        built = funded_physical_card(client, 10000, store=store, rack=rack)
        return built["card"]["id"]

    def _four_inquiries(self, client, card_id):
        partner = make_reseller_partner_headers("partner-8")
        rows = []
        for channel, ip_hash in (("IVR", "iph-1"), ("IVR", "iph-1"), ("WEB", "iph-2"), ("WEB", "iph-2")):
            rows.append(inquire(client, card_id, channel, headers=partner, requester_ip_hash=ip_hash))
        return rows

    def test_one_below_the_threshold_raises_no_alert(self, client):
        """The clock is never moved, so all four inquiries sit inside the trailing window
        and the fourth records a count of 4 — below the threshold of 5 — with no alert.

        Design: Difficulty/boundary_precision_check/inquiry_velocity_alert_fires_exactly_at_fifth_inquiry
        """
        card_id = self._card(client)

        rows = self._four_inquiries(client, card_id)

        assert rows[3]["velocity_count_at_inquiry"] == 4
        assert rows[3]["drain_score_at_inquiry"] == 48
        assert rows[3]["drain_score_at_inquiry"] == expected_inquiry_drain_score(4, 0.0, 0)
        alerts = client.list_draining_alerts(make_fraud_analyst_headers("analyst-8"), {"card_id": card_id})
        assert total_count(alerts) == 0

    def test_the_posture_ladder_still_moves_below_the_velocity_boundary(self, client):
        """"a score exactly on the watch threshold escalates a CLEAR card to WATCH while one
        point below it does not" — 36 at the third inquiry is under the watch threshold of
        40 and 48 at the fourth is over it.

        Design: Difficulty/boundary_precision_check/inquiry_velocity_alert_fires_exactly_at_fifth_inquiry
        """
        card_id = self._card(client)

        rows = self._four_inquiries(client, card_id)

        assert rows[2]["drain_score_at_inquiry"] == 36
        assert rows[3]["drain_score_at_inquiry"] == 48
        assert read_card(client, card_id)["risk_posture"] == "WATCH"

    def test_the_fifth_inquiry_breaches_and_fires_exactly_one_open_alert(self, client):
        """"On breach the handler raises a draining alert on the card automatically, with a
        detection basis of INQUIRY_VELOCITY and an initial state of OPEN, copying
        velocity_count_at_inquiry into the alert's basis_velocity_count."

        Design: Difficulty/boundary_precision_check/inquiry_velocity_alert_fires_exactly_at_fifth_inquiry
        """
        card_id = self._card(client)
        self._four_inquiries(client, card_id)
        analyst = make_fraud_analyst_headers("analyst-8")

        fifth = inquire(client, card_id, "WEB", headers=analyst, requester_ip_hash="iph-3")

        assert fifth["velocity_count_at_inquiry"] == 5
        assert fifth["drain_score_at_inquiry"] == 60
        assert fifth["balance_disclosed_cents"] == 10000
        alerts, meta = list_data_and_meta(
            client.list_draining_alerts(analyst, {"card_id": card_id})
        )
        assert meta["total_count"] == 1
        assert alerts[0]["state"] == "OPEN"
        assert alerts[0]["detection_basis"] == "INQUIRY_VELOCITY"
        assert alerts[0]["basis_velocity_count"] == 5
        assert alerts[0]["exposure_cents"] == 10000
        assert alerts[0]["reopen_count"] == 0

    def test_the_breach_forces_restricted_even_below_the_restrict_threshold(self, client):
        """"If an inquiry velocity breach just occurred, the target is RESTRICTED — the
        velocity breach alone forces that rung no matter how low the score is", and the log
        reads "in occurred_at ascending order".

        Design: Difficulty/boundary_precision_check/inquiry_velocity_alert_fires_exactly_at_fifth_inquiry
        """
        card_id = self._card(client)
        self._four_inquiries(client, card_id)

        inquire(client, card_id, "WEB", headers=make_fraud_analyst_headers("analyst-8"), requester_ip_hash="iph-3")

        card = read_card(client, card_id)
        assert card["drain_risk_score_inquiry"] == 60
        assert card["risk_posture"] == "RESTRICTED"
        rows, meta = list_data_and_meta(
            client.list_balance_inquiries(card_id, make_platform_admin_headers())
        )
        assert meta["total_count"] == 5
        assert [row["velocity_count_at_inquiry"] for row in rows] == [1, 2, 3, 4, 5]


class TestEmptyReserveBasis:
    """"A period with no in-period alerts closes with a gross exposure of 0, a basis count
    of 0 and a reserve of 0 — zero, not empty, and certainly not an error"."""

    def _world(self, client):
        """A single 7500-cent funded card and one OPEN period, with no alerts anywhere."""
        store = create_store(client, name="Quiet Corner Store", region_code="NE", address_line="3 Quiet Corner")
        rack = create_rack(client, store["id"], rack_label="RACK-Q1", expected_card_count=4)
        funded_physical_card(client, 7500, store=store, rack=rack)
        period = open_period(client, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", label="2026-08-quiet")
        return period

    def test_closing_on_an_empty_basis_books_an_integer_zero_reserve(self, client):
        """"The basis is the set of draining alerts whose created_at falls inside the
        period's half-open span and whose state is OPEN, TRIAGED or CONFIRMED", and an
        empty basis yields "a gross exposure of 0, a basis count of 0 and a reserve of 0".

        Design: Difficulty/boundary_precision_check/empty_alert_set_yields_zero_reserve_at_period_close
        """
        period = self._world(client)
        assert period["state"] == "OPEN"
        assert total_count(client.list_draining_alerts(make_risk_manager_headers("risk-9"))) == 0

        closed = close_period(client, period["id"], close_note="clean month, no fraud alerts")

        assert closed["state"] == "CLOSED"
        assert closed["gross_exposure_cents"] == 0
        assert closed["reserve_basis_alert_count"] == 0
        assert closed["provisional_reserve_cents"] == 0
        assert closed["unauthorized_writeoff_cents"] == 0

    def test_the_final_reserve_stays_empty_until_a_restatement(self, client):
        """A new period is created with "final_reserve_cents ... empty", and only restating
        "books the final reserve on the settled basis", so a merely closed period has none.

        Design: Difficulty/boundary_precision_check/empty_alert_set_yields_zero_reserve_at_period_close
        """
        period = self._world(client)

        close_period(client, period["id"], close_note="clean month, no fraud alerts")

        stored = read_period(client, period["id"])
        assert not stored["final_reserve_cents"]
        assert parse_instant(stored["closed_at"]) == parse_instant(CLOCK_ORIGIN)

    def test_the_zero_reserve_was_not_derived_from_the_outstanding_liability(self, client):
        """"Closing also refreshes outstanding_liability_cents, which is alert-independent:
        the sum of current_balance_cents over every gift card whose activation_state is
        ACTIVE or DEPLETED" — 7500 here, while the alert-driven reserve is 0.

        Design: Difficulty/boundary_precision_check/empty_alert_set_yields_zero_reserve_at_period_close
        """
        period = self._world(client)

        closed = close_period(client, period["id"], close_note="clean month, no fraud alerts")

        assert closed["outstanding_liability_cents"] == 7500
        assert closed["provisional_reserve_cents"] == 0
        summary = read_exposure_summary(client, period["id"])
        assert summary["net_funded_liability_cents"] == 7500
        assert summary["in_period_alert_count"] == 0
        assert summary["confirmed_alert_count"] == 0
