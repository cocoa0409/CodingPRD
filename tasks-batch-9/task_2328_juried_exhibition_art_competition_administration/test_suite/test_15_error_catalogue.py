"""The refusal catalogue: every declared code observed on the operation that
raises it, at the precedence the ladder fixes, with the state that must survive a
refusal read back afterwards."""

from test_helpers import (
    CALL_MANAGER,
    FINANCE_A,
    FINANCE_B,
    JURY_CHAIR_A,
    JURY_CHAIR_B,
    REGISTRAR,
    ApiErrorId,
    create_artwork_image_payload,
    create_artwork_payload,
    create_assignment_payload,
    create_condition_report_payload,
    create_entry_payload,
    create_installation_plan_payload,
    create_jury_round_payload,
    create_sale_payload,
    create_score_payload,
    fixtures,
    make_artist_headers,
    make_juror_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# ─── Unissued identifiers ─────────────────────────────

# Well-formed UUIDs the server has never issued, one per entity family.
UNKNOWN_ARTIST = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ARTWORK = "00000000-0000-4000-8000-000000000002"
UNKNOWN_JUROR = "00000000-0000-4000-8000-000000000003"
UNKNOWN_JURY_ROUND = "00000000-0000-4000-8000-000000000004"
UNKNOWN_ASSIGNMENT = "00000000-0000-4000-8000-000000000005"
UNKNOWN_WALL_SEGMENT = "00000000-0000-4000-8000-000000000006"
UNKNOWN_AWARD = "00000000-0000-4000-8000-000000000007"
UNKNOWN_SALE = "00000000-0000-4000-8000-000000000008"
UNKNOWN_SCORE = "00000000-0000-4000-8000-000000000009"
UNKNOWN_ENTRY = "00000000-0000-4000-8000-000000000010"

# ─── Reference works ──────────────────────────────────

ONE_WORK = [fixtures.WORK_RIDGE_LINE]
TWO_WORKS = [fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT]

MEMBER_ONE_WORK_FEE_CENTS = 3713
NON_MEMBER_ONE_WORK_FEE_CENTS = 4500

# ─── Attachment limits ────────────────────────────────

RESTRICTED_CALL = {
    "allowed_media_categories": ["PAINTING", "PHOTOGRAPHY"],
    "eligible_state_codes": ["CA"],
    "max_dimension_cm": 200,
    "max_weight_kg": 40,
    "max_works_per_entry": 2,
    "max_entries_per_artist": 1,
}

CAST_FORM_SCULPTURE = {
    "title": "Cast Form", "medium_category": "SCULPTURE",
    "width_cm": 40.0, "height_cm": 40.0, "depth_cm": 40.0, "weight_kg": 10.0,
    "declared_value_cents": 200000,
}
LONG_PANEL = {
    "title": "Long Panel", "medium_category": "PAINTING",
    "width_cm": 210.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
    "declared_value_cents": 200000,
}
HEAVY_SLAB = {
    "title": "Heavy Slab", "medium_category": "PAINTING",
    "width_cm": 100.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 45.0,
    "declared_value_cents": 200000,
}
THIRD_WORK = {
    "title": "Third Work", "medium_category": "PAINTING",
    "width_cm": 50.0, "height_cm": 50.0, "depth_cm": 4.0, "weight_kg": 3.0,
    "declared_value_cents": 100000,
}

FUTURE_CAPTURE_DATE = "2027-01-01T00:00:00Z"

# ─── Windows ──────────────────────────────────────────

BEFORE_THE_DEADLINE = "2026-09-20T00:00:00Z"
CALL_CLOSES_AT = "2026-10-01T00:00:00Z"
ROUND_CLOSES_AT = "2026-10-12T00:00:00Z"
ONE_SECOND_AFTER_ROUND_CLOSE = "2026-10-12T00:00:01Z"
ONE_SECOND_AFTER_DELIVERY_WINDOW = "2026-11-07T00:00:00Z"

# ─── Jury figures ─────────────────────────────────────

EIGHT_ACROSS = (8, 8, 8)
EIGHT_COMPOSITE = 8.00
FIVE_ACROSS = (5, 5, 5)
FIVE_COMPOSITE = 5.00
CLEARING_CARD = (7, 8, 9)

# ─── Insurance and delivery ───────────────────────────

INSURANCE_CAP_CENTS = 500000

WORK_UNDER_CAP = {
    "title": "Ridge Line", "medium_category": "PAINTING",
    "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
    "declared_value_cents": 400000,
}
WORK_OVER_CAP = {
    "title": "Salt Flat", "medium_category": "PHOTOGRAPHY",
    "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
    "declared_value_cents": 600000,
}
WORK_LATE_ARRIVAL = {
    "title": "Cast Form", "medium_category": "SCULPTURE",
    "width_cm": 40.0, "height_cm": 40.0, "depth_cm": 40.0, "weight_kg": 10.0,
    "declared_value_cents": 100000,
}
INSURED_TOTAL_OF_TWO_DELIVERIES = 1000000

# ─── Awards ───────────────────────────────────────────

COUNCIL_AWARD_BUDGET_CENTS = 500000
OVERSIZED_PRIZE_CENTS = 600000
SPONSOR_PURCHASE_BUDGET_CENTS = 200000
PURCHASE_PRIZE_CENTS = 300000

# ─── Sales ────────────────────────────────────────────

NOT_FOR_SALE_WORK = {
    "title": "Study in Grey", "medium_category": "PHOTOGRAPHY",
    "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
    "declared_value_cents": 300000, "for_sale": False,
}
BUYER_NAME = "K. Adeyemi"
SALE_PRICE_CENTS = 250000
HALF_A_PAYMENT_CENTS = 100000
ARTIST_PAYABLE_CENTS = 149425


# ─── One 404 code per family ───────────────────────────

def test_each_entity_family_answers_an_unknown_id_with_its_own_code(api):
    """PRD §2.5: "Each entity type has its own not-found code:
    `ERR_EXHIBITION_NOT_FOUND`, `ERR_ARTIST_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_ARTWORK_NOT_FOUND`, `ERR_JUROR_NOT_FOUND`, `ERR_JURY_ROUND_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_WALL_SEGMENT_NOT_FOUND`,
    `ERR_SPONSOR_NOT_FOUND`, `ERR_AWARD_NOT_FOUND`, `ERR_SALE_NOT_FOUND`, and
    `ERR_SCORE_NOT_FOUND`, each returning HTTP 404."

    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    PRD §2.2: "The `message` provides a human-readable explanation of what went
    wrong."

    Design: Corner/errors/unknown_ids_across_every_entity_family_return_not_found
    """
    probes = [
        (api.get_artist(UNKNOWN_ARTIST, CALL_MANAGER),
         ApiErrorId.ERR_ARTIST_NOT_FOUND.value),
        (api.get_entry(UNKNOWN_ENTRY, CALL_MANAGER),
         ApiErrorId.ERR_ENTRY_NOT_FOUND.value),
        (api.get_artwork(UNKNOWN_ARTWORK, REGISTRAR),
         ApiErrorId.ERR_ARTWORK_NOT_FOUND.value),
        (api.get_juror(UNKNOWN_JUROR, JURY_CHAIR_A),
         ApiErrorId.ERR_JUROR_NOT_FOUND.value),
        (api.get_jury_round(UNKNOWN_JURY_ROUND, JURY_CHAIR_A),
         ApiErrorId.ERR_JURY_ROUND_NOT_FOUND.value),
        (api.get_juror_assignment(UNKNOWN_ASSIGNMENT, JURY_CHAIR_A),
         ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND.value),
        (api.get_wall_segment(UNKNOWN_WALL_SEGMENT, REGISTRAR),
         ApiErrorId.ERR_WALL_SEGMENT_NOT_FOUND.value),
        (api.get_award(UNKNOWN_AWARD, JURY_CHAIR_A),
         ApiErrorId.ERR_AWARD_NOT_FOUND.value),
        (api.get_sale(UNKNOWN_SALE, FINANCE_A),
         ApiErrorId.ERR_SALE_NOT_FOUND.value),
        (api.get_score(UNKNOWN_SCORE, JURY_CHAIR_A),
         ApiErrorId.ERR_SCORE_NOT_FOUND.value),
    ]

    for response, expected_code in probes:
        error = validate_error(response, expected_code, 404)
        assert error["error_id"] == expected_code
        assert error["message"].strip(), "the envelope carries a readable message"


# ─── Four state codes, one per record type ─────────────

def test_the_blocked_records_type_decides_which_state_code_comes_back(api):
    """PRD §2.10: "When several checks could reject the same request, the server
    applies them in a fixed order and returns the error of the **first** check
    that fails."

    PRD §2.10: "**Target state** — the target record is in a state from which the
    requested transition is declared, else the state code for that record type:
    `ERR_ENTRY_STATE_INVALID`, `ERR_ARTWORK_STATE_INVALID`,
    `ERR_JURY_ROUND_STATE_INVALID`, `ERR_AWARD_STATE_INVALID`,
    `ERR_SALE_STATE_INVALID`, or `ERR_ASSIGNMENT_STATE_INVALID`, all HTTP 409.
    Applies to every action endpoint."

    PRD §3.7: "Marking the work physically hung then carries it
    `PLANNED → INSTALLED` and requires only that the exhibition still be in
    `INSTALLATION`."

    Design: Corner/errors/entity_state_invalid_codes_rejected
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, artworks = fixtures.setup_entry_with_works(
        exhibition["id"], artist, ONE_WORK
    )
    artwork_id = artworks[0]["id"]
    artist_headers = make_artist_headers(artist["id"])

    pending = fixtures.submit_entry(entry["id"], artist)
    assert pending["status"] == "PENDING_FEE"
    assert pending["entry_fee_cents"] == MEMBER_ONE_WORK_FEE_CENTS

    resubmit = api.submit_entry(entry["id"], artist_headers)
    validate_error(resubmit, ApiErrorId.ERR_ENTRY_STATE_INVALID.value, 409)
    unchanged_entry = fixtures.read_entry(entry["id"])
    assert unchanged_entry["status"] == "PENDING_FEE"
    assert unchanged_entry["version"] == pending["version"]

    before_install = fixtures.read_artwork(artwork_id)
    assert before_install["placement_status"] == "UNPLACED"
    early_install = api.install_artwork(artwork_id, REGISTRAR)
    validate_error(early_install, ApiErrorId.ERR_ARTWORK_STATE_INVALID.value, 409)
    after_install = fixtures.read_artwork(artwork_id)
    assert after_install["placement_status"] == "UNPLACED"
    assert after_install["version"] == before_install["version"]

    fixtures.pay_entry_fee(entry["id"], artist, MEMBER_ONE_WORK_FEE_CENTS)
    fixtures.enter_jurying(exhibition["id"])
    juror = fixtures.invite_and_confirm_juror(expertise_categories=["PAINTING"])
    jury_round = fixtures.create_jury_round(exhibition["id"])
    assignment = fixtures.book_session(jury_round["id"], juror)

    opened = fixtures.set_round_status(jury_round["id"], "OPEN")
    assert opened["status"] == "OPEN"
    reopen = api.set_jury_round_status(
        jury_round["id"], {"target_status": "OPEN"}, JURY_CHAIR_A
    )
    validate_error(reopen, ApiErrorId.ERR_JURY_ROUND_STATE_INVALID.value, 409)
    still_open = fixtures.read_jury_round(jury_round["id"])
    assert still_open["status"] == "OPEN"
    assert still_open["reopen_count"] == 0
    assert still_open["version"] == opened["version"]

    cancelled = validate_success(
        api.cancel_juror_assignment(assignment["id"], JURY_CHAIR_A)
    )
    assert cancelled["status"] == "CANCELLED"
    recancel = api.cancel_juror_assignment(assignment["id"], JURY_CHAIR_A)
    validate_error(recancel, ApiErrorId.ERR_ASSIGNMENT_STATE_INVALID.value, 409)
    still_cancelled = fixtures.read_assignment(assignment["id"])
    assert still_cancelled["status"] == "CANCELLED"
    assert still_cancelled["version"] == cancelled["version"]


# ─── The deadline instant, from both sides ─────────────

def test_the_deadline_instant_closes_submission_and_opens_jurying(api):
    """PRD §2.10: "**Call window open** — the clock is strictly before
    `call_closes_at`, else `ERR_CALL_WINDOW_CLOSED` (409). Applies to opening an
    entry, attaching an artwork, submitting an entry, paying a fee, and opening the
    call for entries."

    PRD §2.10: "**Call window closed** — the clock has reached `call_closes_at`,
    else `ERR_CALL_WINDOW_NOT_CLOSED` (409). Applies to advancing to jurying."

    PRD §3.1: "Moving on to `JURYING` is the mirror image: it is refused with
    `ERR_CALL_WINDOW_NOT_CLOSED` until the clock has reached `call_closes_at`,
    because the docket must be final before jurors see it."

    PRD §3.2: "The entry is created in `DRAFT` with `entry_fee_cents` at 0 —
    nothing is assessed until submission."

    Design: Corner/errors/call_window_boundary_errors_rejected
    """
    exhibition = fixtures.open_call(clock=BEFORE_THE_DEADLINE)
    assert exhibition["call_closes_at"] == CALL_CLOSES_AT
    artist = fixtures.register_artist(member_status="MEMBER")
    entry, _ = fixtures.setup_entry_with_works(
        exhibition["id"], artist, ONE_WORK
    )

    too_early = api.advance_exhibition_phase(
        exhibition["id"], {"target_status": "JURYING"}, CALL_MANAGER
    )
    validate_error(too_early, ApiErrorId.ERR_CALL_WINDOW_NOT_CLOSED.value, 409)
    assert fixtures.read_exhibition(exhibition["id"])["status"] == (
        "OPEN_FOR_ENTRIES"
    )

    fixtures.set_clock(CALL_CLOSES_AT)
    too_late = api.submit_entry(entry["id"], make_artist_headers(artist["id"]))
    validate_error(too_late, ApiErrorId.ERR_CALL_WINDOW_CLOSED.value, 409)

    still_draft = fixtures.read_entry(entry["id"])
    assert still_draft["status"] == "DRAFT"
    assert still_draft["submitted_at"] is None
    assert still_draft["entry_fee_cents"] == 0, "nothing was frozen"

    now_permitted = validate_success(
        api.advance_exhibition_phase(
            exhibition["id"], {"target_status": "JURYING"}, CALL_MANAGER
        )
    )
    assert now_permitted["status"] == "JURYING", (
        "the same instant that closed submission satisfies the jurying gate"
    )


# ─── Per-call admissibility limits ─────────────────────

def test_every_call_specific_attachment_limit_reports_its_own_code(api):
    """PRD §3.2: "Three admissibility checks then run: the `medium_category` must
    be one of the call's `allowed_media_categories`, or
    `ERR_MEDIA_CATEGORY_NOT_ALLOWED`; `longest_edge_cm` must not exceed
    `max_dimension_cm` and `weight_kg` must not exceed the exhibition's
    `max_weight_kg`, or `ERR_SIZE_LIMIT_EXCEEDED`; and the entry's `works_count` —
    the number of its works whose `status` is anything other than `WITHDRAWN` —
    must stay within `max_works_per_entry`, or `ERR_MAX_WORKS_EXCEEDED`."

    PRD §3.2: "Two gates apply at this point: the artist's `residency_state_code`
    must appear in the call's `eligible_state_codes`, or the request is refused
    with `ERR_ELIGIBILITY_NOT_MET`; and the artist's existing entries in this
    exhibition whose `status` is `DRAFT`, `PENDING_FEE` or `SUBMITTED` must leave
    room under `max_entries_per_artist`, or the request is refused with
    `ERR_ENTRY_LIMIT_EXCEEDED`."

    PRD §3.2: "Two metadata criteria are checked separately and reported as
    `ERR_IMAGE_METADATA_INCOMPLETE`: `credit_line` must be non-empty, and
    `capture_date` must be present and must not fall after the current logical
    clock."

    Design: Corner/errors/artwork_attachment_constraint_errors_rejected
    """
    exhibition = fixtures.open_call(**RESTRICTED_CALL)
    artist = fixtures.register_artist(residency_state_code="CA")
    artist_headers = make_artist_headers(artist["id"])
    entry = fixtures.open_entry(exhibition["id"], artist)
    first = fixtures.attach_work(
        entry["id"], artist, with_primary_image=False, **fixtures.WORK_RIDGE_LINE
    )
    fixtures.attach_work(
        entry["id"], artist, with_primary_image=False, **fixtures.WORK_SALT_FLAT
    )

    wrong_medium = api.attach_artwork(
        entry["id"], create_artwork_payload(**CAST_FORM_SCULPTURE), artist_headers
    )
    validate_error(
        wrong_medium, ApiErrorId.ERR_MEDIA_CATEGORY_NOT_ALLOWED.value, 422
    )

    too_long = api.attach_artwork(
        entry["id"], create_artwork_payload(**LONG_PANEL), artist_headers
    )
    validate_error(too_long, ApiErrorId.ERR_SIZE_LIMIT_EXCEEDED.value, 422)

    too_heavy = api.attach_artwork(
        entry["id"], create_artwork_payload(**HEAVY_SLAB), artist_headers
    )
    validate_error(too_heavy, ApiErrorId.ERR_SIZE_LIMIT_EXCEEDED.value, 422)

    one_too_many = api.attach_artwork(
        entry["id"], create_artwork_payload(**THIRD_WORK), artist_headers
    )
    validate_error(one_too_many, ApiErrorId.ERR_MAX_WORKS_EXCEEDED.value, 422)
    assert fixtures.read_entry(entry["id"])["works_count"] == 2

    second_entry = api.create_entry(
        create_entry_payload(exhibition["id"], artist["id"]), artist_headers
    )
    validate_error(second_entry, ApiErrorId.ERR_ENTRY_LIMIT_EXCEEDED.value, 409)

    no_credit = api.upload_artwork_image(
        first["id"], create_artwork_image_payload(credit_line=""), artist_headers
    )
    validate_error(
        no_credit, ApiErrorId.ERR_IMAGE_METADATA_INCOMPLETE.value, 422
    )

    future_capture = api.upload_artwork_image(
        first["id"],
        create_artwork_image_payload(capture_date=FUTURE_CAPTURE_DATE),
        artist_headers,
    )
    validate_error(
        future_capture, ApiErrorId.ERR_IMAGE_METADATA_INCOMPLETE.value, 422
    )
    assert fixtures.read_artwork(first["id"])["primary_image_count"] == 0

    outsider = fixtures.register_artist(
        legal_name="Bo Nakamura", residency_state_code="NV"
    )
    ineligible = api.create_entry(
        create_entry_payload(exhibition["id"], outsider["id"]),
        make_artist_headers(outsider["id"]),
    )
    validate_error(ineligible, ApiErrorId.ERR_ELIGIBILITY_NOT_MET.value, 422)


# ─── One code for both sides of the image invariant ────

def test_one_code_guards_both_a_missing_and_a_duplicate_primary_image(api):
    """PRD §3.2: "An **ArtworkImage** record names its `role` — exactly one
    `PRIMARY` image per work, plus any number of `DETAIL` images — its container
    `format`, its `pixel_long_edge` and `pixel_short_edge`, its `file_bytes`, its
    `color_profile`, a `capture_date`, a `credit_line` naming the photographer, and
    a `checksum_sha256` digest recorded for provenance."

    PRD §3.2: "A successful upload refreshes the work's `primary_image_count`, the
    count of its images whose `role` is `PRIMARY`; an attempt to upload a second
    `PRIMARY` image for the same work is refused with
    `ERR_PRIMARY_IMAGE_REQUIRED`."

    PRD §3.3: "Submission requires that the exhibition be `OPEN_FOR_ENTRIES`, that
    the clock be strictly before `call_closes_at`, that `works_count` be at least
    1, that every work of the entry have a `primary_image_count` of at least 1 —
    otherwise `ERR_PRIMARY_IMAGE_REQUIRED` — and that the artist's
    `residency_state_code` still appear in `eligible_state_codes`."

    PRD §3.2: "Because a violating upload is refused rather than stored, every
    persisted image reports `standard_ok` as true."

    PRD §3.3: "The base line is the exhibition's `entry_fee_base_cents` multiplied
    by one minus that discount fraction, rounded half up to whole cents."

    Design: Corner/errors/primary_image_gate_errors_rejected
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="NON_MEMBER")
    artist_headers = make_artist_headers(artist["id"])
    entry = fixtures.open_entry(exhibition["id"], artist)
    artwork = fixtures.attach_work(
        entry["id"], artist, with_primary_image=False, **fixtures.WORK_RIDGE_LINE
    )
    assert fixtures.read_artwork(artwork["id"])["primary_image_count"] == 0

    unimaged = api.submit_entry(entry["id"], artist_headers)
    validate_error(unimaged, ApiErrorId.ERR_PRIMARY_IMAGE_REQUIRED.value, 409)
    assert fixtures.read_entry(entry["id"])["status"] == "DRAFT"

    primary = validate_success(
        api.upload_artwork_image(
            artwork["id"], create_artwork_image_payload(), artist_headers
        ),
        201,
    )
    assert primary["role"] == "PRIMARY"
    assert primary["standard_ok"] is True
    assert fixtures.read_artwork(artwork["id"])["primary_image_count"] == 1

    detail = validate_success(
        api.upload_artwork_image(
            artwork["id"],
            create_artwork_image_payload(role="DETAIL"),
            artist_headers,
        ),
        201,
    )
    assert detail["role"] == "DETAIL"
    assert fixtures.read_artwork(artwork["id"])["primary_image_count"] == 1, (
        "a DETAIL image is always admissible and does not touch the count"
    )

    second_primary = api.upload_artwork_image(
        artwork["id"], create_artwork_image_payload(), artist_headers
    )
    validate_error(
        second_primary, ApiErrorId.ERR_PRIMARY_IMAGE_REQUIRED.value, 409
    )
    assert fixtures.read_artwork(artwork["id"])["primary_image_count"] == 1

    submitted = validate_success(api.submit_entry(entry["id"], artist_headers))
    assert submitted["status"] == "PENDING_FEE"
    assert submitted["entry_fee_cents"] == NON_MEMBER_ONE_WORK_FEE_CENTS


# ─── Round and score refusals ──────────────────────────

def test_round_uniqueness_juror_readiness_and_the_scoring_window(api):
    """PRD §3.5: "A `JuryChair` creates each **JuryRound** against an
    `exhibition_id` with a `round_number` — at least 1, and unique within that
    exhibition, else `ERR_DUPLICATE_ROUND_NUMBER` — and a `round_type` of either
    `BLIND_SCORING`, which masks artist identity from juror readers, or
    `DELIBERATION`, which reveals it."

    PRD §3.4: "The juror must be `CONFIRMED`, or the booking is refused with
    `ERR_JUROR_NOT_CONFIRMED`."

    PRD §3.5: "Four gates apply beyond the standard ladder: the juror must be
    `CONFIRMED`; the clock must lie inside the round's closed
    `[opens_at, closes_at]` window, else `ERR_SCORING_WINDOW_CLOSED`; the scored
    work must belong to the round's exhibition, else
    `ERR_EXHIBITION_SCOPE_MISMATCH`; and no score may already exist for this
    combination of round, work and juror, else `ERR_DUPLICATE_SCORE`."

    Design: Corner/errors/jury_round_and_score_errors_rejected
    """
    exhibition = fixtures.open_call()
    artist = fixtures.register_artist(member_status="MEMBER")
    _, artworks = fixtures.setup_submitted_entry(
        exhibition["id"], artist, TWO_WORKS
    )
    first_id, second_id = artworks[0]["id"], artworks[1]["id"]

    jury_round, juror = fixtures.setup_open_round(exhibition["id"])
    invited_only = fixtures.invite_juror(display_name="Noor Haddad")
    assert invited_only["status"] == "INVITED"

    fixtures.submit_score(jury_round["id"], juror, first_id, *EIGHT_ACROSS)
    assert fixtures.read_artwork(first_id)["provisional_mean_score"] == (
        EIGHT_COMPOSITE
    )

    duplicate_number = api.create_jury_round(
        create_jury_round_payload(
            exhibition["id"], round_number=1, round_type="DELIBERATION",
            opens_at="2026-10-13T00:00:00Z", closes_at="2026-10-15T00:00:00Z",
        ),
        JURY_CHAIR_A,
    )
    validate_error(
        duplicate_number, ApiErrorId.ERR_DUPLICATE_ROUND_NUMBER.value, 409
    )

    current_version = fixtures.read_jury_round(jury_round["id"])["version"]
    unconfirmed_booking = api.create_juror_assignment(
        jury_round["id"],
        create_assignment_payload(
            invited_only["id"], current_version,
            session_start_at="2026-10-07T09:00:00Z",
            session_end_at="2026-10-07T11:00:00Z",
        ),
        JURY_CHAIR_A,
    )
    validate_error(
        unconfirmed_booking, ApiErrorId.ERR_JUROR_NOT_CONFIRMED.value, 409
    )
    assert fixtures.read_juror(invited_only["id"])["assignment_count"] == 0, (
        "the refused booking wrote nothing"
    )

    repeat = api.submit_score(
        jury_round["id"],
        create_score_payload(first_id, *FIVE_ACROSS),
        make_juror_headers(juror["id"]),
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_SCORE.value, 409)
    assert fixtures.read_artwork(first_id)["provisional_mean_score"] == (
        EIGHT_COMPOSITE
    ), "the rejected card was never applied"

    fixtures.set_clock(ONE_SECOND_AFTER_ROUND_CLOSE)
    late = api.submit_score(
        jury_round["id"],
        create_score_payload(second_id, *EIGHT_ACROSS),
        make_juror_headers(juror["id"]),
    )
    validate_error(late, ApiErrorId.ERR_SCORING_WINDOW_CLOSED.value, 409)

    after = fixtures.read_jury_round(jury_round["id"])
    assert after["status"] == "OPEN", "the window closed, the round did not"
    assert after["closes_at"] == ROUND_CLOSES_AT
    assert after["scored_artwork_count"] == 1


# ─── A conflict is declared against the artist ─────────

def test_a_declared_conflict_blocks_that_artists_work_and_no_others(api):
    """PRD §2.9: "A related but distinct safeguard governs the jury: a juror who
    has declared a conflict of interest with an artist may not score that artist's
    work, and the attempt is rejected with `ERR_JUROR_CONFLICT_DECLARED`
    (HTTP 403)."

    PRD §3.4: "Going forward, the same juror is refused with
    `ERR_JUROR_CONFLICT_DECLARED` on any attempt to score that artist's work."

    PRD §3.4: "A juror's `conflict_count` reports how many declarations they have
    filed."

    Design: Corner/errors/juror_conflict_declared_score_rejected
    """
    exhibition = fixtures.open_call()
    conflicted_artist = fixtures.register_artist(legal_name="Ana Ruiz")
    other_artist = fixtures.register_artist(legal_name="Bo Nakamura")
    _, conflicted_works = fixtures.setup_submitted_entry(
        exhibition["id"], conflicted_artist, ONE_WORK
    )
    _, other_works = fixtures.setup_submitted_entry(
        exhibition["id"], other_artist, [fixtures.WORK_SALT_FLAT]
    )
    conflicted_id = conflicted_works[0]["id"]
    other_id = other_works[0]["id"]

    jury_round, juror = fixtures.setup_open_round(exhibition["id"])
    declaration = fixtures.file_conflict_declaration(
        juror, conflicted_artist, "TEACHER_STUDENT"
    )
    assert declaration["relation_type"] == "TEACHER_STUDENT"
    assert declaration["voided_score_count"] == 0, "no score was cast yet"

    blocked = api.submit_score(
        jury_round["id"],
        create_score_payload(conflicted_id, 9, 9, 9),
        make_juror_headers(juror["id"]),
    )
    validate_error(
        blocked, ApiErrorId.ERR_JUROR_CONFLICT_DECLARED.value, 403
    )
    untouched = fixtures.read_artwork(conflicted_id)
    assert untouched["valid_score_count"] == 0
    assert untouched["provisional_mean_score"] is None

    permitted = fixtures.submit_score(
        jury_round["id"], juror, other_id, *EIGHT_ACROSS
    )
    assert permitted["composite_score"] == EIGHT_COMPOSITE, (
        "the block is scoped to the conflicted artist, not to the juror"
    )

    assert fixtures.read_juror(juror["id"])["conflict_count"] == 1
    _, meta = validate_paginated(
        api.list_artist_conflict_declarations(
            conflicted_artist["id"], JURY_CHAIR_A
        )
    )
    assert meta["total_count"] == 1


# ─── An empty candidate set is a refusal ───────────────

def test_an_all_declined_docket_refuses_the_acceptance_run_outright(api):
    """PRD §3.6: "The candidate set is every artwork of the exhibition whose
    `status` is `SHORTLISTED` **and** whose owning entry's `status` is
    `SUBMITTED`."

    PRD §3.6: "If the candidate set is empty the whole run is refused with
    `ERR_NO_ELIGIBLE_ARTWORKS` and no state changes at all — the exhibition stays
    in `JURYING`."

    Design: Corner/errors/no_eligible_artworks_acceptance_list_rejected
    """
    ctx = fixtures.setup_shortlisted_show(
        works=ONE_WORK, scores=[FIVE_ACROSS]
    )
    exhibition_id = ctx["exhibition"]["id"]
    artwork_id = ctx["artworks"][0]["id"]

    declined = fixtures.read_artwork(artwork_id)
    assert declined["certified_mean_score"] == FIVE_COMPOSITE
    assert declined["status"] == "DECLINED", (
        "a certified mean below the advance threshold declines the work"
    )

    before = fixtures.read_exhibition(exhibition_id)
    assert before["status"] == "JURYING"

    refused = api.run_acceptance_list(
        exhibition_id, {"expected_exhibition_version": before["version"]},
        JURY_CHAIR_A,
    )
    validate_error(refused, ApiErrorId.ERR_NO_ELIGIBLE_ARTWORKS.value, 409)

    after = fixtures.read_exhibition(exhibition_id)
    assert after["status"] == "JURYING"
    assert after["accepted_count"] == 0
    assert after["waitlisted_count"] == 0
    assert after["version"] == before["version"], "no state changes at all"


# ─── Three physical-phase guards ───────────────────────

def test_the_physical_phase_guards_fire_at_three_different_moments(api):
    """PRD §3.7: "Entering the installation phase is gated on two things beyond
    being in `RESULTS_PUBLISHED`: at least one wall segment must already be
    registered for the exhibition, else `ERR_WALL_SEGMENT_REQUIRED`, and the clock
    must not yet have passed `delivery_window_end_at`, else
    `ERR_DELIVERY_WINDOW_INVALID` — there is no point opening intake after the
    delivery window has expired."

    PRD §2.10: "**Insurance ceiling** — `declared_value_cents` is at most
    `per_work_insurance_cap_cents`, else `ERR_INSURANCE_COVERAGE_MISSING` (409).
    Applies to the installation plan."

    PRD §2.10: "**Body schema** — required fields present, enum members drawn from
    the declared sets, integers within range (each score criterion from 1 to 10
    inclusive, `photo_count` at least 1, cent amounts non-negative),
    `span_start_cm` strictly less than `span_end_cm`, the three score weights
    summing to exactly 1.00, `damage_notes` present when `condition_grade` is
    `DAMAGED`, `list_price_cents` present when `for_sale` is true, and both
    `carrier` and `tracking_number` present when `return_method` is `COURIER`."

    PRD §2.10: "Any violation is `ERR_INVALID_REQUEST` (400)."

    PRD §3.7: "An `INTAKE` report is the event that acknowledges delivery: it
    carries the work `ACCEPTED → DELIVERED`, requires the exhibition to be in
    `INSTALLATION`, and requires the clock to lie inside the closed
    `[delivery_window_start_at, delivery_window_end_at]` interval, else
    `ERR_DELIVERY_WINDOW_INVALID`."

    PRD §3.7: "Coverage is defined by state: `insured_value_total_cents` is the sum
    of `declared_value_cents` over the exhibition's works whose `status` is
    `DELIVERED`, `ON_VIEW` or `SOLD`."

    Design: Corner/errors/delivery_insurance_and_span_input_errors_rejected
    """
    ctx = fixtures.setup_shortlisted_show(
        works=[WORK_UNDER_CAP, WORK_OVER_CAP, WORK_LATE_ARRIVAL],
        exhibition_overrides={
            "per_work_insurance_cap_cents": INSURANCE_CAP_CENTS
        },
        scores=[CLEARING_CARD] * 3,
    )
    exhibition_id = ctx["exhibition"]["id"]
    under_cap, over_cap, late_arrival = (
        artwork["id"] for artwork in ctx["artworks"]
    )
    result = fixtures.run_acceptance_list(exhibition_id)
    assert result["accepted_count"] == 3

    no_inventory = api.advance_exhibition_phase(
        exhibition_id, {"target_status": "INSTALLATION"}, CALL_MANAGER
    )
    validate_error(
        no_inventory, ApiErrorId.ERR_WALL_SEGMENT_REQUIRED.value, 409
    )
    assert fixtures.read_exhibition(exhibition_id)["status"] == (
        "RESULTS_PUBLISHED"
    )

    wall = fixtures.register_wall(exhibition_id)
    assert fixtures.enter_installation(exhibition_id)["status"] == "INSTALLATION"

    for artwork_id in (under_cap, over_cap):
        fixtures.file_condition_report(artwork_id, "INTAKE", "A")
        assert fixtures.read_artwork(artwork_id)["status"] == "DELIVERED"
    wall_before = fixtures.read_wall(wall["id"])

    uninsurable = api.file_installation_plan(
        over_cap,
        create_installation_plan_payload(
            wall["id"], 300.0, 400.0, wall_before["version"]
        ),
        REGISTRAR,
    )
    validate_error(
        uninsurable, ApiErrorId.ERR_INSURANCE_COVERAGE_MISSING.value, 409
    )
    assert fixtures.read_wall(wall["id"])["version"] == wall_before["version"]

    zero_width = api.file_installation_plan(
        under_cap,
        create_installation_plan_payload(
            wall["id"], 100.0, 100.0, wall_before["version"]
        ),
        REGISTRAR,
    )
    validate_error(zero_width, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
    assert fixtures.read_artwork(under_cap)["placement_status"] == "UNPLACED"

    assert fixtures.read_exhibition(exhibition_id)[
        "insured_value_total_cents"
    ] == INSURED_TOTAL_OF_TWO_DELIVERIES

    fixtures.set_clock(ONE_SECOND_AFTER_DELIVERY_WINDOW)
    late = api.file_condition_report(
        late_arrival, create_condition_report_payload("INTAKE", "A"), REGISTRAR
    )
    validate_error(late, ApiErrorId.ERR_DELIVERY_WINDOW_INVALID.value, 409)
    assert fixtures.read_artwork(late_arrival)["status"] == "ACCEPTED"


# ─── Two budgets guard one confirmation ────────────────

def test_neither_budget_is_tested_before_the_confirmation_that_commits(api):
    """PRD §3.8: "Two budget tests then apply, each to its own kind of award: for
    an award with no sponsor, the exhibition's `award_committed_cents` plus this
    award's `prize_cents` must be at most `award_budget_cents`, else
    `ERR_AWARD_BUDGET_EXCEEDED`; and for a `PURCHASE_AWARD`, the sponsor's
    `purchase_award_committed_cents` plus this award's `prize_cents` must be at
    most that sponsor's `purchase_award_budget_cents`, else
    `ERR_SPONSOR_BUDGET_EXCEEDED`."

    PRD §3.8: "An award that is not `PROPOSED` when confirmation is requested, or
    not `CONFIRMED` when rescission is requested, is refused with
    `ERR_AWARD_STATE_INVALID`."

    PRD §3.8: "The award is created at `status` `PROPOSED` with
    `proposed_by_user_id` set to the acting chair's opaque identity."

    Design: Corner/errors/award_state_and_budget_errors_rejected
    """
    ctx = fixtures.setup_on_view_show(
        works=TWO_WORKS,
        exhibition_overrides={
            "award_budget_cents": COUNCIL_AWARD_BUDGET_CENTS
        },
    )
    exhibition_id = ctx["exhibition"]["id"]
    honoured, purchased = ctx["accepted_artwork_ids"]
    sponsor = fixtures.register_sponsor(
        exhibition_id,
        purchase_award_budget_cents=SPONSOR_PURCHASE_BUDGET_CENTS,
    )

    council_award = fixtures.propose_award(
        exhibition_id, honoured, "BEST_IN_SHOW", OVERSIZED_PRIZE_CENTS,
        headers=JURY_CHAIR_A,
    )
    purchase_award = fixtures.propose_award(
        exhibition_id, purchased, "PURCHASE_AWARD", PURCHASE_PRIZE_CENTS,
        headers=JURY_CHAIR_A, sponsor_id=sponsor["id"],
    )
    assert council_award["status"] == "PROPOSED"
    assert purchase_award["status"] == "PROPOSED"
    before = fixtures.read_exhibition(exhibition_id)
    assert before["award_committed_cents"] == 0

    premature_rescission = api.rescind_award(
        council_award["id"], {"reason": "wrong recipient"}, JURY_CHAIR_B
    )
    validate_error(
        premature_rescission, ApiErrorId.ERR_AWARD_STATE_INVALID.value, 409
    )

    over_council_budget = api.confirm_award(
        council_award["id"],
        {"expected_exhibition_version": before["version"]},
        JURY_CHAIR_B,
    )
    validate_error(
        over_council_budget, ApiErrorId.ERR_AWARD_BUDGET_EXCEEDED.value, 402
    )

    over_sponsor_budget = api.confirm_award(
        purchase_award["id"],
        {"expected_exhibition_version": before["version"]},
        JURY_CHAIR_B,
    )
    validate_error(
        over_sponsor_budget, ApiErrorId.ERR_SPONSOR_BUDGET_EXCEEDED.value, 402
    )
    assert PURCHASE_PRIZE_CENTS < COUNCIL_AWARD_BUDGET_CENTS, (
        "the purchase prize clears the council ceiling and fails its own"
    )

    for award_id in (council_award["id"], purchase_award["id"]):
        refused = fixtures.read_award(award_id)
        assert refused["status"] == "PROPOSED"
        assert refused["confirmed_by_user_id"] is None

    after = fixtures.read_exhibition(exhibition_id)
    assert after["award_committed_cents"] == 0
    assert after["version"] == before["version"]
    assert fixtures.read_sponsor(sponsor["id"])[
        "purchase_award_committed_cents"
    ] == 0
    _, sales_meta = validate_paginated(api.list_sales(FINANCE_A))
    assert sales_meta["total_count"] == 0, "no purchase sale was cascaded"


# ─── The money chain refuses each skipped step ─────────

def test_every_skipped_step_of_the_money_chain_has_its_own_refusal(api):
    """PRD §3.9: "The work must be `ON_VIEW`, must have `for_sale` true with a
    `list_price_cents` posted — otherwise `ERR_ARTWORK_NOT_FOR_SALE` — and must not
    already carry a sale in any state other than `VOIDED`."

    PRD §3.9: "Recording buyer payment carries it `INVOICED → PAID` and requires
    the tendered `amount_cents` to equal `buyer_total_cents` exactly, else
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    PRD §3.9: "A sale whose state does not admit the requested step is refused
    with `ERR_SALE_STATE_INVALID`."

    PRD §3.9: "Advancing to `PAYOUTS_RELEASED` requires that no sale of the
    exhibition still sit at `RECORDED` or `INVOICED` — every non-voided sale must
    have reached `PAID` or `PAYOUT_RELEASED` — and that `payouts_released_cents`
    equal `artist_payable_total_cents` exactly, else `ERR_PAYOUT_INCOMPLETE`."

    PRD §3.7: "When the work's status axis has reached `ON_VIEW` or
    `RETURN_PENDING`, a `DEINSTALL`-stage condition report must already exist for
    it, else the deinstall is refused with `ERR_CONDITION_REPORT_REQUIRED`."

    Design: Corner/errors/sales_payout_and_settlement_errors_rejected
    """
    ctx = fixtures.setup_on_view_show(
        works=[fixtures.WORK_RIDGE_LINE, NOT_FOR_SALE_WORK]
    )
    exhibition_id = ctx["exhibition"]["id"]
    offered_id = ctx["artworks"][0]["id"]
    withheld_id = ctx["artworks"][1]["id"]
    assert fixtures.read_artist(ctx["artist"]["id"])["tax_form_on_file"] is True

    not_for_sale = api.create_sale(
        create_sale_payload(
            withheld_id, buyer_name=BUYER_NAME,
            sale_price_cents=SALE_PRICE_CENTS,
        ),
        FINANCE_A,
    )
    validate_error(
        not_for_sale, ApiErrorId.ERR_ARTWORK_NOT_FOR_SALE.value, 422
    )
    assert fixtures.read_artwork(withheld_id)["status"] == "ON_VIEW"

    sale = validate_success(
        api.create_sale(
            create_sale_payload(
                offered_id, buyer_name=BUYER_NAME,
                sale_price_cents=SALE_PRICE_CENTS,
            ),
            FINANCE_A,
        ),
        201,
    )
    assert sale["status"] == "RECORDED"
    assert sale["buyer_total_cents"] == SALE_PRICE_CENTS

    early_payout = api.release_sale_payout(
        sale["id"],
        {"expected_exhibition_version": fixtures.exhibition_version(
            exhibition_id
        )},
        FINANCE_B,
    )
    validate_error(early_payout, ApiErrorId.ERR_SALE_STATE_INVALID.value, 409)

    invoiced = validate_success(api.invoice_sale(sale["id"], FINANCE_A))
    assert invoiced["status"] == "INVOICED"

    short_payment = api.record_sale_payment(
        sale["id"], {"amount_cents": HALF_A_PAYMENT_CENTS}, FINANCE_A
    )
    validate_error(
        short_payment, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH.value, 402
    )
    assert fixtures.read_sale(sale["id"])["status"] == "INVOICED"

    paid = validate_success(
        api.record_sale_payment(
            sale["id"], {"amount_cents": SALE_PRICE_CENTS}, FINANCE_A
        )
    )
    assert paid["status"] == "PAID"
    assert paid["artist_payable_cents"] == ARTIST_PAYABLE_CENTS

    reconciling = fixtures.advance_settlement(exhibition_id, "RECONCILING")
    assert reconciling["settlement_status"] == "RECONCILING"
    assert reconciling["artist_payable_total_cents"] == ARTIST_PAYABLE_CENTS
    assert reconciling["payouts_released_cents"] == 0

    premature_close = api.advance_settlement(
        exhibition_id, {"target_settlement_status": "PAYOUTS_RELEASED"},
        FINANCE_B,
    )
    validate_error(
        premature_close, ApiErrorId.ERR_PAYOUT_INCOMPLETE.value, 409
    )
    assert fixtures.read_exhibition(exhibition_id)["settlement_status"] == (
        "RECONCILING"
    )

    unreported = api.deinstall_artwork(withheld_id, REGISTRAR)
    validate_error(
        unreported, ApiErrorId.ERR_CONDITION_REPORT_REQUIRED.value, 409
    )
    assert fixtures.read_artwork(withheld_id)["placement_status"] == "INSTALLED"
