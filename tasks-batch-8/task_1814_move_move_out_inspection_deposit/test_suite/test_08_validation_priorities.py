"""Observable validation order: state beats temporal, referential beats
fiscal, and schema beats uniqueness (PRD §2.9 fixes the pipeline order)."""
import test_helpers as th
from test_helpers import (
    ApiErrorId,
    api_client,
    create_disbursement_payload,
    create_dispute_payload,
    create_jurisdiction,
    create_property,
    create_statement_for,
    create_tenancy,
    create_unit,
    get_statement,
    get_success_data,
    make_manager_admin_headers,
    make_property_manager_headers,
    make_tenant_headers,
    setup_issued_statement_with_damage,
    setup_settled_tenancy,
    validate_error,
    validate_success,
)

ADMIN = make_manager_admin_headers()
PM = make_property_manager_headers()


class TestStateBeatsTemporal:
    def test_dispute_on_settled_statement_after_window(self):
        """PRD §2.9: "fifth, state preconditions on the target resources (the
        state-guard errors such as `ERR_INVALID_STATE_TRANSITION` and
        `ERR_TENANCY_NOT_VACATED`); sixth, temporal business rules such as the
        dispute window (`ERR_DISPUTE_WINDOW_CLOSED`)". PRD §3.6: "The target
        statement must be `ISSUED` or `DISPUTED` (otherwise
        `ERR_STATEMENT_NOT_DISPUTABLE`)".

        The statement is SETTLED (not disputable) AND the 30-day window has
        closed; the state-category error ERR_STATEMENT_NOT_DISPUTABLE wins.

        Design: Difficulty/priority_pair_validation_conflict/dispute_state_beats_temporal
        """
        ctx = setup_settled_tenancy()
        stmt = ctx["statement"]
        assert stmt["status"] == "SETTLED"
        api_client.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, ADMIN)
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=stmt["id"],
                                   disputed_amount_cents=5_000,
                                   reason="too late and settled"),
            make_tenant_headers(ctx["tenancy"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_DISPUTABLE)

    def test_settled_statement_alone_is_not_disputable(self):
        """PRD §3.6: "The target statement must be `ISSUED` or `DISPUTED`
        (otherwise `ERR_STATEMENT_NOT_DISPUTABLE`)".

        Even inside the dispute window, a SETTLED statement rejects a dispute
        with the state-category error.

        Design: Difficulty/priority_pair_validation_conflict/dispute_state_beats_temporal
        """
        ctx = setup_settled_tenancy()
        stmt = ctx["statement"]
        api_client.set_clock({"to_iso8601": "2026-08-15T00:00:00Z"}, ADMIN)
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=stmt["id"],
                                   disputed_amount_cents=5_000,
                                   reason="settled already"),
            make_tenant_headers(ctx["tenancy"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_NOT_DISPUTABLE)


class TestReferentialBeatsFiscal:
    def _setup_superseded_statement(self):
        """S1 issued timely and disputed (20,000c); S2 created with the
        correct OCC version supersedes S1."""
        ctx = setup_issued_statement_with_damage()
        ten = ctx["tenancy"]
        resp = api_client.create_dispute(
            create_dispute_payload(statement_id=ctx["statement"]["id"],
                                   disputed_amount_cents=20_000,
                                   reason="paint wear"),
            make_tenant_headers(ten["id"]),
        )
        ctx["dispute"] = get_success_data(resp)
        ctx["statement2"] = create_statement_for(ten["id"])
        return ctx

    def test_superseded_statement_beats_over_balance_amount(self):
        """PRD §2.9: "seventh, referential-liveness rules such as
        current-statement and move-in-item linkage (`ERR_STATEMENT_SUPERSEDED`,
        `ERR_ITEM_LINK_MISMATCH`)" and "tenth, money-sanity limits
        (`ERR_AMOUNT_EXCEEDS_BALANCE` and its siblings)". PRD §3.7: "The
        referenced statement must be the tenancy's current statement — the one
        with the latest `statement_seq`, never a superseded one — or creation
        is rejected with `ERR_STATEMENT_SUPERSEDED`".

        The disbursement references superseded S1 AND exceeds the balance; the
        referential error wins.

        Design: Difficulty/priority_pair_validation_conflict/disbursement_referential_beats_fiscal
        """
        ctx = self._setup_superseded_statement()
        stmt1 = ctx["statement"]
        resp = api_client.create_disbursement(
            create_disbursement_payload(tenancy_id=ctx["tenancy"]["id"],
                                        statement_id=stmt1["id"],
                                        kind="REFUND", amount_cents=999_999),
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_STATEMENT_SUPERSEDED)

    def test_supersede_flips_statuses(self):
        """PRD §3.5: "Creating against a tenancy whose previous statement is
        `DISPUTED` is the deliberate create-with-supersede path: the
        predecessor flips to `SUPERSEDED`, any active dispute riding on it is
        withdrawn, and the new statement takes the next per-tenancy
        `statement_seq`".

        After the create-with-supersede: S1 SUPERSEDED, S2 DRAFT.

        Design: Difficulty/priority_pair_validation_conflict/disbursement_referential_beats_fiscal
        """
        ctx = self._setup_superseded_statement()
        assert get_statement(ctx["statement"]["id"])["status"] == "SUPERSEDED"
        stmt2 = get_statement(ctx["statement2"]["id"])
        assert stmt2["status"] == "DRAFT"
        assert stmt2["statement_seq"] == ctx["statement"]["statement_seq"] + 1


class TestSchemaBeatsConstraint:
    def test_invalid_body_beats_overlap(self):
        """PRD §2.9: "third, request-body schema — the body must parse and
        contain all required fields with well-typed, non-negative values, and
        this schema check deliberately precedes any identifier resolution
        (`ERR_INVALID_REQUEST`)" and "eighth, uniqueness and scheduling
        constraints (for example `ERR_UNIT_OCCUPANCY_OVERLAP` and
        `ERR_INSPECTOR_SCHEDULE_CONFLICT`)". PRD §3.2: "any genuine overlap is
        rejected with `ERR_UNIT_OCCUPANCY_OVERLAP`".

        A tenancy create that is both schema-invalid (missing deposit_cents)
        and lease-overlapping surfaces ERR_INVALID_REQUEST; the unit still has
        exactly one tenancy.

        Design: Corner/errors/schema_error_beats_overlap_constraint
        """
        jur = create_jurisdiction(interest_required=False, annual_interest_rate_bp=0)
        prop = create_property(jur["id"])
        unit = create_unit(prop["id"])
        create_tenancy(unit["id"], tenant_display_name="T One",
                       lease_start_on="2026-01-01", lease_end_on="2027-01-01")
        resp = api_client.create_tenancy(
            {"unit_id": unit["id"], "tenant_display_name": "T Two",
             "lease_start_on": "2026-06-01", "lease_end_on": "2027-06-01",
             "monthly_rent_cents": 150_000, "keys_issued": 2, "fobs_issued": 1},
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        data = get_success_data(api_client.list_tenancies(
            PM, params={"unit_id": unit["id"], "limit": 100}))
        rows = data if isinstance(data, list) else data.get("data", [])
        assert len(rows) == 1
