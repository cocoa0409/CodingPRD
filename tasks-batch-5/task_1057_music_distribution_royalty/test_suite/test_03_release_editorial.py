"""Building a record: release metadata, tracks, pre-save campaigns and editorial review."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    assert_release, assert_track, assert_collaborator,
    set_clock, create_plan, create_artist, create_active_subscription,
    create_release, add_track, create_collaborator, submit_release,
    read_release, read_subscription, read_track, CLOCK_BASE, upc, isrc,
    make_artist_headers, make_ops_headers, make_fan_headers, make_admin_headers,
)


def _artist_world(plan_kwargs=None, email="artist@example.com"):
    set_clock(CLOCK_BASE)
    plan = create_plan(**(plan_kwargs or {}))
    artist = create_artist(email=email)
    sub = create_active_subscription(artist["id"], plan["id"])
    return plan, artist, sub


def test_release_system_fields_are_server_generated(api):
    """PRD §3.3: "The new release starts with editorial `status` `DRAFT` and distribution
    `delivery_status` `NONE`, `pre_save_count` at 0, and `rejection_reason_code`, `submitted_at`
    and `taken_down_at` all null."
    PRD §3.3: "Pre-save behaviour may also be declared up front through `pre_save_enabled` (false
    when omitted) and `pre_save_opens_at`, which is null whenever pre-saves are disabled."
    PRD §2.4: "Most resources additionally carry `updated_at`, refreshed on every mutation of that
    row, and `version`, an integer that starts at 1 when the row is created and increases by
    exactly 1 on each mutation."

    Design: Corner/entities/release_system_fields_generated_and_client_input_ignored
    """
    plan, artist, _sub = _artist_world(email="stratus@example.com")

    release = validate_success(
        api.create_release(
            {"artist_id": artist["id"], "title": "Cloudbank",
             "release_date": "2026-09-01T00:00:00Z",
             "primary_genre": "Downtempo", "label_name": "Stratus Rec"},
            make_artist_headers(artist["id"]),
        ),
        201,
    )

    assert_release(release)
    assert release["status"] == "DRAFT"
    assert release["delivery_status"] == "NONE"
    assert release["pre_save_count"] == 0
    assert release["pre_save_enabled"] is False
    assert release["version"] == 1
    assert release["upc"] is None


def test_duplicate_upc_across_releases_rejected(api):
    """PRD §3.3: "A barcode may be supplied immediately as `upc` or left null and added later;
    when present it must be exactly 12 digits and must not already be in use by another release,
    on pain of `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/errors/duplicate_upc_across_releases_returns_4XX
    """
    plan, artist, _sub = _artist_world(email="caelum@example.com")
    create_release(artist["id"], title="Chisel A", upc="312345678928")

    resp = api.create_release(
        {"artist_id": artist["id"], "title": "Chisel B",
         "release_date": "2026-09-01T00:00:00Z", "primary_genre": "Pop",
         "label_name": "Caelum Rec", "upc": "312345678928"},
        make_artist_headers(artist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    _rows, meta = validate_paginated(
        api.list_releases(make_admin_headers(), params={"artist_id": artist["id"]})
    )
    assert meta["total_count"] == 1


def test_duplicate_track_number_within_release_rejected(api):
    """PRD §3.3: "Each track carries a `title`, a `duration_seconds` runtime of at least one whole
    second, and a `track_number`, a 1-based ordinal that must be at least 1 and must be unique
    within its release — a repeated ordinal is refused with `ERR_DUPLICATE_IDENTIFIER`."

    Design: Corner/entities/duplicate_track_number_within_release_rejected
    """
    plan, artist, _sub = _artist_world(email="lacerta@example.com")
    release = create_release(artist["id"], title="Lizard", upc=upc(1))
    add_track(release["id"], artist["id"], title="Scale", track_number=1, isrc=isrc(1))

    resp = api.add_track(
        release["id"],
        {"title": "Tail", "duration_seconds": 160, "track_number": 1, "isrc": isrc(2),
         "explicit": False},
        make_artist_headers(artist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER.value)

    _rows, meta = validate_paginated(
        api.list_tracks(make_admin_headers(), params={"release_id": release["id"]})
    )
    assert meta["total_count"] == 1


def test_collaborator_withholding_is_computed_from_paperwork_and_residence(api):
    """PRD §3.4: "Whenever a collaborator is registered or revised, the platform recomputes their
    `withholding_bps` — the rate at which tax will be withheld from their payouts — by walking
    four cases in a strictly pinned order."
    PRD §3.4: "First, if the payee's `tax_form_status` is either `MISSING` or `EXPIRED`, backup
    withholding applies at 2400 basis points, and this case overrides everything below it,
    including the domestic zero rate and any treaty relief, regardless of country."
    PRD §3.4: "Otherwise, if their `country_code` is `US`, the rate is 0 basis points."
    PRD §3.4: "`tax_form_status`, which is one of `MISSING`, `SUBMITTED`, `VERIFIED` or `EXPIRED`
    and defaults to `MISSING`"

    Design: Corner/entities/collaborator_withholding_bps_is_computed_and_client_value_ignored
    """
    plan, artist, _sub = _artist_world(email="nimbus@example.com")

    verified_us = validate_success(
        api.create_collaborator(
            {"artist_id": artist["id"], "name": "Verified US", "email": "vus@example.com",
             "country_code": "US", "tax_form_status": "VERIFIED"},
            make_artist_headers(artist["id"]),
        ),
        201,
    )
    no_form = validate_success(
        api.create_collaborator(
            {"artist_id": artist["id"], "name": "No Form", "email": "noform@example.com",
             "country_code": "DE"},
            make_artist_headers(artist["id"]),
        ),
        201,
    )

    assert_collaborator(verified_us)
    assert_collaborator(no_form)
    assert verified_us["withholding_bps"] == 0
    assert no_form["tax_form_status"] == "MISSING"
    assert no_form["withholding_bps"] == 2400, (
        "backup withholding overrides any treaty relief for a German payee with no paperwork"
    )


def test_enabling_content_id_without_plan_entitlement_rejected(api):
    """PRD §3.3: "Whenever `content_id_enabled` is being set to true — whether while adding a
    track or while later amending one — the platform checks the `allows_content_id` flag of the
    plan behind the artist's subscription, and refuses the request with
    `ERR_CONTENT_ID_NOT_ENTITLED` (HTTP 403) when that plan does not permit it."

    Design: Corner/validations/enabling_content_id_on_a_plan_without_entitlement_rejected
    """
    plan, artist, _sub = _artist_world(
        {"code": "LITE", "name": "Lite", "commission_bps": 1000,
         "included_release_slots": 3, "allows_content_id": False},
        email="octans@example.com",
    )
    release = create_release(artist["id"], title="South", upc=upc(1))
    track = add_track(release["id"], artist["id"], title="Pole", isrc=isrc(1))

    resp = api.update_track(track["id"], {"content_id_enabled": True},
                            make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_CONTENT_ID_NOT_ENTITLED.value)

    assert read_track(track["id"], artist["id"])["content_id_enabled"] is False


def test_pre_save_registration_honours_the_open_window(api):
    """PRD §3.3: "A `Fan` registers one by supplying a `fan_reference` identifying themselves; the
    platform raises the release's `pre_save_count` by 1 and advances the release's `version` by 1."
    PRD §3.3: "Registration is only accepted while the pre-save window is genuinely open, which
    means all three of the following hold: `pre_save_enabled` is true on the release,
    `pre_save_opens_at` is at or before the current instant, and the current instant is strictly
    earlier than `release_date`."
    PRD §3.3: "A registration that arrives before the campaign opens, after the record has come
    out, or against a release that never enabled pre-saves at all is refused with
    `ERR_PRE_SAVE_WINDOW_CLOSED` (HTTP 422)."

    Design: Corner/validations/pre_save_accepted_inside_window_and_rejected_after_release_date
    """
    plan, artist, _sub = _artist_world(email="phoenix@example.com")
    release = create_release(
        artist["id"], title="Rebirth", upc=upc(1),
        pre_save_enabled=True, pre_save_opens_at="2026-08-01T00:00:00Z",
    )

    early = api.register_pre_save(release["id"], "fan-early", make_fan_headers("fan-early"))
    validate_error(early, ApiErrorId.ERR_PRE_SAVE_WINDOW_CLOSED.value)

    set_clock("2026-08-15T00:00:00Z")
    accepted = validate_success(
        api.register_pre_save(release["id"], "fan-ok", make_fan_headers("fan-ok"))
    )
    assert accepted["pre_save_count"] == 1

    set_clock("2026-09-01T00:00:00Z")
    late = api.register_pre_save(release["id"], "fan-late", make_fan_headers("fan-late"))
    validate_error(late, ApiErrorId.ERR_PRE_SAVE_WINDOW_CLOSED.value)

    assert read_release(release["id"], artist["id"])["pre_save_count"] == 1


def test_approving_a_draft_release_is_an_invalid_transition(api):
    """PRD §3.5: "Approval moves the release `IN_REVIEW → APPROVED` and advances `version` by 1,
    but is permitted only when the release's `upc` is non-null — a barcode-less record cannot be
    approved, and the attempt is refused with `ERR_INVALID_STATE`."
    PRD §2.8: "7. State legality — the target resource is in a state from which the requested
    transition is declared: `ERR_INVALID_STATE`."

    Design: Corner/state_machines/approve_release_from_draft_is_rejected_as_invalid_transition
    """
    plan, artist, _sub = _artist_world(email="mensa@example.com")
    release = create_release(artist["id"], title="Table", upc="212345678901")

    resp = api.approve_release(release["id"], make_ops_headers())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    assert read_release(release["id"], artist["id"])["status"] == "DRAFT"


def test_editorial_rejection_records_the_reason_and_frees_the_slot(api):
    """PRD §3.5: "Rejection moves the release `IN_REVIEW → REJECTED`, records the supplied
    `reason_code` into `rejection_reason_code`, recomputes `releases_used` so that the slot is
    given back to the artist, and advances `version` by 1."

    Design: Corner/state_machines/release_reject_records_reason_and_releases_the_slot
    """
    plan, artist, sub = _artist_world(
        {"code": "SOLO", "name": "Solo", "included_release_slots": 1},
        email="sculptor@example.com",
    )
    release = create_release(artist["id"], title="Chisel", upc="212345678932")
    add_track(release["id"], artist["id"], title="Marble", isrc=isrc(1))
    submit_release(release["id"], artist["id"])
    validate_success(api.review_release(release["id"], make_ops_headers()))

    rejected = validate_success(
        api.reject_release(release["id"], "ARTWORK_INVALID", make_ops_headers())
    )

    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason_code"] == "ARTWORK_INVALID"
    assert read_subscription(sub["id"])["releases_used"] == 0


def test_rejected_release_withdraws_back_to_draft_clearing_the_reason(api):
    """PRD §3.5: "From `REJECTED` the same operation also returns the release to `DRAFT`, but
    there it clears `rejection_reason_code` back to null instead; `releases_used` is unaffected on
    this path because the rejection already released the slot."
    PRD §3.5: "A rejected release is not dead: withdrawing it returns it to `DRAFT` for repair, so
    the full editorial cycle `DRAFT → SUBMITTED → IN_REVIEW → REJECTED → DRAFT` may be traversed
    as often as necessary."

    Design: Corner/state_machines/rejected_release_can_be_withdrawn_back_to_draft_clearing_reason
    """
    plan, artist, sub = _artist_world(email="fornax3@example.com")
    release = create_release(artist["id"], title="Loop", upc="212345678949")
    add_track(release["id"], artist["id"], title="Cycle", isrc=isrc(1))
    submit_release(release["id"], artist["id"])
    validate_success(api.review_release(release["id"], make_ops_headers()))
    validate_success(api.reject_release(release["id"], "ARTWORK_INVALID", make_ops_headers()))

    withdrawn = validate_success(
        api.withdraw_release(release["id"], make_artist_headers(artist["id"]))
    )
    assert withdrawn["status"] == "DRAFT"
    assert withdrawn["rejection_reason_code"] is None

    resubmitted = validate_success(
        api.submit_release(release["id"], make_artist_headers(artist["id"]))
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert read_subscription(sub["id"])["releases_used"] == 1


def test_artist_cannot_approve_their_own_release(api):
    """PRD §2.1: "Once the caller is recognised, the platform checks that their role appears in
    the set of roles authorised for the endpoint they addressed; if it does not, the request is
    refused with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/artist_cannot_approve_own_release
    """
    plan, artist, _sub = _artist_world(email="canis@example.com")
    release = create_release(artist["id"], title="Bark", upc="412345678900")
    add_track(release["id"], artist["id"], title="Woof", isrc=isrc(1))
    submit_release(release["id"], artist["id"])
    validate_success(api.review_release(release["id"], make_ops_headers()))

    resp = api.approve_release(release["id"], make_artist_headers(artist["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)

    assert read_release(release["id"], artist["id"])["status"] == "IN_REVIEW"


def test_artist_cannot_submit_another_artists_release(api):
    """PRD §2.1: "When an entity-backed role — `Artist` or `Collaborator` — addresses a resource
    that belongs to somebody else, the request is refused with `ERR_FORBIDDEN_OWNERSHIP`
    (HTTP 403)."

    Design: Corner/rbac/artist_cannot_submit_another_artists_release
    """
    set_clock(CLOCK_BASE)
    plan = create_plan()
    artist_a = create_artist(display_name="Owner A", legal_name="A LLC",
                             email="ownera@example.com")
    artist_b = create_artist(display_name="Owner B", legal_name="B LLC",
                             email="ownerb@example.com")
    create_active_subscription(artist_a["id"], plan["id"])
    release = create_release(artist_a["id"], title="Mine", upc=upc(1))
    add_track(release["id"], artist_a["id"], title="Solo", isrc=isrc(1))

    resp = api.submit_release(release["id"], make_artist_headers(artist_b["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP.value)

    assert read_release(release["id"], artist_a["id"])["status"] == "DRAFT"
