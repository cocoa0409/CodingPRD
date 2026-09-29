"""The two residency variants of the compact privilege determination."""
from test_helpers import (
    ApiClient,
    assert_license_dimensions,
    assert_privilege_triple,
    determine_privilege,
    reread_license,
    reread_nurse,
    residency_evidence_entry,
    seed_active_license,
)

_EVIDENCE = [
    residency_evidence_entry("DRIVER_LICENSE", "MI", "2026-05-01T00:00:00Z"),
    residency_evidence_entry("TAX_RETURN", "OH", "2026-06-01T00:00:00Z"),
]


def _out_of_state_evidence_context(api: ApiClient):
    """A compact-state credential whose documents point to a different state."""
    return seed_active_license(
        api,
        program_overrides={
            "program_code": "OH-BSN-02",
            "program_name": "Scioto BSN",
            "degree_level": "BSN",
            "nclex_first_time_pass_rate_bp": 9100,
        },
        nurse_overrides={
            "full_name": "Kai Moreno",
            "birth_year": 1990,
            "ssn_last4": "7712",
            "declared_primary_state": "OH",
            "residency_evidence": _EVIDENCE,
        },
    )


def test_declared_variant_reads_multistate_while_evidenced_variant_reads_single_state(
    api: ApiClient,
):
    """PRD §3.3: "Under `RESIDENCY_DECLARED` — the variant used at issuance, on
    every registration change, and whenever it is requested explicitly — the
    primary state of residence is simply the nurse's `declared_primary_state`,
    taken at face value."

    PRD §3.3: "Candidates are ranked first by the evidentiary weight of their
    `evidence_type`, where a `DRIVER_LICENSE` outranks a `TAX_RETURN`, which in
    turn outranks a `VOTER_REGISTRATION`; among entries of equal weight, the
    later `effective_date` ranks higher; and if two entries still tie, the one
    with the lower zero-based index in `residency_evidence` wins."

    PRD §3.3: "If the resolved state does not equal the issuing board's
    `state_code`, the answer is `SINGLE_STATE` — a nurse whose home is elsewhere
    holds only a single-state credential here."

    PRD §3.3: "Because the two variants can disagree on identical nurse data,
    the same credential can read `MULTISTATE` under `RESIDENCY_DECLARED` and
    `SINGLE_STATE` under `RESIDENCY_EVIDENCED`."

    Design: Difficulty/dual_variant_calc/privilege_variant_flips_multistate_to_single_state
    """
    ctx = _out_of_state_evidence_context(api)

    declared = determine_privilege(api, ctx["license_id"], "RESIDENCY_DECLARED")
    assert_privilege_triple(declared, "MULTISTATE",
                            expected_variant="RESIDENCY_DECLARED",
                            expected_basis_state="OH")

    evidenced = determine_privilege(api, ctx["license_id"], "RESIDENCY_EVIDENCED")
    assert_privilege_triple(evidenced, "SINGLE_STATE",
                            expected_variant="RESIDENCY_EVIDENCED",
                            expected_basis_state="MI")


def test_variant_flip_writes_only_the_three_privilege_fields(api: ApiClient):
    """PRD §3.3: "The result is written to three fields:
    `multistate_privilege_status`, which is one of `NOT_ELIGIBLE`,
    `SINGLE_STATE`, `MULTISTATE`, or `PRIVILEGE_REVOKED`; `privilege_variant`,
    which records whether `RESIDENCY_DECLARED` or `RESIDENCY_EVIDENCED` was
    used; and `privilege_basis_state`, which records the primary state of
    residence the determination resolved to."

    PRD §2.7: "A third field, `multistate_privilege_status`, is not a dimension
    at all but a pure derivation recomputed from both dimensions plus residency
    and board data."

    PRD §3.1: "Editing residency data deliberately does **not** recompute any
    credential's `multistate_privilege_status` — a fresh privilege determination
    must be run explicitly by a `LicensureAnalyst` before the compact posture
    reflects the new data."

    Design: Difficulty/dual_variant_calc/privilege_variant_flips_multistate_to_single_state
    """
    ctx = _out_of_state_evidence_context(api)
    nurse_version_before = ctx["nurse"]["version"]

    determine_privilege(api, ctx["license_id"], "RESIDENCY_DECLARED")
    determine_privilege(api, ctx["license_id"], "RESIDENCY_EVIDENCED")

    credential = reread_license(api, ctx["license_id"])
    assert_license_dimensions(credential, "ACTIVE", "CLEAR")
    assert credential["privilege_variant"] == "RESIDENCY_EVIDENCED", (
        "The last determination run is the one recorded in privilege_variant"
    )

    nurse = reread_nurse(api, ctx["nurse_id"])
    assert nurse["version"] == nurse_version_before, (
        f"A privilege determination must not mutate the nurse record: version "
        f"moved from {nurse_version_before} to {nurse['version']}"
    )
    assert nurse["declared_primary_state"] == "OH", (
        "The nurse's own declaration is read, never rewritten"
    )
    assert nurse["residency_evidence"] == _EVIDENCE, (
        "The evidence array is read in declaration order, never reordered"
    )
