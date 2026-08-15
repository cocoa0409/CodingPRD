"""Giveaway awards: monthly quota boundary (queue A), fulfill flow and
segregation of duties (queue B)."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_ready_bike, make_helmet_part, restock_part,
    TEST_USERS, make_coordinator_headers, make_director_headers,
    ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
DIRECTOR = TEST_USERS["director_headers"]


def _five_requested_awards(bike_id: str):
    ids = []
    for org, code, age in (
        ("OrgA", "RA-1", "ADULT"), ("OrgB", "RB-1", "ADULT"),
        ("OrgC", "RC-1", "YOUTH"), ("OrgD", "RD-1", "ADULT"),
        ("OrgE", "RE-1", "ADULT"),
    ):
        g = validate_success(
            api_client.create_giveaway(
                {"bike_id": bike_id, "partner_org": org, "referral_code": code,
                 "recipient_age_group": age},
                COORD,
            ),
            expected_status=201,
        )
        ids.append(g["id"])
    return ids


class TestGiveawayQuotaBoundary:
    def test_first_four_approvals_succeed(self):
        """PRD §3.10: "counting awards in `APPROVED` or `FULFILLED` status whose
        `decided_at` falls within the current logical-clock calendar month —
        `REQUESTED`, `DENIED`, and `CANCELLED` rows are excluded — that count
        must be below 4 at the moment of approval. The fourth approval of a
        month succeeds; the fifth is rejected with
        `ERR_GIVEAWAY_QUOTA_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/giveaway_quota_fourth_ok_fifth_rejected
        """
        bike, _, _, _ = make_ready_bike(bike_type="HYBRID", grade="B",
                                        part_unit_cost_cents=300)
        ids = _five_requested_awards(bike["id"])
        for gid in ids[:4]:
            approved = validate_success(
                api_client.approve_giveaway(gid, make_director_headers("pd-1"))
            )
            assert approved["status"] == "APPROVED"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"

    def test_fifth_approval_rejected_by_quota(self):
        """PRD §3.10: "The fourth approval of a month succeeds; the fifth is
        rejected with `ERR_GIVEAWAY_QUOTA_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/giveaway_quota_fourth_ok_fifth_rejected
        """
        bike, _, _, _ = make_ready_bike(bike_type="HYBRID", grade="B",
                                        part_unit_cost_cents=300)
        ids = _five_requested_awards(bike["id"])
        for gid in ids[:4]:
            validate_success(
                api_client.approve_giveaway(gid, make_director_headers("pd-1"))
            )
        r = api_client.approve_giveaway(ids[4], make_director_headers("pd-1"))
        validate_error(r, ApiErrorId.ERR_GIVEAWAY_QUOTA_EXCEEDED)
        g5 = validate_success(api_client.get_giveaway(ids[4], COORD))
        assert g5["status"] == "REQUESTED"


class TestGiveawayCancelFreesQuota:
    def test_giveaway_cancel_frees_quota_slot(self):
        """PRD §3.10: "A director may cancel an `APPROVED` award — recording an
        optional `reason` — moving it to `CANCELLED`. Cancellation frees the
        monthly quota slot, because cancelled awards are excluded from the
        quota count."

        Design: Corner/calculations/giveaway_cancel_frees_quota_slot
        """
        bike, _, _, _ = make_ready_bike(bike_type="ROAD", grade="A",
                                        part_unit_cost_cents=100)
        ids = _five_requested_awards(bike["id"])
        for gid in ids[:4]:
            validate_success(
                api_client.approve_giveaway(gid, make_director_headers("pd-1"))
            )
        cancelled = validate_success(
            api_client.cancel_giveaway(
                ids[1], {"reason": "recipient declined"}, DIRECTOR
            )
        )
        assert cancelled["status"] == "CANCELLED"
        fifth = validate_success(
            api_client.approve_giveaway(ids[4], make_director_headers("pd-1"))
        )
        assert fifth["status"] == "APPROVED"


class TestGiveawayFulfill:
    def _approved_award(self, age_group: str = "ADULT", bike_type: str = "ROAD",
                        grade: str = "A", approver_id: str = "pd-1"):
        bike, _, _, _ = make_ready_bike(bike_type=bike_type, grade=grade,
                                        part_unit_cost_cents=100)
        g = validate_success(
            api_client.create_giveaway(
                {"bike_id": bike["id"], "partner_org": "OrgA",
                 "referral_code": "RA-1", "recipient_age_group": age_group},
                COORD,
            ),
            expected_status=201,
        )
        validate_success(
            api_client.approve_giveaway(g["id"], make_director_headers(approver_id))
        )
        return bike, g

    def test_giveaway_fulfill_happy_path_adult(self):
        """PRD §3.10: "Fulfillment stamps `fulfilled_by_user_id`, moves the
        award to `FULFILLED`, moves the bike to `GIFTED`, and bumps both
        records' versions."

        Design: Corner/state_machines/giveaway_fulfill_happy_path_adult
        """
        bike, g = self._approved_award("ADULT")
        fulfilled = validate_success(
            api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        )
        assert fulfilled["status"] == "FULFILLED"
        assert fulfilled["fulfilled_by_user_id"] == "sc-1"
        assert fulfilled["decided_by_user_id"] == "pd-1"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "GIFTED"

    def test_youth_giveaway_fulfill_requires_helmet(self):
        """PRD §3.10: "A `YOUTH` recipient additionally requires a helmet
        distributed as `GIVEAWAY_RECIPIENT` referencing this award, else
        `ERR_HELMET_REQUIRED`; adult recipients carry no helmet precondition."

        Design: Corner/state_machines/youth_giveaway_fulfill_requires_helmet
        """
        bike, g = self._approved_award("YOUTH", bike_type="KIDS", grade="B")
        hp = make_helmet_part(name="Helmet YS", helmet_size="S", unit_cost_cents=1200)
        restock_part(hp["id"], 2)
        r = api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        validate_error(r, ApiErrorId.ERR_HELMET_REQUIRED)
        validate_success(
            api_client.create_helmet_distribution(
                {"helmet_part_id": hp["id"], "recipient_kind": "GIVEAWAY_RECIPIENT",
                 "giveaway_id": g["id"]},
                COORD,
            ),
            expected_status=201,
        )
        ok = validate_success(
            api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        )
        assert ok["status"] == "FULFILLED"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "GIFTED"

    def test_fulfiller_is_approver_segregation(self):
        """PRD §2.9: "The fulfiller of a giveaway must not be the director who
        approved it; equality of the fulfiller's `X-User-ID` with the award's
        `decided_by_user_id` is rejected with `ERR_FULFILLER_IS_APPROVER`."

        Design: Corner/validations/fulfiller_is_approver_segregation
        """
        bike, g = self._approved_award("ADULT", approver_id="pd-9")
        r = api_client.fulfill_giveaway(
            g["id"],
            # even presenting the ShopCoordinator role, same user id as approver
            make_coordinator_headers("pd-9"),
        )
        validate_error(r, ApiErrorId.ERR_FULFILLER_IS_APPROVER)
        ok = validate_success(
            api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        )
        assert ok["status"] == "FULFILLED"

    def test_award_fulfill_before_approval_returns_award_not_approved(self):
        """PRD §3.10: "The award must be `APPROVED` (else
        `ERR_AWARD_NOT_APPROVED`)".

        Design: Corner/validations/award_fulfill_before_approval_returns_award_not_approved
        """
        bike, _, _, _ = make_ready_bike(bike_type="ROAD", grade="A",
                                        part_unit_cost_cents=100)
        g = validate_success(
            api_client.create_giveaway(
                {"bike_id": bike["id"], "partner_org": "OrgN",
                 "referral_code": "RN-1", "recipient_age_group": "ADULT"},
                COORD,
            ),
            expected_status=201,
        )
        r = api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        validate_error(r, ApiErrorId.ERR_AWARD_NOT_APPROVED)
        g_after = validate_success(api_client.get_giveaway(g["id"], COORD))
        assert g_after["status"] == "REQUESTED"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "READY_FOR_DISPOSITION"

    def test_fulfill_blocked_by_pending_sale(self):
        """PRD §3.10: "no `PENDING` sale may reference the bike — a pending sale
        blocks fulfillment with `ERR_SALE_PENDING_CONFLICT`."

        Design: Corner/validations/fulfill_blocked_by_pending_sale
        """
        bike, g = self._approved_award("ADULT")
        sale = validate_success(
            api_client.create_sale(
                {"bike_id": bike["id"], "buyer_name": "B P", "buyer_email": "bp@x.org"},
                COORD,
            ),
            expected_status=201,
        )
        r = api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        validate_error(r, ApiErrorId.ERR_SALE_PENDING_CONFLICT)
        validate_success(
            api_client.void_sale(
                sale["id"], {"reason": "release for program"}, DIRECTOR
            )
        )
        ok = validate_success(
            api_client.fulfill_giveaway(g["id"], make_coordinator_headers("sc-1"))
        )
        assert ok["status"] == "FULFILLED"
        bike_after = validate_success(api_client.get_bike(bike["id"], COORD))
        assert bike_after["status"] == "GIFTED"
