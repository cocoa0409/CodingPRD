"""Optimistic concurrency control on statement creation (PRD §2.8)."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    create_statement_payload,
    get_success_data,
    get_tenancy,
    make_manager_admin_headers,
    make_property_manager_headers,
    setup_vacated_tenancy,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestStatementCreateOcc:
    def test_stale_version_rejected(self):
        """PRD §2.8: "The request must carry `expected_tenancy_version`,
        holding the `version` of the target tenancy as the client last
        observed it. If the tenancy's current `version` no longer matches —
        because another writer has advanced it since the client last read it —
        the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
        the client from building a statement on top of state it has not
        observed."

        expected_tenancy_version one behind the observed version fails 412;
        no statement is created.

        Design: Corner/complexity_layers/occ_stale_version_rejected
        """
        ctx = setup_vacated_tenancy()
        ten = get_tenancy(ctx["tenancy"]["id"])
        assert ten["version"] >= 1
        resp = api_client.create_statement(
            create_statement_payload(tenancy_id=ten["id"],
                                     expected_tenancy_version=ten["version"] - 1),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        data = get_success_data(api_client.list_statements(
            PM, params={"tenancy_id": ten["id"], "limit": 100}))
        rows = data if isinstance(data, list) else data.get("data", [])
        assert rows == []

    def test_current_version_succeeds_and_replay_fails(self):
        """PRD §2.8: "A successful statement creation itself increments the
        tenancy's `version`, so a second create carrying the previously
        observed value is necessarily working from stale state and must fail."
        PRD §3.5: "the new statement takes the next per-tenancy
        `statement_seq` (the sequence starts at one and increments per
        tenancy, providing the ordering key for supersession and for
        identifying the current statement). A new statement is born in `DRAFT`".

        Create with the fresh version succeeds (201, seq 1, DRAFT) and bumps
        the tenancy version by exactly 1; replaying with the old version
        fails 412.

        Design: Corner/complexity_layers/occ_current_version_succeeds_and_bumps
        """
        ctx = setup_vacated_tenancy()
        ten = get_tenancy(ctx["tenancy"]["id"])
        resp = api_client.create_statement(
            create_statement_payload(tenancy_id=ten["id"],
                                     expected_tenancy_version=ten["version"]),
            PM,
        )
        stmt = validate_success(resp, expected_status=201)
        assert stmt["statement_seq"] == 1
        assert stmt["status"] == "DRAFT"
        ten_after = get_tenancy(ten["id"])
        assert ten_after["version"] == ten["version"] + 1, (
            f"creation must bump the tenancy version by 1: "
            f"{ten['version']} -> {ten_after['version']}"
        )
        replay = api_client.create_statement(
            create_statement_payload(tenancy_id=ten["id"],
                                     expected_tenancy_version=ten["version"]),
            PM,
        )
        validate_error(replay, ApiErrorId.ERR_STALE_VERSION)
