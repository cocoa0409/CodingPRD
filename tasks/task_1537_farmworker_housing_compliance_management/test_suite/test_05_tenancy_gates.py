"""Tenancy creation and activation gates: eligibility, existence order, OCC,
condemnation, posture, member-housed, and the pest-vs-referential priority."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_member,
    apply_pest_treatment,
    condemn_unit_with_finding,
    create_authorization,
    create_household,
    create_tenancy,
    get_household,
    get_unit,
    set_eligibility,
    setup_active_tenancy,
    setup_certified_site,
    setup_eligible_household,
    setup_pending_tenancy,
    setup_site_with_units,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["operator_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]

BOGUS_A = "00000000-0000-4000-8000-0000000000aa"
BOGUS_B = "00000000-0000-4000-8000-0000000000bb"


class TestTenancyCreateGates:
    def test_pending_household_blocks_tenancy_create(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "An `IntakeCoordinator` creates one with the
        `household_id`, the `unit_id`, a `move_in_date`, and
        `expected_unit_version` per §2.7; the household must already be
        `ELIGIBLE` (`ERR_HOUSEHOLD_NOT_ELIGIBLE`)."

        Design: Corner/validations/pending_household_blocks_tenancy_create
        """
        ctx = setup_certified_site(site_name="S")
        unit = get_unit(ctx["unit"]["id"])
        household = create_household(name="Fam PE")  # stays PENDING_ELIGIBILITY

        resp = api.create_tenancy(
            {"household_id": household["id"], "unit_id": unit["id"],
             "move_in_date": "2026-08-11",
             "expected_unit_version": unit["version"]},
            intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_NOT_ELIGIBLE)

    def test_body_fk_existence_left_to_right(self, api,
                                             intake_coordinator_headers):
        """PRD §2.11: "Existence is validated left to right: path identifiers
        first, in path order, then foreign keys in the request body."
        PRD §3.4: "An `IntakeCoordinator` creates one with the `household_id`,
        the `unit_id`, a `move_in_date`, and `expected_unit_version` per §2.7"

        Design: Corner/validations/body_fk_existence_left_to_right
        """
        ctx = setup_certified_site(site_name="S", open=False)
        unit = get_unit(ctx["unit"]["id"])
        household = create_household(name="Fam FK")

        # Both foreign keys bogus: household_id is declared before unit_id.
        both_bad = api.create_tenancy(
            {"household_id": BOGUS_A, "unit_id": BOGUS_B,
             "move_in_date": "2026-08-11",
             "expected_unit_version": unit["version"]},
            intake_coordinator_headers)
        validate_error(both_bad, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND)

        # Valid household, bogus unit.
        unit_bad = api.create_tenancy(
            {"household_id": household["id"], "unit_id": BOGUS_B,
             "move_in_date": "2026-08-11",
             "expected_unit_version": unit["version"]},
            intake_coordinator_headers)
        validate_error(unit_bad, ApiErrorId.ERR_UNIT_NOT_FOUND)

    def test_occ_stale_tenancy_create(self, api, intake_coordinator_headers):
        """PRD §2.7: "creating a tenancy requires `expected_unit_version`. In
        every case the field is non-optional and must equal the parent
        entity's current `version` — the site's, the household's, or the
        unit's respectively. When another write has advanced the parent's
        `version` since the client last read it, the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.4: "the create increments the unit's `version`."

        Design: Corner/validations/occ_stale_tenancy_create
        """
        ctx = setup_certified_site(site_name="S")
        unit_id = ctx["unit"]["id"]
        h1 = setup_eligible_household(name="Fam O1")["household"]
        h2 = setup_eligible_household(
            name="Fam O2", members=(("O2", "1991-01-01", "HEAD"),))[
            "household"]

        observed = get_unit(unit_id)["version"]
        t1 = api.create_tenancy(
            {"household_id": h1["id"], "unit_id": unit_id,
             "move_in_date": "2026-08-11",
             "expected_unit_version": observed},
            intake_coordinator_headers)
        assert t1.status_code == 201, "Setup failed creating T1"

        # T1's create advanced the unit version; the replay is stale.
        stale = api.create_tenancy(
            {"household_id": h2["id"], "unit_id": unit_id,
             "move_in_date": "2026-08-12",
             "expected_unit_version": observed},
            intake_coordinator_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    def test_occ_stale_authorization_create(self, api,
                                            intake_coordinator_headers):
        """PRD §2.7: "creating a deduction authorization requires
        `expected_household_version` ... When another write has advanced the
        parent's `version` since the client last read it, the create is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.5: "Consent replaces consent: creating an authorization
        supersedes the household's existing `ACTIVE` one"

        Design: Corner/validations/occ_stale_authorization_create
        """
        household = create_household(name="Fam OCC")
        observed = household["version"]
        auth1 = validate_success(api.create_deduction_authorization(
            {"household_id": household["id"], "cap_percent": 0.25,
             "purpose": "RENT", "effective_date": "2026-08-01",
             "expected_household_version": observed},
            intake_coordinator_headers), expected_status=201)

        stale = api.create_deduction_authorization(
            {"household_id": household["id"], "cap_percent": 0.35,
             "purpose": "RENT_AND_UTILITIES", "effective_date": "2026-08-01",
             "expected_household_version": observed},
            intake_coordinator_headers)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        auth1_after = validate_success(api.get_deduction_authorization(
            auth1["id"], intake_coordinator_headers))
        assert auth1_after["status"] == "ACTIVE", (
            "The rejected create must not supersede the ACTIVE authorization")


class TestActivationReferentialGates:
    def test_err_member_already_housed_on_activation(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "And no member of the household may belong to another
        tenancy in `ACTIVE` or `NOTICE` (`ERR_MEMBER_ALREADY_HOUSED`)."

        Design: Corner/errors/err_member_already_housed_on_activation
        """
        ctx = setup_site_with_units(site_name="S", unit_specs=[
            {"unit_code": "U1"}, {"unit_code": "U2"}])
        u1, u2 = ctx["units"]
        hh = setup_eligible_household(name="Fam MH")["household"]

        t1 = create_tenancy(hh["id"], u1["id"], move_in_date="2026-08-05")
        activate = api.update_tenancy(t1["id"], {"status": "ACTIVE"}, INTAKE)
        assert activate.status_code == 200, "Setup failed activating T1"

        t2 = create_tenancy(hh["id"], u2["id"], move_in_date="2026-08-12")
        resp = api.update_tenancy(t2["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_MEMBER_ALREADY_HOUSED)

    def test_err_unit_condemned_blocks_activation(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "The unit must stand in `CERTIFIED` or `OCCUPIED`; any
        other status is `ERR_INVALID_STATE`, except `CONDEMNED`, which
        surfaces `ERR_UNIT_CONDEMNED`."
        PRD §3.7: "Every `CRITICAL` finding then condemns its cited unit: from
        `CERTIFIED`, from `OCCUPIED`, or from `HABITABILITY_HOLD`, the unit
        moves to `CONDEMNED`."

        Design: Corner/errors/err_unit_condemned_blocks_activation
        """
        ctx = setup_pending_tenancy(site_name="S", household_name="Fam CD")
        condemn_unit_with_finding(ctx["site"]["id"], ctx["unit"]["id"],
                                  issuer="ci-1")
        assert get_unit(ctx["unit"]["id"])["status"] == "CONDEMNED", (
            "Setup failed: unit should be CONDEMNED")

        resp = api.update_tenancy(ctx["tenancy"]["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_CONDEMNED)

    def test_err_site_restricted_blocks_activation(
            self, api, intake_coordinator_headers):
        """PRD §2.9: "A site is `RESTRICTED` when any of its units is
        `CONDEMNED`"
        PRD §2.9: "While a site is `RESTRICTED`, tenancy activation and notice
        rescission are rejected with `ERR_SITE_RESTRICTED` — new move-ins stop
        until the site digests its enforcement backlog."

        Design: Corner/errors/err_site_restricted_blocks_activation
        """
        ctx = setup_site_with_units(site_name="S", unit_specs=[
            {"unit_code": "U1"}, {"unit_code": "U2"}])
        u1, u2 = ctx["units"]

        # Condemn U1 -> posture RESTRICTED; U2 stays CERTIFIED and clean.
        condemn_unit_with_finding(ctx["site"]["id"], u1["id"], issuer="ci-1")
        summary = validate_success(api.get_site_compliance_summary(
            ctx["site"]["id"], ADMIN))
        assert summary["compliance_posture"] == "RESTRICTED", (
            "Setup failed: posture should be RESTRICTED")

        hh = setup_eligible_household(name="Fam SR")["household"]
        t2 = create_tenancy(hh["id"], u2["id"], move_in_date="2026-08-11")
        resp = api.update_tenancy(t2["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_SITE_RESTRICTED)


class TestPestSafetyBeatsReferential:
    """Difficulty instance: activation that violates both the pest-safety gate
    and the member-already-housed gate reports the safety error."""

    def _setup_double_violation(self, api):
        """Site OPEN; units A and B CERTIFIED; household H ELIGIBLE with one
        member; T1 on A ACTIVE (members already housed); treatment on B
        APPLIED at clock 2026-08-10 with a 3-day buffer (exclusion end
        2026-08-13); T2 on B PENDING_MOVE_IN with move_in 2026-08-12."""
        ctx = setup_site_with_units(site_name="Site PB", unit_specs=[
            {"unit_code": "A"}, {"unit_code": "B"}])
        ua, ub = ctx["units"]
        hh = setup_eligible_household(name="Fam PB")["household"]

        t1 = create_tenancy(hh["id"], ua["id"], move_in_date="2026-08-05")
        activate = api_client_update_active(api, t1["id"])
        assert activate["status"] == "ACTIVE", "Setup failed activating T1"

        treatment = apply_pest_treatment(
            ub["id"], "FUMIGATION", "2026-08-10", 3,
            apply_clock="2026-08-10T09:00:00Z")
        assert treatment["status"] == "APPLIED", "Setup failed applying pest"

        t2 = create_tenancy(hh["id"], ub["id"], move_in_date="2026-08-12")
        return {"ctx": ctx, "household": hh, "t2": t2}

    def test_pest_exclusion_error_wins_over_member_housed(
            self, api, intake_coordinator_headers):
        """PRD §2.8: "Eleventh, pest safety: a move-in date inside an applied
        treatment's exclusion window (`ERR_UNIT_UNDER_PEST_EXCLUSION`), and
        clearing a treatment before its buffer elapses
        (`ERR_REENTRY_BUFFER_ACTIVE`)."
        PRD §2.8: "Sixteenth, the referential and eligibility gates, each with
        its own code: household not `ELIGIBLE` (`ERR_HOUSEHOLD_NOT_ELIGIBLE`),
        a member already housed elsewhere (`ERR_MEMBER_ALREADY_HOUSED`)"

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_pest_blocked_activation
        """
        state = self._setup_double_violation(api)
        resp = api.update_tenancy(state["t2"]["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        # Both the eleventh (pest safety) and sixteenth (member already
        # housed) gates fail; the fixed global order reports the safety gate.
        validate_error(resp, ApiErrorId.ERR_UNIT_UNDER_PEST_EXCLUSION)

    def test_rejected_activation_leaves_tenancy_pending(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "if any `APPLIED` treatment on the unit has an
        `exclusion_end_date` on or after the `move_in_date`, activation is
        rejected with `ERR_UNIT_UNDER_PEST_EXCLUSION`, while a move-in date
        later than every such end date is allowed."

        Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_pest_blocked_activation
        """
        state = self._setup_double_violation(api)
        resp = api.update_tenancy(state["t2"]["id"], {"status": "ACTIVE"},
                                  intake_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNIT_UNDER_PEST_EXCLUSION)

        tenancy = validate_success(api.get_tenancy(state["t2"]["id"],
                                                   intake_coordinator_headers))
        assert tenancy["status"] == "PENDING_MOVE_IN", (
            "A rejected activation mutates nothing")


def api_client_update_active(api, tenancy_id):
    return validate_success(api.update_tenancy(
        tenancy_id, {"status": "ACTIVE"}, INTAKE))
