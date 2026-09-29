"""How a guide earns client capacity, and how a permit totals it up.

Covers the four-input capacity formula, the area ceiling frozen onto each
authorization row, the fresh-summation invariant across a revoke cycle, the
qualify action endpoint, and the divergence between the live guide figure and
the frozen authorization figure.
"""
from test_helpers import (
    ApiErrorId,
    MAX_AUTHORIZED_GUIDES_PER_PERMIT,
    authorize_guide,
    create_guide,
    create_qualified_guide,
    list_permit_authorizations,
    read_guide,
    read_permit,
    refile_certification,
    revoke_authorization,
    setup_issued_permit,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
    TEST_USERS,
    make_outfitter_representative_headers,
)

SPECIALIST = TEST_USERS["permit_specialist_headers"]

RITA_LEAD_WFR_7 = {
    "full_name": "Rita Long",
    "qualification_level": "LEAD",
    "first_aid_cert_type": "WFR",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 7,
}
BEN_ASSISTANT_BASIC_2 = {
    "full_name": "Ben Cruz",
    "qualification_level": "ASSISTANT",
    "first_aid_cert_type": "BASIC_FIRST_AID",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 2,
}
NELL_LEAD_BASIC_9 = {
    "full_name": "Nell Park",
    "qualification_level": "LEAD",
    "first_aid_cert_type": "BASIC_FIRST_AID",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 9,
}
TAM_TRAINEE_WEMT_12 = {
    "full_name": "Tam Reyes",
    "qualification_level": "TRAINEE",
    "first_aid_cert_type": "WEMT",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 12,
}
OLA_ASSISTANT_NONE_12 = {
    "full_name": "Ola Vance",
    "qualification_level": "ASSISTANT",
    "first_aid_cert_type": "NONE",
    "first_aid_expires_on": "2030-06-30",
    "seasons_experience": 12,
}


def test_base_capacity_is_the_weaker_tier_plus_a_capped_bonus_across_the_input_grid():
    """PRD §3.1: "The guide's field tier contributes a ratio allowance of 0 for a `TRAINEE`, 4
    for an `ASSISTANT` and 8 for a `LEAD`. The medical tier contributes a certification cap of
    0 for `NONE`, 4 for `BASIC_FIRST_AID`, 8 for `WFR` and 12 for `WEMT`. An experience bonus
    adds one point for every three completed seasons, discarding any remainder, and is never
    worth more than 2 points. Two categorical cases short-circuit the arithmetic entirely: a
    `TRAINEE`, or a guide whose certification type is `NONE`, has a `base_client_capacity` of 0
    regardless of anything else. For every other guide, the capacity is the **lesser** of the
    field allowance and the certification cap — the weaker of the two tiers binds — plus the
    experience bonus, and never less than 0."
    PRD §3.1: "A `LEAD` holding `WFR` with seven completed seasons therefore carries 8 (the
    lesser of 8 and 8) plus 2 (seven divided by three, floored, capped at 2), for 10."
    PRD §3.1: "A guide enters in `status` `PENDING_QUALIFICATION` with `qualified_at` null, and
    `base_client_capacity` is computed immediately even though the guide is not yet qualified"

    Design: Difficulty/combinatorial_formula/guide_client_capacity_four_input_min_interaction
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]

    rita = create_guide(outfitter_id, **RITA_LEAD_WFR_7)
    ben = create_guide(outfitter_id, **BEN_ASSISTANT_BASIC_2)
    nell = create_guide(outfitter_id, **NELL_LEAD_BASIC_9)
    tam = create_guide(outfitter_id, **TAM_TRAINEE_WEMT_12)
    ola = create_guide(outfitter_id, **OLA_ASSISTANT_NONE_12)

    assert rita["base_client_capacity"] == 10, "min(8, 8) + min(2, 7 // 3)"
    assert ben["base_client_capacity"] == 4, "min(4, 4) + min(2, 2 // 3)"
    assert nell["base_client_capacity"] == 6, (
        "min(8, 4) + min(2, 9 // 3): a higher level and three more seasons than Ben, "
        "yet the basic-first-aid tier binds and the bonus is capped at 2"
    )
    assert tam["base_client_capacity"] == 0, (
        "the TRAINEE short-circuit outranks WEMT and twelve seasons"
    )
    assert ola["base_client_capacity"] == 0, (
        "the NONE certification short-circuit outranks ASSISTANT and twelve seasons"
    )

    for guide in (rita, ben, nell, tam, ola):
        assert guide["status"] == "PENDING_QUALIFICATION"
        assert guide["qualified_at"] is None

    assert read_guide(rita["id"])["base_client_capacity"] == 10
    assert read_guide(nell["id"])["base_client_capacity"] == 6


def test_the_area_ceiling_is_applied_last_and_frozen_onto_every_authorization_row():
    """PRD §3.6: "Its `authorized_client_capacity` is computed once, at this instant, as the
    lesser of the area's `max_clients_per_guide` and the guide's `base_client_capacity`, and is
    then **frozen**"
    PRD §3.6: "The permit's `authorized_client_capacity_total` is then recomputed as a fresh
    sum of `authorized_client_capacity` over the permit's `AUTHORIZED` rows — always a full
    re-summation, never an increment — and the permit's `version` advances."

    Design: Difficulty/combinatorial_formula/guide_client_capacity_four_input_min_interaction
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]
    assert context["use_area"]["max_clients_per_guide"] == 8

    rita = create_qualified_guide(outfitter_id, **RITA_LEAD_WFR_7)
    ben = create_qualified_guide(outfitter_id, **BEN_ASSISTANT_BASIC_2)
    nell = create_qualified_guide(outfitter_id, **NELL_LEAD_BASIC_9)
    assert [rita["base_client_capacity"], ben["base_client_capacity"],
            nell["base_client_capacity"]] == [10, 4, 6]

    first = authorize_guide(permit_id, rita["id"], outfitter_id)
    assert first["authorized_client_capacity"] == 8, (
        "the area ceiling min(8, 10) is applied after the formula, not inside it"
    )
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8

    second = authorize_guide(permit_id, ben["id"], outfitter_id)
    assert second["authorized_client_capacity"] == 4, "min(8, 4) — the ceiling does not bind"
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 12

    third = authorize_guide(permit_id, nell["id"], outfitter_id)
    assert third["authorized_client_capacity"] == 6, "min(8, 6) — the ceiling does not bind"

    permit = read_permit(permit_id)
    assert permit["authorized_client_capacity_total"] == 18, (
        "8 + 4 + 6 over the frozen row values, not 10 + 4 + 6 over the base capacities"
    )
    assert read_guide(rita["id"])["base_client_capacity"] == 10, (
        "the guide's own figure is untouched by the ceiling that bound its authorization"
    )
    rows, _meta = list_permit_authorizations(permit_id)
    assert sum(row["authorized_client_capacity"] for row in rows) == 18


def _permit_with_two_authorized_guides():
    """An ISSUED permit whose roster totals 12 = min(8, 10) + min(8, 4)."""
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]
    rita = create_qualified_guide(outfitter_id, **RITA_LEAD_WFR_7)
    ben = create_qualified_guide(outfitter_id, **BEN_ASSISTANT_BASIC_2)
    first = authorize_guide(permit_id, rita["id"], outfitter_id)
    second = authorize_guide(permit_id, ben["id"], outfitter_id)
    assert first["authorized_client_capacity"] == 8
    assert second["authorized_client_capacity"] == 4
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 12
    return {
        "outfitter_id": outfitter_id,
        "permit_id": permit_id,
        "rita": rita,
        "ben": ben,
        "first": first,
        "second": second,
    }


def test_revoked_rows_keep_their_frozen_capacity_while_the_total_counts_only_the_live_set():
    """PRD §3.6: "The revoked row keeps its frozen `authorized_client_capacity` for the audit
    record but stops counting toward the permit's total, which is again recomputed as a fresh
    sum; `revoked_at` is stamped and both rows' `version` advance."
    PRD §3.6: "Revocation is available to the holder and to an `AuthorizedOfficer` and carries a
    `revocation_reason_code`, which on this path is `HOLDER_REQUEST`"

    Design: Difficulty/compensating_invariant/guide_capacity_total_conservation_across_revoke_cycle
    """
    stage = _permit_with_two_authorized_guides()
    permit_id = stage["permit_id"]
    outfitter_id = stage["outfitter_id"]

    revoked_first = revoke_authorization(stage["first"]["id"], outfitter_id)
    assert revoked_first["status"] == "REVOKED"
    assert revoked_first["revocation_reason_code"] == "HOLDER_REQUEST"
    assert revoked_first["revoked_at"] is not None
    assert revoked_first["authorized_client_capacity"] == 8, (
        "the frozen figure survives the revocation for the audit record"
    )
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 4, (
        "the sum runs over AUTHORIZED rows only"
    )

    revoked_second = revoke_authorization(stage["second"]["id"], outfitter_id)
    assert revoked_second["authorized_client_capacity"] == 4
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 0

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 2
    assert [row["status"] for row in rows] == ["REVOKED", "REVOKED"]
    assert sum(row["authorized_client_capacity"] for row in rows) == 12, (
        "twelve points of capacity are still recorded in the table and none of it counts"
    )

    live, live_meta = list_permit_authorizations(permit_id, {"status": "AUTHORIZED"})
    assert live == [] and live_meta["total_count"] == 0


def test_revoke_then_reauthorize_restores_the_identical_total_by_fresh_summation():
    """PRD §3.6: "The permit's `authorized_client_capacity_total` is then recomputed as a fresh
    sum of `authorized_client_capacity` over the permit's `AUTHORIZED` rows — always a full
    re-summation, never an increment — and the permit's `version` advances."
    PRD §3.6: "The authorization must still be `AUTHORIZED`; `REVOKED` is terminal, so a second
    revocation — whether the first was manual or one of the system cascades — is refused with
    `ERR_AUTHORIZATION_NOT_ACTIVE` rather than treated as a harmless no-op."
    PRD §3.6: "Finally the roster is capped: at most **8** authorizations with `status`
    `AUTHORIZED` may stand on one permit at a time, and the ninth is `ERR_GUIDE_ROSTER_FULL`."

    Design: Difficulty/compensating_invariant/guide_capacity_total_conservation_across_revoke_cycle
    """
    stage = _permit_with_two_authorized_guides()
    permit_id = stage["permit_id"]
    outfitter_id = stage["outfitter_id"]
    before = read_permit(permit_id)

    revoke_authorization(stage["first"]["id"], outfitter_id)
    revoke_authorization(stage["second"]["id"], outfitter_id)
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 0

    validate_error(
        api_client.revoke_guide_authorization(
            stage["first"]["id"], {"revocation_reason_code": "HOLDER_REQUEST"},
            make_outfitter_representative_headers(outfitter_id),
        ),
        ApiErrorId.ERR_AUTHORIZATION_NOT_ACTIVE,
    )

    third = authorize_guide(permit_id, stage["rita"]["id"], outfitter_id)
    assert third["id"] != stage["first"]["id"], "REVOKED is terminal, so a new row is created"
    assert third["status"] == "AUTHORIZED"
    assert third["authorized_client_capacity"] == 8, "re-frozen from unchanged inputs"
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8

    fourth = authorize_guide(permit_id, stage["ben"]["id"], outfitter_id)
    assert fourth["authorized_client_capacity"] == 4

    after = read_permit(permit_id)
    assert after["authorized_client_capacity_total"] == 12, (
        "the revoke-then-reauthorize pair compensates exactly: the total is reached by "
        "summing two live rows, not by adding back what was subtracted"
    )
    assert after["version"] > before["version"]

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 4
    assert [row["status"] for row in rows] == [
        "REVOKED", "REVOKED", "AUTHORIZED", "AUTHORIZED"
    ]
    live, live_meta = list_permit_authorizations(permit_id, {"status": "AUTHORIZED"})
    assert live_meta["total_count"] == 2
    assert {row["id"] for row in live} == {third["id"], fourth["id"]}
    assert live_meta["total_count"] < MAX_AUTHORIZED_GUIDES_PER_PERMIT, (
        "four rows exist but only two stand against the cap of eight"
    )


def test_qualify_takes_an_empty_body_and_screens_only_the_two_safety_conditions():
    """PRD §3.1: "Two safety conditions guard the transition: the `first_aid_cert_type` must not
    be `NONE`, else `ERR_FIRST_AID_CERT_MISSING`, and `first_aid_expires_on` must be on or after
    the current logical date, else `ERR_FIRST_AID_CERT_EXPIRED` — the expiry boundary is
    inclusive, so a certificate expiring exactly today is still valid."
    PRD §3.1: "Qualification stamps `qualified_at` from the logical clock and recomputes
    `base_client_capacity`. A `TRAINEE` may be qualified; it simply keeps a
    `base_client_capacity` of 0 and can never be authorized to a permit."
    PRD §3.1: "The filing overwrites both certification fields, recomputes
    `base_client_capacity` and stamps `qualified_at`"

    Design: Corner/endpoints/qualify_is_an_action_endpoint_with_an_empty_body_and_two_safety_preconditions
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    holder = context["holder_headers"]

    rita = create_guide(outfitter_id, **RITA_LEAD_WFR_7)
    nate = create_guide(
        outfitter_id, full_name="Nate Poe", qualification_level="LEAD",
        first_aid_cert_type="NONE", first_aid_expires_on="2030-06-30",
        seasons_experience=5,
    )
    ida = create_guide(
        outfitter_id, full_name="Ida Vane", qualification_level="ASSISTANT",
        first_aid_cert_type="WFR", first_aid_expires_on="2026-12-31",
        seasons_experience=0,
    )
    tom = create_guide(outfitter_id, **TAM_TRAINEE_WEMT_12)
    ivy = create_guide(
        outfitter_id, full_name="Ivy Cole", qualification_level="ASSISTANT",
        first_aid_cert_type="BASIC_FIRST_AID", first_aid_expires_on="2027-01-05",
        seasons_experience=6,
    )

    qualified_rita = validate_success(api_client.qualify_guide(rita["id"], SPECIALIST))
    assert qualified_rita["status"] == "QUALIFIED"
    assert qualified_rita["qualified_at"].startswith("2027-01-05")
    assert qualified_rita["base_client_capacity"] == 10

    validate_error(
        api_client.qualify_guide(nate["id"], SPECIALIST),
        ApiErrorId.ERR_FIRST_AID_CERT_MISSING,
    )
    assert read_guide(nate["id"])["status"] == "PENDING_QUALIFICATION"

    validate_error(
        api_client.qualify_guide(ida["id"], SPECIALIST),
        ApiErrorId.ERR_FIRST_AID_CERT_EXPIRED,
    )
    assert read_guide(ida["id"])["status"] == "PENDING_QUALIFICATION"

    refiled = refile_certification(
        ida["id"], outfitter_id,
        first_aid_cert_type="WFR", first_aid_expires_on="2030-06-30",
    )
    assert refiled["first_aid_expires_on"] == "2030-06-30"
    repaired = validate_success(api_client.qualify_guide(ida["id"], SPECIALIST))
    assert repaired["status"] == "QUALIFIED"
    assert repaired["base_client_capacity"] == 4, "min(4, 8) with no experience bonus"

    qualified_tom = validate_success(api_client.qualify_guide(tom["id"], SPECIALIST))
    assert qualified_tom["status"] == "QUALIFIED", "the TRAINEE level does not block this act"
    assert qualified_tom["base_client_capacity"] == 0

    qualified_ivy = validate_success(api_client.qualify_guide(ivy["id"], SPECIALIST))
    assert qualified_ivy["status"] == "QUALIFIED", (
        "a certificate expiring exactly on the logical date is still valid"
    )
    assert qualified_ivy["base_client_capacity"] == 6, "min(4, 4) + min(2, 6 // 3)"

    rows, meta = validate_paginated(
        api_client.list_guides(outfitter_id, holder, params={"status": "QUALIFIED"})
    )
    assert meta["total_count"] == 4
    assert {row["full_name"] for row in rows} == {
        "Rita Long", "Ida Vane", "Tam Reyes", "Ivy Cole"
    }


def test_a_certification_downgrade_moves_the_live_figure_but_not_the_frozen_one():
    """PRD §3.1: "The filing overwrites both certification fields, recomputes
    `base_client_capacity` and stamps `qualified_at`"
    PRD §3.6: "Its `authorized_client_capacity` is computed once, at this instant, as the lesser
    of the area's `max_clients_per_guide` and the guide's `base_client_capacity`, and is then
    **frozen**: a later certification upgrade that raises the guide's `base_client_capacity`
    does not raise the capacity already authorized, and the holder must revoke and re-authorize
    to capture the increase."
    PRD §3.6: "Authorizations are listable two ways, both oldest first and both including
    revoked rows unless an optional `status` filter narrows them"

    Design: Corner/endpoints/frozen_authorization_capacity_and_live_guide_capacity_diverge_and_only_a_new_link_resyncs_them
    """
    context = setup_issued_permit()
    outfitter_id = context["outfitter"]["id"]
    permit_id = context["permit"]["id"]

    rita = create_qualified_guide(outfitter_id, **RITA_LEAD_WFR_7)
    assert rita["base_client_capacity"] == 10
    first = authorize_guide(permit_id, rita["id"], outfitter_id)
    assert first["authorized_client_capacity"] == 8

    downgraded = refile_certification(
        rita["id"], outfitter_id,
        first_aid_cert_type="BASIC_FIRST_AID", first_aid_expires_on="2030-06-30",
    )
    assert downgraded["status"] == "QUALIFIED"
    assert downgraded["base_client_capacity"] == 6, (
        "min(4, 8) + min(2, 7 // 3): the live figure follows the downgrade at once"
    )

    live_rows, _meta = list_permit_authorizations(permit_id, {"status": "AUTHORIZED"})
    assert [row["authorized_client_capacity"] for row in live_rows] == [8], (
        "a certification write does not re-derive a frozen authorization"
    )
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 8, (
        "the total sums frozen row values, not the guide's live capacity"
    )

    revoke_authorization(first["id"], outfitter_id)
    assert read_permit(permit_id)["authorized_client_capacity_total"] == 0

    second = authorize_guide(permit_id, rita["id"], outfitter_id)
    assert second["authorized_client_capacity"] == 6, (
        "min(8, 6) — re-linking is the only path that adopts the new live capacity"
    )
    permit = read_permit(permit_id)
    assert permit["authorized_client_capacity_total"] == 6
    assert permit["administrative_status"] == "ISSUED"
    assert permit["compliance_status"] == "COMPLIANT", (
        "no rule ties a holder's own roster change on an ISSUED permit to compliance"
    )

    rows, meta = list_permit_authorizations(permit_id)
    assert meta["total_count"] == 2
    assert [row["id"] for row in rows] == [first["id"], second["id"]]
    assert rows[0]["status"] == "REVOKED"
    assert rows[0]["revocation_reason_code"] == "HOLDER_REQUEST"
    assert rows[0]["authorized_client_capacity"] == 8, "the audit record keeps the old freeze"
    assert rows[1]["status"] == "AUTHORIZED"
    assert rows[1]["authorized_client_capacity"] == 6
