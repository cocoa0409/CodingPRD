"""Access control read as three separate layers: authentication ahead of role
permission, the role lists of §4 as hard boundaries with no hierarchy, ownership
for the two entity-backed roles, and the segregation of duties that splits the
two money decisions."""

from test_helpers import (
    CALL_MANAGER,
    FINANCE_A,
    FINANCE_B,
    JURY_CHAIR_A,
    JURY_CHAIR_A_USER_ID,
    JURY_CHAIR_B,
    REGISTRAR,
    TEST_USERS,
    ApiErrorId,
    build_user_headers,
    create_conflict_declaration_payload,
    create_entry_payload,
    create_exhibition_payload,
    create_installation_plan_payload,
    create_juror_payload,
    create_sale_payload,
    create_wall_segment_payload,
    fixtures,
    make_artist_headers,
    make_juror_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ONE_WORK = [fixtures.WORK_RIDGE_LINE]

# The `Artist` header pair with the identity half removed. Nothing else about
# the request is wrong, so only the authentication rung can fire.
ARTIST_WITHOUT_USER_ID_HEADER = {
    name: value
    for name, value in TEST_USERS["artist_headers"].items()
    if name != "X-User-ID"
}

# A role name outside the declared six, carried by an otherwise well-formed
# header pair.
UNDECLARED_ROLE_HEADERS = build_user_headers(JURY_CHAIR_A_USER_ID, "Curator")

# ─── Segregation of duties ────────────────────────────

AWARD_PRIZE_CENTS = 100000
SALE_PRICE_CENTS = 250000
ARTIST_PAYABLE_CENTS = 149425

# ─── Shared operations ────────────────────────────────

NON_MEMBER_ONE_WORK_FEE_CENTS = 4500


# ─── Role lists are boundaries, not a hierarchy ────────

def test_no_role_may_reach_across_into_another_roles_exclusive_operation(api):
    """PRD §2.1: "Every endpoint declares which of these roles may invoke it (see
    the table in §4); a request whose role is syntactically valid but not listed
    for the endpoint is rejected with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

    PRD §2.10: "**Role permission** — the acting role is listed for the endpoint,
    else `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

    PRD §4: "| `POST` | `/exhibitions` | Create an exhibition (call for entries
    configuration) in `DRAFT` / `NOT_STARTED`. | `CallManager` |"

    PRD §4: "| `POST` | `/jurors` | Invite a juror with declared expertise and
    honorarium terms. | `JuryChair` |"

    PRD §4: "| `POST` | `/entries` | Open a `DRAFT` entry for the acting artist
    against an `OPEN_FOR_ENTRIES` call. | `Artist` |"

    PRD §4: "| `POST` | `/artworks/{id}/installation-plan` | Reserve a buffered
    wall span for a delivered artwork. | `Registrar` |"

    PRD §4: "| `POST` | `/sales` | Record a gallery sale of a work on view
    (tax-inclusive posted price). | `FinanceOfficer` |"

    PRD §4: "| `POST` | `/exhibitions/{id}/unclaimed-sweep` | Accrue storage fees
    on unclaimed work at the current logical clock and forfeit works past the
    grace period. | `Registrar` |"

    PRD §4: "| `GET` | `/scores` | Filtered list of scores by round, artwork and
    juror. | `JuryChair`, `Juror` |"

    Design: Corner/rbac/role_not_permitted_on_other_roles_exclusive_operations_rejected
    """
    exhibition = fixtures.open_call()
    wall = fixtures.register_wall(exhibition["id"])
    artist = fixtures.register_artist()
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, ONE_WORK
    )
    artwork_id = artworks[0]["id"]

    # Each probe is refused on role grounds alone: every other input is valid.
    probes = [
        api.create_exhibition(
            create_exhibition_payload(title="Registrar's Own Season"), REGISTRAR
        ),
        api.create_juror(
            create_juror_payload(email="iris.vega@example.org"), CALL_MANAGER
        ),
        api.create_entry(
            create_entry_payload(exhibition["id"], artist["id"]), JURY_CHAIR_A
        ),
        api.file_installation_plan(
            artwork_id,
            create_installation_plan_payload(
                wall["id"], 0.0, 100.0, wall["version"]
            ),
            FINANCE_A,
        ),
        api.create_sale(create_sale_payload(artwork_id), REGISTRAR),
        api.run_unclaimed_sweep(
            exhibition["id"], make_artist_headers(artist["id"])
        ),
        api.list_scores(REGISTRAR),
    ]
    for response in probes:
        validate_error(response, ApiErrorId.ERR_ROLE_NOT_PERMITTED.value, 403)

    _, exhibitions_meta = validate_paginated(api.list_exhibitions(CALL_MANAGER))
    assert exhibitions_meta["total_count"] == 1, (
        "the registrar's creation attempt persisted nothing"
    )

    _, entries_meta = validate_paginated(api.list_entries(CALL_MANAGER))
    assert entries_meta["total_count"] == 1, "only the artist's own entry exists"
    assert fixtures.read_entry(entry["id"])["status"] == "DRAFT"

    _, sales_meta = validate_paginated(api.list_sales(FINANCE_A))
    assert sales_meta["total_count"] == 0

    _, scores_meta = validate_paginated(api.list_scores(JURY_CHAIR_A))
    assert scores_meta["total_count"] == 0

    assert fixtures.read_artwork(artwork_id)["placement_status"] == "UNPLACED"

    untouched_wall = fixtures.read_wall(wall["id"])
    assert untouched_wall["occupied_cm"] == 0.0
    assert untouched_wall["loaded_weight_kg"] == 0.0
    assert untouched_wall["version"] == wall["version"], (
        "the refused plan never reached the wall"
    )


# ─── Authentication is the first rung ──────────────────

def test_an_absent_identity_and_an_undeclared_role_both_fail_authentication(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting user, and `X-User-Role`, declaring the capacity in
    which they are acting."

    PRD §2.1: "If either header is absent, or if the supplied role is not one of
    the six roles the system recognises, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    PRD §2.1: "The six roles are `CallManager`, `JuryChair`, `Juror`, `Artist`,
    `Registrar`, and `FinanceOfficer`."

    PRD §2.10: "**Header authentication** — both auth headers present and the
    role recognised, else `ERR_UNAUTHENTICATED` (401). Applies to every
    endpoint."

    Design: Corner/rbac/missing_x_user_id_header_returns_unauthenticated
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist()

    headerless = api.create_entry(
        create_entry_payload(exhibition["id"], artist["id"]),
        ARTIST_WITHOUT_USER_ID_HEADER,
    )
    validate_error(headerless, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # `Curator` is not one of the six, so the request fails authentication
    # rather than the role-permission rung that would answer 403.
    undeclared_role = api.get_exhibition(
        exhibition["id"], UNDECLARED_ROLE_HEADERS
    )
    validate_error(undeclared_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    _, meta = validate_paginated(api.list_entries(CALL_MANAGER))
    assert meta["total_count"] == 0, "the header-less attempt created no entry"


# ─── Ownership for an entity-backed role ───────────────

def test_one_artist_may_not_patch_or_read_another_artists_record(api):
    """PRD §2.1: "An artist may only read and patch their own artist record."

    PRD §2.1: "An ownership violation by an entity-backed actor is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    PRD §2.1: "The ownership check applies to opening an entry, attaching an
    artwork to an entry, submitting an entry, paying an entry fee, withdrawing an
    entry, uploading an artwork image, confirming a juror invitation, resigning
    as a juror, filing a juror conflict declaration, and patching an artist
    record."

    PRD §3.2: "Administrative updates to an artist record may be made by the
    artist themselves on their own record, or by a `CallManager`; only a
    `CallManager` may supply `payout_hold` to lift a hold the system has
    imposed."

    Design: Corner/rbac/artist_cannot_patch_or_read_another_artists_records
    """
    exhibition = fixtures.open_call()
    # `member_status` starts at `NON_MEMBER` so the `CallManager`'s patch below
    # genuinely moves the field rather than rewriting the value it already held.
    owner = fixtures.register_artist(
        legal_name="Ana Ruiz", payout_method="CHECK", member_status="NON_MEMBER"
    )
    stranger = fixtures.register_artist(
        legal_name="Bea Lund", residency_state_code="OR"
    )
    entry = fixtures.open_entry(exhibition["id"], owner)

    owner_headers = make_artist_headers(owner["id"])
    stranger_headers = make_artist_headers(stranger["id"])

    foreign_patch = api.patch_artist(
        owner["id"], {"payout_method": "ACH"}, stranger_headers
    )
    validate_error(foreign_patch, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    foreign_read = api.get_artist(owner["id"], stranger_headers)
    validate_error(foreign_read, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)

    foreign_withdraw = api.withdraw_entry(entry["id"], stranger_headers)
    validate_error(
        foreign_withdraw, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403
    )

    unchanged = fixtures.read_artist(owner["id"])
    assert unchanged["payout_method"] == "CHECK"
    assert unchanged["version"] == owner["version"], (
        "a refused patch does not advance the record"
    )
    assert fixtures.read_entry(entry["id"])["status"] == "DRAFT"

    # The identical patch from the owning identity, and then from a
    # `CallManager`, both succeed — only foreign identity was the defect.
    by_owner = validate_success(
        api.patch_artist(owner["id"], {"payout_method": "ACH"}, owner_headers)
    )
    assert by_owner["payout_method"] == "ACH"
    assert by_owner["version"] == owner["version"] + 1

    by_manager = validate_success(
        api.patch_artist(
            owner["id"], {"member_status": "MEMBER"}, CALL_MANAGER
        )
    )
    assert by_manager["member_status"] == "MEMBER"
    assert by_manager["payout_method"] == "ACH"
    assert by_manager["version"] == owner["version"] + 2

    own_read = validate_success(api.get_artist(owner["id"], owner_headers))
    assert own_read["id"] == owner["id"]


# ─── The two split decisions ───────────────────────────

def test_the_setter_up_of_each_money_decision_cannot_also_take_it(api):
    """PRD §2.9: "The `X-User-ID` confirming an award must differ from the
    `proposed_by_user_id` recorded when the award was proposed, and the
    `X-User-ID` releasing an artist payout must differ from the
    `recorded_by_user_id` recorded when the sale was booked."

    PRD §2.9: "Both violations are rejected with `ERR_SEGREGATION_OF_DUTIES`
    (HTTP 403)."

    PRD §2.9: "Two decisions in this system may not be taken by the same operator
    who set them up, and the constraint is enforced on the opaque `X-User-ID`
    rather than on the role."

    PRD §3.8: "On success the award records `confirmed_by_user_id`, and either the
    exhibition's `award_committed_cents` — the sum of `prize_cents` over
    `CONFIRMED` awards with no sponsor — or the sponsor's
    `purchase_award_committed_cents` is recomputed."

    PRD §3.9: "On success the sale records `payout_released_by_user_id`, the
    exhibition's `payouts_released_cents` — the sum of `artist_payable_cents`
    over that exhibition's sales at `PAYOUT_RELEASED` — is recomputed, and both
    the exhibition's `version` and the sale's `version` increment by 1."

    Design: Corner/rbac/segregation_of_duties_second_step_by_the_same_user_rejected
    """
    ctx = fixtures.setup_sold_show(
        works=ONE_WORK, sale_overrides={"recorder": FINANCE_A}
    )
    exhibition_id = ctx["exhibition"]["id"]
    artwork_id = ctx["sold_artwork_id"]
    sale = ctx["sale"]
    assert sale["status"] == "PAID"
    assert sale["artist_payable_cents"] == ARTIST_PAYABLE_CENTS

    award = fixtures.propose_award(
        exhibition_id, artwork_id, "BEST_IN_SHOW", AWARD_PRIZE_CENTS,
        headers=JURY_CHAIR_A,
    )
    assert award["proposed_by_user_id"] == JURY_CHAIR_A_USER_ID

    fixtures.advance_settlement(exhibition_id, "RECONCILING", FINANCE_B)
    before = fixtures.read_exhibition(exhibition_id)

    same_chair = api.confirm_award(
        award["id"], {"expected_exhibition_version": before["version"]},
        JURY_CHAIR_A,
    )
    validate_error(same_chair, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    still_proposed = fixtures.read_award(award["id"])
    assert still_proposed["status"] == "PROPOSED"
    assert still_proposed["confirmed_by_user_id"] is None

    same_officer = api.release_sale_payout(
        sale["id"], {"expected_exhibition_version": before["version"]},
        FINANCE_A,
    )
    validate_error(same_officer, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)

    still_paid = fixtures.read_sale(sale["id"])
    assert still_paid["status"] == "PAID"
    assert still_paid["payout_released_by_user_id"] is None

    after_refusals = fixtures.read_exhibition(exhibition_id)
    assert after_refusals["award_committed_cents"] == 0
    assert after_refusals["payouts_released_cents"] == 0
    assert after_refusals["version"] == before["version"], (
        "the split-duty check runs before any ledger write"
    )

    # The same two steps taken by the second chair and the second officer.
    confirmed = fixtures.confirm_award(
        award["id"], exhibition_id, headers=JURY_CHAIR_B
    )
    assert confirmed["status"] == "CONFIRMED"
    released = fixtures.release_payout(
        sale["id"], exhibition_id, headers=FINANCE_B
    )
    assert released["status"] == "PAYOUT_RELEASED"

    settled = fixtures.read_exhibition(exhibition_id)
    assert settled["award_committed_cents"] == AWARD_PRIZE_CENTS
    assert settled["payouts_released_cents"] == ARTIST_PAYABLE_CENTS


# ─── A shared operation accepts every listed role ──────

def test_every_role_listed_on_a_shared_operation_is_actually_accepted(api):
    """PRD §4: "| `POST` | `/wall-segments` | Register a gallery wall segment for
    an exhibition. | `CallManager`, `Registrar` |"

    PRD §3.4: "Accepting the invitation advances the juror `INVITED → CONFIRMED`,
    and may be performed either by the juror on their own record or by the chair
    on their behalf."

    PRD §3.4: "Resignation, available from `INVITED` or `CONFIRMED` and likewise
    performable by either party, moves the juror to the terminal `RESIGNED`."

    PRD §3.4: "A juror's `conflict_count` reports how many declarations they have
    filed."

    PRD §3.3: "Withdrawal is available to the owning artist and to a
    `CallManager` from `DRAFT`, `PENDING_FEE` or `SUBMITTED`, and only while the
    exhibition is `OPEN_FOR_ENTRIES` or `JURYING`."

    PRD §3.3: "A successful withdrawal moves the entry to `WITHDRAWN`, moves each
    of its works whose `status` is `DRAFT`, `SUBMITTED` or `SHORTLISTED` to
    `WITHDRAWN`, and recomputes the exhibition's `shortlisted_count`."

    Design: Corner/rbac/shared_operations_accepted_for_every_permitted_role
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="NON_MEMBER")
    entry, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, ONE_WORK
    )
    assert entry["status"] == "SUBMITTED"
    assert entry["fee_paid_cents"] == NON_MEMBER_ONE_WORK_FEE_CENTS
    artwork_id = artworks[0]["id"]

    first_juror = fixtures.invite_juror(
        display_name="Iris Vega", email="iris.vega@example.org"
    )
    second_juror = fixtures.invite_juror(
        display_name="Omar Fell", email="omar.fell@example.org",
        honorarium_cents=40000,
    )

    by_manager = validate_success(
        api.create_wall_segment(
            create_wall_segment_payload(exhibition["id"], label="W1"),
            CALL_MANAGER,
        ),
        201,
    )
    by_registrar = validate_success(
        api.create_wall_segment(
            create_wall_segment_payload(
                exhibition["id"], label="W2", length_cm=400.0, max_weight_kg=50.0
            ),
            REGISTRAR,
        ),
        201,
    )
    assert {by_manager["label"], by_registrar["label"]} == {"W1", "W2"}

    walls, walls_meta = validate_paginated(
        api.list_wall_segments(
            JURY_CHAIR_A, params={"exhibition_id": exhibition["id"]}
        )
    )
    assert walls_meta["total_count"] == 2
    assert {wall["label"] for wall in walls} == {"W1", "W2"}

    # Confirmation by the juror's own identity, and by the chair on behalf of
    # the second juror.
    by_self = validate_success(
        api.confirm_juror(
            first_juror["id"], make_juror_headers(first_juror["id"])
        )
    )
    assert by_self["status"] == "CONFIRMED"

    by_chair = validate_success(
        api.confirm_juror(second_juror["id"], JURY_CHAIR_A)
    )
    assert by_chair["status"] == "CONFIRMED"

    resigned = validate_success(api.resign_juror(second_juror["id"], JURY_CHAIR_A))
    assert resigned["status"] == "RESIGNED"

    declaration = validate_success(
        api.file_conflict_declaration(
            first_juror["id"],
            create_conflict_declaration_payload(artist["id"], "FAMILY"),
            JURY_CHAIR_A,
        ),
        201,
    )
    assert declaration["juror_id"] == first_juror["id"]
    assert declaration["artist_id"] == artist["id"]
    assert declaration["relation_type"] == "FAMILY"
    assert fixtures.read_juror(first_juror["id"])["conflict_count"] == 1

    withdrawn = validate_success(
        api.withdraw_entry(entry["id"], CALL_MANAGER)
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert fixtures.read_artwork(artwork_id)["status"] == "WITHDRAWN"
