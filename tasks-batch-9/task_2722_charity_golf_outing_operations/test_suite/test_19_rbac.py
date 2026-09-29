"""The two access-control tiers: who is recognized, and what that identity may reach."""

import pytest

from test_helpers import (
    BENEFICIARY_HEADERS,
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    MISSING_ROLE_HEADERS,
    MISSING_USER_ID_HEADERS,
    NON_EXISTENT_UUID,
    NO_HEADERS,
    SPONSORSHIP_HEADERS,
    TREASURER_ALT_HEADERS,
    TREASURER_ALT_USER_ID,
    TREASURER_HEADERS,
    TREASURER_USER_ID,
    UNKNOWN_ROLE_HEADERS,
    ApiErrorId,
    is_valid_uuid,
    make_participant_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
NO_GUARANTEE = {"guaranteed_player_count": 0}
CLOCK_START = "2026-08-01T00:00:00Z"

TREASURER_WITHOUT_AN_ID = {"X-User-Role": "CharityTreasurer", "Content-Type": "application/json"}
DEFECTIVE_HEADERS = {
    "the user id header is absent": MISSING_USER_ID_HEADERS,
    "the role header is absent": MISSING_ROLE_HEADERS,
    "the role is not one of the six": UNKNOWN_ROLE_HEADERS,
    "neither header is present": NO_HEADERS,
}


class TestAuthenticationRunsFirst:
    def test_every_defective_identity_is_refused_on_a_write_and_on_a_read(self, api):
        """The first tier reads the two headers and nothing else: "If either header is absent,
        or if `X-User-Role` carries a value that is not one of those six strings, the
        request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."  It applies to reads as
        well as writes, since "Every request to the API, without exception, must carry two
        headers".

        Design: Corner/rbac/a_request_missing_auth_headers_is_rejected_before_every_other_check
        """
        fx.set_clock(api, CLOCK_START)

        for label, headers in DEFECTIVE_HEADERS.items():
            validate_error(
                api.create_outing(f.outing_payload(name=f"Refused: {label}"), headers),
                ApiErrorId.UNAUTHENTICATED,
                401,
            )
            validate_error(api.list_outings(headers), ApiErrorId.UNAUTHENTICATED, 401)

        _, meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert meta["total_count"] == 0

    def test_an_anonymous_request_that_is_also_malformed_or_forbidden_reports_401(self, api):
        """Authentication outranks both the schema tier and the role tier, because it "is the
        very first check the server performs on any request, ahead of schema validation and
        ahead of any lookup of the resources the request names."  A well-formed identity
        then gets through.

        Design: Corner/rbac/a_request_missing_auth_headers_is_rejected_before_every_other_check
        """
        fx.set_clock(api, CLOCK_START)

        malformed = {
            key: value
            for key, value in f.outing_payload(name="Malformed And Anonymous").items()
            if key != "beneficiary_name"
        }
        validate_error(
            api.create_outing(malformed, NO_HEADERS), ApiErrorId.UNAUTHENTICATED, 401
        )
        validate_error(
            api.create_outing(
                f.outing_payload(name="Wrong Role And Anonymous"), TREASURER_WITHOUT_AN_ID
            ),
            ApiErrorId.UNAUTHENTICATED,
            401,
        )

        created = validate_success(
            api.create_outing(f.outing_payload(name="Fully Authenticated"), DIRECTOR_HEADERS),
            201,
        )
        assert is_valid_uuid(created["id"])

        rows, meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert meta["total_count"] == 1
        assert [row["name"] for row in rows] == ["Fully Authenticated"]


FENCE_OUTING = {"name": "Role Fence Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
DIRECTOR_COURSE = {"course_name": "Director Course GC", "rate_per_player_cents": 8000,
                   "guaranteed_player_count": 0}
TREASURER_SIGN = {
    "asset_type": "HOLE_SIGN",
    "label": "Treasurer Sign",
    "hole_number": 4,
    "capacity": 1,
    "list_price_cents": 50000,
}
BENEFICIARY_TIER = {
    "code": "BENEF",
    "kind": "TEAM",
    "price_cents": 120000,
    "player_slots": 4,
    "gsv_cents": 0,
    "inventory_cap": 4,
}
FORBIDDEN_CALLS = (
    "a treasurer creating an outing",
    "a director drafting a contract",
    "a treasurer building sponsorship inventory",
    "a director driving the finance dimension",
    "a sponsorship manager issuing a receipt",
    "the course locking the field",
    "the beneficiary publishing a tier",
    "the course reading the proceeds report",
)


class TestEachRoleIsFencedOutOfAnothersOperations:
    def _an_open_outing_every_call_could_legally_target(self, api):
        ctx = fx.open_outing(api, outing=FENCE_OUTING, contract=NO_GUARANTEE, tier=SOLO_TIER)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Fence Buyer", player_count=1
        )
        fx.pay_registration(api, registration["id"], 30000)
        ctx["registration_id"] = registration["id"]
        ctx["version"] = fx.outing_version(api, ctx["outing_id"])
        return ctx

    def _forbidden(self, api, ctx, label):
        if label == "a treasurer creating an outing":
            return api.create_outing(
                f.outing_payload(name="Treasurer Outing"), TREASURER_HEADERS
            )
        if label == "a director drafting a contract":
            return api.create_contract(
                f.contract_payload(ctx["outing_id"], **DIRECTOR_COURSE), DIRECTOR_HEADERS
            )
        if label == "a treasurer building sponsorship inventory":
            return api.create_sponsorship_asset(
                f.sponsorship_asset_payload(ctx["outing_id"], **TREASURER_SIGN),
                TREASURER_HEADERS,
            )
        if label == "a director driving the finance dimension":
            return api.finance_transition(
                ctx["outing_id"],
                f.finance_transition_payload("RECONCILE", ctx["version"]),
                DIRECTOR_HEADERS,
            )
        if label == "a sponsorship manager issuing a receipt":
            return api.create_receipt(
                f.registration_receipt_payload(ctx["outing_id"], ctx["registration_id"]),
                SPONSORSHIP_HEADERS,
            )
        if label == "the course locking the field":
            return api.play_transition(
                ctx["outing_id"], f.play_transition_payload("LOCK_FIELD"), COURSE_HEADERS
            )
        if label == "the beneficiary publishing a tier":
            return api.create_package_tier(
                f.package_tier_payload(ctx["outing_id"], **BENEFICIARY_TIER),
                BENEFICIARY_HEADERS,
            )
        return api.get_proceeds_report(ctx["outing_id"], COURSE_HEADERS)

    @pytest.mark.parametrize("label", FORBIDDEN_CALLS)
    def test_a_role_absent_from_the_endpoint_is_refused(self, api, label):
        """Every one of these calls is otherwise legal for its own role, so only the roles
        list can be refusing it: "Once the caller is authenticated, the server checks
        whether the declared role appears on the endpoint being called. A role that is not
        listed for the endpoint is refused with `ERR_UNAUTHORIZED` (HTTP 403)."  A
        read-only fence is enforced just as strictly, and the `Beneficiary` "is a read-only
        role limited to reading outings and the beneficiary proceeds report."

        Design: Corner/rbac/a_role_cannot_reach_another_roles_exclusive_operations
        """
        ctx = self._an_open_outing_every_call_could_legally_target(api)
        validate_error(self._forbidden(api, ctx, label), ApiErrorId.UNAUTHORIZED, 403)

    def test_the_fence_precedes_existence_and_leaves_the_declared_reads_working(self, api):
        """The role tier sits above path existence, so a forbidden caller learns nothing about
        which identifiers exist: "The Authorized Role(s) column is exhaustive: any other
        role receives `ERR_UNAUTHORIZED`, and a request with no identity headers at all
        receives `ERR_UNAUTHENTICATED`."  The two reads the beneficiary is listed on still
        answer, and none of the refusals moved the outing.

        Design: Corner/rbac/a_role_cannot_reach_another_roles_exclusive_operations
        """
        ctx = self._an_open_outing_every_call_could_legally_target(api)
        for label in FORBIDDEN_CALLS:
            validate_error(self._forbidden(api, ctx, label), ApiErrorId.UNAUTHORIZED, 403)

        validate_error(
            api.finance_transition(
                NON_EXISTENT_UUID,
                f.finance_transition_payload("RECONCILE", ctx["version"]),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )

        read = validate_success(api.get_outing(ctx["outing_id"], BENEFICIARY_HEADERS))
        assert read["id"] == ctx["outing_id"]
        report = validate_success(
            api.get_proceeds_report(ctx["outing_id"], BENEFICIARY_HEADERS)
        )
        assert report["net_proceeds_cents"] is not None

        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["play_status"] == "OPEN"
        assert outing["finance_status"] == "COLLECTING"
        assert outing["version"] == ctx["version"]


OWN_ROW_OUTING = {"name": "Own Row Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
FLAT_COURSE = {
    "guaranteed_player_count": 0,
    "slope_rating": 113,
    "course_rating": 72.0,
    "par": 72,
}


class TestAParticipantIsFencedToTheirOwnRow:
    def _two_golfers_each_acting_for_themselves(self, api):
        ctx = fx.open_outing(api, outing=OWN_ROW_OUTING, contract=FLAT_COURSE, tier=SOLO_TIER)
        players = []
        for name, index in (("Golfer One", 10.0), ("Golfer Two", 20.0)):
            registration = fx.new_registration(
                api, ctx["outing_id"], ctx["tier_id"], buyer_name=name, player_count=1
            )
            fx.pay_registration(api, registration["id"], 30000)
            players.append(
                fx.new_player(api, registration["id"], full_name=name, handicap_index=index)
            )
        ctx["first_player_id"] = players[0]["id"]
        ctx["second_player_id"] = players[1]["id"]
        return ctx

    def test_the_own_row_write_is_accepted_and_re_derives_from_the_confirm_snapshot(self, api):
        """The entity-backed role may act on itself: "a `Participant` may update a handicap
        index only on their own player row".  The conversion "runs on registration
        confirmation, on a waitlist promotion, on the field lock, on a contract amendment
        that changed `slope_rating`, `course_rating`, or `par`, and on a handicap-index
        update", but before the lock "the index in use is `handicap_index_at_confirm`, the
        value snapshotted when the package was confirmed", which on this flat course leaves
        the stroke figure at the snapshotted 10.

        Design: Corner/rbac/a_participant_cannot_touch_another_golfers_row
        """
        ctx = self._two_golfers_each_acting_for_themselves(api)
        own = make_participant_headers(ctx["first_player_id"])

        updated = validate_success(
            api.update_handicap_index(
                ctx["first_player_id"], f.handicap_index_payload(8.4), own
            )
        )
        assert updated["handicap_index"] == pytest.approx(8.4, abs=0.01)
        assert updated["handicap_index_at_confirm"] == pytest.approx(10.0, abs=0.01)
        assert updated["course_handicap"] == 10

        read = validate_success(api.get_player(ctx["first_player_id"], own))
        assert read["id"] == ctx["first_player_id"]
        assert read["handicap_index"] == pytest.approx(8.4, abs=0.01)
        assert read["course_handicap"] == 10

    def test_another_golfers_row_a_bogus_row_and_a_staff_action_are_all_refused(self, api):
        """The ownership check is part of the authorization tier - "the role is listed on the
        endpoint, and a `Participant` is acting on their own player row, otherwise
        `ERR_UNAUTHORIZED`" - so it covers reads as well as writes and is reported ahead of
        path existence.  The role also holds nothing of its own: a `Participant` "may buy a
        package, add a player row, and read outings, package tiers, their own registration,
        their own player row, teams, the pairing sheet, contests, and receipts, but they
        hold no exclusive operation of their own."

        Design: Corner/rbac/a_participant_cannot_touch_another_golfers_row
        """
        ctx = self._two_golfers_each_acting_for_themselves(api)
        own = make_participant_headers(ctx["first_player_id"])

        validate_error(
            api.update_handicap_index(
                ctx["second_player_id"], f.handicap_index_payload(1.0), own
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        neighbour = fx.read_player(api, ctx["second_player_id"])
        assert neighbour["handicap_index"] == pytest.approx(20.0, abs=0.01)

        validate_error(
            api.get_player(ctx["second_player_id"], own), ApiErrorId.UNAUTHORIZED, 403
        )
        validate_error(
            api.update_handicap_index(
                NON_EXISTENT_UUID, f.handicap_index_payload(5.0), own
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        validate_error(
            api.play_transition(
                ctx["outing_id"], f.play_transition_payload("LOCK_FIELD"), own
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        assert fx.read_outing(api, ctx["outing_id"])["play_status"] == "OPEN"


DUTIES_OUTING = {"name": "Duties Split Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
PLEDGE_A = {
    "item_type": "DONATION",
    "description": "Direct appeal pledge A",
    "fmv_cents": 0,
    "ask_cents": 50000,
}
PLEDGE_B = dict(PLEDGE_A, description="Direct appeal pledge B")


class TestTheSellerOfAnItemMayNotReceiptIt:
    def _two_paid_pledges_recorded_by_one_treasurer(self, api):
        ctx = fx.open_outing(api, outing=DUTIES_OUTING, contract=NO_GUARANTEE, tier=SOLO_TIER)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Donor Buyer", player_count=1
        )
        fx.pay_registration(api, registration["id"], 30000)
        ctx["registration_id"] = registration["id"]

        item_ids = []
        for pledge in (PLEDGE_A, PLEDGE_B):
            item = fx.new_item(api, ctx["outing_id"], **pledge)
            fx.sell_item(api, item["id"], registration["id"], 50000)
            fx.pay_item(api, item["id"], 50000)
            item_ids.append(item["id"])
        ctx["first_item_id"], ctx["second_item_id"] = item_ids
        return ctx

    def test_the_recording_user_is_barred_while_a_second_treasurer_may_issue(self, api):
        """The bar compares stored stamps rather than roles: "the user who recorded a
        fundraising sale" "may not be the user who issues that item's charitable receipt;
        the same error is returned, and on success the issuing user is recorded as
        `issued_by_user_id`."  A donation is fully deductible, since "For a `DONATION` the
        `gsv_cents` is 0 and the whole `payment_cents` is deductible", and the accepted
        receipt cascades the subject, because "Issuing a receipt against a `PAID`
        fundraising item cascades that item `PAID → RECEIPTED`".

        Design: Corner/rbac/the_user_who_recorded_a_sale_cannot_issue_that_items_receipt
        """
        ctx = self._two_paid_pledges_recorded_by_one_treasurer(api)

        validate_error(
            api.create_receipt(
                f.item_receipt_payload(ctx["outing_id"], ctx["first_item_id"]),
                TREASURER_HEADERS,
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES,
            403,
        )
        assert fx.read_item(api, ctx["first_item_id"])["status"] == "PAID"

        receipt = validate_success(
            api.create_receipt(
                f.item_receipt_payload(ctx["outing_id"], ctx["first_item_id"]),
                TREASURER_ALT_HEADERS,
            ),
            201,
        )
        assert receipt["payment_cents"] == 50000
        assert receipt["gsv_cents"] == 0
        assert receipt["deductible_amount_cents"] == 50000
        assert receipt["receipt_number"] == "GR-0001"
        assert receipt["issued_by_user_id"] == TREASURER_ALT_USER_ID

        assert fx.read_item(api, ctx["first_item_id"])["status"] == "RECEIPTED"
        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["receipted_deductible_total_cents"] == 50000

    def test_the_bar_is_per_subject_and_the_role_fence_still_outranks_it(self, api):
        """The stamp is read from the subject, so the barred user is a perfectly good issuer
        for a different one - the rule names "the user who recorded a fundraising sale"
        "recorded as `recorded_by_user_id` on the item".  A role that never issues receipts
        at all is stopped one tier earlier, at "the role is listed on the endpoint", so it
        reports the authorization code rather than the duties code, and the numbering keeps
        running: "the first receipt of an outing reads `GR-0001`, the second `GR-0002`".

        Design: Corner/rbac/the_user_who_recorded_a_sale_cannot_issue_that_items_receipt
        """
        ctx = self._two_paid_pledges_recorded_by_one_treasurer(api)
        fx.issue_item_receipt(
            api, ctx["outing_id"], ctx["first_item_id"], TREASURER_ALT_HEADERS
        )

        own_subject = validate_success(
            api.create_receipt(
                f.registration_receipt_payload(ctx["outing_id"], ctx["registration_id"]),
                TREASURER_HEADERS,
            ),
            201,
        )
        assert own_subject["payment_cents"] == 30000
        assert own_subject["deductible_amount_cents"] == 30000
        assert own_subject["receipt_number"] == "GR-0002"
        assert own_subject["issued_by_user_id"] == TREASURER_USER_ID

        validate_error(
            api.create_receipt(
                f.item_receipt_payload(ctx["outing_id"], ctx["second_item_id"]),
                SPONSORSHIP_HEADERS,
            ),
            ApiErrorId.UNAUTHORIZED,
            403,
        )
        assert fx.read_item(api, ctx["second_item_id"])["status"] == "PAID"

        rows, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 2
        assert {row["receipt_number"] for row in rows} == {"GR-0001", "GR-0002"}
