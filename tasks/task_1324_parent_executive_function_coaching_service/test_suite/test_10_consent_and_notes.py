"""Consent-scoped coordination: share gates, sealing cascades, and OCC on
consent creation (PRD §2.7, §2.10, §3.9)."""
from test_helpers import (
    ApiErrorId,
    add_client,
    create_consent,
    create_consent_payload,
    create_contact,
    create_family,
    create_coach,
    create_finalized_note,
    get_success_data,
    make_coach_headers,
    make_contact_headers,
    make_family_headers,
    set_clock,
    setup_note_consent_scenario,
    sign_consent,
    validate_error,
    validate_success,
)


def test_share_rejected_while_consent_pending_then_succeeds(api):
    """PRD §2.10: "Sharing a note therefore requires three things, each with
    its own rejection: an `ACTIVE` consent grant must exist pairing the note's
    client's family with the target contact (`ERR_CONSENT_NOT_ACTIVE` when none
    exists)"
    PRD §3.9: "A successful share moves the note to `SHARED` and stamps
    `shared_with_contact_id` and `shared_at`."

    Design: Difficulty/cross_entity_state_dependency/note_share_gated_by_consent_state
    """
    ctx = setup_note_consent_scenario(topic="PROGRESS", scope="FULL_PLAN", sign=False)
    family, coach, note, contact, consent = (
        ctx["family"], ctx["coach"], ctx["note"], ctx["contact"], ctx["consent"],
    )
    assert consent["status"] == "PENDING_SIGNATURE"
    coach_h = make_coach_headers(coach["id"])

    # PENDING_SIGNATURE is not ACTIVE.
    resp = api.share_note(note["id"], contact["id"], coach_h)
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)

    sign_consent(consent["id"], family["id"])
    shared = validate_success(api.share_note(note["id"], contact["id"], coach_h))
    assert shared["status"] == "SHARED"
    assert shared["shared_with_contact_id"] == contact["id"]
    assert shared["shared_at"] is not None


def test_shared_note_visible_in_contact_view(api):
    """PRD §3.9: "An external contact reads exactly the notes whose
    `shared_with_contact_id` names that contact and whose status remains
    `SHARED`, in creation order"

    Design: Difficulty/cross_entity_state_dependency/note_share_gated_by_consent_state
    """
    ctx = setup_note_consent_scenario(topic="PROGRESS", scope="FULL_PLAN", sign=True)
    coach, note, contact = ctx["coach"], ctx["note"], ctx["contact"]
    validate_success(
        api.share_note(note["id"], contact["id"], make_coach_headers(coach["id"]))
    )
    visible = validate_success(
        api.list_shared_notes(contact["id"], make_contact_headers(contact["id"]))
    )
    assert [n["id"] for n in visible] == [note["id"]]


def test_share_without_consent_and_unlinked_returns_consent_error(api):
    """PRD §2.8: "then consent existence (`ERR_CONSENT_NOT_ACTIVE`) followed by
    consent scope coverage (`ERR_CONSENT_SCOPE_INSUFFICIENT`)" — both ahead of
    "referential linkage (`ERR_CONTACT_NOT_LINKED`, `ERR_INTAKE_CLIENT_MISMATCH`,
    `ERR_TRACK_MISMATCH`)".
    PRD §2.10: "an `ACTIVE` consent grant must exist pairing the note's
    client's family with the target contact (`ERR_CONSENT_NOT_ACTIVE` when none
    exists)"

    Design: Difficulty/priority_pair_validation_conflict/share_without_consent_and_unlinked_contact_returns_consent_error
    """
    ctx = setup_note_consent_scenario(topic="PLAN_DETAIL", scope="FULL_PLAN",
                                      sign=False)
    coach, note = ctx["coach"], ctx["note"]
    # A contact belonging to a DIFFERENT family, with no consent at all.
    other_family = create_family("Fam SB", "sb@example.com")
    other_contact = create_contact(other_family["id"], name="Teacher T",
                                   contact_type="SCHOOL", email="t@school.example.com")
    resp = api.share_note(
        note["id"], other_contact["id"], make_coach_headers(coach["id"])
    )
    # Both violations hold (no consent; contact not linked); safety wins.
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)


def test_share_without_consent_to_linked_contact_also_consent_error(api):
    """PRD §2.10: "Sharing a note therefore requires three things, each with
    its own rejection: an `ACTIVE` consent grant must exist pairing the note's
    client's family with the target contact (`ERR_CONSENT_NOT_ACTIVE` when none
    exists); the grant's scope must cover the note's topic per the ladder
    (`ERR_CONSENT_SCOPE_INSUFFICIENT`); and the contact must belong to the same
    family as the note's client (`ERR_CONTACT_NOT_LINKED`)."

    Design: Difficulty/priority_pair_validation_conflict/share_without_consent_and_unlinked_contact_returns_consent_error
    """
    # Same rule isolated: the contact IS linked to the note's family but no
    # consent grant exists at all.
    family = create_family("Fam SA2", "sa2@example.com")
    client = add_client(family["id"], full_name="Kid SA2", date_of_birth="2013-03-01")
    coach = create_coach("CERTIFIED", full_name="Coach S2")
    note = create_finalized_note(client["id"], coach["id"], topic="PLAN_DETAIL")
    contact = create_contact(family["id"], name="Dr L")
    resp = api.share_note(note["id"], contact["id"], make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)
    # No partial share happened.
    notes = validate_success(
        api.list_client_notes(client["id"], make_coach_headers(coach["id"]))
    )
    assert notes[0]["status"] == "FINALIZED"


def test_note_scope_insufficient_via_progress_only(api):
    """PRD §2.10: "`PROGRESS_ONLY` covers notes whose topic is `PROGRESS`;
    `GOALS_AND_PROGRESS` covers notes with topic `PROGRESS` or `GOALS`;
    `FULL_PLAN` covers all three topics."
    PRD §2.10: "the grant's scope must cover the note's topic per the ladder
    (`ERR_CONSENT_SCOPE_INSUFFICIENT`)"

    Design: Corner/validations/note_scope_insufficient_via_progress_only
    """
    ctx = setup_note_consent_scenario(topic="GOALS", scope="PROGRESS_ONLY", sign=True)
    coach, note, contact = ctx["coach"], ctx["note"], ctx["contact"]
    resp = api.share_note(note["id"], contact["id"], make_coach_headers(coach["id"]))
    validate_error(resp, ApiErrorId.ERR_CONSENT_SCOPE_INSUFFICIENT)


def test_note_sealed_when_consent_revoked(api, admin_headers):
    """PRD §3.9: "A family member may revoke a grant from either
    `PENDING_SIGNATURE` or `ACTIVE`; revoking an active grant seals every note
    in `SHARED` status that was shared to the grant's contact."
    PRD §2.10: "every note shared under it is moved to `SEALED`, the terminal
    state, and immediately disappears from the external contact's shared-notes
    view."

    Design: Corner/validations/note_sealed_when_consent_revoked
    """
    ctx = setup_note_consent_scenario(topic="PROGRESS", scope="FULL_PLAN", sign=True)
    family, coach, client, note, contact, consent = (
        ctx["family"], ctx["coach"], ctx["client"],
        ctx["note"], ctx["contact"], ctx["consent"],
    )
    shared = validate_success(
        api.share_note(note["id"], contact["id"], make_coach_headers(coach["id"]))
    )
    assert shared["status"] == "SHARED"

    revoked = validate_success(
        api.transition_consent(consent["id"], "REVOKED", make_family_headers(family["id"]))
    )
    assert revoked["status"] == "REVOKED"

    notes = validate_success(api.list_client_notes(client["id"], admin_headers))
    assert notes[0]["status"] == "SEALED"
    visible = validate_success(
        api.list_shared_notes(contact["id"], make_contact_headers(contact["id"]))
    )
    assert visible == [], "sealed notes disappear from the consent-limited view"


def test_consent_supersede_seals_prior_shared_notes(api, admin_headers):
    """PRD §3.9: "Creation supersedes: any prior non-terminal grant for the
    same contact moves to `SUPERSEDED`, and when the superseded grant was
    `ACTIVE`, the note-sealing cascade runs over the notes shared under it. The
    family's `version` increments by one."

    Design: Corner/validations/consent_supersede_seals_prior_shared_notes
    """
    ctx = setup_note_consent_scenario(topic="GOALS", scope="GOALS_AND_PROGRESS",
                                      sign=True)
    family, coach, client, note, contact, consent1 = (
        ctx["family"], ctx["coach"], ctx["client"],
        ctx["note"], ctx["contact"], ctx["consent"],
    )
    validate_success(
        api.share_note(note["id"], contact["id"], make_coach_headers(coach["id"]))
    )

    # The replacement grant supersedes the ACTIVE one.
    consent2 = create_consent(family["id"], contact["id"], scope="FULL_PLAN",
                              expires_at="2027-06-01T00:00:00Z")
    assert consent2["status"] == "PENDING_SIGNATURE"

    consents = validate_success(api.list_contact_consents(contact["id"], admin_headers))
    by_id = {c["id"]: c for c in consents}
    assert by_id[consent1["id"]]["status"] == "SUPERSEDED"

    notes = validate_success(api.list_client_notes(client["id"], admin_headers))
    assert notes[0]["status"] == "SEALED", "supersede runs the note-sealing cascade"


def test_consent_sign_after_expiry_rejected(api):
    """PRD §3.9: "A family member signs a pending grant — moving it from
    `PENDING_SIGNATURE` to `ACTIVE` — provided the family owns the grant
    (`ERR_FORBIDDEN_SCOPE`) and the grant has not yet reached its `expires_at`;
    signing at or after expiry is rejected with `ERR_CONSENT_EXPIRED`."

    Design: Corner/state_machines/consent_sign_after_expiry_rejected
    """
    family = create_family("Fam CE", "ce@example.com")
    contact = create_contact(family["id"], name="Dr E")
    consent = create_consent(family["id"], contact["id"], scope="FULL_PLAN",
                             expires_at="2026-08-02T00:00:00Z")
    set_clock("2026-08-03T00:00:00Z")
    resp = api.transition_consent(
        consent["id"], "ACTIVE", make_family_headers(family["id"])
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_EXPIRED)


def test_occ_consent_create_stale_family_version(api, admin_headers):
    """PRD §2.7: "Creating a consent grant for a family requires the request
    body to carry `expected_family_version`, holding the `version` of the
    Family as the caller last observed it. A mismatch with the family's current
    `version` is rejected with `ERR_STALE_FAMILY_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_consent_create_stale_family_version
    """
    family = create_family("Fam OV", "ov@example.com")
    fam_h = make_family_headers(family["id"])
    contact1 = create_contact(family["id"], name="Dr One", email="one@clinic.example.com")
    contact2 = create_contact(family["id"], name="Ms Two", contact_type="SCHOOL",
                              email="two@school.example.com")

    stale_version = validate_success(api.get_family(family["id"], admin_headers))["version"]
    get_success_data(
        api.create_consent(
            family["id"],
            create_consent_payload(contact1["id"], stale_version),
            fam_h,
        )
    )
    # Consent 1 advanced Family.version; replaying the stale view fails.
    resp = api.create_consent(
        family["id"],
        create_consent_payload(contact2["id"], stale_version,
                               scope="PROGRESS_ONLY"),
        fam_h,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_FAMILY_VERSION)

    fresh_version = validate_success(api.get_family(family["id"], admin_headers))["version"]
    consent2 = validate_success(
        api.create_consent(
            family["id"],
            create_consent_payload(contact2["id"], fresh_version,
                                   scope="PROGRESS_ONLY"),
            fam_h,
        ),
        expected_status=201,
    )
    assert consent2["status"] == "PENDING_SIGNATURE"
