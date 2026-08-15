"""Participant lifecycle: reservation gating (queue A cross-entity), withdrawal
/ expiry cascades, graduation path and preconditions (queue B)."""
from datetime import datetime, timezone

from test_helpers import (
    api_client, validate_success, validate_error,
    make_participant, make_ready_bike, make_hours_met_participant,
    make_helmet_part, restock_part, set_clock, log_hours, approve_log,
    TEST_USERS, make_participant_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _instant(iso: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp to an aware datetime (format-agnostic).

    PRD §2.4 pins three fractional digits only for created_at/updated_at;
    clock-stamped fields such as graduated_at are compared by instant.
    """
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def _graduate_helmet(participant_id: str):
    hp = make_helmet_part(name="Helmet Grad", helmet_size="S", unit_cost_cents=1200)
    restock_part(hp["id"], 2)
    return validate_success(
        api_client.create_helmet_distribution(
            {
                "helmet_part_id": hp["id"],
                "recipient_kind": "EARN_A_BIKE_GRADUATE",
                "participant_id": participant_id,
            },
            COORD,
        ),
        expected_status=201,
    )


class TestReserveBlockedBeforeHoursMet:
    def test_reserve_before_hours_met_rejected(self):
        """PRD §3.8: "Reservation requires the participant to be exactly
        `HOURS_MET` (else `ERR_HOURS_NOT_MET`)".

        Design: Difficulty/cross_entity_state_dependency/reserve_blocked_before_hours_met
        """
        p = make_participant(full_name="P E", contact_email="pe@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 6, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 5, "SHOP_HELP")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        # 11 < 12: still ENROLLED
        bike, _, _, _ = make_ready_bike(bike_type="ROAD", grade="A")
        r = api_client.reserve_bike(
            p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
        )
        validate_error(r, ApiErrorId.ERR_HOURS_NOT_MET)

    def test_reserve_before_hours_met_leaves_bike_ready(self):
        """PRD §3.8: "Reservation requires the participant to be exactly
        `HOURS_MET` (else `ERR_HOURS_NOT_MET`), to hold no existing reservation
        (else `ERR_RESERVATION_EXISTS`), and to name a `bike_id` currently
        `READY_FOR_DISPOSITION` (else `ERR_BIKE_NOT_AVAILABLE`)."

        Design: Difficulty/cross_entity_state_dependency/reserve_blocked_before_hours_met
        """
        p = make_participant(full_name="P E2", contact_email="pe2@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 6, "REFURB_WORK")
        approve_log(h1["id"], p["id"])
        bike, _, _, _ = make_ready_bike(bike_type="ROAD", grade="A")
        r = api_client.reserve_bike(
            p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
        )
        validate_error(r, ApiErrorId.ERR_HOURS_NOT_MET)
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"
        p_after = validate_success(api_client.get_participant(p["id"], COORD))
        assert p_after["reserved_bike_id"] is None


class TestSaleCompleteBlockedWhenBikeReserved:
    def _setup_pending_sale_and_reserved(self):
        p, _ = make_hours_met_participant("ADULT")
        bike, _, _, _ = make_ready_bike(bike_type="HYBRID", grade="B",
                                        part_unit_cost_cents=300)
        sale = validate_success(
            api_client.create_sale(
                {"bike_id": bike["id"], "buyer_name": "B X", "buyer_email": "bx@x.org"},
                COORD,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.reserve_bike(
                p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
            )
        )
        return p, bike, sale

    def test_complete_fails_with_bike_not_available(self):
        """PRD §3.9: "Completion requires the sale still `PENDING` (else
        `ERR_SALE_NOT_PENDING`), the bike still `READY_FOR_DISPOSITION` (else
        `ERR_BIKE_NOT_AVAILABLE`)".

        Design: Difficulty/cross_entity_state_dependency/sale_complete_blocked_when_bike_reserved
        """
        p, bike, sale = self._setup_pending_sale_and_reserved()
        r = api_client.complete_sale(sale["id"], {"payment_method": "CASH"}, COORD)
        validate_error(r, ApiErrorId.ERR_BIKE_NOT_AVAILABLE)

    def test_failed_complete_leaves_sale_and_reservation_untouched(self):
        """PRD §3.8: "Success moves the bike `READY_FOR_DISPOSITION →
        RESERVED_FOR_GRADUATE`, stamps the participant's `reserved_bike_id`,
        and bumps both records' versions." and PRD §3.9: "The new sale is
        `PENDING`".

        Design: Difficulty/cross_entity_state_dependency/sale_complete_blocked_when_bike_reserved
        """
        p, bike, sale = self._setup_pending_sale_and_reserved()
        api_client.complete_sale(sale["id"], {"payment_method": "CASH"}, COORD)
        sale_after = validate_success(api_client.get_sale(sale["id"], COORD))
        assert sale_after["status"] == "PENDING"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "RESERVED_FOR_GRADUATE"
        p_after = validate_success(api_client.get_participant(p["id"], COORD))
        assert p_after["reserved_bike_id"] == bike["id"]


class TestSaleVoid:
    def test_sale_void_leaves_bike_ready_and_seals_sale(self):
        """PRD §3.9: "Voiding a sale is a director's action against a `PENDING`
        sale (anything else is `ERR_SALE_NOT_PENDING`), records an optional
        `reason`, and flips the sale to `VOIDED`. The bike was never
        transitioned by the pending sale, so it stays `READY_FOR_DISPOSITION`".

        Design: Corner/state_machines/sale_void_leaves_bike_ready_and_seals_sale
        """
        bike, _, _, _ = make_ready_bike(bike_type="BMX", grade="A",
                                        part_unit_cost_cents=150)
        sale = validate_success(
            api_client.create_sale(
                {"bike_id": bike["id"], "buyer_name": "B V", "buyer_email": "bv@x.org"},
                COORD,
            ),
            expected_status=201,
        )
        voided = validate_success(
            api_client.void_sale(sale["id"], {"reason": "buyer walked"}, DIRECTOR)
        )
        assert voided["status"] == "VOIDED"
        r = api_client.complete_sale(sale["id"], {"payment_method": "CASH"}, COORD)
        validate_error(r, ApiErrorId.ERR_SALE_NOT_PENDING)
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"


class TestWithdrawAndExpiry:
    def test_withdraw_releases_reserved_bike(self):
        """PRD §3.8: "Withdrawal is available from either `ENROLLED` or
        `HOURS_MET` — from any other status it is rejected with
        `ERR_INVALID_STATE` — and moves the participant to `WITHDRAWN`,
        releasing any reserved bike as above." and PRD §3.7: "The participant
        must be `ENROLLED` or `HOURS_MET` at logging time, else
        `ERR_PARTICIPANT_NOT_ACTIVE`."

        Design: Corner/state_machines/withdraw_releases_reserved_bike
        """
        p, _ = make_hours_met_participant("ADULT")
        bike, _, _, _ = make_ready_bike(bike_type="MTB", grade="C",
                                        part_unit_cost_cents=100)
        validate_success(
            api_client.reserve_bike(
                p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
            )
        )
        withdrawn = validate_success(
            api_client.withdraw_participant(p["id"], make_participant_headers(p["id"]))
        )
        assert withdrawn["status"] == "WITHDRAWN"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"
        r = api_client.create_hour_log(
            p["id"],
            {"work_date": "2026-08-04", "hours": 2, "activity_type": "OUTREACH"},
            make_participant_headers(p["id"]),
        )
        validate_error(r, ApiErrorId.ERR_PARTICIPANT_NOT_ACTIVE)

    def test_participant_expiry_releases_reserved_bike(self):
        """PRD §3.8: "The ops sweep moves an `ENROLLED` or `HOURS_MET`
        participant to `EXPIRED` once the logical clock passes
        `enrollment_deadline`, applying the same bike-release cascade." and PRD
        §3.7: "an `enrollment_deadline` exactly 90 days after enrollment".

        Design: Corner/state_machines/participant_expiry_releases_reserved_bike
        """
        # enrolled at the default clock 2026-08-01 -> deadline 2026-10-30
        p = make_participant(full_name="P EX", contact_email="pex@x.org",
                             age_group="ADULT")
        set_clock("2026-08-07T00:00:00Z")
        h1 = log_hours(p["id"], "2026-08-02", 6, "REFURB_WORK")
        h2 = log_hours(p["id"], "2026-08-03", 6, "SHOP_HELP")
        approve_log(h1["id"], p["id"])
        approve_log(h2["id"], p["id"])
        bike, _, _, _ = make_ready_bike(bike_type="HYBRID", grade="B",
                                        part_unit_cost_cents=250)
        validate_success(
            api_client.reserve_bike(
                p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
            )
        )
        set_clock("2026-10-31T00:00:00Z")
        sweep = validate_success(api_client.run_sweep(COORD))
        assert sweep["participants_expired"] == 1
        p_after = validate_success(api_client.get_participant(p["id"], COORD))
        assert p_after["status"] == "EXPIRED"
        assert p_after["reserved_bike_id"] is None
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"


class TestGraduation:
    def test_graduation_happy_path(self):
        """PRD §3.8: "Graduation moves the participant `HOURS_MET → GRADUATED`,
        stamps `graduated_at` from the logical clock, moves the reserved bike
        `RESERVED_FOR_GRADUATE → GIFTED`, and bumps both records."

        Design: Corner/state_machines/graduation_happy_path
        """
        p, _ = make_hours_met_participant("ADULT")
        bike, _, _, _ = make_ready_bike(bike_type="ROAD", grade="A",
                                        part_unit_cost_cents=400)
        validate_success(
            api_client.reserve_bike(
                p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
            )
        )
        validate_success(
            api_client.record_quiz(p["id"], {"passed": True}, COORD)
        )
        _graduate_helmet(p["id"])
        graduated = validate_success(api_client.graduate_participant(p["id"], DIRECTOR))
        assert graduated["status"] == "GRADUATED"
        assert _instant(graduated["graduated_at"]) == _instant("2026-08-07T00:00:00Z")
        assert graduated["hours_earned"] == 12
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "GIFTED"

    def test_graduate_without_bike_returns_no_bike_reserved(self):
        """PRD §3.8: "to hold a reserved bike (else `ERR_NO_BIKE_RESERVED`)".

        Design: Corner/validations/graduate_without_bike_returns_no_bike_reserved
        """
        p, _ = make_hours_met_participant("YOUTH")
        validate_success(api_client.record_quiz(p["id"], {"passed": True}, COORD))
        _graduate_helmet(p["id"])
        r = api_client.graduate_participant(p["id"], DIRECTOR)
        validate_error(r, ApiErrorId.ERR_NO_BIKE_RESERVED)
        p_after = validate_success(api_client.get_participant(p["id"], COORD))
        assert p_after["status"] == "HOURS_MET"

    def test_graduate_requires_quiz(self):
        """PRD §3.8: "to have `safety_quiz_passed` set true — a coordinator
        records quiz outcomes through the quiz-recording action, whose `passed`
        input stamps the flag and bumps the participant's `version` — else
        `ERR_QUIZ_NOT_PASSED`".

        Design: Corner/validations/graduate_requires_quiz
        """
        p, _ = make_hours_met_participant("YOUTH")
        bike, _, _, _ = make_ready_bike(bike_type="KIDS", grade="B",
                                        part_unit_cost_cents=80,
                                        wheel_size_inches=20)
        validate_success(
            api_client.reserve_bike(
                p["id"], {"bike_id": bike["id"]}, make_participant_headers(p["id"])
            )
        )
        _graduate_helmet(p["id"])
        r = api_client.graduate_participant(p["id"], DIRECTOR)
        validate_error(r, ApiErrorId.ERR_QUIZ_NOT_PASSED)
        p_after = validate_success(api_client.get_participant(p["id"], COORD))
        assert p_after["status"] == "HOURS_MET"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "RESERVED_FOR_GRADUATE"

    def test_second_reservation_rejected(self):
        """PRD §3.8: "to hold no existing reservation (else
        `ERR_RESERVATION_EXISTS`)".

        Design: Corner/validations/second_reservation_rejected
        """
        p, _ = make_hours_met_participant("ADULT")
        bike1, part, lead, insp = make_ready_bike(bike_type="ROAD", grade="A")
        # second READY bike via same lead/inspector — build with shared part
        bike2, _, _, _ = make_ready_bike(bike_type="MTB", grade="B")
        first = validate_success(
            api_client.reserve_bike(
                p["id"], {"bike_id": bike1["id"]}, make_participant_headers(p["id"])
            )
        )
        assert first["reserved_bike_id"] == bike1["id"]
        r = api_client.reserve_bike(
            p["id"], {"bike_id": bike2["id"]}, make_participant_headers(p["id"])
        )
        validate_error(r, ApiErrorId.ERR_RESERVATION_EXISTS)
        bike2_after = validate_success(api_client.get_bike(bike2["id"], COORD))
        assert bike2_after["status"] == "READY_FOR_DISPOSITION"
