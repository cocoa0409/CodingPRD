"""Credit strategy assembly: OCC on the project version, strategy completeness
gates, attempt uniqueness, and the create/drop compensating pair
(PRD §2.5, §3.2)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_attempt,
    create_credit_entry,
    create_energy_model_payload,
    create_members,
    create_project,
    get_attempt,
    get_project,
    get_success_data,
    lock_strategy,
    make_energy_modeler_headers,
    make_project_administrator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]
ANY = TEST_USERS["any_headers"]


def _prereq_entry(points=0, code="EAp1"):
    return create_credit_entry(
        credit_code=code, title="Fundamental Commissioning",
        category="ENERGY_ATMOSPHERE", points_possible=points,
        is_prerequisite=True, phase_eligibility="BOTH", requires_energy_model=False)


class TestStrategyLockOCC:
    def test_stale_version_lock_strategy_blocked(self, api):
        """PRD §2.5: "Locking the credit strategy requires the request to carry `expected_project_version` holding the project's `version` as last observed by the client; if the project's current `version` no longer matches — for example because another writer created or dropped an attempt, so the strategy membership the client believes it is locking has changed — the lock is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_version_lock_strategy_blocked
        """
        members = create_members()
        entry = _prereq_entry()
        project = create_project(members["admin"]["id"], project_name="OCC Tower")
        stale_version = project["version"]
        create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])

        resp = api.lock_strategy(
            project["id"], stale_version,
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
        assert get_project(project["id"])["status"] == "REGISTERED"

    def test_correct_version_lock_strategy_succeeds(self, api):
        """PRD §2.5: "Locking the credit strategy requires the request to carry `expected_project_version` holding the project's `version` as last observed by the client; if the project's current `version` no longer matches — for example because another writer created or dropped an attempt, so the strategy membership the client believes it is locking has changed — the lock is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."
        PRD §3.2: "A successful lock moves the project `REGISTERED → STRATEGY_LOCKED` and increments its `version` by one."

        Design: Corner/complexity_layers/occ_correct_version_lock_strategy_succeeds
        """
        members = create_members()
        entry = _prereq_entry()
        project = create_project(members["admin"]["id"], project_name="OCC2 Tower")
        create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        fresh_version = get_project(project["id"])["version"]

        locked = validate_success(
            api.lock_strategy(
                project["id"], fresh_version,
                make_project_administrator_headers(members["admin"]["id"]))
        )
        assert locked["status"] == "STRATEGY_LOCKED"

    def test_stale_version_energy_model_create_blocked(self, api):
        """PRD §2.5: "Creating an energy model carries the same requirement and the same rejection: a modeler whose last observed project version has been overtaken — for instance because another model create has already altered the project's model inventory — is working from a stale view, and the create is rejected with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/occ_stale_version_energy_model_create_blocked
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="OCC3 Tower")
        stale_version = project["version"]
        baseline = validate_success(
            api.create_energy_model(
                create_energy_model_payload(
                    project["id"], stale_version, model_type="BASELINE"),
                make_energy_modeler_headers(members["modeler"]["id"])),
            201,
        )

        resp = api.create_energy_model(
            create_energy_model_payload(
                project["id"], stale_version, model_type="PROPOSED",
                annual_energy_cost_modeled_cents=11400000,
                annual_energy_cost_confirmed_only_cents=11400000),
            make_energy_modeler_headers(members["modeler"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION)
        assert baseline["version_index"] == 1
        data, meta = validate_paginated(
            api.list_energy_models(
                ANY, params={"project_id": project["id"], "model_type": "PROPOSED"}))
        assert meta["total_count"] == 0, "the stale create must not persist a model"


class TestStrategyCompletenessGates:
    def test_lock_strategy_with_zero_attempts_rejected(self, api):
        """PRD §3.2: "At least one attempt not in `DROPPED` must exist, otherwise `ERR_EMPTY_CREDIT_STRATEGY` (HTTP 422)."

        Design: Corner/validations/lock_strategy_empty_strategy_rejected
        """
        members = create_members()
        project = create_project(members["admin"]["id"], project_name="Empty Tower")
        resp = api.lock_strategy(
            project["id"], project["version"],
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_EMPTY_CREDIT_STRATEGY)

    def test_lock_strategy_missing_prerequisite_rejected(self, api):
        """PRD §3.2: "And every prerequisite catalog entry must have at least one attempt not in `DROPPED` on this project, otherwise `ERR_PREREQUISITE_CREDIT_MISSING` (HTTP 409)."

        Design: Corner/validations/lock_strategy_missing_prerequisite_blocked
        """
        members = create_members()
        _prereq_entry()
        regular = create_credit_entry(
            credit_code="WEc1", title="Water Efficiency", category="WATER",
            points_possible=2, is_prerequisite=False, phase_eligibility="DESIGN",
            requires_energy_model=False)
        project = create_project(members["admin"]["id"], project_name="Prereq Tower")
        create_attempt(
            project["id"], regular["id"], members["spec"]["id"], members["admin"]["id"])
        version = get_project(project["id"])["version"]

        resp = api.lock_strategy(
            project["id"], version,
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PREREQUISITE_CREDIT_MISSING)


class TestAttemptUniqueness:
    def test_duplicate_credit_attempt_rejected(self, api):
        """PRD §3.2: "And the project may hold at most one attempt per `credit_code` among attempts not yet dropped, otherwise `ERR_DUPLICATE_CREDIT_ATTEMPT` (HTTP 409)."

        Design: Corner/validations/create_duplicate_credit_attempt_rejected
        """
        members = create_members()
        entry = create_credit_entry(
            credit_code="WEc1", category="WATER", points_possible=2)
        project = create_project(members["admin"]["id"], project_name="Dup Tower")
        create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])

        resp = api.create_credit_attempt(
            {"project_id": project["id"], "credit_library_entry_id": entry["id"],
             "phase": "DESIGN", "documentation_owner_id": members["spec"]["id"]},
            make_project_administrator_headers(members["admin"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CREDIT_ATTEMPT)

    def test_re_add_dropped_credit_allowed(self, api):
        """PRD §3.2: "And the project may hold at most one attempt per `credit_code` among attempts not yet dropped, otherwise `ERR_DUPLICATE_CREDIT_ATTEMPT` (HTTP 409)."
        PRD §3.2: "An attempt that has not yet been submitted can be dropped from the strategy: from `SELECTED`, `DOCUMENTATION_IN_PROGRESS`, or `READY_FOR_SUBMITTAL`, dropping moves the attempt to `DROPPED`."

        Design: Corner/validations/re_add_dropped_credit_allowed
        """
        members = create_members()
        entry = create_credit_entry(
            credit_code="WEc1", category="WATER", points_possible=2)
        project = create_project(members["admin"]["id"], project_name="Readd Tower")
        old = create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        get_success_data(
            api.drop_attempt(
                old["id"], make_project_administrator_headers(members["admin"]["id"])))

        new = validate_success(
            api.create_credit_attempt(
                {"project_id": project["id"], "credit_library_entry_id": entry["id"],
                 "phase": "DESIGN", "documentation_owner_id": members["spec"]["id"]},
                make_project_administrator_headers(members["admin"]["id"])),
            201,
        )
        assert new["status"] == "SELECTED"
        assert new["id"] != old["id"]
        assert get_attempt(old["id"])["status"] == "DROPPED"


class TestOwnerSpecialty:
    def test_assign_owner_invalid_specialty_rejected(self, api):
        """PRD §3.2: "Assigning a documentation owner moves the attempt forward. From `SELECTED`, the assignment transitions the attempt `SELECTED → DOCUMENTATION_IN_PROGRESS`; performed while the attempt is already in `DOCUMENTATION_IN_PROGRESS`, the same operation simply replaces the owner and leaves the status unchanged. In both cases the new owner's `specialty` must be `DOCUMENTATION`, failing which the assignment is rejected with `ERR_INVALID_TEAM_MEMBER_SPECIALTY`."

        Design: Corner/validations/assign_owner_invalid_specialty_rejected
        """
        members = create_members()
        entry = create_credit_entry(
            credit_code="WEc1", category="WATER", points_possible=2)
        project = create_project(members["admin"]["id"], project_name="Specialty Tower")
        attempt = create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])

        resp = api.assign_owner(
            attempt["id"], members["modeler"]["id"],
            make_project_administrator_headers(members["admin"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_TEAM_MEMBER_SPECIALTY)
        assert get_attempt(attempt["id"])["status"] == "SELECTED"


class TestCreateDropCompensatingPair:
    def _setup(self, api):
        members = create_members()
        entry = create_credit_entry(
            credit_code="SSc1", title="Site Selection", category="SUSTAINABLE_SITES",
            points_possible=6, is_prerequisite=False, phase_eligibility="DESIGN",
            requires_energy_model=False)
        project = create_project(members["admin"]["id"], project_name="Tower Q")
        return members, entry, project

    def test_create_adds_points_to_pursued_total(self, api):
        """PRD §3.2: "Each creation recomputes the project's `points_pursued_total` — the sum of `points_possible` over every attempt not in `DROPPED` — and increments the project's `version` by one."

        Design: Difficulty/compensating_invariant/credit_create_drop_points_pool_conserved
        """
        members, entry, project = self._setup(api)
        assert project["points_pursued_total"] == 0

        attempt = create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        assert attempt["points_possible"] == 6

        after = get_project(project["id"])
        assert after["points_pursued_total"] == 6, (
            "creation adds the attempt's points_possible to the pursued total")

    def test_drop_restores_pursued_total(self, api):
        """PRD §3.2: "The drop recomputes `points_pursued_total` and increments the project's `version`; create and drop are exact compensating pairs, so selecting a credit and later dropping it leaves the pursued-points total precisely where it was."

        Design: Difficulty/compensating_invariant/credit_create_drop_points_pool_conserved
        """
        members, entry, project = self._setup(api)
        attempt = create_attempt(
            project["id"], entry["id"], members["spec"]["id"], members["admin"]["id"])
        assert get_project(project["id"])["points_pursued_total"] == 6

        dropped = validate_success(
            api.drop_attempt(
                attempt["id"], make_project_administrator_headers(members["admin"]["id"]))
        )
        assert dropped["status"] == "DROPPED"

        after = get_project(project["id"])
        assert after["points_pursued_total"] == 0, (
            "create + drop cancel exactly; the pursued-points pool is conserved")
