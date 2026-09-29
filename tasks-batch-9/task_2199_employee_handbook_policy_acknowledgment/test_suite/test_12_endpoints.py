"""Endpoint surface behaviour: partial patch, link navigation and action endpoints."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_same_instant,
    make_admin_headers,
    make_author_headers,
    make_counsel_headers,
    mint_version,
    new_document,
    new_employee,
    new_jurisdiction,
    new_reviewer,
    patch_employee,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_employee_patch_updates_one_field_and_leaves_the_rest_intact():
    """PRD §3.1: "An `HRComplianceAdmin` may later update an employee's
    `employment_status`, `preferred_language_code`, `needs_accessible_format` or
    `manager_id`, and any such update increments the employee's `version` by 1."  PRD
    §2.4: "`updated_at` is refreshed on every mutation alongside the version bump."

    Design: Corner/endpoints/corner_employee_patch_is_partial_and_bounded_to_declared_inputs
    """
    jurisdiction = new_jurisdiction()
    manager = new_employee(jurisdiction["id"])
    subject = new_employee(
        jurisdiction["id"],
        preferred_language_code="es",
        needs_accessible_format=True,
        manager_id=manager["id"],
    )
    token = subject["version"]
    set_clock("2026-08-05T00:00:00Z")

    patched = patch_employee(subject["id"], employment_status="ON_LEAVE")

    assert patched["employment_status"] == "ON_LEAVE", (
        f"the named field must change, got {patched['employment_status']}"
    )
    assert patched["preferred_language_code"] == "es", (
        "an omitted patchable field must keep its stored value, got "
        f"{patched['preferred_language_code']}"
    )
    assert patched["needs_accessible_format"] is True, (
        f"an omitted patchable field must not be reset, got {patched['needs_accessible_format']}"
    )
    assert patched["manager_id"] == manager["id"], (
        f"an omitted patchable field must not be cleared, got {patched['manager_id']}"
    )
    assert patched["work_email"] == subject["work_email"], (
        "work_email is not among the four updatable fields, got "
        f"{patched['work_email']}"
    )
    assert patched["jurisdiction_id"] == jurisdiction["id"]
    assert patched["open_ack_count"] == 0
    assert patched["open_escalation_count"] == 0
    assert patched["version"] == token + 1, (
        f"the update must increment version to {token + 1}, got {patched['version']}"
    )
    assert_same_instant(patched["updated_at"], "2026-08-05T00:00:00.000Z", "updated_at")

    reread = validate_success(api_client.get_employee(subject["id"], make_admin_headers()))
    assert reread == patched, (
        "a single read must return exactly the representation the update returned"
    )


def test_addendum_link_rows_reverse_navigate_from_version_jurisdiction_and_reviewer():
    """PRD §3.2: "Uniqueness across the whole system is enforced with a single error,
    `ERR_DUPLICATE_RESOURCE` at 409. It guards ... the pair of `policy_version_id` and
    `jurisdiction_id` on addenda".  PRD §3.2: "Addenda may be listed by
    `policy_version_id`, by `jurisdiction_id`, by `approved_by_reviewer_id` — which is
    how an auditor finds everything a given counsel signed — and by `status`."

    Design: Corner/endpoints/corner_addendum_link_navigates_from_both_parents
    """
    from test_helpers import create_addendum_payload

    ca = new_jurisdiction()
    ny = new_jurisdiction()
    reviewer = new_reviewer(ca["id"])
    document = new_document()
    v1 = mint_version(document, [ca["id"], ny["id"]])
    v2 = mint_version(document, [ca["id"], ny["id"]])

    def _add(policy_version_id, jurisdiction_id):
        return api_client.create_addendum(
            policy_version_id,
            create_addendum_payload(jurisdiction_id),
            make_author_headers(),
        )

    created = {}
    for label, version_id, jurisdiction_id in (
        ("ca1", v1["id"], ca["id"]),
        ("ny1", v1["id"], ny["id"]),
        ("ca2", v2["id"], ca["id"]),
    ):
        row = validate_success(_add(version_id, jurisdiction_id), 201)
        assert row["status"] == "DRAFT", (
            f"a fresh addendum starts in DRAFT, got {row['status']}"
        )
        assert row["approved_by_reviewer_id"] is None
        created[label] = row

    validate_error(_add(v1["id"], ca["id"]), ApiErrorId.ERR_DUPLICATE_RESOURCE)

    def _ids(**params):
        params["limit"] = 100
        rows, _meta = validate_paginated(
            api_client.list_addenda(make_admin_headers(), params=params)
        )
        return {row["id"] for row in rows}

    assert _ids(policy_version_id=v1["id"]) == {created["ca1"]["id"], created["ny1"]["id"]}, (
        "one version carries one addendum per jurisdiction"
    )
    assert _ids(jurisdiction_id=ca["id"]) == {created["ca1"]["id"], created["ca2"]["id"]}, (
        "one jurisdiction is addressed by addenda on several versions"
    )
    assert _ids(policy_version_id=v1["id"], jurisdiction_id=ny["id"]) == {
        created["ny1"]["id"]
    }, "the two filters must compose down to the single link row"

    approved = validate_success(
        api_client.approve_addendum(
            created["ca1"]["id"], make_counsel_headers(reviewer["id"])
        )
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_reviewer_id"] == reviewer["id"], (
        f"approval must record the signing reviewer, got {approved['approved_by_reviewer_id']}"
    )

    assert _ids(approved_by_reviewer_id=reviewer["id"]) == {created["ca1"]["id"]}
    assert _ids(status="DRAFT") == {created["ny1"]["id"], created["ca2"]["id"]}, (
        "only the untouched rows remain in DRAFT"
    )


def test_legal_hold_flags_an_append_only_retention_row_without_altering_it():
    """PRD §3.7: "A dispute hold is placed by supplying a `hold_reason` that records
    the dispute reference; this sets `legal_hold` to true so the row is preserved past
    its `retention_until`. Both `legal_hold` and `hold_reason` default to their unset
    values — false and null respectively — on every newly appended row." ... "Retention
    rows ... may be listed by `acknowledgment_id`, `employee_id`, `jurisdiction_id` and
    `legal_hold`".

    Design: Corner/endpoints/corner_legal_hold_action_flags_a_retention_row_without_moving_state
    """
    from test_helpers import (
        acknowledge,
        assert_append_only_fields,
        refresh_acknowledgment,
        retention_rows_for,
        setup_released_scenario,
    )

    ctx = setup_released_scenario(
        jurisdiction={
            "retention_years": 5,
            "ack_deadline_days": 30,
            "min_legal_review_days": 5,
        },
        effective_date="2026-09-01T00:00:00Z",
    )
    ack = acknowledge(ctx["assignment"], ctx["employee"]["id"])
    rows = retention_rows_for(ctx["employee"]["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row["legal_hold"] is False, (
        f"a newly appended row starts off hold, got {row['legal_hold']}"
    )
    assert row["hold_reason"] is None, (
        f"hold_reason defaults to null, got {row['hold_reason']}"
    )

    held = validate_success(
        api_client.place_legal_hold(
            row["id"],
            {"hold_reason": "Litigation hold: Doe v. Acme"},
            make_admin_headers(),
        )
    )
    assert held["legal_hold"] is True, (
        f"the action must flip the flag, got {held['legal_hold']}"
    )
    assert held["hold_reason"] == "Litigation hold: Doe v. Acme", (
        f"the action must store the supplied reference, got {held['hold_reason']}"
    )
    assert held["record_kind"] == "CAPTURE", (
        f"the hold must not rewrite record_kind, got {held['record_kind']}"
    )
    assert held["signed_delta"] == 1, (
        f"the hold must not rewrite signed_delta, got {held['signed_delta']}"
    )
    assert_same_instant(
        held["retention_until"],
        "2031-09-01T00:00:00.000Z",
        "the hold must not move the 5 calendar year retention horizon",
    )
    assert held["acknowledgment_id"] == ack["id"]
    assert held["employee_id"] == ctx["employee"]["id"]
    assert_append_only_fields(held)

    reread = validate_success(
        api_client.get_retention_record(row["id"], make_admin_headers())
    )
    assert reread == held, "a single read must return exactly what the action returned"

    flagged, flagged_meta = validate_paginated(
        api_client.list_retention_records(
            make_admin_headers(), params={"legal_hold": True, "limit": 100}
        )
    )
    assert flagged_meta["total_count"] == 1, (
        f"exactly one row is on hold, got {flagged_meta['total_count']}"
    )
    assert flagged[0]["id"] == row["id"]

    _owned, owned_meta = validate_paginated(
        api_client.list_retention_records(
            make_admin_headers(),
            params={"employee_id": ctx["employee"]["id"], "limit": 100},
        )
    )
    assert owned_meta["total_count"] == 1, (
        f"the hold must not append a second row, got {owned_meta['total_count']}"
    )
    assert refresh_acknowledgment(ack["id"])["status"] == "EFFECTIVE", (
        "a retention hold must not touch the evidence row's own status"
    )
