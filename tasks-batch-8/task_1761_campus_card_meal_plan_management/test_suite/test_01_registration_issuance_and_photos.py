"""Card holder registration, card issuance, and the photo verification cycle."""
from test_helpers import (
    ApiErrorId,
    activate_card,
    assert_card_holder,
    assert_campus_card,
    assert_photo_submission,
    create_card_holder_payload,
    create_holder,
    create_provisional_card,
    get_success_data,
    issue_card,
    make_cardholder_headers,
    review_photo,
    set_clock,
    submit_photo,
    validate_error,
    validate_success,
)

ADMIN_ID = "card-office-1"


class TestCardHolderCreation:
    def test_card_holder_creation_defaults_and_duplicate_key_rejected(self, api):
        """PRD §3.1: "A new holder starts with `status` `ACTIVE`, a
        `fraud_strike_count` of 0, and `fraud_flag` false."
        PRD §3.1: "The `university_id` is a natural key: a duplicate submission
        is rejected with `ERR_DUPLICATE_NATURAL_KEY`."

        Design: Corner/entities/card_holder_creation_defaults_and_duplicate_key_rejected
        """
        from test_helpers import TEST_USERS
        admin = TEST_USERS["card_office_admin_headers"]
        payload = create_card_holder_payload(
            university_id="U90001", full_name="Ada One", email="ada@x.edu",
            holder_type="FACULTY", housing_status="OFF_CAMPUS")
        resp = api.create_card_holder(payload, admin)
        holder = validate_success(resp, 201)
        assert_card_holder(holder)
        assert holder["status"] == "ACTIVE"
        assert holder["fraud_strike_count"] == 0
        assert holder["fraud_flag"] is False
        assert holder["version"] == 1

        dup = api.create_card_holder(
            create_card_holder_payload(
                university_id="U90001", full_name="Ada Two", email="ada2@x.edu",
                holder_type="STAFF", housing_status="COMMUTER"),
            admin)
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_NATURAL_KEY)

        bad_enum = api.create_card_holder(
            create_card_holder_payload(
                university_id="U90002", full_name="Bad Enum", email="be@x.edu",
                holder_type="SUPERUSER", housing_status="COMMUTER"),
            admin)
        validate_error(bad_enum, ApiErrorId.ERR_VALIDATION)


class TestCardIssuance:
    def test_card_issuance_initial_state_and_system_fields(self, api):
        """PRD §3.1: "A fresh card starts with `lifecycle_status` `PENDING_PHOTO`,
        `photo_status` `NOT_SUBMITTED`, `is_provisional` true,
        `replacement_fee_cents` 0, `lost_or_stolen_report_count` 0, and a null
        `replaced_by_card_id`."
        PRD §3.1: "The server mints a unique 16-digit `card_number` and links the
        card to its holder via `holder_id` taken from the creation path."

        Design: Corner/entities/card_issuance_initial_state_and_system_fields
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90003", full_name="Cal Issue",
                               email="cal@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])
        assert_campus_card(card)
        assert card["lifecycle_status"] == "PENDING_PHOTO"
        assert card["photo_status"] == "NOT_SUBMITTED"
        assert card["is_provisional"] is True
        assert card["replacement_fee_cents"] == 0
        assert card["lost_or_stolen_report_count"] == 0
        assert card["replaced_by_card_id"] is None
        assert card["version"] == 1
        assert card["holder_id"] == holder["id"]
        assert isinstance(card["card_number"], str) and card["card_number"]


class TestPhotoCycle:
    def test_photo_submission_resubmission_sequence(self, api):
        """PRD §3.1: "Submissions are ordered by a `submission_sequence`, a 1-based
        ordinal assigned in `created_at` order among the card's submissions"
        PRD §3.1: "A rejected photo is not the end of the road: the holder may
        submit again, cycling `REJECTED` → `PENDING_REVIEW` without bound."

        Design: Corner/entities/photo_submission_resubmission_sequence
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90008", full_name="Hana Photo",
                               email="hana@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])
        p1 = submit_photo(card["id"], holder["id"], image_ref="img://v1")
        assert_photo_submission(p1)
        assert p1["submission_sequence"] == 1
        assert p1["review_status"] == "PENDING_REVIEW"
        review_photo(p1["id"], decision="REJECTED", rejection_reason="blurry")

        p2 = submit_photo(card["id"], holder["id"], image_ref="img://v2")
        assert p2["submission_sequence"] == 2
        assert p2["review_status"] == "PENDING_REVIEW"
        card_now = get_success_data(api.get_card(card["id"], api_headers_admin()))
        assert card_now["photo_status"] == "PENDING_REVIEW"

    def test_photo_rejection_requires_reason(self, api):
        """PRD §3.1: "Rejection requires a `rejection_reason`; omitting it is
        rejected with `ERR_VALIDATION`."

        Design: Corner/state_machines/photo_rejection_requires_reason
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90013", full_name="Mona Photo",
                               email="mona@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])
        photo = submit_photo(card["id"], holder["id"], image_ref="img://m1")

        from test_helpers import TEST_USERS
        resp = api.review_photo(photo["id"], {"decision": "REJECTED"},
                                TEST_USERS["card_office_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        still = get_success_data(
            api.get_card(card["id"], TEST_USERS["card_office_admin_headers"]))
        assert still["photo_status"] == "PENDING_REVIEW"

    def test_activation_without_photo_and_without_flag_rejected(self, api):
        """PRD §3.1: "the card's `photo_status` must be `APPROVED`, unless the
        caller deliberately passes `allow_provisional` as true (otherwise
        `ERR_PHOTO_NOT_APPROVED`)"

        Design: Corner/state_machines/activation_without_photo_and_without_flag_rejected
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U90012", full_name="Liv Photo",
                               email="liv@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])

        from test_helpers import TEST_USERS
        resp = api.activate_card(card["id"], {},
                                 TEST_USERS["card_office_admin_headers"])
        validate_error(resp, ApiErrorId.ERR_PHOTO_NOT_APPROVED)
        still = get_success_data(
            api.get_card(card["id"], TEST_USERS["card_office_admin_headers"]))
        assert still["lifecycle_status"] == "PENDING_PHOTO"

    def test_cardholder_cannot_review_photo(self, api):
        """PRD §4: the photo review endpoint's authorized role list contains only
        CardOfficeAdmin. PRD §2.1: "If the headers are well-formed but the named
        role is not in the calling endpoint's authorized role list, the request is
        rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/rbac/cardholder_cannot_review_photo
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U94001", full_name="Rho Photo",
                               email="rho@x.edu", holder_type="STUDENT_RESIDENT",
                               housing_status="ON_CAMPUS")
        card = issue_card(holder["id"])
        photo = submit_photo(card["id"], holder["id"], image_ref="img://rho")

        resp = api.review_photo(photo["id"], {"decision": "APPROVED"},
                                make_cardholder_headers(holder["id"]))
        validate_error(resp, ApiErrorId.ERR_ROLE_NOT_PERMITTED)
        from test_helpers import TEST_USERS
        photos = get_success_data(
            api.list_card_photos(card["id"],
                                 TEST_USERS["card_office_admin_headers"]))
        assert photos[0]["review_status"] == "PENDING_REVIEW"


def api_headers_admin():
    from test_helpers import TEST_USERS
    return TEST_USERS["card_office_admin_headers"]


class TestCardParallelDimensions:
    def test_provisional_activation_and_photo_approval_independence(self, api):
        """PRD §3.1: "The card's lifecycle dimension (`lifecycle_status`:
        `PENDING_PHOTO`, `ACTIVE`, `LOST_FROZEN`, `STOLEN_FROZEN`, `REPLACED`,
        `EXPIRED`, `DEACTIVATED`) and its photo dimension (`photo_status`:
        `NOT_SUBMITTED`, `PENDING_REVIEW`, `APPROVED`, `REJECTED`) are **parallel
        and independent**; each has its own rules, and neither implies the other."
        PRD §3.1: "Approval additionally clears a provisional card's
        `is_provisional` to false."

        Design: Difficulty/non_linear_state_machine/campus_card_parallel_dimensions_with_freeze_cycle
        """
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U4001", full_name="Fay Staff",
                               email="fay@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        card = issue_card(holder["id"])
        assert card["lifecycle_status"] == "PENDING_PHOTO"
        assert card["photo_status"] == "NOT_SUBMITTED"

        active = activate_card(card["id"], allow_provisional=True)
        assert active["lifecycle_status"] == "ACTIVE"
        assert active["photo_status"] == "NOT_SUBMITTED"
        assert active["is_provisional"] is True

        photo = submit_photo(card["id"], holder["id"], image_ref="img://fay")
        after_submit = get_success_data(api.get_card(card["id"],
                                                     api_headers_admin()))
        assert after_submit["lifecycle_status"] == "ACTIVE"
        assert after_submit["photo_status"] == "PENDING_REVIEW"

        review_photo(photo["id"], decision="APPROVED")
        after_approval = get_success_data(api.get_card(card["id"],
                                                       api_headers_admin()))
        assert after_approval["lifecycle_status"] == "ACTIVE"
        assert after_approval["photo_status"] == "APPROVED"
        assert after_approval["is_provisional"] is False

    def test_lost_freeze_unfreeze_cycle_preserves_photo_dimension(self, api):
        """PRD §3.2: "Reporting moves the card `ACTIVE` → `LOST_FROZEN`, increments
        the card's `lost_or_stolen_report_count` by 1, and suspends every `ACTIVE`
        access grant on the card with `suspended_reason` `CARD_FROZEN`."
        PRD §3.2: "unfreezing moves `LOST_FROZEN` → `ACTIVE`, provided the holder's
        `status` is `ACTIVE` (otherwise `ERR_HOLDER_NOT_ACTIVE`), and restores every
        grant suspended with `suspended_reason` `CARD_FROZEN` back to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/campus_card_parallel_dimensions_with_freeze_cycle
        """
        from test_helpers import TEST_USERS
        set_clock("2026-08-25T09:00:00Z")
        holder = create_holder(university_id="U4001", full_name="Fay Staff",
                               email="fay@x.edu", holder_type="STAFF",
                               housing_status="OFF_CAMPUS")
        card = issue_card(holder["id"])
        activate_card(card["id"], allow_provisional=True)
        photo = submit_photo(card["id"], holder["id"], image_ref="img://fay")
        review_photo(photo["id"], decision="APPROVED")

        lost_resp = api.report_card_lost(card["id"],
                                         make_cardholder_headers(holder["id"]))
        lost = validate_success(lost_resp, 200)
        assert lost["lifecycle_status"] == "LOST_FROZEN"
        assert lost["lost_or_stolen_report_count"] == 1

        back_resp = api.unfreeze_card(card["id"],
                                      make_cardholder_headers(holder["id"]))
        back = validate_success(back_resp, 200)
        assert back["lifecycle_status"] == "ACTIVE"
        after = get_success_data(
            api.get_card(card["id"], TEST_USERS["card_office_admin_headers"]))
        assert after["photo_status"] == "APPROVED"
        assert after["is_provisional"] is False
