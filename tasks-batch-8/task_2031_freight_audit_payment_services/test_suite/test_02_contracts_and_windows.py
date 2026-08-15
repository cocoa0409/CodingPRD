"""Rate-contract windows, activation guards, OCC, and the supersede cascade.

Covers PRD §3.2 half-open window semantics and activation rules, the §2.8
evaluation order between temporal and structural checks, §2.9 optimistic
concurrency on activation, and the §3.2 three-hop supersede/re-rate cascade.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    create_active_carrier,
    create_active_client,
    create_contract,
    create_invoice,
    create_shipment,
    get_invoice,
    set_clock,
    setup_standard_chain,
    capture_invoice,
    finalize_invoice,
    first_exception,
    rate_invoice,
    validate_error,
    validate_success,
)


def _ltl_lane(rate_per_kg=150, breaks=None):
    return {
        "origin_country": "US",
        "dest_country": "CA",
        "mode": "LTL",
        "weight_breaks": breaks if breaks is not None else [
            {"min_kg": 0, "rate_per_kg_minor": rate_per_kg}
        ],
        "fuel_surcharge_pct_bp": 1000,
        "accessorials": [{"code": "LIFTGATE", "flat_minor": 5000, "cap_pct_bp": 2000}],
        "minimum_charge_minor": 20000,
    }


class TestHalfOpenWindowAdjacency:
    def test_adjacent_successor_at_effective_to_activates(self, api):
        """PRD §3.2: "The draft carries a `name`, the `currency` every lane rate
        is denominated in, a half-open validity window running from
        `effective_from` (inclusive) to `effective_to` (exclusive), an optional
        `supersedes_contract_id` declaring which currently `ACTIVE` contract
        this one replaces upon activation, and the `lanes` array." A successor
        starting exactly at the incumbent's `effective_to` shares no covered
        date, so the half-open windows do not intersect and activation succeeds.

        Design: Difficulty/resource_temporal_overlap/contract_window_half_open_adjacency
        """
        chain = setup_standard_chain(lanes=[_ltl_lane()])
        successor = create_contract(
            chain["carrier"]["id"],
            lanes=[_ltl_lane(rate_per_kg=140)],
            name="C5",
            effective_from="2026-12-31",
            effective_to="2027-06-01",
        )
        res = api.activate_rate_contract(
            successor["id"], {"expected_rate_contract_version": successor["version"]}, ADMIN
        )
        activated = validate_success(res, 200)
        assert activated["status"] == "ACTIVE"
        incumbent = validate_success(api.get_rate_contract(chain["contract"]["id"], ADMIN))
        assert incumbent["status"] == "ACTIVE"

    def test_successor_one_day_before_effective_to_overlaps(self, api):
        """PRD §3.2: "the overlap rule rejects activation with
        `ERR_CONTRACT_WINDOW_OVERLAP` when the contract's half-open window would
        intersect another `ACTIVE` contract of the same carrier that covers an
        intersecting lane, unless that other contract is the declared supersedes
        target".

        Design: Difficulty/resource_temporal_overlap/contract_window_half_open_adjacency
        """
        chain = setup_standard_chain(lanes=[_ltl_lane()])
        overlapping = create_contract(
            chain["carrier"]["id"],
            lanes=[_ltl_lane(rate_per_kg=140)],
            name="C6",
            effective_from="2026-12-30",
            effective_to="2027-06-01",
        )
        res = api.activate_rate_contract(
            overlapping["id"],
            {"expected_rate_contract_version": overlapping["version"]},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP, expected_status=409)


class TestTemporalMasksStructural:
    def test_overlap_reported_before_weight_break_ordering(self, api):
        """PRD §2.8: "Every request passes through a fixed evaluation pipeline,
        and a failure at any stage short-circuits the stages after it — when
        several rules would independently reject the same request, the earliest
        stage's error is the one reported." Temporal window checks (stage 8:
        `ERR_CONTRACT_WINDOW_OVERLAP`) precede structural uniqueness checks
        (stage 9: `ERR_WEIGHT_BREAK_INVALID`).

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_contract_activate_rejected
        """
        chain = setup_standard_chain(lanes=[_ltl_lane()])
        bad = create_contract(
            chain["carrier"]["id"],
            lanes=[_ltl_lane(breaks=[
                {"min_kg": 1000, "rate_per_kg_minor": 120},
                {"min_kg": 0, "rate_per_kg_minor": 150},
            ])],
            name="C7",
            effective_from="2026-09-01",
            effective_to="2026-11-01",
        )
        res = api.activate_rate_contract(
            bad["id"], {"expected_rate_contract_version": bad["version"]}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_WINDOW_OVERLAP, expected_status=409)

    def test_supersedes_target_exempt_lets_weight_break_rule_report(self, api):
        """PRD §3.2: "the overlap rule rejects activation with
        `ERR_CONTRACT_WINDOW_OVERLAP` when the contract's half-open window would
        intersect another `ACTIVE` contract of the same carrier that covers an
        intersecting lane, unless that other contract is the declared supersedes
        target; and every lane's `weight_breaks` must be strictly ascending by
        `min_kg` (`ERR_WEIGHT_BREAK_INVALID`)." With the incumbent named as the
        supersedes target, the temporal check passes and the structural rule is
        the one reported.

        Design: Difficulty/priority_pair_validation_conflict/temporal_vs_constraint_on_contract_activate_rejected
        """
        chain = setup_standard_chain(lanes=[_ltl_lane()])
        bad = create_contract(
            chain["carrier"]["id"],
            lanes=[_ltl_lane(breaks=[
                {"min_kg": 1000, "rate_per_kg_minor": 120},
                {"min_kg": 0, "rate_per_kg_minor": 150},
            ])],
            name="C8",
            effective_from="2026-09-01",
            effective_to="2026-11-01",
            supersedes_contract_id=chain["contract"]["id"],
        )
        res = api.activate_rate_contract(
            bad["id"], {"expected_rate_contract_version": bad["version"]}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_WEIGHT_BREAK_INVALID, expected_status=422)


class TestSupersedeRerateCascade:
    """Activation of a superseding contract cascades: predecessor SUPERSEDED,
    invoices re-rated, open RATE_MISMATCH exceptions re-evaluated."""

    def _setup(self, api):
        chain = setup_standard_chain(lanes=[_ltl_lane()])
        client_id = chain["client"]["id"]
        carrier_id = chain["carrier"]["id"]
        # Exception invoice: billed 60400 vs rated 87500 -> RATE_MISMATCH.
        sh_e = create_shipment(client_id, carrier_id, pro_number="PRO-1006")
        inv_e = create_invoice(
            client_id,
            carrier_id,
            invoice_number="INV-0006",
            shipment_id=sh_e["id"],
            billed_total_minor=60400,
            lines=[
                {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 45400},
                {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 10000},
                {"charge_code": "LIFTGATE", "billed_amount_minor": 5000},
            ],
        )
        capture_invoice(inv_e["id"])
        rate_invoice(inv_e["id"])
        finalize_invoice(inv_e["id"])
        exception = first_exception(inv_e["id"])
        assert exception["code"] == "RATE_MISMATCH"
        # Plain RATED invoice (never finalized).
        sh_r = create_shipment(client_id, carrier_id, pro_number="PRO-1007")
        inv_r = create_invoice(
            client_id, carrier_id, invoice_number="INV-0007", shipment_id=sh_r["id"]
        )
        capture_invoice(inv_r["id"])
        rate_invoice(inv_r["id"])
        # Successor contract at 100/kg superseding the incumbent.
        successor = create_contract(
            carrier_id,
            lanes=[_ltl_lane(rate_per_kg=100)],
            name="C2",
            effective_from="2026-08-10",
            effective_to="2026-12-31",
            supersedes_contract_id=chain["contract"]["id"],
        )
        res = api.activate_rate_contract(
            successor["id"], {"expected_rate_contract_version": successor["version"]}, ADMIN
        )
        validate_success(res, 200)
        return chain, inv_e, exception, inv_r, successor

    def test_supersede_moves_predecessor_and_rerates_rated_invoice(self, api):
        """PRD §3.2: "Hop one: the named contract moves from `ACTIVE` to
        `SUPERSEDED`. Hop two: every carrier invoice whose `rated_contract_id`
        points at the superseded contract and whose `audit_status` is `RATED` or
        `EXCEPTION` is re-rated against the newly active contract — line rating
        recomputes each line's `rated_amount_minor` and the invoice's
        `rated_total_minor`, `variance_minor`, and `variance_pct_bp`, and
        `rated_contract_id` is updated to the new contract."

        The 100/kg successor rates the 500 kg fixture at 50000 + 5000 fuel +
        5000 LIFTGATE = 60000.

        Design: Difficulty/transitive_cascade/contract_activation_supersede_rerate_autoresolve_cascade
        """
        chain, _inv_e, _exc, inv_r, successor = self._setup(api)
        predecessor = validate_success(api.get_rate_contract(chain["contract"]["id"], ADMIN))
        assert predecessor["status"] == "SUPERSEDED"
        rerated = get_invoice(inv_r["id"])
        assert rerated["rated_total_minor"] == 60000
        assert rerated["rated_contract_id"] == successor["id"]

    def test_open_rate_mismatch_autoresolves_when_variance_within_tolerance(self, api):
        """PRD §3.2: "Hop three: every audit exception in `OPEN`,
        `CARRIER_NOTIFIED`, or `CARRIER_RESPONDED` with code `RATE_MISMATCH` on
        one of those re-rated invoices is re-evaluated against the client's
        tolerances; when the new absolute variance is within
        `audit_tolerance_minor` and the new `variance_pct_bp` is within
        `audit_tolerance_pct_bp`, the exception auto-transitions to
        `RESOLVED_ACCEPTED` with `resolution_credit_minor` set to its
        `disputed_amount_minor`, and the invoice's `approved_amount_minor` is
        pinned to the new `rated_total_minor`."

        Re-rated at 60000, the 60400 invoice's variance is 400 <= 500, so its
        exception auto-resolves (its disputed amount was 0: the original
        variance was negative) and approved pins to 60000.

        Design: Difficulty/transitive_cascade/contract_activation_supersede_rerate_autoresolve_cascade
        """
        _chain, inv_e, exception, _inv_r, _successor = self._setup(api)
        assert exception["disputed_amount_minor"] == 0
        exceptions = validate_success(api.list_invoice_exceptions(inv_e["id"], ANALYST))
        resolved = [e for e in exceptions if e["id"] == exception["id"]][0]
        assert resolved["status"] == "RESOLVED_ACCEPTED"
        assert resolved["resolution_credit_minor"] == 0
        rerated = get_invoice(inv_e["id"])
        assert rerated["rated_total_minor"] == 60000
        assert rerated["approved_amount_minor"] == 60000


class TestActivationGuards:
    def test_inverted_window_rejected_at_create(self, api):
        """PRD §3.2: "the window sanity rule then requires `effective_from`
        strictly earlier than `effective_to` (`ERR_CONTRACT_WINDOW_INVALID`) —
        the same sanity rule is also enforced when the draft is first created".

        An empty half-open window (from == to) is rejected at creation.

        Design: Corner/validations/contract_window_inverted_rejected
        """
        set_clock()
        client = create_active_client()
        carrier = create_active_carrier(client["id"])
        res = api.create_rate_contract(
            carrier["id"],
            {
                "name": "CBAD",
                "currency": "USD",
                "lanes": [_ltl_lane()],
                "effective_from": "2026-09-01",
                "effective_to": "2026-09-01",
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID, expected_status=422)

    def test_descending_weight_breaks_rejected_at_activate(self, api):
        """PRD §3.2: "every lane's `weight_breaks` must be strictly ascending
        by `min_kg` (`ERR_WEIGHT_BREAK_INVALID`)".

        With no overlapping contract in play, the structural rule fires alone.

        Design: Corner/validations/weight_break_unordered_rejected
        """
        set_clock()
        client = create_active_client()
        carrier = create_active_carrier(client["id"])
        contract = create_contract(
            carrier["id"],
            lanes=[_ltl_lane(breaks=[
                {"min_kg": 1000, "rate_per_kg_minor": 120},
                {"min_kg": 0, "rate_per_kg_minor": 150},
            ])],
            name="CBAD2",
        )
        res = api.activate_rate_contract(
            contract["id"], {"expected_rate_contract_version": contract["version"]}, ADMIN
        )
        validate_error(res, ApiErrorId.ERR_WEIGHT_BREAK_INVALID, expected_status=422)

    def test_second_activate_with_stale_version_rejected(self, api):
        """PRD §2.9: "Activating a rate contract (`POST
        /fap/rate-contracts/{id}/activate`) requires the request to carry
        `expected_rate_contract_version`, the caller's last observed `version`
        of the contract; if the contract's current `version` no longer matches —
        activation both bumps the version and may unleash the supersede and
        re-rating cascade, so a writer holding an older observed version is
        acting on stale state — the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412)." PRD §2.8: "On the version-guarded writes (see §2.9), the
        supplied expected version must match the parent entity's current
        `version`; a mismatch yields `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_contract_activate_returns_412
        """
        set_clock()
        client = create_active_client()
        carrier = create_active_carrier(client["id"])
        contract = create_contract(carrier["id"], lanes=[_ltl_lane()], name="C1")
        payload = {"expected_rate_contract_version": contract["version"]}
        validate_success(api.activate_rate_contract(contract["id"], payload, ADMIN), 200)
        res = api.activate_rate_contract(contract["id"], payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
