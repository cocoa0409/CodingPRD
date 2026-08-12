"""Guardian registration defaults, child field validation, waiver lifecycle,
and waiver OCC (PRD §2.7, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, assert_guardian, assert_waiver,
    reset_clock, register_guardian, guardian_headers, add_child, sign_waiver,
    make_staff, staff_headers, create_waiver_payload, get_guardian_fresh,
)
from test_helpers import api_client as _api  # noqa: F401  (client via fixtures module fns)


class TestGuardianRegistration:
    def test_guardian_creation_applies_system_defaults(self, api):
        """PRD §3.1: "The new `Guardian` starts with `membership_status` of
        `NONE`, `loyalty_tier` of `BRONZE`, every counter at zero, and
        `version` 1."
        PRD §2.5: "`id` (string): a server-minted UUID with no type prefix,
        unique per resource."

        Design: Corner/entities/guardian_creation_applies_system_defaults
        """
        reset_clock()
        guardian = register_guardian("G D", "gd@x.com", "901")
        assert_guardian(guardian)
        assert guardian["version"] == 1
        assert guardian["membership_status"] == "NONE"
        assert guardian["loyalty_tier"] == "BRONZE"
        for field in ("credits_granted", "credits_consumed", "credits_held",
                      "credits_available", "credits_statement",
                      "lifetime_points", "points_balance"):
            assert guardian[field] == 0, f"{field} must start at zero"
        # bare UUID with no type prefix (e.g. not "guardian_...")
        assert guardian["id"].count("-") == 4


class TestChildValidation:
    def test_child_creation_missing_birth_date_returns_invalid_request(self, api):
        """PRD §3.1: "Each guardian registers their children with a
        `full_name`, a `birth_date`, and optionally an `allergies` list".
        PRD §2.8: "missing required fields or wrong types yield
        `ERR_VALIDATION` (HTTP 400)".

        Design: Corner/entities/child_creation_missing_birth_date_returns_invalid_request
        """
        guardian = register_guardian("G E", "ge@x.com", "902")
        res = api.create_child(guardian["id"], {"full_name": "Kid X"},
                               guardian_headers(guardian))
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_child_creation_invalid_allergen_enum_rejected(self, api):
        """PRD §3.1: allergy codes are "drawn from the codes `PEANUT`,
        `TREE_NUT`, `MILK`, `EGG`, `WHEAT`, `SOY`, `FISH`, and `SESAME`".
        PRD §2.8: "enum fields carrying an undeclared member yield
        `ERR_INVALID_ENUM` (HTTP 400)".

        Design: Corner/entities/child_creation_invalid_allergen_enum_rejected
        """
        guardian = register_guardian("G F", "gf@x.com", "903")
        res = api.create_child(
            guardian["id"],
            {"full_name": "Kid Y", "birth_date": "2020-01-15",
             "allergies": ["GLUTEN"]},
            guardian_headers(guardian))
        validate_error(res, ApiErrorId.ERR_INVALID_ENUM, expected_status=400)


class TestGuardianRead:
    def test_get_nonexistent_guardian_returns_not_found(self, api):
        """PRD §2.8: "Third, existence: every identifier in the path and every
        foreign-key reference in the body must resolve, checked left-to-right
        along the path (every URL path variable is named `id`), and the first
        unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/get_nonexistent_guardian_returns_not_found
        """
        mgr = make_staff("MANAGER", "Mgr One")
        res = api.get_guardian(NON_EXISTENT_UUID, staff_headers(mgr))
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestWaiverLifecycle:
    def test_waiver_new_signature_supersedes_prior(self, api):
        """PRD §3.1: "any previously `SIGNED` waiver for the same guardian flips
        to `SUPERSEDED` so that at most one waiver per guardian is ever current;
        the act of signing also increments the guardian's `version` by 1."

        Design: Corner/state_machines/waiver_new_signature_supersedes_prior
        """
        reset_clock()
        guardian = register_guardian("G I", "gi@x.com", "906")
        gh = guardian_headers(guardian)
        w1 = sign_waiver(guardian)
        assert_waiver(w1)
        assert w1["status"] == "SIGNED"

        w2 = sign_waiver(guardian)
        assert w2["status"] == "SIGNED"

        data, meta = validate_paginated(api.list_waivers(guardian["id"], gh))
        assert meta["total_count"] == 2
        by_id = {w["id"]: w for w in data}
        assert by_id[w1["id"]]["status"] == "SUPERSEDED"
        assert by_id[w2["id"]]["status"] == "SIGNED"
        assert sum(1 for w in data if w["status"] == "SIGNED") == 1

    def test_waiver_create_with_stale_guardian_version_rejected(self, api):
        """PRD §2.7: "Signing a new waiver for a guardian requires the request
        to carry `expected_guardian_version`, holding the guardian `version`
        the client last observed. If the guardian's current `version` has
        advanced since that read — for example because a newer waiver already
        superseded the client's view — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412), and the client must re-read the
        guardian before signing."

        Design: Corner/cross_cutting_layers/waiver_create_with_stale_guardian_version_rejected
        """
        reset_clock()
        guardian = register_guardian("G AE", "gae@x.com", "930")
        gh = guardian_headers(guardian)
        stale_version = guardian["version"]

        w1 = validate_success(api.create_waiver(
            guardian["id"], create_waiver_payload(stale_version), gh), 201)
        assert w1["status"] == "SIGNED"

        # Replay the pre-signing version: the first signing bumped it.
        res = api.create_waiver(
            guardian["id"], create_waiver_payload(stale_version), gh)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

        data, _ = validate_paginated(api.list_waivers(guardian["id"], gh))
        signed = [w for w in data if w["status"] == "SIGNED"]
        assert len(signed) == 1 and signed[0]["id"] == w1["id"]
