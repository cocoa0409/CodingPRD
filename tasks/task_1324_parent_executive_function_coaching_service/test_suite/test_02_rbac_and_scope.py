"""Role authorization and entity-backed ownership (PRD §2.1, §4)."""
from test_helpers import (
    ApiErrorId,
    add_client,
    create_checkin,
    create_contact,
    create_family,
    create_note,
    create_coach,
    create_supervision_record,
    make_coach_headers,
    make_contact_headers,
    make_family_headers,
    activate_family,
    setup_active_plan_scenario,
    submit_checkin,
    validate_error,
)


def test_coach_cannot_purchase_package_forbidden(api, admin_headers):
    """PRD §2.1: "A request whose role is not listed among the endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /api/families/{id}/packages lists only PracticeAdmin among its
    authorized roles.

    Design: Corner/rbac/coach_cannot_purchase_package_forbidden
    """
    family = create_family("Fam RB", "rb@example.com")
    add_client(family["id"], full_name="Kid RB")
    activate_family(family["id"])
    coach = create_coach("CERTIFIED", full_name="Coach RB")
    resp = api.purchase_package(
        family["id"],
        {"track": "INDIVIDUAL", "credits_total": 4},
        make_coach_headers(coach["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_family_cannot_acknowledge_checkin_forbidden(api):
    """PRD §2.1: "A request whose role is not listed among the endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: POST /api/checkins/{id}/acknowledge lists only Coach among its
    authorized roles.

    Design: Corner/rbac/family_cannot_acknowledge_checkin_forbidden
    """
    ctx = setup_active_plan_scenario(account_name="Fam FA", primary_email="fa@example.com")
    family, plan, coach = ctx["family"], ctx["plans"][0], ctx["coach"]
    checkin = create_checkin(plan["id"], coach["id"], "2026-08-05T00:00:00Z")
    submit_checkin(checkin["id"], family["id"])
    resp = api.acknowledge_checkin(checkin["id"], make_family_headers(family["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_external_contact_cannot_read_family_forbidden(api):
    """PRD §2.1: "A request whose role is not listed among the endpoint's
    authorized roles is rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §2.1: "When `X-User-Role` is `ExternalContact`, `X-User-ID` is the `id`
    of the acting `CoordinationContact`; the caller may only read the
    shared-notes view of its own contact record."

    Design: Corner/rbac/external_contact_cannot_read_family_forbidden
    """
    family = create_family("Fam EC", "ec@example.com")
    contact = create_contact(family["id"], name="Dr X")
    resp = api.get_family(family["id"], make_contact_headers(contact["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


def test_wrong_family_scope_forbidden(api):
    """PRD §2.1: "A caller passing authentication and role checks but failing
    one of these entity-backed ownership comparisons is rejected with
    `ERR_FORBIDDEN_SCOPE`."
    PRD §2.1: "When `X-User-Role` is `FamilyMember`, `X-User-ID` is the `id` of
    the acting `Family`; ownership checks compare the path family's `id`, or
    the `family_id` of the family that owns the path resource, to `X-User-ID`."

    Design: Corner/rbac/wrong_family_scope_forbidden
    """
    family_a = create_family("Fam WA", "wa2@example.com")
    family_b = create_family("Fam WB", "wb2@example.com")
    resp = api.get_family(family_b["id"], make_family_headers(family_a["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)


def test_non_author_coach_cannot_finalize_note(api):
    """PRD §3.9: "Only the author may finalize a note — moving it from `DRAFT`
    to `FINALIZED`, with anyone else rejected by `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/rbac/non_author_coach_cannot_finalize_note
    """
    family = create_family("Fam NA", "na@example.com")
    client = add_client(family["id"], full_name="Kid NA")
    coach1 = create_coach("CERTIFIED", full_name="Coach One")
    coach2 = create_coach("CERTIFIED", full_name="Coach Two")
    note = create_note(client["id"], coach1["id"], topic="PROGRESS", body="author-only")
    resp = api.transition_note(note["id"], "FINALIZED", make_coach_headers(coach2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)


def test_supervisee_cannot_mark_held_own_record(api):
    """PRD §2.9: "Records move from `SCHEDULED` to `HELD` only at the hand of
    the named supervisor (segregation of duties: the supervisee cannot mark
    their own record), and from `HELD` to `VERIFIED` only at the hand of a
    `PracticeAdmin`"
    PRD §2.1: "A caller passing authentication and role checks but failing one
    of these entity-backed ownership comparisons is rejected with
    `ERR_FORBIDDEN_SCOPE`."

    Design: Corner/rbac/supervisee_cannot_mark_held_own_record
    """
    supervisee = create_coach("ASSOCIATE", full_name="Coach Jun2")
    supervisor = create_coach("SUPERVISOR", full_name="Coach Sup2")
    record = create_supervision_record(supervisee["id"], supervisor["id"], hours=1.0)
    resp = api.transition_supervision_record(
        record["id"], "HELD", make_coach_headers(supervisee["id"])
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SCOPE)
