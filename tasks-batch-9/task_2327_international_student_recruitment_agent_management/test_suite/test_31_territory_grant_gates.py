"""What a country grant is allowed to be, and how many may share it.

Exclusivity depends on how the contract was configured, capacity depends on the
whole country rather than the single request, and a free country accepts the
exclusive grant and then reports its own shadow.
"""

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_occupancy
from test_helpers.test_users import OFFICER


class TestExclusiveGrantNeedsAPermissiveContract:
    @pytest.fixture()
    def two_contract_models(self, client):
        """One contract restricted to shared grants, one permitting exclusivity."""
        restricted_agency = fx.register_agency(
            client, legal_name="Shared Only Agency", complete_diligence=False
        )
        restricted = fx.draft_contract(
            client,
            restricted_agency["id"],
            contract_ref="CTR-001",
            exclusivity_model=C.EXCLUSIVITY_NON_EXCLUSIVE_ONLY,
        )
        permissive_agency = fx.register_agency(
            client, legal_name="Exclusive Capable Agency", complete_diligence=False
        )
        permissive = fx.draft_contract(
            client,
            permissive_agency["id"],
            contract_ref="CTR-002",
            exclusivity_model=C.EXCLUSIVITY_EXCLUSIVE_ALLOWED,
        )
        return {
            "restricted_id": restricted["id"],
            "permissive_id": permissive["id"],
        }

    def test_the_rule_fires_only_on_the_restricted_contract(
        self, client, two_contract_models
    ):
        """The same body is refused on one contract and accepted on the other.

        "An `EXCLUSIVE` request is permitted only when the contract's
        `exclusivity_model` is `EXCLUSIVE_ALLOWED`; on a `NON_EXCLUSIVE_ONLY`
        contract it is refused with `ERR_EXCLUSIVITY_NOT_PERMITTED`."

        "The assignment is created in `ACTIVE` with `released_on` unset."

        Design: Corner/validations/exclusive_assignment_requires_permissive_contract_model
        """
        env = two_contract_models

        refused = client.assign_territory(
            env["restricted_id"],
            F.territory_payload("IN", C.TERRITORY_EXCLUSIVE, "2026-08-01", "2027-07-31"),
            OFFICER,
        )
        validate_error(refused, E.ERR_EXCLUSIVITY_NOT_PERMITTED, 422)

        shared = fx.assign_territory(
            client,
            env["restricted_id"],
            country_code="IN",
            exclusivity=C.TERRITORY_NON_EXCLUSIVE,
            start_date="2026-08-01",
            end_date="2027-07-31",
        )
        assert shared["exclusivity"] == C.TERRITORY_NON_EXCLUSIVE
        assert shared["status"] == C.ASSIGNMENT_ACTIVE

        exclusive = fx.assign_territory(
            client,
            env["permissive_id"],
            country_code="VN",
            exclusivity=C.TERRITORY_EXCLUSIVE,
            start_date="2026-08-01",
            end_date="2027-07-31",
        )
        assert exclusive["exclusivity"] == C.TERRITORY_EXCLUSIVE
        assert exclusive["status"] == C.ASSIGNMENT_ACTIVE


class TestSharedCapacityIsCountedAcrossTheCountry:
    def test_the_third_shared_grant_is_the_last_one_the_country_accepts(self, client):
        """Every request is legal alone; the fourth is refused for the aggregate.

        "The capacity gate says that at every instant of the requested interval the
        number of `ACTIVE` `NON_EXCLUSIVE` assignments for that country must remain at
        most three, so a request that would create a fourth concurrent non-exclusive
        occupant at any instant is `ERR_TERRITORY_CAPACITY_EXCEEDED`."

        "`exclusive_slot_available`, which is true exactly when
        `exclusive_active_count` is zero, `non_exclusive_active_count` is zero, and
        either `exclusive_cooloff_until` is null or the requested instant falls at or
        after it."

        Design: Corner/validations/non_exclusive_capacity_boundary_is_aggregate
        """
        contract_ids = []
        for index in range(1, 5):
            agency = fx.register_agency(
                client,
                legal_name=f"Shared Country Agency {index}",
                complete_diligence=False,
            )
            contract = fx.draft_contract(
                client,
                agency["id"],
                contract_ref=f"CTR-00{index}",
                exclusivity_model=C.EXCLUSIVITY_NON_EXCLUSIVE_ONLY,
            )
            contract_ids.append(contract["id"])

        for contract_id in contract_ids[:3]:
            granted = fx.assign_territory(
                client,
                contract_id,
                country_code="IN",
                exclusivity=C.TERRITORY_NON_EXCLUSIVE,
                start_date="2026-08-01",
                end_date="2027-07-31",
            )
            assert granted["status"] == C.ASSIGNMENT_ACTIVE

        fourth = client.assign_territory(
            contract_ids[3],
            F.territory_payload(
                "IN", C.TERRITORY_NON_EXCLUSIVE, "2026-08-01", "2027-07-31"
            ),
            OFFICER,
        )
        validate_error(fourth, E.ERR_TERRITORY_CAPACITY_EXCEEDED, 409)

        assert_occupancy(
            fx.read_occupancy(client, "IN", "2026-09-01"),
            country_code="IN",
            at_date="2026-09-01",
            exclusive_active_count=0,
            non_exclusive_active_count=3,
            exclusive_cooloff_until=None,
            exclusive_slot_available=False,
        )


class TestAFreeCountryAcceptsTheExclusiveGrant:
    def test_the_accepted_grant_occupies_the_country_and_casts_its_shadow(self, client):
        """Nothing overlaps, so the gate passes and the read shows the buffer.

        "The exclusivity gate says that an `EXCLUSIVE` request requires zero `ACTIVE`
        assignments of either kind overlapping its interval and no `EXCLUSIVE`
        cool-off shadow reaching into that interval"

        "`exclusive_cooloff_until` — the latest cool-off end among the country's
        `ACTIVE` `EXCLUSIVE` assignments, or null when there are none"

        "An `EXCLUSIVE` assignment additionally casts a **cool-off shadow**: its
        shadow ends 30 days after its `end_date`"

        Design: Corner/validations/exclusive_assignment_passes_when_country_is_free
        """
        agency = fx.register_agency(
            client, legal_name="Open Country Agency", complete_diligence=False
        )
        contract = fx.draft_contract(client, agency["id"], contract_ref="CTR-001")

        granted = validate_success(
            client.assign_territory(
                contract["id"],
                F.territory_payload(
                    "VN", C.TERRITORY_EXCLUSIVE, "2026-08-01", "2026-12-31"
                ),
                OFFICER,
            ),
            201,
        )
        assert granted["status"] == C.ASSIGNMENT_ACTIVE
        assert granted["released_on"] is None

        assert_occupancy(
            fx.read_occupancy(client, "VN", "2026-09-01"),
            country_code="VN",
            at_date="2026-09-01",
            exclusive_active_count=1,
            non_exclusive_active_count=0,
            exclusive_cooloff_until="2027-01-30",
            exclusive_slot_available=False,
        )
