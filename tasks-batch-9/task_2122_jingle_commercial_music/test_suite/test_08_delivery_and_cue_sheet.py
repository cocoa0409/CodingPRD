"""Stem delivery, the basis-point waterfall and performance-royalty registration."""
from test_helpers import (
    ApiErrorId,
    RIGHTS_ADMIN_ISSUER_ID,
    add_cue_entry,
    assert_cue_shares_conserved,
    assert_cue_sheet_entry,
    assert_deliverable,
    create_composer,
    deliver_stems,
    file_cue_sheet,
    get_brief,
    get_cue_entry,
    get_deliverable,
    get_project,
    make_client_rep_headers,
    make_producer_headers,
    make_rights_admin_headers,
    set_clock,
    setup_engagement_with_deliverable,
    validate_error,
    validate_paginated,
    validate_success,
    void_cue_entry,
)


def test_cue_sheet_reaches_registered_while_the_master_stays_pending(api):
    """PRD §3.8: "The package carries **two status dimensions that evolve independently
    on the same row**."
    PRD §3.8: "Registration with the performing-rights organisation moves it
    `FILED → REGISTERED`, requires at least one `ALLOCATED` line — again
    `ERR_CUE_SHEET_EMPTY` when there is none — and requires the governing licence deal
    to be `ACTIVE`, refusing with `ERR_LICENSE_NOT_ACTIVE` otherwise."
    PRD §3.8: "An operation on one dimension never touches the other."

    Design: Difficulty/non_linear_state_machine/deliverable_cuesheet_dimension_reaches_registered_while_master_stays_pending
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 800_000})
    add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                  role="COMPOSER", declared_weight=1)

    filed = validate_success(api.file_cue_sheet(
        env["deliverable"]["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert filed["cuesheet_status"] == "FILED", f"Expected FILED, got {filed['cuesheet_status']}"

    registered = validate_success(api.register_cue_sheet(
        env["deliverable"]["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert_deliverable(registered)
    assert registered["cuesheet_status"] == "REGISTERED", (
        f"Expected REGISTERED, got {registered['cuesheet_status']}")
    assert registered["master_status"] == "PENDING", (
        "The audio dimension is untouched by the paperwork dimension; "
        f"got {registered['master_status']}")
    assert registered["delivered_lengths"] == [], (
        f"No stems were delivered; got {registered['delivered_lengths']}")
    assert registered["stem_manifest"] == [], (
        f"No stems were delivered; got {registered['stem_manifest']}")


def test_registration_in_production_leaves_the_engagement_untransitioned(api):
    """PRD §3.8: "Registration is nevertheless permitted while the engagement is still
    `IN_PRODUCTION`: in that case the paperwork dimension advances and the engagement
    simply does not transition."
    PRD §3.8: "When at least one remains, the allocation runs as follows: the total
    weight is the sum of `declared_weight` across all `ALLOCATED` lines; each line's
    provisional share is 10,000 multiplied by that line's `declared_weight`, divided by
    the total weight, and truncated downward to a whole basis point; the remainder is
    10,000 less the sum of those truncated shares; the lines are then ordered by
    `declared_weight` descending with `created_at` ascending as tie-break, and the first
    lines in that order each receive one additional basis point until the remainder is
    exhausted."

    Design: Difficulty/non_linear_state_machine/deliverable_cuesheet_dimension_reaches_registered_while_master_stays_pending
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 800_000})
    entry = add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                          role="COMPOSER", declared_weight=1)
    file_cue_sheet(env["deliverable"]["id"])
    validate_success(api.register_cue_sheet(
        env["deliverable"]["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))

    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["unallocated_bps"] == 0, (
        f"One allocated line takes the whole sheet; got {deliverable['unallocated_bps']}")
    only_line = get_cue_entry(entry["id"])
    assert only_line["share_bps"] == 10_000, (
        f"A single line takes all 10000 basis points; got {only_line['share_bps']}")
    project = get_project(env["project"]["id"])
    assert project["status"] == "IN_PRODUCTION", (
        "Registration while the engagement is IN_PRODUCTION must not transition it; "
        f"got {project['status']}")


def test_filing_an_empty_cue_sheet_is_rejected(api):
    """PRD §3.8: "Filing moves the paperwork dimension `NOT_FILED → FILED` and requires
    at least one `ALLOCATED` line on the package, otherwise it is refused with
    `ERR_CUE_SHEET_EMPTY`."

    Design: Difficulty/boundary_precision_check/file_cue_sheet_with_empty_allocated_set_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 800_000})

    validate_error(
        api.file_cue_sheet(env["deliverable"]["id"],
                           make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_CUE_SHEET_EMPTY.value, 422)


def test_empty_cue_sheet_keeps_the_full_ten_thousand_basis_points(api):
    """PRD §3.8: "A new package opens with `master_status` at `PENDING`,
    `cuesheet_status` at `NOT_FILED`, `delivered_lengths` and `stem_manifest` empty,
    `unallocated_bps` at 10,000 and `registered_at` null."
    PRD §3.8: "When no `ALLOCATED` line remains, `unallocated_bps` is the whole 10,000
    and every voided line already carries a `share_bps` of zero."

    Design: Difficulty/boundary_precision_check/file_cue_sheet_with_empty_allocated_set_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 800_000})

    validate_error(
        api.file_cue_sheet(env["deliverable"]["id"],
                           make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_CUE_SHEET_EMPTY.value, 422)

    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["cuesheet_status"] == "NOT_FILED", (
        f"The refused filing must leave NOT_FILED; got {deliverable['cuesheet_status']}")
    assert deliverable["unallocated_bps"] == 10_000, (
        f"An empty sheet holds the whole 10000; got {deliverable['unallocated_bps']}")
    _, meta = validate_paginated(api.list_cue_entries(
        make_producer_headers(), params={"deliverable_id": deliverable["id"]}))
    assert meta["total_count"] == 0, f"Expected no cue-sheet lines; got {meta['total_count']}"


def test_registration_requires_an_active_licence(api):
    """PRD §3.8: "Registration with the performing-rights organisation moves it
    `FILED → REGISTERED`, requires at least one `ALLOCATED` line — again
    `ERR_CUE_SHEET_EMPTY` when there is none — and requires the governing licence deal
    to be `ACTIVE`, refusing with `ERR_LICENSE_NOT_ACTIVE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/cue_sheet_registration_gated_by_license_deal_not_yet_active
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACCEPTED", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "TERM", "term_months": 24,
                        "market_codes": ["US_NATIONAL"], "creative_fee_cents": 800_000})
    add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                  role="COMPOSER", declared_weight=1)
    file_cue_sheet(env["deliverable"]["id"])

    validate_error(
        api.register_cue_sheet(env["deliverable"]["id"],
                               make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value, 409)


def test_refused_registration_leaves_the_cue_sheet_filed_and_unstamped(api):
    """PRD §3.8: "A new package opens with `master_status` at `PENDING`,
    `cuesheet_status` at `NOT_FILED`, `delivered_lengths` and `stem_manifest` empty,
    `unallocated_bps` at 10,000 and `registered_at` null."
    PRD §3.8: "Registration with the performing-rights organisation moves it
    `FILED → REGISTERED`, requires at least one `ALLOCATED` line — again
    `ERR_CUE_SHEET_EMPTY` when there is none — and requires the governing licence deal
    to be `ACTIVE`, refusing with `ERR_LICENSE_NOT_ACTIVE` otherwise."

    Design: Difficulty/cross_entity_state_dependency/cue_sheet_registration_gated_by_license_deal_not_yet_active
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACCEPTED", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "TERM", "term_months": 24,
                        "market_codes": ["US_NATIONAL"], "creative_fee_cents": 800_000})
    entry = add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                          role="COMPOSER", declared_weight=1)
    file_cue_sheet(env["deliverable"]["id"])

    validate_error(
        api.register_cue_sheet(env["deliverable"]["id"],
                               make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_LICENSE_NOT_ACTIVE.value, 409)

    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["cuesheet_status"] == "FILED", (
        f"The refused registration must leave the sheet FILED; got {deliverable['cuesheet_status']}")
    assert deliverable["registered_at"] is None, (
        f"No registration instant may be stamped; got {deliverable['registered_at']}")
    assert get_cue_entry(entry["id"])["share_bps"] == 10_000
    deal = validate_success(api.get_license_deal(env["deal"]["id"], make_producer_headers()))
    assert deal["status"] == "ACCEPTED", f"Expected ACCEPTED, got {deal['status']}"
    project = get_project(env["project"]["id"])
    assert project["status"] == "IN_PRODUCTION", f"Expected IN_PRODUCTION, got {project['status']}"


def test_voiding_an_added_line_restores_the_prior_shares(api):
    """PRD §3.8: "Adding a line and then voiding it are exact compensating actions:
    after the void, every surviving line's `share_bps` and the package's
    `unallocated_bps` must be back at the values they held before the add."
    PRD §3.8: "On success the line's `share_bps` is set to zero and frozen there —
    voided lines never re-enter the waterfall — the waterfall re-runs over the remaining
    `ALLOCATED` lines, and `unallocated_bps` becomes 10,000 if none remain or zero
    otherwise."

    Design: Difficulty/compensating_invariant/cue_entry_add_then_void_conserves_ten_thousand_basis_points
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 800_000})
    arranger = create_composer(index=1)
    publisher = create_composer(index=2)
    first = add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                          role="COMPOSER", declared_weight=2)
    second = add_cue_entry(env["deliverable"]["id"], arranger["id"],
                           role="ARRANGER", declared_weight=1)
    assert get_cue_entry(first["id"])["share_bps"] == 6_667
    assert get_cue_entry(second["id"])["share_bps"] == 3_333

    third = add_cue_entry(env["deliverable"]["id"], publisher["id"],
                          role="PUBLISHER", declared_weight=1)
    voided = validate_success(api.void_cue_entry(
        third["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)))
    assert_cue_sheet_entry(voided)
    assert voided["status"] == "VOIDED", f"Expected VOIDED, got {voided['status']}"
    assert voided["share_bps"] == 0, f"A voided line is frozen at zero; got {voided['share_bps']}"

    assert get_cue_entry(first["id"])["share_bps"] == 6_667, (
        "The weight-2 line must return to exactly 6667, not a re-floored 6666")
    assert get_cue_entry(second["id"])["share_bps"] == 3_333, (
        "The weight-1 line must return to exactly 3333")
    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["unallocated_bps"] == 0
    assert deliverable["cuesheet_status"] == "NOT_FILED", (
        f"Two lines survive, so the paperwork dimension is untouched; "
        f"got {deliverable['cuesheet_status']}")


def test_cue_shares_and_unallocated_always_sum_to_ten_thousand(api):
    """PRD §3.8: "Every add and every void re-runs the basis-point waterfall across the
    package's `ALLOCATED` lines, and the result must always satisfy a second
    conservation law: **the `share_bps` of all `ALLOCATED` lines plus the package's
    `unallocated_bps` must equal exactly 10,000 after every request.**"

    Design: Difficulty/compensating_invariant/cue_entry_add_then_void_conserves_ten_thousand_basis_points
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=150_000, submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 800_000})
    arranger = create_composer(index=1)
    publisher = create_composer(index=2)
    add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                  role="COMPOSER", declared_weight=2)
    add_cue_entry(env["deliverable"]["id"], arranger["id"],
                  role="ARRANGER", declared_weight=1)

    def lines():
        rows, _ = validate_paginated(api.list_cue_entries(
            make_producer_headers(),
            params={"deliverable_id": env["deliverable"]["id"], "limit": 100}))
        return rows

    assert_cue_shares_conserved(get_deliverable(env["deliverable"]["id"]), lines())

    third = add_cue_entry(env["deliverable"]["id"], publisher["id"],
                          role="PUBLISHER", declared_weight=1)
    assert get_cue_entry(third["id"])["share_bps"] == 2_500, (
        "Weights 2, 1 and 1 floor to 5000, 2500 and 2500 with no remainder")
    assert_cue_shares_conserved(get_deliverable(env["deliverable"]["id"]), lines())

    void_cue_entry(third["id"])
    assert_cue_shares_conserved(get_deliverable(env["deliverable"]["id"]), lines())


def test_rejecting_the_master_reverts_the_dimension_and_clears_the_manifest(api):
    """PRD §3.8: "A `ClientRep` owning the engagement may reject it, moving the audio
    dimension `STEMS_DELIVERED → PENDING` with a `rejection_note` and clearing both
    `delivered_lengths` and `stem_manifest` back to empty arrays, so the producer must
    deliver the whole package again."
    PRD §3.8: "An operation on one dimension never touches the other."

    Design: Corner/state_machines/corner_reject_master_reverts_dimension_and_clears_the_manifest
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", required_lengths=[60, 30, 15], demo_fee_cents=100_000,
        submitted_length_seconds=30,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 400_000})
    delivered = deliver_stems(env["deliverable"]["id"],
                              lengths_seconds=[60, 30, 15],
                              stem_names=["DRUMS", "BASS", "KEYS", "VOX", "MIX"])
    assert delivered["master_status"] == "STEMS_DELIVERED"

    rejected = validate_success(api.reject_master(
        env["deliverable"]["id"], {"rejection_note": "vocal comp is flat"},
        make_client_rep_headers(env["client"]["id"])))
    assert rejected["master_status"] == "PENDING", (
        f"Expected PENDING, got {rejected['master_status']}")
    assert rejected["delivered_lengths"] == [], (
        f"The delivered lengths must be cleared; got {rejected['delivered_lengths']}")
    assert rejected["stem_manifest"] == [], (
        f"The stem manifest must be cleared; got {rejected['stem_manifest']}")
    assert rejected["cuesheet_status"] == "NOT_FILED", (
        f"The paperwork dimension is untouched; got {rejected['cuesheet_status']}")
    project = get_project(env["project"]["id"])
    assert project["status"] == "IN_PRODUCTION", f"Expected IN_PRODUCTION, got {project['status']}"


def test_stem_delivery_must_match_the_brief_lengths_and_cover_every_stem(api):
    """PRD §3.8: "The delivered length set must **equal** the `required_lengths` of the
    engagement's single `APPROVED` creative brief — no missing cut and no surplus cut —
    and a mismatch in either direction is refused with
    `ERR_ALTERNATE_LENGTHS_INCOMPLETE`."
    PRD §3.8: "The stem set must **contain** every one of the five required stems
    `DRUMS`, `BASS`, `KEYS`, `VOX` and `MIX`; a missing stem is refused with
    `ERR_STEM_MANIFEST_INCOMPLETE`, while extra stems beyond those five are accepted and
    stored."

    Design: Corner/validations/corner_stem_delivery_missing_a_length_and_missing_a_stem
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", required_lengths=[60, 30, 15], demo_fee_cents=100_000,
        submitted_length_seconds=60,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 400_000})

    validate_error(
        api.deliver_stems(env["deliverable"]["id"],
                          {"stem_names": ["DRUMS", "BASS", "KEYS", "VOX", "MIX"],
                           "lengths_seconds": [60, 30]},
                          make_producer_headers()),
        ApiErrorId.ERR_ALTERNATE_LENGTHS_INCOMPLETE.value, 422)
    validate_error(
        api.deliver_stems(env["deliverable"]["id"],
                          {"stem_names": ["DRUMS", "BASS", "KEYS", "VOX"],
                           "lengths_seconds": [60, 30, 15]},
                          make_producer_headers()),
        ApiErrorId.ERR_STEM_MANIFEST_INCOMPLETE.value, 422)

    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["master_status"] == "PENDING", (
        f"Both refusals must leave the audio dimension PENDING; got {deliverable['master_status']}")
    assert deliverable["delivered_lengths"] == []
    assert deliverable["stem_manifest"] == []


def test_cue_waterfall_remainder_goes_to_the_earliest_equal_weight_line(api):
    """PRD §3.8: "When at least one remains, the allocation runs as follows: the total
    weight is the sum of `declared_weight` across all `ALLOCATED` lines; each line's
    provisional share is 10,000 multiplied by that line's `declared_weight`, divided by
    the total weight, and truncated downward to a whole basis point; the remainder is
    10,000 less the sum of those truncated shares; the lines are then ordered by
    `declared_weight` descending with `created_at` ascending as tie-break, and the first
    lines in that order each receive one additional basis point until the remainder is
    exhausted."

    Design: Corner/calculations/corner_cue_waterfall_remainder_goes_to_the_earliest_equal_weight_entry
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=100_000,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 400_000})
    arranger = create_composer(index=1)
    publisher = create_composer(index=2)

    first = add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                          role="COMPOSER", declared_weight=1)
    second = add_cue_entry(env["deliverable"]["id"], arranger["id"],
                           role="ARRANGER", declared_weight=1)
    third = add_cue_entry(env["deliverable"]["id"], publisher["id"],
                          role="PUBLISHER", declared_weight=1)

    assert get_cue_entry(first["id"])["share_bps"] == 3_334, (
        "Three equal weights floor to 3333 each and the single remaining basis point "
        "goes to the earliest-created line")
    assert get_cue_entry(second["id"])["share_bps"] == 3_333
    assert get_cue_entry(third["id"])["share_bps"] == 3_333
    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["unallocated_bps"] == 0, (
        f"Expected unallocated_bps 0, got {deliverable['unallocated_bps']}")


def test_second_brief_approval_and_second_void_are_rejected(api):
    """PRD §3.2: "Approving a brief that is already `APPROVED` or `SUPERSEDED` is
    refused with `ERR_BRIEF_NOT_DRAFT`; approving while the engagement is not in
    `BRIEFING` is refused with `ERR_PROJECT_NOT_IN_BRIEFING`."
    PRD §3.8: "It is refused with `ERR_CUE_ENTRY_ALREADY_VOIDED` when the line is
    already `VOIDED` or when the package's cue sheet is already `REGISTERED`."
    PRD §3.8: "When no `ALLOCATED` line remains, `unallocated_bps` is the whole 10,000
    and every voided line already carries a `share_bps` of zero."

    Design: Corner/errors/corner_second_brief_approval_and_second_cue_void_are_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    env = setup_engagement_with_deliverable(
        stage="ACTIVE", demo_fee_cents=100_000,
        deal_overrides={"license_structure": "BUYOUT", "market_codes": ["US_NATIONAL"],
                        "creative_fee_cents": 400_000})
    entry = add_cue_entry(env["deliverable"]["id"], env["composer"]["id"],
                          role="COMPOSER", declared_weight=1)
    void_cue_entry(entry["id"])

    validate_error(
        api.approve_brief(env["brief"]["id"], make_client_rep_headers(env["client"]["id"])),
        ApiErrorId.ERR_BRIEF_NOT_DRAFT.value, 409)
    validate_error(
        api.void_cue_entry(entry["id"], make_rights_admin_headers(RIGHTS_ADMIN_ISSUER_ID)),
        ApiErrorId.ERR_CUE_ENTRY_ALREADY_VOIDED.value, 409)

    brief = get_brief(env["project"]["id"], env["brief"]["id"])
    assert brief["status"] == "APPROVED", f"Expected APPROVED, got {brief['status']}"
    line = get_cue_entry(entry["id"])
    assert line["status"] == "VOIDED", f"Expected VOIDED, got {line['status']}"
    assert line["share_bps"] == 0
    deliverable = get_deliverable(env["deliverable"]["id"])
    assert deliverable["unallocated_bps"] == 10_000, (
        f"With no ALLOCATED line left the whole 10000 is unallocated; "
        f"got {deliverable['unallocated_bps']}")
    assert deliverable["cuesheet_status"] == "NOT_FILED"
