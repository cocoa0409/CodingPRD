"""Host agreements: commission gating, renewal-boundary overlap, termination
cascade, ops-run expiry, soft-delete listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_host_agreement_payload,
    create_material_payload,
    create_program_payload,
    create_site_payload,
    get_success_data,
    setup_program_with_operational_site,
    setup_verified_participant_with_grant,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency /
#             site_commission_requires_active_agreement (2 tests)
# ---------------------------------------------------------------------------

def _setup_site_with_draft_agreement(api):
    prog = validate_success(api.create_program(
        create_program_payload(name="P13", fiscal_year=2026), ADMIN),
        expected_status=201)
    prog_id = prog["id"]
    site = validate_success(api.create_site(prog_id, create_site_payload(), ADMIN),
                            expected_status=201)
    agr = validate_success(api.create_host_agreement(
        prog_id, create_host_agreement_payload(site["id"]), ADMIN),
        expected_status=201)
    api.create_material(prog_id, create_material_payload(), ADMIN)
    return prog_id, site["id"], agr["id"]


def test_commission_blocked_while_agreement_is_draft(api):
    """PRD §3.2: "Commissioning transitions a site from `ONBOARDING` to
    `OPERATIONAL`. It requires an `ACTIVE` host agreement covering the site —
    otherwise `ERR_SITE_NO_ACTIVE_AGREEMENT` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/site_commission_requires_active_agreement
    """
    prog_id, site_id, _agr_id = _setup_site_with_draft_agreement(api)

    resp = api.commission_site(prog_id, site_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_SITE_NO_ACTIVE_AGREEMENT)


def test_commission_succeeds_after_agreement_activation(api):
    """PRD §3.2: "Commissioning transitions a site from `ONBOARDING` to
    `OPERATIONAL`. It requires an `ACTIVE` host agreement covering the site —
    otherwise `ERR_SITE_NO_ACTIVE_AGREEMENT` (HTTP 409) — and requires the
    owning program to be `ACTIVE`."
    PRD §3.2: "As a side effect, the site's posture is computed for the first
    time; a freshly commissioned site with zero stored mass and no open
    reports lands at `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/site_commission_requires_active_agreement
    """
    prog_id, site_id, agr_id = _setup_site_with_draft_agreement(api)

    get_success_data(api.activate_host_agreement(prog_id, agr_id, ADMIN))
    site = validate_success(api.commission_site(prog_id, site_id, ADMIN))
    assert site["status"] == "OPERATIONAL"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap /
#             host_agreement_term_renewal_touching_boundary (2 tests)
# ---------------------------------------------------------------------------

def _setup_agreement_overlap_scenario(api):
    # Terms must satisfy PRD §3.2's activation rule "term_end must be strictly
    # after the current logical clock" (clock starts at 2026-08-01T00:00:00Z),
    # so the half-open boundary scenario is anchored after the clock.
    prog = validate_success(api.create_program(
        create_program_payload(name="P16", fiscal_year=2026), ADMIN),
        expected_status=201)
    prog_id = prog["id"]
    site = validate_success(api.create_site(prog_id, create_site_payload(), ADMIN),
                            expected_status=201)
    site_id = site["id"]

    a1 = validate_success(api.create_host_agreement(
        prog_id, create_host_agreement_payload(
            site_id, host_name="H1",
            term_start="2026-08-01T00:00:00Z",
            term_end="2026-12-01T00:00:00Z"), ADMIN), expected_status=201)
    get_success_data(api.activate_host_agreement(prog_id, a1["id"], ADMIN))

    a2 = validate_success(api.create_host_agreement(
        prog_id, create_host_agreement_payload(
            site_id, host_name="H2",
            term_start="2026-12-01T00:00:00Z",
            term_end="2027-04-01T00:00:00Z"), ADMIN), expected_status=201)
    a3 = validate_success(api.create_host_agreement(
        prog_id, create_host_agreement_payload(
            site_id, host_name="H3",
            term_start="2026-11-15T00:00:00Z",
            term_end="2027-03-01T00:00:00Z"), ADMIN), expected_status=201)
    return prog_id, a1["id"], a2["id"], a3["id"]


def test_touching_renewal_boundary_agreement_activates(api):
    """PRD §3.2: "no other `ACTIVE` agreement for the same site may have a
    term overlapping this one, failing with `ERR_AGREEMENT_OVERLAP` (HTTP 409)
    — overlap here follows the half-open rule of §2.6, so a renewal whose
    `term_start` exactly equals the outgoing agreement's `term_end` is
    permitted"

    Design: Difficulty/resource_temporal_overlap/host_agreement_term_renewal_touching_boundary
    """
    prog_id, _a1, a2, _a3 = _setup_agreement_overlap_scenario(api)

    resp = api.activate_host_agreement(prog_id, a2, ADMIN)
    agr = validate_success(resp)
    assert agr["status"] == "ACTIVE"


def test_strict_interior_overlap_rejected(api):
    """PRD §2.6: "Two intervals conflict only when each one's start falls
    strictly before the other's end; touching boundaries — where one
    interval's end equals the other's start — never conflict."
    PRD §3.2: "no other `ACTIVE` agreement for the same site may have a term
    overlapping this one, failing with `ERR_AGREEMENT_OVERLAP` (HTTP 409)"

    Design: Difficulty/resource_temporal_overlap/host_agreement_term_renewal_touching_boundary
    """
    prog_id, _a1, _a2, a3 = _setup_agreement_overlap_scenario(api)

    resp = api.activate_host_agreement(prog_id, a3, ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_OVERLAP)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade / agreement_terminate_cascade_depth2 (2 tests)
# ---------------------------------------------------------------------------

def _setup_operational_site_with_participant(api):
    ids = setup_program_with_operational_site()
    part = setup_verified_participant_with_grant(ids["prog_id"], ids["site_id"])
    return ids, part


def test_agreement_termination_clears_site_link_and_closes_posture(api):
    """PRD §3.2: "In either termination path, if the terminating agreement is
    the one referenced by its site's `host_agreement_id`, that link is cleared
    and the site's posture is recomputed — which, with no covering agreement,
    drives the posture to `CLOSED` under §2.7's agreement-coverage tier."

    Design: Difficulty/transitive_cascade/agreement_terminate_cascade_depth2
    """
    ids, _part = _setup_operational_site_with_participant(api)
    prog_id, site_id, agr_id = ids["prog_id"], ids["site_id"], ids["agr_id"]

    agr = validate_success(api.terminate_host_agreement(prog_id, agr_id, ADMIN))
    assert agr["status"] == "TERMINATED"

    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    assert site["posture"] == "CLOSED", (
        f"with no active agreement the posture must be CLOSED, got "
        f"{site['posture']}")


def test_drop_rejected_after_agreement_termination_closes_site(api):
    """PRD §2.7: "Otherwise, if the site's `host_agreement_id` is null — no
    currently effective agreement — posture is `CLOSED`; a site with no active
    agreement cannot accept drops."
    PRD §2.7: "a site at `SUSPENDED` or `CLOSED` rejects every drop with
    `ERR_SITE_POSTURE_BLOCKS_DROP` (HTTP 409)."

    Design: Difficulty/transitive_cascade/agreement_terminate_cascade_depth2
    """
    from test_helpers import create_drop_payload, get_site_version
    ids, part = _setup_operational_site_with_participant(api)
    prog_id, site_id, agr_id, mat_id = (
        ids["prog_id"], ids["site_id"], ids["agr_id"], ids["mat_id"])

    get_success_data(api.terminate_host_agreement(prog_id, agr_id, ADMIN))

    sv = get_site_version(prog_id, site_id)
    resp = api.create_drop(
        prog_id, site_id,
        create_drop_payload(part["part_id"], part["grant_id"], mat_id, sv,
                            gross_weight_kg=1.00,
                            occurred_at="2026-07-01T10:00:00Z"),
        part["part_headers"])
    validate_error(resp, ApiErrorId.ERR_SITE_POSTURE_BLOCKS_DROP)


# ---------------------------------------------------------------------------
# Corner: errors/error_agreement_already_expired (1 test)
# ---------------------------------------------------------------------------

def test_activate_agreement_with_past_term_end_rejected(api):
    """PRD §3.2: "`term_end` must be strictly after the current logical clock,
    failing with `ERR_AGREEMENT_ALREADY_EXPIRED` (HTTP 409) for an agreement
    whose term has already run out."

    Design: Corner/errors/error_agreement_already_expired
    """
    prog = validate_success(api.create_program(
        create_program_payload(name="P", fiscal_year=2026), ADMIN),
        expected_status=201)
    site = validate_success(api.create_site(prog["id"], create_site_payload(), ADMIN),
                            expected_status=201)
    agr = validate_success(api.create_host_agreement(
        prog["id"],
        create_host_agreement_payload(site["id"],
                                      term_start="2026-01-01T00:00:00Z",
                                      term_end="2026-06-01T00:00:00Z"),
        ADMIN), expected_status=201)

    # Clock default is 2026-08-01, already past term_end 2026-06-01
    resp = api.activate_host_agreement(prog["id"], agr["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_AGREEMENT_ALREADY_EXPIRED)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers/ops_run_expires_agreement_and_closes_site (1 test)
# ---------------------------------------------------------------------------

def test_ops_run_expires_agreement_and_closes_site(api):
    """PRD §3.2: "the ops-run checkpoint transitions any `ACTIVE` agreement
    whose `term_end` has been reached to `EXPIRED`, clears the site's
    `host_agreement_id` if it points at the expired agreement, and recomputes
    an `OPERATIONAL` site's posture, dropping it to `CLOSED` when no other
    `ACTIVE` agreement covers the site."

    Design: Corner/cross_cutting_layers/ops_run_expires_agreement_and_closes_site
    """
    ids = setup_program_with_operational_site(
        agreement_overrides={"term_end": "2026-08-10T00:00:00Z"})
    prog_id, site_id, agr_id = ids["prog_id"], ids["site_id"], ids["agr_id"]

    get_success_data(api.set_clock("2026-08-15T00:00:00Z", ADMIN))
    get_success_data(api.run_ops(prog_id, ADMIN))

    agr = validate_success(api.get_host_agreement(prog_id, agr_id, ADMIN))
    assert agr["status"] == "EXPIRED"

    site = validate_success(api.get_site(prog_id, site_id, ADMIN))
    assert site["posture"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_layers/archived_site_excluded_from_default_list (1 test)
# ---------------------------------------------------------------------------

def test_archived_site_excluded_from_default_listing(api):
    """PRD §2.9: "archiving sets a site's `archived` flag to true, after which
    the site is excluded from default site listings. Callers who need archived
    sites pass `include_archived` on the listing."

    Design: Corner/cross_cutting_layers/archived_site_excluded_from_default_list
    """
    ids = setup_program_with_operational_site()
    prog_id, site_id = ids["prog_id"], ids["site_id"]

    get_success_data(api.decommission_site(prog_id, site_id, ADMIN))
    get_success_data(api.archive_site(prog_id, site_id, ADMIN))

    data_default, meta_default = validate_paginated(api.list_sites(prog_id, ADMIN))
    assert meta_default["total_count"] == 0, (
        f"archived site must be excluded by default, got "
        f"{meta_default['total_count']}")

    data_inc, meta_inc = validate_paginated(
        api.list_sites(prog_id, ADMIN, params={"include_archived": True}))
    assert meta_inc["total_count"] == 1
