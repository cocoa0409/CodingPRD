"""Ladder ordering, family-specific 404 codes, and the uniqueness guards."""

import pytest

from test_helpers import (
    COURSE_HEADERS,
    DIRECTOR_HEADERS,
    NON_EXISTENT_UUID,
    SPONSORSHIP_HEADERS,
    TREASURER_HEADERS,
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

NOT_FOUND_OUTING = {"name": "Not Found Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
SOLO_TIER = {
    "code": "SOLO",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}
NO_GUARANTEE = {"guaranteed_player_count": 0}

FAMILY_READS = [
    ("get_contract", "COURSE", ApiErrorId.CONTRACT_NOT_FOUND),
    ("get_package_tier", "DIRECTOR", ApiErrorId.TIER_NOT_FOUND),
    ("get_player", "DIRECTOR", ApiErrorId.PLAYER_NOT_FOUND),
    ("get_sponsorship_asset", "SPONSORSHIP", ApiErrorId.ASSET_NOT_FOUND),
    ("get_sponsor_allocation", "SPONSORSHIP", ApiErrorId.ALLOCATION_NOT_FOUND),
    ("get_contest", "DIRECTOR", ApiErrorId.CONTEST_NOT_FOUND),
    ("get_fundraising_item", "TREASURER", ApiErrorId.ITEM_NOT_FOUND),
    ("get_receipt", "TREASURER", ApiErrorId.RECEIPT_NOT_FOUND),
]
READER_HEADERS = {
    "COURSE": COURSE_HEADERS,
    "DIRECTOR": DIRECTOR_HEADERS,
    "SPONSORSHIP": SPONSORSHIP_HEADERS,
    "TREASURER": TREASURER_HEADERS,
}


class TestFamilySpecificNotFoundCodes:
    def _draft_outing_with_one_tier(self, api):
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        outing = fx.new_outing(api, **NOT_FOUND_OUTING)
        tier = fx.new_tier(api, outing["id"], **SOLO_TIER)
        return outing["id"], tier["id"]

    @pytest.mark.parametrize("reader,role,expected", FAMILY_READS)
    def test_each_entity_family_answers_with_its_own_not_found_code(
        self, api, reader, role, expected
    ):
        """No generic 404 exists. The PRD names one code per family: "every identifier
        embedded in the path resolves to a live row. Identifiers are resolved left to
        right, so the outermost segment is reported first, and the reported error names
        the missing family", listing `ERR_CONTRACT_NOT_FOUND`, `ERR_TIER_NOT_FOUND`,
        `ERR_PLAYER_NOT_FOUND`, `ERR_ASSET_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`,
        `ERR_CONTEST_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`, and `ERR_RECEIPT_NOT_FOUND`,
        "all at HTTP 404".

        Design: Corner/validations/unknown_path_and_body_ids_return_the_leftmost_not_found_code
        """
        self._draft_outing_with_one_tier(api)

        response = getattr(api, reader)(NON_EXISTENT_UUID, READER_HEADERS[role])
        validate_error(response, expected, 404)

    def test_the_first_declared_body_reference_wins_when_both_are_dead(self, api):
        """Body foreign keys are resolved in a fixed order: "every foreign key supplied in
        the request body resolves to a live row, checked in the order the endpoint
        declares its inputs, and reported with the same family-specific 404 codes".
        Registration creation declares `outing_id` before `package_tier_id`, so a live
        outing with a dead tier reports the tier while two dead references report the
        outing, and neither refused call creates a row.

        Design: Corner/validations/unknown_path_and_body_ids_return_the_leftmost_not_found_code
        """
        outing_id, _ = self._draft_outing_with_one_tier(api)

        validate_error(
            api.create_registration(
                f.registration_payload(
                    outing_id, NON_EXISTENT_UUID, buyer_name="Ghost Tier", player_count=1
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.TIER_NOT_FOUND,
            404,
        )
        validate_error(
            api.create_registration(
                f.registration_payload(
                    NON_EXISTENT_UUID,
                    NON_EXISTENT_UUID,
                    buyer_name="Ghost Everything",
                    player_count=1,
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.OUTING_NOT_FOUND,
            404,
        )

        rows, meta = validate_paginated(
            api.list_registrations(DIRECTOR_HEADERS, outing_id=outing_id)
        )
        assert meta["total_count"] == 0
        assert rows == []


PRIORITY_OUTING = {"name": "Priority Open", "field_capacity_teams": 4, "prize_pool_cents": 0}


class TestAuthorizationBeforeSchemaBeforePath:
    def test_a_wrong_role_is_reported_before_a_missing_required_field(self, api):
        """One request breaks two rules and the earlier tier must answer. The PRD says
        "The server therefore evaluates a fixed ladder and reports the **first** rule
        that fails; every later rule is left unevaluated", and authorization sits above
        the schema: "the role is listed on the endpoint, and a `Participant` is acting
        on their own player row, otherwise `ERR_UNAUTHORIZED`" precedes "the body and
        query conform as described in" "2.5, otherwise `ERR_INVALID_REQUEST`".

        Design: Corner/validations/authorization_outranks_the_schema_check_on_the_same_request
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.new_outing(api, **PRIORITY_OUTING)

        payload = f.outing_payload(name="Wrong Role And Missing Field")
        payload.pop("beneficiary_name")
        validate_error(
            api.create_outing(payload, TREASURER_HEADERS), ApiErrorId.UNAUTHORIZED, 403
        )

        _, meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert meta["total_count"] == 1

    def test_a_bad_enum_is_reported_before_the_dead_path_identifier(self, api):
        """The mirror case pairs an unusable body with an unresolvable path, and the schema
        tier still answers, because "the body and query conform as described in" "2.5,
        otherwise `ERR_INVALID_REQUEST`" is checked before "every identifier embedded in
        the path resolves to a live row".  So the answer is 422 and never
        `ERR_OUTING_NOT_FOUND`, and the outing already on file is untouched.

        Design: Corner/validations/authorization_outranks_the_schema_check_on_the_same_request
        """
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        fx.new_outing(api, **PRIORITY_OUTING)

        validate_error(
            api.play_transition(
                NON_EXISTENT_UUID,
                f.play_transition_payload("NOT_AN_ACTION"),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
            422,
        )

        rows, meta = validate_paginated(api.list_outings(DIRECTOR_HEADERS))
        assert meta["total_count"] == 1
        assert rows[0]["play_status"] == "DRAFT"


AMBIGUOUS_OUTING = {
    "name": "Ambiguous Receipt Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
FRAMED_LOT = {
    "item_type": "AUCTION",
    "description": "Framed scorecard",
    "fmv_cents": 2000,
    "ask_cents": 10000,
}


class TestReceiptSubjectArity:
    def _one_receiptable_registration_and_one_paid_lot(self, api):
        ctx = fx.open_outing(api, contract=NO_GUARANTEE, tier=SOLO_TIER, outing=AMBIGUOUS_OUTING)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Both Subjects Buyer",
            player_count=1,
        )
        fx.pay_registration(api, registration["id"], 30000)
        item = fx.new_item(api, ctx["outing_id"], **FRAMED_LOT)
        fx.sell_item(api, item["id"], registration["id"], 20000)
        fx.pay_item(api, item["id"], 20000)
        ctx["registration_id"] = registration["id"]
        ctx["item_id"] = item["id"]
        return ctx

    def test_naming_a_registration_and_an_item_at_once_is_refused(self, api):
        """The subject rule is an exclusive choice, not a null test: "a forward receipt
        names exactly one subject and a reversal names exactly one reversed receipt",
        and "Naming zero subjects, naming more than one, or naming a subject that does
        not match the declared `receipt_kind` is refused with
        `ERR_RECEIPT_SUBJECT_AMBIGUOUS` (HTTP 422)."  Both subjects here are
        individually receiptable, so only the arity rule can have fired.

        Design: Corner/validations/a_receipt_naming_two_subjects_or_none_is_ambiguous
        """
        ctx = self._one_receiptable_registration_and_one_paid_lot(api)

        validate_error(
            api.create_receipt(
                f.registration_receipt_payload(
                    ctx["outing_id"],
                    ctx["registration_id"],
                    fundraising_item_id=ctx["item_id"],
                ),
                TREASURER_HEADERS,
            ),
            ApiErrorId.RECEIPT_SUBJECT_AMBIGUOUS,
            422,
        )

        _, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 0
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is False
        assert fx.read_item(api, ctx["item_id"])["status"] == "PAID"

    def test_naming_no_subject_at_all_is_refused_by_the_same_code(self, api):
        """The other direction of the same rule: "Naming zero subjects, naming more than
        one, or naming a subject that does not match the declared `receipt_kind` is
        refused with `ERR_RECEIPT_SUBJECT_AMBIGUOUS` (HTTP 422)."  Because "the first
        receipt of an outing reads `GR-0001`, the second `GR-0002`" numbers only
        accepted receipts, the refused call consumes no number at all.

        Design: Corner/validations/a_receipt_naming_two_subjects_or_none_is_ambiguous
        """
        ctx = self._one_receiptable_registration_and_one_paid_lot(api)

        payload = f.registration_receipt_payload(ctx["outing_id"], ctx["registration_id"])
        payload.pop("registration_id")
        validate_error(
            api.create_receipt(payload, TREASURER_HEADERS),
            ApiErrorId.RECEIPT_SUBJECT_AMBIGUOUS,
            422,
        )

        _, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 0
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 0
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is False
        assert fx.read_item(api, ctx["item_id"])["status"] == "PAID"


UNIQUENESS_OUTING = {
    "name": "Receipt Uniqueness Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}


class TestForwardReceiptUniquenessAndImmutability:
    def _one_receipted_registration(self, api):
        ctx = fx.open_outing(api, contract=NO_GUARANTEE, tier=SOLO_TIER, outing=UNIQUENESS_OUTING)
        registration = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Reversal Buyer", player_count=1
        )
        fx.pay_registration(api, registration["id"], 30000)
        ctx["registration_id"] = registration["id"]
        ctx["first_receipt"] = fx.issue_registration_receipt(
            api, ctx["outing_id"], registration["id"]
        )
        return ctx

    def test_a_second_receipt_is_refused_while_the_first_is_live(self, api):
        """Uniqueness counts live forward rows only: "At most one un-reversed forward
        receipt may exist per subject" "and a second is refused with
        `ERR_DUPLICATE_RECEIPT`."  The tier declares `gsv_cents` 0, so the live receipt
        is the full payment and the outing's total, "the signed sum of
        `deductible_amount_cents` over every receipt of the outing, reversals included",
        stays at that one figure.

        Design: Corner/validations/a_second_forward_receipt_is_refused_but_a_reversed_subject_may_be_receipted_again
        """
        ctx = self._one_receipted_registration(api)
        assert ctx["first_receipt"]["receipt_number"] == "GR-0001"
        assert ctx["first_receipt"]["deductible_amount_cents"] == 30000

        validate_error(
            api.create_receipt(
                f.registration_receipt_payload(ctx["outing_id"], ctx["registration_id"]),
                TREASURER_HEADERS,
            ),
            ApiErrorId.DUPLICATE_RECEIPT,
            409,
        )

        _, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 1
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 30000
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is True

    def test_a_reversal_mirrors_every_sign_and_frees_the_subject(self, api):
        """A reversal is an appended row, never an edit: "its `payment_cents` is the
        negation of the original's `payment_cents`, its `gsv_cents` the negation of the
        original's `gsv_cents`, and its `deductible_amount_cents` the negation of the
        original's `deductible_amount_cents`", and "Appending a reversal clears the
        subject registration's `receipt_issued` flag back to false".  Because the total
        is a signed sum, "a forward receipt followed by its reversal returns the total
        to exactly the value it held before the forward receipt was issued".

        Design: Corner/validations/a_second_forward_receipt_is_refused_but_a_reversed_subject_may_be_receipted_again
        """
        ctx = self._one_receipted_registration(api)

        reversal = fx.reverse_receipt(
            api, ctx["first_receipt"]["id"], reason="Payment charged back"
        )
        assert reversal["receipt_kind"] == "REVERSAL"
        assert reversal["receipt_number"] == "GR-0002"
        assert reversal["payment_cents"] == -30000
        assert reversal["gsv_cents"] == 0
        assert reversal["deductible_amount_cents"] == -30000

        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 0
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is False

    def test_neither_a_reversal_nor_a_reversed_receipt_may_be_reversed_again(self, api):
        """Append-only means two refusals: "A reversal may never itself be reversed, and a
        receipt that already carries a live reversal may not be reversed a second time;
        both are refused with `ERR_RECEIPT_IMMUTABLE`."  Both refused calls consume no
        number, so the ledger still holds exactly the forward row and its reversal.

        Design: Corner/validations/a_second_forward_receipt_is_refused_but_a_reversed_subject_may_be_receipted_again
        """
        ctx = self._one_receipted_registration(api)
        reversal = fx.reverse_receipt(
            api, ctx["first_receipt"]["id"], reason="Payment charged back"
        )

        validate_error(
            api.reverse_receipt(
                ctx["first_receipt"]["id"],
                f.reversal_payload("Second attempt at the same reversal"),
                TREASURER_HEADERS,
            ),
            ApiErrorId.RECEIPT_IMMUTABLE,
            409,
        )
        validate_error(
            api.reverse_receipt(
                reversal["id"], f.reversal_payload("Reversing a reversal"), TREASURER_HEADERS
            ),
            ApiErrorId.RECEIPT_IMMUTABLE,
            409,
        )

        _, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 2
        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 0

    def test_a_reversed_subject_may_be_receipted_again(self, api):
        """Reversal is the correction mechanism, so the subject becomes receiptable once
        more: only "At most one un-reversed forward receipt may exist per subject" bars a
        second forward row, and the reversal is what "makes the outing eligible for a
        corrected receipt".  The replacement takes the next number in the per-outing
        sequence and restores the outing's signed total.

        Design: Corner/validations/a_second_forward_receipt_is_refused_but_a_reversed_subject_may_be_receipted_again
        """
        ctx = self._one_receipted_registration(api)
        fx.reverse_receipt(api, ctx["first_receipt"]["id"], reason="Payment charged back")

        replacement = fx.issue_registration_receipt(
            api, ctx["outing_id"], ctx["registration_id"]
        )
        assert replacement["receipt_number"] == "GR-0003"
        assert replacement["payment_cents"] == 30000
        assert replacement["deductible_amount_cents"] == 30000

        assert fx.read_outing(api, ctx["outing_id"])["receipted_deductible_total_cents"] == 30000
        assert fx.read_registration(api, ctx["registration_id"])["receipt_issued"] is True
        _, meta = validate_paginated(
            api.list_receipts(TREASURER_HEADERS, outing_id=ctx["outing_id"])
        )
        assert meta["total_count"] == 3


ROSTER_OUTING = {"name": "Roster Limits Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
PAIR_TIER = {
    "code": "PAIR",
    "kind": "TEAM",
    "price_cents": 60000,
    "player_slots": 2,
    "gsv_cents": 12000,
    "inventory_cap": 10,
}
FOURSOME_NAMES = ("Four One", "Four Two", "Four Three", "Four Four")
TWOSOME_NAMES = ("Two One", "Two Two")


class TestTeamMembershipLimits:
    def _a_paid_foursome_and_a_paid_twosome(self, api):
        ctx = fx.open_outing(api, contract=NO_GUARANTEE, outing=ROSTER_OUTING)
        pair = fx.add_tier(api, ctx, **PAIR_TIER)

        foursome = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Foursome Buyer", player_count=4
        )
        ctx["foursome_id"] = foursome["id"]
        ctx["foursome_players"] = [
            fx.new_player(api, foursome["id"], full_name=name, handicap_index=12.0)["id"]
            for name in FOURSOME_NAMES
        ]
        fx.pay_registration(api, foursome["id"], 120000)

        twosome = fx.new_registration(
            api, ctx["outing_id"], pair["id"], buyer_name="Twosome Buyer", player_count=2
        )
        ctx["twosome_id"] = twosome["id"]
        ctx["twosome_players"] = [
            fx.new_player(api, twosome["id"], full_name=name, handicap_index=12.0)["id"]
            for name in TWOSOME_NAMES
        ]
        fx.pay_registration(api, twosome["id"], 60000)
        return ctx

    def test_a_fifth_golfer_and_a_five_player_group_are_refused_on_different_rules(self, api):
        """Two neighbouring size limits are separate rules. The roster limit belongs to the
        registration: "Adding a player beyond the owning registration's `player_count` is
        refused with `ERR_PLAYER_SLOTS_EXCEEDED`."  The team bound belongs to the team:
        "The `player_ids` array must be non-empty, must not be longer than four, and must
        not be longer than the `player_count` of the registration that funded the
        players, otherwise `ERR_TEAM_SIZE_INVALID`", and "a team holds between one and
        four golfers" however many registrations contributed them.

        Design: Corner/validations/team_membership_rejects_a_reused_player_an_oversized_group_and_an_extra_player
        """
        ctx = self._a_paid_foursome_and_a_paid_twosome(api)

        validate_error(
            api.create_player(
                f.player_payload(ctx["foursome_id"], full_name="Four Five", handicap_index=12.0),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.PLAYER_SLOTS_EXCEEDED,
            409,
        )
        _, meta = validate_paginated(
            api.list_players(DIRECTOR_HEADERS, registration_id=ctx["foursome_id"])
        )
        assert meta["total_count"] == 4

        validate_error(
            api.create_team(
                f.team_payload(
                    ctx["outing_id"],
                    ctx["foursome_players"] + ctx["twosome_players"][:1],
                    team_name="Fivesome",
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.TEAM_SIZE_INVALID,
            409,
        )
        _, teams_meta = validate_paginated(
            api.list_teams(DIRECTOR_HEADERS, outing_id=ctx["outing_id"])
        )
        assert teams_meta["total_count"] == 0

    def test_a_linked_golfer_may_not_be_grouped_again_while_the_lawful_pair_may(self, api):
        """Grouping is exclusive per golfer: "A golfer who already carries a `team_id` cannot
        be grouped again", refused with `ERR_PLAYER_ALREADY_ASSIGNED`.  An accepted
        request writes that link - "On acceptance the server writes `team_id` on every
        listed player, derives the team's `player_count` as the count of players pointing
        at it, and computes the team's `team_playing_handicap` under the provisional
        treatment, recording `handicap_variant` as `PROVISIONAL`" - so the untouched
        golfer named alongside the reused one keeps a null `team_id`.

        Design: Corner/validations/team_membership_rejects_a_reused_player_an_oversized_group_and_an_extra_player
        """
        ctx = self._a_paid_foursome_and_a_paid_twosome(api)

        foursome_team = validate_success(
            api.create_team(
                f.team_payload(
                    ctx["outing_id"], ctx["foursome_players"], team_name="Legit Foursome"
                ),
                DIRECTOR_HEADERS,
            ),
            201,
        )
        assert foursome_team["player_count"] == 4
        assert foursome_team["team_playing_handicap"] is not None
        assert foursome_team["handicap_variant"] == "PROVISIONAL"

        validate_error(
            api.create_team(
                f.team_payload(
                    ctx["outing_id"],
                    [ctx["foursome_players"][0], ctx["twosome_players"][0]],
                    team_name="Reuses A Player",
                ),
                DIRECTOR_HEADERS,
            ),
            ApiErrorId.PLAYER_ALREADY_ASSIGNED,
            409,
        )
        assert fx.read_player(api, ctx["twosome_players"][0])["team_id"] is None

        twosome_team = validate_success(
            api.create_team(
                f.team_payload(
                    ctx["outing_id"], ctx["twosome_players"], team_name="Legit Twosome"
                ),
                DIRECTOR_HEADERS,
            ),
            201,
        )
        assert twosome_team["player_count"] == 2
        _, meta = validate_paginated(api.list_teams(DIRECTOR_HEADERS, outing_id=ctx["outing_id"]))
        assert meta["total_count"] == 2


INVENTORY_OUTING = {"name": "Inventory Cap Open", "field_capacity_teams": 4, "prize_pool_cents": 0}
LIMITED_TIER = {
    "code": "LIMITED",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 1,
}
OPEN_TIER = {
    "code": "OPEN_TIER",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 10,
}


class TestTierInventoryCapVersusFieldCapacity:
    def _one_capped_tier_already_sold_out(self, api):
        ctx = fx.open_outing(api, contract=NO_GUARANTEE, tier=LIMITED_TIER, outing=INVENTORY_OUTING)
        ctx["open_tier_id"] = fx.add_tier(api, ctx, **OPEN_TIER)["id"]
        first = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="First On Limited", player_count=1
        )
        ctx["second_id"] = fx.new_registration(
            api, ctx["outing_id"], ctx["tier_id"], buyer_name="Second On Limited", player_count=1
        )["id"]
        ctx["sibling_id"] = fx.new_registration(
            api, ctx["outing_id"], ctx["open_tier_id"], buyer_name="On Open Tier", player_count=1
        )["id"]
        fx.pay_registration(api, first["id"], 30000)
        return ctx

    def test_the_exhausted_tier_refuses_the_sale_instead_of_waitlisting_it(self, api):
        """Two supply gates are independent, and only the tier gate can fire here. The PRD
        makes the cap strict - "the held tier's `sold_count` must be strictly below its
        `inventory_cap`, otherwise `ERR_TIER_INVENTORY_EXHAUSTED`" - and the waitlist gate
        is a different comparison: "the server compares the outing's current
        `confirmed_player_slots` plus this registration's `player_count` against the
        field's capacity in player slots, which is `field_capacity_teams` multiplied by
        four."  One sold slot against sixteen leaves the field wide open, so the answer is
        the tier error and the refused row keeps its `PENDING_PAYMENT` posture.

        Design: Corner/validations/the_tier_inventory_cap_refuses_a_sale_while_the_field_still_has_room
        """
        ctx = self._one_capped_tier_already_sold_out(api)

        validate_error(
            api.record_registration_payment(
                ctx["second_id"], f.payment_payload(30000), TREASURER_HEADERS
            ),
            ApiErrorId.TIER_INVENTORY_EXHAUSTED,
            409,
        )

        refused = fx.read_registration(api, ctx["second_id"])
        assert refused["status"] == "PENDING_PAYMENT"
        assert refused["amount_paid_cents"] == 0
        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["confirmed_player_slots"] == 1
        assert outing["waitlisted_registration_count"] == 0

    def test_a_sibling_tier_with_headroom_still_confirms(self, api):
        """The cap is a per-tier count - "`inventory_cap`, the maximum number of
        registrations that may hold this tier in a revenue-recognized state" - so the
        sibling tier's own headroom is untouched by the exhausted one, and its buyer
        confirms because "a payment that lands exactly on the capacity figure confirms,
        and only the first slot past it waitlists".  Each tier's live `sold_count` is
        "the number of registrations currently holding it whose status is `CONFIRMED`,
        `AMENDED`, or `CHECKED_IN`".

        Design: Corner/validations/the_tier_inventory_cap_refuses_a_sale_while_the_field_still_has_room
        """
        ctx = self._one_capped_tier_already_sold_out(api)
        validate_error(
            api.record_registration_payment(
                ctx["second_id"], f.payment_payload(30000), TREASURER_HEADERS
            ),
            ApiErrorId.TIER_INVENTORY_EXHAUSTED,
            409,
        )

        sibling = validate_success(
            api.record_registration_payment(
                ctx["sibling_id"], f.payment_payload(30000), TREASURER_HEADERS
            )
        )
        assert sibling["status"] == "CONFIRMED"

        assert fx.read_tier(api, ctx["tier_id"])["sold_count"] == 1
        assert fx.read_tier(api, ctx["open_tier_id"])["sold_count"] == 1
        outing = fx.read_outing(api, ctx["outing_id"])
        assert outing["confirmed_player_slots"] == 2
        assert outing["waitlisted_registration_count"] == 0


FIRST_UNIQUENESS_OUTING = {
    "name": "Uniqueness Open",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
SECOND_UNIQUENESS_OUTING = {
    "name": "Second Uniqueness Open",
    "beneficiary_name": "Southside Literacy Trust",
    "scheduled_date": "2026-09-26T12:00:00Z",
    "wave_a_start": "2026-09-26T12:00:00Z",
    "wave_a_end": "2026-09-26T16:30:00Z",
    "field_capacity_teams": 4,
    "prize_pool_cents": 0,
}
T4_TIER = {
    "code": "T4",
    "kind": "TEAM",
    "price_cents": 120000,
    "player_slots": 4,
    "gsv_cents": 24000,
    "inventory_cap": 10,
}
SHADOW_T4_TIER = {
    "code": "T4",
    "kind": "INDIVIDUAL",
    "price_cents": 30000,
    "player_slots": 1,
    "gsv_cents": 0,
    "inventory_cap": 5,
}
PIN_CONTEST = {"contest_type": "CLOSEST_TO_PIN", "hole_number": 7, "prize_value_cents": 50000}
DRIVE_CONTEST = {"contest_type": "LONGEST_DRIVE", "hole_number": 7, "prize_value_cents": 40000}


class TestUniquenessScopes:
    def _two_outings_the_first_already_furnished(self, api):
        fx.set_clock(api, "2026-08-01T00:00:00Z")
        first = fx.new_outing(api, **FIRST_UNIQUENESS_OUTING)
        second = fx.new_outing(api, **SECOND_UNIQUENESS_OUTING)
        contract = fx.new_contract(api, first["id"])
        fx.new_tier(api, first["id"], **T4_TIER)
        contest = fx.new_contest(api, first["id"], **PIN_CONTEST)
        return {
            "first_id": first["id"],
            "second_id": second["id"],
            "contract_id": contract["id"],
            "contest_id": contest["id"],
        }

    def test_a_tier_code_is_unique_per_outing_and_a_contract_is_unique_ever(self, api):
        """Two uniqueness scopes differ. A tier carries "a short `code` that must be unique
        among that outing's tiers", so the same code is refused on the first outing with
        `ERR_TIER_CODE_DUPLICATE` yet accepted on a second one.  A contract is stricter:
        "there may be at most one per outing: a second attempt against an outing that
        already has a contract is refused with `ERR_CONTRACT_ALREADY_EXISTS`", and the
        original terms survive the refusal.

        Design: Corner/validations/duplicate_tier_codes_a_second_contract_and_a_reused_contest_hole_are_rejected
        """
        ctx = self._two_outings_the_first_already_furnished(api)

        validate_error(
            api.create_package_tier(
                f.package_tier_payload(ctx["first_id"], **SHADOW_T4_TIER), DIRECTOR_HEADERS
            ),
            ApiErrorId.TIER_CODE_DUPLICATE,
            409,
        )
        _, tiers_meta = validate_paginated(
            api.list_package_tiers(DIRECTOR_HEADERS, outing_id=ctx["first_id"])
        )
        assert tiers_meta["total_count"] == 1

        elsewhere = validate_success(
            api.create_package_tier(
                f.package_tier_payload(ctx["second_id"], **T4_TIER), DIRECTOR_HEADERS
            ),
            201,
        )
        assert elsewhere["code"] == "T4"
        assert elsewhere["outing_id"] == ctx["second_id"]

        validate_error(
            api.create_contract(
                f.contract_payload(
                    ctx["first_id"], course_name="Second Course GC", rate_per_player_cents=8000
                ),
                COURSE_HEADERS,
            ),
            ApiErrorId.CONTRACT_ALREADY_EXISTS,
            409,
        )
        rows, contracts_meta = validate_paginated(
            api.list_contracts(COURSE_HEADERS, outing_id=ctx["first_id"])
        )
        assert contracts_meta["total_count"] == 1
        assert rows[0]["rate_per_player_cents"] == 9500

    def test_the_hole_lock_counts_only_non_voided_contests(self, api):
        """The hole lock is not a permanent reservation: "At most one non-voided contest may
        occupy any given `hole_number` within an outing; a second is refused with
        `ERR_CONTEST_HOLE_CONFLICT`."  Voiding is available from `PLANNED`, and
        "`AWARDED` and `VOID` are the terminal lifecycle states", so once the first
        contest is void the same hole accepts a replacement and both rows remain on file.

        Design: Corner/validations/duplicate_tier_codes_a_second_contract_and_a_reused_contest_hole_are_rejected
        """
        ctx = self._two_outings_the_first_already_furnished(api)

        validate_error(
            api.create_contest(
                f.contest_payload(ctx["first_id"], **DRIVE_CONTEST), DIRECTOR_HEADERS
            ),
            ApiErrorId.CONTEST_HOLE_CONFLICT,
            409,
        )

        voided = fx.drive_contest(api, ctx["contest_id"], "VOID")
        assert voided["status"] == "VOID"

        replacement = validate_success(
            api.create_contest(
                f.contest_payload(ctx["first_id"], **DRIVE_CONTEST), DIRECTOR_HEADERS
            ),
            201,
        )
        assert replacement["hole_number"] == 7
        assert replacement["contest_type"] == "LONGEST_DRIVE"
        assert replacement["status"] == "PLANNED"

        _, meta = validate_paginated(api.list_contests(DIRECTOR_HEADERS, outing_id=ctx["first_id"]))
        assert meta["total_count"] == 2
        assert fx.read_contest(api, ctx["contest_id"])["status"] == "VOID"
